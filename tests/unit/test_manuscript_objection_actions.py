"""Authored UNRUN. Inert model/review seams; no scientific or provider evidence.

The real manuscript preparation/materialization and protocol packet services are
exercised when root admits this software batch. No test is a physics verdict.
"""
from copy import deepcopy
from pathlib import Path
import subprocess
import pytest
from ravel.workflow import manuscript_workflow as mw, manuscript_production as mp
from ravel.workflow import research_protocol as rp, research_coordinator_decisions as decisions
from ravel.workflow import scientific_judgment, state_io
from test_staged_manuscript_authoring import case
from test_manuscript_production import put


def quantitative_context(root,name,state):
    """The actual report reader takes a relative pin3 in its document directory."""
    pin=put(root,name,state)
    return {**pin,'path':Path(pin['path']).name}


@pytest.fixture(autouse=True)
def no_native_or_provider_process(monkeypatch):
    from ravel.workflow import execution
    monkeypatch.setattr(execution,'runtime_context',lambda:{'explicit_inert_source_control':True,
        'environment_sha256':execution.digest(execution.runtime_environment())})
    def refuse(*a,**k):raise AssertionError('No native, provider, model or metadata process admitted')
    monkeypatch.setattr(subprocess,'Popen',refuse)


def ready(tmp_path, monkeypatch):
    from ravel.workflow import scientific_report as sr
    from test_research_cycle import contract
    actual_load=mw.cycle._load;actual_context=sr._context
    _,_,production,state,final=case(tmp_path,monkeypatch)
    monkeypatch.setattr(mw.cycle,'_load',actual_load);monkeypatch.setattr(sr,'_context',actual_context)
    declaration=contract(tmp_path)
    declaration['budget']={'calls':20,'output_tokens':100000,'wall_seconds':2000,'native_attempts':0}
    campaign=tmp_path/'campaign';registry={}
    state=mw.cycle.create(campaign,declaration,base_dir=tmp_path)
    production['quantitative_report']=put(tmp_path,'quantities-current.json',{
        'context':quantitative_context(tmp_path,'context-current.json',state['context']),'toy_request':True})
    production['runtime'].update(action='model',model='fixture-model',model_build='observed-snapshot')
    initial=mp.prepare_writer(production,tmp_path/'first-writer',base_dir=tmp_path,campaign=campaign)
    complete({'binding':initial},state,final,monkeypatch,registry)
    package=mp.collect(initial,tmp_path/'first-package')
    ir=mw._read(package['package']['integrity_request'],tmp_path)
    feedback_case=put(tmp_path,'review-case.json',{'root':'manuscript-integrity','nodes':[{'id':'manuscript-integrity',
        'anchors':[{'format':'json','location':'','value':ir}]}]})
    feedback_case={k:feedback_case[k] for k in ('path','sha256')}
    def verified(role):
        return {'receipt':{'role':role},'contract':{'role':role,'actor_id':role,'case_pin':feedback_case,'rundir':str(tmp_path)},
            'value':{'kind':'scientific_review','verdict':'send_back','audit':{
                'nodes':[{'id':'method.square','decision':'unresolved','assumptions':[]}],'edges':[]}},'supporting_artifacts':[]}
    monkeypatch.setattr(scientific_judgment,'verify_binding',verified)
    monkeypatch.setattr(mw.integrity,'assess',lambda *a,**k:{'complete_actual_independent_roles':True,'scoped_integrity_review_complete':True})
    monkeypatch.setattr(mw.integrity,'assessment_pins',lambda *a,**k:[])
    budget={'calls':10,'output_tokens':50000,'wall_seconds':1000,'native_attempts':0}
    revision=mw.prepare_revision(package['package_pin'],['critic','verifier','synthesizer'],tmp_path/'revision',base_dir=tmp_path,campaign=campaign,budget=budget)['revision']
    state.clear();state.update(mw.cycle._load(campaign)[1])
    rows=[{'objection_index':i,'kind':'editorial','response':'Clarify supplied method wording without changing the operation or its quantities.',
        'protocol_claim_ids':[],'protocol_stage_ids':[],'required_experiment_ids':[]} for i in range(3)]
    return revision,rows,production,state,campaign,package,final,registry


def complete(prepared,state,value,monkeypatch,registry):
    """Real journal/Graph accounting with disclosed inert HTTP response bytes."""
    from test_manuscript_historical_origin import complete_actual
    observed=complete_actual(prepared['binding'],value,monkeypatch)
    state.clear();state.update(observed)
    return observed


def spend_inert(campaign,calls=1):
    """Explicit synthetic charge in the real ordinary journal; no fake counter."""
    _,state=mw.cycle._load(campaign)
    identity='explicit-inert-charge-'+str(state['revision'])
    mw.cycle._charge(state,identity,{'calls':calls,'output_tokens':0,'wall_seconds':0,'native_attempts':0},{'explicit_synthetic_charge':True})
    return mw.cycle._commit(campaign,state,'explicit_inert_resource_spent',operation=identity)


def plan(tmp_path,monkeypatch):
    fixture=ready(tmp_path,monkeypatch);revision,rows,_,_,campaign,*_=fixture
    pin=mw.prepare_actions(revision,rows,tmp_path/'actions',base_dir=tmp_path,campaign=campaign)['action_plan']
    return pin,fixture


def successor_request(tmp_path,production,package):
    new=deepcopy(production);new['revision']={'previous_package':package['package_pin'],'feedback_binding':'critic'}
    return put(tmp_path,'replacement.json',new)


def test_complete_editorial_actions_prepare_no_numerical_or_meta_job(tmp_path,monkeypatch):
    action,fixture=plan(tmp_path,monkeypatch);_,rows,_,state,campaign,*_=fixture
    read=mw.verify_actions(action,base_dir=tmp_path,campaign=campaign)
    assert len(read['plan']['actions'])==3 and all(r['resolution']=='unresolved' for r in read['plan']['actions'])
    assert all(r['affected_manuscript']['method_ids']==['square'] for r in read['plan']['actions'])
    assert read['plan']['remaining_budget']['calls']==10 and read['plan']['usage_at_prepare']==mw.cycle._usage(state)
    monkeypatch.setattr(rp,'prepare_meta_review',lambda *a,**k:pytest.fail('Pure editorial response launched a meta job'))
    with pytest.raises(ValueError,match='no scientific meta'):
        mw.prepare_action_meta(action,tmp_path/'not-issued',base_dir=tmp_path,campaign=campaign)
    assert not (tmp_path/'not-issued').exists()


@pytest.mark.parametrize('fault',['missing','duplicate','order','boolean','foreign-stage','unknown-kind','false-closure'])
def test_complete_objection_map_cannot_drop_rebind_or_self_close(tmp_path,monkeypatch,fault):
    revision,rows,_,_,campaign,*_=ready(tmp_path,monkeypatch)
    if fault=='missing':rows.pop()
    elif fault=='duplicate':rows[1]['objection_index']=0
    elif fault=='order':rows.reverse()
    elif fault=='boolean':rows[0]['objection_index']=False
    elif fault=='foreign-stage':rows[0]['protocol_stage_ids']=['unrelated']
    elif fault=='unknown-kind':rows[0]['kind']='auto-accept'
    else:rows[0]['resolution']='resolved'
    with pytest.raises(ValueError):mw.prepare_actions(revision,rows,tmp_path/'refused',base_dir=tmp_path,campaign=campaign)
    assert not (tmp_path/'refused').exists()


