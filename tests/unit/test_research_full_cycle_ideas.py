"""Real isolated idea-stream dispatches for fictional full-cycle artifacts."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_graph, research_cycle as cycle, research_protocol as protocol
from test_research_full_cycle_transport import InertReviewHost


def _schema(value):
    """Closed public fixture schema; all authority stays in original consumers."""
    if type(value) is dict:
        properties = {key: _schema(item) for key, item in value.items()}
        return {'type': 'object', 'properties': properties, 'required': list(properties),
                'additionalProperties': False}
    if type(value) is list:
        return {'type': 'array', 'items': _schema(value[0]) if value else {'type': 'string'}}
    return {'type': {str: 'string', int: 'integer', float: 'number', bool: 'boolean',
                     type(None): 'null'}[type(value)]}


def actual_ideas(root, artifact, out):
    """Replace only stream receipt pins with original charged Graph evidence.

    No hypothesis adoption, scientific acceptance or dispatch registration is
    simulated. Both stream specifications exist before either call, and no
    source context presents the peer stream's proposed ideas.
    """
    root, out = Path(root), Path(out)
    artifact = deepcopy(artifact)
    state = cycle._load(root)[1]
    binding = state['contract'].get('goal_binding')
    limitation = next(row for row in protocol.methodology_status(root)['record']['stages']
                      if row['id'] == 'limitation_census')
    assert limitation['status'] == 'done'
    specifications, hosts, rows_by_stream = {}, {}, {}
    for stream, model in (('a', 'gpt-5'), ('b', 'claude-x')):
        rows = [row for row in artifact['ideas'] if row['stream'] == stream]
        assert rows, 'both independent idea streams are required'
        rows_by_stream[stream] = rows
        pins = [*([binding['contract']] if binding is not None else []), limitation['artifact'],
                *[row['novelty']['scout_receipt'] for row in rows]]
        pins = list({pin['path']: pin for pin in pins}.values())
        for pin in pins:
            cycle._check_pin(pin, state['base_dir'])
        inputs = [{'id': 'source-'+str(index), 'path': pin['path'], 'sha256': pin['sha256']}
                  for index, pin in enumerate(pins)]
        specification = {'schema_version': 1, 'graph_id': 'actual-idea-stream-'+stream,
            'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 2048,
                       'max_wall_seconds': 30, 'max_reworks': 0},
            'nodes': [{'id': 'ideas', 'kind': 'model', 'role': 'proposer', 'depends_on': [],
                'inputs': inputs, 'packet': None, 'action': 'chat_completions', 'max_attempts': 1,
                'parameters': {'model': model, 'reasoning_effort': 'high', 'max_output_tokens': 2048,
                    'instructions': 'Independently propose fictional bounded arithmetic ideas for stream '+stream+
                        '. Use the complete original task and limitation sources. No peer ideas are supplied.',
                    'output_schema': _schema({'ideas': rows})}}]}
        def respond(node, context, *, rows=deepcopy(rows), inputs=deepcopy(inputs)):
            assert {row['id'] for row in context['input_artifacts']} == {pin['id'] for pin in inputs}
            assert {row['sha256'] for row in context['input_artifacts']} == {pin['sha256'] for pin in inputs}
            return {'ideas': rows}
        specifications[stream] = specification
        hosts[stream] = InertReviewHost(respond, max_request_bytes=8_000_000)
        # Prepare both source-bound contexts before any model dispatch.
        agent_graph.create(out/stream/'graph', {**specification,
            **({'goal_binding': binding} if binding is not None else {})})
    receipts = {}
    for stream in ('a', 'b'):
        graph = out/stream/'graph'
        result = cycle.execute_graph(root, graph, specifications[stream], hosts[stream], prepared=True)
        assert result['complete'], result['nodes']
        origin = cycle._graph_result(graph, 'ideas')
        assert origin['value']['value'] == {'ideas': rows_by_stream[stream]}
        receipts[stream] = protocol.idea_dispatch_receipt(root, stream, rows_by_stream[stream],
            origin, out/('dispatch-'+stream+'.json'))
    artifact['dispatch_receipts'] = receipts
    return artifact


def _idea_case(tmp_path):
    from test_research_full_cycle_authority import campaign
    from test_research_full_cycle import complete_stage, stage_settings
    from test_research_default_protocol import synthetic_artifacts
    from test_research_cycle import write
    root = campaign(tmp_path)
    artifacts = synthetic_artifacts(root)
    complete_stage(root, 'limitation_census', write(root/'census.json', artifacts['limitation_census']),
                   'legacy', stage_settings())
    result = actual_ideas(root, artifacts['ideas'], root/'actual-ideas')
    return root, artifacts, result


def test_ideas_artifact_uses_actual_source_isolated_charged_streams(tmp_path):
    root, artifacts, result = _idea_case(tmp_path)
    assert result['ideas'] == artifacts['ideas']['ideas']
    assert result['dispatch_receipts'] != artifacts['ideas']['dispatch_receipts']
    assert set(result['dispatch_receipts']) == {'a', 'b'}
    assert protocol.seed_to_test(result, base_dir=root)
    current = cycle._load(root)[1]
    receipts = protocol.verify_idea_dispatches(current, result, base_dir=root)
    assert len({receipt['request_id'] for receipt in receipts}) == 2
    assert all(receipt['execution_observation'] == 'remote_transport_observed' for receipt in receipts)
    for stream, receipt in zip(('a', 'b'), receipts):
        pin = result['dispatch_receipts'][stream]
        assert pin == cycle._pin(pin['path'])
        document = cycle._read(pin, root)
        assert document['ideas_sha256'] == protocol.ce.digest([
            row for row in result['ideas'] if row['stream'] == stream])
        assert document['worker_receipt'] == receipt
        assert document['goal_binding'] == current['contract']['goal_binding']
    assert current['hypotheses'] == []
    charged = {row['root'] for row in current['graphs']}
    assert {str(root/'actual-ideas'/stream/'graph') for stream in ('a', 'b')} <= charged


@pytest.mark.parametrize('damage', ['missing', 'forged', 'stale', 'cross_campaign'])
def test_ideas_authority_and_stage_preparation_refuse_invalid_stream_custody(tmp_path, damage):
    from test_research_full_cycle_authority import authorize, campaign
    from test_research_full_cycle import complete_stage, stage_settings
    from test_research_default_protocol import synthetic_artifacts
    from test_research_cycle import write
    root, _, artifact = _idea_case(tmp_path)
    if damage == 'missing':
        del artifact['dispatch_receipts']['a']
    elif damage == 'forged':
        document = cycle._read(artifact['dispatch_receipts']['a'], root)
        document['origin']['root'] = str(root/'unregistered-idea-graph')
        artifact['dispatch_receipts']['a'] = write(root/'forged-stream.json', document)
    elif damage == 'stale':
        path = Path(artifact['dispatch_receipts']['a']['path'])
        path.write_bytes(path.read_bytes() + b'\n')
    else:
        root = campaign(tmp_path/'foreign')
        census = synthetic_artifacts(root)['limitation_census']
        complete_stage(root, 'limitation_census', write(root/'census.json', census), 'legacy', stage_settings())
    state = cycle._load(root)[1]
    with pytest.raises((ValueError, OSError)):
        protocol.verify_idea_dispatches(state, artifact, base_dir=root)
    proposed = write(root/'invalid-ideas.json', artifact)
    authorize(root, protocol.stage_action('ideas', proposed))
    before = cycle._load(root)[1]
    roles = next(row['roles'] for row in protocol.methodology_status(root)['record']['stages']
                 if row['id'] == 'ideas')
    with pytest.raises((ValueError, OSError)):
        protocol.prepare_stage(root, 'ideas', proposed, root/'refused-ideas', model='gpt-5',
            role_models={role: stage_settings()['roles'][role] for role in roles})
    assert cycle._load(root)[1] == before
    assert not (root/'refused-ideas').exists()
