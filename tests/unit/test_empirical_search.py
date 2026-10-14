"""Portable controller/source-operation tests, not model or native efficacy."""
from copy import deepcopy
from itertools import permutations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import pytest

MODULE=Path(__file__).resolve().parents[2]/'src/ravel/workflow/empirical_search.py'
spec=importlib.util.spec_from_file_location('ravel.workflow.empirical_search',MODULE)
e=importlib.util.module_from_spec(spec);sys.modules[spec.name]=e;spec.loader.exec_module(e)


def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')
    return {'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}


def contract(**changes):
    c={'schema_version':1,'scope':'Explicit programming calibration; no physics qualification.',
        'question':'Construct a complete result then improve its measured error while retaining source obligations.',
        'metric':'declared exact program error','direction':'minimize','policy':'branch','num_seeds':1,
        'max_debug_depth':2,'component_experiments':False,'proposal_transport':'source_tool',
        'budget':{'max_rounds':8,'max_candidates':8,'max_model_calls':8,'max_reserved_output_tokens':128000,
            'output_per_proposal':16000,'max_experiment_attempts':32},
        'hypotheses':[{'id':'group-cross-terms','component':'grouping','statement':'Grouping before outer products may preserve same-group cross terms.',
            'discriminating_experiment':'Remove grouping only; inspect the complete paired population.',
            'predictions':{'same-group':'Cross terms change.','no-same-group':'Cross terms remain identical.'}}],
        'source_obligations':[{'id':'complete-census','description':'Retain all original groups, signed/zero weights and all requested output components.'}]}
    c.update(changes);return c


def population(tmp_path,candidates,*,values=None,status=None,missing=()):
    cases=[{'id':key,'partition':part,'input_sha256':hashlib.sha256(key.encode()).hexdigest()}
        for key,part in [('dev','development'),('blind','held_out'),('whole','full_case')]]
    rows=[];trials=[];ledger=[]
    for cid,parent,kind,score,components in candidates:
        source=tmp_path/(cid+'.py');source.write_text('def estimator(x):\n    return x\n')
        sha=hashlib.sha256(source.read_bytes()).hexdigest()
        rows.append({'id':cid,'parent':parent,'kind':kind,'recipe_sha256':sha,'components':components,
            'reason':'Source-only controlled candidate, no actual model/native call.'})
        for case in cases:
            pair=(cid,case['id'])
            if pair in missing:
                trials.append({'candidate_id':cid,'case_id':case['id'],'result':None,'check':None});continue
            value=score if values is None else values.get(pair,score)
            state='passed' if status is None else status.get(pair,'passed')
            result=write(tmp_path/(cid+'-'+case['id']+'-result.json'),{'measured_scalar':value,'execution':'Explicit supplied report fixture.'})
            check=write(tmp_path/(cid+'-'+case['id']+'-check.json'),{'schema_version':1,
                'candidate_id':cid,'case_id':case['id'],'input_sha256':case['input_sha256'],
                'recipe_sha256':sha,'result_sha256':result['sha256'],'metric':contract()['metric'],
                'status':state,'score':value if state=='passed' else None,'limitations':['Mechanical outcome fixture, not scientific acceptance.']})
            trials.append({'candidate_id':cid,'case_id':case['id'],'result':result,'check':check})
            ledger.append({'id':cid+'-'+case['id'],'kind':'experiment','candidate_id':cid,
                'case_id':case['id'],'reserved_output_tokens':0,'artifact':result})
    plan={'schema_version':1,'scope':contract()['scope'],'metric':contract()['metric'],
        'direction':'minimize','candidates':rows,'cases':cases,'trials':trials}
    return plan,ledger


def advance(tmp_path,plan,ledger,c=None,previous=None,name='plan.json'):
    return e.advance(c or contract(),write(tmp_path/name,plan),ledger,base_dir=tmp_path,previous=previous)


def test_measured_branch_retains_better_incumbent_while_linear_improves_latest(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping']),('worse','seed','evolved',5,['grouping'])])
    branch=advance(tmp_path,plan,ledger)
    linear=advance(tmp_path,plan,ledger,contract(policy='linear'),name='linear.json')
    assert branch['decision']['parent_candidate_id']=='seed'
    assert linear['decision']['parent_candidate_id']=='worse'
    assert branch['decision']['research_incumbent']=='seed'
    assert branch['usage']==linear['usage'] and branch['scientific_acceptance'] is False


def test_component_ablation_selects_observed_high_impact_component(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping','weighting']),
        ('dropgroup','seed','ablation',5,['weighting']),('dropweight','seed','ablation',2,['grouping'])])
    record=advance(tmp_path,plan,ledger,contract(component_experiments=True))
    assert record['decision']['kind']=='improve_component'
    assert record['decision']['component_id']=='grouping'
    assert record['decision']['parent_candidate_id']=='seed'
    assert len(record['decision']['hypotheses'])==1


@pytest.mark.parametrize('order',list(permutations(('g_high','g_low','weight'))))
@pytest.mark.parametrize('direction',['minimize','maximize'])
def test_repeated_component_losses_use_explicit_maximum_independent_of_row_order(tmp_path,order,direction):
    scores={'minimize':{'seed':1,'g_high':10,'g_low':2,'weight':5},
        'maximize':{'seed':10,'g_high':1,'g_low':9,'weight':6}}[direction]
    candidates=[('seed',None,'seed',scores['seed'],['grouping','weighting'])]
    candidates += [(key,'seed','ablation',scores[key],
        ['grouping'] if key=='weight' else ['weighting']) for key in order]
    plan,ledger=population(tmp_path,candidates);plan['direction']=direction
    record=advance(tmp_path,plan,ledger,contract(component_experiments=True,direction=direction))
    assert record['decision']['kind']=='improve_component'
    assert record['decision']['component_id']=='grouping'
    assert [row['candidate_id'] for row in record['decision']['development_history']]==['seed',*order]
    assert {row['candidate_id']:row['score'] for row in record['decision']['development_history']}==scores
    assert record['usage']['experiment_attempts']==12
    assert 'maximum finite observed loss' in record['decision']['reason']
    assert record['scientific_acceptance'] is False


@pytest.mark.parametrize('status',['unresolved','failed'])
@pytest.mark.parametrize('unknown_first',[False,True])
def test_unresolved_or_failed_repeat_does_not_erase_a_finite_component_loss(tmp_path,status,unknown_first):
    repeated=[('measured','seed','ablation',10,['weighting']),
        ('unknown','seed','ablation',100,['weighting'])]
    if unknown_first:repeated.reverse()
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping','weighting']),
        *repeated,('weight','seed','ablation',5,['grouping'])],status={('unknown','dev'):status})
    record=advance(tmp_path,plan,ledger,contract(component_experiments=True))
    assert record['decision']['component_id']=='grouping'
    rows={row['candidate_id']:row for row in record['decision']['development_history']}
    assert rows['unknown']['score'] is None
    assert rows['unknown']['missing_cases']==(['dev'] if status=='unresolved' else [])
    assert rows['unknown']['failed_cases']==(['dev'] if status=='failed' else [])
    assert rows['measured']['score']==10


