"""Authenticated campaign deltas; journal storage is not a scientific budget.

The first record and older records remain readable as full snapshots. New records
contain only changes, including appended list members. Every replay verifies the
record chain and every reconstructed state, without retaining copies of prior states.
"""
from copy import deepcopy
from collections import OrderedDict
import hashlib
from pathlib import Path
import threading

from . import candidate_experiments as ce, state_io

KIND = 'research-history-delta.v1'
# The former fixed journal bound. Every full-snapshot record was admitted under it,
# so no campaign receives less journal capacity than it had before deltas.
LEGACY_REVISIONS = 128
_VERIFIED = OrderedDict()
_LOCK = threading.RLock()
_CACHE_ROOTS = 4


def _bytes(root, count):
    """Hash every record's current bytes; file metadata grants no reuse."""
    return tuple(hashlib.sha256((root / 'history' / f'{revision:04d}.json').read_bytes()).hexdigest()
                 for revision in range(count + 1))


def changes(before, after, path=()):
    if type(before) is dict and type(after) is dict:
        result = [{'op': 'delete', 'path': [*path, key]} for key in sorted(before.keys() - after.keys())]
        for key in sorted(after):
            result.extend(changes(before[key], after[key], (*path, key)) if key in before else
                          [{'op': 'set', 'path': [*path, key], 'value': deepcopy(after[key])}])
        return result
    if type(before) is list and type(after) is list and len(after) >= len(before):
        result = []
        for index, prior in enumerate(before):
            result.extend(changes(prior, after[index], (*path, index)))
        if len(after) > len(before):
            result.append({'op': 'append', 'path': list(path), 'value': deepcopy(after[len(before):])})
        return result
    return [] if type(before) is type(after) and before == after else [
        {'op': 'set', 'path': list(path), 'value': deepcopy(after)}]


def apply(state, operations):
    current = deepcopy(state)
    return _apply(current, operations)


def _member(target, key):
    if type(target) is dict and type(key) is str:
        return target[key]
    if type(target) is list and type(key) is int and 0 <= key < len(target):
        return target[key]
    raise ValueError('invalid research history delta path')


def _apply(current, operations):
    """Apply to a replay-owned state; public apply preserves its caller's state."""
    if type(operations) is not list:
        raise ValueError('invalid research history delta operations')
    for row in operations:
        if (type(row) is not dict or type(row.get('op')) is not str
                or row['op'] not in {'set', 'delete', 'append'}):
            raise ValueError('invalid research history delta operation')
        expected = {'op', 'path'} | ({'value'} if row['op'] != 'delete' else set())
        if set(row) != expected or type(row['path']) is not list:
            raise ValueError('invalid research history delta fields')
        target = current
        try:
            for key in row['path'][:-1]:
                target = _member(target, key)
        except KeyError as exc:
            raise ValueError('invalid research history delta path') from exc
        if row['op'] == 'append':
            try:
                target = _member(target, row['path'][-1]) if row['path'] else current
            except KeyError as exc:
                raise ValueError('invalid research history delta path') from exc
            if type(target) is not list or type(row['value']) is not list:
                raise ValueError('research history append requires lists')
            target.extend(deepcopy(row['value']))
        elif not row['path']:
            raise ValueError('research history cannot replace its root')
        elif row['op'] == 'delete':
            key = row['path'][-1]
            if type(target) is not dict or type(key) is not str or key not in target:
                raise ValueError('research history deletes only object members')
            del target[key]
        else:
            key = row['path'][-1]
            if not (type(target) is dict and type(key) is str):
                _member(target, key)
            target[key] = deepcopy(row['value'])
    return current


