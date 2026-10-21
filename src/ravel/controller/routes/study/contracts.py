"""Scope and quantity checks for ordinary controller study children.

These checks preserve obligations. They confer no execution authority, review
credit, numerical accuracy or scientific acceptance.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def records(store, kind):
    return [deepcopy(row.get('record', row)) for row in store.scan(kind)]


def relative(value):
    if type(value) is not str or not value or '\\' in value:
        raise ValueError('an ordinary relative artifact path is required')
    path = Path(value)
    if path.is_absolute() or path.as_posix() != value or any(p in ('.', '..') for p in path.parts):
        raise ValueError('artifact path escapes its declared root')
    return path


def pinned_json(root, pin):
    """Read bounded regular bytes without following links in any component."""
    if type(pin) is not dict or set(pin) != {'path', 'sha256'}:
        raise ValueError('an exact path and sha256 pin is required')
    path = relative(pin['path'])
    if type(pin['sha256']) is not str or len(pin['sha256']) != 64:
        raise ValueError('a sha256 pin is required')
    root = Path(root).absolute()
    # Use descriptors for every component, including the supplied root. Resolving
    # first would hide a symlink and turn an untrusted path into a trusted read.
    directory = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in [*root.parts[1:], *path.parts[:-1]]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 2_000_000:
                raise ValueError('bounded regular JSON artifact required')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                raw = stream.read(2_000_001)
            if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != pin['sha256']:
                raise ValueError('artifact bytes differ from their adopted digest')
        finally:
            os.close(fd)
    finally:
        os.close(directory)
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate JSON field')
            out[key] = value
        return out
    def invalid(value):
        raise ValueError('nonfinite JSON value: ' + value)
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    # Reject numeric overflow (e.g. 1e999) as well as explicit NaN/Infinity.
    digest(value)
    return value


def adopted_json(context, artifact):
    """Read only the latest controller-accepted custody record for an artifact."""
    found = [r for r in records(context['store'], 'custody') if r.get('artifact') == artifact]
    if not found or found[-1].get('status') != 'accepted':
        raise ValueError('the controller has not adopted ' + artifact)
    row = found[-1]
    return pinned_json(context['run_dir'], {'path': row['destination'], 'sha256': row['sha256']}), row


def requested(reading, kind, field):
    return [deepcopy(row['value'][field]) for row in reading.get('constraints', [])
            if row.get('type') == kind and type(row.get('value')) is dict and field in row['value']]


def scope(reading, covered, stages):
    """Uncovered deliverables and requested stages remain explicit obligations."""
    expected = [row['id'] for row in reading.get('deliverables', [])]
    if (type(covered) is not list or any(type(v) is not str for v in covered)
            or len(covered) != len(set(covered)) or len(expected) != len(set(expected))):
        raise ValueError('distinct original deliverable ids required')
    if type(stages) is not list or any(type(v) is not str for v in stages) or len(stages) != len(set(stages)):
        raise ValueError('distinct implemented stage ids required')
    if set(covered) - set(expected):
        raise ValueError('study coverage invents an original deliverable')
    missing = [{'id': item, 'kind': 'deliverable', 'reason': 'not covered by this study child'}
               for item in expected if item not in covered]
    missing.extend({'id': 'stage:' + item, 'kind': 'stage', 'reason': 'requested stage has no admitted operation'}
                   for item in requested(reading, 'requested_stage', 'stage') if item not in stages)
    forbidden = set(requested(reading, 'negated_stage', 'stage')) & set(stages)
    if forbidden:
        raise ValueError('study includes an explicitly excluded stage: ' + ', '.join(sorted(forbidden)))
    return missing


def quantity_errors(expected, actual):
    """Exact descriptor continuity; conversions must be separately planned operations.

    The adapter supplies these descriptors from its actual consumed/produced
    contracts. Equality is an integrity check, never physical validation.
    """
    if type(expected) is not dict or type(actual) is not dict:
        return ['quantity descriptors are required']
    fields = ('units', 'statistic', 'basis', 'sign_convention', 'covariance',
              'population', 'perturbative_order', 'process_basis', 'bin_ids')
    return [field + ' changed or missing at the handoff' for field in fields
            if field in expected and (field not in actual or digest(expected[field]) != digest(actual[field]))]


def execution_errors(expected, actual):
    """Compare source-backed generation/analysis facts, including named populations."""
    fields = ('pdf_member', 'generation_settings', 'spectrum', 'invisible_states',
              'beam_energy', 'seed', 'weight_names', 'reentrant', 'merged', 'bin_ids',
              'perturbative_order', 'process_basis')
    errors = quantity_errors(expected, actual)
    errors += [field + ' differs from the approved execution contract' for field in fields
               if field in expected and (field not in actual or digest(expected[field]) != digest(actual[field]))]
    if expected.get('reentrant') is False and actual.get('merged') is True:
        errors.append('a non-reentrant routine cannot be merged')
    if expected.get('single_weight') is True and len(actual.get('weight_names', [])) != 1:
        errors.append('a single-weight routine requires exactly one executed weight')
    return list(dict.fromkeys(errors))


def bind_scope(plan, reading, covered, stages):
    """Narrow a plan without dropping any prior open obligation or reading fact."""
    out = deepcopy(plan)
    missing = scope(reading, covered, stages)
    existing = out.setdefault('open_obligations', [])
    for row in missing:
        if row['id'] not in {r['id'] for r in existing}:
            existing.append(row)
    for row in out.get('deliverables', []):
        if row['id'] not in covered:
            row.update(status='open', reason='not covered by this study child')
            row.pop('step', None)
            row.pop('output', None)
    for node in out.get('steps', []):
        if 'deliverables' in node:
            node['deliverables'] = [item for item in node['deliverables'] if item in covered]
    out['sha256'] = digest({k: v for k, v in out.items() if k != 'sha256'})
    return out
