"""Production executors: work orders, the executor provider, waivers, stage receipts and the lease."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from ravel.workflow import agent_worker, decision_gate, rdj_custody
from executor_fixtures import Workers, edge, no_self_checks, plan, run_root


def executor():
    from ravel.workflow import production_executor as module
    return module


N1 = {'id': 'N1', 'operation': 'model-events', 'rung': 'smoke'}
N2 = {'id': 'N2', 'operation': 'event-production', 'rung': 'full', 'tool': 'madgraph'}


@pytest.fixture
def root(tmp_path):
    return run_root(tmp_path)


def two_nodes(root, **options):
    return plan(root, nodes=[N2, N1], edges=[edge('N1', 'N2')], **options)


def full_action(node_id='N2', rung='full'):
    return executor().launch_action(node_id, stage='shower', cmd=[sys.executable, '-c', 'pass'], rung=rung)


def executor_errors(root, action):
    return [e for e in decision_gate.check(root, 'launch', action) if e.provider == 'executor']


def test_executors_map_operations_to_registered_cards_that_declare_them():
    from ravel.workflow import role_registry
    table = executor().executors()
    assert table['worker_rungs'] == ['full', 'scan']
    for operation, role in table['operations'].items():
        card = role_registry.load(role)
        assert card['family'] == 'production' and operation in card['operations'], (operation, role)
    assert set(table['coordinator']['host_may']) >= {'plan', 'route', 'dispatch', 'present_checkins', 'run_smoke_rungs'}


def test_seal_orders_carries_role_handbooks_self_checks_and_obligations(root):
    from ravel.workflow import role_registry, work_dispatch
    two_nodes(root)
    sealed = executor().seal_orders(root)
    assert [row['node_id'] for row in sealed] == ['N1', 'N2']
    order = executor().load_order(root, 'N2')
    card = role_registry.load('shower-detector')
    assert order['role'] == 'shower-detector' and order['rung'] == 'full'
    assert order['handbooks'] == card['knowledge']['must_read']
    assert order['self_check'] == role_registry.self_checks('shower-detector') and order['self_check']
    assert order['consults'] == card['knowledge']['consult']
    assert {p['id'] for p in order['review_points']} >= {'RP3:N2'}
    assert order['obligations'] == work_dispatch.derive_obligations(order)
    assert order['declared_outputs'] == [executor().default_output('N2')]
    assert executor().seal_orders(root) == sealed  # equal bytes: idempotent
    assert work_dispatch.pin_obligations(root)['path'] == 'inputs/work-obligations.json'


def test_seal_after_checkin1_approval_is_refused(root):
    two_nodes(root)
    (root / 'inputs/checkin1_approval.json').write_text('{}')
    with pytest.raises(ValueError, match='before CHECK-IN 1 approval'):
        executor().seal_orders(root)
    assert not (root / 'inputs/work-orders').exists()


def test_next_order_follows_plan_edges(root):
    two_nodes(root)
    executor().seal_orders(root)
    first = executor().next_order(root)
    assert first['node_id'] == 'N1' and first['order']['role'] == 'generator'
    assert [r['ready'] for r in executor().pending(root)] == [True, False]


def test_full_launch_without_worker_receipt_or_waiver_is_refused(root):
    """Negative: the executor provider refuses a full-rung launch with neither credit."""
    two_nodes(root)
    executor().seal_orders(root)
    errors = executor_errors(root, full_action())
    assert [e.code for e in errors] == ['executor_receipt_missing'], errors


def test_full_launch_naming_no_plan_node_is_refused(root):
    two_nodes(root)
    action = {**full_action(), 'node_id': None}
    assert [e.code for e in executor_errors(root, action)] == ['executor_node_missing']


def test_smoke_launch_is_the_host_s_own(root):
    two_nodes(root)
    executor().seal_orders(root)
    assert executor_errors(root, full_action('N1', 'smoke')) == []


class SelfCheckingWorkers(Workers):
    """Runs every sealed self-check through the worker's own broker before closing the attempt."""

    def __call__(self, rundir, spec, **options):
        from ravel.workflow import tool_gate, role_registry
        from ravel.workflow.transports import cli_worker
        from ravel.workflow import transport_registry
        ws = agent_worker.workspace(rundir, spec['node_id'], spec['attempt'])
        original = agent_worker.finish

        def finish(run, value, **kwargs):
            order = json.loads((ws / 'inputs/work-order.json').read_text())
            card = role_registry.load(spec['role']['id'])
            belt = cli_worker.toolbelt_for(card, transport_registry.load('claude-cli-worker'), False)
            target = tool_gate.production_broker(run, ws, tools=belt['tools'], role=card['id'],
                                                node_id=spec['node_id'], attempt=spec['attempt'], max_calls=100)
            self.checks = []
            for n, check in enumerate(order['self_check']):
                reply = target.call({'call_id': f'c{n}', 'action': 'check run',
                                     'args': {'check_id': check}})
                self.checks.append((check, reply['status']))
            return original(run, value, **kwargs)
        agent_worker.finish, saved = finish, agent_worker.finish
        try:
            return super().__call__(rundir, spec, **options)
        finally:
            agent_worker.finish = saved


