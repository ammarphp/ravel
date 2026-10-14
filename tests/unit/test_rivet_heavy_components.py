"""Portable native source emission controls; no ancestry kernel/native execution."""
from copy import deepcopy
import hashlib
import json
import os
import subprocess
import urllib.request

import pytest
from ravel import analysis_sources
from ravel.physics import rivet_particle_component as p, rivet_components as connected, rivet_event_components as pipeline


def node(identity, kind, **kw):
    result=dict(id=identity,kind=kind,projection_name=None,output=None);result.update(kw);return result


def top(**kw):
    result=node('recordtops','partonic_tops',cuts=[],decay_mode='e_mu',emu_from_prompt_tau=False,
        include_hadronic_taus=False,which_top='last',record_scope='native_generator_record')
    result.update(kw);return result


def heavy(**kw):
    result=node('heavy','heavy_hadrons',cuts=[]);result.update(kw);return result


def recipe(*nodes):
    return dict(schema_version=1,kind='native-rivet-particle-components',nodes=list(nodes))


@pytest.fixture(autouse=True)
def pure(monkeypatch):
    def deny(*a,**kw):raise AssertionError('native/process/provider forbidden')
    monkeypatch.setattr(subprocess,'Popen',deny);monkeypatch.setattr(os,'system',deny);monkeypatch.setattr(urllib.request,'urlopen',deny)


@pytest.mark.parametrize('decay,enum',[('all','ALL'),('electron','ELECTRON'),('muon','MUON'),('tau','TAU'),('e_mu','E_MU'),('e_mu_tau','E_MU_TAU'),('hadronic','HADRONIC')])
def test_closed_top_decay_constructor(decay,enum):
    r=recipe(top(decay_mode=decay));before=deepcopy(r);c=p.compile_component(r)
    assert f'PartonicTops recordtops(TopDecay::{enum}, PromptEMuFromTau::NO, InclHadronicTau::NO, Cuts::OPEN, WhichTop::LAST);' in c['init']
    assert r==before and c['nodes'][0]['native_base']=='ParticleFinder_not_FinalState'
    assert not c['native_executed'] and not c['physics_validated']


@pytest.mark.parametrize('emu,had,which',[(True,False,'first'),(False,True,'last'),(True,True,'first'),(False,False,'last')])
def test_explicit_flags_cut_and_copy_order(emu,had,which):
    c=p.compile_component(recipe(top(emu_from_prompt_tau=emu,include_hadronic_taus=had,which_top=which,
        cuts=[dict(field='pt',relation='gt',value=100,unit='GeV')])))
    assert f'PromptEMuFromTau::{"YES"if emu else"NO"}, InclHadronicTau::{"YES"if had else"NO"}, (Cuts::pT > 100.0*GeV), WhichTop::{which.upper()}' in c['init']
    assert 'cut_before_first_last' in c['nodes'][0]['input_scope']
    assert 'photon_ancestor_exclusion' in c['nodes'][0]['decay_selection']


@pytest.mark.parametrize('access,method',[('tops','tops'),('particles','particles'),('particles_by_pt','particlesByPt'),('raw_particles','rawParticles')])
def test_top_safe_collections(access,method):
    c=p.compile_component(recipe(top(projection_name='Tops',output=dict(id='toplist',access=access))))
    assert f'const Particles toplist = apply<PartonicTops>(event, "Tops").{method}();' in c['analyze']


@pytest.mark.parametrize('access,method',[('b_hadrons','bHadrons'),('c_hadrons','cHadrons'),('particles','particles'),('particles_by_pt','particlesByPt')])
def test_heavy_parent_and_output_cuts_are_distinct(access,method):
    c=p.compile_component(recipe(heavy(cuts=[dict(field='abs_eta',relation='lt',value=3.2,unit='1')],
        projection_name='Hadrons',output=dict(id='selected',access=access,cuts=[dict(field='pt',relation='gt',value=5,unit='GeV')]))))
    assert 'HeavyHadrons heavy((Cuts::abseta < 3.2));' in c['init']
    assert f'.{method}((Cuts::pT > 5.0*GeV));' in c['analyze']
    assert c['nodes'][0]['flavor_partition']=='bottom_priority_charm_only_if_no_bottom_Bc_in_bottom_only'
    assert c['nodes'][0]['charm_from_bottom']=='not_ancestry_vetoed'
    assert 'direct_genParticle_children' in c['nodes'][0]['terminal_copy']


def test_raw_collection_has_no_native_cut_overload():
    n=heavy(projection_name='Hadrons',output=dict(id='raw',access='raw_particles',cuts=None))
    assert '.rawParticles();' in p.compile_component(recipe(n))['analyze']
    n['output']['cuts']=[]
    with pytest.raises(ValueError,match='no native Cut overload'):p.compile_component(recipe(n))


