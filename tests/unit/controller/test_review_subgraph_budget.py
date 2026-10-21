"""Bound direct review workers at their parent reservation; no model sessions run."""
from copy import deepcopy
import hashlib
import json

import pytest

from ravel.controller import routes
from ravel.controller.step import budget, graph
from ravel.controller.step.services import StepHold
from ravel.workflow import graph_registry, review_points
from ravel.workflow.graphs import review

from test_p04_support import (FakeStore, context, install_plan, make_step, records,
                              run_env, services_installed)  # noqa: F401


def review_root(root):
    inputs = root / 'inputs'
    inputs.mkdir(parents=True)
    raw = json.dumps({'nodes': [], 'edges': [], 'trap_sweep': True,
                      'claims': [{'id': 'value', 'kind': 'agreement', 'absolute_yield': True}]}).encode()
    (inputs / 'request_plan.json').write_bytes(raw)
    (inputs / 'task_contract.json').write_text(json.dumps({
        'agent_layer_epoch': 2, 'delegated': True,
        'request_plan': {'path': 'inputs/request_plan.json', 'sha256': hashlib.sha256(raw).hexdigest()}}))
    return root


def review_step(at='checkin2:value', **share):
    return make_step('operation-review', kind='subgraph', role=None, outputs=(), budget=share,
                     graph={'id': 'review.points', 'instance': {'at': at, 'attempt': 1}},
                     parameters={'ordinary_review': True})


def population(root, at):
    # Include dependent and already satisfied points: pending alone undercounts later rounds.
    return sum(role['count'] for point in review_points.population(review_points._facts(root))
               if (point['when']['at'] == at or (at == 'checkin2' and point['when']['at'].startswith('checkin2:')))
               and point['mode'] not in review.UNDISPATCHED_MODES
               for role in point['roles'])


def finite(amounts):
    return {**amounts, 'tokens': 1000000, 'cost_usd': 100, 'core_hours': 2, 'events': 0}


def test_review_parent_reserves_all_rounds_and_admits_under_a_finite_envelope(tmp_path):
    root = review_root(tmp_path / 'child')
    step = review_step()
    amounts = graph._amounts(step, None, 'subgraph', subgraph_root=root)
    workers = population(root, step['graph']['instance']['at']) * review.MAX_ROUNDS
    assert workers > 0
    assert amounts['wall_seconds'] == workers * 3600
    assert amounts['model_calls'] == workers * 60
    assert amounts['children'] == workers
    assert amounts['core_hours'] == amounts['events'] == 0
    store = FakeStore(tmp_path / 'store')
    reserved = budget.reserve(store, step_id=step['id'], attempt=1, amounts=amounts, ceilings=finite(amounts))
    budget.settle(store, reserved['key'], status='settled', measured=None)
    assert budget.totals(store)['wall_seconds']['charged'] == workers * 3600
    assert budget.totals(store)['model_calls']['charged'] == workers * 60


@pytest.mark.parametrize('dimension', ['wall_seconds', 'model_calls', 'children'])
def test_review_minimum_that_cannot_fit_refuses_typed(tmp_path, dimension):
    root = review_root(tmp_path / 'child')
    amounts = graph._amounts(review_step(), None, 'subgraph', subgraph_root=root)
    ceilings = finite(amounts)
    ceilings[dimension] = amounts[dimension] - 1
    store = FakeStore(tmp_path / 'store')
    with pytest.raises(StepHold) as refused:
        budget.reserve(store, step_id='review', attempt=1, amounts=amounts, ceilings=ceilings)
    assert refused.value.reason == 'budget_exhausted'
    assert refused.value.evidence['refused'][0]['dimension'] == dimension
    assert records(store, budget.RESERVATION) == []


@pytest.mark.parametrize('dimension', ['wall_seconds', 'broker_calls', 'children'])
def test_explicit_share_cannot_undercut_the_derived_review_minimum(tmp_path, dimension):
    root = review_root(tmp_path / 'child')
    with pytest.raises(StepHold) as refused:
        graph._amounts(review_step(**{dimension: 1}), None, 'subgraph', subgraph_root=root)
    assert refused.value.reason == 'seat_budget_infeasible'


