"""Explicit controller policy joins: no environment policy fallback or positive acceptance claim."""
import hashlib
import json
import os
from pathlib import Path

import pytest


class MemoryStore:
    """Minimal bare/nested append-only store protocol; no controller service dependency."""
    def __init__(self, root, *, nested=True):
        self.root = root.resolve()
        self.root.mkdir(parents=True)
        self.records = {}
        self.nested = nested

    def path(self, *parts):
        return self.root.joinpath(*parts)

    def append(self, kind, record):
        rows = self.records.setdefault(kind, [])
        rows.append(dict(record))
        return f'{kind}-{len(rows)}'

    def scan(self, kind):
        return [{'record': dict(row)} if self.nested else dict(row)
                for row in self.records.get(kind, [])]


def sources(path, fingerprints=('private example',)):
    path.write_text(json.dumps({'kind': 'restricted-sources', 'fingerprints': list(fingerprints)}))
    return path


def own(monkeypatch, store, run):
    from ravel.controller.confine import policy
    monkeypatch.setattr(policy.runs, 'owner_of', lambda path: ('owned', run))
    monkeypatch.setattr(policy.runs, 'store', lambda run_id: store)


@pytest.mark.parametrize('nested', [False, True])
def test_SW22_missing_pin_never_uses_environment_file(tmp_path, monkeypatch, nested):
    from ravel.controller.confine import policy
    store = MemoryStore(tmp_path / 'store', nested=nested)
    run = tmp_path / 'run'
    run.mkdir()
    supplied = sources(tmp_path / 'env-policy.json')
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(supplied))
    own(monkeypatch, store, run)
    with pytest.raises(policy.SourcePolicyRefused, match='exactly one'):
        policy.restricted_sources(run)
    monkeypatch.setattr(policy.runs, 'operator_settings', lambda: {})
    monkeypatch.setattr(policy.identity, 'require_governed_install', lambda **kwargs:
                        {'kind': 'installed', 'governed': True, 'label': None})
    with pytest.raises(policy.SourcePolicyRefused):
        policy.admission(store, run_dir=run)
    assert store.scan(policy.SOURCE_KIND) == []


@pytest.mark.parametrize('nested', [False, True])
def test_SW22_changed_or_removed_pin_cannot_be_replaced_by_env(tmp_path, monkeypatch, nested):
    from ravel.controller.confine import policy
    store = MemoryStore(tmp_path / 'store', nested=nested)
    run = tmp_path / 'run'
    run.mkdir()
    original = sources(tmp_path / 'policy.json')
    alternative = sources(tmp_path / 'replacement.json')
    pin = policy.freeze_sources(store, original, run_dir=run)
    assert pin['path'] == str(original.resolve())
    assert pin['sha256'] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert policy.freeze_sources(store, original, run_dir=run) == pin
    assert len(store.scan(policy.SOURCE_KIND)) == 1
    own(monkeypatch, store, run)
    assert policy.restricted_sources(run / 'outputs') == str(original.resolve())
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(alternative))
    sources(original, ['different restriction'])
    with pytest.raises(policy.SourcePolicyRefused, match='bytes differ'):
        policy.restricted_sources(run)
    with pytest.raises(policy.SourcePolicyRefused, match='pinned differently'):
        policy.freeze_sources(store, alternative, run_dir=run)
    original.unlink()
    with pytest.raises(policy.SourcePolicyRefused):
        policy.restricted_sources(run)


def test_source_pin_refuses_duplicate_records(tmp_path, monkeypatch):
    from ravel.controller.confine import policy
    store = MemoryStore(tmp_path / 'store')
    run = tmp_path / 'run'
    run.mkdir()
    path = sources(tmp_path / 'policy.json')
    pin = policy.freeze_sources(store, path)
    store.append(policy.SOURCE_KIND, pin)
    own(monkeypatch, store, run)
    with pytest.raises(policy.SourcePolicyRefused, match='exactly one'):
        policy.restricted_sources(run)
    with pytest.raises(policy.SourcePolicyRefused, match='pinned differently'):
        policy.freeze_sources(store, path)


