# framework/tests/test_deviations_guard.py
"""Edit-time DEVIATIONS guard (Phase 3, D15/G17 moment-of-change half).

Drives .claude/hooks/deviations-guard.sh with a fake PostToolUse stdin payload: an Edit to a
CHECK-IN-1-baselined input with NO DEVIATIONS.md row must BLOCK (exit 2, reason on stderr); the
same edit with a naming DEVIATIONS.md row must pass (exit 0); an edit to a non-baselined file passes.
Also unit-tests validate_run_state.edit_guard directly (0 allow / 1 block).
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VRS_PY = REPO / "trial-runs" / "_infrastructure" / "validate_run_state.py"
GUARD_SH = REPO / ".claude" / "hooks" / "deviations-guard.sh"


def _load_vrs():
    spec = importlib.util.spec_from_file_location("validate_run_state_under_test", VRS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fire(path):
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(path)}})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(REPO))
    return subprocess.run(["bash", str(GUARD_SH)], input=payload, capture_output=True,
                          text=True, env=env)


def test_edit_guard_blocks_baselined_edit_without_deviation(tmp_path):
    rd = tmp_path / "run"
    (rd / "inputs").mkdir(parents=True)
    tc = rd / "inputs" / "task_contract.json"
    tc.write_text("{}")
    r = _fire(tc)
    assert r.returncode == 2, r.stdout + r.stderr          # exit 2 == hook BLOCK
    assert "task_contract.json" in r.stderr


def test_edit_guard_allows_when_deviation_names_the_file(tmp_path):
    rd = tmp_path / "run"
    (rd / "inputs").mkdir(parents=True)
    tc = rd / "inputs" / "task_contract.json"
    tc.write_text("{}")
    (rd / "DEVIATIONS.md").write_text("# Deviations\n- task_contract.json: lumi corrected.\n")
    assert _fire(tc).returncode == 0


def test_edit_guard_ignores_non_baselined_file(tmp_path):
    p = tmp_path / "run" / "notes.txt"
    p.parent.mkdir(parents=True)
    p.write_text("hi")
    assert _fire(p).returncode == 0


def test_edit_guard_function_returns_1_on_block(tmp_path):
    vrs = _load_vrs()
    rd = tmp_path / "run"
    (rd / "inputs").mkdir(parents=True)
    tc = rd / "inputs" / "task_contract.json"
    tc.write_text("{}")
    assert vrs.edit_guard(str(tc)) == 1                     # block
    (rd / "DEVIATIONS.md").write_text("- task_contract.json changed\n")
    assert vrs.edit_guard(str(tc)) == 0                     # allow


# The exact D-1 canonical merge snippet (see Step 3's wiring block), run as a subprocess so the test
# exercises the real idiom rather than a paraphrase.
_MERGE = r'''
import json, os
SETTINGS = os.path.join(os.environ["CLAUDE_PROJECT_DIR"], ".claude", "settings.json")
obj = json.load(open(SETTINGS)) if os.path.exists(SETTINGS) else {}
hooks = obj.setdefault("hooks", {})
arr = hooks.setdefault("PostToolUse", [])
cmd = 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/deviations-guard.sh"'
if not any(any(h.get("command") == cmd for h in blk.get("hooks", [])) for blk in arr):
    arr.append({"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": cmd}]})
json.dump(obj, open(SETTINGS, "w"), indent=2); open(SETTINGS, "a").write("\n")
'''


def test_settings_merge_preserves_card_guard_and_observer(tmp_path):
    """D-1: the deviations-guard wiring is an idempotent MERGE -- it APPENDS its PostToolUse block and
    leaves the PreToolUse card-guard and the Phase-1 PostToolUse observer untouched, and is a no-op on
    a second run (Phase 4b Task 4.14 adds this test to its gate so a future clobber fails loud)."""
    proj = tmp_path
    (proj / ".claude").mkdir()
    card = 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/protect-original-cards.sh"'
    obs = 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/posttooluse-observer.sh"'
    dev = 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/deviations-guard.sh"'
    settings = proj / ".claude" / "settings.json"
    settings.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": card}]}],
        "PostToolUse": [{"matcher": "Bash|Edit|Write|MultiEdit|NotebookEdit|Skill|Agent|Task",
                         "hooks": [{"type": "command", "command": obs}]}]}}, indent=2))
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
    for _ in range(2):                                       # run twice -> must be idempotent
        r = subprocess.run([sys.executable, "-c", _MERGE], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    obj = json.loads(settings.read_text())
    post_cmds = [h["command"] for blk in obj["hooks"]["PostToolUse"] for h in blk["hooks"]]
    pre_cmds = [h["command"] for blk in obj["hooks"]["PreToolUse"] for h in blk["hooks"]]
    assert post_cmds.count(dev) == 1                         # appended exactly once (idempotent)
    assert obs in post_cmds                                  # observer survived (not clobbered)
    assert card in pre_cmds                                  # PreToolUse card-guard survived
