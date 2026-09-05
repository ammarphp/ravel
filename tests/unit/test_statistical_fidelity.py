"""Numerical and missing-evidence regressions; no generated events or baseline edits."""
import json
import math
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from ravel.physics import pyhf_exclude as exclude
from ravel.physics import sa2json_native as converter
from ravel.validation import certify_acceptance as acceptance
from ravel.validation import validate_cutflow as cutflow


@pytest.mark.parametrize("field", ["n", "b", "db", "s"])
@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "2"])
def test_counting_rejects_invalid_measurements(field, bad):
    sr = dict(name="SR", n=10, b=10, db=2, s=5)
    sr[field] = bad
    for builder, arg in [(exclude.model_from_counting, sr),
                         (exclude.model_from_counting_combined, [sr])]:
        with pytest.raises(ValueError, match=field):
            builder(arg)


def test_zero_background_uncertainty_is_exactly_preserved():
    sr = dict(name="SR", n=10, b=10, db=0, s=5)
    single, _ = exclude.model_from_counting(sr)
    combined, _ = exclude.model_from_counting_combined([sr])
    assert single.spec == combined.spec
    background = next(s for s in combined.spec["channels"][0]["samples"]
                      if s["name"] == "background")
    assert background["modifiers"][0]["data"] == [0.0]


def test_counting_uncertainty_on_zero_background_is_not_silently_disabled():
    with pytest.raises(ValueError, match="zero background"):
        exclude.model_from_counting(dict(n=0, b=0, db=2, s=5))


def test_limit_matches_independent_pyhf_root_with_coarse_plot_grid():
    from pyhf.infer.intervals.upper_limits import toms748_scan
    model, data = exclude.model_from_counting(dict(n=10, b=10, db=2, s=5))
    result = exclude.compute(model, data, n_curve=5)
    reference = toms748_scan(data, model, 0.001, 10, rtol=1e-5)
    np.testing.assert_allclose([result["obs_limit"], *result["exp_limits"]],
                               [float(reference[0]), *map(float, reference[1])], rtol=3e-4)
    assert result["limit_status"]["observed"] == "resolved"
    assert result["limit_status"]["expected"] == ["resolved"] * 5
    diagnostics = result["fit_diagnostics"]
    assert diagnostics["available"]
    assert math.isfinite(diagnostics["twice_nll"])
    assert {p["name"] for p in diagnostics["parameters"]} == set(model.config.par_names)
    assert diagnostics["covariance"] is None
    assert diagnostics["nuisance_pull_uncertainties"] is None


def _synthetic_cls(monkeypatch, function):
    monkeypatch.setattr(exclude, "hypotest", lambda mu, *_args, **_kw: function(mu))
    return exclude.model_from_counting(dict(n=10, b=10, db=2, s=5))


def test_non_power_of_two_cap_is_respected_and_bound_is_labeled(monkeypatch):
    visited = []
    def curve(mu):
        visited.append(mu)
        return 0.8, [0.5, 0.6, 0.7, 0.8, 0.9]
    model, data = _synthetic_cls(monkeypatch, curve)
    result = exclude.compute(model, data, n_curve=3, poi_cap=0.3)
    assert max(visited) <= 0.3
    assert result["obs_limit"] == 0.3
    assert result["limit_status"]["observed"] == "above_scan"


def test_expected_band_cap_does_not_censor_resolved_observed_limit(monkeypatch):
    model, data = _synthetic_cls(monkeypatch, lambda mu: (
        math.exp(-4 * mu), [math.exp(-rate * mu) for rate in [6, 5, 4, 3, 0.01]]))
    result = exclude.compute(model, data, n_curve=3, poi_cap=2)
    assert not result["at_poi_cap"]
    assert result["limit_status"]["observed"] == "resolved"
    assert result["limit_status"]["expected"][-1] == "above_scan"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_cls_cannot_be_dropped_across_a_limit(monkeypatch, bad):
    model, data = _synthetic_cls(monkeypatch, lambda mu: (
        bad if 0.9 <= mu <= 1.1 else math.exp(-3 * mu),
        [math.exp(-rate * mu) for rate in [5, 4, 3, 2, 1]]))
    with pytest.raises((ValueError, RuntimeError), match="CLs"):
        exclude.compute(model, data, n_curve=5)


