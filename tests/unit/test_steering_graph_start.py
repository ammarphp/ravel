"""In-process graph node starts are serialized with live steering.

A node is admitted under the steering lock and recorded as running work before its body starts:
a pause that commits first refuses the node, and a pause that commits afterwards finds the node
draining. Both graph engines are driven at their node-start function.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ravel.workflow import agent_graph, gate_wiring as gw, graph_nodes, graph_substrate as gs
from test_agent_graph import Host, node, spec


@pytest.fixture
def scope(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'scope'
    root.mkdir()
    return root


def pause_between_check_and_start(monkeypatch, root):
    """Commit a pause right after the first steering check passes: the window the lock must close."""
    real, fired = gw.dispatch_permitted, []

    def checked(rundir, node_id, **options):
        result = real(rundir, node_id, **options)
        if result[0] and not fired:
            fired.append(node_id)
            gw.record_steering(root, 'Pause the study.', effect='pause')
        return result
    monkeypatch.setattr(gw, 'dispatch_permitted', checked)
    return fired


def instrumented(function):
    return graph_nodes._instrumented('compute', 'synthetic-graph', None, function)


def state(root):
    return {'meta': {'scope_root': str(root)}}


def test_graph_node_body_does_not_start_after_a_pause_commits_at_its_admission(scope, monkeypatch):
    started = []
    fired = pause_between_check_and_start(monkeypatch, scope)
    with pytest.raises(graph_nodes.GraphError, match='paused'):
        instrumented(lambda value: started.append('body') or {})(state(scope))
    assert fired and started == []


def test_admitted_graph_node_drains_through_a_later_pause_and_is_reported_running(scope):
    seen = {}

    def body(value):
        # The pause commits while this node runs: it is not blocked by the node, and the node finishes.
        gw.record_steering(scope, 'Pause the study.', effect='pause')
        seen['during'] = gw.steering_state(scope)
        return {'done': True}
    assert instrumented(body)(state(scope)) == {'done': True}
    assert seen['during']['paused'] and seen['during']['pause_status'] == 'draining'
    assert not seen['during']['observed_stopped']
    after = gw.steering_state(scope)
    assert after['pause_status'] == 'observed-stopped' and after['observed_stopped']
    assert gw.admitted_work(scope) == []
    with pytest.raises(graph_nodes.GraphError, match='paused'):
        instrumented(lambda value: pytest.fail('a node started under the pause'))(state(scope))


def test_pause_and_node_start_are_serialized_across_threads(scope):
    entered, release, results = threading.Event(), threading.Event(), {}

    def body(value):
        entered.set()
        assert release.wait(10)
        return {'done': True}

    def start():
        return instrumented(body)(state(scope))

    def pause():
        results['pause'] = gw.record_steering(scope, 'Pause the study.', effect='pause')
        results['state'] = gw.steering_state(scope)
    with ThreadPoolExecutor(2) as pool:
        running = pool.submit(start)
        assert entered.wait(10)
        paused = pool.submit(pause)
        paused.result(10)  # the running node does not hold the steering lock
        assert results['state']['pause_status'] == 'draining'
        release.set()
        assert running.result(10) == {'done': True}
    assert gw.steering_state(scope)['pause_status'] == 'observed-stopped'


def test_cancel_on_pause_does_not_signal_the_process_running_an_admitted_node(scope, monkeypatch):
    gw.set_steering_policy(scope, dict(autonomy='manual', checkin_thresholds={}, hard_ceilings={}, signoff_steps=[],
                                       unknown_cost='ask', on_pause='cancel', result_acceptance='physicist'),
                           source_text='Cancel on pause.')
    (scope / 'inputs/checkin1_approval.json').write_text('{"approved":true}')
    gw.ack_steering(scope, gw.steering_records(scope)[-1]['event_id'], interpretation='Policy retained.')
    gw.record_plan_approval(scope)
    monkeypatch.setattr(gs.os, 'killpg', lambda *a: pytest.fail('the runner process group was signalled'))

    def body(value):
        gw.record_steering(scope, 'Stop now.', effect='pause')
        return {'done': True}
    assert instrumented(body)(state(scope)) == {'done': True}


def test_node_refused_by_a_veto_registers_no_running_work(scope):
    (scope / 'graph_spec.json').write_text('{"nodes": []}')
    gw.record_steering(scope, 'Stop the study.', effect='veto')
    with pytest.raises(graph_nodes.GraphError, match='veto'):
        instrumented(lambda value: pytest.fail('a vetoed node started'))(state(scope))
    assert gw.admitted_work(scope) == []


def test_admitted_node_is_recorded_in_custody_and_leaves_the_scope_directory_untouched(scope):
    seen = {}

    def body(value):
        seen['running'] = gw.admitted_work(scope)
        seen['entries'] = sorted(p.name for p in scope.iterdir())
        return {'done': True}
    before = sorted(p.name for p in scope.iterdir())
    assert instrumented(body)(state(scope)) == {'done': True}
    assert [row['role'] for row in seen['running']] == ['graph-node'] and seen['entries'] == before
    assert gw.admitted_work(scope) == [] and sorted(p.name for p in scope.iterdir()) == before


def test_admitted_work_of_a_process_that_is_gone_no_longer_counts(scope):
    import subprocess
    import sys
    gone = subprocess.Popen([sys.executable, '-c', 'pass'])
    gone.wait()
    gw._admitted_change(scope, add={'id': 'steering-admitted-gone', 'pid': gone.pid, 'role': 'graph-node',
                                    'node_id': None, 'scope': str(scope), 'started_utc': 'synthetic'})
    assert gw.admitted_work(scope) == []


def test_legacy_graph_node_does_not_start_after_a_pause_commits_at_its_admission(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'graph'
    agent_graph.create(root, spec([node('first')]))
    fired = pause_between_check_and_start(monkeypatch, root)
    host = Host()
    try:
        outcome = agent_graph.execute(root, host, workers=1)
    except (agent_graph.GraphError, ValueError) as exc:
        assert 'paused' in str(exc)
    else:
        assert outcome['complete'] is False
    assert fired and host.dispatched == []
    assert agent_graph.status(root)['nodes']['first']['status'] == 'pending'
    assert gw.admitted_work(root) == []


def test_legacy_graph_node_admitted_before_a_pause_drains_and_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'graph'
    agent_graph.create(root, spec([node('first'), node('second', ['first'])]))
    seen = {}

    def operation(item, request, control):
        if item['id'] == 'first':
            gw.record_steering(root, 'Pause the study.', effect='pause')
            seen['during'] = gw.steering_state(root)['pause_status']
        return {'public': item['id']}
    host = Host(operation)
    outcome = agent_graph.execute(root, host, workers=1)
    # The node that was running finished; the queued one never started.
    assert outcome['complete'] is False
    assert host.dispatched == ['first'] and seen['during'] == 'draining'
    status = agent_graph.status(root)['nodes']
    assert status['first']['status'] == 'completed' and status['second']['status'] == 'pending'
    assert gw.steering_state(root)['pause_status'] == 'observed-stopped'
