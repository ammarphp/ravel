"""Evidence-only qualification of retained failed outputs; no producer is launched."""
from pathlib import Path
import hashlib
import json
import re
import time

from ravel.workflow.state_io import atomic_json
from ravel.validation import mpi_observer as native
from ravel.validation import diagnostic_plan as plans
from ravel.validation import initialized_settings_checks as checks
from ravel.physics import lhe_provenance

SCOPE = 'retained_initialized_settings_qualification'
ZERO_CALLS = dict(compiles=0, shower_calls=0, shower_exposures=0,
                 new_hard_events=0, detectors=0, conversions=0, analyses=0, fits=0, retries=0)
JSON_CEILING = 64*1024**2


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(path, ceiling=JSON_CEILING):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), 'Regular JSON evidence required')
    with path.open('rb') as stream:
        raw = stream.read(ceiling+1)
    require(0 < len(raw) <= ceiling, 'Bounded complete JSON evidence required')
    return checks.strict(raw)


def validate(task):
    require(type(task) is dict and set(task)=={'input','sha256'} and type(task['input']) is str and type(task['sha256']) is str,'exact retained input pin required')


def separate_roots(origin, resource):
    """Refuse lexical or resolved origin overlap before any output publication."""
    origin, resource = Path(origin), Path(resource)
    for p in (origin, resource):
        require(p.is_absolute() and '..' not in p.parts and
                not any(q.is_symlink() for q in (p, *p.parents)),
                'Absolute nonsymlink origin and resource ancestors required')
    old, new = origin.resolve(strict=True), resource.resolve(strict=False)
    require(old.is_dir() and not old.is_relative_to(new) and not new.is_relative_to(old),
            'Separate resolved origin and resource roots required')
    return old, new


def document(task, base):
    from ravel.workflow.science import regular
    validate(task)
    path=regular(task['input'],base)
    require(native.digest(path)==task['sha256'],'retained qualification input changed')
    d=load(path,1024**2)
    plan=plans.selected(d, ('failure_boundary','transports','snapshots','pairs','binary'))
    plans.fields(d,{'schema_version','scope','origin_contract','evidence','artifacts','resources','assumptions','plan'},'closed retained qualification fields required')
    require(type(d['schema_version']) is int and d['schema_version']==1 and d['scope']==SCOPE,'retained schema/scope differs')
    pin=d['origin_contract'];origin=regular(pin['path'],path.parent)
    require(native.digest(origin)==pin['sha256'],'origin contract changed')
    old=load(origin,1024**2)
    native.validate_resources(d['resources'])
    native.validate_resources(old['resources'])
    native.validate_stages(old['stages'],old['resources']['max_seconds'])
    e=d['evidence']
    require(set(e)=={'report','stage_record','outer_receipt','root_quiescence','output_root','output_manifest'},'exact origin evidence required')
    root=Path(e['output_root'])
    require(root.is_absolute() and '..' not in root.parts,'absolute origin output root required')
    require(type(d['artifacts']) is list and d['artifacts'] and len({row['path'] for row in d['artifacts']})==len(d['artifacts']),'unique complete origin artifact population required')
    require(load(e['output_manifest']['path'])['artifacts']==d['artifacts'],'retained output manifest differs')
    for row in d['artifacts']:
        q=Path(row['path']);require(q.is_absolute() and '..' not in q.parts and q.is_relative_to(root),'origin artifact outside output root')
    separate_roots(root,d['resources']['resource_root'])
    require(type(d['assumptions']) is list and d['assumptions'] and all(type(x) is str and x for x in d['assumptions']),'failed-origin scope assumptions required')
    for field in ('transports','snapshots','pairs'):
        require(type(plan[field]) is list and plan[field] and len({row['id'] for row in plan[field]})==len(plan[field]),'complete unique supplied '+field+' witnesses required')
    for row in plan['snapshots']:
        require(set(row)=={'id','file','schema','compiled_source','command','settings','masses'},'closed retained snapshot contract required')
        plans.relative(row['file'])
    for row in plan['pairs']:
        require(set(row)=={'id','disabled','enabled','reference','encoding'},'closed retained pair contract required')
        require(set(row['disabled'])==set(row['enabled'])==set(row['reference'])=={'hepmc','sidecar'},'complete paired stream witnesses required')
        for name in [*row['disabled'].values(),*row['enabled'].values()]:plans.relative(name)
    for row in plan['transports']:
        require(set(row)=={'id','folder','source_lhe','events','encoding','command'},'closed retained transport contract required')
        plans.relative(row['folder']);plans.positive(row['events'],'transport.events',integer=True)
    return path,d,old,plan


