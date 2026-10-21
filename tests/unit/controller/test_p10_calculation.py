"""Inert charged-planner delivery and original calculation parent controls."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from ravel.physics import literal_calculation as literal
from ravel.workflow import intake_planner, science, graph_substrate as gs
from ravel.workflow.graphs import intake_plan


class Store:
    def __init__(self):
        self.rows = []
    def append(self, kind, record):
        self.rows.append((kind, json.loads(json.dumps(record, allow_nan=False))))
        return str(len(self.rows))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    store = Store()
    obligations = [{'id': 'quantity', 'units': 'pb', 'statistic': 'supplied quadratic form'},
                   {'id': 'whole_original_request', 'text': 'Retain every supplied component.'}]
    parent = write(tmp_path / 'inputs/parent.json', {'prompt': '2 pb + 3 pb',
                   'task_mode': 'calculation', 'obligations': obligations})
    handoff = {'task_kind': 'calculation', 'goal_binding': {'parent_sha256': parent['sha256']},
               'original_request': '2 pb + 3 pb', 'obligations': obligations}
    request = write(tmp_path / 'planning/request.json', {'schema_version': 1,
        'kind': 'intake-planning-request', 'parent_contract': parent, 'handoff': handoff,
        'parent_task_accepted': False, 'execution_authorized': False, 'physics_validated': False})
    state = {'mode': 'literal-calculation', 'status': 'planned', 'approved': False,
             'tamper': False, 'changed_goal': False, 'changed_obligations': False,
             'returned_authority': False, 'wrong_literal_parent': False}
    calls = []
    def materialize(request_pin, graph_root, output_dir, *, base_dir, presented_pins):
        calls.append(('materialize', deepcopy(request_pin), deepcopy(presented_pins)))
        assert request_pin == request and Path(base_dir) == tmp_path
        output = Path(output_dir)
        assert not output.exists()
        child = output / 'study'
        task = {'parent_contract': parent, 'expression': '2 pb + 3 pb', 'unit': 'pb'}
        if state['wrong_literal_parent']:
            task['parent_contract'] = {**parent, 'sha256': '0' * 64}
        spec = {'schema_version': 1 if state['mode'] == 'literal-calculation' else 2,
                'mode': state['mode'], 'task': task, 'max_seconds': 10,
                'goal_binding': deepcopy(handoff['goal_binding'])}
        if state['changed_goal']:
            spec['goal_binding'] = {'parent_sha256': '0' * 64}
        pin = write(output / 'science.json', spec)
        write(child / science.SPEC, spec)
        write(child / science.PLAN, {'mode': state['mode'], 'planned': True})
        if state['approved']:
            approval = child / science.APPROVAL
            approval.parent.mkdir(parents=True, exist_ok=True)
            approval.write_text('{}')
        value = {'schema_version': 1, 'kind': 'intake-planning-delivery', 'request': request,
            'parent_contract': parent, 'goal_binding': deepcopy(handoff['goal_binding']),
            'original_request': handoff['original_request'], 'original_obligations': deepcopy(obligations),
            'remaining_parent_obligations': deepcopy(obligations),
            'disposition': 'scientific_study', 'science_specification': pin, 'child_root': str(child),
            'execution_authorized': False, 'parent_task_accepted': False, 'physics_validated': False}
        if state['changed_obligations']:
            value['remaining_parent_obligations'] = []
        delivery = write(output / 'delivery.json', value)
        if state['tamper']:
            Path(delivery['path']).write_text('{}')
        return {'delivery': delivery, 'value': value, 'execution_authorized': state['returned_authority'],
                'parent_task_accepted': False}
    monkeypatch.setattr(intake_planner, 'materialize', materialize)
    monkeypatch.setattr(science, 'verify_plan', lambda child: {'planned': True})
    monkeypatch.setattr(science, 'packet', lambda child: {'execution': {'status': state['status']}})
    def validate_parent(task, base):
        calls.append(('validate_parent', deepcopy(task), Path(base)))
        assert task['parent_contract'] == parent
        assert Path(base) == tmp_path
        literal.validate(task)
        return {'parent_contract': parent, 'unit': 'pb', 'execution_authorized': False}
    monkeypatch.setattr(literal, 'validate_parent', validate_parent)
    def invoke():
        return intake_planner.controller_child(store, request, tmp_path / 'graph', tmp_path / 'output',
                                               base_dir=tmp_path, presented_pins=[request, parent])
    return store, state, calls, invoke, tmp_path, obligations


def test_R08_literal_child_rechecks_delivery_and_exact_original_parent(fixture):
    store, state, calls, invoke, root, obligations = fixture
    value = invoke()
    assert value['continuation'] == 'controller.step'
    assert value['execution_authorized'] is False and value['parent_task_accepted'] is False
    assert value['original_obligations'] == value['remaining_parent_obligations'] == obligations
    assert value['original_obligations'][0]['units'] == 'pb'
    assert value['original_obligations'][0]['statistic'] == 'supplied quadratic form'
    assert [c[0] for c in calls] == ['materialize', 'validate_parent']
    assert store.rows[-1][0] == 'controller-intake-child'
    assert store.rows[-1][1]['remaining_parent_obligations'] == obligations
    with pytest.raises(ValueError, match='fresh unprepared'):
        invoke()


@pytest.mark.parametrize('mutation', ['tamper', 'approved', 'changed_obligations',
                                    'returned_authority', 'wrong_literal_parent'])
def test_calculation_delivery_mutation_cannot_create_authority(fixture, mutation):
    store, state, calls, invoke, root, obligations = fixture
    state[mutation] = True
    with pytest.raises(ValueError):
        invoke()
    assert store.rows == []


@pytest.mark.parametrize('status', ['running', 'completed', 'prepared'])
def test_executed_or_nonplanned_child_is_refused(fixture, status):
    store, state, calls, invoke, root, obligations = fixture
    state['status'] = status
    with pytest.raises(ValueError, match='planned unapproved'):
        invoke()
    assert store.rows == []


def test_physical_child_retains_all_parent_obligations_and_judgment(fixture):
    store, state, calls, invoke, root, obligations = fixture
    state['mode'] = 'fictional-physical-operation'
    value = invoke()
    assert value['continuation'] == 'judgment'
    assert value['literal_parent'] is None
    assert value['remaining_parent_obligations'] == obligations
    assert value['execution_authorized'] is False
    assert [c[0] for c in calls] == ['materialize']


def test_physical_child_changed_original_goal_is_refused(fixture):
    store, state, calls, invoke, root, obligations = fixture
    state.update(mode='fictional-physical-operation', changed_goal=True)
    with pytest.raises(ValueError, match='original scientific goal'):
        invoke()
    assert store.rows == []


def test_literal_exact_units_remain_required(tmp_path):
    pin = {'path': str(tmp_path / 'parent.json'), 'sha256': 'a' * 64, 'size': 2}
    task = {'parent_contract': pin, 'expression': '2 pb + 3 pb', 'unit': 'pb'}
    assert literal.exact_value(task['expression'])['numerator'] == '5'
    assert literal.exact_value(task['expression'])['unit'] == 'pb'
    literal.validate(task)
    for actual in ({k: v for k, v in task.items() if k != 'unit'}, {**task, 'unit': 'fb'}):
        with pytest.raises(ValueError):
            literal.validate(actual)


def planner_spec():
    return {'schema_version': 1, 'graph_id': 'synthetic-intake',
            'budget': {'max_nodes': 2, 'max_calls': 2, 'max_output_tokens': 32,
                       'max_wall_seconds': 10, 'max_reworks': 0},
            'nodes': [{'id': 'choose', 'kind': 'model', 'role': 'designer', 'depends_on': [], 'inputs': [],
                       'packet': None, 'action': 'responses', 'parameters': {}, 'max_attempts': 1},
                      {'id': 'prepare', 'kind': 'tool', 'role': 'executor', 'depends_on': ['choose'],
                       'inputs': [], 'packet': None, 'action': 'intake-plan', 'parameters': {}, 'max_attempts': 1}]}


def test_trusted_build_context_runner_delivers_json_child_without_model(tmp_path, monkeypatch):
    spec = planner_spec()
    monkeypatch.setattr(intake_plan.agent_graph, '_load', lambda path: (spec, None))
    calls = []
    delivered = {'child_root': 'fictional-child', 'execution_authorized': False,
                 'remaining_parent_obligations': [{'id': 'quantity'}]}
    def runner(node, host):
        calls.append(node)
        return {'choice': 'fictional'} if node == 'choose' else deepcopy(delivered)
    ctx = gs.BuildContext(tmp_path, 'intake.plan', 1, {'graph_root': str(tmp_path / 'graph')},
                          extras={'node_runner': runner})
    builder = intake_plan.build(ctx)
    app = gs.finish(builder, 'intake.plan', checkpointer=None,
                    expected_structure=intake_plan.graph_registry.get('intake.plan')['structure_sha256'])
    found = app.invoke({'meta': {'graph_id': 'intake.plan', 'version': 1, 'instance': {},
                               'scope_root': str(tmp_path)}})
    assert calls == ['choose', 'prepare']
    assert found['completed']['prepare'] == delivered
    assert ctx.node_runner is None  # Build does not mutate a caller's context.


def test_explicit_legacy_runner_wins_and_noncallable_extra_refused(tmp_path, monkeypatch):
    spec = planner_spec()
    monkeypatch.setattr(intake_plan.agent_graph, '_load', lambda path: (spec, None))
    ctx = gs.BuildContext(tmp_path, 'intake.plan', 1, {'graph_root': str(tmp_path)},
                          node_runner=lambda node, host: None, extras={'node_runner': 'untrusted data'})
    assert intake_plan.build(ctx) is not None
    with pytest.raises(ValueError, match='must be callable'):
        intake_plan.build(replace(ctx, node_runner=None))
