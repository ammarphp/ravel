"""Admitted paired interventions using supplied stages, populations and criteria."""
from pathlib import Path
import json
import platform
import math
import time
from ravel.validation import mpi_observer as native
from ravel.validation import initialized_settings_checks as checks
from ravel.workflow.state_io import atomic_json
from ravel.validation import diagnostic_plan as plans
from ravel.validation.mpi_paired import causal_stage_recipe as recipe
from ravel.validation.mpi_paired import external_loader_census as loaders
from ravel.validation.mpi_paired import causal_postprocessing as post
from ravel.validation.mpi_paired import paired_effect_inference_v2 as estimator
from ravel.validation.mpi_paired import producer_witness_v2 as witness
from ravel.validation.mpi_paired.full_signal_moments import specification

SCOPE='fixed_cohort_paired_mpi_response'
QUALIFICATION_SCOPE='initialized_settings_observer_qualification'
RETAINED_QUALIFICATION_SCOPE='retained_initialized_settings_qualification'
DOCUMENT_CEILING=16*1024**2

def require(ok,message):
    if not ok:raise ValueError(message)

def read_json(path,check_budget=lambda:None,*,ceiling=DOCUMENT_CEILING):
    _,raw,_=witness._read_pin(path,check_budget,retain=True,ceiling=ceiling)
    return checks.strict(raw)

def pins(value):
    if isinstance(value,dict):
        if 'path' in value or 'sha256' in value:
            require(set(value) in ({'path','sha256'},{'path','sha256','bytes'}) and type(value['path']) is str
                    and Path(value['path']).is_absolute() and '..' not in Path(value['path']).parts
                    and type(value['sha256']) is str and len(value['sha256'])==64
                    and all(c in '0123456789abcdef' for c in value['sha256']), 'Closed absolute scientific pin required')
            if 'bytes' in value:require(type(value['bytes']) is int and value['bytes']>=0,'Exact pin byte count required')
            yield value
        else:
            for v in value.values():yield from pins(v)
    elif isinstance(value,list):
        for v in value:yield from pins(v)

def validate(task):
    require(type(task) is dict and set(task)=={'input','sha256'} and type(task['input']) is str
            and type(task['sha256']) is str and len(task['sha256'])==64,'Exact paired-effect input pin required')

