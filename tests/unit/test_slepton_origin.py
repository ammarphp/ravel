"""Original-exposure origin accounting with malformed/absent-row controls."""
import copy
import json
import math
from pathlib import Path
import pytest
from ravel.physics import slepton_origin as origin
from ravel.physics import compressed_validation as cv


def particle(pid,uid,m1=-1,m2=-1,status=1):
    return dict(pid=pid,uid=uid,m1=m1,m2=m2,status=status,pt=6.,eta=.2,phi=.1,energy=7.)


def event(kind='four',key=10,weight=2.):
    pair=(1000011,-1000011) if kind=='four' else (1000015,-1000015) if kind=='stau' else (1000015,-2000015)
    p=[particle(pair[0],91,status=22),particle(pair[1],42,status=22),particle(1000022,15,0),particle(1000022,19,1)]
    if kind=='four':p.extend([particle(11,100,0),particle(-11,200,1)])
    else:p.extend([particle(15,100,0,status=2),particle(-15,200,1,status=2),particle(11,300,4),particle(-13,400,5)])
    indices=[4,5] if kind=='four' else [6,7]
    reco=[dict(index=i,flavour='electron' if abs(p[j]['pid'])==11 else 'muon',ref=p[j]['uid'],pt=6.,eta=.2,phi=.1)for i,j in enumerate(indices)]
    return dict(source_entry=key,event_number=key,weight=weight,particles=p,reco=reco)


def trace(key,weight,region=None,flavours=(0,0),solved=True):
    t=cv.new_event(key,weight);t['rjr_status']='solved' if solved else 'not_reached'
    for k in cv.PREFIX:t['predicates'][k]=True
    t['predicates']['two_signal_leptons']=True
    t['leptons']=[{'flavour':f}for f in flavours]
    if not solved:t['predicates']['baseline_lepton']=False
    t['accepted_regions']=[region] if region else []
    return t


def fixture():
    mapping={'SRee':{'region':'SR','flavour':'isee'},'SRmm':{'region':'SR','flavour':'ismm'},'CRall':{'region':'CR'}}
    events=[event('four',10),event('mixed',20),event('four',30)]
    native=[{'event_id':e['event_number'],'weight_pb':.1}for e in events]
    traces=[trace(10,.1,'SR'),trace(20,.1,'CR',(0,1)),trace(30,.1,solved=False)]
    arrays={'Event':[10,20],'eventWeight':[.1,.1],'isee':[1,0],'ismm':[0,0],'SR':[.1,0.],'CR':[0.,.1]}
    return events,native,traces,arrays,mapping


def run_fixture(f=None):
    return origin.decompose(*(f or fixture()),lumi=100,scale=.05,expected_events=3)


def test_four_stau_and_mixed_signed_pairs():
    for kind,pair in [('four',[-1000011,1000011]),('stau',[-1000015,1000015]),('mixed',[-2000015,1000015])]:
        row=origin.analyze_origin(event(kind))
        assert row['signed_root_pair']==pair
        assert row['category']==('four_state_only' if kind=='four' else 'contains_stau')
        assert row['overlays']['any_reco_stau_tau_descendant']==(kind!='four')


def test_exposure_category_moments_and_all_flavour_cr_preserved():
    result=run_fixture();assert result['input_events']==3
    assert result['categories']['contains_stau']['sumw_pb']==.1
    assert result['all_events']['sumw_pb']==pytest.approx(.3)
    assert result['channels'][2]['categories']['contains_stau']['yield']==10
    assert result['channels'][2]['categories']['contains_stau']['sumw2_pb2']==pytest.approx(.01)
    assert result['channels'][2]['overlapping_reco_origin_event_subsets']['any_reco_stau_tau_descendant']['moments']['count']==1
    assert result['channels'][0]['categories']['contains_stau']['precision_status']=='zero_selected_precision_unresolved'
    assert result['physics_certified'] is False


def test_shuffled_unique_ids_are_joined_by_key():
    data=list(fixture());data[0]=data[0][::-1];data[1]=data[1][::-1];data[2]=data[2][::-1]
    data[3]={k:v[::-1] for k,v in data[3].items()}
    assert run_fixture(data)==run_fixture()

