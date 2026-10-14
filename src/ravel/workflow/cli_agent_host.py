"""Answer RAVEL model requests with a fresh agent CLI session.

Supported CLIs: Claude Code (``claude -p``), Codex (``codex exec``), Gemini CLI
(``gemini -p``, for AI Studio keys and Vertex AI) and Google Antigravity
(``agy -p``, for consumer Google accounts). Each request runs one new
non-interactive session in an empty temporary directory, with the argv of the
CLI's ``*-cli-oneshot`` transport declaration and only the environment names
that declaration passes. No earlier conversation and no parent transcript is
passed; the session receives only the request's instructions, its output schema
and its prepared context.

Before launch the CLI needs a current probe (``ravel transport probe <id>``) of the
same executable: the launcher's sha256 must equal the probed one. The model id and
effort are validated before they reach argv, and extra arguments come from a closed
allowlist. This launcher writes a session receipt: the executable path and sha256,
the exact argv digest, the process facts it observed, the environment names, the
declaration digest and the configuration evidence. What the CLI reports about itself
(session id, model, usage, configuration events) stays in ``cli_reported``.

User configuration. Claude runs with ``--setting-sources project --safe-mode``
and ``--strict-mcp-config`` in an empty directory (not ``--bare``, which drops
the subscription login); admin-managed settings stay in force and their digest is
recorded. Codex runs with a fresh ``CODEX_HOME`` holding a copy of ``auth.json``
and a generated ``config.toml``. Gemini CLI and Antigravity run with a fresh
``HOME`` holding only their login material, but have no flag that excludes
settings or instructions found from their working directory, and keep read tools.
Every answer records ``user_configuration_loaded``.

Three uses:
  serve        the AgentHost command-adapter program (JSON request on stdin,
               JSON result and session receipt on stdout); select it with host config
               {"type": "agent-cli", "agent": "claude" | "codex" | "gemini" | "antigravity" | "auto"}.
  answer       answer one prepared external request file (agent-graph
               prepare-external, judgment prepare-role --external) and write
               the response and usage evidence for deliver-external.
  answer-graph answer and deliver every external node of a graph that is
               awaiting a response, when an agent CLI is installed.

This is not an OS sandbox: the CLI runs as the user with the user's own
agent login. A machine answer is recorded as a model answer, never as human
or physicist review.
"""
import argparse
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from . import transport_registry, transport_receipt

AGENTS = ('claude', 'codex', 'antigravity', 'gemini')
LAUNCHERS = {'claude': 'claude', 'codex': 'codex', 'antigravity': 'agy', 'gemini': 'gemini'}
ONESHOT = {'claude': 'claude-cli-oneshot', 'codex': 'codex-cli-oneshot',
           'antigravity': 'antigravity-cli-oneshot', 'gemini': 'gemini-cli-oneshot'}
DEFAULT_TIMEOUT = 1800
PASSED_ENVIRONMENT = transport_registry.BASE_ENVIRONMENT + ('CLAUDE_CONFIG_DIR', 'CODEX_HOME')
# The closed effort values each CLI accepts; an effort outside its set is refused, never dropped.
EFFORTS = {'claude': ('low', 'medium', 'high', 'xhigh', 'max'),
           'antigravity': ('low', 'medium', 'high', 'xhigh', 'max'),
           'codex': ('minimal', 'low', 'medium', 'high', 'xhigh'),
           'gemini': ()}
MAX_ARGV_PROMPT = 512 * 1024
ARGV_MARGIN = 64 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
# Extra arguments are a closed allowlist; everything else is refused before launch.
ALLOWED_EXTRA = {'claude': ('--verbose',), 'codex': (), 'antigravity': (), 'gemini': ()}
# Flags named when an extra argument is refused because it can re-enable tools, permissions or configuration.
DENIED_EXTRA = {'claude': ('--setting-sources', '--settings', '--add-dir', '--mcp-config', '--plugin-dir', '--agents',
                           '--continue', '--resume', '-c', '-r', '--tools', '--allowedTools', '--allowed-tools',
                           '--disallowedTools', '--permission-mode', '--dangerously-skip-permissions',
                           '--system-prompt', '--system-prompt-file', '--append-system-prompt',
                           '--append-system-prompt-file', '--bare', '--restricted'),
                'codex': ('--profile', '-p', '--cd', '-C', '--add-dir', 'resume', '-c', '--config', '-s', '--sandbox',
                          '--oss', '--full-auto', '--dangerously-bypass-approvals-and-sandbox', '--enable',
                          '--disable')}
MANAGED_SETTINGS = ('/Library/Application Support/ClaudeCode/managed-settings.json',
                    '/etc/claude-code/managed-settings.json')
# Login material copied into a fresh HOME (never read or logged); everything else in HOME stays out.
LOGIN_MATERIAL = {'gemini': ('.config/gcloud/application_default_credentials.json',),
                  'antigravity': ('.gemini/oauth_creds.json', '.gemini/google_accounts.json')}
DOTENV_CANDIDATES = ('.env', '.gemini/.env')
WRAPPER_MODULE = 'ravel.workflow.cli_agent_host'


class AgentCLIError(RuntimeError):
    """A failed or unparseable agent CLI answer; nothing is delivered.

    ``code`` is one of refused, unusable, timeout, exit, output, parse, schema. Messages never carry the
    CLI's own stderr or error text, which can echo credentials; only their sizes and digests.
    """

    def __init__(self, message, code='refused'):
        super().__init__(message)
        self.code = code


def module_sha256():
    """Digest of this launcher module, recorded as the receipt writer."""
    return transport_registry.file_sha256(Path(__file__).resolve())