@pytest.mark.parametrize('fault',['source','campaign','objection','allocation'])
def test_action_readback_keeps_actual_source_campaign_and_original_criticism(tmp_path,monkeypatch,fault):
    action,fixture=plan(tmp_path,monkeypatch);_,_,_,state,campaign,*_=fixture
    if fault=='source':(tmp_path/'score.py').write_text('different source')
    else:
        data=mw._read(action,tmp_path)
        if fault=='campaign':data['campaign']=str(tmp_path/'foreign')
        elif fault=='objection':data['actions'][0]['objection']['current_audit_item']['decision']='supported'
        else:data['remaining_budget']['calls']=11
        action=put(tmp_path,'changed-plan.json',data)
    with pytest.raises(ValueError):mw.verify_actions(action,base_dir=tmp_path,campaign=campaign)


def core_rows():
    protocol={'claims':[{'id':'whole','stage_ids':['baseline','full','ablation'],'comparison_ids':[]}],
        'stages':[{'id':i,'candidate':'base' if i!='ablation' else 'remove','purpose':i,
                   'cells':[{'experiment_id':i}], 'ablation':None if i!='ablation' else {'parent_candidate':'base'}} for i in ['baseline','full','ablation']],
        'comparisons':[]}
    # Literal purpose for the central stage is full (not a screen surrogate).
    protocol['stages'][1]['purpose']='full'
    revision={'objections':[{'role':'critic','current_audit_item':{'id':'method.square'}}]}
    loaded={'methods':{'square':{'citation_ids':[]}},'citations':{},'figures':{},'evidence':{},'formatting':{'synthetic':True}}
    ir={'claims':[{'id':'claim','method_ids':['square'],'citation_ids':[],'evidence':[]}]}
    row={'objection_index':0,'kind':'core-method','response':'Recompute the complete original method contrast.',
         'protocol_claim_ids':['whole'],'protocol_stage_ids':['baseline','full','ablation'],'required_experiment_ids':[]}
    return protocol,revision,loaded,ir,row


def test_core_change_retains_complete_baseline_full_and_ablation(tmp_path,monkeypatch):
    protocol,revision,loaded,ir,row=core_rows()
    monkeypatch.setattr(mp.manuscript_format,'section_layout',lambda _: [{'id':'methods'},{'id':'results'}])
    result=mw._action_rows([row],revision,ir,loaded,protocol)
    assert result[0]['protocol_stage_ids']==['baseline','full','ablation']
    assert result[0]['affected_manuscript']['claim_ids']==['claim']
    assert result[0]['affected_manuscript']['section_ids']==['methods','results']


def test_core_change_cannot_omit_connected_distinct_incumbent_baseline(monkeypatch):
    protocol,revision,loaded,ir,row=core_rows()
    protocol['stages'].append({'id':'incumbent','candidate':'original','purpose':'baseline','cells':[], 'ablation':None})
    protocol['comparisons'].append({'id':'contrast','left_stage':'full','right_stage':'incumbent','experiment_id':'contrast-study'})
    protocol['claims'][0]['comparison_ids']=['contrast']
    monkeypatch.setattr(mp.manuscript_format,'section_layout',lambda _: [{'id':'methods'}])
    with pytest.raises(ValueError,match='full baseline/ablation'):
        mw._action_rows([row],revision,ir,loaded,protocol)
    row['protocol_stage_ids'].append('incumbent')
    assert mw._action_rows([row],revision,ir,loaded,protocol)[0]['protocol_stage_ids']==row['protocol_stage_ids']


@pytest.mark.parametrize('missing',['baseline','full','ablation'])
def test_core_change_cannot_select_favorable_subset(monkeypatch,missing):
    protocol,revision,loaded,ir,row=core_rows()
    monkeypatch.setattr(mp.manuscript_format,'section_layout',lambda _: [{'id':'methods'}])
    row['protocol_stage_ids'].remove(missing)
    with pytest.raises(ValueError,match='full baseline/ablation'):
        mw._action_rows([row],revision,ir,loaded,protocol)


@pytest.mark.parametrize('kind',['editorial','citation','empirical'])
def test_action_kind_cannot_hide_scientific_work_or_missing_observation(monkeypatch,kind):
    protocol,revision,loaded,ir,row=core_rows();row['kind']=kind
    with pytest.raises(ValueError):mw._action_rows([row],revision,ir,loaded,protocol)


def test_real_protocol_packet_presents_linked_objection_content(tmp_path,monkeypatch):
    artifact,_,_,root,*_=actual_material_plan(tmp_path,monkeypatch,calls=2)
    supplement,_=mw.action_context(artifact,base_dir=tmp_path,campaign=root)
    prepared=rp.prepare_meta_review(root,tmp_path/'meta',role='critic',model='inert',reasoning_effort='high',
        max_output_tokens=128,max_wall_seconds=10,manuscript_action_plan=artifact)
    subject=rp._json(prepared['context'],tmp_path)
    assert subject['manuscript_actions']==supplement and artifact in subject['source_inputs']
    manifest=state_io.read_json(Path(prepared['graph_root']).parent/'context/manifest.json')
    presented=next(r for r in manifest['artifacts'] if r.get('source_path')==artifact['path'])
    assert (Path(prepared['graph_root']).parent/'context'/presented['path']).read_bytes()==Path(artifact['path']).read_bytes()
    assert not prepared['execution_authorized']


def test_real_charged_protocol_action_requires_fresh_observation_before_resolution(tmp_path,monkeypatch):
    import test_research_protocol as inherited
    pin,_,_,root,*_=actual_material_plan(tmp_path,monkeypatch,calls=4)
    def current():return mw.verify_actions(pin,base_dir=tmp_path,campaign=root)
    original=rp.prepare_meta_review;attempts=[]
    def linked(root_,output,**kw):
        attempts.append(str(output));output=Path(str(output)+'-attempt'+str(len(attempts)))
        return original(root_,output,manuscript_action_plan=pin,**kw)
    monkeypatch.setattr(rp,'prepare_meta_review',linked)
    before=mw.cycle._usage(mw.cycle._load(root)[1])['calls']
    state=inherited.meta(tmp_path,root,monkeypatch,'additional_evidence',required=['objection-probe'])
    event=state['events'][-1];revision=event['revision']
    assert event['manuscript_action_plan']==pin and event['old_votes_carried'] is False
    assert mw.cycle._usage(state)['calls']==before+1 and not rp.status(root)['complete_scientific_evidence']
    with pytest.raises(ValueError):mw._material_actions_complete(current())
    with pytest.raises(ValueError):
        inherited.meta(tmp_path,root,monkeypatch,'resolve_objections',required=['objection-probe'],resolves=[revision])
    assert rp._active_holds(mw.cycle._load(root)[1],'complete-method')
    observe_inert_complete_study(tmp_path,root,'objection-probe',monkeypatch)
    state=inherited.meta(tmp_path,root,monkeypatch,'resolve_objections',required=['objection-probe'],resolves=[revision])
    assert state['events'][-1]['manuscript_action_plan']==pin
    assert len(mw._material_actions_complete(current()))==2 and rp.status(root)['complete_scientific_evidence']
    assert mw.cycle._usage(state)['calls']==before+3  # failed resolution remains charged


