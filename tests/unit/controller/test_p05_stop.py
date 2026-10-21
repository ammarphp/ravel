"""Real inert descendant cleanup and durable stop/restart boundaries."""
from contextlib import nullcontext
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from test_p05_support import own
from ravel.controller import entry


@pytest.fixture
def controls(tmp_path, monkeypatch):
    from ravel.controller import authority
    from ravel.controller.authority import common
    from ravel.workflow import stage_supervisor as supervisor, execution_backend as backend
    root = (tmp_path / 'run').resolve()
    root.mkdir()
    store = own(monkeypatch, tmp_path / 'store', {root: 'run-inert'})['run-inert']
    monkeypatch.setattr(common, '_OWNERSHIP', None)
    view = {'state': 'running', 'request': None, 'record': None, 'revoked': False}
    observations = []
    checks = []
    monkeypatch.setattr(authority, 'control', lambda store: dict(view))
    def check(store, action='effect'):
        checks.append(action)
        if view['state'] != 'running':
            raise authority.AuthorityRefused('controller stop requested')
        return dict(view)
    monkeypatch.setattr(authority, 'check', check)
    monkeypatch.setattr(authority, 'observe_stop', lambda store, phase, evidence=None:
                        observations.append({'phase': phase, 'evidence': evidence}))
    return root, store, view, observations, checks


def test_real_descendant_stop_reaps_before_stopped(controls, monkeypatch):
    from ravel.workflow import execution, stage_supervisor as supervisor, launch_authorization
    from ravel.workflow import method_selection, review_enforcement, wms_policy
    root, store, control, observations, checks = controls
    # Fake only the adjacent policy interfaces (including the scientific review gate a controller-owned run
    # always applies). Popen, signals, census, waiting, durable attempt state and the supervisor loop are the
    # production implementations.
    monkeypatch.setattr(supervisor, '_authorized_branch', lambda *a: True)
    monkeypatch.setattr(supervisor, '_controller_launch', lambda *a, **k: {'kind': 'inert-broker'})
    monkeypatch.setattr(supervisor, '_stage_binding', lambda *a, **k: None)
    monkeypatch.setattr(supervisor, '_machine_lease', lambda *a, **k: nullcontext())
    monkeypatch.setattr(method_selection, 'require_launch', lambda *a, **k: None)
    monkeypatch.setattr(wms_policy, 'require_dispatch', lambda *a, **k: None)
    monkeypatch.setattr(review_enforcement, 'before_stage', lambda *a, **k: None)
    def launch(run, plan, argv, **kwargs):
        kwargs.pop('context', None)
        kwargs.pop('confinement', None)
        proc = subprocess.Popen(argv, **kwargs)
        proc.ravel_authorization = {'kind': 'inert'}
        return proc
    monkeypatch.setattr(launch_authorization, 'authorized_popen', launch)
    marker, effect = root / 'child.pid', root / 'late-effect'
    program = ('import os,pathlib,time,signal\n'
               'pid=os.fork()\n'
               'if pid==0:\n'
               ' signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
               f' pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\n'
               ' time.sleep(1)\n'
               f' pathlib.Path({str(effect)!r}).write_text("survived")\n'
               ' time.sleep(10)\n'
               'else: time.sleep(20)\n')
    stop_requested_at = []
    def stop():
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        stop_requested_at.append(time.monotonic())
        control.update(state='stop_requested', request='stop', record='control-inert', ancestor='parent-inert')
    thread = threading.Thread(target=stop, daemon=True)
    thread.start()
    code = supervisor.supervise('inert', root, 1, 'logs/inert.log',
            [sys.executable, '-c', program], cwd=str(root), required_plan='smoke',
            kill_secs=2., poll=.02, grace=.15)
    thread.join(timeout=1)
    child = int(marker.read_text())
    assert code == 130, code
    assert stop_requested_at and time.monotonic() - stop_requested_at[0] < 1.5
    assert not effect.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
    record = execution.load_execution(root)['stages']['inert']
    assert record['cleanup']['group_state'] == 'empty'
    assert record['cleanup']['requires_recovery'] is False
    assert child in record['cleanup']['reaped_descendants']
    assert [o['phase'] for o in observations] == ['draining', 'stopped']
    assert observations[-1]['evidence']['verified_gone'] is True
    assert observations[-1]['evidence']['remaining_group_members'] == []
    assert checks


def test_current_ancestor_stop_refuses_dispatch_without_attempt(controls):
    from ravel.workflow import stage_supervisor as supervisor
    root, store, control, observations, checks = controls
    control.update(state='stop_requested', request='stop', record='control-parent', ancestor='parent-inert')
    with pytest.raises(ValueError, match='stop'):
        supervisor.supervise('inert', root, 1, 'logs/inert.log', [sys.executable, '-c', 'pass'], required_plan='smoke')
    assert not (root / 'execution_state.json').exists()
    assert checks and not observations


