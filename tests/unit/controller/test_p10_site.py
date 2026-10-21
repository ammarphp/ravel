"""Capability, restart, budget and drain controls with an inert scheduler."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from ravel.controller.routes.study import site
from ravel.controller.confine import capability as real_capability
from ravel.controller.store import RunStore


def test_dispatch_uses_only_the_supplied_substrate_invoker(env):
    store, spec, context, state, _, _, step = env
    execute = step.run
    step.run = lambda *args: pytest.fail('direct governed entry bypasses substrate receipts')
    calls = []
    def invoke():
        calls.append(spec['id'])
        return execute(store, spec, context)
    assert site.dispatch(store, spec, context, invoke)['status'] == 'completed'
    assert site.dispatch(store, spec, context, invoke)['status'] == 'completed'
    assert calls == ['launch-a'] and state['effects'] == 1


def test_parent_site_token_cannot_authorize_more_than_one_submission(env):
    store, spec, context, state, *_ = env
    spec['parameters']['wms_scope']['max_jobs'] = 2
    with pytest.raises(ValueError, match='one scheduler submission'):
        site.dispatch(store, spec, context, lambda: pytest.fail('invalid scope reached invocation'))
    assert store.scan('study-site') == [] and state['tokens'] == {}


def test_adapter_exposes_packet_dispatch_recovery_and_stop_hooks(env, monkeypatch):
    from ravel.controller.routes import study
    from ravel.controller.routes.study import runtime, remote
    store, spec, context, state, *_ = env
    context.update(store=store, plan={'route': 'study.site', 'steps': []})
    assert study.packet_context(spec, context) == runtime.packet_context(context)
    assert study.dispatch(spec, context, lambda: {'status': 'completed'})['status'] == 'completed'
    plan = {'plan_sha256': 'b' * 64}
    handle = {'plan_sha256': 'b' * 64, 'backend': 'inert', 'remote': 'remote-a'}
    site.track(store, spec['id'], plan, handle)
    _backend(monkeypatch, state)
    monkeypatch.setattr(remote, 'capture', lambda context: [])
    study.recover(context)
    assert state['recoveries'] == ['remote-a'] and state['cancelled'] == []
    study.ending('bounded work', context)
    assert state['cancelled'] == ['remote-a']


def test_submission_crash_recovers_recorded_identity_without_second_invocation(env, monkeypatch):
    from ravel.controller.routes import study
    store, spec, context, state, *_ = env
    context.update(store=store, plan={'route': 'study.site', 'steps': []})
    calls = []
    def invoke():
        site.require_capability(Path(context['run_dir']) / 'jobscript')
        calls.append('submitted')
        site.track(store, spec['id'], {'plan_sha256': 'b' * 64},
            {'plan_sha256': 'b' * 64, 'backend': 'inert', 'remote': 'remote-a'})
        raise RuntimeError('interrupted after durable submission')
    with pytest.raises(RuntimeError, match='interrupted'):
        site.dispatch(store, spec, context, invoke)
    restarted = Store(root=store.root)
    restarted.rows = deepcopy(store.rows)
    context['store'] = restarted
    _backend(monkeypatch, state)
    study.recover(context)
    assert site.dispatch(restarted, spec, context, invoke)['status'] == 'held'
    state['stop'] = 'stop_requested'
    study.ending('operator stop', context)
    assert calls == ['submitted'] and state['submissions'] == {'inert-token-launch-a': 1}
    assert state['cancelled'] == ['remote-a']
    assert len(restarted.scan('study-remote')) == 1


@pytest.mark.parametrize('target_kind', ['scratch', 'symlink'])
def test_controller_watcher_requires_durable_target(tmp_path, monkeypatch, target_kind):
    from ravel.workflow import preflight_watcher as watcher
    from ravel.controller import store as stores
    root = tmp_path.resolve() / 'run'
    root.mkdir()
    target = root / ('scratch/fire.sh' if target_kind == 'scratch' else 'scripts/fire.sh')
    target.parent.mkdir()
    target.write_text('#!/bin/sh\nexit 0\n')
    if target_kind == 'symlink':
        link = root / 'linked.sh'
        link.symlink_to(target)
        target = link
    monkeypatch.setattr(stores, 'controller_owned', lambda path: 'fixture-run')
    rec, _ = watcher.arm_watcher(str(root), 'completion', 'sh ' + str(target), str(target))
    assert rec['verdict'] == 'fail' and rec['refusal_codes'] == ['watcher_target_not_durable']


def test_controller_watcher_accepts_a_durable_retained_input(tmp_path, monkeypatch):
    # The positive control: a regular, nonlinked run member that the controller retained as an accepted input.
    import fakes
    from ravel.workflow import preflight_watcher as watcher
    fakes.isolate(tmp_path, monkeypatch)
    store = RunStore.create(tmp_path / 'run', run_id='durable-watcher')
    target = store.run_dir / 'inputs' / 'fire.sh'
    target.parent.mkdir()
    target.write_text('#!/bin/sh\nexit 0\n')
    store.append('custody', {'artifact': 'prepare:fire.sh', 'destination': 'inputs/fire.sh', 'status': 'accepted',
                             'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    rec, _ = watcher.arm_watcher(str(store.run_dir), 'completion', 'sh ' + str(target), str(target))
    assert rec['verdict'] == 'pass' and rec['refusal_codes'] == []


def test_generation_recipe_pin_is_checked_before_invocation(tmp_path, monkeypatch):
    from ravel.controller.routes import study
    monkeypatch.setattr(study, 'gate', lambda *args: [])
    monkeypatch.setattr(study, '_tables', lambda: ({'produce': {'effects': ['generates_events']}}, {}))
    context = {'run_dir': str(tmp_path.resolve()), 'plan': {'parameters': {}}}
    spec = {'id': 'generate', 'operation': 'produce'}
    assert study.admit(spec, context)[0]['code'] == 'external_recipe_missing'
    recipe = tmp_path / 'recipe.json'
    recipe.write_text('{"source": "retained input"}')
    context['plan']['parameters']['external_recipe'] = {
        'path': recipe.name, 'sha256': hashlib.sha256(recipe.read_bytes()).hexdigest()}
    assert study.admit(spec, context) == []
    recipe.write_text('{}')
    assert study.admit(spec, context)[0]['code'] == 'external_recipe_missing'


def test_real_capability_uses_bound_store_and_consumes_only_once(tmp_path, monkeypatch):
    from ravel.controller.confine import runs
    store = RunStore('capability-run', root=tmp_path.resolve() / 'protected')
    workflow = tmp_path.resolve() / 'workflow'
    workflow.mkdir()
    script = workflow / 'job.sh'
    script.write_text('# properties = {"rule": "task_unit", "threads": 1}\nexit 0\n')
    sha = hashlib.sha256(script.read_bytes()).hexdigest()
    token = real_capability.mint_capability(store, 'launch-one',
        {'workflow_dir': str(workflow), 'tasks': ['unit'], 'max_jobs': 1, 'jobscript_sha256': sha})
    monkeypatch.setattr(runs, 'store', lambda run_id: pytest.fail('bound store must not use the default root'))
    scope = {'jobscript': {'path': str(script), 'sha256': sha}}
    with site.trusted_launch(store, 'launch-one', token, scope):
        assert site.require_capability(script)['submissions'] == 1
        with pytest.raises(ValueError, match='all were submitted'):
            site.require_capability(script)
    assert len(store.scan('wms-submission')) == 1


def test_scheduler_executable_rejects_invalid_tokens_and_accepts_one_durable_token(tmp_path, monkeypatch):
    from ravel.workflow import wms_policy
    from ravel.controller.confine import runs
    root = tmp_path.resolve()
    store = RunStore('capability-run', root=root / 'protected')
    workflow = root / 'workflow'
    workflow.mkdir()
    script = workflow / 'job.sh'
    script.write_text('# properties = {"rule": "task_unit", "threads": 1}\nexit 0\n')
    other = workflow / 'other.sh'
    other.write_text(script.read_text() + '# different bytes\n')
    scheduler = root / 'bin'
    scheduler.mkdir()
    effects = root / 'scheduler-calls'
    executable = scheduler / 'condor_submit'
    executable.write_text('#!/bin/sh\nprintf "submitted\\n" >> ' + str(effects) + '\nprintf "73.0\\n"\n')
    executable.chmod(0o700)
    monkeypatch.setenv('PATH', str(scheduler) + os.pathsep + os.environ['PATH'])
    monkeypatch.setattr(runs, 'owner_of', lambda path: None)
    sha = hashlib.sha256(script.read_bytes()).hexdigest()
    token = real_capability.mint_capability(store, 'launch-one', {'workflow_dir': str(workflow),
        'tasks': ['unit'], 'max_jobs': 1, 'jobscript_sha256': sha})
    stale = real_capability.mint_capability(store, 'launch-stale', {'workflow_dir': str(workflow),
        'tasks': ['unit'], 'max_jobs': 1, 'jobscript_sha256': sha})
    real_capability.revoke_capability(store, 'launch-stale')
    code = ('import sys;from pathlib import Path;from ravel.controller import store;'
            'store.store_root=lambda:Path(sys.argv[1]);'
            'from ravel.workflow.site_profiles.htcondor import submit_main;'
            'raise SystemExit(submit_main(sys.argv[2:]))')
    args = [sys.executable, '-c', code, str(store.store_root), '--options-json',
            json.dumps({'workflow_dir': str(workflow), 'mem_mb': 64, 'runtime': 1})]
    def submit(path, secret=None):
        environment = dict(os.environ)
        if secret is None:
            environment.pop(wms_policy.CAPABILITY_ENV, None)
        else:
            environment[wms_policy.CAPABILITY_ENV] = secret
        return subprocess.run([*args, str(path)], env=environment, capture_output=True, text=True, timeout=20)
    assert submit(script).returncode != 0
    for secret in [stale, token]:
        with wms_policy.launch_authorization(workflow, 'unit', 1, {'unit': 'a' * 64},
                capability=secret, controller_run=store.run_id):
            if secret == stale:
                assert submit(script, secret).returncode != 0
            else:
                assert submit(other, secret).returncode != 0
    assert not effects.exists() and store.scan('wms-submission') == []
    with wms_policy.launch_authorization(workflow, 'unit', 2, {'unit': 'a' * 64},
            capability=token, controller_run=store.run_id):
        done = submit(script, token)
        assert done.returncode == 0, done.stderr
        assert done.stdout.strip() == '73.0'
        assert submit(script, token).returncode != 0
    assert effects.read_text().splitlines() == ['submitted']
    assert len(store.scan('wms-submission')) == 1


def test_parent_capability_survives_executor_process_and_submission_crash(tmp_path, monkeypatch):
    from ravel.controller import authority
    from ravel.controller.confine import runs
    from ravel.controller.routes import study
    from ravel.workflow import execution_backend as backend, wms_policy
    root = tmp_path.resolve()
    store = RunStore('durable-run', root=root / 'protected')
    run = root / 'run'
    run.mkdir()
    script = run / 'job.sh'
    script.write_text('# properties = {"rule": "task_unit", "threads": 1}\nexit 0\n')
    scheduler = root / 'bin'
    scheduler.mkdir()
    effects = root / 'scheduler-calls'
    executable = scheduler / 'condor_submit'
    executable.write_text('#!/bin/sh\nprintf "submitted\\n" >> ' + str(effects) + '\nprintf "73.0\\n"\n')
    executable.chmod(0o700)
    monkeypatch.setenv('PATH', str(scheduler) + os.pathsep + os.environ['PATH'])
    monkeypatch.setattr(runs, 'owner_of', lambda path: None)
    state = {'stop': 'running', 'recovered': [], 'cancelled': []}
    monkeypatch.setattr(authority, 'stop_state', lambda store: state['stop'])
    spec = {'id': 'launch-one', 'budget': {'wall_seconds': 1}, 'parameters': {
        'launch': {'jobscript': {'path': script.name, 'sha256': hashlib.sha256(script.read_bytes()).hexdigest()}},
        'wms_scope': {'workflow_dir': str(run), 'tasks': ['unit'], 'max_jobs': 1}}}
    context = {'store': store, 'run_dir': str(run), 'site_budget': 1,
               'plan_sha256': 'a' * 64, 'plan': {'route': 'study.site', 'steps': []}}
    code = ('import sys;from pathlib import Path;from ravel.controller import store;'
            'store.store_root=lambda:Path(sys.argv[1]);'
            'from ravel.controller.routes.study import site;assert site.active_launch(run_id="durable-run");'
            'from ravel.workflow.site_profiles.htcondor import submit_main;'
            'raise SystemExit(submit_main(sys.argv[2:]))')
    def invoke():
        options = site.launch_options(run, {'unit': 'a' * 64})
        environment = {**os.environ, **site.submission_environment()}
        with wms_policy.launch_authorization(run, 'unit', 1, {'unit': 'a' * 64}, **options):
            done = subprocess.run([sys.executable, '-c', code, str(store.store_root), '--options-json',
                json.dumps({'workflow_dir': str(run), 'mem_mb': 64, 'runtime': 1}), str(script)],
                env=environment, capture_output=True, text=True, timeout=20)
        assert done.returncode == 0, done.stderr
        site.track(store, spec['id'], {'plan_sha256': 'b' * 64},
            {'plan_sha256': 'b' * 64, 'backend': 'inert', 'remote': done.stdout.strip()})
        raise RuntimeError('interrupted after actual submission')
    with pytest.raises(RuntimeError, match='interrupted'):
        study.dispatch(spec, context, invoke)
    restarted = RunStore(store.run_id, root=store.store_root)
    context['store'] = restarted
    def recover(plan, handle):
        state['recovered'].append(handle['remote'])
        return {'handle': handle, 'observation': {'state': 'running'}}
    def cancel(plan, handle, *, wait_seconds):
        state['cancelled'].append(handle['remote'])
        return {'state': 'cancelled'}
    monkeypatch.setattr(backend, 'recover', recover)
    monkeypatch.setattr(backend, 'cancel', cancel)
    study.recover(context)
    assert study.dispatch(spec, context, lambda: pytest.fail('restart cannot resubmit'))['status'] == 'held'
    state['stop'] = 'stop_requested'
    study.ending('operator stop', context)
    assert state['recovered'] == ['73.0', '73.0'] and state['cancelled'] == ['73.0']
    assert effects.read_text().splitlines() == ['submitted']
    assert len(restarted.scan('wms-capability')) == len(restarted.scan('wms-submission')) == 1
    assert len(restarted.scan('study-remote')) == 1


@pytest.mark.parametrize('interrupted', [False, True])
def test_dispatch_captures_source_handle_even_when_child_is_interrupted(env, monkeypatch, interrupted):
    from ravel.controller.routes.study import remote
    store, spec, context, *_ = env
    captures = []
    monkeypatch.setattr(remote, 'capture', lambda ctx: captures.append(ctx['store']) or [])
    def invoke():
        if interrupted:
            raise RuntimeError('interrupted child')
        return {'status': 'completed'}
    if interrupted:
        with pytest.raises(RuntimeError, match='interrupted'):
            site.dispatch(store, spec, context, invoke)
    else:
        site.dispatch(store, spec, context, invoke)
    assert captures == [store]


def test_recovery_refuses_a_changed_recorded_remote_identity(env, monkeypatch):
    from ravel.workflow import execution_backend as backend
    store, spec, context, *_ = env
    dispatch(store, spec, context)
    site.track(store, spec['id'], {'plan_sha256': 'b' * 64},
        {'plan_sha256': 'b' * 64, 'backend': 'inert', 'remote': 'original-remote'})
    monkeypatch.setattr(backend, 'recover', lambda plan, handle: {
        'handle': {**handle, 'remote': 'changed-remote'}, 'observation': {'state': 'succeeded'}})
    result = site.reconcile(store)
    assert result['resolved'] is False
    assert result['attempts'][0]['handle']['remote'] == 'original-remote'
    assert result['attempts'][0]['error'] == 'recovered remote identity differs from the original attempt'


def test_refused_watcher_target_is_never_executed_for_help(tmp_path, monkeypatch):
    from ravel.workflow import preflight_watcher as watcher
    from ravel.controller import store as stores
    root = tmp_path.resolve() / 'run'
    scratch = root / 'scratch'
    scratch.mkdir(parents=True)
    target = scratch / 'fire.py'
    target.write_text('raise RuntimeError("must never execute")')
    monkeypatch.setattr(stores, 'controller_owned', lambda path: 'fixture-run')
    monkeypatch.setattr(watcher, '_target_required_arity',
                        lambda path: None if path is None else pytest.fail('invalid target executed'))
    record, _ = watcher.arm_watcher(str(root), 'completion', 'python3 ' + str(target), str(target))
    assert record['verdict'] == 'fail'


def dispatch(store, spec, context):
    """The parent supplies its child invocation; preserve the fixture's crash controls."""
    return site.dispatch(store, spec, context,
                         lambda: sys.modules['ravel.controller.step'].run(store, spec, context))


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

    def read(self, kind, record_id):
        return next(deepcopy(row) for row in self.rows if row['kind'] == kind and row['id'] == record_id)

    def scan(self, kind):
        return [deepcopy(row) for row in self.rows if row['kind'] == kind]

    def path(self, *parts):
        return self.root.joinpath(*parts)

    def checkpointer(self):
        raise NotImplementedError('no graph execution in this inert fake')


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    run = root / 'run'
    run.mkdir()
    script = run / 'jobscript'
    script.write_text('inert payload\n')
    state = {'stop': 'running', 'effects': 0, 'notifications': [], 'tokens': {}, 'cancelled': [], 'recoveries': []}
    authority = ModuleType('ravel.controller.authority')
    authority.stop_state = lambda store: state['stop']
    def request(store, kind, subject, bounds):
        assert kind == 'escalation' and set(subject) == {'view'} and bounds == {}
        assert subject['view']['run_id'] == store.run_id
        assert subject['view']['pins']['site_ending']
        state['notifications'].append({'kind': kind, 'subject': subject, 'bounds': bounds})
        return {'pending': 'recorded notification'}
    authority.request = request
    authority.operator_config = lambda: {'wait_bound': 0}
    authority.freeze_mode = lambda store, contract: {'mode': 'autonomous'}
    confine = ModuleType('ravel.controller.confine')
    def mint(store, launch_id, scope):
        assert set(scope) <= {'workflow_dir', 'tasks', 'rules', 'max_jobs', 'profile_sha256',
                              'jobscript_sha256', 'resource_maxima'}
        assert Path(scope['workflow_dir']).is_absolute()
        token = 'inert-token-' + launch_id
        if token in state['tokens']:
            raise ValueError('launch already minted')
        state['tokens'][token] = deepcopy(scope)
        return token
    def verify(token, jobscript):
        if token not in state['tokens']:
            raise ValueError('missing capability')
        claim = state['tokens'][token]
        if hashlib.sha256(Path(jobscript).read_bytes()).hexdigest() != claim['jobscript_sha256']:
            raise ValueError('capability belongs to other script bytes')
        used = state.setdefault('submissions', {}).get(token, 0)
        if used >= claim.get('max_jobs', 1):
            raise ValueError('capability job budget exhausted')
        state['submissions'][token] = used + 1
        return deepcopy(claim)
    confine.mint_capability = mint
    confine.verify_capability = verify
    step = ModuleType('ravel.controller.step')
    def execute(store, spec, context):
        # This stands for the submission boundary, not a model or native job.
        site.require_capability(script, run_id=store.run_id, launch_id=spec['id'])
        state['effects'] += 1
        return {'status': 'completed', 'step_id': spec['id'], 'outputs': [], 'budget': {'wall_seconds': 1}}
    step.run = execute
    sink = ModuleType('ravel.controller.sink')
    def ending(store, reason):
        return {'receipt_id': store.append('qualified-receipt', {'reason': reason}), 'qualified': True}
    sink.bounded_end = ending
    for name, module in [('authority', authority), ('confine', confine), ('step', step), ('sink', sink)]:
        monkeypatch.setitem(sys.modules, 'ravel.controller.' + name, module)
        import ravel.controller
        monkeypatch.setattr(ravel.controller, name, module, raising=False)
    store = Store(root=root / 'store')
    spec = {'id': 'launch-a', 'kind': 'operate', 'budget': {'wall_seconds': 10},
            'parameters': {'wms_scope': {'workflow_dir': str(run), 'max_jobs': 1}, 'launch': {'jobscript': {'path': 'jobscript',
                'sha256': hashlib.sha256(script.read_bytes()).hexdigest()}}}}
    context = {'run_dir': str(run), 'plan_sha256': 'a' * 64, 'site_budget': 10}
    return store, spec, context, state, authority, confine, step


