"""Scientific-review state transitions with tiny local execution receipts, no simulation."""
import copy
import json
from pathlib import Path
import sys

import pytest

from ravel.workflow import execution, physics_review as review, waypoint_evidence as waypoint, workflow_state
from ravel.workflow.state_io import atomic_json, read_json


def policy():
    return {"schema_version": 1,
        "actors": {"proposer": "worker", "executor": "worker", "physics_decider": "physicist", "skeptical_verifier": "skeptic", "physics_critic": "critic"},
        "max_redos": 2, "allowed_changed_paths": ["inputs/settings.cfg"], "allowed_stages": ["detector"],
        "required_checks": [{"id": "integrity", "kind": "integrity"}, {"id": "agreement", "kind": "scientific"}],
        "claim_scopes": {"diagnostic": {"checks": ["integrity"], "actions": ["delivery"]},
            "reproduction": {"checks": ["integrity", "agreement"], "actions": ["bulk", "delivery", "reuse"]}}}


def make_attempt(root, *, value=1, extra_inputs=()):
    # A deliberately small execution receipt avoids binding concurrently edited
    # development source files; execution's package-hashing tests live elsewhere.
    inputs = ["inputs/settings.cfg", "inputs/held-fixed.txt", *extra_inputs]
    spec = {"command": [sys.executable, "-c", "pass"], "cwd": str(root.resolve()),
        "inputs": inputs, "outputs": ["outputs/produced.json"], "input_snapshot": execution.snapshot(root, inputs),
        "parents": {}, "runtime": execution.runtime_context()}
    spec["fingerprint"] = execution.digest(spec)
    record = execution.begin_attempt(root, "detector", spec, "logs/detector.log")
    atomic_json(root / "outputs/produced.json", {"value": value})
    (root / "logs/detector.log").write_text(f"generated value {value}\n")
    assert execution.finish_attempt(root, record, 0) == 0
    return record


def check_packet(root, record, *, agreement="pass", integrity="pass"):
    atomic_json(root / "inputs/comparison.json", {"status": "pass" if agreement == "pass" else "fail",
        "summary": "Declared comparison", "diagnostics": {"residual": 0 if agreement == "pass" else .2}})
    manifest = waypoint.create(root, produced="outputs/produced.json", reference="inputs/reference.json",
        comparison="inputs/comparison.json", inputs=["inputs/settings.cfg"])
    atomic_json(root / waypoint.MANIFEST, manifest)
    atomic_json(root / "inputs/checkin2.json", {"sections": {"evidence_manifest": waypoint.MANIFEST}})
    atomic_json(root / "inputs/checks.json", {"schema_version": 1, "checks": [
        {"id": cid, "status": status, "evidence": [{"path": "outputs/produced.json", "location": "$.value"}],
         "attempt_ids": [record["attempt_id"]]} for cid, status in (("integrity", integrity), ("agreement", agreement))]})


@pytest.fixture
def run(tmp_path, monkeypatch):
    root = tmp_path / "run"
    (root / "inputs").mkdir(parents=True)
    atomic_json(root / review.POLICY, policy())
    atomic_json(root / "inputs/checkin1_approval.json", {"fixture": "approval verifier is an independently tested boundary"})
    # Keep unit controls independent of integration changes to approval schemas.
    monkeypatch.setattr(workflow_state, "approval_input_paths", lambda rd: [str(Path(rd) / review.POLICY)])
    monkeypatch.setattr(workflow_state, "verify_approval", lambda *a, **kw: [])
    (root / "inputs/settings.cfg").write_text("efficiency=0.8\n")
    (root / "inputs/held-fixed.txt").write_text("fixed recipe\n")
    atomic_json(root / "inputs/reference.json", {"reference": 1})
    record = make_attempt(root)
    check_packet(root, record)
    return root, record


def opened(run, **kwargs):
    root, record = run
    return review.open_cycle(root, effective_settings=["inputs/settings.cfg"],
        stage_receipts=[record["attempt_record"]], check_results="inputs/checks.json", **kwargs)


def accept(root, *, scope="reproduction", closes=()):
    for role, actor in (("physics_critic", "critic"), ("skeptical_verifier", "skeptic"), ("physics_decider", "physicist")):
        review.submit_review(root, role=role, actor_id=actor, verdict="accept", summary="Evidence supports the stated scope",
            claim_scope=scope, closes=list(closes))


def finding(name="F1", paths=None):
    return {"id": name, "summary": "The setting needs the declared correction",
        "evidence": [{"path": "outputs/produced.json", "location": "$.value"}],
        "check_ids": ["agreement"], "required_paths": ["inputs/settings.cfg"] if paths is None else paths,
        "required_stages": ["detector"]}


def reject(root, name="F1", paths=None):
    return review.submit_review(root, role="physics_decider", actor_id="physicist", verdict="send_back",
        summary="Send back for a controlled correction", findings=[finding(name, paths)])


def correct(root):
    (root / "inputs/settings.cfg").write_text("efficiency=0.85\n")
    return review.authorize_correction(root, actor_id="physicist", changed_paths=["inputs/settings.cfg"],
        stages=["detector"], recheck_checks=["agreement"])


def test_acceptance_requires_both_distinct_reviewers_and_traceable_checks(run):
    root, _ = run
    opened(run)
    assert review.gate_errors(root, "bulk")
    review.submit_review(root, role="physics_decider", actor_id="physicist", verdict="accept",
        summary="Supported", claim_scope="reproduction")
    assert review.gate_errors(root, "bulk")
    review.submit_review(root, role="skeptical_verifier", actor_id="skeptic", verdict="accept",
        summary="Independently checked", claim_scope="reproduction")
    assert review.gate_errors(root, "bulk")
    review.submit_review(root, role="physics_critic", actor_id="critic", verdict="accept",
        summary="Critical examination complete", claim_scope="reproduction")
    assert review.gate_errors(root, "bulk") == []
    assert review.gate_errors(root, "delivery") == []
    assert review.status(root)["claim_scope"] == "reproduction"
    assert "not authenticated" in review.status(root)["attestation"]


