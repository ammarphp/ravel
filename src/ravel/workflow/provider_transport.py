"""Finite stateless provider wire formats; deterministic tools remain in AgentHost.

No SDK discovery, credential lookup, model inference, network call or fallback.
The public-record function is a structured return envelope, not a scientific tool.
Every returned value still passes AgentHost's complete local output validator.

Authentication is declared: a named environment variable, a token command run once
per request (for example ``gcloud auth print-access-token``), or none. The header
style is bearer, ``x-api-key``, ``x-goog-api-key`` or ``api-key``. Token values are
never logged, returned in errors or written to any record.
"""
from copy import deepcopy
import hashlib
import ipaddress
import json
import os
import re
import subprocess
from urllib.parse import quote

HTTP_ADAPTERS = frozenset({'responses', 'anthropic', 'gemini', 'chat_completions'})
DEFAULTS = {'responses': 'https://api.openai.com/v1/responses',
            'anthropic': 'https://api.anthropic.com/v1/messages',
            'gemini': 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'}
MODEL_ACTIONS = HTTP_ADAPTERS | {'command', 'model'}
HTTP_MODEL_ACTIONS = HTTP_ADAPTERS | {'model'}
FUNCTION = 'return_public_record'


class ProviderFailure(ValueError):
    pass


def loopback(endpoint):
    # Literal addresses only: no ambient DNS decision in local-only mode.
    if endpoint.hostname == 'localhost':
        return True
    try:
        return ipaddress.ip_address(endpoint.hostname).is_loopback
    except ValueError:
        return False


def policy(adapter, endpoint, privacy, local_models, capabilities):
    if type(privacy) is not str or privacy not in {'configured', 'local_only'}:
        raise ProviderFailure('privacy must be configured or local_only')
    if type(local_models) is not list or any(type(m) is not str or not m.strip() for m in local_models) or len(set(local_models)) != len(local_models):
        raise ProviderFailure('local_models must contain distinct explicit model identifiers')
    if privacy == 'local_only':
        if adapter not in HTTP_ADAPTERS or not loopback(endpoint) or not local_models:
            raise ProviderFailure('local_only requires literal loopback HTTP transport and explicit local_models; command is unconfined')
        if any(':cloud' in m.lower() for m in local_models):
            raise ProviderFailure('cloud model identifiers are forbidden in local_only')
    elif local_models:
        raise ProviderFailure('local_models requires local_only')
    if adapter in {'responses', 'command'}:
        if capabilities is not None:
            raise ProviderFailure('legacy Responses/command capabilities are fixed; choose a named provider adapter')
        return None
    if type(capabilities) is not dict or set(capabilities) != {'output_mode', 'token_limit_field', 'reasoning_efforts', 'max_context_bytes', 'max_output_tokens'}:
        raise ProviderFailure('named HTTP adapter requires complete explicit capabilities')
    c = deepcopy(capabilities)
    modes = {'tool_call', 'json_schema'} if adapter == 'chat_completions' else {'tool_call'}
    if type(c['output_mode']) is not str or c['output_mode'] not in modes:
        raise ProviderFailure('unsupported provider output mode; full local schema validation is mandatory')
    fields = {'max_tokens', 'max_completion_tokens'} if adapter == 'chat_completions' else ({'max_tokens'} if adapter == 'anthropic' else {'maxOutputTokens'})
    if type(c['token_limit_field']) is not str or c['token_limit_field'] not in fields:
        raise ProviderFailure('unsupported provider output token field')
    efforts = c['reasoning_efforts']
    if type(efforts) is not list or any(type(e) is not str or not e for e in efforts) or len(set(efforts)) != len(efforts):
        raise ProviderFailure('reasoning_efforts must be a distinct declared list; empty explicitly omits provider effort')
    if adapter != 'chat_completions' and efforts:
        raise ProviderFailure('this Messages/generateContent profile does not translate reasoning effort; declare empty list explicitly')
    for name, maximum in [('max_context_bytes', 16_000_000), ('max_output_tokens', 1_000_000)]:
        if type(c[name]) is not int or not 16 <= c[name] <= maximum:
            raise ProviderFailure('invalid provider capability bound: ' + name)
    return c


def request(adapter, parameters, context_text, wire_schema, capabilities, endpoint, privacy, local_models):
    model = parameters['model']
    if privacy == 'local_only' and model not in local_models:
        raise ProviderFailure('requested model is outside the exact local-only model allowlist')
    if len(context_text.encode()) > capabilities['max_context_bytes'] or parameters['max_output_tokens'] > capabilities['max_output_tokens']:
        raise ProviderFailure('complete context/output exceeds declared provider capabilities; no truncation')
    efforts = capabilities['reasoning_efforts']
    if efforts and parameters['reasoning_effort'] not in efforts:
        raise ProviderFailure('requested reasoning effort is unsupported by selected provider profile')
    instructions = ('Return only public JSON claims, evidence and concise public rationales. Do not return private reasoning traces.\n'
                    + parameters['instructions'])
    schema = wire_schema or {'type': 'object'}
    path = endpoint.path
    if adapter == 'anthropic':
        body = {'model': model, 'system': instructions, 'messages': [{'role': 'user', 'content': context_text}],
                'max_tokens': parameters['max_output_tokens'], 'stream': False,
                'tools': [{'name': FUNCTION, 'description': 'Return the complete public record; this executes no tool.', 'input_schema': schema}],
                'tool_choice': {'type': 'tool', 'name': FUNCTION, 'disable_parallel_tool_use': True}}
    elif adapter == 'gemini':
        if path.count('{model}') != 1 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}', model):
            raise ProviderFailure('Gemini endpoint requires one {model} placeholder and an explicit bare model ID')
        path = path.replace('{model}', quote(model, safe=''))
        body = {'systemInstruction': {'parts': [{'text': instructions}]},
                'contents': [{'role': 'user', 'parts': [{'text': context_text}]}],
                'generationConfig': {'candidateCount': 1, 'maxOutputTokens': parameters['max_output_tokens']},
                'tools': [{'functionDeclarations': [{'name': FUNCTION, 'description': 'Return the public record only.', 'parametersJsonSchema': schema}]}],
                'toolConfig': {'functionCallingConfig': {'mode': 'ANY', 'allowedFunctionNames': [FUNCTION]}}}
    else:
        body = {'model': model, 'messages': [{'role': 'system', 'content': instructions}, {'role': 'user', 'content': context_text}],
                capabilities['token_limit_field']: parameters['max_output_tokens'], 'stream': False, 'n': 1}
        if capabilities['output_mode'] == 'tool_call':
            body.update(tools=[{'type': 'function', 'function': {'name': FUNCTION, 'description': 'Return the public record only.', 'parameters': schema}}],
                        tool_choice={'type': 'function', 'function': {'name': FUNCTION}})
        else:
            if wire_schema is None:
                raise ProviderFailure('json_schema capability requires an explicit output schema')
            body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'public_record', 'strict': True, 'schema': schema}}
        if efforts:
            body['reasoning_effort'] = parameters['reasoning_effort']
    return body, path