def test_capability_required_at_inert_submission_boundary(env):
    store, spec, context, state, _, confine, _ = env
    mint = confine.mint_capability
    def refuse(*args):
        raise ValueError('capability mint refused')
    confine.mint_capability = refuse
    with pytest.raises(ValueError, match='capability'):
        dispatch(store, spec, context)
    assert state['effects'] == 0
    # A refused, undisbursed reservation releases budget for another launch.
    confine.mint_capability = mint
    other = deepcopy(spec)
    other['id'] = 'launch-b'
    result = dispatch(store, other, context)
    assert result['status'] == 'completed'
    assert state['effects'] == 1


def test_capability_positive_and_restart_reuses_durable_outcome(env):
    store, spec, context, state, *_ = env
    first = dispatch(store, spec, context)
    restarted = Store(root=store.root)
    restarted.rows = deepcopy(store.rows)
    assert dispatch(restarted, spec, context) == first
    assert state['effects'] == 1
    assert len([r for r in store.scan('study-site') if r['record']['event'] == 'reserved']) == 1


def test_restart_cannot_increase_budget_or_change_job(env):
    store, spec, context, state, *_ = env
    dispatch(store, spec, context)
    with pytest.raises(ValueError, match='restart'):
        dispatch(store, spec, {**context, 'site_budget': 100})
    changed = deepcopy(spec)
    changed['budget']['wall_seconds'] = 1
    with pytest.raises(ValueError, match='restart'):
        dispatch(store, changed, context)
    assert state['effects'] == 1


