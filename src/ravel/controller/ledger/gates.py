"""Transition gates over the obligation ledger (CONTROLLER-SPEC 3.1, 3.2 and 7.4).

``unmet(store, transition)`` lists every requirement of the transition that the ledger does not show as met. The
main path is cumulative: each transition also requires everything the earlier ones did. A transition may carry a
qualifier in brackets: the waypoint step for ``checkin2→execute[s05]``, the launching step for ``launch[s07]``,
the occurrence for ``deviation→execute[d2]``.

An instance is met when it is ``satisfied`` (R rows with a credit, I rows with an acknowledgement),
``not_applicable`` with its reason, ``waived`` where its row is waivable, or, for an L row, ``violated`` with the
label the sink renders. A step is closed when its plan instances are met, it entered the step graph, every
expected seat (and scan point) has an attempt, and the latest attempt of every seat is met. Superseded attempts and
removed steps do not count; their violations stay in the receipt.

``deliver[accepted]`` requires every current instance met, every plan step closed, every original obligation
covered or waived, the delivery materialised and no run-level violation. ``deliver[qualified]`` (and the bounded
ending) requires only a ledger that can state every obligation: a verified chain, the catalogue the run pinned and
an intake materialisation. Each unmet row names its consequence: ``qualified`` (incomplete; waivable or a
population hole) or ``diagnostic`` (a row nobody may waive for an accepted result, or a ledger fault).
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
import json
import re

from . import catalogue as catalogue_module, chain
from .catalogue import Catalogue
from .state import State, load as load_state

PLAN_REVIEW_STEP = 'plan_review'
FINAL_REVIEW_STEP = 'final_review'
_GATE_HOOKS = {}
_HOOK_CACHE = ContextVar('ledger_gate_hook_cache', default=None)


def register_gate_hook(provider_id: str, fn) -> None:
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ValueError('a gate provider id is a nonempty string')
    if not callable(fn):
        raise TypeError('a gate hook must be callable')
    if provider_id in _GATE_HOOKS and _GATE_HOOKS[provider_id] is not fn:
        raise ValueError(f'gate provider {provider_id!r} is already registered')
    _GATE_HOOKS[provider_id] = fn


@contextmanager
def hook_scope():
    """Share callback results only within one decision and its nested transition check."""
    token = _HOOK_CACHE.set({})
    try:
        yield
    finally:
        _HOOK_CACHE.reset(token)

INTAKE_NODES = ('controller.intake', 'controller.route_select')
PLAN_NODES = ('judgment.frame', 'judgment.decompose', 'judgment.classify', 'step.seat_derivation',
              'step.plan_bind')

# name -> requirements. 'after' makes the path cumulative. 'own' is the GATE row the transition's own decision
# discharges: that transition does not require it, and every edge taken after the decision does.
APPROVED = ('GATE-approve_plan',)
TRANSITIONS = {
    'intake→route_select': {'stages': ('intake',), 'nodes': ('controller.intake',)},
    'route_select→plan': {'after': 'intake→route_select', 'nodes': INTAKE_NODES},
    'plan→plan_review': {'after': 'route_select→plan', 'stages': ('plan',), 'deliverables': 'declared'},
    'plan_review→checkin1': {'after': 'plan→plan_review', 'nodes': PLAN_NODES, 'review_steps': (PLAN_REVIEW_STEP,)},
    'checkin1→execute': {'after': 'plan_review→checkin1', 'nodes': ('authority.ci1',), 'rows': ('CHECKIN-1',),
                         'own': APPROVED},
    'prepare_launch': {'after': 'route_select→plan', 'step_clean': True, 'own': ('GATE-launch',)},
    'launch': {'after': 'checkin1→execute', 'rows': APPROVED, 'waypoint_ancestors': True, 'step_clean': True,
               'own': ('GATE-launch',)},
    'checkin2→execute': {'after': 'checkin1→execute', 'rows': APPROVED, 'waypoint': True,
                         'own': ('GATE-checkin2_accept',)},
    'deviation→execute': {'after': 'checkin1→execute', 'rows': APPROVED, 'occurrences': ('deviation',),
                          'nodes': ('controller.deviation', 'authority.deviation'), 'own': ('GATE-deviation',)},
    'escalate→execute': {'after': 'checkin1→execute', 'rows': APPROVED, 'occurrences': ('escalation',),
                         'nodes': ('controller.escalation', 'judgment.ask')},
    'execute→final_review': {'after': 'checkin1→execute', 'steps': True, 'rows': APPROVED},
    'final_review→checkin3': {'after': 'execute→final_review', 'nodes': ('judgment.kill_the_result',),
                              'review_steps': (FINAL_REVIEW_STEP,)},
    'checkin3→deliver': {'after': 'final_review→checkin3', 'nodes': ('authority.ci3', 'authority.final'),
                         'rows': ('CHECKIN-3', 'CHECKIN-final'), 'own': ('GATE-final_task',)},
    'deliver[accepted]': {'after': 'checkin3→deliver', 'stages': ('deliver',), 'everything': True},
    'deliver[qualified]': {'integrity_only': True},
    'deliver[diagnostic]': {'integrity_only': True},
    'bounded_end→deliver': {'integrity_only': True},
}
ENDINGS = ('deliver[qualified]', 'deliver[diagnostic]', 'bounded_end→deliver')

# decision gate (decision_gate.GATES) -> ledger transition and the action field naming its qualifier
DECISION_TRANSITIONS = {
    'approve_plan': ('checkin1→execute', None),
    'launch': ('launch', ('step', 'node_id')),
    'checkin2_accept': ('checkin2→execute', ('waypoint', 'step', 'node_id')),
    'deviation': ('deviation→execute', ('event', 'deviation')),
    'correction': ('checkin1→execute', None),
    'failed_stage_feedback': ('checkin1→execute', None),
    'research_choice': ('checkin1→execute', None),
    'unblind': ('checkin1→execute', None),
    'spend_above_ceiling': ('checkin1→execute', None),
    'delivery': ('deliver[accepted]', None),
    # The final task is decided at CHECK-IN 3, before delivery materialises its own rows: it requires the edge into
    # delivery. An accepted delivery still requires deliver[accepted], which the sink gates (``decide_label``).
    'final_task': ('checkin3→deliver', None),
    'export': ('deliver[accepted]', None),
    'report_integrity': ('deliver[accepted]', None),
}
DELIVERY_GATES = ('GATE-delivery', 'GATE-final_task', 'GATE-export', 'GATE-report_integrity')
TRANSITION = re.compile(r'^(?P<name>[^\[\]]+?)(?:\[(?P<qualifier>[^\[\]]+)\])?$')


def parse(transition: str) -> tuple[str, str | None]:
    if not isinstance(transition, str):
        raise ValueError(f'a ledger transition is a string, not {transition!r}')
    whole = transition.strip().replace('->', '→')  # the ASCII spelling names the same transition
    if whole in TRANSITIONS:
        return whole, None
    match = TRANSITION.match(whole)
    if not match or match.group('name') not in TRANSITIONS:
        raise ValueError(f'unknown ledger transition {transition!r}')
    return match.group('name'), match.group('qualifier')


def requirements(name: str) -> list[dict]:
    chain, current = [], name
    while current:
        spec = TRANSITIONS[current]
        chain.append(spec)
        current = spec.get('after')
    return list(reversed(chain))


def population_equality(expected, actual) -> list[str]:
    """The holes: members of ``expected`` that ``actual`` lacks, counted with multiplicity, in expected order.

    Extras in ``actual`` are not holes; swap the arguments to list them. Every population check of the gates
    (original obligations, seats and scan points) goes through this function.
    """
    for name, values in (('expected', expected), ('actual', actual)):
        if not isinstance(values, (list, tuple)) or not all(isinstance(v, str) for v in values):
            raise TypeError(f'{name} must be a list of strings')
    available = Counter(actual)
    holes = []
    for member in expected:
        if available[member] > 0:
            available[member] -= 1
        else:
            holes.append(member)
    return holes


# ---- instance and step judgements ---------------------------------------------------------------------

def instance_met(instance, row) -> tuple[bool, str | None]:
    evidence = instance.evidence or {}
    status = instance.status
    if status == 'satisfied':
        if row['class'] == 'R' and not evidence.get('credit'):
            return False, 'credit_missing'
        if row['class'] == 'I' and not evidence.get('ack'):
            return False, 'ack_missing'
        return True, None
    if status == 'not_applicable':
        if row['class'] == 'R' and not evidence.get('credit'):
            return False, 'credit_missing'
        return True, None
    if status == 'waived':
        return (True, None) if row['waivability'] == 'authority' else (False, 'waiver_not_allowed')
    if status == 'violated':
        if row['class'] == 'L' and evidence.get('label'):
            return True, None
        return False, 'violated'
    return False, 'pending'


def _row_entry(instance, row, reason: str, note: str = '') -> dict:
    consequence = 'qualified' if row['waivability'] == 'authority' else 'diagnostic'
    message = f'{row["id"]} is {instance.status}' + (f' ({reason})' if reason != instance.status else '')
    return {'entry': instance.key, 'id': row['id'], 'status': instance.status, 'reason': reason,
            'class': row['class'], 'ledger_class': row['ledger_class'], 'node': row['node'],
            'package': row.get('package'), 'waivability': row['waivability'], 'consequence': consequence,
            'message': message + (f': {note}' if note else '')}


def _hole(entry: str, reason: str, message: str, consequence: str = 'qualified') -> dict:
    return {'entry': entry, 'id': None, 'status': 'absent', 'reason': reason, 'class': None, 'ledger_class': None,
            'node': None, 'package': None, 'waivability': None, 'consequence': consequence, 'message': message}


def _check(catalogue: Catalogue, state: State, keys, out: list, *, exclude=(), note='', skip=()) -> None:
    for key in keys:
        instance = state.instances[key]
        if instance.id in exclude or key in skip:
            continue
        row = catalogue.rows[instance.id]
        met, reason = instance_met(instance, row)
        if not met:
            out.append(_row_entry(instance, row, reason, note))


def _step_plan_keys(state: State, step_id: str) -> list[str]:
    return [k for k in state.plan_keys if state.instances[k].scope.get('step') == step_id]


def _units(state: State, step_id: str) -> dict:
    return {(point, seat): latest for (step, point, seat), latest in state.latest_seats().items() if step == step_id}


def _card_ids() -> dict:
    """The role registry's one generated name-to-card mapping (``role_registry.card_ids``)."""
    from ravel.workflow import role_registry
    return role_registry.card_ids()


