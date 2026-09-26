"""Supplied-measurement inference, unit/covariance gates and real Spey roots."""
import json
from copy import deepcopy

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from ravel.physics.measurement import inputs, prepare, run, validate


def document():
    ids = ["a", "b"]
    def vector(values):
        return {"values": values, "bin_ids": ids[:], "unit": "pb"}
    return {"schema_version": 1, "analysis_id": "synthetic-gaussian-control",
            "quantity": {"axes": [{"name": "mass", "unit": "GeV"}],
                         "bins": [{"id": "a", "low": [0], "high": [1]}, {"id": "b", "low": [1], "high": [3]}],
                         "representation": "integrated", "normalization": "absolute", "unit": "pb"},
            "data": vector([11, 19]), "sm": vector([10, 20]), "signal": vector([2, 1]),
            "experimental_covariance": {"bin_ids": ids[:], "matrix": [[4, 1], [1, 9]], "unit": "(pb)^2"},
            "covariance_policy": "experimental_only", "overlap": {"policy": "single_measurement"}, "constraints": []}


def task(**updates):
    spec = {"schema_version": 1, "input": "input.json", "inference": "goodness_of_fit", "signal_strength": 1.}
    spec.update(updates)
    return spec


def execute(tmp_path, model=None, spec=None, name="output"):
    (tmp_path / "input.json").write_text(json.dumps(document() if model is None else model))
    return run(task() if spec is None else spec, tmp_path, tmp_path / name)


def normalized_document():
    result = document()
    result["quantity"].update(normalization="normalized", representation="differential", unit="1/(GeV)")
    for key, values in (("data", [.4, .3]), ("sm", [.5, .25]), ("signal", [.1, -.05])):
        result[key].update(unit="1/(GeV)", values=values)
    result["experimental_covariance"].update(unit="(1/(GeV))^2", matrix=[[.01, -.005], [-.005, .0025]])
    result["constraints"] = [{"coefficients": [1, 2], "value": 1}]
    return result


def test_gof_is_actual_correlated_gaussian_arithmetic_and_not_exclusion(tmp_path):
    result = execute(tmp_path)
    assert result["goodness_of_fit"]["sm"]["chi2"] == pytest.approx(15/35)
    assert result["goodness_of_fit"]["tested_model"]["chi2"] == pytest.approx(21/35)
    assert result["goodness_of_fit"]["sm"]["degrees_of_freedom"] == 2
    assert result["inference"] is None
    assert result["physics_validated"] is False
    assert result["unit"] == "pb"
    assert json.loads((tmp_path / "output/measurement.json").read_text()) == result
    assert len(result["input"]["sha256"]) == 64
    with pytest.raises(FileExistsError):
        run(task(), tmp_path, tmp_path / "output")


def test_explicit_bin_labels_allow_safe_reordering_for_each_input():
    model = document()
    expected = prepare(model)
    for key in ("data", "sm", "signal"):
        model[key]["bin_ids"].reverse()
        model[key]["values"].reverse()
    model["experimental_covariance"]["bin_ids"].reverse()
    model["experimental_covariance"]["matrix"] = [[9, 1], [1, 4]]
    actual = prepare(model)
    for key in ("data", "sm", "signal", "covariance"):
        assert np.array_equal(expected[key], actual[key])


def test_units_are_not_countified_or_luminosity_multiplied(tmp_path):
    result = execute(tmp_path)
    converted = document()
    converted["quantity"]["unit"] = "fb"
    for key in ("data", "sm", "signal"):
        converted[key]["values"] = [value * 1000 for value in converted[key]["values"]]
        converted[key]["unit"] = "fb"
    converted["experimental_covariance"].update(unit="(fb)^2", matrix=[[4e6, 1e6], [1e6, 9e6]])
    other = execute(tmp_path, converted, name="converted")
    for key in ("sm", "tested_model"):
        assert result["goodness_of_fit"][key] == pytest.approx(other["goodness_of_fit"][key])
    assert result["fit"]["unconstrained_signal_strength"] == pytest.approx(other["fit"]["unconstrained_signal_strength"])


