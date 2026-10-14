"""Continuum integrals, independent original-density fits and toy semantics."""
from copy import deepcopy
import hashlib
import json
import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
from ravel.physics import continuous_fit as cf


def document():
    params = {"mu": {"initial":1., "bounds":[0.,12.], "meaning":"signal strength"},
              "background_yield": {"initial":120., "bounds":[.01,1000.], "meaning":"FULL before transfer"},
              "slope": {"initial":-.35, "bounds":[-2.,2.], "meaning":"continuum coefficient"},
              "transfer_theta": {"initial":.15, "bounds":[-8.,8.], "meaning":"physical auxiliary truth"}}
    truth = {name:p["initial"] for name,p in params.items()}
    regions = [{"name":"CRleft", "role":"control", "edges":[0.,1.,2.], "observed":[35,27], "signal":[.2,.4], "observation_ids":["l0","l1"], "source":"synthetic"},
               {"name":"SR", "role":"signal", "edges":[2.,3.], "observed":[32], "signal":[8.], "observation_ids":["s0"], "source":"synthetic"},
               {"name":"CRright", "role":"control", "edges":[3.,4.,5.], "observed":[14,8], "signal":[.3,.1], "observation_ids":["r0","r1"], "source":"synthetic"}]
    return {"schema_version":1, "model_id":"synthetic-sideband", "question":"Joint source-bound continuous fit?",
            "sources":[{"id":"synthetic", "path":"source.txt", "sha256":"0"*64, "reference":"Hand supplied synthetic control"}],
            "full_range":[0.,5.], "background":{"family":"exponential", "yield_definition":"full_range_before_sr_transfer", "source":"synthetic"},
            "transfer":{"nominal":1.2, "log_sigma":.2, "observed_auxiliary":.15, "sampling_law":"z_normal_theta_unit_variance", "source":"synthetic", "meaning":"Supplied positive SR transfer"},
            "parameters":params, "regions":regions,
            "partition":{"boundary_convention":"half_open_final_closed", "source":"synthetic", "assertion":"Disjoint synthetic variable intervals"},
            "signal_statistics":{"mode":"conditional_fixed", "finite_mc":"not_modeled", "source":"synthetic", "meaning":"Exact conditional arrays, no inferred MC"},
            "comparison_points":[truth, dict(truth,mu=0.,slope=0.,transfer_theta=-.6)], "profile_points":[0.,1.,2.],
            "calibration":{"enabled":False,"seed":734910,"trials_per_truth":2,"truths":[truth],"nuisance_sampling":"fixed_truth","auxiliary_sampling":"gaussian_repeated","statistic":"two_sided_profile_lr","confidence_level":.95,"threshold":3.841458820694124,"interval_method":"fixed_threshold_confidence_set_inclusion","maxiter":500},
            "assumptions":["Exponential family is supplied, physical applicability untested.","Transfer auxiliary model is supplied.","Signals conditioned fixed, include CR contamination."]}


