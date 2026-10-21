"""The batch-job observer and the operator stop against the HTCondor stand-in, whose jobs are real processes.

The stand-in's four commands are installed on a PATH directory, so the scheduler client functions resolve and call
them exactly as they would call a site's clients. Every name is fictional.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from test_p06_support import autonomous, operator_home  # noqa: F401
from test_autonomy_needs import _store_with_dir
from ravel.controller import batch_jobs
from ravel.controller.authority import OPERATOR_COMMAND, autonomy, common, stop
from ravel.workflow import wms_site

STANDIN = Path(__file__).resolve().parents[2] / 'fixtures' / 'canaries' / 'bin' / 'fake_scheduler.py'
COMMANDS = ('condor_submit', 'condor_q', 'condor_history', 'condor_rm')

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process sessions')


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    state = tmp_path / 'effects' / 'scheduler.json'
    for name in COMMANDS:
        wrapper = bin_dir / name
        wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} -I {STANDIN} {state} "$0" "$@"\n')
        wrapper.chmod(0o755)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))

    def run(name, *args, check=True):
        done = subprocess.run([str(bin_dir / name), *map(str, args)], capture_output=True, text=True,
                              cwd=tmp_path, timeout=30, check=False)
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


def _descriptor(root, name, body):
    workdir = root / 'work'
    workdir.mkdir(exist_ok=True)
    script = workdir / (name + '.sh')
    script.write_text('#!/bin/sh\n' + body + '\n')
    logs = root / 'logs' / name
    lines = ['universe = vanilla', 'executable = /bin/sh', 'arguments = "\'' + str(script) + '\'"',
             'initialdir = "' + str(workdir) + '"', 'output = "' + str(logs / 'job.out') + '"',
             'error = "' + str(logs / 'job.err') + '"', 'getenv = False', 'environment = "MARKER=1"', 'queue 1']
    path = root / (name + '.sub')
    path.write_text('\n'.join(lines) + '\n')
    return path


def _submit_sleeper(scheduler, store, name):
    """Submit one sleeping job through the stand-in and journal it as the controller does; returns its job id."""
    descriptor = _descriptor(scheduler.root, name, 'sleep 60')
    out = scheduler('condor_submit', '-terse', descriptor).stdout.split()[0]
    job = out.split('.')[0] + '.0'
    store.append('study-site-job', {'launch_id': 'operate', 'job': job, 'scheduler': 'htcondor',
                                    'jobscript_sha256': '0' * 64})
    return job


def _state(scheduler):
    return json.loads(scheduler.state.read_text())


def _row(scheduler, job):
    return next(r for r in _state(scheduler)['jobs'] if str(r['cluster']) == job.split('.')[0])


def _pin(scheduler, job, **fields):
    state = _state(scheduler)
    for row in state['jobs']:
        if str(row['cluster']) == job.split('.')[0]:
            row.update(fields)
    scheduler.state.write_text(json.dumps(state))


def _group_gone(pgid):
    """No live (non-zombie) member remains in the process group; a reaped or exited leader may linger as a zombie."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    members = subprocess.run(['ps', '-A', '-o', 'pgid=,stat='], capture_output=True, text=True).stdout
    return not [line for line in members.splitlines()
                if line.split() and line.split()[0] == str(pgid) and not line.split()[1].startswith('Z')]


def _wait_gone(pgid, deadline=10.0):
    end = time.monotonic() + deadline
    while not _group_gone(pgid) and time.monotonic() < end:
        time.sleep(0.05)
    return _group_gone(pgid)


def _history_status(scheduler, job):
    return scheduler('condor_history', job.split('.')[0], '-af', 'JobStatus').stdout.split()


def _decisions(store):
    return store.scan(batch_jobs.DECISION)


