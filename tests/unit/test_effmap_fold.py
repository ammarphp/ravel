"""Signed generator weights and explicit unknown map-response coverage."""
import json

import pytest

from ravel.physics.effmap_fold import run_fold


def fold(tmp_path, events, *, sparse=False, quiet=True):
    bins = [{"low": 0, "high": 1}]
    if sparse:
        bins.append({"low": 2, "high": 3})
    (tmp_path / "map.json").write_text(json.dumps({
        "independent_variables": [{"header": {"name": "x"}, "values": bins}],
        "dependent_variables": [{"header": {"name": "eff"},
                                 "values": [{"value": 1}] * len(bins)}],
    }))
    path = tmp_path / "events.json"
    path.write_text(json.dumps(events))
    spec = {"maps": {"m": {"file": "map.json"}},
            "objects": {"probe": {"map": "m", "axes": ["x"]}}}
    result = run_fold(str(path), spec, str(tmp_path), 1, 1,
                      str(tmp_path / "out"), quiet=quiet)
    persisted = json.loads((tmp_path / "out/fold_result.json").read_text())
    assert persisted == result
    return result


def event(weight, x, **extra):
    return {"weight": weight, "objects": [{"kind": "probe", "x": x}], **extra}


def test_signed_omission_can_raise_mean_above_complete_response(tmp_path, capsys):
    result = fold(tmp_path, [event(2, .5), event(-1, 4)], quiet=False)
    # Independent completion: unit response on BOTH events gives (2-1)/(2-1)=1.
    complete_mean = (2 * 1 + (-1) * 1) / (2 - 1)
    assert result["mean_fold_weight"] == 2 > complete_mean
    assert result["expected_yield"] == 2000
    assert "conservative under-coverage" not in result["envelope_policy"].lower()
    d = result["map_coverage"]
    assert d["status"] == "partial"
    assert d["omitted_sum_gen_weights"] == -1
    assert d["omitted_sum_abs_gen_weights"] == 1
    assert d["omitted_sum_positive_gen_weights"] == 0
    assert d["omitted_sum_negative_gen_weights"] == -1
    assert d["omitted_n_negative_gen_weights"] == 1
    assert d["n_negative_gen_weights"] == 1
    assert d["omitted_weighted_response_sum"] is None
    assert "conservative under-coverage" not in result["envelope_policy"].lower()
    out = capsys.readouterr().out
    assert "response contribution is UNKNOWN" in out
    assert "conservative UNDER-coverage" not in out
    rows = [json.loads(line) for line in open(result["weights_file"])]
    assert [r["fold_weight"] for r in rows] == [1, 0]
    assert [r["gen_weight"] for r in rows] == [2, -1]
    assert [r["envelope_ok"] for r in rows] == [True, False]


def test_positive_omission_preserves_full_denominator_and_is_unknown(tmp_path):
    result = fold(tmp_path, [event(2, .5), event(1, 4)])
    assert result["sum_gen_weights"] == 3
    assert result["mean_fold_weight"] == pytest.approx(2 / 3)
    assert result["expected_yield"] == pytest.approx(2000 / 3)
    d = result["map_coverage"]
    assert d["omitted_sum_gen_weights"] == 1
    assert d["omitted_sum_abs_gen_weights"] == 1
    assert d["omitted_sum_positive_gen_weights"] == 1
    assert d["omitted_sum_negative_gen_weights"] == 0
    assert d["omitted_n_negative_gen_weights"] == 0
    assert d["omitted_weighted_response_sum"] is None


def test_cancelling_omitted_weights_do_not_hide_unknown_response(tmp_path):
    result = fold(tmp_path, [event(2, .5), event(1, 4), event(-1, 4)])
    d = result["map_coverage"]
    assert d["status"] == "partial"
    assert d["n_events_omitted"] == 2
    assert d["omitted_sum_gen_weights"] == 0
    assert d["omitted_sum_abs_gen_weights"] == 2
    assert d["omitted_sum_positive_gen_weights"] == 1
    assert d["omitted_sum_negative_gen_weights"] == -1
    assert d["omitted_weighted_response_sum"] is None
    # Equal signed sums do not imply equal unknown efficiencies: eps=(1,0)
    # on the omitted (+1,-1) pair adds 1 to the weighted response numerator.
    assert result["mean_fold_weight"] == 1 < (2 + 1 * 1 - 1 * 0) / 2


