"""Per-prompt audit records for agent sessions (Claude Code and Codex).

Each record carries the prompt text, the model build the agent CLI reported,
the prompt timestamp, token counts and a tool-call summary. Records come from
transcripts named explicitly by path, and from hook events appended to a run's
audit log while the session runs. Nothing here reads a transcript that was not
named by the caller or by the hook payload, and a missing value stays null.

Commands:
  ravel agent-audit collect --transcript FILE ... --out DIR
  ravel agent-audit build --log LOG [--transcript FILE ...] --out DIR
  ravel agent-audit hook --log LOG          (Claude Code UserPromptSubmit/Stop/SubagentStop)
  ravel agent-audit codex-notify --log LOG PAYLOAD   (Codex notify program)
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

SCHEMA_VERSION = 1
USAGE_KEYS = ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens', 'output_tokens', 'total_tokens')
SKIPPED_PROMPT_PREFIXES = ('<local-command-stdout>', '<local-command-stderr>', '[Request interrupted')


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def pin(path):
    path = Path(path).absolute()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _lines(path):
    rows = []
    with Path(path).open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError as exc:
                raise ValueError(f'{path}:{number}: transcript line is not JSON') from exc
            if type(value) is dict:
                rows.append(value)
    return rows


def detect(rows):
    """Codex rollouts wrap every line in {timestamp, type, payload}."""
    for row in rows[:20]:
        if row.get('type') in ('session_meta', 'turn_context', 'response_item', 'event_msg') and 'payload' in row:
            return 'codex'
        if row.get('type') in ('user', 'assistant', 'summary', 'system') or 'message' in row:
            return 'claude-code'
    raise ValueError('unrecognised agent transcript format')


def _empty_usage():
    return {key: 0 for key in USAGE_KEYS}


def _add(total, usage):
    for key in USAGE_KEYS:
        total[key] += usage[key]


def _claude_usage(usage):
    if type(usage) is not dict:
        return None
    fresh = int(usage.get('input_tokens') or 0)
    created = int(usage.get('cache_creation_input_tokens') or 0)
    read = int(usage.get('cache_read_input_tokens') or 0)
    output = int(usage.get('output_tokens') or 0)
    total_input = fresh + created + read
    return {'input_tokens': total_input, 'cached_input_tokens': read, 'cache_creation_input_tokens': created,
            'output_tokens': output, 'total_tokens': total_input + output}


def _claude_prompt(message):
    if type(message) is not dict or message.get('role') != 'user':
        return None
    content = message.get('content')
    if type(content) is str:
        text = content
    elif type(content) is list:
        if any(type(b) is dict and b.get('type') == 'tool_result' for b in content):
            return None
        text = '\n'.join(b.get('text', '') for b in content if type(b) is dict and b.get('type') == 'text')
    else:
        return None
    if not text.strip() or text.lstrip().startswith(SKIPPED_PROMPT_PREFIXES):
        return None
    return text


def _record(agent, source, session, stream, index, timestamp, prompt):
    return {'schema_version': SCHEMA_VERSION, 'agent': agent, 'session_id': session.get('id'),
            'cli_version': session.get('cli_version'), 'stream': stream['id'], 'sidechain': stream['sidechain'],
            'prompt_index': index, 'timestamp': timestamp, 'prompt': prompt, 'models': [], 'model': None,
            'usage': _empty_usage(), 'usage_reported': False, 'assistant_messages': 0, 'tool_calls': {},
            'source': source}


def _finish(record, models, tools):
    record['models'] = sorted(models)
    record['model'] = record['models'][0] if len(record['models']) == 1 else (
        max(models, key=models.get) if models else None)
    from .prompt_log import exact_model
    record['model_requested'] = record.get('model_requested')
    record['model_reported'] = record['model']
    record['model_build_exact'] = exact_model(record['model'])
    record['prompt_sha256'] = hashlib.sha256(record['prompt'].encode('utf-8')).hexdigest()
    record['tool_calls'] = dict(sorted(tools.items()))
    if not record['usage_reported']:
        record['usage'] = {key: None for key in USAGE_KEYS}
    return record


def parse_claude(path):
    """Claude Code JSONL: one row per prompt, usage deduplicated by message id."""
    path = Path(path).absolute()
    rows = _lines(path)
    source = pin(path)
    streams = {}
    session = {'id': None, 'cli_version': None}
    message_sums = _empty_usage()
    for row in rows:
        session['id'] = session['id'] or row.get('sessionId')
        session['cli_version'] = session['cli_version'] or row.get('version')
        key = (bool(row.get('isSidechain')), row.get('agentId') or '')
        stream = streams.setdefault(key, {'id': ('sidechain:' + key[1]) if key[0] else 'main', 'sidechain': key[0],
                                          'records': [], 'messages': {}, 'current': None})
        kind = row.get('type')
        if kind == 'user' and not row.get('isMeta'):
            text = _claude_prompt(row.get('message'))
            if text is not None:
                record = _record('claude-code', source, session, stream, len(stream['records']) + 1,
                                 row.get('timestamp'), text)
                stream['records'].append((record, Counter(), Counter()))
                stream['current'] = len(stream['records']) - 1
        elif kind == 'assistant' and type(row.get('message')) is dict:
            message = row['message']
            identity = message.get('id') or row.get('uuid')
            owner = stream['current']
            entry = stream['messages'].setdefault(identity, {'owner': owner, 'model': None, 'usage': None, 'tools': Counter()})
            model = message.get('model')
            if type(model) is str and model and not model.startswith('<'):
                entry['model'] = model
            usage = _claude_usage(message.get('usage'))
            if usage is not None:
                entry['usage'] = usage  # Streaming rows repeat usage; the last row is complete.
            for block in message.get('content') or []:
                if type(block) is dict and block.get('type') == 'tool_use':
                    entry['tools'][block.get('name') or 'unknown'] += 1
    records = []
    for stream in streams.values():
        for entry in stream['messages'].values():
            if entry['usage'] is not None:
                _add(message_sums, entry['usage'])
            if entry['owner'] is None:
                continue
            record, models, tools = stream['records'][entry['owner']]
            record['assistant_messages'] += 1
            if entry['model']:
                models[entry['model']] += 1
            tools.update(entry['tools'])
            if entry['usage'] is not None:
                record['usage_reported'] = True
                _add(record['usage'], entry['usage'])
        records.extend(_finish(r, m, t) for r, m, t in stream['records'])
    records.sort(key=lambda r: (r['sidechain'], r['stream'], r['prompt_index']))
    return {'agent': 'claude-code', 'source': source, 'session_id': session['id'], 'records': records,
            'message_usage_sum': message_sums}


def _codex_usage(info):
    if type(info) is not dict:
        return None
    total = info.get('total_token_usage')
    if type(total) is not dict:
        return None
    return {'input_tokens': int(total.get('input_tokens') or 0),
            'cached_input_tokens': int(total.get('cached_input_tokens') or 0),
            'cache_creation_input_tokens': 0,
            'output_tokens': int(total.get('output_tokens') or 0),
            'reported_total_tokens': total.get('total_tokens')}


def parse_codex(path):
    """Codex rollout JSONL: prompts are user_message events; usage is the cumulative-counter delta."""
    path = Path(path).absolute()
    rows = _lines(path)
    source = pin(path)
    session = {'id': None, 'cli_version': None}
    stream = {'id': 'main', 'sidechain': False}
    records = []
    model = None
    baseline = None
    last = None

    def close():
        if not records:
            return
        record, models, tools = records[-1]
        if last is not None:
            start = baseline or {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0}
            delta = {key: last[key] - start[key] for key in ('input_tokens', 'cached_input_tokens', 'output_tokens')}
            if any(value for value in delta.values()):
                record['usage_reported'] = True
                record['usage'] = {'input_tokens': delta['input_tokens'], 'cached_input_tokens': delta['cached_input_tokens'],
                                   'cache_creation_input_tokens': 0, 'output_tokens': delta['output_tokens'],
                                   'total_tokens': delta['input_tokens'] + delta['output_tokens']}

    for row in rows:
        payload = row.get('payload') if type(row.get('payload')) is dict else {}
        kind = row.get('type')
        if kind == 'session_meta':
            session['id'] = payload.get('id') or session['id']
            session['cli_version'] = payload.get('cli_version') or session['cli_version']
        elif kind == 'turn_context':
            model = payload.get('model') or model
        elif kind == 'event_msg' and payload.get('type') == 'user_message':
            text = payload.get('message')
            if type(text) is str and text.strip():
                close()
                baseline = dict(last) if last is not None else None
                record = _record('codex', source, session, stream, len(records) + 1, row.get('timestamp'), text)
                records.append((record, Counter(), Counter()))
        elif kind == 'event_msg' and payload.get('type') == 'token_count':
            usage = _codex_usage(payload.get('info'))
            if usage is not None:
                last = usage
        elif kind == 'event_msg' and payload.get('type') == 'agent_message' and records:
            records[-1][0]['assistant_messages'] += 1
            if model:
                records[-1][1][model] += 1
        elif kind == 'response_item' and records:
            item = payload.get('type')
            if item in ('function_call', 'custom_tool_call', 'local_shell_call', 'web_search_call'):
                records[-1][2][payload.get('name') or item] += 1
            if item == 'message' and payload.get('role') == 'assistant' and model:
                records[-1][1][model] += 1
    close()
    totals = _empty_usage()
    if last is not None:
        totals.update(input_tokens=last['input_tokens'], cached_input_tokens=last['cached_input_tokens'],
                      output_tokens=last['output_tokens'], total_tokens=last['input_tokens'] + last['output_tokens'])
    return {'agent': 'codex', 'source': source, 'session_id': session['id'],
            'records': [_finish(r, m, t) for r, m, t in records], 'message_usage_sum': totals}


def parse(path):
    rows = _lines(path)
    if rows and 'ravel' in rows[0] and 'prompt_index' in rows[0]:
        from .worker_audit import parse_transcript
        return parse_transcript(path)
    return parse_codex(path) if detect(rows) == 'codex' else parse_claude(path)


def _totals(records):
    total = _empty_usage()
    for record in records:
        if record['usage_reported']:
            _add(total, record['usage'])
    return total


def collect(paths):
    """Parse every named transcript; check per-prompt sums against per-message sums."""
    sessions = [parse(p) for p in paths]
    records = [r for s in sessions for r in s['records']]
    checks = []
    for s in sessions:
        attributed = _totals(s['records'])
        unattributed = {k: s['message_usage_sum'][k] - attributed[k] for k in USAGE_KEYS}
        checks.append({'source': s['source']['path'], 'session_id': s['session_id'],
                       'prompt_usage_sum': attributed, 'message_usage_sum': s['message_usage_sum'],
                       'usage_outside_prompts': unattributed,
                       'consistent': all(v >= 0 for v in unattributed.values())})
    records.sort(key=lambda r: (r['timestamp'] or '', r['session_id'] or '', r['stream'], r['prompt_index']))
    return {'schema_version': SCHEMA_VERSION, 'kind': 'agent-session-audit', 'generated_utc': utc_now(),
            'sources': [s['source'] for s in sessions], 'records': records, 'totals': _totals(records),
            'checks': checks,
            'scope': 'Prompts, reported model builds, timestamps, token counts and tool-call counts as recorded by the agent CLI.'}


def render_markdown(audit):
    lines = ['# Agent prompt log', '',
             f"{len(audit['records'])} prompts from {len(audit['sources'])} transcript(s). "
             'Token counts are the counts reported by the agent CLI; a dash means the CLI did not report one.', '',
             '| # | Time (UTC) | Agent | Session | Model build | Input tokens | Cached input | Output tokens | Tool calls |',
             '|---|---|---|---|---|---|---|---|---|']
    for number, r in enumerate(audit['records'], 1):
        usage = r['usage']
        cell = lambda key: '-' if usage[key] is None else str(usage[key])
        tools = ', '.join(f'{k}×{v}' for k, v in r['tool_calls'].items()) or '-'
        session = (r['session_id'] or '-') + (' (subagent)' if r['sidechain'] else '')
        lines.append(f"| {number} | {r['timestamp'] or '-'} | {r['agent']} | {session} | {r['model'] or '-'} | "
                     f"{cell('input_tokens')} | {cell('cached_input_tokens')} | {cell('output_tokens')} | {tools} |")
    total = audit['totals']
    lines += ['', f"Total: {total['input_tokens']} input tokens ({total['cached_input_tokens']} cached), "
              f"{total['output_tokens']} output tokens.", '', '## Prompts', '']
    for number, r in enumerate(audit['records'], 1):
        lines += [f"### {number}. {r['timestamp'] or '-'} — {r['model'] or 'model not reported'}", '',
                  '```text', r['prompt'].replace('```', '` ` `'), '```', '']
    return '\n'.join(lines)


def _write_new(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(text)
    return pin(path)


def write(audit, out):
    """Write agent-audit.jsonl, agent-audit.md and agent-audit.json into a new directory."""
    out = Path(out).absolute()
    if out.exists() and any(out.iterdir()):
        raise ValueError('audit output directory must be new or empty')
    rows = ''.join(json.dumps(r, sort_keys=True, allow_nan=False) + '\n' for r in audit['records'])
    files = [_write_new(out / 'agent-audit.jsonl', rows), _write_new(out / 'agent-audit.md', render_markdown(audit))]
    summary = {k: v for k, v in audit.items() if k != 'records'}
    summary['files'] = files
    files.append(_write_new(out / 'agent-audit.json', json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + '\n'))
    return {'files': files, 'prompts': len(audit['records']), 'totals': audit['totals']}


# ---------------------------------------------------------------- live hooks

def _append(log, value):
    """Append one JSON line under an exclusive lock; never rewrite earlier lines."""
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, sort_keys=True, allow_nan=False) + '\n'
    with log.open('a', encoding='utf-8') as stream:
        try:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def read_log(log):
    return _lines(log) if Path(log).exists() else []


def _recorded_turns(log):
    return {(e.get('source_path'), e['record'].get('stream'), e['record'].get('prompt_index'))
            for e in read_log(log) if e.get('event') == 'turn_recorded' and type(e.get('record')) is dict}


def handle_hook(event, log):
    """Claude Code hook event → audit log lines. Returns the events appended."""
    name = event.get('hook_event_name')
    appended = []
    if name == 'UserPromptSubmit':
        entry = {'event': 'prompt_submitted', 'timestamp': utc_now(), 'agent': 'claude-code',
                 'session_id': event.get('session_id'), 'prompt': event.get('prompt'),
                 'transcript_path': event.get('transcript_path'), 'cwd': event.get('cwd')}
        _append(log, entry)
        appended.append(entry)
    elif name in ('Stop', 'SubagentStop'):
        transcript = event.get('agent_transcript_path') or event.get('transcript_path')
        if not transcript or not Path(transcript).is_file():
            entry = {'event': 'turn_unrecorded', 'timestamp': utc_now(), 'hook': name,
                     'session_id': event.get('session_id'), 'transcript_path': transcript,
                     'reason': 'transcript not readable'}
            _append(log, entry)
            return [entry]
        parsed = parse(transcript)
        seen = _recorded_turns(log)
        for record in parsed['records']:
            key = (parsed['source']['path'], record['stream'], record['prompt_index'])
            if key in seen:
                continue
            entry = {'event': 'turn_recorded', 'timestamp': utc_now(), 'hook': name,
                     'source_path': parsed['source']['path'], 'record': record}
            _append(log, entry)
            appended.append(entry)
    return appended


def handle_codex_notify(payload, log):
    entry = {'event': 'codex_turn_complete', 'timestamp': utc_now(), 'agent': 'codex',
             'notification_type': payload.get('type'), 'thread_id': payload.get('thread-id') or payload.get('thread_id'),
             'turn_id': payload.get('turn-id') or payload.get('turn_id'),
             'input_messages': payload.get('input-messages') or payload.get('input_messages') or [],
             'cwd': payload.get('cwd')}
    _append(log, entry)
    return entry


def build(log, transcripts=(), out=None):
    """Audit from named transcripts plus the transcripts the hook log names.

    Turns recorded by hooks whose transcript is gone are kept from the log.
    Hook prompts never matched to a transcript prompt are listed as gaps.
    """
    events = read_log(log)
    named = [Path(p).absolute() for p in transcripts]
    for e in events:
        path = e.get('transcript_path') or e.get('source_path')
        if path and Path(path).is_file() and Path(path).absolute() not in named:
            named.append(Path(path).absolute())
    audit = collect(named)
    present = {r['source']['path'] for r in audit['records']} | {s['path'] for s in audit['sources']}
    kept = [e['record'] for e in events if e.get('event') == 'turn_recorded' and e.get('source_path') not in present]
    unique = {}
    for record in kept:
        unique[(record['source']['path'], record['stream'], record['prompt_index'])] = record
    audit['records'].extend(unique.values())
    audit['records'].sort(key=lambda r: (r['timestamp'] or '', r['session_id'] or '', r['stream'], r['prompt_index']))
    audit['totals'] = _totals(audit['records'])
    texts = {(r['session_id'], r['prompt']) for r in audit['records']}
    audit['gaps'] = [{'timestamp': e['timestamp'], 'session_id': e.get('session_id'), 'prompt': e.get('prompt')}
                     for e in events if e.get('event') == 'prompt_submitted'
                     and (e.get('session_id'), e.get('prompt')) not in texts]
    audit['hook_log'] = pin(log) if Path(log).exists() else None
    if out is not None:
        return {**write(audit, out), 'gaps': len(audit['gaps'])}
    return audit


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel agent-audit', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    c = commands.add_parser('collect', help='parse named transcripts into a prompt log')
    c.add_argument('--transcript', type=Path, action='append', required=True)
    c.add_argument('--out', type=Path, required=True)
    b = commands.add_parser('build', help='combine a hook log with named transcripts')
    b.add_argument('--log', type=Path, required=True)
    b.add_argument('--transcript', type=Path, action='append', default=[])
    b.add_argument('--out', type=Path, required=True)
    h = commands.add_parser('hook', help='Claude Code hook entry point (reads the event from stdin)')
    h.add_argument('--log', type=Path, required=True)
    n = commands.add_parser('codex-notify', help='Codex notify entry point')
    n.add_argument('--log', type=Path, required=True)
    n.add_argument('payload')
    args = parser.parse_args(argv)
    if args.command == 'hook':
        # A hook must never block or alter the session; it prints nothing.
        try:
            handle_hook(json.loads(sys.stdin.read() or '{}'), args.log)
        except Exception as exc:  # noqa: BLE001 - the hook records its own failure
            try:
                _append(args.log, {'event': 'hook_error', 'timestamp': utc_now(), 'message': str(exc)[:500]})
            except OSError:
                pass
        return 0
    if args.command == 'codex-notify':
        try:
            handle_codex_notify(json.loads(args.payload), args.log)
        except Exception as exc:  # noqa: BLE001
            try:
                _append(args.log, {'event': 'hook_error', 'timestamp': utc_now(), 'message': str(exc)[:500]})
            except OSError:
                pass
        return 0
    try:
        result = write(collect(args.transcript), args.out) if args.command == 'collect' else build(args.log, args.transcript, args.out)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'agent audit: {exc}\n')
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