def test_large_indexed_meta_context_cannot_silently_omit_manuscript_actions(tmp_path):
    with pytest.raises(ValueError,match='complete inline'):
        rp.context(tmp_path,presentation='indexed',manuscript_action_plan={'path':'unread','sha256':'a'*64,'size':1})


@pytest.mark.parametrize('fault',['report-only','missing-claim','missing-stage','missing-test'])
def test_meta_result_must_retain_every_material_obligation(monkeypatch,fault):
    pin={'path':'synthetic','sha256':'a'*64,'size':1}
    current={'pin':pin,'plan':{'actions':[{'kind':'empirical','protocol_claim_ids':['claim'],'protocol_stage_ids':['full'],
        'required_experiment_ids':['new-observation']}]},'state':{'events':[]}}
    monkeypatch.setattr(mw,'verify_actions',lambda *a,**k:deepcopy(current))
    value={'action':'additional_evidence','affected_claim_ids':['claim'],'affected_stage_ids':['full'],
        'required_experiment_ids':['new-observation']}
    assert mw.validate_action_meta(pin,value,base_dir='.',campaign='.')==pin
    if fault=='report-only':value['action']='report_only'
    elif fault=='missing-claim':value['affected_claim_ids']=[]
    elif fault=='missing-stage':value['affected_stage_ids']=[]
    else:value['required_experiment_ids']=[]
    with pytest.raises(ValueError):mw.validate_action_meta(pin,value,base_dir='.',campaign='.')


def test_successor_real_writer_reads_whole_response_but_does_not_close_it(tmp_path,monkeypatch):
    action,fixture=plan(tmp_path,monkeypatch);_,_,production,state,campaign,package,final,registry=fixture
    request=successor_request(tmp_path,production,package)
    result=mw.prepare_successor(action,request,tmp_path/'next',base_dir=tmp_path,campaign=campaign)
    record=mw._read(result['successor'],tmp_path)
    context=mw._read(result['writer']['presentation'],tmp_path) if 'presentation' in result['writer'] else None
    instructions=Path(result['writer']['presentation']['path']).read_text()
    assert 'manuscript-action-response' in instructions and 'objection_index' in instructions
    assert not result['objections_closed'] and not record['objections_closed']
    assert result['writer']['spec']['nodes'][0]['role']=='improver'
    complete({'binding':result['writer']},state,final,monkeypatch,registry)
    replacement=mp.collect(result['writer'],tmp_path/'new-package')
    resolved=mw.resolve_actions(result['successor'],replacement['package_pin'],['critic','verifier','synthesizer'],
        tmp_path/'resolved',base_dir=tmp_path,campaign=campaign)
    assert resolved['resolved_objection_count']==3 and not resolved['scientific_acceptance']
    record=mw._read(resolved['resolution'],tmp_path)
    assert record['resolved_objection_indices']==[0,1,2] and not record['parent_task_accepted']


@pytest.mark.parametrize('fault',['method','quantity','runtime','omit-method','budget'])
def test_editorial_successor_cannot_change_science_or_reset_allocation(tmp_path,monkeypatch,fault):
    action,fixture=plan(tmp_path,monkeypatch);_,_,production,state,campaign,package,*_=fixture
    request=deepcopy(production);request['revision']={'previous_package':package['package_pin'],'feedback_binding':'critic'}
    if fault=='method':request['methods'][0]['description']='Different estimator.'
    elif fault=='quantity':request['quantitative_report']=put(tmp_path,'foreign-quantity.json',{'context':{'path':'synthetic-context'},'changed':True})
    elif fault=='runtime':request['runtime']['max_output_tokens']=4097
    elif fault=='omit-method':request['methods']=[]
    else:
        _,charged=mw.cycle._load(campaign)
        mw.cycle._charge(charged,'explicit-inert-exhaustion',{'calls':10,'output_tokens':50000,'wall_seconds':1000,'native_attempts':0},{'synthetic':True})
        mw.cycle._commit(campaign,charged,'explicit_synthetic_revision_allowance_spent')
    with pytest.raises(ValueError):mw.prepare_successor(action,put(tmp_path,'bad-request.json',request),tmp_path/'refused',base_dir=tmp_path,campaign=campaign)
    assert not (tmp_path/'refused').exists()


def test_unresolved_material_action_and_old_results_cannot_reach_writer(tmp_path,monkeypatch):
    action,fixture=plan(tmp_path,monkeypatch);_,_,_,_,campaign,*_=fixture
    current=mw.verify_actions(action,base_dir=tmp_path,campaign=campaign)
    current['plan']['actions'][0].update(kind='empirical',protocol_claim_ids=['whole'],required_experiment_ids=['fresh'])
    monkeypatch.setattr(rp,'status_state',lambda _: {'replacement_obligations':{'stages':{}}})
    with pytest.raises(ValueError,match='fresh scientific replacement'):
        mw._material_actions_complete(current)


def test_revision_allowance_is_cumulative_and_never_widens_campaign():
    current={'state':{'resource_ledger':[{'ceiling':{'calls':2,'output_tokens':20,'wall_seconds':10,'native_attempts':0}}],
                     'contract':{'budget':{'calls':100,'output_tokens':1000,'wall_seconds':1000,'native_attempts':10}}},
             'plan':{'remaining_budget':{'calls':2,'output_tokens':100,'wall_seconds':100,'native_attempts':0},
                     'usage_at_prepare':{'calls':0,'output_tokens':0,'wall_seconds':0,'native_attempts':0}}}
    with pytest.raises(ValueError,match='no per-action reset'):
        mw._action_allowance(current,{'calls':1,'output_tokens':1,'wall_seconds':1,'native_attempts':0})


def test_original_review_or_missing_new_review_cannot_close_response(tmp_path,monkeypatch):
    action,fixture=plan(tmp_path,monkeypatch);_,_,production,state,campaign,package,final,registry=fixture
    result=mw.prepare_successor(action,successor_request(tmp_path,production,package),tmp_path/'next',base_dir=tmp_path,campaign=campaign)
    with pytest.raises(ValueError,match='exact prepared ordinary writer'):
        mw.resolve_actions(result['successor'],package['package_pin'],['critic','verifier','synthesizer'],tmp_path/'old-resolution',base_dir=tmp_path,campaign=campaign)
    complete({'binding':result['writer']},state,final,monkeypatch,registry)
    new=mp.collect(result['writer'],tmp_path/'new')
    monkeypatch.setattr(mw.integrity,'assess',lambda *a,**k:{'complete_actual_independent_roles':True,'scoped_integrity_review_complete':False})
    with pytest.raises(ValueError,match='fresh actual complete'):
        mw.resolve_actions(result['successor'],new['package_pin'],['critic','verifier','synthesizer'],tmp_path/'missing-resolution',base_dir=tmp_path,campaign=campaign)


def test_coordinator_exposes_actual_typed_services_without_new_engine():
    for action, function in [('manuscript-actions','prepare_actions'),('manuscript-action-meta','prepare_action_meta'),
                             ('manuscript-successor','prepare_successor'),('manuscript-action-resolve','resolve_actions')]:
        assert decisions.EXTENSIONS[action]==('ravel.workflow.manuscript_workflow',function)
        assert decisions.EXTENSION_TRANSPORT[action]['arguments']


