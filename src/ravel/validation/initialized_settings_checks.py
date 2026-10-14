"""Read-only initialized-witness qualification checks; never invoke a producer.

The surrounding supervised stage must separately bind compilation/runtime/source,
clean command exits and end custody. Exact content comparison is not a physics
model or historical-settings claim.
"""
from __future__ import annotations
import gzip,hashlib,json,math
from pathlib import Path
IDS=[1000011,2000011,1000013,2000013,1000015,2000015,1000022,15]
MAX_SNAPSHOT=1024**2
MAX_DECODED_32_EVENT_FILE=128*1024**2

def require(ok,message):
    if not ok:raise ValueError(message)

def strict(raw):
    def pairs(items):
        d={}
        for k,v in items:
            require(k not in d,'duplicate JSON key');d[k]=v
        return d
    def bad(value):raise ValueError('nonfinite JSON constant: '+value)
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)

def finite(value):
    if isinstance(value,float):require(math.isfinite(value),'nonfinite scalar')
    elif isinstance(value,dict):
        for x in value.values():finite(x)
    elif isinstance(value,list):
        for x in value:finite(x)

def snapshot(path,schema,*,command,compiled_source_path,expected_settings,expected_masses):
    from jsonschema import Draft202012Validator
    path=Path(path);require(path.is_file() and not path.is_symlink(),'regular snapshot required')
    with path.open('rb') as f:raw=f.read(MAX_SNAPSHOT+1)
    require(0<len(raw)<=MAX_SNAPSHOT,'bounded complete snapshot required')
    value=strict(raw);Draft202012Validator(schema).validate(value);finite(value)
    require(value['request']=={'config_path':command[1],'count_override':command[3],'argv':command},'exact producer request differs')
    require(value['producer']['compiled_source_path']==compiled_source_path and value['producer']['compiled_header_version_integer']==8312,'observed compile identity differs')
    require([p['pdg_id'] for p in value['post_init_particles']]==IDS,'ordered full particle census differs')
    for p in value['post_init_particles']:
        if p['present']:
            require(p['channel_count']==len(p['channels']) and [r['index'] for r in p['channels']]==list(range(p['channel_count'])),'complete ordered decay-channel census required')
        if str(p['pdg_id']) in expected_masses:
            require(p['present'] and p['m0_GeV']==expected_masses[str(p['pdg_id'])],'source-bound mass expectation differs')
    for section,items in expected_settings.items():
        for key,target in items.items():
            actual=value['post_init_settings'][section][key]
            require(type(actual) is type(target) and actual==target,'post-init setting differs: '+key)
    require(value['internal_rng']['unchanged_by_snapshot'] is True,'getter RNG noninterference assertion absent')
    return {'snapshot_sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'post_init_settings':value['post_init_settings'],
            'post_init_particles':value['post_init_particles'],'info_beams':value['info_beams'],'lha_beams':value['lha_beams'],
            'pre_init_settings':value['pre_init_settings'],'internal_rng':value['internal_rng'],
            'snapshot_complete':True,'event_generation_complete':False,
            'limitation':'Producer PID/getters are observations; independent compilation and runtime custody are separate.'}

def content(path,encoding):
    require(encoding in ('plain','gzip'),'explicit supported encoding required')
    path=Path(path);require(path.is_file() and not path.is_symlink(),'regular event evidence required')
    before=path.stat();identity=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
    digest=hashlib.sha256();count=0
    with (gzip.open(path,'rb') if encoding=='gzip' else path.open('rb')) as stream:
        for raw in iter(lambda:stream.read(1024**2),b''):
            count+=len(raw);require(count<=MAX_DECODED_32_EVENT_FILE,'decoded32-event evidence exceeds admitted128MiB');digest.update(raw)
    after=path.stat();require(identity==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'content changed during read')
    return {'content_sha256':digest.hexdigest(),'content_bytes':count}

def equal_content(left,right,*,left_encoding='plain',right_encoding='plain'):
    a=content(left,left_encoding);b=content(right,right_encoding)
    require(a==b,'complete decoded content differs')
    return {'equal':True,**a}

def transport(report,*,events,command):
    require(report['status']=='content_verified' and report['joined_events']==events,'full original-LHA content join absent')
    require(report['producer']['returncode']==0 and report['producer']['command']==command,'clean exact producer exit absent')
    require(report['producer']['source_checks_before_and_after'] is True,'producer custody incomplete')
    # Actual output paths and all file bytes must also be bound by stage receipts.
    return {'events':events,'clean_exit':True,'full_content_join':True}

def pair(disabled,enabled,reference,*,encoding='plain'):
    """All inputs are retained files; enabled/disabled refer to settings observation."""
    require(set(disabled)==set(enabled)==set(reference)=={'hepmc','sidecar'},'exact paired evidence members required')
    return {'settings_observer_hepmc':equal_content(disabled['hepmc'],enabled['hepmc'],left_encoding=encoding,right_encoding=encoding),
            'settings_observer_lha':equal_content(disabled['sidecar'],enabled['sidecar']),
            'accepted_mpi32_hepmc':equal_content(disabled['hepmc'],reference['hepmc'],left_encoding=encoding),
            'accepted_mpi32_lha':equal_content(disabled['sidecar'],reference['sidecar']),
            'scope':'Same32 source events/card/seed/current runtime only; no detector rerun or MPI effect.'}
