"""Supplied, fictional EW likelihoods and source-domain refusal controls."""
from copy import deepcopy
from importlib import import_module
import json
import subprocess
import sys

import numpy as np
import pytest


def api():
    return import_module("ravel.physics.sm.ewpo")


def point():
    return {"m_H": 130.0, "m_t": 175.0, "m_Z": 92.0,
            "alpha_s": 0.12, "delta_alpha_had": 0.028,
            "delta_alpha_lep": 0.031, "alpha_mZ": 1 / 127.0,
            "s2w_on_shell": 0.22}


def upstream_point():
    p = point()
    return {"m_h": p["m_H"], "m_t": p["m_t"], "m_Z": p["m_Z"],
            "alpha_s": p["alpha_s"], "Delta_alpha_e_had": p["delta_alpha_had"],
            "Delta_alpha_e_lep": p["delta_alpha_lep"]}


def upstream_values(payload):
    """Keep live scientific imports out of planning-test interpreter state."""
    code = r'''
import hashlib, json, pathlib, sys
from flavio.physics.wdecays import mw
from flavio.physics.zdecays import gammazsm
p = json.load(sys.stdin)
values = []
for point in p['points']:
    if p['kind'] == 'mass':
        values.append(mw.mW_SM(point))
    else:
        row = {}
        for name, native in p['mapping'].items():
            value = gammazsm.Zobs(native, point['m_H'], point['m_t'], point['alpha_s'],
                                  point['delta_alpha_had'] + point['delta_alpha_lep'], point['m_Z'])
            row[name] = value / gammazsm.pb if name == 'sigma0had_pb' else value
        values.append(row)
module = mw if p['kind'] == 'mass' else gammazsm
print(json.dumps({'values': values, 'source_sha256': hashlib.sha256(pathlib.Path(module.__file__).read_bytes()).hexdigest()}))
'''
    result = subprocess.run([sys.executable, "-B", "-c", code], input=json.dumps(payload),
                            text=True, capture_output=True, check=True, timeout=60)
    return json.loads(result.stdout)


def shards():
    """Independent affine formulas whose inputs and domains can be changed."""
    ranges = {"m_H": [100., 160.], "m_t": [150., 200.], "m_Z": [90., 94.],
              "alpha_s": [0.10, 0.14], "delta_alpha_had": [0.02, 0.04],
              "delta_alpha_lep": [0.02, 0.04]}
    slopes = {"m_W": {"m_t": .008, "m_H": -.003, "m_Z": .8},
              "sin2theta_eff": {"m_H": .00002, "m_t": -.00003},
              "Gamma_nu": {"m_Z": .002, "alpha_s": .1}}
    constants = {"m_W": 79., "sin2theta_eff": .23, "Gamma_nu": .17}
    result = {}
    for name, slope in slopes.items():
        result[name] = {
            "kind": "polynomial", "unit": "1" if name == "sin2theta_eff" else "GeV",
            "sources": [{"id": "SRC-0001", "citation": "Fictional analytic fixture",
                         "locator": "https://example.invalid/source/ANA-0001"}],
            "validity": {"ranges": deepcopy(ranges), "source": "SRC-0001"},
            "variables": {key: {"parameter": key, "transform": "difference",
                                "reference": point()[key]} for key in slope},
            "terms": [{"coefficient": constants[name], "powers": {}}] + [
                {"coefficient": value, "powers": {key: 1}} for key, value in slope.items()]}
    return result


def spec(mode="sm"):
    p = point()
    priors = {key: {"value": p[key], "uncertainty": err}
              for key, err in {"m_H": 4., "m_t": 2., "m_Z": .02,
                               "alpha_s": .003, "delta_alpha_had": .0004}.items()}
    return {"schema_version": 1, "mode": mode, "parameter_point": p,
            "parametrizations": shards(),
            "inputs": {"parameters": priors,
                       "observables": {"sin2theta_eff": {"value": .23, "uncertainty": .0003},
                                       "Gamma_nu": {"value": .17, "uncertainty": .002}},
                       "m_W": {"variant": "VAR-0001", "value": 79., "uncertainty": .01}},
            "conventions": {"mass_definition": "on_shell_running_width", "top_mass": "pole",
                            "weak_angle": "effective_leptonic"}}