AUTH_KINDS = ('env', 'command', 'none')
HEADER_STYLES = ('bearer', 'x-api-key', 'x-goog-api-key', 'api-key')
DEFAULT_HEADER = {'anthropic': 'x-api-key', 'gemini': 'x-goog-api-key', 'responses': 'bearer', 'chat_completions': 'bearer'}
MAX_TOKEN_BYTES = 16384


def auth_config(adapter, auth, privacy):
    """Validate an explicit HTTP auth block: {kind, env_name | command, header_style}. None keeps the legacy key path."""
    if auth is None:
        return None
    if adapter not in HTTP_ADAPTERS:
        raise ProviderFailure('auth applies to HTTP provider adapters only')
    if type(auth) is not dict or auth.get('kind') not in AUTH_KINDS:
        raise ProviderFailure('auth.kind must be env, command or none')
    allowed = {'kind', 'header_style'} | ({'env_name'} if auth['kind'] == 'env' else {'command'} if auth['kind'] == 'command' else set())
    if set(auth) - allowed:
        raise ProviderFailure('auth fields for kind ' + auth['kind'] + ': ' + ', '.join(sorted(allowed)))
    style = auth.get('header_style', DEFAULT_HEADER[adapter])
    if style not in HEADER_STYLES:
        raise ProviderFailure('auth.header_style must be one of ' + ', '.join(HEADER_STYLES))
    result = {'kind': auth['kind'], 'header_style': style}
    if auth['kind'] == 'env':
        if type(auth.get('env_name')) is not str or not auth['env_name'].isidentifier():
            raise ProviderFailure('env auth names one environment variable')
        result['env_name'] = auth['env_name']
    elif auth['kind'] == 'command':
        command = auth.get('command')
        if type(command) is not list or not command or any(type(a) is not str or not a or '\x00' in a for a in command):
            raise ProviderFailure('command auth names its token program as an argument list')
        if privacy == 'local_only':
            raise ProviderFailure('local_only refuses a token command; a loopback server needs no credential')
        result['command'] = list(command)
    return result


def auth_identity(auth):
    """Nonsecret identity: the kind, header style, variable name or the command's digest."""
    identity = {'kind': auth['kind'], 'header_style': auth['header_style']}
    if auth['kind'] == 'env':
        identity['env_name'] = auth['env_name']
    if auth['kind'] == 'command':
        identity['command_sha256'] = hashlib.sha256(json.dumps(auth['command']).encode()).hexdigest()
    return identity


