"""Observed-session independence of research stage roles (XF04), on the real stage engines.

Every case runs the installed ``research_coordinator_decisions`` checks against a real governed
campaign and real external role deliveries. Model families are descriptive labels; independence
rests on distinct observed actors, sessions and packets. No model or scientific worker runs.
"""
from copy import deepcopy
import inspect
import json
from pathlib import Path

import pytest

from ravel.workflow import (agent_graph, agent_host, research_coordinator_decisions as decisions,
                            research_orchestrator, research_protocol as protocol, transport_registry)
from ravel.workflow.graphs import ServiceRefused, stage as stage_graph

from test_agent_graph import external_response
from test_research_default_protocol import governed_cycle, synthetic_artifacts, write

STAGE = 'limitation_census'
PRODUCER, CRITIC = 'limitation-census', 'sufficiency-verifier'


@pytest.fixture(autouse=True)
def inert_decision_provider(monkeypatch):
    # The external decision provider is an inert seam; its refusals are tested in the gate suites.
    monkeypatch.setattr(protocol, 'decision_errors', lambda *a, **k: [])


def settings_for(model):
    return {'model': model, 'reasoning_effort': 'high', 'adapter': 'external',
            'max_output_tokens': 1024, 'max_wall_seconds': 60}


def prepared_stage(tmp_path, model='host-agent'):
    root = governed_cycle(tmp_path)
    artifact = write(root, 'census.json', synthetic_artifacts(root)[STAGE])
    settings = settings_for(model)
    value = research_orchestrator.run_protocol_stage(root, artifact, root / 'stage',
                                                     host=agent_host.AgentHost(), settings=settings)
    assert value['kind'] == 'research-stage-delivery-required' and not value['complete']
    return root, artifact, settings, root / 'stage/graph'


def deliver(graph_root, role, *, actor, invocation, model='host-agent'):
    pending = agent_graph.prepare_external(graph_root, role)
    fields = json.loads(Path(pending['request_file']).read_text())['parameters']['output_schema']['properties']
    public = {key: fields[key]['const'] for key in ('stage', 'role_id', 'subject_sha256')}
    public.update(verdict='accept', findings=['Synthetic transport control only.'], attributed_claim_ids=[])
    response = external_response(pending, graph_root.parent / (role + '-response.json'), value=public,
                                 actor_id=actor, invocation_id=invocation, observed_model=model)
    agent_graph.deliver_external(graph_root, role, response)


def deliver_separately(graph_root, model='host-agent'):
    for role in (PRODUCER, CRITIC):
        deliver(graph_root, role, actor='actor-' + role, invocation='session-' + role, model=model)


def legacy_complete(root, artifact, settings):
    return research_orchestrator.run_protocol_stage(root, artifact, root / 'stage',
                                                    host=agent_host.AgentHost(), settings=settings)


def graph_complete(root, artifact, settings):
    """The graph engine's own completion node, on the stage the legacy engine prepared."""
    prepared = research_orchestrator._read(research_orchestrator._pin(root / 'stage/preparation.json'))
    state = {'stage_request': stage_graph.request(artifact=artifact, out=root / 'stage', settings=settings,
                                                  host_key='inert', operation_sha256='0' * 64,
                                                  campaign_root=root),
             'prepared': prepared}
    return stage_graph._complete(state, None)


ENGINES = {'legacy': legacy_complete, 'graph': graph_complete}


def refusal(exc):
    """The original refusal, through the graph service's classification wrapper."""
    while not isinstance(exc, transport_registry.TransportRefusal) and exc.__cause__ is not None:
        exc = exc.__cause__
    return exc


@pytest.mark.parametrize('model,label', [('claude-control', 'same'), ('opaque-control', 'unknown')])
def test_XF04_same_or_unknown_family_critic_in_a_separate_session_is_credited_with_its_label(
        tmp_path, model, label):
    root, artifact, settings, graph_root = prepared_stage(tmp_path, model)
    deliver_separately(graph_root, model)
    checked = decisions.receipt_family_check(STAGE, graph_root, settings, root=root)
    assert checked[CRITIC]['family_check'] == label and checked[CRITIC]['family_relations'] == {PRODUCER: label}
    assert checked[CRITIC]['session_check'] == 'distinct'
    assert checked[CRITIC]['family_label'] == 'separate session, ' + label + ' model family'
    result = legacy_complete(root, artifact, settings)
    assert result['complete'] and result['scientific_acceptance'] is False
    assert protocol.methodology_status(root)['next_stage'] == 'ideas'


