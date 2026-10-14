"""Grounded diagnostic selection keeps blockers and full-scope rival identities."""
from copy import deepcopy
import hashlib

import pytest

from ravel.workflow import experiment_allocator
from ravel.workflow import research_transfer as transfer


def setup(tmp_path):
    raw = b"frozen diagnostic prerequisite\n"
    (tmp_path / "input.txt").write_bytes(raw)
    pin = {"path": "input.txt", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    case = {"schema_version": 1, "scope": "bounded diagnostic", "prediction_basis": "hypothetical",
            "budget": 2, "horizon": 1,
            "actions": [{"id": "native", "cost": 1, "outcomes": ["a", "b", "c", "d"], "nominal_change": 0},
                        {"id": "witness", "cost": 1, "outcomes": ["x", "y"], "nominal_change": 0}],
            "hypotheses": [{"id": f"h{i}", "predictions": {"native": n, "witness": w},
                            "provenance": ["frozen finite declarations"], "reopening_trigger": "new input"}
                           for i, (n, w) in enumerate(zip("abcd", "xxyy"))]}
    affordances = {"schema_version": 1, "scope": case["scope"],
                   "prerequisites": [{"id": "worker", "state": "unavailable", "evidence": [],
                                      "note": "native worker unqualified"},
                                     {"id": "rows", "state": "available", "evidence": [pin],
                                      "note": "retained source-matched rows"}],
                   "actions": [{"id": "native", "alternatives": [["worker"]]},
                               {"id": "witness", "alternatives": [["rows"]]}]}
    return case, affordances


def test_actual_affordance_masks_blocked_action_without_merging_full_scope_rivals(tmp_path):
    case, affordances = setup(tmp_path)
    before = deepcopy((case, affordances))
    result = transfer.recommend(case, affordances, base_dir=tmp_path)
    assert result["unmasked_policy"]["first_action"] == "native"
    assert result["policy"]["first_action"] == "witness"
    assert result["policy"]["guaranteed_eliminated_classes"] == 2
    assert result["unique_class_count"] == 4
    assert result["affordance_assessment"]["actions"][0]["alternative_blocker_sets"] == [["worker"]]
    assert result["execution_authorized"] is result["physics_validated"] is False
    assert result["dependency_closure_complete"] is False
    assert (case, affordances) == before


@pytest.mark.parametrize("horizon", [1, 2])
def test_all_available_exactly_reuses_existing_policy(horizon, tmp_path):
    case, affordances = setup(tmp_path)
    case["horizon"] = horizon
    affordances["prerequisites"][0].update(state="available", evidence=deepcopy(affordances["prerequisites"][1]["evidence"]))
    result = transfer.recommend(case, affordances, base_dir=tmp_path)
    assert result["policy"] == experiment_allocator.recommend(case)["policy"]


def test_unknown_and_drift_remain_blockers_and_zero_feasible_actions_abstains(tmp_path):
    case, affordances = setup(tmp_path)
    affordances["prerequisites"][0]["state"] = "unknown"
    (tmp_path / "input.txt").write_text("changed rows")
    result = transfer.recommend(case, affordances, base_dir=tmp_path)
    assert result["policy"] is None
    states = {row["id"]: row["observed_state"] for row in result["affordance_assessment"]["prerequisites"]}
    assert states == {"worker": "unknown", "rows": "stale"}


def test_declared_alternative_route_is_used_and_failed_options_preserved(tmp_path):
    case, affordances = setup(tmp_path)
    affordances["actions"][0]["alternatives"].append(["rows"])
    result = transfer.recommend(case, affordances, base_dir=tmp_path)
    assert result["policy"]["first_action"] == "native"
    assert result["affordance_assessment"]["actions"][0]["alternative_blocker_sets"] == [["worker"], []]


def test_present_files_do_not_override_unavailable_disposition(tmp_path):
    case, affordances = setup(tmp_path)
    affordances["prerequisites"][0]["evidence"] = deepcopy(affordances["prerequisites"][1]["evidence"])
    result = transfer.recommend(case, affordances, base_dir=tmp_path)
    assert result["policy"]["first_action"] == "witness"


@pytest.mark.parametrize("mutation", ["no_pins", "unknown_key", "duplicate", "scope", "traversal", "empty_route", "bool_size"])
def test_ambiguous_unbounded_or_unpinned_requirements_refuse(mutation, tmp_path):
    case, affordances = setup(tmp_path)
    pin = affordances["prerequisites"][1]["evidence"][0]
    if mutation == "no_pins": affordances["prerequisites"][1]["evidence"] = []
    if mutation == "unknown_key": affordances["actions"][1]["alternatives"] = [["invented"]]
    if mutation == "duplicate": affordances["prerequisites"].append(deepcopy(affordances["prerequisites"][0]))
    if mutation == "scope": affordances["scope"] = "different scientific subject"
    if mutation == "traversal": pin["path"] = "../input.txt"
    if mutation == "empty_route": affordances["actions"][0]["alternatives"] = [[]]
    if mutation == "bool_size": pin["size"] = True
    with pytest.raises(ValueError):
        transfer.recommend(case, affordances, base_dir=tmp_path)


def test_symlink_escape_refused_before_read(tmp_path):
    case, affordances = setup(tmp_path)
    outside = tmp_path.parent / "outside-proof.txt"
    outside.write_text("outside")
    (tmp_path / "input.txt").unlink()
    (tmp_path / "input.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        transfer.recommend(case, affordances, base_dir=tmp_path)


def test_missing_asset_reports_stale_instead_of_bypassing_mask(tmp_path):
    case, affordances = setup(tmp_path)
    (tmp_path / "input.txt").unlink()
    result = transfer.recommend(case, affordances, base_dir=tmp_path)
    assert result["policy"] is None
    assert result["affordance_assessment"]["prerequisites"][0]["observed_state"] == "stale"