def test_budget_exhaustion_notifies_and_uses_qualified_sink(env):
    store, spec, context, state, *_ = env
    dispatch(store, spec, context)
    other = deepcopy(spec)
    other['id'] = 'launch-b'
    result = dispatch(store, other, context)
    assert result['qualified'] and state['effects'] == 1
    assert state['notifications'][-1]['subject']['view']['summary'] == 'site budget exhausted'
    assert state['notifications'][-1]['bounds'] == {}


def test_dispatch_crash_requires_reconciliation_without_resubmission(env):
    store, spec, context, state, _, _, step = env
    def interrupted(*args):
        state['effects'] += 1
        raise RuntimeError('controller interrupted after submission')
    step.run = interrupted
    with pytest.raises(RuntimeError, match='interrupted'):
        dispatch(store, spec, context)
    restarted = Store(root=store.root)
    restarted.rows = deepcopy(store.rows)
    assert dispatch(restarted, spec, context)['status'] == 'held'
    assert state['effects'] == 1
    site.bounded_end(restarted, 'unresolved dispatch')
    ending = restarted.scan('study-site-ending')[-1]['record']
    assert ending['unresolved_dispatches'] == ['launch-a']


def _backend(monkeypatch, state, *, terminal=True):
    from ravel.workflow import execution_backend as backend
    def recover(plan, handle):
        state['recoveries'].append(handle['remote'])
        handle['remote'] = 'remote-a'
        return {'handle': handle, 'observation': {'state': 'running', 'exit_code': None}}
    def cancel(plan, handle, *, wait_seconds):
        state['cancelled'].append(handle['remote'])
        return {'state': 'cancelled' if terminal else 'unknown', 'exit_code': None}
    monkeypatch.setattr(backend, 'recover', recover)
    monkeypatch.setattr(backend, 'cancel', cancel)


