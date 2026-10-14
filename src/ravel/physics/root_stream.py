"""Ordinary approved ROOT streaming, with source-only site preparation."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, unquote
from ravel.physics import root_stream_core as core
from ravel.physics import dataset_query_quantities as custody

SCOPE = core.SCOPE


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def write_new(path, value):
    raw = encoded(value); path = Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)): raise ValueError('ordinary publication path required')
    with path.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
    pin = {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    if core.Capture().read(pin,path.parent,max(core.MAX_DOCUMENT if hasattr(core,'MAX_DOCUMENT') else 8*1024**2,len(raw)))[1] != raw:
        raise ValueError('intended publication differs')
    return pin


def census(root):
    root=custody._ordinary(root,Path.cwd(),directory=True);rows={}
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):raise ValueError('complete ordinary directory/file census required')
        rows[p.relative_to(root).as_posix()]=({'kind':'directory'} if p.is_dir() else {'kind':'file','sha256':custody.custody._hash(p),'size':p.stat().st_size})
    return rows


def validate(task):
    core.keys(task, ('config', *(['read_contract'] if 'read_contract' in task else [])), 'ROOT stream task')
    core.pin(task['config'])
    if 'read_contract' in task: core.pin(task['read_contract'])
    return task


def _load(task, base, capture):
    validate(task); path, raw = capture.read(task['config'],base)
    c = core.config(core.strict(raw)); base = path.parent
    if c['schema_version']==2:
        from ravel.physics import root_stream_partitions as partitions
        master=partitions.read_master(c['partitioning']['master'],base,capture);base=Path(master['base_config']['path']).parent
    ds = core.dataset(capture.document(c['dataset'],base))
    authority = capture.document(ds['membership_authority'],base)
    core.keys(authority, ('schema_version','samples'), 'full membership authority')
    core.require(type(authority['schema_version']) is int and authority['schema_version']==1 and authority['samples']==ds['samples'], 'dataset differs from full source membership record')
    a = core.analysis(capture.document(c['analysis'],base),ds)
    if 'derived_factor' in a['weight_contract']:
        factor = a['weight_contract']['derived_factor']
        core.require(factor['entry'] == c['bundle']['entry'] and
                     factor['source'] == c['bundle']['files'][factor['entry']],
                     'derived nominal factor must be the exact admitted kernel source')
        capture.read(factor['source'],base)
    capture.read(a['original_goal'],base); capture.read(c['bundle']['review_source'],base)
    core.require(c['bundle']['blind_entry']==(None if a['blinding'] is None else a['blinding']['blind_entry']), 'MC/data conditional blind entry differs')
    if a['blinding'] is not None:
        blind=a['blinding'];policy=capture.document(blind['source'],base)
        core.keys(policy,('schema_version','kind','domain_id','original_goal_sha256','allowed_regions','model_fields','protected_regions','review_source'),'immutable original blind domain')
        core.require(type(policy['schema_version']) is int and policy['schema_version']==1 and policy['kind']=='root-stream-blind-domain' and
                     policy['original_goal_sha256']==a['original_goal']['sha256'] and policy['allowed_regions']==blind['allowed_regions'] and policy['model_fields']==blind['model_fields'],
                     'original blind-domain source/fields differ')
        core.text(policy['domain_id']);core.require(type(policy['protected_regions']) is list and policy['protected_regions'] and
            not set(policy['protected_regions'])&set(policy['allowed_regions']),'original protected SR must remain disjoint')
        capture.read(policy['review_source'],base)
    for sample in ds['samples']:
        n = sample['normalization']
        if n is not None:
            original = capture.document(n['original_population'],base)
            core.keys(original, ('schema_version','sample_id','dsid','members'), 'original normalization population')
            core.require(original['schema_version']==1 and type(original['schema_version']) is int and original['sample_id']==sample['id'] and original['dsid']==sample['dsid'], 'original normalization sample differs')
            core.require(type(original['members']) is list and original['members'], 'full original normalization members required')
            rows={}
            for row in original['members']:
                core.keys(row, ('guid','did','entries'), 'original member exposure')
                core.text(row['guid']); core.text(row['did']); core.integer(row['entries'],0,10**15,'original entries')
                core.require(row['guid'] not in rows,'original member duplicate'); rows[row['guid']]=row
            for member in sample['members']:
                core.require(rows.get(member['guid'])=={k:member[k] for k in ('guid','did','entries')}, 'processed source is not bound to original normalization population')
            record=capture.document(n['source'],base)
            fields=('schema_version','sample_id','dsid','original_population_sha256','sum_weights','luminosity_fb_inverse','cross_section_pb','filter_efficiency','k_factor')
            core.keys(record,fields,'original full normalization record')
            core.require(record['schema_version']==1 and type(record['schema_version']) is int and record['sample_id']==sample['id'] and record['dsid']==sample['dsid'] and record['original_population_sha256']==n['original_population']['sha256'], 'normalization origin differs')
            for name in fields[4:]: core.require(record[name]==n[name] and type(record[name]) in (int,float), 'normalization source value differs')
        for member in sample['members']:
            capture.read(member['checksum']['authority'],base)
            u=urlsplit(member['uri'])
            if u.scheme=='root': core.require(u.hostname in c['site']['allowed_hosts'], 'initial remote host outside declared site policy')
    for p in c['bundle']['files'].values(): capture.read(p,base)
    if c['schema_version']==2:
        partitions.bound_master(c,ds,a,base,capture)
        if c['partitioning']['operation']=='merge':partitions._completions(c,ds,a,base,capture)
    if 'read_contract' in task:
        from ravel.workflow import data_read_outcomes
        core.require(c['schema_version']==1, 'typed read outcomes require an original full ROOT acquisition; partition execution remains a separate contract')
        data_read_outcomes.bound_contract(task['read_contract'],task,c,ds,a,base,capture)
    return path,c,ds,a


def source_base(c,base):
    if c.get('schema_version')==2:
        from ravel.physics.root_stream_partitions import input_base
        return input_base(c,base)
    return Path(base)


def runtime(c,base,capture):
    """Complete generic source trees; IRIS's ServiceX API requirement stays intact."""
    assets={}; roots=[]; total=0
    for t in c['runtime']['trees']:
        root=custody._ordinary(t['root'],base,directory=True)
        core.require(not any(root==r or root.is_relative_to(r) or r.is_relative_to(root) for r in roots),'disjoint runtime roots required')
        roots.append(root); doc=core.strict(capture.read(t['manifest'],base,32*1024**2)[1])
        core.keys(doc,('schema_version','files'),'runtime manifest')
        core.require(type(doc['schema_version']) is int and doc['schema_version']==1 and type(doc['files']) is dict and doc['files'],'complete runtime manifest1 required')
        for name,row in doc['files'].items():
            core.relative(name);core.keys(row,('sha256','size'),'runtime member')
            p=root/name; assets[str(p)]={'path':str(p),**row};core.pin(assets[str(p)]);total+=row['size']
    core.require(len(assets)<=64000 and total<=8*1024**3,'bounded complete runtime required')
    sites=[custody._ordinary(p,base,directory=True) for p in c['runtime']['site_roots']]
    core.require(len(set(sites))==len(sites) and all(any(p==r or p.is_relative_to(r) for r in roots) for p in sites),'runtime site roots outside captured trees')
    python,_=capture.read(c['runtime']['python'],base,64*1024**2)
    core.require(os.access(python,os.X_OK),'explicit executable interpreter required')
    assets[str(python)]={**c['runtime']['python'],'path':str(python)}
    custody.closed_assets(assets,roots)
    return assets,roots,sites,python


