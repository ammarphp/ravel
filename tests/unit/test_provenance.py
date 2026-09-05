"""provenance.py -- the shared provenance base (Phase 1, Task 1.1).

Import by file path (repo-root py.py shadows the real py package on sys.path). Run from /tmp:
    cd /tmp && python3 -m pytest <abspath> -q
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROVENANCE_PY = REPO / "src" / "ravel" / "workflow" / "provenance.py"


def _load():
    spec = importlib.util.spec_from_file_location("provenance_under_test", PROVENANCE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_selftest_passes():
    r = subprocess.run([sys.executable, str(PROVENANCE_PY), "--selftest"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "selftest:" in r.stdout
    assert "SELFTEST FAIL" not in r.stderr
    assert r.stdout.count("  FAIL\n") == 0


def test_fingerprint_deterministic_and_pair_shape(tmp_path):
    mod = _load()
    p = tmp_path / "task_contract.json"
    p.write_text(json.dumps({"task_mode": "scan"}))
    fp1, fp2 = mod.fingerprint([str(p)]), mod.fingerprint([str(p)])
    assert fp1 == fp2 and len(fp1) == 64
    pair = mod.provenance_pair("workflow_state.py", [str(p)])
    assert set(pair) == set(mod.PROV_KEYS)
    assert pair["generated_by"] == "workflow_state.py"
    assert pair["input_fingerprint"] == fp1


def test_verify_pair_rejects_handwritten_and_drift(tmp_path):
    mod = _load()
    p = tmp_path / "task_contract.json"
    p.write_text(json.dumps({"task_mode": "scan"}))
    rec = mod.provenance_pair("workflow_state.py", [str(p)])
    assert mod.verify_pair(rec, "workflow_state.py", [str(p)])[0] is True
    handwritten = {"input_fingerprint": rec["input_fingerprint"]}       # no generated_by
    assert mod.verify_pair(handwritten, "workflow_state.py", [str(p)])[0] is False
    p.write_text(json.dumps({"task_mode": "reproduce"}))                # mutate declared input
    assert mod.verify_pair(rec, "workflow_state.py", [str(p)])[0] is False
