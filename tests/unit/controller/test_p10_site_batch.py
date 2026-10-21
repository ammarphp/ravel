"""One site capability for a workflow manager's batch jobs: an approved job count, never a pre-approval inspection.

The workflow manager writes each jobscript at run time, so the plan cannot pin its bytes. The capability
bounds the job count, the rules the adoption names and the site profile; each submission must be an
ordinary jobscript of the approved workflow directory whose (rule, outputs) job is distinct, and its frozen
bytes are journalled. The scheduler and the capability verifier are inert stand-ins here.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ravel.controller.routes.study import site
from ravel.controller.confine import capability as real_capability
from ravel.workflow import wms_launch

PROFILE = 'c' * 64


class Store:
    def __init__(self, run_id='fictional', *, root=None):
        self.run_id = run_id
        self.root = Path(root or '.')
        self.rows = []

    def append(self, kind, record):
        json.dumps(record, allow_nan=False)
        record_id = f'{kind}-{len(self.rows) + 1:06d}'
        self.rows.append({'id': record_id, 'kind': kind, 'record': deepcopy(record)})
        return record_id

    def scan(self, kind):
        return [deepcopy(row) for row in self.rows if row['kind'] == kind]

    def read(self, kind, record_id):
        return next(deepcopy(row) for row in self.rows if row['kind'] == kind and row['id'] == record_id)

    def path(self, *parts):
        return self.root.joinpath(*parts)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _records(store, kind):
    return [row['record'] for row in store.scan(kind)]


def _jobscript(folder, name, rule, outputs):
    path = folder / name
    properties = {'rule': rule, 'output': outputs, 'threads': 1, 'type': 'single'}
    path.write_text('#!/bin/sh\n# properties = ' + json.dumps(properties) + '\nexit 0\n')
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    run = root / 'run'
    work = run / 'children' / 'study.workflow' / 'work'
    scripts_dir = work / '.snakemake' / 'tmp.inert'
    scripts_dir.mkdir(parents=True)
    scripts = [_jobscript(scripts_dir, f'snakejob.point.{index}.sh', 'point', [f'output/point-{index}.json'])
               for index in range(3)]
    state = {'stop': 'running', 'tokens': {}, 'launches': {}, 'submissions': {}, 'effects': []}
    authority = ModuleType('ravel.controller.authority')
    authority.stop_state = lambda store: state['stop']
    authority.request = lambda store, kind, subject, bounds: {'pending': 'recorded notification'}
    confine = ModuleType('ravel.controller.confine')
    confine.capability = real_capability

    def mint(store, launch_id, scope):
        assert set(scope) <= {'workflow_dir', 'tasks', 'rules', 'max_jobs', 'profile_sha256', 'resource_maxima'}
        token = 'inert-token-' + launch_id
        if token in state['tokens']:
            raise ValueError('launch already minted')
        state['tokens'][token] = deepcopy(scope)
        state['launches'][token] = launch_id
        return token

    def verify(token, jobscript, *, store=None):
        if token not in state['tokens']:
            raise ValueError('missing capability')
        claim = state['tokens'][token]
        used = state['submissions'].get(token, 0)
        if used >= claim['max_jobs']:
            raise ValueError('capability job budget exhausted: all were submitted')
        state['submissions'][token] = used + 1
        frozen = store.path('frozen', f'{token}-{used}', 'job.sh')
        frozen.parent.mkdir(parents=True)
        frozen.write_bytes(Path(jobscript).read_bytes())
        sha = _sha(jobscript)
        store.append('wms-submission', {'launch_id': state['launches'][token], 'jobscript_sha256': sha})
        return {'snapshot_path': str(frozen), 'jobscript_sha256': sha, 'submissions': used + 1}

    confine.mint_capability = mint
    confine.verify_capability = verify
    sink = ModuleType('ravel.controller.sink')
    sink.bounded_end = lambda store, reason: {'receipt_id': store.append('qualified-receipt', {'reason': reason}),
                                              'qualified': True}
    import ravel.controller
    for name, module in [('authority', authority), ('confine', confine), ('sink', sink)]:
        monkeypatch.setitem(sys.modules, 'ravel.controller.' + name, module)
        monkeypatch.setattr(ravel.controller, name, module, raising=False)
    store = Store(root=root / 'store')
    spec = {'id': 'operate', 'kind': 'operate', 'budget': {'wall_seconds': 10},
            'parameters': {'wms_scope': {'workflow_dir': str(work), 'max_jobs': 3, 'rules': ['all', 'point'],
                                         'profile_sha256': PROFILE},
                           'launch': {'batch': 3}}}
    context = {'run_dir': str(run), 'plan_sha256': 'a' * 64, 'site_budget': 10}

    def submit(snapshot):
        state['effects'].append(str(snapshot))
        return f'{99 + len(state["effects"])}.0'
    return {'store': store, 'spec': spec, 'context': context, 'state': state, 'scripts': scripts,
            'run': run, 'work': work, 'scripts_dir': scripts_dir, 'submit': submit}


def _submit(script, submit, **options):
    """The broker's call: one admission with the pinned profile it revalidated, then the submit."""
    return wms_launch.controller_submission(script, submit, profile_sha256=options.pop('profile_sha256', PROFILE),
                                            **options)


