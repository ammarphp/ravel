import json, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude/hooks/userpromptsubmit-router.sh"

def _run(prompt):
    import os
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(REPO))
    return subprocess.run(["bash", str(HOOK)], input=json.dumps({"prompt": prompt}),
                          capture_output=True, text=True, env=env)

def test_bash_syntax_ok():
    assert subprocess.run(["bash", "-n", str(HOOK)]).returncode == 0

def test_injects_reminder_on_physics_prompt():
    r = _run("Initiate: reproduce Figure 3 of arXiv:2306.11055")
    assert r.returncode == 0
    assert "physicist-intake" in r.stdout and "additionalContext" in r.stdout

def test_silent_on_dev_prompt():
    r = _run("fix the typo in the README")
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_router_touches_route_pending_marker():
    """A3: physics classification leaves a session-keyed marker the fan-out guard keys on."""
    import os
    sid = "T3MARKERTEST"
    marker = REPO / "logs" / f".route-pending-{sid}"
    marker.unlink(missing_ok=True)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(REPO))
    r = subprocess.run(["bash", str(HOOK)],
                       input=json.dumps({"prompt": "Initiate: reproduce Figure 3 of arXiv:2306.11055",
                                         "session_id": sid}),
                       capture_output=True, text=True, env=env)
    try:
        assert r.returncode == 0 and "additionalContext" in r.stdout
        assert marker.is_file()
    finally:
        marker.unlink(missing_ok=True)
