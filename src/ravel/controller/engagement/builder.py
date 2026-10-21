"""The envelope builder: compile actual instruction packets for a plan's sessions and project them.

One builder serves both sources. ``scripts/maintenance/build_engagement_envelopes.py`` runs it over
the installed route specs (the content-pinned ``envelopes.json``); the controller runs it at
CHECK-IN 1 over a judgment-planned run's own plan (``plan_projection``), which has no route spec.
No models or scientific execution.
"""
from __future__ import annotations

from copy import deepcopy

from .envelope import installed_projection, project
from .policy import _packet_step, load_policy, role_cards, seat_plan
from .records import TIERS, EngagementRefused, data, digest


class PacketScopeUnavailable(EngagementRefused):
    """The installed renderer cannot represent the requested reduced packet yet."""


class InstalledInstructions:
    """Translate route checkpoint names to the installed catalogue's template selectors."""

    def __init__(self, provider):
        self.provider = provider

    def __getattr__(self, name):
        return getattr(self.provider, name)

    @staticmethod
    def step(step):
        result = deepcopy(step)
        checkpoint = result.get('checkin')
        if checkpoint in ('checkin1', 'checkin2', 'checkin3'):
            result['checkin'] = 'CI' + checkpoint[-1]
        elif checkpoint in ('attack', 'integrity'):
            result['checkin'] = 'CI3'
        return result

    def manifest(self, step, card):
        return self.provider.manifest(self.step(step), card)

    def packet(self, manifest, card, step, inputs, **options):
        return self.provider.packet(manifest, card, self.step(step), inputs, **options)

    def check_packet(self, packet, manifest, card, step, inputs, **options):
        return self.provider.check_packet(packet, manifest, card, self.step(step), inputs, **options)


def installed_instructions():
    from ravel.controller import instructions
    return InstalledInstructions(instructions) if hasattr(instructions, 'check_packet') else instructions


def _packet(step, card, instructions, tier, policy):
    step = deepcopy(step)
    step['role'] = card['id']
    step['engagement'] = {**step.get('engagement', {}), **policy['packet_scope'][tier]}
    manifest = instructions.manifest(step, card)
    owed = {u['id'] for m in step['engagement'].get('folded_manifests', []) for u in m['units']}
    if not owed <= {u['id'] for u in manifest['units']}:
        # Some binding providers carry the union in the effective card instead of
        # the step. Accept that representation only through their ordinary checks.
        card = {**deepcopy(card), 'folded_cards': deepcopy(step['engagement'].get('folded_cards', []))}
        try:
            manifest = instructions.manifest(step, card)
        except ValueError as exc:
            raise PacketScopeUnavailable('installed renderer omits folded units; project full seats') from exc
        if not owed <= {u['id'] for u in manifest['units']}:
            raise PacketScopeUnavailable('installed renderer omits folded units; project full seats')
    built = instructions.packet(manifest, card, step, [])
    if hasattr(instructions, 'check_packet'):
        errors = instructions.check_packet(built, manifest, card, step, [])
        if errors:
            raise EngagementRefused('; '.join(errors))
    if not isinstance(built.get('text'), str) or not built['text']:
        raise EngagementRefused('empty instruction packet')
    deferred = set(built.get('deferred', []))
    duties = [u for u in manifest['units'] if u['kind'] == 'duty']
    if deferred & {u['id'] for u in duties}:
        raise EngagementRefused('packet defers duty units')
    if tier == 'lean' and any(u['kind'] == 'context' and u.get('via') not in ('card', 'must_read', 'knowledge')
                              and u['id'] not in deferred for u in manifest['units']):
        raise PacketScopeUnavailable('lean packet inlines deferrable context; project full packets')
    tokens = built.get('tokens', math_tokens(built['text']))
    if type(tokens) is not int or tokens <= 0:
        raise EngagementRefused('packet token estimate must be a positive integer')
    return {'packet_tokens': tokens, 'duty_units': len(duties), 'packet_sha256': built['sha256'],
            'manifest_sha256': manifest['sha256']}


def math_tokens(text):
    return (len(text) + 3) // 4


