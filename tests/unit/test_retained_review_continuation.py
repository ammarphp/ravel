"""Actual API/custody shapes; synthetic calls and execution only, no native/model."""
from pathlib import Path
from copy import deepcopy
import json, hashlib
import pytest
from ravel.workflow import scientific_judgment as j, physics_review as review, retained_science_review as retained
from ravel.workflow import execution, agent_graph as graph, agent_host, review_context
from ravel.workflow.state_io import atomic_json, read_json
from review_continuation_fixture import closed
from test_provider_transport import install_http, document, capabilities

@pytest.fixture(autouse=True)
def inert(monkeypatch):
    monkeypatch.setattr(execution.platform,'platform',lambda:'synthetic-source-control-platform')

def prepare(root,out,*,retained_study=True,action='model'):
    return j.prepare_role(root,out,role='critic',actor_id='critic',model='synthetic',reasoning_effort='high',max_output_tokens=2048,max_wall_seconds=120,
        claim_scope='provider_readiness',action=action,retained_study=retained_study)

def public_value(binding,verdict='accept'):
    c=j._read_pin(binding['request']);case=read_json(c['case_pin']['path'])
    v={'schema_version':1,'kind':'scientific_review','subject_sha256':binding['subject_sha256'],'verdict':verdict,
       'summary':'Explicit synthetic fixture; not an actual scientific verdict.','findings':[],'closes':[],
       'claim_scope':c['claim_scope'] if verdict=='accept' else None,
       'audit':{'case_sha256':execution.digest(case),'nodes':[{'id':n['id'],'decision':'supported','reason':'Synthetic located evidence',
          'assumptions':[{'disposition':'accepted','reason':'Synthetic applicability'} for _ in n['assumptions']]} for n in case['nodes']],
          'edges':[{'parent':e['parent'],'child':e['child'],'decision':'supported','reason':'Synthetic edge evidence'} for e in case['edges']]},
       'proposal':None,'proposal_verdict':None}
    if verdict=='send_back':
        v['findings']=[{'id':'synthetic-need-work','summary':'Synthetic recomputation required',
            'evidence':[{'path':'outputs/attempt-1/result.json','location':'$.value'}],
            'check_ids':['agreement'],'required_paths':[],'required_stages':['science']}]
    if verdict=='evidence':
        v.update(kind='scientific_evidence_request',verdict=None,claim_scope=None,summary='Provide bounded retained input snapshot witness; no native redo requested.')
        v['audit']['nodes'][0].update(decision='unresolved',reason='Located retained-byte evidence missing')
    return v

def external(binding,out,value):
    prepared=graph.prepare_external(binding['graph_root'],'critic')
    response={k:prepared[k] for k in ('request_id','request_sha256')}
    response.update(schema_version=1,invocation_id='synthetic-explicit-inert-invocation',actor_id='synthetic-host-critic',observed_model='inert fixture, no actual call',fresh_context=True,parent_transcript_supplied=False,value=value)
    path=out/'response.json';atomic_json(path,response)
    graph.deliver_external(binding['graph_root'],'critic',path)
    return prepared

def local_host():
    return agent_host.AgentHost(adapter='chat_completions',endpoint='http://127.0.0.1:8000/v1/chat/completions',
        privacy='local_only',local_models=['synthetic'],capabilities=capabilities(max_output_tokens=2048))

def wire_record(binding,value):
    # The HTTP transports carry a conditional public record nested under one object.
    schema=read_json(Path(binding['graph_root'])/graph.SPEC)['nodes'][0]['parameters']['output_schema']
    return {'public_record':value} if 'anyOf' in schema else value

def observed(binding,value,monkeypatch):
    """Dispatch a prepared role through the provider host on its local-only route.

    Only the socket is replaced: it answers with `value` as one structured tool call. Host,
    Graph and receipt reader are the production code, so the receipt is observed and separated
    by their own rules. No model runs and the public value stays an explicit synthetic fixture.
    """
    seen=install_http(monkeypatch,document('chat_completions',wire_record(binding,value)))
    state=j.execute_role(binding,local_host())
    assert state['complete'] and state['usage']['calls']==1 and len(seen)==1,state['nodes'][binding['node_id']]
    receipt=graph.role_receipt(binding['graph_root'],binding['node_id'],expected_subject_sha256=binding['subject_sha256'],
        expected_packet_sha256=binding['context_manifest_sha256'],require_exact_subject=True)
    assert receipt['public_value']==value
    assert receipt['execution_observation']=='local_transport_observed' and receipt['attestation']=='transport_attested'
    assert receipt['context_transport_separated'] and not receipt['scientific_independence_proven']
    return seen

