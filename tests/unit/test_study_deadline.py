"""A declared study deadline: validated in the contract, shown in status, warned at its margin."""
import json

import pytest

from ravel import cli
from ravel.validation.validate_task_contract import validate
from ravel.workflow import current_state, study_deadline
from ravel.workflow.state_io import atomic_json, read_json


def initiate(root):
    assert cli.main(['initiate', '--prompt', 'Survey searches for a synthetic heavy resonance.', '--out', str(root)]) == 0


def with_deadline(root, deadline):
    path = root / 'inputs/task_contract.json'
    contract = read_json(path)
    contract['deadline'] = deadline
    atomic_json(path, contract)
    return contract


def test_contract_accepts_absolute_and_budget_deadlines(tmp_path):
    initiate(tmp_path / 'run')
    contract = read_json(tmp_path / 'run/inputs/task_contract.json')
    for deadline in ({'utc': '2030-01-01T12:00:00Z', 'margin_s': 3600},
                     {'budget_s': 86400, 'start_utc': '2030-01-01T00:00:00Z', 'margin_s': 0}):
        assert validate({**contract, 'deadline': deadline}) == []


@pytest.mark.parametrize('deadline, message', [
    ({'utc': '2030-01-01T12:00:00Z'}, 'margin_s'),
    ({'utc': '2030-01-01T12:00:00', 'margin_s': 1}, 'UTC'),
    ({'utc': '2030-01-01T12:00:00Z', 'budget_s': 5, 'start_utc': '2030-01-01T00:00:00Z', 'margin_s': 1}, 'exactly one'),
    ({'budget_s': 60, 'margin_s': 1}, 'run start_utc'),
    ({'budget_s': 60, 'start_utc': '2030-01-01T00:00:00Z', 'margin_s': 61}, 'exceeds'),
    ({'utc': '2030-01-01T12:00:00Z', 'start_utc': '2030-01-01T00:00:00Z', 'margin_s': 1}, 'belongs to a budget'),
])
def test_malformed_deadlines_are_refused(tmp_path, deadline, message):
    initiate(tmp_path / 'run')
    contract = read_json(tmp_path / 'run/inputs/task_contract.json')
    errors = validate({**contract, 'deadline': deadline})
    assert errors and any(message in e for e in errors)


def test_schema_refuses_unknown_and_negative_fields(tmp_path):
    initiate(tmp_path / 'run')
    contract = read_json(tmp_path / 'run/inputs/task_contract.json')
    assert validate({**contract, 'deadline': {'utc': '2030-01-01T12:00:00Z', 'margin_s': -1}})
    assert validate({**contract, 'deadline': {'utc': '2030-01-01T12:00:00Z', 'margin_s': 1, 'grace': 5}})


def test_read_and_state_compute_time_left_and_margin(tmp_path, monkeypatch):
    root = tmp_path / 'run'
    initiate(root)
    assert study_deadline.read(root) is None and study_deadline.state(root) is None
    with_deadline(root, {'budget_s': 7200, 'start_utc': '2030-01-01T10:00:00Z', 'margin_s': 1800})
    assert study_deadline.read(root) == {'deadline_utc': '2030-01-01T12:00:00Z', 'margin_s': 1800.0,
                                         'source': 'contract.deadline.budget_s'}
    early = study_deadline.state(root, '2030-01-01T11:00:00Z')
    assert early['seconds_left'] == 3600 and early['in_margin'] is False and early['action'] is None
    assert 'warning' not in early
    late = study_deadline.state(root, '2030-01-01T12:10:00Z')
    assert late['in_margin'] and late['overdue'] and 'passed' in late['warning']
    # No reviewed result and no receipt-pinned output: the one action is to finish the review.
    assert late['action']['kind'] == 'finish-review'
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2030-01-01T10:00:00Z')
    with pytest.raises(ValueError, match='margin has not been reached'):
        study_deadline.require_margin(root)


def test_declare_stamps_the_run_start_for_a_budget(monkeypatch):
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2030-01-01T00:00:00Z')
    assert study_deadline.declare(budget_s=60, margin_s=10) == {'margin_s': 10, 'budget_s': 60,
                                                                'start_utc': '2030-01-01T00:00:00Z'}
    with pytest.raises(ValueError, match='exactly one'):
        study_deadline.declare(margin_s=10)


def test_status_packet_shows_time_left_and_the_margin_action(tmp_path, monkeypatch, capsys):
    root = tmp_path / 'run'
    initiate(root)
    assert current_state.build_packet(root)['study_deadline'] is None
    with_deadline(root, {'utc': '2030-01-01T12:00:00Z', 'margin_s': 3600})
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2030-01-01T09:00:00Z')
    packet = current_state.build_packet(root)
    assert packet['study_deadline']['seconds_left'] == 10800 and packet['study_deadline']['in_margin'] is False
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2030-01-01T11:15:00Z')
    capsys.readouterr()
    cli.main(['status', '--rundir', str(root)])
    view = json.loads(capsys.readouterr().out)['study_deadline']
    assert view['in_margin'] is True and view['seconds_left'] == 2700
    assert view['action']['kind'] == 'finish-review' and 'margin reached' in view['warning']
    text = json.dumps(view).lower()
    assert 'human' not in text and 'physicist' not in text and view['action']['kind'] != 'reviewed-fill'


def test_malformed_declared_deadline_is_reported_in_the_packet(tmp_path):
    root = tmp_path / 'run'
    initiate(root)
    view = study_deadline.packet_block(root, contract={'deadline': {'utc': 'tomorrow', 'margin_s': 1}})
    assert 'error' in view and view['in_margin'] is None and view['action'] is None
