# tests/unit/test_pre_generate_guard.py
import json, os, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude/hooks/pre-generate-guard.sh"

def _mk_run(tmp_path, model):
    rd = tmp_path / "trial-runs" / "2026-07-09_svj"
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs" / "task_contract.json").write_text(json.dumps({"targets": {"model": model}}))
    return rd

def test_guard_blocks_mg5_without_recipe(tmp_path):
    _mk_run(tmp_path, "SVJ")
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {
        "command": "bash run-pipeline-native.sh trial-runs/2026-07-09_svj config.toml"}})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    r = subprocess.run(["bash", str(HOOK)], input=stdin, capture_output=True, text=True, env=env)
    assert r.returncode == 2, r.stdout + r.stderr

def test_guard_noop_on_non_generation(tmp_path):
    _mk_run(tmp_path, "SVJ")
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    r = subprocess.run(["bash", str(HOOK)], input=stdin, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr

def test_guard_allows_when_recipe_present(tmp_path):
    rd = _mk_run(tmp_path, "SVJ")
    (rd / "inputs" / "generation_recipe.json").write_text(json.dumps({"model": "SVJ"}))
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {
        "command": "bash run-pipeline-native.sh trial-runs/2026-07-09_svj config.toml"}})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    r = subprocess.run(["bash", str(HOOK)], input=stdin, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr

def test_settings_merge_coexistence():
    # D-1: after Task 4.14's idempotent merge, the pre-generate-guard must COEXIST in PostToolUse with
    # Phase 1's observer and Phase 3's deviations-guard (Phase 4b runs after 1-3). A bare "PostToolUse"
    # key or a wholesale Write would clobber a sibling -> this asserts none was dropped.
    settings = json.loads((REPO / ".claude" / "settings.json").read_text())
    hooks = settings.get("hooks", {})
    post = "\n".join(h.get("command", "")
                     for blk in hooks.get("PostToolUse", []) for h in blk.get("hooks", []))
    assert "pre-generate-guard.sh" in post, "pre-generate-guard absent/clobbered in PostToolUse"
    assert "observer" in post, "Phase-1 PostToolUse observer clobbered by the merge"
    assert "deviations" in post, "Phase-3 deviations-guard clobbered by the merge"
    pre = "\n".join(h.get("command", "")
                    for blk in hooks.get("PreToolUse", []) for h in blk.get("hooks", []))
    assert "protect-original-cards" in pre, "PreToolUse card-guard clobbered by the merge"
