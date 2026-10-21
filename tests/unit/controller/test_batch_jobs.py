"""The controller's batch-job observer, its typed recovery decisions and the operator stop's own drain.

Inert: the scheduler is replaced by injected observe, cancel and hold-reason callables, so no process starts.
Every name is fictional.
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from test_p06_support import autonomous, new_store, operator_home  # noqa: F401
from test_autonomy_needs import _store_with_dir, _tampered
from ravel.controller import batch_jobs, recovery
from ravel.controller.authority import AuthorityRefused, OPERATOR_COMMAND, autonomy, common, stop

HELD = {'state': 'held'}
RUNNING = {'state': 'running'}
CANCELLED = {'state': 'cancelled'}


def _journal(store, *jobs, launch_id='operate'):
    for job in jobs:
        store.append('study-site-job', {'launch_id': launch_id, 'job': job, 'scheduler': 'htcondor',
                                        'jobscript_sha256': '0' * 64})


def _conditions(store, code):
    return [r for r in store.scan(autonomy.CONDITION) if r['code'] == code]


def _decisions(store):
    return store.scan(batch_jobs.DECISION)


def _stop(store, action='stop'):
    return stop.record_control(store, action, label=OPERATOR_COMMAND, source='operator_cli', evidence={},
                               reason='halt')


class Clock:
    """A fake clock for the stop's bounded re-observation: sleeping advances time and never waits."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        self.now += 0.01
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    @staticmethod
    def time_ns():
        import time
        return time.time_ns()


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(batch_jobs, 'time', fake)
    return fake


class Scheduler:
    """Injected scheduler functions: ``stubborn`` jobs ignore a cancellation, ``slow`` ones end one poll later."""

    def __init__(self, states, *, stubborn=(), slow=(), broken=()):
        self.states, self.stubborn, self.slow, self.broken = dict(states), set(stubborn), set(slow), set(broken)
        self.cancelled, self.observed, self.pending = [], [], {}

    def observe(self, job):
        self.observed.append(job)
        if job in self.broken:
            raise RuntimeError('scheduler unreachable')
        if self.pending.get(job):
            self.pending[job] -= 1
            if not self.pending[job]:
                self.states[job] = 'cancelled'
        return {'state': self.states[job]}

    def cancel(self, job):
        self.cancelled.append(job)
        if job not in self.stubborn:
            if job in self.slow:
                self.pending[job] = 2
            else:
                self.states[job] = 'cancelled'
        return {'returncode': 0, 'command': 'fictional-rm'}

    def hold_reason(self, job):
        return {'code': 7, 'raw': '7'}


def test_classify_sorts_held_removed_and_active_rows_and_never_calls_the_run_own_drain_removed(operator_home, tmp_path):
    store = new_store(tmp_path)
    store.append('study-site-job-state', {'launch_id': 'operate', 'job': '3.0', 'drain': True,
                                          'cancel': {'returncode': 0}, 'observation': dict(CANCELLED)})
    rows = [{'launch_id': 'operate', 'job': job, 'observation': dict(state)} for job, state in (
        ('1.0', HELD), ('2.0', CANCELLED), ('3.0', CANCELLED), ('4.0', {'state': 'pending'}), ('5.0', RUNNING))]
    found = batch_jobs.classify(store, rows, hold_reason=lambda job: {'code': 7, 'job': job})
    assert [r['job'] for r in found['jobs']] == ['1.0', '2.0', '3.0', '4.0', '5.0']
    assert [r['job'] for r in found['held']] == ['1.0']
    assert found['held'][0]['observation']['hold'] == {'code': 7, 'job': '1.0'}
    assert [r['job'] for r in found['removed']] == ['2.0']
    assert [r['job'] for r in found['active']] == ['4.0', '5.0']
    assert 'hold' not in found['active'][0]['observation']
    assert batch_jobs.own_cancellations(store) == {'3.0'}


