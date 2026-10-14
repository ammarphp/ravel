"""Authenticated MG export/static-build reuse through the ordinary event worker.

No global cache, integration checkpoint, sampler, or execution authority. A
candidate must be a current successful ordinary model-events delivery. Every
run copies into a fresh process; only the source-bound prelaunch export and LO
static Source/lib objects are eligible. The released engine still treats cards,
cleans its PDF/subprocess products, compiles and surveys normally.
"""
import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import shutil

KIND = 'authenticated-generator-export/v1'
BUILD_API = ('madgraph.interface.madevent_interface', 'MadEventCmd', 'configure_directory')


def require(ok, message):
    if not ok: raise ValueError(message)


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def identity(st):
    return [st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def regular_bytes(path, maximum):
    path=Path(path); before=path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_size<=maximum, 'bounded regular reuse member required')
    fd=os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        require(identity(os.fstat(fd))==identity(before), 'reuse member replaced before read')
        chunks=[]; size=0
        while True:
            block=os.read(fd, min(1024**2, maximum+1-size))
            if not block: break
            chunks.append(block); size+=len(block)
            require(size<=maximum, 'reuse member exceeds declared byte ceiling')
        require(identity(before)==identity(os.fstat(fd))==identity(path.lstat()), 'reuse member changed during read')
        return b''.join(chunks)
    finally: os.close(fd)


def write_bytes(path, raw):
    """Commit intended bytes before writing; a changed first reread is not a baseline."""
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), 'fresh reuse emission required')
    expected=hashlib.sha256(raw).hexdigest(); path.write_bytes(raw)
    require(regular_bytes(path,len(raw))==raw, 'intended reuse emission changed')
    return {'path':str(path),'sha256':expected,'size':len(raw)}


def write_document(path, value): return write_bytes(path, encoded(value))


