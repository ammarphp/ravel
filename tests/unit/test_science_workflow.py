"""Exercise real bounded CLI/lifecycle execution, including hostile artifact drift."""
import json
from pathlib import Path
import pytest
from ravel.workflow import science
from ravel.workflow.state_io import read_json, atomic_json
from ravel.physics.science_worker import main as worker


def fixture(tmp_path):
    from test_scientific_quantities import contract, event
    atomic_json(tmp_path/'contract.json',contract())
    (tmp_path/'records.jsonl').write_text('\n'.join(json.dumps(e) for e in [event('a',[[.5]],2),event('b',[[2]],-1)])+'\n')
    spec={'schema_version':1,'mode':'quantities','source':'synthetic signed-weight control',
          'assumptions':['Synthetic numbers validate transport, not physics'],'max_seconds':45,
          'approval_mode':'scripted_yes','task':{'contract':'contract.json','records':'records.jsonl'}}
    atomic_json(tmp_path/'spec.json',spec)
    return tmp_path/'run',tmp_path/'spec.json'


def test_real_plan_approve_supervised_run_and_resume(tmp_path):
    rd,sp=fixture(tmp_path)
    science.plan(rd,sp)
    assert science.packet(rd)['execution']['status']=='planned'
    with pytest.raises((OSError,ValueError)):
        science.run(rd)
    science.approve(rd,'User-authorized synthetic engineering control',scripted=True)
    assert science.packet(rd)['execution']['status']=='approved'
    assert science.run(rd)==0
    r=read_json(rd/'outputs/result.json')
    assert r['quantities']['values']['nominal']==[2,-1]
    assert science.packet(rd)['lifecycle_verdict']=='PASS'
    assert science.run(rd,resume=True)==0
    with pytest.raises(ValueError,match='attempt is spent'):
        science.run(rd)
    before=read_json(rd/'execution_attempt.json')
    before['budget_seconds']=100000
    atomic_json(rd/'execution_attempt.json',before)
    assert science.packet(rd)['lifecycle_verdict']=='FAIL'


def test_changed_approval_description_cannot_authorize_different_inputs(tmp_path):
    rd,sp=fixture(tmp_path); science.plan(rd,sp)
    c=read_json(rd/'inputs/checkin1.json'); c['sections']['iv']['max_seconds']=9000
    atomic_json(rd/'inputs/checkin1.json',c)
    with pytest.raises(ValueError,match='check-in'):
        science.approve(rd,'yes',scripted=True)


def test_stale_scientific_input_and_direct_worker_bypass(tmp_path):
    rd,sp=fixture(tmp_path); science.plan(rd,sp)
    science.approve(rd,'yes',scripted=True)
    with pytest.raises((ValueError,OSError)):
        worker([str(rd)])
    (tmp_path/'records.jsonl').write_text('{}\n')
    with pytest.raises(ValueError,match='stale study'):
        science.run(rd)
    assert not (rd/'execution_attempt.json').exists()


def test_failure_is_preserved_and_spends_approved_attempt(tmp_path):
    rd,sp=fixture(tmp_path)
    (tmp_path/'records.jsonl').write_text('{"event_id":"bad"}\n')
    science.plan(rd,sp); science.approve(rd,'yes',scripted=True)
    assert science.run(rd)!=0
    assert science.packet(rd)['execution']['status']=='failed'
    assert (rd/'logs/science-worker.log').is_file()
    with pytest.raises(ValueError,match='attempt is spent'):
        science.run(rd,resume=True)


def test_failed_scientific_comparison_retained_as_failed(tmp_path):
    spec={'schema_version':1,'mode':'domain','source':'synthetic lifetime benchmark',
          'assumptions':['engineering fixture'],'max_seconds':30,'approval_mode':'scripted_yes',
          'task':{'domain':'llp','config':{}}}
    atomic_json(tmp_path/'bad.json',spec)
    with pytest.raises(ValueError):
        science.plan(tmp_path/'run',tmp_path/'bad.json')
    assert not (tmp_path/'run').exists()


def test_approval_mode_and_destination_reuse_refused(tmp_path):
    rd,sp=fixture(tmp_path); science.plan(rd,sp)
    with pytest.raises(ValueError,match='approval mode'):
        science.approve(rd,'yes',scripted=False)
    with pytest.raises(FileExistsError):
        science.plan(rd,sp)


def test_active_attempt_is_not_reported_as_a_failed_scientific_result(tmp_path,monkeypatch):
    rd,sp=fixture(tmp_path); p=science.plan(rd,sp); science.approve(rd,'yes',scripted=True)
    atomic_json(rd/'execution_attempt.json',{'attempt':1,'plan_sha256':science.execution.file_hash(rd/science.PLAN),'budget_seconds':45})
    original=science.execution.load_execution
    monkeypatch.setattr(science.execution,'load_execution',lambda p:{'stages':{'science':{'status':'running'}}})
    packet=science.packet(rd)
    assert packet['execution']['status']=='running'
    assert packet['lifecycle_verdict']=='PENDING'
