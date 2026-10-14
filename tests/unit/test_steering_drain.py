"""A drain pause lets admitted work finish its broker work; a cancellation stops it.

The stop functions are the real ones: the host tests open a real host-subagent broker window and
the command-line tests run a fake CLI under the real worker supervisor in the sandbox. New
launches are refused under both modes. The crash tests kill a process inside the pause between
its commitment, its stop markers and its recorded execution, then resume.
"""
import json
import os
import time

import pytest

from ravel.workflow import agent_worker as worker, broker, gate_wiring as gw, graph_substrate as gs
from ravel.workflow import rdj_custody as custody
from ravel.workflow.transports import cli_worker, host_subagent
from test_cli_worker_adapter import cli, ready, real_sandbox_or_skip, spec as cli_spec  # noqa: F401
from test_host_subagent_adapter import spec as host_spec

HOST = 'host-subagent-claude'
CHECK = 'check:validation.validate_task_contract.validate'
CANCEL = dict(autonomy='manual', checkin_thresholds={}, hard_ceilings={}, signoff_steps=[], unknown_cost='ask',
              on_pause='cancel', result_acceptance='physicist')


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.delenv('RAVEL_WORK_ROOT', raising=False)
    (tmp_path / 'run').mkdir()
    return tmp_path / 'run'


def cancel_on_pause(run):
    gw.set_steering_policy(run, CANCEL, source_text='Cancel running work on pause.')
    (run / 'inputs').mkdir(exist_ok=True)
    (run / 'inputs/checkin1_approval.json').write_text('{"approved":true}')
    gw.ack_steering(run, gw.steering_records(run)[-1]['event_id'], interpretation='Policy retained.')
    gw.record_plan_approval(run)


def host_call(packet, call_id, action, args):
    return broker.socket_call(packet['broker_socket'], {'call_id': call_id, 'action': action, 'args': args})


def attempt_receipts(run, node_id, attempt):
    return [broker.verify_broker_receipt(run, {'path': r['record']['path'], 'sha256': r['record']['sha256']},
                                         verify_outputs=False)
            for r in broker.ledger(run, 'broker')
            if r['record']['node_id'] == node_id and r['record']['attempt'] == attempt]


def refused_code(reply):
    return (reply.get('error') or {}).get('code')


# ---------------------------------------------------------------- host broker window

def test_host_window_finishes_its_output_and_self_check_under_a_drain_pause(run):
    s, other = host_spec(), host_spec(attempt=2)
    ws, other_ws = worker.materialize(run, s), worker.materialize(run, other)
    packet = host_subagent.brief(run, s, ws, transport_id=HOST)
    with host_subagent.serve_broker(run, s, packet):
        gw.record_steering(run, 'Pause the study.', effect='pause')
        assert broker.stop_mode(run) == 'drain'  # written by the real worker stop
        assert (run / gs.STOP).is_file()  # and by the real graph stop
        assert host_call(packet, 'c1', 'write', {'path': 'outputs/result.txt', 'content': 'x'})['status'] == 'ok'
        check = host_call(packet, 'c2', 'check run', {'check_id': CHECK})
        assert refused_code(check) != 'stop_requested', check
        # A new launch is refused while this window drains.
        with pytest.raises(cli_worker.LaunchRefused):
            host_subagent.brief(run, other, other_ws, transport_id=HOST)
        assert gw.steering_state(run)['pause_status'] == 'draining'
    receipt = host_subagent.complete(run, s, packet, final={'completed': True, 'summary': 'host reported'})
    assert receipt['status'] == 'ok' and receipt['broker']['calls'] == 2
    assert [r['action'] for r in attempt_receipts(run, s['node_id'], 1)] == ['write', 'check run']
    assert gw.steering_state(run)['pause_status'] == 'observed-stopped'


def test_host_window_stops_its_broker_work_under_a_cancelling_pause(run):
    cancel_on_pause(run)
    s = host_spec()
    ws = worker.materialize(run, s)
    packet = host_subagent.brief(run, s, ws, transport_id=HOST)
    with host_subagent.serve_broker(run, s, packet):
        gw.record_steering(run, 'Pause the study.', effect='pause')
        assert broker.stop_mode(run) == 'cancel'
        for n, (action, args) in enumerate((('write', {'path': 'outputs/result.txt', 'content': 'x'}),
                                            ('check run', {'check_id': CHECK}))):
            assert refused_code(host_call(packet, f'c{n}', action, args)) == 'stop_requested'
    assert not (ws / 'outputs/result.txt').exists()
    receipt = host_subagent.complete(run, s, packet, final={'completed': True, 'summary': 'host reported'})
    assert receipt['status'] != 'ok' and receipt['credited_outputs'] == []