def test_full_launch_with_non_empty_self_checks_earns_an_ok_receipt(root, monkeypatch):
    from ravel.validation import validate_cutflow
    from executor_fixtures import write
    write(root / 'inputs/trap_sweep.json', {'traps_checked': [f'T{i}' for i in range(1, 13)]})
    seen = []

    def cutflow(argv=None):
        seen.append(argv)
        out = Path(argv[argv.index('--out') + 1])
        out.write_text('synthetic cutflow')
        out.with_suffix('.json').write_text(json.dumps({'verdict': 'PASS'}))

    monkeypatch.setattr(validate_cutflow, 'main', cutflow)
    write(root / 'inputs/signal.yoda', {})
    (root / 'inputs/tables').mkdir()
    options = {'signal': 'inputs/signal.yoda', 'routine': 'synthetic', 'sigma_pb': 1,
               'lumi_fb': 1, 'tables_dir': 'inputs/tables', 'grid': 'synthetic',
               'm_parent': 100, 'm_lsp': 0, 'srs': 'A'}
    plan(root, nodes=[N1, {**N2, 'fields': [{'pointer': '/check_inputs',
                 'value': {'check:validation.validate_cutflow': options},
                 'authority': 'source_document', 'evidence': 'synthetic inputs'}]}],
         edges=[edge('N1', 'N2')])
    executor().seal_orders(root)
    assert executor().load_order(root, 'N2')['self_check']
    workers = SelfCheckingWorkers(root)
    monkeypatch.setattr(agent_worker, 'dispatch', workers)
    receipt = executor().dispatch(root, 'N2')
    assert seen
    assert all(status == 'ok' for _, status in workers.checks), workers.checks
    from ravel.workflow import broker
    receipts = [r['record'] for r in broker.ledger(root, 'broker')]
    checks = [broker.verify_broker_receipt(root, {'path': r['path'], 'sha256': r['sha256']}) for r in receipts]
    assert set(executor().load_order(root, 'N2')['self_check']) <= {r['validator_id'] for r in checks}
    assert receipt['status'] == 'ok' and receipt['outcome']['computed_checks']['self_checks'], receipt['outcome']


def test_full_launch_with_the_role_worker_receipt_passes(root, monkeypatch):
    two_nodes(root)
    no_self_checks(monkeypatch)
    executor().seal_orders(root)
    workers = Workers(root)
    monkeypatch.setattr(agent_worker, 'dispatch', workers)
    receipt = executor().dispatch(root, 'N2')
    assert receipt['status'] == 'ok' and receipt['role']['id'] == 'shower-detector'
    assert workers.calls[0]['map_id'] == 'production:N2'
    assert executor_errors(root, full_action()) == []


def test_a_failed_worker_receipt_earns_no_launch(root, monkeypatch):
    two_nodes(root)
    no_self_checks(monkeypatch)
    executor().seal_orders(root)
    monkeypatch.setattr(agent_worker, 'dispatch', Workers(root, fail_once={'shower-detector'}))
    assert executor().dispatch(root, 'N2')['status'] == 'failed'
    assert [e.code for e in executor_errors(root, full_action())] == ['executor_receipt_missing']


def test_host_waiver_counts_and_is_listed_for_checkin2_and_delivery(root):
    two_nodes(root)
    executor().seal_orders(root)
    executor().waive(root, 'N2', 'the host wrote the shower card at the operator\'s request')
    assert executor_errors(root, full_action()) == []
    listed = executor().host_authored_nodes(root)
    assert [(r['node_id'], r['executor'], r['counts']) for r in listed] == [('N2', 'host', True)]
    with pytest.raises(ValueError, match='already has a host waiver'):
        executor().waive(root, 'N2', 'again')


