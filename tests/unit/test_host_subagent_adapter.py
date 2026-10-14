"""Host-subagent adapter controls: synthetic host reports only; no host CLI runs."""
import json

import pytest

from ravel.workflow import agent_worker as worker, broker, role_registry, transport_registry as tr
from ravel.workflow.transports import cli_worker, host_subagent

HOSTS = [d['id'] for d in tr.all_declarations() if d['transport_kind'] == 'host-subagent']


def spec(role='analysis-author', attempt=1):
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': 'host.worker', 'attempt': attempt,
            'role': {'id': role, 'version': role_registry.load(role)['version'],
                     'card_sha256': role_registry.card_sha256(role)},
            'transport_preference': ['host-subagent-claude'], 'inputs': [],
            'declared_outputs': [{'path': 'outputs/result.txt', 'kind': 'text', 'required': True}],
            'budgets': {'max_turns': 5, 'max_wall_seconds': 30, 'max_broker_calls': 5, 'max_cost_usd': None},
            'final_record_schema': 'producer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.delenv('RAVEL_WORK_ROOT', raising=False)
    (tmp_path / 'run').mkdir()
    return tmp_path / 'run'


@pytest.mark.parametrize('transport_id', HOSTS)
def test_host_routes_are_executable_but_never_blind_or_voting(transport_id):
    document = tr.load(transport_id)
    assert document['capabilities']['blind_capable'] is False and document['capabilities']['isolation'] == 'cli-policy'
    assert host_subagent.unsupported(document) is None and tr.executor_available(document)
    capabilities, reasons = tr.effective_capabilities(document, None)
    assert reasons == [] and capabilities['blind_capable'] is False
    assert not tr.blind_admissible(document)
    for role in ('physics-critic', 'physics-decider', 'skeptical-verifier'):
        assert 'isolation' in tr.unmet(document, capabilities, role_registry.load(role))


def test_a_blind_capable_host_declaration_is_refused():
    document = json.loads(json.dumps(tr.load('host-subagent-claude')))
    document['capabilities']['blind_capable'] = True
    assert host_subagent.unsupported(document) == 'blind_capable:host-subagent'


@pytest.mark.parametrize('role,missing', [('physics-critic', 'isolation'), ('physics-decider', 'isolation'),
                                          ('skeptical-verifier', 'isolation')])
def test_voting_and_blind_roles_are_refused_before_any_brief(run, role, missing):
    s = spec(role)
    ws = worker.materialize(run, s) if role not in worker.blind_roles() else worker.workspace(run, s['node_id'], 1)
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        host_subagent.brief(run, s, ws, transport_id='host-subagent-claude')
    assert refused.value.missing == [missing]


def test_brief_broker_and_host_reported_receipt(run):
    s = spec()
    ws = worker.materialize(run, s)
    packet = host_subagent.brief(run, s, ws, transport_id='host-subagent-claude')
    assert json.loads((ws / 'inputs/host-brief.json').read_text()) == packet
    assert {'ws_read', 'ws_write'} <= set(packet['tools']) and packet['attestation'] == 'host_attested'
    with host_subagent.serve_broker(run, s, packet):
        reply = broker.socket_call(packet['broker_socket'], {'call_id': 'c1', 'action': 'write',
                                                             'args': {'path': 'outputs/result.txt', 'content': 'x'}})
    assert reply['status'] == 'ok'
    receipt = host_subagent.complete(run, s, packet, final={'completed': True, 'summary': 'host reported'})
    assert receipt['status'] == 'ok' and receipt['attestation'] == 'host_attested'
    assert receipt['isolation']['profile'] == 'cli-policy' and receipt['isolation']['user_configuration_loaded'] is True
    assert receipt['transport']['transport_kind'] == 'host-subagent' and receipt['broker']['calls'] == 1


def test_cli_worker_adapter_never_launches_a_host_route(run, monkeypatch):
    from ravel.workflow import sandbox
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    s = spec()
    ws = worker.materialize(run, s)
    selection = {'transport_id': 'host-subagent-claude', 'model': 'claude-x', 'effort': None}
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(run, s, ws, selection=selection)
    assert refused.value.missing == ['transport_kind:host-subagent']


def test_host_broker_is_the_gated_production_broker_and_serves_every_listed_tool(run):
    from ravel.workflow import toolbelt
    s = spec()
    ws = worker.materialize(run, s)
    packet = host_subagent.brief(run, s, ws, transport_id='host-subagent-claude')
    knowledge = [n for n in packet['tools'] if n.startswith('knowledge_')]
    assert knowledge, packet['tools']
    with host_subagent.serve_broker(run, s, packet) as served:
        assert 'ravel_gate_broker_guard' in [g.__name__ for g in served.guards]
        belt = json.loads((broker.custody(run) / (worker._key(s['node_id'], 1) + '.host-toolbelt.json')).read_text())
        tools = [t for t in belt['tools'] if t['name'] in packet['tools']]
        find = toolbelt.to_request(tools, 'knowledge_find', {'text': 'workspace'}, 'k1')
        replies = [broker.socket_call(packet['broker_socket'], find),
                   broker.socket_call(packet['broker_socket'], toolbelt.to_request(tools, 'read', {'path': 'inputs/x'}, 'a1')),
                   broker.socket_call(packet['broker_socket'], {'call_id': 'a2', 'action': 'knowledge query',
                                                                'args': {'op': 'xsec', 'args': {}}})]
    assert [r['status'] for r in replies] == ['ok', 'refused', 'refused']


def test_host_broker_refuses_a_brief_whose_toolbelt_changed(run):
    s = spec()
    ws = worker.materialize(run, s)
    packet = host_subagent.brief(run, s, ws, transport_id='host-subagent-claude')
    widened = {**packet, 'tools': packet['tools'] + ['cmd_unlisted']}
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        with host_subagent.serve_broker(run, s, widened):
            pass
    assert refused.value.missing == ['toolbelt:changed']
