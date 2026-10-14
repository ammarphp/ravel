"""Synthetic source graphs, independent derivatives and exact fit witnesses."""
from copy import deepcopy
import hashlib
import json
import math
from types import SimpleNamespace

import numpy as np
import pyhf
import pytest
from scipy.stats import multinomial, norm, poisson

from ravel.physics.joint_analytic import AnalyticPublishedJoint, AnalyticJointProfiler, _code4, _code4_coefficients, _code4p
from ravel.physics.mc_auxiliary import MCAuxiliaryBlock, compact
from ravel.physics.published_background import BackgroundAuxBlock, inspect_workspace
from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS
from joint_model_fixtures import write_mc

pytestmark = pytest.mark.filterwarnings("ignore:jsonschema.RefResolver is deprecated:DeprecationWarning")
BUDGET = {"objective_calls":10000,"gradient_calls":10000,"feasibility_lp_calls":16,"stationarity_lp_calls":3,"maxiter":200,"lp_maxiter":1000,"wall_seconds":20.}


def workspace(*, extra=0, rich=False, fixed_alpha=False):
    channels = []
    for name, b in (("SR",10.),("CR",20.)):
        shared = {"name":"alpha","type":"normsys","data":{"hi":math.e,"lo":1/math.e}}
        smods = [{"name":"mu","type":"normfactor","data":None},deepcopy(shared)]
        bmods = [{"name":"beta","type":"normfactor","data":None},deepcopy(shared)]
        for i in range(extra):
            modifier = {"name":f"shared{i}","type":"normsys","data":{"hi":1.03+.002*i,"lo":.96-.001*i}}
            smods.append(deepcopy(modifier));bmods.append(deepcopy(modifier))
        if rich:
            # One coordinate affects both additive and multiplicative source
            # terms; source pooled MC remains on background after replacement.
            smods.extend([{"name":"alpha","type":"histosys","data":{"hi_data":[6.],"lo_data":[4.4]}},
                          {"name":"pooled","type":"staterror","data":[.5]},
                          {"name":"lumi","type":"lumi","data":None}])
            bmods.extend([{"name":"alpha","type":"histosys","data":{"hi_data":[b+2.],"lo_data":[b-1.]}},
                          {"name":"pooled","type":"staterror","data":[2.]},
                          {"name":"lumi","type":"lumi","data":None},
                          {"name":"shape_factor","type":"shapefactor","data":None}])
            if name == "CR":
                bmods.append({"name":"MC_CR","type":"shapesys","data":[3.]})
        channels.append({"name":name,"samples":[{"name":"signal","data":[5.],"modifiers":smods},
                                                           {"name":"background","data":[b],"modifiers":bmods}]})
    parameters = [{"name":"alpha","fixed":fixed_alpha},{"name":"beta","inits":[1.],"bounds":[[0.,10.]]}]
    if rich:
        parameters.append({"name":"lumi","auxdata":[1.],"inits":[1.],"bounds":[[.5,1.5]],"sigmas":[.02]})
    return {"version":"1.0.0","channels":channels,"observations":[{"name":"SR","data":[22]},{"name":"CR","data":[28]}],
            "measurements":[{"name":"M","config":{"poi":"mu","parameters":parameters}}]}


def construct(tmp_path, *, extra=0, rich=False, kind="fixed-N-LO", fixed_alpha=False, mu_upper=30., source=None):
    mc = MCAuxiliaryBlock({"input":str(write_mc(tmp_path/"MC",kind))})
    source = workspace(extra=extra,rich=rich,fixed_alpha=fixed_alpha) if source is None else source
    mapping = {"SR":["signal"],"CR":["signal"]}
    bg_source = inspect_workspace(source,mapping)["background_projection"]
    bg = BackgroundAuxBlock(source,mapping,measurement="M",policy="rebuild_background_mc_from_source" if rich else "separable_signal_mc",model_id="synthetic-source",
                            background_source=bg_source if rich else None)
    joint = AnalyticPublishedJoint(bg,mc,source_workspace=source,signal_samples=mapping,
                                    source_bin_map=[{"channel":"CR","bin":0,"mc_bin_id":"CR"},{"channel":"SR","bin":0,"mc_bin_id":"SR"}],
                                    model_id="synthetic-analytic-extension",response_assumptions=["Declared diagonal published-response extension on known fixed marks.","Source and new MC auxiliaries independent; synthetic law only."])
    semantics = {name:{"lower":"physical" if name == "beta" else "numerical","upper":"numerical"} for name in bg.contract()["active_parameter_names"]}
    caps = {name:100. for name in mc.class_ids} if kind == "poisson-A" else {}
    profiler = AnalyticJointProfiler(joint,bg,mc,mu_domain={"initial":min(.8,mu_upper/2),"upper":mu_upper},source_bound_semantics=semantics,rate_caps=caps)
    return joint,bg,mc,profiler,source


