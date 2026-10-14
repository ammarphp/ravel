"""Self-check receipts and the credit they earn, driven through broker registration, the worker
dispatch entry point, ``finish`` and the production gate. Synthetic checks and inert workers only.
"""
import json

import pytest

from ravel.workflow import broker as broker_module
from test_worker_broker import make

ROUTE_CHECK = 'check:validation.validate_run_state.check_route'
DOCUMENT_CHECK = 'review.normalization_recompute'


def receipt_of(target):
    return target.verify_ledger()[-1]


def registered(tmp_path, monkeypatch, handler, *, scalar):
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check')
    if scalar:
        target.register('check', handler, derivation='registered_validator', validator_id=ROUTE_CHECK)
        args = {}
    else:
        target.register('check', handler, derivation='registered_validator', validator_ids=[ROUTE_CHECK])
        args = {'check_id': ROUTE_CHECK}
    reply = target.call({'call_id': 'self-check', 'action': 'check', 'args': args})
    return reply, receipt_of(target)


# ---------------------------------------------------------------- one execution-aware receipt mechanism

@pytest.mark.parametrize('scalar', [True, False])
@pytest.mark.parametrize('value', [{}, {'validator_executed': False}, {'validator_executed': False, 'exit_status': 0},
                                   {'exit_status': 0}, {'validator_executed': 'yes', 'exit_status': 0},
                                   {'validator_executed': 1, 'exit_status': 0}])
def test_validator_that_did_not_run_earns_no_ok_receipt_and_no_identity(tmp_path, monkeypatch, scalar, value):
    reply, receipt = registered(tmp_path, monkeypatch, lambda args: dict(value), scalar=scalar)
    assert reply['status'] == 'failed'
    assert receipt['status'] == 'failed' and receipt['validator_id'] is None
    assert receipt['exit_status'] != 0


@pytest.mark.parametrize('scalar', [True, False])
def test_validator_success_needs_explicit_execution_and_outcome(tmp_path, monkeypatch, scalar):
    reply, receipt = registered(tmp_path, monkeypatch, lambda args: {'validator_executed': True, 'exit_status': 0},
                                scalar=scalar)
    assert reply['status'] == 'ok'
    assert receipt['validator_id'] == ROUTE_CHECK and receipt['exit_status'] == 0


@pytest.mark.parametrize('scalar', [True, False])
def test_executed_validator_without_a_stated_outcome_fails_with_its_identity(tmp_path, monkeypatch, scalar):
    reply, receipt = registered(tmp_path, monkeypatch, lambda args: {'validator_executed': True}, scalar=scalar)
    assert reply['status'] == 'failed'
    assert receipt['validator_id'] == ROUTE_CHECK and receipt['exit_status'] != 0


@pytest.mark.parametrize('scalar', [True, False])
def test_failing_validator_keeps_its_identity(tmp_path, monkeypatch, scalar):
    reply, receipt = registered(tmp_path, monkeypatch, lambda args: {'validator_executed': True, 'exit_status': 1},
                                scalar=scalar)
    assert reply['status'] == 'failed'
    assert receipt['validator_id'] == ROUTE_CHECK and receipt['exit_status'] == 1


@pytest.mark.parametrize('scalar', [True, False])
def test_validator_that_raises_after_entry_keeps_its_identity(tmp_path, monkeypatch, scalar):
    def entered_then_raised(args):
        raise broker_module.ValidatorRaised('synthetic failure inside the validator')
    reply, receipt = registered(tmp_path, monkeypatch, entered_then_raised, scalar=scalar)
    assert reply['status'] == 'failed'
    assert receipt['validator_id'] == ROUTE_CHECK and receipt['exit_status'] != 0


@pytest.mark.parametrize('scalar', [True, False])
def test_handler_that_raises_before_the_validator_names_no_validator(tmp_path, monkeypatch, scalar):
    def raised_before_entry(args):
        raise ValueError('inputs could not be read')
    reply, receipt = registered(tmp_path, monkeypatch, raised_before_entry, scalar=scalar)
    assert reply['status'] == 'failed' and receipt['validator_id'] is None


def test_other_actions_keep_their_default_success(tmp_path, monkeypatch):
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('effect')
    target.register('effect', lambda args: {})
    assert target.call({'call_id': 'effect', 'action': 'effect', 'args': {}})['status'] == 'ok'
    assert receipt_of(target)['validator_id'] is None