def _planned_kind(seat: dict) -> str:
    return 'review' if seat.get('kind') == 'review' else 'producer'


def _seat_identity(state: State, step_id: str, point: str, seat: str, attempt, cards: dict) -> tuple:
    """``(kind, card id)`` of a seat attempt: the card its materialisation context recorded (``role``), resolved through
    the mapping; a review or consult seat by the kind it recorded, every other attempt (a worker or a launch) is the
    step's producer."""
    context = state.seat_context.get((step_id, point, seat, attempt)) or {}
    role = context.get('role') or seat
    kind = context.get('seat_kind') if seat != 'producer' and context.get('seat_kind') in ('review', 'consult') \
        else 'producer'
    return kind, cards.get(role, role)


def step_unmet(catalogue: Catalogue, state: State, step_id: str, *, exclude=(), skip=(),
               review_populations=None) -> list[dict]:
    """Why ``step_id`` is not closed (empty when it is). ``skip`` leaves out named instance keys."""
    step = state.step(step_id)
    if step is None:
        return [_hole(f'step:{step_id}', 'step_unknown', f'step {step_id} is not in the current plan')]
    out: list[dict] = []
    _check(catalogue, state, _step_plan_keys(state, step_id), out, exclude=exclude, skip=skip)
    units = _units(state, step_id)
    if not units:
        out.append(_hole(f'step:{step_id}', 'step_not_entered',
                         f'step {step_id} never entered the governed step graph'))
    unit = '\x1f'.join  # identifiers never hold control characters
    # A seat is the card that sat it: a planned seat names a role, a seat attempt records the card it ran (its context
    # ``role``); both resolve through the role registry's one name-to-card mapping, with the seat's kind.
    cards = _card_ids()
    actual = [unit((point, *_seat_identity(state, step_id, point, seat, attempt, cards)))
              for (point, seat), (attempt, _) in units.items()]
    expected, names = [], {}
    for seat in step['seats']:
        identity = (_planned_kind(seat), cards.get(seat['role'], seat['role']))
        declared = (review_populations or {}).get(step_id)
        if seat['kind'] == 'review' and declared is not None:
            for point in declared:
                expected.append(unit((point, *identity)))
                names[expected[-1]] = seat['seat']
            for (point, actual_seat), (attempt, _) in units.items():
                if point not in declared and (actual_seat == seat['seat'] or _seat_identity(
                        state, step_id, point, actual_seat, attempt, cards) == identity):
                    out.append(_hole(f'seat:{step_id}/{point}/{actual_seat}', 'review_point_undeclared',
                                     'the review attempt is outside its pinned point population', 'diagnostic'))
            continue
        if seat['kind'] == 'review' and step['points']:
            # A scan step is reviewed once, or at every point.
            if not population_equality([unit((p, *identity)) for p in step['points']], actual):
                continue
            expected.append(unit(('', *identity)))
            names[expected[-1]] = seat['seat']
            continue
        for point in step['points'] or ['']:
            expected.append(unit((point, *identity)))
            names[expected[-1]] = seat['seat']
    for hole in population_equality(expected, actual):
        point = hole.split('\x1f', 1)[0]
        seat = names[hole]
        where = f'{step_id}/{point}/{seat}' if point else f'{step_id}/{seat}'
        out.append(_hole(f'seat:{where}', 'seat_missing', f'seat {seat} of step {step_id}'
                         + (f' at point {point}' if point else '') + ' has no attempt'))
    for (point, seat), (attempt, keys) in sorted(units.items()):
        _check(catalogue, state, keys, out, exclude=exclude, note=f'latest attempt {attempt}', skip=skip)
    return out


