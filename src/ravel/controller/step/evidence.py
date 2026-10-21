"""The worker's broker calls, mirrored into the run store as the step's evidence log (M25).

After an attempt the controller verifies each broker receipt of that attempt against the
broker's custody ledger and appends its call record (action, argument digest, status, output
pins, the validator it ran, the source it retrieved) to the run store. Required-use checks read
this log, never the worker's prose: a knowledge id the final record claims it used without a
query that reached it is labelled unsupported (I07, a LABELLED row), and a run-tree copy of an
observation log is ignored (G13).
"""
from __future__ import annotations

import json

from .services import digest, records

EVIDENCE = 'broker-evidence'
KNOWLEDGE_ACTION = 'knowledge query'


def mirror(store, run_dir, *, step_id, attempt, node_id, worker_attempt):
    """Append the verified broker calls of one worker attempt; returns the mirrored rows."""
    from ravel.workflow import broker
    present = {row.get('receipt_id') for row in records(store, EVIDENCE)
               if row.get('node_id') == node_id and row.get('worker_attempt') == worker_attempt}
    rows = []
    for entry in broker.ledger(run_dir, 'broker'):
        record = entry['record']
        if record['node_id'] != node_id or record['attempt'] != worker_attempt:
            continue
        receipt = broker.verify_broker_receipt(run_dir, {'path': record['path'], 'sha256': record['sha256']},
                                               verify_outputs=False)
        reply = receipt.get('reply') or {}
        row = {'schema_version': 1, 'step_id': step_id, 'attempt': attempt, 'node_id': node_id,
               'worker_attempt': worker_attempt, 'receipt_id': receipt['receipt_id'], 'action': receipt['action'],
               'args_sha256': receipt['args_sha256'], 'status': receipt['status'],
               'error': (reply.get('error') or {}).get('code'), 'derivation': receipt['derivation'],
               'validator_id': receipt['validator_id'] if type(receipt['validator_id']) is str else None,
               'source': receipt.get('source'), 'output_pins': receipt['output_pins'],
               'input_pins': receipt['input_pins'], 'stdout_sha256': receipt['stdout_sha256'],
               'reply_tail_sha256': digest(reply.get('stdout_tail', '')),
               'policy': receipt.get('policy'),
               'knowledge': _knowledge_terms(receipt) if receipt['action'] == KNOWLEDGE_ACTION else None,
               'receipt_sha256': record['receipt_sha256']}
        if row['receipt_id'] not in present:
            row['record_id'] = store.append(EVIDENCE, row)
        rows.append(row)
    return rows


def comparison_rows(store, run_dir, step, observation, observation_id, calls):
    """C11 from confined broker calls under the retained request's unchanged source policy.

    Output phase labels grant no read permission. Both the worker's OS boundary and
    the broker's enforced policy must be observed; missing evidence leaves the row pending.
    ``calls`` comes only from ``mirror``'s verified receipts for this observed attempt.
    """
    from ravel.workflow import broker, knowledge_broker, source_policy
    if step.get('kind') != 'compare' or observation.get('status') != 'ok' or not observation_id or not calls:
        return {}
    isolation = observation.get('isolation') or {}
    inventory = observation.get('tool_inventory') or {}
    if (isolation.get('profile') != 'ravel-sandbox' or isolation.get('user_configuration_loaded') is not False
            or (isolation.get('evidence') or {}).get('confirmed') is not True
            or inventory.get('kind') != 'worker' or inventory.get('backend') not in ('linux', 'macos')
            or inventory.get('equal') is not True or inventory.get('differences') != []
            or inventory.get('mcp_observed') is not True or inventory.get('mcp_error')):
        return {}
    try:
        intakes = records(store, 'intake')
        if len(intakes) != 1:
            return {}
        contract = json.loads(store.get_blob(intakes[0]['contract_blob']))
        expected = source_policy.canonical(contract.get('forbidden_sources', []))
        if knowledge_broker.policy_rows(run_dir) != expected:
            return {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    policy_sha = broker.digest(expected)
    for call in calls:
        policy = call.get('policy') or {}
        if (call.get('step_id') != step['id'] or call.get('node_id') != observation.get('node_id')
                or call.get('worker_attempt') != observation.get('attempt') or not call.get('receipt_id')
                or call.get('status') not in ('ok', 'refused')
                or policy.get('source_restriction_sha256') != policy_sha
                or call['status'] == 'ok' and policy.get('allowlisted') is not True):
            return {}
    if not any(call['status'] == 'ok' for call in calls):
        return {}
    return {'C11': {'status': 'satisfied', 'evidence': {
        'record': observation_id, 'intake': intakes[0]['_record_id'],
        'source_restriction_sha256': policy_sha, 'receipts': [call['receipt_id'] for call in calls],
        'mechanism': 'confined_worker_and_source_bound_broker'}}}


def _knowledge_terms(receipt):
    """The knowledge ids a query reached: its arguments and the ids in its reply."""
    reply = (receipt.get('reply') or {}).get('stdout_tail') or ''
    found = set()
    try:
        value = json.loads(reply)
    except ValueError:
        value = None
    stack = [value]
    while stack:
        item = stack.pop()
        if type(item) is dict:
            for key, child in item.items():
                if key in ('id', 'atlas_id') and type(child) is str:
                    found.add(child)
                stack.append(child)
        elif type(item) is list:
            stack.extend(item)
    return sorted(found)


def knowledge_labels(final, rows):
    """Labels for knowledge ids the final record claims without a query that reached them."""
    claimed = (final or {}).get('knowledge_used') if type(final) is dict else None
    if type(claimed) is not list:
        return []
    reached = {term for row in rows if row['status'] == 'ok' for term in row.get('knowledge') or ()}
    queried = any(row['action'] == KNOWLEDGE_ACTION and row['status'] == 'ok' for row in rows)
    return [{'label': 'knowledge_use_unsupported', 'id': item, 'queried': queried}
            for item in claimed if type(item) is str and item not in reached]


def call_counts(rows):
    return {'broker_calls': len(rows), 'refused': sum(1 for r in rows if r['status'] == 'refused'),
            'knowledge_queries': sum(1 for r in rows if r['action'] == KNOWLEDGE_ACTION)}