def empty_input_attempt(run, monkeypatch, *, approved=False):
    root, _ = run
    empty = root / "inputs/empty-runtime.py"
    empty.write_bytes(b"")
    if approved:
        monkeypatch.setattr(workflow_state, "approval_input_paths",
                            lambda rd: [str(Path(rd) / review.POLICY), str(empty)])
    record = make_attempt(root, extra_inputs=[str(empty)])
    check_packet(root, record)
    return root, record, empty


@pytest.mark.parametrize("approved", [False, True])
def test_bound_empty_input_survives_review_snapshot_acceptance_and_reuse(run, monkeypatch, approved):
    root, record, empty = empty_input_attempt(run, monkeypatch, approved=approved)
    cycle = review.open_cycle(root, effective_settings=["inputs/settings.cfg"],
                             stage_receipts=[record["attempt_record"]], check_results="inputs/checks.json")
    pin = next(p for p in cycle["snapshots"] if p["path"] == "inputs/empty-runtime.py")
    assert pin["size"] == 0 and pin["content_retained"] is True
    blob = root / pin["snapshot"]
    assert blob.read_bytes() == b"" and execution.file_hash(blob) == pin["sha256"]
    accept(root)
    assert review.gate_errors(root, "reuse") == []
    assert review.validate_snapshot(review.snapshot(root, action="reuse")) == []
    assert str(empty) in review.bound_paths(root) and str(blob) in review.bound_paths(root)


@pytest.mark.parametrize("defect", ["cited_scientific", "effective_settings", "check_results", "unbound_snapshot"])
def test_empty_input_permission_does_not_allow_empty_review_evidence(run, monkeypatch, defect):
    root, record, empty = empty_input_attempt(run, monkeypatch)
    settings, checked = ["inputs/settings.cfg"], "inputs/checks.json"
    if defect == "cited_scientific":
        checks = read_json(root / checked)
        checks["checks"][1]["evidence"] = [{"path": str(empty), "location": "$"}]
        atomic_json(root / checked, checks)
    elif defect == "effective_settings":
        settings = [str(empty)]
    elif defect == "check_results":
        checked = str(empty)
    else:
        with pytest.raises(ValueError, match="missing or empty"):
            review._snapshots(root, ["inputs/empty-runtime.py"], "unbound")
        return
    with pytest.raises(ValueError, match="missing or empty"):
        review.open_cycle(root, effective_settings=settings,
                          stage_receipts=[record["attempt_record"]], check_results=checked)
    assert not review.registered(root)


@pytest.mark.parametrize("defect", ["input_before_open", "input_after_acceptance", "frozen_blob"])
def test_empty_input_hash_and_zero_byte_snapshot_still_detect_drift(run, monkeypatch, defect):
    root, record, empty = empty_input_attempt(run, monkeypatch)
    if defect == "input_before_open":
        empty.write_bytes(b"changed after successful execution")
        with pytest.raises(ValueError, match="stage receipt invalid"):
            review.open_cycle(root, effective_settings=["inputs/settings.cfg"],
                              stage_receipts=[record["attempt_record"]], check_results="inputs/checks.json")
        assert not review.registered(root)
        return
    cycle = review.open_cycle(root, effective_settings=["inputs/settings.cfg"],
                              stage_receipts=[record["attempt_record"]], check_results="inputs/checks.json")
    accept(root)
    if defect == "frozen_blob":
        pin = next(p for p in cycle["snapshots"] if p["size"] == 0)
        (root / pin["snapshot"]).write_bytes(b"changed frozen input")
    else:
        empty.write_bytes(b"changed after acceptance")
    assert review.gate_errors(root, "reuse")


def test_empty_input_remains_bound_through_controlled_correction(run, monkeypatch):
    root, record, empty = empty_input_attempt(run, monkeypatch)
    review.open_cycle(root, effective_settings=["inputs/settings.cfg"],
                      stage_receipts=[record["attempt_record"]], check_results="inputs/checks.json")
    reject(root)
    admission = correct(root)
    assert next(p for p in admission["snapshots"] if p["path"] == "inputs/empty-runtime.py")["size"] == 0
    assert review.admitted_correction(root)["correction_id"] == admission["correction_id"]
    assert review.gate_errors(root, "correction", "detector") == []
    empty.write_bytes(b"changed held-fixed runtime input")
    assert review.gate_errors(root, "correction", "detector")


def test_empty_input_cannot_be_relabelled_as_scientific_evidence_in_detached_review(run, monkeypatch):
    root, record, _ = empty_input_attempt(run, monkeypatch)
    review.open_cycle(root, effective_settings=["inputs/settings.cfg"],
                      stage_receipts=[record["attempt_record"]], check_results="inputs/checks.json")
    accept(root)
    saved = review.snapshot(root, action="reuse")
    saved["events"][0]["checks"][1]["evidence"][0]["path"] = "inputs/empty-runtime.py"
    previous = saved["registration"]["sha256"]
    for event in saved["events"]:
        event["previous_sha256"] = previous
        event["sha256"] = execution.digest({k: v for k, v in event.items() if k != "sha256"})
        previous = event["sha256"]
    saved["checkpoint"]["sha256"] = previous
    assert "empty review evidence is not a bound input" in review.validate_snapshot(saved)[0]


@pytest.mark.parametrize("change", ["same_reviewers", "self_review", "bool_budget", "unknown", "duplicate_check", "no_integrity", "bad_path"])
def test_policy_is_strict_and_has_no_implicit_grants(change):
    p = policy()
    if change == "same_reviewers": p["actors"]["skeptical_verifier"] = "physicist"
    if change == "self_review": p["actors"]["physics_decider"] = "worker"
    if change == "bool_budget": p["max_redos"] = True
    if change == "unknown": p["unlimited"] = True
    if change == "duplicate_check": p["required_checks"].append(p["required_checks"][0])
    if change == "no_integrity": p["required_checks"][0]["kind"] = "scientific"
    if change == "bad_path": p["allowed_changed_paths"] = ["../settings.cfg"]
    assert review.validate_policy(p)


def test_policy_must_be_bound_prospectively_into_approval(run, monkeypatch):
    root, _ = run
    monkeypatch.setattr(workflow_state, "approval_input_paths", lambda rd: [])
    with pytest.raises(ValueError, match="prospectively"):
        opened(run)
    assert not (root / review.REGISTRATION).exists()