def actual_reviews(root,monkeypatch):
    """Distinct located old/new synthetic review subjects, never a latest-case stub."""
    registry={}
    def add(package,prefix,verdict):
        ir=mw._read(package['integrity_request'],root)
        subject=put(root,prefix+'-case.json',{'root':'manuscript-integrity','nodes':[
            {'id':'manuscript-integrity','anchors':[{'format':'json','location':'','value':ir}]}]})
        subject={k:subject[k] for k in ('path','sha256')}
        bindings=[]
        for role in ('critic','verifier','synthesizer'):
            key=prefix+'-'+role;bindings.append(key)
            registry[key]={'receipt':{'role':role,'explicit_synthetic_review':True},
                'contract':{'role':role,'actor_id':key,'case_pin':subject,'rundir':str(root)},
                'value':{'kind':'scientific_review','verdict':verdict,'audit':{
                    'nodes':[{'id':'method.square','decision':'unresolved','assumptions':[]}] if verdict=='send_back' else [],
                    'edges':[]}},'supporting_artifacts':[]}
        return bindings
    monkeypatch.setattr(scientific_judgment,'verify_binding',lambda binding:deepcopy(registry[binding]))
    def assess(request,bindings,**kw):
        receipts=[registry[b] for b in bindings]
        exact=all(scientific_judgment._read_pin(r['contract']['case_pin'])['nodes'][0]['anchors'][0]['value']==request for r in receipts)
        roles={r['contract']['role'] for r in receipts}
        return {'complete_actual_independent_roles':exact and roles=={'critic','verifier','synthesizer'},
            'scoped_integrity_review_complete':exact and roles=={'critic','verifier','synthesizer'} and all(r['value']['verdict']=='pass' for r in receipts)}
    monkeypatch.setattr(mw.integrity,'assess',assess)
    monkeypatch.setattr(mw.integrity,'assessment_pins',lambda *a,**k:[])
    return add


def current_budget(campaign):
    _,state=mw.cycle._load(campaign)
    return {k:state['contract']['budget'][k]-mw.cycle._usage(state)[k] for k in state['contract']['budget']}


def test_prior_origin_revision_preparation_uses_current_head_budget_after_real_context_change(tmp_path,monkeypatch):
    from test_manuscript_historical_origin import historical_episode
    request,value,campaign,initial,binding,completion,got,advanced=historical_episode(tmp_path,monkeypatch)
    add=actual_reviews(tmp_path,monkeypatch);reviews=add(got['package'],'old','send_back')
    before=mw.cycle._load(campaign)[1];budget=current_budget(campaign)
    revision=mw.prepare_revision(got['package_pin'],reviews,tmp_path/'actual-revision',base_dir=tmp_path,
        campaign=campaign,budget=budget)['revision']
    record=mw._read(revision,tmp_path)
    allocated=mw.cycle._load(campaign)[1]
    assert allocated['parent_sha256']==before['sha256'] and allocated['events'][-1]['kind']=='manuscript_revision_allocated'
    assert record['campaign_state_sha256']==allocated['sha256'] and record['campaign_context_sha256']==mp.ce.digest(advanced['context'])
    assert record['remaining_budget']==budget and budget['calls']==19 and mw.cycle._usage(allocated)==mw.cycle._usage(before)
    rows=[{'objection_index':i,'kind':'editorial','response':'Preserve the source and original result; clarify its wording.',
        'protocol_claim_ids':[],'protocol_stage_ids':[],'required_experiment_ids':[]} for i in range(3)]
    action=mw.prepare_actions(revision,rows,tmp_path/'actual-actions',base_dir=tmp_path,campaign=campaign)['action_plan']
    assert mw.verify_actions(action,base_dir=tmp_path,campaign=campaign)['state']==allocated
    with pytest.raises(ValueError,match='research quantities changed'):mp.verify_author(got['package'],base_dir=tmp_path)
    inflated=deepcopy(budget);inflated['calls']+=1
    with pytest.raises(ValueError,match='replenish'):
        mw.prepare_revision(got['package_pin'],reviews,tmp_path/'inflated',base_dir=tmp_path,campaign=campaign,budget=inflated)
    assert not (tmp_path/'inflated').exists() and mw.cycle._load(campaign)[1]==allocated


def material_actual_campaign(root,monkeypatch):
    """Real campaign/protocol/current-context history; supplied science is scoped inert."""
    import test_research_protocol as inherited
    from test_manuscript_production import setup
    from ravel.workflow import scientific_report as sr
    actual_load=mw.cycle._load;actual_context=sr._context
    request,_,value=setup(root/'source',monkeypatch)
    monkeypatch.setattr(mw.cycle,'_load',actual_load);monkeypatch.setattr(sr,'_context',actual_context)
    campaign,protocol=inherited.baseline_screen_full(root/'protocol',monkeypatch)
    state=mw.cycle._load(campaign)[1]
    request['runtime'].update(action='model',model='fixture-model',model_build='observed-snapshot',max_output_tokens=128)
    cp=put(root/'source','context-c0.json',state['context'])
    request['quantitative_report']=put(root/'source','quantities-c0.json',{'context':{**cp,'path':Path(cp['path']).name},'toy_request':True})
    return request,value,campaign,protocol


def probe_stage(protocol):
    """Append the complete two-cell probe stage on fresh cells that declare their exposure.

    The actual observation derives a stage's evaluation from its cells, which must name
    complete distinct seeds and a data generation. Bound protocol rows cannot change, so
    the probe reads fresh copies of the full cells, not the original rows.
    """
    original=next(s for s in protocol['stages'] if s['id']=='new-full')
    cells={c['id']:c for c in protocol['cells']};rows=[]
    for index,row in enumerate(original['cells']):
        cell={**deepcopy(cells[row['cell_id']]),'id':'probe-'+row['cell_id'],'seeds':[40+index],'generation':'probe-data'}
        protocol['cells'].append(cell);rows.append({**row,'cell_id':cell['id'],'experiment_id':'objection-probe'})
    protocol['stages'].append({**deepcopy(original),'id':'objection-probe','purpose':'full','requires':[],'requires_stages':[],'cells':rows})


