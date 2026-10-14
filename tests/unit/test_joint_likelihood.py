"""Synthetic joined-density and sampling controls; no fits or real data."""
from copy import deepcopy
from functools import partial
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pyhf
import pytest
from scipy.stats import multinomial,norm,poisson

from ravel.physics.published_background import BackgroundAuxBlock,inspect_workspace
from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS
from ravel.physics.joint_likelihood import JointPublishedFiniteMC,compact,response_identity
from ravel.physics.mc_auxiliary import MCAuxiliaryBlock
from joint_model_fixtures import write_mc


pytestmark=pytest.mark.filterwarnings("ignore:jsonschema.RefResolver is deprecated:DeprecationWarning")


BASE=Path(__file__).resolve().parents[2]


def workspace():
    channels=[]
    for name,background in (("SR",10.),("CR",20.)):
        channels.append({"name":name,"samples":[
            {"name":"signal","data":[5.],"modifiers":[{"name":"mu","type":"normfactor","data":None},
                {"name":"alpha","type":"normsys","data":{"hi":1.2,"lo":.8}},
                {"name":"mc_"+name,"type":"staterror","data":[1.]}]},
            {"name":"background","data":[background],"modifiers":[
                {"name":"alpha","type":"normsys","data":{"hi":1.1,"lo":.9}},
                {"name":"mc_"+name,"type":"staterror","data":[2.]},
                {"name":"poisson_"+name,"type":"shapesys","data":[1.]}]}]})
    return {"version":"1.0.0","channels":channels,
            "observations":[{"name":"SR","data":[11]},{"name":"CR","data":[14]}],
            "measurements":[{"name":"M","config":{"poi":"mu","parameters":[]}}]}


def synthetic_response(latent,nominal,source_point,configuration,source_data):
    """Stateless synthetic normsys law using explicit pinned inputs.

    Original signal MC coordinates stay at one. The published response is a
    declared same-model synthetic law, not uncertainty borrowed for real stau.
    """
    model=pyhf.Workspace(source_data[configuration["workspace_data_id"]]).model(measurement_name=configuration["measurement"],modifier_settings=configuration["modifier_settings"])
    vector=model.config.suggested_init()
    vector[model.config.par_map["alpha"]["slice"].start]=source_point["alpha"]
    vector[model.config.poi_index]=1.
    with_signal=model.expected_actualdata(vector)
    vector[model.config.poi_index]=0.
    factors=(with_signal-model.expected_actualdata(vector))/configuration["source_signal_nominal"]
    return [nominal[0]*float(factors[1])*configuration["signal_scale"],nominal[1]*float(factors[0])*configuration["signal_scale"]]


def alternate_response(latent,nominal,source_point,configuration,source_data):
    return [2*x for x in nominal]


def defaults_response(latent,nominal,source_point,configuration,source_data=None):
    return nominal


def input_mutating_response(latent,nominal,source_point,configuration,source_data):
    values=list(nominal)
    latent.clear();nominal.clear();source_point.clear()
    configuration["signal_scale"]=999.
    source_data["workspace"].clear()
    return values


def runtime_mutating_response(latent,nominal,source_point,configuration,source_data):
    runtime_mutating_response.changed=True
    return nominal


class StatefulResponse:
    def __init__(self):
        self.scale=2
    def evaluate(self,latent,nominal,source_point,configuration,source_data):
        return [self.scale*x for x in nominal]
    def __call__(self,latent,nominal,source_point,configuration,source_data):
        return self.evaluate(latent,nominal,source_point,configuration,source_data)


def configuration():
    return {"measurement":"M","modifier_settings":deepcopy(MODIFIER_SETTINGS),"workspace_data_id":"workspace","source_signal_nominal":5.,"signal_scale":1.}


