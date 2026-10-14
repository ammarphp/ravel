"""Native source construction and independent supplied-number semantic witnesses.

These tests do not run Rivet, compile C++, simulate particles or qualify events.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import os
import subprocess
import urllib.request

import pytest
from ravel import analysis_sources
from ravel.physics import (rivet_particle_component as p, rivet_components as connected,
                          rivet_event_components as event, native_construction as native,
                          routine_build, existing_events)


def node(identity, kind, **fields):
    return {'id': identity, 'kind': kind, 'projection_name': None, 'output': None, **fields}


def recipe():
    return {'schema_version': 1, 'kind': 'native-rivet-particle-components', 'nodes': [
        node('base', 'stable', cuts=[], pids=None),
        node('invis', 'invisible', prompt_only=True, tau_decays='prompt', muon_decays='nonprompt',
             projection_name='Invisible', output={'id': 'invisible_particles', 'access': 'particles'}),
        node('leps', 'charged_leptons', input='base'),
        node('leaders', 'leading', input='leps', pids={'matching': 'absolute', 'values': [11, 13]},
             leading_only=False, empty_policy='empty_collection'),
        node('pairfs', 'invariant_mass', input='base', pid_pairs=[[13, -14], [-13, 14]],
             mass_window={'low': 20, 'high': 1000, 'unit': 'GeV'}, target_mass=None,
             mass_measure='invariant', projection_name='Pairs',
             output={'id': 'pair_list', 'access': 'particle_pairs'}),
        node('mergedfs', 'merged', first='leaders', second='pairfs')]}


@pytest.fixture(autouse=True)
def pure(monkeypatch):
    def deny(*a, **kw):
        raise AssertionError('native/process/provider execution forbidden')
    monkeypatch.setattr(subprocess, 'Popen', deny)
    monkeypatch.setattr(os, 'system', deny)
    monkeypatch.setattr(urllib.request, 'urlopen', deny)


def test_exact_native_constructors_and_pair_access():
    r = recipe(); original = deepcopy(r); c = p.compile_component(r)
    assert r == original
    for literal in (
        'InvisibleFinalState invis(OnlyDirect::YES, TauDecaysAs::PROMPT, MuDecaysAs::NONPROMPT)',
        'ChargedLeptons leps(base)', 'LeadingParticlesFinalState leaders(leps)',
        'leaders.addParticleIdPair(11);', 'leaders.setLeadingOnly(false);',
        'InvMassFinalState pairfs(base, std::vector<std::pair<PdgId, PdgId>>{{13, -14}, {-13, 14}}, 20.0*GeV, 1000.0*GeV, -1.0*GeV)',
        'pairfs.useTransverseMass(false);', 'MergedFinalState mergedfs(leaders, pairfs)'):
        assert literal in c['init']
    assert 'const std::vector<std::pair<Particle, Particle>> pair_list = apply<InvMassFinalState>(event, "Pairs").particlePairs();' in c['analyze']
    assert not c['native_executed'] and not c['physics_validated']
    assert len([h for h in c['headers'] if any(k in h for k in ('InvisibleFinalState', 'ChargedLeptons', 'LeadingParticles', 'InvMassFinalState', 'MergedFinalState'))]) == 5


def test_invisible_scope_does_not_inherit_restricted_base():
    r = recipe(); r['nodes'][0]['cuts'] = [{'field': 'abs_eta', 'relation': 'lt', 'value': 2, 'unit': '1'}]
    c = p.compile_component(r); inv = c['nodes'][1]
    assert 'invis(base' not in c['init']
    assert inv['input_scope'] == 'native_default_whole_FinalState_no_supplied_acceptance_filter'
    assert 'all_native_invisible_species_not_neutrinos_only' in inv['visibility']
    assert inv['detector_response'] == 'not_detector_MET_or_efficiency'


def test_multiple_identical_invisible_policies_are_explicit():
    r = recipe(); n = deepcopy(r['nodes'][1]); n.update(id='otherinvis', projection_name=None, output=None)
    r['nodes'].append(n)
    assert p.compile_component(r)['init'].count('InvisibleFinalState') == 2


@pytest.mark.parametrize('field,value', [('prompt_only', False), ('tau_decays', 'nonprompt'), ('muon_decays', 'prompt')])
def test_native_cache_policy_aliases_do_not_mix_invisible_flags(field, value):
    r = recipe(); n = deepcopy(r['nodes'][1]); n.update(id='otherinvis', projection_name='OtherInvisible', output=None); n[field] = value
    r['nodes'].append(n)
    with pytest.raises(ValueError, match='cache comparison'): p.compile_component(r)


def test_signed_leading_ids_and_global_default_are_preserved():
    r = recipe(); n = r['nodes'][3]; n.update(pids={'matching': 'signed', 'values': [-11, 13]}, leading_only=True, empty_policy='native_default_particle')
    c = p.compile_component(r)
    assert 'leaders.addParticleId(-11)' in c['init'] and 'leaders.addParticleIdPair' not in c['init']
    assert 'leaders.setLeadingOnly(true)' in c['init']
    assert c['nodes'][3]['empty_policy'] == 'native_default_particle'
    assert 'not_safe_single_particle_access' in c['nodes'][3]['global_zero_or_empty']


def test_material_signed_and_identity_witnesses():
    # Supplied PDG records distinguish signed selection from absolute selection.
    rows = [(-11, 'positron-first', 7), (-11, 'positron-tie', 7), (11, 'electron', 4), (13, 'muon', 7)]
    assert [row[1] for row in rows if row[0] == -11] != [row[1] for row in rows if abs(row[0]) == 11]
    # Native strict > leaves first per signed PID; a global equal-pT tie uses map order.
    per_pid = {}
    for pid, identity, pt in rows:
        if pid not in per_pid or pt > per_pid[pid][1]: per_pid[pid] = (identity, pt)
    assert per_pid[-11][0] == 'positron-first'
    assert sorted(per_pid)[0] == -11
    assert p.compile_component(recipe())['nodes'][3]['tie_rule'].startswith('strict_greater')
    # Merging compares raw identities, so equal momenta can survive and duplicates
    # inside an input stay. This tiny identity census is not a particle evaluator.
    first = ['raw-a', 'raw-a']; second = ['raw-a', 'raw-b', 'raw-b']
    merged = first + [identity for identity in second if identity not in first]
    assert merged == ['raw-a', 'raw-a', 'raw-b', 'raw-b']
    meta = p.compile_component(recipe())['nodes'][5]
    assert meta['duplicate_identity'] == 'native_genParticle_pointer_not_PID_or_momentum'
    assert meta['duplicate_scope'].startswith('second_against_first_only')


def test_mass_target_keeps_full_invariant_metric_in_transverse_window():
    r = recipe(); r['nodes'][4].update(mass_measure='transverse', target_mass={'value': 10, 'unit': 'GeV'})
    c = p.compile_component(r); meta = c['nodes'][4]
    assert 'useTransverseMass(true)' in c['init']
    assert meta['target_metric'] == 'full_invariant_mass_even_when_window_is_transverse'
    assert 'distance_below_1e30_native_units_else_passing_pairs' in meta['pair_selection']
    # Exact massless four-vectors give pair A full m=10 but mT=6; B m=mT=8.
    a = [(5, 3, 0, 4), (5, -3, 0, -4)]
    summed = [sum(v[i] for v in a) for i in range(4)]
    assert Fraction(summed[0])**2 - sum(Fraction(v)**2 for v in summed[1:]) == 100
    assert 2 * (3 * 3 - 3 * -3) == 36
    full_distance = [abs(Fraction(10) - 10), abs(Fraction(8) - 10)]
    transverse_distance = [abs(Fraction(6) - 10), abs(Fraction(8) - 10)]
    assert full_distance.index(min(full_distance)) == 0
    assert transverse_distance.index(min(transverse_distance)) == 1
    assert meta['window_operation'] == 'native_inRange_after_negative_full_mass2_rejection'


def test_mass_cache_guard_covers_equivalent_parent_aliases():
    r = recipe(); alias = deepcopy(r['nodes'][0]); alias['id'] = 'basealias'; r['nodes'].insert(1, alias)
    n = deepcopy(r['nodes'][5]); n.update(id='otherpair', input='basealias', projection_name=None, output=None,
                                        target_mass={'value': 80, 'unit': 'GeV'})
    r['nodes'].append(n)
    with pytest.raises(ValueError, match='omits target'): p.compile_component(r)
    n['mass_window']['low'] = 30
    assert p.compile_component(r)['nodes'][-1]['window_measure'] == 'invariant'


@pytest.mark.parametrize('mutation', [
    lambda r: r['nodes'][1].update(input='base'),
    lambda r: r['nodes'][1].update(prompt_only=1),
    lambda r: r['nodes'][1].update(tau_decays=None),
    lambda r: r['nodes'][2].update(input='later'),
    lambda r: r['nodes'][3].update(leading_only='false'),
    lambda r: r['nodes'][3].update(empty_policy='empty_by_default'),
    lambda r: r['nodes'][3]['pids'].update(values=[True]),
    lambda r: r['nodes'][3]['pids'].update(matching='absolute', values=[-11]),
    lambda r: r['nodes'][4].update(pid_pairs=[[13, 13]]),
    lambda r: r['nodes'][4].update(pid_pairs=[[13, -14], [13, -14]]),
    lambda r: r['nodes'][4].update(pid_pairs=[[13, False]]),
    lambda r: r['nodes'][4].update(pid_pairs=[[-13.0, 14]]),
    lambda r: r['nodes'][4]['mass_window'].update(low=1000),
    lambda r: r['nodes'][4]['mass_window'].update(unit='MeV'),
    lambda r: r['nodes'][4].update(target_mass={'value': 0, 'unit': 'GeV'}),
    lambda r: r['nodes'][4].update(mass_measure='auto'),
    lambda r: r['nodes'][5].update(second='missing'),
    lambda r: r['nodes'][5].update(first='mergedfs'),
    lambda r: r['nodes'][2].update(id='InvMassFinalState'),
    lambda r: r['nodes'][1]['output'].update(access='particle_pairs'),
])
def test_semantic_ambiguity_or_unsupported_scope_refuses(mutation):
    r = recipe(); mutation(r)
    with pytest.raises(ValueError): p.compile_component(r)


def test_same_particle_dag_feeds_existing_jet_and_recoil_routes():
    jet = {'id':'visiblejets','projection_name':'Jets','input':{'kind':'projection','id':'mergedfs'},
        'clustering':{'algorithm':'antikt','radius':.4,'recombination':'E_scheme','muons':'all','invisibles':'none','area':None,'grooming':None},
        'jet_cuts':[], 'output':None}
    c = connected.compile_component({'schema_version':1,'kind':'native-rivet-components','particles':recipe(),
        'jets':{'schema_version':1,'kind':'native-rivet-jet-components','components':[jet]}})
    assert 'visiblejets_finder(mergedfs,' in c['init']
    e = event.compile_component({'schema_version':1,'kind':'native-rivet-event-components','particles':recipe(),
        'dileptons':[], 'jets':[jet], 'missing_momentum':[{'id':'recoil','projection_name':'Recoil','input':'mergedfs',
            'outputs':[{'id':'missing','quantity':'missing_pt','unit':'GeV'}]}]})
    assert 'MissingMomentum recoil(mergedfs)' in e['init']
    assert '.missingPt()/GeV' in e['analyze']
    assert e['event_semantics'][-1]['scope'].startswith('native_VisibleFinalState')
    assert not e['physics_validated']


def test_quantity_contract_stays_complete_and_requires_real_build_custody(tmp_path):
    # A constructed enclosing routine may deliver histograms, profiles and
    # counters via the existing route. This supplied contract is a mechanical
    # interface case, not an inferred CMS/ATLAS unit or numerical result.
    p.compile_component(recipe())
    task = {'backend':'rivet-built','routine':'SelectionControl',
        'build_receipt':str(tmp_path/'build-receipt.json'),'build_plan':str(tmp_path/'build-plan.json'),
        'events':str(tmp_path/'events.hepmc'),'metadata':str(tmp_path/'event-metadata.json'),
        'runtime':{'python':'bound-python','version':'4.1.4'},'seed':1,'options':{},'observables':[
          {'path':'/SelectionControl/pt','axes':[{'name':'pT','unit':'GeV'}],
           'representation':'differential','normalization':'absolute','unit':'pb/GeV'},
          {'path':'/SelectionControl/mean','axes':[{'name':'pT','unit':'GeV'}],
           'representation':'mean','normalization':'absolute','unit':'1','quantity_kind':'profile_mean'},
          {'path':'/SelectionControl/count','axes':[],'representation':'integrated',
           'normalization':'absolute','unit':'event','quantity_kind':'scalar_counter'}]}
    existing_events.validate(task)
    assert len(task['observables']) == 3
    with pytest.raises((ValueError, FileNotFoundError)):
        existing_events.inputs(task, tmp_path)
    wrong = deepcopy(task); wrong['observables'] = []
    with pytest.raises(ValueError, match='denominator'): existing_events.validate(wrong)
    wrong = deepcopy(task); wrong['observables'].append(deepcopy(wrong['observables'][0]))
    with pytest.raises(ValueError, match='duplicate'): existing_events.validate(wrong)


def test_whole_source_materialization_enters_existing_construction_and_build(tmp_path):
    from test_native_construction import setup
    cfg, config = setup(tmp_path)
    original = analysis_sources.load_capsule(config['source_capsule']['path'])
    template = b'#include "Rivet/Analysis.hh"\n// RAVEL_PARTICLE_HEADERS\nnamespace Rivet {\nclass Unknown : public Analysis {\npublic:\nRIVET_DEFAULT_ANALYSIS_CTOR(Unknown);\nvoid init(){\n// RAVEL_PARTICLE_INIT\nbook_all_original_outputs();\n}\nvoid analyze(const Event& event){\n// RAVEL_PARTICLE_ANALYZE\noriginal_weights_selection_and_fill();\n}\nvoid finalize(){original_normalization();}\n};\nRIVET_DECLARE_PLUGIN(Unknown);\n}\n'
    built = p.instantiate(template, expected_sha256=hashlib.sha256(template).hexdigest(), recipe=recipe())
    assert b'original_weights_selection_and_fill();' in built['source']
    assert b'void finalize(){original_normalization();}' in built['source']
    root = tmp_path/'constructed'; root.mkdir()
    for fact in original['files']:
        data = built['source'] if fact['role'] == 'compile' else (tmp_path/'original'/fact['path']).read_bytes()
        (root/fact['path']).write_bytes(data)
    fresh = connected.source_capsule(original, compile_unit='Unknown.cc', source=built['source'], root=str(root))
    cp = tmp_path/'constructed-source.json'; cp.write_text(json.dumps(fresh))
    analysis_sources.source_files(fresh, tmp_path)
    assert analysis_sources.routine_bindings(fresh, tmp_path, ['Unknown.cc'])['Unknown']['registration'] != 'declared-capsule-primary'
    assert fresh['files'][1:] == original['files'][1:]
    assert not fresh['dependency_review']['complete']
    # Existing full-source construction consumes complete C++ and explicit recipe;
    # it does not claim the deterministic compiler was a fresh model generation.
    config['source_capsule'] = {'path':str(cp),'sha256':hashlib.sha256(cp.read_bytes()).hexdigest()}
    config['source_claims'] = [{'id':'source-all','path':'Unknown.cc','line_start':1,
        'line_end':len(built['source'].splitlines()),'excerpt_sha256':hashlib.sha256(built['source']).hexdigest()}]
    recipe_path = tmp_path/'typed-recipe.json'; recipe_path.write_text(json.dumps(recipe()))
    config['support_sources'] = [{'path':str(recipe_path),'sha256':hashlib.sha256(recipe_path.read_bytes()).hexdigest(),
        'description':'Explicit typed constructor input; native source and runtime remain unqualified.'}]
    cfg.write_text(json.dumps(config))
    result = native.write_source_packet(cfg, tmp_path/'source-packet.json')
    packet = json.loads((tmp_path/'source-packet.json').read_text())
    assert not result['model_executed'] and not packet['execution_authorized']
    assert 'InvMassFinalState' in packet['source_text'][0]['text']
    assert json.loads(packet['support_sources'][0]['text']) == recipe()
    assert len(packet['obligations']) == len(config['obligations'])
    build_config = json.loads((tmp_path/'runtime.json').read_text()); build_config['source_capsule']=str(cp)
    build_file = tmp_path/'fresh-build.json'; build_file.write_text(json.dumps(build_config))
    task = {'backend':'routine-build','input':str(build_file)}
    with pytest.raises(ValueError, match='unresolved declared transitive dependency'): routine_build.seal_configuration(task, tmp_path)
    assert not (tmp_path/'RivetControl.so').exists()
