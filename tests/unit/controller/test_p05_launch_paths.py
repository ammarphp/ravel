"""Every launch path of a controller-owned run goes through the confined launcher (SW16, SW17, SW34-SW38, SW41).

Legacy runs the controller does not own keep their 1.1.0 behaviour. Approval capture is
replaced by an event written through the real journal, so the journal, its store mirror and
the controller clock are the real ones.
"""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from test_p05_support import operator, own, sandboxed  # noqa: F401 (fixture)


@pytest.fixture
def launch_seams(monkeypatch):
    """Approval capture and steering are outside P05; their seams admit the launch, the journal is real."""
    from ravel.workflow import gate_wiring, launch_authorization as la

    def prepared(root, required_plan, command, context, *, _session=None):
        return la._append(root, {'event': 'authorized', 'command': command, 'context': context,
                                 'authorization': {'required_plan': required_plan}})
    monkeypatch.setattr(la, '_prepare_popen_authorization', prepared)
    monkeypatch.setattr(gate_wiring, 'steering_dispatch', lambda root, node: contextlib.nullcontext())
    monkeypatch.setattr(gate_wiring, 'register_steering_process', lambda root, process, context: None)
    return la


def controller_run(tmp_path, monkeypatch, run_id='run-launch'):
    from ravel.workflow import agent_tripwire
    monkeypatch.setattr(agent_tripwire, 'context', lambda: {'ravel_kind': 'effect', 'node': 'inert-launch'})
    run = (tmp_path / 'run').resolve()
    (run / 'outputs').mkdir(parents=True, exist_ok=True)
    store_root = (tmp_path / 'store').resolve()
    stores = own(monkeypatch, store_root, {run: run_id})
    operator(monkeypatch, {'store_root': str(store_root)})
    return run, stores[run_id]


def stage_context(run, outputs):
    return {'stage': 'fit', 'node_id': 'fit', 'kind': 'scientific-stage',
            'stage_spec': {'inputs': [], 'outputs': [str(run / o) for o in outputs]}}