def test_stop_drains_recorded_remote_handle_before_sink(env, monkeypatch):
    store, spec, context, state, *_ = env
    dispatch(store, spec, context)
    site.track(store, spec['id'], {'plan_sha256': 'b' * 64},
               {'plan_sha256': 'b' * 64, 'backend': 'inert', 'remote': 'remote-a'})
    _backend(monkeypatch, state)
    state['stop'] = 'stop_requested'
    result = dispatch(store, {**spec, 'id': 'launch-b'}, context)
    assert result['qualified']
    assert state['cancelled'] == ['remote-a']
    assert state['effects'] == 1
    ending = store.scan('study-site-ending')[-1]['record']
    assert ending['reconciliation']['resolved']


def test_unknown_remote_is_retained_and_never_called_reaped(env, monkeypatch):
    store, spec, context, state, *_ = env
    dispatch(store, spec, context)
    site.track(store, spec['id'], {'plan_sha256': 'b' * 64},
               {'plan_sha256': 'b' * 64, 'backend': 'inert', 'remote': None})
    _backend(monkeypatch, state, terminal=False)
    assert site.reconcile(store, drain=True)['resolved'] is False
    assert site.reconcile(store, drain=True)['resolved'] is False
    assert state['recoveries'] == [None, 'remote-a']