def document(task,base):
    from ravel.workflow.science import regular
    validate(task);p=regular(task['input'],base)
    require(native.digest(p)==task['sha256'],'Paired-effect input changed')
    d=read_json(p)
    diagnostic=plans.selected(d, ('intervention','stages','census','qualification_expectations','loader_stages','setting_contrasts'))
    plans.fields(d,{'plan','schema_version','scope','tools','inputs','sources','runtime_inventory',
        'qualification','schema','settings','masses','expected_identities','selection_sources',
        'signal_spec','environment','resources','platform','assumptions'},'Paired-effect fields differ')
    require(type(d['schema_version']) is int and d['schema_version']==1 and d['scope']==SCOPE,'Paired-effect schema/scope differs')
    plan=recipe.stages(plan=diagnostic,resources=d['resources'])
    require(d['platform']==platform.platform(),'Native platform changed')
    require(d['expected_identities']['path']==d['inputs']['expected_identities'],'Original identity manifest association differs')
    require(set(d['settings'])=={'on','off'},'two declared initialized arms required')
    contrasts=diagnostic['setting_contrasts']
    require(type(contrasts) is list and contrasts,'supplied initialized intervention required')
    for contrast in contrasts:
        require(set(contrast)=={'group','field','on','off'} and contrast['group'] in ('flags','modes','words'),'closed setting contrast required')
        require(contrast['on']!=contrast['off'] and all(d['settings'][arm][contrast['group']].get(contrast['field'])==contrast[arm] for arm in ('on','off')),'supplied initialized contrast differs')
    estimator.validate_descriptor(diagnostic['intervention'],d['signal_spec'])
    require(set(d['selection_sources'])=={'selection_source_sha256','diagnostic_source_sha256','rjr_binary_sha256'} and all(type(v) is str and len(v)==64 and all(c in '0123456789abcdef' for c in v) for v in d['selection_sources'].values()),'bound selection implementation identities required')
    for arm in ('on','off'):
        require(set(d['settings'][arm])=={'flags','modes','words'},'closed initialized settings required')
        require(all(type(v) is bool for v in d['settings'][arm]['flags'].values()) and all(type(v) is int for v in d['settings'][arm]['modes'].values()) and all(type(v) is str for v in d['settings'][arm]['words'].values()),'typed initialized settings required')
    require(type(d['masses']) is dict and d['masses'] and all(type(k) is str and type(v) in (int,float) and math.isfinite(v) and v>=0 for k,v in d['masses'].items()),'supplied mass expectations required')
    require(set(diagnostic['loader_stages'])<={s['id'] for s in plan['stages']},'declared loader population differs')
    require(plan['census'].get('selected_original_events')==diagnostic['intervention']['analyzed_events'],'effect census differs from supplied cohort')
    require(type(d['sources']) is list and 1<=len(d['sources'])<=1024,'Bounded complete helper/source pins required')
    source_paths={row['path'] for row in d['sources']}
    # Environment prefixes are directory identities established by complete tree
    # censuses; every executable/helper and all scientific input files are pins.
    literal_files={v for k,v in d['tools'].items() if k not in ('rivet_env','recast_env')}|set(d['inputs'].values())
    require(literal_files<=source_paths,'Every literal tool/scientific input must be a direct pin')
    require(type(d['environment']) is dict and all(type(k) is str and type(v) is str for k,v in d['environment'].items()),'Complete literal native environment required')
    for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','PYTHONDONTWRITEBYTECODE','DYLD_PRINT_LIBRARIES'):
        require(d['environment'].get(k)=='1','Single-thread/bytecode/loader settings required')
    r=d['resources'];require(set(r)=={'max_seconds','workers','attempts','retained_bytes','free_floor_bytes','headroom_bytes','inherited_bytes','lineage_ceiling_bytes','resource_root'},'Closed resource envelope required')
    require(all(type(v) is int for k,v in r.items() if k!='resource_root'),'Exact integer resource bounds required')
    native.validate_resources(r)
    require(type(d['assumptions']) is list and len(d['assumptions'])>=6 and all(type(v) is str and v for v in d['assumptions']),'Scientific/custody limits required')
    return p,d,plan

def inputs(task,base,*,_session=None):
    from ravel.workflow.science import regular
    p,d,_=document(task,base);paths=[p]
    if _session is not None:
        _session.require_inventory(Path(d['qualification']['rundir'])/'logs/physics_review/events')
    for row in pins(d):
        q=regular(row['path'],p.parent,_session=_session)
        actual=_session.hash_file(q) if _session is not None else native.digest(q)
        require(actual==row['sha256'],'Bound paired input changed: '+str(q))
        if 'bytes' in row:require(type(row['bytes']) is int and q.stat().st_size==row['bytes'],'Input byte count differs')
        paths.append(q)
    inventory=read_json(d['runtime_inventory']['path'],ceiling=64*1024**2)
    for row in inventory.get('aliases',[]):
        require(set(row)=={'path','resolved'} and str(Path(row['path']).resolve(strict=True))==row['resolved'],'Runtime alias changed')
    paths.extend(native.observer_runtime_files(inventory,_session=_session))
    return list(dict.fromkeys(paths))

def _validation_inputs(task,base,session):return inputs(task,base,_session=session)

def input_snapshot(task,base):
    from ravel.workflow.execution import _validation_session
    session=_validation_session(base,task)
    try:
        observed={str(p):session.hash_file(p) for p in inputs(task,base,_session=session)}
        errors=session.finish();require(not errors,'; '.join(errors));return observed
    finally:session.close()

def execution_seconds(task,base):return document(task,base)[1]['resources']['max_seconds']

def resource_bounds(task,base):
    _,d,p=document(task,base)
    return {**{k:v for k,v in d['resources'].items() if k!='resource_root'},**p['census']}

