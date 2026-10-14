"""Ordinary supplied-HepMC2 CheckMATE studies using the existing science worker.

First operation: complete native SR tables from a bounded supplied stream. A
configured-runtime control is distinct from later region delivery. Neither is
detector validation, a CLs endpoint, paper reproduction or catalogue coverage.
No compiler, installer, generation, shower or statistical model is substituted.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import math
import os
import re
from pathlib import Path

from ravel.physics import backend_provider as provider
from ravel.workflow import science
from ravel.workflow.state_io import atomic_json, read_json

SCOPE = 'complete bounded supplied-event native CheckMATE SR table with source-column semantics'


def _keys(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError(label+' requires exactly '+', '.join(sorted(names)))


def _pin(value, base):
    _keys(value, ('path','sha256'), 'input pin')
    path = science.regular(value['path'], base)
    if provider._sha(path) != value['sha256']:
        raise ValueError('bound backend input changed: '+str(path))
    return path


def validate(task):
    _keys(task, ('config',), 'checkmate-events task')
    if not isinstance(task['config'],str) or not task['config'].strip():
        raise ValueError('checkmate-events config required')
    return deepcopy(task)


def _load(task, base):
    validate(task)
    path = science.regular(task['config'],base)
    c = read_json(path)
    fields=('schema_version','purpose','catalogue','request','python','runtime_manifest','prior_qualification','max_seconds','max_ram_mib','source')
    _keys(c,fields+('event_conversion','reader_library','reader_seconds') if 'event_conversion' in c else fields,'CheckMATE configuration')
    if type(c['schema_version']) is not int or c['schema_version']!=1:
        raise ValueError('CheckMATE configuration version1 required')
    if c['purpose'] not in ('configured-runtime-control','region-delivery'):
        raise ValueError('distinct runtime-control or region-delivery purpose required')
    if not isinstance(c['source'],str) or not c['source'].strip():
        raise ValueError('backend scientific/source description required')
    if type(c['max_seconds']) is not int or not 1<=c['max_seconds']<=900:
        raise ValueError('native ceiling must be1..900seconds')
    if type(c['max_ram_mib']) is not int or not 512<=c['max_ram_mib']<=8192:
        raise ValueError('native RAM ceiling must be512..8192MiB')
    return path,c


def hepmc2_census(path, requested):
    """Read the entire stream's declared event weight vectors, without simulation.

    This is a framing/exposure witness. It does not validate particle/vertex
    kinematics, detector response or the native reader's consumed weights.
    """
    if type(requested) is not int or not 1<=requested<=1000:
        raise ValueError('first native operation permits1..1000 supplied events')
    weights=[]; started=False; ended=False; version=False
    with Path(path).open() as stream:
        for line in stream:
            parts=line.split()
            if not parts: continue
            if ended: raise ValueError('trailing HepMC2 records')
            if parts[0]=='HepMC::Version':
                if version or started or len(parts)!=2 or not re.fullmatch(r'[23]\.[0-9.]+',parts[1]):
                    raise ValueError('exact HepMC2 version framing required')
                version=True
            elif parts[0]=='HepMC::IO_GenEvent-START_EVENT_LISTING':
                if not version or started: raise ValueError('duplicate/out-of-order event-list start')
                started=True
            elif parts[0]=='HepMC::IO_GenEvent-END_EVENT_LISTING':
                if not started: raise ValueError('event-list end before start')
                ended=True
            elif not started:
                raise ValueError('record before event-list start')
            elif parts[0]=='E':
                if len(parts)<13: raise ValueError('truncated HepMC2 E record')
                count=int(parts[11])
                if count<0 or 12+count>=len(parts): raise ValueError('invalid random-state vector')
                index=12+count; nweights=int(parts[index])
                if nweights<1 or len(parts)!=index+1+nweights:
                    raise ValueError('explicit complete HepMC2 weight vector required')
                vector=[float(w) for w in parts[index+1:]]
                if not all(math.isfinite(w) for w in vector): raise ValueError('nonfinite event weight')
                # First native route deliberately refuses multiplexed weights;
                # no arbitrary nominal-index assumption reaches the reader.
                if nweights!=1: raise ValueError('first route requires exactly one explicit weight per event')
                weights.append(vector[0])
                if len(weights)>requested: raise ValueError('input exposure exceeds requested complete stream')
            elif parts[0] not in ('N','U','C','H','F','V','P'):
                raise ValueError('unsupported HepMC2 record type')
    if not version or not started or not ended or len(weights)!=requested:
        raise ValueError('complete HepMC2 framing/exposure differs from request')
    try:
        sums=(math.fsum(weights),math.fsum(w*w for w in weights))
    except OverflowError as error:
        raise ValueError('nonfinite event-weight moments') from error
    if not all(math.isfinite(w) for w in sums) or sums[0]<=0:
        raise ValueError('first route requires finite moments and positive total normalization weight')
    return {'events':len(weights),'sum_weights':sums[0],
            'sum_squared_weights':sums[1],
            'negative_events':sum(w<0 for w in weights),'zero_events':sum(w==0 for w in weights),
            'nominal_weight_index':0,'native_weight_consumption_observed':False,
            'particle_kinematics_validated':False}


def configured_layout(script, root, fritz):
    """Resolve the actual configured entry's literal paths before execution."""
    tree=ast.parse(Path(script).read_text()); paths={}; appended=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.Assign):
            for t in n.targets:
                if isinstance(t,ast.Subscript) and isinstance(t.value,ast.Name) and t.value.id=='config_paths':
                    try: key=ast.literal_eval(t.slice); value=ast.literal_eval(n.value)
                    except (ValueError,TypeError): continue
                    if key in paths: raise ValueError('duplicate configured entry path')
                    paths[key]=value
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='append' and isinstance(n.func.value,ast.Attribute):
            if ast.unparse(n.func.value)=='sys.path' and len(n.args)==1:
                try: appended.append(ast.literal_eval(n.args[0]))
                except (ValueError,TypeError): pass
    root=Path(root).resolve()
    # First qualification uses a source-local configured build. Remote installs
    # need a distinct asset relocation map rather than guessed prefix rewriting.
    if paths.get('remote')!='no' or Path(paths.get('install_dir','')).resolve()!=root:
        raise ValueError('first route requires an exact source-local configured CheckMATE build')
    if str(root/'tools/python') not in [str(Path(p).resolve()) for p in appended if isinstance(p,str)]:
        raise ValueError('configured Python import path differs from pinned source')
    if Path(fritz).resolve()!=root/'tools/fritz/bin/fritz':
        raise ValueError('configured Fritz path differs from bound native binary')
    for key in ('data_dir','source'):
        if Path(paths.get(key,'')).resolve()!=root:
            raise ValueError('source-local configured '+key+' differs from pinned source')
    return {'source_root':str(root),'data_root':str(root/'data'),
            'python_source_root':str(root/'tools/python'),'fritz':str(Path(fritz).resolve()),
            'scope':'Literal configured paths only; actual module/library/plugin/card consumption requires independent observation.'}



