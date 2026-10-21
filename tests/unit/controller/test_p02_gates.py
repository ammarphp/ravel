"""P02 transition gates: the exact unmet rows of every transition, walked through one fictional run."""
from __future__ import annotations

import pytest

from ravel.controller import ledger
from ravel.controller.ledger import gates, state as state_module
from p02_support import (INTAKE, PLAN, RUN, compose_authority, fixture_catalogue, fixture_rows,  # noqa: F401
                              fixture_store, issued_waiver, row, satisfy, use_catalogue)
from test_p06_support import operator_home  # noqa: F401


def k(row, **scope):
    return ledger.instance_key(row, RUN, scope)


def unmet(store, transition):
    return [(row['entry'], row['reason']) for row in ledger.gate(store, transition)]


def pending(entry):
    return (entry, 'pending')


def walk(store):
    """The fictional run, transition by transition; every assertion names the exact unmet rows."""
    assert unmet(store, 'intake→route_select') == [('stage:intake', 'stage_not_materialised')]
    ledger.materialise(store, 'intake', INTAKE)
    assert unmet(store, 'intake→route_select') == [pending(k('X-INTAKE'))]
    satisfy(store, [k('X-INTAKE')])
    assert unmet(store, 'intake→route_select') == []
    assert unmet(store, 'route_select→plan') == [pending(k('X-ROUTE'))]
    satisfy(store, [k('X-ROUTE')])
    assert unmet(store, 'route_select->plan') == []                      # the ASCII spelling is the same edge
    assert unmet(store, 'plan→plan_review') == [('stage:plan', 'stage_not_materialised')]

    dropped = {**PLAN, 'deliverables': [{'id': 'D1', 'steps': ['s1']}]}
    ledger.materialise(store, 'plan', {'plan': dropped, 'route': 'analysis'})
    assert unmet(store, 'plan→plan_review') == [('deliverable:D2', 'deliverable_not_declared')]
    ledger.materialise(store, 'plan', {'plan': PLAN, 'route': 'analysis'})
    assert unmet(store, 'plan→plan_review') == []

    assert unmet(store, 'plan_review→checkin1') == [
        pending(k('X-SEATDERIV', step='s1')), pending(k('X-SEATDERIV', step='s2')),
        ('step:plan_review', 'review_missing')]
    critic = ledger.materialise(store, 'review', {'step': 'plan_review', 'seat': 'plan-critic', 'attempt': 1})
    satisfy(store, [k('X-SEATDERIV', step='s1'), k('X-SEATDERIV', step='s2')] + critic)
    assert unmet(store, 'plan_review→checkin1') == []

    assert unmet(store, 'checkin1→execute') == [pending(k('CHECKIN-1')), pending(k('X-CI1'))]
    satisfy(store, [k('CHECKIN-1'), k('X-CI1')])
    assert unmet(store, 'checkin1→execute') == []                        # its own GATE-approve_plan is not required
    for later in ('launch[s1]', 'escalate→execute'):                     # every later edge requires the decision
        assert unmet(store, later) == [pending(k('GATE-approve_plan'))]
    satisfy(store, [k('GATE-approve_plan')])

    ci2 = [k('CHECKIN-2', step='s1'), k('GATE-checkin2_accept', step='s1'), k('X-CI2', step='s1')]
    assert unmet(store, 'launch[s2]') == [pending(key) for key in ci2]   # bulk work waits for the waypoint's GO
    assert unmet(store, 'launch[s1]') == []

    assert unmet(store, 'checkin2→execute[s1]') == [
        pending(k('CHECKIN-2', step='s1')), pending(k('GATE-launch', step='s1')),
        pending(k('X-CI2', step='s1')), pending(k('X-OP-alpha', step='s1')), pending(k('X-STEPDOC', step='s1')),
        ('seat:s1/checker', 'seat_missing'), ('seat:s1/maker', 'seat_missing'), ('step:s1', 'step_not_entered')]
    assert unmet(store, 'checkin2→execute') == []                        # no waypoint is reached yet
    maker = ledger.materialise(store, 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 1, 'seat_kind': 'worker'})
    checker = ledger.materialise(store, 'review', {'step': 's1', 'seat': 'checker', 'attempt': 1})
    satisfy(store, maker + checker + [k('X-OP-alpha', step='s1'), k('X-STEPDOC', step='s1'),
                                      k('GATE-launch', step='s1')])
    assert unmet(store, 'checkin2→execute') == [pending(k('CHECKIN-2', step='s1')), pending(k('X-CI2', step='s1'))]
    satisfy(store, [k('CHECKIN-2', step='s1'), k('X-CI2', step='s1')])
    assert unmet(store, 'checkin2→execute[s1]') == []
    assert unmet(store, 'launch[s2]') == [pending(k('GATE-checkin2_accept', step='s1'))]
    satisfy(store, [k('GATE-checkin2_accept', step='s1')])
    assert unmet(store, 'launch[s2]') == []

    assert unmet(store, 'execute→final_review') == [
        pending(k('GATE-launch', step='s2')),
        pending(k('X-POINT', step='s2', point='p1')), pending(k('X-POINT', step='s2', point='p2')),
        ('seat:s2/p1/maker', 'seat_missing'), ('seat:s2/p2/maker', 'seat_missing'),
        ('step:s2', 'step_not_entered')]
    points = []
    for point in ('p1', 'p2'):
        points += ledger.materialise(store, 'dispatch', {'step': 's2', 'seat': 'maker', 'attempt': 1,
                                                         'seat_kind': 'launch', 'point': point})
    satisfy(store, points + [k('GATE-launch', step='s2'),
                             k('X-POINT', step='s2', point='p1'), k('X-POINT', step='s2', point='p2')])
    assert unmet(store, 'execute→final_review') == []

    assert unmet(store, 'final_review→checkin3') == [('step:final_review', 'review_missing')]
    final = ledger.materialise(store, 'review', {'step': 'final_review', 'seat': 'physics-critic', 'attempt': 1,
                                                 'review_kind': 'final'})
    satisfy(store, final)
    assert unmet(store, 'final_review→checkin3') == []
    assert unmet(store, 'checkin3→deliver') == [pending(k('CHECKIN-3')), pending(k('X-CI3'))]
    satisfy(store, [k('CHECKIN-3'), k('X-CI3')])
    assert unmet(store, 'checkin3→deliver') == []

    assert unmet(store, 'deliver[accepted]') == [
        pending(k('X-KEEP', deliverable='D1')), pending(k('X-KEEP', deliverable='D2')),
        pending(k('X-LABEL')), pending(k('X-STANDING')), ('stage:deliver', 'stage_not_materialised')]
    assert unmet(store, 'deliver[qualified]') == []                      # a bounded ending stays reachable
    delivered = ledger.materialise(store, 'deliver', {'artifacts': ['a1']})
    satisfy(store, delivered + [k('X-STANDING')])
    ledger.record(store, k('X-LABEL'), 'violated', {'reason': 'same model family', 'label': 'same model family'})
    assert ledger.parent_join(store) == [k('X-KEEP', deliverable='D1'), k('X-KEEP', deliverable='D2')]
    assert unmet(store, 'deliver[accepted]') == []


