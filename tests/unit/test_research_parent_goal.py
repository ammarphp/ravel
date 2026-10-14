"""Original-parent consumer controls; synthetic evidence, no scientific execution.

Graph/Host/context and report/task-completion calls are real ordinary source
operations. Component current-evidence checks in report fixtures are explicitly
stubbed; accepted-parent journals are synthetic ordinary physics-review fixtures.
These controls establish custody/propagation, never physics or human authenticity.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest

from ravel.workflow import research_cycle as cycle, scientific_context as sc
from ravel.workflow import agent_graph, agent_host, scientific_report, task_completion as tc, workflow_state
from ravel.workflow.state_io import read_json
from test_research_cycle import contract, propose, hypotheses, experiment, write, report_request
from test_task_completion import goal, PROMPT, child, request, resolved, review_run, review_final_artifacts
from test_scientific_judgment import observed_role_boundary


def bound(base, *, clipped=False, amendment=False):
    c, cp = goal(base, clipped=clipped)
    instruction = 'Only ATLAS is now required; retain the original CMS request as superseded.'
    if amendment:
        old = c['task_requirements']['obligations'][2]
        ap = write(base/'instruction.json', {'schema_version':1, 'kind':'task-scope-instruction',
            'authority':'direct-user-instruction', 'prompt_sha256':c['task_requirements']['prompt_sha256'],
            'instruction':instruction, 'changes':[{'obligation_id':'cms', 'before_sha256':tc.ce.digest(old),
                'disposition':'withdraw', 'statement':'CMS explicitly withdrawn', 'criteria':None}]})
        c['task_requirements']['amendments'] = [ap]
        cp = write(Path(cp['path']), c)
        parent = Path(cp['path']).parent.parent
        write(parent/'inputs/checkin1.json', {'schema_version':1, 'kind':'checkin1', 'sections':{
            'i':'synthetic request control', 'i-b':'exact census', 'ii':'scoped summary',
            'iii':{'plan':'none','waypoint':'source-only'}, 'iv':'no compute',
            'v':[{'id':'F1','text':'synthetic control, no authenticated human vote'}],
            'vi':['answer','ask','propose']}})
        write(parent/'inputs/cost_preflight.json', {'schema_version':1, 'generated_by':'cost_preflight.py',
            'mode':'none','walltime_h':[0,0]})
    c = contract(base)
    c['goal_binding'] = {'contract':cp, 'assignment_id':'summary-child'}
    root=base/'cycle'; cycle.create(root,c,base_dir=base, evaluation_harness=True)
    return root,c,cp,instruction


def design(base, root, c, identity='paired'):
    e = experiment(base,identity,grouped=True)
    p=Path(e['study']['path']); spec=read_json(p)
    spec['goal_binding']=deepcopy(c['goal_binding']); e['study']=write(p,spec)
    return cycle.design(root,e), e


def graph_spec(base):
    pins=[cycle._pin(base/'context-request.json'),cycle._pin(base/'math.py')]
    inputs=[{'id':name, **{k:p[k] for k in ('path','sha256')}} for name,p in zip(('request','api'),pins)]
    return {'schema_version':1,'graph_id':'actual-parent-context','budget':{'max_nodes':1,'max_calls':1,
        'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[{'id':'context','kind':'tool',
        'role':'proposer','depends_on':[],'inputs':inputs,'packet':None,'action':'scientific-context',
        'parameters':{'request_input':'request'},'max_attempts':1}]}


def complete_component(base,root,c,monkeypatch):
    """Literal complete supplied quantity plus explicit synthetic review labels."""
    propose(base,root); state,e=design(base,root,c)
    rd=base/'component-fixture'; result=write(rd/'outputs/attempt-1/result.json',
        {'quantities':{'covariance':[[1.0]],'values':{'nominal':[1.0]}}})
    observation={'outcome':'shared','prediction_comparison':{'independent':'differs','grouped':'matches','unknown':'unknown'},
        'synthetic_fixture_only':True}
    state['experiments'][0].update(rundir=str(rd),observation=observation,
        adjudication={'view':{'state':'accepted'},'synthetic_fixture_only':True,
            'scope':e['acceptance_scope'],'snapshot':write(rd/'synthetic-review.json',
                {'events':[],'synthetic_fixture_only':True})})
    state['context']=sc.apply_step(state['context'],{'id':'paired','outputs':{'measurement':{
        k:result[k] for k in ('path','sha256')}},'code_status':'success','actor_complete':True,
        'question':'Synthetic component delivery, no physical inference.','next_experiment':{
        k:'Retain scoped supplied values; whole HVT task stays distinct.' for k in
        ('hypothesis','change','measurement','if_supported','if_not_supported')}},base)
    cycle._commit(root,state,'synthetic_component_fixture')
    monkeypatch.setattr(cycle,'_current_evidence',lambda *a,**kw:{'explicit_synthetic_component_gate':True})
    recipe = report_request(base,root,rd)
    recipe['artifact_request']['basis'][0]['path'] = 'context-request.json'
    recipe['artifact_request']['tools']['study']['path'] = str(rd.relative_to(base)/'outputs/attempt-1/result.json')
    return recipe


def test_legacy_exploration_and_unknowns_need_no_parent_or_prior_proof(tmp_path):
    c=contract(tmp_path); root=tmp_path/'cycle'; state=cycle.create(root,c,base_dir=tmp_path, evaluation_harness=True)
    propose(tmp_path,root); cycle.design(root,experiment(tmp_path,'paired',grouped=True))
    assert 'parent_task' not in state
    assert cycle.select(root)['selected']=='paired'
    assert cycle.select(root)['parent_task'] is None and not cycle.status(root)['parent_task_accepted']
    assert sum(not h['source_basis'] for h in cycle._load(root)[1]['hypotheses'])==3


def test_clipped_child_denominator_never_replaces_literal_parent(tmp_path):
    root,c,cp,_=bound(tmp_path,clipped=True); propose(tmp_path,root); design(tmp_path,root,c)
    view=cycle.select(root); parent=view['parent_task']
    assert parent['original_request']==PROMPT
    assert parent['original_obligations'][-1]['criteria']['lower_gev'] is None
    assert parent['assignment']['coverage'][-1]['criteria']['lower_gev']==150
    assert {r['id'] for r in parent['original_obligations']}=={'original-request','atlas','cms','domain'}
    assert parent['contract']==cp and not view['parent_task_accepted']
    assert cycle._load(root)[1]['hypotheses'][0]['premise_bindings'][cycle.PARENT_PREMISE]==tc.ce.digest(parent)


def test_real_graph_host_inherits_parent_and_spends_one_original_reservation(tmp_path,monkeypatch):
    root,c,cp,_=bound(tmp_path,clipped=True); spec=graph_spec(tmp_path); before=deepcopy(spec)
    contexts=[]; original=agent_host.AgentHost._context
    def capture(self,*args,**kwargs):
        result=original(self,*args,**kwargs); contexts.append(deepcopy(result)); return result
    monkeypatch.setattr(agent_host.AgentHost,'_context',capture)
    gr=tmp_path/'graph'; result=cycle.execute_graph(root,gr,spec,agent_host.AgentHost())
    assert result['complete'] and result['usage']['calls']==1 and spec==before
    # Tool dispatch does not call model context. Read the real retained request
    # through the same public Host context method without a model invocation.
    saved=read_json(cycle._graph_result(gr,'context')['receipt']['path'])
    agent_host.AgentHost()._context(spec['nodes'][0],saved['request'],{})
    assert contexts[-1]['parent_task']['original_request']==PROMPT
    assert contexts[-1]['parent_task']['contract']==cp
    assert contexts[-1]['parent_task']['effective_obligations'][-1]['criteria']['lower_gev'] is None
    assert agent_graph._load(gr)[0]['goal_binding']==c['goal_binding']
    again=cycle.execute_graph(root,gr,spec,agent_host.AgentHost())
    assert again['usage']==result['usage'] and cycle._usage(cycle._load(root)[1])['calls']==1


@pytest.mark.parametrize('alteration',['assignment','contract'])
def test_foreign_graph_parent_refuses_before_dispatch_or_resource_charge(tmp_path,alteration):
    root,c,cp,_=bound(tmp_path); spec=graph_spec(tmp_path)
    spec['goal_binding']=deepcopy(c['goal_binding'])
    if alteration=='assignment': spec['goal_binding']['assignment_id']='foreign'
    else: spec['goal_binding']['contract']['sha256']='0'*64
    before=cycle._load(root)[1]['sha256']
    with pytest.raises(ValueError,match='replace its original'):cycle.execute_graph(root,tmp_path/'graph',spec,agent_host.AgentHost())
    assert cycle._load(root)[1]['sha256']==before and not (tmp_path/'graph').exists()


@pytest.mark.parametrize('alteration',['missing','assignment','contract'])
def test_new_study_must_preserve_parent_without_extra_approval(tmp_path,alteration):
    root,c,cp,_=bound(tmp_path); propose(tmp_path,root); e=experiment(tmp_path,'paired',grouped=True)
    if alteration!='missing':
        spec=read_json(e['study']['path']); spec['goal_binding']=deepcopy(c['goal_binding'])
        if alteration=='assignment':spec['goal_binding']['assignment_id']='foreign'
        else:spec['goal_binding']['contract']['sha256']='0'*64
        e['study']=write(Path(e['study']['path']),spec)
    before=cycle._load(root)[1]['sha256']
    with pytest.raises(ValueError,match='preserve the research parent|existing parent assignment|task artifact changed'):cycle.design(root,e)
    assert cycle._load(root)[1]['sha256']==before


@pytest.mark.parametrize('operation',['select','status','feedback','propose'])
def test_current_parent_source_drift_refuses_without_rebinding(tmp_path,operation):
    root,c,cp,_=bound(tmp_path); propose(tmp_path,root); design(tmp_path,root,c)
    Path(cp['path']).write_text('{}\n'); head=read_json(root/'head.json')
    with pytest.raises(ValueError):
        if operation=='select':cycle.select(root)
        elif operation=='status':cycle.status(root)
        elif operation=='feedback':cycle.feedback_packet(root,'paired')
        else:cycle.propose(root,hypotheses(),origin={})
    assert read_json(root/'head.json')==head


def test_agent_note_is_proposed_only_and_cannot_refresh_away_original_cms(tmp_path):
    root,c,cp,_=bound(tmp_path,amendment=True); parent=cycle.status(root)['parent_task']
    assert not parent['scope_changes'][0]['effective_authorization']
    assert not parent['effective_obligations'][2].get('withdrawn',False)
    with pytest.raises(ValueError,match='already current'):cycle.refresh_parent_goal(root,reason='An agent may not authorize its narrowing.')


def test_actual_planned_authorization_and_revocation_reopen_existing_journal(tmp_path,monkeypatch):
    root,c,cp,instruction=bound(tmp_path,amendment=True)
    complete_component(tmp_path,root,c,monkeypatch)
    previous=cycle._load(root)[1]; old_history=cycle._pin(root/'history/0000.json')
    parent=Path(cp['path']).parent.parent
    assert workflow_state.cmd_approve(SimpleNamespace(rundir=str(parent),plan='none',quote=instruction))==0
    with pytest.raises(ValueError,match='goal-refresh'):cycle.select(root)
    current=cycle.refresh_parent_goal(root,reason='Record actual source-bound planned instruction approval.')
    assert current['parent_task']['contract']==cp and current['parent_task']['original_request']==PROMPT
    assert current['parent_task']['effective_obligations'][2]['withdrawn']
    assert not current['context']['quantity_completion'] and current['context']['steps']==[]
    assert current['experiments'][0]['observation']==previous['experiments'][0]['observation']
    assert current['experiments'][0]['adjudication']==previous['experiments'][0]['adjudication']
    assert not cycle._fresh(current,current['hypotheses'][0]['premise_bindings'])
    assert cycle.select(root)['selected'] is None and not cycle.status(root)['connected_task_complete']
    assert current['events'][-1]['old_votes_carried']==[] and cycle._pin(root/'history/0000.json')==old_history
    # Fresh speculative descendants explicitly bind the newly observed scope.
    row=deepcopy(hypotheses()[1]); row['id']='new-grouped'; row['parents']=['grouped']
    pin=write(tmp_path/'fresh-hypothesis.json',[row]); new=cycle.propose(root,[row],origin={
        'kind':'supplied_source','pin':pin,'description':'Explicit synthetic requalification, no model claim.'})
    assert cycle._fresh(new,new['hypotheses'][-1]['premise_bindings'])
    (parent/'inputs/checkin1_approval.json').unlink()
    with pytest.raises(ValueError,match='goal-refresh'):cycle.status(root)
    revoked=cycle.refresh_parent_goal(root,reason='Original instruction approval removed; original CMS obligation is live again.')
    assert not revoked['parent_task']['effective_obligations'][2].get('withdrawn',False)
    assert not cycle._fresh(revoked,revoked['hypotheses'][-1]['premise_bindings'])
    assert not revoked['parent_task']['parent_task_complete']


def test_feedback_retains_parent_and_scoped_negative_without_closure(tmp_path,monkeypatch):
    root,c,cp,_=bound(tmp_path,clipped=True); complete_component(tmp_path,root,c,monkeypatch)
    feedback=read_json(cycle.feedback_packet(root,'paired')['path'])
    assert feedback['parent_task']['original_request']==PROMPT and not feedback['parent_task_accepted']
    assert feedback['observation']['prediction_comparison']['unknown']=='unknown'
    assert feedback['adjudication']['synthetic_fixture_only']


@pytest.mark.parametrize('mutation',['drop','foreign'])
def test_new_campaign_cannot_silently_replace_original_assignment(tmp_path,monkeypatch,mutation):
    root,c,cp,_=bound(tmp_path); state=cycle._load(root)[1]
    state['timing'].update(started_epoch=1000.0,deadline_epoch=1060.0)
    cycle._commit(root,state,'synthetic_expired_campaign'); monkeypatch.setattr(cycle.time,'time',lambda:1100.0)
    new=deepcopy(c); new['id']='continuation'; new['budget']['wall_seconds']=120
    if mutation=='drop':new.pop('goal_binding')
    else:new['goal_binding']['assignment_id']='foreign'
    with pytest.raises(ValueError,match='drop or replace'):cycle.continue_campaign(root,tmp_path/'next',new,reason='Scope narrowing must not become a continuation.')
    assert not (tmp_path/'next').exists()


def test_complete_component_progress_report_keeps_parent_open(tmp_path,monkeypatch):
    root,c,cp,_=bound(tmp_path,clipped=True); recipe=complete_component(tmp_path,root,c,monkeypatch)
    assert cycle.status(root)['connected_task_complete']
    recipe.update(task_completion=request(tmp_path,cp,[child(tmp_path,cp)]),delivery='progress')
    result=cycle.synthesize(root,recipe,base_dir=tmp_path)
    assert not result['parent_task_accepted'] and PROMPT in result['report']['report_text']
    assert result['report']['task_completion']['unmet_obligation_ids']==['original-request','atlas','cms','domain']
    assert result['report']['plot_data']==scientific_report.compose(recipe,base_dir=tmp_path)['plot_data']
    recipe['delivery']='final'
    with pytest.raises(ValueError,match='parent task remains open'):cycle.synthesize(root,recipe,base_dir=tmp_path)


def test_exact_parent_acceptance_is_propagated_only_from_actual_bound_helper(tmp_path,monkeypatch,observed_role_boundary):
    root,c,cp,_=bound(tmp_path); recipe=complete_component(tmp_path,root,c,monkeypatch)
    out=resolved(tmp_path,cp,monkeypatch); rp=write(tmp_path/'base-recipe.json',recipe)
    completion=request(tmp_path,cp,[out],report=rp); ready=tc.evaluate(completion,base_dir=tmp_path)
    document=read_json(completion['path']); parent=tmp_path/'final-review'
    document['parent_review']={'rundir':str(parent),'claim_scope':'original_task_completion'}
    completion=write(Path(completion['path']),document)
    review_run(parent,[completion['path'],*[p['path'] for p in ready['input_pins'] if p['path']!=completion['path']]],
        monkeypatch,scope='original_task_completion')
    # The accepted parent review alone does not release a whole-task final delivery.
    # Its CHECK-IN 3 final-artifact review is registered through the ordinary graph.
    with pytest.raises(ValueError,match='CHECK-IN 3 final-artifact review'):
        cycle.synthesize(root,{**recipe,'task_completion':completion,'delivery':'final'},base_dir=tmp_path)
    reviewed=review_final_artifacts(parent,completion,recipe,tmp_path,monkeypatch)
    accepted=tc.require_final(completion,base_dir=tmp_path)['final_results_review']
    recipe.update(task_completion=completion,delivery='final')
    assert reviewed=={k:v for k,v in recipe.items()}
    recipe['final_results_review']={'rundir':accepted['rundir'],'manifest':accepted['manifest']}
    result=cycle.synthesize(root,recipe,base_dir=tmp_path)
    assert result['parent_task_accepted'] and result['report']['task_completion']['parent_task_accepted']
    assert result['parent_task']['contract']==cp and not result['physics_validated']
    Path(out['coverage'][0]['evidence'][0]['path']).write_text('{}\n')
    with pytest.raises(ValueError):cycle.synthesize(root,recipe,base_dir=tmp_path)


def test_different_parent_completion_refuses_before_writer(tmp_path,monkeypatch):
    root,c,cp,_=bound(tmp_path); recipe=complete_component(tmp_path,root,c,monkeypatch)
    other=tmp_path/'other'; other.mkdir(); _,foreign=goal(other)
    recipe.update(task_completion=request(tmp_path,foreign),delivery='progress')
    monkeypatch.setattr(scientific_report,'compose',lambda *a,**kw:pytest.fail('foreign parent reached writer'))
    with pytest.raises(ValueError,match='exact original parent'):cycle.synthesize(root,recipe,base_dir=tmp_path)


def test_unbound_cycle_does_not_borrow_foreign_parent_completion(tmp_path,monkeypatch):
    c=contract(tmp_path); root=tmp_path/'cycle'; cycle.create(root,c,base_dir=tmp_path, evaluation_harness=True)
    # Reuse a bound fixture after removing only its goal-binding requirement.
    propose(tmp_path,root); e=experiment(tmp_path,'paired',grouped=True); cycle.design(root,e)
    _,state=cycle._load(root); rd=tmp_path/'fixture'
    result=write(rd/'outputs/attempt-1/result.json',{'quantities':{'covariance':[[1.0]]}})
    state['experiments'][0].update(rundir=str(rd),observation={'outcome':'shared'},adjudication={'view':{'state':'accepted'},'scope':e['acceptance_scope'],
        'snapshot':write(rd/'synthetic-review.json',{'events':[],'synthetic_fixture_only':True})})
    state['context']=sc.apply_step(state['context'],{'id':'paired','outputs':{'measurement':{
        k:result[k] for k in ('path','sha256')}},'code_status':'success','actor_complete':True,
        'question':'Synthetic quantity','next_experiment':{k:'Retain supplied result.' for k in
        ('hypothesis','change','measurement','if_supported','if_not_supported')}},tmp_path)
    cycle._commit(root,state,'synthetic_fixture'); monkeypatch.setattr(cycle,'_current_evidence',lambda *a,**kw:{})
    recipe=report_request(tmp_path,root,rd); _,cp=goal(tmp_path)
    recipe.update(task_completion=request(tmp_path,cp),delivery='progress')
    with pytest.raises(ValueError,match='original bound research parent'):cycle.synthesize(root,recipe,base_dir=tmp_path)


@pytest.mark.parametrize('operation',['select','status','synthesize','propose'])
def test_ending_parent_drift_cannot_return_stale_derived_decision(tmp_path,monkeypatch,operation):
    root,c,cp,_=bound(tmp_path)
    if operation=='synthesize':
        recipe=complete_component(tmp_path,root,c,monkeypatch); original=scientific_report.compose
        def drift(*args,**kwargs):
            result=original(*args,**kwargs); Path(cp['path']).write_text('{}\n'); return result
        monkeypatch.setattr(scientific_report,'compose',drift)
        action=lambda:cycle.synthesize(root,recipe,base_dir=tmp_path)
    elif operation=='propose':
        original=cycle._append_hypotheses
        def drift(*args,**kwargs):
            result=original(*args,**kwargs); Path(cp['path']).write_text('{}\n'); return result
        monkeypatch.setattr(cycle,'_append_hypotheses',drift); action=lambda:propose(tmp_path,root)
    elif operation=='select':
        propose(tmp_path,root); design(tmp_path,root,c); original=cycle._read
        def drift(pin,*args,**kwargs):
            result=original(pin,*args,**kwargs)
            if Path(pin['path']).name=='study.json':Path(cp['path']).write_text('{}\n')
            return result
        monkeypatch.setattr(cycle,'_read',drift); action=lambda:cycle.select(root)
    else:
        complete_component(tmp_path,root,c,monkeypatch)
        def drift(*args,**kwargs):Path(cp['path']).write_text('{}\n'); return {}
        monkeypatch.setattr(cycle,'_current_evidence',drift); action=lambda:cycle.status(root)
    head=read_json(root/'head.json')
    with pytest.raises(ValueError):action()
    assert read_json(root/'head.json')==head


def test_component_only_report_automatically_exposes_original_unassessed_obligations(tmp_path,monkeypatch):
    root,c,cp,_=bound(tmp_path,clipped=True); recipe=complete_component(tmp_path,root,c,monkeypatch)
    original=deepcopy(recipe)
    result=cycle.synthesize(root,recipe,base_dir=tmp_path)
    assert recipe==original and not result['parent_task_accepted']
    assert PROMPT in result['report']['report_text'] and '| cms |' in result['report']['report_text']
    assert result['report']['task_completion']['unmet_obligation_ids']==['original-request','atlas','cms','domain']
    assert not result['report']['task_completion']['ready_for_parent_review']
    assert cycle.synthesize(root,recipe,base_dir=tmp_path)['report']==result['report']
    retained=Path(result['report']['task_completion']['request']['path'])
    retained.write_text('{}\n')
    with pytest.raises(ValueError,match='progress projection differs'):cycle.synthesize(root,recipe,base_dir=tmp_path)
