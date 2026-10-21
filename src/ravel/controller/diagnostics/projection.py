"""Prospective ledger population using binding APIs on a disposable store."""
from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .records import DiagnosticsRefused, entries


def project_obligations(store, contexts, *, ledger=None, store_factory=None, catalogue=None):
    """Materialise in isolation; the actual run journal and run directory are never changed.

    Contexts are the controller's complete planned stage/seat contexts, not worker
    declarations. Retry and conditional populations should be supplied explicitly
    with their condition. The peer's own selector and key factory remain authoritative.
    """
    if ledger is None:
        from ravel.controller import ledger
    if store_factory is None:
        from ravel.controller.store import RunStore
        store_factory = RunStore
    if catalogue is None:
        catalogue = json.loads(files('ravel').joinpath('data/obligations/catalogue.json').read_text())
    nodes = {row['id']: row['node'] for row in catalogue['rows']}
    rows, conditions = {}, {}
    with TemporaryDirectory(prefix='diagnostic-projection-') as temporary:
        shadow = store_factory(store.run_id, root=Path(temporary))
        try:
            for event in entries(store, 'ledger'):
                shadow.append('ledger', deepcopy(event['record']))
            for item in contexts:
                stage, context = item['stage'], deepcopy(item['context'])
                selected = ledger.materialise(shadow, stage, context)
                for key in selected:
                    condition = item.get('conditional')
                    if key not in conditions or condition is None:
                        conditions[key] = condition
            for event in entries(shadow, 'ledger'):
                body = event['record'].get('body', {})
                if body.get('event') != 'materialise':
                    continue
                for instance in body.get('instances', []):
                    row_id = instance['id']
                    if row_id not in nodes:
                        raise DiagnosticsRefused('projected obligation lacks catalogue discharge node')
                    rows[instance['key']] = {'key': instance['key'], 'row': row_id,
                                             'scope': deepcopy(instance.get('scope', {})),
                                             'stage': body['stage'], 'discharge_node': nodes[row_id]}
                    if conditions.get(instance['key']) is not None:
                        rows[instance['key']]['conditional'] = conditions[instance['key']]
        finally:
            close = getattr(shadow, 'close', None)
            if close:
                close()
    return [rows[key] for key in sorted(rows)]
