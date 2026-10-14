"""The exported interpreter may be a virtual environment's launcher link; sources may not.

Synthetic inert files only: the interpreter fixture is never executed.
"""
import hashlib
from pathlib import Path

import pytest

from ravel.workflow import research_cycle, site_workflow as w
from test_site_workflow import workflow_fixture


def launcher_fixture(tmp_path, monkeypatch):
    """A regular interpreter file reached through bin/python, as a virtual environment names it."""
    request, rd, source = workflow_fixture(tmp_path, monkeypatch)
    target = Path(request['python']['path'])
    launcher = tmp_path / 'environment/bin/python'
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(target)
    request['python'] = {**request['python'], 'path': str(launcher)}
    return request, launcher, target


def test_linked_launcher_is_exported_by_name_and_read_at_its_target(tmp_path, monkeypatch):
    request, launcher, target = launcher_fixture(tmp_path, monkeypatch)
    result = w.export(request, tmp_path, tmp_path / 'export')
    document = w.verify(result['manifest']['path'], result['manifest']['sha256'])
    # The environment is selected by the launcher name, so the commands keep it.
    assert document['python'] == request['python']
    assert str(launcher) in (tmp_path / 'export/Snakefile').read_text()
    # The bytes that were hashed are those of the canonical interpreter file.
    assert {'path': str(target), 'sha256': request['python']['sha256'],
            'size': request['python']['size']} in document['audit_input_pins']


def test_retargeted_launcher_is_refused_at_verification(tmp_path, monkeypatch):
    request, launcher, _ = launcher_fixture(tmp_path, monkeypatch)
    result = w.export(request, tmp_path, tmp_path / 'export')
    other = tmp_path / 'other-python'
    other.write_bytes(b'another inert interpreter'); other.chmod(0o755)
    launcher.unlink(); launcher.symlink_to(other)
    with pytest.raises(ValueError, match='consumed source bytes differ'):
        w.verify(result['manifest']['path'], result['manifest']['sha256'])


def test_launcher_bytes_must_match_the_declared_pin(tmp_path, monkeypatch):
    request, _, _ = launcher_fixture(tmp_path, monkeypatch)
    request['python']['sha256'] = hashlib.sha256(b'not the interpreter').hexdigest()
    with pytest.raises(ValueError, match='consumed source bytes differ'):
        w.export(request, tmp_path, tmp_path / 'export')
    assert not (tmp_path / 'export').exists()


def test_launcher_target_must_be_executable(tmp_path, monkeypatch):
    request, _, target = launcher_fixture(tmp_path, monkeypatch)
    target.chmod(0o644)
    with pytest.raises(ValueError, match='explicit analysis interpreter required'):
        w.export(request, tmp_path, tmp_path / 'export')


def test_linked_audit_source_is_still_refused_and_names_the_link(tmp_path, monkeypatch):
    request, _, _ = launcher_fixture(tmp_path, monkeypatch)
    proof = Path(request['audit']['environment']['path'])
    alias = tmp_path / 'alias.json'
    alias.symlink_to(proof)
    request['audit']['environment'] = {**request['audit']['environment'], 'path': str(alias)}
    with pytest.raises(ValueError, match='ordinary research paths required') as refusal:
        w.export(request, tmp_path, tmp_path / 'export')
    assert str(alias) in str(refusal.value)
    assert not (tmp_path / 'export').exists()


def test_refusal_names_the_first_linked_ancestor(tmp_path):
    real = tmp_path / 'real'; real.mkdir()
    (real / 'source.json').write_text('{}')
    alias = tmp_path / 'alias'
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError) as refusal:
        research_cycle._ordinary(alias / 'source.json')
    assert str(refusal.value) == f'ordinary research paths required: {alias} is a symbolic link'
