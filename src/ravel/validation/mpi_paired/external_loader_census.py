"""Observe native image traces when reusing an accepted external binary.

This is a bounded read-only census, not a build or process runner. Stage identities and required observations come from the supplied plan.
"""
from pathlib import Path
import hashlib
import os
import re
import stat

from ravel.workflow.state_io import atomic_json
from ravel.validation.mpi_paired.producer_witness_v2 import _read_pin, _identity

LOG_CEILING=16*1024**2


def require(ok,message):
    if not ok:raise ValueError(message)


def read_trace(path,check_budget):
    """Descriptor-bound 16 MiB read; a non-shower trace may truthfully be empty."""
    path=Path(path).absolute()
    require('..' not in path.parts and not any(p.is_symlink() for p in (path,*path.parents)),'Regular trace path required')
    before=os.lstat(path)
    require(stat.S_ISREG(before.st_mode) and 0<=before.st_size<=LOG_CEILING,'Trace exceeds declared byte ceiling')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK);parts=[];count=0
    try:
        require(_identity(os.fstat(fd))==_identity(before),'Trace changed before read')
        while True:
            check_budget();maximum=min(1024**2,LOG_CEILING+1-count)
            require(maximum>0,'Trace exceeded bounded read')
            block=os.read(fd,maximum)
            if not block:break
            count+=len(block);require(count<=LOG_CEILING,'Trace exceeded bounded read');parts.append(block)
        require(count==before.st_size and _identity(os.fstat(fd))==_identity(before) and _identity(os.lstat(path))==_identity(before),'Trace changed during read')
    finally:os.close(fd)
    raw=b''.join(parts)
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':count},raw


def census(out,stage_names,bound_files,*,accepted_binary,required_stages,check_budget):
    out=Path(out)
    require(len(stage_names)==len(set(stage_names)) and all(type(n) is str and n and '/' not in n and n not in ('.','..') for n in stage_names),'Unique simple stage IDs required')
    require(set(required_stages)<=set(stage_names),'Both actual paired shower IDs are required')
    # ``bound_files`` is the adapter's completed initial regular-file snapshot;
    # its keys are canonical paths. The adapter independently repeats that full
    # observation at end. Resolve the few observed images, not the whole supplied inventory.
    require(all(Path(path).is_absolute() and '..' not in Path(path).parts for path in bound_files),'Absolute initial custody paths required')
    known=set(bound_files)
    binary=Path(accepted_binary)
    require(str(binary) in bound_files,'Accepted external binary must be a bound input')
    pin,_,_=_read_pin(binary,check_budget)
    require(pin['sha256']==bound_files[str(binary)],'Accepted external binary differs from initial custody')
    require(pin['path'] in known,'Accepted binary resolved identity differs')
    report={'accepted_external_binary':pin,'observed_bound_images':[],
            'system_platform_bound_images':[],'unbound_images':[],
            'stage_trace_counts':{},'trace_pins':[],'required_stage_ids':list(required_stages),
            'status':'running','limits':'Only actual loader trace images are observed; OS shared-cache paths are platform-bound. No complete dynamic data-dependency closure or new binary qualification is inferred.'}
    observed=set();system=set();unknown=set()
    def save():
        report['observed_bound_images']=sorted(observed)
        report['system_platform_bound_images']=sorted(system)
        report['unbound_images']=sorted(unknown)
        atomic_json(out/'native-loader-census.json',report)
    save()
    try:
        for name in stage_names:
            check_budget();report['active_stage']=name;save()
            trace,raw=read_trace(out/'native-logs'/(name+'.log'),check_budget)
            report['trace_pins'].append(trace)
            images=re.findall(r'^dyld\[\d+\]: <[0-9A-Fa-f-]+> (/[^\r\n]+)$',raw.decode('utf-8',errors='replace'),re.MULTILINE)
            report['stage_trace_counts'][name]=len(images)
            for path in images:
                if path.startswith(('/usr/lib/','/System/Library/','/System/Volumes/Preboot/Cryptexes/')):
                    system.add(path)
                else:
                    resolved=str(Path(path).resolve(strict=True))
                    (observed if resolved in known else unknown).add(resolved)
            save()
            require(name not in required_stages or images,'Actual paired shower loader trace missing: '+name)
        require(not unknown,'Actual native loader used unbound image')
        check_budget();report.update(status='passed',active_stage=None);save()
    except Exception as error:
        report.update(status='failed',error={'type':type(error).__name__,'message':str(error)});save();raise
    return report
