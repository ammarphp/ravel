"""SDK-free multi-turn wire envelopes and one-action text protocol.

Only public text and function arguments are parsed. Private reasoning blocks are
not converted into the model transcript. Raw transport digests remain evidence.
"""
from copy import deepcopy
import json
import re

ADAPTERS = frozenset({'anthropic', 'gemini', 'chat_completions', 'responses'})
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_-]{0,63}\Z')


class ProtocolError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def loads(text):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value
    def constant(_):
        raise ValueError('nonfinite JSON value')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def text_action(text, *, call_id):
    try:
        value = loads(text)
    except (TypeError, ValueError):
        raise ProtocolError('malformed_json', 'one complete JSON object required') from None
    if type(value) is list:
        raise ProtocolError('multiple_actions', 'one action per turn required')
    if (type(value) is not dict or set(value) != {'action', 'args'}
            or type(value['action']) is not str or type(value['args']) is not dict):
        raise ProtocolError('invalid_action', 'action and args object required')
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': call_id, 'name': value['action'], 'args': value['args']}]}


# Adapters whose request carries a reasoning effort, and the request field that carries it. The
# Messages and Gemini requests here have no effort field, so an effort for them is refused.
EFFORT_FIELDS = {'chat_completions': 'reasoning_effort', 'responses': 'reasoning.effort'}