def repeated_data():
    return {"main":[28,22],"source_auxiliary":[0.],"MC_auxiliary":[3,2,5]}


def custom_mc(directory, bin_ids, counts, *, kappa):
    """Complete synthetic fixed-N categories, including the unselected class."""
    directory.mkdir()
    total = sum(counts)
    classes,groups = [],[]
    for i,n in enumerate(counts):
        marks = [float(i == j) for j in range(len(bin_ids))]
        ids = [f"c{i}-g{k}" for k in range(n)]
        classes.append({"id":f"c{i}","contribution":marks,"denominator_mark":1.,"exposure":None,"observed":n,"observed_group_ids":ids,"initial":n/total,"source":"ledger"})
        groups.extend({"id":identity,"class_id":f"c{i}","contribution":marks,"denominator_mark":1.} for identity in ids)
    bins = [{"id":name,"role":"control" if name.startswith("CR") else "signal","source":"ledger"} for name in bin_ids]
    design = {"kind":"fixed_n_categories","sampling_law":"iid_fixed_mark_categories","fixed_marks":True,"support_complete":True,"ledger_source":"ledger","independence":"iid_groups_within_one_fixed_N_stream","total_groups":total,"kappa":kappa,"normalization_source":"ledger","normalization_meaning":"Known synthetic inclusive exposure"}
    ledger = {"schema_version":1,"sampling_law":design["sampling_law"],"support_complete":True,"classes":[{key:c[key] for key in ("id","contribution","denominator_mark","exposure")} for c in classes],"groups":groups,
              "normalization":{key:design[key] for key in ("total_groups","kappa","normalization_meaning")},"bins":[{key:b[key] for key in ("id","role")} for b in bins]}
    raw = compact(ledger);(directory/"ledger.json").write_bytes(raw)
    model = {"schema_version":1,"model_id":"synthetic-complete-support","sources":[{"id":"ledger","path":"ledger.json","sha256":hashlib.sha256(raw).hexdigest(),"reference":"Complete synthetic known fixed-mark law"}],"bins":bins,"mc_design":design,"classes":classes,
             "assumptions":["Known IID complete categorical sampling law.","Synthetic controls supply no native generator authority."]}
    path = directory/"model.json";path.write_bytes(compact(model))
    return MCAuxiliaryBlock({"input":str(path)})


@pytest.mark.parametrize("alpha",[-2.,-1.,-.7,0.,.4,1.,2.])
def test_code4_and_code4p_match_pinned_source_and_independent_difference(alpha):
    hi,lo = 1.37,.71
    coefficients = _code4_coefficients(hi,lo)
    value,derivative = _code4(alpha,hi,lo,coefficients)
    official = float(pyhf.interpolators.code4([[[[lo],[1.],[hi]]]],subscribe=False)(np.array([[alpha]])).reshape(-1)[0])
    assert value == pytest.approx(official,abs=2e-14)
    step = 1e-6
    def oracle(a):
        return float(pyhf.interpolators.code4([[[[lo],[1.],[hi]]]],subscribe=False)(np.array([[a]])).reshape(-1)[0])
    assert derivative == pytest.approx((oracle(alpha+step)-oracle(alpha-step))/(2*step),rel=2e-8,abs=1e-9)
    delta,slope = _code4p(alpha,np.array([5.]),np.array([7.]),np.array([4.]))
    def shape(a):
        return float(pyhf.interpolators.code4p([[[[4.],[5.],[7.]]]],subscribe=False)(np.array([[a]])).reshape(-1)[0])
    assert delta[0] == pytest.approx(shape(alpha),abs=2e-14)
    assert slope[0] == pytest.approx((shape(alpha+step)-shape(alpha-step))/(2*step),abs=2e-9)


