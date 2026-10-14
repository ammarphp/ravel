"""Isolated native ServiceX and Awkward/RDataFrame boundary.

Only the ordinary admitted worker launches this module. SDK/frontend source is
pinned prospectively; no claim of equivalence to the old IRIS container image.
Public observations whitelist fields and never dump native status/cache objects.
"""
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import shutil
import sys


def safe_write(path, value, *, exclusive=False):
    raw=(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    if exclusive:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    else:
        from ravel.workflow.state_io import atomic_json
        atomic_json(path,value)


def query_identity(c, ds, analysis):
    from ravel.physics.dataset_query_quantities_core import digest
    service=c['service']
    return digest({'dataset':ds,'analysis':analysis,'bundle':c['bundle'],
        'service':None if service is None else {k:service[k] for k in ('endpoint','codegen','result_format')}})


class RemoteObservation:
    """A durable source-level API observation, not a remote job/cost oracle."""
    def __init__(self,out,identity):
        self.out=Path(out); self.identity=identity
        self.value={'schema_version':1,'query_identity':identity,'phase':'prepared','request_id':None,
            'submit_method_invocations':0,'remote_job_count':None,'remote_cost':None,
            'cache_policy':'fresh_private_attempt','cache_hit':False,'cancel_acknowledged':False,
            'status_observations':[],'terminal_observed':False,'automatic_resubmit_allowed':False}
        safe_write(self.out/'remote-observation.json',self.value,exclusive=True)

    def save(self):safe_write(self.out/'remote-observation.json',self.value)

    async def submit(self,method,*args,**kwargs):
        if self.value['phase']!='prepared':raise ValueError('existing ambiguous/started intent prohibits duplicate dispatch')
        # TransformRequest has no credentials. Retain the exact consumed native
        # source request as a hash, without dumping private native status/cache.
        if args and hasattr(args[0],'model_dump'):
            from ravel.physics.dataset_query_quantities_core import digest
            source=args[0].model_dump(mode='json',by_alias=True)
            self.value['native_transform_request_sha256']=digest(source)
            self.value['native_selection_sha256']=hashlib.sha256(source['selection'].encode()).hexdigest()
        self.value.update(phase='submission_started',submit_method_invocations=1)
        self.save() # before the native method, including any internal HTTP retry
        try:
            request_id=await method(*args,**kwargs)
            from ravel.physics.dataset_query_quantities_core import text
            text(request_id,'received remote request id')
            self.value.update(phase='request_id_received',request_id=request_id)
            self.save();return request_id
        except BaseException:
            self.value['phase']='submission_ambiguous';self.save();raise

    def status(self,value):
        from ravel.physics.dataset_query_quantities_core import remote_status
        public=remote_status(value)
        if self.value['request_id'] is not None and public['request_id']!=self.value['request_id']:
            raise ValueError('observed remote request identity changed')
        self.value['status_observations'].append(public)
        self.value['terminal_observed']=public['terminal_observed']
        self.save();return public

    async def cancel_and_observe(self,adapter):
        identity=self.value['request_id']
        if identity is None:return
        try:
            await adapter.cancel_transform(identity)
            self.value['cancel_acknowledged']=True;self.save()
        except BaseException:
            self.value['cancel_acknowledged']=False;self.save()
        try:self.status(await adapter.get_transform_status(request_id=identity))
        except BaseException:self.value['phase']='remote_terminal_unobserved';self.save()


async def service_files(client, generator, c, ds, observation):
    """Use the actual released FileList/Query interface, never NFiles=1."""
    from servicex.dataset_identifier import FileListDataset
    from servicex.models import ResultFormat
    identifiers=[m['uri'] for d in ds['datasets'] for m in d['members']]
    q=client.generic_query(FileListDataset(identifiers),generator,codegen=c['service']['codegen'],
        title='RAVEL IRIS '+observation.identity[:16],result_format=ResultFormat(c['service']['result_format']),
        ignore_cache=True,fail_if_incomplete=True)
    original=q.servicex.submit_transform
    async def submitted(*a,**kw):return await observation.submit(original,*a,**kw)
    q.servicex.submit_transform=submitted
    try:
        files=await q.as_files_async(display_progress=False)
        if q.current_status is None or observation.value['submit_method_invocations']!=1:
            raise ValueError('fresh attempt did not observe its native submission/status')
        status=observation.status(q.current_status)
        if status['status']!='Complete' or status['files_failed'] not in (None,0) or status['files_remaining'] not in (None,0):
            raise ValueError('native returned incomplete/failed source population')
        return [Path(p) for p in files]
    except BaseException:
        if c['service']['cancel_if_failed']:await observation.cancel_and_observe(q.servicex)
        raise
    finally:q.servicex.submit_transform=original


def make_client(c,private):
    """Explicit private nonsecret config, no home config or ambient token file."""
    from servicex.servicex_client import ServiceXClient
    # A supplied plugin directory cannot quietly replace the reviewed SDK.
    from ravel.physics import dataset_query_quantities_core as core
    from ravel.physics.dataset_query_quantities import asset_check
    api=core.strict((core.DATA/'servicex-api.json').read_bytes())
    for module_name,relative in (('servicex.servicex_client','servicex_client.py'),('servicex.servicex_adapter','servicex_adapter.py'),('servicex.query_core','query_core.py')):
        module=sys.modules[module_name];path=Path(module.__file__).absolute()
        expected=api['required_package_files'][relative]
        asset_check({str(path):{'path':str(path),'sha256':expected,'size':path.stat().st_size}})
    config=Path(private)/'servicex.json'
    # JSON is valid YAML. This file never contains the resolved credential.
    safe_write(config,{'api_endpoints':[{'name':'ravel','endpoint':c['service']['endpoint']}],
        'default-endpoint':'ravel','cache-path':str(Path(private)/'cache')},exclusive=True)
    os.environ.pop('BEARER_TOKEN_FILE',None)
    client=ServiceXClient(backend='ravel',config_path=str(config),cache_dir=str(Path(private)/'cache'))
    reference=c['service']['credential_reference']
    if reference is not None:
        credential=os.environ.get(reference['name'])
        if not credential:raise ValueError('approved native credential reference is unavailable')
        client.servicex.refresh_token=credential
    return client


def load_plugin(directory,entry):
    path=Path(directory)/entry
    spec=importlib.util.spec_from_file_location('ravel_iris_supplied_analysis',path)
    if spec is None or spec.loader is None:raise ValueError('native source entry unavailable')
    module=importlib.util.module_from_spec(spec)
    sys.path.insert(0,str(Path(directory)))
    spec.loader.exec_module(module)
    return module


def native_tables(files, backend):
    """Native formats stay native; the supplied source controls branch meaning."""
    if backend=='awkward-hist':
        import awkward as ak
        import uproot
        answer=[];counts=[]
        for row in files:
            if row['format']=='parquet':
                table=ak.from_parquet(row['path']);answer.append(table);count=len(table);api='awkward.from_parquet/len'
            else:
                with uproot.open(row['path']) as f:
                    trees=[k for k in f.keys(cycle=False) if hasattr(f[k],'arrays')]
                    if len(trees)!=1:raise ValueError('one explicit native return tree required')
                    tree=f[trees[0]];table=tree.arrays(library='ak');count=int(tree.num_entries)
                    if len(table)!=count:raise ValueError('ROOT tree/array row counts differ')
                    answer.append(table);api='uproot.TTree.num_entries/array_len'
            counts.append({'id':row['id'],'rows':count,'source_members':row['source_members'],'api':api})
        return answer,counts
    import ROOT
    answer=[];counts=[]
    for row in files:
        if row['format']!='root':raise ValueError('RDataFrame requires ROOT returns')
        f=ROOT.TFile.Open(row['path'])
        if not f or f.IsZombie():raise ValueError('native ROOT return unreadable')
        names=[key.GetName() for key in f.GetListOfKeys() if key.GetClassName()=='TTree']
        f.Close()
        if len(names)!=1:raise ValueError('one explicit ROOT tree required')
        table=ROOT.RDataFrame(names[0],row['path']);count=int(table.Count().GetValue());answer.append(table)
        counts.append({'id':row['id'],'rows':count,'source_members':row['source_members'],'api':'ROOT.RDataFrame.Count.GetValue'})
    return answer,counts


def runtime_versions(runtime):
    from importlib.metadata import version
    answer={}
    for name,expected in runtime['versions'].items():
        if name=='ROOT':
            import ROOT
            actual=ROOT.gROOT.GetVersion()
        else:actual=version(name)
        if actual!=expected:raise ValueError('native package version differs from supplied runtime')
        answer[name]=actual
    return answer


def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    if len(args)!=2:raise ValueError('one exact admitted native request and digest required')
    # This standalone copied driver authenticates its request/worker through the
    # parent envelope before importing any supplied or optional native source.
    fd=os.open(args[0],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        import stat
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size>16*1024**2:raise ValueError('bounded regular native request required')
        raw=b''
        while len(raw)<=16*1024**2:
            block=os.read(fd,1024**2)
            if not block:break
            raw+=block
        if os.fstat(fd)!=before or hashlib.sha256(raw).hexdigest()!=args[1]:raise ValueError('consumed native request differs')
    finally:os.close(fd)
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate request key')
            d[k]=v
        return d
    def reject(value):raise ValueError('nonfinite request')
    request=json.loads(raw,object_pairs_hook=unique,parse_constant=reject)
    sys.path.insert(0,request['source_root'])
    from ravel.physics import dataset_query_quantities_core as core
    core.keys(request,('config','dataset','analysis','returned','bundle_directory','private_directory','output','source_root','runtime_assets','closed_roots','driver_sha256'),'native request')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=request['driver_sha256']:
        raise ValueError('native selected driver changed')
    c=core.config(request['config']);ds=core.dataset(request['dataset']);a=core.contract(request['analysis'])
    out=Path(request['output']);private=Path(request['private_directory'])
    from ravel.physics.dataset_query_quantities import asset_check,closed_assets
    closed_assets(request['runtime_assets'],request['closed_roots'])
    for root in c['runtime']['site_roots']:sys.path.insert(0,root)
    private.mkdir(mode=0o700,exist_ok=False)
    # Native SDK/ROOT user configuration and download caches cannot fall back
    # to the operator's home. This affects only this isolated native process.
    for name in ('home','tmp'):(private/name).mkdir(mode=0o700)
    os.environ['HOME']=str(private/'home');os.environ['TMPDIR']=str(private/'tmp')
    os.environ.pop('BEARER_TOKEN_FILE',None)
    safe_write(out/'native-start.json',{'phase':'source_checked','query_identity':query_identity(c,ds,a),'scientific_acceptance':False},exclusive=True)
    # Upstream logs can contain signed URLs/authorization errors. Preserve safe
    # API states/counts; do not copy native cache or unfiltered stdout to review.
    logging.disable(logging.CRITICAL)
    errors=[];observation=None;delivery=None
    versions=None
    try:
        with open(os.devnull,'w') as quiet,redirect_stdout(quiet),redirect_stderr(quiet):
            versions=runtime_versions(c['runtime'])
            if c['operation']=='observe_existing_remote_request':
                prior=core.Capture().document(c['remote_request']['intent'],Path(args[0]).parent)
                if prior.get('query_identity')!=query_identity(c,ds,a) or prior.get('request_id')!=c['remote_request']['id']:
                    raise ValueError('existing request is not the exact retained intent')
                observation=RemoteObservation(out,prior['query_identity'])
                observation.value.update(phase='observation_only',request_id=c['remote_request']['id'],cache_policy='no_query_no_cache_reuse')
                observation.save();client=make_client(c,private)
                if c['remote_request']['cancel']:asyncio.run(observation.cancel_and_observe(client.servicex))
                else:observation.status(asyncio.run(client.get_transform_status_async(c['remote_request']['id'])))
            else:
                plugin=load_plugin(request['bundle_directory'],c['bundle']['entry'])
                if c['operation']=='query_and_analyze':
                    observation=RemoteObservation(out,query_identity(c,ds,a))
                    client=make_client(c,private)
                    paths=asyncio.run(service_files(client,plugin.query(ds,a),c,ds,observation))
                    mapped=plugin.correspondence(paths,ds,a)
                    mapped=core.returned(mapped,ds)
                    if mapped['origin']!='fresh_service_return':raise ValueError('fresh remote return mislabeled as cache')
                    # Path/order mappings come from the exact supplied source;
                    # asynchronous arrival order carries no source authority.
                    if set(str(p.absolute()) for p in paths)!=set(str(Path(r['pin']['path']).absolute()) for r in mapped['files']):
                        raise ValueError('correspondence omits/adds native returned files')
                else:mapped=core.returned(request['returned'],ds)
                # Check native file bytes with streaming descriptor admission;
                # data formats are read by native libraries, not decoded JSON.
                from ravel.physics.dataset_query_quantities import asset_check
                native_assets={};files=[]
                for row in mapped['files']:
                    path=Path(row['pin']['path']);path=(path if path.is_absolute() else Path(args[0]).parent/path).absolute()
                    native_assets[str(path)]={**row['pin'],'path':str(path)}
                    files.append({'id':row['id'],'path':str(path),'format':row['format'],'source_members':row['source_members']})
                asset_check(native_assets)
                if c['operation']=='query_and_analyze':
                    destination=out/'returned';destination.mkdir(exist_ok=False)
                    copied=[]
                    for i,(row,f) in enumerate(zip(mapped['files'],files)):
                        target=destination/(str(i)+'.'+row['format'])
                        shutil.copyfile(f['path'],target)
                        observed={**row['pin'],'path':str(target)}
                        asset_check({str(target):observed})
                        copied.append({**row,'pin':observed})
                        f['path']=str(target)
                    asset_check(native_assets)
                    mapped={**mapped,'files':copied}
                tables,native_counts=native_tables(files,c['runtime']['backend'])
                rows=plugin.analyze(tables,files,ds,a)
                core.native_population(native_counts,mapped,rows)
                delivery=core.analyze(a,ds,mapped,rows,max_rows=c['max_event_rows'],max_products=c['max_group_products'])
                delivery['native_row_census']=native_counts
                asset_check(native_assets)
                # Public result retains exact file hashes/id relations, not
                # SDK private URLs/keys/cache directory identities.
                delivery['returned_members']=[{'id':r['id'],'sha256':r['pin']['sha256'],'size':r['pin']['size'],'format':r['format'],'source_members':r['source_members']} for r in mapped['files']]
                safe_write(out/'native-event-export.json',rows,exclusive=True)
                safe_write(out/'returned-manifest.json',mapped,exclusive=True)
    except BaseException as error:
        # Never serialize exception text from credential/object-store code.
        errors.append(type(error).__name__)
    try:closed_assets(request['runtime_assets'],request['closed_roots'])
    except BaseException as error:errors.append('ending_source_'+type(error).__name__)
    safe_write(out/'native-result.json',{'status':'failed' if errors else 'passed','delivery':delivery,
        'remote':None if observation is None else observation.value,'errors':errors,
        'runtime_versions':versions,'physics_validated':False,'native_runtime_qualified':False},exclusive=True)
    return 3 if errors else 0


if __name__=='__main__':raise SystemExit(main())
