"""Generic, offline premise retrieval controls; no inference or native jobs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import premises, physics_knowledge, trap_sweep


def ids(rows):
    return {row['id'] for row in rows}


def test_registry_consolidates_canonical_populations():
    registry = premises.registry()
    assert tuple(r['id'].removeprefix('trap:') for r in registry['premises']
                 if r['id'].removeprefix('trap:') in trap_sweep.TRAP_IDS) == trap_sweep.TRAP_IDS
    original = json.loads((premises.DATA.parent / 'inference/interpretation_traps.json').read_text())
    interpretation = {r['id']: r for r in registry['premises'] if r['canonical']['kind'] == 'interpretation'}
    assert set(interpretation) == {'trap:' + r['id'] for r in original['traps']}
    for r in original['traps']:
        assert interpretation['trap:' + r['id']]['canonical']['id'] == r['id']
    from ravel.workflow.sfitter_review_protocol import CONCERNS
    assert {r['canonical']['id'] for r in registry['premises']
            if r['canonical']['kind'] == 'concern'} == set(CONCERNS)


def test_single_point_yield_fires_before_execution():
    plan = {'nodes': [{'id': 'predict', 'operation': 'signal-yield',
                       'claim_kind': 'prediction', 'basis': 'simulated_acceptance',
                       'tags': ['single-point', 'single-charge']} ]}
    hits = premises.firing(plan)
    assert {'trap:T9', 'conv:single-charge'} <= ids(hits)
    assert all(r['obligations'] and r['why'] for r in hits)
    assert plan['nodes'][0].keys() == {'id', 'operation', 'claim_kind', 'basis', 'tags'}


def test_registered_yield_mode_fires_from_an_unexecuted_spec():
    plan = {'nodes': [{'id': 'predict', 'spec': {'mode': 'mc-expected-construction'}}]}
    assert {'trap:T9', 'conv:single-charge'} <= ids(premises.firing(plan))


def test_registered_measurement_mode_fires_from_an_unexecuted_spec():
    plan = {'nodes': [{'id': 'fit', 'spec': {'mode': 'differential-likelihood',
                                            'interference': True}}]}
    hits = ids(premises.firing(plan))
    assert {'trap:T1', 'trap:T8', 'trap:landau-yang',
            'trap:cp-odd-continuum-interference', 'trap:interference-k-factor'} <= hits


def test_measurement_interference_fires_entire_interpretation_before_inference():
    facts = {'operation': 'measurement-reinterpretation',
             'observables': ['four-lepton-mass'], 'tags': ['interference', 'broad-resonance']}
    hits = premises.firing(facts)
    original = json.loads((premises.DATA.parent / 'inference/interpretation_traps.json').read_text())
    assert {'trap:T1', 'trap:T8', *('trap:' + r['id'] for r in original['traps'])} <= ids(hits)
    assert all(r['status'] == 'check_required' for r in hits)


def test_broad_four_lepton_query_returns_physics_and_obligations():
    result = premises.query('find', text='four-lepton broad resonance interference CP gluon fusion')
    required = {'trap:landau-yang', 'trap:cp-odd-continuum-interference',
                'trap:signed-weight-normalisation', 'trap:interference-k-factor'}
    assert required <= ids(result['results'])
    assert result['kind'] == 'knowledge-result'
    assert result['served_ids'] == [r['id'] for r in result['results']]
    assert all(r['citation'] and r['obligations'] for r in result['results'])
    unsigned = {k: v for k, v in result.items() if k != 'result_sha256'}
    assert result['result_sha256'] == hashlib.sha256(json.dumps(
        unsigned, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@pytest.mark.parametrize('name', ['generation', 'normalization', 'statistics',
                                  'interference-cp', 'theory-procedures',
                                  'reinterpretation', 'detector-models'])
def test_shards_pass_existing_kernel_with_located_licensed_evidence(name):
    request = premises.shard_request(name, text='physics', roots='all')
    packet = physics_knowledge.retrieve(request, premises.DATA)
    assert 0 < len(packet['nodes']) <= physics_knowledge.MAX_NODES
    assert not any(packet['claims'].values())
    for node in packet['nodes']:
        assert node['source_evidence'] and node['obligations']
        assert all('Apache-2.0' in e['citation'] for e in node['source_evidence'])


def test_conventions_dependency_closure_and_caveats():
    result = premises.query('conventions', tags=['gluon-fusion', 'interference'])
    nodes = {r['id']: r for r in result['results']}
    assert 'conv:signed-weights' in nodes
    assert 'on-shell' in nodes['conv:landau-yang']['summary']
    assert 'CP-symmetric' in nodes['conv:cp-even-odd']['summary']
    assert 'universal' in nodes['conv:interference-k-factor']['summary']


def test_irrelevant_and_explicit_false_facts_do_not_fire():
    assert premises.firing({'operation': 'symbolic-calculation', 'interference': False}) == []
    assert premises.firing({'operation': 'unregistered-operation', 'title': 'interference'}) == []


def test_predicates_do_not_leak_between_plan_nodes():
    combined = {'nodes': [{'id': 'a', 'operation': 'symbolic-calculation'},
                          {'id': 'b', 'operation': 'signal-yield'}]}
    rows = premises.firing(combined)
    assert next(r for r in rows if r['id'] == 'trap:T9')['node_ids'] == ['b']


@pytest.mark.parametrize('facts', [None, [], {'nodes': 'bad'}, {'tags': 'interference'},
                                  {'nodes': [{'id': 'a'}, {'id': 'a'}]}])
def test_malformed_facts_refused(facts):
    with pytest.raises(ValueError):
        premises.firing(facts)


def test_query_is_deterministic_and_returns_fresh_objects():
    first = premises.query('for_node', operation='signal-yield')
    saved = deepcopy(first)
    first['results'][0]['statement'] = 'changed by caller'
    assert premises.query('for_node', operation='signal-yield') == saved
    with pytest.raises(ValueError):
        premises.query('execute')
    with pytest.raises(ValueError):
        premises.query('show', id='trap:missing')


def test_catalogue_licences_and_nonopen_sources_have_no_excerpts():
    registry = premises.registry()
    assert registry['license'] == 'Apache-2.0'
    for row in registry['premises'] + registry['conventions']:
        assert row['license'] == 'Apache-2.0'
        for citation in row['citation']:
            assert citation['locator'] and citation['license']
            if citation['license'] == 'LicenseRef-locator-only':
                assert 'excerpt' not in citation
                assert citation['excerpt_sha256'] is None


def test_relocated_shards_need_no_checkout(tmp_path):
    import shutil
    target = tmp_path.resolve() / 'knowledge'
    shutil.copytree(premises.DATA, target)
    request = premises.shard_request('normalization', roots='all', data_dir=target)
    assert physics_knowledge.retrieve(request, target)['nodes']


def test_stale_authored_source_pin_refuses_retrieval(tmp_path):
    import shutil
    target = tmp_path.resolve() / 'knowledge'
    shutil.copytree(premises.DATA, target)
    path = target / 'premises.json'
    path.write_bytes(path.read_bytes().replace(b'branching', b'BRANCHING', 1))
    with pytest.raises(ValueError, match='source bytes differ'):
        physics_knowledge.retrieve(premises.shard_request(
            'normalization', roots='all', data_dir=target), target)


def test_canonical_concern_text_is_loaded_not_copied(monkeypatch):
    original = premises._concerns()
    original['traceability'] = ('extraction', 'A revised canonical check')
    monkeypatch.setattr(premises, '_concerns', lambda: original)
    row = premises.query('show', id='trap:review-traceability')['results'][0]
    assert row['check'] == 'A revised canonical check'
    assert row['obligations'][0]['description'] == row['check']
    assert row['canonical_source_pin']['sha256']


def test_existing_kernel_dependency_closure_is_used():
    request = premises.shard_request('interference-cp', text='root',
                                     roots=['conv:cp-odd-continuum'])
    packet = physics_knowledge.retrieve(request, premises.DATA)
    assert set(packet['selection']['selected_ids']) == {
        'conv:cp-odd-continuum', 'conv:cp-even-odd', 'conv:signed-weights'}


@pytest.mark.parametrize('predicate', [None, {'eval': 'True'}, {'any': []},
                                      {'any': [{'unknown': ['x']}]},
                                      {'any': [{'tags_any': 'interference'}]}])
def test_predicates_reject_executable_or_unknown_selectors(predicate):
    with pytest.raises(ValueError):
        premises._predicate(predicate, set(), set())


def test_title_and_identifier_do_not_steer_firing():
    facts = {'operation': 'signal-yield', 'tags': ['single-charge']}
    a = premises.firing({**facts, 'title': 'unrelated prose', 'id': 'a'})
    b = premises.firing({**facts, 'title': 'different prose', 'id': 'b'})
    assert ids(a) == ids(b)


def test_scientific_caveats_are_returned_with_canonical_notes():
    cp = premises.query('show', id='trap:cp-even-cp-odd-interference-in-even-observables')['results'][0]
    assert 'CP-symmetric' in cp['statement'] and 'asymmetric cuts' in cp['statement']
    assert cp['canonical']['statement']
    signed = premises.query('show', id='trap:signed-weight-normalisation')['results'][0]
    assert 'unless' in signed['statement'] and 'magnitudes' in signed['check']
    assert signed['canonical']['statement']


def _locators(row_id):
    row = premises.query('show', id=row_id)['results'][0]
    return ' '.join(c['locator'] for c in row['citation'])


@pytest.mark.parametrize('row_id,required,absent', [
    ('conv:landau-yang', ['Dokl. Akad. Nauk SSSR 60 (1948) 207', 'arXiv:0806.2864'], []),
    ('trap:landau-yang', ['Dokl. Akad. Nauk SSSR 60 (1948) 207', 'arXiv:0806.2864'], []),
    ('conv:interference-k-factor', ['arXiv:1304.3053'], []),
    ('trap:interference-k-factor', ['arXiv:1304.3053'], []),
    ('conv:cp-odd-continuum', ['arXiv:hep-ph/9404359'], ['review Kinematics']),
    ('trap:cp-odd-continuum-interference', ['arXiv:hep-ph/9404359'], ['review Kinematics']),
    ('conv:single-charge', ['review Structure Functions'], ['review Kinematics']),
])
def test_physics_premises_cite_sources_that_state_them(row_id, required, absent):
    text = _locators(row_id)
    assert all(r in text for r in required)
    assert not any(a in text for a in absent)


def test_shard_nodes_repeat_their_registry_rows_exactly():
    rows = {r['id']: r for r in premises.registry()['conventions']}
    seen = set()
    for name in premises.SHARDS:
        shard = json.loads((premises.DATA / 'conventions' / (name + '.json')).read_text())
        for node in shard['nodes']:
            row = rows[node['id']]
            seen.add(node['id'])
            assert row['shard'] == name
            assert node['statement'] == row['statement']
            assert node['tags'] == row['tags']
            assert node['obligations'] == row['obligations']
            assert node['evidence'][0]['locator'].endswith(
                '; '.join(c['locator'] for c in row['citation']))
    assert seen == set(rows)