def test_complete_density_matches_independent_normalized_factors(tmp_path):
    joint,bg,mc,_,_ = construct(tmp_path)
    point = bg.initial_point();point.update(alpha=.4,beta=1.2)
    latent = {"class0":.3,"class1":.2,"class2":.5}
    result = joint.evaluate_with_gradient(point,latent,mu=2.,main_observations=[28,22],source_auxiliary_observations=[.1],mc_observations=[3,2,5])
    factor = float(pyhf.interpolators.code4([[[[1/math.e],[1.],[math.e]]]],subscribe=False)(np.array([[.4]])).reshape(-1)[0])
    means = factor*np.array([24.+8.,12.+12.])
    expected = sum(poisson.logpmf([28,22],means))+norm.logpdf(.1,.4,1)+multinomial.logpmf([3,2,5],10,[.3,.2,.5])
    assert result["joint_logpdf"] == pytest.approx(expected,abs=2e-12)
    assert result["source"]["main_means"] == pytest.approx(means)
    assert len(result["distribution_mean_vector"]) == 2+1+3
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize("kind",["fixed-N-LO","fixed-N-signed","poisson-A"])
def test_dense_shared_graph_complete_analytic_gradient_and_mean_jacobian(tmp_path,kind):
    joint,bg,mc,_,source = construct(tmp_path,extra=10,rich=True,kind=kind)
    point = bg.initial_point();point["alpha"] = .37;point["beta"] = 1.2;point["lumi"] = 1.01
    point["shape_factor[0]"] = .94
    for i in range(10):point[f"shared{i}"] = -.2+.04*i
    latent = {c["id"]:c["initial"] for c in mc.document()["classes"]}
    mu = 1.7
    result = joint.evaluate_with_gradient(point,latent,mu=mu)
    assert len(result["gradient"]) > 8
    assert result["source"]["background_means"] == pytest.approx(bg.background_means(point),rel=3e-14)
    # Independent compiled source signal with only signal MC factors removed.
    stripped = deepcopy(source)
    for channel in stripped["channels"]:
        signal = channel["samples"][0]
        signal["modifiers"] = [m for m in signal["modifiers"] if m["type"] not in {"staterror","shapesys"}]
    compiled = pyhf.Workspace(stripped).model(modifier_settings=MODIFIER_SETTINGS)
    vector = [1. if n == "mu" else point[n] for n in compiled.config.par_names]
    published = compiled.main_model.expected_data(vector,return_by_sample=True)[compiled.config.samples.index("signal")]
    snom = np.array(mc.nominal(latent)["signal_expectation"])[[1,0]]
    assert result["source"]["signal_means"] == pytest.approx(snom*published/5.,rel=3e-14)
    expected = sum(poisson.logpmf(bg._source_data[:2],result["source"]["main_means"]))+bg.auxiliary_logpdf(point)+mc.auxiliary_logpdf(latent)
    assert result["joint_logpdf"] == pytest.approx(expected,abs=2e-11)
    grad = np.array(result["gradient"]);jac = np.array(result["distribution_mean_jacobian"])
    axes = result["coordinate_order"]
    last = mc.class_ids[-1]
    for axis in axes[:-1] if kind != "poisson-A" else axes:
        plus,minus = deepcopy(point),deepcopy(point)
        lp,lm = deepcopy(latent),deepcopy(latent)
        up,um = mu,mu
        direction = np.zeros(len(axes));direction[axes.index(axis)] = 1.
        step = 1e-6
        if axis == "mu":up += step;um -= step
        elif axis.startswith("source:"):
            name = axis.removeprefix("source:");plus[name] += step;minus[name] -= step
        else:
            name = axis.removeprefix("MC:");lp[name] += step;lm[name] -= step
            if kind != "poisson-A":lp[last] -= step;lm[last] += step;direction[axes.index("MC:"+last)] = -1.
        rp = joint.evaluate_with_gradient(plus,lp,mu=up);rm = joint.evaluate_with_gradient(minus,lm,mu=um)
        assert grad@direction == pytest.approx((rp["nll"]-rm["nll"])/(2*step),rel=3e-6,abs=3e-7),axis
        assert jac@direction == pytest.approx((np.array(rp["distribution_mean_vector"])-np.array(rm["distribution_mean_vector"]))/(2*step),rel=3e-7,abs=3e-7),axis
    # Background-only widths are reconstructed, not original pooled widths.
    rows = bg.contract()["replacement_background_auxiliaries"]
    assert sorted(r["sigma"] for r in rows) == pytest.approx([.1,.2])


def test_more_than_eight_free_coordinate_fit_has_exact_saturation_witness(tmp_path):
    joint,bg,mc,profiler,_ = construct(tmp_path,extra=10)
    data = repeated_data();data["source_auxiliary"] = [0.]*11
    result = profiler.fit(data=data,budget=BUDGET)
    assert result["verified"],result
    assert len(result["recipe"]["coordinate_order"]) == 15
    expected = -sum(poisson.logpmf([28,22],[28,22]))-11*norm.logpdf(0,0,1)-multinomial.logpmf([3,2,5],10,[.3,.2,.5])
    assert result["nll"] == pytest.approx(expected,abs=2e-8)
    assert result["parameters"]["mu"] == pytest.approx(2.,abs=3e-4)
    assert result["parameters"]["source"]["beta"] == pytest.approx(1.,abs=3e-4)
    best = min((r for r in result["attempts"] if r["verified"]),key=lambda r:r["nll"])
    assert best["main_means"] == pytest.approx([28.,22.],abs=3e-4)
    assert len({tuple(a["start_coordinates"]) for a in result["attempts"]}) >= 2
    assert not result["global_optimum_certified"]
    json.dumps(result,allow_nan=False)


