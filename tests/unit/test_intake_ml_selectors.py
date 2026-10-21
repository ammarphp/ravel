"""Closed ML operation interpretations reach their declared fixed routes through grounded intake."""
from copy import deepcopy
import importlib
import json

import pytest

from ravel import cli
from ravel.validation import validate_task_contract as contracts
from ravel.workflow import intake


CASES = (
    ('published-classifier', 'calculation', 'ml.inference',
     'Apply the supplied classifier to the supplied events and return its score table.'),
    ('ml-training', 'research', 'ml.training',
     'Train a classifier on the supplied labelled table and report its held-out performance.'),
)


def interpretation(prompt, kind, **fields):
    return {'schema_version': 1, 'prompt_sha256': intake.prompt_hash(prompt), 'kind': kind,
            'objective': prompt, 'requested_outputs': [prompt],
            'evidence': [{'start': 0, 'end': len(prompt), 'text': prompt}], 'unresolved': [], **fields}


@pytest.mark.parametrize('operation,parent,route,prompt', CASES)
@pytest.mark.parametrize('representation', ('kind', 'operation'))
def test_grounded_ml_selector_roundtrip_uses_the_actual_fixed_route(operation, parent, route, prompt, representation):
    semantic = (interpretation(prompt, operation) if representation == 'kind'
                else interpretation(prompt, parent, operation=operation))
    before = deepcopy(semantic)
    assert intake.validate_interpretation(semantic, prompt) == []
    normalized = intake.proposal(prompt, semantic)
    assert normalized['kind'] == parent and normalized['operation'] == operation
    assert normalized['source'] == 'host-agent' and normalized['review_status'] == 'draft'
    assert semantic == before
    contract, reading, _ = cli._draft_route(prompt, semantic)
    assert contracts.validate(contract) == []
    stored = json.loads(json.dumps(contract, allow_nan=False))
    assert stored == contract
    assert stored['intake'] == normalized
    assert stored['task_mode'] == parent and stored['compute_plan'] == 'none'
    assert stored['approval_required'] is True
    selector = importlib.import_module('ravel.controller.routes.select')
    selected = selector.select(stored, reading, [])
    declared = selector.find(route)
    assert selected['route'] == route
    assert selected['spec_sha256'] == selector.spec_sha256(declared)
    assert selected['version'] == declared['version']
    assert selected['view']['operation'] == operation
    assert selected['view']['held'] is False


def test_ml_operation_admission_extends_only_the_exact_closed_operation_set():
    expected = {'manuscript', 'diagram', 'measurement_fit', 'supplied_events',
                'published-classifier', 'ml-training'}
    assert set(contracts.INTERPRETATION_SCHEMA['properties']['operation']['enum']) == expected
    assert set(contracts.INTAKE_SCHEMA['properties']['operation']['enum']) == expected
    assert set(intake.OPERATION_KINDS) == expected


@pytest.mark.parametrize('operation', ('unknown-operation', 'published_classifier', 'ml_training', 'ML-TRAINING'))
@pytest.mark.parametrize('field', ('kind', 'operation'))
def test_unknown_ml_operation_spellings_remain_refused(operation, field):
    prompt = 'Process the supplied table and return the requested outputs.'
    semantic = interpretation(prompt, 'calculation', **({'operation': operation} if field == 'operation' else {}))
    if field == 'kind':
        semantic['kind'] = operation
    errors = intake.validate_interpretation(semantic, prompt)
    assert any(field in error for error in errors)
    with pytest.raises(ValueError, match=field):
        intake.proposal(prompt, semantic)


@pytest.mark.parametrize('operation,parent,route,prompt', CASES)
@pytest.mark.parametrize('field', ('compute_authorized', 'extra'))
def test_ml_operation_interpretations_keep_unknown_fields_closed(operation, parent, route, prompt, field):
    semantic = interpretation(prompt, parent, operation=operation, **{field: True})
    errors = intake.validate_interpretation(semantic, prompt)
    assert any(field in error for error in errors)
    with pytest.raises(ValueError, match=field):
        cli._draft_route(prompt, semantic)


@pytest.mark.parametrize('operation,parent,route,prompt', CASES)
def test_ml_operation_keeps_its_declared_planning_parent(operation, parent, route, prompt):
    other = 'research' if parent == 'calculation' else 'calculation'
    semantic = interpretation(prompt, other, operation=operation)
    assert any('operation disagrees' in error for error in intake.validate_interpretation(semantic, prompt))
    with pytest.raises(ValueError, match='operation disagrees'):
        intake.proposal(prompt, semantic)


@pytest.mark.parametrize('field,value', (('operation', 'unknown-operation'), ('extra', True)))
def test_stored_intake_refuses_unknown_operation_or_field(field, value):
    prompt = 'Calculate a summary of the supplied table.'
    contract, _, _ = cli._draft_route(prompt, interpretation(prompt, 'calculation'))
    assert contracts.validate(contract) == []
    contract['intake'][field] = value
    assert any(field in error for error in contracts.validate(contract))