def test_the_operator_stop_drains_real_jobs_and_a_second_stop_removes_nothing_again(operator_home, tmp_path, scheduler,
                                                                                    monkeypatch, capsys):
    from ravel.controller.authority import cli
    autonomous()
    store = _store_with_dir(tmp_path)
    jobs = [_submit_sleeper(scheduler, store, 'one'), _submit_sleeper(scheduler, store, 'two')]
    groups = {job: int(_row(scheduler, job)['pgid']) for job in jobs}
    assert not any(_group_gone(pgid) for pgid in groups.values())
    monkeypatch.setattr(common, 'open_store', lambda identifier: store)
    assert cli.main(['stop', '--run', store.run_id, '--reason', 'operator stop']) == 0
    result = json.loads(capsys.readouterr().out)['batch_jobs']
    assert result['verified'] is True and result['unverified'] == []
    assert [j['job'] for j in result['jobs']] == jobs
    for entry in result['jobs']:
        assert entry['before']['state'] == 'running' and entry['after']['state'] == 'cancelled'
        assert entry['cancel']['returncode'] == 0 and entry['verified'] is True
    for job in jobs:
        assert _wait_gone(groups[job])
        assert _history_status(scheduler, job) == ['3']
    removed = list(_state(scheduler)['removed'])
    assert sorted(removed) == sorted(job.split('.')[0] for job in jobs)
    assert cli.main(['stop', '--run', store.run_id, '--reason', 'operator stop again']) == 0
    again = json.loads(capsys.readouterr().out)['batch_jobs']
    assert again['verified'] is True
    assert [j['already_terminal'] for j in again['jobs']] == [True, True]
    assert all(j['cancel'] is None for j in again['jobs'])
    assert _state(scheduler)['removed'] == removed
    assert len([e for e in _state(scheduler)['events'] if e['command'] == 'condor_rm']) == 2


def test_the_observer_reads_a_hold_a_release_and_a_foreign_removal_from_real_scheduler_output(operator_home, tmp_path,
                                                                                              scheduler):
    autonomous()
    store = _store_with_dir(tmp_path)
    job = _submit_sleeper(scheduler, store, 'watched')
    running = batch_jobs.observe(store)
    assert [r['job'] for r in running['active']] == [job] and running['held'] == [] and running['removed'] == []
    assert batch_jobs.decide(store, running) == []
    _pin(scheduler, job, status=5, hold_reason_code=7)
    held = batch_jobs.observe(store)
    assert [r['job'] for r in held['held']] == [job]
    assert held['held'][0]['observation']['state'] == 'held'
    assert held['held'][0]['observation']['hold']['code'] == 7
    decisions = batch_jobs.decide(store, held)
    assert [d['decision'] for d in decisions] == ['await_release'] and batch_jobs.hold_for(decisions) is None
    assert [c['phase'] for c in store.scan(autonomy.CONDITION) if c['code'] == 'jobs_held'] == ['open']
    _pin(scheduler, job, status=2)
    released = batch_jobs.observe(store)
    assert [r['job'] for r in released['active']] == [job] and released['held'] == []
    decisions = batch_jobs.decide(store, released)
    assert [d['decision'] for d in decisions] == ['released']
    assert [c['phase'] for c in store.scan(autonomy.CONDITION) if c['code'] == 'jobs_held'] == ['open', 'cleared']
    assert 'Removed job' in scheduler('condor_rm', job.split('.')[0]).stdout  # someone else, not the run
    removed = batch_jobs.observe(store)
    assert [r['job'] for r in removed['removed']] == [job] and removed['held'] == []
    decisions = batch_jobs.decide(store, removed)
    assert [d['decision'] for d in decisions] == ['recover']
    assert batch_jobs.hold_for(decisions).code == 'batch_jobs_removed'
    assert [c['phase'] for c in store.scan(autonomy.CONDITION) if c['code'] == 'jobs_removed'] == ['open']
    assert [d['decision'] for d in _decisions(store)] == ['await_release', 'released', 'recover']


def test_a_job_the_run_drained_itself_is_never_reported_removed(operator_home, tmp_path, scheduler):
    autonomous()
    store = _store_with_dir(tmp_path)
    job = _submit_sleeper(scheduler, store, 'drained')
    stop.record_control(store, 'stop', label=OPERATOR_COMMAND, source='operator_cli', evidence={}, reason='halt')
    result = batch_jobs.stop_jobs(store)
    assert result['verified'] is True and result['jobs'][0]['after']['state'] == 'cancelled'
    assert _wait_gone(int(_row(scheduler, job)['pgid']))
    assert batch_jobs.own_cancellations(store) == {job}
    observed = batch_jobs.observe(store)
    assert observed['jobs'] == [] and observed['removed'] == []
    assert batch_jobs.decide(store, observed) == []
    seen = wms_site.observe_job(job)
    assert seen['state'] == 'cancelled'
    classified = batch_jobs.classify(store, [{'launch_id': 'operate', 'job': job, 'observation': seen}])
    assert classified['removed'] == [] and [r['job'] for r in classified['jobs']] == [job]
    assert store.scan(autonomy.CONDITION) == [] and _decisions(store) == []