def _violations(catalogue: Catalogue, state: State, step_id: str, *, exclude=()) -> list[dict]:
    """Unlabelled violations among a step's plan instances and its seats' latest attempts."""
    keys = list(_step_plan_keys(state, step_id))
    for (_, _), (_, seat_keys) in sorted(_units(state, step_id).items()):
        keys.extend(seat_keys)
    out = []
    for key in keys:
        instance = state.instances[key]
        row = catalogue.rows[instance.id]
        if instance.status == 'violated' and instance.id not in exclude and not instance_met(instance, row)[0]:
            out.append(_row_entry(instance, row, 'violated', f'step {step_id} cannot launch after a violation'))
    return out


def _ancestors(state: State, step_id: str) -> list[str]:
    seen, stack = [], [step_id]
    while stack:
        step = state.step(stack.pop())
        for parent in (step or {}).get('depends_on') or []:
            if parent not in seen:
                seen.append(parent)
                stack.append(parent)
    return seen


def _waypoint_keys(catalogue: Catalogue, state: State, step_id: str) -> list[str]:
    keys = []
    for key in _step_plan_keys(state, step_id):
        row = catalogue.rows[state.instances[key].id]
        if row['node'].split('[', 1)[0] == 'authority.ci2' or row['id'] in ('CHECKIN-2', 'GATE-checkin2_accept'):
            keys.append(key)
    return keys


