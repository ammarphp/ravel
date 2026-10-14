"""Synthetic in-process transports; no live provider or scientific execution."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest


ADAPTERS = ['anthropic', 'gemini', 'chat_completions', 'responses']
SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'integer'}},
          'required': ['answer'], 'additionalProperties': False}


def wire(adapter, name, args, number=1):
    call = {'id': 'call-' + str(number), 'name': name, 'args': args}
    if adapter == 'anthropic':
        return {'type': 'message', 'role': 'assistant', 'stop_reason': 'tool_use',
                'content': [{'type': 'tool_use', 'id': call['id'], 'name': name, 'input': args}],
                'usage': {'input_tokens': 2, 'output_tokens': 1}}
    if adapter == 'gemini':
        return {'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model',
                'parts': [{'functionCall': {'id': call['id'], 'name': name, 'args': args}}]}}],
                'usageMetadata': {'promptTokenCount': 2, 'candidatesTokenCount': 1}}
    if adapter == 'responses':
        return {'status': 'completed', 'output': [{'type': 'function_call', 'call_id': call['id'],
                'name': name, 'arguments': json.dumps(args)}], 'usage': {'input_tokens': 2, 'output_tokens': 1}}
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
            'tool_calls': [{'id': call['id'], 'type': 'function', 'function': {
                'name': name, 'arguments': json.dumps(args)}}]}}],
            'usage': {'prompt_tokens': 2, 'completion_tokens': 1}}


class Sender:
    identity = {'fixture': 'script-v1'}

    def __init__(self, script):
        self.script, self.calls = script, []

    def __call__(self, body, *, timeout, max_cost_usd):
        self.calls.append(deepcopy(body))
        raw = self.script[len(self.calls) - 1]
        if isinstance(raw, BaseException):
            raise raw
        return {'body': raw, 'http_status': 200}


def setup(tmp_path, monkeypatch, script, adapter='chat_completions', text=False, **budgets):
    from ravel.transports.ravel_loop import RavelLoop
    from ravel.workflow.ravel_chat_model import RavelTransportChatModel
    from test_worker_broker import make
    broker = make(tmp_path, monkeypatch)
    effects = []
    broker.allowed_actions.add('echo')
    broker.register('echo', lambda args: effects.append(args) or {'stdout': 'observed'})
    sender = Sender(script)
    reservation = budgets.pop('cost_reservation_usd', None)
    final_schema = budgets.pop('final_schema_override', SCHEMA)
    streaming = budgets.pop('streaming', False)
    model = RavelTransportChatModel(adapter=adapter, model='synthetic-model', sender=sender,
                                   max_cost_per_turn_usd=reservation,
                                   streaming_declared=streaming, stream_enabled=streaming,
                                   text_protocol=text, request_binding={'request': 'synthetic'})
    limits = {'max_turns': 8, 'max_wall_seconds': 120, 'max_broker_calls': 8,
              'max_cost_usd': None, 'max_steps': 8, **budgets}
    loop = RavelLoop(tmp_path / 'scope', model=model, broker=broker, budgets=limits,
                     final_schema=final_schema, tools=[{'name': 'echo', 'description': 'Echo supplied data',
                     'args_schema': {'type': 'object'}}], instance={'worker': 'synthetic'})
    return loop, sender, effects, broker


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_allowed_disallowed_and_step_exhaustion_then_valid_final(tmp_path, monkeypatch, adapter):
    script = [wire(adapter, n, a, i) for i, (n, a) in enumerate([
        ('echo', {'n': 1}), ('forbidden', {}), ('echo', {'n': 2}), ('submit_final', {'answer': 7})])]
    loop, sender, effects, broker = setup(tmp_path, monkeypatch, script, adapter, max_steps=2)
    result = loop.run('perform synthetic work')
    assert result['final'] == {'answer': 7} and effects == [{'n': 1}]
    assert [r['code'] for r in result['action_receipts']] == ['ok', 'unknown_tool', 'budget_exhausted', 'ok']
    assert all(r['receipt']['sha256'] for r in result['action_receipts'])
    assert len(sender.calls) == 4
    assert loop.run('perform synthetic work')['final'] == result['final'] and len(sender.calls) == 4
    for receipt in result['turn_receipts']:
        assert receipt['request_sha256'] and receipt['response_sha256'] and receipt['http_status'] == 200
        assert receipt['provider_usage']
    assert result['framework_values_are_scientific_authority'] is False


@pytest.mark.parametrize('invalid,code', [
    ('{bad', 'malformed_json'),
    ('[{"action":"echo","args":{}},{"action":"echo","args":{}}]', 'multiple_actions'),
    ('{"action":"missing","args":{}}', 'unknown_tool'),
])
def test_text_protocol_negative_receipts(tmp_path, monkeypatch, invalid, code):
    loop, sender, effects, _ = setup(tmp_path, monkeypatch,
        [invalid, '{"action":"submit_final","args":{"answer":4}}'], text=True)
    result = loop.run('synthetic vote')
    assert result['action_receipts'][0]['code'] == code
    assert result['action_receipts'][0]['receipt']['sha256']
    assert result['steps'] == 2 and len(sender.calls) == 2 and effects == []
    assert result['final'] == {'answer': 4}


@pytest.mark.parametrize('boundary', ['model', 'tool'])
def test_crash_after_receipt_resumes_without_repeating_effect(tmp_path, monkeypatch, boundary):
    from ravel.workflow import effect_ledger
    loop, sender, effects, _ = setup(tmp_path, monkeypatch, [
        wire('chat_completions', 'echo', {}), wire('chat_completions', 'submit_final', {'answer': 1}, 2)])
    original = effect_ledger.call
    crashed = []

    def crash(*args, **kwargs):
        value = original(*args, **kwargs)
        if kwargs['path'].endswith('/' + boundary) and not crashed:
            crashed.append(True)
            raise KeyboardInterrupt('synthetic checkpoint gap')
        return value

    monkeypatch.setattr(effect_ledger, 'call', crash)
    with pytest.raises(KeyboardInterrupt):
        loop.run('synthetic task')
    monkeypatch.setattr(effect_ledger, 'call', original)
    assert loop.run('synthetic task')['final'] == {'answer': 1}
    assert len(sender.calls) == 2 and len(effects) == 1


def test_lost_stream_is_ambiguous_and_never_repeated(tmp_path, monkeypatch):
    loop, sender, effects, _ = setup(tmp_path, monkeypatch, [TimeoutError('lost after send')], streaming=True)
    result = loop.run('synthetic stream')
    assert result['status'] == 'ambiguous'
    assert result['turn_receipts'][0]['request_sha256']
    assert result['turn_receipts'][0]['response_sha256'] is None
    assert loop.run('synthetic stream')['status'] == 'ambiguous'
    assert len(sender.calls) == 1 and not effects


def test_no_provider_sdk_imports():
    root = Path(__file__).parents[2] / 'src/ravel'
    files = [root / 'transports/ravel_loop.py'] + [root / 'workflow' / name for name in
        ('ravel_chat_model.py', 'provider_tools.py', 'langchain_guard.py', 'langchain_service.py')]
    forbidden = {'anthropic', 'openai', 'google', 'litellm', 'langchain_openai', 'langchain_anthropic'}
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert not {a.name.split('.')[0] for a in node.names} & forbidden
            if isinstance(node, ast.ImportFrom):
                assert (node.module or '').split('.')[0] not in forbidden


def test_receipt_pins_stay_valid_after_gap_reuse(tmp_path, monkeypatch):
    from ravel.workflow import effect_ledger
    from ravel.workflow.execution import file_hash
    loop, sender, effects, _ = setup(tmp_path, monkeypatch, [
        wire('chat_completions', 'echo', {}), wire('chat_completions', 'submit_final', {'answer': 1}, 2)])
    result = loop.run('synthetic')
    path = loop._path(0, 'action')
    receipt = effect_ledger.latest(loop.scope_root, path)
    effect_ledger.call(loop.scope_root, graph=receipt['graph'], path=path, kind=receipt['kind'],
        identity=receipt['identity'], provisioning={}, function=lambda: pytest.fail('repeated action'))
    for action in result['action_receipts']:
        pin = action['receipt']
        assert file_hash(loop.scope_root / pin['path']) == pin['sha256']
    assert loop.run('synthetic')['final'] == {'answer': 1}


def test_completed_checkpoint_does_not_hide_edited_turn_receipt(tmp_path, monkeypatch):
    from ravel.workflow import effect_ledger
    from ravel.workflow.state_io import atomic_json
    loop, sender, _, _ = setup(tmp_path, monkeypatch, [wire('chat_completions', 'submit_final', {'answer': 1})])
    loop.run('synthetic')
    receipt = effect_ledger.latest(loop.scope_root, loop._path(0, 'model'))
    receipt['result']['http_status'] = 299
    atomic_json(loop.scope_root / 'calls' / (receipt['call_id'] + '.json'), receipt)
    with pytest.raises(ValueError, match='receipt'): loop.run('synthetic')
    assert len(sender.calls) == 1


def test_advertised_disallowed_tool_uses_broker_refusal_receipt(tmp_path, monkeypatch):
    loop, sender, effects, broker = setup(tmp_path, monkeypatch, [
        wire('chat_completions', 'echo', {}), wire('chat_completions', 'submit_final', {'answer': 1}, 2)])
    broker.allowed_actions.remove('echo')
    # Prepare a new binding reflecting the actual narrower role policy.
    from ravel.workflow.effect_ledger import digest
    loop._identity = digest(loop.identity)
    result = loop.run('synthetic')
    assert result['action_receipts'][0]['code'] == 'not_allowlisted'
    assert not effects and len(broker.verify_ledger()) == 1


@pytest.mark.parametrize('cost,reason', [(None, 'unknown_cost'), (0.25, 'max_cost_usd')])
def test_cost_ceiling_holds_unknown_or_over_limit_usage(tmp_path, monkeypatch, cost, reason):
    raw = wire('chat_completions', 'echo', {})
    if cost is not None: raw['usage']['cost_usd'] = cost
    loop, sender, effects, _ = setup(tmp_path, monkeypatch, [raw], max_cost_usd=0.2, cost_reservation_usd=0.1)
    result = loop.run('synthetic priced work')
    assert result['status'] == 'budget_exhausted' and result['stop_receipt']
    assert len(sender.calls) == 1 and not effects
    assert reason in json.loads((loop.scope_root / result['stop_receipt']['path']).read_text())['result']['reasons']


def test_invalid_final_consumes_a_turn_and_has_no_completion(tmp_path, monkeypatch):
    loop, sender, effects, _ = setup(tmp_path, monkeypatch,
        [wire('chat_completions', 'submit_final', {'answer': 'wrong'})], max_turns=1)
    result = loop.run('synthetic')
    assert result['final'] is None and result['action_receipts'][0]['code'] == 'schema_invalid'
    assert result['status'] == 'budget_exhausted' and len(sender.calls) == 1


def test_crash_during_sent_model_call_is_never_repeated(tmp_path, monkeypatch):
    loop, sender, effects, _ = setup(tmp_path, monkeypatch, [KeyboardInterrupt('synthetic sent gap')])
    with pytest.raises(KeyboardInterrupt): loop.run('synthetic')
    result = loop.run('synthetic')
    assert result['status'] == 'ambiguous' and len(sender.calls) == 1


def test_broker_action_list_maps_provider_safe_names(tmp_path, monkeypatch):
    from ravel.transports.ravel_loop import RavelLoop
    loop, sender, effects, broker = setup(tmp_path, monkeypatch, [
        wire('chat_completions', 'ws_echo', {}), wire('chat_completions', 'submit_final', {'answer': 1}, 2)])
    broker.allowed_actions.add('ws.echo')
    broker.register('ws.echo', lambda args: effects.append(args) or {})
    mapped = RavelLoop(loop.scope_root, model=loop.model, broker=broker, budgets=loop.budgets,
                       final_schema=SCHEMA, tools=None, instance={'worker': 'mapped'})
    assert mapped.run('synthetic')['final'] == {'answer': 1} and effects == [{}]


def test_substrate_builder_handoff_matches_build_context(tmp_path, monkeypatch):
    from ravel.transports.ravel_loop import build
    from ravel.workflow.graph_substrate import BuildContext, finish
    from langgraph.graph import StateGraph
    loop, _, _, _ = setup(tmp_path, monkeypatch, [])
    ctx = BuildContext(loop.scope_root, 'ravel-loop', 1, loop.instance, extras={'ravel_loop': loop})
    builder = build(ctx)
    assert isinstance(builder, StateGraph)
    assert finish(builder, 'ravel-loop').structure_sha256


def test_text_judgment_record_schema(tmp_path, monkeypatch):
    schema = {'type': 'object', 'properties': {'verdict': {'type': 'boolean'}, 'rationale': {'type': 'string'}},
              'required': ['verdict', 'rationale'], 'additionalProperties': False}
    loop, sender, effects, _ = setup(tmp_path, monkeypatch,
        ['{"action":"submit_final","args":{"verdict":true,"rationale":"Synthetic evidence checked."}}'],
        text=True, final_schema_override=schema)
    result = loop.run('Give a synthetic judgment')
    assert result['final']['verdict'] is True and len(sender.calls) == 1 and not effects


def test_unpriced_cost_capped_sender_is_refused_before_send(tmp_path, monkeypatch):
    loop, sender, effects, _ = setup(tmp_path, monkeypatch, [], max_cost_usd=0.1)
    result = loop.run('synthetic priced work')
    assert result['status'] == 'budget_exhausted' and result['stop_receipt']
    assert not sender.calls and not effects


def test_expired_provider_deadline_prevents_tool_dispatch(tmp_path, monkeypatch):
    import time
    original = Sender.__call__
    def slow(self, *args, **kwargs):
        time.sleep(1.05)  # inert sender deliberately violates its supplied deadline
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Sender, '__call__', slow)
    loop, sender, effects, _ = setup(tmp_path, monkeypatch,
        [wire('chat_completions', 'echo', {})], max_wall_seconds=1)
    result = loop.run('synthetic')
    assert result['status'] == 'budget_exhausted' and result['stop_receipt']
    assert len(sender.calls) == 1 and not effects


@pytest.mark.parametrize('boundary', ['model', 'tool'])
def test_fresh_process_resume_does_not_repeat_model_or_tool(tmp_path, boundary):
    import subprocess
    import sys
    program = r'''
import json, os, sys
from pathlib import Path
from ravel.transports.ravel_loop import RavelLoop
from ravel.workflow.ravel_chat_model import RavelTransportChatModel
from ravel.workflow.broker import Broker, work_root
from ravel.workflow import effect_ledger as ledger
root, mode, boundary = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
os.environ['RAVEL_STATE_DIR'] = str(root / 'state')
os.environ['RAVEL_WORK_ROOT'] = str(root / 'work')
run = root / 'run'; run.mkdir(exist_ok=True)
workspace = work_root(run) / 'synthetic' / '1'
workspace.mkdir(parents=True, exist_ok=True)
for name in ('inputs', 'outputs', 'scratch', 'calls'): (workspace / name).mkdir(exist_ok=True)
def count(path): return int(path.read_text()) if path.exists() else 0
class Remote:
    identity = {'fixture': 'durable-script'}
    def __call__(self, body, *, timeout, max_cost_usd):
        path = root / 'model-count'; number = count(path); path.write_text(str(number + 1))
        name, args = ('echo', {}) if number == 0 else ('submit_final', {'answer': 7})
        raw = {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
            'tool_calls': [{'id': 'call-' + str(number), 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps(args)}}]}}], 'usage': {'prompt_tokens': 2, 'completion_tokens': 1}}
        return {'body': raw, 'http_status': 200}
broker = Broker(run, workspace, node_id='synthetic', attempt=1, allowed_actions=['echo'], max_calls=4)
def echo(args):
    path = root / 'tool-count'; path.write_text(str(count(path) + 1)); return {}
broker.register('echo', echo)
model = RavelTransportChatModel(adapter='chat_completions', model='synthetic', sender=Remote(),
                                request_binding={'request': 'synthetic'})
schema = {'type': 'object', 'properties': {'answer': {'type': 'integer'}}, 'required': ['answer'], 'additionalProperties': False}
loop = RavelLoop(root / 'scope', model=model, broker=broker, final_schema=schema,
    tools=[{'name': 'echo', 'description': 'Synthetic echo', 'args_schema': {'type': 'object'}}],
    budgets={'max_turns': 4, 'max_wall_seconds': 120, 'max_broker_calls': 4, 'max_cost_usd': None},
    instance={'worker': 'synthetic'})
if mode == 'crash':
    original = ledger.call
    def crash(*args, **kwargs):
        value = original(*args, **kwargs)
        if kwargs['path'].endswith('/' + boundary): os._exit(23)
        return value
    ledger.call = crash
result = loop.run('synthetic')
assert result['final'] == {'answer': 7} and result['status'] == 'completed'
assert count(root / 'model-count') == 2 and count(root / 'tool-count') == 1
'''
    for mode, expected in [('crash', 23), ('resume', 0)]:
        result = subprocess.run([sys.executable, '-B', '-c', program, str(tmp_path), mode, boundary],
                                timeout=20, capture_output=True, text=True)
        assert result.returncode == expected, result.stderr


def test_loop_workflow_doc_has_no_internal_work_package_labels():
    import re
    root = Path(__file__).parents[2]
    for doc in ('docs/workflow/reference/research-orchestration.md',
                'src/ravel/data/workflow/docs/workflow/reference/research-orchestration.md'):
        text = (root / doc).read_text()
        section = text.split('## Native model agent loop', 1)[1].split('\n## ', 1)[0]
        assert not re.search(r'\b(?:LG|AL|M)-\d', section)


def test_loop_route_serves_blind_roles_only_through_registry_admission():
    from ravel.workflow import transport_registry as registry
    loops = [d for d in registry.all_declarations() if d['transport_kind'] == 'ravel-loop']
    assert loops and all(registry.executor_available(d) for d in loops)
    for document in loops:
        qualified = document['qualification']['status'] == 'live_qualified' and registry.sandbox_available()
        assert registry.blind_admissible(document) is (qualified and document['capabilities']['blind_capable'])