def test_document_validator_that_raises_keeps_its_exact_identity(tmp_path, monkeypatch):
    from ravel.workflow import review_projection_checks

    def raises(doc, *, check_id):
        raise RuntimeError('the validator failed on this document')
    monkeypatch.setitem(review_projection_checks.CHECKS, DOCUMENT_CHECK, raises)
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    review_projection_checks.register(target, {'id': 'normalization-auditor', 'must_check': [], 'tools': {}})
    (target.workspace / 'inputs/check.json').write_text(json.dumps({'reported_yield': 1}))
    reply = target.call({'call_id': 'raise', 'action': 'check run',
                         'args': {'check_id': DOCUMENT_CHECK, 'paths': ['inputs/check.json']}})
    assert reply['status'] == 'failed'
    receipt = receipt_of(target)
    assert receipt['validator_id'] == DOCUMENT_CHECK and receipt['exit_status'] != 0


def test_document_check_whose_input_cannot_be_read_names_no_validator(tmp_path, monkeypatch):
    from ravel.workflow import review_projection_checks
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    review_projection_checks.register(target, {'id': 'normalization-auditor', 'must_check': [], 'tools': {}})
    (target.workspace / 'inputs/check.json').write_text('{not json')
    reply = target.call({'call_id': 'unreadable', 'action': 'check run',
                         'args': {'check_id': DOCUMENT_CHECK, 'paths': ['inputs/check.json']}})
    assert reply['status'] == 'failed' and receipt_of(target)['validator_id'] is None


# ---------------------------------------------------------------- work orders, self-check credit and production credit

import sys
from pathlib import Path

from ravel.workflow import agent_worker, decision_gate, role_registry
from executor_fixtures import edge, no_self_checks, plan, run_root
from test_agent_worker import put

N1 = {'id': 'N1', 'operation': 'model-events', 'rung': 'smoke'}
N2 = {'id': 'N2', 'operation': 'event-production', 'rung': 'full'}
ROLE = 'shower-detector'


def executor():
    from ravel.workflow import production_executor
    return production_executor


@pytest.fixture
def root(tmp_path):
    value = run_root(tmp_path)
    plan(value, nodes=[N2, N1], edges=[edge('N1', 'N2')])
    return value


def gate_codes(root):
    action = executor().launch_action('N2', stage='shower', cmd=[sys.executable, '-c', 'pass'], rung='full')
    return [e.code for e in decision_gate.check(root, 'launch', action) if e.provider == 'executor']


def inert_launch(monkeypatch, *, checks=()):
    """Stand in for the sandboxed launch only: the dispatch command, materialization, the worker's
    own production broker, ``finish`` and the receipt are the real ones."""
    from ravel.workflow import tool_gate, transport_registry
    from ravel.workflow.transports import cli_worker
    seen = {}

    def launch(rundir, spec, **options):
        ws = agent_worker.workspace(rundir, spec['node_id'], spec['attempt'])
        for output in spec['declared_outputs']:
            put(rundir, ws, output['path'], 'synthetic output')
        card = role_registry.load(spec['role']['id'])
        belt = cli_worker.toolbelt_for(card, transport_registry.load('claude-cli-worker'), False)
        # The broker a supervised worker gets (agent_worker.supervise builds it the same way).
        target = tool_gate.production_broker(rundir, ws, tools=belt['tools'], role=card['id'],
                                            node_id=spec['node_id'], attempt=spec['attempt'], max_calls=100)
        seen['replies'] = [target.call({'call_id': f'check-{n}', 'action': 'check run', 'args': {'check_id': check}})
                           for n, check in enumerate(checks)]
        return agent_worker.finish(rundir, spec, final={'completed': True}, execution={'exit_status': 0})
    monkeypatch.setattr(agent_worker, 'launch', launch)
    return seen


def dispatch_command(root, spec, capsys):
    """``ravel work dispatch --spec``: the retained worker command."""
    path = root.parent / f"spec-{spec['node_id']}-{spec['attempt']}.json"
    path.write_text(json.dumps(spec))
    code = agent_worker.main(['dispatch', '--rundir', str(root), '--spec', str(path)])
    capsys.readouterr()
    return code, agent_worker.load_receipt(root, spec['node_id'], spec['attempt'])


def advisory(spec):
    """The same role and node dispatched outside the production executor (no plan-node claim)."""
    spec['parent']['map_id'] = None
    return spec


def orderless(root, attempt=1):
    spec = executor().worker_spec(root, 'N2', attempt)
    spec['work_order'] = None
    return spec


def test_production_worker_without_its_sealed_order_is_refused_at_dispatch(root, monkeypatch, capsys):
    executor().seal_orders(root)
    assert role_registry.self_checks(ROLE)
    monkeypatch.setattr(agent_worker, 'launch', lambda *a, **kw: pytest.fail('the supervisor was launched'))
    path = root.parent / 'orderless.json'
    path.write_text(json.dumps(orderless(root)))
    with pytest.raises(ValueError, match='sealed work order'):
        agent_worker.main(['dispatch', '--rundir', str(root), '--spec', str(path)])
    assert not agent_worker.dispatched(root, 'N2', 1)
    assert not agent_worker.workspace(root, 'N2', 1).exists()
    assert gate_codes(root) == ['executor_receipt_missing']
    # Naming another node's sealed order, or an order that is not the sealed one, is refused as well.
    other = executor().worker_spec(root, 'N2')
    other['work_order'] = executor().worker_spec(root, 'N1')['work_order']
    unsealed = executor().worker_spec(root, 'N2')
    unsealed['work_order'] = legacy_order(root)
    for spec in (other, unsealed):
        path.write_text(json.dumps(spec))
        with pytest.raises(ValueError, match='work order'):
            agent_worker.main(['dispatch', '--rundir', str(root), '--spec', str(path)])
    assert not agent_worker.dispatched(root, 'N2', 1)


