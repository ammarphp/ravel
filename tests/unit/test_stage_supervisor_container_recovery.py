"""Mechanical controls only: no Podman, VM, scientific worker or host signal."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,signal
import pytest
from ravel.workflow import stage_supervisor as s
from ravel.workflow import execution,science,physics_review,review_enforcement,launch_authorization
from ravel.physics import simpleanalysis_container as c,routine_build,simpleanalysis_events

REAL_EVENT_PLAN=simpleanalysis_events.execution_plan

@pytest.fixture(params=('routine-build','simpleanalysis-built'))
def control(tmp_path,monkeypatch,request):
    root=tmp_path
    inputs=root/'inputs';inputs.mkdir()
    for name in ('science-plan','science-approval'):
        (inputs/(name+'.json')).write_text(json.dumps({'base_dir':str(root), **({'schema_version':2} if name=='science-plan' else {})}))
    from method_decision_fixture import admit_method
    admit_method(root, refresh=False)
    config=inputs/'build.json';config.write_text('{"schema_version":3}')
    job={'schema_version':1,'kind':'simpleanalysis-container-job',
         'transport':{'image':{'config_sha256':'c'*64},'client':{},'environment':{},'connection':'test'},
         'input_directory':str(root/'prepared'),'input_files':{},
         'guest_entrypoint':['/bin/bash','/tmp/ravel-input/run.sh'],
         'resources':{'max_seconds':30,'workers':1,'memory_mib':128,'pids':256,'network':'none','pull':'never'},
         'physics_validated':False}
    jp=inputs/'container.json';jp.write_text(json.dumps(job))
    fact={'name':'.','size':jp.stat().st_size,'sha256':execution.file_hash(jp)}
    spec={'command':['NEVER-EXECUTED'],'runtime':{},'inputs':[str(jp)],'outputs':['outputs/attempt-1'],
          'input_snapshot':{str(jp):{'kind':'file','files':[fact]}},'parents':{},'cwd':str(root)}
    spec['fingerprint']=execution.digest(spec)
    record={**deepcopy(spec),'stage':'science','attempt_id':'a'*32,
            'attempt_record':'logs/execution/science/'+('a'*32)+'/record.json',
            'status':'running','child_pid':None,'child_identity':None}
    directory=root/Path(record['attempt_record']).parent;directory.mkdir(parents=True)
    execution._update(root,'science',record)
    state=SimpleNamespace(root=root,job=job,jp=jp,spec=spec,record=record,calls=[],launches=[],
                          scenario='owned',stop=False,failure_ledger_commands=[],child=SimpleNamespace(pid=23456,returncode=0,
                              poll=lambda:0,ravel_authorization={'test_only':True}),
                          out=root/'outputs/attempt-1')
    state.backend=request.param
    state.task={'backend':'routine-build','input':str(config)} if request.param=='routine-build' else {
        'backend':'simpleanalysis-built','routine':'DeclaredRoutine','build_receipt':str(config),
        'build_plan':str(config),'events':str(config),'object_contract':str(config),
        'regions':['DeclaredRegion'],'container_plan':str(jp)}
    state.plan_calls=[]
    monkeypatch.setattr(science,'execution_spec',lambda rd:{'mode':'analyze','task':state.task})
    monkeypatch.setattr(science,'launch_binding',lambda rd,stage:{'binding':spec,'stage':{'outputs':spec['outputs']},'max_seconds':50})
    monkeypatch.setattr(routine_build,'build_plan',lambda task,base,out:{'output_root':str(out),
        'container_job':job,'container_plan':{'path':str(jp),'sha256':execution.file_hash(jp)}})
    def event_plan(task,base,out):
        assert task==state.task and base==root and out==state.out
        state.plan_calls.append((deepcopy(task),str(base),str(out)))
        return {'schema_version':1,'kind':'source-built-simpleanalysis-event-plan',
                'output_directory':str(getattr(state,'event_output',out)),
                'container_job':getattr(state,'event_job',job)}
    monkeypatch.setattr(simpleanalysis_events,'execution_plan',event_plan)
    monkeypatch.setattr(c,'validate_transport',lambda transport,**kw:transport)
    def call(client,args,*,cleanup=False,check=True):
        assert cleanup and 0 < client.deadline-c.time.monotonic() <= 60
        assert client.output != state.out
        state.calls.append(args)
        if state.scenario=='queryfail':raise TimeoutError('mock lost client')
        if args[:2]==['container','exists']:
            return SimpleNamespace(returncode=1 if state.scenario=='absent' else 0,stdout=b'')
        if args[:2]==['container','stop']:
            state.stop=True
            return SimpleNamespace(returncode=0,stdout=b'')
        assert args[:2]==['container','inspect']
        name='ravel-sa-'+hashlib.sha256((c.plan_hash(job)+str(state.out.resolve())).encode()).hexdigest()[:24]
        observation={'Id':'d'*64,'Name':name,'Image':'sha256:'+'c'*64,
            'Config':{'Labels':{'org.ravel.plan':c.plan_hash(job),'org.ravel.job':name}},
            'State':{'Running':not state.stop or state.scenario=='stillrunning',
                     'Pid':0 if state.stop and state.scenario!='guestpid' else 123}}
        if state.scenario=='unowned':observation['Config']['Labels']['org.ravel.plan']='e'*64
        if state.scenario=='cidreuse' and state.stop:observation['Id']='b'*64
        return SimpleNamespace(returncode=0,stdout=json.dumps([observation]).encode())
    monkeypatch.setattr(c._Client,'call',call)
    def forbid(*a,**k):pytest.fail('unconfigured process or signal operation')
    # Descriptive platform metadata can probe uname through subprocess.run.
    # Keep this mechanical fixture's process allowlist closed to failure-ledger calls.
    monkeypatch.setattr(execution.platform, 'platform', lambda: 'synthetic-mechanical-platform')
    monkeypatch.setattr(s.subprocess,'Popen',forbid)
    # The machine fence's process census would list real processes; this mechanical world has none.
    from ravel.workflow import machine_lease
    monkeypatch.setattr(machine_lease,'token_census',lambda:{})
    # Steering's post-run liveness probe (signal 0) would reach the forbidden killpg; this group is gone.
    from ravel.workflow import graph_substrate
    monkeypatch.setattr(graph_substrate,'_group_alive',lambda pgid:False)
    def ledger_only(command, **kwargs):
        assert command[:6] == [s.sys.executable, str(Path(s.__file__).parent / 'workflow_state.py'),
                               'record', '--kind', 'failure', '--rundir']
        assert kwargs == {'capture_output': True, 'text': True, 'timeout': 30}
        state.failure_ledger_commands.append(command)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(s.subprocess,'run',ledger_only)
    monkeypatch.setattr(s.os,'killpg',forbid)
    monkeypatch.setattr(s.signal,'signal',lambda *a:signal.SIG_DFL)
    monkeypatch.setattr(execution,'process_group_members',lambda pid:[])
    monkeypatch.setattr(execution,'process_identity',lambda pid:'owned-host')
    return state

def prepare(v,kill=100,grace=60):
    s._prepare_container_recovery(v.root,'science',v.spec,v.record,kill,grace)

def integration(v,monkeypatch,launch_error=None):
    # This helper exercises a new launch, not an unregistered RUNNING prior attempt.
    execution._update(v.root,'science',{**v.record,'status':'failed'})
    monkeypatch.setattr(execution,'plan_stage',lambda *a,**k:v.spec)
    monkeypatch.setattr(physics_review,'_science_run',lambda *a:True)
    monkeypatch.setattr(science,'review_enabled',lambda *a:True)
    monkeypatch.setattr(science,'verify_launch',lambda *a:[])
    monkeypatch.setattr(review_enforcement,'before_stage',lambda *a,**k:None)
    monkeypatch.setattr(review_enforcement,'finish_correction_failure',lambda *a:None)
    def begin(*a):
        v.record.pop('container_recovery_plan',None)
        v.record['status']='running'
        execution._update(v.root,'science',v.record)
        return v.record
    monkeypatch.setattr(execution,'begin_attempt',begin)
    def popen(*a,**k):
        snapshot=s._container_snapshot(v.root,v.record)
        persisted=execution.load_execution(v.root)['stages']['science']
        assert persisted['container_recovery_plan']==v.record['container_recovery_plan']
        assert snapshot['job']==v.job and not v.out.exists()
        v.launches.append(True)
        v.out.mkdir(parents=True)
        (v.out/'worker-receipt.json').write_text('{"cid":"FORGED","status":"quiescent"}')
        if launch_error:raise launch_error
        return v.child
    monkeypatch.setattr(launch_authorization,'authorized_popen',popen)
    def finish(root,record,code,reason):
        record.update(status='succeeded' if code==0 else 'failed',exit_code=code,error=reason)
        execution._update(root,'science',record)
        return code
    monkeypatch.setattr(execution,'finish_attempt',finish)
    return s.supervise('science',v.root,0,'logs/science.log',['NEVER-EXECUTED'],
                        kill_secs=100,poll=.01,grace=10,inputs=v.spec['inputs'],
                        outputs=v.spec['outputs'],cwd=str(v.root))

def test_container_recovery_write_once_pin_before_popen_and_no_output_precreation(control):
    v=control;prepare(v)
    snapshot=s._container_snapshot(v.root,v.record)
    assert snapshot['output']==str(v.out) and snapshot['cleanup_seconds']==60
    assert snapshot['worker_seconds']==40 and not v.out.exists()
    assert (v.root/v.record['container_recovery_plan']['path']).stat().st_mode & 0o222==0
    with pytest.raises(FileExistsError):prepare(v)
    assert v.calls==[]

@pytest.mark.parametrize('defect',['selection','output','binding','unbound_job','changed_job','reserve'])
def test_container_recovery_prelaunch_scope_rejection_has_no_client_or_worker(control,monkeypatch,defect):
    v=control
    if defect=='selection':monkeypatch.setattr(science,'launch_binding',lambda *a:{'binding':{},'stage':{'outputs':v.spec['outputs']}})
    if defect=='output':v.spec['outputs'].append('outputs/other')
    if defect=='binding':v.spec['input_snapshot'][str(v.jp)]['files'][0]['sha256']='0'*64
    if defect=='unbound_job':v.spec['input_snapshot'].clear()
    if defect=='changed_job':v.jp.write_text('{"different":true}')
    with pytest.raises(ValueError):prepare(v,kill=30 if defect=='reserve' else 100)
    assert v.calls==[] and v.launches==[] and not v.out.exists()

@pytest.mark.parametrize('scenario,held,stop',[
    ('owned',False,True),('absent',False,False),('unowned',True,False),
    ('queryfail',True,False),('stillrunning',True,True),('guestpid',True,True),('cidreuse',True,True)])
def test_container_recovery_actual_helper_ownership_and_quiescence_controls(control,scenario,held,stop):
    v=control;prepare(v);v.scenario=scenario
    v.out.mkdir(parents=True);worker=v.out/'container-cleanup.json';worker.write_text('{"status":"FORGED"}')
    before=worker.read_bytes()
    result=s._recover_container(v.root,v.record,'control')
    assert result['requires_recovery'] is held and v.stop is stop
    assert worker.read_bytes()==before
    assert result['observation']['path'].startswith(str(Path(v.record['attempt_record']).parent))
    assert all(args[0]=='container' and args[1] in ('exists','inspect','stop') for args in v.calls)
    assert not any(args[:2]==['container','stop'] for args in v.calls) if not stop else True

@pytest.mark.parametrize('scenario,expected',[('owned',0),('unowned',3),('queryfail',3),('guestpid',3)])
def test_container_recovery_zero_exit_host_still_observes_guest_and_holds_unknown(control,monkeypatch,scenario,expected):
    v=control;v.scenario=scenario
    assert integration(v,monkeypatch)==expected
    assert v.launches==[True] and v.calls
    assert v.record['container_cleanup']['requires_recovery'] is (expected!=0)
    if expected:
        failure = json.loads((v.root / 'logs/science.failure.json').read_text())
        assert failure['cleanup']['container'] == v.record['container_cleanup']
        assert len(v.failure_ledger_commands) == 1
    assert (v.out/'worker-receipt.json').read_text()=='{"cid":"FORGED","status":"quiescent"}'

@pytest.mark.parametrize('failure',[RuntimeError('lost client before CID'),KeyboardInterrupt('client killed')])
def test_container_recovery_client_loss_even_without_recorded_host_pid_recovers_guest(control,monkeypatch,failure):
    v=control
    assert integration(v,monkeypatch,failure) in (2,130)
    assert v.record['child_pid'] is None and v.stop is True
    assert v.record['container_cleanup']['requires_recovery'] is False
    assert v.record['status']=='failed'
    failure = json.loads((v.root / 'logs/science.failure.json').read_text())
    assert failure['cleanup']['container'] == v.record['container_cleanup']
    assert len(v.failure_ledger_commands) == 1

def test_container_recovery_resume_recovery_precedes_changed_input_planning(control,monkeypatch):
    v=control;prepare(v)
    v.record.update(child_pid=99999,child_identity='original-host')
    execution._update(v.root,'science',v.record)
    monkeypatch.setattr(execution,'process_identity',lambda pid:None)
    def absent(pid,sig):
        assert sig==0
        raise ProcessLookupError('known old host absent')
    monkeypatch.setattr(s.os,'kill',absent)
    def reject(*a,**kw):
        pytest.fail('absent host without descendant containment reached new planning')
    monkeypatch.setattr(execution,'plan_stage',reject)
    with pytest.raises(ValueError,match='recovery remains held'):
        s.supervise('science',v.root,0,'logs/science.log',['NEVER-EXECUTED'],kill_secs=100,grace=10,resume=True,authorization_plan={'compute_plan':'full'})
    assert v.stop and not v.launches

def test_container_recovery_reused_host_pid_never_signaled_guest_cleanup_independent(control,monkeypatch):
    v=control;prepare(v)
    v.record.update(child_pid=99999,child_identity='original-host')
    execution._update(v.root,'science',v.record)
    monkeypatch.setattr(execution,'process_identity',lambda pid:'unrelated-reused-host')
    s._recover_container_orphan(v.root,'science')
    with pytest.raises(ValueError,match='ownership'):
        s._recover_orphan(v.root,'science',10)
    assert v.stop and v.record['child_pid']==99999

def test_container_recovery_no_child_pid_does_not_skip_guest_recovery(control):
    v=control;prepare(v)
    s._recover_container_orphan(v.root,'science')
    assert v.stop and v.record['child_pid'] is None

@pytest.mark.parametrize('mutation',['bytes','symlink','output','attempt'])
def test_container_recovery_retained_snapshot_mutation_refuses_before_client(control,mutation):
    v=control;prepare(v);path=v.root/v.record['container_recovery_plan']['path']
    if mutation=='bytes':path.chmod(0o644);path.write_text('{}')
    if mutation=='symlink':raw=path.read_bytes();path.unlink();other=v.root/'other';other.write_bytes(raw);path.symlink_to(other)
    if mutation=='output':v.record['outputs']=['outputs/other']
    if mutation=='attempt':v.record['attempt_id']='b'*32
    execution._update(v.root,'science',v.record)
    with pytest.raises(ValueError):s._recover_container_orphan(v.root,'science')
    assert v.calls==[]

def test_container_recovery_unresolved_guest_blocks_resume_even_with_absent_host(control):
    v=control;prepare(v);v.scenario='queryfail'
    with pytest.raises(ValueError,match='unresolved'):s._recover_container_orphan(v.root,'science')
    assert not v.launches

def test_container_recovery_success_reuse_checks_retained_quiescence_without_new_client(control):
    v=control;prepare(v);s._recover_container(v.root,v.record,'final')
    v.record['status']='succeeded';execution._update(v.root,'science',v.record)
    count=len(v.calls);s._recover_container_orphan(v.root,'science')
    assert len(v.calls)==count
    observation=v.root/v.record['container_cleanup']['observation']['path']
    observation.write_text('{"requires_recovery":false}')
    with pytest.raises(ValueError):s._recover_container_orphan(v.root,'science')
    assert len(v.calls)==count

def test_container_recovery_failure_to_publish_outer_pin_never_launches(control,monkeypatch):
    v=control
    monkeypatch.setattr(execution,'_update',lambda *a: (_ for _ in ()).throw(OSError('ledger unavailable')))
    with pytest.raises(OSError):prepare(v)
    assert not v.calls and not v.launches


def test_container_recovery_missing_durable_plan_pin_holds_even_when_host_record_empty(control):
    v=control;prepare(v);v.record.pop('container_recovery_plan')
    execution._update(v.root,'science',v.record)
    with pytest.raises(ValueError,match='authority is missing'):
        s._recover_container_orphan(v.root,'science')
    assert not v.calls

def test_container_recovery_rehashed_snapshot_cannot_replace_approved_job_bytes(control):
    v=control;prepare(v)
    path=v.root/v.record['container_recovery_plan']['path']
    doc=json.loads(path.read_text());doc['job']['transport']['connection']='unrelated'
    doc['job_input']['canonical_sha256']=execution.digest(doc['job'])
    path.chmod(0o644);path.write_text(json.dumps(doc))
    v.record['container_recovery_plan']['sha256']=execution.file_hash(path)
    execution._update(v.root,'science',v.record)
    with pytest.raises(ValueError,match='job bytes'):
        s._recover_container_orphan(v.root,'science')
    assert not v.calls

def test_container_recovery_changed_current_job_and_qualification_do_not_block_retained_recovery(control):
    v=control;prepare(v)
    v.jp.write_text('{"science":"changed after approved launch"}')
    s._recover_container_orphan(v.root,'science')
    assert v.stop


"""Complete common-path producer race controls; no real client/process/signal."""


def live_prior(v,monkeypatch):
    prepare(v);v.record.update(child_pid=99999,child_identity='owned-producer',status='running')
    execution._update(v.root,'science',v.record)
    v.producer_alive=True;v.late_guest_created=False;v.scenario='absent'
    monkeypatch.setattr(execution,'process_identity',lambda pid:'owned-producer')
    monkeypatch.setattr(execution,'process_group_members',lambda pid:[pid] if v.producer_alive else [])
    monkeypatch.setattr(s.os,'getpgid',lambda pid:pid)
    def terminate(*a,**k):
        assert v.producer_alive and not v.calls
        # Producer creates during bounded fencing, immediately before it dies.
        v.late_guest_created=True;v.scenario='owned';v.producer_alive=False
        return {'requires_recovery':False,'group_state':'empty','remaining_group_members':[]}
    monkeypatch.setattr(s,'_terminate_owned_group',terminate)


def test_container_recovery_input_refusal_occurs_only_after_host_fence_and_late_guest_cleanup(control,monkeypatch):
    v=control;live_prior(v,monkeypatch)
    def refuse(*a,**k):
        assert not v.producer_alive and v.late_guest_created and v.stop
        assert [x[1] for x in v.calls]==['exists','inspect','stop','inspect']
        raise ValueError('current input drift after complete old resource cleanup')
    monkeypatch.setattr(execution,'plan_stage',refuse)
    with pytest.raises(ValueError,match='current input drift'):
        s.supervise('science',v.root,0,'logs/science.log',['NEVER-EXECUTED'],kill_secs=100,grace=10,resume=True,authorization_plan={'compute_plan':'full'})
    assert not v.producer_alive and v.stop and not v.launches


def test_container_recovery_new_attempt_can_be_reached_only_after_fence_and_final_old_guest_observation(control,monkeypatch):
    v=control;live_prior(v,monkeypatch)
    monkeypatch.setattr(execution,'plan_stage',lambda *a,**k:v.spec)
    monkeypatch.setattr(physics_review,'_science_run',lambda *a:False)
    monkeypatch.setattr(review_enforcement,'before_stage',lambda *a,**k:None)
    monkeypatch.setattr(execution,'reusable',lambda *a:False)
    def begin(*a,**k):
        assert not v.producer_alive and v.late_guest_created and v.stop
        assert [x[1] for x in v.calls]==['exists','inspect','stop','inspect']
        raise ValueError('safe new attempt barrier reached')
    monkeypatch.setattr(execution,'begin_attempt',begin)
    with pytest.raises(ValueError,match='safe new attempt'):
        s.supervise('science',v.root,0,'logs/science.log',['NEVER-EXECUTED'],kill_secs=100,grace=10,resume=True,authorization_plan={'compute_plan':'full'})
    assert not v.launches

@pytest.mark.parametrize('custody',['reused','unreadable','missing','terminal_missing'])
def test_container_recovery_unresolved_host_never_signaled_guest_recovered_but_overall_held(control,monkeypatch,custody):
    v=control;prepare(v)
    v.record.update(child_pid=99999,child_identity='original-host',status='running')
    if custody=='reused':monkeypatch.setattr(execution,'process_identity',lambda pid:'unrelated-host')
    if custody=='unreadable':
        monkeypatch.setattr(execution,'process_identity',lambda pid:None)
        monkeypatch.setattr(s.os,'kill',lambda pid,sig:None if sig==0 else pytest.fail('blind host signal'))
    if custody in ('missing','terminal_missing'):v.record['child_pid']=None
    if custody=='terminal_missing':v.record['status']='failed'
    execution._update(v.root,'science',v.record)
    monkeypatch.setattr(execution,'plan_stage',lambda *a,**kw:pytest.fail('planning before producer fence'))
    with pytest.raises(ValueError,match='host producer remains unresolved'):
        s.supervise('science',v.root,0,'logs/science.log',['NEVER-EXECUTED'],kill_secs=100,grace=10,resume=True,authorization_plan={'compute_plan':'full'})
    assert v.stop and not v.launches
    current=execution.load_execution(v.root)['stages']['science']
    assert current['container_producer_fence']['requires_recovery']
    assert current['container_cleanup']['producer_requires_recovery']
    assert current['container_cleanup']['requires_recovery']


def test_container_recovery_owned_fence_failure_preserved_even_when_guest_observed_absent(control,monkeypatch):
    v=control;live_prior(v,monkeypatch)
    def unresolved(*a,**kw):
        return {'requires_recovery':True,'group_state':'active','remaining_group_members':[99999]}
    monkeypatch.setattr(s,'_terminate_owned_group',unresolved)
    monkeypatch.setattr(execution,'finish_attempt',lambda root,record,code,reason:execution._update(root,'science',record))
    with pytest.raises(ValueError,match='producer remains unresolved'):
        s._recover_previous_attempt(v.root,'science',10)
    assert v.producer_alive and not v.stop
    assert execution.load_execution(v.root)['stages']['science']['container_cleanup']['requires_recovery']



def test_container_recovery_public_run_recovers_before_any_current_input_validation(control,monkeypatch):
    v=control;live_prior(v,monkeypatch)
    def invalid(*a,**k):
        assert not v.producer_alive and v.late_guest_created and v.stop
        raise ValueError('current scientific input changed')
    monkeypatch.setattr(science,'verify_plan',invalid)
    monkeypatch.setattr(execution,'begin_attempt',lambda *a,**k:pytest.fail('recovery creates attempt'))
    with pytest.raises(ValueError,match='input changed'):science.run(v.root,resume=True)
    assert not v.launches and not v.producer_alive and v.stop


def test_container_recovery_public_run_spent_token_is_not_relaunch_authority_but_prior_resources_recovered(control,monkeypatch):
    v=control;live_prior(v,monkeypatch)
    (v.root/'execution_attempt.json').write_text('{"attempt":1}')
    def valid(*a,**kw):
        assert not v.producer_alive and v.stop
        return {'schema_version':2}
    monkeypatch.setattr(science,'verify_plan',valid)
    monkeypatch.setattr(science,'_packet_v2_observed',lambda *a,**k:{'lifecycle_verdict':'PENDING'})
    monkeypatch.setattr(physics_review,'active',lambda *a:False)
    monkeypatch.setattr(execution,'begin_attempt',lambda *a,**k:pytest.fail('spent token creates attempt'))
    with pytest.raises(ValueError,match='approved attempt is spent'):science.run(v.root,resume=True)
    assert not v.launches and v.stop


def test_container_recovery_public_recovery_does_not_grant_approval_or_require_current_plan(control,monkeypatch):
    v=control;live_prior(v,monkeypatch)
    (v.root/science.PLAN).unlink();(v.root/science.APPROVAL).unlink()
    monkeypatch.setattr(science,'approve',lambda *a,**k:pytest.fail('recovery grants approval'))
    monkeypatch.setattr(execution,'begin_attempt',lambda *a,**k:pytest.fail('recovery creates attempt'))
    s.recover_previous_attempt(v.root,'science',grace=2)
    assert v.stop and not v.producer_alive and not v.launches
    assert not (v.root/science.APPROVAL).exists()


def test_container_recovery_guest_reserve_is_independent_of_actual_two_second_host_grace(control,monkeypatch):
    v=control
    prepare(v)
    snap=s._container_snapshot(v.root,v.record)
    assert snap['cleanup_seconds']==60 and snap['worker_seconds']==40
    assert s.CONTAINER_CLEANUP_SECS==60
    v.record.update(child_pid=99999,child_identity='original-host')
    execution._update(v.root,'science',v.record)
    monkeypatch.setattr(execution,'process_identity',lambda pid:None)
    monkeypatch.setattr(s.os,'kill',lambda pid,sig:(_ for _ in ()).throw(ProcessLookupError()))
    with pytest.raises(ValueError,match='recovery remains held'):
        s.recover_previous_attempt(v.root,'science',grace=2)
    assert v.stop
    assert execution.load_execution(v.root)['stages']['science']['cleanup']['requires_recovery']


def test_container_recovery_recovery_public_lock_is_nonblocking_and_no_nested_self_deadlock(control):
    v=control
    from ravel.workflow.state_io import file_lock
    with file_lock(v.root/'logs/execution/science.lock'):
        with pytest.raises((BlockingIOError,RuntimeError,ValueError)):
            s.recover_previous_attempt(v.root,'science',grace=2)


@pytest.mark.parametrize('control',['simpleanalysis-built'],indirect=True)
@pytest.mark.parametrize('defect',['planned_output','planned_job','task_job','event_admission'])
def test_event_container_recovery_admission_refuses_rebound_plan_before_client(control,monkeypatch,defect):
    v=control
    if defect=='planned_output':v.event_output=v.root/'outputs/unapproved'
    if defect=='planned_job':
        v.event_job=deepcopy(v.job);v.event_job['transport']['connection']='unapproved'
    if defect=='task_job':
        other=v.root/'other-job.json';other.write_bytes(v.jp.read_bytes())
        v.task['container_plan']=str(other)
    if defect=='event_admission':
        def refused(*a,**k):raise ValueError('accepted source/runtime or native input evidence changed')
        monkeypatch.setattr(simpleanalysis_events,'execution_plan',refused)
    with pytest.raises(ValueError):prepare(v)
    assert not v.calls and not v.launches and not v.out.exists()
    assert 'container_recovery_plan' not in v.record


@pytest.mark.parametrize('control',['simpleanalysis-built'],indirect=True)
def test_event_container_recovery_binds_read_only_real_event_plan_and_exact_raw_job(control,monkeypatch):
    from test_simpleanalysis_events import fixture as event_fixture
    v=control
    directory=v.root/'event-fixture';directory.mkdir()
    task,prepared,job,_=event_fixture(directory,monkeypatch)
    # The event fixture isolates its already accepted native-build evidence and
    # slim ROOT reader. The real execution_plan still checks the complete copied
    # runtime, observer, event/object contract, run.sh and closed container job.
    monkeypatch.setattr(simpleanalysis_events,'execution_plan',REAL_EVENT_PLAN)
    v.task,v.job,v.jp=task,job,Path(task['container_plan'])
    fact={'name':'.','size':v.jp.stat().st_size,'sha256':execution.file_hash(v.jp)}
    v.spec['inputs']=[str(v.jp)]
    v.spec['input_snapshot']={str(v.jp):{'kind':'file','files':[fact]}}
    v.spec.pop('fingerprint');v.spec['fingerprint']=execution.digest(v.spec)
    v.record.update(deepcopy(v.spec));execution._update(v.root,'science',v.record)
    prepare(v,kill=200)
    snapshot=s._container_snapshot(v.root,v.record)
    assert snapshot['output']==str(v.out) and snapshot['job']==job
    assert snapshot['job_input']['path']==str(v.jp)
    assert snapshot['job_input']['file']==fact
    assert snapshot['worker_seconds']==140 and snapshot['cleanup_seconds']==60
    assert not v.out.exists() and not v.calls and not v.launches
    assert (prepared/'work/native-observer.so').is_file()


@pytest.mark.parametrize('control',['simpleanalysis-built'],indirect=True)
@pytest.mark.parametrize('backend',['simpleanalysis','rivet-built','unrecognized'])
def test_event_recovery_branch_does_not_admit_generic_container_tasks(control,backend):
    v=control;v.task['backend']=backend
    prepare(v)
    assert not v.plan_calls and not v.calls and not v.launches
    assert 'container_recovery_plan' not in v.record and not v.out.exists()
