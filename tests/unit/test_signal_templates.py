"""All-channel template admission and independent original-coordinate witnesses."""
from copy import deepcopy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tarfile

import numpy as np
import pytest

from ravel.physics import published_model as published
from ravel.physics import signal_templates as templates


def _pin(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def source_document(archive, background_raw, patchset_raw, coordinates, *, members=None, source=None):
    background = json.loads(background_raw)
    return {"schema_version": 1, "source": source or {
        "record_id": "synthetic", "version": 1, "resource_id": "fixture",
        "record_url": "https://example.invalid/record", "archive_url": "https://example.invalid/archive", "doi": "synthetic control"},
        "archive": _pin(archive), "members": {role: {"name": (members or {}).get(role, role + ".json"),
        "sha256": hashlib.sha256(raw).hexdigest()} for role, raw in (("background", background_raw), ("patchset", patchset_raw))},
        "coordinates": coordinates, "measurement": background["measurements"][0]["name"],
        "expected_background_digest": published.canonical_background_digest(background), "grounding": [],
        "inference": {"backend": "numpy", "fit_tolerance": 1e-7, "poi_cap": 128,
                      "root_rtol": 1e-4, "n_curve": 3, "poi_domain_policy": "engine_dynamic_nonnegative",
                      "retain_profile_witnesses": True, "witness_limits": {"evaluations": 100, "minimizations": 1000, "bytes": 1048576}}}


def fixture(tmp_path, *, shape_stat=False, omitted_cr=False, zero_error=False, shared_stat=False):
    channels, observations, operations = [], [], []
    for index, (name, nominal) in enumerate((("SR", [4.0, 0.0]), ("CR", [2.0, 1.0]))):
        stat_kind = "shapesys" if shape_stat else "staterror"
        background = {"name": "background", "data": [12.0, 8.0], "modifiers": [
            {"name": "shared", "type": "normsys", "data": {"hi": 1.15, "lo": 0.8}}]}
        if shared_stat and name == "SR":
            background["modifiers"].append({"name": "mc_SR", "type": "staterror", "data": [1.2, 0.4]})
        channels.append({"name": name, "samples": [background]})
        observations.append({"name": name, "data": [16, 9]})
        sample = {"name": "signal", "data": nominal, "modifiers": [
            {"name": "mu", "type": "normfactor", "data": None},
            {"name": "shared", "type": "normsys", "data": {"hi": 1.3, "lo": 0.9}},
            {"name": "shape", "type": "histosys", "data": {"hi_data": [nominal[0] + 1, nominal[1] + 2], "lo_data": [nominal[0] / 2, nominal[1]]}},
            {"name": "mc_" + name, "type": stat_kind, "data": [0.4, 0.2 if zero_error or name == "CR" else 0.0]}]}
        if not (omitted_cr and name == "CR"):
            operations.append({"op": "add", "path": f"/channels/{index}/samples/0", "value": sample})
    background = {"version": "1.0.0", "channels": channels, "observations": observations,
                  "measurements": [{"name": "M", "config": {"poi": "mu", "parameters": []}}]}
    patchset = {"version": "1.0.0", "metadata": {"analysis_id": "control", "description": "synthetic shape control",
        "references": {"hepdata": "synthetic"}, "labels": ["mass"], "digests": {"sha256": published.canonical_background_digest(background)}},
        "patches": [{"metadata": {"name": "point", "values": [200]}, "patch": operations}]}
    background_raw, patchset_raw = json.dumps(background).encode(), json.dumps(patchset).encode()
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, raw in (("background.json", background_raw), ("patchset.json", patchset_raw)):
            member = tarfile.TarInfo(name); member.size = len(raw); stream.addfile(member, io.BytesIO(raw))
    document = source_document(archive, background_raw, patchset_raw, {"mass": 200})
    return published.load_published_model(document), document


def supplied(source, tmp_path):
    template = templates.identity_template(source, "new-template")
    evidence = tmp_path / "prediction-evidence.json"
    evidence.write_text('{"description":"synthetic supplied-prediction control"}')
    for channel in template["channels"]:
        for sample in channel["samples"]:
            sample["provenance"] = {"kind": "supplied_prediction", "description": "Synthetic all-region prediction with explicit absolute variations",
                                    "evidence": [_pin(evidence)], "normalization_shape": "source_decomposition"}
            errors = next(m["data"] for m in sample["modifiers"] if m["type"] in ("staterror", "shapesys"))
            sample["mc_stat"] = {"mode": "supplied", "description": "Nonnegative-weight MC with supplied moments",
                                 "weight_model": "nonnegative", "sumw": deepcopy(sample["data"]), "sumw2": [e * e for e in errors]}
    return template


def scalar_histosys(alpha, nominal, high, low):
    """Independent code4p polynomial, evaluated without a pyhf interpolator."""
    up, down = high - nominal, nominal - low
    if alpha >= 1:
        return alpha * up
    if alpha <= -1:
        return alpha * down
    return alpha * (up + down) / 2 + (up - down) / 16 * (15 * alpha**2 - 10 * alpha**4 + 3 * alpha**6)


def scalar_normsys(alpha, high, low):
    """Solve the six endpoint value/derivative conditions independently."""
    if alpha >= 1:
        return high**alpha
    if alpha <= -1:
        return low**(-alpha)
    matrix, target = [], []
    for endpoint, factor, sign in ((1, high, 1), (-1, low, -1)):
        log_slope = sign * math.log(factor)
        for derivative in range(3):
            matrix.append([0 if power < derivative else math.prod(range(power - derivative + 1, power + 1)) * endpoint**(power - derivative)
                           for power in range(1, 7)])
            target.append(factor * log_slope**derivative - (1 if derivative == 0 else 0))
    coefficients = np.linalg.solve(matrix, target)
    return 1 + sum(c * alpha**power for power, c in enumerate(coefficients, 1))


def direct_prediction(workspace, model, pars):
    """Sum original sample coordinates with all source modifiers retained."""
    channels = {channel["name"]: channel for channel in workspace["channels"]}
    values = []
    for name in model.config.channels:
        channel = channels[name]
        for bin_index in range(len(channel["samples"][0]["data"])):
            total = 0.0
            for sample in channel["samples"]:
                nominal = sample["data"][bin_index]
                additive, multiplicative = nominal, 1.0
                for modifier in sample["modifiers"]:
                    kind, data = modifier["type"], modifier["data"]
                    part = model.config.par_map[modifier["name"]]["slice"]
                    parameter = pars[part]
                    if kind == "histosys":
                        additive += scalar_histosys(parameter[0], nominal, data["hi_data"][bin_index], data["lo_data"][bin_index])
                    elif kind == "normsys":
                        multiplicative *= scalar_normsys(parameter[0], data["hi"], data["lo"])
                    elif kind in ("staterror", "shapesys", "shapefactor"):
                        index = bin_index if len(parameter) == len(sample["data"]) else model.config.channel_slices[name].start + bin_index
                        multiplicative *= parameter[index]
                    elif kind in ("normfactor", "lumi"):
                        multiplicative *= parameter[0]
                    else:
                        raise AssertionError(kind)
                total += additive * multiplicative
            values.append(total)
    return np.asarray(values)


def direct_logpdf(workspace, model, pars, data):
    expected = direct_prediction(workspace, model, pars)
    value = sum(n * math.log(mean) - mean - math.lgamma(n + 1) for n, mean in zip(data[:model.config.nmaindata], expected))
    offset = model.config.nmaindata
    for name in model.config.auxdata_order:
        pset = model.config.param_set(name)
        means = np.asarray(pars[model.config.par_map[name]["slice"]])
        observed = data[offset:offset + len(pset.auxdata)]
        offset += len(pset.auxdata)
        if pset.pdf_type == "normal":
            sigmas = getattr(pset, "sigmas", [1.0] * len(means))
            value += sum(-0.5 * ((n - mean) / sigma)**2 - math.log(sigma * math.sqrt(2 * math.pi)) for n, mean, sigma in zip(observed, means, sigmas))
        else:
            value += sum(n * math.log(mean * factor) - mean * factor - math.lgamma(n + 1) for n, mean, factor in zip(observed, means, pset.factors))
    return value


def test_identity_preserves_all_channels_and_distinct_template_identity(tmp_path):
    source, _ = fixture(tmp_path)
    template = templates.identity_template(source, "identity-control")
    contract = templates.build_signal_template(source, template)
    assert contract.manifest()['quantity'] == {'weight_convention': 'signed'}
    assert contract.workspace_json == source.workspace_json
    assert contract.manifest()["template_compact_sha256"] != source.manifest()["workspace_compact_sha256"]
    assert contract.manifest()["source_contract"] == source.manifest()
    contract.workspace()["channels"][0]["samples"][0]["data"][0] = 99
    assert contract.workspace()["channels"][0]["samples"][0]["data"][0] == 4


def test_changed_all_region_prediction_is_consumed_without_scaling(tmp_path):
    pytest.importorskip("pyhf")
    source, _ = fixture(tmp_path)
    template = supplied(source, tmp_path)
    for index, channel in enumerate(template["channels"]):
        sample = channel["samples"][0]
        sample["data"] = [3.0 + index, 0.5 + index]
        sample["modifiers"][1]["data"] = {"hi": 1.08 + index * 0.01, "lo": 0.7}
        sample["modifiers"][2]["data"] = {"hi_data": [6.0 + index, 2.0 + index], "lo_data": [0.2 + index, 0.1 + index]}
        sample["modifiers"][-1]["data"] = [0.3, 0.1]
        sample["mc_stat"]["sumw"] = deepcopy(sample["data"])
        sample["mc_stat"]["sumw2"] = [0.09, 0.01]
    contract = templates.build_signal_template(source, template)
    import jsonpatch
    assert jsonpatch.apply_patch(source.workspace(), contract.patch()) == contract.workspace()
    assert contract.manifest()["workspace_compact_sha256"] != source.manifest()["workspace_compact_sha256"]
    for index, channel in enumerate(contract.workspace()["channels"]):
        assert channel["samples"][0]["data"] == [3.0 + index, 0.5 + index]
        assert channel["samples"][0]["modifiers"][2]["data"]["hi_data"] == [6.0 + index, 2.0 + index]
        assert channel["samples"][1:] == source.workspace()["channels"][index]["samples"][1:]
    assert contract.workspace()["observations"] == source.workspace()["observations"]
    assert contract.workspace()["measurements"] == source.workspace()["measurements"]
    model, data, _ = templates.compile_signal_template(contract)
    pars = np.asarray(model.config.suggested_init(), dtype=float)
    pars[model.config.par_map["shape"]["slice"]] = 0.35
    assert model.expected_actualdata(pars) == pytest.approx(direct_prediction(contract.workspace(), model, pars), rel=1e-11)
    assert float(model.logpdf(pars, data)[0]) == pytest.approx(direct_logpdf(contract.workspace(), model, pars, data), abs=1e-10)


@pytest.mark.parametrize("alpha", [-1.4, -1, -0.35, 0, 0.35, 1, 1.4])
def test_asymmetric_absolute_shapes_zero_bin_and_joint_density(tmp_path, alpha):
    pytest.importorskip("pyhf")
    source, _ = fixture(tmp_path)
    contract = templates.build_signal_template(source, supplied(source, tmp_path))
    model, data, compiled = templates.compile_signal_template(contract)
    pars = np.asarray(model.config.suggested_init(), dtype=float)
    pars[model.config.poi_index] = 1.7
    # Negative extrapolation with a zero nominal and positive high anchor gives
    # a negative signal component. Use the negative points for normsys alone.
    pars[model.config.par_map["shape"]["slice"]] = max(alpha, -1)
    pars[model.config.par_map["shared"]["slice"]] = alpha
    assert model.expected_actualdata(pars) == pytest.approx(direct_prediction(contract.workspace(), model, pars), rel=1e-11, abs=1e-11)
    assert float(model.logpdf(pars, data)[0]) == pytest.approx(direct_logpdf(contract.workspace(), model, pars, data), abs=1e-10)
    assert compiled["constraints"]["shared"]["n_parameters"] == 1
    if alpha == 0.35:
        assert scalar_normsys(alpha, 1.3, 0.9) != pytest.approx(1.3**alpha, abs=1e-4)
        signal = model.expected_actualdata(pars) - direct_prediction(contract.workspace(), model, np.where(np.arange(len(pars)) == model.config.poi_index, 0, pars))
        assert signal[model.config.channel_slices["SR"].start + 1] > 0


def test_free_and_conditional_optimizer_agree_with_direct_density(tmp_path):
    pyhf = pytest.importorskip("pyhf")
    from scipy.optimize import minimize
    source, _ = fixture(tmp_path)
    contract = templates.build_signal_template(source, supplied(source, tmp_path))
    model, data, _ = templates.compile_signal_template(contract)
    original_backend, original_optimizer = pyhf.get_backend()
    try:
        pyhf.set_backend("numpy", pyhf.optimize.scipy_optimizer(tolerance=1e-9))
        for mu in (None, 0.7):
            actual = pyhf.infer.mle.fit(data, model) if mu is None else pyhf.infer.mle.fixed_poi_fit(mu, data, model)
            initial = np.asarray(model.config.suggested_init(), dtype=float)
            fixed = list(model.config.suggested_fixed())
            if mu is not None:
                initial[model.config.poi_index] = mu; fixed[model.config.poi_index] = True
            free = [i for i, flag in enumerate(fixed) if not flag]
            def objective(values):
                pars = initial.copy(); pars[free] = values
                return -2 * direct_logpdf(contract.workspace(), model, pars, data)
            result = minimize(objective, initial[free], bounds=[model.config.suggested_bounds()[i] for i in free], method="SLSQP", options={"ftol": 1e-9, "maxiter": 1000})
            assert result.success, result.message
            assert float(pyhf.infer.mle.twice_nll(actual, data, model)[0]) == pytest.approx(result.fun, abs=2e-6)
    finally:
        pyhf.set_backend(original_backend, original_optimizer)


@pytest.mark.parametrize("fault,match", [
    ("missing_cr", "every fitted"), ("duplicate_channel", "duplicate template channel"),
    ("negative", "nonnegative"), ("nan", "nonnegative"), ("missing_modifier", "modifier identities"),
    ("renamed_shared", "shared nuisance"), ("wrong_interpolation", "interpolation"),
    ("missing_evidence", "byte-bound"), ("false_identity", "official sample"),
    ("changed_stat_preserved", "finite-MC"), ("signed_mc", "signed/cancelling"),
    ("bad_sumw2", "sumw2"), ("zero_variance", "zero/cancelling"),
    ("source_drift", "source workspace"), ("negative_anchor", "nonnegative"),
])
def test_invalid_templates_refused(tmp_path, fault, match):
    source, _ = fixture(tmp_path)
    template = supplied(source, tmp_path)
    sample = template["channels"][0]["samples"][0]
    if fault == "missing_cr": template["channels"].pop()
    elif fault == "duplicate_channel": template["channels"].append(deepcopy(template["channels"][0]))
    elif fault == "negative": sample["data"][0] = -1
    elif fault == "nan": sample["data"][0] = float("nan")
    elif fault == "missing_modifier": sample["modifiers"].pop()
    elif fault == "renamed_shared": sample["modifiers"][1]["name"] = "independent"
    elif fault == "wrong_interpolation": template["modifier_settings"]["histosys"]["interpcode"] = "code0"
    elif fault == "missing_evidence": sample["provenance"]["evidence"] = []
    elif fault == "false_identity": sample["provenance"]["kind"] = "source_identity"; sample["data"][0] = 5
    elif fault == "changed_stat_preserved": sample["mc_stat"] = {"mode": "source_preserved", "description": "invalid stale MC"}; sample["data"][0] = 5
    elif fault == "signed_mc": sample["mc_stat"]["weight_model"] = "signed"
    elif fault == "bad_sumw2": sample["mc_stat"]["sumw2"][0] = 99
    elif fault == "zero_variance": sample["modifiers"][-1]["data"][1] = 1; sample["mc_stat"]["sumw2"][1] = 1
    elif fault == "source_drift": template["source_workspace_sha256"] = "0" * 64
    elif fault == "negative_anchor": sample["modifiers"][2]["data"]["lo_data"][0] = -1
    with pytest.raises(ValueError, match=match): templates.build_signal_template(source, template)


def test_absent_source_channel_is_unknown_not_zero(tmp_path):
    source, _ = fixture(tmp_path, omitted_cr=True)
    template = templates.identity_template(source, "absent-is-not-zero")
    contract = templates.build_signal_template(source, template)
    assert contract.manifest()["complete_signal_prediction"] is False
    assert contract.manifest()["uncovered_channels"] == ["CR"]
    assert contract.workspace_json == source.workspace_json
    template["channels"][0]["samples"][0]["provenance"]["kind"] = "supplied_prediction"
    evidence = tmp_path / "prediction.json"; evidence.write_text("{}")
    template["channels"][0]["samples"][0]["provenance"]["evidence"] = [_pin(evidence)]
    with pytest.raises(ValueError, match="identity witnesses only"):
        templates.build_signal_template(source, template)
    template["channels"][0]["samples"][0]["provenance"]["kind"] = "source_identity"
    del template["channels"][1]["source_absent"]
    with pytest.raises(ValueError, match="explicit signal sample"):
        templates.build_signal_template(source, template)


def test_shared_normalization_shape_double_counting_refused(tmp_path):
    source, document = fixture(tmp_path)
    workspace = source.workspace()
    # Source-published paired name is valid; supplied full absolute rate and
    # another nontrivial rate modifier for it must declare a real decomposition.
    patch = source.patch()
    for op in patch: op["value"]["modifiers"][2]["name"] = "shared"
    # Construct this source using the same exact-source loader, not a fake contract.
    with tarfile.open(document["archive"]["path"]) as archive:
        background_raw = archive.extractfile("background.json").read()
        patchset = json.load(archive.extractfile("patchset.json"))
    patchset["patches"][0]["patch"] = patch
    patchset_raw = json.dumps(patchset).encode()
    archive_path = tmp_path / "paired.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, raw in (("background.json", background_raw), ("patchset.json", patchset_raw)):
            member = tarfile.TarInfo(name); member.size = len(raw); archive.addfile(member, io.BytesIO(raw))
    source = published.load_published_model(source_document(archive_path, background_raw, patchset_raw, {"mass": 200}))
    templates.build_signal_template(source, templates.identity_template(source, "exact-paired-control"))
    with pytest.raises(ValueError, match="double-counts"):
        templates.build_signal_template(source, supplied(source, tmp_path))
    neutral_rate = supplied(source, tmp_path)
    for channel in neutral_rate["channels"]:
        next(m for m in channel["samples"][0]["modifiers"] if m["type"] == "normsys")["data"] = {"hi": 1, "lo": 1}
    # A neutral rate factor does not double-count a full absolute shape anchor.
    templates.build_signal_template(source, neutral_rate)


def test_positive_shapesys_error_at_zero_nominal_refused(tmp_path):
    source, _ = fixture(tmp_path, shape_stat=True)
    template = templates.identity_template(source, "invalid-zero-stat")
    sample = template["channels"][0]["samples"][0]
    sample["modifiers"][-1]["data"][1] = 0.5
    # Explicitly supplying moments must still refuse an unrepresentable bin.
    template = supplied(source, tmp_path)
    sample = template["channels"][0]["samples"][0]
    sample["modifiers"][-1]["data"][1] = 0.5
    sample["mc_stat"]["sumw2"][1] = 0.25
    with pytest.raises(ValueError, match="zero/cancelling"):
        templates.build_signal_template(source, template)


def test_zero_mc_pool_uncertainty_refused_even_for_published_identity(tmp_path):
    source, _ = fixture(tmp_path, zero_error=True)
    # An independently source-loaded pathological source remains inadmissible.
    with pytest.raises(ValueError, match="zero pooled nominal"):
        templates.build_signal_template(source, templates.identity_template(source, "pathological-zero-pool"))


def test_shared_staterror_keeps_original_pooled_uncertainty(tmp_path):
    pytest.importorskip("pyhf")
    source, _ = fixture(tmp_path, shared_stat=True)
    contract = templates.build_signal_template(source, templates.identity_template(source, "shared-stat-control"))
    _, _, compiled = templates.compile_signal_template(contract)
    assert compiled["constraints"]["mc_SR"]["sigmas"] == pytest.approx([math.sqrt(0.4**2 + 1.2**2) / 16, 0.4 / 8])


def test_bound_bridge_input_inventory_and_byte_drift(tmp_path):
    source, source_input = fixture(tmp_path)
    source_path = tmp_path / "published.json"; source_path.write_text(json.dumps(source_input))
    template_path = tmp_path / "template.json"; template_path.write_text(json.dumps(supplied(source, tmp_path)))
    bridge = {"schema_version": 1, "published_model": _pin(source_path), "template": _pin(template_path)}
    bridge_path = tmp_path / "bridge.json"; bridge_path.write_text(json.dumps(bridge))
    inventory = templates.inputs({"input": str(bridge_path)}, tmp_path)
    assert {source_path, template_path, bridge_path, tmp_path / "source.tar.gz", tmp_path / "prediction-evidence.json"} <= set(inventory)
    assert templates.load_signal_template(bridge).workspace_json == source.workspace_json
    template_path.write_text(template_path.read_text() + " ")
    with pytest.raises(ValueError, match="source bytes differ"):
        templates.load_signal_template(bridge)


@pytest.mark.parametrize("resolved", [True, False])
def test_adapter_fits_constructed_model_and_retains_failed_receipts(tmp_path, monkeypatch, resolved):
    pytest.importorskip("pyhf")
    from ravel.physics import pyhf_exclude as engine
    source, document = fixture(tmp_path)
    source_path = tmp_path / "published.json"; source_path.write_text(json.dumps(document))
    template_path = tmp_path / "template.json"; template_path.write_text(json.dumps(supplied(source, tmp_path)))
    bridge_path = tmp_path / "bridge.json"
    bridge_path.write_text(json.dumps({"schema_version": 1, "published_model": _pin(source_path), "template": _pin(template_path)}))
    def compute(model, data, **kwargs):
        assert model.config.channels == ["CR", "SR"]
        assert kwargs["profile_witness_context"]["contract"]["template_id"] == "new-template"
        kwargs["diagnostic_record"]["test_probe"] = True
        kwargs["profile_witness_record"]["retained"] = True
        return {"limit_status": {"observed": "resolved" if resolved else "unresolved", "expected": ["resolved"] * 5}}
    monkeypatch.setattr(engine, "compute", compute)
    out = tmp_path / "outputs"
    result = templates.run({"input": str(bridge_path)}, tmp_path, out)
    assert result["status"] == ("passed" if resolved else "failed")
    assert result["physics_validated"] is False
    assert json.loads((out / "signal_template_workspace.json").read_text()) == source.workspace()
    assert json.loads((out / "profile_witnesses.json").read_text()) == {"retained": True}
    assert (out / ("exclusion.json" if resolved else "inference_failure.json")).is_file()
    with pytest.raises(ValueError, match="must be empty"):
        templates.run({"input": str(bridge_path)}, tmp_path, out)


def test_adapter_refuses_incomplete_published_identity_prediction(tmp_path):
    source, document = fixture(tmp_path, omitted_cr=True)
    source_path = tmp_path / "published.json"; source_path.write_text(json.dumps(document))
    template_path = tmp_path / "template.json"; template_path.write_text(json.dumps(templates.identity_template(source, "incomplete-identity")))
    bridge_path = tmp_path / "bridge.json"
    bridge_path.write_text(json.dumps({"schema_version": 1, "published_model": _pin(source_path), "template": _pin(template_path)}))
    with pytest.raises(ValueError, match="complete SR/CR predictions"):
        templates.run({"input": str(bridge_path)}, tmp_path, tmp_path / "outputs")
    assert not (tmp_path / "outputs").exists()


def test_compile_operation_preserves_incomplete_identity_without_fitting(tmp_path, monkeypatch):
    pytest.importorskip("pyhf")
    from ravel.physics import pyhf_exclude as engine
    source, document = fixture(tmp_path, omitted_cr=True)
    source_path = tmp_path / "published.json"; source_path.write_text(json.dumps(document))
    template_path = tmp_path / "template.json"; template_path.write_text(json.dumps(templates.identity_template(source, "incomplete-compile-control")))
    bridge_path = tmp_path / "bridge.json"
    bridge_path.write_text(json.dumps({"schema_version": 1, "published_model": _pin(source_path), "template": _pin(template_path)}))
    def no_fit(*args, **kwargs):
        pytest.fail("compile operation must not invoke inference")
    monkeypatch.setattr(engine, "compute", no_fit)
    out = tmp_path / "outputs"
    result = templates.run({"input": str(bridge_path), "operation": "compile"}, tmp_path, out)
    assert result["status"] == "passed" and result["physics_validated"] is False
    assert result["numerical_inference"] is False and result["complete_signal_prediction"] is False
    assert json.loads((out / "signal_template_workspace.json").read_text()) == source.workspace()
    assert (out / "signal_template_compiled.json").is_file()
    assert not (out / "exclusion.json").exists()
    assert not (out / "profile_witnesses.json").exists()
    with pytest.raises(ValueError, match="compile or inference"):
        templates.validate({"input": str(bridge_path), "operation": "fit-without-approval"})


def local_input(variable):
    """A local input named by an environment variable, or None. RAVEL_STAU_LIKELIHOODS: the official
    byte-pinned stau likelihood archive; RAVEL_SLEPTON_PATCH_INPUT: the official slepton patch input."""
    value = os.environ.get(variable)
    return Path(value) if value else None


@pytest.mark.parametrize("point", [(100, 1), (400, 40)])
def test_official_stau_all_five_channels_modifiers_and_independent_density(point):
    pytest.importorskip("pyhf")
    archive_path = local_input("RAVEL_STAU_LIKELIHOODS")
    if archive_path is None or not archive_path.is_file():
        pytest.skip("set RAVEL_STAU_LIKELIHOODS to the official byte-pinned stau likelihood archive")
    with tarfile.open(archive_path) as archive:
        background_raw = archive.extractfile("Region-combined/BkgOnly.json").read()
        patchset_raw = archive.extractfile("Region-combined/patchset.json").read()
    document = source_document(archive_path, background_raw, patchset_raw, {"mst": point[0], "mn2": point[1]},
        members={"background": "Region-combined/BkgOnly.json", "patchset": "Region-combined/patchset.json"},
        source={"record_id": "ins1567", "version": 2, "resource_id": "1406212",
                "record_url": "https://www.hepdata.net/record/ins1567?version=2",
                "archive_url": "https://www.hepdata.net/record/resource/2008?view=true", "doi": "10.17182/hepdata.107.v2"})
    source = published.load_published_model(document)
    contract = templates.build_signal_template(source, templates.identity_template(source, f"official-{point[0]}-{point[1]}-control"))
    model, data, compiled = templates.compile_signal_template(contract)
    official_model, official_data, official_compiled = published.compile_published_model(source)
    assert contract.workspace_json == source.workspace_json
    assert compiled["constraints"] == official_compiled["constraints"]
    assert data == official_data
    assert set(compiled["channel_order"]) == {"QCR1cut_cuts", "QCR2cut_cuts", "SR1cut_cuts", "SR2cut_cuts", "WCRcut_cuts"}
    assert all(row["nominal"][0] > 0 for row in contract.manifest()["signal"])
    assert {kind for row in contract.manifest()["signal"] for _, kind in row["modifier_name_types"]} == {"lumi", "staterror", "normfactor", "normsys", "histosys"}
    for alpha in (-1, -0.35, 0, 0.35, 1):
        pars = np.asarray(model.config.suggested_init(), dtype=float)
        pars[model.config.poi_index] = 1.3
        pars[model.config.par_map["PRW_DATASF"]["slice"]] = alpha
        assert model.expected_actualdata(pars) == pytest.approx(direct_prediction(contract.workspace(), model, pars), rel=1e-11, abs=1e-10)
        assert model.expected_actualdata(pars) == pytest.approx(official_model.expected_actualdata(pars), rel=1e-12)
        assert float(model.logpdf(pars, data)[0]) == pytest.approx(direct_logpdf(contract.workspace(), model, pars, data), abs=1e-8)


def test_official_slepton_nontrivial_signal_histosys_original_density():
    pytest.importorskip("pyhf")
    input_path = local_input("RAVEL_SLEPTON_PATCH_INPUT")
    if input_path is None or not input_path.is_file():
        pytest.skip("set RAVEL_SLEPTON_PATCH_INPUT to the official slepton patch input")
    document = json.loads(input_path.read_text())
    document["coordinates"] = {"chirality": "degenerate", "mL": 60, "mN1": 59.5}
    source = published.load_published_model(document, input_path.parent)
    contract = templates.build_signal_template(source, templates.identity_template(source, "official-slepton-60-59p5-shape-control"))
    assert contract.workspace_json == source.workspace_json
    assert contract.manifest()["complete_signal_prediction"] is False
    assert contract.manifest()["uncovered_channels"]
    model, data, _ = templates.compile_signal_template(contract)
    nontrivial = [(op["value"], m) for op in source.patch() for m in op["value"]["modifiers"]
                  if m["type"] == "histosys" and (m["data"]["hi_data"] != op["value"]["data"] or m["data"]["lo_data"] != op["value"]["data"])]
    assert nontrivial
    _, variation = nontrivial[0]
    for alpha in (-1, -0.35, 0, 0.35, 1):
        pars = np.asarray(model.config.suggested_init(), dtype=float)
        pars[model.config.poi_index] = 1.3
        pars[model.config.par_map[variation["name"]]["slice"]] = alpha
        assert model.expected_actualdata(pars) == pytest.approx(direct_prediction(contract.workspace(), model, pars), rel=1e-10, abs=1e-10)
        assert float(model.logpdf(pars, data)[0]) == pytest.approx(direct_logpdf(contract.workspace(), model, pars, data), abs=1e-8)
    sample, variation = nontrivial[0]
    assert scalar_histosys(0.35, sample["data"][0], variation["data"]["hi_data"][0], variation["data"]["lo_data"][0]) != pytest.approx(
        0.35 * (variation["data"]["hi_data"][0] - sample["data"][0]), abs=1e-8)
