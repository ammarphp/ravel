"""CHECK-IN 2: a recorded GO, bound to the CHECK-IN 2 artefact and the current CHECK-IN 1 approval,
gates compute beyond the smoke run (the full sample and the scan).

Run from OUTSIDE the repo: cd /tmp && python3 -m pytest <abspath> -q
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ravel.workflow import workflow_state, waypoint_evidence, launch_authorization  # noqa: E402

WS = REPO / "src" / "ravel" / "workflow" / "workflow_state.py"
VRS = REPO / "src" / "ravel" / "validation" / "validate_run_state.py"
GUARD = REPO / ".claude" / "hooks" / "pretooluse-bash.sh"

CHECKIN1 = {"schema_version": 1, "kind": "checkin1", "sections": {
    "i": "req", "i-b": "census", "ii": "gallery prose",
    "iii": {"plan": "x", "waypoint": "the simulation-only background in SR1"}, "iv": "budget",
    "v": [{"id": "F1", "text": "assume"}], "vi": ["answer", "ask", "propose"]}}
CHECKIN2 = {"schema_version": 1, "kind": "checkin2", "sections": {
    "waypoint": "The simulation-only background in SR1, beside the published one",
    "expectation": "Shapes agree within the smoke statistics",
    "ask": {"options": [{"name": "GO"}, {"name": "ADJUST"}]}}}


def _vrs():
    spec = importlib.util.spec_from_file_location("vrs_checkin2", VRS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ws(*args):
    return subprocess.run([sys.executable, str(WS), *map(str, args)], cwd=REPO, capture_output=True, text=True)


def _write_inputs(rd, plan, session=None):
    (rd / "inputs").mkdir(parents=True, exist_ok=True)
    budget = {"schema_version": 1, "generated_by": "cost_preflight.py", "mode": plan, "walltime_h": [0.5, 1],
              "points": 4 if plan == "scan" else 1, "events_per_point": 10000, "backend": "native"}
    contract = _vrs()._base_contract(task_mode="reproduce", compute_plan=plan, targets={"model": "svj-tchannel"})
    if plan in ("full", "scan"):
        contract["cost_estimate"] = budget
    (rd / "inputs" / "task_contract.json").write_text(json.dumps(contract))
    (rd / "inputs" / "checkin1.json").write_text(json.dumps(CHECKIN1))
    (rd / "inputs" / "cost_preflight.json").write_text(json.dumps(budget))
    if session is not None:
        (rd / "run_state.json").write_text(json.dumps({"schema_version": 1, "session_id": session}))


def _write_checkin2(rd, *, status="pass"):
    for name in ("produced.png", "reference.png"):
        (rd / "inputs" / name).write_bytes(name.encode())
    (rd / "inputs/comparison.json").write_text(json.dumps({
        "status": status, "summary": "Smoke comparison reviewed", "diagnostics": {"relative_residual": 0.4}}))
    manifest = waypoint_evidence.create(rd, produced="inputs/produced.png", reference="inputs/reference.png",
                                       comparison="inputs/comparison.json", inputs=["inputs/cost_preflight.json"])
    (rd / waypoint_evidence.MANIFEST).write_text(json.dumps(manifest))
    checkin = json.loads(json.dumps(CHECKIN2))
    checkin["sections"]["evidence_manifest"] = waypoint_evidence.MANIFEST
    (rd / "inputs/checkin2.json").write_text(json.dumps(checkin))


def _run(tmp_path, plan="full", approve=True, checkin2=True):
    rd = tmp_path / "2026-10-07_TEST_checkin2"
    _write_inputs(rd, plan)
    if approve:
        result = _ws("approve", "--rundir", rd, "--quote", "Yes, run the plan", "--plan", plan)
        assert result.returncode == 0, result.stderr
    if checkin2:
        _write_checkin2(rd)
    return rd


def test_go_refuses_without_a_checkin2_artefact(tmp_path):
    rd = _run(tmp_path, checkin2=False)
    result = _ws("go", "--rundir", rd, "--quote", "GO")
    assert result.returncode == 1 and "checkin2" in result.stderr
    assert not (rd / "inputs" / "checkin2_go.json").exists()


def test_go_refuses_an_invalid_checkin2(tmp_path):
    rd = _run(tmp_path)
    bad = json.loads((rd / "inputs/checkin2.json").read_text())
    bad["sections"]["ask"]["options"] = [{"name": "GO"}]
    (rd / "inputs" / "checkin2.json").write_text(json.dumps(bad))
    result = _ws("go", "--rundir", rd, "--quote", "GO")
    assert result.returncode == 1 and "ADJUST" in result.stderr


def test_go_refuses_without_a_valid_checkin1_approval(tmp_path):
    rd = _run(tmp_path, approve=False)
    result = _ws("go", "--rundir", rd, "--quote", "GO")
    assert result.returncode == 1 and "checkin1_approval" in result.stderr


def test_go_writes_a_record_bound_to_checkin2_and_the_approval(tmp_path):
    rd = _run(tmp_path)
    result = _ws("go", "--rundir", rd, "--quote", "GO: the background matches")
    assert result.returncode == 0, result.stderr
    doc = json.loads((rd / "inputs" / "checkin2_go.json").read_text())
    assert doc["schema_version"] == 2 and doc["generated_by"] == "workflow_state.py go"
    assert doc["decision"] == "GO" and doc["quote"] == "GO: the background matches"
    assert doc["checkin2"] == "inputs/checkin2.json"
    assert doc["checkin1_approval"] == "inputs/checkin1_approval.json"
    assert len(doc["input_fingerprint"]) == 64
    assert workflow_state.verify_checkin2_go(str(rd)) == []


def test_a_new_checkin1_approval_voids_the_go(tmp_path):
    rd = _run(tmp_path)
    assert _ws("go", "--rundir", rd, "--quote", "GO").returncode == 0
    assert _ws("approve", "--rundir", rd, "--quote", "Approved again after a change", "--plan", "full").returncode == 0
    errors = workflow_state.verify_checkin2_go(str(rd))
    assert errors and "stale" in errors[0]


def test_an_edited_checkin2_voids_the_go(tmp_path):
    rd = _run(tmp_path)
    assert _ws("go", "--rundir", rd, "--quote", "GO").returncode == 0
    path = rd / "inputs" / "checkin2.json"
    path.write_text(path.read_text() + "\n")
    assert workflow_state.verify_checkin2_go(str(rd))


def test_a_hand_written_go_is_rejected(tmp_path):
    rd = _run(tmp_path)
    (rd / "inputs" / "checkin2_go.json").write_text(json.dumps({
        "schema_version": 1, "generated_by": "workflow_state.py go", "generated_utc": "", "decision": "GO",
        "quote": "GO", "checkin2": "inputs/checkin2.json", "checkin1_approval": "inputs/checkin1_approval.json",
        "input_fingerprint": "0" * 64}))
    assert workflow_state.verify_checkin2_go(str(rd))


@pytest.mark.parametrize("rung,needs_go", [("none", False), ("dry", False), ("smoke", False),
                                           ("full", True), ("scan", True)])
def test_only_compute_beyond_the_smoke_run_needs_the_go(tmp_path, rung, needs_go):
    rd = _run(tmp_path, plan="scan")
    assert bool(workflow_state.checkin2_gate_errors(str(rd), rung)) is needs_go
    assert _ws("go", "--rundir", rd, "--quote", "GO").returncode == 0
    assert workflow_state.checkin2_gate_errors(str(rd), rung) == []


def _guard(command, project, cwd, session):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd), "session_id": session}
    return subprocess.run(["bash", str(GUARD)], input=json.dumps(payload), capture_output=True, text=True, env=env)


def _project(tmp_path):
    rd = tmp_path / "trial-runs" / "run1"
    shutil.copytree(REPO / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _write_inputs(rd, "scan", session="S1")
    (rd / "inputs" / "generation_recipe.json").write_text("{}")
    assert _ws("approve", "--rundir", rd, "--quote", "Yes, run the scan", "--plan", "scan").returncode == 0
    _write_checkin2(rd)
    return rd


SCAN_LAUNCH = "python3 src/ravel/workflow/scan_orchestrator.py launch --manifest trial-runs/run1/scan.toml --go"


def test_guard_blocks_a_scan_launch_without_the_go(tmp_path):
    rd = _project(tmp_path)
    result = _guard(SCAN_LAUNCH, tmp_path, rd, "S1")
    assert result.returncode == 2 and "CHECK-IN 2" in result.stderr


def test_guard_allows_a_scan_launch_after_the_go(tmp_path):
    rd = _project(tmp_path)
    assert _ws("go", "--rundir", rd, "--quote", "GO").returncode == 0
    result = _guard(SCAN_LAUNCH, tmp_path, rd, "S1")
    assert result.returncode == 0, result.stderr


def _native_run(tmp_path, rung, go):
    vrs = _vrs()
    rd = _run(tmp_path)
    if go:
        assert _ws("go", "--rundir", rd, "--quote", "GO").returncode == 0
        process = launch_authorization.authorized_popen(rd, rung, [sys.executable, "-c", "pass"],
                       context={"kind": "native-generation", "plan_sha256": "test-plan"})
        assert process.wait() == 0
    (rd / "inputs" / "native_execution_plan.json").write_text(json.dumps({
        "required_compute_plan": rung, "plan_sha256": "test-plan"}))
    (rd / "outputs").mkdir(exist_ok=True)
    (rd / "outputs" / "sr_yields.json").write_text(json.dumps({"srs": {"SR1": 1.0}}))
    contract = json.loads((rd / "inputs" / "task_contract.json").read_text())
    facts = vrs.discover_facts(str(rd), contract)
    return vrs.inv_checkin2_go_before_bulk_compute(str(rd), contract, facts, False, False)


def test_invariant_fails_a_full_run_without_the_go(tmp_path):
    status, detail = _native_run(tmp_path, "full", go=False)
    assert status == "FAIL" and "CHECK-IN 2" in detail


def test_invariant_passes_a_full_run_with_the_go(tmp_path):
    status, _detail = _native_run(tmp_path, "full", go=True)
    assert status == "PASS"


def test_invariant_does_not_ask_for_the_go_at_the_smoke_waypoint(tmp_path):
    status, _detail = _native_run(tmp_path, "smoke", go=False)
    assert status == "PASS"


def test_the_approval_check_holds_full_and_scan_launches_until_the_go(tmp_path):
    """The native pipeline, the scan budget and the Bash guard all call verify_approval with the launch size."""
    rd = _run(tmp_path, plan="scan")
    assert workflow_state.verify_approval(str(rd), required_plan="smoke") == []
    for rung in ("full", "scan"):
        errors = workflow_state.verify_approval(str(rd), required_plan=rung)
        assert errors and "CHECK-IN 2" in errors[0]
    assert workflow_state.verify_approval(str(rd)) == [], "a size-less check (status, validator) is not a launch"
    assert _ws("go", "--rundir", rd, "--quote", "GO").returncode == 0
    assert workflow_state.verify_approval(str(rd), required_plan="scan") == []


def test_scoped_runs_have_no_checkin2(tmp_path):
    """The scoped route carries one bounded calculation with no waypoint, so its full launch needs no go."""
    rd = tmp_path / "scoped"
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    for args in (["initiate", "--prompt", "Compute a likelihood-only check from the supplied counting model.",
                  "--out", str(rd)],
                 ["plan", "--rundir", str(rd), "--spec", str(REPO / "benchmarks/scoped/atlas-2jl-counting.json")],
                 ["approve", "--rundir", str(rd), "--quote", "Yes, run this exact plan."]):
        result = subprocess.run([sys.executable, "-m", "ravel", *args], cwd=tmp_path, env=env,
                                capture_output=True, text=True, stdin=subprocess.DEVNULL)
        assert result.returncode == 0, result.stdout + result.stderr
    assert workflow_state.verify_approval(str(rd), required_plan="full") == []
