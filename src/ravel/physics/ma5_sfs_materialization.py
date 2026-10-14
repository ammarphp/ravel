"""Isolated MA5 writer materialization through ordinary routine-build.

This invokes source writers only after ordinary approval. No MA5 launcher,
configuration probe, library build, compiler, installer or events are used.
Generated SFS source is an observed engineering artifact, not a tuned detector.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time

from ravel.physics.ma5_saf import Capture as _Capture, _identity, _json, _keys
from ravel.workflow.state_io import atomic_json

KIND = 'ma5-sfs-materialization'
ASSETS = ('source', 'header', 'info', 'sfs_card')
SOURCE_TREES = ('madanalysis', 'tools/ReportGenerator/Services',
                'tools/SampleAnalyzer/Commons', 'tools/SampleAnalyzer/Process',
                'tools/SampleAnalyzer/Interfaces', 'tools/SampleAnalyzer/Configuration')
EXTRA_SOURCE = ('bin/ma5', 'tools/SampleAnalyzer/newAnalyzer.py')
LIBRARIES = tuple('tools/SampleAnalyzer/Lib/lib'+x+'_for_ma5.so'
                  for x in ('commons', 'fastjet', 'process', 'root'))
SOURCE_SUFFIXES = {'.py', '.h', '.cpp', '.txt', '.dat', '.ma5'}
MAX_SOURCE = 32*1024**2
MAX_FILES = 4096
REQUIRED = ('new_smearer_reco.h', 'new_smearer_reco.cpp', 'sigmas.h', 'reco.h',
            'new_tagger.h', 'new_tagger.cpp', 'efficiencies.h')
ARCHITECTURE = {'isMac': bool, 'has_root': bool, 'has_fastjet': bool,
                'root_compiler': str, 'toPATH1': list, 'toPATH2': list,
                'toLDPATH1': list, 'toLDPATH2': list}

# This is independently authored orchestration of pinned upstream APIs, not a
# replacement SFS implementation. The future helper process records its actual
# imported source and calls upstream writers. It is not executed by planning.
HELPER = r'''import hashlib,json,logging,os,runpy,sys
from pathlib import Path
request=Path(sys.argv[1]);d=json.loads(request.read_text());root=Path(d['source_root']);job=Path(d['job_root'])
# Reset inherited user/runtime search paths before imports. -I -B also applies.
os.environ.clear();os.environ.update(d['environment']);sys.path[:0]=[str(root/'tools/ReportGenerator/Services'),str(root)]
class Errors(logging.Handler):
 def emit(self,record):
  if record.levelno>=logging.ERROR:raise RuntimeError('MA5 writer error: '+record.getMessage())
logging.getLogger('MA5').addHandler(Errors())
from madanalysis.core.main import Main
from madanalysis.enumeration.ma5_running_type import MA5RunningType
from madanalysis.enumeration.normalize_type import NormalizeType
from madanalysis.interpreter.interpreter import Interpreter
from madanalysis.IOinterface.job_writer import JobWriter
# Prevent implicit build/install/helper dispatch. The only allowed process is
# the already supervised Python writer itself; newAnalyzer runs in this process.
def forbidden(*a,**k):raise RuntimeError('materialization cannot dispatch a native/helper process')
import subprocess
subprocess.Popen=forbidden;subprocess.run=forbidden;subprocess.call=forbidden;subprocess.check_call=forbidden;subprocess.check_output=forbidden;os.system=forbidden
Main.BuildLibrary=forbidden;Main.CheckConfig=forbidden;Main.CheckConfig2=forbidden
main=Main();main.archi_info.ma5dir=str(root);main.archi_info.ma5_version='1.11.1';main.archi_info.ma5_date='2026/04/01'
for key,value in d['architecture'].items():setattr(main.archi_info,key,value)
main.mode=MA5RunningType.RECO;main.normalize=NormalizeType.NONE;main.InitObservables(main.mode)
main.forced=True;Main.forced=True;main.script=True;main.expertmode=True
interpreter=Interpreter(main)
for row in d['card_program']:
 line=row['command'];verb,argument=line.split(None,1)
 if verb=='set':interpreter.do_set(argument)
 elif verb=='define':interpreter.do_define(argument)
 else:raise RuntimeError('undeclared card operation')
if main.fastsim.package!='fastjet' or main.recasting.status!='off' or len(main.datasets)!=0 or len(main.selection)!=0 or main.output!='':raise RuntimeError('SFS-only state required')
if not all((main.superfastsim.isNewSmearerOn(),main.superfastsim.isSmearerOn(),main.superfastsim.isRecoOn(),main.superfastsim.isTaggerOn())):raise RuntimeError('complete requested SFS components missing')
jobber=JobWriter(main,str(job),False)
for operation in (jobber.Open,jobber.CopyLHEAnalysis):
 if not operation():raise RuntimeError('upstream job structure failed')
if not jobber.WriteSelectionHeader(main) or not jobber.WriteSelectionSource(main):raise RuntimeError('upstream SFS source writer failed')
a=job/'Build/SampleAnalyzer/User/Analyzer'
for name in ('user.h','user.cpp','analysisList.h'):(a/name).unlink()
previous=os.getcwd();argv=list(sys.argv)
try:
 os.chdir(job/'Build/SampleAnalyzer');sys.argv=[str(job/'Build/SampleAnalyzer/newAnalyzer.py'),d['analysis'],'1'];runpy.run_path(sys.argv[0],run_name='__main__')
finally:os.chdir(previous);sys.argv=argv
# Only stub source/header are replaced by the exact original analysis. Upstream
# SFS sources, analysisList registration and Main are retained unmodified.
for key,suffix in [('source','.cpp'),('header','.h')]:
 raw=Path(d['assets'][key]).read_bytes();(a/(d['analysis']+suffix)).write_bytes(raw)
(job/'Input'/(d['analysis']+'.info')).write_bytes(Path(d['assets']['info']).read_bytes())
if not jobber.WriteMakefiles() or not jobber.CreateBldDir(analysisName=d['analysis'],outputName='analysis.saf'):raise RuntimeError('upstream registration/build writer failed')
imports=[]
for name,module in sorted(sys.modules.items()):
 p=getattr(module,'__file__',None)
 if name=='madanalysis' or name.startswith('madanalysis.') or name in ('string_tools','shell_command','chronometer','colored_log'):
  q=Path(p).resolve() if p else None
  if q is None or not q.is_relative_to(root):raise RuntimeError('upstream import escaped staged source')
  imports.append({'module':name,'path':str(q),'sha256':hashlib.sha256(q.read_bytes()).hexdigest()})
observation={'kind':'ma5-sfs-writer-observation/v1','pid':os.getpid(),'python':{'path':str(Path(sys.executable).resolve()),'sha256':hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()},'environment':dict(os.environ),'request_sha256':hashlib.sha256(request.read_bytes()).hexdigest(),'card_program':d['card_program'],'imports':imports,'analysis':d['analysis'],'source_root':str(root),'job_root':str(job),'compiler_calls':0,'event_calls':0,'physics_validated':False}
Path(d['observation']).write_text(json.dumps(observation,indent=2,allow_nan=False)+'\n')
'''


class Capture(_Capture):
    """Existing descriptor-bound capture, additionally admitting empty source units."""
    def bounded(self,path):
        before=self.ordinary(path)
        if before[3]:return super().bounded(path)
        with path.open('rb') as stream:
            if _identity(os.fstat(stream.fileno()))!=before or stream.read(1) or _identity(os.fstat(stream.fileno()))!=before:
                raise ValueError('empty source identity changed')
        if self.ordinary(path)!=before:raise ValueError('empty source pathname changed')
        return before,b''


def require(condition, message):
    if not condition: raise ValueError(message)


def accepts(task, base):
    if type(task) is not dict or task.get('backend') != 'routine-build': return False
    cap=Capture();_,raw=cap.read(task['input'],base);doc=_json(raw);cap.finish()
    return type(doc) is dict and doc.get('schema_version') == 6 and doc.get('kind') == KIND


def card_program(raw):
    """Retain literal ordered SFS commands; do not evaluate their efficiencies."""
    text=raw.decode('utf-8');rows=[];families=set()
    for ordinal,line in enumerate(text.splitlines(),1):
        command=line.split('#',1)[0].strip()
        if not command:continue
        require(len(command)<=8192 and not any(x in command for x in (';', '\\', '\x00', '`')), 'SFS card cannot contain compound/executable commands')
        if command.startswith('set '):
            require(re.fullmatch(r'set main\.fastsim\.[A-Za-z0-9_.]+\s*=\s*[A-Za-z0-9_.+\-]+',command) is not None,'only literal main.fastsim settings admitted')
        else:
            m=re.fullmatch(r'define (smearer|reco_efficiency|tagger)\s+[^\n]+',command)
            require(m is not None,'only SFS source definitions admitted');families.add(m[1])
        rows.append({'line':ordinal,'command':command})
    require(1<=len(rows)<=1024 and families=={'smearer','reco_efficiency','tagger'},'complete bounded smear/reco/tagger card required')
    require(sum(r['command']=='set main.fastsim.package = fastjet' for r in rows)==1,'one explicit FastJet package setting required')
    return rows


def selected_source(root):
    root=Path(root);cap=Capture();cap.ordinary(root,directory=True);found=set()
    for subtree in SOURCE_TREES:
        directory=root/subtree;cap.ordinary(directory,directory=True)
        for p in directory.rglob('*'):
            if '__pycache__' in p.parts:continue
            if p.suffix in SOURCE_SUFFIXES and (p.is_file() or p.is_symlink()):
                cap.ordinary(p);found.add(p.relative_to(root).as_posix())
    for relative in (*EXTRA_SOURCE,*LIBRARIES):
        cap.ordinary(root/relative);found.add(relative)
    require(len(found)<=MAX_FILES,'bounded complete MA5 source projection required')
    return sorted(found)


def _load(task,base):
    _keys(task,('backend','input'),'routine-build task');require(task['backend']=='routine-build','routine-build backend required')
    c=Capture();cp,raw=c.read(task['input'],base);d=_json(raw)
    _keys(d,('schema_version','kind','analysis','assets','source_manifest','runtime','architecture','resources'),'MA5 materialization config')
    require(type(d['schema_version']) is int and d['schema_version']==6 and d['kind']==KIND,'MA5 materialization schema6 required')
    require(type(d['analysis']) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',d['analysis']) is not None,'safe literal analysis identity required')
    _keys(d['assets'],ASSETS,'complete original analysis/SFS assets')
    asset_paths={k:c.pin(d['assets'][k],cp.parent)[0] for k in ASSETS}
    raw_assets={k:c.files[v][1] for k,v in asset_paths.items()};program=card_program(raw_assets['sfs_card'])
    header=raw_assets['header'].decode();source=raw_assets['source'].decode()
    require(re.search(r'INIT_ANALYSIS\(\s*'+re.escape(d['analysis'])+r'\s*,\s*"'+re.escape(d['analysis'])+r'"\s*\)',header) is not None,'header registration must equal configured analysis')
    require('new_tagger.h' in header and 'new_smearer_reco.h' in header and re.search(r'\b'+re.escape(d['analysis'])+r'::Initialize\b',source) is not None,'original source must depend on generated SFS/header identity')
    mp,mraw=c.pin(d['source_manifest'],cp.parent);manifest=_json(mraw)
    _keys(manifest,('schema_version','root','selection','files'),'MA5 source manifest')
    require(type(manifest['schema_version']) is int and manifest['schema_version']==1 and manifest['selection']=='ma5-sfs-source-projection/v1','explicit source projection required')
    root=Path(manifest['root']);c.ordinary(root,directory=True);rows=manifest['files']
    require(type(rows) is list and 1<=len(rows)<=MAX_FILES,'bounded source-file census required')
    mapping={};total=0
    for row in rows:
        _keys(row,('relative','sha256','size','mode'),'MA5 source member')
        rel=PurePosixPath(row['relative']);require(not rel.is_absolute() and '..' not in rel.parts and str(rel)==row['relative'] and row['relative'] not in mapping,'unique canonical source relative path required')
        require(type(row['size']) is int and 0<=row['size']<=8*1024**2 and type(row['mode']) is int and 0<=row['mode']<=0o777,'bounded source member/permission required')
        p,b=c.read(str(root/rel),cp.parent,expected=row['sha256']);require(len(b)==row['size'] and stat.S_IMODE(p.stat().st_mode)==row['mode'],'source member size/mode differs')
        mapping[row['relative']]=p;total+=len(b)
    require(total<=MAX_SOURCE and sorted(mapping)==selected_source(root),'complete bounded source projection differs')
    require(re.search(r"version\s*=\s*['\"]1\.11\.1['\"]",c.files[root/'bin/ma5'][1].decode()) is not None,'pinned MA5 1.11.1 source required; other versions need fresh admission')
    _keys(d['runtime'],('python','files'),'materialization runtime');python,_=c.pin(d['runtime']['python'],cp.parent)
    require(os.access(python,os.X_OK),'bound interpreter must be executable')
    require(type(d['runtime']['files']) is list and len(d['runtime']['files'])<=4096,'bounded explicit interpreter/dependency census required')
    runtime=[c.pin(v,cp.parent)[0] for v in d['runtime']['files']];require(len(runtime)==len(set(runtime)),'unique runtime dependencies required')
    _keys(d['architecture'],ARCHITECTURE,'declared writer architecture projection')
    for key,typ in ARCHITECTURE.items():
        value=d['architecture'][key];require(type(value) is typ,'typed writer architecture projection required')
        if typ is str:require(re.fullmatch(r'/[A-Za-z0-9_./+\-]+',value) is not None,'literal compiler pathname required')
        if typ is list:require(len(value)<=32 and all(type(v) is str and v.startswith('/') and not any(x in v for x in ('\n','\x00','`','$',';')) for v in value),'bounded literal path projection required')
    require(d['architecture']['has_root'] is True and d['architecture']['has_fastjet'] is True,'declared ROOT/FastJet writer configuration required; not observed ABI')
    _keys(d['resources'],('max_seconds','max_ram_mib','max_output_bytes'),'materialization resources')
    for key,low,high in [('max_seconds',1,600),('max_ram_mib',128,4096),('max_output_bytes',1024,128*1024**2)]:
        require(type(d['resources'][key]) is int and low<=d['resources'][key]<=high,'bounded materialization resources required')
    c.finish();return d,cp,c,root,mapping,asset_paths,program


def configuration(task,base):
    return deepcopy(_load(task,base)[0])


def inputs(task,base):
    return list(_load(task,base)[2].files)


def execution_seconds(task,base):
    return _load(task,base)[0]['resources']['max_seconds']


def fact(path,cap):
    p,b=cap.read(str(path),Path(path).parent)
    return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'size':len(b)}


def build_plan(task,base,out):
    d,cp,c,root,mapping,assets,program=_load(task,base);out=Path(out).absolute()
    require('..' not in out.parts and not any(q.is_symlink() for q in (out,*out.parents)),'canonical owned output required')
    from ravel.physics.routine_build import isolated_process_environment
    environment=isolated_process_environment(out/'work/home',out/'work/tmp');environment['PYTHONDONTWRITEBYTECODE']='1'
    plan={'schema_version':6,'kind':'ma5-sfs-materialization-plan','task':deepcopy(task),'base_dir':str(Path(base).absolute()),'input':fact(cp,c),
          'analysis':d['analysis'],'configuration':deepcopy(d),'source_root':str(root),'source_projection':d['source_manifest'],
          'source_files':[{'relative':r,'input':fact(p,c),'mode':stat.S_IMODE(p.stat().st_mode)} for r,p in mapping.items()],
          'input_pins':[fact(p,c) for p in c.files], 'output_root':str(out),'job_root':str(out/'job'),
          'command':[str(Path(d['runtime']['python']['path']) if Path(d['runtime']['python']['path']).is_absolute() else cp.parent/d['runtime']['python']['path']),'-I','-B',str(out/'writer.py'),str(out/'writer-request.json')],
          'helper_sha256':hashlib.sha256(HELPER.encode()).hexdigest(),'card_program':program,'environment':environment,
          'assets':{k:str(v) for k,v in assets.items()},'required_generated_members':list(REQUIRED),'saf_output':'analysis.saf',
          'scope':'Source writer materialization only; no compiler/load/events/tuned-response or scientific acceptance',
          'qualified_native_runtime':False,'physics_validated':False}
    c.finish();return plan


def _write(path,value,cap):
    intended=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode();atomic_json(path,json.loads(intended));p,b=cap.read(str(path),path.parent)
    require(b==intended,'generated materialization document differs from intended bytes');return fact(p,cap)


def _copy(path,raw,mode):
    require(not path.exists() and not path.is_symlink(),'fresh materialization destination required')
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);path.chmod(mode)
    require(Capture().read(str(path),path.parent)[1]==raw,'copied source bytes differ')


def job_membership(job):
    """Complete ordinary file/directory population; never select by suffix."""
    job=Path(job);cap=Capture();cap.ordinary(job,directory=True);members=[]
    for p in sorted(job.rglob('*')):
        require(len(members)<MAX_FILES,'bounded whole materialized job membership required')
        directory=p.is_dir();cap.ordinary(p,directory=directory)
        members.append({'relative':p.relative_to(job).as_posix(),'kind':'directory' if directory else 'file'})
    cap.finish();return members


def inspect_job(plan,cap):
    """Complete bounded output census, with original source and registration checks."""
    out=Path(plan['output_root']);job=out/'job';cap.ordinary(job,directory=True)
    rows=[];total=0
    for p in sorted(job.rglob('*')):
        if p.is_symlink():raise ValueError('materialized job cannot contain links')
        if p.is_file():
            row=fact(p,cap);total+=row['size'];rows.append(row)
    require(len(rows)<=MAX_FILES and total<=plan['configuration']['resources']['max_output_bytes'],'bounded complete generated job required')
    a=job/'Build/SampleAnalyzer/User/Analyzer'
    for name in REQUIRED:
        require((a/name).is_file(),'missing generated SFS member: '+name)
        require(bool(cap.read(str(a/name),out)[1]),'empty generated SFS member: '+name)
    for key,suffix in [('source','.cpp'),('header','.h')]:
        p=a/(plan['analysis']+suffix);require(hashlib.sha256(cap.read(str(p),out)[1]).hexdigest()==plan['configuration']['assets'][key]['sha256'],'original analyzer changed during materialization')
    p=job/'Input'/(plan['analysis']+'.info');require(hashlib.sha256(cap.read(str(p),out)[1]).hexdigest()==plan['configuration']['assets']['info']['sha256'],'original analysis metadata changed')
    registration=cap.read(str(a/'analysisList.h'),out)[1].decode()
    require(re.findall(r'manager\.Add\(\s*"([^"]+)"\s*,\s*new\s+([A-Za-z_][A-Za-z0-9_]*)\s*\)',registration)==[(plan['analysis'],plan['analysis'])],'single exact source registration required')
    main=cap.read(str(job/'Build/Main/main.cpp'),out)[1].decode()
    require(re.findall(r'InitializeAnalyzer\(\s*"([^"]+)"\s*,\s*"([^"]+)"',main)==[(plan['analysis'],'analysis.saf')] and 'InitializeWriter' not in main,'one exact analyzer and analysis.saf output required')
    require('InitializeJetClusterer' in main and 'new NewSmearer()' in main and 'new NewTagger()' in main,'complete generated FastJet/SFS components required')
    for name in ('Makefile','setup.sh','setup.csh'):require((job/'Build'/name).is_file(),'complete upstream build files required')
    cap.finish();return rows


def verify_observation(actual,plan,source,mapping,cap):
    """Reconcile recorded writer metadata with the same captured source plan."""
    d=plan['configuration'];out=Path(plan['output_root']);prefix=out/'work/source'
    _keys(actual,('kind','pid','python','environment','request_sha256','card_program','imports','analysis','source_root','job_root','compiler_calls','event_calls','physics_validated'),'writer observation')
    require(actual['kind']=='ma5-sfs-writer-observation/v1' and actual['analysis']==d['analysis'] and actual['source_root']==str(prefix) and actual['job_root']==plan['job_root'] and actual['card_program']==plan['card_program'] and actual['environment']==plan['environment'] and actual['request_sha256']==hashlib.sha256(cap.files[out/'writer-request.json'][1]).hexdigest(),'actual writer identity/config observation differs')
    require(type(actual['pid']) is int and actual['pid']>0 and type(actual['compiler_calls']) is int and actual['compiler_calls']==0 and type(actual['event_calls']) is int and actual['event_calls']==0 and actual['physics_validated'] is False,'source-only writer scope required')
    require(actual['python']=={'path':plan['command'][0],'sha256':d['runtime']['python']['sha256']},'actual bound interpreter differs')
    imports=actual['imports'];require(type(imports) is list and imports,'actual writer source-import inventory required')
    names=set()
    for row in imports:
        _keys(row,('module','path','sha256'),'writer source import');q=Path(row['path']);require(type(row['module']) is str and q.is_relative_to(prefix) and row['module'] not in names,'unique staged source import required');names.add(row['module'])
        rel=q.relative_to(prefix).as_posix();require(rel in mapping and row['sha256']==hashlib.sha256(source.files[mapping[rel]][1]).hexdigest(),'imported writer source differs from declared source')


def run(task,base,out,*,worker_started=None):
    started=time.monotonic() if worker_started is None else worker_started;plan=build_plan(task,base,out);out=Path(out).absolute()
    require(out.is_dir() and not any(out.iterdir()),'fresh empty worker-owned materialization root required')
    d,cp,c,root,mapping,assets,program=_load(task,base);emitted=Capture();prefix=out/'work/source'
    for relative,p in mapping.items():_copy(prefix/relative,c.files[p][1],stat.S_IMODE(p.stat().st_mode))
    staged={}
    for key,p in assets.items():
        q=out/'work/assets'/p.name;_copy(q,c.files[p][1],0o644);staged[key]=str(q)
        require(emitted.read(str(q),out)[1]==c.files[p][1],'staged original asset differs before writer')
    for relative in ('home','tmp'):(out/'work'/relative).mkdir()
    _write(out/'build-plan.json',plan,emitted);_copy(out/'writer.py',HELPER.encode(),0o600)
    request={'source_root':str(prefix),'job_root':plan['job_root'],'analysis':d['analysis'],'architecture':d['architecture'],
             'assets':staged,'card_program':program,'environment':plan['environment'],'observation':str(out/'writer-observation.json')}
    _write(out/'writer-request.json',request,emitted)
    require(build_plan(task,base,out)==plan,'source/runtime changed before source writer')
    remaining=d['resources']['max_seconds']-(time.monotonic()-started);require(remaining>0,'materialization admission/copy exhausted work budget')
    native=out/'writer-execution';native.mkdir()
    from ravel.physics.reinterpret_db import execute_native
    observation=execute_native(plan['command'],native,{'max_seconds':remaining,'max_ram_mib':d['resources']['max_ram_mib']})
    require(observation.get('returncode')==0 and observation.get('resource_violation') is None,'successful supervised writer required')
    for key,p in assets.items():require(emitted.read(staged[key],out)[1]==c.files[p][1],'staged original asset changed during writer')
    _,b=emitted.read(str(out/'writer-observation.json'),out);actual=_json(b)
    verify_observation(actual,plan,c,mapping,emitted)
    for relative,p in mapping.items():require(emitted.read(str(prefix/relative),out)[1]==c.files[p][1],'staged writer source mutated')
    membership=job_membership(out/'job');inventory=inspect_job(plan,emitted)
    require(job_membership(out/'job')==membership,'generated job membership changed during capture')
    c.finish();require(build_plan(task,base,out)==plan,'original source/runtime ending drift')
    receipt={'schema_version':6,'kind':'ma5-sfs-materialization-receipt','status':'passed','plan_sha256':fact(out/'build-plan.json',emitted)['sha256'],
             'analysis':d['analysis'],'job_inventory':inventory,'job_membership':membership,'source_copy_inventory':[{'relative':relative,'copy':fact(prefix/relative,emitted)} for relative in mapping],
             'helper':fact(out/'writer.py',emitted),'writer_request':fact(out/'writer-request.json',emitted),'writer_observation':fact(out/'writer-observation.json',emitted),
             'execution_files':[fact(p,emitted) for p in sorted(native.iterdir()) if p.is_file()],'execution':observation,
             'phase':'materialized_source','compiled':False,'native_events_processed':0,'qualified_native_runtime':False,'physics_validated':False,
             'original_task_complete':False,'scope':plan['scope'],'next_requirements':['Separate source-bound compilation and loader receipt for generated job against complete matched ROOT/FastJet runtime','Existing ma5-pad supplied-event task with all original input/weight/output custody','Published 27 CR bins, tuned-response/tagger and full36-bin statistical qualification remain independent']}
    _write(out/'build-receipt.json',receipt,emitted);emitted.finish()
    total=sum(p.stat().st_size for p in out.rglob('*') if p.is_file());require(total<=d['resources']['max_output_bytes'],'successful retained materialization exceeds storage ceiling; preserve failed evidence')
    require(job_membership(out/'job')==membership,'ending generated job membership changed; retained receipt is failed evidence')
    return receipt


def verify_receipt(receipt,plan,base,out):
    c=Capture();out=Path(out).absolute();_,b=c.read(str(out/'build-receipt.json'),out);_,p=c.read(str(out/'build-plan.json'),out)
    require(receipt==_json(b) and plan==_json(p) and plan==build_plan(plan['task'],base,out),'exact source-bound materialization receipt/plan required')
    require(receipt.get('schema_version')==6 and receipt.get('kind')=='ma5-sfs-materialization-receipt' and receipt.get('status')=='passed' and receipt.get('phase')=='materialized_source' and receipt.get('compiled') is False and receipt.get('physics_validated') is False and receipt.get('qualified_native_runtime') is False and receipt.get('original_task_complete') is False and receipt.get('native_events_processed')==0,'materialization-only receipt required')
    require(receipt['plan_sha256']==hashlib.sha256(p).hexdigest() and receipt['job_inventory']==inspect_job(plan,c),'whole generated job differs')
    require(receipt.get('job_membership')==job_membership(out/'job'),'complete retained generated job membership differs')
    d,cp,original,root,mapping,assets,program=_load(plan['task'],base);prefix=out/'work/source'
    expected_copies=[]
    for relative,p in mapping.items():
        require(c.read(str(prefix/relative),out)[1]==original.files[p][1],'staged source copy differs from original input')
        expected_copies.append({'relative':relative,'copy':fact(prefix/relative,c)})
    require(receipt['source_copy_inventory']==expected_copies and receipt['helper']==fact(out/'writer.py',c) and c.files[out/'writer.py'][1]==HELPER.encode(),'complete staged source/helper custody differs')
    require(receipt['writer_request']==fact(out/'writer-request.json',c),'writer request bytes differ')
    expected_request={'source_root':str(prefix),'job_root':plan['job_root'],'analysis':d['analysis'],'architecture':d['architecture'],
                      'assets':{k:str(out/'work/assets'/p.name) for k,p in assets.items()},'card_program':program,'environment':plan['environment'],'observation':str(out/'writer-observation.json')}
    require(_json(c.files[out/'writer-request.json'][1])==expected_request,'writer request differs from exact planned source/materialization')
    for key,p in assets.items():require(c.read(expected_request['assets'][key],out)[1]==original.files[p][1],'staged original analysis/SFS asset changed')
    for row in receipt['execution_files']:require(row==fact(Path(row['path']),c) and Path(row['path']).parent==out/'writer-execution','complete writer execution evidence changed')
    require({r['path'] for r in receipt['execution_files']}=={str(p) for p in (out/'writer-execution').iterdir() if p.is_file()},'whole writer execution census differs')
    require(sum(p.stat().st_size for p in out.rglob('*') if p.is_file())<=d['resources']['max_output_bytes'],'retained successful materialization cap exceeded')
    original.finish()
    c.pin({k:receipt['writer_observation'][k] for k in ('path','sha256')},out)
    verify_observation(_json(c.files[out/'writer-observation.json'][1]),plan,original,mapping,c)
    _,execution=c.read(str(out/'writer-execution/native-execution.json'),out)
    require(_json(execution)==receipt['execution'] and receipt['execution']['command']==plan['command'] and receipt['execution']['returncode']==0 and receipt['execution']['resource_violation'] is None,'retained successful writer execution required')
    c.finish();return receipt


def write_report(result,out):
    p=Path(out)/'ma5-sfs-materialization.md'
    text='# Materialized MA5 SFS source\n\n'+result['analysis']+': '+result['phase']+'.\n\nThe complete generated source/header/Main/registration inventory is in build-receipt.json. No compiler, ABI/load, events, tuned detector or full SVJ likelihood is qualified.\n\n'+'\n'.join('- '+x for x in result['next_requirements'])+'\n'
    p.write_text(text);return [{'stem':'ma5-sfs-materialization','files':[p.name,'build-receipt.json','build-plan.json','writer-observation.json'],'normalization':'Source materialization only; no selected yield or calibration'}]
