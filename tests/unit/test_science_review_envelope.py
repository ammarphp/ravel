"""Pure science envelope and journal controls; no worker process or external tool."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from ravel.workflow import execution, physics_review as review, science, launch_authorization, stage_supervisor
from ravel.workflow.state_io import atomic_json, read_json
from test_physics_review import policy
from bound_review import bound_review


def specification(base, *, copied=False):
    atomic_json(base / 'events.json', {'weight': 1, 'held': 'original source'})
    p = policy()
    p.update(allowed_stages=['science'], allowed_changed_paths=['inputs/science-mutable/events.json'] if copied else [science.EXECUTION_TASK])
    contract = {'task_fields': [] if copied else ['/config/target_ctau/value'],
                'input_slots': [{'task_path': '/config/events_file', 'run_path': 'inputs/science-mutable/events.json',
                                 'fields': ['/weight']}] if copied else []}
    return {'schema_version': 2, 'mode': 'domain', 'source': 'Explicit synthetic engineering control',
            'assumptions': ['No detector or independent physics validation is inferred'], 'max_seconds': 45,
            'max_attempts': 3, 'approval_mode': 'scripted_yes',
            'task': {'domain': 'llp', 'config': {'operation': 'reweight', 'events_file': 'events.json',
                     'target_ctau': {'value': 2, 'unit': 'mm'}, 'source_ctau': {'value': 1, 'unit': 'mm'}}},
            'review_policy': {'schema_version': 1, 'policy': p, 'correction_contract': contract}}


@pytest.fixture
def planned(tmp_path, monkeypatch):
    # A synthetic binding isolates immutable scientific custody from concurrent
    # edits to development source; actual module launches are tested after freeze.
    def small_binding(rd, stage, command, inputs, outputs, parents, cwd):
        executable = str(Path(sys.executable).resolve())
        augmented = list(inputs) + ([executable] if executable not in inputs else [])
        binding = {'command': list(command), 'cwd': str(Path(cwd).resolve()), 'inputs': augmented,
                   'outputs': list(outputs), 'parents': {}, 'runtime': execution.runtime_context(),
                   'input_snapshot': execution.snapshot(rd, augmented)}
        binding['fingerprint'] = execution.digest(binding)
        return binding
    monkeypatch.setattr(execution, 'plan_stage', small_binding)
    # Synthetic receipts below are explicitly not process-launch evidence.
    # Retained authorization snapshots have separate pure controls in this file;
    # real module receipt chains are checked after the implementation freeze.
    monkeypatch.setattr(launch_authorization, 'audit_launches', lambda *a, **k: [])
    source = tmp_path / 'spec.json'
    atomic_json(source, specification(tmp_path))
    rd = tmp_path / 'run'
    science.plan(rd, source)
    from test_method_selection import write_record, record
    from ravel.workflow.method_selection import refresh_checkin
    write_record(rd, record('rough_estimate'))
    refresh_checkin(rd)
    science.approve(rd, 'Approve this exact synthetic bounded envelope', scripted=True)
    return rd, source


def token(rd, number=1, admission=None):
    attempt = {'attempt': number, 'plan_sha256': execution.file_hash(rd / science.PLAN),
               'budget_seconds': 45, 'started_utc': execution.utc_now(),
               'correction_id': admission['correction_id'] if admission else None,
               'correction_plan_sha256': execution.file_hash(rd / science._correction_path(number)) if admission else None}
    atomic_json(rd / 'execution_attempt.json', attempt)
    atomic_json(rd / 'logs/science-attempts' / f'{number:08d}.json', attempt)


def successful_evidence(rd, number=1):
    p = science.verify_plan(rd, approved=True)
    stage, binding, _ = science._selected(rd, p)
    record = execution.begin_attempt(rd, 'science', binding, stage['log'])
    out = rd / f'outputs/attempt-{number}'
    atomic_json(out / 'result.json', {'status': 'passed', 'physics_validated': False, 'value': number})
    atomic_json(out / 'recipe.json', {'task': science.execution_spec(rd)['task']})
    atomic_json(out / 'verification.json', {'passed': True, 'scope': 'domain', 'physics_validated': False,
                                          'expert_review': False, 'result_sha256': execution.file_hash(out / 'result.json')})
    atomic_json(out / 'checkin2.json', {'schema_version': 1, 'kind': 'checkin2', 'sections': {
        'waypoint': 'Explicit synthetic control', 'expectation': 'Bounded arithmetic evidence',
        'ask': {'options': ['GO', 'ADJUST']}}})
    (rd / stage['log']).write_text('Synthetic retained receipt fixture\n')
    assert execution.finish_attempt(rd, record, 0) == 0
    return record


def checks(rd, record, number, status):
    out = f'outputs/attempt-{number}/result.json'
    atomic_json(rd / f'inputs/checks-{number}.json', {'schema_version': 1, 'checks': [
        {'id': name, 'status': value, 'attempt_ids': [record['attempt_id']],
         'evidence': [{'path': out, 'location': '$.value'}]}
        for name, value in [('integrity', 'pass'), ('agreement', status)]]})


def test_approval_binds_actual_science_documents_without_native_receipt(planned):
    rd, _ = planned
    assert science.verify_approval_envelope(rd) == []
    assert not (rd / 'inputs/checkin1_approval.json').exists()
    assert [Path(p).name for p in science.approval_input_paths(rd)] == [
        'science-plan.json', 'science.json', 'checkin1.json', 'physics_review_policy.json', 'method-decision.json']
    approval_hash = execution.file_hash(rd / science.APPROVAL)
    document = read_json(rd / science.EXECUTION_TASK)
    document['task']['config']['target_ctau']['value'] = 3
    atomic_json(rd / science.EXECUTION_TASK, document)
    assert science.verify_approval_envelope(rd) == []
    assert execution.file_hash(rd / science.APPROVAL) == approval_hash
    token(rd)
    selected = science.launch_binding(rd, 'science')
    context = {'stage_spec': review._stage_spec(rd, {**selected['stage'], 'inputs': selected['binding']['inputs']}),
               'max_seconds': 45, 'review_action': 'bulk'}
    assert 'original approval' in '; '.join(science.verify_launch(rd, 'science', selected['stage']['command'], context))


@pytest.mark.parametrize('change', ['budget', 'unit', 'mode', 'backend', 'nonnumeric'])
def test_numeric_envelope_rejects_semantic_or_unbounded_change(planned, change):
    rd, _ = planned
    task = read_json(rd / science.EXECUTION_TASK)
    if change == 'budget':
        p = read_json(rd / science.PLAN)
        p['max_seconds'] = 900
        atomic_json(rd / science.PLAN, p)
    elif change == 'unit':
        task['task']['config']['target_ctau']['unit'] = 'm'
    elif change == 'mode':
        task['task']['domain'] = 'model-probe'
    elif change == 'backend':
        task['task']['backend'] = 'native'
    else:
        task['task']['config']['target_ctau']['value'] = True
    atomic_json(rd / science.EXECUTION_TASK, task)
    assert science.verify_approval_envelope(rd)


def test_prospective_policy_and_budget_cannot_be_widened(planned):
    rd, _ = planned
    p = read_json(rd / science.REVIEW_POLICY)
    p['max_redos'] = 30
    atomic_json(rd / science.REVIEW_POLICY, p)
    assert science.verify_approval_envelope(rd)
    assert science.packet(rd)['lifecycle_verdict'] == 'FAIL'


def test_real_science_waypoint_uses_current_attempt_and_registered_science_approval(planned):
    rd, _ = planned
    token(rd)
    record = successful_evidence(rd)
    checks(rd, record, 1, 'fail')
    cycle = review.open_cycle(rd, effective_settings=science.review_effective_settings(rd),
                              stage_receipts=[record['attempt_record']], check_results='inputs/checks-1.json')
    pins = {pin['path'] for pin in cycle['snapshots']}
    assert 'outputs/attempt-1/checkin2.json' in pins
    assert 'inputs/science-approval.json' in pins
    assert 'inputs/checkin2.json' not in pins
    assert science.packet(rd)['lifecycle_verdict'] == 'PENDING'
    assert 'inputs/science-approval.json' in {pin['path'] for pin in read_json(rd / review.REGISTRATION)['bindings']}


def test_exact_numeric_repair_keeps_approval_and_requires_fresh_review(planned):
    rd, _ = planned
    token(rd)
    first = successful_evidence(rd)
    checks(rd, first, 1, 'fail')
    review.open_cycle(rd, effective_settings=science.review_effective_settings(rd),
                      stage_receipts=[first['attempt_record']], check_results='inputs/checks-1.json')
    bound_review(rd, role='physics_critic', verdict='send_back', summary='Explicit numeric defect',
        findings=[{'id': 'F1', 'summary': 'Repair the declared numeric setting',
                   'evidence': [{'path': 'outputs/attempt-1/result.json', 'location': '$.value'}],
                   'check_ids': ['agreement'], 'required_paths': [science.EXECUTION_TASK], 'required_stages': ['science']}])
    initial_hashes = {path: execution.file_hash(rd / path) for path in [science.SPEC, science.PLAN, science.APPROVAL]}
    task = read_json(rd / science.EXECUTION_TASK)
    task['task']['config']['target_ctau']['value'] = 3
    atomic_json(rd / science.EXECUTION_TASK, task)
    admission = science.correct(rd, actor_id='physicist', changed_paths=[science.EXECUTION_TASK], recheck_checks=['agreement'])
    assert science.packet(rd)['execution']['status'] == 'correction_admitted'
    assert science.packet(rd)['lifecycle_verdict'] == 'PENDING'
    token(rd, 2, admission)
    selected = science.launch_binding(rd, 'science')
    context = {'kind': 'science-stage', 'stage': 'science', 'review_action': 'correction', 'max_seconds': 45,
               'plan_sha256': execution.file_hash(rd / science.PLAN),
               'stage_spec': review._stage_spec(rd, {**selected['stage'], 'inputs': selected['binding']['inputs']})}
    captured = launch_authorization._capture(rd, 'science', command=selected['stage']['command'], context=context)
    launch_authorization._historical_errors({'authorization': captured, 'context': context,
        'command': selected['stage']['command'], 'utc': launch_authorization.operational_utc()})
    second = successful_evidence(rd, 2)
    assert first['attempt_id'] != second['attempt_id']
    checks(rd, second, 2, 'pass')
    review.open_cycle(rd, effective_settings=science.review_effective_settings(rd),
        stage_receipts=[second['attempt_record']], check_results='inputs/checks-2.json', correction_id=admission['correction_id'])
    assert science.packet(rd)['lifecycle_verdict'] == 'PENDING'
    # Recorded votes are bound responses of dispatched roles; a declared reviewer name is advice only.
    for role in ['physics_critic', 'skeptical_verifier', 'physics_decider']:
        bound_review(rd, role=role, verdict='accept', summary='Located fresh repair evidence',
                     closes=['F1'], claim_scope='reproduction')
    assert science.packet(rd)['lifecycle_verdict'] == 'PASS'
    assert {path: execution.file_hash(rd / path) for path in initial_hashes} == initial_hashes
    assert (rd / 'outputs/attempt-1/result.json').exists()
    assert (rd / 'outputs/attempt-2/result.json').exists()


def test_mutable_copies_preserve_original_files(planned, tmp_path):
    _, _ = planned
    source = tmp_path / 'copied.json'
    atomic_json(source, specification(tmp_path, copied=True))
    rd = tmp_path / 'copied-run'
    science.plan(rd, source)
    from test_method_selection import write_record, record
    from ravel.workflow.method_selection import refresh_checkin
    write_record(rd, record('rough_estimate'))
    refresh_checkin(rd)
    science.approve(rd, 'Approve explicit copied-input fields', scripted=True)
    original = (tmp_path / 'events.json').read_bytes()
    copied = rd / 'inputs/science-mutable/events.json'
    document = read_json(copied)
    document['weight'] = 2
    atomic_json(copied, document)
    assert science.verify_approval_envelope(rd) == []
    assert (tmp_path / 'events.json').read_bytes() == original
    document['held'] = 'replaced input structure'
    atomic_json(copied, document)
    assert science.verify_approval_envelope(rd)


def test_retained_initial_science_receipt_replays_frozen_approval(planned):
    rd, _ = planned
    token(rd)
    selected = science.launch_binding(rd, 'science')
    context = {'kind': 'science-stage', 'stage': 'science', 'review_action': 'bulk', 'max_seconds': 45,
               'plan_sha256': execution.file_hash(rd / science.PLAN),
               'stage_spec': review._stage_spec(rd, {**selected['stage'], 'inputs': selected['binding']['inputs']})}
    snapshot = launch_authorization._capture(rd, 'science', command=selected['stage']['command'], context=context)
    event = {'utc': launch_authorization.operational_utc(), 'command': selected['stage']['command'],
             'context': context, 'authorization': snapshot}
    assert science.validate_authorization_snapshot(snapshot, event) == []
    launch_authorization._historical_errors(event)
    atomic_json(rd / science.APPROVAL, {'late': 'replacement cannot backfill old authorization'})
    launch_authorization._historical_errors(event)
    changed = deepcopy(event)
    changed['authorization']['approval']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='retained science'):
        launch_authorization._historical_errors(changed)


def test_direct_supervisor_budget_change_refuses_before_execution_attempt(planned, monkeypatch):
    rd, _ = planned
    token(rd)
    stage = science.verify_plan(rd, approved=True)['stages'][0]
    monkeypatch.setattr(execution, 'begin_attempt', lambda *a, **k: pytest.fail('invalid launch must not create an execution attempt'))
    with pytest.raises(ValueError, match='hard budget'):
        stage_supervisor.supervise('science', str(rd), 0, stage['log'], stage['command'], kill_secs=900,
            inputs=stage['inputs'], outputs=stage['outputs'], depends_on=[], cwd=str(rd))


def test_admitted_run_precheck_uses_the_supervisors_augmented_inputs(planned, monkeypatch):
    rd, _ = planned
    token(rd)
    first = successful_evidence(rd)
    checks(rd, first, 1, 'fail')
    review.open_cycle(rd, effective_settings=science.review_effective_settings(rd),
                      stage_receipts=[first['attempt_record']], check_results='inputs/checks-1.json')
    bound_review(rd, role='physics_critic', verdict='send_back', summary='Explicit numeric defect',
        findings=[{'id': 'F1', 'summary': 'Repair the declared numeric setting',
                   'evidence': [{'path': 'outputs/attempt-1/result.json', 'location': '$.value'}],
                   'check_ids': ['agreement'], 'required_paths': [science.EXECUTION_TASK], 'required_stages': ['science']}])
    task = read_json(rd / science.EXECUTION_TASK)
    task['task']['config']['target_ctau']['value'] = 3
    atomic_json(rd / science.EXECUTION_TASK, task)
    science.correct(rd, actor_id='physicist', changed_paths=[science.EXECUTION_TASK], recheck_checks=['agreement'])
    class ReachedSupervisor(Exception):
        pass
    def held_supervisor(*args, **kwargs):
        assert read_json(rd / 'execution_attempt.json')['attempt'] == 2
        raise ReachedSupervisor()
    monkeypatch.setattr(stage_supervisor, 'supervise', held_supervisor)
    with pytest.raises(ReachedSupervisor):
        science.run(rd)


def test_built_rivet_requires_prospective_review_before_run_creation(tmp_path, monkeypatch):
    spec = specification(tmp_path)
    spec.update(schema_version=1, mode='analyze', task={'backend': 'rivet-built'})
    del spec['max_attempts'], spec['review_policy']
    monkeypatch.setattr(science, 'adapter', lambda _: SimpleNamespace(validate=lambda _: None))
    atomic_json(tmp_path / 'built.json', spec)
    with pytest.raises(ValueError, match='prospective version 2'):
        science.plan(tmp_path / 'built-run', tmp_path / 'built.json')
    assert not (tmp_path / 'built-run').exists()


@pytest.mark.parametrize('with_figures,adapter_status', [(False, 'passed'), (False, 'failed'), (True, 'passed')])
def test_built_rivet_worker_keeps_artifacts_and_result_status_in_selected_attempt(tmp_path, monkeypatch, with_figures, adapter_status):
    from ravel.physics import science_worker
    from ravel.plotting import science_figures
    rd = tmp_path / 'built-run'
    rd.mkdir()
    selected = rd / 'outputs/attempt-2'
    proposal = {'attempt': 2, 'output_directory': 'outputs/attempt-2', 'base_dir': str(tmp_path),
                'stage_binding': {'input_snapshot': {}}}
    spec = {'schema_version': 2, 'mode': 'analyze', 'task': {'backend': 'rivet-built'}, 'assumptions': []}
    calls = []
    def analyze(task, base, destination):
        calls.append(('analysis', destination))
        destination.mkdir()
        return {'status': adapter_status, 'physics_validated': False}
    def render(specification, result, base, destination):
        calls.append(('figures', destination))
        (destination / 'scalar-counters.json').write_text('{}\n')
        (destination / 'scalar-counters.md').write_text('| Counter | Value |\n| --- | --- |\n| events | 1 |\n')
        return {'figures': [{'stem': 'continuous-histogram', 'files': ['continuous-histogram.png']}] if with_figures else [],
                'tables': [{'stem': 'scalar-counters', 'files': ['scalar-counters.json', 'scalar-counters.md']}]}
    monkeypatch.setattr(science_worker, 'verify_worker', lambda _: proposal)
    monkeypatch.setattr(science_worker, 'execution_spec', lambda _: spec)
    monkeypatch.setattr(science_worker, 'adapter', lambda _: SimpleNamespace(run=analyze))
    monkeypatch.setattr(science_figures, 'render', render)
    assert science_worker.main([str(rd), '--attempt', '2']) == (0 if adapter_status == 'passed' else 3)
    assert calls == [('analysis', selected / 'analysis'), ('figures', selected / 'analysis')]
    receipt = read_json(selected / 'figures.json')
    assert receipt['figures'] == ([{'stem': 'analysis/continuous-histogram',
                                   'files': ['analysis/continuous-histogram.png']}] if with_figures else [])
    assert receipt['tables'] == [{'stem': 'analysis/scalar-counters',
                                 'files': ['analysis/scalar-counters.json', 'analysis/scalar-counters.md']}]
    for name in receipt['tables'][0]['files']:
        assert (selected / name).is_file()
        assert '](' + name + ')' in (selected / 'RESULT.md').read_text()
    assert read_json(selected / 'result.json')['status'] == adapter_status
    assert read_json(selected / 'verification.json')['passed'] is (adapter_status == 'passed')
    assert not (rd / 'outputs/attempt-1').exists()
    assert not (rd / 'work').exists()
