"""Agent session audit log from synthetic Claude Code and Codex transcripts."""
import io
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_audit as aa


def jsonl(path, rows):
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return path


def claude_rows(session='s-1', model='claude-test-build-20260101'):
    usage1 = {'input_tokens': 10, 'cache_creation_input_tokens': 100, 'cache_read_input_tokens': 1000, 'output_tokens': 5}
    usage1_final = dict(usage1, output_tokens=40)
    usage2 = {'input_tokens': 3, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 1200, 'output_tokens': 7}
    return [
        {'type': 'summary', 'summary': 'ignored'},
        {'type': 'user', 'sessionId': session, 'version': '2.1.0', 'timestamp': '2026-10-10T10:00:00Z',
         'message': {'role': 'user', 'content': 'Design the selection for the supplied samples.'}},
        # One assistant message streamed over two rows: usage must be counted once (last row wins).
        {'type': 'assistant', 'sessionId': session, 'timestamp': '2026-10-10T10:00:05Z',
         'message': {'id': 'msg_1', 'model': model, 'role': 'assistant', 'usage': usage1,
                     'content': [{'type': 'text', 'text': 'Looking.'}]}},
        {'type': 'assistant', 'sessionId': session, 'timestamp': '2026-10-10T10:00:06Z',
         'message': {'id': 'msg_1', 'model': model, 'role': 'assistant', 'usage': usage1_final,
                     'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ls'}}]}},
        {'type': 'user', 'sessionId': session, 'timestamp': '2026-10-10T10:00:07Z',
         'message': {'role': 'user', 'content': [{'type': 'tool_result', 'content': 'files'}]}},
        {'type': 'assistant', 'sessionId': session, 'timestamp': '2026-10-10T10:00:08Z',
         'message': {'id': 'msg_2', 'model': model, 'role': 'assistant', 'usage': usage2,
                     'content': [{'type': 'tool_use', 'name': 'Read', 'input': {}}, {'type': 'tool_use', 'name': 'Bash', 'input': {}}]}},
        {'type': 'user', 'isMeta': True, 'sessionId': session, 'message': {'role': 'user', 'content': 'caveat'}},
        {'type': 'user', 'sessionId': session, 'timestamp': '2026-10-10T10:05:00Z',
         'message': {'role': 'user', 'content': [{'type': 'text', 'text': 'Now write the note.'}]}},
        {'type': 'assistant', 'sessionId': session, 'timestamp': '2026-10-10T10:05:09Z',
         'message': {'id': 'msg_3', 'model': '<synthetic>', 'role': 'assistant',
                     'usage': {'input_tokens': 0, 'output_tokens': 0}, 'content': []}},
        # A subagent's first prompt and reply in the same file.
        {'type': 'user', 'isSidechain': True, 'agentId': 'a7', 'sessionId': session, 'timestamp': '2026-10-10T10:01:00Z',
         'message': {'role': 'user', 'content': 'Review the cutflow.'}},
        {'type': 'assistant', 'isSidechain': True, 'agentId': 'a7', 'sessionId': session, 'timestamp': '2026-10-10T10:01:30Z',
         'message': {'id': 'msg_s1', 'model': 'claude-small-build', 'role': 'assistant',
                     'usage': {'input_tokens': 50, 'output_tokens': 9}, 'content': []}},
    ]