def inputs(task,base):
    capture=core.Capture();p,c,ds,_=_load(task,base,capture)
    assets,_,_,_=runtime(c,source_base(c,p.parent),capture)
    custody.asset_check(assets)
    # Authenticate declared local scientific members via streaming descriptors,
    # not the finite document/runtime pin schema. Adler32 is checked as Adler32;
    # an additional SHA256 is retained for ordinary input snapshot correspondence.
    from ravel.physics.root_stream_worker import local_member_pin
    local=[]
    for s in ds['samples']:
        for m in s['members']:
            if urlsplit(m['uri']).scheme=='file':local.append(Path(local_member_pin(m)['path']))
    capture.finish()
    return sorted({*capture.rows,*map(Path,assets),*local})


def execution_seconds(task,base):
    capture=core.Capture();c=_load(task,base,capture)[1];capture.finish();return c['limits']['max_seconds']


def validate_scope(spec):
    p=spec.get('review_policy',{}).get('policy',{})
    core.require(spec.get('schema_version')==2 and spec.get('max_attempts')==1 and p.get('max_redos')==0 and set(p.get('claim_scopes',{}))=={SCOPE} and p['claim_scopes'][SCOPE].get('actions')==['delivery'],'one-attempt delivery-only ROOT scope required')
    return spec


def context_inputs(task,base):
    capture=core.Capture();_load(task,base,capture);capture.finish();return sorted(capture.rows)


def context(task,base):
    capture=core.Capture();_,c,ds,a=_load(task,base,capture);capture.finish()
    value={'schema_version':1,'kind':'root-stream-source-context','sample_ids':[{'id':s['id'],'kind':s['kind'],'dsid':s['dsid']} for s in ds['samples']],
        'branch_contract':a['branch_contract'],'quantity_ids':[q['id'] for q in a['quantities']],
        'blinding':None if a['blinding'] is None else {'policy':a['blinding']['policy'],'allowed_regions':a['blinding']['allowed_regions'],'model_fields':a['blinding']['model_fields'],'original_policy_sha256':a['blinding']['source']['sha256']},
        'site':{k:c['site'][k] for k in ('id','rse','durable_output_policy')},'limits':c['limits'],
        'input_pins':list(capture.rows.values()),'data_values_or_sr_counts_presented':False,
        'execution_authorized':False,'physics_validated':False,
        'limitations':['Runtime, credentials, data access and source-law accuracy require actual ordinary qualification.','Remote checksum is authoritative metadata evidence, not an atomic whole-file byte snapshot.']}
    if 'read_contract' in task:
        value['read_contract']=deepcopy(task['read_contract'])
        value['read_outcomes_visibility']='complete machine record; public summary contains no DATA entry census'
    if c['schema_version']==2:
        value['input_pins']=[]
        value['restricted_partition_input_witness']={'sha256':core.digest(list(capture.rows.values())),'complete':True,'visibility':'machine_records_not_model_census'}
    return value



