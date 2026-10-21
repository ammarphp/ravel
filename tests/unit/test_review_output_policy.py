"""Pure complete review lifecycle, synthetic receipts/roles; no native/worker."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
import pytest
from ravel.workflow import science,execution,physics_review as review,launch_authorization,review_context
from ravel.workflow.state_io import atomic_json,read_json
from test_science_output_policy import planned,token
from test_science_review_envelope import checks
from bound_review import bound_review


@pytest.fixture
def completed(tmp_path,monkeypatch):
    monkeypatch.setattr(launch_authorization,'audit_launches',lambda *a,**k:[])
    rd,p=planned(tmp_path);science.approve(rd,'Synthetic complete lifecycle test, no worker/native',scripted=True);token(rd)
    stage,binding,_=science._selected(rd,p);record=execution.begin_attempt(rd,'science',binding,stage['log']);out=rd/stage['outputs'][0]
    atomic_json(out/'result.json',{'status':'passed','physics_validated':False,'value':1})
    atomic_json(out/'recipe.json',{'task':science.execution_spec(rd)['task']})
    atomic_json(out/'verification.json',{'passed':True,'scope':'domain','physics_validated':False,'expert_review':False,'result_sha256':execution.file_hash(out/'result.json')})
    atomic_json(out/'checkin2.json',{'schema_version':1,'kind':'checkin2','sections':{'waypoint':'Synthetic control','expectation':'Byte custody','ask':{'options':['GO','ADJUST']}}})
    logger=out/'native-work/source/combine_logger.out';logger.parent.mkdir(parents=True);logger.write_bytes(b'')
    (rd/stage['log']).write_text('Synthetic fixture, no actual worker\n')
    assert execution.finish_attempt(rd,record,0)==0;checks(rd,record,1,'pass')
    return rd,record,logger


def open_cycle(data):
    rd,record,_=data
    return review.open_cycle(rd,effective_settings=science.review_effective_settings(rd),stage_receipts=[record['attempt_record']],check_results='inputs/checks-1.json')


def test_complete_open_read_roles_bound_paths_snapshot_and_reuse(completed,tmp_path):
    rd,record,logger=completed;cycle=open_cycle(completed)
    rows=[p for p in cycle['snapshots'] if p['path'].endswith('combine_logger.out')]
    assert len(rows)==1 and rows[0]['size']==0 and rows[0]['sha256']==hashlib.sha256(b'').hexdigest()
    reg,events=review._read(rd);assert review._empty_snapshot_allowed(rows[0],reg,cycle)
    assert str(logger) in review.bound_paths(rd)
    # Detached classification can validate exactly the same frozen proofs.
    snap={'schema_version':1,'registration':reg,'events':events,'checkpoint':read_json(rd/review.HEAD),'action':'history','stage':None}
    assert review.validate_snapshot(snap,require_admission=False)==[]
    # Recorded votes are bound responses of dispatched roles; a declared reviewer name is advice only.
    for role in ['physics_critic','skeptical_verifier','physics_decider']:
        bound_review(rd,role=role,verdict='accept',summary='Synthetic source custody test; no scientific review',claim_scope='reproduction')
    assert review.status(rd)['state']=='accepted'
    assert review.gate_errors(rd,'reuse')==[]
    assert science.packet(rd)['lifecycle_verdict']=='PASS'
    assert execution.stage_errors(rd,'science')==[]
    assert review.validate_snapshot(review.snapshot(rd,action='reuse'))==[]
    packet=tmp_path/'critic-context'
    manifest=review_context.create(rd,'critic',packet)
    assert any(p.get('source_path','').endswith('combine_logger.out') for p in manifest['artifacts'])


@pytest.mark.parametrize('location',['check','setting','finding'])
def test_incidental_zero_cannot_be_scientific_evidence(completed,location):
    rd,record,logger=completed
    if location=='check':
        c=read_json(rd/'inputs/checks-1.json');c['checks'][0]['evidence'][0]['path']=str(logger);atomic_json(rd/'inputs/checks-1.json',c)
        with pytest.raises(ValueError,match='missing or empty'):open_cycle(completed)
    elif location=='setting':
        with pytest.raises(ValueError,match='missing or empty'):
            review.open_cycle(rd,effective_settings=[str(logger)],stage_receipts=[record['attempt_record']],check_results='inputs/checks-1.json')
    else:
        open_cycle(completed)
        with pytest.raises(ValueError,match='missing or empty'):
            bound_review(rd,role='physics_critic',verdict='send_back',summary='Synthetic refusal',findings=[{'id':'F1','summary':'Cited empty log','evidence':[{'path':str(logger),'location':'whole'}],'check_ids':['integrity'],'required_paths':[],'required_stages':['science']}])


@pytest.mark.parametrize('change',['removed','text_changed','symlink'])
def test_live_output_mutation_refuses_review_reuse(completed,change):
    rd,_,logger=completed;open_cycle(completed)
    if change=='removed':logger.unlink()
    if change=='text_changed':logger.write_text('changed')
    if change=='symlink':
        other=logger.with_name('other');other.write_bytes(b'');logger.unlink();logger.symlink_to(other)
    assert review.gate_errors(rd,'reuse')


def test_historical_zero_class_uses_frozen_receipt_not_mutable_ledger(completed):
    rd,_,_=completed;cycle=open_cycle(completed)
    state=read_json(rd/execution.STATE_NAME);state['stages']['science'].pop('output_policy');atomic_json(rd/execution.STATE_NAME,state)
    reg,events=review._read(rd)
    assert events[0]['cycle_id']==cycle['cycle_id']
    assert review._incidental_output_paths(reg,cycle)=={'outputs/attempt-1/native-work/source/combine_logger.out'}
    assert review.gate_errors(rd,'reuse')


@pytest.mark.parametrize('change',['spec_policy','receipt_policy','receipt_status','approval_plan','source_pin','missing_proof','empty_check','oversized'])
def test_detached_proof_refuses_mutation(completed,change):
    rd,_,_=completed;cycle=open_cycle(completed);reg,_=review._read(rd);cycle=deepcopy(cycle);reg=deepcopy(reg)
    proof=cycle['receipts'][0]['incidental_output_proof']
    if change=='missing_proof':
        cycle['receipts'][0].pop('incidental_output_proof')
        assert not review._empty_snapshot_allowed(next(p for p in cycle['snapshots'] if p['size']==0),reg,cycle)
        return
    if change=='empty_check':
        cycle['checks'][0]['evidence'][0]['path']='outputs/attempt-1/native-work/source/combine_logger.out'
        assert not review._empty_snapshot_allowed(next(p for p in cycle['snapshots'] if p['size']==0),reg,cycle)
        return
    if change=='source_pin':proof['plan']['sha256']='0'*64
    elif change=='oversized':proof['specification']['text']=' '* (review.MAX_RETAINED_BYTES+1)
    else:
        key='specification' if change=='spec_policy' else 'receipt' if change in ('receipt_policy','receipt_status') else 'approval'
        doc=json.loads(proof[key]['text'])
        if change=='spec_policy':doc['output_policy']['allow_empty_directory_members'][0]['path']='outputs/attempt-1/other.log'
        if change=='receipt_policy':doc.pop('output_policy')
        if change=='receipt_status':doc['status']='failed'
        if change=='approval_plan':doc['plan_sha256']='0'*64
        proof[key]['text']=json.dumps(doc)
    with pytest.raises(ValueError):review._incidental_output_paths(reg,cycle)


def test_oversized_actual_proof_refuses_before_cycle_write(completed,monkeypatch):
    rd,_,_=completed;monkeypatch.setattr(review,'MAX_INCIDENTAL_PROOF_BYTES',1)
    with pytest.raises(ValueError,match='budget'):open_cycle(completed)
    assert not list((rd/review.DIRECTORY/'events').glob('*.json'))
