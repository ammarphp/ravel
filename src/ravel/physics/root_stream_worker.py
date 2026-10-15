"""Source-bound isolated reader. Only the approved ordinary adapter launches it.

Private data chunks and credential resolution remain here. Supplied analysis and
blinding code is explicitly reviewed trusted code, not an OS sandbox.
"""
import hashlib
from contextlib import redirect_stdout, redirect_stderr
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from urllib.parse import urlsplit, unquote
import zlib


def read_pinned(path, expected, maximum):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('ordinary source path required')
    before=path.stat();identity=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or identity(os.fstat(fd))!=identity(before):raise ValueError('source descriptor differs')
        data=bytearray()
        while True:
            b=os.read(fd,min(1024**2,maximum+1-len(data)))
            if not b:break
            data.extend(b)
            if len(data)>maximum:raise ValueError('source allocation bound exceeded')
        if identity(os.fstat(fd))!=identity(before) or identity(path.stat())!=identity(before) or hashlib.sha256(data).hexdigest()!=expected:raise ValueError('source bytes/current identity differ')
        return bytes(data)
    finally:os.close(fd)


def check_pinned(path, expected, size):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('ordinary asset required')
    identity=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    before=path.stat();fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or identity(os.fstat(fd))!=identity(before):raise ValueError('asset descriptor differs')
        h=hashlib.sha256();count=0
        while True:
            b=os.read(fd,1024**2)
            if not b:break
            count+=len(b);h.update(b)
            if count>size:raise ValueError('asset exceeds original size')
        if identity(os.fstat(fd))!=identity(before) or identity(path.stat())!=identity(before) or count!=size or h.hexdigest()!=expected:raise ValueError('asset bytes/current identity differ')
    finally:os.close(fd)


