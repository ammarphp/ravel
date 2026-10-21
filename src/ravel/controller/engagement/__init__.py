"""Binding engagement API. All decisions and usage evidence live in RunStore."""
from __future__ import annotations

from copy import deepcopy

from . import envelope, facts, policy
from .facts import action_of
from .envelope import JUDGMENT_ROUTE, budget_projection, check_envelope, envelope_binding
from .escalation import observe
from .records import (CHECK, DECISION, ESCALATION, EngagementRefused, append, current_tier,
                      data, digest, latest, resolve_applied_plan, rows, verify)

__all__ = ['action_of', 'assemble', 'decide', 'apply', 'observe', 'check_envelope', 'receipt_section', 'tier',
           'register_gates', 'gate_errors', 'envelope_binding']


def register_gates(ledger):
    """Explicit trusted composition; importing engagement installs no callbacks."""
    ledger.register_gate_hook('engagement', gate_errors)
    from ravel.controller.composition_usage import register
    register()


def tier(store):
    return current_tier(store)



def _operator():
    from ravel.controller.authority import operator_config
    return operator_config()


def decide(store, state):
    installed = policy.load_policy()
    collected, plan = facts.collect(store, state, installed)
    previous = latest(store, DECISION)
    approved = [a for a in rows(store, 'authority') if a.get('kind') == 'approve_plan'
                and a.get('authorizes_effects') is True]
    from ravel.controller.authority import frozen
    config = frozen(store, required=False)
    if config is None:
        config = _operator()
    route = plan['route']['id']
    try:
        envelopes = envelope.installed_projection()
        projected = envelopes.get('routes', {}).get(route, {})
    except EngagementRefused:
        projected = {}
    spec_sha256 = plan['route'].get('spec_sha256')
    if spec_sha256 and any(e.get('route_spec_sha256') != spec_sha256 for e in projected.values()):
        projected = {}
    if route == JUDGMENT_ROUTE and not spec_sha256:
        # A judgment plan has no route spec: its own plan is projected with the same builder, at the
        # check-in that approves it; that approval binds the projection (``envelope_binding``).
        from .builder import plan_projection
        try:
            projected = plan_projection(plan)
        except EngagementRefused:
            projected = {}
    return assemble(store, collected, plan, config, projected, installed=installed,
                    floors=[tier(store)] if approved and previous else [])


def assemble(store, collected, plan, config, projected, *, installed, floors=(), context=None):
    """The one engagement decision: the tier policy computes from ``collected`` and only floors raise it.

    ``floors`` are tiers already owed (an approved prior decision, an escalation); the frozen operator minimum
    and authenticated physicist raises for this plan apply after them. ``context`` facts are recorded with the
    decision without entering the tier computation. Rendering twice before any input changes is idempotent.
    """
    computed = policy.tier(collected, installed)
    selected = computed['tier']
    for floor in floors:
        selected = policy.raise_only(selected, floor)
    minimum = config.get('engagement', {}).get('minimum_tier')
    selected = policy.raise_only(selected, minimum)
    authorities = rows(store, 'authority')
    raises = [a for a in rows(store, 'engagement-raise') if a.get('plan_sha256') == plan['sha256']
              and a.get('channel') == 'terminal' and a.get('authority_record_id') in
              {r.get('uid', r['record_id']) for r in authorities
               if r.get('authorizes_effects') is True
               and r.get('label') in ('human', 'physicist_terminal_response')
               and (r.get('subject') or {}).get('pins', {}).get('plan_sha256') == plan['sha256']}]
    for raise_record in raises:
        selected = policy.raise_only(selected, raise_record['tier'])
    seats = policy.seat_plan(plan, selected, installed)
    # Unclassified seats are preserved in the decision; application refuses until policy coverage is complete.
    budget = budget_projection(projected.get(selected), config.get('budgets', {}))
    from .compute import DEFAULT, validate as compute_policy
    decision = {
        'policy_id': installed['id'], 'policy_version': installed['version'], 'policy_sha256': installed['sha256'],
        'facts': {**collected, **deepcopy(context or {})}, 'minimum_tiers': computed['minimum_tiers'],
        'computed_tier': computed['tier'],
        'tier': selected, 'reasons': computed['reasons'], 'seat_plan': seats, 'seat_plan_sha256': seats['sha256'],
        'correction_bound': installed['correction_rounds'][selected], 'packet_scope': installed['packet_scope'][selected],
        'envelopes': projected, 'projected_envelope': projected.get(selected), 'budget_authority': budget,
        'compute_policy': compute_policy(config.get('compute_policy', DEFAULT)),
        'operator_minimum': minimum, 'physicist_raise_ids': [r['record_id'] for r in raises],
        'authority_record_ids': [a.get('uid', a['record_id']) for a in authorities
                                 if a.get('kind') == 'approve_plan' and a.get('authorizes_effects') is True],
        'scientific_plan_sha256': plan['sha256'], 'scientific_plan': plan,
    }
    previous = latest(store, DECISION)
    if previous and all(previous.get(k) == v for k, v in decision.items()):
        return previous
    return append(store, DECISION, decision)


