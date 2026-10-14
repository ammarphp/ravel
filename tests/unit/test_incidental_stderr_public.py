"""Real public snapshot/finish/reuse and prospective plan, no worker/native calls."""
import hashlib
from pathlib import Path

import pytest
from ravel.workflow import execution,science
from ravel.workflow.state_io import atomic_json,read_json
from test_science_review_envelope import specification


def policy(path='outputs/attempt-1/container-output/listing.stderr'):
    return {'schema_version':1,'allow_empty_directory_members':[{'path':path,'role':'incidental_log'}]}


@pytest.mark.parametrize('cached',[False,True])
def test_exact_stderr_zero_retained_and_unlisted_scientific_zero_refused(tmp_path,cached):
    d=tmp_path/'out';d.mkdir()
    (d/'listing.stderr').write_bytes(b'')
    (d/'result.json').write_text('{"status":"passed","native_identity":"nonempty-control"}')
    session=execution._validation_session(tmp_path) if cached else None
    snapshot=session.snapshot if cached else lambda *a,**k:execution.snapshot(tmp_path,*a,**k)
    p=policy('out/listing.stderr')
    rows=next(iter(snapshot(['out'],outputs=True,output_policy=p).values()))['files']
    assert rows[0]=={'name':'listing.stderr','size':0,'sha256':hashlib.sha256(b'').hexdigest()}
    with pytest.raises(ValueError,match='empty output'):
        snapshot(['out'],outputs=True)
    (d/'required.root').write_bytes(b'')
    with pytest.raises(ValueError):
        snapshot(['out'],outputs=True,output_policy=p)
    if session:session.close()


@pytest.mark.parametrize('name',['result.json','identity.raw','compiled.so','result.root','unlisted.stderr','arbitrary.stdout'])
def test_stderr_policy_does_not_admit_other_zeros(tmp_path,name):
    d=tmp_path/'out';d.mkdir()
    (d/'listing.stderr').write_bytes(b'')
    (d/'required.log').write_text('nonempty')
    (d/name).write_bytes(b'')
    with pytest.raises(ValueError):execution.snapshot(tmp_path,['out'],outputs=True,output_policy=policy('out/listing.stderr'))


def test_stderr_plan_checkin_and_stage_are_prospectively_bound(tmp_path):
    s=specification(tmp_path)
    s.update(max_attempts=1,output_policy=policy())
    s['review_policy']['policy'].update(max_redos=0,allowed_changed_paths=[])
    s['review_policy']['correction_contract']={'task_fields':[],'input_slots':[]}
    sp=tmp_path/'spec.json';atomic_json(sp,s);rd=tmp_path/'run'
    p=science.plan(rd,sp)
    assert p['stage_binding']['output_policy']==s['output_policy']
    assert p['stages'][0]['output_policy']==s['output_policy']
    assert read_json(rd/'inputs/checkin1.json')['sections']['i-b']['output_policy']==s['output_policy']
    assert science.verify_plan(rd)==p
    assert not (rd/science.APPROVAL).exists() and not (rd/'execution_attempt.json').exists()


def test_finish_reuse_and_zero_hash_require_exact_stderr_policy(tmp_path):
    (tmp_path/'source.txt').write_text('source input control')
    p=policy('out/listing.stderr')
    b=execution.plan_stage(tmp_path,'science',['/usr/bin/true'],['source.txt'],['out'],[],tmp_path,output_policy=p)
    r=execution.begin_attempt(tmp_path,'science',b,'logs/science.log')
    atomic_json(tmp_path/'out/result.json',{'status':'passed','claim':'pure engineering receipt fixture'})
    (tmp_path/'out/listing.stderr').write_bytes(b'')
    (tmp_path/'logs/science.log').write_text('No worker started; retained synthetic receipt control.\n')
    assert execution.finish_attempt(tmp_path,r,0)==0
    assert execution.reusable(tmp_path,'science',b)
    assert any(row['name']=='listing.stderr' and row['size']==0 for row in next(iter(r['output_snapshot'].values()))['files'])
    b2=execution.plan_stage(tmp_path,'science',['/usr/bin/true'],['source.txt'],['out'],[],tmp_path,output_policy=policy('out/other.stderr'))
    assert not execution.reusable(tmp_path,'science',b2)
    (tmp_path/'out/listing.stderr').write_text('changed')
    assert not execution.reusable(tmp_path,'science',b)
