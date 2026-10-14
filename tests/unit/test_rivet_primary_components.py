"""Portable native-source contracts; never evaluates physics on particles."""
from copy import deepcopy
import hashlib
import pytest
from ravel.physics import rivet_particle_component as p,rivet_components as connected,rivet_event_components as event

def primary(kind='primary_particles',**changes):
 n=dict(id='primaries',kind=kind,projection_name='PRIM',output=None,cuts=[],record_scope='native_generator_record')
 if kind=='primary_particles':n['pids']=[310,3122]
 n.update(changes);return n

def recipe(*nodes):return dict(schema_version=1,kind='native-rivet-particle-components',nodes=list(nodes))
def cut(field,relation,value,unit='1'):return dict(field=field,relation=relation,value=value,unit=unit)

def test_primary_literal_order_absolute_pid_not_finalstate():
 n=primary();before=deepcopy(n);c=p.compile_component(recipe(n));assert n==before
 assert 'const PrimaryParticles primaries({310, 3122}, Cuts::OPEN);'in c['init']
 assert c['nodes'][0]['ordered_pid_roster']==[310,3122]
 inverse=p.compile_component(recipe(primary(pids=[3122,310])))
 assert inverse['init']!=c['init'] and inverse['recipe_sha256']!=c['recipe_sha256']
 assert c['nodes'][0]['native_base']=='ParticleFinder_not_FinalState'
 assert not p.is_final_state('primary_particles')and not p.is_final_state('alice_primary_particles')
 assert not c['native_executed']and not c['physics_validated']

@pytest.mark.parametrize('values',[[-310],[True],[310.],[0],[310,310],list(range(1,130)),[2147483648],None,'310'])
def test_unrepresentable_negative_duplicate_unknown_pids_refuse(values):
 with pytest.raises(ValueError):p.compile_component(recipe(primary(pids=values)))

@pytest.mark.parametrize('values',[[],[2147483647],[211,321,310]])
def test_exact_empty_or_positive_native_int_roster(values):
 c=p.compile_component(recipe(primary(pids=values)));assert c['nodes'][0]['ordered_pid_roster']==values


def test_alice_specialization_is_not_manual_generic_pidlist():
 c=p.compile_component(recipe(primary('alice_primary_particles',cuts=[cut('signed_eta','native_range',dict(low=2,high=4.8)),cut('abs_charge','gt',0)])))
 assert 'const ALICE::PrimaryParticles primaries(Cuts::range(Cuts::eta, 2.0, 4.8) && (Cuts::abscharge > 0.0));'in c['init']
 assert 'Rivet/Projections/AliceCommon.hh'in c['headers']
 assert not any('ALICE::'in h for h in c['headers'])
 assert 'unchanged_native_ALICE_species_switch'in c['nodes'][0]['pid_selection']
 assert 'cache_registration_witness'in ' '.join(c['remaining_obligations'])
 with pytest.raises(ValueError):p.compile_component(recipe(primary('alice_primary_particles',pids=[211])))

@pytest.mark.parametrize('field,qty',[('signed_eta','eta'),('signed_rapidity','rap'),('charge','charge')])
def test_signed_predicates_preserve_negative_literals_and_native_quantity(field,qty):
 c=p.compile_component(recipe(primary(cuts=[cut(field,'gt',-2),cut(field,'lt',-1)])))
 assert f'(Cuts::{qty} > -2.0) && (Cuts::{qty} < -1.0)'in c['init']
 assert 'charge3'not in c['init']

@pytest.mark.parametrize('field',['pt','abs_eta','abs_rapidity','signed_eta','signed_rapidity','charge','abs_charge'])
def test_native_half_open_range_is_not_inclusive_or_rescaled(field):
 unit='GeV'if field=='pt'else'1';c=p.compile_component(recipe(primary(cuts=[cut(field,'native_range',dict(low=0,high=2),unit)])))
 qty=p.PARTICLE_FIELDS[field][0];assert 'Cuts::range(Cuts::'+qty+', 'in c['init']
 assert '>='not in c['init'] and '<='not in c['init']
 assert ('*GeV'in c['init'])==(field=='pt')

@pytest.mark.parametrize('bad',[
 cut('signed_eta','gt',True),cut('signed_eta','gt',float('nan')),cut('signed_eta','gt',float('inf')),
 cut('signed_eta','gt',2**53+1),cut('signed_eta','gt',10**400),cut('abs_charge','gt',-1),
 cut('signed_eta','native_range',dict(low=2,high=-2)),cut('signed_eta','native_range',dict(low=1,high=2,extra=True)),
 cut('signed_eta','native_range',[1,2]),cut('charge3','eq',3),cut('charge','eq',1,'GeV'),cut('eta','gt',1),
 cut('signed_rapidity','within',2)])
def test_bad_native_cut_requests_refuse(bad):
 with pytest.raises(ValueError):p.compile_component(recipe(primary(cuts=[bad])))