def ordinary_plan_destination(rundir):
    """Resolve the actual initial or selected stage of a current science plan.

    Schema-2 plan documents have no top-level output_directory. Before an
    attempt the verified original stage is prospective; afterwards _selected
    authenticates the retained spent token and exact correction stage.
    """
    from ravel.workflow import science
    rd=science.root(rundir)
    with science._validation_scope(rd) as session:
        plan=science.verify_plan(rd,approved=False,_session=session)
        spec=science.execution_spec(rd,_proposal=plan,_session=session)
        if plan['schema_version']==2 and os.path.lexists(rd/'execution_attempt.json'):
            stage,_,_=science._selected(rd,plan,_session=session)
        else:
            core.require(len(plan['stages'])==1,'one original ordinary science stage required')
            stage=plan['stages'][0]
        core.require(type(stage['outputs']) is list and len(stage['outputs'])==1,'one actual stage destination required')
        destination=stage['outputs'][0]
        core.require(type(destination) is str and destination and not Path(destination).is_absolute() and
            '..' not in Path(destination).parts,'actual ordinary relative output destination required')
        return plan,spec,destination


def ordinary_delivery(rundir, *, expected_output=None, expected_task=None):
    """Read the existing successful ordinary attempt, not caller status bits.

    This authenticates delivery/admission and its complete current census. It
    grants neither independent scientific acceptance nor a new execution right.
    """
    from ravel.workflow import science
    rd=science.root(rundir)
    with science._validation_scope(rd) as session:
        plan=science.verify_plan(rd,approved=True,_session=session)
        stage,binding,_=science._selected(rd,plan,_session=session)
        spec=science.execution_spec(rd,_proposal=plan,_session=session)
        out=(rd/stage['outputs'][0]).absolute()
        if expected_output is not None:
            core.require(out==Path(expected_output).absolute(),'actual selected ordinary destination differs')
        if expected_task is not None:
            core.require(spec['mode']=='root-stream' and spec['task']==expected_task,'actual delivered ROOT task differs')
        # These existing consumers authenticate the original attempt token,
        # approval, launch/admission, succeeded execution and complete outputs.
        paths=science.review_waypoint_paths(rd,_session=session)
        errors=science.execution.validate_completed_execution(rd,[stage],_session=session)
        core.require(not errors,'actual original successful ordinary execution required')
        cap=core.Capture()
        pins=[];values=[]
        for name in ('result.json','verification.json'):
            path=out/name
            declaration={'path':str(path),'sha256':custody.custody._hash(path),'size':path.stat().st_size}
            values.append(core.strict(cap.read(declaration,out,max(8*1024**2,declaration['size']))[1]));pins.append(declaration)
        result,view=values
        core.require(result.get('status')=='passed' and result.get('physics_validated') is False and
            view.get('passed') is True and view.get('scope')==spec['mode'] and
            view.get('physics_validated') is False and view.get('expert_review') is False and
            view.get('result_sha256')==pins[0]['sha256'],'ordinary verification must bind the actual delivered result')
        cap.finish()
        # Ending reads cannot substitute a different successful census.
        core.require(science.review_waypoint_paths(rd,_session=session)==paths,'ending ordinary delivery membership differs')
        cap.finish()
        return {'rundir':str(rd),'output_directory':str(out),'mode':spec['mode'],
                'outputs':pins,'result':result,'verification':view,'fingerprint':binding['fingerprint'],
                'scientific_acceptance_inferred':False}


def ordinary_stream_delivery(result,destination,task):
    """Require the selected successful ROOT producer for the exact raw table."""
    from ravel.workflow import science
    out=Path(destination).absolute()
    for rd in out.parents:
        if not (rd/science.PLAN).is_file():continue
        receipt=ordinary_delivery(rd,expected_output=out.parent,expected_task=task)
        core.require(receipt['result']==result,'table is not the actual succeeded ordinary ROOT result')
        return receipt
    raise ValueError('actual ordinary ROOT delivery origin required')


