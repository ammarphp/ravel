"""Governed research calls use the binding peer interface, with inert transports."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_graph, research_cycle as cycle, research_controller as bridge
from p11_fakes import FakeRunStore, FakeStep, installed_step
from test_research_cycle import contract, write


def setup(tmp_path):
    definition = contract(tmp_path)
    definition['budget'].update(calls=24, output_tokens=10000)
    root = tmp_path / 'campaign'
    cycle.create(root, definition, base_dir=tmp_path, evaluation_harness=True)
    source = write(tmp_path / 'subject.json', {'scientific': 'supplied-only'})
    fields = {'stage': {'type': 'string', 'const': 'screen'},
              'role_id': {'type': 'string', 'const': 'producer-seat'},
              'subject_sha256': {'type': 'string', 'const': source['sha256']},
              'verdict': {'type': 'string'}, 'findings': {'type': 'array', 'items': {'type': 'string'}},
              'attributed_claim_ids': {'type': 'array', 'items': {'type': 'string'}}}
    node = {'id': 'producer-seat', 'kind': 'model', 'role': 'proposer', 'action': 'model',
            'depends_on': [], 'inputs': [{'id': 'subject', 'path': source['path'], 'sha256': source['sha256']}],
            'packet': None, 'max_attempts': 1, 'parameters': {'model': 'gpt-5', 'reasoning_effort': 'high',
                'max_output_tokens': 256, 'instructions': 'Return the supplied public record.',
                'output_schema': {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}}}
    spec = {'schema_version': 1, 'graph_id': 'governed-research-control', 'nodes': [node],
            'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 256,
                       'max_wall_seconds': 60, 'max_reworks': 0}}
    store = FakeRunStore('research-control', root=tmp_path.parent / (tmp_path.name + '-controller-store'))
    parent = bridge._step('campaign', 'subgraph')
    parent.update(graph={'id': 'research.loop', 'instance': {}},
                  parameters={'campaign': str(root), 'research_request': source})
    context = {'run_dir': str(tmp_path), 'research_max_wall_seconds': 600,
               'research_campaign': str(root), 'plan_sha256': cycle.ce.digest({'steps': [parent]})}
    store.append('research-subgraph-entry', {'parent_step': parent,
        'parent_step_sha256': cycle.ce.digest(parent), 'parent_plan_sha256': context['plan_sha256'],
        'request': source, 'campaign': str(root)})
    return root, spec, store, context


def test_R06_P03_governed_role_dispatch_preserves_real_graph_custody(tmp_path):
    root, spec, store, context = setup(tmp_path)
    peer = FakeStep()
    graph = root / 'role-graph'
    with installed_step(peer), bridge.bound(store, context):
        result = cycle.execute_graph(root, graph, spec, object())
        assert result['complete'], json.dumps(result.get('nodes'), indent=2)
        assert cycle.execute_graph(root, graph, spec, object())['complete']
    assert len(peer.calls) == 1
    node = peer.calls[0]['step']
    assert node['kind'] == 'author' and node['role'] == 'research-explorer'
    assert node['budget']['wall_seconds'] == spec['budget']['max_wall_seconds']
    assert node['parameters']['research_node'] == spec['nodes'][0]
    assert peer.calls[0]['context']['run_id'] == store.run_id
    actual = cycle._graph_result(graph, 'producer-seat')
    assert actual['value']['value']['verdict'] == 'accept'
    assert actual['value']['transport']['controller_run_id'] == store.run_id
    assert actual['value']['transport']['observed_model'] == 'gpt-5'
    assert len(store.scan('research-call')) == 1
    derived = store.scan('research-derived-step')
    assert len(derived) == 1 and derived[0]['record']['step'] == node
    assert derived[0]['record']['parent_plan_sha256'] == context['plan_sha256']
    assert store.read('research-subgraph-entry', derived[0]['record']['parent_entry_id'])['record']['campaign'] == str(root)
    assert cycle._load(root)[1]['resource_ledger'][0]['ceiling']['calls'] == 1


@pytest.mark.parametrize('damage', ['inactive_scope', 'completed_graph', 'changed_request_source', 'changed_node'])
def test_R06_derived_publication_requires_original_live_graph_and_protected_scope(tmp_path, damage):
    root, spec, store, context = setup(tmp_path)
    peer = FakeStep()
    graph = root/'role-graph'
    with installed_step(peer), bridge.bound(store, context):
        assert cycle.execute_graph(root, graph, spec, object())['complete']
    call = peer.calls[0]
    step, actual_context = deepcopy(call['step']), deepcopy(call['context'])
    before = deepcopy(store.scan('research-derived-step'))
    if damage == 'inactive_scope':
        with pytest.raises(ValueError, match='controller composition scope'):
            bridge._derive_dispatch(store, step, actual_context)
        return
    if damage == 'changed_request_source':
        Path(store.scan('research-subgraph-entry')[0]['record']['request']['path']).write_text('{}')
    elif damage == 'changed_node':
        step['parameters']['research_node']['parameters']['instructions'] = 'Changed after original admission.'
    with bridge.bound(store, actual_context), pytest.raises(ValueError):
        bridge._derive_dispatch(store, step, actual_context)
    assert store.scan('research-derived-step') == before


@pytest.mark.parametrize('status', ['held', 'failed', 'budget_exhausted'])
def test_R06_governed_refusal_never_runs_legacy_transport_or_credits_success(tmp_path, status):
    root, spec, store, context = setup(tmp_path)
    peer = FakeStep(script=[status])
    with installed_step(peer), bridge.bound(store, context):
        result = cycle.execute_graph(root, root / 'role-graph', spec, object())
    assert not result['complete']
    assert len(peer.calls) == 1
    assert store.scan('research-call') == []
    assert cycle._load(root)[1]['resource_ledger'][0]['ceiling']['calls'] == 1


def test_R06_an_unregistered_research_role_is_refused_never_given_a_default_card(tmp_path, monkeypatch):
    """Every graph role resolves through the registry today; when one does not, nothing is dispatched under a
    substitute card (the former fallback mapped it to research-explorer)."""
    from ravel.workflow import role_registry
    root, spec, store, context = setup(tmp_path)
    real = role_registry.load

    def load(name, **kwargs):
        if name in ('proposer', 'producer-seat', None):
            raise KeyError(name)
        return real(name, **kwargs)
    monkeypatch.setattr(role_registry, 'load', load)
    peer = FakeStep()
    with installed_step(peer), bridge.bound(store, context):
        result = cycle.execute_graph(root, root / 'role-graph', spec, object())
    assert not result['complete']
    assert peer.calls == [] and store.scan('research-call') == []  # nothing dispatched under any card


def test_V05_adopted_worker_output_and_observation_are_required(tmp_path):
    root, spec, store, context = setup(tmp_path)
    peer = FakeStep()
    run = peer.run

    def damaged(store, step, context):
        outcome = run(store, step, context)
        Path(outcome['outputs'][0]['path']).write_text('{}')
        return outcome

    peer.run = damaged
    with installed_step(peer), bridge.bound(store, context):
        result = cycle.execute_graph(root, root / 'role-graph', spec, object())
    assert not result['complete'] and store.scan('research-call') == []


@pytest.mark.parametrize('shared', ['session_id', 'actor_id'])
def test_XF04_C2_protected_dispatch_cannot_reuse_an_observed_identity(tmp_path, shared):
    root, spec, store, context = setup(tmp_path)
    peer = FakeStep()
    original = peer.run
    def reuse(store, step, context):
        outcome = original(store, step, context)
        observation = next(row for row in reversed(store.rows) if row['kind'] == 'step-observation')
        prior = next((row['record']['observation'] for row in store.rows if row['kind'] == 'research-call'), None)
        if prior is not None:
            observation['record'][shared] = prior[shared]
        return outcome
    peer.run = reuse
    with installed_step(peer), bridge.bound(store, context):
        assert cycle.execute_graph(root, root/'first-role', spec, object())['complete']
        second = cycle.execute_graph(root, root/'second-role', spec, object())
    assert not second['complete']
    assert 'reused an observed actor or session' in second['nodes']['producer-seat']['error']['message']
    assert len(store.scan('research-call')) == 1


def test_R06_protected_store_cannot_be_inside_the_original_run(tmp_path):
    store = FakeRunStore('unsafe-store', root=tmp_path/'run'/'store')
    with pytest.raises(ValueError, match='outside the original run'):
        with bridge.bound(store, {'run_dir': str(tmp_path/'run')}):
            raise AssertionError('invalid store entered composition scope')


def test_R06_original_graph_wall_exhaustion_is_typed_and_never_renews_a_worker(tmp_path, monkeypatch):
    from p11_fakes import FakeControl
    root, spec, store, context = setup(tmp_path)
    graph = root/'clocked-role'
    peer = FakeStep()
    with installed_step(peer), bridge.bound(store, context):
        assert cycle.execute_graph(root, graph, spec, object())['complete']
        saved = cycle._graph_result(graph, 'producer-seat')
        _, state = agent_graph._load(graph)
        monkeypatch.setattr(agent_graph.time, 'time', lambda: state['started_epoch'] + 61)
        host = bridge.GovernedHost(store, {**context, 'run_id': store.run_id})
        control = FakeControl({'research': {'graph_root': str(graph)}})
        with pytest.raises(cycle.CampaignBudgetExhausted, match='wall-time budget exhausted'):
            host.execute(spec['nodes'][0], peer.calls[0]['context']['research']['request'], control)
    assert len(peer.calls) == 1
    boundary = store.scan('research-budget-boundary')[0]['record']
    assert boundary['kind'] == 'original_graph_wall_exhausted'
    assert boundary['started_epoch'] == state['started_epoch']
    assert boundary['max_wall_seconds'] == spec['budget']['max_wall_seconds']


def test_V05_public_rdj_edge_payload_gets_an_exact_controller_worker_projection(tmp_path):
    payload = tmp_path/'payload.json'
    payload.write_text('{"role":"rdj-edge-reviewer","claims":["fictional public assertion"]}')
    pin = cycle._pin(payload)
    node = {'role': 'rdj_edge_reviewer', 'packet': None,
            'inputs': [{'id': 'rdj-payload', 'path': pin['path'], 'sha256': pin['sha256']}]}
    context = {'run_dir': str(tmp_path/'run')}
    packet, subject = bridge._worker_packet(node, 'research-edge', context)
    assert subject == pin['sha256'] and node['packet'] is None
    assert bridge._worker_packet(node, 'research-edge', context) == (packet, subject)
    artifact = Path(packet['path'])/'artifacts/rdj-payload.json'
    assert artifact.read_bytes() == payload.read_bytes()
    artifact.write_text('{}')
    with pytest.raises(ValueError):
        bridge._worker_packet(node, 'research-edge', context)
    payload.write_text('{}')
    with pytest.raises(ValueError, match='source changed'):
        bridge._worker_packet(node, 'research-other-edge', context)


def test_V05_extra_edge_inputs_cannot_be_hidden_by_a_narrow_projection(tmp_path):
    node = {'role': 'rdj_edge_reviewer', 'packet': None,
            'inputs': [{'id': 'rdj-payload'}, {'id': 'other-source'}]}
    assert bridge._worker_packet(node, 'research-edge', {'run_dir': str(tmp_path)}) == (None, None)


def test_P03_operation_dispatch_keeps_the_registered_production_executor(tmp_path):
    root, spec, store, context = setup(tmp_path)
    node = spec['nodes'][0]
    node.update(kind='tool', role='designer', action='quantitative-predictive', parameters={})
    spec['budget']['max_output_tokens'] = 0
    peer = FakeStep(script=['held'])
    with installed_step(peer), bridge.bound(store, context):
        result = cycle.execute_graph(root, root/'operation-role', spec, object())
    assert not result['complete']
    assert peer.calls[0]['step']['kind'] == 'operate'
    assert peer.calls[0]['step']['operation'] == 'quantitative-predictive'
    assert peer.calls[0]['step']['role'] == 'calculation'
    assert peer.calls[0]['step']['parameters']['research_node'] == node
    assert store.scan('research-call') == []


def test_R06_explicit_unregistered_role_never_falls_back_to_graph_role(tmp_path):
    _, spec, store, context = setup(tmp_path)
    node = deepcopy(spec['nodes'][0])
    node['registry_role'] = 'unregistered-role-control'
    assert node['role'] == 'proposer'
    host = bridge.GovernedHost(store, context)
    with pytest.raises(ValueError, match='research node has no registered governing role'):
        host.execute(node, {}, object())
    assert store.scan('research-call') == []
