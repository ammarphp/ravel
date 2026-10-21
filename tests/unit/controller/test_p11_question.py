"""The question entry uses the registered judgment graph and protected checkpoints."""
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ravel.workflow import graph_nodes, graph_registry, research_controller as controller, state_io
from langgraph.graph import END, START, StateGraph

from p11_fakes import FakeRunStore
from test_p11_route import prepared_route
from ravel.controller.routes import research


class QuestionState(graph_nodes.BaseState, total=False):
    request: dict
    plan: Any
    context: dict
    results: dict


def register_question(monkeypatch, tmp_path, result, seen):
    """P08's fixture builder uses its actual request/plan/context binding view.

    The fixture row stands in for the installed ``judgment.plan`` row (its registration fragment included)
    for this block only, with that row's field set.
    """
    installed = graph_registry.get('judgment.plan')
    row = {'id': 'judgment.plan', 'version': 1, 'kernel_version': 1,
        'module': 'ravel.workflow.graph_substrate', 'builder': 'selftest', 'scope': 'run',
        'instance_keys': ['run_id'], 'roles': [], 'gates': {}, 'subgraphs': [],
        'interrupts': [], 'structure_sha256': graph_registry.PIN, 'owner': 'graph-substrate'}
    assert set(row) == set(installed) and row['version'] == installed['version']
    assert row['instance_keys'] == installed['instance_keys'] and row['scope'] == installed['scope']

    def builder(ctx):
        seen['build_context'] = ctx
        graph = StateGraph(QuestionState)

        def answer(state):
            seen['input'] = deepcopy(state)
            active = controller.active()
            assert active is not None and active[0].run_id == ctx.instance['run_id']
            return {'results': {'plan': deepcopy(result)}}

        graph_nodes.add(graph, 'answer', graph_nodes.Node('guard', answer), graph_id=row['id'])
        graph_nodes.add(graph, 'decision_turn', graph_nodes.decision_turn('p11-question'), graph_id=row['id'])
        graph_nodes.add(graph, 'reconcile', graph_nodes.reconcile_node(), graph_id=row['id'])
        graph_nodes.add(graph, 'hold', graph_nodes.hold('p11-question'), graph_id=row['id'])
        graph.add_edge(START, 'answer')
        graph.add_edge('answer', END)
        return graph

    return graph_registry.registered(row, builders={'judgment.plan': builder}, replace=True)


def test_question_graph_adopts_real_bound_research_plan_and_protected_checkpoint(tmp_path, monkeypatch):
    plan, context, _ = prepared_route(tmp_path / 'run')
    expected = research.bind(plan, context)
    store = FakeRunStore('question-control', root=tmp_path / 'protected-store')
    request = {'original_question': 'Compare the original supplied laws and retain every deliverable.'}
    before = deepcopy((request, context))
    seen = {}
    with register_question(monkeypatch, tmp_path, expected, seen):
        adopted = controller.question_plan(store, request, context)
    assert adopted == expected
    assert adopted['id'] == 'research' and adopted['match']['row'] == 5
    campaign = next(row for row in adopted['steps'] if row['id'] == 'campaign')
    assert campaign['graph']['id'] == 'research.loop'
    assert campaign['parameters']['research_request'] == expected['parameters']['research_request']
    assert (request, context) == before
    assert controller.active() is None
    shown = seen['input']
    assert shown['request'] == request and shown['plan'] is None
    assert shown['context'] == {**context, 'run_id': store.run_id}
    scope = store.path('research-question')
    assert shown['meta'] == {'graph_id': 'judgment.plan', 'version': 1,
                             'scope_root': str(scope), 'instance': {'run_id': store.run_id}, 'path': []}
    assert seen['build_context'].scope_root == scope
    assert seen['build_context'].graph_id == 'judgment.plan'
    assert seen['build_context'].instance == {'run_id': store.run_id}
    config = {'configurable': {'thread_id': store.run_id + ':research-question'}}
    checkpoint = store.checkpointer().get_tuple(config)
    assert checkpoint is not None
    assert checkpoint.checkpoint['channel_values']['results']['plan'] == expected
    records = store.scan('research-question-plan')
    assert len(records) == 1
    assert records[0]['record'] == {'request_sha256': controller.cycle.ce.digest(request), 'plan': expected}
    assert not scope.is_relative_to(Path(context['run_dir']))


@pytest.mark.parametrize('result', [None, [], 'prose plan', {}, {'steps': []}, {'steps': 'corrupt'},
                                   {'steps': [None]}, {'steps': [{'kind': 'route'}]}])
def test_question_graph_refuses_empty_or_corrupt_results_without_adoption(tmp_path, monkeypatch, result):
    store = FakeRunStore('invalid-question', root=tmp_path / 'protected-store')
    seen = {}
    with register_question(monkeypatch, tmp_path, result, seen):
        with pytest.raises(ValueError, match='typed research plan'):
            controller.question_plan(store, {'question': 'Retain original scope'}, {'run_dir': str(tmp_path / 'run')})
    assert 'input' in seen  # Refusal follows a genuine registered Graph execution.
    assert store.scan('research-question-plan') == []
    assert controller.active() is None


def canonical(plan):
    """The controller plan seal: UTF-8 canonical JSON without escapes, as the plan compiler writes it."""
    import hashlib
    import json
    body = {k: v for k, v in plan.items() if k != 'sha256'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def test_non_ascii_plan_keeps_the_controller_canonical_seal_through_binding_and_question(tmp_path, monkeypatch):
    plan, context, _ = prepared_route(tmp_path / 'run')
    plan['checkins'][0]['sections'].append('original bound σ ≥ 2')
    bound = research.bind(plan, context)
    assert 'original bound σ ≥ 2' in bound['checkins'][0]['sections'] and bound['sha256'] == canonical(bound)
    store = FakeRunStore('unicode-question', root=tmp_path / 'protected-store')
    with register_question(monkeypatch, tmp_path, bound, {}):
        assert controller.question_plan(store, {'original_question': 'Bound σ.'}, context) == bound
    forged = {**bound, 'sha256': controller.cycle.ce.digest({k: v for k, v in bound.items() if k != 'sha256'})}
    assert forged['sha256'] != bound['sha256']
    with register_question(monkeypatch, tmp_path, forged, {}):
        with pytest.raises(ValueError, match='sealed typed research plan'):
            controller.question_plan(store, {'original_question': 'Bound σ.'}, context)
    assert len(store.scan('research-question-plan')) == 1
