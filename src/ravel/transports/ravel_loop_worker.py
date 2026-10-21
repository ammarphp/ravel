"""The RAVEL loop as a sandboxed worker executable: ``python -m ravel.transports.ravel_loop_worker``.

``ravel.workflow.transports.ravel_loop.prepare_launch`` builds the launch; the supervisor starts this
module inside the worker sandbox with the prompt on standard input. It runs ``RavelLoop`` over:

- the pinned toolbelt in ``inputs/toolbelt.json`` (its manifest digest is checked) served through the
  broker socket exactly as the broker MCP face serves it (``toolbelt.to_request``, ``broker.socket_call``),
  so every tool call gets the same broker receipt and guard;
- the closed final-record schema in ``inputs/final-schema.json`` as the loop's ``submit_final`` tool;
- the provider endpoint, adapter, model, effort and authentication in ``inputs/loop.json``, written once
  and read-only by the adapter. A credential is read only from the environment variable the declaration
  names; its value is never written, logged or printed.

It prints one result envelope on standard output, which the supervisor captures through a pipe:
``type: ravel-loop-result``, the session id the adapter minted, the requested model, each model turn's
reported model, HTTP status and the provider's own ``usage`` object as received, the number of model
turns and broker calls, the loop status and the final record. ``provider_usage.decode`` and the
adapter's ``observe`` read that envelope; nothing in it is estimated. The exit status is 0 only when
the loop completed with a final record. Standard library plus RAVEL's own loop dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib import error as urlerror, request as urlrequest
from urllib.parse import quote

CONFIG_KIND = 'ravel-loop-worker-config'
RESULT_TYPE = 'ravel-loop-result'
SCOPE = ('scratch', 'loop')
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class Sender:
    """One provider HTTP request per model turn; no retry, fallback or credential discovery."""

    def __init__(self, config):
        auth = config['auth']
        self.endpoint, self.adapter, self.model = config['endpoint'], config['adapter'], config['model']
        self.socket_path = config['broker_socket']
        self.auth = {'kind': auth['kind'], 'env_name': auth.get('env_name'), 'header_style': auth.get('header_style')}
        self.identity = {'transport_id': config['transport_id'], 'endpoint': self.endpoint, 'adapter': self.adapter,
                         'auth': dict(self.auth)}

    def _url(self):
        if self.adapter == 'gemini':
            return self.endpoint.replace('{model}', quote(self.model, safe=''))
        return self.endpoint

    def __call__(self, body, *, timeout, max_cost_usd):
        from ravel.workflow import provider_transport
        key = None
        if self.auth['kind'] == 'env':
            key = os.environ.get(self.auth['env_name'] or '')
            if not key:
                # Raised before anything is sent; the loop records a refused turn, never a value.
                raise RuntimeError('credential variable is not set in the worker environment')
        headers = provider_transport.headers(self.adapter, key, self.auth['header_style'])
        data = json.dumps(body, allow_nan=False).encode()
        call = urlrequest.Request(self._url(), data=data, headers=headers, method='POST')
        from ravel.workflow.transports.loop_control import _admitted
        with _admitted(self.socket_path, 'provider-model-request'):
            try:
                with urlrequest.build_opener(NoRedirect()).open(call, timeout=timeout) as response:
                    status, raw = response.status, response.read(MAX_RESPONSE_BYTES + 1)
            except urlerror.HTTPError as exc:
                status, raw = exc.code, exc.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError('provider response exceeds the byte bound')
        try:
            document = json.loads(raw)
        except ValueError:
            document = {}
        return {'body': document if type(document) is dict else {}, 'http_status': status}


class NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('provider redirects are refused; configure the final endpoint explicitly')


class BrokerClient:
    """The loop's broker: the pinned toolbelt's served tools, sent to the broker socket as the MCP face sends them."""

    def __init__(self, served, socket_path, *, node_id, attempt):
        self.served, self.socket_path = served, socket_path
        self.node_id, self.attempt = node_id, attempt
        self.actions = sorted(t['name'] for t in served)
        self.allowed_actions = set(self.actions)
        self.calls = 0

    def call(self, request):
        from ravel.workflow import broker, toolbelt
        self.calls += 1
        reply = broker.socket_call(self.socket_path, toolbelt.to_request(self.served, request['action'],
                                                                          request['args'], request['call_id']))
        if type(reply) is dict and reply.get('status') != 'ok' and not reply.get('error'):
            reply = {**reply, 'error': {'code': 'action_' + str(reply.get('status'))}}
        return reply


def _read(workspace, relative):
    path = workspace / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing worker input: ' + relative)
    return json.loads(path.read_text(encoding='utf-8'))


def run(workspace, config_path, socket_path, prompt):
    """Run the loop once; return the result envelope."""
    from ravel.transports.ravel_loop import RavelLoop
    from ravel.workflow import broker_mcp, toolbelt
    from ravel.workflow.ravel_chat_model import RavelTransportChatModel
    workspace = Path(workspace).absolute()
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    if type(config) is not dict or config.get('kind') != CONFIG_KIND or config.get('schema_version') != 1:
        raise ValueError('not a ravel-loop worker configuration')
    belt = _read(workspace, config['toolbelt'])
    if belt.get('kind') != 'toolbelt' or toolbelt.manifest_sha256(belt) != belt.get('manifest_sha256'):
        raise ValueError('the toolbelt document is not a toolbelt or its manifest digest differs')
    if belt['manifest_sha256'] != config['toolbelt_manifest_sha256']:
        raise ValueError('the toolbelt differs from the one the launch was prepared with')
    schema = _read(workspace, config['final_schema'])
    served = broker_mcp.served(belt['tools'])
    tools = [{'name': t['name'], 'description': t['description'], 'args_schema': t['args_schema']} for t in served]
    client = BrokerClient(served, socket_path, node_id=config['node_id'], attempt=config['attempt'])
    sender = Sender({**config, 'broker_socket': str(socket_path)})
    model = RavelTransportChatModel(adapter=config['adapter'], model=config['model'], sender=sender,
                                    request_binding={'transport_id': config['transport_id'],
                                                     'declaration_sha256': config['declaration_sha256'],
                                                     'session_id': config['session_id']},
                                    max_output_tokens=config['max_output_tokens'],
                                    token_limit_field=config['token_limit_field'],
                                    reasoning_effort=config.get('effort'),
                                    max_cost_per_turn_usd=(config.get('cost_bound') or {}).get('cost_usd'),
                                    tariff=config.get('cost_bound'))
    budgets = dict(config['budgets'])
    loop = RavelLoop(workspace.joinpath(*SCOPE), model=model, broker=client, budgets=budgets, final_schema=schema,
                     tools=tools, tool_actions={t['name']: t['name'] for t in tools},
                     instance={'transport': config['transport_id'], 'node_id': config['node_id'],
                               'attempt': config['attempt'], 'session_id': config['session_id']},
                     instruction_owner=workspace)
    from ravel.workflow.transports import loop_control
    with loop_control.bound(loop.scope_root, socket_path):
        result = loop.run(prompt)
    turns = [{'model': t.get('model_reported'), 'http_status': t.get('http_status'),
              'usage': t.get('provider_usage'), 'error': (t.get('error') or {}).get('code'),
              'request_sha256': t.get('request_sha256'), 'response_sha256': t.get('response_sha256')}
             for t in result['turn_receipts']]
    return {'type': RESULT_TYPE, 'schema_version': 1, 'session_id': config['session_id'],
            'transport_id': config['transport_id'], 'adapter': config['adapter'],
            'model_requested': config['model'], 'effort': config.get('effort'),
            'status': result['status'], 'num_turns': len(turns), 'turns': turns,
            'broker_calls': sum(1 for r in result['action_receipts'] if r.get('reply') is not None),
            'final': result['final']}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m ravel.transports.ravel_loop_worker', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--socket', type=Path, default=os.environ.get('RAVEL_BROKER_SOCKET'))
    args = parser.parse_args(argv)
    if args.socket is None:
        parser.error('broker socket required (--socket or RAVEL_BROKER_SOCKET)')
    prompt = sys.stdin.read()
    try:
        envelope = run(args.workspace, args.config, args.socket, prompt)
    except Exception as exc:  # the worker fails closed; its text never carries a credential value
        import traceback
        print(json.dumps({'type': RESULT_TYPE, 'schema_version': 1, 'status': 'error',
                          'error': type(exc).__name__, 'error_at': [
                              {'module': Path(frame.filename).name, 'function': frame.name, 'line': frame.lineno}
                              for frame in traceback.extract_tb(exc.__traceback__)[-8:]]}))
        return 2
    print(json.dumps(envelope, allow_nan=False, sort_keys=True))
    return 0 if envelope['status'] == 'completed' and envelope['final'] is not None else 1


if __name__ == '__main__':
    raise SystemExit(main())