def test_observe_skips_jobs_recorded_terminal_and_records_an_observer_exception_as_unknown(operator_home, tmp_path):
    store = new_store(tmp_path)
    _journal(store, '1.0', '2.0', '3.0')
    store.append('study-site-job-state', {'launch_id': 'operate', 'job': '1.0', 'observation': {'state': 'exited'}})
    calls = []

    def observe(job):
        calls.append(job)
        if job == '3.0':
            raise RuntimeError('boom')
        return dict(RUNNING)
    found = batch_jobs.observe(store, observe_job=observe)
    assert calls == ['2.0', '3.0']
    assert {r['job']: r['observation']['state'] for r in found['jobs']} == {'2.0': 'running', '3.0': 'unknown'}
    unknown = next(r for r in found['jobs'] if r['job'] == '3.0')
    assert 'RuntimeError' in unknown['observation']['error'] and 'boom' in unknown['observation']['error']
    assert [r['job'] for r in found['active']] == ['2.0'] and found['held'] == [] and found['removed'] == []



def test_a_tampered_ledger_refuses_the_job_census_and_never_reads_as_no_jobs(operator_home, tmp_path):
    from ravel.controller import store as store_module
    store = store_module.RunStore.create(tmp_path / 'runs' / 'fictional-run', root=tmp_path / 'ledger')
    assert batch_jobs.journalled(store) == [] and batch_jobs.own_cancellations(store) == set()  # nothing journalled
    _journal(store, '510.0', '520.0')
    store.append('study-site-job-state', {'launch_id': 'operate', 'job': '510.0', 'cancel': {'returncode': 0},
                                          'observation': dict(CANCELLED)})
    assert [r['job'] for r in batch_jobs.journalled(store)] == ['510.0', '520.0']
    assert batch_jobs.own_cancellations(store) == {'510.0'}
    reopened = _tampered(store, 1, 'job', '599.0')
    assert reopened.verify() != []

    def unobserved(job):
        raise AssertionError('a job read from a tampered ledger is never observed')
    for census in (batch_jobs.journalled, batch_jobs.own_cancellations,
                   lambda s: batch_jobs.observe(s, observe_job=unobserved)):
        with pytest.raises(store_module.StoreTampered):
            census(reopened)

def test_a_held_job_reports_jobs_held_once_with_one_wait_and_one_await_release_decision(operator_home, tmp_path):
    autonomous()
    store = _store_with_dir(tmp_path)
    _journal(store, '300.0')
    scheduler = Scheduler({'300.0': 'held'})
    for _ in range(3):
        observed = batch_jobs.observe(store, observe_job=scheduler.observe, hold_reason=scheduler.hold_reason)
        assert [r['job'] for r in observed['held']] == ['300.0']
        assert observed['jobs'][0]['observation']['hold']['code'] == 7
        decisions = batch_jobs.decide(store, observed)
        assert [d['decision'] for d in decisions] == ['await_release']
        assert batch_jobs.hold_for(decisions) is None
    assert [r['phase'] for r in _conditions(store, 'jobs_held')] == ['open']
    assert [w['code'] for w in autonomy.open_waits(store)] == ['jobs_held']
    assert [r['phase'] for r in store.scan(autonomy.WAIT)] == ['open']
    [record] = _decisions(store)
    assert record['decision'] == 'await_release' and record['jobs'] == ['300.0'] and record['code'] == 'batch_jobs_held'
    assert record['controller_never'] == ['release', 'edit', 'resubmit']


def test_a_hold_past_the_wait_bound_ends_qualified_with_a_typed_hold(operator_home, tmp_path):
    autonomous(wait_bound_seconds=60)
    store = _store_with_dir(tmp_path)
    _journal(store, '300.0')
    scheduler = Scheduler({'300.0': 'held'})
    observed = batch_jobs.observe(store, observe_job=scheduler.observe, hold_reason=scheduler.hold_reason)
    [first] = batch_jobs.decide(store, observed)
    assert first['decision'] == 'await_release' and first['wait_bound_seconds'] == 60
    started = first['first_held_ns']
    [within] = batch_jobs.decide(store, observed, now_ns=started + 59 * 10 ** 9)
    assert within['decision'] == 'await_release' and within['first_held_ns'] == started
    decisions = batch_jobs.decide(store, observed, now_ns=started + 61 * 10 ** 9)
    assert [d['decision'] for d in decisions] == ['end_qualified']
    hold = batch_jobs.hold_for(decisions)
    assert isinstance(hold, batch_jobs.BatchJobsHold) and hold.code == 'batch_jobs_held'
    assert str(hold).startswith('batch_jobs_held: ') and '300.0' in str(hold)
    with pytest.raises(batch_jobs.BatchJobsHold):
        raise hold
    assert [d['decision'] for d in _decisions(store)] == ['await_release', 'end_qualified']
    assert recovery.classify({'status': 'held', 'reason': str(hold)})['recoverable'] is False