def test_multiple_failed_objects_count_omitted_generator_weight_once(tmp_path):
    missing = event(-1, 4)
    missing["objects"].append({"kind": "probe", "x": -1})
    result = fold(tmp_path, [event(2, .5), missing])
    assert result["counts"]["n_objects_out_of_envelope"] == 2
    assert result["counts"]["n_events_envelope_excluded"] == 1
    assert result["map_coverage"]["omitted_sum_gen_weights"] == -1
    assert result["map_coverage"]["omitted_sum_abs_gen_weights"] == 1


def test_sparse_hole_is_partial_response_domain(tmp_path):
    result = fold(tmp_path, [event(2, .5), event(-1, 1.5)], sparse=True)
    assert result["counts"]["out_of_envelope_reasons"] == {"m:in-range-hole": 1}
    assert result["map_coverage"]["status"] == "partial"
    assert result["map_coverage"]["omitted_sum_gen_weights"] == -1
    assert result["map_coverage"]["omitted_weighted_response_sum"] is None


def test_unselected_outside_event_is_not_an_unknown_omission(tmp_path):
    result = fold(tmp_path, [event(2, .5), event(-1, 4, selected=False)])
    assert result["mean_fold_weight"] == 2
    assert result["counts"]["n_events_selected_false"] == 1
    assert result["counts"]["n_events_envelope_excluded"] == 0
    d = result["map_coverage"]
    assert d["status"] == "no_unmapped_selected_objects"
    assert d["n_events_omitted"] == 0
    assert d["omitted_weighted_response_sum"] == 0
    assert d["n_negative_gen_weights"] == 1


def test_complete_signed_map_coverage_is_scoped_not_validated(tmp_path):
    result = fold(tmp_path, [event(2, .5), event(-1, .5)])
    assert result["mean_fold_weight"] == 1
    d = result["map_coverage"]
    assert d["status"] == "no_unmapped_selected_objects"
    assert d["scope"] == "selected events and object kinds specified in the fold spec"
    assert d["omitted_sum_gen_weights"] == 0
    assert d["omitted_sum_abs_gen_weights"] == 0
    assert d["omitted_weighted_response_sum"] == 0
    assert "NOT satisfied" in result["r5_gate"]


def test_zero_weight_unmapped_event_retains_domain_gap(tmp_path):
    result = fold(tmp_path, [event(2, .5), event(0, 4)])
    assert result["mean_fold_weight"] == 1
    d = result["map_coverage"]
    assert d["status"] == "partial"
    assert d["n_events_omitted"] == 1
    assert d["omitted_sum_abs_gen_weights"] == 0
    # The weighted contribution is known zero, while the response domain is still partial.
    assert d["omitted_weighted_response_sum"] == 0


def test_known_zero_mapped_factor_fixes_contribution_despite_domain_gap(tmp_path):
    events = [event(2, .5), event(-1, 4)]
    events[1]["objects"].append({"kind": "probe", "x": .5})
    result = fold(tmp_path, events)
    # Change only the map efficiency to zero and use the same event/spec inputs.
    map_path = tmp_path / "map.json"
    doc = json.loads(map_path.read_text())
    doc["dependent_variables"][0]["values"][0]["value"] = 0
    map_path.write_text(json.dumps(doc))
    spec = {"maps": {"m": {"file": "map.json"}},
            "objects": {"probe": {"map": "m", "axes": ["x"]}}}
    result = run_fold(str(tmp_path / "events.json"), spec, str(tmp_path), 1, 1,
                      str(tmp_path / "out-zero"), quiet=True)
    assert result["map_coverage"]["status"] == "partial"
    assert result["map_coverage"]["omitted_sum_gen_weights"] == -1
    assert result["map_coverage"]["omitted_weighted_response_sum"] == 0
    assert result["mean_fold_weight"] == 0


def test_product_underflow_does_not_claim_known_zero_response(tmp_path):
    events = [event(2, .5), event(-1, 4)]
    events[1]["objects"] += [{"kind": "probe", "x": .5}] * 2
    fold(tmp_path, events)
    map_path = tmp_path / "map.json"
    doc = json.loads(map_path.read_text())
    doc["dependent_variables"][0]["values"][0]["value"] = 1e-200
    map_path.write_text(json.dumps(doc))
    spec = {"maps": {"m": {"file": "map.json"}},
            "objects": {"probe": {"map": "m", "axes": ["x"]}}}
    result = run_fold(str(tmp_path / "events.json"), spec, str(tmp_path), 1, 1,
                      str(tmp_path / "out-tiny"), quiet=True)
    assert result["map_coverage"]["status"] == "partial"
    assert result["map_coverage"]["omitted_weighted_response_sum"] is None
