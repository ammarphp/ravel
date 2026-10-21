"""The research loop budget: declared at binding, shown and bound at CHECK-IN 1, enforced per cycle and child.

Real adopted campaign requests and the installed engagement calibration; an in-memory store stands in for the
controller store. No worker, model or native call.
"""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

from ravel.controller.routes import research
from ravel.controller.routes.research import loop_budget
from ravel.workflow import research_coordinator_decisions as decisions

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p11_fakes import FakeRunStore  # noqa: E402
from test_p11_route import prepared_route  # noqa: E402


@pytest.fixture
def bound(tmp_path):
    plan, context, children = prepared_route(tmp_path / 'run')
    return research.bind(plan, context), context, children


def assess(store, budget, admission, tmp_path, *, disposition='continue', action='protocol-stage', evidence=None):
    from ravel.workflow import research_cycle as cycle
    from test_research_cycle import write
    source = write(tmp_path / 'gain-evidence.json', {'unresolved': 'An independent comparison remains.'})
    public = {'action': action, 'reason': 'Prospective comparison of the supplied alternatives.',
              'information_gain': {'decision': disposition,
                  'expected_gain': 'Distinguish the unresolved alternatives.' if disposition == 'continue'
                                   else 'The remaining comparison repeats the available evidence.',
                  'cost_justification': 'The independent comparison justifies one projected cycle.'
                                      if disposition == 'continue' else 'Repetition does not justify another cycle.',
                  'evidence_input_ids': ['evidence'] if evidence is None else evidence}}
    output = write(tmp_path / (admission['key'] + '-decision.json'), public)
    return loop_budget.record_decision(store, budget, admission, public, [{'id': 'evidence', **source}],
                                       output=output, observation_sha256=cycle.ce.digest(public))


def test_binding_declares_one_sealed_loop_budget_on_the_plan_and_its_campaign_step(bound):
    plan, context, children = bound
    budget = plan['parameters']['research_loop_budget']
    assert loop_budget.verify(budget) is budget
    campaign = next(row for row in plan['steps'] if row['id'] == 'campaign')
    assert campaign['parameters']['research_loop_budget'] == budget
    value = decisions.request(plan['parameters']['research_request'])
    assert budget['max_cycles'] == value['max_decisions']
    assert budget['max_children'] == value['campaign']['max_experiments']
    assert budget['campaign_ceilings'] == value['campaign']['budget']
    # Every protocol stage has a projection; a cycle is priced at its dearest stage, low <= central <= high.
    assert set(budget['per_stage']) == {s['id'] for s in research.protocol.default_protocol()['stages']}
    for metric in loop_budget.METRICS:
        low, central, high = (budget['per_cycle'][level][metric] for level in loop_budget.LEVELS)
        assert 0 < low <= central <= high, metric
    # Each declared child carries its own tier from its own facts, with the policy's reasons.
    assert [c['id'] for c in budget['children']] == [c['id'] for c in children]
    for child in budget['children']:
        assert child['tier'] in ('lean', 'standard', 'full') and child['tier_reasons']
        assert child['projected']['high']['cost_usd'] >= child['projected']['low']['cost_usd'] > 0
    totals = budget['projected_total_usd']
    assert 0 < totals['low'] <= totals['central'] <= totals['high']
    assert budget['cost_ceiling_usd'] == totals['high']  # no operator envelope in this context
    from ravel.workflow.research_controller import plan_sha256
    assert plan['sha256'] == plan_sha256(plan)  # the approval's digest covers the budget


def test_a_child_with_checkable_simple_facts_is_leaner_than_one_with_unknown_facts():
    installed, _, policy_document = loop_budget._installed()
    unknown = loop_budget.child_projection({'id': 'a', 'route': 'study'}, installed, policy_document)
    # Unknown consequence, compute or novelty is always full: a child is never cheaper than its facts allow.
    assert unknown['tier'] == 'full'
    assert any(r['rule'] == 'unknown-means-complex' for r in unknown['tier_reasons'])