def test_diagnostic_failure_is_valid_evidence_but_not_reproduction(run):
    root, record = run
    check_packet(root, record, agreement="fail")
    opened(run)
    with pytest.raises(ValueError, match="required checks"):
        review.submit_review(root, role="physics_decider", actor_id="physicist", verdict="accept",
            summary="Cannot certify reproduction", claim_scope="reproduction")
    accept(root, scope="diagnostic")
    assert review.gate_errors(root, "delivery") == []
    assert review.status(root)["claim_scope"] == "diagnostic"
    assert review.gate_errors(root, "bulk")


def test_integrity_failure_cannot_be_accepted_as_diagnostic(run):
    root, record = run
    check_packet(root, record, integrity="fail")
    opened(run)
    with pytest.raises(ValueError, match="required checks"):
        accept(root, scope="diagnostic")


def test_self_review_wrong_actor_and_same_cycle_overwrite_are_refused(run):
    root, _ = run
    opened(run)
    with pytest.raises(ValueError, match="actor"):
        review.submit_review(root, role="physics_decider", actor_id="worker", verdict="accept",
            summary="Self approval", claim_scope="reproduction")
    reject(root)
    with pytest.raises(ValueError, match="overwrite"):
        review.submit_review(root, role="physics_decider", actor_id="physicist", verdict="accept",
            summary="Change my mind without a correction", claim_scope="reproduction")
    with pytest.raises(ValueError, match="rejected cycle"):
        review.submit_review(root, role="skeptical_verifier", actor_id="skeptic", verdict="accept",
            summary="Override rejection", claim_scope="reproduction")
    assert review.gate_errors(root, "reuse", "detector")
    with pytest.raises(ValueError, match="successor"):
        opened(run)


def test_correction_pins_exact_bytes_and_held_fixed_inputs(run):
    root, _ = run
    opened(run)
    reject(root)
    correct(root)
    assert review.gate_errors(root, "correction", "detector") == []
    assert review.gate_errors(root, "bulk")
    assert review.gate_errors(root, "correction", "madgraph")
    (root / "inputs/settings.cfg").write_text("efficiency=0.99\n")
    assert review.gate_errors(root, "correction", "detector")


def test_unallowed_input_change_cannot_be_admitted(run):
    root, _ = run
    opened(run)
    reject(root)
    (root / "inputs/held-fixed.txt").write_text("different generator recipe\n")
    with pytest.raises(ValueError, match="changed"):
        correct(root)
    assert review.status(root)["redos_used"] == 0


def test_successful_redo_requires_fresh_attempt_then_two_explicit_closures(run):
    root, old = run
    opened(run)
    reject(root)
    amendment = correct(root)
    # Old receipts have stale settings; unchanged old output bytes cannot repair rejection.
    with pytest.raises(ValueError):
        opened(run, correction_id=amendment["correction_id"])
    fresh = make_attempt(root, value=2)
    check_packet(root, fresh)
    opened((root, fresh), correction_id=amendment["correction_id"])
    with pytest.raises(ValueError, match="close every"):
        accept(root)
    accept(root, closes=["F1"])
    state = review.status(root)
    assert state["state"] == "accepted" and state["redos_used"] == 1 and not state["unresolved_findings"]
    assert review.gate_errors(root, "bulk") == []
    reg, events = review._read(root)
    assert any(e["event"] == "review" and e["verdict"] == "send_back" for e in events)
    assert old["attempt_id"] != fresh["attempt_id"]


@pytest.mark.parametrize("agreement", ["fail", "inconclusive"])
def test_narrow_diagnostic_scope_cannot_close_failed_inherited_defect(run, agreement):
    root, _ = run
    opened(run)
    reject(root)
    amendment = correct(root)
    fresh = make_attempt(root, value=2)
    check_packet(root, fresh, agreement=agreement)
    opened((root, fresh), correction_id=amendment["correction_id"])
    before = review.status(root)["events"]
    with pytest.raises(ValueError, match="inherited finding F1 remains unresolved"):
        accept(root, scope="diagnostic", closes=["F1"])
    state = review.status(root)
    assert state["events"] == before
    assert state["state"] == "awaiting_review"
    assert [finding["id"] for finding in state["unresolved_findings"]] == ["F1"]
    assert review.gate_errors(root, "delivery")


def test_detached_narrow_scope_cannot_backfill_failed_defect_closure(run):
    root, _ = run
    opened(run)
    reject(root)
    amendment = correct(root)
    fresh = make_attempt(root, value=2)
    check_packet(root, fresh)
    opened((root, fresh), correction_id=amendment["correction_id"])
    accept(root, scope="diagnostic", closes=["F1"])
    saved = review.snapshot(root, action="delivery")
    assert review.validate_snapshot(saved) == []
    successor = next(event for event in saved["events"] if event["event"] == "cycle" and event["inherited_findings"])
    next(check for check in successor["checks"] if check["id"] == "agreement")["status"] = "fail"
    previous = saved["registration"]["sha256"]
    for event in saved["events"]:
        event["previous_sha256"] = previous
        event["sha256"] = execution.digest({key: value for key, value in event.items() if key != "sha256"})
        previous = event["sha256"]
    saved["checkpoint"]["sha256"] = previous
    assert "inherited finding F1 remains unresolved" in review.validate_snapshot(saved)[0]


def test_failure_consumes_budget_and_does_not_reset_by_removing_pointer(run):
    root, _ = run
    opened(run)
    reject(root)
    a = correct(root)
    review.fail_correction(root, correction_id=a["correction_id"], reason="Toy execution failed")
    b = review.authorize_correction(root, actor_id="physicist", changed_paths=["inputs/settings.cfg"],
        stages=["detector"], recheck_checks=["agreement"])
    review.fail_correction(root, correction_id=b["correction_id"], reason="Another failed attempt")
    assert review.status(root)["redos_used"] == 2
    with pytest.raises(ValueError, match="exhausted"):
        review.authorize_correction(root, actor_id="physicist", changed_paths=["inputs/settings.cfg"],
            stages=["detector"], recheck_checks=["agreement"])
    (root / review.HEAD).unlink()
    assert review.status(root)["state"] == "invalid"
    with pytest.raises((ValueError, OSError)):
        opened(run)


