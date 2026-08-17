"""The approval chain (R3 T2, H1): workflow_state approve + the pre-exec Bash guard + invariant.

Run from OUTSIDE the repo: cd /tmp && python3 -m pytest <abspath> -q
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WS = REPO / "trial-runs" / "_infrastructure" / "workflow_state.py"
VRS = REPO / "trial-runs" / "_infrastructure" / "validate_run_state.py"
GUARD = REPO / ".claude" / "hooks" / "pretooluse-bash.sh"


def _vrs():
    spec = importlib.util.spec_from_file_location("vrs_r3t2", VRS)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _ws(*args):
    return subprocess.run([sys.executable, str(WS), *args], cwd=REPO,
                          capture_output=True, text=True)


VALID_CHECKIN1 = {"schema_version": 1, "kind": "checkin1", "sections": {
    "i": "req", "i-b": "census", "ii": "gallery prose",
    "iii": {"plan": "x", "waypoint": "wp"}, "iv": "budget",
    "v": [{"id": "F1", "text": "assume"}], "vi": ["answer", "ask", "propose"]}}


def _rundir(tmp_path, with_checkin=True, with_cost=True):
    rd = tmp_path / "2026-08-05_TEST_approve"
    (rd / "inputs").mkdir(parents=True)
    if with_checkin:
        (rd / "inputs" / "checkin1.json").write_text(json.dumps(VALID_CHECKIN1))
    if with_cost:
        (rd / "inputs" / "cost_preflight.json").write_text(json.dumps(
            {"schema_version": 1, "generated_by": "cost_preflight.py",
             "mode": "smoke", "walltime_h": [0.5, 1]}))
    return rd


def test_approve_refuses_without_checkin1(tmp_path):
    rd = _rundir(tmp_path, with_checkin=False)
    r = _ws("approve", "--rundir", str(rd), "--quote", "GO ahead")
    assert r.returncode == 1 and "checkin1" in (r.stderr + r.stdout)


def test_approve_refuses_without_cost_artifact(tmp_path):
    rd = _rundir(tmp_path, with_cost=False)
    r = _ws("approve", "--rundir", str(rd), "--quote", "GO ahead")
    assert r.returncode == 1 and "cost_preflight" in (r.stderr + r.stdout)


def test_approve_writes_artifact(tmp_path):
    rd = _rundir(tmp_path)
    r = _ws("approve", "--rundir", str(rd), "--quote", "GO — approved, F1 answered", "--plan", "smoke")
    assert r.returncode == 0, r.stderr
    doc = json.loads((rd / "inputs" / "checkin1_approval.json").read_text())
    assert doc["generated_by"] == "workflow_state.py approve"
    assert doc["approved_plan"] == "smoke" and "GO" in doc["quote"]


def _guard(command, project_dir, cwd, session=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    if session is not None:
        payload["session_id"] = session
    return subprocess.run(["bash", str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)


def _skel(tmp_path, plan="smoke", approved=False, recipe=True):
    """A project skeleton with one session-scoped run."""
    proj = tmp_path
    rd = proj / "trial-runs" / "run1"
    (rd / "inputs").mkdir(parents=True)
    (rd / "run_state.json").write_text(json.dumps({"schema_version": 1, "session_id": "S1"}))
    (rd / "inputs" / "task_contract.json").write_text(json.dumps(
        {"compute_plan": plan, "targets": {"model": "svj-tchannel"}}))
    (rd / "inputs" / "generation_recipe.json").write_text("{}") if recipe else None
    if approved:
        (rd / "inputs" / "checkin1_approval.json").write_text(json.dumps(
            {"schema_version": 1, "generated_by": "workflow_state.py approve",
             "approved_plan": plan, "quote": "GO"}))
    return proj, rd


def test_guard_blocks_detached_gen():
    r = _guard("nohup ./bin/generate_events &", REPO, REPO, session="NOSESSION-X")
    assert r.returncode == 2 and "nohup" in r.stderr.lower() or "detach" in r.stderr.lower()


def test_guard_blocks_unapproved_smoke_gen(tmp_path):
    proj, rd = _skel(tmp_path, approved=False)
    r = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml",
               proj, rd, session="S1")
    assert r.returncode == 2 and "approve" in r.stderr


def test_guard_allows_approved_supervised_gen(tmp_path):
    proj, rd = _skel(tmp_path, approved=True)
    r = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml",
               proj, rd, session="S1")
    assert r.returncode == 0, r.stderr


def test_guard_blocks_unsupervised_gen(tmp_path):
    proj, rd = _skel(tmp_path, approved=True)
    r = _guard("./bin/mg5_aMC run.mg5", proj, rd, session="S1")
    assert r.returncode == 2 and ("wrap" in r.stderr.lower() or "supervis" in r.stderr.lower())


def test_guard_passes_non_gen_bash(tmp_path):
    proj, rd = _skel(tmp_path, approved=False)
    r = _guard("ls -la && git status", proj, rd, session="S1")
    assert r.returncode == 0


def test_guard_passes_dev_session(tmp_path):
    (tmp_path / "trial-runs").mkdir()
    r = _guard("./bin/mg5_aMC run.mg5", tmp_path, tmp_path, session="DEV1")
    assert r.returncode == 0


def test_invariant_fails_without_approval(tmp_path):
    vrs = _vrs()
    rd = tmp_path / "2026-08-05_TEST_inv"
    (rd / "inputs").mkdir(parents=True); (rd / "outputs").mkdir()
    contract = vrs._base_contract(task_mode="reproduce", compute_plan="smoke")
    vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
    vrs._write_json(str(rd / "outputs" / "sr_yields.json"), {"srs": {"SR1": 1.0}})
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_approval_before_compute(str(rd), contract, facts, False, False)
    assert status == "FAIL" and "approve" in detail
