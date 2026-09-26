"""Independent arithmetic controls for weighted scientific quantity transport."""
from copy import deepcopy

import pytest

from ravel.physics.quantities import calculate, merge, validate


def contract(**updates):
    result = {"schema_version": 1, "axes": [{"name": "pt", "unit": "GeV"}],
              "bins": [{"id": "low", "low": [0.], "high": [1.]},
                       {"id": "high", "low": [1.], "high": [3.]}],
              "weight_names": ["nominal"], "input_weight_unit": "pb",
              "representation": "integrated", "normalization": {"kind": "absolute", "scale": 1., "unit": "pb"}}
    result.update(updates)
    return result


def event(id_, fills, weight=1., *, group=None, shard="sample-a", weights=None):
    return {"event_id": str(id_), "group_id": str(id_ if group is None else group), "shard_id": shard,
            "weights": {"nominal": weight} if weights is None else weights, "fills": fills}


def test_unequal_width_density_scales_both_axes_of_covariance():
    events = [event("a", [[.5], [2]], 2), event("b", [[2]], -1)]
    integrated = calculate(contract(), events)
    density = calculate(contract(representation="differential"), events)
    assert integrated["values"]["nominal"] == [2, 1]
    assert integrated["covariance"] == [[4, 4], [4, 5]]
    assert density["values"]["nominal"] == [2, .5]
    assert density["covariance"] == [[4, 2], [2, 1.25]]
    assert density["unit"] == "pb/(GeV)"
    assert density["state"]["negative_weight_records"] == {"nominal": 1}


def test_correlated_signed_subevents_cancel_before_squaring():
    grouped = [event("a", [[.5]], 2, group="shared"), event("b", [[.5]], -1, group="shared")]
    assert calculate(contract(), grouped)["covariance"][0][0] == 1
    grouped[1]["group_id"] = "independent"
    assert calculate(contract(), grouped)["covariance"][0][0] == 5


def test_negative_cross_bin_covariance_from_correlated_subevents():
    rows = [event("a", [[.5]], 2, group="g"), event("b", [[2]], -1, group="g")]
    assert calculate(contract(), rows)["covariance"] == [[4, -2], [-2, 1]]


def test_multiple_weights_preserve_joint_covariance():
    c = contract(weight_names=["nominal", "up"])
    rows = [event("a", [[.5]], weights={"nominal": 2, "up": -3}),
            event("b", [[2]], weights={"nominal": 1, "up": 4})]
    result = calculate(c, rows)
    assert result["values"] == {"nominal": [2, 1], "up": [-3, 4]}
    assert result["covariance"][0][2] == -6
    assert result["covariance"][1][3] == 4
    assert result["covariance_order"][2] == {"weight": "up", "bin_id": "low"}


def test_normalization_includes_denominator_variance_and_cross_terms():
    c = contract(normalization={"kind": "normalized", "scope": "in_range"})
    rows = [event("a", [[.5]]), event("b", [[2]]), event("c", [[2]])]
    result = calculate(c, rows)
    assert result["values"]["nominal"] == pytest.approx([1/3, 2/3])
    assert result["covariance"][0] == pytest.approx([2/27, -2/27])
    assert result["covariance"][1] == pytest.approx([-2/27, 2/27])
    assert result["denominators"]["nominal"]["sumw"] == 3
    assert sum(sum(row) for row in result["covariance"]) == pytest.approx(0, abs=1e-15)


def test_normalized_joint_weight_covariance_is_invariant_to_weight_stream_scale():
    c = contract(weight_names=["nominal", "up"], normalization={"kind": "normalized", "scope": "in_range"})
    rows = [event("a", [[.5]], weights={"nominal": 1, "up": 2}),
            event("b", [[2]], weights={"nominal": 2, "up": 1})]
    original = calculate(c, rows)
    assert original["covariance"][0][2] == pytest.approx(8/81)
    for row in rows:
        row["weights"]["up"] *= 10
    scaled = calculate(c, rows)
    assert original["values"] == scaled["values"]
    for left, right in zip(original["covariance"], scaled["covariance"]):
        assert left == pytest.approx(right)


def test_all_events_denominator_retains_empty_and_flow_records():
    c = contract(normalization={"kind": "normalized", "scope": "all_events"})
    rows = [event("a", [[.5]]), event("b", []), event("c", [[4]])]
    result = calculate(c, rows)
    assert result["values"]["nominal"] == pytest.approx([1/3, 0])
    assert result["covariance"][0][0] == pytest.approx(2/27)
    assert result["flow"]["nominal"]["sumw"] == 1
    assert result["flow"]["nominal"]["unit"] == "pb"
    assert result["state"]["counts"] == {"records": 3, "fills": 2, "in_range": 1, "flow": 1, "empty_records": 1}


def test_normalized_differential_area_and_constraint_covariance():
    result = calculate(contract(representation="differential", normalization={"kind": "normalized", "scope": "in_range"}),
                       [event("a", [[.5]]), event("b", [[2]])])
    assert result["values"]["nominal"] == [.5, .25]
    assert result["unit"] == "1/(GeV)"
    assert result["covariance"][0] == pytest.approx([.125, -.0625])
    assert result["covariance"][1] == pytest.approx([-.0625, .03125])


