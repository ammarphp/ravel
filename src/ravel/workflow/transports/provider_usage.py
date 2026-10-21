"""Strict normalization of provider counters from supervisor-owned captures.

Only reported counters are summed. Protocols without an inference cache-write
category carry an explicit typed basis for that zero; missing actual counters
remain unknown. Model identities are observed response fields only.
"""
from __future__ import annotations

import json

from .. import broker

SPLIT = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')
SPLIT_LAUNCHERS = ('claude', 'codex', 'gemini')
SPLIT_ADAPTERS = ('anthropic', 'chat_completions', 'responses', 'gemini')


def split_problem(document):
    kind = document['transport_kind']
    if kind == 'cli-worker':
        name = document.get('launcher')
        return None if name in SPLIT_LAUNCHERS else 'usage_split_unreported:' + str(name)
    if kind == 'ravel-loop':
        from .ravel_loop import adapter_of
        name = adapter_of(document)
        return None if name in SPLIT_ADAPTERS else 'usage_split_unreported:' + str(name)
    return 'usage_split_unreported:' + kind


class InvalidUsage(ValueError):
    pass


def _count(document, key):
    value = document.get(key) if isinstance(document, dict) else None
    if type(value) is not int or value < 0:
        raise InvalidUsage('provider_usage_split_missing')
    return value


def _identity(value):
    return value if isinstance(value, str) and value else None


def _split(usage, protocol):
    if protocol == 'anthropic':
        return {key: _count(usage, key) for key in SPLIT}, {'kind': 'provider_reported', 'protocol': protocol}
    if protocol in ('codex', 'responses', 'chat_completions'):
        inp, out = ('prompt_tokens', 'completion_tokens') if protocol == 'chat_completions' else ('input_tokens', 'output_tokens')
        total, output = _count(usage, inp), _count(usage, out)
        if protocol == 'codex':
            cached = _count(usage, 'cached_input_tokens')
        else:
            detail = 'prompt_tokens_details' if protocol == 'chat_completions' else 'input_tokens_details'
            cached = _count(usage.get(detail), 'cached_tokens')
        details = usage.get('completion_tokens_details' if protocol == 'chat_completions' else 'output_tokens_details')
        if isinstance(details, dict) and 'reasoning_tokens' in details and _count(details, 'reasoning_tokens') > output:
            raise InvalidUsage('provider_usage_split_inconsistent')
        # OpenAI total_tokens, when present, includes cached input and reasoning output.
        if 'total_tokens' in usage and _count(usage, 'total_tokens') != total + output:
            raise InvalidUsage('provider_usage_split_inconsistent')
        basis = {'kind': 'protocol_no_cache_write_category', 'protocol': protocol,
                 'cache_creation_input_tokens': 0}
    elif protocol in ('gemini', 'gemini-cli'):
        if protocol == 'gemini-cli':
            total, cached = _count(usage, 'prompt'), _count(usage, 'cached')
            output = _count(usage, 'candidates') + _count(usage, 'thoughts')
            total_key = 'total'
        else:
            total, cached = _count(usage, 'promptTokenCount'), _count(usage, 'cachedContentTokenCount')
            output = _count(usage, 'candidatesTokenCount') + _count(usage, 'thoughtsTokenCount')
            total_key = 'totalTokenCount'
        if total_key in usage and _count(usage, total_key) != total + output:
            raise InvalidUsage('provider_usage_split_inconsistent')
        basis = {'kind': 'cache_resource_creation_separate_operation', 'protocol': protocol,
                 'cache_creation_input_tokens': 0}
    else:
        raise InvalidUsage('provider_usage_split_unavailable')
    if cached > total:
        raise InvalidUsage('provider_usage_split_inconsistent')
    # Reject a claimed write counter in a protocol that has no such category.
    if 'cache_creation_input_tokens' in usage and _count(usage, 'cache_creation_input_tokens') != 0:
        raise InvalidUsage('provider_usage_split_inconsistent')
    return dict(zip(SPLIT, (total - cached, 0, cached, output))), basis


def normalize_usage(adapter, raw_usage):
    """Normalize a single inference response without inventing missing counters."""
    try:
        usage, basis = _split(raw_usage, adapter)
        return {'status': 'reported', 'usage': usage, 'split_basis': [basis]}
    except InvalidUsage as exc:
        return {'status': 'unknown', 'reason': str(exc)}
    except (TypeError, AttributeError):
        return {'status': 'unknown', 'reason': 'provider_usage_split_missing'}