@pytest.mark.parametrize('fields',[dict(decay_mode='any_inferred'),dict(emu_from_prompt_tau=1),dict(include_hadronic_taus='false'),dict(which_top='stable'),dict(record_scope='fiducial_pseudotop'),dict(output=dict(id='one',access='top')),dict(id='TopDecay'),dict(id='WhichTop'),dict(id='HeavyHadrons')])
def test_ambiguity_and_type_shadow_refuse(fields):
    with pytest.raises(ValueError):p.compile_component(recipe(top(**fields)))


@pytest.mark.parametrize('dependent',[
    node('charged','charged',input='recordtops'),node('visible','visible',input='recordtops'),
    node('ids','identified',input='recordtops',pids=dict(matching='absolute',values=[6])),
    node('prompt','prompt',input='recordtops',tau_decays='prompt',muon_decays='prompt'),
    node('merged','merged',first='recordtops',second='recordtops'),
    node('vetoed','vetoed',input='recordtops',veto_projections=[],veto_pids=None)])
def test_top_cannot_be_a_final_state_operand(dependent):
    with pytest.raises(ValueError,match='FinalState'):p.compile_component(recipe(top(),dependent))


def test_top_is_a_valid_particlefinder_veto_operand():
    c=p.compile_component(recipe(top(),node('base','stable',cuts=[],pids=None),
        node('vetoed','vetoed',input='base',veto_projections=['recordtops'],veto_pids=None)))
    assert 'vetoed.vetoFinalState(recordtops);' in c['init']


def jet(parent):
    return dict(id='nativejet',projection_name='Jets',input=dict(kind='projection',id=parent),
        clustering=dict(algorithm='antikt',radius=.4,recombination='E_scheme',muons='all',invisibles='none',area=None,grooming=None),jet_cuts=[],output=None)


def test_connected_jets_preserve_native_base_types():
    task=dict(schema_version=1,kind='native-rivet-components',particles=recipe(top(),heavy()),
        jets=dict(schema_version=1,kind='native-rivet-jet-components',components=[jet('heavy')]))
    assert 'nativejet_finder(heavy,' in connected.compile_component(task)['init']
    task['jets']['components'][0]['input']['id']='recordtops'
    with pytest.raises(ValueError,match='FinalState'):connected.compile_component(task)


@pytest.mark.parametrize('stage',['jets','missing_momentum','dileptons'])
def test_complete_event_pipeline_rejects_top_final_state_inputs(stage):
    task=dict(schema_version=1,kind='native-rivet-event-components',particles=recipe(top(),heavy()),dileptons=[],jets=[],missing_momentum=[])
    if stage=='jets':task['jets']=[jet('recordtops')]
    elif stage=='missing_momentum':task[stage]=[dict(id='recoil',projection_name='MET',input='recordtops',outputs=[])]
    else:task[stage]=[dict(id='pairs',projection_name='Pairs',input=dict(kind='final_state',id='recordtops'),mass_target=dict(value=91,unit='GeV'),radius=.1,lepton_selection=dict(cuts=[],pids=None),pair_cuts=dict(kinematics=[],mass_window=None),dressing='cone',outputs=[],remaining=None)]
    with pytest.raises(ValueError,match='FinalState'):pipeline.compile_component(task)


def test_heavy_complete_event_route_and_no_native_outputs_claimed():
    task=dict(schema_version=1,kind='native-rivet-event-components',particles=recipe(top(),heavy()),dileptons=[],jets=[jet('heavy')],missing_momentum=[dict(id='recoil',projection_name='MET',input='heavy',outputs=[])])
    c=pipeline.compile_component(task)
    assert 'MissingMomentum recoil(heavy)' in c['init']
    assert not c['physics_validated'] and not c['native_executed']


def test_accessors_do_not_cross_flavor_or_projection_classes():
    for n in [top(projection_name='Top',output=dict(id='wrong',access='b_hadrons')),heavy(projection_name='Heavy',output=dict(id='wrong',access='tops',cuts=None))]:
        with pytest.raises(ValueError):p.compile_component(recipe(n))


def test_slots_preserve_whole_enclosing_weight_output_normalization(tmp_path):
    original=b'// RAVEL_PARTICLE_HEADERS\nvoid init(){\n// RAVEL_PARTICLE_INIT\nbook_all_original_named_weight_outputs();\n}\nvoid analyze(const Event& event){\n// RAVEL_PARTICLE_ANALYZE\noriginal_selection_weight_fill_all_flows();\n}\nvoid finalize(){original_cross_section_and_ratio_normalization();}\n'
    c=p.instantiate(original,expected_sha256=hashlib.sha256(original).hexdigest(),recipe=recipe(top(),heavy()))
    assert b'original_selection_weight_fill_all_flows();' in c['source'] and b'original_cross_section_and_ratio_normalization();' in c['source']
    assert c['source_capsule_dependency_review']=='incomplete_requires_fresh_native_admission'
    with pytest.raises(ValueError):p.instantiate(original,expected_sha256='0'*64,recipe=recipe(top()))
