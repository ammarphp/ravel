"""Role projections over real retained execution attempts and review cycles."""
import json
from copy import deepcopy
from pathlib import Path
import shutil

import pytest

from ravel.workflow import execution, physics_review as review, review_context as context, waypoint_evidence
from ravel.workflow import diagnostic_plan, decision_case
from ravel.workflow.state_io import atomic_json, read_json
from test_physics_review import run, opened, make_attempt, check_packet, finding


def packet(root, tmp_path, role="critic", **kwargs):
    out = tmp_path / role
    manifest = context.create(root, role, out, **kwargs)
    return out, manifest


def contents(out, manifest):
    return {(entry["source_path"], entry["source_phase"]): context.read_artifact(
        out, entry["id"], expected_manifest_sha256=manifest["sha256"])
        for entry in manifest["artifacts"]}


def rewrite_manifest(out, manifest):
    manifest["sha256"] = execution.digest({k: v for k, v in manifest.items() if k != "sha256"})
    atomic_json(out / "manifest.json", manifest)


@pytest.mark.parametrize("custom_waypoint", [False, True])
def test_critic_withholds_duplicated_producer_verdict_and_check_labels(run, tmp_path, custom_waypoint):
    root, _ = run
    doc = read_json(root / "inputs/comparison.json")
    doc["summary"] = "PRODUCER-NARRATIVE-READY-FOR-LAUNCH"
    atomic_json(root / "inputs/comparison.json", doc)
    waypoint = waypoint_evidence.create(root, produced="outputs/produced.json", reference="inputs/reference.json",
        comparison="inputs/comparison.json", inputs=["inputs/settings.cfg"])
    name = "inputs/custom-evidence.json" if custom_waypoint else waypoint_evidence.MANIFEST
    atomic_json(root / name, waypoint)
    atomic_json(root / "inputs/checkin2.json", {"sections": {"evidence_manifest": name}})
    opened(run)
    out, manifest = packet(root, tmp_path)
    values = contents(out, manifest)
    assert all(b"PRODUCER-NARRATIVE" not in value for value in values.values())
    assert json.loads(values[("inputs/comparison.json", "current_cycle")]) == {"diagnostics": {"residual": 0}}
    assert json.loads(values[(name, "current_cycle")])["result"] == {"diagnostics": {"residual": 0}}
    assert all("status" not in check for check in json.loads(values[("inputs/checks.json", "current_cycle")])["checks"])
    assert manifest["findings"] == [] and manifest["reviews"] == []
    assert "Only the packet reader" in manifest["access_limitation"]
    assert "arbitrary scientific artifacts may still carry narrative" in manifest["access_limitation"]


def test_verifier_receives_critic_obligations_and_admitted_setting_bytes_without_verdict(run, tmp_path):
    root, _ = run; opened(run)
    review.submit_review(root, role="physics_critic", actor_id="critic", verdict="send_back",
        summary="OTHER-REVIEWER-VERDICT-SEND-BACK", findings=[finding()])
    (root / "inputs/settings.cfg").write_text("efficiency=0.85\n")
    admission = review.authorize_correction(root, actor_id="physicist", changed_paths=["inputs/settings.cfg"],
        stages=["detector"], recheck_checks=["agreement"])
    out, manifest = packet(root, tmp_path, "verifier")
    values = contents(out, manifest)
    assert manifest["findings"][0]["id"] == "F1"
    assert manifest["reviews"] == []
    assert "OTHER-REVIEWER-VERDICT" not in json.dumps(manifest)
    assert values[("inputs/settings.cfg", "current_cycle")] == b"efficiency=0.8\n"
    assert values[("inputs/settings.cfg", "admitted_correction")] == b"efficiency=0.85\n"
    assert manifest["correction"]["correction_id"] == admission["correction_id"]
    assert manifest["correction"]["state"] == "admitted_before_successor"
    assert manifest["verification_scope"]["finding_ids"] == ["F1"]
    assert manifest["verification_scope"]["fresh_attempts_available"] is False
    assert manifest["correction"]["stage_specs"][0]["stage"] == "detector"
    change = manifest["correction"]["setting_changes"][0]
    assert change["before_sha256"] != change["admitted_sha256"]