def _non_seat_current(state: State) -> list[str]:
    seat_keys = set()
    for attempts in state.seats.values():
        for keys in attempts.values():
            seat_keys.update(keys)
    return [k for k in state.current_keys() if k not in seat_keys]


# ---- the gate ------------------------------------------------------------------------------------------

def integrity(catalogue: Catalogue, state: State) -> list[dict]:
    if state.error:
        return [_hole('ledger', 'chain_broken', f'the ledger cannot be trusted: {state.error}', 'diagnostic')]
    if state.run_id is None:
        return [_hole('stage:intake', 'stage_not_materialised', 'the run has no intake materialisation',
                      'diagnostic')]
    if state.pins.get('catalogue_sha256') != catalogue.sha256:
        return [_hole('catalogue', 'catalogue_changed', 'the installed obligation catalogue differs from the one '
                      'this run pinned at intake', 'diagnostic')]
    return []


def evaluate(catalogue: Catalogue, state: State, transition: str, *, exclude=(),
             review_populations=None) -> list[dict]:
    name, qualifier = parse(transition)
    out = integrity(catalogue, state)
    if out or TRANSITIONS[name].get('integrity_only'):
        return out
    # The GATE row a transition's own decision discharges is required by the later transitions, not by this one.
    exclude = frozenset(exclude) | frozenset(TRANSITIONS[name].get('own', ()))
    non_seat = _non_seat_current(state)
    by_id = {}
    for key in non_seat:
        by_id.setdefault(state.instances[key].id, []).append(key)
    stages = {'intake': state.intake, 'plan': state.plan, 'deliver': state.deliver}
    for spec in requirements(name):
        for stage in spec.get('stages', ()):
            if stages[stage] is None:
                out.append(_hole(f'stage:{stage}', 'stage_not_materialised', f'the {stage} stage was never '
                                 'materialised for this run'))
        nodes = spec.get('nodes', ())
        if nodes:  # run and step instances of these nodes; occurrences are judged by their own transition
            keys = [k for k in non_seat
                    if catalogue.rows[state.instances[k].id]['node'].split('[', 1)[0] in nodes
                    and state.instances[k].scope.get('event') is None]
            _check(catalogue, state, keys, out, exclude=exclude)
        for rid in spec.get('rows', ()):
            keys = [k for k in by_id.get(rid, []) if state.instances[k].scope.get('step') is None]
            _check(catalogue, state, keys, out, exclude=exclude)
        if spec.get('deliverables') == 'declared' and state.plan is not None:
            declared = [d['id'] for d in state.plan.get('deliverables') or []]
            for deliverable in population_equality(list(state.deliverables), declared):
                out.append(_hole(f'deliverable:{deliverable}', 'deliverable_not_declared',
                                 f'original obligation {deliverable} is neither mapped nor kept open by the plan'))
        for step in spec.get('review_steps', ()):
            units = _units(state, step)
            if not units:
                out.append(_hole(f'step:{step}', 'review_missing', f'no {step} review seat was dispatched'))
            for (point, seat), (attempt, keys) in sorted(units.items()):
                _check(catalogue, state, keys, out, exclude=exclude, note=f'latest attempt {attempt}')
        if spec.get('steps'):
            for step in state.plan_steps():
                out.extend(step_unmet(catalogue, state, step['id'], exclude=exclude,
                                      review_populations=review_populations))
        if spec.get('waypoint'):
            # A waypoint is reached when its step's own work is closed; its CHECK-IN 2 rows are then required.
            waypoints = [s['id'] for s in state.plan_steps() if s['waypoint']]
            reached = [w for w in waypoints
                       if not step_unmet(catalogue, state, w, skip=set(_waypoint_keys(catalogue, state, w)),
                                         review_populations=review_populations)]
            targets = [qualifier] if qualifier else reached
            for target in targets:
                if target not in waypoints:
                    out.append(_hole(f'step:{target}', 'waypoint_unknown', f'{target} is not a waypoint of the plan'))
                    continue
                checkin = set(_waypoint_keys(catalogue, state, target))
                out.extend(step_unmet(catalogue, state, target, exclude=exclude, skip=checkin,
                                      review_populations=review_populations))
                _check(catalogue, state, sorted(checkin), out, exclude=exclude)
        if spec.get('step_clean') and qualifier and state.step(qualifier) is not None:
            out.extend(_violations(catalogue, state, qualifier, exclude=exclude))
        if spec.get('waypoint_ancestors') and qualifier:
            if state.step(qualifier) is None:
                out.append(_hole(f'step:{qualifier}', 'step_unknown', f'{qualifier} is not in the current plan'))
            for ancestor in _ancestors(state, qualifier):
                step = state.step(ancestor)
                if step and step['waypoint']:
                    _check(catalogue, state, _waypoint_keys(catalogue, state, ancestor), out, exclude=exclude,
                           note=f'waypoint before {qualifier}')
        for kind in spec.get('occurrences', ()):
            ids = [qualifier] if qualifier else [i for i, o in state.occurrences.items() if o['kind'] == kind]
            for occurrence in ids:
                record = state.occurrences.get(occurrence)
                if record is None or record['kind'] != kind:
                    out.append(_hole(f'event:{occurrence}', 'occurrence_unknown',
                                     f'no {kind} occurrence {occurrence} was materialised'))
                    continue
                _check(catalogue, state, record['keys'], out, exclude=exclude)
        if spec.get('everything'):
            _check(catalogue, state, state.current_keys(), out, exclude=exclude)
            for step in state.plan_steps():
                out.extend(step_unmet(catalogue, state, step['id'], exclude=exclude,
                                      review_populations=review_populations))
            present = sorted({i.scope['deliverable'] for i in state.instances.values() if 'deliverable' in i.scope})
            for deliverable in population_equality(list(state.deliverables), present):
                out.append(_hole(f'deliverable:{deliverable}', 'deliverable_not_materialised',
                                 f'original obligation {deliverable} has no conservation entry'))
            for item in (state.plan or {}).get('open_obligations') or []:
                if item['kind'] != 'deliverable':  # an open deliverable is held by its conservation entry
                    out.append(_hole(f'open:{item["id"]}', 'open_obligation', f'the plan keeps {item["id"]} open'
                                     + (f': {item["reason"]}' if item.get('reason') else '')))
    if name not in ENDINGS:
        for key in non_seat:
            instance = state.instances[key]
            row = catalogue.rows[instance.id]
            if instance.status == 'violated' and not instance.scope and not instance_met(instance, row)[0] \
                    and row['waivability'] != 'authority' and instance.id not in exclude:
                out.append(_row_entry(instance, row, 'run_violation', 'a run-level violation stops forward '
                                      'transitions; only a qualified or diagnostic ending remains'))
    return _dedupe(out)


