"""Root-executable actual-failure regressions; no numerical upstream execution."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from sfitter_complete_fixture import source, card, workflow_request, pin
import sfitter_card_repair_fixture as repairs
from ravel.physics import sfitter_profiles as profiles, sfitter_card_derivation as derivation, sfitter_higgs_support as support

@pytest.mark.parametrize('profile',['top','higgs'])
@pytest.mark.parametrize('initialization',['omitted','supplied','wrong_count'])
def test_actual_released_flow_optional_initialization_is_conditional(tmp_path,profile,initialization):
    import yaml
    root=source(tmp_path);basis=profiles.basis(root,profile);selected=[basis[-1],basis[0]]
    cp,rp,params,document=card(tmp_path,root,profile,selected)
    source_text=(root/'sfitter/sfitter/fit/flow_fitter.py').read_text()
    assert 'self.prescale_params.get("mean_init")' in source_text
    assert 'self.prescale_params.get("std_init")' in source_text
    if initialization=='omitted':
        params['prescale'].pop('mean_init',None);params['prescale'].pop('std_init',None)
    else:
        params['prescale']['mean_init']=[0.,0.]
        params['prescale']['std_init']=[1.,1.] if initialization=='supplied' else [1.]
    rp.write_text(yaml.safe_dump(params))
    if initialization=='wrong_count':
        with pytest.raises(ValueError,match='coordinate'):profiles.compile_card(root,cp,rp,profile,selected,'flow')
    else:
        result=profiles.compile_card(root,cp,rp,profile,selected,'flow')
        assert result['params']==params and result['selection']['indices']==[len(basis)-1,0]

@pytest.mark.parametrize('profile',['top','higgs'])
def test_actual_craft_inherited_annealing_population_keeps_source_settings(tmp_path,profile):
    root=source(tmp_path);basis=profiles.basis(root,profile);selected=[basis[-1],basis[0]]
    cp,rp,params,document=card(tmp_path,root,profile,selected,'craft')
    before=copy.deepcopy(params)
    result=profiles.compile_card(root,cp,rp,profile,selected,'craft')
    assert params==before==result['params']
    assert params['smc']['annealing_steps']==1 and params['smc']['annealing_beta']==.1
    source_text=(root/'sfitter/sfitter/fit/smc_fitter.py').read_text()
    assert 'self.marginal_params = {**self.smc_params, **self.params.get("marginalize", {})}' in source_text
    assert 'self.prescale_params = {**self.marginal_params, **self.params.get("prescale", {})}' in source_text


def test_actual_top_complete_experiment_identity_selects_atlas_and_preserves_cms(tmp_path):
    root=source(tmp_path);raw=json.loads((root/'sfitter/data/Top_Full.json').read_bytes())
    predecessor=json.loads((root/'sfitter/data/TopLikelihood_22WC.json').read_bytes())
    candidates=[(i,r) for i,r in enumerate(predecessor['observations']) if r['ID']=='2300211_0' and r['name']=='SingleT_whel_FL_7']
    assert [(i,r['data']) for i,r in candidates]==[(1,[.32]),(7,[.31])]
    # The package holds no repair record: without a supplied byte-bound manifest it refuses.
    with pytest.raises(derivation.records.SourceRecordError) as missing:derivation.derive(root,repairs.TOP)
    assert missing.value.reason=='missing_repair_manifest'
    binding,manifest=repairs.top_manifest(tmp_path,root)
    # The supplied record selects the earlier row with the same experimental modifiers, never ID or data alone.
    matched=[i for i,r in candidates if repairs.experimental(r['modifiers'])==repairs.experimental(raw['observations'][1]['Meas']['modifiers'])]
    assert matched==[1]
    value,lineage=derivation.derive(root,repairs.TOP,binding)
    assert lineage['repair_manifest']==binding and lineage['review']==manifest['review']
    repair=next(r for r in lineage['changes'] if r['path']=='/observations/1/Meas/data')
    assert repair['operation']=='copy' and repair['source']=='earlier' and repair['source_path']=='/observations/1/data'
    assert repair['before']==[32.9] and repair['after']==[.32]
    assert pin(root/'sfitter/data/TopLikelihood_22WC.json') in lineage['inputs']
    assert value['observations'][1]['Meas']['data']==[.32]
    assert value['observations'][1]['name']==value['predictions'][1]['name']=='SingleT_whel_FL_7'
    assert lineage['rows'][1]['corrected_ID']=='2300211_0' and lineage['rows'][1]['original_indices']==[1]
    assert value['observations'][1]['Meas']['modifiers']==raw['observations'][1]['Meas']['modifiers']
    # CMS remains an independently preserved original row, including every uncertainty.
    preserved=copy.deepcopy(value['observations'][7]);preserved['ID']=raw['observations'][7]['ID']
    assert preserved==raw['observations'][7]
    assert len(value['observations'])==52 and sum(len(o['Meas']['data']) for o in value['observations'])==110

@pytest.mark.parametrize('profile',['top','higgs'])
def test_actual_workflow_semantic_purpose_recaptures_positive_fixture(tmp_path,profile):
    root=source(tmp_path);request,config=workflow_request(tmp_path,root,profile)
    current=pin(Path(config['semantic_manifest']['path']))
    assert config['semantic_manifest']==current
    semantic=json.loads(Path(current['path']).read_bytes())
    assert semantic['purpose']=='supplied_full_study'
    handoff=json.loads(Path(request['handoffs']['conventions']['path']).read_bytes())
    assert handoff['payload']['semantic_manifest']==current

@pytest.mark.parametrize('name',['Higgs_Full.json','Higgs_Full_with_CtG.json'])
def test_unresolved_original_higgs_prediction_cannot_be_relabelled_as_physics(tmp_path,name):
    root=source(tmp_path);path=root/'sfitter/data'/name;original=path.read_bytes();document=json.loads(original)
    row=document['observations'][197];prediction=document['predictions'][197]
    assert row['ID']==prediction['ID']=='5019'
    assert row['name']=='MuATLAS13tthLep1l2tau'
    assert prediction['name']=='MuATLAS13tthLep2lOS1tau'
    assert row['Meas']['data']==[-.6]
    assert document['observations'][196]['Meas']['data']==[1.7]
    # The hold comes from the supplied reviewed defect registry; the package holds no card roster.
    binding,registry=repairs.held_manifest(tmp_path,root,name,197)
    with pytest.raises(support.HiggsInputSupportError,
                       match=r'^input held by reviewed source defect registry$') as error:
        derivation.derive(root,repairs.CARDS+'/'+name,binding)
    assert error.value.reason=='unresolved_source_defect' and error.value.details==error.value.support
    evidence=error.value.support
    assert len(evidence['scientific_input_holds'])==1
    hold=evidence['scientific_input_holds'][0]
    assert hold['id']==repairs.HOLD_ID
    assert hold['source']=='card'
    assert hold['input_observation_index']==197
    assert hold['observation_pointer']=='/observations/197' and hold['prediction_pointer']=='/predictions/197'
    assert hold['retained_input_observation']['ID']=='5019'
    assert hold['retained_input_observation']['name']==row['name']
    assert hold['retained_input_prediction']['name']==prediction['name']
    assert hold['retained_input_observation']==row
    assert hold['retained_input_prediction']==prediction
    assert hold['resolution_required']
    assert hold['intended_physical_response'] is None
    assert {'path':str(path),'sha256':hashlib.sha256(original).hexdigest()} in hold['source_bindings']
    assert registry in hold['source_bindings']
    status=evidence['scientific_input_support']
    assert status['input_disposition']=='held_source_defect'
    assert status['physics_validated'] is False
    assert status['reviewed_registry']==registry
    assert status['input_fingerprint']==support.fingerprint(document)
    # A relabelled copy of the held pair keeps the hold: identity text is not the physical record.
    relabelled=copy.deepcopy(document)
    for field in ('observations','predictions'):relabelled[field][197].update(ID='ANA-0001',name='fictional response')
    with pytest.raises(support.HiggsInputSupportError) as again:support.require_supported(root,relabelled,registry)
    located=again.value.support['scientific_input_holds']
    assert [h['input_observation_index'] for h in located]==[197]
    assert located[0]['retained_input_observation']==relabelled['observations'][197]
    assert located[0]['retained_input_prediction']==relabelled['predictions'][197]
    assert path.read_bytes()==original
