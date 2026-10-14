"""Authored elementary-law and ordinary-path controls; root executes separately."""

from method_decision_fixture import admit_method
from copy import deepcopy
import hashlib
import inspect
import json
import math
from pathlib import Path
import pytest
from ravel.workflow import quantitative_predictive_checks as q


def pin(path,value):
    raw=(json.dumps(value,allow_nan=False,sort_keys=True)+'\n').encode();path.write_bytes(raw)
    return {'path':str(path.absolute()),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def runtime_sources():
    import numpy as np
    from numpy.linalg import _umath_linalg
    from numpy.core import _multiarray_umath,overrides
    from numpy.linalg import linalg as linalg_implementation
    from scipy import stats,special
    rows=[]
    for module in (np,np.linalg,linalg_implementation,_umath_linalg,_multiarray_umath,overrides,stats,stats.poisson.__class__,stats.chi2.__class__,stats.rv_continuous,special._ufuncs):
        path=Path(inspect.getfile(module)).absolute();raw=path.read_bytes()
        rows.append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)})
    return rows


def fixture(tmp_path,*,means=((1.,2.),(2.,1.)),observed=(1,2),gaussian=None,calculation='fixed_poisson_deviance',representation='observed_realization',utility=None):
    n=len(observed);pop=[{'id':'q'+str(i),'cell_id':'cell'+str(i),'quantity':'yield' if gaussian is None else 'mass',
        'unit':'events' if gaussian is None else 'GeV','dimension':{} if gaussian is None else {'energy':[1,1]},
        'representation':'raw_count' if gaussian is None else 'continuous_value',
        'support':{'bin':[i,i+1]},'normalization':{'kind':'absolute'}} for i in range(n)]
    def records(values):
        return [{k:deepcopy(row[k]) for k in ('id','unit','quantity','dimension','support','normalization')}|{'value':v,'quality':True} for row,v in zip(pop,values)]
    data=pin(tmp_path/'prediction.json',{'null':records(means[0]),'alt':records(means[1])})
    law=pin(tmp_path/'law.json',{'description':'synthetic fixed law for elementary tests only'})
    obs=pin(tmp_path/'observed.json',{'records':records(observed)})
    sources=runtime_sources() if gaussian is not None or calculation in {'fixed_poisson_upper_tail','fixed_poisson_threshold_power'} else []
    resources=q.default_resources(wall_seconds=30,max_rss_mib=512)
    allocation=pin(tmp_path/'resources.json',resources)
    c={'schema_version':1,'kind':'prospective_quantitative_predictive_check','check_id':'check','experiment_id':'candidate',
        'goal_binding':None,'premise_bindings':{},'population':pop,'observed':{'result_path':'outputs/attempt-1/result.json','records_pointer':'/records','representation':representation},
        'conditions':{'kind':'synthetic fixed fixture'},'hypotheses':[{'hypothesis_id':h,'prediction':{'source':data,'pointer':'/'+h},
            'parameters':{'fixed':[]},'applicability':{'domain':'synthetic fixture only'},'qualification':'supplied_unqualified',
            'numerical_error':{'status':'unknown'}} for h in ('null','alt')],
        'comparison':{'null_id':'null','alternative_ids':['alt'],'calculation':calculation,'direction':'diagnostic_only'},
        'noise':{'kind':'independent_fixed_poisson' if gaussian is None else 'known_fixed_joint_gaussian_residual',
            'source':law,'independence':'complete supplied law only','conditioning':'fixed_supplied_truth','qualification':'supplied_unqualified','unknown_reasons':[]},
        'nuisances':{'treatment':'fixed_supplied','state':[],'constraints':{'kind':'none'},'fit_evidence':None,'fit_data_exposure':[],'generative_scope':{'kind':'fixed synthetic'}},
        'exposure':{'kind':'withheld_confirmation','record_ids':['measurement'],'fit_record_ids':[],'confirmation_record_ids':['measurement'],
            'replicate_cluster_ids':['physical-measurement'],'source':law},
        'numerics':{'method':'fixed_binary64_scipy_1.14.1_numpy_1.26.4','runtime_requirements':{'versions':{'numpy':'1.26.4','scipy':'1.14.1'},'files':sources},
            'absolute_tolerance':1e-12,'relative_tolerance':1e-10,'bounds':{'max_exact_count':2**53,'equilibrated_condition_max':1e10,
                'symmetry_absolute_tolerance':0.,'symmetry_relative_tolerance':0.},'method_source':law,'uncertainty_status':'unknown'},
        'decision_family':{'family_id':'family','planned_tests':['check'],'selection':'predeclared','stopping':'fixed','multiplicity':'none','inferential_scope':'one conditional fixed test'},
        'selection_inputs':{'candidate_id':'candidate','obligation_ids':['original-obligation'],'utility_declaration':utility,
            'cost':{'status':'estimated','vector':{'calls':0,'output_tokens':0,'wall_seconds':60,'native_attempts':1},'source':law},
            'feasibility':{'status':'feasible','source':law},'coverage':{'held_out':['synthetic'],'invariants':[],'limits':[],'convergence':[]}},
        'source_provenance':[data,law], 'requested_limits':deepcopy(q.DEFAULT_LIMITS)}
    if calculation=='fixed_poisson_threshold_power':c['comparison'].update(threshold=1,alpha=.8)
    if gaussian is not None:
        cov={'kind':'residual','coordinate_ids':[r['id'] for r in pop],
            'product_units':[[[a['unit'],b['unit']] for b in pop] for a in pop], 'known_fixed':True,'covariance':gaussian}
        c['noise']['covariance']={'source':pin(tmp_path/'cov.json',cov),'pointer':''}
    return {'contract':pin(tmp_path/'contract.json',c),'resources':allocation},obs,c,resources


def change(tmp_path,binding,c):
    binding=deepcopy(binding);binding['contract']=pin(tmp_path/'contract.json',c);return binding


def run(binding,obs,tmp_path):return q.evaluate(binding,obs,base_dir=tmp_path)


@pytest.mark.parametrize('x,mu,expected',[(0,0,0),(0,2,2),(2,2,0),(0,3,3)])
def test_zero_and_equal_core(x,mu,expected):
    assert q.poisson_core(x,mu)['value']==expected


def test_structural_support_and_no_infinity_json():
    value=q.poisson_core(1,0);assert value['status']=='structural_zero_support'
    assert value['mathematical_value']=='positive_infinity';json.dumps(value,allow_nan=False)


def test_near_equal_large_count():
    value=2*q.poisson_core(10**12+1,10**12)['value']
    assert value>0;assert math.isclose(value,1e-12-1/(3e24),rel_tol=2e-15)


