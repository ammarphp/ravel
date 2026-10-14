"""Portable native-source emission controls; no particles/decays computed."""
from copy import deepcopy
import hashlib
import pytest
from ravel.physics import rivet_particle_component as p, rivet_event_components as event, rivet_components as jets

def recipe(access='projection',stops=None):
 return dict(schema_version=1,kind='native-rivet-particle-components',nodes=[
  dict(id='mothers',kind='unstable',projection_name='MOTHERS',output=None,cuts=[],pids=dict(matching='absolute',values=[511,531])),
  dict(id='decays',kind='decayed_particles',projection_name='DECAYS',output=None if access is None else dict(id='products',access=access),input='mothers',stable_pids=[3122,-3122]if stops is None else stops,record_scope='native_generator_record')])

def test_signed_stop_order_native_constructor_and_lazy_access():
 c=p.compile_component(recipe(None));s=c['init']
 assert 'DecayedParticles decays(mothers);\ndecays.addStable(3122);\ndecays.addStable(-3122);\ndeclare(decays, "DECAYS");'in s
 assert c['analyze']=='' and c['headers'].count('Rivet/Projections/DecayedParticles.hh')==1
 assert c['nodes'][1]['stable_stop_pids']==[3122,-3122]
 assert c['nodes'][1]['native_base']=='Projection_not_ParticleFinder_or_FinalState'
 assert not c['native_executed'] and not c['physics_validated']
 assert 'branching_fraction' in c['nodes'][1]['applicability']
 assert any('aligned_tables'in x for x in c['remaining_obligations'])

@pytest.mark.parametrize('access,typ,method', [('projection','DecayedParticles',''),('decaying','Particles','.decaying()'),('n_stable','std::vector<unsigned int>','.nStable()'),('decay_products','std::vector<std::map<PdgId, Particles>>','.decayProducts()')])
def test_complete_const_native_table_access(access,typ,method):
 c=p.compile_component(recipe(access))
 assert c['analyze']==f'const {typ}& products = apply<DecayedParticles>(event, "DECAYS"){method};'
 assert c['nodes'][1]['sorting']=='native_parent_pT_order_after_mother_gate_alignment_preserved'

@pytest.mark.parametrize('access',['particles','particles_by_pt','raw_particles','tops','modeMatches','first',0,None,False])
def test_no_table_relabel_or_unchecked_singleton(access):
 r=recipe();r['nodes'][1]['output']['access']=access
 with pytest.raises(ValueError):p.compile_component(r)

@pytest.mark.parametrize('stops',[[],[443],[-443],[443,-443],[-2147483648,2147483647]])
def test_literal_signed_rosters_are_not_auto_conjugated(stops):
 c=p.compile_component(recipe(stops=stops))
 assert c['init'].count('.addStable(')==len(stops)
 for value in stops:assert f'decays.addStable({value});'in c['init']

@pytest.mark.parametrize('stops',[None,False,{},'443',[True],[0],[1.0],[443,443],[2147483648],[-2147483649],list(range(1,130))])
def test_bounded_exact_native_pid_roster_refuses_ambiguity(stops):
 r=recipe();r['nodes'][1]['stable_pids']=stops
 with pytest.raises(ValueError):p.compile_component(r)

@pytest.mark.parametrize('parent',['unknown','decays',False,None])
def test_forward_self_unknown_input_refused(parent):
 r=recipe();r['nodes'][1]['input']=parent
 with pytest.raises(ValueError):p.compile_component(r)

def test_decay_tables_cannot_feed_particlefinder_or_raw_veto():
 r=recipe();third=deepcopy(r['nodes'][1]);third.update(id='again',projection_name='AGAIN',output=None,input='decays');r['nodes'].append(third)
 with pytest.raises(ValueError,match='ParticleFinder'):p.compile_component(r)
 r=recipe();r['nodes'].insert(0,dict(id='fs',kind='stable',projection_name=None,output=None,cuts=[],pids=None));r['nodes'].append(dict(id='clean',kind='vetoed',projection_name=None,output=None,input='fs',veto_projections=['decays'],veto_pids=None))
 with pytest.raises(ValueError,match='ParticleFinder'):p.compile_component(r)
 r['nodes'][-1]['veto_projections']=['mothers'];assert 'clean.vetoFinalState(mothers);'in p.compile_component(r)['init']

@pytest.mark.parametrize('parent_kind',['primary_particles','alice_primary_particles'])
def test_native_particlefinder_parent_need_not_be_finalstate(parent_kind):
 r=recipe();r['nodes'][0]=dict(id='mothers',kind=parent_kind,projection_name=None,output=None,cuts=[],record_scope='native_generator_record',**({'pids':[511,531]}if parent_kind=='primary_particles'else{}))
 assert 'DecayedParticles decays(mothers);'in p.compile_component(r)['init']
 assert p.is_particle_finder(parent_kind) and not p.is_final_state(parent_kind)

def jet_recipe():
 return dict(schema_version=1,kind='native-rivet-components',particles=recipe(),jets=dict(schema_version=1,kind='native-rivet-jet-components',components=[dict(id='jet',projection_name='JETS',input=dict(kind='projection',id='decays'),clustering=dict(algorithm='antikt',radius=.4,recombination='E_scheme',muons='none',invisibles='none',area=None,grooming=None),jet_cuts=[],output=None)]))

def test_connected_fastjets_cannot_consume_plain_projection():
 with pytest.raises(ValueError,match='FinalState'):jets.compile_component(jet_recipe())

def test_connected_met_cannot_consume_plain_projection():
 r=dict(schema_version=1,kind='native-rivet-event-components',particles=recipe(),dileptons=[],jets=[],missing_momentum=[dict(id='met',projection_name='MET',input='decays',outputs=[dict(id='out',quantity='missing_pt',unit='GeV')])])
 with pytest.raises(ValueError,match='FinalState'):event.compile_component(r)

@pytest.mark.parametrize('field,value',[('record_scope','detector_reconstructed'),('projection_name',None),('id','DecayedParticles')])
def test_declaration_and_scope_closed(field,value):
 r=recipe();r['nodes'][1][field]=value
 with pytest.raises(ValueError):p.compile_component(r)

def test_whole_template_body_and_digest_preserved():
 raw=b'// RAVEL_PARTICLE_HEADERS\nvoid init(){\n // RAVEL_PARTICLE_INIT\n}\nvoid analyze(){\n // RAVEL_PARTICLE_ANALYZE\n // original modeMatches and histograms\n}\nvoid finalize(){ /* original signed counter normalization */ }\n'
 c=p.instantiate(raw,expected_sha256=hashlib.sha256(raw).hexdigest(),recipe=recipe())
 assert c['source'].endswith(b'void finalize(){ /* original signed counter normalization */ }\n')
 assert b'// original modeMatches and histograms'in c['source']
 with pytest.raises(ValueError):p.instantiate(raw,expected_sha256='0'*64,recipe=recipe())
