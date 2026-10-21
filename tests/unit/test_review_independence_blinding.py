"""Planted canaries distinguish packet access from semantic blinding claims."""
import json
from pathlib import Path

import pytest

from ravel.workflow import review_context as context, review_projection as projection
from ravel.workflow import review_independence as ri
from test_review_independence import query, evidence


def packet(tmp_path, monkeypatch):
    root = tmp_path / 'study'; (root / 'inputs').mkdir(parents=True)
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'machine-state'))
    (root / 'author-transcript.txt').write_text('TRANSCRIPT_CANARY')
    (root / 'instructions.txt').write_text('INSTRUCTION_CANARY')
    (root / 'inputs/headline.json').write_text('{"headline":"ANSWER_CANARY"}')
    (root / 'inputs/source.json').write_text(json.dumps({
        'value': 7, 'reference': 8, 'producer_verdict': 'AUTHOR_VERDICT_CANARY',
        'verdict': 'PEER_VERDICT_CANARY'}))
    (root / 'inputs/summary.md').write_text('PROSE_SUMMARY_CANARY')
    (root / 'inputs/held_out').mkdir()
    (root / 'inputs/held_out/PATH_CANARY.png').write_bytes(b'IMAGE_CANARY')
    (root / 'inputs/link.txt').symlink_to(root / 'author-transcript.txt')
    card = {'id': 'physics-critic', 'sees': {'profile': 'blind', 'forbidden_inputs':
        ['producer_headline', 'other_verdicts', 'held_out_artifacts']}, 'tools': {'read_paths': ['inputs/']}}
    binding = projection.project(root, card, key='fictional-review', out_root=tmp_path / 'packets')
    return root, binding


def test_excluded_canaries_do_not_enter_projected_artifact_reads(tmp_path, monkeypatch):
    root, binding = packet(tmp_path, monkeypatch)
    manifest = context.verify_packet(binding['path'], expected_manifest_sha256=binding['manifest_sha256'])
    presented = b''.join(context.read_artifact(binding['path'], entry['id'],
        expected_manifest_sha256=binding['manifest_sha256']) for entry in manifest['artifacts'])
    for marker in (b'TRANSCRIPT_CANARY', b'INSTRUCTION_CANARY', b'ANSWER_CANARY',
                   b'AUTHOR_VERDICT_CANARY', b'PEER_VERDICT_CANARY', b'PROSE_SUMMARY_CANARY', b'IMAGE_CANARY'):
        assert marker not in presented
    assert b'"reference": 8' in presented  # explicitly permitted reference content
    for reader in (context.read_artifact, context.read_artifact_page):
        for forbidden in ('../author-transcript.txt', str(root / 'instructions.txt'), 'inputs/link.txt',
                          'inputs/held_out/PATH_CANARY.png'):
            with pytest.raises(ValueError):
                reader(binding['path'], forbidden, expected_manifest_sha256=binding['manifest_sha256'])


def test_projection_metadata_and_unknown_prose_are_not_proof_of_semantic_blinding(tmp_path, monkeypatch):
    root, binding = packet(tmp_path, monkeypatch)
    # Existing structural projection preserves omission locators and unknown prose.
    # Record these limitations; never credit a shared workspace or an unqualified
    # whole prompt just because a known JSON verdict key was removed.
    manifest = json.loads((Path(binding['path']) / 'manifest.json').read_text())
    assert 'PATH_CANARY' in json.dumps(manifest)
    (root / 'inputs/ordinary.json').write_text('{"description":"ORDINARY_PROSE_CANARY"}')
    card = {'id': 'physics-critic', 'sees': {'profile': 'blind', 'forbidden_inputs': []},
            'tools': {'read_paths': ['inputs/ordinary.json']}}
    _, files = projection.build(root, card)
    assert b'ORDINARY_PROSE_CANARY' in b''.join(raw for _, raw in files)
    q = query(packet_sha256=binding['manifest_sha256'])
    proof = evidence(q, exposure_verified=False)
    with ri.authority_session(lambda _: proof):
        assert not ri.decide(q)['independent']


def test_symlink_replacement_cannot_escape_pinned_packet(tmp_path, monkeypatch):
    root, binding = packet(tmp_path, monkeypatch)
    manifest = json.loads((Path(binding['path']) / 'manifest.json').read_text())
    entry = manifest['artifacts'][0]
    target = Path(binding['path']) / entry['path']; target.unlink()
    target.symlink_to(root / 'author-transcript.txt')
    for reader in (context.read_artifact, context.read_artifact_page):
        with pytest.raises(ValueError, match='symlink'):
            reader(binding['path'], entry['id'], expected_manifest_sha256=binding['manifest_sha256'])


def test_read_paths_beyond_the_total_bound_are_indexed_omissions_and_subjects_stay_mandatory(tmp_path, monkeypatch):
    root = tmp_path / 'study'; (root / 'inputs').mkdir(parents=True)
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'machine-state'))
    (root / 'inputs/subject.json').write_text('{"value": 1}')
    for i in range(6):
        (root / f'inputs/bulk-{i}.json').write_text('{"rows": "' + 'x' * 900 + '"}')
    card = {'id': 'physics-critic', 'sees': {'profile': 'blind', 'forbidden_inputs': []},
            'tools': {'read_paths': ['inputs/']}}
    whole, _ = projection.build(root, card, subjects=['inputs/subject.json'])
    assert not [o for o in whole['omissions'] if o['class'] == 'size']
    used = sum(len(raw) for _, raw in projection.build(root, card, subjects=['inputs/subject.json'])[1])
    monkeypatch.setattr(projection, 'MAX_TOTAL_BYTES', used - 1500)
    bounded, files = projection.build(root, card, subjects=['inputs/subject.json'])
    sized = [o for o in bounded['omissions'] if o['class'] == 'size']
    assert sized and all('total bound' in o['reason'] and o['source_sha256'] for o in sized)
    assert [s['source_path'] for s in bounded['subjects']] == ['inputs/subject.json']
    assert sum(len(raw) for _, raw in files) <= projection.MAX_TOTAL_BYTES
    # A declared subject is never dropped: alone beyond the bound, the projection refuses.
    monkeypatch.setattr(projection, 'MAX_TOTAL_BYTES', 5)
    with pytest.raises(projection.ProjectionRefused, match='byte bound'):
        projection.build(root, card, subjects=['inputs/subject.json'])
