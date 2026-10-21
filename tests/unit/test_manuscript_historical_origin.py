"""UNRUN source-authorship controls with real campaign history and Graph accounting.

Scientific prose/quantities and local HTTP responses are disclosed toy data.
No research_cycle._load, scientific_report._context, author/role/materialization
or history verifier is replaced. A supplied context step is replayed through
scientific_context and committed to the existing journal; it is not an executed
scientific experiment or a native/model efficacy claim.
"""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from ravel.workflow import manuscript_production as mp, research_cycle as cycle
from ravel.workflow import scientific_context as sc, scientific_report as sr, agent_graph as graph
from ravel.workflow.state_io import atomic_json, read_json
from test_manuscript_production import setup, put, pin
from test_manuscript_revision_origin import revise
from test_research_cycle import contract
from test_visual_presentation import provider_host
from test_provider_transport import install_http


def actual_campaign_setup(root, monkeypatch):
    """Reusable genuine history/context producer; only report prose is synthetic."""
    actual_load=cycle._load;actual_context=sr._context
    request,_,value=setup(root/'source',monkeypatch)
    monkeypatch.setattr(cycle,'_load',actual_load)
    monkeypatch.setattr(sr,'_context',actual_context)
    declaration=contract(root/'source')
    declaration['budget'].update(calls=20,output_tokens=16384,wall_seconds=600)
    campaign=root/'campaign';state=cycle.create(campaign,declaration,base_dir=root/'source', evaluation_harness=True)
    cp=put(root/'source','context-c0.json',state['context'])
    request['quantitative_report']=put(root/'source','quantities-c0.json',{'context':{**cp,'path':Path(cp['path']).name},'toy_request':True})
    request['runtime'].update(action='model',model='fixture-model',model_build='observed-snapshot')
    return request,value,campaign,state


def complete_actual(binding,value,monkeypatch):
    from test_staged_manuscript_authoring import claim_fixture
    claim_fixture(binding,value)
    response={'status':'completed','model':'observed-snapshot','id':'synthetic-historical-wire',
        'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(value)}]}],
        'usage':{'input_tokens':10,'output_tokens':7,'total_tokens':17}}
    seen=install_http(monkeypatch,response)
    state=cycle.execute_graph(binding['campaign'],binding['graph'],binding['spec'],provider_host('responses'),prepared=True)
    assert state['complete'] and len(seen)==1
    return cycle._load(binding['campaign'])[1]


def advance_supplied_context(campaign,root,identity='measurement-c1'):
    _,state=cycle._load(campaign)
    measurement=put(root,identity+'.json',{'quantities':{'covariance':[[1.0]]}})
    step={'id':identity,'outputs':{'measurement':{k:measurement[k] for k in ('path','sha256')}},
        'code_status':'success','actor_complete':True,'question':None,'next_experiment':None}
    state['context']=sc.apply_step(state['context'],step,state['base_dir'])
    return cycle._commit(campaign,state,'supplied_context_observed',artifact=measurement)


def historical_episode(root,monkeypatch):
    request,value,campaign,initial=actual_campaign_setup(root,monkeypatch)
    binding=mp.prepare_writer(request,root/'writer',base_dir=root/'source',campaign=campaign)
    completion=complete_actual(binding,value,monkeypatch)
    package=mp.collect(binding,root/'note')
    advanced=advance_supplied_context(campaign,root/'observations')
    return request,value,campaign,initial,binding,completion,package,advanced


def rewrite_history(campaign, change):
    """Adversarial honestly rehashed chain; never an alternative production API."""
    head=read_json(campaign/'head.json');current=read_json(head['path'])
    # Records may be authenticated deltas; rewrite the replayed states as a full-snapshot chain.
    records=[cycle.historical_state(campaign,i) for i in range(current['revision']+1)]
    change(records)
    prior=None
    for record in records:
        record['parent_sha256']=prior;record.pop('sha256')
        record['sha256']=mp.ce.digest(record);prior=record['sha256']
        atomic_json(campaign/'history'/f"{record['revision']:04d}.json",record)
    atomic_json(campaign/'head.json',pin(campaign/'history'/f"{records[-1]['revision']:04d}.json"))


def test_actual_history_origin_allows_current_successor_but_never_old_current_acceptance(tmp_path,monkeypatch):
    r,value,campaign,initial,b,completion,got,advanced=historical_episode(tmp_path,monkeypatch)
    before=cycle._load(campaign)[1];old=deepcopy(got['package'])
    receipt=mp.verify_author_origin(old,base_dir=tmp_path)
    assert receipt['public_value']==value and got['package']==old
    assert cycle._load(campaign)[1]==before
    with pytest.raises(ValueError,match='research quantities changed'):mp.verify_author(old,base_dir=tmp_path)
    with pytest.raises(ValueError,match='stale research quantities'):mp.execute_writer(b,object())
    assert cycle._load(campaign)[1]==before and graph.status(b['graph'])['usage']['calls']==1
    current=deepcopy(r);cp=put(tmp_path/'source','context-c1.json',advanced['context'])
    current['quantitative_report']=put(tmp_path/'source','quantities-c1.json',{'context':{**cp,'path':Path(cp['path']).name},'toy_request':True})
    revised=revise(tmp_path/'revision-input',current,old,monkeypatch)
    new=mp.prepare_writer(revised,tmp_path/'new-writer',base_dir=tmp_path/'source',campaign=campaign)
    assert new['campaign']==b['campaign'] and new['spec']['nodes'][0]['role']=='improver'
    charged=complete_actual(new,value,monkeypatch)
    assert len(charged['resource_ledger'])==2 and cycle._usage(charged)['calls']==2
    new_package=mp.collect(new,tmp_path/'new-note')['package']
    mp.verify_author(new_package,base_dir=tmp_path)
    assert charged['timing']==before['timing']
    assert not any(Path(p['path']).name=='head.json' for p in new_package['input_pins'])
    assert mp._REVISION_VERIFICATION.get() is None


