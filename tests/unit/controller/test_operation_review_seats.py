"""Registered operation producers retain all card-required review duties at every tier."""
from copy import deepcopy

import pytest

from ravel.controller import instructions
from ravel.controller.engagement import policy
from ravel.controller.engagement.records import TIERS, digest
from ravel.controller.step import operations
from ravel.workflow import role_registry


def workflow_plan(*, physical=False, role=None, operation='external-workflow', review=()):
    task = {'schema_version': 1, 'operation': 'run', 'snakefile': 'inputs/workflow',
            'targets': ['all'], 'cores': 1}
    if physical:
        task.update(outputs=['result.bin'], output_contract={'result.bin': 'event_sample'})
    node = {'id': 'operate', 'kind': 'operate', 'operation': operation,
            'role': role or ('analysis-author' if physical else 'calculation'),
            'review': list(review), 'parameters': {'task': task}, 'inputs': [], 'outputs': [],
            'depends_on': [], 'instruction_sources': []}
    return {'route': {'id': 'study.site'}, 'steps': [node], 'deliverables': [],
            'checkins': [], 'instruction_sources': []}


@pytest.mark.parametrize('tier', TIERS)
def test_receipt_only_workflow_keeps_registered_reviewer_and_full_manifest(tier):
    plan = workflow_plan()
    original = deepcopy(plan)
    node = plan['steps'][0]
    assert operations.executor_errors(node) == []
    roster = policy.seat_plan(plan, tier)
    assert roster['errors'] == []
    key = 'step:operate:skeptical-verifier'
    assert roster['bindings'][key] == key and roster['actions'][key] == 'keep'
    seat, = [seat for seat in roster['seats'] if seat['key'] == key]
    assert seat['rule'] == 'keep' and seat['source_seats'] == [key]
    assert seat['folded_cards'] == seat['folded_roles'] == []
    producer = role_registry.load(node['role'])
    assert seat['classification_source'] == {
        'source': 'registered_operation_producer_reviewed_by', 'operation': 'external-workflow',
        'producer_role': producer['id'], 'reviewer': 'skeptical-verifier',
        'card_sha256': role_registry.card_sha256(node['role'])}
    card = role_registry.load('skeptical-verifier')
    review_step = {**node, 'role': card['id'], 'kind': 'review'}
    manifest = instructions.manifest(review_step, card)
    assert seat['manifests'] == [manifest]
    expected = instructions.reviewer_items(manifest, card)
    assert expected and seat['items'] == [
        {**item, 'source_item_id': item['id'], 'source_seat': key, 'id': key + '/' + item['id']}
        for item in expected]
    assert seat['constraints'] == policy._constraints(card)
    assert seat['step']['engagement']['items'] == seat['items']
    assert seat['step']['engagement']['constraints'] == seat['constraints']
    assert roster['sha256'] == digest({k: v for k, v in roster.items() if k != 'sha256'})
    assert plan == original


@pytest.mark.parametrize('tier', TIERS)
def test_physical_workflow_preserves_both_existing_reviewer_obligations(tier):
    plan = workflow_plan(physical=True)
    assert operations.executor_errors(plan['steps'][0]) == []
    roster = policy.seat_plan(plan, tier)
    assert roster['errors'] == []
    for role in ('object-selection-mapper', 'physics-critic'):
        key = 'step:operate:' + role
        target, = [seat for seat in roster['seats'] if seat['key'] == roster['bindings'][key]]
        retained = [item for item in target['items'] if item.get('source_seat') == key]
        checks = {item['check'] for item in retained if item['kind'] == 'must_check'}
        assert checks == set(role_registry.load(role)['must_check'])
        assert retained
        # Existing explicit policy retains its folding/keeping rules and needs no fallback.
        if target['key'] == key:
            assert 'classification_source' not in target


@pytest.mark.parametrize('tier', TIERS)
@pytest.mark.parametrize('physical', [False, True])
def test_registered_review_fallback_is_independent_of_template_step_and_route(tier, physical):
    plan = workflow_plan(physical=physical)
    plan['route']['id'] = 'study'
    node = plan['steps'][0]
    node['id'] = 'derive'
    producer = role_registry.load(node['role'])
    roster = policy.seat_plan(plan, tier)
    assert roster['errors'] == []
    for role in producer['reviewed_by']:
        key = 'step:derive:' + role
        seat, = [seat for seat in roster['seats'] if seat['key'] == key]
        assert roster['actions'][key] == seat['rule'] == 'keep'
        assert roster['bindings'][key] == key
        assert seat['classification_source'] == {
            'source': 'registered_operation_producer_reviewed_by', 'operation': node['operation'],
            'producer_role': producer['id'], 'reviewer': role,
            'card_sha256': role_registry.card_sha256(node['role'])}
        retained = [item for item in seat['items'] if item.get('source_seat') == key]
        assert {item['check'] for item in retained if item['kind'] == 'must_check'} == set(
            role_registry.load(role)['must_check'])
        assert retained and seat['constraints'] == policy._constraints(role_registry.load(role))


@pytest.mark.parametrize('tier', TIERS)
@pytest.mark.parametrize('variant', ['extra-reviewer', 'wrong-production-role', 'unregistered-operation'])
def test_untrusted_or_extra_review_seat_stays_unclassified(tier, variant):
    if variant == 'extra-reviewer':
        plan = workflow_plan(review=['normalization-auditor'])
        reviewer = 'normalization-auditor'
    elif variant == 'wrong-production-role':
        plan = workflow_plan(physical=True, role='calculation')
        reviewer = 'skeptical-verifier'
        assert operations.executor_errors(plan['steps'][0])
    else:
        plan = workflow_plan(operation='unregistered-operation')
        reviewer = 'skeptical-verifier'
    roster = policy.seat_plan(plan, tier)
    key = 'step:operate:' + reviewer
    assert 'unclassified seat kept: ' + key in roster['errors']
    target, = [seat for seat in roster['seats'] if seat['key'] == roster['bindings'][key]]
    assert 'classification_source' not in target
    assert roster['actions'][key] == 'keep'
