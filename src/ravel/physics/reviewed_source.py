"""Byte-bound supplied reviews, JSON selectors and typed source refusals."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from .ma5_saf import Capture


class SourceRecordError(ValueError):
    def __init__(self, reason, message, *, details=None):
        self.reason = reason
        self.details = deepcopy(details)
        super().__init__(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def document(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SourceRecordError('invalid_source_record', 'duplicate JSON key')
            result[key] = value
        return result
    def reject(value):
        raise SourceRecordError('invalid_source_record', 'nonfinite JSON constant')
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)
    encoded(result)
    return result


def load(pin, base, kind, missing):
    if pin is None:
        raise SourceRecordError(missing, 'explicit byte-bound ' + kind + ' required')
    capture = Capture()
    path, raw = capture.pin(pin, base)
    value = document(raw)
    import jsonschema
    schema_path = Path(__file__).parents[1] / 'data/source_records/records.schema.json'
    schema_path, schema_raw = capture.read(schema_path, schema_path.parent)
    schema = document(schema_raw)
    try:
        jsonschema.validate(value, {**schema['$defs'][kind], '$defs':schema['$defs']})
    except jsonschema.ValidationError as error:
        raise SourceRecordError('invalid_source_record', error.message) from error
    if value['kind'] != kind:
        raise SourceRecordError('invalid_source_record', 'source-record kind differs')
    sources = {}
    inputs = [{'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}]
    for name, binding in value['sources'].items():
        source, data = capture.pin(binding, path.parent)
        sources[name] = data
        inputs.append({'path': str(source), 'sha256': hashlib.sha256(data).hexdigest()})
    inputs.append({'path':str(schema_path),'sha256':hashlib.sha256(schema_raw).hexdigest()})
    for binding in value['review']['evidence']:
        evidence, data = capture.pin(binding, path.parent)
        inputs.append({'path': str(evidence), 'sha256': hashlib.sha256(data).hexdigest()})
    return value, sources, inputs, capture


def tokens(pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise SourceRecordError('invalid_source_record', 'non-root JSON pointer required')
    result = pointer[1:].split('/')
    if any('~' in part.replace('~0', '').replace('~1', '') for part in result):
        raise SourceRecordError('invalid_source_record', 'invalid JSON pointer escape')
    return [part.replace('~1', '/').replace('~0', '~') for part in result]


def select(value, pointer):
    try:
        for key in tokens(pointer):
            if isinstance(value, list):
                if not key.isdigit() or str(int(key)) != key:
                    raise KeyError(key)
                value = value[int(key)]
            else:
                value = value[key]
        return value
    except (KeyError, IndexError, TypeError) as error:
        raise SourceRecordError('source_scope_mismatch', 'source field missing: ' + pointer) from error


def replace(value, pointer, expected, replacement):
    if encoded(select(value, pointer)) != encoded(expected):
        raise SourceRecordError('source_scope_mismatch', 'source field changed: ' + pointer)
    keys = tokens(pointer)
    parent = value
    for key in keys[:-1]:
        parent = parent[int(key)] if isinstance(parent, list) else parent[key]
    key = int(keys[-1]) if isinstance(parent, list) else keys[-1]
    parent[key] = deepcopy(replacement)