@pytest.mark.parametrize("mutation", ["policy", "approval", "produced", "receipt", "snapshot", "journal", "tail"])
def test_mutation_blocks_live_gate_and_preserves_historical_distinction(run, mutation):
    root, record = run
    cycle = opened(run)
    accept(root)
    target = {"policy": review.POLICY, "approval": "inputs/checkin1_approval.json",
              "produced": "outputs/produced.json", "receipt": record["attempt_record"],
              "snapshot": cycle["snapshots"][0]["snapshot"],
              "journal": review.DIRECTORY + "/events/00000002.json",
              "tail": review.DIRECTORY + "/events/00000003.json"}[mutation]
    p = root / target
    if mutation == "tail": p.unlink()
    else: p.write_bytes(p.read_bytes() + b"\n")
    # Journal whitespace alone has no semantic effect, so change a journal field as well.
    if mutation == "journal":
        doc = read_json(p); doc["summary"] = "Changed"; atomic_json(p, doc)
    assert review.gate_errors(root, "bulk")
    if mutation in ("produced", "receipt", "policy", "approval"):
        assert review.status(root)["state"] == "accepted"


def test_stop_is_terminal_and_findings_cannot_point_outside_evidence(run):
    root, _ = run
    opened(run)
    bad = finding()
    bad["evidence"] = [{"path": "inputs/checkin1_approval.json", "location": "not the issue"}]
    # Approval is bound, so use a distinct existing but unbound artifact.
    atomic_json(root / "inputs/unreviewed.json", {"value": 1})
    bad["evidence"][0]["path"] = "inputs/unreviewed.json"
    with pytest.raises(ValueError, match="not bound"):
        review.submit_review(root, role="physics_decider", actor_id="physicist", verdict="send_back",
            summary="Unbound evidence", findings=[bad])
    review.submit_review(root, role="physics_decider", actor_id="physicist", verdict="stop",
        summary="Missing external reference prevents the requested claim")
    assert review.status(root)["state"] == "stopped"
    with pytest.raises(ValueError): correct(root)
    with pytest.raises(ValueError): opened(run)


def test_review_scopes_must_agree(run):
    root, _ = run
    opened(run)
    review.submit_review(root, role="physics_decider", actor_id="physicist", verdict="accept",
        summary="Diagnostic only", claim_scope="diagnostic")
    with pytest.raises(ValueError, match="same claim"):
        review.submit_review(root, role="skeptical_verifier", actor_id="skeptic", verdict="accept",
            summary="Overreach", claim_scope="reproduction")


def test_check_result_cannot_omit_check_or_cite_unbound_attempt(run):
    root, _ = run
    p = root / "inputs/checks.json"
    doc = read_json(p)
    doc["checks"][0]["attempt_ids"] = ["not-an-executed-attempt"]
    atomic_json(p, doc)
    with pytest.raises(ValueError, match="unbound"):
        opened(run)


def test_large_artifacts_are_committed_without_copies_and_small_blobs_deduplicate(run):
    root, _ = run
    large = root / "inputs/large-events.dat"
    large.write_bytes(b"E" * (review.MAX_RETAINED_BYTES + 1))
    pins = review._snapshots(root, [str(large), "inputs/settings.cfg"], "first")
    assert pins[0]["content_retained"] is False and pins[0]["snapshot"] is None
    assert pins[0]["size"] == review.MAX_RETAINED_BYTES + 1
    again = review._snapshots(root, ["inputs/settings.cfg"], "second")
    assert again[0]["snapshot"] == pins[1]["snapshot"]
    assert len(list((root / review.DIRECTORY / "snapshots").glob("*.blob"))) == 1


def test_directory_evidence_needs_an_explicit_manifest(run):
    root, _ = run
    with pytest.raises(ValueError, match="file manifest"):
        review._snapshots(root, ["inputs"], "bad")


def test_detached_acceptance_remains_valid_after_current_evidence_changes(run):
    root, _ = run
    opened(run)
    accept(root)
    saved = review.snapshot(root)
    assert review.validate_snapshot(saved) == []
    (root / "outputs/produced.json").write_text('{"value":900}\n')
    assert review.gate_errors(root, "bulk")
    assert review.validate_snapshot(saved) == []
    assert review.status(root)["state"] == "accepted"
    changed = copy.deepcopy(saved)
    changed["events"][-1]["actor_id"] = "worker"
    assert review.validate_snapshot(changed)


def test_detached_diagnostic_scope_does_not_authorize_bulk(run):
    root, record = run
    check_packet(root, record, agreement="fail")
    opened(run)
    accept(root, scope="diagnostic")
    saved = review.snapshot(root, action="delivery")
    assert review.validate_snapshot(saved) == []
    saved["action"] = "bulk"
    assert review.validate_snapshot(saved)


def test_exact_correction_command_and_artifact_scope_are_enforced(run):
    root, record = run
    opened(run)
    reject(root)
    amendment = correct(root)
    spec = amendment["stage_specs"][0]
    assert review.correction_execution_errors(root, **spec) == []
    bad = {**spec, "command": [sys.executable, "-c", "print('different calculation')"]}
    assert review.correction_execution_errors(root, **bad)
    bad = {**spec, "outputs": ["outputs/different.json"]}
    assert review.correction_execution_errors(root, **bad)
    bad = {**spec, "log": "logs/unadmitted.log"}
    assert review.correction_execution_errors(root, **bad)
    assert review.correction_execution_errors(root, **{k: v for k, v in spec.items() if k != "log"})
    assert review.validate_snapshot(review.snapshot(root, action="correction", stage="detector")) == []


def test_new_checkpoint_requires_new_successful_checked_output_and_same_settings(run):
    root, _ = run
    first = opened(run)
    accept(root)
    with pytest.raises(ValueError, match="newly successful"):
        opened(run, checkpoint=True)
    fresh = make_attempt(root, value=3)
    check_packet(root, fresh)
    second = opened((root, fresh), checkpoint=True)
    assert first["cycle_id"] != second["cycle_id"]
    assert review.status(root)["state"] == "awaiting_review"
    assert review.gate_errors(root, "bulk")
    assert review.status(root)["redos_used"] == 0
    accept(root)
    assert review.validate_snapshot(review.snapshot(root)) == []


