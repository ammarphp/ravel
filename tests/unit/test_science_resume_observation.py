"""Accepted reuse reads share one authority-local session; no worker/science call."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from ravel.workflow import science, execution, physics_review as review, review_enforcement, stage_supervisor
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow.validation_io import ValidationSession
from test_science_packet_observation import accepted, count_reads


def inert_resume(monkeypatch):
    monkeypatch.setattr(stage_supervisor, 'recover_previous_attempt', lambda *a, **k: None)
    monkeypatch.setattr(stage_supervisor, 'supervise', lambda *a, **k: pytest.fail('accepted reuse must not start a worker'))
    monkeypatch.setattr(execution, 'begin_attempt', lambda *a, **k: pytest.fail('accepted reuse must not debit an attempt'))


def snapshot(rd):
    files = [*sorted((rd/'outputs').rglob('*')), *sorted((rd/'logs/science-attempts').glob('*.json')),
             *sorted((rd/'logs/execution').rglob('record.json')), rd/execution.STATE_NAME,
             rd/'execution_attempt.json', rd/science.APPROVAL]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}


def test_original_vs_candidate_full_run_resume_reads_and_identical_receipts(accepted, monkeypatch):
    rd, payload, _ = accepted
    inert_resume(monkeypatch)
    # Exact accepted branch from the retained preimage, through ordinary APIs.
    # The public companion needs no ignored/native source or artifact fixture.
    def original_run(root):
        proposal = science.verify_plan(root, approved=True)
        assert science.packet(root)['lifecycle_verdict'] == 'PASS'
        stage, _, _ = science._selected(root, proposal)
        review_enforcement.before_stage(root, 'science', stage['command'], stage['inputs'], stage['outputs'], [],
                                        str(root), stage['log'], resume=True)
        return 0
    reads = count_reads(monkeypatch, payload);before = snapshot(rd)
    assert original_run(rd) == 0
    prior_reads = len(reads);reads.clear()
    assert science.run(rd, resume=True) == 0
    proposed_reads = len(reads)
    assert prior_reads > proposed_reads == 1
    assert snapshot(rd) == before
    assert len(list((rd/'logs/science-attempts').glob('*.json'))) == 1
    print(json.dumps({'baseline_reads':prior_reads,'proposed_reads':proposed_reads,
          'payload_bytes':payload.stat().st_size,'scientific_calls':0,'new_attempts':0}))


def test_no_cache_between_runs_or_next_packet(accepted, monkeypatch):
    rd, payload, _ = accepted;inert_resume(monkeypatch)
    reads = count_reads(monkeypatch, payload);sessions=[];factory=execution._validation_session
    def capture(*a, **k):
        s=factory(*a, **k);sessions.append(s);return s
    monkeypatch.setattr(execution, '_validation_session', capture)
    assert science.run(rd,resume=True)==0
    assert science.run(rd,resume=True)==0
    assert science.packet(rd)['lifecycle_verdict']=='PASS'
    assert len(reads)==3 and len(sessions)==3
    assert len({id(s) for s in sessions})==3
    assert all(s.closed and not s.hashes and not s.stages and not s.proofs for s in sessions)


def add_hold(rd):
    reg, events=review._read(rd);view=review._view(reg, events);cycle=view['cycle']
    evidence=next(p for p in cycle['snapshots'] if p['path'].endswith('/result.json'))
    p=rd/'inputs/late-defect.json';atomic_json(p,{'engineering_adverse':True})
    context={'schema_version':1,'kind':'post_acceptance_scientific_finding','run_id':reg['run_id'],
      'cycle_id':cycle['cycle_id'],'cycle_sha256':cycle['sha256'],'claim_scope':'reproduction',
      'accepted_review_sha256':[e['sha256'] for e in view['reviews']], 'role':'physics_critic',
      'actor_id':'critic','findings':[{'id':'late-reuse-control','summary':'Engineering adverse control',
       'check_ids':['agreement'],'accepted_evidence':[{'path':evidence['path'],'sha256':evidence['sha256'],'location':'$.value'}],
       'new_evidence':[{'path':'inputs/late-defect.json','sha256':execution.file_hash(p),'location':'$.engineering_adverse'}]}]}
    c=rd/'inputs/late-context.json';atomic_json(c,context)
    review.submit_hold(rd,actor_id='physicist',cycle_id=cycle['cycle_id'],claim_scope='reproduction',
      summary='Engineering control holds future use',finding_context=str(c),finding_context_sha256=execution.file_hash(c))


@pytest.mark.parametrize('mutation', ['same_size_restored_mtime','replacement','leaf_symlink','ancestor_symlink',
  'output_membership','output_value','ledger_bytes','ledger_replacement','head','event_membership','runtime','tracked_plan','actual_hold'])
def test_final_commit_census_refuses_late_change(accepted, monkeypatch, mutation):
    rd,payload,_=accepted;inert_resume(monkeypatch);old=ValidationSession.finish;once=[]
    before=snapshot(rd)
    def finish(session):
        if not once:
            once.append(True)
            if mutation=='same_size_restored_mtime':
                st=payload.stat();raw=payload.read_bytes();payload.write_bytes(b'X'+raw[1:]);os.utime(payload,ns=(st.st_atime_ns,st.st_mtime_ns))
            elif mutation=='replacement':
                other=payload.with_name('replacement');other.write_bytes(payload.read_bytes());other.replace(payload)
            elif mutation=='leaf_symlink':
                other=payload.with_name('same');other.write_bytes(payload.read_bytes());payload.unlink();payload.symlink_to(other)
            elif mutation=='ancestor_symlink':
                out=rd/'outputs';moved=rd/'output-target';out.rename(moved);out.symlink_to(moved,target_is_directory=True)
            elif mutation=='output_membership':(rd/'outputs/attempt-1/new.dat').write_text('added')
            elif mutation=='output_value':atomic_json(rd/'outputs/attempt-1/result.json',{'status':'passed','physics_validated':False,'value':9})
            elif mutation=='ledger_bytes':
                d=read_json(rd/execution.STATE_NAME);d['revision']+=1;atomic_json(rd/execution.STATE_NAME,d)
            elif mutation=='ledger_replacement':
                other=rd/'replacement-ledger';other.write_bytes((rd/execution.STATE_NAME).read_bytes());other.replace(rd/execution.STATE_NAME)
            elif mutation=='head':atomic_json(rd/review.HEAD,{'sequence':999,'sha256':'0'*64})
            elif mutation=='event_membership':(rd/review.DIRECTORY/'events/99999999.json').write_text('{}')
            elif mutation=='runtime':session.runtime_context=lambda:{'changed':'runtime'}
            elif mutation=='tracked_plan':
                plan=next(o for o,d in session.tracked if isinstance(o,dict) and 'stage_binding' in o);plan['max_seconds']+=1
            else:add_hold(rd)
        return old(session)
    monkeypatch.setattr(ValidationSession,'finish',finish)
    with pytest.raises((ValueError,OSError),match='census|changed|symlink|runtime|inventory'):
        science.run(rd,resume=True)
    assert once and len(list((rd/'logs/science-attempts').glob('*.json')))==1
    # Changes come solely from the named adverse mutation; no new attempt/launch.
    assert read_json(rd/'execution_attempt.json')['attempt']==1


def test_hold_committed_between_packet_and_reuse_gate_refuses(accepted,monkeypatch):
    rd,_,_=accepted;inert_resume(monkeypatch);before=review_enforcement.before_stage
    def held(*a,**k):add_hold(rd);return before(*a,**k)
    monkeypatch.setattr(review_enforcement,'before_stage',held)
    with pytest.raises(ValueError,match='hold|changed'):
        science.run(rd,resume=True)
    assert review.status(rd)['state']=='scientific_hold'


def test_between_public_calls_restored_mtime_is_rehashed(accepted,monkeypatch):
    rd,payload,_=accepted;inert_resume(monkeypatch);reads=count_reads(monkeypatch,payload)
    assert science.run(rd,resume=True)==0
    st=payload.stat();raw=payload.read_bytes();payload.write_bytes(b'X'+raw[1:]);os.utime(payload,ns=(st.st_atime_ns,st.st_mtime_ns))
    with pytest.raises(ValueError,match='runtime bytes differ'):
        science.run(rd,resume=True)
    assert len(reads)==2


@pytest.mark.parametrize('problem',['closed','cross_run','launch'])
def test_private_reuse_seam_cannot_transplant_or_admit_launch(accepted,monkeypatch,tmp_path,problem):
    rd,_,_=accepted;other=tmp_path/'other';other.mkdir()
    s=execution._validation_session(other if problem=='cross_run' else rd)
    if problem=='closed':s.close()
    try:
        with pytest.raises(ValueError,match='closed|cross-run|fresh launch'):
            review_enforcement.before_stage(rd,'science',[],[],[],[],str(rd),'logs/test',resume=problem!='launch',_session=s)
    finally:s.close()


def test_existing_injected_before_stage_without_private_keyword_remains_supported(accepted,monkeypatch):
    rd,_,_=accepted;inert_resume(monkeypatch);called=[];before=review_enforcement.before_stage
    def legacy(root,stage,command,inputs,outputs,depends_on,cwd,log,*,resume=False):
        called.append(resume);return before(root,stage,command,inputs,outputs,depends_on,cwd,log,resume=resume)
    monkeypatch.setattr(review_enforcement,'before_stage',legacy)
    assert science.run(rd,resume=True)==0 and called==[True]


def test_completed_plan_proof_runs_once_inside_reuse_but_not_between_operations(accepted,monkeypatch):
    rd,_,_=accepted;inert_resume(monkeypatch);calls=[];verify=science._verify_v2
    def counted(*a,**k):calls.append(bool(k['approved']));return verify(*a,**k)
    monkeypatch.setattr(science,'_verify_v2',counted)
    assert science.run(rd,resume=True)==0 and calls==[True]
    calls.clear()
    assert science.packet(rd)['lifecycle_verdict']=='PASS' and calls==[False,True]
    calls.clear()
    assert science.verify_plan(rd,approved=True)['schema_version']==2 and calls==[True]


def test_unapproved_proof_does_not_waive_approval_recheck(accepted):
    rd,_,_=accepted
    with pytest.raises(ValueError,match='approval'):
        with science._validation_scope(rd) as session:
            science.verify_plan(rd,approved=False,_session=session)
            receipt=read_json(rd/science.APPROVAL);receipt['plan_sha256']='0'*64
            atomic_json(rd/science.APPROVAL,receipt)
            science.verify_plan(rd,approved=True,_session=session)


def test_public_before_stage_injected_positional_review_seams_keep_existing_api(monkeypatch,tmp_path):
    monkeypatch.setattr(review,'active',lambda root:True)
    monkeypatch.setattr(review,'status',lambda root:{'state':'accepted','correction_id':None})
    calls=[]
    def gate(root,action,stage):calls.append(action);return []
    monkeypatch.setattr(review,'gate_errors',gate)
    assert review_enforcement.before_stage(tmp_path,'science',[],[],[],[],str(tmp_path),'logs/out',resume=True) is None
    assert calls==['reuse']