def oblique_spec(free_u=True):
    s = spec("oblique")
    s["inputs"]["parameters"] = {}
    s["reference_point"] = {"m_H": 130., "m_t": 175.}
    s["inputs"]["reference_point"] = deepcopy(s["reference_point"])
    s["free_u"] = free_u
    s["conventions"]["ew_scheme"] = "alpha_mZ"
    return s


@pytest.mark.parametrize("bad", [99., 161., float("nan"), float("inf")])
def test_range_guard_never_extrapolates(bad):
    p = point(); p["m_H"] = bad
    with pytest.raises(ValueError, match="validity|finite"):
        api().predict(p, ["m_W"], parametrizations=shards())


def test_uncited_or_missing_validity_refused():
    rows = shards(); rows["m_W"]["validity"] = None
    with pytest.raises(ValueError, match="validity"):
        api().predict(point(), ["m_W"], parametrizations=rows)
    rows = shards(); rows["m_W"]["sources"] = []
    with pytest.raises(ValueError, match="source"):
        api().predict(point(), ["m_W"], parametrizations=rows)


def test_reference_mismatch_is_refused():
    s = oblique_spec(); s["inputs"]["reference_point"]["m_t"] += 1
    with pytest.raises(ValueError, match="reference"):
        api().fit(s)


def test_multiple_mass_variants_cannot_be_combined():
    s = spec(); s["inputs"]["m_W"] = [s["inputs"]["m_W"], s["inputs"]["m_W"]]
    with pytest.raises(ValueError, match="variant"):
        api().fit(s)
    s = spec(); s["inputs"]["observables"]["m_W"] = {"value": 79., "uncertainty": .01}
    with pytest.raises(ValueError, match="variant"):
        api().fit(s)


def test_covariance_population_and_positive_definiteness_refused():
    s = spec(); s["covariance"] = {"order": ["m_W"], "matrix": [[0.]]}
    with pytest.raises(ValueError, match="covariance"):
        api().fit(s)
    s["inputs"]["parameters"] = {}; s["inputs"]["observables"] = {}
    s["free_parameters"] = ["m_t"]
    with pytest.raises(ValueError, match="covariance"):
        api().fit(s)


def test_negative_tiny_theory_covariance_is_refused():
    s = spec(); names = list(s["inputs"]["parameters"]) + list(s["inputs"]["observables"]) + ["m_W"]
    matrix = np.zeros((len(names), len(names))); matrix[-1, -1] = -1e-20
    s["theory_covariance"] = {"order": names, "matrix": matrix.tolist()}
    with pytest.raises(ValueError, match="PSD"):
        api().fit(s)


def test_likelihood_input_hash_binds_covariance_and_fixed_u():
    s = oblique_spec()
    first = api().oblique_likelihood(s)
    s["inputs"]["observables"]["Gamma_nu"]["uncertainty"] *= 2
    assert api().oblique_likelihood(s)["inputs_sha256"] != first["inputs_sha256"]
    s = oblique_spec(); s["free_u"] = False
    assert api().oblique_likelihood(s)["inputs_sha256"] != first["inputs_sha256"]


def test_native_shards_without_source_domains_are_refused():
    with pytest.raises(ValueError, match="validity"):
        api().predict(point(), ["m_W"])


def test_unidentified_oblique_direction_refused():
    s = oblique_spec(); del s["inputs"]["observables"]["Gamma_nu"]
    with pytest.raises(ValueError, match="identif"):
        api().fit(s)


def test_smeft_requires_source_bound_response():
    with pytest.raises(ValueError, match="response"):
        api().fit(spec("smeft"))


def test_sm_recovers_synthetic_parameters_and_zero_chi_square():
    s = spec(); s["parameter_point"]["m_H"] += 3.; s["parameter_point"]["m_t"] -= 2.
    before = deepcopy(s)
    result = api().fit(s)
    assert result["chi2_min"] < 1e-8
    for name in s["inputs"]["parameters"]:
        assert result["parameters"][name] == pytest.approx(point()[name], abs=1e-8)
    assert max(abs(x) for x in result["pulls"].values()) < 1e-8
    assert s == before