def test_changed_script_and_missing_pin_have_zero_effects(env):
    store, spec, context, state, *_ = env
    Path(context['run_dir'], 'jobscript').write_text('changed\n')
    with pytest.raises(ValueError, match='bytes changed'):
        dispatch(store, spec, context)
    other = deepcopy(spec)
    other['parameters']['launch'].pop('jobscript')
    with pytest.raises(ValueError, match='jobscript pin'):
        dispatch(store, other, context)
    assert state['effects'] == 0 and state['tokens'] == {}


def test_failed_notification_cannot_prevent_qualified_sink(env):
    store, _, _, _, authority, *_ = env
    def unavailable(*args):
        raise ValueError('operator notification unavailable')
    authority.request = unavailable
    assert site.bounded_end(store, 'budget ended')['qualified']
    assert store.scan('study-site-notification')[-1]['record']['error_type'] == 'ValueError'


@pytest.mark.parametrize('ceiling', [-1, True, float('nan'), float('inf'), None])
def test_unbounded_budget_cannot_reserve_or_submit(env, ceiling):
    store, spec, context, state, *_ = env
    with pytest.raises(ValueError, match='finite'):
        dispatch(store, spec, {**context, 'site_budget': ceiling})
    assert state['effects'] == 0
    assert store.scan('study-site') == []


