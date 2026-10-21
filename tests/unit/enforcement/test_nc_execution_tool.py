"""Execution and tool rows: the worker reaches only its broker toolbelt; effects stay confined.

The adversary is ``fake_worker.py`` on the governed CLI worker path (sandbox, broker MCP,
dispatcher receipts) or a hostile authored script on a governed launch. Oracles count effects from
outside: broker receipts, sentinel bytes, listener connections, canary bytes.
"""
from __future__ import annotations

import json
import sys

from nc_adversary import InstalledWorker, sandbox_or_skip
from nc_cases import CONTROLLER, INSTALLED, case, require_controller
from nc_mutations import Mutation, register

FINAL = {'completed': True, 'summary': 'fictional result written'}


def _by_action(calls):
    found = {}
    for call in calls:
        found.setdefault(call['action'], []).append(call)
    return found


@case('T02', binding=INSTALLED)
def test_T02_unknown_tool_names_and_a_generic_delegate_are_denied_before_invocation(nc):
    sandbox_or_skip(nc)
    worker = InstalledWorker(nc)
    worker.scenario({'actions': [
        {'op': 'list'},
        {'op': 'call', 'name': 'delegate', 'arguments': {'role': 'generator', 'task': 'produce events'}},
        {'op': 'call', 'name': 'Bash', 'arguments': {'command': 'echo fictional'}},
        {'op': 'call', 'name': 'mcp__ravel__ws_write', 'arguments': {'path': 'outputs/result.txt', 'content': 'x'}},
        {'op': 'call', 'name': 'ws_write', 'arguments': {'path': 'outputs/result.txt', 'content': 'fictional result'}},
    ], 'final': FINAL})
    spec = worker.spec()
    receipt = worker.dispatch(spec)
    calls = _by_action(worker.broker_calls())
    for name in ('delegate', 'Bash', 'mcp__ravel__ws_write'):
        refused = calls[f'tool:{name}']
        assert [c['status'] for c in refused] == ['refused'], name
        assert refused[0]['reply']['error']['code'] == 'not_allowlisted', name
    offered = worker.adversary_log(spec)['names']
    assert not {'delegate', 'Bash', 'shell'} & set(offered)
    # Positive control: the admitted write is the only credited output.
    assert [c['status'] for c in calls['write']] == ['ok']
    assert receipt['status'] == 'ok', receipt.get('failure')
    assert [o['path'] for o in receipt['credited_outputs']] == ['outputs/result.txt']


def _card(role='analysis-author'):
    from ravel.workflow import role_registry
    return role_registry.load(role)


@case('T03', binding=INSTALLED)
def test_T03_an_admitted_tool_called_with_changed_arguments_is_refused_at_the_broker(nc):
    from nc_adversary import InProcessWorker
    worker = InProcessWorker(nc, _card())
    (worker.workspace / 'inputs' / 'data.json').write_text('{"fictional": 1}')
    names = {tool['name'] for tool in worker.tools}
    assert {'ws_read', 'knowledge_find'} <= names, sorted(names)
    worker.play({'actions': [
        {'op': 'call', 'name': 'knowledge_find', 'arguments': {'op': 'show', 'id': 'fictional'}},
        {'op': 'call', 'name': 'ws_read', 'arguments': {'path': 'inputs/data.json', 'follow': '../../'}},
        {'op': 'call', 'name': 'ws_read', 'arguments': {'path': 'inputs/data.json'}},
    ]})
    rows = worker.ledger()
    assert [r['status'] for r in rows] == ['refused', 'refused', 'ok'], [(r['action'], r['status']) for r in rows]
    assert all(r['reply']['error']['code'] == 'not_allowlisted' for r in rows[:2])


def _match_any_arguments(original):
    """Toolbelt membership by action only: changed arguments still match a listed tool."""
    def match(tools, action, args):
        return next((t for t in tools if t['executes_through']['action'] == action), None)
    return match


register(Mutation('M07', 'ravel.workflow.toolbelt:match', _match_any_arguments, ('T03',),
                  why='the broker guard admits a listed action with any arguments'))


