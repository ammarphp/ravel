"""Fictional measurement bundles and correlated coupling inference."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest


FIXTURES = Path(__file__).parents[1] / "fixtures" / "higgs"


def measurements():
    return json.loads((FIXTURES / "measurements.json").read_text())


def parameterization():
    return json.loads((FIXTURES / "parameterization.json").read_text())


@pytest.mark.parametrize("mutation, match", [
    (lambda b: b.update(correlation=[[1, 0.2], [0.3, 1]]), "asymmetric"),
    (lambda b: b.update(correlation=[[1, 1.2], [1.2, 1]]), "semidefinite"),
    (lambda b: b["rows"][1].update(mass_gev=126.0), "mass"),
    (lambda b: b["rows"][0].update(unit="pb"), "unit"),
    (lambda b: b["rows"][0]["uncertainty"].update(minus=0), "positive"),
])
def test_named_measurement_check_refuses_invalid_bundle(mutation, match):
    from ravel.validation.higgs_bundle_checks import check_measurement_bundle
    doc = measurements()
    mutation(doc)
    with pytest.raises(ValueError, match=match):
        check_measurement_bundle(doc)


def test_free_bsm_width_and_unbounded_vector_coupling_are_refused():
    from ravel.validation.higgs_bundle_checks import check_boundary_parameters
    doc = parameterization()
    doc["parameters"]["BR_inv"]["fixed"] = False
    with pytest.raises(ValueError, match="width constraint|vector"):
        check_boundary_parameters(doc)


def test_reserved_mass_combination_is_refused():
    from ravel.physics.higgs_couplings import validate
    with pytest.raises(ValueError, match="reserved"):
        validate({"schema_version": 1, "input": "data.json", "mode": "mass-combination"})


def test_singular_correlation_is_not_regularized():
    from ravel.physics.higgs_couplings import fit
    doc = measurements()
    doc["correlation"] = [[1, 1], [1, 1]]
    with pytest.raises(ValueError, match="null|singular"):
        fit(doc, parameterization())


def toy_model(size=2, parameters=("kappa_a",), squared=False):
    measurement = measurements()
    prediction = parameterization()
    prediction["parameters"] = {n: {"initial": 1, "sm": 1, "fixed": False,
                                    "bounds": [0.1, 3]} for n in parameters}
    prediction["bsm_parameters"] = {}
    prediction["vector_parameters"] = list(parameters)
    prediction["loops"] = {}
    prediction["decays"] = {"D-0001": {"constant": 1}}
    prediction["branching_fractions"] = {"D-0001": 1}
    prediction["production"] = {n: {"polynomial": {"terms": [{"coefficient": 1,
                                "powers": {n: 2 if squared else 1}}]}} for n in parameters}
    rows, rates = [], []
    for i in range(size):
        name = parameters[i % len(parameters)]
        identity = f"R-{i:04d}"
        rows.append({"id": identity, "production": name, "decay": "D-0001", "quantity": "mu",
                     "unit": "1", "mass_gev": measurement["mass_gev"], "value": 1,
                     "uncertainty": {"minus": 0.1, "plus": 0.1}})
        rates.append({"id": identity, "production": name, "decay": "D-0001", "unit": "1", "sm_value": 1})
    measurement["rows"], prediction["rates"] = rows, rates
    measurement["correlation"] = np.eye(size).tolist()
    prediction["closure"] = {"points": [{"parameters": {n: 1 for n in parameters}, "values": [1] * size,
                                         "uncertainty": [1e-10] * size}], "tolerance_sigma": 1}
    return measurement, prediction


def test_linear_parameter_equals_closed_form_weighted_mean_and_interval():
    from ravel.physics.higgs_couplings import fit
    measurement, prediction = toy_model()
    y, sigma = np.array([1.2, 0.9]), np.array([0.1, 0.15])
    correlation = np.array([[1, 0.2], [0.2, 1]])
    measurement["correlation"] = correlation.tolist()
    for row, value, error in zip(measurement["rows"], y, sigma):
        row.update(value=float(value), uncertainty={"minus": float(error), "plus": float(error)})
    covariance = correlation * np.outer(sigma, sigma)
    precision = np.linalg.inv(covariance)
    error = 1 / np.sqrt(np.ones(2) @ precision @ np.ones(2))
    mean = error**2 * (np.ones(2) @ precision @ y)
    result = fit(measurement, prediction)
    assert result["best_fit"]["kappa_a"] == pytest.approx(mean, abs=1e-8)
    interval = result["intervals"]["68"]["kappa_a"]
    assert interval["lower"] == pytest.approx(mean - error, abs=1e-8)
    assert interval["upper"] == pytest.approx(mean + error, abs=1e-8)
    assert result["hesse_errors"]["kappa_a"] == pytest.approx(error, abs=1e-8)
    assert result["sm_comparison"]["degrees_of_freedom"] == 1
    assert result["sm_goodness_of_fit"]["degrees_of_freedom"] == 2


def test_variable_width_matches_known_asymmetric_profile_at_two_sigma():
    from ravel.physics.higgs_couplings import chi_square, fit
    measurement, prediction = toy_model(size=1)
    measurement["rows"][0]["uncertainty"] = {"minus": 0.12, "plus": 0.18}
    # Supplied profile q(d) = (d / (0.144 + 0.2*d))^2.
    for deviation in (-2 * 0.12, 2 * 0.18):
        expected = (deviation / (0.144 + 0.2 * deviation))**2
        actual = chi_square(measurement, [1 + deviation], treatment="variable-width-gaussian")
        assert actual == pytest.approx(expected, rel=0.02)
    result = fit(measurement, prediction, treatment="variable-width-gaussian")
    assert result["treatment"] == "variable-width-gaussian"
    assert result["intervals"]["68"]["kappa_a"]["lower"] == pytest.approx(0.88, abs=1e-7)
    assert result["intervals"]["68"]["kappa_a"]["upper"] == pytest.approx(1.18, abs=1e-7)


def test_variable_width_tracks_an_independent_asymmetric_profile():
    from ravel.physics.higgs_couplings import chi_square
    from scipy.optimize import brentq
    # Counting-shaped profile q(m) = 2 (m - n + n log(n / m)); its unit crossings are the supplied errors.
    count = 50.0

    def crossing(level, lower, upper):
        return brentq(lambda m: 2 * (m - count + count * np.log(count / m)) - level, lower, upper)

    measurement, _ = toy_model(size=1)
    measurement["rows"][0].update(quantity="sigma_br", unit="fb", value=count, uncertainty={
        "minus": count - crossing(1, 1, count), "plus": crossing(1, count, 10 * count) - count})
    for point in (crossing(4, 1, count), crossing(4, count, 10 * count)):
        assert chi_square(measurement, [point], treatment="variable-width-gaussian") == pytest.approx(4, rel=0.02)
        # The fixed mean width misses the same two-sigma points by more than ten percent.
        assert abs(chi_square(measurement, [point], treatment="symmetric-gaussian") - 4) > 0.4


def test_log_normal_preserves_asymmetric_one_sigma_endpoints():
    from ravel.physics.higgs_couplings import chi_square, fit
    measurement, prediction = toy_model(size=1)
    measurement["rows"][0]["uncertainty"] = {"minus": 0.12, "plus": 0.18}
    for value in (0.88, 1.18):
        assert chi_square(measurement, [value], treatment="log-normal") == pytest.approx(1, abs=1e-12)
    result = fit(measurement, prediction, treatment="log-normal")
    assert result["treatment"] == "log-normal"
    assert result["intervals"]["68"]["kappa_a"]["lower"] == pytest.approx(0.88, abs=1e-7)


def test_log_normal_matches_a_known_fixed_log_width_profile():
    from ravel.physics.higgs_couplings import chi_square
    measurement, _ = toy_model(size=1)
    sigma = 0.2
    measurement["rows"][0]["uncertainty"] = {"minus": float(1 - np.exp(-sigma)),
                                                "plus": float(np.exp(sigma) - 1)}
    for displacement in (-3 * sigma, -2 * sigma, 2 * sigma, 3 * sigma):
        assert chi_square(measurement, [float(np.exp(displacement))], treatment="log-normal") == pytest.approx((displacement / sigma)**2, abs=1e-12)


def test_one_and_two_dimensional_scans_use_profile_degrees_of_freedom():
    from ravel.physics.higgs_couplings import fit
    from scipy.stats import chi2
    measurement, prediction = toy_model(size=4, parameters=("kappa_a", "kappa_b"))
    measurement["correlation"] = (np.eye(4) * 0.8 + np.ones((4, 4)) * 0.2).tolist()
    result = fit(measurement, prediction, scans=[
        {"parameters": ["kappa_a"], "axes": [[0.9, 1.0, 1.1]]},
        {"parameters": ["kappa_a", "kappa_b"], "axes": [[0.9, 1.0], [0.9, 1.0]]}])
    for scan, dof in zip(result["scans"], (1, 2)):
        assert scan["degrees_of_freedom"] == dof
        assert scan["thresholds"]["95"] == pytest.approx(chi2.ppf(0.95, dof))
    # A correlated nuisance adjusts in the one-coordinate profile.
    one = result["scans"][0]["points"][0]["delta_chi2"]
    both = result["scans"][1]["points"][1]["delta_chi2"]
    assert one < both
    assert np.allclose(np.diag(result["correlation"]), 1)


def test_seeded_correlated_coupling_toys_close_and_cover():
    from ravel.physics.higgs_couplings import fit
    measurement, prediction = toy_model(size=20, parameters=("kappa_a", "kappa_b"), squared=True)
    truth = np.array([1.1, 0.9])
    correlation = np.eye(20) * 0.9 + np.ones((20, 20)) * 0.1
    measurement["correlation"] = correlation.tolist()
    for row in measurement["rows"]:
        row["uncertainty"] = {"minus": 0.08, "plus": 0.08}
    rng = np.random.default_rng(314159)
    # The Cholesky factor gives the same draws on every platform; the default factorization does not.
    noises = rng.multivariate_normal(np.zeros(20), correlation * 0.08**2, size=200, method="cholesky")
    fitted, errors, covered = [], [], []
    for noise in noises:
        for i, row in enumerate(measurement["rows"]):
            row["value"] = float(truth[i % 2]**2 + noise[i])
        result = fit(measurement, prediction)
        fitted.append([result["best_fit"][n] for n in ("kappa_a", "kappa_b")])
        errors.append([result["hesse_errors"][n] for n in ("kappa_a", "kappa_b")])
        covered.append([result["intervals"]["68"][n]["lower"] <= value <= result["intervals"]["68"][n]["upper"]
                        for n, value in zip(("kappa_a", "kappa_b"), truth)])
    mean = np.mean(fitted, axis=0)
    sigma = np.mean(errors, axis=0)
    coverage = np.mean(covered, axis=0)
    assert np.all(np.abs(mean - truth) < 0.1 * sigma), (mean, sigma)
    assert np.all((0.63 <= coverage) & (coverage <= 0.73)), coverage


def test_width_constraint_and_vector_bound_admit_the_declared_alternatives():
    from ravel.validation.higgs_bundle_checks import check_boundary_parameters
    doc = parameterization()
    doc["parameters"]["BR_inv"]["fixed"] = False
    doc["vector_upper_bound"] = 1
    bounded = check_boundary_parameters(doc)
    assert bounded["limits"]["kappa_V"][1] == 1
    del doc["vector_upper_bound"]
    doc["width_constraint"] = {"value": 1, "sigma": 0.1}
    assert check_boundary_parameters(doc)["passed"]


def test_declared_vector_bound_limits_both_signs():
    from ravel.physics.higgs_parameterization import evaluate, validate_bundle
    from ravel.validation.higgs_bundle_checks import check_boundary_parameters
    doc = parameterization()
    doc["parameters"]["BR_inv"]["fixed"] = False
    doc["parameters"]["kappa_V"]["bounds"] = [None, 3]
    doc["vector_upper_bound"] = 1
    # A squared coupling below minus one would reopen the width degeneracy.
    assert check_boundary_parameters(doc)["limits"]["kappa_V"] == [-1, 1]
    with pytest.raises(ValueError, match="vector"):
        evaluate(doc, {"kappa_V": -2})
    doc["parameters"]["kappa_V"]["initial"] = -2
    with pytest.raises(ValueError, match="vector"):
        validate_bundle(doc)


def test_local_two_axis_correlation_and_nested_bundle_pins(tmp_path):
    from ravel.physics.higgs_couplings import inputs, run
    measurement, prediction = toy_model()
    # The first matrix axis reverses the measured identity order.
    ids = [r["id"] for r in measurement["rows"]][::-1]
    cells = [(a, b, 1 if a == b else 0.2) for a in ids for b in ids]
    table = {"independent_variables": [
        {"header": {"name": "row"}, "values": [{"value": a} for a, _, _ in cells]},
        {"header": {"name": "column"}, "values": [{"value": b} for _, b, _ in cells]}],
        "dependent_variables": [{"header": {"name": "correlation"}, "values": [{"value": c} for _, _, c in cells]}]}
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "correlation.json").write_text(json.dumps(table))
    measurement["correlation"] = {"path": "correlation.json", "format": "hepdata", "bin_ids": ids}
    (nested / "measurements.json").write_text(json.dumps(measurement))
    (tmp_path / "parameterization.json").write_text(json.dumps(prediction))
    (tmp_path / "input.json").write_text(json.dumps({"measurements": {"path": "nested/measurements.json"},
                                                    "parameterization": {"path": "parameterization.json"}}))
    spec = {"schema_version": 1, "input": "input.json", "output": {"filename": "result.json", "format": "json"}}
    assert len(inputs(spec, tmp_path)) == 4
    result = run(spec, tmp_path, tmp_path / "out")
    assert len(result["inputs"]) == 4
    assert result["best_fit"]["kappa_a"] == pytest.approx(1, abs=1e-8)
    assert json.loads((tmp_path / "out" / "result.json").read_text()) == result


def test_absolute_rate_units_and_prediction_callback_seam():
    from ravel.physics.higgs_couplings import fit
    measurement, prediction = toy_model()
    for row in measurement["rows"]:
        row.update(quantity="sigma_br", unit="fb", value=3, uncertainty={"minus": 0.3, "plus": 0.3})
    for row in prediction["rates"]:
        row.update(unit="fb", sm_value=2)
    del prediction["closure"]
    result = fit(measurement, prediction, predictor=lambda point: [2 * point["kappa_a"]] * 2)
    assert result["best_fit"]["kappa_a"] == pytest.approx(1.5, abs=1e-5)
    assert result["predictions"] == pytest.approx([3, 3], abs=1e-5)


def test_registration_fragments_bind_only_existing_python_interfaces():
    import importlib
    root = Path(__file__).parents[2] / "src" / "ravel" / "data" / "higgs" / "registration"
    for mode in ("higgs-parameterization", "higgs-coupling-fit"):
        fragment = json.loads((root / (mode + ".json")).read_text())
        adapter = importlib.import_module(fragment["adapter"]["module"])
        assert all(callable(getattr(adapter, fragment["adapter"][name])) for name in ("validate", "inputs", "run"))
        assert fragment["operation_signatures"][mode]["effects"] == []
        assert fragment["manifest"]["operations"] == [{"mode": mode, "groups": ["python-host"]}]
        for check in fragment["provided_checks"].values():
            assert callable(getattr(importlib.import_module(check["module"]), check["function"]))
