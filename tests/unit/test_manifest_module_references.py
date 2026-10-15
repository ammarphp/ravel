"""Every RAVEL module the toolchain manifest names resolves in this checkout."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "native" / "setup" / "toolchain-manifest.json"

# A dotted name that starts at a word boundary and is not the tail of a file
# name or path (``CMakeLists-ravel.cmake`` is a file, not a module).
_REFERENCE = re.compile(r"(?<![\w./{}-])ravel(?:\.[A-Za-z_][A-Za-z0-9_]*)+")


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def module_references(manifest) -> set[str]:
    """Return every ``ravel.<module>`` name a manifest string refers to."""
    found: set[str] = set()
    for text in _strings(manifest):
        found.update(match.group(0) for match in _REFERENCE.finditer(text))
    return found


def unresolved(names) -> list[str]:
    missing = []
    for name in sorted(names):
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            missing.append(name)
    return missing


def test_manifest_loads_and_names_modules():
    manifest = json.loads(MANIFEST.read_text())
    names = module_references(manifest)
    assert "ravel.workflow.execution_backend" in names


def test_every_manifest_module_reference_resolves():
    manifest = json.loads(MANIFEST.read_text())
    assert unresolved(module_references(manifest)) == []


def test_reference_scan_flags_a_module_that_does_not_exist():
    synthetic = {
        "groups": [
            {"id": "g", "module": "ravel.workflow.execution_backend"},
            {"id": "h", "steps": ["ravel.workflow.no_such_module_here"]},
            {"id": "i", "files": ["{TOOLS}/overlay/ravel/CMakeLists-ravel.cmake"]},
            {"id": "j", "notes": "runs as `ravel.workflow.backends.magnus_cli`."},
        ]
    }
    names = module_references(synthetic)
    assert "ravel.cmake" not in names
    assert unresolved(names) == ["ravel.workflow.no_such_module_here"]
