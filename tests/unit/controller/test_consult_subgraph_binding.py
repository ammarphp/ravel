"""Controller-bound consultation preserves advisory custody and worker budgets."""
from copy import deepcopy

import pytest

from ravel.controller.step import graph
from ravel.controller.step.services import StepHold, bound
from ravel.workflow import agent_worker, consults, graph_substrate
from test_consults import execute_consult, request, worker_spec
from test_p04_support import FakeStore, context, install_plan, make_step


def state_for(tmp_path, pin):
    from langgraph.checkpoint.memory import InMemorySaver
    run = tmp_path / 'run'
    store = FakeStore(tmp_path / 'store', run_dir=run)
    saver = InMemorySaver()
    store.checkpointer = lambda: saver
    step = make_step('advice', kind='subgraph', role=None, outputs=(),
                     graph={'id': 'consult.case', 'instance': {'request': pin}})
    sha = install_plan(store, [step])
    return store, {'meta': {'graph_id': 'controller.step', 'version': 1,
                            'instance': {'run_id': store.run_id}, 'scope_root': str(store.path('scope'))},
                   'step': step, 'acting': deepcopy(step), 'branch': 'subgraph',
                   'context': context(store, run, sha), 'preflight': {'graph': step['graph']}}


def test_real_consult_dispatch_returns_original_advisory_receipt_and_reuses_it(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    run.mkdir()
    children = []

    def through_step(scope, identity, instance):
        assert scope == run and identity == 'consult.case'
        store, state = state_for(tmp_path, instance['request'])
        with bound(store):
            first = graph.subgraph(state)['child']
            second = graph.subgraph(state)['child']
        assert first['outcome'] == second['outcome'] == 'ok'
        assert first['results'] == second['results']
        assert len(agent_worker.status(run)['workers']) == 1
        children.append((store, first))
        return first

    monkeypatch.setattr(graph_substrate, 'run', through_step)
    result, pin = execute_consult(run, monkeypatch)
    assert result['results']['consult_record']['sha256']
    next_spec = consults.next_turn_spec(run, worker_spec(attempt=2), request=pin)
    assert any(item['as'].startswith('inputs/consults/') for item in next_spec['inputs'])
    assert len(children[0][0].scan('step-subgraph')) == 2


def test_consult_reservation_covers_its_pinned_worker(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    pin = request(run)
    store, state = state_for(tmp_path, pin)
    with bound(store):
        child, _ = graph._runtime_child_context(state, 'consult.case', None)
        amounts = graph._amounts(state['acting'], None, 'subgraph', subgraph_root=child)
    budgets = consults.load_request(run, pin)['budgets']
    assert amounts['model_calls'] == budgets['max_turns']
    assert amounts['wall_seconds'] == budgets['max_wall_seconds']
    assert amounts['core_hours'] == amounts['events'] == 0
    state['acting']['budget'] = {'broker_calls': 0}
    with pytest.raises(StepHold, match='seat_budget_infeasible'):
        graph._amounts(state['acting'], None, 'subgraph', subgraph_root=child)


def test_changed_consult_request_refuses_before_dispatch(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    run.mkdir()
    pin = request(run)
    store, state = state_for(tmp_path, pin)
    (run / pin['path']).write_text('{}')
    monkeypatch.setattr(agent_worker, 'dispatch', lambda *a, **kw: pytest.fail('changed request dispatched'))
    with bound(store), pytest.raises((StepHold, ValueError), match='consult.*(pin|request)'):
        graph.subgraph(state)