def test_restart_adopts_existing_identity_without_resubmission_or_budget_reset(tmp_path, monkeypatch):
    from ravel.workflow import execution_backend as backend
    attempt = tmp_path / 'attempt'
    attempt.mkdir()
    plan = {'plan_sha256': 'a' * 64, 'spec': {'stage': 'inert', 'resources': {'wall_seconds': 60}}}
    deadline = time.time_ns() - 1
    handle = {'backend': 'inert', 'tag': 'job-inert', 'plan_sha256': plan['plan_sha256'],
              'attempt_dir': str(attempt), 'remote': {'job_id': 'retained-identity'},
              'state': 'submitted', 'resolution': None, 'wall_deadline_ns': deadline,
              'budget_started_ns': deadline - 60_000_000_000}
    (attempt / 'plan.json').write_text(json.dumps(plan))
    handle['plan_file_sha256'] = backend.file_sha256(attempt / 'plan.json')
    backend.write_handle(handle)
    monkeypatch.setattr(backend, 'submit', lambda *a, **k: pytest.fail('restart resubmitted'))
    monkeypatch.setattr(backend, 'logs', lambda *a, **k: ('', 0))
    monkeypatch.setattr(backend, 'observe', lambda *a, **k: {'state': 'running'})
    settled = []
    monkeypatch.setattr(backend, '_settle', lambda p, h, *a: settled.append(h['remote']))
    box = {'handle': None}
    assert backend._drive(plan, b'', attempt, tmp_path, box, .01, .1, io.StringIO()) == 124
    assert settled == [{'job_id': 'retained-identity'}]
    retained = backend.read_handle(attempt)
    assert retained['wall_deadline_ns'] == deadline
    assert retained['remote'] == handle['remote']


def test_restart_with_ambiguous_dispatch_holds_and_never_resubmits(tmp_path, monkeypatch):
    from ravel.workflow import execution_backend as backend
    attempt = tmp_path / 'attempt'
    attempt.mkdir()
    plan = {'plan_sha256': 'a' * 64, 'spec': {'stage': 'inert', 'resources': {'wall_seconds': 60}}}
    handle = {'backend': 'inert', 'tag': 'job-inert', 'plan_sha256': plan['plan_sha256'],
              'attempt_dir': str(attempt), 'remote': None, 'state': 'dispatch-unknown', 'resolution': None}
    (attempt / 'plan.json').write_text(json.dumps(plan))
    handle['plan_file_sha256'] = backend.file_sha256(attempt / 'plan.json')
    backend.write_handle(handle)
    monkeypatch.setattr(backend, 'submit', lambda *a, **k: pytest.fail('ambiguous restart resubmitted'))
    with pytest.raises(ValueError, match='held|identity|budget'):
        backend._drive(plan, b'', attempt, tmp_path, {'handle': None}, .01, .1, io.StringIO())
    assert backend.read_handle(attempt)['state'] == 'dispatch-unknown'


def test_scheduler_poll_obeys_current_stop_and_cancels_identity(controls, tmp_path, monkeypatch):
    from ravel.workflow import execution_backend as backend
    root, store, control, observations, checks = controls
    attempt = tmp_path / 'attempt'
    plan = {'spec': {'stage': 'inert', 'resources': {'wall_seconds': 60}}}
    handle = {'backend': 'inert', 'tag': 'job-inert', 'remote': {'job_id': 'retained'},
              'budget_started_ns': time.time_ns(), 'wall_deadline_ns': time.time_ns() + 60_000_000_000}
    monkeypatch.setattr(backend, 'submit', lambda *a, **k: handle)
    monkeypatch.setattr(backend, 'logs', lambda *a, **k: ('', 0))
    polls = []
    def observe(*a):
        polls.append(True)
        control.update(state='stop_requested', request='stop', record='control-parent', ancestor='parent-inert')
        return {'state': 'running'} if len(polls) == 1 else {'state': 'cancelled'}
    monkeypatch.setattr(backend, 'observe', observe)
    settled = []
    monkeypatch.setattr(backend, '_settle', lambda p, h, *a: settled.append(h['remote']) or {'state': 'cancelled'})
    assert backend._drive(plan, b'', attempt, root, {'handle': None}, .01, .1, io.StringIO()) == 130
    assert settled == [{'job_id': 'retained'}]
    assert checks


def test_remote_reservation_survives_owner_process_restart(tmp_path, monkeypatch):
    from ravel.workflow import execution_backend as backend
    leases = tmp_path / 'leases'
    leases.mkdir()
    monkeypatch.setattr(backend, 'state_dir', lambda: tmp_path)
    monkeypatch.setattr(backend, 'remote_ceiling', lambda rundir=None: 1)
    # A killed supervisor released its OS lock, but never resolved its remote identity.
    (leases / 'remote-slot-0.json').write_text(json.dumps({'holder': 'previous', 'pid': 99999999,
        'state': 'active', 'attempt_dir': str(tmp_path / 'unresolved-attempt')}))
    with pytest.raises(ValueError, match='ceiling|held|unresolved'):
        with backend.remote_slot('different'):
            pytest.fail('unresolved durable reservation was reset')
    retained = json.loads((leases / 'remote-slot-0.json').read_text())
    assert retained['holder'] == 'previous'


