"""Inert HTTP loop workers on the ordinary broker, custody and qualification path."""
from copy import deepcopy
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ravel.controller.step import seats
from ravel.workflow import agent_worker, broker, model_catalogue as mc, project_instructions, sandbox
from ravel.workflow import transport_registry as tr
from ravel.workflow.transports import cli_worker, ravel_loop
from test_cli_worker_adapter import cli, real_sandbox_or_skip  # noqa: F401


@pytest.fixture
def operator_home(monkeypatch):
    from ravel.workflow.approval_authority import AGENT_MARKERS
    from ravel.controller.authority import issuer, operator
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(issuer, 'home', lambda: operator.controller_home() / 'issuer')
    return operator.controller_home()


def prepared(root, monkeypatch, *, transport='ravel-loop-local', model='qwen-fixture', cap=None, pin=False,
             one_call=False):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    run = root / 'run'
    if pin:
        document = root / 'project-policy.md'
        document.write_text('Use the supplied definitions exactly.\n')
        project_instructions.declare(run, document)
    source = run / cli_worker.CONFORMANCE_INPUT
    source.write_text('{"nonce":"fictional"}')
    card = cli_worker.conformance_card()
    if one_call:
        card['requires']['tools'] = 'none'
        card['tools']['ravel_actions'] = []
        card['stop']['max_broker_calls'] = 0
    spec = cli_worker.conformance_spec(card)
    if one_call:
        spec['declared_outputs'] = []
        spec['budgets'].update(max_turns=1, max_broker_calls=1)
    spec['transport_preference'] = [transport]
    spec['inputs'][0]['pin'] = {'path': cli_worker.CONFORMANCE_INPUT, 'sha256': broker.sha(source)}
    spec['budgets']['max_cost_usd'] = cap
    ws = agent_worker.materialize(run, spec)
    selected = {'transport_id': transport, 'model': model, 'effort': None}
    descriptor = ravel_loop.prepare_launch(run, spec, ws, selection=selected, card=card,
                                           atlas=cli_worker._conformance_atlas())
    return spec, ws, descriptor


def test_loop_launch_carries_instruction_pin_and_read_only_configuration(cli, monkeypatch):
    spec, ws, descriptor = prepared(cli, monkeypatch, pin=True)
    transport = descriptor['transport']
    assert agent_worker._descriptor_adapter(descriptor) is ravel_loop
    assert agent_worker._declared_document_refusal(cli / 'run', descriptor, ws) is None
    prompt = Path(transport['stdin']['path']).read_text()
    assert prompt.index('Use the supplied definitions exactly.') < prompt.index('You are the RAVEL role')
    assert project_instructions.record_problem(transport['project_instructions'],
                                               project_instructions.for_run(cli / 'run')) is None
    config = Path(transport['config']['path'])
    assert config.stat().st_mode & 0o222 == 0
    assert transport['network'] == {'kind': 'loopback', 'host': '127.0.0.1', 'port': 11434}
    config.chmod(0o600)
    config.write_text('{}')
    with pytest.raises(ValueError, match='configuration changed'):
        agent_worker._cli_launch(descriptor, ws)


@pytest.mark.parametrize('module', ['ravel.workflow.model_catalogue',
                                   'ravel.workflow.transports.provider_usage',
                                   'ravel.workflow.toolbelt', 'ravel.workflow.agent_worker'])
def test_loop_qualification_identity_includes_enforcing_dependencies(monkeypatch, module):
    document = tr.load('ravel-loop-local')
    before = ravel_loop.current_probe(document)[0]
    assert module in before['sources']
    fingerprint = tr.file_sha256
    import importlib
    changed = Path(importlib.import_module(module).__file__)
    monkeypatch.setattr(tr, 'file_sha256', lambda path: '0' * 64 if Path(path) == changed else fingerprint(path))
    after = ravel_loop.current_probe(document)[0]
    assert after['executable_sha256'] != before['executable_sha256']


