from copy import deepcopy
import hashlib,json,os,subprocess
from pathlib import Path
import pytest
from ravel import analysis_sources
from ravel.physics import rivet_components as m

def capsule():
    return {'schema_version':1,'kind':'analysis-source-capsule','framework':'rivet','routine':'Example',
        'source':{'repository':'supplied','revision':None,'description':'Explicit fabricated portable source fixture.'},
        'root':'/original','files':[{'path':'SYN_9347_I1349.cc','sha256':'a'*64,'role':'compile'},
          {'path':'Example.info','sha256':'b'*64,'role':'configuration'}],
        'layout':{'include_dirs':[],'asset_dirs':['.']},'dependencies':[
          {'name':'runtime','kind':'runtime','status':'unresolved','files':[],'reason':'Fabricated source control, not a runtime.'}],
        'dependency_review':{'complete':False,'description':'Unqualified fixture.'},'submodules':[]}

def recipe():
    return {'schema_version':1,'kind':'native-rivet-components','particles':{'schema_version':1,'kind':'native-rivet-particle-components','nodes':[
        {'id':'base','kind':'stable','cuts':[{'field':'pt','relation':'ge','value':.3,'unit':'GeV'}],'pids':None,'projection_name':None,'output':None},
        {'id':'selected','kind':'charged','input':'base','projection_name':'Tracks','output':{'id':'track_particles','access':'particles_by_pt'}}]},
        'jets':{'schema_version':1,'kind':'native-rivet-jet-components','components':[{'id':'trackjet','projection_name':'TrackJets','input':{'kind':'projection','id':'selected'},
        'clustering':{'algorithm':'antikt','radius':.5,'recombination':'E_scheme','muons':'all','invisibles':'none','area':None,'grooming':None},'jet_cuts':[{'field':'abs_rapidity','relation':'lt','value':2,'unit':'1'}],'output':'track_jets'}]}}

@pytest.fixture(autouse=True)
def pure(monkeypatch):
    def deny(*a,**k):raise AssertionError('external computation forbidden')
    monkeypatch.setattr(subprocess,'Popen',deny);monkeypatch.setattr(os,'system',deny)

@pytest.mark.parametrize('kind,cls',[('charged','ChargedFinalState'),('visible','VisibleFinalState')])
def test_native_selector_is_upstream_of_fastjets(kind,cls):
    r=recipe();r['particles']['nodes'][1]['kind']=kind;o=m.compile_component(r)
    assert f'const {cls} selected(base);' in o['init']
    assert 'FastJets trackjet_finder(selected, JetAlg::ANTIKT, 0.5, JetMuons::ALL, JetInvisibles::NONE)' in o['init']
    assert 'trackjet_fs' not in o['init']
    assert 'jetsByPt((Cuts::absrap < 2.0))' in o['analyze']
    assert o['jet_semantics'][0]['input']==r['jets']['components'][0]['input']
    assert not o['native_executed'] and not o['physics_validated']
    assert recipe()['particles']['nodes'][1]['kind']=='charged'

def test_nullable_output_keeps_existing_retrieval_timing():
    r=recipe();r['jets']['components'][0]['output']=None;r['jets']['components'][0]['jet_cuts']=[];o=m.compile_component(r)
    assert 'FastJets' not in o['analyze'] and 'particlesByPt' in o['analyze']
    assert o['jet_semantics'][0]['output'] is None

@pytest.mark.parametrize('change',[
    lambda r:r['jets']['components'][0]['input'].update(id='missing'),
    lambda r:r['jets']['components'][0]['input'].update(kind='reconstructed'),
    lambda r:r['jets']['components'][0]['input'].update(cuts=[]),
    lambda r:r['jets']['components'][0].update(output='base'),
    lambda r:r['jets']['components'][0].update(id='base'),
    lambda r:r['jets']['components'][0].update(projection_name='Tracks'),
    lambda r:r['jets']['components'][0]['clustering'].update(grooming='trim'),
    lambda r:r['jets']['components'][0]['clustering'].update(muons='default'),
    lambda r:r['jets']['components'][0]['jet_cuts'][0].update(unit='GeV'),
    lambda r:r['particles']['nodes'][1].update(kind='invisible'),
    lambda r:r['particles']['nodes'][1].update(input='trackjet'),
    lambda r:r['particles']['nodes'][0].update(id='FastJets'),
    lambda r:r.update(schema_version=True),
])
def test_semantic_or_identity_fault_refuses(change):
    r=recipe();change(r)
    with pytest.raises(ValueError):m.compile_component(r)

