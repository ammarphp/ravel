"""Actual ordinary Graph/Host context and cycle transitions; inert counted transport only."""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import scientific_judgment as j, scientific_context_followup as f
from ravel.workflow import research_cycle as rc, agent_graph as graph, agent_host, review_context, execution, physics_review as review
from ravel.workflow.state_io import read_json, atomic_json
from test_scientific_judgment import observed_role_boundary
from test_scientific_judgment import FakeHost, prepare, campaign_for, cycle
from test_physics_review import run

class PresentedHost(FakeHost):
    """Use actual engine-free Host preparation; inject only the supplied role response."""
    def __init__(self,request_pages=None,modify=None):
        self.request_pages=request_pages;self.modify=modify;self.actual=[]
        super().__init__(mutate=self.enrich)
    def enrich(self,v,c):
        if 'context_read' not in c:return
        v.update(schema_version=2,context_request=None,citations=[{'artifact_id':'anchor_context_core','sha256':c['core_sha256'],'location':'/current_action/claim_scope'}])
        if self.request_pages is not None:
            v.update(kind='scientific_context_request',verdict=None,claim_scope=None,findings=[],closes=[],proposal=None,proposal_verdict=None,
                     context_request={'selections':[{**{'artifact_id':None,'section':None,'query':None},**a} for a in self.request_pages]},citations=[])
        if self.modify:self.modify(v,c)
    def execute(self,node,request,control):
        actual=agent_host.AgentHost.from_config({'type':'responses','endpoint':'https://example.invalid/v1/responses','max_request_bytes':2_000_000})
        prepared=actual.prepare_model_context(node,request)
        self.actual.append(deepcopy(prepared))
        result=super().execute(node,request,control)
        return actual._presented_result(result,prepared['context'])

def select(b,kind='artifact'):
    s,_=graph._load(Path(b['graph_root']))
    m=read_json(Path(s['nodes'][0]['packet']['path'])/'manifest.json')
    if kind=='index':return [{'kind':'index','section':'artifacts','offset':0,'max_bytes':1024,'query':''}]
    a=next(a for a in m['artifacts'] if a['id']=='public_case')
    return [{'kind':'artifact','artifact_id':a['id'],'offset':0,'max_bytes':65536}]

def requested(cycle,tmp_path,monkeypatch,*,campaign=True,reworks=1):
    camp=campaign_for(cycle,tmp_path,monkeypatch) if campaign else None
    kw={'campaign':camp,'experiment':'observed'} if camp else {}
    b=prepare(cycle,tmp_path/'initial','critic',max_context_reworks=reworks,evidence_pages=[],**kw)
    h=PresentedHost(select(b));j.execute_role(b,h)
    assert j.consume(cycle,b,allow_control=True)['value']['kind']=='scientific_context_request'
    return b,camp,h

def prepared_revision(binding,tmp_path,monkeypatch):
    captured={};actual=rc.revise_graph
    def retain(*args,**kwargs):captured.update(args=args,kwargs=kwargs)
    monkeypatch.setattr(rc,'revise_graph',retain)
    j.continue_role(binding,tmp_path/'prepared',allow_control=True)
    monkeypatch.setattr(rc,'revise_graph',actual)
    return captured['args'][2],captured['kwargs']

