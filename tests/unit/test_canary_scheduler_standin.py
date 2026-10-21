"""The canary HTCondor stand-in runs submitted jobs as detached processes and reports their state."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

STANDIN = Path(__file__).resolve().parents[1] / 'fixtures' / 'canaries' / 'bin' / 'fake_scheduler.py'
COMMANDS = ('condor_submit', 'condor_q', 'condor_history', 'condor_rm')
SHELL_MAINTAINED = {'PWD', 'OLDPWD', 'SHLVL', '_'}

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process sessions')


@pytest.fixture
def scheduler(tmp_path):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    state = tmp_path / 'effects' / 'scheduler.json'
    for name in COMMANDS:
        wrapper = bin_dir / name
        wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} -I {STANDIN} {state} "$0" "$@"\n')
        wrapper.chmod(0o755)
    environment = dict(os.environ, RAVEL_STANDIN_LEAK_PROBE='must-not-reach-the-job')

    def run(name, *args, check=True):
        done = subprocess.run([str(bin_dir / name), *map(str, args)], capture_output=True, text=True,
                              env=environment, cwd=tmp_path, timeout=30, check=False)
        if check:
            assert done.returncode == 0, done.stderr
        return done

    run.state = state
    run.root = tmp_path
    yield run
    if state.is_file():
        for job in json.loads(state.read_text())['jobs']:
            if 'pgid' in job:
                try:
                    os.killpg(int(job['pgid']), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass


def _descriptor(root, name, body, *, environment='"MARKER=1"', extra=()):
    workdir = root / 'work'
    workdir.mkdir(exist_ok=True)
    script = workdir / (name + '.sh')
    script.write_text('#!/bin/sh\n' + body + '\n')
    logs = root / 'logs' / name
    lines = ['universe = vanilla', 'executable = /bin/sh', 'arguments = "\'' + str(script) + '\'"',
             'initialdir = "' + str(workdir) + '"', 'output = "' + str(logs / 'job.out') + '"',
             'error = "' + str(logs / 'job.err') + '"', 'getenv = False',
             'environment = ' + environment, *extra, 'queue 1']
    path = root / (name + '.sub')
    path.write_text('\n'.join(lines) + '\n')
    return path, workdir, logs


def _submit(scheduler, descriptor):
    out = scheduler('condor_submit', '-terse', descriptor).stdout.split()[0]
    return out.split('.')[0]


def _row(scheduler, cluster):
    return next(job for job in json.loads(scheduler.state.read_text())['jobs'] if str(job['cluster']) == cluster)


def _history(scheduler, cluster):
    return scheduler('condor_history', cluster, '-limit', '1', '-af', 'JobStatus', 'ExitCode').stdout.split()


def _wait_finished(scheduler, cluster, deadline=30.0):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if scheduler('condor_q', cluster, '-af', 'JobStatus').stdout.strip() == '':
            return _history(scheduler, cluster)
        time.sleep(0.1)
    raise AssertionError('job ' + cluster + ' did not finish')


def _gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    stat = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    return not stat or stat.startswith('Z')


def test_submitted_job_runs_detached_and_completes(scheduler):
    descriptor, workdir, logs = _descriptor(scheduler.root, 'ok', 'echo written > result.txt\necho hello\nsleep 1')
    cluster = _submit(scheduler, descriptor)
    row = _row(scheduler, cluster)
    for key in ('pid', 'pgid', 'job_dir', 'started_utc', 'sha256', 'script_sha256', 'description_sha256',
                'text', 'script_text', 'launcher_sha256', 'cwd'):
        assert key in row, key
    assert row['pgid'] == row['pid'] and row['cwd'] == str(workdir)
    assert scheduler('condor_q', cluster, '-af', 'JobStatus', 'ExitCode').stdout.split() == ['2', 'undefined']
    assert _wait_finished(scheduler, cluster) == ['4', '0']
    assert (workdir / 'result.txt').read_text() == 'written\n'
    assert (logs / 'job.out').read_text() == 'hello\n'
    assert _row(scheduler, cluster)['status'] == 4
    view = json.loads(scheduler('condor_history', cluster, '-json').stdout)
    assert len(view) == 1 and view[0]['JobStatus'] == 4 and view[0]['ExitCode'] == 0
    assert view[0]['ClusterId'] == int(cluster)


def test_failing_job_records_its_exit_code_and_output(scheduler):
    descriptor, _, logs = _descriptor(scheduler.root, 'fail', 'echo partial\necho broken >&2\nexit 3')
    cluster = _submit(scheduler, descriptor)
    assert _wait_finished(scheduler, cluster) == ['4', '3']
    assert (logs / 'job.out').read_text() == 'partial\n'
    assert (logs / 'job.err').read_text() == 'broken\n'


def test_plain_executable_with_arguments(scheduler):
    workdir = scheduler.root / 'plain'
    workdir.mkdir()
    script = workdir / 'job.sh'
    script.write_text('#!/bin/sh\nprintf "%s|" "$@" > args.txt\n')
    script.chmod(0o755)
    descriptor = workdir / 'job.sub'
    descriptor.write_text(f'executable = {script}\narguments = "one \'two words\' \'it\'\'s\'"\nqueue\n')
    cluster = _submit(scheduler, descriptor)
    assert _wait_finished(scheduler, cluster) == ['4', '0']
    assert (workdir / 'args.txt').read_text() == "one|two words|it's|"
    job_dir = Path(_row(scheduler, cluster)['job_dir'])
    assert job_dir.parent.parent == scheduler.state.parent
    assert (job_dir / 'stdout').is_file() and (job_dir / 'stderr').is_file()


def test_condor_rm_terminates_the_process_group(scheduler):
    descriptor, _, _ = _descriptor(scheduler.root, 'sleepy', 'sleep 60 &\nsleep 60')
    cluster = _submit(scheduler, descriptor)
    row = _row(scheduler, cluster)
    assert scheduler('condor_q', cluster, '-af', 'JobStatus').stdout.split() == ['2']
    assert 'Removed job ' + cluster in scheduler('condor_rm', cluster).stdout
    end = time.monotonic() + 10
    while not _gone(row['pid']) and time.monotonic() < end:
        time.sleep(0.05)
    assert _gone(row['pid'])
    members = subprocess.run(['ps', '-A', '-o', 'pgid=,stat='], capture_output=True, text=True).stdout
    assert not [line for line in members.splitlines()
                if line.split()[0] == str(row['pgid']) and not line.split()[1].startswith('Z')]
    assert scheduler('condor_q', cluster, '-af', 'JobStatus').stdout == ''
    assert _history(scheduler, cluster)[0] == '3'
    state = json.loads(scheduler.state.read_text())
    assert cluster in state['removed']
    assert [event['command'] for event in state['events']][-1] == 'condor_history'


def test_lost_job_is_completed_without_exit_code(scheduler):
    descriptor, _, _ = _descriptor(scheduler.root, 'lost', 'sleep 60')
    cluster = _submit(scheduler, descriptor)
    os.kill(_row(scheduler, cluster)['pid'], signal.SIGKILL)
    assert _wait_finished(scheduler, cluster) == ['4', 'undefined']


def test_environment_is_only_the_descriptor_plus_path_and_home(scheduler):
    environment = '"MARKER=1 SPACED=\'two words\' QUOTED=\'it\'\'s\' EMPTY="'
    descriptor, workdir, _ = _descriptor(scheduler.root, 'env', 'env > env.txt', environment=environment)
    cluster = _submit(scheduler, descriptor)
    assert _wait_finished(scheduler, cluster) == ['4', '0']
    seen = dict(line.split('=', 1) for line in (workdir / 'env.txt').read_text().splitlines())
    for name in SHELL_MAINTAINED:
        seen.pop(name, None)
    job_dir = Path(_row(scheduler, cluster)['job_dir'])
    home, scratch = job_dir / 'home', job_dir / 'scratch'
    assert seen == {'MARKER': '1', 'SPACED': 'two words', 'QUOTED': "it's", 'EMPTY': '',
                    'PATH': '/usr/bin:/bin', 'HOME': str(home),
                    '_CONDOR_SCRATCH_DIR': str(scratch), '_CONDOR_JOB_AD': str(scratch / '.job.ad')}
    assert home.is_dir() and scratch.is_dir() and (scratch / '.job.ad').is_file()
    assert f'ClusterId = {cluster}' in (scratch / '.job.ad').read_text()


def test_descriptor_path_and_home_are_kept(scheduler):
    home = scheduler.root / 'given-home'
    environment = f'"HOME={home} PATH=/opt/tools/bin:/usr/bin:/bin"'
    descriptor, workdir, _ = _descriptor(scheduler.root, 'env2', 'env > env.txt', environment=environment)
    cluster = _submit(scheduler, descriptor)
    assert _wait_finished(scheduler, cluster) == ['4', '0']
    seen = dict(line.split('=', 1) for line in (workdir / 'env.txt').read_text().splitlines())
    for name in SHELL_MAINTAINED:
        seen.pop(name, None)
    scratch = Path(_row(scheduler, cluster)['job_dir']) / 'scratch'
    assert seen == {'HOME': str(home), 'PATH': '/opt/tools/bin:/usr/bin:/bin',
                    '_CONDOR_SCRATCH_DIR': str(scratch), '_CONDOR_JOB_AD': str(scratch / '.job.ad')}


def test_query_forms_and_constraints(scheduler):
    descriptor, _, _ = _descriptor(scheduler.root, 'tagged', 'sleep 2',
                                   extra=('+RavelProject = "proj"', 'batch_name = "run-a"'))
    cluster = _submit(scheduler, descriptor)
    rows = json.loads(scheduler('condor_q', '-constraint', 'RavelProject == "proj"', '-json').stdout)
    assert [(row['ClusterId'], row['JobStatus'], row['ExitCode'], row['RavelTag']) for row in rows] == \
        [(int(cluster), 2, None, 'run-a')]
    assert scheduler('condor_q', '-constraint', 'RavelProject == "other"', '-json').stdout == '[]'
    constraint = f'ClusterId == {cluster} && ProcId == 0'
    assert scheduler('condor_q', '-constraint', constraint, '-af', 'ClusterId', 'JobStatus').stdout.split() == \
        [cluster, '2']
    assert _wait_finished(scheduler, cluster) == ['4', '0']


def test_a_pinned_status_wins_over_the_process(scheduler):
    descriptor, _, _ = _descriptor(scheduler.root, 'pinned', 'sleep 1')
    cluster = _submit(scheduler, descriptor)
    state = json.loads(scheduler.state.read_text())
    for job in state['jobs']:
        job.update(status=4, exit_code=7)
    scheduler.state.write_text(json.dumps(state))
    assert _history(scheduler, cluster) == ['4', '7']
    time.sleep(1.5)
    assert _history(scheduler, cluster) == ['4', '7']
    assert scheduler('condor_q', cluster, '-af', 'JobStatus').stdout == ''


def test_new_job_status_models_an_outcome_without_running(scheduler):
    scheduler.state.parent.mkdir(parents=True)
    scheduler.state.write_text(json.dumps({'next': 100, 'jobs': [], 'removed': [], 'events': [],
                                           'new_job_status': 4, 'new_job_exit_code': 0}))
    descriptor, workdir, _ = _descriptor(scheduler.root, 'modelled', 'echo ran > ran.txt')
    cluster = _submit(scheduler, descriptor)
    assert _history(scheduler, cluster) == ['4', '0']
    row = _row(scheduler, cluster)
    assert row['pinned_status'] is True and 'pid' not in row
    time.sleep(0.3)
    assert not (workdir / 'ran.txt').exists()


def test_missing_initialdir_is_refused(scheduler):
    descriptor = scheduler.root / 'bad.sub'
    descriptor.write_text(f'executable = /bin/sh\ninitialdir = "{scheduler.root / "absent"}"\nqueue\n')
    done = scheduler('condor_submit', '-terse', descriptor, check=False)
    assert done.returncode != 0 and 'initialdir' in done.stderr
    assert json.loads(scheduler.state.read_text())['jobs'] == []