def _utc():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def detect(environment=None):
    """Installed agent CLIs on PATH, with the version each reports.

    Each ``--version`` runs with that launcher's declared environment only, never the full one.
    """
    source = dict(os.environ if environment is None else environment)
    found = {}
    for agent in AGENTS:
        env, _ = transport_registry.child_environment(transport_registry.load(ONESHOT[agent]), source)
        path = shutil.which(LAUNCHERS[agent], path=env.get('PATH'))
        version = None
        if path:
            try:
                done = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=30, env=env,
                                      stdin=subprocess.DEVNULL)
                text = (done.stdout or done.stderr).strip() if done.returncode == 0 else ''
                version = text.splitlines()[0][:200] if text else None
            except (OSError, subprocess.SubprocessError, IndexError):
                version = None
        found[agent] = {'path': path, 'version': version} if path else None
    return found


def choose(agent, environment=None, preferences=None):
    """A concrete agent: the named one if installed; for ``auto`` the run preferences, else the fixed order.

    ``preferences`` is an agent-preferences record; its first family list that names one-shot
    transports orders the choice. Installed launchers are found on PATH without running them.
    """
    path = dict(os.environ if environment is None else environment).get('PATH')
    if agent in AGENTS:
        if shutil.which(LAUNCHERS[agent], path=path) is None:
            raise AgentCLIError(f'{agent} CLI ({LAUNCHERS[agent]}) is not installed on PATH')
        return agent
    if agent != 'auto':
        raise AgentCLIError('agent must be one of ' + ', '.join(AGENTS) + ' or auto')
    order = list(AGENTS)
    if preferences is not None:
        by_id = {v: k for k, v in ONESHOT.items()}
        ranked = [by_id[t] for family in (preferences.get('families') or {}).values() for t in family if t in by_id]
        order = list(dict.fromkeys(ranked)) or order
    installed = [a for a in order if shutil.which(LAUNCHERS[a], path=path)]
    if not installed:
        raise AgentCLIError('no agent CLI (' + ', '.join(LAUNCHERS[a] for a in AGENTS) + ') is installed on PATH')
    return installed[0]


def build_prompt(parameters, context):
    schema = parameters.get('output_schema')
    lines = ['You are a fresh, independent session answering one structured request from RAVEL.',
             'You have no earlier conversation. Use only the instructions and the context below.',
             'Reply with exactly one JSON object' + (' that matches the output schema' if schema else '') +
             ', with no prose before or after it.', '', '## Instructions', '', parameters['instructions'], '']
    if schema is not None:
        lines += ['## Output JSON schema', '', json.dumps(schema, indent=2, sort_keys=True), '']
    lines += ['## Context', '', json.dumps(context, indent=2, sort_keys=True, ensure_ascii=False)]
    return '\n'.join(lines)


def extract_json(text):
    """The answer's single JSON object, allowing one surrounding code fence."""
    body = (text or '').strip()
    if body.startswith('```'):
        body = body.split('\n', 1)[1] if '\n' in body else ''
        body = body.rsplit('```', 1)[0]
    body = body.strip()
    if not body.startswith('{'):
        start, end = body.find('{'), body.rfind('}')
        if start < 0 or end <= start:
            raise AgentCLIError('agent answer contains no JSON object', 'parse')
        body = body[start:end + 1]
    try:
        value = json.loads(body)
    except ValueError as exc:
        raise AgentCLIError('agent answer is not valid JSON', 'parse') from exc
    if type(value) is not dict:
        raise AgentCLIError('agent answer must be a JSON object', 'parse')
    return value


def _members(pgid):
    from .execution import process_group_members
    try:
        return process_group_members(pgid)
    except (OSError, subprocess.SubprocessError):
        return None


def _stop_group(process, *, own_group):
    """Stop the CLI and every member of its process group; True when none remains.

    With ``own_group`` false the CLI shares this launcher's group (the AgentHost wrapper case), so
    the launcher ignores SIGTERM while it signals the group, then kills each remaining member by pid.
    """
    pgid = process.pid if own_group else os.getpgid(0)
    me = os.getpid()
    previous = None
    try:
        if not own_group:
            previous = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            process.poll()
            members = [m for m in (_members(pgid) or []) if m != me]
            if not members and process.returncode is not None:
                return True
            time.sleep(.05)
        for member in [m for m in (_members(pgid) or []) if m != me] + ([process.pid] if process.poll() is None else []):
            try:
                os.kill(member, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return False
        remaining = _members(pgid)
        return remaining is not None and not [m for m in remaining if m != me]
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def _run(argv, prompt, *, cwd, env, timeout, own_group=True, max_bytes=MAX_OUTPUT_BYTES):
    """Run one CLI process with a byte bound on its output; return (stdout text, process facts).

    ``own_group`` puts the CLI in a new process group (direct use). Under the AgentHost wrapper the
    CLI stays in the wrapper's group, so cancelling the wrapper's group stops the CLI too. On timeout
    or an over-long output every member of the group is stopped before this returns.
    """
    data = (prompt or '').encode()
    started = _utc()
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=cwd, env=env, start_new_session=own_group)
    out, err, pending, failure = bytearray(), bytearray(), memoryview(data), None
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for stream, event, name in ((process.stdin, selectors.EVENT_WRITE, 'in'),
                                        (process.stdout, selectors.EVENT_READ, 'out'),
                                        (process.stderr, selectors.EVENT_READ, 'err')):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, event, name)
            while selector.get_map() and failure is None:
                if time.monotonic() >= deadline:
                    failure = AgentCLIError(f'agent CLI exceeded its {timeout} s timeout; its effect is unknown', 'timeout')
                    break
                for key, _ in selector.select(min(.1, max(0, deadline - time.monotonic()))):
                    if key.data == 'in':
                        try:
                            pending = pending[os.write(key.fd, pending[:65536]):]
                        except BrokenPipeError:
                            pending = memoryview(b'')
                        if not pending:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                        continue
                    content = os.read(key.fd, 65536)
                    if not content:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    (out if key.data == 'out' else err).extend(content)
                    if len(out) > max_bytes or len(err) > max_bytes:
                        failure = AgentCLIError(f'agent CLI output exceeds its {max_bytes}-byte bound', 'output')
                        break
        while failure is None and process.poll() is None:
            if time.monotonic() >= deadline:
                failure = AgentCLIError(f'agent CLI exceeded its {timeout} s timeout; its effect is unknown', 'timeout')
                break
            time.sleep(.02)
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
    if failure is not None:
        _stop_group(process, own_group=own_group)
        raise failure
    facts = {'pid': process.pid, 'pgid': process.pid if own_group else os.getpgid(0), 'started_utc': started,
             'finished_utc': _utc(), 'exit_status': process.returncode,
             'stdout_sha256': transport_receipt.sha256_bytes(bytes(out)),
             'stderr_sha256': transport_receipt.sha256_bytes(bytes(err)),
             'stdout_bytes': len(out), 'stderr_bytes': len(err)}
    if process.returncode != 0:
        raise AgentCLIError(f'agent CLI exited with status {process.returncode} (stderr {len(err)} bytes, '
                            f'sha256 {facts["stderr_sha256"]}; not shown)', 'exit')
    return bytes(out).decode('utf-8', errors='replace'), facts


