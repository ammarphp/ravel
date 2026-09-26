"""Adversarial fixed-event, detector-definition and likelihood-mapping controls."""
from copy import deepcopy
import json
import math
from pathlib import Path
import pytest
from ravel.physics.event_census import census
from ravel.physics.reconstructed_events import run, object_contract, selection_spec
from ravel.physics.region_mapping import apply_mapping


def hepmc(energy=3500, weight=1, number=0, same_direction=False):
    return f'''HepMC::Version 3.03.01
HepMC::Asciiv3-START_EVENT_LISTING
W nominal
E {number} 1 4
U GEV MM
W {weight}
P 1 0 2212 0 0 {energy} {energy} 0 4
P 2 0 2212 0 0 {energy if same_direction else -energy} {energy} 0 4
V -1 0 [1,2]
P 3 -1 11 75 0 0 75 0 1
P 4 -1 -11 -75 0 0 75 0 1
HepMC::Asciiv3-END_EVENT_LISTING
'''


def metadata():
    return {'schema_version': 1, 'event_level': 'hadron', 'beam_pdg': [2212, 2212],
            'beam_energy_gev': [3500, 3500], 'weight_names': ['nominal'], 'events': 1,
            'groups': 'independent', 'cross_section_pb': 1., 'source': 'synthetic structural fixture, not physical generator events'}


def test_hepmc3_census_and_signed_weights(tmp_path):
    p = tmp_path/'events.hepmc'
    p.write_text(hepmc(weight=-2))
    r = census(p, metadata())
    assert r['sumw'] == [-2]
    assert r['group_weight_second_moments'] == [[4]]
    assert r['events'] == 1


@pytest.mark.parametrize('mutation, message', [
    (lambda s: s.replace('END_EVENT_LISTING','MISSING_END'), 'incomplete'),
    (lambda s: s.replace('E 0 1 4','E 0 1 5'), 'particle inventory'),
    (lambda s: s.replace('W nominal', 'W wrong'), 'weight names'),
    (lambda s: s.replace('W 1\n','W nan\n'), 'finiteness'),
    (lambda s: s.replace('U GEV MM\n',''), 'units'),
    (lambda s: s.replace('W 1\n','W 0\n'), 'zero nominal'),
    (lambda s: s.replace('P 2 0 2212 0 0 -3500','P 2 0 2212 0 0 3500'), 'opposing'),
    (lambda s: s.replace('3500','6500'), 'beam'),
])
def test_malformed_census_refuses(tmp_path, mutation, message):
    p = tmp_path/'events.hepmc'; p.write_text(mutation(hepmc()))
    with pytest.raises(ValueError, match=message):
        census(p, metadata())


def test_hepmc2_exact_header_offsets(tmp_path):
    p = tmp_path/'events.hepmc'
    p.write_text('''HepMC::Version 2.06.11
HepMC::IO_GenEvent-START_EVENT_LISTING
E 7 -1 1 0.1 0.01 0 -1 1 1 2 2 123 456 1 2.5
N 1 "nominal"
U GEV MM
V -1 0 0 0 0 0 2 2 0
P 1 2212 0 0 3500 3500 0 4 0 0 -1 0
P 2 2212 0 0 -3500 3500 0 4 0 0 -1 0
P 3 11 75 0 0 75 0 1 0 0 0 0
P 4 -11 -75 0 0 75 0 1 0 0 0 0
HepMC::IO_GenEvent-END_EVENT_LISTING
''')
    assert census(p, metadata())['sumw'] == [2.5]


def test_correlated_subevents_and_duplicate_independent_ids(tmp_path):
    event = hepmc().split('E 0')[1].split('HepMC::Asciiv3-END')[0]
    text = hepmc().replace('HepMC::Asciiv3-END', 'E 0'+event.replace('W 1\n','W -0.5\n')+'HepMC::Asciiv3-END')
    p = tmp_path/'events.hepmc'; p.write_text(text)
    m = metadata(); m['events'] = 2
    with pytest.raises(ValueError, match='duplicate independent'):
        census(p, m)
    m['groups'] = 'correlated_event_number'
    result = census(p, m)
    assert result['independent_groups'] == 1
    assert result['sumw'] == [.5]
    assert result['group_weight_second_moments'] == [[.25]]