def construct(tmp_path,*,fault=None,response_override=None,configuration_override=None,source_path=None,identity_override=None,implementation_path=None):
    source=workspace();mapping={"SR":["signal"],"CR":["signal"]}
    background=inspect_workspace(source,mapping)["background_projection"]
    block=BackgroundAuxBlock(source,mapping,measurement="M",policy="rebuild_background_mc_from_source",model_id="synthetic-background-join",background_source=background)
    mc=MCAuxiliaryBlock({"input":str(write_mc(tmp_path/"MC"))},BASE)
    response=synthetic_response if response_override is None else response_override
    config=configuration() if configuration_override is None else configuration_override
    workspace_path=tmp_path/"response-workspace.json" if source_path is None else source_path
    if source_path is None:workspace_path.write_bytes(compact(source))
    implementation=Path(__file__).resolve() if implementation_path is None else implementation_path
    response_contract={"background_contract_sha256":block.contract_sha256,"source_workspace_sha256":hashlib.sha256(compact(source)).hexdigest(),
        "coordinate_dependencies":["alpha"],"implementation_pin":{"path":str(implementation),"sha256":hashlib.sha256(implementation.read_bytes()).hexdigest()},
        "callable_identity":response_identity(synthetic_response) if identity_override is None else identity_override,"configuration":config,"configuration_sha256":hashlib.sha256(compact(config)).hexdigest(),
        "source_data_pins":[{"id":"workspace","path":str(workspace_path),"sha256":hashlib.sha256(workspace_path.read_bytes()).hexdigest(),"encoding":"json"}],
        "source_workspace_data_id":"workspace","environment_requirements":"reviewed_frozen_transitive_globals_and_dependencies",
        "independence":"supplied_source_and_new_MC_auxiliaries_independent","provenance":"Explicit independent synthetic response source law; developer control only"}
    permutation=[{"channel":"CR","bin":0,"mc_bin_id":"CR"},{"channel":"SR","bin":0,"mc_bin_id":"SR"}]
    if fault=="missing_response":response_contract["coordinate_dependencies"]=[]
    if fault=="old_MC_in_response":response_contract["coordinate_dependencies"].append("mc_SR[0]")
    if fault=="bad_binding":response_contract["background_contract_sha256"]="0"*64
    if fault=="bad_permutation":permutation[0]["mc_bin_id"]="SR"
    if fault=="unknown_independence":response_contract["independence"]="unknown"
    if fault=="configuration_hash":response_contract["configuration_sha256"]="0"*64
    if fault=="missing_source_data":response_contract["source_data_pins"]=[]
    if fault=="source_data_hash":response_contract["source_data_pins"][0]["sha256"]="0"*64
    if fault=="unknown_environment":response_contract["environment_requirements"]="unreviewed_live_globals"
    joint=JointPublishedFiniteMC(block,mc,source_workspace=source,signal_samples=mapping,source_bin_map=permutation,
        response=response,response_contract=response_contract,model_id="synthetic-joint-new-MC",
        main_disposition="replace_conditional_control_with_bound_published_source",base=BASE)
    return joint,block,mc


def test_complete_join_matches_independent_products_with_bin_permutation(tmp_path):
    joint,bg,mc=construct(tmp_path);point=bg.initial_point();point["alpha"]=1.
    point["mc_CR[0]"]=1.1
    latent={"class0":.2,"class1":.4,"class2":.4}
    result=joint.evaluate(point,latent,mu=2.)
    assert result["source"]["signal_means"]==pytest.approx([9.6,4.8],abs=1e-12)
    means=[20*1.1*1.1+2*9.6,10*1.1+2*4.8]
    assert result["source"]["main_means"]==pytest.approx(means)
    aux=sum(float(norm.logpdf(row["observed"],point[row["coordinate"]],row["sigma"])) if row["pdf"]=="normal"
            else float(poisson.logpmf(row["observed"],row["factor"]*point[row["coordinate"]])) for row in bg.contract()["retained_auxiliaries"])
    expected=float(sum(poisson.logpmf([14,11],means)))+aux+float(multinomial.logpmf([3,3,4],10,[.2,.4,.4]))
    assert result["joint_logpdf"]==pytest.approx(expected,abs=2e-12)
    assert not result["physics_validated"] and not result["numerical_inference"]
    assert sum(row["name"]=="alpha" for row in bg.contract()["retained_auxiliaries"])==1
    assert joint.contract()["MC"]["schema"]=="MC-only-v1"
    (tmp_path/"joined-unit-contract.json").write_text(json.dumps(joint.contract(),indent=2,sort_keys=True,allow_nan=False)+"\n")
    (tmp_path/"joined-unit-density.json").write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")


def test_rebuilt_background_MC_does_not_multiply_the_new_signal_again(tmp_path):
    joint,bg,mc=construct(tmp_path);point=bg.initial_point();latent={"class0":.3,"class1":.3,"class2":.4}
    first=joint.evaluate(point,latent,mu=1.)
    point["mc_SR[0]"]=1.3
    second=joint.evaluate(point,latent,mu=1.)
    assert first["source"]["signal_means"]==second["source"]["signal_means"]
    assert second["source"]["background_means"][1]==pytest.approx(1.3*first["source"]["background_means"][1])