def test_normalized_singular_covariance_uses_declared_constraint(tmp_path):
    result = execute(tmp_path, normalized_document())
    assert result["goodness_of_fit"]["sm"]["degrees_of_freedom"] == 1
    assert result["goodness_of_fit"]["sm"]["chi2"] == pytest.approx(1)
    assert result["goodness_of_fit"]["tested_model"]["chi2"] == pytest.approx(4)
    assert result["fit"]["unconstrained_signal_strength"] == pytest.approx(-1)
    projection = np.array(result["constraint_projection"])
    assert projection.shape == (1, 2)
    assert projection @ [1, 2] == pytest.approx([0], abs=1e-12)


def test_absolute_model_can_declare_other_exact_constraints():
    model = normalized_document()
    model["quantity"]["normalization"] = "absolute"
    result = prepare(model)
    assert result["degrees_of_freedom"] == 1


def test_independent_theory_covariance_requires_explicit_policy(tmp_path):
    model = document()
    model["theory_covariance"] = {"bin_ids": ["a", "b"], "unit": "(pb)^2", "matrix": [[1, .2], [.2, 4]]}
    with pytest.raises(ValueError, match="excluded"):
        prepare(model)
    model["covariance_policy"] = "independent_theory_sum"
    result = prepare(model)
    assert np.allclose(result["covariance"], [[5, 1.2], [1.2, 13]])
    assert execute(tmp_path, model)["covariance_policy"] == "independent_theory_sum"


def test_overlap_independence_is_not_inferred_from_histogram_names():
    model = document()
    model["overlap"] = {"policy": "independent_measurements", "bin_groups": ["A", "B"], "evidence": "Synthetic independent construction"}
    with pytest.raises(ValueError, match="independence"):
        prepare(model)
    model["experimental_covariance"]["matrix"] = [[4, 0], [0, 9]]
    prepare(model)
    model["overlap"] = {"policy": "joint_covariance", "evidence": "Supplied joint construction"}
    model["experimental_covariance"]["matrix"] = [[4, 1], [1, 9]]
    prepare(model)


@pytest.mark.parametrize("mutate,match", [
    (lambda m: m.update(schema_version=True), "schema_version"),
    (lambda m: m.update(unknown=1), "unknown"),
    (lambda m: m["data"].update(unit="events"), "unit"),
    (lambda m: m["data"].update(bin_ids=["a", "a"]), "unique"),
    (lambda m: m["signal"].update(bin_ids=["a", "other"]), "identity"),
    (lambda m: m["signal"].update(values=[True, 1]), "boolean"),
    (lambda m: m["experimental_covariance"].update(unit="pb"), "squared unit"),
    (lambda m: m["experimental_covariance"].update(matrix=[[4, 1], [2, 9]]), "asymmetric"),
    (lambda m: m["experimental_covariance"].update(matrix=[[4, 10], [10, 9]]), "positive semidefinite"),
    (lambda m: m["experimental_covariance"].update(matrix=[[1, 1], [1, 1]]), "null direction"),
    (lambda m: m["experimental_covariance"].update(matrix=[[1, 0], [0, 1e-16]]), "ill-conditioned"),
    (lambda m: m["experimental_covariance"].update(matrix=[[1, 0], [0, float("nan")]]), "finite"),
    (lambda m: m.update(covariance_policy="diagonal_fallback"), "covariance_policy"),
    (lambda m: m.update(covariance_policy="independent_theory_sum"), "requires supplied"),
    (lambda m: m.update(overlap={"policy": "assume_none"}), "overlap"),
    (lambda m: m.update(overlap={"policy": "joint_covariance", "evidence": ""}), "evidence"),
])
def test_measurement_adversaries(mutate, match):
    model = document()
    mutate(model)
    with pytest.raises(ValueError, match=match):
        prepare(model)


