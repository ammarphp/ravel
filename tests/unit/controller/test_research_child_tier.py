"""Child policy facts, applied execution and reservations stay in agreement."""
from copy import deepcopy
from importlib import import_module

import pytest

from ravel.controller import engagement, graph
from ravel.controller.engagement import facts, policy
from ravel.controller.routes.research import loop_budget
from ravel.workflow.graph_nodes import RecoveryHold
from test_p18_records import setup as engagement_setup


@pytest.fixture
def child_run(monkeypatch, tmp_path):
    parent, plan, installed = engagement_setup(monkeypatch, tmp_path / 'parent')
    from ravel.controller import capabilities
    monkeypatch.setattr(capabilities, 'catalogue', lambda: {})
    # This fixture represents the code collector's checked output, never worker assertions.
    checked = {name: facts.fact(value, 'checked child input', 'code:child-control') for name, value in
               {'route': 'study', 'deliverables': 1, 'consequence': 'R0', 'compute': 'C0',
                'novelty': 'N0', 'special': []}.items()}
    monkeypatch.setattr(loop_budget, 'child_facts', lambda child, **_: deepcopy(checked))
    projection = {'routes': {'study': {}}, 'packets': {'research': {}}}
    for tier, cost in [('lean', 1), ('standard', 2), ('full', 4)]:
        row = {m: cost for m in loop_budget.METRICS}
        projection['routes']['study'][tier] = {'status': 'ready', **{k: deepcopy(row) for k in loop_budget.LEVELS}}
        projection['packets']['research'][tier] = [
            {'category': c, 'packet_tokens': 100, 'duty_units': 1} for c in ('producer', 'review')]
    calibration = engagement.data('calibration.json')
    monkeypatch.setattr(loop_budget, '_installed', lambda: (deepcopy(projection), calibration, installed))
    descriptor = {'id': 'child-one', 'route': 'study', 'contract': {'deliverables': [{'id': 'value'}]}}
    request = {'max_decisions': 1, 'campaign': {'max_experiments': 1, 'budget': {}}}
    budget = loop_budget.declare(request, [descriptor])
    parent.append('plan', {'plan': plan, 'plan_sha256': plan['sha256']})
    return parent, plan, descriptor, budget, checked


def prepare(child_run):
    from ravel.controller.routes.research import child_engagement as children
    parent, plan, descriptor, budget, _ = child_run
    return children.prepare(parent, descriptor, plan, budget, 'children.child-one')


@pytest.mark.parametrize('parent_tier,child_tier', [('full', 'lean'), ('lean', 'full')])
def test_child_applied_execution_uses_own_facts(child_run, monkeypatch, parent_tier, child_tier):
    parent, plan, descriptor, budget, checked = child_run
    tier = engagement.tier
    monkeypatch.setattr(engagement, 'tier', lambda store: parent_tier if store is parent else tier(store))
    if child_tier == 'full':
        checked.pop('novelty')
        request = {'max_decisions': 1, 'campaign': {'max_experiments': 1, 'budget': {}}}
        budget = loop_budget.declare(request, [descriptor])
        child_run = parent, plan, descriptor, budget, checked
    child_store, decision, applied = prepare(child_run)
    assert decision['computed_tier'] == decision['tier'] == child_tier
    assert applied['engagement']['tier'] == child_tier
    assert decision['facts']['parent_context']['value']['tier'] == parent_tier
    if child_tier == 'lean':
        assert decision['facts']['novelty']['value'] == 'N0'
    else:
        assert 'novelty' not in decision['facts']
    [reservation] = [r['record'] for r in parent.scan(loop_budget.RESERVATION)]
    assert reservation['projection']['tier'] == decision['tier']
    stored = child_store.scan(engagement.DECISION)[-1]['record']
    assert stored['tier'] == child_tier and not parent.scan(engagement.DECISION)
    assert engagement.check_applied(applied, decision) == []


