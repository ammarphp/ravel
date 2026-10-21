"""Provider format fixtures and strict accounting custody checks."""
from copy import deepcopy
import json

import pytest

from ravel.workflow.transports import provider_usage as p

ANTHROPIC = dict(zip(p.SPLIT, (12, 3, 5, 7)))
OPENAI = {'input_tokens': 20, 'input_tokens_details': {'cached_tokens': 5}, 'output_tokens': 7}
CHAT = {'prompt_tokens': 20, 'prompt_tokens_details': {'cached_tokens': 5}, 'completion_tokens': 7}
GEMINI = {'promptTokenCount': 20, 'cachedContentTokenCount': 5,
          'candidatesTokenCount': 4, 'thoughtsTokenCount': 3, 'totalTokenCount': 27}


def fixtures():
    yield 'claude', {'type': 'result', 'session_id': 's', 'num_turns': 2, 'usage': ANTHROPIC}, 2
    yield 'gemini', {'session_id': 's', 'stats': {'models': {'observed': {
        'tokens': {'prompt': 20, 'cached': 5, 'candidates': 4, 'thoughts': 3, 'total': 27},
        'api': {'totalRequests': 2}}}}}, 2
    for adapter, usage in [('anthropic', ANTHROPIC), ('chat_completions', CHAT),
                           ('responses', OPENAI), ('gemini', GEMINI)]:
        yield 'ravel-loop', {'type': 'ravel-loop-result', 'schema_version': 1, 'session_id': 's',
                            'num_turns': 1, 'adapter': adapter, 'model_requested': 'never-observed',
                            'turns': [{'usage': usage, 'model': 'observed'}]}, 1


@pytest.mark.parametrize('agent,document,requests', list(fixtures()))
def test_provider_formats(agent, document, requests):
    original = deepcopy(document)
    result = p.decode(json.dumps(document), agent)
    assert result['status'] == 'reported'
    assert result['requests'] == requests and result['session_id'] == 's'
    assert sum(result['usage'].values()) == 27
    assert 'never-observed' not in result['models']
    assert result['split_basis']
    assert document == original


def codex(usage=None):
    return '\n'.join(json.dumps(e) for e in [{'type': 'thread.started', 'thread_id': 's'},
        {'type': 'turn.completed', 'usage': usage if usage is not None else {
            'input_tokens': 20, 'cached_input_tokens': 5, 'output_tokens': 7}}])


def test_codex_jsonl_and_multiple_turns():
    raw = codex()
    result = p.decode(raw, 'codex')
    assert result['usage'] == dict(zip(p.SPLIT, (15, 0, 5, 7)))
    assert result['split_basis'][0]['kind'] == 'protocol_no_cache_write_category'
    assert result['models'] == []
    result = p.decode(raw + '\n' + raw.splitlines()[1], 'codex')
    assert result['requests'] == 2 and result['usage']['input_tokens'] == 30


@pytest.mark.parametrize('adapter,raw', [('anthropic', ANTHROPIC), ('responses', OPENAI),
                                      ('chat_completions', CHAT), ('gemini', GEMINI)])
@pytest.mark.parametrize('bad', [None, True, -1, 1.5])
def test_actual_counters_missing_or_invalid_fail_closed(adapter, raw, bad):
    usage = deepcopy(raw)
    key = next(iter(usage))
    if bad is None:
        del usage[key]
    else:
        usage[key] = bad
    assert p.normalize_usage(adapter, usage)['status'] == 'unknown'


@pytest.mark.parametrize('bad', [None, True, -1, 21])
def test_cached_input_never_defaulted_or_exceeds_total(bad):
    usage = deepcopy(OPENAI)
    usage['input_tokens_details']['cached_tokens'] = bad
    assert p.normalize_usage('responses', usage)['status'] == 'unknown'
    assert p.decode(codex({'input_tokens': 20, 'output_tokens': 7, 'cached_input_tokens': bad}), 'codex')['status'] == 'unknown'


def test_totals_and_expected_thoughts_must_be_consistent():
    assert p.normalize_usage('responses', {**OPENAI, 'total_tokens': 26})['status'] == 'unknown'
    assert p.normalize_usage('gemini', {**GEMINI, 'totalTokenCount': 26})['status'] == 'unknown'
    usage = deepcopy(GEMINI)
    del usage['thoughtsTokenCount']
    assert p.normalize_usage('gemini', usage)['status'] == 'unknown'
    assert p.normalize_usage('responses', {**OPENAI, 'cache_creation_input_tokens': 1})['status'] == 'unknown'


@pytest.mark.parametrize('bad', [None, True, -1, 0])
def test_requests_missing_invalid_fail_closed(bad):
    agent, document, _ = list(fixtures())[1]
    document['stats']['models']['observed']['api']['totalRequests'] = bad
    assert p.decode(json.dumps(document), agent)['status'] == 'unknown'


def test_meter_requires_verified_capture_and_matching_totals(tmp_path, monkeypatch):
    from ravel.controller.step.graph import _meter
    from ravel.workflow import agent_worker, broker
    path = tmp_path / 'stdout'
    path.write_text(codex())
    monkeypatch.setattr(agent_worker, 'capture_path', lambda *args: path)
    receipt = {'node_id': 'n', 'attempt': 1, 'session_id': 's',
               'usage': {'reported': True, 'turns': 1, 'input_tokens': 20, 'output_tokens': 7},
               'transport': {'agent': 'codex', 'observation': {'stdout_sha256': broker.sha(path)}}}
    usage, meter = _meter(tmp_path, receipt)
    assert meter['split'] == 'complete' and meter['split_basis']
    assert usage['raw'] == dict(zip(p.SPLIT[:3], (15, 0, 5)))
    receipt['usage']['turns'] = True
    assert _meter(tmp_path, receipt)[1]['split'] == 'split_inconsistent'
    receipt['usage']['raw'] = {'input_tokens': 999}
    path.write_text(codex() + '\n')
    usage, meter = _meter(tmp_path, receipt)
    assert meter['split'] == 'capture_unverified' and 'raw' not in usage


@pytest.mark.parametrize('bad', [True, -1, 8])
def test_impossible_reasoning_counters_fail_closed(bad):
    usage = {**OPENAI, 'output_tokens_details': {'reasoning_tokens': bad}}
    assert p.normalize_usage('responses', usage)['status'] == 'unknown'


def test_failed_codex_turn_never_claims_complete_census():
    assert p.decode(codex() + '\n' + json.dumps({'type': 'turn.failed'}), 'codex')['status'] == 'unknown'


def test_claude_observed_model_usage_names_are_preserved():
    agent, document, _ = list(fixtures())[0]
    document['modelUsage'] = {'observed-claude': {}}
    document['model_requested'] = 'requested-only'
    assert p.decode(json.dumps(document), agent)['models'] == ['observed-claude']


def test_unfinished_codex_turn_stays_unknown():
    raw = codex() + '\n' + json.dumps({'type': 'turn.started'}) + '\n' + json.dumps({'type': 'turn.started'})
    assert p.decode(raw, 'codex')['status'] == 'unknown'