def test_scalar_zero_count_probability_and_deviance(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((2.,),(3.,)),observed=(0,),calculation='fixed_poisson_upper_tail')
    p=run(b,o,tmp_path)['comparisons'][0]
    assert p['deviance']['null']['value']==4 and p['tail']['value']==1
    assert math.isclose(p['point_probability']['value'],math.exp(-2),rel_tol=1e-14)
    from scipy import stats
    assert q.poisson_mass(0,0,stats)['log_value']==0
    assert q.poisson_mass(0,1,stats)['status']=='structural_zero_support'


def test_full_poisson_vector_kl(tmp_path):
    binding,obs,c,r=fixture(tmp_path);result=run(binding,obs,tmp_path)
    assert math.isclose(result['comparisons'][0]['directed_kl']['value'],math.log(2),rel_tol=1e-14)
    assert len(result['coordinates'])==2 and result['scientific_acceptance'] is False


@pytest.mark.parametrize('bad',[True,1.5,-1,2**53+1])
def test_raw_counts_refuse_without_rounding(tmp_path,bad):
    b,o,c,r=fixture(tmp_path,observed=(bad,2));v=run(b,o,tmp_path)
    assert v['delivery_status']!='complete';assert len(v['coordinates'])==2


def test_asimov_is_expected_and_not_reference_test(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((1.,2.),(2.5,1.5)),observed=(2.5,1.5),representation='expected_asimov')
    v=run(b,o,tmp_path);p=v['comparisons'][0]
    assert math.isclose(p['deviance']['null']['value'],2*p['directed_kl']['value'],rel_tol=1e-14)
    assert v['test_validity']['status']=='unknown'


def test_zero_threshold_and_size(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((1.,),(2.,)),observed=(1,),calculation='fixed_poisson_threshold_power')
    c['comparison'].update(threshold=0,alpha=.05);v=run(change(tmp_path,b,c),o,tmp_path);p=v['comparisons'][0]
    assert p['size']['value']==1 and p['power']['value']==1 and p['size_attained'] is False


def test_threshold_power_exact_elementary_law(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((1.,),(2.,)),observed=(0,),calculation='fixed_poisson_threshold_power')
    v=run(b,o,tmp_path);p=v['comparisons'][0]
    assert math.isclose(p['size']['value'],-math.expm1(-1),rel_tol=1e-14)
    assert math.isclose(p['power']['value'],-math.expm1(-2),rel_tol=1e-14)


def test_infinite_kl_not_large_power_or_default_utility(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((0.,),(1e-9,)),observed=(0,),calculation='fixed_poisson_threshold_power')
    v=run(b,o,tmp_path);p=v['comparisons'][0]
    assert p['directed_kl']['status']=='structural_zero_support';assert p['power']['value']<2e-9
    assert v['selection_evidence']['utility']['value'] is None


def test_tail_underflow_not_structural_zero():
    from scipy import stats
    v=q.poisson_tail(1.,10000,stats);assert v['value']==0
    assert v['status']=='numerical_underflow';assert v['log_value'] is None
    assert q.poisson_tail(0.,0,stats)['value']==1


@pytest.mark.parametrize('cov,expected',[([[1.,0.],[0.,4.]],2.),([[1.,.5],[.5,1.]],4/3)])
def test_full_gaussian_analytic_anchors(tmp_path,cov,expected):
    observed=(1.,2.) if expected==2 else (1.,1.)
    b,o,c,r=fixture(tmp_path,means=((0.,0.),(1.,1.)),observed=observed,gaussian=cov,calculation='known_gaussian_mahalanobis')
    v=run(b,o,tmp_path);assert math.isclose(v['comparisons'][0]['mahalanobis']['null']['value'],expected,rel_tol=1e-13)


def test_single_coordinate_unit_equilibration(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((0.,0.),(0.,0.)),observed=(1000.,1.),gaussian=[[1e6,0.],[0.,1.]],calculation='known_gaussian_mahalanobis')
    # Complete physical conversion appears in both records and product units.
    c['population'][0]['unit']='MeV'
    for path in ('prediction.json','observed.json'):
        data=json.loads((tmp_path/path).read_text())
        for rows in data.values():rows[0]['unit']='MeV'
        updated=pin(tmp_path/path,data)
        if path=='prediction.json':
            for h in c['hypotheses']:h['prediction']['source']=updated
            c['source_provenance'][0]=updated
        else:o=updated
    data=json.loads((tmp_path/'cov.json').read_text());data['product_units']=[[['MeV','MeV'],['MeV','GeV']],[['GeV','MeV'],['GeV','GeV']]]
    c['noise']['covariance']['source']=pin(tmp_path/'cov.json',data)
    v=run(change(tmp_path,b,c),o,tmp_path);d=v['comparisons'][0]['mahalanobis']['null']
    assert math.isclose(d['value'],2,rel_tol=1e-14) and d['diagnostics']['equilibrated_condition']==1


@pytest.mark.parametrize('cov',[[[1.,.5],[.4,1.]],[[1.,0.],[0.,-1.]]])
def test_bad_covariance_refuses_not_repairs(tmp_path,cov):
    b,o,c,r=fixture(tmp_path,gaussian=cov,calculation='known_gaussian_mahalanobis')
    with pytest.raises(ValueError):run(b,o,tmp_path)


def test_singular_covariance_retains_degeneracy(tmp_path):
    b,o,c,r=fixture(tmp_path,gaussian=[[1.,1.],[1.,1.]],calculation='known_gaussian_mahalanobis')
    v=run(b,o,tmp_path);assert v['calculation_status']=='degenerate'
    assert v['comparisons'][0]['mahalanobis']['null']['value'] is None


def test_shared_prediction_cross_covariance(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((0.,),(1.,)),observed=(1.,),gaussian=[[1.]],calculation='known_gaussian_mahalanobis')
    doc={'kind':'components','coordinate_ids':['q0'],'product_units':[[['GeV','GeV']]],'known_fixed':True,
        'observed_covariance':[[1.]],'prediction_covariance':[[1.]],'data_prediction_covariance':[[.5]]}
    c['noise']['covariance']['source']=pin(tmp_path/'cov.json',doc)
    v=run(change(tmp_path,b,c),o,tmp_path);assert v['comparisons'][0]['mahalanobis']['null']['value']==1
    doc['data_prediction_covariance']=[[1.]];c['noise']['covariance']['source']=pin(tmp_path/'cov.json',doc)
    with pytest.raises(ValueError):run(change(tmp_path,b,c),o,tmp_path)


