"""Pure expected-run compilation from controller-selected inputs, before execution."""
from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
import json

from .records import DiagnosticsRefused, digest, seal


def _route(value):
    return value.get('id') if isinstance(value, dict) else value


def _unique(rows, field, what):
    values = [r.get(field) for r in rows]
    if any(not isinstance(v, str) or not v for v in values) or len(set(values)) != len(values):
        raise DiagnosticsRefused(what + ' identities must be nonempty and unique')


def build_expected(route_spec, plan, engagement, *, obligation_rows, instructions=None,
                   cards=None, classify=None, rdj_policy=None):
    """No effects and no implicit policy selection.

    ``engagement`` is the computed engagement decision, including its seat plan and envelope.
    ``obligation_rows`` is a prospective ledger population, each with its discharging
    node. Instruction and class services have the binding peer signatures; fakes
    can be supplied on a source tree where those peers have not been integrated.
    """
    if instructions is None:
        from ravel.controller import instructions
    if classify is None:
        from ravel.controller.judgment import classify
    if rdj_policy is None:
        rdj_policy = json.loads(files('ravel').joinpath('data/rdj/policy.json').read_text())
    if cards is None:
        from ravel.workflow.role_registry import all_cards
        cards = {c['id']: c for c in all_cards()}
    route = _route(plan.get('route'))
    if not route or route != _route(route_spec.get('id', route_spec.get('route'))):
        raise DiagnosticsRefused('selected route and compiled plan differ')
    if not plan.get('sha256') or engagement.get('scientific_plan_sha256') != plan['sha256']:
        raise DiagnosticsRefused('engagement decision does not bind this plan')
    tier = engagement.get('tier')
    if tier not in ('lean', 'standard', 'full'):
        raise DiagnosticsRefused('computed engagement tier required')
    seat_plan = engagement.get('seat_plan')
    if not isinstance(seat_plan, dict) or seat_plan.get('errors'):
        raise DiagnosticsRefused('complete computed seat plan required')
    steps = deepcopy(plan.get('steps', []))
    _unique(steps, 'id', 'step')
    checkins = deepcopy(plan.get('checkins', []))
    _unique(checkins, 'id', 'check-in')
    nodes, seats, cases = [], [], []

    def add_seat(step, seat, role, category, *, card=None, conditional=None, key=None):
        if not role or role not in cards:
            raise DiagnosticsRefused('instruction card missing for seat role: ' + str(role))
        card = deepcopy(card if card is not None else cards[role])
        spec = deepcopy(step)
        spec['role'] = role
        manifest = instructions.manifest(spec, card)
        units = deepcopy(manifest.get('units'))
        if not isinstance(units, list) or not manifest.get('sha256'):
            raise DiagnosticsRefused('instruction manifest incomplete')
        _unique(units, 'id', 'instruction unit')
        if any(not u.get('sha256') for u in units):
            raise DiagnosticsRefused('instruction unit digest missing')
        seats.append({'id': key or f"{step['id']}:{seat}", 'node_id': step['id'], 'seat': seat,
                      'role': role, 'category': category, 'conditional': conditional,
                      'manifest': manifest, 'instruction_units': units,
                      'acknowledge': [u['id'] for u in units if u.get('kind') == 'duty'],
                      'step_sha256': digest(spec)})

    bindings = seat_plan.get('bindings', {})
    for step in steps:
        # Unknown actions retain the peer's conservative R3 classification.
        action = deepcopy(step.get('action') or {})
        action.setdefault('step_kind', step.get('kind'))
        # As in the judgment planner, a decide step's rung is not a classification input.
        if step.get('rung') and step.get('kind') != 'decide':
            action.setdefault('rung', step['rung'])
        effects = list(action.get('effects') or []) + list(step.get('effects') or [])
        effects += list((step.get('parameters') or {}).get('effects') or [])
        if effects:
            action['effects'] = sorted(set(effects))
        consequence = classify(action)
        if consequence not in ('R0', 'R1', 'R2', 'R3'):
            consequence = 'R3'
        declared = step.get('consequence_class', step.get('class', 'R0'))
        if declared not in ('R0', 'R1', 'R2', 'R3'):
            declared = 'R3'
        consequence = max(consequence, declared)
        nodes.append({'id': step['id'], 'kind': 'step', 'role': step.get('role'),
                      'step_kind': step.get('kind'), 'depends_on': step.get('depends_on', []),
                      'consequence_class': consequence, 'step_sha256': digest(step)})
        producer = f"producer:{step['id']}:{step.get('role')}"
        if (step.get('role') and step.get('kind') not in ('ask', 'route', 'subgraph')
                and not step.get('launch') and not (step.get('parameters') or {}).get('launch')):
            if bindings.get(producer, producer) == producer:
                add_seat(step, 'producer', step['role'], 'producer', key=producer)
        if consequence in ('R2', 'R3') and step.get('kind') != 'ask':
            cases.append({'id': 'rdj:' + step['id'], 'node_id': step['id'],
                          'consequence_class': consequence, 'before_effect': True,
                          'authority_required': consequence == 'R3',
                          'subject_sha256': step.get('spec_sha256', digest(step)),
                          'requirements': deepcopy(rdj_policy['classes'][consequence])})
            for rdj_role in rdj_policy['classes'][consequence]['roles']:
                role = 'rdj-' + rdj_role.replace('_', '-')
                review_step = {**deepcopy(step), 'id': 'rdj:' + step['id'], 'kind': 'review', 'role': role}
                add_seat(review_step, role, role, 'rdj', key=f"rdj:{step['id']}:{role}")
    for checkin in checkins:
        nodes.append({'id': checkin['id'], 'kind': 'checkin', 'role': 'authority',
                      'after': deepcopy(checkin.get('after')), 'spec': checkin})
    _unique(nodes, 'id', 'node')
    for seat in seat_plan.get('seats', []):
        # A producer seat the engagement plan retains already appears in the producer population.
        if seat.get('key') in {s['id'] for s in seats}:
            continue
        step = deepcopy(seat.get('step', {}))
        step.setdefault('id', seat.get('step_id'))
        if not step.get('id'):
            raise DiagnosticsRefused('review seat has no node')
        if step['id'] not in {n['id'] for n in nodes}:
            nodes.append({'id': step['id'], 'kind': 'review', 'role': seat.get('role')})
        # The step controller uses role keys for reviews; the engagement plan keeps its full logical key.
        add_seat(step, seat.get('seat', seat['role']), seat['role'], seat.get('category', 'review'),
                 card=seat.get('card'), conditional=seat.get('conditional'), key=seat['key'])
    _unique(seats, 'id', 'seat')
    obligations = deepcopy(obligation_rows)
    _unique(obligations, 'key', 'obligation')
    if any(not r.get('row') or not r.get('discharge_node') for r in obligations):
        raise DiagnosticsRefused('every expected obligation needs a row and discharging node')
    envelope = engagement.get('projected_envelope') or engagement.get('envelopes', {}).get(tier)
    if (not isinstance(envelope, dict) or envelope.get('status') != 'ready'
            or any(not isinstance(envelope.get(k), dict) or not envelope[k] for k in ('floor', 'low', 'high'))):
        raise DiagnosticsRefused('engagement envelope bounds missing')
    return seal({'schema': 'expected-run.v1', 'route': route, 'route_spec_sha256': digest(route_spec),
                 'plan_sha256': plan['sha256'], 'plan_content_sha256': digest(plan),
                 'engagement_tier': tier, 'engagement_sha256': digest(engagement),
                 'nodes': nodes, 'seats': seats, 'rdj_cases': cases,
                 'obligations': sorted(obligations, key=lambda r: r['key']),
                 'seat_bindings': deepcopy(bindings), 'envelope': deepcopy(envelope)})
