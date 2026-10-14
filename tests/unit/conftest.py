"""Shared test configuration.

One test compares the whole checkout's live evidence inventory with pinned numbers. A distributed
tree carries a curated evidence subset, so it runs only where the full inventory is present.
Source contracts, synthetic process lifecycles and temporary output checks run in every tree,
with their own platform and resource prerequisites.
"""
from pathlib import Path

import pytest

from ravel import evidence_layout

_REPO = Path(__file__).resolve().parents[2]
_FULL_INVENTORY = not evidence_layout.is_public_tree(_REPO)

_FULL_INVENTORY_NODES = {
    "tests/unit/test_check_evidence.py::test_live_evidence_manifest_checks_clean",
}


def pytest_collection_modifyitems(config, items):
    if _FULL_INVENTORY:
        return
    skip = pytest.mark.skip(reason="pins the full evidence inventory, which a distributed tree curates")
    for item in items:
        if item.nodeid in _FULL_INVENTORY_NODES:
            item.add_marker(skip)