def contract():
    return {'schema_version': 1, 'level': 'reconstructed', 'source': 'synthetic detector-boundary control',
            'energy_unit': 'GeV', 'flags': {'electron': {'loose': 1}, 'muon': {'loose': 1}, 'jet': {'b70': 4}},
            'response_evidence': [], 'weight_names': ['nominal']}


def selection():
    definitions = {k: {'pt': 20, 'eta': 2.5, 'id': 0} for k in ('electron','muon','jet')}
    return {'name': 'synthetic_dilepton_and_jets', 'objects': definitions, 'signal': deepcopy(definitions),
            'overlap_removal': [{'remove': 'jet', 'near': 'electron', 'dR': .2}],
            'regions': [{'name': 'dilepton', 'cuts': [{'var': 'nLep', 'op': '>=', 'val': 2}]},
                        {'name': 'zero_lepton', 'cuts': [{'var': 'nLep', 'op': '==', 'val': 0}]}]}


def obj(pt=30, eta=0, phi=0):
    return {'pt':pt,'eta':eta,'phi':phi,'mass':0,'charge':1,'idbits':1}


def event(eid='1', leptons=None, weight=1, group=None):
    return {'event_id':eid,'group_id':group or eid,'weights':{'nominal':weight},
            'objects':{'electron':leptons or [],'muon':[],'jet':[]},'met':{'pt':30,'phi':1}}


def execute(tmp_path, events, spec=None, c=None, reference=None):
    for name, value in [('events', events), ('selection',spec or selection()), ('objects', c or contract())]:
        (tmp_path/f'{name}.json').write_text(json.dumps(value))
    task = {'events':'events.json','selection':'selection.json','object_contract':'objects.json'}
    if reference is not None:
        (tmp_path/'reference.json').write_text(json.dumps(reference)); task['reference']='reference.json'
    return run(task,tmp_path,tmp_path/'output')


def test_all_events_retained_and_id_threshold_boundaries(tmp_path):
    rows = [event('1',[obj(pt=20),obj(pt=20,phi=math.pi)]), event('2',[obj(eta=2.5)]),event('3',weight=-.5)]
    ref = {'source':'independent analytic boundary decisions','events':[
        {'event_id':'1','regions':['dilepton']},{'event_id':'2','regions':['zero_lepton']},{'event_id':'3','regions':['zero_lepton']}]}
    result = execute(tmp_path,rows,reference=ref)
    assert result['events'] == 3
    assert result['yields']['nominal'] == [1,.5]
    assert result['covariance']['nominal'] == [[1,0],[0,1.25]]
    assert result['reference_comparison']['matched_events'] == 3
    assert len(json.loads((tmp_path/'output/decisions.json').read_text())) == 3


def test_omitted_rejected_reference_events_cannot_pass(tmp_path):
    with pytest.raises(ValueError,match='population differs'):
        execute(tmp_path,[event()],reference={'source':'test','events':[]})


def test_bad_decision_comparison_is_failed_not_exception_or_pass(tmp_path):
    r = execute(tmp_path,[event()],reference={'source':'independent','events':[{'event_id':'1','regions':['dilepton']}]})
    assert r['status'] == 'failed'
    assert r['reference_comparison']['mismatches'] == ['1']


def test_absent_objects_are_not_zero_mass_candidates(tmp_path):
    s = selection(); s['regions'] = [{'name':'low_mass','cuts':[{'var':'mll','op':'<','val':10}]}]
    r = execute(tmp_path,[event()],s)
    assert r['raw_selected']['low_mass'] == 0
    assert json.loads((tmp_path/'output/decisions.json').read_text())[0]['variables']['mll'] is None