def _dedupe(rows: list[dict]) -> list[dict]:
    seen, result = set(), []
    for row in rows:
        mark = (row['entry'], row['reason'])
        if mark not in seen:
            seen.add(mark)
            result.append(row)
    return sorted(result, key=lambda r: (r['entry'], r['reason']))


def unmet(store, transition: str, *, exclude=()) -> list[dict]:
    name, _ = parse(transition)  # an unknown transition is a programming error, raised before any store read
    catalogue = catalogue_module.load()
    state = load_state(store, full=True)
    populations, errors = None, []
    if name not in ENDINGS:
        try:
            populations = _scan_review_populations(store, state)
        except (ValueError, KeyError, TypeError, OSError):
            errors.append(_hole('scan:review', 'scan_review_invalid',
                                'the review population differs from its pinned plan declaration', 'diagnostic'))
    out = evaluate(catalogue, state, transition, exclude=exclude, review_populations=populations)
    return _dedupe(out + errors + _hook_unmet(store, catalogue, state, name))


def _scan_review_populations(store, state):
    """Read only a retained, digest-bound declaration; no subset is inferred from attempts.

    The ledger's normalized plan intentionally preserves all point obligations. Read the
    declaration from the full applied plan, authenticate both identities, then narrow only
    the review-seat denominator. Producer and every-point row checks remain unchanged.
    The ledger's plan is the projection of this scientific plan, materialised before or after
    the engagement decision applied its seats; either projection binds the same plan.
    """
    pins = store.scan('plan') if state.plan is not None else []
    if not pins:
        return None
    pin = chain.unwrap(pins[-1])
    if not isinstance(pin, dict) or not (pin.get('applied_plan') or pin.get('applied_blob')):
        return None
    from ravel.controller.engagement.policy import scan_declaration
    from ravel.controller.engagement.records import _plan_document
    from .materialise import plan_context

    scientific = _resolved_plan(store, state)
    applied = _plan_document(store, pin, 'applied_plan', 'applied_blob')
    scope = applied.get('engagement') or {}
    roster = scope.get('seat_plan') or {}
    declaration = roster.get('scan_review')
    expected = scan_declaration(scientific, scope.get('tier'))
    if expected is None and declaration is None:
        return None
    body = deepcopy(applied)
    applied_sha = body.get('engagement', {}).pop('applied_sha256', None)
    if (not applied_sha or chain.digest(body) != applied_sha or pin.get('applied_sha256') != applied_sha
            or applied.get('sha256') != scientific['sha256'] or declaration != expected
            or roster.get('sha256') != chain.digest({k: v for k, v in roster.items() if k != 'sha256'})
            or scope.get('seat_plan_sha256') != roster.get('sha256')
            or state.plan not in (plan_context({'plan': applied}, state), plan_context({'plan': scientific}, state))):
        raise ValueError('the scan review declaration is not the current applied plan')
    # The same declaration may be re-pinned, but it must already exist before work starts.
    declared_at = [entry.get('seq') for entry in pins
                   if chain.unwrap(entry).get('plan_sha256') == scientific['sha256']
                   and chain.unwrap(entry).get('applied_sha256') == applied_sha]
    if not declared_at or any(type(seq) is not int for seq in declared_at):
        raise ValueError('the scan review declaration has no retained order')
    event_plan = None
    for entry in store.scan(chain.KIND):
        event = chain.unwrap(entry).get('body') or {}
        if event.get('stage') == 'plan':
            event_plan = (event.get('context') or {}).get('plan_sha256')
        if (event_plan == scientific['sha256'] and event.get('stage') in ('dispatch', 'review')
                and (event.get('context') or {}).get('step') in declaration['steps']
                and (type(entry.get('seq')) is not int or entry['seq'] <= min(declared_at))):
            raise ValueError('the scan review population was declared after dispatch')
    return {step_id: (population['review_point_ids'] if state.step(step_id)['points']
                      else [''] if population['review_point_ids'] else [])
            for step_id, population in declaration['steps'].items()}


