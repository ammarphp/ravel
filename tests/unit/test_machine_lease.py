"""The machine lease: one native scientific job per machine, waiting and proven inheritance."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

from ravel.workflow import machine_lease as ml

HOLD = ('import sys,time\n'
        'from ravel.workflow import machine_lease as m\n'
        'with m.held(sys.argv[1]) as lease:\n'
        '    print(lease.lease_id, flush=True)\n'
        '    time.sleep(float(sys.argv[2]))\n')
CHILD = ('import json,sys\n'
         'from ravel.workflow import machine_lease as m\n'
         'try:\n'
         '    lease = m.acquire("child")\n'
         '    print(json.dumps({"inherited": lease.inherited, "holder": lease.holder}))\n'
         '    m.release(lease)\n'
         'except m.LeaseBusy as exc:\n'
         '    print(json.dumps({"busy": str(exc)}))\n')


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.delenv(ml.ENV, raising=False)


def _env(**extra):
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(p for p in sys.path if p)
    env.update(extra)
    return env


def _holder(seconds):
    proc = subprocess.Popen([sys.executable, '-c', HOLD, 'external', str(seconds)], stdout=subprocess.PIPE,
                            text=True, env=_env(), start_new_session=True)
    token = proc.stdout.readline().strip()
    assert token, 'holder did not take the lease'
    return proc, token


def _stop(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()


def test_acquire_release_and_holder_record(tmp_path):
    lease = ml.acquire('run-a:stage', rundir='/r', node_id='stage')
    try:
        record = ml.holder()
        assert record['lease_id'] == lease.lease_id and record['holder'] == 'run-a:stage'
        assert record['pid'] == os.getpid() and record['alive'] is True
        assert record['rundir'] == '/r' and record['node_id'] == 'stage'
    finally:
        ml.release(lease)
    ml.release(lease)  # idempotent
    assert ml.holder() is None


def test_one_process_cannot_hold_two_jobs():
    with ml.held('first'):
        with pytest.raises(ml.LeaseBusy, match='native scientific job') as caught:
            ml.acquire('second')
        assert caught.value.held['holder'] == 'first'
    with ml.held('third'):
        pass


def test_a_second_acquire_waits_for_the_holder_to_finish():
    proc, _ = _holder(1.0)
    try:
        waited = []
        started = time.monotonic()
        lease = ml.acquire('waiting', wait_seconds=30, on_wait=waited.append)
        elapsed = time.monotonic() - started
        ml.release(lease)
        assert elapsed >= 0.5 and len(waited) == 1 and waited[0]['holder'] == 'external'
    finally:
        _stop(proc)


def test_wait_bound_raises_lease_busy_with_the_holder():
    proc, _ = _holder(30)
    try:
        with pytest.raises(ml.LeaseBusy) as caught:
            ml.acquire('late', wait_seconds=0.3)
        assert caught.value.held['holder'] == 'external' and caught.value.held['alive'] is True
    finally:
        _stop(proc)


def test_a_dead_holder_leaves_a_stale_record_and_frees_the_machine():
    proc, _ = _holder(30)
    _stop(proc)
    record = ml.holder()
    assert record['holder'] == 'external' and record['alive'] is False
    lease = ml.acquire('after-crash')
    ml.release(lease)


def test_a_proven_descendant_inherits_the_lease():
    with ml.held('parent-stage'):
        out = subprocess.check_output([sys.executable, '-c', CHILD], text=True, env=_env())
    assert '"inherited": true' in out and '"holder": "parent-stage"' in out


def test_a_forged_token_grants_nothing():
    with ml.held('parent-stage'):
        out = subprocess.check_output([sys.executable, '-c', CHILD], text=True, env=_env(**{ml.ENV: 'f' * 32}))
    assert '"busy"' in out


def test_the_right_token_outside_the_holder_ancestry_grants_nothing():
    proc, token = _holder(30)
    try:
        # This process is not a descendant of the holder, so its token is not proof.
        out = subprocess.check_output([sys.executable, '-c', CHILD], text=True, env=_env(**{ml.ENV: token}))
        assert '"busy"' in out
    finally:
        _stop(proc)


def test_execution_backend_lease_is_the_shared_lease():
    from ravel.workflow import execution_backend as eb
    with eb.machine_lease('backend-holder'):
        assert ml.holder()['holder'] == 'backend-holder'
        with pytest.raises(ValueError, match='native scientific job'):
            ml.acquire('other')


# ---------------------------------------------------------------- one job per machine, bound to the job
SCOPED = ('import json,sys\n'
          'from ravel.workflow import machine_lease as m\n'
          'out = []\n'
          'for row in json.loads(sys.argv[1]):\n'
          '    rundir, node, nested = (row + [False])[:3]\n'
          '    try:\n'
          '        lease = m.acquire("child", rundir=rundir, node_id=node, nested=nested)\n'
          '        out.append({"inherited": lease.inherited, "rundir": lease.rundir})\n'
          '    except m.LeaseBusy as exc:\n'
          '        out.append({"busy": str(exc)})\n'
          'print(json.dumps(out))\n')


def _grandchild(requests):
    import json
    shell = f'{sys.executable} -c \'{SCOPED}\' \'{json.dumps(requests)}\''
    return json.loads(subprocess.check_output(['/bin/sh', '-c', shell], text=True, env=_env()))


def test_a_descendant_cannot_start_a_job_for_another_run():
    with ml.held('run-1:science', rundir='/runs/run-1', node_id='science'):
        rows = _grandchild([['/runs/run-2', 'pythia'], ['/runs/run-3', 'madgraph']])
    assert all('busy' in row for row in rows), rows


def test_the_lease_is_handed_to_one_worker_of_the_job_only():
    with ml.held('run-1:science', rundir='/runs/run-1', node_id='science'):
        rows = _grandchild([['/runs/run-1', 'science'], ['/runs/run-1', 'science']])
        assert rows[0] == {'inherited': True, 'rundir': '/runs/run-1'} and 'busy' in rows[1], rows
        # The first worker ended; a sibling worker may then take the handoff, and only one at a time.
        assert _grandchild([['/runs/run-1', 'science']]) == [{'inherited': True, 'rundir': '/runs/run-1'}]


SLEEP_UNDER_LEASE = ('import os,subprocess,sys,time\n'
                     'from ravel.workflow import machine_lease as m\n'
                     'lease = m.acquire("killed supervisor", rundir="/runs/a", node_id="s")\n'
                     'p = subprocess.Popen(["/bin/sleep", sys.argv[1]], start_new_session=True)\n'
                     'm.fence(lease.lease_id, p.pid, label="payload")\n'
                     'print(p.pid, flush=True)\n'
                     'time.sleep(60)\n')


def test_the_lease_outlives_a_killed_holder_while_its_payload_runs():
    proc = subprocess.Popen([sys.executable, '-c', SLEEP_UNDER_LEASE, '30'], stdout=subprocess.PIPE, text=True,
                            env=_env(), start_new_session=True)
    payload = int(proc.stdout.readline())
    try:
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()
        with pytest.raises(ml.LeaseBusy):
            ml.acquire('second-job', wait_seconds=0)
        assert ml.holder()['alive'] is True and ml.holder()['fenced_groups'][0]['pgid'] == payload
    finally:
        os.kill(payload, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while ml.live_fences() and time.monotonic() < deadline:
        time.sleep(0.05)
    lease = ml.acquire('after-the-payload')
    ml.release(lease)


def test_a_relocated_state_dir_does_not_create_a_second_lease(tmp_path, monkeypatch):
    proc = subprocess.Popen([sys.executable, '-c', HOLD, 'external', '30'], stdout=subprocess.PIPE, text=True,
                            env=_env(RAVEL_STATE_DIR=str(tmp_path / 'state-a')), start_new_session=True)
    try:
        assert proc.stdout.readline().strip()
        monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state-b'))
        with pytest.raises(ml.LeaseBusy):
            ml.acquire('other-state-dir', wait_seconds=0)
    finally:
        _stop(proc)


def test_the_lock_location_ignores_state_dir_and_home(tmp_path, monkeypatch):
    # Resolution only: nothing is written to the machine directory.
    monkeypatch.setattr(ml, '_TEST_DOMAIN', None)
    monkeypatch.delenv(ml.GRANT_ENV)
    monkeypatch.delenv(ml.RUNNER_ENV)
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'a'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    first = ml.machine_dir()
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'b'))
    assert ml.machine_dir() == first and not str(first).startswith(str(tmp_path))
    assert ml.domain() == 'machine'


def test_a_test_lock_domain_needs_its_marker(tmp_path, lock_domain_at):
    (tmp_path / 'unmarked').mkdir()
    with pytest.raises(ValueError, match='ravel-test-machine-domain'):
        lock_domain_at(tmp_path / 'unmarked')
    with pytest.raises(ValueError, match='ravel-test-machine-domain'):
        ml.test_domain_grants().issue(tmp_path / 'missing')


def test_a_recreated_lock_file_does_not_admit_a_second_holder():
    with ml.held('first'):
        (ml.machine_dir() / ml.LOCK_NAME).unlink()
        out = subprocess.check_output([sys.executable, '-c', CHILD], text=True, env=_env(**{ml.ENV: ''}))
    assert '"busy"' in out


def test_reentry_in_one_process_fails_at_once():
    with ml.held('first'):
        started = time.monotonic()
        with pytest.raises(ml.LeaseBusy):
            ml.acquire('second', wait_seconds=30)
        assert time.monotonic() - started < 0.1


def test_a_concurrent_holder_probe_does_not_make_a_no_wait_acquire_fail():
    import threading
    stop = threading.Event()

    def probe():
        while not stop.is_set():
            ml.holder()
    thread = threading.Thread(target=probe)
    thread.start()
    try:
        for _ in range(5):
            ml.release(ml.acquire('no-wait', wait_seconds=0))
    finally:
        stop.set()
        thread.join()


def test_a_forked_child_of_the_holder_neither_holds_nor_releases():
    lease = ml.acquire('parent')
    pid = os.fork()
    if pid == 0:
        os._exit(0 if not ml._OPEN else 1)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    take = [sys.executable, '-c', 'from ravel.workflow import machine_lease as m; m.acquire("x")']
    assert subprocess.call(take, env=_env(), stderr=subprocess.DEVNULL) != 0
    ml.release(lease)
    assert subprocess.call(take, env=_env()) == 0


def test_machine_lock_helper_is_shared_across_state_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'a'))
    with ml.machine_lock('exposure-ledger.lock'):
        code = subprocess.call([sys.executable, '-c', 'from ravel.workflow import machine_lease as m\n'
                                'with m.machine_lock("exposure-ledger.lock", wait_seconds=0.2): pass'],
                               env=_env(RAVEL_STATE_DIR=str(tmp_path / 'b')), stderr=subprocess.DEVNULL)
    assert code != 0


# ---------------------------------------------------------------- approval binding, domains, fence records
@pytest.fixture
def machine_domain(tmp_path, monkeypatch):
    """Machine-domain rules at a temporary location (the in-process location seam), never the real directory."""
    monkeypatch.delenv(ml.TEST_ENV, raising=False)
    monkeypatch.setattr(ml, '_LOCATION', tmp_path / 'machine')
    assert ml.domain() == 'machine'
    return tmp_path / 'machine'


def test_a_native_job_lease_needs_an_approved_stage_binding(tmp_path, machine_domain):
    bare = tmp_path / 'bare'
    (bare / 'logs').mkdir(parents=True)
    with pytest.raises(ml.LeaseBusy, match='approved stage'):
        ml.acquire('probe-holder')
    with pytest.raises(ml.LeaseBusy, match='approved stage'):
        ml.acquire('probe-holder', rundir=str(bare), node_id='gen')
    forged = {'route': 'checkin1', 'rung': 'smoke', 'rundir': str(bare), 'node_id': 'gen'}
    with pytest.raises(ValueError, match='approv'):
        ml.acquire('probe-holder', rundir=str(bare), node_id='gen', binding=forged)
    assert not (machine_domain / ml.RECORD_NAME).exists()


def test_the_retired_variable_selects_no_lock_domain_with_or_without_the_runner_variable(tmp_path, monkeypatch):
    marked = tmp_path / 'domain'
    marked.mkdir()
    (marked / ml.TEST_MARKER).write_text('x')
    monkeypatch.setattr(ml, '_TEST_DOMAIN', None)
    monkeypatch.delenv(ml.GRANT_ENV)
    monkeypatch.setenv(ml.TEST_ENV, str(marked))
    for runner in ('forged', None):
        if runner is None:
            monkeypatch.delenv(ml.RUNNER_ENV, raising=False)
        else:
            monkeypatch.setenv(ml.RUNNER_ENV, runner)
        for probe in (ml.machine_dir, ml.domain, ml.ensure_machine_dir):
            with pytest.raises(ValueError, match='no longer selects'):
                probe()
    assert sorted(p.name for p in marked.iterdir()) == [ml.TEST_MARKER]


def test_a_nested_request_for_another_run_is_refused():
    with ml.held('run-1:science', rundir='/runs/run-1', node_id='science'):
        rows = _grandchild([['/runs/run-2', 'amplitude', True]])
    assert 'busy' in rows[0], rows


def test_one_lease_admits_one_computation_at_a_time():
    with ml.held('run-1:gen', rundir='/runs/run-1', node_id='gen') as lease:
        first = ml.reserve(lease.lease_id, label='first job')
        with pytest.raises(ml.LeaseBusy, match='one computation'):
            ml.reserve(lease.lease_id, label='second job')
        ml.unreserve(first)
        ml.unreserve(ml.reserve(lease.lease_id, label='after the first'))


def _orphaned_group():
    """A /bin/sleep whose session leader has exited: its group lives on without its leader."""
    leader = subprocess.Popen([sys.executable, '-c', 'import subprocess\n'
                               'p = subprocess.Popen(["/bin/sleep", "30"])\nprint(p.pid, flush=True)\n'],
                              stdout=subprocess.PIPE, text=True, start_new_session=True)
    sleeper = int(leader.stdout.readline())
    leader.wait()
    return leader.pid, sleeper


def _write_fence(rows):
    from ravel.workflow.state_io import atomic_json
    atomic_json(ml.ensure_machine_dir() / ml.FENCE_NAME, {'groups': rows})


def test_a_reused_leader_pid_does_not_drop_a_group_with_live_members(monkeypatch):
    pgid, sleeper = _orphaned_group()
    try:
        _write_fence([{'lease_id': 'old', 'pgid': pgid, 'pid': pgid, 'identity': 'Thu Jan  1 00:00:00 1970'}])
        real = ml._identity
        monkeypatch.setattr(ml, '_identity', lambda pid: 'a reused pid' if pid == pgid else real(pid))
        with pytest.raises(ml.LeaseBusy):
            ml.acquire('second-job', wait_seconds=0)
    finally:
        os.kill(sleeper, signal.SIGKILL)


def test_a_fence_entry_of_unknown_identity_is_cleared_by_a_recorded_operator_action():
    pgid, sleeper = _orphaned_group()
    try:
        _write_fence([{'lease_id': 'old', 'pgid': pgid, 'pid': pgid, 'identity': None}])
        with pytest.raises(ml.LeaseBusy):
            ml.acquire('second-job', wait_seconds=0)
        ml.clear_fence(pgid=pgid, reason='group belongs to an unrelated shell', operator='test operator')
        actions = (ml.machine_dir() / ml.ACTIONS_NAME).read_text()
        assert 'unrelated shell' in actions and 'test operator' in actions
        ml.release(ml.acquire('after-the-operator-action', wait_seconds=0))
    finally:
        os.kill(sleeper, signal.SIGKILL)


def test_fence_refuses_a_group_whose_identity_cannot_be_read(monkeypatch):
    lease = ml.acquire('holder')
    try:
        monkeypatch.setattr(ml, '_identity', lambda pid: None)
        with pytest.raises(ValueError, match='identity'):
            ml.fence(lease.lease_id, os.getpid())
    finally:
        ml.release(lease)


def test_an_unreadable_fence_record_blocks_until_an_operator_clears_it():
    (ml.ensure_machine_dir() / ml.FENCE_NAME).write_text('{not json')
    with pytest.raises(ml.LeaseBusy, match='unreadable'):
        ml.acquire('second-job', wait_seconds=0)
    ml.clear_fence(unreadable=True, reason='corrupt after a disk-full crash', operator='test operator')
    ml.release(ml.acquire('after-the-operator-action', wait_seconds=0))


def test_a_busy_machine_lock_raises_lease_busy():
    holder = subprocess.Popen([sys.executable, '-c', 'import sys,time\nfrom ravel.workflow import machine_lease as m\n'
                               'with m.machine_lock("x.lock"):\n    print("held", flush=True); time.sleep(20)\n'],
                              stdout=subprocess.PIPE, text=True, env=_env(), start_new_session=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        with pytest.raises(ml.LeaseBusy):
            with ml.machine_lock('x.lock', wait_seconds=0.1):
                pass
    finally:
        _stop(holder)
