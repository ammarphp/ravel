"""Binary Gram stores: streaming blocks, completion markers and resumable schedules."""
import json

import numpy as np
import pytest

from ravel.physics import amplitude_basis as ab
from ravel.physics import amplitude_store as store

MEMBERS = ['continuum', 'scalar_top', 'pseudoscalar_top']
PARTICLES = {'pdg': [21, 21, 11, -11, 13, -13], 'status': [-1, -1, 1, 1, 1, 1]}


def _header(**extra):
    return {'basis': MEMBERS, 'observables': ['s_gev2', 'm_4l_gev'], 'particles': PARTICLES,
            'factor_unit': 'fb', **extra}


def _chunk(rng, n):
    a = rng.normal(size=(n, 4, 3)) + 1j * rng.normal(size=(n, 4, 3))
    G = ab.point_grams(a, normalization=np.ones(n))
    s = rng.uniform(100.0, 1000.0, size=n) ** 2
    momenta = rng.normal(size=(n, 6, 4))
    return {'gram': G, 'factor': rng.uniform(0.1, 1.0, size=n),
            'observables': np.stack([s, np.sqrt(s)], axis=1), 'momenta': momenta}


def test_block_round_trip_and_marker(tmp_path):
    rng = np.random.default_rng(1)
    path = tmp_path / 'block-a.ravg'
    chunks = [_chunk(rng, 5), _chunk(rng, 3)]
    with store.BlockWriter(path, _header(block={'id': 'a', 'cohort': 'mixed', 'seed': 7})) as writer:
        for c in chunks:
            writer.append(**c)
        writer.finish({'attempted': 10, 'accepted': 8, 'rejected': 2, 'failed': 0})
    marker = json.loads(store.marker_path(path).read_text())
    assert marker['points'] == 8 and marker['summary']['attempted'] == 10
    block = store.read_block(path)
    np.testing.assert_array_equal(block['gram'], np.concatenate([c['gram'] for c in chunks]))
    np.testing.assert_array_equal(block['factor'], np.concatenate([c['factor'] for c in chunks]))
    np.testing.assert_array_equal(block['momenta'], np.concatenate([c['momenta'] for c in chunks]))
    assert block['header']['basis'] == MEMBERS
    streamed = list(store.iter_chunks(path, chunk_points=3))
    assert [len(c['factor']) for c in streamed] == [3, 3, 2]


def test_record_is_compact(tmp_path):
    rng = np.random.default_rng(2)
    path = tmp_path / 'b.ravg'
    with store.BlockWriter(path, _header()) as writer:
        writer.append(**_chunk(rng, 100))
        writer.finish({'attempted': 100, 'accepted': 100, 'rejected': 0, 'failed': 0})
    header_bytes = store.header_size(path)
    per_point = (path.stat().st_size - header_bytes) / 100
    assert per_point == 8 * (1 + 2 + 24 + 9)


def test_unfinished_block_is_not_readable(tmp_path):
    rng = np.random.default_rng(3)
    path = tmp_path / 'b.ravg'
    writer = store.BlockWriter(path, _header())
    writer.append(**_chunk(rng, 4))
    writer.abandon()
    assert not path.exists()
    with pytest.raises(FileNotFoundError):
        store.read_block(path)


def test_changed_block_bytes_are_refused(tmp_path):
    rng = np.random.default_rng(4)
    path = tmp_path / 'b.ravg'
    with store.BlockWriter(path, _header()) as writer:
        writer.append(**_chunk(rng, 4))
        writer.finish({'attempted': 4, 'accepted': 4, 'rejected': 0, 'failed': 0})
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(bytes(raw))
    with pytest.raises(ValueError, match='sha256'):
        store.read_block(path)


def test_shape_mismatch_is_refused(tmp_path):
    rng = np.random.default_rng(5)
    c = _chunk(rng, 3)
    c['observables'] = c['observables'][:, :1]
    with store.BlockWriter(tmp_path / 'b.ravg', _header()) as writer:
        with pytest.raises(ValueError, match='observables'):
            writer.append(**c)
        writer.abandon()