def test_drive_clear_stop_refuses_for_controller_owned_run(controls, monkeypatch, capsys):
    from ravel.workflow import graph_substrate
    from ravel.controller import entry
    root, *_ = controls
    stop = root / graph_substrate.STOP
    stop.parent.mkdir(parents=True)
    stop.write_text('retained stop')
    assert entry.drive_main(['--rundir', str(root), '--clear-stop']) == 1
    assert stop.read_text() == 'retained stop'
    assert 'controller' in capsys.readouterr().err


@pytest.mark.parametrize('alias', ['gate', 'respond'])
def test_legacy_cli_refuses_before_reading_response_body(controls, monkeypatch, capsys, alias):
    from ravel.workflow import gate_wiring, respond_cli
    root, *_ = controls
    monkeypatch.setattr(gate_wiring, '_body', lambda args: pytest.fail('legacy body was read before ownership guard'))
    argv = ['--rundir', str(root), '--text-file', str(root / 'missing'), '--approve', 'inert']
    assert (gate_wiring.main(['respond', *argv]) if alias == 'gate' else respond_cli.main(argv)) == 2
    assert 'controller-owned' in capsys.readouterr().err


def test_legacy_steer_initialization_refuses_at_callable_entry(controls):
    from ravel.workflow import gate_wiring
    root, *_ = controls
    with pytest.raises(ValueError, match='controller-owned'):
        gate_wiring.initialize_steering(root, route='operator')


def test_cleanup_positive_control_reaps_a_real_child():
    from ravel.workflow import stage_supervisor as supervisor
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'], start_new_session=True)
    try:
        result = supervisor._terminate_owned_group(process.pid, .2, process)
        assert result['requires_recovery'] is False and result['group_state'] == 'empty'
        assert process.returncode is not None
        with pytest.raises(ProcessLookupError):
            os.kill(process.pid, 0)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)


def test_live_group_cannot_earn_stopped_from_cleanup_boolean(controls):
    from ravel.workflow import stage_supervisor as supervisor
    root, store, control, observations, checks = controls
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'], start_new_session=True)
    record = {'stage': 'inert', 'controller_stop': {'state': 'stop_requested'},
              'cleanup': {'process_group': process.pid, 'group_state': 'empty',
                          'requires_recovery': False, 'errors': []}}
    try:
        supervisor._controller_stopped(root, record, process)
        assert observations == []
        assert record['cleanup']['requires_recovery'] is True
    finally:
        supervisor._terminate_owned_group(process.pid, .2, process)


def test_actual_owner_exit_keeps_remote_reservation(tmp_path, monkeypatch):
    from ravel.workflow import execution_backend as backend
    program = r'''
import os, pathlib, sys
from ravel.workflow import execution_backend as backend
backend.state_dir = lambda: pathlib.Path(sys.argv[1])
backend.remote_ceiling = lambda root=None: 1
with backend.remote_slot('retained-owner', attempt_dir=pathlib.Path(sys.argv[1])/'attempt'):
 os._exit(0)
'''
    done = subprocess.run([sys.executable, '-c', program, str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    monkeypatch.setattr(backend, 'state_dir', lambda: tmp_path)
    monkeypatch.setattr(backend, 'remote_ceiling', lambda rundir=None: 1)
    with pytest.raises(ValueError, match='ceiling'):
        with backend.remote_slot('different-owner'):
            pytest.fail('a lost OS lock reset the durable reservation')
    with backend.remote_slot('retained-owner', attempt_dir=tmp_path / 'attempt') as slot:
        assert slot == 0
        reservation = json.loads((tmp_path / 'leases' / 'remote-slot-0.json').read_text())
        assert reservation['holder'] == 'retained-owner'


@pytest.mark.parametrize('command', ['approve', 'go', 'delegated-approve', 'delegated-go'])
def test_legacy_approval_callable_entries_refuse(controls, capsys, command):
    from ravel.workflow import workflow_state
    from types import SimpleNamespace
    root, *_ = controls
    if command in ('approve', 'go'):
        call = workflow_state.cmd_approve if command == 'approve' else workflow_state.cmd_go
        assert call(SimpleNamespace(rundir=str(root))) == 1
        assert 'controller-owned' in capsys.readouterr().err
    else:
        with pytest.raises(ValueError, match='controller-owned'):
            if command == 'delegated-approve':
                workflow_state.record_delegated_approval(root, 'smoke')
            else:
                workflow_state.record_delegated_go(root)
    assert not (root / 'inputs').exists()


def test_unknown_resolution_holds_and_explicit_operator_clear_still_resolves():
    from ravel.workflow import execution_backend as backend
    handle = {'state': 'unknown', 'resolution': 'unverified'}
    assert backend.handle_resolved(handle) is False
    handle.update(resolution='operator-cleared', cleanup_required=True)
    assert backend.handle_resolved(handle) is True
