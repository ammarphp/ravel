"""Source-built runtime reuse admission controls; no native/image execution."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.physics import simpleanalysis_container as container
from ravel.physics import simpleanalysis_events as events


def fixture(tmp_path,monkeypatch):
    from test_simpleanalysis_container import fixture as transport_fixture
    _,transport,_,_=transport_fixture(tmp_path)
    build_out=tmp_path/'accepted-build';runtime=build_out/'container-output/runtime/work'
    (runtime/'build/qualified-platform/bin').mkdir(parents=True)
    binary=runtime/'build/qualified-platform/bin/simpleAnalysis';binary.write_bytes(b'accepted native binary protocol control')
    (runtime/'native-observer.so').write_bytes(b'accepted existing observer protocol control')
    (runtime/'build/qualified-platform/setup.sh').write_text('accepted generated setup')
    (runtime/'source').mkdir();(runtime/'source/routine.cxx').write_text('DefineAnalysis(RealRoutine)')
    guest={'schema_version':1,'setup':{'path':'/release_setup.sh','sha256':'a'*64},
        'tools':{name:{'path':'/qualified/'+name,'sha256':'b'*64} for name in ('compiler','c_compiler','cmake','python')},
        'binary_relative':'qualified-platform/bin/simpleAnalysis','qualification_sha256':transport['qualification']['sha256']}
    (build_out/'container-input').mkdir();(build_out/'container-input/source-contract.json').write_text(json.dumps({'guest':guest}))
    receipt={'schema_version':3,'runtime_files':container.tree_facts(runtime.parent),'binary':{'sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}}
    plan={'schema_version':3,'framework':'simpleanalysis','base_dir':str(tmp_path),'container_job':{'transport':transport}}
    rp=build_out/'build-receipt.json';pp=build_out/'build-plan.json';rp.write_text(json.dumps(receipt));pp.write_text(json.dumps(plan))
    # Independent accepted-build verification itself belongs to build controls;
    # these controls isolate its event admission/reuse boundary.
    monkeypatch.setattr(events,'_build',lambda *_:(receipt,plan,build_out))
    monkeypatch.setattr(events.routine_build,'bound_routine',lambda _r,_p,_o,routine: {
        'routine':routine,'primary_build_routine':'RealRoutine','source_binding':{'registration':'literal-DefineAnalysis'},
        'binary_sha256':receipt['binary']['sha256'],'physics_validated':False} if routine=='RealRoutine' else (_ for _ in ()).throw(ValueError('unregistered')))
    monkeypatch.setattr(events.adapter,'read_input',lambda *_,**_k:{10:2.,11:-.5})
    supplied=tmp_path/'events.root';supplied.write_bytes(b'prospective native slim input control')
    contract=tmp_path/'object-contract.json';contract.write_text(json.dumps({'level':'synthetic_structural','weight_names':['nominal']}))
    prepared=tmp_path/'prepared-events'
    events.prepare_inputs(rp,pp,'RealRoutine',supplied,contract,['DeclaredRegion'],prepared)
    job=container.make_plan(transport,prepared,max_seconds=120)
    jp=tmp_path/'event-job.json';jp.write_text(json.dumps(job))
    task={'backend':'simpleanalysis-built','routine':'RealRoutine','build_receipt':str(rp),'build_plan':str(pp),
          'events':str(supplied),'object_contract':str(contract),'regions':['DeclaredRegion'],'container_plan':str(jp)}
    return task,prepared,job,guest


def test_read_only_event_admission_reuses_complete_runtime_and_existing_observer(tmp_path,monkeypatch):
    task,prepared,job,guest=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr('subprocess.run',lambda *_a,**_k:pytest.fail('event admission ran a native process'))
    out=tmp_path/'not-created'
    plan=events.execution_plan(task,tmp_path,out)
    assert plan['container_job']==job and plan['input_events']==2
    assert plan['source_builds']==0 and plan['compute_authorized'] is False
    assert not out.exists()
    script=(prepared/'run.sh').read_text()
    assert 'RAVEL_NATIVE_BINARY=/tmp/ravel-work/build/qualified-platform/bin/simpleAnalysis' in script
    assert 'LD_PRELOAD=/tmp/ravel-work/native-observer.so' in script
    assert ' -a RealRoutine -o /tmp/ravel-output/selection -n -w 0 /tmp/ravel-input/events.root' in script
    assert 'cmake' not in script and 'gcc' not in script and 'compiler' not in script
    assert (prepared/'work/native-observer.so').read_bytes()==b'accepted existing observer protocol control'


@pytest.mark.parametrize('defect',['binary','observer','extra_runtime','event','original_event','object_contract','program','regions','unknown_routine','image','resource'])
def test_rehashed_job_cannot_change_accepted_runtime_source_or_native_input(tmp_path,monkeypatch,defect):
    task,prepared,job,_=fixture(tmp_path,monkeypatch)
    if defect=='binary':(prepared/'work/build/qualified-platform/bin/simpleAnalysis').write_bytes(b'wrong native image')
    elif defect=='observer':(prepared/'work/native-observer.so').write_bytes(b'wrong preload image')
    elif defect=='extra_runtime':(prepared/'work/unbound-library.so').write_bytes(b'extra image')
    elif defect=='event':(prepared/'events.root').write_bytes(b'different ROOT')
    elif defect=='original_event':Path(task['events']).write_bytes(b'original changed ROOT')
    elif defect=='object_contract':(prepared/'object-contract.json').write_text('{"level":"reconstructed"}')
    elif defect=='program':(prepared/'run.sh').write_text('arbitrary rehashed event command')
    elif defect=='regions':task['regions']=['AnotherRegion']
    elif defect=='unknown_routine':task['routine']='MetadataOnlyName'
    elif defect=='image':job['transport']=copy.deepcopy(job['transport']);job['transport']['image']['config_sha256']='c'*64
    elif defect=='resource':job['resources']['workers']=2
    if defect not in ('image','resource'):
        job['input_files']=container.tree_facts(prepared)
    Path(task['container_plan']).write_text(json.dumps(job))
    monkeypatch.setattr('subprocess.run',lambda *_a,**_k:pytest.fail('refused event admission ran a native process'))
    with pytest.raises(ValueError):events.execution_plan(task,tmp_path,tmp_path/'unused')


def test_missing_retained_observer_forbids_recompiling_during_event_preparation(tmp_path,monkeypatch):
    task,_,_,_=fixture(tmp_path,monkeypatch)
    receipt,_,_=events._build(task['build_receipt'],task['build_plan'])
    receipt['runtime_files'].pop('work/native-observer.so')
    with pytest.raises(ValueError,match='zero-build'):
        events.prepare_inputs(task['build_receipt'],task['build_plan'],task['routine'],task['events'],task['object_contract'],task['regions'],tmp_path/'another')
    assert not (tmp_path/'another').exists()


def test_guest_paths_and_routine_names_are_validated_before_shell_interpolation(tmp_path,monkeypatch):
    _,_,_,guest=fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError):events.guest_program(guest,'RealRoutine;touch /unbound')
    guest['setup']['path']='/release_setup.sh;env'
    with pytest.raises(ValueError):events.guest_program(guest,'RealRoutine')


def test_named_weight_is_bound_to_source_contract_exact_native_index_and_script(tmp_path,monkeypatch):
    task,_,_,_=fixture(tmp_path,monkeypatch)
    object_path=Path(task['object_contract'])
    object_path.write_text(json.dumps({'level':'synthetic_structural','weight_names':['nominal','muR=0.5 muF=1.0']}))
    prepared=tmp_path/'named-prepared'
    events.prepare_inputs(task['build_receipt'],task['build_plan'],'RealRoutine',task['events'],object_path,
                          task['regions'],prepared,weight_name='muR=0.5 muF=1.0')
    receipt,build_plan,_=events._build(task['build_receipt'],task['build_plan'])
    job=container.make_plan(build_plan['container_job']['transport'],prepared,max_seconds=120)
    path=tmp_path/'named-job.json';path.write_text(json.dumps(job))
    task.update(container_plan=str(path),weight_name='muR=0.5 muF=1.0')
    plan=events.execution_plan(task,tmp_path,tmp_path/'named-not-created')
    assert plan['contract']['selected_weight']=={'name':'muR=0.5 muF=1.0','index':1,'names':['nominal','muR=0.5 muF=1.0']}
    assert ' -w 1 ' in (prepared/'run.sh').read_text()
    assert 'muR=' not in (prepared/'run.sh').read_text()
    task['weight_name']='nominal'
    with pytest.raises(ValueError,match='program contract differs'):events.execution_plan(task,tmp_path,tmp_path/'not-created')


def public_input_fixture(tmp_path,monkeypatch):
    """Real public/input paths with inherited accepted-build/ROOT-reader controls.

    The existing event fixture substitutes accepted-build receipt verification and
    slim ROOT reading. The native configuration fixture supplies a complete pure
    source/build input population so build.inputs itself is not substituted.
    None of these synthetic receipt records is native or scientific acceptance.
    """
    from test_simpleanalysis_build import configured_fixture
    build_base=tmp_path/'build-inputs';build_base.mkdir()
    build_task,build_prepared,_=configured_fixture(build_base)
    event_base=tmp_path/'event-inputs';event_base.mkdir()
    task,_,_,_=fixture(event_base,monkeypatch)
    receipt,plan,build_out=events._build(task['build_receipt'],task['build_plan'])
    plan['input']={'path':str(build_base/build_task['input'])}
    plan['base_dir']=str(build_base)
    Path(task['build_plan']).write_text(json.dumps(plan))
    objects=event_base/'object-definitions.json';objects.write_text('{"scope":"explicit synthetic structural objects"}')
    response=event_base/'response-evidence.json';response.write_text('{"scope":"explicit structural response control"}')
    contract_path=Path(task['object_contract'])
    contract=json.loads(contract_path.read_text())
    contract.update(object_definitions=str(objects),response_evidence=[str(response)])
    contract_path.write_text(json.dumps(contract))
    prepared=event_base/'public-prepared'
    events.prepare_inputs(task['build_receipt'],task['build_plan'],task['routine'],task['events'],
                          task['object_contract'],task['regions'],prepared)
    job=container.make_plan(plan['container_job']['transport'],prepared,max_seconds=120)
    Path(task['container_plan']).write_text(json.dumps(job))
    monkeypatch.setattr('subprocess.run',lambda *_a,**_k:pytest.fail('public admission executed a process'))
    monkeypatch.setattr('subprocess.Popen',lambda *_a,**_k:pytest.fail('public admission launched a process'))
    monkeypatch.setattr(container,'execute',lambda *_a,**_k:pytest.fail('public admission executed a container'))
    return task,event_base,prepared,job,build_base,build_task,build_prepared,build_out,objects,response


def test_public_source_built_event_inputs_include_exact_container_and_complete_real_build_assets(tmp_path,monkeypatch):
    from ravel.physics import existing_events
    from ravel.workflow import science
    task,base,prepared,job,build_base,build_task,build_prepared,build_out,objects,response=public_input_fixture(tmp_path,monkeypatch)
    assert existing_events.validate(task) is None
    admitted=existing_events.inputs(task,base)
    # Construct the expected population independently from the explicit fixture
    # paths and closed job inventory rather than calling events.inputs again.
    expected=set(events.build.inputs(build_task,build_base))
    expected.update(p for p in build_out.rglob('*') if p.is_file())
    expected.update(Path(task[k]) for k in ('events','object_contract','container_plan'))
    expected.update((objects,response))
    expected.update(prepared/name for name in job['input_files'])
    assert set(admitted)==expected and len(admitted)==len(expected)
    assert Path(task['container_plan']) in admitted and build_base/'native-job.json' in admitted
    assert build_prepared/'native-observer.c' in admitted
    assert build_base/'source/Framework/real.cxx' in admitted
    assert prepared/'work/native-observer.so' in admitted
    spec={'mode':'analyze','task':task,'max_seconds':job['resources']['max_seconds']}
    assert spec['max_seconds']==120
    assert science.task_inputs(spec,base)==admitted
    assert not (base/'unexecuted-event-output').exists()
    assert not (tmp_path/'outputs').exists()


@pytest.mark.parametrize('defect',['missing_job','extra_command','routine_injection','no_regions','all_region','empty_job','empty_weight'])
def test_public_source_built_event_validate_refuses_malformed_task_without_execution(tmp_path,monkeypatch,defect):
    from ravel.physics import existing_events
    task,*_=public_input_fixture(tmp_path,monkeypatch)
    if defect=='missing_job':task.pop('container_plan')
    elif defect=='extra_command':task['command']=['/bin/bash','unbound.sh']
    elif defect=='routine_injection':task['routine']='RealRoutine;touch unbound'
    elif defect=='no_regions':task['regions']=[]
    elif defect=='all_region':task['regions']=['All']
    elif defect=='empty_job':task['container_plan']=''
    elif defect=='empty_weight':task['weight_name']=''
    with pytest.raises(ValueError):existing_events.validate(task)


@pytest.mark.parametrize('defect',['build_source','build_recipe','copied_binary','copied_observer','copied_event',
    'original_event','copied_object_contract','program','transport','extra_runtime','job_symlink'])
def test_public_source_built_event_inputs_refuse_stale_assets_even_after_job_rehash(tmp_path,monkeypatch,defect):
    from ravel.physics import existing_events
    task,base,prepared,job,build_base,_,_,_,_,_=public_input_fixture(tmp_path,monkeypatch)
    if defect=='build_source':(build_base/'source/Framework/real.cxx').write_text('altered source')
    elif defect=='build_recipe':
        path=build_base/'build.json';config=json.loads(path.read_text());config['recipe']['flags']=['-O3'];path.write_text(json.dumps(config))
    elif defect=='copied_binary':(prepared/'work/build/qualified-platform/bin/simpleAnalysis').write_bytes(b'changed ELF control')
    elif defect=='copied_observer':(prepared/'work/native-observer.so').write_bytes(b'changed observer')
    elif defect=='copied_event':(prepared/'events.root').write_bytes(b'changed slim input')
    elif defect=='original_event':Path(task['events']).write_bytes(b'changed original slim input')
    elif defect=='copied_object_contract':(prepared/'object-contract.json').write_text('{"level":"unapproved"}')
    elif defect=='program':(prepared/'run.sh').write_text('arbitrary rehashed command')
    elif defect=='transport':job['transport']=copy.deepcopy(job['transport']);job['transport']['image']['config_sha256']='c'*64
    elif defect=='extra_runtime':(prepared/'work/unbound.so').write_bytes(b'unbound library')
    elif defect=='job_symlink':
        path=Path(task['container_plan']);other=base/'alias-job.json';other.write_bytes(path.read_bytes());path.unlink();path.symlink_to(other)
    if defect not in ('transport','job_symlink'):
        job['input_files']=container.tree_facts(prepared)
    if defect!='job_symlink':Path(task['container_plan']).write_text(json.dumps(job))
    # Structure still validates. Real public input admission must reject evidence
    # drift before any worker/client executes and without creating output paths.
    assert existing_events.validate(task) is None
    with pytest.raises(ValueError):existing_events.inputs(task,base)
    assert not (base/'unexecuted-event-output').exists()
