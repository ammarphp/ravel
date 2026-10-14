"""Portable stationarity geometry and returned-evidence regressions.

Only built-in synthetic source/MC fixtures and supplied solver endpoints are used.
No private candidate/archive paths or external physics inputs are required.
"""
import hashlib
import json
import math
from types import SimpleNamespace
import numpy as np
import pytest
import scipy.optimize
from ravel.physics import joint_analytic as new_analytic, joint_profile as new_profile, finite_mc_model as new_finite
from ravel.physics.mc_auxiliary import MCAuxiliaryBlock,compact
from ravel.physics.published_background import BackgroundAuxBlock
from ravel.workflow.state_io import atomic_json
from joint_model_fixtures import write_mc,write_legacy
from test_joint_analytic import workspace

pytestmark=pytest.mark.filterwarnings('ignore:jsonschema.RefResolver is deprecated:DeprecationWarning')
BUDGET={'objective_calls':2000,'gradient_calls':2000,'feasibility_lp_calls':8,'stationarity_lp_calls':3,'maxiter':50,'lp_maxiter':1000,'wall_seconds':5.}

def mc_source(tmp_path,*,kappa=20.,signed=False):
    path=write_mc(tmp_path);document=json.loads(path.read_bytes());ledger_path=tmp_path/'mc-ledger.json';ledger=json.loads(ledger_path.read_bytes())
    if signed:
        for row,marks in zip(document['classes'],([1.,1.],[-1.,-1.],[0.,0.])):
            row['contribution']=marks
        for row in ledger['classes']:row['contribution']=next(c['contribution'] for c in document['classes'] if c['id']==row['id'])
        for row in ledger['groups']:row['contribution']=next(c['contribution'] for c in document['classes'] if c['id']==row['class_id'])
    document['mc_design']['kappa']=kappa;ledger['normalization']['kappa']=kappa;raw=compact(ledger);ledger_path.write_bytes(raw);document['sources'][0]['sha256']=hashlib.sha256(raw).hexdigest();path.write_bytes(compact(document));return MCAuxiliaryBlock({'input':str(path)})

def engine(module,tmp_path,*,kappa=20.,signed=False,beta_lower=0.,generic=False):
    mc=mc_source(tmp_path/'MC',kappa=kappa,signed=signed);source=workspace();source['measurements'][0]['config']['parameters'][1]['bounds'][0][0]=beta_lower
    mapping={'SR':['signal'],'CR':['signal']};bg=BackgroundAuxBlock(source,mapping,measurement='M',policy='separable_signal_mc',model_id='synthetic-boundary-source')
    joint=module.AnalyticPublishedJoint(bg,mc,source_workspace=source,signal_samples=mapping,source_bin_map=[{'channel':'CR','bin':0,'mc_bin_id':'CR'},{'channel':'SR','bin':0,'mc_bin_id':'SR'}],model_id='synthetic-boundary-join',response_assumptions=['Explicit synthetic fixed-mark law.','Source and MC auxiliary independent.'])
    semantics={name:{'lower':'physical' if name=='beta' and beta_lower==0 else 'numerical','upper':'numerical'} for name in bg.contract()['active_parameter_names']}
    profiler=module.AnalyticJointProfiler(joint,bg,mc,mu_domain={'initial':1.,'upper':10.},source_bound_semantics=semantics,rate_caps={})
    return joint,bg,mc,profiler,semantics

def returned(x):return SimpleNamespace(x=np.array(x),success=True,message='Synthetic returned endpoint; optimizer deliberately stubbed',nit=1)

def checked(a):
    w=a['stationarity_witness'];json.dumps(w,allow_nan=False)
    assert len(w['coordinates'])==len(w['coordinate_bounds'])==len(w['coordinate_order'])==len(w['raw_coordinate_gradient'])
    assert 'literal_zero_physical_slack' in w['activity_rule']
    for x,b,slack in zip(w['coordinates'],w['coordinate_bounds'],w['coordinate_slacks']):assert slack==[x-b[0],b[1]-x]
    lp=w['lp'];assert lp['objective']==w['raw_coordinate_gradient']
    direction=lp['result']['direction']
    if direction is not None:
        assert float(np.dot(lp['objective'],direction))==pytest.approx(lp['result']['objective'],abs=1e-8)
        assert max(0.,-lp['result']['objective'])==pytest.approx(a['tangent_descent_violation'])
        for d,(lo,hi) in zip(direction,lp['direction_bounds']):assert lo-1e-12<=d<=hi+1e-12
        if lp['A_ub'] is not None:assert np.max(np.asarray(lp['A_ub'])@direction-np.asarray(lp['b_ub']))<=1e-10
        if lp['A_eq'] is not None:assert np.max(np.abs(np.asarray(lp['A_eq'])@direction-np.asarray(lp['b_eq'])))<=1e-10
    return w


