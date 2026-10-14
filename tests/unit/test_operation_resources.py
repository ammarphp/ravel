"""Typed generic solver work, no CAMB/native solver or invented event count."""
from copy import deepcopy
import sys
from pathlib import Path
import pytest
from ravel.workflow import execution,operation_resources as resources,stage_supervisor as supervisor
from ravel.workflow.state_io import atomic_json,read_json
from ravel.validation.validate_task_contract import validate


def declaration():
    return {'schema_version':1,'kind':'solver','generated_events':0,'solver_evaluations':2,'max_seconds':2}


@pytest.fixture
def endpoint(tmp_path):
    rd=tmp_path.resolve();(rd/'inputs').mkdir();(rd/'outputs').mkdir()
    cmd=[sys.executable,'-c',"from pathlib import Path; Path('outputs/result.txt').write_text('supplied control, not a solver'); print('marker')"]
    stage={'stage':'transfer','command':cmd,'cwd':str(rd),'inputs':[],'outputs':['outputs/result.txt'],
           'depends_on':[],'operation_resources':declaration()}
    plan={'stages':[stage],'operation_resources':declaration(),'max_seconds':2}
    path=rd/'inputs/endpoint-plan.json';atomic_json(path,plan)
    cost={'mode':'full','points':1,'solver_evaluations':2,'walltime_h':[0,2/3600]}
    contract={'schema_version':1,'prompt':'A source-bound transfer function','task_mode':'generate',
        'detector_mode':'parton-level','stat_mode':'none-generation','compute_plan':'full','approval_required':True,
        'required_user_inputs':[],'assumptions':['No events generated; supplied tiny control only'],
        'operation_resources':declaration(),'cost_estimate':cost,
        'execution_plan':{'path':'inputs/endpoint-plan.json','sha256':execution.file_hash(path)}}
    atomic_json(rd/'inputs/task_contract.json',contract)
    from method_decision_fixture import admit_method
    admit_method(rd)
    return rd,stage,contract


@pytest.mark.parametrize('key,value',[('schema_version',True),('kind','event_generation'),('generated_events',1),
    ('generated_events',False),('solver_evaluations',0),('solver_evaluations',True),('solver_evaluations',2.0),
    ('max_seconds',0),('max_seconds',float('inf')),('max_seconds',True)])
def test_closed_typed_non_event_class_refuses_invalid_values(key,value):
    d=declaration();d[key]=value
    with pytest.raises(ValueError):resources.validate(d)


def test_solver_contract_cost_names_the_actual_unit(endpoint):
    _,_,c=endpoint;assert validate(c)==[]
    c['cost_estimate']['events_per_point']=1
    assert any('bookkeeping' in e for e in validate(c))
    del c['cost_estimate']['events_per_point'];c['cost_estimate']['solver_evaluations']=3
    assert any('matching' in e for e in validate(c))


@pytest.mark.parametrize('change',['command','count','class','events','walltime','plan','contract','undeclared'])
def test_stage_refuses_incomplete_or_changed_resources_before_any_launch(endpoint,monkeypatch,change):
    rd,s,c=endpoint;d=declaration();events=0;budget=2;cmd=s['command']
    if change=='command':cmd=[sys.executable,'-c','print(123)']
    elif change=='count':d['solver_evaluations']=3
    elif change=='class':d['kind']='arbitrary'
    elif change=='events':events=1
    elif change=='walltime':budget=3
    elif change=='plan':(rd/'inputs/endpoint-plan.json').write_text('{}')
    elif change=='contract':c['operation_resources']['solver_evaluations']=3;atomic_json(rd/'inputs/task_contract.json',c)
    elif change=='undeclared':d=None
    monkeypatch.setattr(supervisor.subprocess,'Popen',lambda *a,**k:pytest.fail('refusal reached child launch'))
    with pytest.raises(ValueError):supervisor.supervise('transfer',rd,events,'logs/transfer.log',cmd,
        inputs=[],outputs=s['outputs'],cwd=str(rd),required_plan='full',kill_secs=budget,operation_resources=d)