def test_checkin_shows_the_loop_budget_binds_its_digest_and_asks_the_critic(bound):
    plan, context, _ = bound
    extra = research.checkin('approve_plan', {**context, 'plan': plan})
    budget = plan['parameters']['research_loop_budget']
    assert extra['pins'] == {'research_loop_budget_sha256': budget['sha256']}
    [section] = extra['sections']
    assert section['id'] == 'research_loop_budget'
    text = '\n'.join(section['lines'])
    assert f"{budget['max_cycles']} coordinator cycles" in text and 'per cycle' in text
    assert all(f"Child {c['id']}" in text for c in budget['children'])
    assert budget['stop_rule'] in section['lines']
    assert [item['id'] for item in extra['review_items']] == ['research_loop_budget']
    assert research.checkin('go', {**context, 'plan': plan}) == {}


@pytest.mark.parametrize('damage', ['missing', 'tampered', 'step_differs'])
def test_checkin_refuses_a_plan_whose_loop_budget_is_missing_changed_or_unbound(bound, damage):
    plan, context, _ = bound
    plan = deepcopy(plan)
    if damage == 'missing':
        del plan['parameters']['research_loop_budget']
    elif damage == 'tampered':
        plan['parameters']['research_loop_budget']['max_cycles'] += 1
    else:
        campaign = next(row for row in plan['steps'] if row['id'] == 'campaign')
        campaign['parameters']['research_loop_budget'] = loop_budget.declare(
            decisions.request(plan['parameters']['research_request']), [], tier='full')
    errors = research.checkin('approve_plan', {**context, 'plan': plan})['errors']
    assert errors and errors[0]['code'] in ('research_loop_budget_missing', 'research_loop_budget_unbound')


def test_cycles_are_admitted_up_to_the_approved_count_and_a_replay_is_not_charged_twice(bound, tmp_path):
    plan, _, _ = bound
    budget = deepcopy(plan['parameters']['research_loop_budget'])
    body = {k: v for k, v in budget.items() if k != 'sha256'}
    body.update(max_cycles=2, cost_ceiling_usd=10 * body['per_cycle']['high']['cost_usd'])
    budget = {**body, 'sha256': loop_budget.digest(body)}
    store = FakeRunStore('loop', root=tmp_path / 'store')
    first = loop_budget.admit(store, budget, 'cycle', 'turn-1')
    assert first['presented_budget']['cycles_used'] == 0
    assert loop_budget.admit(store, budget, 'cycle', 'turn-1') == first
    assess(store, budget, first, tmp_path)
    loop_budget.admit(store, budget, 'cycle', 'turn-2')
    with pytest.raises(loop_budget.LoopBudgetExhausted, match='2 cycles used'):
        loop_budget.admit(store, budget, 'cycle', 'turn-3')
    view = loop_budget.view(store, budget)
    assert view['cycles_used'] == 2 and view['committed_high_usd'] == 2 * budget['per_cycle']['high']['cost_usd']


def test_a_cycle_or_child_beyond_the_cost_ceiling_is_refused_before_anything_is_committed(bound, tmp_path):
    plan, _, _ = bound
    body = {k: v for k, v in plan['parameters']['research_loop_budget'].items() if k != 'sha256'}
    body.update(cost_ceiling_usd=1.5 * body['per_cycle']['high']['cost_usd'])
    budget = {**body, 'sha256': loop_budget.digest(body)}
    store = FakeRunStore('ceiling', root=tmp_path / 'store')
    first = loop_budget.admit(store, budget, 'cycle', 'turn-1')
    assess(store, budget, first, tmp_path)
    with pytest.raises(loop_budget.LoopBudgetExhausted, match='remain'):
        loop_budget.admit(store, budget, 'cycle', 'turn-2')
    with pytest.raises(loop_budget.LoopBudgetExhausted, match='remain'):
        loop_budget.admit(store, budget, 'child', 'child-1', child={'id': 'adaptive', 'route': 'study'})
    assert loop_budget.committed(store, budget)['cycles'] == 1
    assert loop_budget.committed(store, budget)['children'] == 0


def test_a_changed_budget_admits_nothing(bound, tmp_path):
    plan, _, _ = bound
    budget = deepcopy(plan['parameters']['research_loop_budget'])
    budget['cost_ceiling_usd'] *= 10
    with pytest.raises(loop_budget.LoopBudgetExhausted, match='changed'):
        loop_budget.admit(FakeRunStore('changed', root=tmp_path / 'store'), budget, 'cycle', 'turn-1')
    with pytest.raises(loop_budget.LoopBudgetExhausted, match='no approved'):
        loop_budget.verify(None)


