"""Unrun N2-A ancestor-custody controls; no science or native qualification.

The actual typed index and Capture supply their original identity predicates.
The worker's engineering authority remains explicitly synthetic.
"""
from types import SimpleNamespace

import pytest

from ravel.physics.ma5_saf import Capture
from ravel.workflow import physics_review as review, review_context
from ravel.workflow.validation_io import identity
from test_readonly_preparation import owner_at, prepare, session, tiny_module
from test_readonly_preparation_successor_v3 import admitted_fixture


def replace_ancestor(ancestor):
    """Replace only the outer directory; preserve the nested tree and bytes."""
    old = ancestor.with_name(ancestor.name + '-old')
    ancestor.rename(old)
    ancestor.mkdir()
    (old / 'keep').rename(ancestor / 'keep')


@pytest.mark.parametrize('change', ['positive', 'ancestor-replaced', 'unrelated-entry'])
def test_actual_packet_parent_commitment_survives_later_owner_callback(tmp_path, monkeypatch, change):
    initial = tmp_path / 'initial'; initial.mkdir()
    root, _, _, _, _ = admitted_fixture(initial, monkeypatch)
    ancestor = tmp_path / 'A'; packet = ancestor / 'keep/packet'
    manifest = review_context.create(root, 'critic', packet)
    index = review_context._PacketIndex(packet, manifest['sha256'])
    for entry in index.entries.values():
        index.read(entry)
    original = {path: identity(path.lstat()) for path in index.observed}
    original.update({packet: identity(packet.lstat()), packet / 'artifacts': identity((packet / 'artifacts').lstat())})
    with owner_at(root, monkeypatch) as owner:
        review._readonly_context_sources(root, index, owner.session)
        assert owner.session.path_identities[(ancestor, 3)] == index.parents[ancestor]
        owner.session.retain_final_check(index.finish)
        prepare(owner, tiny_module(), root)
        def current():
            fresh = review_context._PacketIndex(packet, manifest['sha256'])
            for entry in fresh.entries.values(): fresh.read(entry)
            review._readonly_context_sources(root, fresh, owner.session)
            fresh.finish()
        owner.add_ending_check(current)
        def late():
            if change == 'ancestor-replaced': replace_ancestor(ancestor)
            elif change == 'unrelated-entry': (ancestor / 'unrelated.txt').write_bytes(b'unrelated delivery')
            # Exact nested payload/root identities survive the ancestor change.
            assert all(identity(path.lstat()) == before for path, before in original.items())
        owner.add_ending_check(late)
        if change == 'ancestor-replaced':
            with pytest.raises(ValueError, match='typed path identity changed'):
                owner.finish()
        else:
            assert owner.finish().result['values'] == [3, 7]
        assert not (root / 'adapter.json').exists()
    assert owner.closed and owner.session.closed and owner.session.path_identities == {}


@pytest.mark.parametrize('change', ['positive', 'ancestor-replaced', 'unrelated-entry'])
def test_actual_capture_ancestor_population_survives_later_owner_callback(tmp_path, monkeypatch, change):
    root = tmp_path / 'worker'
    ancestor = tmp_path / 'A'; native = ancestor / 'keep/native'; native.mkdir(parents=True)
    source = native / 'source.saf'; source.write_bytes(b'original supplied source')
    capture = Capture(); capture.read(source, native)
    capture.roots[native] = capture.census(native)
    packet = tmp_path / 'packet'; (packet / 'artifacts').mkdir(parents=True)
    (packet / 'manifest.json').write_bytes(b'explicit controlled Capture-only transport')
    index = SimpleNamespace(root=packet, source_capture=capture)
    original = identity(source.lstat())
    with owner_at(root, monkeypatch) as owner:
        review._readonly_context_sources(root, index, owner.session)
        expected = capture.paths[source][ancestor]
        assert owner.session.path_identities[(ancestor, 3)] == expected
        assert owner.session.path_identities[(source, 6)] == original
        owner.session.retain_final_check(capture.finish)
        prepare(owner, tiny_module(), root)
        def current():
            capture.finish()
            review._readonly_context_sources(root, index, owner.session)
        owner.add_ending_check(current)
        def late():
            if change == 'ancestor-replaced': replace_ancestor(ancestor)
            elif change == 'unrelated-entry': (ancestor / 'unrelated.txt').write_bytes(b'unrelated delivery')
            assert identity(source.lstat()) == original and source.read_bytes() == b'original supplied source'
        owner.add_ending_check(late)
        if change == 'ancestor-replaced':
            with pytest.raises(ValueError, match='typed path identity changed'):
                owner.finish()
        else:
            assert owner.finish().result['physics_validated'] is False
    assert owner.closed and owner.session.closed and owner.session.path_identities == {}


@pytest.mark.parametrize('change', ['stale-enrollment', 'conflicting-enrollment',
    'deleted-original', 'refreshed-original', 'late-fact-replaced', 'late-fact-positive'])
def test_explicit_identity_facts_keep_original_and_late_read_commitments(tmp_path, change):
    current = session(tmp_path / 'worker')
    directory = tmp_path / 'directory'; directory.mkdir()
    original = identity(directory.lstat())[:3]
    if change == 'stale-enrollment':
        directory.rename(tmp_path / 'old-directory'); directory.mkdir()
        with pytest.raises(ValueError, match='typed path identity changed'):
            current.retain_path_identity(directory, original)
        current.close()
        return
    current.retain_path_identity(directory, original)
    if change == 'conflicting-enrollment':
        with pytest.raises(ValueError, match='typed path identity changed'):
            current.retain_path_identity(directory, (original[0], original[1] + 1, original[2]))
        assert current.path_identities[(directory, 3)] == original
        current.close()
        return
    late = tmp_path / 'late-directory'; late.mkdir()
    def ending():
        if change == 'deleted-original': current.path_identities.clear()
        elif change == 'refreshed-original':
            directory.rename(tmp_path / 'old-directory'); directory.mkdir()
            current.path_identities[(directory, 3)] = identity(directory.lstat())[:3]
        else:
            current.retain_path_identity(late, identity(late.lstat())[:3])
            if change == 'late-fact-replaced':
                late.rename(tmp_path / 'old-late-directory'); late.mkdir()
    current.retain_final_check(ending)
    current.readonly_freeze(); current.readonly_drain()
    try:
        if change == 'late-fact-positive': current.readonly_terminal()
        else:
            with pytest.raises(ValueError, match='commitments changed|typed path identity changed'):
                current.readonly_terminal()
    finally:
        current.close()
    assert current.closed and current.path_identities == {}