def test_exact_zero_strength_and_complete_mu_one_profile_bounds(tmp_path):
    _,_,_,profiler,_ = construct(tmp_path)
    result = profiler.profile([0.,1.],data=repeated_data(),budget_per_fit=BUDGET)
    assert result["verified"],result
    assert result["profiles"][0]["fit"]["parameters"]["source"]["beta"] == pytest.approx(5/3,abs=2e-5)
    assert result["profiles"][0]["twice_delta_nll"] == pytest.approx(2.452006730216766,abs=2e-7)
    assert 0 <= result["profiles"][1]["twice_delta_nll"] <= .3194629734533976+2e-7


def test_source_fixed_and_conditional_masks_are_distinct(tmp_path):
    _,bg,_,profiler,_ = construct(tmp_path,fixed_alpha=True)
    result = profiler.fit(fixed_mu=0.,data=repeated_data(),budget=BUDGET)
    assert result["verified"],result
    assert result["parameters"]["source"]["alpha"] == 0.
    assert result["recipe"]["true_fixed_source_coordinates"] == ["alpha"]
    assert "source:alpha" not in result["recipe"]["coordinate_order"]
    with pytest.raises(ValueError,match="genuine source fixed"):
        profiler.fit(fixed_source={"alpha":1.},budget=BUDGET)


def test_zero_mc_rate_has_exact_boundary_score_and_unresolved_recession(tmp_path):
    joint,bg,mc,profiler,_ = construct(tmp_path,kind="poisson-A")
    point = bg.initial_point()
    latent = {"class0":0.,"class1":0.}
    result = joint.evaluate_with_gradient(point,latent,mu=2.,main_observations=[20.,10.],mc_observations=[0,0])
    assert result["gradient"][-2:] == pytest.approx([1.,1.])
    # Valid zero NET boundary, including a negative marked class; no observed
    # arithmetic is clipped. Physical net is checked before total main mean.
    with pytest.raises(ValueError,match="negative.*NET"):
        joint.evaluate_with_gradient(point,{"class0":0.,"class1":1.},mu=0.)
    with pytest.raises(ValueError,match="zero probability"):
        joint.evaluate_with_gradient(point,latent,mu=2.,mc_observations=[1,0])
    data = {"main":[28,22],"source_auxiliary":[0.],"MC_auxiliary":[0,0]}
    refused = profiler.fit(data=data,budget=BUDGET)
    assert refused["status"] == "unresolved_strength_recession"
    assert sum(refused["work"]["used"].values()) == 0


@pytest.mark.parametrize("key",["objective_calls","gradient_calls","feasibility_lp_calls","stationarity_lp_calls"])
def test_analytic_budget_limits_retain_failed_attempts(tmp_path,key,monkeypatch):
    _,_,_,profiler,_ = construct(tmp_path)
    budget = deepcopy(BUDGET);budget[key] = 1
    if key == "feasibility_lp_calls":
        monkeypatch.setattr("ravel.physics.joint_analytic.linprog",lambda *a,**k:SimpleNamespace(success=False,message="failed target",x=None))
    result = profiler.fit(fixed_mu=1.,data=repeated_data(),budget=budget)
    assert result["status"] == "budget_exhausted"
    assert result["work"]["used"][key] <= 1
    assert not result["verified"]
    json.dumps(result,allow_nan=False)


def test_wall_invalid_grid_and_artificial_cap_refuse_without_false_endpoint(tmp_path,monkeypatch):
    _,_,_,profiler,_ = construct(tmp_path,mu_upper=.5)
    result = profiler.fit(data=repeated_data(),budget=BUDGET)
    assert not result["verified"]
    assert any(any(a.get("coordinate") == "mu" and not a["physical"] for a in attempt.get("active_bounds",[])) for attempt in result["attempts"])
    stopped = profiler.fit(data=repeated_data(),budget=BUDGET,wall_hook=lambda:True)
    assert stopped["status"] == "budget_exhausted" and not stopped["attempts"]
    assert sum(stopped["work"]["used"].values()) == 0
    monkeypatch.setattr(profiler,"fit",lambda **k:pytest.fail("invalid grid launched a fit"))
    for grid in ([float("nan")],[1.],[.1,.1]):
        with pytest.raises(ValueError):profiler.profile(grid,budget_per_fit=BUDGET)


