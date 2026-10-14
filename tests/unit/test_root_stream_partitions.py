"""Proposed independent population/moment oracles, not executed by the author."""
from copy import deepcopy
from fractions import Fraction as F
import math
import pytest
from ravel.physics import root_stream_core as c,root_stream_partition_core as pc,root_stream_partitions as p
from root_stream_fixture import population,event_population,accumulate,put


def _master(ds,a,grouping,document,entries):
    parts,groups=p.partition_population(ds,grouping,document,entries,100)
    return {'dataset_sha256':c.digest(ds),'analysis_sha256':c.digest(a),'grouping':grouping,'groups':groups,'partitions':parts,'master_sha256':'1'*64,
        'master_pin':{'path':'/synthetic/master.json','sha256':'1'*64,'size':1}}


def _partials(ds,a,cfg,master,events,chunk=2):
    lookup={(s['id'],m['id']):(s,m) for s in ds['samples'] for m in s['members']};results=[]
    for part in master['partitions']:
        acc=pc.PartitionStream(ds,a,{**cfg['limits'],'chunk_entries':chunk},master,part)
        for interval in part['intervals']:
            sample,member=lookup[interval['sample'],interval['member']];acc.group_id=interval['group']
            for start in (range(interval['start'],interval['stop'],chunk) if interval['stop']>interval['start'] else [0]):
                stop=min(start+chunk,interval['stop']);entries=[];records=[];weights=[]
                for i in range(start,stop):
                    raw,sf,variation,fills=events[sample['id']][i]
                    if sample['kind']=='data' and any(fill[0]>=2 for fill in fills):continue
                    entries.append(i);records.append({'source_entry':i,'fills':{'regions':deepcopy(fills)}});weights.append({'w':raw,'sf':sf,'variation':variation})
                acc.chunk(sample['id'],member['id'],start,stop,entries,records,weights)
        touched={v['member'] for v in part['intervals']};identities=[]
        for sample in ds['samples']:
            for member in sample['members']:
                if member['id'] not in touched:continue
                original={k:member[k] for k in ('guid','size_bytes','entries')};original['checksum']={k:member['checksum'][k] for k in ('algorithm','value')}
                identities.append({'member':member['id'],'before':deepcopy(original),'after':deepcopy(original),'evidence_scope':'synthetic metadata; no actual reader'})
        native={'schema_version':1,'status':'passed','delivery':acc.finish(),'identities':identities,'physics_validated':False}
        results.append(({'partition_id':part['id']},native))
    return results

@pytest.mark.parametrize('entries',[1,2,3,5,20])
@pytest.mark.parametrize('chunk',[1,2,7])
def test_complete_disjoint_raw_merge_matches_independent_sameevent_oracle(tmp_path,entries,chunk):
    ds,a,cfg,task,proof=population(tmp_path);events=event_population()
    master=_master(ds,a,{'kind':'independent_entries','source':proof,'statement':'Synthetic justified independent entry premise'},None,entries)
    partials=_partials(ds,a,cfg,master,events,chunk)
    merged=p._aggregate(master,partials,ds,a,{**cfg['limits'],'chunk_entries':chunk})
    serial=accumulate(ds,a,cfg['limits'],chunk,events)
    assert merged['delivery']['samples']==serial['samples']
    for sample,row in zip(ds['samples'],merged['delivery']['samples']):
        vectors=[]
        for raw,sf,variation,fills in events[sample['id']]:
            if sample['kind']=='data' and any(v[0]>=2 for v in fills):continue
            weights=[F(1),F(1)] if sample['kind']=='data' else [F(raw)*F(sf),F(raw)*F(sf)*F(variation)]
            vector=[F(0)]*6
            for k,w in enumerate(weights):
                for fill in fills:
                    if 0<=fill[0]<3:vector[3*k+int(fill[0])]+=w
            vectors.append(vector)
        factor=F(1) if sample['kind']=='data' else F(1000)*F(sample['normalization']['cross_section_pb'])/F(sample['normalization']['sum_weights'])
        q=row['quantities']['regions'];assert q['values']['nominal']==[float(sum(v[i] for v in vectors)*factor) for i in range(3)]
        assert q['covariance']==[[float(sum(v[i]*v[j] for v in vectors)*factor**2) for j in range(6)] for i in range(6)]
        assert row['normalization']==sample['normalization']
    assert sum(r['stop']-r['start'] for r in merged['delivery']['coverage'])==12

