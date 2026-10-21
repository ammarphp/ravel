"""Read a run's own journal, redacted graph events and checkpoint history only."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from hashlib import sha256
import json
import sqlite3

from .records import CONFIG, EXPECTED, FAULT, FAULT_RESULT, TRANSCRIPT, DiagnosticsRefused, digest, entries

KINDS = (EXPECTED, CONFIG, 'plan', 'route', 'step-dispatch', 'step-observation', 'step-outcome',
         'step-launch', 'step-result', 'step-review-credit', 'instruction-delivery',
         'worker-session', 'worker-completion', 'instruction-ack', 'broker-evidence',
         'broker-model-call', 'sandbox-probe', 'inventory-probe', 'authority', 'authority-wait',
         'envelope-check', 'engagement-decision', 'engagement-escalation', 'ledger',
         'budget-settlement', 'judgment-record', 'judgment-outcome', 'judgment-event', 'rdj-receipt',
         'review-credit', 'step-inventory',
         'review', 'wave', 'wave-result', 'gate', 'admission', 'receipt', 'ending',
         FAULT, FAULT_RESULT, TRANSCRIPT)


def body(entry):
    return entry['record']


def identity(row):
    # A seat's dispatch names its parent step and its observation the derived seat step;
    # the worker node id already encodes the parent, so the seat and attempt identify it.
    return (row.get('seat'), row.get('attempt', 1))


def _graph_files(store):
    """Read SQLite with mode=ro, without importing a graph runtime or deserialising code."""
    checkpoints, events, gaps = [], [], []
    event_path = store.path('graph', 'framework', 'events.jsonl')
    if event_path.exists():
        for number, line in enumerate(event_path.read_text(encoding='utf-8').splitlines(), 1):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError('object required')
                events.append({'line': number, **value})
            except ValueError:
                gaps.append({'kind': 'graph-event', 'line': number, 'reason': 'unreadable event'})
    else:
        gaps.append({'kind': 'graph-event', 'reason': 'not recorded'})
    database = store.path('graph', 'framework', 'graphs.sqlite')
    if database.exists():
        try:
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
                query = ('SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, '
                         'checkpoint, metadata FROM checkpoints '
                         'ORDER BY thread_id, checkpoint_ns, checkpoint_id')
                for thread, namespace, key, parent, value, metadata in connection.execute(query):
                    def byte_digest(item):
                        return sha256(item.encode() if isinstance(item, str) else item or b'').hexdigest()
                    checkpoints.append({'thread_id': thread, 'namespace': namespace, 'checkpoint_id': key,
                                        'parent_checkpoint_id': parent, 'sha256': byte_digest(value),
                                        'metadata_sha256': byte_digest(metadata)})
        except sqlite3.Error as exc:
            gaps.append({'kind': 'checkpoint', 'reason': 'unreadable history: ' + str(exc)})
    else:
        gaps.append({'kind': 'checkpoint', 'reason': 'not recorded'})
    return checkpoints, events, gaps


def observe(store):
    """Returns JSON-safe evidence with original record ids; no run-tree or supplied log lookup."""
    by_kind = {kind: deepcopy(entries(store, kind)) for kind in KINDS}
    # Reports may be requested while workers append. A second read up to the
    # first pass's watermark yields one journal prefix, rather than mixing times.
    cutoff = max((e['seq'] for values in by_kind.values() for e in values), default=0)
    by_kind = {kind: [deepcopy(e) for e in entries(store, kind) if e['seq'] <= cutoff] for kind in KINDS}
    checkpoints, graph_events, gaps = _graph_files(store)
    dispatches = [body(e) for e in by_kind['step-dispatch']]
    observations = [body(e) for e in by_kind['step-observation']]
    workers = {}
    for row in dispatches + observations:
        if row.get('node_id'):
            key = (row['node_id'], row.get('attempt', 1))
            previous = workers.get(key)
            if previous and identity(previous) != identity(row):
                raise DiagnosticsRefused('worker identity maps to multiple seats')
            workers[key] = row
    timeline = []
    for kind, values in by_kind.items():
        for entry in values:
            record = body(entry)
            linked = workers.get((record.get('node_id'), record.get('attempt', 1)), {})
            timeline.append({'record_id': entry['id'], 'kind': kind, 'seq': entry['seq'],
                             'time_ns': entry.get('time_ns'),
                             'node_id': record.get('step_id') or record.get('step') or linked.get('step_id'),
                             'worker_node_id': record.get('node_id'),
                             'seat': record.get('seat', linked.get('seat')),
                             'role': record.get('role', linked.get('role')),
                             'attempt': record.get('attempt'), 'record': record})
    timeline.sort(key=lambda r: r['seq'])
    return {'schema': 'observed-run.v1', 'run_id': store.run_id, 'records': by_kind,
            'journal_cutoff_seq': cutoff,
            'timeline': timeline, 'checkpoints': checkpoints, 'graph_events': graph_events,
            'gaps': gaps, 'sha256': digest({'records': by_kind, 'checkpoints': checkpoints,
                                         'graph_events': graph_events, 'gaps': gaps})}