def test_planning_retains_resource_fingerprint_without_contract_hash_cycle(endpoint):
    rd,s,c=endpoint
    old=execution.plan_stage(rd,'transfer',s['command'],[],s['outputs'],[],rd)
    new=execution.plan_stage(rd,'transfer',s['command'],[],s['outputs'],[],rd,operation_resources=declaration())
    assert 'operation_resources' not in old and old['fingerprint']!=new['fingerprint']
    assert str(rd/'inputs/task_contract.json') not in new['input_snapshot']
    assert str(rd/'inputs/endpoint-plan.json') not in new['input_snapshot']


def test_actual_tiny_supervised_marker_binds_fresh_authority_and_finish_reuse(endpoint,monkeypatch):
    rd,s,_=endpoint
    # Explicitly synthetic approval transport: actual supervisor/process/receipt,
    # no native solver, real workflow approval or scientific acceptance claim.
    from ravel.workflow import launch_authorization as launch
    def checked(root,required,cmd,**kwargs):
        assert required=='full' and kwargs['context']['events']==0
        assert kwargs['context']['stage_spec']['operation_resources']==declaration()
        assert kwargs['context']['operation_authority']==resources.authority(rd,declaration())
        kwargs.pop('context');p=supervisor.subprocess.Popen(cmd,**kwargs);p.ravel_authorization={'synthetic':True};return p
    monkeypatch.setattr(launch,'authorized_popen',checked)
    assert supervisor.supervise('transfer',rd,0,'logs/transfer.log',s['command'],kill_secs=2,poll=.01,grace=.1,
        inputs=[],outputs=s['outputs'],cwd=str(rd),required_plan='full',operation_resources=declaration())==0
    record=execution.load_execution(rd)['stages']['transfer']
    assert execution.stage_errors(rd,'transfer')==[]
    assert record['operation_authority']==resources.authority(rd,declaration())
    assert execution.validate_completed_execution(rd,[s])==[]
    bad=deepcopy(s);del bad['operation_resources']
    assert any('operation resources differ' in e for e in execution.validate_completed_execution(rd,[bad]))
    c=read_json(rd/'inputs/task_contract.json');c['prompt']+=' changed';atomic_json(rd/'inputs/task_contract.json',c)
    assert any('authority changed' in e for e in execution.stage_errors(rd,'transfer'))


@pytest.mark.parametrize('change',['resource','authority'])
def test_finish_rejects_changed_contract_or_fingerprint(endpoint,change):
    rd,s,c=endpoint
    binding=execution.plan_stage(rd,'transfer',s['command'],[],s['outputs'],[],rd,operation_resources=declaration())
    record=execution.begin_attempt(rd,'transfer',binding,'logs/transfer.log')
    record['operation_authority']=resources.authority(rd,declaration())
    (rd/'outputs/result.txt').write_text('marker')
    if change=='resource':record['operation_resources']['solver_evaluations']=3
    else:c['prompt']+=' changed';atomic_json(rd/'inputs/task_contract.json',c)
    assert execution.finish_attempt(rd,record,0)==3


def approve_endpoint(endpoint):
    from ravel.workflow import workflow_state as ws
    from test_approval_chain import VALID_CHECKIN1
    rd,s,c=endpoint
    atomic_json(rd/'inputs/checkin1.json',VALID_CHECKIN1)
    cost=c['cost_estimate']|{'schema_version':1,'generated_by':'cost_preflight.py'}
    atomic_json(rd/'inputs/cost_preflight.json',cost)
    from method_decision_fixture import admit_method
    admit_method(rd)
    assert ws.main(['approve','--rundir',str(rd),'--quote','Synthetic engineering approval; no native solver','--plan','full','--scripted'])==0
    assert ws.verify_approval(str(rd),required_plan='full')==[]
    ctx={'kind':'scientific-stage','stage':'transfer','review_action':'bulk','events':0,'max_seconds':2,
        'stage_spec':s|{'log':str(rd/'logs/transfer.log')},'operation_authority':resources.authority(rd,declaration())}
    return ctx


