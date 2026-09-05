# tests/unit/test_validate_parameters.py
"""validate_parameters.py -- the D10 parameter-validation contract (Phase 3, G12).

Drives the tool's own --selftest (subprocess, cwd=REPO so sibling imports resolve) plus a few
file-path unit checks. Import by file path (py.py shadow); run from OUTSIDE the repo.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VP_PY = REPO / "src" / "ravel" / "validation" / "validate_parameters.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_parameters_under_test", VP_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_selftest_passes():
    r = subprocess.run([sys.executable, str(VP_PY), "--selftest"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SELFTEST FAIL" not in r.stderr


def _emit_run(rd, *extra):
    return subprocess.run([sys.executable, str(VP_PY), "emit", "--rundir", str(rd), *extra],
                          cwd=REPO, capture_output=True, text=True)


def test_emit_auto_seeds_gated_traps_only(tmp_path):
    rd = tmp_path / "run"
    (rd / "inputs").mkdir(parents=True)
    json.dump({"task_mode": "scan"}, open(rd / "inputs" / "task_contract.json", "w"))
    json.dump({"schema_version": 1, "traps_hit": ["T6", "T8", "T1"]},
              open(rd / "inputs" / "trap_sweep.json", "w"))
    assert _emit_run(rd, "--param", "m_slepton:varied", "--timestamp", "X").returncode == 0
    doc = json.load(open(rd / "inputs" / "validations.json"))
    names = {p["name"] for p in doc["params"]}
    assert {"m_slepton", "T6", "T8"} <= names          # gated traps + the varied param
    assert "T1" not in names                            # T1 is not in GATED_TRAPS
    assert doc["generated_by"] == "validate_parameters.py" and "input_fingerprint" in doc
    assert all(p["status"] == "PENDING" for p in doc["params"])   # never defaults to PASS


def test_check_blocks_until_all_pass(tmp_path):
    vp = _load_module()
    rd = tmp_path / "run"
    (rd / "inputs").mkdir(parents=True)
    json.dump({"task_mode": "scan"}, open(rd / "inputs" / "task_contract.json", "w"))
    json.dump({"schema_version": 1, "traps_hit": ["T8"]},
              open(rd / "inputs" / "trap_sweep.json", "w"))
    assert vp.main(["emit", "--rundir", str(rd), "--param", "m_slepton"]) == 0
    assert vp.main(["check", "--rundir", str(rd), "--require-nonempty"]) == 1   # all PENDING
    # PASS is EARNED -- recording PASS without evidence is refused
    assert vp.main(["record", "--rundir", str(rd), "--param", "m_slepton", "--status", "PASS"]) == 1
    for nm in ("m_slepton", "T8"):
        assert vp.main(["record", "--rundir", str(rd), "--param", nm, "--status", "PASS",
                        "--evidence", "checked"]) == 0
    assert vp.main(["check", "--rundir", str(rd), "--require-nonempty"]) == 0
    # a FAILing record re-blocks the gate
    assert vp.main(["record", "--rundir", str(rd), "--param", "T8", "--status", "FAIL",
                    "--evidence", "mismatch"]) == 0
    assert vp.main(["check", "--rundir", str(rd), "--require-nonempty"]) == 1
