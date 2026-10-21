"""Consequential native launches use the single current authority channel sequentially."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ravel.controller import graph
from ravel.controller.authority import retained, service
from ravel.controller.step.services import StepHold
from ravel.workflow import rdj_loop
from test_native_authority import bridge  # noqa: F401
from test_native_launch_gate import native, reviewed  # noqa: F401
from test_p06_support import autonomous, frozen_store, operator_home, view  # noqa: F401


@pytest.fixture
def wave(tmp_path, monkeypatch):
    rows = []
    store = SimpleNamespace(run_dir=tmp_path, run_id='native-waves',
                            append=lambda kind, row: rows.append((kind, deepcopy(row))))
    plan = {'steps': [
        {'id': 'ordinary', 'kind': 'compose'},
        *[{'id': f'native.{tag}', 'kind': 'operate', 'rung': 'scan',
           'parameters': {'launch': {'argv': ['tool']}}} for tag in ('first', 'second')]]}
    identifiers = [step['id'] for step in plan['steps']]
    state = {'plan': {'steps': identifiers, 'prepare': identifiers,
                      'sha256': 'a' * 64, 'approved_sha256': 'a' * 64}, 'steps': {}}
    monkeypatch.setattr(graph, '_store', lambda _: store)
    monkeypatch.setattr(graph, '_governed', lambda *a: None)
    monkeypatch.setattr(graph, 'current_plan', lambda *a: plan)
    monkeypatch.setattr(graph, '_boundary_reached', lambda *a: None)
    monkeypatch.setattr(graph, 'engagement_hold', lambda *a: None)
    monkeypatch.setattr(graph, '_admitted', lambda state, store, plan, ready, steps: (ready, {}, {}))
    monkeypatch.setattr(graph, 'settle_answers', lambda *a: ({}, {}, {}))
    monkeypatch.setattr(graph, 'run_route_children', lambda *a: ({}, {}, []))
    monkeypatch.setattr(graph, 'close_decides', lambda *a: ({}, {}, {}, {}))
    return SimpleNamespace(plan=plan, state=state, rows=rows)


@pytest.mark.parametrize('phase', ['prepare', 'execute'])
@pytest.mark.parametrize('basis', ['unknown_cost', 'explicit_floor'])
def test_consequential_native_wave_keeps_other_requests_for_a_later_wave(wave, monkeypatch, phase, basis):
    if basis == 'explicit_floor':
        monkeypatch.setattr(rdj_loop, '_cost_facts', lambda _: {'points': 1, 'walltime_hours': 0})
        for step in wave.plan['steps'][1:]:
            step['consequence_class'] = 'R3'
    select = graph.prepare_wave if phase == 'prepare' else graph.plan_wave
    before = deepcopy(wave.plan)
    first = select(wave.state)
    assert first['loop']['decision'] == 'dispatch'
    assert [item['step']['id'] for item in first['loop']['items']] == ['native.first']
    assert wave.rows[-1][1]['ready'] == ['native.first']
    assert wave.plan == before
    assert wave.state['steps'] == {}
    next_state = {**wave.state, 'steps': {'native.first': {'status': 'completed'}}}
    second = select(next_state)
    assert [item['step']['id'] for item in second['loop']['items']] == ['native.second']


@pytest.mark.parametrize('phase', ['prepare', 'execute'])
def test_bounded_lower_class_native_launches_retain_parallel_waves(wave, monkeypatch, phase):
    monkeypatch.setattr(rdj_loop, '_cost_facts', lambda _: {'points': 1, 'walltime_hours': 0})
    select = graph.prepare_wave if phase == 'prepare' else graph.plan_wave
    found = select(wave.state)
    assert [item['step']['id'] for item in found['loop']['items']] == ['ordinary', 'native.first', 'native.second']


def test_interleaved_retained_views_are_validation_failures_not_operator_waits(tmp_path, operator_home):
    autonomous()
    store = frozen_store(tmp_path)
    view(store, 'r3_action', plan_sha256='a' * 64, step_sha256='b' * 64)
    first = retained.current(store, 'r3_action')['view']
    view(store, 'r3_action', plan_sha256='a' * 64, step_sha256='c' * 64)
    result = service.request(store, 'r3_action', {'view': first}, {})
    assert result['pending']['request'] is None
    assert 'check-in view differs from authenticated retained plan and reading' in result['pending']['errors']
    assert store.scan('authority-request') == []
    assert store.scan('authority') == []


def test_native_builder_preserves_authority_validation_errors(bridge, monkeypatch):
    from ravel.controller.authority import rdj
    n = bridge
    n.reviewed.retained['reading'] = {'request_pins': {}, 'inferred_critical_facts': [],
                                     'flags': [], 'items': {}}
    monkeypatch.setattr(retained, 'capture', lambda store, kind, **kw: {'view': kw['view']})
    monkeypatch.setattr(rdj, 'dispatch_native', lambda *a: None)
    pending = {'kind': 'r3_action', 'request': None, 'reason': 'check-in incomplete',
               'errors': ['check-in view differs from authenticated retained plan and reading']}
    monkeypatch.setattr(service, 'request', lambda *a: {'pending': deepcopy(pending)})
    with pytest.raises(StepHold) as held:
        n.api.prepare(n.store, n.step, n.context, {**n.prepared, 'native_preflight': 'preflight-2'})
    assert held.value.reason == 'authority_request_invalid'
    assert pending['errors'][0] in held.value.would_make_possible
    assert held.value.evidence['pending'] == pending
