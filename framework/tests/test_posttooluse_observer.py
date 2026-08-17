"""posttooluse-observer.sh -- the L1 PostToolUse observer (Phase 1, Task 1.6).

Drives the hook script end-to-end against a temp project whose trial-runs/_infrastructure is a
symlink to the real one (so workflow_state.py + siblings resolve) and whose trial-runs/<run> has
an initialized run_state.json. Run from /tmp: cd /tmp && python3 -m pytest <abspath> -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OBSERVER_SH = REPO / ".claude" / "hooks" / "posttooluse-observer.sh"
WORKFLOW_STATE_PY = REPO / "trial-runs" / "_infrastructure" / "workflow_state.py"

_SURVEY_CONTRACT = {
    "prompt": "selftest", "task_mode": "survey", "detector_mode": "particle-level",
    "stat_mode": "none-survey", "required_user_inputs": [], "assumptions": ["fx"],
    "compute_plan": "none", "approval_required": True,
}


def _project_with_run(tmp_path):
    proj = tmp_path / "proj"
    (proj / "trial-runs").mkdir(parents=True)
    os.symlink(REPO / "trial-runs" / "_infrastructure", proj / "trial-runs" / "_infrastructure")
    rd = proj / "trial-runs" / "myrun"
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs" / "task_contract.json").write_text(json.dumps(_SURVEY_CONTRACT))
    r = subprocess.run([sys.executable, str(WORKFLOW_STATE_PY), "init", "--rundir", str(rd)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return proj, rd


def _drive(proj, stdin_obj):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
    return subprocess.run(["bash", str(OBSERVER_SH)], input=json.dumps(stdin_obj),
                          env=env, capture_output=True, text=True)


def test_observer_records_skill(tmp_path):
    proj, rd = _project_with_run(tmp_path)
    o = _drive(proj, {"tool_name": "Skill", "tool_input": {"name": "physicist-intake"}})
    assert o.returncode == 0, o.stdout + o.stderr
    st = json.loads((rd / "run_state.json").read_text())
    assert [e["skill"] for e in st["skills_invoked"]] == ["physicist-intake"]


def test_observer_records_edit_and_subagent_but_never_bash(tmp_path):
    proj, rd = _project_with_run(tmp_path)
    assert _drive(proj, {"tool_name": "Edit", "tool_input": {"file_path": "inputs/x.dat"}}).returncode == 0
    assert _drive(proj, {"tool_name": "Task",
                         "tool_input": {"subagent_type": "physics-reviewer"}}).returncode == 0
    # Bash is NEVER recorded by the observer (D-2): it cannot supply the N6 liveness fields, so
    # neither a plain `ls` nor a compute command may produce a compute_launched entry -- those
    # entries are written only by the DRIVE `record --kind compute` command.
    assert _drive(proj, {"tool_name": "Bash", "tool_input": {"command": "ls -la trial-runs"}}).returncode == 0
    assert _drive(proj, {"tool_name": "Bash",
                         "tool_input": {"command": "mg5_aMC run.mg5"}}).returncode == 0
    st = json.loads((rd / "run_state.json").read_text())
    assert [e["path"] for e in st["edits"]] == ["inputs/x.dat"]
    assert [e["agent_type"] for e in st["subagents"]] == ["physics-reviewer"]
    assert st["compute_launched"] == []                                       # observer never emits compute


def test_observer_never_blocks_when_no_active_run(tmp_path):
    proj = tmp_path / "empty"
    (proj / "trial-runs").mkdir(parents=True)          # no _infrastructure symlink -> WS missing
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
    o = subprocess.run(["bash", str(OBSERVER_SH)],
                       input=json.dumps({"tool_name": "Skill", "tool_input": {"name": "x"}}),
                       env=env, capture_output=True, text=True)
    assert o.returncode == 0