def _tokens(input_tokens, output_tokens):
    return {'input_tokens': input_tokens, 'output_tokens': output_tokens, 'total_tokens': input_tokens + output_tokens}


def _config_events(events):
    """The CLI's own configuration report: init events naming memory, plugins or MCP servers."""
    found = []
    for event in events:
        if type(event) is not dict:
            continue
        if event.get('user_configuration_loaded') is True:
            found.append({'type': str(event.get('type')), 'user_configuration_loaded': True})
            continue
        named = sorted(k for k in ('memory_paths', 'plugins', 'mcp_servers') if event.get(k))
        if named:
            found.append({'type': str(event.get('type')), 'subtype': str(event.get('subtype')), 'names': named})
    return found


def _claude(out):
    try:
        document = json.loads(out)
    except ValueError as exc:
        raise AgentCLIError('claude did not return its JSON result envelope', 'parse') from exc
    events = document if type(document) is list else [document]
    if type(document) is list:  # stream-json envelopes end with the result event
        document = next((d for d in reversed(document) if type(d) is dict and d.get('type') == 'result'), {})
    if type(document) is not dict or document.get('is_error') or document.get('subtype') not in (None, 'success'):
        raise AgentCLIError('claude reported an error result', 'exit')
    usage = document.get('usage') if type(document.get('usage')) is dict else None
    tokens = None
    if usage is not None:
        total_input = sum(int(usage.get(k) or 0) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
        tokens = _tokens(total_input, int(usage.get('output_tokens') or 0))
    models = document.get('modelUsage') if type(document.get('modelUsage')) is dict else {}
    observed = max(models, key=lambda m: (models[m] or {}).get('outputTokens', 0)) if models else None
    structured = document.get('structured_output')
    text = json.dumps(structured) if type(structured) is dict else document.get('result')
    init = any(type(e) is dict and e.get('type') == 'system' and e.get('subtype') == 'init' for e in events)
    return {'text': text, 'session_id': document.get('session_id'), 'observed_model': observed,
            'all_models': sorted(models), 'usage': tokens, 'config_events': _config_events(events),
            'config_basis': 'stream-json init event' if init else 'isolation flags (the json result carries no configuration report)',
            'meter': {'usage': usage, 'modelUsage': models, 'num_turns': document.get('num_turns'),
                      'total_cost_usd': document.get('total_cost_usd'), 'duration_ms': document.get('duration_ms')}}


def _codex_rollout(thread_id, env):
    """(served model, rollout sha256) from this invocation's own rollout file, when present."""
    if not thread_id or not re.fullmatch(r'[A-Za-z0-9._-]{1,200}', str(thread_id)):
        return None, None
    home = Path(env.get('CODEX_HOME') or Path(env.get('HOME', '~')).expanduser() / '.codex')
    sessions = home / 'sessions'
    if not sessions.is_dir():
        return None, None
    for path in sessions.rglob(f'rollout-*{thread_id}.jsonl'):
        if path.is_symlink():
            continue
        raw = path.read_bytes()
        model = None
        for line in raw.decode('utf-8', errors='replace').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if type(row) is dict and row.get('type') == 'turn_context' and type(row.get('payload')) is dict:
                model = row['payload'].get('model') or model
        return model, transport_receipt.sha256_bytes(raw)
    return None, None


def fresh_codex_home(target, env):
    """A per-call CODEX_HOME: a copy of the login's auth.json and a generated config.toml, nothing else.

    The file is copied, never read or logged, and a symlinked auth.json is refused. The copy can
    refresh its token inside the temporary home; the user's own auth.json is not updated.
    Returns the evidence label.
    """
    source = Path(env.get('CODEX_HOME') or Path(env.get('HOME', '~')).expanduser() / '.codex')
    target = Path(target)
    target.mkdir(mode=0o700)
    auth = source / 'auth.json'
    if auth.is_symlink():
        raise AgentCLIError('codex auth.json is a symbolic link; refusing to copy it', 'refused')
    if auth.is_file():
        shutil.copyfile(auth, target / 'auth.json', follow_symlinks=False)
        os.chmod(target / 'auth.json', 0o600)
    (target / 'config.toml').write_text('# Configuration of one call: no user instructions, profiles or providers.\n')
    env['CODEX_HOME'] = str(target)
    return 'fresh-home'


def fresh_google_home(agent, target, env):
    """A per-call HOME holding only the agent's login material; returns (label, dotenv paths left out)."""
    real = Path(env.get('HOME', '~')).expanduser()
    target = Path(target)
    target.mkdir(mode=0o700)
    for relative in LOGIN_MATERIAL[agent]:
        source = real / relative
        if source.is_symlink():
            raise AgentCLIError(f'{agent} login material {relative} is a symbolic link; refusing to copy it', 'refused')
        if source.is_file():
            (target / relative).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source, target / relative, follow_symlinks=False)
            os.chmod(target / relative, 0o600)
    settings = real / '.gemini' / 'settings.json'
    selected = None
    if settings.is_file() and not settings.is_symlink():
        try:
            document = json.loads(settings.read_text())
            auth = ((document.get('security') or {}).get('auth') or {}) if type(document) is dict else {}
            selected = auth.get('selectedType') or document.get('selectedAuthType')
        except (ValueError, OSError, AttributeError):
            selected = None
    if type(selected) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', selected):
        (target / '.gemini').mkdir(parents=True, exist_ok=True, mode=0o700)
        (target / '.gemini' / 'settings.json').write_text(json.dumps({'security': {'auth': {'selectedType': selected}}}))
    left_out = sorted(str(real / c) for c in DOTENV_CANDIDATES if (real / c).exists())
    env['HOME'] = str(target)
    return 'fresh-home', left_out


