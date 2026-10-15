"""Original EasyScan CLI, under the ordinary scientific lifecycle.

Cold preparation authenticates source/configuration without importing EasyScan,
NumPy, sampler libraries or any external physics engine. A native result is a
scoped raw delivery, never convergence, posterior or physical qualification.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
from ravel.physics import parameter_space_sampling_core as core
from ravel.physics import dataset_query_quantities as integrity
from ravel.workflow.state_io import atomic_json

API=core.API;SCOPE=core.SCOPE
# Source-interface extension point for additional native samplers.
SAMPLER_OUTPUTS={
    'RANDOM': ('ScanResult.txt',),
    'GRID': ('ScanResult.txt',),
    'BESTFIT': ('ScanResult.txt',),
    'ONEPOINT': ('ScanResult.txt',),
    'MCMC': ('ScanResult.txt','All_ScanResult.txt'),
    'EMCEE': ('ScanResult.txt','All_ScanResult.txt','EMCEEChain.txt'),
    'DYNESTY': ('ScanResult.txt','DynestySamples.txt'),
    'MULTINEST': ('ScanResult.txt','stats.dat'),
}


def context_source_hashes(hash_file):
    """Graph source commitment seam; supplied contracts replace stored questions."""
    return {'parameter-space-sampling.api': hash_file(API)}


def validate(task):
    core.keys(task,('config',),'EasyScan ordinary task');core.pin(task['config']);return dict(task)


def _members(root):
    p=integrity._ordinary(root,Path.cwd(),directory=True);result={}
    for q in sorted(p.rglob('*')):
        if q.is_symlink() or not (q.is_file() or q.is_dir()):raise ValueError('closed tree contains a nonordinary member')
        if q.is_file():result[q.relative_to(p).as_posix()]=q
    return result


def tree(declaration,base,capture, *, released=False):
    root=integrity._ordinary(declaration['root'],base,directory=True)
    manifest=capture.document(declaration['manifest'],base)
    core.keys(manifest,('schema_version','files'),'complete source tree')
    if type(manifest['schema_version']) is not int or manifest['schema_version']!=1 or type(manifest['files']) is not dict or not manifest['files']:raise ValueError('complete source tree1 required')
    if len(manifest['files'])>20000:raise ValueError('complete tree exceeds20k member limit')
    assets={};total=0
    if released:
        expected=core.strict(API.read_bytes())['files']
        if {k:{x:v[x] for x in ('sha256','size')} for k,v in manifest['files'].items()}!=expected:raise ValueError('original released EasyScan source differs')
    for rel,row in manifest['files'].items():
        core.relative(rel);core.keys(row,('sha256','size','mode'),'source member')
        core.integer(row['mode'],0,0o777,'ordinary file permissions')
        q=root/rel;assets[str(q)]={'path':str(q),'sha256':row['sha256'],'size':row['size']};core.pin(assets[str(q)])
        if row['size']>64*1024**2:raise ValueError('source member exceeds64MiB')
        total+=row['size']
        if total>4*1024**3:raise ValueError('source tree exceeds4GiB')
        if q.stat().st_mode&0o777!=row['mode']:raise ValueError('source executable permission differs')
    integrity.closed_assets(assets,[root])
    return root,manifest,assets


def _load(task,base,capture, *, trees=True):
    validate(task);p,raw=capture.read(task['config'],base)
    c=core.config(core.strict(raw));capture.read(c['question'],p.parent)
    _,iraw=capture.read(c['ini'],p.parent)
    info=core.ini(iraw,c)
    if trees:
        fr,_,fa=tree(c['framework'],p.parent,capture,released=True)
        wr,_,wa=tree(c['workspace'],p.parent,capture)
        if fr==wr or fr.is_relative_to(wr) or wr.is_relative_to(fr):raise ValueError('disjoint framework and mutable workspace required')
        existing=_members(wr)
        mutable={q for prog in c['programmes'] for q in [*prog['inputs'],*prog['outputs'],*prog['intermediates'],*prog['mutable_paths']]}
        code_suffixes={'.py','.sh','.so','.dylib','.a','.o','.exe','.dll'}
        if any(Path(q).suffix.lower() in code_suffixes or q in existing and existing[q].stat().st_mode&0o111 for q in mutable):raise ValueError('native executable/source code cannot be declared mutable card/output')
        if info['result_folder'] in existing or (wr/info['result_folder']).exists():raise ValueError('original result path must be fresh; explicit continuation is separate')
        if info['workers']>1 and any((wr/('p'+str(i)+'_'+info['parallel_folder'])).exists() for i in range(info['workers'])):raise ValueError('preexisting native worker directories refused')
        for prog in c['programmes']:
            d=info['projection'][prog['section']];com=d.get('Command path','').rstrip('/') or '.'
            if not (wr/com).is_dir():raise ValueError('supplied native command directory missing')
            if info['workers']>1 and (not (com==info['parallel_folder'] or com.startswith(info['parallel_folder']+'/')) or any(not f.startswith(info['parallel_folder']+'/') for f in [*prog['inputs'],*prog['outputs'],*prog['intermediates'],*prog['mutable_paths']])):raise ValueError('complete parallel programme population must live inside isolated source tree')
            # Input may be produced by an earlier programme, so its absence is
            # distinguished from a missing initial source input.
            prior=[q for previous in c['programmes'][:c['programmes'].index(prog)] for q in [*previous['outputs'],*previous['intermediates']]]
            if any(f not in existing and f not in prior for f in prog['inputs']):raise ValueError('initial native input member missing')
        if sum(v['size'] for v in [*fa.values(),*wa.values()])*(info['workers'] if info['workers']>1 else 1)>c['resources']['max_copy_bytes']:raise ValueError('complete native source/worker copies exceed declared bound')
    if c['operation']=='continue-native':
        previous=capture.document(c['continuation'],p.parent)
        core.keys(previous,('schema_version','config_identity','runtime_identity','method','root','files'),'immutable native continuation')
        if previous['schema_version']!=1 or previous['method']!='MCMC' or previous['config_identity']!=identity(c,info) or previous['runtime_identity']!=core.digest(c['runtime']):raise ValueError('continuation configuration/runtime differs')
        if type(previous['files']) is not dict or not {'ScanResult.txt','All_ScanResult.txt'}.issubset(previous['files']):raise ValueError('complete predecessor native tables required')
        previous_root=integrity._ordinary(previous['root'],p.parent,directory=True)
        if set(_members(previous_root))!=set(previous['files']):raise ValueError('complete immutable predecessor population differs')
        for rel,row in previous['files'].items():
            core.relative(rel);q,_=capture.read(row,p.parent,limit=64*1024**2)
            if q!=previous_root/rel:raise ValueError('predecessor file identity/path differs')
        if set(_members(previous_root))!=set(previous['files']):raise ValueError('ending immutable predecessor population differs')
        core.table(capture.read(previous['files']['ScanResult.txt'],p.parent,limit=64*1024**2)[1])
    if c['operation']=='read-returned':
        ret=capture.document(c['returned'],p.parent)
        core.keys(ret,('schema_version','config_identity','runtime_identity','root','files','observation'),'complete original native return')
        if ret['schema_version']!=1 or ret['config_identity']!=identity(c,info) or ret['runtime_identity']!=core.digest(c['runtime']):raise ValueError('returned original protocol/runtime differs')
        if type(ret['files']) is not dict or not ret['files']:raise ValueError('complete returned member census required')
        return_root=integrity._ordinary(ret['root'],p.parent,directory=True)
        if set(_members(return_root))!=set(ret['files']):raise ValueError('complete returned member population differs')
        total=0
        for rel,row in ret['files'].items():
            core.relative(rel);q,_=capture.read(row,p.parent,limit=64*1024**2)
            if q!=return_root/rel:raise ValueError('returned member identity/path differs')
            total+=row['size']
        if len(ret['files'])>c['resources']['max_output_members'] or total>c['resources']['max_output_bytes']:raise ValueError('complete returned population exceeds declared resources')
        if set(_members(return_root))!=set(ret['files']):raise ValueError('ending returned member population differs')
    return p,c,info


def identity(c,info):
    # Count/seed/bounds/commands/plots and complete source/workspace pins remain;
    # operation, transport pathname and outer resource ceilings are separate.
    return core.digest({'task':c['study_id'],'question':c['question']['sha256'],'ini':info['projection'],'framework':c['framework']['manifest']['sha256'],'workspace':c['workspace']['manifest']['sha256'],'programmes':c['programmes'],'report':c['report']})


def runtime(c,base,capture):
    if c['runtime'] is None:raise core.ScanInputError('runtime inputs')
    rt=c['runtime'];assets={};roots=[]
    for row in rt['trees']:
        root,_,members=tree(row,base,capture)
        if any(root==r or root.is_relative_to(r) or r.is_relative_to(root) for r in roots):raise ValueError('disjoint captured runtime trees required')
        assets.update(members);roots.append(root)
    if len(assets)>20000 or sum(v['size'] for v in assets.values())>4*1024**3:raise ValueError('complete native runtime exceeds20k/4GiB')
    sites=[integrity._ordinary(p,base,directory=True) for p in rt['site_roots']]
    if len(set(sites))!=len(sites) or any(not any(s==r or s.is_relative_to(r) for r in roots) for s in sites):raise ValueError('native site path outside complete runtime')
    python,_=capture.read(rt['python'],base,limit=64*1024**2)
    if not os.access(python,os.X_OK):raise ValueError('explicit executable Python required')
    assets[str(python)]={**rt['python'],'path':str(python)}
    integrity.asset_check(assets)
    return python,sites,roots,assets


def context_inputs(task,base):
    cap=core.Capture();p,c,_=_load(task,base,cap,trees=False);cap.finish()
    return sorted({*cap.rows,API})


def context(task,base):
    cap=core.Capture();p,c,info=_load(task,base,cap,trees=False);cap.finish()
    return {'schema_version':1,'mode':'parameter-space-sampling','operation':c['operation'],'study_id':c['study_id'],
        'native_configuration':info,'programmes':c['programmes'],'resources':c['resources'],
        'runtime_requirements':None if c['runtime'] is None else c['runtime']['versions'],
        'report':c['report'],'source_api':core.strict(API.read_bytes()),
        'dependency_pins':list(cap.rows.values()),'missing_runtime':c['runtime'] is None,
        'execution_authorized':False,'physics_validated':False,'native_algorithms_reimplemented':False,
        'limitations':['Cold context parses mappings; full source/runtime membership is checked by ordinary plan, then again around dispatch.',
            'Input intervals, external library versions, units and engine scientific conventions are source premises, not independently validated.',
            'RNG seeding is only the released Python random field; complete sampler/parallel determinism is unestablished.',
            'Native MCMC continuation restores only its final row in a private predecessor copy; no RNG checkpoint.']}


def inputs(task,base):
    cap=core.Capture();p,c,info=_load(task,base,cap)
    fr,_,fa=tree(c['framework'],p.parent,cap,released=True);wr,_,wa=tree(c['workspace'],p.parent,cap)
    _,_,_,ra=runtime(c,p.parent,cap)
    cap.finish();return sorted({*cap.rows,*map(Path,fa),*map(Path,wa),*map(Path,ra),API})


def execution_seconds(task,base):
    cap=core.Capture();_,c,_=_load(task,base,cap,trees=False);cap.finish();return c['resources']['max_seconds']


def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{})
    if spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or policy.get('max_redos')!=0 or set(policy.get('claim_scopes',{}))!={SCOPE} or policy['claim_scopes'][SCOPE]['actions']!=['delivery']:raise ValueError('EasyScan requires one-attempt ordinary delivery-only scope')
    return spec


def specification(task, *, source, assumptions, actors, max_seconds, approval_mode='physicist'):
    validate(task);core.keys(actors,('proposer','executor','physics_critic','skeptical_verifier','physics_decider'),'actual role actors')
    for a in actors.values():core.text(a,'declared actual actor')
    checks=[{'id':'integrity','kind':'integrity'},{'id':'complete_population','kind':'scientific'},{'id':'native_semantics','kind':'scientific'}]
    result={'schema_version':2,'mode':'parameter-space-sampling','source':source,'assumptions':assumptions,'task':task,'approval_mode':approval_mode,'max_attempts':1,'max_seconds':max_seconds,
        'review_policy':{'schema_version':1,'policy':{'schema_version':1,'actors':actors,'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':checks,'claim_scopes':{SCOPE:{'checks':[v['id'] for v in checks],'actions':['delivery']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}}
    from ravel.workflow import science
    science.validate(result);return result


def _approved(task,out):
    from ravel.workflow import science
    for rd in (out,*out.parents):
        if (rd/'inputs/science-plan.json').is_file():
            plan=science.verify_worker(rd);spec=science.execution_spec(rd);validate_scope(spec)
            if spec['mode']!='parameter-space-sampling' or spec['task']!=task or out!=(rd/plan['output_directory']/'parameter-space-sampling').absolute():raise ValueError('ordinary selected EasyScan worker differs')
            return rd,plan
    raise ValueError('approved ordinary EasyScan worker required')


def _copy_tree(declaration,base,capture,destination, *, released=False):
    root,manifest,assets=tree(declaration,base,capture,released=released)
    destination.mkdir(parents=True,exist_ok=False)
    for rel,row in manifest['files'].items():
        _,raw=capture.read(assets[str(root/rel)],base,limit=64*1024**2)
        q=destination/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw);q.chmod(row['mode'])
        if q.read_bytes()!=raw:raise ValueError('staged source does not match consumed admitted bytes')
    integrity.closed_assets(assets,[root]);return manifest


def census(root,maximum,member_limit):
    members=_members(root);result={};total=0
    if len(members)>member_limit:raise ValueError('complete output member bound exceeded')
    for rel,q in members.items():
        before=q.stat();total+=before.st_size
        if total>maximum:raise ValueError('whole retained output byte bound exceeded')
        sha=integrity.custody._hash(q)
        result[rel]={'sha256':sha,'size':before.st_size}
    integrity.asset_check({str(Path(root)/r):{'path':str(Path(root)/r),**v} for r,v in result.items()})
    if set(_members(root))!=set(result):raise ValueError('ending output population differs')
    return result


def project(c,info,files,read,observation):
    tables={};figures=[];issues=[]
    for rel in files:
        name=Path(rel).name
        if name in ('ScanResult.txt','All_ScanResult.txt','EMCEEChain.txt','DynestySamples.txt','Previous_ScanResult.txt'):
            if files[rel]['size']>64*1024**2:raise ValueError('native table exceeds64MiB reader bound')
            tables[rel]=core.table(read(rel))
            if tables[rel]['malformed_rows'] or any(r['status']=='blank' for r in tables[rel]['rows']):issues.append('malformed_table:'+rel)
        if rel.startswith(info['result_folder']+'/Figures/') and name.endswith(('.png','.pdf','.svg')):figures.append(rel)
    result_prefix=info['result_folder']+'/'
    required=[result_prefix+name for name in SAMPLER_OUTPUTS[info['method']]]
    missing=[r for r in required if r not in files]
    missing+=[result_prefix+'Figures/'+f for f in info['figures'] if result_prefix+'Figures/'+f not in files]
    if missing:issues.append('missing_native_outputs')
    if observation.get('status')!='completed':issues.append('native_observation_not_completed')
    counts=observation.get('counts',{})
    if info['method']=='RANDOM' and counts.get('evaluations')!=info['point_setting']:issues.append('complete_random_trial_population_differs')
    if info['method']=='GRID' and counts.get('evaluations')!=info['grid_population']:issues.append('complete_grid_population_differs')
    workers=observation.get('workers',[])
    if info['workers']>1 and (len(workers)!=info['workers'] or any(w.get('exitcode')!=0 for w in workers) or len({w.get('pid') for w in workers})!=len(workers)):issues.append('native_worker_exit_population_differs')
    samplers=observation.get('samplers',{})
    # CONTROLLER.setProgram applies auxfun.sortDic before scanner dispatch.
    sampled=sorted((p for p in info['parameters'] if p['prior']!='fixed'),key=lambda p:p['name'])
    if info['method'] in ('EMCEE','DYNESTY') and info['method'] not in samplers:issues.append('complete_native_sampler_arrays_missing')
    weights=None
    sampler_population=None
    def finite(v):return type(v) in (int,float) and __import__('math').isfinite(v)
    if info['method']=='BESTFIT':
        opt=observation.get('optimizer')
        if type(opt) is not dict or set(opt)!={'x','fun','success','message','nit','nfev'} or type(opt['x']) is not list or len(opt['x'])!=info['sampled_parameters'] or not all(finite(v) for v in opt['x']) or not finite(opt['fun']):issues.append('native_bestfit_complete_objective_result_missing')
    def same_native(v,parsed):
        if finite(v):return v==parsed['value']
        return type(v) is dict and set(v)=={'native_nonfinite'} and parsed['status']=='native_nonfinite' and str(v['native_nonfinite']).lower()==parsed['raw'].lower()
    if info['method']=='EMCEE' and 'EMCEE' in samplers:
        data=samplers['EMCEE'];chain=data.get('chain_unit_coordinates');logs=data.get('log_probability');accept=data.get('acceptance_fraction')
        steps=info['chain_slots']//info['walkers'];walkers=info['walkers'];dims=info['sampled_parameters']
        complete=type(chain) is list and len(chain)==steps and type(logs) is list and len(logs)==steps and type(accept) is list and len(accept)==walkers
        complete=complete and all(type(row) is list and len(row)==walkers and all(type(v) is list and len(v)==dims and all(finite(x) and 0<=x<=1 for x in v) for v in row) for row in chain)
        complete=complete and all(type(row) is list and len(row)==walkers and all(finite(v) or type(v) is dict and v.get('native_nonfinite') in ('-inf','inf','nan') for v in row) for row in logs) and all(finite(v) and 0<=v<=1 for v in accept)
        if not complete:issues.append('complete_emcee_array_dimensions_or_values_differ')
        else:
            flat_logs=[v for row in logs for v in row];flat_chain=[v for row in chain for v in row]
            finite_rows=[(u,v) for u,v in zip(flat_chain,flat_logs) if finite(v)];finite_logs=[v for _,v in finite_rows]
            sampler_population={'scheduled_slots':info['chain_slots'],'complete_slots':len(flat_logs),'finite_slots':len(finite_logs),'nonfinite_slots':len(flat_logs)-len(finite_logs),'written_finite_rows':None}
            t=tables.get(result_prefix+'EMCEEChain.txt')
            if t is not None:
                sampler_population['written_finite_rows']=len(t['rows'])
                captured=data.get('physical_chain_rows')
                if captured is None:
                    # Legacy supplied observations use the exact released
                    # Python scalar Prior law. No approximate comparison band.
                    try:physical=[[core.prior_coordinate(x,p) for x,p in zip(u,sampled)] for u,_ in finite_rows]
                    except (ValueError,OverflowError):physical=None
                else:
                    # Actual worker observes source Prior once at export, after
                    # sampler return. Preserve native scalar rounding and bind
                    # its full unit coordinates to the complete retained chain.
                    valid=type(captured) is list and len(captured)==len(finite_rows)
                    valid=valid and all(type(r) is dict and set(r)=={'unit_coordinates','physical_coordinates'} and type(r['unit_coordinates']) is list and len(r['unit_coordinates'])==dims and all(finite(x) for x in r['unit_coordinates']) and r['unit_coordinates']==u and type(r['physical_coordinates']) is list and len(r['physical_coordinates'])==dims and all(finite(x) for x in r['physical_coordinates']) for r,(u,_) in zip(captured,finite_rows))
                    physical=[r['physical_coordinates'] for r in captured] if valid else None
                if physical is None or t['columns']!=['log_probability',*[p['name'] for p in sampled]] or len(t['rows'])!=len(finite_rows) or any(len(r['fields'])!=dims+1 or not all(field['status']=='finite' and field['value']==v for field,v in zip(r['fields'],[logp,*coords])) for r,(_,logp),coords in zip(t['rows'],finite_rows,physical or [])):issues.append('native_finite_chain_and_complete_arrays_differ')
            if len(finite_logs)!=info['chain_slots']:issues.append('requested_finite_emcee_chain_shortened')
    if info['method']=='DYNESTY' and result_prefix+'DynestySamples.txt' in tables:
        t=tables[result_prefix+'DynestySamples.txt'];weights=core.dynesty_weights(t)
        if weights['status']!='diagnostic':issues.append('native_dynesty_weights_unavailable')
        data=samplers.get('DYNESTY',{});samples=data.get('samples');n=len(samples) if type(samples) is list else 0
        complete=n>0 and all(type(row) is list and len(row)==info['sampled_parameters'] and all(finite(v) for v in row) for row in samples)
        complete=complete and all(type(data.get(k)) is list and len(data[k])==n for k in ('logl','logwt','logz','logzerr','ncall'))
        if not complete or len(t['rows'])!=n or t['columns']!=['log_likelihood','log_weight','log_evidence',*[p['name'] for p in sampled]]:issues.append('complete_dynesty_array_population_differs')
        elif any(not all(same_native(v,p) for v,p in zip([data['logl'][i],data['logwt'][i],data['logz'][i],*samples[i]],r['fields'])) for i,r in enumerate(t['rows'])):issues.append('native_dynesty_table_and_complete_arrays_differ')
        sampler_population={'native_sample_rows':n,'written_rows':len(t['rows']),'live_point_setting':info['point_setting'],'run_nested_convergence_qualified':False}
    if info['method']=='MCMC' and info['workers']==1 and result_prefix+'ScanResult.txt' in tables and len(tables[result_prefix+'ScanResult.txt']['rows'])!=info['point_setting']:issues.append('native_mcmc_saved_population_differs')
    return {'tables':tables,'figures':figures,'missing_outputs':missing,'issues':issues,'observation':observation,'dynesty_weights':weights,'sampler_population':sampler_population,'native_initial_discrepancies':info['discrepancies'],
        'method_interpretation':core.strict(API.read_bytes())['methods'],
        'scientific_validity_unknown':True,'posterior_or_absolute_evidence_qualified':False}


def run(task,base,output):
    out=Path(output).absolute();rd,plan=_approved(task,out)
    cap=core.Capture();p,c,info=_load(task,base,cap)
    if c['resources']['max_seconds']>plan['max_seconds']:raise ValueError('native wall limit exceeds admitted task')
    before={str(q):integrity.custody._hash(q) for q in inputs(task,base)}
    python,sites,rt_roots,rt_assets=runtime(c,p.parent,cap)
    if out.exists() or any(q.is_symlink() for q in (out,*out.parents)):raise ValueError('fresh ordinary output required')
    out.mkdir(parents=True);native=out/'native';native.mkdir();work=native/'work'
    emitted=core.Emitted(out);staged=core.Emitted(out)
    framework=native/'framework';_copy_tree(c['framework'],p.parent,cap,framework,released=True)
    _copy_tree(c['workspace'],p.parent,cap,work)
    _,iraw=cap.read(c['ini'],p.parent);ini_path=work/'ravel-native.ini'
    if ini_path.exists():raise ValueError('reserved copied configuration path occupied')
    emitted.bytes(ini_path,iraw)
    previous=None;returned=None
    if c['continuation'] is not None:
        previous=cap.document(c['continuation'],p.parent);target=work/info['result_folder'];target.mkdir()
        for rel,row in previous['files'].items():
            _,raw=cap.read(row,p.parent,limit=64*1024**2);q=target/rel;staged.bytes(q,raw)
    if c['returned'] is not None:
        returned=cap.document(c['returned'],p.parent)
        for rel,row in returned['files'].items():
            _,raw=cap.read(row,p.parent,limit=64*1024**2);q=work/rel
            if q.exists():raise ValueError('returned files overlap admitted workspace')
            staged.bytes(q,raw)
    package=Path(__file__).parents[2];assets=dict(rt_assets)
    for root in (package,framework):
        for q in _members(root).values():assets[str(q)]={'path':str(q),'sha256':integrity.custody._hash(q),'size':q.stat().st_size}
    driver=native/'driver.py';raw=Path(__file__).with_name('parameter_space_sampling_worker.py').read_bytes();emitted.bytes(driver,raw)
    assets[str(driver)]={'path':str(driver),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    request={'schema_version':1,'config':c,'info':info,'ini':str(ini_path),'work':str(work),'framework':str(framework),'output':str(native),
        'source_root':str(package),'site_roots':[str(v) for v in sites],'assets':assets,'closed_roots':[str(package),str(framework),*map(str,rt_roots)],
        'initial_workspace':census(work,c['resources']['max_output_bytes'],c['resources']['max_output_members']),
        'initial_modes':{r:q.stat().st_mode&0o777 for r,q in _members(work).items()},
        'returned':returned,'config_identity':identity(c,info)}
    req=native/'request.json';req_sha=emitted.json(req,request,atomic_json)['sha256'];staged.finish();emitted.finish();cap.finish()
    errors=[];receipt=None
    from ravel.physics.reinterpret_db import execute_native
    try:receipt=execute_native([str(python),'-I','-B',str(driver),str(req),req_sha],native,c['resources'])
    except (ValueError,OSError,RuntimeError) as exc:errors.append('native_execution_'+type(exc).__name__)
    # All partial logs/tables/raw programme files remain in the failed attempt.
    raw=census(native,c['resources']['max_output_bytes'],c['resources']['max_output_members']);emitted.json(out/'raw-census.json',{'files':raw,'before_validation':True},atomic_json)
    delivery=None
    try:
        retained=core.Capture()
        def read_retained(root,rel,files):return retained.read({'path':str(root/rel),**files[rel]},root,limit=64*1024**2)[1]
        observation=core.strict(read_retained(native,'observation.json',raw))
        workspace=census(work,c['resources']['max_output_bytes'],c['resources']['max_output_members'])
        delivery=project(c,info,workspace,lambda r:read_retained(work,r,workspace),observation)
        retained.finish()
        if delivery['issues']:errors.extend(delivery['issues'])
        # Validate immutable staged members after both native return and reader.
        from ravel.physics.parameter_space_sampling_observer import check_workspace
        check_workspace(request)
        integrity.closed_assets(assets,request['closed_roots'])
        cap.finish()
        if before!={str(q):integrity.custody._hash(q) for q in inputs(task,base)} or integrity.custody._hash(req)!=req_sha or census(native,c['resources']['max_output_bytes'],c['resources']['max_output_members'])!=raw:raise ValueError('ending source/output commitment differs')
    except (ValueError,OSError,KeyError,TypeError) as exc:errors.append('ending_or_delivery_'+type(exc).__name__+': '+str(exc))
    result={'status':'failed' if errors else 'passed','kind':'original-parameter-space-sampling-delivery','status_scope':SCOPE,'physics_validated':False,
        'operation':c['operation'],'study_id':c['study_id'],'config_identity':identity(c,info),'runtime_identity':core.digest(c['runtime']),
        'report':c['report'],'native_configuration':info,'programme_contracts':c['programmes'],'resources':c['resources'],'native_execution':receipt,'delivery':delivery,'errors':errors,'raw_census':'raw-census.json',
        'limitations':['Original sampler and external-programme algorithms are unchanged. Delivery does not qualify engines, convergence or scientific interpretation.',
            'Native MCMC uses released acceptance/dwell conventions; Dynesty likelihood omits Gaussian normalization constants, so absolute evidence is unqualified.',
            'Python random seed is retained; complete NumPy/emcee/dynesty/parallel reproducibility is unknown.',
            'A wall/resource failure retains partial populations and does not claim requested sampler completion.',
            'Detached timed/Popen PROGRAM branch is refused before dispatch; arbitrary supplied command descendant containment still needs execution qualification.',
            'Native source and unit/version/initial-point discrepancies are retained. No automatic repair of physical input.']}
    emitted.json(out/'parameter-space-sampling.json',result,atomic_json)
    census(out,c['resources']['max_output_bytes'],c['resources']['max_output_members'])
    emitted.finish()
    return result


def write_report(result,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);d=result.get('delivery') or {}
    lines=['# Original EasyScan delivery','', 'Status: '+result['status']+'. Native/physics/convergence qualification remains pending.','',
        'Study: '+result['study_id']+'. Original method: '+result['native_configuration']['method']+'.','',
        'Raw programme calls, complete tables, saved files and sampler arrays remain in the attempt; invalid or missing outputs are explicit.','',
        '| Native table | Complete rows | Malformed rows | Nonfinite rows |','|---|---:|---|---|']
    for name,t in d.get('tables',{}).items():lines.append('| '+name+' | '+str(len(t['rows']))+' | '+str(t['malformed_rows'])+' | '+str(t['nonfinite_rows'])+' |')
    figs=[]
    for i,rel in enumerate(d.get('figures',[])):
        src=out/'parameter-space-sampling/native/work'/rel
        if not src.is_file() or src.is_symlink():raise ValueError('native figure referenced by report is unavailable')
        lines+=['','![Original EasyScan source-unqualified figure](parameter-space-sampling/native/work/'+rel+')']
        figs.append({'stem':'parameter-space-sampling/native/work/'+str(Path(rel).with_suffix('')),'files':['parameter-space-sampling/native/work/'+rel],'kind':'retained_original_native_plot','style_qualified':False})
    lines+=['','## Interpretation boundaries','',*result['limitations']]
    emitted=core.Emitted(out)
    emitted.bytes(out/'parameter-space-sampling-report.md',('\n'.join(lines)+'\n').encode('utf-8'));emitted.json(out/'parameter-space-sampling-table.json',d,atomic_json)
    selected=core.export_table(result,out,emitted)
    if 'resources' in result:census(out,result['resources']['max_output_bytes'],result['resources']['max_output_members'])
    emitted.finish()
    return {'status':'passed','selected_table':selected,'figures':figs,'tables':[{'stem':'parameter-space-sampling-report','files':['parameter-space-sampling-report.md','parameter-space-sampling-table.json',selected['file']],'normalization':'Native raw callback/chain/weighted populations separately retained; no fabricated weights/errors'}]}


def main(argv=None):
    import argparse
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='action',required=True)
    cp=sub.add_parser('context',help='inspect a supplied scan contract; no runtime imports');cp.add_argument('--task',type=Path,required=True);cp.add_argument('--output',type=Path,required=True)
    a=ap.parse_args(argv)
    from ravel.workflow.research_cycle import _bounded_source_snapshot
    p,raw=_bounded_source_snapshot(a.task.absolute(),8*1024**2);value=context(core.strict(raw),p.parent)
    if a.output.exists() or any(q.is_symlink() for q in (a.output,*a.output.parents)):raise ValueError('fresh ordinary context output required')
    a.output.parent.mkdir(parents=True,exist_ok=True);emitted=core.Emitted(a.output.parent);emitted.json(a.output,value,atomic_json);emitted.finish();return 0


if __name__=='__main__':raise SystemExit(main())