@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
@pytest.mark.parametrize('drift',[None,'source','extra-source'])
def test_retained_role_dispatch_checks_retained_custody_not_the_current_inventory(closed,tmp_path,monkeypatch,drift):
    # The ordinary route refuses this study because the framework inventory moved on; its
    # prepared role is dispatched under the retained custody its request records.
    with pytest.raises(ValueError,match='inventory changed'):j._live(closed.root)
    b=prepare(closed.root,tmp_path/'dispatch')
    assert 'retained_study' in j._read_pin(b['request'])
    if drift is None:
        observed(b,public_value(b),monkeypatch)
        assert j.consume(closed.root,b)['verdict']=='accept'
        return
    if drift=='source':(closed.package/'_bootstrap.py').write_text('changed')
    else:(closed.package/'unbound.py').write_text('not captured')
    seen=install_http(monkeypatch,document('chat_completions',wire_record(b,public_value(b))))
    with pytest.raises((ValueError,OSError)) as refusal:j.execute_role(b,local_host())
    assert 'inventory changed' not in str(refusal.value)
    assert seen==[] and graph.status(b['graph_root'])['usage']['calls']==0

@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
@pytest.mark.parametrize('verdict',['accept','send_back','evidence'])
def test_cross_epoch_actual_api_prepare_external_deliver_consume(closed,tmp_path,monkeypatch,verdict):
    with pytest.raises(ValueError,match='inventory changed'): j.prepare_role(closed.root,tmp_path/'old-route',role='critic',actor_id='critic',model='synthetic',reasoning_effort='high',max_output_tokens=2048,max_wall_seconds=120,claim_scope='provider_readiness')
    # A relayed response is retained and charged, and it never enters the journal: a relay is
    # self-attested, so its vote is advisory and its nonvoting request is not an observed transport.
    relay=prepare(closed.root,tmp_path/'relayed',action='external');external(relay,tmp_path,public_value(relay,verdict))
    assert graph.status(relay['graph_root'])['usage']['calls']==1
    refusal='fresh observed role transport required' if verdict=='evidence' else 'self-attested review is advisory; it does not count as independent'
    for options in ({},{'allow_control':True}):
        with pytest.raises(ValueError,match=refusal):j.consume(closed.root,relay,**options)
    assert len(review._read(closed.root)[1])==1 and graph.status(relay['graph_root'])['usage']['calls']==1
    b=prepare(closed.root,tmp_path/'continued');observed(b,public_value(b,verdict),monkeypatch)
    before=graph.status(b['graph_root'])['usage']['calls']
    result=j.consume(closed.root,b)
    assert before==graph.status(b['graph_root'])['usage']['calls']==1
    reg,events=review._read(closed.root);view=review._view(reg,events)
    if verdict=='evidence':
        assert result['execution_authorized'] is False and view['reviews']==[] and view['state']=='awaiting_review'
        fresh=prepare(closed.root,tmp_path/'after-evidence');assert graph.status(fresh['graph_root'])['usage']['calls']==0
    else:
        assert result['verdict']==verdict and len(result['supporting_artifacts'])<512
        assert len([p for p in result['supporting_artifacts'] if p.get('kind')=='role_context'])==1
        with pytest.raises(ValueError,match='role already decided'):prepare(closed.root,tmp_path/'overwrite')
        review._judgments_live(closed.root,view)

