"""Declared child outputs retain their bytes, scope and ordinary adoption checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.controller.routes.manuscript import staged
from ravel.controller.step import graph
from ravel.controller.step.services import StepHold, bound
from ravel.workflow import graph_registry, graph_substrate, ml_executor

from test_p04_support import (FakeStore, context, graphs, install_plan, make_step,  # noqa: F401
                              run_env, run_step, services_installed)


@pytest.fixture
def child(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    run.mkdir()
    store = FakeStore(tmp_path / 'store', run_dir=run)
    checkpoint = object()
    store.checkpointer = lambda: checkpoint
    step = make_step('assembly', kind='subgraph', role=None,
                     outputs=(('outputs/assembly.json', 'table'),),
                     graph={'id': 'manuscript.build', 'instance': {}})
    sha = install_plan(store, [step])
    state = {'meta': {'graph_id': 'controller.step', 'version': 1, 'instance': {'run_id': store.run_id},
                      'scope_root': str(store.path('scope')), 'path': None},
             'step': step, 'acting': deepcopy(step), 'branch': 'subgraph',
             'context': context(store, run, sha, attempt=2), 'preflight': {'graph': step['graph']}}
    calls = []
    raw = b'{"original": 1}\n'
    def invoke(view, config=None):
        binding = staged.active()
        assert binding is not None, 'the child requires its controller service binding'
        assert binding.store is store and binding.step_id == step['id']
        assert binding.output_root == run / 'steps/assembly/attempts/2/outputs'
        assert view['meta']['scope_root'] == str(run)
        assert view['meta']['path'] == graph.nodes.invocation(state['meta'], {'subgraph': 'manuscript.build'})
        assert config['configurable']['thread_id']
        assert config['configurable']['checkpoint_ns']
        target = binding.output_root / 'outputs/assembly.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        calls.append(config)
        return {'results': {'note_assembly': {'status': 'completed'}}, 'status': {}}
    def build(graph_id, ctx, *, checkpointer):
        assert graph_id == 'manuscript.build' and checkpointer is checkpoint
        assert ctx.scope_root == run
        return SimpleNamespace(invoke=invoke)
    monkeypatch.setattr(graph_registry, 'get', lambda ident: {'id': ident, 'version': 1, 'subgraphs': []})
    monkeypatch.setattr(graph_registry, 'check_instance', lambda *args: None)
    monkeypatch.setattr(graph_substrate, 'build', build)
    with bound(store):
        yield SimpleNamespace(state=state, store=store, run=run, raw=raw, calls=calls)


def _adopt(child):
    child.state.update(graph.validate_node(child.state))
    assert child.state['validation']['passed'], child.state['validation']
    child.state.update(graph.adopt(child.state))
    return child.state['adoption']


def test_manuscript_subgraph_adopts_original_declared_bytes(child):
    child.state.update(graph.subgraph(child.state))
    assert staged.active() is None
    assert child.state['child']['results'] == {'note_assembly': {'status': 'completed'}}
    assert child.state['child']['inventory'] == [{'path': 'outputs/assembly.json',
        'sha256': hashlib.sha256(child.raw).hexdigest(), 'bytes': len(child.raw)}]
    adopted = _adopt(child)
    assert adopted['refused'] is None and len(adopted['adopted']) == 1
    child.state.update(graph.checks(child.state))
    assert child.state['checks']['passed']
    row = child.state['checks']['accepted'][0]
    assert row['status'] == 'accepted' and row['attempt'] == 2
    assert (child.run / row['destination']).read_bytes() == child.raw
    assert row['destination'].startswith('steps/assembly.attempt-2.')
    assert [r['record']['status'] for r in child.store.scan('custody')] == ['staged', 'accepted']


def test_subgraph_missing_service_binding_refuses_before_build(child, monkeypatch):
    monkeypatch.delitem(graph.SUBGRAPH_BINDERS, 'manuscript.build')
    with pytest.raises(StepHold) as refused:
        graph.subgraph(child.state)
    assert refused.value.reason == 'subgraph_services_missing'
    assert not child.calls and not child.store.scan('custody')


@pytest.mark.parametrize('defect', ['other_attempt', 'escape', 'changed', 'link', 'store_root', 'missing'])
def test_subgraph_output_scope_and_bytes_are_rechecked(child, defect):
    child.state.update(graph.subgraph(child.state))
    root = Path(child.state['child']['output_root'])
    if defect == 'other_attempt':
        child.state['child']['output_root'] = str(root.parent.parent / '1/outputs')
    elif defect == 'escape':
        child.state['acting']['outputs'][0]['path'] = '../outside.json'
    elif defect == 'changed':
        (root / 'outputs/assembly.json').write_bytes(b'changed')
    elif defect == 'missing':
        (root / 'outputs/assembly.json').unlink()
    elif defect == 'store_root':
        child.state['child']['output_root'] = str(child.store.root)
    else:
        source = root / 'outputs/assembly.json'
        source.unlink()
        source.parent.rmdir()
        source.parent.symlink_to(child.store.root, target_is_directory=True)
    child.state.update(graph.validate_node(child.state))
    if child.state['validation']['passed']:
        child.state.update(graph.adopt(child.state))
        assert child.state['adoption']['refused']
    else:
        assert child.state['validation']['errors']
    assert child.store.scan('custody') == []


def test_subgraph_rechecks_bytes_between_validation_and_adoption(child):
    child.state.update(graph.subgraph(child.state))
    child.state.update(graph.validate_node(child.state))
    assert child.state['validation']['passed']
    root = Path(child.state['child']['output_root'])
    (root / 'outputs/assembly.json').write_bytes(b'changed after validation')
    result = graph.adopt(child.state)['adoption']
    assert result['refused'] == 'adoption_bytes_changed' and result['adopted'] == []
    assert child.store.scan('custody') == []


def test_manuscript_binder_refuses_another_attempt_root(child):
    ctx = {**child.state['context'], 'plan': graph.operations.current_plan(child.store, child.state['context'])}
    with pytest.raises((ValueError, StepHold)):
        with staged.bind_step(child.store, child.state['acting'], ctx,
                              child.run / 'steps/assembly/attempts/1/outputs'):
            pytest.fail('a foreign attempt was bound')


def test_study_binding_is_controller_owned_and_scoped(child):
    assert ml_executor.active() is None
    with graph.SUBGRAPH_BINDERS['ml.study'](child.state, child.run / 'steps/assembly/attempts/2/outputs'):
        binding = ml_executor.active()
        assert binding.store is child.store and binding.run_dir == child.run
        assert binding.context['plan_sha256'] == binding.plan['sha256']
    assert ml_executor.active() is None


def test_child_checkpoint_keeps_parent_thread_and_namespace(child, monkeypatch):
    from langgraph import config
    monkeypatch.setattr(config, 'get_config', lambda: {'configurable': {
        'thread_id': 'parent-thread', 'checkpoint_ns': 'parent:node', 'checkpoint_id': 'parent-snapshot'}})
    graph.subgraph(child.state)
    configured = child.calls[0]['configurable']
    assert configured['thread_id'] == 'parent-thread'
    assert configured['checkpoint_ns'].startswith('parent:node|')
    assert 'checkpoint_id' not in configured


def test_child_checkpoint_is_retained_below_the_parent_in_the_store(child, monkeypatch):
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph

    database = child.store.path('child-checkpoints.sqlite')
    with sqlite3.connect(database, check_same_thread=False) as connection:
        saver = SqliteSaver(connection, serde=graph_substrate.strict_serializer())
        child.store.checkpointer = lambda: saver
        def assemble(state):
            binding = staged.active()
            assert binding is not None and binding.store is child.store
            output = binding.output_root / 'outputs/assembly.json'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(child.raw)
            return {'results': {'assembly': {'status': 'completed'}}}
        def build(graph_id, ctx, *, checkpointer):
            assert checkpointer is saver
            builder = StateGraph(graph.nodes.BaseState)
            builder.add_node('assemble', assemble)
            builder.add_edge(START, 'assemble')
            builder.add_edge('assemble', END)
            return builder.compile(checkpointer=checkpointer)
        monkeypatch.setattr(graph_substrate, 'build', build)
        parent = StateGraph(graph.State)
        parent.add_node('child', graph.subgraph)
        parent.add_edge(START, 'child')
        parent.add_edge('child', END)
        result = parent.compile(checkpointer=saver).invoke(child.state,
            config={'configurable': {'thread_id': 'parent-thread'}})
        assert result['child']['outcome'] == 'ok'
        checkpoints = list(saver.list(None))
        assert {row.config['configurable']['thread_id'] for row in checkpoints} == {'parent-thread'}
        children = [row for row in checkpoints if row.config['configurable']['checkpoint_ns']]
        assert children and any(row.checkpoint['channel_values'].get('results', {}).get('assembly')
                                for row in children)
        assert database.is_file() and not database.is_relative_to(child.run)


def test_inert_manuscript_runs_through_the_governed_step(run_env, graphs, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from ravel.controller import graph as controller
    from ravel.controller.step import custody
    original_build = graph_substrate.build
    checkpoint = InMemorySaver(serde=graph_substrate.strict_serializer())
    run_env.store.checkpointer = lambda: checkpoint
    raw = b'{"assembly": "original"}\n'
    def build(graph_id, ctx, *, checkpointer=None):
        if graph_id != 'manuscript.build':
            return original_build(graph_id, ctx, checkpointer=checkpointer)
        assert checkpointer is checkpoint
        def invoke(view, config=None):
            binding = staged.active()
            assert binding is not None and binding.store is run_env.store
            target = binding.output_root / 'outputs/assembly.json'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            return {'results': {'note_assembly': {'status': 'completed'}}}
        return SimpleNamespace(invoke=invoke)
    monkeypatch.setattr(graph_substrate, 'build', build)
    author = make_step('author', outputs=(('outputs/claim_map.json', 'manuscript:claim-map'),))
    custody.record_outcome(run_env.store, author, 1, 'completed')
    assembly = make_step('assembly', kind='subgraph', role=None, depends_on=['author'],
        outputs=(('outputs/assembly.json', 'table'),),
        graph={'id': 'manuscript.build', 'instance': {'request_id': 'assembly'}},
        budget={key: 1 for key in graph.budget.DIMENSIONS if key != 'model_calls'})
    asked = []
    def approved(store, pins):
        assert store is run_env.store and set(pins) == {'plan_sha256'}
        asked.append(pins)
        return {'id': 'approved', 'subject': {'pins': pins}}, None
    install_plan(run_env.store, [author, assembly])
    original = run_env.store.records('plan')[-1]
    plan = json.loads(run_env.store.get_blob(original['blob']))
    plan['deliverables'] = [{'id': 'D1', 'status': 'mapped', 'step': assembly['id'],
                             'output': 'outputs/assembly.json', 'artifact_kind': 'table', 'claim_kind': 'table'}]
    plan['sha256'] = graph.digest({key: value for key, value in plan.items() if key != 'sha256'})
    run_env.store.append('plan', {'plan_sha256': plan['sha256'],
        'blob': run_env.store.put_blob(json.dumps(plan).encode()), 'source': 'fixture', 'revision': 0})
    from ravel.controller import step as governed
    with controller.services(authority=SimpleNamespace(plan_authority=approved)):
        outcome = governed.run(run_env.store, assembly, context(run_env.store, run_env.run_dir, plan['sha256']))
    assert outcome['status'] == 'completed', json.dumps(outcome, sort_keys=True)
    assert asked
    assert len(outcome['outputs']) == 1
    assert (run_env.run_dir / 'steps/assembly/outputs/assembly.json').read_bytes() == raw
    assert [row['status'] for row in run_env.store.records('custody')] == ['staged', 'accepted']
