"""Tiny arithmetic, provenance and complete 42-call flow controls."""
from copy import deepcopy
from decimal import Decimal, localcontext
import json
import math
from pathlib import Path

import pytest

from ravel.validation import likelihood_candidate_check as candidate
from ravel.validation import likelihood_step_refinement as refine
from test_likelihood_candidate_check import portfolio
from diagnostic_plan_fixture import CANDIDATE_PLAN, REFINE_PLAN, CRITERIA, REFINE_LIMITS, metadata


def retained():
    children,probe,_ = portfolio()
    expected = candidate.select_candidates(children,probe,{'model_compact_sha256':'model','data_compact_sha256':'data'},CANDIDATE_PLAN)
    probe['data'] = [2.]*2
    compiled = {k:k for k in candidate.IDENTITY_KEYS}
    rows = []
    for index,original in enumerate(expected):
        fd = [{'index':i,'rule':'fixed' if i in (1,2) else 'central','h':1e-4,
               'h_gradient':1e-6-2e-5,'half_gradient':1e-6-5e-6} for i in range(6)]
        comparisons = [{'index':i,'masked':i in (1,2),'absolute_residual':4e-6,'tolerance':1e-5,
                        'passed':not(index and i in (3,4))} for i in range(6)]
        rows.append({**deepcopy(original),'finite_difference':fd,'analytic_gradient':[1e-6]*6,
                     'gradient_parity':{'coordinates':comparisons},'stationary':False})
    report = {'status':'passed','diagnostic_delivery_complete':True,'runtime_before_passed':True,
              'runtime_after_passed':True,'arithmetic_parity_passed':False,'all_candidate_checks_passed':False,
              'original_comparison_passed':False,'paired_profile_completed':False,'budget':{'calls':98},
              'candidates':rows,'compiled_identity':compiled,'data':probe['data'],'bounds':probe['bounds'],
              'fixed_coordinates':probe['fixed_coordinates'],
              'reference':{'parameters':deepcopy(expected[0]['parameters']),'passed':True}}
    return report,expected,report['reference']['parameters'],compiled,probe


def test_exact_eight_previous_convergence_failures_only():
    args=retained()
    pairs=refine.select_failed(*args,REFINE_PLAN)
    assert [(r['candidate_index'],r['coordinate']) for r in pairs] == [(i,j) for i in [1,2,3,4] for j in [3,4]]
    assert len(args[0]['candidates'])==5 and not args[0]['candidates'][0]['stationary']


@pytest.mark.parametrize('field',['value','vector','identity','data','mask','extra_failure','missing_failure','derivative_failure','reference','original_verdict'])
def test_origin_drift_refused(field):
    report,expected,reference,compiled,probe=deepcopy(retained())
    if field=='value':report['candidates'][1]['recorded_twice_nll']+=1
    elif field=='vector':report['candidates'][2]['parameters'][3]+=.01
    elif field=='identity':report['compiled_identity']={**compiled,'npars':'changed'}
    elif field=='data':report['data']=[9.]*2
    elif field=='mask':report['fixed_coordinates']=[]
    elif field=='extra_failure':report['candidates'][2]['gradient_parity']['coordinates'][5]['passed']=False
    elif field=='missing_failure':report['candidates'][2]['gradient_parity']['coordinates'][3]['passed']=True
    elif field=='derivative_failure':report['candidates'][2]['gradient_parity']['coordinates'][3]['absolute_residual']=1.
    elif field=='reference':report['reference']['passed']=False
    else:report['arithmetic_parity_passed']=True
    with pytest.raises(ValueError):
        refine.select_failed(report,expected,reference,compiled,probe,REFINE_PLAN)