def test_successor_verifier_has_prior_settings_fresh_receipt_and_inherited_obligation(run, tmp_path):
    root, _ = run; opened(run)
    review.submit_review(root, role="physics_critic", actor_id="critic", verdict="send_back", summary="PRIOR-ROLE-VERDICT-SEND-BACK", findings=[finding()])
    (root / "inputs/settings.cfg").write_text("efficiency=0.85\n")
    admission = review.authorize_correction(root, actor_id="physicist", changed_paths=["inputs/settings.cfg"],
        stages=["detector"], recheck_checks=["agreement"])
    fresh = make_attempt(root, value=2); check_packet(root, fresh)
    review.open_cycle(root, effective_settings=["inputs/settings.cfg"], stage_receipts=[fresh["attempt_record"]],
        check_results="inputs/checks.json", correction_id=admission["correction_id"])
    out, manifest = packet(root, tmp_path, "verifier")
    values = contents(out, manifest)
    assert values[("inputs/settings.cfg", "current_cycle")] == b"efficiency=0.85\n"
    assert values[("inputs/settings.cfg", "before_correction")] == b"efficiency=0.8\n"
    assert manifest["correction"]["state"] == "successor_cycle_opened"
    assert manifest["verification_scope"]["fresh_attempts_available"] is True
    assert manifest["findings"][0]["id"] == "F1"
    assert any(json.loads(value).get("attempt_id") == fresh["attempt_id"]
               for (name, _), value in values.items() if name == fresh["attempt_record"])
    _, critic = packet(root, tmp_path, "critic")
    assert [obligation["id"] for obligation in critic["findings"]] == ["F1"]
    assert critic["findings"][0] == finding()
    assert critic["reviews"] == []
    assert "PRIOR-ROLE-VERDICT" not in json.dumps(critic)


def test_only_synthesizer_sees_other_review_summaries(run, tmp_path):
    root, _ = run; opened(run)
    review.submit_review(root, role="physics_critic", actor_id="critic", verdict="accept",
        summary="CRITIC-RECORDED-VERDICT", claim_scope="diagnostic")
    _, critic = packet(root, tmp_path, "critic")
    _, verifier = packet(root, tmp_path, "verifier")
    _, synth = packet(root, tmp_path, "synthesizer")
    assert critic["reviews"] == verifier["reviews"] == []
    assert synth["reviews"][0]["summary"] == "CRITIC-RECORDED-VERDICT"


def _bind_check_evidence(root, name, document):
    atomic_json(root / name, document)
    checks = read_json(root / "inputs/checks.json")
    checks["checks"][1]["evidence"].append({"path": name, "location": "/"})
    atomic_json(root / "inputs/checks.json", checks)


@pytest.mark.parametrize("role", ["critic", "verifier", "synthesizer"])
def test_known_diagnostic_report_masks_outcomes_but_retains_measurements(run, tmp_path, role):
    root, _ = run
    base = Path(__file__).resolve().parents[2] / "tests/fixtures/physics-review"
    report = diagnostic_plan.evaluate(read_json(base / "clean-plan.json"), base)
    assert report["status"] == "supported"
    report["criterion_outcomes"][0]["channels"][0]["reason"] = "PRODUCER-INTERPRETATION"
    _bind_check_evidence(root, "inputs/diagnostic-report.json", report)
    opened(run)
    out, manifest = packet(root, tmp_path, role)
    content = contents(out, manifest)[("inputs/diagnostic-report.json", "current_cycle")]
    projected = json.loads(content)
    if role == "synthesizer":
        assert content == (root / "inputs/diagnostic-report.json").read_bytes()
        return
    assert "status" not in projected
    assert "status" not in projected["criterion_outcomes"][0]
    assert all("status" not in row for row in projected["integrity_checks"])
    row = projected["criterion_outcomes"][0]["channels"][0]
    original = report["criterion_outcomes"][0]["channels"][0]
    assert "status" not in row and "reason" not in row
    assert b"PRODUCER-INTERPRETATION" not in content
    for field in ("baseline", "candidate", "difference", "envelope", "relative_mc_errors"):
        assert row[field] == original[field]
    assert projected["comparison_covariance"] == report["comparison_covariance"]
    entry = next(entry for entry in manifest["artifacts"] if entry["source_path"] == "inputs/diagnostic-report.json")
    assert "outcome labels" in entry["projection"]