def accepted_qualification(d,check_budget):
    """Bind current full journal to detached accepted scope and exact binary.

    Ordinary source snapshots also bind each current file throughout this run;
    a later hold/head change refuses end custody instead of trusting old votes.
    """
    from ravel.workflow.physics_review import validate_snapshot
    q=d['qualification']
    require(set(q)=={'review_snapshot','registration','events','head','result','rundir','claim_scope'},'Exact current qualification evidence required')
    scope=q['claim_scope']
    require(scope in (QUALIFICATION_SCOPE,RETAINED_QUALIFICATION_SCOPE),'Declared qualification route differs')
    current=read_json(q['review_snapshot']['path'],check_budget,ceiling=64*1024**2)
    require(not validate_snapshot(current),'Qualification review is not valid accepted authority')
    require(current['action']=='reuse','Qualification must admit explicit reuse')
    root=Path(q['rundir']);require(root.is_absolute() and '..' not in root.parts,'Qualification run root required')
    require(q['registration']['path']==str(root/'logs/physics_review/registration.json') and q['head']['path']==str(root/'logs/physics_review/head.json'),'Qualification current authority paths differ')
    require(type(q['events']) is list and 1<=len(q['events'])<=1000,'Bounded complete current event journal required')
    directory=root/'logs/physics_review/events'
    expected=[directory/f'{i:08d}.json' for i in range(1,len(q['events'])+1)]
    require([row['path'] for row in q['events']]==list(map(str,expected)) and sorted(directory.glob('*.json'))==expected,'Current review event population changed')
    reg=read_json(q['registration']['path'],check_budget);head=read_json(q['head']['path'],check_budget)
    events=[read_json(row['path'],check_budget,ceiling=64*1024**2) for row in q['events']]
    require(current['registration']==reg and current['checkpoint']==head and current['events']==events,'Qualification snapshot is not the current full journal')
    cycle=next(e for e in reversed(events) if e['event']=='cycle')
    votes=[e for e in events if e['event']=='review' and e['cycle_id']==cycle['cycle_id']]
    require(len(votes)==3 and {e['role'] for e in votes}=={'physics_critic','skeptical_verifier','physics_decider'} and all(e['verdict']=='accept' and e['claim_scope']==scope for e in votes),'Exact initialized qualification role/scope acceptance required')
    accepted={str(Path(row['path']) if Path(row['path']).is_absolute() else root/row['path']):row['sha256'] for row in cycle['snapshots']}
    source={p['path']:p['sha256'] for p in d['sources']}
    for path,sha in ((q['result']['path'],q['result']['sha256']),
                     (d['inputs']['qualified_binary'],source[d['inputs']['qualified_binary']]),
                     (d['inputs']['qualified_wrapper_source'],source[d['inputs']['qualified_wrapper_source']])):
        require(accepted.get(path)==sha,'Exact initialized result/source/binary not accepted by this cycle')
    inventory=read_json(d['runtime_inventory']['path'],check_budget,ceiling=64*1024**2)
    require(all(accepted.get(row['path'])==row['sha256'] for row in inventory['files']),'Physical runtime differs from the accepted initialized witness')
    result=read_json(q['result']['path'],check_budget,ceiling=64*1024**2)
    require(result['status']=='passed' and result['successful_end_custody'] is True,'Initialized qualification did not finish successfully')
    expectations=d['plan']['qualification_expectations']
    if scope==QUALIFICATION_SCOPE:
        require(result['planned_native_counts']==plans.required(expectations,'native_counts'),'supplied qualification population differs')
    else:
        require(result['scope']==RETAINED_QUALIFICATION_SCOPE and
                result['new_native_counts']==dict(compiles=0,shower_calls=0,shower_exposures=0,new_hard_events=0,
                    detectors=0,conversions=0,analyses=0,fits=0,retries=0),'Retained qualification route/counts differ')
        require(result['original_resource_contract_satisfied'] is False and result['original_result_rewritten'] is False
                and result['origin']['original_scientific_status']=='failed' and
                result['origin']['original_controller_status']=='failed','Original failure must remain explicit')
        stages=plans.required(expectations,'stages')
        require([row['stage'] for row in result['commands']]==stages and all(row['returncode']==0 for row in result['commands']),'complete clean retained command witnesses required')
        transport_ids=plans.required(expectations,'transport_ids');events=plans.required(expectations,'events')
        require(set(result['transports'])==set(result['transport_comparisons'])==set(transport_ids) and all(row['status']=='content_verified' and row['original_events']==row['joined_events']==events for row in result['transports'].values()) and all(row['status']=='passed' for row in result['transport_comparisons'].values()),'complete supplied retained transport qualifications required')
    require(set(result['snapshots'])==set(result['pairs'])==set(plans.required(expectations,'arms')),'complete supplied initialized arms required')
    return {'cycle_id':cycle['cycle_id'],'result':q['result'],'binary_sha256':source[d['inputs']['qualified_binary']],'scope':scope,'journal_head':head}