def test_missing_registration_or_checkpoint_never_becomes_inactive(run):
    root, _ = run
    assert review.active(root) is False
    opened(run)
    assert review.active(root) is True
    (root / review.REGISTRATION).unlink()
    assert review.active(root) is True
    assert review.status(root)["state"] == "invalid"
    with pytest.raises(ValueError, match="disappeared"):
        opened(run)


def test_critic_rejection_is_sticky_and_cannot_be_voted_away(run):
    root, _ = run
    opened(run)
    review.submit_review(root, role="physics_critic", actor_id="critic", verdict="send_back",
        summary="A blocking scientific problem", findings=[finding()])
    for role, actor in (("skeptical_verifier", "skeptic"), ("physics_decider", "physicist")):
        with pytest.raises(ValueError, match="rejected cycle"):
            review.submit_review(root, role=role, actor_id=actor, verdict="accept", summary="Vote to overrule",
                claim_scope="reproduction")


def test_invalid_first_cycle_does_not_consume_registration_or_block_smoke(run):
    root, _ = run
    with pytest.raises(ValueError):
        review.open_cycle(root, effective_settings=["inputs/settings.cfg"],
            stage_receipts=["missing-receipt.json"], check_results="inputs/checks.json")
    assert not review.registered(root)
    assert not review.active(root)


def test_valid_empty_registration_is_unopened_not_corruption_fallback(run):
    root, _ = run
    review._registration(root, create=True)
    assert review.registered(root)
    assert not review.active(root)
    (root / review.HEAD).unlink()
    assert review.active(root)


def test_completed_correction_stage_cannot_spend_another_attempt_under_same_admission(run):
    root, _ = run
    opened(run)
    reject(root)
    correct(root)
    make_attempt(root, value=2)
    assert "already succeeded" in review.gate_errors(root, "correction", "detector")[0]


@pytest.mark.parametrize("use_producer_log", [False, True])
def test_multistage_correction_regenerates_only_declared_predecessor_inputs(run, use_producer_log):
    root, first = run
    p = policy()
    p["allowed_stages"].append("statistics")
    atomic_json(root / review.POLICY, p)

    def statistics_attempt(value):
        inputs = ["outputs/produced.json", "inputs/held-fixed.txt"]
        if use_producer_log:
            inputs.append("logs/detector.log")
        spec = {"command": [sys.executable, "-c", "pass"], "cwd": str(root.resolve()), "inputs": inputs,
                "outputs": ["outputs/statistics.json"], "input_snapshot": execution.snapshot(root, inputs),
                "parents": {"detector": execution.load_execution(root)["stages"]["detector"]["receipt_sha256"]},
                "runtime": execution.runtime_context()}
        spec["fingerprint"] = execution.digest(spec)
        rec = execution.begin_attempt(root, "statistics", spec, "logs/statistics.log")
        atomic_json(root / "outputs/statistics.json", {"value": value})
        (root / "logs/statistics.log").write_text(f"statistics value {value}\n")
        assert execution.finish_attempt(root, rec, 0) == 0
        return rec

    second = statistics_attempt(1)
    review.open_cycle(root, effective_settings=["inputs/settings.cfg"],
        stage_receipts=[first["attempt_record"], second["attempt_record"]], check_results="inputs/checks.json")
    f = finding()
    f["required_stages"].append("statistics")
    review.submit_review(root, role="physics_critic", actor_id="critic", verdict="send_back", summary="Both stages require redo", findings=[f])
    (root / "inputs/settings.cfg").write_text("efficiency=0.85\n")
    correction = review.authorize_correction(root, actor_id="physicist", changed_paths=["inputs/settings.cfg"],
        stages=["detector", "statistics"], recheck_checks=["agreement"])
    assert review.gate_errors(root, "correction", "statistics")
    fresh_first = make_attempt(root, value=2)
    assert review.gate_errors(root, "correction", "statistics") == []
    if use_producer_log:
        assert {"path": "logs/detector.log", "producer": "detector", "consumer": "statistics"} in correction["regenerated_inputs"]
        assert "logs/detector.log" not in {p["path"] for p in correction["snapshots"]}
        log = root / "logs/detector.log"
        original = log.read_bytes()
        log.write_text("post-success counterfeit log\n")
        assert review.gate_errors(root, "correction", "statistics")
        log.write_bytes(original)
        assert review.gate_errors(root, "correction", "statistics") == []
    fresh_second = statistics_attempt(2)
    check_packet(root, fresh_first)
    results = read_json(root / "inputs/checks.json")
    results["checks"][1]["attempt_ids"].append(fresh_second["attempt_id"])
    results["checks"][1]["evidence"].append({"path": "outputs/statistics.json", "location": "$.value"})
    atomic_json(root / "inputs/checks.json", results)
    review.open_cycle(root, effective_settings=["inputs/settings.cfg"],
        stage_receipts=[fresh_first["attempt_record"], fresh_second["attempt_record"]],
        check_results="inputs/checks.json", correction_id=correction["correction_id"])
    accept(root, closes=["F1"])
    assert review.gate_errors(root, "bulk") == []


def test_only_named_prepared_native_settings_can_be_allowed_under_output():
    p = policy()
    p["allowed_changed_paths"] = ["output/native_effective_settings.json", "output/run_card.dat", "output/shower.cfg"]
    assert review.validate_policy(p) == []
    for path in ("output/exclusion.json", "output/native_execution_result.json", "logs/execution/record.json", "outputs/result.json"):
        bad = copy.deepcopy(p)
        bad["allowed_changed_paths"].append(path)
        assert review.validate_policy(bad)


