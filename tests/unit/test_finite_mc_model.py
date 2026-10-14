"""Unit-scale controls only; no accepted scientific calibration campaign."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import multinomial,poisson
from ravel.physics import finite_mc_model as fm


def document(kind="poisson_groups",signed=False):
    if kind=="poisson_groups":
        marks=[[1.,2.]] if not signed else [[1.,.5],[-1.,-.5]]
        counts=[6] if not signed else [4,2]
        initial=[2.] if not signed else [4.,2.]
        exposure=[3.] if not signed else [1.,1.]
        denominators=[None]*len(marks)
    else:
        marks=[[1.,0.],[0.,1.],[0.,0.]] if not signed else [[1.,.2],[-1.,-.2],[0.,0.],[0.,0.]]
        counts=[3,3,4] if not signed else [4,1,4,1]
        initial=[.3,.3,.4] if not signed else [.4,.1,.4,.1]
        exposure=[None]*len(marks)
        denominators=[1.]*len(marks) if not signed else [1.,-1.,1.,-1.]
    classes=[{"id":f"class{k}","contribution":a,"denominator_mark":d,"exposure":t,"observed":m,
              "observed_group_ids":[f"group{k}-{j}" for j in range(m)],"initial":x,"upper":100. if kind=="poisson_groups" else 1.,"source":"ledger"}
             for k,(a,d,t,m,x) in enumerate(zip(marks,denominators,exposure,counts,initial))]
    point={"mu":3. if kind=="poisson_groups" else 1.,"nuisance":{c["id"]:c["initial"] for c in classes}}
    observed=[8,16] if kind=="poisson_groups" and not signed else [8,7] if kind=="poisson_groups" else [8,10] if not signed else [8,5]
    bins=[{"id":name,"role":role,"observed":n,"background":b,"observation_id":"observed-"+name,"source":"ledger"} for name,role,n,b in zip(["SR","CR"],["signal","control"],observed,[2.,4.])]
    return {"schema_version":1,"model_id":kind+("-signed" if signed else "-positive"),
            "sources":[{"id":"ledger","path":"ledger.json","sha256":"0"*64,"reference":"Explicitly synthetic fixed-mark generator law and observed groups"}],
            "bins":bins,"partition":{"kind":"disjoint","source":"ledger","overlap_counts":[[observed[0],0],[0,observed[1]]]},
            "background_contract":{"mode":"conditional_fixed","source":"ledger","meaning":"Synthetic exact known background, no official workspace claim"},
            "mc_design":{"kind":kind,"sampling_law":"independent_poisson_fixed_mark_populations" if kind=="poisson_groups" else "iid_fixed_mark_categories",
                         "fixed_marks":True,"support_complete":True,"ledger_source":"ledger","independence":"disjoint_poisson_group_populations" if kind=="poisson_groups" else "iid_groups_within_one_fixed_N_stream",
                         "total_groups":None if kind=="poisson_groups" else sum(counts),"kappa":None if kind=="poisson_groups" else 20. if not signed else 12.,
                         "normalization_source":"ledger","normalization_meaning":"Known MC to target exposure" if kind=="poisson_groups" else "Known external inclusive expectation, times expected mark ratio"},
            "classes":classes,"mu":{"initial":2. if kind=="poisson_groups" else .8,"upper":30.,"meaning":"Source strength multiplying the full latent SR/CR signal"},
            "comparison_points":[point,dict(point,mu=1. if kind=="poisson_groups" else 2.)],"profile_points":[1.,3.] if kind=="poisson_groups" else [1.,2.],
            "calibration":{"enabled":False,"seed":390041,"trials_per_truth":1,"truths":[point],"nuisance_sampling":"fixed_truth","main_sampling":"repeat_poisson_main","mc_sampling":"repeat_declared_MC_law","threshold":3.841458820694124,"confidence_level":.95,"maxiter":500},
            "assumptions":["Fixed known marks and complete support are supplied assumptions, not derived from moments.","Actual independent Poisson populations or IID fixed-N categories must be justified by generator source.","Conditional fixed background; detector, official nuisances and MC/source variation coupling remain open."]}


def bind(folder,model):
    folder.mkdir(parents=True,exist_ok=True)
    model=deepcopy(model)
    ledger={"schema_version":1,"sampling_law":model["mc_design"]["sampling_law"],"support_complete":True,
            "classes":[{key:c[key] for key in ("id","contribution","denominator_mark","exposure")} for c in model["classes"]],
            "groups":[{"id":gid,"class_id":c["id"],"contribution":c["contribution"],"denominator_mark":c["denominator_mark"]} for c in model["classes"] for gid in c["observed_group_ids"]],
            "normalization":{key:model["mc_design"][key] for key in ("total_groups","kappa","normalization_meaning")},
            "main_bins":[{key:b[key] for key in ("id","role","observed","background","observation_id")} for b in model["bins"]],
            "main_partition":{key:model["partition"][key] for key in ("kind","overlap_counts")}}
    raw=(json.dumps(ledger,indent=2,sort_keys=True)+"\n").encode()
    (folder/"ledger.json").write_bytes(raw)
    model["sources"][0]["sha256"]=hashlib.sha256(raw).hexdigest()
    (folder/"model.json").write_text(json.dumps(model,indent=2,sort_keys=True)+"\n")
    return model


@pytest.mark.parametrize("kind",fm.KINDS)
@pytest.mark.parametrize("signed",[False,True])
def test_full_density_matches_independent_Poisson_or_multinomial(kind,signed):
    model=document(kind,signed)
    assert fm.prepare(model)
    for point in model["comparison_points"]:
        result=fm.evaluate(model,point);independent=fm.independent_density(model,point)
        n=[b["observed"] for b in model["bins"]];m=[c["observed"] for c in model["classes"]]
        nll=-sum(poisson.logpmf(n,result["main_means"]))
        nll-=sum(poisson.logpmf(m,result["mc_means"])) if kind=="poisson_groups" else multinomial.logpmf(m,sum(m),list(point["nuisance"].values()))
        assert result["nll"]==pytest.approx(independent["nll"],abs=1e-12)
        assert result["nll"]==pytest.approx(nll,abs=1e-12)


def test_signed_laws_have_same_moments_but_different_exact_probabilities():
    result=fm.signed_law_witness()
    A,B=result["laws"]
    assert A["mean"]==B["mean"]==2.
    assert A["variance"]==B["variance"]==6.
    assert A["third_cumulant"]==2. and B["third_cumulant"]==10.
    assert abs(A["pmf"]["0"]-B["pmf"]["0"])>.05
    assert result["pmf_L1_distance"]>.3
    assert result["A_skellam_zero_residual"]<1e-13
    assert all(law["omitted_tail_bound"]<1e-13 for law in result["laws"])


def test_equal_observed_sumw_sumw2_produce_different_profile_inference():
    A=document("poisson_groups",True)
    C=deepcopy(A)
    C["model_id"]="equal-observed-moments-different-strata"
    C["classes"]=[]
    for index,(weight,count) in enumerate(((2.,1),(.5,4),(-.5,4))):
        C["classes"].append({"id":f"c{index}","contribution":[weight,.5*weight],"denominator_mark":None,"exposure":1.,"observed":count,
                             "observed_group_ids":[f"c{index}-{j}" for j in range(count)],"initial":float(count),"upper":100.,"source":"ledger"})
    point={"mu":3.,"nuisance":{c["id"]:c["initial"] for c in C["classes"]}}
    C["comparison_points"]=[point,dict(point,mu=1.)];C["calibration"]["truths"]=[point]
    def moments(model):
        return [sum(c["contribution"][0]**power*c["observed"] for c in model["classes"]) for power in (1,2)]
    assert moments(A)==moments(C)==[2.,6.]
    first=fm.profile(A,[1.,3.]);second=fm.profile(C,[1.,3.])
    assert first["verified"] and second["verified"],(first,second)
    assert first["global_fit"]["parameters"]["mu"]==pytest.approx(3.,abs=2e-5)
    assert second["global_fit"]["parameters"]["mu"]==pytest.approx(3.,abs=2e-5)
    assert abs(first["profiles"][0]["twice_delta_nll"]-second["profiles"][0]["twice_delta_nll"])>.01


def test_exact_saturated_Poisson_auxiliary_global_and_conditional_witness():
    model=document()
    result=fm.profile(model,[1.,3.])
    assert result["verified"],result
    best=result["global_fit"]
    assert best["parameters"]["mu"]==pytest.approx(3.,abs=2e-5)
    assert best["parameters"]["nuisance"]["class0"]==pytest.approx(2.,abs=1e-5)
    # Two main bins proportional 1:2 combine to Pois(6+3*mu*rho),
    # with independent MC count m=6~Pois(3*rho). At mu=1, the exact
    # optimum solves 18*rho^2 -54*rho -36=0.
    root=(54+math.sqrt(54**2+4*18*36))/(2*18)
    conditional=result["profiles"][0]["fit"]
    assert conditional["parameters"]["nuisance"]["class0"]==pytest.approx(root,abs=2e-5)
    assert conditional["conditional_convex"]
    independent=fm.independent_density(model,{"mu":1.,"nuisance":{"class0":root}})
    assert conditional["nll"]==pytest.approx(independent["nll"],abs=1e-10)


def test_fixed_N_saturated_global_recovery_and_complete_correlations():
    model=document("fixed_n_categories")
    result=fm.profile(model,[1.])
    assert result["verified"],result
    assert result["global_fit"]["parameters"]["mu"]==pytest.approx(1.,abs=2e-5)
    for name,value in zip(["class0","class1","class2"],[.3,.3,.4]):
        assert result["global_fit"]["parameters"]["nuisance"][name]==pytest.approx(value,abs=2e-5)
    covariance=fm.evaluate(model,model["comparison_points"][0])["mark_estimator_covariance"]
    assert covariance==pytest.approx(np.asarray([[.021,-.009],[-.009,.021]]))
    # A Poissonized bin treatment would erase the fixed-N negative covariance.
    assert covariance[0][1]<0


def test_zero_observed_selected_CR_keeps_positive_latent_probability():
    model=document("fixed_n_categories")
    model["classes"][1].update(observed=0,observed_group_ids=[])
    model["classes"][2].update(observed=7,observed_group_ids=[f"other-{i}" for i in range(7)])
    assert fm.prepare(model)
    result=fm.evaluate(model,model["comparison_points"][0])
    assert result["signal_expectation"][1]==pytest.approx(6.)
    assert result["nll"] is not None
    first=fm.fit(model,fixed_mu=1.)
    assert first["verified"],first
    assert first["parameters"]["nuisance"]["class1"]>0


def test_zero_MC_recession_is_unresolved_before_mu_cap_can_create_limit():
    model=document("fixed_n_categories")
    for c in model["classes"][:2]:
        c.update(observed=0,observed_group_ids=[])
    model["classes"][2].update(observed=10,observed_group_ids=[f"unselected-{i}" for i in range(10)])
    result=fm.fit(model)
    assert not result["verified"]
    assert result["structural_limits"]["analytic_scaling_recession"]
    # Explicitly approach the supremum without fixing selected p to zero.
    main=[];nll=[]
    model["mu"]["upper"]=1000.
    for mu in (10.,100.,1000.):
        point={"mu":mu,"nuisance":{"class0":.3/mu,"class1":.3/mu,"class2":1-.6/mu}}
        row=fm.evaluate(model,point);main.append(row["main_means"]);nll.append(row["nll"])
    assert main[0]==pytest.approx(main[1]) and main[1]==pytest.approx(main[2])
    assert nll[0]>nll[1]>nll[2]


def test_negative_observed_signed_sum_and_denominator_are_valid_auxiliary_data():
    model=document("fixed_n_categories",True)
    data={"main":[8,5],"mc":[1,4,1,4]}
    assert sum(d*m for d,m in zip([1,-1,1,-1],data["mc"]))==-6
    point=model["comparison_points"][0]
    result=fm.evaluate(model,point,data)
    assert result["finite"]
    assert result["expected_denominator"]==pytest.approx(.6)
    assert result["signal_expectation"]==pytest.approx([6.,1.2])
    assert fm.independent_density(model,point,data)["nll"]==pytest.approx(result["nll"],abs=1e-12)
    bad=deepcopy(point);bad["nuisance"]={"class0":.1,"class1":.4,"class2":.1,"class3":.4}
    with pytest.raises(ValueError):
        fm.evaluate(model,bad,data)


def test_shared_signed_group_preserves_negative_cross_bin_covariance():
    model=document("poisson_groups",True)
    model["classes"][0]["contribution"]=[1.,-.5]
    model["classes"][1]["contribution"]=[0.,2.]
    point=model["comparison_points"][0]
    result=fm.evaluate(model,point)
    assert result["signal_expectation"]==pytest.approx([4.,2.])
    assert result["mark_estimator_covariance"][0][1]==pytest.approx(-2.)


@pytest.mark.parametrize("kind",fm.KINDS)
def test_joint_gradients_follow_the_declared_original_density(kind):
    model=document(kind,True);point=deepcopy(model["comparison_points"][0])
    result=fm.evaluate(model,point)
    step=1e-6
    up,down=deepcopy(point),deepcopy(point);up["mu"]+=step;down["mu"]-=step
    derivative=(fm.independent_density(model,up)["nll"]-fm.independent_density(model,down)["nll"])/(2*step)
    assert result["gradient"][0]==pytest.approx(derivative,abs=1e-6)
    ids=list(point["nuisance"])
    for k,name in enumerate(ids if kind=="poisson_groups" else ids[:-1]):
        up,down=deepcopy(point),deepcopy(point)
        up["nuisance"][name]+=step;down["nuisance"][name]-=step
        expected=result["gradient"][k+1]
        if kind=="fixed_n_categories":
            up["nuisance"][ids[-1]]-=step;down["nuisance"][ids[-1]]+=step
            expected-=result["gradient"][-1]
        derivative=(fm.independent_density(model,up)["nll"]-fm.independent_density(model,down)["nll"])/(2*step)
        assert expected==pytest.approx(derivative,abs=1e-6)


def test_identification_cannot_be_created_by_signal_strength_bound():
    model=document("poisson_groups",True)
    point={"mu":1.,"nuisance":{"class0":2.,"class1":2.}}
    result=fm.identifiability(model,point)
    assert not result["identified"]
    assert result["rank"]==2 and result["free_dimension"]==3


def test_numerical_mu_caps_are_unresolved_and_retained():
    model=document()
    model["mu"]["upper"]=2.2
    model["comparison_points"]=[dict(model["comparison_points"][0],mu=1.),dict(model["comparison_points"][0],mu=2.)]
    model["profile_points"]=[1.,2.]
    model["calibration"]["truths"]=[model["comparison_points"][0]]
    result=fm.fit(model)
    assert not result["verified"]
    assert any(any(bound["coordinate"]==0 and bound["side"]=="upper" and not bound["physical"] for bound in r.get("active_bounds",[])) for r in result["attempts"])


def test_success_code_without_tangent_stationarity_is_refused(monkeypatch):
    import scipy.optimize
    from types import SimpleNamespace
    def false_success(fun,x0,**kwargs):
        return SimpleNamespace(x=x0,success=True,message="fake solver",nit=0)
    monkeypatch.setattr(scipy.optimize,"minimize",false_success)
    result=fm.fit(document())
    assert not result["verified"]
    assert all(r["tangent_descent_violation"]>1e-4 for r in result["attempts"])


def test_zero_rate_zero_count_exact_boundary_has_no_pseudocount():
    model=document("poisson_groups",True)
    model["classes"][1].update(observed=0,observed_group_ids=[])
    point={"mu":1.,"nuisance":{"class0":4.,"class1":0.}}
    result=fm.evaluate(model,point)
    assert result["finite"] and result["mc_means"][1]==0.
    assert result["nll"]==pytest.approx(fm.independent_density(model,point)["nll"],abs=1e-12)
    # Positive observed count at a zero latent rate has exactly zero probability.
    impossible=fm.evaluate(document("poisson_groups",True),point)
    assert not impossible["finite"] and impossible["nll"] is None
    json.dumps(impossible,allow_nan=False)


@pytest.mark.parametrize("change",[
    lambda d:d["mc_design"].update(kind="moment_matched_gaussian"),
    lambda d:d["mc_design"].update(fixed_marks=False),
    lambda d:d["mc_design"].update(support_complete=False),
    lambda d:d["mc_design"].update(total_groups=6),
    lambda d:d["classes"][0].update(exposure=None),
    lambda d:d["classes"][0].update(observed=6.5),
    lambda d:d["classes"][0].update(observed_group_ids=["same"]*6),
    lambda d:d["partition"]["overlap_counts"][0].__setitem__(1,1),
    lambda d:d["calibration"].update(mc_sampling="condition_on_observed_MC"),
    lambda d:d["calibration"].update(nuisance_sampling="prior_draws"),
])
def test_source_or_sampling_shortcuts_are_refused(change):
    model=document();change(model)
    with pytest.raises(ValueError):
        fm.prepare(model)


def test_missing_unselected_support_is_not_silently_Poissonized():
    model=document("fixed_n_categories")
    model["classes"].pop()
    with pytest.raises(ValueError,match="includes unselected"):
        fm.prepare(model)


def test_observed_ledger_is_custodied_and_checks_fixed_marks(tmp_path):
    bind(tmp_path,document())
    assert len(fm.inputs({"input":"model.json"},tmp_path))==2
    ledger=json.loads((tmp_path/"ledger.json").read_text());ledger["groups"][0]["contribution"]=[99.,2.]
    raw=json.dumps(ledger).encode();(tmp_path/"ledger.json").write_bytes(raw)
    model=json.loads((tmp_path/"model.json").read_text());model["sources"][0]["sha256"]=hashlib.sha256(raw).hexdigest();(tmp_path/"model.json").write_text(json.dumps(model))
    with pytest.raises(ValueError,match="unequal observed marks"):
        fm.inputs({"input":"model.json"},tmp_path)


def test_raw_group_export_keeps_unselected_and_zero_observed_support():
    model=document("fixed_n_categories")
    support=[{key:c[key] for key in ("id","contribution","denominator_mark","exposure")} for c in model["classes"]]
    support.append({"id":"zero-observed","contribution":[.5,.5],"denominator_mark":1.,"exposure":None})
    groups=[{"id":gid,"class_id":c["id"],"contribution":c["contribution"],"denominator_mark":c["denominator_mark"]} for c in model["classes"] for gid in c["observed_group_ids"]]
    normalization={key:model["mc_design"][key] for key in ("total_groups","kappa","normalization_meaning")}
    export=fm.export_fixed_mark_ledger(groups,support,"iid_fixed_mark_categories",normalization)
    assert export["observed_counts_in_declared_support"]["zero-observed"]==0
    assert export["observed_counts_in_declared_support"]["class2"]==4
    assert len(export["ledger"]["classes"])==4
    assert export["ledger"]["normalization"]["total_groups"]==10
    invalid=deepcopy(groups);invalid[0]["denominator_mark"]=-.8
    with pytest.raises(ValueError,match="not fixed"):
        fm.export_fixed_mark_ledger(invalid,support,"iid_fixed_mark_categories",normalization)


def test_raw_export_validates_unobserved_support_and_generator_normalization():
    model=document("fixed_n_categories")
    support=[{key:c[key] for key in ("id","contribution","denominator_mark","exposure")} for c in model["classes"]]
    groups=[{"id":gid,"class_id":c["id"],"contribution":c["contribution"],"denominator_mark":c["denominator_mark"]} for c in model["classes"] for gid in c["observed_group_ids"]]
    normalization={key:model["mc_design"][key] for key in ("total_groups","kappa","normalization_meaning")}
    bad_support=deepcopy(support)+[{"id":"zero-observed","contribution":[float("nan"),.5],"denominator_mark":1.,"exposure":None}]
    with pytest.raises(ValueError):
        fm.export_fixed_mark_ledger(groups,bad_support,"iid_fixed_mark_categories",normalization)
    with pytest.raises(ValueError,match="kappa"):
        fm.export_fixed_mark_ledger(groups,support,"iid_fixed_mark_categories",dict(normalization,kappa=0.))
    with pytest.raises(ValueError,match="fixed N or ratio"):
        fm.export_fixed_mark_ledger([], [{"id":"p","contribution":[1.,1.],"denominator_mark":None,"exposure":1.}],
                                    "independent_poisson_fixed_mark_populations",normalization)


@pytest.mark.parametrize("kind",fm.KINDS)
def test_sampling_repeats_main_and_MC_at_fixed_truth(kind):
    model=document(kind);truth=model["calibration"]["truths"][0]
    first=np.random.default_rng(390041);second=np.random.default_rng(390041)
    data=fm.draw_data(model,truth,first)
    main=second.poisson(fm.evaluate(model,truth)["main_means"]).tolist()
    mc=second.poisson(fm.evaluate(model,truth)["mc_means"]).tolist() if kind=="poisson_groups" else second.multinomial(10,[.3,.3,.4]).tolist()
    assert data=={"main":main,"mc":mc}
    assert truth==model["calibration"]["truths"][0]
    if kind=="fixed_n_categories":
        assert sum(data["mc"])==10


def test_all_toy_failures_remain_in_denominator(monkeypatch):
    model=document();model["calibration"].update(enabled=True,trials_per_truth=2)
    def failed(*args,**kwargs):
        return {"verified":False,"global_fit":{"verified":False},"profiles":[{"twice_delta_nll":None,"fit":{"verified":False}}]}
    monkeypatch.setattr(fm,"profile",failed)
    result=fm.calibrate(model);ensemble=result["ensembles"][0]
    assert ensemble["generated"]==ensemble["failed"]==2 and ensemble["resolved"]==0
    assert ensemble["coverage_bounds_all_trials"]==[0.,1.]
    assert len(ensemble["trials"])==2
    json.dumps(result,allow_nan=False)


def test_solver_exceptions_retain_all_attempts(monkeypatch):
    import scipy.optimize
    def failed(*args,**kwargs):
        raise RuntimeError("controlled solver exception")
    monkeypatch.setattr(scipy.optimize,"minimize",failed)
    result=fm.fit(document())
    assert not result["verified"] and len(result["attempts"])==3
    assert all(r["failure_kind"]=="optimizer_exception" and r["exception_type"]=="RuntimeError" for r in result["attempts"])
    json.dumps(result,allow_nan=False)


def test_failed_stationarity_solver_is_JSON_safe_and_unverified(monkeypatch):
    from types import SimpleNamespace
    import scipy.optimize
    monkeypatch.setattr(scipy.optimize,"linprog",lambda *args,**kwargs:SimpleNamespace(success=False,fun=None,message="controlled LP failure"))
    result=fm.fit(document())
    assert not result["verified"]
    assert all(r["tangent_descent_violation"] is None and not r["stationarity_solver_success"] for r in result["attempts"])
    json.dumps(result,allow_nan=False)


def test_profile_exceptions_keep_draws_and_full_toy_denominator(monkeypatch):
    model=document("fixed_n_categories");model["calibration"].update(enabled=True,trials_per_truth=2)
    def failed(*args,**kwargs):
        raise RuntimeError("controlled profile exception")
    monkeypatch.setattr(fm,"profile",failed)
    result=fm.calibrate(model);ensemble=result["ensembles"][0]
    assert ensemble["generated"]==ensemble["failed"]==2 and ensemble["resolved"]==0
    assert ensemble["coverage_bounds_all_trials"]==[0.,1.]
    assert all(sum(t["data"]["mc"])==10 and t["fit"]["failure_kind"]=="profile_exception" for t in ensemble["trials"])
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize("kind",fm.KINDS)
def test_tiny_enabled_calibration_and_actual_JSON_outputs(tmp_path,kind):
    model=document(kind);model["calibration"]["enabled"]=True
    bind(tmp_path,model)
    result=fm.run({"input":"model.json"},tmp_path,tmp_path/"outputs")
    assert result["status"]=="passed",result
    assert result["calibration"]["executed"]
    assert result["calibration"]["ensembles"][0]["generated"]==1
    assert not result["physics_validated"]
    assert json.loads((tmp_path/"outputs/finite_mc_result.json").read_text())==result


def test_resource_bounds_derive_observed_and_full_toy_fit_counts(tmp_path):
    model=document("fixed_n_categories")
    model["calibration"].update(enabled=True,trials_per_truth=8,truths=[model["comparison_points"][0],model["comparison_points"][1]])
    bind(tmp_path,model)
    bounds=fm.resource_bounds({"input":"model.json"},tmp_path)
    assert fm.execution_seconds({"input":"model.json"},tmp_path)==60
    assert bounds["calibration_trial_denominator"]==16
    assert bounds["maximum_fit_calls"]==1+len(model["profile_points"])+2*16
    assert bounds["maximum_optimizer_attempts"]==3*bounds["maximum_fit_calls"]
    assert bounds["maximum_total_optimizer_iterations"]==500*bounds["maximum_optimizer_attempts"]
    assert bounds["maximum_seed_feasibility_LP_calls"]==2*len(model["classes"])*bounds["maximum_fit_calls"]
    assert bounds["maximum_endpoint_stationarity_LP_calls"]==3*bounds["maximum_fit_calls"]
    assert bounds["processes"]==bounds["threads"]==1


def test_nonempty_output_is_refused_before_input_reads_or_fitting(tmp_path,monkeypatch):
    output=tmp_path/"outputs";output.mkdir();(output/"sentinel.txt").write_text("preserve")
    def forbidden(*args,**kwargs):
        pytest.fail("input capture must not happen after output admission refusal")
    monkeypatch.setattr(fm,"_capture",forbidden)
    with pytest.raises(FileExistsError,match="new or empty"):
        fm.run({"input":"missing.json"},tmp_path,output)
    assert (output/"sentinel.txt").read_text()=="preserve"


def test_output_symlink_is_refused_before_input_reads(tmp_path,monkeypatch):
    target=tmp_path/"target";target.mkdir();output=tmp_path/"outputs";output.symlink_to(target,target_is_directory=True)
    monkeypatch.setattr(fm,"_capture",lambda *args:pytest.fail("early output guard required"))
    with pytest.raises(ValueError,match="symlink"):
        fm.run({"input":"missing.json"},tmp_path,output)
    assert list(target.iterdir())==[]


def test_derived_finite_mark_overflow_is_retained_as_failed_JSON(tmp_path):
    model=document()
    model["classes"][0]["contribution"]=[1e155,2e155]
    bind(tmp_path,model)
    result=fm.run({"input":"model.json"},tmp_path,tmp_path/"outputs")
    assert result["status"]=="failed" and not result["calibration"]["executed"]
    assert all(not row["passed"] and row["failure_kind"]=="comparison_exception" for row in result["comparisons"])
    assert all(row["exception_type"] in ("FloatingPointError","ValueError") for row in result["comparisons"])
    assert json.loads((tmp_path/"outputs/finite_mc_result.json").read_text())==result
    fitted=fm.fit(model)
    assert not fitted["verified"] and len(fitted["attempts"])==3
    json.dumps(fitted,allow_nan=False)


def test_sampling_exceptions_are_distinct_from_generated_joint_data(monkeypatch):
    model=document();model["calibration"].update(enabled=True,trials_per_truth=2)
    def failed(*args,**kwargs):
        raise FloatingPointError("controlled draw overflow")
    monkeypatch.setattr(fm,"draw_data",failed)
    result=fm.calibrate(model);ensemble=result["ensembles"][0]
    assert ensemble["generated"]==0 and ensemble["attempted"]==ensemble["denominator"]==ensemble["failed"]==2
    assert ensemble["coverage_bounds_all_trials"]==[0.,1.]
    assert all(t["data"] is None and t["fit"]["failure_kind"]=="sampling_exception" for t in ensemble["trials"])
    json.dumps(result,allow_nan=False)


def test_raw_NET_or_denominator_overflow_refuses_before_numeric_inference():
    model=document();model["classes"][0]["contribution"]=[1e308,1e308]
    with pytest.raises(ValueError,match="NET expectation overflows"):
        fm.prepare(model)
    model=document("fixed_n_categories");model["classes"][0]["denominator_mark"]=1e308
    # A finite expected denominator can still yield an unrepresentable squared
    # denominator or derivative; this is a numerical refusal, not zero support.
    fm.prepare(model)
    with pytest.raises((ValueError,FloatingPointError)):
        fm.evaluate(model,model["comparison_points"][0])


@pytest.mark.parametrize("signed",[False,True])
def test_fixed_mu_fixed_N_requires_distinct_feasible_actual_simplex_starts(signed,monkeypatch):
    import scipy.optimize
    original=scipy.optimize.minimize;called=[]
    def recording(fun,x0,*args,**kwargs):
        called.append(np.asarray(x0).copy())
        return original(fun,x0,*args,**kwargs)
    monkeypatch.setattr(scipy.optimize,"minimize",recording)
    model=document("fixed_n_categories",signed)
    result=fm.fit(model,fixed_mu=1.)
    assert result["verified"],result
    assert len(called)>=2 and len({tuple(x) for x in called})==len(called)
    assert result["start_generation"]["distinct_seed_count"]==len(called)
    assert 0<result["start_generation"]["simplex_feasibility_LP_calls"]<=2*len(model["classes"])
    assert len(result["start_generation"]["simplex_feasibility_LP_attempts"])==result["start_generation"]["simplex_feasibility_LP_calls"]
    for index,start in enumerate(called):
        assert result["attempts"][index]["start_coordinates"]==start.tolist()
        point=result["attempts"][index]["start_parameters"]
        evaluated=fm.evaluate(model,point)
        assert abs(sum(point["nuisance"].values())-1)<1e-12
        assert all(v>=0 for v in evaluated["signal_expectation"]) and evaluated["expected_denominator"]>0
    verified=[row for row in result["attempts"] if row["verified"]]
    assert len({tuple(row["start_coordinates"]) for row in verified})>=2
    json.dumps(result,allow_nan=False)


def test_degenerate_physical_simplex_refuses_a_distinct_start_claim(monkeypatch):
    import scipy.optimize
    model=document("fixed_n_categories")
    model["classes"]=model["classes"][:2]
    for index,c in enumerate(model["classes"]):
        c.update(contribution=[1.,-1.] if index==0 else [-1.,1.],observed=5,
                 observed_group_ids=[f"fixed{index}-{j}" for j in range(5)],initial=.5)
    point={"mu":1.,"nuisance":{"class0":.5,"class1":.5}}
    model["comparison_points"]=[point,dict(point,mu=2.)];model["calibration"]["truths"]=[point]
    fm.prepare(model)
    monkeypatch.setattr(scipy.optimize,"minimize",lambda *a,**k:pytest.fail("unique physical simplex must refuse before claiming multistart profiling"))
    result=fm.fit(model,fixed_mu=1.)
    assert not result["verified"] and result["attempts"]==[]
    assert result["start_generation"]["distinct_seed_count"]==1
    assert result["start_generation"]["simplex_feasibility_LP_calls"]==4
    assert "genuinely distinct" in result["failure"]
    json.dumps(result,allow_nan=False)
