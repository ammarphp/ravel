"""Adverse custody/ordering probes; all launches are tiny local control processes."""
import json
import sys

import pytest

from ravel.workflow import launch_authorization as launch, waypoint_evidence as evidence, workflow_state as ws
from ravel.workflow.execution import digest
from test_checkin2_gate import _run, _ws, _write_checkin2, _vrs


@pytest.fixture
def approved(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_STATE_UTC", "2026-10-08T00:00:00Z")
    root = _run(tmp_path)
    assert _ws("go", "--rundir", root, "--quote", "GO").returncode == 0
    return root


def _launch(root):
    return launch.authorized_popen(root, "full", [sys.executable, "-c", "pass"],
                                  context={"kind": "native-generation", "plan_sha256": "test-plan"})


@pytest.mark.parametrize("name", ["produced.png", "reference.png", "comparison.json", "cost_preflight.json",
                                 "waypoint_evidence.json"])
def test_reviewed_evidence_changes_void_go_and_prevent_launch(approved, monkeypatch, name):
    path = approved / "inputs" / name
    path.write_bytes(path.read_bytes() + b"\n")
    assert ws.verify_checkin2_go(str(approved))
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: pytest.fail("stale evidence launched"))
    with pytest.raises(ValueError):
        _launch(approved)


def test_go_needs_manifest_and_real_evidence(tmp_path):
    root = _run(tmp_path)
    (root / evidence.MANIFEST).unlink()
    result = _ws("go", "--rundir", root, "--quote", "GO")
    assert result.returncode == 1 and not (root / "inputs/checkin2_go.json").exists()


def test_known_failed_comparison_can_be_explicitly_approved(tmp_path):
    root = _run(tmp_path)
    _write_checkin2(root, status="fail")
    assert _ws("go", "--rundir", root, "--quote", "GO with the reviewed residual").returncode == 0
    assert _launch(root).wait() == 0
    assert launch.audit_launches(root, require_generation=True) == []
    events = launch._events(root)
    manifest = json.loads(events[0]["authorization"]["go_inputs"][2]["text"])
    assert manifest["result"]["status"] == "fail" and manifest["result"]["diagnostics"]["relative_residual"] == .4


@pytest.mark.parametrize("older_name", [False, True])
def test_later_go_cannot_authorize_already_recorded_bulk_compute(tmp_path, older_name):
    root = _run(tmp_path)
    (root / "inputs/native_execution_plan.json").write_text(json.dumps({"required_compute_plan": "full"}))
    (root / "outputs").mkdir()
    (root / "outputs/sr_yields.json").write_text('{"srs":{"SR1":1}}')
    assert _ws("go", "--rundir", root, "--quote", "GO after compute").returncode == 0
    if older_name:
        moved = root.with_name("2026-09-01_older-run-name")
        root.rename(moved)
        root = moved
    assert ws.verify_checkin2_go(str(root)) == []
    vrs = _vrs()
    contract = json.loads((root / "inputs/task_contract.json").read_text())
    status, detail = vrs.inv_checkin2_go_before_bulk_compute(str(root), contract, vrs.discover_facts(str(root), contract), False, False)
    assert status == "FAIL" and "later GO cannot backfill" in detail


def test_launch_retains_exact_approval_and_order_after_current_approval_changes(approved):
    assert _launch(approved).wait() == 0
    before = launch._events(approved)
    assert [e["event"] for e in before] == ["authorized", "launched"]
    assert before[1]["authorization_sha256"] == before[0]["sha256"]
    assert before[0]["authorization"]["go"]["sha256"] == launch.file_hash(approved / "inputs/checkin2_go.json")
    assert _ws("approve", "--rundir", approved, "--quote", "New first approval", "--plan", "full").returncode == 0
    assert ws.verify_checkin2_go(str(approved))
    assert launch._events(approved) == before
    assert launch.audit_launches(approved, require_generation=True) == []


