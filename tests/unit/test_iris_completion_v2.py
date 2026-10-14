"""Complete supplied operation controls, explicitly synthetic software inputs."""
from copy import deepcopy
import json
from pathlib import Path
from types import ModuleType,SimpleNamespace
import sys
import pytest
from ravel.physics import dataset_query_quantities_core as c,dataset_query_quantities as adapter,dataset_query_quantities_worker as w
from test_dataset_query_quantities import population_fixture,configuration,write


def prefix_case(tmp_path, *, historical=False):
    ds,a,ret,rows=population_fixture(tmp_path,variant='prefix')
    if historical:a['task_id']='fictional-alternate'
    ds['prefix']={'events':7,'source':a['source_question']};a['event_domain']['prefix']=deepcopy(ds['prefix']);ret['source_dataset_sha256']=c.digest(ds)
    return ds,a,ret,rows


@pytest.mark.parametrize('historical',[False,True])
def test_complete_shorter_original_cohort_zero_objects_and_denominator(tmp_path,historical):
    ds,a,ret,rows=prefix_case(tmp_path,historical=historical)
    # Give the empty/unselected original source record a nonzero signed weight;
    # it must contribute to D while contributing no object fills.
    rows[-1]['weights']={'nominal':5,'var':10}
    result=c.analyze(a,ds,ret,rows,max_rows=100,max_products=1000)
    metric=result['raw_unweighted_metrics']['mass']
    assert metric['selected_events']==3 and metric['metric_denominator_events']==4
    assert metric['avg_entries_per_event']==1 and result['source_prefix_events']==4
    assert result['observables']['mass']['state']['sumw'][3]==9
    assert result['observables']['mass']['state']['sumw'][7]==18
    assert metric['scope']=='raw_unweighted_fills_per_original_source_prefix_event'


@pytest.mark.parametrize('mutation',['unknown','filtered','gap','duplicate','missing'])
def test_source_stage_prefix_requires_full_original_entry_domain(tmp_path,mutation):
    ds,a,ret,rows=prefix_case(tmp_path)
    if mutation=='unknown':ds['datasets'][0]['members'][0]['events']=None;ret['exposure']['m0']['source_events']=None
    elif mutation=='filtered':ds['datasets'][0]['members'][0]['events']=100000;ret['exposure']['m0']['source_events']=100000
    elif mutation=='gap':rows[2]['source_entry']=3
    elif mutation=='duplicate':rows[2]['source_entry']=1
    elif mutation=='missing':rows.pop();ret['exposure']['m0']['returned_events']=2
    ret['source_dataset_sha256']=c.digest(ds)
    with pytest.raises(ValueError):c.analyze(a,ds,ret,rows,max_rows=100,max_products=1000)


def test_original_seven_source_order_before_selection(tmp_path):
    ds,a,ret,rows=prefix_case(tmp_path)
    ds['datasets'][0]['members']=[ds['datasets'][0]['members'][0]];ds['datasets'][0]['members'][0]['events']=8
    ret['files'][0]['source_members']=['m0'];ret['exposure']={'m0':{'source_events':8,'returned_events':8}};ret['source_dataset_sha256']=c.digest(ds)
    rows=[{'event_id':'e'+str(i),'group_id':'e'+str(i),'member_id':'m0','source_entry':i,'selected':i in (6,7),
        'weights':{'nominal':1,'var':-1},'fills':{'mass':[[1]] if i==6 else [[3]] if i==7 else []}} for i in range(8)]
    result=c.analyze(a,ds,ret,list(reversed(rows)),max_rows=8,max_products=1000000)
    assert result['source_prefix_events']==7 and result['selected_events']==1
    assert result['observables']['mass']['values']['nominal']==[1,0]
    assert result['raw_unweighted_metrics']['mass']['avg_entries_per_event']==1/7
    assert result['observables']['mass']['state']['sumw'][3]==7


@pytest.mark.parametrize('mutation',['missing','count','association','duplicate'])
def test_native_api_row_census_refuses_incomplete_or_substituted_export(tmp_path,mutation):
    ds,a,ret,rows=prefix_case(tmp_path)
    counts=[{'id':'r0','rows':4,'source_members':['m0','m1'],'api':'inert actual API facade'}]
    if mutation=='missing':counts=[]
    elif mutation=='count':counts[0]['rows']=3
    elif mutation=='association':counts[0]['source_members']=['m0']
    elif mutation=='duplicate':counts*=2
    with pytest.raises(ValueError):c.native_population(counts,ret,rows)


