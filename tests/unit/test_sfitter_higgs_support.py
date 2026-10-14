"""Supplied source support preserves holds and ledgers without a card roster."""
from copy import deepcopy
import math
import pytest
from ravel.physics import sfitter_higgs_support as support
from source_record_fixtures import defect_registry,reviewed,write


def card():
    return {'observations':[{'ID':'ANA-0001','name':'fictional response','data':[1.]}],
            'predictions':[{'ID':'ANA-0001','name':'fictional response','data':[2.]}]}


@pytest.mark.parametrize('variant',[False,True])
def test_saved_ledger_cannot_drop_assumptions_registry_or_holds(tmp_path,variant):
    c=card();binding=defect_registry(tmp_path,c,assumptions=[{'law':'supplied source law','qualified':False}])
    result=support.require_supported(tmp_path,c,binding)
    contract={'profile':'higgs',**result}
    expected=support.contract_metadata(contract)
    support.verify_saved(expected,expected,contract)
    changed=deepcopy(expected)
    if variant:changed['native_law_assumptions']=[]
    else:changed['scientific_input_support']['reviewed_registry']['sha256']='0'*64
    with pytest.raises(ValueError,match='source assumptions'):support.verify_saved(changed,expected,contract)


def test_exact_numeric_spelling_does_not_clear_a_physical_hold():
    assert support._physical_record({'data':[0,1]})==support._physical_record({'data':[0.,1.]})
    assert support._physical_record({'ID':'ANA-0001','name':'one','data':[1.]})==support._physical_record({'ID':'ANA-0002','name':'two','data':[1.]})
    assert support._physical_record({'data':[1.]})!=support._physical_record({'data':[True]})
    assert support._physical_record({'data':[.1]})!=support._physical_record({'data':[math.nextafter(.1,math.inf)]})


@pytest.mark.parametrize('mutation',['unreviewed','changed_source','missing_evidence','unknown_card'])
def test_unreviewed_or_unbound_registry_never_admits_an_input(tmp_path,mutation):
    c=card();binding=defect_registry(tmp_path,c);import json
    value=json.loads(__import__('pathlib').Path(binding['path']).read_text())
    if mutation=='unreviewed':value['review']['status']='proposed'
    elif mutation=='changed_source':__import__('pathlib').Path(value['sources']['card']['path']).write_text('{}')
    elif mutation=='missing_evidence':value['review']['evidence']=[]
    else:c['predictions'][0]['data']=[3.]
    binding=write(tmp_path/'defects.json',value)
    with pytest.raises(ValueError):support.require_supported(tmp_path,c,binding)
