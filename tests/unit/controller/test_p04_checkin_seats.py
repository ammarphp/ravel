"""Review seats the controller runs as steps of their own under one step id are distinct seats.

A check-in's seats (the CHECK-IN 3 triad, for one) share a step id: each is a review step whose ``parameters.seat_kind``
is review. Each needs its own worker node, reservation, records, final-record custody and ledger seat
(``seat:<role>:1``); otherwise a second card's attempt replays or collides with the first card's.
"""
from __future__ import annotations

from test_p04_support import (context, graphs, inert_worker, install_plan, make_step, records, run_env,  # noqa: F401
                              services_installed)

ROLES = ('physics-critic', 'physics-decider')


def _seat(role, plan_sha):
    return make_step('final_review', kind='review', role=role,
                     inputs=({'artifact': 'inputs/controller-plan.json', 'sha256': None},),
                     outputs=((f'outputs/review-final-{role}.json', 'review-findings'),),
                     parameters={'subject_plan_sha256': plan_sha, 'purpose': 'final', 'seat_kind': 'review',
                                 'review_kind': 'final'})


def _invoke(env, step, plan_sha, role):
    """One invocation of the step graph per seat, as the controller keys each check-in seat's invocation."""
    from ravel.controller.step import GRAPH_ID, _controller_scope
    from ravel.controller.step.services import bound
    from ravel.workflow import graph_substrate
    ctx = context(env.store, env.run_dir, plan_sha)
    with bound(env.store), _controller_scope(ctx['run_id']):
        return graph_substrate.run(env.store.path('step-scopes', 'final_review', role, '1'), GRAPH_ID,
                                   {'run_id': ctx['run_id']}, input={'step': step, 'context': ctx})


def _receipt_diagnostic(env):
    import json
    from ravel.workflow import agent_worker, broker
    rows = []
    for entry in broker.ledger(env.run_dir, 'worker-receipts'):
        pin = entry['record']['pin']
        receipt = json.loads(broker.locate(env.run_dir, pin['path']).read_text())
        ws = agent_worker.workspace(env.run_dir, receipt['node_id'], receipt['attempt'])
        tools = ws / 'scratch/tools.json'
        rows.append({'role': receipt['role']['id'], 'status': receipt['status'],
                     'failure': receipt.get('failure'), 'broker': receipt.get('broker'),
                     'outcome': receipt.get('outcome'), 'credited_outputs': receipt.get('credited_outputs'),
                     'served_tools': json.loads(tools.read_text()) if tools.is_file() else None})
    return rows


def test_two_check_in_seats_under_one_step_id_are_distinct_seats(run_env, inert_worker, graphs):
    plan_sha = install_plan(run_env.store, [make_step('s0')])
    (run_env.run_dir / 'inputs' / 'controller-plan.json').write_text('{"plan": "fictional"}\n')
    for role in ROLES:
        observation = _invoke(run_env, _seat(role, plan_sha), plan_sha, role)
        assert not observation.get('interrupts'), observation
    credits = [r for r in records(run_env.store, 'step-credit') if r.get('step_id') == 'final_review']
    assert sorted(r['own']['query']['role'] for r in credits if r['credited']) == sorted(ROLES), (credits, _receipt_diagnostic(run_env))
    seats = [f'seat:{role}:1' for role in ROLES]
    dispatched = [r for r in records(run_env.store, 'step-dispatch') if r.get('step_id') == 'final_review']
    assert sorted(r['seat'] for r in dispatched) == seats and len({r['node_id'] for r in dispatched}) == 2
    reservations = [r['key'] for r in records(run_env.store, 'budget-reservation') if r.get('step_id') == 'final_review']
    assert sorted(reservations) == [f'final_review/1/{seat}' for seat in seats]
    adopted = {r['artifact'] for r in records(run_env.store, 'custody') if r.get('step_id') == 'final_review'}
    assert {f'final_review:final-record-{role}.json' for role in ROLES} <= adopted
    assert 'final_review:final-record.json' not in adopted
    materialised = [c[2] for c in run_env.fakes['ledger'].calls if c[0] == 'materialise' and c[2].get('step') == 'final_review']
    assert sorted({c['seat'] for c in materialised}) == seats
    assert {c['seat']: c['role'] for c in materialised} == {f'seat:{role}:1': role for role in ROLES}
    # The critic's normalization check has no subject here; it is not applicable only because the review policy's
    # stored classification says so (this fixture's contract derives no normalization audit), never by default.
    [critic] = [r for r in records(run_env.store, 'step-validation') if r.get('seat') == 'seat:physics-critic:1'
                and r.get('report')]
    [result] = [r for r in critic['report']['results'] if r['check_id'] == 'check:physics.normalization_ledger.check']
    assert result['status'] == 'not_applicable' and result['reason'] == 'policy_not_applicable', result
    [classification] = [row['record'] for row in run_env.store.scan('review-classification')
                        if row['id'] == result['classification']['record']]
    assert classification['checks']['check:physics.normalization_ledger.check'] == {
        'applies': False, 'rows': [5], 'points': []}


def test_a_review_step_of_a_plan_keeps_its_producer_seat(run_env, inert_worker, graphs):
    step = make_step('r1', kind='review', role='physics-decider', outputs=(('outputs/findings.json', 'findings'),))
    from test_p04_support import run_step
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'completed', (outcome, _receipt_diagnostic(run_env))
    materialised = [c[2] for c in run_env.fakes['ledger'].calls if c[0] == 'materialise' and c[2].get('step') == 'r1']
    assert {c['seat'] for c in materialised} == {'producer'}
