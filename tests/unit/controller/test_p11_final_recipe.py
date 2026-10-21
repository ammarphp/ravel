"""Final recipe follows the authenticated declaration, without a legacy alias."""
from copy import deepcopy
import hashlib

import pytest

from ravel.physics import quantities
from ravel.workflow import scientific_context as sc, scientific_report as report
from ravel.workflow.state_io import read_json
from test_research_cycle import quantities_contract, source_context, write
from test_research_full_cycle_outer import final_recipe
from test_scientific_context import attempt


def inputs(base):
    root, child = base / 'campaign', base / 'ordinary-child'
    request = source_context(base)
    declared = write(base / 'inputs/declarations/current-request.json', request)
    # Real supplied arithmetic; no completed campaign, authority or review fixture.
    records = [{'event_id': identity, 'group_id': 'paired', 'shard_id': 'toy',
                'weights': {'nominal': weight}, 'fills': [[.5]]}
               for identity, weight in [('a', 2), ('b', -1)]]
    calculated = quantities.calculate(quantities_contract(), records)
    result = write(child / 'outputs/attempt-1/result.json', {'quantities': calculated})
    context = sc.compile_context(request, base)
    context = sc.apply_step(context, attempt({'measurement': {
        key: result[key] for key in ('path', 'sha256')}}), base)
    assert context['quantity_completion'] and context['context_complete']
    state = {'base_dir': str(base), 'scientific_context_declaration': {'request': declared},
             'context': context}
    return root, child, state, declared, result


@pytest.mark.parametrize('relative_declaration', [False, True])
def test_final_recipe_composes_actual_declared_request_and_exact_current_quantity(tmp_path, relative_declaration):
    root, child, state, declared, result = inputs(tmp_path)
    if relative_declaration:
        state['scientific_context_declaration']['request']['path'] = 'inputs/declarations/current-request.json'
    original = deepcopy(state)
    snapshot = write(tmp_path / 'expected-context.json', state['context'])
    assert not (tmp_path / 'context-request.json').exists()
    recipe = final_recipe(tmp_path, root, child, state)
    assert state == original
    basis = recipe['artifact_request']['basis'][0]
    assert basis == {**declared, 'path': 'inputs/declarations/current-request.json'}
    assert basis['sha256'] == hashlib.sha256((tmp_path / basis['path']).read_bytes()).hexdigest()
    persisted = tmp_path / recipe['context']['path']
    assert persisted.read_bytes() == (tmp_path / 'expected-context.json').read_bytes()
    assert recipe['context']['sha256'] == snapshot['sha256']
    assert read_json(persisted) == state['context']
    assert recipe['artifact_request']['tools']['study']['sha256'] == result['sha256']
    out = report.compose(recipe, base_dir=tmp_path)
    assert out['delivered_artifact']['artifact'] == {'variance': 1.0}
    assert out['facts'][0]['value'] == 1.0
    assert out['facts'][0]['requested_quantity_checked'] == 'conditional-variance'
    assert out['requested_quantity_census'] == [{'id': 'conditional-variance', 'passed': True,
                                                'exposed_fact_ids': ['conditional']}]
    assert out['requested_quantity_completion'] is True
    assert out['context_sha256'] == state['context']['context_sha256']
    assert out['delivered_artifact']['basis'] == [basis]
    assert out['scientific_acceptance'] is False and out['execution_authorized'] is False
    assert state['context']['physics_validated'] is False
    assert read_json(tmp_path / result['path'])['quantities']['physics_validated'] is False
    assert not (tmp_path / 'context-request.json').exists()


@pytest.mark.parametrize('damage', ['changed', 'missing'])
def test_final_recipe_refuses_changed_or_missing_actual_declaration_before_materialization(tmp_path, damage):
    root, child, state, declared, _ = inputs(tmp_path)
    source = tmp_path / declared['path']
    if damage == 'changed':
        source.write_text('{}\n')
    else:
        source.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        final_recipe(tmp_path, root, child, state)
    assert not (root / 'synthesis-context').exists()


def test_final_recipe_refuses_missing_ordinary_child_result(tmp_path):
    root, child, state, _, result = inputs(tmp_path)
    (tmp_path / result['path']).unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        final_recipe(tmp_path, root, child, state)