def inputs(task, base, *, _session=None):
    from ravel.workflow.science import regular
    p,d,old,plan=document(task,base)
    def pin_rows(value):
        if isinstance(value,dict):
            if 'path' in value and 'sha256' in value:
                yield value
            else:
                for row in value.values():yield from pin_rows(row)
        elif isinstance(value,list):
            for row in value:yield from pin_rows(row)
    paths=[p]
    for row in [*pin_rows(d),*pin_rows(old)]:
        require(set(row) in ({'path','sha256'},{'path','sha256','bytes'}) and re.fullmatch('[0-9a-f]{64}',row['sha256']),'exact retained source pin required')
        q=regular(row['path'],p.parent,_session=_session)
        h=_session.hash_file(q) if _session else native.digest(q)
        require(h==row['sha256'],'retained source changed: '+str(q))
        if 'bytes' in row:require(type(row['bytes']) is int and row['bytes']>=0 and q.stat().st_size==row['bytes'],'retained artifact size changed')
        paths.append(q)
    root=Path(d['evidence']['output_root'])
    require(not any(q.is_symlink() for q in root.rglob('*')),'original output tree contains symlink')
    require({str(q) for q in root.rglob('*') if q.is_file()}=={r['path'] for r in d['artifacts']},'original output population changed')
    return list(dict.fromkeys(paths))


def _validation_inputs(task, base, session):
    return inputs(task, base, _session=session)


def input_snapshot(task, base):
    from ravel.workflow.execution import _validation_session
    session = _validation_session(base, task)
    try:
        result = {str(p): session.hash_file(p) for p in inputs(task, base, _session=session)}
        require(not (errors := session.finish()), '; '.join(errors))
        return result
    finally:
        session.close()


def execution_seconds(task, base):
    return document(task, base)[1]['resources']['max_seconds']


def resource_bounds(task, base):
    return {**{k:v for k,v in document(task, base)[1]['resources'].items() if k != 'resource_root'}, **ZERO_CALLS}


def failure_boundary(report, stage, outer, quiescence, contract):
    classes=plans.required(contract,'failure_classes')
    allowed={'resource_floor','resource_ceiling','deadline','producer_exit','custody_mismatch'}
    require(type(classes) is list and classes and set(classes)<=allowed,'typed retained failure classes required')
    failures=[report,stage,outer]
    bindings=contract.get('class_bindings',[])
    for binding in bindings:
        require(set(binding)=={'record','sha256','failure_class'} and binding['record'] in ('report','stage','outer') and binding['failure_class'] in classes,'closed byte-bound failure classification required')
    classified={}
    from ravel.workflow.execution import digest
    for name,record in zip(('report','stage','outer'),failures):
        declared=record.get('failure_class')
        if declared is None:
            matches=[b for b in bindings if b['record']==name and b['sha256']==digest(record)]
            require(len(matches)==1,'untyped legacy failure needs one supplied byte-bound classification')
            declared=matches[0]['failure_class']
        classified[name]=declared
    failure_class=classified['report']
    require(report.get('status')=='failed' and report.get('successful_end_custody') is False and report.get('active_stage') is None and failure_class in classes,'terminal typed failed report required')
    require(stage.get('status')=='failed' and type(stage.get('exit_code')) is int and stage['exit_code']!=0 and classified['stage']==failure_class and stage.get('cleanup',{}).get('group_state')=='empty' and stage['cleanup'].get('requires_recovery') is False,'failed terminal stage with completed cleanup required')
    require(outer.get('status')=='failed' and outer.get('complete_delivery') is False and classified['outer']==failure_class,'typed failed controller required')
    phases=plans.required(contract,'phases');execution_phase=plans.required(contract,'execution_phase')
    require(type(phases) is list and phases and len(set(phases))==len(phases) and [p['name'] for p in outer['phases']]==phases and execution_phase in phases,'complete supplied origin phases required')
    phase=outer['phases'][phases.index(execution_phase)]
    require(phase['final_returncode']==stage['exit_code'] and type(phase['timed_out']) is bool and (not phase['timed_out'] or failure_class=='deadline'),'stage/controller terminal failure differs')
    require(all(type(p.get('final_returncode')) is int and type(p.get('timed_out')) is bool for p in outer['phases']),'complete phase terminal outcomes required')
    require(outer['final_census']['quiescent'] is True and not outer['final_census']['active_rows'] and not outer['final_census']['zombie_rows'] and quiescence['quiescent'] is True and quiescence['matching_rows']==[],'retained root terminal quiescence required')
    require(stage['supervisor_pid']==phase['pid'] and {outer['watchdog_pid'],stage['supervisor_pid'],stage['child_pid']}<=set(quiescence['owned_pids']) and {stage['child_pid'],stage['supervisor_pid']}<=set(quiescence['groups']),'quiescence does not cover actual scientific lineage')
    return {'original_scientific_status':'failed','original_controller_status':'failed','failure_class':failure_class,'original_resource_contract_satisfied':False,'original_result_rewritten':False,'quiescence_scope':'Pinned observation at its recorded time; no new OS observation.'}


