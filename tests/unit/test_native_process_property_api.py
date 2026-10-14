"""Portable native property-contract controls; no upstream imports or execution.

The independently retained source-method suite separately verifies this getter
contract against the pinned MG5 release; these fixtures carry no physics model.
"""
from copy import deepcopy
import pytest
from ravel.physics import model_event_process as observer


class NativeProperties(dict):
    def __init__(self,values=None):
        super().__init__({'decay_chains':[]})
        self.update(values or {})
    def get(self,name):
        return self[name]


def process():
    return NativeProperties({'legs':[{'ids':[-11],'state':False,'polarization':[-1,1]},
                                     {'ids':[11],'state':False,'polarization':[]},
                                     {'ids':[6],'state':True,'polarization':[]},
                                     {'ids':[-6],'state':True,'polarization':[]}],
        'model':object(),'orders':{'QED':2},'overall_orders':{'QCD':2},
        'squared_orders':{'QED':4},'sqorders_types':{'QED':'<='},
        'constrained_orders':{'QCD':(2,'>')},'split_orders':['QED'],
        'required_s_channels':[[23]],'forbidden_onsh_s_channels':[25],
        'forbidden_s_channels':[22],'forbidden_particles':[5],
        'perturbation_couplings':[],'NLO_mode':'tree','is_decay_chain':False,
        'id':5,'uid':17,'has_born':True})


def test_complete_snapshot_native_getter_preserves_fields_and_original():
    obj=process();original=dict(obj);result=observer.snapshot(obj)
    assert set(result)==set(obj)-{'model'}
    assert result['constrained_orders']=={'QCD':[2,'>']}
    assert result['legs'][0]['polarization']==[-1,1]
    assert dict(obj)==original
    assert observer.identity(result)['required_s_channels']==[[23]]


def test_native_default_argument_witness_and_supported_one_key_read():
    obj=process()
    with pytest.raises(TypeError):obj.get('decay_chains',[])
    assert observer.snapshot(obj)['decay_chains']==[]


def test_missing_native_property_cannot_become_empty_observation():
    obj=process();del obj['decay_chains']
    with pytest.raises(KeyError):observer.snapshot(obj)


def test_native_nested_decays_retained_and_ordinary_intake_remains_refused():
    child=process();parent=process();parent['decay_chains']=[child]
    result=observer.snapshot(parent)
    assert result['decay_chains'][0]['uid']==17
    with pytest.raises(ValueError,match='decay-chain'):observer.identity(result)


def test_unsupported_native_field_refused_without_losing_valid_fields():
    obj=process();obj['bad_extra_field']=object()
    with pytest.raises(ValueError,match='unsupported'):observer.snapshot(obj)


def test_restriction_changes_are_observations_not_pass_labels():
    obj=process();snapshot=observer.snapshot(obj)
    changed=deepcopy(snapshot);changed['forbidden_s_channels']=[23]
    assert observer.identity(changed)!=observer.identity(snapshot)
    assert changed['orders']==snapshot['orders']