def observe_inert_complete_study(root,campaign,identity,monkeypatch):
    """Actual observe/context/journal bodies; terminal SDK/review boundaries are inert.

    No process, native result, physics vote or claimed measured efficacy exists.
    The real complete deterministic comparison result is kept whole; its missing
    requested covariance remains an unresolved scientific-context quantity.
    """
    import test_research_protocol as inherited
    from ravel.workflow import science
    result=inherited.accepted_fixture(campaign,identity)
    _,state=mw.cycle._load(campaign);e=next(e for e in state['experiments'] if e['id']==identity)
    rd=Path(e['rundir']);old_adjudication=deepcopy(e['adjudication']);receipt=e['observation']['receipt']
    e['observation']=None;e['adjudication']=None;e['context_outputs']={'measurement':'outputs/attempt-1/result.json'}
    # Standard result location and existing explicit synthetic ordinary receipt.
    put(rd/'outputs/attempt-1','result.json',mw._read(result,root))
    # The evaluation records the attempt's measured cost: the synthetic record declares one.
    receipt=put(Path(receipt['path']).parent,Path(receipt['path']).name,{**mw._read(receipt,root),'wall_seconds':1.5})
    mw.cycle._charge(state,'experiment:'+identity,e['cost'],e['study'])
    mw.cycle._commit(campaign,state,'explicit_inert_terminal_study_presented',experiment_id=identity)
    expected=str(rd.resolve())
    with monkeypatch.context() as scoped:
        def checked(path):
            assert str(Path(path).resolve())==expected
        def verify(path,*,approved):checked(path);assert approved is True
        def packet(path):checked(path);return {'execution':{'status':'succeeded'},'errors':[],
            'explicit_inert_terminal_adapter':True}
        def execution(path):
            checked(path);return {'stages':{'science':{'attempt_record':str(Path(receipt['path']).relative_to(rd)),
                'attempt_id':'synthetic-'+identity,'status':'succeeded'}}}
        scoped.setattr(science,'verify_plan',verify);scoped.setattr(science,'packet',packet)
        scoped.setattr(science.execution,'load_execution',execution)
        observed=mw.cycle.observe(campaign,identity)
    e=next(e for e in observed['experiments'] if e['id']==identity)
    assert observed['events'][-1]['kind']=='actual_study_observed' and e['observation']['scientific_acceptance'] is False
    assert len(mw._read(e['observation']['result'],root)['cells'])==2
    # The observation recorded the evaluation with the declared exposure of both cells.
    evaluation=next(v['evaluation'] for v in reversed(observed['events']) if v['kind']=='research_evaluation_observed' and v['experiment_id']==identity)
    assert evaluation['cells']==['probe-full-a','probe-full-b'] and evaluation['seeds']==['40','41'] and evaluation['generation']=='probe-data'
    assert evaluation['cost']==1.5 and evaluation['attempt']==receipt and evaluation['status']=='success'
    # This is the explicitly supplied scoped review stand-in used by the source
    # protocol fixture, not an independent physicist/model adjudication.
    e['adjudication']=old_adjudication
    return mw.cycle._commit(campaign,observed,'explicit_synthetic_scope_presented',experiment_id=identity)


def test_material_action_real_observation_context_change_and_current_replacement_writer(tmp_path,monkeypatch):
    import test_research_protocol as inherited
    from test_manuscript_historical_origin import complete_actual
    request,value,campaign,protocol=material_actual_campaign(tmp_path,monkeypatch)
    # Prepare the future complete two-cell probe before opening its obligation.
    probe_stage(protocol)
    rp.bind(campaign,put(tmp_path/'protocol','extended-protocol.json',protocol))
    inherited.design(tmp_path/'protocol',campaign,protocol,'objection-probe',[3,4])
    first=mp.prepare_writer(request,tmp_path/'first',base_dir=tmp_path/'source',campaign=campaign)
    complete_actual(first,value,monkeypatch);old=mp.collect(first,tmp_path/'old-note')
    add=actual_reviews(tmp_path,monkeypatch);reviews=add(old['package'],'old','send_back')
    revision=mw.prepare_revision(old['package_pin'],reviews,tmp_path/'revision',base_dir=tmp_path,campaign=campaign,
        budget=current_budget(campaign))['revision']
    rows=[{'objection_index':i,'kind':'empirical','response':'Observe the complete declared two-cell probe, retain all outcomes.',
        'protocol_claim_ids':['complete-method'],'protocol_stage_ids':['new-full'],
        'required_experiment_ids':['objection-probe']} for i in range(3)]
    action=mw.prepare_actions(revision,rows,tmp_path/'actions',base_dir=tmp_path,campaign=campaign)['action_plan']
    # Keep inherited actual Graph/Host/meta bodies; only supply the exact plan pin
    # at their normal preparation argument, with no action-context/currentness stub.
    original_prepare=rp.prepare_meta_review
    monkeypatch.setattr(rp,'prepare_meta_review',lambda *a,**kw:original_prepare(*a,**kw,manuscript_action_plan=action))
    opened=inherited.meta(tmp_path/'protocol',campaign,monkeypatch,'additional_evidence',stages=['new-full'],required=['objection-probe'])
    meta_revision=opened['events'][-1]['revision'];before=mw.cycle._load(campaign)[1]
    with pytest.raises(ValueError,match='fresh scientific replacement'):
        mw.prepare_successor(action,put(tmp_path,'too-early.json',request),tmp_path/'too-early',base_dir=tmp_path,campaign=campaign)
    assert not (tmp_path/'too-early').exists()
    observed=observe_inert_complete_study(tmp_path,campaign,'objection-probe',monkeypatch)
    assert observed['context']!=before['context'] and observed['context']['steps']
    resolved=inherited.meta(tmp_path/'protocol',campaign,monkeypatch,'resolve_objections',stages=['new-full'],
        required=['objection-probe'],resolves=[meta_revision])
    assert not rp._active_holds(resolved,'complete-method')
    current=mw.verify_actions(action,base_dir=tmp_path,campaign=campaign)
    assert len(mw._material_actions_complete(current))==2
    # Source-faithful C0 provenance remains verifiable, while current acceptance
    # and a C0 replacement remain invalid. No history/currentness verifier stub.
    mp.verify_author_origin(old['package'],base_dir=tmp_path)
    with pytest.raises(ValueError,match='research quantities changed'):mp.verify_author(old['package'],base_dir=tmp_path)
    stale=deepcopy(request);stale['revision']={'previous_package':old['package_pin'],'feedback_binding':reviews[0]}
    with pytest.raises(ValueError):mw.prepare_successor(action,put(tmp_path,'stale.json',stale),tmp_path/'stale-writer',base_dir=tmp_path,campaign=campaign)
    fresh=deepcopy(stale);cp=put(tmp_path/'source','context-c1.json',resolved['context'])
    fresh['quantitative_report']=put(tmp_path/'source','quantities-c1.json',{'context':{**cp,'path':Path(cp['path']).name},'toy_request':True})
    next_=mw.prepare_successor(action,put(tmp_path,'fresh.json',fresh),tmp_path/'next',base_dir=tmp_path,campaign=campaign)
    assert not next_['objections_closed']
    response=mw._read(mw._read(next_['successor'],tmp_path)['response'],tmp_path)
    assert [r['objection_index'] for r in response['actions']]==[0,1,2] and len(response['actual_protocol_events'])==2
    charged=complete_actual(next_['writer'],value,monkeypatch);new=mp.collect(next_['writer'],tmp_path/'new-note')
    fresh_reviews=add(new['package'],'new','pass')
    with pytest.raises(ValueError,match='fresh actual complete'):
        mw.resolve_actions(next_['successor'],new['package_pin'],reviews,tmp_path/'old-review-refused',base_dir=tmp_path,campaign=campaign)
    result=mw.resolve_actions(next_['successor'],new['package_pin'],fresh_reviews,tmp_path/'resolved-writing',
        base_dir=tmp_path,campaign=campaign)
    assert result['resolved_objection_count']==3 and not result['scientific_acceptance'] and not result['parent_task_accepted']
    assert mw.cycle._usage(charged)['calls']==4 and len(charged['resource_ledger'])==5
    assert charged['timing']==before['timing'] and new['package']['parent_task_accepted'] is False


