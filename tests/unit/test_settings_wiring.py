import json, subprocess
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SETTINGS = REPO / ".claude/settings.json"
HOOKS = REPO / ".claude/hooks"

def _guards():
    """The PreToolUse file guards on disk (protect-*.sh); each must stay wired exactly once."""
    return sorted(path.name for path in HOOKS.glob("protect-*.sh"))

def _cmds(blocks):
    return [hk.get("command", "") for blk in blocks for hk in blk.get("hooks", [])]

def test_settings_valid_json_and_wires_all_hooks():
    cfg = json.loads(SETTINGS.read_text())
    h = cfg["hooks"]
    pre = json.dumps(h["PreToolUse"])
    for guard in _guards():                            # PreToolUse guards preserved (untouched)
        assert guard in pre, guard
    assert "pretooluse-skill.sh" in pre                # G22 (merged by the hook wiring)
    assert "stop-dispatcher.sh" in json.dumps(h["Stop"])
    assert "userpromptsubmit-router.sh" in json.dumps(h["UserPromptSubmit"])
    assert "posttooluse-observer.sh" in json.dumps(h["PostToolUse"])   # observer preserved

def test_observer_matcher_not_narrowed_and_no_duplicate_blocks():
    # The hook wiring merges Stop/UserPromptSubmit/PreToolUse-Skill only; it must NOT re-narrow the
    # observer matcher nor duplicate any block (the merge is idempotent).
    cfg = json.loads(SETTINGS.read_text())
    h = cfg["hooks"]
    obs = [blk for blk in h["PostToolUse"] if "posttooluse-observer.sh" in json.dumps(blk)]
    assert len(obs) == 1, "observer block missing or duplicated"
    for tok in ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Skill", "Agent", "Task"):
        assert tok in obs[0]["matcher"], f"observer matcher lost {tok} (must stay the full set)"
    for event, cmd in (("Stop", "stop-dispatcher.sh"),
                       ("UserPromptSubmit", "userpromptsubmit-router.sh"),
                       ("PreToolUse", "pretooluse-skill.sh"),
                       *(("PreToolUse", guard) for guard in _guards())):
        n = sum(cmd in c for c in _cmds(h[event]))
        assert n == 1, f"{cmd} appears {n}x in {event} (expected exactly 1)"

def test_all_hook_scripts_have_valid_bash():
    for sh in (*_guards(), "stop-dispatcher.sh",
               "userpromptsubmit-router.sh", "pretooluse-skill.sh"):
        assert subprocess.run(["bash", "-n", str(HOOKS / sh)]).returncode == 0, sh


def test_skill_guard_matcher_covers_agent_task():
    """The guard must see Agent/Task fan-out, not just Skill."""
    import json as _json
    h = _json.load(open(REPO / ".claude" / "settings.json"))["hooks"]
    blk = next(b for b in h["PreToolUse"]
               if any("pretooluse-skill.sh" in x["command"] for x in b["hooks"]))
    assert blk["matcher"] == "Skill|Agent|Task"


def test_pretooluse_bash_guard_wired():
    """The pre-exec compute gate must be a PreToolUse block with matcher Bash."""
    import json as _json
    h = _json.load(open(REPO / ".claude" / "settings.json"))["hooks"]
    blk = next(b for b in h["PreToolUse"]
               if any("pretooluse-bash.sh" in x["command"] for x in b["hooks"]))
    assert blk["matcher"] == "Bash"
