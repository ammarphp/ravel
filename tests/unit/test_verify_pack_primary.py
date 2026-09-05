# tests/unit/test_verify_pack_primary.py
"""verify_pack.check_figure_target -- primary-aware FAIL (Phase 3, D9/G10).

A PRIMARY figure target declared at check-in but unfulfilled (null counterpart, or a counterpart
with no composed side_by_side) must flip verify_pack to FAIL (exit 1); a non-primary unfulfilled
target stays an advisory WARN. Import by file path (py.py shadow); call the checker directly with a
Report so no rundir/on-disk artifacts are needed for the DECLARED-but-unfulfilled branches.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VP_PY = REPO / "src" / "ravel" / "validation" / "verify_pack.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_pack_under_test", VP_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _levels(rep):
    return [lvl for (lvl, _a, _m) in rep.lines]


def test_primary_unfulfilled_counterpart_fails():
    vp = _load_module()
    rep = vp.Report()
    doc = {"targets": [{"figure_id": "Figure 3", "primary": True,
                        "declared_at_checkin": True, "generated_counterpart": None}]}
    vp.check_figure_target(rep, "/nonexistent", {}, "figure_target.json", doc)
    assert "FAIL" in _levels(rep)


def test_primary_counterpart_without_side_by_side_fails():
    vp = _load_module()
    rep = vp.Report()
    doc = {"targets": [{"figure_id": "Figure 3", "primary": True, "declared_at_checkin": True,
                        "generated_counterpart": {"path": "plots/x.png", "step": "08-scan"},
                        "side_by_side": None}]}
    vp.check_figure_target(rep, "/nonexistent", {}, "figure_target.json", doc)
    assert "FAIL" in _levels(rep)


def test_nonprimary_unfulfilled_is_warn_only():
    vp = _load_module()
    rep = vp.Report()
    doc = {"targets": [{"figure_id": "Figure 5", "primary": False, "generated_counterpart": None}]}
    vp.check_figure_target(rep, "/nonexistent", {}, "figure_target.json", doc)
    lv = _levels(rep)
    assert "FAIL" not in lv and "WARN" in lv
