"""Placement pins: fingerprinted, shown at CHECK-IN 1, executed through the backend with payload custody."""
from __future__ import annotations

import json

import pytest

from ravel.cli import main
from ravel.workflow import execution, execution_backend as eb, placement, scoped, scoped_spec
from ravel.workflow.state_io import atomic_json, read_json


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    eb._INSTANCES.clear()


def counting_spec(**extra):
    return {'schema_version': 1, 'mode': 'likelihood', 'source': 'Synthetic one-bin counting control',
            'assumptions': ['One synthetic bin with a Poisson background constraint'],
            'max_seconds': 120, 'approval_mode': 'scripted_yes',
            'likelihood': {'counting': {'observed': 10, 'background': 9, 'background_uncertainty': 2, 'signal': 1},
                           'poi_cap': 64, 'normalization': {'kind': 'signal_events', 'luminosity_fb': 1}},
            **extra}


def native(cpus=1):
    return {'backend_plan': {'backend': 'native', 'resources': {'cpus': cpus, 'memory_mib': 512}}}


def planned(tmp_path, name, spec):
    rd = tmp_path / name
    assert main(['initiate', '--prompt', 'Compute a likelihood-only control for the supplied counting model.',
                 '--out', str(rd)]) == 0
    source = tmp_path / f'{name}.json'
    atomic_json(source, spec)
    scoped.plan(rd, source)
    from method_decision_fixture import admit_method
    admit_method(rd)
    return rd


def test_placement_changes_the_fingerprint_and_checkin_shows_it(tmp_path):
    plain = planned(tmp_path, 'plain', counting_spec())
    one = planned(tmp_path, 'one', counting_spec(execution=native(1)))
    two = planned(tmp_path, 'two', counting_spec(execution=native(2)))
    bindings = [read_json(rd / scoped.PLAN)['stage_binding'] for rd in (plain, one, two)]
    assert len({b['fingerprint'] for b in bindings}) == 3
    assert bindings[1]['command'][2:4] == ['ravel.workflow.execution_backend', 'worker']
    section = read_json(one / 'inputs/checkin1.json')['sections']['i-b']
    assert 'placement' not in read_json(plain / 'inputs/checkin1.json')['sections']['i-b']
    assert section['placement']['backend'] == 'native' and section['placement']['resources']['cpus'] == 1
    assert section['placement']['plan_sha256'] == read_json(one / placement.PLAN)['plan_sha256']
    assert 'Placement: native backend, 1 CPU(s)' in (one / 'CHECKIN1.md').read_text()
    assert scoped.verify_plan(one)['stages'][0]['command'] == placement.worker_command(one, 'likelihood')


def test_a_changed_pinned_plan_is_stale(tmp_path):
    rd = planned(tmp_path, 'run', counting_spec(execution=native(1)))
    plan = read_json(rd / placement.PLAN)
    plan['spec']['resources']['cpus'] = 4
    plan['plan_sha256'] = eb.digest({k: v for k, v in plan.items() if k != 'plan_sha256'})
    atomic_json(rd / placement.PLAN, plan)
    with pytest.raises(ValueError, match='differs from the declared placement'):
        scoped.verify_plan(rd)


@pytest.mark.parametrize('execution_field,message', [
    ({'backend_plan': {'backend': 'oci-local', 'resources': {'cpus': 1, 'memory_mib': 512}}}, 'payload custody'),
    ({'backend_plan': {'backend': 'native', 'resources': {'cpus': 1, 'memory_mib': 512, 'wall_seconds': 5}}}, 'wall clock'),
    ({'backend_plan': {'backend': 'native'}}, 'requires backend and resources'),
    ({'placement': {}}, 'exactly backend_plan'),
])
def test_unsupported_placements_are_refused(execution_field, message):
    errors = scoped_spec.validate(counting_spec(execution=execution_field))
    assert errors and message in errors[0]


@pytest.mark.parametrize('name', ['RAVEL_STATE_DIR', 'RAVEL_MACHINE_LEASE', 'HOME', 'TMPDIR', 'PYTHONUSERBASE',
                                  'PATH', 'PYTHONPATH', 'OMP_NUM_THREADS'])
def test_placement_env_cannot_set_lease_state_or_runtime_variables(name):
    field = native(1)
    field['backend_plan']['env'] = {name: '/tmp/elsewhere'}
    errors = scoped_spec.validate(counting_spec(execution=field))
    assert errors and name in errors[0]


def test_checkin_shows_the_placement_environment_trees_and_lease_wait(tmp_path):
    tree = tmp_path / 'tool-tree'
    tree.mkdir()
    (tree / 'tool.dat').write_text('synthetic\n')
    field = native(1)
    field['backend_plan'].update(env={'TOOL_MODE': 'fast', 'SEED_TABLE': 'default'},
                                 readonly_trees=[{'path': str(tree), 'env': 'TOOL_TREE'}])
    rd = planned(tmp_path, 'env', counting_spec(execution=field))
    section = read_json(rd / 'inputs/checkin1.json')['sections']['i-b']['placement']
    assert section['env'] == {'TOOL_MODE': 'fast', 'SEED_TABLE': 'default'}
    assert section['readonly_trees'][0]['path'] == str(tree) and section['lease_wait_seconds'] == 120
    text = (rd / 'CHECKIN1.md').read_text()
    for key in ('TOOL_MODE=fast', 'SEED_TABLE=default', str(tree), 'TOOL_TREE', 'waits up to 120 s'):
        assert key in text


def test_placed_scoped_run_executes_through_the_backend_with_proven_custody(tmp_path):
    rd = planned(tmp_path, 'run', counting_spec(execution=native(1)))
    assert scoped.approve(rd, 'Scripted assent to this synthetic placed control', scripted=True) == 0
    code = scoped.run(rd)
    log = (rd / 'logs/scoped-worker.log').read_text()
    record = execution.load_execution(rd)['stages']['likelihood']
    assert record['status'] == 'succeeded', log
    assert code in (0, 3)
    result = read_json(rd / 'outputs/result.json')
    assert result['limit_status']['observed'] == 'resolved'
    handles = eb.stage_handles(rd, 'likelihood')
    assert len(handles) == 1
    attempt = handles[0].parent
    receipt = read_json(attempt / eb.RECEIPT_NAME)
    assert [o['destination'] for o in receipt['outputs']] == [str(rd / 'outputs')]
    payload = read_json(attempt / 'job/payload.json')
    launcher = read_json(attempt / 'job/launcher.json')
    assert payload['pid'] != launcher['pid'] and payload['identity']
    assert receipt['outputs'][0]['sha256'] == eb.identity(rd / 'outputs')['sha256']


def test_delegated_defaults_written_after_approval_block_the_placed_launch(tmp_path):
    # Absent at approval is part of what was approved; adding the record afterwards is not.
    rd = planned(tmp_path, 'late', counting_spec(execution=native(1)))
    assert scoped.approve(rd, 'Scripted assent to this synthetic placed control', scripted=True) == 0
    atomic_json(rd / 'inputs/delegated_defaults.json', {'schema_version': 1, 'entries': []})
    # The approved-input byte commitment names the late record before the fingerprint check runs.
    with pytest.raises(ValueError, match=r'approved input changed: inputs/delegated_defaults\.json'):
        scoped.run(rd)
    assert not (rd / 'outputs/result.json').exists()
