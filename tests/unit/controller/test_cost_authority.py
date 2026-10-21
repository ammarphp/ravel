"""Authenticated cost authority and polling never fabricate a calibration or an answer."""
from copy import deepcopy
import json
import sys
import time

import pytest

from ravel.controller.step import budget, graph, services, spec
from ravel.controller.step.services import StepHold, digest
from test_p04_support import FakeAuthority, graphs, make_step, records, run_env, services_installed
from test_p04_reserve import _reserve_state, _top_step
from test_p06_support import autonomous, operator_home  # noqa: F401


def verified_interface(env, monkeypatch, *, fault=None):
    fake = env.fakes['authority']; fake.answers['r3_action'] = ('approve', 'operator_command', 'admit')
    calls = []
    def verify(store, identifier, *, kind, subject):
        calls.append((identifier, kind, deepcopy(subject)))
        if fault in ('withdrawn', 'stale', 'forged'):
            raise fake.AuthorityRefused(fault)
        stored = store.read('authority', identifier)['record']
        assert kind == 'r3_action' and subject == stored['subject']['view']['pins']
        result = {**stored, 'id': identifier, 'source': 'operator_cli', 'authorizes_effects': True,
                  'subject': {'pins': deepcopy(subject)}}
        if fault == 'source': result['source'] = 'machine'
        if fault == 'identity': result['id'] = 'other-record'
        if fault == 'pins': result['subject']['pins']['step_sha256'] = '0' * 64
        if fault == 'label': result['label'] = FakeAuthority.TERMINAL
        if fault == 'authorized': result['authorizes_effects'] = False
        if fault == 'option': result['option'] = 'pilot_first'
        if fault == 'decision': result['decision'] = 'default'
        return result
    monkeypatch.setattr(sys.modules['ravel.controller.authority'], 'verify', verify, raising=False)
    return calls


def test_only_verified_operator_cost_admission_can_create_a_reservation(run_env, monkeypatch):
    calls = verified_interface(run_env, monkeypatch)
    state = _reserve_state(run_env, _top_step())
    with services.bound(run_env.store):
        result = graph.reserve(state)
    assert len(calls) == 1 and calls[0][1] == 'r3_action'
    assert calls[0][2] == {'plan_sha256': state['context']['plan_sha256'],
                          'step_sha256': spec.step_sha256(state['step'])}
    reserved = records(run_env.store, 'budget-reservation')
    assert len(reserved) == 1 and reserved[0]['basis']['signoff'] == calls[0][0]
    assert result['reservation']['record_id'] and records(run_env.store, budget.CALIBRATION) == []


@pytest.mark.parametrize('fault', ['withdrawn', 'stale', 'forged', 'source', 'identity', 'pins',
                                  'label', 'authorized', 'option', 'decision'])
def test_cost_signoff_replays_authentication_and_current_pins(run_env, monkeypatch, fault):
    calls = verified_interface(run_env, monkeypatch, fault=fault)
    state = _reserve_state(run_env, _top_step())
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason in ('authority_refused', 'uncalibrated_top_rung_cost')
    assert len(calls) == 1
    assert records(run_env.store, 'budget-reservation') == [] and records(run_env.store, 'step-launch') == []


@pytest.mark.parametrize('label,decision,option', [(FakeAuthority.TERMINAL, 'approve', 'admit'),
    (FakeAuthority.MACHINE, 'approve', 'admit'), ('operator_command', 'default', 'pilot_first'),
    ('operator_command', 'approve', None)])
def test_machine_default_and_unattested_terminal_never_sign_cost(run_env, monkeypatch, label, decision, option):
    calls = verified_interface(run_env, monkeypatch)
    run_env.fakes['authority'].answers['r3_action'] = (decision, label, option)
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(_reserve_state(run_env, _top_step()))
    assert held.value.reason == 'uncalibrated_top_rung_cost' and calls == []
    assert records(run_env.store, 'budget-reservation') == []


def pending():
    return {'request': 'authority-request-fixture', 'kind': 'r3_action', 'since_ns': time.time_ns(),
            'waited_seconds': 0, 'wait_bound_seconds': 60, 'needed': 'authenticated operator answer'}