def test_api_loop_refuses_before_launch_without_a_sufficient_ceiling(cli, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fictional-not-a-key')
    model = 'claude-sonnet-5-5'
    bound = mc.call_bound(model)
    with pytest.raises(cli_worker.LaunchRefused) as missing:
        prepared(cli, monkeypatch, transport='ravel-loop-anthropic', model=model)
    assert missing.value.missing == ['cost_budget']
    # Refusals do not reserve or start any process; a fresh attempt workspace is needed.
    other = cli / 'next'
    (other / 'run/inputs').mkdir(parents=True)
    with pytest.raises(cli_worker.LaunchRefused) as insufficient:
        prepared(other, monkeypatch, transport='ravel-loop-anthropic', model=model,
                 cap=bound['cost_usd'] / 2)
    assert insufficient.value.missing == ['cost_budget']
    assert 'context-full call reserves' in str(insufficient.value)
    assert not agent_worker.processes(cli / 'run')


def test_one_call_role_gets_an_empty_toolbelt():
    card = cli_worker.conformance_card()
    card['requires']['tools'] = 'none'
    card['tools']['ravel_actions'] = []
    card['stop'] = {'evidence_budget': 0, 'max_broker_calls': 0}
    belt = cli_worker.toolbelt_for(card, tr.load('ravel-loop-local'), False,
                                   atlas=cli_worker._conformance_atlas())
    assert all(t['executes_through']['action'] is None for t in belt['tools'])
    assert {t['name'] for t in belt['tools']} == {'submit_final'}


def test_worker_loop_runs_one_call_with_a_checkpoint_and_no_broker_effect(cli, monkeypatch):
    from ravel.transports import ravel_loop_worker as executable
    _, ws, descriptor = prepared(cli, monkeypatch, one_call=True)
    belt = json.loads((ws / 'inputs/toolbelt.json').read_text())
    assert {t['name'] for t in belt['tools']} == {'submit_final'}

    class Sender:
        identity = {'kind': 'inert'}

        def __init__(self, config):
            pass

        def __call__(self, body, **kwargs):
            return {'http_status': 200, 'body': {'model': 'qwen-fixture',
                'usage': {'prompt_tokens': 20, 'completion_tokens': 7,
                          'prompt_tokens_details': {'cached_tokens': 5}},
                'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                    'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {
                        'name': 'submit_final', 'arguments': json.dumps({'completed': True, 'summary': 'done'})}}]}}]}}

    monkeypatch.setattr(executable, 'Sender', Sender)
    from ravel.workflow import gate_wiring
    from ravel.workflow.transports import loop_control
    gate_wiring.initialize_steering(cli / 'run', route='transport-qualification')

    class InertBroker:
        socket_path = cli / 'admission.sock'

        def call(self, request):
            pytest.fail('one-call worker attempted a broker tool effect')

    with broker.serve(InertBroker(), node_admission=loop_control.supervisor_admission(cli / 'run', 'one-call', 1)):
        envelope = executable.run(ws, descriptor['transport']['config']['path'],
                                  InertBroker.socket_path, 'supplied prompt')
    assert envelope['status'] == 'completed' and envelope['num_turns'] == 1
    assert envelope['final']['completed'] and envelope['broker_calls'] == 0
    assert list((ws / 'scratch/loop').rglob('*.sqlite*'))
    records = [row['record'] for row in broker.ledger(cli / 'run', 'worker-node-admissions')]
    assert {row['phase'] for row in records} == {'admitted', 'ended'}
    assert all(row['node_id'] == 'one-call' and row['attempt'] == 1 for row in records)


def test_supervisor_node_admission_obeys_parent_pause_and_finite_budget(cli):
    from ravel.workflow import gate_wiring
    from ravel.workflow.transports import loop_control
    run = cli / 'run'
    gate_wiring.initialize_steering(run, route='transport-qualification')
    factory = loop_control.supervisor_admission(run, 'original-parent', 1, max_nodes=1)
    with factory('guard'):
        pass
    with pytest.raises(ValueError, match='budget exhausted'):
        with factory('model'):
            pytest.fail('exhausted admission executed')
    gate_wiring.record_steering(run, 'Pause work now.', effect='pause')
    factory = loop_control.supervisor_admission(run, 'original-parent', 1)
    with pytest.raises(gate_wiring.SteeringRefused):
        with factory('model'):
            pytest.fail('paused admission executed')


