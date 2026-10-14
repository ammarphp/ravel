"""ravel_gate: in-graph interceptor and the shared broker guard. Synthetic cards and data only."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from ravel.workflow import effect_ledger, graph_nodes, graph_registry, role_registry, tool_gate, toolbelt
from ravel.workflow.broker import Broker, work_root

GRAPH = {'id': 'synthetic.tools', 'version': 1}


@pytest.fixture
def run(tmp_path, monkeypatch):
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setenv('RAVEL_STATE_DIR', str(root / 'state'))
    run = root / 'run'
    run.mkdir()
    return run


def card():
    return deepcopy(role_registry.load('ablation-critic'))


def broker_for(run, tools, *, max_calls=20, sinks=None, graph_id=None):
    workspace = work_root(run) / 'worker' / '1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    (workspace / 'inputs/data.txt').write_text('synthetic')
    broker = Broker(run, workspace, node_id='worker', attempt=1,
                    allowed_actions=['read', 'write', 'knowledge query'], max_calls=max_calls,
                    guards=[tool_gate.broker_guard(tools, rundir=run, sinks=sinks, graph_id=graph_id)])
    toolbelt.register_actions(broker, card())
    return broker


def gate_for(run, tools, broker, turn=1, **options):
    return tool_gate.ravel_gate(tools, scope_root=run, graph=GRAPH, broker_call=broker.call,
                                prefix=effect_ledger.path(GRAPH['id'], {'case': 'synthetic'}, None, {'turn': turn}),
                                **options)


def request(name, args, identity):
    return {'tool_call': {'name': name, 'args': args, 'id': identity}}


def test_in_graph_tool_node_runs_calls_through_the_gate(run):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode
    tools = toolbelt.for_card(card())
    broker = broker_for(run, tools)
    node = ToolNode(tool_gate.langchain_tools(tools), wrap_tool_call=gate_for(run, tools, broker),
                    handle_tool_errors=False)
    graph = StateGraph(MessagesState)
    graph.add_node('tools', node)
    graph.add_edge(START, 'tools')
    graph.add_edge('tools', END)
    calls = [{'name': 'ws_read', 'args': {'path': 'inputs/data.txt'}, 'id': 't1'},
             {'name': 'shell_exec', 'args': {'argv': ['true']}, 'id': 't2'}]
    out = graph.compile().invoke({'messages': [AIMessage(content='', tool_calls=calls)]})
    read, refused = out['messages'][1:]
    assert json.loads(read.content)['stdout_tail'] == 'synthetic' and read.artifact['atlas_id'] == 'cmd:work'
    assert refused.status == 'error' and json.loads(refused.content)['error']['code'] == 'not_allowlisted'
    assert refused.artifact['tool_name'] == 'shell_exec'
    # ToolNode runs the two calls concurrently; each has its own receipt.
    assert sorted(r['action'] for r in broker.verify_ledger()) == ['read', 'tool:shell_exec']


def test_direct_tool_execution_outside_the_gate_is_refused():
    tool = tool_gate.langchain_tools(toolbelt.for_card(card()))[1]
    with pytest.raises(RuntimeError, match='only through ravel_gate'):
        tool.func(path='inputs/data.txt')


def test_replayed_call_returns_its_receipt_before_any_counter_moves(run):
    tools = toolbelt.for_card(card())
    broker = broker_for(run, tools, max_calls=1)
    gate = gate_for(run, tools, broker)
    first = gate.call(request('ws_read', {'path': 'inputs/data.txt'}, 't1'))
    assert first['status'] == 'ok'
    # The budget is spent; a replay of the same path still returns the receipted reply.
    again = gate_for(run, tools, broker).call(request('ws_read', {'path': 'inputs/data.txt'}, 't1'))
    assert again == first and len(broker.verify_ledger()) == 1
    other = gate.call(request('ws_read', {'path': 'inputs/data.txt'}, 't2'))
    assert other['error']['code'] == 'budget_exhausted'


def test_started_call_without_outcome_is_ambiguous_and_not_redispatched(run):
    tools = toolbelt.for_card(card())
    broker = broker_for(run, tools)
    gate = gate_for(run, tools, broker)

    class Crash(BaseException):
        pass

    def crash(_request):
        raise Crash()
    gate.broker_call = crash
    with pytest.raises(Crash):
        gate.call(request('ws_read', {'path': 'inputs/data.txt'}, 't1'))
    gate.broker_call = broker.call
    with pytest.raises(effect_ledger.Ambiguous):
        gate.call(request('ws_read', {'path': 'inputs/data.txt'}, 't1'))
    assert broker.verify_ledger() == []


def test_third_identical_call_on_distinct_paths_escalates(run):
    tools = toolbelt.for_card(card())
    broker = broker_for(run, tools)
    gate = gate_for(run, tools, broker)
    replies = [gate.call(request('ws_read', {'path': 'inputs/data.txt'}, f't{i}')) for i in range(3)]
    assert [r['status'] for r in replies] == ['ok', 'ok', 'refused']
    assert replies[-1]['error']['code'] == 'decision_block'


def test_consequential_action_without_a_passing_gate_is_refused_with_the_gate_record(run):
    tools = toolbelt.for_card(card())
    sinks = [{'sink': 'knowledge query', 'gates': ['launch'], 'action_digest_of': 'synthetic'}]
    broker = broker_for(run, tools, sinks=sinks)
    seen = []

    def refusing(rundir, gate, action):
        seen.append((gate, action['digest']))
        return [{'code': 'approval_missing', 'gate': gate, 'provider': 'review_points', 'message': 'synthetic',
                 'fix': 'none', 'pins': []}]
    with graph_nodes.gate_checker(refusing, providers=lambda gate: {}):
        reply = broker.call(toolbelt.to_request(tools, 'knowledge_coverage', {}, 'c1'))
    assert reply['status'] == 'refused' and reply['error']['code'] == 'gate_refused'
    record = json.loads(reply['error']['message'])
    assert record['tool_name'] == 'knowledge_coverage' and record['gates'] == ['launch']
    assert record['errors'][0]['code'] == 'approval_missing' and seen[0][1] == record['action_digest']
    with graph_nodes.gate_checker(lambda *a: [], providers=lambda gate: {}):
        passed = broker.call(toolbelt.to_request(tools, 'knowledge_coverage', {}, 'c2'))
    assert passed['status'] == 'ok'
    assert len(broker.verify_ledger()) == 2


def test_inactive_mandatory_provider_refuses_with_provider_inactive(run, monkeypatch):
    tools = toolbelt.for_card(card())
    sinks = [{'sink': 'knowledge query', 'gates': ['launch'], 'action_digest_of': 'synthetic'}]
    broker = broker_for(run, tools, sinks=sinks, graph_id='synthetic.tools')
    row = {'id': 'synthetic.tools', 'gates': {'launch': {'required_providers': ['review_points']}}}
    monkeypatch.setattr(graph_registry, 'get', lambda graph_id: row)
    with graph_nodes.gate_checker(lambda *a: [], providers=lambda gate: {'review_points': False}):
        reply = broker.call(toolbelt.to_request(tools, 'knowledge_coverage', {}, 'c1'))
    assert reply['error']['code'] == 'provider_inactive'
    assert json.loads(reply['error']['message'])['errors'][0]['provider'] == 'review_points'


def test_consequential_list_decides_not_the_author():
    assert tool_gate.consequential_gates('ravel.workflow.agent_graph:deliver_external') == ['delivery']
    assert tool_gate.consequential_gates('read') == []


def test_replay_with_a_changed_tool_or_arguments_is_refused(run):
    tools = toolbelt.for_card(card())
    broker = broker_for(run, tools)
    (broker.workspace / 'inputs/other.txt').write_text('other')
    gate = gate_for(run, tools, broker)
    assert gate.call(request('ws_read', {'path': 'inputs/data.txt'}, 't1'))['status'] == 'ok'
    for name, args in (('ws_read', {'path': 'inputs/other.txt'}), ('knowledge_coverage', {})):
        with pytest.raises(effect_ledger.NondeterministicRequest):
            gate_for(run, tools, broker).call(request(name, args, 't1'))
    assert len(broker.verify_ledger()) == 1


def test_replay_whose_broker_receipt_changed_is_refused(run):
    tools = toolbelt.for_card(card())
    broker = broker_for(run, tools)
    gate = gate_for(run, tools, broker, rundir=run)
    first = gate.call(request('ws_read', {'path': 'inputs/data.txt'}, 't1'))
    assert gate_for(run, tools, broker, rundir=run).call(request('ws_read', {'path': 'inputs/data.txt'}, 't1')) == first
    receipt = broker.workspace / 'calls/1.json'
    receipt.write_text(receipt.read_text().replace('synthetic', 'forged!!!'))
    with pytest.raises((effect_ledger.NondeterministicRequest, ValueError)):
        gate_for(run, tools, broker, rundir=run).call(request('ws_read', {'path': 'inputs/data.txt'}, 't1'))


def test_unlisted_alias_and_malformed_calls_are_refused_with_receipts(run):
    tools = [t for t in toolbelt.for_card(card()) if t['name'] in ('submit_final', 'ws_read')]
    broker = broker_for(run, tools)
    gate = gate_for(run, tools, broker)
    replies = [gate.call(request('read', {'path': 'inputs/data.txt'}, 'a1')),
               gate.call(request('ws_read', ['inputs/data.txt'], 'a2')),
               gate.call(request('ws_read', {'path': 'inputs/data.txt', 'extra': 1}, 'a3'))]
    assert [r['error']['code'] for r in replies] == ['not_allowlisted', 'invalid_call', 'not_allowlisted']
    assert [r['action'] for r in broker.verify_ledger()] == ['tool:read', 'read', 'read']


def test_shipped_sink_list_gates_the_broker_exec_action(run):
    assert tool_gate.consequential_gates('exec') == ['launch']
    belt = toolbelt.for_card(card())
    work = next(t for t in belt if t['name'] == 'ws_read')
    exec_tool = deepcopy(work) | {'name': 'exec_synthetic', 'args_schema': {'type': 'object'},
                                  'executes_through': {'action': 'exec', 'fixed_args': {}}}
    workspace = work_root(run) / 'worker' / '1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    broker = Broker(run, workspace, node_id='worker', attempt=1, allowed_actions=['exec'], max_calls=5,
                    guards=[tool_gate.broker_guard([exec_tool], rundir=run)])
    broker.register('exec', lambda args: {'stdout': 'ran'})
    refusing = lambda rundir, gate, action: [{'code': 'approval_missing', 'gate': gate, 'provider': 'synthetic',
                                              'message': 'synthetic', 'fix': 'none', 'pins': []}]
    with graph_nodes.gate_checker(refusing, providers=lambda gate: {}):
        reply = broker.call(toolbelt.to_request([exec_tool], 'exec_synthetic', {'argv': ['true']}, 'e1'))
    assert reply['error']['code'] == 'gate_refused' and json.loads(reply['error']['message'])['gates'] == ['launch']


def test_production_factory_installs_the_gate_and_narrows_knowledge(run):
    tools = toolbelt.for_card(card())
    workspace = work_root(run) / 'worker' / '1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    made = tool_gate.production_broker(run, workspace, tools=tools, role='ablation-critic', node_id='worker',
                                       attempt=1, max_calls=10)
    assert 'ravel_gate_broker_guard' in [g.__name__ for g in made.guards]
    assert made.allowed_actions == set(toolbelt.allowed_actions(tools))
    ops = toolbelt.knowledge_ops(tools)
    outside = next(op for op in ('xsec', 'constants', 'conventions', 'coverage') if op not in ops)
    replies = [made.call({'call_id': 'k1', 'action': 'knowledge query', 'args': {'op': outside, 'args': {}}}),
               made.call({'call_id': 'k2', 'action': 'knowledge.' + outside, 'args': {}}),
               made.call(toolbelt.to_request(tools, 'read', {'path': 'inputs/x'}, 'k3'))]
    assert [r['status'] for r in replies] == ['refused'] * 3
    shown = made.call(toolbelt.to_request(tools, 'knowledge_show', {'id': 'cmd:work'}, 'k4'))
    assert shown['status'] == 'ok', shown
