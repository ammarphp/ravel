"""Source-built SimpleAnalysis through the standard governed routine-build task.

The transport runs only already acquired/qualified immutable images. This module
never acquires an image, boots a VM, installs tools, or infers physics validation.
Planning is read-only. Compiler, target graph, source bytes, native main image,
full listing and closed-container observations are rebound after execution.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex

from ravel import analysis_sources as sources
from ravel.physics import simpleanalysis_container as container
from ravel.physics.simpleanalysis_observer import NATIVE_LOADER_OBSERVER,verify_native_image
from ravel.physics.simpleanalysis_recipe import offline_external_overlay,guest_programs
from ravel.workflow.science import regular
from ravel.workflow.state_io import atomic_json,read_json


def _qualified_external_inputs(name, entry, observed, qualification_path, prepared, base):
    """Rebind the full extracted archive census and its single project root.

    The qualifier retains the complete ordinary-file manifest beside its receipt.
    A self-declared staged tree cannot replace that acquisition. This checks
    retained bytes, not remote Git history or external process authentication.
    """
    if entry['source_commit'] != observed['commit'] or entry['archive_sha256'] != observed['sha256']:
        raise ValueError('offline dependency differs from qualified archive identity')
    archive = regular(observed['path'], base)
    if sources.digest(archive) != entry['archive_sha256']:
        raise ValueError('acquired source archive bytes differ')
    census_path = regular(Path(qualification_path).parent / (name + '-source-files.json'), base)
    if sources.digest(census_path) != observed.get('source_files_sha256'):
        raise ValueError('qualified extracted source census bytes differ')
    census = read_json(census_path)
    if not isinstance(census, dict) or not census or type(observed.get('ordinary_files')) is not int or len(census) != observed['ordinary_files']:
        raise ValueError('complete qualified extracted source census required')
    prefixes = set()
    for relative, fact in census.items():
        sources.relative_path(relative)
        if not isinstance(fact, dict) or set(fact) != {'sha256', 'size'} or not isinstance(fact['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', fact['sha256']) or type(fact['size']) is not int or fact['size'] < 0:
            raise ValueError('ordinary qualified extracted source file facts required')
        parts = Path(relative).parts
        if len(parts) < 2:
            raise ValueError('one complete archive project directory required')
        prefixes.add(parts[0])
    extracted = Path(observed['extracted_root'])
    if not extracted.is_absolute() or any(p.is_symlink() for p in (extracted, *extracted.parents)) or container.tree_facts(extracted) != census or len(prefixes) != 1:
        raise ValueError('actual extracted archive differs from qualified full source census')
    project = extracted / next(iter(prefixes))
    declared_root = Path(entry['root'])
    if not declared_root.is_absolute() or declared_root != project or any(p.is_symlink() for p in (declared_root, *declared_root.parents)):
        raise ValueError('offline dependency root is not the complete qualified archive project')
    prefix = project.name + '/'
    expected = {p[len(prefix):]: fact for p, fact in census.items()}
    if entry['files'] != expected or container.tree_facts(project) != expected or container.tree_facts(Path(prepared) / 'work/externals' / name) != expected:
        raise ValueError('actual offline dependency source bytes differ from qualified extraction')
    return [archive, census_path, *[regular(extracted / p, base) for p in census]]


def _configuration(task,base):
    from ravel.physics.routine_build import validate
    validate(task);cp=regular(task['input'],base);config=read_json(cp)
    if not isinstance(config,dict) or set(config)!={'schema_version','source_capsule','recipe','container_plan'} or config['schema_version']!=3:
        raise ValueError('closed native container routine-build configuration/v3 required')
    sp=regular(config['source_capsule'],base);capsule=sources.load_capsule(sp);root,files=sources.source_files(capsule,base)
    if capsule['framework']!='simpleanalysis' or not capsule['submodules'] or not capsule['dependency_review']['complete'] or any(d['status']!='resolved' for d in capsule['dependencies']):
        raise ValueError('complete native source/submodule/runtime/asset closure required')
    recipe=config['recipe'];roles={f['path']:f['role'] for f in capsule['files']}
    if set(recipe)!={'name','compile_units','output','flags'} or recipe['name']!='simpleanalysis-analysisbase' or recipe['flags']!=[]:
        raise ValueError('full upstream SimpleAnalysis closed native recipe required')
    declared={p for p,role in roles.items() if role=='compile'};units=recipe['compile_units']
    if not isinstance(units,list) or not units or len(set(units))!=len(units) or set(units)!=declared-{'SimpleAnalysisFramework/util/slimMaker.cxx'}:
        raise ValueError('complete simpleAnalysis target source denominator required; slimMaker is a separate target')
    sources.relative_path(recipe['output'])
    if Path(recipe['output']).name!='simpleAnalysis':raise ValueError('the full upstream simpleAnalysis target is required')
    jp=regular(config['container_plan'],base);job=read_json(jp)
    rebuilt=container.make_plan(job['transport'],job['input_directory'],max_seconds=job['resources']['max_seconds'],memory_mib=job['resources']['memory_mib'],cpus=job['resources'].get('cpus',1))
    if rebuilt!=job:raise ValueError('closed container job plan differs from bound inputs/resources')
    prepared=Path(job['input_directory']);contract=read_json(prepared/'source-contract.json')
    inventory=sources.inventory(capsule,base);bindings=container.routine_bindings(capsule,base,units)
    expected_fields = {'source_inventory','routine_bindings','compile_units','offline_external_overlays','external_sources','guest','observer_source_sha256','physics_validated'} | ({'dependency_checkpoint'} if 'dependency_checkpoint' in contract else set())
    if set(contract)!=expected_fields or contract['physics_validated'] is not False or contract['source_inventory']!=inventory or contract['routine_bindings']!=bindings or set(contract['compile_units'])!=declared:
        raise ValueError('prepared native source/routine contract differs from admitted capsule')
    if contract['guest']['binary_relative']!=recipe['output'] or contract['guest']['qualification_sha256']!=sources.digest(job['transport']['qualification']['path']):
        raise ValueError('guest layout or actual qualification identity differs')
    if contract['guest'].get('compiler_jobs',1) > job['resources'].get('cpus',1):
        raise ValueError('native compiler jobs exceed explicitly declared container CPUs')
    for name,program in guest_programs(contract['guest'],contract.get('dependency_checkpoint')).items():
        if (prepared/name).read_text()!=program:
            raise ValueError('native compiler/guest command program differs from fixed recipe')
    observer=NATIVE_LOADER_OBSERVER.encode()
    if (prepared/'native-observer.c').read_bytes()!=observer or contract['observer_source_sha256']!=hashlib.sha256(observer).hexdigest():
        raise ValueError('actual same-process native observer source differs')
    overlays={entry['path']:entry for entry in contract['offline_external_overlays']}
    if set(overlays)!={'Ext_HEPMC/externals.cmake','Ext_RestFrames/externals.cmake'}:
        raise ValueError('only the exact two upstream acquisition clauses may differ')
    expected={}
    for fact in capsule['files']:
        raw=(root/fact['path']).read_bytes()
        if fact['path'] in overlays:
            raw=offline_external_overlay(raw,'HepMC3' if fact['path'].startswith('Ext_HEPMC/') else 'RestFrames')
            if overlays[fact['path']]['before_sha256']!=fact['sha256'] or overlays[fact['path']]['after_sha256']!=hashlib.sha256(raw).hexdigest():
                raise ValueError('offline source acquisition transform differs')
        expected[fact['path']]={'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    if container.tree_facts(prepared/'work/source')!=expected:
        raise ValueError('actual prepared native sources differ from bound upstream/overlay')
    qualification_path=regular(job['transport']['qualification']['path'],base)
    qualification=read_json(qualification_path);external_inputs=[]
    acquisitions=qualification.get('source_acquisitions',[])
    if not isinstance(acquisitions,list) or any(not isinstance(entry,dict) or not isinstance(entry.get('name'),str) for entry in acquisitions):
        raise ValueError('actual independently acquired external source archives required')
    acquired={entry['name']:entry for entry in acquisitions}
    if len(acquired)!=len(acquisitions) or set(contract['external_sources'])!={'HepMC3','RestFrames'} or not set(contract['external_sources'])<=set(acquired):
        raise ValueError('unique actual independently acquired external source archives required')
    for name,entry in contract['external_sources'].items():
        external_inputs.extend(_qualified_external_inputs(name,entry,acquired[name],qualification_path,prepared,base))
    if 'dependency_checkpoint' in contract:
        from ravel.physics import simpleanalysis_checkpoint as checkpoint
        external_inputs.extend(checkpoint.verify(contract['dependency_checkpoint'],prepared,contract))
    return config,capsule,cp,sp,jp,job,contract,files,external_inputs


def inputs(task,base):
    _,_,cp,sp,jp,job,_,files,external_inputs=_configuration(task,base)
    transport=job['transport'];prepared=Path(job['input_directory'])
    paths=[cp,sp,jp,*files,*external_inputs,Path(transport['client']['resolved_path']),
        *[Path(f['path']) for f in transport['client_artifacts']],Path(transport['qualification']['path']),
        *[prepared/p for p in job['input_files']]]
    return list(dict.fromkeys(paths))


def build_plan(task,base,out):
    config,capsule,cp,sp,jp,job,contract,_,_=_configuration(task,base)
    out=Path(out).resolve()
    return {'schema_version':3,'kind':'routine-build-plan','recipe':config['recipe'],'routine':capsule['routine'],
        'framework':'simpleanalysis','base_dir':str(Path(base).resolve()),'output_root':str(out),
        'input':{'path':str(cp),'sha256':sources.digest(cp)},'source_capsule':{'path':str(sp),'sha256':sources.digest(sp)},
        'source_inventory':contract['source_inventory'],'routine_bindings':contract['routine_bindings'],
        'container_plan':{'path':str(jp),'sha256':sources.digest(jp)},'container_job':job,
        'binary':'container-output/runtime/work/build/'+config['recipe']['output'],
        'probe_command':['/tmp/ravel-work/build/'+config['recipe']['output'],'-l'],
        'runtime_identity':{'transport':job['transport'],'guest':contract['guest']},
        'compute_authorized':False,'physics_validated':False,
        'scope':'Full original source target in qualified immutable AnalysisBase; compiler/main ELF/listing custody required; no events or physics certification'}


def verify_compiler_graph(plan,out):
    out=Path(out);guest=out/'container-output';contract=read_json(out/'container-input/source-contract.json')
    expected={f['path']:f for f in plan['source_inventory']['files'] if f['role']=='compile'}
    commands=read_json(guest/'compile_commands.json')
    if not isinstance(commands,list) or not commands:raise ValueError('actual CMake compile-command denominator required')
    command_sources=set();command_argv={}
    for command in commands:
        path=Path(command['file'])
        if not path.is_absolute():path=Path(command['directory'])/path
        command_sources.add(str(path))
        arguments=command.get('arguments') or shlex.split(command['command'])
        command_argv[str(path)]=arguments
        if str(path).startswith('/tmp/ravel-work/source/') and command['file'] not in arguments and str(path) not in arguments:
            raise ValueError('CMake source path is not the actual compile-command operand')
    replies=guest/'cmake-reply';indexes=list(replies.glob('index-*.json'))
    if len(indexes)!=1:raise ValueError('one actual CMake File API target graph required')
    index=read_json(indexes[0]);codemodel=index['reply']['codemodel-v2']['jsonFile'];sources.relative_path(codemodel)
    model=read_json(replies/codemodel);generated=set();target_names=set()
    for configuration in model['configurations']:
        for target_ref in configuration['targets']:
            sources.relative_path(target_ref['jsonFile'])
            target=read_json(replies/target_ref['jsonFile']);target_names.add(target['name'])
            for source in target.get('sources',[]):
                if source.get('isGenerated') and 'compileGroupIndex' in source:
                    path=Path(source['path']);generated.add(str(path if path.is_absolute() else Path(model['paths']['build'])/path))
    if 'simpleAnalysis' not in target_names or 'SimpleAnalysisFrameworkLib' not in target_names:
        raise ValueError('actual full SimpleAnalysis native target graph required')
    journal=guest/'compiler-invocations.jsonl';rows=[json.loads(line) for line in journal.read_text().splitlines()]
    seen={};observed_generated={};tools=contract['guest']['tools'];driver=tools['compiler']
    if not rows:raise ValueError('actual source compiler invocations required')
    for row in rows:
        if row.get('schema_version')!=1 or type(row.get('pid')) is not int or row['pid']<=0 or row.get('driver_path')!=driver['path'] or row.get('driver_sha256')!=driver['sha256'] or not row.get('argv') or row['argv'][0]!=driver['path'] or not row.get('cwd','').startswith('/tmp/ravel-work/build/') and row.get('cwd')!='/tmp/ravel-work/build':
            raise ValueError('actual native compiler path/bytes/argv differ')
        for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
            if row['environment'].get(key)!='1':raise ValueError('native compiler worker envelope differs')
        for fact in row['compile_inputs']:
            raw=base64.b64decode(fact['content_base64'],validate=True)
            if hashlib.sha256(raw).hexdigest()!=fact['sha256'] or fact['path'] not in command_sources or fact['path'] not in row['argv'] or row['argv']!=command_argv[fact['path']]:
                raise ValueError('actual compiler raw source/operand differs from target graph')
            if fact['path'].startswith('/tmp/ravel-work/source/'):
                relative=fact['path'][len('/tmp/ravel-work/source/'):]
                if relative not in expected or sources.digest(out/'container-input/work/source'/relative)!=fact['sha256'] or expected[relative]['sha256']!=fact['sha256'] or relative in seen:
                    raise ValueError('missing/duplicate/drifting upstream native compile input')
                seen[relative]=fact['sha256']
            elif fact['path'] in generated:
                if fact['path'] in observed_generated:raise ValueError('duplicate generated native target input')
                observed_generated[fact['path']]=fact['sha256']
            else:raise ValueError('unbound native compiler source outside upstream/generated target')
    if set(seen)!=set(plan['recipe']['compile_units']) or not observed_generated:
        raise ValueError('full observed native target/source/dictionary coverage required')
    return {'status':'passed','observed_source_units':seen,'observed_generated_units':observed_generated,
            'source_units_declared':len(expected),'source_units_compiled':len(seen),'target_names':sorted(target_names),
            'excluded_unbuilt_target_sources':sorted(set(expected)-set(seen)),'physics_validated':False}


def _evidence(plan,out):
    out=Path(out);guest=out/'container-output';job=plan['container_job']
    transport=container.verify_receipt(read_json(out/'container-receipt.json'),job,out)
    contract=read_json(out/'container-input/source-contract.json')
    if read_json(guest/'source-contract.json')!=contract:
        raise ValueError('actual native retained source contract differs')
    log=(guest/'build.log').read_text()
    native_tools=[contract['guest']['setup'],*[contract['guest']['tools'][key] for key in ('compiler','c_compiler','cmake')]]
    for tool in native_tools:
        matches=re.findall(r'(?m)^([0-9a-f]{64})  '+re.escape(tool['path'])+r'$',log)
        if matches!=[tool['sha256']]:
            raise ValueError('actual native setup/compiler/CMake tool bytes differ from qualified guest')
    for fact in plan['source_inventory']['files']:
        relative=fact['path'];before=out/'container-input/work/source'/relative;after=guest/'runtime/work/source'/relative
        if not after.is_file() or after.read_bytes()!=before.read_bytes():
            raise ValueError('actual native staged upstream source changed during build')
    binary=out/plan['binary'];qualification=read_json(job['transport']['qualification']['path'])
    native=verify_native_image(guest/'probe',binary,plan['probe_command'][0],qualification)
    if (guest/'probe/cmdline.raw').read_bytes().split(b'\0')[:-1]!=[item.encode() for item in plan['probe_command']]:
        raise ValueError('actual native listing argv differs')
    names=container.verify_listing((guest/'listing.stdout').read_bytes(),plan['routine_bindings'])
    graph=verify_compiler_graph(plan,out)
    return {'transport':transport,'native_image':native,'compiler_graph':graph,'registered_names':names}


def run(task,base,out):
    plan=build_plan(task,base,out);out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/'build-plan.json').exists():raise ValueError('preserve prior native build attempt')
    atomic_json(out/'build-plan.json',plan);atomic_json(out/'source-inventory.json',plan['source_inventory'])
    container.execute(plan['container_job'],out)
    observed=_evidence(plan,out)
    if build_plan(task,base,out)!=plan:raise ValueError('native source/runtime/job changed during actual build')
    receipt={'schema_version':3,'kind':'routine-build-receipt','status':'passed','routine':plan['routine'],'framework':'simpleanalysis',
        'recipe':plan['recipe']['name'],'source_capsule_sha256':plan['source_capsule']['sha256'],
        'source_inventory_sha256':sources.digest(out/'source-inventory.json'),'build_plan_sha256':sources.digest(out/'build-plan.json'),
        'binary':{'path':plan['binary'],'sha256':sources.digest(out/plan['binary'])},
        'runtime_identity':plan['runtime_identity'],'observed':observed,
        'evidence_files':{p:{'sha256':sources.digest(out/p),'size':(out/p).stat().st_size} for p in [
            'container-receipt.json','container-client.jsonl','container-cleanup.json','container-output/compiler-invocations.jsonl',
            'container-output/compile_commands.json','container-output/listing.stdout','container-output/listing.stderr',
            'container-output/source-contract.json','container-output/build.log']},
        'runtime_files':container.tree_facts(out/'container-output/runtime'),'physics_validated':False,
        'limitations':['Actual compiler/staged source/main ELF/listing observations are retained before-main/build boundaries, not authenticated external process attestation.',
            'Full compiled target and canonical names establish source/runtime API capability; no event, detector response, model or physics validity is inferred.']}
    atomic_json(out/'build-receipt.json',receipt)
    return receipt


def verify_receipt(receipt,plan,base,out):
    out=Path(out).resolve()
    if read_json(out/'build-receipt.json')!=receipt or read_json(out/'build-plan.json')!=plan or plan!=build_plan({'backend':'routine-build','input':plan['input']['path']},base,out):
        raise ValueError('retained native build receipt/plan/input identity differs')
    fields={'schema_version','kind','status','routine','framework','recipe','source_capsule_sha256','source_inventory_sha256','build_plan_sha256','binary','runtime_identity','observed','evidence_files','runtime_files','physics_validated','limitations'}
    if set(receipt)!=fields or receipt['schema_version']!=3 or receipt['kind']!='routine-build-receipt' or receipt['status']!='passed' or receipt['physics_validated'] is not False:
        raise ValueError('successful observed native routine-build receipt/v3 required')
    for key,value in {'routine':plan['routine'],'framework':'simpleanalysis','recipe':plan['recipe']['name'],'source_capsule_sha256':plan['source_capsule']['sha256'],'runtime_identity':plan['runtime_identity']}.items():
        if receipt[key]!=value:raise ValueError('native source/build/runtime identity differs')
    if receipt['source_inventory_sha256']!=sources.digest(out/'source-inventory.json') or read_json(out/'source-inventory.json')!=plan['source_inventory'] or receipt['build_plan_sha256']!=sources.digest(out/'build-plan.json') or receipt['binary']!={'path':plan['binary'],'sha256':sources.digest(out/plan['binary'])}:
        raise ValueError('native source/plan/binary byte identity differs')
    for p,fact in receipt['evidence_files'].items():
        sources.relative_path(p)
        if not (out/p).is_file() or (out/p).is_symlink() or {'sha256':sources.digest(out/p),'size':(out/p).stat().st_size}!=fact:
            raise ValueError('retained native build evidence changed')
    if container.tree_facts(out/'container-output/runtime')!=receipt['runtime_files'] or _evidence(plan,out)!=receipt['observed']:
        raise ValueError('native build runtime/actual observation differs')
    return {'status':'passed','routine':plan['routine'],'binary_sha256':receipt['binary']['sha256'],
            'registered_names':receipt['observed']['registered_names'],'prospectively_sealed':True,
            'custody':'source-target-compiler-main-elf-closed-container','physics_validated':False}


def bound_routine(receipt,plan,out,routine):
    verify_receipt(receipt,plan,plan['base_dir'],out)
    binding=plan['routine_bindings'].get(routine)
    if binding is None or routine not in receipt['observed']['registered_names'] or binding['registration']!='literal-DefineAnalysis' or any(f['path'] not in receipt['observed']['compiler_graph']['observed_source_units'] for f in binding['source_files']):
        raise ValueError('selected native routine lacks actual source/compiler/listing custody')
    return {'routine':routine,'primary_build_routine':plan['routine'],'source_binding':binding,
            'binary_sha256':receipt['binary']['sha256'],'physics_validated':False}