def test_indirect_recovers_dropped_input_and_profiles_intervals():
    s = spec("indirect"); s["drop"] = "m_t"; s["parameter_point"]["m_t"] -= 3.
    result = api().fit(s)
    row = result["indirect"]
    assert row["name"] == "m_t"
    assert "m_t" not in result["pulls"]
    assert row["value"] == pytest.approx(point()["m_t"], abs=1e-8)
    assert row["interval"][0] < row["value"] < row["interval"][1]
    assert row["delta_chi2"] == 1.
    for x in row["interval"]:
        assert api().profile_chi2(s, "m_t", x) - result["chi2_min"] == pytest.approx(1., abs=1e-6)


def test_indirect_observable_profile_uses_remaining_data():
    s = spec("indirect"); s["drop"] = "m_W"
    s["inputs"]["m_W"]["value"] = 200.
    result = api().fit(s)
    row = result["indirect"]
    assert row["value"] == pytest.approx(79., abs=1e-8)
    assert "m_W" not in result["pulls"]
    for endpoint in row["interval"]:
        assert api().profile_chi2(s, "m_W", endpoint) == pytest.approx(1., abs=1e-6)


@pytest.mark.parametrize("free_u", [True, False])
def test_oblique_recovers_planted_shifts(free_u):
    s = oblique_spec(free_u); expected = [.14, -.09, .06 if free_u else 0.]
    shifts = api().oblique_shifts(point(), ["m_W", "sin2theta_eff", "Gamma_nu"], expected,
                                  parametrizations=shards())
    s["inputs"]["m_W"]["value"] += shifts["m_W"]
    for name in s["inputs"]["observables"]:
        s["inputs"]["observables"][name]["value"] += shifts[name]
    result = api().fit(s)
    assert result["oblique"] == pytest.approx(expected, abs=1e-8)
    assert result["chi2_min"] < 1e-8


def test_oblique_likelihood_consumer_signature_and_psd():
    s = oblique_spec(False); result = api().oblique_likelihood(s)
    assert set(("mean", "covariance", "reference_point", "inputs_sha256")) <= result.keys()
    c = np.asarray(result["covariance"])
    assert c.shape == (3, 3)
    np.testing.assert_allclose(c, c.T, atol=1e-14)
    assert min(np.linalg.eigvalsh(c)) >= -1e-14
    assert c[2, 2] == 0.
    assert result["reference_point"] == s["reference_point"]
    assert len(result["inputs_sha256"]) == 64


def test_variants_produce_separate_records():
    rows = [{"variant": "VAR-0001", "value": 79., "uncertainty": .01},
            {"variant": "VAR-0002", "value": 79.02, "uncertainty": .015}]
    results = api().fit_variants(spec(), rows)
    assert [r["variant"] for r in results] == ["VAR-0001", "VAR-0002"]
    assert results[0]["inputs_sha256"] != results[1]["inputs_sha256"]
    assert results[0]["chi2_min"] != results[1]["chi2_min"]


def test_changed_population_correlated_covariance_and_units():
    s = spec(); del s["inputs"]["observables"]["Gamma_nu"]
    names = list(s["inputs"]["parameters"]) + ["sin2theta_eff", "m_W"]
    errors = [s["inputs"]["parameters"].get(k, s["inputs"]["observables"].get(k, s["inputs"]["m_W"]))["uncertainty"] for k in names]
    c = np.diag(np.square(errors)); c[0, 1] = c[1, 0] = .2 * errors[0] * errors[1]
    s["covariance"] = {"order": names, "matrix": c.tolist()}
    assert api().fit(s)["chi2_min"] < 1e-8
    s["conventions"]["mass_definition"] = "complex_pole"
    with pytest.raises(ValueError, match="mass"):
        api().fit(s)


