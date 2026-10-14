"""Synthetic accepted receipt, not native/scientific acceptance. No worker."""

from method_decision_fixture import admit_method
from pathlib import Path
from types import SimpleNamespace
import json,os
import pytest
from ravel.workflow import science,execution,physics_review as review,launch_authorization
from ravel.workflow.validation_io import ValidationSession
from ravel.workflow.state_io import atomic_json,read_json
from ravel.validation import likelihood_parity
from test_physics_review import policy

@pytest.fixture
def accepted(tmp_path,monkeypatch):
    payload=tmp_path/'runtime.bin';payload.write_bytes(b'bounded-runtime-control-'*4096)
    inventory={'schema_version':1,'files':[{'path':str(payload),'sha256':execution.file_hash(payload)}]}
    implementation=SimpleNamespace(validate=lambda task:None,
        inputs=lambda task,base:likelihood_parity.runtime_files(inventory),
        _validation_inputs=lambda task,base,session:likelihood_parity.runtime_files(inventory,_session=session))
    monkeypatch.setattr(science,'adapter',lambda spec:implementation)
    monkeypatch.setattr(launch_authorization,'audit_launches',lambda *a,**k:[])
    p=policy();p.update(allowed_stages=['science'],allowed_changed_paths=[],max_redos=0)
    spec={'schema_version':2,'mode':'likelihood-parity','source':'Synthetic observational performance control',
        'assumptions':['No native launch or scientific acceptance'], 'max_seconds':45,'max_attempts':1,
        'approval_mode':'scripted_yes','task':{'input':str(payload)},
        'review_policy':{'schema_version':1,'policy':p,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    source=tmp_path/'spec.json';atomic_json(source,spec);rd=tmp_path/'run'
    science.plan(rd,source); admit_method(rd);science.approve(rd,'Synthetic engineering control only',scripted=True)
    plan=read_json(rd/science.PLAN)
    attempt={'attempt':1,'plan_sha256':execution.file_hash(rd/science.PLAN),
        'budget_seconds':45,'started_utc':execution.utc_now(),'correction_id':None,'correction_plan_sha256':None}
    atomic_json(rd/'execution_attempt.json',attempt);atomic_json(rd/'logs/science-attempts/00000001.json',attempt)
    stage,binding,_=science._selected(rd,plan);record=execution.begin_attempt(rd,'science',binding,stage['log'])
    out=rd/stage['outputs'][0]
    atomic_json(out/'result.json',{'status':'passed','physics_validated':False,'value':1})
    atomic_json(out/'recipe.json',{'synthetic_receipt':True})
    atomic_json(out/'verification.json',{'passed':True,'scope':'likelihood-parity','physics_validated':False,'expert_review':False,'result_sha256':execution.file_hash(out/'result.json')})
    atomic_json(out/'checkin2.json',{'schema_version':1,'kind':'checkin2','sections':{'waypoint':'Synthetic control','expectation':'Observational custody','ask':{'options':['GO','ADJUST']}}})
    (rd/stage['log']).write_text('Synthetic, no launched worker\n')
    assert execution.finish_attempt(rd,record,0)==0
    atomic_json(rd/'inputs/checks.json',{'schema_version':1,'checks':[
        {'id':name,'status':'pass','attempt_ids':[record['attempt_id']],
         'evidence':[{'path':str(out/'result.json'),'location':'$.value'}]} for name in ('integrity','agreement')]})
    review.open_cycle(rd,effective_settings=[science.EXECUTION_TASK],stage_receipts=[record['attempt_record']],check_results='inputs/checks.json')
    for role,actor in [('physics_critic','critic'),('skeptical_verifier','skeptic'),('physics_decider','physicist')]:
        review.submit_review(rd,role=role,actor_id=actor,verdict='accept',summary='Synthetic observational control only',claim_scope='reproduction')
    return rd,payload,record

def independent_accepted_packet_reference(rd):
    """Prior independent checks, using actual shared APIs and a fixed typed result.

    This fixture is accepted only synthetically. It is a small stable reference
    for packet content/read count, not another admission or scientific worker.
    Waypoint checks remain independent here to retain the prior read boundary.
    """
    from ravel.workflow import review_enforcement
    p = science.verify_plan(rd)
    science.verify_plan(rd, approved=True)
    assert review.active(rd) and review.status(rd)['state'] == 'accepted'
    stage, _, _ = science._selected(rd, p)
    assert execution.validate_completed_execution(rd, [stage]) == []
    out = rd / stage['outputs'][0]
    result = read_json(out / 'result.json')
    verification = read_json(out / 'verification.json')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    assert verification['passed'] and verification['scope'] == p['mode']
    assert verification['result_sha256'] == execution.file_hash(out / 'result.json')
    waypoint_plan = science.verify_plan(rd, approved=True)
    science._selected(rd, waypoint_plan)
    assert execution.stage_errors(rd, 'science') == []
    assert review_enforcement.delivery_errors(rd) == []
    assert review.active(rd) and review.status(rd)['state'] == 'accepted'
    return {'schema_version': 2, 'rundir': str(rd), 'task_mode': 'likelihood-parity',
            'execution': {'status': 'completed'}, 'lifecycle_verdict': 'PASS',
            'errors': [], 'review_errors': [],
            'next_required': 'Scoped review accepted; reuse only the exact checked products',
            'physics_validated': False,
            'scope': 'Bounded scientific adapter delivery, not scientific closure or authenticated independent review'}


def count_reads(monkeypatch,payload):
    counts=[];old=Path.open
    def opened(path,*args,**kw):
        if path==payload and args and args[0]=='rb':counts.append(str(path))
        return old(path,*args,**kw)
    monkeypatch.setattr(Path,'open',opened);return counts

def test_instrumented_baseline_vs_proposed_full_packet_content_reads(accepted,monkeypatch):
    rd,payload,record=accepted;reads=count_reads(monkeypatch,payload)
    before=independent_accepted_packet_reference(rd);baseline=len(reads);reads.clear()
    after=science.packet(rd);proposed=len(reads)
    assert before==after and after['lifecycle_verdict']=='PASS'
    assert baseline>=7 and proposed==1
    before_record=execution.file_hash(rd/record['attempt_record'])
    reads.clear();assert science.packet(rd,write=True)==after
    assert len(reads)==1 and execution.file_hash(rd/record['attempt_record'])==before_record
    print(json.dumps({'baseline_runtime_content_reads':baseline,'proposed_runtime_content_reads':proposed,'fresh_second_packet_reads':len(reads),'synthetic_payload_bytes':payload.stat().st_size,'native_calls':0}))

@pytest.mark.parametrize('mutation',['same_size_mtime','replacement','symlink','output_membership','ledger','head','event_membership','runtime','tracked_plan'])
def test_mutation_after_last_cached_check_rejected_before_packet_return(accepted,monkeypatch,mutation):
    rd,payload,_=accepted;old=ValidationSession.finish;once=[]
    def finish(session):
        if not once:
            once.append(True)
            if mutation=='same_size_mtime':
                st=payload.stat();raw=payload.read_bytes();payload.write_bytes(b'X'+raw[1:]);os.utime(payload,ns=(st.st_atime_ns,st.st_mtime_ns))
            elif mutation=='replacement':
                other=payload.with_name('replacement');other.write_bytes(payload.read_bytes());other.replace(payload)
            elif mutation=='symlink':
                other=payload.with_name('same');other.write_bytes(payload.read_bytes());payload.unlink();payload.symlink_to(other)
            elif mutation=='output_membership':(rd/'outputs/attempt-1/extra').write_text('late addition')
            elif mutation=='ledger':
                state=read_json(rd/execution.STATE_NAME);state['revision']+=1;atomic_json(rd/execution.STATE_NAME,state)
            elif mutation=='head':atomic_json(rd/review.HEAD,{'sequence':999,'sha256':'0'*64})
            elif mutation=='event_membership':(rd/review.DIRECTORY/'events/99999999.json').write_text('{}')
            elif mutation=='runtime':session.runtime_context=lambda:{'changed':'runtime'}
            else:
                plan=next(obj for obj,digest in session.tracked if isinstance(obj,dict) and 'stage_binding' in obj)
                plan['max_seconds']+=1
        return old(session)
    monkeypatch.setattr(ValidationSession,'finish',finish)
    packet=science.packet(rd,write=True)
    assert packet['lifecycle_verdict']=='FAIL' and packet['execution']['status']=='invalid'
    assert packet['errors'] and once

@pytest.mark.parametrize('entry',['packet','completed','stage','review_gate','review_read'])
@pytest.mark.parametrize('problem',['cross_run','closed'])
def test_private_session_seams_reject_cross_run_or_closed_context(accepted,tmp_path,entry,problem):
    rd,_,record=accepted;other=tmp_path/'other';other.mkdir()
    session=execution._validation_session(other if problem=='cross_run' else rd)
    if problem=='closed':session.close()
    plan=read_json(rd/science.PLAN)
    try:
        if entry=='packet':
            with pytest.raises(ValueError,match='cross-run|closed'):science._packet_v2_observed(rd,session)
        elif entry=='completed':assert execution.validate_completed_execution(rd,plan['stages'],_session=session)
        elif entry=='stage':
            with pytest.raises(ValueError,match='cross-run|closed'):execution.stage_errors(rd,'science',_session=session)
        elif entry=='review_gate':
            with pytest.raises(ValueError,match='cross-run|closed'):review.gate_errors(rd,'delivery',_session=session)
        else:
            with pytest.raises(ValueError,match='cross-run|closed'):review._read(rd,_session=session)
    finally:session.close()


def test_no_session_reuse_between_public_packet_calls(accepted,monkeypatch):
    rd,payload,_=accepted;factory=execution._validation_session;seen=[]
    def capture(*a,**k):
        result=factory(*a,**k);seen.append(result);return result
    monkeypatch.setattr(execution,'_validation_session',capture)
    for _ in range(2):assert science.packet(rd)['lifecycle_verdict']=='PASS'
    assert len(seen)==2 and seen[0] is not seen[1]
    assert all(x.closed and not x.hashes and not x.stages for x in seen)


def test_observation_session_cannot_create_registration(accepted):
    rd,_,_=accepted;session=execution._validation_session(rd)
    try:
        with pytest.raises(ValueError,match='cannot create'):review._registration(rd,create=True,_session=session)
    finally:session.close()


def test_existing_unary_delivery_seam_retains_pending_semantics(accepted, monkeypatch):
    from ravel.workflow import review_enforcement
    rd, _, _ = accepted
    monkeypatch.setattr(review_enforcement, 'delivery_errors', lambda _: ['live review is unresolved'])
    result = science.packet(rd)
    assert result['lifecycle_verdict'] == 'PENDING'
    assert result['execution']['status'] == 'awaiting_review'
    assert result['review_errors'] == ['live review is unresolved']


@pytest.mark.parametrize('mutation', ['dangling_leaf', 'dangling_ancestor', 'live_ancestor'])
def test_absent_inventory_late_symlink_leaf_or_ancestor_refuses(tmp_path, mutation):
    session = execution._validation_session(tmp_path)
    parent = tmp_path / 'review-parent'
    events = parent / 'events'
    session.require_inventory(events)
    if mutation == 'dangling_leaf':
        parent.mkdir()
        events.symlink_to(tmp_path / 'missing-target')
    else:
        target = tmp_path / 'missing-target'
        if mutation == 'live_ancestor':
            target.mkdir()
        parent.symlink_to(target, target_is_directory=True)
    assert not events.exists()
    errors = session.finish()
    assert errors and 'symlink' in errors[0]
    assert session.closed


def test_absent_inventory_unchanged_absence_passes_and_closes(tmp_path):
    session = execution._validation_session(tmp_path)
    session.require_inventory(tmp_path / 'review-parent' / 'events')
    assert session.finish() == []
    assert session.closed


def test_packet_cache_cannot_carry_authority_across_fresh_approval_boundary(accepted, monkeypatch):
    rd, payload, _ = accepted
    reads = count_reads(monkeypatch, payload)
    assert science.packet(rd)['lifecycle_verdict'] == 'PASS'
    assert len(reads) == 1
    reads.clear()
    assert science.verify_approval_envelope(rd) == []
    assert len(reads) == 1
    content = payload.read_bytes()
    payload.write_bytes(b'X' + content[1:])
    assert science.verify_approval_envelope(rd)
    with pytest.raises(ValueError):
        science.verify_plan(rd, approved=True)
