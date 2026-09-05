# tests/unit/test_spine_sim_complete.py
"""Completeness gate (Task 6.8): every EXPECTED gate has a case script AND --require-all is green.
This is the whole-spine integration assertion; it requires Phases 0-4 + Tasks 6.1-6.7 on disk.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "tests" / "adversarial" / "run_suite.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_spine_sim_uut2", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_expected_gate_has_a_case_file():
    mod = _load()
    found = mod.discover_cases(REPO / "tests" / "adversarial" / "cases")
    missing = [g for g in mod.EXPECTED_GATES if g not in found]
    assert not missing, f"gates with no case script: {missing}"


def test_require_all_board_is_green():
    r = subprocess.run([sys.executable, str(ENGINE), "--require-all", "--json"],
                       cwd=REPO, capture_output=True, text=True, timeout=1200)
    payload = json.loads(r.stdout)
    bad = [x for x in payload["results"] if x["status"] != "PASS"
           and not (x["gate"] == "G21" and x["status"] == "SKIP")]
    assert r.returncode == 0, json.dumps(bad, indent=2)
    assert not bad, json.dumps(bad, indent=2)
    assert len(payload["results"]) == 30
    assert {x["gate"] for x in payload["results"]} == set(_load().EXPECTED_GATES)
