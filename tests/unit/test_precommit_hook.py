"""Exercise the real installer in isolated Git checkouts, never the user's hooks."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / "scripts/maintenance/install-git-hooks.sh"
CENSUS = REPO / "src/ravel/validation/check_agent_surface.py"


def _environment(**updates):
    # A caller's Git worktree/index or global hooksPath must never redirect an
    # isolated test into the actual checkout or a shared user hook directory.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    env.update(updates)
    return env


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, env=_environment(),
                          capture_output=True, text=True, check=True)


def _hooks_dir(repo):
    value = _git(repo, "rev-parse", "--git-path", "hooks").stdout.strip()
    assert value, "Git returned an empty hooks path"
    return Path(value) if os.path.isabs(value) else repo / value


def _checkout(tmp_path, *, separate_git_dir=False):
    repo = tmp_path / "checkout with spaces"
    repo.mkdir()
    args = ["init", "-q"]
    if separate_git_dir:
        args += ["--separate-git-dir", str(tmp_path / "git metadata")]
    _git(repo, *args)
    checker = repo / "src/ravel/validation/check_agent_surface.py"
    checker.parent.mkdir(parents=True)
    checker.write_text(
        "import os, sys\n"
        "print('isolated-checker-executed')\n"
        "sys.exit(int(os.environ.get('RAVEL_TEST_CHECKER_RC', '0')))\n"
    )
    return repo, checker


def _install(repo, env=None):
    return subprocess.run(["bash", str(INSTALLER)], cwd=repo,
                          env=_environment() if env is None else env,
                          capture_output=True, text=True)


@pytest.mark.parametrize("separate_git_dir", [False, True])
def test_installer_creates_executable_hook(tmp_path, separate_git_dir):
    repo, _ = _checkout(tmp_path, separate_git_dir=separate_git_dir)
    result = _install(repo)
    assert result.returncode == 0, result.stderr
    hook = _hooks_dir(repo) / "pre-commit"
    assert hook.is_file(), "pre-commit hook not installed"
    assert os.access(hook, os.X_OK), "pre-commit hook not executable"
    assert "check_agent_surface.py" in hook.read_text()
    assert str(hook) in result.stdout
    if separate_git_dir:
        assert (repo / ".git").is_file()
        assert hook.parent == tmp_path / "git metadata/hooks"


@pytest.mark.parametrize("relative_hooks", [None, "custom hooks/location"])
def test_nested_invocation_installs_at_git_declared_top_level_path(tmp_path, relative_hooks):
    repo, _ = _checkout(tmp_path)
    if relative_hooks is not None:
        _git(repo, "config", "core.hooksPath", relative_hooks)
    nested = repo / "nested"
    nested.mkdir()
    result = _install(nested)
    assert result.returncode == 0, result.stderr
    expected = repo / (relative_hooks or ".git/hooks") / "pre-commit"
    assert expected.is_file(), result.stdout
    assert os.access(expected, os.X_OK)
    assert str(expected) in result.stdout
    assert not (tmp_path / ".git/hooks/pre-commit").exists()


@pytest.mark.parametrize("checker_exit", [0, 7, 23])
def test_hook_propagates_check_agent_surface_exit(tmp_path, checker_exit):
    repo, checker = _checkout(tmp_path)
    result = _install(repo)
    assert result.returncode == 0, result.stderr
    env = _environment(RAVEL_TEST_CHECKER_RC=str(checker_exit))
    direct = subprocess.run([sys.executable, str(checker)], cwd=repo, env=env,
                            capture_output=True, text=True)
    viahook = subprocess.run(["bash", str(_hooks_dir(repo) / "pre-commit")],
                             cwd=repo, env=env, capture_output=True, text=True)
    assert viahook.returncode == direct.returncode == checker_exit
    assert "isolated-checker-executed" in viahook.stdout
    assert ("check_agent_surface FAILED" in viahook.stderr) == (checker_exit != 0)


def test_hook_runs_actual_surface_checker_in_isolated_checkout(tmp_path):
    repo, checker = _checkout(tmp_path)
    # Keep the real source/stage checker and its inputs. Only its hook installation
    # lives in this throwaway repository, rather than changing the user's hooks.
    checker.write_text("import runpy\nrunpy.run_path(" + repr(str(CENSUS)) +
                       ", run_name='__main__')\n")
    installed = _install(repo)
    assert installed.returncode == 0, installed.stderr
    direct = subprocess.run([sys.executable, str(CENSUS)], cwd=REPO,
                            env=_environment(), capture_output=True, text=True)
    viahook = subprocess.run(["bash", str(_hooks_dir(repo) / "pre-commit")], cwd=repo,
                             env=_environment(), capture_output=True, text=True)
    assert direct.returncode == 0, direct.stdout + direct.stderr
    assert viahook.returncode == direct.returncode, viahook.stdout + viahook.stderr
    assert "agent surface: OK" in viahook.stdout


def test_nonrepository_refuses_before_any_write(tmp_path):
    before = list(tmp_path.iterdir())
    result = _install(tmp_path, _environment(GIT_CEILING_DIRECTORIES=str(tmp_path.parent.resolve())))
    assert result.returncode != 0
    assert "not a git repository" in result.stderr.lower()
    assert "installed pre-commit" not in result.stdout
    assert list(tmp_path.iterdir()) == before


@pytest.mark.parametrize("failing_query", ["--show-toplevel", "--git-path"])
def test_git_resolution_failure_never_reaches_mutation(tmp_path, failing_query):
    # Fake Git only controls the failure point; mutation commands are tripwires.
    # This checks refusal before writes without ever allowing the old /pre-commit
    # fallback to target the filesystem root.
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "mutations.log"
    git = tools / "git"
    git.write_text("#!/bin/sh\n"
                   'for arg in "$@"; do\n'
                   '  if [ "$arg" = "$RAVEL_TEST_FAIL_QUERY" ]; then exit 31; fi\n'
                   'done\n'
                   'printf "%s\\n" "$RAVEL_TEST_REPO"\n')
    git.chmod(0o755)
    for name in ("mkdir", "chmod", "cat"):
        command = tools / name
        command.write_text("#!/bin/sh\nprintf '%s\\n' " + name +
                           ' >> "$RAVEL_TEST_MUTATIONS"\nexit 37\n')
        command.chmod(0o755)
    env = _environment(PATH=str(tools) + os.pathsep + os.environ["PATH"],
                       RAVEL_TEST_FAIL_QUERY=failing_query, RAVEL_TEST_REPO=str(tmp_path),
                       RAVEL_TEST_MUTATIONS=str(log))
    result = _install(tmp_path, env)
    assert result.returncode == 31
    assert "installed pre-commit" not in result.stdout
    assert not log.exists()
    assert not (tmp_path / "pre-commit").exists()


def test_failed_install_does_not_print_success(tmp_path):
    repo, _ = _checkout(tmp_path)
    _git(repo, "config", "core.hooksPath", "blocked-hooks")
    (repo / "blocked-hooks").write_text("existing regular file prevents directory creation")
    result = _install(repo)
    assert result.returncode != 0
    assert "installed pre-commit" not in result.stdout
    assert (repo / "blocked-hooks").read_text() == "existing regular file prevents directory creation"
