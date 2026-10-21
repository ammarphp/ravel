"""Inventory probes compare what a launch or worker can reach with what was admitted (CT05).

The probes run inert inventory programs in the real sandbox; a difference makes ``equal``
false, which is what the step's preflight holds on.
"""
import sys

import pytest

from test_p05_support import sandboxed  # noqa: F401 (fixture)


def launch_target(tmp_path, **extra):
    run = (tmp_path / 'run').resolve()
    (run / 'outputs').mkdir(parents=True)
    (run / 'inputs').mkdir()
    return run, {'run_dir': str(run), 'stage': 'probe', 'cwd': str(run), 'reads': [str(run)],
                 'writes': [str(run / 'outputs')], **extra}


def test_a_launch_inventory_equal_to_its_admitted_set(tmp_path, sandboxed):
    from ravel.controller.confine import probe
    run, target = launch_target(tmp_path)
    first = probe('launch', target)
    assert first['writable'] == [str(run / 'outputs')] and first['network'] == 'none'
    assert 'GH_TOKEN' not in first['env_names'] and first['class'] == 'confined'
    admitted = {'writable': first['writable'], 'env_names': first['env_names'], 'network': 'none',
                'tools': first['tools']}
    again = probe('launch', {**target, 'admitted': admitted})
    assert again['equal'] is True and again['differences'] == []


def test_CT05_extra_mount_or_tool_differs_from_admission(tmp_path, sandboxed):
    from ravel.controller.confine import probe
    run, target = launch_target(tmp_path)
    admitted = {'writable': [str(run / 'outputs')], 'network': 'none', 'tools': [sys.executable]}
    (run / 'extra').mkdir()
    wider = probe('launch', {**target, 'writes': [str(run / 'outputs'), str(run / 'extra')], 'admitted': admitted})
    assert wider['equal'] is False
    assert {'field': 'writable', 'unadmitted': [str(run / 'extra')]} in wider['differences']
    tooled = probe('launch', {**target, 'tools': [sys.executable, '/usr/bin/extra-tool'], 'admitted': admitted})
    assert tooled['equal'] is False and {'field': 'tools', 'unadmitted': ['/usr/bin/extra-tool']} in tooled['differences']


MCP_FIXTURE = r"""
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    result = ({'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
               'serverInfo': {'name': 'inert', 'version': '1'}}
              if request['method'] == 'initialize' else
              {'tools': [{'name': name, 'inputSchema': {'type': 'object'}} for name in sys.argv[1:]]})
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
"""


def worker_target(tmp_path, tools=('read', 'write')):
    ws = (tmp_path / 'worker').resolve()
    for name in ('inputs', 'outputs', 'scratch'):
        (ws / name).mkdir(parents=True, exist_ok=True)
    return {'workspace': str(ws), 'mcp_command': [sys.executable, '-I', '-S', '-B', '-c', MCP_FIXTURE, *tools]}


def test_a_worker_inventory_reports_actual_mcp_tools(tmp_path, sandboxed):
    from ravel.controller.confine import probe
    target = worker_target(tmp_path)
    first = probe('worker', {**target, 'tools': ['invented']})
    assert first['tools'] == ['read', 'write'] and first['mcp_observed'] is True
    assert first['declared_tools'] == ['invented']
    admitted = {key: first[key] for key in ('tools', 'writable', 'network', 'env_names')}
    assert probe('worker', {**target, 'admitted': admitted})['equal'] is True
    extra = probe('worker', {**target, 'mcp_command': [*target['mcp_command'], 'shell'], 'admitted': admitted})
    assert extra['equal'] is False
    assert {'field': 'tools', 'unadmitted': ['shell']} in extra['differences']


def test_worker_missing_actual_mcp_or_admitted_fields_holds(tmp_path, sandboxed):
    from ravel.controller.confine import probe
    target = worker_target(tmp_path)
    del target['mcp_command']
    seen = probe('worker', {**target, 'tools': ['read'], 'admitted': {'tools': ['read']}})
    assert seen['equal'] is False and seen['mcp_observed'] is False
    assert seen['tools'] == []
    assert any(row.get('reason') == 'missing admitted field' for row in seen['differences'])


def test_worker_actual_write_roots_and_extra_mount(tmp_path, sandboxed):
    from ravel.controller.confine import probe
    target = worker_target(tmp_path)
    from pathlib import Path
    ws = Path(target['workspace'])
    narrow = {**target, 'writable': [str(ws / 'outputs')]}
    first = probe('worker', narrow)
    assert first['writable'] == [str(ws / 'outputs')]
    admitted = {key: first[key] for key in ('tools', 'writable', 'network', 'env_names')}
    extra = probe('worker', {**target, 'admitted': admitted})
    assert extra['equal'] is False
    assert {'field': 'writable', 'unadmitted': [str(ws / 'scratch')]} in extra['differences']


def test_worker_malformed_actual_server_holds(tmp_path, sandboxed):
    from ravel.controller.confine import probe
    target = worker_target(tmp_path)
    target['mcp_command'] = [sys.executable, '-I', '-S', '-B', '-c', 'print("bad response", flush=True)']
    seen = probe('worker', {**target, 'admitted': {}})
    assert seen['equal'] is False and seen['mcp_observed'] is False


def test_probe_rejects_unknown_kinds_and_admitted_fields(tmp_path):
    from ravel.controller.confine import probe
    with pytest.raises(ValueError):
        probe('container', {})
    from ravel.controller.confine.probe import _compare
    with pytest.raises(ValueError):
        _compare({}, {'ports': []})
    assert _compare({'network': 'none'}, None) == (None, [])
