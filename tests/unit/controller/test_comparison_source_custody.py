"""Comparison credit comes from enforced source policy, independently of output labels."""
from copy import deepcopy
import json

import pytest

from ravel.controller import ledger
from ravel.controller.step import evidence, graph
from ravel.workflow import broker, knowledge_broker
from test_p04_support import FakeStore


@pytest.fixture
def subject(tmp_path):
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    restrictions = [{'kind': 'forbidden-source', 'paths': ['private/**'], 'origin': 'harness',
                     'statement': 'Keep private sources restricted after sealing.', 'evidence': []}]
    contract = {'forbidden_sources': restrictions}
    (run / 'inputs/task_contract.json').write_text(json.dumps(contract))
    store = FakeStore(tmp_path / 'store', run_dir=run)
    intake = store.append('intake', {'contract_blob': store.put_blob(json.dumps(contract).encode())})
    workspace = broker.work_root(run) / 'compare' / '1'
    (workspace / 'inputs/private').mkdir(parents=True)
    (workspace / 'outputs').mkdir()
    (workspace / 'inputs/settings.json').write_text('{"value": 3}')
    (workspace / 'inputs/private/value.json').write_text('{"value": 7}')
    (workspace / 'outputs/phase.json').write_text(json.dumps({
        'result_sealed_first': True, 'phase': 'after-delivery', 'label': 'after-sealing'}))
    served = knowledge_broker.SourceBoundBroker(run, workspace, role='calculation', node_id='compare',
                                                attempt=1, allowed_actions=['read'], max_calls=4)
    allowed = served.call({'call_id': 'public-read', 'action': 'read', 'args': {'path': 'inputs/settings.json'}})
    denied = served.call({'call_id': 'private-read', 'action': 'read',
                          'args': {'path': 'inputs/private/value.json'}})
    assert allowed['status'] == 'ok'
    assert denied['status'] == 'refused' and denied['error']['code'] == 'forbidden_source'
    calls = evidence.mirror(store, run, step_id='compare', attempt=1, node_id='compare', worker_attempt=1)
    observation = {'status': 'ok', 'node_id': 'compare', 'attempt': 1,
                   'isolation': {'profile': 'ravel-sandbox', 'user_configuration_loaded': False,
                                 'evidence': {'confirmed': True}},
                   'tool_inventory': {'kind': 'worker', 'backend': 'linux', 'equal': True,
                                      'differences': [], 'mcp_observed': True, 'mcp_error': None}}
    observed = store.append(graph.OBSERVATION, observation)
    return store, run, {'id': 'compare', 'kind': 'compare'}, observation, observed, calls, intake


def _rows(subject):
    store, run, step, observation, observed, calls, _ = subject
    return evidence.comparison_rows(store, run, step, observation, observed, calls)


def test_comparison_records_exact_seat_credit_from_receipted_policy(subject):
    store, run, step, observation, observed, calls, intake = subject
    before = deepcopy((observation, calls))
    value = _rows(subject)['C11']
    assert value['status'] == 'satisfied'
    proof = value['evidence']
    assert proof['record'] == observed and proof['intake'] == intake
    assert proof['source_restriction_sha256'] == broker.digest(knowledge_broker.policy_rows(run))
    assert proof['receipts'] == [row['receipt_id'] for row in calls]
    assert (observation, calls) == before
    ledger.materialise(store, 'intake', {'run_id': store.run_id})
    ledger.materialise(store, 'dispatch', {'run_id': store.run_id, 'step': step['id'],
                                      'seat': 'producer', 'attempt': 1, 'step_kind': 'compare'})
    key = ledger.instance_key('C11', store.run_id, {'step': step['id'], 'seat': 'producer', 'attempt': 1})
    ledger.record(store, key, value['status'], proof)
    assert next(row for row in ledger.current(store) if row['entry'] == key)['status'] == 'satisfied'


@pytest.mark.parametrize('damage', ['no_calls', 'foreign_node', 'foreign_attempt', 'missing_policy',
                                   'changed_policy', 'unallowlisted_success', 'ambiguous_call',
                                   'no_isolation', 'unconfirmed', 'configuration', 'fallback',
                                   'missing_inventory', 'inventory_mismatch', 'foreign_inventory',
                                   'missing_mcp', 'failed_worker', 'foreign_observation', 'changed_contract',
                                   'missing_intake'])
def test_missing_or_foreign_enforcement_proof_keeps_comparison_pending(subject, damage):
    store, run, _, observation, _, calls, _ = subject
    if damage == 'no_calls':
        calls.clear()
    elif damage == 'foreign_node':
        calls[0]['node_id'] = 'other'
    elif damage == 'foreign_attempt':
        calls[0]['worker_attempt'] = 2
    elif damage == 'missing_policy':
        calls[0].pop('policy', None)
    elif damage == 'changed_policy':
        calls[0]['policy'] = {'allowlisted': True, 'source_restriction_sha256': '0' * 64}
    elif damage == 'unallowlisted_success':
        calls[0]['policy'] = {'allowlisted': False,
                              'source_restriction_sha256': broker.digest(knowledge_broker.policy_rows(run))}
    elif damage == 'ambiguous_call':
        calls[0]['status'] = 'ambiguous'
    elif damage == 'no_isolation':
        observation.pop('isolation')
    elif damage == 'unconfirmed':
        observation['isolation']['evidence']['confirmed'] = False
    elif damage == 'configuration':
        observation['isolation']['user_configuration_loaded'] = True
    elif damage == 'fallback':
        observation['isolation']['profile'] = 'cli-policy'
    elif damage == 'missing_inventory':
        observation.pop('tool_inventory')
    elif damage == 'inventory_mismatch':
        observation['tool_inventory']['differences'] = ['extra-root']
    elif damage == 'foreign_inventory':
        observation['tool_inventory']['kind'] = 'launch'
    elif damage == 'missing_mcp':
        observation['tool_inventory']['mcp_observed'] = False
    elif damage == 'failed_worker':
        observation['status'] = 'failed'
    elif damage == 'foreign_observation':
        observation['node_id'] = 'other'
    elif damage == 'changed_contract':
        (run / 'inputs/task_contract.json').write_text('{"forbidden_sources": []}')
    elif damage == 'missing_intake':
        store.entries[:] = [row for row in store.entries if row['kind'] != 'intake']
    assert _rows(subject) == {}


def test_other_step_kinds_acquire_no_comparison_credit(subject):
    subject[2]['kind'] = 'derive'
    assert _rows(subject) == {}