@pytest.mark.parametrize("mutation", ["edit", "delete", "reorder", "late_approval", "missing_go", "no_launch"])
def test_corrupt_or_incomplete_launch_history_fails(approved, mutation):
    assert _launch(approved).wait() == 0
    directory = approved / launch.JOURNAL
    first, second = directory / "00000001.json", directory / "00000002.json"
    if mutation == "delete":
        first.unlink()
    elif mutation == "no_launch":
        second.unlink()
    elif mutation == "reorder":
        first.write_bytes(second.read_bytes())
    elif mutation in ("late_approval", "missing_go"):
        event = json.loads(first.read_text())
        if mutation == "missing_go":
            event["authorization"]["go"] = None
        else:
            record = json.loads(event["authorization"]["approval"]["text"])
            record["generated_utc"] = "2027-01-01T00:00:00Z"
            text = json.dumps(record)
            event["authorization"]["approval"].update(text=text, sha256=launch.provenance.sha256_bytes(text.encode()))
        event["sha256"] = digest({k: v for k, v in event.items() if k != "sha256"})
        first.write_text(json.dumps(event))
        tail = json.loads(second.read_text())
        tail.update(previous_sha256=event["sha256"], authorization_sha256=event["sha256"])
        tail["sha256"] = digest({k: v for k, v in tail.items() if k != "sha256"})
        second.write_text(json.dumps(tail))
    else:
        event = json.loads(first.read_text())
        event["command"] = ["changed"]
        first.write_text(json.dumps(event))
    assert launch.audit_launches(approved, require_generation=True)


def test_popen_failure_never_becomes_a_launch(approved, monkeypatch):
    def fail(*a, **k):
        raise OSError("control launch failed")
    monkeypatch.setattr(launch.subprocess, "Popen", fail)
    with pytest.raises(OSError):
        _launch(approved)
    assert [e["event"] for e in launch._events(approved)] == ["authorized"]
    assert launch.audit_launches(approved)


def test_receipt_capture_preserves_crlf_json_bytes(tmp_path):
    root = _run(tmp_path)
    path = root / "inputs/checkin1_approval.json"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert _ws("go", "--rundir", root, "--quote", "GO").returncode == 0
    assert _launch(root).wait() == 0
    event = launch._events(root)[0]
    assert "\r\n" in event["authorization"]["approval"]["text"]
    assert launch.audit_launches(root) == []


def test_failed_launch_event_write_stops_the_owned_process(approved, monkeypatch):
    original_append, original_popen = launch._append, launch.subprocess.Popen
    processes = []
    def append(root, event):
        if event["event"] == "launched":
            raise OSError("launch event write failed")
        return original_append(root, event)
    def popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(launch, "_append", append)
    monkeypatch.setattr(launch.subprocess, "Popen", popen)
    with pytest.raises(OSError, match="launch event write failed"):
        launch.authorized_popen(approved, "full", [sys.executable, "-c", "import time; time.sleep(30)"],
                               context={}, start_new_session=True)
    assert processes[0].poll() is not None
    assert launch.audit_launches(approved)


def test_operational_records_have_real_time_and_clock_can_be_injected(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKFLOW_STATE_UTC", raising=False)
    root = _run(tmp_path)
    assert launch.parse_utc(json.loads((root / "inputs/checkin1_approval.json").read_text())["generated_utc"])
    monkeypatch.setenv("WORKFLOW_STATE_UTC", "2027-01-01T01:02:03Z")
    assert _ws("go", "--rundir", root, "--quote", "GO").returncode == 0
    assert json.loads((root / "inputs/checkin2_go.json").read_text())["generated_utc"] == "2027-01-01T01:02:03Z"


@pytest.mark.parametrize("value", ["", "2026-10-08", "2026-10-08T00:00:00+01:00", True, []])
def test_invalid_operational_timestamps(value):
    with pytest.raises((ValueError, TypeError)):
        launch.parse_utc(value)


def test_changed_evidence_between_receipt_and_popen_is_refused(approved, monkeypatch):
    original = launch._append
    def append_then_change(root, event):
        result = original(root, event)
        if event["event"] == "authorized":
            (root / "inputs/produced.png").write_bytes(b"changed after approval capture")
        return result
    monkeypatch.setattr(launch, "_append", append_then_change)
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: pytest.fail("raced evidence launched"))
    with pytest.raises(ValueError, match="changed before Popen"):
        _launch(approved)