def test_reserve_uses_the_same_bound_child_as_dispatch(run_env, monkeypatch):
    root = review_root(run_env.run_dir / 'children' / 'review')
    step = review_step()
    expected = graph._amounts(step, None, 'subgraph', subgraph_root=root)
    run_env.fakes['authority'].budgets.update(finite(expected))
    plan_sha = install_plan(run_env.store, [step])
    seen = []

    def bridge(state, graph_id, node_runner, *, budget_only=False):
        assert budget_only is True
        seen.append((state['acting']['id'], graph_id, node_runner))
        return root, {}

    monkeypatch.setattr(graph, '_runtime_child_context', bridge)
    state = {'step': step, 'context': context(run_env.store, run_env.run_dir, plan_sha)}
    from ravel.controller.step.services import bound
    with bound(run_env.store):
        reserved = graph.reserve(state)['reservation']['amounts']
    assert seen == [('operation-review', 'review.points', None)]
    assert reserved == {**{d: 0 for d in budget.OPTIONAL_DIMENSIONS}, **expected}


@pytest.mark.parametrize('route_id', ['calculation', 'chain', 'scoped', 'study', 'study.site'])
def test_every_review_route_uses_the_registered_reservation(tmp_path, route_id):
    root = review_root(tmp_path / 'child')
    step = next(s for s in routes.find(route_id)['steps'] if s['id'] == 'operation-review')
    assert step['budget'] == {}
    amounts = graph._amounts(step, None, 'subgraph', subgraph_root=root)
    count = population(root, step['graph']['instance']['at']) * review.MAX_ROUNDS
    assert count > 0
    assert amounts['wall_seconds'] == count * 3600
    assert amounts['model_calls'] == count * 60
    assert amounts['core_hours'] == 0


def test_launch_fact_is_generic_and_unknown_graphs_stay_unknown():
    row = deepcopy(graph_registry.get('review.points'))
    row.update(id='synthetic.review')
    row['resources'] = {'starts_launches': False}
    step = review_step()
    step['graph']['id'] = row['id']
    with graph_registry.registered(row):
        assert graph._amounts(step, None, 'subgraph')['core_hours'] == 0
    row['resources']['starts_launches'] = True
    with graph_registry.registered(row):
        assert graph._amounts(step, None, 'subgraph')['core_hours'] is None
    step['graph']['id'] = 'unregistered.review'
    unknown = graph._amounts(step, None, 'subgraph')
    assert unknown['core_hours'] is None and unknown['model_calls'] is None


def test_unavailable_review_population_cannot_be_reserved_as_free(tmp_path):
    with pytest.raises(StepHold) as refused:
        graph._amounts(review_step(), None, 'subgraph', subgraph_root=tmp_path)
    assert refused.value.reason == 'subgraph_budget_unavailable'


def test_research_and_manuscript_reservations_are_unchanged():
    step = review_step(wall_seconds=1800)
    step['graph']['id'] = 'research.loop'
    assert graph._amounts(step, None, 'subgraph') == {
        'wall_seconds': 1800, 'model_calls': 0, 'tokens': None, 'cost_usd': None,
        'core_hours': 0, 'events': 0, 'children': 1}
    build = next(s for s in routes.find('manuscript')['steps'] if s['id'] == 'm02-build')
    assert graph._amounts(build, None, 'subgraph') == {
        'wall_seconds': 7200, 'model_calls': 400, 'tokens': 800000, 'cost_usd': None,
        'core_hours': None, 'events': 0, 'children': 1}


def test_two_declared_rounds_do_not_narrow_the_six_round_admission_bound(tmp_path):
    root = review_root(tmp_path / 'child')
    roles = {role['role']: role['count'] for point in review_points.derive(review_points._facts(root))
             if point['when']['at'] == 'checkin2:value' for role in point['roles']}
    assert roles == {'physics-critic': 1, 'skeptical-verifier': 1, 'physics-decider': 1,
                     'normalization-auditor': 1, 'discrepancy-attributor': 1, 'trap-auditor': 1}
    amounts = graph._amounts(review_step(), None, 'subgraph', subgraph_root=root)
    assert population(root, 'checkin2:value') == 10
    assert amounts['wall_seconds'] == 216000 and amounts['model_calls'] == 3600
    ceilings = {**finite(amounts), 'wall_seconds': 3600, 'review_rounds': 2}
    with pytest.raises(StepHold) as refused:
        budget.reserve(FakeStore(tmp_path / 'store'), step_id='review', attempt=1,
                       amounts=amounts, ceilings=ceilings)
    assert refused.value.reason == 'budget_exhausted'
    literal = next(s for s in routes.find('study.site')['steps'] if s['id'] == 'operation-review')
    assert literal['graph']['instance']['at'] == 'checkin2'
    assert population(root, 'checkin2') == population(root, 'checkin2:value')


