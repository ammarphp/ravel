"""Ravel's task-contract API; full simulation remains workflow-driven."""


def _declared_version():
    """The version `pyproject.toml` declares: read from it in a source tree, else from the
    installed distribution's metadata, which the build copies from that file.

    A sandboxed worker reads `src/` only: the stat of the file above it is refused, and the
    package must still import (the broker's MCP face runs there)."""
    from pathlib import Path
    project = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        text = project.read_text() if project.is_file() else None
    except OSError:
        text = None
    if text is not None:
        import tomllib
        table = tomllib.loads(text).get("project", {})
        if table.get("name") == "ravel-hep":
            return table["version"]
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("ravel-hep")
    except PackageNotFoundError:
        return "unknown"


__version__ = _declared_version()
__all__ = ["validate_task_contract", "__version__"]


def validate_task_contract(contract: object) -> list[str]:
    """Return errors; an empty list means schema-valid, not compute-approved."""
    from .validation.validate_task_contract import validate
    return validate(contract)


# Register role-owned enforcement surfaces before governance-first consumers run.
# The callback is idempotent and imports no card data or scientific toolchain.
# A closed staged copy of selected source modules carries neither the registry
# nor the governance module it registers into. Only that exact joint absence
# leaves the registration out; a tree with governance must have its registry.
import importlib as _importlib
import importlib.util as _importlib_util
try:
    _role_registry = _importlib.import_module(__name__ + '.workflow.role_registry')
except ModuleNotFoundError as _absent:
    if (_absent.name != __name__ + '.workflow.role_registry'
            or _importlib_util.find_spec(__name__ + '.workflow.host_governance') is not None):
        raise
else:
    _role_registry.register_surface_extension()
    del _role_registry
del _importlib, _importlib_util