@pytest.mark.parametrize('transport', ['ravel-loop-local', 'ravel-loop-gemini', 'ravel-loop-anthropic'])
def test_loop_adapters_are_wired_without_a_split_gate(monkeypatch, transport):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    assert 'ravel-loop' in seats.wired_kinds()
    assert seats.seat_problem(tr.load(transport)) is None


def test_local_network_grant_is_port_bound_and_rejects_other_hosts(monkeypatch, tmp_path):
    network = {'kind': 'loopback', 'host': '127.0.0.1', 'port': 11434}
    assert sandbox.network_port(network) == 11434
    assert sandbox.egress(network, backend='macos') == 'tcp-11434'
    with pytest.raises(ValueError, match='unknown sandbox network'):
        sandbox.network_port({**network, 'host': 'example.invalid'})
    monkeypatch.setattr(sandbox, 'linux_port_rules', lambda: False)
    with pytest.raises(sandbox.SandboxUnavailable, match='port_filter'):
        sandbox.linux_command(tmp_path, ['/bin/true'], network=network)


def test_model_identity_accepts_dated_builds_but_refuses_sibling_models():
    assert seats.model_matches('fictional-model', 'fictional-model-20261019')
    assert not seats.model_matches('fictional-model', 'fictional-model-pro')
    assert not seats.model_matches('fictional-model', 'fictional-model-9')
    assert not seats.model_matches('claude-sonnet-5', 'claude-sonnet-5-5')


def test_mixed_or_missing_turn_model_never_prices_whole_session(cli, monkeypatch):
    spec, ws, descriptor = prepared(cli, monkeypatch)
    turns = [{'model': 'claude-sonnet-5-5', 'usage': {'prompt_tokens': 20, 'completion_tokens': 7,
               'prompt_tokens_details': {'cached_tokens': 5}}},
             {'model': None, 'usage': {'prompt_tokens': 20, 'completion_tokens': 7,
               'prompt_tokens_details': {'cached_tokens': 5}}}]
    envelope = {'type': 'ravel-loop-result', 'schema_version': 1, 'status': 'completed',
                'adapter': 'chat_completions', 'session_id': descriptor['transport']['session_id'],
                'num_turns': 2, 'turns': turns, 'final': {'completed': True, 'summary': 'fictional'}}
    path = agent_worker.capture_path(cli / 'run', spec['node_id'], spec['attempt'], 'stdout')
    path.write_text(json.dumps(envelope))
    result = ravel_loop.observe(cli / 'run', descriptor, ws, spec,
                                {'exit_status': 0, 'isolation': {'user_configuration_loaded': False,
                                                               'evidence': {'confirmed': True}}})
    assert result['model']['observed'] is None
    assert result['usage']['reported'] and result['usage']['input_tokens'] == 40
    assert result['usage']['cost_usd'] is None


