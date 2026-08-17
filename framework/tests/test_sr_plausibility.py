"""Tests for sr_plausibility.py (D14 emitter). Import by file path; drive main()/--selftest.
    REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/framework/tests/test_sr_plausibility.py" -q
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "trial-runs" / "_infrastructure" / "sr_plausibility.py"


def _load():
    spec = importlib.util.spec_from_file_location("sr_plausibility_uut", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _mk(rd, sr_yields, exclusion):
    os.makedirs(os.path.join(rd, "outputs", "pyhf_exclusion"), exist_ok=True)
    json.dump(sr_yields, open(os.path.join(rd, "outputs", "sr_yields.json"), "w"))
    json.dump(exclusion, open(os.path.join(rd, "outputs", "pyhf_exclusion", "exclusion.json"), "w"))


def test_all_zero_yields_are_implausible():
    sp = _load()
    with tempfile.TemporaryDirectory() as td:
        rd = os.path.join(td, "bad")
        _mk(rd, [{"name": "SR1", "n": 0, "b": 0.0, "db": 0.0, "s": 0.0}],
            {"obs_limit": 1e9, "exp_limits": [1, 1, 1, 1, 1], "per_sr": {}, "best_sr": "SR1"})
        rc = sp.main(["--rundir", rd])
        rec = json.load(open(os.path.join(rd, "outputs", "sr_plausibility.json")))
        assert rc == 1 and rec["verdict"] == "implausible"
        assert rec["generated_by"] == "sr_plausibility.py" and rec["input_fingerprint"]


def test_healthy_yields_are_plausible_with_matching_fingerprint():
    sp = _load()
    with tempfile.TemporaryDirectory() as td:
        rd = os.path.join(td, "good")
        _mk(rd, [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}],
            {"obs_limit": 0.7, "exp_limits": [0.4, 0.55, 0.7, 0.95, 1.3], "per_sr": {},
             "best_sr": "SR1", "excluded_obs": True})
        rc = sp.main(["--rundir", rd])
        rec = json.load(open(os.path.join(rd, "outputs", "sr_plausibility.json")))
        assert rc == 0 and rec["verdict"] == "plausible"
        assert rec["input_fingerprint"] == sp.compute_input_fingerprint(rd)


def test_selftest_exit_zero():
    result = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                            cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
