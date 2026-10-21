"""Explicit operator exports of delivery snapshots; original run permissions never widen."""
from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat

from ravel.controller.authority import mode
from ravel.controller.store import RunStore, StoreError
from ravel.workflow import private_files, provider_policy


class ShareRefused(ValueError):
    def __init__(self, reason, remedy):
        self.reason, self.remedy = reason, remedy
        super().__init__(f'share refused ({reason}): {remedy}')


def _ordinary_path(path):
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise ShareRefused('unsafe_path', f'{entry} is a symbolic link; choose ordinary paths')


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _identity(path):
    _ordinary_path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ShareRefused('unsafe_source', f'{path} must be an ordinary file without hard links')
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def export(store, destination, *, audience, group=None, public=False):
    """Snapshot delivery privately, audit the declared audience, then publish export copies."""
    from ravel.controller.authority.operator import _refuse_agent
    try:
        _refuse_agent('scientific export')
    except ValueError as exc:
        raise ShareRefused('operator_action_required', str(exc) + '; invoke ravel share as the operator') from exc
    if not isinstance(audience, str) or not audience.strip():
        raise ShareRefused('audience_required', 'declare a nonempty audience for this export')
    if type(public) is not bool or public == (group is not None):
        raise ShareRefused('sharing_scope_required', 'choose either an explicit group or the separate public operation')
    problems = store.check_binding()
    if problems:
        raise ShareRefused('run_binding_invalid', '; '.join(problems))
    try:
        frozen = mode.frozen(store)
    except (ValueError, StoreError) as exc:
        raise ShareRefused('frozen_policy_invalid', 'restore the trusted frozen policy: ' + str(exc)) from exc
    policy = frozen.get('provider_policy') if type(frozen) is dict else None
    if (type(policy) is not dict or type(policy.get('record')) is not dict
            or provider_policy.digest(policy['record']) != policy.get('policy_sha256')):
        raise ShareRefused('frozen_policy_invalid', 'restore the trusted frozen provider policy; do not edit run-tree declarations')
    record = policy['record']
    if set(record) != {'declared', 'data_classification'} or type(record['declared']) is not bool:
        raise ShareRefused('frozen_policy_invalid', 'restore a valid trusted classification record')
    classification = record['data_classification']
    if record['declared']:
        try:
            provider_policy.classification(classification)
        except ValueError as exc:
            raise ShareRefused('frozen_policy_invalid', str(exc)) from exc
    elif classification != provider_policy.PUBLIC:
        raise ShareRefused('frozen_policy_invalid', 'restore a valid implicit classification record')
    if public and (record['declared'] is not True or classification.get('level') != 'public'):
        raise ShareRefused('public_export_restricted',
                           'start a separately reviewed run with explicit public classification; do not declassify this run')
    gid = None
    if not public:
        try:
            membership = grp.getgrnam(group)
        except (KeyError, TypeError) as exc:
            raise ShareRefused('group_unavailable', 'choose an existing group in the operator account memberships') from exc
        gid = membership.gr_gid
        if gid not in {*os.getgroups(), os.getgid(), os.getegid()}:
            raise ShareRefused('group_membership_required', 'choose a group in the operator account memberships')
    source = Path(store.run_dir).absolute() / 'delivery'
    destination = Path(os.path.abspath(Path(destination).expanduser()))
    _ordinary_path(source)
    _ordinary_path(destination)
    for protected in (Path(store.run_dir).resolve(), Path(store.store_root).resolve()):
        if destination.is_relative_to(protected) or protected.is_relative_to(destination):
            raise ShareRefused('destination_restricted', 'choose a new destination outside the run and authority store')
    if destination.exists():
        raise ShareRefused('destination_exists', 'choose a new destination; existing exports are never replaced')
    if not source.is_dir():
        raise ShareRefused('delivery_missing', 'complete delivery before exporting scientific artifacts')
    files, directories = [], [source]
    for root, dirs, names in os.walk(source, followlinks=False):
        root = Path(root)
        for name in dirs:
            directory = root / name
            _ordinary_path(directory)
            if not stat.S_ISDIR(directory.lstat().st_mode):
                raise ShareRefused('unsafe_source', 'delivery directories must be ordinary directories')
            directories.append(directory)
        for name in names:
            path = root / name
            files.append((path, _identity(path)))
    if not any(path == source / 'RECEIPT.json' for path, _ in files):
        raise ShareRefused('receipt_missing', 'complete delivery with its original RECEIPT.json before exporting')
    if (source / 'EXPORT.json').exists():
        raise ShareRefused('reserved_member', 'delivery contains reserved EXPORT.json; preserve it outside this export')
    staging = destination.with_name('.' + destination.name + '.export-' + secrets.token_hex(12))
    try:
        private_files.mkdir(staging)
        for directory in directories:
            private_files.mkdir(staging / directory.relative_to(source))
        members = []
        for path, identity in sorted(files):
            if _identity(path) != identity:
                raise ShareRefused('source_changed', 'retry export from a stable completed delivery')
            relative = path.relative_to(source)
            target = staging / relative
            private_files.copy(path, target)
            digest = _hash(target)
            if _identity(path) != identity or _hash(path) != digest:
                raise ShareRefused('source_changed', 'retry export from a stable completed delivery')
            members.append({'path': str(relative), 'sha256': digest, 'bytes': target.stat().st_size})
        manifest = {'schema': 'scientific-export.v1', 'kind': 'public' if public else 'group',
                    'audience': audience.strip(), 'group': group, 'gid': gid,
                    'source_run_id': store.run_id, 'source_run': str(store.run_dir),
                    'destination': str(destination), 'classification': record,
                    'policy_sha256': policy['policy_sha256'], 'members': members,
                    'source_receipt_sha256': next(row['sha256'] for row in members if row['path'] == 'RECEIPT.json')}
        private_files.write(staging / 'EXPORT.json', (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode())
        if store.check_binding():
            raise ShareRefused('run_binding_invalid', 'restore the original run binding before export')
        store.append('scientific-export', manifest)
        for path in [*(staging / row['path'] for row in members), staging / 'EXPORT.json']:
            if gid is not None:
                os.chown(path, -1, gid)
            path.chmod(0o644 if public else 0o640)
        for directory in sorted([staging, *(staging / p.relative_to(source) for p in directories[1:])],
                                key=lambda p: len(p.parts), reverse=True):
            if gid is not None:
                os.chown(directory, -1, gid)
            directory.chmod(0o755 if public else 0o750)
        _ordinary_path(destination)
        if destination.exists():
            raise ShareRefused('destination_exists', 'choose a new destination; existing exports are never replaced')
        os.rename(staging, destination)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='kind', required=True)
    for kind in ('group', 'public'):
        command = sub.add_parser(kind)
        command.add_argument('run_id')
        command.add_argument('destination')
        command.add_argument('--audience', required=True)
        if kind == 'group':
            command.add_argument('--group', required=True)
    args = parser.parse_args(argv)
    try:
        result = export(RunStore(args.run_id), args.destination, audience=args.audience,
                        group=getattr(args, 'group', None), public=args.kind == 'public')
    except (ShareRefused, OSError, ValueError, StoreError) as exc:
        parser.exit(2, str(exc) + '\n')
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