def test_nonmonotonic_expected_curve_is_rejected(monkeypatch):
    def curve(mu):
        expected = [math.exp(-rate * mu) for rate in [5, 4, 3, 2, 1]]
        if mu == 1:
            expected[2] = expected[3]  # legal quantile order, but rises from preceding point
        return math.exp(-3 * mu), expected
    model, data = _synthetic_cls(monkeypatch, curve)
    with pytest.raises(RuntimeError, match="monoton"):
        exclude.compute(model, data, n_curve=25)


@pytest.mark.parametrize("payload", [
    {"SR": {"acceptance": float("nan"), "events": 10}},
    {"SR": {"acceptance": -0.1, "events": 10}},
    {"SR": {"acceptance": 0.1, "events": -1}},
    {"SR": {"acceptance": True, "events": 10}},
    {"SR": {"events": 1, "n_generated": 0}},
])
def test_acceptance_file_rejects_invalid_values(tmp_path, payload):
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        acceptance.read_my_acceptance(str(path))


def _cutflow_main(tmp_path, monkeypatch, mine, published, *, srs="SR", extra=()):
    objects = {f"/ROUTINE/{sr}": SimpleNamespace(val=lambda v=value: v)
               for sr, value in mine.items()}
    monkeypatch.setitem(sys.modules, "yoda", SimpleNamespace(read=lambda _: objects))
    monkeypatch.setattr(cutflow, "published_axe", lambda _t, sr, *_a, **_kw:
                        (published.get(sr), "grid node (m_parent=100, m_lsp=1)"))
    out = tmp_path / "cert.md"
    monkeypatch.setattr(sys, "argv", ["validate_cutflow", "--signal", "unused.yoda",
        "--routine", "ROUTINE", "--sigma-pb", "0.001", "--lumi-fb", "1000",
        "--tables-dir", str(tmp_path), "--grid", "fixture", "--m-parent", "100",
        "--m-lsp", "1", "--srs", srs, "--out", str(out), *extra])
    cutflow.main()
    return json.loads(out.with_suffix(".json").read_text())


def test_missing_driving_comparison_fails_with_null_residual(tmp_path, monkeypatch):
    result = _cutflow_main(tmp_path, monkeypatch, {}, {}, extra=("--driving-sr-override", "SR"))
    assert result["verdict"] == "FAIL"
    assert result["worst_driving_mu95_impact"] is None
    assert result["comparison_counts"] == {"requested": 1, "evaluated": 0, "missing": 1}


def test_zero_acceptance_is_measured_complete_deficit(tmp_path, monkeypatch):
    result = _cutflow_main(tmp_path, monkeypatch, {"SR": 0}, {"SR": 0.1},
                           extra=("--driving-sr-override", "SR"))
    assert result["verdict"] == "FAIL"
    assert result["rows"][0]["ratio"] == 0
    assert result["rows"][0]["mu95_impact"] == 1
    assert result["comparison_counts"]["evaluated"] == 1


def test_worst_driving_residual_includes_all_driving_regions(tmp_path, monkeypatch):
    ex = tmp_path / "exclusion.json"
    ex.write_text(json.dumps({"best_sr": "A", "per_sr": {
        "A": {"exp_median": 1}, "B": {"exp_median": 1.1}}}))
    result = _cutflow_main(tmp_path, monkeypatch, {"A": 100, "B": 67}, {"A": 0.1, "B": 0.1},
                           srs="A,B", extra=("--exclusion", str(ex)))
    assert result["verdict"] == "FAIL"
    assert result["worst_driving_mu95_impact"] == pytest.approx(0.33)


def test_acceptance_only_publication_cannot_stand_in_for_acceptance_efficiency(tmp_path):
    (tmp_path / "submission.yaml").write_text("description: acceptance SR-S slepton\ndata_file: acceptance.yaml\n")
    (tmp_path / "acceptance.yaml").write_text("""independent_variables:
- values: [{value: 100}]
- values: [{value: 10}]
dependent_variables:
- values: [{value: 100}]
""")
    value, description, _ = acceptance.published_acceff(str(tmp_path), "SR-S", "slepton", 100, 10)
    assert value is None
    assert "efficiency" in description