@pytest.mark.parametrize('unqualified',['fitted','estimated'])
def test_fitted_and_estimated_do_not_gain_pvalues(tmp_path,unqualified):
    b,o,c,r=fixture(tmp_path,means=((1.,2.),(1.,2.)),observed=(1.,2.),gaussian=[[1.,0.],[0.,1.]],calculation='known_gaussian_mahalanobis')
    if unqualified=='fitted':c['nuisances']['treatment']='fitted_to_same_data'
    else:
        doc=json.loads((tmp_path/'cov.json').read_text());doc['known_fixed']=False
        c['noise']['covariance']['source']=pin(tmp_path/'cov.json',doc)
    v=run(change(tmp_path,b,c),o,tmp_path);assert v['comparisons'][0]['mahalanobis']['null']['value']==0
    assert v['test_validity']['status']=='unknown' and 'conditional_chi_square_tails' not in v['comparisons'][0]


def test_unknown_noise_raw_only(tmp_path):
    b,o,c,r=fixture(tmp_path,calculation='raw_residual');c['noise']['kind']='unknown';c['noise']['unknown_reasons']=['unknown measurement law']
    v=run(change(tmp_path,b,c),o,tmp_path);assert v['comparisons'][0]['mean_difference']==[1.,-1.]
    assert v['test_validity']['status']=='unknown'


def test_nuisance_overlap_and_equal_means_not_identifiability(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((1.,2.),(1.,2.)));c['nuisances']['treatment']='finite_supplied_states'
    v=run(change(tmp_path,b,c),o,tmp_path);assert v['comparisons'][0]['directed_kl']['value']==0
    assert v['selection_evidence']['global_identifiability_qualified'] is False


@pytest.mark.parametrize('field,bad',[('support',{'bin':[0,2]}),('unit','fb'),('quantity','different yield'),('normalization',{'kind':'normalized'}),('quality',False)])
def test_support_unit_and_quality_complete_refusal(tmp_path,field,bad):
    b,o,c,r=fixture(tmp_path);data=json.loads((tmp_path/'observed.json').read_text());data['records'][0][field]=bad
    o=pin(tmp_path/'observed.json',data);v=run(b,o,tmp_path);assert v['delivery_status']!='complete' and len(v['coordinates'])==2


def test_heldout_fit_overlap_refuses(tmp_path):
    b,o,c,r=fixture(tmp_path);c['exposure']['fit_record_ids']=['measurement']
    with pytest.raises(ValueError):run(change(tmp_path,b,c),o,tmp_path)


def test_adaptive_family_and_shared_measurement_not_votes(tmp_path):
    b,o,c,r=fixture(tmp_path);c['exposure']['kind']='adaptive_full';c['decision_family']['planned_tests']=['check','unissued']
    v=run(change(tmp_path,b,c),o,tmp_path);assert v['test_validity']['status']=='unknown'
    assert v['complete_planned_population']['planned_tests']==['check','unissued']


def test_actual_producer_failure_retained_full_roster(tmp_path):
    b,o,c,r=fixture(tmp_path);v=q.evaluate(b,o,base_dir=tmp_path,producer_success=False)
    assert v['delivery_status']=='failed' and v['calculation_status']=='not_issued'
    assert len(v['coordinates'])==2 and len(v['comparisons'])==1


def test_changed_prediction_invalidates_historical_evidence(tmp_path):
    b,o,c,r=fixture(tmp_path);v=run(b,o,tmp_path);(tmp_path/'prediction.json').write_text('{}')
    with pytest.raises(ValueError):q.verify_value(b,v,base_dir=tmp_path,observation_pin=o)


def test_duplicate_records_and_boolean_rebinding_refuse(tmp_path):
    b,o,c,r=fixture(tmp_path);data=json.loads((tmp_path/'observed.json').read_text());data['records'][1]['id']='q0'
    o=pin(tmp_path/'observed.json',data);assert run(b,o,tmp_path)['delivery_status']!='complete'


def test_original_intended_output_survives_writer_callback(tmp_path,monkeypatch):
    from ravel.workflow import state_io
    b,o,c,r=fixture(tmp_path);d=q.Delivery(b,tmp_path,Path(o['path']),True)
    original=state_io.atomic_json
    def writer(path,value):
        value['coordinates'][0]['observed']=True
        original(path,value)
    monkeypatch.setattr(state_io,'atomic_json',writer)
    with pytest.raises(ValueError):d.write(tmp_path/'check.json')


def test_resource_65_full_population_and_admitted_128(tmp_path):
    n=65;b,o,c,r=fixture(tmp_path,means=(tuple([1.]*n),tuple([2.]*n)),observed=tuple([1]*n))
    v=run(b,o,tmp_path);assert v['resource_requirements']['status']=='pending_resources' and len(v['coordinates'])==65
    r['limits']['coordinates']=128;c['requested_limits']['coordinates']=128
    b['resources']=pin(tmp_path/'resources.json',r);v=run(change(tmp_path,b,c),o,tmp_path)
    assert v['delivery_status']=='complete' and len(v['coordinates'])==65


def test_contract_cannot_raise_effective_bound(tmp_path):
    n=65;b,o,c,r=fixture(tmp_path,means=(tuple([1.]*n),tuple([2.]*n)),observed=tuple([1]*n))
    c['requested_limits']['coordinates']=128;v=run(change(tmp_path,b,c),o,tmp_path)
    assert v['resource_requirements']['status']=='pending_resources'


def test_gaussian_d2_is_twice_kl_not_power(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((0.,0.),(1.,1.)),gaussian=[[1.,0.],[0.,1.]],calculation='known_gaussian_mean_separation')
    v=run(b,o,tmp_path);p=v['comparisons'][0]
    assert p['d2']['value']==2 and p['kl_common_covariance']['value']==1
    assert p['kl_common_covariance']['not_power'] is True


def test_no_automatic_utility_or_zero_cost_ratio(tmp_path):
    b,o,c,r=fixture(tmp_path);v=q.separation(b,base_dir=tmp_path)
    assert v['selection_evidence']['utility']['value'] is None
    assert 'utility_per_cost' not in v['selection_evidence']


def test_explicit_objective_complete_rivals_and_comparability(tmp_path):
    b,o,c,r=fixture(tmp_path);u={'objective_id':'objective','source':c['noise']['source'],'metric':'directed_poisson_kl',
        'reduction':'minimum_alternative','direction':'maximize','definition':'caller requests this KL diagnostic only','assumptions':'fixed supplied synthetic laws; not power'}
    c['selection_inputs']['utility_declaration']=u;v=q.separation(change(tmp_path,b,c),base_dir=tmp_path)
    e=v['selection_evidence'];assert math.isclose(e['utility']['value'],math.log(2),rel_tol=1e-14)
    rows=[{'id':'a','cost':{'native_attempts':1,'wall_seconds':60},'quantitative_selection':e},
          {'id':'b','cost':{'native_attempts':1,'wall_seconds':60},'quantitative_selection':deepcopy(e)}]
    rows[1]['quantitative_selection']['utility']['value']=2
    assert q.choose_declared(rows)['id']=='b'
    rows[1]['quantitative_selection']['comparability']['objective']['objective_id']='other'
    assert q.choose_declared(rows) is None