@pytest.mark.parametrize('generic',[False,True])
def test_joined_actual_lp_transport_and_late_failure_preserve_raw_score(tmp_path,monkeypatch,generic):
    module=new_profile if generic else new_analytic
    joint,bg,mc,profiler,semantics=engine(new_analytic if generic else module,tmp_path,kappa=1e6)
    if generic:
        class Proxy:
            contract_sha256=joint.contract_sha256
            def contract(self):return joint.contract()
            def evaluate(self,source,latent,**kw):
                row=joint.evaluate_with_gradient(source,latent,**kw)
                return {'finite':row['finite'],'source':row['source'],'joint_logpdf':-row['nll']}
        profiler=module.JointProfiler(Proxy(),bg,mc,mu_domain={'initial':1.,'upper':10.},source_bound_semantics=semantics,rate_caps={})
    monkeypatch.setattr(module,'minimize',lambda *a,**k:returned([5e-8]))
    kwargs={'fixed_source':bg.initial_point(),'fixed_latent':{c['id']:c['initial'] for c in mc.document()['classes']},
            'data':{'main':[0,0],'source_auxiliary':[0.],'MC_auxiliary':[3,3,4]},'budget':BUDGET}
    fit=profiler.fit(**kwargs)
    assert not fit["verified"]
    atomic_json(tmp_path/"joined-attempts.json",fit)
    assert json.loads((tmp_path/"joined-attempts.json").read_text())==fit
    for a in fit['attempts']:
        w=checked(a)
        assert w['coordinates']==[5e-8] and w['coordinate_slacks'][0][0]>0
        assert w['raw_coordinate_gradient']==pytest.approx([600000.],rel=1e-10)
        c=w['linear_constraints'];assert np.asarray(c['matrix'])@np.asarray(w['coordinates'])+np.asarray(c['offset'])==pytest.approx(c['residuals'])
        if not generic:
            assert len(w['nonlinear_constraints']['residuals'])==4
            assert len(w['nonlinear_constraints']['jacobian'])==4
    original=module.linprog
    def fail_after_endpoint(c,*a,**kw):
        if len(c)==1 and abs(c[0])>1e5:raise RuntimeError('late stationarity failure')
        return original(c,*a,**kw)
    monkeypatch.setattr(module,'linprog',fail_after_endpoint)
    failed=profiler.fit(**kwargs)
    assert not failed['verified']
    for a in failed['attempts']:
        assert a['failure_kind']=='numerical_or_verification_exception'
        w=a['stationarity_witness'];assert w['raw_coordinate_gradient']==pytest.approx([600000.],rel=1e-10)
        assert 'lp' in w and 'result' not in w['lp'];json.dumps(w,allow_nan=False)


def test_finite_complete_simplex_lp_and_late_failure_retained(tmp_path,monkeypatch):
    document=json.loads(write_legacy(tmp_path).read_bytes())
    for c,marks in zip(document['classes'],([1.,1.],[-1.,-1.],[0.,0.])):c['contribution']=marks
    x=[.30000005,.3,.39999995]
    monkeypatch.setattr(scipy.optimize,'minimize',lambda *a,**k:returned(x))
    fit=new_finite.fit(document,fixed_mu=1.,data={'main':[0,0],'mc':[3,3,4]},maxiter=30)
    atomic_json(tmp_path/'finite-attempts.json',fit)
    assert json.loads((tmp_path/'finite-attempts.json').read_text())==fit
    for a in fit['attempts']:
        w=checked(a);assert w['coordinates']==x
        assert w['lp']['A_eq']==[[1.,1.,1.]] and w['lp']['b_eq']==[0.]
        assert w['linear_constraints']['simplex_residual']==pytest.approx(0.,abs=1e-15)
        assert all(r>0 for r in w['linear_constraints']['net_residuals'])
    original=scipy.optimize.linprog
    def fail_verification(c,*a,**kw):
        if kw.get('b_eq')==[0.]:raise RuntimeError('late finiteMC stationarity failure')
        return original(c,*a,**kw)
    monkeypatch.setattr(scipy.optimize,'linprog',fail_verification)
    failed=new_finite.fit(document,fixed_mu=1.,data={'main':[0,0],'mc':[3,3,4]},maxiter=30)
    assert not failed['verified']
    for a in failed['attempts']:
        assert a['failure_kind']=='verification_exception'
        w=a['stationarity_witness'];assert w['coordinates']==x and len(w['raw_coordinate_gradient'])==3
        assert w['lp']['A_eq']==[[1.,1.,1.]] and 'result' not in w['lp'];json.dumps(w,allow_nan=False)


