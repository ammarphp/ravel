"""Crash recovery and process-local verified journal indexing (synthetic records)."""
import json
import os

import pytest

from ravel.controller import store as st


def opened(tmp_path):
    return st.RunStore('run-index-test', root=tmp_path / 'store')


def test_recover_preserves_tail_and_complete_head_lag(tmp_path):
    store = opened(tmp_path)
    first = store.append('event', {'n': 1})
    head = (store.root / st.HEAD).read_bytes()
    second = store.append('event', {'n': 2})
    (store.root / st.HEAD).write_bytes(head)
    tail = b'{"record": "unfinished'
    with (store.root / st.JOURNAL).open('ab') as stream:
        stream.write(tail)
    fresh = opened(tmp_path)
    with pytest.raises(st.StoreTampered):
        fresh.latest('event')
    identifier = fresh.recover()
    repair = fresh.read('journal-recovery', identifier)['record']
    assert fresh.get_blob(repair['tail_blob']) == tail
    assert repair['tail_bytes'] == len(tail)
    assert repair['head_before']['seq'] == 1
    assert repair['head_after']['seq'] == 2
    assert [row['id'] for row in fresh.scan('event')] == [first, second]
    assert fresh.recover() is None
    assert fresh.count('journal-recovery') == 1
    assert fresh.verify() == []


def test_head_lag_only_is_recorded_once(tmp_path):
    store = opened(tmp_path)
    store.append('event', {})
    previous = (store.root / st.HEAD).read_bytes()
    store.append('event', {})
    (store.root / st.HEAD).write_bytes(previous)
    store.recover()
    assert store.latest('journal-recovery')['record']['cause'] == 'head-lag'
    assert store.count('event') == 2
    assert store.recover() is None


@pytest.mark.parametrize('killpoint', ['truncate', 'head', 'record', 'record-head', 'partial-record'])
def test_recovery_crashes_finish_exactly_once(tmp_path, monkeypatch, killpoint):
    store = opened(tmp_path)
    store.append('event', {'n': 1})
    with (store.root / st.JOURNAL).open('ab') as stream:
        stream.write(b'partial')
    original_truncate = st.os.ftruncate
    original_private = st._write_private
    original_append = st.RunStore._append_locked

    def truncate(fd, size):
        original_truncate(fd, size)
        if killpoint == 'truncate':
            raise OSError('crash after truncate')

    def private(path, data, **kwargs):
        if killpoint == 'record-head' and path.name == st.HEAD:
            raise OSError('crash before head')
        original_private(path, data, **kwargs)
        if killpoint == 'head' and path.name == st.HEAD:
            raise OSError('crash after head')

    def append(self, kind, record, **kwargs):
        if killpoint == 'partial-record' and kind == 'journal-recovery':
            with (self.root / st.JOURNAL).open('ab') as stream:
                stream.write(st._line(kwargs['prepared']).encode()[:80])
            raise OSError('crash during recovery record')
        result = original_append(self, kind, record, **kwargs)
        if killpoint == 'record' and kind == 'journal-recovery':
            raise OSError('crash after record')
        return result

    # The head kill point needs a complete record not yet acknowledged.
    if killpoint == 'head':
        journal = store.root / st.JOURNAL
        journal.write_bytes(journal.read_bytes()[:-7])
        previous = (store.root / st.HEAD).read_bytes()
        store.append('event', {'n': 2})
        (store.root / st.HEAD).write_bytes(previous)
        with journal.open('ab') as stream:
            stream.write(b'partial')
    with monkeypatch.context() as patch:
        patch.setattr(st.os, 'ftruncate', truncate)
        patch.setattr(st, '_write_private', private)
        patch.setattr(st.RunStore, '_append_locked', append)
        with pytest.raises(OSError, match='crash'):
            store.recover()
    fresh = opened(tmp_path)
    fresh.recover()
    assert fresh.count('journal-recovery') == 1
    assert fresh.recover() is None
    assert fresh.verify() == []


