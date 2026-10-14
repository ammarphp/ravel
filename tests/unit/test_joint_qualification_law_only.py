"""Portable law-only controls; ordinary imports work after source promotion."""
from copy import deepcopy
import json

import numpy as np
import pytest

from ravel.physics import joint_qualification as q
from ravel.physics import joint_analytic, joint_profile, finite_mc_model
from ravel.physics.mc_auxiliary import compact
from test_joint_qualification import input_model

pytestmark=pytest.mark.filterwarnings("ignore:jsonschema.RefResolver is deprecated:DeprecationWarning")


def law_input(tmp_path,monkeypatch):
    task,document,path=input_model(tmp_path)
    document.update(schema_version=2,execution_scope='law_only',qualification_mu_upper=document.pop('fit')['mu_domain']['upper'])
    path.write_bytes(compact(document))
    def forbidden(*args,**kwargs):pytest.fail('law-only invoked fit, profiler, optimizer or LP')
    monkeypatch.setattr(q,'AnalyticJointProfiler',forbidden)
    for module in (joint_analytic,joint_profile,finite_mc_model):
        for name in ('minimize','linprog'):
            if hasattr(module,name):monkeypatch.setattr(module,name,forbidden)
    return task,document,path


def test_two_case_law_retains_all_tangent_checks_and_zero_fit_census(tmp_path,monkeypatch):
    task,document,path=law_input(tmp_path,monkeypatch)
    second=deepcopy(document['cases'][0]);second['id']='second'
    document['cases'].append(second);path.write_bytes(compact(document))
    result=q.run(task,tmp_path,tmp_path/'out')
    assert result['status']=='passed' and result['law_qualification_passed']
    assert result['execution_scope']=='law_only' and not result['profile_qualification_performed']
    assert result['claim_scope']=='Supplied full-law values at the exact initial and interior points, and all declared tangent derivatives at the interior point only; no numerical optimum, profile, calibration or CLs qualification'
    assert result['planned_fit_denominator']==result['completed_fit_records']==0
    assert result['fits']==result['nested_model_checks']==[]
    assert not result['physics_validated'] and not result['global_optimum_certified']
    for record in result['qualification']:
        assert len(record['fixed_vectors'])==2
        assert len(record['gradient_columns'])==document['cases'][0]['expected_free_coordinates']
        assert all(len(c['steps'])==2 and c['passed'] for c in record['gradient_columns'])
    expected=2*(2+4*document['cases'][0]['expected_free_coordinates'])
    assert result['qualification_budget_used']['density_wrapper_calls']==expected
    assert result['qualification_budget_used']['pyhf_main_calls']==3*expected
    bounds=result['resource_bounds']
    for key in ('maximum_fit_calls','maximum_optimizer_attempts','maximum_optimizer_objective_calls','maximum_optimizer_analytic_gradient_calls','maximum_total_seed_LP_calls','maximum_total_stationarity_LP_calls','maximum_total_optimizer_iterations'):
        assert bounds[key]==0
    assert bounds['maximum_analytic_qualification_evaluations']==bounds['maximum_total_analytic_gradient_calls']==4
    assert all(v==0 for v in result['endpoint_verification_budget_used'].values())
    saved=json.loads((tmp_path/'out/joint_qualification_result.json').read_bytes())
    assert saved==result
    journal=[json.loads(line) for line in (tmp_path/'out/qualification-progress.jsonl').read_bytes().splitlines()]
    assert not any(row['kind']=='fit' for row in journal)
    assert sum(row['kind']=='independent_density' and row['state']=='completed' for row in journal)==expected


@pytest.mark.parametrize('mutation',['missing_scope','wrong_scope','schema1_with_scope','schema2_with_fit','missing_mu_upper','bool_version'])
def test_explicit_scope_and_disjoint_schema_keys_are_required(tmp_path,monkeypatch,mutation):
    task,document,path=law_input(tmp_path,monkeypatch)
    if mutation=='missing_scope':document.pop('execution_scope')
    elif mutation=='wrong_scope':document['execution_scope']='automatic'
    elif mutation=='schema1_with_scope':document['schema_version']=1
    elif mutation=='schema2_with_fit':document['fit']={}
    elif mutation=='missing_mu_upper':document.pop('qualification_mu_upper')
    else:document['schema_version']=True
    path.write_bytes(compact(document))
    monkeypatch.setattr(q,'_compile',lambda *a,**k:pytest.fail('compile before schema refusal'))
    with pytest.raises(ValueError):q.resource_bounds(task,tmp_path)