def test_pause_holds_without_reservation_or_qualified_ending(env):
    store, spec, context, state, *_ = env
    state['stop'] = 'pause_requested'
    held = dispatch(store, spec, context)
    assert held['status'] == 'held'
    assert store.scan('study-site') == [] and store.scan('qualified-receipt') == []
    assert state['effects'] == 0 and state['notifications'] == []
    state['stop'] = 'running'
    assert dispatch(store, spec, context)['status'] == 'completed'
    assert state['effects'] == 1


def test_pause_after_reservation_withdraws_and_resume_dispatches_once(env):
    store, spec, context, state, authority, *_ = env
    answers = iter(['running', 'pause_requested'])
    authority.stop_state = lambda store: next(answers, state['stop'])
    held = dispatch(store, spec, context)
    assert held['status'] == 'held' and state['effects'] == 0
    assert store.scan('qualified-receipt') == []
    restarted = Store(root=store.root)
    restarted.rows = deepcopy(store.rows)
    assert dispatch(restarted, spec, context)['status'] == 'completed'
    assert dispatch(restarted, spec, context)['status'] == 'completed'
    assert state['effects'] == 1
    reservations = [r for r in restarted.scan('study-site') if r['record']['event'] == 'reserved']
    assert len(reservations) == 1


def test_refused_capability_is_withdrawn_not_an_unresolved_dispatch(env):
    store, spec, context, state, _, confine, _ = env
    mint = confine.mint_capability
    def refuse(*args):
        raise ValueError('capability mint refused')
    confine.mint_capability = refuse
    with pytest.raises(ValueError, match='capability'):
        dispatch(store, spec, context)
    site.bounded_end(store, 'budget ended')
    assert store.scan('study-site-ending')[-1]['record']['unresolved_dispatches'] == []
    confine.mint_capability = mint
    assert dispatch(store, spec, context)['status'] == 'completed'
    assert state['effects'] == 1


def test_scheduler_error_during_drain_still_reaches_qualified_sink(env, monkeypatch):
    store, spec, context, state, *_ = env
    dispatch(store, spec, context)
    site.track(store, spec['id'], {'plan_sha256': 'b' * 64},
               {'plan_sha256': 'b' * 64, 'backend': 'inert', 'remote': 'remote-a'})
    from ravel.workflow import execution_backend as backend
    def unavailable(plan, handle):
        raise RuntimeError('scheduler query failed')
    monkeypatch.setattr(backend, 'recover', unavailable)
    assert site.bounded_end(store, 'deadline reached')['qualified']
    attempt = store.scan('study-site-ending')[-1]['record']['reconciliation']['attempts'][0]
    assert attempt['resolved'] is False and attempt['error_type'] == 'RuntimeError'


def test_capability_boundary_refuses_outside_context_and_wrong_scope(env):
    store, spec, context, state, _, confine, _ = env
    script = Path(context['run_dir'], 'jobscript')
    with pytest.raises(ValueError, match='trusted launch'):
        site.require_capability(script)
    scope = {'jobscript': {'path': str(script), 'sha256': spec['parameters']['launch']['jobscript']['sha256']},
             'jobscript_sha256': spec['parameters']['launch']['jobscript']['sha256']}
    token = confine.mint_capability(store, spec['id'],
        {'workflow_dir': context['run_dir'], 'jobscript_sha256': scope['jobscript_sha256']})
    with site.trusted_launch(store, spec['id'], token, scope):
        site.require_capability(script, run_id=store.run_id, launch_id=spec['id'])
        with pytest.raises(ValueError, match='scope'):
            site.require_capability(script, run_id='another-run')
        with pytest.raises(ValueError, match='nested conflicting'):
            with site.trusted_launch(store, 'another-launch', token, scope):
                pass
        script.write_text('replaced after admission')
        with pytest.raises(ValueError, match='exact bytes'):
            site.require_capability(script)
    with pytest.raises(ValueError, match='trusted launch'):
        site.require_capability(script)


def test_context_is_reset_after_dispatch_crash(env):
    store, spec, context, state, _, _, step = env
    def fail(*args):
        raise RuntimeError('inert crash')
    step.run = fail
    with pytest.raises(RuntimeError):
        dispatch(store, spec, context)
    with pytest.raises(ValueError, match='trusted launch'):
        site.require_capability(Path(context['run_dir'], 'jobscript'))
    events = [r['record']['event'] for r in store.scan('study-site')]
    assert events == ['reserved', 'dispatch_started']


def test_withdrawn_attempt_identity_and_ceiling_remain_immutable(env):
    store, spec, context, state, authority, *_ = env
    answers = iter(['running', 'pause_requested'])
    authority.stop_state = lambda store: next(answers, 'running')
    assert dispatch(store, spec, context)['status'] == 'held'
    with pytest.raises(ValueError, match='restart'):
        dispatch(store, spec, {**context, 'site_budget': 20})
    changed = deepcopy(spec)
    changed['budget']['wall_seconds'] = 1
    with pytest.raises(ValueError, match='restart'):
        dispatch(store, changed, context)
    assert state['effects'] == 0