def test_real_interrupt_resume_is_only_a_poll_without_an_answer(run_env, monkeypatch):
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    calls = []
    def reserve(state):
        calls.append('reserve')
        raise StepHold('awaiting_authority', 'waiting', evidence={'pending': pending()})
    monkeypatch.setattr(graph, 'reserve', reserve)
    builder = StateGraph(dict); builder.add_node('reserve', graph.reserve_point)
    builder.add_edge(START, 'reserve'); builder.add_edge('reserve', END)
    compiled = builder.compile(checkpointer=InMemorySaver())
    state = _reserve_state(run_env, _top_step())
    config = {'configurable': {'thread_id': 'cost-poll'}}
    with services.bound(run_env.store):
        first = compiled.invoke(state, config)
        payload = first['__interrupt__'][0].value
        assert payload['schema_id'] == 'controller_authority' and payload['approval_from_resume'] is False
        assert payload['authority_kind'] == 'r3_action' and payload['pending']['request']
        assert 'ravel operator answer' in payload['operator_answer']['command']
        again = compiled.invoke(Command(resume={'kind': 'authority_poll', 'note': 'admit'}), config)
    assert again['__interrupt__'] and len(calls) >= 2
    assert records(run_env.store, 'budget-reservation') == [] and records(run_env.store, 'step-launch') == []


@pytest.mark.parametrize('case', ['expired', 'malformed', 'other_hold', 'poll_bound'])
def test_cost_wait_holds_without_an_answer_or_an_implicit_resume(run_env, monkeypatch, case):
    pauses = []; calls = []
    import langgraph.types
    def reserve(state):
        calls.append('reserve'); value = pending()
        if case == 'expired': value['waited_seconds'] = 61
        if case == 'malformed': value.pop('request')
        raise StepHold('other_hold' if case == 'other_hold' else 'awaiting_authority', 'waiting',
                       evidence={'pending': value})
    monkeypatch.setattr(graph, 'reserve', reserve)
    monkeypatch.setattr(langgraph.types, 'interrupt', lambda *a, **k: pauses.append(a) or {'kind': 'authority_poll'})
    state = _reserve_state(run_env, _top_step(), unattended=case == 'expired')
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve_point(state)
    assert held.value.reason == ('other_hold' if case == 'other_hold' else 'awaiting_authority')
    assert len(pauses) == (64 if case == 'poll_bound' else 0)
    assert len(calls) == (65 if case == 'poll_bound' else 1)
    assert records(run_env.store, 'budget-reservation') == []


@pytest.mark.parametrize('fault', [None, 'amounts', 'id', 'withdrawn', 'narrowed'])
def test_cost_gate_rechecks_exact_reservation_and_current_authority(run_env, monkeypatch, fault):
    state = _reserve_state(run_env, make_step('ordinary'))
    with services.bound(run_env.store):
        state.update(graph.reserve(state))
        count = len(records(run_env.store, 'budget-reservation'))
        if fault == 'amounts': state['reservation']['amounts']['events'] = 1
        if fault == 'id': state['reservation']['record_id'] = 'unknown'
        if fault == 'withdrawn': run_env.fakes['authority'].stop = 'paused'
        if fault == 'narrowed': run_env.fakes['authority'].budgets['wall_seconds'] = 0
        checked = graph.cost_authority(state)
    assert bool(checked['gates']['cost_authority']['errors']) == (fault is not None)
    assert len(records(run_env.store, 'budget-reservation')) == count
    assert records(run_env.store, 'step-launch') == []


