"""Implementation-divergence comparator.

Two ``analysis-author`` workers implement one specification independently. Their
per-region results are compared by code: a region whose difference exceeds the
tolerance, after the combined statistical uncertainty is allowed for, is an A finding
with ``code_check`` evidence. A region present in one implementation only is also
divergence. Agreement within tolerance establishes consistency of the two encodings,
not their correctness against the reference.

Inputs: ``{'regions': {name: {'yield': float, 'stat': float >= 0}}}`` for each
implementation (``stat`` optional, default 0). The review graph reads each author's
final record (``regions``) from its credited receipt; ``record(rundir, point_id, result)``
writes and registers the check result so ``check:<id>`` names it.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

CHECK_RESULT_KIND = 'ravel-check-result'
PRODUCER = 'ravel.validation.divergence'
TOLERANCE = 0.10
DIRECTORY = 'review/divergence'


def _regions(value):
    regions = (value or {}).get('regions') if type(value) is dict else None
    if type(regions) is not dict or not regions:
        return None
    out = {}
    for name, row in regions.items():
        if type(row) is not dict:
            return None
        y, s = row.get('yield'), row.get('stat', 0.0)
        if type(y) not in (int, float) or type(s) not in (int, float) or not math.isfinite(y) or not math.isfinite(s) or s < 0:
            return None
        out[name] = (float(y), float(s))
    return out


def compare(a, b, *, tolerance=TOLERANCE, check_id='review.divergence', sigma=2.0):
    """A ``ravel-check-result``: passed, failed (A findings) or inconclusive (an input is unusable)."""
    left, right = _regions(a), _regions(b)
    base = {'schema_version': 1, 'kind': CHECK_RESULT_KIND, 'check_id': check_id, 'producer': PRODUCER, 'pins': []}
    if left is None or right is None:
        return {**base, 'status': 'inconclusive', 'outcome': 'inputs_missing', 'findings': [],
                'diagnostics': {'unusable': [n for n, v in (('a', left), ('b', right)) if v is None]}}
    findings, rows = [], {}
    for name in sorted(set(left) | set(right)):
        if name not in left or name not in right:
            findings.append(_finding(check_id, name, f'region {name} is implemented by one author only'))
            continue
        (ya, sa), (yb, sb) = left[name], right[name]
        scale = max(abs(ya), abs(yb))
        rel = abs(ya - yb) / scale if scale else 0.0
        allowed = tolerance * scale + sigma * math.hypot(sa, sb)
        rows[name] = {'a': ya, 'b': yb, 'relative_difference': rel, 'allowed_difference': allowed}
        if abs(ya - yb) > allowed:
            findings.append(_finding(check_id, name, f'region {name}: the two implementations give {ya:.6g} and '
                                     f'{yb:.6g} (relative difference {rel:.3g}, tolerance {tolerance:g})'))
    status = 'failed' if findings else 'passed'
    return {**base, 'status': status, 'outcome': 'divergent' if findings else 'consistent', 'findings': findings,
            'diagnostics': {'regions': rows, 'tolerance': tolerance, 'sigma': sigma}}


def _finding(check_id, region, summary):
    return {'id': f'{check_id}:{region}', 'code': 'implementation_divergence', 'materiality': 'A', 'severity': 'A',
            'evidence_class': 'code_check', 'evidence_locators': ['check:' + check_id], 'summary': summary,
            'claim': None, 'location': region, 'status': 'open'}


def check_id_for(point_id):
    return 'divergence.' + ''.join(c if c.isalnum() or c in '_.-' else '-' for c in point_id)[:100]


def record(rundir, point_id, value):
    """Write ``review/divergence/<id>.json`` and register it in RDJ custody; returns the run-relative path."""
    from ravel.workflow import rdj_custody
    from ravel.workflow.state_io import atomic_json
    check_id = check_id_for(point_id)
    value = {**value, 'check_id': check_id, 'point_id': point_id,
             'findings': [{**f, 'id': f"{check_id}:{f['location']}", 'evidence_locators': ['check:' + check_id]}
                          for f in value['findings']]}
    rel = f'{DIRECTORY}/{check_id}.json'
    path = Path(rundir) / rel
    if not path.exists() or json.loads(path.read_text()) != value:
        atomic_json(path, value)
        rdj_custody.register_check_result(rundir, rel)
    return rel


def recorded(rundir, point_ids):
    """The registered divergence results of ``point_ids`` whose bytes are unchanged (an absent one is skipped)."""
    from ravel.workflow import rdj_custody
    found = {}
    for point_id in sorted(point_ids):
        try:
            found[point_id] = rdj_custody.check_result(rundir, check_id_for(point_id))
        except (ValueError, OSError):
            continue
    return found