def build_tier(plan, spec, tier, cards, instructions, policy, calibration):
    from .planning import prepare_outputs
    plan = {**plan, 'steps': prepare_outputs(plan.get('steps', []))}
    seats = seat_plan(plan, tier, policy, cards=cards, instructions=instructions, projection=True)
    if seats['errors']:
        raise EngagementRefused('; '.join(seats['errors']))
    sessions = []
    for step in plan.get('steps', []):
        role = step.get('role')
        if not role:
            continue  # governed launches have no model session
        if role not in cards:
            raise EngagementRefused('unknown producer role: ' + role)
        key = f"producer:{step['id']}:{role}"
        if key in seats['bindings']:
            continue  # verification producers are represented in the seat plan
        fixed = (step.get('parameters') or {}).get('phase') == 'prepare'
        built = _packet(step, cards[role], instructions, 'full' if fixed else tier, policy)
        sessions.append({**built, 'key': key, 'category': 'producer', 'conditional': False,
                         'reserved_calls': (cards[role].get('stop') or {}).get('max_turns', 0),
                         'reserved_tokens': (step.get('budget') or {}).get('tokens', 0) or 0})
        # Consult triggers are controller facts evaluated at execution. Reserve
        # their possible sessions, without pretending they all must fire.
        consult_keys = set()
        for consult in cards[role].get('knowledge', {}).get('consult', []):
            when, consult_role = consult['when'], consult['role']
            if when not in ('before_first_smoke', 'on_use', 'failure', 'contested_node'):
                raise EngagementRefused('unclassified consult trigger: ' + when)
            if when == 'before_first_smoke' and step.get('rung') != 'smoke':
                continue
            if consult_role not in cards:
                raise EngagementRefused('unknown consult role: ' + consult_role)
            consult_key = f"consult:{step['id']}:{consult_role}:{when}"
            if consult_key in consult_keys:
                continue
            consult_keys.add(consult_key)
            consult_step = {**deepcopy(step), 'id': consult_key, 'kind': 'consult', 'role': consult_role}
            built = _packet(consult_step, cards[consult_role], instructions, 'full' if fixed else tier, policy)
            sessions.append({**built, 'key': consult_key, 'category': 'consult', 'conditional': True,
                             'trigger': when,
                             'reserved_calls': (cards[consult_role].get('stop') or {}).get('max_turns', 0)})
    for seat in seats['seats']:
        fixed = seat['category'] == 'checkin1' or (seat['step'].get('parameters') or {}).get('phase') == 'prepare'
        packet_step = _packet_step(seat, policy['packet_scope']['full' if fixed else tier])
        built = _packet(packet_step, seat['card'], instructions, 'full' if fixed else tier, policy)
        sessions.append({**built, 'key': seat['key'], 'category': 'checkin' if seat['category'].startswith('checkin') else 'review',
                         'conditional': bool(seat['conditional']),
                         'reserved_calls': (seat['card'].get('stop') or {}).get('max_turns', 0),
                         'reserved_tokens': (seat['step'].get('budget') or {}).get('tokens', 0) or 0})
    # Each non-worker effect also consumes a child reservation. Operation templates
    # may materialise launches later; reserving both paths is conservative.
    effects = sum(s.get('kind') in ('operate', 'acquire', 'subgraph') for s in plan.get('steps', []))
    retries = calibration['high_retries']
    reservations = {'children': len(sessions) + effects + retries,
                    'model_calls': sum(s.get('reserved_calls', 0) for s in sessions)
                                   + retries * max((s.get('reserved_calls', 0) for s in sessions), default=0),
                    'tokens': sum(s.get('reserved_tokens', 0) for s in sessions)
                              + retries * max((s.get('reserved_tokens', 0) for s in sessions), default=0)}
    projected = project(sessions, calibration)
    projected['high']['sessions'] = max(projected['high']['sessions'], reservations['children'])
    projected['high']['calls'] = max(projected['high']['calls'], reservations['model_calls'])
    projected['high']['input_tokens'] = max(projected['high']['input_tokens'], reservations['tokens'])
    return {**projected, 'reservations': reservations, 'route_spec_sha256': digest(spec)}, sessions


def build_tiers(plan, spec, tiers, *, cards, instructions, policy, calibration):
    """Every tier's entry and sessions; an unsupported reduction retains the complete full-seat upper bound."""
    entries, packets = {}, {}
    for tier in tiers:
        try:
            entry, sessions = build_tier(plan, spec, tier, cards, instructions, policy, calibration)
        except PacketScopeUnavailable as exc:
            # Preserve the scope check: compile and validate the full roster instead.
            # This is an upper bound until the installed renderer supports reduction.
            entry, sessions = build_tier(plan, spec, 'full', cards, instructions, policy, calibration)
            entry['projection_tier'] = 'full'
            entry['scope_reason'] = str(exc)
        entries[tier], packets[tier] = entry, sessions
    return entries, packets


def plan_projection(plan):
    """The envelope of one scientific plan that no installed route spec projects (a judgment-planned run).

    Built at CHECK-IN 1 from the plan's own steps, seats and every tier with the builder the installed
    route projections use, from the same current installed policy, calibration and instruction sources:
    a stale or unavailable installed projection refuses here as it refuses for every fixed route. Each
    entry names the plan it projects (``plan_sha256``); the decision that carries it is what CHECK-IN 1's
    authority binds (``engagement_envelope_sha256``)."""
    if type(plan) is not dict or type(plan.get('sha256')) is not str:
        raise EngagementRefused('plan projection needs the scientific plan digest')
    installed_projection()  # currency of policy, calibration and instruction sources
    policy = load_policy()
    spec = {k: deepcopy(v) for k, v in plan.items() if k not in ('sha256', 'engagement')}
    target = {**deepcopy(spec), 'route': deepcopy(plan.get('route') or {'id': 'judgment'})}
    target['deliverables'] = [{**d, 'id': d.get('id', f'deliverable-{i}')}
                              for i, d in enumerate(plan.get('deliverables', []))]
    try:
        entries, _ = build_tiers(target, spec, TIERS, cards=role_cards(), instructions=installed_instructions(),
                                 policy=policy, calibration=data('calibration.json'))
    except (ImportError, KeyError, TypeError, RuntimeError) as exc:
        raise EngagementRefused('plan projection unavailable: ' + str(exc)) from exc
    return {tier: {**entry, 'source': 'plan', 'plan_sha256': plan['sha256']} for tier, entry in entries.items()}