def test_XF04_a_reused_declared_actor_is_refused_at_delivery(tmp_path):
    root, artifact, settings, graph_root = prepared_stage(tmp_path)
    deliver(graph_root, PRODUCER, actor='producer-actor', invocation='producer-session')
    with pytest.raises(agent_graph.GraphError, match='declared actor'):
        deliver(graph_root, CRITIC, actor='producer-actor', invocation='critic-session')
    assert protocol.methodology_status(root)['next_stage'] == STAGE


@pytest.mark.parametrize('engine', sorted(ENGINES))
def test_XF04_critic_reusing_the_proposers_session_is_refused_before_complete_stage(tmp_path, monkeypatch, engine):
    root, artifact, settings, graph_root = prepared_stage(tmp_path)
    deliver(graph_root, PRODUCER, actor='producer-actor', invocation='shared-session')
    deliver(graph_root, CRITIC, actor='critic-actor', invocation='shared-session')
    # The pre-completion check alone must refuse: complete_stage never runs. Were that check
    # bypassed, this spy would be called and the test would fail.
    called = []
    monkeypatch.setattr(protocol, 'complete_stage', lambda *a, **k: called.append(a) or {'complete': True})
    with pytest.raises(Exception) as raised:
        ENGINES[engine](root, artifact, settings)
    found = refusal(raised.value)
    assert isinstance(found, transport_registry.TransportRefusal), raised.value
    assert {'session_independence:' + CRITIC + ':' + PRODUCER,
            'session_independence:' + PRODUCER + ':' + CRITIC} & set(found.missing)
    assert called == []
    assert protocol.methodology_status(root)['next_stage'] == STAGE


@pytest.mark.parametrize('missing', [PRODUCER, CRITIC])
def test_XF04_a_role_whose_delivery_cannot_be_found_is_refused(tmp_path, monkeypatch, missing):
    root, artifact, settings, graph_root = prepared_stage(tmp_path)
    present = CRITIC if missing == PRODUCER else PRODUCER
    deliver(graph_root, present, actor='actor-' + present, invocation='session-' + present)
    called = []
    monkeypatch.setattr(protocol, 'complete_stage', lambda *a, **k: called.append(a))
    with pytest.raises(agent_graph.GraphError, match='not complete'):
        decisions.receipt_family_check(STAGE, graph_root, settings, root=root)
    with pytest.raises(ServiceRefused, match='not complete'):
        graph_complete(root, artifact, settings)
    assert called == [] and protocol.methodology_status(root)['next_stage'] == STAGE


def test_XF04_an_earlier_stage_proposer_without_a_bound_delivery_is_refused(tmp_path):
    root = governed_cycle(tmp_path)
    # Acceptance (R3) judges the validate stage's producer, which never completed here.
    assert 'research-evolver' in decisions.stage_proposers('acceptance')
    with pytest.raises(ValueError, match='earlier producer has no completed bound stage: research-evolver'):
        decisions.stage_family_check(root, 'acceptance', {'ablation-critic': 'gpt-5', 'skeptical-verifier': 'gpt-5'})


def test_XF04_a_direct_callers_receipts_never_become_unverified_authority(tmp_path, monkeypatch):
    root, artifact, settings, graph_root = prepared_stage(tmp_path)
    deliver(graph_root, PRODUCER, actor='producer-actor', invocation='shared-session')
    deliver(graph_root, CRITIC, actor='critic-actor', invocation='shared-session')
    # A caller can label fabricated receipts as separate seats; the label is not a credit path.
    fabricated = {role: {'transport': {'actor_id': 'fabricated-' + role, 'invocation_id': 'fabricated-' + role},
                         'context_manifest_sha256': role, 'context_transport_separated': True}
                  for role in (PRODUCER, CRITIC)}
    labelled = decisions.dispatch_check(STAGE, {r: {'kind': 'producer'} for r in fabricated}, receipts=fabricated)
    assert {row['session_check'] for row in labelled.values()} == {'distinct'}
    # Neither completion check nor complete_stage accepts caller receipts: both recompute them
    # from the stage's Graph, which records one shared seat.
    for function in (decisions.receipt_family_check, protocol.complete_stage):
        assert 'receipts' not in inspect.signature(function).parameters
    prepared = research_orchestrator._read(research_orchestrator._pin(root / 'stage/preparation.json'))
    with pytest.raises(transport_registry.TransportRefusal, match='distinct actors, sessions and packets'):
        protocol.complete_stage(root, prepared, graph_root)
    with pytest.raises(transport_registry.TransportRefusal):
        legacy_complete(root, artifact, settings)
    assert protocol.methodology_status(root)['next_stage'] == STAGE