def response_spec():
    s = spec("smeft")
    s["inputs"]["parameters"] = {}
    s["linear_response"] = {
        "coefficients": ["coef_a", "coef_b"], "eft": "SMEFT", "basis": "Warsaw",
        "scale": 92., "unit": "GeV^-2", "reference_point": point(),
        "sources": [{"id": "SRC-0002", "citation": "Fictional linear fixture",
                     "locator": "https://example.invalid/source/ANA-0002"}],
        "validity": {"ranges": {"coef_a": [-.5, .5], "coef_b": [-.5, .5]}, "source": "SRC-0002"},
        "baseline": {"m_W": 79., "sin2theta_eff": .23, "Gamma_nu": .17},
        "jacobian": {"m_W": {"coef_a": .1, "coef_b": .3},
                     "sin2theta_eff": {"coef_a": .01, "coef_b": -.02},
                     "Gamma_nu": {"coef_a": .2, "coef_b": .1}}}
    return s


def test_smeft_recovers_supplied_linear_coefficients():
    s = response_spec(); expected = {"coef_a": .13, "coef_b": -.08}
    for name, derivatives in s["linear_response"]["jacobian"].items():
        row = s["inputs"]["m_W"] if name == "m_W" else s["inputs"]["observables"][name]
        row["value"] += sum(value * expected[k] for k, value in derivatives.items())
    result = api().fit(s)
    assert result["wilson_coefficients"] == pytest.approx(expected, abs=1e-8)
    assert result["chi2_min"] < 1e-8
    assert result["coefficient_unit"] == "GeV^-2"


def test_smeft_coefficient_prior_uses_coefficient_units():
    s = response_spec()
    s["coefficient_priors"] = {"coef_a": {"value": 0., "uncertainty": .1, "unit": "GeV^-2"}}
    assert api().fit(s)["chi2_min"] < 1e-8


@pytest.mark.parametrize("mutation", ["reference", "units", "population", "bound"])
def test_smeft_bad_response_refused(mutation):
    s = response_spec(); r = s["linear_response"]
    if mutation == "reference":
        r["reference_point"]["m_t"] += 1
    elif mutation == "units":
        r["unit"] = "TeV^-2"
    elif mutation == "population":
        del r["jacobian"]["m_W"]["coef_b"]
    else:
        s["inputs"]["m_W"]["value"] += 10.
    with pytest.raises(ValueError, match="reference|GeV|response|validity"):
        api().fit(s)


def test_oblique_formulas_against_independent_linear_expressions():
    p = point(); S, T, U = .11, -.07, .04
    a, sw, cw = p["alpha_mZ"], p["s2w_on_shell"], 1 - p["s2w_on_shell"]
    shifts = api().oblique_shifts(p, ["m_W", "sin2theta_eff", "Gamma_nu"], [S, T, U], parametrizations=shards())
    assert shifts["m_W"] == pytest.approx(79. * a * (-S + 2*cw*T + (cw-sw)*U/(2*sw)) / (4*(cw-sw)), abs=1e-14)
    assert shifts["sin2theta_eff"] == pytest.approx(a*(S-4*sw*cw*T)/(4*(cw-sw)), abs=1e-14)
    assert shifts["Gamma_nu"] == pytest.approx(.17*a*T, abs=1e-14)


def test_upstream_likelihood_seam_reuses_existing_core(monkeypatch, tmp_path):
    from ravel.physics import eft_toolchain_core
    calls = []
    monkeypatch.setattr(eft_toolchain_core, "evaluate", lambda *args: calls.append(args) or {"likelihood": {"delta_log_likelihood": 0.}})
    config = {"smelli": {"include_likelihoods": ["likelihood_ewpt.yaml"]}}
    supplied = object()
    result = api().ewpt_cross_check(config, {}, {}, wilson_api=supplied,
                                   flavio_api=supplied, smelli_api=supplied, journal=supplied, output=tmp_path)
    assert result["likelihood"]["delta_log_likelihood"] == 0.
    assert calls[0][0] is config
    config["smelli"]["include_likelihoods"].append("ANA-0001.yaml")
    with pytest.raises(ValueError, match="EW likelihood"):
        api().ewpt_cross_check(config, {}, {}, wilson_api=supplied,
                               flavio_api=supplied, smelli_api=supplied, journal=supplied, output=tmp_path)