def test_audit_subset_keeps_full_amplitudes(tmp_path):
    rng = np.random.default_rng(6)
    path = tmp_path / 'b.ravg'
    amplitudes = rng.normal(size=(3, 2, 4, 3)) + 1j * rng.normal(size=(3, 2, 4, 3))
    with store.BlockWriter(path, _header(audit_points=2)) as writer:
        writer.append(**_chunk(rng, 3), amplitudes=amplitudes)
        writer.finish({'attempted': 3, 'accepted': 3, 'rejected': 0, 'failed': 0})
    audit = store.read_audit(path)
    assert len(audit['points']) == 2
    np.testing.assert_array_equal(audit['amplitudes'], amplitudes[:2])


def _producer(calls):
    def produce(block, writer):
        calls.append(block['id'])
        rng = np.random.default_rng(block['seed'])
        for _ in range(3):
            writer.append(**_chunk(rng, 4))
        return {'attempted': 12, 'accepted': 12, 'rejected': 0, 'failed': 0}
    return produce


def _schedule(max_seconds=100):
    return {'schema_version': 1, 'blocks': [
        {'id': f'b{i}', 'cohort': 'mixed' if i % 2 else 'same', 'seed': 100 + i, 'draws': 12, 'max_seconds': 10}
        for i in range(4)], 'max_operation_seconds': max_seconds}


def test_schedule_runs_all_blocks_and_writes_manifest(tmp_path):
    calls = []
    manifest = store.run_schedule(tmp_path / 'store', _schedule(), _producer(calls), header=_header())
    assert manifest['status'] == 'complete'
    assert calls == ['b0', 'b1', 'b2', 'b3']
    assert [b['id'] for b in manifest['blocks']] == ['b0', 'b1', 'b2', 'b3']
    assert store.load_manifest(tmp_path / 'store')['status'] == 'complete'


def test_interrupted_schedule_resumes_to_the_same_blocks(tmp_path):
    full = store.run_schedule(tmp_path / 'full', _schedule(), _producer([]), header=_header())

    calls = []
    original = _producer(calls)

    def failing(block, writer):
        if block['id'] == 'b2':
            writer.append(**_chunk(np.random.default_rng(0), 2))
            raise KeyboardInterrupt
        return original(block, writer)

    with pytest.raises(KeyboardInterrupt):
        store.run_schedule(tmp_path / 'resumed', _schedule(), failing, header=_header())
    partial = store.load_manifest(tmp_path / 'resumed')
    assert partial['status'] == 'incomplete' and [b['id'] for b in partial['blocks']] == ['b0', 'b1']
    resumed_calls = []
    resumed = store.run_schedule(tmp_path / 'resumed', _schedule(), _producer(resumed_calls), header=_header())
    assert resumed_calls == ['b2', 'b3']
    assert [b['sha256'] for b in resumed['blocks']] == [b['sha256'] for b in full['blocks']]


def test_operation_budget_stops_between_blocks(tmp_path):
    clock = iter([0.0, 0.0, 6.0, 6.0, 12.0, 12.0, 12.0, 12.0])
    manifest = store.run_schedule(tmp_path / 's', _schedule(max_seconds=11), _producer([]), header=_header(),
                                  clock=lambda: next(clock))
    assert manifest['status'] == 'incomplete'
    assert manifest['remaining'] == ['b2', 'b3']


def test_changed_header_cannot_resume(tmp_path):
    store.run_schedule(tmp_path / 's', _schedule(), _producer([]), header=_header())
    with pytest.raises(ValueError, match='header'):
        store.run_schedule(tmp_path / 's', _schedule(), _producer([]), header=_header(factor_unit='pb'))


def test_tampered_completed_block_is_refused_on_resume(tmp_path):
    manifest = store.run_schedule(tmp_path / 's', _schedule(), _producer([]), header=_header())
    first = tmp_path / 's' / manifest['blocks'][0]['path']
    first.write_bytes(first.read_bytes()[:-8])
    with pytest.raises(ValueError):
        store.run_schedule(tmp_path / 's', _schedule(), _producer([]), header=_header())


def test_schedule_refusals():
    bad = _schedule()
    bad['blocks'][1]['id'] = 'b0'
    with pytest.raises(ValueError, match='unique'):
        store.validate_schedule(bad)
    bad = _schedule()
    bad['blocks'][1]['seed'] = bad['blocks'][0]['seed']
    with pytest.raises(ValueError, match='seed'):
        store.validate_schedule(bad)
    bad = _schedule()
    bad['blocks'][0]['draws'] = 5
    with pytest.raises(ValueError, match='exposure'):
        store.validate_schedule(bad)
