"""Proposed pure small-population oracles. Author did not run these bodies."""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import pytest
from ravel.physics import root_stream_core as c, root_stream as adapter, root_stream_worker as worker
from root_stream_fixture import population,event_population,accumulate,quantity,pin,put


@pytest.mark.parametrize('chunk',[1,2,3,4,7])
def test_partition_signed_sameevent_covariance_and_full_dsid_denominators(tmp_path,chunk):
    ds,a,cfg,_,_=population(tmp_path);delivery=accumulate(ds,a,cfg['limits'],chunk)
    # Independent rational per-event oracle, no production sum/project helpers.
    for sample,result in zip(ds['samples'],delivery['samples']):
        vectors=[];raw=[]
        for w,sf,variation,fills in event_population()[sample['id']]:
            if sample['kind']=='data' and any(x[0]>=2 for x in fills):continue
            nominal=F(1) if sample['kind']=='data' else F(w)*F(sf)
            weights=[nominal,nominal if sample['kind']=='data' else nominal*F(variation)]
            vector=[F(0)]*6
            for k,weight in enumerate(weights):
                for fill in fills:
                    if 0<=fill[0]<3:vector[k*3+int(fill[0])]+=weight
            vectors.append(vector);raw.append(F(w))
        factor=F(1) if sample['kind']=='data' else F(1000)*F(sample['normalization']['cross_section_pb'])/F(sample['normalization']['sum_weights'])
        sums=[sum(v[i] for v in vectors)*factor for i in range(6)]
        moments=[[sum(v[i]*v[j] for v in vectors)*factor*factor for j in range(6)] for i in range(6)]
        q=result['quantities']['regions']
        assert q['values']=={'nominal':list(map(float,sums[:3])),'up':list(map(float,sums[3:]))}
        assert q['covariance']==[[float(x) for x in row] for row in moments]
        assert result['normalization']==sample['normalization']
        if sample['kind']!='data':assert result['raw_mc_weights']['sumw']==float(sum(raw))
    assert delivery['samples'][0]['quantities']['regions']['covariance'][0][1]>0
    assert sum(row['stop']-row['start'] for row in delivery['coverage'])==12
    assert delivery['samples'][2]['quantities']['regions']['values']['nominal'][2]==0


def test_empty_tree_and_empty_selection_preserve_complete_exposure(tmp_path):
    ds,a,cfg,_,_=population(tmp_path);s=ds['samples'][0];s['members'][0]['entries']=0;ds['samples']=[s]
    acc=c.Stream(ds,a,cfg['limits']);acc.chunk(s['id'],s['members'][0]['id'],0,0,[],[],[])
    result=acc.finish();assert result['coverage']==[{'sample':'background','member':'background_file','start':0,'stop':0}]
    assert result['samples'][0]['quantities']['regions']['values']['nominal']==[0,0,0]


@pytest.mark.parametrize('fault',['gap','duplicate','omit_mc','unknown_quantity','bool_weight'])
def test_source_identity_and_exposure_refusals(tmp_path,fault):
    ds,a,cfg,_,_=population(tmp_path);acc=c.Stream(ds,a,cfg['limits']);entries=[0,1]
    records=[{'source_entry':i,'fills':{'regions':[]}} for i in entries];weights=[{'w':1,'sf':1,'variation':1} for i in entries];start=0
    if fault=='gap':start=1
    if fault=='duplicate':records[1]['source_entry']=0
    if fault=='omit_mc':entries=[0];records=records[:1];weights=weights[:1]
    if fault=='unknown_quantity':records[0]['fills']['other']=[]
    if fault=='bool_weight':weights[0]['w']=True
    with pytest.raises(ValueError):acc.chunk('background','background_file',start,2,entries,records,weights)


@pytest.mark.parametrize('value',[2**63-1,2**64-1])
def test_integer_float64_exactness_not_saturating_cast(value):
    with pytest.raises(ValueError):c.scalar(value)
    assert c.scalar(2**63)==float(2**63)


