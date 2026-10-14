"""Portable synthetic adapter admission, derivative and journal controls."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import pytest

from ravel.physics import joint_qualification as q
from ravel.physics.mc_auxiliary import compact
from ravel.physics.published_background import BackgroundAuxBlock, inspect_workspace
from joint_model_fixtures import write_mc
from test_joint_analytic import workspace

pytestmark=pytest.mark.filterwarnings("ignore:jsonschema.RefResolver is deprecated:DeprecationWarning")


def pin(path):return {"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}


def input_model(tmp_path,*,rich=False):
    source=workspace(rich=rich);mapping={"SR":["signal"],"CR":["signal"]}
    original=tmp_path/"workspace.json";original.write_bytes(compact(source))
    background=inspect_workspace(source,mapping)["background_projection"]
    bgpath=tmp_path/"background.json";bgpath.write_bytes(compact(background))
    mcpath=write_mc(tmp_path/"MC")
    block=BackgroundAuxBlock(source,mapping,measurement="M",policy="rebuild_background_mc_from_source",model_id="synthetic-source",background_source=background)
    initial=block.initial_point();interior=deepcopy(initial);interior["alpha"]=.13;interior["beta"]=1.1
    mc=json.loads(mcpath.read_bytes());latent={c["id"]:c["initial"] for c in mc["classes"]}
    case={"id":"synthetic","workspace":pin(original),"mc_model":pin(mcpath),"signal_samples":mapping,"source_bin_map":[{"channel":"CR","bin":0,"mc_bin_id":"CR"},{"channel":"SR","bin":0,"mc_bin_id":"SR"}],
          "source_bound_semantics":{name:{"lower":"physical" if name=="beta" else "numerical","upper":"numerical"} for name in initial},
          "initial_point":{"mu":1.,"source":initial,"latent":latent},"interior_point":{"mu":1.3,"source":interior,"latent":{"class0":.28,"class1":.33,"class2":.39}},
          "expected_source_coordinates":len(initial),"expected_free_coordinates":len(initial)+3}
    document={"schema_version":1,"model_id":"synthetic-full-source-qualification","measurement":"M","background_source":pin(bgpath),"cases":[case],
              "qualification":{"steps":[2e-5,1e-5],"mean_atol":1e-9,"mean_rtol":1e-10,"nll_atol":1e-8,"gradient_atol":2e-4,"gradient_rtol":2e-5,"wall_seconds":5.,"density_wrapper_calls":100,"pyhf_main_calls":300,"source_auxiliary_factor_calls":1000,"MC_density_calls":100},
              "fit":{"mu_domain":{"initial":1.,"upper":20.},"fixed_strength":1.,"budget_per_fit":{"objective_calls":2000,"gradient_calls":5000,"feasibility_lp_calls":8,"stationarity_lp_calls":3,"maxiter":200,"lp_maxiter":1000,"wall_seconds":5.},
                     "endpoint_verification":{"wall_seconds":2.5,"density_wrapper_calls":3,"pyhf_main_calls":9,"source_auxiliary_factor_calls":100,"MC_density_calls":3}},
              "execution_seconds":60,"outer_work_seconds":55.,"assumptions":["Controlled known fixed-N law.","All retained source nuisance coordinates profiled.","No native sampling-law or confidence claim."]}
    path=tmp_path/"input.json";path.write_bytes(compact(document))
    return {"input":str(path)},document,path


def test_resource_admission_and_input_custody_have_no_scientific_calls(tmp_path,monkeypatch):
    task,document,path=input_model(tmp_path)
    monkeypatch.setattr(q,"_compile",lambda *a,**k:pytest.fail("resource admission compiled scientific engine"))
    monkeypatch.setattr(q.IndependentSourceOracle,"evaluate",lambda *a,**k:pytest.fail("resource admission evaluated density"))
    assert len(q.inputs(task,tmp_path))==5
    assert q.execution_seconds(task,tmp_path)==60
    bounds=q.resource_bounds(task,tmp_path)
    assert bounds["maximum_fit_calls"]==4 and bounds["maximum_optimizer_attempts"]==12
    assert bounds["case_free_coordinate_counts"]=={"synthetic":5}
    assert not bounds["native_thread_ceiling_measured"]
    (tmp_path/"workspace.json").write_text("{}")
    with pytest.raises(ValueError,match="pin changed"):q.inputs(task,tmp_path)


def test_fresh_output_is_admitted_before_any_capture_or_work(tmp_path,monkeypatch):
    task,_,_=input_model(tmp_path);out=tmp_path/"out";out.mkdir();(out/"old").write_text("preserve")
    monkeypatch.setattr(q,"_capture",lambda *a,**k:pytest.fail("dirty output admitted capture"))
    with pytest.raises((FileExistsError,ValueError)):q.run(task,tmp_path,out)
    assert (out/"old").read_text()=="preserve"


def test_actual_small_joint_qualification_fits_and_independent_endpoints(tmp_path):
    task,_,_=input_model(tmp_path)
    result=q.run(task,tmp_path,tmp_path/"out")
    assert result["status"]=="passed",result
    columns=result["qualification"][0]["gradient_columns"]
    assert len(columns)==5 and all(c["passed"] and len(c["steps"])==2 for c in columns)
    assert all(len(c["analytic_mean_column"])==6 for c in columns)
    assert result["qualification_budget_used"]=={"density_wrapper_calls":22,"pyhf_main_calls":66,"source_auxiliary_factor_calls":22,"MC_density_calls":22}
    assert result["endpoint_verification_budget_used"]["density_wrapper_calls"]==12
    assert all(r["passed"] for r in result["nested_model_checks"])
    for construction in ("fixed_MC_baseline","finite_MC"):
        fitted=result["fits"][0]["fits"][construction]["free_strength"]
        assert fitted["parameters"]["mu"]==pytest.approx(8/3,abs=3e-4)
        assert fitted["parameters"]["source"]["beta"]==pytest.approx(.6,abs=3e-4)
        assert fitted["independent_endpoint_parity"]
        assert all(c["passed"] for c in fitted["independent_endpoint_checks"])
    journal=[json.loads(line) for line in (tmp_path/"out/qualification-progress.jsonl").read_bytes().splitlines()]
    previous=None
    for i,row in enumerate(journal):
        assert row["sequence"]==i and row["previous_sha256"]==previous
        previous=hashlib.sha256(compact(row)).hexdigest()
    assert len([r for r in journal if r["kind"]=="fit" and r["state"]=="planned"])==4
    assert len([r for r in journal if r["kind"]=="fit" and r["state"]=="running"])==4
    assert not result["physics_validated"] and not result["global_optimum_certified"]
    json.dumps(result,allow_nan=False)


def test_independent_oracle_rebuilt_gamma_and_noninteger_poisson_constants(tmp_path):
    task,_,_=input_model(tmp_path,rich=True)
    document,_,background,cases=q._capture(task,tmp_path);row,source,mc=cases[0]
    bg,joint=q._compile(row,source,background,mc,"M","synthetic")
    budget=q.QualificationBudget(document["qualification"],time.monotonic()+10)
    oracle=q.IndependentSourceOracle(source,background,row,mc,"M",budget)
    p=deepcopy(row["interior_point"]);p["source"]["pooled[0]"]=1.04;p["source"]["pooled[1]"]=.93;p["source"]["MC_CR[0]"]=1.05
    independent=oracle.evaluate(p);analytic=joint.evaluate_with_gradient(p["source"],p["latent"],mu=p["mu"])
    assert independent["nll"]==pytest.approx(analytic["nll"],abs=2e-11)
    assert independent["distribution_mean_vector"]==pytest.approx(analytic["distribution_mean_vector"],abs=2e-12)
    assert sorted(r["sigma"] for r in oracle.aux if r["coordinate"].startswith("pooled"))==pytest.approx([.1,.2])
    assert any(r["pdf"]=="poisson" and r["observed"]!=int(r["observed"]) for r in oracle.aux)


def test_scalar_score_cancellation_does_not_hide_wrong_mean_jacobian(tmp_path,monkeypatch):
    task,_,_=input_model(tmp_path)
    original=q.AnalyticPublishedJoint.evaluate_with_gradient
    def corrupt(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        result["distribution_mean_jacobian"][0][0]+=1.
        return result
    monkeypatch.setattr(q.AnalyticPublishedJoint,"evaluate_with_gradient",corrupt)
    monkeypatch.setattr(q.AnalyticJointProfiler,"fit",lambda *a,**k:pytest.fail("fit launched after Jacobian qualification refusal"))
    result=q.run(task,tmp_path,tmp_path/"out")
    assert result["status"]=="failed" and result["fits"]==[]
    column=result["qualification"][0]["gradient_columns"][0]
    assert column["coordinate"]=="mu" and not column["passed"]
    assert all(s["score_absolute_error"]<1e-4 for s in column["steps"])
    assert any(s["mean_max_absolute_error"]>.99 for s in column["steps"])
    assert result["planned_fit_denominator"]==4


def test_unverified_retained_endpoint_is_also_independently_checked(tmp_path):
    task,_,_=input_model(tmp_path);document,_,background,cases=q._capture(task,tmp_path)
    row,source,mc=cases[0];bg,joint=q._compile(row,source,background,mc,"M","synthetic")
    p=row["interior_point"];a=joint.evaluate_with_gradient(p["source"],p["latent"],mu=p["mu"])
    budget=q.QualificationBudget(document["qualification"],time.monotonic()+10)
    oracle=q.IndependentSourceOracle(source,background,row,mc,"M",budget);out=tmp_path/"journal";out.mkdir()
    fit={"verified":False,"attempts":[{"index":0,"parameters":p,"nll":a["nll"],"distribution_mean_vector":a["distribution_mean_vector"]}]}
    checked=q._endpoint_checks(fit,oracle,q.Journal(out),"failed-fit",document["qualification"])
    assert not checked["verified"] and checked["independent_endpoint_parity"]
    assert budget.used["density_wrapper_calls"]==1
    fit={"verified":True,"attempts":[{"index":0,"parameters":p,"nll":a["nll"]+1.,"distribution_mean_vector":a["distribution_mean_vector"]}]}
    checked=q._endpoint_checks(fit,oracle,q.Journal(out),"wrong-fit",document["qualification"])
    assert not checked["verified"] and not checked["independent_endpoint_parity"]


def test_qualification_call_exhaustion_is_retained_and_no_fits_launch(tmp_path,monkeypatch):
    task,document,path=input_model(tmp_path);document["qualification"]["pyhf_main_calls"]=1;path.write_bytes(compact(document))
    monkeypatch.setattr(q.AnalyticJointProfiler,"fit",lambda *a,**k:pytest.fail("fit after independent-call exhaustion"))
    result=q.run(task,tmp_path,tmp_path/"out")
    assert result["status"]=="failed" and result["fits"]==[]
    assert result["qualification_budget_used"]["pyhf_main_calls"]==1
    assert "ceiling exhausted" in result["qualification"][0]["fixed_vectors"][0]["error"]
    rows=[json.loads(line) for line in (tmp_path/"out/qualification-progress.jsonl").read_bytes().splitlines()]
    assert any(r["kind"]=="independent_density" and r["state"]=="running" for r in rows)
    assert any(r["kind"]=="independent_density" and r["state"]=="failed" for r in rows)


@pytest.mark.parametrize("corruption",["selected_nll","selected_parameters"])
def test_selected_endpoint_must_bind_a_checked_retained_attempt(tmp_path,corruption):
    task,_,_=input_model(tmp_path);document,_,background,cases=q._capture(task,tmp_path)
    row,source,mc=cases[0];bg,joint=q._compile(row,source,background,mc,"M","synthetic")
    p=row["interior_point"];a=joint.evaluate_with_gradient(p["source"],p["latent"],mu=p["mu"])
    oracle=q.IndependentSourceOracle(source,background,row,mc,"M",q.QualificationBudget(document["qualification"],time.monotonic()+10))
    out=tmp_path/"journal";out.mkdir()
    fit={"verified":True,"parameters":deepcopy(p),"nll":a["nll"],"attempts":[{"index":0,"parameters":p,"nll":a["nll"],"distribution_mean_vector":a["distribution_mean_vector"]}]}
    if corruption=="selected_nll":fit["nll"]-=1.
    else:fit["parameters"]["mu"]+=1.
    checked=q._endpoint_checks(fit,oracle,q.Journal(out),"corrupted-selected",document["qualification"])
    assert checked["independent_endpoint_checks"][0]["passed"]
    assert not checked["verified"] and not checked["selected_endpoint_binding"]["passed"]
    assert not checked["independent_endpoint_parity"]


def test_missing_attempt_state_is_explicit_without_erasing_other_failed_attempts(tmp_path):
    task,_,_=input_model(tmp_path);document,_,background,cases=q._capture(task,tmp_path)
    row,source,mc=cases[0];bg,joint=q._compile(row,source,background,mc,"M","synthetic")
    p=row["interior_point"];a=joint.evaluate_with_gradient(p["source"],p["latent"],mu=p["mu"])
    oracle=q.IndependentSourceOracle(source,background,row,mc,"M",q.QualificationBudget(document["qualification"],time.monotonic()+10))
    out=tmp_path/"journal";out.mkdir()
    fit={"verified":False,"attempts":[{"index":0,"failure_kind":"budget_exhausted"},{"index":1,"parameters":p,"nll":a["nll"],"distribution_mean_vector":a["distribution_mean_vector"]}]}
    checked=q._endpoint_checks(fit,oracle,q.Journal(out),"partial-fit",document["qualification"])
    assert len(checked["independent_endpoint_checks"])==2
    assert not checked["independent_endpoint_checks"][0]["checked"]
    assert checked["independent_endpoint_checks"][0]["passed"] is None
    assert checked["independent_endpoint_checks"][1]["passed"]
    assert not checked["verified"]


def test_independent_oracle_does_not_share_the_MC_nominal_implementation(tmp_path,monkeypatch):
    task,_,_=input_model(tmp_path);document,_,background,cases=q._capture(task,tmp_path)
    row,source,mc=cases[0]
    oracle=q.IndependentSourceOracle(source,background,row,mc,"M",q.QualificationBudget(document["qualification"],time.monotonic()+10))
    monkeypatch.setattr(mc,"nominal",lambda *a,**k:pytest.fail("independent oracle called shared MC nominal"))
    assert math.isfinite(oracle.evaluate(row["interior_point"])["nll"])


def test_MC_nominal_corruption_is_detected_by_independent_fixed_vector_oracle(tmp_path,monkeypatch):
    task,_,_=input_model(tmp_path)
    original=q.MCAuxiliaryBlock.nominal
    def corrupt(self,*args,**kwargs):
        result=original(self,*args,**kwargs);result["signal_expectation"]=[v+1. for v in result["signal_expectation"]]
        return result
    monkeypatch.setattr(q.MCAuxiliaryBlock,"nominal",corrupt)
    monkeypatch.setattr(q.AnalyticJointProfiler,"fit",lambda *a,**k:pytest.fail("fit after MC oracle refusal"))
    result=q.run(task,tmp_path,tmp_path/"out")
    assert result["status"]=="failed" and result["fits"]==[]
    assert not result["qualification"][0]["fixed_vectors"][0]["passed"]


def test_returned_fit_survives_interruption_of_the_next_solver(tmp_path,monkeypatch):
    class SimulatedHardTimeout(BaseException):pass
    task,_,_=input_model(tmp_path);original=q.AnalyticJointProfiler.fit;calls=[]
    def interrupted(self,*args,**kwargs):
        calls.append(kwargs)
        if len(calls)>1:raise SimulatedHardTimeout("No current solver object serialized")
        return original(self,*args,**kwargs)
    monkeypatch.setattr(q.AnalyticJointProfiler,"fit",interrupted)
    with pytest.raises(SimulatedHardTimeout):q.run(task,tmp_path,tmp_path/"out")
    rows=[json.loads(line) for line in (tmp_path/"out/qualification-progress.jsonl").read_bytes().splitlines()]
    returned=[r for r in rows if r["kind"]=="fit" and r["state"]=="returned"]
    completed=[r for r in rows if r["kind"]=="fit" and r["state"]=="completed"]
    running=[r for r in rows if r["kind"]=="fit" and r["state"]=="running"]
    assert len(returned)==len(completed)==1 and len(running)==2
    assert returned[0]["snapshot"]["attempts"] and returned[0]["snapshot"]["parameters"]
    assert completed[0]["snapshot"]["selected_endpoint_binding"]["passed"]
    assert completed[0]["snapshot"]["independent_endpoint_parity"]
    assert running[-1]["identity"].endswith("fixed_strength")
    assert not (tmp_path/"out/joint_qualification_result.json").exists()
