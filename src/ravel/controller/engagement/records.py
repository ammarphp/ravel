"""JSON records whose custody and clock belong exclusively to RunStore."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from importlib.resources import files
import json

TIERS = ('lean', 'standard', 'full')
DECISION = 'engagement-decision'
ESCALATION = 'engagement-escalation'
CHECK = 'envelope-check'


class EngagementRefused(ValueError):
    """Incomplete or inconsistent controller evidence; never a lowering fallback."""


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def data(name):
    return json.loads(files('ravel').joinpath('data/controller/engagement', name).read_text())


def rows(store, kind):
    # The binding RunStore returns journal envelopes, not bare bodies.
    return [{**deepcopy(e['record']), 'record_id': e['id']} for e in store.scan(kind)]


def latest(store, kind):
    found = rows(store, kind)
    return found[-1] if found else None


def _plan_document(store, pin, inline='plan', blob_field='blob'):
    source = pin.get(inline)
    if source is not None:
        return source
    blob = pin.get(blob_field)
    if isinstance(blob, str) and len(blob) == 64 and all(c in '0123456789abcdef' for c in blob):
        path, expected = 'blobs/' + blob, blob
    elif isinstance(blob, dict):
        path, expected = blob.get('path'), blob.get('sha256')
    else:
        raise EngagementRefused('current plan blob missing')
    if not isinstance(path, str) or path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/')):
        raise EngagementRefused('invalid current plan blob pointer')
    raw = store.path(*path.split('/')).read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise EngagementRefused('current plan blob digest mismatch')
    return json.loads(raw)


def resolve_applied_plan(store, candidate, decision):
    """Resolve a ledger document to its current stored view, preserving both pins.

    The ledger may supply the scientific document while the controller pins the
    applied view. Never manufacture that view from a decision: read its bytes,
    authenticate them and let ``check_applied`` validate the entire projection.
    """
    pin = latest(store, 'plan')
    if not pin or not isinstance(candidate, dict):
        raise EngagementRefused('current applied plan missing')
    source = _plan_document(store, pin)
    scientific_sha = decision['scientific_plan_sha256']
    if (not isinstance(source, dict) or pin.get('plan_sha256') != scientific_sha
            or source.get('sha256') != scientific_sha or candidate.get('sha256') != scientific_sha):
        raise EngagementRefused('current plan differs from the engagement scientific pin')
    if not source.get('engagement'):
        if (source != decision['scientific_plan']
                or digest({k: v for k, v in source.items() if k != 'sha256'}) != scientific_sha):
            raise EngagementRefused('current scientific plan digest mismatch')
        if 'applied_plan' not in pin and 'applied_blob' not in pin:
            return deepcopy(candidate)
        source = _plan_document(store, pin, 'applied_plan', 'applied_blob')
    if isinstance(source, dict) and source.get('engagement'):
        body = deepcopy(source)
        applied_sha = body['engagement'].pop('applied_sha256', None)
        if applied_sha != digest(body) or pin.get('applied_sha256', applied_sha) != applied_sha:
            raise EngagementRefused('current applied plan digest mismatch')
        if candidate != source and candidate != decision['scientific_plan']:
            raise EngagementRefused('supplied plan differs from the current applied view')
        return deepcopy(source)
    raise EngagementRefused('current applied plan missing')


def append(store, kind, record):
    from jsonschema import Draft202012Validator
    body = deepcopy(record)
    body['schema'] = kind + '.v1'
    body['sha256'] = digest(body)
    schema = data('schemas/' + kind + '.v1.json')
    Draft202012Validator(schema).validate(body)
    body['record_id'] = store.append(kind, body)
    return body


def verify(record):
    if record.get('sha256') != digest({k: v for k, v in record.items() if k not in ('sha256', 'record_id')}):
        raise EngagementRefused('engagement record digest mismatch')


def current_tier(store):
    decision = latest(store, DECISION)
    if not decision:
        return 'full'
    verify(decision)
    index = TIERS.index(decision['tier'])
    for event in rows(store, ESCALATION):
        verify(event)
        if event['scope'] == 'run':
            index = max(index, TIERS.index(event['new_tier']))
    return TIERS[index]
