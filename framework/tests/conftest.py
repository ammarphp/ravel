"""Shared test configuration.

DEV-ONLY LIVE PINS: tests named `test_live_*` assert pinned values of the FULL dev repo's live
state (audit readiness %, evidence-manifest cleanliness against every dev run dir). In the
public distribution export those pins are meaningless — the export ships a curated evidence
subset, so the live numbers legitimately differ. They auto-skip outside the dev repo, detected
by a dev-only sentinel file that the export deliberately does not ship (ORCHESTRATION.md).
Everything else in the suite runs identically in both trees.
"""
import os

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_IS_DEV = os.path.exists(os.path.join(_REPO, "ORCHESTRATION.md"))


def pytest_collection_modifyitems(config, items):
    if _IS_DEV:
        return
    skip = pytest.mark.skip(reason="live dev-repo state pin (public export ships a curated "
                                   "evidence subset; the pinned live numbers apply to the dev "
                                   "tree only)")
    # Semantically dev-bound tests (beyond the test_live_* naming convention), each with its
    # reason: the pristine-card guard protects operator-workspace originals that a public clone
    # deliberately does not contain.
    dev_bound = {
        # pristine-card guard: protects operator-workspace originals a clone doesn't contain
        "test_drive_hook_blocks_on_the_real_card_guard",
        # dev state-board integration pins: they assert the FULL dev tree's reconciliation
        # gates (statefresh/dirmap-hard-fail). Distribution trees soften those by design
        # (2026-07-30: dirmap dev-only rows -> WARN; curated evidence subset shifts live
        # numbers) and are guarded publicly by claims_check + check_evidence + replay + spine.
        "test_clean_repo_passes",
        "test_agent_surface_green",
        "test_dirmap_flags_dangling_row_the_g20_trigger",
    }
    for item in items:
        if item.name.startswith("test_live_") or item.name in dev_bound:
            item.add_marker(skip)