def command_evidence(receipt, stage, old, output, pins):
    expected = [x.replace('{OUTPUT}',str(output)) for x in stage['argv']]
    outputs = [str(output/x) for x in stage['outputs']]
    require(receipt['argv'] == expected and receipt['cwd'] == str(output) and
            receipt['environment'] == old['environment'] and receipt['outputs'] == outputs and
            receipt['max_seconds'] == stage['max_seconds'], 'Original native command contract differs')
    require(receipt['status'] == 'completed' and receipt['actual_returncode'] == 0 and
            receipt['expected_returncode'] == 0 and receipt.get('timed_out',False) is False,
            'Original native command did not complete cleanly')
    artifacts = receipt['artifacts']
    require(len(artifacts) == len(outputs) and {x['path'] for x in artifacts} == set(outputs),
            'Original command artifact census differs')
    require(all(pins.get(x['path']) == x['sha256'] for x in artifacts), 'Command artifact absent or changed')
    return {'stage':stage['id'],'pid':receipt['pid'],'returncode':0,
            'elapsed_seconds':receipt['elapsed_seconds'],'output_count':len(outputs)}


def loader_evidence(output, stages, pins, binary):
    known = set(pins)
    require(str(binary) in known, 'Built binary is not retained input')
    result = {'built_candidate':{'path':str(binary),'sha256':pins[str(binary)]},
              'observed_bound_images':set(), 'system_platform_bound_images':set(), 'unbound_images':set(),
              'stage_trace_counts':{}}
    for stage in stages:
        p = output/'native-logs'/(stage['id']+'.log')
        require(str(p) in known and p.stat().st_size <= 16*1024**2, 'Bounded pinned loader trace required')
        with p.open('rb') as f: raw = f.read(16*1024**2+1)
        require(len(raw) <= 16*1024**2 and hashlib.sha256(raw).hexdigest() == pins[str(p)], 'Loader trace changed')
        images = re.findall(r'^dyld\[\d+\]: <[0-9A-Fa-f-]+> (/[^\r\n]+)$',raw.decode('utf-8',errors='replace'),re.MULTILINE)
        require(images, 'Missing actual native loader trace')
        result['stage_trace_counts'][stage['id']] = len(images)
        for image in images:
            if image.startswith(('/usr/lib/','/System/Library/','/System/Volumes/Preboot/Cryptexes/')):
                result['system_platform_bound_images'].add(image)
            else:
                image = str(Path(image).resolve(strict=True))
                result['observed_bound_images' if image in known else 'unbound_images'].add(image)
    for key in ('observed_bound_images','system_platform_bound_images','unbound_images'):
        result[key] = sorted(result[key])
    require(not result['unbound_images'], 'Original native loader image is unbound')
    return result


def entry_reserve(resources, observation):
    """Check remaining whole-case capacity using the fresh first Guard sample."""
    used, free = observation['usage']['logical_bytes'], observation['free_bytes']
    require(type(used) is int and used >= 0 and type(free) is int and free >= 0,
            'Exact nonnegative initial storage observation required')
    remaining = max(0, resources['retained_bytes']-used)
    needed = resources['free_floor_bytes']+remaining+resources['headroom_bytes']
    return {'observation':observation, 'remaining_case_capacity_bytes':remaining,
            'required_free_bytes':needed, 'passed':free >= needed,
            'limitation':'Fresh userspace observation, not a quota or guarantee against other writers.'}


