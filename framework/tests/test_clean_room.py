# framework/tests/test_clean_room.py
"""framework/spine_sim/clean_room.py -- the un-hinted self-drive launcher verdict engine (Task 6.6).

The LIVE claude -p run is slow/costed/non-deterministic, so the unit tests drive the PURE verdict
engine (evaluate_transcript) against fabricated claude --output-format json payloads, plus the pure
command-builder. The live round-trip is a separate, env-gated smoke (skipped by default).
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CR = REPO / "framework" / "spine_sim" / "clean_room.py"


def _load():
    spec = importlib.util.spec_from_file_location("clean_room_uut", CR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payload(tool_names, files_written, final_text):
    # a minimal shape mirroring claude --output-format json: a result blob + a tool-use trail
    return {"type": "result", "subtype": "success", "is_error": False,
            "result": final_text,
            "tool_uses": [{"name": n, "input": {}} for n in tool_names],
            "files_written": files_written}


def test_reaching_checkin1_with_a_valid_contract_and_no_survey_passes():
    mod = _load()
    p = _payload(
        tool_names=["Skill", "Bash", "Read"],
        files_written=["trial-runs/2026-07-09_x/inputs/task_contract.json"],
        final_text="CHECK-IN 1: here is the task_contract and the no-generation survey ...")
    v = mod.evaluate_transcript(p)
    assert v["verdict"] == "PASS", v
    assert "CHECKIN1" in v["reached"]


def test_surveying_the_repo_before_checkin1_is_a_violation():
    mod = _load()
    p = _payload(
        tool_names=["Read", "Read", "Read", "Grep"],   # dev-repo survey, never routed
        files_written=[],
        final_text="Let me first survey DIRECTORY.md and framework/STATUS.md ...")
    v = mod.evaluate_transcript(p)
    assert v["verdict"] == "FAIL"
    assert any("survey" in x.lower() or "task_contract" in x.lower() for x in v["violations"])


def test_generation_before_checkin1_is_a_violation():
    mod = _load()
    p = _payload(
        tool_names=["Bash"],
        files_written=[],
        final_text="Running mg5_aMC generate_events now.")
    v = mod.evaluate_transcript(p)
    assert v["verdict"] == "FAIL"
    assert any("generat" in x.lower() for x in v["violations"])


def test_build_launch_cmd_is_unhinted_and_headless():
    mod = _load()
    cmd = mod.build_launch_cmd("Initiate: reinterpret X", "$DSRLAB_ROOT",
                               "11111111-1111-1111-1111-111111111111", str(REPO))
    assert cmd[0].endswith("claude")
    assert "-p" in cmd and "--output-format" in cmd
    # un-hinted: project CLAUDE.md/settings must NOT auto-load (parent-cwd router is the whole point)
    assert "--setting-sources" in cmd
    j = cmd.index("--setting-sources")
    assert cmd[j + 1] in ("user", "")
    assert "--strict-mcp-config" in cmd


def test_selftest_exits_0():
    import subprocess
    r = subprocess.run([sys.executable, str(CR), "--selftest"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "clean_room selftest: PASS" in r.stdout


def test_replay_scores_a_captured_transcript(tmp_path):
    # The deterministic replay path (EXECUTION ADJUSTMENT): --replay scores a CAPTURED claude
    # --output-format json payload offline, exit 0 on PASS. This is how the on-demand live gate is
    # exercised without an authenticated claude round-trip.
    import subprocess
    payload = _payload(
        tool_names=["Skill", "Bash", "Read"],
        files_written=["trial-runs/2026-07-09_x/inputs/task_contract.json"],
        final_text="CHECK-IN 1: task_contract + no-generation survey done, awaiting the go-ahead.")
    f = tmp_path / "captured_payload.json"
    f.write_text(json.dumps(payload))
    r = subprocess.run([sys.executable, str(CR), "--replay", str(f), "--json"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    v = json.loads(r.stdout)
    assert v["verdict"] == "PASS", v