def test_SW16_controller_launch_is_confined_and_journaled_on_real_clock(
        tmp_path, monkeypatch, sandboxed, launch_seams):
    from ravel.workflow import wms_policy
    la = launch_seams
    run, store = controller_run(tmp_path, monkeypatch)
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2001-01-01T00:00:00Z')
    monkeypatch.setenv('GH_TOKEN', 'controller-credential')
    command = [sys.executable, '-c', 'import os, json\nopen("outputs/env.json", "w").write(json.dumps(sorted(os.environ)))']
    with wms_policy.controller_dispatch(run):
        process = la.authorized_popen(run, 'full', command, context=stage_context(run, ['outputs']), cwd=str(run),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    out, err = process.communicate(timeout=60)
    from ravel.controller import confine
    confine.finish(process)
    assert process.returncode == 0, err.decode()
    names = json.loads((run / 'outputs' / 'env.json').read_text())
    assert 'GH_TOKEN' not in names and 'WORKFLOW_STATE_UTC' not in names
    events = la._events(run)
    assert [e['event'] for e in events] == ['authorized', 'launched'] and events[0]['command'] == command
    assert not any(e['utc'].startswith('2001') for e in events), 'a controller run never takes the fixed clock'
    assert events[1]['confinement']['kind'] == 'confined'
    stored = [row['record']['sha256'] for row in store.scan(la.STORE_KIND)]
    assert stored == [e['sha256'] for e in events] and la.store_mirror_errors(run) == []


def test_a_run_tree_journal_that_differs_from_the_store_no_longer_audits(tmp_path, monkeypatch, launch_seams):
    from ravel.controller.confine import runs
    la = launch_seams
    run, store = controller_run(tmp_path, monkeypatch)
    la._append(run, {'event': 'authorized', 'command': ['x'], 'context': {}, 'authorization': {'required_plan': 'full'}})
    assert la.store_mirror_errors(run) == []
    # An event written into the run tree without the controller (no store original).
    monkeypatch.setattr(runs, 'owner_of', lambda path: None)
    la._append(run, {'event': 'authorized', 'command': ['y'], 'context': {}, 'authorization': {'required_plan': 'full'}})
    monkeypatch.undo()
    run, store = controller_run(tmp_path, monkeypatch)
    errors = la.audit_launches(run)
    assert errors and 'differs from the controller store' in errors[0]


def test_a_legacy_run_launches_as_before(tmp_path, monkeypatch, launch_seams):
    la = launch_seams
    run = (tmp_path / 'legacy').resolve()
    run.mkdir()
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2001-01-01T00:00:00Z')
    seen = {}
    real = subprocess.Popen

    def popen(argv, **kwargs):
        seen['argv'], seen['env'] = argv, kwargs.get('env')
        return real(argv, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', popen)
    process = la.authorized_popen(run, 'full', [sys.executable, '-c', 'pass'], context={'stage': 'fit'}, cwd=str(run))
    process.wait(timeout=60)
    assert seen['argv'] == [sys.executable, '-c', 'pass'] and seen['env'] is None
    events = la._events(run)
    assert 'confinement' not in events[1] and events[0]['utc'] == '2001-01-01T00:00:00Z'
    assert all(event['governance_label'] == 'NOT GOVERNED' for event in events)


def test_SW41_missing_controller_dispatch_refuses_before_effect(
        tmp_path, monkeypatch, launch_seams):
    from ravel.workflow import wms_policy
    la = launch_seams
    run, store = controller_run(tmp_path, monkeypatch)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('a process started'))
    with pytest.raises(ValueError, match='absence of a workflow policy is not permission'):
        la.authorized_popen(run, 'full', [sys.executable, '-c', 'pass'], context=stage_context(run, ['outputs']),
                            cwd=str(run))
    assert la._events(run) == [] and store.scan(la.STORE_KIND) == []
    # A confined child that carries its running attempt's custody secret keeps custody.
    from ravel.controller.confine import custody_digest
    from ravel.workflow import execution
    token = 'f' * 64
    state = {'schema_version': 1, 'revision': 1, 'stages': {'fit': {'status': 'running', 'confinement': {
        'custody_sha256': custody_digest(token)}}}}
    (run / execution.STATE_NAME).write_text(json.dumps(state))
    monkeypatch.setenv('RAVEL_STAGE_CUSTODY', 'e' * 64)
    with pytest.raises(ValueError):
        wms_policy.require_custody(run)
    monkeypatch.setenv('RAVEL_STAGE_CUSTODY', token)
    wms_policy.require_custody(run)
    monkeypatch.delenv('RAVEL_STAGE_CUSTODY')
    with wms_policy.controller_dispatch(run):
        wms_policy.require_custody(run)
        wms_policy.require_custody(run / 'points' / 'p1')


def test_controller_side_brokers_keep_the_controller_environment_and_are_recorded(
        tmp_path, monkeypatch, launch_seams):
    from ravel.workflow import wms_policy
    la = launch_seams
    run, store = controller_run(tmp_path, monkeypatch)
    seen = {}

    def popen(argv, **kwargs):
        seen['argv'], seen['env'] = argv, kwargs.get('env')
        return SimpleNamespace(pid=os.getpid(), poll=lambda: 0, wait=lambda: 0, kill=lambda: None)
    monkeypatch.setattr(subprocess, 'Popen', popen)
    worker = [sys.executable, '-m', 'ravel.workflow.execution_backend', 'worker', '--rundir', str(run)]
    with wms_policy.controller_dispatch(run):
        la.authorized_popen(run, 'full', worker, context=stage_context(run, ['outputs']), cwd=str(run))
    assert seen['argv'] == worker and seen['env']['PYTHONSAFEPATH'] == '1'
    record = la._events(run)[1]['confinement']
    assert record['class'] == 'controller-side' and record['entry_point'] == 'ravel.workflow.execution_backend worker'


def test_only_registered_ravel_entry_points_of_this_installation_are_controller_side(tmp_path, monkeypatch):
    import sysconfig
    from ravel import paths
    from ravel.controller.confine import brokers, entry_point
    run = (tmp_path / 'run').resolve()
    (run / 'inputs').mkdir(parents=True)
    boot = str(Path(paths.__file__).with_name('_bootstrap.py'))
    assert entry_point(run, [sys.executable, boot, 'ravel.physics.native_pipeline', 'run', '--plan', 'p'])
    assert entry_point(run, [sys.executable, '-m', 'ravel.workflow.partitioned_execution', 'run'])
    assert entry_point(run, [str(Path(sysconfig.get_path('scripts')) / 'ravel'), 'partitions', 'run'])
    other = tmp_path / 'other-env' / 'bin' / 'python'
    for command in ([str(other), '-m', 'ravel.workflow.execution_backend', 'worker'],
                    [sys.executable, '-m', 'ravel.workflow.execution_backend', 'doctor'],
                    [sys.executable, str(tmp_path / '_bootstrap.py'), 'ravel.physics.native_pipeline', 'run'],
                    [sys.executable, '-c', 'import ravel'], ['bash', 'run.sh']):
        assert entry_point(run, command) is None, command
    science = [sys.executable, boot, 'ravel.physics.science_worker', str(run)]
    (run / 'inputs' / 'science.json').write_text(json.dumps({'mode': 'event-production'}))
    assert entry_point(run, science)['entry_point'].endswith('(event-production)')
    (run / 'inputs' / 'science.json').write_text(json.dumps({'mode': 'literal-calculation'}))
    assert entry_point(run, science) is None
    assert brokers.environment({'A': '1'}) == {'PYTHONPATH': str(Path(paths.__file__).resolve().parent.parent),
                                               'PYTHONNOUSERSITE': '1', 'PYTHONSAFEPATH': '1'}


@pytest.mark.parametrize('module,arguments', [
    ('ravel.controller.routes.manuscript.note', ['sources']),
    ('ravel.workflow.partitioned_execution', ['run']),
])
def test_isolated_module_keeps_its_installed_package_inside_confinement(tmp_path, monkeypatch, module, arguments):
    from ravel.controller.confine import brokers, launcher, locations
    from ravel.workflow import sandbox
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos' if sys.platform == 'darwin' else 'linux')
    monkeypatch.setattr(launcher, 'qualify', lambda kind: {'backend': kind, 'confirmed': True})
    run, _ = controller_run(tmp_path, monkeypatch)
    command = [sys.executable, '-I', '-m', module, *arguments]
    plan = launcher.prepare({'argv': command, 'reads': [], 'writes': [str(run / 'outputs')],
                             'cwd': str(run / 'outputs'), 'run_dir': str(run)})
    assert plan.argv == command and plan.record['kind'] == 'confined'
    assert locations.package_root() / 'ravel' not in plan.hidden
    assert locations.within(locations.package_root(), plan.reads)
    assert plan.record['writable'] == [str(run / 'outputs')]
    assert brokers.entry_point(run, command) is None


@pytest.mark.parametrize('form', ['code', 'extra_flag', 'missing_module', 'foreign_interpreter', 'foreign_bootstrap'])
def test_isolated_module_package_visibility_keeps_other_commands_confined_and_masked(tmp_path, monkeypatch, form):
    from ravel.controller.confine import brokers, launcher, locations
    from ravel.workflow import sandbox
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos' if sys.platform == 'darwin' else 'linux')
    monkeypatch.setattr(launcher, 'qualify', lambda kind: {'backend': kind, 'confirmed': True})
    run, _ = controller_run(tmp_path, monkeypatch)
    other = tmp_path / 'other-env/bin/python'
    other.parent.mkdir(parents=True)
    other.symlink_to(sys.executable)
    forms = {
        'code': [sys.executable, '-I', '-c', 'import ravel'],
        'extra_flag': [sys.executable, '-I', '-S', '-m', 'ravel.workflow.partitioned_execution', 'run'],
        'missing_module': [sys.executable, '-I', '-m'],
        'foreign_interpreter': [str(other), '-I', '-m', 'ravel.workflow.partitioned_execution', 'run'],
        'foreign_bootstrap': [sys.executable, '-I', str(tmp_path / '_bootstrap.py'), 'ravel.workflow.partitioned_execution', 'run'],
    }
    command = forms[form]
    plan = launcher.prepare({'argv': command, 'reads': [], 'writes': [str(run / 'outputs')],
                             'cwd': str(run / 'outputs'), 'run_dir': str(run)})
    assert plan.record['kind'] == 'confined'
    assert locations.package_root() / 'ravel' in plan.hidden
    assert brokers.entry_point(run, command) is None


def test_SW38_authorized_popen_calls_tripwire(tmp_path, monkeypatch, launch_seams):
    from ravel.workflow import agent_tripwire
    la = launch_seams
    run = (tmp_path / 'run').resolve()
    run.mkdir()
    monkeypatch.setattr(la, '_authorized_popen_locked', lambda *a, **k: SimpleNamespace(pid=1))
    monkeypatch.setenv(agent_tripwire.ENV, 'report')
    before = len(agent_tripwire.OBSERVED)
    la.authorized_popen(run, 'full', ['inert'], context={'stage': 'fit'})
    assert agent_tripwire.OBSERVED[before]['layer'] == 'authorized_popen'
    monkeypatch.setenv(agent_tripwire.ENV, 'block')
    monkeypatch.setattr(la, '_authorized_popen_locked', lambda *a, **k: pytest.fail('spawn reached'))
    with pytest.raises(agent_tripwire.TripwireViolation):
        la.authorized_popen(run, 'full', ['inert'], context={'stage': 'fit'})


def test_SW17_engineering_only_dispatch_refuses_without_markers(tmp_path, monkeypatch):
    from ravel.workflow import approval_authority, stage_supervisor
    from ravel.controller.authority import issuer
    for name in approval_authority.AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    issuer.initialize()  # Let the live authority precheck reach the engineering-only boundary.
    run, _ = controller_run(tmp_path, monkeypatch)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('a process started'))
    with pytest.raises(ValueError, match='controller-owned run'):
        stage_supervisor.supervise('probe', str(run), 0, 'logs/probe.log', [sys.executable, '-c', 'pass'],
                                   _engineering_only=True)
    assert not (run / 'logs' / 'execution').exists()


