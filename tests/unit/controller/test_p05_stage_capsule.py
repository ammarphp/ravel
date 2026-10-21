"""Direct inert controls for stage/native scope, capsules, clocks and post-lease CPU grants."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_native_payload_requires_existing_verified_plan(tmp_path, monkeypatch):
    from ravel.workflow.backends import native
    from ravel.controller import confine
    job = tmp_path / 'attempt' / 'job'
    job.mkdir(parents=True)
    monkeypatch.setattr(confine, 'prepare', lambda spec: pytest.fail('missing plan reached prepare'))
    monkeypatch.setattr(native.eb, 'load_plan', lambda *a, **k: pytest.fail('missing plan reached load'))
    with pytest.raises(ValueError, match='requires its pinned plan.json'):
        native._confined_payload(job, ['/usr/bin/true'], None)


def test_native_payload_scope_is_declared_facts_exact_custody_and_approved_capsule(tmp_path, monkeypatch):
    from ravel.workflow.backends import native
    from ravel.controller import confine
    from ravel.controller.confine import runs
    run = tmp_path / 'run'
    job = run / 'logs' / 'attempt' / 'job'
    job.mkdir(parents=True)
    declared = tmp_path / 'declared-input'
    declared.write_text('inert')
    tree = tmp_path / 'declared-tree'
    tree.mkdir()
    custody = [job / 'payload.json', job / 'launcher.json', job.parent / 'plan.json',
               job.parent / 'backend-handle.json', run / 'execution_state.json']
    for path in custody:
        path.write_text('{}')
    (run / 'unrelated-secret').write_text('must stay absent')
    plan = {'spec': {'env': {'PATH': '/approved/bin', 'OMP_NUM_THREADS': '2',
                             'GATE_TIMESTAMP': 'fake', 'AWS_SECRET_ACCESS_KEY': 'not-a-key',
                             'WORKFLOW_STATE_UTC': 'fake', 'LD_PRELOAD': '/untrusted.so'},
                     'resources': {'cpus': 2, 'wall_seconds': 20, 'memory_mib': 128}},
            'inputs': [{'path': str(declared)}], 'readonly_trees': [{'path': str(tree)}]}
    observed = {}

    def load(path, *, verify_inputs):
        assert path == job.parent / 'plan.json' and verify_inputs is True
        return plan

    monkeypatch.setattr(native.eb, 'load_plan', load)
    monkeypatch.setattr(runs, 'owner_of', lambda path: ('run-1', run))
    monkeypatch.setattr(confine, 'prepare', lambda spec: observed.update(spec) or spec)
    monkeypatch.setenv('PATH', '/ambient/bin')
    monkeypatch.setenv('PYTHONPATH', '/ambient/unapproved')
    monkeypatch.setenv('OMP_NUM_THREADS', '99')
    monkeypatch.setenv('RAVEL_STAGE_CUSTODY', 'channel')
    native._confined_payload(job, ['/usr/bin/true'], '/approved/true')
    assert set(observed['reads']) == {str(p) for p in [declared, tree, *custody]}
    assert str(run) not in observed['reads'] and str(job.parent) not in observed['reads']
    assert observed['writes'] == [str(job / 'output'), str(job / 'work')]
    assert observed['limits'] == {'cpus': 2, 'wall_seconds': 20, 'memory_mib': 128}
    assert observed['env']['PATH'] == '/approved/bin'
    assert observed['env']['OMP_NUM_THREADS'] == '2'
    assert observed['env']['RAVEL_STAGE_CUSTODY'] == 'channel'
    assert 'PYTHONPATH' not in observed['env']
    assert not set(observed['env']) & {'GATE_TIMESTAMP', 'WORKFLOW_STATE_UTC', 'AWS_SECRET_ACCESS_KEY', 'LD_PRELOAD'}


def test_native_controller_environment_cannot_restore_spec_selectors(tmp_path, monkeypatch):
    from ravel.workflow.backends import native
    monkeypatch.setattr(native, '_controller_job', lambda job: True)
    monkeypatch.setenv('LANG', 'ambient-locale')
    plan = {'spec': {'env': {'PATH': '/approved/bin', 'OMP_NUM_THREADS': '3',
                             'GATE_TIMESTAMP': 'fake', 'RAVEL_OVERRIDE': 'yes'},
                     'resources': {'cpus': 3}, 'inherit_runtime_environment': True},
            'readonly_trees': []}
    env = native.environment(plan, tmp_path)
    assert env['PATH'] == '/approved/bin' and env['OMP_NUM_THREADS'] == '3'
    assert not set(env) & {'LANG', 'GATE_TIMESTAMP', 'RAVEL_OVERRIDE'}
    assert env['RAVEL_BACKEND_JOB'] == str(tmp_path)


def test_controller_stage_real_clock_overrides_both_clock_selectors(tmp_path, monkeypatch):
    from ravel.workflow import stage_supervisor as supervisor
    monkeypatch.setattr(supervisor, '_controller_run', lambda run: 'owned')
    monkeypatch.setenv('GATE_TIMESTAMP', '1999-01-01T00:00:00Z')
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2000-01-01T00:00:00Z')
    monkeypatch.setattr(supervisor.execution, 'utc_now', lambda: '2001-01-01T00:00:00Z')
    before = datetime.now(timezone.utc).replace(microsecond=0)
    observed = supervisor._resolve_timestamp(tmp_path)
    after = datetime.now(timezone.utc).replace(microsecond=0)
    assert before <= datetime.fromisoformat(observed.replace('Z', '+00:00')) <= after
    monkeypatch.setattr(supervisor, '_controller_run', lambda run: None)
    assert supervisor._resolve_timestamp(tmp_path) == '1999-01-01T00:00:00Z'
    monkeypatch.delenv('GATE_TIMESTAMP')
    assert supervisor._resolve_timestamp(tmp_path) == '2001-01-01T00:00:00Z'


def test_stage_context_carries_exact_snapshot_runtime_and_only_declared_limits(monkeypatch):
    from ravel.workflow import stage_supervisor as supervisor
    snapshot = {'input.dat': {'sha256': 'inert'}}
    monkeypatch.setattr(supervisor.execution, 'runtime_environment',
                        lambda: {'PATH': '/approved/bin', 'OMP_NUM_THREADS': '4', 'CONDA_PREFIX': None})
    context = supervisor._controller_launch_context({}, {'input_snapshot': snapshot}, 23)
    assert context['environment_capsule'] == {'PATH': '/approved/bin', 'OMP_NUM_THREADS': '4'}
    assert context['input_snapshot'] is snapshot and context['max_seconds'] == 23
    assert context['limits'] == {'cpus': 4}
    declared = {'cpus': 2, 'memory_mib': 128, 'wall_seconds': 12}
    context = supervisor._controller_launch_context({}, {'input_snapshot': snapshot}, 23, declared)
    assert context['limits'] == declared
    monkeypatch.setattr(supervisor.execution, 'runtime_environment', lambda: {'OMP_NUM_THREADS': 'invalid'})
    assert 'limits' not in supervisor._controller_launch_context({}, {'input_snapshot': snapshot}, 23)


def test_post_lease_grant_rebinds_cpu_set_and_refuses_over_allocation(monkeypatch):
    from ravel.workflow import stage_supervisor as supervisor
    from ravel.controller import confine

    class FakePlan:
        def __init__(self, cpus):
            self.limits = {'cpus': cpus, 'cpu_set': [0, 1]}

    monkeypatch.setattr(confine, 'Plan', FakePlan)
    monkeypatch.setattr(confine, 'machine_grant', lambda: [8, 9, 10])
    plan = FakePlan(2)
    supervisor._refresh_controller_grant(plan)
    assert plan.limits['cpu_set'] == [8, 9]
    monkeypatch.setattr(confine, 'machine_grant', lambda: [8])
    with pytest.raises(confine.ConfinementRefused, match='acquired machine grant'):
        supervisor._refresh_controller_grant(plan)
    supervisor._refresh_controller_grant({'kind': 'controller-broker'})
