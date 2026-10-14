"""Software controls only: no SDK/service/ROOT/Awkward or scientific calls."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType
import shutil

import pytest
from ravel.physics import dataset_query_quantities as adapter, dataset_query_quantities_core as c, dataset_query_quantities_worker as w


def pin(path):
    raw=path.read_bytes();return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,allow_nan=False));return pin(path)


def population_fixture(tmp_path, *, variant='baseline'):
    authority=write(tmp_path/'authority.json',{'full_DID_member_census':'synthetic software only'})
    ds={'schema_version':1,'membership_authority':authority,'datasets':[{'did':'fictional:amber','members':[{'id':'m0','uri':'root://example.invalid/data/a.root','events':3},{'id':'m1','uri':'root://example.invalid/data/b.root','events':1}]}],
        'source_filter':'all exported rows; selected predicate from supplied source','ordering':'declared_member_then_source_entry','prefix':None}
    q={'schema_version':1,'axes':[{'name':'x','unit':'GeV'}],'bins':[{'id':'lo','low':[0],'high':[2]},{'id':'hi','low':[2],'high':[4]}],
        'weight_names':['nominal','var'],'input_weight_unit':'1','representation':'integrated','normalization':{'kind':'absolute','scale':1,'unit':'1'}}
    obs=[{'id':'mass','quantity':q,'metric_scope':'raw_unweighted_fills_per_selected_event'}]
    if variant=='baseline':obs.append({'id':'pt','quantity':deepcopy(q),'metric_scope':'raw_unweighted_fills_per_selected_event'})
    analysis={'schema_version':1,'task_id':'fictional-'+variant,'source_question':authority,'observables':obs,'weight_names':['nominal','var'],
        'weight_semantics':'signed common MC event weights; software control','scale_factor_semantics':'unknown, not inferred from b-tag discriminator',
        'event_domain':{'datasets':['fictional:amber'],'prefix':None},'dataset_components':False,'presentation':{'plot_kind':'histogram','formats':['pdf','png']},
        'source_filter':ds['source_filter'],'sampling_law':'poissonized_independent_groups_event_common_weights'}
    native=tmp_path/'synthetic-native.root';native.write_bytes(b'NOT ACTUAL ROOT: inert file-only control')
    ret={'schema_version':1,'origin':'supplied_native_return','source_dataset_sha256':c.digest(ds),'files':[{'id':'r0','pin':pin(native),'format':'root','source_members':['m0','m1']}],
        'exposure':{'m0':{'source_events':3,'returned_events':3},'m1':{'source_events':1,'returned_events':1}},'source_filter':ds['source_filter']}
    rows=[]
    for i,(member,entry,weight,fills,selected) in enumerate([('m1',0,3,[3],True),('m0',1,-1,[1,1],True),('m0',0,2,[1],True),('m0',2,0,[],False)]):
        rows.append({'event_id':'e'+str(i),'group_id':'shared' if i in (1,2) else 'g'+str(i),'member_id':member,'source_entry':entry,'selected':selected,
            'weights':{'nominal':weight,'var':2*weight},'fills':{o['id']:[[x] for x in fills] for o in obs}})
    return ds,analysis,ret,rows


def calculate(tmp_path):
    ds,a,r,rows=population_fixture(tmp_path)
    return c.analyze(a,ds,r,rows,max_rows=100,max_products=1000)


def test_arbitrary_observable_population_is_supplied(tmp_path):
    ds,a,ret,events=population_fixture(tmp_path)
    assert len(c.contract(a)['observables'])==2
    a['observables'].pop()
    assert len(c.contract(a)['observables'])==1


def test_signed_group_cancellation_joint_covariance_and_unweighted_metrics(tmp_path):
    result=calculate(tmp_path)
    # Shared group: 2*one fill + (-1)*two fills cancels in every lo bin.
    assert result['observables']['mass']['values']['nominal']==[0,3]
    order=result['joint_raw_moments']['covariance_order']
    cov=result['joint_raw_moments']['covariance']
    assert cov[1][3]==9 and cov[0][2]==0
    assert result['observables']['mass']['state']['sumw'][-1]==8
    assert result['raw_unweighted_metrics']['mass']['entries']==4
    assert result['raw_unweighted_metrics']['mass']['raw_unweighted_axis_means']==[1.5]
    assert result['full_returned_events']==4 and result['selected_events']==3
    assert order[3]=={'weight':'nominal','bin_id':'3'}
    assert result['upstream_per_fill_diagonal']['mass']['values']['nominal']['bin_sumw2']==[6,9]
    assert result['group_product_accounting']['includes_represented_zero_entries'] is True


def test_async_order_never_controls_source_prefix(tmp_path):
    ds,a,ret,rows=population_fixture(tmp_path,variant='prefix')
    ds['prefix']={'events':7,'source':a['source_question']};a['event_domain']['prefix']=deepcopy(ds['prefix']);ret['source_dataset_sha256']=c.digest(ds)
    forward=c.analyze(a,ds,ret,rows,max_rows=100,max_products=1000)
    backward=c.analyze(a,ds,ret,list(reversed(rows)),max_rows=100,max_products=1000)
    assert forward==backward
    assert forward['source_prefix_events']==4 and forward['selected_events']==3
    assert forward['raw_unweighted_metrics']['mass']['metric_denominator_events']==4


@pytest.mark.parametrize('mutation', ['missing_member','missing_row','duplicate_entry','duplicate_event','missing_weight','nonfinite','object_weight','extra_observable','bad_flow'])
def test_complete_exposure_and_weight_contract_refusals(tmp_path,mutation):
    ds,a,ret,rows=population_fixture(tmp_path)
    if mutation=='missing_member':ret['files'][0]['source_members']=['m0']
    elif mutation=='missing_row':rows.pop()
    elif mutation=='duplicate_entry':rows[0]['member_id']='m0';rows[0]['source_entry']=rows[1]['source_entry']
    elif mutation=='duplicate_event':rows[0]['event_id']=rows[1]['event_id']
    elif mutation=='missing_weight':rows[0]['weights'].pop('var')
    elif mutation=='nonfinite':rows[0]['weights']['nominal']=float('inf')
    elif mutation=='object_weight':rows[0]['fills']['mass']=[{'value':[1],'weight':3}]
    elif mutation=='extra_observable':rows[0]['fills']['unknown']=[]
    elif mutation=='bad_flow':rows[0]['fills']['mass']=[[True]]
    with pytest.raises(ValueError):c.analyze(a,ds,ret,rows,max_rows=100,max_products=1000)


def test_dense_product_and_row_bounds_do_not_thin_population(tmp_path):
    ds,a,ret,rows=population_fixture(tmp_path)
    with pytest.raises(ValueError,match='event population'):c.analyze(a,ds,ret,rows,max_rows=3,max_products=1000)
    with pytest.raises(ValueError,match='grouped joint products'):c.analyze(a,ds,ret,rows,max_rows=100,max_products=1)


@pytest.mark.parametrize('uri',['https://host/file?signature=secret','https://user:secret@host/file','https://host/file#secret'])
def test_no_signed_url_or_embedded_credential_contract(uri):
    with pytest.raises(ValueError):c.public_uri(uri)


def test_returned_format_and_cache_claim_are_explicit(tmp_path):
    ds,a,ret,rows=population_fixture(tmp_path)
    ret['files'][0]['format']='json'
    with pytest.raises(ValueError):c.returned(ret,ds)
    ret['files'][0]['format']='root';ret['origin']='authenticated_native_cache'
    with pytest.raises(ValueError):c.returned(ret,ds)


def test_descriptor_consumed_bytes_hash_symlink_and_ending_drift(tmp_path):
    source=tmp_path/'source.json';source.write_text('{"value":1}')
    cap=c.Capture();assert cap.document(pin(source),tmp_path)=={'value':1}
    source.write_text('{"value":2}')
    with pytest.raises(ValueError):cap.finish()
    alias=tmp_path/'alias';alias.symlink_to(source)
    with pytest.raises(ValueError):c.Capture().read(pin(alias),tmp_path)


@pytest.mark.parametrize('raw',[b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1e999}'])
def test_duplicate_and_nonfinite_document(raw):
    with pytest.raises(ValueError):
        value=c.strict(raw)
        if raw.endswith(b'1e999}'):c.number(value['x'])


def test_remote_intent_precedes_submit_and_ambiguous_attempt_never_resubmits(tmp_path):
    observation=w.RemoteObservation(tmp_path,'a'*64)
    called=[]
    async def loss(*args):
        stored=c.strict((tmp_path/'remote-observation.json').read_bytes())
        assert stored['phase']=='submission_started' and stored['submit_method_invocations']==1
        called.append(1);raise RuntimeError('do not disclose signed/private error text')
    with pytest.raises(RuntimeError):asyncio.run(observation.submit(loss))
    assert observation.value['phase']=='submission_ambiguous' and observation.value['remote_job_count'] is None
    with pytest.raises(ValueError):asyncio.run(observation.submit(loss))
    with pytest.raises(FileExistsError):w.RemoteObservation(tmp_path,'a'*64)
    assert called==[1]


def test_cancel_ack_is_not_terminal_and_status_is_secret_safe(tmp_path):
    observation=w.RemoteObservation(tmp_path,'a'*64);observation.value['request_id']='id'
    status=SimpleNamespace(request_id='id',status='Running',files=1,files_completed=0,files_failed=0,files_remaining=1,minio_secret_key='PRIVATE',signed_url_list=['SECRET'])
    class Adapter:
        async def cancel_transform(self,id):assert id=='id'
        async def get_transform_status(self,request_id):return status
    asyncio.run(observation.cancel_and_observe(Adapter()))
    assert observation.value['cancel_acknowledged'] is True and observation.value['terminal_observed'] is False
    raw=(tmp_path/'remote-observation.json').read_text();assert 'PRIVATE' not in raw and 'SECRET' not in raw


def test_actual_service_bridge_full_file_list_and_no_nfiles(monkeypatch,tmp_path):
    # Native modules are explicit inert test doubles; no optional import/call.
    ds,a,ret,rows=population_fixture(tmp_path)
    m=ModuleType('servicex.dataset_identifier');m.FileListDataset=lambda files:SimpleNamespace(files=files)
    f=ModuleType('servicex.models');f.ResultFormat=lambda value:value
    monkeypatch.setitem(sys.modules,'servicex.dataset_identifier',m);monkeypatch.setitem(sys.modules,'servicex.models',f)
    observation=w.RemoteObservation(tmp_path,'a'*64);seen=[]
    class Adapter:
        async def submit_transform(self,request):return 'request-id'
    native=Adapter()
    class Query:
        servicex=native
        current_status=SimpleNamespace(request_id='request-id',status='Complete',files=2,files_completed=2,files_failed=0,files_remaining=0)
        async def as_files_async(self,display_progress):
            assert display_progress is False
            await self.servicex.submit_transform('request');return ['b.root','a.root']
    class Client:
        def generic_query(self,identifier,generator,**kwargs):seen.append((identifier,kwargs));return Query()
    c0={'service':{'codegen':'atlasr25','result_format':'root','cancel_if_failed':False}}
    assert asyncio.run(w.service_files(Client(),'query',c0,ds,observation))==[Path('b.root'),Path('a.root')]
    assert seen[0][0].files==[m['uri'] for d in ds['datasets'] for m in d['members']]
    assert seen[0][1]['ignore_cache'] is True and seen[0][1]['fail_if_incomplete'] is True
    assert observation.value['submit_method_invocations']==1 and observation.value['terminal_observed'] is True


def test_actual_report_route_has_requested_plots_without_acceptance_credit(tmp_path):
    from ravel.plotting.science_figures import render
    delivery=calculate(tmp_path)
    result={'status':'passed','task_id':'fictional-baseline','operation':'analyze_returned_native_files','delivery':delivery,'remote':None,'limitations':['software-only'], 'physics_validated':False,'software_fixture_scope':'Explicit synthetic inert native rows'}
    report=render({'mode':'dataset-query-quantities','task':{}},result,tmp_path,tmp_path/'report')
    assert len(report['figures'])==2
    assert all((tmp_path/'report'/f).is_file() for r in report['figures'] for f in r['files'])
    table=c.strict((tmp_path/'report/dataset-query-quantities-table.json').read_bytes())
    assert table['delivery']==delivery and table['physics_validated'] is False


def configuration(tmp_path):
    ds,a,ret,rows=population_fixture(tmp_path)
    source=Path(__file__).parents[1]/'fixtures/iris_frontend/servicex'
    root=tmp_path/'runtime';package=root/'servicex';shutil.copytree(source,package)
    manifest={'schema_version':1,'files':{str(p.relative_to(root)):{k:v for k,v in pin(p).items() if k!='path'} for p in root.rglob('*') if p.is_file()}}
    runtime_manifest=write(tmp_path/'runtime-manifest.json',manifest)
    python=tmp_path/'interpreter';python.write_text('inert approved interpreter fixture, never executed');python.chmod(0o700)
    plugin=tmp_path/'source-analysis.py'
    plugin.write_text('import json\ndef analyze(tables,files,ds,a):\n    return json.loads('+repr(json.dumps(rows))+')\n')
    config={'schema_version':1,'operation':'analyze_returned_native_files',
        'dataset':write(tmp_path/'dataset.json',ds),'analysis':write(tmp_path/'analysis.json',a),
        'bundle':{'entry':'analysis.py','files':{'analysis.py':pin(plugin)}},
        'runtime':{'python':pin(python),'site_roots':[str(root)],'trees':[{'root':str(root),'manifest':runtime_manifest}],
            'versions':{'servicex':'3.3.1','awkward':'inert','hist':'inert','uproot':'inert','numpy':'inert','func_adl_servicex_xaodr25':'inert'},'backend':'awkward-hist'},
        'service':None,'returned':write(tmp_path/'returns.json',ret),'remote_request':None,
        'max_seconds':10,'max_ram_mib':128,'max_output_bytes':64*1024**2,'max_event_rows':100,'max_group_products':1000,'trusted_native_source':True}
    task={'config':write(tmp_path/'config.json',config)}
    return task,config,rows


def test_complete_runtime_and_source_intake_and_context_no_optional_import(tmp_path):
    task,cfg,rows=configuration(tmp_path)
    files=adapter.inputs(task,tmp_path)
    assert Path(cfg['runtime']['python']['path']) in files
    assert adapter.API in files
    context=adapter.context(task,tmp_path)
    assert context['execution_authorized'] is False and context['returned_file_count']==1
    assert context['supplied_population']['observables']==['mass','pt']
    assert adapter.execution_seconds(task,tmp_path)==10
    # Nothing silently substitutes NFiles1 or an incomplete directory snapshot.
    (Path(cfg['runtime']['trees'][0]['root'])/'unexpected.py').write_text('# extra')
    with pytest.raises(ValueError,match='membership'):adapter.inputs(task,tmp_path)


def test_foreign_cwd_public_cli_context_has_same_source_meaning(tmp_path,monkeypatch):
    task,cfg,rows=configuration(tmp_path)
    document=tmp_path/'task.json';document.write_text(json.dumps(task))
    other=tmp_path/'foreign';other.mkdir();monkeypatch.chdir(other)
    output=tmp_path/'context.json'
    assert adapter.main(['context','--task',str(document),'--output',str(output)])==0
    assert c.strict(output.read_bytes())['analysis']['task_id']=='fictional-baseline'
    with pytest.raises(ValueError):adapter.main(['context','--task',str(document),'--output',str(output)])


def test_actual_native_worker_and_parent_delivery_transport_without_native_libraries(tmp_path,monkeypatch):
    task,cfg,rows=configuration(tmp_path)
    rd=tmp_path/'ordinary-control';rd.mkdir()
    out=rd/'outputs/attempt-1/dataset-query-quantities'
    # Explicit control substitutes approval and native library boundary only.
    monkeypatch.setattr(adapter,'_approved',lambda task,out:(rd,{'max_seconds':10}))
    monkeypatch.setattr(w,'native_tables',lambda files,backend:(['inert native facade'],[{'id':r['id'],'rows':4,'source_members':r['source_members'],'api':'inert source-only native row API'} for r in files]))
    monkeypatch.setattr(w,'runtime_versions',lambda runtime:runtime['versions'])
    from ravel.physics import reinterpret_db
    commands=[]
    def inert(command,output,config):
        commands.append(command)
        assert command[1:3]==['-I','-B']
        # The worker runs in this process here, so the stand-in applies the command's -B itself:
        # a bytecode cache written beside the copied source would change the closed source tree.
        monkeypatch.setattr(sys,'dont_write_bytecode',True)
        assert w.main(command[-2:])==0
        return {'exit_code':0,'control_facade':True,'process_launched':False}
    monkeypatch.setattr(reinterpret_db,'execute_native',inert)
    result=adapter.run(task,tmp_path,out)
    assert result['status']=='passed' and result['physics_validated'] is False
    assert result['delivery']['observables']['mass']['values']['nominal']==[0,3]
    assert result['remote'] is None and len(commands)==1
    assert c.strict((out/'native/returned-manifest.json').read_bytes())['origin']=='supplied_native_return'
    assert (rd/'work/iris-private-attempt-1').is_dir()
    with pytest.raises(ValueError):adapter.run(task,tmp_path,out)


def test_real_graph_host_context_complete_dependencies_and_stale_refusal(tmp_path):
    from ravel.workflow import agent_graph as graph, agent_host as host, execution
    task,cfg,rows=configuration(tmp_path)
    task_path=tmp_path/'task.json';task_path.write_text(json.dumps(task))
    dependencies=adapter.context_inputs(task,tmp_path)
    pins=[{'id':'task','path':str(task_path),'sha256':execution.file_hash(task_path)}]
    pins += [{'id':'d'+str(i),'path':str(p),'sha256':execution.file_hash(p)} for i,p in enumerate(dependencies)]
    node={'id':'iris-context','kind':'tool','role':'executor','depends_on':[],'inputs':pins,'packet':None,
        'action':'dataset-query-quantities-context','parameters':{'request_input':'task'},'max_attempts':1}
    specification={'schema_version':1,'graph_id':'iris-source-context','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':60,'max_reworks':0},'nodes':[node]}
    root=tmp_path/'graph';graph.create(root,specification)
    result=graph.execute(root,host.AgentHost(),workers=1)
    assert result['complete'] and result['usage']['calls']==1
    assert result['execution_authorized'] is False
    cfg_path=Path(task['config']['path']);cfg_path.write_text('{}')
    with pytest.raises(graph.GraphError):graph.execute(root,host.AgentHost(),workers=1)


def test_released_full_filelist_and_generic_query_bodies_are_wrapped(tmp_path):
    import ast
    import typing
    fixture=Path(__file__).parents[1]/'fixtures/iris_frontend/servicex'
    source=ast.parse((fixture/'dataset_identifier.py').read_text())
    klass=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='FileListDataset')
    functions=[n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name in ('__init__','populate_transform_request')]
    namespace={'List':typing.List,'str':str,'TransformRequest':object}
    for f in functions:
        for arg in (*f.args.posonlyargs,*f.args.args,*f.args.kwonlyargs):arg.annotation=None
        f.returns=None
        exec(compile(ast.fix_missing_locations(ast.Module(body=[f],type_ignores=[])),'released-filelist','exec'),namespace)
    class Dataset:pass
    obj=Dataset();namespace['__init__'](obj,['source-b','source-a'])
    request=SimpleNamespace();namespace['populate_transform_request'](obj,request)
    assert request.file_list==['source-b','source-a'] and request.did is None
    source=ast.parse((fixture/'servicex_client.py').read_text())
    method=next(n for cl in source.body if isinstance(cl,ast.ClassDef) for n in cl.body if isinstance(n,ast.FunctionDef) and n.name=='generic_query')
    class Generator:
        default_codegen='atlasr25'
    supplied=Generator();observed={}
    class Query:
        def __init__(self,**kw):observed.update(kw)
    for arg in (*method.args.posonlyargs,*method.args.args,*method.args.kwonlyargs):arg.annotation=None
    method.returns=None
    # Actual AST body is unchanged; annotations/default ResultFormat dependency
    # is an inert source-extraction environment, not an SDK or service import.
    namespace={'QueryStringGenerator':Generator,'GenericQueryStringGenerator':Generator,'Query':Query,'ResultFormat':SimpleNamespace(parquet='parquet')}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'released-generic-query','exec'),namespace)
    client=SimpleNamespace(servicex='native-adapter',config='explicit-private-config',query_cache='private-cache')
    namespace['generic_query'](client,obj,supplied,ignore_cache=True,fail_if_incomplete=True)
    assert observed['dataset_identifier'] is obj and observed['ignore_cache'] is True and observed['fail_if_incomplete'] is True


def test_declared_population_cannot_drop_one_dataset(tmp_path):
    task,cfg,rows=configuration(tmp_path)
    analysis=c.strict(Path(cfg['analysis']['path']).read_bytes())
    analysis['event_domain']['datasets'].append('fictional:violet')
    cfg['analysis']=write(tmp_path/'analysis-extra.json',analysis);task={'config':write(tmp_path/'config-extra.json',cfg)}
    with pytest.raises(ValueError,match='declared dataset'):adapter.context(task,tmp_path)


def test_zero_signed_weights_still_charge_actual_represented_products(tmp_path):
    ds,a,ret,rows=population_fixture(tmp_path)
    for row in rows:row['weights']={'nominal':0,'var':0}
    result=c.analyze(a,ds,ret,rows,max_rows=100,max_products=1000)
    assert result['actual_group_products']>0
    with pytest.raises(ValueError,match='grouped joint products'):c.analyze(a,ds,ret,rows,max_rows=100,max_products=1)


def test_nonfinite_derived_fill_moment_is_never_a_pass(tmp_path):
    ds,a,ret,rows=population_fixture(tmp_path)
    rows[0]['weights']={'nominal':1e308,'var':1e308}
    with pytest.raises(ValueError):c.analyze(a,ds,ret,rows,max_rows=100,max_products=1000)