def verify_configured_entry(template, script, values):
    """Bind configure substitutions without permitting arbitrary entry code."""
    text=Path(template).read_text()
    tokens=set(re.findall(r'@([A-Za-z0-9_]+)@',text))
    _keys(values,tokens,'exact configure substitution values')
    if any(not isinstance(v,str) or any(c in v for c in ('\n','\r',"'",'"','@')) for v in values.values()):
        raise ValueError('configure values must be literal quote/newline-free strings')
    effective=re.sub(r'@([A-Za-z0-9_]+)@',lambda match: values[match[1]],text)
    if Path(script).read_bytes()!=effective.encode():
        raise ValueError('configured entry differs from exact released template substitutions')
    compile(effective,str(script),'exec') # Syntax only, no import or execution.


def _admission(task, base):
    path,c=_load(task,base); directory=path.parent
    catalog_path=_pin(c['catalogue'],directory); catalog=provider.read_json(catalog_path)
    request_path=_pin(c['request'],directory); request=provider.read_json(request_path)
    _keys(request, ('routine','events','format','max_events','cross_section_fb','cross_section_error_fb',
                    'random_seed','model','quantity','output_parent','name','weight_convention','runtime'), 'native request')
    provider._number(request['cross_section_fb'],'cross section',positive=True)
    provider._number(request['cross_section_error_fb'],'cross section error')
    if type(request['random_seed']) is not int or request['random_seed']<=0:
        raise ValueError('exact positive native seed required')
    if not isinstance(request['weight_convention'],str) or not request['weight_convention'].strip():
        raise ValueError('explicit source weight convention required')
    if request['quantity']!='region_table' or request['model']!='simple':
        raise ValueError('first ordinary mode delivers region tables only; multibin inference/HS3 CLs are separate operations')
    if catalog['framework']!='checkmate' or catalog['revision'] not in (provider.CM_REVISION,provider.CM_252_REVISION):
        raise ValueError('first route requires exact retained CheckMATE source layout')
    row=provider.resolve(catalog,request['routine']); root=Path(catalog['root'])
    if row['duplicate_metadata_keys'] or not row['metadata_identity_match']:
        raise ValueError('first route requires unambiguous selected metadata identity; aliases/duplicate metadata need an explicit source derivative')
    provider.verify_facts(root,catalog['engine_facts']+catalog['list_facts']+row['facts'])
    if any(f['status']!='present' for f in row['facts']): raise ValueError('selected analysis source/card incomplete')
    event=_pin(request['events'],directory)
    if request['format']!='hepmc2' or event.suffix.lower()!='.hepmc':
        raise ValueError('source-qualified .hepmc HepMC2 input required')
    exposure=hepmc2_census(event,request['max_events'])
    if request['runtime'] is None: raise ValueError('installed configured runtime pins are required; discovery is not runtime')
    runtime=request['runtime']; _keys(runtime,('executable','fritz','manifest'),'backend runtime')
    python=_pin(c['python'],directory); script=_pin(runtime['executable'],directory); fritz=_pin(runtime['fritz'],directory)
    for p in (event,script,fritz,python): provider._native_path(str(p))
    if not os.access(python,os.X_OK) or not os.access(fritz,os.X_OK): raise ValueError('native Python/Fritz must be executable')
    manifest_path=_pin(c['runtime_manifest'],directory)
    if manifest_path!=_pin(runtime['manifest'],directory): raise ValueError('two different runtime manifests')
    manifest=read_json(manifest_path)
    fields=('schema_version','kind','revision','python_sha256','entry_sha256','fritz_sha256','configured_values','files','scope')
    compat=catalog['revision']==provider.CM_252_REVISION
    _keys(manifest,fields+('compatibility_overlay',) if compat else fields,'runtime manifest')
    if (type(manifest['schema_version']) is not int or manifest['schema_version']!=1 or
        manifest['kind']!='checkmate-declared-runtime' or manifest['revision']!=catalog['revision'] or
        manifest['python_sha256']!=c['python']['sha256'] or manifest['entry_sha256']!=runtime['executable']['sha256'] or
        manifest['fritz_sha256']!=runtime['fritz']['sha256'] or not isinstance(manifest['files'],list) or not manifest['files']):
        raise ValueError('native runtime manifest differs from executable/source identities')
    if not isinstance(manifest['scope'],str) or not manifest['scope'].strip():
        raise ValueError('declared runtime scope required')
    if compat:
        from ravel.physics import checkmate_252_compat,hepmc_legacy_conversion
        layout=checkmate_252_compat.verify(root,script,manifest['configured_values'],manifest['compatibility_overlay'])
        if python!=Path(manifest['configured_values']['python']).resolve():raise ValueError('declared2.5.2 interpreter differs from configured original')
        if fritz.resolve()!=root/'tools/fritz/bin/fritz':raise ValueError('bound2.5.2 Fritz path differs')
        if type(c['reader_seconds']) is not int or not 1<=c['reader_seconds']<c['max_seconds']:raise ValueError('explicit bounded readback reservation required')
        reader_library=_pin(c['reader_library'],directory)
        if reader_library!=(Path(manifest['configured_values']['ROOT_LIB_DIR'])/'libDelphes.dylib').resolve():
            raise ValueError('reader library differs from configured original ROOT/Delphes prefix')
        conversion_path=_pin(c.get('event_conversion'),directory)
        converted=hepmc_legacy_conversion.verify_manifest(conversion_path)
        if converted['event_output']!=request['events'] or converted['events']!=request['max_events']:raise ValueError('event conversion differs from exact native exposure')
    else:
        verify_configured_entry(root/'tools/python/CheckMATE.in',script,manifest['configured_values'])
        layout=configured_layout(script,root,fritz)
    files=[path,catalog_path,request_path,event,python,script,fritz,manifest_path]
    files += [_pin(f,directory) for f in manifest['files']]
    if compat:
        files += [conversion_path,reader_library]+[_pin(converted[k],directory) for k in ('source','original_prefix','event_output','metadata_sidecar','converter')]
        files += [_pin(v,directory) for v in manifest['compatibility_overlay'].values() if isinstance(v,dict)]
    files += [root/f['path'] for f in catalog['engine_facts']+catalog['list_facts']+row['facts'] if f['status']=='present']
    for rel in row['asset_paths']:
        if '/Likelihoods/' in rel or rel.endswith('pyhf_conf.json'): continue
        f=provider._fact(root,rel)
        if f['status']!='present': raise ValueError('native analysis asset unavailable: '+rel)
        files.append(root/rel)
    declared={str(p.resolve()) for p in files}
    if compat and str(reader_library) not in {str(Path(f['path']).resolve()) for f in manifest['files']}:
        raise ValueError('reader library must be bound in declared runtime closure')
    upstream=list((root/'tools/python').glob('*.py'))
    if not {str(p.resolve()) for p in upstream}<=declared:
        raise ValueError('runtime manifest must bind the complete upstream Python namespace')
    if c['purpose']=='region-delivery':
        _keys(c['prior_qualification'],('rundir','result'),'prior runtime control')
        rd=Path(c['prior_qualification']['rundir']).resolve()
        result_path=_pin(c['prior_qualification']['result'],directory)
        if result_path!=rd/'outputs/attempt-1/result.json': raise ValueError('first prior qualification must bind exact attempt1 result')
        prior=read_json(result_path)
        if (science.packet(rd)['lifecycle_verdict']!='PASS' or science.verify_plan(rd)['max_attempts']!=1 or
            prior.get('routine')!=row['id'] or prior.get('kind')!='checkmate-configured-runtime-control' or prior.get('status')!='passed' or
            prior.get('runtime_identity')!=_identity(c,request) or prior.get('configured_layout')!=layout):
            raise ValueError('prior configured-runtime control is not current accepted exact runtime/source evidence')
        files += [result_path,rd/science.PLAN,rd/science.APPROVAL,rd/'execution_state.json']
    elif c['prior_qualification'] is not None:
        raise ValueError('first runtime control does not inherit unrelated qualification')
    files += list(Path(__file__).resolve().parents[1].rglob('*.py'))
    return path,c,catalog,request,row,exposure,layout,sorted(set(p.resolve() for p in files))


