"""Intake orchestration reserves its existing finite planner envelope before direct calls."""
from copy import deepcopy

import pytest

from ravel.controller import routes
from ravel.controller.step import budget, graph, services
from ravel.controller.step.services import StepHold
from ravel.workflow import graph_registry
from test_p04_reserve import _reserve_state
from test_p04_support import run_env, services_installed  # noqa: F401


def planner_step():
    return deepcopy(next(s for s in routes.find('calculation')['steps']
                         if (s.get('graph') or {}).get('id') == 'intake.plan'))


def test_installed_planner_has_finite_parent_resources(run_env):
    step = planner_step()
    resources = graph_registry.get('intake.plan').get('resources') or {}
    assert resources['budget_builder'] == 'reservation_budget'
    amounts = graph._amounts(step, None, 'subgraph', subgraph_root=run_env.run_dir)
    assert amounts['wall_seconds'] == 3600 and amounts['model_calls'] == 2
    assert amounts['children'] == 1 and amounts['events'] == amounts['core_hours'] == 0
    with services.bound(run_env.store):
        result = graph.reserve(_reserve_state(run_env, step))
    assert result['reservation']['amounts'] == {**{d: 0 for d in budget.OPTIONAL_DIMENSIONS}, **amounts}


@pytest.mark.parametrize('dimension', ['wall_seconds', 'model_calls', 'children'])
def test_declared_share_preserves_the_direct_call_minimum(run_env, dimension):
    step = deepcopy(planner_step())
    step['budget'][dimension] = 0
    with pytest.raises(StepHold) as held:
        graph._amounts(step, None, 'subgraph', subgraph_root=run_env.run_dir)
    assert held.value.reason == 'seat_budget_infeasible'


def test_resource_binding_preserves_the_charged_runner_requirement(run_env):
    state = {'acting': planner_step(), 'context': {'run_dir': str(run_env.run_dir)}}
    root, bindings = graph._runtime_child_context(state, 'intake.plan', None, budget_only=True)
    assert root == run_env.run_dir and bindings == {}
    with pytest.raises(StepHold) as held:
        graph._runtime_child_context(state, 'intake.plan', None)
    assert held.value.reason == 'intake_runner_unavailable'


@pytest.mark.parametrize('path', ['../foreign', '/foreign'])
def test_planner_resources_keep_the_bound_root(run_env, path):
    step = planner_step()
    step['graph']['instance']['graph_root'] = path
    with pytest.raises(StepHold) as held:
        graph._amounts(step, None, 'subgraph', subgraph_root=run_env.run_dir)
    assert held.value.reason == 'subgraph_budget_unavailable'
