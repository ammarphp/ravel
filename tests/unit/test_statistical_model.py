"""New-analysis construction, independent witnesses and actual quantity bridge."""
from copy import deepcopy
import hashlib
import json
import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("pyhf")

from ravel.physics.statistical_model import (
    prepare, compile_model, evaluate, identifiability, compare_likelihoods,
    fit, inputs, run, moment_log_response, attach_quantity_uncertainty,
)
from ravel.physics.quantities import calculate


def document():
    return {"schema_version": 1, "model_id": "synthetic-contaminated-control", "question": "Can a shared control yield distinguish signal from background?",
            "sources": [{"id": "synthetic", "path": "source.txt", "sha256": "0"*64}],
            "parameters": [{"name": "mu", "role": "poi", "initial": 1., "bounds": [0., 20.], "meaning": "supplied signal strength"},
                           {"name": "beta", "role": "rate", "initial": 10., "bounds": [0., 100.], "meaning": "SR background event yield"}],
            "bins": [{"id": "SR", "role": "signal", "observed": 12, "observation_id": "sample:SR", "source": "synthetic"},
                     {"id": "CR", "role": "control", "observed": 24, "observation_id": "sample:CR", "source": "synthetic"}],
            "components": [{"id": "signal", "nominal": [5., 1.], "factors": [["mu"], ["mu"]], "log_response": [[], []], "source": "synthetic"},
                           {"id": "background", "nominal": [1., 2.], "factors": [["beta"], ["beta"]], "log_response": [[], []], "source": "synthetic"}],
            "auxiliary": {"names": [], "observed": [], "covariance": [], "source": None},
            "partition": {"kind": "disjoint", "source": "synthetic", "overlap_counts": [[12, 0], [0, 24]]},
            "template_statistics": {"kind": "conditional_fixed", "reason": "Synthetic exact coefficients, no MC sample", "source": "synthetic"},
            "assumptions": [{"id": "A1", "statement": "Disjoint independent Poisson observations with fixed transfer factor 2", "source": "synthetic", "status": "assumed"}]}


def task():
    return {"input": "model.json", "profile_points": [1.], "comparison_points": [{"mu": 0., "beta": 12.}, {"mu": 1., "beta": 10.325485849042453}, {"mu": 2., "beta": 9.}]}


def bind(tmp_path, model=None):
    model = document() if model is None else model
    (tmp_path/"source.txt").write_text("Explicitly synthetic analytic count control, not collision data.\n")
    model["sources"][0]["sha256"] = hashlib.sha256((tmp_path/"source.txt").read_bytes()).hexdigest()
    (tmp_path/"model.json").write_text(json.dumps(model))
    return model


def correlated():
    model = document()
    model["auxiliary"] = {"names": ["a", "b"], "observed": [.3, -.1], "covariance": [[1., .5], [.5, 1.]], "source": "synthetic"}
    model["components"][0]["log_response"] = [[.2, .1], [.2, .1]]
    model["components"][1]["log_response"] = [[.1, -.2], [0., 0.]]
    return model


def abcd():
    model = document()
    model["model_id"] = "synthetic-abcd"
    model["parameters"][1]["initial"] = 20.
    for name in ("rx", "ry"):
        model["parameters"].append({"name": name, "role": "rate", "initial": 1., "bounds": [0., 10.], "meaning": "background sideband ratio"})
    model["bins"] = [{"id": name, "role": "signal" if name == "A" else "control", "observed": count,
                      "observation_id": f"sample:{name}", "source": "synthetic"} for name,count in zip("ABCD",[12,18,8,22])]
    model["partition"]["overlap_counts"] = [[(row["observed"] if i==j else 0) for j in range(4)] for i,row in enumerate(model["bins"])]
    model["components"][0].update(nominal=[5.,0.,0.,0.], factors=[["mu"] for _ in range(4)], log_response=[[] for _ in range(4)])
    model["components"][1].update(nominal=[1.,1.,1.,1.], factors=[["beta","rx","ry"],["beta","rx"],["beta","ry"],["beta"]],log_response=[[] for _ in range(4)])
    model["assumptions"][0]["statement"] = "ABCD factorization imposed as a synthetic model; real sideband closure would need separate evidence"
    return model


