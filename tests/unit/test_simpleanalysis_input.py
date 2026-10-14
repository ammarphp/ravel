"""Prospective native-width structural input controls; no ROOT/native execution."""
import copy
import struct

import pytest

from ravel.physics.simpleanalysis_input import PREFIXES,prepare_writer,structural_events
from ravel.physics.simpleanalysis_adapter import native_slim_schema


def event(eid=1,weight=1):
    scalars={name:0 for name,kind in native_slim_schema().items() if 'vector' not in kind}
    scalars.update(Event=eid,sumet=200.1,met_pt=100.1,met_phi=.123)
    return {'scalars':scalars,'weight':weight,'objects':{name:[] for name in PREFIXES}}


def test_native_widths_are_fixed_before_approval_and_all_empty_collections_explicit(tmp_path):
    supplied=[event(1,2.1),event(2,-1)];original=copy.deepcopy(supplied)
    rows=structural_events(supplied)
    assert supplied==original
    assert len(rows[0])==82
    assert rows[0]['met_pt']==struct.unpack('<f',struct.pack('<f',100.1))[0]
    assert rows[1]['mcWeights']==[-1.] and rows[0]['el_id']==[]
    result=prepare_writer(supplied,tmp_path/'input')
    assert result['events']==2 and result['branches']==82 and result['native_execution'] is False
    with pytest.raises(ValueError,match='preserve'):
        prepare_writer(supplied,tmp_path/'input')


@pytest.mark.parametrize('defect',['event_float','event_overflow','zero_weight','underflow_weight','negative_sumw','missing_collection','missing_scalar','incomplete_object','nonfinite','negative_pt'])
def test_wrong_or_lossy_native_input_is_refused_before_root_job(defect):
    value=event()
    if defect=='event_float':value['scalars']['Event']=1.
    elif defect=='event_overflow':value['scalars']['Event']=2**31
    elif defect=='zero_weight':value['weight']=0
    elif defect=='underflow_weight':value['weight']=1e-100
    elif defect=='negative_sumw':value['weight']=-1
    elif defect=='missing_collection':value['objects'].pop('HSTruth')
    elif defect=='missing_scalar':value['scalars'].pop('genHT')
    elif defect=='incomplete_object':value['objects']['mu']=[{'pt':100}]
    elif defect=='nonfinite':value['scalars']['met_phi']=float('nan')
    elif defect=='negative_pt':value['scalars']['met_pt']=-1
    with pytest.raises(ValueError):structural_events([value])


def test_source_object_bits_and_mass_groups_are_native_ints_and_aligned():
    value=event()
    value['objects']['tau']=[{'pt':50,'eta':.3,'phi':-.2,'charge':-1,'id':65537,'motherID':15}]
    value['objects']['jet']=[{'pt':30,'eta':.2,'phi':1,'charge':0,'id':32,'motherID':5,'m':5}]
    rows=structural_events([value])
    assert rows[0]['tau_id']==[65537] and rows[0]['jet_m']==[5.]
    value['objects']['tau'][0]['id']=65537.
    with pytest.raises(ValueError,match='signed32bit'):structural_events([value])


def test_explicit_named_weight_vectors_keep_native_widths_and_original_order(tmp_path):
    values=[event(1),event(2)]
    for value,weights in zip(values,([2.1,3.2],[-.5,-.75])):
        value.pop('weight');value['weights']=weights
    names=['nominal','muR=0.5 muF=1.0']
    rows=structural_events(values,weight_names=names)
    assert rows[0]['mcWeights']==[struct.unpack('<f',struct.pack('<f',x))[0] for x in (2.1,3.2)]
    result=prepare_writer(values,tmp_path/'named',weight_names=names)
    import json
    assert json.loads((tmp_path/'named/events.json').read_text())['weight_names']==names
    assert result['events']==2
    with pytest.raises(ValueError):structural_events(values)


@pytest.mark.parametrize('defect',['duplicate_name','missing_weight','zero_variation','negative_variation_sum','huge_integer'])
def test_complete_named_weight_declaration_and_storage_are_required(defect):
    value=event();value.pop('weight');value['weights']=[1.,2.];names=['nominal','variation']
    if defect=='duplicate_name':names=['nominal','nominal']
    elif defect=='missing_weight':value['weights']=[1.]
    elif defect=='zero_variation':value['weights'][1]=1e-100
    elif defect=='negative_variation_sum':value['weights'][1]=-1.
    else:value['weights'][1]=10**1000
    with pytest.raises(ValueError):structural_events([value],weight_names=names)
