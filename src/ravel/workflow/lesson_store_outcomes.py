"""Outcome library: one row per completed task, written from receipts only (KM section 2.5).

A row records the run and its originating request digest, the operation, the analysis and
implementation, the basis and certification tier, the model's structural key, result pins and
discrepancy rows. Every pin and metric cites a receipt in the row. ``prior_outcomes`` returns
earlier rows with the same structural key; neither function declares novelty.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re

from .knowledge_atlas import digest, encode
from .lesson_store import _HEX, _excluded, _read_dir, _receipt_ok, _write, origin_errors

LOCAL = Path('.ravel/knowledge/outcomes')
SCHEMA = Path(__file__).resolve().parents[1] / 'data/knowledge/schema/outcome.json'
_NOVELTY = re.compile(r'"novel(?:ty)?"', re.I)


def outcome_row(*, run_id, request_digest, operation, analysis, implementation, basis, certification_tier,
                structural_key, result_pins, discrepancies, metrics, receipts) -> dict:
    """Build an outcome row; ``metrics`` is ``{name: {"value": number, "receipt": <receipt path>}}``."""
    row = {'run': {'id': run_id, 'request_digest': request_digest}, 'operation': operation,
           'result': {'analysis': analysis, 'implementation': implementation, 'basis': basis,
                      'certification_tier': certification_tier, 'structural_key': structural_key,
                      'pins': result_pins, 'discrepancies': discrepancies},
           'metrics': metrics, 'receipts': receipts}
    return {'id': 'outcome:' + digest(encode(row))[:16], **row}


def outcome_errors(row) -> list[str]:
    from jsonschema import Draft202012Validator
    errors = [e.message for e in Draft202012Validator(json.loads(SCHEMA.read_text())).iter_errors(row)]
    if errors:
        return errors
    run = row['run'] if isinstance(row['run'], dict) else {}
    errors += origin_errors({'request_digest': run.get('request_digest'), 'run_id': run.get('id')})
    receipts = row['receipts']
    if not isinstance(receipts, list) or not receipts or not all(map(_receipt_ok, receipts)):
        return errors + ['outcome needs receipts with path and sha256']
    known = {(r['path'], r['sha256']) for r in receipts}
    paths = {r['path'] for r in receipts}
    result = row['result'] if isinstance(row['result'], dict) else {}
    for key in ('analysis', 'implementation', 'basis', 'certification_tier'):
        if not isinstance(result.get(key), str) or not result[key].strip():
            errors.append('result.' + key + ' is required')
    key = result.get('structural_key')
    if key is not None and not _HEX.fullmatch(str(key)):
        errors.append('result.structural_key must be a sha256 signature or null')
    pins = result.get('pins')
    if not isinstance(pins, list) or not pins or any(
            not _receipt_ok(p) or (p['path'], p['sha256']) not in known for p in pins):
        errors.append('every result pin must be one of the row receipts')
    discrepancies = result.get('discrepancies')
    if not isinstance(discrepancies, list) or any(
            not isinstance(d, dict) or d.get('receipt') not in paths for d in discrepancies):
        errors.append('every discrepancy row must cite a row receipt')
    metrics = row['metrics']
    if not isinstance(metrics, dict) or any(
            not isinstance(m, dict) or type(m.get('value')) not in (int, float) or not math.isfinite(m['value'])
            or m.get('receipt') not in paths for m in metrics.values()):
        errors.append('every metric needs a finite value and a row receipt')
    if _NOVELTY.search(json.dumps(row)):
        errors.append('an outcome row never declares novelty')
    expected = 'outcome:' + digest(encode({k: v for k, v in row.items() if k != 'id'}))[:16]
    if row['id'] != expected:
        errors.append('id does not match the row content')
    return errors


def write_outcome(root, row) -> Path:
    """Record the row at task completion; the same id never holds different content."""
    errors = outcome_errors(row)
    if errors:
        raise ValueError('outcome refused: ' + '; '.join(errors))
    path = Path(root) / LOCAL / (row['id'].replace(':', '_') + '.json')
    if path.exists() and json.loads(path.read_text()) != row:
        raise ValueError('a different outcome already holds this id')
    return _write(path, row)


def prior_outcomes(root, structural_key, *, exclusions=()) -> list[dict]:
    """Earlier outcome rows for a structural key, minus harness-excluded ids, runs or requests."""
    tokens = {str(t) for t in exclusions}
    return [r for r in _read_dir(Path(root) / LOCAL)
            if r.get('result', {}).get('structural_key') == structural_key and not _excluded(r, tokens)]