def test_SW36_controller_refuses_version_one_and_confines_other_commands(tmp_path, monkeypatch):
    from ravel.controller import confine
    from ravel.controller.confine import launcher
    from ravel.workflow import sandbox, stage_supervisor
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos' if sys.platform == 'darwin' else 'linux')
    monkeypatch.setattr(launcher, 'qualify', lambda kind: {'backend': kind, 'confirmed': True})
    run, _ = controller_run(tmp_path, monkeypatch)
    context = stage_context(run, ['outputs'])
    with pytest.raises(confine.ConfinementRefused, match='version-one'):
        stage_supervisor._controller_launch(run, 'science', [sys.executable, '-c', 'pass'], context, str(run),
                                            legacy_science=True)
    nested = [sys.executable, '-m', 'ravel.workflow.execution_backend', 'worker', '--rundir', str(run)]
    assert stage_supervisor._controller_launch(run, 'inner', nested, context, str(run),
                                               legacy_science=False)['class'] == 'controller-side'
    plan = stage_supervisor._controller_launch(run, 'inner', ['bash', 'authored.sh'], context, str(run),
                                               legacy_science=False)
    assert isinstance(plan, confine.Plan) and plan.record['declared_outputs'] == [str(run / 'outputs')]


def test_SW37_native_backend_gets_allowlist_and_confined_payload(tmp_path, monkeypatch):
    from ravel.controller import confine
    from ravel.controller.confine import launcher
    from ravel.workflow import sandbox
    from ravel.workflow.backends import native
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos' if sys.platform == 'darwin' else 'linux')
    monkeypatch.setattr(launcher, 'qualify', lambda kind: {'backend': kind, 'confirmed': True})
    run, _ = controller_run(tmp_path, monkeypatch)
    job = run / 'logs' / 'execution' / 'stage' / 'a1' / 'backend' / 'job'
    (job / 'output').mkdir(parents=True)
    (job / 'work').mkdir()
    monkeypatch.setenv('GH_TOKEN', 'controller-credential')
    monkeypatch.setenv('RAVEL_ROOT', str(tmp_path))
    plan = {'spec': {'env': {'STAGE_SETTING': '1'}, 'resources': {'cpus': 1}, 'argv': ['tool']},
            'readonly_trees': [], 'inputs': []}
    env = native.environment(plan, job)
    assert 'GH_TOKEN' not in env and 'RAVEL_ROOT' not in env and env['STAGE_SETTING'] == '1'
    assert env['RAVEL_OUTPUT_DIR'] == str(job / 'output')
    legacy = (tmp_path / 'legacy-job').resolve()
    assert native.environment(plan, legacy)['GH_TOKEN'] == 'controller-credential'
    (job.parent / 'plan.json').write_text('{}')
    monkeypatch.setattr(native.eb, 'load_plan', lambda *a, **kw: plan)
    confined = native._confined_payload(job, [sys.executable, '-c', 'pass'], None)
    assert isinstance(confined, confine.Plan)
    assert confined.record['writable'] == [str(job / 'output'), str(job / 'work')]