def test_actual_declared_input_census_and_conditional_blind_entry(tmp_path):
    ds,a,cfg,task,_=population(tmp_path)
    assert c.dataset(ds)==ds;assert c.analysis(a,ds)==a;assert c.config(cfg)==cfg
    inputs=adapter.context_inputs(task,tmp_path)
    assert task['config']['path'] in {str(p) for p in inputs}
    context=adapter.context(task,tmp_path)
    assert context['data_values_or_sr_counts_presented'] is False
    assert 'credential_reference' not in context['site']
    cfg['bundle'].pop('blind_entry')
    with pytest.raises(ValueError):c.config(cfg)


def test_ending_publication_and_native_empty_directory_refusals(tmp_path):
    out=tmp_path/'delivery';out.mkdir();(out/'native').mkdir();adapter.write_new(out/'native/request.json',{})
    value={'status':'passed','physics_validated':False};adapter.write_new(out/'root-stream-result.json',value)
    g=adapter.Guard(value,out,native_outputs=adapter.census(out/'native'))
    cp=adapter.write_new(out/'closure.json',g.closure());g.commitment=deepcopy(cp);result={**value,'commitment':cp}
    assert g.finish(result)
    (out/'native/unselected-directory').mkdir()
    with pytest.raises(ValueError):g.finish(result)
    (out/'native/unselected-directory').rmdir();result['physics_validated']=True
    with pytest.raises(ValueError):g.finish(result)


def test_original_result_closure_cannot_be_rebound(tmp_path):
    out=tmp_path/'delivery';out.mkdir();(out/'native').mkdir();value={'status':'passed','physics_validated':False}
    adapter.write_new(out/'root-stream-result.json',value);g=adapter.Guard(value,out)
    cp=adapter.write_new(out/'closure.json',g.closure());g.commitment=deepcopy(cp)
    altered={**cp,'path':str(tmp_path/'external.json')}
    with pytest.raises(ValueError):g.finish({**value,'commitment':altered})


def test_authenticated_reader_return_buffer_and_ending_bytes(tmp_path):
    p=tmp_path/'request';p.write_bytes(b'original');digest=hashlib.sha256(b'original').hexdigest()
    assert worker.read_pinned(p,digest,32)==b'original'
    p.write_bytes(b'changed!')
    with pytest.raises(ValueError):worker.read_pinned(p,digest,32)


def test_fake_reader_blind_before_kernel_and_weights_before_mutation(tmp_path,monkeypatch):
    import numpy as np
    import awkward as ak
    ds,a,cfg,_,_=population(tmp_path)
    # Real adapter-to-worker API seam with an inert reader; no ROOT/site open.
    ds['samples']=ds['samples'][:1];ds['samples'][0]['members'][0]['entries']=3
    a['blinding']=None;cfg['bundle']['blind_entry']=None
    class Handle:
        def close(self):pass
    class Tree:
        num_entries=3
        def arrays(self,names,entry_start,entry_stop,library):
            return ak.Array({'w':np.array([2.,-1.,3.])[entry_start:entry_stop], 'sf':np.array([.5,2.,1.])[entry_start:entry_stop],
                             'variation':np.ones(3)[entry_start:entry_stop], 'x':np.array([.5,2.5,.5])[entry_start:entry_stop]})
    class Opened:
        def close(self):pass
    class Kernel:
        def analyze(self,table,entries,sample):
            # Changing the table's weight field must not change source weights.
            table['w']=np.full(len(entries),999.)
            return [{'source_entry':int(i),'fills':{'regions':[[.5]]}} for i in entries]
    monkeypatch.setattr(worker,'open_member',lambda *args:(Handle(),None))
    monkeypatch.setattr(worker,'identity',lambda *args:{'same':'original'})
    monkeypatch.setattr(worker,'load_plugin',lambda *args:Kernel())
    result=worker.stream(ds,a,cfg,tmp_path,reader=lambda *args:(Opened(),Tree()))
    assert result['delivery']['samples'][0]['raw_mc_weights']['sumw']==4
    assert result['delivery']['samples'][0]['quantities']['regions']['values']['nominal'][0]==400


def native_fixture(ds,a,cfg,delivery):
    observations=[]
    for sample in ds['samples']:
        for member in sample['members']:
            row={'guid':member['guid'],'size_bytes':member['size_bytes'],'checksum':{k:member['checksum'][k] for k in ('algorithm','value')},'entries':member['entries']}
            observations.append({'member':member['id'],'before':row,'after':deepcopy(row),'evidence_scope':'synthetic source records'})
    return {'schema_version':1,'status':'passed','delivery':delivery,'identities':observations,'physics_validated':False}