def usage_items(store, root, *, attempt=1, count=2):
    from ravel.controller.step.subgraph_usage import Tracker
    tracker = Tracker(store, review_step(), attempt, root)
    items = review.derive(root, 'checkin2:value', 0)['items'][:count]
    assert len(items) == count
    review.write_packets(root, items)
    descriptors = [{'spec': review.worker_spec(root, item, invocation=tracker.binding),
                    'graph': {'id': review.ITEM, 'version': graph_registry.get(review.ITEM)['version']}} for item in items]
    tracker.record(descriptors)
    return tracker, items, descriptors


def finish_item(root, item, descriptor, *, turns=2, reported=True):
    from ravel.workflow import agent_worker, broker
    worker = descriptor['spec']
    identity = broker.digest({'worker_spec_sha256': broker.digest(worker), 'kind': 'worker'})
    agent_worker.materialize(root, worker, graph=descriptor['graph'], packet=review._projection(root, item),
        effect={'identity_sha256': identity, 'epoch': {'cancellation': 0},
                'downstream': str(root / 'downstream' / (worker['node_id'] + '.json'))})
    return agent_worker.finish(root, worker, final=None, execution={'exit_status': 1, 'usage': {
        'reported': reported, 'turns': turns, 'input_tokens': 5, 'output_tokens': 7, 'cost_usd': 0.1}})


def test_subgraph_usage_sums_authenticated_own_item_receipts(tmp_path):
    from ravel.controller.step import subgraph_usage
    root = review_root(tmp_path / 'child')
    store = FakeStore(tmp_path / 'store')
    tracker, items, descriptors = usage_items(store, root)
    receipts = [finish_item(root, item, row, turns=i+2) for i, (item, row) in enumerate(zip(items, descriptors))]
    tracker.finish(completed=True)
    measured, source = subgraph_usage.measurement(store, review_step(), 1)
    assert source and measured['wall_seconds'] == pytest.approx(sum(r['wall_seconds'] for r in receipts))
    assert measured['model_calls'] == 5 and measured['tokens'] == 24
    assert measured['cost_usd'] == pytest.approx(0.2)


def test_missing_receipt_charges_just_that_items_declared_ceiling(tmp_path):
    from ravel.controller.step import subgraph_usage
    root = review_root(tmp_path / 'child')
    store = FakeStore(tmp_path / 'store')
    tracker, items, descriptors = usage_items(store, root)
    receipt = finish_item(root, items[0], descriptors[0], turns=3)
    tracker.finish(completed=True)
    measured, _ = subgraph_usage.measurement(store, review_step(), 1)
    assert measured['wall_seconds'] == pytest.approx(receipt['wall_seconds'] + 3600)
    assert measured['model_calls'] == 3 + 60
    assert measured['tokens'] is None and measured['cost_usd'] is None


def test_missing_usage_preserves_its_item_ceiling(tmp_path):
    from ravel.controller.step import subgraph_usage
    root = review_root(tmp_path / 'child')
    store = FakeStore(tmp_path / 'store')
    tracker, items, descriptors = usage_items(store, root, count=1)
    receipt = finish_item(root, items[0], descriptors[0], turns=None, reported=False)
    tracker.finish(completed=True)
    measured, _ = subgraph_usage.measurement(store, review_step(), 1)
    assert measured['wall_seconds'] == receipt['wall_seconds']
    assert measured['model_calls'] == 60 and measured['tokens'] is None


def test_other_parent_attempts_receipts_cannot_refund_this_attempt(tmp_path):
    from ravel.controller.step import subgraph_usage
    root = review_root(tmp_path / 'child')
    store = FakeStore(tmp_path / 'store')
    first, items, descriptors = usage_items(store, root, count=1)
    finish_item(root, items[0], descriptors[0], turns=1)
    first.finish(completed=True)
    second, _, next_descriptors = usage_items(store, root, attempt=2, count=1)
    assert next_descriptors[0]['spec']['node_id'] != descriptors[0]['spec']['node_id']
    second.finish(completed=True)
    measured, _ = subgraph_usage.measurement(store, review_step(), 2)
    assert measured['wall_seconds'] == 3600 and measured['model_calls'] == 60


@pytest.mark.parametrize('field', ['usage', 'subject'])
def test_tampered_worker_usage_cannot_refund_the_parent(tmp_path, field):
    from ravel.controller.step import subgraph_usage
    from ravel.workflow import agent_worker
    root = review_root(tmp_path / 'child')
    store = FakeStore(tmp_path / 'store')
    tracker, items, descriptors = usage_items(store, root, count=1)
    receipt = finish_item(root, items[0], descriptors[0])
    path = agent_worker.workspace(root, receipt['node_id'], receipt['attempt']) / 'receipt.json'
    if field == 'usage':
        receipt['wall_seconds'] = 0
        receipt['usage']['turns'] = 0
    else:
        receipt['review_subject']['sha256'] = 'f' * 64
    path.write_text(json.dumps(receipt))
    tracker.finish(completed=True)
    measured, _ = subgraph_usage.measurement(store, review_step(), 1)
    assert measured['wall_seconds'] == 3600 and measured['model_calls'] == 60


