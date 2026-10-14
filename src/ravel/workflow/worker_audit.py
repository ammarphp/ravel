"""Read every code-spawned worker record through the transport-neutral transcript record.

No role allowlist filters the census. Failed, ambiguous and incomplete sessions
remain visible; missing model or token evidence is reported as unknown, not zero.
"""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path


def _time(value):
    if type(value) is not str or datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('timezone-aware transcript timestamp required')


def parse_transcript(path):
    from . import agent_audit as aa
    rows = aa._lines(path); source = aa.pin(path)
    if not rows:
        raise ValueError('worker transcript has no prompt records')
    seen = set()
    for record in rows:
        if record.get('schema_version') != 1 or type(record.get('ravel')) is not dict:
            raise ValueError('transport-neutral worker transcript record required')
        ravel = record['ravel']
        if not all(k in ravel for k in ('node_id', 'attempt', 'role_id', 'receipt_sha256')):
            raise ValueError('worker transcript identity required')
        if not all(type(record.get(k)) is str and record[k].strip() for k in ('agent', 'stream', 'prompt', 'session_id')):
            raise ValueError('worker prompt/session identity required')
        if type(record.get('prompt_index')) is not int or record['prompt_index'] < 1:
            raise ValueError('positive prompt index required')
        key = record['stream'], record['prompt_index']
        if key in seen: raise ValueError('duplicate worker prompt record')
        seen.add(key); _time(record['timestamp'])
        if type(record.get('usage_reported')) is not bool or type(record.get('usage')) is not dict:
            raise ValueError('explicit worker token accounting required')
        usage = record['usage']
        for k in aa.USAGE_KEYS:
            if k not in usage or usage[k] is not None and (type(usage[k]) is not int or usage[k] < 0):
                raise ValueError('nonnegative or unknown worker tokens required')
        if record['usage_reported']:
            if any(usage[k] is None for k in aa.USAGE_KEYS) or usage['input_tokens'] + usage['output_tokens'] != usage['total_tokens']:
                raise ValueError('complete consistent reported worker token counts required')
        else:
            record['usage'] = {k: None for k in aa.USAGE_KEYS}
        if type(record.get('tool_calls')) is not dict or type(record.get('models')) is not list:
            raise ValueError('model and tool census required')
        record['source'] = source
    session_ids = {r['session_id'] for r in rows}
    if len(session_ids) != 1: raise ValueError('one worker session per transcript required')
    totals = aa._totals(rows)
    return {'agent': rows[0]['agent'], 'source': source, 'session_id': rows[0]['session_id'],
            'records': rows, 'message_usage_sum': totals}


def _inside(root, path):
    path = Path(path)
    path = path if path.is_absolute() else root / path
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root):
        raise ValueError('worker record symlink refused')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('worker record outside run refused')
    return path.absolute()