def test_smoke_launch_needs_first_approval_but_not_go(tmp_path):
    root = _run(tmp_path, plan="smoke", checkin2=False)
    process = launch.authorized_popen(root, "smoke", [sys.executable, "-c", "pass"], context={"kind": "native-stage"})
    assert process.wait() == 0
    assert launch._events(root)[0]["authorization"]["go"] is None
    (root / "inputs/checkin1_approval.json").unlink()
    with pytest.raises(ValueError, match="refused"):
        launch.authorized_popen(root, "smoke", [sys.executable, "-c", "pass"], context={})


def test_empty_first_approval_timestamp_does_not_authorize_live_compute(approved):
    path = approved / "inputs/checkin1_approval.json"
    doc = json.loads(path.read_text())
    doc["generated_utc"] = ""
    path.write_text(json.dumps(doc))
    assert ws.verify_approval(str(approved)) == [], "archival integrity can still be inspected"
    assert ws.verify_approval(str(approved), required_plan="smoke")


@pytest.mark.parametrize("change", ["boolean_version", "list_pin", "missing_file", "duplicate_input", "list_status"])
def test_manifest_malformed_types_and_identities_fail(approved, change):
    path = approved / evidence.MANIFEST
    manifest = json.loads(path.read_text())
    if change == "boolean_version": manifest["schema_version"] = True
    elif change == "list_pin": manifest["produced"] = []
    elif change == "missing_file": (approved / "inputs/reference.png").unlink()
    elif change == "duplicate_input": manifest["inputs"].append(manifest["inputs"][0])
    else:
        (approved / "inputs/comparison.json").write_text('{"status":[],"summary":"review","diagnostics":{"x":1}}')
        manifest["comparison"] = evidence.pin(approved, "inputs/comparison.json")
    assert evidence.validate(approved, manifest)


def test_unbound_figure_is_not_the_reviewed_waypoint(approved):
    from ravel.validation.validate_checkin import validate
    (approved / "other.png").write_bytes(b"not reviewed")
    doc = json.loads((approved / "inputs/checkin2.json").read_text())
    doc["sections"]["waypoint"] = "other.png"
    assert any("not bound" in e for e in validate(doc, base_dir=approved))


def test_supervised_full_launch_retains_receipt_and_blocks_changed_evidence(tmp_path, monkeypatch):
    from test_native_dispatch import stub_backend, configuration, approve_fixture
    from ravel.physics import native_pipeline as pipeline
    from ravel.workflow.stage_supervisor import supervise
    from ravel.workflow.state_io import read_json
    stub_backend(tmp_path, monkeypatch)
    config = configuration(tmp_path)
    config.write_text(config.read_text().replace("nevents = 2", "nevents = 1001"))
    card = tmp_path / "cards/run.dat"
    card.write_text(card.read_text().replace("2 = nevents", "1001 = nevents"))
    plan = pipeline.build_execution_plan(tmp_path, config)
    approve_fixture(plan)
    _write_checkin2(tmp_path)
    assert _ws("go", "--rundir", tmp_path, "--quote", "GO synthetic receipt control").returncode == 0
    assert plan["required_compute_plan"] == "full"
    # The fixture backend writes two synthetic events regardless of requested size.
    # Stop after generation: this tests authorization, not event-count/physics closure.
    for stage in plan["stages"][:2]:
        assert supervise(stage["stage"], str(tmp_path), plan["nevents"], "logs/" + stage["stage"] + ".log",
                         stage["command"], inputs=stage["inputs"], outputs=stage["outputs"],
                         depends_on=stage["depends_on"], cwd=str(tmp_path), poll=.005, grace=.1) == 0
    assert launch.audit_launches(tmp_path, plan_sha256=plan["plan_sha256"], require_generation=True) == []
    ledger = read_json(tmp_path / "execution_state.json")
    assert ledger["stages"]["madgraph"]["authorization_receipt"]["sha256"]
    (tmp_path / "inputs/produced.png").write_bytes(b"changed after reviewed launch")
    stage = plan["stages"][2]
    assert supervise(stage["stage"], str(tmp_path), plan["nevents"], "logs/next.log", stage["command"],
                     inputs=stage["inputs"], outputs=stage["outputs"], depends_on=stage["depends_on"],
                     cwd=str(tmp_path), poll=.005, grace=.1) != 0
    assert launch.audit_launches(tmp_path, plan_sha256=plan["plan_sha256"], require_generation=True) == []
    # An execution ledger cannot substitute a different PID for the retained launch.
    ledger["stages"]["madgraph"]["child_pid"] += 1
    (tmp_path / "execution_state.json").write_text(json.dumps(ledger))
    assert launch.audit_launches(tmp_path, require_generation=True)


