"""The host write guard remains enforceable when its package cannot import."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude/hooks"


def _env(project, tmp_path, **values):
    return dict(os.environ, CLAUDE_PROJECT_DIR=str(project), RAVEL_PYTHON=sys.executable,
                RAVEL_STATE_DIR=str(tmp_path / "state"), HOME=str(tmp_path), **values)


def _guard(project, path, env, cwd=""):
    return subprocess.run(["bash", str(HOOKS / "protect-enforcement.sh")],
                          input=json.dumps({"tool_name": "Edit", "session_id": "S-GUARD", "cwd": cwd,
                                            "tool_input": {"file_path": str(path)}}),
                          text=True, capture_output=True, env=env, cwd=project)


def _physics_project(tmp_path):
    project = tmp_path / "project"
    (project / "logs").mkdir(parents=True)
    (project / "logs/.route-pending-S-GUARD").touch()
    return project


@pytest.mark.parametrize("rel", [
    "src/ravel/data/transports/claude-cli-oneshot.json",
    "src/ravel/data/gates/providers.json",
    "src/ravel/workflow/transport_receipt.py",
    ".claude/ravel-gate.sh", ".codex/ravel-gate.sh", ".gemini/ravel-gate.sh",
    ".codex/adapters/ravel-gate.sh",
])
def test_transport_gate_and_shim_paths_are_guarded(tmp_path, rel):
    project = _physics_project(tmp_path)
    done = _guard(project, project / rel, _env(project, tmp_path))
    assert done.returncode == 2, done.stdout + done.stderr


@pytest.mark.parametrize("exists", [True, False])
def test_registered_extension_path_is_guarded(tmp_path, exists):
    project = _physics_project(tmp_path)
    (project / "src").symlink_to(REPO / "src")
    extension = project / "authority/policy.json"
    extension.parent.mkdir()
    if exists:
        extension.write_text("{}")
    startup = tmp_path / "startup"
    startup.mkdir()
    (startup / "sitecustomize.py").write_text(
        "from ravel.workflow import host_governance as hg\n"
        f"hg.SURFACE_EXTENSIONS += (lambda: {{'fixture': {str(extension)!r}}},)\n")
    env = _env(project, tmp_path)
    env["PYTHONPATH"] = str(startup) + os.pathsep + str(REPO / "src")
    done = _guard(project, extension, env)
    assert done.returncode == 2, done.stdout + done.stderr


def test_symlink_alias_to_enforcement_file_is_guarded(tmp_path):
    project = _physics_project(tmp_path)
    settings = project / ".claude/settings.json"
    settings.parent.mkdir()
    settings.write_text("{}")
    alias = project / "innocent.json"
    alias.symlink_to(settings)
    done = _guard(project, alias, _env(project, tmp_path))
    assert done.returncode == 2, done.stdout + done.stderr


def test_symlink_parent_alias_to_uncreated_enforcement_path_is_guarded(tmp_path):
    project = _physics_project(tmp_path)
    hooks = project / ".claude/hooks"
    hooks.mkdir(parents=True)
    alias = project / "notes"
    alias.symlink_to(hooks, target_is_directory=True)
    done = _guard(project, alias / "new.sh", _env(project, tmp_path))
    assert done.returncode == 2, done.stdout + done.stderr


@pytest.mark.parametrize("physics", ["marker", "registry", "cwd"])
def test_missing_ravel_import_blocks_physics_write(tmp_path, physics):
    project = tmp_path / "project"
    project.mkdir()
    env = _env(project, tmp_path)
    # A real Python interpreter that retains stdlib but cannot load source or site packages.
    missing = tmp_path / "without-ravel"
    missing.write_text("#!/bin/sh\nunset PYTHONPATH\nexec " + shlex.quote(sys.executable) + ' -S "$@"\n')
    missing.chmod(0o755)
    env["RAVEL_PYTHON"] = str(missing)
    cwd = ""
    if physics == "marker":
        (project / "logs").mkdir()
        (project / "logs/.route-pending-S-GUARD").touch()
    else:
        run = tmp_path / "registered-run" if physics == "registry" else project / "trial-runs/run"
        run.mkdir(parents=True)
        (run / "run_state.json").write_text("{}")
        if physics == "registry":
            from ravel.workflow import active_run
            record = Path(env["RAVEL_STATE_DIR"]) / "active-runs"
            record.mkdir(parents=True)
            import hashlib
            key = hashlib.sha256(b"S-GUARD").hexdigest()[:32] + ".json"
            (record / key).write_text(json.dumps({"schema_version": 1, "kind": active_run.KIND,
                                                "session_id": "S-GUARD", "rundir": str(run)}))
        else:
            cwd = str(run)
    done = _guard(project, project / ".claude/hooks/x.sh", env, cwd)
    assert done.returncode == 2 and "unavailable" in done.stderr, done.stdout + done.stderr


def test_observer_logs_failed_import_and_allows(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    missing = tmp_path / "without-ravel"
    missing.write_text("#!/bin/sh\nunset PYTHONPATH\nexec " + shlex.quote(sys.executable) + ' -S "$@"\n')
    missing.chmod(0o755)
    env = _env(project, tmp_path)
    env["RAVEL_PYTHON"] = str(missing)
    done = subprocess.run(["bash", str(HOOKS / "posttooluse-observer.sh")], input="{}",
                          capture_output=True, text=True, env=env, cwd=project)
    assert done.returncode == 0
    assert "unavailable" in done.stderr
    assert "unavailable" in (project / "logs/hook-failures.log").read_text()


def test_hooks_use_recorded_python():
    for path in HOOKS.glob("*.sh"):
        lines = [line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")]
        python_lines = [line for line in lines if "python3" in line]
        assert all('${RAVEL_PYTHON:-python3}' in line or "echo " in line for line in python_lines), path