def test_finish_gives_a_production_worker_without_an_order_no_self_check_credit(root, monkeypatch):
    """Defence behind the dispatch refusal: a dispatcher that skipped it still earns nothing."""
    executor().seal_orders(root)
    spec = orderless(root)
    monkeypatch.setattr(agent_worker, '_require_sealed_order', lambda *a: None)
    ws = agent_worker.materialize(root, spec)
    for output in spec['declared_outputs']:
        put(root, ws, output['path'], 'synthetic output')
    receipt = agent_worker.finish(root, spec, final={'completed': True}, execution={'exit_status': 0})
    assert receipt['outcome']['computed_checks']['self_checks'] is False and receipt['status'] == 'failed'
    assert gate_codes(root) == ['executor_receipt_missing']


def test_ok_receipt_without_the_sealed_order_earns_no_production_credit(root, monkeypatch, capsys):
    """An advisory worker of the node's role, dispatched without an order through the worker
    command, gets its own receipt; it cannot satisfy the production gate."""
    executor().seal_orders(root)
    inert_launch(monkeypatch)
    code, receipt = dispatch_command(root, advisory(orderless(root)), capsys)
    assert receipt['status'] == 'ok' and receipt['role']['id'] == ROLE and receipt['node_id'] == 'N2'
    assert gate_codes(root) == ['executor_receipt_missing']
    assert executor().worker_receipt(root, 'N2') is None


def test_worker_bound_to_the_sealed_order_earns_production_credit(root, monkeypatch, capsys):
    no_self_checks(monkeypatch)
    executor().seal_orders(root)
    inert_launch(monkeypatch)
    code, receipt = dispatch_command(root, executor().worker_spec(root, 'N2'), capsys)
    assert code == 0 and receipt['status'] == 'ok'
    assert gate_codes(root) == []
    assert executor().worker_receipt(root, 'N2')['attempt'] == 1


def test_receipt_of_a_resealed_or_replaced_order_stops_counting(root, monkeypatch, capsys):
    no_self_checks(monkeypatch)
    executor().seal_orders(root)
    inert_launch(monkeypatch)
    dispatch_command(root, executor().worker_spec(root, 'N2'), capsys)
    assert gate_codes(root) == []
    path = executor().order_path(root, 'N2')
    order = json.loads(path.read_text())
    order['budgets']['max_turns'] += 1
    order['order_sha256'] = executor()._order_digest(order)
    path.write_text(json.dumps(order))  # a different order under the node's name
    assert executor().worker_receipt(root, 'N2') is None
    assert gate_codes(root) == ['executor_receipt_missing']


def legacy_order(root, *, role=ROLE, node_id='N2', self_check=()):
    """A pinned work order in the retained worker input format, outside the sealed-order store."""
    name = f'inputs/legacy-order-{role}-{node_id}.json'
    (root / name).write_text(json.dumps({'kind': 'work-order', 'node_id': node_id, 'role': role,
                                         'self_check': list(self_check), 'check_inputs': {}}))
    return {'path': name, 'sha256': broker_module.sha(root / name)}


def legacy_spec(root, pin, attempt=1):
    spec = advisory(executor().worker_spec(root, 'N2', attempt))
    spec['work_order'] = pin
    return spec


def test_legacy_pinned_order_is_accepted_at_dispatch_and_by_the_worker_broker(root, monkeypatch, capsys):
    executor().seal_orders(root)
    (root / 'inputs/trap_sweep.json').write_text(json.dumps({'traps_checked': [f'T{i}' for i in range(1, 13)]}))
    trap = 'check:validation.validate_run_state.check_trap_sweep'
    assert trap in role_registry.self_checks(ROLE)
    seen = inert_launch(monkeypatch, checks=[trap])
    code, receipt = dispatch_command(root, legacy_spec(root, legacy_order(root, self_check=[trap])), capsys)
    # The broker was built over the dispatcher-pinned order and ran the role's check.
    assert [reply['status'] for reply in seen['replies']] == ['ok'], seen['replies']
    assert receipt['outcome']['computed_checks']['self_checks'] is True
    assert receipt['status'] == 'ok' and code == 0
    # A legacy order is a valid worker input; it is not the node's sealed order.
    assert gate_codes(root) == ['executor_receipt_missing']