def capacity(state):
    """Structural ceiling derived from declared seats, rounds and resource limits.

    A charged graph has reservation/observation/effect/context/adoption journal
    edges. Stage rounds add preparation, completion and per-seat joins. Ordinary
    experiments add design, preparation, observation, review and revision edges.
    This ceiling detects runaway journaling; only actual resource/round limits
    are budget exhaustion and may produce a qualified scientific ending. It is
    never below the former fixed bound. Revision ``r`` is admitted only while
    ``r < capacity(state at r - 1)``, at commit and again at every replay.
    """
    contract = state['contract']
    stages = (state.get('methodology') or {}).get('stages', [])
    stage_edges = sum((4 + 2 * len(row['roles'])) * row['bound']['max_rounds'] for row in stages)
    return max(LEGACY_REVISIONS, 1 + stage_edges + 5 * contract['budget']['calls']
               + 16 * contract['max_experiments'] + 2 * len(contract['premises']) + 16)


def replay(root, head, *, through=None):
    """Reconstruct a verified current or historical state from an authenticated head."""
    count = head['revision']
    if (type(count) is not int or count < 0 or (through is not None
            and (type(through) is not int or not 0 <= through <= count))):
        raise ValueError('invalid research history revision')
    root = Path(root).absolute()
    key = ce.digest(head)
    if through is None:
        with _LOCK:
            cached = _VERIFIED.get(root)
        # A known head already passed structural capacity and complete replay.
        # Every file is still read and cryptographically checked on every hit.
        if cached is not None and cached[0] == key and _bytes(root, count) == cached[1]:
            return deepcopy(cached[2])
    selected, checked = None, []
    for current in _states(root, head, checked=checked if through is None else None):
        if current['revision'] == through:
            selected = deepcopy(current)
    if through is None:
        if _bytes(root, count) != tuple(checked):
            raise ValueError('research history changed during replay')
        with _LOCK:
            _VERIFIED[root] = (key, tuple(checked), deepcopy(current))
            _VERIFIED.move_to_end(root)
            while len(_VERIFIED) > _CACHE_ROOTS:
                _VERIFIED.popitem(last=False)
    return selected if through is not None else current


def states(root, head):
    """Yield detached verified states; exhaust to authenticate the complete head.

    Each yielded state has a checked content digest and ancestry up to its revision.
    The iterator retains only the current state, and consumers may retain or mutate
    returned states without changing subsequent reconstruction.
    """
    for current in _states(root, head):
        yield deepcopy(current)


def _states(root, head, *, checked=None):
    count = head['revision']
    if type(count) is not int or count < 0:
        raise ValueError('invalid research history revision')
    current, previous_record = None, None
    for revision in range(count + 1):
        path = root / 'history' / f'{revision:04d}.json'
        before = path.read_bytes() if checked is not None else None
        record = state_io.read_json(path)
        if checked is not None:
            after = path.read_bytes()
            if after != before:
                raise ValueError('research history changed during replay')
            checked.append(hashlib.sha256(after).hexdigest())
        content = {k: v for k, v in record.items() if k != 'sha256'}
        if (record.get('sha256') != ce.digest(content)
                or type(record.get('revision')) is not int or record['revision'] != revision):
            raise ValueError('research history content differs')
        if current is not None and revision >= capacity(current):
            raise ValueError('research journal exceeds its declared structural capacity')
        if record.get('kind') == KIND:
            if (current is None or record['parent_sha256'] != current['sha256']
                    or record['parent_record_sha256'] != previous_record['sha256']):
                raise ValueError('research ancestry differs')
            current = _apply(current, record['changes'])
            if (type(current['revision']) is not int or current['revision'] != revision
                    or current['parent_sha256'] != record['parent_sha256']
                    or current['sha256'] != record['result_sha256']):
                raise ValueError('research history delta result differs')
        else:
            if revision and record['parent_sha256'] != current['sha256']:
                raise ValueError('research ancestry differs')
            current = record.copy()
        if revision == 0 and current.get('parent_sha256') is not None:
            raise ValueError('research ancestry differs')
        if current['sha256'] != ce.digest({k: v for k, v in current.items() if k != 'sha256'}):
            raise ValueError('reconstructed research history content differs')
        previous_record = record
        if revision == count and previous_record != head:
            raise ValueError('research head differs from immutable history')
        yield current