def test_a_drain_never_replaces_a_cancellation_in_force(run):
    worker.stop(run)  # an operator's cancellation
    gw.record_steering(run, 'Pause the study.', effect='pause')
    assert broker.stop_mode(run) == 'cancel'


def test_a_stop_record_without_a_mode_is_a_cancellation(run):
    (run / 'agent-work').mkdir()
    (run / broker.STOP_RECORD).write_text(json.dumps({'utc': '2026-10-01T00:00:00Z'}))
    assert broker.stop_mode(run) == 'cancel'
    (run / broker.STOP_RECORD).write_text('not json')
    assert broker.stop_mode(run) == 'cancel'


# ---------------------------------------------------------------- command-line worker under its real supervisor

DRAINING_CLI = '''#!{python} -B
import json, os, subprocess, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
args = sys.argv[1:]
if args == ['--version']:
    print('fake-cli 9.9.9'); sys.exit(0)
if '--help' in args:
    sys.stdout.write((here / 'help.txt').read_text()); sys.exit(0)
prompt = sys.stdin.read()
entry = json.loads(Path(args[args.index('--mcp-config') + 1]).read_text())['mcpServers']['ravel']
server = subprocess.Popen([entry['command'], *entry['args']], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
def rpc(n, method, params):
    server.stdin.write(json.dumps({{'jsonrpc': '2.0', 'id': n, 'method': method, 'params': params}}) + '\\n')
    server.stdin.flush()
    return json.loads(server.stdout.readline())
rpc(1, 'initialize', {{}})
read = rpc(2, 'tools/call', {{'name': 'ws_read', 'arguments': {{'path': 'inputs/conformance.json'}}}})
nonce = json.loads(read['result']['structuredContent']['stdout_tail'])['nonce']
Path('scratch/ready').write_text('ready')
deadline = time.monotonic() + 50
while not (here / 'go').exists() and time.monotonic() < deadline:
    time.sleep(0.05)
wrote = rpc(3, 'tools/call', {{'name': 'ws_write', 'arguments': {{'path': 'outputs/conformance.txt', 'content': nonce}}}})
checked = rpc(4, 'tools/call', {{'name': 'check_validation_validate_task_contract_validate', 'arguments': {{}}}})
server.stdin.close(); server.wait()
print(json.dumps({{'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '',
    'session_id': (here / 'session.txt').read_text().strip(), 'num_turns': 3,
    'total_cost_usd': 0.0123, 'usage': {{'input_tokens': 100, 'output_tokens': 20}},
    'modelUsage': {{'claude-fixture-model': {{'outputTokens': 20}}}},
    'structured_output': {{'completed': True, 'summary': 'written after the pause'}}}}))
'''