def _codex(out):
    thread, usage, text, errors = None, None, None, []
    events = []
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if type(event) is not dict:
            continue
        events.append(event)
        kind = event.get('type')
        if kind == 'thread.started':
            thread = event.get('thread_id')
        elif kind == 'turn.completed' and type(event.get('usage')) is dict:
            usage = event['usage']
        elif kind == 'item.completed' and type(event.get('item')) is dict and event['item'].get('type') == 'agent_message':
            text = event['item'].get('text')
        elif kind in ('error', 'turn.failed'):
            errors.append(kind)
    if errors:
        raise AgentCLIError(f'codex reported {len(errors)} error event(s) ({", ".join(sorted(set(errors)))}); '
                            'their text is not shown', 'exit')
    tokens = None
    if usage is not None:
        tokens = _tokens(int(usage.get('input_tokens') or 0), int(usage.get('output_tokens') or 0))
    return {'text': text, 'session_id': thread, 'observed_model': None, 'all_models': [], 'usage': tokens,
            'config_events': _config_events(events), 'config_basis': 'a fresh CODEX_HOME and the CLI events',
            'meter': {'usage': usage}}


def _google(name, out):
    """Gemini CLI and Antigravity print one JSON document: the response text, a session id and per-model stats."""
    try:
        document = json.loads(out)
    except ValueError as exc:
        raise AgentCLIError(f'{name} did not return its JSON output', 'parse') from exc
    if type(document) is list:
        document = next((d for d in reversed(document) if type(d) is dict and d.get('type') == 'result'), {})
    if type(document) is not dict or document.get('error') or document.get('is_error'):
        raise AgentCLIError(f'{name} reported an error result', 'exit')
    structured = document.get('structured_output')
    text = json.dumps(structured) if type(structured) is dict else next(
        (document[k] for k in ('response', 'result', 'text') if type(document.get(k)) is str), None)
    stats = document.get('stats') if type(document.get('stats')) is dict else {}
    models = stats.get('models') if type(stats.get('models')) is dict else {}
    if not models and type(document.get('modelUsage')) is dict:
        models = document['modelUsage']
    tokens, observed = None, document.get('model') if type(document.get('model')) is str else None
    if models:
        def count(row, *keys):
            block = row.get('tokens') if type(row.get('tokens')) is dict else row
            return sum(int(block.get(k) or 0) for k in keys)
        observed = observed or max(models, key=lambda m: count(models[m] or {}, 'candidates', 'outputTokens'))
        tokens = _tokens(sum(count(r or {}, 'prompt', 'inputTokens') for r in models.values()),
                         sum(count(r or {}, 'candidates', 'thoughts', 'outputTokens') for r in models.values()))
    elif type(document.get('usage')) is dict:
        tokens = _tokens(int(document['usage'].get('input_tokens') or 0), int(document['usage'].get('output_tokens') or 0))
    session = next((document[k] for k in ('session_id', 'sessionId', 'conversation_id', 'conversationId')
                    if type(document.get(k)) is str), None)
    return {'text': text, 'session_id': session, 'observed_model': observed, 'all_models': sorted(models),
            'usage': tokens, 'config_events': [{'type': 'declared', 'user_configuration_loaded': True}],
            'config_basis': f'{name} has no flag that excludes settings or instructions it finds',
            'meter': {'stats': stats or None}}


def _arg_max():
    try:
        return os.sysconf('SC_ARG_MAX')
    except (ValueError, OSError):
        return 256 * 1024


def check_values(agent, parameters):
    """Refuse a model id or effort that could act as a flag or that the CLI cannot carry."""
    model = parameters.get('model')
    if type(model) is not str or not transport_registry.MODEL_ID.match(model):
        raise AgentCLIError('model id must match ' + transport_registry.MODEL_ID.pattern, 'refused')
    effort = parameters.get('reasoning_effort')
    if EFFORTS[agent] and effort not in EFFORTS[agent]:
        raise AgentCLIError(f'{agent} accepts effort ' + ', '.join(EFFORTS[agent]) + f'; {effort!r} is refused', 'refused')


def check_extra_args(agent, extra_args):
    """Extra arguments come from a closed allowlist; name the reason for any other."""
    template = set(transport_registry.template_flags(transport_registry.load(ONESHOT[agent])))
    for argument in extra_args:
        text = str(argument)
        flag = text.split('=', 1)[0] if text.startswith('--') else text[:2] if text.startswith('-') else text
        if text in ALLOWED_EXTRA.get(agent, ()):
            continue
        why = ('repeats a template flag' if flag in template else
               'can re-enable tools, permissions or user configuration' if flag in DENIED_EXTRA.get(agent, ()) else
               'is not in the allowlist')
        raise AgentCLIError(f'extra argument {flag!r} {why}; allowed: ' + (', '.join(ALLOWED_EXTRA[agent]) or 'none'),
                            'refused')