def model_artifact_source(source_path,source_sha256):
    """Classify an actual producer artifact before any text/binary presentation.

    Role copies retain their authenticated original source identity. No extension,
    JSON discriminator or caller-supplied visibility bit supplies this authority.
    This does not classify arbitrary text copied outside its original provenance.
    """
    from ravel.workflow import science
    source=Path(source_path).absolute()
    from ravel.physics.root_stream_partitions import private_source
    private_source(source,source_sha256)
    for rd in source.parents:
        if not os.path.lexists(rd/science.PLAN):
            # Missing authority cannot erase a genuine retained producer
            # namespace. These exact original science records also survive
            # renamed PLAN files; never inline its private ledger as external.
            retained=any(os.path.lexists(rd/name) for name in
                (science.SPEC,science.EXECUTION_TASK,science.REVIEW_POLICY))
            core.require(not retained,'retained scientific producer namespace lacks its original plan')
            continue
        with science._validation_scope(rd) as session:
            plan=science.verify_plan(rd,approved=False,_session=session)
            spec=science.execution_spec(rd,_proposal=plan,_session=session)
            if spec['mode']!='root-stream':continue
            if os.path.lexists(rd/'execution_attempt.json'):
                stage,_,_=science._selected(rd,plan,_session=session)
            else:
                core.require(len(plan['stages'])==1,'one original ordinary science stage required')
                stage=plan['stages'][0]
            core.require(type(stage['outputs']) is list and len(stage['outputs'])==1,'one actual stage destination required')
            folder=(rd/stage['outputs'][0]).absolute()
            public=[folder/'result.json',folder/'root-stream-report.json',folder/'root-stream-report.md']
            # All genuine native/request/ledger/closure and original input records
            # remain machine-only, independently of their contents or copy name.
            core.require(source in public,'restricted root-stream producer artifacts cannot enter model context')
            receipt=ordinary_delivery(rd,expected_output=folder,expected_task=spec['task'])
            result=receipt['result'];g=guard(result,folder/'root-stream')
            full,req=private_delivery(g)
            core.require(result['delivery']==public_delivery(full,req['dataset'],req['analysis'],req['config']),'original public projection differs')
            expected=[encoded(result),encoded({'status':result['status'],'delivery':result['delivery'],'physics_validated':False}),report_bytes(result)]
            cap=core.Capture()
            for path,raw in zip(public,expected):
                declaration={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
                cap.read(declaration,folder,max(8*1024**2,len(raw)))
                if path==source:core.require(source_sha256==declaration['sha256'],'model source differs from authenticated allowed projection')
            cap.finish();g.finish(result,common=folder)
            core.require(ordinary_delivery(rd,expected_output=folder,expected_task=spec['task'])==receipt,'ending allowed-public producer differs')
            cap.finish()
            return 'original_allowed_public_projection'
    return 'outside_root_stream_producer_namespace'


def model_input_text(text, *, source_path=None, source_sha256=None):
    """Reject typed internal DATA records before ordinary model presentation.

    This is a narrow contract for actual root-stream schemas, not arbitrary text
    taint tracking or a sandbox. Tool-only original source pins stay admissible.
    Model nodes must consume root-stream-context or allowed aggregate outputs.
    """
    if source_path is not None:
        core.require(type(source_sha256) is str,'authenticated model source digest required')
        model_artifact_source(source_path,source_sha256)
    try:value=core.strict(text.encode())
    except (ValueError,TypeError,UnicodeError):return text
    def visit(row):
        if type(row) is dict:
            if row.get('kind')=='data':
                core.require(set(row)=={'id','kind','quantities','visibility'} and row['visibility']=='original_allowed_CR_VR_aggregates_only',
                    'restricted DATA population/moment state cannot enter ordinary model context')
                for q in row['quantities'].values():
                    core.keys(q,('kind','bins','axes','unit','weight_names','values','covariance','physics_validated'),'allowed public data fields')
                    core.require(q['kind']=='allowed-data-aggregates' and q['physics_validated'] is False,'source-defined public data projection required')
            if row.get('kind') in ('root-stream-partition-moments','root-stream-partition-master','root-stream-private-partition-plan','root-stream-private-merge-plan','root-stream-ordinary-partition-completion','physical-event-groups','root-stream-master-attempt-genesis','root-stream-master-attempt-claim'):
                raise ValueError('restricted original partition/group machine record cannot enter model context')
            if row.get('kind')=='typed-data-read-outcomes':
                raise ValueError('complete typed read population is a restricted machine record')
            if row.get('kind')=='root-stream-moments':
                core.require(not any(s.get('kind')=='data' for s in row.get('samples',[])),'restricted DATA census cannot enter ordinary model context')
            for child in row.values():visit(child)
        elif type(row) is list:
            for child in row:visit(child)
    visit(value);return text


def public_delivery(native,ds,a,request_config=None):
    """Fixed allowlist projection; complete DATA census remains machine-private."""
    validate_delivery(native,ds,a,{'max_chunks':10**7,'chunk_entries':10**6},request_config)
    if request_config is not None and request_config.get('schema_version')==2 and request_config['partitioning']['operation']=='partition':
        from ravel.physics import root_stream_partitions as partitions
        cap=core.Capture();m=partitions.bound_master(request_config,ds,a,Path(request_config['partitioning']['master']['path']).parent,cap)
        part=next(x for x in m['partitions'] if x['id']==request_config['partitioning']['partition_id'])
        projected=partitions.public_partial(native,m,part,ds,a,request_config['limits']);cap.finish();return projected
    full=native['delivery'];data_ids={s['id'] for s in ds['samples'] if s['kind']=='data'}
    data_members={m['id'] for s in ds['samples'] if s['kind']=='data' for m in s['members']}
    result={'schema_version':1,'kind':'root-stream-public-moments','samples':[],'mc_coverage':[deepcopy(r) for r in full['coverage'] if r['sample'] not in data_ids],
            'mc_identities':[deepcopy(r) for r in native['identities'] if r['member'] not in data_members],
            'data_completeness_witnesses':[],'sampling_law':full['sampling_law'],'physics_validated':False}
    for sample,row in zip(ds['samples'],full['samples']):
        if sample['kind']!='data':result['samples'].append(deepcopy(row));continue
        blind=a['blinding'];public={'id':row['id'],'kind':'data','quantities':{},'visibility':'original_allowed_CR_VR_aggregates_only'}
        for name,q in row['quantities'].items():
            allowed=blind['model_fields'][name];bins=q['contract']['bins'];indices=[[b['id'] for b in bins].index(x) for x in allowed]
            order=[w*len(bins)+i for w in range(len(q['contract']['weight_names'])) for i in indices]
            public['quantities'][name]={'kind':'allowed-data-aggregates','bins':[deepcopy(bins[i]) for i in indices],
                'axes':deepcopy(q['contract']['axes']),'unit':q['contract']['normalization']['unit'],'weight_names':deepcopy(q['contract']['weight_names']),
                'values':{w:[q['values'][w][i] for i in indices] for w in q['contract']['weight_names']},
                'covariance':[[q['covariance'][i][j] for j in order] for i in order],'physics_validated':False}
        private={'sample':sample,'intervals':[r for r in full['coverage'] if r['sample']==sample['id']],
                 'identities':[r for r in native['identities'] if r['member'] in {m['id'] for m in sample['members']}],'complete_moments':row}
        result['data_completeness_witnesses'].append({'sample':sample['id'],'original_policy_sha256':blind['source']['sha256'],
            'restricted_census_sha256':core.digest(private),'complete':True,'visibility':'restricted_machine_record_not_model_evidence'})
        result['samples'].append(public)
    return result


def read_request(capture,pin,base):
    core.require(pin['size']<=64*1024**2,'complete request metadata allocation exceeded')
    request=core.strict(capture.read(pin,base,64*1024**2)[1])
    core.require(pin['size']<=(64 if request['config'].get('schema_version')==2 else 32)*1024**2,'original request schema allocation exceeded')
    return request


def private_delivery(guard):
    """Only trusted source-bound statistical/check consumers read this record."""
    core.require(guard.native_pin is not None and guard.request_pin is not None,'original complete native source required')
    capture=core.Capture();req=read_request(capture,guard.request_pin,guard.out)
    full=core.strict(capture.read(guard.native_pin,guard.out,max(8*1024**2,guard.native_pin['size']))[1])
    validate_delivery(full,req['dataset'],req['analysis'],req['config']['limits'],req['config']);capture.finish()
    return full,req


def _approved(task,out):
    from ravel.workflow import science
    for rd in (out,*out.parents):
        if (rd/science.PLAN).is_file():
            plan=science.verify_worker(rd);spec=science.execution_spec(rd);validate_scope(spec)
            core.require(spec['mode']=='root-stream' and spec['task']==task and out==(rd/plan['output_directory']/'root-stream').absolute(),'actual selected ordinary ROOT worker required')
            return rd,plan
    raise ValueError('actual approved ordinary ROOT worker required')


def run(task,base,output):
    from contextlib import nullcontext
    out=Path(output).absolute();rd,plan=_approved(task,out)
    capture=core.Capture();p,c,ds,a=_load(task,base,capture)
    core.require(c['limits']['max_seconds']<=plan['max_seconds'],'native limit exceeds ordinary approval')
    if c['schema_version']==2:
        from ravel.physics import root_stream_partitions as partitions
        partitions.claim_dispatch(c,ds,a,source_base(c,p.parent),rd)
    before={str(q):custody.custody._hash(q) for q in inputs(task,base)}
    assets,roots,sites,python=runtime(c,source_base(c,p.parent),capture)
    core.require(not out.exists(),'fresh stream output required');custody._ordinary(out.parent,rd,directory=True)
    out.mkdir();native=out/'native';native.mkdir();source=native/'source';source.mkdir()
    for name,declaration in c['bundle']['files'].items():
        _,raw=capture.read(declaration,source_base(c,p.parent));q=source/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw)
        assets[str(q)]={'path':str(q),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    package=Path(__file__).parents[2]
    for q in package.rglob('*'):
        core.require(not q.is_symlink(),'helper source alias refused')
        if q.is_file(): assets[str(q)]={'path':str(q),'sha256':custody.custody._hash(q),'size':q.stat().st_size}
    roots=[*roots,package,source]
    driver=Path(__file__).with_name('root_stream_worker.py')
    c=deepcopy(c)
    if c['schema_version']==1:c['runtime']['site_roots']=[str(p) for p in sites]
    req={'config':c,'dataset':ds,'analysis':a,'bundle_directory':str(source),'output':str(native),
         'source_root':str(package),'runtime_assets':assets,'closed_roots':[str(r) for r in roots]}
    core.require(len(encoded(req))<=(64 if c['schema_version']==2 else 32)*1024**2,'complete isolated request exceeds declared bootstrap bound')
    req_pin=write_new(native/'request.json',req);capture.finish();custody.closed_assets(assets,roots)
    from ravel.physics.reinterpret_db import execute_native
    errors=[];delivery=None;native_pin=None;receipt=None
    try:
        # Stage first, then freshly admit and serialize the actual effect in
        # the worker. The parent does not hold this lock while we claim work.
        boundary=partitions.effect_dispatch(c,ds,a,source_base(c,p.parent),rd) if c.get('schema_version')==2 else nullcontext()
        with boundary:
            if c.get('schema_version')==2 and c['partitioning']['operation']=='merge':
                from ravel.physics import root_stream_partitions as partitions
                merged=partitions.merge(c,ds,a,source_base(c,p.parent))
                write_new(native/'native-result.json',merged)
                receipt={'kind':'ordinary_complete_raw_partition_merge','external_native_calls':0,'physics_validated':False}
            else:receipt=execute_native([str(python),'-I','-B',str(driver),req_pin['path'],req_pin['sha256']],native,c['limits'])
        q=native/'native-result.json';native_pin={'path':str(q),'sha256':custody.custody._hash(q),'size':q.stat().st_size}
        delivery=core.strict(core.Capture().read(native_pin,native,max(8*1024**2,c['limits']['max_output_bytes']))[1])
        core.keys(delivery,('schema_version','status','delivery','identities','physics_validated'),'native stream result')
        core.require(delivery['schema_version']==1 and type(delivery['schema_version']) is int and delivery['status']=='passed' and delivery['physics_validated'] is False,'explicit source-only native result required')
        validate_delivery(delivery,ds,a,c['limits'],c)
    except (OSError,ValueError,RuntimeError,KeyError,TypeError): errors.append('native_or_delivery_refused');delivery=None
    # Original inputs are re-read before the final original native result pin.
    try:
        custody.closed_assets(assets,roots);capture.finish()
        core.require(before=={str(q):custody.custody._hash(q) for q in inputs(task,base)},'ending original input source differs')
        core.Capture().read(req_pin,native,max(8*1024**2,req_pin['size']))
        if native_pin is not None: core.Capture().read(native_pin,native,max(8*1024**2,c['limits']['max_output_bytes']))
    except (OSError,ValueError,KeyError,TypeError):errors.append('ending_custody_refused');delivery=None
    value={'schema_version':1,'kind':'root-stream-result','status':'failed' if errors else 'passed','physics_validated':False,
           'status_scope':SCOPE,'delivery':None if delivery is None else public_delivery(delivery,ds,a,c),'errors':errors,'native_receipt':receipt,
           'limitations':['Remote identities are source/endpoint metadata evidence, not a server lock or full byte SHA256.','Independent-event moment law and source normalization are conditional; no physics, detector, background-model or sensitivity qualification.']}
    if 'read_contract' in task:
        from ravel.workflow import data_read_outcomes
        record=data_read_outcomes.reader_record(task,source_base(c,p.parent),c,ds,a,out=out,
            run_directory=rd,plan=plan,native_delivery=delivery,native_request=req_pin,
            native_receipt=receipt,input_hashes=before,errors=errors)
        value['read_outcomes']=write_new(native/'read-outcomes.json',record)
        value['read_summary']=data_read_outcomes.public_summary(record)
    pin=write_new(out/'root-stream-result.json',value)
    guard=Guard(value,out,inputs=before,native_pin=native_pin,request_pin=req_pin,native_outputs=census(native))
    closure=guard.closure();cp=write_new(out/'closure.json',closure)
    result={**deepcopy(value),'commitment':cp};guard.commitment=deepcopy(cp);guard.finish(result)
    return result


def validate_delivery(value,ds,a,limits,request_config=None):
    grouped=False;master=None
    if request_config is not None and request_config.get('schema_version')==2:
        from ravel.physics import root_stream_partitions as partitions,root_stream_partition_core as partition_core
        cap=core.Capture();master=partitions.bound_master(request_config,ds,a,Path(request_config['partitioning']['master']['path']).parent,cap)
        if request_config['partitioning']['operation']=='partition':
            part=next(x for x in master['partitions'] if x['id']==request_config['partitioning']['partition_id'])
            partitions.validate_partial(value,master,part,ds,a,limits);cap.finish();return
        core.require(value==partitions.merge(request_config,ds,a,source_base(request_config,Path.cwd())),'full merge differs from complete original raw ordinary completions')
        grouped=master['grouping']['kind']=='declared_groups';cap.finish()

    core.keys(value,('schema_version','status','delivery','identities','physics_validated'),'native result')
    core.require(type(value['schema_version']) is int and value['schema_version']==1 and value['status']=='passed' and value['physics_validated'] is False,'explicit native delivery status required')
    d=value['delivery'];core.keys(d,('schema_version','kind','samples','coverage','coverage_sha256','sampling_law','blinding','physics_validated',*(['physical_grouping'] if grouped else [])),'whole stream moments')
    core.require(d['schema_version']==1 and type(d['schema_version']) is int and d['sampling_law']==(partition_core.GROUP_LAW if grouped else 'poissonized_independent_physical_events_with_event_common_weights'),'declared independent physical event law required')
    core.require(type(d) is dict and d.get('kind')=='root-stream-moments' and d.get('physics_validated') is False,'stream moments required')
    core.require(type(d.get('coverage')) is list and len(d['coverage'])<=limits['max_chunks'] and d.get('coverage_sha256')==core.digest(d['coverage']),'original bounded interval commitment required')
    index=0;offset=0;members=[(s,m) for s in ds['samples'] for m in s['members']]
    for row in d['coverage']:
        core.keys(row,('sample','member','start','stop'),'source interval')
        core.require(index<len(members),'extra source interval')
        s,m=members[index];start,stop=row['start'],row['stop']
        core.require(type(start) is int and type(stop) is int and (row['sample'],row['member'],start)==(s['id'],m['id'],offset) and
                     (start<stop<=m['entries'] or start==stop==m['entries']==0) and stop-start<=limits['chunk_entries'],'source interval gap/overlap/order refused')
        offset=stop
        if stop==m['entries']:index+=1;offset=0
    core.require(index==len(members) and offset==0,'missing original source intervals')
    core.require([r.get('id') for r in d.get('samples',[])]==[s['id'] for s in ds['samples']],'whole sample population differs')
    core.require(type(value['identities']) is list and len(value['identities'])==len(members),'complete remote/local identity population required')
    for (s,m),r in zip(members,value['identities']):
        core.keys(r,('member','before','after','evidence_scope'),'member identity')
        expected={'guid':m['guid'],'size_bytes':m['size_bytes'],'checksum':{'algorithm':m['checksum']['algorithm'],'value':m['checksum']['value']},'entries':m['entries']}
        core.require(r['member']==m['id'] and r['before']==expected and r['after']==expected,'native observed member identity differs')
    for s,r in zip(ds['samples'],d['samples']):
        core.keys(r,('id','kind','dsid','normalization','raw_mc_weights','weight_contract','quantities'),'whole sample delivery')
        raw=r['raw_mc_weights']
        if s['kind']=='data':core.require(raw is None,'data cannot acquire MC weights')
        else:
            core.keys(raw,('sumw','sumw2','scope',*(['record_sumw2'] if grouped else [])),'original analyzed MC weights')
            core.scalar(raw['sumw']);core.require(core.scalar(raw['sumw2'])>=0 and raw['scope']==('complete declared physical groups; record_sumw2 retains original entry squares; full denominator is separate' if grouped else 'analyzed original entries; retained full denominator is separate'),'original raw MC moment scope differs')
        core.require(r.get('normalization')==s['normalization'] and r.get('kind')==s['kind'] and r.get('dsid')==s['dsid'] and r.get('weight_contract')==a['weight_contract'],'sample normalization/weight law differs')
        core.require(set(r.get('quantities',{}))=={q['id'] for q in a['quantities']},'complete quantities required')
        for q in a['quantities']:
            result=r['quantities'][q['id']];c=deepcopy(q['contract']);c['normalization']['scale']=core.scale(s)
            core.require(result.get('contract')==c and result.get('kind')=='stream_weighted_quantities' and result.get('physics_validated') is False,'sample global normalization differs')
            state=result['state'];core.keys(state,('sumw','second_moment','counts','negative_weight_records'),'complete bounded moment state')
            dimensions=(len(c['bins'])+2)*len(c['weight_names'])
            core.require(type(state['sumw']) is list and len(state['sumw'])==dimensions and type(state['second_moment']) is list and len(state['second_moment'])==dimensions,'complete moment dimensions required')
            for i,row in enumerate(state['second_moment']):
                core.require(type(row) is list and len(row)==dimensions,'complete second moment dimensions required')
                for j,x in enumerate(row):
                    core.scalar(x);core.require(x==state['second_moment'][j][i] and (i!=j or x>=0),'symmetric nonnegative-diagonal event moments required')
            for x in state['sumw']:core.scalar(x)
            counts=state['counts'];core.keys(counts,('records','fills','in_range','flow','empty_records'),'full event/fill counts')
            for n,x in counts.items():core.integer(x,0,10**18,'event count')
            total=(sum(g['sample']==s['id'] for g in master['groups']) if grouped else sum(m['entries'] for m in s['members']))
            core.require((counts['records']==total if s['kind']!='data' else counts['records']<=total) and counts['empty_records']<=counts['records'] and counts['fills']==counts['in_range']+counts['flow'],'complete MC/data exposure differs')
            core.keys(state['negative_weight_records'],c['weight_names'],'all weight negative counts')
            for x in state['negative_weight_records'].values():core.integer(x,0,counts['records'],'negative count')
            expected=core.quantities._project(c,state)
            core.keys(result,(*expected,'identity_scope'),'full projected stream quantity')
            core.require(result['identity_scope']==(partition_core.IDENTITY if grouped else 'authenticated complete member-entry interval census; one independent physical event per source entry'),'source event identity scope differs')
            for key in expected:core.require(result.get(key)==( 'stream_weighted_quantities' if key=='kind' else expected[key]),'native full projection differs')
            for key in ('values','covariance','flow','denominators','state_sha256','contract_sha256','counts'):
                if key in expected:core.require(result.get(key)==expected[key],'native moment projection differs')


class Guard:
    """Invocation-local original publication authority, retained before callbacks."""
    def __init__(self,value,out,*,inputs=None,native_pin=None,request_pin=None,native_outputs=None):
        self.out=Path(out).absolute();self.raw=encoded(value)
        self.inputs=deepcopy(inputs or {});self.native_pin=deepcopy(native_pin);self.request_pin=deepcopy(request_pin)
        self.native_outputs=deepcopy(native_outputs or {});self.commitment=None;self.publications=[]
    def closure(self):
        return {'schema_version':1,'result_sha256':hashlib.sha256(self.raw).hexdigest(),'inputs':self.inputs,'native_pin':self.native_pin,'request_pin':self.request_pin,'native_outputs':self.native_outputs}
    def finish(self,result,common=None):
        value={k:v for k,v in result.items() if k!='commitment'}
        core.require(encoded(value)==self.raw,'live returned result differs from intended result')
        cp=result['commitment'];core.require(cp==self.commitment and cp['path']==str(self.out/'closure.json'),'original canonical closure is nonreplaceable')
        capture=core.Capture()
        request=None if self.request_pin is None else read_request(capture,self.request_pin,self.out)
        maximum=(64 if request is not None and request['config'].get('schema_version')==2 else 8)*1024**2
        core.require(cp['size']<=maximum,'complete closure metadata allocation exceeded')
        _,raw=capture.read(cp,self.out,max(8*1024**2,cp['size']))
        core.require(core.strict(raw)==self.closure(),'original complete closure differs')
        result_pin={'path':str(self.out/'root-stream-result.json'),'sha256':hashlib.sha256(self.raw).hexdigest(),'size':len(self.raw)}
        capture.read(result_pin,self.out,max(8*1024**2,len(self.raw)))
        for p,h in self.inputs.items(): core.require(custody.custody._hash(Path(p))==h,'ending original source differs')
        if self.request_pin:capture.read(self.request_pin,self.out,max(8*1024**2,self.request_pin['size']))
        if self.native_pin:
            capture.read(self.native_pin,self.out,max(8*1024**2,self.native_pin['size']))
            if value['status']=='passed':
                full,req=private_delivery(self)
                core.require(value['delivery']==public_delivery(full,req['dataset'],req['analysis'],req['config']),'original public blind projection differs')
            else:core.require(value.get('delivery') is None,'failed partial native data cannot be published')
        if common is not None:
            path=Path(common)/'result.json';captured=core.Capture();p,raw=captured.read({'path':str(path),'sha256':custody.custody._hash(path),'size':path.stat().st_size},path.parent,max(8*1024**2,path.stat().st_size))
            core.require(core.strict(raw)==result,'ordinary durable result differs from original live result');captured.finish()
        capture.finish()
        # Original output content and membership are checked after ending reads.
        custody.asset_check({p['path']:p for p in [cp,result_pin,*self.publications]})
        core.require({p.name for p in self.out.iterdir()}=={'native','root-stream-result.json','closure.json'},'own output membership differs')
        core.require(census(self.out/'native')==self.native_outputs,'complete native output member/content census differs')
        if common is not None:
            p=Path(common)/'result.json';expected=encoded(result)
            capture.read({'path':str(p),'sha256':hashlib.sha256(expected).hexdigest(),'size':len(expected)},p.parent,max(8*1024**2,len(expected)))
        return True


def guard(result,destination):
    cp=result['commitment'];out=Path(destination).absolute()
    core.require(cp['path']==str(out/'closure.json'),'canonical original closure required')
    core.require(cp['size']<=64*1024**2,'complete closure metadata allocation exceeded')
    capture=core.Capture();closure=core.strict(capture.read(cp,out,max(8*1024**2,cp['size']))[1]);capture.finish()
    core.keys(closure,('schema_version','result_sha256','inputs','native_pin','request_pin','native_outputs'),'original complete closure')
    g=Guard({k:v for k,v in result.items() if k!='commitment'},out,inputs=closure['inputs'],native_pin=closure['native_pin'],request_pin=closure['request_pin'],native_outputs=closure['native_outputs'])
    g.commitment=deepcopy(cp)
    core.require(g.closure()==closure,'returned original closure differs');g.finish(result);return g


def report_bytes(result):
    return ('\n'.join(['# ROOT streaming delivery','',result['status']+'. Source/native and scientific qualification remain separate.','',*result['limitations']])+'\n').encode()


def blinding_check(result,destination,public_paths,accepted_policy):
    """Genuine fixed packet projection check, not a caller's pass assertion.

    The complete native/request/census/closure are restricted machine records.
    Only these three analytical publications are eligible final model evidence.
    Arbitrary files, plots or external CERN metadata require separate review.
    """
    out=Path(destination).absolute();g=guard(result,out);full,req=private_delivery(g)
    blind=req['analysis']['blinding'];core.require(blind is not None,'actual original data blind domain required')
    cap=core.Capture();policy=cap.document(accepted_policy,out)
    core.require(accepted_policy['sha256']==blind['source']['sha256'] and accepted_policy['size']==blind['source']['size'] and
        policy['model_fields']==blind['model_fields'] and policy['allowed_regions']==blind['allowed_regions'],'accepted immutable blind domain cannot be widened')
    common=out.parent
    paths=[common/'result.json',common/'root-stream-report.json',common/'root-stream-report.md']
    core.require(type(public_paths) is list and [str(Path(x).absolute()) for x in public_paths]==[str(x) for x in paths],
        'only fixed public analytical packet roster may become model evidence; private native/census/recipe inputs refused')
    expected=[encoded(result),encoded({'status':result['status'],'delivery':result['delivery'],'physics_validated':False}),report_bytes(result)]
    for path,raw in zip(paths,expected):cap.read({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)},common,max(8*1024**2,len(raw)))
    core.require(result['delivery']==public_delivery(full,req['dataset'],req['analysis'],req['config']),'source-defined allowed public fields differ')
    cap.finish();g.finish(result,common=common)
    return {'schema_version':1,'kind':'blinding_preservation_check','policy_sha256':accepted_policy['sha256'],
        'status':'pass','sr_data_exposed':False,'checked_paths':[str(x) for x in paths]}


def write_report(result,out):
    out=Path(out)
    from .yield_hub import write_stream
    # One partition's public record holds unnormalized partial moments, not the
    # finished quantities a binned-value projection describes; the merge delivers those.
    if result['delivery']['kind']!='root-stream-public-partition':write_stream(result['delivery'], out / 'binned-values')
    pin=write_new(out/'root-stream-report.json',{'status':result['status'],'delivery':result['delivery'],'physics_validated':False})
    raw=report_bytes(result);p=out/'root-stream-report.md'
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    md={'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    custody.asset_check({str(p):md})
    return [{'stem':'root-stream-report','files':['root-stream-report.md','root-stream-report.json'],'normalization':'One original full signed MC denominator per DSID, after complete interval coverage','intended_commitments':[pin,md]}]


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',type=Path,required=True)
    args=p.parse_args(argv);capture=core.Capture()
    path=args.request.absolute();declaration={'path':str(path),'sha256':custody.custody._hash(path),'size':path.stat().st_size}
    task=capture.document(declaration,path.parent);value=context(task,path.parent);capture.finish()
    print(json.dumps(value,indent=2,sort_keys=True,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