@pytest.mark.parametrize('mutation',['missing_root','extra_root','same_sign','missing_bino','unsupported_root'])
def test_unresolved_topology_stays_in_selected_denominator(mutation):
    data=list(fixture());p=data[0][1]['particles']
    if mutation=='missing_root':p[1]['pid']=-22
    elif mutation=='extra_root':p.append(particle(1000013,900,status=22))
    elif mutation=='same_sign':p[1]['pid']*=-1
    elif mutation=='missing_bino':p[2]['status']=2
    else:p[1]['pid']=-3000015
    result=run_fixture(data)
    assert result['input_events']==3 and result['categories']['unresolved_topology']['count']==1
    assert result['channels'][2]['categories']['unresolved_topology']['yield']==10
    assert result['category_attribution_status']=='unresolved_selected_topology'


def test_unrelated_tau_does_not_become_stau_descendant():
    e=event('four');e['particles'].extend([particle(15,500,status=2),particle(13,501,6)])
    e['reco'].append(dict(index=0,flavour='muon',ref=501,pt=5.,eta=.1,phi=.2))
    row=origin.analyze_origin(e)
    assert row['category']=='four_state_only'
    assert row['overlays']['any_reco_other_tau_descendant']
    assert not row['overlays']['any_reco_stau_tau_descendant']


def test_stau_tau_lineage_follows_copies_not_just_tau_flag():
    e=event('stau');e['particles'][6]['status']=2;e['particles'].append(particle(11,700,6));e['reco'][0]['ref']=700
    row=origin.analyze_origin(e)
    assert row['reco_leptons'][0]['origin']=='stau_tau_descendant'
    assert row['reco_leptons'][0]['stau_tau_root_indices']==[0]

@pytest.mark.parametrize('mutation',['mother_outside','cycle','duplicate_uid','missing_ref','duplicate_ref'])
def test_malformed_ancestry_fails_with_event_identity(mutation):
    data=list(fixture());e=data[0][1]
    if mutation=='mother_outside':e['particles'][6]['m1']=999
    elif mutation=='cycle':e['particles'][6]['m1']=6
    elif mutation=='duplicate_uid':e['particles'][2]['uid']=e['particles'][0]['uid']
    elif mutation=='missing_ref':e['reco'][0]['ref']=999
    else:e['reco'].append(copy.deepcopy(e['reco'][0]))
    with pytest.raises(ValueError,match='event 20'):run_fixture(data)

@pytest.mark.parametrize('mutation',['duplicate_native','missing_native','duplicate_trace','missing_trace','duplicate_delphes','missing_delphes','duplicate_analysis','missing_selected','extra_analysis','changed_raw_weight','changed_converted_weight','changed_analysis_weight','changed_region_weight','changed_flavour','unknown_region','unknown_rejection','overlapping_channels'])
def test_impossible_join_or_normalization_fails(mutation):
    data=list(fixture());events,native,traces,arrays,mapping=data
    if mutation=='duplicate_native':native.append(copy.deepcopy(native[0]))
    elif mutation=='missing_native':native.pop()
    elif mutation=='duplicate_trace':traces.append(copy.deepcopy(traces[0]))
    elif mutation=='missing_trace':traces.pop()
    elif mutation=='duplicate_delphes':events.append(copy.deepcopy(events[0]))
    elif mutation=='missing_delphes':events.pop()
    elif mutation=='duplicate_analysis':arrays['Event'][1]=10
    elif mutation=='missing_selected':data[3]={k:v[:1]for k,v in arrays.items()}
    elif mutation=='extra_analysis':arrays['Event'][1]=999
    elif mutation=='changed_raw_weight':events[0]['weight']=20
    elif mutation=='changed_converted_weight':native[0]['weight_pb']=1
    elif mutation=='changed_analysis_weight':arrays['eventWeight'][0]=1
    elif mutation=='changed_region_weight':arrays['SR'][0]=1
    elif mutation=='changed_flavour':arrays['isee'][0]=0;arrays['ismm'][0]=1
    elif mutation=='unknown_region':traces[0]['accepted_regions']=['UNKNOWN']
    elif mutation=='unknown_rejection':traces[2]['predicates']['baseline_lepton']=None
    else:traces[0]['accepted_regions'].append('CR');arrays['CR'][0]=.1
    with pytest.raises(ValueError):run_fixture(data)