def test_oci_local_containers_of_a_controller_run_are_read_only_and_unprivileged(tmp_path, monkeypatch):
    from ravel.workflow.backends import oci_local
    run, _ = controller_run(tmp_path, monkeypatch)
    plan = {'spec': {'image': {'platform': 'linux/amd64', 'reference': 'registry.invalid/image@sha256:' + 'a' * 64},
                     'resources': {'cpus': 1, 'memory_mib': 512}, 'argv': ['tool']},
            'plan_sha256': 'b' * 64, 'inputs': [], 'readonly_trees': []}
    controlled = oci_local.OciLocalBackend().create_arguments(plan, {'tag': 't', 'job_dir': str(run / 'job')})
    assert '--read-only' in controlled and controlled[controlled.index('--user') + 1] == f'{os.getuid()}:{os.getgid()}'
    legacy = oci_local.OciLocalBackend().create_arguments(plan, {'tag': 't', 'job_dir': str(tmp_path / 'legacy')})
    assert '--read-only' not in legacy and '--user' not in legacy
    assert controlled.index('--read-only') < controlled.index(plan['spec']['image']['reference'])


def test_SW35_construction_checks_are_planned_confined(tmp_path, monkeypatch):
    from ravel.controller import confine
    from ravel.controller.confine import launcher
    from ravel.workflow import agentrivet_checks, sandbox
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos' if sys.platform == 'darwin' else 'linux')
    monkeypatch.setattr(launcher, 'qualify', lambda kind: {'backend': kind, 'confirmed': True})
    run, _ = controller_run(tmp_path, monkeypatch)
    session = agentrivet_checks.Session.__new__(agentrivet_checks.Session)
    session.root = run / 'construction'
    session.root.mkdir()
    session.checks = {'runtime': {'python': {'path': sys.executable}}, 'sample': None}
    workdir = session.root / 'checks' / 'w1'
    workdir.mkdir(parents=True)
    plan = session._confinement([sys.executable, '-c', 'pass'], workdir, {'PATH': os.environ['PATH']})
    assert isinstance(plan, confine.Plan) and plan.record['writable'] == [str(workdir.resolve())]
    session.root = (tmp_path / 'legacy-construction').resolve()
    assert session._confinement([sys.executable, '-c', 'pass'], workdir, {}) is None


