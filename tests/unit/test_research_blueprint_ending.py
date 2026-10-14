"""Ending pins must refuse drift, retaining failed emitted files and old pins."""
import hashlib
import json
from pathlib import Path
import pytest
from ravel.workflow import research_blueprint as blueprint, research_cycle as cycle, agent_host
from test_research_blueprint import case, graph_spec, inert_runtime


@pytest.mark.parametrize('target', ['scientific-input', 'materialization-commitment'])
def test_emitted_bytes_changed_after_commit_write_do_not_return_success(tmp_path, monkeypatch, target):
    root, req, choice, request, _ = case(tmp_path, monkeypatch, concrete_baseline=True)
    original = blueprint._write
    changed = []
    def late(path, raw):
        initial_pin = original(path, raw)
        if Path(path).name == 'materialization.json':
            destination = (root / 'materialized/paired/inputs/records.jsonl'
                           if target == 'scientific-input' else Path(path))
            before = destination.read_bytes()
            destination.write_bytes(before + b' ')
            changed.append((destination, hashlib.sha256(before).hexdigest()))
        return initial_pin
    monkeypatch.setattr(blueprint, '_write', late)
    graph = tmp_path / 'ending-output-graph'
    result = cycle.execute_graph(root, graph, graph_spec(root, req, choice, request), agent_host.AgentHost())
    assert not result['complete'] and len(changed) == 1
    destination, original_hash = changed[0]
    assert destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() != original_hash
    commitment = root / 'materialized/materialization.json'
    value = json.loads(commitment.read_bytes())
    if target == 'scientific-input':
        assert next(p['sha256'] for p in value['output_pins'] if p['path'] == str(destination)) == original_hash
    assert not value['planning_approval_execution_acceptance_authorized']
    assert not cycle._load(root)[1]['experiments']
