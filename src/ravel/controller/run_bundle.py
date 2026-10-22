"""Operator-authenticated, quiescent controller backups and read-only evidence shares.

Restore retains absolute locators. Mount a replacement filesystem at those
locators; arbitrary locator/checkpoint migrations require a separately reviewed
migration. Neither ordinary resume nor import guesses how to rewrite authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import sqlite3
import stat

from .store import (RunStore, StoreError, RUN_MARKER, INDEX,
                    _path_key, _private_dir, _write_private, _fsync_directory, directory_identity)

SCHEMA = 'controller-run-bundle.v1'
CONTEXT = ['controller-run-bundle', 1]


class BundleRefused(StoreError):
    code = 'run_bundle_refused'


def _refuse(message, remedy):
    error = BundleRefused(message + '; ' + remedy)
    error.remedy = remedy
    raise error


def _regular_tree(root):
    for path in sorted(Path(root).rglob('*')):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _refuse(f'bundle member is linked or not a regular file: {path}',
                    'materialize ordinary files before exporting; never copy live sockets or links')
        yield path


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _copy(source, target):
    _private_dir(target.parent)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with source.open('rb') as src, os.fdopen(fd, 'wb') as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())


def _copy_tree(source, target, *, databases=False):
    _private_dir(target)
    files = list(_regular_tree(source))
    database_paths = {p for p in files if databases and p.suffix in ('.sqlite', '.db')}
    for path in files:
        rel = path.relative_to(source)
        if path.name.endswith('.lock') or path.name in ('journal.lock',):
            continue
        if any(str(path) == str(db) + suffix for db in database_paths for suffix in ('-wal', '-shm')):
            continue
        out = target / rel
        if path in database_paths:
            _private_dir(out.parent)
            with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as src, sqlite3.connect(out) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                    _refuse('checkpoint database failed integrity_check', 'repair from a verified backup')
            os.chmod(out, 0o600)
        else:
            _copy(path, out)
            if _sha(path) != _sha(out):
                _refuse(f'member changed while exporting: {path}', 'stop every writer and retry export')
    directories = [target, *(path for path in target.rglob('*') if path.is_dir())]
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        _fsync_directory(directory)
    _fsync_directory(target.parent)


def _verify_restored_tree(root, prefix, members):
    """Bind copied bytes to the authenticated inventory, including copy-time changes."""
    expected = {name[len(prefix):]: wanted for name, wanted in members.items() if name.startswith(prefix)}
    actual = {path.relative_to(root).as_posix(): path for path in _regular_tree(root)
              if not (prefix == 'store/' and path.relative_to(root).as_posix() == 'RESTORE-PENDING')}
    if set(actual) != set(expected):
        _refuse('restored membership differs from the signed inventory',
                'retain the failed restore for inspection and retrieve a complete unmodified bundle')
    for name, path in actual.items():
        wanted = expected[name]
        if path.stat().st_size != wanted['size'] or _sha(path) != wanted['sha256']:
            _refuse(f'restored member differs from the signed inventory: {prefix}{name}',
                    'retain the failed restore for inspection and retrieve an unmodified bundle')


def export_run(store, destination, *, share_only=False):
    from .authority import issuer, operator, stop, common
    from ..workflow import graph_substrate, state_io
    operator._refuse_agent('ravel operator export-run')
    issuer._key()
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        _refuse('export destination exists', 'choose a new directory with --out')
    if any(parent.is_symlink() for parent in destination.parents):
        _refuse('export destination traverses a symbolic link',
                'choose a new directory at a real path outside the run, store and issuer')
    destination = Path(os.path.abspath(destination))
    if destination.exists() or destination.is_symlink():
        _refuse('export destination exists', 'choose a new directory with --out')
    for root in (store.root, store.run_dir, issuer.home()):
        root = Path(os.path.realpath(root))
        if destination.is_relative_to(root) or root.is_relative_to(destination):
            _refuse('export overlaps protected input state', 'choose --out outside the run, store and issuer')
    if store.verify() or store.check_binding():
        _refuse('run integrity or directory binding failed', 'restore its verified backup before export')
    # Transport-owned login homes are ephemeral credential state, not evidence.
    # A normally reaped worker already removes them. Never share a crash remnant.
    if any(store.root.rglob('*.cli-home')):
        _refuse('a private worker login home still requires supervised cleanup',
                f'finish transport recovery with ravel drive --resume {store.run_id}, then retry export')
    scope = store.graph_scope()
    try:
        with state_io.file_lock(scope / graph_substrate.SCOPE_LOCK, blocking=False):
            if any(p.get('state') == 'running' for p in graph_substrate.processes(scope)):
                _refuse('a process handle is still live', f'ravel operator pause --run {store.run_id} --reason backup')
            if not share_only:
                stop.record_control(store, 'pause', label=common.OPERATOR_COMMAND, source='operator_cli',
                                    evidence={'command': 'ravel operator export-run', 'operator_uid': os.getuid()},
                                    reason='verified run backup; explicit operator resume required')
            # The journal lock seals a consistent prefix; the graph runner lock
            # excludes checkpoint, effect and artifact writers for the snapshot.
            with store.snapshot():
                if store.verify():
                    _refuse('journal changed before snapshot', 'retry after stopping writers')
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                try:
                    os.mkdir(destination, 0o700)
                except FileExistsError:
                    _refuse('export destination exists', 'choose a new directory with --out')
                try:
                    _fsync_directory(destination.parent)
                    _copy_tree(store.run_dir, destination / 'run')
                    _copy_tree(store.root, destination / 'store', databases=True)
                    anchors = []
                    kinds = {entry['kind'] for entry in store._entries}
                    for kind in sorted(kinds):
                        context = issuer.context(store, kind)
                        path = issuer.journal_path(context)
                        if path.exists():
                            common.scan(store, kind)  # authenticate body, order, ids and external membership
                            raw = json.loads(path.read_bytes())
                            issuer.authenticate(raw, ['journal', context])
                            _write_private(destination / path.name, path.read_bytes(), exclusive=True)
                            anchors.append({'kind': kind, 'name': path.name, 'context': context})
                    members = {p.relative_to(destination).as_posix(): {'sha256': _sha(p), 'size': p.stat().st_size}
                               for p in _regular_tree(destination)}
                    manifest = issuer.seal({'schema': SCHEMA, 'run_id': store.run_id,
                                           'run_dir': str(store.run_dir), 'store_root': str(store.store_root),
                                           'original_run': store.run_record(), 'head': store.head(),
                                           'share_only': bool(share_only), 'anchors': anchors, 'members': members,
                                           'export_id': secrets.token_hex(16)}, CONTEXT)
                    _write_private(destination / 'BUNDLE.json',
                                   (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode(), exclusive=True)
                except BaseException:
                    shutil.rmtree(destination, ignore_errors=True)
                    raise
    except ValueError as exc:
        if 'another process owns' in str(exc):
            _refuse('the controller is running', f'ravel operator pause --run {store.run_id} --reason backup')
        raise
    return {'bundle': str(destination), 'run_id': store.run_id, 'share_only': bool(share_only),
            'manifest_sha256': _sha(destination / 'BUNDLE.json'), 'head': manifest['head'],
            'next_action': ('inspect BUNDLE.json and member digests; this share cannot be restored' if share_only else
                            shlex.join(['ravel', 'operator', 'restore-run', '--bundle', str(destination)]))}


def verify_bundle(bundle, *, authenticate=True):
    from .authority import issuer
    bundle = Path(bundle).expanduser().absolute()
    if bundle.is_symlink() or any(p.is_symlink() for p in bundle.parents):
        _refuse('bundle path traverses a link', 'use the real private bundle directory')
    manifest = json.loads((bundle / 'BUNDLE.json').read_bytes())
    if manifest.get('schema') != SCHEMA:
        _refuse('unknown bundle schema', 'use the exporting RAVEL installation')
    if authenticate:
        issuer.authenticate(manifest, CONTEXT)
    actual = {p.relative_to(bundle).as_posix() for p in _regular_tree(bundle)} - {'BUNDLE.json'}
    if actual != set(manifest['members']):
        _refuse('bundle membership differs from its manifest', 'retrieve a complete unmodified bundle')
    for name, wanted in manifest['members'].items():
        if name.startswith('/') or '..' in Path(name).parts:
            _refuse('unsafe bundle member name', 'retrieve an unmodified bundle')
        path = bundle / name
        if path.stat().st_size != wanted['size'] or _sha(path) != wanted['sha256']:
            _refuse(f'bundle digest mismatch: {name}', 'retrieve an unmodified bundle')
    # Audit the actual exported journal and blobs, not just the signed inventory.
    snapshot = RunStore.__new__(RunStore)
    from .store import GENESIS, _thread_lock
    snapshot.run_id, snapshot.root = manifest['run_id'], bundle / 'store'
    snapshot.store_root = bundle
    snapshot._lock, snapshot._entries, snapshot._by_id = _thread_lock(snapshot.root), [], {}
    snapshot._offset, snapshot._head, snapshot._connections = 0, GENESIS, []
    snapshot._refresh()
    snapshot._check_head()
    if {'seq': len(snapshot._entries), 'digest': snapshot._head} != manifest['head']:
        _refuse('exported journal/head does not verify', 'retrieve a complete unmodified bundle')
    for path in (bundle / 'store' / 'blobs').glob('*'):
        if path.name != _sha(path):
            _refuse('exported blob identity differs', 'retrieve an unmodified bundle')
    for path in (bundle / 'store').rglob('*.sqlite'):
        with sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True) as connection:
            if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                _refuse('exported checkpoint database is corrupt', 'retrieve a verified backup')
    return manifest


def restore_run(bundle):
    from .authority import issuer, operator, stop, common
    from .store import store_root
    from ..workflow import effect_ledger
    operator._refuse_agent('ravel operator restore-run')
    manifest = verify_bundle(bundle)
    if manifest['share_only']:
        _refuse('read-only share cannot restore authority', 'request an operator export without --share-only')
    base = store_root()
    if str(base) != manifest['store_root']:
        _refuse('restore requires the original store locator',
                f'mount the replacement filesystem at {manifest["store_root"]} and configure that store_root; '
                'arbitrary checkpoint/authority locator migration is not admitted')
    run_dir, store_dir = Path(manifest['run_dir']), base / manifest['run_id']
    if any(p.exists() or p.is_symlink() for p in (run_dir, store_dir)):
        _refuse('restore destination already exists', 'preserve existing state separately; restore only into absent '
                'original run and store paths')
    if any(parent.is_symlink() for target in (run_dir, store_dir) for parent in target.parents):
        _refuse('restore destination traverses a symbolic link',
                'mount the replacement filesystem at the original real locators')
    # A newer external authority history makes this a stale backup. Never roll
    # it back, since that could redispatch an already completed external effect.
    for anchor in manifest['anchors']:
        target = issuer.journal_path(anchor['context'])
        raw = (Path(bundle) / anchor['name']).read_bytes()
        issuer.authenticate(json.loads(raw), ['journal', anchor['context']])
        if target.exists() and target.read_bytes() != raw:
            _refuse('newer or conflicting external authority history exists',
                    'restore the latest export; retain this bundle as read-only evidence')
    try:
        _private_dir(store_dir)
        _write_private(store_dir / 'RESTORE-PENDING', b'restore incomplete; do not resume\n', exclusive=True)
        _copy_tree(Path(bundle) / 'run', run_dir)
        _copy_tree(Path(bundle) / 'store', store_dir)
        _verify_restored_tree(run_dir, 'run/', manifest['members'])
        _verify_restored_tree(store_dir, 'store/', manifest['members'])
        for anchor in manifest['anchors']:
            target = issuer.journal_path(anchor['context'])
            raw = (Path(bundle) / anchor['name']).read_bytes()
            wanted = manifest['members'][anchor['name']]
            if len(raw) != wanted['size'] or hashlib.sha256(raw).hexdigest() != wanted['sha256']:
                _refuse('authority anchor changed while restoring', 'retrieve an unmodified bundle')
            if not target.exists():
                _write_private(target, raw, exclusive=True)
        store = RunStore(manifest['run_id'], root=base)
        info = run_dir.stat()
        binding = {**manifest['original_run'], 'dev': info.st_dev, 'ino': info.st_ino,
                   'restored_from': manifest['export_id'], 'predecessor_head': manifest['head'],
                   'identity': secrets.token_hex(16)}
        store.append('run-restoration', binding)
        marker = json.loads((run_dir / RUN_MARKER).read_bytes())
        marker['restoration_identity'] = binding['identity']
        _write_private(run_dir / RUN_MARKER, (json.dumps(marker, sort_keys=True) + '\n').encode())
        index = _private_dir(base / INDEX)
        _write_private(index / f'path-{_path_key(run_dir)}.json', json.dumps({
            'run_id': store.run_id, 'run_dir': str(run_dir), **directory_identity(run_dir)}).encode())
        # No old live handle may be targeted on this machine. Keep the bytes
        # as evidence, remove the active registry, and fence capabilities.
        scope = store.graph_scope()
        for relative in ('agent-work/processes.json', 'framework/locks/scope.json'):
            path = scope / relative
            if path.exists():
                os.replace(path, path.with_name(path.name + '.restored-evidence'))
                _fsync_directory(path.parent)
        effect_ledger.bump_epoch(scope, 'cancellation')
        effect_ledger.bump_epoch(scope, 'runner')
        from .confine import capability
        revoked = {row['record'].get('launch_id') for row in store.scan(capability.REVOKED)}
        for row in store.scan(capability.KIND):
            launch_id = row['record'].get('launch_id')
            if launch_id not in revoked:
                capability.revoke_capability(store, launch_id)
                revoked.add(launch_id)
        if store.verify():
            _refuse('restored journal failed verification', 'retain the failed restore for inspection; do not resume')
        (store_dir / 'RESTORE-PENDING').unlink()
        _fsync_directory(store_dir)
        if store.check_binding():
            _refuse('restored binding failed verification', 'retain the failed restore for inspection; do not resume')
        return {'run_id': store.run_id, 'restoration_identity': binding['identity'], 'head': store.head(),
                'next_action': f'ravel operator resume --run {store.run_id} --reason restored; '
                               f'ravel drive --resume {store.run_id}'}
    except BaseException:
        # Preserve failed state for audit. Ordinary resume refuses until the
        # restore is complete; never overwrite an existing destination on retry.
        if store_dir.is_dir():
            _write_private(store_dir / 'RESTORE-FAILED', b'restore incomplete; do not resume\n')
        raise
