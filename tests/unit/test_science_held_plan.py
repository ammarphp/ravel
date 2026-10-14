"""A study whose supplied inputs or native prerequisites are absent gets a held CHECK-IN 1."""
import json
import os
from types import SimpleNamespace

import pytest

from ravel.workflow import science
from ravel.workflow.state_io import atomic_json, read_json
from test_physics_review import policy


def quantities_spec(tmp_path, *, records='records.jsonl'):
    from test_scientific_quantities import contract
    atomic_json(tmp_path / 'contract.json', contract())
    spec = {'schema_version': 1, 'mode': 'quantities', 'source': 'synthetic weighted-record control',
            'assumptions': ['Synthetic records exercise planning only'], 'max_seconds': 30,
            'approval_mode': 'scripted_yes', 'task': {'contract': 'contract.json', 'records': records}}
    atomic_json(tmp_path / 'spec.json', spec)
    return tmp_path / 'run', tmp_path / 'spec.json'


def write_records(tmp_path, name='records.jsonl'):
    from test_scientific_quantities import event
    (tmp_path / name).write_text('\n'.join(json.dumps(e) for e in [event('a', [[.5]], 2)]) + '\n')


def test_regular_distinguishes_missing_symlink_and_directory(tmp_path):
    with pytest.raises(science.MissingInput, match='not found'):
        science.regular('absent.json', tmp_path)
    (tmp_path / 'real.json').write_text('{}')
    os.symlink(tmp_path / 'real.json', tmp_path / 'alias.json')
    with pytest.raises(ValueError, match='symlink') as refused:
        science.regular('alias.json', tmp_path)
    assert not isinstance(refused.value, science.MissingInput)
    (tmp_path / 'folder').mkdir()
    with pytest.raises(ValueError, match='regular file') as refused:
        science.regular('folder', tmp_path)
    assert not isinstance(refused.value, science.MissingInput)


def test_missing_supplied_input_writes_a_held_checkin1(tmp_path):
    rd, spec = quantities_spec(tmp_path)
    result = science.plan(rd, spec)
    assert result['status'] == 'held' and result['mode'] == 'quantities'
    held = read_json(rd / science.HELD)
    assert held['status'] == 'held' and held['execution_authorized'] is False
    unmet = held['unmet']
    assert [u['kind'] for u in unmet] == ['input']
    assert unmet[0]['reason'] == 'missing' and unmet[0]['path'].endswith('records.jsonl')
    flags = held['checkin1']['sections']['v']
    assert flags[0]['id'] == 'F1' and 'records.jsonl' in flags[0]['item']
    assert 'records.jsonl' in (rd / 'CHECKIN1.md').read_text()
    assert not (rd / science.PLAN).exists()
    assert not (rd / 'inputs/checkin1.json').exists()


def test_held_plan_lists_every_missing_path_named_in_the_task(tmp_path):
    rd, spec = quantities_spec(tmp_path)
    (tmp_path / 'contract.json').unlink()
    result = science.plan(rd, spec)
    paths = sorted(os.path.basename(u['path']) for u in result['unmet'])
    assert paths == ['contract.json', 'records.jsonl']


def test_supplying_the_items_plans_in_the_held_directory(tmp_path):
    rd, spec = quantities_spec(tmp_path)
    science.plan(rd, spec)
    write_records(tmp_path)
    proposal = science.plan(rd, spec)
    assert proposal['mode'] == 'quantities' and (rd / science.PLAN).is_file()
    assert not (rd / science.HELD).exists()
    assert (rd / 'inputs/held/science-held.json').is_file()
    assert science.packet(rd)['execution']['status'] == 'planned'


def test_a_planned_directory_is_never_reused(tmp_path):
    rd, spec = quantities_spec(tmp_path)
    write_records(tmp_path)
    science.plan(rd, spec)
    with pytest.raises(FileExistsError):
        science.plan(rd, spec)


def test_symlinked_input_is_refused_without_a_directory(tmp_path):
    rd, spec = quantities_spec(tmp_path, records='alias.jsonl')
    write_records(tmp_path)
    os.symlink(tmp_path / 'records.jsonl', tmp_path / 'alias.jsonl')
    with pytest.raises(ValueError, match='symlink'):
        science.plan(rd, spec)
    assert not rd.exists()