def _dispatch(env, body):
    def invoke():
        body()
        return {'status': 'completed', 'step_id': env['spec']['id'], 'outputs': []}
    return site.dispatch(env['store'], env['spec'], env['context'], invoke)


def test_one_capability_admits_each_distinct_batch_job_once_within_its_count(env):
    store, submit = env['store'], env['submit']
    jobs = []
    outcome = _dispatch(env, lambda: jobs.extend(
        _submit(script, submit) for script in env['scripts']))
    assert outcome['status'] == 'completed' and jobs == ['100.0', '101.0', '102.0']
    capability = _records(store, 'study-site-capability')
    assert len(capability) == 1 and capability[0]['scope'] == env['spec']['parameters']['wms_scope']
    reserved = [r for r in _records(store, 'study-site') if r['event'] == 'reserved']
    assert len(reserved) == 1 and reserved[0]['batch'] == 3
    assert not {'jobscript', 'jobscripts'} & set(reserved[0])
    admitted = _records(store, site.BATCH_JOB)
    assert [(row['rule'], row['output']) for row in admitted] == [
        ('point', [f'output/point-{index}.json']) for index in range(3)]
    assert [row['jobscript_sha256'] for row in admitted] == [_sha(s) for s in env['scripts']]
    assert [row['job'] for row in _records(store, 'study-site-job')] == jobs
    assert len(_records(store, 'wms-submission')) == 3


def test_batch_refusals_have_no_scheduler_effect(env):
    store, state, scripts, submit = env['store'], env['state'], env['scripts'], env['submit']
    folder = env['scripts_dir']
    outside = _jobscript(env['run'], 'outside.sh', 'point', ['output/point-9.json'])
    foreign_rule = _jobscript(folder, 'snakejob.other.sh', 'unlisted', ['output/other.json'])
    no_properties = folder / 'snakejob.bare.sh'
    no_properties.write_text('#!/bin/sh\nexit 0\n')
    twin = _jobscript(folder, 'snakejob.twin.sh', 'point', ['output/point-0.json'])
    link = folder / 'snakejob.link.sh'
    link.symlink_to(scripts[1])

    def body():
        _submit(scripts[0], submit)
        assert len(state['effects']) == 1
        with pytest.raises(ValueError, match='already submitted'):
            _submit(twin, submit)
        with pytest.raises(ValueError, match='ordinary file of the approved workflow directory'):
            _submit(outside, submit)
        with pytest.raises(ValueError, match='ordinary file of the approved workflow directory'):
            _submit(link, submit)
        with pytest.raises(ValueError, match='does not name'):
            _submit(foreign_rule, submit)
        with pytest.raises(ValueError, match='properties'):
            _submit(no_properties, submit)
        state['stop'] = 'stop_requested'
        with pytest.raises(ValueError, match='operator state: stop_requested'):
            _submit(scripts[1], submit)
        state['stop'] = 'running'
        assert len(state['effects']) == 1
        _submit(scripts[1], submit)
        _submit(scripts[2], submit)
        extra = _jobscript(folder, 'snakejob.point.3.sh', 'point', ['output/point-3.json'])
        with pytest.raises(ValueError, match='all were submitted'):
            _submit(extra, submit)
    assert _dispatch(env, body)['status'] == 'completed'
    assert len(state['effects']) == 3 and len(_records(store, 'study-site-job')) == 3
    assert len(_records(store, site.BATCH_JOB)) == 3


