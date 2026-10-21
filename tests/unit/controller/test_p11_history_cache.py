"""Verified replay reuse still authenticates every immutable record's bytes."""
from collections import OrderedDict
from copy import deepcopy
import os
from pathlib import Path
import shutil

import pytest

from ravel.workflow import research_cycle as cycle, research_history as history, state_io
from test_p11_history import genesis  # noqa: F401


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    monkeypatch.setattr(history, '_VERIFIED', OrderedDict())


@pytest.fixture
def chain(genesis):
    root, initial = genesis
    states = [deepcopy(initial)]
    for index in range(1, 4):
        states.append(cycle._commit(root, states[-1], 'cache_observation', index=index))
    with history._LOCK:
        history._VERIFIED.clear()
    return root, states


@pytest.fixture
def replay_calls(monkeypatch):
    calls = []
    actual = history._states

    def observe(root, head, **kwargs):
        calls.append((Path(root), deepcopy(head)))
        yield from actual(root, head, **kwargs)

    monkeypatch.setattr(history, '_states', observe)
    return calls


def head(root, revision=3):
    return state_io.read_json(root / 'history' / f'{revision:04d}.json')


def reseal_delta_with_bad_state(root, revision):
    path = root / 'history' / f'{revision:04d}.json'
    row = state_io.read_json(path)
    row['changes'].append({'op': 'set', 'path': ['unchanged_payload'], 'value': 'Forged retained context.'})
    row.pop('sha256')
    state_io.atomic_json(path, cycle._seal(row))
    if revision == 3:
        state_io.atomic_json(root / 'head.json', cycle._pin(path))


def test_warm_current_reuses_replay_only_after_reading_every_record_byte(chain, replay_calls, monkeypatch):
    root, states = chain
    assert history.replay(root, head(root)) == states[-1]
    assert len(replay_calls) == 1
    reads = []
    actual = Path.read_bytes

    def record_read(path):
        if path.parent == root / 'history':
            reads.append(path)
        return actual(path)

    monkeypatch.setattr(Path, 'read_bytes', record_read)
    assert cycle._load_history(root) == (root, states[-1])
    assert len(replay_calls) == 1
    expected = {root / 'history' / f'{revision:04d}.json' for revision in range(4)}
    assert expected <= set(reads)
    assert all(reads.count(path) >= 1 for path in expected)


def test_same_size_corruption_with_restored_timestamps_refuses_warm_and_historical_reads(chain, replay_calls):
    root, states = chain
    assert cycle._load_history(root)[1] == states[-1]
    path = root / 'history' / '0000.json'
    metadata, original = path.stat(), path.read_bytes()
    changed = original.replace(b'retained scientific context', b'RETAINED scientific context', 1)
    assert changed != original and len(changed) == len(original)
    path.write_bytes(changed)
    os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    assert path.stat().st_size == metadata.st_size
    assert path.stat().st_mtime_ns == metadata.st_mtime_ns
    for read in (lambda: cycle._load_history(root), lambda: cycle.historical_state(root, 0)):
        with pytest.raises(ValueError):
            read()
    assert len(replay_calls) == 3


def test_self_resealed_older_record_cannot_reuse_verified_metadata(chain, replay_calls):
    root, states = chain
    assert cycle._load_history(root)[1] == states[-1]
    path = root / 'history' / '0000.json'
    metadata = path.stat()
    row = state_io.read_json(path)
    row['unchanged_payload'] = row['unchanged_payload'].replace('retained', 'RETAINED', 1)
    row.pop('sha256')
    state_io.atomic_json(path, cycle._seal(row))
    os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    assert path.stat().st_size == metadata.st_size
    assert path.stat().st_mtime_ns == metadata.st_mtime_ns
    with pytest.raises(ValueError, match='ancestry'):
        cycle._load_history(root)
    assert len(replay_calls) == 2


def test_valid_commit_changes_head_and_requires_fresh_full_replay(chain, replay_calls):
    root, states = chain
    prior = cycle._load_history(root)[1]
    assert prior == states[-1] and len(replay_calls) == 1
    old_head = head(root)
    newer = cycle._commit(root, prior, 'new_cache_observation', index=4)
    assert len(replay_calls) == 1  # The commit may reuse only its unchanged predecessor.
    assert history.ce.digest(head(root, 4)) != history.ce.digest(old_head)
    assert cycle._load_history(root)[1] == newer
    assert len(replay_calls) == 2
    assert cycle._load_history(root)[1] == newer
    assert len(replay_calls) == 2
    assert newer != prior and newer['revision'] == prior['revision'] + 1


