"""tests/adversarial/_probe_check.py -- the read-only checker of the recorded hook probes.

Gates G0a-G0c run the checker against tests/fixtures/hook-probes/; these tests prove it is not
vacuous: each verifier judges seeded passing and failing evidence correctly, an edited record is
rejected, and an inconsistent primacy branch fails. Imported by file path (the case library's
convention).
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "tests" / "adversarial" / "_probe_check.py"
PROBES = REPO / "tests" / "fixtures" / "hook-probes"


def _load():
    spec = importlib.util.spec_from_file_location("probe_check_under_test", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _record(mod, spike, evidence):
    verdict, decision, checks = mod.derive(spike, evidence)
    return {"schema_version": 1, "input_fingerprint": mod.fingerprint(evidence), "spike": spike,
            "verdict": verdict, "decision": decision, "evidence": evidence, "checks": checks}


def test_recorded_probes_recheck_with_their_recorded_verdicts():
    for spike, expected in (("SPK-1", 1), ("SPK-2", 0), ("SPK-3", 0)):
        result = subprocess.run([sys.executable, str(CHECKER), "--spike", spike, "--check",
                                 str(PROBES / f"{spike.lower()}.json")],
                                cwd=REPO, capture_output=True, text=True)
        assert result.returncode == expected, (spike, result.stdout, result.stderr)
    result = subprocess.run([sys.executable, str(CHECKER), "--check-primacy", str(PROBES / "hook-primacy.json")],
                            cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_verifiers_judge_seeded_evidence():
    mod = _load()
    full = "USERPROMPTSUBMIT 1\nPOSTTOOLUSE 1\nSTOP 1\nSTOP 2\n"
    assert mod.derive("SPK-1", {"probe_log": full, "transcript": "...SPK1-STOP-BLOCK..."})[:2] == \
        ("PASS", "hook-primary")
    for log, transcript in (("USERPROMPTSUBMIT 1\nSTOP 1\nSTOP 2\n", "SPK1-STOP-BLOCK"),
                            ("USERPROMPTSUBMIT 1\nPOSTTOOLUSE 1\nSTOP 1\n", "SPK1-STOP-BLOCK"),
                            (full, "no reason fed back")):
        assert mod.derive("SPK-1", {"probe_log": log, "transcript": transcript})[:2] == \
            ("unproven", "fallback-primary")
    tok = "SPK-abc123def456"
    assert mod.derive("SPK-2", {"token": tok, "launch_cmd": f"echo {tok}", "reinvoke_text": f"done {tok}"})[:2] == \
        ("PASS", "harness-reinvoke-primary")
    assert mod.derive("SPK-2", {"token": tok, "launch_cmd": f"echo {tok}", "reinvoke_text": "no stdout"})[:2] == \
        ("unproven", "poll-fallback-primary")
    wake = {"mechanism": "run_in_background sleep+echo", "scheduled_utc": "2026-07-09T00:02:00Z",
            "fired_utc": "2026-07-09T00:02:07Z", "tolerance_s": 30}
    assert mod.derive("SPK-3", wake)[:2] == ("PASS", "wake-primitive-primary")
    assert mod.derive("SPK-3", dict(wake, fired_utc="2026-07-09T00:20:00Z"))[:2] == \
        ("unproven", "bg-sleep-reinvoke-fallback")


def test_check_rejects_an_edited_record(tmp_path, capsys):
    mod = _load()
    tok = "SPK-cafebabe0002"
    record = _record(mod, "SPK-2", {"token": tok, "launch_cmd": f"echo {tok}", "reinvoke_text": tok})
    good = tmp_path / "spk-2.json"
    good.write_text(json.dumps(record))
    assert mod.check_record("SPK-2", str(good)) == 0
    record["evidence"] = {"token": tok, "launch_cmd": "echo x", "reinvoke_text": "x"}  # keep the old fp+verdict
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(record))
    assert mod.check_record("SPK-2", str(edited)) == 3
    assert mod.check_record("SPK-3", str(good)) == 3            # wrong probe
    assert mod.check_record("SPK-2", str(tmp_path / "absent.json")) == 2
    (tmp_path / "broken.json").write_text("{")
    assert mod.check_record("SPK-2", str(tmp_path / "broken.json")) == 3


def test_check_primacy_rejects_an_inconsistent_branch(tmp_path):
    mod = _load()
    doc = json.loads((PROBES / "hook-primacy.json").read_text())
    path = tmp_path / "hook-primacy.json"
    path.write_text(json.dumps(doc))
    assert mod.check_primacy(str(path)) == 0
    name = next(n for n, b in doc["branches"].items() if b["governed_by"] == "SPK-2")
    doc["branches"][name]["primary"] = "fallback"              # SPK-2 PASSed: must not be fallback
    path.write_text(json.dumps(doc))
    assert mod.check_primacy(str(path)) == 1
    doc = json.loads((PROBES / "hook-primacy.json").read_text())
    doc["spikes"]["SPK-1"]["verdict"] = "PASS"                  # edited without re-fingerprinting
    path.write_text(json.dumps(doc))
    assert mod.check_primacy(str(path)) == 3


def test_usage_exit_2():
    assert _load().main([]) == 2
