"""A supervised stage that declares an execution backend."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

from ravel.workflow import execution, execution_backend as eb, machine_lease as ml
from ravel.workflow import stage_supervisor
from test_checkin2_gate import _run, _ws


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2026-10-08T00:00:00Z')
    monkeypatch.delenv(ml.ENV, raising=False)
    eb._INSTANCES.clear()


RUN = '2026-10-07_TEST_checkin2'


def approved_root(tmp_path):
    root = tmp_path / RUN
    if not (root / 'inputs/checkin1_approval.json').is_file():
        _run(tmp_path, plan='smoke', checkin2=False)
    (root / 'logs').mkdir(parents=True, exist_ok=True)
    return root


def approve(root):
    result = _ws('approve', '--rundir', root, '--quote', 'Yes, run the plan', '--plan', 'smoke')
    assert result.returncode == 0, result.stderr


def make_plan(tmp_path, argv, *, name='plan.json', wall=60, outputs=None, approved=True):
    """A backend plan pinned under the run's inputs/backend-plans, then approved at CHECK-IN 1."""
    data = tmp_path / 'input.txt'
    if not data.exists():
        data.write_text('a\nb\nc\n')
    spec = {'schema_version': 1, 'backend': 'native', 'stage': 'count',
            'argv': argv, 'inputs': [{'path': str(data)}],
            'outputs': outputs if outputs is not None else [{'name': 'n.json', 'destination': 'outputs/n.json'}],
            'resources': {'cpus': 1, 'memory_mib': 128, 'wall_seconds': wall}}
    root = approved_root(tmp_path)
    (root / 'inputs/backend-plans').mkdir(exist_ok=True)
    path = eb.write_plan(eb.prepare(spec), root / 'inputs/backend-plans' / name)
    if approved:
        approve(root)
    return path


COUNT = [sys.executable, '-c', 'import json,os;json.dump({"n":3},open(os.path.join(os.environ["RAVEL_OUTPUT_DIR"],"n.json"),"w"))']


def rundir(tmp_path):
    """An approved run (CHECK-IN 1 at the smoke rung): backend stages launch only with an approval."""
    return approved_root(tmp_path)


def supervise(stage, root, events, *args, **kwargs):
    kwargs.setdefault('required_plan', 'smoke')
    return stage_supervisor.supervise(stage, root, events or 10, *args, **kwargs)


def test_backend_stage_runs_through_the_supervisor(tmp_path):
    root = rundir(tmp_path)
    plan = make_plan(tmp_path, COUNT)
    code = supervise('count', root, 0, 'logs/count.log', None, kill_secs=60.0,
                                      poll=0.1, grace=3.0, backend_plan=plan)
    assert code == 0, (root / 'logs/count.log').read_text()
    assert json.loads((root / 'outputs/n.json').read_text()) == {'n': 3}
    record = execution.load_execution(root)['stages']['count']
    assert record['status'] == 'succeeded'
    assert str(plan.resolve()) in record['inputs']
    assert record['outputs'] == ['outputs/n.json']
    assert record['command'][:4] == [sys.executable, '-m', 'ravel.workflow.execution_backend', 'worker']
    handles = eb.stage_handles(root, 'count')
    assert len(handles) == 1 and json.loads(handles[0].read_text())['state'] == 'fetched'
    assert (handles[0].parent / 'fetch-receipt.json').is_file()


def test_changed_plan_invalidates_reuse(tmp_path):
    root = rundir(tmp_path)
    plan = make_plan(tmp_path, COUNT)
    assert supervise('count', root, 0, 'logs/count.log', None, kill_secs=60.0, poll=0.1,
                                      grace=3.0, backend_plan=plan) == 0
    assert supervise('count', root, 0, 'logs/count.log', None, kill_secs=60.0, poll=0.1,
                                      grace=3.0, backend_plan=plan, resume=True) == 0
    first = execution.load_execution(root)['stages']['count']['fingerprint']
    other = make_plan(tmp_path, COUNT, name='plan2.json', wall=120)
    specification = execution.plan_stage(root, 'count', eb.worker_command(root, 'count', other, poll=0.1),
                                         [str(other.resolve())], ['outputs/n.json'], [], os.getcwd())
    assert specification['fingerprint'] != first
    assert not execution.reusable(root, 'count', specification)