def read_document(path, maximum=16*1024**2):
    def _unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'duplicate reuse field');result[key]=value
        return result
    return json.loads(regular_bytes(path, maximum),object_pairs_hook=_unique,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite reuse document')))


_EMPTY = {'kind':'lossless-empty-reuse-member/v1', 'size':0,
          'sha256':hashlib.sha256(b'').hexdigest()}
_RELEASED_MARKER_SOURCES = {
    'madgraph/iolibs/export_v4.py':'ada53ca10e4bf6b4ac11d85f5a74898871ed328f2db5a77cbed2d207d7a05e3c',
    'madgraph/various/misc.py':'2ea5ab86b66c4e01d158d10ff84975d5d1345e257a88ff4b62bff1c37d3335a1',
    'Template/LO/bin/internal/clean_template':'f6bcadb43be98c2a98c28765ca6e1bef7debde0e211270759e5dddce0fd5deb2',
    'Template/LO/Events/.keep':_EMPTY['sha256']}


def released_events_marker(root):
    """Exact released LO template/copy/finalize law; this is not event data."""
    root=Path(root); pins=[]
    for name,expected in _RELEASED_MARKER_SOURCES.items():
        path=root/name
        require(not any(p.is_symlink() for p in (path,*path.parents)), 'released marker source aliases refused')
        raw=regular_bytes(path,16*1024**2)
        require(hashlib.sha256(raw).hexdigest()==expected, 'unsupported released Events marker source')
        pins.append({'path':str(path),'sha256':expected,'size':len(raw)})
    return {'kind':'mg5_2_9_27_LO_template_Events_keep','sources':pins}


def _store_blob(path, raw):
    # No scientific file is padded or rewritten. Only storage uses an exact
    # typed envelope, so ordinary output snapshots never need a blanket zero rule.
    return {'blob':write_bytes(path,raw)} if raw else {
        'blob':write_bytes(path,encoded(_EMPTY)), 'encoding':_EMPTY['kind']}


def _blob_bytes(row, maximum):
    pin=row['blob'];raw=regular_bytes(pin['path'],maximum)
    require(type(pin['size']) is int and len(raw)==pin['size'] and
        hashlib.sha256(raw).hexdigest()==pin['sha256'], 'reuse blob changed')
    if 'encoding' not in row: return raw
    require(row['encoding']==_EMPTY['kind'] and raw==encoded(_EMPTY), 'invalid lossless empty reuse envelope')
    return b''


def model_import_path(reuse, fresh_model):
    """Observer import identity stays at origin; complete current model source stays fresh.

    Called after current probe equality and the existing copied-source custody
    checks. Full export compatibility includes every UFO/source member. An old
    approval cannot substitute for the prospective current execution approval.
    """
    if reuse is None or reuse['state'] not in ('export-reuse','export-and-static-reuse'):
        return Path(fresh_model)
    record=verify(reuse['record'])
    require(record['compatibility']['export']==reuse['compatibility']['export'], 'reused model/source association differs')
    origin=record['origin'];path=Path(origin['model_path'])
    require(path.is_absolute() and '..' not in path.parts and
        origin['process_identity']['commitment']==origin['observer_request']['commitment'] and
        origin['observer_request']['commitment']['model_import']=='import model '+str(path)+'-full',
        'reused observer belongs to foreign model import')
    return path


def validate(options):
    require(type(options) is dict and set(options)=={'candidate','max_files','max_bytes','max_member_bytes'}, 'explicit complete generator reuse policy required')
    for key, ceiling in (('max_files',100000),('max_bytes',4*1024**3),('max_member_bytes',128*1024**2)):
        require(type(options[key]) is int and 1<=options[key]<=ceiling, 'finite '+key+' required')
    require(options['max_member_bytes']<=options['max_bytes'], 'member ceiling exceeds complete reuse ceiling')
    candidate=options['candidate']
    if candidate is not None:
        require(type(candidate) is dict and set(candidate)=={'rundir','capsule_sha256'}, 'exact prior ordinary run/capsule required')
        require(type(candidate['rundir']) is str and candidate['rundir'], 'literal prior run required')
        require(type(candidate['capsule_sha256']) is str and len(candidate['capsule_sha256'])==64 and
            all(x in '0123456789abcdef' for x in candidate['capsule_sha256']), 'exact reuse capsule digest required')
    return options


def build_api(root):
    module, owner, method=BUILD_API; path=Path(root)/(module.replace('.','/')+'.py')
    raw=regular_bytes(path, 16*1024**2); tree=ast.parse(raw)
    owners=[x for x in tree.body if isinstance(x,ast.ClassDef) and x.name==owner]
    methods=[] if len(owners)!=1 else [x for x in owners[0].body if isinstance(x,ast.FunctionDef) and x.name==method]
    require(len(methods)==1, 'unsupported LO static build API')
    fn=methods[0]
    require([x.arg for x in fn.args.args]==['self','html_opening'] and len(fn.args.defaults)==1 and
        isinstance(fn.args.defaults[0],ast.Constant) and fn.args.defaults[0].value is True and
        not fn.args.vararg and not fn.args.kwarg and not fn.args.kwonlyargs, 'unsupported LO static build signature')
    return {'module':module,'owner':owner,'method':method,'source_sha256':hashlib.sha256(raw).hexdigest(),
        'definition_sha256':hashlib.sha256(ast.dump(fn,include_attributes=False).encode()).hexdigest()}


def compatibility(c, base, texts):
    """Complete sources/tool identities; only declared seed/exposure differ for static objects."""
    from . import model_tool_bridge as bridge, model_events as events
    base=Path(base); sources=[]
    for role, spec in [('madgraph',c['runtime']['madgraph_tree']),('model',c['model_tree']),
            *[(x['role'],x['tree']) for x in c['runtime']['dependencies']]]:
        root, manifest, files=bridge._tree(spec,base)
        sources.append({'role':role,'root':str(root),'manifest_sha256':bridge._hash(manifest),
            'files':[{'relative':str(p.relative_to(root)),'sha256':bridge._hash(p),'mode':stat.S_IMODE(p.stat().st_mode)} for p in files]})
    python=bridge._pin(c['runtime']['python'],base); support=bridge._pin(c['runtime']['python_manifest'],base)
    doc=bridge._read(support)
    support_files=[{'path':str(bridge._pin(row,base)),'sha256':row['sha256'],
        'mode':stat.S_IMODE(bridge._pin(row,base).stat().st_mode)} for row in doc['files']]
    from . import model_event_process, model_event_source, model_event_phases, reinterpret_db
    producer=[{'name':Path(x.__file__).name,'sha256':bridge._hash(x.__file__)}
        for x in (events,model_event_process,model_event_source,model_event_phases,reinterpret_db,sys.modules[__name__])]
    build_tools=[]
    for name in ('make','ar','ranlib'):
        path=shutil.which(name)
        if path is None: continue
        path=Path(path).resolve();require(path.is_file() and os.access(path,os.X_OK),'regular executable build tool required')
        build_tools.append({'name':name,'path':str(path),'sha256':bridge._hash(path),'mode':stat.S_IMODE(path.stat().st_mode)})
    environment_keys=('PATH','FC','F77','CC','CXX','AR','RANLIB','FFLAGS','CFLAGS','CXXFLAGS','LDFLAGS',
        'MAKEFLAGS','MFLAGS','LIBRARY_PATH','LD_LIBRARY_PATH','DYLD_LIBRARY_PATH','CPATH',
        'C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','SDKROOT','MACOSX_DEPLOYMENT_TARGET')
    # Existing execute_native sets these five values for every admitted child.
    native_environment={name:os.environ.get(name) for name in environment_keys}
    native_environment.update({name:'1' for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS',
        'MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')})
    uname=os.uname()
    export={'sources':sources,'python':{'path':str(python),'sha256':bridge._hash(python),
        'mode':stat.S_IMODE(python.stat().st_mode),'support_sha256':bridge._hash(support),'support':support_files},
        'options':{k:None if v is None else str(bridge._regular(v,base,directory=k.endswith('_path'))) for k,v in c['runtime']['options'].items()},
        'commands':events.process_commands(texts['process'],c),'process_card_sha256':hashlib.sha256(texts['process'].encode()).hexdigest(),
        'order':c['generation']['order'],'full_unrestricted_ufo':True,'complex_mass_scheme':False if 'parameter_observation' in c else 'released-default',
        'producer':producer,'build_tools':build_tools,'native_environment_sha256':digest(native_environment),'abi':{'sysname':uname.sysname,'release':uname.release,'machine':uname.machine}}
    generation=deepcopy(c['generation'])
    for key in ('events','seed'): generation.pop(key)
    for key in ('nevents','iseed'): generation['run_settings'].pop(key,None)
    run=events.assignments(texts['run']); run={k:v for k,v in run.items() if k not in ('iseed','nevents')}
    static={'export':digest(export),'generation':generation,'run_rows':run,
        'cards':{k:None if c['cards'][k] is None else c['cards'][k]['sha256'] for k in c['cards'] if k not in ('run','process')},
        'shower':c['shower'],'decay':c['decay'],'reweight':c['reweight'],'weights':c['weights'],
        'parameter_observation':c.get('parameter_observation'),'pre_shower_lhe_transform':c.get('pre_shower_lhe_transform')}
    return {'export':export,'export_sha256':digest(export),'static_sha256':digest(static),
        'static_toolchain_bound':len(build_tools)==3,'toolchain_inputs':[x['path'] for x in build_tools]}


