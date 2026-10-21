"""One site capability covering N plan-pinned jobscripts, with an inert scheduler."""
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
from ravel.controller.store import RunStore
from ravel.workflow import wms_launch, wms_policy


class Store:
    def __init__(self, run_id='fictional', *, root=None):
        self.run_id = run_id
        self.root = Path(root or '.')
        self.rows = []

    def append(self, kind, record):
        json.dumps(record, allow_nan=False)
        record_id = str(len(self.rows) + 1)
        self.rows.append({'id': record_id, 'kind': kind, 'record': deepcopy(record)})
        return record_id

    def scan(self, kind):
        return [deepcopy(row) for row in self.rows if row['kind'] == kind]

    def path(self, *parts):
        return self.root.joinpath(*parts)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _records(store, kind):
    return [row['record'] for row in store.scan(kind)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    run = root / 'run'
    run.mkdir()
    scripts = []
    for index in range(3):
        script = run / f'job-{index}.sh'
        script.write_text(f'inert payload {index}\n')
        scripts.append(script)
    state = {'stop': 'running', 'tokens': {}, 'launches': {}, 'submissions': {}, 'effects': [],
             'notifications': []}
    authority = ModuleType('ravel.controller.authority')
    authority.stop_state = lambda store: state['stop']
    def request(store, kind, subject, bounds):
        state['notifications'].append(kind)
        return {'pending': 'recorded notification'}
    authority.request = request
    confine = ModuleType('ravel.controller.confine')
    def mint(store, launch_id, scope):
        assert set(scope) <= {'workflow_dir', 'tasks', 'rules', 'max_jobs', 'profile_sha256',
                              'jobscript_sha256', 'resource_maxima'}
        assert Path(scope['workflow_dir']).is_absolute()
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
        sha = _sha(jobscript)
        if 'jobscript_sha256' in claim and sha != claim['jobscript_sha256']:
            raise ValueError('capability belongs to other script bytes')
        used = state['submissions'].get(token, 0)
        if used >= claim.get('max_jobs', 1):
            raise ValueError('capability job budget exhausted')
        state['submissions'][token] = used + 1
        frozen = store.path('frozen', f'{token}-{used}', 'job.sh')
        frozen.parent.mkdir(parents=True)
        frozen.write_bytes(Path(jobscript).read_bytes())
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
    spec = {'id': 'launch-a', 'kind': 'operate', 'budget': {'wall_seconds': 10},
            'parameters': {'wms_scope': {'workflow_dir': str(run), 'max_jobs': 3},
                           'launch': {'jobscripts': [{'path': s.name, 'sha256': _sha(s)} for s in scripts]}}}
    context = {'run_dir': str(run), 'plan_sha256': 'a' * 64, 'site_budget': 10}
    def submit(snapshot):
        state['effects'].append(str(snapshot))
        return f'{99 + len(state["effects"])}.0'
    return {'store': store, 'spec': spec, 'context': context, 'state': state, 'scripts': scripts,
            'run': run, 'submit': submit}


def _dispatch(env, body):
    def invoke():
        body()
        return {'status': 'completed', 'step_id': env['spec']['id'], 'outputs': []}
    return site.dispatch(env['store'], env['spec'], env['context'], invoke)


def test_one_capability_admits_each_pinned_jobscript_once(env):
    store, submit = env['store'], env['submit']
    jobs = []
    outcome = _dispatch(env, lambda: jobs.extend(
        wms_launch.controller_submission(script, submit) for script in env['scripts']))
    assert outcome['status'] == 'completed'
    assert jobs == ['100.0', '101.0', '102.0'] and len(env['state']['effects']) == 3
    capability = _records(store, 'study-site-capability')
    assert len(capability) == 1
    assert capability[0]['scope'] == {'workflow_dir': str(env['run']), 'max_jobs': 3}
    reserved = [r for r in _records(store, 'study-site') if r['event'] == 'reserved']
    assert len(reserved) == 1 and 'jobscript' not in reserved[0]
    assert reserved[0]['jobscripts'] == env['spec']['parameters']['launch']['jobscripts']
    rows = _records(store, 'study-site-job')
    assert [r['job'] for r in rows] == jobs
    assert {r['jobscript_sha256'] for r in rows} == {_sha(s) for s in env['scripts']}
    assert all(r['scheduler'] == 'htcondor' and r['launch_id'] == 'launch-a' for r in rows)
    assert [r['submissions'] for r in rows] == [1, 2, 3]
    assert [r['outcome']['status'] for r in _records(store, 'study-site') if r['event'] == 'outcome'] == ['completed']


def test_refusals_inside_the_trusted_launch_have_no_scheduler_effect(env):
    store, state, scripts, submit = env['store'], env['state'], env['scripts'], env['submit']
    stray = env['run'] / 'unpinned.sh'
    stray.write_text('inert unpinned payload\n')
    def body():
        wms_launch.controller_submission(scripts[0], submit)
        assert len(state['effects']) == 1
        with pytest.raises(ValueError, match='already submitted'):
            wms_launch.controller_submission(scripts[0], submit)
        with pytest.raises(ValueError, match='not one of the approved'):
            wms_launch.controller_submission(stray, submit)
        original = scripts[1].read_bytes()
        scripts[1].write_bytes(b'changed payload\n')
        with pytest.raises(ValueError, match='exact bytes'):
            wms_launch.controller_submission(scripts[1], submit)
        scripts[1].write_bytes(original)
        state['stop'] = 'stop_requested'
        with pytest.raises(ValueError, match='operator state: stop_requested'):
            wms_launch.controller_submission(scripts[1], submit)
        state['stop'] = 'running'
        assert len(state['effects']) == 1
        wms_launch.controller_submission(scripts[1], submit)
        wms_launch.controller_submission(scripts[2], submit)
        with pytest.raises(ValueError, match='already submitted|all were submitted|budget exhausted'):
            wms_launch.controller_submission(scripts[2], submit)
    assert _dispatch(env, body)['status'] == 'completed'
    assert len(state['effects']) == 3 and len(_records(store, 'study-site-job')) == 3
    assert state['submissions'] == {'inert-token-launch-a': 3}
    assert len(_records(store, 'wms-submission')) == 3


def test_foreign_or_absent_launch_context_is_refused(env):
    store, state, scripts, submit = env['store'], env['state'], env['scripts'], env['submit']
    scope = {'jobscripts': [{'path': str(s), 'sha256': _sha(s)} for s in scripts],
             'capability': {'workflow_dir': str(env['run']), 'max_jobs': 3}}
    with pytest.raises(ValueError, match='trusted launch'):
        wms_launch.controller_submission(scripts[0], submit)
    with site.trusted_launch(store, 'launch-b', 'inert-token-launch-b', scope):
        with pytest.raises(ValueError, match='scope'):
            wms_launch.controller_submission(scripts[0], submit, launch_id='launch-a')
        with pytest.raises(ValueError, match='missing capability'):
            wms_launch.controller_submission(scripts[0], submit)
    with pytest.raises(ValueError, match='trusted launch'):
        site.record_submission({'jobscript_sha256': 'a' * 64}, '1.0')
    assert state['effects'] == [] and store.scan('study-site-job') == [] and store.scan('wms-submission') == []


@pytest.mark.parametrize('change, message', [
    ('max_jobs', 'max_jobs equal to its pinned jobscript count'),
    ('duplicate', 'distinct'),
    ('missing', 'ordinary pinned file'),
    ('both', 'never both'),
])
def test_dispatch_refuses_an_invalid_multi_pin_before_any_mint(env, change, message):
    store, state, spec, run = env['store'], env['state'], env['spec'], env['run']
    pins = spec['parameters']['launch']['jobscripts']
    if change == 'max_jobs':
        spec['parameters']['wms_scope']['max_jobs'] = 2
    elif change == 'duplicate':
        twin = run / 'twin.sh'
        twin.write_bytes(env['scripts'][0].read_bytes())
        pins.append({'path': twin.name, 'sha256': _sha(twin)})
        spec['parameters']['wms_scope']['max_jobs'] = 4
    elif change == 'missing':
        pins[2]['path'] = 'absent.sh'
    else:
        spec['parameters']['launch']['jobscript'] = deepcopy(pins[0])
    with pytest.raises(ValueError, match=message):
        site.dispatch(store, spec, env['context'], lambda: pytest.fail('invalid pins reached invocation'))
    assert store.rows == [] and state['tokens'] == {} and state['effects'] == []


def test_restart_after_dispatch_started_never_resubmits(env):
    store, state, scripts, submit = env['store'], env['state'], env['scripts'], env['submit']
    def body():
        wms_launch.controller_submission(scripts[0], submit)
        raise RuntimeError('interrupted after one submission')
    with pytest.raises(RuntimeError, match='interrupted'):
        _dispatch(env, body)
    restarted = Store(root=store.root)
    restarted.rows = deepcopy(store.rows)
    held = site.dispatch(restarted, env['spec'], env['context'],
                         lambda: pytest.fail('restart cannot resubmit'))
    assert held == {'status': 'held', 'reason': 'reconcile the original dispatch; no resubmission',
                    'launch_id': 'launch-a'}
    assert len(state['effects']) == 1 and len(_records(restarted, 'study-site-job')) == 1


def test_single_jobscript_path_is_unchanged(env):
    store, state, scripts = env['store'], env['state'], env['scripts']
    spec = env['spec']
    spec['parameters'] = {'wms_scope': {'workflow_dir': str(env['run']), 'max_jobs': 1},
                          'launch': {'jobscript': {'path': scripts[0].name, 'sha256': _sha(scripts[0])}}}
    assert _dispatch(env, lambda: site.require_capability(scripts[0]))['status'] == 'completed'
    reserved = [r for r in _records(store, 'study-site') if r['event'] == 'reserved']
    assert reserved[0]['jobscript'] == spec['parameters']['launch']['jobscript']
    assert 'jobscripts' not in reserved[0]
    assert _records(store, 'study-site-capability')[0]['scope'] == {
        'workflow_dir': str(env['run']), 'max_jobs': 1, 'jobscript_sha256': _sha(scripts[0])}
    assert state['submissions'] == {'inert-token-launch-a': 1}


def test_real_capability_admits_distinct_pins_within_its_job_count(tmp_path, monkeypatch):
    from ravel.controller import authority
    from ravel.controller.confine import runs
    root = tmp_path.resolve()
    store = RunStore('multi-run', root=root / 'protected')
    workflow = root / 'workflow'
    workflow.mkdir()
    scripts = []
    for index in range(3):
        script = workflow / f'job-{index}.sh'
        script.write_text(f'# properties = {{"rule": "task_unit", "threads": 1}}\n# member {index}\nexit 0\n')
        scripts.append(script)
    monkeypatch.setattr(runs, 'store', lambda run_id: pytest.fail('bound store must not use the default root'))
    monkeypatch.setattr(authority, 'stop_state', lambda store: 'running')
    token = real_capability.mint_capability(store, 'launch-one', {'workflow_dir': str(workflow), 'max_jobs': 2})
    scope = {'jobscripts': [{'path': str(s), 'sha256': _sha(s)} for s in scripts],
             'capability': {'workflow_dir': str(workflow), 'max_jobs': 2}}
    effects = []
    def submit(snapshot):
        effects.append(_sha(snapshot))
        return f'{70 + len(effects)}.0'
    with site.trusted_launch(store, 'launch-one', token, scope):
        assert wms_launch.controller_submission(scripts[0], submit) == '71.0'
        assert wms_launch.controller_submission(scripts[1], submit) == '72.0'
        with pytest.raises(ValueError, match='already submitted'):
            wms_launch.controller_submission(scripts[0], submit)
        with pytest.raises(ValueError, match='all were submitted'):
            wms_launch.controller_submission(scripts[2], submit)
    assert effects == [_sha(scripts[0]), _sha(scripts[1])]
    assert len(store.scan('wms-submission')) == 2
    rows = _records(store, 'study-site-job')
    assert [r['job'] for r in rows] == ['71.0', '72.0'] and [r['submissions'] for r in rows] == [1, 2]


def test_reconcile_drains_journalled_scheduler_jobs(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    tools = root / 'bin'
    tools.mkdir()
    removed, leaked = root / 'removed', root / 'leaked'
    programs = {
        'condor_q': f'#!/bin/sh\nif grep -qx "$1" "{removed}" 2>/dev/null; then echo "3 0"; '
                    f'else echo "2 undefined"; fi\n',
        'condor_history': '#!/bin/sh\nexit 0\n',
        'condor_rm': f'#!/bin/sh\necho "$1" >> "{removed}"\n'
                     f'printenv {wms_policy.CAPABILITY_ENV} >> "{leaked}"\nexit 0\n',
    }
    for name, text in programs.items():
        (tools / name).write_text(text)
        (tools / name).chmod(0o700)
    monkeypatch.setenv('PATH', str(tools) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv(wms_policy.CAPABILITY_ENV, 'rwc1.never-exported')
    store = Store(root=root / 'store')
    with site.trusted_launch(store, 'launch-a', 'inert-token', {'jobscripts': [], 'capability': {}}):
        site.record_submission({'jobscript_sha256': 'a' * 64, 'submissions': 1}, '200.0')
        site.record_submission({'jobscript_sha256': 'b' * 64, 'submissions': 2}, '201.0')
    observed = site.reconcile(store, drain=False)
    assert observed['resolved'] is False and not removed.exists()
    assert [j['observation']['state'] for j in observed['jobs']] == ['running', 'running']
    assert not any(j['cancelled'] for j in observed['jobs'])
    drained = site.reconcile(store, drain=True)
    assert drained['resolved'] is True
    assert [(j['job'], j['cancelled'], j['observation']['state']) for j in drained['jobs']] == [
        ('200.0', True, 'cancelled'), ('201.0', True, 'cancelled')]
    assert removed.read_text().splitlines() == ['200.0', '201.0']
    assert leaked.read_text() == ''
    assert len(_records(store, 'study-site-job-state')) == 4
    again = site.reconcile(store, drain=True)
    assert again == {'resolved': True, 'attempts': [], 'jobs': []}
    assert removed.read_text().splitlines() == ['200.0', '201.0']