def run(task, base, output_dir):
    started=time.monotonic()
    _,d,old,plan=document(task,base)
    origin_root,resource_root=separate_roots(d['evidence']['output_root'],d['resources']['resource_root'])
    out=Path(output_dir).absolute()
    require('..' not in out.parts and not any(p.is_symlink() for p in (out,*out.parents)),'nonsymlink output ancestors required')
    out=out.resolve(strict=False)
    require(not out.exists() or out.is_dir() and not any(out.iterdir()),'fresh empty output required')
    require(out.is_relative_to(resource_root) and not out.is_relative_to(origin_root),'output outside new resource root')
    out.mkdir(parents=True,exist_ok=True)
    guard=native.Guard(d['resources'],out/'resource-telemetry.jsonl')
    result={'status':'failed','scope':SCOPE,'successful_end_custody':False,'new_native_counts':ZERO_CALLS,'commands':[],'transports':{},'transport_comparisons':{},'snapshots':{},'pairs':{},'physics_validated':False,'original_resource_contract_satisfied':False,'original_result_rewritten':False}
    def save():
        result['elapsed_seconds']=time.monotonic()-started
        plans.publish(out,plan,result)
    def budget():require(time.monotonic()-started<d['resources']['max_seconds']-native.CUSTODY_RESERVE_SECONDS,'retained verification deadline exceeded')
    save()
    try:
        result['entry_resource']=entry_reserve(d['resources'],guard.check());save()
        require(result['entry_resource']['passed'],'Insufficient entry reserve for remaining whole-case capacity')
        budget();before=input_snapshot(task,base);budget()
        e=d['evidence'];root=origin_root
        report=load(e['report']['path']);stage_record=load(e['stage_record']['path'])
        result['origin']=failure_boundary(report,stage_record,load(e['outer_receipt']['path']),load(e['root_quiescence']['path']),plan['failure_boundary']);save()
        require(report['input_pins'] and all(before.get(p)==h for p,h in report['input_pins'].items()),'original source/runtime custody differs')
        require(all(stage_record['input_snapshot'].get(p,{}).get('files')==[{'name':'.','size':Path(p).stat().st_size,'sha256':h}] for p,h in report['input_pins'].items()),'adapter and supervised custody differ')
        require(len(report['commands'])==len(old['stages']),'complete original command receipts required')
        for index,stage in enumerate(old['stages']):
            budget();result['active_stage']=stage['id'];save()
            receipt=load(root/'native-logs'/(stage['id']+'.command.json'),1024**2)
            require(receipt==report['commands'][index],'reported and literal receipt differ')
            result['commands'].append(command_evidence(receipt,stage,old,root,before));save()
        for row in plan['transports']:
            budget();folder=root/row['folder'];transport=load(folder/'transport-verification.json',1024**2)
            command=transport['producer']['command']
            require(command==[v.replace('{OUTPUT}',str(root)) for v in row['command']],'retained producer identity differs')
            checks.transport(transport,events=row['events'],command=command)
            require(all(before.get(x['path'])==x['sha256'] for x in transport['producer']['input_sources']),'producer source custody differs')
            fresh=lhe_provenance.verify_new_generation(row['source_lhe']['path'],folder/'original-lhe.jsonl',folder/'events.hepmc.gz',expected_events=row['events'],encoding=row['encoding'])
            result['transports'][row['id']]=fresh;result['transport_comparisons'][row['id']]={'status':'pending'};save()
            agrees=all(transport.get(k)==v for k,v in fresh.items())
            result['transport_comparisons'][row['id']]={'status':'passed' if agrees else 'mismatch'};save()
            require(agrees,'retained transport arithmetic differs')
        for row in plan['snapshots']:
            budget()
            result['snapshots'][row['id']]=checks.snapshot(root/row['file'],load(row['schema']['path'],1024**2),command=[v.replace('{OUTPUT}',str(root)) for v in row['command']],compiled_source_path=row['compiled_source']['path'],expected_settings=row['settings'],expected_masses=row['masses']);save()
        for row in plan['pairs']:
            budget()
            result['pairs'][row['id']]=checks.pair({k:root/v for k,v in row['disabled'].items()},{k:root/v for k,v in row['enabled'].items()},{k:v['path'] for k,v in row['reference'].items()},encoding=row['encoding']);save()
        result['loader_census']=loader_evidence(root,old['stages'],before,root/plans.relative(plan['binary']));save()
        require(result['loader_census']==report['loader_census'],'original loader census differs')
        budget();require(before==input_snapshot(task,base),'final retained custody changed')
        result['input_count']=len(before)
        result['input_digest']=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result['limits']=['Original failed contracts remain failed.','Qualification covers only the declared retained population and witnesses.','Time and storage observations are sampled; no OS quota is inferred.']
        result.update(status='passed',successful_end_custody=True,active_stage=None);save()
        guard.check(final=True)
        require(time.monotonic()-started<d['resources']['max_seconds'],'final verification deadline exceeded')
    except Exception as exc:
        result.update(status='failed',successful_end_custody=False,error={'type':type(exc).__name__,'message':str(exc)})
        save()
    return result
