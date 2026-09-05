"""Locations for source checkouts, packaged data, and optional native tools."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def repository_root(start: str | Path | None = None) -> Path | None:
    """Find a Ravel source checkout without assuming the caller's directory depth.

    An explicit start confines the search to that path and its ancestors. Otherwise
    RAVEL_ROOT, this package's location, and the current directory are considered.
    Installed package data is deliberately not treated as a source checkout.
    """
    starts = ([Path(start)] if start is not None else
              ([Path(os.environ["RAVEL_ROOT"])] if os.environ.get("RAVEL_ROOT") else [])
              + [Path(__file__), Path.cwd()])
    for candidate in starts:
        candidate = candidate.expanduser().resolve()
        if candidate.is_file():
            candidate = candidate.parent
        for parent in (candidate, *candidate.parents):
            if ((parent / "pyproject.toml").is_file()
                    and (parent / "src/ravel/__init__.py").is_file()):
                return parent
    return None


def require_repository_root(start: str | Path | None = None) -> Path:
    root = repository_root(start)
    if root is None:
        raise FileNotFoundError("This operation requires a Ravel source checkout. "
                                "Set RAVEL_ROOT to its directory or run from that checkout.")
    return root


def package_data_path(*parts: str) -> Path:
    """Locate read-only package assets (Python wheels are installed unpacked)."""
    return Path(__file__).resolve().parent.joinpath("data", *parts)


def native_build_root() -> Path:
    """Locate optional native tools without relocating an existing installation.

    New installations use native/build. Existing development installations retain
    their original toolchain bytes; RAVEL_NATIVE_BUILD overrides either location.
    """
    override = os.environ.get("RAVEL_NATIVE_BUILD")
    if override:
        return Path(override).expanduser().resolve()
    root = repository_root() or Path.cwd()
    legacy = root / "stages/01-event-generation/build"
    return legacy if legacy.is_dir() else root / "native/build"


def native_binary(name: str) -> Path:
    """Find a generated native executable; these binaries are never wheel contents."""
    if Path(name).name != name:
        raise ValueError("native binary name must be a filename")
    override = os.environ.get("RAVEL_NATIVE_BIN")
    directory = (Path(override).expanduser().resolve() if override else
                 (repository_root() or Path.cwd()) / "native/build/bin")
    return directory / name


def module_command(module: str, *args: object, python=None) -> list[str]:
    """Invoke the same package with an optional external Python interpreter.

    The one package bootstrap works for editable and ordinary installations, and
    for native conda interpreters without installing replay dependencies there.
    A sequence may be supplied for a prefix such as conda run -n rivet python.
    """
    prefix = ([sys.executable] if python is None else
              [str(python)] if isinstance(python, (str, Path)) else list(python))
    return [*prefix, str(Path(__file__).with_name("_bootstrap.py")), module,
            *(str(arg) for arg in args)]
