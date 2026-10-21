"""Frozen source restrictions and the operator's single export ceiling."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

from ravel.controller import authority
from ravel.controller.confine import policy
from ravel.controller.store import RunStore
from ravel.workflow import procedure_export, submission_export
from test_p06_support import operator_home  # noqa: F401

SCANNER = Path(__file__).resolve().parents[3] / 'scripts/maintenance/restricted_source_scan.py'


def owned_run(tmp_path, *, configured=True, pinned=True):
    source = tmp_path / 'restrictions.json'
    source.write_text(json.dumps({'schema_version': 1, 'kind': 'restricted-sources',
                                 'documents': [], 'fingerprints': ['fictional-private-phrase']}))
    authority.operator.init(mode='autonomous', restricted_sources=str(source) if configured else None,
                            procedure_byte_ceiling=16)
    store = RunStore.create(tmp_path / 'runs' / 'owned-export')
    mode = authority.freeze_mode(store, {'prompt': 'Export a fictional recorded result.'})
    assert mode['restricted_sources'] == (str(source) if configured else None)
    if pinned:
        policy.freeze_sources(store, source, run_dir=store.run_dir)
    return store, source


def scanner_source(monkeypatch):
    calls = []
    def git(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, SCANNER.read_bytes(), b'')
    monkeypatch.setattr(submission_export, '_git', git)
    return calls


def test_frozen_policy_allows_only_the_pinned_sources(tmp_path, monkeypatch, operator_home):
    store, source = owned_run(tmp_path)
    calls = scanner_source(monkeypatch)
    vendor = tmp_path / 'vendor'
    vendor.mkdir()
    item = vendor / 'widget.py'
    item.write_text('clean fictional module\n')
    override = tmp_path / 'override.json'
    override.write_text(json.dumps({'schema_version': 1, 'kind': 'restricted-sources',
                                   'documents': [], 'fingerprints': ['different-fictional-phrase']}))
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(override))
    authority.operator.set_values({'restricted_sources': str(override)})
    assert submission_export._restricted_source_scan(tmp_path, 'v0.0.0', vendor, controller_run=store.run_id) == {
        'deny_list': 'pinned', 'findings': 0}
    assert len(calls) == 1
    item.write_text('fictional-private-phrase\n')
    with pytest.raises(ValueError, match='restricted-source finding'):
        submission_export._restricted_source_scan(tmp_path, 'v0.0.0', vendor, controller_run=store.run_id)
    calls.clear()
    source.write_text(override.read_text())
    with pytest.raises(ValueError, match='changed|differ'):
        submission_export._restricted_source_scan(tmp_path, 'v0.0.0', vendor, controller_run=store.run_id)
    assert calls == []  # policy failure precedes fetching or executing scanner code


def test_missing_policy_bytes_refuse_before_scanner_load(tmp_path, monkeypatch, operator_home):
    store, source = owned_run(tmp_path)
    source.unlink()
    calls = scanner_source(monkeypatch)
    with pytest.raises(ValueError, match='missing|unreadable'):
        submission_export._restricted_source_scan(tmp_path, 'v0.0.0', tmp_path, controller_run=store.run_id)
    assert calls == []


def test_scanner_uses_the_validated_policy_snapshot(tmp_path, monkeypatch, operator_home):
    store, source = owned_run(tmp_path)
    vendor = tmp_path / 'vendor'
    vendor.mkdir()
    (vendor / 'widget.py').write_text('fictional-private-phrase\n')
    def replace_after_validation(*args, **kwargs):
        source.write_text(json.dumps({'schema_version': 1, 'kind': 'restricted-sources',
                                      'documents': [], 'fingerprints': ['different-fictional-phrase']}))
        return subprocess.CompletedProcess(args, 0, SCANNER.read_bytes(), b'')
    monkeypatch.setattr(submission_export, '_git', replace_after_validation)
    with pytest.raises(ValueError, match='restricted-source finding'):
        submission_export._restricted_source_scan(tmp_path, 'v0.0.0', vendor, controller_run=store.run_id)


@pytest.mark.parametrize('configured,pinned', [(False, False), (True, False)])
def test_missing_frozen_policy_refuses_before_loading_scanner(tmp_path, monkeypatch, operator_home,
                                                             configured, pinned):
    store, _ = owned_run(tmp_path, configured=configured, pinned=pinned)
    calls = scanner_source(monkeypatch)
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(tmp_path / 'permissive.json'))
    with pytest.raises(ValueError, match='policy|pinned'):
        submission_export._restricted_source_scan(tmp_path, 'v0.0.0', tmp_path, controller_run=store.run_id)
    assert calls == []


def test_raised_environment_ceiling_cannot_expand_controller_export(tmp_path, monkeypatch, operator_home):
    store, _ = owned_run(tmp_path)
    monkeypatch.setenv('RAVEL_PROCEDURE_BYTE_CEILING', '1000000000')
    assert procedure_export._byte_ceiling(store.run_dir) == 16
    small, large = store.run_dir / 'small.txt', store.run_dir / 'large.txt'
    small.write_bytes(b'within cap')
    large.write_bytes(b'x' * 17)
    pins, missing = procedure_export._files(store.run_dir, [small, large], {},
                                            procedure_export._byte_ceiling(store.run_dir))
    assert missing == []
    assert pins[0]['sha256'] == hashlib.sha256(small.read_bytes()).hexdigest()
    assert not pins[0].get('reference_only')
    assert pins[1]['reference_only'] is True and pins[1]['sha256'] is None
    assert procedure_export._byte_ceiling(tmp_path) == 1000000000


def release_tree(monkeypatch):
    raw = b'print("fictional output")\n'
    name = 'src/widget.py'
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    record = {'source': 'vendor', 'tag': 'v0.0.0', 'commit': 'a' * 40,
              'url': 'https://example.invalid/release', 'distribution': 'fictional-package', 'version': '0.0.0'}
    tree = {name: {'blob_id': blob, 'mode': '100644', 'kind': 'blob'}}
    monkeypatch.setattr(submission_export, '_framework_release', lambda mode, checkout: (
        checkout, {**record, 'source': mode}, [name], tree))
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as stream:
        info = tarfile.TarInfo(name)
        info.size = len(raw)
        stream.addfile(info, io.BytesIO(raw))
    calls = []
    def git(command, *args, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(args, 0,
            archive.getvalue() if command == 'archive' else SCANNER.read_bytes(), b'')
    monkeypatch.setattr(submission_export, '_git', git)
    return calls


def test_vendor_and_release_reference_modes(tmp_path, monkeypatch, operator_home):
    store, _ = owned_run(tmp_path)
    calls = release_tree(monkeypatch)
    vendor = tmp_path / 'vendored'
    vendor.mkdir()
    package = submission_export._Package(vendor, tmp_path)
    submission_export._write_framework(package, 'vendor', tmp_path, controller_run=store.run_id)
    manifest = json.loads((vendor / 'vendor/ravel/VENDOR-MANIFEST.json').read_text())
    assert manifest['restricted_source_scan'] == {'deny_list': 'pinned', 'findings': 0}
    assert calls == ['archive', 'show']
    referenced = tmp_path / 'referenced'
    referenced.mkdir()
    calls.clear()
    submission_export._write_framework(submission_export._Package(referenced, tmp_path),
                                        'release:v0.0.0', tmp_path, controller_run=store.run_id)
    assert calls == [] and not (referenced / 'vendor').exists()
    assert 'fictional-package @ git+' in (referenced / 'environment/ravel-requirements.txt').read_text()


def test_legacy_scanner_keeps_environment_policy(tmp_path, monkeypatch):
    scanner_source(monkeypatch)
    source = tmp_path / 'legacy.json'
    source.write_text(json.dumps({'schema_version': 1, 'kind': 'restricted-sources',
                                 'documents': [], 'fingerprints': ['fictional-private-phrase']}))
    vendor = tmp_path / 'vendor'
    vendor.mkdir()
    (vendor / 'widget.py').write_text('clean module\n')
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(source))
    assert submission_export._restricted_source_scan(tmp_path, 'v0.0.0', vendor) == {
        'deny_list': 'supplied', 'findings': 0}