def test_mutating_cold_and_warm_return_values_cannot_change_the_cached_state(chain, replay_calls):
    root, states = chain
    cold = cycle._load_history(root)[1]
    cold['contract']['budget']['calls'] = 0
    cold['events'][-1]['kind'] = 'caller_forgery'
    assert cycle._load_history(root)[1] == states[-1]
    warm = cycle._load_history(root)[1]
    warm['events'].clear()
    warm['unchanged_payload'] = 'caller replacement'
    assert cycle._load_history(root)[1] == states[-1]
    assert len(replay_calls) == 1


def test_historical_reads_always_replay_all_records_and_refuse_a_tampered_tail(chain, replay_calls):
    root, states = chain
    assert cycle._load_history(root)[1] == states[-1]
    assert cycle.historical_state(root, 0) == states[0]
    assert cycle.historical_state(root, 1) == states[1]
    assert len(replay_calls) == 3
    reseal_delta_with_bad_state(root, 3)
    with pytest.raises(ValueError, match='reconstructed research history content differs'):
        cycle.historical_state(root, 0)
    assert len(replay_calls) == 4


def test_unknown_valid_head_is_fully_replayed_instead_of_reusing_another_head(chain, replay_calls):
    root, states = chain
    assert history.replay(root, head(root)) == states[3]
    assert history.replay(root, head(root, 1)) == states[1]
    assert len(replay_calls) == 2
    assert cycle._load_history(root)[1] == states[3]
    assert len(replay_calls) == 3


@pytest.mark.parametrize('field', ['sha256', 'result_sha256', 'unrecorded_field'])
def test_forged_head_cannot_reuse_cache_even_when_every_record_byte_is_unchanged(chain, replay_calls, field):
    root, states = chain
    original = head(root)
    assert history.replay(root, original) == states[-1]
    forged = {**original, field: '0' * 64}
    with pytest.raises(ValueError, match='head differs'):
        history.replay(root, forged)
    assert len(replay_calls) == 2
    assert cycle._load_history(root)[1] == states[-1]
    assert len(replay_calls) == 2


def test_cache_retains_at_most_four_roots_and_an_evicted_root_requires_replay(chain, replay_calls):
    root, states = chain
    roots = [root]
    for index in range(1, 5):
        other = root.parent / f'campaign-copy-{index}'
        shutil.copytree(root, other)
        roots.append(other)
    for campaign in roots:
        assert history.replay(campaign, head(campaign)) == states[-1]
        assert len(history._VERIFIED) <= 4
    assert len(replay_calls) == 5
    assert len(history._VERIFIED) == 4 and root not in history._VERIFIED
    for campaign in roots[1:]:
        assert history.replay(campaign, head(campaign)) == states[-1]
    assert len(replay_calls) == 5
    assert history.replay(root, head(root)) == states[-1]
    assert len(replay_calls) == 6 and len(history._VERIFIED) == 4


@pytest.mark.parametrize('changed', ['record_being_read', 'already_verified_record'])
def test_cold_replay_refuses_bytes_changed_during_read_and_never_caches_them(chain, replay_calls, monkeypatch, changed):
    root, states = chain
    trigger = root / 'history' / '0001.json'
    target = trigger if changed == 'record_being_read' else root / 'history' / '0000.json'
    original_bytes = target.read_bytes()
    actual = state_io.read_json
    fired = []

    def changing_read(path):
        value = actual(path)
        if Path(path) == trigger and not fired:
            fired.append(True)
            target.write_bytes(original_bytes + b'\n')
        return value

    monkeypatch.setattr(state_io, 'read_json', changing_read)
    with pytest.raises(ValueError, match='research history changed during replay'):
        cycle._load_history(root)
    assert fired and len(replay_calls) == 1
    assert root not in history._VERIFIED
    target.write_bytes(original_bytes)
    assert cycle._load_history(root)[1] == states[-1]
    assert len(replay_calls) == 2
    assert cycle._load_history(root)[1] == states[-1]
    assert len(replay_calls) == 2
