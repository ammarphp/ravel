"""Private inert original-epoch fixtures; no historical run or real review is edited."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
import pytest
from retained_status_fixture import closed
from ravel.workflow import execution,physics_review as review,retained_science_review as retained
from ravel.workflow.state_io import atomic_json,read_json

@pytest.fixture(autouse=True)
def inert_platform(monkeypatch):
    monkeypatch.setattr(execution.platform,'platform',lambda:'synthetic-source-control-platform')

def hold_status_as_new_evidence(closed):
    rd=closed.root;reg,events=review._read(rd);view=review._view(reg,events);cycle=view['cycle']
    old=next(p for p in cycle['snapshots'] if p['path']=='outputs/attempt-1/result.json')
    target=rd/'current_state.json';committed=target.read_bytes()
    context={'schema_version':1,'kind':'post_acceptance_scientific_finding','run_id':reg['run_id'],
        'cycle_id':cycle['cycle_id'],'cycle_sha256':cycle['sha256'],'claim_scope':'provider_readiness',
        'accepted_review_sha256':[e['sha256'] for e in view['reviews']], 'role':'physics_critic','actor_id':'critic',
        'findings':[{'id':'late-status-commitment','summary':'Inert status-custody control only',
            'check_ids':['agreement'],'accepted_evidence':[{'path':old['path'],'sha256':old['sha256'],'location':'$.value'}],
            'new_evidence':[{'path':'current_state.json','sha256':execution.file_hash(target),'location':'$'}]}]}
    path=rd/'inputs/late-status-context.json';atomic_json(path,context)
    event=review.submit_hold(rd,actor_id='decider',cycle_id=cycle['cycle_id'],claim_scope='provider_readiness',
        summary='Synthetic custody hold; no scientific finding asserted',finding_context=str(path),finding_context_sha256=execution.file_hash(path))
    got=review._view(*review._read(rd));assert got['state']=='scientific_hold'
    assert any(p['path']=='current_state.json' for p in got['holds'][-1]['snapshots'])
    assert target.read_bytes()==committed
    return event,committed

def test_late_hold_between_observe_and_write_cannot_overwrite_committed_evidence(closed,monkeypatch,tmp_path):
    original=retained.observe;activated=[];committed=[]
    def observed_then_committed(root,*a,**k):
        proof=original(root,*a,**k)
        assert proof['review_state']=='accepted'
        event,raw=hold_status_as_new_evidence(closed)
        activated.append(event);committed.append(raw)
        return proof
    monkeypatch.setattr(retained,'observe',observed_then_committed)
    result=None;error=None
    try:result=retained.packet(closed.root,write=True)
    except ValueError as exc:error=str(exc)
    assert len(activated)==1
    after=(closed.root/'current_state.json').read_bytes()
    atomic_json(tmp_path/'late-hold-write-witness.json',{
        'kind':'inert_late_hold_write_interleaving','hold_event_sha256':activated[0]['sha256'],
        'late_hold_view':review._view(*review._read(closed.root))['state'],
        'committed_status_sha256':hashlib.sha256(committed[0]).hexdigest(),
        'after_status_sha256':execution.file_hash(closed.root/'current_state.json'),
        'returned_packet':result,'returned_error':error,'committed_bytes_preserved':after==committed[0],
        'actual_historical_run_or_role_vote':False})
    assert after==committed[0], 'observational write overwrote current_state.json after a valid hold committed it'

def test_original_opaque_runtime_input_change_cannot_be_requalified(closed):
    root=closed.root;initial=read_json(root/execution.STATE_NAME)
    kernel=root.parent/'kernel';kernel.write_bytes(b'changed opaque synthetic executable; never run\n')
    with pytest.raises(ValueError):retained.observe(root,action='reuse')
    assert read_json(root/execution.STATE_NAME)==initial

def test_extra_original_output_member_is_not_ignored(closed):
    root=closed.root;initial=(root/execution.STATE_NAME).read_bytes()
    (root/'outputs/attempt-1/unlisted-result.dat').write_bytes(b'additional returned material\n')
    with pytest.raises(ValueError):retained.observe(root,action='delivery')
    assert (root/execution.STATE_NAME).read_bytes()==initial

def test_changed_original_launch_event_cannot_be_replaced_by_current_approval(closed):
    root=closed.root;p=root/'logs/authorization/00000001.json';event=read_json(p)
    event['authorization']['stage_binding']['fingerprint']='0'*64;atomic_json(p,event)
    with pytest.raises(ValueError):retained.observe(root,action='reuse')

def test_retained_detached_snapshot_cannot_gain_bulk_or_new_claim_authority(closed):
    snapshot=review.snapshot(closed.root,action='reuse',retained_study=True)
    assert review.validate_snapshot(snapshot)==[]
    wrong_action={**snapshot,'action':'bulk'}
    assert review.validate_snapshot(wrong_action)
    wrong_scope=deepcopy(snapshot)
    for event in wrong_scope['events']:
        if event['event']=='review':event['claim_scope']='unaccepted-physical-exclusion'
    assert review.validate_snapshot(wrong_scope)
    assert review.gate_errors(closed.root,'bulk',retained_study=True)

def test_foreign_and_closed_validation_sessions_cannot_supply_retained_proof(closed,tmp_path):
    foreign=tmp_path/'different-run';foreign.mkdir()
    session=execution._validation_session(foreign)
    try:
        with pytest.raises(ValueError):retained.observe(closed.root,_session=session)
    finally:session.close()
    closed_session=execution._validation_session(closed.root);closed_session.close()
    with pytest.raises(ValueError):retained.observe(closed.root,_session=closed_session)