@pytest.mark.parametrize('damage', ['chain', 'head', 'acknowledged-tail'])
def test_recovery_refuses_damage_without_mutation(tmp_path, damage):
    store = opened(tmp_path)
    for n in range(3):
        store.append('event', {'n': n})
    journal = store.root / st.JOURNAL
    head = store.root / st.HEAD
    if damage == 'chain':
        journal.write_bytes(journal.read_bytes().replace(b'"n":0', b'"n":9'))
    elif damage == 'head':
        head.write_text('{"seq":0,"digest":"bad"}')
    else:
        journal.write_bytes(journal.read_bytes()[:-10])
    before = {p.name: p.read_bytes() for p in store.root.iterdir() if p.is_file()}
    with pytest.raises(st.StoreTampered):
        opened(tmp_path).recover()
    assert before == {p.name: p.read_bytes() for p in store.root.iterdir() if p.is_file()}


@pytest.mark.parametrize('exclusive', [False, True])
def test_private_writes_loop_and_sync_parent(tmp_path, monkeypatch, exclusive):
    path = tmp_path / 'data'
    original_write = st.os.write
    synced = []
    monkeypatch.setattr(st.os, 'write', lambda fd, data: original_write(fd, data[:3]))
    monkeypatch.setattr(st, '_fsync_directory', lambda directory: synced.append(directory))
    st._write_private(path, b'0123456789abcdef', exclusive=exclusive)
    assert path.read_bytes() == b'0123456789abcdef'
    assert synced == [tmp_path]


@pytest.mark.parametrize('exclusive', [False, True])
def test_private_zero_progress_refuses_without_publishing(tmp_path, monkeypatch, exclusive):
    path = tmp_path / 'data'
    monkeypatch.setattr(st.os, 'write', lambda fd, data: 0)
    with pytest.raises(st.StoreError, match='no progress'):
        st._write_private(path, b'bytes', exclusive=exclusive)
    assert not path.exists()


@pytest.mark.parametrize('fresh', [False, True])
def test_same_size_tampering_is_detected_even_with_restored_mtime(tmp_path, fresh):
    store = opened(tmp_path)
    store.append('event', {'n': 1})
    path = store.root / st.JOURNAL
    info = path.stat()
    path.write_bytes(path.read_bytes().replace(b'"n":1', b'"n":2'))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    reader = opened(tmp_path) if fresh else store
    with pytest.raises(st.StoreTampered):
        reader.latest('event')


def test_valid_rewritten_prefix_is_refused(tmp_path):
    store = opened(tmp_path)
    store.append('event', {'n': 1})
    path = store.root / st.JOURNAL
    entry = json.loads(path.read_bytes())
    body = {k: v for k, v in entry.items() if k not in ('id', 'digest')}
    body['record']['n'] = 2
    entry = {**body, 'id': f"event-000001-{st._digest(body)[:12]}"}
    entry['digest'] = st._digest(entry)
    path.write_text(st._line(entry))
    (store.root / st.HEAD).write_text(json.dumps({'seq': 1, 'digest': entry['digest']}))
    with pytest.raises(st.StoreTampered, match='prefix changed'):
        opened(tmp_path).latest('event')


