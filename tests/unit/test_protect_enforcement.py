"""Enforcement-surface self-protection (R3 T4, H3/N9).

Run from OUTSIDE the repo: cd /tmp && python3 -m pytest <abspath> -q
"""
import json, os, subprocess
import pytest
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "protect-enforcement.sh"


def _run(file_path, project_dir, session=None, marker=False, run=False):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
    if marker and session:
        (project_dir / "logs").mkdir(exist_ok=True)
        (project_dir / "logs" / f".route-pending-{session}").write_text("")
    if run and session:
        rd = project_dir / "trial-runs" / "runX"
        (rd / "inputs").mkdir(parents=True, exist_ok=True)
        (rd / "run_state.json").write_text(json.dumps(
            {"schema_version": 1, "session_id": session}))
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}
    if session is not None:
        payload["session_id"] = session
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)


def test_blocks_gate_tool_edit_in_marker_session(tmp_path):
    (tmp_path / "trial-runs").mkdir()
    r = _run(tmp_path / "src" / "ravel" / "workflow" / "stop_dispatch.py",
             tmp_path, session="P1", marker=True)
    assert r.returncode == 2 and "read-only" in r.stderr


def test_blocks_settings_edit_in_run_session(tmp_path):
    r = _run(tmp_path / ".claude" / "settings.json", tmp_path, session="P1", run=True)
    assert r.returncode == 2


def test_allows_in_dev_session(tmp_path):
    (tmp_path / "trial-runs").mkdir()
    r = _run(tmp_path / "src" / "ravel" / "workflow" / "stop_dispatch.py",
             tmp_path, session="D1")
    assert r.returncode == 0


def test_allows_physics_file_even_in_session(tmp_path):
    r = _run(tmp_path / "src" / "ravel" / "plotting" / "overlay_on_data.py",
             tmp_path, session="P1", run=True)
    assert r.returncode == 0


@pytest.mark.parametrize("relative", [
    "src/ravel/validation/validate_task_contract.py",
    "src/ravel/validation/benchmark.py",
    "src/ravel/evidence_layout.py",
    "src/ravel/paths.py",
    "tests/adversarial/run_suite.py",
    "scripts/check_repository.py",
])
def test_reorganized_enforcement_paths_remain_protected(tmp_path, relative):
    result = _run(tmp_path / relative, tmp_path, session="P1", marker=True)
    assert result.returncode == 2