def bind(tmp_path,model=None):
    model = document() if model is None else deepcopy(model)
    source = tmp_path/"source.txt"
    source.write_text("Synthetic supplied counting model, not physical data.\n")
    model["sources"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    (tmp_path/"model.json").write_text(json.dumps(model))
    return model


def test_exact_integrals_flat_limit_and_original_density():
    from scipy.integrate import quad
    for slope in (-2.,-.35,-1e-12,0.,1e-12,.4,2.):
        for a,b in ((0.,5.),(.2,.201),(2.,3.)):
            expected = quad(lambda x: math.exp(slope*(x-.7)),a,b,epsabs=1e-12)[0]
            assert cf.exponential_integral(a,b,slope,.7) == pytest.approx(expected,rel=2e-12)
    assert cf.exponential_integral(10.,100.,0.) == 90.
    with pytest.raises(ValueError,match="increasing"):
        cf.exponential_integral(2.,1.,0.)


def test_flat_FULL_yield_transfer_and_all_region_signal():
    model = document()
    point = dict(model["comparison_points"][0],slope=0.,transfer_theta=0.)
    result = cf.evaluate(model,point)
    assert result["full_range_fractions"] == pytest.approx([.2]*5)
    assert result["background"] == pytest.approx([24.,24.,28.8,24.,24.])
    assert result["means"] == pytest.approx([24.2,24.4,36.8,24.3,24.1])
    assert sum(result["background"]) == pytest.approx(124.8)
    # Transfer modifies only SR; CR signals still enter the joint density.
    without = cf.evaluate(model,dict(point,mu=0.))
    assert np.subtract(result["means"],without["means"]) == pytest.approx([.2,.4,8.,.3,.1])
    expected = sum(m-n*math.log(m)+math.lgamma(n+1) for m,n in zip(result["means"],[35,27,32,14,8]))+.15**2/2+math.log(2*math.pi)/2
    assert result["nll"] == pytest.approx(expected,abs=2e-13)


def test_range_gaps_do_not_renormalize_FULL_yield():
    model = document()
    model["full_range"] = [-1.,6.]
    assert cf.prepare(model)
    point = dict(model["comparison_points"][0],slope=0.,mu=0.,transfer_theta=0.)
    result = cf.evaluate(model,point)
    assert result["full_range_fractions"] == pytest.approx([1/7]*5)
    assert sum(result["full_range_fractions"]) == pytest.approx(5/7)
    assert result["background"][0] == pytest.approx(120/7)


def test_pinned_ROOT_tutorial_LEFT_RIGHT_FULL_normalization():
    # ROOT v6-34-10 rf204b specifies FULL=[10,100], LEFT=[10,20],
    # RIGHT=[60,100], RooExponential coefficient=-.04. Bin probabilities
    # multiply N_FULL; independent subrange normalization would double-count N.
    model = document()
    model["full_range"] = [10.,100.]
    model["parameters"]["background_yield"].update(initial=10000.,bounds=[.01,20000.])
    model["parameters"]["slope"].update(initial=-.04,bounds=[-.1,.1])
    model["regions"][0]["edges"] = [10.,15.,20.]
    model["regions"][1]["edges"] = [20.,60.]
    model["regions"][2]["edges"] = [60.,80.,100.]
    point = {"mu":0.,"background_yield":10000.,"slope":-.04,"transfer_theta":0.}
    model["comparison_points"] = [point,dict(point,mu=1.,slope=0.)]
    model["calibration"]["truths"] = [point]
    assert cf.prepare(model)
    result = cf.evaluate(model,point)
    denominator = math.exp(-.04*10)-math.exp(-.04*100)
    left = (math.exp(-.04*10)-math.exp(-.04*20))/denominator
    right = (math.exp(-.04*60)-math.exp(-.04*100))/denominator
    assert sum(result["background"][:2]) == pytest.approx(10000*left,rel=1e-13)
    assert sum(result["background"][3:]) == pytest.approx(10000*right,rel=1e-13)
    assert sum(result["full_range_fractions"]) == pytest.approx(1.,abs=2e-15)
    assert left+right < .6
    assert cf.compare(model,model["comparison_points"])["passed"]


def test_all_gradients_match_original_density_finite_differences():
    model = document()
    for slope in (-.7,-1e-11,0.,1e-11,.8):
        point = dict(model["comparison_points"][0],slope=slope)
        result = cf.evaluate(model,point)
        for i,name in enumerate(cf.PARAMETERS):
            step = 1e-5 if name != "background_yield" else 1e-3
            up,down = dict(point),dict(point)
            up[name] += step
            down[name] -= step
            gradient = (cf.independent_quadrature(model,up)["nll"]-cf.independent_quadrature(model,down)["nll"])/(2*step)
            assert result["gradient"][i] == pytest.approx(gradient,abs=2e-6,rel=1e-7)


def test_quad_checker_is_independent_of_producer_integral(monkeypatch):
    model = document()
    def wrong(*args):
        return args[1]-args[0]
    monkeypatch.setattr(cf,"exponential_integral",wrong)
    result = cf.compare(model,model["comparison_points"])
    assert not result["passed"]
    assert result["points"][0]["max_mean_difference"] > 10


def test_exact_integer_recovery_is_global_saturated_likelihood_witness():
    model = document()
    model["transfer"].update(nominal=1.,observed_auxiliary=0.)
    model["regions"][0].update(signal=[1.,2.],observed=[22,24])
    model["regions"][1].update(signal=[8.],observed=[36])
    model["regions"][2].update(signal=[3.,1.],observed=[26,22])
    truth = {"mu":2.,"background_yield":100.,"slope":0.,"transfer_theta":0.}
    saturated = sum(n-n*math.log(n)+math.lgamma(n+1) for n in [22,24,36,26,22])+math.log(2*math.pi)/2
    fit = cf.fit(model)
    assert fit["verified"], fit
    assert fit["nll"] == pytest.approx(saturated,abs=1e-9)
    for name,value in truth.items():
        assert fit["parameters"][name] == pytest.approx(value,abs=5e-4)
    # Each independent Poisson factor and auxiliary reaches its own global max.
    assert cf.independent_quadrature(model,truth)["nll"] == pytest.approx(saturated,abs=1e-12)


def test_real_profile_matches_separate_quadrature_fit():
    from scipy.integrate import quad
    from scipy.optimize import minimize
    model = document()
    # Independent objective does not call any cf numerical function.
    def original(x,mu):
        yield_,slope,theta = math.exp(x[0]),x[1],x[2]
        norm = quad(lambda t: math.exp(slope*t),0.,5.)[0]
        means,counts = [],[]
        for region in model["regions"]:
            for a,b,s,n in zip(region["edges"],region["edges"][1:],region["signal"],region["observed"]):
                integral = quad(lambda t: math.exp(slope*t),a,b)[0]
                bkg = yield_*integral/norm
                if region["role"] == "signal":
                    bkg *= 1.2*math.exp(.2*theta)
                means.append(bkg+mu*s)
                counts.append(n)
        return sum(m-n*math.log(m)+math.lgamma(n+1) for m,n in zip(means,counts))+(theta-.15)**2/2+math.log(2*math.pi)/2
    independent = minimize(lambda x:original(x,1.),[math.log(120),-.35,.15],method="Nelder-Mead",options={"maxiter":1500,"xatol":1e-9,"fatol":1e-11})
    assert independent.success
    result = cf.profile(model,[0.,1.,2.])
    assert result["verified"], result
    conditional = result["profiles"][1]["fit"]
    assert conditional["nll"] == pytest.approx(independent.fun,abs=1e-8)
    assert conditional["parameters"]["background_yield"] == pytest.approx(math.exp(independent.x[0]),abs=2e-4)
    assert conditional["parameters"]["slope"] == pytest.approx(independent.x[1],abs=2e-6)
    assert conditional["parameters"]["transfer_theta"] == pytest.approx(independent.x[2],abs=2e-5)
    assert result["profiles"][1]["twice_delta_nll"] > 0
    assert {r["method"] for r in conditional["attempts"] if r["verified"]} == {"L-BFGS-B","SLSQP"}


def test_flat_local_degeneracy_is_not_cured_by_bounds():
    model = document()
    point = dict(model["comparison_points"][0],slope=0.,transfer_theta=0.)
    model["parameters"]["slope"]["initial"] = 0.
    model["parameters"]["transfer_theta"]["initial"] = 0.
    model["transfer"]["nominal"] = 1.
    model["transfer"]["observed_auxiliary"] = 0.
    for region in model["regions"]:
        region["signal"] = [1.]*(len(region["edges"])-1)
        region["observed"] = [20]*(len(region["edges"])-1)
    check = cf.identifiability(model,point)
    assert not check["identified"] and check["rank"] == 3
    assert check["null_directions_in_physical_coordinates"]
    assert not cf.fit(model)["verified"]


def test_false_solver_success_is_refused(monkeypatch):
    import scipy.optimize
    from types import SimpleNamespace
    def false(fun,x0,**kwargs):
        return SimpleNamespace(x=x0,success=True,message="fake success",nit=0)
    monkeypatch.setattr(scipy.optimize,"minimize",false)
    result = cf.fit(document())
    assert not result["verified"]
    assert all(r["projected_gradient_max"] > 1e-4 for r in result["attempts"])


def test_artificial_caps_are_retained_as_unresolved():
    model = document()
    model["parameters"]["background_yield"]["bounds"][1] = 121.
    for region in model["regions"]:
        region["observed"] = [1000]*len(region["observed"])
    result = cf.fit(model)
    assert not result["verified"]
    assert any(any(b["parameter"] == "background_yield" and not b["physical"] for b in r.get("active_bounds",[])) for r in result["attempts"])


@pytest.mark.parametrize("change",[
    lambda d:d["regions"][0].update(signal=[0.,0.]),
    lambda d:d["regions"][0].update(signal=[-.2,.4]),
    lambda d:d["regions"][2].update(edges=[2.9,4.,5.]),
    lambda d:d["regions"][2].update(observation_ids=["l0","r1"]),
    lambda d:d["regions"][0].update(observed=[35.5,27]),
    lambda d:d["signal_statistics"].update(finite_mc="poisson_invented"),
    lambda d:d["background"].update(yield_definition="fit_range"),
    lambda d:d["transfer"].update(nominal=-1.),
    lambda d:d["transfer"].update(log_sigma=0.),
    lambda d:d["calibration"].update(nuisance_sampling="prior_draw"),
    lambda d:d["calibration"].update(auxiliary_sampling="fixed_observed"),
    lambda d:d["calibration"].update(trials_per_truth=257),
    lambda d:d["regions"][0].update(source="unbound"),
    lambda d:d["parameters"]["slope"].update(bounds=[-100.,100.]),
    lambda d:d["profile_points"].append(20.),
])
def test_semantic_adversaries_fail_before_inference(change):
    model = document()
    change(model)
    with pytest.raises(ValueError):
        cf.prepare(model)


def test_custody_hash_duplicate_json_and_symlinks(tmp_path):
    bind(tmp_path)
    assert len(cf.inputs({"input":"model.json"},tmp_path)) == 2
    (tmp_path/"source.txt").write_text("mutated\n")
    with pytest.raises(ValueError,match="hash mismatch"):
        cf.inputs({"input":"model.json"},tmp_path)
    (tmp_path/"bad.json").write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError):
        cf.inputs({"input":"bad.json"},tmp_path)
    (tmp_path/"link.json").symlink_to(tmp_path/"model.json")
    with pytest.raises(ValueError,match="regular file"):
        cf.inputs({"input":"link.json"},tmp_path)


