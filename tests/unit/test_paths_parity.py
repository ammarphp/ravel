"""native/scripts/paths.sh and src/ravel/paths.py resolve the same prefix and binary directory."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from ravel import paths
from ravel.setup import installer

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src/ravel").mkdir(parents=True)
    (repo / "src/ravel/__init__.py").write_text("")
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n")
    (repo / "native/scripts").mkdir(parents=True)
    shutil.copy(ROOT / "native/scripts/paths.sh", repo / "native/scripts/paths.sh")
    return repo


def shell_paths(repo, env):
    command = 'source native/scripts/paths.sh && printf "%s\\n%s\\n" "$RAVEL_NATIVE_BUILD" "$RAVEL_NATIVE_BIN"'
    result = subprocess.run(["/bin/bash", "-c", command], cwd=repo, env={"PATH": "/usr/bin:/bin", **env},
                            capture_output=True, text=True, check=True)
    build, binary = result.stdout.splitlines()
    return Path(build), Path(binary)


def python_paths(repo, env, monkeypatch):
    for key in ("RAVEL_NATIVE_BUILD", "RAVEL_NATIVE_BIN", "BUILD_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RAVEL_ROOT", str(repo))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return paths.native_build_root(), paths.native_binary("x").parent


@pytest.mark.parametrize("case", ["default", "legacy", "pointer", "environment", "environment-and-bin"])
def test_shell_and_python_agree(checkout, tmp_path, monkeypatch, case):
    env = {}
    if case == "default":
        # With no toolchain anywhere, paths.sh stops unless a first installation is requested.
        env = {"RAVEL_NATIVE_PROVISION": "1"}
    elif case == "legacy":
        (checkout / "stages/01-event-generation/build").mkdir(parents=True)
    elif case == "pointer":
        (checkout / ".ravel").mkdir()
        (checkout / ".ravel/native-prefix").write_text(str(tmp_path / "pointed") + "\n")
    elif case == "environment":
        env = {"RAVEL_NATIVE_BUILD": str(tmp_path / "chosen")}
    elif case == "environment-and-bin":
        env = {"RAVEL_NATIVE_BUILD": str(tmp_path / "chosen"), "RAVEL_NATIVE_BIN": str(tmp_path / "programs")}
    shell = shell_paths(checkout, env)
    python = python_paths(checkout, env, monkeypatch)
    assert tuple(p.resolve() for p in shell) == tuple(p.resolve() for p in python)
    expected = {
        "default": (checkout / "native/build", checkout / "native/build/bin"),
        "legacy": (checkout / "stages/01-event-generation/build", checkout / "native/build/bin"),
        "pointer": (tmp_path / "pointed", tmp_path / "pointed/bin"),
        "environment": (tmp_path / "chosen", tmp_path / "chosen/bin"),
        "environment-and-bin": (tmp_path / "chosen", tmp_path / "programs"),
    }[case]
    assert tuple(p.resolve() for p in python) == tuple(p.resolve() for p in expected)
    # The installer resolves the same prefix that the runtime will use.
    assert installer.resolve_prefix(checkout, None, env).resolve() == python[0].resolve()


def test_conflicting_aliases_are_refused(checkout):
    result = subprocess.run(["/bin/bash", "-c", "source native/scripts/paths.sh"], cwd=checkout,
                            env={"PATH": "/usr/bin:/bin", "BUILD_DIR": "/one", "RAVEL_NATIVE_BUILD": "/two"},
                            capture_output=True, text=True)
    assert result.returncode != 0 and "disagree" in result.stderr