def test_real_issuer_operator_answer_is_current_and_capture_polling_is_idempotent(tmp_path, monkeypatch, operator_home):
    from ravel.controller import authority
    from ravel.controller.authority import common, retained
    from ravel.controller.store import RunStore
    autonomous(); store = RunStore.create(tmp_path / 'real-cost')
    authority.freeze_mode(store, {'prompt': 'Evaluate a fictional bounded cost admission.'})
    step = _top_step(); plan = {'steps': [step], 'deliverables': [], 'parameters': {}}
    plan['sha256'] = digest(plan)
    store.append('plan', {'plan_sha256': plan['sha256'], 'revision': 0,
                          'blob': store.put_blob(json.dumps(plan).encode())})
    ctx = {'plan_sha256': plan['sha256']}
    monkeypatch.setattr(common, 'nonce', lambda: 'THROWAWAY-COST-CODE')
    ids = []
    for _ in range(2):
        with pytest.raises(StepHold) as held:
            graph._cost_signoff(store, step, {'events': 100, 'wall_seconds': 50}, ctx)
        assert held.value.reason == 'awaiting_authority'
        ids.append(held.value.evidence['pending']['request'])
    assert ids[0] == ids[1] and len(store.scan(common.REQUESTS)) == len(store.scan(retained.KIND)) == 1
    answered = authority.answer(store, ids[0], 'THROWAWAY-COST-CODE', 'admit')
    admitted = graph._cost_signoff(store, step, {'events': 100, 'wall_seconds': 50}, ctx)
    assert admitted['id'] == answered['id'] and admitted['label'] == authority.OPERATOR_COMMAND
    assert admitted['source'] == 'operator_cli' and admitted['option'] == 'admit'
    assert store.scan('budget-reservation') == [] and store.scan(budget.CALIBRATION) == []



def test_cost_structure_matches_its_g8_registration(tmp_path):
    from pathlib import Path
    from ravel.workflow import graph_registry, graph_substrate
    path = Path(__file__).resolve().parents[3] / 'src/ravel/data/graphs/registration/controller.step.json'
    row = json.loads(path.read_text())['graphs'][0]
    assert row['id'] == 'controller.step' and 'controller_authority' in row['interrupts']
    assert 'cost_authority' in row['gates']
    measured = {**deepcopy(row), 'structure_sha256': graph_registry.PIN}
    with graph_registry.registered(measured, replace=True):
        context = graph_substrate.BuildContext(scope_root=tmp_path, graph_id=row['id'], version=row['version'],
            instance={'run_id': 'cost-structure'}, row=measured)
        compiled = graph_substrate.build(row['id'], context)
    assert compiled.structure_sha256 == row['structure_sha256']



def test_cost_gate_replays_signoff_after_reservation_and_refuses_withdrawal(run_env, monkeypatch):
    calls = verified_interface(run_env, monkeypatch)
    state = _reserve_state(run_env, _top_step())
    with services.bound(run_env.store):
        state.update(graph.reserve(state))
        assert len(calls) == 1
        def withdrawn(*args, **kwargs):
            raise run_env.fakes['authority'].AuthorityRefused('operator ceiling narrowed after reservation')
        monkeypatch.setattr(sys.modules['ravel.controller.authority'], 'verify', withdrawn)
        checked = graph.cost_authority(state)
    assert checked['gates']['cost_authority']['errors'][0]['code'] == 'authority_refused'
    assert len(records(run_env.store, 'budget-reservation')) == 1
    assert records(run_env.store, 'step-launch') == [] and records(run_env.store, budget.CALIBRATION) == []



@pytest.mark.parametrize('changed', [False, True])
def test_initial_ordinary_cost_gate_uses_protected_step_before_a_plan_exists(run_env, monkeypatch, changed):
    from test_p04_support import context
    step = make_step('initial.worker')
    state = {'step': step, 'context': context(run_env.store, run_env.run_dir, None)}
    with services.bound(run_env.store):
        state.update(graph.reserve(state))
        def absent_plan(*args, **kwargs):
            pytest.fail('initial ordinary reservation demanded a future compiled plan')
        monkeypatch.setattr(graph.operations, 'plan_step', absent_plan)
        if changed:
            state['acting']['parameters']['changed_after_reserve'] = True
        checked = graph.cost_authority(state)
    assert bool(checked['gates']['cost_authority']['errors']) == changed
    if changed:
        assert checked['gates']['cost_authority']['errors'][0]['code'] == 'reservation_changed'
    assert records(run_env.store, 'step-launch') == []
