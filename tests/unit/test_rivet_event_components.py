"""Portable source compiler controls: no native particle or jet execution."""
from copy import deepcopy
import hashlib
import pytest
from ravel.physics import rivet_event_components as m

def recipe():
 return {'schema_version':1,'kind':'native-rivet-event-components',
 'particles':{'schema_version':1,'kind':'native-rivet-particle-components','nodes':[
 {'id':'fs','kind':'stable','projection_name':'FS','output':None,'cuts':[],'pids':None},
 {'id':'photons','kind':'identified','projection_name':None,'output':None,'input':'fs','pids':{'matching':'absolute','values':[22]}}]},
 'dileptons':[{'id':'pair','projection_name':'PAIR','input':{'kind':'native_origins','leptons':'prompt','photons':'nodecay','tau_decays':'prompt','muon_decays':'prompt'},
 'mass_target':{'value':91.2,'unit':'GeV'},'radius':.1,'lepton_selection':{'cuts':[{'field':'pt','relation':'gt','value':20,'unit':'GeV'}],'pids':{'matching':'absolute','values':[11,13]}},
 'pair_cuts':{'kinematics':[],'mass_window':{'low':66,'high':116,'unit':'GeV','operation':'native_massIn'}},'dressing':'cone',
 'outputs':[{'id':'bosons','access':'bosons'},{'id':'leptons','access':'leptons'},{'id':'raw','access':'raw_particles'}],
 'remaining':{'id':'remaining','projection_name':'REMAINING','selection':'all'}}],
 'jets':[{'id':'jet','projection_name':'JETS','input':{'kind':'projection','id':'remaining'},'clustering':{'algorithm':'antikt','radius':.4,'recombination':'E_scheme','muons':'none','invisibles':'none','area':None,'grooming':None},'jet_cuts':[{'field':'pt','relation':'gt','value':30,'unit':'GeV'}],'output':'selected_jets'}],
 'missing_momentum':[{'id':'met','projection_name':'MET','input':'remaining','outputs':[{'id':'out_'+q,'quantity':q,'unit':'GeV'}for q in m.MET_METHODS]}]}

def test_connected_native_order_and_all_recoil_methods():
 c=m.compile_component(recipe());s=c['init'];a=c['analyze']
 assert s.index('FinalState fs')<s.index('DileptonFinder pair')<s.index('VetoedFinalState remaining')<s.index('FastJets jet_finder')<s.index('MissingMomentum met')
 assert 'FastJets jet_finder(remaining,'in s and 'jet_fs('not in s
 assert 'jet_finder' in s and 'jetsByPt((Cuts::pT > 30.0*GeV))'in a
 assert 'Cuts::massIn(66.0*GeV, 116.0*GeV)'in s
 assert 'LeptonOrigin::PROMPT, PhotonOrigin::NODECAY, TauDecaysAs::PROMPT, MuDecaysAs::PROMPT, DressingType::CONE)'in s
 for typ,method,_ in m.MET_METHODS.values():assert '.'+method+'()/GeV;'in a
 assert 'no_fallback_after_rejection'in c['event_semantics'][0]['selection']
 assert 'not_lepton_input_scope'in c['event_semantics'][0]['remaining_scope']
 assert c['native_executed']is False and c['physics_validated']is False

@pytest.mark.parametrize('kind', ['final_state','two_final_states'])
def test_exact_native_constructor_order(kind):
 r=recipe();r['dileptons'][0]['input']=({'kind':kind,'id':'fs'}if kind=='final_state'else{'kind':kind,'leptons':'fs','photons':'photons'})
 s=m.compile_component(r)['init'];assert 'DileptonFinder pair('+('fs,'if kind=='final_state'else'fs, photons,')in s

@pytest.mark.parametrize('selection,cls',[('all','VetoedFinalState'),('charged','ChargedFinalState'),('visible','VisibleFinalState')])
def test_native_remaining_selection(selection,cls):
 r=recipe();r['dileptons'][0]['remaining']['selection']=selection
 assert f'const {cls} remaining(pair.remainingFinalState());'in m.compile_component(r)['init']

@pytest.mark.parametrize('field,value', [('id','fs'),('projection_name','FS')])
def test_global_namespace_collision(field,value):
 r=recipe();r['dileptons'][0][field]=value
 with pytest.raises(ValueError):m.compile_component(r)

@pytest.mark.parametrize('stage', ['pair','jet','met'])
def test_future_projection_reference(stage):
 r=recipe()
 if stage=='pair':r['dileptons'][0]['input']={'kind':'final_state','id':'remaining'}
 elif stage=='jet':r['jets'][0]['input']['id']='unknown'
 else:r['missing_momentum'][0]['input']='met'
 with pytest.raises(ValueError):m.compile_component(r)

@pytest.mark.parametrize('cuts',[[],[{'field':'pt','relation':'gt','value':1e6,'unit':'GeV'}]])
def test_lazy_jet_collection_must_consume_declared_cuts(cuts):
 r=recipe();r['jets'][0]['output']=None;r['jets'][0]['jet_cuts']=cuts
 if cuts:
  with pytest.raises(ValueError,match='no generated collection'):m.compile_component(r)
 else:assert 'jetsByPt'not in m.compile_component(r)['analyze']

@pytest.mark.parametrize('bad', [None,False,[],{},'bogus'])
def test_origin_types_closed(bad):
 r=recipe();r['dileptons'][0]['input']['leptons']=bad
 with pytest.raises(ValueError):m.compile_component(r)

@pytest.mark.parametrize('change',[('unit','MeV'),('high',65),('operation','inclusive_window')])
def test_mass_window_native_operation_only(change):
 r=recipe();r['dileptons'][0]['pair_cuts']['mass_window'][change[0]]=change[1]
 with pytest.raises(ValueError):m.compile_component(r)

@pytest.mark.parametrize('quantity,unit',[('missing_energy','GeV'),('missing_pt','1'),('missing_et','MeV')])
def test_no_undeclared_energy_or_units(quantity,unit):
 r=recipe();r['missing_momentum'][0]['outputs']=[{'id':'bad','quantity':quantity,'unit':unit}]
 with pytest.raises(ValueError):m.compile_component(r)

def test_safe_pair_outputs_refuse_unchecked_boson():
 r=recipe();r['dileptons'][0]['outputs']=[{'id':'one','access':'boson'}]
 with pytest.raises(ValueError):m.compile_component(r)

def test_whole_source_slots_are_exact_and_bound():
 raw=b'// RAVEL_EVENT_HEADERS\nvoid init(){\n // RAVEL_EVENT_INIT\n}\nvoid analyze(){\n // RAVEL_EVENT_ANALYZE\n}\n// original finalize remains\n';sha=hashlib.sha256(raw).hexdigest()
 o=m.instantiate(raw,expected_sha256=sha,recipe=recipe())
 assert o['source'].endswith(b'// original finalize remains\n')
 assert o['source_sha256']==hashlib.sha256(o['source']).hexdigest()
 with pytest.raises(ValueError):m.instantiate(raw,expected_sha256='0'*64,recipe=recipe())
 duplicate=raw+b'// RAVEL_EVENT_INIT\n'
 with pytest.raises(ValueError):m.instantiate(duplicate,expected_sha256=hashlib.sha256(duplicate).hexdigest(),recipe=recipe())
