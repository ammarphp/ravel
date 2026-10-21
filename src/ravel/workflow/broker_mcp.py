"""The broker's MCP face: ``ravel work mcp``.

A stdio MCP server (newline-delimited JSON-RPC 2.0) whose ``tools/list`` is the card's
toolbelt and whose ``tools/call`` is a broker call. CLI workers load it through their own
MCP configuration, written into a fresh configuration directory by ``client_config`` from
the transport's ``worker_surface.mcp`` row. Where a CLI's MCP loading is unconfirmed the
row says ``probe_required`` and the worker keeps ``ravel work call``; the result records
which path was used.

The JSON-RPC core is a stdlib implementation of ``initialize``, ``ping``, ``tools/list``
and ``tools/call`` (the ``mcp`` package is not installed); the knowledge server is
meant to share it. ``submit_final`` is not listed: CLI workers finish with their own
structured output (``--json-schema``/``--output-schema``) or validated text JSON.

A tool call becomes ``toolbelt.to_request`` and goes to the broker socket, so it gets the
same receipt and the same ``tool_gate.broker_guard`` checks as the in-graph loop and
``ravel work call``. A malformed call (a non-string name, non-object arguments) is still
sent, and the broker refuses it with a receipt. The call id is ``params._meta.call_id`` when the client supplies a
stable one, otherwise derived from this server session and the JSON-RPC id.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from . import toolbelt
from .transport_registry import MCP_CONFIGS  # noqa: F401  (the values a worker_surface.mcp row declares)

PROTOCOL_VERSION = '2025-06-18'
SERVER_NAME = 'ravel-broker'
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


def served(tools):
    """The toolbelt entries the server lists and calls: those that execute through a broker action.

    ``submit_final`` executes nothing here (it is the CLI's structured output), so a worker's served
    inventory, and the tool set admitted for it, never names it.
    """
    return [t for t in tools if t['executes_through']['action'] is not None]


class Server:
    """One MCP session over a toolbelt; ``call(broker_request) -> reply`` reaches the broker."""

    def __init__(self, tools, call, *, version='1', literature_output=None):
        self.tools = served(tools)
        self.call = call
        self.version = version
        self.literature_output = literature_output
        self.session = uuid.uuid4().hex[:12]

    def listing(self):
        result = []
        for tool in self.tools:
            read_only = 'workspace_write' not in tool['effects'] and not tool['consequential']
            result.append({'name': tool['name'], 'description': tool['description'],
                           'inputSchema': tool['args_schema'],
                           'annotations': {'readOnlyHint': read_only, 'openWorldHint': False},
                           '_meta': {'atlas_id': tool['atlas_id'], 'derivation': tool['derivation']}})
        return result

    def _call_id(self, params, rpc_id):
        meta = params.get('_meta') or {}
        if type(meta.get('call_id')) is str and meta['call_id']:
            return meta['call_id']
        return 'm' + toolbelt.digest([self.session, rpc_id])[:40]

    def _tools_call(self, params, rpc_id):
        # A malformed name or arguments still go to the broker, which refuses them with a receipt.
        name, args = params.get('name'), params.get('arguments', {})
        if name == 'submit_final':
            raise _RpcError(INVALID_PARAMS, 'submit_final is structured output; finish with the CLI final message')
        reply = self.call(toolbelt.to_request(self.tools, name, args, self._call_id(params, rpc_id)))
        result = {'content': [{'type': 'text', 'text': json.dumps(reply, sort_keys=True)}],
                  'structuredContent': reply, 'isError': reply.get('status') != 'ok'}
        tool = toolbelt.by_name(self.tools).get(name) if isinstance(name, str) else None
        route = tool['executes_through'] if tool is not None else {}
        if self.literature_output is not None and route.get('action') == 'literature query':
            projection = self.literature_output(reply, route['fixed_args']['op'])
            result['content'].extend(projection['content'])
            result['isError'] = result['isError'] or projection['isError']
        return result

    def handle(self, message):
        """One JSON-RPC message in; a response object, or None for a notification."""
        if type(message) is not dict or message.get('jsonrpc') != '2.0' or type(message.get('method')) is not str:
            return _error(message.get('id') if type(message) is dict else None, INVALID_REQUEST, 'invalid request')
        rpc_id, method = message.get('id'), message['method']
        params = message.get('params') or {}
        if 'id' not in message:
            return None  # notifications (initialized, cancelled) need no reply
        try:
            if type(params) is not dict:
                raise _RpcError(INVALID_PARAMS, 'params must be an object')
            if method == 'initialize':
                result = {'protocolVersion': params.get('protocolVersion') or PROTOCOL_VERSION,
                          'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': SERVER_NAME, 'version': self.version}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': self.listing()}
            elif method == 'tools/call':
                result = self._tools_call(params, rpc_id)
            else:
                raise _RpcError(METHOD_NOT_FOUND, f'method {method} is not served')
        except _RpcError as exc:
            return _error(rpc_id, exc.code, str(exc))
        except (ValueError, OSError) as exc:
            return _error(rpc_id, INVALID_PARAMS, f'{type(exc).__name__}: {exc}')
        return {'jsonrpc': '2.0', 'id': rpc_id, 'result': result}


class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _error(rpc_id, code, message):
    return {'jsonrpc': '2.0', 'id': rpc_id, 'error': {'code': code, 'message': message}}


def serve_stdio(server, stdin, stdout):
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except ValueError:
            response = _error(None, PARSE_ERROR, 'parse error')
        else:
            response = server.handle(message)
        if response is not None:
            stdout.write(json.dumps(response, allow_nan=False) + '\n')
            stdout.flush()


# ---- per-CLI configuration ---------------------------------------------------------------

def server_command(*, workspace, toolbelt_path, socket_path, python=None):
    """argv that starts this server inside the worker sandbox."""
    return [python or sys.executable, '-B', '-m', 'ravel.workflow.work_cli', 'mcp', '--workspace', str(workspace),
            '--toolbelt', str(toolbelt_path), '--socket', str(socket_path)]


def _toml(value):
    return json.dumps(value)  # a TOML basic string or array of strings has JSON syntax


def client_config(declaration, *, config_dir, command):
    """Write the transport's MCP configuration into ``config_dir``; return what the launch needs.

    Returns ``{path, argv, env, config, fallback}``: the extra argv (placeholders filled),
    the environment to set (a fresh config home), and ``fallback`` = ``"ravel work call"``
    when the CLI's MCP loading is unconfirmed.
    """
    surface = (declaration.get('worker_surface') or {}).get('mcp')
    if surface is None:
        raise ValueError(f"transport {declaration['id']} declares no worker_surface.mcp row")
    config_dir = Path(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    kind = surface['config']
    entry = {'command': command[0], 'args': command[1:]}
    env, path = {}, None
    if kind == 'mcp_config_flag':
        path = config_dir / 'mcp.json'
        path.write_text(json.dumps({'mcpServers': {'ravel': entry}}, indent=1))
    elif kind == 'codex_home':
        path = config_dir / 'config.toml'
        path.write_text(f'[mcp_servers.ravel]\ncommand = {_toml(entry["command"])}\nargs = {_toml(entry["args"])}\n')
        env['CODEX_HOME'] = str(config_dir)
    elif kind == 'settings_json':
        path = config_dir / '.gemini' / 'settings.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'mcpServers': {'ravel': entry}}, indent=1))
        env['HOME'] = str(config_dir)
    elif kind == 'opencode_config':
        path = config_dir / 'opencode.json'
        path.write_text(json.dumps({'mcp': {'ravel': {'type': 'local', 'command': list(command), 'enabled': True}}},
                                   indent=1))
        env['OPENCODE_CONFIG'] = str(path)
    elif kind != 'probe_required':
        raise ValueError(f'unknown worker_surface.mcp.config {kind!r}')
    argv = [a.replace('{mcp_config}', str(path)) if path else a for a in surface.get('argv', [])]
    return {'config': kind, 'path': str(path) if path else None, 'argv': argv, 'env': env,
            'fallback': 'ravel work call' if kind == 'probe_required' else None}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel work mcp', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--toolbelt', type=Path, help='toolbelt document (default: <workspace>/toolbelt.json)')
    parser.add_argument('--socket', type=Path, default=os.environ.get('RAVEL_BROKER_SOCKET'))
    args = parser.parse_args(argv)
    if args.socket is None:
        parser.error('broker socket required (--socket or RAVEL_BROKER_SOCKET)')
    document = json.loads((args.toolbelt or args.workspace / 'toolbelt.json').read_text())
    if document.get('kind') != 'toolbelt' or toolbelt.manifest_sha256(document) != document.get('manifest_sha256'):
        parser.error('toolbelt document is not a toolbelt or its manifest digest differs')
    from .broker import socket_call

    def literature_output(reply, operation):
        # Imported only when a literature reply is projected: other workers' MCP face stays minimal.
        from . import literature_mcp
        return literature_mcp.projector(args.workspace)(reply, operation)

    server = Server(document['tools'], lambda request: socket_call(args.socket, request),
                    literature_output=literature_output)
    serve_stdio(server, sys.stdin, sys.stdout)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
