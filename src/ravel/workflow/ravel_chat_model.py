"""LangChain chat adapter over an explicit SDK-free transport sender.

The sender contract is ``(body, timeout=seconds, max_cost_usd=cap) ->
{body, http_status}``. A declared streaming sender assembles one complete result;
an exception after sending remains ambiguous in the enclosing effect ledger.
There is no credential discovery, implicit retry, fallback or truncation.
"""
from copy import deepcopy
import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, PrivateAttr

from . import provider_tools
from .effect_ledger import digest
from .langchain_guard import GuardError, SingleEffect, guarded


class PreDispatchRefusal(GuardError):
    not_dispatched = True


class RavelTransportChatModel(SingleEffect, BaseChatModel):
    cache: Any = False
    adapter: str
    model: str
    sender: Any = Field(exclude=True)
    request_binding: dict
    text_protocol: bool = False
    streaming_declared: bool = False
    stream_enabled: bool = False
    max_output_tokens: int = 1024
    max_context_bytes: int = 1_000_000
    max_cost_per_turn_usd: float | None = None
    token_limit_field: str = 'max_completion_tokens'
    tools: list[dict] = Field(default_factory=list)
    _pin: str = PrivateAttr()

    def model_post_init(self, context):
        if self.adapter not in provider_tools.ADAPTERS or not callable(self.sender):
            raise GuardError('explicit adapter and trusted sender required')
        if not hasattr(self.sender, 'identity'):
            raise GuardError('sender must expose a nonsecret host identity')
        if self.cache is not False:
            raise GuardError('provider cache is owned by the effect ledger')
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise GuardError('positive output token bound required')
        import math
        if self.max_cost_per_turn_usd is not None and (not math.isfinite(self.max_cost_per_turn_usd)
                                                       or self.max_cost_per_turn_usd <= 0):
            raise GuardError('finite positive per-turn cost reservation required')
        self._pin = digest(self.identity)

    @property
    def _llm_type(self):
        return 'ravel-transport'

    @property
    def identity(self):
        from .execution import file_hash
        from . import langchain_guard
        return {'adapter': self.adapter, 'model': self.model, 'host': deepcopy(self.sender.identity),
                'request_binding': deepcopy(self.request_binding), 'text_protocol': self.text_protocol,
                'streaming_declared': self.streaming_declared, 'stream_enabled': self.stream_enabled,
                'max_output_tokens': self.max_output_tokens, 'max_context_bytes': self.max_context_bytes,
                'max_cost_per_turn_usd': self.max_cost_per_turn_usd,
                'token_limit_field': self.token_limit_field,
                'sources': {'chat_model': file_hash(__file__),
                            'provider_tools': file_hash(provider_tools.__file__),
                            'guard': file_hash(langchain_guard.__file__)}}

    def current(self):
        if digest(self.identity) != self._pin:
            raise GuardError('provider request or host identity changed')

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        if kwargs or tool_choice not in (None, 'auto'):
            raise GuardError('bind explicit tool schemas; choice belongs to each receipted turn')
        bound = self.model_copy(update={'tools': deepcopy(tools)})
        return bound

    def turn(self, envelope, *, timeout=60, max_cost_usd=None, callbacks=()):
        if type(timeout) not in (int, float) or not 0 < timeout <= 86400:
            raise GuardError('finite socket deadline required')
        if envelope.get('stream', False) and not self.streaming_declared:
            raise GuardError('transport does not declare streaming')
        consumed = deepcopy(envelope)
        request_sha = digest(consumed)
        sent = False

        def current():
            self.current()
            if digest(envelope) != request_sha:
                raise GuardError('bound turn request changed')

        def dispatch():
            nonlocal sent
            body = provider_tools.render(self.adapter, consumed, model=self.model,
                max_output_tokens=self.max_output_tokens, text_protocol=self.text_protocol,
                token_limit_field=self.token_limit_field)
            if len(json.dumps(body).encode()) > self.max_context_bytes:
                raise GuardError('complete context exceeds declared bound; no truncation')
            # The enclosing model effect persists this exact request with its result.
            prompt = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
            sent = True
            delivery = self.sender(deepcopy(body), timeout=timeout, max_cost_usd=max_cost_usd)
            if type(delivery) is not dict or set(delivery) != {'body', 'http_status'}:
                raise GuardError('sender must return complete body and HTTP status')
            raw = delivery['body']
            status = delivery['http_status']
            evidence = {'request_sha256': digest(body), 'response_sha256': digest(raw),
                        'prompt': prompt, 'prompt_sha256': digest(body), 'model_requested': self.model,
                        'model_reported': raw.get('modelVersion' if self.adapter == 'gemini' else 'model') if type(raw) is dict else None,
                        'http_status': status, 'provider_usage': {}, 'usage': {}, 'message': None, 'error': None}
            if type(status) is not int or not 200 <= status < 300:
                evidence['error'] = {'code': 'http_error', 'message': 'provider HTTP refusal'}
                return evidence
            if type(raw) is dict:
                evidence['provider_usage'] = deepcopy(raw.get('usageMetadata' if self.adapter == 'gemini' else 'usage', {}))
            evidence['usage'] = usage(self.adapter, evidence['provider_usage'])
            try:
                if self.text_protocol:
                    text = raw if type(raw) is str else provider_tools.parse(self.adapter, raw)['content']
                    evidence['message'] = provider_tools.text_action(text, call_id='text-action')
                else:
                    evidence['message'] = provider_tools.parse(self.adapter, raw)
            except provider_tools.ProtocolError as exc:
                evidence['error'] = {'code': exc.code, 'message': str(exc)}
            return evidence
        try:
            return guarded(dispatch, current=current, callbacks=callbacks)
        except GuardError as exc:
            if not sent: raise PreDispatchRefusal(str(exc)) from exc
            raise

    def invoke(self, input, config=None, *, stop=None, **kwargs):
        config = deepcopy(config or {})
        if stop or kwargs or set(config) - {'callbacks', 'tags', 'metadata', 'run_name', 'run_id'}:
            raise GuardError('finite local chat invocation required')
        # BaseChatModel configures callbacks before _generate: guard its entry too.
        return guarded(lambda: super(RavelTransportChatModel, self).invoke(input, config),
                       current=self.current, callbacks=config.get('callbacks', ()))

    def generate(self, messages, stop=None, callbacks=None, **kwargs):
        # generate() is another public BaseChatModel entry point with early hooks.
        if len(messages) != 1 or stop or set(kwargs) - {'tags', 'metadata', 'run_name', 'run_id'}:
            raise GuardError('one public model turn per invocation')
        return guarded(lambda: super(RavelTransportChatModel, self).generate(
            messages, stop=stop, callbacks=callbacks, **kwargs), current=self.current, callbacks=callbacks or ())

    async def ainvoke(self, *args, **kwargs):
        raise GuardError('async model effects require an explicit ledger adapter')

    async def agenerate(self, *args, **kwargs):
        raise GuardError('async model effects require an explicit ledger adapter')

    def batch_as_completed(self, *args, **kwargs):
        raise GuardError('batched effects are refused')

    def abatch_as_completed(self, *args, **kwargs):
        raise GuardError('batched effects are refused')

    async def abatch(self, *args, **kwargs):
        raise GuardError('batched effects are refused')

    async def astream(self, *args, **kwargs):
        raise GuardError('streaming belongs to the declared turn sender')
        yield  # async generator API, unreachable by design

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if stop or kwargs:
            raise GuardError('no implicit stop rules or provider options')
        turns = []
        roles = {'human': 'user', 'system': 'system', 'ai': 'assistant', 'tool': 'tool'}
        for m in messages:
            if m.type not in roles or type(m.content) is not str:
                raise GuardError('public text/tool messages required')
            item = {'role': roles[m.type], 'content': m.content}
            if m.type == 'ai': item['tool_calls'] = deepcopy(m.tool_calls)
            if m.type == 'tool': item.update(tool_call_id=m.tool_call_id, name=m.name)
            turns.append(item)
        result = self.turn({'messages': turns, 'tools': self.tools, 'tool_choice': 'auto',
                            'stream': self.stream_enabled}, callbacks=run_manager or ())
        if result['error']: raise provider_tools.ProtocolError(**result['error'])
        message = result['message']
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=message['content'],
            tool_calls=message['tool_calls'], response_metadata={k: v for k, v in result.items() if k != 'message'}))])


def usage(adapter, raw):
    """Keep unknown token/cost counts unknown; never infer billing from tokens."""
    if type(raw) is not dict: return {'reported': False, 'cost_usd': None}
    names = {'gemini': ('promptTokenCount', 'candidatesTokenCount'),
             'chat_completions': ('prompt_tokens', 'completion_tokens')}.get(adapter, ('input_tokens', 'output_tokens'))
    result = {'reported': all(k in raw for k in names), 'cost_usd': raw.get('cost_usd')}
    for key, source in zip(('input_tokens', 'output_tokens'), names):
        value = raw.get(source)
        if value is not None and (type(value) is not int or value < 0):
            raise GuardError('invalid provider token usage')
        result[key] = value
    if result['cost_usd'] is not None:
        import math
        value = result['cost_usd']
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise GuardError('invalid provider cost usage')
    return result
