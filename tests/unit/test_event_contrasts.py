"""Complete source×arm joins and independently checked normalized contrasts."""
from copy import deepcopy
import hashlib
import json

import pytest

from ravel.physics import event_contrasts as contrasts


def fixture(*, scope="all_events", model="poissonized_independent_groups", differential=False):
    contract = {"schema_version": 1, "axes": [{"name": "x", "unit": "GeV"}],
                "bins": [{"id": "one", "low": [0.], "high": [1.]},
                         {"id": "two", "low": [1.], "high": [3.]}],
                "weight_names": ["nominal"], "input_weight_unit": "1",
                "representation": "differential" if differential else "integrated",
                "normalization": {"kind": "normalized", "scope": scope}}
    pin = {"path": "pending", "sha256": "0" * 64}
    document = {"schema_version": 1, "source": "Exact signed paired arithmetic control",
                "original_artifacts": [pin], "census": pin,
                "coupling": {"kind": "same_source_groups", "evidence": "Shared original signed subevents"},
                "quantity": contract, "arms": [{"name": name, "records": pin} for name in ("A", "B")],
                "contrasts": [{"id": "A-to-B", "baseline": {"arm": "A", "weight": "nominal"},
                               "candidate": {"arm": "B", "weight": "nominal"}}], "uncertainty_model": model}
    source = [("e1", "g1", 2, 0, 3, 1), ("e2", "g1", -1, 0, -1, 1),
              ("e3", "g2", 1, 1, 1, 0), ("e4", "g3", 1, None, 1, None)]
    census = {"schema_version": 1, "kind": "original_event_census",
              "records": [{"event_id": eid, "group_id": gid, "shard_id": "source"} for eid, gid, *_ in source]}
    arms = {"A": [], "B": []}
    for eid, gid, wa, ba, wb, bb in source:
        for arm, weight, bin_ in (("A", wa, ba), ("B", wb, bb)):
            arms[arm].append({"event_id": eid, "group_id": gid, "shard_id": "source",
                              "weights": {"nominal": weight}, "fills": [] if bin_ is None else [[.5 if bin_ == 0 else 2.]]})
    return deepcopy(document), census, arms


def test_signed_changed_weights_fills_and_denominators_match_exact_witness():
    document, census, arms = fixture()
    delivered = contrasts.calculate(document, census, arms)
    result = delivered["result"]
    comparison = result["contrasts"][0]
    assert (result["source_events"], result["derived_records"], result["independent_groups"]) == (4, 8, 3)
    assert comparison["baseline"] == pytest.approx([1/3, 1/3])
    assert comparison["candidate"] == pytest.approx([1/4, 1/2])
    assert comparison["difference"] == pytest.approx([-1/12, 1/6])
    assert comparison["baseline_candidate_covariance"][0] == pytest.approx([-1/24, 1/12])
    assert comparison["baseline_candidate_covariance"][1] == pytest.approx([1/16, -1/24])
    assert comparison["covariance"][0] == pytest.approx([733/3456, -397/1728])
    assert comparison["covariance"][1] == pytest.approx([-397/1728, 217/864])
    # Discarding this signed cross block UNDERSTATES the paired variance.
    independent = comparison["baseline_covariance"][0][0] + comparison["candidate_covariance"][0][0]
    assert independent == pytest.approx(445/3456)
    assert independent < comparison["covariance"][0][0]


def test_fixed_iid_groups_uses_three_groups_not_four_events_or_eight_arm_rows():
    doc, census, arms = fixture(model="fixed_iid_groups")
    result = contrasts.calculate(doc, census, arms)["result"]
    assert result["fixed_group_correction"] == 1.5
    assert result["contrasts"][0]["covariance"][0] == pytest.approx([733/2304, -397/1152])
    doc["uncertainty_model"] = "poissonized_independent_groups"
    poisson = contrasts.calculate(doc, census, arms)["result"]
    for a, b in zip(result["joint_covariance"], poisson["joint_covariance"]):
        assert a == pytest.approx([1.5 * x for x in b])


