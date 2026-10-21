"""Finite synthetic resource accounting over actual expanded plans; no executions."""
from copy import deepcopy
import math

import pytest

from ravel.controller.routes import plan_sha256
from ravel.controller.routes.budgeting import BudgetInfeasible, narrow_plan


def step(identifier, **budget):
    return {'id': identifier, 'kind': 'operate', 'operation': 'unclassified-test-operation',
            'parameters': {}, 'budget': budget}


def plan(*steps):
    value = {'steps': list(steps), 'parameters': {'scan_points': ['unexpanded-a', 'unexpanded-b']},
             'other': {'retained': True}}
    value['sha256'] = plan_sha256(value)
    return value


def test_actual_expanded_subset_only_and_no_template_scan_counts():
    original = plan(step('scan.point.actual', broker_calls=20, attempts=3))
    before = deepcopy(original)
    result = narrow_plan(original, {'model_calls': 7})
    assert [s['id'] for s in result['steps']] == ['scan.point.actual']
    assert result['steps'][0]['budget'] == {'broker_calls': 7, 'attempts': 3}
    assert result['parameters'] == original['parameters']
    assert result['other'] == original['other']
    assert original == before
    assert result['sha256'] == plan_sha256(result) != original['sha256']


@pytest.mark.parametrize('explicit', [False, True])
@pytest.mark.parametrize('envelope', [{'events': 0}, {'events': 100000}, {}])
def test_proven_nongeneration_allows_zero_events(explicit, envelope):
    node = step('calculate', events=900)
    if explicit:
        node['parameters']['execution_effects'] = ['executes_native']
    else:
        node['operation'] = 'acquire-published'
    result = narrow_plan(plan(node), envelope)
    assert result['steps'][0]['budget']['events'] == 0


def test_proven_nongeneration_may_explicitly_declare_zero_events():
    node = step('metadata', tokens=20)
    node['parameters']['execution_effects'] = []
    result = narrow_plan(plan(node), {})
    assert result['steps'][0]['budget'] == {'tokens': 20, 'events': 0}


@pytest.mark.parametrize('classification', ['explicit-generation', 'registered-generation', 'missing', 'unknown'])
def test_generation_or_unclassified_operation_retains_intended_population(classification):
    node = step('events', events=100)
    if classification == 'explicit-generation':
        node['parameters']['execution_effects'] = ['generates_events']
    elif classification == 'registered-generation':
        node['operation'] = 'generate'
    elif classification == 'missing':
        node.pop('operation')
    with pytest.raises(BudgetInfeasible) as caught:
        narrow_plan(plan(node), {'events': 99})
    assert caught.value.code == 'plan_budget_infeasible'
    assert caught.value.evidence == {'dimension': 'events', 'required': 100, 'available': 99, 'steps': ['events']}
    assert 'reduce' in caught.value.remedy and 'increase' in caught.value.remedy
    assert narrow_plan(plan(node), {'events': 100})['steps'][0]['budget']['events'] == 100


def test_finite_wall_ceiling_uses_proportional_residuals_above_positive_minima():
    result = narrow_plan(plan(step('one', wall_seconds=11), step('two', wall_seconds=21)), {'wall_seconds': 17})
    values = [s['budget']['wall_seconds'] for s in result['steps']]
    assert values == [6, 11]
    assert sum(values) <= 17 and all(v > 0 for v in values)


@pytest.mark.parametrize('source', ['step', 'envelope', 'minimum'])
@pytest.mark.parametrize('value', [1.0, 1.5])
def test_wall_budgets_require_actual_integers(source, value):
    node = step('wall', wall_seconds=value if source == 'step' else 10)
    envelope = {'wall_seconds': value if source == 'envelope' else 10}
    if source == 'minimum':
        node['parameters']['budget_minimum'] = {'wall_seconds': value}
    with pytest.raises(ValueError, match='wall_seconds requires an integer'):
        narrow_plan(plan(node), envelope)


def test_nondivisible_wall_allocation_passes_actual_authority_resource_checks():
    from ravel.controller.authority import operator, service
    from ravel.controller.routes.compiler import authority_budget
    envelope = {'wall_seconds': 7}
    result = narrow_plan(plan(step('one', wall_seconds=11), step('two', wall_seconds=21)), envelope)
    values = [node['budget']['wall_seconds'] for node in result['steps']]
    assert values == [2, 4] and all(type(value) is int for value in values)
    assert sum(values) <= envelope['wall_seconds']
    config = operator.default_config()
    config['budgets'].update(envelope)
    operator.validate(config)
    for node in result['steps']:
        service._check_limits({'stage': 'calculation', 'budget': authority_budget(node['budget'])},
                              config, operator=True, for_effect=True)


