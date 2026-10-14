"""Resealed pure in-memory proofs reach semantic guards; no disk/worker mutation."""
from copy import deepcopy
import hashlib,json
import pytest
from ravel.workflow import execution,physics_review as review
from test_review_output_policy import completed,open_cycle


def frozen(data):
    rd,_,_=data
    cycle=open_cycle(data);reg,_=review._read(rd)
    return deepcopy(reg),deepcopy(cycle)


def reseal(reg,cycle,key,doc):
    source=cycle['receipts'][0]['incidental_output_proof'][key]
    raw=(json.dumps(doc,sort_keys=True,indent=2)+'\n').encode()
    sha=hashlib.sha256(raw).hexdigest()
    source['text']=raw.decode();source['sha256']=sha
    matching=[p for p in cycle['snapshots'] if p['path']==source['path']]
    assert len(matching)==1
    matching[0].update(sha256=sha,size=len(raw),snapshot=f'{review.DIRECTORY}/snapshots/{sha}.blob')
    for pin in reg['bindings']:
        if pin['path']==source['path']:pin['sha256']=sha
    # The test deliberately repairs provenance wrappers; refusal must be semantic.
    assert hashlib.sha256(source['text'].encode()).hexdigest()==source['sha256']==matching[0]['sha256']


@pytest.mark.parametrize('field',['command','inputs','runtime','outputs','input_snapshot','parents','cwd'])
def test_resealed_record_committed_fields_refuse(completed,field):
    reg,cycle=frozen(completed);proof=cycle['receipts'][0]['incidental_output_proof']
    record=json.loads(proof['receipt']['text'])
    if field=='command':record[field]=record[field]+['--unapproved']
    elif field in ('inputs','outputs'):record[field]=record[field]+['unapproved/member']
    elif field=='cwd':record[field]=record[field]+'/unapproved'
    elif field=='parents':record[field]={'unapproved':'0'*64}
    elif field=='input_snapshot':record[field]={}
    elif field=='runtime':record[field]['environment_sha256']='0'*64
    committed={k:record[k] for k in ('command','cwd','inputs','outputs','input_snapshot','parents','runtime')}|execution.output_policy_fields(record)
    assert execution.digest(committed)!=record['fingerprint']
    reseal(reg,cycle,'receipt',record)
    with pytest.raises(ValueError,match='record committed specification'):review._incidental_output_paths(reg,cycle)


def test_self_rehashed_record_still_must_equal_approved_binding(completed):
    reg,cycle=frozen(completed);proof=cycle['receipts'][0]['incidental_output_proof']
    record=json.loads(proof['receipt']['text']);record['command'].append('--unapproved')
    committed={k:record[k] for k in ('command','cwd','inputs','outputs','input_snapshot','parents','runtime')}|execution.output_policy_fields(record)
    record['fingerprint']=execution.digest(committed);record['receipt_sha256']=execution.receipt_digest(record)
    cycle['receipts'][0]['receipt_sha256']=record['receipt_sha256'];reseal(reg,cycle,'receipt',record)
    with pytest.raises(ValueError,match='record committed specification'):review._incidental_output_paths(reg,cycle)


@pytest.mark.parametrize('change',['version','generator','mode','unknown_field','late_approval','blank_quote','non_utc'])
def test_resealed_approval_schema_and_temporal_binding_refuse(completed,change):
    reg,cycle=frozen(completed);proof=cycle['receipts'][0]['incidental_output_proof'];doc=json.loads(proof['approval']['text'])
    if change=='version':doc['schema_version']=1
    elif change=='generator':doc['generated_by']='unapproved.tool'
    elif change=='mode':doc['approval_mode']='physicist'
    elif change=='unknown_field':doc['incidental_permission']=True
    elif change=='late_approval':doc['utc']='2999-01-01T00:00:00+00:00'
    elif change=='blank_quote':doc['quote']=' '
    elif change=='non_utc':doc['utc']='2026-01-01T00:00:00'
    reseal(reg,cycle,'approval',doc)
    with pytest.raises(ValueError,match='approval|UTC'):review._incidental_output_paths(reg,cycle)


def test_resealed_record_finish_before_start_refuses(completed):
    reg,cycle=frozen(completed);doc=json.loads(cycle['receipts'][0]['incidental_output_proof']['receipt']['text'])
    doc['finished_utc']='1900-01-01T00:00:00+00:00';reseal(reg,cycle,'receipt',doc)
    with pytest.raises(ValueError,match='timing'):review._incidental_output_paths(reg,cycle)


def test_resealed_plan_unknown_field_refuses(completed):
    reg,cycle=frozen(completed);doc=json.loads(cycle['receipts'][0]['incidental_output_proof']['plan']['text'])
    doc['unapproved_extension']=True;reseal(reg,cycle,'plan',doc)
    with pytest.raises(ValueError,match='science plan'):review._incidental_output_paths(reg,cycle)