def test_source_zero_bin_and_clipping_refusal_and_contract_copies(tmp_path):
    source = workspace();source["channels"][0]["samples"][0]["data"] = [0.]
    with pytest.raises(ValueError,match="zero-bin"):
        construct(tmp_path/"zero",source=source)
    joint,bg,_,_,_ = construct(tmp_path/"good")
    contract = joint.contract();contract["source_bin_map"].reverse()
    assert joint.contract()["source_bin_map"][0]["channel"] == "CR"
    bg._model.main_model.clip_bin_data = 0.
    from ravel.physics.joint_analytic import _SourceGraph
    with pytest.raises(ValueError,match="clipped"):
        _SourceGraph(workspace(),bg,{"CR":["signal"],"SR":["signal"]})


def test_extreme_finite_mu_refuses_overflow_without_warning_or_nonfinite_output(tmp_path):
    joint,bg,mc,_,_ = construct(tmp_path)
    latent = {c["id"]:c["initial"] for c in mc.document()["classes"]}
    with pytest.raises(ValueError,match="overflow"):
        joint.evaluate_with_gradient(bg.initial_point(),latent,mu=1e308)


def test_reference_is_raw_nominal_even_when_source_initials_are_overridden(tmp_path):
    source = workspace()
    source["measurements"][0]["config"]["parameters"][0]["inits"] = [.5]
    source["measurements"][0]["config"]["parameters"].append({"name":"signal_scale","inits":[2.],"bounds":[[0.,5.]]})
    for channel in source["channels"]:
        channel["samples"][0]["modifiers"].append({"name":"signal_scale","type":"normfactor","data":None})
    joint,bg,mc,_,_ = construct(tmp_path,source=source)
    point = bg.initial_point();latent = {c["id"]:c["initial"] for c in mc.document()["classes"]}
    result = joint.evaluate_with_gradient(point,latent,mu=1.)
    compiled = bg._model
    vector = [1. if n == "mu" else point[n] for n in compiled.config.par_names]
    expected = compiled.main_model.expected_data(vector,return_by_sample=True)[compiled.config.samples.index("signal")]
    assert result["source"]["signal_means"] == pytest.approx(np.array(mc.nominal(latent)["signal_expectation"])[[1,0]]*expected/5.)
    assert joint._graph.nominal_signal == pytest.approx([5.,5.])
    # A zero multiplicative coordinate has a nonzero derivative; division by
    # the factor would give 0/0 or silently erase this exact product rule.
    point["signal_scale"] = 0.;point["beta"] = 0.
    zero = joint.evaluate_with_gradient(point,latent,mu=1.,main_observations=[0.,0.])
    assert zero["source"]["main_means"] == [0.,0.]
    gradient = dict(zip(zero["coordinate_order"],zero["gradient"]))
    factor = float(pyhf.interpolators.code4([[[[1/math.e],[1.],[math.e]]]],subscribe=False)(np.array([[.5]])).reshape(-1)[0])
    assert gradient["source:signal_scale"] == pytest.approx(12.*factor)
    assert gradient["source:beta"] == pytest.approx(30.*factor)


def test_source_poisson_auxiliary_zero_count_exact_boundary_derivative(tmp_path):
    source = workspace(rich=True)
    source["measurements"][0]["config"]["parameters"].append({"name":"MC_CR","bounds":[[0.,10.]]})
    joint,bg,mc,_,_ = construct(tmp_path,rich=True,source=source)
    point = bg.initial_point();point["MC_CR[0]"] = 0.
    latent = {c["id"]:c["initial"] for c in mc.document()["classes"]}
    rows = bg.contract()["retained_auxiliaries"]
    aux = [0. if row["pdf"] == "poisson" else row["observed"] for row in rows]
    result = joint.evaluate_with_gradient(point,latent,mu=1.,main_observations=[6.,16.],source_auxiliary_observations=aux)
    gradient = dict(zip(result["coordinate_order"],result["gradient"]))
    factor = next(r["factor"] for r in rows if r["coordinate"] == "MC_CR[0]")
    # CR signal=6; observed6 makes its main score zero. The Poisson source
    # auxiliary at (observed,mean)=(0,0) contributes exactly its factor.
    assert gradient["source:MC_CR[0]"] == pytest.approx(factor)
    epsilon = 1e-7;shifted = deepcopy(point);shifted["MC_CR[0]"] = epsilon
    plus = joint.evaluate_with_gradient(shifted,latent,mu=1.,main_observations=[6.,16.],source_auxiliary_observations=aux)
    assert (plus["nll"]-result["nll"])/epsilon == pytest.approx(factor,rel=2e-6)


