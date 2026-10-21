"""Research child decisions in separate protected stores, against parent reservations."""
from copy import deepcopy

from ravel.controller.engagement import policy
from ravel.controller.engagement.facts import fact
from ravel.controller.engagement.records import DECISION, ESCALATION, current_tier, digest, latest, rows, verify
from ravel.workflow.graph_nodes import RecoveryHold


class ChildTierHold(RecoveryHold):
    """A child requires renewed priced admission before any further dispatch."""


def child_store(parent, key):
    from ravel.controller.store import RunStore
    return RunStore('child-' + digest({'parent': parent.run_id, 'key': key})[:32],
                    root=parent.path('children'))


def prepare(parent, child, plan, budget, key, *, frozen_mode=None):
    """Apply the priced child facts; floors/escalations may raise, but unpriced execution holds."""
    from ravel.controller import authority, engagement
    from ravel.controller.routes.research import loop_budget
    if (plan.get('sha256') != digest({k: v for k, v in plan.items() if k != 'sha256'})
            or (plan.get('route') or {}).get('id') != (child.get('route') or 'study')):
        raise ChildTierHold('research_child_tier_unpriced', 'the child plan differs from its own route or digest')
    store = child_store(parent, key)
    installed, _, rules = loop_budget._installed()
    # Runtime callers already hold the authenticated frozen mode in controller state.
    # Direct callers resolve it through authority, never live preferences.
    config = deepcopy(frozen_mode) if frozen_mode is not None else authority.frozen(parent, required=False) or {}
    own_config = (authority.frozen(store, required=False) if store.scan('mode') else None) or {}
    parent_minimum = config.get('engagement', {}).get('minimum_tier')
    own_minimum = own_config.get('engagement', {}).get('minimum_tier')
    minimum = policy.raise_only(parent_minimum, own_minimum) if parent_minimum else own_minimum
    config = {**config, 'engagement': {**config.get('engagement', {}), 'minimum_tier': minimum}}
    floors = [current_tier(store)] if latest(store, DECISION) else []
    for event in rows(store, ESCALATION):
        verify(event)
        floors.append(event['new_tier'])
    # The child's own facts decide its tier through the one engagement assembly; the parent is context only.
    context = {'parent_context': fact(
        {'run_id': parent.run_id, 'tier': engagement.tier(parent), 'reservation_key': key,
         'budget_sha256': budget['sha256']}, 'parent run and reservation key', 'code:research-child-context')}
    checked = loop_budget.child_facts(child, store=parent, reviewed=True)
    if checked.get('compute', {}).get('source') not in (None, 'missing') and 'engagement_planning' in child:
        if child['engagement_planning']['plan'] != plan:
            raise ChildTierHold('research_child_tier_unpriced', 'the execution plan differs from the priced child plan')
    decision = engagement.assemble(store, checked, plan, config,
                                   installed['routes'].get(child.get('route') or 'study', {}),
                                   installed=rules, floors=floors, context=context)
    selected = decision['tier']
    projection = loop_budget.child_projection(child, installed, rules, minimum_tier=selected,
                                              store=parent, reviewed=True)
    try:
        reservation = loop_budget.admit(parent, budget, 'child', key, child=child, minimum_tier=selected)
        loop_budget.check_execution(reservation, projection)
    except loop_budget.ChildProjectionMismatch as exc:
        raise ChildTierHold('research_child_tier_unpriced', str(exc)) from None
    decision = engagement.effective_decision(store)
    return store, decision, engagement.apply(plan, decision)


def resolve(parent, parent_plan, context):
    """Authenticate the applied child view at the acting-node admission, retaining parent authority."""
    from ravel.controller import graph
    from ravel.controller.routes import plan_sha256
    lineage = context.get('route_child') or {}
    reference = context.get('research_child_engagement') or {}
    try:
        row = parent.read(graph.ROUTE_PLAN, lineage['record'])['record']
        if (row['parent_plan_sha256'] != parent_plan['sha256'] or row['parent_step'] != lineage['step']
                or lineage['parent_plan_sha256'] != parent_plan['sha256']):
            raise ValueError('child lineage differs from the approved parent')
        steps = [s for s in parent_plan['steps'] if s['id'] == lineage['step']]
        if len(steps) != 1 or steps[0].get('kind') != 'route':
            raise ValueError('the parent has no unique child route step')
        step = steps[0]
        plan = graph._json_blob(parent, row['blob'])
        if plan_sha256(plan) != row['plan_sha256'] or plan['sha256'] != lineage['plan_sha256']:
            raise ValueError('the approved child plan changed')
        _, decision, applied = prepare(parent, step['parameters']['item'], plan,
            parent_plan['parameters']['research_loop_budget'], lineage['step'],
            frozen_mode=context.get('mode') or {})
        if reference != {'key': lineage['step'], 'tier': decision['tier'],
                         'decision_sha256': decision['sha256'],
                         'run_id': child_store(parent, lineage['step']).run_id}:
            raise ValueError('the child engagement reference is missing or stale')
        return applied
    except ChildTierHold:
        raise
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as exc:
        raise ChildTierHold('research_child_tier_unpriced', str(exc)) from None
