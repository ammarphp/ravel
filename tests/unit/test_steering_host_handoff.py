"""Steering admission at the host-subagent handoff; synthetic host reports only, no host CLI runs.

RAVEL does not spawn the host's subagent. It admits the handoff (the brief) and the working
window (the broker it serves) under live steering, records the admitted start, and writes a
receipt only for work that started inside an admitted window.
"""
import json

import pytest

from ravel.workflow import agent_worker as worker, broker, gate_wiring as gw, graph_substrate as gs
from ravel.workflow.transports import cli_worker, host_subagent
from test_host_subagent_adapter import spec

HOST = 'host-subagent-claude'


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.delenv('RAVEL_WORK_ROOT', raising=False)
    monkeypatch.setattr(gs, 'stop', lambda *a, **kw: {})
    monkeypatch.setattr(worker, 'stop', lambda *a, **kw: {})
    (tmp_path / 'run').mkdir()
    return tmp_path / 'run'


def resume(run):
    event = gw.record_steering(run, 'Continue the study.', effect='resume')
    gw.ack_steering(run, event['event_id'], interpretation='Continue within the approved scope.')


def write_result(packet):
    return broker.socket_call(packet['broker_socket'], {'call_id': 'c1', 'action': 'write',
                                                        'args': {'path': 'outputs/result.txt', 'content': 'x'}})


def start_record(run, s):
    return broker.custody(run) / (worker._key(s['node_id'], s['attempt']) + '.host-start.json')


@pytest.mark.parametrize('effect, nodes', [('pause', []), ('veto', []), ('veto', ['host.worker']),
                                           ('requirement', ['host.worker'])])
def test_brief_is_refused_while_steering_blocks_the_node(run, effect, nodes):
    s = spec()
    ws = worker.materialize(run, s)
    gw.record_steering(run, 'Hold this work.', effect=effect, affected_nodes=nodes)
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        host_subagent.brief(run, s, ws, transport_id=HOST)
    assert refused.value.missing == ['steering']
    assert not (ws / 'inputs/host-brief.json').exists()
    assert not (broker.custody(run) / (worker._key(s['node_id'], 1) + '.host-brief.json')).exists()


def test_pause_after_the_brief_closes_the_working_window_and_completion_earns_nothing(run):
    s = spec()
    ws = worker.materialize(run, s)
    packet = host_subagent.brief(run, s, ws, transport_id=HOST)
    gw.record_steering(run, 'Pause the study.', effect='pause')
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        with host_subagent.serve_broker(run, s, packet):
            pytest.fail('the broker opened under a pause')
    assert refused.value.missing == ['steering']
    assert not start_record(run, s).exists()
    # A subagent the host started anyway worked outside an admitted window: no receipt is written.
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        host_subagent.complete(run, s, packet, final={'completed': True, 'summary': 'host reported'})
    assert refused.value.missing == ['steering']
    with pytest.raises(ValueError, match='no receipt'):
        worker.load_receipt(run, s['node_id'], s['attempt'])
    # After the acknowledged resume the same attempt is admitted and completes.
    resume(run)
    with host_subagent.serve_broker(run, s, packet):
        assert write_result(packet)['status'] == 'ok'
    receipt = host_subagent.complete(run, s, packet, final={'completed': True, 'summary': 'host reported'})
    assert receipt['attestation'] == 'host_attested' and receipt['broker']['calls'] == 1


def test_admitted_window_records_the_start_and_is_reported_as_running_work(run):
    s = spec()
    ws = worker.materialize(run, s)
    packet = host_subagent.brief(run, s, ws, transport_id=HOST)
    with host_subagent.serve_broker(run, s, packet):
        acknowledged = json.loads(start_record(run, s).read_text())
        assert acknowledged['node_id'] == s['node_id'] and acknowledged['attempt'] == s['attempt']
        assert acknowledged['kind'] == 'host-subagent-start' and acknowledged['host_spawn_observed'] is False
        assert [row['role'] for row in gw.admitted_work(run)] == ['host-subagent']
        # A pause that lands now finds the subagent running: it drains and is reported as such.
        gw.record_steering(run, 'Pause the study.', effect='pause')
        state = gw.steering_state(run)
        assert state['pause_status'] == 'draining' and not state['observed_stopped']
        assert write_result(packet)['status'] == 'ok'
    assert gw.admitted_work(run) == []
    assert gw.steering_state(run)['pause_status'] == 'observed-stopped'
    # Work that started inside the admitted window completes after the pause.
    receipt = host_subagent.complete(run, s, packet, final={'completed': True, 'summary': 'host reported'})
    assert receipt['attestation'] == 'host_attested' and receipt['broker']['calls'] == 1


def test_completion_without_an_admitted_start_writes_no_receipt(run):
    s = spec()
    ws = worker.materialize(run, s)
    packet = host_subagent.brief(run, s, ws, transport_id=HOST)
    with pytest.raises(cli_worker.LaunchRefused, match='start'):
        host_subagent.complete(run, s, packet, final={'completed': True, 'summary': 'host reported'})
    with pytest.raises(ValueError, match='no receipt'):
        worker.load_receipt(run, s['node_id'], s['attempt'])


def test_start_acknowledgement_of_another_attempt_or_brief_does_not_count(run):
    s = spec()
    ws = worker.materialize(run, s)
    packet = host_subagent.brief(run, s, ws, transport_id=HOST)
    with host_subagent.serve_broker(run, s, packet):
        pass
    record = json.loads(start_record(run, s).read_text())
    record['brief_sha256'] = '0' * 64
    start_record(run, s).write_text(json.dumps(record))
    with pytest.raises(cli_worker.LaunchRefused, match='start'):
        host_subagent.complete(run, s, packet, final={'completed': True, 'summary': 'host reported'})


def test_handoff_without_steering_custody_is_refused_under_machine_rules(run, tmp_path, monkeypatch):
    from ravel.workflow import machine_lease as ml
    s = spec()
    ws = worker.materialize(run, s)
    monkeypatch.delenv(ml.TEST_ENV, raising=False)
    monkeypatch.setattr(ml, '_LOCATION', tmp_path / 'machine')
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        host_subagent.brief(run, s, ws, transport_id=HOST)
    assert refused.value.missing == ['steering'] and 'custody is absent' in str(refused.value)