def test_complete_actual_phase_transcript_origin_after_context_advance(tmp_path,monkeypatch):
    from test_manuscript_historical_origin import actual_campaign_setup,complete_actual,advance_supplied_context
    from test_staged_manuscript_authoring import plan as story_value
    from ravel.workflow import scientific_report as sr
    request,final,campaign,initial=actual_campaign_setup(tmp_path,monkeypatch)
    request['runtime']['max_output_tokens']=128
    request['runtime']['max_context_bytes']=400000
    # A disclosed fixed prose/quantity projection; real replay/history remain in
    # the original _context and cycle._load, restored by actual_campaign_setup.
    monkeypatch.setattr(sr,'compose',lambda *a,**kw:{'report_text':'Supplied toy score4; no physics validity.',
        'requested_quantity_completion':False,'expected_slots':{'score':{'fact_id':'score','value':4,'unit':'1','scope':'toy','population':'whole supplied toy'}},'facts':[]})
    prod=put(tmp_path/'source','production.json',request);slots=[]
    for i,kind in enumerate(['story','citation-scout','caption','section','coherence','editorial-revision','synthesis']):
        slots.append({'id':'phase'+str(i),'kind':kind,'depends_on':[] if i==0 else [s['id'] for s in slots] if kind=='synthesis' else ['phase0'],
            'runtime':deepcopy(request['runtime'])})
    declaration={'schema_version':2,'kind':'staged-manuscript-request','production_request':prod,'missing':[],
        'phase_slots':slots,'budget':{'max_calls':7,'max_input_tokens':112000,'max_output_tokens':896,
            'max_wall_seconds':420,'max_context_bytes':400000,'max_revisions':1}}
    staged=put(tmp_path/'source','staged.json',declaration);current=mw._load(staged,tmp_path/'source')
    prepared=mw.prepare_story(staged,tmp_path/'workflow',base_dir=tmp_path/'source',campaign=campaign)
    complete_actual(prepared['binding'],story_value(current),monkeypatch)
    story=mw.consume_phase(prepared,tmp_path/'workflow/issued/phase0/consumed',base_dir=tmp_path)['product']
    resolution=mw.resolve_sources(story,prod,tmp_path/'resolution',base_dir=tmp_path,campaign=campaign)['resolution'];products=[story]
    for i in range(1,6):
        prepared=mw.prepare_phase(story,'phase'+str(i),tmp_path/('workflow/issued/phase'+str(i)),base_dir=tmp_path,
            campaign=campaign,prior_products=[story],resolution_pin=resolution)
        value={'paragraphs':deepcopy(final['paragraphs']) if i in (3,4,5) else [],'figures':[],'tasks':[],'unresolved':[]}
        complete_actual(prepared['binding'],value,monkeypatch)
        products.append(mw.consume_phase(prepared,tmp_path/('workflow/issued/phase'+str(i)+'/consumed'),base_dir=tmp_path)['product'])
    synthesis=mw.prepare_phase(story,'phase6',tmp_path/'workflow/issued/phase6',base_dir=tmp_path,campaign=campaign,
        prior_products=products,resolution_pin=resolution)
    owner=synthesis['binding']['author_binding'];complete_actual(owner,final,monkeypatch)
    got=mw.assemble(story,products,tmp_path/'note',base_dir=tmp_path,campaign=campaign,synthesis_binding=synthesis)
    before=advance_supplied_context(campaign,tmp_path/'observations')
    mp.verify_author_origin(got['package'],base_dir=tmp_path)
    loaded=mp._load(request,tmp_path/'source');view=mp._origin_view(owner,loaded)
    transcript=mw.verify_transcript(owner['stages'],loaded,campaign,_origin=view)
    assert len(transcript['actual_prior_phases'])==6 and transcript['prior_reserved_output_tokens']==768
    assert mw.transcript_pins(owner['stages'],loaded,campaign,_origin=view)
    view.close();assert mw.cycle._load(campaign)[1]==before and mw.cycle._usage(before)['calls']==7
    with pytest.raises(ValueError):mw.verify_transcript(owner['stages'],loaded,campaign)
    with pytest.raises(ValueError,match='never authorizes'):
        mw._phase_state(mw._read(transcript['actual_prior_phases'][0]['binding'],tmp_path),require_complete=False,_origin=view)


@pytest.mark.parametrize('fault',['lower','current','replayed-preparation','cross-criticism'])
def test_actual_public_readback_rejects_rebound_revision_baseline(tmp_path,monkeypatch,fault):
    action,fixture=plan(tmp_path,monkeypatch);revision,_,_,_,campaign,package,*_=fixture
    original=mw.verify_actions(action,base_dir=tmp_path,campaign=campaign)
    charged=spend_inert(campaign,2)
    data=deepcopy(original['plan'])
    if fault=='lower':data['usage_at_prepare']['calls']=0
    else:data['usage_at_prepare']=mw.cycle._usage(charged)
    if fault=='replayed-preparation':
        value=mw._read(revision,tmp_path);value['campaign_state_sha256']=charged['sha256']
        data['revision']=put(tmp_path,'replayed-criticism.json',value)
    elif fault=='cross-criticism':
        actual=scientific_judgment.verify_binding
        def distinct(binding):
            value=deepcopy(actual(binding));value['contract']['actor_id']='new-'+value['contract']['actor_id']
            value['receipt']['new_explicit_inert_review']=True
            return value
        with monkeypatch.context() as local:
            local.setattr(scientific_judgment,'verify_binding',distinct)
            another=mw.prepare_revision(package['package_pin'],['critic','verifier','synthesizer'],tmp_path/'different-criticism',
                base_dir=tmp_path,campaign=campaign,budget={'calls':2,'output_tokens':50000,'wall_seconds':1000,'native_attempts':0})['revision']
            other=mw._revision_inputs(another,tmp_path,campaign)[4]
            data['usage_at_prepare']=mw.cycle._usage(other)
    with pytest.raises(ValueError,match='baseline'):
        mw.verify_actions(put(tmp_path,'rebound-plan.json',data),base_dir=tmp_path,campaign=campaign)
    unchanged=mw.verify_actions(action,base_dir=tmp_path,campaign=campaign)
    assert unchanged['plan']['usage_at_prepare']==original['plan']['usage_at_prepare']
    assert mw.cycle._usage(unchanged['state'])['calls']==original['plan']['usage_at_prepare']['calls']+2


def test_same_criticism_repreparation_reuses_earliest_allocation_after_spend(tmp_path,monkeypatch):
    action,fixture=plan(tmp_path,monkeypatch);revision,rows,_,_,campaign,package,*_=fixture
    original=mw.verify_actions(action,base_dir=tmp_path,campaign=campaign);spend_inert(campaign,2)
    before=mw.cycle._load(campaign)[1]
    again=mw.prepare_revision(package['package_pin'],['critic','verifier','synthesizer'],tmp_path/'same-criticism',
        base_dir=tmp_path,campaign=campaign,budget=original['plan']['remaining_budget'])['revision']
    repinned=put(tmp_path,'copied-revision.json',mw._read(again,tmp_path))
    new=mw.prepare_actions(repinned,rows,tmp_path/'same-actions',base_dir=tmp_path,campaign=campaign)['action_plan']
    current=mw.verify_actions(new,base_dir=tmp_path,campaign=campaign)
    assert current['plan']['usage_at_prepare']==original['plan']['usage_at_prepare']
    assert len([e for e in current['state']['events'] if e['kind']=='manuscript_revision_allocated'])==1
    assert mw.cycle._load(campaign)[1]==before
    with pytest.raises(ValueError,match='no per-action reset'):
        mw._action_allowance(current,{'calls':9,'output_tokens':0,'wall_seconds':0,'native_attempts':0})
    increased=deepcopy(original['plan']['remaining_budget']);increased['calls']+=1
    with pytest.raises(ValueError,match='cannot replenish'):
        mw.prepare_revision(package['package_pin'],['critic','verifier','synthesizer'],tmp_path/'increased',
            base_dir=tmp_path,campaign=campaign,budget=increased)


