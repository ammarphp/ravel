"""Closed native task declarations preserve approval identity and real input custody."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from ravel.controller import operation_tasks
from ravel.controller.confine import commitments
from ravel.controller.judgment import planning, schemas
from ravel.controller.step import custody
from ravel.controller.step.services import digest
from ravel.physics import measurement


class Store:
    def __init__(self):
        self.rows = []

    def append(self, kind, record):
        identifier = f'{kind}-{len(self.rows)}'
        self.rows.append({'kind': kind, 'id': identifier, 'record': deepcopy(record)})
        return identifier

    def scan(self, kind):
        return deepcopy([row for row in self.rows if row['kind'] == kind])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path):
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    data = run / 'inputs/measurement.json'
    # Materialization validates the task and file custody, without running inference.
    data.write_text('{}\n')
    task = run / 'inputs/task.json'
    task.write_text(json.dumps({'schema_version': 1, 'input': data.name,
                                'inference': 'goodness_of_fit', 'signal_strength': 1.0}))
    step = {'id': 'measure', 'kind': 'operate', 'operation': 'measurement', 'role': 'inference',
            'depends_on': [],
            'inputs': [{'artifact': 'inputs/task.json', 'sha256': sha(task)},
                       {'artifact': 'inputs/measurement.json', 'sha256': sha(data)}],
            'outputs': [{'path': 'outputs/result.json', 'kind': 'json', 'required': True}],
            'parameters': {'operation_task': {'materializer': 'science-mode',
                                             'task_input': 'inputs/task.json',
                                             'result_output': 'outputs/result.json'}}}
    plan = {'sha256': 'approved-plan', 'route': {'id': 'judgment'}, 'steps': [step]}
    return Store(), plan, step, run, task, data


def judgment_row(step):
    return {key: deepcopy(step[key]) for key in ('id', 'kind', 'operation', 'role', 'inputs',
                                                'outputs', 'depends_on')} | {
        'purpose': 'Evaluate the supplied measurement task',
        'operation_task': deepcopy(step['parameters']['operation_task']),
        'budget_share': {'fraction': 1.0}, 'protocols': [], 'review': [], 'obligations': []}


def judgment_plan(row):
    return {'schema_version': 1, 'kind': 'judgment-plan', 'frame_sha256': 'a' * 64,
            'steps': [row], 'deliverables': [{'id': 'result', 'status': 'planned',
                                             'outputs': [{'step': row['id'],
                                                          'path': 'outputs/result.json'}]}]}


def test_schema_accepts_closed_operation_task(case):
    row = judgment_row(case[2])
    assert schemas.errors('judgment-plan.v1', judgment_plan(row)) == []


@pytest.mark.parametrize('change', ['inline-argv', 'extra-field', 'unknown-materializer'])
def test_schema_refuses_executable_or_open_declaration(case, change):
    row = judgment_row(case[2])
    if change == 'inline-argv':
        row['operation_task']['argv'] = [sys.executable, '-c', 'print(1)']
    elif change == 'extra-field':
        row['operation_task']['module'] = 'worker.selected'
    else:
        row['operation_task']['materializer'] = 'worker-selected'
    errors = schemas.errors('judgment-plan.v1', judgment_plan(row))
    assert errors and any('operation_task' in error for error in errors)


def test_controller_step_retains_and_copies_declaration(case):
    row = judgment_row(case[2])
    row['class'] = 'R2'
    original = deepcopy(row)
    compiled = planning.controller_step(row, inputs={}, deliverables=['result'])
    assert compiled['parameters']['operation_task'] == row['operation_task']
    assert compiled['operation'] == 'measurement'
    assert compiled['role'] == 'inference'
    value, adapter = operation_tasks.declaration(compiled)
    assert adapter is measurement
    value['result_output'] = 'outputs/changed.json'
    compiled['parameters']['operation_task']['result_output'] = 'outputs/other.json'
    assert row == original


@pytest.mark.parametrize('change', ['unsupported-operation', 'role-mismatch', 'undeclared-input',
                                   'undeclared-output', 'escaping-output', 'explicit-launch'])
def test_declaration_refuses_unregistered_or_unbound_request(case, change):
    step = case[2]
    if change == 'unsupported-operation':
        step['operation'] = 'calculate'
    elif change == 'role-mismatch':
        step['role'] = 'calculation'
    elif change == 'undeclared-input':
        step['parameters']['operation_task']['task_input'] = 'inputs/other.json'
    elif change == 'undeclared-output':
        step['parameters']['operation_task']['result_output'] = 'outputs/other.json'
    elif change == 'escaping-output':
        step['parameters']['operation_task']['result_output'] = 'outputs/../escape.json'
        step['outputs'][0]['path'] = 'outputs/../escape.json'
    else:
        step['parameters']['launch'] = {'argv': [sys.executable]}
    with pytest.raises(ValueError):
        operation_tasks.declaration(step)


def test_judgment_route_commits_registered_descriptor_and_task_bytes(case):
    store, plan, step, run, task, _ = case
    identifier = commitments.create(store, plan, run)
    assert commitments.verify(store, plan, step, run) == identifier
    assert commitments.create(store, plan, run) == identifier
    record = store.rows[0]['record']['steps'][0]
    assert record['native'] is True
    assert record['mode'] == 'input-bound-materializer'
    descriptor = record['materializer']
    assert descriptor == operation_tasks.descriptor(step)
    assert descriptor['adapter'] == 'operation-task'
    assert descriptor['implementation'] == 'ravel.physics.measurement'
    assert descriptor['interpreter'] == sys.executable
    assert descriptor['sources'] and all(len(row['sha256']) == 64 for row in descriptor['sources'])
    assert record['inputs'][0]['sha256'] == sha(task)
    assert 'argv_sha256' not in record


@pytest.mark.parametrize('change', ['task-bytes', 'source-binding'])
def test_commitment_refuses_task_bytes_or_retained_source_identity_change(case, change):
    store, plan, step, run, task, _ = case
    commitments.create(store, plan, run)
    if change == 'task-bytes':
        task.write_text(task.read_text() + '\n')
    else:
        # Corrupt the retained source binding, without mutating installed source files.
        source = store.rows[0]['record']['steps'][0]['materializer']['sources'][0]
        source['sha256'] = '0' * 64
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)
    with pytest.raises(ValueError):
        commitments.create(store, plan, run)


def test_validated_uses_real_measurement_task_contract(case):
    _, _, _, _, task, data = case
    assert operation_tasks._validated(measurement, task, [task, data]) == json.loads(task.read_text())
    malformed = json.loads(task.read_text())
    malformed['signal_strength'] = -1
    task.write_text(json.dumps(malformed))
    with pytest.raises(ValueError, match='signal_strength'):
        operation_tasks._validated(measurement, task, [task, data])


def test_validated_refuses_undeclared_measurement_data(case):
    _, _, _, _, task, _ = case
    with pytest.raises(ValueError, match='outside its declared input custody'):
        operation_tasks._validated(measurement, task, [task])


def materialize(case, monkeypatch):
    store, plan, step, run, *_ = case
    monkeypatch.setattr(operation_tasks.operations, 'current_plan', lambda *_: deepcopy(plan))
    return operation_tasks.materialize_launch(step, {'store': store, 'run_dir': run})


def test_materialize_retains_fixed_entrypoint_and_bound_scope(case, monkeypatch):
    _, plan, step, _, _, _ = case
    monkeypatch.setenv('PYTHONPATH', '/worker-selected/runtime')
    launch = materialize(case, monkeypatch)
    assert launch['argv'] == [sys.executable, '-m', 'ravel.controller.operation_tasks',
                              '--operation', 'measurement', '--task', '@input:inputs/task.json',
                              '--result', 'result.json', '--input', '@input:inputs/task.json',
                              '--input', '@input:inputs/measurement.json']
    assert launch['env'] == {'PYTHONPATH': str(Path(operation_tasks.__file__).resolve().parents[2]),
                             'PYTHONNOUSERSITE': '1'}
    assert launch['env'] == operation_tasks.descriptor(step)['environment'] and launch['reads'] == []
    assert launch['scope'] == {'operation': 'measurement', 'role': 'inference', 'step_id': 'measure',
                               'plan_sha256': plan['sha256'], 'task_input': 'inputs/task.json',
                               'operation_task_sha256': digest(step['parameters']['operation_task'])}


@pytest.mark.parametrize('change', ['task-bytes', 'data-bytes', 'unreceipted-input', 'undeclared-data'])
def test_materialize_checks_real_custody_and_native_input_closure(case, monkeypatch, change):
    _, _, step, _, task, data = case
    if change == 'task-bytes':
        task.write_text(task.read_text() + '\n')
    elif change == 'data-bytes':
        data.write_text('{"changed": true}')
    elif change == 'unreceipted-input':
        step['inputs'][1]['artifact'] = 'prepare:outputs/measurement.json'
    else:
        step['inputs'].pop()
    with pytest.raises(ValueError, match='custody'):
        materialize(case, monkeypatch)


def test_materialize_refuses_changed_retained_step(case, monkeypatch):
    store, plan, step, run, *_ = case
    retained = deepcopy(plan)
    monkeypatch.setattr(operation_tasks.operations, 'current_plan', lambda *_: retained)
    step['parameters']['operation_task']['result_output'] = 'outputs/other.json'
    step['outputs'][0]['path'] = 'outputs/other.json'
    with pytest.raises(ValueError, match='retained approved step'):
        operation_tasks.materialize_launch(step, {'store': store, 'run_dir': run})


def test_materialize_refuses_unaccepted_predecessor(case, monkeypatch):
    store, plan, step, run, _, data = case
    produced = run / 'steps/prepare/outputs/measurement.json'
    produced.parent.mkdir(parents=True)
    produced.write_bytes(data.read_bytes())
    artifact = 'prepare:outputs/measurement.json'
    step['depends_on'] = ['prepare']
    step['inputs'][1] = {'artifact': artifact, 'sha256': sha(produced)}
    plan['steps'].insert(0, {'id': 'prepare', 'depends_on': [], 'outputs': []})
    store.append(custody.CUSTODY, {'artifact': artifact, 'step_id': 'prepare', 'status': 'staged',
                                  'destination': 'steps/prepare/outputs/measurement.json',
                                  'sha256': sha(produced), 'inputs': []})
    with pytest.raises(ValueError, match='predecessor_not_accepted'):
        materialize(case, monkeypatch)


def test_commitment_refuses_changed_adapter_source_bytes(case, monkeypatch, tmp_path):
    store, plan, step, run, *_ = case
    adapter_source = tmp_path / 'measurement-adapter.py'
    adapter_source.write_text('"""Approved adapter source identity."""\n')
    monkeypatch.setattr(measurement, '__file__', str(adapter_source))
    identifier = commitments.create(store, plan, run)
    assert commitments.verify(store, plan, step, run) == identifier
    sources = store.rows[0]['record']['steps'][0]['materializer']['sources']
    assert {'path': str(adapter_source), 'sha256': sha(adapter_source)} in sources
    adapter_source.write_text('"""Changed adapter source identity."""\n')
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)
    with pytest.raises(ValueError):
        commitments.create(store, plan, run)


@pytest.fixture
def authored_case(tmp_path):
    """Inert helper controls; these tests make no confinement claim."""
    from ravel.physics import authored_analysis
    base, output = tmp_path / 'authored-inputs', tmp_path / 'authored-output'
    base.mkdir()
    output.mkdir()
    (base / 'spec.md').write_text('Exercise declared authored task postconditions.\n')
    code = base / 'attempt.py'
    code.write_text('pass\n')
    task = {'purpose': 'Exercise authored helper refusal with declared output postconditions',
            'specification': 'spec.md', 'code': code.name, 'timeout_seconds': 5,
            'io_contract': {'inputs': [], 'outputs': [
                {'path': 'result.json', 'kind': 'json', 'postconditions': [
                    {'pointer': '/value', 'check': 'positive'}]}]}}
    return authored_analysis, task, base, output, code


def test_authored_helper_refuses_forbidden_subprocess_before_effect(authored_case):
    adapter, task, base, output, code = authored_case
    code.write_text('import subprocess\nfrom pathlib import Path\n'
                    'Path("executed").write_text("unexpected execution")\n')
    adapter.validate(task)
    findings = adapter.lint(code.read_text(), task)
    assert any(row['rule'] == 'forbidden-module' and row['severity'] == 'error' for row in findings)
    with pytest.raises(ValueError, match='source lint'):
        operation_tasks._authored(adapter, task, base, output)
    assert not (output / 'authored-analysis').exists()
    assert not list(output.rglob('executed'))


@pytest.mark.parametrize(('failure', 'failure_class'), [
    ('missing-output', 'coding'), ('numeric-postcondition', 'coding'),
    ('scientific-postcondition', 'scientific_unresolved')])
def test_authored_helper_retains_failed_output_observation(authored_case, failure, failure_class):
    adapter, task, base, output, code = authored_case
    if failure != 'missing-output':
        code.write_text('from pathlib import Path\n'
                        'Path("result.json").write_text(\'{"value": -1}\\n\')\n')
    if failure == 'scientific-postcondition':
        task['io_contract']['outputs'][0]['postconditions'][0]['class'] = 'scientific_unresolved'
    adapter.validate(task)
    assert not any(row['severity'] == 'error' for row in adapter.lint(code.read_text(), task))
    with pytest.raises(ValueError, match='authored native attempt failed: ' + failure_class):
        operation_tasks._authored(adapter, task, base, output)
    folder = output / 'authored-analysis'
    observation = json.loads((folder / 'observation.json').read_text())
    assert observation['started'] is True and observation['exit_code'] == 0
    assert observation['timed_out'] is False
    assert observation['failure_class'] == failure_class
    assert observation['code_sha256'] == sha(code)
    assert observation['postconditions'] == adapter.check_outputs(folder / 'work', task)
    failed = [row for row in observation['postconditions'] if not row['passed']]
    assert len(failed) == 1
    assert failed[0]['check'] == ('exists' if failure == 'missing-output' else 'positive')
    assert failed[0]['class'] == failure_class
    assert adapter.classify(observation, observation['postconditions'], None) == failure_class


def test_authored_helper_refuses_reference_paths_before_execution(authored_case):
    adapter, task, base, output, code = authored_case
    reference = base / 'reference.json'
    reference.write_text('{"withheld": true}\n')
    task['reference_paths'] = [str(reference)]
    code.write_text('from pathlib import Path\nPath("executed").write_text("unexpected execution")\n')
    adapter.validate(task)
    assert not any(row['severity'] == 'error' for row in adapter.lint(code.read_text(), task))
    with pytest.raises(ValueError, match='does not admit withheld reference paths'):
        operation_tasks._authored(adapter, task, base, output)
    assert not (output / 'authored-analysis').exists()
    assert not list(output.rglob('executed'))