def test_empty_range_charge_equality_and_duplicate_predicate_contract():
 c=p.compile_component(recipe(primary(cuts=[cut('signed_eta','native_range',dict(low=-1,high=-1)),cut('charge','eq',1),cut('charge','ne',0)])))
 assert 'Cuts::range(Cuts::eta, -1.0, -1.0)'in c['init']
 assert '(Cuts::charge == 1.0)'in c['init'] and '(Cuts::charge != 0.0)'in c['init']
 with pytest.raises(ValueError):p.compile_component(recipe(primary(cuts=[cut('signed_eta','gt',-1)]*2)))

@pytest.mark.parametrize('kind',['primary_particles','alice_primary_particles'])
@pytest.mark.parametrize('consumer',['identified','charged','visible','prompt','dressed','merged'])
def test_particlefinder_is_not_implicitly_promoted_to_finalstate(kind,consumer):
 first=primary(kind)
 n=dict(id='badconsumer',kind=consumer,projection_name=None,output=None,input='primaries')
 if consumer=='identified':n['pids']=dict(matching='absolute',values=[11])
 if consumer=='prompt':n.update(tau_decays='prompt',muon_decays='nonprompt')
 if consumer=='dressed':n.pop('input');n.update(leptons='primaries',photons='primaries',radius=.1,dressing='cone',cuts=[])
 if consumer=='merged':n.pop('input');n.update(first='primaries',second='primaries')
 with pytest.raises(ValueError,match='FinalState'):p.compile_component(recipe(first,n))

@pytest.mark.parametrize('kind',['primary_particles','alice_primary_particles'])
def test_finalstate_veto_accepts_particlefinder_raw_identity(kind):
 stable=dict(id='allparts',kind='stable',cuts=[],pids=None,projection_name=None,output=None)
 veto=dict(id='rest',kind='vetoed',input='allparts',veto_projections=['primaries'],veto_pids=None,projection_name=None,output=None)
 c=p.compile_component(recipe(stable,primary(kind),veto));assert 'rest.vetoFinalState(primaries);'in c['init']

@pytest.mark.parametrize('access,method',[('particles','particles'),('particles_by_pt','particlesByPt'),('raw_particles','rawParticles')])
def test_compatible_native_collection_or_lazy_constructor_cuts(access,method):
 c=p.compile_component(recipe(primary(output=dict(id='selected',access=access),cuts=[cut('pt','gt',1e6,'GeV')])))
 assert f'apply<PrimaryParticles>(event, "PRIM").{method}();'in c['analyze']
 lazy=p.compile_component(recipe(primary(cuts=[cut('pt','gt',1e6,'GeV')])));assert 'Cuts::pT > 1000000.0*GeV'in lazy['init']and lazy['analyze']==''

@pytest.mark.parametrize('change',[dict(record_scope='detector_tracks'),dict(id='ALICE'),dict(id='PrimaryParticles'),dict(output=dict(id='selected',access='tops')),dict(input='allparts')])
def test_native_identity_scope_and_unadmitted_input_refuse(change):
 with pytest.raises(ValueError):p.compile_component(recipe(primary(**change)))


def test_signed_particle_cuts_do_not_expand_jet_cut_contract():
 # Jet cut schema remains deliberately separate; no inherited charged-jet filter.
 with pytest.raises(ValueError):p.jets._cuts([cut('charge','eq',1)])
 with pytest.raises(ValueError):p.jets._cuts([cut('signed_eta','gt',-2)])


def test_whole_template_and_known_sha_are_required():
 raw=b'// RAVEL_PARTICLE_HEADERS\nvoid init(){\n // RAVEL_PARTICLE_INIT\n}\nvoid analyze(){\n // RAVEL_PARTICLE_ANALYZE\n}\n// unchanged normalization\n'
 c=p.instantiate(raw,expected_sha256=hashlib.sha256(raw).hexdigest(),recipe=recipe(primary()))
 assert c['source'].endswith(b'// unchanged normalization\n')
 with pytest.raises(ValueError):p.instantiate(raw,expected_sha256='0'*64,recipe=recipe(primary()))

@pytest.mark.parametrize('kind',['primary_particles','alice_primary_particles'])
def test_connected_fastjets_refuses_particlefinder_input(kind):
 component=dict(id='myjet',projection_name='JETS',input=dict(kind='projection',id='primaries'),clustering=dict(algorithm='antikt',radius=.4,recombination='E_scheme',muons='none',invisibles='none',area=None,grooming=None),jet_cuts=[],output='found_jets')
 r=dict(schema_version=1,kind='native-rivet-components',particles=recipe(primary(kind)),jets=dict(schema_version=1,kind='native-rivet-jet-components',components=[component]))
 with pytest.raises(ValueError,match='FinalState'):connected.compile_component(r)

@pytest.mark.parametrize('kind',['primary_particles','alice_primary_particles'])
def test_connected_met_refuses_particlefinder_input(kind):
 met=dict(id='recoil',projection_name='MET',input='primaries',outputs=[dict(id='missing',quantity='missing_pt',unit='GeV')])
 r=dict(schema_version=1,kind='native-rivet-event-components',particles=recipe(primary(kind)),dileptons=[],jets=[],missing_momentum=[met])
 with pytest.raises(ValueError,match='FinalState'):event.compile_component(r)
