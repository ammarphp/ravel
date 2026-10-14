"""Native toolchain discovery from checkouts, linked worktrees and the shared location."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ravel import paths

ROOT = Path(__file__).resolve().parents[2]
PATHS_SH = ROOT / "native" / "scripts" / "paths.sh"


def _checkout(path):
    (path / "src" / "ravel").mkdir(parents=True)
    (path / "src" / "ravel" / "__init__.py").write_text("")
    (path / "pyproject.toml").write_text("[project]\nname='ravel'\n")
    (path / "native" / "scripts").mkdir(parents=True)
    shutil.copy(PATHS_SH, path / "native" / "scripts" / "paths.sh")
    return path


def _linked_worktree(main, worktree, name="feature"):
    """Lay out the files git writes for `git worktree add`, without invoking git."""
    gitdir = main / ".git" / "worktrees" / name
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n")
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n")


@pytest.fixture
def layout(tmp_path, monkeypatch):
    for var in ("RAVEL_NATIVE_BUILD", "RAVEL_NATIVE_BIN", "BUILD_DIR", "RAVEL_ROOT",
                "XDG_DATA_HOME", "RAVEL_NATIVE_PROVISION"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    main = _checkout(tmp_path / "main")
    work = _checkout(tmp_path / "main-worktrees" / "feature")
    _linked_worktree(main, work)
    return main, work


def test_worktree_uses_the_main_checkout_toolchain(layout):
    main, work = layout
    (main / "native" / "build" / "tools").mkdir(parents=True)
    (main / "native" / "build" / "bin").mkdir()
    (main / "native" / "build" / "bin" / "pythia_shower").write_text("")
    assert paths.main_checkout(work) == main
    assert paths.native_build_root(work) == main / "native" / "build"
    assert paths.native_binary("pythia_shower", work) == main / "native" / "build" / "bin" / "pythia_shower"


def test_existing_development_build_keeps_precedence(layout):
    main, work = layout
    legacy = main / "stages" / "01-event-generation" / "build"
    legacy.mkdir(parents=True)
    (main / "native" / "build").mkdir(parents=True)
    assert paths.native_build_root(work) == legacy


def test_the_checkout_own_build_wins_over_the_main_checkout(layout):
    main, work = layout
    (main / "native" / "build").mkdir(parents=True)
    (work / "native" / "build").mkdir(parents=True)
    assert paths.native_build_root(work) == work / "native" / "build"


def test_shared_user_location_is_found(layout, tmp_path):
    _, work = layout
    shared = tmp_path / "home" / ".local" / "share" / "ravel-native"
    shared.mkdir(parents=True)
    assert paths.native_build_root(work) == shared


def test_xdg_data_home_moves_the_shared_location(layout, tmp_path, monkeypatch):
    _, work = layout
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    shared = tmp_path / "data" / "ravel-native"
    shared.mkdir(parents=True)
    assert paths.native_build_root(work) == shared


def test_override_wins_and_missing_build_keeps_the_conventional_path(layout, tmp_path, monkeypatch):
    _, work = layout
    assert paths.native_build_root(work) == work / "native" / "build"
    monkeypatch.setenv("RAVEL_NATIVE_BUILD", str(tmp_path / "elsewhere"))
    assert paths.native_build_root(work) == tmp_path / "elsewhere"


# ---------------------------------------------------------------- the shell helper
def _source(shell, script, env, cwd):
    cmd = (f'source "{script}" && printf "%s\\n%s\\n" "$RAVEL_NATIVE_BUILD" "$RAVEL_NATIVE_BIN"')
    return subprocess.run([shell, "-c", cmd], env=env, cwd=cwd, capture_output=True, text=True)


def _shell_env(tmp_path, **extra):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")}
    env.update(extra)
    return env


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_paths_sh_resolves_the_main_checkout_from_either_shell(layout, tmp_path, shell):
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} unavailable")
    main, work = layout
    legacy = main / "stages" / "01-event-generation" / "build"
    legacy.mkdir(parents=True)
    (main / "native" / "build" / "bin").mkdir(parents=True)
    # source from an unrelated directory: the helper must locate itself, not the caller
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = _source(shell, work / "native" / "scripts" / "paths.sh", _shell_env(tmp_path), elsewhere)
    assert out.returncode == 0, out.stderr
    build, binary = out.stdout.splitlines()
    assert Path(build).resolve() == legacy.resolve()
    assert Path(binary).resolve() == (main / "native" / "build" / "bin").resolve()


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_paths_sh_fails_loudly_when_no_build_exists(layout, tmp_path, shell):
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} unavailable")
    _, work = layout
    out = _source(shell, work / "native" / "scripts" / "paths.sh", _shell_env(tmp_path), tmp_path)
    assert out.returncode != 0
    assert "native build" in out.stderr.lower()
    assert str(work / "native" / "build") in out.stderr
    assert "RAVEL_NATIVE_BUILD" in out.stderr


def test_paths_sh_allows_a_first_installation(layout, tmp_path):
    _, work = layout
    out = _source("bash", work / "native" / "scripts" / "paths.sh",
                  _shell_env(tmp_path, RAVEL_NATIVE_PROVISION="1"), tmp_path)
    assert out.returncode == 0, out.stderr
    assert Path(out.stdout.splitlines()[0]) == (work / "native" / "build").resolve() or \
        out.stdout.splitlines()[0] == str(work / "native" / "build")


def test_paths_sh_keeps_an_explicit_prefix_for_provisioning(layout, tmp_path):
    _, work = layout
    target = tmp_path / "new-prefix"
    out = _source("bash", work / "native" / "scripts" / "paths.sh",
                  _shell_env(tmp_path, RAVEL_NATIVE_BUILD=str(target)), tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines()[0] == str(target)
    assert "does not exist" in out.stderr


def test_paths_sh_rejects_disagreeing_aliases(layout, tmp_path):
    _, work = layout
    out = _source("bash", work / "native" / "scripts" / "paths.sh",
                  _shell_env(tmp_path, RAVEL_NATIVE_BUILD=str(tmp_path / "a"),
                             BUILD_DIR=str(tmp_path / "b")), tmp_path)
    assert out.returncode != 0 and "disagree" in out.stderr
