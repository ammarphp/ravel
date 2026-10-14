"""Ordinary IRIS columnar analysis through existing science/native APIs.

Planning never imports ServiceX/ROOT/Awkward, reads credentials or submits a
query. The exact supplied query/analysis source, membership authority and native
runtime remain inputs; full native/service qualification is separate.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
from ravel.physics import dataset_query_quantities_core as core
from ravel.physics import model_tool_bridge as custody
from ravel.workflow.state_io import atomic_json

SCOPE=core.SCOPE
API=core.DATA/'servicex-api.json'


def validate(task):
    core.keys(task,('config',),'IRIS ordinary task');core.pin(task['config']);return task


def _load(task,base,capture):
    validate(task);p,raw=capture.read(task['config'],base)
    c=core.config(core.strict(raw));ds=core.dataset(capture.document(c['dataset'],p.parent))
    a=core.contract(capture.document(c['analysis'],p.parent))
    if a['source_filter']!=ds['source_filter']:raise ValueError('query and analysis source filters differ')
    core.original_domain(a,ds)
    if ds['prefix'] is not None and sum(m['events'] for d in ds['datasets'] for m in d['members'])>c['max_event_rows']:
        raise ValueError('complete declared source export exceeds declared event-row bound before query dispatch')
    capture.read(ds['membership_authority'],p.parent)
    if ds['prefix'] is not None:capture.read(ds['prefix']['source'],p.parent)
    capture.read(a['source_question'],p.parent)
    if c['remote_request'] is not None:
        prior=capture.document(c['remote_request']['intent'],p.parent)
        from ravel.physics.dataset_query_quantities_worker import query_identity
        if prior.get('query_identity')!=query_identity(c,ds,a) or prior.get('request_id')!=c['remote_request']['id']:
            raise ValueError('observation-only request must bind exact prior intent')
    returned=None
    if c['returned'] is not None:
        returned=core.returned(capture.document(c['returned'],p.parent),ds)
        if ds['prefix'] is not None and any(r['source_events'] is None or r['returned_events']!=r['source_events'] for r in returned['exposure'].values()):
            raise ValueError('prefix requires complete source return before prefix; reduced native return cannot satisfy it')
        if returned['origin']!='supplied_native_return':raise ValueError('supplied-file operation cannot claim a fresh remote submission')
    return p,c,ds,a,returned


def _ordinary(value,base,directory=False):
    return custody._regular(value,base,directory=directory)


def asset_check(assets):
    """Streaming leaf/descriptor bytes and ending current path observations."""
    from ravel.workflow.research_cycle import _ordinary
    for name, row in assets.items():
        core.pin(row)
        if row['path']!=name:raise ValueError('asset path declaration differs')
        p=_ordinary(Path(name));before=p.lstat()
        ident=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            opened=os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or ident(opened)!=ident(before) or opened.st_size!=row['size']:
                raise ValueError('native asset descriptor identity differs')
            h=hashlib.sha256();count=0
            while True:
                chunk=os.read(fd,1024**2)
                if not chunk:break
                count+=len(chunk);h.update(chunk)
                if count>row['size']:raise ValueError('native asset grew during consumption')
            if ident(os.fstat(fd))!=ident(before) or ident(_ordinary(p).lstat())!=ident(before) or count!=row['size'] or h.hexdigest()!=row['sha256']:
                raise ValueError('native asset bytes/current identity differ')
        finally:os.close(fd)


def closed_assets(assets, roots):
    """Finite ending membership/leaf checks; no continuous filesystem lock."""
    def membership():
        for root in roots:
            p=_ordinary(root,Path.cwd(),directory=True)
            members=list(p.rglob('*'))
            if any(q.is_symlink() or not (q.is_file() or q.is_dir()) for q in members):raise ValueError('native source tree has a nonordinary member')
            expected={n for n in assets if Path(n).is_relative_to(p)}
            if {str(q) for q in members if q.is_file()}!=expected:raise ValueError('complete native source membership differs')
    membership();asset_check(assets);membership()


def runtime(c,base,capture):
    rt=c['runtime'];assets={};roots=[];total=0
    for declaration in rt['trees']:
        root=_ordinary(declaration['root'],base,directory=True)
        if any(root==r or root.is_relative_to(r) or r.is_relative_to(root) for r in roots):raise ValueError('disjoint native runtime trees required')
        roots.append(root);manifest=capture.document(declaration['manifest'],base)
        core.keys(manifest,('schema_version','files'),'full runtime manifest')
        if type(manifest['schema_version']) is not int or manifest['schema_version']!=1 or type(manifest['files']) is not dict or not manifest['files']:
            raise ValueError('complete runtime manifest1 required')
        actual=set()
        for q in root.rglob('*'):
            if q.is_symlink() or not (q.is_file() or q.is_dir()):raise ValueError('native runtime member is aliased/nonordinary')
            if q.is_file():actual.add(q.relative_to(root).as_posix())
        if actual!=set(manifest['files']):raise ValueError('full native runtime membership changed')
        for rel,row in manifest['files'].items():
            if Path(rel).is_absolute() or '..' in Path(rel).parts:raise ValueError('literal relative runtime member required')
            core.keys(row,('sha256','size'),'runtime member')
            q=root/rel;assets[str(q)]={'path':str(q),**row};core.pin(assets[str(q)])
            total+=row['size']
    if len(assets)>20000 or total>4*1024**3:raise ValueError('complete runtime exceeds20k/4GiB finite admission')
    sites=[_ordinary(s,base,directory=True) for s in rt['site_roots']]
    if len(set(sites))!=len(sites) or any(not any(s==r or s.is_relative_to(r) for r in roots) for s in sites):
        raise ValueError('native site roots outside complete captured runtime')
    api=core.strict(API.read_bytes())
    packages=[s/'servicex' for s in sites if (s/'servicex').is_dir()]
    if len(packages)!=1:raise ValueError('exactly one pinned ServiceX package required')
    for rel,sha in api['required_package_files'].items():
        q=str(packages[0]/rel)
        if q not in assets or assets[q]['sha256']!=sha:raise ValueError('frontend source differs from inspected3.3.1 API')
    python,_=capture.read(rt['python'],base,limit=64*1024**2)
    if not os.access(python,os.X_OK):raise ValueError('explicit executable native interpreter required')
    assets[str(python)]={**rt['python'],'path':str(python)}
    asset_check(assets)
    # Repeat complete membership after content validation, not just before it.
    for root,declaration in zip(roots,rt['trees']):
        doc=capture.document(declaration['manifest'],base)
        actual={q.relative_to(root).as_posix() for q in root.rglob('*') if q.is_file()}
        if any(q.is_symlink() for q in root.rglob('*')) or actual!=set(doc['files']):raise ValueError('ending runtime membership changed')
    return assets,sites,python


def bundle(c,base,capture):
    result={}
    for rel,declaration in c['bundle']['files'].items():
        path,raw=capture.read(declaration,base)
        result[rel]=(path,raw)
    return result


def inputs(task,base):
    capture=core.Capture();p,c,ds,a,ret=_load(task,base,capture)
    assets,_,_=runtime(c,p.parent,capture);bundle(c,p.parent,capture)
    if ret is not None:
        native={}
        for row in ret['files']:
            q=_ordinary(row['pin']['path'],p.parent)
            native[str(q)]={**row['pin'],'path':str(q)}
        asset_check(native);assets.update(native)
    capture.finish()
    return sorted({*capture.rows,*map(Path,assets),API})


def execution_seconds(task,base):
    capture=core.Capture();c=_load(task,base,capture)[1];capture.finish();return c['max_seconds']


def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{});scopes=policy.get('claim_scopes',{})
    if spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or policy.get('max_redos')!=0 or set(scopes)!={SCOPE} or scopes[SCOPE].get('actions')!=['delivery']:
        raise ValueError('IRIS requires one-attempt ordinary delivery-only scope, no automatic remote resubmit')
    return spec


def _approved(task,out):
    from ravel.workflow import science
    for rd in (out,*out.parents):
        if (rd/'inputs/science-plan.json').is_file():
            plan=science.verify_worker(rd);spec=science.execution_spec(rd);validate_scope(spec)
            if spec['mode']!='dataset-query-quantities' or spec['task']!=task or out!=(rd/plan['output_directory']/'dataset-query-quantities').absolute():raise ValueError('selected ordinary IRIS worker differs')
            return rd,plan
    raise ValueError('actual approved ordinary IRIS worker required')


def _census(out):
    result={}
    for p in out.rglob('*'):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):raise ValueError('nonordinary IRIS output')
        if p.is_file():result[str(p.relative_to(out))]={'sha256':custody._hash(p),'size':p.stat().st_size}
    return result


def run(task,base,output):
    out=Path(output).absolute();rd,plan=_approved(task,out)
    capture=core.Capture();p,c,ds,a,ret=_load(task,base,capture)
    if c['max_seconds']>plan['max_seconds']:raise ValueError('native budget exceeds approved scientific task')
    before={str(q):custody._hash(q) for q in inputs(task,base)}
    assets,sites,python=runtime(c,p.parent,capture);sources=bundle(c,p.parent,capture);capture.finish()
    if out.exists() or any(q.is_symlink() for q in (out,*out.parents)):raise ValueError('fresh ordinary output required')
    out.mkdir(parents=True);native=out/'native';native.mkdir();source=native/'source';source.mkdir()
    for rel,(_,raw) in sources.items():
        q=source/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw)
        assets[str(q)]={'path':str(q),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    driver_raw=Path(__file__).with_name('dataset_query_quantities_worker.py').read_bytes();driver=native/'driver.py';driver.write_bytes(driver_raw)
    assets[str(driver)]={'path':str(driver),'sha256':hashlib.sha256(driver_raw).hexdigest(),'size':len(driver_raw)}
    # Existing source identity binds the whole Ravel package. Retain each file
    # used by the isolated helper at the same exact epoch, not a live transplant.
    package=Path(__file__).parents[2]
    for q in package.rglob('*'):
        if q.is_symlink():raise ValueError('Ravel helper source traverses an alias')
        if q.is_file():
            assets[str(q)]={'path':str(q),'sha256':custody._hash(q),'size':q.stat().st_size}
    private=rd/'work'/('iris-private-'+out.parent.name)
    if private.exists():raise ValueError('existing private attempt forbids implicit cache/remote retry')
    private.parent.mkdir(parents=True,exist_ok=True)
    _ordinary(private.parent,rd,directory=True)
    # Relative supplied return/intent paths must retain their original meaning.
    if ret is not None:
        ret={**ret,'files':[{**r,'pin':{**r['pin'],'path':str(_ordinary(r['pin']['path'],p.parent))}} for r in ret['files']]}
    c={**c,'runtime':{**c['runtime'],'site_roots':[str(s) for s in sites]}}
    if c['remote_request'] is not None:
        c={**c,'remote_request':{**c['remote_request'],'intent':{**c['remote_request']['intent'],'path':str(_ordinary(c['remote_request']['intent']['path'],p.parent))}}}
    request={'config':c,'dataset':ds,'analysis':a,'returned':ret,'bundle_directory':str(source),'private_directory':str(private),
        'output':str(native),'source_root':str(package),'runtime_assets':assets,'closed_roots':[str(package),str(source),*[str(_ordinary(t['root'],p.parent,directory=True)) for t in c['runtime']['trees']]],'driver_sha256':assets[str(driver)]['sha256']}
    req=native/'request.json';atomic_json(req,request);req_sha=custody._hash(req)
    closed_assets(assets,request['closed_roots']);errors=[];receipt=None;raw=None;delivered=None
    from ravel.physics.reinterpret_db import execute_native
    try:receipt=execute_native([str(python),'-I','-B',str(driver),str(req),req_sha],native,c)
    except (OSError,ValueError,RuntimeError) as exc:errors.append('native_owner_'+type(exc).__name__)
    raw=_census(native);atomic_json(out/'raw-census.json',{'files':raw,'before_adjudication':True,'private_cache_not_public_evidence':True})
    try:
        delivered=core.strict((native/'native-result.json').read_bytes())
        if delivered['status']!='passed' or delivered['physics_validated'] is not False:raise ValueError('native postcondition failed')
        if c['operation']=='observe_existing_remote_request':
            if delivered['remote']['submit_method_invocations']!=0:raise ValueError('observation operation attempted submission')
        else:
            rows=core.strict((native/'native-event-export.json').read_bytes())
            # Adjudication must bind the exact parent-side source population.
            if delivered['delivery']['full_returned_events']!=len(rows):raise ValueError('native full event census differs')
            mapped=core.returned(core.strict((native/'returned-manifest.json').read_bytes()),ds)
            if ret is not None and mapped!=ret:raise ValueError('supplied native return manifest changed')
            returned_assets={}
            for row in mapped['files']:
                q=_ordinary(row['pin']['path'],p.parent)
                if ret is None and not q.is_relative_to(native/'returned'):raise ValueError('fresh returned file outside retained native delivery')
                returned_assets[str(q)]={**row['pin'],'path':str(q)}
            asset_check(returned_assets)
            core.native_population(delivered['delivery']['native_row_census'],mapped,rows)
            checked=core.analyze(a,ds,mapped,rows,max_rows=c['max_event_rows'],max_products=c['max_group_products'])
            for key,value in checked.items():
                if delivered['delivery'].get(key)!=value:raise ValueError('native quantity projection differs from source-bound parent check')
    except (OSError,ValueError,KeyError,TypeError) as exc:errors.append('delivery_'+type(exc).__name__)
    try:
        closed_assets(assets,request['closed_roots'])
        if custody._hash(req)!=req_sha or before!={str(q):custody._hash(q) for q in inputs(task,base)}:raise ValueError('input/runtime/source ending commitment changed')
        if _census(native)!=raw:raise ValueError('native outputs changed after adjudication')
    except (OSError,ValueError,KeyError,TypeError) as exc:errors.append('ending_custody_'+type(exc).__name__)
    result={'status':'failed' if errors else 'passed','kind':'dataset-query-quantities-delivery','status_scope':SCOPE,'physics_validated':False,
        'operation':c['operation'],'task_id':a['task_id'],'analysis':a,'dataset_sha256':core.digest(ds),'native_execution':receipt,
        'delivery':None if delivered is None else delivered.get('delivery'),'remote':None if delivered is None else delivered.get('remote'),
        'errors':errors,'remote_cost':None,'automatic_resubmit_allowed':False,'credential_values_disclosed':False,
        'native_runtime_qualified':False,'data_or_service_qualified':False,
        'limitations':['Complete explicit FileList is not independent proof of DID membership; the supplied authority and exposure remain premises.',
            'Member and source-entry order is explicit; async completion order is never used for source-defined prefixes.',
            'Raw unweighted comparator metrics are separate from signed weighted histogram quantities.',
            'Poissonized independent-group moments are conditional MC moments, not detector/SF/theory/integration calibration.',
            'SDK cache and unfiltered native logs are private. Safe public API observations do not establish remote containment or actual HTTP job count.',
            'Cancellation acknowledgment is not terminal observation; unknown remote cost/status prevents automatic duplicate dispatch.',
            'Pinned frontend3.3.1 is a prospective dependency; original IRIS container/runtime equivalence remains unknown.']}
    if sum(r['size'] for r in _census(out).values())>c['max_output_bytes']:result['status']='failed';result['errors'].append('whole_output_byte_bound')
    atomic_json(out/'dataset-query-quantities.json',result)
    if sum(r['size'] for r in _census(out).values())>c['max_output_bytes']:
        result['status']='failed';result['errors'].append('final_whole_output_byte_bound');atomic_json(out/'dataset-query-quantities.json',result)
    return result


def context_inputs(task,base):
    capture=core.Capture();p,c,ds,a,_=_load(task,base,capture);bundle(c,p.parent,capture);capture.finish()
    return sorted({*capture.rows,API})


def context(task,base):
    capture=core.Capture();_,c,ds,a,ret=_load(task,base,capture);capture.finish()
    return {'schema_version':1,'mode':'dataset-query-quantities','operation':c['operation'],'analysis':a,'dataset':ds,
        'runtime_requirements':{'backend':c['runtime']['backend'],'versions':c['runtime']['versions']},
        'service':None if c['service'] is None else {k:v for k,v in c['service'].items() if k!='credential_reference'},
        'credential_reference_required':c['service'] is not None and c['service']['credential_reference'] is not None,
        'supplied_population':{'datasets':a['event_domain']['datasets'],'observables':[o['id'] for o in a['observables']]},
        'returned_file_count':None if ret is None else len(ret['files']),
        'execution_authorized':False,'physics_validated':False,'automatic_resubmit_allowed':False,
        'dependency_pins':[{'path':str(q),'sha256':custody._hash(q),'size':q.stat().st_size} for q in context_inputs(task,base)]}


def specification(task, *, source, assumptions, actors, max_seconds, approval_mode='physicist'):
    """Return an ordinary unapproved specification with actual caller actors.

    This does not create a run, approval, vote or query. Actor strings are
    declared identities, not authentication. Root/caller keeps dispatch control.
    """
    validate(task)
    core.keys(actors,('proposer','executor','physics_critic','skeptical_verifier','physics_decider'),'actual review actors')
    for actor in actors.values():core.text(actor,'actual reviewer actor')
    value={'schema_version':2,'mode':'dataset-query-quantities','source':source,'assumptions':assumptions,
        'max_seconds':max_seconds,'max_attempts':1,'approval_mode':approval_mode,'task':task,
        'review_policy':{'schema_version':1,'policy':{'schema_version':1,'actors':actors,'max_redos':0,
            'allowed_changed_paths':[],'allowed_stages':['science'],
            'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'complete_population','kind':'scientific'},{'id':'weighted_quantities','kind':'scientific'}],
            'claim_scopes':{SCOPE:{'checks':['integrity','complete_population','weighted_quantities'],'actions':['delivery']}}},
            'correction_contract':{'task_fields':[],'input_slots':[]}}}
    from ravel.workflow import science
    science.validate(value)
    return value


def write_report(result,out, *, figures=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    lines=['# IRIS columnar delivery','', 'Status: '+result['status']+'. Scientific validity and native/service qualification remain unestablished.','',
        'Task: '+result['task_id']+'. Operation: '+result['operation']+'.','',
        'The complete native exposure, grouped signed quantities and raw unweighted metrics are retained in the JSON table. Unknowns stay explicit.','']
    delivery=result.get('delivery')
    if delivery is not None:
        lines+=['| Observable | Raw fills | Selected events | Metric denominator events | Raw entries/event |','|---|---:|---:|---:|---:|']
        for name,row in delivery['raw_unweighted_metrics'].items():
            lines.append('| '+name+' | '+str(row['entries'])+' | '+str(row['selected_events'])+' | '+str(row['metric_denominator_events'])+' | '+str(row['avg_entries_per_event'])+' |')
    for figure in figures or []:
        lines+=['','![Source-unqualified '+figure['kind']+']('+figure['stem']+'.png)',
                '[Vector PDF]('+figure['stem']+'.pdf). Declared units and grouped MC errors; no physics qualification.']
    lines+=['','Remote cost: unknown. Cancellation ACK and observed terminal state are distinct.','',*result['limitations']]
    (out/'dataset-query-quantities-report.md').write_text('\n'.join(lines)+'\n')
    atomic_json(out/'dataset-query-quantities-table.json',{'delivery':delivery,'remote':result.get('remote'),'physics_validated':False})
    return [{'stem':'dataset-query-quantities-report','files':['dataset-query-quantities-report.md','dataset-query-quantities-table.json'],'normalization':'Full declared population; original signed weight, per-observable units and normalization retained'}]


def main(argv=None):
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='action',required=True)
    population_parser=sub.add_parser('population',help='inspect a supplied analysis population; no query')
    population_parser.add_argument('--analysis',type=Path,required=True)
    context_parser=sub.add_parser('context',help=core.context_description())
    context_parser.add_argument('--task',type=Path,required=True);context_parser.add_argument('--output',type=Path,required=True)
    args=ap.parse_args(argv)
    if args.action=='population':
        from ravel.workflow.research_cycle import _bounded_source_snapshot
        _,raw=_bounded_source_snapshot(args.analysis.absolute(),core.MAX_DOCUMENT)
        analysis=core.contract(core.strict(raw))
        print(json.dumps({'event_domain':analysis['event_domain'],'observables':analysis['observables']},sort_keys=True));return 0
    from ravel.workflow.research_cycle import _bounded_source_snapshot
    path,raw=_bounded_source_snapshot(args.task.absolute(),core.MAX_DOCUMENT)
    value=context(core.strict(raw),path.parent)
    if args.output.exists() or any(p.is_symlink() for p in (args.output,*args.output.parents)):raise ValueError('fresh regular context output required')
    args.output.parent.mkdir(parents=True,exist_ok=True);atomic_json(args.output,value);return 0


if __name__=='__main__':raise SystemExit(main())