def build(rundir):
    from . import agent_audit as aa
    root = Path(rundir).absolute(); sessions = []; sources = []; gaps = []; valid_transcripts = []
    receipts = sorted(root.glob('**/agent-work/*/*/receipt.json'))
    transcripts = sorted(root.glob('**/agent-work/*/*/transcript.jsonl'))
    accounted = set()
    for path in receipts:
        session = {'receipt': None, 'node_id': path.parent.parent.name, 'attempt': path.parent.name,
                   'role_id': None, 'session_id': None, 'model_build': None, 'timestamp': None,
                   'tokens': {k: None for k in aa.USAGE_KEYS}, 'graph': None, 'status': 'unreadable', 'transcript': None}
        try:
            path = _inside(root, path); session['receipt'] = aa.pin(path); sources.append(session['receipt'])
            receipt = json.loads(path.read_text())
            if receipt.get('kind') != 'agent-worker-receipt' or receipt.get('schema_version') not in (1, 2):
                raise ValueError('agent-worker-receipt schema required')
            session.update(node_id=receipt['node_id'], attempt=receipt['attempt'], role_id=receipt['role']['id'],
                           session_id=receipt.get('session_id'), model_build=receipt.get('model', {}).get('observed'),
                           timestamp=receipt.get('started_utc'), graph=deepcopy(receipt.get('graph')), status=receipt['status'])
            transcript = receipt.get('transcript')
            if not transcript: raise ValueError('missing transcript pin')
            target = Path(transcript['path'])
            target = target if target.is_absolute() else path.parents[3] / target
            target = _inside(root, target); accounted.add(target)
            pin = aa.pin(target); session['transcript'] = pin; sources.append(pin)
            if pin['sha256'] != transcript['sha256'] or 'size' in transcript and pin['size'] != transcript['size']:
                raise ValueError('worker transcript changed')
            parsed = parse_transcript(target)
            for record in parsed['records']:
                identity = record['ravel']
                if (identity['node_id'], identity['attempt'], identity['role_id'], record['session_id']) != (
                        receipt['node_id'], receipt['attempt'], receipt['role']['id'], receipt.get('session_id')):
                    raise ValueError('worker transcript/receipt identity differs')
            models = sorted({r['model'] for r in parsed['records'] if r.get('model')})
            if session['model_build'] is not None and models and models != [session['model_build']]:
                raise ValueError('worker transcript/receipt model build differs')
            session['model_build'] = session['model_build'] or (models[0] if len(models) == 1 else None)
            session['models'] = models
            session['timestamp'] = session['timestamp'] or parsed['records'][0]['timestamp']; _time(session['timestamp'])
            if all(r['usage_reported'] for r in parsed['records']):
                session['tokens'] = parsed['message_usage_sum']
                usage = receipt.get('usage', {})
                if usage.get('reported') and any(usage.get(k) != session['tokens'][k] for k in ('input_tokens', 'output_tokens')):
                    raise ValueError('worker transcript/receipt token counts differ')
            if not session['model_build'] or session['tokens']['total_tokens'] is None:
                gaps.append({'node_id': session['node_id'], 'reason': 'model build or token accounting unknown'})
            valid_transcripts.append(str(target))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            gaps.append({'node_id': session['node_id'], 'reason': str(exc)})
        sessions.append(session)
    for path in transcripts:
        if path.absolute() not in accounted:
            gaps.append({'node_id': path.parent.parent.name, 'reason': 'transcript has no worker receipt', 'path': str(path)})
            session = {'receipt': None, 'transcript': None, 'node_id': path.parent.parent.name,
                       'attempt': path.parent.name, 'role_id': None, 'session_id': None, 'model_build': None,
                       'timestamp': None, 'tokens': {k: None for k in aa.USAGE_KEYS}, 'graph': None, 'status': 'unreceipted'}
            try:
                parsed = parse_transcript(_inside(root, path)); first = parsed['records'][0]
                session.update(transcript=parsed['source'], role_id=first['ravel']['role_id'], session_id=first['session_id'],
                               model_build=first.get('model'), timestamp=first['timestamp'])
                if all(r['usage_reported'] for r in parsed['records']): session['tokens'] = parsed['message_usage_sum']
                sources.append(parsed['source']); valid_transcripts.append(str(path.absolute()))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                gaps.append({'path': str(path), 'reason': 'unreceipted transcript unreadable: ' + str(exc)})
            sessions.append(session)
    # Older code-spawned graph model calls predate the normalized worker seam.
    # Retain them as session rows, including failed calls without usage evidence.
    known_sessions = {row['session_id'] for row in sessions if row['session_id']}
    for state_path in sorted(root.glob('**/graph_state.json')):
        try:
            state = json.loads(_inside(root, state_path).read_text()); sources.append(aa.pin(state_path))
            spec_path = state_path.with_name('graph_spec.json')
            spec = json.loads(_inside(root, spec_path).read_text()); sources.append(aa.pin(spec_path))
            roles = {n['id']: n.get('role') for n in spec['nodes']}
            for call_id, call in sorted(state.get('calls', {}).items()):
                if call.get('kind') != 'model': continue
                path = _inside(root, state_path.parent / 'calls' / (call_id + '.json'))
                pin = aa.pin(path) if path.exists() else None
                if pin: sources.append(pin)
                saved = json.loads(path.read_text()) if pin else {}
                result = saved.get('result', {}); transport = result.get('transport', {})
                host_record = transport.get('session_receipt', {})
                launcher = host_record.get('launcher_receipt', {})
                reported = launcher.get('cli_reported', {})
                session_id = reported.get('session_id') or transport.get('cli_session_id')
                if session_id and session_id in known_sessions: continue
                usage = reported.get('usage') or result.get('usage', {})
                if type(usage) is dict and type(usage.get('tokens')) is dict: usage = usage['tokens']
                tokens = {k: usage.get(k) for k in aa.USAGE_KEYS} if type(usage) is dict else {k: None for k in aa.USAGE_KEYS}
                if tokens['input_tokens'] is not None and tokens['output_tokens'] is not None:
                    tokens['total_tokens'] = tokens['input_tokens'] + tokens['output_tokens']
                session = {'receipt': pin, 'node_id': call['node_id'], 'attempt': call.get('attempt_id'),
                           'role_id': roles.get(call['node_id']), 'session_id': session_id,
                           'model_build': reported.get('observed_model') or result.get('observed_model'),
                           'timestamp': launcher.get('process', {}).get('started_utc'), 'tokens': tokens,
                           'graph': {'id': state.get('graph_id'), 'version': state.get('graph_revision'), 'thread_id': None},
                           'status': saved.get('status', call.get('status', 'unknown')), 'transcript': None}
                sessions.append(session)
                gaps.append({'node_id': session['node_id'], 'reason': 'legacy graph call lacks transport-neutral worker transcript; unknown fields retained'})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            gaps.append({'path': str(state_path), 'reason': 'graph session census unreadable: ' + str(exc)})
    return {'schema_version': 1, 'kind': 'worker-session-audit', 'sessions': sessions, 'sources': sources,
            'transcripts': sorted(set(valid_transcripts)), 'gaps': gaps, 'complete': not gaps,
            'scope': 'All recorded agent-work sessions, without role filtering; accounting is reported evidence, not physics qualification.'}
