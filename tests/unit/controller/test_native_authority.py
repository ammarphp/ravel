"""Exact native authority bridge; declaration fakes isolate authenticated service interfaces."""
from copy import deepcopy
import importlib
from types import SimpleNamespace
import pytest

from test_native_launch_gate import native, reviewed, make_action  # noqa: F401


@pytest.fixture
def bridge(reviewed, monkeypatch):
    from ravel.controller.authority import common, rdj, retained, service
    from ravel.workflow import rdj_approval, role_registry
    from ravel.controller.judgment.steps import rdj_role
    n = reviewed
    n.reviewed.result['class'] = 'R3'
    n.api = importlib.import_module('ravel.controller.step.native_authority')
    n.action = make_action(n)
    n.real_active = n.api.active
    monkeypatch.setattr(n.api, 'active', lambda rundir, action: True)
    n.operator = {'id': 'operator-native', 'kind': 'r3_action', 'label': common.OPERATOR_COMMAND,
        'source': 'operator_cli', 'decision': 'approve', 'option': 'admit', 'authorizes_effects': True,
        'subject': {'pins': deepcopy(n.action['view_pins'])}}
    from ravel.workflow import rdj_loop
    monkeypatch.setattr(rdj_loop, 'compute_class', lambda *a, **k: (n.reviewed.result['class'], {}))
    n.case = {'role': rdj_role(), 'step_id': 'observed-native-critic', 'transport': 'observed'}
    n.errors = {}
    def exact_case(store, digest):
        assert store is n.store and digest == n.action['digest']
        return (None, n.errors['case']) if 'case' in n.errors else (deepcopy(n.case), None)
    monkeypatch.setattr(rdj_approval, '_case', exact_case)
    monkeypatch.setattr(role_registry, 'same_card', lambda a, b: a == b)
    def current(store, kind, subject=None):
        assert store is n.store and kind == 'r3_action' and subject == n.action['view_pins']
        return None if n.errors.get('missing') else {**deepcopy(n.operator), 'id': 'operator-native'}
    def verify(store, identifier, *, kind, subject=None):
        assert store is n.store and identifier == 'operator-native' and kind == 'r3_action'
        assert subject == n.action['view_pins']
        if n.errors.get('stale'):
            raise common.AuthorityRefused('stale authority')
        return deepcopy(n.operator)
    monkeypatch.setattr(service, 'current', current)
    monkeypatch.setattr(service, 'verify', verify)
    return n


def test_exact_native_r3_uses_current_observed_case_and_verified_operator(bridge):
    missing, evidence = bridge.api.evaluate(bridge.store.run_dir, bridge.action)
    assert missing == [] and evidence['subject_sha256'] == bridge.action['digest']
    assert evidence['authority'] == 'operator-native'


@pytest.mark.parametrize('fault', ['missing', 'stale', 'machine', 'terminal', 'default', 'delegated',
    'source', 'decision', 'option', 'effects', 'pins', 'canonical'])
def test_native_r3_rejects_every_nonexact_operator_declaration(bridge, fault):
    n = bridge
    if fault in ('missing', 'stale'): n.errors[fault] = True
    if fault in ('machine', 'terminal', 'default', 'delegated'): n.operator['label'] = fault
    if fault == 'source': n.operator['source'] = 'controller_terminal'
    if fault == 'decision': n.operator['decision'] = 'default'
    if fault == 'option': n.operator['option'] = 'hold'
    if fault == 'effects': n.operator['authorizes_effects'] = False
    if fault == 'pins': n.operator['subject']['pins']['attempt'] = '99'
    if fault == 'canonical': n.operator['id'] = 'alias'
    missing, evidence = n.api.evaluate(n.store.run_dir, n.action)
    assert missing and evidence is None


@pytest.mark.parametrize('reason', ['no RDJ case decided it', 'case has verdict revise',
                                  'case has no observed blind transport credit'])
def test_native_r3_requires_accepted_observed_critic(bridge, reason):
    bridge.errors['case'] = reason
    missing, evidence = bridge.api.evaluate(bridge.store.run_dir, bridge.action)
    assert missing and evidence is None