def test_frozen_preparation_budgets_remain_unchanged_and_count_against_envelope():
    prep = step('prepare', wall_seconds=8, broker_calls=4, attempts=2)
    result = narrow_plan(plan(prep, step('run', wall_seconds=20, broker_calls=10)),
                         {'wall_seconds': 10, 'model_calls': 5}, frozen_ids=['prepare'])
    assert result['steps'][0] == prep
    assert result['steps'][1]['budget'] == {'wall_seconds': 2, 'broker_calls': 1}
    with pytest.raises(BudgetInfeasible) as caught:
        narrow_plan(plan(prep), {'wall_seconds': 7}, frozen_ids=['prepare'])
    assert caught.value.evidence['required'] == 8


def test_frozen_nongeneration_keeps_original_event_reservation():
    node = step('prepared', events=50)
    node['parameters']['execution_effects'] = []
    assert narrow_plan(plan(node), {'events': 50}, frozen_ids=['prepared'])['steps'][0] == node
    with pytest.raises(BudgetInfeasible):
        narrow_plan(plan(node), {'events': 49}, frozen_ids=['prepared'])


def test_zero_wall_ceiling_is_infeasible_instead_of_increased():
    with pytest.raises(BudgetInfeasible) as caught:
        narrow_plan(plan(step('zero', wall_seconds=0)), {'wall_seconds': 100})
    assert caught.value.evidence == {'dimension': 'wall_seconds', 'required': 1, 'available': 0, 'steps': ['zero']}


def test_explicit_minima_are_reserved_and_infeasibility_names_actual_steps():
    nodes = [step('one', tokens=100), step('two', tokens=100)]
    for node in nodes:
        node['parameters']['budget_minimum'] = {'tokens': 20}
    with pytest.raises(BudgetInfeasible) as caught:
        narrow_plan(plan(*nodes), {'tokens': 39})
    assert caught.value.evidence == {'dimension': 'tokens', 'required': 40, 'available': 39,
                                     'steps': ['one', 'two']}
    assert [s['budget']['tokens'] for s in narrow_plan(plan(*nodes), {'tokens': 41})['steps']] == [20, 20]


def test_explicit_event_minimum_cannot_exceed_original_ceiling():
    node = step('events', events=100)
    node['parameters']['budget_minimum'] = {'events': 101}
    with pytest.raises(BudgetInfeasible):
        narrow_plan(plan(node), {'events': 200})


@pytest.mark.parametrize('value', [-1, float('inf'), float('nan'), True, '3', None])
def test_invalid_step_budgets_refused(value):
    with pytest.raises(ValueError):
        narrow_plan(plan(step('bad', tokens=value)), {'tokens': 10})


@pytest.mark.parametrize('value', [-1, float('inf'), float('nan'), True, '3', 1.5])
def test_invalid_envelopes_refused(value):
    with pytest.raises(ValueError):
        narrow_plan(plan(step('bad', tokens=5)), {'tokens': value})


@pytest.mark.parametrize('minimum', [{'tokens': -1}, {'tokens': 1.5}, {'unknown': 1}, {'events': 1},
                                    {'attempts': 1}, [], {'tokens': float('inf')}])
def test_invalid_minima_refused(minimum):
    node = step('bad', tokens=5, attempts=2)
    node['parameters']['budget_minimum'] = minimum
    with pytest.raises(ValueError):
        narrow_plan(plan(node), {'tokens': 10})


@pytest.mark.parametrize('effects', [None, 'generates_events', ['unknown'], [1], ['executes_native'] * 2])
def test_invalid_effect_declarations_refused(effects):
    node = step('bad', events=10)
    node['parameters']['execution_effects'] = effects
    with pytest.raises(ValueError):
        narrow_plan(plan(node), {'events': 0})


def test_unbounded_dimensions_and_absent_dimensions_stay_unchanged():
    original = plan(step('run', wall_seconds=20, tokens=30, cost_usd=2.5))
    result = narrow_plan(original, {'tokens': None})
    assert result == original


def test_all_summed_dimensions_fit_finite_envelope_and_original_ceilings():
    original = plan(*(step(str(i), wall_seconds=10 + i, tokens=15 + i, broker_calls=5 + i,
                           cost_usd=0.5 + i, core_hours=0.2 + i, children=2, review_rounds=3)
                      for i in range(4)))
    envelope = {'wall_seconds': 14, 'tokens': 21, 'model_calls': 7, 'cost_usd': 3.3,
                'core_hours': 2.1, 'children': 3, 'review_rounds': 5}
    result = narrow_plan(original, envelope)
    for dimension in original['steps'][0]['budget']:
        key = 'model_calls' if dimension == 'broker_calls' else dimension
        assert sum(s['budget'][dimension] for s in result['steps']) <= envelope[key]
        assert all(0 <= s['budget'][dimension] <= before['budget'][dimension]
                   for s, before in zip(result['steps'], original['steps']))
        assert all(math.isfinite(s['budget'][dimension]) for s in result['steps'])


