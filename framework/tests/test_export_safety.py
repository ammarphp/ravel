"""Destructive-path and provenance-rebinding regressions for distribution staging."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('export_safety', REPO / 'scripts/export_safety.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def test_prepare_never_deletes_a_populated_directory_or_source(tmp_path):
    repo = tmp_path / 'source'
    repo.mkdir()
    protected = tmp_path / 'protected'
    protected.mkdir()
    marker = protected / 'keep.txt'
    marker.write_text('keep this evidence')
    for forbidden in (protected, repo, repo / 'nested', tmp_path, Path.home(), Path('/')):
        with pytest.raises(ValueError):
            export.prepare(forbidden, repo)
    assert marker.read_text() == 'keep this evidence'
    fresh = tmp_path / 'new-stage'
    assert export.prepare(fresh, repo) == fresh


def test_prepare_rejects_symlink_leaf_and_parent(tmp_path):
    repo = tmp_path / 'source'
    repo.mkdir()
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(target, target_is_directory=True)
    for forbidden in (link, link / 'new-stage'):
        with pytest.raises(ValueError, match='symlink'):
            export.prepare(forbidden, repo)
    assert not (target / 'new-stage').exists()


@pytest.fixture
def evidence_trees(tmp_path):
    source, stage = tmp_path / 'source', tmp_path / 'stage'
    for root in (source, stage):
        (root / 'results').mkdir(parents=True)
        (root / 'framework').mkdir()
    home = '/home/researcher'
    data = b'{"value": 42, "path": "/home/researcher/Documents/DSRLab/run"}\n'
    manifest = {'schema_version': 1, 'source_commit': 'abc123', 'claims': [
        {'claim_id': 'example', 'status': 'served', 'artifacts': [
            {'path': 'results/example.json', 'shipped': True, 'dev_only': False,
             'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}]}]}
    for root in (source, stage):
        (root / 'results/example.json').write_bytes(data)
        (root / 'evidence_manifest.json').write_text(json.dumps(manifest) + '\n')
    # The binding helper renders an index; the test isolates integrity from its prose layout.
    (source / 'framework/build_evidence.py').write_text(
        'def render_evidence_md(manifest):\n    return "# Evidence\\n"\n')
    export.sanitize(stage, home)
    return source, stage, home


def test_exact_redaction_rebinds_hash_without_modifying_source(evidence_trees):
    source, stage, home = evidence_trees
    original = (source / 'evidence_manifest.json').read_bytes()
    changes = export.bind_evidence(stage, source, home)
    assert len(changes) == 1
    data = (stage / 'results/example.json').read_bytes()
    assert b'$DSRLAB_ROOT/run' in data and b'"value": 42' in data
    manifest = json.loads((stage / 'evidence_manifest.json').read_text())
    artifact = manifest['claims'][0]['artifacts'][0]
    assert artifact['sha256'] == hashlib.sha256(data).hexdigest()
    assert artifact['bytes'] == len(data)
    assert (source / 'evidence_manifest.json').read_bytes() == original
    assert json.loads((stage / 'results/export-provenance.json').read_text())['artifact_transformations'] == changes


@pytest.mark.parametrize('mutation', ['staged_data', 'source_data', 'manifest_claims'])
def test_tampering_cannot_be_blessed_by_rebinding(evidence_trees, mutation):
    source, stage, home = evidence_trees
    if mutation == 'manifest_claims':
        (stage / 'evidence_manifest.json').write_text('{"schema_version": 1, "claims": []}')
    else:
        root = source if mutation == 'source_data' else stage
        (root / 'results/example.json').write_text('{"value": 9000}')
    before = (stage / 'evidence_manifest.json').read_bytes()
    with pytest.raises(ValueError):
        export.bind_evidence(stage, source, home)
    assert (stage / 'evidence_manifest.json').read_bytes() == before
    assert not (stage / 'results/export-provenance.json').exists()


def test_artifact_escape_and_symlinks_are_rejected_before_reading(tmp_path):
    outside = tmp_path / 'outside.txt'
    outside.write_text('private')
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'link').symlink_to(outside)
    for relative in ('../outside.txt', str(outside), 'x/../outside.txt', 'link', 'x//y'):
        with pytest.raises(ValueError):
            export.evidence_path(root, relative)


def test_binding_cannot_repair_an_invalid_source_byte_pin(evidence_trees):
    source, stage, home = evidence_trees
    manifest = json.loads((source / 'evidence_manifest.json').read_text())
    manifest['claims'][0]['artifacts'][0]['bytes'] += 1
    encoded = json.dumps(manifest).encode()
    (source / 'evidence_manifest.json').write_bytes(encoded)
    (stage / 'evidence_manifest.json').write_bytes(export.sanitize_bytes(encoded, export.replacements_for(home)))
    with pytest.raises(ValueError, match='byte count'):
        export.bind_evidence(stage, source, home)


def test_sanitization_preserves_binary_bytes_and_rejects_malformed_repository_url():
    rules = export.replacements_for('/home/researcher', 'https://github.com/ammarphp/ravel.git')
    assert export.sanitize_bytes(b'binary\0/home/researcher', rules) == b'binary\0/home/researcher'
    assert export.sanitize_bytes(b'\xff/home/researcher', rules) == b'\xff/home/researcher'
    for url in ('https://example.org/a/b', 'https://github.com/a/b?token=secret',
                'https://github.com/a/b/extra', 'https://github.com/a/..'):
        with pytest.raises(ValueError):
            export.replacements_for('/home/researcher', url)