def _structure(root, maximum):
    root=Path(root); require(root.is_absolute() and '..' not in root.parts, 'canonical native export root required')
    ancestors=[(str(p),identity(p.lstat())[:3]) for p in (*reversed(root.parents),root)]
    require(all(stat.S_ISDIR(x[1][2]) for x in ancestors), 'reuse directory aliases refused')
    rows=[]; pending=[root]
    while pending:
        directory=pending.pop()
        entries=[]
        with os.scandir(directory) as stream:
            for entry in stream:
                require(len(rows)+len(entries)<maximum,'complete reuse population exceeds ceiling')
                entries.append(Path(entry.path))
        for path in sorted(entries):
            st=path.lstat(); require(len(rows)<maximum, 'complete reuse population exceeds ceiling')
            relative=path.relative_to(root).as_posix()
            require(stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode), 'special reuse member refused')
            row={'relative':relative,'identity':identity(st),'type':'directory' if stat.S_ISDIR(st.st_mode) else 'link' if stat.S_ISLNK(st.st_mode) else 'file'}
            if row['type']=='link': row['literal']=os.readlink(path)
            rows.append(row)
            if row['type']=='directory': pending.append(path)
    return ancestors, sorted(rows,key=lambda x:x['relative'])


def _relative(name):
    p=PurePosixPath(name)
    require(type(name) is str and name and not p.is_absolute() and '..' not in p.parts and str(p)==name, 'canonical reuse member required')
    return p


