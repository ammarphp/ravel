"""Read-only review seats publish their declared findings under the effect guard."""
from copy import deepcopy

import pytest

from test_p04_support import graphs, inert_worker, run_env, services_installed  # noqa: F401

from ravel.controller import graph
from ravel.controller.routes import inspect


def seat():
    return graph._seat_step('plan-critic', purpose='plan', plan={'sha256': 'a' * 64})


@pytest.mark.parametrize('route', inspect.READ_ONLY_ROUTES)
def test_controller_plan_review_keeps_its_declared_artifact(route):
    step = seat()
    assert inspect.guard(step, {'route': {'id': route}}) == []


@pytest.mark.parametrize('change', ['kind', 'role', 'output', 'operation', 'launch', 'rung', 'budget'])
def test_scientific_effects_and_unbound_findings_remain_refused(change):
    step = deepcopy(seat())
    if change == 'kind': step['kind'] = 'synthesize'
    elif change == 'role': step['role'] = 'baseline-producer'
    elif change == 'output': step['outputs'][0]['kind'] = 'model'
    elif change == 'operation': step['operation'] = 'literal-calculation'
    elif change == 'launch': step['parameters']['launch'] = {'argv': ['/bin/true']}
    elif change == 'rung': step['rung'] = 'full'
    else: step['budget']['events'] = 1
    assert inspect.guard(step, {'route': {'id': 'inspect'}})


def test_findings_stay_review_evidence_instead_of_a_scientific_deliverable():
    step = seat()
    plan = {'route': {'id': 'inspect'}, 'steps': [step], 'deliverables': [
        {'id': 'result', 'status': 'mapped', 'step': step['id'], 'artifact_kind': 'review-findings'}]}
    assert any(row['code'] == 'scientific_deliverable' for row in inspect.plan_effects(plan))


@pytest.mark.parametrize('route', inspect.READ_ONLY_ROUTES)
def test_read_only_review_reaches_governed_worker_dispatch(run_env, inert_worker, graphs, route):
    from ravel.controller import step as governed
    from test_p04_support import context, install_plan, make_step, records
    step = make_step('review', kind='review', role='plan-critic',
        outputs=(('outputs/findings.json', 'review-findings'),), parameters={'seat_kind': 'review'})
    pin = install_plan(run_env.store, [step])
    outcome = governed.run(run_env.store, step, context(run_env.store, run_env.run_dir, pin, route=route))
    dispatched = records(run_env.store, 'step-dispatch')
    assert dispatched, outcome
    assert outcome.get('reason') != 'effect_output'
    assert records(run_env.store, 'step-observation')
