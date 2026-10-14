"""Reuse an observed source-built SimpleAnalysis runtime on supplied slim ROOT.

Preparation copies the already accepted runtime and its existing native observer.
It does not compile, boot a VM, acquire an image or convert detector objects.
Execution is a closed container job admitted by the ordinary scientific study.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil

from ravel import analysis_sources as sources
from ravel.physics import routine_build, simpleanalysis_build as build
from ravel.physics import simpleanalysis_container as container
from ravel.physics import simpleanalysis_adapter as adapter
from ravel.physics.simpleanalysis_observer import verify_native_image
from ravel.physics.simpleanalysis_outputs import read_outputs
from ravel.physics.simpleanalysis_recipe import validate_guest
from ravel.workflow.science import regular
from ravel.workflow.state_io import atomic_json, read_json

_FIELDS = {'backend','routine','build_receipt','build_plan','events','object_contract','regions','container_plan'}


def validate(task):
    if not isinstance(task,dict) or set(task) not in (_FIELDS,_FIELDS|{'weight_name'}) or task['backend']!='simpleanalysis-built':
        raise ValueError('closed source-built SimpleAnalysis event task required')
    if 'weight_name' in task and (not isinstance(task['weight_name'],str) or not task['weight_name']):
        raise ValueError('explicit selected native MC-weight name required')
    if not isinstance(task['routine'],str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*',task['routine']):
        raise ValueError('literal native routine name required')
    regions=task['regions']
    if not isinstance(regions,list) or not regions or len(set(regions))!=len(regions) or any(not isinstance(r,str) or not re.fullmatch('[A-Za-z0-9_]+',r) or r=='All' for r in regions):
        raise ValueError('explicit unique source region names required')
    for field in ('build_receipt','build_plan','events','object_contract','container_plan'):
        if not isinstance(task[field],str) or not task[field]:
            raise ValueError('explicit source/build/event/container input paths required')


def _build(receipt_path, plan_path):
    receipt_path,plan_path=Path(receipt_path).resolve(),Path(plan_path).resolve()
    if receipt_path.parent!=plan_path.parent:
        raise ValueError('retained receipt and original build plan must share their build output')
    receipt,plan=read_json(receipt_path),read_json(plan_path)
    if receipt.get('schema_version')!=3 or plan.get('schema_version')!=3 or plan.get('framework')!='simpleanalysis':
        raise ValueError('observed source-built native SimpleAnalysis receipt/v3 required')
    routine_build.verify_receipt(receipt,plan,plan['base_dir'],receipt_path.parent)
    return receipt,plan,receipt_path.parent


def guest_program(guest,routine,weight_index=0):
    """The fixed zero-build event program; all interpolated paths are closed."""
    validate_guest(guest)
    if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*',routine):
        raise ValueError('literal selected native routine required')
    if type(weight_index) is not int or weight_index<0:
        raise ValueError('exact nonnegative supplied MC-weight index required')
    binary='/tmp/ravel-work/build/'+guest['binary_relative']
    platform=Path(guest['binary_relative']).parts[0]
    program='''#!/bin/bash
set -euo pipefail
mkdir -p /tmp/ravel-output/probe
exec > /tmp/ravel-output/events.log 2>&1
set +u
set +o pipefail
source SETUP
set -euo pipefail
export LC_ALL=C LC_CTYPE=C OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cp -a /tmp/ravel-input/work /tmp/ravel-work
set +u
set +o pipefail
source /tmp/ravel-work/build/PLATFORM/setup.sh
set -euo pipefail
sha256sum SETUP BINARY /tmp/ravel-work/native-observer.so
RAVEL_NATIVE_BINARY=BINARY RAVEL_NATIVE_OBSERVER_DIRECTORY=/tmp/ravel-output/probe LD_PRELOAD=/tmp/ravel-work/native-observer.so BINARY -a ROUTINE -o /tmp/ravel-output/selection -n -w WEIGHT_INDEX /tmp/ravel-input/events.root
printf '%s\\n' SOURCE_BUILT_SIMPLEANALYSIS_EVENTS_COMPLETED
'''
    replacements={'SETUP':guest['setup']['path'],'PLATFORM':platform,'BINARY':binary,'ROUTINE':routine,'WEIGHT_INDEX':str(weight_index)}
    return re.sub(r'\b(?:SETUP|PLATFORM|BINARY|ROUTINE|WEIGHT_INDEX)\b',lambda match:replacements[match[0]],program)


def _facts(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('ordinary bound event input required')
    return {'sha256':sources.digest(path),'size':path.stat().st_size}


def _contract(receipt,plan,build_out,routine,events,object_contract,regions,weight_name='nominal'):
    binding=routine_build.bound_routine(receipt,plan,build_out,routine)
    guest=read_json(build_out/'container-input/source-contract.json')['guest']
    runtime=build_out/'container-output/runtime'
    if 'work/native-observer.so' not in receipt['runtime_files']:
        raise ValueError('accepted native build did not retain its observer for zero-build event reuse')
    selection=adapter.weight_selection(read_json(object_contract),weight_name)
    return {'schema_version':2,'kind':'source-built-simpleanalysis-events','routine':routine,
        'regions':regions,'source_binding':binding,'build_receipt_sha256':sources.digest(build_out/'build-receipt.json'),
        'build_plan_sha256':sources.digest(build_out/'build-plan.json'),'runtime_files':container.tree_facts(runtime),
        'guest':guest,'events':_facts(events),'object_contract':_facts(object_contract),
        'selected_weight':selection,
        'command':['/tmp/ravel-work/build/'+guest['binary_relative'],'-a',routine,'-o','/tmp/ravel-output/selection','-n','-w',str(selection['index']),'/tmp/ravel-input/events.root'],
        'source_builds':0,'physics_validated':False}


def prepare_inputs(receipt_path,plan_path,routine,events,object_contract,regions,destination,*,weight_name='nominal'):
    """Stage an exact accepted runtime and native inputs before science.plan."""
    receipt,plan,build_out=_build(receipt_path,plan_path)
    probe_task={'backend':'simpleanalysis-built','routine':routine,'build_receipt':str(receipt_path),
        'build_plan':str(plan_path),'events':str(events),'object_contract':str(object_contract),
        'regions':regions,'container_plan':'prepared-later','weight_name':weight_name}
    validate(probe_task)
    adapter.read_input(events,read_json(object_contract),require_native_abi=True,weight_name=weight_name)
    contract=_contract(receipt,plan,build_out,routine,events,object_contract,regions,weight_name)
    destination=Path(destination)
    if destination.exists():raise ValueError('preserve prior prepared native event input')
    destination.mkdir(parents=True)
    shutil.copytree(build_out/'container-output/runtime/work',destination/'work')
    shutil.copy2(events,destination/'events.root');shutil.copy2(object_contract,destination/'object-contract.json')
    (destination/'run.sh').write_text(guest_program(contract['guest'],routine,contract['selected_weight']['index']))
    atomic_json(destination/'event-contract.json',contract)
    return {'input_directory':str(destination.resolve()),'input_files':container.tree_facts(destination),
            'source_builds':0,'physics_validated':False}


def execution_plan(task,base,out):
    """Read-only admission, also used by the outer prelaunch recovery hook."""
    validate(task)
    paths={key:regular(task[key],base) for key in ('build_receipt','build_plan','events','object_contract','container_plan')}
    receipt,plan,build_out=_build(paths['build_receipt'],paths['build_plan'])
    object_contract=read_json(paths['object_contract'])
    weight_name=task.get('weight_name','nominal')
    expected=adapter.read_input(paths['events'],object_contract,require_native_abi=True,weight_name=weight_name)
    job=read_json(paths['container_plan'])
    if job.get('transport')!=plan['container_job']['transport']:
        raise ValueError('event runtime transport differs from accepted source-built image/qualification')
    rebuilt=container.make_plan(job['transport'],job['input_directory'],max_seconds=job['resources']['max_seconds'],memory_mib=job['resources']['memory_mib'])
    if rebuilt!=job:raise ValueError('native event job differs from bound inputs/resources')
    prepared=Path(job['input_directory'])
    contract=_contract(receipt,plan,build_out,task['routine'],paths['events'],paths['object_contract'],task['regions'],weight_name)
    if read_json(prepared/'event-contract.json')!=contract or (prepared/'run.sh').read_text()!=guest_program(contract['guest'],task['routine'],contract['selected_weight']['index']):
        raise ValueError('native event guest/source/runtime program contract differs')
    files={**{p:fact for p,fact in receipt['runtime_files'].items()},
        'events.root':contract['events'],'object-contract.json':contract['object_contract'],
        'event-contract.json':_facts(prepared/'event-contract.json'),'run.sh':_facts(prepared/'run.sh')}
    if container.tree_facts(prepared)!=files:
        raise ValueError('prepared event runtime/input bytes differ from accepted source build')
    return {'schema_version':1,'kind':'source-built-simpleanalysis-event-plan','routine':task['routine'],
        'base_dir':str(Path(base).resolve()),'output_directory':str(Path(out).resolve()),'task':task,
        'build_output':str(build_out),'build_receipt_sha256':sources.digest(paths['build_receipt']),
        'build_plan_sha256':sources.digest(paths['build_plan']),'contract':contract,'container_job':job,
        'input_events':len(expected),'source_builds':0,'compute_authorized':False,'physics_validated':False}


def execution_seconds(task,base):
    """Preserve the exact admitted container wall ceiling, including its cleanup.

    Reuse read-only plan validation rather than trusting a detached resource
    field. No source build, container query, event job or output is created.
    """
    plan=execution_plan(task,base,Path(base)/'unexecuted-event-output')
    return plan['container_job']['resources']['max_seconds']


def inputs(task,base):
    # Plan construction requires an output spelling only for its retained record;
    # no container namespace is launched or inspected during admission.
    plan=execution_plan(task,base,Path(base)/'unexecuted-event-output')
    build_out=Path(plan['build_output']);build_plan=read_json(build_out/'build-plan.json')
    files=build.inputs({'backend':'routine-build','input':build_plan['input']['path']},build_plan['base_dir'])
    files += [p for p in build_out.rglob('*') if p.is_file()]
    files += [regular(task[k],base) for k in ('events','object_contract','container_plan')]
    contract=read_json(regular(task['object_contract'],base))
    files += [regular(contract['object_definitions'],base),*[regular(p,base) for p in contract['response_evidence']]]
    files += [Path(plan['container_job']['input_directory'])/p for p in plan['container_job']['input_files']]
    return list(dict.fromkeys(files))


def _evidence(plan,out):
    out=Path(out);job=plan['container_job'];guest=out/'container-output';contract=plan['contract']
    transport=container.verify_receipt(read_json(out/'container-receipt.json'),job,out)
    binary=out/'container-input/work/build'/contract['guest']['binary_relative']
    if sources.digest(binary)!=contract['source_binding']['binary_sha256']:
        raise ValueError('selected event binary differs from accepted source build')
    native=verify_native_image(guest/'probe',binary,contract['command'][0],read_json(job['transport']['qualification']['path']))
    if (guest/'probe/cmdline.raw').read_bytes().split(b'\0')[:-1]!=[arg.encode() for arg in contract['command']]:
        raise ValueError('actual native event argv differs')
    log=(guest/'events.log').read_text().splitlines()
    for path,sha in [(contract['guest']['setup']['path'],contract['guest']['setup']['sha256']),
        (contract['command'][0],contract['source_binding']['binary_sha256']),
        ('/tmp/ravel-work/native-observer.so',contract['runtime_files']['work/native-observer.so']['sha256'])]:
        if log.count(sha+'  '+path)!=1:
            raise ValueError('event guest setup/binary/observer byte identity differs')
    if log.count('SOURCE_BUILT_SIMPLEANALYSIS_EVENTS_COMPLETED')!=1:
        raise ValueError('native event completion marker missing or duplicated')
    return {'transport':transport,'native_image':native,'source_binding':contract['source_binding'],
            'source_builds':0,'physics_validated':False}


def run(task,base,out):
    plan=execution_plan(task,base,out);out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/'event-plan.json').exists():raise ValueError('preserve prior native event attempt')
    atomic_json(out/'event-plan.json',plan)
    container.execute(plan['container_job'],out)
    observed=_evidence(plan,out)
    if execution_plan(task,base,out)!=plan:
        raise ValueError('accepted source/runtime/native event input changed during execution')
    expected=adapter.read_input(regular(task['events'],base),read_json(regular(task['object_contract'],base)),require_native_abi=True,weight_name=task.get('weight_name','nominal'))
    result=adapter.parse_outputs(out/'container-output',task['routine'],expected,task['regions'])
    native_outputs=read_outputs(out/'container-output/selection.root',task['routine'],expected_events=len(expected))
    native_outputs['selected_weight']=plan['contract']['selected_weight']
    atomic_json(out/'native-output.json',native_outputs)
    atomic_json(out/'decisions.json',result.pop('decisions'))
    weight_name=plan['contract']['selected_weight']['name']
    if weight_name!='nominal':
        result['yields']={weight_name:result['yields']['nominal']}
        result['covariance']={weight_name:result['covariance']['nominal']}
    result.update(status='passed',routine=task['routine'],physics_validated=False,
        scope='Source/API execution on explicitly supplied native slim ROOT',
        source_builds=0,source_binding=plan['contract']['source_binding'],observed=observed,
        selected_weight=plan['contract']['selected_weight'],
        build_receipt_sha256=plan['build_receipt_sha256'],build_plan_sha256=plan['build_plan_sha256'],
        native_outputs={'path':'native-output.json','sha256':sources.digest(out/'native-output.json'),
                        'size':(out/'native-output.json').stat().st_size,
                        'object_census':native_outputs['object_census']},
        limitations=['Observed source-built main ELF and complete input-event census establish routine API execution only.',
                     'Detector response, model applicability and statistical/physics calibration require separate evidence.',
                     'Only the explicitly selected supplied MC-weight stream is executed; native reweighter/systematic options require separate source admission.',
                     'Overlapping yields and native per-bin Sumw2 imply no joint histogram covariance or exclusion limit.'])
    return result