@pytest.mark.parametrize('change, message', [
    ('max_jobs', 'max_jobs equal to its approved job count'),
    ('count', 'positive approved job count'),
    ('rules', 'distinct rules'),
    ('profile', 'pins its site profile'),
    ('pins', 'no jobscript pins'),
])
def test_dispatch_refuses_an_invalid_batch_scope_before_any_mint(env, change, message):
    store, state, spec = env['store'], env['state'], env['spec']
    scope, launch = spec['parameters']['wms_scope'], spec['parameters']['launch']
    if change == 'max_jobs':
        scope['max_jobs'] = 2
    elif change == 'count':
        launch['batch'] = 0
    elif change == 'rules':
        scope['rules'] = ['point', 'point']
    elif change == 'profile':
        del scope['profile_sha256']
    else:
        launch['jobscript'] = {'path': env['scripts'][0].name, 'sha256': _sha(env['scripts'][0])}
    with pytest.raises(ValueError, match=message):
        site.dispatch(store, spec, env['context'], lambda: pytest.fail('an invalid scope reached invocation'))
    assert store.rows == [] and state['tokens'] == {} and state['effects'] == []


def test_restart_rebuilds_the_batch_launch_and_never_resubmits(env):
    store, state, scripts, submit = env['store'], env['state'], env['scripts'], env['submit']

    def body():
        _submit(scripts[0], submit)
        raise RuntimeError('interrupted after one submission')
    with pytest.raises(RuntimeError, match='interrupted'):
        _dispatch(env, body)
    restarted = Store(root=store.root)
    restarted.rows = deepcopy(store.rows)
    held = site.dispatch(restarted, env['spec'], env['context'], lambda: pytest.fail('restart cannot resubmit'))
    assert held == {'status': 'held', 'reason': 'reconcile the original dispatch; no resubmission',
                    'launch_id': 'operate'}
    assert len(state['effects']) == 1 and len(_records(restarted, site.BATCH_JOB)) == 1


def _adopted_context(env, store, *, outputs=None, inspection_outputs=('output/point-0.json', 'output/point-1.json')):
    """The prepared and operated records ``await_batch`` reads, through real custody-shaped rows."""
    run, work = env['run'], env['work']
    workflow_root = work.parent
    adoption = workflow_root / 'adoption' / 'adoption.json'
    adoption.parent.mkdir(parents=True)
    adoption.write_text(json.dumps({'workdir': str(work), 'outputs': outputs}))
    inspection = run / 'children' / 'study' / 'outputs' / 'attempt-1' / 'external-workflow' / 'inspection' / 'inspection.json'
    inspection.parent.mkdir(parents=True)
    inspection.write_text(json.dumps({'summary': [{'output_file': name} for name in inspection_outputs]}))
    preparation = {'site_launch': {'batch': 2}, 'workflow_root': str(workflow_root),
                   'adoption': {'path': str(adoption), 'sha256': _sha(adoption)}}
    receipt = {'kind': 'ordinary-study-receipt',
               'result': {'inspection': {'path': str(inspection), 'sha256': _sha(inspection), 'size': 1}}}
    for step, name, value in (('prepare-child', 'preparation.json', preparation), ('operate', 'result.json', receipt)):
        target = run / 'steps' / step / 'attempts' / '1' / 'outputs' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))
        store.append('custody', {'artifact': f'{step}:outputs/{name}', 'step_id': step, 'path': f'outputs/{name}',
                                 'destination': f'steps/{step}/attempts/1/outputs/{name}', 'attempt': 1,
                                 'sha256': _sha(target), 'status': 'accepted'})
    for index in range(2):
        store.append('study-site-job', {'launch_id': 'operate', 'job': f'{200 + index}.0', 'scheduler': 'htcondor',
                                        'jobscript_sha256': str(index) * 64})
    plan = {'steps': [{'id': 'operate'}, {'id': 'reconcile'}], 'parameters': {'study_binding': {'max_seconds': 60}}}
    return {'run_dir': str(run), 'attempt': 1, 'plan': plan}, adoption


@pytest.fixture
def awaiting(env, monkeypatch):
    from ravel.controller.routes.study import contracts
    observed = {'200.0': ['running', 'exited 0'], '201.0': ['exited 0']}

    def observe(job):
        states = observed[job]
        text = states.pop(0) if len(states) > 1 else states[0]
        return {'state': text.split()[0], 'raw': '4 0' if text.startswith('exited 0') else ('4 1' if text.startswith('exited') else '2')}
    from ravel.workflow import wms_site
    monkeypatch.setattr(wms_site, 'observe_job', observe)
    monkeypatch.setattr(wms_site, 'cancel_job', lambda job: pytest.fail('a wait never cancels'))

    def adopted_json(context, artifact):
        store = context['store']
        row = [r for r in _records(store, 'custody') if r['artifact'] == artifact][-1]
        path = Path(context['run_dir']) / row['destination']
        return json.loads(path.read_text()), row
    monkeypatch.setattr(contracts, 'adopted_json', adopted_json)
    return observed


