"""Symbolic-provider detection and source-only model export/cache.

No kernel, tool, activation or numerical calculation is launched. A source
capsule establishes byte provenance, never licensed rights or model validity.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import zipfile

from ravel.physics import model_tool_bridge as custody

KINDS={'supplied-ufo','pregenerated-spectrum'}
ASSETS={'ufo-source','generated-spectrum-source','parameter-card','slha','model-reference'}
PROTECTED={'wolframkernel','mathkernel','wolfram','wolframscript','mathpass'}
MAX_BYTES=512*1024*1024
MAX_BUNDLE_BYTES=MAX_BYTES+32*1024*1024
BUNDLE_FORMAT='zip-stored-regular-source-v1'

def validate(task):
    custody._keys(task,('config',),'model-sources task')
    if not isinstance(task['config'],str) or not task['config'].strip():raise ValueError('explicit source configuration required')
    return dict(task)

def _text(value):
    if not isinstance(value,str) or not value.strip():raise ValueError('explicit source/license attribution required')

def _protected(path):
    return any(part.lower() in PROTECTED or part.lower()=='licensing' for part in Path(path).parts)

def _ordinary_tree(root):
    for p in root.rglob('*'):
        relative=p.relative_to(root)
        if any(part in custody.EXCLUDED for part in relative.parts) or p.suffix in ('.pyc','.pyo','.pkl'):
            continue
        if p.is_symlink() or (not p.is_file() and not p.is_dir()):raise ValueError('source aliases/special files refused')

def _optional_file(fact,base):
    custody._keys(fact,('path','sha256'),'optional provider file')
    if not isinstance(fact['path'],str) or not isinstance(fact['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',fact['sha256']):raise ValueError('explicit optional provider file identity required')
    path=Path(fact['path']);path=path if path.is_absolute() else Path(base)/path
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('provider path/ancestor alias refused')
    return custody._pin(fact,base) if path.exists() else None

def _load(task,base):
    validate(task);path=custody._regular(task['config'],base);c=custody._read(path)
    custody._keys(c,('schema_version','source','baseline_kind','assets','symbolic_provider','export_policy','reuse'),'model source configuration')
    if type(c['schema_version']) is not int or c['schema_version']!=1 or c['baseline_kind'] not in KINDS or c['export_policy']!='private_source_cache_only':raise ValueError('explicit source-only baseline/private export required')
    _text(c['source'])
    if not isinstance(c['assets'],list) or not 1<=len(c['assets'])<=16:raise ValueError('bounded explicit supplied source assets required')
    files={};inputs=[path];ids=set();kinds=set()
    for asset in c['assets']:
        custody._keys(asset,('id','kind','source','license','file','tree'),'model source asset')
        if not isinstance(asset['id'],str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}',asset['id']) or asset['id'] in ids or asset['kind'] not in ASSETS:raise ValueError('unique explicit asset id/kind required')
        ids.add(asset['id']);kinds.add(asset['kind']);_text(asset['source']);_text(asset['license'])
        if (asset['file'] is None)==(asset['tree'] is None):raise ValueError('exactly one file/tree source required')
        if asset['file'] is not None:
            p=custody._pin(asset['file'],path.parent);rows={p.name:p}
        else:
            root,manifest,members=custody._tree(asset['tree'],path.parent);inputs.append(manifest)
            _ordinary_tree(root)
            rows={p.relative_to(root).as_posix():p for p in members}
        for name,p in rows.items():
            if _protected(name) or p.is_symlink():raise ValueError('source export excludes engine/credential files and aliases')
            files[asset['id']+'/'+name]=p;inputs.append(p)
    required='ufo-source' if c['baseline_kind']=='supplied-ufo' else 'generated-spectrum-source'
    if required not in kinds:raise ValueError('baseline must actually contain its declared supplied source kind')
    if len(files)>20000 or sum(p.stat().st_size for p in files.values())>MAX_BYTES:raise ValueError('bounded source capsule exceeded')
    provider=c['symbolic_provider'];observed={'configured':False,'runtime_qualified':False,'license_rights_qualified':False}
    if provider is not None:
        custody._keys(provider,('kind','kernel','application_metadata','package_source','last_attempt','license_note'),'symbolic provider')
        if provider['kind'] not in ('wolfram-feynrules','wolfram-sarah'):raise ValueError('explicit symbolic provider kind required')
        _text(provider['license_note'])
        kernel=_optional_file(provider['kernel'],path.parent);metadata=_optional_file(provider['application_metadata'],path.parent)
        root,manifest,members=custody._tree(provider['package_source'],path.parent);inputs.extend([manifest,*members])
        _ordinary_tree(root)
        if any(_protected(p.relative_to(root)) or p.is_symlink() for p in members):raise ValueError('provider source contains engine/credential material or aliases')
        inputs.extend(p for p in (kernel,metadata) if p is not None)
        kernel_hash=custody._hash(kernel) if kernel is not None else None
        if kernel_hash is not None and any(custody._hash(p)==kernel_hash for p in files.values()):raise ValueError('engine binary cannot be re-labelled as an exported model asset')
        last=None
        if provider['last_attempt'] is not None:
            last=custody._pin(provider['last_attempt'],path.parent);inputs.append(last)
        observed={'configured':True,'kind':provider['kind'],'kernel_present':kernel is not None,
            'kernel_executable':kernel is not None and os.access(kernel,os.X_OK),'application_metadata_present':metadata is not None,
            'package_source_files':len(members),'last_attempt':provider['last_attempt'],
            'last_attempt_is_historical_only':last is not None,'runtime_qualified':False,'license_rights_qualified':False,
            'qualification_required':'Explicit separately approved native provider qualification; no automatic activation or fallback',
            'license_note':provider['license_note']}
    contract={k:v for k,v in c.items() if k!='reuse'}
    digest=hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return path,c,files,inputs,observed,digest

def _member_name(name):
    if not isinstance(name,str) or not name:raise ValueError('explicit source-bundle member name required')
    p=Path(name)
    if (p.is_absolute() or '\\' in name or '\x00' in name
            or p.as_posix()!=name or any(part in ('','.', '..') for part in name.split('/'))):
        raise ValueError('unsafe exact source-bundle member name')
    return name

def _verify_bundle(bundle,expected,modes):
    """Check complete bytes/modes without extracting paths or executing source."""
    if len(expected)>20000 or bundle.stat().st_size>MAX_BUNDLE_BYTES:
        raise ValueError('source bundle exceeds bounded archive/member count')
    if set(expected)!=set(modes) or any(type(mode) is not int or not 0<=mode<=0o777 for mode in modes.values()):raise ValueError('source bundle mode inventory differs')
    total=0
    with zipfile.ZipFile(bundle,'r') as archive:
        members=archive.infolist()
        names=[_member_name(m.filename) for m in members]
        if len(names)!=len(set(names)) or set(names)!=set(expected):
            raise ValueError('source bundle member addition/deletion/duplicate')
        for member in members:
            mode=member.external_attr>>16
            total+=member.file_size
            if (total>MAX_BYTES or member.compress_type!=zipfile.ZIP_STORED or member.flag_bits&1
                    or not stat.S_ISREG(mode) or stat.S_IMODE(mode)!=modes[member.filename]
                    or modes[member.filename]&~0o777 or member.is_dir()):
                raise ValueError('source bundle storage/type/mode/size refused')
            digest=hashlib.sha256();size=0
            with archive.open(member,'r') as stream:
                while block:=stream.read(1024*1024):
                    size+=len(block);digest.update(block)
            if size!=member.file_size or digest.hexdigest()!=expected[member.filename]:
                raise ValueError('source bundle member bytes changed')
    return {'files':len(members),'bytes':total,'empty_members':[m.filename for m in members if m.file_size==0]}

def _write_bundle(bundle,files,modes):
    with zipfile.ZipFile(bundle,'x',compression=zipfile.ZIP_STORED) as archive:
        for name,p in sorted(files.items()):
            _member_name(name)
            if modes[name]&~0o777:raise ValueError('source export refuses special permission bits')
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            info.create_system=3;info.external_attr=(stat.S_IFREG|modes[name])<<16
            info.compress_type=zipfile.ZIP_STORED;info.file_size=p.stat().st_size
            with p.open('rb') as source,archive.open(info,'w') as destination:
                shutil.copyfileobj(source,destination)

def _capsule_bundle(manifest,doc,base):
    custody._keys(doc,('schema_version','source_contract_sha256','source_configuration_sha256','files','modes','bundle','baseline_kind','provider_status','scope'),'source capsule')
    if type(doc['schema_version']) is not int or doc['schema_version']!=2:
        raise ValueError('complete typed source-bundle capsule version2 required; V1 raw exports stay historical')
    custody._keys(doc['bundle'],('format','path','sha256','bytes'),'source bundle binding')
    if doc['bundle']['format']!=BUNDLE_FORMAT or doc['bundle']['path']!='source-assets.zip':
        raise ValueError('explicit closed source-bundle format/path required')
    bundle=custody._pin({'path':str(manifest.parent/doc['bundle']['path']),'sha256':doc['bundle']['sha256']},base)
    if bundle.stat().st_size!=doc['bundle']['bytes']:raise ValueError('source-bundle bytes differ')
    return bundle

def _cache(c,base,digest,files):
    if c['reuse'] is None:return None,[]
    manifest=custody._pin(c['reuse'],base);doc=custody._read(manifest)
    expected={name:custody._hash(p) for name,p in files.items()}
    modes={name:stat.S_IMODE(p.stat().st_mode) for name,p in files.items()}
    bundle=_capsule_bundle(manifest,doc,base)
    if doc['source_contract_sha256']!=digest or doc['files']!=expected or doc['modes']!=modes or doc['baseline_kind']!=c['baseline_kind']:raise ValueError('cache provenance/model source identity differs')
    _verify_bundle(bundle,expected,modes)
    return bundle,[manifest,bundle]

def restore_source_bundle(capsule,base,output):
    """Restore a complete pinned source cache for a subsequent private consumer.

    Restored legitimate empty files are source inputs, never incidental outputs.
    No licence/physics/approval or tool execution is inherited from the cache.
    """
    manifest=custody._pin(capsule,base)
    manifest_sha=custody._hash(manifest)
    if manifest_sha!=capsule['sha256']:raise ValueError('source capsule changed before restore read')
    doc=custody._read(manifest)
    bundle=_capsule_bundle(manifest,doc,base)
    inventory=_verify_bundle(bundle,doc['files'],doc['modes'])
    before={str(manifest):manifest_sha,str(bundle):doc['bundle']['sha256']}
    if before!={str(p):custody._hash(p) for p in (manifest,bundle)}:raise ValueError('source capsule/bundle changed before restore')
    out=Path(output).absolute()
    if out!=out.resolve() or any(p.is_symlink() for p in (out,*out.parents)) or out.exists():
        raise ValueError('new canonical ordinary private restore directory required')
    out.mkdir(parents=True)
    with zipfile.ZipFile(bundle,'r') as archive:
        for member in archive.infolist():
            destination=out/_member_name(member.filename)
            destination.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(member,'r') as source,destination.open('xb') as target:
                shutil.copyfileobj(source,target)
            destination.chmod(doc['modes'][member.filename])
    actual={p.relative_to(out).as_posix():custody._hash(p) for p in out.rglob('*') if p.is_file()}
    modes={p.relative_to(out).as_posix():stat.S_IMODE(p.stat().st_mode) for p in out.rglob('*') if p.is_file()}
    if actual!=doc['files'] or modes!=doc['modes'] or any(p.is_symlink() or not(p.is_file() or p.is_dir()) for p in out.rglob('*')) or before!={str(p):custody._hash(p) for p in (manifest,bundle)}:
        raise ValueError('source bundle/restore custody changed')
    return {'root':str(out),'files':inventory['files'],'bytes':inventory['bytes'],'empty_members':inventory['empty_members'],'physics_validated':False,'native_calls':0,'approval_inherited':False}

def inputs(task,base):
    path,c,files,source_inputs,_,digest=_load(task,base)
    _,cache_inputs=_cache(c,path.parent,digest,files)
    return sorted(set(source_inputs+cache_inputs))

def inspect(task,base):
    path,c,files,_,provider,digest=_load(task,base)
    root,_=_cache(c,path.parent,digest,files)
    return {'baseline_kind':c['baseline_kind'],'baseline_available':True,'source_files':len(files),
        'source_bytes':sum(p.stat().st_size for p in files.values()),'source_contract_sha256':digest,
        'symbolic_provider':provider,'cache_reusable':root is not None,'native_calls':0,'physics_validated':False}

def materialize(task,base,output):
    """Export only declared source bytes; caller supplies private fresh output."""
    path,c,files,_,provider,digest=_load(task,base);cache,_=_cache(c,path.parent,digest,files)
    before={str(p):custody._hash(p) for p in inputs(task,base)}
    input_modes={str(p):stat.S_IMODE(p.stat().st_mode) for p in inputs(task,base)}
    out=Path(output).absolute()
    if any(p.is_symlink() for p in (out,*out.parents)) or (out.exists() and any(out.iterdir())):raise ValueError('fresh ordinary source-export output required')
    out.mkdir(parents=True,exist_ok=True)
    expected={name:custody._hash(p) for name,p in files.items()}
    modes={name:stat.S_IMODE(p.stat().st_mode) for name,p in files.items()}
    bundle=out/'source-assets.zip'
    if cache is None:_write_bundle(bundle,files,modes)
    else:shutil.copy2(cache,bundle)
    inventory=_verify_bundle(bundle,expected,modes)
    end_modes={name:stat.S_IMODE(p.stat().st_mode) for name,p in files.items()}
    if (bundle.is_symlink() or end_modes!=modes
            or input_modes!={str(p):stat.S_IMODE(p.stat().st_mode) for p in inputs(task,base)}
            or before!={str(p):custody._hash(p) for p in inputs(task,base)}):raise ValueError('source/cache custody changed during export')
    capsule={'schema_version':2,'source_contract_sha256':digest,'source_configuration_sha256':custody._hash(path),
        'files':expected,'modes':modes,'bundle':{'format':BUNDLE_FORMAT,'path':bundle.name,'sha256':custody._hash(bundle),'bytes':bundle.stat().st_size},'baseline_kind':c['baseline_kind'],'provider_status':provider,
        'scope':'Private source bytes/provenance only; no engine distribution, legal rights, generated spectrum or model validity inferred'}
    custody._write(out/'source-capsule.json',capsule)
    consumer_inputs={}
    for asset in c['assets']:
        rows={name.split('/',1)[1]:digest for name,digest in expected.items() if name.startswith(asset['id']+'/')}
        manifest=out/(asset['id']+'-source.json')
        custody._write(manifest,{'schema_version':1,'files':rows})
        consumer_inputs[asset['id']]={'kind':asset['kind'],'source':asset['source'],'license':asset['license'],
            'tree':None,'file':None,'source_kind':'tree' if asset['tree'] is not None else 'file',
            'bundle':{'capsule':{'path':str(out/'source-capsule.json'),'sha256':custody._hash(out/'source-capsule.json')},'member_prefix':asset['id']+'/',
                'manifest':{'path':str(manifest),'sha256':custody._hash(manifest)},'restore_required':True}}
    custody._write(out/'asset-inputs.json',{'schema_version':2,'assets':consumer_inputs,'physics_validated':False,'consumer_instruction':'restore_source_bundle into a fresh private source directory; bind the restored asset prefix plus exact per-asset manifest before a separate model/spectrum operation. No source import/build/approval is inherited.'})
    result={'status':'passed','source':c['source'],'baseline_kind':c['baseline_kind'],'symbolic_provider':provider,
        'source_files':len(expected),'source_bytes':inventory['bytes'],'empty_source_members':inventory['empty_members'],'source_storage':BUNDLE_FORMAT,'cache_reused':cache is not None,'source_contract_sha256':digest,
        'native_calls':0,'activation_calls':0,'physics_validated':False,
        'limitations':['Source identity/export is distinct from numerical model robustness and independent physics cross-checks.',
            'Supplied-UFO and pregenerated-spectrum sources do not require an installed symbolic provider.',
            'Source-only inspection accepts a null provider field; runtime operations require their configured provider. Historical records do not establish current license or compatibility.',
            'Private cache policy does not grant redistribution rights to engine, package, model or generated outputs.']}
    custody._write(out/'result.json',result);return result

def run(task,base,output):
    for rd in (Path(output).absolute(),*Path(output).absolute().parents):
        if (rd/'inputs/science-plan.json').is_file():
            from ravel.workflow import science
            selected=science.verify_worker(rd);spec=science.execution_spec(rd)
            if spec['mode']!='model-sources' or spec['task']!=task or Path(output).resolve()!=(rd/selected['output_directory']).resolve():raise ValueError('source export differs from approved ordinary study')
            return materialize(task,base,output)
    raise ValueError('model-source study requires approved supervised worker')
