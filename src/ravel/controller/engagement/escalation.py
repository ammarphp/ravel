"""Controller-observed triggers; append-only, idempotent, monotone engagement."""
from __future__ import annotations

from copy import deepcopy

from .records import DECISION, ESCALATION, TIERS, EngagementRefused, append, current_tier, digest, latest, rows
from . import policy as policy_module
from .policy import seat_plan


def triggers(event):
    result = []
    review = event.get('review') or {}
    if event.get('validation_failed') and event.get('retry_exhausted'):
        result.append('E1')
    if (review.get('verdict') in ('revise', 'unresolved') or review.get('credited') is False
            or any(i.get('status') in ('failed', 'fail', 'blocked') for i in review.get('items', []))):
        result.append('E2')
    if event.get('outside_tolerance') or event.get('decomposition_opened') or event.get('anchor_mismatch'):
        result.append('E3')
    escalation = event.get('escalation')
    escalation_kind = escalation.get('kind') if isinstance(escalation, dict) else escalation
    if (escalation_kind in ('checkin_flag', 'decision_block', 'new_experiment_required', 'stop')
            or event.get('deviation') or event.get('replan') or event.get('status') == 'held'
            or event.get('ledger_class_violation') == 'L'
            or (event.get('envelope_status') in ('below_floor', 'unknown') and event.get('completed'))):
        result.append('E4')
    if event.get('new_consequence') == 'R2':
        result.append('E5')
    if event.get('new_consequence') == 'R3':
        result.append('E6')
    if event.get('mechanical_retry_passed'):
        result.append('E7')
    cost, expected = event.get('cost_usd'), event.get('expected_cost_usd')
    if type(cost) in (int, float) and type(expected) in (int, float) and expected >= 0 and cost > 2 * expected:
        result.append('E8')
    return result


def observe(store, event):
    if not isinstance(event, dict) or not event.get('evidence'):
        raise EngagementRefused('escalation needs a controller evidence pointer')
    fired = triggers(event)
    if not fired:
        return None
    identity = digest(event)
    previous = rows(store, ESCALATION)
    for existing in previous:
        if existing.get('event_sha256') == identity:
            return existing
    decision = latest(store, DECISION)
    if not decision:
        raise EngagementRefused('escalation requires the recorded engagement decision')
    policy = policy_module.load_policy()
    if decision['policy_sha256'] != policy['sha256']:
        raise EngagementRefused('policy changed after the engagement decision')
    step = event.get('step_id')
    old = current_tier(store)
    index = TIERS.index(old)
    run_trigger = any(t in fired for t in ('E1', 'E2', 'E3', 'E4', 'E5', 'E6'))
    scope = 'run' if run_trigger else 'step'
    if scope == 'step':
        index = max([index] + [TIERS.index(e['new_tier']) for e in previous
                               if e.get('step_id') == step and e['scope'] == 'step'])
        old = TIERS[index]
    if any(t in fired for t in ('E1', 'E2', 'E3', 'E4')):
        index = min(2, index + 1)  # one outcome, one correction; do not multiply overlapping signals
    if 'E5' in fired:
        index = max(index, 1)
    if 'E6' in fired:
        index = 2
    retries = sum('E7' in e['triggers'] and e.get('step_id') == step for e in previous)
    if 'E7' in fired and retries == 1:
        index = min(2, index + 1)
    new = TIERS[index]
    before = seat_plan(decision['scientific_plan'], old, policy)
    after = seat_plan(decision['scientific_plan'], new, policy)
    rereview = run_trigger or ('E7' in fired and retries >= 1)
    if scope == 'step' and rereview:
        # A second retry requires reviews on this step even when ordinary standard
        # policy would fold a non-claim step into a checkpoint. Keep its original
        # folded duties too; this is an additional subject-specific re-review.
        after = seat_plan(decision['scientific_plan'], current_tier(store), policy)
        separate = seat_plan(decision['scientific_plan'], 'full', policy)
        for seat in separate['seats']:
            if seat['step_id'] != step:
                continue
            after['seats'] = [s for s in after['seats'] if s['key'] != seat['key']] + [deepcopy(seat)]
            after['bindings'][seat['key']] = seat['key']
            after['actions'][seat['key']] = 'keep'
        after['sha256'] = digest({k: v for k, v in after.items() if k != 'sha256'})
    before_keys = {s['key'] for s in before['seats']}
    additions = [s for s in after['seats'] if s['key'] not in before_keys
                 and (scope == 'run' or s['step_id'] == step)]
    correction_count = sum('E2' in e['triggers'] and e.get('step_id') == step for e in previous) + ('E2' in fired)
    # A finding consumes the bound in force when it occurred; escalation does not reset the counter.
    bounds = [policy['correction_rounds'][old]] + [e['correction_bound'] for e in previous
                                                  if e.get('step_id') == step and 'E2' in e['triggers']]
    bound = min(bounds)
    return append(store, ESCALATION, {
        'event_sha256': identity, 'decision_id': decision['record_id'], 'triggers': fired,
        'evidence': deepcopy(event['evidence']), 'scope': scope, 'step_id': step,
        'subject_sha256': event.get('subject_sha256'), 'old_tier': old, 'new_tier': new,
        'seats_added': additions, 'seat_plan': after if new != old or rereview else before,
        'rereview': rereview, 'remaining_steps': 'not_yet_dispatched' if scope == 'run' else [step],
        'requires_rdj': 'E5' in fired, 'requires_authority': 'E6' in fired,
        'correction_count': correction_count, 'correction_bound': bound,
        'correction_exhausted': correction_count > bound, 'seat_addition_class': 'R1',
        'plan_deviation': False, 'notify': 'E8' in fired})