@pytest.mark.parametrize("x,fun,objective,bounds,fixed", [
    ([float("nan")], 0, lambda _: 0, [(0, 1)], []),
    ([2], 0, lambda _: 0, [(0, 1)], []),
    ([0.5], 0, lambda _: 0, [(0, 1)], [(0, 0.2)]),
    ([0.5], 1e10, lambda _: float("nan"), [(0, 1)], []),
    ([0.5], 0, lambda _: 3, [(0, 1)], []),
])
def test_optimizer_success_flag_cannot_validate_bad_minimum(x, fun, objective, bounds, fixed):
    assert not exclude.robust_optimizer._valid_result(x, fun, objective, bounds, fixed)


def test_migrad_penalty_plateau_cannot_be_returned_as_a_valid_fit(monkeypatch):
    class FakeMinuit:
        def __init__(self, _objective, *x):
            self.values = list(x)
            self.fval = 1e10
            self.limits = [None] * len(x)
            self.fixed = [False] * len(x)
            self.valid = True
        def migrad(self, **_kwargs):
            pass
    monkeypatch.setitem(sys.modules, "iminuit", SimpleNamespace(Minuit=FakeMinuit))
    with pytest.raises(RuntimeError, match="original-objective"):
        exclude.robust_optimizer._migrad(lambda _: float("nan"), [1], [(0, 2)], [])


@pytest.mark.parametrize("factor", ["-2", "0", "nan", "inf"])
def test_cli_rejects_invalid_signal_scale_before_reading_or_fitting(tmp_path, monkeypatch, factor):
    monkeypatch.setattr(sys, "argv", ["pyhf_exclude", "counting", "--srs", "does-not-exist.json",
        "--out", str(tmp_path / "out"), f"--sigma-scale={factor}"])
    with pytest.raises(SystemExit, match="2"):
        exclude.main()
    assert not (tmp_path / "out").exists()


def test_signal_scale_changes_every_signal_strength_coordinate_consistently():
    result = {"obs_limit": 2, "exp_limits": [1, 1.5, 2, 3, 4], "scan_mu": [0.1, 1, 10],
              "limit_status": {"observed": "resolved", "expected": ["below_scan", "resolved", "resolved", "resolved", "above_scan"]},
              "limit_brackets": {"observed": [1, 3], "expected": [[None, 1], [1, 2], [1, 3], [2, 4], [4, None]]},
              "per_sr": {"A": {"obs_limit": 2, "exp_median": 3, "s": 10}}}
    exclude.scale_result(result, 2)
    assert result["obs_limit_lo"] == 2
    assert result["obs_limit"] == 1
    assert result["scan_mu"] == [0.05, 0.5, 5]
    assert result["limit_brackets"] == {"observed": [0.5, 1.5], "expected": [[None, 0.5], [.5, 1], [.5, 1.5], [1, 2], [2, None]]}
    assert {k: result["per_sr"]["A"][k] for k in ("obs_limit", "exp_median", "s_lo", "s")} == {
        "obs_limit": 1, "exp_median": 1.5, "s_lo": 10, "s": 20}
    assert result["per_sr"]["A"]["s"] * result["per_sr"]["A"]["obs_limit"] == 20


@pytest.mark.parametrize("value", ["NaN", "1e999", "Infinity"])
def test_likelihood_json_rejects_nonfinite_numbers_before_pyhf(tmp_path, value):
    bkg, patch = tmp_path / "background.json", tmp_path / "patch.json"
    bkg.write_text('{"observation":' + value + '}')
    patch.write_text("[]")
    with pytest.raises(ValueError, match="nonfinite"):
        exclude.model_from_likelihood(bkg, patch)


def test_acceptance_preserves_weighted_event_yields(tmp_path):
    path = tmp_path / "yields.csv"
    path.write_text("SR,events,acceptance,err\nSR,5.9,0.059,0.01\n")
    assert acceptance.read_my_acceptance(str(path))["SR"] == (0.059, 5.9)


