"""Autonomous resource contracts at the actual supervisor and scan entry points.

Native transport-contract controls isolate existing legacy native-plan approvals
from mode issuance: their approval seam is explicitly synthetic, and they do not
qualify delegated approval or physics. Science uses real goal-bound approval.
Only process transport is inert in the science positive control.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from ravel.physics import native_pipeline as native
from ravel.workflow import execution, launch_authorization as launch, operating_mode as mode
from ravel.workflow import science, stage_supervisor as supervisor, scan_orchestrator as scan
from ravel.workflow.state_io import atomic_json, read_json
from test_operating_mode import operator, set_operator_mode, authorize_run, initialize_trusted  # noqa: F401


def configure(project, *, stages, seconds=100000, events=20, redos=0):
    bounds = deepcopy(mode.DEFAULT_BOUNDS)
    bounds.update(allowed_stages=stages, max_seconds=seconds, max_events=events, max_redos=redos)
    set_operator_mode('autonomous', project=project, bounds=bounds)


def inert_transport(monkeypatch):
    # Patch the Popen immediately at its transport boundary. Other subprocess
    # readers (process census, environment inspection) continue to run normally.
    original = launch.subprocess.Popen
    targets = {}

    def popen(command, **kwargs):
        key = tuple(map(str, command))
        if key in targets:
            for output in targets[key]:
                path = Path(output)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.suffix == '.json': atomic_json(path, {'fictional_transport_output': True})
                else: path.write_text('Synthetic transport output; no physics claim\n')
            process = original([sys.executable, '-c', "print('Inert transport completed')"], **kwargs)
            process.command = list(command)
            return process
        return original(command, **kwargs)

    monkeypatch.setattr(launch.subprocess, 'Popen', popen)
    return targets


def usage(root):
    value = mode.frozen(root)
    return [row['record'] for row in mode.rdj_custody._read(mode._ledger(value['budget_root'], 'usage'))]


def test_actual_science_supervisor_derives_zero_generated_events(operator, monkeypatch):
    from method_decision_fixture import admit_method
    from test_autonomy_final_results import linked_parent
    from test_research_cycle import specification
    configure(operator, stages=['science'], seconds=60)
    parent = linked_parent(operator, 'Calculate the supplied two-record diagnostic.')
    original = read_json(parent['path'])
    parent_root = operator / 'parent'
    parent_path = parent_root / 'inputs/task_contract.json'
    atomic_json(parent_path, original)
    parent = {'path': str(parent_path), 'sha256': execution.file_hash(parent_path),
              'size': parent_path.stat().st_size}
    # The original request receives its mode before any child is initialized.
    initialize_trusted(parent_root, original, project=operator)
    source = specification(operator, 'supplied', grouped=False)
    spec = read_json(source['path'])
    spec['goal_binding'] = {'contract': parent, 'assignment_id': 'whole-child'}
    atomic_json(source['path'], spec)
    root = operator / 'science-run'
    science.plan(root, source['path'])
    # Older science integration builds do not yet initialize the mode themselves.
    initialize_trusted(root, spec, project=operator)
    admit_method(root)
    mode.bind_plan(root)
    assert science.approve_delegated(root) == 0
    proposal = science.verify_plan(root, approved=True)
    stage = proposal['stages'][0]
    targets = inert_transport(monkeypatch)
    targets[tuple(stage['command'])] = []
    # The deliberately inert worker produces none of the scientific outputs.
    # The launch and reservation must still happen through the real supervisor.
    science.run(root)
    authorized = next(e for e in launch._events(root) if e['event'] == 'authorized')
    assert authorized['context']['kind'] == 'science-stage'
    assert authorized['context']['events'] == 0
    assert authorized['context']['resource_events'] == 0
    assert authorized['context']['max_seconds'] == proposal['max_seconds']
    assert usage(root)[0]['events'] == 0
    assert usage(root)[0]['max_seconds'] == proposal['max_seconds']


@pytest.fixture
def native_transport_contract(operator, monkeypatch, request):
    """Real saved native plan, synthetic approval seam, real mode reservations.

    This fixture tests the native caller integration, not approval admission.
    The separate science test above exercises actual delegated approval.
    """
    from test_native_dispatch import configuration, stub_backend
    from method_decision_fixture import admit_method
    stub_backend(operator, monkeypatch)
    root = operator / 'native-run'
    root.mkdir()
    # Native configuration paths are relative to the run, including the supplied
    # package manifest and cards; keep the fixture assets in that same directory.
    config = configuration(root)
    plan = native.build_execution_plan(root, config)
    saved = native.write_plan(plan)
    options = getattr(request, 'param', {})
    configure(operator, stages=options.get('stages', [s['stage'] for s in plan['stages']]),
              seconds=options.get('seconds', 100000), events=options.get('events', 20))
    initialize_trusted(root, {'prompt': 'Synthetic native transport contract.'}, project=operator)
    for stage in plan['stages']:
        for name in stage['inputs']:
            path = Path(name)
            if not path.exists() and path.is_relative_to(root / 'inputs'):
                atomic_json(path, {})
    # The fake approval transport returns only after the normalizer has loaded
    # the saved source-bound plan. It never supplies resource context values.
    def synthetic_approval(value):
        if value != native.load_plan(saved):
            raise ValueError('synthetic approved native plan changed')
        return True
    monkeypatch.setattr(native, 'verify_execution_approval', synthetic_approval)
    monkeypatch.setattr(launch, '_capture', lambda *a, **k: {
        'required_plan': plan['required_compute_plan'], 'approval': {'path': str(saved), 'sha256': execution.file_hash(saved)},
        'approval_inputs': [], 'go': None, 'go_inputs': [], 'review': None, 'review_inputs': []})
    monkeypatch.setattr(launch, '_historical_errors', lambda *a, **k: None)
    # No actual native stage input/output exists in this transport fixture. The
    # plan specification is retained, while native engine qualification remains
    # outside this test's synthetic admission seam.
    admit_method(root, 'new_events', refresh=False)
    return root, plan


def test_actual_scan_dispatch_records_attempt_without_double_reserving(native_transport_contract, monkeypatch):
    root, plan = native_transport_contract
    from ravel.paths import module_command
    targets = inert_transport(monkeypatch)
    command = module_command('ravel.physics.native_pipeline', 'run', '--plan', plan['plan_path'])
    targets[tuple(command)] = []
    point = {'tag': 'toy', 'run_dir': str(root), 'config': plan['config']}
    args = SimpleNamespace(backend='native', go=True)
    process = scan.launch_point(point, {'points': [point]}, args, plan=plan)
    assert process.command == command
    assert process.wait(timeout=10) == 0
    context = launch._events(root)[0]['context']
    assert context['stage'] == 'scan-dispatch' and context['resource_reservation'] == 'orchestration'
    assert context['resource_events'] == 0 and context['max_seconds'] == 0
    assert context['resource_stages'] == [s['stage'] for s in plan['stages']]
    assert usage(root)[0]['max_seconds'] == 0 and usage(root)[0]['events'] == 0
    with pytest.raises(ValueError, match='redo ceiling'):
        scan.launch_point(point, {'points': [point]}, args, plan=plan)


@pytest.mark.parametrize('mutation', ['command', 'rung', 'hash'])
def test_scan_dispatch_cannot_forge_wrapper_exemption(native_transport_contract, monkeypatch, mutation):
    root, plan = native_transport_contract
    from ravel.paths import module_command
    command = module_command('ravel.physics.native_pipeline', 'run', '--plan', plan['plan_path'])
    context = {'kind': 'scan-dispatch', 'plan_sha256': plan['plan_sha256'],
               'resource_reservation': 'orchestration', 'resource_events': 0}
    rung = plan['required_compute_plan']
    if mutation == 'command': command.append('--forged')
    elif mutation == 'rung': rung = 'full'
    elif mutation == 'hash': context['plan_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='scope|plan|rung|command'):
        launch.verified_resource_context(root, rung, command, context)
    assert usage(root) == []


@pytest.mark.parametrize('native_transport_contract', [{'stages': ['madgraph']}], indirect=True)
def test_scan_dispatch_requires_every_actual_stage_in_scope(native_transport_contract, monkeypatch):
    root, plan = native_transport_contract
    point = {'tag': 'toy', 'run_dir': str(root), 'config': plan['config']}
    with pytest.raises(ValueError, match='stage scope'):
        scan.launch_point(point, {'points': [point]}, SimpleNamespace(backend='native', go=True), plan=plan)
    assert usage(root) == []


def test_actual_native_supervisor_charges_generation_once(native_transport_contract, monkeypatch):
    root, plan = native_transport_contract
    targets = inert_transport(monkeypatch)
    selected = plan['stages'][:next(i+1 for i,s in enumerate(plan['stages']) if s['stage']=='pythia')]
    assert 'madgraph' in [s['stage'] for s in selected]
    for stage in selected:
        targets[tuple(stage['command'])] = stage['outputs']
        result = supervisor.supervise(stage['stage'], str(root), plan['nevents'],
            str(native.log_root(plan) / (stage['stage'] + '.log')), stage['command'],
            inputs=stage['inputs'], outputs=stage['outputs'], depends_on=stage['depends_on'],
            cwd=str(root), authorization_plan=plan, poll=.01, grace=.1)
        if result != 0:
            import json
            raise AssertionError(json.dumps({k:v for k,v in execution.load_execution(root)['stages'][stage['stage']].items()
                if k in {'stage','status','error','exit_code','cleanup'}}, sort_keys=True))
    rows = usage(root)
    assert [r['stage'] for r in rows] == [s['stage'] for s in selected]
    assert [r['events'] for r in rows] == [plan['nevents'] if s['stage']=='madgraph' else 0 for s in selected]
    authorized = [e for e in launch._events(root) if e['event'] == 'authorized']
    assert all(e['context']['events'] == plan['nevents'] for e in authorized)
    assert sum(r['events'] for r in rows) == plan['nevents']


@pytest.mark.parametrize('override', ['timeout', 'workload'])
def test_actual_native_supervisor_refuses_resource_mismatch(native_transport_contract, monkeypatch, override):
    root, plan = native_transport_contract
    stage = plan['stages'][0]
    targets = inert_transport(monkeypatch)
    targets[tuple(stage['command'])] = stage['outputs']
    result = supervisor.supervise(stage['stage'], str(root), plan['nevents'] + (override == 'workload'),
        str(native.log_root(plan) / (stage['stage'] + '.log')), stage['command'],
        inputs=stage['inputs'], outputs=stage['outputs'], depends_on=stage['depends_on'], cwd=str(root),
        authorization_plan=plan, poll=.01, grace=.1, **({'kill_secs': 1} if override == 'timeout' else {}))
    assert result != 0
    assert usage(root) == []
    assert launch._events(root) == []


@pytest.mark.parametrize('native_transport_contract', [{'seconds': 1}], indirect=True)
def test_actual_native_supervisor_cannot_shrink_a_plan_to_fit_the_grant(native_transport_contract, monkeypatch):
    root, plan = native_transport_contract
    stage = plan['stages'][0]
    targets = inert_transport(monkeypatch)
    targets[tuple(stage['command'])] = stage['outputs']
    result = supervisor.supervise(stage['stage'], str(root), plan['nevents'],
        str(native.log_root(plan) / (stage['stage'] + '.log')), stage['command'],
        inputs=stage['inputs'], outputs=stage['outputs'], depends_on=stage['depends_on'], cwd=str(root),
        authorization_plan=plan, poll=.01, grace=.1)
    assert result != 0
    assert usage(root) == []
    assert launch._events(root) == []
