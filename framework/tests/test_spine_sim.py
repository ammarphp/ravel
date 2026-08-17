# framework/tests/test_spine_sim.py
"""framework/spine_sim/run_spine_sim.py -- the per-gate verification board engine (Task 6.1).

Import the module under test by FILE PATH (the repo root's py.py shadows the `py` package pytest
needs); run this file from OUTSIDE the repo: cd /tmp && python3 -m pytest <abspath> -q .
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "framework" / "spine_sim" / "run_spine_sim.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_spine_sim_uut", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_case(cases_dir, gate, body):
    p = cases_dir / f"case_{gate}.py"
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


_PASS = "import sys\nprint('[FIRED] ok')\nsys.exit(0)\n"
_FAIL = "import sys\nsys.stderr.write('[GATE-DID-NOT-FIRE] nope\\n')\nsys.exit(1)\n"
_ERR = "import sys\nsys.stderr.write('[SETUP-ERROR] boom\\n')\nsys.exit(2)\n"


def test_expected_gates_is_the_full_set(tmp_path):
    mod = _load()
    # G0a/G0b/G0c + G1..G27 = 30 distinct rows (spec §5 calls this "~28")
    assert len(mod.EXPECTED_GATES) == 30
    assert mod.EXPECTED_GATES[0] == "G0a" and "G27" in mod.EXPECTED_GATES
    assert len(set(mod.EXPECTED_GATES)) == 30


def test_all_pass_board_exits_0(tmp_path, capsys):
    mod = _load()
    cases = tmp_path / "cases"; cases.mkdir()
    _write_case(cases, "G0a", _PASS)
    _write_case(cases, "G1", _PASS)
    rc = mod.main(["--cases", str(cases)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "2 PASS / 0 FAIL" in out


def test_one_failing_case_makes_board_exit_1(tmp_path, capsys):
    mod = _load()
    cases = tmp_path / "cases"; cases.mkdir()
    _write_case(cases, "G0a", _PASS)
    _write_case(cases, "G1", _FAIL)
    rc = mod.main(["--cases", str(cases)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "G1" in out and "1 PASS / 1 FAIL" in out


def test_setup_error_is_not_pass(tmp_path, capsys):
    mod = _load()
    cases = tmp_path / "cases"; cases.mkdir()
    _write_case(cases, "G1", _ERR)
    rc = mod.main(["--cases", str(cases)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "ERROR" in out


def test_only_selects_a_subset(tmp_path, capsys):
    mod = _load()
    cases = tmp_path / "cases"; cases.mkdir()
    _write_case(cases, "G0a", _PASS)
    _write_case(cases, "G1", _FAIL)
    rc = mod.main(["--cases", str(cases), "--only", "G0a"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "G1" not in out and "1 PASS / 0 FAIL" in out


def test_require_all_fails_on_a_missing_gate(tmp_path, capsys):
    mod = _load()
    cases = tmp_path / "cases"; cases.mkdir()
    _write_case(cases, "G0a", _PASS)  # only one of the 30 present
    rc = mod.main(["--cases", str(cases), "--require-all"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "MISSING" in out

def test_json_payload_matches_text_verdict(tmp_path, capsys):
    mod = _load()
    cases = tmp_path / "cases"; cases.mkdir()
    _write_case(cases, "G0a", _PASS)
    _write_case(cases, "G1", _FAIL)
    rc = mod.main(["--cases", str(cases), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1 and payload["all_pass"] is False
    assert {r["gate"]: r["status"] for r in payload["results"]} == {"G0a": "PASS", "G1": "FAIL"}


def test_self_drive_gate_skips_when_artifact_absent_and_runs_when_forced(tmp_path):
    # A self-drive gate (G21) whose live artifact is absent is SKIP (green) by default, but --with-
    # self-drive forces it to run. Point SELF_DRIVE_ARTIFACT at a guaranteed-absent path so the test
    # never depends on a stray real verdict file.
    mod = _load()
    mod.SELF_DRIVE_ARTIFACT = tmp_path / "no_such_verdict.json"
    cases = tmp_path / "cases"; cases.mkdir()
    _write_case(cases, "G0a", _PASS)
    _write_case(cases, "G21", _FAIL)        # would FAIL the board if actually run
    rc = mod.main(["--cases", str(cases)])  # default: G21 SKIP -> board green
    assert rc == 0
    rc2 = mod.main(["--cases", str(cases), "--with-self-drive"])  # forced -> G21 runs -> FAIL
    assert rc2 == 1


def test_cli_smoke_via_subprocess(tmp_path):
    cases = tmp_path / "cases"; cases.mkdir()
    _write_case(cases, "G0a", _PASS)
    r = subprocess.run([sys.executable, str(ENGINE), "--cases", str(cases)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 PASS / 0 FAIL" in r.stdout


def test_selftest_exits_0(tmp_path):
    r = subprocess.run([sys.executable, str(ENGINE), "--selftest"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "run_spine_sim selftest: PASS" in r.stdout