def test_invalid_specification_still_refuses(tmp_path):
    rd, spec = quantities_spec(tmp_path)
    document = read_json(spec); document['max_seconds'] = 0; atomic_json(spec, document)
    with pytest.raises(ValueError, match='max_seconds'):
        science.plan(rd, spec)
    assert not rd.exists()


def v2_spec(tmp_path, monkeypatch, implementation):
    monkeypatch.setattr(science, 'adapter', lambda spec: implementation)
    review = policy(); review.update(allowed_stages=['science'], allowed_changed_paths=[], max_redos=0)
    document = {'schema_version': 2, 'mode': 'likelihood-parity', 'source': 'Synthetic held-plan control',
                'assumptions': ['No computation'], 'max_seconds': 45, 'max_attempts': 1,
                'approval_mode': 'scripted_yes', 'task': {'input': str(tmp_path / 'events.hepmc')},
                'review_policy': {'schema_version': 1, 'policy': review,
                                  'correction_contract': {'task_fields': [], 'input_slots': []}}}
    atomic_json(tmp_path / 'spec.json', document)
    return tmp_path / 'run', tmp_path / 'spec.json'


def test_v2_missing_event_file_is_held_not_reported_as_a_symlink(tmp_path, monkeypatch):
    implementation = SimpleNamespace(validate=lambda task: None, inputs=lambda task, base: [task['input']])
    rd, spec = v2_spec(tmp_path, monkeypatch, implementation)
    result = science.plan(rd, spec)
    assert result['status'] == 'held'
    assert result['unmet'][0]['reason'] == 'missing'
    assert result['unmet'][0]['path'].endswith('events.hepmc')


def test_missing_native_prerequisite_is_held(tmp_path, monkeypatch):
    def inputs(task, base):
        raise science.MissingPrerequisite('diagram engine is not provisioned in this environment')
    implementation = SimpleNamespace(validate=lambda task: None, inputs=inputs)
    rd, spec = v2_spec(tmp_path, monkeypatch, implementation)
    (tmp_path / 'events.hepmc').write_text('event')
    result = science.plan(rd, spec)
    assert result['status'] == 'held'
    assert result['unmet'] == [{'kind': 'prerequisite', 'reason': 'missing',
                                'item': 'diagram engine is not provisioned in this environment'}]


def test_missing_python_package_is_a_held_prerequisite(tmp_path, monkeypatch):
    def inputs(task, base):
        raise ModuleNotFoundError("No module named 'absent_engine'", name='absent_engine')
    implementation = SimpleNamespace(validate=lambda task: None, inputs=inputs)
    rd, spec = v2_spec(tmp_path, monkeypatch, implementation)
    (tmp_path / 'events.hepmc').write_text('event')
    result = science.plan(rd, spec)
    assert result['unmet'][0]['kind'] == 'prerequisite' and 'absent_engine' in result['unmet'][0]['item']


def test_status_packet_of_a_held_study_names_the_unmet_items(tmp_path):
    from ravel.workflow import current_state
    rd, spec = quantities_spec(tmp_path)
    science.plan(rd, spec)
    packet = current_state.build_packet(rd)
    assert packet['execution']['status'] == 'held'
    assert 'records.jsonl' in json.dumps(packet['next_required'])


def test_cli_plan_reports_a_held_checkin(tmp_path, capsys):
    from ravel.cli import main
    rd, spec = quantities_spec(tmp_path)
    assert main(['plan', '--rundir', str(rd), '--spec', str(spec)]) == 0
    out = capsys.readouterr().out
    assert 'Held' in out and 'CHECKIN1.md' in out


def test_v2_held_study_plans_in_place_once_the_file_exists(tmp_path, monkeypatch):
    implementation = SimpleNamespace(validate=lambda task: None, inputs=lambda task, base: [task['input']])
    rd, spec = v2_spec(tmp_path, monkeypatch, implementation)
    assert science.plan(rd, spec)['status'] == 'held'
    (tmp_path / 'events.hepmc').write_text('event')
    proposal = science.plan(rd, spec)
    assert proposal['schema_version'] == 2 and (rd / science.PLAN).is_file()
    assert (rd / 'inputs/held/science-held.json').is_file()
    assert science.packet(rd)['execution']['status'] == 'planned'