def test_signed_weights_are_retained_without_absolute_value_rebase():
    data=list(fixture());data[0][1]['weight']=-2;data[1][1]['weight_pb']=-.1;data[2][1]['weight_pb']=-.1;data[3]['eventWeight'][1]=-.1;data[3]['CR'][1]=-.1
    result=run_fixture(data)
    assert result['categories']['contains_stau']['sumw_pb']==-.1
    assert result['categories']['contains_stau']['sumw2_pb2']==pytest.approx(.01)
    assert result['all_events']['negative_weights']==1


def test_shared_event_covariance_and_boundary_precision():
    full=origin.Moments();part=origin.Moments()
    for w in [1,1,1,1]:full.add(w)
    part.add(1)
    fraction=origin.subset_fraction(part.result(1),full.result(1))
    assert fraction['ratio']==.25 and fraction['standard_error']==pytest.approx(math.sqrt(.25*.75/4))
    assert fraction['numerator_denominator_covariance_pb2']==1
    assert origin.subset_fraction(full.result(1),full.result(1))['standard_error'] is None


def model_fixture():
    result=run_fixture();metadata={'compressed_signal_model':'full','additional_scale':1,'acceptance_certified':False,'sample':'signal','mc_stat_policy':'shapesys','channels':[]}
    background={'channels':[]};patch=[]
    for i,row in enumerate(result['channels']):
        total=row['total'];modifier='mc'+str(i)
        metadata['channels'].append({'channel':row['channel'],'mapping':row['mapping'],'sumw':total['sumw_pb'],'sumw2':total['sumw2_pb2'],'nominal_yield':total['yield'],'mc_stat_error':total['mc_error'],'nonzero_weights':total['nonzero_weights'],'negative_weights':total['negative_weights'],'mc_stat_modifier':modifier if total['sumw2_pb2'] else None})
        background['channels'].append({'name':row['channel'],'samples':[]})
        modifiers=[{'name':'mu','type':'normfactor','data':None}]
        if total['sumw2_pb2']:modifiers.append({'name':modifier,'type':'shapesys','data':[total['mc_error']]})
        patch.append({'op':'add','path':f'/channels/{i}/samples/0','value':{'name':'signal','data':[total['yield']],'modifiers':modifiers}})
    return result,metadata,background,patch


def test_unsplit_model_moments_positive_control():origin.validate_model_moments(*model_fixture())

@pytest.mark.parametrize('mutation',['rebased_subset','changed_sumw2','missing_channel','changed_mapping','wrong_patch','missing_mc'])
def test_unsplit_metadata_and_patch_boundaries(mutation):
    result,meta,bkg,patch=model_fixture()
    if mutation=='rebased_subset':meta['channels'][0]['sumw']*=3
    elif mutation=='changed_sumw2':meta['channels'][0]['sumw2']*=3
    elif mutation=='missing_channel':meta['channels'].pop()
    elif mutation=='changed_mapping':meta['channels'][0]['mapping']={'region':'CR'}
    elif mutation=='wrong_patch':patch[0]['value']['data'][0]*=2
    else:patch[0]['value']['modifiers'].pop()
    with pytest.raises(ValueError):origin.validate_model_moments(result,meta,bkg,patch)


def lhe(tmp_path,pids=(1000015,-2000015),bad_mother=False):
    file=tmp_path/'sample.lhe'
    rows=['<LesHouchesEvents>','<event>','4 7 0.2 1 1 1','1 -1 0 0 0 0 0 0 6500 6500 0 0 0','-1 -1 0 0 0 0 0 0 -6500 6500 0 0 0']
    rows.extend(f'{pid} 1 {3 if bad_mother else 1} 2 0 0 0 0 0 150 150 0 0'for pid in pids)
    rows+=['</event>','</LesHouchesEvents>'];file.write_text('\n'.join(rows));return file


def test_lhe_inventory_keeps_signed_mixed_pair_and_separate_identity(tmp_path):
    result=origin.lhe_inventory(lhe(tmp_path),expected_events=1,applied_cross_section_pb=.236)
    assert result['signed_pairs']['-2000015,1000015']['sumw_pb']==.236
    assert result['subprocess_counts']=={'7':1}
    assert result['event_join_to_delphes'].startswith('not_established')


