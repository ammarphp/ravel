"""The broker MCP face: one toolbelt and one receipt on every transport. Synthetic data only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from ravel.workflow import broker as broker_module, broker_mcp, effect_ledger, role_registry, tool_gate, toolbelt
from ravel.workflow import sandbox, transport_registry
from ravel.workflow.broker import Broker, work_root

SRC = Path(__file__).resolve().parents[2] / 'src'
TRANSPORT_FIELDS = {'started_utc', 'finished_utc', 'wall_seconds'}


def card():
    return deepcopy(role_registry.load('ablation-critic'))


def make(root, tools, *, shared_run=None):
    """A production broker. ``shared_run`` keeps one run path (knowledge results bind the run)
    while each side gets its own custody and workspace through its own state directory."""
    run = root / 'run'
    if shared_run is not None:
        os.environ['RAVEL_STATE_DIR'] = str(root / 'state')  # restored by the fixture's monkeypatch
        run = shared_run
        run.mkdir(exist_ok=True)
    workspace = work_root(run) / 'worker' / '1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    (workspace / 'inputs/data.txt').write_text('synthetic')
    # The production factory the CLI supervisor and the host-subagent broker use; no hand-installed guard.
    broker = tool_gate.production_broker(run, workspace, tools=tools, role=card()['id'], node_id='worker', attempt=1,
                                         max_calls=20)
    return run, broker


@pytest.fixture
def root(tmp_path, monkeypatch):
    base = Path(os.path.realpath(tmp_path))
    monkeypatch.setenv('RAVEL_STATE_DIR', str(base / 'state'))
    return base


def normalized(broker):
    rows = []
    for receipt in broker.verify_ledger():
        rows.append({k: v for k, v in receipt.items() if k not in TRANSPORT_FIELDS})
    return rows


def rpc(server, method, params=None, rpc_id=1):
    return server.handle({'jsonrpc': '2.0', 'id': rpc_id, 'method': method, 'params': params or {}})


# ---- acceptance 3: in-graph loop, socket and MCP give equal receipts apart from transport fields

@pytest.mark.parametrize('name,args', [('ws_read', {'path': 'inputs/data.txt'}),
                                       ('knowledge_show', {'id': 'cmd:work'}),
                                       ('shell_exec', {'argv': ['true']}),
                                       ('read', {'path': 'inputs/data.txt'}),
                                       ('knowledge_show', {'op': 'xsec', 'id': 'cmd:work'}),
                                       ('ws_read', {'path': 'inputs/data.txt', 'extra': True})])
def test_same_call_gives_equal_receipts_in_graph_socket_and_mcp(root, name, args):
    tools = toolbelt.for_card(card())
    prefix = effect_ledger.path('synthetic.tools', {'case': 'synthetic'}, None, {'turn': 1})
    identity = tool_gate.call_id(prefix + '/tool:t1')

    shared = root / 'run'
    run, in_graph = make(root / 'graph', tools, shared_run=shared)
    gate = tool_gate.ravel_gate(tools, scope_root=root / 'graph-scope', graph={'id': 'synthetic.tools', 'version': 1},
                                prefix=prefix, broker_call=in_graph.call)
    graph_reply = gate.call({'tool_call': {'name': name, 'args': args, 'id': 't1'}})
    receipts = [normalized(in_graph)]

    _, socket_side = make(root / 'socket', tools, shared_run=shared)
    with broker_module.serve(socket_side):
        socket_reply = broker_module.socket_call(socket_side.socket_path,
                                                 toolbelt.to_request(tools, name, args, identity))
    receipts.append(normalized(socket_side))

    _, mcp_side = make(root / 'mcp', tools, shared_run=shared)
    with broker_module.serve(mcp_side):
        server = broker_mcp.Server(tools, lambda r: broker_module.socket_call(mcp_side.socket_path, r))
        result = rpc(server, 'tools/call', {'name': name, 'arguments': args, '_meta': {'call_id': identity}})['result']
    mcp_reply = result['structuredContent']
    receipts.append(normalized(mcp_side))

    assert graph_reply == socket_reply == mcp_reply
    assert result['isError'] is (mcp_reply['status'] != 'ok')
    assert receipts[0] == receipts[1] == receipts[2] and len(receipts[0]) == 1
    if name in ('shell_exec', 'read'):  # outside the toolbelt: refused by name, with a receipt, on every path
        assert receipts[0][0]['action'] == 'tool:' + name and receipts[0][0]['status'] == 'refused'
    if name == 'knowledge_show':
        assert receipts[0][0]['status'] == ('refused' if 'op' in args else 'ok'), receipts[0][0]


def test_mcp_malformed_calls_are_refused_by_the_broker_with_a_receipt(root):
    tools = toolbelt.for_card(card())
    _, side = make(root / 'malformed', tools)
    server = broker_mcp.Server(tools, side.call)
    for n, params in enumerate([{'name': 7, 'arguments': {}}, {'name': 'ws_read', 'arguments': ['x']},
                                {'name': 'ws_read'}]):
        result = rpc(server, 'tools/call', params, rpc_id=n)['result']
        assert result['isError'] is True and result['structuredContent']['status'] == 'refused', params
    assert [r['status'] for r in side.verify_ledger()] == ['refused', 'refused', 'refused']


# ---- the JSON-RPC core

def test_tools_list_is_the_card_toolbelt_without_structured_output(root):
    tools = toolbelt.for_card(card())
    server = broker_mcp.Server(tools, lambda r: {})
    init = rpc(server, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}})['result']
    assert init['serverInfo']['name'] == 'ravel-broker' and 'tools' in init['capabilities']
    assert server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) is None
    listed = rpc(server, 'tools/list')['result']['tools']
    assert [t['name'] for t in listed] == [t['name'] for t in tools if t['name'] != 'submit_final']
    assert all(t['_meta']['atlas_id'] and t['inputSchema']['type'] == 'object' for t in listed)
    assert rpc(server, 'nope')['error']['code'] == broker_mcp.METHOD_NOT_FOUND
    assert rpc(server, 'tools/call', {'name': 'submit_final', 'arguments': {}})['error']['code'] == \
        broker_mcp.INVALID_PARAMS


def test_ravel_work_mcp_serves_stdio_against_the_broker_socket(root):
    belt = toolbelt.build(card())
    _, side = make(root / 'stdio', belt['tools'])
    (side.workspace / 'toolbelt.json').write_text(json.dumps(belt))
    lines = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
             {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
             {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
             {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
              'params': {'name': 'ws_read', 'arguments': {'path': 'inputs/data.txt'}}}]
    env = {**os.environ, 'PYTHONPATH': str(SRC)}
    with broker_module.serve(side):
        done = subprocess.run([sys.executable, '-m', 'ravel', 'work', 'mcp', '--workspace', str(side.workspace),
                               '--socket', str(side.socket_path)], input='\n'.join(json.dumps(x) for x in lines) + '\n',
                              capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    replies = [json.loads(x) for x in done.stdout.splitlines()]
    assert [r['id'] for r in replies] == [1, 2, 3]
    assert replies[2]['result']['structuredContent']['stdout_tail'] == 'synthetic'
    assert len(side.verify_ledger()) == 1


def test_cli_worker_mcp_command_serves_inside_the_worker_sandbox(root, require_sandbox):
    """The CLI starts the MCP face inside the worker's sandbox, which reads src/ and not the tree
    around it; the package must import there (a refused stat of pyproject.toml once closed it)."""
    from ravel.workflow.transports import cli_worker
    belt = toolbelt.build(card())
    _, side = make(root / 'sandboxed', belt['tools'])
    toolbelt_path = side.workspace / 'inputs' / 'toolbelt.json'
    toolbelt_path.write_text(json.dumps(belt))
    socket = '/tmp/ravel-broker.sock' if sandbox.available() == 'linux' else side.socket_path
    command = cli_worker.mcp_command(side.workspace, toolbelt_path, socket)
    lines = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
             {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
             {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
              'params': {'name': 'ws_read', 'arguments': {'path': 'inputs/data.txt'}}}]
    with broker_module.serve(side):
        argv = sandbox.command(side.workspace, command, read_paths=sandbox.runtime_paths(command),
                               broker_socket=side.socket_path)
        done = subprocess.run(argv, cwd=side.workspace, input='\n'.join(json.dumps(x) for x in lines) + '\n',
                              capture_output=True, text=True, timeout=120,
                              env={'PATH': '/usr/bin:/bin', 'HOME': str(side.workspace / 'scratch'),
                                   'PYTHONDONTWRITEBYTECODE': '1'})
    assert done.returncode == 0, done.stderr
    replies = [json.loads(x) for x in done.stdout.splitlines()]
    assert [r['id'] for r in replies] == [1, 2, 3]
    assert replies[2]['result']['structuredContent']['stdout_tail'] == 'synthetic'


def test_work_mcp_refuses_an_edited_toolbelt(root):
    belt = toolbelt.build(card())
    belt['tools'].append(deepcopy(belt['tools'][1]) | {'name': 'widened'})
    path = root / 'toolbelt.json'
    path.write_text(json.dumps(belt))
    from ravel.workflow import work_cli
    with pytest.raises(SystemExit):
        work_cli.main(['mcp', '--workspace', str(root), '--toolbelt', str(path), '--socket', str(root / 's')])


# ---- per-CLI configuration from the transport rows

def _command_from(kind, written):
    path = Path(written['path'])
    if kind in ('mcp_config_flag', 'settings_json'):
        entry = json.loads(path.read_text())['mcpServers']['ravel']
        return [entry['command'], *entry['args']]
    if kind == 'codex_home':
        entry = tomllib.loads(path.read_text())['mcp_servers']['ravel']
        return [entry['command'], *entry['args']]
    return json.loads(path.read_text())['mcp']['ravel']['command']


@pytest.mark.parametrize('identity', ['claude-cli-worker', 'codex-cli-worker', 'gemini-cli-worker', 'opencode-worker',
                                      'antigravity-cli-worker'])
def test_cli_worker_stub_lists_the_toolbelt_through_its_mcp_configuration(root, identity):
    declaration = transport_registry.validate(json.loads(
        (transport_registry.BUILTIN_DIR / f'{identity}.json').read_text()))
    belt = toolbelt.build(card())
    _, side = make(root / identity, belt['tools'])
    toolbelt_path = side.workspace / 'toolbelt.json'
    toolbelt_path.write_text(json.dumps(belt))
    command = broker_mcp.server_command(workspace=side.workspace, toolbelt_path=toolbelt_path,
                                        socket_path=side.socket_path)
    written = broker_mcp.client_config(declaration, config_dir=root / identity / 'config', command=command)
    if written['config'] == 'probe_required':
        assert written['fallback'] == 'ravel work call' and written['path'] is None
        return
    if identity == 'claude-cli-worker':
        assert written['argv'] == ['--mcp-config', written['path']]
        assert '--strict-mcp-config' in declaration['argv_template']
    stub = _command_from(written['config'], written)  # what the CLI would launch from its configuration
    lines = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
             {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}]
    with broker_module.serve(side):
        done = subprocess.run(stub, input='\n'.join(json.dumps(x) for x in lines) + '\n', capture_output=True,
                              text=True, env={**os.environ, 'PYTHONPATH': str(SRC)}, timeout=120)
    assert done.returncode == 0, done.stderr
    listed = json.loads(done.stdout.splitlines()[1])['result']['tools']
    assert [t['name'] for t in listed] == [t['name'] for t in belt['tools'] if t['name'] != 'submit_final']


def test_structured_output_rows_distinguish_enforced_from_validated_text():
    rows = {}
    for path in sorted(transport_registry.BUILTIN_DIR.glob('*.json')):
        declaration = json.loads(path.read_text())
        if 'worker_surface' in declaration:
            rows[declaration['id']] = declaration['worker_surface']['structured_output']
    assert rows == {'antigravity-cli-worker': 'enforced', 'claude-cli-worker': 'enforced',
                    'claude-cli-worker-apikey': 'enforced', 'claude-cli-worker-bedrock': 'enforced',
                    'claude-cli-worker-vertex': 'enforced', 'codex-cli-worker': 'enforced',
                    'codex-cli-worker-apikey': 'enforced', 'codex-cli-worker-azure': 'enforced',
                    'gemini-cli-worker': 'validated_text', 'opencode-worker': 'validated_text'}


def test_worker_surface_row_is_validated():
    declaration = json.loads((transport_registry.BUILTIN_DIR / 'gemini-cli-worker.json').read_text())
    bad = deepcopy(declaration)
    bad['worker_surface']['structured_output'] = 'enforced'  # no schema flag: cannot claim enforcement
    with pytest.raises(ValueError, match='worker_surface'):
        transport_registry.validate(bad)
    bad = deepcopy(declaration)
    bad['worker_surface']['mcp']['config'] = 'anything'
    with pytest.raises(ValueError, match='worker_surface'):
        transport_registry.validate(bad)
