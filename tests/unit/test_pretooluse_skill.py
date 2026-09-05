import json, os, subprocess
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude/hooks/pretooluse-skill.sh"

def _mk_run(project_dir, name, session=None, with_contract=False):
    """Build trial-runs/<name>/ with an optional run_state.json (session_id) and inputs/contract."""
    rd = project_dir / "trial-runs" / name
    (rd / "inputs").mkdir(parents=True)
    if session is not None:
        (rd / "run_state.json").write_text(
            json.dumps({"schema_version": 1, "session_id": session}))
    if with_contract:
        (rd / "inputs" / "task_contract.json").write_text("{}")
    return rd

def _run(skill, project_dir, cwd, session=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
    payload = {"tool_name": "Skill", "tool_input": {"skill": skill}, "cwd": str(cwd)}
    if session is not None:
        payload["session_id"] = session
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)

def test_bash_syntax_ok():
    assert subprocess.run(["bash", "-n", str(HOOK)]).returncode == 0

def test_blocks_gated_skill_when_active_run_has_no_contract(tmp_path):
    # A mature repo with OTHER runs that DO carry a contract must NOT mask a fresh active run with
    # none -- this is the R8-critical repo-wide-glob bug.
    _mk_run(tmp_path, "old_run", session="OLD1", with_contract=True)
    active = _mk_run(tmp_path, "active_run", session="SESS", with_contract=False)
    r = _run("new-analysis", tmp_path, active, session="SESS")   # active resolved from cwd
    assert r.returncode == 2 and "physicist-intake" in r.stderr

def test_blocks_when_no_active_run_resolvable(tmp_path):
    # Physics session, gated skill, cwd=repo root, no matching session -> conservative block even
    # though an unrelated run has a contract.
    _mk_run(tmp_path, "unrelated", session="OTHER", with_contract=True)
    r = _run("run-scan", tmp_path, tmp_path)
    assert r.returncode == 2 and "physicist-intake" in r.stderr

def test_allows_physicist_intake(tmp_path):
    _mk_run(tmp_path, "active_run", session="SESS", with_contract=False)
    assert _run("physicist-intake", tmp_path, tmp_path, session="SESS").returncode == 0

def test_allows_gated_skill_with_contract_in_active_run(tmp_path):
    active = _mk_run(tmp_path, "active_run", session="SESS", with_contract=True)
    # active run resolved from cwd; its inputs/task_contract.json is present -> allow
    assert _run("run-scan", tmp_path, active, session="SESS").returncode == 0

def test_allows_gated_skill_when_active_run_resolved_by_session(tmp_path):
    # cwd is the repo root, but the session's run_state.json ties us to the run with a contract.
    _mk_run(tmp_path, "active_run", session="SESS", with_contract=True)
    assert _run("certify", tmp_path, tmp_path, session="SESS").returncode == 0

def test_ignores_ungated_skill(tmp_path):
    _mk_run(tmp_path, "active_run", session="SESS", with_contract=False)
    assert _run("judgment-protocols", tmp_path, tmp_path, session="SESS").returncode == 0


# ------------------------------------------------------- Task 3 (A3): fan-out-before-routing guard
def _run_tool(tool_name, project_dir, cwd, session=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
    payload = {"tool_name": tool_name, "tool_input": {}, "cwd": str(cwd)}
    if session is not None:
        payload["session_id"] = session
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)


def _touch_marker(project_dir, session):
    (project_dir / "logs").mkdir(exist_ok=True)
    (project_dir / "logs" / f".route-pending-{session}").write_text("")


def test_agent_fanout_blocked_while_route_pending(tmp_path):
    (tmp_path / "trial-runs").mkdir()
    _touch_marker(tmp_path, "SESSX")
    r = _run_tool("Agent", tmp_path, tmp_path, session="SESSX")
    assert r.returncode == 2 and "physicist-intake" in r.stderr


def test_task_fanout_blocked_while_route_pending(tmp_path):
    (tmp_path / "trial-runs").mkdir()
    _touch_marker(tmp_path, "SESSX")
    r = _run_tool("Task", tmp_path, tmp_path, session="SESSX")
    assert r.returncode == 2


def test_agent_fanout_allowed_once_contract_exists_and_marker_cleared(tmp_path):
    _mk_run(tmp_path, "active", session="SESSX", with_contract=True)
    _touch_marker(tmp_path, "SESSX")
    r = _run_tool("Agent", tmp_path, tmp_path, session="SESSX")
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "logs" / ".route-pending-SESSX").exists()   # consumed


def test_agent_fanout_inert_for_other_session(tmp_path):
    (tmp_path / "trial-runs").mkdir()
    _touch_marker(tmp_path, "SESSY")
    r = _run_tool("Agent", tmp_path, tmp_path, session="SESSX")
    assert r.returncode == 0


def test_agent_fanout_inert_without_marker(tmp_path):
    (tmp_path / "trial-runs").mkdir()   # dev session: no marker -> never blocked
    r = _run_tool("Agent", tmp_path, tmp_path, session="SESSX")
    assert r.returncode == 0