def test_backend_plan_stage_must_match(tmp_path):
    root = rundir(tmp_path)
    plan = make_plan(tmp_path, COUNT)
    with pytest.raises(ValueError, match='stage'):
        supervise('other', root, 0, 'logs/other.log', None, kill_secs=60.0, backend_plan=plan)
    with pytest.raises(ValueError, match='command'):
        supervise('count', root, 0, 'logs/count.log', ['echo', 'hi'], kill_secs=60.0, backend_plan=plan)


def test_supervisor_kill_cancels_the_backend_job(tmp_path):
    root = rundir(tmp_path)
    marker = tmp_path / 'pid.txt'
    argv = [sys.executable, '-c', f'import os,time;open({str(marker)!r},"w").write(str(os.getpid()));time.sleep(60)']
    plan = make_plan(tmp_path, argv)
    started = time.monotonic()
    # The wall ceiling leaves the worker, the launcher and the payload time to start on a slow host.
    code = supervise('count', root, 0, 'logs/count.log', None, kill_secs=10.0,
                                      poll=0.1, grace=6.0, backend_plan=plan)
    assert code == 124 and time.monotonic() - started < 30
    pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    handle = json.loads(eb.stage_handles(root, 'count')[0].read_text())
    assert handle['cancel_requested'] is True and handle['resolution'] == 'cancelled'


def test_second_local_job_is_refused_after_its_lease_wait(tmp_path):
    from ravel.workflow import machine_lease
    root = rundir(tmp_path)
    plan = make_plan(tmp_path, COUNT)
    with eb.machine_lease('another stage'):
        with pytest.raises(machine_lease.LeaseBusy, match='native scientific job'):
            supervise('count', root, 0, 'logs/count.log', None, kill_secs=60.0,
                                       poll=0.1, grace=3.0, backend_plan=plan, lease_wait=0.3)
    assert execution.load_execution(root)['stages'] == {}


HOLD = ('import sys,time\n'
        'from ravel.workflow import machine_lease as m\n'
        'with m.held("earlier native job"):\n'
        '    print("held", flush=True)\n'
        '    time.sleep(float(sys.argv[1]))\n')


