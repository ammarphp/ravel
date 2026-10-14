"""Current-reader routes over inert original-epoch receipts; no native or Host calls."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel import cli
from ravel.workflow import execution, science, physics_review as review
from ravel.workflow import retained_science_review as retained, scientific_judgment as j, agent_graph as graph
from ravel.workflow.state_io import atomic_json, read_json
from retained_status_fixture import closed
from test_retained_review_continuation import public_value, observed

@pytest.fixture(autouse=True)
def inert(monkeypatch):
    monkeypatch.setattr(execution.platform,'platform',lambda:'synthetic-source-control-platform')

def original_bytes(root):
    return {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}

def check_packet(closed,state):
    before=original_bytes(closed.root)
    p=retained.packet(closed.root)
    assert p['errors']==[],p
    assert p['review_state']==state
    assert p['physics_validated'] is False and p['execution_authority_granted'] is False
    assert p['current_runtime_requalified'] is False and p['scientific_acceptance_granted'] is False
    assert p['original_execution']['framework_root']==str(closed.package)
    assert p['original_execution']['runtime']==closed.record['runtime']
    assert str(Path(retained.__file__).absolute())==p['current_reader']['path']
    assert p['current_reader']['sha256']==execution.file_hash(retained.__file__)
    assert original_bytes(closed.root)==before
    return p

@pytest.mark.parametrize('closed',['awaiting_review','send_back','stopped',None],indirect=True)
def test_status_distinguishes_retained_review_states(closed):
    reg,events=review._read(closed.root);state=review._view(reg,events)['state']
    p=check_packet(closed,state)
    assert p['lifecycle_verdict']==('PASS' if state=='accepted' else 'PENDING')
    assert p['execution']['status']==('completed' if state=='accepted' else state)
    if state!='accepted':assert review.gate_errors(closed.root,'reuse',retained_study=True)

@pytest.mark.parametrize('action',['delivery','reuse'])
def test_retained_action_and_existing_detached_schema(closed,action):
    before=original_bytes(closed.root)
    assert review.gate_errors(closed.root,action,retained_study=True)==[]
    snapshot=review.snapshot(closed.root,action=action,retained_study=True)
    assert set(snapshot)=={'schema_version','registration','events','checkpoint','action','stage'}
    assert review.validate_snapshot(snapshot)==[] and snapshot['action']==action
    assert original_bytes(closed.root)==before
    assert review.gate_errors(closed.root,action) # default still rebuilds current admission
    with pytest.raises(ValueError,match='inventory changed'):science.verify_plan(closed.root,approved=True)
    with pytest.raises(ValueError,match='pending review'):retained.pending(closed.root)

@pytest.mark.parametrize('action,stage',[('bulk',None),('correction','science'),('final_task',None),('reuse','science'),(None,None)])
def test_retained_route_never_admits_other_actions(closed,action,stage):
    assert review.gate_errors(closed.root,action,stage,retained_study=True)
    with pytest.raises(ValueError):review.snapshot(closed.root,action=action,stage=stage,retained_study=True)

@pytest.mark.parametrize('closed',['awaiting_review'],indirect=True)
def test_current_typed_role_contexts_then_scoped_status_gate(closed,tmp_path,monkeypatch):
    for role,actor in [('critic','critic'),('verifier','skeptic'),('synthesizer','decider')]:
        b=j.prepare_role(closed.root,tmp_path/role,role=role,actor_id=actor,model='synthetic',reasoning_effort='high',max_output_tokens=2048,max_wall_seconds=120,claim_scope='provider_readiness',retained_study=True)
        # Votes count only through an observed transport; a relayed response is refused as self-attested.
        observed(b,public_value(b),monkeypatch)
        event=j.consume(closed.root,b)
        assert any(p.get('kind')=='role_context' for p in event['supporting_artifacts'])
    p=check_packet(closed,'accepted');assert p['claim_scope']=='provider_readiness'
    assert review.gate_errors(closed.root,'reuse',retained_study=True)==[]
    assert review.validate_snapshot(review.snapshot(closed.root,action='delivery',retained_study=True))==[]
    with pytest.raises(ValueError,match='pending review'):j._live(closed.root,retained_study=True)
    reg,events=review._read(closed.root)
    pin=next(p for e in events for p in e.get('supporting_artifacts',[]) if p.get('kind')=='role_context')
    Path(pin['path']).write_text('{}\n')
    assert retained.packet(closed.root)['execution']['status']=='invalid'
    assert review.gate_errors(closed.root,'reuse',retained_study=True)

@pytest.mark.parametrize('defect',['source','source_member','output','log','approval','journal','runtime_missing'])
def test_changed_original_commitments_refuse_instead_of_rebinding(closed,defect):
    rd=closed.root
    if defect=='source':(closed.package/'workflow/execution.py').write_text('changed source')
    elif defect=='source_member':(closed.package/'new.py').write_text('new source')
    elif defect=='output':atomic_json(rd/'outputs/attempt-1/result.json',{'status':'passed','physics_validated':True})
    elif defect=='log':(rd/closed.record['log']).write_text('new log')
    elif defect=='approval':atomic_json(rd/science.APPROVAL,{'forged':True})
    elif defect=='journal':atomic_json(rd/review.HEAD,{'sequence':0,'sha256':'0'*64})
    else:
        ledger=read_json(rd/execution.STATE_NAME);ledger['stages']['science'].pop('runtime_environment');atomic_json(rd/execution.STATE_NAME,ledger)
    p=retained.packet(rd)
    assert p['execution']['status']=='invalid' and p['lifecycle_verdict']=='FAIL' and p['errors']
    assert review.gate_errors(rd,'reuse',retained_study=True)
    with pytest.raises(ValueError):review.snapshot(rd,action='reuse',retained_study=True)

def add_hold(closed):
    rd=closed.root;reg,events=review._read(rd);view=review._view(reg,events);cycle=view['cycle']
    old=next(p for p in cycle['snapshots'] if p['path']=='outputs/attempt-1/result.json')
    fresh=rd/'inputs/late.json';atomic_json(fresh,{'synthetic_new_finding':True,'science_calls':0})
    context={'schema_version':1,'kind':'post_acceptance_scientific_finding','run_id':reg['run_id'],
        'cycle_id':cycle['cycle_id'],'cycle_sha256':cycle['sha256'],'claim_scope':'provider_readiness',
        'accepted_review_sha256':[e['sha256'] for e in view['reviews']], 'role':'physics_critic','actor_id':'critic',
        'findings':[{'id':'new-custody-obligation','summary':'Synthetic adverse claim control','check_ids':['agreement'],
        'accepted_evidence':[{'path':old['path'],'sha256':old['sha256'],'location':'$.value'}],
        'new_evidence':[{'path':'inputs/late.json','sha256':execution.file_hash(fresh),'location':'$.synthetic_new_finding'}]}]}
    target=rd/'inputs/late-context.json';atomic_json(target,context)
    review.submit_hold(rd,actor_id='decider',cycle_id=cycle['cycle_id'],claim_scope='provider_readiness',summary='Hold this synthetic accepted scope',finding_context=str(target),finding_context_sha256=execution.file_hash(target))
    return fresh,target

@pytest.mark.parametrize('change',[False,True])
def test_late_hold_is_visible_and_blocks_without_lifting(closed,change):
    fresh,target=add_hold(closed)
    p=check_packet(closed,'scientific_hold')
    assert p['held_claim_scope']=='provider_readiness' and p['claim_scope'] is None and p['unresolved_findings']
    assert p['lifecycle_verdict']=='PENDING'
    assert review.gate_errors(closed.root,'reuse',retained_study=True)
    with pytest.raises(ValueError):review.snapshot(closed.root,action='delivery',retained_study=True)
    if change:
        fresh.write_text('{}\n')
        p=retained.packet(closed.root)
        assert p['execution']['status']=='invalid' and p['errors']

def test_ending_source_drift_refuses_same_call(closed,monkeypatch):
    create=execution._validation_session
    def session(*a,**kw):
        current=create(*a,**kw);finish=current.finish
        def changed():
            (closed.package/'during-observation.py').write_text('new member at ending boundary')
            return finish()
        current.finish=changed
        return current
    monkeypatch.setattr(execution,'_validation_session',session)
    p=retained.packet(closed.root)
    assert p['execution']['status']=='invalid' and 'during validation' in ';'.join(p['errors'])

def test_current_reader_runtime_drift_refuses(closed,monkeypatch):
    initial=execution.runtime_context();calls=0
    def changing():
        nonlocal calls;calls+=1
        return initial if calls==1 else {**initial,'platform':'changed reader runtime'}
    monkeypatch.setattr(execution,'runtime_context',changing)
    assert retained.packet(closed.root)['execution']['status']=='invalid'

def test_new_observation_never_uses_prior_cache(closed):
    assert retained.packet(closed.root)['lifecycle_verdict']=='PASS'
    (closed.package/'workflow/execution.py').write_text('changed after first complete call')
    assert retained.packet(closed.root)['execution']['status']=='invalid'

def test_explicit_cli_status_and_observational_write(closed,capsys):
    before=original_bytes(closed.root);before.pop(str(closed.root/'current_state.json'))
    assert cli.main(['status','--rundir',str(closed.root),'--retained-study','--write'])==0
    p=json.loads(capsys.readouterr().out)
    assert p==read_json(closed.root/'current_state.json') and p['lifecycle_verdict']=='PASS'
    after=original_bytes(closed.root);after.pop(str(closed.root/'current_state.json'))
    assert after==before
    assert cli.main(['status','--rundir',str(closed.root)])==1
    normal=json.loads(capsys.readouterr().out)
    assert normal['execution']['status']=='invalid'

def test_explicit_review_cli_retained_gate(closed,capsys):
    assert review.main(['--rundir',str(closed.root),'gate','--action','reuse','--retained-study'])==0
    assert json.loads(capsys.readouterr().out)=={'errors':[]}

def test_alias_refuses_status_gate_snapshot_and_write(closed,tmp_path):
    alias=tmp_path/'alias';alias.symlink_to(closed.root,target_is_directory=True)
    assert retained.packet(alias)['execution']['status']=='invalid'
    assert review.gate_errors(alias,'reuse',retained_study=True)
    with pytest.raises(ValueError):retained.packet(alias,write=True)
    with pytest.raises(ValueError):review.snapshot(alias,action='delivery',retained_study=True)

def test_explicit_boolean_required(closed):
    assert review.gate_errors(closed.root,'reuse',retained_study='yes')
    with pytest.raises(ValueError):review.snapshot(closed.root,action='reuse',retained_study=1)

@pytest.mark.parametrize('closed',['postcondition_failed','verification_failed'],indirect=True)
def test_accepted_journal_cannot_overrule_original_failed_delivery_postconditions(closed):
    reg,events=review._read(closed.root)
    assert review._view(reg,events)['state']=='accepted'
    p=retained.packet(closed.root)
    assert p['execution']['status']=='invalid' and p['errors']
    assert review.gate_errors(closed.root,'delivery',retained_study=True)

def test_review_projection_cli_and_separate_reader_runtime(closed,capsys):
    p=review.status(closed.root,retained_study=True)
    assert p['state']=='accepted' and p['live_errors']==[]
    assert p['current_reader']['runtime']==execution.runtime_context()
    assert p['current_runtime_requalified'] is False
    assert review.main(['--rundir',str(closed.root),'status','--retained-study'])==0
    assert json.loads(capsys.readouterr().out)==p

def test_observation_requires_complete_contexts_and_source_even_with_invalid_write(closed):
    before=(closed.root/'current_state.json').read_bytes()
    (closed.package/'workflow/execution.py').write_text('changed input')
    with pytest.raises(ValueError,match='valid original commitments'):retained.packet(closed.root,write=True)
    assert (closed.root/'current_state.json').read_bytes()==before

@pytest.mark.parametrize('closed',['status_evidence'],indirect=True)
def test_write_cannot_overwrite_current_state_if_it_is_review_committed_evidence(closed):
    before=(closed.root/'current_state.json').read_bytes()
    assert retained.packet(closed.root)['lifecycle_verdict']=='PASS'
    with pytest.raises(ValueError,match='overwrite evidence'):retained.packet(closed.root,write=True)
    assert (closed.root/'current_state.json').read_bytes()==before

def test_written_packet_matches_intended_labels_before_return(closed,monkeypatch):
    from ravel.workflow import state_io
    original=state_io.atomic_json
    def corrupt(path,value):
        original(path,{**value,'physics_validated':True})
    monkeypatch.setattr(state_io,'atomic_json',corrupt)
    with pytest.raises(ValueError,match='intended observational packet'):retained.packet(closed.root,write=True)

def test_actual_public_main_entrypoint_writes_retained_packet(closed,monkeypatch,capsys):
    import runpy,sys
    monkeypatch.setattr(sys,'argv',['ravel','status','--rundir',str(closed.root),'--retained-study','--write'])
    with pytest.raises(SystemExit) as exit:
        runpy.run_module('ravel.__main__',run_name='__main__')
    assert exit.value.code==0
    p=json.loads(capsys.readouterr().out)
    assert p==read_json(closed.root/'current_state.json') and p['review_state']=='accepted'
