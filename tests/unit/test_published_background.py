from copy import deepcopy
import math

import numpy as np
import pyhf
import pytest

from ravel.physics.published_background import BackgroundAuxBlock, inspect_workspace


def workspace(pooled=False):
    channels = []
    for name in ("SR", "CR"):
        stat = "mc_" + name
        channels.append({"name": name, "samples": [
            {"name": "signal", "data": [5.], "modifiers": [
                {"name": "mu", "type": "normfactor", "data": None},
                {"name": "alpha", "type": "normsys", "data": {"hi": 1.2, "lo": .8}},
                {"name": stat if pooled else "sig_" + stat, "type": "staterror", "data": [1.]}]},
            {"name": "background", "data": [10.], "modifiers": [
                {"name": "beta", "type": "normfactor", "data": None},
                {"name": "alpha", "type": "normsys", "data": {"hi": 1.1, "lo": .9}},
                {"name": stat, "type": "staterror", "data": [2.]},
                {"name": "poisson_" + name, "type": "shapesys", "data": [.5]}]}]})
    return {"channels": channels, "observations": [{"name": n, "data": [14]} for n in ("SR", "CR")],
            "measurements": [{"name": "M", "config": {"poi": "mu", "parameters": []}}], "version": "1.0.0"}


def construct(pooled=False):
    w = workspace(pooled)
    mapping = {"SR": ["signal"], "CR": ["signal"]}
    bg = inspect_workspace(w, mapping)["background_projection"] if pooled else None
    return BackgroundAuxBlock(w, mapping, measurement="M", model_id="synthetic-reconstruction-v1",
        policy="rebuild_background_mc_from_source" if pooled else "separable_signal_mc", background_source=bg)


@pytest.mark.parametrize("pooled", [False, True])
def test_source_shared_response_constraint_retained_once_and_positive_cr_signal(pooled):
    block = construct(pooled)
    p = block.initial_point()
    c = block.contract()
    assert sum(row["name"] == "alpha" for row in c["retained_auxiliaries"]) == 1
    signal = {"background_contract_sha256": block.contract_sha256, "source_point": p,
              "means": [5, 5], "provenance": "Explicit conditional synthetic point"}
    r = block.join(p, signal, mu=2)
    assert r["main_means"] == [20, 20]
    assert r["signal_means"][block.channel_slices["CR"][0]] == 5
    expected_main = 2 * (14 * math.log(20) - 20 - math.lgamma(15))
    assert r["main_logpdf"] == pytest.approx(expected_main, abs=1e-13)


def test_separable_policy_refuses_pooled_mc_and_does_not_silently_drop_background_constraint():
    with pytest.raises(ValueError, match="pooled"):
        BackgroundAuxBlock(workspace(True), {"SR": ["signal"], "CR": ["signal"]},
            measurement="M", policy="separable_signal_mc", model_id="refused")


def test_rebuild_changes_pooled_sigma_explicitly_to_published_background_width():
    block = construct(True)
    c = block.contract()
    assert c["reconstructed_pooled_mc_names"] == ["mc_CR", "mc_SR"]
    assert c["original_patched_auxiliary_equivalence"] is False
    assert c["removed_signal_mc_parameters"] == []
    for row in c["original_replaced_auxiliaries"]:
        assert row["sigma"] == pytest.approx(math.sqrt(5) / 15)
    for row in c["replacement_background_auxiliaries"]:
        assert row["sigma"] == pytest.approx(.2)


def test_exact_background_bytes_semantics_cannot_be_changed_during_rebuild():
    w = workspace(True)
    bg = inspect_workspace(w, {"SR": ["signal"], "CR": ["signal"]})["background_projection"]
    bg["channels"][0]["samples"][0]["data"][0] = 10.1
    with pytest.raises(ValueError, match="exact published background"):
        BackgroundAuxBlock(w, {"SR": ["signal"], "CR": ["signal"]}, measurement="M",
            policy="rebuild_background_mc_from_source", model_id="refused", background_source=bg)


