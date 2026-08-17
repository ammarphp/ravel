import json, os, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "trial-runs/_infrastructure/stop_dispatch.py"

def _mk_run(tmp, **state):
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    st = {"schema_version": 1, "session_id": "SELFTEST"}; st.update(state)
    json.dump(st, open(os.path.join(tmp, "run_state.json"), "w"))
    return str(tmp)

def _run(rundir, last_message):
    return subprocess.run([sys.executable, str(SCRIPT), "--rundir", str(rundir),
                           "--last-message", last_message, "--branch", "drive"],
                          cwd=REPO, capture_output=True, text=True)

def test_drive_blocks_narrate_without_execute(tmp_path):
    rd = _mk_run(tmp_path, next_required={"kind": "command", "what": "run-stage madgraph",
                                          "why": "generation stage"})
    r = _run(rd, "Next I'll generate the events.")
    assert r.returncode == 2 and "DRIVE" in r.stderr

def test_drive_passes_with_recent_compute(tmp_path):
    lf = os.path.join(tmp_path, "logs", "madgraph.log")
    rd = _mk_run(tmp_path, next_required={"what": "run-stage madgraph"},
                 compute_launched=[{"bg_kind": "harness", "logfile": lf}])
    open(lf, "w").write("running")
    assert _run(rd, "Next I'll generate the events.").returncode == 0

def test_drive_passes_on_delivery_turn(tmp_path):
    rd = _mk_run(tmp_path, next_required={"what": "run-stage madgraph"})
    assert _run(rd, "Here is CHECK-IN 1 for your approval.").returncode == 0

def test_drive_passes_when_nothing_required(tmp_path):
    rd = _mk_run(tmp_path)
    assert _run(rd, "All done.").returncode == 0
