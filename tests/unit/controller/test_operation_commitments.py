"""Approval commitments bind source identity and measured bytes without execution."""
from copy import deepcopy
import hashlib

import pytest

from ravel.controller.confine import commitments


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
    source = run / 'inputs/data.txt'
    source.write_text('approved input')
    executable = tmp_path / 'executor'
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o700)
    script = run / 'script.py'
    script.write_text('print(1)\n')
    producer = {'id': 'prepare', 'kind': 'author', 'inputs': [], 'depends_on': [],
                'outputs': [{'path': 'outputs/prepared.json', 'kind': 'json'}]}
    step = {'id': 'consume', 'kind': 'operate', 'operation': 'calculate', 'depends_on': ['prepare'],
            'inputs': [{'artifact': 'inputs/data.txt', 'sha256': sha(source)},
                       {'artifact': 'prepare:outputs/prepared.json', 'sha256': None}],
            'outputs': [], 'parameters': {'launch': {'argv': [str(executable), 'script.py',
                        '@input:inputs/data.txt', '@input:prepare:outputs/prepared.json']}}}
    plan = {'sha256': 'approved-plan', 'steps': [producer, step]}
    return Store(), plan, step, run, executable, script, source


def test_approval_reuse_and_deferred_identity(case):
    store, plan, step, run, *_ = case
    identifier = commitments.create(store, plan, run)
    assert commitments.create(store, plan, run) == identifier
    assert commitments.verify(store, plan, step, run) == identifier
    assert len(store.rows) == 1
    row = store.rows[0]['record']['steps'][0]
    assert row['native'] is True
    assert row['inputs'][0]['sha256'] == step['inputs'][0]['sha256']
    deferred = row['inputs'][1]
    assert deferred['deferred'] is True and deferred['producer'] == 'prepare'
    assert deferred['output'] == plan['steps'][0]['outputs'][0]
    assert 'sha256' not in deferred
    assert len(row['files']) == 2


@pytest.mark.parametrize('index', [4, 5, 6])
def test_executable_script_or_input_mutation_refuses(case, index):
    store, plan, step, run, *_ = case
    commitments.create(store, plan, run)
    case[index].write_text('changed bytes')
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)
    with pytest.raises(ValueError):
        commitments.create(store, plan, run)


def test_null_run_hash_is_measured_then_verified(case):
    store, plan, step, run, _, _, source = case
    step['inputs'][0]['sha256'] = None
    commitments.create(store, plan, run)
    assert store.rows[0]['record']['steps'][0]['inputs'][0]['sha256'] == sha(source)
    source.write_text('unapproved change')
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)


@pytest.mark.parametrize('change', ['foreign-plan', 'step', 'producer', 'output'])
def test_approval_identity_mutation_refuses(case, change):
    store, plan, step, run, *_ = case
    commitments.create(store, plan, run)
    if change == 'foreign-plan':
        plan['sha256'] = 'another-plan'
    elif change == 'step':
        step['parameters']['launch']['argv'].append('inline-content')
    elif change == 'producer':
        plan['steps'][0]['purpose'] = 'changed'
    else:
        plan['steps'][0]['outputs'][0]['path'] = 'outputs/other.json'
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)


@pytest.mark.parametrize('change', ['missing-producer', 'missing-dependency', 'missing-output',
                                   'missing-run-input', 'foreign-token', 'missing-argv', 'missing-plan-hash'])
def test_invalid_commitment_refuses(case, change):
    store, plan, step, run, _, _, source = case
    if change == 'missing-producer':
        plan['steps'].pop(0)
    elif change == 'missing-dependency':
        step['depends_on'] = []
    elif change == 'missing-output':
        plan['steps'][0]['outputs'] = []
    elif change == 'missing-run-input':
        source.unlink()
        step['inputs'][0]['sha256'] = None
    elif change == 'foreign-token':
        step['parameters']['launch']['argv'].append('@input:inputs/foreign')
    elif change == 'missing-argv':
        step['parameters'] = {}
    else:
        plan.pop('sha256')
    with pytest.raises(ValueError):
        commitments.create(store, plan, run)
    assert store.rows == []


def test_dependency_ancestor_is_allowed(case):
    store, plan, step, run, *_ = case
    plan['steps'].insert(1, {'id': 'middle', 'kind': 'author', 'depends_on': ['prepare'],
                             'inputs': [], 'outputs': []})
    step['depends_on'] = ['middle']
    identifier = commitments.create(store, plan, run)
    assert commitments.verify(store, plan, step, run) == identifier


def test_governed_worker_operation_needs_no_native_argv(case):
    store, plan, step, run, *_ = case
    step['kind'] = 'derive'
    step['parameters'] = {}
    identifier = commitments.create(store, plan, run)
    row = store.rows[0]['record']['steps'][0]
    assert row['native'] is False and 'argv_sha256' not in row
    assert commitments.verify(store, plan, step, run) == identifier


def test_worker_acquisition_without_a_launch_commits_inputs_not_an_argv(case):
    """An acquire step the governed step runs as a worker session (no launch, no installed route materializer)
    is committed like a worker step: its existing input bytes are pinned and no executable is required."""
    store, plan, step, run, *_ = case
    step['kind'] = 'acquire'
    step.pop('operation')
    step['parameters'] = {}
    plan['route'] = {'id': 'judgment', 'spec_sha256': None}
    identifier = commitments.create(store, plan, run)
    row = store.rows[0]['record']['steps'][0]
    assert row['native'] is False and 'argv_sha256' not in row and 'materializer' not in row
    assert row['inputs'][0]['sha256'] == step['inputs'][0]['sha256']
    assert commitments.verify(store, plan, step, run) == identifier
    # The same acquire step with a confined launch stays a native commitment of its executable and argv.
    launched = deepcopy(plan)
    launched['sha256'] = 'approved-plan-launched'
    launched['steps'][1]['parameters'] = {'launch': {'argv': deepcopy(case[4] and [str(case[4]), 'script.py'])}}
    commitments.create(store, launched, run)
    native = store.rows[1]['record']['steps'][0]
    assert native['native'] is True and native['argv_sha256']