@pytest.mark.skipif(__import__('os').environ.get('RAVEL_FULL_CONTEXT_CONTROL') != '180s_explicitly_allocated', reason='Full >9700-member source control needs a separately allotted outer180s worker; default bounded population only')
@pytest.mark.parametrize('closed',['awaiting_many'],indirect=True)
def test_full_more9700_index_empty_sources_real_external_consume(closed,tmp_path):
    b=prepare(closed.root,tmp_path/'many')
    spec=read_json(Path(b['graph_root'])/graph.SPEC);packet=Path(spec['nodes'][0]['packet']['path']);m=read_json(packet/'manifest.json')
    assert 9700<len(m['artifacts'])<=10000
    zeros=[a for a in m['artifacts'] if (packet/a['path']).stat().st_size==0]
    assert len(zeros)==3 and all(a['projection']=='exact bytes' for a in zeros)
    external(b,tmp_path,public_value(b))
    result=j.consume(closed.root,b)
    assert len(result['supporting_artifacts'])<512
    reg,events=review._read(closed.root);view=review._view(reg,events)
    review._judgments_live(closed.root,view)
    copy=packet/m['artifacts'][0]['path'];copy.write_bytes(copy.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='changed'):review._judgments_live(closed.root,view)

@pytest.mark.parametrize('verdict',['send_back','stop'])
@pytest.mark.parametrize('bad',['scope','closes'])
def test_conditional_schema_refuses_nonaccept_scope_or_closes(verdict,bad):
    schema=j.output_schema();agent_host._schema(schema)
    value={k:None for k in schema['properties']};value.update(schema_version=1,kind='scientific_review',subject_sha256='a'*64,verdict=verdict,summary='Synthetic negative format',findings=[],closes=[])
    value['claim_scope']='diagnostic' if bad=='scope' else None
    if bad=='closes':value['closes']=['invented']
    with pytest.raises(agent_host.HostFailure,match='conditional'):agent_host.validate_public_result(value,schema)

@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
@pytest.mark.parametrize('which',['source','approval','missing-source','extra-source'])
def test_original_pending_source_and_authority_changes_refused(closed,which):
    if which=='source':(closed.package/'_bootstrap.py').write_text('changed')
    elif which=='approval':(closed.root/'inputs/science-approval.json').write_text('{}')
    elif which=='missing-source':(closed.package/'_bootstrap.py').unlink()
    else:(closed.package/'unbound.py').write_text('not captured')
    with pytest.raises((ValueError,OSError)):retained.pending(closed.root)

@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
def test_late_original_input_drift_refuses_before_journal(closed,tmp_path,monkeypatch):
    b=prepare(closed.root,tmp_path/'late');observed(b,public_value(b),monkeypatch)
    real=review._supporting
    def late(root,values,**kwargs):
        result=real(root,values,**kwargs)
        closed.metadata.write_text('late input change')
        return result
    monkeypatch.setattr(review,'_supporting',late)
    with pytest.raises(ValueError,match='changed'):j.consume(closed.root,b)
    assert len(review._read(closed.root)[1])==1

@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
def test_empty_control_is_not_allowed_by_source_copy_exception(closed,tmp_path):
    b=prepare(closed.root,tmp_path/'control-empty');spec=read_json(Path(b['graph_root'])/graph.SPEC)
    packet=Path(spec['nodes'][0]['packet']['path']);m=read_json(packet/'manifest.json')
    entry=next(a for a in m['artifacts'] if a['id']=='judgment_request');(packet/entry['path']).write_bytes(b'')
    entry['sha256']=hashlib.sha256(b'').hexdigest();m['sha256']=execution.digest({k:v for k,v in m.items() if k!='sha256'});atomic_json(packet/'manifest.json',m)
    _,_,_,view=j._live(closed.root,retained_study=True)
    pin={'kind':'role_context',**j._pin(packet/'manifest.json'),'manifest_sha256':m['sha256'],'cycle_id':view['cycle']['cycle_id'],'cycle_sha256':view['cycle']['sha256']}
    with pytest.raises(ValueError,match='SOURCE'):review._supporting(closed.root,[pin])

def test_original_cap_unchanged():
    with pytest.raises(ValueError,match='bounded supporting'):review._supporting(Path('/not-used'),[{}]*513)


