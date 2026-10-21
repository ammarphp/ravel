"""Inert worker adversary: a scripted stand-in for a model CLI. It never calls a model.

Installed as the executable of a CLI worker transport (``nc_adversary.install_worker``), it does
what a real CLI does on the RAVEL worker path: reads the prompt on standard input, starts the broker
MCP server named in ``--mcp-config``, speaks newline-delimited JSON-RPC to it (``initialize``,
``tools/list``, ``tools/call``) and prints the CLI's final JSON envelope. What it does in between
comes from ``scenario.json`` beside the executable: a finite list of actions, many of them
forbidden (unadmitted tools, writes outside ``outputs/``, reads of protected paths, sockets,
process starts, forged acknowledgement and freshness claims, each escalation value, budget
overruns). It reports its own attempts in ``scratch/adversary.json``; the oracle never trusts that
report and counts effects from outside.

``run(scenario, rpc, workspace)`` is the same logic for an in-process MCP session
(``nc_adversary.InProcessWorker``). Standard library only: this file runs inside the sandbox.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def _attempt(log, op, detail, func):
    entry = {'op': op, **detail}
    try:
        entry['result'] = func()
        entry['ok'] = True
    except BaseException as exc:  # an adversary records every refusal and keeps going
        entry['ok'] = False
        entry['error'] = f'{type(exc).__name__}: {exc}'
    log.append(entry)
    return entry


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return str(path)


def _connect(host, port):
    with socket.create_connection((host, port), timeout=2):
        return 'connected'


def run(scenario, rpc, workspace):
    """Perform the scripted actions through ``rpc(method, params) -> response``; return the log."""
    workspace = Path(workspace)
    log, names = [], []
    rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'nc-fake-worker'}})
    if scenario.get('conformance') is True:
        # Fixed inert task used by the actual installed qualifier. The nonce is obtained
        # only from MCP, never supplied in scenario.json or a fabricated qualification.
        listed = rpc('tools/list', {})
        names[:] = [tool['name'] for tool in listed['result']['tools']]
        observed = rpc('tools/call', {'name': 'ws_read',
                                     'arguments': {'path': 'inputs/conformance.json'}})
        nonce = json.loads(observed['result']['structuredContent']['stdout_tail'])['nonce']
        written = rpc('tools/call', {'name': 'ws_write',
            'arguments': {'path': 'outputs/conformance.txt', 'content': nonce}})
        surface = rpc('tools/call', {'name': 'ws_write', 'arguments': {
            'path': 'outputs/surface.txt', 'content': '\n'.join('mcp__ravel__' + name for name in names)}})
        log.append({'op': 'conformance', 'read': observed, 'write': written, 'surface': surface})
    for step, action in enumerate(scenario.get('actions', [])):
        op = action['op']
        if op == 'list':
            entry = _attempt(log, op, {}, lambda: rpc('tools/list', {}))
            if entry['ok'] and 'result' in entry['result']:
                names[:] = [tool['name'] for tool in entry['result']['result']['tools']]
                entry['result'] = {'names': list(names)}
        elif op == 'call':
            params = {'name': action.get('name'), 'arguments': action.get('arguments', {})}
            if action.get('call_id'):
                params['_meta'] = {'call_id': action['call_id']}
            _attempt(log, op, {'name': action.get('name')}, lambda: rpc('tools/call', params))
        elif op == 'native_write':
            _attempt(log, op, {'path': action['path']}, lambda: _write(action['path'], action.get('text', 'nc')))
        elif op == 'native_read':
            def read():
                data = Path(action['path']).read_bytes()
                if action.get('copy_to'):
                    _write(action['copy_to'], data.decode(errors='replace'))
                return len(data)
            _attempt(log, op, {'path': action['path']}, read)
        elif op == 'connect':
            _attempt(log, op, {'port': action['port']}, lambda: _connect(action.get('host', '127.0.0.1'), action['port']))
        elif op == 'exec':
            _attempt(log, op, {'argv': action['argv']},
                     lambda: subprocess.run(action['argv'], capture_output=True, timeout=10).returncode)
        elif op == 'spawn':
            _attempt(log, op, {'argv': action['argv']},
                     lambda: subprocess.Popen(action['argv'], start_new_session=True, stdin=subprocess.DEVNULL,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid)
        elif op == 'env_dump':
            text = '\n'.join(f'{k}={v}' for k, v in sorted(os.environ.items()))
            if action.get('via') == 'broker':
                _attempt(log, op, {'via': 'broker'}, lambda: rpc('tools/call', {
                    'name': 'ws_write', 'arguments': {'path': action['to'], 'content': text}}))
            else:
                _attempt(log, op, {'via': 'native'}, lambda: _write(action['to'], text))
        elif op == 'sleep':
            time.sleep(float(action['seconds']))
            log.append({'op': op, 'ok': True})
        else:
            log.append({'op': op, 'ok': False, 'error': 'unknown scripted action'})
    try:
        _write(workspace / 'scratch' / 'adversary.json', json.dumps({'names': names, 'log': log}, default=str))
    except OSError:
        pass
    return log


def envelope(scenario):
    """The CLI's final JSON result line (``claude -p --output-format json`` shape)."""
    model = scenario.get('model', 'claude-fixture-model')
    usage = scenario.get('usage', {'input_tokens': 100, 'output_tokens': 20})
    document = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': scenario.get('result', ''),
                'session_id': scenario.get('session_id', 'nc-session-1'), 'num_turns': scenario.get('turns', 3),
                'total_cost_usd': scenario.get('cost', 0.0125), 'usage': usage,
                'modelUsage': {model: {'outputTokens': usage.get('output_tokens', 0)}}}
    if scenario.get('final', None) is not None:
        document['structured_output'] = scenario['final']
    return document


def _subprocess_rpc(argv):
    entry = json.loads(Path(argv[argv.index('--mcp-config') + 1]).read_text())['mcpServers']['ravel']
    server = subprocess.Popen([entry['command'], *entry['args']], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True)
    counter = iter(range(1, 1_000_000))

    def rpc(method, params):
        server.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': next(counter), 'method': method, 'params': params}) + '\n')
        server.stdin.flush()
        line = server.stdout.readline()
        if not line:
            raise ConnectionError('broker MCP server closed its output')
        return json.loads(line)
    return server, rpc


def main(argv):
    here = Path(__file__).resolve().parent
    if argv == ['--version']:
        print((here / 'version.txt').read_text().strip() if (here / 'version.txt').is_file() else 'fake-cli 9.9.9')
        return 0
    if '--help' in argv:
        sys.stdout.write((here / 'help.txt').read_text())
        return 0
    if argv == ['auth', 'status', '--json']:
        print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'}))
        return 0
    scenario = json.loads((here / 'scenario.json').read_text())
    prompt = sys.stdin.read()
    try:
        _write(Path('scratch') / 'prompt.txt', prompt)
    except OSError:
        pass
    server, rpc = _subprocess_rpc(argv)
    try:
        run(scenario, rpc, Path.cwd())
    finally:
        server.stdin.close()
        server.wait()
    if scenario.get('raw_stdout') is not None:
        sys.stdout.write(scenario['raw_stdout'])
    else:
        print(json.dumps(envelope(scenario)))
    return int(scenario.get('exit', 0))


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