def test_acceptance_true_worst_driving_residual_and_zero_ratio(tmp_path, monkeypatch):
    path = tmp_path / "yields.json"
    path.write_text(json.dumps({"SR_S_A": {"acceptance": 0.1, "events": 100},
                                "SR_S_B": {"acceptance": 0.133, "events": 80},
                                "SR_S_C": {"acceptance": 0, "events": 0}}))
    monkeypatch.setattr(acceptance, "published_acceff", lambda *_a, **_kw:
                        (0.1, "grid node (m_parent=100, split=10)", False))
    out = tmp_path / "cert.md"
    monkeypatch.setattr(sys, "argv", ["certify_acceptance", "--acceptance", str(path),
        "--tables-dir", str(tmp_path), "--grid", "slepton", "--m-parent", "100", "--dm", "10",
        "--srs", "SR_S_A,SR_S_B,SR_S_C", "--out", str(out)])
    acceptance.main()
    result = json.loads(out.with_suffix(".json").read_text())
    assert result["worst_driving_residual"] == pytest.approx(0.33)
    assert result["rows"][2]["ratio"] == 0
    assert result["comparison_counts"] == {"requested": 3, "evaluated": 3, "missing": 0}
    assert result["verdict"] == "FAIL"


def test_nearest_mass_point_is_diagnostic_only_in_cutflow(tmp_path, monkeypatch):
    # Use a real grid lookup: the sole node is a different mass, despite a perfect yield ratio.
    (tmp_path / "submission.yaml").write_text("description: acceptance times efficiency SRSR fixture\ndata_file: table.yaml\n")
    (tmp_path / "table.yaml").write_text("""independent_variables:
- values: [{value: 200}]
- values: [{value: 1}]
dependent_variables:
- values: [{value: 0.1}]
""")
    objects = {"/ROUTINE/SR": SimpleNamespace(val=lambda: 100)}
    monkeypatch.setitem(sys.modules, "yoda", SimpleNamespace(read=lambda _: objects))
    out = tmp_path / "cert.md"
    monkeypatch.setattr(sys, "argv", ["validate_cutflow", "--signal", "unused", "--routine", "ROUTINE",
        "--sigma-pb", "0.001", "--lumi-fb", "1000", "--tables-dir", str(tmp_path),
        "--grid", "fixture", "--m-parent", "100", "--m-lsp", "1", "--srs", "SR",
        "--driving-sr-override", "SR", "--out", str(out)])
    cutflow.main()
    result = json.loads(out.with_suffix(".json").read_text())
    assert result["rows"][0]["ratio"] == 1
    assert result["driving_reference_unmatched"]
    assert result["verdict"] == "FAIL"


def test_nearest_mass_point_is_diagnostic_only_in_acceptance(tmp_path, monkeypatch):
    path = tmp_path / "acceptance.json"
    path.write_text('{"SR_S": {"acceptance": 0.1, "events": 100}}')
    monkeypatch.setattr(acceptance, "published_acceff", lambda *_a, **_kw:
                        (0.1, "NEAREST grid node (m_parent=200, split=10)", False))
    out = tmp_path / "cert.md"
    monkeypatch.setattr(sys, "argv", ["certify_acceptance", "--acceptance", str(path),
        "--tables-dir", str(tmp_path), "--grid", "slepton", "--m-parent", "100", "--dm", "10",
        "--srs", "SR_S", "--out", str(out)])
    acceptance.main()
    result = json.loads(out.with_suffix(".json").read_text())
    assert result["verdict"] == "FAIL"
    assert result["driving_reference_unmatched"]
    assert "different published mass point" in result["fail_reason"]


def test_exact_inverse_signal_shift_is_separate_from_acceptance_proxy(tmp_path, monkeypatch):
    result = _cutflow_main(tmp_path, monkeypatch, {"SR": 50}, {"SR": 0.1},
                           extra=("--driving-sr-override", "SR"))
    row = result["rows"][0]
    assert row["mu95_impact"] == 0.5
    assert row["inverse_signal_limit_shift"] == 1.0  # half signal -> twice the limit, if uniform
    assert "proxy" in result["mu95_impact_semantics"]


