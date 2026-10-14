"""Successful-parent lineage controls, not actual frontier adaptation efficacy."""
from copy import deepcopy
from pathlib import Path

import pytest

from ravel import analysis_sources as sources
from ravel.physics import analysis_ir, routine_candidate as candidate, routine_evolution as evolution
from ravel.workflow import agent_graph, execution, physics_review, science
from ravel.workflow.state_io import atomic_json, read_json
from test_routine_candidate import setup, _external_control_reply, pin


def accepted_control(tmp_path, monkeypatch):
    """Run actual IR; supplied review/supervision controls are explicitly mocked."""
    task,config=setup(tmp_path)
    correct=deepcopy(config['candidates'][-1]);correct['parent']=None
    config['candidates']=[correct];config['repair_board']=[]
    atomic_json(task['input'],config);task['candidate']=correct['id']
    graph=tmp_path/'model-graph'
    prepared=candidate.prepare_agent_request(task,tmp_path,graph,model='fixture-control',reasoning_effort='high',
        max_output_tokens=12000,requested_task='Complete supplied engineering source selection.')
    _external_control_reply(task,graph,prepared)
    draft=tmp_path/'actual-draft.json'
    materialized=candidate.materialize_agent_candidate(graph,source_task=task,base_dir=tmp_path,
        output_config=draft,candidate_id='model-initial')
    rd=tmp_path/'study';out=rd/'outputs/attempt-1'
    result=candidate.run(materialized['task'],tmp_path,out)
    assert result['candidate_disposition']=='verified_on_supplied_events'
    atomic_json(out/'result.json',result)
    for relative in (science.SPEC,science.PLAN,science.APPROVAL,'outputs/attempt-1/checkin2.json','record.json'):
        atomic_json(rd/relative,{'fixture':'supplied supervision control, not actual scientific acceptance'})
    monkeypatch.setattr(science,'verify_plan',lambda *a,**k:{})
    monkeypatch.setattr(execution,'stage_errors',lambda *a,**k:[])
    monkeypatch.setattr(execution,'load_execution',lambda *a,**k:{'stages':{'science':{'attempt_record':str(rd/'record.json')}}})
    monkeypatch.setattr(physics_review,'gate_errors',lambda *a,**k:[])
    monkeypatch.setattr(physics_review,'status',lambda *a,**k:{'cycle_id':'fixture-cycle','state':'accepted'})
    monkeypatch.setattr(physics_review,'_read',lambda *a,**k:({},[]))
    monkeypatch.setattr(physics_review,'_view',lambda *a,**k:{'cycle':{'cycle_id':'fixture-cycle','snapshots':[]}})
    lineage=evolution.capture_incumbent(rd,tmp_path/'round.json',objective='Add a useful source-derived diagnostic without changing selection.',
        metric='Declared independent mismatch count',direction='minimize',incumbent_score=0)
    return materialized['task'],graph,lineage,rd


def fresh_evaluation(task,tmp_path, *, relabel_only=False, include_prior_case=False):
    config=read_json(task['input']);events=read_json(config['events']['path'])
    for row in events:
        row['event_id']='held-out-'+row['event_id'];row['group_id']='held-out-'+row['group_id']
        if not relabel_only:
            # New kinematics, not an identity-only rewrite of prior inputs.
            row['objects']['jet'][0]['pt'] += 3
    if include_prior_case:
        prior=deepcopy(read_json(config['events']['path'])[0])
        prior['event_id']=prior['group_id']='relabelled-development-case'
        events.append(prior)
    ep=tmp_path/'held-out-events.json';atomic_json(ep,events)
    recipe=config['candidates'][0]['recipe'];program,_=candidate.construct(recipe,{c['id']:c for c in config['claims']})
    contract=read_json(config['contract']['path'])
    evaluated=analysis_ir.evaluate_program(program,contract,events)
    bundle=tmp_path/'held-out-witness';analysis_ir.write_bundle(evaluated,bundle)
    oracle=tmp_path/'held-out-oracle.json';atomic_json(oracle,{'schema_version':1,'kind':'source-case-oracle',
        'source_capsule_sha256':config['source_capsule']['sha256'],'events_sha256':sources.digest(ep),
        'records':[{'event_id':r['event_id'],'regions':r['regions'],'observables':{'n':r['nodes']['n']['value']}} for r in evaluated['decisions']],
        'author':'Explicit engineering control; no independent scientific witness claim','scope':'Fresh source/lineage admission controls'})
    config['events']=pin(ep);config['reference']['bundle']=str(bundle)
    config['reference']['manifest_sha256']=sources.digest(bundle/'manifest.json');config['reference']['source_oracle']=pin(oracle)
    path=tmp_path/'fresh-evaluation.json';atomic_json(path,config)
    return {**task,'input':str(path)}


