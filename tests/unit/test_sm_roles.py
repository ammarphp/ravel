"""Staged specialist contracts and generic staffing; no model or tool execution."""
from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

from ravel.workflow import role_registry as rr

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'src/ravel/data'
ROLES = ('consult-sm-measurement', 'measurement-analyst', 'theory-prediction-producer',
         'consult-generators', 'precision-theory-auditor', 'unfolding-reviewer',
         'generator-tuner', 'pdf-impact-analyst', 'ew-fit-analyst', 'measurement-combination-reviewer')
SPECIALISTS = ('precision-theory-auditor', 'unfolding-reviewer', 'measurement-combination-reviewer')


def card(role):
    # The cards wait beside their registration fragment until the registry merge places them
    # at their declared override path; a card in roles/cards that the registry does not list is refused.
    return json.loads((DATA / 'sm/registration/cards' / (role + '.json')).read_text())


def fragment(name):
    return json.loads((DATA / 'sm/registration' / (name + '.json')).read_text())


def kinds():
    # The fragment's quantity vocabulary joins the registry's at the same merge as its cards.
    return {**rr.registry_document()['quantity_kinds'], **fragment('roles')['quantity_kinds']}


@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('identity', ['hb:missing-handbook', 'check:sm.missing-check'])
def test_registry_validator_refuses_unknown_card_reference(role, identity):
    value = card(role)
    # A supplied synthetic ID set isolates registry resolution from pending integration.
    known = set(value['knowledge']['must_read'] + value['must_check'])
    value['knowledge']['must_read'].append(identity)
    assert 'unresolved knowledge ID: ' + identity in rr.validate_card(value, known_ids=known, quantity_kinds=kinds())


@pytest.mark.parametrize('role', ROLES)
def test_ten_cards_follow_schema_and_have_exact_registration(role):
    value = card(role)
    known = set(value['knowledge']['must_read'] + value['must_check'])
    assert rr.validate_card(value, known_ids=known, quantity_kinds=kinds()) == []
    row = fragment('roles')['roles'][role]
    assert row['card'] == value and row['override'] == 'cards/' + role + '.json'
    assert role in fragment('roles')['required_roles']
    assert value['model']['effort'] == 'high'


@pytest.mark.parametrize('role', SPECIALISTS)
@pytest.mark.parametrize('fault', ['fresh_session', 'producer_headline', 'actor'])
def test_specialist_protocol_rejects_independence_fault(role, fault):
    sm = importlib.import_module('ravel.validation.sm_checks')
    value = card(role)
    assert sm.review_card_errors(value) == []
    if fault == 'fresh_session': value['independence']['fresh_session'] = False
    elif fault == 'producer_headline': value['sees']['forbidden_inputs'].remove('producer_headline')
    else: value['independence']['distinct_actor_from'] = []
    assert sm.review_card_errors(value)
    known = set(value['knowledge']['must_read'] + value['must_check'])
    assert rr.validate_card(value, known_ids=known, quantity_kinds=kinds())


@pytest.mark.parametrize('role', SPECIALISTS)
def test_specialist_review_packet_rejects_planted_scientific_fault(role):
    from test_sm_checks import packet, plant
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    checks = card(role)['must_check']
    assert all(sm.run(identity, bundle, record)['status'] == 'passed' for identity in checks)
    plant(checks[0].removeprefix('check:sm.'), bundle, record)
    assert any(sm.run(identity, bundle, record)['status'] == 'failed' for identity in checks)


def test_fragment_quantity_vocabulary_matches_card_ownership():
    vocabulary = fragment('roles')['quantity_kinds']
    assert not set(vocabulary) & set(rr.registry_document()['quantity_kinds'])
    owned = {(kind, role) for role in ROLES for kind in card(role)['ownership']['owns']}
    assert owned == {(kind, role) for kind, row in vocabulary.items() for role in row['source_roles']}
    for role in ROLES:
        value = card(role)
        assert set(value['ownership']['judges']) <= set(vocabulary)
        assert bool(value['ownership']['owns']) == (value['independence']['kind'] == 'producer')
        if role in SPECIALISTS:
            assert value['ownership']['judges']


def test_all_traps_and_checks_have_bidirectional_coverage():
    sm = importlib.import_module('ravel.validation.sm_checks')
    traps = fragment('traps')['traps']
    assert {t['id'] for t in traps} == {'TS' + str(i) for i in range(1, 16)}
    rows = fragment('checks')['checks']
    registered = {r['id'] for r in rows}
    assert registered == {'check:' + identity for identity in sm.CHECKS}
    assert all(t['checks'] and set(t['checks']) <= registered for t in traps)
    assert all(r['traps'] or r['stage_gates'] for r in rows)
    for trap in traps:
        for identity in trap['checks']:
            assert trap['id'] in next(r for r in rows if r['id'] == identity)['traps']