@case('T01', binding=INSTALLED)
def test_T01_no_interpreter_shell_or_renamed_executable_gives_a_worker_an_effect_outside_its_sandbox(nc):
    sandbox_or_skip(nc)
    worker = InstalledWorker(nc)
    protected = nc.effects.sentinels('outside-workspace', {'result.json': '{"fictional": 1}'})
    target = protected.root / 'result.json'
    port = nc.effects.listener.port
    worker.scenario({'actions': [
        {'op': 'list'},
        {'op': 'exec', 'argv': ['/bin/sh', '-c', f'echo forged > {target}']},
        {'op': 'exec', 'argv': [sys.executable, '-c', f'open({str(target)!r}, "w").write("forged")']},
        {'op': 'exec', 'argv': [sys.executable, '-c',
                                f'import socket; socket.create_connection(("127.0.0.1", {port}), timeout=2)']},
        {'op': 'exec', 'argv': ['/bin/cp', '/bin/sh', 'scratch/renamed-tool']},
        {'op': 'exec', 'argv': ['scratch/renamed-tool', '-c', f'echo forged > {target}']},
        {'op': 'native_write', 'path': str(target), 'text': 'forged'},
        {'op': 'call', 'name': 'ws_write', 'arguments': {'path': 'outputs/result.txt', 'content': 'fictional'}},
    ], 'final': FINAL})
    spec = worker.spec()
    receipt = worker.dispatch(spec)
    assert protected.changes() == [] and nc.effects.listener.accepted == 0
    offered = set(worker.adversary_log(spec)['names'])
    assert not offered & {'Bash', 'shell', 'exec', 'python', 'run'}, offered
    pinned = json.loads((worker.workspace(spec) / 'inputs' / 'toolbelt.json').read_text())
    belt = {t['name'] for t in pinned['tools'] if t['executes_through']['action'] is not None}
    assert offered == belt, 'the offered tools equal the toolbelt pinned for this launch'
    assert receipt['status'] == 'ok', receipt.get('failure')  # positive control: the broker write is credited


@case('I04', binding=INSTALLED)
def test_I04_writes_outside_declared_outputs_fail_at_the_broker_and_in_the_sandbox(nc):
    sandbox_or_skip(nc)
    worker = InstalledWorker(nc)
    worker.write_input('inputs/approved.json', '{"fictional": "approved"}')
    neighbour = nc.effects.sentinels('neighbour', {'outputs/result.txt': 'neighbour'})
    worker.scenario({'actions': [
        {'op': 'call', 'name': 'ws_write', 'arguments': {'path': '../../escape.txt', 'content': 'x'}},
        {'op': 'call', 'name': 'ws_write', 'arguments': {'path': str(neighbour.root / 'outputs/result.txt'),
                                                         'content': 'x'}},
        {'op': 'call', 'name': 'ws_write', 'arguments': {'path': 'inputs/approved.json', 'content': 'x'}},
        {'op': 'native_write', 'path': str(neighbour.root / 'outputs' / 'result.txt'), 'text': 'x'},
        {'op': 'native_write', 'path': str(worker.run / 'outputs' / 'adopted.json'), 'text': 'x'},
        {'op': 'call', 'name': 'ws_write', 'arguments': {'path': 'outputs/result.txt', 'content': 'fictional'}},
    ], 'final': FINAL})
    spec = worker.spec(inputs=['inputs/approved.json'])
    receipt = worker.dispatch(spec)
    calls = worker.broker_calls()
    writes = [c for c in calls if c['action'] == 'write']
    assert [c['status'] for c in writes] == ['refused', 'refused', 'refused', 'ok'], [c['status'] for c in writes]
    assert neighbour.changes() == []
    assert not (worker.run / 'outputs' / 'adopted.json').exists()
    assert (worker.run / 'inputs' / 'approved.json').read_text() == '{"fictional": "approved"}'
    assert [o['path'] for o in receipt['credited_outputs']] == ['outputs/result.txt']  # positive control
