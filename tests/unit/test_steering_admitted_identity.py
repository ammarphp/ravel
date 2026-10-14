"""Admitted in-process work is identified by more than a process id.

Each crash test starts a real graph node in a child process (the node start admits it under
steering) and then ends that process the way a crash does. A killed process, an unreaped one and a process id that another
process now carries must all stop counting as running work, the stale record must leave the
custody file, and a pause must reach ``observed-stopped`` instead of staying ``draining``.
"""
import json
import os
import signal
import time

import pytest

from ravel.workflow import gate_wiring as gw


@pytest.fixture
def scope(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'scope'
    root.mkdir()
    return root


@pytest.fixture
def children():
    """``(pid, descriptor)`` of each child process of this test; all are killed, reaped and closed at teardown."""
    started = []
    yield started
    for pid, descriptor in started:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        os.close(descriptor)


def child(children, body):
    """Fork a child that runs ``body(report)`` and never returns into the test session.

    Returns its process id and a descriptor that reads end-of-file once the child has terminated."""
    read, write = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read)
            body(lambda: os.write(write, b'1'))
        finally:
            os._exit(0)
    children.append((pid, read))
    os.close(write)
    assert os.read(read, 1) == b'1', 'the child ended before it reported'
    return pid, read


def admitted_child(children, scope):
    """A child that starts a real instrumented graph node and stays inside the node body."""
    from ravel.workflow import graph_nodes

    def body(report):
        def node(state):
            report()
            time.sleep(600)
            return {}
        graph_nodes._instrumented('compute', 'synthetic-graph', None, node)({'meta': {'scope_root': str(scope)}})
    return child(children, body)


def idle_child(children):
    def body(report):
        report()
        time.sleep(600)
    return child(children, body)


def stored(scope):
    path = gw._admitted_store(scope)
    return json.loads(path.read_text()) if path.is_file() else []


def lock_files(scope):
    directory = gw._admitted_store(scope).parent / gw.ADMITTED_LOCKS
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


def ended_without_reaping(pid, descriptor):
    """Wait until the process has terminated and leave it unreaped."""
    assert os.read(descriptor, 1) == b''  # the kernel is closing its descriptors: it has terminated
    os.kill(pid, 0)  # an unreaped process still answers a signal probe


def eventually(condition, seconds=10):
    """True once ``condition()`` holds; the kernel finishes a killed process a moment after the signal."""
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def pause(scope):
    gw.record_steering(scope, 'Pause the study.', effect='pause')
    return gw.steering_state(scope)


def test_work_admitted_in_another_process_is_reported_while_that_process_runs(scope, children):
    pid, _ = admitted_child(children, scope)
    rows = gw.admitted_work(scope)
    assert [(row['pid'], row['role']) for row in rows] == [(pid, 'graph-node')]
    # The record names more than the process id: the admission lock its process holds.
    assert rows[0]['lock'] in lock_files(scope)
    state = pause(scope)
    assert state['pause_status'] == 'draining' and not state['observed_stopped']
    assert gw.admitted_work(scope) == rows and stored(scope) == rows


def test_process_killed_after_admission_no_longer_counts_and_its_record_is_removed(scope, children):
    pid, _ = admitted_child(children, scope)
    assert pause(scope)['pause_status'] == 'draining'
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    assert stored(scope) != []  # the crash left the record behind
    assert gw.admitted_work(scope) == []
    # Removed durably, with its lock file, not only filtered from the answer.
    assert stored(scope) == [] and lock_files(scope) == []
    state = gw.steering_state(scope)
    assert state['pause_status'] == 'observed-stopped' and state['observed_stopped']


def test_terminated_process_that_was_not_reaped_no_longer_counts(scope, children):
    pid, descriptor = admitted_child(children, scope)
    os.kill(pid, signal.SIGKILL)
    ended_without_reaping(pid, descriptor)
    assert eventually(lambda: gw.admitted_work(scope) == [])
    assert stored(scope) == [] and lock_files(scope) == []
    assert pause(scope)['pause_status'] == 'observed-stopped'
    os.kill(pid, 0)  # still unreaped: the answer did not depend on reaping it