def test_contaminated_control_matches_independent_closed_form():
    model = document()
    assert prepare(model)["poi"] == "mu"
    check = compare_likelihoods(model, task()["comparison_points"])
    assert check["passed"]
    assert check["max_absolute_residual"] < 1e-12
    best = fit(model)
    profile = fit(model, fixed=1.)
    assert best["verified"] and profile["verified"]
    assert best["parameters"]["mu"] == pytest.approx(0., abs=1e-6)
    assert best["parameters"]["beta"] == pytest.approx(12., abs=1e-5)
    assert profile["parameters"]["beta"] == pytest.approx((39+math.sqrt(7209))/12, abs=2e-5)
    assert 2*(profile["nll_without_constant"]-best["nll_without_constant"]) == pytest.approx(1.0264300139475324, abs=1e-8)


def test_signal_injection_recovery_with_control_leakage():
    model = document()
    model["bins"][0]["observed"], model["bins"][1]["observed"] = 15,21
    model["partition"]["overlap_counts"] = [[15,0],[0,21]]
    result = fit(model)
    assert result["verified"]
    assert result["parameters"] == pytest.approx({"mu":1.,"beta":10.}, abs=1e-5)


def test_abcd_product_factors_match_exact_independence_witness():
    model=abcd()
    best=fit(model)
    zero=fit(model,fixed=0.)
    assert best["verified"] and zero["verified"]
    assert best["parameters"] == pytest.approx({"mu":12/11,"beta":22.,"rx":18/22,"ry":8/22}, abs=2e-4)
    assert zero["means"] == pytest.approx([10.,20.,10.,20.],abs=2e-4)
    assert 2*(zero["nll_without_constant"]-best["nll_without_constant"]) == pytest.approx(1.2060898897361056,abs=1e-8)


def test_correlated_auxiliary_whitening_nonzero_observation_and_code1():
    model=correlated()
    point={"mu":1.,"beta":12.,"a":1.,"b":-1.}
    value=evaluate(model,point)
    assert value["auxiliary_nll"] == pytest.approx(193/150)
    assert value["means"] == pytest.approx([5*math.exp(.1)+12*math.exp(.3),math.exp(.1)+24])
    points=[point,{"mu":.7,"beta":10.,"a":.37,"b":-.29},{"mu":2.,"beta":8.,"a":-1.3,"b":.8}]
    bundle=compile_model(model)
    assert compare_likelihoods(model,points,bundle)["passed"]
    bundle["model_settings"]["modifier_settings"]["normsys"]["interpcode"]="code4"
    assert not compare_likelihoods(model,points,bundle)["passed"]


def test_bin_order_and_component_order_do_not_change_likelihood():
    model=correlated()
    other=deepcopy(model)
    other["bins"].reverse()
    other["partition"]["overlap_counts"]=[[24,0],[0,12]]
    other["components"].reverse()
    for row in other["components"]:
        for key in ("nominal","factors","log_response"):
            row[key].reverse()
    point={"mu":1.,"beta":12.,"a":1.,"b":-1.}
    assert evaluate(other,point)["nll_without_constant"] == pytest.approx(evaluate(model,point)["nll_without_constant"])
    assert compare_likelihoods(other,[point,{**point,"a":.5}])["passed"]


def test_confounding_is_diagnostic_not_fake_fit_limit(tmp_path):
    model=document();model["components"][0]["nominal"][1]=10.
    assert not identifiability(model)["identified"]
    assert not identifiability(model)["poi_identifiable"]
    bind(tmp_path,model)
    result=run(task(),tmp_path,tmp_path/"out")
    assert result["status"]=="passed"
    assert result["model_assessment"]=="unidentified"
    assert result["fit"] is None and result["inference"] is None
    assert result["physics_validated"] is False


def test_identifiability_is_invariant_under_rate_unit_rescaling():
    baseline=identifiability(document())
    other=document()
    other["parameters"][1]["initial"]*=1e14
    other["parameters"][1]["bounds"][1]*=1e14
    other["components"][1]["nominal"]=[x/1e14 for x in other["components"][1]["nominal"]]
    scaled=identifiability(other)
    assert scaled["rank"] == baseline["rank"] == 2
    assert scaled["singular_values"] == pytest.approx(baseline["singular_values"])


def test_run_retains_model_settings_basis_and_no_exclusion_claim(tmp_path):
    bind(tmp_path)
    result=run(task(),tmp_path,tmp_path/"out")
    assert result["status"]=="passed" and result["fit"]["verified"]
    assert result["profiles"][0]["q_mu"] == pytest.approx(1.0264300139475324,abs=1e-8)
    assert result["inference"] is None and not result["physics_validated"]
    assert json.loads((tmp_path/"out/model-settings.json").read_text())["modifier_settings"]["normsys"]["interpcode"]=="code1"
    assert (tmp_path/"out/model-basis.json").is_file()
    with pytest.raises(FileExistsError):
        run(task(),tmp_path,tmp_path/"out")