def _source_directory(path, options):
    before=_structure(Path(path),options['max_files']);rows=[];total=0
    for row in before[1]:
        require(row['type']!='link','source directory alias requires fresh export')
        item={'relative':row['relative'],'type':row['type'],'mode':stat.S_IMODE(row['identity'][2])}
        if row['type']=='file':
            raw=regular_bytes(Path(path)/row['relative'],options['max_member_bytes']);total+=len(raw)
            require(total<=options['max_bytes'],'linked source directory exceeds declared bytes')
            item.update(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        rows.append(item)
    require(_structure(Path(path),options['max_files'])==before,'linked source directory changed during capture')
    return {'rows':rows,'total_bytes':total}


def capture_export(process, destination, options, roots):
    """Only called after authenticated fresh export, before any production launch."""
    options=validate(options); process=Path(process); destination=Path(destination)
    require(not destination.exists(), 'fresh export capsule required')
    before=_structure(process,options['max_files']); rows=[]; total=0; referenced_files=0; referenced_bytes=0
    # An initial export has no events. Never package an arbitrary completed or failed run tree.
    event_files=[x for x in before[1] if x['relative'].startswith('Events/') and x['type']!='directory']
    require(all(x['relative']=='Events/.keep' and x['type']=='file' and x['identity'][3]==0 for x in event_files),
        'prelaunch export contains event state')
    marker=None if not event_files else released_events_marker(roots['madgraph'])
    for row in before[1]:
        p=process/row['relative']; item={'relative':row['relative'],'type':row['type'],'mode':stat.S_IMODE(row['identity'][2]),'mtime_ns':row['identity'][4]}
        if row['type']=='file':
            raw=regular_bytes(p,options['max_member_bytes'])
            stored=raw if raw else encoded(_EMPTY);total+=len(stored)
            require(len(stored)<=options['max_member_bytes'] and total+referenced_bytes<=options['max_bytes'],
                'complete export/reference byte ceiling exceeded')
            item.update(_store_blob(destination/'tree'/row['relative'],raw))
            if row['relative']=='Events/.keep':item['marker_source']=marker
        elif row['type']=='link':
            # Record literal structure. Internal future includes can be dangling until treatcards.
            target=Path(os.path.abspath(p.parent/row['literal'])); matches=[(role,Path(root)) for role,root in roots.items() if target.is_relative_to(Path(root))]
            require(matches, 'export link outside authenticated source roots')
            role,root=max(matches,key=lambda x:len(x[1].parts)); item.update(role=role,target=target.relative_to(root).as_posix(),literal=row['literal'])
            if role!='process':
                if target.is_dir():
                    remaining=dict(options,max_files=options['max_files']-len(before[1])-referenced_files,
                        max_bytes=options['max_bytes']-total-referenced_bytes)
                    require(remaining['max_files']>=0 and remaining['max_bytes']>=0,'complete linked-source work ceiling exceeded')
                    item['target_directory']=_source_directory(target,remaining)
                    referenced_files+=len(item['target_directory']['rows']);referenced_bytes+=item['target_directory']['total_bytes']
                else:
                    raw=regular_bytes(target,options['max_member_bytes']); item['target_sha256']=hashlib.sha256(raw).hexdigest()
                    item['target_size']=len(raw);referenced_files+=1;referenced_bytes+=len(raw)
                require(len(before[1])+referenced_files<=options['max_files'] and total+referenced_bytes<=options['max_bytes'],
                    'complete linked-source work ceiling exceeded')
        rows.append(item)
    require(_structure(process,options['max_files'])==before, 'export membership/bytes identity changed during capture')
    destination.mkdir(parents=True,exist_ok=True)
    record={'schema_version':1,'kind':'prelaunch-export-tree/v1','root':str(destination),'options':options,
        'roots':{k:str(v) for k,v in roots.items()},'rows':rows,'total_bytes':total,
        'referenced_files':referenced_files,'referenced_bytes':referenced_bytes}
    write_document(destination/'export.json',record)
    verify_tree(record)
    return record


def _closed_storage(root, structure, expected_files):
    expected=set(expected_files)
    for name in list(expected_files):
        expected.update(str(x) for x in PurePosixPath(name).parents if str(x)!='.')
    require({x['relative'] for x in structure[1]}==expected,'closed reuse storage directory/member population changed')
    require(all((x['type']=='file')==(x['relative'] in expected_files) for x in structure[1]),'reuse storage alias or kind changed')


def verify_tree(record):
    root=Path(record['root']); expected={'export.json'}|{str(Path(x['blob']['path']).relative_to(root)) for x in record['rows'] if x['type']=='file'}
    before=_structure(root,record['options']['max_files']*2+1)
    _closed_storage(root,before,expected)
    require(read_document(root/'export.json')==record, 'export metadata changed')
    require(all(x['relative']=='Events/.keep' and x['type']=='file' or x['type']=='directory' for x in record['rows'] if x['relative'].startswith('Events/')), 'prelaunch export contains event state')
    for row in record['rows']:
        _relative(row['relative'])
        if row['type']=='file':
            pin=row['blob']; require(Path(pin['path'])==root/'tree'/row['relative'], 'foreign export blob')
            raw=_blob_bytes(row,record['options']['max_member_bytes'])
            if row['relative'].startswith('Events/'):
                require(row['relative']=='Events/.keep' and not raw and
                    row.get('marker_source')==released_events_marker(record['roots']['madgraph']), 'unqualified export Events marker')
    require(_structure(root,record['options']['max_files']*2+1)==before, 'export capsule late bytes/identity/membership changed')
    return record


def capture_static(process, destination, export, static_sha256, api):
    """Retain only static objects/libraries, never grids, binaries, cards or RNG state."""
    destination=Path(destination)
    if destination.exists(): return read_document(destination/'static.json')
    process=Path(process); options=export['options']; rows=[]; total=0
    before=_structure(process,options['max_files'])
    for item in before[1]:
        relative=PurePosixPath(item['relative'])
        if item['type']!='file' or relative.parts[0] not in ('Source','lib') or relative.suffix not in ('.o','.a'): continue
        raw=regular_bytes(process/relative,options['max_member_bytes']); stored=raw if raw else encoded(_EMPTY);total+=len(stored)
        require(len(stored)<=options['max_member_bytes'], 'static member storage ceiling exceeded')
        require(total+export['total_bytes']+export['referenced_bytes']<=options['max_bytes'], 'complete export/reference/static byte ceiling exceeded')
        require(len(rows)+1+len(export['rows'])+export['referenced_files']<=options['max_files'], 'complete export/reference/static file ceiling exceeded')
        rows.append({'relative':str(relative),'mode':stat.S_IMODE(item['identity'][2]),'mtime_ns':item['identity'][4],
            **_store_blob(destination/'tree'/relative,raw)})
    require(_structure(process,options['max_files'])==before, 'native static population changed during capture')
    destination.mkdir(parents=True,exist_ok=True)
    record={'schema_version':1,'kind':'LO-static-source-objects/v1','root':str(destination),'rows':rows,
        'static_sha256':static_sha256,'api':api,'total_bytes':total,'options':options}
    write_document(destination/'static.json',record); verify_static(record)
    return record


def verify_static(record):
    root=Path(record['root']); expected={'static.json'}|{'tree/'+x['relative'] for x in record['rows']}
    before=_structure(root,record['options']['max_files']*2+1)
    _closed_storage(root,before,expected)
    require(read_document(root/'static.json')==record,'static metadata changed')
    for row in record['rows']:
        name=_relative(row['relative']);require(name.parts[0] in ('Source','lib') and name.suffix in ('.o','.a'),'runtime/adaptive member in static capsule')
        pin=row['blob']; require(Path(pin['path'])==root/'tree'/name, 'foreign static blob')
        _blob_bytes(row,record['options']['max_member_bytes'])
    require(_structure(root,record['options']['max_files']*2+1)==before,'static capsule late bytes/identity/membership changed')
    return record


def materialize(record, process, roots):
    verify_tree(record); process=Path(process); require(not process.exists(),'fresh reused process required'); process.mkdir()
    for row in record['rows']:
        destination=process/_relative(row['relative'])
        if row['type']=='directory':
            destination.mkdir(parents=True,exist_ok=True);destination.chmod(row['mode'])
        elif row['type']=='file':
            raw=_blob_bytes(row,record['options']['max_member_bytes']);write_bytes(destination,raw)
            destination.chmod(row['mode']);os.utime(destination,ns=(row['mtime_ns'],row['mtime_ns']))
        elif row['type']=='link':
            require(row['role'] in roots,'unbound reused link root');target=Path(roots[row['role']])/_relative(row['target'])
            if row['role']!='process':
                if 'target_directory' in row:require(_source_directory(target,record['options'])==row['target_directory'],'relocated source directory differs')
                else:require(hashlib.sha256(regular_bytes(target,record['options']['max_member_bytes'])).hexdigest()==row['target_sha256'],'relocated source link differs')
            destination.parent.mkdir(parents=True,exist_ok=True);destination.symlink_to(os.path.relpath(target,destination.parent))
        else: raise ValueError('unknown reuse member kind')
    # Released do_save emits mg5_path in this exact configuration. Only this native root changes.
    for name in ('Cards/me5_configuration.txt','Cards/amcatnlo_configuration.txt'):
        path=process/name
        if not path.exists(): continue
        raw=regular_bytes(path,record['options']['max_member_bytes']).decode(); lines=[]
        for line in raw.splitlines(keepends=True):
            stripped=line.split('#',1)[0].strip()
            if stripped and '=' in stripped and stripped.split('=',1)[0].strip()=='mg5_path':
                require(stripped.split('=',1)[1].strip()==record['roots']['madgraph'],'unqualified exported mg5_path')
                line='mg5_path = '+str(roots['madgraph'])+'\n'
            lines.append(line)
        expected=''.join(lines).encode();path.write_bytes(expected)
        require(regular_bytes(path,len(expected))==expected,'relocated MG configuration changed')
    expected={row['relative']:row for row in record['rows']}
    before=_structure(process,record['options']['max_files'])
    require({row['relative'] for row in before[1]}==set(expected),'materialized export namespace differs')
    for row in before[1]:
        intended=expected[row['relative']];path=process/row['relative']
        require(row['type']==intended['type'] and stat.S_IMODE(row['identity'][2])==intended['mode'],'materialized export kind/mode differs')
        if row['type']=='file':
            raw=_blob_bytes(intended,record['options']['max_member_bytes'])
            if row['relative'] in ('Cards/me5_configuration.txt','Cards/amcatnlo_configuration.txt'):
                lines=[]
                for line in raw.decode().splitlines(keepends=True):
                    stripped=line.split('#',1)[0].strip()
                    if stripped and '=' in stripped and stripped.split('=',1)[0].strip()=='mg5_path':line='mg5_path = '+str(roots['madgraph'])+'\n'
                    lines.append(line)
                raw=''.join(lines).encode()
            require(regular_bytes(path,record['options']['max_member_bytes'])==raw,'materialized export bytes differ')
        elif row['type']=='link':
            target=Path(roots[intended['role']])/_relative(intended['target'])
            require(os.readlink(path)==os.path.relpath(target,path.parent),'materialized export link differs')
    require(_structure(process,record['options']['max_files'])==before,'materialized export changed during final read')
    verify_tree(record)
    return {'export_members':len(record['rows']),'adaptive_state_reused':False}


def apply_static(record, process):
    verify_static(record);process=Path(process)
    for row in record['rows']:
        destination=process/_relative(row['relative'])
        require(destination.parent.is_dir() and not any(p.is_symlink() for p in (destination,*destination.parents)),'static overlay outside existing regular export directories')
        raw=_blob_bytes(row,record['options']['max_member_bytes'])
        destination.write_bytes(raw);destination.chmod(row['mode'])
        require(regular_bytes(destination,len(raw))==raw,'static overlay changed')
        os.utime(destination,ns=(row['mtime_ns'],row['mtime_ns']))
    before=_structure(process,record['options']['max_files'])
    for row in record['rows']:
        raw=_blob_bytes(row,record['options']['max_member_bytes'])
        path=process/row['relative']
        require(regular_bytes(path,record['options']['max_member_bytes'])==raw and stat.S_IMODE(path.lstat().st_mode)==row['mode'],'ending static overlay changed')
    require(_structure(process,record['options']['max_files'])==before,'static overlay namespace/identity changed during final read')
    verify_static(record)
    return len(record['rows'])


def publish(output, export, compatibility, origin, static=None):
    output=Path(output); verify_tree(export)
    if static is not None: verify_static(static)
    record={'schema_version':1,'kind':KIND,'compatibility':compatibility,'export':export,'static':static,
        'origin':origin,'physics_validated':False,'integration_state_reusable':False}
    pin=write_document(output/'generator-reuse.json',record); verify(record)
    return {'record':pin,'state':origin['state'],'static_objects_available':static is not None,'physics_validated':False}


def verify(record):
    require(type(record) is dict and record.get('kind')==KIND and record.get('schema_version')==1 and
        record.get('physics_validated') is False and record.get('integration_state_reusable') is False,'unqualified reusable generator capsule')
    require(digest(record['compatibility']['export'])==record['compatibility']['export_sha256'],'export identity digest differs')
    verify_tree(record['export'])
    if record['static'] is not None:
        require(record['static']['static_sha256']==record['compatibility']['static_sha256'],'static compatibility differs')
        verify_static(record['static'])
    return record


def probe(c, base, texts):
    """Initial unavailable/incompatible candidates are explicit misses, not new approvals."""
    options=validate(c['generator_reuse']); current=compatibility(c,base,texts)
    candidate=options['candidate']
    if candidate is None: return {'state':'fresh','compatibility':current,'inputs':[]}
    from ravel.workflow import science, execution
    from . import model_tool_bridge as bridge
    try:
        rd=bridge._regular(candidate['rundir'],base,directory=True)
        with science._validation_scope(rd) as session:
            outputs=science.review_waypoint_paths(rd,_session=session)
            plan=science.verify_plan(rd,approved=True,_session=session)
            require(plan['mode']=='model-events','reuse needs ordinary model-events origin')
            stage,_,_=science._selected(rd,plan,_session=session); output=rd/stage['outputs'][0]
            path=output/'generator-reuse.json'; raw=regular_bytes(path,16*1024**2)
            require(hashlib.sha256(raw).hexdigest()==candidate['capsule_sha256'],'requested capsule pin differs')
            record=read_document(path);verify(record)
            require(len(record['export']['rows'])+record['export']['referenced_files']+(0 if record['static'] is None else len(record['static']['rows']))<=options['max_files'] and
                record['export']['total_bytes']+record['export']['referenced_bytes']+(0 if record['static'] is None else record['static']['total_bytes'])<=options['max_bytes'] and
                all(x['blob']['size']<=options['max_member_bytes'] for x in record['export']['rows'] if x['type']=='file') and
                (record['static'] is None or all(x['blob']['size']<=options['max_member_bytes'] for x in record['static']['rows'])),
                'candidate exceeds current admitted reuse resource bounds')
            result=session.read_document(output/'result.json')
            require(result.get('status')=='passed' and result.get('physics_validated') is False and
                result.get('generator_reuse',{}).get('record')=={'path':str(path),'sha256':candidate['capsule_sha256'],'size':len(raw)},'capsule is not in original successful result')
            require(record['compatibility']['export']==current['export'],'export physics/runtime/source identity differs')
            inputs=sorted(set(outputs+list(session.files)))
            static=record['static'] if record['static'] is not None and record['compatibility']['static_sha256']==current['static_sha256'] else None
            return {'state':'export-and-static-reuse' if static is not None else 'export-reuse','compatibility':current,
                'record':record,'static':static,'capsule_pin':{'path':str(path),'sha256':candidate['capsule_sha256'],'size':len(raw)},'inputs':inputs}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return {'state':'miss','compatibility':current,'inputs':[], 'reason':str(exc)}


def ending(result, output):
    info=result.get('generator_reuse')
    if info is None: return None
    pin=info['record'];require(Path(pin['path'])==Path(output)/'generator-reuse.json','foreign delivered reuse capsule')
    raw=regular_bytes(pin['path'],16*1024**2)
    require(len(raw)==pin['size'] and hashlib.sha256(raw).hexdigest()==pin['sha256'],'delivered reusable capsule changed')
    record=read_document(pin['path']);verify(record)
    require(record['origin']['process_identity']==result['generation_process_identity'],'reused process origin differs')
    helper=record['origin'].get('capture_helper')
    if helper is not None:
        require(Path(helper['path'])==Path(output)/'native-generator-reuse.py','foreign delivered capture helper')
        raw=regular_bytes(helper['path'],128*1024**2)
        require(len(raw)==helper['size'] and hashlib.sha256(raw).hexdigest()==helper['sha256'],'delivered capture helper changed')
    return record