def _argv_values(agent, parameters, prompt, *, cwd, timeout, env):
    schema = parameters.get('output_schema')
    values = {'model': parameters['model'], 'effort': parameters['reasoning_effort'] if EFFORTS[agent] else None,
              'schema': json.dumps(schema, sort_keys=True) if schema is not None else None}
    if agent == 'codex':
        values['last_message'] = str(Path(cwd) / 'last-message.txt')
    elif agent == 'antigravity':
        environment = sum(len(k) + len(v) + 2 for k, v in env.items())
        limit = min(MAX_ARGV_PROMPT, _arg_max() - environment - ARGV_MARGIN)
        if len(prompt.encode()) > limit:
            raise AgentCLIError(f'antigravity takes its prompt as an argument; this request exceeds the {limit}-byte '
                                'room left by ARG_MAX and the environment', 'refused')
        values.update(prompt=prompt, print_timeout=f'{max(int(timeout) - 5, 1)}s')
    elif agent == 'gemini':
        values['prompt_hint'] = 'Answer the request given on standard input.'
    return values


def _managed_settings():
    for path in MANAGED_SETTINGS:
        if Path(path).is_file():
            try:
                return transport_registry.file_sha256(path)
            except OSError:
                return None
    return None


def _cli_version(executable, env):
    try:
        done = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=30, env=env,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (done.stdout or '').strip() if done.returncode == 0 else ''
    return text.splitlines()[0][:200] if text else None


def invoke(agent, parameters, context, *, timeout=DEFAULT_TIMEOUT, executable=None, extra_args=(), environment=None,
           request_sha256=None, own_group=True, max_output_bytes=MAX_OUTPUT_BYTES, tools_required='none'):
    """Run one fresh CLI session; return its parsed, schema-checked answer and the launcher's receipt.

    Refuses before launch when the transport has no current probe of this executable, when the model
    id or effort is invalid for the CLI, or when an extra argument is outside the allowlist.
    """
    from .agent_host import validate_public_result, HostFailure
    if tools_required not in transport_registry.TOOLS:
        raise AgentCLIError('unknown role tools requirement', 'refused')
    source = dict(os.environ if environment is None else environment)
    agent = choose(agent, source)
    declaration = transport_registry.load(ONESHOT[agent])
    check_values(agent, parameters)
    extra_args = [str(a) for a in extra_args]
    check_extra_args(agent, extra_args)
    env, _ = transport_registry.child_environment(declaration, source)
    path, sha = transport_registry.resolve_executable(declaration, source, executable)
    if not path:
        raise AgentCLIError(f'{agent} CLI ({LAUNCHERS[agent]}) is not installed on PATH', 'unusable')
    probe = transport_registry.read_probe(declaration['id'])
    capabilities, reasons = transport_registry.effective_capabilities(declaration, probe, executable_sha256=sha)
    if capabilities is None:
        raise AgentCLIError(f'transport {declaration["id"]} is unusable: ' + ', '.join(reasons) +
                            f'; run `ravel transport probe {declaration["id"]}` for this executable', 'unusable')
    prompt = build_prompt(parameters, context)
    host_invocation = 'host-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='ravel-agent-cli-') as cwd, \
            tempfile.TemporaryDirectory(prefix='ravel-agent-home-') as home:
        config, home_mode, dotenv = ('verified-flags' if agent == 'claude' else 'none'), 'real', []
        if agent == 'codex':
            config, home_mode = fresh_codex_home(Path(home) / 'codex-home', env), 'fresh-codex-home'
        elif agent in ('gemini', 'antigravity'):
            config, dotenv = fresh_google_home(agent, Path(home) / 'home', env)
            home_mode = 'fresh'
        env_names = sorted(env)
        cli_version = _cli_version(path, env)
        values = _argv_values(agent, parameters, prompt, cwd=cwd, timeout=timeout, env=env)
        argv = transport_registry.render_argv(declaration, values, executable=path)
        argv = argv[:-1] + extra_args + argv[-1:] if agent == 'codex' else argv + extra_args
        stdin = '' if agent == 'antigravity' else prompt
        out, facts = _run(argv, stdin, cwd=cwd, env=env, timeout=timeout, own_group=own_group, max_bytes=max_output_bytes)
        rollout = None
        if agent == 'claude':
            answer = _claude(out)
        elif agent == 'codex':
            answer = _codex(out)
            last = Path(cwd) / 'last-message.txt'
            if last.is_file() and not last.is_symlink() and last.read_text().strip():
                answer['text'] = last.read_text()
            answer['observed_model'], rollout = _codex_rollout(answer['session_id'], env)
            answer['all_models'] = [answer['observed_model']] if answer['observed_model'] else []
        else:
            answer = _google(agent, out)
    prompt_sha = transport_receipt.sha256_bytes(prompt.encode())
    recorded_argv = [prompt_sha if agent == 'antigravity' and a == prompt else a for a in argv]
    events = answer.pop('config_events')
    loaded = config == 'none' or bool(events)
    managed = _managed_settings() if agent == 'claude' else None
    basis = ('user configuration excluded by ' + ('isolation flags' if config == 'verified-flags' else 'a fresh home')
             + f' ({answer.pop("config_basis")})' if not loaded else
             'user-level configuration may have been loaded; not an independent fresh context'
             + f' ({answer.pop("config_basis")})')
    if managed:
        basis += '; admin-managed settings are present and stay in force (digest recorded)'
    if dotenv:
        basis += '; dotenv files left out of the fresh HOME: ' + ', '.join(dotenv)
    value = extract_json(answer['text'])
    try:
        value = validate_public_result(value, parameters.get('output_schema'))
    except HostFailure as exc:
        raise AgentCLIError(f'agent answer does not match the requested schema: {exc}', 'schema') from None
    # Transmitted only when the rendered argv carries the effort: a template without {effort} never does.
    effort_transmitted = values['effort'] is not None and any('{effort}' in t for t in declaration['argv_template'])
    receipt = {
        'schema_version': transport_receipt.SCHEMA_VERSION, 'kind': transport_receipt.KIND,
        'writer': {'module': WRAPPER_MODULE, 'module_sha256': module_sha256()},
        'transport': {'id': declaration['id'], 'transport_kind': declaration['transport_kind'],
                      'declaration_sha256': transport_registry.declaration_sha256(declaration),
                      'declaration_origin': transport_registry.origin(declaration),
                      'qualification_status': declaration['qualification']['status'],
                      'attestation_capability': capabilities['attestation']},
        'probe': {'probe_sha256': transport_registry.digest(probe), 'executable_sha256': probe['executable_sha256'],
                  'current': probe['executable_sha256'] == sha},
        'executable': {'path': path, 'sha256': sha, 'cli_version': cli_version},
        'invocation': {'host_invocation_id': host_invocation, 'argv_sha256': transport_registry.digest(recorded_argv),
                       'env_names': env_names, 'home_mode': home_mode, 'dotenv_paths': dotenv, 'cwd': cwd,
                       'prompt_in_argv': agent == 'antigravity'},
        'process': facts,
        'content': {'request_sha256': request_sha256 or transport_receipt.digest({'parameters': parameters, 'context': context}),
                    'prompt_sha256': prompt_sha, 'value_sha256': transport_receipt.digest(value)},
        'effort': {'requested': parameters['reasoning_effort'], 'transmitted': effort_transmitted},
        'configuration': {'tools_required': tools_required, 'effective_tools': capabilities['tools'], 'isolation_profile': capabilities['isolation'],
                          'config': config, 'override_args': [], 'managed_settings_sha256': managed,
                          'user_configuration_loaded': loaded, 'basis': basis},
        'cli_reported': {'label': 'cli-reported', 'session_id': answer['session_id'] if type(answer['session_id']) is str
                         and answer['session_id'].strip() else None,
                         'observed_model': answer['observed_model'], 'all_models': answer['all_models'],
                         'usage': answer['usage'], 'config_events': events, 'rollout_sha256': rollout}}
    transport_receipt.shape(receipt)
    observed = answer['observed_model'] or f'not reported by {agent} (requested {parameters["model"]})'
    return {'agent': agent, 'value': value, 'usage': answer['usage'], 'observed_model': observed,
            'all_models': answer['all_models'], 'meter': answer['meter'], 'receipt': receipt,
            'cli_session_id': receipt['cli_reported']['session_id'], 'host_invocation_id': host_invocation,
            'isolation': legacy_isolation(receipt)}


