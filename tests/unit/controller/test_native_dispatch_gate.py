"""A native process cannot start before the real launch decision is admitted."""
import pytest
from ravel.controller.step import operations, services
from test_p04_graph import _launch_step, _launch_tool, _signature
from test_p04_support import graphs, records, run_env, run_step, services_installed


@pytest.mark.parametrize('refused', [False, True, 'withdrawn'])
def test_native_launch_decision_precedes_the_actual_start(run_env, graphs, monkeypatch, refused):
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    step = _launch_step(_launch_tool(run_env.root))
    calls = []
    def decide(store, run_dir, gate, action):
        calls.append((gate, action, records(store, 'step-launch')))
        return [{'code': 'unresolved_review'}] if refused is True or (refused == 'withdrawn' and len(calls) == 2) else []
    monkeypatch.setattr(services.module('ledger'), 'decide', decide)
    result = run_step(run_env, step)
    assert len(calls) == (1 if refused is True else 2), result
    assert all(call[0] == 'launch' and call[2] == [] for call in calls), result
    assert all(call[1] == calls[0][1] for call in calls), 'fresh checks must decide the same exact action'
    assert calls[0][1]['step'] == step['id']
    assert calls[0][1]['view_pins']['native_preflight']
    assert calls[0][2] == []
    if refused:
        rejected = [row for row in records(run_env.store, 'step-fact')
                    if row.get('mechanism') == 'native-launch-decision' and row.get('passed') is False]
        assert len(rejected) == 1 and rejected[0]['errors'] == [{'code': 'unresolved_review'}]
        assert rejected[0]['action'] == calls[-1][1]
        assert records(run_env.store, 'step-launch') == []
        assert run_env.fakes['confine'].launched == []
        assert result['status'] == 'held'
        assert result['reason'] == ('native_authority_refused' if refused is True else 'native_launch_gate_refused')
    else:
        assert result['status'] == 'completed', result
        assert len(run_env.fakes['confine'].launched) == 1
        admitted = [row for row in records(run_env.store, 'step-fact')
                    if row.get('mechanism') == 'native-launch-decision' and row.get('passed') is True]
        assert len(admitted) == 2 and all(row['action'] == calls[0][1] for row in admitted)
        assert [row for row in records(run_env.store, 'step-fact')
                if row['mechanism'] == 'native-launch-decision'][-1]['passed'] is True
