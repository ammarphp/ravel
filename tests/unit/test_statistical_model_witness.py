"""Frozen algebraic witnesses and adverse checks, independent of compilation."""
from copy import deepcopy
import inspect
import math

import pytest

from ravel.validation import statistical_model_witness as witness


def model(counts=(12, 24), signal=(5, 1), transfer=(1, 2)):
    return {
        "schema_version": 1,
        "parameters": [
            {"name": "mu", "role": "poi", "bounds": [0, 100]},
            {"name": "beta", "role": "rate", "bounds": [0, 100]},
        ],
        "bins": [{"id": name, "observed": n} for name, n in zip(("SR", "CR"), counts)],
        "components": [
            {"id": "signal", "nominal": list(signal), "factors": [["mu"], ["mu"]], "log_response": [[], []]},
            {"id": "background", "nominal": list(transfer), "factors": [["beta"], ["beta"]], "log_response": [[], []]},
        ],
        "auxiliary": {"names": [], "observed": [], "covariance": [], "source": None},
    }


def correlated_model():
    document = model()
    document["auxiliary"] = {"names": ["x", "y"], "observed": [0.3, -0.1],
                             "covariance": [[1, 0.5], [0.5, 1]], "source": "auxiliary"}
    document["components"][0]["log_response"] = [[0.2, 0.1], [0.2, 0.1]]
    document["components"][1]["log_response"] = [[0.1, -0.2], [0, 0]]
    return document


def test_contaminated_on_off_exact_profile():
    reference = witness.on_off_reference(12, 24, 5, 1, 2, 1)
    assert reference["profile_beta"] == pytest.approx((39 + math.sqrt(7209)) / 12, abs=1e-14)
    assert reference["profile_beta"] == pytest.approx(10.325485849042453, abs=1e-14)
    assert reference["means"] == pytest.approx([15.325485849042453, 21.650971698084906], abs=1e-14)
    assert reference["muhat"] == 0
    assert reference["betahat"] == 12
    assert reference["qtilde_mu"] == pytest.approx(1.0264300139475324, abs=1e-12)
    evaluation = witness.evaluate(model(), {"mu": 1, "beta": reference["profile_beta"]})
    assert evaluation["poisson_nll"] == pytest.approx(reference["poisson_nll"], abs=1e-14)


def test_control_signal_changes_profile_and_is_not_dropped():
    contaminated = witness.on_off_reference(12, 24, 5, 1, 2, 1)
    pure_control = witness.on_off_reference(12, 24, 5, 0, 2, 1)
    assert pure_control["profile_beta"] == pytest.approx((21 + math.sqrt(1881)) / 6)
    assert contaminated["qtilde_mu"] != pytest.approx(pure_control["qtilde_mu"])


def test_correlated_auxiliary_physical_basis_exact_quadratic():
    value = witness.evaluate(correlated_model(), {"mu": 1, "beta": 12, "x": 1, "y": -1})
    assert value["auxiliary_nll"] == pytest.approx(193 / 150, abs=1e-14)
    assert value["means"] == pytest.approx([21.724160281290274, 25.105170918075647], abs=1e-13)
    assert value["nll_without_constant"] == value["poisson_nll"] + value["auxiliary_nll"]


def test_abcd_products_and_exact_mle_witnesses():
    document = model()
    document["parameters"] += [{"name": name, "role": "rate", "bounds": [0, 10]} for name in ("rX", "rY")]
    document["bins"] = [{"id": name, "observed": n} for name, n in zip("ABCD", (12, 18, 8, 22))]
    document["components"] = [
        {"id": "signal", "nominal": [5, 0, 0, 0], "factors": [["mu"]] * 4, "log_response": [[]] * 4},
        {"id": "background", "nominal": [1] * 4,
         "factors": [["beta", "rX", "rY"], ["beta", "rX"], ["beta", "rY"], ["beta"]], "log_response": [[]] * 4},
    ]
    null = witness.evaluate(document, {"mu": 0, "beta": 20, "rX": 1, "rY": 0.5})
    full = witness.evaluate(document, {"mu": 12 / 11, "beta": 22, "rX": 18 / 22, "rY": 8 / 22})
    assert null["means"] == [10, 20, 10, 20]
    assert full["means"] == pytest.approx([12, 18, 8, 22])
    assert 2 * (null["nll_without_constant"] - full["nll_without_constant"]) == pytest.approx(1.2060898897361056, abs=1e-12)


def test_proportional_signal_exposes_nonidentifiability():
    reference = witness.on_off_reference(12, 24, 5, 10, 2, 1)
    assert reference["identifiable"] is False
    assert reference["qtilde_mu"] == pytest.approx(0, abs=1e-12)
    assert reference["profile_beta"] == pytest.approx(7)
    document = model(signal=(5, 10))
    first = witness.evaluate(document, {"mu": 0, "beta": 12})
    second = witness.evaluate(document, {"mu": 1, "beta": 7})
    assert first == second