@pytest.mark.parametrize('components',[['grouping','weighting'],['weighting','grouping']])
@pytest.mark.parametrize('reverse_rows',[False,True])
def test_equal_component_maxima_follow_retained_source_component_order(tmp_path,components,reverse_rows):
    contrasts=[('group','seed','ablation',5,['weighting']),
        ('weight','seed','ablation',5,['grouping'])]
    if reverse_rows:contrasts.reverse()
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,components),*contrasts])
    record=advance(tmp_path,plan,ledger,contract(component_experiments=True))
    assert record['decision']['component_id']==components[0]
    assert 'equal maxima follow retained component order' in record['decision']['reason']


def test_component_experiment_is_requested_before_attributing_an_untested_effect(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping','weighting'])])
    record=advance(tmp_path,plan,ledger,contract(component_experiments=True))
    assert record['decision']['kind']=='ablate_component' and record['decision']['component_id']=='grouping'


def test_compound_ablation_is_not_single_component_attribution(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping','weighting']),('compound','seed','ablation',10,[])])
    record=advance(tmp_path,plan,ledger,contract(component_experiments=True))
    assert record['decision']['kind']=='ablate_component'


def test_known_full_case_failure_cannot_hide_behind_a_good_development_score(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',10,['grouping']),('bad','seed','evolved',0,['grouping'])],
        status={('bad','whole'):'failed'})
    record=advance(tmp_path,plan,ledger)
    assert record['decision']['parent_candidate_id']=='seed'
    assert record['decision']['development_history'][1]['failed_cases']==['whole']


def test_no_good_candidate_routes_a_real_failure_to_bounded_debug(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])],status={('seed','dev'):'failed'})
    record=advance(tmp_path,plan,ledger)
    assert record['decision']['kind']=='debug' and record['decision']['research_incumbent'] is None


def test_unknown_result_requests_evidence_without_calling_it_a_failure(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])],missing=[('seed','dev')])
    record=advance(tmp_path,plan,ledger)
    assert record['decision']['kind']=='evaluate_existing'
    assert record['decision']['development_history'][0]['failed_cases']==[]


def test_unresolved_measurement_requests_new_discriminating_plan_not_failure_or_overwrite(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])],status={('seed','dev'):'unresolved'})
    record=advance(tmp_path,plan,ledger)
    assert record['decision']['kind']=='request_precision_plan'
    assert record['decision']['development_history'][0]['failed_cases']==[]