def test_p02_gate_returns_the_exact_unmet_rows_of_every_transition(fixture_store):
    walk(fixture_store)
    summary = ledger.summary(fixture_store)
    assert summary['chain']['verified'] and summary['current']['by_status']['pending'] == 0
    assert summary['deliverables']['open'] == []


def test_p02_unmet_rows_name_their_node_package_and_consequence(fixture_store):
    ledger.materialise(fixture_store, 'intake', INTAKE)
    ledger.materialise(fixture_store, 'plan', {'plan': PLAN, 'route': 'analysis'})
    rows = {row['entry']: row for row in ledger.gate(fixture_store, 'deliver[accepted]')}
    intake = rows[k('X-INTAKE')]
    assert (intake['id'], intake['node'], intake['package'], intake['class']) == \
        ('X-INTAKE', 'controller.intake', 'P99', 'E')
    assert intake['consequence'] == 'diagnostic' and rows[k('X-ROUTE')]['consequence'] == 'qualified'
    assert rows['stage:deliver']['consequence'] == 'qualified' and rows['stage:deliver']['id'] is None
    assert all(row['message'] for row in rows.values())


def test_p02_labelled_rows_record_violations_with_their_label(fixture_store):
    ledger.materialise(fixture_store, 'intake', INTAKE)
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.record(fixture_store, k('X-LABEL'), 'violated', {'reason': 'detected'})
    assert raised.value.code == 'label_missing'
    assert pending(k('X-LABEL')) in unmet(fixture_store, 'deliver[accepted]')   # detection must still run
    ledger.record(fixture_store, k('X-LABEL'), 'violated', {'reason': 'detected', 'label': 'UNCONFINED EXECUTION'})
    assert not [row for row in ledger.gate(fixture_store, 'deliver[accepted]') if row['entry'] == k('X-LABEL')]
    assert unmet(fixture_store, 'intake→route_select') == [pending(k('X-INTAKE'))]   # a carried label blocks nothing


