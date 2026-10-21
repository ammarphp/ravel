"""Independent provider accounting, with real custody and deliberately inert result bytes."""
from __future__ import annotations

import json

import pytest

from ravel.controller import composition_usage, graph, engagement
from ravel.controller.engagement import envelope
from ravel.controller.store import RunStore
from ravel.workflow import agent_worker, broker
from ravel.workflow.transports import provider_usage


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    store = RunStore.create(tmp_path / 'runs' / 'run', root=tmp_path / 'store')
    run, node, attempt = store.run_dir, 'worker', 1
    raw = {'type': 'result', 'session_id': 'session-a', 'num_turns': 2,
           'usage': {'input_tokens': 100, 'cache_creation_input_tokens': 200,
                     'cache_read_input_tokens': 300, 'output_tokens': 40},
           'structured_output': {'usage': {'input_tokens': 999999}, 'requests': 999}}
    capture = agent_worker.capture_path(run, node, attempt, 'stdout')
    capture.write_text(json.dumps(raw))
    kept = provider_usage.capture(run, node, attempt, 'claude')
    receipt = {'node_id': node, 'attempt': attempt, 'session_id': 'session-a', 'status': 'ok',
               'transport': {'agent': 'claude', 'observation': {'provider_usage': kept}},
               'usage': {'input_tokens': 1, 'output_tokens': 1, 'turns': 100}}
    path = run / 'receipt.json'

    def publish():
        path.write_text(json.dumps(receipt))
        ledger = broker.custody(run) / 'worker-receipts.jsonl'
        if ledger.exists():
            ledger.unlink()
        broker.append_ledger(run, 'worker-receipts', {'node_id': node, 'attempt': attempt,
                             'pin': {'path': 'receipt.json', 'sha256': broker.sha(path)}})

    publish()
    identity = {'node_id': node, 'attempt': attempt, 'seat': None}
    store.append('step-dispatch', {**identity, 'purpose': 'producer', 'packet_tokens': 100,
                                   'packet_sha256': 'a' * 64})
    observation = {**identity, 'session_id': 'session-a', 'status': 'completed',
                   'usage': {'reported': True, 'input_tokens': 600, 'output_tokens': 40,
                             'turns': 2, 'cost_usd': 0.01, 'raw': {k: raw['usage'][k]
                                         for k in provider_usage.SPLIT if k != 'output_tokens'}}}
    store.append('step-observation', observation)
    store.append('instruction-delivery', {**identity, 'kind': 'instruction-delivery-session',
                                           'packet_tokens': 100, 'packet_sha256': 'a' * 64})
    return store, raw, capture, receipt, publish, observation


def check(session, *, counts=None, observation=None):
    store = session[0]
    dispatches = [r['record'] for r in store.scan('step-dispatch')]
    observations = [observation or session[-1]]
    deliveries = [r['record'] for r in store.scan('instruction-delivery')]
    expected = {'status': 'ready', 'floor': {'sessions': 1},
                'low': {'calls': 1, 'input_tokens': 1},
                'high': dict.fromkeys(envelope.METRICS, 1000000)}
    return envelope.evaluate(dispatches, observations, deliveries, expected=expected,
                             broker=counts if counts is not None else composition_usage.counter(store))


def test_composition_registers_the_controller_counter_and_ignores_worker_usage(session, monkeypatch):
    monkeypatch.setattr(graph, '_BROKER_COUNTER', [])
    graph.compose_services()
    assert graph._BROKER_COUNTER == [composition_usage.counter]
    assert graph.broker_counts(session[0]) == {'requests': 2, 'tokens': 640}
    result = check(session)
    assert result['accepted_allowed'] and result['floors']['H5']['status'] == 'ok', result
    kept = session[0].latest('provider-counter')['record']
    assert kept['sessions'][0]['usage'] == session[1]['usage']
    assert kept['problems'] == []
    count = len(session[0].scan('provider-counter'))
    composition_usage.counter(session[0])
    assert len(session[0].scan('provider-counter')) == count


@pytest.mark.parametrize('mutation,reason', [
    ('absent', 'provider_record_missing'), ('split', 'provider_usage_split_missing'),
    ('worker', 'provider_usage_split_missing'), ('capture', 'provider_record_changed'),
    ('session', 'provider_session_mismatch')])
def test_missing_or_worker_written_provider_usage_keeps_acceptance_closed(session, mutation, reason):
    store, raw, capture, receipt, publish, _ = session
    if mutation == 'absent':
        del receipt['transport']['observation']['provider_usage']
    elif mutation in ('split', 'worker'):
        if mutation == 'worker':
            del raw['usage']
            raw['structured_output']['usage'] = dict.fromkeys(provider_usage.SPLIT, 1000)
        else:
            del raw['usage']['cache_read_input_tokens']
        capture.write_text(json.dumps(raw))
        receipt['transport']['observation']['provider_usage'] = provider_usage.capture(
            store.run_dir, 'worker', 1, 'claude')
    elif mutation == 'capture':
        capture.write_text(json.dumps({**raw, 'num_turns': 3}))
    else:
        receipt['session_id'] = 'other-session'
    publish()
    result = check(session)
    assert not result['accepted_allowed'] and result['floors']['H5']['status'] != 'ok', result
    assert reason in {r['reason'] for r in store.latest('provider-counter')['record']['problems']}


def test_disagreeing_independent_counter_keeps_acceptance_closed(session):
    for counts in ({'requests': 3, 'tokens': 640}, {'requests': 2, 'tokens': 900}):
        result = check(session, counts=counts)
        assert not result['accepted_allowed'] and result['floors']['H5']['status'] == 'below_floor', result


def test_a_launched_attempt_without_a_receipt_is_unknown(session):
    store = session[0]
    store.append('step-dispatch', {'node_id': 'unsettled', 'attempt': 1})
    assert composition_usage.counter(store) == {'requests': None, 'tokens': None}
    assert store.latest('provider-counter')['record']['problems'][-1]['reason'] == 'provider_receipt_missing'


def test_transport_launch_census_catches_an_unmirrored_missing_session(session):
    store = session[0]
    path = agent_worker._record_path(store.run_dir, 'unmirrored', 1)
    path.write_text(json.dumps({'spec': {'node_id': 'unmirrored', 'attempt': 1}, 'launch': {}}))
    assert composition_usage.counter(store) == {'requests': None, 'tokens': None}
    assert store.latest('provider-counter')['record']['problems'][-1] == {
        'reason': 'provider_receipt_missing', 'node_id': 'unmirrored', 'attempt': 1}


def test_delivery_gate_rechecks_the_provider_record_after_a_good_check(session):
    store = session[0]
    engagement.check_envelope(store, 'deliver', broker=composition_usage.counter(store))
    assert 'EG09' not in {r['row'] for r in engagement.gate_errors(store, 'deliver[accepted]')}
    session[2].unlink()
    assert 'EG09' in {r['row'] for r in engagement.gate_errors(store, 'deliver[accepted]')}
    assert not engagement.receipt_section(store)['accepted_allowed']


@pytest.mark.parametrize('agent', ['codex', 'gemini', 'unknown'])
def test_unreported_provider_split_is_unknown(session, agent):
    record = provider_usage.decode(json.dumps(session[1]), agent)
    assert record['status'] == 'unknown' and record['reason'] == 'provider_usage_split_unavailable'