def test_poisson_log_ratio_against_high_precision_near_cancellation():
    n=1e7;plus=n+1.00001;minus=n+.99999
    with localcontext() as ctx:
        ctx.prec=80
        p,m,count=map(Decimal.from_float,(plus,minus,n))
        expected=float(2*((p-m)-count*(p/m).ln()))
    assert refine.poisson_difference(n,plus,minus)==pytest.approx(expected,abs=2e-20)
    assert refine.poisson_difference(0.,plus,minus)==2*(plus-minus)
    with pytest.raises(ValueError):
        refine.poisson_difference(1.,0.,1.)


def test_stable_complete_main_normal_poisson_terms():
    data=[2.]*2+[.9,3.]
    layout=[{'pdf':'normal','sigma':.1},{'pdf':'poisson','sigma':None}]
    plus={'main_means':[2.01]*2,'density':{'auxiliary_expected':[1.02,3.1]}}
    minus={'main_means':[1.99]*2,'density':{'auxiliary_expected':[.98,2.9]}}
    result=refine.stable_difference(plus,minus,data,layout)
    with localcontext() as ctx:
        ctx.prec=80
        def p(n,m):
            m=Decimal.from_float(m)
            return 2*(m-Decimal.from_float(n)*m.ln())
        expected=2*(p(2.,2.01)-p(2.,1.99))+p(3.,3.1)-p(3.,2.9)
        n=Decimal.from_float(.9);s=Decimal.from_float(.1)
        expected+=((n-Decimal.from_float(1.02))**2-(n-Decimal.from_float(.98))**2)/s**2
    assert len(result['term_differences'])==4
    assert result['difference']==pytest.approx(float(expected),abs=1e-13)


def quadratic_bias_pair():
    g=1e-6;c=-2e-5
    return {'original_h_gradient':g+c,'original_half_gradient':g+c/4,
            'retained_jax_gradient':g,'refined_steps':[
                {'whole_objective_gradient':g+c/16,'stable_term_gradient':g+c/16},
                {'whole_objective_gradient':g+c/64,'stable_term_gradient':g+c/64}]}


def test_predeclared_quadratic_convergence_and_cancellation_checks():
    pair=quadratic_bias_pair()
    refine.classify(pair,CRITERIA)
    assert pair['refined_coordinate_checks_passed']
    assert pair['coarse_to_quarter_drift_ratio']==pytest.approx(.25)
    pair=quadratic_bias_pair()
    pair['refined_steps'][1]['whole_objective_gradient']+=.01
    refine.classify(pair,CRITERIA)
    assert not pair['cancellation_passed'] and not pair['refined_coordinate_checks_passed']


def test_small_analytic_residual_cannot_override_failed_scaling():
    pair=quadratic_bias_pair()
    for row in pair['refined_steps']:
        row.update(whole_objective_gradient=pair['original_half_gradient'],stable_term_gradient=pair['original_half_gradient'])
    refine.classify(pair,CRITERIA)
    assert pair['retained_jax_agreement_passed'] and pair['convergence_passed']
    assert not pair['quadratic_scaling_consistent'] and not pair['refined_coordinate_checks_passed']


