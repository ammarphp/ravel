"""Content-bearing work-order obligations, checked before adoption mutates a run.

The expected obligation list is independently derived from the admitted plan and
claims by the producer of the work order. Never derive it from worker outputs.
This check establishes packet fidelity, not scientific correctness or authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat


def digest(order):
    value = {k: v for k, v in order.items() if k != 'order_sha256'}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=_pairs)


def _path(workspace, relative):
    if not isinstance(relative, str):
        raise ValueError('output path must be a string')
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'outputs':
        raise ValueError('output must stay inside workspace outputs/: ' + relative)
    root = Path(workspace).absolute()
    target = root / path
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError('symlink in output path: ' + relative)
    if not target.is_file() or not stat.S_ISREG(target.stat().st_mode):
        raise ValueError('required regular output missing: ' + relative)
    if target.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('output content check exceeds bounded read: ' + relative)
    return target


def _empty(value):
    return value is None or isinstance(value, (str, list, dict)) and not (value.strip() if isinstance(value, str) else value)


def _pointer(value, pointer):
    if pointer == '':
        return value
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('JSON pointer required')
    for token in pointer[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            if not token.isdecimal():
                raise ValueError('invalid array pointer')
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise ValueError('pointer does not resolve')
    return value


def snapshot(order, workspace):
    """Read once and retain the exact checked bytes for the adopting copy."""
    members = {}
    for output in order['declared_outputs']:
        relative = Path(output['path'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0] != 'outputs':
            raise ValueError('output must stay inside workspace outputs/')
        path = Path(workspace) / output['path']
        if not output['required'] and not path.exists():
            continue
        path = _path(workspace, output['path'])
        before = path.lstat()
        fingerprint = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as stream:
            if fingerprint(os.fstat(stream.fileno())) != fingerprint(before):
                raise ValueError('output changed before checked read: ' + output['path'])
            raw = stream.read(64 * 1024 * 1024 + 1)
            if fingerprint(os.fstat(stream.fileno())) != fingerprint(before):
                raise ValueError('output changed during checked read: ' + output['path'])
        after = path.lstat()
        if fingerprint(before) != fingerprint(after) or len(raw) != before.st_size or any(p.is_symlink() for p in path.parents):
            raise ValueError('output changed while checked: ' + output['path'])
        members[output['path']] = raw
    return members


def check(order, workspace, *, expected_obligations, members=None):
    errors = []
    try:
        if not isinstance(expected_obligations, list) or not isinstance(order.get('obligations'), list):
            return ['independently derived and work-order obligations required']
        canonical = lambda values: {json.dumps(v, sort_keys=True, ensure_ascii=False) for v in values}
        if not canonical(order['obligations']).issuperset(canonical(expected_obligations)):
            errors.append('missing or changed derived work-order obligation')
        ids = [v['id'] for v in order['obligations']]
        if len(ids) != len(set(ids)) or any(not isinstance(v, str) or not v.strip() for v in ids):
            errors.append('unique nonempty obligation IDs required')
        outputs = order.get('declared_outputs')
        if not isinstance(outputs, list) or not outputs:
            return errors + ['declared outputs required']
        paths = [o['path'] for o in outputs]
        if len(paths) != len(set(paths)):
            errors.append('duplicate declared output path')
        if any(type(o.get('required')) is not bool or not isinstance(o.get('kind'), str) or not o['kind'].strip() for o in outputs):
            errors.append('output kind and explicit required flag required')
        if errors:
            return errors
        members = snapshot(order, workspace) if members is None else members
        values = {}
        for output in outputs:
            relative = output['path']
            if relative not in members:
                if output['required']:
                    errors.append('required output missing: ' + relative)
                continue
            raw = members[relative]
            if output['required'] and not raw.strip():
                errors.append('empty required output: ' + relative)
            if output.get('sha256') and hashlib.sha256(raw).hexdigest() != output['sha256']:
                errors.append('output digest differs: ' + relative)
            if relative.endswith('.json'):
                value = json.loads(raw, object_pairs_hook=_pairs)
                if output['required'] and _empty(value):
                    errors.append('empty required JSON output: ' + relative)
                values[relative] = value
        for obligation in order['obligations']:
            relative = obligation['output']
            if relative not in paths or relative not in members:
                errors.append('obligation output omitted: ' + obligation['id'])
                continue
            if not members[relative].strip():
                errors.append('empty obligation output: ' + obligation['id'])
            if not next(o['required'] for o in outputs if o['path'] == relative):
                errors.append('obligation output cannot be optional: ' + obligation['id'])
            pointer = obligation.get('pointer')
            if pointer is not None:
                try:
                    value = _pointer(values[relative], pointer)
                    if _empty(value):
                        errors.append('empty obligation content: ' + obligation['id'])
                except (KeyError, IndexError, ValueError, TypeError):
                    errors.append('obligation pointer does not resolve: ' + obligation['id'])
        return errors
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return errors + ['work-order content refused: ' + str(exc)]


def require_fidelity(order, workspace, *, expected_obligations, members=None):
    errors = check(order, workspace, expected_obligations=expected_obligations, members=members)
    if errors:
        raise ValueError('work-order fidelity: ' + '; '.join(errors))
    return ['check:obligation_coverage', 'check:work_order_content']