def apply(plan, decision):
    verify(decision)
    installed = policy.load_policy()
    if decision['policy_sha256'] != installed['sha256']:
        raise EngagementRefused('policy changed after the engagement decision')
    original = deepcopy(plan)
    if original.get('engagement'):
        # Re-application always starts from the pinned scientific plan, not yesterday's seat projection.
        original = deepcopy(decision['scientific_plan'])
    if original.get('sha256') != decision['scientific_plan_sha256'] or original != decision['scientific_plan']:
        raise EngagementRefused('decision belongs to a different scientific plan')
    seats = decision['seat_plan']
    if seats['sha256'] != digest({k: v for k, v in seats.items() if k != 'sha256'}):
        # No-review plans also use the ordinary content digest.
        raise EngagementRefused('seat plan digest mismatch')
    if seats['errors']:
        raise EngagementRefused('; '.join(seats['errors']))
    result = deepcopy(original)
    for step in result['steps']:
        descriptors = [deepcopy(s) for s in seats['seats']
                       if s['step_id'] == step['id'] and s['category'] == 'step']
        step['engagement_seats'] = descriptors
        step['seats'] = ([{'seat': step['role'], 'role': step['role'], 'kind': 'producer'}]
                         if step.get('role') else [])
        step['seats'] += [{'seat': s['key'], 'role': s['role'], 'kind': 'review'} for s in descriptors]
        source_key = f"producer:{step['id']}:{step.get('role')}"
        if source_key in seats['bindings'] and seats['bindings'][source_key] != source_key:
            step['engagement_folded_into'] = seats['bindings'][source_key]
        if (step.get('parameters') or {}).get('phase') == 'prepare':
            step['engagement'] = deepcopy(installed['packet_scope']['full'])
        else:
            step['correction_rounds'] = decision['correction_bound']
            step['engagement'] = deepcopy(decision['packet_scope'])
    checkins = {c['id']: c for c in result.get('checkins', [])}
    for name in seats['authority_nodes']:
        checkins.setdefault(name, {'id': name, 'sections': []})
        checkins[name]['seats'] = list(dict.fromkeys(
            s['role'] for s in seats['seats'] if s['step_id'] == name and not s['conditional']))
        checkins[name]['engagement_seats'] = [deepcopy(s) for s in seats['seats'] if s['step_id'] == name]
    result['checkins'] = list(checkins.values())
    result['engagement'] = {'tier': decision['tier'], 'decision_id': decision.get('record_id'),
                            'decision_sha256': decision['sha256'], 'policy_sha256': decision['policy_sha256'],
                            'seat_plan_sha256': decision['seat_plan_sha256'], 'seat_plan': deepcopy(seats),
                            'packet_scope': deepcopy(decision['packet_scope']),
                            'correction_bound': decision['correction_bound']}
    # This digest intentionally remains the original scientific plan digest.
    result['sha256'] = original['sha256']
    result['engagement']['applied_sha256'] = digest(result)
    return result