def test_authored_analysis_of_a_controller_study_never_reads_its_withheld_reference(tmp_path, monkeypatch, sandboxed):
    from ravel.physics import authored_analysis
    run, _ = controller_run(tmp_path, monkeypatch)
    base = run / 'study'
    (base / 'reference').mkdir(parents=True)
    (base / 'reference' / 'published.json').write_text('{"withheld": "reference-canary-31aa"}')
    (base / 'data.json').write_text('{"x": 1}')
    code = tmp_path / 'code.py'
    code.write_text('import json\nsteps = json.load(open("step-inputs.json"))\n'
                    'data = json.load(open(steps["inputs"]["data"]))\nseen = {}\n'
                    'try:\n    open(steps["reference"]).read(); seen["reference"] = "ALLOWED"\n'
                    'except OSError:\n    seen["reference"] = "denied"\n'
                    'json.dump({"x": data["x"], **seen}, open("out.json", "w"))\n')
    task = {'io_contract': {'inputs': [{'name': 'data', 'path': 'data.json'}], 'outputs': [{'path': 'out.json'}]},
            'parameters': [], 'reference_paths': ['reference'], 'timeout_seconds': 60}
    # The code receives the withheld path by name to try it; the contract still lists only data.json.
    original = authored_analysis.json.dumps

    def with_reference(value, *a, **k):
        if isinstance(value, dict) and 'inputs' in value and 'outputs' in value:
            value = {**value, 'reference': str(base / 'reference' / 'published.json')}
        return original(value, *a, **k)
    monkeypatch.setattr(authored_analysis.json, 'dumps', with_reference)
    workdir = run / 'attempts' / 'a1' if False else tmp_path / 'attempt-1'
    observation = authored_analysis.execute(code, workdir, task, base)
    assert observation['exit_code'] == 0, observation['stderr_tail']
    result = json.loads((workdir / 'out.json').read_text())
    assert result == {'x': 1, 'reference': 'denied'}
    assert observation['confinement']['launch']['withheld'] == [str((base / 'reference').resolve())]