def load_plugin(directory,entry,name):
    p=Path(directory)/entry
    spec=importlib.util.spec_from_file_location(name,p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def _stat_identity(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _directory_identity(info):
    # A directory's size and times change with every unrelated entry another process
    # creates or removes in it; a replaced directory changes its device or inode.
    return (info.st_dev,info.st_ino,info.st_mode)


def _local_snapshot(handle, member):
    """Stream arbitrarily large declared members; retain the opened namespace."""
    path,before,ancestors=handle._ravel_original_namespace
    if any(x.is_symlink() for x in (path,*path.parents)) or _stat_identity(path.stat())!=before:
        raise ValueError('original local source namespace differs')
    if _stat_identity(os.fstat(handle.fileno()))!=before or any(_directory_identity(p.stat())!=v for p,v in ancestors):
        raise ValueError('original local descriptor/ancestor differs')
    pos=handle.tell();handle.seek(0);h=hashlib.sha256();adler=1;count=0
    while True:
        b=handle.read(1024**2)
        if not b:break
        count+=len(b);h.update(b);adler=zlib.adler32(b,adler)
        if count>member['size_bytes']:raise ValueError('local source exceeds original size')
    handle.seek(pos)
    if count!=member['size_bytes'] or _stat_identity(os.fstat(handle.fileno()))!=before or _stat_identity(path.stat())!=before or any(p.is_symlink() or _directory_identity(p.stat())!=v for p,v in ancestors):
        raise ValueError('ending original local descriptor/ancestor/size differs')
    expected=member['checksum'];value=h.hexdigest() if expected['algorithm']=='sha256' else f'{adler&0xffffffff:08x}'
    if value!=expected['value']:raise ValueError('local source checksum differs')
    row={'guid':member['guid'],'size_bytes':count,'checksum':{'algorithm':expected['algorithm'],'value':value},'entries':member['entries']}
    return row,h.hexdigest()


def local_member_pin(member):
    # Scientific input members have their own declared size, independent of the
    # small source-document allocation bound and complete runtime-tree budget.
    if urlsplit(member['uri']).scheme!='file':raise ValueError('local member required')
    handle,fs=open_member(member,{})
    try:
        _,sha=_local_snapshot(handle,member)
        return {'path':str(handle._ravel_original_namespace[0]),'sha256':sha,'size':member['size_bytes']}
    finally:handle.close()


def identity(handle, member, fs=None):
    """Local descriptor bytes vs remote metadata, explicitly distinct scopes."""
    if fs is None:return _local_snapshot(handle,member)[0]
    path=urlsplit(member['uri']).path
    size=fs.info(path)['size'];algorithm,value=fs.checksum(path)
    # Released checksum() returns the server's algorithm, regardless of its
    # argument. Never relabel an Adler32 reply as SHA256.
    algorithm=algorithm.lower();value=value.lower()
    if algorithm=='adler32':value=value.zfill(8)
    expected=member['checksum']
    if algorithm!=expected['algorithm'] or value!=expected['value'] or size!=member['size_bytes']:raise ValueError('member checksum/size identity differs')
    return {'guid':member['guid'],'size_bytes':size,'checksum':{'algorithm':algorithm,'value':value},'entries':member['entries']}


def open_member(member,site):
    u=urlsplit(member['uri'])
    if u.scheme=='file':
        if u.netloc not in ('','localhost') or not u.path.startswith('/'):raise ValueError('literal absolute local file URI required')
        p=Path(unquote(u.path)).absolute()
        if any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('local member alias refused')
        before=_stat_identity(p.stat());ancestors=[(x,_directory_identity(x.stat())) for x in p.parents]
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(fd).st_mode) or _stat_identity(os.fstat(fd))!=before:
            os.close(fd);raise ValueError('regular original local descriptor required')
        handle=os.fdopen(fd,'rb');handle._ravel_original_namespace=(p,before,ancestors)
        return handle,None
    if u.scheme!='root' or u.hostname not in site['allowed_hosts']:raise ValueError('remote initial host outside allowed site')
    from fsspec_xrootd import XRootDFileSystem
    fs=XRootDFileSystem(hostid=u.netloc,timeout=site['read_timeout_seconds'],locate_all_sources=False,
                       valid_sources=site['allowed_hosts'])
    return fs.open(member['uri'],'rb'),fs


def admitted(table,entries,sample,blind,analysis):
    """Mask before analysis; no data values or exclusion statistics exported."""
    if sample['kind']!='data':return table,entries
    if blind is None:raise ValueError('data requires source-reviewed blind mask')
    import numpy as np
    mask=blind.allow(table,tuple(analysis['blinding']['allowed_regions']))
    if not isinstance(mask,np.ndarray) or mask.dtype!=np.dtype('bool') or mask.shape!=(len(entries),):raise ValueError('exact boolean allowed-region mask required')
    return table[mask],entries[mask]


def check_branches(table,contracts,expected):
    import awkward as ak
    import numpy as np
    if len(table)!=expected or set(table.fields)!={b['name'] for b in contracts}:raise ValueError('complete original branch/table population differs')
    for b in contracts:
        col=table[b['name']]
        if b['shape']=='scalar':array=ak.to_numpy(col,allow_missing=False)
        else:
            # Exactly one jagged object dimension; nested/optional records refuse.
            lengths=ak.num(col,axis=1)
            if len(lengths)!=expected:raise ValueError('jagged source exposure differs')
            array=ak.to_numpy(ak.flatten(col,axis=1),allow_missing=False)
        if array.ndim!=1 or array.dtype!=np.dtype(b['dtype']):raise ValueError('source branch dtype/shape differs')


def stream(ds,a,c,bundle,*,reader=None,progress=None):
    """Dependency-injection seam for pure fake readers; production uses Uproot."""
    from ravel.physics import root_stream_core as core
    import numpy as np
    acc=core.Stream(ds,a,c['limits']);observations=[]
    visits=[(sample,member,0,member['entries'],None) for sample in ds['samples'] for member in sample['members']]
    if c.get('schema_version')==2:
        from ravel.physics import root_stream_partitions as partitions,root_stream_partition_core as partition_core
        cap=core.Capture();master=partitions.bound_master(c,ds,a,Path(c['partitioning']['master']['path']).parent,cap)
        core.require(c['partitioning']['operation']=='partition','external reader performs only one original partition, never a merge')
        part=next(x for x in master['partitions'] if x['id']==c['partitioning']['partition_id']);cap.finish()
        acc=partition_core.PartitionStream(ds,a,c['limits'],master,part)
        lookup={(sample['id'],member['id']):(sample,member) for sample in ds['samples'] for member in sample['members']}
        visits=[(*lookup[(row['sample'],row['member'])],row['start'],row['stop'],row['group']) for row in part['intervals']]
    kernel=load_plugin(bundle,c['bundle']['entry'],'ravel_admitted_root_kernel')
    blind=None if c['bundle']['blind_entry'] is None else load_plugin(bundle,c['bundle']['blind_entry'],'ravel_source_blinding')
    source_names=[b['name'] for b in a['branch_contract']]
    weight_names=set(a['weight_contract']['scale_factors'])|{v['branch'] for v in a['weight_contract']['variations']}
    if a['weight_contract']['raw_mc_weight'] is not None:weight_names.add(a['weight_contract']['raw_mc_weight'])
    for sample,member,interval_start,interval_stop,group_id in visits:
            if c.get('schema_version')==2:acc.group_id=group_id
            handle,fs=open_member(member,c['site'])
            try:
                before=identity(handle,member,fs)
                if reader is None:
                    import uproot
                    opened=uproot.open(handle);tree=opened[member['tree']]
                else:opened,tree=reader(handle,member)
                if int(tree.num_entries)!=member['entries']:raise ValueError('actual full tree entry count differs')
                size=c['limits']['chunk_entries'];ranges=range(interval_start,interval_stop,size) if interval_stop>interval_start else [interval_start]
                for start in ranges:
                    stop=min(start+size,interval_stop)
                    table=tree.arrays(source_names,entry_start=start,entry_stop=stop,library='ak')
                    check_branches(table,a['branch_contract'],stop-start)
                    entries=np.arange(start,stop,dtype=np.int64)
                    # Capture immutable original weights before any supplied code.
                    original_rows=[]
                    for i in range(len(entries)):
                        row={}
                        for name in sorted(weight_names):
                            if sample['kind']=='data':continue
                            value=table[name][i]
                            if hasattr(value,'item'):value=value.item()
                            row[name]=core.scalar(value)
                        original_rows.append(row)
                    table,entries=admitted(table,entries,sample,blind,a)
                    rows=[original_rows[int(entry)-start] for entry in entries]
                    public={'id':sample['id'],'kind':sample['kind'],**core.sample_identity(sample),'process':sample['process']}
                    if 'derived_factor' in a['weight_contract']:
                        # Capture SFs before analyze can mutate the table; raw
                        # generator/scalar weights retain their original values.
                        factors = kernel.event_factors(table, entries.copy(), public)
                        if type(factors) is not list or len(factors) != len(rows):
                            raise ValueError('all admitted source event factors required')
                        for row, factor in zip(rows, factors):
                            factor = core.scalar(factor)
                            if factor < 0: raise ValueError('nonnegative nominal event SF required')
                            row['__ravel_derived_nominal_factor__'] = factor
                    records=kernel.analyze(table,entries.copy(),public)
                    acc.chunk(sample['id'],member['id'],start,stop,[int(x) for x in entries],records,rows)
                    if progress is not None:progress(acc.coverage[-1])
                after=identity(handle,member,fs)
                if before!=after:raise ValueError('ending original source identity differs')
                observations.append({'member':member['id'],'before':before,'after':after,
                    'evidence_scope':'local opened descriptor checksum' if fs is None else 'Rucio GUID/expected checksum and remote before/after metadata; not atomic byte snapshot'})
                opened.close()
            finally:handle.close()
    unique={}
    for row in observations:
        core.require(row['member'] not in unique or unique[row['member']]==row,'original member changed across complete group spans')
        unique[row['member']]=row
    observations=[unique[member['id']] for sample in ds['samples'] for member in sample['members'] if member['id'] in unique]
    return {'schema_version':1,'status':'passed','delivery':acc.finish(),'identities':observations,'physics_validated':False}


def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    if len(args)!=2:raise ValueError('exact native request path and digest required')
    raw=read_pinned(args[0],args[1],64*1024**2)
    # Bootstrap metadata is decoded once from the authenticated buffer.
    def unique(rows):
        d={}
        for k,v in rows:
            if k in d:raise ValueError('duplicate request key')
            d[k]=v
        return d
    req=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite request')))
    for name,row in req['runtime_assets'].items():
        if row['path']!=name:raise ValueError('runtime asset path differs')
        check_pinned(name,row['sha256'],row['size'])
    sys.path[:0]=[req['source_root'],*req['config']['runtime']['site_roots']]
    from ravel.physics import root_stream,root_stream_core as core
    core.keys(req,('config','dataset','analysis','bundle_directory','output','source_root','runtime_assets','closed_roots'),'native request')
    c=core.config(req['config']);core.require(len(raw)<=(64 if c['schema_version']==2 else 32)*1024**2,'original schema request allocation exceeded');ds=core.dataset(req['dataset']);a=core.analysis(req['analysis'],ds)
    if c['schema_version']==2:
        base=root_stream.source_base(c,Path(args[0]).parent)
        sys.path[:0]=[str(root_stream.custody._ordinary(p,base,directory=True)) for p in c['runtime']['site_roots']]
    if not sys.platform.startswith('linux'):raise ValueError('required Linux site analysis runtime is not supplied')
    for name,version in c['runtime']['versions'].items():
        if importlib.metadata.version(name)!=version:raise ValueError('required site runtime version differs')
    from ravel.physics import dataset_query_quantities
    roots=[Path(x) for x in req['closed_roots']];dataset_query_quantities.closed_assets(req['runtime_assets'],roots)
    ref=c['site']['credential_reference'];secret=None if ref is None else os.environ.get(ref['name'])
    for key in ('X509_USER_PROXY','BEARER_TOKEN_FILE','XRD_TOKEN','XRD_AUTHZ','XRD_PROXY'):os.environ.pop(key,None)
    if ref is not None:
        if not secret:raise ValueError('explicit required site credential unavailable')
        os.environ[ref['target']]=secret
    try:
        # No raw table/plugin output enters logs or agent context. The source
        # reviewed kernel is trusted analysis code, not a hostile-code sandbox.
        ledger=Path(req['output'])/'completed-intervals.jsonl';written=0
        with ledger.open('xb') as intervals, open(os.devnull,'w') as private_log:
            def progress(row):
                nonlocal written
                line=(json.dumps(row,sort_keys=True,allow_nan=False)+'\n').encode();written+=len(line)
                if written>c['limits']['max_output_bytes']:raise ValueError('interval ledger bound exceeded')
                intervals.write(line);intervals.flush();os.fsync(intervals.fileno())
            with redirect_stdout(private_log),redirect_stderr(private_log):
                result=stream(ds,a,c,req['bundle_directory'],progress=progress)
        root_stream.validate_delivery(result,ds,a,c['limits'],c)
        dataset_query_quantities.closed_assets(req['runtime_assets'],roots)
        if read_pinned(args[0],args[1],(64 if c['schema_version']==2 else 32)*1024**2)!=raw:raise ValueError('native request changed')
        if len(root_stream.encoded(result))>c['limits']['max_output_bytes']:raise ValueError('complete result exceeds output bound')
        root_stream.write_new(Path(req['output'])/'native-result.json',result)
    finally:
        for key in ('X509_USER_PROXY','BEARER_TOKEN_FILE','XRD_TOKEN','XRD_AUTHZ','XRD_PROXY'):os.environ.pop(key,None)
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,KeyError,TypeError,ImportError,RuntimeError):
        # Native exception text may contain data or tokens; never print it.
        print('ROOT streaming refused; private source/runtime/data boundary',file=sys.stderr);raise SystemExit(2)
