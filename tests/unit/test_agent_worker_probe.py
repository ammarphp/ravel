"""Worker inventory admission against the real confinement and stdio probe."""
from copy import deepcopy
import json
import os
import sys

from ravel.controller import confine
from ravel.workflow import agent_worker as worker


SERVER = r'''
import json, os, sys
assert os.environ['CAPSULE_VALUE'] == 'declared'
for line in sys.stdin:
    message = json.loads(line)
    if 'id' not in message:
        continue
    result = {'tools': [{'name': name} for name in json.loads(sys.argv[1])]} if message['method'] == 'tools/list' else {}
    print(json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': result}), flush=True)
'''


def test_worker_start_passes_the_real_confinement_probe(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('CAPSULE_VALUE', 'declared')
    monkeypatch.setenv('LC_CTYPE', 'C.UTF-8')
    monkeypatch.setenv('UNADMITTED_PARENT_VALUE', 'excluded')
    run = tmp_path / 'run'
    run.mkdir()
    ws = tmp_path / 'workspace'
    for name in ('inputs', 'outputs', 'scratch'):
        (ws / name).mkdir(parents=True)
    descriptor = {'argv': [sys.executable, '-B', '-c', 'pass'],
                  'transport': {'transport_kind': 'cli-worker', 'network': None,
                                'mcp_command': [sys.executable, '-I', '-S', '-B', '-c', SERVER,
                                                json.dumps(['read', 'write'])]},
                  'pass_env_names': ['CAPSULE_VALUE', 'LC_CTYPE'],
                  'allowed_actions': ['read', 'write']}
    controller = {'toolbelt': {'tools': ['read', 'write']}}
    targets = []
    real_probe = confine.probe

    def probe(kind, target):
        targets.append(deepcopy(target))
        return real_probe(kind, target)

    monkeypatch.setattr(confine, 'probe', probe)
    accepted = worker._controller_inventory(run, ws, descriptor, controller)
    assert 'observed' in accepted, accepted
    assert accepted['observed']['equal'] is True
    target = targets[-1]
    # The probe runs under the child's own grant: no explicit write roots, only the admitted set to compare.
    assert 'writable' not in target
    assert set(target['admitted']) == {'tools', 'writable', 'env_names', 'network'}
    assert target['admitted']['tools'] == ['read', 'write']
    assert target['admitted']['writable'] == sorted(map(os.path.realpath, (ws / 'outputs', ws / 'scratch')))
    assert target['admitted']['network'] == 'none'
    assert target['mcp_command'] == descriptor['transport']['mcp_command']
    assert target['mcp_env']['CAPSULE_VALUE'] == 'declared'
    assert 'UNADMITTED_PARENT_VALUE' not in target['admitted']['env_names']
    assert sorted(target['mcp_env']) == target['admitted']['env_names']

    extra = deepcopy(descriptor)
    extra['transport']['mcp_command'][-1] = json.dumps(['read', 'write', 'undeclared_tool'])
    refused = worker._controller_inventory(run, ws, extra, controller)
    assert refused['refusal'] == 'inventory_probe_mismatch', refused
    assert 'tools' in refused['missing'] and 'undeclared_tool' in refused['detail']
    assert targets[-1]['admitted'] == target['admitted']

    missing = deepcopy(descriptor)
    missing['transport'].pop('mcp_command')
    refused = worker._controller_inventory(run, ws, missing, controller)
    assert refused['refusal'].startswith('inventory_probe_'), refused
    assert 'MCP' in refused['detail'], refused

    for field, value in (('env_names', []), ('network', 'host-loopback'), ('writable', [])):
        narrowed = {'toolbelt': controller['toolbelt'], 'admitted_inventory': deepcopy(target['admitted'])}
        narrowed['admitted_inventory'][field] = value
        refused = worker._controller_inventory(run, ws, descriptor, narrowed)
        assert refused['refusal'] == 'inventory_probe_mismatch', refused
        assert field in refused['missing'], refused

    provider = deepcopy(descriptor)
    provider['transport']['network'] = 'provider'
    accepted = worker._controller_inventory(run, ws, provider, controller)
    assert 'observed' in accepted and accepted['observed']['equal'] is True, accepted