def test_legacy_order_grants_no_check_its_role_is_not_permitted(root, monkeypatch, capsys):
    executor().seal_orders(root)
    foreign = 'review.manuscript_audit'
    assert foreign not in role_registry.self_checks(ROLE)
    seen = inert_launch(monkeypatch, checks=[foreign])
    code, receipt = dispatch_command(root, legacy_spec(root, legacy_order(root, self_check=[foreign])), capsys)
    assert seen['replies'][0]['status'] == 'refused'
    assert receipt['outcome']['computed_checks']['self_checks'] is False and receipt['status'] == 'failed'


def test_legacy_order_for_another_role_or_node_is_refused_at_dispatch(root, monkeypatch, capsys):
    executor().seal_orders(root)
    monkeypatch.setattr(agent_worker, 'launch', lambda *a, **kw: pytest.fail('the supervisor was launched'))
    for pin, attempt in ((legacy_order(root, role='generator'), 1), (legacy_order(root, node_id='N1'), 2)):
        spec = legacy_spec(root, pin, attempt)
        path = root.parent / f'spec-{attempt}.json'
        path.write_text(json.dumps(spec))
        with pytest.raises(ValueError, match='work order belongs to a different'):
            agent_worker.main(['dispatch', '--rundir', str(root), '--spec', str(path)])
        with pytest.raises((OSError, ValueError)):
            agent_worker.load_receipt(root, 'N2', attempt)


def test_order_copy_changed_after_dispatch_is_refused_by_the_worker_broker(root, monkeypatch):
    from ravel.workflow import tool_gate, transport_registry
    from ravel.workflow.transports import cli_worker
    executor().seal_orders(root)
    spec = legacy_spec(root, legacy_order(root))
    ws = agent_worker.materialize(root, spec)
    copy = ws / 'inputs/work-order.json'
    order = json.loads(copy.read_text())
    order['self_check'] = ['review.manuscript_audit']
    copy.chmod(0o600)
    copy.write_text(json.dumps(order))
    card = role_registry.load(ROLE)
    belt = cli_worker.toolbelt_for(card, transport_registry.load('claude-cli-worker'), False)
    with pytest.raises(ValueError, match='dispatcher pinned'):
        tool_gate.production_broker(root, ws, tools=belt['tools'], role=card['id'], node_id='N2', attempt=1,
                                    max_calls=10)


def test_cutflow_self_check_keeps_a_worker_output_of_the_same_name(tmp_path, monkeypatch):
    from ravel.validation import validate_cutflow
    from ravel.workflow import review_projection_checks
    from test_agent_worker import setup, spec
    check = 'check:validation.validate_cutflow'
    worker, run = setup(tmp_path, monkeypatch)
    (run / 'inputs/tables').mkdir(parents=True)
    (run / 'inputs/signal.yoda').write_text('{}')
    options = {'signal': 'inputs/signal.yoda', 'routine': 'synthetic', 'sigma_pb': 1, 'lumi_fb': 1,
               'tables_dir': 'inputs/tables', 'grid': 'synthetic', 'm_parent': 100, 'm_lsp': 0, 'srs': 'A'}
    order = run / 'order.json'
    order.write_text(json.dumps({'kind': 'work-order', 'node_id': 'worker', 'self_check': [check],
                                 'check_inputs': {check: options}}))
    value = spec()
    value['work_order'] = {'path': 'order.json', 'sha256': broker_module.sha(order)}
    ws = worker.materialize(run, value)
    # The worker's own outputs, written through its broker under the names the validator report used.
    for name in ('outputs/cutflow-self-check.json', 'outputs/cutflow-self-check.md'):
        put(run, ws, name, 'the worker wrote this')

    def cutflow(argv=None):
        out = Path(argv[argv.index('--out') + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text('synthetic cutflow')
        out.with_suffix('.json').write_text(json.dumps({'verdict': 'PASS'}))
    monkeypatch.setattr(validate_cutflow, 'main', cutflow)
    target = broker_module.Broker(run, ws, node_id='worker', attempt=1, allowed_actions=['check run'], max_calls=20)
    review_projection_checks.register(target, {'id': value['role']['id'], 'must_check': [check], 'tools': {}})
    reply = target.call({'call_id': 'cutflow', 'action': 'check run', 'args': {'check_id': check}})
    assert reply['status'] == 'ok', reply
    assert receipt_of(target)['validator_id'] == check
    for name in ('outputs/cutflow-self-check.json', 'outputs/cutflow-self-check.md'):
        assert (ws / name).read_text() == 'the worker wrote this'
    assert json.loads((ws / 'scratch/self-checks/cutflow-self-check.json').read_text()) == {'verdict': 'PASS'}