@pytest.mark.parametrize('field', ['actor', 'receipt_session', 'launcher_session', 'session_id'])
def test_XF04_every_observed_session_identity_of_a_seat_is_compared(field):
    """A fresh invocation id cannot hide a seat's reuse of another seat's actual CLI session."""
    def receipt(actor, invocation):
        return {'transport': {'actor_id': actor, 'invocation_id': invocation},
                'context_manifest_sha256': actor, 'context_transport_separated': True,
                'session': {'cli_session_id': None}}
    receipts = {PRODUCER: receipt('producer-actor', 'producer-invocation'),
                CRITIC: receipt('critic-actor', 'critic-invocation')}
    receipts[PRODUCER]['session']['cli_session_id'] = 'producer-cli'
    reused = receipts[CRITIC]
    if field == 'actor':
        reused['transport']['actor_id'] = 'producer-actor'
    elif field == 'receipt_session':
        reused['session']['cli_session_id'] = 'producer-cli'
    elif field == 'launcher_session':
        reused['transport']['session_receipt'] = {'launcher_receipt': {'cli_reported': {'session_id': 'producer-cli'}}}
    else:
        reused['transport']['session_id'] = 'producer-cli'
    assigned = {PRODUCER: {'kind': 'producer'}, CRITIC: {'kind': 'specialist'}}
    with pytest.raises(transport_registry.TransportRefusal) as refused:
        decisions.dispatch_check(STAGE, assigned, receipts=receipts)
    assert refused.value.missing == ['session_independence:' + CRITIC + ':' + PRODUCER]
    separate = deepcopy(receipts)
    separate[CRITIC] = receipt('critic-actor', 'critic-invocation')
    assert decisions.dispatch_check(STAGE, assigned, receipts=separate)[CRITIC]['session_check'] == 'distinct'


@pytest.mark.parametrize('absent', ['actor_id', 'session', 'packet', 'separation'])
def test_XF04_a_seat_without_an_observed_actor_session_or_packet_is_refused(absent):
    receipts = {role: {'transport': {'actor_id': 'actor-' + role, 'invocation_id': 'session-' + role},
                       'context_manifest_sha256': 'packet-' + role, 'context_transport_separated': True}
                for role in (PRODUCER, CRITIC)}
    row = receipts[CRITIC]
    if absent == 'actor_id':
        del row['transport']['actor_id']
    elif absent == 'session':
        del row['transport']['invocation_id']
    elif absent == 'packet':
        row['context_manifest_sha256'] = None
    else:
        row['context_transport_separated'] = False
    with pytest.raises(transport_registry.TransportRefusal) as refused:
        decisions.dispatch_check(STAGE, {r: {'kind': 'producer'} for r in receipts}, receipts=receipts)
    assert refused.value.missing == ['session_independence:' + CRITIC]


def test_XF04_a_completed_stage_receipt_is_recomputed_not_read_from_its_saved_pin(tmp_path):
    root, artifact, settings, graph_root = prepared_stage(tmp_path)
    deliver_separately(graph_root)
    assert legacy_complete(root, artifact, settings)['complete']
    receipt = decisions.bound_stage_receipt(root, PRODUCER)
    assert receipt['transport']['actor_id'] == 'actor-' + PRODUCER
    row = next(r for r in protocol.methodology_status(root)['record']['stages'] if r['id'] == STAGE)
    saved = Path(row['worker_receipts'][PRODUCER]['path'])
    saved = saved if saved.is_absolute() else root / saved
    rewritten = json.loads(saved.read_text())
    rewritten['transport']['actor_id'] = 'rewritten-actor'
    saved.write_text(json.dumps(rewritten))
    with pytest.raises(ValueError):
        decisions.bound_stage_receipt(root, PRODUCER)


def test_XF04_a_changed_current_graph_receipt_is_refused(tmp_path):
    root, artifact, settings, graph_root = prepared_stage(tmp_path)
    deliver_separately(graph_root)
    result = agent_graph.status(graph_root)['nodes'][CRITIC]['result']
    (graph_root / result['path']).write_text('{}')
    with pytest.raises(ValueError):
        decisions.receipt_family_check(STAGE, graph_root, settings, root=root)
    assert protocol.methodology_status(root)['next_stage'] == STAGE


def test_XF04_both_engines_check_sessions_before_stage_completion():
    import ast
    for function in (stage_graph._complete, research_orchestrator.run_protocol_stage):
        tree = ast.parse(inspect.getsource(function).lstrip())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        check = next(n for n in calls if n.func.attr == 'receipt_family_check')
        completion = next(n for n in calls if n.func.attr == 'complete_stage')
        assert check.lineno < completion.lineno
        assert any(k.arg == 'root' for k in check.keywords)
