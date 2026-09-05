import json, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/ravel/validation/verify_pack.py"

def test_verify_pack_selftest_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_open_defect_note_fails(tmp_path):
    rd = tmp_path / "run"; rd.mkdir()
    (rd / "run_state.json").write_text(json.dumps(
        {"open_defect_notes": [{"helper": "read_yoda.py", "note": "A×e reads 956%", "status": "open"}]}))
    r = subprocess.run([sys.executable, str(SCRIPT), str(rd)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "open defect note" in (r.stdout + r.stderr).lower()

def test_fixed_defect_note_ok(tmp_path):
    rd = tmp_path / "run"; rd.mkdir()
    (rd / "run_state.json").write_text(json.dumps(
        {"open_defect_notes": [{"helper": "read_yoda.py", "note": "fixed", "status": "fixed"}]}))
    r = subprocess.run([sys.executable, str(SCRIPT), str(rd)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_open_defect_stop_branch(tmp_path):
    # D-4/G26: the branch THIS task registers in stop_dispatch.py must BLOCK (exit 2 + token) a DELIVERY
    # turn-end with an OPEN defect note, but NOT gate a non-delivery turn (gated on ctx['is_delivery']).
    STOP = REPO / "src/ravel/workflow/stop_dispatch.py"
    rd = tmp_path / "run"; rd.mkdir()
    (rd / "run_state.json").write_text(json.dumps(
        {"session_id": "T", "open_defect_notes": [
            {"helper": "read_yoda.py", "note": "A x e reads 956%", "status": "open"}]}))
    blocked = subprocess.run([sys.executable, str(STOP), "--rundir", str(rd),
                              "--last-message", "Here is the results deck.",
                              "--branch", "open-defect"], cwd=REPO, capture_output=True, text=True)
    assert blocked.returncode == 2 and "G26-OPEN-DEFECT" in blocked.stderr, blocked.stdout + blocked.stderr
    nondelivery = subprocess.run([sys.executable, str(STOP), "--rundir", str(rd),
                                  "--last-message", "still working on it",
                                  "--branch", "open-defect"], cwd=REPO, capture_output=True, text=True)
    assert nondelivery.returncode == 0, nondelivery.stdout + nondelivery.stderr
