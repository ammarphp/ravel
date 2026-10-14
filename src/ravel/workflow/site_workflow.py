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


def validate(request):
    core.keys(request,('schema_version','site_id','python','tasks','audit','wms'),'site workflow request')
    core.require(type(request['schema_version']) is int and request['schema_version']==1,'site export schema1 required')
    core.text(request['site_id']);core.pin(request['python'])
    core.require(request['wms']=={'engine':'snakemake','version':'9.27.0','cores':1,'retries':0},'required bounded WMS profile must preserve original authority')
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
        core.keys(task,('id','rundir','plan','owner','depends_on'),'prepared ordinary task')
        core.require(type(task['id']) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',task['id']) and task['id'] not in seen,'distinct literal task id required')
        core.require(task['id'] not in RESERVED_TASK_IDS,'task id '+task['id']+' is a reserved Snakemake rule or keyword name')
        core.text(task['rundir']);core.pin(task['plan'])
        core.require(type(task['depends_on']) is list and len(set(task['depends_on']))==len(task['depends_on']) and set(task['depends_on'])<=seen,'dependencies must be earlier complete task identities')
        owner=task['owner'];core.require(type(owner) is dict,'actual ordinary owner required')
        if owner.get('kind')=='research_cycle':
            core.keys(owner,('kind','cycle','experiment'),'campaign owner');core.text(owner['cycle']);core.text(owner['experiment'])
        else:core.require(owner=={'kind':'ordinary'},'explicit standalone or actual research-cycle owner required')
        seen.add(task['id'])
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


def _source_assets():
    root=Path(__file__).parents[2]
    census=root_stream.census(root)
    # Complete source membership, including installed operational/data assets.
    return root,census


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
    tasks=[];cycles={};rundirs=set();partition_tasks=set()
    for row in request['tasks']:
        rd=_path(row['rundir'],base,True);core.require(rd not in rundirs,'one original run may not be dispatched twice');rundirs.add(rd)
        p,_=cap.read(row['plan'],base);core.require(p==rd/science.PLAN,'actual canonical prepared plan required')
        plan,spec,destination=root_stream.ordinary_plan_destination(rd)
        if spec['mode']=='root-stream':
            from ravel.physics import root_stream_partitions as partitions
            identity=partitions.dispatch_identity(spec['task'],rd,cap)
            if identity is not None:
                core.require(identity not in partition_tasks,'duplicate original master partition/merge dispatch refused');partition_tasks.add(identity)
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
        # Exact original stage source and inputs are already checked by verify_plan.
        tasks.append({**deepcopy(row),'rundir':str(rd),'plan':_pin(p),'owner':owner,'mode':spec['mode'],
                      'output_directory':destination})
    cap.finish();source_root,source_census=_source_assets()
    return {'schema_version':1,'kind':'site-workflow-export','site_id':request['site_id'],'python':python,
            'tasks':tasks,'audit':deepcopy(audit),'audit_input_pins':list(cap.rows.values()),'cycles':cycles,
            'source_root':str(source_root),'source_census':source_census,'wms':request['wms'],
            'original_blind_domain_sha256':None if blind['original_domain'] is None else blind['original_domain']['sha256'],
            'execution_authorized':False,'scientific_acceptance_inferred':False,
            'limitations':['Credentials are runtime policy references and are never copied into this packet.',
                'Exports bind current paths and source; moving to a site requires ordinary re-preparation, not plan relocation.',
                'WMS retries and resume are disabled; failed/ambiguous operations need existing guarded recovery.',
                'Prompt/model/token/environment records preserve supplied source identity; their scientific completeness needs independent review.']}


def _snakefile(manifest_path,document):
    """Every executable token is generated/quoted from the closed actual schema.

    No top-level Python runs at parse time: integrity is the explicit rule
    ravel_verify_export, which every task rule takes as input. run_step re-verifies too.
    """
    expected=hashlib.sha256(root_stream.encoded(document)).hexdigest()
    python=document['python']['path'];gate='completed/.export-verified-'+expected[:12]+'.json'
    def escaped(argv):return shlex.join(argv).replace('{','{{').replace('}','}}')
    verify=escaped([python,'-I','-B','-m','ravel.workflow.site_workflow','verify','--export',str(manifest_path),'--export-sha256',expected])
    marker=json.dumps({'export_sha256':expected,'verified':True},sort_keys=True).replace('{','{{').replace('}','}}')
    lines=['# Generated reproducibility wrapper; ordinary RAVEL retains all authority.','rule all:','    input:']
    for task in document['tasks']:lines.append('        '+repr('completed/'+task['id']+'.json')+',')
    lines.extend(['','rule ravel_verify_export:','    output: '+repr(gate),'    threads: 1','    retries: 0',
        '    shell: '+repr(verify+' > /dev/null && printf \'%s\\n\' '+shlex.quote(marker)+' > {output:q}')])
    for task in document['tasks']:
        deps=[gate]+['completed/'+x+'.json' for x in task['depends_on']]
        command=escaped([python,'-I','-B','-m','ravel.workflow.site_workflow','run-step','--export',str(manifest_path),'--task',task['id'],'--export-sha256',expected])
        # Literal braces must escape Snakemake's formatter; no arbitrary shell.
        lines.extend(['','rule task_'+task['id']+':','    input: '+repr(deps),
            '    output: '+repr('completed/'+task['id']+'.json'),'    threads: 1','    retries: 0','    shell: '+repr(command)])
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
    return {'manifest':pin,'closure':closure,'wms_argv':['snakemake','--snakefile',str(p),'--directory',str(out),'--cores','1','--retries','0'],
            'execution_authorized':False,'scientific_acceptance_inferred':False}


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
    partition_tasks=set()
    for task in doc['tasks']:
        rd=Path(task['rundir']);cap.read(task['plan'],out)
        plan,spec,destination=root_stream.ordinary_plan_destination(rd)
        core.require(destination==task['output_directory'] and spec['mode']==task['mode'],'actual selected stage destination/mode differs')
        if spec['mode']=='root-stream':
            from ravel.physics import root_stream_partitions as partitions
            identity=partitions.dispatch_identity(spec['task'],rd,cap)
            if identity is not None:
                core.require(identity not in partition_tasks,'duplicate original master partition/merge dispatch refused');partition_tasks.add(identity)
            _,_,_,analysis=root_stream._load(spec['task'],rd,cap)
            if analysis['blinding'] is not None:core.require(analysis['blinding']['source']['sha256']==doc['original_blind_domain_sha256'],
                'original exported blind-domain policy cannot change across adaptive tasks')
    for cycle,binding in doc['cycles'].items():
        _,state=research_cycle._load(cycle)
        core.require({'context_request_sha256':state['context']['request_sha256'],'contract':state['contract']}==binding,'original campaign question/contract differs')
    delivered=[]
    for task in doc['tasks']:
        marker=out/'completed'/(task['id']+'.json')
        if marker.exists():
            value=cap.document(_pin(marker),out);core.keys(value,('schema_version','task','export_sha256','status','outputs','scientific_acceptance_inferred'),'completion marker')
            folder=Path(task['rundir'])/task['output_directory']
            core.require(value['schema_version']==1 and value['task']==task['id'] and value['export_sha256']==expected_sha256 and value['status']=='delivered' and value['scientific_acceptance_inferred'] is False and [r['path'] for r in value['outputs']]==[str(folder/'result.json'),str(folder/'verification.json')],'original complete completion marker required')
            receipt=root_stream.ordinary_delivery(task['rundir'],expected_output=folder)
            core.require(value['outputs']==receipt['outputs'],'marker is not the original succeeded ordinary delivery')
            delivered.append((task['rundir'],folder,receipt))
            result=core.strict(cap.read(value['outputs'][0],out,max(8*1024**2,value['outputs'][0]['size']))[1]);view=cap.document(value['outputs'][1],out)
            core.require(result.get('status')=='passed' and result.get('physics_validated') is False and view.get('passed') is True and view.get('physics_validated') is False,'retained ordinary delivery required')
    cap.finish();core.require(root_stream.census(Path(doc['source_root']))==doc['source_census'],'ending complete original source differs')
    for rd,folder,receipt in delivered:
        core.require(root_stream.ordinary_delivery(rd,expected_output=folder)==receipt,'ending original WMS delivery differs')
    cap.finish()
    dataset_query_quantities.asset_check({r['path']:r for r in closure['files']})
    return doc


def run_step(path,identity,expected_sha256):
    """Explicit execution entry called by the required WMS, never by export."""
    from . import science,research_cycle
    doc=verify(path,expected_sha256);out=Path(path).absolute().parent
    task=next((t for t in doc['tasks'] if t['id']==identity),None);core.require(task is not None,'actual exported task required')
    marker=out/'completed'/ (identity+'.json');core.require(not marker.exists(),'spent WMS step cannot silently resume')
    cap=core.Capture()
    for dep in task['depends_on']:
        value=cap.document(_pin(out/'completed'/(dep+'.json')),out)
        core.require(value['task']==dep and value['export_sha256']==_pin(path)['sha256'] and value['status']=='delivered','exact delivered dependency required')
        prior=next(t for t in doc['tasks'] if t['id']==dep)
        folder=Path(prior['rundir'])/prior['output_directory']
        core.keys(value,('schema_version','task','export_sha256','status','outputs','scientific_acceptance_inferred'),'original completion marker')
        core.require(value['scientific_acceptance_inferred'] is False and [p['path'] for p in value['outputs']]==[str(folder/'result.json'),str(folder/'verification.json')],'canonical full ordinary output roster required')
        receipt=root_stream.ordinary_delivery(prior['rundir'],expected_output=folder)
        core.require(value['outputs']==receipt['outputs'],'predecessor marker lacks actual ordinary delivery')
        result=core.strict(cap.read(value['outputs'][0],out,max(8*1024**2,value['outputs'][0]['size']))[1])
        view=cap.document(value['outputs'][1],out)
        core.require(result.get('status')=='passed' and result.get('physics_validated') is False and view.get('passed') is True and view.get('physics_validated') is False,'actual predecessor delivery required')
    cap.finish();science.verify_plan(task['rundir'],approved=True)
    owner=task['owner']
    # Exact exported source is checked immediately before the existing supervisor.
    verify(path,expected_sha256)
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
    capture.finish();verify(path,expected_sha256);pin=root_stream.write_new(marker,value)
    dataset_query_quantities.asset_check({r['path']:r for r in [pin,result_pin,verification_pin]})
    verify(path,expected_sha256)
    return value


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='operation',required=True)
    e=sub.add_parser('export');e.add_argument('--request',type=Path,required=True);e.add_argument('--out',type=Path,required=True)
    h=sub.add_parser('statistical-handoff');h.add_argument('--request',type=Path,required=True);h.add_argument('--out',type=Path,required=True)
    v=sub.add_parser('verify');v.add_argument('--export',type=Path,required=True);v.add_argument('--export-sha256',required=True)
    r=sub.add_parser('run-step');r.add_argument('--export',type=Path,required=True);r.add_argument('--task',required=True);r.add_argument('--export-sha256',required=True)
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
    elif args.operation=='verify':value=verify(args.export,args.export_sha256)
    else:value=run_step(args.export,args.task,args.export_sha256)
    print(json.dumps(value,sort_keys=True,allow_nan=False));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError,RuntimeError):
        raise SystemExit('Site workflow refused; preserve original ordinary/source/approval records')