def test_nd_bin_hypervolume_and_half_open_boundaries():
    c = contract(axes=[{"name": "x", "unit": "GeV"}, {"name": "eta", "unit": "1"}],
                 bins=[{"id": "rectangle", "low": [0, -1], "high": [2, 2]}], representation="differential")
    result = calculate(c, [event("a", [[0, -1], [2, 0], [1, 2], [1, 1]])])
    assert result["bin_volumes"] == [6]
    assert result["values"]["nominal"] == [2/6]
    assert result["flow"]["nominal"]["sumw"] == 2
    assert result["covariance"][0][0] == pytest.approx((2/6)**2)


def test_irregular_gap_is_explicit_flow():
    c = contract()
    c["bins"][1]["low"] = [2]
    result = calculate(c, [event("a", [[1.5]])])
    assert result["state"]["counts"]["flow"] == 1
    assert result["values"]["nominal"] == [0, 0]


def test_merge_is_identical_to_monolithic_even_with_unequal_exposure():
    c = contract(representation="differential", normalization={"kind": "normalized", "scope": "all_events"})
    a = [event("a", [[.5]], 2), event("b", [], -1)]
    b = [event("c", [[2]], 3, shard="sample-b")]
    direct = calculate(c, a+b)
    merged = merge([calculate(c, a), calculate(c, b)])
    assert merged == direct
    assert merged["values"]["nominal"] == [.5, .375]


def test_signed_shards_can_finalize_only_after_merge():
    c = contract(normalization={"kind": "normalized", "scope": "all_events"})
    negative = [event("a", [[.5]], -1)]
    positive = [event("b", [[2]], 3, shard="sample-b")]
    with pytest.raises(ValueError, match="denominator"):
        calculate(c, negative)
    result = merge([calculate(c, negative, finalize=False), calculate(c, positive, finalize=False)])
    assert result == calculate(c, negative+positive)
    assert result["values"]["nominal"] == [-.5, 1.5]


@pytest.mark.parametrize("identity", ["event_id", "group_id", "shard_id"])
def test_merging_any_shared_identity_fails(identity):
    a = event("a", [[.5]], shard="shard-a")
    b = event("b", [[2]], shard="shard-b")
    b[identity] = a[identity]
    with pytest.raises(ValueError, match="overlapping"):
        merge([calculate(contract(), [a]), calculate(contract(), [b])])


def test_changed_scale_and_changed_state_cannot_be_merged():
    a = calculate(contract(), [event("a", [[.5]])])
    b = calculate(contract(normalization={"kind": "absolute", "scale": 2, "unit": "pb"}), [event("b", [[2]], shard="b")])
    with pytest.raises(ValueError, match="contracts differ"):
        merge([a, b])
    mutated = deepcopy(a)
    mutated["state"]["sumw"][0] = 2
    with pytest.raises(ValueError, match="state has changed"):
        merge([mutated])


@pytest.mark.parametrize("mutate,match", [
    (lambda c: c.update(schema_version=True), "schema_version"),
    (lambda c: c.update(unknown=1), "unknown"),
    (lambda c: c["bins"][1].update(low=[.5]), "overlapping"),
    (lambda c: c["bins"][0].update(high=[0]), "positive width"),
    (lambda c: c["bins"][0].update(high=[float("inf")]), "finite"),
    (lambda c: c["bins"][1].update(id="low"), "unique"),
    (lambda c: c["axes"][0].update(unit=""), "unit"),
    (lambda c: c["normalization"].update(scale=True), "boolean"),
    (lambda c: c.update(weight_names=["nominal", "nominal"]), "unique"),
])
def test_contract_adversaries(mutate, match):
    c = contract()
    mutate(c)
    with pytest.raises(ValueError, match=match):
        validate(c)


@pytest.mark.parametrize("mutate,match", [
    (lambda r: r[1].update(event_id="a"), "duplicate event"),
    (lambda r: r[1].update(group_id="a", shard_id="b"), "split"),
    (lambda r: r[0].update(fills=[[float("nan")]]), "finite"),
    (lambda r: r[0].update(fills=[[1, 2]]), "dimensionality"),
    (lambda r: r[0]["weights"].update(nominal=True), "boolean"),
    (lambda r: r[0]["weights"].update(extra=1), "weights"),
    (lambda r: r[0].update(group_id=""), "string"),
])
def test_event_adversaries(mutate, match):
    rows = [event("a", [[.5]]), event("b", [[2]])]
    mutate(rows)
    with pytest.raises(ValueError, match=match):
        calculate(contract(), rows)


def test_zero_normalization_and_overflow_are_retained_as_errors():
    rows = [event("a", [[.5]], 1), event("b", [[2]], -1)]
    with pytest.raises(ValueError, match="denominator"):
        calculate(contract(normalization={"kind": "normalized", "scope": "in_range"}), rows)
    with pytest.raises(ValueError, match="finite"):
        calculate(contract(), [event("big", [[.5]], 1e200)])
    with pytest.raises(ValueError, match="finite"):
        calculate(contract(), [event("integer-overflow", [[.5]], 10**1000)])
    with pytest.raises(ValueError, match="at least one"):
        calculate(contract(), [])


def test_compensated_sum_preserves_small_weight_between_large_cancellations():
    rows = [event("a", [[.5]], 1e16, group="g"), event("b", [[.5]], 1, group="g"), event("c", [[.5]], -1e16, group="g")]
    result = calculate(contract(), rows)
    assert result["values"]["nominal"][0] == 1
    assert result["covariance"][0][0] == 1