def test_successful_parent_improves_without_failure_edge_and_retains_budget(tmp_path,monkeypatch):
    task,graph,lineage,rd=accepted_control(tmp_path,monkeypatch)
    original=read_json(task['input']);original_result=sources.digest(rd/'outputs/attempt-1/result.json')
    request=evolution.prepare_improvement_request(lineage,graph,tmp_path/'improve-source.json',model='fixture-control',reasoning_effort='high')
    assert request['prior_calls_retained']==1 and request['revision_type']=='improve_successful_incumbent'
    _external_control_reply(task,graph,request)
    evaluation=fresh_evaluation(task,tmp_path)
    challenger=tmp_path/'challenger.json'
    result=evolution.materialize_improvement_candidate(lineage,graph,challenger,candidate_id='new-challenger',evaluation_task=evaluation)
    inputs=candidate.inputs(result['task'],tmp_path)
    assert Path(lineage['path']) in inputs and rd/'outputs/attempt-1/result.json' in inputs
    assert read_json(challenger)['improvement_lineage']==lineage
    assert read_json(challenger)['candidates'][0]['parent'] is None
    output=tmp_path/'challenger-output';outcome=candidate.run(result['task'],tmp_path,output)
    assert outcome['candidate_disposition']=='verified_on_supplied_events'
    assert read_json(output/'candidate-source-admission.json')['bindings']['improvement_lineage_sha256']==lineage['sha256']
    assert outcome['prior_reviews_carried']==[]
    assert sources.digest(rd/'outputs/attempt-1/result.json')==original_result
    assert read_json(task['input'])==original
    assert agent_graph.status(graph)['usage']['calls']==2
    assert agent_graph.status(graph)['budget']['max_calls']==3


def test_same_population_cannot_count_as_fresh_improvement(tmp_path,monkeypatch):
    task,graph,lineage,rd=accepted_control(tmp_path,monkeypatch)
    request=evolution.prepare_improvement_request(lineage,graph,tmp_path/'improve-source.json',model='fixture-control',reasoning_effort='high')
    _external_control_reply(task,graph,request)
    with pytest.raises(ValueError,match='fresh held-out case population'):
        evolution.materialize_improvement_candidate(lineage,graph,tmp_path/'challenger.json',candidate_id='challenger',evaluation_task=task)


@pytest.mark.parametrize('relabel_only,include_prior_case',[(True,False),(False,True)])
def test_relabelled_or_mixed_development_cases_are_not_held_out(tmp_path,monkeypatch,relabel_only,include_prior_case):
    task,graph,lineage,rd=accepted_control(tmp_path,monkeypatch)
    request=evolution.prepare_improvement_request(lineage,graph,tmp_path/'improve-source.json',model='fixture-control',reasoning_effort='high')
    _external_control_reply(task,graph,request)
    evaluation=fresh_evaluation(task,tmp_path,relabel_only=relabel_only,include_prior_case=include_prior_case)
    with pytest.raises(ValueError,match='fresh held-out case population'):
        evolution.materialize_improvement_candidate(lineage,graph,tmp_path/'challenger.json',candidate_id='challenger',evaluation_task=evaluation)


def test_case_content_census_ignores_labels_order_and_numeric_spelling():
    original=[{'event_id':'a','group_id':'g','weights':{'nominal':1},
        'objects':{'electron':[],'muon':[],'jet':[{'pt':40,'eta':0,'phi':0,'mass':0,'charge':0,'idbits':0}]},
        'met':{'pt':0,'phi':0}}]
    clone=deepcopy(original)
    clone[0]['event_id']='new';clone[0]['group_id']='new-group'
    clone[0]['weights']['nominal']=1.0;clone[0]['objects']['jet'][0]['pt']=40.0
    clone[0]['met']={'pt':-0.0,'phi':0.0}
    assert candidate._case_content_digests(original)==candidate._case_content_digests(clone)
    clone[0]['objects']['jet'][0]['pt']=43.0
    assert not candidate._case_content_digests(original)&candidate._case_content_digests(clone)


