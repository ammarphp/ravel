"""Reviewed, source-bound engagement facts. Worker assertions earn no lowering."""
from __future__ import annotations

from copy import deepcopy
import json
import math

from .records import digest, latest, rows, EngagementRefused

FACTS = ('route', 'deliverables', 'consequence', 'compute', 'novelty', 'special')


def fact(value=None, source='missing', checker='unknown'):
    return {'value': value, 'source': source, 'checker': checker}


def action_of(step):
    """Project a step's action onto the judgment tables without hiding unknowns."""
    parameters = step.get('parameters') or {}
    judgment = parameters.get('judgment') or {}
    action = judgment.get('action', parameters.get('action', step.get('action', {})))
    action = deepcopy(action) if isinstance(action, dict) else {'kind': action}
    action['kind'] = step.get('operation', step.get('action_kind',
                                  parameters.get('action_kind', action.get('kind'))))
    action['step_kind'] = step.get('kind')
    for field in ('rung', 'gate', 'research_choice'):
        action[field] = step.get(field, parameters.get(field, action.get(field)))
    effects = []
    for source in (action, parameters, step):
        values = source.get('effects')
        if values is not None:
            if not isinstance(values, list):
                effects = deepcopy(values)
                break
            effects.extend(deepcopy(values))
    action['effects'] = effects
    action['declared_class'] = step.get('consequence_class')
    return action


def plan_from_store(store, state):
    pin = latest(store, 'plan')
    if not pin:
        raise EngagementRefused('a pinned plan is required')
    plan = pin.get('plan')
    if plan is None and pin.get('blob'):
        blob = pin['blob']
        path = blob.get('path') if isinstance(blob, dict) else ('blobs/' + blob if isinstance(blob, str) and len(blob) == 64 and all(c in '0123456789abcdef' for c in blob) else None)
        if not path or path.startswith('/') or '..' in path.split('/'):
            raise EngagementRefused('invalid plan blob pointer')
        raw = store.path(*path.split('/')).read_bytes()
        from hashlib import sha256
        if sha256(raw).hexdigest() != (blob.get('sha256') if isinstance(blob, dict) else blob):
            raise EngagementRefused('plan blob digest mismatch')
        plan = json.loads(raw)
    if plan is None:
        candidate = state.get('plan', {})
        if 'steps' in candidate:
            plan = candidate
    if not isinstance(plan, dict) or pin.get('plan_sha256') != plan.get('sha256'):
        raise EngagementRefused('plan does not match its store pin')
    if plan['sha256'] != digest({k: v for k, v in plan.items() if k != 'sha256'}):
        raise EngagementRefused('scientific plan digest mismatch')
    return deepcopy(plan), pin['record_id']


def _reviewed(store, record, plan_sha):
    """A controller credit names both the exact fact bytes and current plan."""
    if not record:
        return False
    subject = digest({k: v for k, v in record.items() if k != 'record_id'})
    return any(r.get('credited') is True and r.get('role') == 'plan-critic'
               and r.get('subject_sha256') == subject and r.get('plan_sha256') == plan_sha
               for r in rows(store, 'engagement-fact-credit'))


def compute_class(method, policy, *, points=1):
    from ravel.workflow.method_selection import validate_method_decision
    if validate_method_decision(method):
        return 'C3'
    rung = method['selected']['method']
    base = policy['compute']['rungs'].get(rung, 'C3')
    hours = method.get('cost_forecast', {}).get('cpu_hours')
    if type(points) is not int or points < 0:
        return 'C3'
    if type(hours) not in (int, float) or not math.isfinite(hours) or hours < 0:
        return 'C3'
    if points > policy['compute']['max_scan_points'] or hours > policy['compute']['max_scan_core_hours']:
        return 'C3'
    if points > 1 or hours > policy['compute']['max_one_point_core_hours']:
        base = max(base, 'C2')
    return base


def plan_consequence(plan):
    try:
        from ravel.controller.judgment import classify
    except ImportError:
        classify = lambda action: 'R3'
    classes = []
    for step in plan.get('steps', []):
        action = action_of(step)
        if step.get('kind') == 'decide' or action.get('effects') or step.get('consequence_class') is not None:
            value = classify(action)
            if value not in ('R0', 'R1', 'R2', 'R3'):
                value = 'R3'
            declared = step.get('consequence_class', 'R0')
            if declared not in ('R0', 'R1', 'R2', 'R3'):
                declared = 'R3'
            classes.append(max(value, declared))
    return max(classes, default='R0')


def plan_compute(method, plan, policy, *, points=None):
    value = compute_class(method, policy, points=(len(plan.get('scan_points', [])) or 1) if points is None else points)
    rungs = [s.get('rung') for s in plan.get('steps', [])]
    if any(r and r not in policy['compute']['plan_rungs'] for r in rungs):
        return 'C3'
    if 'scan' in rungs:
        return max(value, 'C2')
    if any(s.get('operation') or s.get('launch') or (s.get('parameters') or {}).get('launch')
           for s in plan.get('steps', [])):
        return max(value, 'C1')
    return value


