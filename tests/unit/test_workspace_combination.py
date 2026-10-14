import copy
import math

import pytest

from ravel.physics import workspace_combination as join


def component(name, background, signal, kind):
    modifier = ({"name": "theta", "type": "histosys", "data": {"hi_data": [background*1.2], "lo_data": [background*.8]}}
                if kind == "histosys" else {"name": "theta", "type": "normsys", "data": {"hi": 1.2, "lo": .8}})
    workspace = {"version": "1.0.0", "channels": [{"name": name, "samples": [
        {"name": "background", "data": [background], "modifiers": [modifier]},
        {"name": "signal", "data": [signal], "modifiers": [{"name": "mu", "type": "normfactor", "data": None}]}]}],
        "observations": [{"name": name, "data": [13 if name == "a" else 24]}],
        "measurements": [{"name": "source", "config": {"poi": "mu", "parameters": []}}]}
    return {"id": name, "workspace": workspace, "measurement": "source", "parameter_map": {"theta": "common", "mu": "mu"}}


def inputs():
    return [component("a", 10., 3., "histosys"), component("b", 20., 2., "normsys")], {
        "measurement": "combined", "poi": "mu", "shared_parameters": {"mu": ["a", "b"], "common": ["a", "b"]},
        "independence": "Closed synthetic fixture: two distinct Poisson observations."}


@pytest.mark.parametrize("theta", [0., 1., -1.])
def test_mixed_modifier_one_shared_auxiliary_matches_independent_density(theta):
    import pyhf
    components, policy = inputs()
    before = copy.deepcopy(components)
    result = join.combine(components, policy)
    assert components == before
    assert result["report"]["auxiliary_terms"] == 1
    ws = pyhf.Workspace(result["workspace"])
    model = ws.model(measurement_name="combined")
    pars = model.config.suggested_init()
    pars[model.config.par_map["mu"]["slice"].start] = .7
    pars[model.config.par_map["common"]["slice"].start] = theta
    expected_means = [10*(1+.2*theta)+.7*3, 20*(1+.2*theta)+.7*2]
    expected = sum(n*math.log(mean)-mean-math.lgamma(n+1) for n, mean in zip([13, 24], expected_means))
    expected += -.5*(theta*theta+math.log(2*math.pi))
    assert float(model.logpdf(pars, ws.data(model))[0]) == pytest.approx(expected, abs=1e-12)


def test_explicit_separate_nuisances_produce_two_auxiliaries():
    components, policy = inputs()
    components[1]["parameter_map"]["theta"] = "other"
    del policy["shared_parameters"]["common"]
    result = join.combine(components, policy)
    assert result["report"]["auxiliary_terms"] == 2


@pytest.mark.parametrize("mutation,match", [
    ("roster", "exact declared"), ("missing_map", "complete exact"),
    ("collision", "merging distinct"), ("channel", "distinct names"),
    ("domain", "law, domain"), ("fixed", "law, domain"),
    ("auxiliary", "law, domain"), ("independence", "independence statement"),
    ("poi", "common POI"), ("extra_map", "complete exact")])
def test_conflicting_source_contracts_refuse(mutation, match):
    components, policy = inputs()
    row = components[1]
    if mutation == "roster": del policy["shared_parameters"]["common"]
    elif mutation == "missing_map": del row["parameter_map"]["theta"]
    elif mutation == "collision": row["parameter_map"]["theta"] = "mu"
    elif mutation == "channel":
        row["workspace"]["channels"][0]["name"] = "a"
        row["workspace"]["observations"][0]["name"] = "a"
    elif mutation == "domain": row["workspace"]["measurements"][0]["config"]["parameters"] = [{"name": "theta", "bounds": [[-4, 4]]}]
    elif mutation == "fixed": row["workspace"]["measurements"][0]["config"]["parameters"] = [{"name": "theta", "fixed": True}]
    elif mutation == "auxiliary": row["workspace"]["measurements"][0]["config"]["parameters"] = [{"name": "theta", "auxdata": [1.]}]
    elif mutation == "independence": policy["independence"] = ""
    elif mutation == "poi": row["parameter_map"]["mu"] = "different_mu"
    elif mutation == "extra_map": row["parameter_map"]["not_in_source"] = "new"
    with pytest.raises(ValueError, match=match): join.combine(components, policy)


def test_shared_vector_requires_explicit_future_coordinate_join():
    components, policy = inputs()
    for row in components:
        modifier = row["workspace"]["channels"][0]["samples"][0]["modifiers"][0]
        modifier.update(type="staterror", data=[2.])
    with pytest.raises(ValueError, match="coordinate identity"):
        join.combine(components, policy)


@pytest.mark.parametrize("bad", [[], [{"name": "b", "data": [24]}]*2,
    [{"name": "unknown", "data": [24]}], [{"name": "b", "data": [24, 1]}],
    [{"name": "b", "data": [-1]}], [{"name": "b", "data": [True]}]])
def test_complete_observation_population_is_mandatory(bad):
    components, policy = inputs()
    components[1]["workspace"]["observations"] = bad
    with pytest.raises(ValueError, match="observation|observed bins"):
        join.combine(components, policy)


def test_invalid_original_lumi_cannot_be_repaired_by_mapping():
    import pyhf
    components, policy = inputs()
    row = components[0]
    row["workspace"]["channels"][0]["samples"][0]["modifiers"][0] = {"name": "not_valid_lumi_name", "type": "lumi", "data": None}
    row["workspace"]["measurements"][0]["config"]["parameters"] = [{"name": "not_valid_lumi_name", "inits": [1.], "bounds": [[.1, 2.]], "auxdata": [1.], "sigmas": [.1]}]
    row["parameter_map"] = {"mu": "mu", "not_valid_lumi_name": "lumi"}
    del policy["shared_parameters"]["common"]
    with pytest.raises(pyhf.exceptions.InvalidSpecification):
        join.combine(components, policy)


def test_unique_vector_renaming_preserves_original_bin_law():
    components, policy = inputs()
    del policy["shared_parameters"]["common"]
    for row in components:
        channel = row["workspace"]["channels"][0]
        for sample in channel["samples"]:
            sample["data"] = sample["data"] + [sample["data"][0]/2]
        channel["samples"][0]["modifiers"][0].update(type="staterror", data=[2., 1.])
        row["workspace"]["observations"][0]["data"] += [7.]
        row["parameter_map"]["theta"] = row["id"] + "_statistics"
    result = join.combine(components, policy)
    assert result["report"]["auxiliary_terms"] == 4
    for row in result["report"]["components"]:
        old = row["source_parameters"]["theta"]
        new = row["parameters"][row["id"] + "_statistics"]
        assert old == new
        assert old["dimension"] == 2 and old["scalar"] is False
        assert row["mapped_source_parameters"] == row["parameters"]