def test_profile_boundary_and_one_sided_ratio():
    # The joint MLE here has beta=0 and mu=4, above the tested mu.
    result = witness.on_off_reference(20, 0, 5, 0, 2, 1)
    assert result["muhat"] == 4
    assert result["betahat"] == 0
    assert result["qtilde_mu"] == 0
    assert witness.on_off_reference(0, 0, 5, 1, 2, 1)["profile_beta"] == 0


def test_zero_mean_probability_semantics():
    zero = witness.evaluate(model(counts=(0, 0)), {"mu": 0, "beta": 0})
    assert zero == {"means": [0, 0], "poisson_nll": 0, "auxiliary_nll": 0, "nll_without_constant": 0}
    impossible = witness.evaluate(model(), {"mu": 0, "beta": 0})
    assert impossible["nll_without_constant"] == math.inf


def test_verify_detects_wrong_mean_and_wrong_auxiliary_claim():
    document = correlated_model()
    point = {"mu": 1, "beta": 12, "x": 1, "y": -1}
    claim = {"means": [21.724160281290274, 25.105170918075647],
             "auxiliary_nll": 193 / 150}
    # NLL is independently assembled from the frozen means and auxiliary value.
    claim["nll_without_constant"] = sum(m - n * math.log(m) for n, m in zip((12, 24), claim["means"])) + 193 / 150
    assert witness.verify(document, [point], [claim])["passed"]
    claim["means"][1] += 1
    assert witness.verify(document, [point], [claim])["passed"] is False
    claim["means"][1] -= 1
    claim["auxiliary_nll"] = 0
    result = witness.verify(document, [point], [claim])
    assert result["passed"] is False
    assert result["max_absolute_residual"] == pytest.approx(193 / 150)


@pytest.mark.parametrize("defect", ["float_version", "bool_count", "negative_count", "float_count", "duplicate_rate", "duplicate_bin", "duplicate_component", "missing_nominal", "negative_nominal", "unknown_factor", "duplicate_factor", "short_response", "short_covariance", "asymmetric_covariance", "singular_covariance", "indefinite_covariance", "nan_response", "colliding_auxiliary", "missing_point", "extra_point", "bool_point", "negative_rate", "above_cap", "overflow"])
def test_malformed_scientific_arithmetic_is_refused(defect):
    document = correlated_model()
    point = {"mu": 1, "beta": 12, "x": 1, "y": -1}
    if defect == "float_version": document["schema_version"] = 1.0
    elif defect == "bool_count": document["bins"][0]["observed"] = True
    elif defect == "negative_count": document["bins"][0]["observed"] = -1
    elif defect == "float_count": document["bins"][0]["observed"] = 12.0
    elif defect == "duplicate_rate": document["parameters"].append(deepcopy(document["parameters"][1]))
    elif defect == "duplicate_bin": document["bins"][1]["id"] = "SR"
    elif defect == "duplicate_component": document["components"][1]["id"] = "signal"
    elif defect == "missing_nominal": document["components"][0]["nominal"].pop()
    elif defect == "negative_nominal": document["components"][0]["nominal"][0] = -5
    elif defect == "unknown_factor": document["components"][0]["factors"][0] = ["unknown"]
    elif defect == "duplicate_factor": document["components"][0]["factors"][0] = ["mu", "mu"]
    elif defect == "short_response": document["components"][0]["log_response"][0].pop()
    elif defect == "short_covariance": document["auxiliary"]["covariance"].pop()
    elif defect == "asymmetric_covariance": document["auxiliary"]["covariance"][0][1] = 0.4
    elif defect == "singular_covariance": document["auxiliary"]["covariance"] = [[1, 1], [1, 1]]
    elif defect == "indefinite_covariance": document["auxiliary"]["covariance"] = [[1, 2], [2, 1]]
    elif defect == "nan_response": document["components"][0]["log_response"][0][0] = math.nan
    elif defect == "colliding_auxiliary": document["auxiliary"]["names"][0] = "mu"
    elif defect == "missing_point": del point["x"]
    elif defect == "extra_point": point["extra"] = 0
    elif defect == "bool_point": point["x"] = True
    elif defect == "negative_rate": point["mu"] = -1
    elif defect == "above_cap": point["mu"] = 101
    elif defect == "overflow": point["x"] = 10000
    with pytest.raises(ValueError):
        witness.evaluate(document, point)


@pytest.mark.parametrize("defect", ["empty", "short", "nonfinite", "wrong_shape", "negative_atol"])
def test_malformed_verification_claims_are_refused(defect):
    points = [{"mu": 0, "beta": 12}]
    claims = [{"means": [12, 24], "nll_without_constant": 0}]
    tolerance = 1e-8
    if defect == "empty": points, claims = [], []
    elif defect == "short": claims = []
    elif defect == "nonfinite": claims[0]["nll_without_constant"] = math.inf
    elif defect == "wrong_shape": claims[0]["means"] = [12]
    elif defect == "negative_atol": tolerance = -1
    with pytest.raises(ValueError):
        witness.verify(model(), points, claims, atol=tolerance)


def test_checker_source_has_no_producer_or_whitening_import():
    source = inspect.getsource(witness)
    assert "ravel.physics" not in source
    assert "cholesky" not in source
