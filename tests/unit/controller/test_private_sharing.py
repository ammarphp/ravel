"""Inert trusted-policy controls for explicit delivery exports."""
import grp
import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from ravel.controller import sharing
from ravel.workflow import private_files, provider_policy


@pytest.fixture
def world(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    delivery = run / 'delivery'
    authority = tmp_path / 'authority'
    private_files.mkdir(delivery / 'artifacts')
    private_files.mkdir(authority)
    private_files.write(delivery / 'RECEIPT.json', b'{"original_receipt": true}\n')
    private_files.write(delivery / 'artifacts' / 'result.txt', b'qualified science', mode=0o400)
    record = {'declared': True, 'data_classification': {'level': 'internal', 'allowed_providers': []}}
    frozen = {'provider_policy': {'record': record, 'policy_sha256': provider_policy.digest(record)}}
    monkeypatch.setattr(sharing.mode, 'frozen', lambda store: frozen)
    monkeypatch.setattr(sharing.grp, 'getgrnam', lambda name: SimpleNamespace(gr_gid=os.getgid()))
    class Store:
        run_id = 'run-test'
        run_dir = run
        store_root = authority
        events = []
        def check_binding(self):
            return []
        def append(self, kind, manifest):
            # Even with permissive caller umask, staging stays private until audit.
            staging = next(tmp_path.glob('.*.export-*'))
            assert stat.S_IMODE(staging.stat().st_mode) == 0o700
            for path in staging.rglob('*'):
                assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
            self.events.append((kind, manifest))
    return SimpleNamespace(run=run, delivery=delivery, authority=authority,
                           destination=tmp_path / 'export', store=Store(), record=record, frozen=frozen)


def classify(world, level, declared=True):
    world.record.update(declared=declared, data_classification={
        'level': level, 'allowed_providers': [] if declared else None})
    world.frozen['provider_policy']['policy_sha256'] = provider_policy.digest(world.record)


def test_group_snapshot_private_creation_and_unchanged_originals(world):
    before = {p: stat.S_IMODE(p.stat().st_mode) for p in world.delivery.rglob('*')}
    old = os.umask(0)
    try:
        manifest = sharing.export(world.store, world.destination, group='collaborators', audience='Analysis team')
    finally:
        os.umask(old)
    assert manifest['kind'] == 'group'
    assert manifest['gid'] == os.getgid()
    assert manifest['audience'] == 'Analysis team'
    assert world.store.events == [('scientific-export', manifest)]
    assert json.loads((world.destination / 'EXPORT.json').read_text()) == manifest
    for original, permissions in before.items():
        assert stat.S_IMODE(original.stat().st_mode) == permissions
        exported = world.destination / original.relative_to(world.delivery)
        assert stat.S_IMODE(exported.stat().st_mode) == (0o750 if original.is_dir() else 0o640)
        if original.is_file():
            assert exported.read_bytes() == original.read_bytes()
        assert exported.stat().st_gid == os.getgid()
    assert manifest['source_receipt_sha256'] == hashlib.sha256((world.delivery / 'RECEIPT.json').read_bytes()).hexdigest()
    assert all(row['path'] not in ('authority', '.ravel-run.json') for row in manifest['members'])


@pytest.mark.parametrize('audience', ['', '  ', None])
def test_audience_required(world, audience):
    with pytest.raises(sharing.ShareRefused) as caught:
        sharing.export(world.store, world.destination, group='team', audience=audience)
    assert caught.value.reason == 'audience_required'
    assert not world.destination.exists()


@pytest.mark.parametrize('level,declared', [('restricted', True), ('internal', True), ('public', False)])
def test_public_operation_refuses_nonpublic_or_implicit_policy(world, level, declared):
    classify(world, level, declared)
    with pytest.raises(sharing.ShareRefused) as caught:
        sharing.export(world.store, world.destination, public=True, audience='Everyone')
    assert caught.value.reason == 'public_export_restricted'
    assert 'separately reviewed' in caught.value.remedy
    assert not world.destination.exists()


def test_explicit_public_operation(world):
    classify(world, 'public')
    manifest = sharing.export(world.store, world.destination, public=True, audience='Public release')
    assert manifest['kind'] == 'public'
    assert manifest['group'] is None and manifest['gid'] is None
    assert stat.S_IMODE(world.destination.stat().st_mode) == 0o755
    assert stat.S_IMODE((world.destination / 'EXPORT.json').stat().st_mode) == 0o644
    assert (world.destination / 'RECEIPT.json').read_bytes() == (world.delivery / 'RECEIPT.json').read_bytes()
    assert stat.S_IMODE((world.delivery / 'artifacts' / 'result.txt').stat().st_mode) == 0o400


def test_nonmember_group_refused(world, monkeypatch):
    monkeypatch.setattr(sharing.grp, 'getgrnam', lambda name: SimpleNamespace(gr_gid=987654))
    with pytest.raises(sharing.ShareRefused) as caught:
        sharing.export(world.store, world.destination, group='strangers', audience='Strangers')
    assert caught.value.reason == 'group_membership_required'


@pytest.mark.parametrize('link', ['symlink_file', 'symlink_directory', 'hardlink'])
def test_delivery_links_refused(world, link):
    target = world.delivery / 'artifacts' / 'result.txt'
    path = world.delivery / 'linked'
    if link == 'hardlink':
        os.link(target, path)
    else:
        path.symlink_to(target if link == 'symlink_file' else target.parent,
                        target_is_directory=link == 'symlink_directory')
    with pytest.raises(sharing.ShareRefused, match='unsafe_'):
        sharing.export(world.store, world.destination, group='team', audience='Team')
    assert not world.destination.exists()
    assert not list(world.destination.parent.glob('.*.export-*'))


@pytest.mark.parametrize('destination', ['run', 'authority', 'symlink', 'existing'])
def test_unsafe_or_existing_destination_refused(world, destination):
    if destination == 'run':
        dest = world.run / 'new'
    elif destination == 'authority':
        dest = world.authority / 'new'
    elif destination == 'existing':
        dest = world.destination
        dest.mkdir()
    else:
        dest = world.destination
        dest.symlink_to(world.delivery, target_is_directory=True)
    with pytest.raises(sharing.ShareRefused):
        sharing.export(world.store, dest, group='team', audience='Team')


def test_tampered_frozen_policy_refused(world):
    world.record['data_classification']['level'] = 'public'
    with pytest.raises(sharing.ShareRefused, match='frozen_policy_invalid'):
        sharing.export(world.store, world.destination, public=True, audience='Everyone')


def test_binding_failure_refused(world, monkeypatch):
    monkeypatch.setattr(world.store, 'check_binding', lambda: ['directory replaced'])
    with pytest.raises(sharing.ShareRefused, match='run_binding_invalid'):
        sharing.export(world.store, world.destination, group='team', audience='Team')


def test_audit_failure_cleans_private_staging(world, monkeypatch):
    def failed(*args):
        raise OSError('journal full')
    monkeypatch.setattr(world.store, 'append', failed)
    with pytest.raises(OSError, match='journal full'):
        sharing.export(world.store, world.destination, group='team', audience='Team')
    assert not world.destination.exists()
    assert not list(world.destination.parent.glob('.*.export-*'))


def test_missing_receipt_refused(world):
    (world.delivery / 'RECEIPT.json').unlink()
    with pytest.raises(sharing.ShareRefused, match='receipt_missing'):
        sharing.export(world.store, world.destination, group='team', audience='Team')


def test_dotdot_cannot_bypass_destination_protection(world):
    dest = world.run.parent / 'unused' / '..' / 'run' / 'export'
    with pytest.raises(sharing.ShareRefused, match='destination_restricted'):
        sharing.export(world.store, dest, group='team', audience='Team')


def test_absent_frozen_policy_is_typed_refusal(world, monkeypatch):
    monkeypatch.setattr(sharing.mode, 'frozen', lambda store: None)
    with pytest.raises(sharing.ShareRefused, match='frozen_policy_invalid'):
        sharing.export(world.store, world.destination, group='team', audience='Team')


def test_agent_session_cannot_authorize_sharing(world, monkeypatch):
    monkeypatch.setenv('RAVEL_AGENT_ID', 'inert-agent')
    with pytest.raises(sharing.ShareRefused, match='operator_action_required'):
        sharing.export(world.store, world.destination, group='team', audience='Team')
    assert world.store.events == [] and not world.destination.exists()