def test_changed_model_source_inventory_during_capture_fails_cleanly(tmp_path,monkeypatch):
    from pathlib import Path
    model = bind(tmp_path)
    read = Path.read_bytes
    accesses = 0
    def change_inventory(path):
        nonlocal accesses
        if path.name == "model.json":
            accesses += 1
            if accesses == 2:
                model["sources"][0]["path"] = "new-source.txt"
                return json.dumps(model).encode()
        return read(path)
    monkeypatch.setattr(Path,"read_bytes",change_inventory)
    with pytest.raises(ValueError,match="changed during capture"):
        cf.run({"input":"model.json"},tmp_path,tmp_path/"outputs")


def test_bounded_toys_repeat_auxiliary_at_fixed_nuisance_truth():
    model = document()
    model["calibration"]["enabled"] = True
    model["calibration"]["trials_per_truth"] = 2
    result = cf.calibrate(model)
    assert result["executed"] and result["all_fits_resolved"], result
    ensemble = result["ensembles"][0]
    assert ensemble["generated_trials"] == ensemble["resolved_trials"] == 2
    truth = model["calibration"]["truths"][0]
    rng = np.random.default_rng(model["calibration"]["seed"])
    for trial in ensemble["trials"]:
        expected_counts = rng.poisson(cf.evaluate(model,truth)["means"]).tolist()
        expected_z = float(rng.normal(truth["transfer_theta"],1.))
        assert trial["data"] == {"counts":expected_counts,"auxiliary":expected_z}
        assert trial["data"]["auxiliary"] != model["transfer"]["observed_auxiliary"]
        assert trial["fits"]["profiles"][0]["fit"]["fixed_mu"] == truth["mu"]
    assert ensemble["coverage_mcse_upper_bound"] == pytest.approx(.5/math.sqrt(2))
    assert len(ensemble["exact_binomial_intervals_failure_exclude_include"]) == 2
    assert "finite signal MC" in " ".join(result["limits"])