@pytest.mark.parametrize('carrier', ['another-process', 'the-inspecting-process'])
def test_reused_process_id_does_not_keep_a_pause_draining(scope, children, carrier):
    pid, _ = admitted_child(children, scope)
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    # The process id of the dead worker is carried by an unrelated live process now.
    reused = idle_child(children)[0] if carrier == 'another-process' else os.getpid()
    rows = stored(scope)
    assert len(rows) == 1
    rows[0]['pid'] = reused
    gw._admitted_store(scope).write_text(json.dumps(rows))
    os.kill(reused, 0)  # alive: a check of the process id alone would call the work running
    state = pause(scope)
    assert state['pause_status'] == 'observed-stopped' and state['observed_stopped']
    assert gw.admitted_work(scope) == [] and stored(scope) == [] and lock_files(scope) == []


def test_next_admission_removes_the_stale_record_of_a_crashed_process(scope, children):
    pid, _ = admitted_child(children, scope)
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    seen = {}
    with gw.steering_admitted(scope, 'next') as identifier:
        seen['stored'] = stored(scope)
        seen['running'] = gw.admitted_work(scope)
    assert [row['id'] for row in seen['stored']] == [identifier]
    assert [row['id'] for row in seen['running']] == [identifier]
    assert stored(scope) == [] and lock_files(scope) == []


def test_work_admitted_in_this_process_counts_until_its_body_ends(scope):
    with gw.steering_admitted(scope, 'first') as first, gw.steering_admitted(scope, 'second') as second:
        assert sorted(row['id'] for row in gw.admitted_work(scope)) == sorted([first, second])
        assert pause(scope)['pause_status'] == 'draining'
    assert gw.admitted_work(scope) == [] and lock_files(scope) == []
    assert gw.steering_state(scope)['pause_status'] == 'observed-stopped'


def test_refused_admission_leaves_no_record_and_no_lock(scope):
    gw.record_steering(scope, 'Stop the study.', effect='veto')
    with pytest.raises(gw.SteeringRefused):
        with gw.steering_admitted(scope, 'node'):
            pytest.fail('vetoed work was admitted')
    assert stored(scope) == [] and lock_files(scope) == []


def test_body_that_raises_releases_its_admission(scope):
    with pytest.raises(RuntimeError, match='synthetic'):
        with gw.steering_admitted(scope, 'node'):
            raise RuntimeError('synthetic failure in the body')
    assert gw.admitted_work(scope) == [] and stored(scope) == [] and lock_files(scope) == []


def test_record_whose_lock_name_leaves_the_lock_directory_is_not_followed(scope, children, tmp_path):
    """A record cannot point the liveness probe at another file."""
    outside = tmp_path / 'outside.lock'
    outside.write_text('')
    pid, _ = idle_child(children)
    gw._admitted_change(scope, add={'id': 'steering-admitted-forged', 'pid': pid, 'role': 'graph-node',
                                    'node_id': None, 'scope': str(scope), 'started_utc': 'synthetic',
                                    'lock': '../../outside.lock'})
    assert gw.admitted_work(scope) == []
    assert outside.exists()


def test_record_written_before_admissions_held_a_lock_is_judged_by_its_process(scope, children):
    """The earlier record format has only a process id; it counts while that process exists."""
    pid, _ = idle_child(children)
    gw._admitted_change(scope, add={'id': 'steering-admitted-earlier', 'pid': pid, 'role': 'graph-node',
                                    'node_id': None, 'scope': str(scope), 'started_utc': 'synthetic'})
    assert [row['pid'] for row in gw.admitted_work(scope)] == [pid]
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    assert gw.admitted_work(scope) == [] and stored(scope) == []