def _resolved_plan(store, state: State):
    """Resolve the current full document without importing any collaborating controller package."""
    if state.plan is None:
        return None
    records = store.scan('plan')
    if not records:
        return state.plan  # stores that materialise the ledger directly have only its projection
    pin = chain.unwrap(records[-1])
    if not isinstance(pin, dict) or pin.get('plan_sha256') != state.plan.get('plan_sha256'):
        raise ValueError('the controller plan pin differs from the current ledger plan')
    plan = pin.get('plan')
    if plan is None:
        blob = pin.get('blob')
        if isinstance(blob, str) and re.fullmatch(r'[0-9a-f]{64}', blob):
            path, digest = 'blobs/' + blob, blob
        elif isinstance(blob, dict):
            path, digest = blob.get('path'), blob.get('sha256')
        else:
            raise ValueError('the controller plan has no document or blob')
        if not isinstance(path, str) or path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/')):
            raise ValueError('the controller plan blob path is invalid')
        raw = store.path(*path.split('/')).read_bytes()
        if sha256(raw).hexdigest() != digest:
            raise ValueError('the controller plan blob digest differs from its pin')
        plan = json.loads(raw)
    if not isinstance(plan, dict) or plan.get('sha256') != pin['plan_sha256'] or \
            chain.digest({k: v for k, v in plan.items() if k != 'sha256'}) != plan['sha256']:
        raise ValueError('the controller plan document differs from its pinned digest')
    return plan


