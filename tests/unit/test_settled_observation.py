"""The opening observation of a file waits until a later change must alter its change time."""
from types import SimpleNamespace

import pytest

from ravel.workflow import validation_io as vio

SECOND = 1_000_000_000


class Clock:
    """A stamping clock and a monotonic clock that advance only when the code sleeps."""

    def __init__(self, monkeypatch, now):
        self.now, self.slept = now, []
        monkeypatch.setattr(vio, '_stamp_clock_ns', lambda: self.now)
        monkeypatch.setattr(vio.time, 'monotonic_ns', lambda: self.now)
        monkeypatch.setattr(vio.time, 'sleep', self.sleep)

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += round(seconds * SECOND)


def observer(stamps):
    calls = []

    def observe():
        calls.append(stamps[min(len(calls), len(stamps) - 1)])
        return SimpleNamespace(st_ctime_ns=calls[-1])
    return observe, calls


def test_an_older_change_time_is_returned_at_once(monkeypatch):
    clock = Clock(monkeypatch, 5 * SECOND + 123_456_789)
    observe, calls = observer([5 * SECOND + 123_456_788])
    assert vio.settled(observe).st_ctime_ns == 5 * SECOND + 123_456_788
    assert len(calls) == 1 and clock.slept == []


@pytest.mark.parametrize('behind', [0, 1, 999_999])
def test_a_change_within_the_current_clock_step_is_waited_out_and_observed_again(monkeypatch, behind):
    stamp = 7 * SECOND + 415_722_677
    clock = Clock(monkeypatch, stamp - behind)
    observe, calls = observer([stamp])
    assert vio.settled(observe).st_ctime_ns == stamp
    assert len(calls) == 2 and clock.slept == [(behind + 1) / SECOND]
    assert clock.now > stamp


@pytest.mark.parametrize('stamp,step', [(9 * SECOND, SECOND), (9 * SECOND + 250_000_000, 1_000_000),
                                        (9 * SECOND + 250_001_000, 1_000), (9 * SECOND + 250_001_001, 1)])
def test_the_wait_covers_one_step_of_the_filesystem_stamps(monkeypatch, stamp, step):
    assert vio._stamp_step_ns(stamp) == step
    clock = Clock(monkeypatch, stamp + step - 1)        # one nanosecond short of a full step
    observe, calls = observer([stamp])
    vio.settled(observe)
    assert clock.slept == [1 / SECOND] and len(calls) == 2
    clock = Clock(monkeypatch, stamp + step)
    observe, calls = observer([stamp])
    vio.settled(observe)
    assert clock.slept == [] and len(calls) == 1


def test_a_file_changed_during_the_wait_is_waited_for_again(monkeypatch):
    first, second = 3 * SECOND + 1, 3 * SECOND + 700_001
    clock = Clock(monkeypatch, first)
    observe, calls = observer([first, second, second])
    assert vio.settled(observe).st_ctime_ns == second
    assert len(calls) == 3 and len(clock.slept) == 2 and clock.now > second


def test_a_change_time_from_another_clock_is_returned_without_waiting(monkeypatch):
    clock = Clock(monkeypatch, 4 * SECOND + 5)
    observe, calls = observer([4 * SECOND + 5 + vio.SETTLE_LIMIT_NS + 7])
    assert vio.settled(observe).st_ctime_ns == calls[0]
    assert len(calls) == 1 and clock.slept == []


def test_a_file_that_never_stops_changing_ends_at_the_limit(monkeypatch):
    clock = Clock(monkeypatch, 2 * SECOND + 3)
    calls = []

    def observe():                                       # every observation finds a newer change
        calls.append(clock.now + 400_000_001)
        return SimpleNamespace(st_ctime_ns=calls[-1])
    assert vio.settled(observe).st_ctime_ns == calls[-1]
    assert sum(clock.slept) * SECOND <= vio.SETTLE_LIMIT_NS + 500_000_000 and 2 <= len(calls) <= 6


def test_a_same_size_rewrite_after_a_settled_observation_always_changes_the_identity(tmp_path):
    path = tmp_path / 'source.bin'
    for trial in range(120):
        path.write_bytes(b'a' * 12)
        before = vio.identity(vio.settled(path.stat))
        path.write_bytes(b'b' * 12)
        assert vio.identity(path.stat()) != before, trial


def test_a_change_and_restore_after_a_settled_observation_always_changes_the_identity(tmp_path):
    path = tmp_path / 'source.bin'
    original = b'{"value":3}\n'
    for trial in range(120):
        path.write_bytes(original)
        before = vio.identity(vio.settled(path.lstat))
        path.write_bytes(b'{"value":9}\n')
        path.write_bytes(original)
        assert path.read_bytes() == original and vio.identity(path.lstat()) != before, trial


def test_session_baseline_sees_a_same_size_rewrite(tmp_path):
    from ravel.workflow import execution
    from ravel.workflow.state_io import read_json
    for trial in range(40):
        root = tmp_path / str(trial)
        root.mkdir()
        session = vio.ValidationSession(root, resolve_path=lambda base, value, output=False: base / value,
                                        read_json=read_json, runtime_context=lambda: {'version': 'synthetic'},
                                        digest=execution.digest, state_name='ledger.json')
        data = root / 'data.bin'
        data.write_bytes(b'old')
        session.hash_file(data)
        data.write_bytes(b'new')
        with pytest.raises(ValueError, match='changed'):
            session.observe(data)
        session.close()


def recorded_settling(monkeypatch):
    """Record each stat result that a reader takes through the settled helper."""
    taken, original = [], vio.settled

    def settled(observe):
        value = original(observe)
        taken.append((value.st_dev, value.st_ino))
        return value
    monkeypatch.setattr(vio, 'settled', settled)
    return taken


def test_the_bounded_research_source_snapshot_opens_with_a_settled_observation(tmp_path, monkeypatch):
    from ravel.workflow import research_cycle
    path = tmp_path / 'request.json'
    path.write_bytes(b'{"value":3}\n')
    taken = recorded_settling(monkeypatch)
    assert research_cycle._bounded_source_snapshot(path, 64)[1] == b'{"value":3}\n'
    leaf = path.lstat()
    assert taken == [(leaf.st_dev, leaf.st_ino)]


def test_the_initialized_settings_reader_opens_with_a_settled_observation(tmp_path, monkeypatch):
    from ravel.physics import native_event_io
    path = tmp_path / 'settings.json'
    path.write_bytes(b'{"value":3}\n')
    taken = recorded_settling(monkeypatch)
    value, record = native_event_io.read_initialized_settings(path)
    leaf = path.lstat()
    assert value == {'value': 3} and record['bytes'] == 12
    assert taken == [(leaf.st_dev, leaf.st_ino)]


def test_the_source_capture_opens_each_consumed_file_with_a_settled_observation(tmp_path, monkeypatch):
    import hashlib
    from ravel.physics import cosmic_evolution_core as core
    path = tmp_path / 'rank.json'
    path.write_bytes(b'{"rank":0}\n')
    pin = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': 11}
    taken = recorded_settling(monkeypatch)
    capture = core.Capture(tmp_path, {'max_input_files': 2, 'max_input_bytes': 1024})
    assert capture.json(pin) == {'rank': 0}
    leaf = path.lstat()
    assert taken == [(leaf.st_dev, leaf.st_ino)]
    capture.finish()
