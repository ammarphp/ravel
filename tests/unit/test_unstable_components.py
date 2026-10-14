"""Portable source construction controls. No native interpretation is simulated."""
from copy import deepcopy
import hashlib
import pytest
from ravel.physics import rivet_particle_component as m, rivet_components as connected

def recipe(output=None):
    return {'schema_version':1,'kind':'native-rivet-particle-components','nodes':[{'id':'physical_hadrons','kind':'unstable','cuts':[{'field':'abs_rapidity','relation':'lt','value':.96,'unit':'1'}],'pids':None,'projection_name':'UFS','output':output}]}

def test_native_projection_preserves_constructor_cut_even_lazy_access():
    r=recipe();out=m.compile_component(r)
    assert out['init']=='const UnstableParticles physical_hadrons((Cuts::absrap < 0.96));\ndeclare(physical_hadrons, "UFS");'
    assert out['analyze']=='' and r==recipe()
    sem=out['nodes'][0]
    assert sem['native_record_selection']['stable_status1_included_subject_to_parton_and_duplicate_filters']
    assert sem['native_record_selection']['duplicate_suppression']=='direct_child_same_signed_PDG_and_child_status2'
    assert sem['cut_phase']=='after_native_record_status_parton_and_same_signed_child_filter'
    assert not out['native_executed'] and not out['physics_validated']

@pytest.mark.parametrize('access,method',[('particles','particles'),('particles_by_pt','particlesByPt'),('raw_particles','rawParticles')])
def test_explicit_collection_access(access,method):
    out=m.compile_component(recipe({'id':'returned','access':access}))
    assert out['analyze']==f'const Particles returned = apply<UnstableParticles>(event, "UFS").{method}();'

@pytest.mark.parametrize('matching,values,field',[('signed',[443,20443,445],'pid'),('signed',[3122,-3122],'pid'),('absolute',[3122,421],'abspid')])
def test_native_cut_pid_identity_preserved(matching,values,field):
    r=recipe();r['nodes'][0]['cuts']=[];r['nodes'][0]['pids']={'matching':matching,'values':values};out=m.compile_component(r)
    assert ' || '.join(f'(Cuts::{field} == {p})' for p in values) in out['init']

@pytest.mark.parametrize('change',[
 lambda r:r['nodes'][0].update(statuses=[2]),
 lambda r:r['nodes'][0].update(decay_filter='first'),
 lambda r:r['nodes'][0].update(input='stable'),
 lambda r:r['nodes'][0].update(output={'id':'out','access':'dressed_leptons'}),
 lambda r:r['nodes'][0].update(id='UnstableParticles'),
 lambda r:r['nodes'][0].update(id='UnstableFinalState'),
 lambda r:r['nodes'][0]['cuts'][0].update(unit='GeV'),
 lambda r:r['nodes'][0].update(pids={'matching':'absolute','values':[-3122]}),
 lambda r:r['nodes'][0].update(output={'id':'physical_hadrons','access':'particles'}),
 lambda r:r['nodes'][0].update(projection_name=None,output={'id':'returned','access':'particles'}),
])
def test_unserved_status_ancestry_and_bad_identity_refuse(change):
    r=recipe();change(r)
    with pytest.raises(ValueError):m.compile_component(r)

def test_identification_and_raw_veto_compose_on_explicit_native_unstable_node():
    r=recipe();r['nodes'] += [
      {'id':'b_hadrons','kind':'identified','input':'physical_hadrons','pids':{'matching':'absolute','values':[511,521]},'projection_name':None,'output':None},
      {'id':'other_hadrons','kind':'vetoed','input':'physical_hadrons','veto_projections':['b_hadrons'],'veto_pids':None,'projection_name':'Other','output':{'id':'kept','access':'particles'}}]
    out=m.compile_component(r)
    assert 'IdentifiedFinalState b_hadrons(physical_hadrons);\nb_hadrons.acceptIdPairs({511, 521});' in out['init']
    assert 'other_hadrons.vetoFinalState(b_hadrons);' in out['init']
    assert out['recipe']['nodes'][0]['kind']=='unstable'
    assert not out['physics_validated']

def test_explicit_unstable_fastjets_input_is_not_replaced_by_stable():
    r={'schema_version':1,'kind':'native-rivet-components','particles':recipe(),
      'jets':{'schema_version':1,'kind':'native-rivet-jet-components','components':[{
       'id':'selected_hadron_jet','projection_name':'SelectedHadronJet','input':{'kind':'projection','id':'physical_hadrons'},
       'clustering':{'algorithm':'antikt','radius':.4,'recombination':'E_scheme','muons':'none','invisibles':'none','area':None,'grooming':None},'jet_cuts':[],'output':None}]}}
    out=connected.compile_component(r)
    assert 'selected_hadron_jet_finder(physical_hadrons,' in out['init'] and 'FinalState physical_hadrons' not in out['init']
    assert out['particle_semantics'][0]['native_class']=='UnstableParticles'
    assert out['links'][0]['input_projection']=='physical_hadrons' and not out['native_executed']

def test_all_source_slot_rest_is_byte_exact():
    original=b'// RAVEL_PARTICLE_HEADERS\r\ninit(){\r\n // RAVEL_PARTICLE_INIT\r\n}\r\nanalyze(){\r\n // RAVEL_PARTICLE_ANALYZE\r\n parent_children_weight_fill();\r\n}\r\nall_final_and_raw_objects();\r\n'
    out=m.instantiate(original,expected_sha256=hashlib.sha256(original).hexdigest(),recipe=recipe())
    assert b' parent_children_weight_fill();\r\n}\r\nall_final_and_raw_objects();\r\n' in out['source']
    assert out['source_sha256']==hashlib.sha256(out['source']).hexdigest()
    with pytest.raises(ValueError):m.instantiate(original,expected_sha256='0'*64,recipe=recipe())

def test_legacy_includes_do_not_gain_unstable_dependency():
    r=recipe();r['nodes'][0]['kind']='stable';out=m.compile_component(r)
    assert 'Rivet/Projections/UnstableParticles.hh' not in out['headers']
    assert out['nodes'][0]['cut_phase']=='stable_final_state_particles'