def test_a_job_running_again_after_a_hold_clears_jobs_held_and_decides_released(operator_home, tmp_path):
    autonomous()
    store = _store_with_dir(tmp_path)
    _journal(store, '300.0')
    scheduler = Scheduler({'300.0': 'held'})
    batch_jobs.decide(store, batch_jobs.observe(store, observe_job=scheduler.observe,
                                                hold_reason=scheduler.hold_reason))
    assert _conditions(store, 'jobs_held')[-1]['phase'] == 'open'
    scheduler.states['300.0'] = 'running'
    decisions = batch_jobs.decide(store, batch_jobs.observe(store, observe_job=scheduler.observe,
                                                            hold_reason=scheduler.hold_reason))
    assert [d['decision'] for d in decisions] == ['released']
    assert batch_jobs.hold_for(decisions) is None
    assert _conditions(store, 'jobs_held')[-1]['phase'] == 'cleared'
    assert [d['decision'] for d in _decisions(store)] == ['await_release', 'released']
    again = batch_jobs.decide(store, batch_jobs.observe(store, observe_job=scheduler.observe,
                                                        hold_reason=scheduler.hold_reason))
    assert again == [] and len(_decisions(store)) == 2


def test_a_job_removed_by_someone_else_opens_jobs_removed_and_recovers(operator_home, tmp_path):
    autonomous()
    store = _store_with_dir(tmp_path)
    _journal(store, '300.0', '301.0')
    scheduler = Scheduler({'300.0': 'cancelled', '301.0': 'running'})
    for _ in range(2):
        observed = batch_jobs.observe(store, observe_job=scheduler.observe, hold_reason=scheduler.hold_reason)
        assert [r['job'] for r in observed['removed']] == ['300.0']
        decisions = batch_jobs.decide(store, observed)
        assert [d['decision'] for d in decisions] == ['recover']
        hold = batch_jobs.hold_for(decisions)
        assert isinstance(hold, batch_jobs.BatchJobsHold) and hold.code == 'batch_jobs_removed'
        assert '300.0' in str(hold) and '301.0' not in str(hold)
    assert [r['phase'] for r in _conditions(store, 'jobs_removed')] == ['open']
    assert 'jobs_removed' in {w['code'] for w in autonomy.open_waits(store)}
    [record] = _decisions(store)
    assert record['code'] == 'batch_jobs_removed' and record['recoverable_by_replan'] is True
    assert recovery.classify({'status': 'held', 'reason': 'batch_jobs_removed: x'})['recoverable'] is True
    assert recovery.classify({'status': 'held', 'reason': 'batch_jobs_held: x'})['recoverable'] is False


def test_an_unknown_hold_code_is_refused():
    with pytest.raises(ValueError):
        batch_jobs.BatchJobsHold('other', 'x')


def test_stop_jobs_refuses_a_running_run_and_a_pause_and_allows_a_stop_and_a_revoke(operator_home, tmp_path):
    autonomous()
    running = _store_with_dir(tmp_path, run_id='run-0001')
    _journal(running, '300.0')
    scheduler = Scheduler({'300.0': 'running'})
    with pytest.raises(AuthorityRefused):
        batch_jobs.stop_jobs(running, wait_seconds=0, observe_job=scheduler.observe, cancel_job=scheduler.cancel)
    paused = _store_with_dir(tmp_path, run_id='run-0002')
    _journal(paused, '300.0')
    _stop(paused, 'pause')
    with pytest.raises(AuthorityRefused):
        batch_jobs.stop_jobs(paused, wait_seconds=0, observe_job=scheduler.observe, cancel_job=scheduler.cancel)
    assert scheduler.cancelled == [] and scheduler.observed == []
    stopped = _store_with_dir(tmp_path, run_id='run-0003')
    _journal(stopped, '300.0')
    control = _stop(stopped)
    result = batch_jobs.stop_jobs(stopped, wait_seconds=0, observe_job=scheduler.observe, cancel_job=scheduler.cancel)
    assert result['verified'] is True
    revoked = _store_with_dir(tmp_path, run_id='run-0004')
    _journal(revoked, '301.0')
    revoke = _stop(revoked, 'revoke')
    scheduler.states['301.0'] = 'running'
    result = batch_jobs.stop_jobs(revoked, wait_seconds=0, observe_job=scheduler.observe, cancel_job=scheduler.cancel)
    assert result['verified'] is True
    assert revoked.scan(batch_jobs.STOP)[-1]['control_kind'] == 'revoke'
    assert stopped.scan(batch_jobs.STOP)[-1]['control'] == control['id']
    assert revoked.scan(batch_jobs.STOP)[-1]['control'] == revoke['id']