@pytest.mark.parametrize("defect", [None, "missing_receipt", "shared_run"])
def test_scan_aggregate_checks_every_reported_point(tmp_path, defect):
    parent = _run(tmp_path / "parent", plan="scan")
    assert _ws("go", "--rundir", parent, "--quote", "GO campaign").returncode == 0
    points = []
    for tag in ("p1", "p2"):
        child = _run(tmp_path / tag, plan="scan")
        assert _ws("go", "--rundir", child, "--quote", "GO point").returncode == 0
        plan = {"required_compute_plan": "scan", "plan_sha256": "plan-" + tag}
        (child / "inputs/native_execution_plan.json").write_text(json.dumps(plan))
        if tag != "p2" or defect != "missing_receipt":
            process = launch.authorized_popen(child, "scan", [sys.executable, "-c", "pass"],
                          context={"kind": "native-generation", "plan_sha256": plan["plan_sha256"]})
            assert process.wait() == 0
        points.append({"tag": tag, "run_dir": str(child)})
    if defect == "shared_run":
        points[1]["run_dir"] = points[0]["run_dir"]
    manifest, scan = {"points": points}, {"points": [{"tag": p["tag"], "mu95_obs": 1} for p in points]}
    facts = {"statistics_artifact_name": "scan.json", "statistics_path": "scan.json",
             "scan_doc": scan, "scan_manifest_doc": manifest}
    contract = json.loads((parent / "inputs/task_contract.json").read_text())
    contract["task_mode"] = "scan"
    status, detail = _vrs().inv_checkin2_go_before_bulk_compute(str(parent), contract, facts, False, False)
    assert status == ("FAIL" if defect else "PASS"), detail


@pytest.mark.parametrize("record", [[], True, {"schema_version": True, "params": []},
                                    {"schema_version": 1, "params": [None]},
                                    {"schema_version": 1, "params": [{"name": [], "status": "PASS"}]}])
def test_parameter_artifact_malformed_types_return_errors(tmp_path, record):
    from ravel.validation.validate_parameters import load_validations
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs/validations.json").write_text(json.dumps(record))
    doc, error = load_validations(str(tmp_path))
    assert doc is None and error


@pytest.mark.parametrize("value", [[], {"traps_checked": [["T1"]]}, {"traps_checked": [True]},
                                   {"traps_checked": ["T1", "T1"]}])
def test_trap_artifact_malformed_types_return_errors(tmp_path, value):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs/trap_sweep.json").write_text(json.dumps(value))
    status, _path, _checks = _vrs().check_trap_sweep(str(tmp_path), {}, {"trap_sweep_path": "inputs/trap_sweep.json"}, "R", False)
    assert status == "FAIL"


@pytest.mark.parametrize("field,value", [("verdicts", True), ("escalations", [{"id": []}]),
                                        ("traps_hit", [{"id": {}}])])
def test_other_trap_rows_are_type_checked(tmp_path, field, value):
    vrs = _vrs()
    doc = vrs._trap_sweep_doc()
    doc[field] = value
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs/trap_sweep.json").write_text(json.dumps(doc))
    assert vrs.check_trap_sweep(str(tmp_path), {}, {"trap_sweep_path": "inputs/trap_sweep.json"}, "R", False)[0] == "FAIL"