@pytest.mark.parametrize('module',[new_profile,new_analytic,new_finite])
def test_nonfinite_diagnostic_values_are_explicit_null_not_json_nan(module):
    assert module._diagnostic_values({'x':np.array([math.nan,math.inf,-math.inf,1.]),'g':np.float64(2.)})=={'x':[None,None,None,1.],'g':2.}
    json.dumps(module._diagnostic_values(np.array([math.nan])),allow_nan=False)


def test_analytic_nonlinear_residual_survives_later_jacobian_failure(tmp_path,monkeypatch):
    joint,bg,mc,profiler,_=engine(new_analytic,tmp_path,kappa=1e6)
    monkeypatch.setattr(new_analytic,'minimize',lambda *a,**k:returned([5e-8]))
    original=joint.physical_constraints_at;calls=[]
    def second_fails(source,latent):
        calls.append(dict(source))
        if len(calls)==2:raise RuntimeError('nonlinear Jacobian interruption')
        return original(source,latent)
    monkeypatch.setattr(joint,'physical_constraints_at',second_fails)
    fit=profiler.fit(fixed_source=bg.initial_point(),fixed_latent={c['id']:c['initial'] for c in mc.document()['classes']},data={'main':[0,0],'source_auxiliary':[0.],'MC_auxiliary':[3,3,4]},budget=BUDGET)
    a=fit['attempts'][0];assert a['failure_kind']=='numerical_or_verification_exception'
    assert len(calls)>=2 and a['error']=='nonlinear Jacobian interruption' and a['exception_type']=='RuntimeError'
    w=a['stationarity_witness'];assert w['raw_coordinate_gradient']==pytest.approx([600000.],rel=1e-10)
    assert len(w['nonlinear_constraints']['residuals'])==4 and 'jacobian' not in w['nonlinear_constraints']


def test_returned_coordinates_survive_postsolver_budget_refusal(tmp_path,monkeypatch):
    joint,bg,mc,profiler,_=engine(new_analytic,tmp_path,kappa=1e6)
    returned_flag=[]
    def optimizer(*a,**k):returned_flag.append(True);return returned([5e-8])
    original=new_analytic.WorkBudget.check
    def after_solver(work):
        if returned_flag:raise new_analytic.BudgetExhausted('post-solver synthetic budget refusal')
        return original(work)
    monkeypatch.setattr(new_analytic,'minimize',optimizer);monkeypatch.setattr(new_analytic.WorkBudget,'check',after_solver)
    fit=profiler.fit(fixed_source=bg.initial_point(),fixed_latent={c['id']:c['initial'] for c in mc.document()['classes']},data={'main':[0,0],'source_auxiliary':[0.],'MC_auxiliary':[3,3,4]},budget=BUDGET)
    a=fit['attempts'][0];assert a['failure_kind']=='budget_exhausted'
    w=a['stationarity_witness'];assert w['coordinates']==[5e-8] and 'raw_coordinate_gradient' not in w


@pytest.mark.parametrize('module',[new_profile,new_analytic,new_finite])
def test_positive_slack_counterexample_is_not_an_exact_boundary(module):
    # Supplied scalar model f(x)=.5e16*x^2, x>=0: a feasible boundary move
    # improves by12.5 despite the previous proximity rule suppressing g.
    x=5e-8;gradient=1e16*x
    old_near_active=x<=1e-7
    assert old_near_active and .5e16*x*x==pytest.approx(12.5)
    assert gradient>0 and not module._tangent_active(x,1e-7,physical=True)
    assert module._tangent_active(0.,1e-7,physical=True)
    assert module._tangent_active(x,1e-7,physical=False)
    with pytest.raises(ValueError):module._tangent_active(-1e-18,1e-7,physical=True)


def test_wrong_length_finite_solver_vector_is_retained_refusal(tmp_path,monkeypatch):
    document=json.loads(write_legacy(tmp_path).read_bytes())
    monkeypatch.setattr(scipy.optimize,'minimize',lambda *a,**k:returned([.4,.6]))
    fit=new_finite.fit(document,fixed_mu=1.,maxiter=30)
    assert not fit['verified'] and len(fit['attempts'])==3
    for a in fit['attempts']:
        assert a['failure_kind']=='verification_exception'
        assert a['stationarity_witness']['coordinates']==[.4,.6]
        assert 'raw_coordinate_gradient' not in a['stationarity_witness']
    atomic_json(tmp_path/'malformed-return.json',fit)
    assert json.loads((tmp_path/'malformed-return.json').read_text())==fit