def test_bare_executable_rebinding_refuses(case, monkeypatch, tmp_path):
    store, plan, step, run, executable, *_ = case
    step['parameters']['launch']['argv'][0] = 'executor'
    monkeypatch.setenv('PATH', str(executable.parent))
    commitments.create(store, plan, run)
    other = tmp_path / 'other'
    other.mkdir()
    replacement = other / 'executor'
    replacement.write_bytes(executable.read_bytes())
    replacement.chmod(0o700)
    monkeypatch.setenv('PATH', str(other))
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)


def test_missing_or_conflicting_protected_record_refuses(case):
    store, plan, step, run, *_ = case
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)
    commitments.create(store, plan, run)
    conflict = deepcopy(store.rows[0]['record'])
    conflict['steps'] = []
    store.append(commitments.KIND, conflict)
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)


@pytest.mark.parametrize('link', ['symlink', 'hardlink'])
def test_run_inputs_have_no_writable_aliases(case, link):
    import os
    store, plan, step, run, _, _, source = case
    alias = run / 'inputs/alias'
    if link == 'symlink':
        source.rename(alias)
        source.symlink_to(alias)
    else:
        os.link(source, alias)
    with pytest.raises(ValueError):
        commitments.create(store, plan, run)


def test_present_producer_output_is_pinned_and_mutation_refuses(case):
    store, plan, step, run, *_ = case
    produced = run / 'steps/prepare/outputs/prepared.json'
    produced.parent.mkdir(parents=True)
    produced.write_text('{"approved":true}')
    identifier = commitments.create(store, plan, run)
    entry = store.rows[0]['record']['steps'][0]['inputs'][1]
    assert entry['deferred'] is False
    assert entry['path'] == str(produced)
    assert entry['sha256'] == sha(produced)
    assert commitments.verify(store, plan, step, run) == identifier
    produced.write_text('{"changed":true}')
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)
    produced.unlink()
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)


def test_deferred_output_appearing_preserves_original_approval_contract(case):
    store, plan, step, run, *_ = case
    identifier = commitments.create(store, plan, run)
    produced = run / 'steps/prepare/outputs/prepared.json'
    produced.parent.mkdir(parents=True)
    produced.write_text('{"future":true}')
    assert commitments.create(store, plan, run) == identifier
    assert commitments.verify(store, plan, step, run) == identifier
    entry = store.rows[0]['record']['steps'][0]['inputs'][1]
    assert entry['deferred'] is True and 'sha256' not in entry
    # Its actual bytes still require custody.input_errors at the effect boundary.


def materialized_route(case):
    from ravel.controller.routes.select import find, spec_sha256
    store, plan, step, run, *_ = case
    spec = find('analysis')
    plan['route'] = {'id': spec['id'], 'spec_sha256': spec_sha256(spec)}
    step['parameters'] = {'route_adapter': spec['adapter'], 'task': {'approved': True}}
    return store, plan, step, run


@pytest.mark.parametrize('with_spec_hash', [True, False])
def test_installed_route_pins_input_bound_materializer(case, with_spec_hash):
    store, plan, step, run = materialized_route(case)
    if not with_spec_hash:
        plan['route'].pop('spec_sha256')
    identifier = commitments.create(store, plan, run)
    row = store.rows[0]['record']['steps'][0]
    assert row['mode'] == 'input-bound-materializer'
    assert row['materializer']['module'] == 'ravel.controller.routes.analysis'
    assert row['materializer']['adapter'] == 'analysis'
    assert len(row['materializer']['sha256']) == 64
    assert 'argv_sha256' not in row
    assert commitments.verify(store, plan, step, run) == identifier


@pytest.mark.parametrize('change', ['unknown-route', 'missing-route', 'spec-hash', 'adapter'])
def test_missing_argv_requires_approved_matching_installed_adapter(case, change):
    store, plan, step, run = materialized_route(case)
    if change == 'unknown-route':
        plan['route']['id'] = 'uninstalled-route'
    elif change == 'missing-route':
        plan.pop('route')
    elif change == 'spec-hash':
        plan['route']['spec_sha256'] = 'wrong'
    else:
        step['parameters']['route_adapter'] = 'another-family'
    with pytest.raises(ValueError):
        commitments.create(store, plan, run)


@pytest.mark.parametrize('change', ['module-bytes', 'module-path', 'declared-step'])
def test_materializer_descriptor_and_step_changes_refuse(case, monkeypatch, tmp_path, change):
    from ravel.controller.routes import analysis
    store, plan, step, run = materialized_route(case)
    module_file = tmp_path / 'adapter.py'
    module_file.write_text('# approved adapter bytes')
    monkeypatch.setattr(analysis, '__file__', str(module_file))
    commitments.create(store, plan, run)
    if change == 'module-bytes':
        module_file.write_text('# changed adapter bytes')
    elif change == 'module-path':
        another = tmp_path / 'another.py'
        another.write_bytes(module_file.read_bytes())
        monkeypatch.setattr(analysis, '__file__', str(another))
    else:
        step['parameters']['task']['approved'] = False
    with pytest.raises(ValueError):
        commitments.verify(store, plan, step, run)