def test_vector_coordinate_mapping_across_different_channel_sizes(tmp_path):
    source = workspace(rich=True)
    for channel in source["channels"]:
        n = 3 if channel["name"] == "CR" else 2
        for sample in channel["samples"]:
            nominal = sample["data"][0]
            sample["data"] = [nominal+i for i in range(n)]
            for modifier in sample["modifiers"]:
                if modifier["type"] in {"staterror","shapesys"}:modifier["data"] = [modifier["data"][0]+.1*i for i in range(n)]
                if modifier["type"] == "histosys":
                    modifier["data"] = {key:[modifier["data"][key][0]+i for i in range(n)] for key in ("hi_data","lo_data")}
    source["observations"] = [{"name":"SR","data":[22,24]},{"name":"CR","data":[28,29,30]}]
    mc = custom_mc(tmp_path/"MC",["SR0","SR1","CR0","CR1","CR2"],[2,2,2,2,1,1],kappa=10.)
    mapping = {"SR":["signal"],"CR":["signal"]}
    bg = BackgroundAuxBlock(source,mapping,measurement="M",policy="rebuild_background_mc_from_source",model_id="synthetic-vector",background_source=inspect_workspace(source,mapping)["background_projection"])
    joint = AnalyticPublishedJoint(bg,mc,source_workspace=source,signal_samples=mapping,source_bin_map=[{"channel":c,"bin":i,"mc_bin_id":c+str(i)} for c,n in (("CR",3),("SR",2)) for i in range(n)],model_id="synthetic-vector-extension",response_assumptions=["Declared diagonal source extension.","Independent synthetic source and MC experiments."])
    point = bg.initial_point();point["alpha"] = .31
    for i in range(3):point[f"shape_factor[{i}]"] = .8+.1*i
    for i in range(5):point[f"pooled[{i}]"] = .9+.03*i
    for i in range(3):point[f"MC_CR[{i}]"] = 1.1+.02*i
    latent = {c["id"]:c["initial"] for c in mc.document()["classes"]}
    result = joint.evaluate_with_gradient(point,latent,mu=1.)
    assert result["source"]["background_means"] == pytest.approx(bg.background_means(point),rel=2e-14)
    matrix = np.array(result["distribution_mean_jacobian"])
    for name in [n for n in point if n.startswith(("pooled","MC_CR","shape_factor"))]:
        plus,minus = deepcopy(point),deepcopy(point);step = 1e-6;plus[name] += step;minus[name] -= step
        oracle = (np.array(bg.background_means(plus))-np.array(bg.background_means(minus)))/(2*step)
        assert matrix[:5,result["coordinate_order"].index("source:"+name)] == pytest.approx(oracle,rel=3e-8,abs=2e-8),name


