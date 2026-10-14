import json, os, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/ravel/workflow/stop_dispatch.py"

def _mk_run(tmp, **state):
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    st = {"schema_version": 1, "session_id": "SELFTEST"}; st.update(state)
    json.dump(st, open(os.path.join(tmp, "run_state.json"), "w"))
    return str(tmp)

def _run(rundir):
    return subprocess.run([sys.executable, str(SCRIPT), "--rundir", str(rundir),
                           "--last-message", "ok", "--branch", "detach"],
                          cwd=REPO, capture_output=True, text=True)

def test_detach_blocks_incomplete_entry(tmp_path):
    rd = _mk_run(tmp_path, compute_launched=[{"bg_kind": "detached", "logfile": "logs/j.log"}])
    r = _run(rd)                                # missing done_condition + next_action, no heartbeat
    assert r.returncode == 2 and "DETACH" in r.stderr

def test_detach_passes_complete_with_heartbeat(tmp_path):
    lf = os.path.join(tmp_path, "logs", "j.log")
    rd = _mk_run(tmp_path, compute_launched=[{"bg_kind": "detached", "logfile": lf,
                 "done_condition": "output/exclusion.json exists", "next_action": "harvest"}])
    open(lf, "w").write("beat")                 # recent mtime -> heartbeat
    assert _run(rd).returncode == 0

def test_detach_ignores_harness_bg(tmp_path):
    rd = _mk_run(tmp_path, compute_launched=[{"bg_kind": "harness"}])
    assert _run(rd).returncode == 0