def collect(store, state, policy):
    plan, pointer = plan_from_store(store, state)
    result = {name: fact() for name in FACTS}
    selected = latest(store, 'route')
    route = (plan.get('route') or {}).get('id')
    if selected and selected.get('route') == route:
        value = route
        if route == 'judgment':
            value = 'judgment.fallback' if selected.get('reason') == 'known-mode-no-spec' else 'judgment.open'
        result['route'] = fact(value, selected['record_id'], 'code:route-select')
    reading = latest(store, 'engagement-population')
    deliveries = plan.get('deliverables', [])
    expected = sorted(d['id'] for d in deliveries)
    if (reading and reading.get('plan_sha256') == plan['sha256']
            and sorted(reading.get('deliverable_ids', [])) == expected
            and len(expected) == len(set(expected)) and not plan.get('open_obligations')
            and all(d.get('status', 'mapped') == 'mapped' for d in deliveries)):
        result['deliverables'] = fact(len(deliveries), reading['record_id'], 'code:population-equality')
    result['consequence'] = fact(plan_consequence(plan), pointer + '#/steps', 'code:classify')
    method = latest(store, 'engagement-method')
    if _reviewed(store, method, plan['sha256']):
        value = plan_compute(method['method'], plan, policy, points=method.get('scan_points', 1))
        result['compute'] = fact(value, method['record_id'], 'code+plan-critic')
    novelty = latest(store, 'engagement-novelty')
    if _reviewed(store, novelty, plan['sha256']) and novelty.get('value') in ('N0', 'N1', 'N2'):
        result['novelty'] = fact(novelty['value'], novelty['record_id'], 'code+plan-critic')
    # Special flags must be a complete controller-derived inventory bound to this plan.
    special = latest(store, 'engagement-special')
    if special and special.get('plan_sha256') == plan['sha256'] and special.get('complete') is True:
        result['special'] = fact(special.get('flags'), special['record_id'], 'code:special-inventory')
    return result, plan


def special_flags(plan, contract, *, parent='unknown'):
    flags = []
    route = (plan.get('route') or {}).get('id', '')
    if route == 'ml.training':
        flags.append('ml_training')
    if parent in ('research', 'judgment'):
        flags.append(parent + '_child')
    if contract.get('mixed_request') is True:
        flags.append('mixed_request')
    effects = [effect for step in plan.get('steps', []) for effect in
               list(step.get('effects') or []) + list((step.get('parameters') or {}).get('effects') or [])]
    if 'unblind' in effects or contract.get('unblinding') is True:
        flags.append('unblinding')
    return sorted(set(flags))


def pin_inputs(store, plan, reading, contract, *, method=None, novelty=None, parent='unknown', method_source=None):
    """Pin adopted planning inputs and original scope for the plan critic."""
    expected = sorted(d.get('id') for d in reading.get('deliverables', []) if d.get('id'))
    actual = sorted(d.get('id') for d in plan.get('deliverables', []) if d.get('id'))
    if expected == actual and len(expected) == len(reading.get('deliverables', [])):
        store.append('engagement-population', {'plan_sha256': plan['sha256'], 'deliverable_ids': expected})
    store.append('engagement-special', {'plan_sha256': plan['sha256'], 'flags': special_flags(plan, contract, parent=parent),
                                        'complete': parent in ('none', 'research', 'judgment')})
    store.append('engagement-method', {'method': deepcopy(method), 'plan_sha256': plan['sha256'],
                                       'scan_points': len(plan.get('scan_points', [])) or 1,
                                       **({'source': deepcopy(method_source)} if method_source is not None else {})})
    if novelty in ('N0', 'N1', 'N2'):
        store.append('engagement-novelty', {'value': novelty, 'plan_sha256': plan['sha256']})
    return review_items(store, plan)


def review_items(store, plan):
    result = []
    for kind in ('engagement-method', 'engagement-novelty'):
        row = latest(store, kind)
        if (row and row.get('plan_sha256') == plan['sha256']
                and (kind != 'engagement-method' or row.get('method') is not None)):
            result.append({'id': kind, 'record_id': row['record_id'],
                           'subject_sha256': digest({k: v for k, v in row.items() if k != 'record_id'}),
                           'must_check': 'Verify the source and content of this engagement fact.'})
    from .planning import child_items
    return result + child_items(store, plan)


def credit_reviewed_facts(store, plan, review_record_id):
    """Credit only fact hashes that the protected plan review actually covered."""
    review = store.read('review', review_record_id)['record']
    critic = review.get('seats', {}).get('plan-critic', {})
    if review.get('plan_sha256') != plan['sha256'] or critic.get('credited') is not True or critic.get('verdict') != 'accept':
        return []
    covered = review.get('engagement_fact_sha256s', [])
    recorded = []
    for item in review_items(store, plan):
        if item['subject_sha256'] in covered:
            recorded.append(store.append('engagement-fact-credit', {
                'credited': True, 'role': 'plan-critic', 'subject_sha256': item['subject_sha256'],
                'plan_sha256': plan['sha256'], 'review_record_id': review_record_id}))
    return recorded
