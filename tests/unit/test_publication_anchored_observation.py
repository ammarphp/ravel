"""Root-only prospective controls; author has not imported or run this module.

Uses the existing authentic inert author Graph and ordinary build preparation.
No TeX/native/provider call is allowed by that original fixture.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import threading

import pytest

from ravel.physics import manuscript_build as mb
from ravel.workflow import manuscript_production as mp, publication_runtime as pr
from ravel.workflow import publication_observation as observed, science
from test_publication_unqualified_validation import prepared, session, runtime_proofs


def ready(tmp_path, monkeypatch):
    f = prepared(tmp_path, monkeypatch)
    s = session(f)
    mb._validation_inputs(f['task'], f['base'], s)
    proof = runtime_proofs(s)[0]
    return f, s, proof


def test_real_verify_v2_full_equal_plan_and_four_fresh_authors(tmp_path, monkeypatch):
    f = prepared(tmp_path, monkeypatch)
    expected = mb.inputs(f['task'], f['base'])
    authors = []
    original = mp.verify_author
    def fresh(*args, **kwargs):
        authors.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(mp, 'verify_author', fresh)
    s = session(f)
    proposal = science._verify_v2(f['rd'], _session=s)
    assert len(authors) == 4
    assert proposal == json.loads((f['rd'] / science.PLAN).read_text())
    assert len(runtime_proofs(s)) == 1
    assert mb._validation_inputs(f['task'], proposal['base_dir'], s) == expected
    assert mb._validation_execution_seconds(f['task'], proposal['base_dir'], s) == 30
    assert len(authors) == 6
    assert s.finish() == [] and s.closed and not s.proofs
    assert not (f['rd'] / science.APPROVAL).exists()
    assert not (f['rd'] / 'execution_attempt.json').exists()


def test_genuine_scope_complete_inventory_equal_and_all_fds_closed(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    root = Path(f['runtime']['snapshot_root'])
    limits = deepcopy(proof.context['config']['custody_limits'])
    expected = pr._inventory(root, limits=limits)
    owner = observed.observation(proof)
    assert type(owner) is observed._PublicationPaths
    with owner:
        actual = pr._inventory(root, limits=limits, _path_observation=owner)
        assert actual == expected
        descriptors = tuple(owner.core.acquired)
        assert descriptors and owner.core.records
    assert owner.closed and not owner.core.acquired and not owner.core.records
    assert s.path_identities
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert s.finish() == []


@pytest.mark.parametrize('change', ['leaf-alias', 'ancestor-alias', 'inode', 'mode', 'bytes'])
def test_actual_immediate_named_path_mutations_refuse_and_close(tmp_path, monkeypatch, change):
    f, s, proof = ready(tmp_path, monkeypatch)
    leaf = Path(f['runtime']['snapshot_root']) / 'selected/assets/synthetic.tfm'
    owner = observed.observation(proof)
    with pytest.raises((ValueError, OSError)):
        with owner:
            before = pr._identity(leaf, _path_observation=owner)
            descriptors = tuple(owner.core.acquired)
            if change == 'leaf-alias':
                leaf.unlink(); leaf.symlink_to(leaf.parent / 'article.cls')
            elif change == 'ancestor-alias':
                old = leaf.parent; moved = old.with_name('moved-assets')
                old.rename(moved); old.symlink_to(moved, target_is_directory=True)
            elif change == 'inode':
                replacement = leaf.with_name('replacement')
                replacement.write_bytes(leaf.read_bytes()); replacement.replace(leaf)
            elif change == 'mode':
                leaf.chmod(0o600)
            else:
                leaf.write_bytes(b'changed original bytes')
            after = pr._identity(leaf, _path_observation=owner)
            assert after == before
    assert owner.closed
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    s.close()


def test_method_tail_catches_change_after_last_content_read(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    leaf = Path(f['runtime']['snapshot_root']) / 'selected/assets/synthetic.tfm'
    owner = observed.observation(proof)
    with pytest.raises(ValueError):
        with owner:
            pr._identity(leaf, _path_observation=owner)
            leaf.write_bytes(b'late before pure-method return')
    assert owner.closed and not owner.core.acquired
    s.close()


def test_original_session_final_callback_population_guard_remains(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    leaf = Path(f['runtime']['snapshot_root']) / 'selected/assets/synthetic.tfm'
    s.retain_final_check(lambda: (leaf.parent / 'late-empty-directory').mkdir())
    errors = s.finish()
    assert errors and s.closed and not s.proofs
    assert any('inventory' in value or 'population' in value for value in errors)


def test_error_body_and_late_helper_injection_close_captured_descriptors(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    leaf = Path(f['runtime']['snapshot_root']) / 'selected/assets/synthetic.tfm'
    owner = observed.observation(proof)
    with pytest.raises(ValueError, match='deliberate'):
        with owner:
            pr._identity(leaf, _path_observation=owner)
            descriptors = tuple(owner.core.acquired)
            monkeypatch.setattr(observed._PublicationPaths, 'close', lambda self: [])
            raise ValueError('deliberate body failure')
    assert owner.closed and not owner.core.acquired
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    s.close()


def test_directories_have_separate_actual_type_guard(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    root = Path(f['runtime']['snapshot_root'])
    owner = observed.observation(proof)
    with owner:
        assert pr._regular(root, directory=True, _path_observation=owner) == root
        with pytest.raises(ValueError, match='regular publication'):
            pr._regular(root, _path_observation=owner)
    assert owner.closed
    assert s.finish() == []


def test_noncanonical_spelling_retains_original_fallback(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    root = Path(f['runtime']['snapshot_root'])
    spelling = str(root / 'selected/assets') + '/../assets/synthetic.tfm'
    expected = pr._identity(spelling)
    owner = observed.observation(proof)
    with owner:
        assert pr._identity(spelling, _path_observation=owner) == expected
        assert owner.core.records == {}
    assert s.finish() == []


def test_caps_keep_full_default_reader_population(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    root = Path(f['runtime']['snapshot_root'])
    expected = pr._inventory(root, limits=proof.context['config']['custody_limits'])
    owner = observed.observation(proof)
    with owner:
        # This is the core's declared cache bound, not the input resource law.
        owner.core.MAX_DIRECTORY_FDS = 0
        actual = pr._inventory(root, limits=proof.context['config']['custody_limits'], _path_observation=owner)
        assert actual == expected and not owner.core.records
    assert s.finish() == []


def test_cross_thread_reuse_refuses_without_reading(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    owner = observed.observation(proof)
    failures = []
    with owner:
        def other():
            try:
                owner.check()
            except ValueError as error:
                failures.append(str(error))
        thread = threading.Thread(target=other)
        thread.start(); thread.join(timeout=5)
        assert not thread.is_alive() and failures
    assert s.finish() == []


def test_foreign_owner_and_closed_session_cannot_select(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='exact private'):
        pr._regular(Path(f['runtime']['snapshot_root']), directory=True, _path_observation=object())
    s.close()
    assert observed.observation(proof) is None


def test_new_scope_never_borrows_previous_descriptors(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    leaf = Path(f['runtime']['snapshot_root']) / 'selected/assets/synthetic.tfm'
    first = observed.observation(proof)
    with first:
        pr._identity(leaf, _path_observation=first)
    second = observed.observation(proof)
    assert second is not first and first.closed
    with second:
        assert not second.core.records
        pr._identity(leaf, _path_observation=second)
    assert second.closed and s.finish() == []


def test_source_callable_injection_uses_complete_default_path(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    original = observed._CORE._chain
    def replacement(*args, **kwargs):
        return original(*args, **kwargs)
    monkeypatch.setattr(observed._CORE, '_chain', replacement)
    assert observed.observation(proof) is None
    assert mb._validation_inputs(f['task'], f['base'], s)
    assert s.finish() == []


def test_tuple_reader_replacement_cannot_self_report_ownership(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    leaf = Path(f['runtime']['snapshot_root']) / 'selected/assets/synthetic.tfm'
    owner = observed.observation(proof)
    reader = proof.owners
    with pytest.raises(ValueError, match='live same-process'):
        with owner:
            pr._identity(leaf, _path_observation=owner)
            descriptors = tuple(owner.core.acquired)
            monkeypatch.setattr(proof, 'owners', lambda: reader())
            owner.check()
    assert owner.closed and not owner.core.acquired
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert observed.observation(proof) is None
    s.close()


def test_inert_core_cleanup_replacement_cannot_leak_acquired_descriptors(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    leaf = Path(f['runtime']['snapshot_root']) / 'selected/assets/synthetic.tfm'
    owner = observed.observation(proof)
    with pytest.raises(ValueError, match='live same-process'):
        with owner:
            pr._identity(leaf, _path_observation=owner)
            descriptors = tuple(owner.core.acquired)
            monkeypatch.setattr(observed._CORE, 'close_all', lambda self, closer: [])
            owner.check()
    assert owner.closed and not owner.core.acquired and not owner.core.records
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    s.close()


def test_inert_terminal_replacement_cannot_skip_original_fact_tail(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    leaf = Path(f['runtime']['snapshot_root']) / 'selected/assets/synthetic.tfm'
    owner = observed.observation(proof)
    with pytest.raises(ValueError, match='live same-process'):
        with owner:
            pr._identity(leaf, _path_observation=owner)
            descriptors = tuple(owner.core.acquired)
            monkeypatch.setattr(observed._PublicationPaths, 'terminal', lambda self: None)
    assert owner.closed and not owner.core.acquired
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    s.close()


def test_selected_directory_identity_is_committed_across_pure_methods(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    root = Path(f['runtime']['snapshot_root'])
    leaf = root / 'selected/assets/synthetic.tfm'
    first = observed.observation(proof)
    with first:
        pr._identity(leaf, _path_observation=first)
    # Keep the exact original leaf inode/bytes while replacing its directory.
    # The source-owned Session has enrolled original ancestor identity3 facts;
    # this deliberate stricter lifetime contract refuses the new directory.
    parent = leaf.parent
    parked = parent.with_name('parked-assets')
    parent.rename(parked)
    parent.mkdir()
    for member in tuple(parked.iterdir()):
        member.rename(parent / member.name)
    second = observed.observation(proof)
    with pytest.raises(ValueError, match='typed path identity'):
        with second:
            pr._identity(leaf, _path_observation=second)
    assert second.closed and not second.core.acquired
    s.close()


def test_actual_resource_refusal_keeps_full_population_and_closes(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    root = Path(f['runtime']['snapshot_root'])
    limits = deepcopy(proof.context['config']['custody_limits'])
    limits['max_files'] = 1
    owner = observed.observation(proof)
    with pytest.raises(ValueError, match='file budget'):
        with owner:
            pr._inventory(root, limits=limits, _path_observation=owner)
    assert owner.closed and not owner.core.acquired and not owner.core.records
    s.close()


import hashlib
from ravel.workflow.validation_io import identity

def test_original_session_rechecks_enrolled_ancestor_after_later_callback(tmp_path, monkeypatch):
    outer = tmp_path / 'owned-outer'
    inner = outer / 'retained-inner'
    f = prepared(inner, monkeypatch)
    s = session(f)
    proposal = science._verify_v2(f['rd'], _session=s)
    assert proposal == __import__('json').loads((f['rd'] / science.PLAN).read_text())
    assert len(runtime_proofs(s)) == 1
    proof = runtime_proofs(s)[0]
    assert proof.finish in s.final_checks
    original_ancestor = s.path_identities[(outer, 3)]
    assert original_ancestor == identity(outer.lstat())[:3]
    # Only the enrolled, uninventoried ancestor changes; all actual query roots
    # and files remain the same. Do not substitute a changed runtime population.
    assert all(Path(value) not in (outer, inner) for value, _ in s.queries)
    original_queries = dict(s.queries)
    original_files = dict(s.files)
    original_bytes = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in s.files}
    called = []

    def after_publication_proof():
        assert s.final_checks.index(proof.finish) < s.final_checks.index(after_publication_proof)
        parked = tmp_path / 'parked-original-outer'
        outer.rename(parked)
        outer.mkdir()
        (parked / inner.name).rename(inner)
        assert identity(outer.lstat())[:3] != original_ancestor
        assert s.path_identities[(outer, 3)] == original_ancestor
        for (value, outputs), previous in original_queries.items():
            path, census, _ = s.census(value, outputs)
            assert (str(path), census) == previous
        for path, previous in original_files.items():
            assert s.observe(path) == previous
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == original_bytes[path]
        called.append(True)

    s.retain_final_check(after_publication_proof)
    errors = s.finish()
    assert called == [True]
    assert s.closed and not s.proofs
    # The intended stricter ancestor commitment must survive every later
    # callback, just as retained byte/population commitments already do.
    assert errors, 'an enrolled ancestor changed after the publication proof tail'
    assert not (f['rd'] / science.APPROVAL).exists()
    assert not (f['rd'] / 'execution_attempt.json').exists()



def test_actual_verify_v2_postcallback_typed_tail_accepts_unchanged(tmp_path, monkeypatch):
    f = prepared(tmp_path, monkeypatch)
    s = session(f)
    proposal = science._verify_v2(f['rd'], _session=s)
    assert proposal == json.loads((f['rd'] / science.PLAN).read_text())
    proof = runtime_proofs(s)[0]
    original = dict(s.path_identities)
    called = []
    def later():
        assert s.final_checks.index(proof.finish) < s.final_checks.index(later)
        assert all(s.path_identities.get(key) == value for key, value in original.items())
        called.append(True)
    s.retain_final_check(later)
    assert s.finish() == []
    assert called == [True] and s.closed and not s.proofs
    assert not (f['rd'] / science.APPROVAL).exists()
    assert not (f['rd'] / 'execution_attempt.json').exists()


@pytest.mark.parametrize('mutation', ['erase', 'rewrite'])
def test_callback_cannot_erase_or_rebase_original_typed_commitment(tmp_path, monkeypatch, mutation):
    outer = tmp_path / 'owned-outer'
    inner = outer / 'retained-inner'
    f = prepared(inner, monkeypatch)
    s = session(f)
    science._verify_v2(f['rd'], _session=s)
    proof = runtime_proofs(s)[0]
    expected = s.path_identities[(outer, 3)]
    called = []
    def later():
        assert s.final_checks.index(proof.finish) < s.final_checks.index(later)
        parked = tmp_path / 'parked-original-outer'
        outer.rename(parked); outer.mkdir(); (parked / inner.name).rename(inner)
        assert identity(outer.lstat())[:3] != expected
        if mutation == 'erase':
            s.path_identities.clear()
        else:
            s.path_identities[(outer, 3)] = identity(outer.lstat())[:3]
        called.append(True)
    s.retain_final_check(later)
    errors = s.finish()
    assert called == [True] and errors
    assert any('original typed path commitment' in value for value in errors)
    assert s.closed and not s.proofs
    assert not (f['rd'] / science.APPROVAL).exists()
    assert not (f['rd'] / 'execution_attempt.json').exists()


def test_new_fact_enrolled_by_callback_is_checked_at_real_finish_tail(tmp_path, monkeypatch):
    f, s, proof = ready(tmp_path, monkeypatch)
    leaf = tmp_path / 'late-fact'
    leaf.write_bytes(b'original late fact')
    called = []
    def later():
        assert s.final_checks.index(proof.finish) < s.final_checks.index(later)
        s.retain_path_identity(leaf, identity(leaf.lstat()))
        leaf.write_bytes(b'changed after late enrolment')
        called.append(True)
    s.retain_final_check(later)
    errors = s.finish()
    assert called == [True] and errors
    assert any('typed path identity changed after final callbacks' in value for value in errors)
    assert s.closed and not s.proofs
    assert not (f['rd'] / science.APPROVAL).exists()
    assert not (f['rd'] / 'execution_attempt.json').exists()