def legacy_isolation(receipt):
    """The schema-3 relay isolation block, derived from a launcher receipt."""
    configuration = receipt['configuration']
    return {'transport_id': receipt['transport']['id'], 'declaration_sha256': receipt['transport']['declaration_sha256'],
            'argv_sha256': receipt['invocation']['argv_sha256'], 'cli_version': receipt['executable']['cli_version'],
            'config': configuration['config'], 'config_overriding_arguments': configuration['override_args'],
            'env_names': receipt['invocation']['env_names'], 'effort_transmitted': receipt['effort']['transmitted'],
            'user_configuration_loaded': configuration['user_configuration_loaded'], 'basis': configuration['basis'],
            'cli_session_id': receipt['cli_reported']['session_id'],
            'executable_sha256': receipt['executable']['sha256'],
            'session_receipt_sha256': transport_receipt.digest(receipt)}


# ------------------------------------------------------------ command adapter

def serve(stdin, stdout, *, agent, timeout, executable=None, extra_args=()):
    """AgentHost command adapter: {request_id, parameters, context} -> {request_id, value, usage, observed_model, session_receipt}.

    The receipt's request digest is the sha256 of the exact bytes read from stdin. The CLI runs in this
    wrapper's process group, so stopping the wrapper's group stops the CLI and its descendants.
    """
    raw = stdin.buffer.read() if hasattr(stdin, 'buffer') else stdin.read().encode()
    request = json.loads(raw)
    # Share the group only when this wrapper leads it (AgentHost starts it in a new session); otherwise
    # a timeout would signal whatever group the caller runs in.
    leader = os.getpgid(0) == os.getpid()
    answer = invoke(agent, request['parameters'], request['context'], timeout=timeout, executable=executable,
                    extra_args=extra_args, request_sha256=transport_receipt.sha256_bytes(raw), own_group=not leader,
                    tools_required=request.get('role_requires', {}).get('tools', 'none'))
    stdout.write(json.dumps({'request_id': request['request_id'], 'value': answer['value'],
                             'usage': answer['usage'], 'observed_model': answer['observed_model'],
                             'session_receipt': answer['receipt']},
                            sort_keys=True, allow_nan=False))
    stdout.flush()


def wrapper_prefix():
    return [sys.executable, '-B', '-m', WRAPPER_MODULE, 'serve']