def test_await_batch_waits_for_every_job_then_adopts_the_inspected_outputs(env, awaiting):
    store = Store(root=env['store'].root)
    context, _ = _adopted_context(env, store)
    for index in range(2):
        (env['work'] / 'output').mkdir(exist_ok=True)
        (env['work'] / 'output' / f'point-{index}.json').write_text(json.dumps({'point': index}))
    sleeps = []
    adoption = site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0, sleep=sleeps.append)
    assert sleeps == [0], 'one poll saw a running job; the next saw every job exited'
    assert adoption['event'] == 'fetched' and adoption['scientific_acceptance_inferred'] is False
    names = [row['name'] for row in adoption['receipt']['outputs']]
    assert names == ['output/point-0.json', 'output/point-1.json']
    delivered = Path(env['run']) / 'steps' / 'reconcile' / 'attempts' / '1' / 'delivered'
    assert all((delivered / name).is_file() for name in names)
    assert [row['job'] for row in adoption['receipt']['jobs']] == ['200.0', '201.0']
    again = site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0,
                             sleep=lambda seconds: pytest.fail('a restart never waits or fetches twice'))
    assert again == adoption and len(_records(store, 'study-adoption')) == 1


def test_await_batch_holds_on_a_failed_job(env, awaiting):
    from ravel.controller.routes.study.runtime import StudyHold
    store = Store(root=env['store'].root)
    context, _ = _adopted_context(env, store)
    awaiting['200.0'] = ['exited 1']
    with pytest.raises(StudyHold, match='without success'):
        site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0, sleep=lambda seconds: None)
    assert [row['event'] for row in _records(store, 'study-adoption')] == ['failed']
    with pytest.raises(StudyHold, match='without success'):
        site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0, sleep=lambda seconds: None)
    assert not [row for row in _records(store, 'study-adoption') if row['event'] == 'fetched']


def test_await_batch_holds_on_an_adoption_changed_after_preparation(env, awaiting):
    from ravel.controller.routes.study.runtime import StudyHold
    store = Store(root=env['store'].root)
    context, adoption = _adopted_context(env, store)
    adoption.write_text(json.dumps({'workdir': str(env['work']), 'outputs': ['changed']}))
    with pytest.raises(StudyHold, match='adoption record changed'):
        site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0, sleep=lambda seconds: None)
    assert not [row for row in _records(store, 'study-adoption') if row['event'] == 'fetched']


def test_await_batch_honours_stop_and_the_journalled_count(env, awaiting):
    from ravel.controller.routes.study.runtime import StudyHold
    store = Store(root=env['store'].root)
    context, _ = _adopted_context(env, store)
    env['state']['stop'] = 'stop_requested'
    with pytest.raises(StudyHold, match='operator state: stop_requested'):
        site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0, sleep=lambda seconds: None)
    env['state']['stop'] = 'running'
    store.append('study-site-job', {'launch_id': 'operate', 'job': '202.0', 'jobscript_sha256': '2' * 64})
    with pytest.raises(StudyHold, match='3 batch job'):
        site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0, sleep=lambda seconds: None)


def _observer_boundary(monkeypatch):
    """The authority stand-in has no autonomy service: record the observer's condition reports instead."""
    from ravel.controller import batch_jobs
    from ravel.workflow import wms_site
    reported = []
    monkeypatch.setattr(batch_jobs, '_report', lambda store, code, jobs, evidence: reported.append(
        ('open', code, sorted(jobs))) or {'reported': True, 'wait': None, 'notification_error': None})
    monkeypatch.setattr(batch_jobs, '_clear', lambda store, code, evidence: reported.append(('cleared', code)) or True)
    monkeypatch.setattr(wms_site, 'hold_reason', lambda job: {'code': 7, 'raw': '7'})
    return reported


def test_await_batch_waits_on_a_held_job_and_continues_once_it_is_released(env, awaiting, monkeypatch):
    reported = _observer_boundary(monkeypatch)
    store = Store(root=env['store'].root)
    context, _ = _adopted_context(env, store)
    for index in range(2):
        (env['work'] / 'output').mkdir(exist_ok=True)
        (env['work'] / 'output' / f'point-{index}.json').write_text(json.dumps({'point': index}))
    awaiting['200.0'] = ['held', 'running', 'exited 0']
    sleeps = []
    adoption = site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0, sleep=sleeps.append)
    assert adoption['event'] == 'fetched' and len(sleeps) == 2
    assert reported == [('open', 'jobs_held', ['200.0']), ('cleared', 'jobs_held')]
    decisions = _records(store, 'batch-recovery-decision')
    assert [(d['decision'], d['jobs']) for d in decisions] == [('await_release', ['200.0']), ('released', [])]
    assert decisions[0]['evidence']['jobs'][0]['observation']['hold'] == {'code': 7, 'raw': '7'}
    assert decisions[0]['controller_never'] == ['release', 'edit', 'resubmit']