def test_data_complement_census_stays_private_and_host_public_projection(tmp_path):
    import json
    ds,a,cfg,_,_=population(tmp_path);full=native_fixture(ds,a,cfg,accumulate(ds,a,cfg['limits'],2))
    public=adapter.public_delivery(full,ds,a);data=public['samples'][2]
    assert data['quantities']['regions']['values']['nominal']==[1,1]
    assert [x['id'] for x in data['quantities']['regions']['bins']]==['CR','VR']
    assert all(x['sample']!='data' for x in public['mc_coverage'])
    assert all(x['member']!='data_file' for x in public['mc_identities'])
    assert data.keys()=={'id','kind','quantities','visibility'}
    assert 'counts' not in data['quantities']['regions'] and 'state' not in data['quantities']['regions']
    assert public['data_completeness_witnesses'][0]['complete'] is True
    assert adapter.model_input_text(json.dumps(public))==json.dumps(public)
    for private in (ds,{'schema_version':1,'samples':ds['samples']},full,full['delivery']):
        with pytest.raises(ValueError):adapter.model_input_text(json.dumps(private))
    # Neither complete DATA entries/ranges nor complement count is serialized
    # into the public analytical packet. MC full exposure remains unaffected.
    assert public['mc_coverage']==[x for x in full['delivery']['coverage'] if x['sample']!='data']


def test_actual_data_mask_precedes_analysis_with_inert_reader(tmp_path,monkeypatch):
    import numpy as np
    import awkward as ak
    ds,a,cfg,_,_=population(tmp_path);ds['samples']=ds['samples'][2:]
    seen=[]
    class Handle:
        def close(self):pass
    class Opened:
        def close(self):pass
    class Tree:
        num_entries=4
        def arrays(self,names,entry_start,entry_stop,library):
            return ak.Array({n:np.array([.5,1.5,2.5,.5],dtype=np.float64)[entry_start:entry_stop] if n=='x' else np.ones(4)[entry_start:entry_stop] for n in names})
    class Blind:
        def allow(self,table,regions):
            assert regions==('CR','VR');return np.asarray(table['x']<2,dtype=bool)
    class Kernel:
        def analyze(self,table,entries,sample):
            assert all(float(x)<2 for x in table['x']);seen.extend(int(x) for x in entries)
            return [{'source_entry':int(i),'fills':{'regions':[[float(x)]]}} for i,x in zip(entries,table['x'])]
    monkeypatch.setattr(worker,'open_member',lambda *args:(Handle(),None))
    monkeypatch.setattr(worker,'identity',lambda handle,member,fs: {'guid':member['guid'],'size_bytes':member['size_bytes'],'checksum':{k:member['checksum'][k] for k in ('algorithm','value')},'entries':member['entries']})
    monkeypatch.setattr(worker,'load_plugin',lambda directory,entry,name:Blind() if entry=='blind.py' else Kernel())
    full=worker.stream(ds,a,cfg,tmp_path,reader=lambda *args:(Opened(),Tree()))
    assert seen==[0,1,3]
    public=adapter.public_delivery(full,ds,a)
    assert public['mc_coverage']==[] and public['mc_identities']==[]
    assert public['samples'][0]['quantities']['regions']['values']['nominal']==[2,1]


@pytest.mark.parametrize('algorithm',['sha256','adler32'])
def test_local_descriptor_member_checksum_and_original_namespace(tmp_path,algorithm):
    import zlib
    p=tmp_path/'member';raw=b'bounded synthetic checksum';p.write_bytes(raw)
    member={'uri':p.as_uri(),'guid':'synthetic','entries':1,'size_bytes':len(raw),'checksum':{'algorithm':algorithm,'value':hashlib.sha256(raw).hexdigest() if algorithm=='sha256' else f'{zlib.adler32(raw)&0xffffffff:08x}'}}
    assert worker.local_member_pin(member)=={'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    handle,_=worker.open_member(member,{})
    try:
        assert worker.identity(handle,member)['entries']==1
        old=tmp_path/'old';p.rename(old);p.write_bytes(raw)
        with pytest.raises(ValueError):worker.identity(handle,member)
    finally:handle.close()