def test_delegated_waiver_needs_an_r2_receipt(root, monkeypatch):
    from ravel.workflow import rdj_loop
    two_nodes(root, delegated=True)
    executor().seal_orders(root)
    executor().waive(root, 'N2', 'host-authored card')
    assert [e.code for e in executor_errors(root, full_action())] == ['executor_waiver_unauthorized']
    seen = []

    def receipt(cls):
        def found(rundir, gate, action):
            seen.append(action)
            return {'case': {'risk': {'class': cls}}}
        return found
    monkeypatch.setattr(rdj_loop, 'authorizing_receipt', receipt('R1'))
    assert [e.code for e in executor_errors(root, full_action())] == ['executor_waiver_unauthorized']
    monkeypatch.setattr(rdj_loop, 'authorizing_receipt', receipt('R2'))
    assert executor_errors(root, full_action()) == []
    assert seen[-1]['kind'] == 'host_waiver' and seen[-1]['floor'] == 'R2'
    assert seen[-1]['digest'] == executor().waiver_action(root, 'N2')['digest']


def test_launch_stage_refuses_before_the_supervisor(root, monkeypatch):
    from ravel.workflow import stage_supervisor
    two_nodes(root)
    executor().seal_orders(root)
    started = []
    monkeypatch.setattr(stage_supervisor, 'supervise', lambda *a, **k: started.append(a) or 0)
    with pytest.raises(executor().ExecutorRefused, match='executor_receipt_missing'):
        executor().launch_stage(root, 'N2', stage='shower', cmd=[sys.executable, '-c', 'pass'], events=10,
                                rung='full', gate_check=None)
    assert started == []


def test_stage_receipt_and_module_origin_are_registered_by_the_executor(tmp_path):
    """Acceptance 5: before registration the stage anchor is 'generated'; after, it resolves with its origin."""
    from rdj_fixtures import Run, TOOL
    from ravel.workflow import execution, rdj_anchor
    run = Run(tmp_path.resolve() / 'run')
    run.stage('limits', 'outputs/limits.json', {'mu': 1.2}, register=False)
    attempt = execution.load_execution(run.root)['stages']['limits']['attempt_id']
    with pytest.raises(rdj_anchor.Generated):
        rdj_anchor.stage_receipt(run.root, f'stage:limits:{attempt}')
    registered = executor().register_stage(run.root, 'limits')
    assert registered['receipt_id'] == f'stage:limits:{attempt}'
    record = rdj_anchor.stage_receipt(run.root, f'stage:limits:{attempt}')
    assert record['command'] == TOOL
    origin = executor().registered_origin(run.root, 'limits', attempt)
    from ravel.physics import pyhf_exclude
    assert origin['module'] == 'ravel.physics.pyhf_exclude'
    assert origin['module_origin'] == str(Path(pyhf_exclude.__file__).resolve())
    assert executor().register_stage(run.root, 'limits') == registered  # idempotent
    rows = [r['record'] for r in rdj_custody.rows(run.root, 'stages')]
    assert len(rows) == 2 and rows[1]['kind'] == 'module_origin'


def test_module_origin_outside_ravel_is_not_recorded():
    assert executor().module_origin([sys.executable, '-c', 'pass']) is None
    assert executor().module_origin(['/usr/bin/env', 'python', '-m', 'ravel.x']) is None
    with pytest.raises(ValueError, match='not installed'):
        executor().module_origin([sys.executable, '-m', 'ravel.no_such_module_here'])


HOLD = ('import sys,time\n'
        'from ravel.workflow import machine_lease as m\n'
        'with m.held("earlier native job"):\n'
        '    print("held", flush=True)\n'
        '    time.sleep(float(sys.argv[1]))\n')
COUNT = [sys.executable, '-c', 'import json;json.dump({"n":3},open("outputs/n.json","w"))']