@pytest.mark.parametrize('damage', ['facts', 'floor', 'replay_facts'])
def test_tier_mismatch_holds_before_dispatch(child_run, monkeypatch, damage):
    parent, _, _, budget, checked = child_run
    if damage == 'replay_facts':
        prepare(child_run)
    if damage == 'floor':
        import ravel.controller.authority as authority
        monkeypatch.setattr(authority, 'frozen', lambda store, required=False:
                            {'engagement': {'minimum_tier': 'full'}, 'budgets': {}})
    else:
        checked.pop('compute')
    with pytest.raises(RecoveryHold, match='research_child_tier_unpriced'):
        prepare(child_run)
    assert loop_budget.committed(parent, budget)['children'] <= 1
    if damage == 'floor':
        from ravel.controller.routes.research import child_engagement as children
        stored = children.child_store(parent, 'children.child-one').scan(engagement.DECISION)[-1]['record']
        assert stored['computed_tier'] == 'lean' and stored['tier'] == 'full'


def test_child_escalation_raises_and_cannot_spend_a_lean_reservation(child_run):
    child_store, decision, _ = prepare(child_run)
    raised = engagement.observe(child_store, {'evidence': ['checked-outcome'], 'status': 'held'})
    assert raised['old_tier'] == 'lean' and raised['new_tier'] == 'standard'
    with pytest.raises(RecoveryHold, match='research_child_tier_unpriced'):
        prepare(child_run)


def test_raised_child_can_run_when_its_floor_was_priced(child_run, monkeypatch):
    parent, plan, descriptor, _, checked = child_run
    checked['consequence'] = facts.fact('R3', 'checked consequence', 'code:child-control')
    budget = loop_budget.declare({'max_decisions': 1, 'campaign': {'max_experiments': 1, 'budget': {}}}, [descriptor])
    child_store, decision, applied = prepare((parent, plan, descriptor, budget, checked))
    assert decision['tier'] == applied['engagement']['tier'] == 'full'
    engagement.observe(child_store, {'evidence': ['checked-outcome'], 'status': 'held'})
    assert prepare((parent, plan, descriptor, budget, checked))[1]['tier'] == 'full'


def inline_dispatch(child_run, monkeypatch):
    parent, plan, descriptor, budget, _ = child_run
    child = deepcopy(plan)
    parent_plan = {'sha256': 'a' * 64, 'parameters': {'research_loop_budget': budget}}
    step = {'id': 'children.child-one', 'parameters': {'item': descriptor}}
    pin = parent.append(graph.ROUTE_PLAN, {'spec_sha256': 'spec', 'plan_sha256': child['sha256']})
    state = {'plan': {'route_children': {step['id']: {'record_id': pin}}}, 'steps': {}, 'loop': {}}
    from ravel.controller import routes
    monkeypatch.setattr(routes, 'find', lambda name: {})
    monkeypatch.setattr(routes, 'adapter_module', lambda spec: None)
    select = import_module('ravel.controller.routes.select')
    monkeypatch.setattr(select, 'spec_sha256', lambda spec: 'spec')
    monkeypatch.setattr(graph, '_intake_records', lambda *args: ({}, {}, None))
    monkeypatch.setattr(graph, '_latest_authority', lambda *args: 'approval')
    monkeypatch.setattr(graph, '_context', lambda *args, **kw: kw)
    monkeypatch.setattr(graph, 'service', lambda name: type('Authority', (), {'stop_state': lambda self, store: 'running'})())
    invoked = []
    monkeypatch.setattr(graph, '_invoke', lambda state, gid, view, segment: invoked.append(view) or {})
    monkeypatch.setattr(graph, 'fold_outcome', lambda *args: ({'status': graph.STEP_DONE, 'attempts': 1}, {}, None))
    row, hold, _ = graph.route_child(state, parent, parent_plan, step, child, {})
    return row, hold, invoked