@pytest.mark.parametrize("pooled", [False, True])
def test_all_retained_auxiliary_density_matches_independent_normal_and_poisson_products(pooled):
    block = construct(pooled)
    p = block.initial_point()
    p["alpha"] = 1.
    p["beta"] = 1.1
    for name in p:
        if name.startswith("mc_") or name.startswith("poisson_"):
            p[name] = 1.07
    c = block.contract()
    observations = [r["observed"] + (.15 if r["pdf"] == "normal" else 1) for r in c["retained_auxiliaries"]]
    from scipy.stats import norm, poisson
    expected = sum(norm.logpdf(y, p[r["coordinate"]], r["sigma"]) if r["pdf"] == "normal"
                   else poisson.logpmf(y, r["factor"] * p[r["coordinate"]])
                   for r, y in zip(c["retained_auxiliaries"], observations))
    assert block.auxiliary_logpdf(p, observations) == pytest.approx(expected, abs=1e-12)
    # Shared alpha affects the background through its one source coordinate.
    assert block.background_means(p) == pytest.approx([10 * 1.1 * 1.1 * 1.07 ** 2] * 2)


def test_rebuilt_auxiliaries_match_background_only_pyhf_at_nontrivial_point():
    block = construct(True)
    p = block.initial_point()
    p["alpha"] = -.7
    p["beta"] = .9
    for name in p:
        if name.startswith("mc_") or name.startswith("poisson_"):
            p[name] = .92
    w = workspace(True)
    bg = inspect_workspace(w, {"SR": ["signal"], "CR": ["signal"]})["background_projection"]
    source = pyhf.Workspace(bg)
    from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS
    model = source.model(measurement_name="M", poi_name=None, modifier_settings=MODIFIER_SETTINGS)
    vector = np.asarray([p[n] for n in model.config.par_names])
    expected = float(np.asarray(model.constraint_logpdf(np.asarray(model.config.auxdata), vector)).reshape(-1)[0])
    assert block.auxiliary_logpdf(p) == pytest.approx(expected, abs=2e-12)
    assert block.background_means(p) == pytest.approx(model.expected_actualdata(vector).tolist())


def test_retained_auxiliary_draw_uses_same_fixed_truth_and_exact_factor_law():
    block = construct(True)
    p = block.initial_point()
    a, b = np.random.default_rng(413), np.random.default_rng(413)
    expected = [float(b.normal(p[r["coordinate"]], r["sigma"])) if r["pdf"] == "normal"
                else int(b.poisson(r["factor"] * p[r["coordinate"]])) for r in block.contract()["retained_auxiliaries"]]
    assert block.draw_auxiliary(p, a) == expected


@pytest.mark.parametrize("fault", ["missing_coordinate", "changed_point", "changed_binding", "missing_cr", "negative_signal", "negative_mu"])
def test_join_refuses_unknown_or_physically_invalid_signal_custody(fault):
    block = construct()
    p = block.initial_point()
    signal = {"background_contract_sha256": block.contract_sha256, "source_point": deepcopy(p),
              "means": [1, 2], "provenance": "synthetic"}
    mu = 1
    if fault == "missing_coordinate":
        del p["alpha"]
        signal["source_point"] = deepcopy(p)
    elif fault == "changed_point": signal["source_point"]["alpha"] = .2
    elif fault == "changed_binding": signal["background_contract_sha256"] = "0" * 64
    elif fault == "missing_cr": signal["means"] = [1]
    elif fault == "negative_signal": signal["means"] = [-1, 2]
    else: mu = -1
    with pytest.raises(ValueError): block.join(p, signal, mu=mu)


def test_source_and_returned_contract_mutations_cannot_rewrite_compiled_block():
    w = workspace()
    block = BackgroundAuxBlock(w, {"SR": ["signal"], "CR": ["signal"]},
        measurement="M", policy="separable_signal_mc", model_id="stable")
    w["channels"][0]["samples"][1]["data"][0] = 1e5
    c = block.contract()
    c["retained_auxiliaries"][0]["sigma"] = 99
    assert block.background_means(block.initial_point()) == [10, 10]
    assert block.contract()["retained_auxiliaries"][0]["sigma"] != 99


