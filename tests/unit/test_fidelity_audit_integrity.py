"""Published demonstrations must fail integrity checks after data or code drift."""
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_fidelity_audits


def test_current_fidelity_demonstrations_are_bound_to_inputs():
    assert check_fidelity_audits.check() == []


@pytest.mark.parametrize('mutation', ['scan_population', 'native_population', 'native_code_pin',
                                     'native_event_io.py', 'pool_replicas.py'])
def test_tampered_demonstration_is_rejected(tmp_path, mutation):
    source = ROOT / 'evidence/audits'
    selected = check_fidelity_audits.audit_paths(source)
    shutil.copy2(source / 'current.json', tmp_path / 'current.json')
    for path in selected.values():
        shutil.copytree(path, tmp_path / path.name)
    if mutation == 'scan_population':
        path = tmp_path / selected['scan'].name / 'scan__reldiff.json'
        data = json.loads(path.read_text())
        data['planned'] -= 2
    elif mutation == 'native_population':
        path = tmp_path / selected['native'].name / 'erjr_differential.json'
        data = json.loads(path.read_text())
        data['changed_events'].pop()
    elif mutation == 'native_code_pin':
        path = tmp_path / selected['native'].name / 'verification.json'
        data = json.loads(path.read_text())
        data['engine_sha256']['sa_native_core.py'] = '0' * 64
    else:
        path = tmp_path / selected['native'].name / 'verification.json'
        data = json.loads(path.read_text())
        data['additional_engine_sha256']['src/ravel/physics/' + mutation] = '0' * 64
    path.write_text(json.dumps(data))
    assert check_fidelity_audits.check(audits=tmp_path)


@pytest.fixture
def additional_sources(tmp_path):
    pins = {}
    for name in check_fidelity_audits.REQUIRED_ADDITIONAL_NATIVE_ENGINES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
        pins[name] = check_fidelity_audits.sha(path)
    assert check_fidelity_audits.additional_native_engine_errors(tmp_path, pins) == []
    return tmp_path, pins


@pytest.mark.parametrize('filename', ['native_event_io.py', 'pool_replicas.py'])
def test_additional_native_engine_changed_source_bytes_are_rejected(additional_sources, filename):
    root, pins = additional_sources
    name = 'src/ravel/physics/' + filename
    path = root / name
    path.write_bytes(path.read_bytes() + b'\n# independently changed source\n')
    assert check_fidelity_audits.additional_native_engine_errors(root, pins) == [
        f'native audit additional implementation changed: {name}']


@pytest.mark.parametrize('pins', [None, [], '', {}, True])
def test_additional_native_engine_map_is_required(tmp_path, pins):
    assert check_fidelity_audits.additional_native_engine_errors(tmp_path, pins)


@pytest.mark.parametrize('name', sorted(check_fidelity_audits.REQUIRED_ADDITIONAL_NATIVE_ENGINES))
def test_additional_native_engine_pin_cannot_be_dropped(additional_sources, name):
    root, pins = additional_sources
    del pins[name]
    assert any('pin missing: ' + name in error
               for error in check_fidelity_audits.additional_native_engine_errors(root, pins))


@pytest.mark.parametrize('value', [None, False, 12, '0' * 63, 'g' * 64, 'A' * 64])
def test_additional_native_engine_hash_must_be_sha256(additional_sources, value):
    root, pins = additional_sources
    pins['src/ravel/physics/native_event_io.py'] = value
    assert any('SHA-256 is malformed' in error
               for error in check_fidelity_audits.additional_native_engine_errors(root, pins))


@pytest.mark.parametrize('name', ['../outside.py', 'src/../../outside.py', '/absolute.py',
                                 'C:/outside.py', '..\\outside.py', './source.py',
                                 'src//source.py', '', '.', 'bad\0name.py', 3])
def test_additional_native_engine_paths_cannot_redirect_reads(additional_sources, monkeypatch, name):
    root, pins = additional_sources
    pins[name] = '0' * 64
    reads = []
    original = check_fidelity_audits.sha
    monkeypatch.setattr(check_fidelity_audits, 'sha', lambda path: (reads.append(path), original(path))[1])
    errors = check_fidelity_audits.additional_native_engine_errors(root, pins)
    assert any('path is not repository-relative' in error for error in errors)
    assert all(path.is_relative_to(root) for path in reads)
    assert len(reads) == 2


def test_additional_native_engine_symlink_cannot_escape_repository(additional_sources, tmp_path):
    root, pins = additional_sources
    outside = root.parent / (root.name + '-outside.py')
    outside.write_text('retained outside source\n')
    name = 'src/ravel/physics/native_event_io.py'
    (root / name).unlink()
    (root / name).symlink_to(outside)
    pins[name] = check_fidelity_audits.sha(outside)
    assert any('path escapes repository' in error
               for error in check_fidelity_audits.additional_native_engine_errors(root, pins))
    assert outside.read_text() == 'retained outside source\n'


def test_additional_native_engine_missing_file_is_not_ignored(additional_sources):
    root, pins = additional_sources
    (root / 'src/ravel/physics/pool_replicas.py').unlink()
    assert any('file unavailable' in error
               for error in check_fidelity_audits.additional_native_engine_errors(root, pins))


def test_duplicate_additional_engine_json_key_cannot_replace_a_binding(tmp_path):
    source = ROOT / 'evidence/audits'
    selected = check_fidelity_audits.audit_paths(source)
    shutil.copy2(source / 'current.json', tmp_path / 'current.json')
    native = tmp_path / selected['native'].name
    native.mkdir()
    (native / 'verification.json').write_text(
        '{"additional_engine_sha256":{"src/ravel/physics/native_event_io.py":"' + '0' * 64 +
        '","src/ravel/physics/native_event_io.py":"' + '1' * 64 + '"}}')
    with pytest.raises(ValueError, match='duplicate JSON key'):
        check_fidelity_audits.check(audits=tmp_path)


@pytest.mark.parametrize('name', ['../elsewhere', '2026-09-05-scan-fidelity', '/absolute/path'])
def test_registry_cannot_redirect_a_native_audit_to_another_kind_or_directory(tmp_path, name):
    registry = {'schema_version': 1, 'native': name, 'scan': '2026-09-05-scan-fidelity',
                'statistical': '2026-09-06-statistical-fidelity'}
    (tmp_path / 'current.json').write_text(json.dumps(registry))
    with pytest.raises(ValueError, match='invalid dated native'):
        check_fidelity_audits.audit_paths(tmp_path)
