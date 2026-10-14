"""Synthetic complete-production geometry and explicit supplied source scaling."""
from copy import deepcopy
import pytest
from ravel.physics import sfitter_inputs as inputs,sfitter_profiles
from source_record_fixtures import defect_registry,pin


def selected(tmp,monkeypatch):
    root=tmp/'source';path=root/'sfitter/sfitter/likelihood/datacard.py';path.parent.mkdir(parents=True)
    names=[prefix+suffix for prefix in ('cs','csTEV') for suffix in ('gf','tth','vbf','wh','zh')]
    path.write_text('def higgs_names():\n    names = '+repr(names)+'\n    return names\n')
    monkeypatch.setattr(sfitter_profiles,'basis',lambda root,profile:['a','b'])
    o={'ID':'ANA-0001','name':'fictional scalar mixture','Meas':{'data':[1.],
        'modifiers':[{'name':'pois','type':'pois','data':[0.]},{'name':'stat','type':'stat','data':[.1]}]},
        'Bkg':{'data':[0.],'modifiers':[]},'modifiers':[],'Decay':['brw','brtau'],'Luminosity':[1.]}
    card={'observations':[o],'predictions':[{'ID':o['ID'],'name':o['name'],'data':[0.],
        'modifiers':[{'name':'cs'+suffix,'type':'Higgs','data':[.25,.75] if suffix=='gf' else [0.,0.]} for suffix in ('gf','tth','vbf','wh','zh')]}]}
    weights=dict.fromkeys(names,2.);weights['csTEVtth']=0.
    return root,path,card,weights


@pytest.mark.parametrize('scenario,accepted',[('one',True),('zero_only',False),('two',False),('partial',False)])
def test_activity_uses_supplied_scaling_and_complete_block_geometry(tmp_path,monkeypatch,scenario,accepted):
    root,path,card,weights=selected(tmp_path,monkeypatch)
    mods=card['predictions'][0]['modifiers']
    if scenario=='zero_only':
        for m in mods:m['name']=m['name'].replace('cs','csTEV');m['data']=[1.,0.] if m['name'].endswith('tth') else [0.,0.]
    elif scenario=='two':mods.extend({'name':'csTEV'+s,'type':'Higgs','data':[1.,0.] if s=='gf' else [0.,0.]} for s in ('gf','tth','vbf','wh','zh'))
    elif scenario=='partial':mods.pop()
    binding=defect_registry(tmp_path,card,sources={'evaluator':pin(path)},support={'native_production_scaling':{'weights':weights}})
    if accepted:
        result=inputs.inspect_profile_datacard(card,root,'higgs',source_review=binding)
        assert len(result['population'][0]['prediction_terms'])==5 and result['scientific_input_holds']==[]
    else:
        with pytest.raises(ValueError,match='one active complete'):
            inputs.inspect_profile_datacard(card,root,'higgs',source_review=binding)


def test_changed_prediction_requires_a_new_supplied_review(tmp_path,monkeypatch):
    root,path,card,weights=selected(tmp_path,monkeypatch)
    binding=defect_registry(tmp_path,card,sources={'evaluator':pin(path)},support={'native_production_scaling':{'weights':weights}})
    card['predictions'][0]['modifiers'][0]['data']=[.5,.5]
    with pytest.raises(ValueError) as error:inputs.inspect_profile_datacard(card,root,'higgs',source_review=binding)
    assert error.value.reason=='missing_input_review'