@pytest.mark.parametrize('fault', ['attempt', 'pins', 'code'])
def test_native_rechecks_protected_action_on_every_read(bridge, fault):
    n = bridge
    if fault == 'attempt': n.action['view_pins']['attempt'] = '3'
    if fault == 'pins': n.action['view_pins']['launch_sha256'] = 'c' * 64
    if fault == 'code': n.faults['commitments'] = True
    missing, evidence = n.api.evaluate(n.store.run_dir, n.action)
    assert missing and evidence is None


def test_native_current_scientific_review_still_blocks(bridge):
    bridge.reviewed.result['approval_errors'] = ['review revise']
    missing, evidence = bridge.api.evaluate(bridge.store.run_dir, bridge.action)
    assert missing and evidence is None


def test_lower_class_prepare_never_captures_or_requests(reviewed, monkeypatch):
    from ravel.controller.authority import rdj, retained, service
    api = importlib.import_module('ravel.controller.step.native_authority')
    def forbidden(*args, **kwargs): pytest.fail('lower-class action requested R3 authority')
    monkeypatch.setattr(retained, 'capture', forbidden)
    monkeypatch.setattr(service, 'request', forbidden)
    monkeypatch.setattr(rdj, 'dispatch_native', forbidden)
    prepared = {**reviewed.prepared, 'native_preflight': 'preflight-2'}
    result = api.prepare(reviewed.store, reviewed.step, reviewed.context, prepared)
    assert result['class'] == 'R1' and not result.get('pending')


def test_active_context_is_historical_exact_and_authenticated(bridge, monkeypatch):
    from ravel.controller.authority import common, retained
    n = bridge
    rows = []
    n.reviewed.records[retained.KIND] = [{'record': 'protected-context'}]
    def authenticated(store, kind, schema):
        assert store is n.store and kind == retained.KIND and schema == retained.SCHEMA
        return deepcopy(rows)
    monkeypatch.setattr(common, 'scan', authenticated)
    assert not n.real_active(n.store.run_dir, n.action)
    rows.append({'kind': 'r3_action', 'view': {'pins': {'step_sha256': n.action['view_pins']['step_sha256']}}})
    assert not n.real_active(n.store.run_dir, n.action)
    rows.append({'kind': 'r3_action', 'view': {'pins': deepcopy(n.action['view_pins'])}})
    rows.append({'kind': 'r3_action', 'view': {'pins': {'another': 'context'}}})
    assert n.real_active(n.store.run_dir, n.action)
    def forged(*args): raise common.AuthorityRefused('issuer authentication failed')
    monkeypatch.setattr(common, 'scan', forged)
    with pytest.raises(common.AuthorityRefused): n.real_active(n.store.run_dir, n.action)


def test_prepare_captures_before_observed_dispatch_and_returns_real_pending(bridge, monkeypatch):
    from ravel.controller.authority import retained, rdj, service
    n = bridge
    n.reviewed.retained['reading'] = {'request_pins': {}, 'inferred_critical_facts': ['actual-inference'],
                                    'flags': [{'kind': 'risk', 'text': 'approved risk'}], 'items': {}}
    calls = []
    def capture(store, kind, *, plan, reading, view):
        assert store is n.store and kind == 'r3_action' and plan == n.plan
        assert view['pins'] == n.action['view_pins'] and reading['inferred_critical_facts'] == ['actual-inference']
        assert reading['flags'][0]['text'] == 'approved risk'
        assert [o['effect'] for o in view['options']] == [True, False]
        calls.append('capture')
        return {'view': view}
    def dispatch(store, action, context):
        assert calls == ['capture'] and action == n.action
        calls.append('dispatch')
    def request(store, kind, subject, bounds):
        assert calls == ['capture', 'dispatch'] and kind == 'r3_action'
        assert subject['conservative_default'] == 'hold' and bounds == {
            'rung': 'smoke', 'stages': ['analysis'], 'budget': {'wall_seconds': 7, 'events': 0}}
        return {'pending': {'request': 'real-request-id', 'kind': 'r3_action'}}
    monkeypatch.setattr(retained, 'capture', capture)
    monkeypatch.setattr(rdj, 'dispatch_native', dispatch)
    monkeypatch.setattr(service, 'request', request)
    result = n.api.prepare(n.store, n.step, n.context, {**n.prepared, 'native_preflight': 'preflight-2'})
    assert result['pending']['request'] == 'real-request-id'
    assert 'authority' not in result


