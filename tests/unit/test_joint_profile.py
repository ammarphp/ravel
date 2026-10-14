"""Small synthetic controls with factorwise exact profile witnesses."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyhf
import pytest
from scipy.optimize import brentq
from scipy.stats import multinomial,norm,poisson

from ravel.physics.joint_likelihood import JointPublishedFiniteMC,compact,response_identity
from ravel.physics.mc_auxiliary import MCAuxiliaryBlock,extract_legacy_mc,prepare
from ravel.physics.joint_profile import JointProfiler
from ravel.physics.published_background import BackgroundAuxBlock,inspect_workspace

pytestmark=pytest.mark.filterwarnings("ignore:jsonschema.RefResolver is deprecated:DeprecationWarning")
from joint_model_fixtures import write_mc,write_legacy
BASE=Path(__file__).resolve().parents[2]
BUDGET={"objective_calls":10000,"gradient_calls":600,"feasibility_lp_calls":16,"stationarity_lp_calls":3,"maxiter":150,"lp_maxiter":1000,"wall_seconds":20.}


def workspace(*,fixed_alpha=False,beta_initial=1.,beta_upper=10.):
    channels=[]
    for name,b in (("SR",10.),("CR",20.)):
        shared={"name":"alpha","type":"normsys","data":{"hi":math.e,"lo":1/math.e}}
        channels.append({"name":name,"samples":[
            {"name":"signal","data":[5.],"modifiers":[{"name":"mu","type":"normfactor","data":None},deepcopy(shared)]},
            {"name":"background","data":[b],"modifiers":[{"name":"beta","type":"normfactor","data":None},deepcopy(shared)]}]})
    return {"version":"1.0.0","channels":channels,"observations":[{"name":"SR","data":[22]},{"name":"CR","data":[28]}],
            "measurements":[{"name":"M","config":{"poi":"mu","parameters":[{"name":"alpha","fixed":fixed_alpha},{"name":"beta","inits":[beta_initial],"bounds":[[0,beta_upper]]}]}}]}


def response(latent,nominal,source_point,configuration,source_data):
    source=source_data[configuration["workspace_id"]]
    modifier=next(m for m in source["channels"][0]["samples"][0]["modifiers"] if m["name"]==configuration["coordinate"])
    # Direct source code4 law; no cached function state or rebuilt pyhf model.
    histogram=[[[[modifier["data"]["lo"]],[1.],[modifier["data"]["hi"]]]]]
    factor=float(pyhf.interpolators.code4(histogram,subscribe=False)(np.array([[source_point[configuration["coordinate"]]]])).reshape(-1)[0])
    return [factor*x for x in nominal]


def construct(tmp_path,*,legacy="fixed-N-LO",fixed_alpha=False,beta_initial=1.,beta_upper=10.,mu_upper=30.):
    output=tmp_path/"mc-only"
    path=write_mc(output,legacy)
    mc=MCAuxiliaryBlock({"input":str(path)},BASE)
    source=workspace(fixed_alpha=fixed_alpha,beta_initial=beta_initial,beta_upper=beta_upper);mapping={"SR":["signal"],"CR":["signal"]}
    background=BackgroundAuxBlock(source,mapping,measurement="M",policy="separable_signal_mc",model_id="synthetic-source")
    source_path=tmp_path/"workspace.json";source_path.write_bytes(compact(source))
    config={"workspace_id":"workspace","coordinate":"alpha"}
    contract={"background_contract_sha256":background.contract_sha256,"source_workspace_sha256":inspect_workspace(source,mapping)["workspace_sha256"],"coordinate_dependencies":["alpha"],
              "implementation_pin":{"path":str(Path(__file__).resolve()),"sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},"callable_identity":response_identity(response),
              "configuration":config,"configuration_sha256":hashlib.sha256(compact(config)).hexdigest(),"source_data_pins":[{"id":"workspace","path":str(source_path),"sha256":hashlib.sha256(source_path.read_bytes()).hexdigest(),"encoding":"json"}],
              "source_workspace_data_id":"workspace","environment_requirements":"reviewed_frozen_transitive_globals_and_dependencies","independence":"supplied_source_and_new_MC_auxiliaries_independent","provenance":"Explicit synthetic source law; no official response claim"}
    permutation=[{"channel":"CR","bin":0,"mc_bin_id":"CR"},{"channel":"SR","bin":0,"mc_bin_id":"SR"}]
    joint=JointPublishedFiniteMC(background,mc,source_workspace=source,signal_samples=mapping,source_bin_map=permutation,response=response,response_contract=contract,model_id="synthetic-profile",main_disposition="replace_conditional_control_with_bound_published_source",base=BASE)
    caps={c["id"]:100. for c in mc.document()["classes"]} if mc.document()["mc_design"]["kind"]=="poisson_groups" else {}
    profiler=JointProfiler(joint,background,mc,mu_domain={"initial":.8,"upper":mu_upper},source_bound_semantics={"alpha":{"lower":"numerical","upper":"numerical"},"beta":{"lower":"physical","upper":"numerical"}},rate_caps=caps)
    return joint,background,mc,profiler


def data():return {"main":[28,22],"source_auxiliary":[0.],"MC_auxiliary":[3,2,5]}


def test_genuine_MC_only_export_and_density_never_reuses_main_fields(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path)
    document=mc.document();ledger=json.loads((tmp_path/"mc-only/mc-ledger.json").read_bytes())
    assert set(document)=={"schema_version","model_id","sources","bins","mc_design","classes","assumptions"}
    assert all(set(b)=={"id","role","source"} for b in document["bins"])
    assert not {"main_bins","main_partition"}&set(ledger)
    assert all("upper" not in c for c in document["classes"])
    latent={"class0":.3,"class1":.2,"class2":.5};point=bg.initial_point();point["alpha"]=1.;point["beta"]=1.2
    result=joint.evaluate(point,latent,mu=2.,main_observations=[28,22],source_auxiliary_observations=[0.],mc_observations=[3,2,5])
    means=[math.e*(24+8),math.e*(12+12)]
    expected=sum(poisson.logpmf([28,22],means))+norm.logpdf(0,1,1)+multinomial.logpmf([3,2,5],10,[.3,.2,.5])
    assert result["joint_logpdf"]==pytest.approx(expected,abs=2e-12)
    assert result["source"]["main_means"]==pytest.approx(means)
    altered=deepcopy(document);altered["bins"][0]["background"]=2
    with pytest.raises(ValueError):prepare(altered)


def test_full_joint_profile_has_factorwise_global_and_mu_zero_witness(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path)
    result=profiler.profile([0.],data=data(),budget_per_fit=BUDGET)
    (tmp_path/"analytic-profile-result.json").write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False))
    assert result["verified"],result
    free=result["global_fit"];zero=result["profiles"][0]["fit"]
    # Each normalized factor simultaneously attains its own maximum: both
    # Poisson means match n, normal mean matches z, and p equals m/N. Their
    # sum therefore attains the global likelihood upper bound independently.
    exact_nll=-sum(poisson.logpmf([28,22],[28,22]))-norm.logpdf(0,0,1)-multinomial.logpmf([3,2,5],10,[.3,.2,.5])
    assert free["nll"]==pytest.approx(exact_nll,abs=2e-8)
    assert free["parameters"]["mu"]==pytest.approx(2.,abs=2e-4)
    assert free["parameters"]["source"]["beta"]==pytest.approx(1.,abs=2e-4)
    assert free["parameters"]["source"]["alpha"]==pytest.approx(0.,abs=2e-4)
    endpoint=free["parameters"]
    evaluated=joint.evaluate(endpoint["source"],endpoint["latent"],mu=endpoint["mu"],main_observations=data()["main"],source_auxiliary_observations=data()["source_auxiliary"],mc_observations=data()["MC_auxiliary"])
    assert evaluated["source"]["signal_means"]==pytest.approx([4.,6.],abs=2e-4)
    assert evaluated["source"]["main_means"]==pytest.approx([28.,22.],abs=2e-4)
    assert zero["parameters"]["source"]["beta"]==pytest.approx(5/3,abs=2e-4)
    expected_lr=2*sum(n*math.log(n/mean)+mean-n for n,mean in zip([28,22],[100/3,50/3]))
    assert result["profiles"][0]["twice_delta_nll"]==pytest.approx(expected_lr,abs=2e-7)
    assert not free["global_optimum_certified"] # the independent test supplies the proof, not the generic solver
    for fit in (free,zero):
        starts=[tuple(a["start_coordinates"]) for a in fit["attempts"]]
        assert len(set(starts))==len(starts)>=2
        assert all(fit["work"]["used"][key]<=fit["work"]["declared"][key] for key in fit["work"]["used"])


def test_conditional_masks_are_not_source_fixed_or_full_joint_profile(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path)
    p={"class0":.3,"class1":.2,"class2":.5}
    result=profiler.fit(fixed_mu=1.,fixed_source={"alpha":0.},fixed_latent=p,data=data(),budget=BUDGET)
    # Independent monotone score equation; only beta is optimized here.
    beta=brentq(lambda b:20*(1-28/(20*b+4))+10*(1-22/(10*b+6)),.001,10.)
    assert result["verified"],result
    assert result["parameters"]["source"]["beta"]==pytest.approx(beta,abs=2e-5)
    assert result["recipe"]["true_fixed_source_coordinates"]==[]
    assert result["recipe"]["conditional_masks"]["source"]=={"alpha":0.}
    assert result["recipe"]["coordinate_order"]==["source:beta"]


def test_complete_mu_one_profile_respects_independent_feasible_point_bound(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path)
    result=profiler.fit(fixed_mu=1.,data=data(),budget=BUDGET)
    (tmp_path/"complete-mu1-profile-result.json").write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False))
    assert result["verified"],result
    # The independent critic derives this code4 factor from endpoint Hermite
    # conditions, without invoking our response or density. A feasible point
    # alpha=.5, beta=.6708640525962742, p=(.3,.2,.5) bounds the COMPLETE
    # profiled NLL; full profiling must improve or match this conditional point.
    factor=1.6487677607274631;beta=.6708640525962742
    feasible_means=[factor*(20*beta+4),factor*(10*beta+6)]
    bound=-sum(poisson.logpmf([28,22],feasible_means))-norm.logpdf(0,.5,1)-multinomial.logpmf([3,2,5],10,[.3,.2,.5])
    global_nll=-sum(poisson.logpmf([28,22],[28,22]))-norm.logpdf(0,0,1)-multinomial.logpmf([3,2,5],10,[.3,.2,.5])
    assert result["nll"]<=bound+1e-7
    assert -1e-7<=2*(result["nll"]-global_nll)<=.3194629734533976+2e-7
    assert result["recipe"]["conditional_masks"]["source"]=={}
    assert result["recipe"]["conditional_masks"]["latent"] is None


def test_genuine_source_fixed_flags_remain_exact(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path,fixed_alpha=True)
    result=profiler.fit(fixed_mu=0.,data=data(),budget=BUDGET)
    assert result["verified"],result
    assert result["parameters"]["source"]["alpha"]==0.
    assert result["recipe"]["true_fixed_source_coordinates"]==["alpha"]
    assert "source:alpha" not in result["recipe"]["coordinate_order"]
    with pytest.raises(ValueError,match="genuine source fixed"):
        profiler.fit(fixed_mu=0.,fixed_source={"alpha":1.},data=data(),budget=BUDGET)


@pytest.mark.parametrize("key",["objective_calls","gradient_calls","feasibility_lp_calls","stationarity_lp_calls"])
def test_work_budget_exhaustion_retains_partial_attempts(tmp_path,key,monkeypatch):
    joint,bg,mc,profiler=construct(tmp_path)
    small=deepcopy(BUDGET);small[key]=1
    if key=="feasibility_lp_calls":
        # The ordinary model obtains two perturbed seeds from a single LP.
        # An actual failed seed target makes a second LP necessary; the budget
        # must stop before it, while preserving that first failed target.
        monkeypatch.setattr("ravel.physics.joint_profile.linprog",lambda *a,**k:SimpleNamespace(success=False,message="deterministic failed seed target",x=None))
    result=profiler.fit(fixed_mu=1.,data=data(),budget=small)
    assert not result["verified"] and result["status"]=="budget_exhausted"
    assert result["work"]["used"][key]<=1
    if key=="feasibility_lp_calls":
        assert any(row["kind"]=="feasibility_LP" and not row["success"] for row in result["start_generation"])
    json.dumps(result,allow_nan=False)


def test_wall_hook_stops_before_work_and_retains_explicit_failure(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path)
    result=profiler.fit(data=data(),budget=BUDGET,wall_hook=lambda:True)
    assert result["status"]=="budget_exhausted" and result["attempts"]==[]
    assert result["work"]["exhaustion"]=="wall_hook"
    assert sum(result["work"]["used"].values())==0


def test_artificial_mu_cap_refuses_a_finite_claim(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path,mu_upper=1.2)
    result=profiler.fit(data=data(),budget=BUDGET)
    assert not result["verified"],result
    assert any(any(row.get("coordinate")=="mu" and not row["physical"] for row in a.get("active_bounds",[])) for a in result["attempts"])


def test_all_selected_zero_MC_refuses_strength_before_optimizer(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path)
    repeated=data();repeated["MC_auxiliary"]=[0,0,10]
    result=profiler.fit(data=repeated,budget=BUDGET)
    assert not result["verified"] and result["status"]=="unresolved_strength_recession"
    assert result["attempts"]==[]
    assert sum(result["work"]["used"].values())==0
    # Zero-selected CR remains an uncertain positive latent probability.
    assert mc.nominal({"class0":.2,"class1":.2,"class2":.6})["signal_expectation"]==[4.,4.]


def test_joint_sampling_repeats_all_three_measurements(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path);latent={"class0":.3,"class1":.2,"class2":.5}
    first=np.random.default_rng(4991);independent=np.random.default_rng(4991)
    point=bg.initial_point();draw=joint.draw_joint_data(point,latent,mu=2.,rng=first)
    assert draw["main"]==independent.poisson([28,22]).tolist()
    assert draw["source_auxiliary"]==[float(independent.normal(0,1))]
    assert draw["MC_auxiliary"]==independent.multinomial(10,[.3,.2,.5]).tolist()
    assert set(draw)=={"main","source_auxiliary","MC_auxiliary","sampling"}
    # The sampling annotation is not a data measurement; pass complete blocks.
    fit_data={key:draw[key] for key in ("main","source_auxiliary","MC_auxiliary")}
    assert sum(fit_data["MC_auxiliary"])==10


def test_MC_only_copied_ordering_and_changed_source_refusal(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path)
    before=mc.class_ids;mc.class_ids.reverse();assert mc.class_ids==before
    with pytest.raises(AttributeError):mc.class_ids=list(reversed(before))
    path=tmp_path/"mc-only/mc-ledger.json";path.write_bytes(path.read_bytes()+b"\n")
    with pytest.raises(ValueError,match="MC-only source changed"):
        mc.nominal({"class0":.3,"class1":.2,"class2":.5})


def test_Poisson_MC_density_has_no_inherited_numerical_rate_cap(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path,legacy="poisson-A")
    point={"class0":200.,"class1":100.}
    assert mc.nominal(point)["signal_expectation"]==[100.,50.]
    assert mc.auxiliary_logpdf(point)==pytest.approx(poisson.logpmf(4,200)+poisson.logpmf(2,100))
    with pytest.raises(ValueError,match="NET expectation"):
        mc.nominal({"class0":1.,"class1":2.})


def test_signed_MC_auxiliary_observation_may_have_negative_net_and_denominator(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path,legacy="fixed-N-signed")
    p={"class0":.4,"class1":.1,"class2":.4,"class3":.1};counts=[1,4,2,3]
    classes=mc.document()["classes"]
    assert sum(c["denominator_mark"]*n for c,n in zip(classes,counts))==-4
    assert sum(c["contribution"][0]*n for c,n in zip(classes,counts))==-3
    assert mc.nominal(p)["expected_denominator"]==pytest.approx(.6)
    assert mc.auxiliary_logpdf(p,counts)==pytest.approx(multinomial.logpmf(counts,10,list(p.values())))
    with pytest.raises(ValueError,match="positive expected signed denominator"):
        mc.nominal({"class0":.2,"class1":.1,"class2":.1,"class3":.6})


@pytest.mark.parametrize("field",["schema_version","class_mark","group_mark","denominator_mark"])
def test_boolean_ledger_fields_cannot_impersonate_numbers(tmp_path,field):
    joint,bg,mc,profiler=construct(tmp_path)
    model_path=tmp_path/"mc-only/mc-model.json";ledger_path=tmp_path/"mc-only/mc-ledger.json"
    ledger=json.loads(ledger_path.read_bytes());document=json.loads(model_path.read_bytes())
    if field=="schema_version":ledger["schema_version"]=True
    elif field=="class_mark":ledger["classes"][0]["contribution"][0]=True
    elif field=="group_mark":ledger["groups"][0]["contribution"][0]=True
    else:ledger["groups"][0]["denominator_mark"]=True
    raw=compact(ledger);ledger_path.write_bytes(raw)
    next(p for p in document["sources"] if p["id"]=="ledger")["sha256"]=hashlib.sha256(raw).hexdigest()
    model_path.write_bytes(compact(document))
    with pytest.raises(ValueError):MCAuxiliaryBlock({"input":str(model_path)},BASE)


def test_MC_only_export_rejects_existing_directory_without_overwrite(tmp_path):
    destination=tmp_path/"occupied";destination.mkdir();sentinel=destination/"sentinel.txt";sentinel.write_text("preserve")
    with pytest.raises(ValueError,match="new output directory"):
        extract_legacy_mc({"input":str(write_legacy(tmp_path/"legacy"))},BASE,destination,model_id="new")
    assert sentinel.read_text()=="preserve" and list(destination.iterdir())==[sentinel]


def test_bounded_model_read_refuses_oversize_file_before_JSON(tmp_path):
    path=tmp_path/"oversize.json"
    with path.open("wb") as stream:stream.truncate(8*1024**2+1)
    with pytest.raises(ValueError,match="8 MiB"):
        MCAuxiliaryBlock({"input":str(path)},BASE)
    with pytest.raises(ValueError,match="8 MiB"):
        extract_legacy_mc({"input":str(path)},BASE,tmp_path/"no-export",model_id="oversize")
    assert not (tmp_path/"no-export").exists()


def test_bounded_source_read_refuses_oversize_pinned_source(tmp_path):
    joint,bg,mc,profiler=construct(tmp_path)
    large=tmp_path/"large-source.bin"
    with large.open("wb") as stream:stream.truncate(8*1024**2+1)
    model=tmp_path/"mc-only/mc-model.json";document=json.loads(model.read_bytes())
    document["sources"].append({"id":"large","path":str(large),"sha256":"0"*64,"reference":"Oversize refusal control"})
    model.write_bytes(compact(document))
    with pytest.raises(ValueError,match="8 MiB"):
        MCAuxiliaryBlock({"input":str(model)},BASE)


def test_aggregate_byte_admission_is_enforced(tmp_path,monkeypatch):
    joint,bg,mc,profiler=construct(tmp_path)
    monkeypatch.setattr("ravel.physics.mc_auxiliary.MAX_TOTAL_BYTES",1)
    with pytest.raises(ValueError,match="aggregate byte ceiling"):
        MCAuxiliaryBlock({"input":str(tmp_path/"mc-only/mc-model.json")},BASE)


def test_extractor_uses_bounded_importer_not_unbounded_legacy_capture(tmp_path,monkeypatch):
    monkeypatch.setattr("ravel.physics.mc_auxiliary.fm._capture",lambda *a,**k:pytest.fail("unbounded legacy capture called"))
    path=extract_legacy_mc({"input":str(write_legacy(tmp_path/"legacy"))},BASE,tmp_path/"bounded-export",model_id="bounded")
    mc=MCAuxiliaryBlock({"input":str(path)},BASE)
    assert mc.contract()["resource_admission"]=={"maximum_file_bytes":8*1024**2,"maximum_total_input_bytes":32*1024**2,"maximum_sources":16}


@pytest.mark.parametrize("strengths",[[float("nan")],[float("inf")],[-1.],[31.],[1.,1.],[True]])
def test_profile_invalid_grid_is_refused_before_any_fit(tmp_path,monkeypatch,strengths):
    joint,bg,mc,profiler=construct(tmp_path)
    monkeypatch.setattr(profiler,"fit",lambda **kwargs:pytest.fail("fit executed before profile grid admission"))
    with pytest.raises(ValueError):
        profiler.profile(strengths,data=data(),budget_per_fit=BUDGET)