def test_p02_a_run_level_violation_stops_forward_transitions_but_not_endings(fixture_store):
    ledger.materialise(fixture_store, 'intake', INTAKE)
    satisfy(fixture_store, [k('X-INTAKE')])
    ledger.record(fixture_store, k('X-STANDING'), 'violated', {'reason': 'approval written outside the service'})
    assert (k('X-STANDING'), 'run_violation') in unmet(fixture_store, 'intake→route_select')
    assert unmet(fixture_store, 'deliver[qualified]') == []
    assert unmet(fixture_store, 'bounded_end→deliver') == []
    ledger.record(fixture_store, k('X-ROUTE'), 'violated', {'reason': 'route changed without authority'})
    assert (k('X-ROUTE'), 'run_violation') not in unmet(fixture_store, 'route_select→plan')  # waivable: qualified
    assert (k('X-ROUTE'), 'violated') in unmet(fixture_store, 'route_select→plan')


def test_p02_only_the_latest_attempt_of_a_seat_counts(fixture_store):
    ledger.materialise(fixture_store, 'intake', INTAKE)
    ledger.materialise(fixture_store, 'plan', {'plan': PLAN, 'route': 'analysis'})
    first = ledger.materialise(fixture_store, 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 1,
                                                           'seat_kind': 'worker'})
    seat = next(key for key in first if key.startswith('X-SEAT@'))
    ledger.record(fixture_store, seat, 'violated', {'reason': 'tool outside the belt'})
    assert (seat, 'violated') in unmet(fixture_store, 'execute→final_review')
    retry = ledger.materialise(fixture_store, 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 2,
                                                           'seat_kind': 'worker'})
    satisfy(fixture_store, retry)
    entries = [entry for entry, _ in unmet(fixture_store, 'execute→final_review')]
    assert seat not in entries and not set(retry) & set(entries)
    summary = ledger.summary(fixture_store)
    assert [(v['entry'], v['superseded']) for v in summary['violations']] == [(seat, True)]


def test_p02_deviation_and_escalation_occurrences_gate_their_return_to_execute(tmp_path, monkeypatch, capfd,
                                                                              operator_home):
    # The waiver is a deviation the authority service issued and the operator answered; the ledger reads it
    # only through the reader the service installs at composition (on the controller's own store).
    from ravel.controller.store import RunStore
    use_catalogue(monkeypatch, fixture_catalogue())
    store = RunStore(RUN, root=tmp_path / 'store')
    compose_authority(store, monkeypatch)
    try:
        ledger.materialise(store, 'intake', INTAKE)
        ledger.materialise(store, 'plan', {'plan': PLAN, 'route': 'analysis'})
        assert ('event:d1', 'occurrence_unknown') in unmet(store, 'deviation→execute[d1]')
        ledger.materialise(store, 'event', {'kind': 'deviation', 'id': 'd1'})
        rows = unmet(store, 'deviation->execute[d1]')
        assert pending(k('CHECKIN-deviation', event='d1')) in rows
        assert pending(k('GATE-deviation', event='d1')) not in rows        # the deviation decision discharges it
        change = {'parameter': 'scope', 'from': 'a', 'to': 'b', 'why': 'fixture', 'touches': ['CHECKIN-deviation'],
                  'direction': 'tighten'}
        uid = issued_waiver(store, capfd, ['CHECKIN-deviation'], kind='deviation', change=change)
        ledger.record(store, k('CHECKIN-deviation', event='d1'), 'waived', {'authority': uid})
        assert pending(k('CHECKIN-deviation', event='d1')) not in unmet(store, 'deviation→execute')
        assert pending(k('GATE-deviation', event='d1')) in unmet(store, 'deliver[accepted]')
    finally:
        state_module.forget(store)