def check_applied(plan, decision):
    scientific = decision['scientific_plan']
    if (scientific.get('sha256') != decision['scientific_plan_sha256']
            or digest({k: v for k, v in scientific.items() if k != 'sha256'}) != scientific['sha256']):
        raise EngagementRefused('scientific plan digest mismatch')
    expected = apply(decision['scientific_plan'], decision)
    return [] if plan == expected else ['EG03: declared seats or scientific plan differ from engagement.apply']


def _delivery_counter_current(store, delivery):
    if not store.scan('provider-counter'):
        return True  # Other explicitly composed counters retain their own source contract.
    from ravel.controller.composition_usage import counter
    current = counter(store)
    recorded = (delivery or {}).get('broker') or {}
    return (type(current.get('requests')) is int and type(current.get('tokens')) is int
            and all(current[k] == recorded.get(k) for k in ('requests', 'tokens')))


def receipt_section(store):
    decision = latest(store, DECISION)
    escalations, checks = rows(store, ESCALATION), rows(store, CHECK)
    for record in ([decision] if decision else []) + escalations + checks:
        verify(record)
    last = checks[-1] if checks else None
    delivery = last if last and last['stage'] == 'deliver' else None
    census = {'dispatches': rows(store, 'step-dispatch'), 'observations': rows(store, 'step-observation'),
              'deliveries': [r for r in rows(store, 'instruction-delivery')
                             if r.get('kind') == 'instruction-delivery-session'],
              'settlements': rows(store, 'budget-settlement')}
    if delivery and (delivery.get('usage_sha256') != digest(census)
                     or delivery.get('escalation_sha256') != digest(escalations)
                     or delivery.get('decision_id') != (decision or {}).get('record_id')
                     or delivery.get('tier') != tier(store)
                     or not _delivery_counter_current(store, delivery)):
        delivery = None
    labels = sorted({label for check in checks for label in check['labels']})
    unavailable = data('envelopes.json').get('status') == 'unavailable'
    if not delivery or unavailable:
        labels = sorted(set(labels) | {'USAGE UNKNOWN'})
    accepted = bool(decision and delivery and delivery['accepted_allowed'] and not unavailable)
    return {'tier': tier(store), 'decision_id': (decision or {}).get('record_id'),
            'policy_sha256': (decision or {}).get('policy_sha256'), 'facts': (decision or {}).get('facts', {}),
            'reasons': (decision or {}).get('reasons', []),
            'seat_plan_sha256': effective_decision(store)['seat_plan_sha256'] if decision else None,
            'escalations': escalations, 'envelope_checks': checks,
            'envelope_status': 'unavailable' if unavailable else last['status'] if last else 'unknown', 'labels': labels,
            'accepted_allowed': accepted, 'architecture_complete_allowed': accepted}


def effective_decision(store):
    """Projection for undispatched work; original decision/escalations stay immutable."""
    original = latest(store, DECISION)
    if not original:
        raise EngagementRefused('engagement decision missing')
    verify(original)
    selected = tier(store)
    projected = deepcopy(original)
    installed = policy.load_policy()
    if original['policy_sha256'] != installed['sha256']:
        raise EngagementRefused('policy changed after the engagement decision')
    projected['tier'] = selected
    projected['seat_plan'] = policy.seat_plan(original['scientific_plan'], selected, installed)
    # Step-scoped second-retry raises affect only that step's review and the triggering subject.
    for event in rows(store, ESCALATION):
        if event['scope'] != 'step' or not event['rereview']:
            continue
        for seat in event['seat_plan']['seats']:
            if seat['step_id'] == event['step_id'] and seat['key'] not in {s['key'] for s in projected['seat_plan']['seats']}:
                projected['seat_plan']['seats'].append(deepcopy(seat))
                projected['seat_plan']['bindings'][seat['key']] = seat['key']
                projected['seat_plan']['actions'][seat['key']] = 'keep'
    projected['seat_plan']['sha256'] = digest({k: v for k, v in projected['seat_plan'].items() if k != 'sha256'})
    projected['seat_plan_sha256'] = projected['seat_plan']['sha256']
    projected['correction_bound'] = installed['correction_rounds'][selected]
    projected['packet_scope'] = installed['packet_scope'][selected]
    projected['sha256'] = digest({k: v for k, v in projected.items() if k not in ('sha256', 'record_id')})
    return projected