@pytest.mark.parametrize('interrupt',[None,1,7,14])
def test_actual_adapter_flow_is_bounded_and_retains_partial_work(tmp_path,monkeypatch,interrupt):
    import numpy as np
    import pyhf
    from ravel.physics import published_model
    report,expected,reference,compiled,probe=retained()
    pairs=refine.select_failed(report,expected,reference,compiled,probe,REFINE_PLAN)
    report['constraint_layout']=[]
    calls=[]
    def density(point):
        mean=3+point[3]+point[4]
        return 2*2*(mean-2*math.log(mean)+math.lgamma(3))
    for row in [*report['candidates'],report['reference']]:
        row.update(numpy_twice_nll=density(row['parameters']),independent_twice_nll=density(row['parameters']),
                   fd_projected_gradient=1.,analytic_projected_gradient=1.,reference_quality_passed=False,
                   candidate_checks_passed=False)
    class Model:
        def expected_actualdata(self,point):
            calls.append(list(point))
            active=json.loads((tmp_path/'out/likelihood_step_refinement.json').read_text())['evaluation_journal'][-1]
            assert active['status']=='running' and active['invocation_started']
            assert active['parameters']==list(point)
            if interrupt and len(calls)==interrupt:
                raise RuntimeError('synthetic interrupted density')
            return np.array([3+point[3]+point[4]]*2)
    inp=tmp_path/'input.json'
    bound={k:('literal',{}) for k in ('candidate_input','origin_execution','origin_result','origin_source')}
    d={**{k:{'path':'literal','sha256':'literal'} for k in bound},'limits':REFINE_LIMITS,'criteria':CRITERIA,'plan':{**metadata(file='likelihood_step_refinement.json'),**REFINE_PLAN}}
    monkeypatch.setattr(refine,'document',lambda *a:(inp,d,bound,inp,{'runtime_inventory':'runtime','published_input':'published'},compiled,probe,report,pairs))
    monkeypatch.setattr(refine.parity,'_pin',lambda *a:(inp,{}))
    monkeypatch.setattr(refine.parity,'runtime_files',lambda *a:[])
    monkeypatch.setattr(refine.parity,'compiled_json_identity',lambda x:x)
    monkeypatch.setattr(refine.parity,'constraint_layout',lambda model:[])
    monkeypatch.setattr(published_model,'load_published_model',lambda *a:{})
    monkeypatch.setattr(published_model,'compile_published_model',lambda *a:(Model(),None,compiled))
    monkeypatch.setattr(pyhf.infer.mle,'twice_nll',lambda point,*a:np.array([density(point)]))
    result=refine.run({'input':str(inp)},tmp_path,tmp_path/'out')
    assert result['optimizer_calls']==0 and result['paired_profile_completed'] is False
    assert result['original_arithmetic_parity_passed'] is False and result['original_jax_best_checks_passed'] is False
    if interrupt:
        assert result['status']=='failed' and result['error']['message']=='synthetic interrupted density'
        assert result['budget']['calls']<42 and not result['refinement_checks_passed']
        journal=result['evaluation_journal']
        completed=[r for r in journal if r['category']=='independent_scalar_density' and r['status']=='completed']
        assert [r['parameters'] for r in completed]==calls[:-1]
        assert all('main_means' in r['result'] and 'density' in r['result'] for r in completed)
        assert journal[-1]['status']=='failed' and journal[-1]['parameters']==calls[-1]
        assert journal[-1]['error']['message']=='synthetic interrupted density'
        assert json.loads((tmp_path/'out/likelihood_step_refinement.json').read_text())['evaluation_journal']==journal
        if interrupt==1:
            assert journal[0]['category']=='numpy_baseline_objective' and journal[0]['status']=='completed'
            assert result['baseline_checks'][0]['numpy_twice_nll']==journal[0]['result']
        elif interrupt==7:
            step=result['pairs'][0]['refined_steps'][0]
            assert step['status']=='running' and 'minus' in step and 'plus' not in step
            assert journal[-1]['context']=={'phase':'perturbation','candidate_index':1,'coordinate':3,'divisor':4,'h':2.5e-5,'direction':'plus'}
    else:
        assert result['status']=='passed' and result['diagnostic_delivery_complete']
        assert result['budget']['calls']==42
        assert result['budget']['categories']=={'numpy_baseline_objective':5,'independent_scalar_density':37}
        assert len(calls)==37 and len(result['pairs'])==8
        assert all(len(row['refined_steps'])==2 for row in result['pairs'])
        assert len(result['evaluation_journal'])==42
        assert all(r['status']=='completed' for r in result['evaluation_journal'])


def test_origin_evaluator_census_is_derived_from_supplied_candidates():
    report,expected,reference,compiled,probe=retained()
    report['budget']['calls']-=1
    with pytest.raises(ValueError,match='census'):
        refine.select_failed(report,expected,reference,compiled,probe,REFINE_PLAN)