TOKEN_ENVIRONMENT_EXCLUDE = re.compile(r'(_API_KEY|_AUTH_TOKEN|_SECRET)$|^(ANTHROPIC|OPENAI)_')


def check_token_program(program):
    """An absolute regular program with no replaceable group/world-writable ancestors."""
    import stat
    from pathlib import Path
    path = Path(program)
    if not path.is_absolute():
        raise ProviderFailure('token command must name its program by absolute path, not through PATH')
    try:
        info = path.resolve(strict=True).stat()
    except OSError:
        raise ProviderFailure('token command program is missing') from None
    if not stat.S_ISREG(info.st_mode) or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ProviderFailure('token command program must be a regular file not writable by group or others')
    # Check both the supplied path (including symlink parents) and the resolved target.
    for component in dict.fromkeys((*path.parents, *path.resolve(strict=True).parents)):
        info = component.stat()
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            if info.st_uid == 0 and info.st_mode & stat.S_ISVTX:
                continue
            raise ProviderFailure(f'token command path component is writable by group or others: {component}')


def run_token_command(command, *, timeout=60):
    """Run the declared token program for one request. Its output is the credential and is never logged.

    The program is named by absolute path and checked for group or world write access. It runs with the
    environment minus other providers' credential variables, and its output is read with a byte bound.
    """
    check_token_program(command[0])
    env = {k: v for k, v in os.environ.items() if not TOKEN_ENVIRONMENT_EXCLUDE.search(k)}
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env)
    except OSError:
        raise ProviderFailure('token command could not run') from None
    import selectors
    import time
    deadline, token = time.monotonic() + timeout, bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while len(token) <= MAX_TOKEN_BYTES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                if not selector.select(min(remaining, .1)):
                    continue
                block = os.read(process.stdout.fileno(), 4096)
                if not block:
                    break
                token.extend(block)
        process.wait(timeout=max(deadline - time.monotonic(), .01))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise ProviderFailure('token command timed out') from None
    finally:
        process.stdout.close()
    if process.poll() is None:
        process.kill()
        process.wait()
        raise ProviderFailure('token command output exceeds its bound')
    token = bytes(token)
    if process.returncode != 0:
        raise ProviderFailure(f'token command exited with status {process.returncode}')
    token = token.strip()
    if not token or len(token) > MAX_TOKEN_BYTES or any(c in token for c in b' \t\r\n\x00'):
        raise ProviderFailure('token command must print exactly one nonempty token')
    try:
        return token.decode('ascii')
    except UnicodeDecodeError:
        raise ProviderFailure('token command must print an ASCII token') from None


def headers(adapter, key, style=None):
    result = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if adapter == 'anthropic':
        result['anthropic-version'] = '2023-06-01'
    if key:
        style = style or DEFAULT_HEADER.get(adapter, 'bearer')
        if style == 'bearer':
            result['Authorization'] = 'Bearer ' + key
        else:
            result[style] = key
    return result


def _number(value, label, *, optional=False):
    if value is None and optional:
        return None
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ProviderFailure('invalid provider token count: ' + label)
    return value


def _identity(value, label):
    if type(value) is not str or not value.strip() or len(value) > 200:
        raise ProviderFailure('missing provider ' + label)
    return value


