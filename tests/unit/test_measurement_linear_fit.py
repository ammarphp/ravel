"""Multi-parameter signed linear Gaussian fits of supplied measurements."""
import json

import pytest

np = pytest.importorskip("numpy")
scipy_stats = pytest.importorskip("scipy.stats")

from ravel.physics.measurement import prepare, run, validate


def document(terms=None, data=None):
    ids = ["r1", "r2", "r3", "r4"]

    def vector(values):
        return {"values": values, "bin_ids": ids[:], "unit": "1"}
    covariance = [[0.04, 0.01, 0.0, 0.0], [0.01, 0.09, 0.02, 0.0],
                  [0.0, 0.02, 0.0625, 0.005], [0.0, 0.0, 0.005, 0.01]]
    return {"schema_version": 1, "analysis_id": "synthetic-signal-strength-combination",
            "quantity": {"axes": [{"name": "category", "unit": "1"}],
                         "bins": [{"id": i, "low": [k], "high": [k + 1]} for k, i in enumerate(ids)],
                         "representation": "integrated", "normalization": "absolute", "unit": "1"},
            "data": vector(data or [1.1, 0.85, 1.3, 0.95]), "sm": vector([1.0, 1.0, 1.0, 1.0]),
            "linear_terms": terms or {"parameters": [{"name": "cA", "unit": "TeV^-2"}, {"name": "cB", "unit": "TeV^-2"}],
                                      "bin_ids": ids[:], "unit": "1",
                                      "matrix": [[0.30, 0.05], [-0.10, 0.20], [0.50, -0.25], [0.02, 0.10]]},
            "experimental_covariance": {"bin_ids": ids[:], "matrix": covariance, "unit": "(1)^2"},
            "covariance_policy": "experimental_only", "overlap": {"policy": "joint_covariance",
                                                                  "evidence": "synthetic joint covariance"},
            "constraints": []}


def fit_task():
    return {"schema_version": 1, "input": "input.json", "inference": "linear_fit"}


def execute(tmp_path, model):
    (tmp_path / "input.json").write_text(json.dumps(model))
    return run(fit_task(), tmp_path, tmp_path / "out")


def test_task_schema_for_linear_fit():
    assert validate(fit_task())["inference"] == "linear_fit"
    with pytest.raises(ValueError):
        validate({**fit_task(), "signal_strength": 1.0})


def test_closed_form_generalized_least_squares_with_signed_coefficients(tmp_path):
    model = document()
    result = execute(tmp_path, model)
    fit = result["linear_fit"]
    a = np.array(model["linear_terms"]["matrix"])
    c = np.array(model["experimental_covariance"]["matrix"])
    r = np.array(model["data"]["values"]) - 1.0
    ci = np.linalg.inv(c)
    fisher = a.T @ ci @ a
    cov = np.linalg.inv(fisher)
    best = cov @ a.T @ ci @ r
    assert [p["name"] for p in fit["parameters"]] == ["cA", "cB"]
    assert fit["best_fit"] == pytest.approx(best.tolist(), rel=1e-10)
    assert np.allclose(fit["covariance"], cov, rtol=1e-10, atol=0)
    assert fit["correlation"][0][1] == pytest.approx(cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1]))
    chi2_min = float((r - a @ best) @ ci @ (r - a @ best))
    chi2_sm = float(r @ ci @ r)
    assert fit["chi2_min"] == pytest.approx(chi2_min)
    assert fit["degrees_of_freedom"] == 2
    assert fit["sm_point"]["delta_chi2"] == pytest.approx(chi2_sm - chi2_min)
    assert fit["sm_point"]["p_value"] == pytest.approx(scipy_stats.chi2.sf(chi2_sm - chi2_min, 2))
    for k, row in enumerate(fit["intervals"]):
        sigma = np.sqrt(cov[k, k])
        assert row["profiled"]["68.27"] == pytest.approx([best[k] - sigma, best[k] + sigma])
        assert row["profiled"]["95"] == pytest.approx([best[k] - 1.959963984540054 * sigma, best[k] + 1.959963984540054 * sigma])
        one = (a[:, k] @ ci @ r) / fisher[k, k]
        width = 1 / np.sqrt(fisher[k, k])
        assert row["others_fixed_at_zero"]["best_fit"] == pytest.approx(one)
        assert row["others_fixed_at_zero"]["68.27"] == pytest.approx([one - width, one + width])
    assert fit["joint_region"]["delta_chi2"]["95"] == pytest.approx(scipy_stats.chi2.ppf(0.95, 2))
    assert result["inference"] == "linear_fit" and result["physics_validated"] is False
    assert json.loads((tmp_path / "out/measurement.json").read_text()) == result


def test_negative_coefficients_are_not_clipped(tmp_path):
    model = document(data=[0.8, 1.05, 0.7, 0.98])
    fit = execute(tmp_path, model)["linear_fit"]
    assert fit["best_fit"][0] < 0
    assert fit["intervals"][0]["profiled"]["95"][1] < 0.5


def test_single_parameter_reduces_to_weighted_mean_shift(tmp_path):
    terms = {"parameters": [{"name": "mu_shift", "unit": "1"}], "bin_ids": ["r1", "r2", "r3", "r4"], "unit": "1",
             "matrix": [[1.0], [1.0], [1.0], [1.0]]}
    model = document(terms=terms)
    fit = execute(tmp_path, model)["linear_fit"]
    c = np.array(model["experimental_covariance"]["matrix"])
    w = np.linalg.solve(c, np.ones(4))
    r = np.array(model["data"]["values"]) - 1.0
    assert fit["best_fit"][0] == pytest.approx(float(w @ r / w.sum()))
    assert fit["covariance"][0][0] == pytest.approx(float(1 / w.sum()))


@pytest.mark.parametrize("change", ["degenerate", "wrong_bins", "wrong_unit", "duplicate_name", "both_signal", "too_many"])
def test_unconstrained_or_inconsistent_linear_models_refuse(tmp_path, change):
    model = document()
    terms = model["linear_terms"]
    if change == "degenerate":
        terms["matrix"] = [[r[0], 2 * r[0]] for r in terms["matrix"]]
    elif change == "wrong_bins":
        terms["bin_ids"] = ["r1", "r2", "r3", "rX"]
    elif change == "wrong_unit":
        terms["unit"] = "pb"
    elif change == "duplicate_name":
        terms["parameters"][1]["name"] = "cA"
    elif change == "both_signal":
        model["signal"] = model["data"]
    else:
        terms["parameters"] = [{"name": f"c{i}", "unit": "1"} for i in range(5)]
        terms["matrix"] = [[float(i == j) for i in range(5)] for j in range(4)]
    with pytest.raises(ValueError):
        execute(tmp_path, model)


def test_prepare_keeps_signal_models_unchanged():
    model = document()
    model.pop("linear_terms")
    model["signal"] = {"values": [0.1, 0.1, 0.1, 0.1], "bin_ids": ["r1", "r2", "r3", "r4"], "unit": "1"}
    assert prepare(model)["signal"].tolist() == [0.1] * 4


def test_measurement_figure_draws_best_fit_linear_prediction(tmp_path):
    pytest.importorskip("matplotlib")
    pytest.importorskip("mplhep")
    from ravel.plotting.science_figures import render
    result = execute(tmp_path, document())
    figure = render({"mode": "measurement", "task": fit_task()}, result, tmp_path, tmp_path)
    assert figure["status"] == "passed" and figure["figures"][0]["plot_lint"] == "PASS"