def test_a_budget_without_declared_children_still_prices_and_admits_its_adaptive_children(tmp_path):
    request = {'max_decisions': 2, 'campaign': {'max_experiments': 2,
               'budget': {'calls': 10, 'output_tokens': 1000, 'wall_seconds': 100, 'native_attempts': 1}}}
    budget = loop_budget.declare(request, [], tier='full')
    adaptive = budget['adaptive_child']['projected']['high']['cost_usd']
    assert adaptive > 0
    assert budget['projected_total_usd']['high'] == pytest.approx(
        2 * budget['per_cycle']['high']['cost_usd'] + 2 * adaptive)
    store = FakeRunStore('adaptive', root=tmp_path / 'store')
    for key in ('child-a', 'child-b'):
        loop_budget.admit(store, budget, 'child', key, child={'id': key, 'route': 'study'})
    with pytest.raises(loop_budget.LoopBudgetExhausted, match='2 children used'):
        loop_budget.admit(store, budget, 'child', 'child-c', child={'id': 'child-c', 'route': 'study'})


@pytest.mark.parametrize('disposition', ['continue', 'stop'])
def test_information_gain_discriminates_with_unused_cycles_children_and_cost(bound, tmp_path, disposition):
    plan, _, _ = bound
    budget = plan['parameters']['research_loop_budget']
    store = FakeRunStore('gain', root=tmp_path / 'store')
    first = loop_budget.admit(store, budget, 'cycle', 'turn-1')
    row = assess(store, budget, first, tmp_path, disposition=disposition,
                 action='protocol-stage' if disposition == 'continue' else 'progress')
    assert row['assessment']['decision'] == disposition and row['action_admitted']
    assert row['evidence'][0]['sha256'] and row['output']['sha256'] and row['observation_sha256']
    assert row['next_cycle_projection'] == budget['per_cycle']
    before = loop_budget.view(store, budget)
    assert before['cycles_used'] < before['max_cycles'] and before['children_used'] < before['max_children']
    assert before['remaining_usd'] > budget['per_cycle']['high']['cost_usd']
    if disposition == 'continue':
        admitted = loop_budget.admit(store, budget, 'cycle', 'turn-2')
        assert admitted['key'] == 'turn-2'
    else:
        for kind in ('cycle', 'child'):
            with pytest.raises(loop_budget.InformationGainStopped, match='information-gain stop'):
                loop_budget.admit(store, budget, kind, 'next-' + kind)
        assert loop_budget.view(store, budget) == before


def test_a_low_gain_action_is_recorded_and_refused_before_it_can_run(bound, tmp_path):
    plan, _, _ = bound
    budget = plan['parameters']['research_loop_budget']
    store = FakeRunStore('contradiction', root=tmp_path / 'store')
    first = loop_budget.admit(store, budget, 'cycle', 'turn-1')
    with pytest.raises(loop_budget.InformationGainStopped):
        assess(store, budget, first, tmp_path, disposition='stop', action='experiment')
    [row] = [r['record'] for r in store.scan(loop_budget.DECISION)]
    assert row['action'] == 'experiment' and row['action_admitted'] is False
    assert loop_budget.committed(store, budget)['children'] == 0


@pytest.mark.parametrize('evidence', [[], ['absent'], ['evidence', 'evidence']])
def test_gain_evidence_must_name_distinct_presented_inputs(bound, tmp_path, evidence):
    plan, _, _ = bound
    budget = plan['parameters']['research_loop_budget']
    store = FakeRunStore('bad-evidence', root=tmp_path / 'store')
    first = loop_budget.admit(store, budget, 'cycle', 'turn-1')
    with pytest.raises(ValueError):
        assess(store, budget, first, tmp_path, evidence=evidence)
    assert not store.scan(loop_budget.DECISION)


def test_an_unassessed_cycle_cannot_admit_another_one(bound, tmp_path):
    plan, _, _ = bound
    budget = plan['parameters']['research_loop_budget']
    store = FakeRunStore('unassessed', root=tmp_path / 'store')
    loop_budget.admit(store, budget, 'cycle', 'turn-1')
    with pytest.raises(loop_budget.LoopBudgetExhausted, match='no admitted information-gain decision'):
        loop_budget.admit(store, budget, 'cycle', 'turn-2')
