"""Assumption-audit coverage: an uncontrolled assumption at the severity floor must appear in the result.

The floor and scale are the K8 row's data in ``knowledge/spawn_rows.json``. The
auditor supplies severities; this check only verifies that the delivered result
reports every uncontrolled item at or above the floor. It grades no physics.
"""
from __future__ import annotations

from ravel.paths import package_data_path
import json


def _row():
    rows = json.loads(package_data_path('knowledge', 'spawn_rows.json').read_text())['rows']
    return next(r for r in rows if r['row'] == 'K8')


def check(audit, result):
    """Return one error per uncontrolled item at or above the floor absent from ``assumptions_reported``."""
    row = _row()
    if not isinstance(audit, dict) or audit.get('kind') != 'assumption-audit' or audit.get('schema_version') != 1:
        raise ValueError('assumption audit record required')
    items = audit.get('items')
    if not isinstance(items, list):
        raise ValueError('assumption audit items must be a list')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] or item['id'] in seen:
            raise ValueError('assumption audit items need unique string IDs')
        seen.add(item['id'])
        severity = item.get('severity')
        if type(severity) is not int or not 1 <= severity <= row['severity_max']:
            raise ValueError('assumption severity must be an integer from 1 to %d: %s' % (row['severity_max'], item['id']))
        if type(item.get('controlled')) is not bool:
            raise ValueError('assumption control status must be boolean: ' + item['id'])
    reported = set((result or {}).get('assumptions_reported', []))
    return ['uncontrolled assumption %s (severity %d) is absent from the result' % (item['id'], item['severity'])
            for item in items if not item['controlled'] and item['severity'] >= row['severity_floor']
            and item['id'] not in reported]