def test_stop_jobs_cancels_once_reobserves_until_terminal_and_a_second_stop_cancels_nothing(operator_home, tmp_path,
                                                                                            clock):
    autonomous()
    store = _store_with_dir(tmp_path)
    _journal(store, '300.0')
    control = _stop(store)
    scheduler = Scheduler({'300.0': 'running'}, slow=['300.0'])
    result = batch_jobs.stop_jobs(store, wait_seconds=5, observe_job=scheduler.observe, cancel_job=scheduler.cancel)
    assert scheduler.cancelled == ['300.0']
    assert scheduler.observed == ['300.0'] * 3
    assert result['verified'] is True and result['unverified'] == []
    [job] = result['jobs']
    assert job['before']['state'] == 'running' and job['after']['state'] == 'cancelled'
    assert job['cancel']['returncode'] == 0 and job['verified'] is True and job['already_terminal'] is False
    [record] = store.scan(batch_jobs.STOP)
    assert record['control'] == control['id'] and record['control_kind'] == 'stop' and record['verified'] is True
    assert [j['job'] for j in record['jobs']] == ['300.0']
    [state] = [r for r in store.scan('study-site-job-state') if 'cancel' in r]
    assert state['job'] == '300.0' and state['stop'] == control['id'] and state['cancelled'] is True
    assert state['observation']['state'] == 'cancelled'
    assert batch_jobs.own_cancellations(store) == {'300.0'}
    again = batch_jobs.stop_jobs(store, wait_seconds=5, observe_job=scheduler.observe, cancel_job=scheduler.cancel)
    assert scheduler.cancelled == ['300.0'] and scheduler.observed == ['300.0'] * 3
    assert again['verified'] is True
    [job] = again['jobs']
    assert job['already_terminal'] is True and job['verified'] is True and job['cancel'] is None


def test_stop_jobs_leaves_a_job_that_stays_running_or_cannot_be_observed_unverified(operator_home, tmp_path):
    autonomous()
    store = _store_with_dir(tmp_path)
    _journal(store, '300.0', '301.0', '302.0')
    _stop(store)
    scheduler = Scheduler({'300.0': 'running', '301.0': 'running', '302.0': 'running'},
                          stubborn=['300.0'], broken=['301.0'])
    result = batch_jobs.stop_jobs(store, wait_seconds=0, observe_job=scheduler.observe, cancel_job=scheduler.cancel)
    assert result['verified'] is False and result['unverified'] == ['300.0', '301.0']
    by_job = {j['job']: j for j in result['jobs']}
    assert by_job['300.0']['verified'] is False and by_job['300.0']['after']['state'] == 'running'
    assert by_job['301.0']['verified'] is False and 'scheduler unreachable' in by_job['301.0']['error']
    assert by_job['302.0']['verified'] is True
    assert scheduler.cancelled == ['300.0', '302.0']
    assert store.scan(batch_jobs.STOP)[-1]['verified'] is False


def _drive_stop(store, monkeypatch, capsys, scheduler, *args):
    from ravel.controller.authority import cli
    from ravel.workflow import wms_site
    monkeypatch.setattr(common, 'open_store', lambda identifier: store)
    monkeypatch.setattr(wms_site, 'observe_job', scheduler.observe)
    monkeypatch.setattr(wms_site, 'cancel_job', scheduler.cancel)
    monkeypatch.setattr(wms_site, 'hold_reason', scheduler.hold_reason)
    code = cli.main(['stop', '--run', store.run_id, '--reason', 'operator stop', *args])
    return code, json.loads(capsys.readouterr().out)