@pytest.mark.parametrize("change,match",[
    (lambda m:m["bins"][0].update(observed=1.5),"integer"),
    (lambda m:m["bins"][0].update(observed=True),"integer"),
    (lambda m:m["bins"][1].update(role="validation"),"held out"),
    (lambda m:m["bins"][1].update(observation_id="sample:SR"),"unique"),
    (lambda m:m["partition"]["overlap_counts"][0].__setitem__(1,1),"overlapping"),
    (lambda m:m["components"][0]["nominal"].__setitem__(0,-1.),"nonnegative"),
    (lambda m:m["components"][0]["nominal"].pop(),"exactly"),
    (lambda m:m["components"][0]["factors"].pop(),"every bin"),
    (lambda m:m["components"][0]["factors"][0].append("mu"),"unique known"),
    (lambda m:m["parameters"][0].update(initial=0.),"strictly"),
    (lambda m:m["components"][0].update(source="invented"),"unknown scientific"),
    (lambda m:m["template_statistics"].update(kind="independent_bin_errors"),"template statistics"),
])
def test_rejects_invalid_model_semantics(change,match):
    model=document();change(model)
    with pytest.raises(ValueError,match=match):prepare(model)


def test_auxiliary_covariance_cannot_be_regularized_or_silently_diagonalized():
    model=correlated();model["auxiliary"]["covariance"]=[[1,1],[1,1]]
    with pytest.raises(ValueError,match="positive definite"):prepare(model)
    model["auxiliary"]["covariance"]=[[1,.5],[.2,1]]
    with pytest.raises(ValueError,match="symmetric"):prepare(model)


def test_input_custody_binds_secondary_artifacts_and_detects_mutation(tmp_path):
    bind(tmp_path)
    assert len(inputs(task(),tmp_path))==2
    (tmp_path/"source.txt").write_text("changed")
    with pytest.raises(ValueError,match="hash mismatch"):inputs(task(),tmp_path)


def test_input_custody_rejects_source_parent_symlink(tmp_path):
    bind(tmp_path)
    real=tmp_path/"real";real.mkdir();(real/"data").write_text("x")
    (tmp_path/"link").symlink_to(real,target_is_directory=True)
    model=document();model["sources"][0]["path"]="link/data"
    model["sources"][0]["sha256"]=hashlib.sha256(b"x").hexdigest()
    (tmp_path/"model.json").write_text(json.dumps(model))
    with pytest.raises(ValueError,match="symlink"):inputs(task(),tmp_path)


