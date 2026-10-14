"""A production worker that already has a workspace is dispatched again only under its sealed order.

The dispatcher record of an earlier materialization does not carry the sealed-order requirement
forward by itself: the dispatch command checks the node's sealed order as it is now before it
returns the existing workspace, so an attempt without the order, or with an order that was
replaced, never reaches its supervisor again.
"""
import json

import pytest

from ravel.workflow import agent_worker
from test_self_check_credit import (  # noqa: F401
    advisory, executor, gate_codes, inert_launch, legacy_order, orderless, root)


def materialized_before_the_rule(root, spec):
    """The dispatcher record and workspace an earlier release wrote for this spec, order unchecked."""
    with pytest.MonkeyPatch.context() as earlier:
        earlier.setattr(agent_worker, '_require_sealed_order', lambda *a: None)
        workspace = agent_worker.materialize(root, spec)
    assert agent_worker.dispatched(root, spec['node_id'], spec['attempt'])
    return workspace


def dispatch_command(root, spec):
    path = root.parent / f"spec-{spec['node_id']}-{spec['attempt']}.json"
    path.write_text(json.dumps(spec))
    return agent_worker.main(['dispatch', '--rundir', str(root), '--spec', str(path)])


def no_supervisor(monkeypatch):
    monkeypatch.setattr(agent_worker.subprocess, 'Popen', lambda *a, **kw: pytest.fail('the supervisor was started'))
    monkeypatch.setattr(agent_worker, 'finish', lambda *a, **kw: pytest.fail('the attempt was finished'))


def launch_record(root, spec):
    return agent_worker._record(root, spec['node_id'], spec['attempt'])['launch']


def test_orderless_production_worker_materialized_earlier_is_refused_when_dispatched_again(root, monkeypatch, capsys):
    executor().seal_orders(root)
    spec = orderless(root)
    workspace = materialized_before_the_rule(root, spec)
    no_supervisor(monkeypatch)
    with pytest.raises(ValueError, match='sealed work order'):
        dispatch_command(root, spec)
    with pytest.raises(ValueError, match='sealed work order'):
        agent_worker.launch(root, spec, launch_spec={'argv': ['/inert']}, wait=False)
    assert launch_record(root, spec) is None and not (workspace / 'receipt.json').exists()
    assert gate_codes(root) == ['executor_receipt_missing']


def test_production_worker_with_an_unsealed_pinned_order_is_refused_when_dispatched_again(root, monkeypatch, capsys):
    executor().seal_orders(root)
    spec = executor().worker_spec(root, 'N2')
    spec['work_order'] = legacy_order(root)
    materialized_before_the_rule(root, spec)
    no_supervisor(monkeypatch)
    with pytest.raises(ValueError, match='sealed work order'):
        dispatch_command(root, spec)
    assert launch_record(root, spec) is None


@pytest.mark.parametrize('change', ['resealed', 'removed', 'edited'])
def test_production_worker_whose_sealed_order_changed_is_refused_when_dispatched_again(root, monkeypatch, capsys, change):
    executor().seal_orders(root)
    spec = executor().worker_spec(root, 'N2')
    agent_worker.materialize(root, spec)  # a valid dispatch: the order was the sealed one
    path = executor().order_path(root, 'N2')
    if change == 'removed':
        path.unlink()
    else:
        order = json.loads(path.read_text())
        order['budgets']['max_turns'] += 1
        if change == 'resealed':
            order['order_sha256'] = executor()._order_digest(order)
        path.write_text(json.dumps(order))
    no_supervisor(monkeypatch)
    with pytest.raises(ValueError, match='sealed work order'):
        dispatch_command(root, spec)
    assert launch_record(root, spec) is None


def test_finished_attempt_of_a_replaced_order_is_not_returned_by_the_dispatch_command(root, monkeypatch, capsys):
    from executor_fixtures import no_self_checks
    no_self_checks(monkeypatch)
    executor().seal_orders(root)
    inert_launch(monkeypatch)
    spec = executor().worker_spec(root, 'N2')
    assert dispatch_command(root, spec) == 0
    capsys.readouterr()
    assert gate_codes(root) == []
    path = executor().order_path(root, 'N2')
    order = json.loads(path.read_text())
    order['budgets']['max_turns'] += 1
    order['order_sha256'] = executor()._order_digest(order)
    path.write_text(json.dumps(order))
    with pytest.raises(ValueError, match='sealed work order'):
        dispatch_command(root, spec)
    assert gate_codes(root) == ['executor_receipt_missing']


def test_production_worker_with_its_current_sealed_order_is_reattached(root, monkeypatch, capsys):
    """The valid case: an attempt materialized under the node's sealed order continues."""
    from executor_fixtures import no_self_checks
    no_self_checks(monkeypatch)
    executor().seal_orders(root)
    spec = executor().worker_spec(root, 'N2')
    workspace = agent_worker.materialize(root, spec)
    assert agent_worker.materialize(root, spec) == workspace
    inert_launch(monkeypatch)
    assert dispatch_command(root, spec) == 0
    capsys.readouterr()
    assert agent_worker.load_receipt(root, 'N2', 1)['status'] == 'ok' and gate_codes(root) == []
    # A finished attempt under the unchanged order is returned again.
    assert dispatch_command(root, spec) == 0


def test_worker_outside_the_production_executor_is_reattached_without_a_sealed_order(root, monkeypatch, capsys):
    executor().seal_orders(root)
    spec = advisory(orderless(root))
    workspace = agent_worker.materialize(root, spec)
    assert agent_worker.materialize(root, spec) == workspace
    inert_launch(monkeypatch)
    assert dispatch_command(root, spec) == 0
    capsys.readouterr()
    assert gate_codes(root) == ['executor_receipt_missing']
