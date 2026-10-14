"""Decision-control fixes to the decision-justification core .

Each test names the finding it closes. Each negative test was written before its fix and failed on the base.
"""
import json

import pytest

from ravel.workflow import decision_case as dc
from ravel.workflow import evidence_queue, rdj_custody
from ravel.workflow import rdj_loop as rdj

from rdj_fixtures import (PROPOSER, Roles, Run, add, authorize_tuning_case, challenge, critic, critic_once, escalate,
                          node, prepare_case, record_decision, said, two_level_r2, verifier)

TEST_REQUEST = {"kind": "experiment", "description": "Rerun the scan on a coarser grid and compare the yields"}


@pytest.fixture(autouse=True)
def custody(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("RAVEL_NATIVE_BIN", raising=False)


def refused(run, case_id):
    with pytest.raises(rdj.OpenItems) as exc:
        rdj.authorize(run.root, case_id)
    return {i["code"] for i in exc.value.items}


def finding(fid="F1", locators=("B",), evidence_class="code_check", request=None, materiality="A"):
    return {"id": fid, "code": "missing_evidence", "targets": ["B"], "materiality": materiality,
            "evidence_class": evidence_class, "evidence_locators": list(locators), "request": request}


def full_r2(run, roles=None, **opts):
    roles = roles or Roles()
    case_id = two_level_r2(run, roles=roles, **opts)
    rdj.run_roles(run.root, case_id, roles)
    return case_id


def codes(errors):
    return {e.code for e in errors}


# ---------------------------------------------------------------- item 8: the fixture run is an epoch-two run

def test_fixture_run_is_epoch_two_and_has_run_init_snapshot(tmp_path):
    run = Run(tmp_path / "run")
    contract = json.loads((run.root / "inputs/task_contract.json").read_text())
    assert contract["agent_layer_epoch"] == 2
    events = [r["record"]["event"] for r in rdj_custody.rows(run.root, "inputs")]
    assert events == ["run_init"]
    assert rdj_custody.snapshot_digest(run.root, "inputs/task_contract.json", event="run_init") == \
        run.pin("inputs/task_contract.json")["sha256"]


# ---------------------------------------------------------------- item 1: write-log vouching

def test_empty_write_log_does_not_vouch_for_new_input(tmp_path):
    run = Run(tmp_path / "run")
    planted = run.put("inputs/x.json", {"bins": 40})
    run.put("agent-audit/writes.jsonl", "")
    line = rdj_custody.record_input_snapshot(run.root, "checkin1")
    assert planted["path"] in line["record"]["unvouched"]
    assert planted["path"] not in rdj_custody.input_snapshot(run.root)


def test_incomplete_write_log_does_not_vouch(tmp_path):
    run = Run(tmp_path / "run")
    planted = run.put("inputs/x.json", {"bins": 40})
    run.put("agent-audit/writes.jsonl", json.dumps({"path": "outputs/y.json", "sha256": "0" * 64,
                                                    "session_id": "s"}) + "\n")
    rdj_custody.record_input_snapshot(run.root, "checkin1")
    assert planted["path"] not in rdj_custody.input_snapshot(run.root)


def test_user_text_naming_file_still_vouches(tmp_path):
    run = Run(tmp_path / "run")
    pin = run.steering("Use forty bins for the second pass.")
    run.put("agent-audit/writes.jsonl", "")
    record = rdj_custody.record_input_snapshot(run.root, "checkin1")["record"]
    assert pin["path"] not in record["unvouched"] and record["files"][pin["path"]] == pin["sha256"]
    # User text is RAVEL-written: recorded and vouched for, quoted as user text, never an input artifact.
    assert pin["path"] in record["ravel_written"]


def test_registered_upload_vouches(tmp_path):
    run = Run(tmp_path / "run")
    upload = run.put("inputs/data/upload.json", {"observed": [3, 5]})
    changed = run.put("inputs/data/changed.json", {"observed": [1]})
    rdj_custody.register_acquisition(run.root, upload["path"], source="user_upload")
    rdj_custody.register_acquisition(run.root, changed["path"], source="acquisition")
    run.put("inputs/data/changed.json", {"observed": [2]})  # rewritten after registration
    run.put("agent-audit/writes.jsonl", "")
    rdj_custody.record_input_snapshot(run.root, "checkin1")
    snapshot = rdj_custody.input_snapshot(run.root)
    assert snapshot[upload["path"]] == upload["sha256"]
    assert "inputs/data/changed.json" not in snapshot


def test_a_registered_input_that_the_agent_log_lists_is_not_vouched(tmp_path):
    run = Run(tmp_path / "run")
    upload = run.put("inputs/data/upload.json", {"observed": [3, 5]})
    rdj_custody.register_acquisition(run.root, upload["path"], source="user_upload")
    run.put("agent-audit/writes.jsonl", json.dumps({"path": upload["path"], "sha256": upload["sha256"],
                                                    "session_id": "s"}) + "\n")
    rdj_custody.record_input_snapshot(run.root, "checkin1")
    assert upload["path"] not in rdj_custody.input_snapshot(run.root)


def test_an_acquisition_names_a_file_inside_the_run(tmp_path):
    run = Run(tmp_path / "run")
    with pytest.raises(ValueError):
        rdj_custody.register_acquisition(run.root, "inputs/absent.json", source="user_upload")
    with pytest.raises(ValueError):
        rdj_custody.register_acquisition(run.root, "inputs/cards/settings.json", source="agent")


# ---------------------------------------------------------------- item 2: reopen only by recorded decision

def test_negated_steering_naming_digest_does_not_reopen(tmp_path):
    run = Run(tmp_path / "run")
    _, digest = escalate(run)
    run.steering(f"Do not reopen {digest[:12]}.")
    with pytest.raises(ValueError, match="escalat"):
        rdj.open_case(run.root, "launch", run.action(), PROPOSER)


def test_steering_naming_digest_does_not_reopen(tmp_path):
    run = Run(tmp_path / "run")
    _, digest = escalate(run)
    run.steering(f"Reopen {digest[:12]} please.")
    with pytest.raises(ValueError, match="escalat"):
        rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    assert not hasattr(rdj_custody, "steering_names")


def test_recorded_reopen_decision_reopens(tmp_path):
    run = Run(tmp_path / "run")
    _, digest = escalate(run)
    record_decision(run, "reopen", digest=digest)
    rdj.open_case(run.root, "launch", run.action(), PROPOSER)


# ---------------------------------------------------------------- item 3: code_check verification

def _basis(run, case_id, fid="F1"):
    return run.case(case_id), json.loads((run.root / f"rdj/state/{case_id}.json").read_text())["finding_basis"][fid]


def test_p17_code_check_locator_naming_existing_run_file_is_advisory(tmp_path):
    run = Run(tmp_path / "run")
    roles = Roles(critic=critic([finding(locators=("inputs/cards/settings.json",))]), verifier=verifier(resolved="no"))
    case_id = full_r2(run, roles=roles)
    case, basis = _basis(run, case_id)
    assert basis != "verified"
    assert rdj.finding_status(case, {"finding_basis": {"F1": basis}}, case["critique"]["findings"][0]) == "advisory"
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize"
    assert rdj.decision_detail(run.root, receipt["receipt_id"])["advisory_findings"] == ["F1"]


def test_p17_code_check_locator_naming_case_node_is_advisory(tmp_path):
    run = Run(tmp_path / "run")
    roles = Roles(critic=critic([finding(locators=("B", "A"))]), verifier=verifier(resolved="no"))
    case_id = full_r2(run, roles=roles)
    _, basis = _basis(run, case_id)
    assert basis != "verified"
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"


def test_p17_code_check_naming_registered_failing_check_blocks(tmp_path):
    run = Run(tmp_path / "run")
    locator = run.check_result("closure")
    roles = Roles(critic=critic([finding(locators=(locator,))]), verifier=verifier(resolved="no"))
    case_id = full_r2(run, roles=roles)
    assert _basis(run, case_id)[1] == "verified"
    assert "finding_open" in refused(run, case_id)
    assert rdj.check_critic_basis(run.root, case_id) == []


@pytest.mark.parametrize("variant", ["unregistered", "passed", "unknown_producer", "stale_pin", "edited",
                                     "unknown_invariant"])
def test_p17_a_check_result_verifies_only_registered_failed_recognized_and_current(tmp_path, variant):
    run = Run(tmp_path / "run")
    options = {"unregistered": {"register": False}, "passed": {"status": "passed"},
               "unknown_producer": {"producer": "ravel.physics.pyhf_exclude"},
               "unknown_invariant": {"producer": "invariant:not-a-registered-invariant"}}.get(variant, {})
    locator = run.check_result("closure", **options)
    if variant == "stale_pin":
        run.put("inputs/cards/settings.json", {"bins": 5, "threshold": 2.5})
    if variant == "edited":
        result = json.loads((run.root / "checks/closure.json").read_text())
        run.put("checks/closure.json", {**result, "note": "edited"})
    assert rdj.critic_basis(run.root, None, finding(locators=(locator,))) != "verified"


def test_p17_a_failing_registered_invariant_check_verifies(tmp_path):
    run = Run(tmp_path / "run")
    locator = run.check_result("no-invented", producer="invariant:no-invented-physics-inputs")
    assert rdj.critic_basis(run.root, None, finding(locators=(locator,))) == "verified"


def test_p17_a_failed_validation_stage_verifies_and_a_tool_stage_does_not(tmp_path):
    run = Run(tmp_path / "run")
    failed = {"schema_version": 1, "kind": rdj_custody.CHECK_RESULT_KIND, "check_id": "acc", "status": "failed",
              "producer": "ravel.validation.certify_acceptance", "pins": []}
    validator = run.stage("validate", "outputs/validate.json", failed, kind="measurement")
    tool = run.stage("fit", "outputs/fit.json", {**failed, "check_id": "fit"})
    passed = run.stage("validate2", "outputs/validate2.json", {**failed, "status": "passed"}, kind="measurement")
    assert rdj.critic_basis(run.root, None, finding(locators=(validator["binding"]["receipt_id"],))) == "verified"
    for anchor in (tool, passed):
        assert rdj.critic_basis(run.root, None, finding(locators=(anchor["binding"]["receipt_id"],))) != "verified"


# ---------------------------------------------------------------- item 4: withdrawn and refuting tests

def _tested_case(run, roles=None):
    roles = roles or Roles(critic=critic_once([finding(evidence_class="opinion", locators=(), request=TEST_REQUEST)]),
                           verifier=verifier(resolved="no"))
    case_id = full_r2(run, roles=roles)
    item = next(i for i in evidence_queue.items(run.root, case_id=case_id) if i["source"] == "critic_finding")
    return case_id, item, roles


def test_queue_item_marked_withdrawn_by_file_edit_still_pending(tmp_path):
    run = Run(tmp_path / "run")
    case_id, item, roles = _tested_case(run)
    evidence_queue.resolve(run.root, item["item_id"], status="withdrawn", note="not needed")
    rdj.run_roles(run.root, case_id, roles)
    assert rdj.authorize(run.root, case_id)["outcome"] == "gather_evidence"


def test_refutes_verdict_without_registered_answer_does_not_release_finding(tmp_path):
    run = Run(tmp_path / "run")
    case_id, item, roles = _tested_case(run)
    evidence_queue.resolve(run.root, item["item_id"], status="done", note="the card agrees",
                           pins=[run.pin("inputs/cards/settings.json")], verdict="refutes")
    rdj.run_roles(run.root, case_id, roles)
    assert rdj.authorize(run.root, case_id)["outcome"] == "gather_evidence"


def test_withdrawal_by_recorded_user_decision_releases(tmp_path):
    run = Run(tmp_path / "run")
    case_id, item, roles = _tested_case(run)
    record_decision(run, "withdraw", case_id=case_id, finding_id="F1")
    rdj.run_roles(run.root, case_id, roles)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize" and receipt["open_a_findings"] == 0


def test_a_withdrawal_of_another_case_or_before_the_case_does_not_release(tmp_path):
    run = Run(tmp_path / "run")
    case_id, item, roles = _tested_case(run)
    with pytest.raises(ValueError):
        record_decision(run, "withdraw", case_id="launch-000000000000-00000000", finding_id="F1")
    with pytest.raises(ValueError, match="span"):
        rdj_custody.record_withdrawal(run.root, case_id=case_id, finding_id="F1", source="user_steering",
                                      path=run.steering("Withdraw F2.")["path"], start=9, end=11, text="F1")
    assert rdj.authorize(run.root, case_id)["outcome"] == "gather_evidence"


def test_a_registered_worker_receipt_answer_counts(tmp_path):
    run = Run(tmp_path / "run")
    case_id, item, roles = _tested_case(run)
    receipt = next((run.root / "agent-work").rglob("receipt.json")).relative_to(run.root).as_posix()
    evidence_queue.resolve(run.root, item["item_id"], status="done", note="the investigation answered",
                           pins=[run.pin(receipt)], verdict="refutes")
    rdj.run_roles(run.root, case_id, roles)
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"


def test_the_critic_session_that_raised_a_finding_can_withdraw_it(tmp_path):
    run = Run(tmp_path / "run")
    outputs = [{"findings": [finding(evidence_class="opinion", locators=(), request=TEST_REQUEST)]},
               {"findings": [], "withdrawn": ["F1"]}]
    roles = Roles(critic=lambda payload: said(outputs.pop(0), "critic"), verifier=verifier(resolved="no"))
    case_id, _, _ = _tested_case(run, roles)
    run.put("outputs/smoke.json", {"events": 1})  # B is open again; answering it reruns the critic
    rdj.run_roles(run.root, case_id, roles)
    cid = challenge(run, case_id, "why_believe", "B")
    rdj.answer(run.root, case_id, [{"op": "attach_anchor", "challenge_id": cid, "node_id": "B",
                                    "anchor": run.stage("smoke2", "outputs/smoke2.json", {"events": 100})}])
    run.put("outputs/smoke.json", {"events": 100})  # the first anchor verifies again; the case grew by one
    rdj.run_roles(run.root, case_id, roles)
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"


def test_another_critic_session_cannot_withdraw_a_finding(tmp_path):
    run = Run(tmp_path / "run")
    outputs = [said({"findings": [finding(evidence_class="opinion", locators=(), request=TEST_REQUEST)]}, "critic"),
               said({"findings": [], "withdrawn": ["F1"]}, "critic-2")]
    roles = Roles(critic=lambda payload: outputs.pop(0), verifier=verifier(resolved="no"))
    case_id, _, _ = _tested_case(run, roles)
    run.put("outputs/smoke.json", {"events": 1})
    rdj.run_roles(run.root, case_id, roles)
    cid = challenge(run, case_id, "why_believe", "B")
    rdj.answer(run.root, case_id, [{"op": "attach_anchor", "challenge_id": cid, "node_id": "B",
                                    "anchor": run.stage("smoke2", "outputs/smoke2.json", {"events": 100})}])
    run.put("outputs/smoke.json", {"events": 100})  # the first anchor verifies again; the case grew by one
    with pytest.raises(ValueError, match="withdraw"):
        rdj.run_roles(run.root, case_id, roles)


# ---------------------------------------------------------------- item 5: attestation vocabulary

def test_label_for_cli_verified_is_transport_attested():
    assert dc.label_for("transport_attested_cli", "transport_attested") == "transport_attested"


def test_label_for_cli_unverified_is_self_attested():
    for verified in (None, "self_attested", "host_attested", "transport_attested_cli"):
        assert dc.label_for("transport_attested_cli", verified) == "self_attested"


def test_label_for_relay_schema_1_2_is_self_attested():
    for mode in ("relay_schema_1", "relay_schema_2", "unestablished", None):
        assert dc.label_for(mode, "transport_attested") == "self_attested"
    assert dc.label_for("remote_transport_observed", None) == "transport_attested"
    assert dc.label_for("local_transport_observed", None) == "transport_attested"
    assert dc.label_for("host_attested_external", None) == "host_attested"


def test_attestation_rank_and_independence():
    assert dc.ATTESTATION_RANK == {"self_attested": 0, "host_attested": 1, "human_manual": 1,
                                   "transport_attested": 2}
    assert dc.ATTESTATIONS == ("transport_attested", "host_attested", "self_attested", "human_manual")
    assert [dc.independent(a) for a in dc.ATTESTATIONS] == [True, True, False, True]
    assert rdj.OBSERVED_ATTESTATION["transport_attested_cli"] == "transport_attested"


def test_resolve_worker_receipt_with_cli_mode_not_rejected(tmp_path):
    run = Run(tmp_path / "run")
    cli = lambda payload: said({"findings": []}, "critic", attestation="transport_attested_cli",  # noqa: E731
                               mode="transport_attested_cli", verified_label="transport_attested")
    case_id = full_r2(run, roles=Roles(critic=cli))
    critic_ = run.case(case_id)["critique"]["reviewer"]
    assert critic_["actor_id"] == "critic" and critic_["attestation"] == "transport_attested"


def test_attestation_field_on_receipt_not_trusted(tmp_path):
    run = Run(tmp_path / "run")
    case_id = full_r2(run, roles=Roles(verified=False))
    case = run.case(case_id)
    assert case["critique"]["reviewer"]["attestation"] == "self_attested"
    assert {e["review"]["reviewer"]["attestation"] for e in case["edges"]} == {"self_attested"}
    assert "attestation_insufficient" in refused(run, case_id)


def test_a_cli_mode_without_a_verified_label_is_self_attested(tmp_path):
    run = Run(tmp_path / "run")
    unverified = lambda payload: said({"findings": []}, "critic", mode="transport_attested_cli",  # noqa: E731
                                      verified_label="self_attested")
    case_id = full_r2(run, roles=Roles(critic=unverified))
    assert run.case(case_id)["critique"]["reviewer"]["attestation"] == "self_attested"


def test_a_verified_label_cannot_raise_a_relay_mode(tmp_path):
    run = Run(tmp_path / "run")
    relay = lambda payload: said({"findings": []}, "critic", mode="relay_schema_2",  # noqa: E731
                                 verified_label="transport_attested")
    case_id = full_r2(run, roles=Roles(critic=relay))
    assert run.case(case_id)["critique"]["reviewer"]["attestation"] == "self_attested"


def test_a_worker_registration_names_only_a_worker_label(tmp_path):
    run = Run(tmp_path / "run")
    run.put("agent-work/n/1/receipt.json", {"kind": "agent-worker-receipt"})
    for label in ("human_manual", "transport_attested_cli", "trusted"):
        with pytest.raises(ValueError):
            rdj_custody.register_worker_receipt(run.root, "agent-work/n/1/receipt.json", verified_label=label)


# ---------------------------------------------------------------- item 6: class floor and authorizing receipt

def test_floor_raises_class(tmp_path):
    run = Run(tmp_path / "run")
    cls, factors = rdj.compute_class(run.root, "research_choice", {"kind": "screening_choice", "floor": "R2"})
    assert cls == "R2" and factors["floor"] == "R2"


def test_floor_never_lowers(tmp_path):
    run = Run(tmp_path / "run")
    assert rdj.compute_class(run.root, "launch", {**run.action(), "floor": "R0"})[0] == \
        rdj.compute_class(run.root, "launch", run.action())[0] == "R2"


def test_unknown_floor_raises_valueerror(tmp_path):
    run = Run(tmp_path / "run")
    for floor in ("R9", "r2", 2, True):
        with pytest.raises(ValueError, match="floor"):
            rdj.compute_class(run.root, "launch", {**run.action(), "floor": floor})


def test_a_floor_above_the_case_class_refuses_the_gate(tmp_path):
    run = Run(tmp_path / "run")
    receipt = authorize_tuning_case(run, "R2")
    action = {**run.action("tuning_change"), "floor": "R3"}
    assert "rdj_class_too_low" in codes(rdj.gate_errors(run.root, "deviation", action))
    assert rdj.authorizing_receipt(run.root, "deviation", action) is None
    assert rdj.gate_errors(run.root, "deviation", {**action, "floor": "R2"}) == []
    assert receipt["class"] == "R2"


def test_authorizing_receipt_is_the_one_gate_errors_accepted(tmp_path):
    run = Run(tmp_path / "run")
    action = run.action("tuning_change")
    older = authorize_tuning_case(run, "R2")
    newer = authorize_tuning_case(run, "R2")
    older_case = run.root / older["case"]["path"]
    older_case.write_text(older_case.read_text().replace("synthetic.parameter", "synthetic.other"))
    assert rdj.gate_errors(run.root, "deviation", action) == []
    found = rdj.authorizing_receipt(run.root, "deviation", action)
    assert found["receipt"]["receipt_id"] == newer["receipt_id"]
    assert found["receipt_sha256"] == rdj_custody.rows(run.root, "receipts")[-1]["record"]["sha256"]
    assert found["case"]["case_id"] == newer["case"]["path"].split("/")[-1][:-5]
    assert found["case"]["decision_point"]["tuning"]["class"] == "calibration"
    assert found["case_sha256"] == newer["case_sha256"]
    run.put("outputs/plan.json", {"points": 4})  # the action bytes change: no receipt authorizes
    assert rdj.gate_errors(run.root, "deviation", action) != []
    assert rdj.authorizing_receipt(run.root, "deviation", action) is None


# ---------------------------------------------------------------- item 7: gate-filtered receipt selection

def test_launch_with_only_unblind_receipt_reports_receipt_missing(tmp_path):
    run = Run(tmp_path / "run")
    escalate(run, gate="unblind")
    assert codes(rdj.gate_errors(run.root, "launch", run.action())) == {"rdj_receipt_missing"}


# ---------------------------------------------------------------- RDJ half of the merged-tree acceptance legs

def test_leg_l4_a_real_tuning_case_authorizes_at_its_floor(tmp_path):
    run = Run(tmp_path / "run")
    receipt = authorize_tuning_case(run, "R2", "calibration", gate="checkin2_accept")
    action = {**run.action("tuning_change"), "floor": "R2"}
    assert rdj.gate_errors(run.root, "checkin2_accept", action) == []
    found = rdj.authorizing_receipt(run.root, "checkin2_accept", action)
    assert found["receipt"]["receipt_id"] == receipt["receipt_id"]
    assert found["case"]["decision_point"]["tuning"]["class"] == "calibration"
    assert found["case"]["risk"]["class"] == "R2"


def test_leg_l8_an_r3_unblind_case_needs_a_recorded_approval(tmp_path):
    run = Run(tmp_path / "run")
    action = run.action("bulk_launch")
    case_id = prepare_case(run, "unblind", "bulk_launch")
    assert run.case(case_id)["risk"]["class"] == "R3"
    assert "human_required" in refused(run, case_id)
    assert codes(rdj.gate_errors(run.root, "unblind", action)) == {"rdj_receipt_missing"}
    record_decision(run, "approve", case_id=case_id)
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"
    assert rdj.gate_errors(run.root, "unblind", action) == []
    assert rdj.authorizing_receipt(run.root, "unblind", action)["case"]["case_id"] == case_id


def test_leg_l9_steering_that_names_the_digest_leaves_the_escalation_open(tmp_path):
    run = Run(tmp_path / "run")
    _, digest = escalate(run, gate="checkin2_accept")
    run.steering(f"Do not reopen {digest[:12]}")
    assert codes(rdj.gate_errors(run.root, "checkin2_accept", run.action())) == {"rdj_not_authorized"}
    with pytest.raises(ValueError, match="escalat"):
        rdj.open_case(run.root, "checkin2_accept", run.action(), PROPOSER)


def test_leg_l10_an_input_planted_under_an_empty_write_log_cannot_anchor(tmp_path):
    run = Run(tmp_path / "run")
    run.put("agent-audit/writes.jsonl", "")
    planted = run.put("inputs/x.json", {"efficiency": 0.9})
    rdj_custody.record_input_snapshot(run.root, "checkin1")
    anchor = {"kind": "input_artifact", "binding": planted, "locator": "/efficiency"}
    case_id = two_level_r2(run, leaf_anchor=anchor)
    rdj.run_roles(run.root, case_id, Roles())
    case = run.case(case_id)
    assert {a["verified"] for a in case["anchors"]} == {"generated"}
    assert _hard(run, case_id)
    assert rdj.gate_errors(run.root, "launch", run.action()) != []


def _hard(run, case_id):
    """The case does not authorize: refused with open items, or decided as something other than authorize."""
    try:
        rdj.authorize(run.root, case_id)
    except rdj.OpenItems:
        return True
    rows = [r["record"] for r in rdj_custody.rows(run.root, "receipts") if r["record"]["case_id"] == case_id]
    return rows[-1]["outcome"] != "authorize"


def test_leg_l13_a_code_check_citing_a_run_file_does_not_hold_authorization(tmp_path):
    run = Run(tmp_path / "run")
    roles = Roles(critic=critic([finding(locators=("inputs/cards/settings.json",))]), verifier=verifier(resolved="no"))
    case_id = full_r2(run, roles=roles)
    assert _basis(run, case_id)[1] != "verified"
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"


# ---------------------------------------------------------------- item 0: the rebased command table

def test_cli_focused_commands_include_knowledge_modes_transport_rdj():
    """The rebase keeps every entry of the conflicting hunk; ``review`` joins on the integration tree."""
    from ravel import cli
    assert {"knowledge", "modes", "transport", "rdj"} <= set(cli.FOCUSED_COMMANDS)
    assert cli.FOCUSED_COMMANDS["rdj"][0] == "workflow.rdj_loop"