def _reported(agent, session, rows):
    if not _identity(session):
        raise InvalidUsage('provider_session_missing')
    if not rows:
        raise InvalidUsage('provider_request_count_missing')
    total, requests, bases, models = dict.fromkeys(SPLIT, 0), 0, [], []
    for usage, protocol, count, model in rows:
        if type(count) is not int or count < 1:
            raise InvalidUsage('provider_request_count_missing')
        split, basis = _split(usage, protocol)
        for key in SPLIT:
            total[key] += split[key]
        requests += count
        if basis not in bases:
            bases.append(basis)
        if _identity(model) and model not in models:
            models.append(model)
    return {'status': 'reported', 'agent': agent, 'session_id': session, 'requests': requests,
            'usage': total, 'split_basis': bases, 'models': models}


def decode(raw, agent):
    """Decode supported provider envelopes; never use a worker's structured answer."""
    unknown = {'status': 'unknown', 'reason': 'provider_usage_split_unavailable', 'agent': agent}
    if agent not in (*SPLIT_LAUNCHERS, 'ravel-loop'):
        return unknown
    try:
        if agent == 'codex':
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8')
            events = [json.loads(line) for line in raw.splitlines() if line.strip()]
            sessions = [e.get('thread_id') for e in events if isinstance(e, dict) and e.get('type') == 'thread.started']
            if len(sessions) != 1:
                return unknown
            if any(isinstance(e, dict) and e.get('type') in ('turn.failed', 'error') for e in events):
                raise InvalidUsage('provider_usage_split_missing')
            rows = [(e.get('usage'), 'codex', 1, e.get('model')) for e in events
                    if isinstance(e, dict) and e.get('type') == 'turn.completed']
            started = sum(isinstance(e, dict) and e.get('type') == 'turn.started' for e in events)
            if started and started != len(rows):
                raise InvalidUsage('provider_request_count_missing')
            return _reported(agent, sessions[0], rows)
        document = json.loads(raw)
        if agent == 'claude':
            if isinstance(document, list):
                results = [d for d in document if isinstance(d, dict) and d.get('type') == 'result']
                if len(results) != 1:
                    raise InvalidUsage('provider_result_ambiguous')
                document = results[0]
            if not isinstance(document, dict) or document.get('type') != 'result':
                raise InvalidUsage('provider_result_missing')
            result = _reported(agent, document.get('session_id'), [(document.get('usage'), 'anthropic',
                               document.get('num_turns'), document.get('model'))])
            model_usage = document.get('modelUsage')
            if isinstance(model_usage, dict):
                result['models'] = list(dict.fromkeys(result['models'] + [m for m in model_usage if _identity(m)]))
            return result
        if not isinstance(document, dict):
            return unknown
        if agent == 'gemini':
            models = (document.get('stats') or {}).get('models')
            if not isinstance(models, dict) or not models:
                return unknown
            rows = [(row.get('tokens'), 'gemini-cli', (row.get('api') or {}).get('totalRequests'), model)
                    for model, row in models.items() if isinstance(row, dict)]
            if len(rows) != len(models):
                raise InvalidUsage('provider_usage_split_missing')
            return _reported(agent, document.get('session_id') or document.get('sessionId'), rows)
        if document.get('type') != 'ravel-loop-result' or document.get('schema_version') != 1:
            raise InvalidUsage('provider_result_missing')
        turns = document.get('turns')
        if (not isinstance(turns, list) or type(document.get('num_turns')) is not int
                or document['num_turns'] != len(turns)):
            raise InvalidUsage('provider_request_count_missing')
        rows = [(turn.get('usage'), document.get('adapter'), 1, turn.get('model'))
                for turn in turns if isinstance(turn, dict)]
        if len(rows) != len(turns):
            raise InvalidUsage('provider_usage_split_missing')
        return _reported(agent, document.get('session_id'), rows)
    except InvalidUsage as exc:
        return {**unknown, 'reason': str(exc)}
    except (ValueError, TypeError, AttributeError, UnicodeError):
        return {**unknown, 'reason': 'provider_result_invalid'}


def capture(rundir, node_id, attempt, agent):
    """Read the transport result only from the supervisor's pipe capture."""
    from ..agent_worker import capture_path
    path = capture_path(rundir, node_id, attempt, 'stdout')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > broker.MAX_MESSAGE:
        return {'status': 'unknown', 'reason': 'provider_capture_missing', 'agent': agent}
    raw = path.read_bytes()
    from hashlib import sha256
    return {**decode(raw, agent), 'stdout_sha256': sha256(raw).hexdigest(),
            'node_id': node_id, 'attempt': attempt}
