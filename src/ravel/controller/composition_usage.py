"""Independent accounting of every controller-launched provider session."""
from __future__ import annotations

import json

from ravel.workflow import broker
from ravel.workflow.transports import provider_usage


def counter(store):
    """Reconcile the supervisor's launch census with authenticated provider result records.

    Neither worker final records nor the controller's attributed usage supply totals.
    A missing, changed or unsupported provider record invalidates the whole reading.
    """
    sessions, problems, seen, attempts = [], [], set(), set()
    try:
        run = broker.ordinary(store.run_dir)
        for entry in broker.ledger(run, 'worker-receipts'):
            row = entry['record']
            key = (row['node_id'], row['attempt'])
            if key in attempts:
                problems.append({'reason': 'provider_attempt_duplicate', 'node_id': key[0], 'attempt': key[1]})
                continue
            attempts.add(key)
            pin = row['pin']
            path = broker.locate(run, pin['path'])
            if path.is_symlink() or broker.sha(path) != pin['sha256']:
                problems.append({'reason': 'provider_receipt_changed', 'node_id': key[0], 'attempt': key[1]})
                continue
            receipt = json.loads(path.read_bytes())
            if receipt.get('status') == 'refused':
                continue  # Supervisor refusal before a process existed: no provider session.
            transport = receipt.get('transport') or {}
            kept = (transport.get('observation') or {}).get('provider_usage')
            found = provider_usage.capture(run, *key, transport.get('agent'))
            reason = None
            if kept is None:
                reason = 'provider_record_missing'
            elif found != kept:
                reason = 'provider_record_changed'
            elif found['status'] != 'reported':
                reason = found['reason']
            elif found['session_id'] != receipt.get('session_id'):
                reason = 'provider_session_mismatch'
            elif found['session_id'] in seen:
                reason = 'provider_session_duplicate'
            if reason:
                problems.append({'reason': reason, 'node_id': key[0], 'attempt': key[1]})
                continue
            seen.add(found['session_id'])
            sessions.append(found)
        # A launched child can fail before publishing its receipt, including children
        # whose route has not yet mirrored a step observation into the controller store.
        for path in broker.custody(run).glob('*.worker.json'):
            launch = json.loads(broker.ordinary(path).read_bytes())
            spec = launch['spec']
            if launch.get('launch') is not None and (spec['node_id'], spec['attempt']) not in attempts:
                problems.append({'reason': 'provider_receipt_missing', 'node_id': spec['node_id'],
                                 'attempt': spec['attempt']})
        for entry in store.scan('step-dispatch'):
            row = entry['record']
            if (row.get('node_id'), row.get('attempt')) not in attempts:
                problems.append({'reason': 'provider_receipt_missing', 'node_id': row.get('node_id'),
                                 'attempt': row.get('attempt')})
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        problems.append({'reason': 'provider_census_unavailable', 'detail': type(exc).__name__})
    record = {'kind': 'provider-counter', 'status': 'unknown' if problems else 'reported',
              'sessions': sessions, 'problems': problems}
    previous = store.latest('provider-counter')
    if not previous or previous['record'] != record:
        store.append('provider-counter', record)
    if problems:
        return {'requests': None, 'tokens': None}
    return {'requests': sum(s['requests'] for s in sessions),
            'tokens': sum(sum(s['usage'].values()) for s in sessions)}


def register():
    from .graph import register_broker_counter
    register_broker_counter(counter)