def test_operational_clock_cannot_move_backwards_live_or_in_detached_history(run, monkeypatch):
    root, _ = run
    opened(run)
    monkeypatch.setenv("WORKFLOW_STATE_UTC", "2000-01-01T00:00:00Z")
    with pytest.raises(ValueError, match="clock moved backwards"):
        review.submit_review(root, role="physics_critic", actor_id="critic", verdict="accept",
            summary="Invalid time", claim_scope="reproduction")
    monkeypatch.delenv("WORKFLOW_STATE_UTC")
    accept(root)
    saved = review.snapshot(root)
    saved["events"][1]["utc"] = "2000-01-01T00:00:00Z"
    previous = saved["registration"]["sha256"]
    for event in saved["events"]:
        event["previous_sha256"] = previous
        event["sha256"] = execution.digest({k: v for k, v in event.items() if k != "sha256"})
        previous = event["sha256"]
    saved["checkpoint"]["sha256"] = previous
    assert "clock moved backwards" in review.validate_snapshot(saved)[0]
    for event in saved["events"]:
        atomic_json(root / review.DIRECTORY / "events" / f"{event['sequence']:08d}.json", event)
    atomic_json(root / review.HEAD, saved["checkpoint"])
    assert "clock moved backwards" in review.status(root)["errors"][0]


def test_inherited_fixed_path_can_stay_exact_while_new_finding_requires_other_mutation(run):
    root, first = run
    p = policy()
    p["allowed_changed_paths"].append("inputs/held-fixed.txt")
    atomic_json(root / review.POLICY, p)
    settings = ["inputs/settings.cfg", "inputs/held-fixed.txt"]
    review.open_cycle(root, effective_settings=settings, stage_receipts=[first["attempt_record"]], check_results="inputs/checks.json")
    reject(root)
    first_correction = correct(root)
    second = make_attempt(root, value=2)
    check_packet(root, second)
    review.open_cycle(root, effective_settings=settings, stage_receipts=[second["attempt_record"]],
        check_results="inputs/checks.json", correction_id=first_correction["correction_id"])
    # F1's exact fix now has fresh evidence, but a distinct F2 still blocks acceptance.
    f2 = finding("F2", ["inputs/held-fixed.txt"])
    review.submit_review(root, role="physics_critic", actor_id="critic", verdict="send_back",
        summary="F1's setting is fixed; investigate the separately declared F2", findings=[f2])
    with pytest.raises(ValueError, match="mandatory finding obligation"):
        review.authorize_correction(root, actor_id="physicist", changed_paths=[],
            stages=["detector"], recheck_checks=["agreement"])
    fixed_bytes = (root / "inputs/settings.cfg").read_bytes()
    (root / "inputs/held-fixed.txt").write_text("prospectively allowed second correction\n")
    second_correction = review.authorize_correction(root, actor_id="physicist", changed_paths=["inputs/held-fixed.txt"],
        stages=["detector"], recheck_checks=["agreement"])
    assert (root / "inputs/settings.cfg").read_bytes() == fixed_bytes
    assert second_correction["held_paths"][0]["finding_id"] == "F1"
    third = make_attempt(root, value=3)
    check_packet(root, third)
    review.open_cycle(root, effective_settings=settings, stage_receipts=[third["attempt_record"]],
        check_results="inputs/checks.json", correction_id=second_correction["correction_id"])
    with pytest.raises(ValueError, match="close every"):
        accept(root, closes=["F2"])
    accept(root, closes=["F1", "F2"])
    assert review.gate_errors(root, "bulk") == []
    assert review.validate_snapshot(review.snapshot(root)) == []
    saved = review.snapshot(root)
    admitted = next(e for e in saved["events"] if e["event"] == "correction" and e["held_paths"])
    admitted["held_paths"][0]["correction_id"] = "unrelated-admission"
    previous = saved["registration"]["sha256"]
    for event in saved["events"]:
        event["previous_sha256"] = previous
        event["sha256"] = execution.digest({k: v for k, v in event.items() if k != "sha256"})
        previous = event["sha256"]
    saved["checkpoint"]["sha256"] = previous
    assert "inherited repair commitment" in review.validate_snapshot(saved)[0]


def test_new_finding_cannot_borrow_an_old_repair_of_the_same_path(run):
    root, first = run
    opened(run)
    reject(root)
    correction = correct(root)
    fresh = make_attempt(root, value=2)
    check_packet(root, fresh)
    review.open_cycle(root, effective_settings=["inputs/settings.cfg"], stage_receipts=[fresh["attempt_record"]],
        check_results="inputs/checks.json", correction_id=correction["correction_id"])
    reject(root, "F2")
    with pytest.raises(ValueError, match="mandatory finding obligation"):
        review.authorize_correction(root, actor_id="physicist", changed_paths=[],
            stages=["detector"], recheck_checks=["agreement"])
    assert review.status(root)["redos_used"] == 1


# Private proposal controls. These are engineering fixtures, not physics findings.
def late_finding_context(root):
    reg, events = review._read(root)
    view = review._view(reg, events)
    cycle = view["cycle"]
    old = next(pin for pin in cycle["snapshots"] if pin["path"] == "outputs/produced.json")
    fresh = root / "inputs/late-numerical-defect.json"
    atomic_json(fresh, {"engineering_adverse_control": True, "optimizer_calls": 0, "physics_validated": False})
    context = {"schema_version": 1, "kind": "post_acceptance_scientific_finding", "run_id": reg["run_id"],
        "cycle_id": cycle["cycle_id"], "cycle_sha256": cycle["sha256"], "claim_scope": "reproduction",
        "accepted_review_sha256": [event["sha256"] for event in view["reviews"]],
        "role": "physics_critic", "actor_id": "critic", "findings": [{"id": "late-stationarity",
        "summary": "New located engineering control contests a required numerical claim",
        "check_ids": ["agreement"],
        "accepted_evidence": [{"path": old["path"], "sha256": old["sha256"], "location": "$.value"}],
        "new_evidence": [{"path": "inputs/late-numerical-defect.json", "sha256": execution.file_hash(fresh),
                          "location": "$.engineering_adverse_control"}]}]}
    target = root / "inputs/late-finding-context.json"
    atomic_json(target, context)
    return context, target


def commit_late_hold(root, context, path, **overrides):
    values = {"actor_id": "physicist", "cycle_id": context["cycle_id"], "claim_scope": context["claim_scope"],
              "summary": "Hold future use pending new scientific evidence", "finding_context": str(path),
              "finding_context_sha256": execution.file_hash(path)}
    values.update(overrides)
    return review.submit_hold(root, **values)


