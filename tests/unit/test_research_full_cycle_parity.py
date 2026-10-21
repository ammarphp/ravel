"""Retain executed legacy research parity rows for integration-owned record refresh."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ravel.workflow import research_protocol, research_orchestrator
import test_research_loop_graph as legacy


def test_parity_normalizes_nested_json_receipt_identity_without_losing_contents():
    body = {'artifact': {'path': '/run/ideas.json', 'sha256': 'a'*64, 'size': 1421},
            'ideas': [{'statement': 'A fictional relation', 'prediction': 7}],
            'transport': {'response_id': 'first', 'observed_model': 'gpt-5'}}
    other = deepcopy(body)
    other['artifact']['sha256'] = 'b'*64
    other['transport']['response_id'] = 'second'
    normalize = research_orchestrator._normalized
    assert normalize({'arguments_json': json.dumps(body)}) == normalize({'arguments_json': json.dumps(other)})
    assert normalize({'content': json.dumps(body)}) == normalize({'content': json.dumps(other)})
    for replacement in (7.1, 'changed'):
        changed = deepcopy(other)
        changed['ideas'][0]['prediction'] = replacement
        assert normalize(json.dumps(body)) != normalize(json.dumps(changed))
    other['transport']['observed_model'] = 'claude-x'
    assert normalize(json.dumps(body)) != normalize(json.dumps(other))


def test_parity_compares_stage_packet_content_not_its_subject_digest():
    """A stage packet's cycle_id is its subject digest; the presented subject is compared in full."""
    subject = {'stage': 'ideas', 'proposal': {'path': '/run/ideas.json', 'sha256': 'a'*64},
               'artifact': {'ideas': [{'id': 'Ia', 'prediction': 'shared'}]}}
    def packet(cycle_id, content):
        return {'review_packet': {'context': {'cycle_id': cycle_id, 'source_event_sha256': cycle_id},
                'artifacts': [{'id': 'public_case', 'content': json.dumps(content)}]}}
    other = deepcopy(subject)
    other['proposal']['sha256'] = 'b'*64
    normalize = research_orchestrator._normalized
    assert normalize(packet('c'*64, subject)) == normalize(packet('d'*64, other))
    other['artifact']['ideas'][0]['prediction'] = 'independent'
    assert normalize(packet('c'*64, subject)) != normalize(packet('d'*64, other))


@pytest.mark.parametrize('text', ['ordinary prose', '{invalid', '42', '"quoted"'])
def test_parity_keeps_non_document_text_exact(text):
    assert research_orchestrator._normalized(text) == text


def test_current_legacy_parity_rows_are_computed_from_both_engines(tmp_path, monkeypatch, record_property):
    # The same inert choice service as the original transport parity fixtures.
    monkeypatch.setattr(research_protocol, 'decision_errors', lambda *a, **k: [])
    rows = []
    keep = legacy.keep_parity_result

    def capture(*args, **kwargs):
        row = keep(*args, **kwargs)
        rows.append(row)
        if not row['equal']:
            differences = []
            def compare(left, right, path):
                if left == right or len(differences) >= 12:
                    return
                if isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys():
                    for key in left:
                        compare(left[key], right[key], path+'/'+key)
                elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
                    for index, (a, b) in enumerate(zip(left, right)):
                        compare(a, b, path+'/'+str(index))
                else:
                    differences.append({'path': path, 'legacy': left, 'graph': right})
            compare(args[2], args[3], '')
            # Resolve hashed request differences to the actual compared
            # normalized bodies, so a volatile field cannot hide a real drift.
            for old_graph, new_graph in zip(args[2]['graphs'], args[3]['graphs']):
                for node, old_node in old_graph['nodes'].items():
                    new_node = new_graph['nodes'][node]
                    if old_node['request_identity_sha256'] == new_node['request_identity_sha256']:
                        continue
                    def request_body(graph, old):
                        path = Path(graph['root'])
                        if old:
                            path = Path(str(path).replace(str(Path(args[4])/'run'), str(Path(args[4])/'legacy'), 1))
                        rows = [json.loads(p.read_text()) for p in (path/'requests').glob('*.json')]
                        row = next(row for row in rows if row['request']['node_id'] == node)
                        return research_orchestrator._normalized(row)
                    compare(request_body(old_graph, True), request_body(new_graph, False), '/request/'+node)
            raise AssertionError(json.dumps(differences, sort_keys=True))
        return row

    monkeypatch.setattr(legacy, 'keep_parity_result', capture)
    for number, fixture in enumerate([
        legacy.test_open_question_runs_equal_on_both_engines,
        legacy.test_stage_graph_matches_the_legacy_stage_runner_through_the_first_r2_stage,
        legacy.test_open_question_engines_agree_where_both_stop_on_the_baseline_failure,
    ]):
        base = tmp_path/str(number)
        base.mkdir()
        fixture(base)
    record_property('research_parity_results', json.dumps(rows, sort_keys=True))
    assert {row['id'] for row in rows} == {
        'synthetic-open-question', 'synthetic-protocol-stages', 'open-question-baseline-failure'}
    assert all(row['equal'] for row in rows)
    record = research_orchestrator.parity_record(rows)
    record_property('research_parity_source_identity', json.dumps({
        key: record[key] for key in ('bindings', 'fixture_sources')}, sort_keys=True))
