"""Prospective output-policy lifecycle controls; no worker, native call, or old run mutation."""

from method_decision_fixture import admit_method
from copy import deepcopy
import hashlib
from pathlib import Path
import sys

import pytest
from ravel.workflow import execution,science,physics_review as review,stage_supervisor
from ravel.workflow.state_io import atomic_json,read_json
from test_science_review_envelope import specification


def policy(path='outputs/attempt-1/native-work/source/combine_logger.out'):
    return {'schema_version':1,'allow_empty_directory_members':[{'path':path,'role':'incidental_log'}]}


def spec(base, *, declared=True):
    s=specification(base)
    s['max_attempts']=1
    s['review_policy']['policy'].update(max_redos=0,allowed_changed_paths=[])
    s['review_policy']['correction_contract']={'task_fields':[],'input_slots':[]}
    if declared:s['output_policy']=policy()
    return s


def planned(base, *, declared=True):
    sp=base/'spec.json';atomic_json(sp,spec(base,declared=declared));rd=base/'run'
    p=science.plan(rd,sp); admit_method(rd)
    return rd,p


def token(rd):
    a={'attempt':1,'plan_sha256':execution.file_hash(rd/science.PLAN),'budget_seconds':45,
       'started_utc':execution.utc_now(),'correction_id':None,'correction_plan_sha256':None}
    atomic_json(rd/'execution_attempt.json',a)
    atomic_json(rd/'logs/science-attempts/00000001.json',a)


def record(base, *, declared=True):
    base.mkdir(exist_ok=True)
    (base/'source.json').write_text('{"input":"unchanged"}')
    kw={'output_policy':policy('out/combine_logger.out')} if declared else {}
    b=execution.plan_stage(base,'science',[sys.executable,'-c','pass'],['source.json'],['out'],[],base,**kw)
    r=execution.begin_attempt(base,'science',b,'logs/science.log')
    atomic_json(base/'out/result.json',{'status':'passed','required_values':[1,2,3]})
    (base/'out/combine_logger.out').write_bytes(b'')
    (base/'logs/science.log').write_text('Pure engineering receipt; no worker launched.\n')
    return b,r


def test_prospective_declaration_requires_no_future_output(tmp_path):
    rd,p=planned(tmp_path)
    assert not (rd/'outputs').exists()
    assert p['stages'][0]['output_policy']==policy()
    assert p['stage_binding']['output_policy']==policy()
    assert read_json(rd/'inputs/checkin1.json')['sections']['i-b']['output_policy']==policy()
    assert p['stage_binding']['fingerprint']==execution.digest({k:v for k,v in p['stage_binding'].items() if k!='fingerprint'})
    assert science.verify_plan(rd)==p


def test_absent_declaration_preserves_existing_shapes(tmp_path):
    rd,p=planned(tmp_path,declared=False)
    for mapping in [p['stages'][0],p['stage_binding'],read_json(rd/'inputs/checkin1.json')['sections']['i-b']]:
        assert 'output_policy' not in mapping
    assert science.verify_plan(rd)==p


@pytest.mark.parametrize('change',['null','schema','future_attempt','critical','multi_attempt','legacy'])
def test_invalid_scientific_scope_refuses_before_run_directory(tmp_path,change):
    s=spec(tmp_path)
    if change=='null':s['output_policy']=None
    if change=='schema':s['output_policy']['schema_version']=True
    if change=='future_attempt':s['output_policy']=policy('outputs/attempt-2/empty.log')
    if change=='critical':s['output_policy']=policy('outputs/attempt-1/limit.root')
    if change=='multi_attempt':
        s['max_attempts']=2;s['review_policy']['policy']['max_redos']=1
    if change=='legacy':
        s['schema_version']=1
        del s['review_policy'];del s['max_attempts']
    atomic_json(tmp_path/'bad.json',s)
    with pytest.raises(ValueError):science.plan(tmp_path/'run',tmp_path/'bad.json')
    assert not (tmp_path/'run').exists()


@pytest.mark.parametrize('target',['spec','stage','binding','checkin'])
def test_policy_mutation_or_removal_invalidates_plan(tmp_path,target):
    rd,p=planned(tmp_path)
    if target=='spec':
        v=read_json(rd/science.SPEC);v['output_policy']=policy('outputs/attempt-1/other.log');atomic_json(rd/science.SPEC,v)
    elif target in ('stage','binding'):
        v=read_json(rd/science.PLAN)
        (v['stages'][0] if target=='stage' else v['stage_binding']).pop('output_policy')
        atomic_json(rd/science.PLAN,v)
    else:
        v=read_json(rd/'inputs/checkin1.json');v['sections']['i-b'].pop('output_policy');atomic_json(rd/'inputs/checkin1.json',v)
    with pytest.raises(ValueError):science.verify_plan(rd)


