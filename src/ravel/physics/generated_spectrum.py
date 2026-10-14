"""Fresh generated FlexibleSUSY CMSSM/NMSSM/lowMSSM build/solver to raw SLHA transport.

This runs supplied generated source, not SARAH or symbolic model derivation.
Solver convergence, printed warnings, decay completeness and downstream model
conventions remain separate scientific review obligations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
import zipfile

from ravel.physics import model_tool_bridge as custody
from ravel.physics import model_sources, model_inputs, model_specific_spectrum as named, spheno_mssm as spheno

PHASE_SECONDS={'configure':120,'compile':1200,'solver':60}
STAGE_SECONDS=1440
TARGET='models/CMSSM/run_CMSSM.x'
INPUT='models/CMSSM/LesHouches.in.CMSSM'
SOURCE_ROOT='cmssm'
TOOLS=('cc','cxx','fc','make','gsl_config')
NAMED_ENVIRONMENT=('FLEXIBLESUSY_LOOP_LIBRARY','LD_LIBRARY_PATH','DYLD_LIBRARY_PATH','DYLD_INSERT_LIBRARIES')
BUILD_ENVIRONMENT=('CFLAGS','CXXFLAGS','CPPFLAGS','LDFLAGS','CPATH','CPLUS_INCLUDE_PATH',
    'C_INCLUDE_PATH','LIBRARY_PATH','COMPILER_PATH','GCC_EXEC_PREFIX','CC','CXX','FC',
    'F77','LD','AR','AS','RANLIB','MAKEFLAGS','CONFIG_SITE','CCC_OVERRIDE_OPTIONS')

def validate(task):
    custody._keys(task,('config',),'generated spectrum task')
    if not isinstance(task['config'],str) or not task['config'].strip():
        raise ValueError('explicit source-bound spectrum config required')
    return dict(task)

def validate_config(c):
    if c.get("schema_version")==3:return spheno.validate(c)
    custody._keys(c,('schema_version','operation','source','trusted_generated_source',
        'source_capsule','boost_capsule','eigen_capsule','tools','runtime_inputs',
        'max_ram_mib', *(['profile','input_card','calculate_decays','loop_library'] if c.get('schema_version')==2 else [])),'generated spectrum config')
    if type(c['schema_version']) is not int or (c['schema_version'],c['operation']) not in ((1,'flexiblesusy-2.9.0-generated-CMSSM'),(2,'flexiblesusy-2.9.0-generated-NMSSM'),(2,'flexiblesusy-2.9.0-generated-lowMSSM')):
        raise ValueError('explicit released CMSSM legacy or named NMSSM/lowMSSM generated-source operation required')
    if c['schema_version']==2:
        named.validate_extension(c)
        if c['operation']=='flexiblesusy-2.9.0-generated-lowMSSM':
            from . import weak_scale_mssm as weak
            if c['profile']!=weak.NAME:raise ValueError('operation must bind the exact weak-scale MSSM profile')
        elif c['profile']!=named.NAME:raise ValueError('NMSSM operation must bind the exact NMSSM profile')
    if c['trusted_generated_source'] is not True or not isinstance(c['source'],str) or not c['source'].strip():
        raise ValueError('explicit trust and provenance for executable generated source required')
    custody._keys(c['tools'],TOOLS,'fixed spectrum compiler tools')
    if not isinstance(c['runtime_inputs'],list) or not 1<=len(c['runtime_inputs'])<=100000:
        raise ValueError('explicit finite compiler/GSL/runtime file inventory required')
    if type(c['max_ram_mib']) is not int or not 1024<=c['max_ram_mib']<=4096:
        raise ValueError('one-worker sampled RAM must be1024..4096MiB')
    return c

def _bundle(fact,base):
    manifest=custody._pin(fact,base);doc=custody._read(manifest)
    bundle=model_sources._capsule_bundle(manifest,doc,base)
    inventory=model_sources._verify_bundle(bundle,doc['files'],doc['modes'])
    return manifest,bundle,doc,inventory

def _load(task,base):
    validate(task);path=custody._regular(task['config'],base)
    return path,validate_config(custody._read(path))

def source_contract(key,doc,bundle,c=None):
    """Check fixed source/header roles in the complete bound archive, not by label."""
    if c is not None and spheno.selected(c):
        spheno.source_contract(doc);return
    with zipfile.ZipFile(bundle) as archive:
        if key=='source_capsule' and c is not None and c['schema_version']==2:
            named.source_contract(doc,c['profile'])
        elif key=='source_capsule':
            required={SOURCE_ROOT+'/configure',SOURCE_ROOT+'/'+INPUT,
                SOURCE_ROOT+'/models/CMSSM/module.mk',SOURCE_ROOT+'/models/CMSSM/CMSSM_two_scale_spectrum_generator.cpp'}
            if doc['baseline_kind']!='pregenerated-spectrum' or not required<=set(doc['files']) or any(not name.startswith(SOURCE_ROOT+'/') for name in doc['files']):
                raise ValueError('complete generated CMSSM source roles required')
            if any(name.endswith(('.o','.a','.so','.dylib','.x','.pyc')) or name.split('/')[-1] in ('Makefile','config.status','config.log') for name in doc['files']):
                raise ValueError('prebuilt/partial/configured state cannot enter fresh source build')
            text=archive.read(SOURCE_ROOT+'/configure').decode('utf-8')
            for suffix,value in (('MAJOR','2'),('MINOR','9'),('PATCH','0')):
                if re.findall(r'^FLEXIBLESUSY_'+suffix+r'=([^\r\n]+)$',text,re.M)!=[value]:
                    raise ValueError('supplied configure does not identify FlexibleSUSY2.9.0')
            if not doc['modes'][SOURCE_ROOT+'/configure']&0o111:
                raise ValueError('supplied configure must preserve its executable source mode')
        else:
            if doc['baseline_kind']!='supplied-build-headers' or any(not name.startswith(('include/','info/','etc/','share/')) for name in doc['files']):
                raise ValueError('explicit complete build-header source capsule required')
            if key=='boost_capsule':
                text=archive.read('include/boost/version.hpp').decode('utf-8')
                if re.findall(r'^#define\s+BOOST_VERSION\s+(\d+)\s*$',text,re.M)!=['108500']:
                    raise ValueError('supplied Boost headers must identify1.85.0')
            elif key=='eigen_capsule':
                text=archive.read('include/eigen3/Eigen/src/Core/util/Macros.h').decode('utf-8')
                for name,value in (('WORLD','3'),('MAJOR','4'),('MINOR','0')):
                    if re.findall(r'^#define\s+EIGEN_'+name+r'_VERSION\s+(\d+)\s*$',text,re.M)!=[value]:
                        raise ValueError('supplied Eigen headers must identify3.4.0')
                for name in ('include/eigen3/Eigen/Core','include/eigen3/unsupported/Eigen/MatrixFunctions','include/eigen3/unsupported/Eigen/CXX11/Tensor'):
                    if name not in doc['files']:raise ValueError('complete core/unsupported Eigen source roles required')
            else:raise ValueError('unknown generated spectrum source role')

def inputs(task,base):
    path,c=_load(task,base);rows=[path]
    if spheno.selected(c):
        rows+=spheno.inputs(c,path.parent)
        return sorted(set(rows+list(Path(__file__).resolve().parents[1].rglob("*.py"))))
    for key in ('source_capsule','boost_capsule','eigen_capsule'):
        manifest,bundle,doc,_=_bundle(c[key],path.parent);rows.extend((manifest,bundle))
        source_contract(key,doc,bundle,c)
    for name,fact in c['tools'].items():
        tool=custody._pin(fact,path.parent)
        if not os.access(tool,os.X_OK):raise ValueError('pinned compiler/tool must be executable')
        if name=='cxx' and tool.name!='clang-22':raise ValueError('this source operation binds the regular clang22 driver')
        rows.append(tool)
    rows.extend(custody._pin(fact,path.parent) for fact in c['runtime_inputs'])
    if c['schema_version']==2:rows.extend(named.extension_inputs(c,path.parent))
    rows.extend(Path(__file__).resolve().parents[1].rglob('*.py'))
    return sorted(set(rows))

def commands(c,base,work,out):
    if spheno.selected(c):return spheno.commands(c,base,work,out),None
    tools={name:str(custody._pin(fact,base)) for name,fact in c['tools'].items()};loc=named.layout(c)
    configure=[str(work/'source'/loc['root']/'configure'),'--with-models='+loc['model'],'--with-solvers=two_scale',
        '--disable-meta','--disable-librarylink','--disable-threads','--with-cxx='+str(work/'cxx-driver'),
        '--with-fc='+tools['fc'],'--with-boost-incdir='+str(work/'boost/include'),
        '--with-eigen-incdir='+str(work/'eigen/include/eigen3'),'--with-gsl-config='+tools['gsl_config'],
        '--with-cxxflags=-std=c++17 -O2 -fPIC']
    if c['schema_version']==2 and c['loop_library'] is not None:
        q=c['loop_library'];configure+=['--with-loop-libraries='+q['name'],
            '--with-'+q['name']+'-incdir='+str(custody._regular(q['include_directory'],base,directory=True)),
            '--with-'+q['name']+'-libdir='+str(custody._regular(q['library_directory'],base,directory=True))]
    compile=[tools['make'],'-j1',loc['target']]
    selected=work/'selected-input.slha' if c['schema_version']==2 else work/'source'/loc['root']/loc['input']
    solver=[str(work/'source'/loc['root']/loc['target']),'--slha-input-file='+str(selected),
        '--slha-output-file='+str(out/(loc['model']+'.slha'))]
    return {'configure':configure,'compile':compile,'solver':solver},tools['cc']

def launcher(command,cwd,cc,named_model=False):
    """Literal argv/cwd only, no shell interpolation or user-supplied expressions."""
    return ('import os\n'+ 'command='+repr(command)+'\n'+ 'os.chdir('+repr(str(cwd))+')\n'+
        'for name in '+repr(BUILD_ENVIRONMENT+(NAMED_ENVIRONMENT if named_model else ()) )+': os.environ.pop(name,None)\n'+
        'os.environ["CC"]='+repr(cc)+'\n'+'os.environ["LC_ALL"]="C"\n'+
        'for name in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS"): os.environ[name]="1"\n'+
        'os.execv(command[0],command)\n')

def cxx_driver(executable):
    """Use pinned clang bytes with the exact C++ argv0; no symlink lookup occurs."""
    if Path(executable).name!='clang-22':raise ValueError('regular clang22 driver required')
    argv0=str(Path(executable).with_name('clang++-22'))
    return ('#!'+sys.executable+'\nimport os,sys\n'
        'os.execv('+repr(str(executable))+',['+repr(argv0)+',*sys.argv[1:]])\n')

def diagnose_slha(raw,source):
    digest=hashlib.sha256(raw).hexdigest()
    # Empty declaration means explicitly unknown channel completeness, not zero omitted BR.
    completeness={'schema_version':1,'source_sha256':digest,'channel_completeness':{}}
    try:
        inventory=model_inputs.audit_slha_bytes(raw,source_name=source,expected_sha256=digest,completeness_manifest=completeness)
        disposition='static_inventory';refusal=None
    except ValueError as exc:
        inventory=None;disposition='static_parser_refusal';refusal=str(exc)
    warnings=[];block=None
    try:text=raw.decode('utf-8')
    except UnicodeDecodeError:text=None
    for number,line in enumerate(text.splitlines() if text is not None else [],1):
        tokens=line.split('#',1)[0].split()
        if tokens and tokens[0].upper()=='BLOCK':block=tokens[1].upper() if len(tokens)>1 else None
        elif tokens and tokens[0].upper() in ('DECAY','XSECTION'):block=None
        elif block in ('SPINFO','DCINFO') and tokens:warnings.append({'block':block,'line':number,'source_text':line})
    return {'source_sha256':digest,'static_inventory':inventory,'static_disposition':disposition,
        'static_refusal':refusal,'all_info_rows':warnings,'channel_completeness_declared':False,
        'text_decoded':text is not None,'physics_validated':False,
        'scope':'Original solver bytes/static MASS and DECAY source arithmetic only; no spectrum accuracy or complete physical channels.'}

def _approved(task,output):
    for root in (Path(output).absolute(),*Path(output).absolute().parents):
        if (root/'inputs/science-plan.json').is_file():
            from ravel.workflow import science
            selected=science.verify_worker(root);spec=science.execution_spec(root)
            if (spec['mode']!='generated-spectrum' or spec['task']!=task
                    or Path(output).resolve()!=(root/selected['output_directory']).resolve()
                    or selected['max_seconds']<STAGE_SECONDS):
                raise ValueError('spectrum build differs from exact approved supervised worker/resources')
            return root
    raise ValueError('spectrum build requires an approved supervised worker')

def _restored_inputs(c,base,work):
    """Original members stay immutable; configure/build may add derived files."""
    for name,key in (('source','source_capsule'),('boost','boost_capsule'),('eigen','eigen_capsule')):
        doc=custody._read(custody._pin(c[key],base));root=work/name
        for member,digest in doc['files'].items():
            file=custody._regular(member,root)
            if custody._hash(file)!=digest or stat.S_IMODE(file.stat().st_mode)!=doc['modes'][member]:
                raise ValueError('original restored source/header member changed: '+member)
        # Header distributions are closed inputs. Only the source build tree
        # admits newly generated configure, object, dependency and target files.
        if name!='source':
            actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
            if actual!=set(doc['files']) or any(p.is_symlink() for p in root.rglob('*')):
                raise ValueError('restored header membership changed')

def _compiled_pin(path):
    file=custody._regular(path,Path.cwd())
    if not os.access(file,os.X_OK) or file.stat().st_size<=0:
        raise ValueError('fresh compiled spectrum target not executable/nonempty')
    return {'path':str(file),'sha256':custody._hash(file),'bytes':file.stat().st_size,
        'mode':stat.S_IMODE(file.stat().st_mode)}

def run(task,base,output):
    root=_approved(task,output);start=time.monotonic();path,c=_load(task,base)
    if spheno.selected(c):return _run_spheno(task,base,output,root,path,c,start)
    before={str(p):custody._hash(p) for p in inputs(task,base)}
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=True)
    work=root/'work/generated-spectrum'/out.name
    if work.exists() or any(p.is_symlink() for p in (work,*work.parents)):
        raise ValueError('fresh canonical ordinary spectrum workspace required')
    work.mkdir(parents=True)
    restores={name:model_sources.restore_source_bundle(c[key],path.parent,work/name)
        for name,key in (('source','source_capsule'),('boost','boost_capsule'),('eigen','eigen_capsule'))}
    loc=named.layout(c)
    selected=work/'selected-input.slha' if c['schema_version']==2 else work/'source'/loc['root']/loc['input']
    selected_raw=None
    if c['schema_version']==2:
        source=custody._pin(c['input_card'],path.parent);selected_raw=named.raw_file(source,c['input_card']['sha256'])
        selected.write_bytes(selected_raw)
        if selected.read_bytes()!=selected_raw:raise ValueError('selected named-model input copy changed')
    cmd,cc=commands(c,path.parent,work,out);cwd=work/'source'/loc['root']
    if not cwd.is_dir() or not (work/'boost/include/boost/version.hpp').is_file() or not (work/'eigen/include/eigen3/Eigen/Core').is_file():
        raise ValueError('restored source/header roots differ from admitted roles')
    original_input=custody._hash(selected)
    driver=work/'cxx-driver';driver.write_text(cxx_driver(custody._pin(c['tools']['cxx'],path.parent)));driver.chmod(0o700)
    driver_before=_compiled_pin(driver)
    custody._write(out/'compiler-driver.json',{**driver_before,
        'executable':c['tools']['cxx'],'argv0':str(custody._pin(c['tools']['cxx'],path.parent).with_name('clang++-22')),
        'python_executable':sys.executable,'symlink_lookup_performed':False})
    from ravel.physics.reinterpret_db import execute_native
    executions={}
    target_before=None;retained_before=None
    def phase_inputs():
        if driver_before!=_compiled_pin(driver):
            raise ValueError('fixed generated compiler driver changed before native phase')
        if before!={str(p):custody._hash(p) for p in inputs(task,base)}:
            raise ValueError('original source/runtime changed before native phase')
        _restored_inputs(c,path.parent,work)
        if original_input!=custody._hash(custody._regular(selected,Path.cwd())):
            raise ValueError('exact original solver input changed before native phase')
    for phase,limit in PHASE_SECONDS.items():
        phase_inputs()
        phase_out=out/phase;phase_out.mkdir()
        script=phase_out/'launch.py';script.write_text(launcher(cmd[phase],cwd,cc,c['schema_version']==2))
        if phase=='solver':
            binary=custody._regular(loc['target'],cwd);target_before=_compiled_pin(binary)
            retained=out/('run_'+loc['model']+'.x')
            if retained.exists() or retained.is_symlink():raise ValueError('fresh retained compiled target required')
            with binary.open('rb') as source,retained.open('xb') as target:
                shutil.copyfileobj(source,target)
            retained.chmod(target_before['mode']);retained_before=_compiled_pin(retained)
            if {k:v for k,v in target_before.items() if k!='path'}!={k:v for k,v in retained_before.items() if k!='path'}:
                raise ValueError('retained compiled target copy differs')
            custody._write(out/'compiled-target.json',{**retained_before,'produced_path':str(binary),'main_objects_reused':False})
        remaining=int(STAGE_SECONDS-(time.monotonic()-start))
        if remaining<=0:raise ValueError('generated spectrum stage budget exhausted before '+phase)
        try:
            executions[phase]=execute_native([sys.executable,'-B',str(script)],phase_out,
                {'max_seconds':min(limit,remaining),'max_ram_mib':c['max_ram_mib']})
        except Exception as exc:
            if c['schema_version']==2:
                custody._write(out/'generated-spectrum-progress.json',{'status':'failed','model_profile':c['profile'],
                    'failed_phase':phase,'completed_executions':executions,'failure':type(exc).__name__+': '+str(exc),
                    'physics_validated':False,'raw_phase_outputs_retained':True})
            raise
        if c['schema_version']==2:
            custody._write(out/'generated-spectrum-progress.json',{'status':'phase_returned','model_profile':c['profile'],
                'last_returned_phase':phase,'executions':executions,'physics_validated':False})
        phase_inputs()
        if phase=='solver' and (target_before!=_compiled_pin(binary) or retained_before!=_compiled_pin(retained)):
            raise ValueError('compiled spectrum target changed during solver')
    if before!={str(p):custody._hash(p) for p in inputs(task,base)} or original_input!=custody._hash(selected):
        raise ValueError('original source/runtime or exact solver input changed during build')
    slha=custody._regular(loc['model']+'.slha',out);raw=slha.read_bytes()
    if len(raw)>model_inputs.MAX_BYTES:raise ValueError('solver SLHA exceeds static bound')
    diagnosis=diagnose_slha(raw,str(slha))
    result={'status':'passed','physics_validated':False,'scope':'Fresh supplied generated-source configure/build/solver and raw SLHA transport only',
        'source':c['source'],'source_restores':restores,
        'executions':executions,'solver_input_sha256':original_input,'generated_slha':{'path':str(slha),'sha256':custody._hash(slha),'bytes':len(raw)},
        'compiled_target':retained_before,'compiled_target_stable_after_solver':True,
        'diagnosis':diagnosis,'new_events_generated':0,'compiler_jobs':1,'symbolic_model_generation_performed':False,
        'native_environment_contract':{'removed_build_overrides':list(BUILD_ENVIRONMENT),'CC':cc,'LC_ALL':'C','thread_limits':1},
        'limitations':['Transport/build success is not calibrated spectrum/decay/model validity.','Every SPINFO/DCINFO row and signed mass is preserved; unknown missing/truncated channels remain unresolved.','Declared compiler/GSL support and original input archives are bound; OS/system frameworks and unenumerated compiler defaults remain a finite-capsule boundary requiring runtime review.','Compatible MSSM UFO/SLHA conventions, production cross sections, lifetime/response/likelihood inputs and independent validation remain required before recasting.']}
    if c['schema_version']==2:
        result.update(model_profile=c['profile'],configuration={'path':str(path),'sha256':custody._hash(path)},
            full_slha=named.inventory(raw),input_witness=named.input_witness(selected_raw,c['calculate_decays'],c['loop_library']['name'] if c['loop_library'] else 'none',c['profile']),
            requested_decays=c['calculate_decays'],conventions=named.profile(c['profile'])['conventions'],
            downstream_handoff_scope=named.SCOPE,channel_completeness_declared=False)
        result['native_environment_contract']['removed_build_overrides']+=list(NAMED_ENVIRONMENT)
        if c['profile']==named.NAME:
            result['limitations'][-1]='Compatible NMSSM UFO/SLHA basis/scale conventions, production cross sections, lifetime/response/likelihood inputs and independent physical validation remain required before recasting.'
            result['limitations'].append('NMSSM running couplings/mixings/scales and complete raw return are transported; UFO external matching requires an explicit source-backed full address map and actual accepted derivation/spectrum reviews. Unknown missing widths prevent width matching.')
        else:
            result['decay_implementation_available']=False
            result['limitations'].append('Released lowMSSM supplies no generated decay calculation. Missing widths are unknown; LLP/lifetime requires a separate source-bound decay return.')
            result['limitations'].append('Running input equality M1=M2 is not asserted at every returned scale. This real-parameter DRbar SUSY-scale provider does not implement arbitrary Qin or complex soft prescriptions.')
        phase_inputs()
        if retained_before!=_compiled_pin(retained) or target_before!=_compiled_pin(binary) or slha.read_bytes()!=raw:
            raise ValueError('named-model native outputs changed during complete return diagnosis')
    committed=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode() if c['schema_version']==2 else None
    custody._write(out/'generated-spectrum.json',result)
    if c['schema_version']==2:
        if named.raw_file(out/'generated-spectrum.json')!=committed:
            (out/'generated-spectrum.json').rename(out/'failed-generated-spectrum.json')
            raise ValueError('named-model result altered during initial persistence; original commitment refused')
        phase_inputs()
        if named.raw_file(out/'generated-spectrum.json')!=committed or slha.read_bytes()!=raw:
            (out/'generated-spectrum.json').rename(out/'failed-generated-spectrum.json')
            raise ValueError('named-model result or raw return changed before final delivery')
    return result

def _run_spheno(task,base,output,root,path,c,start):
    """Same admitted engine, two actual upstream phases (no configure fiction)."""
    files=inputs(task,base); before={p:custody._hash(p) for p in files}
    out=Path(output).absolute();spheno.require(not out.exists() or (out.is_dir() and not list(out.iterdir())),"fresh empty SPheno ordinary output required")
    spheno.require(not any(p.is_symlink() for p in (out,*out.parents)),"canonical SPheno output required")
    work=root/'work/generated-spectrum'/out.name
    spheno.require(not work.exists() and not any(p.is_symlink() for p in (work,*work.parents)),"fresh isolated SPheno workspace required")
    spheno.require(not any(out==p or out.is_relative_to(p) or work==p or work.is_relative_to(p) or p.is_relative_to(out) or p.is_relative_to(work) for p in files),"work/output may not overlap input files")
    out.mkdir(parents=True,exist_ok=True);work.mkdir(parents=True)
    restored=model_sources.restore_source_bundle(c['source_capsule'],path.parent,work/'source')
    manifest=spheno.read(custody._pin(c['source_capsule'],path.parent));doc=spheno.document(manifest)
    cwd=work/'source/spheno'
    for name in ('bin','lib','include'): (cwd/name).mkdir(exist_ok=True)
    selected=cwd/'selected-input.slha';native_output=cwd/'spectrum-output.slha'
    spheno.require(not selected.exists() and not native_output.exists() and not (cwd/'LesHouches.in').exists(),"no selected-input collision or ambient fallback input")
    raw_input=spheno.read(custody._pin(c['input_card'],path.parent),c['input_card']['sha256']);witness=spheno.input_witness(raw_input)
    selected.write_bytes(raw_input);spheno.require(spheno.read(selected)==raw_input,"exact supplied native input copy required")
    cmd=spheno.commands(c,path.parent,work,out);executions={};target_pin=None
    def original_inputs():
        spheno.require(before=={p:custody._hash(p) for p in inputs(task,base)},"original SPheno source/card/runtime changed")
        for member,digest in doc['files'].items():
            p=custody._regular(member,work/'source')
            spheno.require(hashlib.sha256(spheno.read(p)).hexdigest()==digest and stat.S_IMODE(p.stat().st_mode)==doc['modes'][member],"restored admitted source changed: "+member)
        spheno.require(spheno.read(selected)==raw_input and not (cwd/'LesHouches.in').exists(),"selected native input changed or fallback introduced")
    from ravel.physics.reinterpret_db import execute_native
    try:
        for phase in ('compile','solver'):
            original_inputs();phase_out=out/phase;phase_out.mkdir()
            script=phase_out/'launch.py';script_raw=spheno.launcher(cmd[phase],cwd,c['native_path'],BUILD_ENVIRONMENT+NAMED_ENVIRONMENT).encode();script.write_bytes(script_raw)
            spheno.require(spheno.read(script)==script_raw,"intended native argv/cwd launcher changed")
            if phase=='solver':
                target=custody._regular('bin/SPheno',cwd);target_pin=_compiled_pin(target)
                target_bytes=spheno.read(target,limit=64*1024*1024);retained=out/'SPheno'
                retained.write_bytes(target_bytes);retained.chmod(target_pin['mode'])
                spheno.require(spheno.read(retained,limit=64*1024*1024)==target_bytes,"compiled retained target differs")
                spheno.require(not native_output.exists(),"fresh native spectrum output required")
            remaining=int(STAGE_SECONDS-(time.monotonic()-start));spheno.require(remaining>0,"existing spectrum stage budget exhausted")
            executions[phase]=execute_native([sys.executable,'-B',str(script)],phase_out,{'max_seconds':min(PHASE_SECONDS[phase],remaining),'max_ram_mib':c['max_ram_mib']})
            original_inputs();spheno.require(spheno.read(script)==script_raw,"native phase launcher changed")
            if phase=='solver':
                spheno.require(target_pin==_compiled_pin(target) and spheno.read(retained,limit=64*1024*1024)==target_bytes,"compiled target changed during solver")
        raw=spheno.read(native_output);spheno.require(raw,"nonempty actual SPheno return required")
        slha=out/'MSSM.slha';slha.write_bytes(raw);spheno.require(spheno.read(slha)==raw,"native raw SLHA copy changed")
        full=named.inventory(raw)
        result={'status':'passed','model_profile':spheno.NAME,'physics_validated':False,'scope':'Consistent source-bound SPheno4.0.5 MSSM spectrum and emitted decay transport; physical completeness/accuracy unresolved',
            'source':c['source'],'configuration':{'path':str(path),'sha256':custody._hash(path)},'source_restores':{'source':restored},'executions':executions,'solver_input_sha256':hashlib.sha256(raw_input).hexdigest(),
            'generated_slha':{'path':str(slha),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)},'native_slha':{'path':str(native_output),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)},
            'full_slha':full,'input_witness':witness,'diagnosis':diagnose_slha(raw,str(slha)),'conventions':spheno.profile()['conventions'],
            'requested_decays':True,'channel_completeness_declared':False,'compiled_target':target_pin,'native_commands':cmd,'native_cwd':str(cwd),
            'phase_ceilings_seconds':{p:PHASE_SECONDS[p] for p in ('compile','solver')},'native_environment_contract':{'PATH':c['native_path'],'removed_build_overrides':list(BUILD_ENVIRONMENT+NAMED_ENVIRONMENT),'LC_ALL':'C','thread_limits':1},
            'downstream_handoff_scope':named.SCOPE,'new_events_generated':0,'compiler_jobs':1,'symbolic_model_generation_performed':False,'width_grafting_performed':False,
            'limitations':spheno.profile()['limitations']+['Runtime transitive system/compiler closure is a separately reviewed finite-capsule limitation.','Near-degenerate mixed MSSM hadronic completeness and original81-point LLP physics remain unresolved.']}
        # Freeze every delivered member and native workspace before final callbacks.
        # Result does not contain itself; exact expected serializer bytes commit it.
        # Return the same strict JSON value as the durable receipt (scalar
        # address dictionaries otherwise have integer keys before encoding).
        result=json.loads(json.dumps(result,allow_nan=False))
        result['complete_native_workspace']=spheno.population(work)
        result['complete_pre_result_outputs']=spheno.population(out)
        expected_work=result['complete_native_workspace'];expected_out=result['complete_pre_result_outputs']
        intended_result=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode()
        result_path=out/'generated-spectrum.json';commit=spheno.write_exact(result_path,result)
        original_inputs()
        spheno.require(spheno.read(native_output)==raw and spheno.read(slha)==raw and target_pin==_compiled_pin(target) and spheno.read(retained,limit=64*1024*1024)==target_bytes,"original native return/compiled target commitment changed")
        spheno.require(expected_work==spheno.population(work),"complete native workspace changed before final delivery")
        ending=spheno.population(out);ending.pop('generated-spectrum.json',None)
        spheno.require(ending==expected_out and hashlib.sha256(spheno.read(result_path,limit=64*1024*1024)).hexdigest()==commit['sha256'],"complete SPheno outputs/result changed before delivery")
        spheno.require(spheno.read(result_path,limit=64*1024*1024)==intended_result and (json.dumps(result,indent=2,allow_nan=False)+'\n').encode()==intended_result,
            "returned SPheno result differs from its intended durable commitment")
        return result
    except Exception as exc:
        spheno.write_exact(out/'generated-spectrum-failure.json',{'status':'failed','model_profile':spheno.NAME,'executions':executions,'failure':type(exc).__name__+': '+str(exc),'physics_validated':False,'original_outputs_retained':True})
        raise

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--rundir',required=True)
    parser.add_argument('--review-policy',required=True);parser.add_argument('--approval-mode',choices=('physicist','scripted_yes'),default='physicist')
    args=parser.parse_args(argv);task={'config':str(custody._regular(args.config,Path.cwd()))};inputs(task,Path.cwd())
    policy=custody._read(custody._regular(args.review_policy,Path.cwd()))
    if policy['policy']['max_redos']!=0:raise ValueError('first generated spectrum source point has zero redo')
    _,configuration=_load(task,Path.cwd())
    description=('Explicit supplied generated FlexibleSUSY2.9.0 CMSSM source and original example input' if configuration['schema_version']==1 else configuration['source'])
    spec={'schema_version':2,'mode':'generated-spectrum','source':description,
        'assumptions':['Generated source bypasses new symbolic derivation; no Wolfram/SARAH/license operation is invoked.','Fresh configure/build/solver transport is distinct from physical spectrum, decay and downstream recast qualification.'],
        'max_seconds':STAGE_SECONDS,'max_attempts':1,'approval_mode':args.approval_mode,'review_policy':policy,'task':task}
    proposal=Path(args.rundir).absolute().with_name(Path(args.rundir).name+'-proposal')
    if proposal.exists() or Path(args.rundir).exists():raise ValueError('fresh spectrum study/proposal required')
    proposal.mkdir(parents=True);source=proposal/'science.json';custody._write(source,spec)
    from ravel.workflow import science
    science.plan(args.rundir,source);return 0

if __name__=='__main__':raise SystemExit(main())