def test_diagnostic_prose_twins_project_to_the_same_measurements():
    base = Path(__file__).resolve().parents[2] / "tests/fixtures/physics-review"
    report = diagnostic_plan.evaluate(read_json(base / "clean-plan.json"), base)
    altered = deepcopy(report)
    altered["status"] = "contradicted"
    altered["criterion_outcomes"][0]["status"] = "contradicted"
    for row in altered["criterion_outcomes"][0]["channels"]:
        row.update(status="contradicted", reason="SKEPTICAL-PRODUCER-VERDICT")
    assert context._project_known_judgments(report) == context._project_known_judgments(altered)


@pytest.mark.parametrize("role", ["critic", "verifier", "synthesizer"])
def test_known_decision_input_and_output_withhold_other_judgments(run, tmp_path, role):
    root, _ = run
    base = Path(__file__).resolve().parents[2] / "tests/fixtures/physics-review"
    case = read_json(base / "recipe-restoration-case.json")
    case["edges"][0]["review"].update(decision="unresolved", reason="WITHHELD-REVIEWER-RATIONALE")
    case["edges"][0]["request"] = {"kind": "evidence", "description": "Supply the original executed recipe witness"}
    case["nodes"][0]["assumptions"].append({"statement": "The source applies to this branch", "disposition": "accepted", "reason": "WITHHELD-ASSUMPTION-JUDGMENT"})
    report = decision_case.evaluate_case(case, base)
    assert report["status"] == "unresolved"
    _bind_check_evidence(root, "inputs/decision-case.json", case)
    _bind_check_evidence(root, "inputs/decision-report.json", report)
    opened(run)
    out, manifest = packet(root, tmp_path, role)
    values = contents(out, manifest)
    source = json.loads(values[("inputs/decision-case.json", "current_cycle")])
    result = json.loads(values[("inputs/decision-report.json", "current_cycle")])
    if role == "synthesizer":
        assert source == case and result == report
        return
    for document in (source, result):
        assert "WITHHELD-REVIEWER-RATIONALE" not in json.dumps(document)
        assert "WITHHELD-ASSUMPTION-JUDGMENT" not in json.dumps(document)
    assert all("review" not in node for node in source["nodes"])
    assert all("review" not in edge for edge in source["edges"])
    assert source["nodes"][0]["assumptions"][-1] == {"statement": "The source applies to this branch"}
    assert source["edges"][0]["rationale"] == case["edges"][0]["rationale"]
    assert source["edges"][0]["request"] == case["edges"][0]["request"]
    assert "status" not in result
    assert all("status" not in node and "reviewer_decision" not in node for node in result["nodes"])
    assert all("status" not in anchor and "reason" not in anchor for anchor in result["anchors"])
    assert all("reason" not in obligation for obligation in result["obligations"])
    assert any(obligation["request"] == case["edges"][0]["request"] for obligation in result["obligations"])


def test_large_files_are_committed_omissions_and_context_cap_is_explicit(run, tmp_path):
    root, record = run
    (root / "inputs/held-fixed.txt").write_bytes(b"x" * (review.MAX_RETAINED_BYTES + 1))
    record = make_attempt(root); check_packet(root, record); opened((root, record))
    out, manifest = packet(root, tmp_path)
    omitted = next(entry for entry in manifest["omissions"] if entry["source_path"] == "inputs/held-fixed.txt")
    assert "content not retained" in omitted["reason"]
    assert omitted["source_sha256"] == execution.file_hash(root / "inputs/held-fixed.txt")
    with pytest.raises(ValueError, match="absent or ambiguous"):
        context.read_artifact(out, omitted["id"], expected_manifest_sha256=manifest["sha256"])
    _, capped = packet(root, tmp_path, "verifier", max_file_bytes=20)
    assert any("context size limit" in omission["reason"] for omission in capped["omissions"])


