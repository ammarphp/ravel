"""Full MCP evidence from a single governed query; fictional sources only."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import broker as core, broker_mcp, effect_ledger, literature_mcp
from ravel.workflow import literature_serving as serving, toolbelt, tool_gate
from test_literature_serving import args, base, bind, install, make_run, TOOL_ROW



def world(base, *, large=False):
    options = {}
    if large:
        options['papers'] = {'elm': {'identifiers': {'document': ['paper:elm']},
                                    'lines': ['Elm rate is 3.5 units in calm air. ' + 'context ' * 1400]}}
    installed = install(base, **options)
    broker = bind(make_run(base), installed.serving)
    return installed, broker


def rpc(server, arguments):
    return server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                          'params': {'name': 'literature_search', 'arguments': arguments}})['result']


@pytest.mark.parametrize('large', [False, True])
def test_mcp_projects_complete_exact_bytes_after_only_one_governed_query(base, large):
    installed, broker = world(base, large=large)
    server = broker_mcp.Server(serving.tools(TOOL_ROW), broker.call,
                              literature_output=literature_mcp.projector(broker.workspace))
    result = rpc(server, args('search', top_k=1))
    reply = result['structuredContent']
    raw = serving.load(broker.rundir, reply)
    assert result['isError'] is False
    assert result['content'][-1]['text'].encode() == raw
    assert json.loads(result['content'][0]['text']) == reply
    assert installed.provider.calls == ['search'] and len(broker.verify_ledger()) == 1
    if large:
        assert len(raw) > 8192  # The broker stdout tail is not the evidence transport.


@pytest.mark.parametrize('damage', ['changed', 'leaf-link', 'directory-link'])
def test_changed_or_redirected_outputs_are_withheld_with_the_original_receipt(base, damage):
    installed, broker = world(base)
    reply = serving.call(broker, 'search', args('search'))
    output = core.locate(broker.rundir, reply['outputs'][0]['path'])
    if damage == 'changed':
        output.write_text('modified')
    elif damage == 'leaf-link':
        saved = output.with_suffix('.saved')
        output.rename(saved)
        output.symlink_to(saved)
    else:
        directory = output.parent
        saved = directory.with_name('saved-literature')
        directory.rename(saved)
        directory.symlink_to(saved, target_is_directory=True)
    result = literature_mcp.projector(broker.workspace)(reply, 'search')
    assert result['isError'] is True
    assert json.loads(result['content'][0]['text']) == {
        'code': 'literature_output_unavailable', 'receipt_id': reply['receipt_id']}
    assert installed.provider.calls == ['search'] and len(broker.verify_ledger()) == 1


@pytest.mark.parametrize('damage', ['digest', 'traversal', 'absolute', 'prefix', 'count', 'shape', 'operation'])
def test_bad_output_descriptors_never_project_evidence(base, damage):
    _, broker = world(base)
    reply = deepcopy(serving.call(broker, 'search', args('search')))
    operation = 'search'
    if damage == 'digest':
        reply['outputs'][0]['sha256'] = 'not-a-digest'
    elif damage == 'traversal':
        reply['outputs'][0]['path'] = '../' + reply['outputs'][0]['path']
    elif damage == 'absolute':
        reply['outputs'][0]['path'] = '/' + reply['outputs'][0]['path']
    elif damage == 'prefix':
        pin = reply['outputs'][0]
        pin['path'] = 'unrelated/outputs/literature/' + pin['sha256'] + '.json'
    elif damage == 'count':
        reply['outputs'].append(deepcopy(reply['outputs'][0]))
    elif damage == 'shape':
        reply['outputs'][0] = None
    else:
        operation = 'list_papers'
    result = literature_mcp.projector(broker.workspace)(reply, operation)
    assert result['isError'] is True
    assert all('results' not in row['text'] for row in result['content'])


def test_mcp_projection_failure_keeps_the_receipted_reply_and_reports_error(base):
    _, broker = world(base)
    def call(request):
        reply = broker.call(request)
        core.locate(broker.rundir, reply['outputs'][0]['path']).write_text('modified')
        return reply
    server = broker_mcp.Server(serving.tools(TOOL_ROW), call,
                              literature_output=literature_mcp.projector(broker.workspace))
    result = rpc(server, args('search'))
    assert result['isError'] is True
    assert result['structuredContent'] == broker.verify_ledger()[-1]['reply']
    assert json.loads(result['content'][-1]['text'])['code'] == 'literature_output_unavailable'


def test_stdio_bootstrap_installs_the_projector(base, monkeypatch):
    installed, broker = world(base)
    tools = serving.tools(TOOL_ROW)
    document = {'kind': 'toolbelt', 'card_id': 'fictional.reader', 'tools': tools, 'omitted': []}
    document['manifest_sha256'] = toolbelt.manifest_sha256(document)
    path = base / 'tools.json'
    path.write_text(json.dumps(document))
    observed = []
    monkeypatch.setattr(core, 'socket_call', lambda socket, request: broker.call(request))
    monkeypatch.setattr(broker_mcp, 'serve_stdio', lambda server, stdin, stdout:
                        observed.append(rpc(server, args('search'))))
    assert broker_mcp.main(['--workspace', str(broker.workspace), '--toolbelt', str(path),
                            '--socket', str(base / 'inert.sock')]) == 0
    assert observed[0]['isError'] is False
    assert observed[0]['content'][-1]['text'].encode() == serving.load(broker.rundir,
                                                                     observed[0]['structuredContent'])
    assert installed.provider.calls == ['search']


def test_denials_add_no_evidence(base):
    _, broker = world(base)
    result = literature_mcp.projector(broker.workspace)({'status': 'refused', 'outputs': []}, 'search')
    assert result == {'content': [], 'isError': True}


def test_trusted_embedding_can_supply_an_exact_nonstandard_logical_mapping(base):
    _, broker = world(base)
    reply = deepcopy(serving.call(broker, 'search', args('search')))
    raw = serving.load(broker.rundir, reply)
    pin = reply['outputs'][0]
    pin['path'] = 'custom/worker/outputs/literature/' + pin['sha256'] + '.json'
    assert literature_mcp.projector(broker.workspace)(reply, 'search')['isError'] is True
    projected = literature_mcp.projector(broker.workspace, logical_workspace='custom/worker')(reply, 'search')
    assert projected == {'content': [{'type': 'text', 'text': raw.decode()}], 'isError': False}


@pytest.mark.parametrize('large', [False, True])
def test_in_graph_messages_project_exact_evidence_and_replay_only_the_original_call(base, large):
    installed, broker = world(base, large=large)
    tools = serving.tools(TOOL_ROW)
    prefix = effect_ledger.path('synthetic.presentation', {'case': 'fictional'}, None, {'turn': 1})
    gate = tool_gate.ravel_gate(tools, scope_root=base / 'scope',
                                graph={'id': 'synthetic.presentation', 'version': 1}, prefix=prefix,
                                broker_call=broker.call, rundir=broker.rundir)
    request = {'tool_call': {'name': 'literature_search', 'args': args('search', top_k=1), 'id': 'q1'}}
    reply = gate.call(request)
    message = gate.message(request, reply)
    content = message['content'] if isinstance(message, dict) else message.content
    assert content[-1]['text'].encode() == serving.load(broker.rundir, reply)
    assert json.loads(content[0]['text']) == reply
    assert gate.call(request) == reply
    assert installed.provider.calls == ['search'] and len(broker.verify_ledger()) == 1
