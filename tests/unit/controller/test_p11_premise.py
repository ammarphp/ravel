"""Coordinator premise retries reconstruct their original authenticated states."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from ravel.workflow import research_cycle as cycle, research_history, state_io

UNIT = str(Path(__file__).resolve().parents[1])
if UNIT not in sys.path:
    sys.path.insert(0, UNIT)
from test_research_cycle import contract, propose, write  # noqa: E402
from test_research_full_cycle_transport import InertReviewHost  # noqa: E402


@pytest.fixture
def revised_campaign(tmp_path):
    definition = contract(tmp_path)
    definition['budget'].update(output_tokens=1024)
    root = tmp_path / 'campaign'
    cycle.create(root, definition, base_dir=tmp_path, evaluation_harness=True)
    source = write(tmp_path / 'premise.txt', 'Supplied prospective grouping assumption; no measurement.\n')
    arguments = {'identity': 'pairing', 'statement': 'Use the explicitly paired supplied source population.',
                 'basis': [source], 'reason': 'Retain prior evidence while revising the prospective assumption.'}
    public = {'kind': 'research-action', 'action': 'revise-premise',
              'reason': 'Source-backed coordinator control.', 'arguments_json': json.dumps(arguments)}
    fields = {key: {'type': 'string'} for key in public}
    node = {'id': 'decision', 'kind': 'model', 'role': 'designer', 'depends_on': [],
            'inputs': [{'id': 'source', 'path': source['path'], 'sha256': source['sha256']}],
            'packet': None, 'action': 'model', 'max_attempts': 1,
            'parameters': {'model': 'inert-premise-control', 'reasoning_effort': 'high',
                           'max_output_tokens': 512, 'instructions': 'Return the supplied source-backed revision.',
                           'output_schema': {'type': 'object', 'properties': fields,
                                             'required': list(fields), 'additionalProperties': False}}}
    specification = {'schema_version': 1, 'graph_id': 'coordinator-premise-control', 'nodes': [node],
                     'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 512,
                                'max_wall_seconds': 60, 'max_reworks': 0}}
    host = InertReviewHost(lambda node, context: deepcopy(public))
    graph = root / 'coordinator-decision'
    assert cycle.execute_graph(root, graph, specification, host)['complete']
    origin = cycle._graph_result(graph, 'decision')
    assert origin['value']['transport']['execution_mode'] == 'provider_http'
    assert origin['value']['value'] == public
    before = cycle._load(root)[1]
    revised = cycle.revise_premise(root, **arguments, coordinator_origin=origin)
    # A later ordinary campaign update makes returning the original result meaningful.
    current = propose(tmp_path, root)
    assert current['revision'] > revised['revision'] > before['revision']
    return root, arguments, origin, before, revised, current


def bytes_of_history(root):
    return {path.name: path.read_bytes() for path in (root / 'history').glob('*.json')}


def test_coordinator_premise_retry_returns_original_hydrated_state_without_append(revised_campaign):
    root, arguments, origin, before, revised, current = revised_campaign
    for state in (before, revised):
        raw = state_io.read_json(root / 'history' / f"{state['revision']:04d}.json")
        assert raw['kind'] == research_history.KIND and raw != state
        assert raw['result_sha256'] == state['sha256']
    event = revised['events'][-1]
    assert event['kind'] == 'premise_revised'
    assert event['before_state_sha256'] == before['sha256']
    assert event['coordinator_origin'] == origin and event['coordinator_arguments'] == arguments
    history_before, head_before = bytes_of_history(root), (root / 'head.json').read_bytes()
    replayed = cycle.revise_premise(root, **arguments, coordinator_origin=origin)
    assert replayed == revised and replayed != current
    assert cycle._load(root)[1] == current
    assert bytes_of_history(root) == history_before
    assert (root / 'head.json').read_bytes() == head_before


@pytest.mark.parametrize('damage', ['before_revision', 'result_revision', 'current_head'])
def test_coordinator_premise_retry_refuses_resealed_corruption_anywhere_in_chain(revised_campaign, damage):
    root, arguments, origin, before, revised, current = revised_campaign
    revision = {'before_revision': before['revision'], 'result_revision': revised['revision'],
                'current_head': current['revision']}[damage]
    path = root / 'history' / f'{revision:04d}.json'
    raw = state_io.read_json(path)
    raw['changes'].append({'op': 'set', 'path': ['premises', 0, 'statement'], 'value': 'Forged retained premise.'})
    raw.pop('sha256')
    state_io.atomic_json(path, cycle._seal(raw))
    if revision == current['revision']:
        # Refresh the file pin so refusal must authenticate the reconstructed state.
        state_io.atomic_json(root / 'head.json', cycle._pin(path))
    history_before, head_before = bytes_of_history(root), (root / 'head.json').read_bytes()
    with pytest.raises(ValueError):
        cycle.revise_premise(root, **arguments, coordinator_origin=origin)
    assert bytes_of_history(root) == history_before
    assert (root / 'head.json').read_bytes() == head_before


def test_coordinator_premise_retry_still_refuses_changed_original_arguments(revised_campaign):
    root, arguments, origin, _, _, _ = revised_campaign
    history_before, head_before = bytes_of_history(root), (root / 'head.json').read_bytes()
    with pytest.raises(ValueError, match='actual original decision'):
        cycle.revise_premise(root, **{**arguments, 'statement': 'An unrequested substitute.'}, coordinator_origin=origin)
    assert bytes_of_history(root) == history_before
    assert (root / 'head.json').read_bytes() == head_before