def response(adapter, document, capabilities, loads):
    if type(document) is not dict:
        raise ProviderFailure('provider result must be an object')
    details = {}
    if adapter == 'anthropic':
        if document.get('type') != 'message' or document.get('role') != 'assistant' or document.get('stop_reason') != 'tool_use':
            raise ProviderFailure('Claude result is not a completed public-record tool use')
        blocks = document.get('content')
        if type(blocks) is not list:
            raise ProviderFailure('invalid Claude content')
        calls = []
        for part in blocks:
            if type(part) is not dict:
                raise ProviderFailure('invalid Claude content block')
            if part.get('type') in {'thinking', 'redacted_thinking'}:
                continue  # Never retain private thinking or signatures.
            if part.get('type') == 'text' and type(part.get('text')) is str and not part['text'].strip():
                continue
            if part.get('type') != 'tool_use' or part.get('name') != FUNCTION:
                raise ProviderFailure('Claude returned extra prose, refusal or unsupported tool')
            _identity(part.get('id'), 'tool identity')
            calls.append(part.get('input'))
        if len(calls) != 1:
            raise ProviderFailure('exactly one public-record function required')
        value = calls[0]
        raw = document.get('usage')
        if type(raw) is not dict:
            raise ProviderFailure('Claude usage unavailable')
        i = _number(raw.get('input_tokens'), 'input_tokens')
        o = _number(raw.get('output_tokens'), 'output_tokens')
        for name in ['cache_creation_input_tokens', 'cache_read_input_tokens']:
            if name in raw:
                details[name] = _number(raw[name], name)
                i += details[name]
        usage = {'input_tokens': i, 'output_tokens': o, 'total_tokens': i + o}
        details['input_semantics'] = 'uncached + cache creation + cache read input tokens'
        model, identity = document.get('model'), document.get('id')
    elif adapter == 'gemini':
        candidates = document.get('candidates')
        if type(candidates) is not list or len(candidates) != 1 or type(candidates[0]) is not dict or candidates[0].get('finishReason') != 'STOP':
            raise ProviderFailure('Gemini result requires one complete candidate; blocked/truncated results refused')
        content = candidates[0].get('content')
        if type(content) is not dict or content.get('role') != 'model' or type(content.get('parts')) is not list:
            raise ProviderFailure('invalid Gemini candidate content')
        calls = []
        for part in content['parts']:
            if type(part) is not dict:
                raise ProviderFailure('invalid Gemini content part')
            if part.get('thought') is True:
                continue
            call = part.get('functionCall')
            if type(call) is not dict or call.get('name') != FUNCTION or set(part) - {'functionCall', 'thoughtSignature'}:
                raise ProviderFailure('Gemini returned extra prose or unsupported tool')
            calls.append(call.get('args'))
        if len(calls) != 1:
            raise ProviderFailure('exactly one public-record function required')
        value = calls[0]
        raw = document.get('usageMetadata')
        if type(raw) is not dict:
            raise ProviderFailure('Gemini usage unavailable')
        i = _number(raw.get('promptTokenCount'), 'promptTokenCount')
        o = _number(raw.get('candidatesTokenCount'), 'candidatesTokenCount')
        t = _number(raw.get('totalTokenCount'), 'totalTokenCount')
        thoughts = _number(raw.get('thoughtsTokenCount', 0), 'thoughtsTokenCount')
        if t != i + o + thoughts or _number(raw.get('toolUsePromptTokenCount', 0), 'toolUsePromptTokenCount') != 0:
            raise ProviderFailure('Gemini token census differs from the single stateless candidate law')
        usage = {'input_tokens': i, 'output_tokens': o + thoughts, 'total_tokens': t}
        details = {'candidate_tokens': o, 'thinking_tokens': thoughts, 'output_semantics': 'candidate + thinking tokens'}
        if 'cachedContentTokenCount' in raw:
            details['cached_input_tokens'] = _number(raw['cachedContentTokenCount'], 'cachedContentTokenCount')
            if details['cached_input_tokens'] > i:
                raise ProviderFailure('Gemini cached input exceeds the complete prompt token census')
        model, identity = document.get('modelVersion'), document.get('responseId')
    else:
        choices = document.get('choices')
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
            raise ProviderFailure('chat result requires exactly one candidate')
        choice = choices[0]
        message = choice.get('message')
        if type(message) is not dict or message.get('role') != 'assistant' or message.get('refusal'):
            raise ProviderFailure('chat result is not a public assistant message')
        if capabilities['output_mode'] == 'tool_call':
            calls = message.get('tool_calls')
            if choice.get('finish_reason') != 'tool_calls' or type(calls) is not list or len(calls) != 1 or message.get('content') not in (None, ''):
                raise ProviderFailure('chat result requires one complete public-record function')
            call = calls[0]
            if type(call) is not dict or call.get('type') != 'function' or type(call.get('function')) is not dict or call['function'].get('name') != FUNCTION:
                raise ProviderFailure('unsupported chat tool call')
            _identity(call.get('id'), 'tool identity')
            arguments = call['function'].get('arguments')
            if type(arguments) is not str:
                raise ProviderFailure('chat function arguments must be JSON text')
            value = loads(arguments)
        else:
            if choice.get('finish_reason') != 'stop' or message.get('tool_calls') or type(message.get('content')) is not str:
                raise ProviderFailure('chat JSON result is truncated or contains unsupported tools')
            value = loads(message['content'])
        raw = document.get('usage')
        if type(raw) is not dict:
            raise ProviderFailure('chat token usage unavailable')
        usage = dict(input_tokens=_number(raw.get('prompt_tokens'), 'prompt_tokens'),
                     output_tokens=_number(raw.get('completion_tokens'), 'completion_tokens'),
                     total_tokens=_number(raw.get('total_tokens'), 'total_tokens'))
        if usage['total_tokens'] != usage['input_tokens'] + usage['output_tokens']:
            raise ProviderFailure('chat token total differs from input plus output')
        model, identity = document.get('model'), document.get('id')
    if type(value) is not dict:
        raise ProviderFailure('public record must be an object')
    return value, _identity(model, 'observed model'), _identity(identity, 'response identity'), usage, details