def test_actual_native_reader_interfaces_return_observed_counts(monkeypatch):
    # Explicit native facade checks REAL source call/serialization, no SDK or
    # native library import. These do not qualify real DAOD/query association.
    file={'id':'f','path':'inert.parquet','format':'parquet','source_members':['m0']}
    ak=ModuleType('awkward');ak.from_parquet=lambda p:[{}, {}, {}]
    up=ModuleType('uproot');monkeypatch.setitem(sys.modules,'awkward',ak);monkeypatch.setitem(sys.modules,'uproot',up)
    tables,counts=w.native_tables([file],'awkward-hist');assert len(tables[0])==3 and counts[0]['rows']==3
    class Tree:
        num_entries=3
        def arrays(self,library):assert library=='ak';return [{},{},{}]
    class RootFile:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def keys(self,cycle):assert cycle is False;return ['events']
        def __getitem__(self,k):return Tree()
    up.open=lambda p:RootFile();file['format']='root'
    _,counts=w.native_tables([file],'awkward-hist');assert counts[0]['rows']==3 and counts[0]['api'].startswith('uproot')
    root=ModuleType('ROOT')
    class TFile:
        def IsZombie(self):return False
        def GetListOfKeys(self):return [SimpleNamespace(GetName=lambda:'events',GetClassName=lambda:'TTree')]
        def Close(self):pass
    root.TFile=SimpleNamespace(Open=lambda p:TFile())
    root.RDataFrame=lambda n,p:SimpleNamespace(Count=lambda:SimpleNamespace(GetValue=lambda:3))
    monkeypatch.setitem(sys.modules,'ROOT',root)
    _,counts=w.native_tables([file],'root-rdataframe');assert counts[0]['rows']==3 and 'Count.GetValue' in counts[0]['api']


def component_case(tmp_path, *, normalized=False):
    ds,a,ret,rows=population_fixture(tmp_path,variant='stack')
    dids=['fictional:amber','fictional:violet'];members=ds['datasets'][0]['members']
    ds['datasets']=[{'did':dids[0],'members':[members[0]]},{'did':dids[1],'members':[members[1]]}]
    a['event_domain']['datasets']=dids;a['dataset_components']=True
    a['presentation']={'plot_kind':'dataset_stack','formats':['pdf','png']}
    ret['source_dataset_sha256']=c.digest(ds)
    # Deliberately cross-DID shared group: component errors are correlated.
    rows[0]['group_id']=rows[2]['group_id'];rows[0]['weights']={'nominal':-3,'var':-6}
    rows[-1]['selected']=True;rows[-1]['weights']={'nominal':5,'var':10}
    if normalized:
        a['observables'][0]['quantity']['normalization']={'kind':'normalized','scope':'all_events'}
    return ds,a,ret,rows


@pytest.mark.parametrize('normalized',[False,True])
def test_did_components_share_full_normalization_signed_groups_and_errors(tmp_path,normalized):
    ds,a,ret,rows=component_case(tmp_path,normalized=normalized)
    result=c.analyze(a,ds,ret,rows,max_rows=100,max_products=1000);components=result['dataset_components']
    did0,did1=components['did_order'];row=components['observables']['mass']
    divisor=3 if normalized else 1
    assert row['values'][did0]['nominal']==[0,0] and row['values'][did1]['nominal']==[0,-3/divisor]
    assert row['values'][did1]['var']==[0,-6/(6 if normalized else 1)]
    assert row['raw_joint_moments']['state']['second_moment'][0][3]==0 # cancelled whole shared group
    assert row['normalization']==a['observables'][0]['quantity']['normalization']
    assert row['aggregation_roundoff_residual']['nominal']==[0,0]
    assert result['actual_group_products']==sum(result['group_product_accounting'][k] for k in ('joint','separate_observables','DID_components'))
    if normalized:assert all(row['marginals'][d]['denominators']['nominal']['sumw']==3 for d in components['did_order'])