def test_observe_uses_protected_item_measurements_and_leaves_later_budget(run_env):
    root = review_root(run_env.run_dir / 'children' / 'usage')
    step = review_step()
    tracker, items, descriptors = usage_items(run_env.store, root, count=1)
    receipt = finish_item(root, items[0], descriptors[0], turns=2)
    tracker.finish(completed=True)
    amounts = graph._amounts(step, None, 'subgraph', subgraph_root=root)
    ceilings = {**finite(amounts), 'children': amounts['children'] + 1}
    reservation = budget.reserve(run_env.store, step_id=step['id'], attempt=1,
                                 amounts=amounts, ceilings=ceilings)
    state = {'step': step, 'acting': step, 'branch': 'subgraph', 'reservation': reservation,
             'context': context(run_env.store, run_env.run_dir, install_plan(run_env.store, [step])),
             'child': {'outcome': 'ok', 'measured': {'wall_seconds': 0, 'model_calls': 0}}}
    from ravel.controller.step.services import bound
    with bound(run_env.store):
        graph.observe(state)
    totals = budget.totals(run_env.store)
    assert totals['wall_seconds']['charged'] == receipt['wall_seconds']
    assert totals['model_calls']['charged'] == 2
    assert totals['children']['charged'] == amounts['children']  # M17's child counter is not refunded.
    later = {**{d: 0 for d in budget.DIMENSIONS}, 'wall_seconds': 1, 'model_calls': 1, 'children': 1}
    budget.reserve(run_env.store, step_id='later', attempt=1, amounts=later, ceilings=ceilings)


@pytest.mark.parametrize('at', ['checkin2:C1', 'checkin2'])
def test_real_review_graph_records_its_items_before_dispatch(tmp_path, monkeypatch, at):
    from rdj_fixtures import Run
    from test_review_points_graph import Workers, plan, run_review
    from ravel.controller.step import subgraph_usage
    from ravel.workflow import agent_worker, graph_substrate
    root = Run(tmp_path / 'child', snapshot=False).root
    plan(root, delegated=True)
    step = review_step(at)
    store = FakeStore(tmp_path / 'store')
    tracker = subgraph_usage.Tracker(store, step, 1, root)
    original = graph_substrate._context

    def owned_context(scope_root, graph_id, instance):
        ctx = original(scope_root, graph_id, instance)
        if graph_id == review.POINTS:
            ctx.extras.update(worker_usage_binding=tracker.binding, record_worker_items=tracker.record)
        return ctx

    monkeypatch.setattr(graph_substrate, '_context', owned_context)
    workers = Workers(root)
    observation = run_review(root, monkeypatch, workers, at=at)
    assert observation['terminal'] is None and not observation['next']
    tracker.finish(completed=True)
    dispatched = records(store, subgraph_usage.DISPATCH)
    assert len(dispatched) == len(workers.calls) == 10
    receipts = [agent_worker.load_receipt(root, r['worker']['node_id'], r['worker']['attempt']) for r in dispatched]
    measured, _ = subgraph_usage.measurement(store, step, 1)
    assert measured['wall_seconds'] == pytest.approx(sum(r['wall_seconds'] for r in receipts))
    assert len(records(store, subgraph_usage.OBSERVATION)) == 10


def test_failed_subgraph_with_missing_receipt_does_not_release_started_work(run_env):
    from ravel.controller.step.services import bound
    root = review_root(run_env.run_dir / 'children' / 'missing')
    step = review_step()
    tracker, _, _ = usage_items(run_env.store, root, count=1)
    tracker.finish(completed=False)
    amounts = graph._amounts(step, None, 'subgraph', subgraph_root=root)
    reservation = budget.reserve(run_env.store, step_id=step['id'], attempt=1,
                                 amounts=amounts, ceilings=finite(amounts))
    state = {'step': step, 'acting': step, 'branch': 'subgraph', 'reservation': reservation,
             'context': context(run_env.store, run_env.run_dir, install_plan(run_env.store, [step]))}
    with bound(run_env.store):
        graph._record_hold(state, 'inert_worker_interrupted', 'the item has no authenticated receipt')
    assert budget.totals(run_env.store)['wall_seconds']['charged'] == 3600
    assert budget.totals(run_env.store)['model_calls']['charged'] == 60