def source_root():
    """The directory that holds this ``ravel`` package when it runs from a source checkout, else None."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / 'ravel').is_dir() and not any(part == 'site-packages' for part in root.parts) else None


def wrapper_agent(command, environment):
    """The agent a command runs when it is exactly this RAVEL launcher, else None.

    The command must be this interpreter running ``-m ravel.workflow.cli_agent_host serve`` with known
    options, and its PYTHONPATH must equal this source root exactly (or be absent for an installed package).
    """
    if type(command) not in (list, tuple) or list(command[:5]) != wrapper_prefix():
        return None
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)

    def refuse(message):
        raise ValueError(message)
    parser.error = refuse
    parser.add_argument('--agent', choices=AGENTS, required=True)
    parser.add_argument('--timeout', type=int, required=True)
    parser.add_argument('--executable')
    parser.add_argument('--extra-arg', action='append', default=[])
    try:
        args, rest = parser.parse_known_args(list(command[5:]))
    except (argparse.ArgumentError, ValueError):
        return None
    if rest:
        return None
    search = (environment or {}).get('PYTHONPATH')
    root = source_root()
    if root is not None:
        if search != str(root):
            return None
    elif search is not None:
        return None
    return args.agent


def host_config(config):
    """Translate {"type": "agent-cli", ...} into the AgentHost command configuration.

    ``auto`` resolves here, at configuration time: by the run's ``preferences`` (an agent-preferences
    record) when given, else the first installed CLI in the fixed order. The command and the transport
    label always name one concrete agent.
    """
    allowed = {'type', 'agent', 'executable', 'extra_args', 'cli_timeout_seconds', 'timeout_seconds',
               'max_request_bytes', 'max_response_bytes', 'bound_roots', 'privacy', 'local_models', 'vision',
               'literature_origins', 'preferences'}
    if type(config) is not dict or config.get('type') != 'agent-cli' or set(config) - allowed:
        raise ValueError('agent-cli host config fields: ' + ', '.join(sorted(allowed)))
    agent = config.get('agent', 'auto')
    if agent not in (*AGENTS, 'auto'):
        raise ValueError('agent must be one of ' + ', '.join(AGENTS) + ' or auto')
    preferences = config.get('preferences')
    if preferences is not None and (type(preferences) is not dict or preferences.get('kind') != 'agent-preferences'):
        raise ValueError('preferences must be an agent-preferences record')
    if agent == 'auto':
        try:
            agent = choose('auto', preferences=preferences)
        except AgentCLIError as exc:
            raise ValueError(str(exc)) from None
    check_extra_args(agent, [str(a) for a in config.get('extra_args', [])])
    cli_timeout = int(config.get('cli_timeout_seconds', min(int(config.get('timeout_seconds', 3600)) - 30, DEFAULT_TIMEOUT)))
    command = wrapper_prefix() + ['--agent', agent, '--timeout', str(max(cli_timeout, 1))]
    if config.get('executable'):
        command += ['--executable', str(config['executable'])]
    for argument in config.get('extra_args', []):
        command += ['--extra-arg=' + str(argument)]
    environment = {k: v for k, v in os.environ.items() if k in PASSED_ENVIRONMENT and k not in ('PATH', 'LANG')}
    environment['PATH'] = os.environ.get('PATH', os.defpath)
    root = source_root()
    if root is not None:
        environment['PYTHONPATH'] = str(root)
    for name in ('RAVEL_STATE_DIR', 'RAVEL_TRANSPORT_PATH'):
        if name in os.environ:
            environment[name] = os.environ[name]
    result = {'type': 'command', 'command': command, 'environment': environment}
    declaration = transport_registry.load(ONESHOT[agent])
    # Declared names (for example GEMINI_API_KEY) are read at call time; their values never enter the config.
    names = sorted(set(declaration['pass_env'] + declaration['auth']['env_names']) - set(environment))
    if names:
        result['pass_env'] = names
    result['transport'] = ONESHOT[agent]
    for key in ('timeout_seconds', 'max_request_bytes', 'max_response_bytes', 'bound_roots', 'privacy',
                'local_models', 'vision', 'literature_origins'):
        if key in config:
            result[key] = config[key]
    return result


# ------------------------------------------------------------ external requests

def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    with path.open('xb') as stream:
        stream.write(raw)
    import hashlib
    return {'path': str(path.absolute()), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _refuse_unfit_reviewer(agent, role):
    """Critic and verifier need a transport without model tools that can attest a fresh session; refuse before launch."""
    from .agent_host import BLIND_ROLES
    if role not in BLIND_ROLES:
        return
    capabilities = transport_registry.load(ONESHOT[agent])['capabilities']
    if capabilities['tools'] != 'none' or capabilities['attestation'] != 'transport':
        raise AgentCLIError(f'{role} refused on {ONESHOT[agent]}: tools {capabilities["tools"]}, attestation '
                            f'{capabilities["attestation"]}; an independent reviewer needs tools none and '
                            'transport attestation', 'refused')


def answer(request_path, out, *, agent='auto', actor_id=None, timeout=DEFAULT_TIMEOUT, executable=None,
           extra_args=(), environment=None):
    """Answer one prepared external request and write a version-3 response file and its launcher receipt."""
    document = json.loads(Path(request_path).read_text())
    if document.get('kind') != 'external_agent_request':
        raise AgentCLIError('not a prepared external agent request')
    request = document['request']
    chosen = choose(agent, dict(os.environ if environment is None else environment))
    _refuse_unfit_reviewer(chosen, (document.get('context') or {}).get('role'))
    result = invoke(chosen, document['parameters'], document['context'], timeout=timeout, executable=executable,
                    extra_args=extra_args, environment=environment, request_sha256=document['sha256'])
    out = Path(out).absolute()
    actor = actor_id or f'{result["agent"]}-cli:{request.get("node_id", "node")}'
    loaded = result['isolation']['user_configuration_loaded']
    invocation = result['cli_session_id'] or result['host_invocation_id']
    receipt = _write_new(out.with_name(out.stem + '.receipt.json'), result['receipt'])
    # A session that loaded the user's own instructions, memory or plugins is not a fresh context.
    response = {'schema_version': 3, 'request_id': request['request_id'], 'request_sha256': document['sha256'],
                'invocation_id': invocation, 'actor_id': actor, 'observed_model': result['observed_model'],
                'fresh_context': not loaded, 'parent_transcript_supplied': False,
                'user_configuration_loaded': loaded, 'isolation': result['isolation'], 'value': result['value'],
                'usage_report': {'state': 'unknown', 'tokens': {'input_tokens': None, 'output_tokens': None, 'total_tokens': None},
                                 'source': None}}
    if result['usage'] is not None:
        evidence_path = out.with_name(out.stem + '.usage.json')
        evidence = _write_new(evidence_path, {
            'schema_version': 1, 'kind': 'host_meter', 'request_id': request['request_id'],
            'request_sha256': document['sha256'], 'invocation_id': invocation,
            'observed_model': result['observed_model'], 'complete_invocation': True, 'usage': result['usage']})
        response['usage_report'] = {'state': 'host_reported', 'tokens': result['usage'], 'source': {
            'kind': 'host_meter', 'invocation_id': invocation,
            'artifact': {'path': evidence_path.name, 'sha256': evidence['sha256'], 'size': evidence['size']}}}
    written = _write_new(out, response)
    return {'response': written, 'receipt': receipt, 'agent': result['agent'], 'observed_model': result['observed_model'],
            'invocation_id': invocation, 'usage': result['usage'], 'meter': result['meter'],
            'user_configuration_loaded': loaded}


def _declared_actor(graph_root):
    """A judgment role binding beside the graph declares the role's actor."""
    binding = Path(graph_root).absolute().parent / 'binding.json'
    if binding.is_file():
        try:
            value = json.loads(binding.read_text())
        except ValueError:
            return None
        if type(value) is dict and Path(str(value.get('graph_root', ''))).absolute() == Path(graph_root).absolute():
            return value.get('actor_id')
    return None


