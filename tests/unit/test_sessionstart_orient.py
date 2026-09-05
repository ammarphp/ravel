"""SessionStart orientation + artifact-keyed delivery (R3 T5, H6+H7).

Run from OUTSIDE the repo: cd /tmp && python3 -m pytest <abspath> -q
"""
import json, os, subprocess, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
ORIENT = REPO / ".claude" / "hooks" / "sessionstart-orient.sh"
SD = REPO / "src" / "ravel" / "workflow" / "stop_dispatch.py"


def test_orient_emits_context_for_newest_run(tmp_path):
    rd = tmp_path / "trial-runs" / "runA"
    rd.mkdir(parents=True)
    (rd / "run_state.json").write_text(json.dumps(
        {"schema_version": 1, "session_id": "S", "current_step": "generation",
         "next_required": {"what": "run-stage shower", "why": "gen"}}))
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
    r = subprocess.run(["bash", str(ORIENT)], input="{}", capture_output=True, text=True, env=env)
    assert r.returncode == 0
    assert "ACTIVE RUN" in r.stdout and "generation" in r.stdout and "MANDATORY" in r.stdout


def test_orient_silent_with_no_runs(tmp_path):
    (tmp_path / "trial-runs").mkdir()
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
    r = subprocess.run(["bash", str(ORIENT)], input="{}", capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_fresh_delivery_artifact_triggers_open_defect_gate(tmp_path):
    """H7: a bland last message + a freshly written RESULT.md must still count as delivery."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "run_state.json").write_text(json.dumps(
        {"schema_version": 1, "session_id": "S",
         "open_defect_notes": [{"helper": "read_x.py", "note": "bug", "status": "open"}],
         "skills_invoked": [{"skill": "x"}], "compute_launched": [{"cmd": "x"}]}))
    (tmp_path / "RESULT.md").write_text("# result\n")
    r = subprocess.run([sys.executable, str(SD), "--rundir", str(tmp_path),
                        "--last-message", "ok", "--branch", "open-defect"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 2 and "OPEN-DEFECT" in r.stderr


def test_stale_artifacts_not_delivery(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "run_state.json").write_text(json.dumps(
        {"schema_version": 1, "session_id": "S",
         "open_defect_notes": [{"helper": "read_x.py", "note": "bug", "status": "open"}],
         "skills_invoked": [{"skill": "x"}], "compute_launched": [{"cmd": "x"}]}))
    p = tmp_path / "RESULT.md"
    p.write_text("# result\n")
    old = time.time() - 7200
    os.utime(p, (old, old))
    r = subprocess.run([sys.executable, str(SD), "--rundir", str(tmp_path),
                        "--last-message", "ok", "--branch", "open-defect"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0