@pytest.mark.parametrize('fault',['preparation','completion-event','completion-context','usage','reservation','charge-event','carried-row'])
def test_historical_origin_rejects_missing_or_foreign_exact_history_laws(tmp_path,monkeypatch,fault):
    r,value,campaign,initial,b,completion,got,advanced=historical_episode(tmp_path,monkeypatch)
    if fault=='preparation':
        changed=deepcopy(b);changed['research_state_sha256']='f'*64
        atomic_json(Path(b['graph']).parent/'binding.json',changed)
        got['package']['author_binding']=pin(Path(b['graph']).parent/'binding.json')
    else:
        def corrupt(records):
            observed=records[completion['revision']]
            if fault in ('completion-event','carried-row'):observed['events'][-1]['kind']='not-an-actual-graph-observation'
            elif fault=='completion-context':observed['context']=advanced['context']
            elif fault=='usage':observed['graphs'][0]['usage']['calls']=2
            elif fault=='reservation':observed['resource_ledger'][0]['ceiling']['calls']=2
            elif fault=='charge-event':
                reservation=next(s for s in records if s['events'][-1]['kind']=='ordinary_graph_reserved')
                reservation['events'][-1]['kind']='not-an-original-graph-charge'
        rewrite_history(campaign,corrupt)
    with pytest.raises(ValueError):mp.verify_author_origin(got['package'],base_dir=tmp_path)
    assert graph.status(b['graph'])['usage']=={'calls':1,'reserved_output_tokens':4096}
    assert mp._REVISION_VERIFICATION.get() is None


def test_origin_append_before_new_operation_is_valid_but_same_operation_head_drift_refuses(tmp_path,monkeypatch):
    r,value,campaign,initial,b,completion,got,advanced=historical_episode(tmp_path,monkeypatch)
    mp.verify_author_origin(got['package'],base_dir=tmp_path)
    loaded=mp._load(r,tmp_path/'source');view=mp._origin_view(b,loaded)
    state=advance_supplied_context(campaign,tmp_path/'observations','measurement-c2')
    with pytest.raises(ValueError):view.close()
    mp.verify_author_origin(got['package'],base_dir=tmp_path)
    assert len(state['resource_ledger'])==1 and cycle._usage(state)['calls']==1
    assert not any(Path(p['path']).name=='head.json' for p in got['package']['input_pins'])


def test_historical_view_refuses_supplied_state_and_new_materialization(tmp_path,monkeypatch):
    r,value,campaign,initial,b,completion,got,advanced=historical_episode(tmp_path,monkeypatch)
    loaded=mp._load(r,tmp_path/'source');view=mp._origin_view(b,loaded)
    checkpoint=graph.status(b['graph'])
    args={'campaign':campaign,'prepared_sha256':b['research_state_sha256'],'graph_root':b['graph'],
        'graph_spec':b['spec'],'checkpoint':checkpoint,'quantitative_context':initial['context']}
    with pytest.raises(ValueError,match='internally authenticated'):mp._origin_campaign(deepcopy(completion),**args)
    assert mp._origin_campaign(view,**args)==completion
    state=mp._author_state(b,_origin=view)
    with pytest.raises(ValueError,match='cannot materialize'):
        mp._materialize(b,*state,tmp_path/'illegal-new-note',write=True,_origin=view)
    assert not (tmp_path/'illegal-new-note').exists()


def test_earliest_own_completion_remains_valid_after_repeat_observation(tmp_path,monkeypatch):
    r,value,campaign,initial,b,completion,got,advanced=historical_episode(tmp_path,monkeypatch)
    _,state=cycle._load(campaign)
    cycle._commit(campaign,state,'ordinary_graph_observed',graph_root=b['graph'])
    view=mp._origin_view(b,mp._load(r,tmp_path/'source'))
    assert view.owner['sha256']==completion['sha256']
    mp.verify_author_origin(got['package'],base_dir=tmp_path)
    assert cycle._usage(cycle._load(campaign)[1])['calls']==1


def test_intervening_context_step_refuses_prepared_current_writer_without_recharge(tmp_path,monkeypatch):
    r,value,campaign,initial=actual_campaign_setup(tmp_path,monkeypatch)
    b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path/'source',campaign=campaign)
    before=advance_supplied_context(campaign,tmp_path/'observations')
    with pytest.raises(ValueError,match='stale research quantities'):mp.execute_writer(b,object())
    assert cycle._load(campaign)[1]==before and graph.status(b['graph'])['usage']['calls']==0