def test_full_125_coordinate_mapping_and_independent_source_density_derivative(tmp_path):
    names = ["SR0","SR1","SR2","SR3","CR0"]
    counts = [10,15,20,5,30,20]
    w,q = [10.,5.,12.,7.,30.],[6.,9.,2.,9.,1.]
    channels = []
    for i,name in enumerate(names):
        shared = [{"name":f"h{k}","type":"normsys","data":{"hi":1.02+.00002*k,"lo":.98-.00001*k}} for k in range(117)]
        channels.append({"name":name,"samples":[{"name":"signal","data":[float(counts[i])],"modifiers":[{"name":"mu","type":"normfactor","data":None}]+deepcopy(shared)},
                                                   {"name":"W","data":[w[i]],"modifiers":[{"name":"beta_W","type":"normfactor","data":None}]+deepcopy(shared)},
                                                   {"name":"Q","data":[q[i]],"modifiers":[{"name":"beta_Q","type":"normfactor","data":None}]+deepcopy(shared)},
                                                   {"name":"other","data":[1.],"modifiers":[]}]})
    source = {"version":"1.0.0","channels":channels,"observations":[{"name":name,"data":[1+w[i]+q[i]+2*counts[i]]} for i,name in enumerate(names)],"measurements":[{"name":"M","config":{"poi":"mu","parameters":[]}}]}
    mc = custom_mc(tmp_path/"MC",names,counts,kappa=100.)
    mapping = {name:["signal"] for name in names}
    bg = BackgroundAuxBlock(source,mapping,measurement="M",policy="separable_signal_mc",model_id="synthetic-119-source")
    joint = AnalyticPublishedJoint(bg,mc,source_workspace=source,signal_samples=mapping,source_bin_map=[{"channel":name,"bin":0,"mc_bin_id":name} for name in sorted(names)],model_id="synthetic-125-join",response_assumptions=["Complete known synthetic fixed-mark law.","Independent diagonal published response extension, not a native stau law."])
    point = bg.initial_point();point.update(beta_W=1.2,beta_Q=.8)
    for k in range(117):point[f"h{k}"] = .05*math.sin(k+1)
    latent = {c["id"]:c["initial"] for c in mc.document()["classes"]}
    result = joint.evaluate_with_gradient(point,latent,mu=1.7)
    assert len(point) == 119 and len(bg.contract()["retained_auxiliaries"]) == 117
    assert len(result["gradient"]) == 126 # includes complete final category before tangent elimination
    model = bg._model;vector = [1.7 if n == "mu" else point[n] for n in model.config.par_names]
    expected = float(model.logpdf(vector,bg._source_data)[0])+multinomial.logpmf(counts,100,[n/100 for n in counts])
    assert result["joint_logpdf"] == pytest.approx(expected,abs=3e-11)
    direction = np.array([math.cos(i+1)/10 for i in range(len(vector))]);epsilon = 2e-6
    independent = -float(model.logpdf(np.array(vector)+epsilon*direction,bg._source_data)[0])+float(model.logpdf(np.array(vector)-epsilon*direction,bg._source_data)[0])
    analytic = sum(result["gradient"][result["coordinate_order"].index("mu" if n == "mu" else "source:"+n)]*d for n,d in zip(model.config.par_names,direction))
    assert analytic == pytest.approx(independent/(2*epsilon),rel=3e-7,abs=3e-7)
    semantics = {name:{"lower":"physical" if name.startswith("beta") else "numerical","upper":"numerical"} for name in point}
    profiler = AnalyticJointProfiler(joint,bg,mc,mu_domain={"initial":.8,"upper":30.},source_bound_semantics=semantics,rate_caps={})
    budget = deepcopy(BUDGET);budget["gradient_calls"] = 1
    refusal = profiler.fit(budget=budget)
    assert len(refusal["recipe"]["coordinate_order"]) == 125
    assert refusal["status"] == "budget_exhausted" and refusal["work"]["used"]["gradient_calls"] == 1
    assert refusal["attempts"] == [] # no full-size optimizer was launched


@pytest.mark.parametrize("field,value",[("main",[28]),("main",[float("nan"),22]),("main",[-1,22]),("main",[True,22]),
                                       ("source_auxiliary",[]),("source_auxiliary",[float("inf")]),("MC_auxiliary",[3,2,4])])
def test_complete_repeated_data_is_admitted_before_objective_gradient_or_lp(tmp_path,field,value,monkeypatch):
    joint,_,_,profiler,_ = construct(tmp_path)
    data = repeated_data();data[field] = value
    monkeypatch.setattr(joint,"evaluate_with_gradient",lambda *a,**k:pytest.fail("invalid data evaluated density"))
    monkeypatch.setattr(joint,"physical_constraints",lambda *a,**k:pytest.fail("invalid data evaluated constraints"))
    monkeypatch.setattr("ravel.physics.joint_analytic.linprog",lambda *a,**k:pytest.fail("invalid data launched LP"))
    with pytest.raises(ValueError):profiler.fit(data=data,budget=BUDGET)
    with pytest.raises(ValueError):profiler.profile([0.],data=data,budget_per_fit=BUDGET)


def test_negative_source_poisson_data_is_admitted_before_work(tmp_path,monkeypatch):
    joint,bg,mc,profiler,_ = construct(tmp_path,rich=True)
    data = {"main":[28,22],"source_auxiliary":[row["observed"] for row in bg.contract()["retained_auxiliaries"]],"MC_auxiliary":mc.counts()}
    poisson_index = next(i for i,r in enumerate(bg.contract()["retained_auxiliaries"]) if r["pdf"] == "poisson")
    data["source_auxiliary"][poisson_index] = -1.
    monkeypatch.setattr("ravel.physics.joint_analytic.linprog",lambda *a,**k:pytest.fail("invalid Poisson auxiliary launched LP"))
    with pytest.raises(ValueError,match="negative Poisson"):
        profiler.fit(data=data,budget=BUDGET)