def render(adapter, envelope, *, model, max_output_tokens, text_protocol=False,
           token_limit_field='max_completion_tokens', reasoning_effort=None):
    if adapter not in ADAPTERS:
        raise ProtocolError('unknown_adapter', 'explicit provider adapter required')
    if reasoning_effort is not None and (adapter not in EFFORT_FIELDS or type(reasoning_effort) is not str
                                         or not reasoning_effort):
        raise ProtocolError('effort_unsupported', f'the {adapter} request carries no reasoning effort')
    messages, tools = deepcopy(envelope['messages']), deepcopy(envelope['tools'])
    stream = envelope.get('stream', False)
    choice = envelope.get('tool_choice', 'auto')
    if choice not in ('auto', 'required', 'none', 'submit_final') or type(stream) is not bool:
        raise ProtocolError('invalid_envelope', 'finite tool choice and boolean stream required')
    if text_protocol:
        instruction = ('Return exactly one JSON object with keys action (tool name) and args (object). '
                       'No prose, lists or multiple actions. Available tools: ' + json.dumps(tools, sort_keys=True))
        messages.insert(0, {'role': 'system', 'content': instruction})
        for message in messages:
            if message['role'] == 'assistant' and message.get('tool_calls'):
                call = message['tool_calls'][0]
                message['content'] = json.dumps({'action': call['name'], 'args': call['args']})
                message.pop('tool_calls')
            if message['role'] == 'tool':
                message.update(role='user', content='Tool result: ' + message['content'])
        tools = []
    system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
    if adapter == 'anthropic':
        turns = []
        for m in messages:
            if m['role'] == 'system': continue
            role = 'user' if m['role'] == 'tool' else m['role']
            if m['role'] == 'tool':
                content = [{'type': 'tool_result', 'tool_use_id': m['tool_call_id'], 'content': m['content']}]
            else:
                content = ([{'type': 'text', 'text': m['content']}] if m.get('content') else []) + [
                    {'type': 'tool_use', 'id': c['id'], 'name': c['name'], 'input': c['args']}
                    for c in m.get('tool_calls', [])]
            if turns and turns[-1]['role'] == role: turns[-1]['content'].extend(content)
            else: turns.append({'role': role, 'content': content})
        body = {'model': model, 'system': system, 'messages': turns,
                'max_tokens': max_output_tokens, 'stream': stream}
        if tools:
            body['tools'] = [{'name': t['name'], 'description': t['description'], 'input_schema': t['args_schema']} for t in tools]
            body['tool_choice'] = ({'type': 'tool', 'name': 'submit_final'} if choice == 'submit_final' else
                                   {'type': {'required': 'any', 'none': 'none', 'auto': 'auto'}[choice]})
            if choice != 'none': body['tool_choice']['disable_parallel_tool_use'] = True
        return body
    if adapter == 'gemini':
        turns = []
        for m in messages:
            if m['role'] == 'system': continue
            parts = [{'text': m['content']}] if m.get('content') and m['role'] != 'tool' else []
            parts.extend({'functionCall': {'id': c['id'], 'name': c['name'], 'args': c['args']}}
                         for c in m.get('tool_calls', []))
            if m['role'] == 'tool':
                parts = [{'functionResponse': {'id': m['tool_call_id'], 'name': m['name'], 'response': loads(m['content'])}}]
            turns.append({'role': 'model' if m['role'] == 'assistant' else 'user', 'parts': parts})
        body = {'systemInstruction': {'parts': [{'text': system}]}, 'contents': turns,
                'generationConfig': {'candidateCount': 1, 'maxOutputTokens': max_output_tokens}}
        if tools:
            body['tools'] = [{'functionDeclarations': [{'name': t['name'], 'description': t['description'],
                              'parametersJsonSchema': t['args_schema']} for t in tools]}]
            mode = {'auto': 'AUTO', 'required': 'ANY', 'none': 'NONE', 'submit_final': 'ANY'}[choice]
            body['toolConfig'] = {'functionCallingConfig': {'mode': mode}}
            if choice == 'submit_final': body['toolConfig']['functionCallingConfig']['allowedFunctionNames'] = ['submit_final']
        return body
    if adapter == 'responses':
        turns = []
        for m in messages:
            if m['role'] == 'tool':
                turns.append({'type': 'function_call_output', 'call_id': m['tool_call_id'], 'output': m['content']})
            else:
                if m.get('content'): turns.append({'role': m['role'], 'content': m['content']})
                turns.extend({'type': 'function_call', 'call_id': c['id'], 'name': c['name'], 'arguments': json.dumps(c['args'])}
                             for c in m.get('tool_calls', []))
        body = {'model': model, 'input': turns, 'max_output_tokens': max_output_tokens, 'stream': stream}
        if reasoning_effort is not None:
            body['reasoning'] = {'effort': reasoning_effort}
        if tools:
            body['tools'] = [{'type': 'function', 'name': t['name'], 'description': t['description'], 'parameters': t['args_schema']} for t in tools]
            body['tool_choice'] = {'type': 'function', 'name': 'submit_final'} if choice == 'submit_final' else choice
            body['parallel_tool_calls'] = False
        return body
    if token_limit_field not in ('max_tokens', 'max_completion_tokens'):
        raise ProtocolError('invalid_envelope', 'explicit chat token limit field required')
    turns = []
    for m in messages:
        item = {'role': m['role'], 'content': m.get('content', '')}
        if m['role'] == 'tool': item['tool_call_id'] = m['tool_call_id']
        if m.get('tool_calls'):
            item['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': json.dumps(c['args'])}}
                                  for c in m['tool_calls']]
        turns.append(item)
    body = {'model': model, 'messages': turns, token_limit_field: max_output_tokens, 'n': 1, 'stream': stream}
    if reasoning_effort is not None:
        body['reasoning_effort'] = reasoning_effort
    if tools:
        body['tools'] = [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'], 'parameters': t['args_schema']}} for t in tools]
        body['tool_choice'] = {'type': 'function', 'function': {'name': 'submit_final'}} if choice == 'submit_final' else choice
        body['parallel_tool_calls'] = False
    return body


def parse(adapter, document):
    """Parse a complete public assistant turn, rejecting incomplete deliveries."""
    calls, texts = [], []
    try:
        if adapter == 'anthropic':
            if document.get('stop_reason') not in ('tool_use', 'end_turn') or document.get('role') != 'assistant':
                raise ValueError('incomplete message')
            for part in document['content']:
                if part['type'] == 'text': texts.append(part['text'])
                elif part['type'] == 'tool_use': calls.append({'id': part['id'], 'name': part['name'], 'args': part['input']})
                elif part['type'] not in ('thinking', 'redacted_thinking'): raise ValueError('unsupported content')
        elif adapter == 'gemini':
            if len(document['candidates']) != 1 or document['candidates'][0]['finishReason'] != 'STOP': raise ValueError('incomplete candidate')
            for i, part in enumerate(document['candidates'][0]['content']['parts']):
                if 'functionCall' in part:
                    call = part['functionCall']
                    calls.append({'id': call.get('id', 'call-' + str(i)), 'name': call['name'], 'args': call['args']})
                elif 'text' in part and not part.get('thought'): texts.append(part['text'])
        elif adapter == 'responses':
            if document['status'] != 'completed': raise ValueError('incomplete response')
            for part in document['output']:
                if part['type'] == 'function_call': calls.append({'id': part['call_id'], 'name': part['name'], 'args': loads(part['arguments'])})
                elif part['type'] == 'message':
                    for content in part['content']:
                        if content['type'] != 'output_text': raise ValueError('refused response')
                        texts.append(content['text'])
                elif part['type'] != 'reasoning': raise ValueError('unsupported response')
        elif adapter == 'chat_completions':
            if len(document['choices']) != 1 or document['choices'][0]['finish_reason'] not in ('stop', 'tool_calls'): raise ValueError('incomplete choice')
            message = document['choices'][0]['message']
            if message.get('refusal'): raise ValueError('refused response')
            if message.get('content'): texts.append(message['content'])
            for part in message.get('tool_calls', []):
                calls.append({'id': part['id'], 'name': part['function']['name'], 'args': loads(part['function']['arguments'])})
        else: raise ValueError('unsupported adapter')
        if any(type(c['id']) is not str or not c['id'] or type(c['name']) is not str
               or type(c['args']) is not dict for c in calls): raise ValueError('invalid function call')
        if any(type(t) is not str for t in texts): raise ValueError('invalid public text')
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProtocolError('invalid_provider_response', 'complete public provider turn required') from None
    return {'role': 'assistant', 'content': ''.join(texts), 'tool_calls': calls}
