"""Reviewed unused nuisance placements require complete physical input and evaluator evidence."""
from copy import deepcopy
import pytest
from ravel.physics import sfitter_inputs as inputs,sfitter_profiles
from source_record_fixtures import defect_registry,pin


def selected(tmp,monkeypatch,variant=False):
    root=tmp/'source';path=root/'sfitter/sfitter/likelihood/datacard.py';path.parent.mkdir(parents=True)
    path.write_text('def higgs_names():\n    names = ["csgf", "cstth", "csvbf", "cswh", "cszh"]\n    return names\n')
    monkeypatch.setattr(sfitter_profiles,'basis',lambda root,profile:['a','b'])
    modifier={'name':'unused','type':'theo','data':[.4]}
    o={'ID':'ANA-0002' if variant else 'ANA-0001','name':'fictional observation','Meas':{'data':[2.],
        'modifiers':[{'name':'pois','type':'pois','data':[0.]},{'name':'stat','type':'stat','data':[1.]},modifier]},
        'Bkg':{'data':[0.],'modifiers':[]},'modifiers':[]}
    card={'observations':[o],'predictions':[{'ID':o['ID'],'name':o['name'],'data':[2.],
          'modifiers':[{'name':'a','data':[0.]}]}]}
    placement={'path':'/observations/0/Meas/modifiers/2','expected':deepcopy(modifier),
        'native_disposition':'retained_unused','evidence':['evaluator']}
    binding=defect_registry(tmp,card,sources={'evaluator':pin(path)},support={'nuisance_placements':[placement]})
    return root,card,binding,placement


@pytest.mark.parametrize('variant',[False,True])
def test_unused_nuisance_is_retained_only_by_selected_exact_review(tmp_path,monkeypatch,variant):
    root,card,binding,placement=selected(tmp_path,monkeypatch,variant)
    before=deepcopy(card)
    census=inputs.inspect_profile_datacard(card,root,'top',source_review=binding)
    assert census['source_card_quirks']==[placement]
    assert any('unused' in key for key in census['native_nuisance_keys'])
    assert card==before and census['observations']==1
    with pytest.raises(ValueError) as error:
        inputs.inspect_profile_datacard(card,root,'top')
    assert error.value.reason=='missing_defect_registry'


@pytest.mark.parametrize('mutation',['value','type','placement','population','boolean','evaluator'])
def test_exact_input_or_evaluator_drift_refuses_nuisance_exception(tmp_path,monkeypatch,mutation):
    root,card,binding,_=selected(tmp_path,monkeypatch)
    if mutation=='value':card['observations'][0]['Meas']['modifiers'][2]['data']=[.5]
    elif mutation=='type':card['observations'][0]['Meas']['modifiers'][2]['type']='syst'
    elif mutation=='placement':card['observations'][0]['Meas']['modifiers'].reverse()
    elif mutation=='population':card['observations'][0]['Meas']['data']=[2.,3.]
    elif mutation=='boolean':card['observations'][0]['Meas']['modifiers'][2]['data']=[True]
    else:(root/'sfitter/sfitter/likelihood/datacard.py').write_text('changed law')
    with pytest.raises(ValueError):inputs.inspect_profile_datacard(card,root,'top',source_review=binding)
