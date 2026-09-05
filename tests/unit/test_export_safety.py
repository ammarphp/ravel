"""Destructive-path and provenance-rebinding regressions for distribution staging."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

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
    for name in ('evidence', 'scripts', 'docs/validation'):
        (source / name).mkdir(parents=True)
    stage.mkdir()
    (source / 'evidence/collections.json').write_bytes((REPO / 'evidence/collections.json').read_bytes())
    home = '/home/researcher'
    data = b'{"value": 42, "path": "/home/researcher/Documents/DSRLab/run"}\n'
    manifest = {'schema_version': 1, 'source_commit': 'abc123', 'claims': [
        {'claim_id': 'example', 'status': 'served', 'artifacts': [
            {'path': 'evidence/example.json', 'shipped': True, 'dev_only': False,
             'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}]}]}
    (source / 'evidence/example.json').write_bytes(data)
    (source / 'evidence/manifest.json').write_text(json.dumps(manifest) + '\n')
    # This isolates integrity from the prose renderer's own unit tests.
    (source / 'scripts/build_evidence.py').write_text(
        'def render_evidence_md(manifest):\n    return "# Evidence\\n"\n')
    (source / 'docs/validation/evidence.md').write_text('# Evidence\n')
    export.assemble(stage, source)
    export.sanitize(stage, home)
    return source, stage, home


def test_exact_redaction_rebinds_hash_without_modifying_source(evidence_trees):
    source, stage, home = evidence_trees
    original = (source / 'evidence/manifest.json').read_bytes()
    changes = export.bind_evidence(stage, source, home)
    assert len(changes) == 1
    data = (stage / 'evidence/example.json').read_bytes()
    assert b'$DSRLAB_ROOT/run' in data and b'"value": 42' in data
    manifest = json.loads((stage / 'evidence/manifest.json').read_text())
    artifact = manifest['claims'][0]['artifacts'][0]
    assert artifact['sha256'] == hashlib.sha256(data).hexdigest()
    assert artifact['bytes'] == len(data)
    assert (source / 'evidence/manifest.json').read_bytes() == original
    provenance = json.loads((stage / 'evidence/export-provenance.json').read_text())
    assert provenance['artifact_transformations'] == changes
    assert provenance['source_commit'] is None
    assert provenance['claim_manifest_source_commit'] == 'abc123'


def test_export_revision_is_actual_git_head_not_the_claim_manifest_revision(evidence_trees):
    source, stage, home = evidence_trees
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Export Test',
                    '-c', 'user.email=export-test@example.invalid',
                    'commit', '-q', '-m', 'Source snapshot'], check=True)
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    export.bind_evidence(stage, source, home)
    provenance = json.loads((stage / 'evidence/export-provenance.json').read_text())
    assert provenance['source_commit'] == head
    assert provenance['claim_manifest_source_commit'] == 'abc123'
    assert provenance['source_commit'] != provenance['claim_manifest_source_commit']
    binding = next(b for b in provenance['artifact_bindings'] if b['public_path'] == 'evidence/example.json')
    assert binding['source_sha256'] == hashlib.sha256((source / 'evidence/example.json').read_bytes()).hexdigest()
    assert binding['export_sha256'] == hashlib.sha256((stage / 'evidence/example.json').read_bytes()).hexdigest()


@pytest.mark.parametrize('mutation', ['staged_data', 'source_data', 'manifest_claims'])
def test_tampering_cannot_be_blessed_by_rebinding(evidence_trees, mutation):
    source, stage, home = evidence_trees
    if mutation == 'manifest_claims':
        (stage / 'evidence/manifest.json').write_text('{"schema_version": 1, "claims": []}')
    else:
        root = source if mutation == 'source_data' else stage
        (root / 'evidence/example.json').write_text('{"value": 9000}')
    before = (stage / 'evidence/manifest.json').read_bytes()
    with pytest.raises(ValueError):
        export.bind_evidence(stage, source, home)
    assert (stage / 'evidence/manifest.json').read_bytes() == before
    assert not (stage / 'evidence/export-provenance.json').exists()


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
    manifest = json.loads((source / 'evidence/manifest.json').read_text())
    manifest['claims'][0]['artifacts'][0]['bytes'] += 1
    encoded = json.dumps(manifest).encode()
    (source / 'evidence/manifest.json').write_bytes(encoded)
    (stage / 'evidence/manifest.json').write_bytes(export.sanitize_bytes(encoded, export.replacements_for(home)))
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


def test_curated_archive_relocation_keeps_source_bytes_and_binds_public_path(evidence_trees):
    source, stage, home = evidence_trees
    original = 'trial-runs/sleptonscan_fig3_SCAN/scan.json'
    public = 'evidence/scans/slepton-bino-figure-3/scan.json'
    data = b'{"historical_run_id":"sleptonscan_fig3_SCAN","value":42}\n'
    archive = source / original
    archive.parent.mkdir(parents=True)
    archive.write_bytes(data)
    manifest = json.loads((source / 'evidence/manifest.json').read_text())
    manifest['claims'][0]['artifacts'] = [
        {'path': public, 'source_path': original, 'shipped': True, 'dev_only': False,
         'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}]
    (source / 'evidence/manifest.json').write_text(json.dumps(manifest))
    shutil.rmtree(stage)
    stage.mkdir()
    export.assemble(stage, source)
    export.sanitize(stage, home)
    changes = export.bind_evidence(stage, source, home)
    assert archive.read_bytes() == data == (stage / public).read_bytes()
    assert not (stage / 'trial-runs').exists()
    assert changes[0]['source_path'] == original
    assert changes[0]['public_path'] == public
    assert changes[0]['source_sha256'] == changes[0]['export_sha256']
    # The same registry resolves the historical case path in an installed/public tree.
    assert export.evidence_layout.resolve(stage, original) == stage / public
    assert export.evidence_layout.resolve(source, public) == archive


@pytest.mark.parametrize('mutation', ['registry', 'unclaimed_file', 'extra_file'])
def test_public_layout_cannot_bless_registry_or_unclaimed_file_tampering(evidence_trees, mutation):
    source, stage, home = evidence_trees
    if mutation == 'registry':
        registry = json.loads((stage / 'evidence/collections.json').read_text())
        registry['collections'][0]['destination'] = 'evidence/scans/another-name'
        (stage / 'evidence/collections.json').write_text(json.dumps(registry))
    elif mutation == 'unclaimed_file':
        (stage / 'scripts/build_evidence.py').write_text('doctored exporter renderer')
    else:
        (stage / 'private-unlisted.txt').write_text('must not ship')
    before = (stage / 'evidence/manifest.json').read_bytes()
    with pytest.raises(ValueError):
        export.bind_evidence(stage, source, home)
    assert (stage / 'evidence/manifest.json').read_bytes() == before
    assert not (stage / 'evidence/export-provenance.json').exists()


@pytest.mark.parametrize('mutation', ['escape', 'collision', 'wrong_version', 'source_identity'])
def test_registry_rejects_ambiguous_or_unsafe_migrations(tmp_path, mutation):
    registry = json.loads((REPO / 'evidence/collections.json').read_text())
    if mutation == 'escape':
        registry['collections'][0]['destination'] = '../outside'
    elif mutation == 'collision':
        registry['collections'][1]['destination'] = registry['collections'][0]['destination']
    elif mutation == 'wrong_version':
        registry['schema_version'] = True
    else:
        registry['collections'][0]['source_run_id'] = 'another-original-run'
    (tmp_path / 'evidence').mkdir()
    (tmp_path / 'evidence/collections.json').write_text(json.dumps(registry))
    with pytest.raises(ValueError):
        export.evidence_layout.load_registry(tmp_path)


def test_public_copy_and_classifier_share_exact_evidence_selection(tmp_path):
    (tmp_path / 'evidence').mkdir()
    (tmp_path / 'evidence/collections.json').write_bytes((REPO / 'evidence/collections.json').read_bytes())
    included = 'trial-runs/CR005_refactor_smoke/output/EwkCompressed2018.txt'
    excluded = 'trial-runs/CR005_refactor_smoke/output/native_objects.txt'
    recursive = 'trial-runs/CR005_refactor_smoke/output/PROC_madgraph/event-dump.txt'
    private = 'trial-runs/private-control-archive/run_state.json'
    for relative in (included, excluded, recursive, private):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    selected = dict(export.evidence_layout.selected_files(tmp_path))
    assert included in selected and excluded not in selected and private not in selected
    assert recursive not in selected
    for relative in (included, excluded, recursive, private):
        assert export.evidence_layout.is_shipped(relative, tmp_path) == (relative in selected)


def test_required_user_facing_entrypoints_ship_and_are_in_the_public_index():
    selection = export.evidence_layout.selected_files(REPO)
    public = {destination for _source, destination in selection}
    required = {'README.md', 'CONTRIBUTING.md', 'AGENTS.md', 'CLAUDE.md', 'DIRECTORY.md',
                'CITATION.cff', 'LICENSE', 'NOTICE', 'CHANGELOG.md',
                'native/README.md', 'environment/README.md', 'benchmarks/README.md'}
    assert required <= public
    index = export.public_directory(selection)
    assert all(f'`{name}`' in index for name in required)