def test_fixed_equal_weight_denominator_has_zero_sampling_variance():
    doc, census, arms = fixture(model="fixed_iid_groups")
    for row in census["records"]: row["group_id"] = row["event_id"]
    for rows in arms.values():
        for row in rows:
            row["group_id"] = row["event_id"]
            row["weights"]["nominal"] = 1
    result = contrasts.calculate(doc, census, arms)["result"]
    denominator = result["contrasts"][0]["denominators"]["A::nominal"]
    assert denominator["raw_group_second_moment"] == 4
    assert denominator["sampling_variance"] == 0
    assert denominator["relative_standard_error"] == 0
    assert result["kernel_uncertainty_model"] == "poissonized_independent_groups"


def test_small_positive_signed_denominator_keeps_precision_unresolved():
    doc, census, arms = fixture()
    arms["A"][3]["weights"]["nominal"] = -1.999
    result = contrasts.calculate(doc, census, arms)["result"]
    denominator = result["contrasts"][0]["denominators"]["A::nominal"]
    assert denominator["sumw"] > 0
    assert denominator["relative_standard_error"] > 1
    assert denominator["precision_status"] == "poorly_determined_denominator_first_order_precision_unresolved"
    assert all(row["arms"]["A::nominal"] == "poorly_determined_denominator_first_order_precision_unresolved"
               for row in result["contrasts"][0]["precision"])


def test_arm_specific_multiweights_preserve_all_cross_stream_covariance():
    doc, census, arms = fixture()
    doc["quantity"]["weight_names"].append("up")
    for rows in arms.values():
        for row in rows: row["weights"]["up"] = 3 * row["weights"]["nominal"]
    result = contrasts.calculate(doc, census, arms)["result"]
    assert len(result["covariance_order"]) == 8
    joint = result["joint_covariance"]
    # Each proportional stream has identical normalized influence, including
    # covariance with the other arm's distinct fills and original weights.
    for i in range(2):
        assert joint[i] == pytest.approx(joint[i+2])
        assert joint[i+4] == pytest.approx(joint[i+6])


@pytest.mark.parametrize("fault", ["missing_empty", "extra", "duplicate", "group", "shard", "missing_weight", "missing_arm"])
def test_incomplete_or_mislabeled_arm_never_becomes_structural_zero(fault):
    doc, census, arms = fixture()
    if fault == "missing_empty": arms["B"].pop()
    elif fault == "extra": arms["B"].append({**deepcopy(arms["B"][0]), "event_id": "outsider"})
    elif fault == "duplicate": arms["B"].append(deepcopy(arms["B"][0]))
    elif fault == "group": arms["B"][0]["group_id"] = "renamed"
    elif fault == "shard": arms["B"][0]["shard_id"] = "other"
    elif fault == "missing_weight": arms["B"][0]["weights"] = {}
    else: del arms["B"]
    with pytest.raises(ValueError): contrasts.calculate(doc, census, arms)


def test_exposure_permutation_and_weight_stream_scaling_preserve_joint_result():
    doc, census, arms = fixture()
    original = contrasts.calculate(doc, census, arms)["result"]
    census["records"].reverse()
    for rows in arms.values(): rows.reverse()
    reversed_ = contrasts.calculate(doc, census, arms)["result"]
    assert original["contrasts"] == reversed_["contrasts"]
    for row in arms["B"]: row["weights"]["nominal"] *= 10
    scaled = contrasts.calculate(doc, census, arms)["result"]
    for a, b in zip(original["joint_covariance"], scaled["joint_covariance"]): assert a == pytest.approx(b)


def test_in_range_shape_differs_from_all_event_acceptance_and_preserves_nullspace():
    doc, census, arms = fixture(scope="in_range")
    result = contrasts.calculate(doc, census, arms)["result"]
    comparison = result["contrasts"][0]
    assert comparison["baseline"] == [.5, .5]
    assert comparison["candidate"] == pytest.approx([1/3, 2/3])
    for row in result["joint_covariance"]:
        assert sum(row[:2]) == pytest.approx(0, abs=1e-15)
        assert sum(row[2:]) == pytest.approx(0, abs=1e-15)
    assert result["normalization_meaning"] == "unit area over finite exclusive fills"


