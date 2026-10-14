"""Synthetic provider envelopes and guard refusals."""
from contextvars import ContextVar
from copy import deepcopy
import pytest

from test_ravel_loop import ADAPTERS, Sender, setup, wire


@pytest.mark.parametrize('flag', ['LANGCHAIN_TRACING', 'LANGCHAIN_HANDLER', 'LANGCHAIN_TRACING_V2', 'LANGSMITH_TRACING'])
def test_model_ambient_tracing_refused(tmp_path, monkeypatch, flag):
    from ravel.workflow.langchain_guard import GuardError
    loop, sender, _, _ = setup(tmp_path, monkeypatch, [])
    monkeypatch.setenv(flag, 'true')
    with pytest.raises(GuardError): loop.model.turn({'messages': [], 'tools': [], 'tool_choice': 'auto', 'stream': False})
    assert not sender.calls


@pytest.mark.parametrize('setting', ['debug', 'verbose', 'hook', 'callback'])
def test_model_ambient_configuration_refused(tmp_path, monkeypatch, setting):
    from langchain_core import globals as settings
    from langchain_core.callbacks.base import BaseCallbackHandler
    from langchain_core.tracers import context as tracing
    from ravel.workflow.langchain_guard import GuardError
    loop, sender, _, _ = setup(tmp_path, monkeypatch, [])
    callbacks = []
    if setting in {'debug', 'verbose'}: monkeypatch.setattr(settings, '_' + setting, True)
    if setting == 'hook':
        monkeypatch.setattr(tracing, '_configure_hooks', [(ContextVar('synthetic-hook', default=object()), True, None, None)])
    if setting == 'callback': callbacks = [BaseCallbackHandler()]
    with pytest.raises(GuardError):
        loop.model.turn({'messages': [], 'tools': [], 'tool_choice': 'auto', 'stream': False}, callbacks=callbacks)
    assert not sender.calls


def test_model_identity_mutation_after_send_refused(tmp_path, monkeypatch):
    from ravel.workflow.langchain_guard import GuardError
    loop, sender, _, _ = setup(tmp_path, monkeypatch, [wire('chat_completions', 'submit_final', {'answer': 1})])
    original = sender.__class__.__call__
    def mutate(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        self.identity = {'fixture': 'changed'}
        return value
    monkeypatch.setattr(Sender, '__call__', mutate)
    with pytest.raises(GuardError): loop.model.turn({'messages': [], 'tools': [], 'tool_choice': 'auto', 'stream': False})
    assert len(sender.calls) == 1


@pytest.mark.parametrize('method', ['with_retry', 'with_fallbacks', 'batch', 'stream'])
def test_model_effect_multiplication_refused(tmp_path, monkeypatch, method):
    from ravel.workflow.langchain_guard import GuardError
    loop, sender, _, _ = setup(tmp_path, monkeypatch, [])
    with pytest.raises(GuardError): getattr(loop.model, method)([])
    assert not sender.calls


@pytest.mark.parametrize('adapter', ADAPTERS)
def test_multi_turn_wire_contains_call_and_matched_result(adapter):
    from ravel.workflow.provider_tools import render, parse
    message = parse(adapter, wire(adapter, 'echo', {'x': 3}))
    envelope = {'messages': [{'role': 'system', 'content': 'synthetic instruction'},
        {'role': 'user', 'content': 'synthetic request'}, message,
        {'role': 'tool', 'tool_call_id': 'call-1', 'name': 'echo', 'content': '{"status":"ok"}'}],
        'tools': [{'name': 'echo', 'description': 'Synthetic echo', 'args_schema': {'type': 'object'}}],
        'tool_choice': 'auto', 'stream': False}
    value = render(adapter, envelope, model='synthetic', max_output_tokens=16)
    assert 'echo' in str(value) and 'call-1' in str(value) and 'status' in str(value)
    if adapter == 'responses': assert any(x.get('type') == 'function_call_output' for x in value['input'])
    if adapter == 'anthropic': assert value['messages'][-1]['content'][0]['type'] == 'tool_result'
    if adapter == 'gemini': assert 'functionResponse' in value['contents'][-1]['parts'][0]


def test_undeclared_stream_refused(tmp_path, monkeypatch):
    from ravel.workflow.langchain_guard import GuardError
    loop, sender, _, _ = setup(tmp_path, monkeypatch, [])
    with pytest.raises(GuardError): loop.model.turn({'messages': [], 'tools': [], 'tool_choice': 'auto', 'stream': True})
    assert not sender.calls


def test_turn_budget_stops_with_receipt(tmp_path, monkeypatch):
    loop, sender, effects, _ = setup(tmp_path, monkeypatch,
        [wire('chat_completions', 'echo', {})], max_turns=1)
    result = loop.run('synthetic work')
    assert result['status'] == 'budget_exhausted' and result['stop_receipt']['sha256']
    assert len(sender.calls) == 1 and len(effects) == 1


def test_text_producer_tool_round_trip(tmp_path, monkeypatch):
    loop, sender, effects, _ = setup(tmp_path, monkeypatch,
        ['{"action":"echo","args":{"x":1}}', '{"action":"submit_final","args":{"answer":2}}'], text=True)
    assert loop.run('synthetic production')['final'] == {'answer': 2}
    assert effects == [{'x': 1}] and len(sender.calls) == 2


def test_public_invoke_refuses_callback_before_it_observes_prompt(tmp_path, monkeypatch):
    from langchain_core.callbacks.base import BaseCallbackHandler
    from ravel.workflow.langchain_guard import GuardError
    observed = []
    class Forbidden(BaseCallbackHandler):
        def on_chat_model_start(self, *args, **kwargs): observed.append(True)
    loop, sender, _, _ = setup(tmp_path, monkeypatch, [])
    with pytest.raises(GuardError): loop.model.invoke('synthetic', config={'callbacks': [Forbidden()]})
    assert not sender.calls and not observed


def test_public_chat_adapter_preserves_tool_call(tmp_path, monkeypatch):
    loop, sender, _, _ = setup(tmp_path, monkeypatch, [wire('chat_completions', 'echo', {'x': 3})])
    result = loop.model.invoke('synthetic')
    assert result.tool_calls[0]['name'] == 'echo' and result.tool_calls[0]['args'] == {'x': 3}
    assert result.response_metadata['http_status'] == 200 and len(sender.calls) == 1