def _identity(c,request):
    return {'catalogue':c['catalogue'],'python':c['python'],'runtime_manifest':c['runtime_manifest'],'runtime':request['runtime']}


def inputs(task,base):
    return _admission(task,base)[-1]


def execution_seconds(task,base):
    # Outer ordinary worker also hashes/prepares/reads back; these30seconds are
    # a declared reservation, not measured runtime qualification.
    return _load(task,base)[1]['max_seconds']+30


def _approved(task,output):
    for rd in (Path(output).absolute(),*Path(output).absolute().parents):
        if (rd/science.PLAN).is_file():
            selected=science.verify_worker(rd); spec=science.execution_spec(rd)
            if spec['mode']!='checkmate-events' or spec['task']!=task or Path(output).resolve()!=(rd/selected['output_directory']).resolve():
                raise ValueError('CheckMATE differs from exact approved worker task/output')
            return rd,selected
    raise ValueError('CheckMATE execution requires approved supervised scientific worker')


def run(task,base,output):
    _,selected=_approved(task,output)
    path,c,catalog,request,row,exposure,layout,files=_admission(task,base)
    if execution_seconds(task,base)>selected['max_seconds']: raise ValueError('native ceiling exceeds approved stage')
    before={str(p):provider._sha(p) for p in files}; out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=True)
    dispatched=deepcopy(request)
    dispatched['output_parent']=str(out/'native'); dispatched['name']='supplied'
    prepared=provider.prepare_checkmate(catalog,dispatched,out/'prepared')
    # This quantity does not silently invoke multi-bin inference. Preparation
    # still reports the unqualified runtime-consumption boundary explicitly.
    command=[str(_pin(c['python'],path.parent)),'-B',str(_pin(request['runtime']['executable'],path.parent)),str(out/'prepared/checkmate.ini')]
    atomic_json(out/'native-dispatch.json',{'command':command,'config_sha256':prepared['configuration_sha256'],
        'input_exposure':exposure,'generated_events':0,'configured_layout':layout,'consumption_verified':False})
    from ravel.physics.reinterpret_db import execute_native
    import time
    native_start=time.monotonic()
    native_config=deepcopy(c)
    compat=catalog['revision']==provider.CM_252_REVISION
    if compat:native_config['max_seconds']-=c['reader_seconds']
    receipt=execute_native(command,out,native_config)
    native_root=Path(prepared['native_output'])
    table=provider.import_region_table(native_root/'evaluation/total_results.txt',row)
    reader=None
    if compat:
        from ravel.physics import checkmate_reader_observation
        remaining=c['max_seconds']-(time.monotonic()-native_start)
        if remaining<=0:raise ValueError('native/readback combined ceiling exhausted')
        rc=deepcopy(c);rc['max_seconds']=min(c['reader_seconds'],remaining)
        observed=out/'reader-observation.json'
        read_command=[str(_pin(c['python'],path.parent)),'-B',str(Path(checkmate_reader_observation.__file__).resolve()),
             '--conversion',str(_pin(c['event_conversion'],path.parent)),'--directory',str(native_root/'delphes'),
             '--library',str(_pin(c['reader_library'],path.parent)),'--library-sha256',c['reader_library']['sha256'],'--out',str(observed)]
        reader_directory=out/'reader-execution';reader_directory.mkdir()
        readback_receipt=execute_native(read_command,reader_directory,rc)
        reader=read_json(observed)
        converted=provider.read_json(_pin(c['event_conversion'],path.parent))
        from ravel.physics import hepmc_legacy_conversion
        checkmate_reader_observation.validate(reader['observation'],hepmc_legacy_conversion.read_legacy(converted['event_output']['path']))
        if (reader.get('status')!='passed' or reader.get('conversion')!=c['event_conversion'] or
            reader.get('library')!=c['reader_library'] or
            reader['observation']['library_load_request']!=str(_pin(c['reader_library'],path.parent))):
            raise ValueError('readback differs from exact bound conversion/library')
        reader['native_receipt']=readback_receipt
    if before!={str(p):provider._sha(p) for p in inputs(task,base)}:
        raise ValueError('backend input/source/runtime changed during execution')
    atomic_json(out/'native-region-table.json',table)
    result={'kind':'checkmate-configured-runtime-control' if c['purpose']=='configured-runtime-control' else 'checkmate-region-delivery',
            'status':'passed','physics_validated':False,'scope':SCOPE,'routine':row['id'],
            'runtime_identity':_identity(c,request),'configured_layout':layout,
            'input_exposure':exposure,'native_execution':receipt,'region_table':table,'event_reader_observation':reader,
            'new_generated_events':0,'source_consumption_verified':False,'detector_validated':False,
            'limitations':['Declared closure/configured literal paths do not prove runtime card/plugin/library consumption.',
                'Persisted reader fields are checked separately; native analysis weight use and detector/selection fidelity remain unqualified.',
                'Complete native SR table only; no CLs, joint independence, full-model inference or paper reproduction.',
                'Configured-runtime control and later region delivery need ordinary CHECK-IN2 review; catalogue rows earn no scientific task credit.']}
    atomic_json(out/'checkmate-result.json',result)
    return result


