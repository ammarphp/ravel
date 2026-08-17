import json, os, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "trial-runs/_infrastructure/stop_dispatch.py"

def _mk_run(tmp, **state):
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    st = {"schema_version": 1, "session_id": "SELFTEST"}; st.update(state)
    json.dump(st, open(os.path.join(tmp, "run_state.json"), "w"))
    return str(tmp)

def _run(rundir, last_message, branch=None):
    cmd = [sys.executable, str(SCRIPT), "--rundir", str(rundir), "--last-message", last_message]
    if branch: cmd += ["--branch", branch]
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)

def test_selftest_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_d18_blocks_delivery_turn_on_invalid_rundir(tmp_path):
    rd = _mk_run(tmp_path)                       # no task_contract.json -> validate exits nonzero
    r = _run(rd, "Here is CHECK-IN 1 for your approval.", branch="d18")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "D18" in r.stderr

def test_d18_passes_non_delivery_turn(tmp_path):
    rd = _mk_run(tmp_path)
    r = _run(rd, "Working on the analysis; will run the smoke rung next.", branch="d18")
    assert r.returncode == 0