def test_real_public_approval_captures_retained_solver_authority(endpoint):
    from ravel.workflow import launch_authorization as launch
    rd,s,_=endpoint;ctx=approve_endpoint(endpoint)
    snapshot=launch._capture(rd,'full',command=s['command'],context=ctx)
    assert len(snapshot['operation_inputs'])==2
    event={'authorization':snapshot,'command':s['command'],'context':ctx,'utc':launch.operational_utc()}
    launch._historical_errors(event)
    changed=deepcopy(event);changed['context']['events']=1
    with pytest.raises(ValueError,match='retained solver'):launch._historical_errors(changed)


@pytest.mark.parametrize('change',['task','endpoint','context','removed_class','authority','outputs','count'])
def test_fresh_public_launch_refuses_mutation_before_popen(endpoint,monkeypatch,change):
    from ravel.workflow import launch_authorization as launch
    rd,s,c=endpoint;ctx=approve_endpoint(endpoint);append=launch._append
    def mutate(root,event):
        value=append(root,event)
        if event['event']=='authorized':
            if change=='task':c['prompt']+=' drift';atomic_json(rd/'inputs/task_contract.json',c)
            elif change=='endpoint':(rd/'inputs/endpoint-plan.json').write_text('{}')
            elif change=='removed_class':del ctx['stage_spec']['operation_resources']
            elif change=='authority':ctx['operation_authority']={}
            elif change=='outputs':ctx['stage_spec']['outputs']=[]
            elif change=='count':ctx['stage_spec']['operation_resources']['solver_evaluations']=3
            else:ctx['max_seconds']=3
        return value
    monkeypatch.setattr(launch,'_append',mutate)
    monkeypatch.setattr(launch.subprocess,'Popen',lambda *a,**k:pytest.fail('changed authority reached launch'))
    with pytest.raises(ValueError):launch.authorized_popen(rd,'full',s['command'],context=ctx)


def test_resource_authority_reader_rejects_oversize_duplicate_and_alias(tmp_path):
    p=tmp_path.resolve()/'doc.json';p.write_bytes(b'X'*(resources.MAX_DOCUMENT_BYTES+1))
    with pytest.raises(ValueError,match='8MiB'):resources.document_pin(p)
    p.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError,match='duplicate'):resources.document(p)
    target=p.with_name('alias.json');target.symlink_to(p)
    with pytest.raises(ValueError,match='ordinary'):resources.document_pin(target)


@pytest.mark.parametrize('change',['class','stage_spec','whole_context'])
def test_public_lower_entry_refuses_solver_class_omission_before_capture(endpoint,monkeypatch,change):
    from ravel.workflow import launch_authorization as launch
    rd,s,_=endpoint;ctx=approve_endpoint(endpoint)
    if change=='class':del ctx['stage_spec']['operation_resources']
    elif change=='stage_spec':del ctx['stage_spec']
    else:ctx={}
    monkeypatch.setattr(launch.subprocess,'Popen',lambda *a,**k:pytest.fail('omitted approved solver class reached launch'))
    with pytest.raises(ValueError,match='approved task'):
        launch.authorized_popen(rd,'full',s['command'],context=ctx)


@pytest.mark.parametrize('remove_inputs',[False,True])
def test_detached_retained_approval_refuses_removed_solver_class(endpoint,remove_inputs):
    from ravel.workflow import launch_authorization as launch
    rd,s,_=endpoint;ctx=approve_endpoint(endpoint)
    snapshot=launch._capture(rd,'full',command=s['command'],context=ctx)
    del ctx['stage_spec']['operation_resources']
    if remove_inputs:del snapshot['operation_inputs']
    event={'authorization':snapshot,'command':s['command'],'context':ctx,'utc':launch.operational_utc()}
    with pytest.raises(ValueError,match='approved task'):launch._historical_errors(event)