def test_lhe_missing_exposure_and_invalid_mothers_fail(tmp_path):
    with pytest.raises(ValueError):origin.lhe_inventory(lhe(tmp_path),expected_events=2,applied_cross_section_pb=.2)
    with pytest.raises(ValueError):origin.lhe_inventory(lhe(tmp_path,bad_mother=True),expected_events=1,applied_cross_section_pb=.2)


def test_lhe_auxiliary_weight_metadata_is_explicit_and_unapplied(tmp_path):
    path=lhe(tmp_path)
    metadata="<rwgt>\n<wgt id='scale_up'>2.5</wgt>\n<wgt id='scale_down'>-3</wgt>\n</rwgt>\n<weights>2.5 -3</weights>"
    path.write_text(path.read_text().replace('</event>',metadata+'\n</event>'))
    result=origin.lhe_inventory(path,expected_events=1,applied_cross_section_pb=.236)
    assert result['raw_sumw']==.2 and result['raw_sumw2']==pytest.approx(.04)
    assert result['signed_pairs']['-2000015,1000015']['sumw_pb']==.236
    assert result['auxiliary_weights']['recognized_blocks']=={'rwgt':1,'weights':1}
    assert result['auxiliary_weights']['rwgt_id_event_counts']=={'scale_down':1,'scale_up':1}


@pytest.mark.parametrize('extra',[
    '1000015 1 0 0 0 0 0 0 0 150 150 0 9',
    "<rwgt><wgt id='a'>2</wgt></rwgt>\n1000015 1 0 0 0 0 0 0 0 150 150 0 9",
    "<rwgt>1000015 1 0 0 0 0 0 0 0 150 150 0 9</rwgt>",
    "<rwgt><wgt id='a'>2</wgt>3</rwgt>",
    "<rwgt><wgt id='a'>2</rwgt>",
    "<rwgt><wgt id='a'>2</wgt><wgt id='a'>3</wgt></rwgt>",
    "<rwgt><wgt id='a'>NaN</wgt></rwgt>",
    '<weights>1e999</weights>',
    '<unknown>1</unknown>',
    '<weights>1</weights><weights>2</weights>',
])
def test_lhe_surplus_records_and_malformed_weight_xml_reject(tmp_path,extra):
    path=lhe(tmp_path,pids=(1000011,-1000011))
    path.write_text(path.read_text().replace('</event>',extra+'\n</event>'))
    with pytest.raises(ValueError):origin.lhe_inventory(path,expected_events=1,applied_cross_section_pb=.2)


@pytest.mark.parametrize('header',['4 7','4 7 .2 1 1 1 extra','4 7 NaN 1 1 1'])
def test_lhe_malformed_header_is_declared_diagnostic_error(tmp_path,header):
    path=lhe(tmp_path);path.write_text(path.read_text().replace('4 7 0.2 1 1 1',header))
    with pytest.raises(ValueError):origin.lhe_inventory(path,expected_events=1,applied_cross_section_pb=.2)


def test_changed_plan_pin_fails_without_generation_and_retains_failure(tmp_path):
    plan=tmp_path/'plan.json';plan.write_text('{}');out=tmp_path/'diagnostic'
    with pytest.raises(ValueError,match='pin changed'):origin.run({'path':str(plan),'sha256':'0'*64},out)
    failure=json.loads((out/'failure.json').read_text());assert failure['complete_population'] is False
    assert not (out/'origin.json').exists()
    with pytest.raises(FileExistsError):origin.run({'path':str(plan),'sha256':'0'*64},out)


def test_nonmodel_one_lepton_track_row_is_preserved_without_inventing_track_flavour():
    data=list(fixture());data[2][0]['predicates']['two_signal_leptons']=False;data[2][0]['leptons']=[{'flavour':0}]
    data[2][0]['accepted_regions']=[];data[3]['SR'][0]=0
    result=run_fixture(data)
    assert result['input_events']==3 and result['channels'][0]['total']['count']==0
    data[2][0]['accepted_regions']=['SR'];data[3]['SR'][0]=.1
    with pytest.raises(ValueError,match='two-lepton evidence'):run_fixture(data)
