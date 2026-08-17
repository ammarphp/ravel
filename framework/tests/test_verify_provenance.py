"""validate_run_state.py --verify-provenance -- the provenance gate (Phase 1, Task 1.7 / G19).

Run from /tmp: cd /tmp && python3 -m pytest <abspath> -q
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VALIDATE_RUN_STATE_PY = REPO / "trial-runs" / "_infrastructure" / "validate_run_state.py"
WORKFLOW_STATE_PY = REPO / "trial-runs" / "_infrastructure" / "workflow_state.py"

_SURVEY_CONTRACT = {
    "prompt": "selftest", "task_mode": "survey", "detector_mode": "particle-level",
    "stat_mode": "none-survey", "required_user_inputs": [], "assumptions": ["fx"],
    "compute_plan": "none", "approval_required": True,
}


def _run(rd):
    return subprocess.run([sys.executable, str(VALIDATE_RUN_STATE_PY),
                           "--rundir", str(rd), "--verify-provenance"],
                          cwd=REPO, capture_output=True, text=True)


def _init(tmp_path):
    rd = tmp_path / "run"
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs" / "task_contract.json").write_text(json.dumps(_SURVEY_CONTRACT))
    r = subprocess.run([sys.executable, str(WORKFLOW_STATE_PY), "init", "--rundir", str(rd)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return rd


def test_genuine_run_state_passes(tmp_path):
    rd = _init(tmp_path)
    r = _run(rd)
    assert r.returncode == 0, r.stdout + r.stderr


def test_absent_run_state_is_na_not_fail(tmp_path):
    rd = tmp_path / "run"
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs" / "task_contract.json").write_text(json.dumps(_SURVEY_CONTRACT))
    r = _run(rd)                                     # no run_state.json -> N/A, not FAIL
    assert r.returncode == 0, r.stdout + r.stderr


def test_handwritten_run_state_rejected(tmp_path):
    rd = _init(tmp_path)
    st = json.loads((rd / "run_state.json").read_text())
    del st["generated_by"]                           # hand-written / backfilled
    (rd / "run_state.json").write_text(json.dumps(st, indent=2))
    r = _run(rd)
    assert r.returncode == 1, r.stdout + r.stderr


def test_fingerprint_drift_rejected(tmp_path):
    rd = _init(tmp_path)
    c = json.loads((rd / "inputs" / "task_contract.json").read_text())
    c["notes"] = "edited after the fingerprint was taken"
    (rd / "inputs" / "task_contract.json").write_text(json.dumps(c))
    r = _run(rd)                                     # stored fingerprint no longer matches
    assert r.returncode == 1, r.stdout + r.stderr


def test_existing_selftest_still_passes():
    r = subprocess.run([sys.executable, str(VALIDATE_RUN_STATE_PY), "--selftest"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr    # regression guard on the 5+2 fixture selftest