def codex_rows():
    def tokens(i, c, o):
        return {'type': 'event_msg', 'timestamp': 'x', 'payload': {'type': 'token_count', 'info': {
            'total_token_usage': {'input_tokens': i, 'cached_input_tokens': c, 'output_tokens': o, 'total_tokens': i + o},
            'last_token_usage': {}}}}
    return [
        {'timestamp': '2026-10-10T11:00:00Z', 'type': 'session_meta', 'payload': {'id': 'cx-1', 'cli_version': '0.50.0'}},
        {'timestamp': '2026-10-10T11:00:00Z', 'type': 'turn_context', 'payload': {'model': 'gpt-test-codex'}},
        {'timestamp': '2026-10-10T11:00:01Z', 'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '<environment_context>'}]}},
        {'timestamp': '2026-10-10T11:00:01Z', 'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'Fit the control regions.'}},
        {'timestamp': '2026-10-10T11:00:02Z', 'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'shell', 'arguments': '{}'}},
        tokens(1000, 800, 50), tokens(1000, 800, 50),
        {'timestamp': '2026-10-10T11:00:03Z', 'type': 'event_msg', 'payload': {'type': 'agent_message', 'message': 'done'}},
        {'timestamp': '2026-10-10T11:02:00Z', 'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'Plot the yields.'}},
        tokens(2500, 1900, 130),
    ]


def test_claude_transcript_gives_one_row_per_prompt_with_deduplicated_usage(tmp_path):
    path = jsonl(tmp_path / 's.jsonl', claude_rows())
    parsed = aa.parse(path)
    main = [r for r in parsed['records'] if not r['sidechain']]
    side = [r for r in parsed['records'] if r['sidechain']]
    assert [r['prompt'] for r in main] == ['Design the selection for the supplied samples.', 'Now write the note.']
    first = main[0]
    assert first['model'] == 'claude-test-build-20260101' and first['timestamp'] == '2026-10-10T10:00:00Z'
    assert first['usage'] == {'input_tokens': 1110 + 1203, 'cached_input_tokens': 2200, 'cache_creation_input_tokens': 100,
                              'output_tokens': 47, 'total_tokens': 1110 + 1203 + 47}
    assert first['tool_calls'] == {'Bash': 2, 'Read': 1} and first['assistant_messages'] == 2
    assert main[1]['model'] is None  # a synthetic placeholder is not a model build
    assert side[0]['prompt'] == 'Review the cutflow.' and side[0]['model'] == 'claude-small-build'
    assert side[0]['stream'] == 'sidechain:a7'


def test_codex_rollout_prompts_use_cumulative_counter_deltas(tmp_path):
    parsed = aa.parse(jsonl(tmp_path / 'rollout.jsonl', codex_rows()))
    first, second = parsed['records']
    assert first['prompt'] == 'Fit the control regions.' and first['model'] == 'gpt-test-codex'
    assert first['usage']['input_tokens'] == 1000 and first['usage']['output_tokens'] == 50
    assert second['usage']['input_tokens'] == 1500 and second['usage']['cached_input_tokens'] == 1100
    assert first['tool_calls'] == {'shell': 1} and first['session_id'] == 'cx-1' and first['cli_version'] == '0.50.0'


def test_totals_equal_per_message_sums(tmp_path):
    audit = aa.collect([jsonl(tmp_path / 's.jsonl', claude_rows()), jsonl(tmp_path / 'r.jsonl', codex_rows())])
    assert all(c['consistent'] for c in audit['checks'])
    claude = next(c for c in audit['checks'] if c['source'].endswith('s.jsonl'))
    assert claude['prompt_usage_sum'] == claude['message_usage_sum']
    assert audit['totals']['output_tokens'] == 47 + 0 + 9 + 130
    assert [r['timestamp'] for r in audit['records']] == sorted(r['timestamp'] for r in audit['records'])


def test_written_log_has_jsonl_markdown_and_summary(tmp_path):
    audit = aa.collect([jsonl(tmp_path / 's.jsonl', claude_rows())])
    result = aa.write(audit, tmp_path / 'out')
    rows = [json.loads(l) for l in (tmp_path / 'out/agent-audit.jsonl').read_text().splitlines()]
    assert len(rows) == result['prompts'] == 3
    md = (tmp_path / 'out/agent-audit.md').read_text()
    assert 'claude-test-build-20260101' in md and 'Design the selection' in md and '| - |' in md
    with pytest.raises(ValueError):
        aa.write(audit, tmp_path / 'out')


def test_hooks_append_prompt_and_completed_turn_once(tmp_path, monkeypatch):
    transcript = jsonl(tmp_path / 's.jsonl', claude_rows())
    log = tmp_path / 'audit/agent-prompts.jsonl'
    submit = {'hook_event_name': 'UserPromptSubmit', 'session_id': 's-1', 'prompt': 'Design the selection for the supplied samples.',
              'transcript_path': str(transcript), 'cwd': str(tmp_path)}
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps(submit)))
    assert aa.main(['hook', '--log', str(log)]) == 0
    stop = {'hook_event_name': 'Stop', 'session_id': 's-1', 'transcript_path': str(transcript)}
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps(stop)))
    aa.main(['hook', '--log', str(log)])
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps(stop)))
    aa.main(['hook', '--log', str(log)])
    events = aa.read_log(log)
    assert [e['event'] for e in events].count('prompt_submitted') == 1
    assert [e['event'] for e in events].count('turn_recorded') == 3


def test_hook_never_fails_the_session(tmp_path, monkeypatch, capsys):
    log = tmp_path / 'log.jsonl'
    monkeypatch.setattr('sys.stdin', io.StringIO('not json'))
    assert aa.main(['hook', '--log', str(log)]) == 0
    assert capsys.readouterr().out == ''
    assert aa.read_log(log)[0]['event'] == 'hook_error'


def test_build_keeps_hook_turns_after_transcript_is_gone_and_reports_gaps(tmp_path, monkeypatch):
    transcript = jsonl(tmp_path / 's.jsonl', claude_rows())
    log = tmp_path / 'log.jsonl'
    aa.handle_hook({'hook_event_name': 'Stop', 'transcript_path': str(transcript)}, log)
    aa.handle_hook({'hook_event_name': 'UserPromptSubmit', 'session_id': 's-1', 'prompt': 'A prompt never answered'}, log)
    transcript.unlink()
    audit = aa.build(log)
    assert len(audit['records']) == 3 and audit['gaps'][0]['prompt'] == 'A prompt never answered'


def test_codex_notify_records_turn(tmp_path):
    log = tmp_path / 'log.jsonl'
    payload = {'type': 'agent-turn-complete', 'turn-id': 't1', 'input-messages': ['Plot it'], 'last-assistant-message': 'ok'}
    assert aa.main(['codex-notify', '--log', str(log), json.dumps(payload)]) == 0
    assert aa.read_log(log)[0]['input_messages'] == ['Plot it']


def test_unknown_format_refused(tmp_path):
    with pytest.raises(ValueError):
        aa.parse(jsonl(tmp_path / 'x.jsonl', [{'foo': 1}]))