def test_actual_same_graph_requested_pages_campaign_then_vote(cycle,tmp_path,monkeypatch, observed_role_boundary):
    b,camp,first=requested(cycle,tmp_path,monkeypatch)
    before,gs=graph._load(Path(b['graph_root']));_,cs=rc._load(camp)
    ledger=deepcopy(cs['resource_ledger']);timing=deepcopy(cs['timing']);start=gs['started_epoch'];usage=deepcopy(gs['usage'])
    assert review.status(cycle)['state']=='awaiting_review' and not review._view(*review._read(cycle))['reviews']
    old=execution.file_hash(Path(b['request']['path']))
    fresh=j.continue_role(b,tmp_path/'followup',allow_control=True)
    assert fresh['graph_root']==b['graph_root'] and fresh['subject_sha256']!=b['subject_sha256']
    after,state=graph._load(Path(b['graph_root']));_,cstate=rc._load(camp)
    assert state['started_epoch']==start and state['usage']==usage and cstate['timing']==timing and cstate['resource_ledger']==ledger
    assert after['budget']==before['budget'] and state['reworks']==1
    with pytest.raises(ValueError,match='superseded context'):j.execute_role(b,PresentedHost())
    h=PresentedHost();j.execute_role(fresh,h);vote=j.consume(cycle,fresh,allow_control=True)
    assert vote['verdict']=='accept' and len(review._view(*review._read(cycle))['reviews'])==1
    _,final=rc._load(camp);assert final['resource_ledger']==ledger and final['graphs'][0]['usage']['calls']==2
    assert rc._usage(final)['calls']==2 and execution.file_hash(Path(b['request']['path']))==old
    packet=h.actual[0]['context']['review_packet']
    assert any(a['id']=='anchor_context_page0000' for a in packet['artifacts'])
    assert len(first.actual)==len(h.actual)==1

def test_advance_retains_nonvoting_request_once(cycle,tmp_path):
    def nonvote(v,c):v.update(kind='scientific_evidence_request',verdict=None,claim_scope=None,findings=[],closes=[])
    result=j.advance(cycle,tmp_path/'advance',host=FakeHost(mutate=nonvote),model='control',reasoning_effort='high',max_output_tokens=1024,
                     max_wall_seconds=20,claim_scope='reproduction',allow_control=True)
    assert result['phase']=='retained_evidence_requested' and result['execution_authorized'] is False
    assert len(list((tmp_path/'advance').rglob('graph_state.json')))==1 and not review._view(*review._read(cycle))['reviews']

@pytest.mark.parametrize('campaign',[False,True])
def test_initial_selected_pages_presented_without_followup(cycle,tmp_path,monkeypatch,campaign, observed_role_boundary):
    camp=campaign_for(cycle,tmp_path,monkeypatch) if campaign else None
    kw={'campaign':camp,'experiment':'observed'} if camp else {}
    b=prepare(cycle,tmp_path/'role','critic',evidence_pages=[{'kind':'index','section':'artifacts','offset':0,'max_bytes':1024,'query':''}],**kw)
    host=PresentedHost();j.execute_role(b,host);assert j.consume(cycle,b,allow_control=True)['verdict']=='accept'
    c=j._read_pin(b['request']);assert c['context_read']['used_pages']==1

@pytest.mark.parametrize('defect',['selection','head','allowance'])
def test_current_request_only_and_original_allowance(cycle,tmp_path,monkeypatch,defect):
    b,camp,h=requested(cycle,tmp_path,monkeypatch,reworks=0 if defect=='allowance' else 1)
    out=tmp_path/'followup'
    if defect=='head':
        # A recorded vote moves the journal head; a declared name would only be retained advice.
        from bound_review import bound_review
        bound_review(cycle,role='skeptical_verifier',verdict='accept',summary='Supplied different judgment',claim_scope='reproduction')
    with pytest.raises(ValueError):j.continue_role(b,out,allow_control=True,**({'selections':select(b,'index')} if defect=='selection' else {}))
    assert not out.exists()

@pytest.mark.parametrize('mutation',['schema','model','calls','inputs','actor','parent'])
def test_shared_revision_refuses_scientific_or_budget_replacement(cycle,tmp_path,monkeypatch,mutation):
    b,camp,_=requested(cycle,tmp_path,monkeypatch);old,state=graph._load(Path(b['graph_root']));new=deepcopy(old)
    new['nodes'][0]['parameters']['instructions']+=' Read the exact same bounded packet.'
    if mutation=='schema':new['nodes'][0]['parameters']['output_schema']=None
    elif mutation=='model':new['nodes'][0]['parameters']['model']='foreign'
    elif mutation=='calls':new['budget']['max_calls']+=1
    elif mutation=='inputs':new['nodes'][0]['inputs']=[{'id':'x','path':b['request']['path'],'sha256':b['request']['sha256']}]
    elif mutation=='actor':new['nodes'][0]['role']='verifier'
    else:new['goal_binding']={'foreign':True}
    before=execution.file_hash(Path(camp)/'head.json')
    with pytest.raises(ValueError):rc.revise_graph(camp,b['graph_root'],new,expected_spec_sha256=execution.digest(old),
        predecessor_result_pin=rc._pin(Path(b['graph_root'])/state['nodes']['critic']['result']['path']),reason='supplied malformed revision')
    assert execution.file_hash(Path(camp)/'head.json')==before and graph.status(b['graph_root'])['spec_sha256']==execution.digest(old)