@pytest.mark.parametrize('entries',[2,3,20])
def test_complete_correlated_groups_are_indivisible_and_squared_after_record_sum(tmp_path,entries):
    ds,a,cfg,task,proof=population(tmp_path);ds['samples']=ds['samples'][:1];events={'background':event_population()['background']}
    document={'schema_version':1,'kind':'physical-event-groups','groups':[
        {'id':'pair','sample':'background','spans':[{'member':'background_file','start':0,'stop':2}]},
        {'id':'empty','sample':'background','spans':[{'member':'background_file','start':2,'stop':3}]},
        {'id':'end','sample':'background','spans':[{'member':'background_file','start':3,'stop':5}]}]}
    master=_master(ds,a,{'kind':'declared_groups','source':proof,'statement':'Complete source-bound synthetic group identity'},document,entries)
    parts=_partials(ds,a,cfg,master,events);merged=p._aggregate(master,parts,ds,a,cfg['limits']);result=merged['delivery']['samples'][0]
    groups=[]
    for indices in ([0,1],[2],[3,4]):
        vector=[F(0)]*6
        for i in indices:
            raw,sf,v,fills=events['background'][i]
            for k,w in enumerate((F(raw)*F(sf),F(raw)*F(sf)*F(v))):
                for fill in fills:
                    if 0<=fill[0]<3:vector[k*3+int(fill[0])]+=w
        groups.append(vector)
    assert result['quantities']['regions']['covariance']==[[float(sum(v[i]*v[j] for v in groups)*F(200)**2) for j in range(6)] for i in range(6)]
    assert result['raw_mc_weights']['sumw2']==(2-1)**2+0**2+(3+1)**2
    assert result['raw_mc_weights']['record_sumw2']==2**2+(-1)**2+0**2+3**2+1**2
    assert result['quantities']['regions']['state']['counts']['records']==3
    assert merged['delivery']['sampling_law']==pc.GROUP_LAW
    assert all(sum('pair' in part['group_ids'] for part in master['partitions'])==1 for _ in [0])

@pytest.mark.parametrize('mutation',['duplicate','omit','coverage_gap','source','schema','weights','normalization'])
def test_raw_reduction_refuses_changed_replayed_incomplete_population(tmp_path,mutation):
    ds,a,cfg,task,proof=population(tmp_path);m=_master(ds,a,{'kind':'independent_entries','source':proof,'statement':'Explicit premise'},None,2)
    rows=_partials(ds,a,cfg,m,event_population())
    if mutation=='duplicate':rows[1]=deepcopy(rows[0])
    elif mutation=='omit':rows.pop()
    elif mutation=='coverage_gap':
        native=rows[0][1];native['delivery']['coverage'][0]['start']=1;native['delivery']['coverage_sha256']=c.digest(native['delivery']['coverage'])
    elif mutation=='source':rows[0][1]['identities'][0]['after']['entries']+=1
    elif mutation=='schema':rows[0][1]['delivery']['samples'][0]['quantities']['regions']['contract']['bins'].pop()
    elif mutation=='weights':rows[0][1]['delivery']['samples'][0]['quantities']['regions']['contract']['weight_names'].reverse()
    else:ds['samples'][0]['normalization']['sum_weights']=999 # master identity is enforced before reduction
    with pytest.raises((ValueError,KeyError,IndexError)):p._aggregate(m,rows,ds,a,cfg['limits'])


def test_expansion_transport_retains_cancellation_beyond_rounded_partition_sum():
    from root_stream_fixture import quantity
    contract=quantity();serial=c.Moments(contract);left=c.Moments(contract);right=c.Moments(contract)
    for i,value in enumerate([1e16,1.,-1e16]):
        row={'nominal':value,'up':value};serial.event(row,[[.5]]);(left if i<2 else right).event(row,[[.5]])
    merged=c.Moments(contract)
    for part in (left,right):pc.merge_moments(merged,pc.dump_moments(part))
    assert left.sums[0].value()+right.sums[0].value()==0.
    assert merged.sums[0].value()==serial.sums[0].value()==math.fsum([1e16,1.,-1e16])==1.
    assert merged.result(1.)==serial.result(1.)


def test_empty_original_member_and_zero_fills_survive_partition_coverage(tmp_path):
    ds,a,cfg,task,proof=population(tmp_path);ds['samples']=ds['samples'][:1];ds['samples'][0]['members'][0]['entries']=0
    m=_master(ds,a,{'kind':'independent_entries','source':proof,'statement':'Explicit premise'},None,2)
    merged=p._aggregate(m,_partials(ds,a,cfg,m,{'background':[]}),ds,a,cfg['limits'])
    assert merged['delivery']['coverage']==[{'sample':'background','member':'background_file','start':0,'stop':0}]
    assert merged['delivery']['samples'][0]['quantities']['regions']['state']['counts']['records']==0
    assert merged['delivery']['samples'][0]['quantities']['regions']['values']['nominal']==[0.,0.,0.]