def wait_for(condition, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    pytest.fail('condition not reached')


def receipt_when_done(run, s, seconds=90):
    def done():
        try:
            worker.load_receipt(run, s['node_id'], s['attempt'])
            return True
        except ValueError:
            return False
    wait_for(done, seconds)
    return worker.load_receipt(run, s['node_id'], s['attempt'])


def started_cli_worker(root):
    real_sandbox_or_skip(root)
    ready(root, body=DRAINING_CLI)
    s = cli_spec(root)
    assert worker.launch(root / 'run', s, wait=False)['status'] == 'running'
    ws = worker.workspace(root / 'run', s['node_id'], s['attempt'])
    wait_for(lambda: (ws / 'scratch/ready').exists())
    return s, ws


def test_cli_worker_finishes_its_output_and_self_check_under_a_drain_pause(cli):
    run = cli / 'run'
    s, ws = started_cli_worker(cli)
    gw.record_steering(run, 'Pause the study.', effect='pause')
    assert broker.stop_mode(run) == 'drain'
    # A new launch is refused; reattaching to the running attempt does not end it.
    refused = worker.launch(run, cli_spec(cli, attempt=2))
    assert refused['status'] == 'refused' and refused['failure']['code'] == 'stop_requested'
    with pytest.raises(gw.SteeringRefused):
        worker.launch(run, s)
    (cli / 'bin/go').write_text('go')
    receipt = receipt_when_done(run, s)
    assert receipt['status'] == 'ok', receipt['failure']
    assert (ws / 'outputs/conformance.txt').read_text() == 'n-0123456789'
    calls = attempt_receipts(run, s['node_id'], 1)
    assert [c['action'] for c in calls] == ['read', 'write', 'check run']
    assert all(refused_code(c['reply']) != 'stop_requested' for c in calls)
    wait_for(lambda: gw.steering_state(run)['pause_status'] == 'observed-stopped')


def test_cli_worker_is_stopped_under_a_cancelling_pause(cli):
    run = cli / 'run'
    cancel_on_pause(run)
    s, ws = started_cli_worker(cli)
    gw.record_steering(run, 'Pause the study.', effect='pause')
    assert broker.stop_mode(run) == 'cancel'
    (cli / 'bin/go').write_text('go')
    receipt = receipt_when_done(run, s)
    assert receipt['status'] != 'ok' and receipt['credited_outputs'] == []
    assert not any(c['action'] == 'write' and c['status'] == 'ok' for c in attempt_receipts(run, s['node_id'], 1))


# ---------------------------------------------------------------- a crash inside the pause, then resume

def crash_inside_pause(run, point):
    """Record a pause in a child process that dies at ``point``; nothing below that point runs."""
    pid = os.fork()
    if pid == 0:
        try:
            if point in ('before_intent', 'before_execution'):
                event = 'pause_intent' if point == 'before_intent' else 'pause_execution'
                append = custody.append

                def dying(rundir, ledger, record, **options):
                    if record.get('event') == event:
                        os._exit(0)
                    return append(rundir, ledger, record, **options)
                custody.append = dying
            else:  # between the graph stop marker and the worker stop marker
                graph_stop = gs.stop

                def dying(*args, **options):
                    graph_stop(*args, **options)
                    os._exit(0)
                gs.stop = dying
            gw.record_steering(run, 'Pause the study.', effect='pause')
        finally:
            os._exit(3)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0


def resume(run):
    event = gw.record_steering(run, 'Continue the study.', effect='resume')
    gw.ack_steering(run, event['event_id'], interpretation='Continue within the approved scope.')


@pytest.mark.parametrize('point, markers', [('before_intent', set()), ('between_markers', {'graph'}),
                                            ('before_execution', {'graph', 'worker'})])
def test_a_resume_after_a_crash_inside_the_pause_clears_what_the_pause_wrote(run, point, markers):
    crash_inside_pause(run, point)
    state = gw.steering_state(run)
    assert state['paused'] and state['pause_status'] == 'requested'  # its execution was never recorded
    assert gw.dispatch_permitted(run, 'node')[0] is False
    assert {name for name, path in (('graph', run / gs.STOP), ('worker', run / broker.STOP_RECORD))
            if path.is_file()} == markers
    resume(run)
    assert not (run / gs.STOP).exists() and broker.stop_mode(run) is None
    state = gw.steering_state(run)
    assert not state['paused'] and state['pause_status'] == 'running'
    assert gw.dispatch_permitted(run, 'node')[0] is True


def test_a_crashed_pause_restores_an_earlier_stop_and_keeps_a_later_one(run):
    worker.stop(run)  # an operator's cancellation before the pause
    earlier = json.loads((run / broker.STOP_RECORD).read_text())
    crash_inside_pause(run, 'before_execution')
    # A graph stop recorded after the crash by someone else is independent of the pause.
    gs.stop(run, reason='operator stop after the crash')
    resume(run)
    assert json.loads((run / broker.STOP_RECORD).read_text()) == earlier
    assert json.loads((run / gs.STOP).read_text())['reason'] == 'operator stop after the crash'


def test_a_second_pause_after_a_crashed_one_restores_the_stop_before_both(run):
    crash_inside_pause(run, 'before_execution')
    gw.record_steering(run, 'Pause again.', effect='pause')
    assert gw.steering_state(run)['pause_status'] in ('observed-stopped', 'draining')
    resume(run)
    assert not (run / gs.STOP).exists() and broker.stop_mode(run) is None