def test_genuine_distinct_criticism_has_distinct_original_allocation(tmp_path,monkeypatch):
    action,fixture=plan(tmp_path,monkeypatch);_,rows,_,_,campaign,package,*_=fixture
    previous=mw.verify_actions(action,base_dir=tmp_path,campaign=campaign);charged=spend_inert(campaign,2)
    actual=scientific_judgment.verify_binding
    def distinct(binding):
        value=deepcopy(actual(binding));value['contract']['actor_id']='next-'+value['contract']['actor_id']
        value['receipt']['explicit_distinct_review']=True
        return value
    monkeypatch.setattr(scientific_judgment,'verify_binding',distinct)
    budget={'calls':2,'output_tokens':10000,'wall_seconds':100,'native_attempts':0}
    revision=mw.prepare_revision(package['package_pin'],['critic','verifier','synthesizer'],tmp_path/'next-criticism',
        base_dir=tmp_path,campaign=campaign,budget=budget)['revision']
    following=mw.prepare_actions(revision,rows,tmp_path/'next-actions',base_dir=tmp_path,campaign=campaign)['action_plan']
    current=mw.verify_actions(following,base_dir=tmp_path,campaign=campaign)
    assert current['plan']['usage_at_prepare']==mw.cycle._usage(charged)
    assert current['allocation']['criticism_sha256']!=previous['allocation']['criticism_sha256']
    assert current['plan']['remaining_budget']==budget and len([e for e in current['state']['events'] if e['kind']=='manuscript_revision_allocated'])==2


def actual_material_plan(root,monkeypatch,*,calls=2):
    import test_research_protocol as inherited
    from test_manuscript_historical_origin import complete_actual
    request,value,campaign,protocol=material_actual_campaign(root,monkeypatch)
    probe_stage(protocol)
    rp.bind(campaign,put(root/'protocol','more-protocol.json',protocol));inherited.design(root/'protocol',campaign,protocol,'objection-probe',[3,4])
    first=mp.prepare_writer(request,root/'first',base_dir=root/'source',campaign=campaign)
    complete_actual(first,value,monkeypatch);package=mp.collect(first,root/'first-note')
    add=actual_reviews(root,monkeypatch);reviews=add(package['package'],'first','send_back')
    budget=current_budget(campaign);budget['calls']=calls
    revision=mw.prepare_revision(package['package_pin'],reviews,root/'revision',base_dir=root,campaign=campaign,budget=budget)['revision']
    rows=[{'objection_index':i,'kind':'empirical','response':'Add a full fresh observation with the original method law.',
        'protocol_claim_ids':['complete-method'],'protocol_stage_ids':[],'required_experiment_ids':['objection-probe']} for i in range(3)]
    action=mw.prepare_actions(revision,rows,root/'actions',base_dir=root,campaign=campaign)['action_plan']
    return action,request,value,campaign,package,reviews


def direct_meta(root,campaign,action):
    return rp.prepare_meta_review(campaign,root,role='verifier',model='inert',reasoning_effort='high',
        max_output_tokens=128,max_wall_seconds=10,manuscript_action_plan=action)


def test_direct_public_meta_preparation_refuses_zero_revision_allowance(tmp_path,monkeypatch):
    action,_,_,campaign,*_=actual_material_plan(tmp_path,monkeypatch,calls=0)
    before=mw.cycle._load(campaign)[1]
    with pytest.raises(ValueError,match='allocation exhausted'):
        direct_meta(tmp_path/'not-prepared',campaign,action)
    assert not (tmp_path/'not-prepared').exists() and mw.cycle._load(campaign)[1]==before


@pytest.mark.parametrize('fault',['spent','copied-root','changed-spec'])
def test_real_graph_dispatch_rechecks_original_revision_reservation(tmp_path,monkeypatch,fault):
    action,_,_,campaign,*_=actual_material_plan(tmp_path,monkeypatch,calls=1)
    prepared=direct_meta(tmp_path/'prepared-meta',campaign,action)
    spec=state_io.read_json(prepared['graph_spec']['path']);graph=prepared['graph_root']
    if fault=='spent':spend_inert(campaign,1)
    elif fault=='copied-root':graph=str(tmp_path/'copied-graph')
    else:spec['budget']['max_output_tokens']+=1
    before=mw.cycle._load(campaign)[1]
    with pytest.raises(ValueError):mw.cycle.execute_graph(campaign,graph,spec,object())
    assert mw.cycle._load(campaign)[1]==before and not Path(graph).exists()


def test_already_charged_complete_meta_resume_keeps_original_authority_without_double_charge(tmp_path,monkeypatch):
    import test_research_protocol as inherited
    action,_,_,campaign,*_=actual_material_plan(tmp_path,monkeypatch,calls=1)
    original=rp.prepare_meta_review
    monkeypatch.setattr(rp,'prepare_meta_review',lambda *a,**kw:original(*a,**kw,manuscript_action_plan=action))
    state=inherited.meta(tmp_path/'protocol',campaign,monkeypatch,'additional_evidence',required=['objection-probe'])
    graph=state['graphs'][-1]['root'];spec=mp.agent_graph._load(Path(graph))[0]
    spent=spend_inert(campaign,1);usage=mw.cycle._usage(spent)
    # Resume still authenticates the original executable source/config. The
    # initial inherited.meta call used this same genuinely configured Host;
    # no provider or model dispatch is allowed when adopting its completion.
    from ravel.workflow import agent_host
    host=agent_host.AgentHost(endpoint='http://127.0.0.1:9/v1/responses')
    checkpoint=mp.agent_graph._load(Path(graph))[1]
    before=mw.cycle._load(campaign)[1]
    invoked=[]
    def no_dispatch(*args,**kwargs):
        invoked.append((args,kwargs));raise AssertionError('Completed resume must not dispatch another Host call')
    monkeypatch.setattr(host,'execute',no_dispatch)
    node=next(n for n in spec['nodes'] if n['id']=='meta')
    assert checkpoint['nodes']['meta']['result']['host_sha256']==mp.agent_graph._node_host_sha(node,mp.agent_graph._host_identity(host))
    result=mw.cycle.execute_graph(campaign,graph,spec,host)
    assert result['complete'] and mw.cycle._usage(mw.cycle._load(campaign)[1])==usage
    assert mp.agent_graph.status(graph)['usage']['calls']==1
    assert invoked==[] and mp.agent_graph._load(Path(graph))[1]==checkpoint
    assert mw.cycle._load(campaign)[1]['resource_ledger']==before['resource_ledger']