def test_shared_index_queries_and_appends_have_bounded_work(tmp_path, monkeypatch):
    store = opened(tmp_path)
    for n in range(1000):
        store.append('event' if n % 2 else 'other', {'n': n, 'payload': ['x'] * 10})
    verifications = []
    copies = []
    reads = []
    original_verify = st.RunStore._verify_entry
    original_copy = st.deepcopy
    original_read = st.Path.read_bytes

    def verify(self, entry):
        verifications.append(entry['seq'])
        return original_verify(self, entry)

    def copy(value):
        copies.append(value)
        return original_copy(value)

    def read(path):
        if path.name == st.JOURNAL:
            reads.append(path)
        return original_read(path)

    monkeypatch.setattr(st.RunStore, '_verify_entry', verify)
    monkeypatch.setattr(st, 'deepcopy', copy)
    monkeypatch.setattr(st.Path, 'read_bytes', read)
    fresh = opened(tmp_path)
    assert fresh.count('event') == 500
    assert verifications == [] and reads == []
    for n in range(30):
        # Newly constructed handles fingerprint bytes and reuse the shared index.
        reader = opened(tmp_path) if n % 2 else store
        with reader.snapshot():
            assert reader.count('event') == 500 + n
            assert reader.latest('event')['record']['n'] == (999 if n == 0 else 999 + n)
            reader.append('event', {'n': 1000 + n})
    assert verifications == [] and reads == []
    # One returned envelope and one appended payload per iteration.
    assert len(copies) == 60
    assert store.count('event') == 530
    latest = store.latest('event')
    latest['record']['n'] = -1
    assert store.latest('event')['record']['n'] == 1029
    assert store.verify() == []
    assert len(verifications) == 1030 and len(reads) == 1
    assert len(store.scan('other')) == 500


def test_cold_status_and_incremental_query_measurements(tmp_path, record_property):
    import time
    from ravel.controller import entry
    store = st.RunStore.create(tmp_path / 'run', root=tmp_path / 'stores')
    for n in range(1000):
        store.append('event', {'n': n, 'payload': ['x'] * 10})
    st._STATES.pop(str(store.root))
    started = time.perf_counter()
    view = entry.status(store.run_id, root=store.store_root)
    cold = time.perf_counter() - started
    reader = st.RunStore(store.run_id, root=store.store_root)
    started = time.perf_counter()
    with reader.snapshot():
        for n in range(100):
            assert reader.count('event') == 1000
            assert reader.latest('event')['record']['n'] == 999
        reader.append('event', {'n': 1000})
    incremental = time.perf_counter() - started
    assert view['verify'] == [] and reader.count('event') == 1001
    record_property('journal_events', 1000)
    record_property('cold_status_seconds', cold)
    record_property('indexed_100_query_groups_and_append_seconds', incremental)


def test_shared_reader_reverifies_changed_metadata(tmp_path):
    store = opened(tmp_path)
    store.append('event', {'n': 1})
    path = store.root / st.JOURNAL
    info = path.stat()
    path.write_bytes(path.read_bytes().replace(b'"n":1', b'"n":2'))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    with pytest.raises(st.StoreTampered):
        store.latest('event')


def test_isolated_private_audit_reader_remains_compatible(tmp_path):
    store = opened(tmp_path)
    store.append('event', {})
    fresh = st.RunStore.__new__(st.RunStore)
    fresh.run_id, fresh.store_root, fresh.root = store.run_id, store.store_root, store.root
    fresh._lock, fresh._entries, fresh._by_id = store._lock, [], {}
    fresh._offset, fresh._head, fresh._connections = 0, st.GENESIS, []
    fresh._refresh()
    fresh._check_head()
    assert len(fresh._entries) == 1


def test_snapshot_hashes_once_and_warm_queries_do_not_read_journal(tmp_path, monkeypatch):
    store = opened(tmp_path)
    store.append('event', {'n': 1})
    original_open = st.Path.open
    journal_opens = []

    def open_path(path, *args, **kwargs):
        if path.name == st.JOURNAL:
            journal_opens.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(st.Path, 'open', open_path)
    with store.snapshot():
        for _ in range(50):
            assert store.latest('event')['record']['n'] == 1
            assert store.count('event') == 1
        with store.snapshot():
            assert len(store.scan('event')) == 1
    assert len(journal_opens) == 1
    store.count('event')
    assert len(journal_opens) == 2


def test_snapshot_supports_cross_handle_reads_and_forced_audits(tmp_path):
    store = opened(tmp_path)
    store.append('event', {'n': 1})
    with store.snapshot():
        fresh = opened(tmp_path)
        with fresh.snapshot():
            assert fresh.count('event') == 1
            assert fresh.verify() == []
            fresh.append('event', {'n': 2})
            assert store.latest('event')['record']['n'] == 2
        assert store.head()['seq'] == 2
    assert fresh.count('event') == 2