def held_history(root):
    reg, events = review._read(root)
    return {"schema_version": 1, "registration": reg, "events": events,
        "checkpoint": read_json(root/review.HEAD), "action": "history", "stage": None}


def test_late_hold_preserves_accepted_receipts_and_refuses_future_use_without_budget(run):
    from ravel.workflow import review_enforcement
    root, record = run
    fixed = policy()
    fixed.update(max_redos=0, allowed_changed_paths=[])
    atomic_json(root/review.POLICY, fixed)
    opened(run)
    accept(root)
    historical = review.snapshot(root, action="delivery")
    previous = review.status(root)
    protected = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()
                 and path not in (root/review.HEAD, root/review.DIRECTORY/"write.lock")}
    context, path = late_finding_context(root)
    event = commit_late_hold(root, context, path)
    assert event["event"] == "scientific_hold"
    assert all(path.read_bytes() == content for path, content in protected.items())
    assert review.validate_snapshot(historical) == []  # Past authorization is not rewritten as a failure.
    state = review.status(root)
    assert state["state"] == "scientific_hold" and state["held_claim_scope"] == "reproduction"
    assert state["scientific_hold_sha256"] == event["sha256"]
    assert state["redos_used"] == previous["redos_used"] == 0
    assert state["redos_remaining"] == previous["redos_remaining"] == 0
    assert execution.stage_errors(root, "detector") == []
    assert execution.load_execution(root)["stages"]["detector"]["status"] == "succeeded"
    for action in ("delivery", "reuse", "bulk", "correction"):
        assert "scientific hold blocks" in review.gate_errors(root, action, "detector")[0]
        with pytest.raises(ValueError, match="inadmissible"):
            review.snapshot(root, action=action, stage="detector")
    assert review_enforcement.delivery_errors(root)
    for resume in (False, True):
        with pytest.raises(ValueError, match="scientific review blocks stage"):
            review_enforcement.before_stage(root, "detector", record["command"], record["inputs"],
                record["outputs"], [], str(root), "logs/future.log", resume=resume)
    with pytest.raises(ValueError):
        review.authorize_correction(root, actor_id="physicist", changed_paths=[], stages=["detector"], recheck_checks=["agreement"])
    with pytest.raises(ValueError):
        review.open_cycle(root, effective_settings=["inputs/settings.cfg"], stage_receipts=[record["attempt_record"]],
                          check_results="inputs/checks.json", checkpoint=True)
    with pytest.raises(ValueError, match="cannot receive another review"):
        review.submit_review(root, role="physics_decider", actor_id="physicist", verdict="accept", summary="lift", claim_scope="reproduction")
    assert review.validate_snapshot(held_history(root), require_admission=False) == []
    assert review.validate_snapshot(held_history(root))
    assert all(path.read_bytes() == content for path, content in protected.items())


@pytest.mark.parametrize("defect", ["wrong_decider", "wrong_cycle", "wrong_scope", "wrong_run", "cycle_sha",
    "vote_sha", "producer_reporter", "wrong_role", "wrong_reporter", "undeclared_check", "custody_only",
    "old_sha", "unlocated_old", "new_sha", "missing_new", "recycled_evidence", "context_alias", "context_sha"])
def test_late_hold_refuses_unauthorized_unbound_or_replayed_context_without_new_event(run, defect):
    root, _ = run
    opened(run)
    accept(root)
    context, path = late_finding_context(root)
    previous = (root/review.HEAD).read_bytes()
    previous_events = {p:p.read_bytes() for p in (root/review.DIRECTORY/"events").glob("*.json")}
    previous_state = review.status(root)
    finding = context["findings"][0]
    args = {}
    if defect == "context_sha": args["finding_context_sha256"] = "0"*64
    elif defect == "wrong_decider": args["actor_id"] = "worker"
    elif defect == "wrong_cycle": args["cycle_id"] = "old-cycle"
    elif defect == "wrong_scope": args["claim_scope"] = "diagnostic"
    elif defect == "wrong_run": context["run_id"] = "other-run"
    elif defect == "cycle_sha": context["cycle_sha256"] = "0"*64
    elif defect == "vote_sha": context["accepted_review_sha256"][0] = "0"*64
    elif defect == "producer_reporter": context["actor_id"] = "worker"
    elif defect == "wrong_role": context["role"] = "physics_decider"
    elif defect == "wrong_reporter": context["actor_id"] = "new-unregistered-expert"
    elif defect == "undeclared_check": finding["check_ids"] = ["unknown"]
    elif defect == "custody_only": finding["check_ids"] = ["integrity"]
    elif defect == "old_sha": finding["accepted_evidence"][0]["sha256"] = "0"*64
    elif defect == "unlocated_old":
        reg, events = review._read(root)
        pin = next(p for p in review._view(reg,events)["cycle"]["snapshots"] if p["path"] == "inputs/settings.cfg")
        finding["accepted_evidence"] = [{"path":pin["path"],"sha256":pin["sha256"],"location":"line1"}]
    elif defect == "new_sha": finding["new_evidence"][0]["sha256"] = "0"*64
    elif defect == "missing_new": finding["new_evidence"][0]["path"] = "inputs/missing.json"
    elif defect == "recycled_evidence": finding["new_evidence"] = copy.deepcopy(finding["accepted_evidence"])
    else:
        alias = root/"inputs/context-alias.json"
        alias.symlink_to(path)
        args["finding_context"] = str(alias)
    atomic_json(path, context)
    with pytest.raises(ValueError): commit_late_hold(root, context, path, **args)
    assert (root/review.HEAD).read_bytes() == previous
    assert {p:p.read_bytes() for p in (root/review.DIRECTORY/"events").glob("*.json")} == previous_events
    assert review.status(root) == previous_state
    assert review.gate_errors(root, "delivery") == []