def test_flavio_linear_response_uses_supplied_native_seam(monkeypatch):
    ew = api(); calls = []
    def fake(parameters, observables, coefficient_document, wilson_options, **kwargs):
        values = coefficient_document["values"]; calls.append(deepcopy(values))
        a = values.get("coef_a", 0.); b = values.get("coef_b", 0.)
        return {"obs_a": 3. + 2*a - b + 7*a*a, "obs_b": 4. - a + 3*b}
    monkeypatch.setattr(ew, "flavio_predictions", fake)
    r = response_spec()["linear_response"]
    result = ew.flavio_linear_response(point(), upstream_point(), {"m_W": "obs_a", "Gamma_nu": "obs_b"},
        r["coefficients"], {"coef_a": .001, "coef_b": .002}, r["validity"], r["sources"],
        scale=92., wilson_options={}, wilson_api=object(), flavio_api=object())
    assert result["jacobian"]["m_W"] == pytest.approx({"coef_a": 2., "coef_b": -1.}, abs=1e-10)
    assert result["jacobian"]["Gamma_nu"] == pytest.approx({"coef_a": -1., "coef_b": 3.}, abs=1e-10)
    assert result["baseline"] == {"m_W": 3., "Gamma_nu": 4.}
    assert result["truncation"] == "linear_at_zero_coefficients"
    assert len(calls) == 9


def test_flavio_response_parameter_mismatch_refused(monkeypatch):
    ew = api()
    monkeypatch.setattr(ew, "flavio_predictions", lambda *args, **kwargs: {"obs_a": 1.})
    r = response_spec()["linear_response"]
    with pytest.raises(ValueError, match="parameter"):
        ew.flavio_linear_response(point(), {"m_t": 180.}, {"m_W": "obs_a"}, r["coefficients"],
            {"coef_a": .001, "coef_b": .002}, r["validity"], r["sources"],
            scale=92., wilson_options={}, wilson_api=object(), flavio_api=object())


def test_native_mass_coefficients_match_pinned_upstream_at_synthetic_points():
    # Source bounds are supplied for this engineering comparison, not certified here.
    rows = api().parametrizations()
    rows["m_W"]["validity"] = deepcopy(shards()["m_W"]["validity"])
    rows["m_W"]["sources"].extend(deepcopy(shards()["m_W"]["sources"]))
    points = []
    for dh, dt in [(-2., -1.), (0., 0.), (2., 1.)]:
        p = point(); p["m_Z"] = 91.2; p["m_H"] += dh; p["m_t"] += dt
        points.append(p)
    payload = {"kind": "mass", "points": [{"m_h": p["m_H"], "m_t": p["m_t"], "m_Z": p["m_Z"],
                 "alpha_s": p["alpha_s"], "Delta_alpha_e_had": p["delta_alpha_had"], "Delta_alpha_e_lep": p["delta_alpha_lep"]} for p in points]}
    upstream = upstream_values(payload)
    assert upstream["source_sha256"] == rows["m_W"]["sources"][0]["upstream_file_sha256"]
    for p, expected in zip(points, upstream["values"]):
        assert api().predict(p, ["m_W"], parametrizations=rows)["m_W"] == pytest.approx(expected, abs=.001)


def test_native_width_coefficient_and_unit_transcription():
    rows = api().parametrizations()
    mapping = {"Gamma_e": "Gammae,mu", "Gamma_tau": "Gammatau", "Gamma_nu": "Gammanu",
               "Gamma_u": "Gammau", "Gamma_c": "Gammac", "Gamma_d": "Gammad,s",
               "Gamma_b": "Gammab", "Gamma_Z": "GammaZ", "R_l": "Rl", "R_c": "Rc",
               "R_b": "Rb", "sigma0had_pb": "sigma0had"}
    for name in mapping:
        rows[name]["validity"] = deepcopy(shards()["m_W"]["validity"])
        rows[name]["sources"].extend(deepcopy(shards()["m_W"]["sources"]))
    points = []
    for change in [-1., 0., 1.]:
        p = point(); p["m_H"] += change; p["m_t"] -= change; p["delta_alpha_had"] += change * .0002
        points.append(p)
    upstream = upstream_values({"kind": "width", "points": points, "mapping": mapping})
    assert upstream["source_sha256"] == rows["Gamma_Z"]["sources"][0]["upstream_file_sha256"]
    for p, expected in zip(points, upstream["values"]):
        native = api().predict(p, mapping, parametrizations=rows)
        for name in mapping:
            assert native[name] == pytest.approx(expected[name], rel=1e-13, abs=1e-12)