@pytest.mark.parametrize('kind', ['relative', 'symlink', 'hardlink', 'directory', 'empty', 'array', 'ineffective'])
def test_source_policy_must_be_absolute_ordinary_effective_json(tmp_path, kind):
    from ravel.controller.confine import policy
    store = MemoryStore(tmp_path / 'store')
    original = sources(tmp_path / 'policy.json')
    target = tmp_path / 'selected'
    if kind == 'relative':
        target = Path('policy.json')
    elif kind == 'symlink':
        target.symlink_to(original)
    elif kind == 'hardlink':
        os.link(original, target)
    elif kind == 'directory':
        target.mkdir()
    elif kind == 'empty':
        target.write_text('')
    elif kind == 'array':
        target.write_text('["wrong format"]')
    else:
        sources(target, ['# ignored', 'a'])
    with pytest.raises(policy.SourcePolicyRefused):
        policy.freeze_sources(store, target)
    assert store.scan(policy.SOURCE_KIND) == []


def test_sources_are_compatible_with_actual_generality_format(tmp_path):
    from ravel.controller.confine import policy
    from ravel.validation.check_generality import _external_entries
    store = MemoryStore(tmp_path / 'store')
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps({'kind': 'restricted-sources', 'fingerprints': ['private phrase'],
                                'documents': [{'sha256': 'a' * 64}]}))
    policy.freeze_sources(store, path)
    entries, documents = _external_entries({'RAVEL_RESTRICTED_SOURCES': str(path)})
    assert len(entries) == 1 and documents == ['a' * 64]


@pytest.mark.parametrize('location', ['store', 'run', 'package', 'checkout'])
def test_policy_is_outside_governed_locations(tmp_path, monkeypatch, location):
    from ravel.controller.confine import policy
    store = MemoryStore(tmp_path / 'store')
    run = tmp_path / 'run'
    run.mkdir()
    package = tmp_path / 'installed' / 'ravel'
    package.mkdir(parents=True)
    fake_file = package / 'controller' / 'confine' / 'policy.py'
    # __file__ is only used to locate the package tree; the fixture never edits installed code.
    monkeypatch.setattr(policy, '__file__', str(fake_file))
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    monkeypatch.setattr(policy.identity, '_checkout', lambda package: checkout)
    root = {'store': store.root, 'run': run, 'package': package, 'checkout': checkout}[location]
    path = sources(root / 'policy.json')
    with pytest.raises(policy.SourcePolicyRefused, match='outside store'):
        policy.freeze_sources(store, path, run_dir=run)


@pytest.mark.parametrize('selector', ['RAVEL_ROOT', 'RAVEL_ADDON_PATH', 'RAVEL_NATIVE_BIN', 'RAVEL_NATIVE_BUILD', 'BUILD_DIR'])
def test_SW23_SW29_admission_records_identity_and_refuses_redirected_code(tmp_path, monkeypatch, selector):
    from ravel.controller.confine import policy
    store = MemoryStore(tmp_path / 'store')
    path = sources(tmp_path / 'policy.json')
    monkeypatch.setattr(policy.runs, 'operator_settings', lambda: {'restricted_sources': str(path)})
    installed = {'kind': 'installed', 'package_dir': '/read-only/site-packages/ravel',
                 'writable_by_controller_user': False, 'symlinks': [], 'selectors': {}}
    monkeypatch.setattr(policy.identity, 'code_identity', lambda: dict(installed))
    accepted = policy.admission(store)
    assert accepted['governed'] is True
    assert store.scan('code-identity')[0]['record'] == accepted
    installed['selectors'] = {selector: '/unapproved'}
    with pytest.raises(policy.identity.UngovernedInstall):
        policy.admission(store)
    from ravel.controller.execution_manifest import ExecutionRefused
    with pytest.raises(ExecutionRefused, match='original source identity'):
        policy.admission(store, development=True)
    assert len(store.scan('code-identity')) == 1  # the first intake pin cannot be replaced
    fresh = MemoryStore(tmp_path / 'development-store')
    development = policy.admission(fresh, development=True)
    assert development['governed'] is False and development['label'] == policy.identity.NOT_GOVERNED
    assert len(store.scan(policy.SOURCE_KIND)) == 1