def test_raw_graph_revise_cannot_bypass_campaign_reservation(cycle,tmp_path,monkeypatch):
    b,camp,_=requested(cycle,tmp_path,monkeypatch);spec,state=graph._load(Path(b['graph_root']));spec['nodes'][0]['parameters']['instructions']+=' raw revise'
    graph.revise(b['graph_root'],spec,reason='unadmitted pure witness')
    with pytest.raises(ValueError,match='exact admitted'):rc.execute_graph(camp,b['graph_root'],spec,PresentedHost(),prepared=True)
    assert graph.status(b['graph_root'])['usage']['calls']==1

@pytest.mark.parametrize('interruption',['before_graph','after_graph'])
def test_exact_interrupted_pair_recovery_retains_clock_and_ceiling(cycle,tmp_path,monkeypatch,interruption):
    b,camp,_=requested(cycle,tmp_path,monkeypatch);old,state=graph._load(Path(b['graph_root']));new,kwargs=prepared_revision(b,tmp_path,monkeypatch)
    original_revise=graph.revise;original_commit=rc._commit
    if interruption=='before_graph':monkeypatch.setattr(graph,'revise',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('injected pre-Graph interruption')))
    else:
        def stop(root,state,event,**payload):
            if event=='ordinary_graph_revision_admitted':raise RuntimeError('injected post-Graph interruption')
            return original_commit(root,state,event,**payload)
        monkeypatch.setattr(rc,'_commit',stop)
    with pytest.raises(RuntimeError):rc.revise_graph(camp,b['graph_root'],new,**kwargs)
    monkeypatch.setattr(graph,'revise',original_revise);monkeypatch.setattr(rc,'_commit',original_commit)
    _,pending=rc._load(camp);ledger=deepcopy(pending['resource_ledger']);timing=deepcopy(pending['timing'])
    with pytest.raises(ValueError,match='pending'):rc.validate_graph_reservation(pending,b['graph_root'],graph._load(Path(b['graph_root']))[0])
    with pytest.raises(ValueError,match='same exact pair'):rc.revise_graph(camp,b['graph_root'],new,**{**kwargs,'reason':'foreign pair'})
    rc.revise_graph(camp,b['graph_root'],new,**kwargs)
    _,admitted=rc._load(camp);gs=graph._load(Path(b['graph_root']))[1]
    assert admitted['resource_ledger']==ledger and admitted['timing']==timing and gs['started_epoch']==state['started_epoch'] and gs['usage']==state['usage']
    assert gs['graph_revision']==1 and gs['reworks']==1
    rc.validate_graph_reservation(admitted,b['graph_root'],new)

@pytest.mark.parametrize('defect',['missing_page','index_citation','wrong_content'])
def test_latest_presentation_and_content_citation_guard(cycle,tmp_path,monkeypatch,defect, observed_role_boundary):
    b,_,_=requested(cycle,tmp_path,monkeypatch,campaign=False)
    if defect=='index_citation':
        # Reproduce a real index-page request; the original role request must be rerun from a separate fresh Graph.
        b=prepare(cycle,tmp_path/'indexinitial','critic',max_context_reworks=1)
        j.execute_role(b,PresentedHost(select(b,'index')))
    fresh=j.continue_role(b,tmp_path/'followup',allow_control=True)
    def change(v,c):
        if defect=='index_citation':v['citations']=[{'artifact_id':c['context_read']['presented_pages'][0]['id'],'sha256':c['context_read']['presented_pages'][0]['sha256'],'location':'/entries'}]
        elif defect=='wrong_content':v['citations'][0]['sha256']='a'*64
    host=PresentedHost(modify=change)
    if defect=='missing_page':
        original=agent_host.AgentHost._presented_result
        def omit(result,context):
            result=original(result,context);c=j._read_pin(fresh['request']);result['isolation']['evidence_presentation']['presented_subject_sha256s'].remove(c['context_read']['presented_pages'][0]['sha256']);return result
        monkeypatch.setattr(agent_host.AgentHost,'_presented_result',staticmethod(omit))
    j.execute_role(fresh,host)
    with pytest.raises(ValueError):j.consume(cycle,fresh,allow_control=True)
    assert not review._view(*review._read(cycle))['reviews']