def test_complete_joint_fixed_truth_sampling_repeats_both_auxiliary_experiments(tmp_path):
    joint,bg,mc=construct(tmp_path);point=bg.initial_point();latent={"class0":.2,"class1":.4,"class2":.4}
    rng=np.random.default_rng(392);independent=np.random.default_rng(392)
    data=joint.draw_joint_data(point,latent,mu=1.,rng=rng)
    assert data["main"]==independent.poisson([28.,14.]).tolist()
    expected_aux=[float(independent.normal(point[row["coordinate"]],row["sigma"])) if row["pdf"]=="normal"
                  else int(independent.poisson(row["factor"]*point[row["coordinate"]])) for row in bg.contract()["retained_auxiliaries"]]
    assert data["source_auxiliary"]==expected_aux
    assert data["MC_auxiliary"]==independent.multinomial(10,[.2,.4,.4]).tolist()
    assert sum(data["MC_auxiliary"])==10
    json.dumps(data,allow_nan=False)
    (tmp_path/"joined-unit-data.json").write_text(json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+"\n")


@pytest.mark.parametrize("fault",["missing_response","old_MC_in_response","bad_binding","bad_permutation","unknown_independence",
                                 "configuration_hash","missing_source_data","source_data_hash","unknown_environment"])
def test_unknown_response_sampling_or_ordering_is_refused(tmp_path,fault):
    with pytest.raises(ValueError):
        construct(tmp_path,fault=fault)


def test_zero_probability_new_MC_observation_remains_JSON_safe(tmp_path):
    joint,bg,mc=construct(tmp_path);latent={"class0":0.,"class1":.4,"class2":.6}
    result=joint.evaluate(bg.initial_point(),latent,mu=1.)
    assert not result["finite"] and result["zero_probability"] and result["joint_logpdf"] is None
    assert result["source"]["signal_means"][1]==0.
    json.dumps(result,allow_nan=False)


def test_MC_public_ordering_and_contract_are_copies_with_no_reassignment(tmp_path):
    joint,bg,mc=construct(tmp_path);latent={"class0":.2,"class1":.4,"class2":.4};point=bg.initial_point()
    baseline=joint.evaluate(point,latent,mu=1.)
    draw=joint.draw_joint_data(point,latent,mu=1.,rng=np.random.default_rng(41))
    original_bins=mc.bin_ids;original_classes=mc.class_ids
    mc.bin_ids.reverse();mc.class_ids.reverse()
    contract=mc.contract()["document"];contract["bins"].reverse();contract["classes"].reverse()
    joint.contract()["source_bin_map"].reverse()
    assert mc.bin_ids==original_bins and mc.class_ids==original_classes
    for attribute in ("bin_ids","class_ids"):
        with pytest.raises(AttributeError):
            setattr(mc,attribute,list(reversed(getattr(mc,attribute))))
    with pytest.raises(AttributeError):
        joint.contract_sha256="0"*64
    assert joint.evaluate(point,latent,mu=1.)==baseline
    assert joint.draw_joint_data(point,latent,mu=1.,rng=np.random.default_rng(41))==draw


def test_two_module_functions_in_same_file_do_not_share_a_callable_identity(tmp_path):
    assert Path(synthetic_response.__code__.co_filename)==Path(alternate_response.__code__.co_filename)
    assert response_identity(synthetic_response)!=response_identity(alternate_response)
    with pytest.raises(ValueError,match="module/qualified name/code identity"):
        construct(tmp_path,response_override=alternate_response)


@pytest.mark.parametrize("response",[StatefulResponse(),StatefulResponse().evaluate,
                                    partial(synthetic_response),defaults_response])
def test_dynamic_callable_or_default_state_is_refused(tmp_path,response):
    with pytest.raises(ValueError,match="pure module function"):
        construct(tmp_path,response_override=response)


def test_closure_and_nested_function_are_refused(tmp_path):
    scale=2.
    def closure(latent,nominal,source_point,configuration,source_data):
        return [scale*x for x in nominal]
    def nested(latent,nominal,source_point,configuration,source_data):
        return nominal
    assert closure.__closure__ is not None and nested.__closure__ is None
    for response in (closure,nested):
        with pytest.raises(ValueError,match="pure module function"):
            construct(tmp_path,response_override=response)


