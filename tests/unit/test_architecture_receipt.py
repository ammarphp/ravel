"""Fictional custody observations; no native or model transport is run."""
import json

import pytest

from ravel.workflow import architecture_receipt as ar
from ravel.workflow import rdj_custody, review_points
from rdj_fixtures import Run


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    for key in ('CLAUDECODE', 'CLAUDE_CODE_SESSION_ID', 'RAVEL_SESSION_ID', 'CLAUDE_PROJECT_DIR'):
        monkeypatch.delenv(key, raising=False)


def test_missing_evidence_is_unknown_not_zero_or_pass(tmp_path):
    receipt = ar.build_receipt(tmp_path)
    assert receipt['host']['mode'] == 'restricted'
    assert receipt['host']['whole_host_enforcement'] == 'unknown'
    assert receipt['host']['tool_inventory'] is None
    assert receipt['roles']['missing'] is None
    assert receipt['autonomy']['mode'] == 'unknown'
    assert receipt['costs']['total'] is None and receipt['costs']['model_calls'] is None
    assert not receipt['accepted'] and not receipt['architecture_complete']
    assert 'NOT GOVERNED' in receipt['notices']
    assert 'INDEPENDENT REVIEW INCOMPLETE' in receipt['notices']
    json.dumps(receipt, allow_nan=False)


def test_environment_cannot_assert_full_enforcement(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_PRE_EXECUTION_GUARDS', 'broker')
    monkeypatch.setenv('RAVEL_HOST', 'qualified-fictional-host')
    receipt = ar.build_receipt(tmp_path)
    assert receipt['host']['whole_host_enforcement'] == 'unknown'
    assert receipt['host']['reported_enforcement']['pre_execution_guards'] == 'none'


@pytest.mark.parametrize('action', ['direct_execution', 'shell', 'independent_review', 'launch', 'invented'])
def test_restricted_host_refuses_substitution(tmp_path, action):
    with pytest.raises(ValueError, match='RESTRICTED HOST'):
        ar.require_host_action(tmp_path, action)
    assert not list(tmp_path.iterdir())


def test_checkin_registry_context_and_diagnostic_read_only(tmp_path):
    section = ar.checkin_section({'rundir': tmp_path})
    assert 'NOT GOVERNED' in section['text']
    assert 'INDEPENDENT REVIEW INCOMPLETE' in ar.checkin_section({})['text']
    assert ar.require_host_action(tmp_path, 'inspect')['architecture_receipt']['accepted'] is False
    assert not list(tmp_path.iterdir())


def test_unbound_contract_cannot_remove_required_roles(tmp_path):
    run = Run(tmp_path / 'run', snapshot=False)
    roles = ar._role_observations(run.root)
    assert roles['status'] == 'unknown' and roles['missing'] is None


def test_required_counts_use_shared_credit_decision(tmp_path, monkeypatch):
    run = Run(tmp_path / 'run')
    points = [{'id': 'seat-a', 'roles': [{'role': 'critic', 'count': 2}], 'mode': 'voting'}]
    monkeypatch.setattr(review_points, 'derive', lambda facts: points)
    monkeypatch.setattr(review_points, '_receipt_records', lambda *args: [])
    monkeypatch.setattr(review_points, 'producer_sessions', lambda *args: {})
    def missing(observed, receipts, producers):
        assert observed == points and receipts == []
        return {'seat-a': [{'role': 'critic', 'count': 2}]}
    monkeypatch.setattr(review_points, '_missing', missing)
    monkeypatch.setattr(review_points, 'pending', lambda root: [{'id': 'seat-a', 'blocking': True}])
    roles = ar._role_observations(run.root)
    assert roles['roles'] == [{'point': 'seat-a', 'role': 'critic', 'required': 2, 'credited': 0, 'missing': 2, 'dispatched': 0}]
    assert roles['blocking_points'] == ['seat-a']


def test_real_registered_stage_without_launch_is_not_governed(tmp_path):
    run = Run(tmp_path / 'run')
    run.stage('summarize', 'outputs/value.json', {'value': 3})
    decision = ar.scientific_admissibility(run.root, [{'path': 'outputs/value.json', 'kind': 'number'}])
    assert not decision['governed']
    assert 'launch' in decision['stages'][0]['reason']


def test_changed_contract_is_reported_unknown(tmp_path):
    run = Run(tmp_path / 'run')
    run.put('inputs/task_contract.json', {'agent_layer_epoch': 1})
    roles = ar._role_observations(run.root)
    assert roles['status'] == 'unknown'
    assert 'differs' in roles['errors'][0]


def test_registered_advisory_dispatch_does_not_fill_independent_seat(tmp_path, monkeypatch):
    run = Run(tmp_path / 'run')
    pin = run.put('agent-work/a/1/receipt.json', {'fictional': True})
    rdj_custody.register_worker_receipt(run.root, pin['path'])
    record = {'_path': pin['path'], '_eligible': True, '_advisory': None, '_label': 'self_attested',
              'role': {'id': 'critic'}, 'review_point_id': 'seat-a', 'usage': {'cost_usd': None}}
    points = [{'id': 'seat-a', 'roles': [{'role': 'critic', 'count': 1}], 'mode': 'voting'}]
    monkeypatch.setattr(review_points, 'derive', lambda facts: points)
    monkeypatch.setattr(review_points, '_receipt_records', lambda *args: [record])
    monkeypatch.setattr(review_points, 'producer_sessions', lambda *args: {})
    def missing(points, records, producers):
        assert records == []
        return {'seat-a': [{'role': 'critic', 'count': 1}]}
    monkeypatch.setattr(review_points, '_missing', missing)
    monkeypatch.setattr(review_points, 'pending', lambda root: [{'id': 'seat-a', 'blocking': True}])
    roles = ar._role_observations(run.root)
    assert roles['roles'][0]['dispatched'] == 1
    assert roles['roles'][0]['credited'] == 0
    assert roles['dispatches'][0]['independent'] is False


def test_checkin_observation_does_not_rewrite_approval_inputs(tmp_path):
    checkin = tmp_path / 'inputs/checkin1.json'
    checkin.parent.mkdir()
    raw = b'{"kind":"checkin1","sections":{}}'
    checkin.write_bytes(raw)
    section = ar.checkin_section({'rundir': tmp_path})
    assert 'INDEPENDENT REVIEW INCOMPLETE' in section['text']
    assert checkin.read_bytes() == raw