def test_the_operator_stop_command_drains_the_jobs_and_exits_zero_when_verified(operator_home, tmp_path, monkeypatch,
                                                                                capsys, clock):
    autonomous()
    store = _store_with_dir(tmp_path)
    _journal(store, '300.0')
    scheduler = Scheduler({'300.0': 'running'})
    code, result = _drive_stop(store, monkeypatch, capsys, scheduler)
    assert code == 0
    assert result['batch_jobs']['verified'] is True and result['batch_jobs']['unverified'] == []
    assert scheduler.cancelled == ['300.0'] and result['kind'] == 'stop'


def test_the_operator_stop_command_exits_three_when_a_job_never_ends(operator_home, tmp_path, monkeypatch, capsys,
                                                                     clock):
    autonomous()
    store = _store_with_dir(tmp_path)
    _journal(store, '300.0')
    scheduler = Scheduler({'300.0': 'running'}, stubborn=['300.0'])
    code, result = _drive_stop(store, monkeypatch, capsys, scheduler)
    assert code == 3
    assert result['batch_jobs']['verified'] is False and result['batch_jobs']['unverified'] == ['300.0']
    assert scheduler.cancelled == ['300.0'] and result['state'] == 'stop_requested'


def test_a_batch_jobs_hold_from_a_route_hook_becomes_the_typed_held_step_reason(tmp_path, monkeypatch):
    from ravel.controller import graph
    name = 'ravel.controller.routes.fictional_batch_hold_route'
    route = types.ModuleType(name)

    def dispatch(step, context, invoke):
        assert context['store'].run_id == 'run-0001'
        raise batch_jobs.BatchJobsHold('batch_jobs_removed', 'the scheduler removed 300.0')
    route.dispatch = dispatch
    monkeypatch.setitem(sys.modules, name, route)
    packet = {'step': {'id': 'reconcile'},
              'context': {'route_dispatch': name, 'run_id': 'run-0001', 'store_root': str(tmp_path / 'store'),
                          'attempt': 1}}
    found = graph.route_dispatch(packet, lambda: pytest.fail('the hook raised before invoking the step'))
    step = found['results']['step']
    assert found['outcome'] == 'held' and step['status'] == 'held' and step['step_id'] == 'reconcile'
    assert step['reason'].startswith('batch_jobs_removed: ')
    assert step['hold']['reason'] == 'batch_jobs_removed'
    assert found['status']['reason'] == step['reason']
    assert recovery.classify(step)['recoverable'] is True


def test_a_parent_stop_drains_its_frozen_child_runs_and_no_unrelated_run(operator_home, tmp_path, clock,
                                                                           monkeypatch):
    from ravel.controller.authority import freeze_child, operator
    autonomous(budgets={'children': 8})
    root = _store_with_dir(tmp_path)
    child = new_store(tmp_path, 'run-0002')
    freeze_child(child, root, {'prompt': 'A fictional child.'})
    other = _store_with_dir(tmp_path, run_id='run-0003')
    stores = {s.run_id: s for s in (root, child, other)}
    real = operator.operator_config
    monkeypatch.setattr(operator, 'operator_config', lambda: {**real(), 'store_root': str(tmp_path / 'store')})
    monkeypatch.setattr(common, 'open_store', lambda name: stores[name])
    _journal(child, '410.0')
    _journal(other, '420.0')
    scheduler = Scheduler({'410.0': 'running', '420.0': 'running'})
    control = _stop(root)
    with pytest.raises(AuthorityRefused):  # the child alone has no stop of its own to drain for
        batch_jobs.stop_jobs(child, observe_job=scheduler.observe, cancel_job=scheduler.cancel)
    result = batch_jobs.stop_jobs(root, observe_job=scheduler.observe, cancel_job=scheduler.cancel)
    assert result['verified'] is True and result['jobs'] == []
    [drained] = result['descendants']
    assert drained['run_id'] == child.run_id and drained['verified'] is True
    assert scheduler.cancelled == ['410.0'], 'only the child run journalled job is removed'
    assert [r['control'] for r in child.scan(batch_jobs.STOP)] == [control['id']]
    assert other.scan(batch_jobs.STOP) == []