def test_restoration_successor_binding_retains_original_and_checks_identity(tmp_path):
    store = st.RunStore.create(tmp_path / 'original', root=tmp_path / 'store')
    original = store.run_record()
    restored = tmp_path / 'restored'
    restored.mkdir()
    info = restored.stat()
    binding = {**original, 'run_dir': str(restored), 'dev': info.st_dev, 'ino': info.st_ino,
               'identity': 'restoration-identity'}
    store.append('run-restoration', binding)
    marker = restored / st.RUN_MARKER
    marker.write_text(json.dumps({'run_id': store.run_id, 'restoration_identity': 'wrong'}))
    assert any('restoration identity' in p for p in store.check_binding())
    marker.write_text(json.dumps({'run_id': store.run_id,
                                  'restoration_identity': 'restoration-identity'}))
    assert store.run_record() == binding
    assert store.scan('run')[0]['record'] == original
    assert store.check_binding() == []
    assert store.check_binding(tmp_path / 'original')
    (store.root / 'RESTORE-FAILED').touch()
    assert any('restoration failed' in p for p in store.check_binding())


@pytest.mark.parametrize('name', [st.HEAD, st.JOURNAL])
def test_recovery_refuses_linked_journal_or_head_without_mutation(tmp_path, name):
    store = opened(tmp_path)
    store.append('event', {})
    path = store.root / name
    original = path.read_bytes()
    target = tmp_path / 'linked'
    target.write_bytes(original)
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(st.StoreTampered, match='not a regular file'):
        store.recover()
    assert path.is_symlink() and target.read_bytes() == original


def test_existing_store_audits_when_module_constructor_is_replaced(tmp_path, monkeypatch):
    store = opened(tmp_path)
    store.append('event', {'n': 1})
    monkeypatch.setattr(st, 'RunStore', lambda *args, **kwargs: store)
    assert store.verify() == []
    assert store.latest('event')['record']['n'] == 1
    path = store.root / st.JOURNAL
    info = path.stat()
    path.write_bytes(path.read_bytes().replace(b'"n":1', b'"n":2'))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert store.verify()
    with pytest.raises(st.StoreTampered):
        store.latest('event')


def test_external_append_parses_only_new_entries_and_forced_audit_parses_all(tmp_path, monkeypatch):
    store = opened(tmp_path)
    for n in range(100):
        store.append('event', {'n': n})
    # Synthesize an external writer: publish bytes/head without changing shared indexes.
    entry = store._prepare_entry('event', {'n': 100})
    with (store.root / st.JOURNAL).open('ab') as stream:
        stream.write(st._line(entry).encode())
    (store.root / st.HEAD).write_text(json.dumps({'seq': entry['seq'], 'digest': entry['digest']}))
    parsed = []
    original = st.RunStore._verify_entry

    def verify(self, candidate):
        parsed.append(candidate['seq'])
        return original(self, candidate)

    monkeypatch.setattr(st.RunStore, '_verify_entry', verify)
    assert opened(tmp_path).latest('event')['record']['n'] == 100
    assert parsed == [101]
    assert store.count('event') == 101
    assert parsed == [101]
    parsed.clear()
    assert store.verify() == []
    assert parsed == list(range(1, 102))


def test_external_tail_is_not_published_until_every_line_validates(tmp_path):
    store = opened(tmp_path)
    store.append('event', {'n': 1})
    entry = store._prepare_entry('event', {'n': 2})
    with (store.root / st.JOURNAL).open('ab') as stream:
        stream.write(st._line(entry).encode() + b'{not-json}\n')
    original_entries = store._entries
    with pytest.raises(st.StoreTampered, match='unreadable record at sequence 3'):
        store.latest('event')
    assert store._entries is original_entries
    assert len(store._entries) == 1
    assert len(store._by_kind['event']) == 1