@pytest.mark.parametrize('selection',[
    {'kind':'artifact','artifact_id':'../foreign','offset':0,'max_bytes':1024},
    {'kind':'artifact','artifact_id':'public_case','offset':-1,'max_bytes':1024},
    {'kind':'artifact','artifact_id':'public_case','offset':0,'max_bytes':65537},
])
def test_page_bounds_and_foreign_identifiers_refuse(cycle,tmp_path,selection):
    with pytest.raises(ValueError):prepare(cycle,tmp_path/'role','critic',evidence_pages=[selection])

def test_complete_original_role_projection_retained(cycle,tmp_path,monkeypatch):
    b,_,_=requested(cycle,tmp_path,monkeypatch,campaign=False)
    fresh=j.continue_role(b,tmp_path/'followup',allow_control=True)
    contract=j._read_pin(fresh['request']);origin=j._read_pin(contract['context_read']['origin_manifest'])
    spec,_=graph._load(Path(b['graph_root']));new=review_context.verify_packet(spec['nodes'][0]['packet']['path'],expected_manifest_sha256=fresh['context_manifest_sha256'])
    from collections import Counter
    assert not Counter(a['sha256'] for a in origin['artifacts'])-Counter(a['sha256'] for a in new['artifacts'])
    assert contract['context_read']['predecessor']['result']['size']>0


def test_interrupted_actual_graph_spec_state_pair_recovers_exactly(cycle,tmp_path,monkeypatch):
    b,camp,_=requested(cycle,tmp_path,monkeypatch);old,state=graph._load(Path(b['graph_root']));new,kwargs=prepared_revision(b,tmp_path,monkeypatch)
    original=graph._save
    monkeypatch.setattr(graph,'_save',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('injected state write interruption')))
    with pytest.raises(RuntimeError):rc.revise_graph(camp,b['graph_root'],new,**kwargs)
    monkeypatch.setattr(graph,'_save',original)
    with pytest.raises(graph.GraphError):graph._load(Path(b['graph_root']))
    rc.revise_graph(camp,b['graph_root'],new,**kwargs)
    actual,checkpoint=graph._load(Path(b['graph_root']));assert actual==new
    assert checkpoint['usage']==state['usage'] and checkpoint['started_epoch']==state['started_epoch'] and checkpoint['reworks']==1
    _,current=rc._load(camp);rc.validate_graph_reservation(current,b['graph_root'],actual)

@pytest.mark.parametrize('campaign',[False,True])
def test_direct_common_request_admission_and_arbitrary_instructions_refuse(cycle,tmp_path,monkeypatch,campaign):
    b,camp,_=requested(cycle,tmp_path,monkeypatch,campaign=campaign)
    old,state=graph._load(Path(b['graph_root']));new,kwargs=prepared_revision(b,tmp_path,monkeypatch)
    foreign=deepcopy(new);foreign['nodes'][0]['parameters']['instructions']+=' unauthorized instructions'
    with pytest.raises(ValueError,match='instructions'):rc.revise_graph(camp,b['graph_root'],foreign,**kwargs)
    assert graph._load(Path(b['graph_root']))[0]==old
    rc.revise_graph(camp,b['graph_root'],new,**kwargs)
    assert graph._load(Path(b['graph_root']))[0]==new