@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
@pytest.mark.parametrize('mode',['bytes','aba','member'])
def test_final_retained_submission_holds_generated_context_copies(closed,tmp_path,monkeypatch,mode):
    b=prepare(closed.root,tmp_path/'role');observed(b,public_value(b),monkeypatch)
    spec=read_json(Path(b['graph_root'])/graph.SPEC);packet=Path(spec['nodes'][0]['packet']['path']);m=read_json(packet/'manifest.json')
    copy=packet/m['artifacts'][0]['path'];before=copy.read_bytes();original=review._supporting
    def late(root,pins,**kwargs):
        out=original(root,pins,**kwargs)
        if kwargs.get('_session') is not None:
            if mode=='member':(packet/'artifacts/unindexed.txt').write_text('late member')
            else:
                copy.write_bytes(before+b'late')
                if mode=='aba':copy.write_bytes(before)
        return out
    monkeypatch.setattr(review,'_supporting',late)
    with pytest.raises(ValueError,match='changed'):j.consume(closed.root,b)
    assert len(review._read(closed.root)[1])==1

@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
@pytest.mark.parametrize('which',['foreign_cycle','wrong_raw','wrong_canonical','extra_member'])
def test_aggregate_context_complete_identity_refusals(closed,tmp_path,which):
    b=prepare(closed.root,tmp_path/'role');spec=read_json(Path(b['graph_root'])/graph.SPEC);packet=Path(spec['nodes'][0]['packet']['path']);m=read_json(packet/'manifest.json')
    _,_,_,v=j._live(closed.root,retained_study=True)
    p={'kind':'role_context',**j._pin(packet/'manifest.json'),'manifest_sha256':m['sha256'],'cycle_id':v['cycle']['cycle_id'],'cycle_sha256':v['cycle']['sha256']}
    if which=='foreign_cycle':p['cycle_id']='foreign'
    elif which=='wrong_raw':p['sha256']='0'*64
    elif which=='wrong_canonical':p['manifest_sha256']='0'*64
    else:(packet/'artifacts/unindexed.txt').write_text('unindexed')
    with pytest.raises(ValueError):review._supporting(closed.root,[p])

@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
def test_aggregate_oversize_manifest_refuses_before_any_content_open(closed,tmp_path,monkeypatch):
    b=prepare(closed.root,tmp_path/'role');spec=read_json(Path(b['graph_root'])/graph.SPEC);packet=Path(spec['nodes'][0]['packet']['path']);manifest=packet/'manifest.json';m=read_json(manifest)
    _,_,_,v=j._live(closed.root,retained_study=True)
    p={'kind':'role_context',**j._pin(manifest),'manifest_sha256':m['sha256'],'cycle_id':v['cycle']['cycle_id'],'cycle_sha256':v['cycle']['sha256']}
    with manifest.open('ab') as f:f.truncate(16*1024**2+1)
    original=Path.open;reads=[]
    def observe(path,*args,**kwargs):
        mode=args[0] if args else kwargs.get('mode','r')
        if path==manifest and 'r' in mode:reads.append(mode)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',observe)
    with pytest.raises(ValueError,match='bounded'):review._supporting(closed.root,[p])
    assert reads==[]

@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
def test_all_actual_api_roles_preserve_aggregate_support_and_scoped_closure(closed,tmp_path,monkeypatch):
    for role,actor in [('critic','critic'),('verifier','skeptic'),('synthesizer','decider')]:
        b=j.prepare_role(closed.root,tmp_path/role,role=role,actor_id=actor,model='synthetic',reasoning_effort='high',max_output_tokens=2048,max_wall_seconds=120,claim_scope='provider_readiness',retained_study=True)
        observed(b,public_value(b),monkeypatch)
        event=j.consume(closed.root,b)
        assert event['role']==j.ROLE[role] and graph.status(b['graph_root'])['usage']['calls']==1
        assert any(p.get('kind')=='role_context' for p in event['supporting_artifacts'])
    reg,events=review._read(closed.root)
    assert review._view(reg,events)['state']=='accepted'
    with pytest.raises(ValueError,match='pending review'):j._live(closed.root,retained_study=True)
    with pytest.raises(ValueError,match='inventory changed'):
        from ravel.workflow import science
        science.verify_plan(closed.root,approved=True)
    review._judgments_live(closed.root,review._view(reg,events))
    paths=review.bound_paths(closed.root)
    assert all(Path(p).is_file() for p in paths)
    assert len([p for p in paths if '/context/artifacts/' in p])>0

