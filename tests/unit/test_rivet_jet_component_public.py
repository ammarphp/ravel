from copy import deepcopy
import hashlib
import importlib.util
import math
from pathlib import Path
import pytest

from ravel.physics import rivet_jet_component as module


def cut(field, relation, value, unit='1'):
    return dict(field=field,relation=relation,value=value,unit=unit)


def recipe():
    return {'schema_version':1,'kind':'native-rivet-jet-components','components':[
        {'id':'akt','projection_name':'antikT','input':{'kind':'stable_final_state','cuts':[],'projection_name':None},
         'clustering':{'algorithm':'antikt','radius':.5,'recombination':'E_scheme','muons':'all','invisibles':'none','area':None,'grooming':None},
         'jet_cuts':[cut('pt','gt',50,'GeV'),cut('abs_eta','lt',2.5)],'output':'selected_jets'}]}


def test_native_projection_and_cut_phases():
    r=recipe();before=deepcopy(r);out=module.compile_component(r)
    assert r==before
    assert 'FinalState akt_fs(Cuts::OPEN)' in out['init']
    assert 'JetAlg::ANTIKT, 0.5, JetMuons::ALL, JetInvisibles::NONE' in out['init']
    assert 'jetsByPt((Cuts::pT > 50.0*GeV) && (Cuts::abseta < 2.5))' in out['analyze']
    assert out['components'][0]['input_cut_phase']=='stable_particles_before_clustering'
    assert out['components'][0]['jet_cut_phase']=='clustered_jets_before_native_sort'
    assert not out['native_executed'] and not out['physics_validated']


def test_massive_rapidity_stays_distinct_from_eta():
    r=recipe();r['components'][0]['jet_cuts']=[cut('abs_rapidity','lt',3)]
    out=module.compile_component(r)
    assert 'Cuts::absrap < 3.0' in out['analyze'] and 'abseta' not in out['analyze']
    # Independent physical distinction: pt=100,m=300,pz=1000 gives eta>y.
    eta=math.asinh(1000/100);y=math.asinh(1000/math.hypot(100,300))
    assert eta>2.5>y


@pytest.mark.parametrize('field,relation,value,unit',[('pt','ge',20,'GeV'),('abs_eta','le',2.4,'1'),('abs_rapidity','gt',.2,'1')])
def test_strict_and_inclusive_not_lowered_by_epsilon(field,relation,value,unit):
    r=recipe();r['components'][0]['jet_cuts']=[cut(field,relation,value,unit)]
    result=module.compile_component(r)
    assert module.RELATIONS[relation] in result['analyze']
    assert repr(float(value)) in result['analyze']
    assert 'nextafter' not in result['analyze']


def test_particle_input_cut_not_moved_to_output():
    r=recipe();r['components'][0]['input']['cuts']=[cut('abs_eta','lt',5)]
    result=module.compile_component(r)
    assert 'FinalState akt_fs((Cuts::abseta < 5.0))' in result['init']
    assert '5.0' not in result['analyze']


@pytest.mark.parametrize('algorithm,enum',[('kt','KT'),('antikt','ANTIKT'),('cambridge','CAM')])
def test_supported_native_algorithms(algorithm,enum):
    r=recipe();r['components'][0]['clustering']['algorithm']=algorithm
    assert 'JetAlg::'+enum in module.compile_component(r)['init']


@pytest.mark.parametrize('key,value',[('algorithm','sisccone'),('radius',0),('radius',True),('radius',float('inf')),('radius',10**400),('radius',2**53+1),('algorithm',{}),('muons',[]),('recombination','pt_scheme'),('area',{}),('grooming','softdrop'),('muons','unknown'),('invisibles',True)])
def test_unserved_clustering_refuses(key,value):
    r=recipe();r['components'][0]['clustering'][key]=value
    with pytest.raises(ValueError):module.compile_component(r)


@pytest.mark.parametrize('target,key,value',[('input','kind','prompt_final_state'),('input','cuts',[cut('pt','gt',20,'TeV')]),('root','extra',True),('component','output','while'),('component','projection_name','x\");system("x'),('component','jet_cuts',[cut('abs_eta','lt',True)]),('component','jet_cuts',[cut('pt','gt',1,'GeV')]*2)])
def test_scope_and_code_injection_refuse(target,key,value):
    r=recipe();o=r if target=='root' else r['components'][0] if target=='component' else r['components'][0][target];o[key]=value
    with pytest.raises(ValueError):module.compile_component(r)


def test_component_identity_collisions():
    r=recipe();r['components'].append(deepcopy(r['components'][0]))
    with pytest.raises(ValueError):module.compile_component(r)


TEMPLATE=b'// RAVEL_JET_HEADERS\nnamespace Rivet {\nclass Candidate : public Analysis {\n void init() {\n  // RAVEL_JET_INIT\n }\n void analyze(const Event& event) {\n  // RAVEL_JET_ANALYZE\n  downstream(selected_jets);\n }\n};\n}\n'


def test_actual_source_instantiation_fresh_identity_preserves_surroundings():
    result=module.instantiate(TEMPLATE,expected_sha256=hashlib.sha256(TEMPLATE).hexdigest(),recipe=recipe())
    assert result['source_sha256']!=result['original_template_sha256']
    assert b'downstream(selected_jets);' in result['source']
    assert b'// RAVEL_JET' not in result['source']
    assert result['source_capsule_dependency_review'].startswith('incomplete')
    assert TEMPLATE.startswith(b'// RAVEL_JET_HEADERS')


@pytest.mark.parametrize('source,sha',[(TEMPLATE,'0'*64),(TEMPLATE+ b'// RAVEL_JET_INIT\n',None),(TEMPLATE.replace(b'// RAVEL_JET_INIT',b'x // RAVEL_JET_INIT'),None)])
def test_template_drift_or_ambiguous_slot_refuses(source,sha):
    with pytest.raises(ValueError):module.instantiate(source,expected_sha256=sha or hashlib.sha256(source).hexdigest(),recipe=recipe())