@pytest.mark.parametrize("mutation",["code","module_binding","defaults","attributes"])
def test_response_runtime_mutation_is_refused_before_density_or_sampling(tmp_path,monkeypatch,mutation):
    joint,bg,mc=construct(tmp_path);latent={"class0":.2,"class1":.4,"class2":.4};point=bg.initial_point()
    if mutation=="code":
        monkeypatch.setattr(synthetic_response,"__code__",alternate_response.__code__)
    elif mutation=="module_binding":
        monkeypatch.setattr(sys.modules[synthetic_response.__module__],"synthetic_response",alternate_response)
    elif mutation=="defaults":
        monkeypatch.setattr(synthetic_response,"__defaults__",(None,))
    else:
        monkeypatch.setattr(synthetic_response,"cached_scale",2.,raising=False)
    for operation in (lambda:joint.evaluate(point,latent,mu=1.),
                      lambda:joint.draw_joint_data(point,latent,mu=1.,rng=np.random.default_rng(41))):
        with pytest.raises(ValueError,match="response"):
            operation()


def test_configuration_and_callback_input_mutation_cannot_rewrite_captured_contract(tmp_path):
    config=configuration()
    joint,bg,mc=construct(tmp_path,response_override=input_mutating_response,identity_override=response_identity(input_mutating_response),configuration_override=config)
    latent={"class0":.2,"class1":.4,"class2":.4};point=bg.initial_point()
    original_latent=deepcopy(latent);original_point=deepcopy(point)
    contract_hash=joint.contract_sha256
    baseline=joint.evaluate(point,latent,mu=1.)
    config["signal_scale"]=123.
    exposed=joint.contract();exposed["response"]["configuration"]["signal_scale"]=456.
    exposed["response"]["source_data_pins"].clear()
    assert joint.evaluate(point,latent,mu=1.)==baseline
    assert latent==original_latent and point==original_point
    assert joint.contract_sha256==contract_hash
    assert joint.contract()["response"]["configuration"]["signal_scale"]==1.


def test_captured_response_source_data_change_is_refused(tmp_path):
    source_path=tmp_path/"workspace.json";source_path.write_bytes(compact(workspace()))
    joint,bg,mc=construct(tmp_path,source_path=source_path)
    changed=workspace();changed["channels"][0]["samples"][0]["data"]=[6.]
    source_path.write_bytes(compact(changed))
    with pytest.raises(ValueError,match="response source data changed"):
        joint.evaluate(bg.initial_point(),{"class0":.2,"class1":.4,"class2":.4},mu=1.)


def test_different_source_point_cannot_enter_through_response_data(tmp_path):
    changed=workspace();changed["channels"][0]["samples"][0]["data"]=[6.]
    source_path=tmp_path/"other-workspace.json";source_path.write_bytes(compact(changed))
    with pytest.raises(ValueError,match="source-data workspace differs"):
        construct(tmp_path,source_path=source_path)


def test_response_executable_mutation_during_callback_is_refused(tmp_path):
    joint,bg,mc=construct(tmp_path,response_override=runtime_mutating_response,identity_override=response_identity(runtime_mutating_response))
    try:
        with pytest.raises(ValueError,match="mutable function attributes"):
            joint.evaluate(bg.initial_point(),{"class0":.2,"class1":.4,"class2":.4},mu=1.)
    finally:
        del runtime_mutating_response.changed


def test_implementation_file_custody_still_applies_to_identified_module_function(tmp_path,monkeypatch):
    path=tmp_path/"temporary_response.py"
    code="def response(latent,nominal,source_point,configuration,source_data):\n    return nominal\n"
    path.write_text(code)
    spec=importlib.util.spec_from_file_location("joined_temporary_response",path)
    module=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,spec.name,module);spec.loader.exec_module(module)
    joint,bg,mc=construct(tmp_path,response_override=module.response,identity_override=response_identity(module.response),implementation_path=path)
    path.write_text(code+"# Changed pinned implementation bytes.\n")
    with pytest.raises(ValueError,match="response implementation changed"):
        joint.evaluate(bg.initial_point(),{"class0":.2,"class1":.4,"class2":.4},mu=1.)


def test_pinned_response_data_size_is_bounded_before_JSON_read(tmp_path):
    path=tmp_path/"oversize.json"
    with path.open("wb") as stream:stream.truncate(8*1024**2+1)
    with pytest.raises(ValueError,match="8 MiB"):
        construct(tmp_path,source_path=path)