def test_reconciliation_error_does_not_skip_other_handles(env, monkeypatch):
    store, spec, context, state, *_ = env
    dispatch(store, spec, context)
    for suffix in ['a', 'b']:
        launch_id = 'launch-' + suffix
        if suffix == 'b':
            store.append('study-site', {'event': 'reserved', 'launch_id': launch_id})
        site.track(store, launch_id, {'plan_sha256': suffix * 64},
                   {'plan_sha256': suffix * 64, 'backend': 'inert', 'remote': suffix})
    from ravel.workflow import execution_backend as backend
    def recover(plan, handle):
        if handle['remote'] == 'a':
            raise RuntimeError('unavailable')
        return {'handle': handle, 'observation': {'state': 'unknown'}}
    monkeypatch.setattr(backend, 'recover', recover)
    monkeypatch.setattr(backend, 'cancel', lambda *a, **kw: {'state': 'unknown'})
    result = site.reconcile(store, drain=True)
    assert not result['resolved'] and len(result['attempts']) == 2
    assert all(not row['resolved'] for row in result['attempts'])
    assert result['attempts'][0]['handle']['remote'] == 'a'


def test_restart_cannot_change_run_identity(env):
    store, spec, context, state, *_ = env
    dispatch(store, spec, context)
    restarted = Store(run_id='another-run', root=store.root)
    restarted.rows = deepcopy(store.rows)
    with pytest.raises(ValueError, match='restart'):
        dispatch(restarted, spec, context)
    assert state['effects'] == 1


def test_final_capability_refusal_never_refunds_or_resubmits(env):
    store, spec, context, state, _, confine, _ = env
    def refuse(*args):
        raise ValueError('final capability refused')
    confine.verify_capability = refuse
    with pytest.raises(ValueError, match='final capability'):
        dispatch(store, spec, context)
    assert dispatch(store, spec, context)['status'] == 'held'
    site.bounded_end(store, 'inspect refused dispatch')
    assert store.scan('study-site-ending')[-1]['record']['unresolved_dispatches'] == ['launch-a']
    assert state['effects'] == 0


def test_pause_resume_reuses_token_and_verifies_once_only_at_effect(env):
    store, spec, context, state, authority, *_ = env
    answers = iter(['running', 'pause_requested'])
    authority.stop_state = lambda store: next(answers, 'running')
    assert dispatch(store, spec, context)['status'] == 'held'
    assert state.get('submissions', {}) == {}
    assert len(store.scan('study-site-capability')) == 1
    assert dispatch(store, spec, context)['status'] == 'completed'
    assert state['submissions'] == {'inert-token-launch-a': 1}
    assert len(store.scan('study-site-capability')) == 1



def test_profile_pin_requires_actual_matching_profile_before_verification(env):
    store, spec, context, state, _, confine, _ = env
    script = Path(context['run_dir'], 'jobscript')
    scope = {'jobscript': {'path': str(script), 'sha256': spec['parameters']['launch']['jobscript']['sha256']},
             'capability': {'profile_sha256': 'b' * 64}}
    calls = []
    confine.verify_capability = lambda token, jobscript: calls.append((token, jobscript))
    assert not site.active_launch()
    with site.trusted_launch(store, spec['id'], 'trusted-token', scope):
        assert site.active_launch(run_id=store.run_id)
        assert not site.active_launch(run_id='other')
        for actual in [None, 'c' * 64]:
            with pytest.raises(ValueError, match='profile'):
                site.require_capability(script, profile_sha256=actual)
        assert calls == []
        site.require_capability(script, profile_sha256='b' * 64)
        assert calls == [('trusted-token', script)]
    assert not site.active_launch()


def test_documented_verifier_optional_inputs_forwarded_without_invention(env):
    store, spec, context, state, _, confine, _ = env
    script = Path(context['run_dir'], 'jobscript')
    scope = {'jobscript': {'path': str(script), 'sha256': spec['parameters']['launch']['jobscript']['sha256']},
             'capability': {'profile_sha256': 'b' * 64}}
    calls = []
    def verify(token, jobscript, *, profile_sha256=None, resource_defaults=None, authorized_tasks=None):
        calls.append((token, jobscript, profile_sha256, resource_defaults, authorized_tasks))
        return {'admitted': True}
    confine.verify_capability = verify
    defaults = {'threads': 1, 'mem_mb': 128}
    tasks = ['approved-task']
    with site.trusted_launch(store, spec['id'], 'trusted-token', scope):
        result = site.require_capability(script, profile_sha256='b' * 64,
                                        resource_defaults=defaults, authorized_tasks=tasks)
    assert result == {'admitted': True}
    assert calls == [('trusted-token', script, 'b' * 64, defaults, tasks)]