def test_failed_toys_are_kept_in_full_denominator(monkeypatch):
    model = document()
    model["calibration"]["enabled"] = True
    def fail(*args,**kwargs):
        return {"verified":False,"global_fit":{"verified":False},"profiles":[{"twice_delta_nll":None,"fit":{"verified":False}}]}
    monkeypatch.setattr(cf,"profile",fail)
    result = cf.calibrate(model)
    ensemble = result["ensembles"][0]
    assert not result["all_fits_resolved"]
    assert ensemble["generated_trials"] == ensemble["failed_trials"] == 2
    assert ensemble["coverage_bounds_all_trials"] == [0.,1.]
    assert ensemble["signal_bias_resolved_only"] is None
    assert len(ensemble["trials"]) == 2


def test_actual_task_outputs_have_limited_scope_and_source_identity(tmp_path):
    bind(tmp_path)
    result = cf.run({"input":"model.json"},tmp_path,tmp_path/"outputs")
    assert result["status"] == "passed", result
    assert not result["physics_validated"] and result["numerical_inference"]
    assert not result["calibration"]["executed"]
    assert result["comparison"]["passed"]
    assert len(result["input_snapshot"]) == 2
    assert (tmp_path/"outputs/continuous_fit_profile.json").is_file()
    assert (tmp_path/"outputs/continuous_fit_contract.json").is_file()