def test_one_complete_physical_group_can_span_two_original_members_without_split(tmp_path):
    ds,a,cfg,task,proof=population(tmp_path);ds['samples']=ds['samples'][:1]
    first=ds['samples'][0]['members'][0];first['entries']=2
    second=deepcopy(first);second.update(id='second_file',guid='guid-second',did='synthetic:second',
        uri='file://'+str(tmp_path/'second.root'),entries=3)
    ds['samples'][0]['members'].append(second)
    doc={'schema_version':1,'kind':'physical-event-groups','groups':[
        {'id':'head','sample':'background','spans':[{'member':first['id'],'start':0,'stop':1}]},
        {'id':'cross-file','sample':'background','spans':[{'member':first['id'],'start':1,'stop':2},
            {'member':second['id'],'start':0,'stop':1}]},
        {'id':'tail','sample':'background','spans':[{'member':second['id'],'start':1,'stop':3}]}]}
    master=_master(ds,a,{'kind':'declared_groups','source':proof,'statement':'Complete explicit cross-member groups'},doc,2)
    owner=next(part for part in master['partitions'] if 'cross-file' in part['group_ids'])
    assert len(owner['intervals'])==2 and all('cross-file' not in part['group_ids'] for part in master['partitions'] if part is not owner)
    acc=pc.PartitionStream(ds,a,cfg['limits'],master,owner);acc.group_id='cross-file'
    acc.chunk('background',first['id'],1,2,[1],[{'source_entry':1,'fills':{'regions':[[.5]]}}],[{'w':2.,'sf':1.,'variation':2.}])
    acc.chunk('background',second['id'],0,1,[0],[{'source_entry':0,'fills':{'regions':[[1.5]]}}],[{'w':-1.,'sf':1.,'variation':.5}])
    row=acc.finish()['samples'][0];q=pc.restore_moments(row['quantities']['regions'],a['quantities'][0]['contract']).result(1.)
    assert q['state']['counts']['records']==1 and q['values']['nominal']==[2.,-1.,0.]
    assert q['covariance'][0][1]==-2. and q['covariance'][0][4]==-1.
    assert math.fsum(row['raw_mc_partials']['sumw2'])==1.
    assert math.fsum(row['raw_mc_partials']['record_sumw2'])==5.


@pytest.mark.parametrize('fault',['oversized_group','missing_group','duplicate_span','foreign_sample','too_many_partitions'])
def test_grouping_and_partition_allocation_never_truncate_or_infer_independence(tmp_path,fault):
    ds,a,cfg,task,proof=population(tmp_path)
    grouping={'kind':'declared_groups','source':proof,'statement':'Pinned explicit physical group source'}
    doc={'schema_version':1,'kind':'physical-event-groups','groups':[
        {'id':sample['id'],'sample':sample['id'],'spans':[{'member':member['id'],'start':0,'stop':member['entries']}]}
        for sample in ds['samples'] for member in sample['members']]}
    entries=20;maximum=100
    if fault=='oversized_group':entries=2
    elif fault=='missing_group':doc['groups'].pop()
    elif fault=='duplicate_span':doc['groups'][0]['spans'].append(deepcopy(doc['groups'][0]['spans'][0]))
    elif fault=='foreign_sample':doc['groups'][0]['spans'][0]['member']='signal_file'
    else:entries=1;maximum=1;grouping['kind']='independent_entries';doc=None
    with pytest.raises(ValueError):p.partition_population(ds,grouping,doc,entries,maximum)


@pytest.mark.parametrize('schema,megabytes,accepted',[(1,32,True),(1,33,False),(2,40,True),(2,65,False)])
def test_native_request_transport_explicit_schema_allocation_keeps_legacy_bound(schema,megabytes,accepted):
    from ravel.physics import root_stream as stream
    class Buffer:
        calls=0
        def read(self,pin,base,maximum):
            self.calls+=1
            assert maximum==64*1024**2
            return None,stream.encoded({'config':{'schema_version':schema}})
    captured=Buffer();pin={'path':'/synthetic/request','sha256':'1'*64,'size':megabytes*1024**2}
    if accepted:assert stream.read_request(captured,pin,None)['config']['schema_version']==schema
    else:
        with pytest.raises(ValueError):stream.read_request(captured,pin,None)
    assert captured.calls==(0 if megabytes>64 else 1)