def test_p02_escalation_return_and_endings_have_exact_unmet_rows(fixture_store, monkeypatch):
    rows = fixture_rows() + [row('CHECKIN-escalation', 'controller.escalation', 'event', 'event',
                                 select={'checkin': 'escalation'}, ledger_class='budget/stop')]
    use_catalogue(monkeypatch, fixture_catalogue(rows))
    ledger.materialise(fixture_store, 'intake', INTAKE)
    ledger.materialise(fixture_store, 'plan', {'plan': PLAN, 'route': 'analysis'})
    critic = ledger.materialise(fixture_store, 'review', {'step': 'plan_review', 'seat': 'plan-critic', 'attempt': 1})
    satisfy(fixture_store, critic + [key for key in ledger.pending(fixture_store) if key.split('@')[0] in (
        'X-INTAKE', 'X-ROUTE', 'X-SEATDERIV', 'X-CI1', 'CHECKIN-1', 'GATE-approve_plan')])
    assert unmet(fixture_store, 'escalate→execute') == []                 # no escalation is open
    assert unmet(fixture_store, 'escalate→execute[e1]') == [('event:e1', 'occurrence_unknown')]
    ledger.materialise(fixture_store, 'event', {'kind': 'escalation', 'id': 'e1', 'step': 's1'})
    question = k('CHECKIN-escalation', event='e1')
    assert unmet(fixture_store, 'escalate→execute[e1]') == [pending(question)]
    assert unmet(fixture_store, 'escalate->execute') == [pending(question)]
    satisfy(fixture_store, [question])
    assert unmet(fixture_store, 'escalate→execute[e1]') == []
    for ending in ('deliver[qualified]', 'deliver[diagnostic]', 'bounded_end→deliver'):
        assert unmet(fixture_store, ending) == []                          # an ending never waits for work


def test_p02_open_obligations_of_the_plan_block_an_accepted_delivery(fixture_store):
    ledger.materialise(fixture_store, 'intake', INTAKE)
    plan = {**PLAN, 'open_obligations': [{'kind': 'parameter', 'id': 'parameter:energy', 'reason': 'not stated'}]}
    ledger.materialise(fixture_store, 'plan', {'plan': plan, 'route': 'analysis'})
    assert ('open:parameter:energy', 'open_obligation') in unmet(fixture_store, 'deliver[accepted]')


def test_p02_unknown_transitions_are_refused():
    for name in ('deliver', 'execute→nowhere', 'deliver[accepted][x]', '', 7):
        with pytest.raises(ValueError):
            gates.parse(name)
    assert gates.parse('checkin2->execute[s05]') == ('checkin2→execute', 's05')
    assert set(gates.TRANSITIONS) >= {'checkin1→execute', 'execute→final_review', 'deliver[accepted]',
                                      'deliver[qualified]'}


def test_p02_decision_gates_map_to_their_ledger_transitions():
    assert gates.decision_transition('approve_plan', {}) == ('checkin1→execute', frozenset({'GATE-approve_plan'}))
    assert gates.decision_transition('launch', {'node_id': 's7'}) == ('launch[s7]', frozenset({'GATE-launch'}))
    assert gates.decision_transition('checkin2_accept', {'waypoint': 's5'})[0] == 'checkin2→execute[s5]'
    assert gates.decision_transition('deviation', {'event': 'd2'})[0] == 'deviation→execute[d2]'
    transition, own = gates.decision_transition('delivery', {})
    assert transition == 'deliver[accepted]' and own == frozenset(gates.DELIVERY_GATES)
    # The final task is decided at CHECK-IN 3, before delivery materialises: it requires the edge into delivery and
    # owns its own row there; an accepted delivery still requires deliver[accepted], which the sink gates.
    assert gates.decision_transition('final_task', {}) == ('checkin3→deliver', frozenset({'GATE-final_task'}))
    assert 'GATE-final_task' in gates.TRANSITIONS['checkin3→deliver']['own']
    from ravel.workflow import decision_gate
    assert set(gates.DECISION_TRANSITIONS) == set(decision_gate.GATES)
    with pytest.raises(ValueError):
        gates.decision_transition('invented', {})


def test_p02_population_equality_reports_holes_with_multiplicity():
    assert ledger.population_equality(['a', 'b', 'c'], ['c', 'a']) == ['b']
    assert ledger.population_equality(['p1', 'p1', 'p2'], ['p1']) == ['p1', 'p2']
    assert ledger.population_equality(['a'], ['a', 'extra']) == []
    assert ledger.population_equality(['a', 'extra'][1:], ['a']) == ['extra']
    with pytest.raises(TypeError):
        ledger.population_equality(['a'], [1])
    with pytest.raises(TypeError):
        ledger.population_equality('ab', ['a'])


# ---- mutation adequacy hooks ----------------------------------------------------------------------------