def test_late_hold_cannot_be_replayed_or_silently_lifted_by_evidence_removal(run):
    root, _ = run
    opened(run)
    accept(root)
    context, path = late_finding_context(root)
    event = commit_late_hold(root, context, path)
    checkpoint = (root/review.HEAD).read_bytes()
    with pytest.raises(ValueError, match="exact currently accepted"):
        commit_late_hold(root, context, path)
    assert (root/review.HEAD).read_bytes() == checkpoint
    path.unlink()
    (root/"inputs/late-numerical-defect.json").unlink()
    assert review.status(root)["state"] == "scientific_hold"
    assert review.gate_errors(root, "reuse")
    blob = root/next(p["snapshot"] for p in event["snapshots"] if p["path"] == "inputs/late-numerical-defect.json")
    blob.write_text("changed retained finding evidence")
    assert review.status(root)["state"] == "invalid"
    assert review.gate_errors(root, "delivery")


@pytest.mark.parametrize("defect", ["decider", "scope", "context_votes", "context_reporter", "extra_budget", "replay"])
def test_detached_late_hold_validation_refuses_rebound_authority_and_budget_grants(run, defect):
    root, _ = run
    opened(run)
    accept(root)
    context, path = late_finding_context(root)
    commit_late_hold(root, context, path)
    history = held_history(root)
    assert review.validate_snapshot(history, require_admission=False) == []
    event = history["events"][-1]
    if defect == "decider": event["actor_id"] = "worker"
    elif defect == "scope": event["claim_scope"] = "diagnostic"
    elif defect == "extra_budget": event["max_redos"] = 20
    elif defect == "replay":
        replay = copy.deepcopy(event)
        replay.update(sequence=len(history["events"])+1, previous_sha256=event["sha256"])
        history["events"].append(replay)
        event = replay
    else:
        body = json.loads(event["finding_context"]["text"])
        if defect == "context_votes": body["accepted_review_sha256"][0] = "0"*64
        else: body["actor_id"] = "worker"
        raw = json.dumps(body,indent=2)+"\n"
        event["finding_context"].update(text=raw,sha256=execution.file_hash(path))
        import hashlib
        event["finding_context"]["sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        pin = next(p for p in event["snapshots"] if p["path"] == event["finding_context"]["path"])
        pin.update(sha256=event["finding_context"]["sha256"],size=len(raw.encode()),
                   snapshot=review.DIRECTORY+"/snapshots/"+event["finding_context"]["sha256"]+".blob")
    event["sha256"] = execution.digest({k:v for k,v in event.items() if k != "sha256"})
    history["checkpoint"] = {"sequence":len(history["events"]),"sha256":event["sha256"]}
    assert review.validate_snapshot(history, require_admission=False)


def test_late_hold_has_a_public_cli_action_with_no_native_process(run, capsys):
    root, _ = run
    opened(run)
    accept(root)
    context, path = late_finding_context(root)
    request = root/"inputs/hold-request.json"
    atomic_json(request,{"actor_id":"physicist","cycle_id":context["cycle_id"],"claim_scope":"reproduction",
                        "summary":"Late engineering defect", "finding_context":str(path), "finding_context_sha256":execution.file_hash(path)})
    assert review.main(["--rundir",str(root),"hold","--request",str(request)]) == 0
    assert json.loads(capsys.readouterr().out)["event"] == "scientific_hold"
    assert review.status(root)["state"] == "scientific_hold"


def test_hash_valid_early_hold_is_a_semantic_refusal_at_all_gate_paths(run):
    from ravel.workflow import review_enforcement
    root, record = run
    opened(run)
    accept(root)
    context, path = late_finding_context(root)
    commit_late_hold(root,context,path)
    history=held_history(root)
    event=copy.deepcopy(history["events"][-1])
    event.update(sequence=2,previous_sha256=history["events"][0]["sha256"])
    event["sha256"]=execution.digest({k:v for k,v in event.items() if k!="sha256"})
    history["events"]=[history["events"][0],event]
    history["checkpoint"]={"sequence":2,"sha256":event["sha256"]}
    assert "invalid scientific hold" in review.validate_snapshot(history,require_admission=False)[0]
    # Deliberate corruption of an isolated unit fixture, never original science records.
    for target in (root/review.DIRECTORY/"events").glob("*.json"):
        if target.name!="00000001.json":target.unlink()
    atomic_json(root/review.DIRECTORY/"events/00000002.json",event)
    atomic_json(root/review.HEAD,history["checkpoint"])
    with pytest.raises(ValueError,match="invalid scientific hold"):
        review._read(root)
    assert review.status(root)["state"]=="invalid"
    for action in ("reuse","delivery","bulk","correction"):
        assert "invalid scientific hold" in review.gate_errors(root,action,"detector")[0]
    assert review_enforcement.delivery_errors(root)
    for resume in (False,True):
        with pytest.raises(ValueError,match="scientific review blocks stage"):
            review_enforcement.before_stage(root,"detector",record["command"],record["inputs"],record["outputs"],
                [],str(root),"logs/forbidden-future.log",resume=resume)


def test_registered_pins_yield_only_to_a_named_amendment_reapproval_within_policy():
    first, second = "a" * 64, "b" * 64
    reg = {"policy": policy(), "bindings": [{"path": "inputs/settings.cfg", "sha256": "c" * 64},
                                            {"path": "inputs/checkin1_approval.json", "sha256": first}]}
    earlier = {"path": "inputs/settings.cfg", "prior_approval_sha256": "d" * 64}
    named = {"path": "inputs/settings.cfg", "prior_approval_sha256": first}
    # The registered approval replaces nothing; a re-recorded approval must chain to it.
    assert review.amended_paths(reg, {"input_changes": [earlier]}, first) == set()
    for unchained in ({}, {"input_changes": []}, {"input_changes": [earlier]}):
        with pytest.raises(ValueError, match="records no amendment re-approval"):
            review.amended_paths(reg, unchained, second)
    assert review.amended_paths(reg, {"input_changes": [earlier, named]}, second) == {
        "inputs/settings.cfg", "inputs/checkin1_approval.json"}
    wider = {"path": "inputs/held-fixed.txt", "prior_approval_sha256": second}
    with pytest.raises(ValueError, match="allowed changed paths: inputs/held-fixed.txt"):
        review.amended_paths(reg, {"input_changes": [named, wider]}, "e" * 64)
