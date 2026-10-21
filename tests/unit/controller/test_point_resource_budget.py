"""Prepared launch resources are independent of a route's template population."""
from copy import deepcopy
import sys

import pytest

from ravel.controller.routes.analysis.execution import bind_launches
from ravel.controller.step import budget, graph, services
from ravel.controller.step.services import StepHold
from test_p04_support import (context, install_plan, make_step, records, run_env,  # noqa: F401
                              services_installed)


def prepared_step(*, generates=False, ceiling=90, identifier='point.first'):
    node = make_step(identifier, kind='operate', role='analysis-author', operation='analysis-lifecycle',
                     rung='scan', budget={'wall_seconds': 21600, 'events': 50000},
                     parameters={'task': {'max_seconds': ceiling}})
    source = {'launches': {identifier: {'argv': [sys.executable, '-c', 'pass', '@input:inputs/data']}},
              'launch_inputs': {identifier: ['inputs/data']},
              'launch_effects': {identifier: ['executes_native', *(['generates_events'] if generates else [])]}}
    return bind_launches({'steps': [node]}, source,
                         [{'artifact': 'inputs/data', 'sha256': 'a' * 64}])['steps'][0]


def reserve_state(env, node):
    pin = install_plan(env.store, [node])
    env.fakes['authority'].budgets.update(wall_seconds=3600, events=0, core_hours=2)
    return {'step': node, 'context': context(env.store, env.run_dir, pin)}


@pytest.mark.parametrize('identifier', ['point.first', 'ordinary.second'])
def test_supplied_launch_discards_template_generation_and_counts_declared_files(run_env, identifier):
    node = prepared_step(identifier=identifier)
    before = deepcopy(node)
    state = reserve_state(run_env, node)
    with services.bound(run_env.store):
        update = graph.reserve(state)
    requested = update['reservation']['amounts']
    assert requested['events'] == 0
    assert requested['input_files'] == 1
    assert requested['wall_seconds'] == 90
    assert requested['core_hours'] == 90 / 3600
    assert node == before
    assert records(run_env.store, budget.RESERVATION)[0]['basis']['upper_bound']['basis'] \
        == 'declared-operation-ceiling'
    assert not [row for row in run_env.fakes['authority'].calls if row[0] == 'request']


@pytest.mark.parametrize('dimension,ceiling', [('wall_seconds', 3601), ('events', 90)])
def test_actual_overage_still_refuses_before_reservation(run_env, dimension, ceiling):
    node = prepared_step(generates=dimension == 'events', ceiling=ceiling)
    state = reserve_state(run_env, node)
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason == 'budget_exhausted'
    assert {row['dimension'] for row in held.value.evidence['refused']} == {dimension}
    assert records(run_env.store, budget.RESERVATION) == []


def test_generation_with_input_volume_still_needs_its_event_population():
    node = prepared_step(generates=True)
    node['budget'].pop('events')
    node['budget']['input_files'] = 1
    assert graph._amounts(node, None, 'launch')['events'] is None


@pytest.mark.parametrize('volume', [{'input_files': 3}, {'input_bytes': 128}])
def test_explicit_input_volume_is_retained(volume):
    node = prepared_step()
    node['budget'].update(volume)
    requested = graph._amounts(node, None, 'launch')
    assert requested['events'] == 0
    for dimension, amount in volume.items():
        assert requested[dimension] == amount


def test_undeclared_effects_do_not_erase_generation():
    node = prepared_step()
    node['parameters'].pop('execution_effects')
    assert graph._amounts(node, None, 'launch')['events'] == 50000


def test_input_file_declaration_cannot_hide_the_launch_read_population():
    node = prepared_step()
    node['budget']['input_files'] = 0
    assert graph._amounts(node, None, 'launch')['input_files'] == 1


@pytest.mark.parametrize('effects', [None, 'executes_native', ['executes_native'] * 2, ['unknown'], [1]])
def test_invalid_execution_effects_cannot_remove_generation(effects):
    node = prepared_step()
    node['parameters']['execution_effects'] = effects
    with pytest.raises(StepHold) as held:
        graph._amounts(node, None, 'launch')
    assert held.value.reason == 'operation_effect_undeclared'
