# tests/unit/test_spine_sim.py
"""tests/adversarial/run_suite.py -- the per-gate verification board engine.

Import the module under test by FILE PATH (a local `py.py` would shadow the `py` package pytest
needs); run this file from a directory without a local py.py.
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "tests" / "adversarial" / "run_suite.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_suite_uut", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_case(cases_dir, gate, body):
    p = cases_dir / f"case_{gate.lower()}.py"
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


_PASS = "import sys\nprint('[FIRED] ok')\nsys.exit(0)\n"
_FAIL = "import sys\nsys.stderr.write('[GATE-DID-NOT-FIRE] nope\\n')\nsys.exit(1)\n"
_ERR = "import sys\nsys.stderr.write('[SETUP-ERROR] boom\\n')\nsys.exit(2)\n"


def test_expected_gates_is_the_full_set(tmp_path):
    mod = _load()
    # G0a/G0b/G0c + G1..G20 + G22..G28 = 30 distinct rows
    assert len(mod.EXPECTED_GATES) == 30
    assert mod.EXPECTED_GATES[0] == "G0a" and "G28" in mod.EXPECTED_GATES
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


def test_every_discovered_case_runs_and_none_is_skipped(tmp_path):
    # The board has no skip state: every discovered case runs, including one for a gate outside
    # EXPECTED_GATES, and its failure sinks the board.
    mod = _load()
    cases = tmp_path / "cases"; cases.mkdir()
    _write_case(cases, "G0a", _PASS)
    _write_case(cases, "G99", _FAIL)
    assert {r["gate"]: r["status"] for r in mod.build_board(cases)} == {"G0a": "PASS", "G99": "FAIL"}
    assert mod.main(["--cases", str(cases)]) == 1


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
    assert "run_suite selftest: PASS" in r.stdout
