"""Supplied-clock resource/retention controls. No real model or solver calls."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
HERE=Path(__file__).resolve().parent
from ravel.physics import joint_score as a
@pytest.fixture(autouse=True)
def no_actual_science(monkeypatch):
 def no(*args,**kwargs):pytest.fail("Actual scientific call forbidden in timing transport control")
 import pyhf,scipy.optimize,subprocess
 monkeypatch.setattr(pyhf,"Workspace",no);monkeypatch.setattr(pyhf,"Model",no)
 monkeypatch.setattr(scipy.optimize,"minimize",no);monkeypatch.setattr(scipy.optimize,"linprog",no)
 monkeypatch.setattr(subprocess,"Popen",no);monkeypatch.setattr(a.physics_review,"snapshot",no)

def harness(monkeypatch, *, final_failure=False, advance_fit=1., initial_failure=False, late_hard_stop=False, initial_elapsed=0., endpoint_elapsed=0., final_elapsed=0.):
    clock=[0.];events=[]; fits=[];oracle_calls=[]
    monkeypatch.setattr(a,"time",SimpleNamespace(monotonic=lambda:clock[0]))
    snapshot={"scope":"supplied transport fixture"}
    class Session:
        def __init__(self,contract,receipt,directory,worker_started):
            assert worker_started==0.;self.directory=directory;directory.mkdir()
            events.append("session")
        def boundary(self,phase):
            events.append(phase)
            clock[0]+=initial_elapsed if phase=="initial" else final_elapsed
            if initial_failure and phase=="initial":raise ValueError("supplied initial refusal")
            if final_failure and phase=="final":raise ValueError("supplied final refusal")
            (self.directory/(phase+"-returned.json")).write_text('{"supplied":true}')
            return {"path":"/supplied/"+phase,"sha256":"a"*64}
    boundary=SimpleNamespace(WorkerSession=Session,
        verify_receipt=lambda *args:{"snapshot":snapshot},inputs=lambda *args:[],
        hook_resource_bounds=lambda *args:{"metadata_children_per_worker":2})
    qualification={"module":boundary,"contract":{"budget":{"worker_inner_seconds":25.,"solver_work_cutoff_seconds":22.,"initial_capture_compile_gate_seconds":2.,"final_gate_reservation_seconds":3.,"complete_worker_seconds":30.}},"receipt":{}}
    design={"resource_bounds":{"execution_seconds":30},"fit_protocol":{"mu_domain":{},"budget_per_fit":{"wall_seconds":4.5},"solver_options":{"mean_floor":1e-12,"diagonal_regularization":1e-8},"rate_caps":{},"endpoint_budget":{"wall_seconds":1.,"density_wrapper_calls":3,"pyhf_main_calls":9,"source_auxiliary_factor_calls":12,"MC_density_calls":3}}}
    cases=[({"id":case,"source_bound_semantics":{}},{}, {}, object()) for case in ("CASE-0001", "CASE-0002")]
    design.update(study_id="STUDY-0001",parameter_grid=[{"name":"coordinate","values":[1,2]}],dataset_population=["DATA-0001"],delivery={"format":"json","filename":"supplied-results.json"},cases=[c[0] for c in cases],objectives=[{"id":"free_mu","fixed_mu":None},{"id":"fixed_mu1","fixed_mu":1.}],comparisons=[{"id":"contrast","left":"free_mu","right":"fixed_mu1","scale":2.,"minimum":0.,"atol":1e-5}])
    for i,c in enumerate(design['cases']):
        c.update(expected_free_coordinates={'free_mu':5,'fixed_mu1':4},original_named_seeds=[{'id':'SEED-'+str(j)} for j in range(3)],parameter_point={'coordinate':i+1},dataset_id='DATA-0001')
    capture={"qualification":qualification,"design":design,"input":{},"snapshot":snapshot,
             "source_compatibility":{},"captured":{},"cases":cases,"background":{},
             "law":{"measurement":"supplied","qualification":{"nll_atol":1e-8,"mean_atol":1e-8,"mean_rtol":1e-9}}}
    monkeypatch.setattr(a,"_capture",lambda *args:capture)
    monkeypatch.setattr(a,"_unchanged",lambda *args:None)
    monkeypatch.setattr(a,"_compile",lambda *args:(object(),object()))
    monkeypatch.setattr(a,"_support_diagnostics",lambda *args:{"scope":"supplied transport fixture"})
    monkeypatch.setattr(a,"_starts",lambda *args:([[0.]*len(args[0].axes)]*3,[{"original_seed_id":i} for i in range(3)]))
    class Problem:
        def __init__(self,*args,fixed_mu=None,**kwargs):self.fixed_mu=fixed_mu;self.axes=list(range(5 if fixed_mu is None else 4))
    class Continuation:
        def __init__(self,**kwargs):pass
        def fit(self,problem,starts,budget,wall_hook):
            if late_hard_stop and len(fits)==1:raise KeyboardInterrupt("supplied later solver stop")
            assert not wall_hook();clock[0]+=advance_fit
            nll=3. if problem.fixed_mu is None else 3.25
            points=[{"mu":1.+i,"source":{},"latent":{},"supplied_nll":nll} for i in range(3)]
            fit={"verified":True,"nll":nll,"parameters":deepcopy(points[0]),"attempts":[
                {"original_seed_id":i,"parameters":point,"nll":nll,"main_means":[2.,3.]} for i,point in enumerate(points)]}
            fits.append({"free_dimension":len(problem.axes),"starts":len(starts),"budget":budget})
            return fit
    monkeypatch.setattr(a,"_solver_module",lambda *args:SimpleNamespace(JointScoreProblem=Problem,ScoreContinuation=Continuation))
    class Budget:
        def __init__(self,limits,deadline):self.used={};self.deadline=deadline
        def check(self):
            if clock[0]>=self.deadline:raise TimeoutError("supplied endpoint cutoff")
    class Oracle:
        def __init__(self,*args):self.budget=args[-1]
        def evaluate(self,point):
            self.budget.check();clock[0]+=endpoint_elapsed;oracle_calls.append(deepcopy(point))
            return {"nll":point["supplied_nll"],"main_means":[2.,3.],"distribution_mean_vector":[2.,3.,0.,30.,270.]}
    monkeypatch.setattr(a.q,"QualificationBudget",Budget)
    monkeypatch.setattr(a.q,"IndependentSourceOracle",Oracle)
    return events,fits,oracle_calls,clock,capture

def test_entire_near_maximum_allocation_delivers_all_four_and_twelve(tmp_path,monkeypatch):
 events,fits,calls,clock,_=harness(monkeypatch,advance_fit=4.4,initial_elapsed=1.9,endpoint_elapsed=.2,final_elapsed=2.9)
 r=a.run({"input":"supplied"},HERE,tmp_path)
 assert r["status"]=="passed"
 assert len(fits)==4 and len(calls)==12 and [x["free_dimension"] for x in fits]==[5,4,5,4]
 assert r["common_solver_endpoint_cutoff_seconds"]==22. and r["common_final_gate_cutoff_seconds"]==25.
 assert 24.<r["elapsed_seconds"]<25.
 assert len(list(tmp_path.glob("*--oracle-return-*.json")))==12
 assert all(x["budget"]["wall_seconds"]==4.5 for x in fits)

def test_initial_expiry_leaves_four_plans_without_fit(tmp_path,monkeypatch):
 events,fits,calls,clock,_=harness(monkeypatch,initial_elapsed=2.)
 r=a.run({"input":"supplied"},HERE,tmp_path)
 assert r["status"]=="unresolved" and not fits and not calls
 assert len(r["fits"])==4 and all(x["status"]=="not_started" for x in r["fits"])

def test_final_expiry_preserves_four_returns_without_admission(tmp_path,monkeypatch):
 _,fits,calls,_,_=harness(monkeypatch,advance_fit=4.4,initial_elapsed=1.9,endpoint_elapsed=.2,final_elapsed=4.9)
 r=a.run({"input":"supplied"},HERE,tmp_path)
 assert r["status"]=="unresolved" and r["custody_refusal"]
 assert len(fits)==4 and len(calls)==12 and all(x["status"]=="completed" for x in r["fits"])

def test_late_solver_failure_retains_completed_case(tmp_path,monkeypatch):
 _,_,_,_,_=harness(monkeypatch,late_hard_stop=True)
 with pytest.raises(KeyboardInterrupt):a.run({"input":"supplied"},HERE,tmp_path)
 assert len(list(tmp_path.glob("*--checked.json")))==1
 assert len(list(tmp_path.glob("*--oracle-return-*.json")))==3

