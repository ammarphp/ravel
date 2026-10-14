"""Machine-lease recovery: unknown versus live ties, malformed fence rows, operator
clearing that resolves a backend handle, the read-only preflight, and crash injection
at every step of a native dispatch (each with a competing acquire and eventual recovery)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from ravel.workflow import execution_backend as eb, machine_lease as ml


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.delenv(ml.ENV, raising=False)
    monkeypatch.delenv(ml.JOB_ENV, raising=False)
    eb._INSTANCES.clear()


def _fence(rows):
    ml._write_fence(rows)


def _row(**extra):
    return {'lease_id': 'a' * 32, 'token': 'b' * 32, 'parent_token': None, 'hold': None, 'starter': None,
            'pgid': None, 'pid': None, 'identity': None, 'label': 'synthetic job', **extra}


# ---------------------------------------------------------------- unknown is not live
def test_an_unavailable_token_census_blocks_but_the_operator_can_clear_it(tmp_path, monkeypatch):
    hold = tmp_path / 'job.log'
    hold.write_text('')  # exists, unlocked: nothing holds it
    _fence([_row(hold=str(hold))])
    monkeypatch.setattr(ml, 'token_census', lambda: None)
    ties = ml.job_processes(ml.live_fences()[0])
    assert 'token' not in ties and ties.get('token_unknown')
    with pytest.raises(ml.LeaseBusy):
        ml.acquire('second-job', wait_seconds=0)
    result = ml.clear_fence(token='b' * 32, reason='census unavailable; hold unlocked; group empty', operator='op')
    assert result['observed'] == {'token_unknown': 'census unavailable'}
    ml.release(ml.acquire('after-clearing', wait_seconds=0))


def test_a_token_a_live_process_carries_is_still_proven_live(tmp_path):
    token = 'c' * 32
    proc = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'],
                            env={**os.environ, ml.JOB_ENV: token})
    try:
        deadline = time.monotonic() + 10
        while proc.pid not in (ml.token_census() or {}).get(token, []) and time.monotonic() < deadline:
            time.sleep(0.05)
        _fence([_row(token=token)])
        with pytest.raises(ValueError, match='proven live'):
            ml.clear_fence(token=token, reason='r', operator='op')
    finally:
        proc.kill()
        proc.wait()


# ---------------------------------------------------------------- malformed rows
def test_malformed_fence_rows_block_until_an_operator_clears_them(tmp_path):
    path = ml.ensure_machine_dir() / ml.FENCE_NAME
    path.write_text(json.dumps({'groups': ['corrupt-entry', {}]}))
    live = ml.live_fences(prune=True)
    assert len(live) == 2 and all(row.get('malformed') for row in live)
    assert json.loads(path.read_text())['groups'] == ['corrupt-entry', {}]  # never pruned away
    with pytest.raises(ml.LeaseBusy, match='malformed'):
        ml.acquire('second-job', wait_seconds=0)
    with pytest.raises(ml.LeaseBusy, match='malformed'):
        ml._admit('a' * 32, live, None)  # a reservation under a held lease is refused the same way
    cleared = ml.clear_fence(malformed=True, reason='hand-edited record', operator='op')
    assert cleared['cleared_malformed'] == ['corrupt-entry', {}]
    ml.release(ml.acquire('after-clearing', wait_seconds=0))


# ---------------------------------------------------------------- clear-fence resolves the handle
def test_clearing_a_fence_entry_resolves_its_backend_handle(tmp_path):
    attempt = tmp_path / 'attempt'
    attempt.mkdir()
    eb.write_handle({'attempt_dir': str(attempt), 'tag': 't', 'state': 'dispatching', 'remote': None,
                     'resolution': None, 'backend': 'native'})
    _fence([_row(handle_dir=str(attempt), pgid=999999, identity='synthetic')])
    result = ml.clear_fence(token='b' * 32, reason='launcher never recorded itself', operator='op')
    handle = eb.read_handle(attempt)
    assert result['resolved_handle'] == str(attempt)
    assert handle['resolution'] == 'operator-cleared' and eb.handle_resolved(handle)
    assert handle['operator_action']['operator'] == 'op'
    actions = (ml.machine_dir() / ml.ACTIONS_NAME).read_text().splitlines()
    assert json.loads(actions[-1])['resolved_handle'] == str(attempt)


def test_clear_fence_journals_its_intent_and_keeps_the_fence_when_the_handle_write_fails(tmp_path, monkeypatch):
    attempt = tmp_path / 'attempt'
    attempt.mkdir()
    eb.write_handle({'attempt_dir': str(attempt), 'tag': 't', 'state': 'dispatching', 'remote': None,
                     'resolution': None, 'backend': 'native'})
    _fence([_row(handle_dir=str(attempt), pgid=999999, identity='synthetic')])
    real = eb.write_handle

    def failing(handle):
        raise OSError('injected handle-write failure')
    monkeypatch.setattr(eb, 'write_handle', failing)
    with pytest.raises(ValueError, match='injected handle-write failure'):
        ml.clear_fence(token='b' * 32, reason='launcher never recorded itself', operator='op')
    assert [row.get('token') for row in ml._rows(ml._fence_document())] == ['b' * 32]  # the fence stays
    assert eb.read_handle(attempt)['resolution'] is None
    phases = [json.loads(line).get('phase') for line in (ml.machine_dir() / ml.ACTIONS_NAME).read_text().splitlines()]
    assert phases == ['intent', 'partial']
    # The same command completes it once the handle can be written.
    monkeypatch.setattr(eb, 'write_handle', real)
    result = ml.clear_fence(token='b' * 32, reason='launcher never recorded itself', operator='op')
    assert result['resolved_handle'] == str(attempt) and eb.read_handle(attempt)['resolution'] == 'operator-cleared'
    assert ml._rows(ml._fence_document()) == []
    actions = [json.loads(line) for line in (ml.machine_dir() / ml.ACTIONS_NAME).read_text().splitlines()]
    assert [a.get('phase') for a in actions] == ['intent', 'partial', 'intent', 'completed']
    assert actions[-1]['resolved_handle'] == str(attempt)


def test_preflight_flags_malformed_fence_rows_and_exits_non_zero():
    path = ml.ensure_machine_dir() / ml.FENCE_NAME
    path.write_text(json.dumps({'groups': ['corrupt-entry', {}]}))
    report = ml.preflight()
    assert report['malformed_rows'] == 2
    assert ml.main(['preflight']) == 1


# ---------------------------------------------------------------- preflight
def test_preflight_lists_live_processes_of_recorded_jobs_without_signalling(tmp_path):
    token = 'd' * 32
    proc = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'], start_new_session=True,
                            env={**os.environ, ml.JOB_ENV: token})
    try:
        deadline = time.monotonic() + 10
        while proc.pid not in (ml.token_census() or {}).get(token, []) and time.monotonic() < deadline:
            time.sleep(0.05)
        # The entry was cleared by an operator; its process still carries the token.
        ml._record_action({'action': 'clear-fence-entry', 'entry': _row(token=token)})
        report = ml.preflight()
        assert [row['pid'] for row in report['processes']] == [proc.pid]
        assert proc.poll() is None  # read-only: nothing was signalled
        assert ml.main(['preflight']) == 1
    finally:
        proc.kill()
        proc.wait()
    assert ml.preflight()['processes'] == [] and ml.main(['preflight']) == 0


def test_ravel_lease_is_a_focused_command():
    from ravel import cli
    assert cli.FOCUSED_COMMANDS['lease'][0] == 'workflow.machine_lease'


# ---------------------------------------------------------------- crash injection in a native dispatch
PAYLOAD = ('import json,os,time\n'
           'time.sleep(float(os.environ.get("RAVEL_TEST_PAYLOAD_SECONDS","1.5")))\n'
           'json.dump({"n":1},open(os.path.join(os.environ["RAVEL_OUTPUT_DIR"],"n.json"),"w"))\n')

# The dispatcher dies (os._exit) at one step of eb.submit; everything before that step is durable.
CRASH = r'''
import os, sys
from ravel.workflow import execution_backend as eb, machine_lease as ml
from ravel.workflow.backends import native
point, plan_path, attempt = sys.argv[1:4]
die = lambda *a, **k: os._exit(9)
def after(fn):
    def wrapped(*a, **k):
        result = fn(*a, **k)
        if result is not None:
            os._exit(9)
        return result
    return wrapped
if point == 'reservation':
    ml.reserve = after(ml.reserve)
elif point == 'dispatch-marker':
    real_write = native.atomic_json
    def marker(path, value):
        real_write(path, value)
        if path.name == native.DISPATCH_MARKER:
            os._exit(9)
    native.atomic_json = marker
elif point == 'popen':
    native.NativeBackend._await_launcher = die
elif point == 'launcher-identity':
    native.NativeBackend.find = after(native.NativeBackend.find)
elif point == 'handle-publication':
    real = eb.write_handle
    eb.write_handle = lambda h: die() if h.get('state') == 'submitted' else real(h)
plan = eb.load_plan(plan_path, verify_inputs=False)
with ml.held('crashing dispatcher'):
    eb.submit(plan, attempt)
'''


def _plan(tmp_path):
    spec = {'schema_version': 1, 'backend': 'native', 'stage': 'crash', 'argv': [sys.executable, '-c', PAYLOAD],
            'outputs': [{'name': 'n.json', 'destination': 'outputs/n.json'}],
            'resources': {'cpus': 1, 'memory_mib': 128, 'wall_seconds': 60}}
    return eb.write_plan(eb.prepare(spec), tmp_path / 'plan.json')


def _crash(tmp_path, point):
    plan = _plan(tmp_path)
    attempt = tmp_path / 'attempt'
    proc = subprocess.run([sys.executable, '-c', CRASH, point, str(plan), str(attempt)], env=dict(os.environ),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 9, proc.stderr
    return eb.load_plan(plan, verify_inputs=False), attempt


def _acquire_eventually(seconds=30.0):
    deadline = time.monotonic() + seconds
    while True:
        try:
            return ml.acquire('competing job', wait_seconds=0)
        except ml.LeaseBusy:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


@pytest.mark.parametrize('point', ['reservation', 'dispatch-marker'])
def test_a_dispatcher_killed_before_the_launcher_exists_blocks_nothing_and_resolves(tmp_path, point):
    plan, attempt = _crash(tmp_path, point)
    # Nothing started: a competing job acquires at once.
    ml.release(ml.acquire('competing job', wait_seconds=0))
    result = eb.recover(plan, eb.read_handle(attempt))
    assert result['handle']['resolution'] in ('never-dispatched', 'never-started')
    assert eb.handle_resolved(eb.read_handle(attempt))
    assert ml.live_fences() == []


@pytest.mark.parametrize('point', ['popen', 'launcher-identity', 'handle-publication'])
def test_a_dispatcher_killed_after_the_launch_keeps_the_machine_and_is_adopted(tmp_path, point):
    plan, attempt = _crash(tmp_path, point)
    handle = eb.read_handle(attempt)
    assert handle['remote'] is None and not eb.handle_resolved(handle)
    # The launcher fences itself and runs the payload although its dispatcher died.
    deadline = time.monotonic() + 10
    while not (attempt / 'job/launcher.json').exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    with pytest.raises(ml.LeaseBusy):
        ml.acquire('competing job', wait_seconds=0)
    ml.release(_acquire_eventually())
    result = eb.recover(plan, eb.read_handle(attempt))
    assert result['handle']['remote'] is not None
    assert result['observation']['state'] == 'succeeded'
    assert eb.handle_resolved(eb.read_handle(attempt))


def test_a_launcher_killed_between_its_fence_and_its_identity_is_found_through_the_fence(tmp_path):
    plan = eb.load_plan(_plan(tmp_path), verify_inputs=False)
    attempt = tmp_path / 'attempt'
    job = attempt / 'job'
    (job / 'output').mkdir(parents=True)
    (job / 'job.log').write_text('')
    token = 'e' * 32
    dead = subprocess.Popen([sys.executable, '-c', 'pass'], start_new_session=True)
    identity = __import__('ravel.workflow.execution', fromlist=['x']).process_identity(dead.pid)
    dead.wait()
    eb.write_handle({'schema_version': 1, 'kind': 'ravel-backend-handle', 'backend': 'native', 'attempt_dir': str(attempt),
                     'job_dir': str(job), 'tag': 't', 'state': 'dispatching', 'remote': None, 'resolution': None,
                     'plan_sha256': plan['plan_sha256'], 'cancel_requested': False})
    (job / 'dispatch.json').write_text(json.dumps({'tag': 't', 'job_token': token}))
    _fence([_row(token=token, hold=str(job / 'job.log'), pgid=dead.pid, pid=dead.pid, identity=identity or 'gone',
                 handle_dir=str(attempt))])
    handle = eb.read_handle(attempt)
    result = eb.recover(plan, dict(handle))
    assert result['handle']['remote']['recorded_by'] == 'fence'
    assert result['observation']['state'] == 'failed'  # the payload never started
    assert eb.handle_resolved(eb.read_handle(attempt))
    ml.release(ml.acquire('competing job', wait_seconds=0))  # its group is empty: nothing blocks
    # Once the dead entry is pruned, the same launch resolves as never started.
    eb.write_handle(handle)
    assert eb.recover(plan, handle)['handle']['resolution'] == 'never-started'


def test_an_unidentified_launch_whose_hold_is_held_stays_unknown_until_the_operator_clears_it(tmp_path):
    plan = eb.load_plan(_plan(tmp_path), verify_inputs=False)
    attempt = tmp_path / 'attempt'
    job = attempt / 'job'
    job.mkdir(parents=True)
    token = 'f' * 32
    eb.write_handle({'schema_version': 1, 'kind': 'ravel-backend-handle', 'backend': 'native', 'attempt_dir': str(attempt),
                     'job_dir': str(job), 'tag': 't', 'state': 'dispatching', 'remote': None, 'resolution': None,
                     'plan_sha256': plan['plan_sha256'], 'cancel_requested': False})
    (job / 'dispatch.json').write_text(json.dumps({'tag': 't', 'job_token': token}))
    _fence([_row(token=token, hold=str(job / 'job.log'), handle_dir=str(attempt))])
    with (job / 'job.log').open('ab') as log:
        ml.take_hold(log)  # a process still holds the launch's log
        result = eb.recover(plan, eb.read_handle(attempt))
        assert result['observation']['state'] == 'unknown' and 'clear-fence' in result['observation']['detail']
        assert not eb.handle_resolved(eb.read_handle(attempt))
        with pytest.raises(ValueError, match='proven live'):
            ml.clear_fence(token=token, reason='r', operator='op')
    ml.clear_fence(token=token, reason='launch process stopped by the operator', operator='op')
    assert eb.read_handle(attempt)['resolution'] == 'operator-cleared'
    ml.release(ml.acquire('competing job', wait_seconds=0))


def test_a_submission_error_after_the_launch_records_the_job_identity(tmp_path):
    from ravel.workflow.backends import native
    plan = eb.load_plan(_plan(tmp_path), verify_inputs=False)
    real = native.NativeBackend.submit

    def failing(self, plan, handle):
        real(self, plan, handle)
        raise RuntimeError('store failed after the launch')
    backend = native.NativeBackend()
    backend.submit = failing.__get__(backend)
    with ml.held('dispatcher'):
        with pytest.raises(RuntimeError):
            eb.submit(plan, tmp_path / 'attempt', backend=backend)
        handle = eb.read_handle(tmp_path / 'attempt')
        assert handle['remote'] is not None and handle['adopted_after_dispatch_error'] is True
        observation = eb.cancel(plan, handle, wait_seconds=10.0)
    assert observation['state'] in eb.TERMINAL