def test_full_workspace_preserves_shared_background_nuisance(tmp_path):
    channels = [{"name": name, "samples": [
        {"name": "signal", "data": [5], "modifiers": [{"name": "mu", "type": "normfactor", "data": None}]},
        {"name": "background", "data": [background], "modifiers": [{"name": "shared_norm", "type": "normsys",
                                                                   "data": {"hi": 1.1, "lo": 0.9}}]},
    ]} for name, background in [("A", 10), ("B", 20)]]
    workspace = {"version": "1.0.0", "channels": channels,
                 "observations": [{"name": "A", "data": [10]}, {"name": "B", "data": [20]}],
                 "measurements": [{"name": "measurement", "config": {"poi": "mu", "parameters": []}}]}
    background, patch = tmp_path / "background.json", tmp_path / "patch.json"
    background.write_text(json.dumps(workspace))
    patch.write_text("[]")
    before = background.read_bytes()
    model, _ = exclude.model_from_likelihood(background, patch)
    assert model.config.par_names.count("shared_norm") == 1
    pars = model.config.suggested_init()
    pars[model.config.poi_index] = 0
    pars[model.config.par_map["shared_norm"]["slice"].start] = 1
    np.testing.assert_allclose(model.expected_data(pars)[:2], [11, 22])
    assert background.read_bytes() == before


def test_poisson_auxiliary_observations_cannot_be_negative():
    model, data = exclude.model_from_counting(dict(n=10, b=10, db=2, s=5))
    data[-1] = -1
    with pytest.raises(ValueError, match="Poisson auxiliary"):
        exclude.compute(model, data)


def _conversion_files(tmp_path, channels, branches, monkeypatch):
    background = tmp_path / "MonoJet-background.json"
    background.write_text(json.dumps({"version": "1.0.0",
        "channels": [{"name": channel, "samples": [{"name": "background", "data": [10], "modifiers": []}]}
                     for channel in channels],
        "observations": [{"name": channel, "data": [10]} for channel in channels],
        "measurements": [{"name": "measurement", "config": {"poi": "mu_SIG", "parameters": []}}]}))
    root = tmp_path / "signal.root"
    class Tree(dict):
        def arrays(self):
            return self
    class Root(dict):
        def __enter__(self):
            return self
        def __exit__(self, *_exc):
            pass
    tree = Tree({name: np.asarray(values, dtype="float64") for name, values in branches.items()})
    monkeypatch.setitem(sys.modules, "uproot", SimpleNamespace(open=lambda _: Root(ntuple=tree)))
    return background, root, tmp_path / "patch.json"


def test_converter_preserves_signed_weights_and_original_channel_order(tmp_path, monkeypatch):
    import jsonpatch
    background, root, output = _conversion_files(tmp_path, ["Z_cuts", "A_cuts"],
                                                 {"Z": [2, -0.5, 0], "A": [0, 3, -1]}, monkeypatch)
    converter.main(["-i", str(root), "-b", str(background), "-o", str(output), "-n", "signal",
                    "-l", "2", "-s", "3"])
    patched = jsonpatch.apply_patch(json.loads(background.read_text()), json.loads(output.read_text()))
    assert [(c["name"], c["samples"][-1]["data"]) for c in patched["channels"]] == [
        ("Z_cuts", [9]), ("A_cuts", [12])]
    assert all(len(c["samples"]) == 1 for c in json.loads(background.read_text())["channels"])


def test_converter_flavour_mask_keeps_negative_selected_weights(tmp_path, monkeypatch):
    import jsonpatch
    background, root, output = _conversion_files(tmp_path, ["Z_ee_cuts"],
        {"Z_ee": [2, -0.5, 100], "isee": [1, 1, 0], "ismm": [0, 0, 1]}, monkeypatch)
    converter.main(["-i", str(root), "-b", str(background), "-o", str(output), "-n", "signal", "-l", "1", "-c"])
    patched = jsonpatch.apply_patch(json.loads(background.read_text()), json.loads(output.read_text()))
    assert patched["channels"][0]["samples"][-1]["data"] == [1.5]


@pytest.mark.parametrize("branches, message", [
    ({"other": [1]}, "missing"), ({"Z": [float("nan")]}, "finite"),
    ({"Z": [1, -2]}, "negative"),
])
def test_converter_does_not_turn_invalid_or_absent_signal_into_a_patch(tmp_path, monkeypatch, branches, message):
    background, root, output = _conversion_files(tmp_path, ["Z_cuts"], branches, monkeypatch)
    with pytest.raises(ValueError, match=message):
        converter.main(["-i", str(root), "-b", str(background), "-o", str(output), "-n", "signal", "-l", "1"])
    assert not output.exists()
