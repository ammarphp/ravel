"""Scoped operation plans retain the original goal and actual typed IO."""
from copy import deepcopy
from pathlib import Path

import pytest

from ravel.workflow import research_child_plan, science, request_reading, request_plan, route_prompt, task_completion
from ravel.validation import validate_request_plan as vp
from test_research_cycle import specification, write
from test_research_full_cycle_authority import intake
from test_intake_connected_v2 import literal_spec


def planned(tmp_path, mode):
    if mode == 'quantities':
        original, parent = intake(tmp_path)
        supplied = specification(tmp_path, 'supplied', grouped=True)
    else:
        prompt = 'Calculate 2+2.'
        original = route_prompt.route(prompt)
        original['task_requirements'] = task_completion.initial_requirements(prompt)
        original['task_requirements']['assignments'] = [{'id': 'original-task', 'purpose': 'Original exact arithmetic.',
            'coverage': [{'obligation_id': row['id'], 'criteria': deepcopy(row['criteria'])}
                         for row in original['task_requirements']['obligations']]}]
        reading = request_reading.document(prompt)
        rp = write(tmp_path/'parent/inputs/reading.json', reading)
        original['reading'] = {'path': 'inputs/reading.json', 'sha256': rp['sha256']}
        plan = write(tmp_path/'parent/inputs/request_plan.json', request_plan.draft(reading, original))
        original.update(agent_layer_epoch=2, request_plan={'path': 'inputs/request_plan.json', 'sha256': plan['sha256']})
        parent = write(tmp_path/'parent/inputs/task_contract.json', original)
        supplied = write(tmp_path/'literal.json', literal_spec(parent))
    rd = tmp_path/'child'
    science.plan(rd, supplied['path'])
    state = {'base_dir': str(tmp_path), 'contract': {'goal_binding': {'contract': parent, 'assignment_id': 'original-task'}}}
    e = {'acceptance_scope': 'supplied_math_diagnostic'}
    root = Path(parent['path']).parent.parent
    reading = science.read_json(root/original['reading']['path'])
    parent_plan = science.read_json(root/original['request_plan']['path'])
    return state, e, rd, original, parent_plan, reading


@pytest.mark.parametrize('mode', ['quantities', 'literal-calculation'])
def test_scoped_plan_is_valid_actual_operation_and_preserves_unresolved_parent(tmp_path, mode):
    state, e, rd, original, parent_plan, reading = planned(tmp_path, mode)
    original_copy = deepcopy(parent_plan)
    plan = research_child_plan.compile_plan(state, e, rd, original, parent_plan, reading, materialize=True)
    assert vp.check(reading, plan, obligations=original['task_requirements']['obligations']) == []
    assert [node['operation'] for node in plan['nodes']] == [mode]
    assert parent_plan == original_copy
    assert {row['obligation_id'] for row in plan['coverage']} == {
        row['id'] for row in original['task_requirements']['obligations']}
    assert plan['inputs'][0]['pin']['sha256'] == state['contract']['goal_binding']['contract']['sha256']
    assert plan['nodes'][0]['spec_template']['sha256'] == science.execution.file_hash(rd/science.SPEC)
    assert not any(node['kind'] == 'envelope' for node in plan['nodes'])
    assert not (rd/science.APPROVAL).exists()
    assert all(not Path(row['pin']['path']).is_absolute() for row in plan['inputs'])
    assert research_child_plan.compile_plan(state, e, rd, original, parent_plan, reading) == plan


def test_generic_registered_pointer_and_quantities_adapter_alias_agree(tmp_path, monkeypatch):
    args = planned(tmp_path, 'quantities')
    via_alias = research_child_plan.compile_plan(*args, materialize=True)
    registry = deepcopy(vp.registry())
    registry['quantities']['consumes'][0]['task_pointer'] = '/task/records'
    monkeypatch.setattr(vp, 'registry', lambda: registry)
    direct = research_child_plan.compile_plan(*args)
    assert direct['inputs'] == via_alias['inputs']
    assert direct['edges'] == via_alias['edges']


def test_unresolved_registered_input_refuses_instead_of_inventing_a_source(tmp_path, monkeypatch):
    args = planned(tmp_path, 'quantities')
    research_child_plan.compile_plan(*args, materialize=True)
    registry = deepcopy(vp.registry())
    registry['quantities']['consumes'][0]['task_pointer'] = '/task/not_supplied'
    monkeypatch.setattr(vp, 'registry', lambda: registry)
    with pytest.raises(ValueError, match='cannot bind registered input'):
        research_child_plan.compile_plan(*args)


@pytest.mark.parametrize('damage', ['missing', 'stale'])
def test_verification_never_recreates_or_repairs_a_scoped_source_copy(tmp_path, damage):
    args = planned(tmp_path, 'quantities')
    plan = research_child_plan.compile_plan(*args, materialize=True)
    path = args[2] / plan['inputs'][0]['pin']['path']
    if damage == 'missing':
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='source copy is missing or changed'):
        research_child_plan.compile_plan(*args)
    assert path.exists() == (damage != 'missing')