def test_exact_finish_cached_validation_and_reuse_preserve_zero_hash(tmp_path):
    b,r=record(tmp_path)
    assert execution.finish_attempt(tmp_path,r,0)==0
    assert execution.stage_errors(tmp_path,'science')==[]
    assert execution.reusable(tmp_path,'science',b)
    rows=next(iter(r['output_snapshot'].values()))['files']
    assert rows[0]=={'name':'combine_logger.out','size':0,'sha256':hashlib.sha256(b'').hexdigest()}
    stage={'stage':'science','command':b['command'],'cwd':b['cwd'],'inputs':b['inputs'],'outputs':b['outputs'],'depends_on':[],**execution.output_policy_fields(b)}
    assert execution.validate_completed_execution(tmp_path,[stage])==[]
    stage.pop('output_policy')
    assert any('output policy differs' in e for e in execution.validate_completed_execution(tmp_path,[stage]))


def test_absent_policy_finish_still_fails(tmp_path):
    _,r=record(tmp_path,declared=False)
    assert execution.finish_attempt(tmp_path,r,0)==3
    assert r['status']=='failed' and 'empty output:' in r['error']


def test_changed_policy_in_flight_cannot_finish_successfully(tmp_path):
    _,r=record(tmp_path)
    r['output_policy']['allow_empty_directory_members'][0]['path']='out/other.log'
    assert execution.finish_attempt(tmp_path,r,0)==3
    assert 'specification changed' in r['error']


def test_adding_policy_to_old_receipt_cannot_repair_it(tmp_path):
    _,r=record(tmp_path,declared=False)
    assert execution.finish_attempt(tmp_path,r,0)==3
    before=execution.file_hash(tmp_path/execution.STATE_NAME)
    assert execution.stage_errors(tmp_path,'science')==['stage science is failed']
    assert execution.file_hash(tmp_path/execution.STATE_NAME)==before


@pytest.mark.parametrize('change',['logger_removed','unexpected_zero','malformed_json','empty_root','logger_changed'])
def test_reuse_refuses_delivery_mutations(tmp_path,change):
    b,r=record(tmp_path);assert execution.finish_attempt(tmp_path,r,0)==0
    if change=='logger_removed':(tmp_path/'out/combine_logger.out').unlink()
    if change=='unexpected_zero':(tmp_path/'out/unknown.log').write_bytes(b'')
    if change=='malformed_json':(tmp_path/'out/result.json').write_text('{')
    if change=='empty_root':(tmp_path/'out/limit.root').write_bytes(b'')
    if change=='logger_changed':(tmp_path/'out/combine_logger.out').write_text('changed')
    assert execution.stage_errors(tmp_path,'science')
    assert not execution.reusable(tmp_path,'science',b)


def test_launch_context_policy_presence_and_value_are_compared(tmp_path):
    rd,p=planned(tmp_path);science.approve(rd,'Synthetic source-only engineering test approval',scripted=True);token(rd)
    selected=science.launch_binding(rd,'science')
    normalized=review._stage_spec(rd,{**selected['stage'],'inputs':selected['binding']['inputs']})
    context={'stage_spec':normalized,'max_seconds':45,'review_action':'bulk'}
    assert science.verify_launch(rd,'science',selected['stage']['command'],context)==[]
    context['stage_spec'].pop('output_policy')
    assert science.verify_launch(rd,'science',selected['stage']['command'],context)
    context['stage_spec']['output_policy']=policy('outputs/attempt-1/other.log')
    assert science.verify_launch(rd,'science',selected['stage']['command'],context)


def test_exact_one_attempt_refuses_correction_before_any_dispatch(tmp_path,monkeypatch):
    rd,p=planned(tmp_path);science.approve(rd,'Synthetic engineering envelope',scripted=True)
    calls=[];monkeypatch.setattr(stage_supervisor,'supervise',lambda *a,**k:calls.append(k))
    with pytest.raises(ValueError):science.correct(rd,actor_id='decider',changed_paths=[],recheck_checks=[],max_seconds=30)
    assert calls==[]


def test_policy_cannot_be_borrowed_by_generic_stage_before_recovery_or_popen(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(stage_supervisor,'_recover_previous_attempt',lambda *a:calls.append('recovery'))
    monkeypatch.setattr(stage_supervisor.subprocess,'Popen',lambda *a,**k:calls.append('Popen'))
    with pytest.raises(ValueError,match='prospective version 2'):
        stage_supervisor.supervise('science',tmp_path,0,'logs/science.log',[sys.executable,'-c','pass'],kill_secs=1,outputs=['out'],output_policy=policy('out/log.out'), _engineering_only=True)
    assert calls==[]


def test_policy_is_independent_of_caller_mutation(tmp_path):
    declared=policy('out/log.out')
    b=execution.plan_stage(tmp_path,'science',[sys.executable,'-c','pass'],[],['out'],[],tmp_path,output_policy=declared)
    old=deepcopy(b);declared['allow_empty_directory_members'][0]['path']='out/other.log'
    assert b==old


# The negative generic-policy control carries no inherited scientific agent session.
pytestmark = pytest.mark.usefixtures("engineering_session")
