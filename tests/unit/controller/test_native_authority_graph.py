"""Native authority interrupt/gate wiring, with strict controller-interface declarations."""
from copy import deepcopy
import json
from pathlib import Path
import time
from types import SimpleNamespace
import pytest

from ravel.controller.step import graph, native_authority, launch_gate
from ravel.controller.step.services import StepHold


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    step = {'id': 'native', 'kind': 'operate', 'rung': 'full', 'consequence_class': 'R3'}
    context = {'run_id': 'native-runtime', 'run_dir': str(tmp_path), 'attempt': 2, 'plan_sha256': 'a' * 64}
    preflight = {'plan_sha256': 'a' * 64, 'launch_sha256': 'b' * 64,
                 'native_preflight': 'protected-preflight', 'budget': {'events': 10}}
    state = {'step': step, 'acting': step, 'context': context, 'preflight': preflight, 'branch': 'launch',
             'reservation': {'amounts': {'events': 10}}}
    store = SimpleNamespace(run_id='native-runtime')
    action = launch_gate.action(step, context, preflight, 'protected-preflight')
    monkeypatch.setattr(graph, '_store', lambda value: store)
    calls, faults = [], {}
    def authorize(actual, ctx, acting, amounts, *, stage=None):
        assert actual is store and ctx == context and acting == step
        assert amounts == state['reservation']['amounts'] and stage == preflight.get('stage')
        calls.append('authorize')
        if faults.get('authority'):
            raise StepHold('authority_refused', 'authority was withdrawn')
    monkeypatch.setattr(graph, '_authorize', authorize)
    answer = {'action': action, 'class': 'R3', 'authority': 'verified-operator'}
    def prepare(actual, acting, ctx, prepared):
        assert actual is store and acting == step and prepared == preflight
        assert ctx['attempt'] == 2 and ctx['plan_sha256'] == preflight['plan_sha256']
        calls.append('prepare')
        return deepcopy(answer)
    monkeypatch.setattr(native_authority, 'prepare', prepare)
    return SimpleNamespace(state=state, action=action, answer=answer, calls=calls, faults=faults)


def pending():
    return {'kind': 'r3_action', 'request': 'protected-request', 'since_ns': time.time_ns(),
            'waited_seconds': 0, 'wait_bound_seconds': 60}


def test_real_native_interrupt_resume_only_polls(runtime):
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    runtime.answer.pop('authority'); runtime.answer['pending'] = pending()
    builder = StateGraph(dict); builder.add_node('point', graph.native_authority_point)
    builder.add_edge(START, 'point'); builder.add_edge('point', END)
    compiled = builder.compile(checkpointer=InMemorySaver())
    config = {'configurable': {'thread_id': 'native-poll'}}
    first = compiled.invoke(runtime.state, config)
    payload = first['__interrupt__'][0].value
    assert payload['approval_from_resume'] is False and payload['authority_kind'] == 'r3_action'
    assert 'ravel operator answer' in payload['operator_answer']['command']
    again = compiled.invoke(Command(resume={'kind': 'authority_poll', 'note': 'admit'}), config)
    assert again['__interrupt__'] and len(runtime.calls) >= 2


def test_lower_class_point_passes_exact_prepare_result_without_extra_authority(runtime):
    runtime.answer.pop('authority'); runtime.answer['class'] = 'R2'
    result = graph.native_authority_point(runtime.state)
    assert result['native_authority'] == runtime.answer and runtime.calls == ['prepare']


@pytest.mark.parametrize('fault', ['malformed', 'expired', 'poll_bound'])
def test_pending_invalid_or_expired_never_reaches_effect(runtime, monkeypatch, fault):
    import langgraph.types
    runtime.answer['pending'] = pending()
    if fault == 'malformed': runtime.answer['pending']['since_ns'] = True
    if fault == 'expired':
        runtime.state['context']['unattended'] = True
        runtime.answer['pending']['waited_seconds'] = 61
    pauses = []
    monkeypatch.setattr(langgraph.types, 'interrupt', lambda *a, **k: pauses.append(a))
    with pytest.raises(StepHold) as held: graph.native_authority_point(runtime.state)
    assert held.value.reason == 'native_authority_refused'
    assert len(pauses) == (64 if fault == 'poll_bound' else 0)


@pytest.mark.parametrize('fault', [None, 'changed', 'missing', 'refused', 'authority'])
def test_native_gate_requires_exact_prepared_action_and_real_launch_decision(runtime, monkeypatch, fault):
    n = runtime; n.state['native_authority'] = deepcopy(n.answer)
    if fault == 'changed': n.state['native_authority']['action']['view_pins']['attempt'] = '99'
    if fault == 'missing': n.state.pop('native_authority')
    if fault == 'authority': n.faults['authority'] = True
    def decide(state):
        n.calls.append('ledger.decide')
        if fault == 'refused': raise graph.LaunchNotStarted('native_launch_gate_refused', 'withdrawn',
            evidence={'record': 'protected-refusal'})
        return {'record': 'protected-decision'}
    monkeypatch.setattr(graph, '_native_launch_decision', decide)
    result = graph.native_authority_gate(n.state)
    gate = result['gates']['native_authority']
    assert bool(gate['errors']) == (fault is not None)
    if fault is None:
        assert gate['action_digest'] == n.action['digest'] and gate['record'] == 'protected-decision'
        assert n.calls == ['authorize', 'ledger.decide']
    elif fault in ('changed', 'missing'): assert n.calls == []
    elif fault == 'authority': assert n.calls == ['authorize'] and gate['record'] is None
    elif fault == 'refused':
        assert n.calls == ['authorize', 'ledger.decide'] and gate['record'] == 'protected-refusal'


def test_launch_routes_through_native_authority_and_consults_still_precede_it():
    assert graph.after_preflight({'branch': 'launch', 'preflight': {}}) == 'native_authority'
    assert graph.after_preflight({'branch': 'launch', 'preflight': {'consults_pending': ['critic']}}) == 'consult'


def test_native_actual_g8_structure_and_gate_registration(tmp_path):
    from ravel.workflow import graph_registry, graph_substrate
    row = json.loads((Path(__file__).resolve().parents[3] /
        'src/ravel/data/graphs/registration/controller.step.json').read_text())['graphs'][0]
    assert row['gates']['native_authority']['required_providers'] == []
    measured = {**deepcopy(row), 'structure_sha256': graph_registry.PIN}
    with graph_registry.registered(measured, replace=True):
        context = graph_substrate.BuildContext(scope_root=tmp_path, graph_id=row['id'], version=row['version'],
            instance={'run_id': 'native-structure'}, row=measured)
        compiled = graph_substrate.build(row['id'], context)
    print('NATIVE_STRUCTURE_SHA256=' + compiled.structure_sha256)
    assert compiled.structure_sha256 == row['structure_sha256']