def test_law_metadata_admission_never_compiles_or_evaluates(tmp_path,monkeypatch):
    task,_,_=law_input(tmp_path,monkeypatch)
    monkeypatch.setattr(q,'_compile',lambda *a,**k:pytest.fail('metadata compiled scientific source'))
    monkeypatch.setattr(q.IndependentSourceOracle,'evaluate',lambda *a,**k:pytest.fail('metadata evaluated source'))
    bounds=q.resource_bounds(task,tmp_path)
    assert bounds['maximum_fit_calls']==0 and len(q.inputs(task,tmp_path))>=4


def test_law_call_exhaustion_retains_failed_oracle_without_fit_fallback(tmp_path,monkeypatch):
    task,document,path=law_input(tmp_path,monkeypatch)
    document['qualification']['pyhf_main_calls']=1;path.write_bytes(compact(document))
    result=q.run(task,tmp_path,tmp_path/'out')
    assert result['status']=='failed' and not result['law_qualification_passed']
    assert result['fits']==[] and result['planned_fit_denominator']==0
    rows=[json.loads(s) for s in (tmp_path/'out/qualification-progress.jsonl').read_bytes().splitlines()]
    assert any(r['kind']=='independent_density' and r['state']=='failed' for r in rows)


def test_wrong_mean_derivative_fails_law_even_when_score_unchanged(tmp_path,monkeypatch):
    task,_,_=law_input(tmp_path,monkeypatch)
    original=q.AnalyticPublishedJoint.evaluate_with_gradient
    def corrupt(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        result['distribution_mean_jacobian'][0][0]+=1.
        return result
    monkeypatch.setattr(q.AnalyticPublishedJoint,'evaluate_with_gradient',corrupt)
    result=q.run(task,tmp_path,tmp_path/'out')
    assert result['status']=='failed' and not result['law_qualification_passed']
    assert result['qualification'][0]['gradient_columns'][0]['passed'] is False
    assert result['fits']==[]


def test_schema1_combined_failure_never_becomes_law_only_success(tmp_path,monkeypatch):
    task,document,path=input_model(tmp_path)
    calls=[]
    class FailedProfiler:
        def __init__(self,*args,**kwargs):pass
        def fit(self,**kwargs):
            calls.append(kwargs)
            return {'verified':False,'status':'explicit_mock_failure','attempts':[]}
    monkeypatch.setattr(q,'AnalyticJointProfiler',FailedProfiler)
    result=q.run(task,tmp_path,tmp_path/'out')
    assert all(row['passed'] for row in result['qualification'])
    assert len(calls)==4 and result['planned_fit_denominator']==4
    assert result['status']=='failed' and 'law_qualification_passed' not in result
    assert 'execution_scope' not in result and result['schema_version']==1


def test_nonempty_output_refuses_before_law_capture(tmp_path,monkeypatch):
    task,_,_=law_input(tmp_path,monkeypatch)
    out=tmp_path/'out';out.mkdir();(out/'preserve').write_text('evidence')
    monkeypatch.setattr(q,'_capture',lambda *a,**k:pytest.fail('capture before fresh-dir refusal'))
    with pytest.raises(FileExistsError):q.run(task,tmp_path,out)
    assert (out/'preserve').read_text()=='evidence'


@pytest.mark.parametrize('when',['before','after'])
def test_analytic_wall_hook_refuses_and_retains_completed_analytic(tmp_path,monkeypatch,when):
    task,_,_=law_input(tmp_path,monkeypatch)
    calls=[]
    original=q.AnalyticPublishedJoint.evaluate_with_gradient
    def evaluate(self,*args,**kwargs):
        calls.append('analytic')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(q.AnalyticPublishedJoint,'evaluate_with_gradient',evaluate)
    def wall(self):
        if when=='before' or calls:raise TimeoutError('synthetic qualification wall exhausted')
    monkeypatch.setattr(q.QualificationBudget,'check',wall)
    monkeypatch.setattr(q.IndependentSourceOracle,'evaluate',lambda *a,**k:pytest.fail('oracle started after analytic wall refusal'))
    result=q.run(task,tmp_path,tmp_path/'out')
    assert result['status']=='failed' and result['fits']==[]
    fixed=result['qualification'][0]['fixed_vectors']
    assert len(fixed)==1 and not fixed[0]['passed']
    journal=[json.loads(line) for line in (tmp_path/'out/qualification-progress.jsonl').read_bytes().splitlines()]
    returned=[r for r in journal if r['kind']=='qualification_analytic' and r['state']=='returned']
    if when=='before':
        assert calls==[] and returned==[] and 'analytic' not in fixed[0]
    else:
        assert calls==['analytic'] and len(returned)==1
        assert returned[0]['snapshot']==fixed[0]['analytic']
        assert fixed[0]['independent'] is None
