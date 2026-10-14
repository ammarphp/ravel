"""Typed source controls; no native dressing, ancestry, weights or clustering."""
from copy import deepcopy
import hashlib
import pytest
from ravel.physics import rivet_particle_component as p

def recipe():
    base={'projection_name':None,'output':None}
    return {'schema_version':1,'kind':'native-rivet-particle-components','nodes':[
      {**base,'id':'allparts','kind':'stable','cuts':[],'pids':None},
      {**base,'id':'bare','kind':'identified','input':'allparts','pids':{'matching':'absolute','values':[11,13]}},
      {**base,'id':'photons','kind':'identified','input':'allparts','pids':{'matching':'signed','values':[22]}},
      {**base,'id':'promptbare','kind':'prompt','input':'bare','tau_decays':'nonprompt','muon_decays':'prompt'},
      {**base,'id':'dressed','kind':'dressed','leptons':'promptbare','photons':'photons','radius':.1,'dressing':'cone',
       'cuts':[{'field':'pt','relation':'gt','value':27,'unit':'GeV'}],'projection_name':'Leptons',
       'output':{'id':'selected','access':'dressed_leptons'}},
      {**base,'id':'jetinput','kind':'vetoed','input':'allparts','veto_projections':['dressed'],
       'veto_pids':{'matching':'absolute','values':[12,14,16]},'projection_name':'JetInput'}]}

def test_native_constructor_phase_defaults_are_explicit():
    r=recipe();old=deepcopy(r);c=p.compile_component(r)
    assert r==old
    assert 'PromptFinalState promptbare(bare, TauDecaysAs::NONPROMPT, MuDecaysAs::PROMPT)'in c['init']
    assert 'LeptonFinder dressed(promptbare, photons, 0.1, (Cuts::pT > 27.0*GeV), DressingType::CONE)'in c['init']
    assert 'bare.acceptIdPairs({11, 13})'in c['init'] and 'photons.acceptIds({22})'in c['init']
    assert 'jetinput.vetoFinalState(dressed)'in c['init']
    assert all('jetinput.addVetoPairId('+str(x)+')'in c['init']for x in [12,14,16])
    assert c['nodes'][4]['cut_phase']=='composite_momentum_after_native_dressing'
    assert c['nodes'][5]['veto_identity'].startswith('native_rawParticles')
    assert c['analyze']=='const DressedLeptons selected = apply<LeptonFinder>(event, "Leptons").dressedLeptons();'
    assert not c['native_executed'] and not c['physics_validated']

@pytest.mark.parametrize('matching,values,token',[('signed',[-11,13],'Cuts::pid == -11'),('absolute',[11,13],'Cuts::abspid == 11')])
def test_stable_species_and_cuts_are_distinct_from_dressed_cuts(matching,values,token):
    r=recipe();r['nodes'][0]['pids']={'matching':matching,'values':values}
    r['nodes'][0]['cuts']=[{'field':'abs_eta','relation':'lt','value':5,'unit':'1'}]
    c=p.compile_component(r);assert token in c['init'] and 'Cuts::abseta < 5.0'in c['init']

@pytest.mark.parametrize('radius',[0.,.1,10])
def test_cone_radius_zero_explicitly_disables_capture(radius):
    r=recipe();r['nodes'][4]['radius']=radius
    assert p.compile_component(r)['nodes'][4]['radius']==float(radius)

@pytest.mark.parametrize('access',['particles','particles_by_pt','raw_particles','dressed_leptons'])
def test_native_accessor_is_literal_and_complete(access):
    r=recipe();r['nodes'][4]['output']['access']=access
    assert p.compile_component(r)['nodes'][4]['output_access']==access

@pytest.mark.parametrize('mutation',['forward','cycle','duplicate','native_name','symbol','pidbool','pidfloat','pidlist','pidzero','pidabsnegative',
  'pidduplicate','unknownkey','decaymissing','decayunknown','cluster','negative_radius','huge_radius','nan','radiusbool',
  'badunits','veto_forward','veto_duplicate','output_undeclared','outputcollision','wrong_accessor','injection','wrongkind'])
def test_refuse_unsupported_or_ambiguous_source(mutation):
    r=recipe();nodes=r['nodes']
    if mutation=='forward':nodes[1]['input']='photons'
    elif mutation=='cycle':nodes[1]['input']='bare'
    elif mutation=='duplicate':nodes[1]['id']='allparts'
    elif mutation=='native_name':nodes[5]['projection_name']='Leptons'
    elif mutation=='symbol':nodes[0]['id']='LeptonFinder'
    elif mutation.startswith('pid'):
        nodes[1]['pids']['values']={'pidbool':[True],'pidfloat':[11.0],'pidlist':[[]],'pidzero':[0],
          'pidabsnegative':[-11],'pidduplicate':[11,11]}[mutation]
    elif mutation=='unknownkey':nodes[4]['implicit_weights']=True
    elif mutation=='decaymissing':nodes[3].pop('muon_decays')
    elif mutation=='decayunknown':nodes[3]['tau_decays']='auto'
    elif mutation=='cluster':nodes[4]['dressing']='antikt'
    elif mutation in ('negative_radius','huge_radius','nan','radiusbool'):
        nodes[4]['radius']={'negative_radius':-.1,'huge_radius':11,'nan':float('nan'),'radiusbool':True}[mutation]
    elif mutation=='badunits':nodes[4]['cuts'][0]['unit']='TeV'
    elif mutation=='veto_forward':nodes[5]['veto_projections']=['later']
    elif mutation=='veto_duplicate':nodes[5]['veto_projections']=['dressed','dressed']
    elif mutation=='output_undeclared':nodes[4]['projection_name']=None
    elif mutation=='outputcollision':nodes[4]['output']['id']='photons'
    elif mutation=='wrong_accessor':nodes[4]['output']['access']='momentum_sum'
    elif mutation=='injection':nodes[4]['id']='x);evil()'
    else:nodes[4]['kind']=[]
    with pytest.raises(ValueError):p.compile_component(r)

def test_fresh_whole_source_slots_preserve_every_outside_byte():
    source=b'// RAVEL_PARTICLE_HEADERS\nvoid init(){\n  // RAVEL_PARTICLE_INIT\n}\nvoid analyze(){\n  // RAVEL_PARTICLE_ANALYZE\n  ORIGINAL_BODY();\n}\n'
    result=p.instantiate(source,expected_sha256=hashlib.sha256(source).hexdigest(),recipe=recipe())
    assert b'  ORIGINAL_BODY();\n'in result['source'] and result['source_sha256']!=result['original_template_sha256']
    assert result['source_capsule_dependency_review'].startswith('incomplete')
    with pytest.raises(ValueError):p.instantiate(source,expected_sha256='0'*64,recipe=recipe())
    with pytest.raises(ValueError):p.instantiate(source+ b'// RAVEL_PARTICLE_INIT\n',expected_sha256=hashlib.sha256(source+b'// RAVEL_PARTICLE_INIT\n').hexdigest(),recipe=recipe())