def quantities(tmp_path, normalized=False):
    contract={"schema_version":1,"axes":[{"name":"bin","unit":"1"}],
              "bins":[{"id":"SR","low":[0],"high":[1]},{"id":"CR","low":[1],"high":[2]}],
              "weight_names":["nominal"],"input_weight_unit":"events","representation":"integrated",
              "normalization":{"kind":"normalized","scope":"in_range"} if normalized else {"kind":"absolute","scale":1.,"unit":"events"}}
    rows=[{"event_id":"a","group_id":"g","shard_id":"s","weights":{"nominal":2.},"fills":[[.5]]},
          {"event_id":"b","group_id":"g","shard_id":"s","weights":{"nominal":-1.},"fills":[[1.5]]},
          {"event_id":"c","group_id":"h","shard_id":"s","weights":{"nominal":3.},"fills":[[.5]]},
          {"event_id":"d","group_id":"i","shard_id":"s","weights":{"nominal":2.},"fills":[[1.5]]}]
    value=calculate(contract,rows)
    path=tmp_path/"quantity.json";path.write_text(json.dumps(value))
    evidence={"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    return value,evidence


def test_actual_signed_group_quantity_covariance_reaches_shared_template_model(tmp_path):
    value,evidence=quantities(tmp_path)
    assert value["values"]["nominal"]==[5.,1.]
    assert value["covariance"]==[[13.,-2.],[-2.,5.]]
    mapping=[{"coordinate":coord,"component":"signal","bin_id":coord["bin_id"]} for coord in value["covariance_order"]]
    attached=attach_quantity_uncertainty(document(),value,mappings=mapping,evidence=evidence,source_id="mc",
                                          interpretation="Use full Poissonized independent-group covariance as a declared local Gaussian approximation")
    out=attached["propagation"]
    assert out["covariance"]==[[13.,-2.],[-2.,5.]]
    assert out["reconstruction_residual"]<1e-12
    model=attached["document"]
    point={"mu":1.,"beta":10.,**dict.fromkeys(model["auxiliary"]["names"],0.)}
    shifted={**point,model["auxiliary"]["names"][0]:.37}
    assert compare_likelihoods(model,[point,shifted])["passed"]
    assert model["template_statistics"]["kind"]=="supplied_log_gaussian_approximation"
    assert "First-order" in model["assumptions"][-1]["statement"]


def test_quantity_bridge_refuses_normalization_and_unbound_or_mixed_sources(tmp_path):
    value,evidence=quantities(tmp_path,normalized=True)
    with pytest.raises(ValueError,match="absolute"):
        moment_log_response(value,coordinates=value["covariance_order"],evidence=evidence,interpretation="explicit")
    value,evidence=quantities(tmp_path)
    changed=deepcopy(value);changed["covariance"][0][1]=0.
    with pytest.raises(ValueError,match="evidence bytes"):
        moment_log_response(changed,coordinates=value["covariance_order"],evidence=evidence,interpretation="explicit")
    with pytest.raises(ValueError,match="joint correlation"):
        attach_quantity_uncertainty(correlated(),value,mappings=[],evidence=evidence,source_id="mc",interpretation="explicit")


def test_unknown_cross_coordinate_uncertainty_is_not_diagonalized(tmp_path):
    value,evidence=quantities(tmp_path)
    out=moment_log_response(value,coordinates=list(reversed(value["covariance_order"])),evidence=evidence,interpretation="explicit")
    assert out["covariance"]==[[5.,-2.],[-2.,13.]]
    with pytest.raises(ValueError,match="duplicate selected"):
        moment_log_response(value,coordinates=[value["covariance_order"][0]]*2,evidence=evidence,interpretation="explicit")


def test_positive_lower_fit_cap_cannot_create_a_verified_background_fit():
    model=document()
    model["parameters"][1].update(initial=20.,bounds=[15.,100.])
    result=fit(model)
    assert not result["verified"]
    assert {"parameter":"beta","boundary":"positive_lower_fit_cap"} in result["active_numerical_bounds"]


def test_two_optimizers_returning_the_initial_vector_do_not_pass_by_agreement(monkeypatch):
    from types import SimpleNamespace
    import scipy.optimize
    import pyhf
    def unchanged(objective, x0, **kwargs):
        return SimpleNamespace(x=np.asarray(x0),fun=objective(x0),success=True,message="fault-injected stale vector",nfev=1)
    def compiled_unchanged(data, model, **kwargs):
        return np.asarray(kwargs["init_pars"]), np.asarray(0.)
    monkeypatch.setattr(scipy.optimize,"minimize",unchanged)
    monkeypatch.setattr(pyhf.infer.mle,"fit",compiled_unchanged)
    result=fit(document())
    assert not result["verified"]
    assert not result["stationarity"]["passed"]
    assert result["solver_nll_difference"]==0.


def test_source_mutation_during_fit_cannot_receive_new_input_identity(tmp_path, monkeypatch):
    import ravel.physics.statistical_model as module
    bind(tmp_path)
    real_fit=module.fit
    def mutate(*args,**kwargs):
        result=real_fit(*args,**kwargs)
        (tmp_path/"source.txt").write_text("source changed during numerical computation")
        return result
    monkeypatch.setattr(module,"fit",mutate)
    with pytest.raises(ValueError,match="changed during"):
        run(task(),tmp_path,tmp_path/"out")
    assert not (tmp_path/"out").exists()


def test_source_mutation_after_input_validation_is_rejected(tmp_path,monkeypatch):
    import ravel.physics.statistical_model as module
    bind(tmp_path)
    real_inputs=module.inputs
    def mutate(*args,**kwargs):
        paths=real_inputs(*args,**kwargs)
        (tmp_path/"source.txt").write_text("mutated after validation")
        return paths
    monkeypatch.setattr(module,"inputs",mutate)
    with pytest.raises(ValueError,match="between validation and capture"):
        run(task(),tmp_path,tmp_path/"out")
    assert not (tmp_path/"out").exists()


def test_model_mutation_after_input_validation_cannot_rebind_recipe(tmp_path,monkeypatch):
    import ravel.physics.statistical_model as module
    bind(tmp_path)
    real_inputs=module.inputs
    def mutate(*args,**kwargs):
        paths=real_inputs(*args,**kwargs)
        model=json.loads((tmp_path/"model.json").read_text())
        model["question"]="different recipe after validation"
        (tmp_path/"model.json").write_text(json.dumps(model))
        return paths
    monkeypatch.setattr(module,"inputs",mutate)
    with pytest.raises(ValueError,match="between capture and validation"):
        run(task(),tmp_path,tmp_path/"out")