def test_actual_signed_component_case_stack_and_report_embedding(tmp_path):
    from ravel.plotting.science_figures import render
    ds,a,ret,rows=component_case(tmp_path)
    rows[1]['weights']={'nominal':1,'var':2}
    delivery=c.analyze(a,ds,ret,rows,max_rows=100,max_products=1000)
    result={'status':'passed','task_id':a['task_id'],'operation':'analyze_returned_native_files','delivery':delivery,'remote':None,
        'limitations':['Synthetic software only'],'physics_validated':False,'software_fixture_scope':'Synthetic inert records'}
    report=render({'mode':'dataset-query-quantities','task':{}},result,tmp_path,tmp_path/'report')
    assert len(report['figures'])==2 # one complete two-DID stack per named weight
    data=c.strict((tmp_path/'report/iris-plot-contract.json').read_bytes())
    for plot in data['plots']:
        assert plot['series'][0]['components'][1]['values'][1]<0
        assert len(plot['series'][0]['components'])==2
        assert plot['style'].startswith('mplhep ATLAS')
    text=(tmp_path/'report/dataset-query-quantities-report.md').read_text()
    assert 'iris-observable-1-weight-1.png' in text
    assert all(d in json.dumps(data) for d in delivery['dataset_components']['did_order'])
    assert all((tmp_path/'report'/f).stat().st_size>1000 for r in report['figures'] for f in r['files'])


@pytest.mark.parametrize('task_id',['fictional-amber','fictional-violet'])
def test_supplied_dataset_population_and_domain_is_available(tmp_path,task_id):
    ds,a,ret,rows=population_fixture(tmp_path)
    a['task_id']=task_id
    assert c.original_domain(a,c.dataset(ds))==a['event_domain']
    ds['datasets'][0]['did']='fictional:missing'
    with pytest.raises(ValueError,match='declared dataset'):c.original_domain(a,c.dataset(ds))


def test_legitimate_original_member_order_changes_seven_prefix(tmp_path):
    # This replaces the V1 positive that narrowed supplied population to one event;
    # that old test is immutable history, not counted as a V2 passing case.
    ds,a,ret,rows=prefix_case(tmp_path);members=ds['datasets'][0]['members'];members[0]['events']=7
    ret['exposure']['m0']={'source_events':7,'returned_events':7}
    rows=[{'event_id':'e'+str(i),'group_id':'e'+str(i),'member_id':'m0','source_entry':i,'selected':i==6,
        'weights':{'nominal':1,'var':1},'fills':{'mass':[[1]] if i==6 else []}} for i in range(7)]
    rows.append({'event_id':'last','group_id':'last','member_id':'m1','source_entry':0,'selected':True,'weights':{'nominal':1,'var':1},'fills':{'mass':[[3]]}})
    ret['source_dataset_sha256']=c.digest(ds)
    first=c.analyze(a,ds,ret,rows,max_rows=8,max_products=1000000)
    members.reverse();ret['source_dataset_sha256']=c.digest(ds)
    second=c.analyze(a,ds,ret,rows,max_rows=8,max_products=1000000)
    assert first['observables']['mass']['values']['nominal']==[1,0]
    assert second['observables']['mass']['values']['nominal']==[0,1]
    assert first['source_order_commitment']!=second['source_order_commitment']
    assert first['raw_unweighted_metrics']['mass']['metric_denominator_events']==7


def test_component_in_range_normalization_and_cross_did_signed_gram(tmp_path):
    ds,a,ret,rows=component_case(tmp_path);rows[1]['weights']={'nominal':1,'var':2}
    a['observables'][0]['quantity']['normalization']={'kind':'normalized','scope':'in_range'}
    answer=c.analyze(a,ds,ret,rows,max_rows=100,max_products=1000)
    part=answer['dataset_components']['observables']['mass'];d0,d1=answer['dataset_components']['did_order']
    assert part['values'][d0]['nominal']==[4,0] and part['values'][d1]['nominal']==[0,-3]
    assert part['raw_joint_moments']['state']['second_moment'][0][3]==-12
    assert part['marginals'][d0]['denominators']['nominal']['sumw']==1
    assert part['marginals'][d1]['denominators']['nominal']['sumw']==1
    assert part['aggregation_roundoff_residual']['nominal']==[0,0]