def gate_errors(store, transition, *, plan=None):
    """Additional unmet rows; never substitutes for the ordinary ledger gate."""
    # P02 supplies the canonical name; preserve direct callers of the ASCII API.
    if transition.replace('->', '→') == 'checkin1→execute':
        try:
            decision = effective_decision(store)
            applied = resolve_applied_plan(store, plan, decision)
            errors = check_applied(applied, decision)
        except (EngagementRefused, KeyError, TypeError, ValueError, OSError) as exc:
            errors = [f'EG03: {exc}']
        return [{'row': 'EG03', 'reason': error} for error in errors]
    if transition == 'deliver[accepted]':
        section = receipt_section(store)
        errors = [] if section['accepted_allowed'] else [{'row': 'EG08', 'reason': section['envelope_status']}]
        checks = section['envelope_checks']
        delivery = checks[-1] if checks and checks[-1]['stage'] == 'deliver' else {}
        if (not delivery.get('broker', {}).get('available')
                or delivery.get('floors', {}).get('H5', {}).get('status') != 'ok'
                or not _delivery_counter_current(store, delivery)):
            errors.append({'row': 'EG09', 'reason': 'independent broker reconciliation missing or failed'})
        return errors + rereview_errors(store)
    return []


def _credited_roles(credit):
    """Roles whose review a step-credit record credits: its credited seats and its own credited review."""
    roles = {r.get('role') for r in credit.get('seats') or () if isinstance(r, dict) and r.get('credited') is True}
    own = credit.get('own') or {}
    if own.get('credited') is True:
        roles.add((own.get('query') or {}).get('role'))
    return roles


def _superseded(store, step):
    """The approved deviation record that installed the current scientific plan without ``step``, or None."""
    try:
        plan, _ = facts.plan_from_store(store, {})
    except (EngagementRefused, KeyError, TypeError, ValueError, OSError):
        return None
    if any(s.get('id') == step for s in plan.get('steps', [])):
        return None
    approvals = [a for a in rows(store, 'authority') if a.get('kind') == 'deviation' and a.get('decision') == 'approve'
                 and a.get('authorizes_effects') is True
                 and ((a.get('subject') or {}).get('pins') or {}).get('plan_sha256') == plan['sha256']]
    return approvals[-1] if approvals else None


def rereview_errors(store):
    """EG05 at accepted delivery: every escalation that requires a re-review (``rereview``) is discharged by review
    evidence recorded after it. A step's escalation needs a later credited review of that step whose credited roles
    include every seat the escalation added on it; a run-level escalation without a step needs a later final review
    round whose every seat credited and accepted. An undischarged re-review withholds acceptance, typed; nothing here
    relaxes another row."""
    escalations = store.scan(ESCALATION)
    if not escalations:
        return []
    credits = store.scan('step-credit')
    finals = [r for r in store.scan('review') if r['record'].get('purpose') == 'final']
    errors = []
    for row in escalations:
        event = row['record']
        if event.get('rereview') is not True:
            continue
        seq = row.get('seq')
        later = lambda found: type(seq) is int and type(found.get('seq')) is int and found['seq'] > seq  # noqa: E731
        step = event.get('step_id')
        if step is not None and _superseded(store, step) is not None:
            # The subject no longer exists: an approved deviation (a replan or a recovery) installed the current
            # plan without this step, so none of its outputs can be delivered and nothing is left to re-review.
            continue
        if step is None:
            discharged = any(later(r) and r['record'].get('seats') and all(
                v.get('credited') is True and v.get('verdict') == 'accept' for v in r['record']['seats'].values())
                for r in finals)
        else:
            needed = {s.get('role') for s in event.get('seats_added') or () if s.get('step_id') == step}
            discharged = any(later(r) and r['record'].get('step_id') == step and r['record'].get('credited') is True
                             and needed <= _credited_roles(r['record']) for r in credits)
        if not discharged:
            errors.append({'row': 'EG05', 'id': 'EG05',
                           'reason': f"rereview_undischarged:{row['id']}:{step or 'run'}",
                           'message': f"the re-review the escalation {row['id']} requires on "
                                      f"{step or 'the run result'} has no later credited review"})
    return errors