def test_await_batch_holds_typed_for_recovery_when_the_scheduler_removed_a_job(env, awaiting, monkeypatch):
    from ravel.controller import batch_jobs, recovery
    reported = _observer_boundary(monkeypatch)
    store = Store(root=env['store'].root)
    context, _ = _adopted_context(env, store)
    awaiting['200.0'] = ['cancelled']
    with pytest.raises(batch_jobs.BatchJobsHold) as held:
        site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0, sleep=lambda seconds: None)
    assert held.value.code == 'batch_jobs_removed'
    assert recovery.classify({'status': 'held', 'reason': str(held.value)})['recoverable'] is True
    assert reported == [('open', 'jobs_removed', ['200.0'])]
    assert [d['decision'] for d in _records(store, 'batch-recovery-decision')] == ['recover']
    # A restart sees the removal recorded terminal and still holds typed, never as a plain failure.
    with pytest.raises(batch_jobs.BatchJobsHold) as again:
        site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0, sleep=lambda seconds: None)
    assert again.value.code == 'batch_jobs_removed'
    assert [d['decision'] for d in _records(store, 'batch-recovery-decision')] == ['recover']
    assert not [row for row in _records(store, 'study-adoption') if row['event'] == 'fetched']


def test_a_job_the_run_cancelled_itself_is_a_plain_failure_not_a_removal(env, awaiting, monkeypatch):
    from ravel.controller.routes.study.runtime import StudyHold
    reported = _observer_boundary(monkeypatch)
    store = Store(root=env['store'].root)
    context, _ = _adopted_context(env, store)
    store.append('study-site-job-state', {'launch_id': 'operate', 'job': '200.0', 'drain': True, 'cancelled': True,
                                          'cancel': {'returncode': 0}, 'observation': {'state': 'cancelled'}})
    with pytest.raises(StudyHold, match='without success'):
        site.await_batch(store, {'id': 'reconcile'}, context, poll_seconds=0, sleep=lambda seconds: None)
    assert reported == [] and _records(store, 'batch-recovery-decision') == []


def test_a_batch_plan_reviews_the_submitted_operation_before_its_reconciliation():
    from ravel.controller.routes import study
    route = Path(study.__file__).resolve().parents[3] / 'data/controller/routes/study_site.json'
    spec = json.loads(route.read_text())
    steps = deepcopy(spec['steps'])
    assert study.batch_order(steps) is steps
    nodes = {node['id']: node for node in steps}
    assert nodes['operation-review']['depends_on'] == ['operate']
    assert nodes['reconcile']['depends_on'] == ['operate', 'operation-review']
    assert nodes['reconcile']['rung'] == 'full', 'the review\'s go-ahead gates the wait for the jobs'
    original = {node['id']: node for node in spec['steps']}
    assert original['reconcile']['depends_on'] == ['operate'], 'a single driver job keeps the route order'
    assert original['operation-review']['depends_on'] == ['operate', 'reconcile']
    with pytest.raises(ValueError, match='operate, operation-review and reconcile'):
        study.batch_order([node for node in deepcopy(spec['steps']) if node['id'] != 'reconcile'])


def test_reconciliation_waits_for_jobs_only_in_a_batch_plan(monkeypatch):
    from ravel.controller.routes import study
    waited = []
    monkeypatch.setattr(site, 'await_batch', lambda store, step, context: waited.append(step['id']))
    batch = {'route': 'study.site', 'steps': [{'id': 'operate', 'parameters': {'launch': {'batch': 2}}}]}
    assert study.dispatch({'id': 'reconcile'}, {'store': Store(), 'plan': batch}, lambda: 'invoked') == 'invoked'
    assert waited == ['reconcile']
    driver = {'route': 'study.site', 'steps': [{'id': 'operate', 'parameters': {'launch': {'jobscript': {}}}}]}
    assert study.dispatch({'id': 'reconcile'}, {'store': Store(), 'plan': driver}, lambda: 'invoked') == 'invoked'
    assert waited == ['reconcile'], 'the driver-job path reconciles as before'