def run(task,base,output_dir):
    start=time.monotonic();out=Path(output_dir).absolute()
    require('..' not in out.parts and not any(p.is_symlink() for p in (out,*out.parents)),'Owned nonsymlink output required')
    require(not out.exists() or out.is_dir() and not any(out.iterdir()),'Fresh empty paired output required')
    out.mkdir(parents=True,exist_ok=True)
    _,d,plan=document(task,base);r=d['resources']
    require(out.is_relative_to(Path(r['resource_root']).resolve()),'Output outside measured resource root')
    (out/'native-logs').mkdir();guard=native.Guard(r,out/'resource-telemetry.jsonl')
    deadline=start+r['max_seconds'];result={'status':'failed','scope':SCOPE,'physics_validated':False,'successful_end_custody':False,'commands':[],'planned_counts':plan['census'],'postprocessing':None,'active':'admission'}
    def save():
        result['elapsed_seconds']=time.monotonic()-start;plans.publish(out,d['plan'],result)
    def check_budget():require(time.monotonic()<deadline,'supplied paired scientific deadline exhausted')
    def keep_post(value):result['postprocessing']=value;save()
    save()
    try:
        before=input_snapshot(task,base);check_budget();guard.check()
        used=native.tree_usage(Path(r['resource_root']))['logical_bytes']
        require(native.shutil.disk_usage(r['resource_root']).free >= r['free_floor_bytes']+max(0,r['retained_bytes']-used)+r['headroom_bytes'],'Entry free space cannot cover remaining retention and cleanup reserve')
        result['qualification']=accepted_qualification(d,check_budget);save()
        for stage in plan['stages']:
            result['active']=stage['id'];save();check_budget()
            result['commands'].append(native.child(stage,out,d['environment'],deadline-native.CUSTODY_RESERVE_SECONDS,guard));save()
        result['active']='postprocessing';save()
        cards={a:d['inputs']['mpi_'+a+'_card'] for a in ('on','off')}
        post.finalize(out=out,stages=plan['stages'],binary=d['inputs']['qualified_binary'],
            compiled_source=d['inputs']['qualified_wrapper_source'],cards=cards,
            schema=read_json(d['schema']['path'],check_budget),expected_settings=d['settings'],
            expected_masses=d['masses'],expected_pin=d['expected_identities'],
            selection_sources=d['selection_sources'],signal_spec=d['signal_spec'],descriptor=d['plan']['intervention'],
            read_json=lambda p:read_json(p,check_budget),pin=lambda p:witness._read_pin(p,check_budget)[0],
            complete_receipt=witness.complete_receipt,settings_checks=checks,infer=estimator.infer,
            check_budget=check_budget,save=keep_post)
        result['active']='final_custody';save();check_budget()
        result['loader_census']=loaders.census(out,[s['id'] for s in plan['stages']],before,accepted_binary=d['inputs']['qualified_binary'],required_stages=d['plan']['loader_stages'],check_budget=check_budget);save()
        require(before==input_snapshot(task,base),'Paired source/runtime or acceptance journal changed')
        check_budget();result.update(status='passed',successful_end_custody=True,input_pins=before,active=None)
    except Exception as exc:result['error']={'type':type(exc).__name__,'message':str(exc)}
    # Include partial failed command identity as well as returned commands.
    result['commands']=[read_json(q) for s in plan['stages'] if (q:=out/'native-logs'/(s['id']+'.command.json')).is_file()]
    result['limits']=['Current supplied-cohort conditional intervention only; equivalence beyond the declared witness is unproven.',
        'Fixed-N empirical covariance and declared ratio/bootstrap estimators do not supply official-template covariance or statistical calibration.',
        'Whole-case sampled storage guard is not an instantaneous OS quota; common supervisor and outer controller own process cleanup.',
        'No regeneration, extension, optimizer, likelihood limit or automatic retry.']
    save()
    try:
        guard.check(final=True);check_budget()
    except Exception as exc:
        result.update(status='failed',successful_end_custody=False,postcondition_error={'type':type(exc).__name__,'message':str(exc)});save()
    return result