@pytest.mark.parametrize('fault',['code','operation'])
def test_empirical_label_cannot_change_actual_method_without_full_reexecution(tmp_path,monkeypatch,fault):
    import test_research_protocol as inherited
    from test_manuscript_production import loc
    action,request,value,campaign,package,reviews=actual_material_plan(tmp_path,monkeypatch,calls=4)
    original=rp.prepare_meta_review
    monkeypatch.setattr(rp,'prepare_meta_review',lambda *a,**kw:original(*a,**kw,manuscript_action_plan=action))
    opened=inherited.meta(tmp_path/'protocol',campaign,monkeypatch,'additional_evidence',required=['objection-probe'])
    observe_inert_complete_study(tmp_path,campaign,'objection-probe',monkeypatch)
    resolved=inherited.meta(tmp_path/'protocol',campaign,monkeypatch,'resolve_objections',required=['objection-probe'],resolves=[opened['events'][-1]['revision']])
    fresh=deepcopy(request);fresh['revision']={'previous_package':package['package_pin'],'feedback_binding':reviews[0]}
    fresh['quantitative_report']=put(tmp_path/'source','current-quantities.json',{
        'context':quantitative_context(tmp_path/'source','current-context.json',resolved['context']),'toy_request':True})
    if fault=='code':
        source=put(tmp_path/'source','different-score.py','def square(x):\n    return x*x+1\n')
        fresh['methods'][0]['operations'][0]['code']=[loc(source,Path(source['path']).read_text())]
        manifest=deepcopy(mw._read(fresh['code_manifest'],tmp_path));manifest['files'].append(source)
        fresh['code_manifest']=put(tmp_path/'source','changed-code-manifest.json',manifest)
    else:fresh['methods'][0]['operations'][0]['id']='different-estimator'
    before=mw.cycle._load(campaign)[1]
    with pytest.raises(ValueError,match='actual changed method requires mapped core-method'):
        mw.prepare_successor(action,put(tmp_path,'hidden-core-change.json',fresh),tmp_path/'refused-writer',base_dir=tmp_path,campaign=campaign)
    assert not (tmp_path/'refused-writer').exists() and mw.cycle._load(campaign)[1]==before


def test_same_method_fresh_result_does_not_change_code_operation_semantics(tmp_path):
    row={'id':'method','description':'Fixed original estimator','citation_ids':[],'uncertainties':['Original applicability'],
        'operations':[{'id':'op','description':'Fixed operation','code':[],'execution':None,'results':[{'value':1}],'differences':['Original observation']}]}
    fresh=deepcopy(row);fresh['operations'][0].update(execution={'observed':'fresh'},results=[{'value':2}],differences=['Fresh observation'])
    assert mw._method_semantics(row,tmp_path)==mw._method_semantics(fresh,tmp_path)
    fresh['operations'][0]['description']='Different estimator'
    assert mw._method_semantics(row,tmp_path)!=mw._method_semantics(fresh,tmp_path)


def test_renamed_copied_action_graph_refuses_before_charge_or_host_effect(tmp_path,monkeypatch):
    action,_,_,campaign,*_=actual_material_plan(tmp_path,monkeypatch,calls=1)
    prepared=direct_meta(tmp_path/'original-meta',campaign,action)
    spec=state_io.read_json(prepared['graph_spec']['path'])
    spec['graph_id']='generic-action-copy'
    copied=tmp_path/'generic-copy'
    spend_inert(campaign,1)
    before=mw.cycle._load(campaign)[1]
    current=mw.verify_actions(action,base_dir=tmp_path,campaign=campaign)
    assert current['allocation']['budget']['calls']==1
    assert mw.cycle._usage(before)['calls']==current['allocation']['usage']['calls']+1
    assert before['contract']['budget']['calls']>mw.cycle._usage(before)['calls']
    invoked=[]
    class NoEffectHost:
        def execute(self,*args,**kwargs):
            invoked.append((args,kwargs));raise AssertionError('No Host effect admitted')
    with pytest.raises(ValueError,match='original manuscript graph preparation registration required'):
        mw.cycle.execute_graph(campaign,copied,spec,NoEffectHost())
    assert invoked==[] and not copied.exists()
    assert mw.cycle._load(campaign)[1]==before
    assert not any(row['id']=='graph:'+str(copied) for row in before['resource_ledger'])


def test_unrelated_renamed_generic_packet_graph_keeps_real_public_dispatch(tmp_path,monkeypatch):
    import test_research_protocol as inherited
    campaign,_=inherited.baseline_screen_full(tmp_path,monkeypatch)
    before=mw.cycle._load(campaign)[1]
    original=rp.prepare_meta_review
    def generic(*args,**kwargs):
        assert 'manuscript_action_plan' not in kwargs
        prepared=original(*args,**kwargs)
        spec=state_io.read_json(prepared['graph_spec']['path'])
        spec['graph_id']='unrelated-generic-review'
        prepared['graph_spec']=put(Path(prepared['graph_spec']['path']).parent,'generic-spec.json',spec)
        return prepared
    monkeypatch.setattr(rp,'prepare_meta_review',generic)
    after=inherited.meta(tmp_path,campaign,monkeypatch,'report_only')
    assert after['events'][-1]['kind']=='protocol_meta_review_applied'
    assert mw.cycle._usage(after)['calls']==mw.cycle._usage(before)['calls']+1
    assert not any(e['kind']=='manuscript_action_graph_prepared' for e in after['events'])
    graph=Path(after['graphs'][-1]['root'])
    spec,actual=mp.agent_graph._load(graph)
    assert spec['graph_id']=='unrelated-generic-review' and actual['usage']['calls']==1
    assert mp.agent_graph.status(graph)['complete']


@pytest.mark.parametrize('fault',['identityless','changed-config'])
def test_complete_action_resume_still_requires_exact_host_identity_without_new_charge(tmp_path,monkeypatch,fault):
    import test_research_protocol as inherited
    from ravel.workflow import agent_host
    action,_,_,campaign,*_=actual_material_plan(tmp_path,monkeypatch,calls=1)
    original=rp.prepare_meta_review
    monkeypatch.setattr(rp,'prepare_meta_review',lambda *a,**kw:original(*a,**kw,manuscript_action_plan=action))
    state=inherited.meta(tmp_path/'protocol',campaign,monkeypatch,'additional_evidence',required=['objection-probe'])
    graph=state['graphs'][-1]['root'];spec,checkpoint=mp.agent_graph._load(Path(graph))
    assert checkpoint['nodes']['meta']['status']=='completed' and checkpoint['usage']['calls']==1
    spent=spend_inert(campaign,1);usage=mw.cycle._usage(spent)
    invoked=[]
    def no_dispatch(*args,**kwargs):
        invoked.append((args,kwargs));raise AssertionError('Invalid resume identity must refuse before Host dispatch')
    if fault=='identityless':
        class MissingIdentityHost:
            execute=staticmethod(no_dispatch)
        host=MissingIdentityHost()
        message='executable host must expose its nonsecret source/config identity'
    else:
        host=agent_host.AgentHost(endpoint='http://127.0.0.1:10/v1/responses')
        monkeypatch.setattr(host,'execute',no_dispatch)
        message='completed generation source/request/host differs; explicit rework required'
    with pytest.raises(mp.agent_graph.GraphError) as refused:
        mw.cycle.execute_graph(campaign,graph,spec,host)
    assert str(refused.value)==message
    assert invoked==[] and mp.agent_graph._load(Path(graph))[1]==checkpoint
    current=mw.cycle._load(campaign)[1]
    assert mw.cycle._usage(current)==usage and current['resource_ledger']==spent['resource_ledger']
    assert mp.agent_graph.status(graph)['complete'] and mp.agent_graph.status(graph)['usage']['calls']==1
