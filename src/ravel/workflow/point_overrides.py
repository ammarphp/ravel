"""Source-bound, per-point setting changes shared by finite scan drivers.

Admission records authority; it never manufactures an execution approval or a
neighbour result. All evidence and effective settings are byte pinned.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

from .state_io import atomic_json, read_json


_TEXT_SCHEMA = {'type': 'string', 'minLength': 1}
_HASH_SCHEMA = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
DECLARATION_SCHEMAS = {
    'point_override_scope': {'type': 'object', 'additionalProperties': False,
        'required': ['context_sha256', 'fields'], 'properties': {
            'context_sha256': _HASH_SCHEMA,
            'fields': {'type': 'object', 'additionalProperties': {'type': 'object',
                'additionalProperties': False, 'required': ['values', 'physics'], 'properties': {
                    'values': {'type': 'array', 'items': {}}, 'physics': {'type': 'boolean'}}}}}},
    'point_override_amendment': {'type': 'object', 'additionalProperties': False,
        'required': ['context_sha256', 'point_id', 'changes', 'physics_fields'], 'properties': {
            'context_sha256': _HASH_SCHEMA, 'point_id': _TEXT_SCHEMA,
            'changes': {'type': 'object', 'additionalProperties': {}},
            'physics_fields': {'type': 'array', 'items': _TEXT_SCHEMA}}},
}


def validate_declaration(key, value):
    from ravel.validation.validate_task_contract import _schema_errors
    errors = _schema_errors(value, DECLARATION_SCHEMAS[key], key)
    if errors:
        raise ValueError('; '.join(errors))
    digest(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def pin(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def check_pin(value):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'} or pin(value['path']) != value:
        raise ValueError('override evidence or settings changed')
    return Path(value['path'])


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('override requires a nonempty reason and assessment')
    return value


def replace_fields(document, changes):
    """Replace existing fields by JSON pointer, including indexed list members."""
    if not isinstance(changes, dict) or not changes:
        raise ValueError('override requires nonempty changes')
    result = copy.deepcopy(document)
    paths = []
    for address, value in changes.items():
        if not isinstance(address, str) or not address.startswith('/') or re.search(r'~(?![01])', address):
            raise ValueError('override fields must be JSON pointers')
        parts = [p.replace('~1', '/').replace('~0', '~') for p in address[1:].split('/')]
        if any(parts[:len(p)] == p or p[:len(parts)] == parts for p in paths):
            raise ValueError('overlapping override fields')
        paths.append(parts)
        current = result
        try:
            for part in parts[:-1]:
                if isinstance(current, list):
                    index = int(part)
                    if index < 0 or str(index) != part:
                        raise ValueError('invalid list index')
                    current = current[index]
                else:
                    current = current[part]
            key = int(parts[-1]) if isinstance(current, list) else parts[-1]
            if isinstance(current, list) and (str(key) != parts[-1] or key < 0):
                raise ValueError('invalid list index')
            old = current[key]
            if old == value and type(old) is type(value):
                raise ValueError('override must change the declared setting')
            current[key] = copy.deepcopy(value)
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError('override must replace an existing declared field') from exc
    digest(result)  # reject nonfinite and unserializable settings
    return result


def _approved(reference, key):
    from . import allocation_study as allocation
    if not isinstance(reference, dict) or set(reference) != {'rundir', 'route', 'rung', 'approval_files'}:
        raise ValueError('override requires an exact approval reference')
    if reference['route'] not in allocation.ROUTES or reference['rung'] not in allocation.RUNGS or reference['rung'] == 'none':
        raise ValueError('override requires an actual compute approval')
    root = Path(reference['rundir']).resolve()
    _, files = allocation._approval(root, reference['route'], reference['rung'])
    if not files or files != reference['approval_files']:
        raise ValueError('override approval changed')
    matches = []
    for name in files:
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('approval path escapes run')
        doc = read_json(path)
        if key in doc:
            matches.append(doc[key])
    if len(matches) != 1:
        raise ValueError(f'approval must bind exactly one {key}')
    validate_declaration(key, matches[0])
    return matches[0]


def neighbours(point, other, axes):
    """One adjacent axis step; other axes and scenario remain fixed."""
    if point.get('scenario') != other.get('scenario'):
        return False
    a, b = point.get('parameters', point.get('axes')), other.get('parameters', other.get('axes'))
    differences = 0
    for axis in axes:
        name, values = axis['name'], axis['values']
        if a[name] != b[name]:
            if abs(values.index(a[name]) - values.index(b[name])) != 1:
                return False
            differences += 1
    return differences == 1


def _classify(fields, changes):
    physics = []
    outside = []
    for address, value in changes.items():
        rule = fields.get(address)
        if rule is None:
            outside.append(address)
            physics.append(address)  # undeclared fields cannot be called numerical repairs
            continue
        if not isinstance(rule, dict) or set(rule) != {'values', 'physics'} or type(rule['physics']) is not bool or not isinstance(rule['values'], list):
            raise ValueError('override scope requires explicit values and physics classification')
        if digest(value) not in {digest(v) for v in rule['values']}:
            outside.append(address)
        if rule['physics']:
            physics.append(address)
    return physics, outside


def admit(point_id, request, settings, *, point, population, axes, successful, context_sha256, evidence_directory=None):
    """Validate a proposed override against an already-approved field/value scope."""
    required = {'changes', 'reason', 'diagnostics', 'approval'}
    if not isinstance(request, dict) or not required <= set(request) or set(request) - required - {'amendment', 'comparison'}:
        raise ValueError('invalid override record fields')
    effective = replace_fields(settings, request['changes'])
    _text(request['reason'])
    if not isinstance(request['diagnostics'], list) or not request['diagnostics']:
        raise ValueError('override requires diagnostic evidence')
    for evidence in request['diagnostics']:
        check_pin(evidence)
    scope = _approved(request['approval'], 'point_override_scope')
    if scope.get('context_sha256') != context_sha256:
        raise ValueError('override approval belongs to a different grid or scan')
    fields = scope.get('fields', {})
    if not isinstance(fields, dict):
        raise ValueError('override scope fields must be an object')
    physics, outside = _classify(fields, request['changes'])
    if outside:
        if 'amendment' not in request:
            raise ValueError('out-of-scope override requires an amendment')
        amendment = _approved(request['amendment'], 'point_override_amendment')
        if amendment != {'context_sha256': context_sha256, 'point_id': point_id, 'changes': request['changes'], 'physics_fields': sorted(physics)}:
            raise ValueError('amendment does not bind the exact point and changes')
    comparison = request.get('comparison')
    if physics:
        if not isinstance(comparison, dict) or set(comparison) != {'neighbour_id', 'default', 'override', 'assessment'}:
            raise ValueError('physics-setting override requires a neighbour comparison')
        nid = comparison['neighbour_id']
        other = population.get(nid)
        if other is None or other.get('override') or not neighbours(point, other, axes):
            raise ValueError('comparison requires a neighbouring successful default point')
        default_path, override_path = check_pin(comparison['default']), check_pin(comparison['override'])
        default_results = successful(other)
        if not default_results:
            raise ValueError('comparison requires a neighbouring successful default point')
        if default_path == override_path:
            raise ValueError('comparison requires distinct default and override result records')
        # Each supplied comparison arm binds the neighbour coordinates, settings and result.
        for path in (default_path, override_path):
            arm = read_json(path)
            if set(arm) != {'point_id', 'changes', 'result'} or arm['point_id'] != nid or arm['changes'] != ({} if path == default_path else request['changes']):
                raise ValueError('comparison arm must bind neighbour and exact setting changes')
            check_pin(arm['result'])
            if path == default_path and arm['result'] not in default_results:
                raise ValueError('comparison default result is not the successful neighbour output')
        if read_json(default_path)['result']['path'] == read_json(override_path)['result']['path']:
            raise ValueError('comparison requires distinct default and override result files')
        _text(comparison['assessment'])
    record = copy.deepcopy(request)
    if evidence_directory is not None:
        # Retry logs and comparison outputs may be overwritten by ordinary execution.
        # Freeze their verified bytes before forming the durable receipt identity.
        archive = Path(evidence_directory).resolve()
        archive.mkdir(parents=True, exist_ok=True)
        def freeze(source, label):
            before = check_pin(source)
            data = before.read_bytes()
            if hashlib.sha256(data).hexdigest() != source['sha256']:
                raise ValueError('override evidence changed during admission')
            target = archive / (source['sha256'] + '-' + label)
            if target.exists() and target.read_bytes() != data:
                raise ValueError('immutable override evidence archive changed')
            target.write_bytes(data)
            return pin(target)
        record['source_evidence'] = {'diagnostics': copy.deepcopy(record['diagnostics']),
                                     'comparison': copy.deepcopy(record.get('comparison'))}
        record['diagnostics'] = [freeze(p, 'diagnostic-' + str(i)) for i, p in enumerate(record['diagnostics'])]
        if physics:
            for name in ('default', 'override'):
                arm = read_json(check_pin(record['comparison'][name]))
                arm['result'] = freeze(arm['result'], name + '-result')
                target = archive / (digest(arm) + '-' + name + '-arm.json')
                atomic_json(target, arm)
                record['comparison'][name] = pin(target)
    record.update(schema_version=1, point_id=point_id, context_sha256=context_sha256, physics_fields=sorted(physics),
                  authority='amendment' if outside else 'delegated', base_settings_sha256=digest(settings),
                  effective_settings_sha256=digest(effective))
    record['receipt_sha256'] = digest(record)
    return record, effective


def verify(record, settings_path=None, *, authority=True):
    if digest({k: v for k, v in record.items() if k != 'receipt_sha256'}) != record['receipt_sha256']:
        raise ValueError('override receipt changed')
    for evidence in record['diagnostics']:
        check_pin(evidence)
    comparison = record.get('comparison')
    if record['physics_fields']:
        if not comparison:
            raise ValueError('physics-setting override requires a neighbour comparison')
        for arm in ('default', 'override'):
            doc = read_json(check_pin(comparison[arm]))
            check_pin(doc['result'])
    if authority:
        scope = _approved(record['approval'], 'point_override_scope')
        if scope.get('context_sha256') != record['context_sha256']:
            raise ValueError('override approval context changed')
        physics, outside = _classify(scope.get('fields', {}), record['changes'])
        if sorted(physics) != record['physics_fields'] or record['authority'] != ('amendment' if outside else 'delegated'):
            raise ValueError('override authority or physics classification changed')
        if outside:
            amendment = _approved(record['amendment'], 'point_override_amendment')
            if amendment != {'context_sha256': record['context_sha256'], 'point_id': record['point_id'], 'changes': record['changes'], 'physics_fields': sorted(physics)}:
                raise ValueError('amendment does not bind the exact point and changes')
    if settings_path is not None:
        if settings_digest(settings_path) != record['effective_settings_sha256']:
            raise ValueError('effective override settings changed')
    return record['receipt_sha256']


def settings_digest(path):
    path = Path(path)
    if path.suffix == '.toml':
        import tomllib
        return digest(tomllib.loads(path.read_text()))
    return digest(read_json(path))


def toml_text(document):
    """Serialize JSON-valued settings as valid TOML, retaining all parsed fields."""
    def value(v):
        if isinstance(v, dict):
            return '{' + ', '.join(json.dumps(k) + ' = ' + value(x) for k, x in v.items()) + '}'
        if isinstance(v, list):
            return '[' + ', '.join(value(x) for x in v) + ']'
        if v is None:
            raise ValueError('TOML settings cannot contain null')
        return json.dumps(v, allow_nan=False)
    return '\n'.join(json.dumps(k) + ' = ' + value(v) for k, v in document.items()) + '\n'


def metadata(record):
    return {'overridden': bool(record), 'regime': record['reason'] if record else 'default',
            'override': record, 'receipt_sha256': record['receipt_sha256'] if record else None}
