"""spike_probe.py -- L0 harness-behaviour spike recorder/verifier (Task 0.2).

Import the module under test by FILE PATH, not package import: the repo root carries a `py.py`
that shadows the real `py` package pytest needs. Run this file from OUTSIDE the repo:
    cd /tmp && python3 -m pytest <this file's abspath> -q
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPIKE_PROBE_PY = REPO / "tests" / "adversarial" / "spike_probe.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("spike_probe_under_test", SPIKE_PROBE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_selftest_passes():
    result = subprocess.run([sys.executable, str(SPIKE_PROBE_PY), "--selftest"],
                            cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "spike_probe selftest: PASS" in result.stdout
    assert "SELFTEST FAIL" not in result.stderr
    assert result.stdout.count("  FAIL\n") == 0


def test_spk1_pass_and_fail_verdicts():
    mod = _load_module()
    good = mod.build_record("SPK-1", {"probe_log": "USERPROMPTSUBMIT\nPOSTTOOLUSE\nSTOP\nSTOP\n",
                                      "transcript": "...SPK1-STOP-BLOCK..."})
    assert good["verdict"] == "PASS" and good["decision"] == "hook-primary" and good["exit"] == 0
    assert good["generated_by"] == "spike_probe.py" and len(good["input_fingerprint"]) == 64
    bad = mod.build_record("SPK-1", {"probe_log": "USERPROMPTSUBMIT\nSTOP\nSTOP\n",
                                     "transcript": "SPK1-STOP-BLOCK"})
    assert bad["verdict"] == "unproven" and bad["decision"] == "fallback-primary" and bad["exit"] == 1


def test_record_and_check_roundtrip(tmp_path):
    mod = _load_module()
    tok = "SPK-deadbeef0001"
    ev = {"token": tok, "launch_cmd": f"sleep 20; echo {tok}", "reinvoke_text": f"done {tok}"}
    p = tmp_path / "evidence.json"
    p.write_text(json.dumps(ev))
    out = tmp_path / "SPK-2.json"
    assert mod.main(["--spike", "SPK-2", "--evidence", str(p), "--record", str(out)]) == 0
    art = json.loads(out.read_text())
    assert art["verdict"] == "PASS" and art["decision"] == "harness-reinvoke-primary"
    assert mod.main(["--spike", "SPK-2", "--check", str(out)]) == 0


def test_check_rejects_fingerprint_tamper(tmp_path):
    mod = _load_module()
    tok = "SPK-cafebabe0002"
    art = mod.build_record("SPK-2", {"token": tok, "launch_cmd": f"echo {tok}", "reinvoke_text": tok})
    art["evidence"] = {"token": tok, "launch_cmd": "echo x", "reinvoke_text": "x"}  # tamper, keep old fp+verdict
    out = tmp_path / "tampered.json"
    out.write_text(json.dumps(art))
    assert mod.main(["--spike", "SPK-2", "--check", str(out)]) == 3


def test_primacy_flips_on_spk1_fail():
    mod = _load_module()
    allpass = {"SPK-1": {"verdict": "PASS", "decision": "hook-primary"},
               "SPK-2": {"verdict": "PASS", "decision": "harness-reinvoke-primary"},
               "SPK-3": {"verdict": "PASS", "decision": "wake-primitive-primary"}}
    doc = mod.build_primacy(allpass)
    assert all(b["primary"] != "fallback" for b in doc["branches"].values() if b["governed_by"] == "SPK-1")
    spk1fail = dict(allpass); spk1fail["SPK-1"] = {"verdict": "unproven", "decision": "fallback-primary"}
    doc2 = mod.build_primacy(spk1fail)
    assert all(b["primary"] == "fallback" for b in doc2["branches"].values() if b["governed_by"] == "SPK-1")


def test_usage_exit_2():
    mod = _load_module()
    assert mod.main([]) == 2


def test_default_primacy_reads_lowercase_committed_probe_files(capsys):
    mod = _load_module()
    assert mod.main(["--primacy", "--json"]) == 0
    actual = json.loads(capsys.readouterr().out)["spikes"]
    fixture_dir = REPO / "tests" / "fixtures" / "hook-probes"
    expected = {}
    for spike in mod.SPIKES:
        record = json.loads((fixture_dir / f"{spike.lower()}.json").read_text())
        expected[spike] = {key: record[key] for key in ("verdict", "decision")}
    assert actual == expected