def test_density_scales_each_covariance_axis_and_exports_raw_witness_bins():
    doc, census, arms = fixture(differential=True)
    result = contrasts.calculate(doc, census, arms)
    assert result["result"]["contrasts"][0]["covariance"][0] == pytest.approx([733/3456, -397/3456])
    payload = result["witnesses"]["A-to-B"]
    assert payload["basis"]["bin_volumes"] == [1, 2]
    assert payload["records"][0]["candidate"] == {"bins": [0, 3], "denominator": 3}


def test_zero_selected_acceptance_retains_zero_central_but_no_precision_bound():
    doc, census, arms = fixture()
    for rows in arms.values():
        for row in rows: row["fills"] = []
    result = contrasts.calculate(doc, census, arms)["result"]
    assert result["contrasts"][0]["baseline"] == [0, 0]
    assert result["contrasts"][0]["covariance"] == [[0, 0], [0, 0]]
    assert all(state == "zero_selected_precision_unresolved"
               for row in result["contrasts"][0]["precision"] for state in row["arms"].values())
    doc["quantity"]["normalization"]["scope"] = "in_range"
    with pytest.raises(ValueError, match="denominator"): contrasts.calculate(doc, census, arms)


def test_single_group_fixed_covariance_and_multifill_shape_are_refused():
    doc, census, arms = fixture(model="fixed_iid_groups")
    for row in census["records"]: row["group_id"] = "same"
    for rows in arms.values():
        for row in rows: row["group_id"] = "same"
    with pytest.raises(ValueError, match="at least two"): contrasts.calculate(doc, census, arms)
    doc, census, arms = fixture()
    arms["A"][0]["fills"].append([2.])
    with pytest.raises(ValueError, match="one fill"): contrasts.calculate(doc, census, arms)