def test_packet_creation_is_exclusive_and_reads_frozen_not_live_producer_content(run, tmp_path):
    root, _ = run; opened(run)
    atomic_json(root / "inputs/comparison.json", {"status": "fail", "summary": "LIVE-REWRITE", "diagnostics": {"residual": 99}})
    out, manifest = packet(root, tmp_path)
    assert json.loads(contents(out, manifest)[("inputs/comparison.json", "current_cycle")])["diagnostics"]["residual"] == 0
    before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError):
        context.create(root, "synthesizer", out)
    assert all(path.read_bytes() == value for path, value in before.items())


@pytest.mark.parametrize("attack", ["artifact", "manifest", "rehashed_manifest"])
def test_content_and_manifest_changes_fail_the_external_creation_digest(run, tmp_path, attack):
    root, _ = run; opened(run); out, manifest = packet(root, tmp_path)
    entry = manifest["artifacts"][0]
    if attack == "artifact":
        (out / entry["path"]).write_bytes(b"changed bytes")
    else:
        changed = read_json(out / "manifest.json"); changed["role"] = "synthesizer"
        if attack == "rehashed_manifest": rewrite_manifest(out, changed)
        else: atomic_json(out / "manifest.json", changed)
    with pytest.raises(ValueError, match="changed"):
        context.read_artifact(out, entry["id"], expected_manifest_sha256=manifest["sha256"])


@pytest.mark.parametrize("attack", ["packet", "manifest", "artifact", "artifact_parent", "out_parent"])
def test_symlink_paths_are_refused_even_when_target_bytes_match(run, tmp_path, attack):
    root, _ = run; opened(run)
    if attack == "out_parent":
        real = tmp_path / "real"; real.mkdir(); link = tmp_path / "link"; link.symlink_to(real, target_is_directory=True)
        with pytest.raises(ValueError, match="symlinks"):
            context.create(root, "critic", link / "packet")
        assert not (real / "packet").exists()
        return
    out, manifest = packet(root, tmp_path); entry = manifest["artifacts"][0]
    if attack == "packet":
        link = tmp_path / "packet-link"; link.symlink_to(out, target_is_directory=True); out = link
    elif attack == "artifact_parent":
        copied = tmp_path / "copied-artifacts"; shutil.copytree(out / "artifacts", copied)
        shutil.rmtree(out / "artifacts"); (out / "artifacts").symlink_to(copied, target_is_directory=True)
    else:
        path = out / ("manifest.json" if attack == "manifest" else entry["path"])
        copy = tmp_path / (attack + "-copy"); copy.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(copy)
    with pytest.raises(ValueError, match="symlinks"):
        context.read_artifact(out, entry["id"], expected_manifest_sha256=manifest["sha256"])


def test_manifest_cannot_allowlist_a_path_outside_the_packet_even_with_a_new_digest(run, tmp_path):
    root, _ = run; opened(run); out, manifest = packet(root, tmp_path)
    entry = manifest["artifacts"][0]; entry["path"] = "../outside.json"
    rewrite_manifest(out, manifest)
    with pytest.raises(ValueError, match="allowlist"):
        context.read_artifact(out, entry["id"], expected_manifest_sha256=manifest["sha256"])


def test_corrupt_retained_custody_fails_before_creating_any_packet(run, tmp_path):
    root, _ = run; cycle = opened(run)
    retained = next(pin for pin in cycle["snapshots"] if pin["snapshot"])
    (root / retained["snapshot"]).write_bytes(b"bad custody")
    out = tmp_path / "not-created"
    with pytest.raises(ValueError, match="evidence changed"):
        context.create(root, "critic", out)
    assert not out.exists()


def test_reader_requires_creation_digest_and_invalid_size_does_not_consume_output(run, tmp_path):
    root, _ = run; opened(run)
    out = tmp_path / "invalid"
    with pytest.raises(ValueError, match="positive exact integer"):
        context.create(root, "critic", out, max_file_bytes=True)
    assert not out.exists()
    out, manifest = packet(root, tmp_path)
    with pytest.raises(ValueError, match="externally retained"):
        context.read_artifact(out, manifest["artifacts"][0]["id"], expected_manifest_sha256="")