def test_whole_hypothesis_null_labels_admission(tmp_path):
    from ravel.workflow import research_cycle as cycle
    b,o,c,r=fixture(tmp_path);e={'id':'candidate','premise_ids':[],'observable':{'schema_version':2,'kind':'quantitative','contract':b['contract']},
        'predictions':{'null':None,'alt':None},'cost':c['selection_inputs']['cost']['vector']}
    state={'premises':[],'base_dir':str(tmp_path),'contract':{}}
    spec={'quantitative_check':b,'max_seconds':60}
    assert q.admit_design(state,e,spec)['guidance']['planned_hypotheses']==['null','alt']
    e['predictions']['alt']='dummy'
    with pytest.raises(ValueError):q.admit_design(state,e,spec)
    assert cycle._discrimination({'null':'x','alt':'y'})['distinct_declared_outcomes']==2


def test_dense_work_bound_and_source_runtime_refusal(tmp_path):
    b,o,c,r=fixture(tmp_path,gaussian=[[1.,0.],[0.,1.]],calculation='known_gaussian_mahalanobis')
    r['limits']['work_units']=1;b['resources']=pin(tmp_path/'resources.json',r)
    assert run(b,o,tmp_path)['resource_requirements']['status']=='pending_resources'
    r['limits']['work_units']=q.DEFAULT_LIMITS['work_units'];b['resources']=pin(tmp_path/'resources.json',r)
    c['numerics']['runtime_requirements']['files']=[]
    with pytest.raises(ValueError):run(change(tmp_path,b,c),o,tmp_path)


def test_canonical_returned_population_not_boolean_alias(tmp_path):
    b,o,c,r=fixture(tmp_path,observed=(1,2));v=run(b,o,tmp_path)
    v['coordinates'][0]['observed']=True
    with pytest.raises(ValueError):q.verify_value(b,v,base_dir=tmp_path,observation_pin=o)


def cycle_fixture(tmp_path,binding,c):
    from ravel.workflow import research_cycle as cycle
    api=tmp_path/'synthetic_api.py';api.write_text('def mean():\n    return 1\n')
    raw=api.read_bytes();source={'path':str(api),'sha256':hashlib.sha256(raw).hexdigest()}
    context={'schema_version':1,'task_id':'predictive-test','task':'Retain the complete original synthetic test objective and all failures.',
        'source_capsules':[],'api_documents':[{'id':'api','pin':source,'language':'python','role':'api','version':'synthetic control','dependencies':[]}],
        'queries':[{'id':'mean','symbol':'mean','mode':'definition','documents':['api'],'required':True}],
        'requested_quantities':[{'id':'value','artifact':'measurement','pointer':'/value','check':{'kind':'finite'},'meaning':'Synthetic engineering value only.'}],
        'compatibility_groups':[{'id':'group','artifacts':['measurement'],'carryover':False,'basis':'Complete supplied fixture only.'}],
        'max_source_bytes':128000,'max_context_bytes':16000,'max_steps':6}
    contract={'schema_version':1,'id':'predictive-cycle','question':'Compare full source-bound supplied quantitative predictions.',
        'scope':'Inert software control; no physics efficacy.','context_request':pin(tmp_path/'context.json',context),'premises':[],
        'budget':{'calls':10,'output_tokens':0,'wall_seconds':600,'native_attempts':6},'max_experiments':6,'exploration_every':2,'required_experiments':['candidate']}
    root=tmp_path/'cycle';cycle.create(root,contract,base_dir=tmp_path, evaluation_harness=True)
    hypotheses=[{'id':h,'statement':'Supplied synthetic rival '+h,'stream':'citation_led' if h=='null' else 'speculative',
        'premise_ids':[],'source_basis':[],'parents':[]} for h in ('null','alt')]
    cycle.propose(root,hypotheses,origin={'kind':'supplied_source','pin':pin(tmp_path/'hypotheses.json',hypotheses),'description':'Explicit synthetic engineering fixture.'})
    policy={'schema_version':1,'actors':{'proposer':'fixture','executor':'fixture','physics_critic':'critic','skeptical_verifier':'verifier','physics_decider':'decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'}],'claim_scopes':{'synthetic':{'checks':['integrity'],'actions':['delivery','reuse']}}}
    quantity={'schema_version':1,'axes':[{'name':'x','unit':'1'}],'bins':[{'id':'bin','low':[0.],'high':[1.]}],
        'weight_names':['nominal'],'input_weight_unit':'1','representation':'integrated','normalization':{'kind':'absolute','scale':1.,'unit':'1'}}
    qp=pin(tmp_path/'quantities.json',quantity);records=tmp_path/'records.jsonl'
    records.write_text('{"event_id":"a","group_id":"a","shard_id":"toy","weights":{"nominal":1},"fills":[[0.5]]}\n')
    spec={'schema_version':2,'mode':'quantities','source':'Complete inert synthetic source control.',
        'assumptions':['Synthetic producer fixture; no scientific validity.'],'max_seconds':60,'max_attempts':1,'approval_mode':'scripted_yes',
        'task':{'contract':qp['path'],'records':str(records)},'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}},
        'quantitative_check':binding}
    e={'id':'candidate','question':'Compare two supplied rivals.','premise_ids':[],'parent':None,'change':'Fixed full record comparison.',
        'study':pin(tmp_path/'study.json',spec),'cost':c['selection_inputs']['cost']['vector'],'predictions':{'null':None,'alt':None},
        'observable':{'schema_version':2,'kind':'quantitative','contract':binding['contract']},'context_outputs':{},'acceptance_scope':'synthetic','exploratory':False}
    return cycle,root,spec,e


def test_real_public_design_and_plan_full_input_closure(tmp_path):
    from ravel.workflow import science
    b,o,c,r=fixture(tmp_path);cycle,root,spec,e=cycle_fixture(tmp_path,b,c)
    state=cycle.design(root,e)
    assert {b['contract']['path'],b['resources']['path'],str(tmp_path/'prediction.json')} <= {p['path'] for p in state['experiments'][0]['input_pins']}
    planned=cycle.prepare_experiment(root,'candidate',tmp_path/'ordinary-run')
    science.verify_plan(tmp_path/'ordinary-run',approved=False)
    assert not (tmp_path/'ordinary-run'/science.APPROVAL).exists()
    with pytest.raises((ValueError,FileNotFoundError)):science.verify_plan(tmp_path/'ordinary-run',approved=True)
    assert planned['experiments'][0]['observation'] is None