@pytest.mark.parametrize("mutate,match", [
    (lambda m: m.update(constraints=[]), "unit-area"),
    (lambda m: m["data"].update(values=[.4, .4]), "violates"),
    (lambda m: m["signal"].update(values=[.1, .05]), "deformation"),
    (lambda m: m["experimental_covariance"].update(matrix=[[.01, 0], [0, .0025]]), "preserve"),
    (lambda m: m["constraints"].append(deepcopy(m["constraints"][0])), "independent"),
    (lambda m: m["quantity"].update(unit="pb"), "normalized quantity unit"),
])
def test_normalized_adversaries(mutate, match):
    model = normalized_document()
    mutate(model)
    with pytest.raises(ValueError, match=match):
        prepare(model)


def test_zero_signal_is_gof_only(tmp_path):
    model = document()
    model["signal"]["values"] = [0, 0]
    result = execute(tmp_path, model)
    assert result["fit"] is None
    assert result["goodness_of_fit"]["sm"] == result["goodness_of_fit"]["tested_model"]


def test_json_duplicates_and_symlink_inputs_are_rejected(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match="duplicate"):
        run(task(), tmp_path, tmp_path / "output")
    path.unlink()
    other = tmp_path / "other.json"
    other.write_text(json.dumps(document()))
    path.symlink_to(other)
    with pytest.raises(ValueError, match="nonsymlink"):
        inputs(task(), tmp_path)


def test_task_validation_is_detached_and_does_not_read_inputs():
    spec = task(input="file-that-does-not-exist.json")
    copy = validate(spec)
    assert copy == spec and copy is not spec
    with pytest.raises(ValueError, match="poi_max"):
        validate(task(inference="spey_cls"))
    with pytest.raises(ValueError, match="only defined"):
        validate(task(poi_max=100))
    with pytest.raises(ValueError, match="nonnegative"):
        validate(task(signal_strength=-1))


@pytest.mark.parametrize("shift", [-2., 0., 2.])
def test_real_spey_six_roots_against_independent_gaussian_formula(tmp_path, shift):
    spey = pytest.importorskip("spey")
    if spey.version() != "0.2.6":
        pytest.skip("adapter is pinned to Spey 0.2.6")
    model = document()
    model["data"]["values"] = [10+2*shift, 20+shift]
    result = execute(tmp_path, model, task(inference="spey_cls", poi_max=20))
    inference = result["inference"]
    curves = [inference["limits"]["observed"], *inference["limits"]["expected"]]
    assert all(curve["status"] == "resolved" for curve in curves)
    assert result["status"] == "passed"
    assert all(abs(check["cls"] - .05) < 5e-5 for check in inference["numerical_evidence"])
    assert all(abs(check["independent_gaussian_cls"] - .05) < 5e-5 for check in inference["numerical_evidence"])
    sigma = result["fit"]["standard_error"]
    assert inference["limits"]["expected"][2]["value"] == pytest.approx(1.959963984540054*sigma, rel=1e-5)
    assert inference["limits"]["observed"]["value"] > max(shift, 0)


def test_real_spey_normalized_signed_shape_and_finite_cap(tmp_path):
    spey = pytest.importorskip("spey")
    if spey.version() != "0.2.6":
        pytest.skip("adapter is pinned to Spey 0.2.6")
    result = execute(tmp_path, normalized_document(), task(inference="spey_cls", poi_max=10))
    assert result["inference"]["limits"]["expected"][2]["value"] == pytest.approx(1.959963984540054, rel=1e-5)
    bounded = execute(tmp_path, document(), task(inference="spey_cls", poi_max=.01), name="bounded")
    observed = bounded["inference"]["limits"]["observed"]
    assert observed == {"value": .01, "status": "above_scan", "bracket": [.01, None]}
    assert bounded["inference"]["excluded_at_test_strength"] is None
    assert bounded["status"] == "failed"


def test_spey_zero_signal_cannot_be_reported_as_a_limit(tmp_path):
    spey = pytest.importorskip("spey")
    if spey.version() != "0.2.6":
        pytest.skip("adapter is pinned to Spey 0.2.6")
    model = document()
    model["signal"]["values"] = [0, 0]
    with pytest.raises(ValueError, match="no finite sensitivity"):
        execute(tmp_path, model, task(inference="spey_cls", poi_max=10))
    assert not (tmp_path / "output/measurement.json").exists()
