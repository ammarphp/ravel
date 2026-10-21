"""Concurrent ledger transactions retain every event and publish only verified snapshots."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing
import os
import random
import threading
import time

import pytest

from ravel.controller import ledger
from ravel.controller import store as store_module
from ravel.controller.ledger import chain, state
from p02_support import fixture_catalogue, row, use_catalogue


RUN = 'concurrent-run'


def _catalogue():
    return fixture_catalogue([
        row('X-INITIAL', 'controller.intake', 'intake', 'run'),
        row('X-EVENT', 'controller.event', 'event', 'event', select={'gate': 'correction'}),
    ])


def _intake(store):
    ledger.materialise(store, 'intake', {'run_id': RUN, 'task_mode': 'calculate', 'deliverables': []})


def _append(store, token):
    keys = ledger.materialise(store, 'event', {'kind': 'correction', 'id': token})
    assert len(keys) == 1
    ledger.record(store, keys[0], 'satisfied', {'mechanism': 'controller.event', 'record': token})


def _read(store, which):
    if which == 0:
        assert ledger.verify(store)['verified']
    elif which == 1:
        assert ledger.summary(store)['chain']['verified']
    elif which == 2:
        ledger.current(store)
    elif which == 3:
        ledger.pending(store)
    elif which == 4:
        assert not any(r['reason'] == 'chain_broken' for r in ledger.gate(store, 'intake->route_select'))
    else:
        assert state.load(store).error is None


def _parallel_participant(root, participant, barrier):
    """Each spawned process opens independent handles and overlaps readers with three writers."""
    with pytest.MonkeyPatch.context() as patch:
        use_catalogue(patch, _catalogue())
        original_scan = chain.scan

        def delayed_scan(store):
            records = original_scan(store)
            # Widen the snapshot/high-water window with reproducible randomized interleavings.
            time.sleep(random.Random(threading.get_ident() + len(records)).uniform(0, .002))
            return records

        patch.setattr(chain, 'scan', delayed_scan)
        threads_ready = threading.Barrier(6)

        def writer(number):
            store = store_module.RunStore(RUN, root=root)
            rng = random.Random(1000 * participant + number)
            threads_ready.wait(timeout=30)
            tokens = []
            for index in range(12):
                token = f'event-{participant}-{number}-{index}'
                time.sleep(rng.uniform(0, .002))
                _append(store, token)
                tokens.append(token)
            return tokens

        def reader(number):
            store = store_module.RunStore(RUN, root=root)
            rng = random.Random(2000 * participant + number)
            threads_ready.wait(timeout=30)
            for _ in range(36):
                _read(store, rng.randrange(6))
                assert store.verify() == []
                time.sleep(rng.uniform(0, .002))

        def other_writer():
            store = store_module.RunStore(RUN, root=root)
            threads_ready.wait(timeout=30)
            for index in range(12):
                store.append('observation', {'participant': participant, 'index': index})

        barrier.wait(timeout=60)
        with ThreadPoolExecutor(max_workers=6) as pool:
            writers = [pool.submit(writer, n) for n in range(3)]
            readers = [pool.submit(reader, n) for n in range(2)]
            other = pool.submit(other_writer)
            tokens = [token for future in writers for token in future.result(timeout=90)]
            for future in readers + [other]:
                future.result(timeout=90)
        return tokens


def test_parallel_appenders_and_readers_preserve_every_event_once(tmp_path, monkeypatch):
    use_catalogue(monkeypatch, _catalogue())
    root = tmp_path / 'store'
    store = store_module.RunStore(RUN, root=root)
    _intake(store)
    context = multiprocessing.get_context('spawn')
    with context.Manager() as manager:
        barrier = manager.Barrier(4)
        with ProcessPoolExecutor(max_workers=4, mp_context=context) as pool:
            futures = [pool.submit(_parallel_participant, root, n, barrier) for n in range(4)]
            expected = [token for future in futures for token in future.result(timeout=150)]
    fresh = store_module.RunStore(RUN, root=root)
    events, error = chain.verify(chain.scan(fresh))
    assert error is None
    assert len(events) == 1 + 2 * len(expected)
    assert [event['seq'] for event in events] == list(range(len(events)))
    materialised = [event['body']['context']['id'] for event in events[1:]
                    if event['body']['event'] == 'materialise']
    recorded = [event['body']['changes'][0]['evidence']['record'] for event in events[1:]
                if event['body']['event'] == 'status']
    assert len(expected) == len(set(expected)) == 144
    assert sorted(materialised) == sorted(recorded) == sorted(expected)
    assert len(fresh.scan('observation')) == 48
    assert fresh.verify() == []
    assert ledger.verify(fresh)['events'] == len(events)
    assert ledger.summary(fresh)['by_status']['satisfied'] == len(expected)


def test_serial_append_is_a_positive_control(tmp_path, monkeypatch):
    use_catalogue(monkeypatch, _catalogue())
    store = store_module.RunStore(RUN, root=tmp_path / 'store')
    _intake(store)
    for n in range(3):
        _append(store, f'event-{n}')
        for reader in range(6):
            _read(store, reader)
    assert ledger.verify(store)['events'] == 7
    assert store.verify() == []


def test_a_reader_snapshot_cannot_race_the_verified_high_water(tmp_path, monkeypatch):
    use_catalogue(monkeypatch, _catalogue())
    store = store_module.RunStore(RUN, root=tmp_path / 'store')
    _intake(store)
    snapshot_taken, release = threading.Event(), threading.Event()
    writer_started = threading.Event()
    original_scan = chain.scan

    def paused_scan(handle):
        records = original_scan(handle)
        if threading.current_thread().name.startswith('snapshot-reader'):
            snapshot_taken.set()
            assert release.wait(10)
        return records

    def write():
        writer_started.set()
        _append(store, 'later-event')
        assert ledger.verify(store)['verified']

    monkeypatch.setattr(chain, 'scan', paused_scan)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='snapshot-reader') as readers, \
            ThreadPoolExecutor(max_workers=1) as writers:
        reader = readers.submit(ledger.verify, store)
        assert snapshot_taken.wait(10)
        writer = writers.submit(write)
        try:
            assert writer_started.wait(10)
            # The writer either completes on the old implementation or waits for the snapshot lock.
            threading.Event().wait(.1)
        finally:
            release.set()
        assert reader.result(timeout=10)['verified']
        writer.result(timeout=10)
    assert ledger.verify(store)['events'] == 3


def test_extending_the_cache_does_not_mutate_an_earlier_snapshot(tmp_path, monkeypatch):
    use_catalogue(monkeypatch, _catalogue())
    store = store_module.RunStore(RUN, root=tmp_path / 'store')
    _intake(store)
    before = state.load(store)
    _append(store, 'later-event')
    after = state.load(store)
    assert (before.events, len(before.instances)) == (1, 1)
    assert (after.events, len(after.instances)) == (3, 2)


def test_lock_identity_resolves_directory_aliases_and_refuses_a_linked_lock(tmp_path):
    store = store_module.RunStore(RUN, root=tmp_path / 'store')
    alias = tmp_path / 'alias'
    alias.symlink_to(store.root, target_is_directory=True)

    class Alias:
        def path(self, *parts):
            return alias.joinpath(*parts)

    assert chain.store_key(Alias()) == chain.store_key(store)
    with chain.locked(store), chain.locked(Alias()):
        pass  # Re-entry through a second handle must not open a second file-lock description.
    lock_path = store.path(chain.LOCK)
    lock_path.unlink()
    target = tmp_path / 'other-lock'
    target.touch(mode=0o600)
    lock_path.symlink_to(target)
    with pytest.raises(ledger.LedgerError) as refused:
        with chain.locked(store):
            pytest.fail('a linked lock was accepted')
    assert refused.value.code == 'store_unavailable'


def _paused_journal_writer(root, started, release, result):
    """Pause a process after a short journal write, before its record/head publication completes."""
    store = store_module.RunStore(RUN, root=root)
    write = os.write
    paused = False

    def short_write(fd, data):
        nonlocal paused
        journal = store.root / store_module.JOURNAL
        if not paused and os.fstat(fd).st_ino == journal.stat().st_ino:
            paused = True
            written = write(fd, data[:len(data) // 2])
            started.set()
            assert release.wait(15)
            return written
        return write(fd, data)

    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(os, 'write', short_write)
            identifier = store.append('observation', {'value': 'complete'})
        result.put(('ok', identifier))
    except Exception as exc:
        result.put(('error', repr(exc)))


@pytest.mark.parametrize('reader', ['scan', 'read', 'head', 'verify'])
def test_journal_readers_wait_for_a_process_to_finish_publication(tmp_path, reader):
    root = tmp_path / 'store'
    store = store_module.RunStore(RUN, root=root)
    identifier = store.append('observation', {'value': 'initial'})
    context = multiprocessing.get_context('spawn')
    started, release, result = context.Event(), context.Event(), context.Queue()
    writer = context.Process(target=_paused_journal_writer, args=(root, started, release, result))
    writer.start()
    try:
        assert started.wait(15)
        entered = threading.Event()

        def read():
            entered.set()
            if reader == 'read':
                return store.read('observation', identifier)
            return getattr(store, reader)(*(['observation'] if reader == 'scan' else []))

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(read)
            try:
                assert entered.wait(10)
                time.sleep(.1)
                assert not future.done(), 'a reader observed an append before publication completed'
            finally:
                release.set()
            value = future.result(timeout=15)
        assert result.get(timeout=15)[0] == 'ok'
        assert value if reader != 'verify' else value == []
        assert len(store.scan('observation')) == 2
        assert store.verify() == []
    finally:
        release.set()
        writer.join(timeout=20)
        if writer.is_alive():
            writer.terminate()
            writer.join(timeout=10)
        result.close()
        result.join_thread()
    assert writer.exitcode == 0


def test_an_incomplete_crash_record_refuses_reads_but_append_recovers_it(tmp_path):
    store = store_module.RunStore(RUN, root=tmp_path / 'store')
    identifier = store.append('observation', {'value': 'initial'})
    with store.path(store_module.JOURNAL).open('ab') as stream:
        stream.write(b'{"incomplete":')
    for read in (lambda: store.scan('observation'), lambda: store.read('observation', identifier), store.head):
        with pytest.raises(store_module.StoreTampered, match='incomplete'):
            read()
    assert 'incomplete' in store.verify()[0]
    store.append('observation', {'value': 'recovered'})
    assert [e['record']['value'] for e in store.scan('observation')] == ['initial', 'recovered']
    assert store.verify() == []


@pytest.mark.parametrize('removed', [0, 1, 2])
def test_a_gap_is_a_typed_refusal_for_fresh_readers_and_appenders(tmp_path, monkeypatch, removed):
    use_catalogue(monkeypatch, _catalogue())
    store = store_module.RunStore(RUN, root=tmp_path / 'store')
    _intake(store)
    _append(store, 'event-one')
    journal = store.path(store_module.JOURNAL)
    lines = journal.read_bytes().splitlines(keepends=True)
    journal.write_bytes(b''.join(lines[:removed] + lines[removed + 1:]))
    fresh = store_module.RunStore(RUN, root=tmp_path / 'store')
    for read in (lambda: fresh.scan('ledger'), lambda: ledger.current(fresh),
                 lambda: fresh.append('observation', {'value': 'must-refuse'})):
        with pytest.raises(store_module.StoreTampered):
            read()
    assert fresh.verify()