def test_veto_and_dressing_feed_same_native_projection_without_rebuilding_fs():
    r=recipe();r['particles']['nodes'].append({'id':'vetoed','kind':'vetoed','input':'base','veto_projections':['selected'],'veto_pids':None,'projection_name':None,'output':None})
    r['jets']['components'][0]['input']['id']='vetoed';o=m.compile_component(r)
    assert 'vetoed.vetoFinalState(selected);' in o['init'] and 'trackjet_finder(vetoed,' in o['init']

def test_source_slots_preserve_enclosing_bytes_and_newline():
    s=b'// original\r\n// RAVEL_COMPONENT_HEADERS\r\nvoid init(){\r\n  // RAVEL_COMPONENT_INIT\r\n}\r\nvoid analyze(){\r\n  // RAVEL_COMPONENT_ANALYZE\r\n  weight_and_fill();\r\n}\r\nfinalize_every_object();\r\n'
    o=m.instantiate(s,expected_sha256=hashlib.sha256(s).hexdigest(),recipe=recipe())
    assert b'weight_and_fill();\r\n}\r\nfinalize_every_object();\r\n' in o['source']
    assert o['source_sha256']==hashlib.sha256(o['source']).hexdigest()
    for bad in (s+s,s.replace(b'// RAVEL_COMPONENT_HEADERS',b'// missing'),s.replace(b'// RAVEL_COMPONENT_HEADERS',b'x // RAVEL_COMPONENT_HEADERS')):
        with pytest.raises(ValueError):m.instantiate(bad,expected_sha256=hashlib.sha256(bad).hexdigest(),recipe=recipe())

@pytest.mark.parametrize('change',[
 lambda cap:cap.update(framework='cpp'),
 lambda cap:cap['files'][0].update(role='reference'),
])
def test_capsule_wrong_source_role_refuses(change):
    cap=capsule();change(cap)
    with pytest.raises(ValueError):m.source_capsule(cap,compile_unit='SYN_9347_I1349.cc',source=b'new',root='/fresh')

def test_complete_old_runtime_review_never_carries():
    cap=capsule()
    for dep in cap['dependencies']:dep['status']='resolved'
    cap['dependency_review']['complete']=True
    fresh=m.source_capsule(cap,compile_unit='SYN_9347_I1349.cc',source=b'new',root='/fresh')
    assert not fresh['dependency_review']['complete'] and all(d['status']=='unresolved' for d in fresh['dependencies'])
    assert fresh['files'][1:]==cap['files'][1:]

def test_two_native_algorithms_share_one_selected_particle_projection():
    r=recipe();c=deepcopy(r['jets']['components'][0]);c.update(id='widejet',projection_name='WideJets',output='wide_jets');c['clustering']['radius']=.8;r['jets']['components'].append(c)
    o=m.compile_component(r)
    assert o['init'].count('ChargedFinalState selected(base)')==1
    assert 'widejet_finder(selected,' in o['init'] and len(o['links'])==2

def test_dressed_lepton_raw_veto_passes_into_jets_without_extra_evaluation():
    r=recipe();r['particles']['nodes']=[
      {'id':'base','kind':'stable','cuts':[],'pids':None,'projection_name':None,'output':None},
      {'id':'leps','kind':'identified','input':'base','pids':{'matching':'absolute','values':[11,13]},'projection_name':None,'output':None},
      {'id':'photons','kind':'identified','input':'base','pids':{'matching':'absolute','values':[22]},'projection_name':None,'output':None},
      {'id':'dressed','kind':'dressed','leptons':'leps','photons':'photons','radius':.1,'dressing':'cone','cuts':[],'projection_name':None,'output':None},
      {'id':'remaining','kind':'vetoed','input':'base','veto_projections':['dressed'],'veto_pids':None,'projection_name':None,'output':None}]
    r['jets']['components'][0]['input']['id']='remaining';r['jets']['components'][0]['output']=None;r['jets']['components'][0]['jet_cuts']=[];o=m.compile_component(r)
    assert 'LeptonFinder dressed(leps, photons, 0.1,' in o['init']
    assert 'remaining.vetoFinalState(dressed)' in o['init'] and 'trackjet_finder(remaining,' in o['init']
    assert not o['analyze']

def test_same_capsule_root_is_not_a_fresh_derivative():
    cap=capsule()
    with pytest.raises(ValueError):m.source_capsule(cap,compile_unit='SYN_9347_I1349.cc',source=b'new',root=cap['root'])

@pytest.mark.parametrize('cut',[
    {'field':'pt','relation':'gt','value':1e6,'unit':'GeV'},
    {'field':'abs_rapidity','relation':'lt','value':2,'unit':'1'},
])
def test_null_output_refuses_unconsumed_jet_cut(cut):
    r=recipe();r['jets']['components'][0]['output']=None;r['jets']['components'][0]['jet_cuts']=[cut]
    original=deepcopy(r)
    with pytest.raises(ValueError,match='null jet output requires empty jet_cuts'):
        m.compile_component(r)
    assert r==original