@pytest.mark.parametrize('campaign',[False,True])
def test_direct_common_vote_cannot_authorize_context_revision(cycle,tmp_path,monkeypatch,campaign):
    camp=campaign_for(cycle,tmp_path,monkeypatch) if campaign else None
    b=prepare(cycle,tmp_path/'initial','critic',max_context_reworks=1,**({'campaign':camp,'experiment':'observed'} if camp else {}))
    j.execute_role(b,PresentedHost());old,state=graph._load(Path(b['graph_root']));new=deepcopy(old)
    new['nodes'][0]['parameters']['instructions']+=' no real request'
    with pytest.raises(ValueError,match='nonvoting context request'):
        rc.revise_graph(camp,b['graph_root'],new,expected_spec_sha256=graph.digest(old),predecessor_result_pin=rc._pin(Path(b['graph_root'])/state['nodes']['critic']['result']['path']),reason='not authority')
    assert graph._load(Path(b['graph_root']))[0]==old

@pytest.mark.parametrize('field',['expected_spec_sha256','expected_state_sha256'])
def test_canonical_graph_fence_refuses_stale_snapshot(cycle,tmp_path,monkeypatch,field):
    b,_,_=requested(cycle,tmp_path,monkeypatch,campaign=False)
    old,state=graph._load(Path(b['graph_root']));new=deepcopy(old);new['nodes'][0]['parameters']['instructions']+=' legacy change'
    with pytest.raises(graph.GraphError,match='superseded'):graph.revise(b['graph_root'],new,reason='exact source fence',**{field:'a'*64})
    assert graph._load(Path(b['graph_root']))==(old,state)

@pytest.mark.parametrize('campaign',[False,True])
def test_concurrent_rework_after_authorization_refuses_under_graph_lock(cycle,tmp_path,monkeypatch,campaign):
    b,camp,_=requested(cycle,tmp_path,monkeypatch,campaign=campaign)
    new,kwargs=prepared_revision(b,tmp_path,monkeypatch)
    original=graph.revise
    def supersede(root,spec,**fences):
        graph.rework(root,['critic'],reason='superseded before locked admission')
        return original(root,spec,**fences)
    monkeypatch.setattr(graph,'revise',supersede)
    with pytest.raises(graph.GraphError,match='superseded'):rc.revise_graph(camp,b['graph_root'],new,**kwargs)
    assert graph._load(Path(b['graph_root']))[0]!=new

def test_shared_admission_recomputes_requested_page_bytes(cycle,tmp_path,monkeypatch):
    b,camp,_=requested(cycle,tmp_path,monkeypatch)
    old,state=graph._load(Path(b['graph_root']));new,kwargs=prepared_revision(b,tmp_path,monkeypatch)
    packet=Path(new['nodes'][0]['packet']['path']);manifest=read_json(packet/'manifest.json')
    row=next(a for a in manifest['artifacts'] if a['id']=='anchor_context_page0000')
    page=read_json(packet/row['path']);page['content']='foreign page content'
    atomic_json(packet/row['path'],page);row['sha256']=execution.file_hash(packet/row['path'])
    manifest['sha256']=execution.digest({k:v for k,v in manifest.items() if k!='sha256'});atomic_json(packet/'manifest.json',manifest)
    new['nodes'][0]['packet']['manifest_sha256']=manifest['sha256']
    head=execution.file_hash(Path(camp)/'head.json')
    with pytest.raises(ValueError,match='exact requested projected source'):rc.revise_graph(camp,b['graph_root'],new,**kwargs)
    assert graph._load(Path(b['graph_root']))==(old,state) and execution.file_hash(Path(camp)/'head.json')==head


def test_admitted_chain_read_revalidates_original_authorization(cycle,tmp_path,monkeypatch):
    b,camp,_=requested(cycle,tmp_path,monkeypatch)
    new,kwargs=prepared_revision(b,tmp_path,monkeypatch);rc.revise_graph(camp,b['graph_root'],new,**kwargs)
    _,state=rc._load(camp);rc.validate_graph_reservation(state,b['graph_root'],new)
    pending=next(e for e in state['events'] if e['kind']=='ordinary_graph_revision_pending')
    changed=deepcopy(state)
    next(e for e in changed['events'] if e['kind']=='ordinary_graph_revision_pending')['admission']['authorization']['selected_pages']+=1
    with pytest.raises(ValueError,match='authorization'):rc.validate_graph_reservation(changed,b['graph_root'],new)
    assert pending['admission']['authorization']['selected_pages']==1