def answer_graph(graph_root, *, agent='auto', node=None, actor_id=None, timeout=DEFAULT_TIMEOUT,
                 executable=None, extra_args=(), environment=None, prepare_pending=False, workers=1):
    """Answer and deliver every awaiting external node (or one named node) as a ``map``.

    Each awaiting node is one item: a failed answer or delivery is that item's ``failed``
    outcome and the others still run. A delivered node is no longer awaiting, so a re-run
    answers only the failed items. ``join_sha256`` is independent of completion order.
    """
    from . import agent_graph, graph_nodes
    root = Path(graph_root).absolute()
    state = agent_graph.status(root)
    if prepare_pending:
        spec = json.loads((root / agent_graph.SPEC).read_text())
        for row in spec.get('nodes', []):
            if row.get('action') == 'external' and state['nodes'].get(row['id'], {}).get('status') == 'pending' \
                    and (node is None or row['id'] == node):
                deps = row.get('depends_on', [])
                if all(state['nodes'][d]['status'] == 'completed' for d in deps):
                    agent_graph.prepare_external(root, row['id'])
        state = agent_graph.status(root)
    awaiting = [(identity, current) for identity, current in state['nodes'].items()
                if current.get('status') == 'awaiting_external' and (node is None or identity == node)]
    actor = actor_id or _declared_actor(root)

    def answer_one(pair):
        identity, current = pair
        request_file = root / current['external_request']['path']
        out = root / 'external-responses' / f'{identity}-{current["attempt_id"]}.json'
        result = answer(request_file, out, agent=agent, actor_id=actor, timeout=timeout, executable=executable,
                        extra_args=extra_args, environment=environment)
        agent_graph.deliver_external(root, identity, out)
        return {k: result[k] for k in ('response', 'agent', 'observed_model', 'invocation_id', 'usage')}
    results = graph_nodes.map_items(awaiting, lambda pair: pair[0], answer_one, workers=workers)
    delivered = [{'node_id': r['key'], **r['result']} for r in results if r['outcome'] == 'ok']
    failed = [{'node_id': r['key'], 'error': r['error']} for r in results if r['outcome'] == 'failed']
    return {'graph': str(root), 'delivered': delivered, 'failed': failed,
            'items': [{'key': r['key'], 'outcome': r['outcome']} for r in results],
            'join_sha256': graph_nodes.join_sha256(results), 'execution_authorized': False,
            'note': 'Answers are model sessions, each recording whether user configuration was loaded; they are not human or physicist review.'}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel agent-cli', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('detect', help='list installed agent CLIs (claude, codex, agy, gemini)')
    for name in ('serve', 'answer', 'answer-graph'):
        sub = commands.add_parser(name)
        sub.add_argument('--agent', default='auto', choices=(*AGENTS, 'auto'))
        sub.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT)
        sub.add_argument('--executable')
        sub.add_argument('--extra-arg', action='append', default=[])
        if name == 'answer':
            sub.add_argument('--request', type=Path, required=True)
            sub.add_argument('--out', type=Path, required=True)
            sub.add_argument('--actor')
        if name == 'answer-graph':
            sub.add_argument('--graph', type=Path, required=True)
            sub.add_argument('--node')
            sub.add_argument('--actor')
            sub.add_argument('--prepare', action='store_true', help='also prepare ready pending external nodes')
            sub.add_argument('--workers', type=int, default=1, help='answer up to this many nodes at once (1-16)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'serve':
            serve(sys.stdin, sys.stdout, agent=args.agent, timeout=args.timeout, executable=args.executable,
                  extra_args=args.extra_arg)
            return 0
        if args.command == 'detect':
            result = detect()
        elif args.command == 'answer':
            result = answer(args.request, args.out, agent=args.agent, actor_id=args.actor, timeout=args.timeout,
                            executable=args.executable, extra_args=args.extra_arg)
        else:
            result = answer_graph(args.graph, agent=args.agent, node=args.node, actor_id=args.actor,
                                  timeout=args.timeout, executable=args.executable, extra_args=args.extra_arg,
                                  prepare_pending=args.prepare, workers=args.workers)
    except AgentCLIError as exc:
        parser.exit(1, f'agent cli ({exc.code}): {exc}\n')
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'agent cli: {type(exc).__name__}: {exc}\n')
    print(json.dumps(result, indent=2, allow_nan=False))
    return 1 if result.get('failed') else 0


if __name__ == '__main__':
    raise SystemExit(main())