@pytest.fixture
def adoption(env, monkeypatch):
    from ravel.workflow import execution_backend as backend
    store, spec, context, state, *_ = env
    dispatch(store, spec, context)
    plan = {'plan_sha256': 'b' * 64, 'spec': {'outputs': [
        {'name': 'numeric.json', 'destination': 'adopted/numeric.json', 'kind': 'file'}]}}
    handle = {'plan_sha256': 'b' * 64, 'backend': 'inert', 'remote': 'original-remote', 'tag': 'original-tag'}
    site.track(store, spec['id'], plan, handle)
    state.update({'fetches': 0, 'adoption_state': 'succeeded'})
    def recover(plan, handle):
        return {'handle': deepcopy(handle), 'observation': {'state': state['adoption_state']}}
    def fetch(plan, handle, base):
        state['fetches'] += 1
        outputs = []
        for row in plan['spec']['outputs']:
            path = base / row['destination']
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(b'{"value":53,"units":"GeV"}')
            fact = backend.identity(path)
            outputs.append({'name': row['name'], 'destination': str(path),
                            **{key: fact[key] for key in ('kind', 'sha256', 'size')}})
        return {'kind': 'ravel-backend-fetch-receipt', 'plan_sha256': plan['plan_sha256'],
                'backend': handle['backend'], 'remote': handle['remote'], 'tag': handle['tag'],
                'outputs': outputs, 'remote_outputs': [], 'quantities': {'literal': 53}}
    monkeypatch.setattr(backend, 'recover', recover)
    monkeypatch.setattr(backend, 'fetch', fetch)
    return store, spec['id'], Path(context['run_dir']), state, backend


def test_remote_adoption_preserves_source_pins_and_restart_never_refetches(adoption):
    store, launch_id, base, state, _ = adoption
    receipt = site.adopt(store, launch_id, base=base)
    assert receipt['quantities'] == {'literal': 53}
    pin = receipt['outputs'][0]
    assert hashlib.sha256(Path(pin['destination']).read_bytes()).hexdigest() == pin['sha256']
    assert 'accepted' not in receipt and 'qualified' not in receipt
    restarted = Store(root=store.root)
    restarted.rows = deepcopy(store.rows)
    assert site.adopt(restarted, launch_id, base=base) == receipt
    assert state['fetches'] == 1
    assert store.scan('study-adoption')[-1]['record']['receipt'] == receipt


@pytest.mark.parametrize('state_name', ['failed', 'cancelled', 'unknown', 'running'])
def test_remote_adoption_requires_observed_success(adoption, state_name):
    store, launch_id, base, state, _ = adoption
    state['adoption_state'] = state_name
    with pytest.raises(ValueError, match='succeeded'):
        site.adopt(store, launch_id, base=base)
    assert state['fetches'] == 0 and store.scan('study-adoption') == []


def test_remote_adoption_refuses_untracked_forged_handle_and_widened_root(adoption):
    store, launch_id, base, state, _ = adoption
    with pytest.raises(ValueError, match='recorded'):
        site.adopt(store, 'untracked', base=base)
    with pytest.raises(ValueError, match='root'):
        site.adopt(store, launch_id, base=base.parent)
    with pytest.raises(ValueError, match='protected'):
        site.adopt(store, launch_id, base=store.root)
    row = store.scan('study-remote')[0]['record']
    with pytest.raises(ValueError, match='immutable'):
        site.track(store, launch_id, row['plan'], {**row['handle'], 'remote': 'forged'})
    assert state['fetches'] == 0


def test_remote_adoption_refuses_escaping_declared_destination(adoption):
    store, launch_id, base, state, _ = adoption
    row = next(r for r in store.rows if r['kind'] == 'study-remote')
    row['record']['plan']['spec']['outputs'][0]['destination'] = '../escape.json'
    with pytest.raises(ValueError, match='escapes'):
        site.adopt(store, launch_id, base=base)
    assert state['fetches'] == 0


def test_remote_adoption_restart_refuses_changed_bytes_or_root(adoption):
    store, launch_id, base, state, _ = adoption
    receipt = site.adopt(store, launch_id, base=base)
    Path(receipt['outputs'][0]['destination']).write_text('changed after fetch')
    with pytest.raises(ValueError, match='pin changed'):
        site.adopt(store, launch_id, base=base)
    with pytest.raises(ValueError, match='root'):
        site.adopt(store, launch_id, base=base / 'widened')
    assert state['fetches'] == 1


def test_remote_adoption_never_repeats_uncertain_fetch(adoption, monkeypatch):
    store, launch_id, base, state, backend = adoption
    def interrupted(*args):
        state['fetches'] += 1
        raise RuntimeError('interrupted backend fetch')
    monkeypatch.setattr(backend, 'fetch', interrupted)
    with pytest.raises(RuntimeError, match='interrupted'):
        site.adopt(store, launch_id, base=base)
    with pytest.raises(ValueError, match='never refetch'):
        site.adopt(store, launch_id, base=base)
    assert state['fetches'] == 1


def test_remote_adoption_refuses_recovered_identity_reassignment(adoption, monkeypatch):
    store, launch_id, base, state, backend = adoption
    def forged(plan, handle):
        return {'handle': {**handle, 'remote': 'different-remote'}, 'observation': {'state': 'succeeded'}}
    monkeypatch.setattr(backend, 'recover', forged)
    with pytest.raises(ValueError, match='original remote plan'):
        site.adopt(store, launch_id, base=base)
    assert state['fetches'] == 0



def test_remote_adoption_refuses_legacy_missing_original_root(adoption):
    store, launch_id, base, state, _ = adoption
    reserved = next(r for r in store.rows if r['kind'] == 'study-site' and r['record']['event'] == 'reserved')
    reserved['record'].pop('run_dir')
    with pytest.raises(ValueError, match='missing.*root binding'):
        site.adopt(store, launch_id, base=base)
    assert state['fetches'] == 0