def test_second_native_launch_through_the_executor_waits_on_the_lease(tmp_path, monkeypatch, capfd):
    """Acceptance 3: inert holder process; the executor's supervised launch waits, then runs and registers."""
    from test_execution_backend_supervised import approved_root
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2026-10-08T00:00:00Z')
    root = approved_root(tmp_path)
    (root / 'outputs').mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    holder = subprocess.Popen([sys.executable, '-c', HOLD, '3'], stdout=subprocess.PIPE, text=True, env=env,
                              start_new_session=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        started = time.monotonic()
        result = executor().launch_stage(root, 'N1', stage='count', cmd=COUNT, events=10, rung='smoke',
                                         outputs=['outputs/n.json'], cwd=str(root), kill_secs=60.0, poll=0.1,
                                         grace=3.0, lease_wait=60.0)
        assert result['exit_code'] == 0 and time.monotonic() - started >= 1.0
        assert holder.wait(timeout=30) == 0
        assert 'waiting for the machine lease' in capfd.readouterr().err
        assert result['registered']['receipt_id'].startswith('stage:count:')
        assert json.loads((root / 'outputs/n.json').read_text()) == {'n': 3}
    finally:
        if holder.poll() is None:
            os.killpg(holder.pid, 9)
            holder.wait()


def test_cli_next_and_waive(root, capsys):
    two_nodes(root)
    assert executor().main(['seal', '--rundir', str(root)]) == 0
    capsys.readouterr()
    assert executor().main(['next', '--rundir', str(root)]) == 0
    assert json.loads(capsys.readouterr().out)['node_id'] == 'N1'
    assert executor().main(['waive', '--rundir', str(root), '--node', 'N1', '--reason', 'host smoke card']) == 0
    capsys.readouterr()
    assert executor().main(['host-authored', '--rundir', str(root)]) == 0
    assert json.loads(capsys.readouterr().out)[0]['node_id'] == 'N1'


@pytest.mark.parametrize('selected, status', [(100, 'ok'), (400, 'failed')])
def test_cutflow_validator_verdict_controls_production_receipt(root, monkeypatch, selected, status):
    from types import SimpleNamespace
    from executor_fixtures import write
    monkeypatch.setitem(sys.modules, 'yoda', SimpleNamespace(read=lambda path: {
        '/synthetic/A': SimpleNamespace(val=lambda: selected)}))
    write(root / 'inputs/trap_sweep.json', {'traps_checked': [f'T{i}' for i in range(1, 13)]})
    write(root / 'inputs/signal.yoda', {})
    tables = root / 'inputs/tables'
    tables.mkdir()
    (tables / 'submission.yaml').write_text(
        'description: acceptance times efficiency SRA synthetic\ndata_file: table.yaml\n')
    (tables / 'table.yaml').write_text(
        'independent_variables:\n- values: [{value: 100}]\n- values: [{value: 0}]\n'
        'dependent_variables:\n- values: [{value: 0.1}]\n')
    options = {'signal': 'inputs/signal.yoda', 'routine': 'synthetic', 'sigma_pb': 1,
               'lumi_fb': 1, 'tables_dir': 'inputs/tables', 'grid': 'synthetic',
               'm_parent': 100, 'm_lsp': 0, 'srs': 'A', 'driving_sr_override': 'A'}
    plan(root, nodes=[N1, {**N2, 'fields': [{'pointer': '/check_inputs',
                 'value': {'check:validation.validate_cutflow': options},
                 'authority': 'source_document', 'evidence': 'synthetic inputs'}]}],
         edges=[edge('N1', 'N2')])
    executor().seal_orders(root)
    monkeypatch.setattr(agent_worker, 'dispatch', SelfCheckingWorkers(root))
    receipt = executor().dispatch(root, 'N2')
    assert receipt['status'] == status, receipt['outcome']
    assert receipt['outcome']['computed_checks']['self_checks'] == (status == 'ok')
    assert bool(receipt['credited_outputs']) == (status == 'ok')


def test_trap_references_resolve_to_the_declared_sweep_check():
    from ravel.workflow import role_registry
    assert role_registry.resolve_self_checks(['trap:T6', 'trap:T10']) == [
        'check:validation.validate_run_state.check_trap_sweep']
    with pytest.raises(ValueError, match='unknown trap'):
        role_registry.resolve_self_checks(['trap:T99'])



def test_self_check_parameters_use_the_admitted_plan_field_schema(root):
    from jsonschema import Draft202012Validator
    from ravel.validation.intake_records import NODE
    fields = [{'pointer': '/check_inputs', 'value': {
        'check:validation.input_closure.check': {'fit': {}, 'reference': {}}},
        'authority': 'source_document', 'evidence': 'synthetic inputs'}]
    Draft202012Validator(NODE['properties']['fields']).validate(fields)
    plan(root, nodes=[{**N2, 'fields': fields}])
    executor().seal_orders(root)
    assert executor().load_order(root, 'N2')['check_inputs'] == fields[0]['value']
