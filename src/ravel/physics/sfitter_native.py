"""Ordinary native SFitter delivery, preserving the pinned top score.

Never imports SFitter/Torch in the planning/control process. The existing science
worker, supervisor, custody and review journal retain all authority boundaries.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from ravel.physics import model_tool_bridge as custody, sfitter_inputs, sfitter_results, sfitter_worker
from ravel.workflow.state_io import read_json, atomic_json

COMMIT='6072a79e0f132d61a927f11ed482a401b34f6e3f'
SCOPE='sfitter-native-delivery'
KINDS=('fit','fixed-vector-qualification')
RUNTIME_PACKAGES=('numpy','pandas','scipy','tables','torch','matplotlib','tqdm','PyYAML')


UPSTREAM_CENSUS_ENV = 'RAVEL_SFITTER_UPSTREAM_CENSUS'


def upstream_census_path():
    """The reviewed upstream source census: the packaged one, or RAVEL_SFITTER_UPSTREAM_CENSUS for a
    local snapshot of the same tree (a test fixture whose prose has been generalized)."""
    import os
    override = os.environ.get(UPSTREAM_CENSUS_ENV)
    return Path(override) if override else Path(__file__).parents[1]/'data/sfitter/upstream-source.json'

def _keys(value,keys,label):
    if type(value) is not dict or set(value)!=set(keys):raise ValueError('closed '+label+' required')
def _text(value,label):
    if type(value) is not str or not value.strip() or len(value.encode())>4096:raise ValueError('explicit '+label+' required')
def _integer(value,label,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError('bounded integer '+label+' required')
def validate(task):
    _keys(task,('config',),'SFitter task');_text(task['config'],'config path');return task
def validate_config(c):
    if type(c) is dict and c.get('schema_version')==2:
        from . import sfitter_complete_native
        return sfitter_complete_native.validate_config(c)
    return _validate_config_schema1(c)

def _validate_config_schema1(c, *, runtime_cap=20000):
    _keys(c,('schema_version','operation','purpose','source','upstream_tree','trusted_upstream_python',
             'runtime','datacard','run_card','semantic_manifest','vectors','max_seconds','max_ram_mib','max_export_bytes'),'SFitter config')
    if type(c['schema_version']) is not int or c['schema_version']!=1 or c['operation'] not in KINDS or c['purpose'] not in ('analytic_qualification','supplied_full_study') or c['trusted_upstream_python'] is not True:
        raise ValueError('explicit trusted pinned native SFitter scope required')
    _text(c['source'],'scientific source')
    if c['operation']=='fixed-vector-qualification' and c['purpose']!='analytic_qualification':raise ValueError('fixed vectors are qualification, not a full study')
    runtime=c['runtime'];_keys(runtime,('python','site_roots','assets','versions','device'),'SFitter runtime')
    if runtime['device'] not in ('cpu','cuda:0') or type(runtime['site_roots']) is not list or type(runtime['assets']) is not list or not runtime['assets'] or len(runtime['assets'])>runtime_cap:
        raise ValueError('bounded explicit native runtime required')
    if len(set(runtime['site_roots']))!=len(runtime['site_roots']):raise ValueError('duplicate runtime root')
    for root in runtime['site_roots']:_text(root,'runtime site root')
    _keys(runtime['versions'],RUNTIME_PACKAGES,'runtime versions')
    for version in runtime['versions'].values():_text(version,'runtime version')
    _integer(c['max_seconds'],'native seconds',1,86400);_integer(c['max_ram_mib'],'RAM MiB',128,8192)
    _integer(c['max_export_bytes'],'export bytes',1024,16*1024*1024)
    if type(c['vectors']) is not list or (c['operation']=='fit' and c['vectors']) or (c['operation']!='fit' and not 1<=len(c['vectors'])<=32):raise ValueError('exact native operation/vector population required')
    return c
def _load(task,base,*,_session=None):
    validate(task);path=(_session.regular_file(task['config'],base) if _session is not None else custody._regular(task['config'],base))
    if path.stat().st_size>4*sfitter_inputs.MAX_INPUT_BYTES:raise ValueError('SFitter config exceeds complete transport byte bound')
    value=validate_config(_session.read_document(path) if _session is not None else read_json(path))
    if value['schema_version']==1 and path.stat().st_size>sfitter_inputs.MAX_INPUT_BYTES:raise ValueError('SFitter legacy config exceeds unchanged input byte bound')
    return path,value
def _source(c,base):
    root,manifest,files=custody._tree(c['upstream_tree'],base)
    expected=read_json(upstream_census_path())
    if expected['commit']!=COMMIT or read_json(manifest)['files']!=expected['files']:
        raise ValueError('native source is not the exact reviewed full upstream235file epoch')
    actual=[p for p in root.rglob('*') if p.is_file()]
    if len(actual)!=len(files) or any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('native source has extra/aliased members')
    return root,manifest,files
def _pins(value):
    if type(value) is dict:
        if set(value)=={'path','sha256'}:yield value
        else:
            for v in value.values():yield from _pins(v)
    elif type(value) is list:
        for v in value:yield from _pins(v)
def semantic(document,card,basis):
    _keys(document,('schema_version','purpose','observables','eft','uncertainty_policy','interval_policy','sources', *(['generation_coherence'] if 'generation_coherence' in document else [])),'native semantic manifest')
    if type(document['schema_version']) is not int or document['schema_version']!=1 or document['purpose'] not in ('analytic_qualification','supplied_full_study'):raise ValueError('explicit semantic scope required')
    rows=document['observables'];actual=card['observations']
    if type(rows) is not list or len(rows)!=len(actual):raise ValueError('whole observable population required')
    for row,obs in zip(rows,actual):
        _keys(row,('ID','name','bins','representation','normalization','unit'),'observable meaning')
        if row['ID']!=obs['ID'] or row['name']!=obs['name'] or type(row['bins']) is not list or len(row['bins'])!=len(obs['Meas']['data']) or len(set(row['bins']))!=len(row['bins']):raise ValueError('whole ordered observation/bin identity differs')
        for label in row['bins']:_text(label,'bin identity')
        if row['representation'] not in ('integrated','differential') or row['normalization']!=('normalized' if len(row['bins'])>1 else 'absolute'):raise ValueError('unchanged native score requires normalized multi-bin groups and absolute singletons')
        _text(row['unit'],'measurement unit')
    eft=document['eft']
    _keys(eft,('target_basis','source_basis','flavour','coefficient_unit','lambda_unit','source_scale_gev','target_scale_gev','rge_policy','conversion','linear','quadratic','mixed_pairs','domain','evidence', *[k for k in ('basis_identifier','ew_input_scheme','validity_cutoff') if k in eft]),'EFT convention contract')
    if eft['target_basis']!=basis or eft['rge_policy']!='not_applied_same_scale' or eft['source_scale_gev']!=eft['target_scale_gev']:
        raise ValueError('only explicit native basis at the same scale; RGE needs a separate source-bound method')
    for k in ('source_scale_gev','target_scale_gev'):
        if sfitter_inputs._finite(eft[k])<=0:raise ValueError('positive explicit renormalization scale required')
    for k in ('source_basis','flavour','coefficient_unit','lambda_unit','domain'):_text(eft[k],k)
    if eft['conversion'] not in ('identity_native_basis','preconverted_source_bound_card') or type(eft['linear']) is not bool or type(eft['quadratic']) is not bool or eft['linear'] is not True:raise ValueError('explicit supplied EFT conversion/truncation required')
    if type(eft['mixed_pairs']) is not list:raise ValueError('explicit mixed population required')
    pairs=[]
    for pair in eft['mixed_pairs']:
        if type(pair) is not list or len(pair)!=2 or pair[0] not in basis or pair[1] not in basis or pair[0]==pair[1]:raise ValueError('known distinct mixed coefficients required')
        pairs.append(tuple(sorted(pair)))
    if len(set(pairs))!=len(pairs):raise ValueError('mixed term alias repeated')
    observed=set()
    for pred in card['predictions']:
        for term in pred['modifiers']:
            parts=term['name'].split('x')
            if len(parts)==2 and parts[0]==parts[1] and not eft['quadratic']:raise ValueError('quadratic term contradicts declared truncation')
            if len(parts)==2 and parts[0]!=parts[1]:
                if not eft['quadratic']:raise ValueError('mixed term contradicts declared linear truncation')
                observed.add(tuple(sorted(parts)))
    if observed!=set(pairs):raise ValueError('whole mixed coefficient population differs from card')
    if document['uncertainty_policy']!='native_top_percent_sources_RFit_component_clamp_named_correlation_capped_shrinkage' or document['interval_policy']!='raw_native_arrays_no_qualified_intervals':raise ValueError('no native statistical translation or interval authority allowed')
    if type(document['sources']) is not list or not document['sources'] or type(eft['evidence']) is not list or not eft['evidence']:raise ValueError('actual source/convention evidence pins required')
    return document
def _validation_pin(pin,base,session):
    """Use only this operation's descriptor-authenticated content observation."""
    custody._keys(pin,('path','sha256'),'file pin')
    if not isinstance(pin['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',pin['sha256']):
        raise ValueError('invalid source hash')
    path=session.regular_file(pin['path'],base)
    if session.hash_file(path)!=pin['sha256']:raise ValueError('source pin changed: '+str(path))
    return path

def _inputs(task,base,*,_session=None):
    path,c=_load(task,base,_session=_session);parent=path.parent
    if c['schema_version']==2:
        from . import sfitter_complete_native
        return sfitter_complete_native.inputs(task,base,_session=_session)
    key=('sfitter-native-inputs',str(path))
    if _session is not None:
        _session.track(task)
        if key in _session.proofs:
            # Closed request JSON and all scientific/source/runtime files remain
            # tracked by the same session. Reuse still checks every leaf identity;
            # finish() retains the full literal ancestry, source census, runtime,
            # ledger and parsed-object checks before authority can return.
            return [_session.regular_file(p,parent) for p in _session.proofs[key]]
    pin=custody._pin if _session is None else lambda p,b:_validation_pin(p,b,_session)
    if _session is not None:
        source_root=custody._regular(c['upstream_tree']['root'],parent,directory=True)
        _session.require_inventory(source_root)
        expected=upstream_census_path()
        _session.regular_file(expected,parent);_session.read_document(expected)
    root,manifest,files=_source(c,parent)
    if _session is not None:
        pin(c['upstream_tree']['manifest'],parent)
        source_doc=_session.read_document(manifest)
        _session.require_inventory(root)
        for source in files:
            pin({'path':str(source),'sha256':source_doc['files'][source.relative_to(root).as_posix()]},parent)
    card_path=pin(c['datacard'],parent);run_path=pin(c['run_card'],parent)
    bound=sfitter_inputs.compile_known_card(root,card_path,run_path,input_scope='engineering_control' if c['purpose']=='analytic_qualification' else 'upstream_known_card')
    read=read_json if _session is None else _session.read_document
    sem_path=pin(c['semantic_manifest'],parent);sem=semantic(read(sem_path),read(card_path),bound['active_parameter_names'])
    from . import generation_conventions
    coherence=generation_conventions.check_fit(sem,sem_path.parent,pin=pin,read=read,card=read(card_path))
    if sem['purpose']!=c['purpose']:raise ValueError('semantic purpose differs from native operation')
    for vector in c['vectors']:sfitter_inputs._vector(vector,len(bound['active_parameter_names']),'full coefficient vector')
    python=pin(c['runtime']['python'],parent)
    if not os.access(python,os.X_OK):raise ValueError('admitted interpreter must be executable')
    runtime=[pin(p,parent) for p in c['runtime']['assets']]
    if len(set(runtime))!=len(runtime):raise ValueError('duplicate runtime asset')
    sites=[custody._regular(directory,parent,directory=True) for directory in c['runtime']['site_roots']]
    if not sites or any(not any(asset.is_relative_to(site) for site in sites) for asset in runtime):raise ValueError('runtime asset must belong to a declared site root')
    evidence=[pin(p,parent) for p in [*sem['sources'],*sem['eft']['evidence']]]
    result=sorted(set([path,manifest,card_path,run_path,sem_path,python,*files,*runtime,*evidence,*coherence['paths']]))
    if _session is not None:_session.proofs[key]=tuple(result)
    return result
def inputs(task,base):return _inputs(task,base)
def _validation_inputs(task,base,session):return _inputs(task,base,_session=session)
def source_output_policy(task,base):
    """Fresh-only exact empty source copies; never admit generated science empties."""
    path,c=_load(task,base);root,manifest,files=_source(c,path.parent)
    expected=read_json(upstream_census_path())
    from ravel.workflow.validation_io import _SFITTER6072_EMPTY_SOURCE_FILES
    rows=[]
    for relative in _SFITTER6072_EMPTY_SOURCE_FILES:
        source=root/relative
        if source not in files or expected['files'].get(relative)!=hashlib.sha256(b'').hexdigest() or source.stat().st_size!=0:
            raise ValueError('exact upstream empty file source required')
        rows.append({'path':'outputs/attempt-1/native/upstream/'+relative,'role':'retained_source_file',
            'marker_class':'sfitter6072_empty_source_file','relative':relative,
            'source':{'path':str(source),'sha256':custody._hash(source),'size':0}})
    return {'schema_version':1,'allow_empty_directory_members':rows}


def execution_seconds(task,base):return _load(task,base)[1]['max_seconds']
def _validation_execution_seconds(task,base,session):return _load(task,base,_session=session)[1]['max_seconds']
def _identity(paths):
    rows={}
    for p in paths:
        p=custody._regular(p,Path.cwd());s=p.stat()
        rows[str(p)]=(custody._hash(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode)
    return rows
def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{})
    scopes=policy.get('claim_scopes',{})
    if spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or policy.get('max_redos')!=0 or set(scopes)!={SCOPE} or scopes[SCOPE].get('actions')!=['delivery']:
        raise ValueError('native SFitter requires version 2 one-attempt delivery-only policy')
    return spec

def _approved(task,out):
    from ravel.workflow import science
    for rd in (out,*out.parents):
        if (rd/'inputs/science-plan.json').is_file():
            plan=science.verify_worker(rd);spec=science.execution_spec(rd)
            policy=spec.get('review_policy',{}).get('policy',{})
            scopes=policy.get('claim_scopes',{})
            if (spec['mode']!='sfitter-native-fit' or spec['task']!=task or out!=(rd/plan['output_directory']).resolve() or spec['schema_version']!=2 or spec['max_attempts']!=1 or policy.get('max_redos')!=0 or set(scopes)!={SCOPE} or scopes[SCOPE]['actions']!=['delivery']):
                raise ValueError('native SFitter requires exact one-attempt ordinary delivery-only approval')
            return plan
    raise ValueError('native SFitter requires its approved ordinary worker')
def run(task,base,output):
    if _load(task,base)[1]['schema_version']==2:
        from . import sfitter_complete_native
        return sfitter_complete_native.run(task,base,output)
    out=Path(output).absolute();plan=_approved(task,out)
    path,c=_load(task,base);paths=inputs(task,base);before=_identity(paths)
    if c['max_seconds']>plan['max_seconds']:raise ValueError('native budget exceeds approval')
    if not re.fullmatch(r'[A-Za-z0-9_./-]+',str(out)) or any(p.is_symlink() for p in (out,*out.parents)):
        raise ValueError('safe ordinary output path required by upstream Documenter')
    out.mkdir(parents=True,exist_ok=True);native=out/'native';native.mkdir(exist_ok=False)
    source_root,_,_= _source(c,path.parent)
    copied=native/'upstream';custody._copy(c['upstream_tree'],path.parent,copied)
    source_before=custody.source_tree(copied)
    package=copied/'sfitter';(package/'output').mkdir(exist_ok=False)
    selected=native/'selected.json';shutil.copyfile(custody._pin(c['datacard'],path.parent),selected)
    run_card=native/'selected.yaml';raw=custody._pin(c['run_card'],path.parent).read_text()
    raw=re.sub(r'^datacard:[^\n]*$', 'datacard: '+json.dumps(str(selected)),raw,flags=re.M);run_card.write_text(raw)
    exporter=native/'sfitter_results.py';shutil.copyfile(Path(sfitter_results.__file__),exporter)
    driver=native/'driver.py';shutil.copyfile(Path(__file__).with_name('sfitter_worker.py'),driver)
    request_config={**c,'runtime':{**c['runtime'],'python':{'path':str(custody._pin(c['runtime']['python'],path.parent)),'sha256':c['runtime']['python']['sha256']},'site_roots':[str(custody._regular(site,path.parent,directory=True)) for site in c['runtime']['site_roots']]}}
    request={'schema_version':1,'config':request_config,'package_root':str(package),'run_card':str(run_card),
             'output':str(native),'basis':sfitter_inputs.native_basis(source_root),
             'runtime_assets':{str(custody._pin(pin,path.parent)):pin['sha256'] for pin in c['runtime']['assets']},
             'source_files':{str(copied/p):sha for p,sha in source_before['files'].items()},
             'exporter_sha256':custody._hash(exporter),'driver_sha256':custody._hash(driver),
             'selected_files':{str(selected):custody._hash(selected),str(run_card):custody._hash(run_card)}}
    copied_before=_identity([copied/p for p in source_before['files']])
    selected_before=_identity([selected,run_card,driver,exporter])
    atomic_json(native/'request.json',request)
    selected_before.update(_identity([native/'request.json']))
    atomic_json(out/'sfitter-input-custody.json',{'source':c['source'],'operation':c['operation'],'purpose':c['purpose'],
                'original_cards':[c['datacard'],c['run_card']],'literal_relocation_only':True,'source_sha256s':before,'physics_validated':False})
    from ravel.physics.reinterpret_db import execute_native
    error=None;receipt=None
    try:receipt=execute_native([str(custody._pin(c['runtime']['python'],path.parent)),'-I','-B',str(driver),str(native/'request.json')],native,c)
    except (ValueError,OSError,RuntimeError) as exc:error=str(exc)
    # Partial native files are already below the ordinary attempted output root.
    # Record their identities before any serializer/postcondition can refuse them.
    retained=[];census_errors=[]
    for p in sorted(native.rglob('*')):
        if p.is_symlink():census_errors.append('aliased native member: '+str(p.relative_to(out)));continue
        if not p.is_file():continue
        try:
            custody._regular(p,out)
            retained.append({'path':str(p.relative_to(out)),'sha256':custody._hash(p),'bytes':p.stat().st_size})
        except (OSError,ValueError) as exc:census_errors.append('native census refused: '+str(exc))
    atomic_json(out/'sfitter-raw-census.json',{'files':retained,'refused_members':census_errors,'before_semantic_adjudication':True,'physics_validated':False})
    problems=list(census_errors)
    if error:problems.append('native_failed: '+error)
    try:
        if before!=_identity(paths):problems.append('original input/runtime/source identity changed')
        if _source(c,path.parent)[0]!=source_root:problems.append('original source census changed')
        if copied_before!=_identity([copied/p for p in source_before['files']]):problems.append('copied source identity changed')
        if selected_before!=_identity([selected,run_card,driver,exporter,native/'request.json']):problems.append('selected card/driver/exporter identity changed')
    except (ValueError,OSError) as exc:problems.append('ending custody refused: '+str(exc))
    for rel,sha in source_before['files'].items():
        p=copied/rel
        try:
            custody._regular(p,out)
            if custody._hash(p)!=sha:problems.append('copied original source changed: '+rel)
        except (OSError,ValueError):problems.append('copied original source missing/aliased: '+rel)
    extra=[p for p in copied.rglob('*') if p.is_file() and p.relative_to(copied).as_posix() not in source_before['files'] and not p.is_relative_to(package/'output')]
    if extra or any(p.is_symlink() for p in native.rglob('*')):problems.append('unexpected/aliased native source/output member')
    for file,sha in ((driver,request['driver_sha256']),(exporter,request['exporter_sha256'])):
        if not file.is_file() or custody._hash(file)!=sha:problems.append('worker/serializer changed')
    delivery=None;initialized=None
    try:
        state_path=native/'initialized-state.json'
        if state_path.stat().st_size>c['max_export_bytes']:raise ValueError('initialized state export exceeds bound')
        candidate=read_json(state_path)
        origins=[{'path':name,'sha256':sha} for name,sha in request['source_files'].items()
                 if name.endswith('/sfitter/likelihood/full_likelihood.py')]
        if len(origins)!=1:raise ValueError('one initialized native source required')
        selected_card=read_json(selected)
        sfitter_results.validate_initialized_state(candidate,request['basis'],origins[0],
            bin_count=sum(len(o['Meas']['data']) for o in selected_card['observations']),
            group_count=len(selected_card['observations']))
        initialized=candidate
    except (ValueError,OSError,KeyError,TypeError) as exc:problems.append('initialized native state incomplete/invalid: '+str(exc))
    try:
        if (native/'delivery.json').stat().st_size>c['max_export_bytes']:raise ValueError('export exceeds bound')
        delivery=read_json(native/'delivery.json')
        if c['operation']=='fit':sfitter_results.validate_result(delivery,request['basis'])
        else:
            validate_qualification(delivery,request['basis'],c['vectors'],sum(len(o['Meas']['data']) for o in read_json(selected)['observations']))
            if initialized is None or delivery['native_tensors']!=initialized['native_tensors']:raise ValueError('fixed-vector return differs from retained initialized state')
        validate_runtime(read_json(native/'runtime.json'),request)
        progress=read_json(native/'progress.json')
        if progress.get('phase')!='complete' or progress.get('error') is not None or progress.get('physics_validated') is not False:raise ValueError('native calculation/final custody did not complete')
    except (ValueError,OSError,KeyError,TypeError) as exc:problems.append('native return incomplete/invalid: '+str(exc))
    result={'schema_version':1,'kind':'sfitter_native_delivery','status':'failed' if problems else 'passed',
            'status_scope':SCOPE,'operation':c['operation'],'purpose':c['purpose'],'problems':problems,
            'native_execution':receipt,'native_return':delivery,'initialized_state':initialized,'raw_census':'sfitter-raw-census.json',
            'profile_search_qualification':'unknown','interval_qualification':'unknown','eft_applicability':'unknown',
            'coverage_calibration':'unknown','physics_validated':False,'automatic_redo':False,
            'limits':['Native delivery only; no convergence, globality, interval, coverage or EFT validity inference.',
                      'Fixed-vector qualification and synthetic controls are not full measurement/campaign credit.',
                      'Pinned declared runtime assets and observed import census do not certify proprietary/OS dependency completeness.']}
    atomic_json(out/'sfitter-native.json',result);return result
TENSORS=sfitter_results.INITIALIZED_TENSORS
def validate_qualification(document,basis,vectors,bin_count):
    _keys(document,('schema_version','kind','parameters','vectors','scores','native_tensors','score_convention','predictions','prediction_reason','physics_validated'),'native qualification return')
    if (type(document['schema_version']) is not int or document['schema_version']!=1 or document['kind']!='sfitter_fixed_vectors' or document['parameters']!=basis or document['vectors']!=vectors or document['physics_validated'] is not False or document['score_convention']!='native_score=-Q' or document['predictions'] is not None):raise ValueError('native qualification scope/population changed')
    _text(document['prediction_reason'],'native prediction limitation')
    sfitter_results.validate_array(document['scores'])
    if document['scores']['shape']!=[len(vectors)]:raise ValueError('fixed-vector population incomplete')
    _keys(document['native_tensors'],TENSORS,'native tensor population')
    for key,value in document['native_tensors'].items():sfitter_results.validate_array(value)
    expected={'smeft_coeffs':[bin_count,len(basis),len(basis)+1],'smeft_offset':[bin_count],
              'measurements':[bin_count],'err_theo':[bin_count],'err_gauss':[bin_count],
              'corr':[bin_count,bin_count],'corr_inv':[bin_count,bin_count],
              'bin_widths':[bin_count],'norm_indices':[bin_count]}
    if any(document['native_tensors'][k]['shape']!=shape for k,shape in expected.items()):raise ValueError('native full tensor dimensions differ')
    if len(document['native_tensors']['norm_start']['shape'])!=1:raise ValueError('native normalization groups incomplete')
    return document

def validate_runtime(document,request):
    _keys(document,('schema_version','versions','device','precision','imports','source_files','runtime_assets','randomness','physics_validated'),'native observed runtime')
    if type(document['schema_version']) is not int or document['schema_version']!=1 or document['versions']!=request['config']['runtime']['versions'] or document['device']!=request['config']['runtime']['device'] or document['precision']!='double' or document['physics_validated'] is not False or document['source_files']!=request['source_files'] or document['runtime_assets']!=request['runtime_assets']:raise ValueError('native observed runtime/source does not match admission')
    if type(document['imports']) is not dict or not document['imports']:raise ValueError('native observed import census missing')
    _text(document['randomness'],'native randomness limitation')
    allowed={**request['runtime_assets'],**request['source_files'],str(Path(request['output'])/'sfitter_results.py'):request['exporter_sha256'],str(Path(request['output'])/'driver.py'):request['driver_sha256']}
    for name,pin in document['imports'].items():
        if type(pin) is dict and pin.get('kind')=='virtual_python_namespace':
            expected=sfitter_worker.virtual_import_contract(name,request)
            if pin!=expected:raise ValueError('native virtual import contract differs')
            owner_name=expected['type']['module']
            if (document['imports'].get(owner_name)!=expected['owner']
                    or document['imports'].get('torch')!=expected['package_owner']):
                raise ValueError('virtual namespace physical owner imports missing or changed')
        else:
            if name in sfitter_worker.VIRTUAL_NAMESPACES:
                raise ValueError('registered virtual namespace requires typed observation')
            _keys(pin,('path','sha256'),'native import')
            if allowed.get(pin['path'])!=pin['sha256']:raise ValueError('unadmitted native import')
    if not any('/sfitter/likelihood/full_likelihood.py' in p.get('path','') for p in document['imports'].values()):raise ValueError('native top likelihood origin missing')
    return document


def write_report(result,output):
    path=Path(output)/'sfitter-native-report.md'
    if result.get('schema_version')==2:
        profile=result['profile'];algorithm=result['algorithm']
        meaning=('top normalized multibin polynomial and signed correlated RFit score' if profile=='top' else 'Higgs branching/production and EWPO independent pull-square source score' if profile=='higgs' else 'original synthetic diagnostic log-likelihood')
        marginal=('unweighted native SMC/CRAFT particle histograms; native log weights are not used by that histogram producer' if algorithm in ('smc','craft') else 'original native flow importance-weighted histograms')
        holds=result.get('scientific_input_holds',[])
        unresolved=('\n\nUnresolved scientific inputs (software delivery does not clear these):\n'
            +json.dumps(holds,indent=2,allow_nan=False)+'\n\nAuthenticated derived-card lineage: '
            +json.dumps(result['card_derivation'],sort_keys=True,allow_nan=False)+'\n') if holds else ''
        support=('\n\nPinned native Higgs law assumptions (production ratio fixed one is not a general ttH EFT response):\n'
            +json.dumps(result['native_law_assumptions'],indent=2,allow_nan=False)
            +'\n\nScientific input support (backend capability and published-card fidelity are separate):\n'
            +json.dumps(result['scientific_input_support'],indent=2,allow_nan=False)+'\n') if profile=='higgs' else ''
        path.write_text('Native SFitter delivery: '+result['status']+'\n\nScope: '+SCOPE+'\n\nProfile: '+profile+'; algorithm: '+algorithm+'; phase: '+result['phase']+'.\n\n'
            +meaning+'. '+marginal+'. Neither is a qualified Bayesian posterior or a Wilks/CLs interval. Native mass-contour plots retain their original meaning. '
            +'Convergence/globality, normalization/prior adequacy, interval qualification, coverage and EFT applicability remain unknown. No native retry is authorized.\n\n'
            +'\n'.join('- '+reason for reason in result['problems'])+'\n'+unresolved+support)
        return [{'stem':'sfitter-native-report','files':[path.name]}]
    path.write_text('Native SFitter delivery: '+result['status']+'\n\nScope: '+SCOPE+'\n\n'
        'Raw score -Q, native profiles exp(-Q), named RFit/correlation/shrinkage inputs and original native outputs are retained. '
        'Convergence/globality, interval qualification, coverage and EFT applicability remain unknown. '
        'No Gaussian likelihood translation or new native retry is authorized.\n\n'
        +'\n'.join('- '+reason for reason in result['problems'])+'\n')
    return [{'stem':'sfitter-native-report','files':[path.name]}]