def write_study(tmp_path):
    doc, census, arms = fixture()
    def save(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    doc["census"] = save("census.json", census)
    doc["original_artifacts"] = [deepcopy(doc["census"])]
    for arm in doc["arms"]: arm["records"] = save(arm["name"] + ".json", arms[arm["name"]])
    save("input.json", doc)
    return {"input": "input.json"}


def test_bound_public_run_checks_producer_against_independent_original_rows(tmp_path):
    task = write_study(tmp_path)
    result = contrasts.run(task, tmp_path, tmp_path / "out")
    assert result["status"] == "passed"
    assert result["independent_witness_status"] == "verified"
    receipt = result["witness_receipts"]["A-to-B"]
    assert receipt["arithmetic_verified"] is True
    assert result["physics_validated"] is False
    assert (tmp_path / "out/contrast-witness-A-to-B.json").is_file()
    assert any("numerical_witness.py" in binding["path"] for binding in result["input_bindings"])


def test_independent_witness_rejects_corrupted_producer_covariance(tmp_path, monkeypatch):
    task = write_study(tmp_path)
    producer = contrasts.calculate
    def corrupted(*args):
        calculation = producer(*args)
        calculation["result"]["contrasts"][0]["covariance"][0][0] += .001
        return calculation
    monkeypatch.setattr(contrasts, "calculate", corrupted)
    result = contrasts.run(task, tmp_path, tmp_path / "out")
    assert result["status"] == "failed"
    assert result["independent_witness_status"] == "failed"
    assert result["witness_receipts"]["A-to-B"]["status"] == "mismatch"


def test_stale_original_bytes_and_symlink_inputs_fail_before_calculation(tmp_path):
    task = write_study(tmp_path)
    (tmp_path / "A.json").write_text((tmp_path / "A.json").read_text() + " ")
    with pytest.raises(ValueError, match="bytes changed"): contrasts.inputs(task, tmp_path)
    task = write_study(tmp_path)
    (tmp_path / "alias.json").symlink_to(tmp_path / "input.json")
    with pytest.raises(ValueError, match="symlink"): contrasts.inputs({"input": "alias.json"}, tmp_path)


def rectangular_bins(count):
    return [{"id": str(i), "low": [i], "high": [i+1]} for i in range(count)]


def population(count):
    return {"schema_version": 1, "kind": "original_event_census", "records": [
        {"event_id": str(i), "group_id": str(i), "shard_id": "source"} for i in range(count)]}


@pytest.mark.parametrize("fault,match", [("bins", "bins"), ("streams", "arm-weight"),
                                         ("dimensions", "raw moment"), ("comparisons", "contrast count")])
def test_oversized_contract_fails_before_pairwise_bin_validation(monkeypatch, fault, match):
    doc, _, _ = fixture()
    if fault == "bins": doc["quantity"]["bins"] = rectangular_bins(33)
    elif fault == "streams": doc["quantity"]["weight_names"] = [str(i) for i in range(9)]
    elif fault == "dimensions":
        doc["quantity"]["bins"] = rectangular_bins(31)
        doc["quantity"]["weight_names"] = ["nominal", "up"]
    else: doc["contrasts"] *= 17
    def forbidden(*args):
        pytest.fail("expensive quantity validation entered before resource refusal")
    monkeypatch.setattr(contrasts.quantities, "validate", forbidden)
    with pytest.raises(ValueError, match=match): contrasts.validate_document(doc)


def test_shape_boundary_admits_32_bins_and_128_raw_dimensions():
    doc, _, _ = fixture()
    doc["quantity"]["bins"] = rectangular_bins(32)
    assert contrasts.validate_document(doc)["quantity"]["bins"] == doc["quantity"]["bins"]
    doc["quantity"]["bins"] = rectangular_bins(30)
    doc["quantity"]["weight_names"] = ["nominal", "up"]
    assert contrasts.validate_document(doc)["quantity"]["weight_names"] == ["nominal", "up"]


def test_original_census_bound_refuses_overlimit_before_identity_join(monkeypatch):
    doc, _, arms = fixture()
    census = population(20_000)
    assert len(contrasts.validate_census(census)["records"]) == 20_000
    census["records"].append(deepcopy(census["records"][0]))
    monkeypatch.setattr(contrasts.quantities, "calculate", lambda *args: pytest.fail("moment kernel entered"))
    with pytest.raises(ValueError, match="census rows exceed"): contrasts.calculate(doc, census, arms)


@pytest.mark.parametrize("fault,match", [("witness", "bin-squared"), ("kernel", "group-product"),
                                         ("aggregate", "aggregate witness")])
def test_work_refusal_precedes_arm_expansion_and_moment_allocation(monkeypatch, fault, match):
    doc, _, _ = fixture()
    if fault == "witness":
        doc["quantity"]["bins"] = rectangular_bins(32)
        census = population(1954)
    elif fault == "kernel":
        doc["quantity"]["bins"] = rectangular_bins(1)
        doc["arms"] = [{"name": name, "records": deepcopy(doc["census"])}
                       for name in ["A", "B", *[str(i) for i in range(14)]]]
        census = population(7000)
    else:
        doc["quantity"]["bins"] = rectangular_bins(32)
        doc["contrasts"] = [{**deepcopy(doc["contrasts"][0]), "id": str(i)} for i in range(16)]
        census = population(600)
    monkeypatch.setattr(contrasts.quantities, "calculate", lambda *args: pytest.fail("moment kernel entered"))
    with pytest.raises(ValueError, match=match): contrasts.calculate(doc, census, {})


def test_raw_input_byte_refusal_precedes_json_parse(tmp_path, monkeypatch):
    path = tmp_path / "oversized.json"
    path.write_bytes(b" " * (contrasts.resource_limits()["artifact_bytes"] + 1))
    monkeypatch.setattr(contrasts, "_json", lambda *args: pytest.fail("oversized JSON parsed"))
    with pytest.raises(ValueError, match="artifact byte limit"):
        contrasts.inputs({"input": path.name}, tmp_path)


def test_oversized_generated_witness_refused_before_kernel(monkeypatch):
    doc, census, arms = fixture(differential=True)
    # Document and canonical census fit separately, while the output witness
    # containing both the unit and original identities exceeds its byte cap.
    doc["quantity"]["axes"][0]["unit"] = "u" * 2_000_000
    for i, original in enumerate(census["records"]):
        ident = str(i) + "e" * 600_000
        original["event_id"] = ident
        for rows in arms.values(): rows[i]["event_id"] = ident
    monkeypatch.setattr(contrasts.quantities, "calculate", lambda *args: pytest.fail("moment kernel entered"))
    with pytest.raises(ValueError, match="paired original-row witness exceeds"):
        contrasts.calculate(doc, census, arms)