def prepare(config, review_policy, out, *, approval_mode='physicist'):
    """Materialize an ordinary specification after complete source admission.

    This invokes no compiler, event processor or worker. Existing ravel plan /
    approve / run own the subsequent resource and CHECK-IN2 lifecycle.
    """
    path=Path(config).resolve(); task={'config':str(path)}
    inputs(task,path.parent)
    policy=read_json(science.regular(review_policy,path.parent))
    c=_load(task,path.parent)[1]
    spec={'schema_version':2,'mode':'checkmate-events','source':c['source'],
          'assumptions':[SCOPE,
              'No new hard events, shower, installation or statistical fit; supplied complete HepMC2 stream only.',
              'Declared runtime/source pins are not proof of consumed cards/plugins/libraries or physics closure.',
              'The native stage ceiling excludes a declared30second ordinary preparation/readback reservation.'],
          'max_seconds':execution_seconds(task,path.parent),'approval_mode':approval_mode,
          'task':task,'max_attempts':1,'review_policy':policy}
    science.validate(spec)
    if spec['review_policy']['policy']['max_redos']!=0:
        raise ValueError('first backend route has one prospective attempt and no automatic retry')
    out=Path(out)
    if out.exists(): raise FileExistsError(out)
    atomic_json(out,spec)
    return spec


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--review-policy',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--approval-mode',choices=('physicist','scripted_yes'),default='physicist')
    args=parser.parse_args(argv)
    prepare(args.config,args.review_policy,args.out,approval_mode=args.approval_mode)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