def test_missing_retained_exact_native_context_cannot_authorize(bridge, monkeypatch):
    monkeypatch.setattr(bridge.api, 'active', lambda *a: False)
    missing, evidence = bridge.api.evaluate(bridge.store.run_dir, bridge.action)
    assert missing and evidence is None


def test_native_r3_mapping_is_used_by_selected_active_providers(bridge, monkeypatch):
    from ravel.workflow import rdj_loop, production_executor
    n = bridge
    monkeypatch.setattr(rdj_loop.custody, 'rows', lambda *a: [])
    monkeypatch.setattr(rdj_loop.anchor_check, 'policy_pin', lambda: {'sha256': 'e' * 64})
    errors, receipt = rdj_loop._gate_decision(n.store.run_dir, 'launch', n.action)
    assert errors == [] and receipt is None
    evidence = rdj_loop.gate_evidence(n.store.run_dir, 'launch', n.action)
    assert evidence['native_case']['authority'] == 'operator-native'
    assert production_executor.gate_errors(n.store.run_dir, 'launch', n.action) == []
    n.errors['stale'] = True
    assert rdj_loop._gate_decision(n.store.run_dir, 'launch', n.action)[0]
    assert rdj_loop.gate_evidence(n.store.run_dir, 'launch', n.action) is None
    assert production_executor.gate_errors(n.store.run_dir, 'launch', n.action)


def test_native_bounds_retain_numeric_reservation_without_inventing_unknown_cost(bridge):
    proof = {**bridge.proof, 'budget': {'wall_seconds': 7, 'events': 0, 'cost_usd': None}}
    assert bridge.api._bounds(bridge.step, proof)['budget'] == {'wall_seconds': 7, 'events': 0}
    assert proof['budget']['cost_usd'] is None


def test_dispatch_native_uses_real_ordinary_rdj_step_and_protected_intake(bridge, monkeypatch):
    from ravel.controller.authority import rdj
    from ravel.controller.judgment import graph
    from ravel.controller.judgment.steps import rdj_role
    n = bridge
    intake = {'request_sha256': '1' * 64, 'reading_blob': '2' * 64, 'contract_blob': '3' * 64}
    monkeypatch.setattr(n.store, 'latest', lambda kind: {'record': intake} if kind == 'intake' else None, raising=False)
    calls = []
    def request(state, store):
        assert store is n.store and state['request'] == {'sha256': '1' * 64,
            'reading_sha256': '2' * 64, 'contract_sha256': '3' * 64}
        assert state['context'] == n.context
        calls.append('request')
        return {'protected': 'request'}
    def context_file(state, name, document):
        assert name == 'native-launch-action' and document['action'] == n.action
        assert document['class'] == 'R3'
        return {'artifact': 'native.json', 'sha256': '4' * 64}
    def run_steps(store, state, request, phase, steps):
        assert store is n.store and request == {'protected': 'request'} and phase == 'native-launch-action'
        step, = steps
        assert step['id'] == 'native-rdj-' + n.action['digest'][:40]
        assert step['role'] == rdj_role()
        assert step['parameters']['judgment']['subject']['sha256'] == n.action['digest']
        calls.append('ordinary-observed-dispatch-interface')
    monkeypatch.setattr(graph, '_request', request)
    monkeypatch.setattr(graph, '_context_file', context_file)
    monkeypatch.setattr(graph, '_inputs', lambda *a: {'request': 'r', 'reading': 'd', 'contract': 'c'})
    monkeypatch.setattr(graph, '_run_planning_steps', run_steps)
    rdj.dispatch_native(n.store, n.action, n.context)
    assert calls == ['request', 'ordinary-observed-dispatch-interface']
    n.reviewed.records['step-outcome'] = [{'record': {'step_id': 'native-rdj-' + n.action['digest'][:40]}}]
    rdj.dispatch_native(n.store, n.action, n.context)
    assert len(calls) == 2
