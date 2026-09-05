"""pairing_check.py's pairing_check.json machine artifact (Task 3.1, D11 triage gate).

pairing_check.py ran and printed but was unwired -- no record survived a run for the lifecycle
validator (validate_run_state.py, next task) to key off. These tests pin: the CLI's existing
exit 0/1 behaviour is UNCHANGED, a pairing_check.json is written every run (verdict=='pass' iff
paired and no mismatches -- the same condition that decides the exit code), and both the matched
and mismatched directions produce a JSON with the right verdict.

Import the module under test by file path, not by package import: the repo root carries a
`py.py` file that shadows the real `py` package pytest depends on internally if the repo root
ends up on sys.path. Run this file from OUTSIDE the repo:
    cd /tmp && python3 -m pytest <this file's abspath> -q
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAIRING_CHECK_PY = REPO / "src" / "ravel" / "validation" / "pairing_check.py"


def _load_pairing_check():
    spec = importlib.util.spec_from_file_location("pairing_check_under_test", PAIRING_CHECK_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_selftest_passes():
    result = subprocess.run([sys.executable, str(PAIRING_CHECK_PY), "--selftest"],
                             cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "verdict=pass" in result.stdout
    assert "verdict=fail" in result.stdout


def _make_workspace(tmp_path):
    ws = {
        "channels": [
            {"name": "SR", "samples": [{"name": "bkg", "data": [5.0, 6.0]}]},
            {"name": "CR", "samples": [{"name": "bkg", "data": [10.0]}]},
        ],
        "observations": [
            {"name": "SR", "data": [5, 6]},
            {"name": "CR", "data": [10]},
        ],
    }
    ws_path = tmp_path / "bkg.json"
    ws_path.write_text(json.dumps(ws))
    return ws_path


def test_matched_pair_exits_zero_and_writes_pass_json(tmp_path):
    ws_path = _make_workspace(tmp_path)
    patch = [{"op": "add", "path": "/channels/0/samples/0",
              "value": {"name": "sig", "data": [1.0, 1.0],
                        "modifiers": [{"type": "normfactor", "name": "mu"}]}}]
    patch_path = tmp_path / "patch_ok.json"
    patch_path.write_text(json.dumps(patch))

    result = subprocess.run(
        [sys.executable, str(PAIRING_CHECK_PY), "--bkg", str(ws_path), "--patch", str(patch_path),
         "--timestamp", "2026-07-08T00:00:00Z"],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PAIRING CHECK PASS" in result.stdout

    out_path = tmp_path / "pairing_check.json"      # default: beside --patch
    assert out_path.is_file()
    rec = json.loads(out_path.read_text())
    assert rec["schema_version"] == 1
    assert rec["generated_utc"] == "2026-07-08T00:00:00Z"
    assert rec["generator"] == "pairing_check.py"
    assert rec["paired"] is True
    assert rec["mismatches"] == []
    assert rec["verdict"] == "pass"
    assert rec["n_channels"] == 2


def test_mismatched_pair_exits_one_and_writes_fail_json(tmp_path):
    ws_path = _make_workspace(tmp_path)
    # workspace SR has 2 bins; patch adds only 1 -> bin-count mismatch
    patch = [{"op": "add", "path": "/channels/0/samples/0",
              "value": {"name": "sig", "data": [1.0],
                        "modifiers": [{"type": "normfactor", "name": "mu"}]}}]
    patch_path = tmp_path / "patch_bad.json"
    patch_path.write_text(json.dumps(patch))

    out_path = tmp_path / "custom_pairing_check.json"
    result = subprocess.run(
        [sys.executable, str(PAIRING_CHECK_PY), "--bkg", str(ws_path), "--patch", str(patch_path),
         "--out", str(out_path), "--timestamp", "2026-07-08T00:00:00Z"],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PAIRING PROBLEMS" in result.stdout

    assert out_path.is_file()
    rec = json.loads(out_path.read_text())
    assert rec["paired"] is False
    assert rec["verdict"] == "fail"
    assert len(rec["mismatches"]) >= 1
    assert any("SR" in m for m in rec["mismatches"])


def test_verdict_matches_exit_code_condition_directly():
    """Unit-level: verdict=='pass' iff paired and no mismatches -- the exact condition that
    decides SystemExit(1) in main(). Exercise write_pairing_check_json directly."""
    pc = _load_pairing_check()
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        out_pass = os.path.join(td, "p.json")
        rec_pass = pc.write_pairing_check_json(out_pass, "bkg.json", "patch.json",
                                                 paired=True, n_channels=3, mismatches=[],
                                                 timestamp="")
        assert rec_pass["verdict"] == "pass"

        out_fail = os.path.join(td, "f.json")
        rec_fail = pc.write_pairing_check_json(out_fail, "bkg.json", "patch.json",
                                                 paired=False, n_channels=3,
                                                 mismatches=["channel SR: bad"], timestamp="")
        assert rec_fail["verdict"] == "fail"

        # paired True but a stray mismatch present (shouldn't happen from check_pairing, but the
        # writer's condition is "paired and no mismatches", not just "paired")
        out_edge = os.path.join(td, "e.json")
        rec_edge = pc.write_pairing_check_json(out_edge, "bkg.json", "patch.json",
                                                 paired=True, n_channels=3,
                                                 mismatches=["stray"], timestamp="")
        assert rec_edge["verdict"] == "fail"
