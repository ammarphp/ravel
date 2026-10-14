"""Read-only public event budget admission; no ROOT/client/build execution."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from ravel.physics import existing_events, simpleanalysis_events
from ravel.workflow import science
from test_simpleanalysis_events import public_input_fixture


@pytest.mark.parametrize('outer', [120, 121])
def test_exact_declared_container_ceiling_is_preserved_at_public_admission(tmp_path, monkeypatch, outer):
    task, base, _, job, *_ = public_input_fixture(tmp_path, monkeypatch)
    initial = deepcopy(job)
    initial_bytes = Path(task['container_plan']).read_bytes()
    assert simpleanalysis_events.execution_seconds(task, base) == 120
    assert existing_events.execution_seconds(task, base) == 120
    assert science.task_inputs({'mode':'analyze', 'task':task, 'max_seconds':outer}, base)
    assert job == initial and Path(task['container_plan']).read_bytes() == initial_bytes
    assert not (base/'unexecuted-event-output').exists()


@pytest.mark.parametrize('seconds', [True, 0, 29, 86401])
def test_invalid_inner_envelope_cannot_supply_an_admission_ceiling(tmp_path, monkeypatch, seconds):
    task, base, _, job, *_ = public_input_fixture(tmp_path, monkeypatch)
    job['resources']['max_seconds'] = seconds
    Path(task['container_plan']).write_text(json.dumps(job))
    with pytest.raises(ValueError, match='bounded container resources'):
        existing_events.execution_seconds(task, base)
    assert not (base/'unexecuted-event-output').exists()


def test_resource_hook_uses_complete_plan_validation_not_a_detached_resource_field(tmp_path, monkeypatch):
    task, base, prepared, job, *_ = public_input_fixture(tmp_path, monkeypatch)
    (prepared/'events.root').write_bytes(b'changed scientific input')
    job['input_files'] = simpleanalysis_events.container.tree_facts(prepared)
    Path(task['container_plan']).write_text(json.dumps(job))
    with pytest.raises(ValueError, match='bytes differ'):
        existing_events.execution_seconds(task, base)


def test_undeclared_inner_native_selection_keeps_outer_supervisor_minimum(tmp_path):
    task = {'backend':'native-selection', 'events':'events.json',
            'object_contract':'objects.json', 'selection':'selection.json'}
    assert existing_events.execution_seconds(task, tmp_path) == 1