def _hook_rows(provider_id: str, rows) -> list[dict]:
    if not isinstance(rows, list):
        raise ValueError('a gate hook returns a list of unmet rows')
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get('reason'), str) or not row['reason'].strip():
            raise ValueError('a gate hook unmet row needs a nonempty reason')
        chain.json_safe(row)
        identifier = row.get('id', row.get('row'))
        if identifier is not None and not isinstance(identifier, str):
            raise ValueError('a gate hook row id must be a string')
        if row.get('message') is not None and not isinstance(row['message'], str):
            raise ValueError('a gate hook message must be a string')
        entry = row.get('entry', f'hook:{provider_id}:{identifier or index}')
        if not isinstance(entry, str) or not entry or row.get('consequence', 'diagnostic') not in \
                ('qualified', 'diagnostic'):
            raise ValueError('a gate hook unmet row has an invalid entry or consequence')
        item = _hole(entry, row['reason'], row.get('message') or row['reason'], 'diagnostic')
        item.update(deepcopy(row))
        item['id'] = identifier
        result.append(item)
    return result


def _hook_unmet(store, catalogue: Catalogue, state: State, name: str) -> list[dict]:
    cache = _HOOK_CACHE.get()
    key = (str(store.path('ledger')), catalogue.sha256, state.head, name,
           tuple((provider_id, id(fn)) for provider_id, fn in _GATE_HOOKS.items()))
    if cache is not None and key in cache:
        return deepcopy(cache[key])
    out = _run_hooks(store, catalogue, state, name)
    if cache is not None:
        cache[key] = deepcopy(out)
    return out


