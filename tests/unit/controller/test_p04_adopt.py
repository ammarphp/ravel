"""Custody of what a step consumes and adopts (M09): verified predecessors, declared outputs, decision rights."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ravel.controller.step import cards, custody
from ravel.controller.step.services import StepHold, digest
from ravel.workflow import role_registry, work_dispatch

from test_p04_support import FakeStore, accepted_artifact, make_step, records, sha


@pytest.fixture
def env(tmp_path):
    run_dir = tmp_path / 'run'
    (run_dir / 'inputs').mkdir(parents=True)
    return FakeStore(tmp_path / 'store', run_dir=run_dir), run_dir


def test_T07_C19_an_input_is_consumed_only_from_an_accepted_record_of_a_real_dependency(env):
    store, run_dir = env
    pin = accepted_artifact(store, run_dir, 's0', 'outputs/a.json', {'a': 1})
    step = make_step('s1', inputs=[pin], depends_on=['s0'])
    errors, found, _ = custody.input_errors(store, step, run_dir)
    assert errors == [] and [r['artifact'] for r in found] == ['s0:outputs/a.json']
    sibling = make_step('s1', inputs=[pin], depends_on=[])   # a future sibling's output, no dependency
    errors, _, _ = custody.input_errors(store, sibling, run_dir)
    assert errors == [{'code': 'input_without_dependency', 'artifact': 's0:outputs/a.json', 'producer': 's0'}]


def test_T06_an_unreceipted_file_copied_into_a_step_directory_is_never_an_input(env, monkeypatch):
    store, run_dir = env
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2001-01-01T00:00:00Z')   # an environment clock changes nothing
    target = run_dir / 'steps/s0/outputs/forged.json'
    target.parent.mkdir(parents=True)
    target.write_text('{"forged": true}')
    step = make_step('s1', inputs=[{'artifact': 's0:outputs/forged.json', 'sha256': sha(target.read_bytes())}],
                     depends_on=['s0'])
    errors, found, _ = custody.input_errors(store, step, run_dir)
    assert errors == [{'code': 'predecessor_unreceipted', 'artifact': 's0:outputs/forged.json'}] and found == []
    raw = make_step('s1', inputs=[{'artifact': 'steps/s0/outputs/forged.json', 'sha256': None}], depends_on=['s0'])
    assert custody.input_errors(store, raw, run_dir)[0][0]['code'] == 'predecessor_unreceipted'


def test_T07_an_unreceipted_predecessor_is_not_laundered_through_a_later_step(env):
    store, run_dir = env
    first = accepted_artifact(store, run_dir, 's0', 'outputs/a.json', {'a': 1})
    rows = records(store, 'custody')
    laundered = dict(rows[-1], artifact='s1:outputs/b.json', step_id='s1', path='outputs/b.json',
                     destination='steps/s1/outputs/b.json', inputs=['s9:outputs/never-adopted.json'])
    (run_dir / 'steps/s1/outputs').mkdir(parents=True)
    (run_dir / 'steps/s1/outputs/b.json').write_text(json.dumps({'a': 1}, sort_keys=True))
    store.append('custody', laundered)
    store.append('step-outcome', {'step_id': 's1', 'attempt': 1, 'status': 'completed'})
    step = make_step('s2', inputs=[{'artifact': 's1:outputs/b.json', 'sha256': first['sha256']}], depends_on=['s1'])
    errors, _, _ = custody.input_errors(store, step, run_dir)
    assert errors == [{'code': 'predecessor_unreceipted', 'artifact': 's9:outputs/never-adopted.json'}]


def test_adopted_bytes_that_changed_after_custody_are_refused(env):
    store, run_dir = env
    pin = accepted_artifact(store, run_dir, 's0', 'outputs/a.json', {'a': 1})
    (run_dir / 'steps/s0/outputs/a.json').write_text('{"a": 2}')
    errors, _, _ = custody.input_errors(store, make_step('s1', inputs=[pin], depends_on=['s0']), run_dir)
    assert errors == [{'code': 'predecessor_bytes_changed', 'artifact': 's0:outputs/a.json'}]


def test_a_staged_artifact_is_consumed_only_after_its_validators_accept_it(env):
    store, run_dir = env
    pin = accepted_artifact(store, run_dir, 's0', 'outputs/a.json', {'a': 1})
    staged = dict(records(store, 'custody')[-1], status='staged')
    store.append('custody', staged)
    errors, _, _ = custody.input_errors(store, make_step('s1', inputs=[pin], depends_on=['s0']), run_dir)
    assert errors == [{'code': 'predecessor_not_accepted', 'artifact': 's0:outputs/a.json', 'status': 'staged'}]
    custody.accept(store, [staged], 'rejected')
    errors, _, _ = custody.input_errors(store, make_step('s1', inputs=[pin], depends_on=['s0']), run_dir)
    assert errors[0]['status'] == 'rejected'


def test_a_run_input_is_pinned_at_dispatch_and_a_changed_one_is_refused(env):
    store, run_dir = env
    (run_dir / 'inputs/supplied.json').write_text('{"x": 1}')
    step = make_step('s1', inputs=[{'artifact': 'inputs/supplied.json', 'sha256': None}])
    errors, found, run_inputs = custody.input_errors(store, step, run_dir)
    assert errors == [] and run_inputs == [{'artifact': 'inputs/supplied.json', 'path': 'inputs/supplied.json',
                                            'sha256': sha(b'{"x": 1}')}]
    pinned = make_step('s1', inputs=[{'artifact': 'inputs/supplied.json', 'sha256': '0' * 64}])
    assert custody.input_errors(store, pinned, run_dir)[0] == [{'code': 'run_input_changed',
                                                                 'artifact': 'inputs/supplied.json'}]


def test_SW39_a_dependency_counts_only_when_its_completion_is_in_the_store(env):
    store, run_dir = env
    step = make_step('s2', depends_on=['s0', 's1'])
    store.append('step-outcome', {'step_id': 's0', 'attempt': 1, 'status': 'completed'})
    store.append('step-outcome', {'step_id': 's1', 'attempt': 1, 'status': 'failed'})
    assert custody.parent_errors(store, step) == [{'code': 'parent_incomplete', 'parent': 's1', 'status': 'failed'}]
    store.append('step-outcome', {'step_id': 's1', 'attempt': 2, 'status': 'completed'})
    assert custody.parent_errors(store, step) == []


def _worker(env, tmp_path, *, credited=True, quantity=None, role='baseline-producer'):
    store, run_dir = env
    workspace = tmp_path / 'ws'
    (workspace / 'outputs').mkdir(parents=True)
    (workspace / 'outputs/result.json').write_text('{"v": 1}')
    (workspace / 'final.json').write_text('{"kind": "producer-result"}')
    step = make_step('s1', role=role, parameters={'quantities': {'outputs/result.json': quantity}} if quantity else None)
    card = role_registry.load(role)
    outputs = cards.declared_outputs(card, step)
    receipt = {'node_id': 'ctl.s1', 'attempt': 1, 'session_id': 'sess-a', 'role': {'id': role},
               'credited_outputs': [{'path': 'outputs/result.json', 'kind': 'result',
                                     'sha256': sha(b'{"v": 1}')}] if credited else []}
    spec = {'sealed': True}
    return dict(store=store, run_dir=run_dir, step=step, attempt=1, card=card, receipt=receipt, workspace=workspace,
                sealed_spec_sha256=digest(spec), recorded_spec=spec, outputs=outputs, inputs_custody=[],
                final_path=workspace / 'final.json', sidecar=True)


def test_adoption_copies_credited_outputs_by_digest_and_stages_their_custody(env, tmp_path):
    adopted = custody.worker_adoption(**_worker(env, tmp_path))
    assert [r['artifact'] for r in adopted] == ['s1:outputs/result.json', 's1:final-record.json']
    assert all(r['status'] == 'staged' and r['owner_role'] == 'baseline-producer' for r in adopted)
    assert (env[1] / 'steps/s1/outputs/result.json').read_text() == '{"v": 1}'


def _launch(env, *, plan_path='outputs/result.json', source_path='result.json'):
    store, run_dir = env
    root = run_dir / 'steps/s1/attempts/1/outputs'
    source = root / source_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'{"v": 1}')
    step = make_step('s1', outputs=((plan_path, 'result'),))
    card = role_registry.load('baseline-producer')
    return dict(store=store, run_dir=run_dir, step=step, attempt=1, card=card,
                launch={'output_root': str(root), 'inventory': [
                    {'path': source_path, 'sha256': sha(source.read_bytes())}], 'exit_status': 0},
                outputs=cards.declared_outputs(card, step), inputs_custody=[])


def test_native_launch_adopts_relative_to_output_root_and_retains_plan_identity(env):
    values = _launch(env)
    adopted = custody.launch_adoption(**values)
    assert len(adopted) == 1
    assert adopted[0]['artifact'] == 's1:outputs/result.json'
    assert adopted[0]['path'] == 'outputs/result.json'
    assert adopted[0]['destination'] == 'steps/s1/outputs/result.json'
    assert adopted[0]['status'] == 'staged'
    assert (env[1] / adopted[0]['destination']).read_bytes() == b'{"v": 1}'


def test_native_launch_does_not_accept_an_extra_outputs_directory(env):
    values = _launch(env, source_path='outputs/result.json')
    with pytest.raises(StepHold) as refused:
        custody.launch_adoption(**values)
    assert refused.value.reason == 'declared_output_missing'
    assert refused.value.evidence == {'missing': ['outputs/result.json']}
    assert records(env[0], 'custody') == []
    assert not (env[1] / 'steps/s1/outputs/result.json').exists()


def test_native_launch_strips_exactly_one_outputs_prefix(env):
    values = _launch(env, plan_path='outputs/outputs/result.json', source_path='outputs/result.json')
    adopted = custody.launch_adoption(**values)
    assert adopted[0]['artifact'] == 's1:outputs/outputs/result.json'
    assert (env[1] / adopted[0]['destination']).read_bytes() == b'{"v": 1}'


def test_launch_inventory_bytes_are_rechecked_before_adoption(env):
    values = _launch(env)
    (Path(values['launch']['output_root']) / 'result.json').write_bytes(b'changed')
    with pytest.raises(StepHold) as refused:
        custody.launch_adoption(**values)
    assert refused.value.reason == 'adoption_bytes_changed'
    assert records(env[0], 'custody') == []


@pytest.mark.parametrize('defect', ['escape', 'absolute', 'link', 'ancestor_link'])
def test_launch_source_cannot_escape_or_traverse_a_symlink(env, tmp_path, defect):
    values = _launch(env)
    root = Path(values['launch']['output_root'])
    source = root / 'result.json'
    external = tmp_path / 'external'
    external.mkdir()
    (external / 'result.json').write_bytes(source.read_bytes())
    if defect in ('escape', 'absolute'):
        source_path = '../outside.json' if defect == 'escape' else str(external / 'result.json')
        if defect == 'escape':
            (root / source_path).write_bytes(source.read_bytes())
        values['outputs'][0]['plan_path'] = 'outputs/' + source_path
        values['launch']['inventory'][0]['path'] = source_path
    elif defect == 'link':
        source.unlink()
        source.symlink_to(external / 'result.json')
    else:
        (root / 'real').mkdir()
        (root / 'real/result.json').write_bytes(source.read_bytes())
        (root / 'linked').symlink_to(root / 'real', target_is_directory=True)
        values['outputs'][0]['plan_path'] = 'outputs/linked/result.json'
        values['launch']['inventory'][0]['path'] = 'linked/result.json'
    with pytest.raises(StepHold) as refused:
        custody.launch_adoption(**values)
    assert refused.value.reason == 'adoption_bytes_changed'
    assert records(env[0], 'custody') == []


def test_subgraph_explicit_layout_adopts_full_plan_path_under_child_root(env):
    values = _launch(env, source_path='outputs/result.json')
    adopted = custody.launch_adoption(**values, output_prefix='')
    assert adopted[0]['artifact'] == 's1:outputs/result.json'
    assert (env[1] / adopted[0]['destination']).read_bytes() == b'{"v": 1}'


def test_CF05_a_required_declared_output_that_was_not_credited_refuses_adoption(env, tmp_path):
    with pytest.raises(StepHold) as refused:
        custody.worker_adoption(**_worker(env, tmp_path, credited=False))
    assert refused.value.reason == 'declared_output_missing' and refused.value.evidence == {
        'missing': ['outputs/result.json']}
    assert not (env[1] / 'steps').exists() and records(env[0], 'custody') == []


def test_G08_adoption_refuses_a_dispatcher_spec_that_differs_from_the_sealed_one(env, tmp_path):
    values = _worker(env, tmp_path)
    values['recorded_spec'] = {'sealed': False}
    with pytest.raises(StepHold) as refused:
        custody.worker_adoption(**values)
    assert refused.value.reason == 'work_order_fidelity'


def test_CF07_a_non_owner_setting_an_owned_quantity_is_refused(env, tmp_path):
    owned = role_registry.load('baseline-producer')['ownership']['owns'][0]
    custody.worker_adoption(**_worker(env, tmp_path, quantity=owned))
    other = next(c for c in role_registry.all_cards() if c['ownership']['owns'] and owned not in c['ownership']['owns'])
    store, run_dir = env
    step = make_step('s5', role=other['id'], parameters={'quantities': {'outputs/result.json': owned}})
    assert cards.ownership_errors(other, step)[0]['code'] == 'ownership_not_owner'
    with pytest.raises(StepHold) as refused:
        custody.worker_adoption(**{**_worker((store, run_dir), tmp_path / 'other', role=other['id']), 'step': step})
    assert refused.value.reason == 'ownership_not_owner'


def test_CF07_a_consumer_must_declare_the_quantity_it_takes_from_another_role(env):
    producer = role_registry.load('baseline-producer')
    quantity = producer['ownership']['owns'][0]
    consumer = role_registry.load('assumption-auditor')
    record = {'artifact': 's0:outputs/a.json', 'quantity': quantity, 'owner_role': producer['id']}
    errors = cards.ownership_errors(consumer, make_step('s1', role=consumer['id']), [record])
    assert errors == [] if quantity in consumer['ownership']['inputs'] + consumer['ownership']['judges'] else (
        errors[0]['code'] == 'ownership_input_undeclared')


def test_I10_a_host_waiver_in_the_run_tree_grants_nothing(env, tmp_path):
    store, run_dir = env
    waiver = run_dir / 'production/waivers/s1.json'
    waiver.parent.mkdir(parents=True)
    waiver.write_text(json.dumps({'kind': 'host-waiver', 'node_id': 's1', 'executor': 'host'}))
    with pytest.raises(StepHold) as refused:
        custody.worker_adoption(**_worker(env, tmp_path, credited=False))
    assert refused.value.reason == 'declared_output_missing'


def test_adoption_never_replaces_other_bytes_or_writes_through_a_link(env, tmp_path):
    store, run_dir = env
    occupied = run_dir / 'steps/s1/outputs/result.json'
    occupied.parent.mkdir(parents=True)
    occupied.write_text('{"other": true}')
    with pytest.raises(StepHold) as refused:
        custody.worker_adoption(**_worker(env, tmp_path))
    assert refused.value.reason == 'adoption_destination_occupied'
    occupied.unlink()
    occupied.parent.rmdir()
    (tmp_path / 'elsewhere').mkdir()
    occupied.parent.symlink_to(tmp_path / 'elsewhere', target_is_directory=True)
    with pytest.raises(StepHold) as linked:
        custody.worker_adoption(**_worker(env, tmp_path / 'again'))
    assert linked.value.reason == 'adoption_destination_invalid'


def test_legacy_adoption_is_refused_for_a_controller_owned_run(tmp_path, monkeypatch):
    from ravel.workflow import agent_worker
    monkeypatch.setattr(agent_worker, 'controller_run', lambda rundir: 'run-p04-fixture')
    with pytest.raises(ValueError, match='governed step'):
        work_dispatch.adopt(tmp_path, 'N1', 1)


def test_an_unreadable_ownership_marker_fails_closed_for_every_legacy_path(tmp_path, monkeypatch):
    import sys
    import types
    from ravel.workflow import agent_worker, completion_budget

    class ControllerOwnershipUnknown(ValueError):
        pass
    store = types.ModuleType('ravel.controller.store')
    store.controller_owned = lambda run_dir: None
    monkeypatch.setitem(sys.modules, 'ravel.controller.store', store)
    limits = {'max_seconds': 10, 'max_events': 10, 'max_children': 1}
    assert agent_worker.controller_run(tmp_path) is None   # a legacy run stays legacy
    completion_budget.reserve(tmp_path / 'legacy', 'child', {'max_seconds': 1, 'max_events': 1}, limits)

    def damaged(run_dir):
        raise ControllerOwnershipUnknown('the controller-run marker cannot be read')
    store.controller_owned = damaged
    assert agent_worker.controller_run(tmp_path) == agent_worker.OWNERSHIP_UNKNOWN
    with pytest.raises(ValueError, match='governed step'):
        work_dispatch.adopt(tmp_path, 'N1', 1)
    with pytest.raises(ValueError, match='run store'):
        completion_budget.reserve(tmp_path / 'damaged', 'child', {'max_seconds': 1, 'max_events': 1}, limits)