def recast_step(**budget):
    node = step('recast', **budget)
    node.update(operation='lifecycle-routine-recast', outputs=[])
    node['parameters']['task'] = {'max_seconds': 900, 'analysis': 'fictional', 'detector_mode': 'none',
                                  'scientific_value': 17}
    return node


def test_registered_task_ceiling_narrows_with_its_budget_and_passes_actual_admission():
    from ravel.controller.step import operations
    original = recast_step(wall_seconds=900)
    result = narrow_plan(plan(original), {'wall_seconds': 40})['steps'][0]
    assert original['parameters']['task']['max_seconds'] == 900
    assert result['parameters']['task'] == {**original['parameters']['task'], 'max_seconds': 40}
    assert result['budget']['wall_seconds'] == 40
    assert operations.admission_errors(result) == []


def test_frozen_task_ceiling_and_budget_are_not_rewritten():
    original = recast_step(wall_seconds=400)
    result = narrow_plan(plan(original), {'wall_seconds': 400}, frozen_ids=['recast'])
    assert result['steps'][0] == original


def test_task_resource_ceiling_is_never_increased_to_fill_a_larger_budget():
    original = recast_step(wall_seconds=900)
    original['parameters']['task']['max_seconds'] = 20
    result = narrow_plan(plan(original), {'wall_seconds': 40})['steps'][0]
    assert result['parameters']['task']['max_seconds'] == 20


@pytest.mark.parametrize('variant', ['missing-field', 'invalid-field', 'unknown-operation', 'unknown-pointer',
                                    'absent-budget-dimension'])
def test_unresolved_or_unknown_task_ceiling_is_not_created_or_rewritten(variant):
    original = recast_step(wall_seconds=900)
    if variant == 'missing-field':
        del original['parameters']['task']['max_seconds']
    elif variant == 'invalid-field':
        original['parameters']['task']['max_seconds'] = 'unresolved'
    elif variant == 'unknown-operation':
        original['operation'] = 'unknown'
    elif variant == 'unknown-pointer':
        original['operation'] = 'acquire-published'  # its /max_bytes is not a resource mapping
        original['parameters']['task']['max_bytes'] = 900
    else:
        original['budget'] = {'tokens': 900}
    result = narrow_plan(plan(original), {'wall_seconds': 40, 'tokens': 40})['steps'][0]
    assert result['parameters']['task'] == original['parameters']['task']


@pytest.mark.parametrize('operation', ['scoped-likelihood', 'ordinary-study-prepare'])
def test_declared_operation_cost_is_a_rounded_up_resource_minimum(operation):
    from ravel.controller.step import operations
    original = recast_step(wall_seconds=900)
    original['operation'] = operation
    original['parameters']['cost'] = {'unit': 'seconds', 'amount': 30.5}
    narrowed = narrow_plan(plan(original), {'wall_seconds': 31})['steps'][0]
    assert narrowed['budget']['wall_seconds'] == 31
    assert narrowed['parameters']['task']['max_seconds'] == 31
    assert narrowed['parameters']['cost'] == original['parameters']['cost']
    assert operations.admission_errors(narrowed) == []
    with pytest.raises(BudgetInfeasible) as caught:
        narrow_plan(plan(original), {'wall_seconds': 30})
    assert caught.value.evidence == {'dimension': 'wall_seconds', 'required': 31, 'available': 30,
                                     'steps': ['recast']}
    assert 'reduce' in caught.value.remedy and 'increase' in caught.value.remedy


def test_declared_points_do_not_invent_wall_seconds_and_remain_subject_to_admission():
    from ravel.controller.step import operations
    original = recast_step(wall_seconds=900)
    original['parameters']['cost'] = {'unit': 'points', 'amount': 30.5}
    narrowed = narrow_plan(plan(original), {'wall_seconds': 20})['steps'][0]
    assert narrowed['budget']['wall_seconds'] == 20
    assert narrowed['parameters']['task']['max_seconds'] == 20
    assert narrowed['parameters']['cost'] == original['parameters']['cost']
    assert operations.admission_errors(narrowed) == [
        {'code': 'operation_cost_above_ceiling', 'requested': 30.5, 'ceiling': 20, 'unit': 'points'}]


@pytest.mark.parametrize('requested,code', [
    ({'unit': 'seconds', 'amount': 30}, 'operation_cost_invalid'),
    ({'unit': 'points', 'amount': '30'}, 'operation_cost_invalid'),
    ({'unit': 'points', 'amount': 901}, 'operation_cost_above_ceiling'),
])
def test_invalid_operation_cost_retains_original_admission_error(requested, code):
    from ravel.controller.step import operations
    original = recast_step(wall_seconds=900)
    original['parameters']['cost'] = requested
    result = narrow_plan(plan(original), {'wall_seconds': 40})['steps'][0]
    assert result['parameters'] == original['parameters']
    assert code in {error['code'] for error in operations.admission_errors(result)}
