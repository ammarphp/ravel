"""Schema-recognised host delegates, without discovery by tool name.

The embedding host supplies an invocation callable. Native adapters translate a
RAVEL envelope into a fresh Claude Code or Codex child launch; generic MCP tools
advertise the same versioned input/output contract in their metadata. These are
host assertions, never sandbox or independent-review evidence. No model SDK,
credential lookup, retry, or parent-conversation executor exists here.
"""
from __future__ import annotations

from copy import deepcopy
import json

from jsonschema import Draft202012Validator

from ravel.paths import package_data_path
from .cli_worker import LaunchRefused


CONTRACT_KEY = 'ravel/role-dispatch'
HOSTS = ('claude', 'codex', 'gemini', 'opencode', 'antigravity')


def schemas():
    return json.loads(package_data_path('agents', 'role-dispatch.json').read_text())


def _validate(value, schema, label):
    if not Draft202012Validator(schema).is_valid(value):
        raise LaunchRefused('role dispatch refused: invalid ' + label, ['delegate:' + label])


class DelegateAdapter:
    """A host-supplied MCP callable with an exact, source-owned schema contract."""

    def __init__(self, tool, invoke):
        metadata = tool.get('_meta') if type(tool) is dict else None
        contract = metadata.get(CONTRACT_KEY) if type(metadata) is dict else None
        schema = schemas()
        _validate(contract, schema['contract'], 'contract')
        if (tool.get('inputSchema') != schema['input']
                or tool.get('outputSchema') != schema['output'] or not callable(invoke)):
            raise LaunchRefused('role dispatch refused: delegate schema/callable mismatch', ['delegate:schema'])
        self.host = contract['host']
        self.identity = {'kind': 'generic-mcp', 'host': self.host,
                         'tool_name': tool.get('name'), 'contract': deepcopy(contract)}
        self._invoke = invoke

    def invoke(self, request):
        schema = schemas()
        arguments = {'request': deepcopy(request)}
        _validate(arguments, schema['input'], 'request')
        result = self._invoke(arguments)
        # MCP CallToolResult may carry the canonical output as structuredContent.
        if type(result) is dict and 'structuredContent' in result:
            if result.get('isError'):
                raise ValueError('delegate reported an error after dispatch')
            result = result['structuredContent']
        _validate(result, schema['output'], 'response')
        return deepcopy(result)


class NativeDelegateAdapter:
    """Fresh-child bridge. ``collect`` returns the canonical completion envelope.

    ``spawn`` and ``collect`` are supplied by the embedding host, never read from
    run files or imported from model SDKs. Collection must wait for that child;
    missing or reused child identities are refused by the common dispatcher.
    """

    def __init__(self, host, spawn, collect):
        if host not in ('claude', 'codex') or not callable(spawn) or not callable(collect):
            raise LaunchRefused('role dispatch refused: unsupported native adapter', ['delegate:native'])
        self.host, self._spawn, self._collect = host, spawn, collect
        self.identity = {'kind': 'native-subagent', 'host': host}

    def invoke(self, request):
        _validate({'request': request}, schemas()['input'], 'request')
        prompt = json.dumps(request, sort_keys=True, allow_nan=False)
        if self.host == 'claude':
            arguments = {'description': 'Execute the bound RAVEL role', 'prompt': prompt,
                         'subagent_type': 'general-purpose'}
        else:
            from .. import broker
            arguments = {'task_name': 'ravel_' + broker.digest(request)[:16],
                         'message': prompt, 'fork_turns': 'none'}
        child = self._spawn(arguments)
        if type(child) is not str or not child.strip():
            raise ValueError('native spawn returned no child session identity')
        result = self._collect(child)
        _validate(result, schemas()['output'], 'response')
        if result['session_id'] != child:
            raise ValueError('completion belongs to a different native child')
        return deepcopy(result)