def test_flag_alias_and_undeclared_bits_refused():
    c = contract(); c['flags']['jet']['b85']=4
    with pytest.raises(ValueError,match='distinct'):
        object_contract(c)
    s = selection(); s['objects']['electron']['id']=16
    with pytest.raises(ValueError,match='undeclared'):
        selection_spec(s,contract())


def test_bjet_cut_requires_detector_working_point():
    s = selection(); s['regions'][0]['cuts']=[{'var':'nBjet','op':'==','val':0}]
    with pytest.raises(ValueError,match='b-tag definition'):
        selection_spec(s,contract())


def workspace():
    return {'version':'1.0.0','channels':[{'name':n,'samples':[
        {'name':'signal','data':[1.],'modifiers':[{'name':'mu','type':'normfactor','data':None}]},
        {'name':'background','data':[10.],'modifiers':[]}]} for n in ('SR','CR')],
        'observations':[{'name':n,'data':[10]} for n in ('SR','CR')],
        'measurements':[{'name':'fit','config':{'poi':'mu','parameters':[]}}]}


def mapping():
    return {'workspace':'workspace.json','poi':'mu','weight_name':'nominal',
            'normalization':{'kind':'events_per_input_weight','factor':2.,'source':'explicit synthetic conversion'},
            'channels':[{'channel':'SR','sample':'signal','regions':['dilepton'],'role':'signal'},
                        {'channel':'CR','sample':'signal','regions':['zero_lepton'],'role':'control'}],
            'omitted_regions':{},'mc_modifier':'signal_mc'}


def mapped(tmp_path, mutate=None):
    pytest.importorskip('pyhf')
    r = execute(tmp_path,[event('1',[obj(),obj(phi=math.pi)]),event('2')])
    (tmp_path/'workspace.json').write_text(json.dumps(workspace()))
    m = mapping()
    if mutate: mutate(m,r)
    return apply_mapping(m,r,tmp_path,tmp_path/'mapped')


def test_mapping_keeps_control_signal_and_mc(tmp_path):
    r = mapped(tmp_path)
    ws = json.loads((tmp_path/'mapped/mapped-workspace.json').read_text())
    assert [c['samples'][0]['data'] for c in ws['channels']] == [[2.],[2.]]
    assert r['inference_ready'] is True
    assert ws['channels'][1]['samples'][0]['modifiers'][-1]['data'] == [2.]


@pytest.mark.parametrize('mutate, message', [
    (lambda m,r: m['channels'].pop(), 'every POI'),
    (lambda m,r: r['region_overlap_counts']['dilepton'].update(zero_lepton=1), 'overlapping'),
    (lambda m,r: r['covariance']['nominal'][0].__setitem__(1,-.2), 'correlated event groups'),
    (lambda m,r: r['yields']['nominal'].__setitem__(0,-1), 'cannot be clipped'),
    (lambda m,r: r['yields']['nominal'].__setitem__(0,0), 'signed-weight cancellation'),
])
def test_mapping_dangerous_models_refused(tmp_path, mutate, message):
    with pytest.raises(ValueError,match=message):
        mapped(tmp_path,mutate)
@pytest.mark.parametrize('defect',['entries','sumw2','missing','variation'])
def test_signed_event_cancellation_does_not_hide_lost_exposure(defect):
    from ravel.physics.existing_events import reconcile_exposure
    exposure={'weight_names':['nominal','scale'], 'independent_groups':3,
              'sumw':[1,2], 'group_weight_second_moments':[[9,18],[18,36]]}
    counters={'/RAW/_EVTCOUNT':{'entries':3,'sumw':1,'sumw2':9},
              '/RAW/_EVTCOUNT[scale]':{'entries':3,'sumw':2,'sumw2':36}}
    reconcile_exposure(counters,exposure)
    if defect in ('entries','sumw2'): counters['/RAW/_EVTCOUNT'][defect]=1
    elif defect=='missing': counters['/SOME_ANALYSIS/_EVTCOUNT']=counters.pop('/RAW/_EVTCOUNT')
    else: counters['/RAW/_EVTCOUNT[scale]']['sumw2']=4
    with pytest.raises(ValueError): reconcile_exposure(counters,exposure)