@pytest.mark.parametrize('served,accepted', [('fictional-model-20261019', True), ('fictional-model-pro', False)])
def test_pinned_tariff_prices_only_a_matching_model_and_stops_unknown_cost(cli, served, accepted):
    from ravel.transports.ravel_loop import RavelLoop
    from ravel.workflow.ravel_chat_model import RavelTransportChatModel

    class Sender:
        identity = {'kind': 'inert-priced-response'}
        calls = 0

        def __call__(self, body, **kwargs):
            self.calls += 1
            return {'http_status': 200, 'body': {'model': served,
                'usage': {'prompt_tokens': 20, 'completion_tokens': 7,
                          'prompt_tokens_details': {'cached_tokens': 5}},
                'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                    'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {
                        'name': 'submit_final', 'arguments': json.dumps({'completed': True})}}]}}]}}

    class NoTools:
        node_id, attempt, allowed_actions = 'priced-node', 1, set()

    sender = Sender()
    model = RavelTransportChatModel(adapter='chat_completions', model='fictional-model', sender=sender,
        request_binding={'kind': 'fictional'}, max_cost_per_turn_usd=0.01,
        tariff={'prices_per_million': {'input': 2.0, 'cache_write': 2.5, 'cache_read': 0.5, 'output': 5.0}})
    loop = RavelLoop(cli / 'priced-scope', model=model, broker=NoTools(), tools=[],
        budgets={'max_turns': 3, 'max_wall_seconds': 60, 'max_broker_calls': 1, 'max_cost_usd': 0.02},
        final_schema={'type': 'object', 'required': ['completed'], 'properties': {'completed': {'const': True}}},
        instance={'kind': 'fictional-price'})
    result = loop.run('Use the supplied task.')
    assert sender.calls == 1
    if accepted:
        assert result['status'] == 'completed'
        assert result['turn_receipts'][0]['usage']['cost_usd'] == pytest.approx(0.0000675)
    else:
        assert result['status'] == 'budget_exhausted' and result['final'] is None
        assert result['turn_receipts'][0]['usage']['cost_usd'] is None


