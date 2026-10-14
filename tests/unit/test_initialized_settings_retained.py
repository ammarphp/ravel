"""Synthetic retained failure, custody and evidence-only operation controls."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.validation import initialized_settings_retained as a
from diagnostic_plan_fixture import FAILURE, metadata, STAGE_IDS


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value));return path


def pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}


def origin():
    report={'status':'failed','successful_end_custody':False,'active_stage':None,'failure_class':'resource_floor','postcondition_error':{'type':'StorageError','message':'supplied text'}}
    stage={'status':'failed','exit_code':7,'failure_class':'resource_floor','supervisor_pid':12,'child_pid':13,'cleanup':{'group_state':'empty','requires_recovery':False}}
    outer={'status':'failed','complete_delivery':False,'failure_class':'resource_floor','watchdog_pid':10,'error':{'type':'ControllerError','message':'another supplied text'},'phases':[{'name':'prepare','final_returncode':0,'timed_out':False,'pid':11},{'name':'execute','final_returncode':7,'timed_out':False,'pid':12}],'final_census':{'quiescent':True,'active_rows':[],'zombie_rows':[]}}
    quiet={'quiescent':True,'matching_rows':[],'owned_pids':[10,11,12,13],'groups':[11,12,13]}
    return report,stage,outer,quiet


def resources(root):
    return {'max_seconds':60,'workers':1,'attempts':1,'retained_bytes':100000,'free_floor_bytes':200000,'headroom_bytes':1000,'inherited_bytes':100,'lineage_ceiling_bytes':200000,'resource_root':str(root)}


def fixture(tmp_path,monkeypatch,*,plan_metadata=None):
    root=tmp_path/'origin';root.mkdir(parents=True)
    source=tmp_path/'source';source.write_text('inert source')
    schema=write(tmp_path/'schema.json',{})
    source_lhe=tmp_path/'inert.lhe';source_lhe.write_text('inert content')
    binary=root/'binary';binary.write_text('never executed')
    old={'environment':{'OMP_NUM_THREADS':'1'},'resources':resources(root),'source':pin(source),'stages':[]}
    report,stage,outer,quiet=origin();report['input_pins']={str(source):pin(source)['sha256']}
    stage['input_snapshot']={str(source):{'files':[{'name':'.','size':source.stat().st_size,'sha256':pin(source)['sha256']}]}}
    plan={**(plan_metadata or metadata(file='initialized-settings-retained.json')),'failure_boundary':copy.deepcopy(FAILURE),'transports':[],'snapshots':[],'pairs':[],'binary':'binary'}
    report['commands']=[]
    for index,ident in enumerate(STAGE_IDS):
        folder=root/ident;folder.mkdir()
        argv=['inert-tool','{OUTPUT}/binary'] if index==0 else ['{OUTPUT}/binary',str(source),'unused','6']
        stage_spec={'id':ident,'argv':argv,'outputs':['binary'] if index==0 else [ident+'/transport-verification.json'],'max_seconds':1,'depends_on':STAGE_IDS[:index]}
        old['stages'].append(stage_spec)
        if index:
            command=[v.replace('{OUTPUT}',str(root)) for v in argv]
            transport={'status':'content_verified','joined_events':6,'producer':{'command':command,'returncode':0,'source_checks_before_and_after':True,'input_sources':[pin(source)]}}
            write(folder/'transport-verification.json',transport)
            plan['transports'].append({'id':ident,'folder':ident,'source_lhe':pin(source_lhe),'events':6,'encoding':'gzip','command':argv})
        outputs=[root/name for name in stage_spec['outputs']]
        receipt={'argv':[v.replace('{OUTPUT}',str(root)) for v in argv],'cwd':str(root),'environment':old['environment'],'outputs':list(map(str,outputs)),'max_seconds':1,'status':'completed','actual_returncode':0,'expected_returncode':0,'pid':100+index,'elapsed_seconds':.01,'artifacts':[pin(p) for p in outputs]}
        report['commands'].append(receipt)
        write(root/'native-logs'/(ident+'.command.json'),receipt)
        log=root/'native-logs'/(ident+'.log');log.write_text('dyld[123]: <ABC-123> '+str(binary)+'\n')
    snapshot_file=write(root/'probe_enabled/settings.json',{})
    plan['snapshots']=[{'id':'arm_a','file':'probe_enabled/settings.json','schema':pin(schema),'compiled_source':pin(source),'command':old['stages'][2]['argv'],'settings':{},'masses':{}}]
    for ident in ('probe_disabled','probe_enabled'):
        for name in ('events.hepmc.gz','original-lhe.jsonl'):(root/ident/name).write_text('same inert stream')
    plan['pairs']=[{'id':'arm_a','disabled':{'hepmc':'probe_disabled/events.hepmc.gz','sidecar':'probe_disabled/original-lhe.jsonl'},'enabled':{'hepmc':'probe_enabled/events.hepmc.gz','sidecar':'probe_enabled/original-lhe.jsonl'},'reference':{'hepmc':pin(source_lhe),'sidecar':pin(source)},'encoding':'gzip'}]
    monkeypatch.setattr(a.checks,'snapshot',lambda *args,**kwargs:{'settings_verified':True})
    monkeypatch.setattr(a.checks,'pair',lambda *args,**kwargs:{'noninterference':True})
    artifacts=[pin(p) for p in sorted(root.rglob('*')) if p.is_file()]
    bound={row['path']:row['sha256'] for row in artifacts}
    report['loader_census']=a.loader_evidence(root,old['stages'],bound,binary)
    oldpin=pin(write(tmp_path/'origin-contract.json',old))
    evidence={'output_root':str(root),'output_manifest':pin(write(tmp_path/'manifest.json',{'artifacts':artifacts}))}
    for name,value in zip(('report','stage_record','outer_receipt','root_quiescence'),(report,stage,outer,quiet)):
        evidence[name]=pin(write(tmp_path/(name+'.json'),value))
    d={'schema_version':1,'scope':a.SCOPE,'origin_contract':oldpin,'artifacts':artifacts,'resources':resources(tmp_path/'new'),'assumptions':['synthetic only'],'evidence':evidence,'plan':plan}
    path=write(tmp_path/'input.json',d);task={'input':str(path),'sha256':pin(path)['sha256']}
    state={'reads':0,'guards':[]}
    def verify(*args,**kwargs):
        state['reads']+=1
        return {'status':'content_verified','joined_events':kwargs['expected_events']}
    monkeypatch.setattr(a.lhe_provenance,'verify_new_generation',verify)
    monkeypatch.setattr(a.native,'child',lambda *args:pytest.fail('native child called'))
    class Guard:
        def __init__(self,*args):pass
        def check(self,final=False):
            state['guards'].append(final)
            return {'usage':{'logical_bytes':0},'free_bytes':400000,'sampled_not_quota':True}
    monkeypatch.setattr(a.native,'Guard',Guard)
    return task,d,state


def test_supplied_resource_successor_preserves_pinned_origin(tmp_path,monkeypatch):
    task,d,_=fixture(tmp_path,monkeypatch)
    d['resources']['free_floor_bytes']=300000
    path=write(Path(task['input']),d);task['sha256']=pin(path)['sha256']
    _,fresh,old,_=a.document(task,tmp_path)
    assert fresh['resources']['free_floor_bytes']==300000
    assert old['resources']['free_floor_bytes']==200000


@pytest.mark.parametrize('change',[{'free_floor_bytes':-1},{'free_floor_bytes':True},{'free_floor_bytes':2.5},{'max_seconds':0},{'workers':2},{'attempts':2},{'headroom_bytes':100001},{'lineage_ceiling_bytes':10}])
def test_invalid_supplied_resource_envelope_refuses(tmp_path,monkeypatch,change):
    task,d,_=fixture(tmp_path,monkeypatch);d['resources'].update(change)
    path=write(Path(task['input']),d);task['sha256']=pin(path)['sha256']
    with pytest.raises(ValueError):a.document(task,tmp_path)


def test_pinned_origin_contract_cannot_be_rewritten(tmp_path,monkeypatch):
    task,d,_=fixture(tmp_path,monkeypatch)
    p=Path(d['origin_contract']['path']);old=json.loads(p.read_text());old['resources']['free_floor_bytes']+=1;write(p,old)
    with pytest.raises(ValueError,match='origin contract changed'):a.document(task,tmp_path)


@pytest.mark.parametrize('used',[0,75,300])
def test_entry_reserves_remaining_whole_case_not_just_floor(used):
    r={'retained_bytes':500,'free_floor_bytes':1000,'headroom_bytes':10}
    need=r['free_floor_bytes']+r['retained_bytes']-used+r['headroom_bytes']
    observation={'usage':{'logical_bytes':used},'free_bytes':need}
    result=a.entry_reserve(r,observation)
    assert result['passed'] and result['required_free_bytes']==need
    observation['free_bytes']-=1
    assert not a.entry_reserve(r,observation)['passed']


@pytest.mark.parametrize('observation',[{'usage':{'logical_bytes':-1},'free_bytes':10},{'usage':{'logical_bytes':0.0},'free_bytes':10},{'usage':{'logical_bytes':0},'free_bytes':True}])
def test_invalid_entry_observation_refuses(observation):
    with pytest.raises(ValueError):a.entry_reserve({},observation)


def test_original_failure_is_required_and_never_upgraded():
    values=origin();before=copy.deepcopy(values)
    result=a.failure_boundary(*values,FAILURE)
    assert values==before and result['original_scientific_status']=='failed'
    assert result['original_resource_contract_satisfied'] is False


@pytest.mark.parametrize('change',[
    lambda r,s,o,q:r.update(status='passed'),
    lambda r,s,o,q:r.update(failure_class='unknown'),
    lambda r,s,o,q:r.update(active_stage='running'),
    lambda r,s,o,q:s.update(exit_code=0),
    lambda r,s,o,q:s['cleanup'].update(requires_recovery=True),
    lambda r,s,o,q:o.update(complete_delivery=True),
    lambda r,s,o,q:o['phases'][1].update(timed_out=True),
    lambda r,s,o,q:q.update(owned_pids=[10,11,12]),
    lambda r,s,o,q:q.update(matching_rows=[{'pid':13}]),
    lambda r,s,o,q:o['phases'].pop(),
    lambda r,s,o,q:o['phases'][1].update(final_returncode=8),
])
def test_different_failure_or_missing_quiescence_refuses(change):
    values=origin();change(*values)
    with pytest.raises(ValueError):a.failure_boundary(*values,FAILURE)


def test_error_text_and_exit_number_are_not_study_selectors():
    values=origin();r,s,o,q=values
    r['postcondition_error']['message']='any typed resource failure'
    o['error']['message']='any controller failure'
    s['exit_code']=17;o['phases'][1]['final_returncode']=17
    assert a.failure_boundary(*values,FAILURE)['failure_class']=='resource_floor'


@pytest.mark.parametrize('change',['returncode','timeout','argv','environment','pins','hash'])
def test_command_refusals(tmp_path,monkeypatch,change):
    task,d,_=fixture(tmp_path,monkeypatch);old=json.loads(Path(d['origin_contract']['path']).read_text());root=Path(d['evidence']['output_root'])
    receipt=json.loads((root/'native-logs/build.command.json').read_text());pins={row['path']:row['sha256'] for row in d['artifacts']}
    if change=='returncode':receipt['actual_returncode']=3
    elif change=='timeout':receipt['timed_out']=True
    elif change=='argv':receipt['argv'][0]='different'
    elif change=='environment':receipt['environment']={}
    elif change=='pins':pins.clear()
    else:receipt['artifacts'][0]['sha256']='0'*64
    with pytest.raises(ValueError):a.command_evidence(receipt,old['stages'][0],old,root,pins)


def test_separate_result_requires_all_evidence_without_native_calls(tmp_path,monkeypatch):
    task,d,state=fixture(tmp_path,monkeypatch);before=Path(d['evidence']['report']['path']).read_bytes()
    result=a.run(task,tmp_path,tmp_path/'new/out')
    assert result['status']=='passed' and result['successful_end_custody']
    assert len(result['commands'])==3 and len(result['transports'])==2
    assert result['snapshots']=={'arm_a':{'settings_verified':True}} and result['pairs']=={'arm_a':{'noninterference':True}}
    assert all(x==0 for x in result['new_native_counts'].values())
    assert Path(d['evidence']['report']['path']).read_bytes()==before
    assert not result['original_resource_contract_satisfied'] and state['guards'][-1]
    assert json.loads((tmp_path/'new/out/initialized-settings-retained.json').read_text())==result


@pytest.mark.parametrize('failure',['transport','mutation','floor','entry','mismatch'])
def test_new_failure_retains_evidence_and_original_failure(tmp_path,monkeypatch,failure):
    task,d,state=fixture(tmp_path,monkeypatch)
    if failure in ('transport','mismatch'):
        def verify(*args,**kwargs):
            if failure=='transport':raise ValueError('synthetic interrupted transport')
            return {'status':'content_verified','joined_events':5}
        monkeypatch.setattr(a.lhe_provenance,'verify_new_generation',verify)
    elif failure=='mutation':
        old=a.input_snapshot;calls=[]
        def snapshot(*args):
            calls.append(1);value=old(*args)
            if len(calls)==2:value['synthetic']='changed'
            return value
        monkeypatch.setattr(a,'input_snapshot',snapshot)
    else:
        class Guard:
            def __init__(self,*args):pass
            def check(self,final=False):
                if final and failure=='floor':raise ValueError('typed resource floor')
                return {'usage':{'logical_bytes':0},'free_bytes':0 if failure=='entry' else 400000}
        monkeypatch.setattr(a.native,'Guard',Guard)
    result=a.run(task,tmp_path,tmp_path/'new/out')
    assert result['status']=='failed' and not result['successful_end_custody']
    assert json.loads(Path(d['evidence']['report']['path']).read_text())['status']=='failed'
    if failure=='mismatch':
        assert result['transports']['probe_disabled']['joined_events']==5
        assert result['transport_comparisons']['probe_disabled']['status']=='mismatch'
    if failure=='entry':assert result['commands']==[] and state['reads']==0


def test_source_has_no_process_or_producer_call():
    tree=ast.parse(Path(a.__file__).read_text())
    calls=[ast.unparse(x.func) for x in ast.walk(tree) if isinstance(x,ast.Call)]
    assert not any(x in calls for x in ('subprocess.run','subprocess.Popen','native.child','os.system'))


@pytest.mark.parametrize('kind',['root_alias','ancestor_alias','output_alias','inside_origin','origin_parent','parent_traversal'])
def test_alias_overlap_refuses_before_mkdir_or_save(tmp_path,monkeypatch,kind):
    origin=tmp_path/'old/output';origin.mkdir(parents=True)
    resource=tmp_path/'new';output=resource/'result'
    if kind=='root_alias':resource.symlink_to(origin,target_is_directory=True)
    elif kind=='ancestor_alias':
        alias=tmp_path/'alias';alias.symlink_to(tmp_path/'old',target_is_directory=True);resource=alias/'new';output=resource/'result'
    elif kind=='output_alias':resource.mkdir();output.symlink_to(origin,target_is_directory=True)
    elif kind=='inside_origin':resource=origin/'new';output=resource/'result'
    elif kind=='origin_parent':resource=tmp_path/'old';output=resource/'result'
    elif kind=='parent_traversal':resource=tmp_path/'foo/../old/output';output=resource/'result'
    d={'evidence':{'output_root':str(origin)},'resources':{'resource_root':str(resource)}}
    monkeypatch.setattr(a,'document',lambda *args:(None,d,{},{}))
    monkeypatch.setattr(a,'atomic_json',lambda *args:pytest.fail('publication before separation'))
    with pytest.raises(ValueError):a.run({},tmp_path,output)
    assert list(origin.iterdir())==[]


def test_supplied_byte_bound_classification_preserves_legacy_failure_outputs():
    from ravel.workflow.execution import digest
    values=origin()
    for record in values[:3]:record.pop('failure_class')
    before=copy.deepcopy(values)
    contract={**FAILURE,'class_bindings':[{'record':name,'sha256':digest(record),'failure_class':'resource_floor'} for name,record in zip(('report','stage','outer'),values)]}
    result=a.failure_boundary(*values,contract)
    assert result['original_scientific_status']=='failed' and not result['original_result_rewritten']
    assert result['failure_class']=='resource_floor' and values==before
    values[0]['postcondition_error']['message']='changed evidence'
    with pytest.raises(ValueError,match='classification'):a.failure_boundary(*values,contract)


def test_retained_settings_cannot_pass_without_selected_witnesses(tmp_path,monkeypatch):
    task,d,_=fixture(tmp_path,monkeypatch)
    d['plan']['transports']=[]
    path=write(Path(task['input']),d);task['sha256']=pin(path)['sha256']
    with pytest.raises(ValueError,match='transport'):a.document(task,tmp_path)


def test_verification_budget_keeps_custody_reserve(tmp_path,monkeypatch):
    from types import SimpleNamespace
    task,d,state=fixture(tmp_path,monkeypatch)
    ticks=iter([0.])
    monkeypatch.setattr(a,'time',SimpleNamespace(monotonic=lambda:next(ticks,d['resources']['max_seconds']-a.native.CUSTODY_RESERVE_SECONDS/2)))
    result=a.run(task,tmp_path,tmp_path/'new/out')
    assert result['status']=='failed' and 'deadline' in result['error']['message']
    assert json.loads((tmp_path/'new/out/initialized-settings-retained.json').read_text())['status']=='failed'
