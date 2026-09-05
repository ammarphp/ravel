import json, os, subprocess, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/ravel/workflow/stop_dispatch.py"

def _mk_run(tmp, **state):
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    st = {"schema_version": 1, "session_id": "SELFTEST"}; st.update(state)
    json.dump(st, open(os.path.join(tmp, "run_state.json"), "w"))
    return str(tmp)

def _run(rundir, last_message):
    return subprocess.run([sys.executable, str(SCRIPT), "--rundir", str(rundir),
                           "--last-message", last_message, "--branch", "phantom"],
                          cwd=REPO, capture_output=True, text=True)

def test_phantom_blocks_claim_without_live_bg(tmp_path):
    rd = _mk_run(tmp_path)                    # no compute_launched -> nothing live
    r = _run(rd, "The scan is now running in the background; I'll report when it finishes.")
    assert r.returncode == 2 and "PHANTOM" in r.stderr

def test_phantom_passes_with_recent_logfile(tmp_path):
    lf = os.path.join(tmp_path, "logs", "orchestrator_launch.log")
    rd = _mk_run(tmp_path, compute_launched=[{"bg_kind": "harness", "logfile": lf}])
    open(lf, "w").write("running")            # mtime = now -> live
    r = _run(rd, "The scan is now running in the background.")
    assert r.returncode == 0

def test_phantom_passes_when_no_claim(tmp_path):
    rd = _mk_run(tmp_path)
    assert _run(rd, "I finished the analysis and here are the numbers.").returncode == 0
