"""Exercise identical historical filtering at real create and batch API seams.

Only retained synthetic records and the existing nonnative review fixture are used.
"""
import copy
import json
from pathlib import Path
import pytest
from ravel.workflow import physics_review as review, review_context as context
from test_physics_review import run, opened
from test_review_context_batch import inert_runtime_for_pure_reader_controls
from test_historical_context_projection import event, frozen, CURRENT, HISTORICAL


@pytest.mark.parametrize('kind', ['journal', 'event', 'receipt', 'nested_request', 'nested_runtime'])
def test_create_and_batch_preserve_identical_filter_basis(run, tmp_path, monkeypatch, kind):
    root, _ = run
    opened(run)
    identity = 'inputs/parent-capture.json'
    value = event(HISTORICAL)
    if kind == 'journal':
        identity = str(tmp_path / 'prior' / 'logs/physics_review/events/00000002.json')
        value = b'not decoded or read as scientific data'
    elif kind in ('receipt', 'nested_request', 'nested_runtime'):
        value = {'schema_version': 1, 'action': 'submit', 'review_event': value}
        if kind.startswith('nested_'):
            field = 'request' if kind == 'nested_request' else 'runtime_contract'
            value[field] = {'independent_nll': -2.25, 'amplitudes': [0, 1.5], 'failed_endpoint': True}
    row = frozen(root, identity, value)
    original = review._read
    session_visits = []
    def fixture_read(path, **kwargs):
        reg, events = original(path, **kwargs)
        events = copy.deepcopy(events)
        cycle = next(e for e in reversed(events) if e['event'] == 'cycle')
        cycle['snapshots'].append(row)
        session_visits.append(kwargs.get('_session'))
        return reg, events
    monkeypatch.setattr(review, '_read', fixture_read)
    packet = tmp_path / 'role-packet'
    manifest = context.create(root, 'critic', packet)
    ids = [entry['id'] for entry in manifest['artifacts']]
    result = context.read_artifacts(packet, ids,
        expected_manifest_sha256=manifest['sha256'], rundir=root, expected_role='critic')
    assert any(session is not None for session in session_visits)
    assert [x['content'] for x in result['artifacts']] == [
        context.read_artifact(packet, entry['id'], expected_manifest_sha256=manifest['sha256'])
        for entry in manifest['artifacts']]
    assert result['receipt']['total_operation_io_bytes'] is None
    assert result['receipt']['excluded_direct_proof_runtime_io'] == 'not_measured'
    matches = [entry for entry in manifest['omissions'] if entry['source_path'] == identity]
    if kind in ('journal', 'event', 'receipt'):
        assert len(matches) == 1
        assert matches[0]['source_sha256'] == row['sha256']
        assert matches[0]['source_size'] == row['size']
        assert not any(entry['source_path'] == identity for entry in result['artifacts'])
    else:
        assert not matches
        returned = next(entry for entry in result['artifacts'] if entry['source_path'] == identity)
        assert returned['content'] == json.dumps(value).encode()
    assert all(not result['receipt'][key] for key in ('acceptance', 'delivery', 'reuse', 'role_vote'))
