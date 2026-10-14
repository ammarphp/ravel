"""Anchor verification by kind (RDJ §5.3) on synthetic runs with real execution receipts."""
import json
import sys

import pytest

from ravel.workflow import rdj_anchor, rdj_custody

from rdj_fixtures import Run, sha


@pytest.fixture(autouse=True)
def custody(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))


def anchor(spec, locator=None, value=None):
    return {"id": "a", "kind": spec["kind"], "binding": spec["binding"],
            "locator": spec.get("locator", "") if locator is None else locator, "value": value, "quantity": None,
            "verified": None}


def context(run):
    return {"rundir": str(run.root), "input_snapshot": rdj_custody.input_snapshot(run.root),
            "generated": sorted(rdj_anchor.generated_paths(run.root)), "action_pins": []}


def test_measurement_needs_the_registered_validator_module_and_its_digest(tmp_path):
    run = Run(tmp_path / "run")
    cert = run.stage("cert", "outputs/cert.json", {"pass": True}, kind="measurement")
    assert rdj_anchor.verify(anchor(cert, "/pass", True), run.root, context=context(run)) == "external"
    assert rdj_anchor.verify(anchor(cert, "/pass", False), run.root, context=context(run)) == "invalid"
    other = run.stage("cert2", "outputs/cert2.json", {"pass": True}, [sys.executable, "my_checker.py"],
                      kind="measurement")
    assert rdj_anchor.verify(anchor(other), run.root, context=context(run)) == "invalid"
    renamed = {**cert, "binding": {**cert["binding"], "validator_id": "my_checker"}}
    assert rdj_anchor.verify(anchor(renamed), run.root, context=context(run)) == "invalid"


def test_model_call_output_is_generated_not_a_tool_output(tmp_path):
    run = Run(tmp_path / "run")
    summary = run.stage("summary", "outputs/summary.json", {"ok": 1}, [sys.executable, "-m", "ravel.workflow.agent_graph"])
    assert rdj_anchor.verify(anchor(summary), run.root, context=context(run)) == "generated"


def test_native_tool_output_is_external(tmp_path):
    run = Run(tmp_path / "run")
    out = run.stage("shower", "outputs/events.json", {"n": 10}, ["pythia_shower", "--config", "x"])
    assert rdj_anchor.verify(anchor(out), run.root, context=context(run)) == "external"


def test_broker_receipts_stay_generated_until_the_broker_ledger_verifies(tmp_path):
    run = Run(tmp_path / "run")
    out = run.put("agent-work/N1/1/outputs/table.json", {"rows": 3})
    for derivation in ("toolchain", "registered_validator", "retrieval"):
        run.put("agent-work/N1/1/calls/4.json", {"schema_version": 1, "kind": "broker-receipt", "receipt_id": "N1/1/4",
                                                 "exit_status": 0, "derivation": derivation, "output_pins": [out]})
        spec = {"kind": "tool_output", "binding": {"receipt_id": "N1/1/4", "output_path": out["path"],
                                                   "sha256": out["sha256"]}}
        assert rdj_anchor.verify(anchor(spec), run.root, context=context(run)) == "generated"


def test_reference_data_is_an_input_recorded_before_the_case(tmp_path):
    run = Run(tmp_path / "run", extra_inputs=[("inputs/reference/table.json", {"value": 0.3})])
    spec = {"kind": "external_fact", "binding": {"record_id": "ins123/t1", "file": run.pin("inputs/reference/table.json")}}
    status, _, observed = rdj_anchor.verify_full(anchor(spec, "/value"), run.root, context=context(run))
    assert status == "external" and observed == 0.3


def test_symlinks_and_escapes_are_invalid(tmp_path):
    (tmp_path / "outside.json").write_text("{}")
    run = Run(tmp_path / "run")
    (run.root / "inputs/link.json").symlink_to(tmp_path / "outside.json")
    pin = {"path": "inputs/link.json", "sha256": sha("{}")}
    spec = {"kind": "input_artifact", "binding": pin}
    assert rdj_anchor.verify(anchor(spec), run.root, context=context(run)) == "invalid"
    escape = {"kind": "input_artifact", "binding": {"path": "../outside.json", "sha256": pin["sha256"]}}
    assert rdj_anchor.verify(anchor(escape), run.root, context=context(run)) == "invalid"


def test_whole_file_value_is_the_text_shown_to_the_reviewer(tmp_path):
    run = Run(tmp_path / "run", extra_inputs=[("inputs/notes.txt", "Use the published binning.")])
    spec = {"kind": "input_artifact", "binding": run.pin("inputs/notes.txt")}
    status, _, observed = rdj_anchor.verify_full(anchor(spec), run.root, context=context(run))
    assert status == "external" and observed == "Use the published binning."
    shown = rdj_anchor.describe({**anchor(spec), "verified": status}, observed)
    assert shown["value"] == "Use the published binning." and "authority" not in shown


def test_generated_paths_include_model_worker_outputs(tmp_path):
    run = Run(tmp_path / "run")
    run.put("agent-work/N1/1/final.json", {"ok": 1})
    run.put("agent-work/N1/1/scratch/notes.json", {"ok": 1})
    run.put("agent-work/N1/1/receipt.json", {"ok": 1})
    found = rdj_anchor.generated_paths(run.root)
    assert {"agent-work/N1/1/final.json", "agent-work/N1/1/scratch/notes.json"} <= found
    assert "agent-work/N1/1/receipt.json" not in found
    log = run.root / "agent-audit/writes.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"path": str(run.root / "outputs/x.json"), "sha256": "0" * 64, "session_id": "s"}) + "\n")
    assert "outputs/x.json" in rdj_anchor.generated_paths(run.root)