@pytest.mark.parametrize('parent_tier,child_tier', [('full', 'lean'), ('lean', 'full')])
def test_inline_route_dispatches_the_child_applied_steps(child_run, monkeypatch, parent_tier, child_tier):
    parent, plan, descriptor, budget, checked = child_run
    tier = engagement.tier
    monkeypatch.setattr(engagement, 'tier', lambda store: parent_tier if store is parent else tier(store))
    if child_tier == 'full':
        checked.pop('novelty')
        budget = loop_budget.declare({'max_decisions': 1, 'campaign': {'max_experiments': 1, 'budget': {}}}, [descriptor])
        child_run = parent, plan, descriptor, budget, checked
    row, hold, invoked = inline_dispatch(child_run, monkeypatch)
    assert hold is None and row['status'] == graph.STEP_DONE
    assert invoked and all(v['step']['engagement']['inline_context_tokens'] ==
                           policy.load_policy()['packet_scope'][child_tier]['inline_context_tokens'] for v in invoked)
    assert all(v['context']['research_child_engagement']['tier'] == child_tier for v in invoked)


def test_inline_mismatch_never_invokes_a_step(child_run, monkeypatch):
    # Reuse the dispatch control but raise its facts after the approved budget was sealed.
    child_run[-1].pop('compute')
    row, hold, invoked = inline_dispatch(child_run, monkeypatch)
    assert row['status'] == 'held' and hold['reason'] == 'research_child_tier_unpriced'
    assert invoked == []


def test_admission_itself_refuses_changed_child_facts(child_run):
    parent, _, descriptor, budget, checked = child_run
    checked.pop('compute')
    with pytest.raises(loop_budget.LoopBudgetExhausted, match='differs from its admitted'):
        loop_budget.admit(parent, budget, 'child', 'children.child-one', child=descriptor)
    assert parent.scan(loop_budget.RESERVATION) == []


def test_step_scoped_escalation_cannot_run_unpriced_child_reviews(child_run):
    child_store, _, _ = prepare(child_run)
    for attempt in (2, 3):
        engagement.observe(child_store, {'evidence': ['checked-retry-' + str(attempt)],
            'step_id': 's1', 'mechanical_retry_passed': True})
    assert engagement.tier(child_store) == 'lean'  # the normal monitor keeps a step raise local
    with pytest.raises(RecoveryHold, match='research_child_tier_unpriced'):
        prepare(child_run)


def test_replayed_admission_refuses_changed_pricing(child_run, monkeypatch):
    parent, _, descriptor, budget, _ = child_run
    loop_budget.admit(parent, budget, 'child', 'children.child-one', child=descriptor)
    installed = loop_budget._installed
    def changed():
        projection, calibration, rules = installed()
        projection['routes']['study']['lean']['high']['cost_usd'] += 1
        return projection, calibration, rules
    monkeypatch.setattr(loop_budget, '_installed', changed)
    with pytest.raises(loop_budget.LoopBudgetExhausted, match='differs from its admitted'):
        loop_budget.admit(parent, budget, 'child', 'children.child-one', child=descriptor)
    assert len(parent.scan(loop_budget.RESERVATION)) == 1


def test_ordinary_exhaustion_remains_a_budget_boundary(child_run):
    parent, plan, descriptor, budget, checked = child_run
    body = {k: v for k, v in budget.items() if k != 'sha256'}
    body['cost_ceiling_usd'] = 0
    budget = {**body, 'sha256': loop_budget.digest(body)}
    with pytest.raises(loop_budget.LoopBudgetExhausted, match='only .* remain'):
        prepare((parent, plan, descriptor, budget, checked))
    assert parent.scan(loop_budget.RESERVATION) == []


def test_unchecked_worker_fields_cannot_lower_unknown_child_facts():
    child = {'id': 'unknown', 'route': 'study', 'engagement': {'tier': 'lean'},
             'facts': {'compute': 'C0', 'novelty': 'N0', 'consequence': 'R0', 'special': []}}
    computed = policy.tier(loop_budget.child_facts(child), policy.load_policy())
    assert computed['tier'] == 'full'
    assert computed['minimum_tiers']['compute'] == 'full'
    assert any(r['rule'] == 'unknown-means-complex' for r in computed['reasons'])