def test_zero_background_mc_uncertainty_retains_fixed_parameter_after_rebuild():
    w = workspace(True)
    for channel in w["channels"]:
        for modifier in channel["samples"][1]["modifiers"]:
            if modifier["type"] == "staterror":
                modifier["data"] = [0.]
    mapping = {"SR": ["signal"], "CR": ["signal"]}
    bg = inspect_workspace(w, mapping)["background_projection"]
    block = BackgroundAuxBlock(w, mapping, measurement="M", model_id="zero-background-error",
        policy="rebuild_background_mc_from_source", background_source=bg)
    domains = block.contract()["active_parameter_domains"]
    assert domains["mc_SR[0]"]["fixed"] is True
    point = block.initial_point()
    point["mc_SR[0]"] = 1.01
    with pytest.raises(ValueError, match="fixed"):
        block.background_means(point)


def test_declared_unscaled_signal_cannot_leak_into_background_at_zero_poi():
    w = workspace()
    w["channels"][0]["samples"].append({"name": "unscaled", "data": [3.], "modifiers": []})
    with pytest.raises(ValueError, match="every declared signal sample"):
        BackgroundAuxBlock(w, {"SR": ["signal", "unscaled"], "CR": ["signal"]},
            measurement="M", policy="separable_signal_mc", model_id="refused-unscaled")


def test_rebuild_refuses_textually_equal_coordinate_with_changed_channel_meaning():
    w = workspace(True)
    for channel in w["channels"]:
        for sample in channel["samples"]:
            sample["modifiers"] = [m for m in sample["modifiers"] if m["type"] != "staterror"]
        channel["samples"][1]["modifiers"].append({"name": "pooled", "type": "staterror", "data": [2.]})
        if channel["name"] == "CR":
            # This sample is a second signal in CR, a background in SR.
            # Original pooled[0] refers to CR; after removal it refers to SR.
            channel["samples"][1]["modifiers"].append({"name": "mu", "type": "normfactor", "data": None})
            channel["samples"].append({"name": "other_background", "data": [10.], "modifiers": []})
    mapping = {"SR": ["signal"], "CR": ["signal", "background"]}
    bg = inspect_workspace(w, mapping)["background_projection"]
    with pytest.raises(ValueError, match="channel/bin support changed"):
        BackgroundAuxBlock(w, mapping, measurement="M", model_id="refused-reindexed",
            policy="rebuild_background_mc_from_source", background_source=bg)


@pytest.mark.parametrize("zero", ["main", "auxiliary"])
def test_zero_probability_boundary_is_explicit_and_strict_json_safe(zero):
    import json
    block = construct()
    p = block.initial_point()
    if zero == "main":
        p["beta"] = 0
    else:
        w = workspace()
        w["measurements"][0]["config"]["parameters"] = [{"name": "poisson_SR", "bounds": [[0, 10]]}]
        block = BackgroundAuxBlock(w, {"SR": ["signal"], "CR": ["signal"]},
            measurement="M", policy="separable_signal_mc", model_id="zero-poisson-boundary")
        p = block.initial_point()
        p["poisson_SR[0]"] = 0
    signal = {"background_contract_sha256": block.contract_sha256, "source_point": p,
              "means": [0, 0], "provenance": "Boundary control"}
    result = block.join(p, signal, mu=0, observations=[0, 0]) if zero == "auxiliary" else block.join(p, signal, mu=0)
    if zero == "main":
        assert result["finite"] is False and result["zero_probability"] is True
        assert result["main_logpdf"] is result["logpdf_before_new_mc_auxiliary"] is None
    else:
        assert result["finite"] is False and result["zero_probability"] is True
        assert result["source_auxiliary_logpdf"] is result["logpdf_before_new_mc_auxiliary"] is None
    json.dumps(result, allow_nan=False)