def test_public_observe_inert_failure_keeps_full_denominator(tmp_path,monkeypatch):
    from ravel.workflow import science
    b,o,c,r=fixture(tmp_path);cycle,root,spec,e=cycle_fixture(tmp_path,b,c);cycle.design(root,e)
    rd=tmp_path/'ordinary-run';cycle.prepare_experiment(root,'candidate',rd); admit_method(rd)
    science.approve(rd,'Root-authorized synthetic fixture only.',scripted=True)
    record=pin(rd/'inert-receipt.json',{'status':'failed','scope':'inert software fixture, not native execution'})
    monkeypatch.setattr(science,'packet',lambda rd:{'execution':{'status':'failed'},'errors':[]})
    monkeypatch.setattr(science.execution,'load_execution',lambda rd:{'stages':{'science':{'attempt_record':'inert-receipt.json','attempt_id':'inert','status':'failed'}}})
    state=cycle.observe(root,'candidate');v=state['experiments'][0]['observation']
    assert v['quantitative_evidence'] is None and v['result_category']=='execution_or_adapter_failure_unresolved'
    assert state['contract']['required_experiments']==['candidate'] and v['scientific_acceptance'] is False


def test_actual_common_worker_with_explicit_inert_adapter(tmp_path,monkeypatch):
    from ravel.physics import science_worker
    from ravel.plotting import science_figures
    b,o,c,r=fixture(tmp_path);cycle,root,spec,e=cycle_fixture(tmp_path,b,c)
    producer={'status':'passed','physics_validated':False,**json.loads(Path(o['path']).read_text())}
    class InertAdapter:
        def run(self,task,base,out):return deepcopy(producer)
    rd=tmp_path/'worker';rd.mkdir()
    monkeypatch.setattr(science_worker,'verify_worker',lambda rd:{'base_dir':str(tmp_path),'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}})
    monkeypatch.setattr(science_worker,'execution_spec',lambda rd:spec|{'mode':'synthetic-inert'})
    monkeypatch.setattr(science_worker,'adapter',lambda spec:InertAdapter())
    monkeypatch.setattr(science_figures,'render',lambda *args:{'figures':[],'tables':[]})
    assert science_worker.main([str(rd)])==0
    artifact=json.loads((rd/'outputs/attempt-1/quantitative-check.json').read_text())
    assert artifact['delivery_status']=='complete' and len(artifact['coordinates'])==2
    assert artifact['scientific_acceptance'] is False


def test_real_charged_host_tool_and_prospective_selector(tmp_path):
    from ravel.workflow import agent_graph,agent_host
    b,o,c,r=fixture(tmp_path);c['selection_inputs']['utility_declaration']={
        'objective_id':'objective','source':c['noise']['source'],'metric':'directed_poisson_kl','reduction':'minimum_alternative',
        'direction':'maximize','definition':'Explicit test-only KL preference','assumptions':'Fixed synthetic means only; no power/physics claim'}
    b=change(tmp_path,b,c);r['wall_seconds']=10;r['max_rss_mib']=256;b['resources']=pin(tmp_path/'resources.json',r)
    cycle,root,spec,e=cycle_fixture(tmp_path,b,c);cycle.design(root,e)
    request=pin(tmp_path/'binding.json',b)
    inputs=[{'id':'binding','path':request['path'],'sha256':request['sha256']}]
    inputs += [{'id':'s'+str(i),'path':str(path),'sha256':cycle._pin(path)['sha256']} for i,path in enumerate(q.inputs(b,tmp_path))]
    graph={'schema_version':1,'graph_id':'quantitative-tool','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},
        'nodes':[{'id':'check','kind':'tool','role':'designer','depends_on':[],'inputs':inputs,'packet':None,'action':'quantitative-predictive','max_attempts':1,'parameters':{'request_input':'binding'}}]}
    graph_root=tmp_path/'graph';observed=cycle.execute_graph(root,graph_root,graph,agent_host.AgentHost())
    assert observed['complete'] and observed['usage']['calls']==1
    cycle.bind_quantitative_selection(root,'candidate',graph_root=graph_root,node_id='check')
    selection=cycle.select(root)
    assert selection['designs'][0]['quantitative_selection']['utility']['value'] is not None
    assert selection['execution_authorized'] is False


def test_complete_correlated_65_requires_and_accepts_full_allocation(tmp_path):
    n=65;cov=[[1. if i==j else .01 for j in range(n)] for i in range(n)]
    b,o,c,r=fixture(tmp_path,means=(tuple([0.]*n),tuple([1.]*n)),observed=tuple([1.]*n),
        gaussian=cov,calculation='known_gaussian_mahalanobis')
    v=run(b,o,tmp_path)
    assert v['resource_requirements']['status']=='pending_resources' and len(v['coordinates'])==65
    r['limits']['coordinates']=128;r['limits']['matrix_elements']=4*128**2
    c['requested_limits'].update(coordinates=128,matrix_elements=4*128**2)
    b['resources']=pin(tmp_path/'resources.json',r);v=run(change(tmp_path,b,c),o,tmp_path)
    assert len(v['coordinates'])==65 and v['delivery_status']=='complete'
    assert math.isclose(v['comparisons'][0]['mahalanobis']['null']['value'],65/(1+64*.01),rel_tol=1e-12)


def test_missing_cell_weighted_count_and_source_units_refuse(tmp_path):
    b,o,c,r=fixture(tmp_path);data=json.loads((tmp_path/'observed.json').read_text());data['records'].pop()
    assert run(b,pin(tmp_path/'observed.json',data),tmp_path)['delivery_status']!='complete'
    c['population'][0]['representation']='weighted_estimator'
    assert q.separation(change(tmp_path,b,c),base_dir=tmp_path)['delivery_status']!='complete'


def test_known_gaussian_tail_retains_numerical_underflow(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((0.,),(1.,)),observed=(1000.,),gaussian=[[1.]],calculation='known_gaussian_mahalanobis')
    v=run(b,o,tmp_path);tail=v['comparisons'][0]['conditional_chi_square_tails']['null']
    assert tail['status']=='numerical_underflow' and tail['log_value'] is None
    assert v['calculation_status']=='numerically_unresolved'


def test_ordinary_adapter_keeps_initial_return_and_reports(tmp_path):
    from ravel.physics import quantitative_predictive as adapter
    b,o,c,r=fixture(tmp_path);task={'schema_version':1,'binding':b};out=tmp_path/'pure-operation'
    value=adapter.run(task,tmp_path,out);guard=adapter.Guard(value,task,tmp_path,out)
    guard.finish(deepcopy(value))
    changed=deepcopy(value);changed['comparisons'][0]['directed_kl']['value']=0
    pin(out/'result.json',changed);(out/'quantitative-report.md').write_text(q.markdown(changed))
    with pytest.raises(ValueError):guard.finish(changed)


@pytest.mark.parametrize('gaussian',[False,True])
def test_actual_charged_host_known_law_route(tmp_path,gaussian):
    from ravel.workflow import agent_graph,agent_host,research_cycle as cycle
    kwargs={'gaussian':[[1.,.5],[.5,1.]],'calculation':'known_gaussian_mean_separation'} if gaussian else {'calculation':'fixed_poisson_threshold_power','means':((1.,),(2.,)),'observed':(0,)}
    b,o,c,r=fixture(tmp_path,**kwargs);r['wall_seconds']=10;r['max_rss_mib']=256;b['resources']=pin(tmp_path/'resources.json',r)
    request=pin(tmp_path/'binding.json',b)
    inputs=[{'id':'binding','path':request['path'],'sha256':request['sha256']}]
    inputs += [{'id':'s'+str(i),'path':str(path),'sha256':cycle._pin(path)['sha256']} for i,path in enumerate(q.inputs(b,tmp_path))]
    graph={'schema_version':1,'graph_id':'fixed-law-tool','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},
        'nodes':[{'id':'check','kind':'tool','role':'designer','depends_on':[],'inputs':inputs,'packet':None,
            'action':'quantitative-predictive','max_attempts':1,'parameters':{'request_input':'binding'}}]}
    agent_graph.create(tmp_path/'graph',graph)
    actual=agent_graph.execute(tmp_path/'graph',agent_host.AgentHost(),workers=1)
    origin=cycle._graph_result(tmp_path/'graph','check');value=origin['value']['value']
    assert actual['complete'] and value['delivery_status']=='complete' and value['observation'] is None
    assert value['numerical_provenance']['versions']=={'numpy':'1.26.4','scipy':'1.14.1'}
    assert value['selection_evidence']['utility']['value'] is None and value['scientific_acceptance'] is False


def test_successful_inert_observation_preserves_separate_feedback_gate(tmp_path,monkeypatch):
    from ravel.workflow import science,research_protocol
    b,o,c,r=fixture(tmp_path);cycle,root,spec,e=cycle_fixture(tmp_path,b,c);cycle.design(root,e)
    rd=tmp_path/'ordinary-run';cycle.prepare_experiment(root,'candidate',rd); admit_method(rd)
    science.approve(rd,'Explicit inert engineering observation fixture.',scripted=True)
    output=rd/'outputs/attempt-1';output.mkdir(parents=True)
    result=pin(output/'result.json',json.loads(Path(o['path']).read_text())|{'status':'passed','physics_validated':False})
    d=q.Delivery(b,tmp_path,Path(result['path']),True);d.write(output/'quantitative-check.json')
    pin(rd/'inert-receipt.json',{'stage':'science','attempt_id':'inert','status':'succeeded','exit_code':0,
        'started_utc':None,'finished_utc':None,'child_pid':None,'child_identity':None,
        'scope':'Explicit synthetic ordinary record; no process, native/model or physics execution.'})
    monkeypatch.setattr(science,'packet',lambda rd:{'execution':{'status':'completed'},'errors':[]})
    monkeypatch.setattr(science.execution,'load_execution',lambda rd:{'stages':{'science':{'attempt_record':'inert-receipt.json','attempt_id':'inert','status':'succeeded'}}})
    state=cycle.observe(root,'candidate');observed=state['experiments'][0]['observation']
    assert observed['result_category']=='quantitative_diagnostic_delivery' and observed['outcome'] is None
    assert observed['quantitative_evidence']['delivery_status']=='complete' and observed['scientific_acceptance'] is False
    assert observed['quantitative_evidence']['complete_planned_population']['hypotheses']==['null','alt']
    with pytest.raises(ValueError,match='actual separate role outcome'):
        cycle.feedback_packet(root,'candidate')
    assert observed['quantitative_evidence']['scientific_acceptance'] is False
    status=cycle.status(root)
    assert status['connected_task_complete'] is False
    attempt=status['outcome_metrics']['resource_use']['ordinary_attempts'][0]
    assert attempt['attempt_id']=='inert' and attempt['status']=='succeeded'
    assert attempt['elapsed_seconds'] is None and attempt['native_calls'] is None and attempt['billed_cost'] is None
    approval=status['outcome_metrics']['interventions']['approval_observations'][0]
    assert approval['classification']=='machine_scripted_assent' and approval['human_origin_authenticated'] is False


def test_complete_permutation_requires_source_and_coordinate_rebinding(tmp_path):
    b,o,c,r=fixture(tmp_path);original=run(b,o,tmp_path)['comparisons'][0]['directed_kl']['value']
    c['population'].reverse()
    data=json.loads((tmp_path/'prediction.json').read_text())
    for records in data.values():records.reverse()
    updated=pin(tmp_path/'prediction.json',data)
    for h in c['hypotheses']:h['prediction']['source']=updated
    c['source_provenance'][0]=updated
    data=json.loads((tmp_path/'observed.json').read_text());data['records'].reverse()
    o=pin(tmp_path/'observed.json',data);b=change(tmp_path,b,c);v=run(b,o,tmp_path)
    assert v['comparisons'][0]['directed_kl']['value']==original
    assert [x['id'] for x in v['coordinates']]==['q1','q0']
    data['records'].reverse();v=run(b,pin(tmp_path/'observed.json',data),tmp_path)
    assert v['delivery_status']!='complete'


def test_ordinary_separation_mode_plan_is_gated_and_whole(tmp_path):
    from ravel.workflow import science
    b,o,c,r=fixture(tmp_path)
    policy={'schema_version':1,'actors':{'proposer':'fixture','executor':'fixture','physics_critic':'critic','skeptical_verifier':'verifier','physics_decider':'decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'}],'claim_scopes':{'synthetic':{'checks':['integrity'],'actions':['delivery','reuse']}}}
    spec={'schema_version':2,'mode':'quantitative-predictive','source':'Complete supplied fixed-law engineering control.',
        'assumptions':['No scientific qualification.'],'max_seconds':60,'max_attempts':1,'approval_mode':'scripted_yes',
        'task':{'schema_version':1,'binding':b},'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    path=tmp_path/'separation-study.json';pin(path,spec);rd=tmp_path/'ordinary-separation'
    science.plan(rd,path); admit_method(rd)
    science.verify_plan(rd,approved=False)
    assert not (rd/science.APPROVAL).exists()
    with pytest.raises((ValueError,FileNotFoundError)):science.verify_plan(rd,approved=True)
    assert science.execution_spec(rd)['task']['binding']==b
    assert set(q.inputs(b,tmp_path))<=set(science.task_inputs(spec,tmp_path))


def test_legacy_full_interval_comparison_remains_connected(tmp_path):
    from ravel.physics import research_comparison
    left=pin(tmp_path/'left.json',{'value':[1,2],'interval':[[.9,1.1],[1.9,2.1]],'quality':True})
    right=pin(tmp_path/'right.json',{'value':[3,4],'interval':[[2.9,3.1],[3.9,4.1]],'quality':True})
    rule=pin(tmp_path/'interval-rule.json',{'schema_version':1,'metric':'loss','unit':'1','direction':'minimize',
        'min_gain':.1,'tolerance':.001,'uncertainty':'supplied_intervals','reduction':'all_cells'})
    # Legacy schema uses source-table pins without the new optional quantitative contract.
    rows=[{'id':'cell'+str(j),'metric':'loss','unit':'1','exposure':'adaptive_full',
        'left':{'source':left,'value_pointer':'/value/'+str(j),'interval_pointer':'/interval/'+str(j),'quality_pointer':'/quality'},
        'right':{'source':right,'value_pointer':'/value/'+str(j),'interval_pointer':'/interval/'+str(j),'quality_pointer':'/quality'}} for j in range(2)]
    request=pin(tmp_path/'comparison.json',{'schema_version':1,'protocol_sha256':'a'*64,'comparison_id':'legacy-comparison','rule':rule,'cells':rows,'dependencies':[]})
    value=research_comparison.calculate({'schema_version':1,'request':request},tmp_path)
    assert value['decision']=='better' and value['cell_count']==2 and value['physics_validated'] is False


# Exact V1 tests above retain their bodies. This fixture binds the physical
# implementation module independently of the product's unwrap observation.
def test_released_numpy_dispatcher_and_original_implementation(tmp_path):
    import numpy as np
    from numpy.core import _multiarray_umath,overrides
    from numpy.linalg import linalg as implementation_module
    assert type(np.linalg.solve) is _multiarray_umath._ArrayFunctionDispatcher
    assert inspect.isfunction(inspect.unwrap(np.linalg.solve))
    assert Path(inspect.getfile(inspect.unwrap(np.linalg.solve)))==Path(implementation_module.__file__)
    b,o,c,r=fixture(tmp_path,gaussian=[[1.,.5],[.5,1.]],calculation='known_gaussian_mahalanobis')
    v=run(b,o,tmp_path)
    observed=v['numerical_provenance']['numpy_solve_observation']
    assert observed['public_export_matches_implementation_module'] and observed['unwrapped_python_implementation']
    assert observed['implementation_source']['path']==str(Path(implementation_module.__file__).absolute())
    assert observed['dispatcher_extension_source']['path']==str(Path(_multiarray_umath.__file__).absolute())
    assert observed['wrapper_factory_source']['path']==str(Path(overrides.__file__).absolute())
    assert v['delivery_status']=='complete' and len(v['coordinates'])==2


def test_numpy_unwrapped_identity_must_match_released_implementation(tmp_path,monkeypatch):
    import numpy as np
    b,o,c,r=fixture(tmp_path,gaussian=[[1.,0.],[0.,1.]],calculation='known_gaussian_mahalanobis')
    original=np.linalg.solve.__wrapped__
    monkeypatch.setattr(np.linalg.solve,'__wrapped__',lambda a,b: original(a,b))
    with pytest.raises(ValueError,match='declared unwrapped Python implementation'):run(b,o,tmp_path)


@pytest.mark.parametrize('capacity',['sources','single_bytes','unique_bytes'])
def test_requested_source_capacity_is_stricter_before_payload_reads(tmp_path,monkeypatch,capacity):
    from ravel.workflow import research_cycle as cycle
    b,o,c,r=fixture(tmp_path)
    if capacity=='sources':
        c['requested_limits'][capacity]=1
        b=change(tmp_path,b,c)
    else:
        # The full prediction is deliberately larger than either bootstrap
        # declaration, while its selected scientific record vectors stay exact.
        original_prediction=c['hypotheses'][0]['prediction']['source']
        payload=json.loads(Path(original_prediction['path']).read_bytes())
        payload['retained_transport_note']='x'*65536
        prediction=pin(tmp_path/'prediction.json',payload)
        for h in c['hypotheses']:h['prediction']['source']=deepcopy(prediction)
        c['source_provenance'][0]=deepcopy(prediction)
        if capacity=='single_bytes':
            c['requested_limits'][capacity]=prediction['size']-1
            b=change(tmp_path,b,c)
            assert max(b['contract']['size'],b['resources']['size'])<c['requested_limits'][capacity]
        else:
            # Re-pin until the literal size of the complete contract (which
            # includes its requested limit) is consistent with this census.
            for _ in range(4):
                b=change(tmp_path,b,c)
                total=sum(p['size'] for p in (b['contract'],b['resources'],prediction,c['noise']['source']))
                c['requested_limits'][capacity]=total-1
            b=change(tmp_path,b,c)
            total=sum(p['size'] for p in (b['contract'],b['resources'],prediction,c['noise']['source']))
            assert c['requested_limits'][capacity]==total-1
            assert max(p['size'] for p in (b['contract'],b['resources'],prediction,c['noise']['source']))<c['requested_limits'][capacity]
    assert r['limits'][capacity]>c['requested_limits'][capacity]
    calls=[];original=cycle._bounded_source_snapshot
    def observed(path,maximum):
        calls.append(str(Path(path).absolute()));return original(path,maximum)
    monkeypatch.setattr(cycle,'_bounded_source_snapshot',observed)
    with pytest.raises(ValueError,match='requested/allocation minimum'):
        q.separation(b,base_dir=tmp_path)
    assert str((tmp_path/'prediction.json').absolute()) not in calls
    assert str((tmp_path/'law.json').absolute()) not in calls
    assert len(c['population'])==2 and [h['hypothesis_id'] for h in c['hypotheses']]==['null','alt']


def test_one_effective_minimum_covers_all_requested_limits(tmp_path):
    b,o,c,r=fixture(tmp_path)
    for key in q.DEFAULT_LIMITS:
        r['limits'][key]=2*c['requested_limits'][key]
    requirements=q.requirements(c,r)
    assert requirements['effective']['limits']==c['requested_limits']
    assert requirements['allocation']==r
    assert requirements['required']['coordinates']==len(c['population'])


@pytest.mark.parametrize('cov,expected_status',[
    ([[1.,1.],[1.,1.]],'degenerate_or_unresolved_condition'),
    ([[1.,.999999999999],[.999999999999,1.]],'degenerate_or_unresolved_condition'),
    ([[1.,2.],[2.,1.]],'non_positive_definite_or_unresolved')])
def test_uncomputed_full_gaussian_tail_preserves_covariance_cause(tmp_path,monkeypatch,cov,expected_status):
    from scipy import stats
    b,o,c,r=fixture(tmp_path,gaussian=cov,calculation='known_gaussian_mahalanobis')
    def forbidden(*args,**kwargs):
        raise AssertionError('no chi-square probability may be evaluated without the full-rank statistic')
    monkeypatch.setattr(stats.chi2,'sf',forbidden)
    monkeypatch.setattr(stats.chi2,'logsf',forbidden)
    v=run(b,o,tmp_path);pair=v['comparisons'][0]
    assert v['calculation_status']=='degenerate' and len(v['coordinates'])==2
    assert [pair['null_id'],pair['alternative_id']]==['null','alt']
    for h in ('null','alt'):
        statistic=pair['mahalanobis'][h];tail=pair['conditional_chi_square_tails'][h]
        assert statistic['status']==tail['status']==expected_status
        assert statistic['value'] is None and tail['value'] is None
        assert tail['reference_tail_evaluation']=='not_evaluated'
        assert tail['diagnostics']==statistic['diagnostics']
        assert tail['diagnostics']['full_dimension']==2
    assert pair['d2']['value'] is None and pair['kl_common_covariance']['value'] is None
    assert v['numerical_provenance']['versions']=={'numpy':'1.26.4','scipy':'1.14.1'}


def test_available_full_gaussian_tail_underflow_is_not_covariance_degeneracy(tmp_path):
    b,o,c,r=fixture(tmp_path,means=((0.,),(1.,)),observed=(1000.,),gaussian=[[1.]],calculation='known_gaussian_mahalanobis')
    v=run(b,o,tmp_path);pair=v['comparisons'][0]
    assert v['calculation_status']=='numerically_unresolved'
    for h in ('null','alt'):
        statistic=pair['mahalanobis'][h];tail=pair['conditional_chi_square_tails'][h]
        assert statistic['status']=='evaluated' and statistic['value'] is not None
        assert statistic['diagnostics']['rank']==statistic['diagnostics']['full_dimension']==1
        assert tail['status']=='numerical_underflow' and tail['value']==0.0
        assert 'reference_tail_evaluation' not in tail


def quantitative_host_fixture(tmp_path):
    """Complete typed source roster, without invoking the numerical tool."""
    from ravel.workflow import agent_host
    b,o,c,r=fixture(tmp_path,gaussian=[[1.,.5],[.5,1.]],calculation='known_gaussian_mean_separation')
    r['wall_seconds']=10;r['max_rss_mib']=256;b['resources']=pin(tmp_path/'resources.json',r)
    def records():
        bound=pin(tmp_path/'binding.json',b)
        sources={p['path']:p for p in [b['contract'],b['resources'],*q._all_pins(c)]}
        inputs=[{'id':'binding','path':bound['path'],'sha256':bound['sha256']}]
        inputs += [{'id':'s'+str(i),'path':p['path'],'sha256':p['sha256']} for i,p in enumerate(sources.values())]
        node={'id':'check','kind':'tool','role':'designer','depends_on':[],'inputs':inputs,'packet':None,
            'action':'quantitative-predictive','max_attempts':1,'parameters':{'request_input':'binding'}}
        return node,{'input_artifacts':deepcopy(inputs)}
    return agent_host,b,c,r,records


@pytest.mark.parametrize('limit,value',[('sources',1),('single_bytes',2_000_000),('unique_bytes',2_000_000)])
@pytest.mark.parametrize('side',['requested','allocation'])
def test_host_quantitative_minimum_refuses_before_large_input_hash(tmp_path,monkeypatch,limit,value,side):
    host,b,c,r,records=quantitative_host_fixture(tmp_path)
    if side=='requested':
        c['requested_limits'][limit]=value;b['contract']=pin(tmp_path/'contract.json',c)
    else:
        r['limits'][limit]=value;b['resources']=pin(tmp_path/'resources.json',r)
    node,request=records();original=host.file_hash;large_reads=[]
    def bounded_hash(path):
        if Path(path).stat().st_size>2_000_000:
            large_reads.append(str(path));raise AssertionError('large payload hashed before complete resource admission')
        return original(path)
    monkeypatch.setattr(host,'file_hash',bounded_hash)
    with pytest.raises(host.HostFailure,match='complete quantitative source population'):
        host.AgentHost()._pins(node,request)
    assert large_reads==[]


@pytest.mark.parametrize('model',[False,True])
def test_quantitative_operational_allowance_does_not_admit_unrelated_or_model_inputs(tmp_path,model):
    host,b,c,r,records=quantitative_host_fixture(tmp_path);node,request=records()
    if model:
        node['kind']='model';node['action']='model'
    else:
        unrelated=tmp_path/'unrelated.dat';unrelated.write_bytes(b'x'*2_000_001)
        row={'id':'unrelated','path':str(unrelated),'sha256':hashlib.sha256(unrelated.read_bytes()).hexdigest()}
        node['inputs'].append(row);request['input_artifacts'].append(deepcopy(row))
    with pytest.raises(host.HostFailure,match='host input bytes differ'):
        host.AgentHost()._pins(node,request)


@pytest.mark.parametrize('role,attempts',[('physics_critic',1),('designer',2)])
def test_quantitative_operational_allowance_preserves_blind_and_retry_boundaries(tmp_path,role,attempts):
    host,b,c,r,records=quantitative_host_fixture(tmp_path);node,request=records()
    node.update(role=role,max_attempts=attempts)
    with pytest.raises(host.HostFailure,match='host input bytes differ'):
        host.AgentHost()._pins(node,request)


def test_quantitative_operational_runtime_source_still_requires_original_hash(tmp_path):
    host,b,c,r,records=quantitative_host_fixture(tmp_path)
    original=next(p for p in c['numerics']['runtime_requirements']['files'] if p['size']>2_000_000)
    copied=tmp_path/'declared-runtime-copy.dat';copied.write_bytes(Path(original['path']).read_bytes())
    declared={**original,'path':str(copied)}
    c['numerics']['runtime_requirements']['files']=[declared if p==original else p for p in c['numerics']['runtime_requirements']['files']]
    b['contract']=pin(tmp_path/'contract.json',c);node,request=records()
    raw=copied.read_bytes();copied.write_bytes(bytes([raw[0]^1])+raw[1:])
    with pytest.raises(host.HostFailure,match='host input bytes differ'):
        host.AgentHost()._pins(node,request)