@pytest.mark.parametrize("kind",["fixed-N-LO","fixed-N-signed","poisson-A"])
def test_complete_sampler_repeats_known_seed_stream_at_fixed_truth(tmp_path,kind):
    joint,bg,mc,_,_ = construct(tmp_path,rich=True,kind=kind)
    point = bg.initial_point();point["alpha"] = .4;point["beta"] = 1.2;point["lumi"] = 1.01
    latent = {c["id"]:c["initial"] for c in mc.document()["classes"]}
    before = deepcopy((point,latent));seed = 9314
    sample = joint.draw_joint_data(point,latent,mu=1.7,rng=np.random.default_rng(seed))
    expected_rng = np.random.default_rng(seed)
    evaluated = joint.evaluate_with_gradient(point,latent,mu=1.7)
    expected = {"main":expected_rng.poisson(evaluated["source"]["main_means"]).tolist(),
                "source_auxiliary":[float(expected_rng.normal(point[r["coordinate"]],r["sigma"])) if r["pdf"] == "normal" else int(expected_rng.poisson(r["factor"]*point[r["coordinate"]])) for r in bg.contract()["retained_auxiliaries"]]}
    if kind == "poisson-A":expected["MC_auxiliary"] = expected_rng.poisson([c["exposure"]*latent[c["id"]] for c in mc.document()["classes"]]).tolist()
    else:expected["MC_auxiliary"] = expected_rng.multinomial(10,[latent[name] for name in mc.class_ids]).tolist()
    assert sample == expected
    assert (point,latent) == before
    assert set(sample) == {"main","source_auxiliary","MC_auxiliary"}
    assert all(type(n) is int for n in sample["main"]+sample["MC_auxiliary"])
    if kind != "poisson-A":assert sum(sample["MC_auxiliary"]) == 10
    joint.evaluate_with_gradient(point,latent,mu=1.7,main_observations=sample["main"],source_auxiliary_observations=sample["source_auxiliary"],mc_observations=sample["MC_auxiliary"])
    json.dumps(sample,allow_nan=False)


def test_sampler_zero_source_and_mc_expectations_do_not_require_old_data_probability(tmp_path):
    source = workspace(rich=True)
    source["measurements"][0]["config"]["parameters"].append({"name":"MC_CR","bounds":[[0.,10.]]})
    joint,bg,mc,_,_ = construct(tmp_path,rich=True,source=source)
    point = bg.initial_point();point.update(beta=0.);point["MC_CR[0]"] = 0.
    latent = {"class0":0.,"class1":0.,"class2":1.}
    with pytest.raises(ValueError,match="zero probability"):
        joint.evaluate_with_gradient(point,latent,mu=2.)
    result = joint.draw_joint_data(point,latent,mu=2.,rng=np.random.default_rng(711))
    assert result["main"] == [0,0] and result["MC_auxiliary"] == [0,0,10]
    index = next(i for i,r in enumerate(bg.contract()["retained_auxiliaries"]) if r["coordinate"] == "MC_CR[0]")
    assert result["source_auxiliary"][index] == 0
    repeated = joint.evaluate_with_gradient(point,latent,mu=2.,main_observations=result["main"],source_auxiliary_observations=result["source_auxiliary"],mc_observations=result["MC_auxiliary"])
    assert repeated["finite"]


def test_alternate_supported_pyhf_interpolations_are_explicitly_refused(tmp_path,monkeypatch):
    from ravel.physics import pyhf_exclude
    source = workspace(rich=True);mapping = {"SR":["signal"],"CR":["signal"]}
    monkeypatch.setattr(pyhf_exclude,"MODIFIER_SETTINGS",{"histosys":{"interpcode":"code0"},"normsys":{"interpcode":"code1"}})
    bg = BackgroundAuxBlock(source,mapping,measurement="M",policy="rebuild_background_mc_from_source",model_id="alternate-source",background_source=inspect_workspace(source,mapping)["background_projection"])
    mc = MCAuxiliaryBlock({"input":str(write_mc(tmp_path/"MC"))})
    with pytest.raises(ValueError,match="exact code4p/code4"):
        AnalyticPublishedJoint(bg,mc,source_workspace=source,signal_samples=mapping,source_bin_map=[{"channel":"CR","bin":0,"mc_bin_id":"CR"},{"channel":"SR","bin":0,"mc_bin_id":"SR"}],model_id="must-refuse",response_assumptions=["Explicit response extension.","Independent MC and source."])


def test_compiler_interpolator_identity_is_checked_beyond_declared_settings(tmp_path):
    joint,bg,_,_,_ = construct(tmp_path,rich=True)
    bg._model.main_model.modifiers_appliers["normsys"].interpolator = pyhf.interpolators.code1([[[[.9],[1.],[1.1]]]],subscribe=False)
    from ravel.physics.joint_analytic import _SourceGraph
    with pytest.raises(ValueError,match="compiled source interpolation"):
        _SourceGraph(workspace(rich=True),bg,{"CR":["signal"],"SR":["signal"]})