@pytest.mark.parametrize('mode',['bytes','aba','member','symlink'])
def test_nested_final_observation_closes_original_file_and_membership(tmp_path,monkeypatch,mode):
    root=tmp_path/'minimal';root.mkdir();data=root/'source';data.mkdir();leaf=data/'evidence.txt';leaf.write_text('original')
    session=execution._validation_session(root)
    session.regular_file(str(leaf),root);session.snapshot([str(data)])
    def late():
        if mode=='member':(data/'new.txt').write_text('late')
        elif mode=='symlink':
            saved=root/'saved.txt';saved.write_bytes(leaf.read_bytes());leaf.unlink();leaf.symlink_to(saved)
        else:
            leaf.write_text('changed')
            if mode=='aba':leaf.write_text('original')
    session.retain_final_check(late)
    errors=session.finish()
    assert errors and ('changed' in errors[0] or 'symlink' in errors[0])

@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
def test_real_consume_closes_original_input_after_nested_context_finish(closed,tmp_path,monkeypatch):
    b=prepare(closed.root,tmp_path/'nested-role');observed(b,public_value(b),monkeypatch)
    supporting=review._supporting
    def append_late(root,values,**kwargs):
        result=supporting(root,values,**kwargs)
        session=kwargs.get('_session')
        if session is not None:session.retain_final_check(lambda:closed.metadata.write_text('late after context finish'))
        return result
    monkeypatch.setattr(review,'_supporting',append_late)
    with pytest.raises(ValueError,match='changed'):j.consume(closed.root,b)
    assert len(review._read(closed.root)[1])==1


@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
def test_retained_evidence_only_case_anchors_enter_actual_external_presentation(closed,tmp_path,monkeypatch):
    original=prepare(closed.root,tmp_path/'initial-unexecuted')
    contract=j._read_pin(original['request']);case=read_json(contract['case_pin']['path'])
    witness=tmp_path/'bounded-custody-witness.json'
    atomic_json(witness,{'kind':'explicit synthetic retained-custody extract','source_sha256':execution.file_hash(closed.metadata),'observation':'one SHA pass, no physics qualification'})
    case['nodes'][0]['anchors'].append({'kind':'measurement','artifact':j._pin(witness),'format':'json','location':'','value':read_json(witness)})
    case_path=tmp_path/'bounded-case.json';atomic_json(case_path,case)
    b=j.prepare_role(closed.root,tmp_path/'evidence-role',role='critic',actor_id='critic',model='synthetic',reasoning_effort='high',max_output_tokens=2048,max_wall_seconds=120,claim_scope='provider_readiness',case_pin=j._pin(case_path),action='external',retained_study=True)
    prepared=external(b,tmp_path,public_value(b,'evidence'))
    presented=read_json(prepared['request_file'])['context']['review_packet']['artifacts']
    assert any('explicit synthetic retained-custody extract' in row['content'] for row in presented)
    # The relayed request is charged and stays outside the journal: a relay is not an observed transport.
    for options in ({},{'allow_control':True}):
        with pytest.raises(ValueError,match='fresh observed role transport required'):j.consume(closed.root,b,**options)
    assert graph.status(b['graph_root'])['usage']['calls']==1 and len(review._read(closed.root)[1])==1
    o=j.prepare_role(closed.root,tmp_path/'observed-evidence-role',role='critic',actor_id='critic',model='synthetic',reasoning_effort='high',max_output_tokens=2048,max_wall_seconds=120,claim_scope='provider_readiness',case_pin=j._pin(case_path),retained_study=True)
    seen=observed(o,public_value(o,'evidence'),monkeypatch)
    assert 'explicit synthetic retained-custody extract' in json.dumps(seen[0]['body'])
    value=j.consume(closed.root,o)
    assert value['value']['kind']=='scientific_evidence_request'
    assert graph.status(o['graph_root'])['usage']['calls']==1 and review._view(*review._read(closed.root))['state']=='awaiting_review'