def test_native_many_to_many_components_keep_complete_row_count(tmp_path):
    ds,a,ret,rows=prefix_case(tmp_path)
    second=deepcopy(ret['files'][0]);second['id']='r1';second['pin']['path']='different-inert.root'
    ret['files'].append(second)
    census=[{'id':r['id'],'rows':2,'source_members':r['source_members'],'api':'inert facade'} for r in ret['files']]
    assert c.native_population(census,ret,rows)==census
    # Disjoint correspondence binds each native file count as well as total.
    ret['files'][0]['source_members']=['m0'];ret['files'][1]['source_members']=['m1']
    census[0]['source_members']=['m0'];census[1]['source_members']=['m1']
    with pytest.raises(ValueError,match='connected'):c.native_population(census,ret,rows)


@pytest.mark.parametrize('bad_counts',[False,True])
def test_actual_prefix_case_worker_parent_serialization_complete_source_records(tmp_path,monkeypatch,bad_counts):
    task,cfg,rows=configuration(tmp_path)
    ds,a,ret,rows=prefix_case(tmp_path)
    # Retain the exact authenticated complete-record native facade as input
    # source, rather than an assertion that an unknown query did the right cut.
    plugin=Path(cfg['bundle']['files']['analysis.py']['path'])
    plugin.write_text('import json\ndef analyze(tables,files,ds,a):\n    return json.loads('+repr(json.dumps(rows))+')\n')
    cfg['bundle']['files']['analysis.py']={'path':str(plugin),'sha256':__import__('hashlib').sha256(plugin.read_bytes()).hexdigest(),'size':plugin.stat().st_size}
    cfg['dataset']=write(tmp_path/'prefix_case-dataset.json',ds);cfg['analysis']=write(tmp_path/'prefix_case-analysis.json',a);cfg['returned']=write(tmp_path/'prefix_case-returns.json',ret)
    task={'config':write(tmp_path/'prefix_case-config.json',cfg)}
    rd=tmp_path/'ordinary-control';rd.mkdir();out=rd/'outputs/attempt-1/dataset-query-quantities'
    monkeypatch.setattr(adapter,'_approved',lambda task,out:(rd,{'max_seconds':10}))
    monkeypatch.setattr(w,'native_tables',lambda files,backend:(['inert complete native facade'],[{'id':r['id'],'rows':3 if bad_counts else 4,'source_members':r['source_members'],'api':'inert source-only actual row-count interface'} for r in files]))
    monkeypatch.setattr(w,'runtime_versions',lambda runtime:runtime['versions'])
    from ravel.physics import reinterpret_db
    def inert(command,output,config):
        # In-process stand-in for the worker command: apply its -B so no bytecode cache
        # is written into the closed copied source tree.
        assert command[1:3]==['-I','-B'];monkeypatch.setattr(sys,'dont_write_bytecode',True)
        code=w.main(command[-2:]);return {'exit_code':code,'process_launched':False,'control_facade':True}
    monkeypatch.setattr(reinterpret_db,'execute_native',inert)
    result=adapter.run(task,tmp_path,out)
    if bad_counts:
        assert result['status']=='failed' and not (out/'native/native-event-export.json').exists()
    else:
        assert result['status']=='passed'
        assert result['delivery']['native_row_census'][0]['rows']==4
        assert result['delivery']['raw_unweighted_metrics']['mass']['metric_denominator_events']==4
        assert (out/'native/native-event-export.json').is_file()


def test_missing_required_plot_runtime_cannot_return_successful_tables_only(tmp_path,monkeypatch):
    from ravel.plotting.science_figures import render
    ds,a,ret,rows=population_fixture(tmp_path)
    delivery=c.analyze(a,ds,ret,rows,max_rows=100,max_products=1000)
    result={'status':'passed','task_id':a['task_id'],'operation':'analyze_returned_native_files','delivery':delivery,'remote':None,'limitations':['Synthetic software only'],'physics_validated':False}
    monkeypatch.setitem(sys.modules,'matplotlib',None)
    with pytest.raises(ValueError,match='Required IRIS histogram'):
        render({'mode':'dataset-query-quantities','task':{}},result,tmp_path,tmp_path/'report')
