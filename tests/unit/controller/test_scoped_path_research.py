"""One research decision and one ordinary child, through explicit inert peers.

The production ordinary-child execution join has a separate CHILDREN #16
regression. Here FakeStep supplies that interface while real graph custody,
the child specification/approval and the arithmetic adapter consume the handoff.
"""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from p11_fakes import FakeStep, installed_step
from ravel.validation.core import validate_schema
from ravel.workflow import research_controller as bridge, research_cycle as cycle, science
from method_decision_fixture import admit_method
from test_p11_mode import setup
from test_research_cycle import write
from test_research_full_cycle_transport import InertReviewHost


@pytest.mark.parametrize('foreign', [False, True], ids=['one-child', 'foreign-child-source'])
def test_one_research_cycle_consumes_one_selected_child_and_refuses_foreign_origin(tmp_path, monkeypatch, foreign):
    import test_p11_mode as child_fixture
    original_contract = child_fixture.contract

    def budgeted_contract(base):
        definition = original_contract(base)
        definition['budget']['output_tokens'] = 512
        return definition

    # This slice adds one 512-token scripted decision to the ordinary child
    # fixture, so its up-front campaign declaration includes that reservation.
    monkeypatch.setattr(child_fixture, 'contract', budgeted_contract)
    root, child, experiment, store, context, _ = setup(tmp_path)
    hypotheses = [
        {'id': 'increase', 'statement': 'The supplied second vector has the larger mean.',
         'stream': 'speculative', 'premise_ids': [], 'source_basis': [], 'parents': []},
        {'id': 'decrease', 'statement': 'The supplied second vector has the smaller mean.',
         'stream': 'speculative', 'premise_ids': [], 'source_basis': [], 'parents': []}]
    cycle.propose(root, hypotheses, origin={'kind': 'supplied_source',
        'pin': write(tmp_path / 'hypotheses.json', hypotheses), 'description': 'Generic supplied alternatives.'})
    design = {'id': experiment['id'], 'question': 'Compare the two supplied vectors.',
        'premise_ids': [], 'parent': None, 'change': 'Evaluate the declared comparison.',
        'study': experiment['study'], 'cost': {'calls': 0, 'output_tokens': 0, 'wall_seconds': 10, 'native_attempts': 1},
        'predictions': {'increase': 'better', 'decrease': 'worse'},
        'observable': {'pointer': '/decision', 'outcomes': {'better': 'better', 'worse': 'worse'}},
        'context_outputs': {}, 'acceptance_scope': 'supplied_math_diagnostic', 'exploratory': True}
    cycle.design(root, design)
    cycle.prepare_experiment(root, experiment['id'], child)
    experiment = deepcopy(cycle._load(root)[1]['experiments'][0])
    admit_method(child)
    assert science.approve(child, 'Run the declared supplied arithmetic control.', scripted=True) == 0
    selected = {'kind': 'child-selection', 'id': experiment['id'], 'study': deepcopy(experiment['study'])}
    if foreign:
        selected['study']['sha256'] = '0' * 64
    public_schema = {'type': 'object', 'additionalProperties': False,
        'required': ['kind', 'id', 'study'], 'properties': {
            'kind': {'type': 'string', 'const': 'child-selection'}, 'id': {'type': 'string'},
            'study': {'type': 'object', 'additionalProperties': False, 'required': ['path', 'sha256', 'size'],
                      'properties': {'path': {'type': 'string'}, 'sha256': {'type': 'string', 'minLength': 64, 'maxLength': 64},
                                     'size': {'type': 'integer', 'minimum': 0, 'maximum': 67108864}}}}}
    validate_schema(public_schema)
    source = write(tmp_path / 'subject.json', {'kind': 'prospective-child', 'id': experiment['id']})
    node = {'id': 'select-child', 'kind': 'model', 'role': 'proposer', 'action': 'model',
        'depends_on': [], 'inputs': [{'id': 'subject', 'path': source['path'], 'sha256': source['sha256']}],
        'packet': None, 'max_attempts': 1,
        'parameters': {'model': 'fictional-model', 'reasoning_effort': 'high', 'max_output_tokens': 512,
                       'instructions': 'Return the supplied generic selection record.', 'output_schema': public_schema}}
    graph_spec = {'schema_version': 1, 'graph_id': 'selected-child', 'nodes': [node], 'budget': {
        'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 512, 'max_wall_seconds': 60, 'max_reworks': 0}}
    parent = bridge._step('campaign', 'subgraph')
    parent.update(graph={'id': 'research.loop', 'instance': {}}, parameters={'campaign': str(root), 'research_request': source})
    context.update(research_campaign=str(root), research_max_wall_seconds=600,
                   plan_sha256=cycle.ce.digest({'steps': [parent]}))
    store.append('research-subgraph-entry', {'parent_step': parent, 'parent_step_sha256': cycle.ce.digest(parent),
        'parent_plan_sha256': context['plan_sha256'], 'request': source, 'campaign': str(root)})
    peer = FakeStep(InertReviewHost(lambda *args: deepcopy(selected)))
    graph = root / 'selection-graph'
    with installed_step(peer), bridge.bound(store, context):
        observation = cycle.execute_graph(root, graph, graph_spec, object())
        assert observation['complete'], json.dumps(observation, sort_keys=True)
        actual = cycle._graph_result(graph, 'select-child')['value']['value']
        assert list(Draft202012Validator(public_schema).iter_errors(actual)) == []
        assert actual == selected
        assert [(c['step']['kind'], c['step']['role']) for c in peer.calls] == [('author', 'research-explorer')]
        consumer_input = {**deepcopy(experiment), 'id': actual['id'], 'study': actual['study']}
        prior_outcomes = deepcopy(store.scan('research-step-outcome'))
        if foreign:
            with pytest.raises(ValueError, match='digest|sha256|changed'):
                bridge.run_child(root, consumer_input)
            assert len(peer.calls) == 1
            assert store.scan('research-step-outcome') == prior_outcomes
            assert science.execution.load_execution(child)['stages'].get('science') is None
        else:
            assert consumer_input == experiment
            assert cycle.run_experiment(root, actual['id']) == 0
            assert [(c['step']['kind'], c['step'].get('role'), c['step'].get('route')) for c in peer.calls] == [
                ('author', 'research-explorer', None), ('route', None, 'study')]
            assert peer.calls[-1]['step']['parameters']['own_checkin1'] is True
            assert science.execution.load_execution(child)['stages']['science']['status'] == 'succeeded'
            assert science.packet(child)['physics_validated'] is False
            assert len(store.scan('research-loop-reservation')) == 1
        # A second view of the same decision reuses its graph receipt.
        before = len(peer.calls)
        assert cycle.execute_graph(root, graph, graph_spec, object())['complete']
        assert len(peer.calls) == before