def test_acting_node_rechecks_child_decision_and_reservation(child_run, monkeypatch):
    from ravel.controller.routes.research import child_engagement as children
    from ravel.controller.step import operations
    parent, plan, descriptor, budget, checked = child_run
    child_store, decision, applied = prepare(child_run)
    step = {'id': 'children.child-one', 'kind': 'route', 'parameters': {'item': descriptor}}
    parent_plan = {'sha256': 'a' * 64, 'steps': [step], 'parameters': {'research_loop_budget': budget}}
    pin = parent.append(graph.ROUTE_PLAN, {'parent_plan_sha256': parent_plan['sha256'],
        'parent_step': step['id'], 'plan_sha256': plan['sha256'], 'blob': 'bound-child'})
    context = {'route_child': {'record': pin, 'step': step['id'], 'plan_sha256': plan['sha256'],
                               'parent_plan_sha256': parent_plan['sha256']},
               'research_child_engagement': {'key': step['id'], 'tier': decision['tier'],
                   'decision_sha256': decision['sha256'], 'run_id': child_store.run_id}}
    monkeypatch.setattr(graph, '_json_blob', lambda store, blob: deepcopy(plan))
    monkeypatch.setattr(operations, 'current_plan', lambda store, ctx: deepcopy(parent_plan))
    assert operations.plan_step(parent, applied['steps'][0], context)[2] == 'research_route_child'
    damaged = deepcopy(applied['steps'][0])
    damaged['engagement'] = policy.load_policy()['packet_scope']['full']
    with pytest.raises(RecoveryHold, match='plan_step_changed'):
        operations.plan_step(parent, damaged, context)
    checked.pop('compute')
    with pytest.raises(RecoveryHold, match='research_child_tier_unpriced'):
        operations.plan_step(parent, applied['steps'][0], context)


def test_adaptive_bridge_applies_own_tier_to_the_governed_dispatch(tmp_path):
    from test_p11_mode import setup, approve
    from p11_fakes import FakeStep, installed_step
    from ravel.workflow import research_controller as bridge
    root, child, experiment, store, context, _ = setup(tmp_path)
    approve(child, experiment['study'])
    peer = FakeStep()
    with installed_step(peer), bridge.bound(store, context):
        assert bridge.run_child(root, experiment) == 0
    from ravel.controller.routes.research import child_engagement as children
    decision = children.child_store(store, 'research-child-' + experiment['id']).scan(engagement.DECISION)[-1]['record']
    [reservation] = [r['record'] for r in store.scan(loop_budget.RESERVATION)]
    assert decision['tier'] == reservation['projection']['tier'] == 'full'
    assert peer.calls[0]['context']['research_child_decision']['tier'] == decision['tier']
    assert peer.calls[0]['step']['engagement'] == decision['packet_scope']


def test_adaptive_budget_exhaustion_keeps_qualified_bounded_ending(tmp_path):
    from test_p11_mode import setup, approve
    from p11_fakes import FakeStep, installed_step
    from ravel.workflow import research_controller as bridge, research_cycle as cycle
    root, child, experiment, store, context, _ = setup(tmp_path)
    approve(child, experiment['study'])
    body = {k: v for k, v in context['research_loop_budget'].items() if k != 'sha256'}
    body['cost_ceiling_usd'] = 0
    context['research_loop_budget'] = {**body, 'sha256': loop_budget.digest(body)}
    peer = FakeStep()
    with installed_step(peer), bridge.bound(store, context), pytest.raises(cycle.CampaignBudgetExhausted):
        bridge.run_child(root, experiment)
    assert peer.calls == []
    assert store.scan('research-budget-boundary')[-1]['record']['kind'] == 'research_loop_budget'
