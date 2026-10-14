"""Transport-neutral worker census and unknown-accounting refusal controls."""
import hashlib
import json
from pathlib import Path

import pytest


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + '\n')
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size}


def worker(root, role, attempt=1, reported=True):
    folder = root / 'agent-work' / role / str(attempt)
    row = {'schema_version': 1, 'agent': 'synthetic-transport', 'session_id': f'{role}-{attempt}',
           'cli_version': '1.0', 'stream': f'{role}/{attempt}', 'sidechain': False, 'prompt_index': 1,
           'timestamp': '2026-10-11T00:00:00Z', 'prompt': 'Inspect the supplied synthetic quantity.',
           'models': ['synthetic-build'], 'model': 'synthetic-build',
           'usage': {k: (v if reported else None) for k, v in
                     dict(input_tokens=8, cached_input_tokens=0, cache_creation_input_tokens=0, output_tokens=3, total_tokens=11).items()},
           'usage_reported': reported, 'assistant_messages': 1, 'tool_calls': {}, 'source': None,
           'ravel': {'node_id': role, 'attempt': attempt, 'role_id': role, 'receipt_sha256': None}}
    transcript = put(folder / 'transcript.jsonl', row)
    receipt = {'schema_version': 1, 'kind': 'agent-worker-receipt', 'node_id': role, 'attempt': attempt,
               'role': {'id': role, 'version': '1.0'}, 'session_id': row['session_id'],
               'model': {'requested': 'synthetic-build', 'observed': 'synthetic-build'},
               'usage': {'input_tokens': 8 if reported else None, 'output_tokens': 3 if reported else None, 'reported': reported},
               'status': 'ok', 'transcript': transcript, 'started_utc': row['timestamp'], 'finished_utc': row['timestamp'],
               'graph': {'id': 'synthetic-graph', 'version': 2, 'thread_id': 'synthetic-thread', 'path': str(root)}}
    return put(folder / 'receipt.json', receipt), transcript


@pytest.mark.parametrize('role', ['production', 'reviewer', 'consult', 'rdj', 'research-coordinator'])
def test_each_worker_family_is_listed_and_ingested(tmp_path, role):
    from ravel.workflow import worker_audit as wa, agent_audit as aa
    worker(tmp_path, role)
    audit = wa.build(tmp_path)
    assert audit['complete'] and len(audit['sessions']) == 1
    session = audit['sessions'][0]
    assert session['role_id'] == role and session['model_build'] == 'synthetic-build'
    assert session['timestamp'] == '2026-10-11T00:00:00Z' and session['tokens']['total_tokens'] == 11
    assert session['graph']['version'] == 2 and session['graph']['thread_id'] == 'synthetic-thread'
    collected = aa.collect([session['transcript']['path']])
    assert collected['records'][0]['ravel']['role_id'] == role and collected['totals']['total_tokens'] == 11


def test_missing_transcript_and_unknown_tokens_remain_gaps(tmp_path):
    from ravel.workflow import worker_audit as wa
    _, transcript = worker(tmp_path, 'consult', reported=False)
    audit = wa.build(tmp_path)
    assert not audit['complete'] and audit['sessions'][0]['tokens']['total_tokens'] is None
    Path(transcript['path']).unlink()
    audit = wa.build(tmp_path)
    assert len(audit['sessions']) == 1 and any('transcript' in g['reason'] for g in audit['gaps'])


def test_changed_transcript_and_unreceipted_prompt_are_not_omitted(tmp_path):
    from ravel.workflow import worker_audit as wa
    receipt, transcript = worker(tmp_path, 'production')
    Path(transcript['path']).write_text('{}\n')
    assert not wa.build(tmp_path)['complete']
    Path(receipt['path']).unlink()
    assert any('receipt' in g['reason'] for g in wa.build(tmp_path)['gaps'])


def test_legacy_code_spawned_graph_call_is_counted_even_without_transcript(tmp_path):
    from ravel.workflow import worker_audit as wa
    put(tmp_path / 'coordinator/graph_spec.json', {'graph_id': 'control', 'nodes': [{'id': 'review', 'role': 'reviewer'}]})
    put(tmp_path / 'coordinator/graph_state.json', {'graph_id': 'control', 'graph_revision': 1,
        'calls': {'call1': {'kind': 'model', 'node_id': 'review', 'attempt_id': 'a1', 'status': 'failed'}}})
    put(tmp_path / 'coordinator/calls/call1.json', {'kind': 'model', 'node_id': 'review', 'attempt_id': 'a1',
                                                'status': 'failed'})
    audit = wa.build(tmp_path)
    assert len(audit['sessions']) == 1 and audit['sessions'][0]['status'] == 'failed'
    assert audit['sessions'][0]['role_id'] == 'reviewer' and not audit['complete']
