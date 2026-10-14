"""One explicitly admitted retained-LHE observer qualification, never MPI inference.

Preparation reads and pins files only. Child commands are sequential, inherit the
scientific supervisor's process group, and retain partial files on every failure.
The sampled resource guard is not an instantaneous filesystem quota.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time

from ravel.workflow.state_io import atomic_json
from ravel.validation import diagnostic_plan as plans

# Whole-operation seconds kept outside native children for comparisons, custody and failure retention.
CUSTODY_RESERVE_SECONDS = 20
SCOPE = 'Original hard-event observer and downstream identity qualification only; no MPI effect, shape, normalization or likelihood acceptance'


def require(value,message):
    if not value:raise ValueError(message)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def filepin(path):
    path=Path(path);require(path.is_file() and not path.is_symlink(),'regular file required')
    return {'path':str(path.resolve()),'sha256':digest(path)}


def validate(task):
    require(isinstance(task,dict) and set(task)=={'input'} and isinstance(task['input'],str),'exact observer input required')


def document(task,base):
    from ravel.workflow.science import regular
    validate(task);p=regular(task['input'],base)
    d=json.loads(p.read_text())
    plan=plans.selected(d, ('equivalence','loader_stages','generated_files'))
    plans.fields(d,{'plan','schema_version','scope','source_inputs','runtime_inventory','environment','resources','stages','selection_contract','helper_sources','comparison_files','identity_reports','tagged_report','platform','assumptions'},'observer contract fields differ')
    require(d['schema_version']==1 and d['scope']==SCOPE,'observer schema/scope differs')
    r=d['resources']
    require(set(r)=={'max_seconds','workers','attempts','hard_events','original_events','selected_events','shower_passes','builds','detector_runs','conversions','analyses','retained_bytes','free_floor_bytes','headroom_bytes','inherited_bytes','lineage_ceiling_bytes','resource_root'},'resource fields differ')
    validate_resources(r)
    require(r['hard_events']==0,'retained-input observer cannot generate hard events')
    require(0<r['selected_events']<=r['original_events'],'complete supplied event population required')
    require(Path(r['resource_root']).is_absolute(),'absolute owned resource root required')
    require(isinstance(d['environment'],dict) and all(isinstance(k,str) and isinstance(v,str) for k,v in d['environment'].items()),'explicit environment required')
    for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','PYTHONDONTWRITEBYTECODE'):
        require(d['environment'].get(k)=='1','single-worker/thread environment required')
    require(d['environment'].get('DYLD_PRINT_LIBRARIES')=='1','actual native loader observation required')
    require(d['platform']==platform.platform(),'declared native platform changed')
    validate_stages(d['stages'],r['max_seconds'])
    ids={s['id'] for s in d['stages']}
    require(type(plan['loader_stages']) is list and set(plan['loader_stages'])<=ids,'declared loader stages required')
    for name in plan['generated_files']:relative(name)
    require(type(d['comparison_files']) is list and d['comparison_files'] and type(d['identity_reports']) is list and d['identity_reports'],'complete observer comparison and identity witnesses required')
    for pair in d['comparison_files']:
        require(isinstance(pair,list) and len(pair)==2,'observer equality pair required')
        for name in pair:relative(name)
    for name in [*d['identity_reports'],d['tagged_report']]:relative(name)
    properties=plan['equivalence']
    require(set(properties)=={'identity_status','tagged_status','events'},'supplied equivalence properties required')
    require(properties['events']==r['selected_events'],'equivalence population differs from planned selection')
    require(isinstance(d['assumptions'],list) and len(d['assumptions'])>=4,'scope and custody limits required')
    return p,d


def validate_resources(r):
    require(type(r) is dict,'resource envelope required')
    for key in ('max_seconds','workers','attempts','retained_bytes','free_floor_bytes','headroom_bytes','inherited_bytes','lineage_ceiling_bytes'):
        plans.positive(plans.required(r,key),'resources.'+key,integer=True,zero=key in ('inherited_bytes','free_floor_bytes'))
    require(r['max_seconds']>CUSTODY_RESERVE_SECONDS,'whole-operation deadline must exceed the custody reserve')
    require(r['workers']==r['attempts']==1,'sequential one-attempt qualification required')
    require(r['headroom_bytes']<r['retained_bytes'] and r['inherited_bytes']+r['retained_bytes']<=r['lineage_ceiling_bytes'],'consistent whole-lineage resource envelope required')
    for key in set(r)-{'resource_root','max_seconds','workers','attempts','retained_bytes','free_floor_bytes','headroom_bytes','inherited_bytes','lineage_ceiling_bytes'}:
        plans.positive(r[key],'resources.'+key,integer=True,zero=True)
    require(Path(r['resource_root']).is_absolute() and '..' not in Path(r['resource_root']).parts,'absolute owned resource root required')


def validate_stages(stages,max_seconds):
    require(type(stages) is list and stages,'supplied stage graph required')
    seen=set();outputs=set()
    for stage in stages:
        require(set(stage)=={'id','argv','outputs','max_seconds','depends_on'},'closed stage graph fields required')
        ident=stage['id'];relative(ident)
        require('/' not in ident and ident not in seen,'unique stage id required')
        require(type(stage['depends_on']) is list and set(stage['depends_on'])<=seen,'stage graph must be topologically ordered')
        require(type(stage['argv']) is list and stage['argv'] and all(type(x) is str and x for x in stage['argv']),'literal stage argv required')
        plans.positive(stage['max_seconds'],'stage.max_seconds',integer=True)
        require(stage['max_seconds']<=max_seconds,'stage ceiling exceeds whole operation')
        require(type(stage['outputs']) is list and stage['outputs'],'declared stage artifacts required')
        for name in stage['outputs']:
            relative(name);require(name not in outputs,'stage artifacts have multiple owners');outputs.add(name)
        seen.add(ident)
    require(sum(stage['max_seconds'] for stage in stages)<=max_seconds-CUSTODY_RESERVE_SECONDS,'reserve time for custody and comparisons')
    return stages


def relative(value):
    p=Path(value)
    require(isinstance(value,str) and not p.is_absolute() and p.parts and all(v not in ('.','..') for v in p.parts) and p.as_posix()==value,'canonical relative artifact required')
    return p


def inputs(task,base,*,_session=None):
    from ravel.workflow.science import regular
    p,d=document(task,base);paths=[p]
    for row in [*d['source_inputs'],d['runtime_inventory'],d['selection_contract'],*d['helper_sources']]:
        require(set(row)=={'path','sha256'},'exact source pin required')
        q=regular(row['path'],p.parent)
        observed=_session.hash_file(q) if _session is not None else digest(q)
        require(observed==row['sha256'],'observer input bytes differ: '+str(q));paths.append(q)
    inventory=json.loads(regular(d['runtime_inventory']['path'],p.parent).read_text())
    for alias in inventory.get('aliases',[]):
        require(set(alias)=={'path','resolved'} and Path(alias['path']).is_absolute()
            and str(Path(alias['path']).resolve(strict=True))==alias['resolved'],'runtime alias resolution changed')
    paths.extend(observer_runtime_files(inventory,_session=_session))
    return list(dict.fromkeys(paths))


def observer_runtime_files(inventory,*,_session=None):
    """Bind the supplied complete runtime in bounded chunks."""
    from ravel.validation.likelihood_parity import runtime_files
    rows=inventory.get('files')
    require(inventory.get('schema_version')==1 and isinstance(rows,list)
        and 1<=len(rows)<=100000,'bounded observer runtime inventory required')
    def census():
        for root,names in inventory.get('complete_python_tree_censuses',{}).items():
            p=Path(root)
            require(p.is_absolute() and p.is_dir() and isinstance(names,list),
                'absolute complete Python tree census required')
            observed=sorted(str(q.relative_to(p)) for q in p.rglob('*') if q.is_file())
            require(observed==names,'Python runtime tree population changed: '+root)
    census()
    paths=[]
    for start in range(0,len(rows),50000):
        paths.extend(runtime_files({'schema_version':1,'files':rows[start:start+50000]},_session=_session))
    require(len(set(paths))==len(paths),'observer runtime inventory repeats a file across chunks')
    census()
    return paths


def _validation_inputs(task,base,session):return inputs(task,base,_session=session)


def execution_seconds(task,base):return document(task,base)[1]['resources']['max_seconds']


def resource_bounds(task,base):
    r=document(task,base)[1]['resources']
    return {k:v for k,v in r.items() if k!='resource_root'}


def loader_census(out,stage_names,bound_files,*,generated_files,required_stages):
    """Observed loaded images, distinct from a claim of complete dynamic closure."""
    known={str(Path(p).resolve()) for p in bound_files}
    generated=[filepin(out/relative(name)) for name in generated_files]
    known.update(row['path'] for row in generated)
    observed=set();system=set();unknown=set();counts={}
    for name in stage_names:
        text=(out/'native-logs'/(name+'.log')).read_text(errors='replace')
        images=re.findall(r'^dyld\[\d+\]: <[0-9A-Fa-f-]+> (/[^\r\n]+)$',text,re.MULTILINE)
        counts[name]=len(images)
        if name in required_stages:
            require(images,'shower loader trace missing')
        for raw in images:
            if raw.startswith(('/usr/lib/','/System/Library/','/System/Volumes/Preboot/Cryptexes/')):
                system.add(raw);continue
            resolved=str(Path(raw).resolve())
            (observed if resolved in known else unknown).add(resolved)
    report={'observed_bound_images':sorted(observed),'system_platform_bound_images':sorted(system),
        'unbound_images':sorted(unknown),'stage_trace_counts':counts,'generated_images':generated,
        'limits':'Loader traces observe loaded images on these commands only; external data coverage is the declared byte inventory, and OS shared-cache images are platform-bound.'}
    atomic_json(out/'native-loader-census.json',report)
    require(not unknown,'actual native loader used unbound image; retained observation requires a new prospective contract')
    return report


def tree_usage(root):
    logical=allocated=0
    for folder,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            p=Path(folder)/name
            require(not p.is_symlink(),'resource tree contains symlink')
        for name in files:
            p=Path(folder)/name
            try:s=p.stat()
            except FileNotFoundError:continue
            logical+=s.st_size;allocated+=s.st_blocks*512
    return {'logical_bytes':logical,'allocated_bytes':allocated}


class Guard:
    def __init__(self,resources,log):self.r=resources;self.log=Path(log);self.maximum=0;self.samples=0
    def check(self,final=False):
        start=time.monotonic();root=Path(self.r['resource_root']);usage=tree_usage(root);free=shutil.disk_usage(root).free
        margin=0 if final else self.r['headroom_bytes'];elapsed=time.monotonic()-start
        row={'phase':'final' if final else 'running','monotonic':start,'usage':usage,'free_bytes':free,'scan_seconds':elapsed,'sampled_not_quota':True}
        with self.log.open('a') as f:f.write(json.dumps(row)+'\n')
        self.samples+=1;self.maximum=max(self.maximum,usage['logical_bytes'])
        require(elapsed<=1.,'resource scan exceeded one-second bound')
        require(free>=self.r['free_floor_bytes']+margin,'minimum free disk floor reached')
        require(usage['logical_bytes']<=self.r['retained_bytes']-margin,'new observer retention ceiling reached')
        require(self.r['inherited_bytes']+usage['logical_bytes']<=self.r['lineage_ceiling_bytes']-margin,'inherited retention ceiling reached')
        if final:
            # Include the telemetry commit itself. Later common supervisor
            # receipts use the headroom reserved throughout native execution.
            post=tree_usage(root)
            require(post['logical_bytes']<=self.r['retained_bytes'] and
                self.r['inherited_bytes']+post['logical_bytes']<=self.r['lineage_ceiling_bytes'],
                'retention ceiling exceeded after final telemetry commit')
            require(shutil.disk_usage(root).free>=self.r['free_floor_bytes'],
                'free disk floor exceeded after final telemetry commit')
            require(time.monotonic()-start<=1.,'final resource scan exceeded one-second bound')
        return row


def child(stage,out,environment,deadline,guard):
    argv=[v.replace('{OUTPUT}',str(out)) for v in stage['argv']]
    require(all('{' not in v and '}' not in v for v in argv),'unknown command substitution')
    expected=[out/relative(p) for p in stage['outputs']]
    for p in expected:
        require(not p.exists() and not p.is_symlink(),'stage output already exists')
        p.parent.mkdir(parents=True,exist_ok=True)
    log=out/'native-logs'/(stage['id']+'.log');receipt=out/'native-logs'/(stage['id']+'.command.json')
    record={'argv':argv,'cwd':str(out),'environment':environment,'expected_returncode':0,'max_seconds':stage['max_seconds'],'outputs':[str(p) for p in expected]}
    atomic_json(receipt,record);guard.check();start=time.monotonic();process=None
    try:
        require(start<deadline,'campaign deadline exhausted before launch')
        with log.open('xb') as stream:
            process=subprocess.Popen(argv,cwd=out,env=environment,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
            record['pid']=process.pid;atomic_json(receipt,record)
            while process.poll() is None:
                guard.check()
                require(time.monotonic()<min(deadline,start+stage['max_seconds']),'native child deadline exceeded')
                time.sleep(.25)
            require(process.returncode==0,'native command failed')
        guard.check()
        record.update(actual_returncode=process.returncode,elapsed_seconds=time.monotonic()-start,artifacts=[filepin(p) for p in expected],status='completed')
        atomic_json(receipt,record)
    except BaseException as exc:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        record.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)},actual_returncode=None if process is None else process.poll(),elapsed_seconds=time.monotonic()-start,cleanup_scope='Direct child only; scientific supervisor must census/clean the inherited process group')
        atomic_json(receipt,record);raise
    return record


def run(task,base,output_dir):
    started=time.monotonic();out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    require(not any(out.iterdir()),'fresh empty observer output required')
    p,d=document(task,base);r=d['resources'];resource_root=Path(r['resource_root']).resolve()
    require(out.is_relative_to(resource_root),'observer output outside its measured resource root')
    (out/'native-logs').mkdir();guard=Guard(r,out/'resource-telemetry.jsonl');records=[];result={'status':'failed','physics_validated':False,'scope':SCOPE,'native_commands':records,'successful_end_custody':False}
    try:
        before={str(q):digest(q) for q in inputs(task,base)}
        guard.check();deadline=started+r['max_seconds']-CUSTODY_RESERVE_SECONDS
        for s in d['stages']:
            records.append(child(s,out,d['environment'],deadline,guard))
        pairs=[]
        for a,b in d['comparison_files']:
            left,right=filepin(out/a),filepin(out/b)
            require(left['sha256']==right['sha256'] and (out/a).stat().st_size==(out/b).stat().st_size,'observer changed full event bytes')
            pairs.append({'disabled':left,'enabled':right,'byte_equal':True})
        atomic_json(out/'observer-byte-equality.json',pairs)
        reports=[]
        for name in d['identity_reports']:
            q=out/name;v=json.loads(q.read_text());require(v['status']==d['plan']['equivalence']['identity_status'] and v['events']==d['plan']['equivalence']['events'],'complete original transport not established');reports.append(filepin(q))
        tagged=json.loads((out/d['tagged_report']).read_text());require(tagged['status']==d['plan']['equivalence']['tagged_status'] and tagged['events']==d['plan']['equivalence']['events'],'literal non-ordinal transport not established')
        result['tagged_identity_report']=filepin(out/d['tagged_report'])
        result['native_loader_census']=loader_census(out,[s['id'] for s in d['stages']],before,generated_files=d['plan']['generated_files'],required_stages=d['plan']['loader_stages'])
        require(before=={str(q):digest(q) for q in inputs(task,base)},'observer source/runtime changed during calculation')
        require(time.monotonic()<started+r['max_seconds'],'observed campaign total deadline exceeded')
        result.update(status='passed',identity_reports=reports,successful_end_custody=True,input_pins=[{'path':k,'sha256':v} for k,v in before.items()])
    except Exception as exc:result['error']={'type':type(exc).__name__,'message':str(exc)}
    # Include the actual failed command too. A planned command is never an
    # executed command; its retained receipt is the evidence of launch/exit.
    result['native_commands']=[json.loads(q.read_text()) for s in d['stages']
        if (q:=out/'native-logs'/(s['id']+'.command.json')).is_file()]
    result.update(elapsed_seconds=time.monotonic()-started,resource_scope='Whole bound preparation/run subtree plus declared inherited bytes; sampled guard, no instantaneous OS quota',limits=['Only the supplied population qualifies this interface; each new population requires complete content and transport evidence.','Observer qualification is conditional on the explicitly declared current native runtime; original historical runtime equivalence is not established.','No automatic retry, extension, new hard-event generation, fit or MPI-effect inference.'])
    plans.publish(out,d['plan'],result)
    try:guard.check(final=True)
    except Exception as exc:
        result.update(status='failed',postcondition_error={'type':type(exc).__name__,'message':str(exc)});plans.publish(out,d['plan'],result)
    return result
