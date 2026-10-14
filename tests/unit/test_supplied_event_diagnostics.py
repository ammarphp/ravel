"""Synthetic observer, retained and authenticated paired contract acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.validation import diagnostic_plan as plans
from ravel.validation import mpi_observer as observer
from ravel.validation import initialized_settings_retained as retained
from ravel.validation.mpi_paired import paired_effect_inference_v2 as inference
from ravel.validation.mpi_paired import mpi_identity_transport as identity
from ravel.validation.mpi_paired import mpi_paired_estimator as estimator
from ravel.validation.mpi_paired import full_signal_moments as signals
from ravel.validation.mpi_paired import paired_moments
from diagnostic_plan_fixture import metadata, intervention, signal
from test_initialized_settings_retained import fixture as retained_fixture, resources


def pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return pin(path)


def observer_contract(root,meta):
    root.mkdir(parents=True,exist_ok=True)
    source=root/'binary';source.write_text('inert pinned file')
    source_pin={k:v for k,v in pin(source).items() if k!='bytes'}
    inventory=write(root/'runtime.json',{'schema_version':1,'files':[{k:v for k,v in pin(source).items() if k!='bytes'}]})
    inventory.pop('bytes')
    count=len(meta['parameter_grid'])
    stages=[{'id':'observe_'+str(i),'argv':['inert-tool'],'outputs':['left','right'] if i==0 else ['identity.json','tagged.json'] if i==1 else ['unused_'+str(i)],'max_seconds':1,'depends_on':[] if i==0 else ['observe_'+str(i-1)]} for i in range(count+1)]
    r={**resources(root/'new'),'hard_events':0,'original_events':count+7,'selected_events':count+3,'shower_passes':2*(count+3),'builds':0,'detector_runs':1,'conversions':1,'analyses':1}
    doc={'plan':{**meta,'equivalence':{'identity_status':'transport_verified','tagged_status':'tagged_transport_verified','events':r['selected_events']},'loader_stages':['observe_0'],'generated_files':[]},'schema_version':1,'scope':observer.SCOPE,'source_inputs':[source_pin],'runtime_inventory':inventory,'environment':{k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','PYTHONDONTWRITEBYTECODE','DYLD_PRINT_LIBRARIES')},'resources':r,'stages':stages,'selection_contract':source_pin,'helper_sources':[source_pin],'comparison_files':[['left','right']],'identity_reports':['identity.json'],'tagged_report':'tagged.json','platform':observer.platform.platform(),'assumptions':['synthetic supplied inputs']*4}
    path=root/'input.json';write(path,doc)
    return {'input':str(path)},doc,source


@pytest.mark.parametrize('mode',['observer','retained'])
def test_two_evidence_contracts_and_typed_missing_input(tmp_path,monkeypatch,mode):
    results=[]
    for version,(count,format) in enumerate(((1,'json'),(3,'jsonl'))):
        root=tmp_path/str(version);root.mkdir()
        meta=metadata('ANA-000'+str(version+1),count=count,format=format,file='chosen.'+format)
        if mode=='observer':
            task,doc,source=observer_contract(root/'inputs',meta)
            def child(stage,out,environment,deadline,guard):
                for name in stage['outputs']:
                    target=out/name
                    if name in ('identity.json','tagged.json'):
                        target.write_text(json.dumps({'status':'transport_verified' if name=='identity.json' else 'tagged_transport_verified','events':doc['resources']['selected_events']}))
                    else:target.write_text('inert same bytes')
                (out/'native-logs'/(stage['id']+'.log')).write_text('dyld[123]: <ABC-123> '+str(source)+'\n')
                receipt={'status':'completed','pid':123,'actual_returncode':0}
                write(out/'native-logs'/(stage['id']+'.command.json'),receipt)
                return receipt
            monkeypatch.setattr(observer,'child',child)
            class Guard:
                def __init__(self,*args):pass
                def check(self,final=False):return {}
            monkeypatch.setattr(observer,'Guard',Guard)
            out=Path(doc['resources']['resource_root'])/'output';adapter=observer
        else:
            task,doc,state=retained_fixture(root,monkeypatch,plan_metadata=meta)
            out=root/'new/output';adapter=retained
        result=adapter.run(task,root,out)
        assert result['status']=='passed',result.get('error')
        assert result['successful_end_custody'] and result['physics_validated'] is False
        assert json.loads((out/meta['output']['file']).read_text())==result
        assert all(result[k]==meta[k] for k in ('study_identity','parameter_grid','dataset_population'))
        assert result['output_format']==format
        if mode=='observer':assert len(result['native_commands'])==count+1
        results.append(result)
    assert results[0]['parameter_grid']!=results[1]['parameter_grid']
    bad=tmp_path/'missing.json';bad.write_text('{}');task={'input':str(bad)}
    if mode=='retained':task['sha256']=pin(bad)['sha256']
    with pytest.raises(plans.PlanError) as caught:adapter.document(task,tmp_path)
    assert caught.value.code=='missing_input' and caught.value.field=='plan'


def paired_contract(root,n,d):
    root.mkdir(parents=True,exist_ok=True)
    spec=signal(d,n);desc=intervention(n,d)
    source=root/'source.lhe';source.write_text('inert content')
    expected={'subset_exposure':n,'original_generation_exposure':n+3,'subset_pin':pin(source),'full_content_unique':True,'rows':[{'subset_ordinal':i,'original_ordinal':i+1,'full_content_sha256':hashlib.sha256(('full-'+str(i)).encode()).hexdigest(),'original_lhe_event_sha256':hashlib.sha256(('lha-'+str(i)).encode()).hexdigest(),'original_weight':1.,'particle_count':2} for i in range(n)]}
    ep=write(root/'expected.json',expected)
    sources={k:'a'*64 for k in ('selection_source_sha256','diagnostic_source_sha256','rjr_binary_sha256')}
    arms={};trace_rows={}
    for arm in ('on','off'):
        folder=root/arm;folder.mkdir()
        files={}
        for key in ('sidecar','hepmc','delphes','ntuple'):
            p=folder/key;p.write_text('inert '+key);files[key]=pin(p)
        rows=[]
        for i in range(n):
            region=desc['regions'][(i+(arm=='off'))%d]
            rows.append({'event_id':i,'accepted_regions':[] if i==n-1 else [region],'weight_pb':3/n})
        header={'kind':'header','schema_version':1,'level':'reco','weight_unit':'pb','metadata':{'input_events':n,'input_sha256':files['ntuple']['sha256'],**desc['trace_metadata'],**sources}}
        trace=folder/'trace.jsonl';trace.write_text('\n'.join(json.dumps(row) for row in [header,*rows])+'\n');files['trace']=pin(trace);trace_rows[arm]=rows
        files.update(lhe=pin(source),expected_manifest=ep)
        provenance={'status':'content_verified','policy':'original-v1','source_files':{'lhe':pin(source)},'original_events':n,'joined_events':n,'hepmc_content':{'complete_framing':True,'particle_populations_verified':True,'event_numbers':list(range(n))},'rows':[{'original_lhe_ordinal':i,'hepmc_event_number':i,'full_content_sha256':row['full_content_sha256'],'original_lhe_event_sha256':row['original_lhe_event_sha256'],'original_weight':1.,'original_particle_count':2} for i,row in enumerate(expected['rows'])]}
        transport={'status':'transport_verified','events':n,'source_files':files,'original_content_witness':provenance,'mapping':identity.original_map(expected,provenance)}
        tp=write(folder/'transport.json',transport)
        receipt={'status':'completed','actual_returncode':0,'expected_returncode':0,'timed_out':False,'argv':['inert-tool'],'pid':123,'artifacts':[*[files[k] for k in ('sidecar','hepmc','delphes','ntuple','trace')],tp]}
        arms[arm]={'transport_pin':tp,'command_pins':[write(folder/'receipt.json',receipt)]}
    return ep,arms,sources,spec,desc,trace_rows


def test_two_paired_contracts_and_typed_missing_input(tmp_path):
    outputs=[]
    for version,(n,d,format) in enumerate(((6,2,'json'),(9,3,'jsonl'))):
        meta=metadata('ANA-000'+str(version+1),count=d,format=format,file='chosen.'+format)
        ep,arms,sources,spec,desc,rows=paired_contract(tmp_path/str(version),n,d)
        result=inference.infer(expected_pin=ep,arms=arms,selection_sources=sources,signal_spec=spec,descriptor=desc,check_budget=lambda:None)
        plans.publish(tmp_path/str(version)/'output',meta,result)
        assert json.loads((tmp_path/str(version)/'output'/meta['output']['file']).read_text())==result
        assert result['exposure']['analyzed_original_events']==n
        assert len(result['all_bin_moments']['pair_census'])==d+1
        assert result['signal_moments']['channel_order']==spec['channel_order']
        assert sum(result['signal_moments']['counts_on'])==n-1
        assert result['signal_moments']['normalization']['expected_constant_trace_weight_pb']==3/n
        assert result['signal_moments']['yield_covariance_on']==result['signal_moments']['yield_covariance_off'] or result['signal_moments']['yield_cross_covariance_on_off']
        outputs.append(result)
    assert outputs[0]['dataset_population']!=outputs[1]['dataset_population']
    del desc['regions']
    with pytest.raises(plans.PlanError) as caught:inference.validate_descriptor(desc,spec)
    assert caught.value.code=='missing_input' and caught.value.field=='regions'


@pytest.mark.parametrize('change',['weight','event_order','denominator','overlap','metadata','producer','manifest'])
def test_paired_authentication_and_estimator_guards(tmp_path,change):
    ep,arms,sources,spec,desc,rows=paired_contract(tmp_path,6,2)
    if change in ('weight','event_order','denominator','overlap'):
        transport={'status':'transport_verified','mapping':list(range(6))}
        if change=='weight':rows['off'][0]['weight_pb']=2.
        elif change=='event_order':rows['off'][0]['event_id']=99
        elif change=='denominator':
            for row in rows['on']:row['accepted_regions']=[]
        else:rows['on'][0]['accepted_regions']=desc['regions']
        with pytest.raises(ValueError):estimator.compare(rows['on'],rows['off'],transport,transport,desc)
    else:
        if change=='metadata':desc['trace_metadata']['model']='MODEL-0002'
        elif change=='producer':
            receipt=Path(arms['off']['command_pins'][0]['path']);data=json.loads(receipt.read_text());data['actual_returncode']=9;arms['off']['command_pins'][0]=write(receipt,data)
        else:Path(ep['path']).write_text('{}')
        with pytest.raises(ValueError):inference.infer(expected_pin=ep,arms=arms,selection_sources=sources,signal_spec=spec,descriptor=desc,check_budget=lambda:None)


def test_migrated_signal_predicates_preserve_normalization_and_paired_covariance():
    channels=['CH-0001','CH-0002']
    mapping=[{'channel':channels[i],'region':'REG-0001','equals':{'leptons.0.flavour':i,'leptons.1.flavour':i},'lengths':{'leptons':2}} for i in range(2)]
    on=[{'event_id':i,'weight_pb':.75,'accepted_regions':['REG-0001'] if i<3 else [],'leptons':[{'flavour':i%2}]*2} for i in range(4)]
    off=copy.deepcopy(on);off[0]['accepted_regions']=[]
    summary=signals.summarize(on,off,channel_order=channels,channel_map=mapping,trace_regions=['REG-0001'],analyzed_events=4,original_events=7,cross_section_pb=2.,kfactor=1.5,luminosity_pb_inverse=10.)
    assert summary['counts_on']==[2,1] and summary['counts_off']==[1,1]
    assert summary['yields_on']==[15.,7.5] and summary['yield_delta_off_minus_on']==[-7.5,0.]
    assert summary['yield_delta_covariance']==[[56.25,0.],[0.,0.]]
    same=signals.summarize(on,on,channel_order=channels,channel_map=mapping,trace_regions=['REG-0001'],analyzed_events=4,original_events=7,cross_section_pb=2.,kfactor=1.5,luminosity_pb_inverse=10.)
    assert same['yield_delta_covariance']==[[0.,0.],[0.,0.]]
    assert same['yield_cross_covariance_on_off']==same['yield_covariance_on']
    on[0]['leptons'].pop()
    with pytest.raises(ValueError,match='population'):signals.indicator(on[0],mapping,['REG-0001'])


def test_precision_and_interval_disagreement_never_choose_a_favorable_result(tmp_path):
    ep,arms,sources,spec,desc,rows=paired_contract(tmp_path,6,2)
    transport={'status':'transport_verified','mapping':list(range(6))}
    desc['max_standard_error']=1e-12
    result=estimator.compare(rows['on'],rows['off'],transport,transport,desc)
    assert result['classification']=='inconclusive' and not result['precision_passed']
    assert result['inconclusive_reason']=='precision criterion unmet'


@pytest.mark.parametrize('census',[[[1,2],[3]],[[True,0],[0,2]],[[0,0],[0,0]]])
def test_malformed_or_zero_denominator_moments_refuse(census):
    with pytest.raises(ValueError):paired_moments.moments(census)


def test_unmapped_trace_region_requires_supplied_population():
    spec=signal()
    rows=[{'event_id':i,'weight_pb':.75,'accepted_regions':['REG-unknown'] if i==0 else ['REG-0']} for i in range(4)]
    with pytest.raises(ValueError,match='region'):
        signals.summarize(rows,rows,analyzed_events=4,original_events=7,**spec)


def test_tagging_requires_event_count_and_full_identifier_population(tmp_path):
    with pytest.raises(plans.PlanError) as caught:identity.relabel(tmp_path/'missing',tmp_path/'out')
    assert caught.value.code=='missing_input' and caught.value.field=='events'
    with pytest.raises(plans.PlanError) as caught:identity.relabel(tmp_path/'missing',tmp_path/'out',expected=3)
    assert caught.value.field=='identities'
    assert identity.supplied_tags(3,[7,11,19])==[7,11,19]
    with pytest.raises(ValueError):identity.supplied_tags(3,[7,7,19])


def test_observer_children_keep_custody_reserve(tmp_path,monkeypatch):
    import time
    task,doc,source=observer_contract(tmp_path/'inputs',metadata(count=1))
    seen=[]
    def child(stage,out,environment,deadline,guard):
        seen.append(deadline-time.monotonic())
        raise ValueError('synthetic stop after deadline capture')
    monkeypatch.setattr(observer,'child',child)
    class Guard:
        def __init__(self,*args):pass
        def check(self,final=False):return {}
    monkeypatch.setattr(observer,'Guard',Guard)
    result=observer.run(task,tmp_path,Path(doc['resources']['resource_root'])/'output')
    assert result['status']=='failed' and len(seen)==1
    assert seen[0]<=doc['resources']['max_seconds']-observer.CUSTODY_RESERVE_SECONDS


def test_resource_envelope_and_stage_graph_leave_custody_reserve(tmp_path):
    reserve=observer.CUSTODY_RESERVE_SECONDS
    with pytest.raises(ValueError):observer.validate_resources(dict(resources(tmp_path),max_seconds=reserve))
    stage={'id':'one','argv':['inert-tool'],'outputs':['a'],'max_seconds':41,'depends_on':[]}
    with pytest.raises(ValueError,match='reserve'):observer.validate_stages([stage],60)
    assert observer.validate_stages([dict(stage,max_seconds=40)],60)