def test_unresolved_alternative_does_not_veto_improvement_of_a_measured_successful_branch(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping']),('unknown','seed','evolved',0,['grouping'])],
        status={('unknown','dev'):'unresolved'})
    record=advance(tmp_path,plan,ledger)
    assert record['decision']['kind']=='improve' and record['decision']['parent_candidate_id']=='seed'
    assert record['decision']['development_history'][1]['missing_cases']==['dev']


def test_unknown_development_cannot_request_an_attempt_outside_the_declared_budget(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])],missing=[('seed','dev')])
    c=contract();c['budget']['max_experiment_attempts']=2
    record=advance(tmp_path,plan,ledger,c)
    assert record['decision']['kind']=='stop_budget'


def test_generation_cap_still_routes_existing_candidate_to_validation(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])],missing=[('seed','blind'),('seed','whole')])
    c=contract();c['budget']['max_candidates']=1
    record=advance(tmp_path,plan,ledger,c)
    assert record['decision']['kind']=='request_validation'


def test_complete_validation_requests_review_not_scientific_acceptance(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])])
    c=contract();c['budget']['max_candidates']=1
    record=advance(tmp_path,plan,ledger,c)
    assert record['decision']['kind']=='request_full_case_review'
    assert record['decision']['scientific_acceptance'] is False and record['execution_identity_checked'] is False


def test_future_validation_answers_do_not_tune_the_selected_component(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping','weighting']),('dropgroup','seed','ablation',4,['weighting']),
        ('dropweight','seed','ablation',2,['grouping'])],values={('dropgroup','blind'):-1000,('dropweight','blind'):1000})
    record=advance(tmp_path,plan,ledger,contract(component_experiments=True))
    assert record['decision']['component_id']=='grouping'
    assert all('blind' not in row.get('missing_cases',[]) for row in record['decision']['development_history'])
    assert '-1000' not in json.dumps(record['decision']) and '1000' not in json.dumps(record['decision'])


@pytest.mark.parametrize('mutation',['prior-source','case-denominator','charge-reset','old-result'])
def test_round_successor_cannot_rewrite_old_scope_source_result_or_budget(tmp_path,mutation):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])])
    first=advance(tmp_path,plan,ledger);prior=write(tmp_path/'round1.json',first)
    new=deepcopy(plan);newledger=deepcopy(ledger)
    if mutation=='prior-source':new['candidates'][0]['reason']='different original source meaning'
    if mutation=='case-denominator':new['cases'][0]['input_sha256']='0'*64
    if mutation=='charge-reset':newledger=[]
    if mutation=='old-result':
        result=write(tmp_path/'changed.json',{'new':'answer'})
        new['trials'][0]['result']=result
        check=deepcopy(json.loads((tmp_path/new['trials'][0]['check']['path']).read_bytes()))
        check['result_sha256']=result['sha256'];new['trials'][0]['check']=write(tmp_path/'changedcheck.json',check)
    with pytest.raises(ValueError):advance(tmp_path,new,newledger,previous=prior,name='newplan.json')


def test_new_round_adds_actual_observed_branch_while_retaining_previous_inputs(tmp_path):
    firstplan,firstledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])])
    record=advance(tmp_path,firstplan,firstledger);prior=write(tmp_path/'round1.json',record)
    newplan,newledger=population(tmp_path,[('seed',None,'seed',1,['grouping']),('next','seed','evolved',0,['grouping'])])
    # Keep first outcomes as literal pins, rather than replacing them during a new run.
    newplan['trials'][:3]=deepcopy(firstplan['trials']);newledger[:3]=deepcopy(firstledger)
    second=advance(tmp_path,newplan,newledger,previous=prior,name='plan2.json')
    assert second['round']==2 and second['usage']['experiment_attempts']==6
    assert second['decision']['research_incumbent']=='next'


@pytest.mark.parametrize('mutation',['schema-bool','round-bool','fake-acceptance','new-contract'])
def test_rehashed_round_metadata_cannot_gain_authority_or_change_contract(tmp_path,mutation):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])])
    first=advance(tmp_path,plan,ledger)
    if mutation=='schema-bool':first['schema_version']=True
    if mutation=='round-bool':first['round']=True
    if mutation=='fake-acceptance':first['scientific_acceptance']=True
    if mutation=='new-contract':first['contract']['source_obligations'][0]['description']='Drop original semantics'
    prior=write(tmp_path/'round.json',first)
    with pytest.raises(ValueError):advance(tmp_path,plan,ledger,previous=prior,name='successor.json')


