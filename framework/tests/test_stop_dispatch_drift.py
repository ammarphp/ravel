"""stage-drift + ledger-empty Stop branch (R3 T3, H2+H8).

Run from OUTSIDE the repo: cd /tmp && python3 -m pytest <abspath> -q
"""
import json, os, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "trial-runs/_infrastructure/stop_dispatch.py"


def _mk_run(tmp, disk_stage=None, **state):
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    st = {"schema_version": 1, "session_id": "SELFTEST",
          "skills_invoked": [], "compute_launched": []}
    st.update(state)
    json.dump(st, open(os.path.join(tmp, "run_state.json"), "w"))
    if disk_stage in ("generation", "statistics", "result_pack"):
        os.makedirs(os.path.join(tmp, "outputs"), exist_ok=True)
        json.dump({"srs": {"SR1": 1.0}},
                  open(os.path.join(tmp, "outputs", "sr_yields.json"), "w"))
    if disk_stage in ("statistics", "result_pack"):
        json.dump({"mu95_obs": 1.2}, open(os.path.join(tmp, "exclusion.json"), "w"))
    if disk_stage == "result_pack":
        json.dump({"schema_version": 1}, open(os.path.join(tmp, "result.json"), "w"))
    return str(tmp)


def _run(rundir):
    return subprocess.run([sys.executable, str(SCRIPT), "--rundir", str(rundir),
                           "--last-message", "working on it", "--branch", "stage-drift"],
                          cwd=REPO, capture_output=True, text=True)


def test_drift_blocks_when_disk_ahead_of_cursor(tmp_path):
    rd = _mk_run(tmp_path, disk_stage="statistics", current_step="route",
                 skills_invoked=[{"skill": "physicist-intake"}],
                 compute_launched=[{"cmd": "x"}])
    r = _run(rd)
    assert r.returncode == 2 and "STAGE-DRIFT" in r.stderr and "advance" in r.stderr


def test_aligned_cursor_passes(tmp_path):
    rd = _mk_run(tmp_path, disk_stage="statistics", current_step="statistics",
                 skills_invoked=[{"skill": "run-stage"}], compute_launched=[{"cmd": "x"}])
    assert _run(rd).returncode == 0


def test_cursor_beyond_disk_passes(tmp_path):
    rd = _mk_run(tmp_path, disk_stage="generation", current_step="verification",
                 skills_invoked=[{"skill": "run-stage"}], compute_launched=[{"cmd": "x"}])
    assert _run(rd).returncode == 0


def test_ledger_empty_blocks(tmp_path):
    rd = _mk_run(tmp_path, disk_stage="generation", current_step="generation",
                 skills_invoked=[], compute_launched=[])
    r = _run(rd)
    assert r.returncode == 2 and "LEDGER-EMPTY" in r.stderr


def test_no_disk_progress_passes(tmp_path):
    rd = _mk_run(tmp_path, disk_stage=None, current_step="route")
    assert _run(rd).returncode == 0
