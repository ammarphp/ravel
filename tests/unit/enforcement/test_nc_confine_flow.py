"""Confinement-flow rows: the probe, the machine grant and the read policy hold whatever the stage declares.

The adversary widens a start by one writable mount or one tool, asks for more cores than the live
machine grant, or writes a self-declared "sealed first" phase flag and then reads a restricted
reference. Oracles are observed from outside the start: the inventory probe's differences and the
step's typed hold, the refusal before any process exists (a process-start counter, an absent
report), and the hostile script's report and canary bytes; positive controls start the admitted
inventory, a granted core count and a permitted read through the same entry.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import HostileLaunch, controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

LAUNCHER = 'ravel.controller.confine.launcher'


def _sandbox(confine):
    from test_nc_switches_launch import _launch_sandbox_or_skip
    _launch_sandbox_or_skip(confine)


@case('CT05', binding=CONTROLLER)
def test_CT05_an_extra_mount_or_tool_makes_the_probe_unequal_and_holds_the_start(nc):
    confine = require_controller('confine')
    graph = require_controller('step.graph')
    from test_nc_step_flow import _hold
    _sandbox(confine)
    store, run_dir = controller_run(nc)
    attempt = run_dir / 'steps' / 's05' / 'attempts' / '1'
    outputs, extra = attempt / 'outputs', run_dir / 'steps' / 's05' / 'extra-mount'
    for path in (outputs, extra):
        path.mkdir(parents=True)
    capsule = {'argv': [sys.executable, '-c', "print('inert')"], 'env': {}, 'reads': [], 'writes': [str(outputs)],
               'cwd': str(outputs), 'run_dir': str(run_dir), 'attempt_dir': str(attempt),
               'limits': {'wall_seconds': 60}, 'backend': 'auto', 'input_digests': {},
               'controller': {'run_id': store.run_id, 'launch_id': 's05:1'}}
    admitted = {'writable': [os.path.realpath(outputs)], 'network': 'none'}
    assert graph._probe('launch', {**capsule, 'admitted': admitted})['equal'] is True  # positive control
    widened = dict(capsule, writes=[str(outputs), str(extra)])
    held = _hold(lambda: graph._probe('launch', {**widened, 'admitted': admitted}), 'inventory_probe_mismatch')
    assert {'field': 'writable', 'unadmitted': [os.path.realpath(extra)]} in held.evidence['differences'], held.evidence
    # A worker start with one tool more than its admitted toolbelt is unequal too.
    workspace = nc.path('probe-workspace', 'inputs', 'placeholder').parent.parent
    for name in ('outputs', 'scratch'):
        (workspace / name).mkdir(exist_ok=True)
    server = r"""
import json,sys
for line in sys.stdin:
    req=json.loads(line)
    if 'id' not in req: continue
    result=({'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'inert','version':'1'}}
        if req['method']=='initialize' else {'tools':[{'name':n,'inputSchema':{'type':'object'}} for n in sys.argv[1:]]})
    print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
"""
    command = [sys.executable, '-I', '-S', '-B', '-c', server, 'read', 'ws_write']
    target = {'workspace': str(workspace), 'mcp_command': command, 'network': None}
    control = confine.probe('worker', target)
    assert control['tools'] == ['read', 'ws_write'] and control['mcp_observed']
    admitted = {key: control[key] for key in ('tools', 'writable', 'env_names', 'network')}
    assert confine.probe('worker', {**target, 'admitted': admitted})['equal'] is True
    found = confine.probe('worker', {**target, 'mcp_command': [*command, 'fictional_extra_tool'], 'admitted': admitted})
    assert found['equal'] is False and {'field': 'tools', 'unadmitted': ['fictional_extra_tool']} in found['differences']



def _probe_always_equal(original):
    def probe(kind, target):
        found = original(kind, target)
        return dict(found, equal=True, differences=[])
    return probe


register(Mutation('M07', ('ravel.controller.confine.probe:probe', 'ravel.controller.confine:probe'),
                  _probe_always_equal, ('CT05',), binding=MUTATION_CONTROLLER,
                  why='the probed inventory is never compared with the admitted set'))


@case('E06', binding=CONTROLLER)
def test_E06_a_launch_asking_more_cores_than_the_live_grant_never_starts(nc):
    confine = require_controller('confine')
    _sandbox(confine)
    from ravel.workflow import machine_lease
    from test_nc_switches_launch import _Popen
    granted = machine_lease.cpu_grant()
    nc.patch.setattr(machine_lease, 'cpu_grant', lambda: granted[:1])  # the run holds a one-core live grant
    launch = HostileLaunch(nc)
    popen = _Popen(nc.patch)
    with pytest.raises(confine.ConfinementRefused, match='asks for 2 CPUs; the live machine grant has 1'):
        launch.run([{'op': 'env'}], limits={'wall_seconds': 60, 'cpus': 2})
    assert popen.starts_of(str(launch.script)) == [] and launch.observed() is None, 'no process was created'
    # Positive control: the granted core count starts through the same entry.
    launch.run([{'op': 'env'}], limits={'wall_seconds': 60, 'cpus': 1})
    assert launch.returncode == 0 and launch.observed() is not None, launch.stderr


register(Mutation('M08', f'{LAUNCHER}:_limits', lambda original: lambda value: dict(value or {}), ('E06',),
                  binding=MUTATION_CONTROLLER, why='launch limits are not checked against the live machine grant'))


@case('C11', binding=CONTROLLER)
def test_C11_a_self_declared_sealing_flag_never_lifts_the_read_policy_of_a_restricted_source(nc):
    confine = require_controller('confine')
    _sandbox(confine)
    launch = HostileLaunch(nc)
    canary = nc.effects.canary('restricted-reference')
    reference = launch.inputs / 'restricted' / 'reference.json'
    reference.parent.mkdir()
    reference.write_text(json.dumps({'value': canary.value}))
    permitted = launch.inputs / 'settings.json'
    permitted.write_text(json.dumps({'value': 'fictional setting'}))
    # The adversary declares its own phase in a writable JSON before the stage starts.
    (launch.run_dir / 'outputs').mkdir(exist_ok=True)
    (launch.run_dir / 'outputs' / 'phase.json').write_text(json.dumps({'result_sealed_first': True}))
    launch.run([{'op': 'read', 'path': str(reference)}, {'op': 'read', 'path': str(permitted)}],
               withheld=[reference.parent])
    restricted, allowed = launch.observed()  # one report row per scripted attempt, in order
    assert restricted['op'] == 'read' and restricted['ok'] is False, restricted
    assert canary.found_in(launch.outputs) == [], 'the restricted bytes reached the stage output'
    assert allowed['op'] == 'read' and allowed['ok'] is True, allowed  # positive control: a permitted read


def _withheld_dropped(original):
    def prepare(spec):
        if isinstance(spec, dict) and spec.get('label') == 'nc-hostile':
            spec = {k: v for k, v in spec.items() if k != 'withheld'}
        return original(spec)
    return prepare


register(Mutation('M24', f'{LAUNCHER}:prepare', _withheld_dropped, ('C11',), binding=MUTATION_CONTROLLER,
                  why='a launch reads the sources its plan withholds'))