def test_actual_host_budget_retains_one_spent_call_and_stops_at_two(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])])
    model=write(tmp_path/'model.json',{'real_host_fixture_disclosed':True})
    ledger.insert(0,{'id':'call1','kind':'model','candidate_id':'seed','case_id':None,'reserved_output_tokens':16000,'artifact':model})
    c=contract(proposal_transport='agent_host_external');c['budget'].update(max_model_calls=2,max_reserved_output_tokens=32000)
    first=advance(tmp_path,plan,ledger,c)
    assert first['decision']['kind']=='improve' and first['usage']['model_calls']==1
    c['budget']['max_model_calls']=1
    limited=advance(tmp_path,plan,ledger,c,name='limitedplan.json')
    assert limited['decision']['kind']=='request_full_case_review'


@pytest.mark.parametrize('change',['missing-charge','excess-attempt','bool-tokens','missing-partition'])
def test_explicit_denominator_and_cumulative_resource_admission(tmp_path,change):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping'])]);c=contract()
    if change=='missing-charge':ledger.pop()
    if change=='excess-attempt':c['budget']['max_experiment_attempts']=2
    if change=='bool-tokens':ledger[0]['reserved_output_tokens']=False
    if change=='missing-partition':plan['cases'][1]['partition']='development'
    with pytest.raises(ValueError):advance(tmp_path,plan,ledger,c)


def request(tmp_path,plan):
    source=tmp_path/'seed.py';before='return x';after='return x + 1'
    license=tmp_path/'LICENSE';license.write_text('Explicit test-owned source license.\n')
    compound=tmp_path/'compound.py';compound.write_text(source.read_text().replace(before,after))
    def p(path):return {'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    return {'schema_version':1,'finding':{'id':'measured-grouping','claim':'Improve the selected component','objection':'Measured contrast identified a useful component target.'},
        'baseline':p(source),'compound_candidate':p(compound),'license':p(license),
        'component':{'id':'grouping','before':before,'after':after},'control_probes':[],
        'rivals':[{'id':'signal','statement':'Selected change alters the declared result','predictions':{'component':['supported']}},
            {'id':'null','statement':'Selected change has no effect','predictions':{'component':['contradicted']}}],
        'next_actions':{status:{'action':'request_evidence','reason':'Require separately admitted actual measurement'} for status in ('supported','contradicted','unresolved')},
        'evaluation_contract':None}


def test_selected_component_produces_complete_literal_controlled_source(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping']),('drop','seed','ablation',4,[])])
    record=advance(tmp_path,plan,ledger,contract(component_experiments=True))
    before=(tmp_path/'seed.py').read_bytes()
    result=e.prepare_component_followup(record,request(tmp_path,plan),base_dir=tmp_path)
    assert 'return x + 1' in result['preparation']['controlled_source']
    assert (tmp_path/'seed.py').read_bytes()==before
    assert result['old_votes_carried']==[] and result['scientific_acceptance'] is False


@pytest.mark.parametrize('mutation',['component','parent-source','decision'])
def test_component_source_followup_cannot_substitute_parent_or_selected_target(tmp_path,mutation):
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping']),('drop','seed','ablation',4,[])])
    record=advance(tmp_path,plan,ledger,contract(component_experiments=True));r=request(tmp_path,plan)
    if mutation=='component':r['component']['id']='different'
    if mutation=='parent-source':r['baseline']['sha256']='0'*64
    if mutation=='decision':record['decision']['parent_candidate_id']='drop'
    with pytest.raises(ValueError):e.prepare_component_followup(record,r,base_dir=tmp_path)


def test_complete_nested_inventory_refuses_population_exceeding_normal_graph_inputs(tmp_path):
    candidates=[('c'+str(i),None,'seed',i,['grouping']) for i in range(8)]
    plan,ledger=population(tmp_path,candidates)
    for case_index in range(5):
        case={'id':'extra'+str(case_index),'partition':'development','input_sha256':hashlib.sha256(str(case_index).encode()).hexdigest()}
        plan['cases'].append(case)
        for candidate in plan['candidates']:
            cid=candidate['id'];result=write(tmp_path/(cid+'-'+case['id']+'.json'),{'measurement':0})
            check=write(tmp_path/(cid+'-'+case['id']+'-check.json'),{'schema_version':1,'candidate_id':cid,
                'case_id':case['id'],'input_sha256':case['input_sha256'],'recipe_sha256':candidate['recipe_sha256'],
                'result_sha256':result['sha256'],'metric':plan['metric'],'status':'passed','score':0,'limitations':['Mechanical graph capacity control.']})
            plan['trials'].append({'candidate_id':cid,'case_id':case['id'],'result':result,'check':check})
            ledger.append({'id':cid+'-'+case['id'],'kind':'experiment','candidate_id':cid,'case_id':case['id'],
                'reserved_output_tokens':0,'artifact':result})
    req={'schema_version':1,'contract':contract(),'plan':write(tmp_path/'plan.json',plan),'ledger':ledger,'previous':None}
    with pytest.raises(ValueError,match='ordinary graph capacity'):e.input_pins(req,base_dir=tmp_path)