def registered_unmet(store, transition: str) -> list[dict]:
    """The callback share of a decision, even when another decision provider refused before its ledger check."""
    name, _ = parse(transition)
    return _hook_unmet(store, catalogue_module.load(), load_state(store, full=True), name)


def _run_hooks(store, catalogue: Catalogue, state: State, name: str) -> list[dict]:
    hooks = tuple(_GATE_HOOKS.items())
    if not hooks:
        if any(row.get('package') == 'P18' for row in catalogue.rows.values()):
            return [_hole('provider:engagement', 'engagement_provider_missing',
                          'the installed catalogue requires an engagement gate provider', 'diagnostic')]
        return []
    out = []
    try:
        plan = _resolved_plan(store, state)
    except Exception:
        plan = None
        out.append(_hole('hook:plan', 'gate_hook_plan_unavailable',
                         'the current plan could not be resolved for gate providers', 'diagnostic'))
    for provider_id, fn in hooks:
        try:
            rows = fn(store, name, plan=deepcopy(plan))
        except Exception:
            out.append(_hole(f'hook:{provider_id}', 'gate_hook_failed',
                             f'gate provider {provider_id} could not verify the transition', 'diagnostic'))
            continue
        try:
            out.extend(_hook_rows(provider_id, rows))
        except Exception:
            out.append(_hole(f'hook:{provider_id}', 'gate_hook_invalid',
                             f'gate provider {provider_id} returned invalid unmet rows', 'diagnostic'))
    return out


def decision_transition(gate: str, action: dict) -> tuple[str, frozenset]:
    """The ledger transition a decision gate requires, and the GATE rows the decision itself discharges."""
    if gate not in DECISION_TRANSITIONS:
        raise ValueError(f'unknown decision gate {gate!r}')
    name, fields = DECISION_TRANSITIONS[gate]
    qualifier = None
    for field in fields or ():
        value = action.get(field) if isinstance(action, dict) else None
        if isinstance(value, str) and value:
            qualifier = value
            break
    own = frozenset(DELIVERY_GATES) if name == 'deliver[accepted]' else frozenset({f'GATE-{gate}'})
    return (f'{name}[{qualifier}]' if qualifier else name), own



def transition_for(store, gate: str, action: dict) -> tuple[str, frozenset]:
    """Select bounded preparation only from its protected current source/authority/binding."""
    ordinary = decision_transition(gate, action)
    if gate != 'launch':
        return ordinary
    try:
        from ravel.controller import ledger
        from ravel.controller.step import binding, launch_gate
        from ravel.workflow import rdj_loop
        directory = store.run_dir
        if directory is None:
            return ordinary
        actual, plan, step, proof = launch_gate.load(directory, action)
        if (actual.run_id != store.run_id or actual.path().resolve() != store.path().resolve()
                or store.check_binding(directory) or store.verify()):
            return ordinary
        if launch_gate.preparation_implementation(step) is None:
            return ordinary
        launch_gate._preparation_authority(actual, plan, step, proof, action['view_pins']['native_preflight'])
        if rdj_loop.compute_class(directory, gate, action)[0] not in ('R0', 'R1'):
            return ordinary
        bound = [row for node in binding.PLAN_BIND_NODES
                 for row in ledger.current(store, node=node, step=step['id'])]
        if (not bound or any((row.get('evidence') or {}).get('sha256') != plan['sha256'] for row in bound)
                or binding.unverified(ledger, store, step)):
            return ordinary
        return f"prepare_launch[{step['id']}]", ordinary[1]
    except Exception:
        # An unproved candidate keeps the full ordinary CI1 transition. Native
        # providers independently refuse its malformed or stale protected identity.
        return ordinary