def test_pending_recovery_revalidates_requested_page_bytes(cycle,tmp_path,monkeypatch):
    b,camp,_=requested(cycle,tmp_path,monkeypatch);new,kwargs=prepared_revision(b,tmp_path,monkeypatch)
    original=graph.revise;monkeypatch.setattr(graph,'revise',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('retained pending')))
    with pytest.raises(RuntimeError):rc.revise_graph(camp,b['graph_root'],new,**kwargs)
    monkeypatch.setattr(graph,'revise',original)
    packet=Path(new['nodes'][0]['packet']['path']);manifest=read_json(packet/'manifest.json')
    row=next(a for a in manifest['artifacts'] if a['id']=='anchor_context_page0000')
    (packet/row['path']).write_bytes(b'foreign retained page')
    with pytest.raises(ValueError):rc.revise_graph(camp,b['graph_root'],new,**kwargs)
    assert graph._load(Path(b['graph_root']))[0]!=new


def mutate_explicit_presentation(result,contract,defect):
    obs=result['isolation'].get('evidence_presentation')
    if defect=='missing':result['isolation'].pop('evidence_presentation')
    elif defect=='malformed':result['isolation']['evidence_presentation']=None
    elif defect=='bad_digests':obs['presented_subject_sha256s']=['not-a-digest']
    elif defect=='deferred':obs['deferred_content_read']=True
    else:
        required=contract['core_sha256'] if defect=='missing_core' else contract['context_read']['presented_pages'][0]['sha256']
        obs['presented_subject_sha256s'].remove(required)


@pytest.mark.parametrize('defect',['missing','malformed','bad_digests','deferred','missing_core','missing_page'])
def test_final_opt_in_consume_requires_explicit_core_and_page_observation(cycle,tmp_path,monkeypatch,defect, observed_role_boundary):
    b=prepare(cycle,tmp_path/'initial','critic',max_context_reworks=1,evidence_pages=[{'kind':'index','section':'artifacts','offset':0,'max_bytes':1024,'query':''}])
    original=agent_host.AgentHost._presented_result
    def omitted(result,context):
        result=original(result,context);mutate_explicit_presentation(result,j._read_pin(b['request']),defect);return result
    monkeypatch.setattr(agent_host.AgentHost,'_presented_result',staticmethod(omitted))
    j.execute_role(b,PresentedHost())
    with pytest.raises(ValueError):j.consume(cycle,b,allow_control=True)
    assert not review._view(*review._read(cycle))['reviews']


@pytest.mark.parametrize('defect',['missing','malformed','bad_digests','deferred','missing_core','missing_page'])
def test_direct_common_prior_request_requires_explicit_core_and_page_observation(cycle,tmp_path,monkeypatch,defect):
    camp=campaign_for(cycle,tmp_path,monkeypatch)
    b=prepare(cycle,tmp_path/'initial','critic',max_context_reworks=1,evidence_pages=[{'kind':'index','section':'artifacts','offset':0,'max_bytes':1024,'query':''}],campaign=camp,experiment='observed')
    j.execute_role(b,PresentedHost(select(b)))
    new,kwargs=prepared_revision(b,tmp_path,monkeypatch)
    root=Path(b['graph_root']);old,state=graph._load(root);ref=state['nodes']['critic']['result'];path=root/ref['path'];saved=read_json(path)
    mutate_explicit_presentation(saved['result'],j._read_pin(b['request']),defect)
    atomic_json(path,saved);ref['sha256']=graph.digest(saved);ref['result_sha256']=graph.digest(saved['result']);graph._save(root,state)
    kwargs['predecessor_result_pin']=rc._pin(path)
    head=execution.file_hash(Path(camp)/'head.json')
    with pytest.raises(ValueError):rc.revise_graph(camp,root,new,**kwargs)
    assert graph._load(root)[0]==old and execution.file_hash(Path(camp)/'head.json')==head