def test_second_native_launch_waits_on_the_lease(tmp_path, capfd):
    import subprocess
    root = rundir(tmp_path)
    plan = make_plan(tmp_path, COUNT)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    holder = subprocess.Popen([sys.executable, '-c', HOLD, '5'], stdout=subprocess.PIPE, text=True, env=env,
                              start_new_session=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        started = time.monotonic()
        code = supervise('count', root, 0, 'logs/count.log', None, kill_secs=60.0,
                                          poll=0.1, grace=3.0, backend_plan=plan, lease_wait=60.0)
        assert code == 0 and time.monotonic() - started >= 1.0
        assert holder.wait(timeout=30) == 0
        assert 'waiting for the machine lease' in capfd.readouterr().err
        assert json.loads((root / 'outputs/n.json').read_text()) == {'n': 3}
    finally:
        if holder.poll() is None:
            os.killpg(holder.pid, 9)
            holder.wait()


def test_unresolved_earlier_handle_blocks_a_new_launch(tmp_path):
    root = rundir(tmp_path)
    plan = make_plan(tmp_path, COUNT)
    earlier = root / 'logs/execution/count/0123/backend'
    earlier.mkdir(parents=True)
    (earlier / eb.HANDLE_NAME).write_text(json.dumps({'tag': 'ravel-x', 'state': 'dispatch-unknown', 'resolution': None}))
    code = supervise('count', root, 0, 'logs/count.log', None, kill_secs=60.0,
                                      poll=0.1, grace=3.0, backend_plan=plan)
    assert code == 2
    assert 'unresolved' in (root / 'logs/count.log').read_text()


def test_cli_accepts_backend_plan(tmp_path):
    root = rundir(tmp_path)
    plan = make_plan(tmp_path, COUNT)
    code = stage_supervisor.main(['--stage', 'count', '--rundir', str(root), '--log', 'logs/count.log',
                                  '--kill-secs', '60', '--events', '10', '--required-plan', 'smoke',
                                  '--backend-plan', str(plan)])
    assert code == 0
    assert (root / 'outputs/n.json').is_file()


# ---------------------------------------------------------------- approval, quiescence and failure paths
def _dead(pid):
    # A zombie (exited, not yet reaped by this test process) counts as dead.
    return execution.process_identity(pid) is None or not execution.process_group_members(os.getpgid(pid)) \
        or pid not in execution.process_group_members(os.getpgid(pid))


def _wait_dead(pid, seconds=10.0):
    deadline = time.monotonic() + seconds
    while not _dead(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return _dead(pid)


def test_a_backend_plan_does_not_launch_in_an_unapproved_directory(tmp_path, capsys):
    bare = tmp_path / 'bare'
    (bare / 'logs').mkdir(parents=True)
    plan = make_plan(tmp_path, COUNT)
    with pytest.raises(ValueError, match='unchecked scientific dispatch'):
        stage_supervisor.supervise('count', bare, 0, 'logs/count.log', None, kill_secs=60.0, backend_plan=plan)
    code = stage_supervisor.main(['--stage', 'count', '--rundir', str(bare), '--log', 'logs/count.log',
                                  '--kill-secs', '60', '--backend-plan', str(plan)])
    assert code != 0 and 'unchecked scientific dispatch' in capsys.readouterr().err
    assert eb.stage_handles(bare) == [] and not (bare / 'logs/execution/count').exists()


def test_a_payload_that_leaves_a_live_descendant_does_not_succeed(tmp_path):
    root = rundir(tmp_path)
    marker = tmp_path / 'bg.txt'
    argv = [sys.executable, '-c',
            'import json,os,subprocess\n'
            'json.dump({"n":3},open(os.path.join(os.environ["RAVEL_OUTPUT_DIR"],"n.json"),"w"))\n'
            f'p=subprocess.Popen(["/bin/sleep","25"]);open({str(marker)!r},"w").write(str(p.pid))\n']
    plan = make_plan(tmp_path, argv)
    code = supervise('count', root, 0, 'logs/count.log', None, kill_secs=60.0, poll=0.1, grace=3.0, backend_plan=plan)
    background = int(marker.read_text())
    try:
        assert code != 0, (root / 'logs/count.log').read_text()
        assert 'process group still has live members' in (root / 'logs/count.log').read_text()
        assert _wait_dead(background) and not (root / 'outputs/n.json').exists()
        assert ml.live_fences() == []
    finally:
        if not _dead(background):
            os.kill(background, 9)


def test_a_payload_that_ignores_sigterm_is_killed_before_the_supervisor_returns(tmp_path):
    root = rundir(tmp_path)
    marker = tmp_path / 'pid.txt'
    argv = [sys.executable, '-c', 'import os,signal,time\n'
            'signal.signal(signal.SIGTERM, lambda *a: None)\n'
            f'open({str(marker)!r},"w").write(str(os.getpid()))\n'
            'time.sleep(4); time.sleep(60)\n']
    plan = make_plan(tmp_path, argv)
    # The science placement grace (2 s) and the placement worker cancel wait (1 s). The wall ceiling
    # leaves the worker, the launcher and the payload time to start on a slow host; the payload
    # outlasts it in any case.
    code = supervise('count', root, 0, 'logs/count.log', None, kill_secs=15.0, poll=0.1, grace=2.0,
                     backend_plan=plan)
    pid = int(marker.read_text())
    try:
        assert code == 124 and _dead(pid)
        assert ml.live_fences() == [] and not (ml.holder() or {}).get('alive')
    finally:
        if not _dead(pid):
            os.kill(pid, 9)


def _attempt(root, plan):
    spec = execution.plan_stage(root, 'count', eb.worker_command(root, 'count', plan, poll=0.1),
                                [str(plan.resolve())], ['outputs/n.json'], [], os.getcwd())
    return execution.begin_attempt(root, 'count', spec, 'logs/count.log')


SLEEPER = [sys.executable, '-c', 'import os,time;time.sleep(30)']


def test_an_error_after_submit_cancels_the_job_before_the_lease_ends(tmp_path, monkeypatch, capsys):
    root = rundir(tmp_path)
    plan = make_plan(tmp_path, SLEEPER)
    _attempt(root, plan)
    def failing_logs(plan, handle, *args, **kwargs):
        # The error strikes a running payload: the launcher records it just after its own identity.
        deadline = time.monotonic() + 30
        while not (Path(handle['job_dir']) / 'payload.json').exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        raise RuntimeError('log read failed')
    monkeypatch.setattr(eb, 'logs', failing_logs)
    assert eb.worker(root, 'count', plan, poll=0.1, register=False, cancel_wait=3.0) == 2
    handle_path = eb.stage_handles(root, 'count')[0]
    handle = json.loads(handle_path.read_text())
    payload = json.loads((Path(handle['job_dir']) / 'payload.json').read_text())['pid']
    events = [json.loads(line)['event'] for line in (handle_path.parent / eb.OBSERVATIONS_NAME).read_text().splitlines()]
    assert handle['cancel_requested'] is True and 'cancel' in events and _dead(payload)


def test_a_job_that_does_not_stop_keeps_the_machine(tmp_path, monkeypatch):
    from ravel.workflow.backends import native
    root = rundir(tmp_path)
    plan = make_plan(tmp_path, SLEEPER, wall=1)
    _attempt(root, plan)
    monkeypatch.setattr(native.NativeBackend, 'cancel', lambda self, plan, handle, grace=5.0: {'signalled': False})
    assert eb.worker(root, 'count', plan, poll=0.1, register=False, cancel_wait=0.5) == 124
    handle = json.loads(eb.stage_handles(root, 'count')[0].read_text())
    launcher = handle['remote']['pgid']
    try:
        with pytest.raises(ml.LeaseBusy):
            ml.acquire('next job', wait_seconds=0)
    finally:
        os.killpg(launcher, 9)
    deadline = time.monotonic() + 10
    while execution.process_group_members(launcher) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not execution.process_group_members(launcher)


def test_a_dispatch_without_a_recorded_identity_stays_unresolved(tmp_path):
    attempt = tmp_path / 'attempt'
    plan = eb.load_plan(make_plan(tmp_path, COUNT))
    (attempt / 'job').mkdir(parents=True)
    handle = {'schema_version': 1, 'kind': 'ravel-backend-handle', 'backend': 'native',
              'plan_sha256': plan['plan_sha256'], 'tag': 'ravel-x', 'attempt_dir': str(attempt),
              'job_dir': str(attempt / 'job'), 'state': 'dispatch-unknown', 'remote': None,
              'cancel_requested': False, 'resolution': None}
    eb.write_handle(handle)
    (attempt / 'job/dispatch.json').write_text('{}')
    result = eb.recover(plan, handle)
    assert result['handle']['resolution'] is None and result['observation']['state'] == 'unknown'
    assert not eb.handle_resolved(eb.read_handle(attempt))
    (attempt / 'job/dispatch.json').unlink()
    assert eb.recover(plan, eb.read_handle(attempt))['handle']['resolution'] == 'never-dispatched'


def test_cancel_never_signals_a_reused_process_group(tmp_path):
    import subprocess
    from ravel.workflow.backends import native
    other = subprocess.Popen(['/bin/sleep', '30'], start_new_session=True)
    try:
        handle = {'remote': {'pid': other.pid, 'pgid': other.pid, 'identity': 'Thu Jan  1 00:00:00 1970'},
                  'job_dir': str(tmp_path)}
        result = native.NativeBackend().cancel({}, handle, grace=0.2)
        time.sleep(0.3)
        assert result['signalled'] is False and 'unresolved' in result and other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_a_plan_that_claims_a_different_locality_is_refused(tmp_path):
    plan = eb.load_plan(make_plan(tmp_path, COUNT))
    plan['backend']['local'] = False
    plan['plan_sha256'] = eb.digest({k: v for k, v in plan.items() if k != 'plan_sha256'})
    with pytest.raises(ValueError, match='adapter'):
        eb.check_plan(plan)


def test_the_pinned_executable_is_verified_before_dispatch(tmp_path, monkeypatch):
    tools = tmp_path / 'tools'
    shadow = tmp_path / 'shadow'
    tools.mkdir()
    shadow.mkdir()
    tool = tools / 'ravel-test-tool'
    tool.write_text('#!/bin/sh\nexit 0\n')
    tool.chmod(0o755)
    monkeypatch.setenv('PATH', f"{tools}{os.pathsep}{os.environ['PATH']}")
    path = make_plan(tmp_path, ['ravel-test-tool'])
    eb.load_plan(path)
    fake = shadow / 'ravel-test-tool'
    fake.write_text('#!/bin/sh\nexit 0\n')
    fake.chmod(0o755)
    monkeypatch.setenv('PATH', f"{shadow}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(ValueError, match='does not resolve to the pinned'):
        eb.load_plan(path)
    monkeypatch.setenv('PATH', os.environ['PATH'].split(os.pathsep, 1)[1])
    tool.write_text('#!/bin/sh\nexit 1\n')
    with pytest.raises(ValueError, match='changed since the plan was prepared'):
        eb.load_plan(path)
    with ml.held('test'):
        with pytest.raises(ValueError, match='changed since the plan was prepared'):
            eb.submit(eb.load_plan(path, verify_inputs=False), tmp_path / 'attempt')
    assert not (tmp_path / 'attempt/job/launcher.json').exists()


def test_a_native_job_needs_the_machine_lease(tmp_path):
    plan = eb.load_plan(make_plan(tmp_path, COUNT))
    with pytest.raises(ValueError, match='machine lease'):
        eb.submit(plan, tmp_path / 'attempt')
    # Refused before anything is written: no handle, no job directory.
    assert not (tmp_path / 'attempt').exists()


def test_a_backend_plan_pinned_after_approval_does_not_launch(tmp_path):
    root = rundir(tmp_path)
    plan = make_plan(tmp_path, COUNT, approved=False)
    code = supervise('count', root, 0, 'logs/count.log', None, kill_secs=60.0, poll=0.1, grace=3.0, backend_plan=plan)
    assert code != 0 and eb.stage_handles(root, 'count') == []
    elsewhere = eb.write_plan(eb.load_plan(plan), tmp_path / 'outside.json')
    approve(root)
    with pytest.raises(ValueError, match='not an approved input'):
        supervise('count', root, 0, 'logs/count.log', None, kill_secs=60.0, backend_plan=elsewhere)


# ---------------------------------------------------------------- detached descendants, start handshake, approval
def _detached_sleep(marker, how):
    """Payload code that leaves a /bin/sleep outside its process group, then exits 0."""
    if how == 'new-session':
        start = 'p=subprocess.Popen(["/bin/sleep","20"],start_new_session=True);pid=p.pid\n'
    else:  # double fork into a new session: the sleep is reparented away from the job
        start = ('r,w=os.pipe()\n'
                 'if os.fork()==0:\n'
                 '    os.setsid()\n'
                 '    child=os.fork()\n'
                 '    if child==0:\n'
                 '        os.execv("/bin/sleep",["/bin/sleep","20"])\n'
                 '    os.write(w,str(child).encode());os._exit(0)\n'
                 'pid=int(os.read(r,32));os.wait()\n')
    return ('import json,os,subprocess\n'
            'out=os.environ.get("RAVEL_OUTPUT_DIR")\n'
            'out and json.dump({"n":3},open(os.path.join(out,"n.json"),"w"))\n'
            + start + f'open({str(marker)!r},"w").write(str(pid))\n')


def _kill_and_wait(pid):
    if not _dead(pid):
        os.kill(pid, 9)
    assert _wait_dead(pid)


@pytest.mark.parametrize('how', ['new-session', 'double-fork'])
def test_a_backend_payload_descendant_outside_its_group_keeps_the_job_and_the_machine(tmp_path, how):
    root = rundir(tmp_path)
    marker = tmp_path / 'detached.txt'
    plan = make_plan(tmp_path, [sys.executable, '-c', _detached_sleep(marker, how)])
    code = supervise('count', root, 0, 'logs/count.log', None, kill_secs=30.0, poll=0.1, grace=2.0, backend_plan=plan)
    detached = int(marker.read_text())
    try:
        assert not _dead(detached)
        assert code != 0, (root / 'logs/count.log').read_text()
        handle = json.loads(eb.stage_handles(root, 'count')[0].read_text())
        observed = eb.get('native').observe(eb.load_plan(Path(handle['attempt_dir']) / 'plan.json', verify_inputs=False),
                                             handle)
        assert observed['state'] != 'succeeded'
        with pytest.raises(ml.LeaseBusy):
            ml.acquire('second-job', wait_seconds=0)
    finally:
        _kill_and_wait(detached)
    assert ml.live_fences(prune=True) == []
    ml.release(ml.acquire('after-the-descendant', wait_seconds=0))


@pytest.mark.parametrize('how', ['new-session', 'double-fork'])
def test_a_supervised_stage_descendant_outside_its_group_keeps_the_machine(tmp_path, how):
    root = rundir(tmp_path)
    marker = tmp_path / 'detached.txt'
    code = supervise('detach', root, 10, 'logs/detach.log', [sys.executable, '-c', _detached_sleep(marker, how)],
                     kill_secs=30.0, poll=0.1, grace=2.0)
    detached = int(marker.read_text())
    try:
        assert code != 0, (root / 'logs/detach.log').read_text()
        with pytest.raises(ml.LeaseBusy):
            ml.acquire('second-job', wait_seconds=0)
    finally:
        _kill_and_wait(detached)
    ml.release(ml.acquire('after-the-descendant', wait_seconds=0))


KILLED_BEFORE_FENCE = ('import os,sys\n'
                       'from ravel.workflow import machine_lease, stage_supervisor\n'
                       '# The supervisor dies right after the child starts, before it can complete the fence.\n'
                       'machine_lease.fence = lambda *a, **k: os._exit(9)\n'
                       'stage_supervisor.supervise("gen", sys.argv[1], 10, "logs/gen.log",\n'
                       '    [sys.executable, "-c", "import os,sys,time;open(sys.argv[1],\'w\').write(str(os.getpid()));time.sleep(20)",\n'
                       '     sys.argv[2]], kill_secs=60.0, poll=0.1, grace=2.0, required_plan="smoke")\n')


def test_the_supervised_stage_fence_is_published_before_the_child_starts(tmp_path):
    import subprocess
    root = rundir(tmp_path)
    marker = tmp_path / 'child.txt'
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(p for p in sys.path if p)}
    supervisor = subprocess.run([sys.executable, '-c', KILLED_BEFORE_FENCE, str(root), str(marker)], env=env,
                                capture_output=True, text=True, timeout=60)
    assert supervisor.returncode == 9, supervisor.stderr
    deadline = time.monotonic() + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    child = int(marker.read_text())
    try:
        with pytest.raises(ml.LeaseBusy):
            ml.acquire('second-job', wait_seconds=0)
    finally:
        _kill_and_wait(child)
    ml.release(ml.acquire('after-the-child', wait_seconds=0))


def test_two_submissions_under_one_lease_are_refused(tmp_path):
    plan = eb.load_plan(make_plan(tmp_path, SLEEPER))
    with ml.held('one job'):
        first = eb.submit(plan, tmp_path / 'first')
        try:
            with pytest.raises(ml.LeaseBusy, match='one computation'):
                eb.submit(plan, tmp_path / 'second')
            assert not (tmp_path / 'second/job/launcher.json').exists()
        finally:
            eb.cancel(plan, first, wait_seconds=5.0)


def test_submit_needs_an_approved_lease_in_the_machine_domain(tmp_path, monkeypatch):
    plan = eb.load_plan(make_plan(tmp_path, COUNT))
    monkeypatch.delenv(ml.TEST_ENV, raising=False)
    monkeypatch.setattr(ml, '_LOCATION', tmp_path / 'machine')
    with pytest.raises(ValueError, match='approved stage'):
        with ml.held('probe-holder'):
            eb.submit(plan, tmp_path / 'attempt')
    with pytest.raises(ValueError, match='approved'):
        eb.submit(plan, tmp_path / 'attempt')
    assert not (tmp_path / 'attempt/job').exists() and not (tmp_path / 'attempt' / eb.HANDLE_NAME).exists()


def test_cancel_does_not_signal_a_group_it_cannot_prove_is_the_job(tmp_path):
    import subprocess
    from ravel.workflow.backends import native
    # A group whose leader has exited: its id may have been reused, and nothing ties it to this job.
    leader = subprocess.Popen([sys.executable, '-c', 'import subprocess\n'
                               'p = subprocess.Popen(["/bin/sleep", "30"])\nprint(p.pid, flush=True)\n'],
                              stdout=subprocess.PIPE, text=True, start_new_session=True)
    sleeper = int(leader.stdout.readline())
    leader.wait()
    try:
        handle = {'remote': {'pid': leader.pid, 'pgid': leader.pid, 'identity': 'Thu Jan  1 00:00:00 1970'},
                  'job_dir': str(tmp_path)}
        result = native.NativeBackend().cancel({}, handle, grace=0.2)
        time.sleep(0.3)
        assert result['signalled'] is False and not _dead(sleeper)
    finally:
        _kill_and_wait(sleeper)



# ---------------------------------------------------------------- approval at every dispatch
def _machine_domain(tmp_path, monkeypatch):
    monkeypatch.delenv(ml.TEST_ENV, raising=False)
    monkeypatch.setattr(ml, '_LOCATION', tmp_path / 'machine')


def test_a_science_binding_needs_a_valid_approval_receipt(tmp_path, monkeypatch):
    from ravel.workflow import physics_review, science
    root = tmp_path / 'study'
    (root / 'inputs').mkdir(parents=True)
    (root / science.PLAN).write_text('{"schema_version": 2}')
    monkeypatch.setattr(physics_review, '_science_run', lambda path: True)
    monkeypatch.setattr(science, 'review_enabled', lambda path: True)
    (root / science.SPEC).write_text('{"schema_version": 2}')
    with pytest.raises((ValueError, KeyError, OSError)):  # no approval receipt at all
        eb.verify_stage_binding({'rundir': str(root), 'node_id': 'science', 'route': 'science', 'rung': None})
    calls = []

    def stale(rd, spec, **kwargs):
        calls.append(spec)
        raise ValueError('missing or stale study approval')
    monkeypatch.setattr(science, '_verify_v2_approval', stale)
    with pytest.raises(ValueError, match='stale study approval'):
        eb.verify_stage_binding({'rundir': str(root), 'node_id': 'science', 'route': 'science', 'rung': None})
    assert calls == [{'schema_version': 2}]


def test_a_scoped_likelihood_binding_needs_its_approved_plan(tmp_path):
    root = tmp_path / 'scoped'
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/scoped-plan.json').write_text('{"mode": "likelihood"}')
    (root / 'inputs/checkin1_approval.json').write_text('{}')
    with pytest.raises((ValueError, OSError)):
        eb.verify_stage_binding({'rundir': str(root), 'node_id': 'likelihood', 'route': 'scoped-likelihood',
                                 'rung': None})


def test_a_held_lease_does_not_dispatch_after_its_approval_is_revoked(tmp_path, monkeypatch):
    path = make_plan(tmp_path, COUNT)
    plan = eb.load_plan(path)
    root = approved_root(tmp_path)
    _machine_domain(tmp_path, monkeypatch)
    binding = eb.approved_binding(root, 'count', 'checkin1', 'smoke')
    with ml.held(f'{root}:count', rundir=str(root), node_id='count', binding=binding):
        (root / 'inputs/checkin1_approval.json').unlink()
        with pytest.raises(ValueError, match='not approved'):
            eb.submit(plan, tmp_path / 'attempt', plan_bytes=path.read_bytes(), authority=(root, 'count'))
    assert not (tmp_path / 'attempt').exists()


def test_a_held_lease_does_not_dispatch_a_plan_its_stage_did_not_pin(tmp_path, monkeypatch):
    path = make_plan(tmp_path, COUNT)
    plan = eb.load_plan(path)
    root = approved_root(tmp_path)
    _machine_domain(tmp_path, monkeypatch)
    binding = eb.approved_binding(root, 'count', 'checkin1', 'smoke')
    with ml.held(f'{root}:count', rundir=str(root), node_id='count', binding=binding):
        # No running attempt pins these bytes, and the caller is no proven worker of the stage.
        with pytest.raises(ValueError, match='pinned|supervised|worker|attempt'):
            eb.submit(plan, tmp_path / 'attempt', plan_bytes=path.read_bytes(), authority=(root, 'count'))
        with pytest.raises(ValueError):
            eb.submit(plan, tmp_path / 'attempt')
    assert not (tmp_path / 'attempt').exists()


def test_require_approved_stage_rechecks_the_science_approval_receipt(tmp_path, monkeypatch):
    from ravel.workflow import launch_authorization, physics_review, science
    root = tmp_path / 'study'
    (root / 'inputs').mkdir(parents=True)
    (root / science.PLAN).write_text('{"schema_version": 2}')
    plan_sha = execution.file_hash(root / science.PLAN)
    record = {'authorization_receipt': {'sequence': 2, 'sha256': 'x'}, 'child_pid': 7, 'command': ['w'],
              'attempt_id': 'a1', 'input_snapshot': {}}
    monkeypatch.setattr(execution, 'await_worker_registration', lambda rd, stage: None)
    monkeypatch.setattr(execution, 'load_execution', lambda rd: {'stages': {'science': record}})
    monkeypatch.setattr(launch_authorization, '_events', lambda rd: [
        {'sequence': 1, 'event': 'authorized', 'command': ['w'], 'authorization': {'required_plan': 'science'},
         'context': {'stage': 'science', 'plan_sha256': plan_sha}},
        {'sequence': 2, 'event': 'launched', 'sha256': 'x', 'pid': 7, 'authorization_sequence': 1}])
    monkeypatch.setattr(physics_review, '_science_run', lambda path: True)
    monkeypatch.setattr(science, 'review_enabled', lambda path: True)
    (root / science.SPEC).write_text('{"schema_version": 2}')

    def stale(rd, spec, **kwargs):
        raise ValueError('missing or stale study approval')
    monkeypatch.setattr(science, '_verify_v2_approval', stale)
    with pytest.raises(ValueError, match='stale study approval'):
        eb.require_approved_stage(root, 'science')
    monkeypatch.setattr(science, '_verify_v2_approval', lambda rd, spec, **k: None)
    assert eb.require_approved_stage(root, 'science')['attempt_id'] == 'a1'


def test_a_failed_authorized_start_leaves_no_reservation_held_by_a_live_supervisor(tmp_path, monkeypatch):
    from ravel.workflow import launch_authorization

    def refused(*args, **kwargs):
        raise ValueError('launch authorization refused')
    monkeypatch.setattr(launch_authorization, 'authorized_popen', refused)
    root = rundir(tmp_path)
    code = supervise('gen', root, 10, 'logs/gen.log', [sys.executable, '-c', 'pass'], kill_secs=30.0, poll=0.1)
    assert code != 0
    # This long-lived caller is still alive: it must not be the starter of a leftover reservation.
    rows = (ml._fence_document() or {'groups': []})['groups']
    assert not [row for row in rows if (row.get('starter') or {}).get('pid') == os.getpid()]
    ml.release(ml.acquire('competing job', wait_seconds=0))