def test_SW24_remote_job_ceiling_comes_from_operator(tmp_path, monkeypatch):
    from ravel.workflow import execution_backend
    run, _ = controller_run(tmp_path, monkeypatch)
    monkeypatch.setenv('RAVEL_REMOTE_JOB_CEILING', '64')
    assert execution_backend.remote_ceiling(run) == 1
    operator(monkeypatch, {'remote_job_ceiling': 3})
    assert execution_backend.remote_ceiling(run) == 3
    assert execution_backend.remote_ceiling() == 64, 'a legacy caller keeps the documented override'
    operator(monkeypatch, {'remote_job_ceiling': 0})
    with pytest.raises(ValueError):
        execution_backend.remote_ceiling(run)


def test_the_scan_audit_reports_an_omitted_manifest_point(tmp_path, monkeypatch):
    from ravel.workflow import launch_authorization, workflow_state
    points = []
    for tag in ('point-a', 'point-b'):
        root = tmp_path / tag
        (root / 'inputs').mkdir(parents=True)
        (root / 'inputs' / 'native_execution_plan.json').write_text(json.dumps(
            {'required_compute_plan': 'scan', 'plan_sha256': tag}))
        points.append({'tag': tag, 'run_dir': str(root)})
    monkeypatch.setattr(workflow_state, 'verify_checkin2_go', lambda path: [])
    monkeypatch.setattr(launch_authorization, 'audit_launches', lambda path, **kw: [])
    manifest = {'points': points}
    assert launch_authorization.audit_scan_launches(tmp_path, manifest, {'points': [
        {'tag': 'point-a'}, {'tag': 'point-b'}]}) == []
    errors = launch_authorization.audit_scan_launches(tmp_path, manifest, {'points': [{'tag': 'point-a'}]})
    assert len(errors) == 1 and 'omits manifest point(s) point-b' in errors[0]
    # A point the population states as a hole is not omitted; one absent from it is.
    hole = {'points': [{'tag': 'point-a'}], 'n_missing': 1, 'missing_tags': ['point-b'],
            'point_population': [{'tag': 'point-a', 'status': 'completed'}, {'tag': 'point-b', 'status': 'missing'}]}
    assert launch_authorization.audit_scan_launches(tmp_path, manifest, hole) == []
    errors = launch_authorization.audit_scan_launches(tmp_path, manifest, {
        **hole, 'point_population': hole['point_population'][:1]})
    assert len(errors) == 1 and 'omits manifest point(s) point-b' in errors[0]
    errors = launch_authorization.audit_scan_launches(tmp_path, manifest, {**hole, 'n_missing': 0, 'missing_tags': []})
    assert len(errors) == 1 and 'claims full coverage while point(s) point-b' in errors[0]
    errors = launch_authorization.audit_scan_launches(tmp_path, manifest, {
        **hole, 'point_population': [{'tag': 'point-a', 'status': 'missing'}, {'tag': 'point-b', 'status': 'missing'}]})
    assert len(errors) == 1 and 'does not record as completed' in errors[0]
    errors = launch_authorization.audit_scan_launches(tmp_path, manifest, {
        **hole, 'point_population': [*hole['point_population'], {'tag': 'point-c', 'status': 'missing'}]})
    assert len(errors) == 1 and 'unmanifested point tag' in errors[0]
