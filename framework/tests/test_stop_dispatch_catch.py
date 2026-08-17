import json, os, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "trial-runs/_infrastructure/stop_dispatch.py"

def _mk_run(tmp):
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    json.dump({"schema_version": 1, "session_id": "SELFTEST"},
              open(os.path.join(tmp, "run_state.json"), "w"))
    return str(tmp)

def _run(rundir, branch="catch", last_message="ok"):
    return subprocess.run([sys.executable, str(SCRIPT), "--rundir", str(rundir),
                           "--last-message", last_message, "--branch", branch],
                          cwd=REPO, capture_output=True, text=True)

def test_catch_blocks_on_open_failure(tmp_path):
    rd = _mk_run(tmp_path)
    json.dump({"stage": "madgraph", "status": "open", "next_action": "reset"},
              open(os.path.join(rd, "logs", "madgraph.failure.json"), "w"))
    r = _run(rd)
    assert r.returncode == 2 and "CATCH" in r.stderr

def test_catch_passes_when_resolved(tmp_path):
    rd = _mk_run(tmp_path)
    json.dump({"stage": "madgraph", "status": "resolved"},
              open(os.path.join(rd, "logs", "madgraph.failure.json"), "w"))
    assert _run(rd).returncode == 0