def test_mu_zero_boundary_and_two_truth_toy_outputs_are_plain_JSON(tmp_path):
    model = document()
    # SR below the continuum prediction gives a physical mu=0 optimum. This
    # exercised the real acceptance failure: NumPy boundary flags escaped in
    # fit.attempts[*].active_bounds[*].physical and json.dumps rejected bool_.
    model["regions"][1]["observed"] = [20]
    model["calibration"].update(enabled=True,trials_per_truth=2)
    truth = model["calibration"]["truths"][0]
    model["calibration"]["truths"].append(dict(truth,mu=0.,transfer_theta=-.5))
    bind(tmp_path,model)
    result = cf.run({"input":"model.json"},tmp_path,tmp_path/"outputs")
    assert result["status"] == "passed", result
    fitted = result["profile"]["global_fit"]
    assert fitted["parameters"]["mu"] == pytest.approx(0.,abs=1e-10)
    physical_bounds = [bound for attempt in fitted["attempts"] for bound in attempt["active_bounds"]
                       if bound["parameter"] == "mu" and bound["side"] == "lower"]
    assert physical_bounds
    assert all(type(bound["physical"]) is bool and bound["physical"] for bound in physical_bounds)
    calibration = result["calibration"]
    assert calibration["executed"] and calibration["all_fits_resolved"]
    assert len(calibration["ensembles"]) == 2
    assert sum(e["generated_trials"] for e in calibration["ensembles"]) == 4
    assert calibration["ensembles"][1]["truth"]["mu"] == 0.
    # No default serializer or blanket NumPy conversion may hide output types.
    assert json.loads(json.dumps(result,allow_nan=False)) == result
    expected = {"continuous_fit_result.json":result,"continuous_fit_contract.json":json.loads((tmp_path/"model.json").read_text()),
                "continuous_fit_comparison.json":result["comparison"],"continuous_fit_profile.json":result["profile"],
                "continuous_fit_calibration.json":calibration}
    for name,value in expected.items():
        assert json.loads((tmp_path/"outputs"/name).read_text()) == value
