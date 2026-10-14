"""Actual shared launch observations; synthetic receipts, no worker/native process."""

from method_decision_fixture import admit_method
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.workflow import science,execution,launch_authorization as launch
from ravel.workflow.state_io import atomic_json,read_json
from ravel.workflow.validation_io import ValidationSession
from ravel.validation import likelihood_parity
from test_physics_review import policy
from test_science_validation_session import token,context_for

@pytest.fixture
def selected_launch(tmp_path,monkeypatch,request):
    payload=tmp_path/'runtime.bin';payload.write_bytes(b'phase-control-runtime-'*4096)
    inventory={'schema_version':1,'files':[{'path':str(payload),'sha256':execution.file_hash(payload)}]}
    implementation=SimpleNamespace(validate=lambda task:None,
        inputs=lambda task,base:likelihood_parity.runtime_files(inventory),
        _validation_inputs=lambda task,base,session:likelihood_parity.runtime_files(inventory,_session=session))
    monkeypatch.setattr(science,'adapter',lambda spec:implementation)
    p=policy();p.update(allowed_stages=['science'],allowed_changed_paths=[],max_redos=0)
    spec={'schema_version':2,'mode':'likelihood-parity','source':'Synthetic launch observation control',
        'assumptions':['No scientific worker, subprocess or physics claim'],'max_seconds':45,'max_attempts':1,
        'approval_mode':'scripted_yes','task':{'input':str(payload)},
        'review_policy':{'schema_version':1,'policy':p,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    declared=getattr(request,'param',False)
    if declared:
        spec['output_policy']={'schema_version':1,'allow_empty_directory_members':[
            {'path':'outputs/attempt-1/framework/__init__.py','role':'python_package_marker'},
            {'path':'outputs/attempt-1/incidental.log','role':'incidental_log'}]}
    source=tmp_path/'spec.json';atomic_json(source,spec);rd=tmp_path/'run';science.plan(rd,source); admit_method(rd)
    science.approve(rd,'Synthetic engineering fixture only',scripted=True);token(rd)
    selected=science.launch_binding(rd,'science');record=execution.begin_attempt(rd,'science',selected['binding'],selected['stage']['log'])
    return SimpleNamespace(rd=rd,payload=payload,selected=selected,record=record,
                           context=context_for(selected,rd),declared=declared)

def track_target(monkeypatch,payload):
    opened=Path.open;factory=execution._validation_session;reads=[];sessions=[]
    def stream(path,*args,**kwargs):
        if path==payload and args and args[0]=='rb':reads.append(path)
        return opened(path,*args,**kwargs)
    def session(*a,**k):
        value=factory(*a,**k);sessions.append(value);return value
    monkeypatch.setattr(Path,'open',stream);monkeypatch.setattr(execution,'_validation_session',session)
    return reads,sessions

@pytest.mark.parametrize('selected_launch',[False,True],indirect=True)
def test_launch_reads_once_closes_before_popen_and_keeps_fresh_worker_finish(selected_launch,monkeypatch):
    v=selected_launch;reads,sessions=track_target(monkeypatch,v.payload);calls=[]
    def popen(command,**kwargs):
        assert len(reads)==1 and len(sessions)==1 and sessions[0].closed and not sessions[0].hashes
        assert command==v.selected['stage']['command'];calls.append(command);return SimpleNamespace(pid=424242)
    monkeypatch.setattr(launch.subprocess,'Popen',popen)
    launch.authorized_popen(v.rd,'science',v.selected['stage']['command'],context=v.context)
    assert len(calls)==1 and [e['event'] for e in launch._events(v.rd)]==['authorized','launched']
    v.record.update(supervisor_pid=os.getppid(),child_pid=os.getpid(),child_identity='synthetic-identity')
    execution._update(v.rd,'science',v.record);monkeypatch.setattr(execution,'process_identity',lambda pid:'synthetic-identity')
    science.verify_worker(v.rd);assert len(reads)==2 and len(sessions)==2 and sessions[-1] is not sessions[0]
    out=v.rd/v.selected['stage']['outputs'][0];out.mkdir(parents=True);atomic_json(out/'result.json',{'synthetic':True,'physics_validated':False})
    (v.rd/v.selected['stage']['log']).write_text('No actual worker\n')
    if v.declared:
        assert v.record['output_policy']==v.selected['stage']['output_policy']
        (out/'framework').mkdir();(out/'framework/__init__.py').touch();(out/'incidental.log').touch()
    assert execution.finish_attempt(v.rd,v.record,0)==0 and len(reads)==3

@pytest.mark.parametrize('mutation',['append_bytes','append_context','append_command','final_bytes',
    'final_ledger','final_context','final_runtime','final_symlink','final_parent_symlink'])
def test_late_launch_mutation_refuses_before_popen(selected_launch,monkeypatch,mutation):
    v=selected_launch;append=launch._append;finish=ValidationSession.finish
    def change(event=None):
        if mutation in ('append_context','final_context'):v.context['max_seconds']+=1
        elif mutation=='append_command':event['command'].append('--forged-command')
        elif mutation=='final_ledger':
            state=read_json(v.rd/execution.STATE_NAME);state['revision']+=1;atomic_json(v.rd/execution.STATE_NAME,state)
        elif mutation=='final_runtime':monkeypatch.setenv('OMP_NUM_THREADS','987')
        elif mutation=='final_symlink':
            target=v.payload.with_name('same.bin');target.write_bytes(v.payload.read_bytes());v.payload.unlink();v.payload.symlink_to(target)
        elif mutation=='final_parent_symlink':
            parent=v.payload.parent;target=parent.with_name(parent.name+'-moved');parent.rename(target);parent.symlink_to(target,target_is_directory=True)
        else:
            before=v.payload.stat();raw=v.payload.read_bytes();v.payload.write_bytes(b'X'+raw[1:])
            os.utime(v.payload,ns=(before.st_atime_ns,before.st_mtime_ns))
    def retained(root,event):
        result=append(root,event)
        if event['event']=='authorized' and mutation.startswith('append_'):change(event)
        return result
    def census(session):
        if mutation.startswith('final_'):change()
        return finish(session)
    monkeypatch.setattr(launch,'_append',retained);monkeypatch.setattr(ValidationSession,'finish',census)
    monkeypatch.setattr(launch.subprocess,'Popen',lambda *a,**k:pytest.fail('changed launch reached Popen'))
    with pytest.raises(ValueError,match='changed|symlink|runtime|supplied state'):
        launch.authorized_popen(v.rd,'science',v.selected['stage']['command'],context=v.context)
    assert [e['event'] for e in launch._events(v.rd)]==['authorized']

@pytest.mark.parametrize('operation',['capture','verify_launch'])
@pytest.mark.parametrize('invalid',['closed','other_run'])
def test_launch_session_rejects_closed_or_cross_run(selected_launch,monkeypatch,operation,invalid):
    v=selected_launch;rd=v.rd if invalid=='closed' else v.rd.parent/'other';rd.mkdir(exist_ok=True)
    session=execution._validation_session(rd)
    if invalid=='closed':session.close()
    try:
        if operation=='capture':
            with pytest.raises(ValueError,match='closed or cross-run'):
                launch._capture_science(v.rd,'science',v.selected['stage']['command'],v.context,_session=session)
        else:
            errors=science.verify_launch(v.rd,'science',v.selected['stage']['command'],v.context,_session=session)
            assert len(errors)==1
            assert errors == ['closed or cross-run validation session']
    finally:session.close()

def test_independent_capture_calls_reread_and_detect_changed_bytes(selected_launch,monkeypatch):
    v=selected_launch;reads,sessions=track_target(monkeypatch,v.payload)
    for index in range(2):
        launch._capture_science(v.rd,'science',v.selected['stage']['command'],v.context)
        assert len(reads)==index+1 and sessions[-1].closed
    assert sessions[0] is not sessions[1]
    raw=v.payload.read_bytes();v.payload.write_bytes(b'X'+raw[1:])
    with pytest.raises(ValueError,match='runtime bytes differ'):
        launch._capture_science(v.rd,'science',v.selected['stage']['command'],v.context)
    assert len(reads)==3 and all(s.closed and not s.hashes for s in sessions)
