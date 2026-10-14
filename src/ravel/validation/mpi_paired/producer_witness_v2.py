"""Add exact byte lengths to a *new* derivative producer witness.

Original child receipts remain immutable. This bridges the shared child's
path/digest artifacts into the paired intake's path/digest/bytes identity. It
does not authorize a native call or upgrade a failed producer.
"""
from pathlib import Path
import copy
import hashlib
import json
import os
import stat


def require(value, message):
    if not value:
        raise ValueError(message)


def _identity(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _read_pin(path, check_budget, *, retain=False, ceiling=None):
    path = Path(path).absolute()
    require('..' not in path.parts, 'Parent traversal is not admitted')
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Symlink input is not admitted')
    before = os.lstat(path)
    require(stat.S_ISREG(before.st_mode), 'Regular artifact required')
    if ceiling is not None:
        require(0 < before.st_size <= ceiling, 'Bounded command receipt required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    parts, count, h = [], 0, hashlib.sha256()
    try:
        require(_identity(os.fstat(fd)) == _identity(before), 'Artifact changed before read')
        while True:
            check_budget()
            maximum = 1024*1024 if ceiling is None else min(1024*1024, ceiling+1-count)
            require(maximum > 0, 'Command receipt exceeded read bound')
            block = os.read(fd, maximum)
            if not block:
                break
            count += len(block); h.update(block)
            if retain:
                parts.append(block)
            if ceiling is not None:
                require(count <= ceiling, 'Command receipt exceeded read bound')
        require(count == before.st_size and _identity(os.fstat(fd)) == _identity(before),
                'Artifact changed during read')
        require(_identity(os.lstat(path)) == _identity(before), 'Artifact path changed during read')
    finally:
        os.close(fd)
    return {'path': str(path), 'sha256': h.hexdigest(), 'bytes': count}, b''.join(parts), _identity(before)


def _strict(raw):
    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, 'Duplicate JSON key'); value[key] = item
        return value
    def invalid(token):
        raise ValueError('Nonfinite JSON '+token)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def complete_receipt(source_pin, output_path, *, owned_output_root, check_budget):
    """Retain one new derivative; all source bytes/producer fields stay strict."""
    check_budget()
    require(set(source_pin) == {'path', 'sha256', 'bytes'}, 'Exact source receipt pin required')
    observed, raw, source_identity = _read_pin(source_pin['path'], check_budget, retain=True, ceiling=1024**2)
    require(observed == source_pin, 'Source command receipt differs')
    receipt = _strict(raw)
    require(receipt.get('status') == 'completed' and receipt.get('actual_returncode') == 0 and
            receipt.get('expected_returncode') == 0 and receipt.get('timed_out', False) is False,
            'Only a clean completed producer may be witnessed')
    require(type(receipt.get('pid')) is int and receipt['pid'] > 0 and
            isinstance(receipt.get('argv'), list) and receipt['argv'] and
            all(type(x) is str and x for x in receipt['argv']), 'Actual producer identity/argv required')
    artifacts = receipt.get('artifacts'); outputs = receipt.get('outputs')
    require(type(artifacts) is list and 1 <= len(artifacts) <= 128 and
            type(outputs) is list and len(outputs) == len(artifacts), 'Complete bounded output census required')
    require(len(set(outputs)) == len(outputs) and all(type(x) is str for x in outputs), 'Distinct literal outputs required')
    root = Path(owned_output_root).absolute()
    require('..' not in root.parts and root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)), 'Regular owned output root required')
    target = Path(output_path).absolute()
    require('..' not in target.parts and target.is_relative_to(root) and
            not any(p.is_symlink() for p in (target, *target.parents)) and
            not os.path.lexists(target) and target != Path(source_pin['path']),
            'Fresh derivative witness below owned output required')
    rows, identities = [], {}
    for item in artifacts:
        require(type(item) is dict and set(item) in ({'path', 'sha256'}, {'path', 'sha256', 'bytes'}),
                'Unsupported raw artifact identity')
        p = Path(item['path'])
        require(p.is_absolute() and '..' not in p.parts and p.is_relative_to(root) and str(p) in outputs, 'Producer artifact outside declared owned outputs')
        actual, _, identity = _read_pin(p, check_budget)
        require(actual['sha256'] == item['sha256'] and
                ('bytes' not in item or type(item['bytes']) is int and actual['bytes'] == item['bytes']),
                'Producer artifact bytes differ')
        require(actual['path'] not in identities, 'Duplicate producer artifact')
        rows.append(actual); identities[actual['path']] = identity
    require({p['path'] for p in rows} == set(outputs), 'Artifact/output census differs')
    require(_identity(os.lstat(source_pin['path'])) == source_identity and
            all(_identity(os.lstat(p)) == value for p, value in identities.items()),
            'Evidence changed before witness publication')
    result = copy.deepcopy(receipt)
    result['artifacts'] = rows
    result['raw_command_receipt'] = observed
    result['artifact_identity_completion'] = {
        'kind': 'same_digest_plus_observed_bytes',
        'source_receipt_unchanged': True,
        'new_native_calls': 0,
        'independent_process_authentication': False,
        'meaning': 'Derivative byte-census observation; ordinary supervisor and final source/output custody remain required.'}
    check_budget()
    with target.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    require(_identity(os.lstat(source_pin['path'])) == source_identity and
            all(_identity(os.lstat(p)) == value for p, value in identities.items()),
            'Evidence changed during witness publication')
    result_pin, _, _ = _read_pin(target, check_budget)
    return result_pin
