import json, subprocess
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SETTINGS = REPO / ".claude/settings.json"
HOOKS = REPO / ".claude/hooks"

def _cmds(blocks):
    return [hk.get("command", "") for blk in blocks for hk in blk.get("hooks", [])]

def test_settings_valid_json_and_wires_all_hooks():
    cfg = json.loads(SETTINGS.read_text())
    h = cfg["hooks"]
    pre = json.dumps(h["PreToolUse"])
    assert "protect-original-cards.sh" in pre          # card-guard preserved (untouched)
    assert "pretooluse-skill.sh" in pre                # G22 (merged this task)
    assert "stop-dispatcher.sh" in json.dumps(h["Stop"])
    assert "userpromptsubmit-router.sh" in json.dumps(h["UserPromptSubmit"])
    assert "posttooluse-observer.sh" in json.dumps(h["PostToolUse"])   # Phase-1 observer preserved

def test_observer_matcher_not_narrowed_and_no_duplicate_blocks():
    # D-1: this task merges Stop/UserPromptSubmit/PreToolUse-Skill only; it must NOT re-narrow the
    # Phase-1 observer matcher nor duplicate any block (the merge is idempotent).
    cfg = json.loads(SETTINGS.read_text())
    h = cfg["hooks"]
    obs = [blk for blk in h["PostToolUse"] if "posttooluse-observer.sh" in json.dumps(blk)]
    assert len(obs) == 1, "observer block missing or duplicated"
    for tok in ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Skill", "Agent", "Task"):
        assert tok in obs[0]["matcher"], f"observer matcher lost {tok} (must stay the full set)"
    for event, cmd in (("Stop", "stop-dispatcher.sh"),
                       ("UserPromptSubmit", "userpromptsubmit-router.sh"),
                       ("PreToolUse", "pretooluse-skill.sh"),
                       ("PreToolUse", "protect-original-cards.sh")):
        n = sum(cmd in c for c in _cmds(h[event]))
        assert n == 1, f"{cmd} appears {n}x in {event} (expected exactly 1)"

def test_all_hook_scripts_have_valid_bash():
    for sh in ("protect-original-cards.sh", "stop-dispatcher.sh",
               "userpromptsubmit-router.sh", "pretooluse-skill.sh"):
        assert subprocess.run(["bash", "-n", str(HOOKS / sh)]).returncode == 0, sh


def test_skill_guard_matcher_covers_agent_task():
    """A3: the guard must see Agent/Task fan-out, not just Skill."""
    import json as _json
    h = _json.load(open(REPO / ".claude" / "settings.json"))["hooks"]
    blk = next(b for b in h["PreToolUse"]
               if any("pretooluse-skill.sh" in x["command"] for x in b["hooks"]))
    assert blk["matcher"] == "Skill|Agent|Task"


def test_pretooluse_bash_guard_wired():
    """R3/H1: the pre-exec compute gate must be a PreToolUse block with matcher Bash."""
    import json as _json
    h = _json.load(open(REPO / ".claude" / "settings.json"))["hooks"]
    blk = next(b for b in h["PreToolUse"]
               if any("pretooluse-bash.sh" in x["command"] for x in b["hooks"]))
    assert blk["matcher"] == "Bash"
