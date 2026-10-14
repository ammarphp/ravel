"""Complete SFitter operation on the existing ordinary delivery authority.

Schema1 stays in sfitter_native. Schema2 binds released profiles, numerical
settings, selected-coordinate embedding, and authentic saved-state phases.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat

from . import sfitter_inputs as inputs_api, sfitter_profiles as profiles, sfitter_compat as compatibility, sfitter_results as results
from . import model_tool_bridge as custody
from ravel.workflow.state_io import read_json, atomic_json

def validate_config(c):
    from . import sfitter_native as legacy
    fields={'schema_version','operation','purpose','source','upstream_tree','trusted_upstream_python','runtime','datacard','run_card','semantic_manifest','vectors','max_seconds','max_ram_mib','max_export_bytes','profile','parameters','algorithm','phase','saved_run','inference','production_handoff'}
    if 'card_derivation' in c:fields.add('card_derivation')
    legacy._keys(c,fields,'complete SFitter config')
    if type(c['schema_version']) is not int or c['schema_version']!=2 or c['profile'] not in profiles.PROFILES or c['algorithm'] not in profiles.ALGORITHMS or c['phase'] not in profiles.PHASES or c['inference']!=profiles.INFERENCE:raise ValueError('released native scope; posterior/evidence inference unsupported')
    if c['phase']=='run' and c['saved_run'] is not None or c['phase']!='run' and c['saved_run'] is None:raise ValueError('exact original saved-state phase required')
    physical=c['profile'] in ('top','higgs')
    if not physical and (c['purpose']!='analytic_qualification' or c['datacard'] is not None or c['semantic_manifest'] is not None or c['production_handoff'] is not None or c.get('card_derivation') is not None):raise ValueError('diagnostic profiles cannot stand in for measurement delivery')
    old={k:copy.deepcopy(c[k]) for k in fields if k in {'schema_version','operation','purpose','source','upstream_tree','trusted_upstream_python','runtime','datacard','run_card','semantic_manifest','vectors','max_seconds','max_ram_mib','max_export_bytes'}}
    old['schema_version']=1;legacy._validate_config_schema1(old,runtime_cap=64000)
    if len(json.dumps(c,allow_nan=False).encode())>4*inputs_api.MAX_INPUT_BYTES:raise ValueError('complete native config metadata exceeds64MiB; no runtime member truncation permitted')
    if c['operation']=='fixed-vector-qualification' and (c['phase']!='run' or not physical):raise ValueError('fixed physical score vectors do not load or plot native fits')
    for key in ('saved_run','production_handoff',*(['card_derivation'] if 'card_derivation' in c else [])):
        if c[key] is not None:legacy._keys(c[key],('path','sha256'),key+' pin')
    return c

def transport_capture():
    """Parse only the descriptor-authenticated original transport buffer.

    Numeric exports can exceed the generic supplied-card 8MiB cap; this local
    subclass raises only the transport limit, keeping descriptor/ancestry/ABA
    and ending guards. Generic Capture is unchanged.
    """
    from ravel.workflow.sfitter_workflow import _strict_document
    from ravel.physics.ma5_saf import Capture, _identity
    class Transport(Capture):
        def bounded(self,path):
            before=self.ordinary(path)
            limit=4*results.MAX_BYTES
            if not 0<before[3]<=limit:raise ValueError('bounded nonempty native transport required')
            with path.open('rb') as stream:
                if _identity(os.fstat(stream.fileno()))!=before:raise ValueError('transport replaced before capture')
                raw=stream.read(limit+1)
                if _identity(os.fstat(stream.fileno()))!=before:raise ValueError('transport changed during capture')
            if self.ordinary(path)!=before or len(raw)!=before[3]:raise ValueError('transport pathname changed during capture')
            return before,raw
    return Transport()

def _read(path,expected=None):
    from ravel.workflow.sfitter_workflow import _strict_document
    cap=transport_capture();_,raw=cap.read(path,Path(path).parent,expected)
    value=_strict_document(raw);cap.finish();return value

def _write_committed(path,value,committed):
    raw=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode()
    expected=hashlib.sha256(raw).hexdigest()
    atomic_json(path,value)
    _read(path,expected)
    committed[Path(path)]=expected
    return {'path':str(path),'sha256':expected}

def semantic(document,card,contract):
    from . import sfitter_native as legacy
    # Reuse all literal convention, truncation and full-source evidence laws.
    physical=contract['profile'];full=contract['selection']['full']
    expected_policy={'top':'native_top_percent_sources_RFit_component_clamp_named_correlation_capped_shrinkage',
        'higgs':'native_higgs_Poisson_Gaussian_RFit_branching_production_EWPO'}[physical]
    if document.get('uncertainty_policy')!=expected_policy:raise ValueError('exact native sector uncertainty policy required')
    projected=copy.deepcopy(document);projected['uncertainty_policy']='native_top_percent_sources_RFit_component_clamp_named_correlation_capped_shrinkage'
    if physical=='higgs':
        if document.get('eft',{}).get('quadratic') is not True:
            raise ValueError('native full Higgs production/decay/EWPO tensors require explicit quadratic scope')
        # The source Higgs score does not normalize multibin predictions.
        for row in projected['observables']:
            if row['normalization']!='absolute':raise ValueError('Higgs source uses absolute measurement/prediction channels')
            row['normalization']='normalized' if len(row['bins'])>1 else 'absolute'
        wc=copy.deepcopy(card)
        for pred in wc['predictions']:pred['modifiers']=[m for m in pred['modifiers'] if m.get('type','WC')=='WC']
    else:wc=card
    legacy.semantic(projected,wc,full)
    return document

def adapter_sources():
    names=('sfitter_complete_native.py','sfitter_complete_worker.py','sfitter_profiles.py','sfitter_compat.py','sfitter_results.py','sfitter_worker.py','sfitter_inputs.py','sfitter_card_derivation.py','sfitter_higgs_support.py','reviewed_source.py')
    return {name:custody._hash(Path(__file__).with_name(name)) for name in names}

def _ordinary_paths(rd):
    from ravel.workflow import science, physics_review
    rd=Path(rd).absolute()
    paths=[Path(p) for p in science.review_waypoint_paths(rd)]
    if science.execution_spec(rd)['mode']!='sfitter-native-fit' or science.packet(rd)['lifecycle_verdict']!='PASS' or physics_review.gate_errors(rd,'delivery'):
        raise ValueError('current successful original ordinary SFitter delivery and scoped reviews required')
    return rd,paths

def saved_state(pin,base,c,contract):
    """Authenticate the original complete ordinary namespace before pickle load."""
    from . import sfitter_native as legacy
    p=custody._pin(pin,base);cap=_read(p,pin['sha256'])
    fields={'schema_version','kind','rundir','run_name','profile','algorithm','selection','source_manifest','runtime','datacard','original_run_card','files','adapter_sources','scientific_inputs','physics_validated'}
    if cap.get('profile') in ('top','higgs'):
        from . import sfitter_higgs_support
        if not set(sfitter_higgs_support.FIELDS)<=set(cap):
            raise ValueError('saved Higgs source-support ledger absent; explicit source requalification required')
        fields.update(sfitter_higgs_support.FIELDS)
    legacy._keys(cap,fields,'saved native capsule')
    declared={k:c.get(k) for k in ('datacard','run_card','semantic_manifest','production_handoff','card_derivation')}
    if cap['scientific_inputs']!=declared:raise ValueError('saved full scientific input/handoff identity differs')
    if cap['adapter_sources']!=adapter_sources():raise ValueError('saved native adapter/compatibility source identity differs')
    if cap['schema_version']!=2 or cap['kind']!='sfitter_saved_native_capsule' or cap['physics_validated'] is not False or cap['profile']!=c['profile'] or cap['algorithm']!=c['algorithm'] or cap['selection']!=contract['selection'] or cap['runtime']!=c['runtime'] or cap['source_manifest']!=c['upstream_tree']['manifest'] or cap['datacard']!=c['datacard'] or cap['original_run_card']!=c['run_card']:raise ValueError('saved native source/runtime/card/coordinate identity differs')
    rd,paths=_ordinary_paths(cap['rundir'])
    if p not in paths or p.name!='state-capsule.json' or p.parent.name!='native':raise ValueError('capsule is outside committed original ordinary outputs')
    delivery=_read(p.parent.parent/'sfitter-native.json')
    if delivery.get('status')!='passed' or delivery.get('schema_version')!=2 or delivery.get('native_capsule')!=pin:raise ValueError('original native result does not bind saved capsule')
    if c['profile'] in ('top','higgs'):
        sfitter_higgs_support.verify_saved(cap,delivery,contract)
    if not re.fullmatch(r'\d{8}_\d{6}_[A-Za-z0-9_]{1,64}',cap['run_name']):raise ValueError('safe original native saved run required')
    root=p.parent/'upstream/sfitter/output'/cap['run_name'];custody._regular(root,base,directory=True)
    members={q.relative_to(root).as_posix():custody._hash(q) for q in root.rglob('*') if q.is_file()}
    if members!=cap['files'] or any(q.is_symlink() for q in root.rglob('*')) or not {'params.yaml','model.pth','results.pkl'}<=set(members):raise ValueError('complete original model/params/results population differs')
    if any(not (root/name).is_relative_to(root) or '..' in Path(name).parts for name in members):raise ValueError('native saved member escaped capsule')
    required=set(paths)|{p,rd/'inputs/science-plan.json',rd/'execution_state.json'}
    required={q for q in required if q.is_file()}
    return cap,root,sorted(required)

def runtime_members(c,parent):
    """Full declared runtime leaf population, never a truncated import subset."""
    sites=[custody._regular(s,parent,directory=True) for s in c['runtime']['site_roots']]
    declared={custody._pin(v,parent) for v in c['runtime']['assets']}
    found=set()
    for root in sites:
        for q in root.rglob('*'):
            if q.is_symlink():raise ValueError('complete runtime directory/file aliases forbidden')
            if q.is_file():
                custody._regular(q,parent);found.add(q)
                if len(found)>64000:raise ValueError('complete runtime exceeds64k file allocation; no truncation')
            elif not q.is_dir():raise ValueError('complete runtime nonregular member forbidden')
    if not found or found!=declared:raise ValueError('complete runtime asset population missing, added or truncated')
    return sites,sorted(found)

def inputs(task,base,*,_session=None):
    from . import sfitter_native as legacy
    legacy.validate(task);p=(_session.regular_file(task['config'],base) if _session else custody._regular(task['config'],base))
    c=validate_config(_session.read_document(p) if _session else _read(p));parent=p.parent
    root,manifest,sources=legacy._source(c,parent)
    pin=custody._pin if _session is None else lambda v,b:legacy._validation_pin(v,b,_session)
    card=pin(c['datacard'],parent) if c['datacard'] is not None else None
    run_card=pin(c['run_card'],parent);bound=profiles.compile_card(root,card,run_card,c['profile'],c['parameters'],c['algorithm'])
    sem_path=pin(c['semantic_manifest'],parent) if c['semantic_manifest'] is not None else None
    sem=semantic(_session.read_document(sem_path) if _session else _read(sem_path,c['semantic_manifest']['sha256']),_session.read_document(card) if _session else _read(card,c['datacard']['sha256']),bound) if sem_path else None
    if sem and sem['purpose']!=c['purpose']:raise ValueError('whole scientific purpose differs')
    for vector in c['vectors']:inputs_api._vector(vector,len(c['parameters']),'selected complete vector')
    python=pin(c['runtime']['python'],parent)
    if not os.access(python,os.X_OK):raise ValueError('executable original runtime required')
    runtime=[pin(v,parent) for v in c['runtime']['assets']]
    sites,complete_runtime=runtime_members(c,parent)
    if set(runtime)!=set(complete_runtime):raise ValueError('complete runtime declared input population differs')
    if not sites or len(set(runtime))!=len(runtime) or any(not any(p.is_relative_to(s) for s in sites) for p in runtime):raise ValueError('finite original runtime closure required')
    paths=[p,manifest,run_card,python,*sources,*runtime,*([card,sem_path] if card else [])]
    if c.get('card_derivation') is not None:
        from . import sfitter_card_derivation
        dp=pin(c['card_derivation'],parent);derivation=_read(dp,c['card_derivation']['sha256'])
        expected,proof=sfitter_card_derivation.derive(root,derivation.get('original_name'),derivation.get('repair_manifest'))
        if derivation!={**proof,'derived_card':c['datacard']} or _read(card,c['datacard']['sha256'])!=expected:raise ValueError('exact declared source-derived card/lineage differs')
        if c['card_derivation'] not in sem['sources']:raise ValueError('scientific semantic sources must explicitly include derived-card lineage')
        paths.append(dp);paths.extend(Path(v['path']) for v in proof['inputs'])
    if sem:paths.extend(pin(v,parent) for v in [*sem['sources'],*sem['eft']['evidence']])
    if c['saved_run'] is not None:paths.extend(saved_state(c['saved_run'],parent,c,bound)[2])
    if c['production_handoff'] is not None:
        from ravel.workflow import sfitter_native_handoff
        paths.extend(sfitter_native_handoff.verify(c['production_handoff'],parent,c,bound)['paths'])
    paths.extend(Path(v['path']) for v in bound.get('census',{}).get('reviewed_inputs',[]))
    paths=sorted(set(paths))
    if _session:
        _session.track(task);_session.track(c);_session.track(bound)
        expected=legacy.upstream_census_path()
        _session.regular_file(expected,parent);_session.read_document(expected)
        _session.require_inventory(root)
        for site in sites:_session.require_inventory(site)
        for q in paths:_session.regular_file(q,parent);_session.hash_file(q)
    return paths

def run(task,base,output):
    from . import sfitter_native as legacy
    out=Path(output).absolute();plan=legacy._approved(task,out)
    path=custody._regular(task['config'],base);c=validate_config(_read(path));parent=path.parent
    paths=inputs(task,base);before=legacy._identity(paths)
    derivation=None
    if c.get('card_derivation') is not None:
        derivation=_read(custody._pin(c['card_derivation'],parent),c['card_derivation']['sha256'])
    if c['max_seconds']>plan['max_seconds'] or not re.fullmatch(r'[A-Za-z0-9_./-]+',str(out)):raise ValueError('native declared budget/safe output differs')
    out.mkdir(parents=True,exist_ok=True);native=out/'native';native.mkdir(exist_ok=False)
    root,_,_=legacy._source(c,parent);copied=native/'upstream';custody._copy(c['upstream_tree'],parent,copied)
    original=custody.source_tree(copied);adaptation=[]
    if c['algorithm'] in ('smc','craft'):adaptation.append(compatibility.apply(copied,original['files'][compatibility.RELATIVE]))
    source=custody.source_tree(copied);package=copied/'sfitter';(package/'output').mkdir(exist_ok=False)
    selected=native/'selected.json';card=None
    if c['datacard'] is not None:shutil.copyfile(custody._pin(c['datacard'],parent),selected);card=selected
    original_card=custody._pin(c['run_card'],parent)
    contract=profiles.compile_card(root,custody._pin(c['datacard'],parent) if card else None,original_card,c['profile'],c['parameters'],c['algorithm'])
    from . import sfitter_higgs_support
    support_metadata=sfitter_higgs_support.contract_metadata(contract)
    params=copy.deepcopy(contract['params'])
    if card:params['datacard']=str(selected)
    # JSON is a strict YAML subset; native FullLoader consumes this exact mapping.
    run_card=native/'selected.yaml';run_card.write_text(json.dumps(params,allow_nan=False,indent=2)+'\n');contract['params']=params
    saved_name=None;reuse_paths=[]
    if c['saved_run'] is not None:
        capsule,saved,reuse_paths=saved_state(c['saved_run'],parent,c,contract)
        saved_name=capsule['run_name'];target=package/'output'/saved_name;shutil.copytree(saved,target)
        old=profiles.yaml_document((target/'params.yaml').read_text())
        wanted=copy.deepcopy(params);old['datacard']=wanted.get('datacard') if card else old.get('datacard')
        if not card:old.pop('datacard',None)
        if old!=wanted:raise ValueError('saved native numerical settings changed')
        (target/'params.yaml').write_bytes(run_card.read_bytes())
    support={}
    for src,name in ((Path(__file__).with_name('sfitter_complete_worker.py'),'driver.py'),(Path(__file__).with_name('sfitter_worker.py'),'sfitter_worker.py'),(Path(results.__file__),'sfitter_results.py')):
        q=native/name;shutil.copyfile(src,q);support[str(q)]=custody._hash(q)
    config=copy.deepcopy(c);config['runtime']['python']['path']=str(custody._pin(c['runtime']['python'],parent));config['runtime']['site_roots']=[str(s) for s in map(lambda v:custody._regular(v,parent,directory=True),c['runtime']['site_roots'])]
    request={'schema_version':2,'config':config,'contract':contract,'package_root':str(package),'run_card':str(run_card),'output':str(native),'basis':c['parameters'],
        'runtime_assets':{str(custody._pin(v,parent)):v['sha256'] for v in c['runtime']['assets']},'source_files':{str(copied/q):h for q,h in source['files'].items()},'support_files':support,
        'selected_files':{str(run_card):custody._hash(run_card),**({str(selected):custody._hash(selected)} if card else {}),**({str(package/'output'/saved_name/name):custody._hash(package/'output'/saved_name/name) for name in ('params.yaml','model.pth',*(['results.pkl'] if c['phase']=='plot' else []))} if saved_name else {})},'saved_run_name':saved_name}
    committed={}
    _write_committed(native/'request.json',request,committed)
    selected_before=legacy._identity([Path(q) for q in [*request['source_files'],*support,*request['selected_files'],str(native/'request.json')]])
    from ravel.physics.reinterpret_db import execute_native
    problems=[];receipt=None
    try:receipt=execute_native([config['runtime']['python']['path'],'-I','-B',str(native/'driver.py'),str(native/'request.json')],native,c)
    except (OSError,ValueError,RuntimeError) as exc:problems.append('native failed: '+str(exc))
    census=[]
    for q in sorted(native.rglob('*')):
        if q.is_symlink():problems.append('aliased native output');continue
        if q.is_file():census.append({'path':q.relative_to(out).as_posix(),'sha256':custody._hash(q),'bytes':q.stat().st_size})
    _write_committed(out/'sfitter-raw-census.json',{'files':census,'before_semantic_adjudication':True,'physics_validated':False},committed)
    delivery=initialized=cap_pin=None
    try:
        if before!=legacy._identity(paths):raise ValueError('original input/source/runtime/producer custody changed')
        # Saved native output files may be archived/replaced by native fit/plot.
        stable=[q for q in selected_before if not saved_name or not Path(q).is_relative_to(package/'output'/saved_name)]
        if {q:selected_before[q] for q in stable}!=legacy._identity([Path(q) for q in stable]):raise ValueError('native source/selected/driver custody changed')
        for q in copied.rglob('*'):
            if q.is_symlink() or q.is_file() and not q.is_relative_to(package/'output') and q.relative_to(copied).as_posix() not in source['files']:raise ValueError('unexpected copied native source member')
        returned_before=legacy._identity([native/name for name in ('delivery.json','initialized-state.json','runtime.json','progress.json','plots.json','saved-state.json')])
        def returned(name):return _read(native/name,returned_before[str(native/name)][0])
        delivery=returned('delivery.json');initialized=returned('initialized-state.json')
        origin=next({'path':p,'sha256':h} for p,h in request['source_files'].items() if p.endswith('/sfitter/likelihood/full_likelihood.py'))
        results.validate_complete_initialized_state(initialized,contract,origin)
        if c['operation']=='fit':results.validate_result(delivery,c['parameters'])
        elif delivery!={'schema_version':2,'kind':'sfitter_complete_fixed_vectors','selection':contract['selection'],'scores':delivery['scores'],'vectors':c['vectors'],'profile':c['profile'],'physics_validated':False} or delivery['scores']['shape']!=[len(c['vectors'])]:raise ValueError('complete fixed-vector return differs')
        else:results.validate_array(delivery['scores'])
        observed=returned('runtime.json')
        runtime_request={**request,'exporter_sha256':support[str(native/'sfitter_results.py')],'driver_sha256':support[str(native/'driver.py')],'runtime_assets':{**request['runtime_assets'],**support}}
        _validate_runtime(observed,request,runtime_request)
        progress=returned('progress.json')
        if progress['phase']!='complete' or progress['error'] is not None or progress['physics_validated'] is not False:raise ValueError('native child ending incomplete')
        if c['operation']=='fit':
            state=returned('saved-state.json')
            if not re.fullmatch(r'\d{8}_\d{6}_[A-Za-z0-9_]{1,64}',state['run_name']):raise ValueError('native saved run namespace differs')
            run=custody._regular(package/'output'/state['run_name'],out,directory=True)
            if run!=Path(state['path']) or run.resolve(strict=True)!=run:raise ValueError('native saved run namespace differs')
            for member in run.rglob('*'):
                custody._regular(member,run,directory=member.is_dir())
            from ravel.workflow import science
            rd=next(p for p in out.parents if (p/science.PLAN).is_file())
            capsule={'schema_version':2,'kind':'sfitter_saved_native_capsule','rundir':str(rd),'run_name':run.name,'profile':c['profile'],'algorithm':c['algorithm'],'selection':contract['selection'],'source_manifest':c['upstream_tree']['manifest'],'runtime':c['runtime'],'datacard':c['datacard'],'original_run_card':c['run_card'],'files':{q.relative_to(run).as_posix():custody._hash(q) for q in run.rglob('*') if q.is_file()},'adapter_sources':adapter_sources(),'scientific_inputs':{k:c.get(k) for k in ('datacard','run_card','semantic_manifest','production_handoff','card_derivation')},'physics_validated':False,**copy.deepcopy(support_metadata)}
            if not {'params.yaml','model.pth','results.pkl'}<=set(capsule['files']):raise ValueError('complete native saved state missing')
            cap_pin=_write_committed(native/'state-capsule.json',capsule,committed)
        if returned_before!=legacy._identity([Path(q) for q in returned_before]):raise ValueError('native original return changed during adjudication')
        runtime_members(c,parent)
        if before!=legacy._identity(paths):raise ValueError('original ending source/runtime/producer differs')
        for q,h in committed.items():_read(q,h)
    except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:problems.append('native complete return/custody refused: '+str(exc))
    result={'schema_version':2,'kind':'sfitter_native_delivery','status':'failed' if problems else 'passed','status_scope':legacy.SCOPE,'operation':c['operation'],'phase':c['phase'],'purpose':c['purpose'],'profile':c['profile'],'algorithm':c['algorithm'],'selection':contract['selection'],'inference':c['inference'],'source_card_quirks':contract['census'].get('source_card_quirks',[]),'problems':problems,'native_execution':receipt,'native_return':delivery,'initialized_state':initialized,'native_capsule':cap_pin,'compatibility':adaptation,'raw_census':'sfitter-raw-census.json','profile_search_qualification':'unknown','interval_qualification':'unknown','eft_applicability':'unknown','coverage_calibration':'unknown','physics_validated':False,'automatic_redo':False}
    result.update(copy.deepcopy(support_metadata))
    if derivation is not None:
        result.update(card_derivation=copy.deepcopy(c['card_derivation']),
            scientific_input_holds=copy.deepcopy(derivation.get('scientific_input_holds',[])))
    _write_committed(out/'sfitter-native.json',result,committed)
    runtime_members(c,parent)
    if before!=legacy._identity(paths):raise ValueError('original input/source/runtime/producer changed before return')
    for q,h in committed.items():_read(q,h)
    # Return a detached value derived from the exact intended durable bytes.
    return _read(out/'sfitter-native.json',committed[out/'sfitter-native.json'])

def _validate_runtime(observed,request,legacy_request):
    from . import sfitter_native as legacy
    if observed.get('runtime_assets')!=request['runtime_assets'] or observed.get('support_files')!=request['support_files'] or observed.get('schema_version')!=2:raise ValueError('complete native support/source runtime differs')
    old={k:v for k,v in observed.items() if k!='support_files'};old['schema_version']=1;old['runtime_assets']=legacy_request['runtime_assets']
    return legacy.validate_runtime(old,legacy_request)