def plan():
    return {'agent_layer_epoch': 2, 'nodes': [
        {'id': 'node-a', 'operation': 'prediction', 'fields': [{'pointer': '/review/stage', 'value': 'S4'}]},
        {'id': 'node-b', 'operation': 'unfold', 'fields': []},
        {'id': 'node-c', 'operation': 'unfold', 'fields': [{'pointer': '/review/stage', 'value': 'S4'}]},
    ]}


@pytest.mark.parametrize('role', ['precision-theory-auditor', 'unfolding-reviewer'])
def test_missing_specialist_is_refused_per_matching_node(role):
    sm = importlib.import_module('ravel.validation.sm_checks')
    value = plan()
    points = sm.derive_review_points(value)
    assert sm.staffing_errors(value, points) == []
    stripped = [p for p in points if all(r['role'] != role for r in p['roles'])]
    assert sm.staffing_errors(value, stripped)


def test_staffing_handles_every_matching_node_and_preserves_legacy_identity():
    sm = importlib.import_module('ravel.validation.sm_checks')
    value = plan()
    points = sm.derive_review_points(value)
    assert len(points) == 4 and all(p['gate'] == 'checkin2_accept' for p in points)
    assert len({p['id'] for p in points}) == 4
    assert sm.derive_review_points({**value, 'nodes': value['nodes'][::-1]}) == points
    assert sm.derive_review_points({**value, 'agent_layer_epoch': 1}) == []
    assert sm.derive_review_points({'agent_layer_epoch': 2, 'nodes': []}) == []


def test_a_review_on_another_node_does_not_cover_a_missing_review():
    sm = importlib.import_module('ravel.validation.sm_checks')
    value = plan()
    points = sm.derive_review_points(value)
    points[0]['node_id'] = 'unrelated-node'
    assert sm.staffing_errors(value, points)


def test_premise_fragment_binds_conventions_checks_and_staffing():
    premises = fragment('premises')['premises']
    assert {p['id'] for p in premises} >= {'premise:sm-theory-review', 'premise:sm-unfold-review'}
    assert all(p['citation'] and p['license'] == 'Apache-2.0' for p in premises)
    assert all(p['obligations'] and p['predicate']['any'] for p in premises)


def test_conventions_shard_authenticates_authored_source():
    from ravel.workflow import physics_knowledge
    path = DATA / 'knowledge/conventions/sm-measurements.json'
    # The source is the authored premise fragment; the existing closed arithmetic
    # vocabulary deliberately carries source-inspection obligations here.
    binding = {'path': str(path), 'sha256': __import__('hashlib').sha256(path.read_bytes()).hexdigest(),
               'size': path.stat().st_size}
    corpus = physics_knowledge.retrieve({'schema_version': 1, 'knowledge': binding,
        'query': {'text': 'measurement', 'tags': ['measurement'], 'roots': [],
                  'domain': ['hep'], 'max_nodes': 64}}, base=path.parent)
    assert corpus['nodes']


@pytest.mark.xfail(reason='awaits SM-14 handbook registration and SM-18 registry merge', strict=True)
def test_live_cards_resolve_in_actual_registry_and_atlas():
    assert rr.validate_registry(root=ROOT) == []
    for role in ROLES:
        assert rr.load(role) == card(role)
        assert rr.validate_card(card(role)) == []


def test_live_derivation_staffs_specialists():
    from ravel.workflow import spawn_rows
    sm = importlib.import_module('ravel.validation.sm_checks')
    assert sm.staffing_errors(plan(), spawn_rows.derive(plan())) == []


def test_theory_uncertainty_operation_is_staffed_without_a_declared_stage():
    from ravel.workflow import spawn_rows
    sm = importlib.import_module('ravel.validation.sm_checks')
    value = {'agent_layer_epoch': 2, 'nodes': [
        {'id': 'node-a', 'operation': 'theory-uncertainty', 'fields': []}]}
    points = sm.derive_review_points(value)
    assert [(p['node_id'], r['role']) for p in points for r in p['roles']] == [
        ('node-a', 'precision-theory-auditor')]
    assert sm.staffing_errors(value, spawn_rows.derive(value)) == []
    assert sm.staffing_errors(value, [])


@pytest.mark.parametrize('role', ROLES)
def test_card_protocol_carries_no_test_vocabulary(role):
    assert not any('planted' in line for line in card(role)['protocol'])
