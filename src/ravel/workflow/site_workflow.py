"""Source-bound Snakemake export over existing ordinary RAVEL run authority.

No planner, scheduler, approval, credential transport, model gateway or automatic
resume is introduced. Export is preparation; run-step explicitly dispatches the
existing supervised ordinary/campaign route and records delivery, not acceptance.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shlex
from ravel.physics import root_stream, root_stream_core as core, dataset_query_quantities


RESERVED_TASK_IDS=frozenset({'all','ravel_verify_export','rule','checkpoint','include','workflow','module','use','onstart','onsuccess',
    'onerror','localrules','ruleorder','configfile','pepfile','pepschema','envvars','container','containerized','report','singularity',
    'wildcard_constraints','scattergather','inputflags','outputflags','subworkflow','storage','resource_scopes','conda','global_workflow'})


def _pin(path):
    path=Path(path).absolute()
    return {'path':str(path),'sha256':dataset_query_quantities.custody._hash(path),'size':path.stat().st_size}


LEGACY_WMS={'engine':'snakemake','version':'9.27.0','cores':1,'retries':0}
PROFILES=('local','htcondor','slurm')


def wms_profile(wms):
    """Fan-out view of a WMS block; the legacy block is local, one core, one job."""
    if 'profile' not in wms:return {'profile':'local','cores':1,'jobs':1,'remote_ceiling':1}
    return {k:wms[k] for k in ('profile','cores','jobs','remote_ceiling')}


def host_slots():
    """Slots the machine lease admits on this host; one until a host declares more.

    Seam for the host-scoped lease (machine_lease.slots(); always one on macOS).
    """
    from . import machine_lease
    slots=getattr(machine_lease,'slots',None)
    value=slots() if slots is not None else 1
    if type(value) is dict:value=value.get('count',value.get('slots'))
    return value if type(value) is int and value>=1 else 1


def validate_wms(wms):
    """Bounded workflow-manager profile; Snakemake retries stay 0.

    A Snakemake retry would re-run a spent run-step. A failed partition is retried
    by RAVEL as a fresh attempt run dir (`ravel wms retry`), bounded by the master.
    """
    core.require(type(wms) is dict and wms.get('engine')=='snakemake' and wms.get('version')=='9.27.0','pinned Snakemake 9.27.0 WMS required')
    core.require(wms.get('retries')==0,'Snakemake retries must be 0: a retry would re-run a spent run-step; '
        'retry a failed partition with `ravel wms retry --task <id>` (a fresh attempt within the approved max_attempts)')
    if wms==LEGACY_WMS:return deepcopy(wms)
    core.keys(wms,('engine','version','profile','cores','jobs','remote_ceiling','retries'),'bounded WMS profile')
    core.require(wms['profile'] in PROFILES,'WMS profile must be one of '+'|'.join(PROFILES))
    for name in ('cores','jobs','remote_ceiling'):core.integer(wms[name],1,1024,'WMS '+name)
    if wms['profile']=='local':
        slots=host_slots()
        core.require(wms['cores']<=slots,f'local cores {wms["cores"]} exceed the {slots} slot(s) the machine lease admits on this host '
            '(one native scientific job at a time unless the host declares more); use a remote profile or cores 1')
        core.require(wms['jobs']<=wms['cores'],'local jobs cannot exceed cores')
    else:
        from .execution_backend import remote_ceiling
        owner=remote_ceiling()
        core.require(wms['jobs']<=wms['remote_ceiling']<=owner,f'remote jobs must fit the declared remote ceiling, which must fit the owner-set ceiling {owner} (RAVEL_REMOTE_JOB_CEILING)')
    return deepcopy(wms)


def validate(request):
    core.keys(request,('schema_version','site_id','python','tasks','audit','wms')+(('fanin',) if type(request) is dict and 'fanin' in request else ()),'site workflow request')
    core.require(type(request['schema_version']) is int and request['schema_version']==1,'site export schema1 required')
    core.text(request['site_id']);core.pin(request['python'])
    validate_wms(request['wms'])
    audit=request['audit'];core.keys(audit,('prompts','model_build','timestamps','token_accounting','environment','tracked_skill_sources','blinding_policy'),'submission records')
    core.text(audit['model_build']);core.require(type(audit['timestamps']) is list and audit['timestamps'],'exact timestamp records required')
    for timestamp in audit['timestamps']:
        from datetime import datetime
        core.require(type(timestamp) is str and datetime.fromisoformat(timestamp.replace('Z','+00:00')).tzinfo is not None,'timezone-aware original timestamp required')
    for name in ('prompts','tracked_skill_sources'):
        core.require(type(audit[name]) is list and audit[name],'complete original source records required')
        for row in audit[name]:core.pin(row)
    for name in ('token_accounting','environment','blinding_policy'):core.pin(audit[name])
    core.require(type(request['tasks']) is list and 1<=len(request['tasks'])<=10000,'bounded complete tasks required')
    import re
    seen=set()
    for task in request['tasks']:
        core.keys(task,('id','rundir','plan','owner','depends_on')+(('after',) if 'after' in task else ()),'prepared ordinary task')
        core.require(type(task['id']) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',task['id']) and task['id'] not in seen,'distinct literal task id required')
        core.require(task['id'] not in RESERVED_TASK_IDS,'task id '+task['id']+' is a reserved Snakemake rule or keyword name')
        core.text(task['rundir']);core.pin(task['plan'])
        core.require(type(task['depends_on']) is list and len(set(task['depends_on']))==len(task['depends_on']) and set(task['depends_on'])<=seen,'dependencies must be earlier complete task identities')
        # Optional dependencies on tasks of earlier one-task exports (project workflows).
        after=task.get('after',[]);core.require(type(after) is list and len(after)<=10000,'bounded earlier export dependencies required')
        for row in after:
            core.keys(row,('task','export','export_sha256'),'earlier export dependency');core.text(row['export'])
            core.require(type(row['task']) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',row['task']) and type(row['export_sha256']) is str and re.fullmatch('[a-f0-9]{64}',row['export_sha256']),'literal earlier export dependency required')
        core.require(len({(r['task'],r['export']) for r in after})==len(after),'distinct earlier export dependencies required')
        owner=task['owner'];core.require(type(owner) is dict,'actual ordinary owner required')
        if owner.get('kind')=='research_cycle':
            core.keys(owner,('kind','cycle','experiment'),'campaign owner');core.text(owner['cycle']);core.text(owner['experiment'])
        else:core.require(owner=={'kind':'ordinary'},'explicit standalone or actual research-cycle owner required')
        seen.add(task['id'])
    fanin=request.get('fanin',[]);core.require(type(fanin) is list and len(fanin)<=100,'bounded partition merge rules required')
    for row in fanin:
        core.keys(row,('id','master','output'),'partition merge rule');core.pin(row['master']);core.text(row['output'])
        core.require(type(row['id']) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',row['id']) and row['id'] not in seen and
            row['id'] not in RESERVED_TASK_IDS,'distinct literal merge rule id required');seen.add(row['id'])
    return deepcopy(request)


def _path(value,base,directory=False):return dataset_query_quantities._ordinary(value,base,directory=directory)


def _interpreter(cap,declaration,base):
    """Snapshot the interpreter that runs the exported steps; return its declared name.

    A virtual environment names its interpreter through a symbolic link and is
    selected by that name. The pinned bytes are therefore read at the canonical
    file, and the generated commands keep the declared name. This holds for the
    interpreter alone: every declared source still refuses a symbolic link.
    """
    core.pin(declaration);named=Path(declaration['path']);named=(named if named.is_absolute() else Path(base)/named).absolute()
    target,_=cap.read({**declaration,'path':os.path.realpath(named)},base,64*1024**2)
    core.require(os.access(target,os.X_OK),'explicit analysis interpreter required')
    return {**declaration,'path':str(named)}


def _approved_environment(plan):
    """Values of the plan's pinned runtime keys, taken from this approved shell.

    The plan pins only their digest. Snakemake sets OMP/GOTO/OPENBLAS/MKL/VECLIB/
    NUMEXPR thread variables for every shell job (snakemake/shell.py:278-286 in
    9.27.0), so verify and run-step restore these values before checking the plan.
    """
    from . import execution
    binding=plan.get('stage_binding') if type(plan) is dict else None
    if type(binding) is not dict or 'environment_sha256' not in binding.get('runtime',{}):return {}
    environment=execution.runtime_environment()
    core.require(execution.digest(environment)==binding['runtime']['environment_sha256'],
        'export the run from a shell with its approved runtime environment ('+', '.join(execution.RUNTIME_ENVIRONMENT_KEYS)+')')
    return {'runtime_environment':environment}


def _restore_environment(path,expected_sha256,identity=None):
    """Before verify/run-step in a WMS job: restore approved runtime values of a digest-matched export."""
    from . import execution
    raw=Path(path).read_bytes();core.require(hashlib.sha256(raw).hexdigest()==expected_sha256,'original export digest differs')
    for task in json.loads(raw)['tasks']:
        if identity is not None and task['id']!=identity:continue
        environment=task.get('runtime_environment')
        if environment is None:continue
        core.require(type(environment) is dict and set(environment)==set(execution.RUNTIME_ENVIRONMENT_KEYS),'closed approved runtime environment required')
        for key,value in environment.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
        return


def _source_assets():
    root=Path(__file__).parents[2]
    census=root_stream.census(root)
    # Complete source membership, including installed operational/data assets.
    return root,census


def _partition_task(spec,rd,cap,wms,partition_tasks,masters):
    """Duplicate-dispatch refusal and the approved fan-out check for a partition/merge branch."""
    from ravel.physics import root_stream_partitions as partitions
    selected=partitions.dispatch_master(spec['task'],rd,cap)
    if selected is None:return
    master,task_id=selected
    identity=(master['owner']['cycle'],partitions.reservation_id(master),task_id)
    core.require(identity not in partition_tasks,'duplicate original master partition/merge dispatch refused');partition_tasks.add(identity)
    core.require(partitions.master_fanout(master)['wms']==wms_profile(wms),'WMS profile differs from the fan-out approved at CHECK-IN 1 '
        '(profile, cores, jobs and remote ceiling are pinned in the partition master); prepare and approve a new plan')
    masters.setdefault(master['master_pin']['sha256'],set()).add(task_id)


def _prepare(request,base):
    """Read-only preparation on actual selected plans; never grant approval."""
    from . import science,research_cycle
    request=validate(request);cap=core.Capture();python=_interpreter(cap,request['python'],base)
    audit=request['audit']
    for row in [*audit['prompts'],*audit['tracked_skill_sources'],audit['token_accounting'],audit['environment']]:cap.read(row,base)
    blind=cap.document(audit['blinding_policy'],base)
    core.keys(blind,('schema_version','policy','review_source','original_domain'),'submission blinding policy')
    core.require(type(blind['schema_version']) is int and blind['schema_version']==1 and blind['policy']=='exclude_signal_region_data_from_model_and_analysis','original explicit submission blinding policy required')
    cap.read(blind['review_source'],base)
    if blind['original_domain'] is not None:cap.read(blind['original_domain'],base)
    tasks=[];cycles={};rundirs=set();partition_tasks=set();masters={};owners={}
    for row in request['tasks']:
        rd=_path(row['rundir'],base,True);core.require(rd not in rundirs,'one original run may not be dispatched twice');rundirs.add(rd)
        p,_=cap.read(row['plan'],base);core.require(p==rd/science.PLAN,'actual canonical prepared plan required')
        plan,spec,destination=root_stream.ordinary_plan_destination(rd)
        if spec['mode']=='root-stream':
            before={k:set(v) for k,v in masters.items()}
            _partition_task(spec,rd,cap,request['wms'],partition_tasks,masters)
            for key,ids in masters.items():
                for task_id in ids-before.get(key,set()):owners.setdefault(key,{})[task_id]=row['id']
            _,_,_,analysis=root_stream._load(spec['task'],rd,cap)
            if analysis['blinding'] is not None:
                original=blind['original_domain'];core.require(original is not None and
                    original['sha256']==analysis['blinding']['source']['sha256'] and original['size']==analysis['blinding']['source']['size'],
                    'adaptive exported root tasks cannot replace or widen original accepted blind-domain policy')
        owner=deepcopy(row['owner'])
        if owner['kind']=='research_cycle':
            cycle=_path(owner['cycle'],base,True);_,state=research_cycle._load(cycle)
            e=next((x for x in state['experiments'] if x['id']==owner['experiment']),None)
            core.require(e is not None and e['rundir']==str(rd) and e['plan']==_pin(p),'actual campaign experiment/plan binding required')
            owner['cycle']=str(cycle)
            # Fixed context/contract identity; later actual journal revisions remain
            # governed by run_experiment, not frozen/renewed by this exporter.
            cycles[str(cycle)]={'context_request_sha256':state['context']['request_sha256'],'contract':deepcopy(state['contract'])}
            if e['parent'] is not None:
                parents=[x for x in tasks if x['owner'].get('cycle')==str(cycle) and x['owner'].get('experiment')==e['parent']]
                if parents:core.require(parents[0]['id'] in row['depends_on'],'export DAG cannot omit a staged actual parent')
        for dep in row.get('after',[]):
            core.require(any(t['id']==dep['task'] for t in verify(dep['export'],dep['export_sha256'])['tasks']),'earlier export dependency names no exported task')
        # Exact original stage source and inputs are already checked by verify_plan.
        tasks.append({**deepcopy(row),'rundir':str(rd),'plan':_pin(p),'owner':owner,'mode':spec['mode'],
                      'output_directory':destination,**_approved_environment(plan)})
    fanin=[]
    for row in request.get('fanin',[]):
        from ravel.physics import root_stream_partitions as partitions
        m=partitions.read_master(row['master'],base,cap);ids=owners.get(row['master']['sha256'],{})
        missing=[x['id'] for x in m['partitions'] if x['id'] not in ids]
        core.require(not missing,'merge rule needs every partition of its master in this workflow; missing: '+', '.join(missing))
        out=Path(row['output']);out=out if out.is_absolute() else Path(base)/out
        core.require(not out.exists(),'fresh merge draft directory required');_path(out.parent,base,True)
        fanin.append({'id':row['id'],'master':deepcopy(row['master']),'output':str(out),
                      'depends_on':[ids[x['id']] for x in m['partitions']],
                      'partition_tasks':{ids[x['id']]:x['id'] for x in m['partitions']}})
    cap.finish();source_root,source_census=_source_assets()
    return {**({'fanin':fanin} if fanin else {}),'schema_version':1,'kind':'site-workflow-export','site_id':request['site_id'],'python':python,
            'tasks':tasks,'audit':deepcopy(audit),'audit_input_pins':list(cap.rows.values()),'cycles':cycles,
            'source_root':str(source_root),'source_census':source_census,'wms':request['wms'],
            'original_blind_domain_sha256':None if blind['original_domain'] is None else blind['original_domain']['sha256'],
            'execution_authorized':False,'scientific_acceptance_inferred':False,
            'limitations':['Credentials are runtime policy references and are never copied into this packet.',
                'Exports bind current paths and source; moving to a site requires ordinary re-preparation, not plan relocation.',
                'Snakemake retries and resume are disabled; a failed partition is retried by RAVEL as a fresh attempt run dir within its approved bound.',
                'Prompt/model/token/environment records preserve supplied source identity; their scientific completeness needs independent review.']}


def _escaped(argv):return shlex.join(argv).replace('{','{{').replace('}','}}')


def _prefix(manifest_path,base):
    prefix=os.path.relpath(Path(manifest_path).absolute().parent,Path(base).absolute())
    return '' if prefix=='.' else prefix+'/'


def verify_rule(manifest_path,document,base,name='ravel_verify_export'):
    """The integrity gate rule; every task rule of the export takes its output as input."""
    expected=hashlib.sha256(root_stream.encoded(document)).hexdigest();python=document['python']['path']
    gate=_prefix(manifest_path,base)+'completed/.export-verified-'+expected[:12]+'.json'
    verify=_escaped([python,'-I','-B','-m','ravel.workflow.site_workflow','verify','--export',str(manifest_path),'--export-sha256',expected])
    marker=json.dumps({'export_sha256':expected,'verified':True},sort_keys=True).replace('{','{{').replace('}','}}')
    return gate,['','rule '+name+':','    output: '+repr(gate),'    threads: 1','    retries: 0',
        '    shell: '+repr(verify+' > /dev/null && printf \'%s\\n\' '+shlex.quote(marker)+' > {output:q}')]


def task_rule(task,manifest_path,document,base,gate):
    """One run-step rule, with paths relative to the Snakemake working directory base.

    Inputs are the export gate, markers of same-export dependencies and markers of
    earlier one-task exports named in the optional after rows.
    """
    expected=hashlib.sha256(root_stream.encoded(document)).hexdigest();python=document['python']['path'];prefix=_prefix(manifest_path,base)
    deps=[gate]+[prefix+'completed/'+x+'.json' for x in task['depends_on']]
    deps+=[_prefix(row['export'],base)+'completed/'+row['task']+'.json' for row in task.get('after',[])]
    command=_escaped([python,'-I','-B','-m','ravel.workflow.site_workflow','run-step','--export',str(manifest_path),'--task',task['id'],'--export-sha256',expected])
    # Literal braces must escape Snakemake's formatter; no arbitrary shell.
    return ['','rule task_'+task['id']+':','    input: '+repr(deps),
        '    output: '+repr(prefix+'completed/'+task['id']+'.json'),'    threads: 1','    retries: 0','    shell: '+repr(command)]



def fanin_rule(row,manifest_path,document,base,gate):
    """One partition merge rule after every partition rule of its master.

    Inputs are partition delivery records: an approved retry satisfies the same output.
    """
    expected=hashlib.sha256(root_stream.encoded(document)).hexdigest();python=document['python']['path'];prefix=_prefix(manifest_path,base)
    deps=[gate]+[prefix+'completed/'+x+'.json' for x in row['depends_on']]
    command=_escaped([python,'-I','-B','-m','ravel.workflow.site_workflow','fanin','--export',str(manifest_path),'--task',row['id'],'--export-sha256',expected])
    return ['','rule fanin_'+row['id']+':','    input: '+repr(deps),
        '    output: '+repr(prefix+'completed/'+row['id']+'.json'),'    threads: 1','    retries: 0','    localrule: True','    shell: '+repr(command)]

def _snakefile(manifest_path,document):
    """Every executable token is generated/quoted from the closed actual schema.

    No top-level Python runs at parse time: integrity is the explicit rule
    ravel_verify_export, which every task rule takes as input. run_step re-verifies too.
    """
    base=Path(manifest_path).absolute().parent
    lines=['# Generated reproducibility wrapper; ordinary RAVEL retains all authority.','rule all:','    input:']
    for task in [*document['tasks'],*document.get('fanin',[])]:lines.append('        '+repr('completed/'+task['id']+'.json')+',')
    gate,rule=verify_rule(manifest_path,document,base);lines.extend(rule)
    for task in document['tasks']:lines.extend(task_rule(task,manifest_path,document,base,gate))
    for row in document.get('fanin',[]):lines.extend(fanin_rule(row,manifest_path,document,base,gate))
    return ('\n'.join(lines)+'\n').encode()


def project_rule(manifest_path,document,base):
    """Rules for a one-task export included by a project workflow; no rule all."""
    core.require(len(document['tasks'])==1,'project rule requires a one-task export')
    task=document['tasks'][0]
    gate,lines=verify_rule(manifest_path,document,base,'ravel_verify_'+task['id'])
    lines=['# Owned by ravel wms add; ordinary RAVEL retains all authority.',*lines[1:],*task_rule(task,manifest_path,document,base,gate)]
    return ('\n'.join(lines)+'\n').encode()


def export(request,base,output):
    value=_prepare(request,base);out=Path(output).absolute()
    core.require(not out.exists(),'fresh source export required');_path(out.parent,base,True);out.mkdir();(out/'completed').mkdir()
    pin=root_stream.write_new(out/'workflow.json',value)
    raw=_snakefile(out/'workflow.json',value);p=out/'Snakefile'
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    sf={'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    closure=root_stream.write_new(out/'export-closure.json',{'schema_version':1,'files':[pin,sf]})
    # Ending checks use original intended bytes, not newly adopted callback pins.
    dataset_query_quantities.asset_check({r['path']:r for r in [pin,sf,closure]});verify(out/'workflow.json',pin['sha256'])
    return {'manifest':pin,'closure':closure,'wms_argv':wms_argv(value['wms'],p,out),'wms_profile':wms_profile(value['wms']),
            'execution_authorized':False,'scientific_acceptance_inferred':False}


def wms_argv(wms,snakefile,directory):
    """Snakemake argv for the approved profile; remote profiles add their executor."""
    view=wms_profile(wms)
    argv=['snakemake','--snakefile',str(snakefile),'--directory',str(directory),'--cores',str(view['cores']),
          '--jobs',str(view['jobs']),'--retries','0']
    if view['profile']!='local':
        from .site_profiles import render
        executor=render(view['profile'],cores=view['cores'])['config']['executor']
        argv+=['--executor',executor]
    return argv


def verify(path,expected_sha256):
    path=Path(path).absolute();out=path.parent;cap=core.Capture()
    core.require(path.name=='workflow.json','canonical export path required')
    closure=cap.document(_pin(out/'export-closure.json'),out)
    core.keys(closure,('schema_version','files'),'export closure');core.require(closure['schema_version']==1 and len(closure['files'])==2,'complete source export closure required')
    core.require([r['path'] for r in closure['files']]==[str(path),str(out/'Snakefile')],'nonreplaceable export file roster required')
    core.require(closure['files'][0]['sha256']==expected_sha256,'original export digest differs')
    doc=cap.document(closure['files'][0],out);_,snake=cap.read(closure['files'][1],out)
    core.require(snake==_snakefile(path,doc),'workflow executable differs from original typed tasks')
    core.require(_interpreter(cap,doc['python'],out)==doc['python'],'exported interpreter name must be absolute')
    for p in doc['audit_input_pins']:cap.read(p,out,64*1024**2)
    core.require(root_stream.census(Path(doc['source_root']))==doc['source_census'],'complete original source epoch differs')
    from . import science,research_cycle
    partition_tasks=set();masters={}
    for task in doc['tasks']:
        rd=Path(task['rundir']);cap.read(task['plan'],out)
        plan,spec,destination=root_stream.ordinary_plan_destination(rd)
        core.require(destination==task['output_directory'] and spec['mode']==task['mode'],'actual selected stage destination/mode differs')
        if spec['mode']=='root-stream':
            _partition_task(spec,rd,cap,doc['wms'],partition_tasks,masters)
            _,_,_,analysis=root_stream._load(spec['task'],rd,cap)
            if analysis['blinding'] is not None:core.require(analysis['blinding']['source']['sha256']==doc['original_blind_domain_sha256'],
                'original exported blind-domain policy cannot change across adaptive tasks')
    for cycle,binding in doc['cycles'].items():
        _,state=research_cycle._load(cycle)
        core.require({'context_request_sha256':state['context']['request_sha256'],'contract':state['contract']}==binding,'original campaign question/contract differs')
    delivered=[];selections={}
    for task in doc['tasks']:
        marker=out/'completed'/(task['id']+'.json')
        if marker.exists():
            if _partition_binding(doc,task['id']) is not None:
                _verify_partition_delivery(path,doc,task['id'],expected_sha256,selections)
                continue
            value=cap.document(_pin(marker),out);core.keys(value,('schema_version','task','export_sha256','status','outputs','scientific_acceptance_inferred'),'completion marker')
            folder=Path(task['rundir'])/task['output_directory']
            core.require(value['schema_version']==1 and value['task']==task['id'] and value['export_sha256']==expected_sha256 and value['status']=='delivered' and value['scientific_acceptance_inferred'] is False and [r['path'] for r in value['outputs']]==[str(folder/'result.json'),str(folder/'verification.json')],'original complete completion marker required')
            receipt=root_stream.ordinary_delivery(task['rundir'],expected_output=folder)
            core.require(value['outputs']==receipt['outputs'],'marker is not the original succeeded ordinary delivery')
            delivered.append((task['rundir'],folder,receipt))
            result=core.strict(cap.read(value['outputs'][0],out,max(8*1024**2,value['outputs'][0]['size']))[1]);view=cap.document(value['outputs'][1],out)
            core.require(result.get('status')=='passed' and result.get('physics_validated') is False and view.get('passed') is True and view.get('physics_validated') is False,'retained ordinary delivery required')
    for row in doc.get('fanin',[]):
        marker=out/'completed'/(row['id']+'.json')
        if marker.exists():
            value=cap.document(_pin(marker),out)
            core.require(value.get('task')==row['id'] and value.get('export_sha256')==expected_sha256 and
                value.get('status')=='merge-draft-written' and value.get('execution_authorized') is False,'original merge rule marker required')
    cap.finish();core.require(root_stream.census(Path(doc['source_root']))==doc['source_census'],'ending complete original source differs')
    for rd,folder,receipt in delivered:
        core.require(root_stream.ordinary_delivery(rd,expected_output=folder)==receipt,'ending original WMS delivery differs')
    cap.finish()
    dataset_query_quantities.asset_check({r['path']:r for r in closure['files']})
    return doc


def _dispatch_record(out,identity,export_sha256,rundir):
    """Record how this step was dispatched; delivery evidence only, never acceptance.

    Snakemake runs the step in its working directory and holds .snakemake/locks
    there during a real (non-dry) run. An absent lock exposes a hand-run step.
    """
    from datetime import datetime,timezone
    from .env_snapshot import capture_runtime
    locks=Path.cwd()/'.snakemake'/'locks'
    folder=out/'dispatch';folder.mkdir(exist_ok=True)
    value={'schema_version':1,'task':identity,'export_sha256':export_sha256,'utc':datetime.now(timezone.utc).isoformat(),
           'cwd':str(Path.cwd()),'snakemake_locks_present':locks.is_dir() and any(locks.iterdir()),
           'runtime_snapshot':capture_runtime(rundir,identity),'scientific_acceptance_inferred':False}
    return root_stream.write_new(folder/(f'{len(list(folder.glob("*.json")))+1:06d}.json'),value)


def run_step(path,identity,expected_sha256):
    """Explicit execution entry called by the required WMS, never by export."""
    from . import science,research_cycle
    doc=verify(path,expected_sha256);out=Path(path).absolute().parent
    task=next((t for t in doc['tasks'] if t['id']==identity),None);core.require(task is not None,'actual exported task required')
    marker=out/'completed'/ (identity+'.json');core.require(not marker.exists(),'spent WMS step cannot silently resume')
    selected=_selected_delivery(path,doc,task)
    if selected is not None:
        # An approved attempt delivered this partition, the original or a later one: this rule
        # publishes that delivery and dispatches nothing. Publication runs no stage, so it needs
        # no launch admission; a governed run is still dispatched only through its indexed export.
        return publish_partition_delivery(path,identity,expected_sha256,selected['rundir'])
    cap=core.Capture();selections={}
    def passed(value,dep_out):
        result=core.strict(cap.read(value['outputs'][0],dep_out,max(8*1024**2,value['outputs'][0]['size']))[1])
        view=cap.document(value['outputs'][1],dep_out)
        core.require(result.get('status')=='passed' and result.get('physics_validated') is False and view.get('passed') is True and view.get('physics_validated') is False,'actual predecessor delivery required')
    def delivered(dep,prior,dep_out,dep_sha256):
        value=cap.document(_pin(dep_out/'completed'/(dep+'.json')),dep_out)
        core.require(value['task']==dep and value['export_sha256']==dep_sha256 and value['status']=='delivered','exact delivered dependency required')
        folder=Path(prior['rundir'])/prior['output_directory']
        core.keys(value,('schema_version','task','export_sha256','status','outputs','scientific_acceptance_inferred'),'original completion marker')
        core.require(value['scientific_acceptance_inferred'] is False and [p['path'] for p in value['outputs']]==[str(folder/'result.json'),str(folder/'verification.json')],'canonical full ordinary output roster required')
        receipt=root_stream.ordinary_delivery(prior['rundir'],expected_output=folder)
        core.require(value['outputs']==receipt['outputs'],'predecessor marker lacks actual ordinary delivery')
        passed(value,dep_out)
    def partition(dep,document,export,digest):
        # A partition dependency is its selected delivered attempt, the original or a retry.
        dep_out=Path(export).absolute().parent
        published=_verify_partition_delivery(export,document,dep,digest,selections)
        if published['retry_ledger'] is not None:
            from . import wms_retry
            wms_retry.require_delivery_visible(published['retry_ledger'],_pin(dep_out/'published'/(dep+'.json')),export,digest,dep)
        passed(cap.document(published['marker'],dep_out),dep_out)
    for dep in task['depends_on']:
        if _partition_binding(doc,dep) is not None:partition(dep,doc,path,expected_sha256)
        else:delivered(dep,next(t for t in doc['tasks'] if t['id']==dep),out,_pin(path)['sha256'])
    for row in task.get('after',[]):
        earlier=verify(row['export'],row['export_sha256'])
        prior=next((t for t in earlier['tasks'] if t['id']==row['task']),None)
        core.require(prior is not None,'earlier export dependency names no exported task')
        # A partition of an earlier export is accepted exactly as one of this export.
        if _partition_binding(earlier,row['task']) is not None:partition(row['task'],earlier,row['export'],row['export_sha256'])
        else:delivered(row['task'],prior,Path(row['export']).absolute().parent,row['export_sha256'])
    cap.finish()
    try:science.verify_plan(task['rundir'],approved=True)
    except ValueError as exc:
        raise ValueError('run dir '+str(task['rundir'])+' has no current approved plan ('+str(exc)+'); approve it with `ravel approve --rundir '+str(task['rundir'])+'`; the workflow manager never approves') from exc
    owner=task['owner']
    # Exact exported source is checked immediately before the existing supervisor.
    verify(path,expected_sha256)
    from . import wms_policy
    # A governed run is dispatched only from its indexed export inside a live `ravel wms launch`.
    wms_policy._admit(task['rundir'],path,expected_sha256,identity)
    _dispatch_record(out,identity,_pin(path)['sha256'],task['rundir'])
    with wms_policy._dispatch_context(task['rundir'],path,expected_sha256,identity):
        code=(research_cycle.run_experiment(owner['cycle'],owner['experiment'],resume=False)
              if owner['kind']=='research_cycle' else science.run(task['rundir'],resume=False))
    core.require(code==0,'ordinary step did not deliver; existing recovery/decision required')
    folder=Path(task['rundir'])/task['output_directory'];capture=core.Capture()
    receipt=root_stream.ordinary_delivery(task['rundir'],expected_output=folder)
    result_pin=_pin(folder/'result.json');result=capture.document(result_pin,folder)
    verification_pin=_pin(folder/'verification.json');view=capture.document(verification_pin,folder)
    core.require(result.get('status')=='passed' and result.get('physics_validated') is False and view.get('passed') is True and view.get('physics_validated') is False,'actual ordinary delivery boundary required')
    core.require([result_pin,verification_pin]==receipt['outputs'],'new marker must bind original succeeded ordinary outputs')
    # This marker never supplies research adjudication/acceptance.
    value={'schema_version':1,'task':identity,'export_sha256':_pin(path)['sha256'],'status':'delivered',
           'outputs':[result_pin,verification_pin],'scientific_acceptance_inferred':False}
    capture.finish();verify(path,expected_sha256)
    if _partition_binding(doc,identity) is not None:
        value=publish_partition_delivery(path,identity,expected_sha256,task['rundir'])
    else:
        pin=root_stream.write_new(marker,value)
        dataset_query_quantities.asset_check({r['path']:r for r in [pin,result_pin,verification_pin]})
    verify(path,expected_sha256)
    from . import wms_retry
    wms_retry.publish_registered_attempt_for_run(task['rundir'])
    return value



def _selected_delivery(path,document,task):
    """The delivered attempt of a partition whose original run directory is spent.

    The original itself when it delivered and its marker is missing: its own indexed
    export ran it in a governed project, or publication stopped before the marker. Any
    approved later attempt otherwise: a registered retry, a direct ordinary run or a new
    campaign experiment. None while the original was never dispatched or no attempt delivered.
    """
    binding=_partition_binding(document,task['id'])
    if binding is None:return None
    from . import execution
    try:spent=type(execution.load_execution(task['rundir'])['stages'].get('science')) is dict
    except (OSError,ValueError,KeyError,TypeError):spent=False
    if not spent:return None
    from ravel.physics import root_stream_partitions as partitions
    row,pid=binding;master=partitions.read_master(row['master'],Path(path).absolute().parent)
    _,state=partitions.owner_state(master)
    return partitions.delivered_attempts(master,state)[pid]


def _partition_binding(document,identity):
    rows=[(row,row['partition_tasks'][identity]) for row in document.get('fanin',[])
          if identity in row.get('partition_tasks',{})]
    if not rows:return None
    core.require(all(row['master']==rows[0][0]['master'] and pid==rows[0][1] for row,pid in rows),
                 'partition delivery belongs to multiple masters')
    return rows[0]


def _verify_partition_delivery(path,document,identity,expected_sha256,selections=None):
    """Authenticate the selected journal claim and ordinary output pins, never a file bit.

    `selections` holds one journal selection per master for a single pass over an
    export, so a pass reads each attempt once however many partitions it checks.
    """
    from ravel.physics import root_stream_partitions as partitions
    binding=_partition_binding(document,identity);core.require(binding is not None,'exported partition binding required')
    row,pid=binding;out=Path(path).absolute().parent;cap=core.Capture()
    master=partitions.read_master(row['master'],out,cap);selections={} if selections is None else selections
    if row['master']['sha256'] not in selections:
        _,state=partitions.owner_state(master);selections[row['master']['sha256']]=partitions.delivered_attempts(master,state)
    chosen=selections[row['master']['sha256']][pid]
    core.require(chosen is not None,'partition '+pid+' has no delivered attempt; use `ravel wms retry`')
    publication_path=out/'published'/(identity+'.json')
    # A delivered attempt needs its publication, not another attempt: `ravel wms retry` would refuse it.
    core.require(publication_path.is_file(),'partition '+pid+' delivered in '+chosen['rundir']+' but its delivery was not published '
                 'to this export; finish it with ravel.workflow.wms_retry.publish_registered_attempt(project, rundir) for a '
                 'registered retry, or ravel.workflow.site_workflow.publish_partition_delivery(export, task, export_sha256, rundir) '
                 'for the original attempt or an attempt run outside the retry command; relaunching the export also '
                 'publishes it through the partition rule; none of these runs the attempt again')
    publication_pin=_pin(publication_path);published=cap.document(publication_pin,out)
    core.keys(published,('schema_version','task','export_sha256','master','partition_id','claim','completion','marker','retry_ledger'),
              'issued partition delivery publication')
    core.require(published['schema_version']==1 and published['task']==identity and
                 published['export_sha256']==expected_sha256 and published['master']==row['master'] and
                 published['partition_id']==pid and published['claim']==chosen,'publication is not the selected authenticated master attempt')
    marker_path=out/'completed'/(identity+'.json')
    core.require(published['marker']==_pin(marker_path),'partition delivery marker differs from its issued pin')
    value=cap.document(published['marker'],out)
    original=next(t for t in document['tasks'] if t['id']==identity)
    receipt=root_stream.ordinary_delivery(chosen['rundir'])
    if chosen['rundir']==original['rundir']:
        core.keys(value,('schema_version','task','export_sha256','status','outputs','scientific_acceptance_inferred'),'original partition delivery')
        core.require(published['retry_ledger'] is None,'original delivery cannot claim retry publication')
    else:
        core.keys(value,('schema_version','kind','task','export_sha256','status','rundir','outputs','scientific_acceptance_inferred'),'retry partition delivery')
        core.require(value['kind']=='partition-delivery' and value['rundir']==chosen['rundir'],'retry delivery names a different attempt')
        from . import wms_retry
        if published['retry_ledger'] is None:
            # An attempt run outside `ravel wms retry` is bound by its journal claim; a registered retry keeps its ledger.
            core.require(wms_retry.registered_project(None,master,pid,chosen,path) is None,
                         'registered retry delivery needs its publication ledger')
        else:wms_retry.verify_delivery_publication(published['retry_ledger'],row['master'],pid,chosen,publication_pin,path,expected_sha256,identity)
    core.require(value['schema_version']==1 and value['task']==identity and value['export_sha256']==expected_sha256 and
                 value['status']=='delivered' and value['scientific_acceptance_inferred'] is False and
                 value['outputs']==receipt['outputs'],'partition delivery differs from ordinary result and verification pins')
    _,_,ds,a=root_stream._load({'config':master['base_config']},out,cap)
    completion,_,actual=partitions.completion(published['completion'],out,master,ds,a,cap)
    core.require(completion['rundir']==chosen['rundir'] and actual==receipt,'completion differs from the selected ordinary delivery')
    core.require(root_stream.ordinary_delivery(chosen['rundir'])==receipt,'ending selected partition delivery differs')
    cap.finish();return published


def publish_partition_delivery(path,identity,expected_sha256,rundir,*,project=None):
    """Expose an ordinary delivered attempt through its original immutable export.

    The existing task output is now the partition's delivery record. Creating it
    satisfies the original rule after a retry, so Snakemake never reruns spend.
    """
    from ravel.physics import root_stream_partitions as partitions
    from .state_io import file_lock
    out=Path(path).absolute().parent
    with file_lock(out/'.partition-delivery.lock'):
        document=verify(path,expected_sha256);binding=_partition_binding(document,identity)
        core.require(binding is not None,'actual exported partition delivery required')
        row,pid=binding;master=partitions.read_master(row['master'],out);_,state=partitions.owner_state(master)
        claim=partitions.delivered_attempts(master,state)[pid]
        core.require(claim is not None and claim['rundir']==str(Path(rundir).absolute()),
                     'partition '+pid+' attempt did not deliver; use `ravel wms retry`')
        original=next(t for t in document['tasks'] if t['id']==identity)
        marker=out/'completed'/(identity+'.json')
        if marker.exists():
            published=_verify_partition_delivery(path,document,identity,expected_sha256)
            if published['retry_ledger'] is not None:
                from . import wms_retry
                wms_retry.record_delivery_publication(published['retry_ledger'],claim,_pin(out/'published'/(identity+'.json')),
                                                     path,expected_sha256,identity,visible=True)
            verify(path,expected_sha256)
            return core.strict(marker.read_bytes())
        ledger=None
        if claim['rundir']!=original['rundir']:
            from . import wms_retry
            # A registered retry publishes through its ledger. A direct ordinary run or a new
            # campaign experiment has none: its authenticated journal claim is its custody.
            registrar=wms_retry.registered_project(project,master,pid,claim,path)
            if registrar is not None:
                ledger=wms_retry.registered_delivery_ledger(registrar,master,pid,claim,path,expected_sha256,identity)
        receipt=root_stream.ordinary_delivery(rundir)
        completion_path=Path(row['master']['path']).parent/'completed'/(pid+'.json')
        completion=(_pin(completion_path) if completion_path.exists() else
                    partitions.record(row['master'],pid,rundir,completion_path))
        cap=core.Capture();_,_,ds,a=root_stream._load({'config':master['base_config']},out,cap)
        recorded,_,actual=partitions.completion(completion,out,master,ds,a,cap)
        core.require(recorded['rundir']==claim['rundir'] and actual==receipt,'publication requires selected ordinary completion')
        cap.finish()
        value={'schema_version':1,'task':identity,'export_sha256':expected_sha256,'status':'delivered',
               'outputs':receipt['outputs'],'scientific_acceptance_inferred':False}
        if claim['rundir']!=original['rundir']:value.update(kind='partition-delivery',rundir=claim['rundir'])
        marker_raw=root_stream.encoded(value)
        marker_pin={'path':str(marker),'sha256':hashlib.sha256(marker_raw).hexdigest(),'size':len(marker_raw)}
        published={'schema_version':1,'task':identity,'export_sha256':expected_sha256,'master':row['master'],
                   'partition_id':pid,'claim':claim,'completion':completion,'marker':marker_pin,'retry_ledger':ledger}
        (out/'published').mkdir(exist_ok=True)
        publication_path=out/'published'/(identity+'.json')
        if publication_path.exists():
            core.require(publication_path.read_bytes()==root_stream.encoded(published),'retained publication differs from selected delivery')
            publication=_pin(publication_path)
        else:publication=root_stream.write_new(publication_path,published)
        if ledger is not None:wms_retry.record_delivery_publication(ledger,claim,publication,path,expected_sha256,identity)
        core.require(root_stream.write_new(marker,value)==marker_pin,'issued delivery bytes changed')
        if ledger is not None:wms_retry.record_delivery_publication(ledger,claim,publication,path,expected_sha256,identity,visible=True)
        verify(path,expected_sha256)
        return value


def run_fanin(path,identity,expected_sha256):
    """Merge rule: after every partition rule, write the merge draft from one delivered attempt each."""
    from ravel.physics import root_stream_partitions as partitions
    doc=verify(path,expected_sha256);out=Path(path).absolute().parent
    row=next((r for r in doc.get('fanin',[]) if r['id']==identity),None);core.require(row is not None,'actual exported merge rule required')
    marker=out/'completed'/(identity+'.json');core.require(not marker.exists(),'spent merge rule cannot silently resume')
    master=partitions.read_master(row['master'],out);_,state=partitions.owner_state(master)
    chosen=partitions.delivered_attempts(master,state)
    missing=[pid for pid,claim in chosen.items() if claim is None]
    unresolved=[(r['task_id'],r['rundir']) for r in partitions.master_claims(master,state)
                if r['task_id'] in missing and partitions.attempt_state(r['rundir'])=='unresolved']
    detail='; '.join(partitions.unresolved_detail(pid,rd) for pid,rd in unresolved)
    core.require(not missing,'merge rule needs every partition delivered; missing: '+', '.join(missing)+
                 '; use `ravel wms retry`'+('; '+detail if detail else ''))
    selections={row['master']['sha256']:chosen}
    for task in row['depends_on']:
        published=_verify_partition_delivery(path,doc,task,expected_sha256,selections)
        if published['retry_ledger'] is not None:
            from . import wms_retry
            wms_retry.require_delivery_visible(published['retry_ledger'],_pin(out/'published'/(task+'.json')),path,expected_sha256,task)
    output=Path(row['output']);drafted=partitions.fanin(row['master'],output.parent,output)
    value={'schema_version':1,'task':identity,'export_sha256':_pin(path)['sha256'],'status':'merge-draft-written',
           'outputs':[drafted['specification'],drafted['closure']],'completions':drafted['completions'],
           'consumed_attempts':drafted['consumed_attempts'],'execution_authorized':False,'scientific_acceptance_inferred':False}
    root_stream.write_new(marker,value);verify(path,expected_sha256)
    return value


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='operation',required=True)
    e=sub.add_parser('export');e.add_argument('--request',type=Path,required=True);e.add_argument('--out',type=Path,required=True)
    h=sub.add_parser('statistical-handoff');h.add_argument('--request',type=Path,required=True);h.add_argument('--out',type=Path,required=True)
    v=sub.add_parser('verify');v.add_argument('--export',type=Path,required=True);v.add_argument('--export-sha256',required=True)
    r=sub.add_parser('run-step');r.add_argument('--export',type=Path,required=True);r.add_argument('--task',required=True);r.add_argument('--export-sha256',required=True)
    f=sub.add_parser('fanin');f.add_argument('--export',type=Path,required=True);f.add_argument('--task',required=True);f.add_argument('--export-sha256',required=True)
    pp=sub.add_parser('partition-plan');pp.add_argument('--request',type=Path,required=True);pp.add_argument('--out',type=Path,required=True)
    for operation in ('partition-record','partition-resume','partition-merge'):
        parser=sub.add_parser(operation);parser.add_argument('--request',type=Path,required=True)
        if operation!='partition-resume':parser.add_argument('--out',type=Path,required=True)
    args=p.parse_args(argv)
    if args.operation.startswith('partition-'):
        from ravel.physics import root_stream_partitions as partitions
        capture=core.Capture();request=capture.document(_pin(args.request),args.request.parent)
        if args.operation=='partition-plan':value=partitions.prepare(request,args.request.parent,args.out)
        else:
            core.keys(request,('master','partition_id','rundir') if args.operation=='partition-record' else ('master','completions'),'original partition action')
            if args.operation=='partition-record':value=partitions.record(request['master'],request['partition_id'],request['rundir'],args.out)
            elif args.operation=='partition-resume':value=partitions.resume(request['master'],request['completions'],args.request.parent)
            else:value=partitions.merge_specification(request['master'],request['completions'],args.request.parent,args.out)
        capture.finish()
    elif args.operation=='export':
        capture=core.Capture();request=capture.document(_pin(args.request),args.request.parent);value=export(request,args.request.parent,args.out);capture.finish()
    elif args.operation=='statistical-handoff':
        from ravel.physics.root_stream_statistics import materialize
        capture=core.Capture();request=capture.document(_pin(args.request),args.request.parent)
        value=materialize(request,args.request.parent,args.out);capture.finish()
    elif args.operation=='verify':
        _restore_environment(args.export,args.export_sha256);value=verify(args.export,args.export_sha256)
    elif args.operation=='fanin':
        _restore_environment(args.export,args.export_sha256);value=run_fanin(args.export,args.task,args.export_sha256)
    else:
        _restore_environment(args.export,args.export_sha256,args.task);value=run_step(args.export,args.task,args.export_sha256)
    print(json.dumps(value,sort_keys=True,allow_nan=False));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        raise SystemExit('Site workflow refused: '+str(exc)+'; preserve original ordinary/source/approval records')