def test_development_requires_source_policy_and_labels_even_installed_code(tmp_path, monkeypatch):
    from ravel.controller.confine import policy
    store = MemoryStore(tmp_path / 'store')
    monkeypatch.setattr(policy.identity, 'require_governed_install', lambda **kwargs:
                        {'kind': 'installed', 'governed': True, 'label': None})
    monkeypatch.setattr(policy.runs, 'operator_settings', lambda: {})
    with pytest.raises(policy.SourcePolicyRefused):
        policy.admission(store, development=True)
    assert store.scan('code-identity')[0]['record']['label'] == policy.identity.NOT_GOVERNED


@pytest.mark.parametrize('value', [-1, True, 1.5, '100', None])
def test_SW24_operator_ceiling_requires_nonnegative_strict_integer(tmp_path, monkeypatch, value):
    from ravel.controller.confine import policy
    monkeypatch.setattr(policy.runs, 'owner_of', lambda path: ('owned', tmp_path))
    monkeypatch.setattr(policy.runs, 'operator_settings', lambda: {'procedure_byte_ceiling': value})
    with pytest.raises(ValueError, match='nonnegative integer'):
        policy.export_ceiling(tmp_path, 100)


def test_SW24_operator_ceiling_ignores_environment_and_legacy_is_explicit(tmp_path, monkeypatch):
    from ravel.controller.confine import policy
    monkeypatch.setenv('RAVEL_PROCEDURE_BYTE_CEILING', '999999')
    monkeypatch.setenv('RAVEL_EXPORT_BYTE_CEILING', '999999')
    monkeypatch.setattr(policy.runs, 'owner_of', lambda path: ('owned', tmp_path))
    monkeypatch.setattr(policy.runs, 'operator_settings', lambda: {'procedure_byte_ceiling': 0})
    assert policy.export_ceiling(tmp_path, 100) == 0
    monkeypatch.setattr(policy.runs, 'operator_settings', lambda: {})
    assert policy.export_ceiling(tmp_path, 100) == 100
    monkeypatch.setattr(policy.runs, 'owner_of', lambda path: None)
    assert policy.export_ceiling(tmp_path, 100) is None
    assert policy.restricted_sources(tmp_path) is None


def test_G14_receipt_retains_labels_and_tool_inventory_without_acceptance(tmp_path):
    from ravel.controller.confine import policy
    store = MemoryStore(tmp_path / 'store')
    store.append('code-identity', {'label': 'NOT GOVERNED', 'governed': False})
    store.append('confinement-launch', {'kind': 'unconfined', 'backend': None})
    inventory = {'kind': 'worker', 'equal': False, 'tools': ['actual-read'], 'differences': []}
    store.append('tool-inventory', inventory)
    evidence = policy.receipt_evidence(store)
    assert evidence['labels'] == ['NOT GOVERNED', 'UNCONFINED EXECUTION']
    assert evidence['tool_inventory'] == [inventory]
    assert evidence['architecture_complete'] is False
    assert 'accepted' not in evidence


def test_G14_no_labels_does_not_manufacture_architecture_completion(tmp_path):
    from ravel.controller.confine import policy
    store = MemoryStore(tmp_path / 'store', nested=False)
    store.append('code-identity', {'label': None, 'governed': True})
    store.append('confinement-launch', {'confinement': {'kind': 'confined'}})
    assert policy.receipt_evidence(store) == {'labels': [], 'tool_inventory': []}
