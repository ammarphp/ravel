"""cost_preflight --rundir artifact + cost-preflight-recorded invariant (R3 T1, H4).

Run from OUTSIDE the repo: cd /tmp && python3 -m pytest <abspath> -q
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CP = REPO / "src" / "ravel" / "workflow" / "cost_preflight.py"
VRS = REPO / "src" / "ravel" / "validation" / "validate_run_state.py"


def _vrs():
    spec = importlib.util.spec_from_file_location("vrs_r3t1", VRS)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_rundir_writes_artifact(tmp_path):
    r = subprocess.run([sys.executable, str(CP), "--mode", "smoke", "--rundir", str(tmp_path)],
                       cwd=REPO, capture_output=True, text=True)
    art = tmp_path / "inputs" / "cost_preflight.json"
    assert art.is_file(), r.stdout + r.stderr
    doc = json.loads(art.read_text())
    assert doc["generated_by"] == "cost_preflight.py"
    assert doc["schema_version"] == 1
    assert doc["mode"] == "smoke" and "walltime_h" in doc
    assert doc["backend"] == "native" and doc["parallel"] == 1


def _run_with_gen(tmp_path, vrs, with_cost):
    rd = tmp_path / "2026-08-04_TEST_cost"
    (rd / "inputs").mkdir(parents=True)
    (rd / "outputs").mkdir()
    contract = vrs._base_contract(task_mode="reproduce", compute_plan="smoke")
    vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
    vrs._write_json(str(rd / "outputs" / "sr_yields.json"), {"srs": {"SR1": 1.0}})
    if with_cost:
        vrs._write_json(str(rd / "inputs" / "cost_preflight.json"),
                        {"schema_version": 1, "generated_by": "cost_preflight.py",
                         "mode": "smoke", "walltime_h": [0.5, 1.0]})
    return str(rd), contract


def test_invariant_fails_without_artifact(tmp_path):
    vrs = _vrs()
    rd, contract = _run_with_gen(tmp_path, vrs, with_cost=False)
    facts = vrs.discover_facts(rd, contract)
    status, detail = vrs.inv_cost_preflight_recorded(rd, contract, facts, False, False)
    assert status == "FAIL" and "cost_preflight" in detail


def test_invariant_passes_with_artifact(tmp_path):
    vrs = _vrs()
    rd, contract = _run_with_gen(tmp_path, vrs, with_cost=True)
    facts = vrs.discover_facts(rd, contract)
    status, _ = vrs.inv_cost_preflight_recorded(rd, contract, facts, False, False)
    assert status == "PASS"


def test_invariant_waives_legacy(tmp_path):
    vrs = _vrs()
    rd, contract = _run_with_gen(tmp_path, vrs, with_cost=False)
    status, _ = vrs.inv_cost_preflight_recorded(rd, contract,
                                                vrs.discover_facts(rd, contract), True, False)
    assert status == "waived-legacy"