def test_changed_incumbent_bytes_or_current_review_state_refuses(tmp_path,monkeypatch):
    task,graph,lineage,rd=accepted_control(tmp_path,monkeypatch)
    monkeypatch.setattr(physics_review,'status',lambda *a,**k:{'cycle_id':'fixture-cycle','state':'awaiting_review'})
    with pytest.raises(ValueError,match='state changed'):
        evolution.validate_lineage(lineage,tmp_path)
    monkeypatch.setattr(physics_review,'status',lambda *a,**k:{'cycle_id':'fixture-cycle','state':'accepted'})
    path=rd/'outputs/attempt-1/result.json';path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError,match='evidence changed'):
        evolution.validate_lineage(lineage,tmp_path)


@pytest.mark.parametrize('disposition',['not_observed','typed_compiler_refused','native_compiler_refused','event_mismatch'])
def test_unsuccessful_or_missing_challenger_preserves_successful_incumbent(tmp_path,monkeypatch,disposition):
    task,graph,lineage,rd=accepted_control(tmp_path,monkeypatch)
    result=evolution.retain_or_compare(lineage,challenger_disposition=disposition,challenger_score=-1,held_out_verified=True,full_case_verified=True)
    assert result['incumbent_retained'] and not result['scientific_acceptance']
    assert result['incumbent_result']['sha256']==sources.digest(rd/'outputs/attempt-1/result.json')


def test_development_pass_or_tie_does_not_replace_incumbent(tmp_path,monkeypatch):
    task,graph,lineage,rd=accepted_control(tmp_path,monkeypatch)
    assert evolution.retain_or_compare(lineage,challenger_disposition='verified_on_supplied_events',challenger_score=-1)['incumbent_retained']
    assert evolution.retain_or_compare(lineage,challenger_disposition='verified_on_supplied_events',challenger_score=0,full_case_verified=True)['incumbent_retained']
    favorable=evolution.retain_or_compare(lineage,challenger_disposition='verified_on_supplied_events',challenger_score=-1,held_out_verified=True,full_case_verified=True)
    assert favorable['next_action']=='request_fresh_full_case_review' and not favorable['scientific_acceptance']
    with pytest.raises(ValueError,match='declaration'):
        evolution.retain_or_compare(lineage,challenger_disposition='verified_on_supplied_events',full_case_verified='yes')


@pytest.mark.parametrize('held_out,full_case',[(False,False),(True,False),(False,True)])
def test_favorable_score_needs_both_evaluation_partitions(tmp_path,monkeypatch,held_out,full_case):
    task,graph,lineage,rd=accepted_control(tmp_path,monkeypatch)
    result=evolution.retain_or_compare(lineage,challenger_disposition='verified_on_supplied_events',
        challenger_score=-1,held_out_verified=held_out,full_case_verified=full_case)
    assert result['incumbent_retained'] and result['next_action']=='retain_incumbent_and_continue_declared_experiments'


def test_held_out_completion_declaration_requires_bool(tmp_path,monkeypatch):
    task,graph,lineage,rd=accepted_control(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='declarations'):
        evolution.retain_or_compare(lineage,challenger_disposition='verified_on_supplied_events',held_out_verified='yes')


def test_failed_parent_is_not_relabelled_as_successful_improvement(tmp_path,monkeypatch):
    task,graph,lineage,rd=accepted_control(tmp_path,monkeypatch)
    output=rd/'outputs/attempt-1'
    for name in ('result.json','construction-feedback.json'):
        record=read_json(output/name);record['candidate_disposition']='event_mismatch';atomic_json(output/name,record)
    with pytest.raises(ValueError,match='actual successful incumbent'):
        evolution.capture_incumbent(rd,tmp_path/'another-round.json',objective='Improve',metric='Count',direction='minimize',incumbent_score=1)