@pytest.mark.parametrize('adapter', ['chat_completions', 'responses', 'anthropic', 'gemini'])
def test_live_qualification_path_with_inert_local_http_and_broker(cli, monkeypatch, adapter, operator_home):
    real_sandbox_or_skip(cli)
    if sandbox.available() == 'linux' and not sandbox.linux_port_rules():
        pytest.skip('sandbox-blocked: local endpoint requires a TCP port filter')
    observed = []
    run = cli / 'qualification'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            observed.append(body)
            n = len(observed)
            if n == 1:
                name, args = 'ws_read', {'path': cli_worker.CONFORMANCE_INPUT}
            elif n == 2:
                nonce = json.loads((run / cli_worker.CONFORMANCE_INPUT).read_text())['nonce']
                name, args = 'ws_write', {'path': cli_worker.CONFORMANCE_OUTPUT, 'content': nonce}
            elif n == 3:
                definitions = (body['tools'][0]['functionDeclarations'] if adapter == 'gemini'
                               else body['tools'])
                names = [(tool['function'] if adapter == 'chat_completions' else tool)['name']
                         for tool in definitions]
                names = [name for name in names if name != 'submit_final']
                name, args = 'ws_write', {'path': cli_worker.SURFACE_OUTPUT, 'content': '\n'.join(names)}
            else:
                name, args = 'submit_final', {'completed': True, 'summary': 'fictional conformance'}
            if adapter == 'anthropic':
                reply = {'model': 'qwen-fixture', 'role': 'assistant', 'stop_reason': 'tool_use',
                         'content': [{'type': 'tool_use', 'id': f'c{n}', 'name': name, 'input': args}],
                         'usage': {'input_tokens': 15, 'cache_read_input_tokens': 5,
                                   'cache_creation_input_tokens': 0, 'output_tokens': 7}}
            elif adapter == 'gemini':
                reply = {'modelVersion': 'qwen-fixture', 'candidates': [{'finishReason': 'STOP',
                         'content': {'role': 'model', 'parts': [{'functionCall': {
                             'id': f'c{n}', 'name': name, 'args': args}}]}}],
                         'usageMetadata': {'promptTokenCount': 20, 'cachedContentTokenCount': 5,
                                           'candidatesTokenCount': 5, 'thoughtsTokenCount': 2}}
            elif adapter == 'responses':
                reply = {'model': 'qwen-fixture', 'status': 'completed',
                         'output': [{'type': 'function_call', 'call_id': f'c{n}', 'name': name,
                                     'arguments': json.dumps(args)}],
                         'usage': {'input_tokens': 20, 'output_tokens': 7,
                                   'input_tokens_details': {'cached_tokens': 5}}}
            else:
                reply = {'model': 'qwen-fixture', 'choices': [{'finish_reason': 'tool_calls',
                    'message': {'role': 'assistant', 'tool_calls': [{'id': f'c{n}', 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(args)}}]}}],
                    'usage': {'prompt_tokens': 20, 'completion_tokens': 7,
                              'prompt_tokens_details': {'cached_tokens': 5}}}
            raw = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    document = deepcopy(tr.load('ravel-loop-local'))
    identity = 'fixture-loop-' + adapter.replace('_', '-')
    suffix = {'chat_completions': '/v1/chat/completions', 'responses': '/v1/responses',
              'anthropic': '/v1/messages', 'gemini': '/v1beta/models/{model}:generateContent'}[adapter]
    document.update(id=identity, endpoint=f'http://127.0.0.1:{server.server_port}' + suffix)
    routes = cli / 'inert-routes'
    routes.mkdir()
    (routes / (identity + '.json')).write_text(json.dumps(document))
    # Install the inert declaration in the fixture's trusted builtin directory;
    # user declarations retain their separate isolation and blind-role ceiling.
    monkeypatch.setattr(tr, 'BUILTIN_DIR', routes)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            record = cli_worker.qualify(identity, rundir=run, model='qwen-fixture')
        except cli_worker.QualificationFailed as exc:
            captures = {kind: agent_worker.capture_path(run, 'qualify.conformance', 1, kind).read_text()
                        for kind in ('stdout', 'stderr')}
            ws = agent_worker.workspace(run, 'qualify.conformance', 1)
            errors = []
            from ravel.workflow import graph_substrate
            with graph_substrate.saver(ws / 'scratch/loop') as saver:
                last = next(saver.list(None, limit=1), None)
                if last is not None:
                    errors.append({'failures': last.checkpoint.get('channel_values', {}).get('failures')})
            for path in (ws / 'scratch/loop').rglob('*.json'):
                value = json.loads(path.read_text())
                if isinstance(value, dict) and value.get('status') in ('failed', 'ambiguous', 'refused'):
                    errors.append({'file': path.name, 'value': value})
            pytest.fail(json.dumps({'receipt': exc.receipt, 'captures': captures,
                                    'observed_http_calls': len(observed), 'errors': errors}, default=str))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert len(observed) == 4
    assert all(step['passed'] for step in record['steps'])
    receipt = json.loads(Path(record['receipt']['path']).read_text())
    assert receipt['status'] == 'ok' and receipt['attestation'] == 'transport_attested'
    assert receipt['model']['observed'] == 'qwen-fixture'
    assert receipt['usage']['input_tokens'] == 80 and receipt['usage']['output_tokens'] == 28
    assert receipt['usage']['turns'] == 4
    assert receipt['transport']['observation']['provider_usage']['usage']['cache_read_input_tokens'] == 20
    assert len(receipt['credited_outputs']) == 2
    assert record['probe_sha256'] == tr.digest(ravel_loop.current_probe(tr.load(identity))[0])
    from ravel.controller import entry
    from ravel.controller.authority import operator, qualifications
    operator.init(mode='autonomous')
    retained = qualifications.record(record)
    store = entry.start(b'Calculate a fictional observable.', channel='terminal', rundir=cli / 'ordinary-run')
    [adopted] = [row['record'] for row in store.scan(qualifications.ADOPTION)]
    assert adopted['status'] == 'adopted' and adopted['record_sha256'] == retained['record_sha256']
    assert tr.store_qualifications(store) == {tr.digest(record): record}
    card = cli_worker.conformance_card()
    card['requires']['blind'] = True
    prefs = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {card['family']: [identity]},
             'tier_models': {'judgment': {identity: 'qwen-fixture'}}}
    from ravel.controller.step.services import StepHold
    try:
        selected = seats.select(card, prefs, store=store)
    except StepHold as exc:
        pytest.fail(json.dumps(exc.evidence))
    assert selected['transport_id'] == identity and selected['model'] == 'qwen-fixture'
