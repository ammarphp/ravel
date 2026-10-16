"""Typed repair versus scope routing. Classification never confers evidence authority."""
from copy import deepcopy
import hashlib
import json

from ravel.paths import package_data_path


def fields():
    schema = json.loads(package_data_path('roles', 'schema', 'outputs', 'findings.v2.json').read_text())
    properties = schema['oneOf'][1]['properties']['items']['items']['properties']
    return {key: deepcopy(properties[key]) for key in ('classification', 'reclassifications')}


def transport_fields():
    """Project into the hosted finite schema subset; semantic digest checks stay live."""
    def convert(value):
        if isinstance(value, list):
            return [convert(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {('anyOf' if k == 'oneOf' else k): convert(v) for k, v in value.items() if k != 'pattern'}
        if 'oneOf' in value:
            result['type'] = 'object'
        elif 'type' not in result and ('const' in value or 'enum' in value):
            result['type'] = 'string'
        return result
    return convert(fields())


def validate(item, *, decider_id=None):
    if 'classification' not in item and 'reclassifications' not in item:
        return None
    from jsonschema import Draft202012Validator
    properties = fields()
    selected = {key: item[key] for key in properties if key in item}
    if 'reclassifications' in selected and 'classification' not in selected:
        raise ValueError('reclassification requires the original classification')
    schema = {'type': 'object', 'properties': properties, 'additionalProperties': False}
    errors = list(Draft202012Validator(schema).iter_errors(selected))
    if errors:
        raise ValueError('invalid finding classification: ' + errors[0].message)
    for row in item.get('reclassifications', []):
        if decider_id is not None and row['actor_id'] != decider_id:
            raise ValueError('only the declared decider may reclassify a finding')
    current = selected.get('classification')
    for row in item.get('reclassifications', []):
        if row['classification']['artifact_sha256'] != current['artifact_sha256']:
            raise ValueError('reclassification cannot change the reviewed artifact digest')
        current = row['classification']
    if current and current['kind'] == 'limitation':
        ids = [row['claim_id'] for row in current['claims']]
        if len(ids) != len(set(ids)):
            raise ValueError('each affected claim needs one limitation effect')
    return deepcopy(current)


def kind(item):
    classification = validate(item)
    return classification['kind'] if classification else 'unclassified'


def reclassify(item, classification, *, actor_id, decider_id, reason):
    if not decider_id or actor_id != decider_id:
        raise ValueError('only the declared decider may reclassify a finding')
    result = deepcopy(item)
    result.setdefault('reclassifications', []).append({
        'actor_id': actor_id, 'reason': reason, 'classification': deepcopy(classification)})
    validate(result, decider_id=decider_id)
    return result


def repair_key(item):
    """Stable across reviewer IDs and request/closure bookkeeping, bound to exact bytes."""
    classification = validate(item)
    if not classification or classification['kind'] != 'defect':
        raise ValueError('classified rework requires a defect with a named target')
    identity = {'code': item.get('code'), 'check_ids': sorted(item.get('check_ids', [])),
                'location': item.get('location', item.get('evidence')),
                'artifact_sha256': classification['artifact_sha256'],
                'target': classification['target']}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def partition(items):
    repairs, limitations = [], []
    for item in items:
        (limitations if kind(item) == 'limitation' else repairs).append(deepcopy(item))
    return repairs, limitations


def limitation_census(items):
    """Full original finding and classification trail accompany every bounded claim."""
    rows = []
    for item in items:
        classification = validate(item)
        if classification and classification['kind'] == 'limitation':
            for claim in classification['claims']:
                rows.append({'finding_id': item['id'], **deepcopy(claim),
                    'artifact_sha256': classification['artifact_sha256'], 'finding': deepcopy(item),
                    'disposition': 'withdrawn' if claim['effect'] == 'invalidates' or claim['bound'] == 'unbounded' else 'qualified'})
    return rows


def require_dispositions(items, rows):
    """Withdrawal is always allowed; a bounded claim may instead remain qualified."""
    by_id = {row['planned_claim_id']: row for row in rows}
    for limit in limitation_census(items):
        row = by_id.get(limit['claim_id'])
        allowed = {'withdrawn'} if limit['disposition'] == 'withdrawn' else {'qualified', 'withdrawn'}
        if row is None or row['disposition'] not in allowed or limit['bound'] not in row['reason']:
            raise ValueError('review limitation requires a visible qualified or withdrawn claim disposition with its bound')
