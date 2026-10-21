"""CHECK-IN 2 binds current waypoint seats and a separate exact-action RDJ critic."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ravel.controller import graph
from ravel.controller.authority import common, rdj, retained, service
from ravel.controller.judgment import graph as judgment_graph
from ravel.controller.judgment.steps import rdj_role
from ravel.workflow import rdj_approval, rdj_loop
from test_waypoint_policy import current_round  # noqa: F401


@pytest.fixture
def checkpoint(current_round, monkeypatch):
    f = current_round
    f.plan['checkins'] = [{'id': 'checkin2', 'seats': [f.role]}]
    f.action.update(kind='controller.checkin2_accept', waypoint='measure', pins=[])
    f.retained_pins = deepcopy(f.action['view_pins'])
    f.required, f.factors = 'R2', {}
    f.case_reason, f.case_role = None, rdj_role()
    f.authority_label = common.MACHINE
    f.authority_calls = []
    def current(store, kind):
        assert store is f.store and kind == 'go'
        return {'view': {'pins': deepcopy(f.retained_pins)}}
    def case(store, digest):
        assert store is f.store and digest == f.action['digest']
        return ({'role': f.case_role, 'credit': 'action-credit', 'case': 'action-case'}
                if f.case_reason is None else None), f.case_reason
    def authority(store, kind, *, subject):
        assert store is f.store and kind == 'go' and subject == f.action['view_pins']
        f.authority_calls.append(kind)
        return {'id': 'current-go', 'label': f.authority_label}
    monkeypatch.setattr(retained, 'current', current)
    monkeypatch.setattr(rdj_approval, '_case', case)
    monkeypatch.setattr(rdj_approval, 'applies', lambda root: True)
    monkeypatch.setattr(rdj_loop, 'compute_class', lambda *a, **k: (f.required, deepcopy(f.factors)))
    monkeypatch.setattr(rdj_loop.custody, 'rows', lambda *a: [])
    monkeypatch.setattr(rdj_loop.anchor_check, 'policy_pin', lambda: {'sha256': 'e' * 64})
    monkeypatch.setattr(service, 'current', authority)
    from ravel.controller import store as store_module
    monkeypatch.setattr(store_module, 'controller_owned', lambda root: 'run')
    monkeypatch.setattr(store_module, 'RunStore', lambda owner: f.store)
    return f


def errors(f):
    return rdj_loop.gate_errors(f.store.run_dir, 'checkin2_accept', f.action)


def test_exact_current_waypoint_and_action_case_pass_without_json_receipt(checkpoint):
    f = checkpoint
    assert errors(f) == []
    evidence = rdj_loop.gate_evidence(f.store.run_dir, 'checkin2_accept', f.action)
    assert evidence['mechanism'] == 'rdj_checkin2_accept.mapping'
    assert evidence['action_digest'] == f.action['digest']
    assert evidence['action_case']['credit'] == 'action-credit'
    assert evidence['action_case']['waypoint_reviews'][f.role]['credit'] == 'credit-2'
    assert f.authority_calls == []
    assert rdj_loop.authorizing_receipt(f.store.run_dir, 'checkin2_accept', f.action) is None


@pytest.mark.parametrize('fault', ['missingcase', 'revise', 'wrongcard', 'retainedpins', 'staleoutputs',
                                  'seatmissing', 'wrongkind', 'wrongwaypoint', 'waypointrevise'])
def test_checkpoint_bridge_refuses_incomplete_or_stale_subject(checkpoint, fault):
    f = checkpoint
    if fault == 'missingcase': f.case_reason = 'no RDJ case for exact action'
    if fault == 'revise': f.case_reason = 'latest action case verdict is revise'
    if fault == 'waypointrevise': f.records['review'][0]['record']['seats'][f.role]['verdict'] = 'revise'
    if fault == 'wrongcard': f.case_role = 'rdj-verifier'
    if fault == 'retainedpins': f.retained_pins['checkin2_review'] = 'old-round'
    if fault == 'staleoutputs': next(iter(f.accepted.values()))['sha256'] = 'd' * 64
    if fault == 'seatmissing': f.plan['checkins'][0]['seats'].append('physics-critic')
    if fault == 'wrongkind': f.action['kind'] = 'controller.approve_plan'
    if fault == 'wrongwaypoint': f.action['waypoint'] = 'another-waypoint'
    assert errors(f)
    assert rdj_loop.gate_evidence(f.store.run_dir, 'checkin2_accept', f.action) is None
    assert rdj_loop.authorizing_receipt(f.store.run_dir, 'checkin2_accept', f.action) is None


@pytest.mark.parametrize('label,passes', [(common.MACHINE, False), (common.OPERATOR_COMMAND, True)])
def test_r3_checkpoint_requires_exact_current_go_operator_authority(checkpoint, label, passes):
    f = checkpoint; f.required = 'R3'; f.authority_label = label
    assert (errors(f) == []) == passes
    evidence = rdj_loop.gate_evidence(f.store.run_dir, 'checkin2_accept', f.action)
    assert (evidence is not None) == passes
    assert f.authority_calls == ['go', 'go']
    if passes:
        assert evidence['action_case']['authority'] == 'current-go'
        assert evidence['action_case']['authority_label'] == common.OPERATOR_COMMAND


def test_dispatch_uses_ordinary_exact_critic_once_even_after_failed_outcome(checkpoint, monkeypatch):
    f = checkpoint; dispatched, materials = [], []
    monkeypatch.setattr(judgment_graph, '_request', lambda state, store: {})
    monkeypatch.setattr(judgment_graph, '_inputs', lambda *a: {})
    monkeypatch.setattr(judgment_graph, '_base_inputs', lambda *a: [])
    def material(state, name, document):
        materials.append((name, deepcopy(document)))
        return {'artifact': name, 'sha256': 'f' * 64}
    def run(store, state, request, phase, steps):
        assert store is f.store and phase == 'checkpoint-action'
        dispatched.extend(steps)
        f.records.setdefault('step-outcome', []).append({'id': 'failed-action-seat',
            'record': {'step_id': steps[0]['id'], 'status': 'failed'}})
    monkeypatch.setattr(judgment_graph, '_context_file', material)
    monkeypatch.setattr(judgment_graph, '_run_planning_steps', run)
    rdj.dispatch(f.store, {}, f.action, {'purpose': 'waypoint'})
    rdj.dispatch(f.store, {}, f.action, {'purpose': 'waypoint'})
    assert len(dispatched) == len(materials) == 1
    assert dispatched[0]['id'] == 'authority-rdj-' + f.action['digest'][:40]
    assert dispatched[0]['role'] == rdj_role()
    assert materials[0][0] == 'checkpoint-action'
    assert materials[0][1]['action'] == f.action
    assert materials[0][1]['approval_view']['pins'] == f.action['view_pins']
    f.case_reason = 'no observed accepted action case'
    assert errors(f), 'dispatching or failing a critic is not observed acceptance'


def test_controller_go_dispatches_exact_action_after_retaining_and_before_request(checkpoint, monkeypatch):
    f = checkpoint; calls = []
    state = {'plan': f.plan, 'run': {}}
    monkeypatch.setattr(graph, '_store', lambda actual: f.store)
    monkeypatch.setattr(graph, 'authority_material', lambda *a: (
        {'view': {'pins': deepcopy(f.action['view_pins'])}}, {}, f.plan))
    def retain(store, kind, **kwargs):
        assert store is f.store and kind == 'go'
        assert kwargs['view']['pins'] == f.action['view_pins']
        calls.append('retain')
    def dispatch(store, actual, action, context):
        assert calls == ['retain'] and store is f.store and actual is state
        assert action == graph._gate_action('checkin2_gate', state, f.action['view_pins'])
        assert action['kind'] == 'controller.checkin2_accept' and context['purpose'] == 'waypoint'
        calls.append('dispatch')
    def request(store, kind, subject, bounds):
        assert calls == ['retain', 'dispatch'] and kind == 'go' and store is f.store
        assert subject['view']['pins'] == f.action['view_pins']
        calls.append('request')
        return {'decision': 'reject'}
    monkeypatch.setattr(graph, 'retain', retain)
    monkeypatch.setattr(graph, 'authority_bounds', lambda *a: {})
    monkeypatch.setattr(graph, '_context', lambda *a, **kw: kw)
    monkeypatch.setattr(graph, 'service', lambda name: SimpleNamespace(request=request))
    monkeypatch.setattr(graph, '_record_mechanism_rows', lambda *a: None)
    monkeypatch.setattr(rdj, 'dispatch', dispatch)
    result = graph.authority_point('checkin2').function(state)
    assert calls == ['retain', 'dispatch', 'request']
    assert result['loop']['checkin2_decision'] == 'reject' and result['authority']['go'] == []


def test_generic_json_receipt_cannot_replace_observed_checkpoint_case(checkpoint, monkeypatch):
    f = checkpoint; f.case_reason = 'no observed checkpoint action case'
    monkeypatch.setattr(rdj_loop.custody, 'rows', lambda *a: [{'record': {
        'action_digest': f.action['digest'], 'gate': 'checkin2_accept', 'case_id': 'json-only-case'}}])
    def forbidden(*args):
        raise AssertionError('controller checkpoint selected the generic JSON receipt path')
    monkeypatch.setattr(rdj_loop, '_current_receipt', forbidden)
    assert errors(f)
    assert rdj_loop.gate_evidence(f.store.run_dir, 'checkin2_accept', f.action) is None
    assert rdj_loop.authorizing_receipt(f.store.run_dir, 'checkin2_accept', f.action) is None