def test_undeclared_review_subset_does_not_close_scan(fixture_store):
    from copy import deepcopy
    plan = deepcopy(PLAN)
    plan['steps'][1]['review'] = ['checker']
    ledger.materialise(fixture_store, 'intake', INTAKE)
    ledger.materialise(fixture_store, 'plan', {'plan': plan})
    keys = ledger.materialise(fixture_store, 'review', {'step': 's2', 'seat': 'checker',
                                                       'point': 'p1', 'attempt': 1})
    satisfy(fixture_store, keys)
    assert ('seat:s2/checker', 'seat_missing') in unmet(fixture_store, 'execute→final_review')
    # The legacy point-less review remains the unchanged positive control.
    keys = ledger.materialise(fixture_store, 'review', {'step': 's2', 'seat': 'checker', 'attempt': 1})
    satisfy(fixture_store, keys)
    assert ('seat:s2/checker', 'seat_missing') not in unmet(fixture_store, 'execute→final_review')


def test_declared_review_subset_requires_pinned_plan(monkeypatch, tmp_path):
    from test_p18_scan import applied_scan, enter_grid, scan_store
    from ravel.controller.engagement.policy import scan_sample
    scientific, applied, points = applied_scan(monkeypatch)
    sample = scan_sample(points, 'standard', scientific['sha256'], points[-1:])
    store = scan_store(monkeypatch, tmp_path, scientific, applied)
    enter_grid(store, applied, sample)
    assert not [r for r in ledger.gate(store, 'execute→final_review') if r['reason'] == 'seat_missing']
    # A subset supplied only by the caller, without the retained population, has no authority.
    store.rewrite([e for e in store.entries() if e['kind'] != 'plan'])
    assert any(r['reason'] == 'seat_missing' for r in ledger.gate(store, 'execute→final_review'))


def test_declared_review_population_keeps_producer_rows_and_missing_reviews(monkeypatch, tmp_path):
    from test_p18_scan import applied_scan, enter_grid, scan_store
    from ravel.controller.engagement.policy import scan_sample
    scientific, applied, points = applied_scan(monkeypatch)
    sample = scan_sample(points, 'standard', scientific['sha256'], points[-1:])
    store = scan_store(monkeypatch, tmp_path, scientific, applied)
    enter_grid(store, applied, sample[1:], omit=points[0])
    rows = ledger.gate(store, 'execute→final_review')
    assert any(r['reason'] == 'seat_missing' and sample[0] in r['entry'] for r in rows)
    assert any(r['reason'] == 'seat_missing' and 'generator' in r['entry'] for r in rows)

@pytest.mark.parametrize('target', ['evaluate', 'population_equality'])
def test_p02_disabling_the_gate_or_population_equality_fails_the_walk(fixture_store, monkeypatch, target):
    """A gate that returns nothing, or a population check that finds no hole, fails the named walk."""
    monkeypatch.setattr(gates, target, lambda *args, **kwargs: [])
    with pytest.raises(AssertionError):
        walk(fixture_store)
    state_module.forget(fixture_store)


CARDS_PLAN = {'sha256': 'e' * 64,
              'steps': [{'id': 's1', 'kind': 'derive', 'role': 'calculation', 'review': ['skeptical_verifier']}],
              'deliverables': [{'id': 'D1', 'steps': ['s1']}]}


def _seat_holes(store):
    return [entry for entry, reason in unmet(store, 'execute→final_review') if reason == 'seat_missing']


@pytest.mark.parametrize('reviewer, holes', [
    ('skeptical-verifier', []),
    ('plan-critic', ['seat:s1/skeptical_verifier']),
])
def test_p02_a_planned_seat_is_the_card_its_attempt_ran(fixture_store, reviewer, holes):
    """The step graph keys its attempts ``producer`` and ``seat:<role>:<n>`` and records the card each ran; a planned
    seat names a role, in any spelling. The ledger matches the two by the card id both resolve to through the role
    registry's one generated mapping, with the seat kind; a review by another card leaves the planned seat open."""
    ledger.materialise(fixture_store, 'intake', {**INTAKE, 'deliverables': ['D1']})
    ledger.materialise(fixture_store, 'plan', {'plan': CARDS_PLAN, 'route': 'analysis'})
    assert sorted(_seat_holes(fixture_store)) == ['seat:s1/calculation', 'seat:s1/skeptical_verifier']
    ledger.materialise(fixture_store, 'dispatch', {'step': 's1', 'seat': 'producer', 'attempt': 1, 'seat_kind': 'worker',
                                                   'role': 'calculation'})
    ledger.materialise(fixture_store, 'review', {'step': 's1', 'seat': f'seat:{reviewer}:1', 'attempt': 1,
                                                 'role': reviewer, 'seat_kind': 'review'})
    assert _seat_holes(fixture_store) == holes
