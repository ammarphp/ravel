"""Bounded, digest-bound members of a trusted controller acquisition artifact.

A member digest is its canonical identity; ``blob`` is its relative file locator.
Keeping the original logical locator (``blob == path``) preserves source metadata
and downstream readers without another retained representation of the corpus.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from ..confine.inputs import CHUNK, _ordinary, hash_copy

KEY = 'acquired_member_manifest'
MAX_MANIFEST_BYTES = 8 << 20
MAX_MEMBER_ENTRIES = 32768


@contextmanager
def copy_lock(store):
    """Serialize admission through retained writes, including concurrent copy batches."""
    if store is None:
        yield
        return
    from ravel.workflow.state_io import file_lock
    from .services import lock_path
    with file_lock(lock_path(store, 'retained-storage')):
        yield


def member_files(root):
    """Enumerate a finite ordinary tree before sorting its bounded member index."""
    root = Path(root)
    pending, files, count = [root], [], 0
    while pending:
        directory = pending.pop()
        if directory.is_symlink():
            raise ValueError('acquisition member directory is a symbolic link')
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > MAX_MEMBER_ENTRIES:
                    raise ValueError('acquisition member population exceeds its entry ceiling')
                info = entry.stat(follow_symlinks=False)
                path = Path(entry.path)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    files.append(path)
                else:
                    raise ValueError('acquisition member is a symbolic link or special file')
    return sorted(files)


def logical_path(value):
    if (type(value) is not str or not value or '\\' in value
            or any(ord(c) < 32 for c in value) or PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('acquisition member has malformed path')
    return value


def bounded_bytes(path, ceiling=MAX_MANIFEST_BYTES):
    """Read only bounded metadata from one stat-checked ordinary descriptor."""
    with _ordinary(path) as (stream, _):
        raw = stream.read(ceiling + 1)
    if len(raw) > ceiling:
        raise ValueError('acquisition member manifest metadata exceeds its byte ceiling')
    return raw


def load(path):
    # Never decode legacy corpus-sized JSON. The metadata itself has an explicit bound.
    value = json.loads(bounded_bytes(path))
    if type(value) is not dict or 'acquired_members' in value:
        raise ValueError('legacy acquisition embedding is refused')
    return value


def rows(document):
    if 'acquired_members' in document:
        raise ValueError('legacy acquisition embedding is refused')
    manifest = document.get(KEY)
    if type(manifest) is not dict or set(manifest) != {'schema_version', 'members'} or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1:
        raise ValueError('acquisition member manifest has malformed version or fields')
    members = manifest['members']
    if type(members) is not list or len(members) > MAX_MEMBER_ENTRIES:
        raise ValueError('acquisition member manifest needs a member list')
    seen, sizes = set(), {}
    for row in members:
        if type(row) is not dict or set(row) != {'path', 'sha256', 'bytes', 'blob'}:
            raise ValueError('acquisition member manifest has malformed member fields')
        name = logical_path(row['path'])
        if name in seen or name == 'hepdata_manifest.json':
            raise ValueError('acquisition member manifest has duplicate or reserved path')
        seen.add(name)
        if (type(row['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', row['sha256'])
                or type(row['bytes']) is not int or row['bytes'] < 0
                or row['blob'] != name):
            raise ValueError('acquisition member manifest has malformed digest, size or blob')
        if row['sha256'] in sizes and sizes[row['sha256']] != row['bytes']:
            raise ValueError('acquisition members with one digest must have one byte size')
        sizes[row['sha256']] = row['bytes']
    return members


def verify(path, *, attachments=None):
    """Verify exact attached population and every blob without interpreting source fields."""
    path = Path(path)
    members = rows(load(path))
    expected = {row['blob']: row for row in members}
    if attachments is not None:
        wanted = [{k: row[k] for k in ('path', 'sha256', 'bytes', 'blob')} for row in members]
        actual = [{k: row.get(k) for k in ('path', 'sha256', 'bytes', 'blob')} for row in attachments]
        if actual != wanted:
            raise ValueError('acquisition member attachments differ from manifest')
        if any(row.get('destination') != (path.parent / row['blob']).as_posix() for row in attachments):
            raise ValueError('acquisition member attachment destination differs')
    actual = set()
    for item in member_files(path.parent):
        if item != path:
            actual.add(item.relative_to(path.parent).as_posix())
    if actual != set(expected):
        raise ValueError('acquisition member blob population differs')
    for blob, row in expected.items():
        target = path.parent / blob
        if hash_copy(target)[0] != row['sha256'] or target.stat().st_size != row['bytes']:
            raise ValueError('acquisition member bytes or digest changed')
    return members


def copy_checked(source, target):
    """Exclusive private streaming copy with the ordinary-input descriptor race checks."""
    target = Path(target)
    created = False
    try:
        with _ordinary(source) as (stream, mode):
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode & 0o600)
            created = True
            digest = hashlib.sha256()
            with os.fdopen(fd, 'wb') as output:
                while chunk := stream.read(CHUNK):
                    digest.update(chunk)
                    output.write(chunk)
        return digest.hexdigest(), mode
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


def screen_json_keys(path, forbidden):
    """Hash and screen JSON key spellings without retaining the whole document.

    Only a string followed by a colon can be an object key. Escaped spellings
    fit a bounded key buffer; arbitrarily long string values and whitespace stream.
    """
    forbidden = set(forbidden)
    ceiling = 6 * max(map(len, forbidden), default=0)
    found, buffer = set(), bytearray()
    quoted = escaped = oversized = False
    candidate = None
    digest = hashlib.sha256()
    with _ordinary(path) as (stream, _):
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
            for value in chunk:
                if quoted:
                    if not escaped and value == 34:
                        candidate = None
                        if not oversized:
                            try:
                                text = json.loads(b'"' + bytes(buffer) + b'"')
                                candidate = text if text in forbidden else None
                            except (ValueError, UnicodeError):
                                pass
                        quoted = False
                        continue
                    if not oversized:
                        buffer.append(value)
                        if len(buffer) > ceiling:
                            buffer.clear()
                            oversized = True
                    escaped = not escaped and value == 92
                elif value == 34:
                    quoted, escaped, oversized = True, False, False
                    buffer.clear()
                    candidate = None
                elif value in b' \t\r\n':
                    continue
                else:
                    if value == 58 and candidate is not None:
                        found.add(candidate)
                    candidate = None
    return digest.hexdigest(), sorted(found)


def admit_copies(run_dir, copies, *, store=None):
    """Observe capacity and account the exact new copy batch before creating any file.

    This is admission accounting, not a filesystem quota or a headroom reservation.
    Each later copy batch is admitted again against current retained bytes and space.
    """
    import shutil
    from ..confine.resource_admission import RECEIPT_MARGIN_BYTES, retained_bytes
    from .services import StepHold, module
    run = Path(run_dir).resolve(strict=True)
    unique = {Path(target): Path(source) for source, target, *_ in copies if not Path(target).exists()}
    if not unique:
        return None
    needed = sum(source.stat().st_size for source in unique.values())
    bounds, frozen = {}, None
    # Library adoption can operate on an unowned store with no authority record.
    # Controller ownership still requires authenticated authority when records are
    # missing, so deleting a mode row cannot turn a governed copy into that case.
    from ..confine import runs
    governed = store is not None and (bool(store.scan('mode')) or runs.owner_of(run) is not None)
    if governed:
        authority = module('authority')
        provider = getattr(authority, 'frozen', None)
        if not callable(provider):
            raise StepHold('copy_storage_refused', 'governed copies require authenticated resource authority')
        frozen = provider(store, required=True)
        provider = getattr(authority, 'effective_bounds', None)
        if frozen is None or not callable(provider):
            raise StepHold('copy_storage_refused', 'governed copies require current resource bounds')
        bounds = provider(store)
    ceiling = (bounds.get('budgets') or {}).get('retained_disk_bytes')
    floor = (frozen or {}).get('disk_free_floor_bytes') or 0
    roots = [run]
    if store is not None and getattr(store, 'root', None) is not None:
        root = Path(store.root).resolve(strict=True)
        if not root.is_relative_to(run):
            roots.append(root)
    existing = sum(retained_bytes(root) for root in roots)
    projected = existing + needed + RECEIPT_MARGIN_BYTES
    if ceiling is not None and projected > ceiling:
        raise StepHold('copy_storage_refused', 'new input or adoption copies exceed retained_disk_bytes')
    devices = {}
    for target, source in unique.items():
        parent = target.parent
        while not parent.exists():
            parent = parent.parent
        device = parent.stat().st_dev
        item = devices.setdefault(device, {'path': str(parent), 'copy_bytes': 0,
                                          'free_bytes': shutil.disk_usage(parent).free})
        item['copy_bytes'] += source.stat().st_size
    for item in devices.values():
        item['required_free_bytes'] = item['copy_bytes'] + RECEIPT_MARGIN_BYTES + floor
        if item['free_bytes'] < item['required_free_bytes']:
            raise StepHold('copy_storage_refused', 'filesystem cannot cover new copies and receipt margin')
    evidence = {'schema_version': 1, 'kind': 'retained-copy-admission', 'existing_bytes': existing,
                'new_copy_bytes': needed, 'copy_count': len(unique), 'projected_retained_bytes': projected,
                'retained_disk_bytes': ceiling, 'filesystems': list(devices.values()),
                'scope': 'conservative admission accounting; no quota or headroom reservation',
                'headroom_reserved': False}
    if store is not None:
        evidence['record_id'] = store.append('retained-copy-admission', evidence)
    return evidence