@pytest.mark.parametrize('generic',[False,True])
def test_wrong_length_joined_solver_vector_preserves_raw_return(tmp_path,monkeypatch,generic):
    module=new_profile if generic else new_analytic
    joint,bg,mc,profiler,semantics=engine(new_analytic,tmp_path,kappa=1e6)
    if generic:
        class Proxy:
            contract_sha256=joint.contract_sha256
            def contract(self):return joint.contract()
            def evaluate(self,source,latent,**kw):
                row=joint.evaluate_with_gradient(source,latent,**kw)
                return {'finite':row['finite'],'source':row['source'],'joint_logpdf':-row['nll']}
        profiler=module.JointProfiler(Proxy(),bg,mc,mu_domain={'initial':1.,'upper':10.},source_bound_semantics=semantics,rate_caps={})
    monkeypatch.setattr(module,'minimize',lambda *a,**k:returned([5e-8,9.]))
    fit=profiler.fit(fixed_source=bg.initial_point(),fixed_latent={c['id']:c['initial'] for c in mc.document()['classes']},data={'main':[0,0],'source_auxiliary':[0.],'MC_auxiliary':[3,3,4]},budget=BUDGET)
    assert not fit['verified'] and len(fit['attempts'])==3
    for a in fit['attempts']:
        assert a['failure_kind']=='numerical_or_verification_exception'
        assert a['stationarity_witness']['coordinates']==[5e-8,9.]
        assert 'raw_coordinate_gradient' not in a['stationarity_witness']
    atomic_json(tmp_path/'joined-malformed-return.json',fit)
    assert json.loads((tmp_path/'joined-malformed-return.json').read_text())==fit


def test_literal_physical_bound_blocks_only_outward_descent(tmp_path,monkeypatch):
    joint,bg,mc,profiler,_=engine(new_analytic,tmp_path,kappa=1e6)
    monkeypatch.setattr(new_analytic,'minimize',lambda *a,**k:returned([0.]))
    fit=profiler.fit(fixed_source=bg.initial_point(),fixed_latent={c['id']:c['initial'] for c in mc.document()['classes']},data={'main':[0,0],'source_auxiliary':[0.],'MC_auxiliary':[3,3,4]},budget=BUDGET)
    assert fit['verified']
    for a in fit['attempts']:
        w=checked(a)
        assert w['coordinates']==[0.] and w['raw_coordinate_gradient']==pytest.approx([600000.])
        assert w['lp']['direction_bounds'][0][0]==0. and a['tangent_descent_violation']==0.


def test_actual_nonlinear_background_positive_slack_and_literal_zero(tmp_path,monkeypatch):
    joint,bg,mc,profiler,_=engine(new_analytic,tmp_path,beta_lower=-1.)
    for x,expected in [(5e-8,False),(0.,True)]:
        monkeypatch.setattr(new_analytic,'minimize',lambda *a,**k:returned([x]))
        fit=profiler.fit(fixed_mu=1.,fixed_source={'alpha':0.},fixed_latent={c['id']:c['initial'] for c in mc.document()['classes']},data={'main':[0,0],'source_auxiliary':[0.],'MC_auxiliary':[3,3,4]},budget=BUDGET)
        assert fit['verified'] is expected
        for a in fit['attempts']:
            w=checked(a);assert w['raw_coordinate_gradient']==pytest.approx([30.])
            assert all(v>0 if x else v==0 for v in w['nonlinear_constraints']['residuals'][:2])
            assert a['tangent_descent_violation']==pytest.approx(0. if expected else 30.)



def test_dual_active_physical_and_numerical_sides_both_retained(tmp_path,monkeypatch):
    document=json.loads(write_legacy(tmp_path).read_bytes())
    document['mu'].update(initial=5e-9,upper=1e-8)
    for point in document['comparison_points']+document['calibration']['truths']:point['mu']=5e-9
    document['profile_points']=[5e-9]
    monkeypatch.setattr(scipy.optimize,'minimize',lambda *a,**k:returned([0.,.3,.3,.4]))
    fit=new_finite.fit(document,data={'main':[0,0],'mc':[3,3,4]},maxiter=30)
    assert not fit['verified'] and len(fit['attempts'])==3
    for a in fit['attempts']:
        assert not a['verified'] and a['success']
        sides=[row for row in a['active_bounds'] if row['coordinate']==0]
        assert sides==[{'coordinate':0,'side':'lower','physical':True},{'coordinate':0,'side':'upper','physical':False}]
        w=checked(a)
        assert w['coordinate_bounds'][0]==[0.,1e-8]
        assert w['coordinate_slacks'][0]==[0.,1e-8]
        assert w['lp']['direction_bounds'][0]==[0.,0.]
    atomic_json(tmp_path/'both-bound-sides.json',fit)
    assert json.loads((tmp_path/'both-bound-sides.json').read_text())==fit