def test_profile_reports_validity_endpoints_without_confidence_claim():
    s = spec("indirect"); s["drop"] = "m_t"
    s["bounds"] = {"m_t": [174.99, 175.01]}
    row = api().fit(s)["indirect"]
    assert row["interval"] == pytest.approx([174.99, 175.01], abs=1e-9)
    assert row["endpoint_status"] == ["validity_boundary", "validity_boundary"]


def test_cli_respects_supplied_output_and_refuses_overwrite(tmp_path):
    supplied = tmp_path / "supplied.json"; supplied.write_text(json.dumps(spec()))
    output = tmp_path / "chosen.json"
    assert api().main(["fit", str(supplied), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["chi2_min"] < 1e-8
    with pytest.raises(ValueError, match="fresh output"):
        api().main(["fit", str(supplied), "--output", str(output)])


def test_cli_duplicate_mass_selection_refused(tmp_path):
    supplied = tmp_path / "duplicate.json"
    text = json.dumps(spec()).replace('"variant": "VAR-0001"', '"variant": "VAR-0001", "variant": "VAR-0002"')
    supplied.write_text(text)
    with pytest.raises(ValueError, match="duplicate JSON"):
        api().main(["fit", str(supplied), "--output", str(tmp_path / "result.json")])


@pytest.mark.xfail(strict=True, reason="awaits cited effective-angle source and matching upstream model")
def test_native_effective_angle_shard_and_upstream_model():
    assert api().parametrizations()["sin2theta_eff"]["terms"]


@pytest.mark.xfail(strict=True, reason="awaits EW-input producer schema")
def test_ew_input_producer_schema_contract():
    assert api().ew_input_schema_status() == "qualified"


@pytest.mark.xfail(strict=True, reason="awaits external EW fit adapter")
def test_external_fit_adapter_contract():
    assert api().external_fit_interface_status() == "qualified"


def covariance_spec(scale=1., correlation=0.):
    s = spec(); names = list(s["inputs"]["parameters"]) + list(s["inputs"]["observables"]) + ["m_W"]
    rows = {**s["inputs"]["parameters"], **s["inputs"]["observables"], "m_W": s["inputs"]["m_W"]}
    errors = np.array([rows[k]["uncertainty"] for k in names])
    c = np.diag(np.square(errors))
    c[0, 1] = c[1, 0] = correlation * errors[0] * errors[1]
    c[-1, -1] *= scale
    s["covariance"] = {"order": names, "matrix": c.tolist()}
    return s


def test_covariance_diagonal_must_match_supplied_uncertainties():
    assert api().fit(covariance_spec())["chi2_min"] < 1e-8
    with pytest.raises(ValueError, match="covariance diagonal differs"):
        api().fit(covariance_spec(scale=4.))
    with pytest.raises(ValueError, match="positive definite"):
        api().fit(covariance_spec(correlation=1.5))


def test_malformed_specification_shapes_are_refused_as_values():
    for bad in (None, [], "oblique"):
        with pytest.raises(ValueError, match="specification"):
            api().oblique_likelihood(bad)
    s = spec(); del s["inputs"]
    with pytest.raises(ValueError, match="inputs"):
        api().fit_variants(s, [{"variant": "VAR-0001", "value": 79., "uncertainty": .01}])
    s = spec(); s["theory_covariance"] = "independent"
    with pytest.raises(ValueError, match="theory covariance"):
        api().fit(s)
    s = spec(); s["covariance"] = {"order": covariance_spec()["covariance"]["order"], "matrix": [[1., 2.], [3.]]}
    with pytest.raises(ValueError, match="covariance"):
        api().fit(s)
    for bad in ("many", 0, True, 2.5):
        s = spec(); s["max_nfev"] = bad
        with pytest.raises(ValueError, match="max_nfev"):
            api().fit(s)
