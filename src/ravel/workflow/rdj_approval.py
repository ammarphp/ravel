"""The rdj requirement of a controller run's plan approval, discharged by the run's independent review evidence.

In a run the controller owns, the decision-justification requirement of ``approve_plan`` (class R2) is
satisfied only when both of these hold:

1. The CHECK-IN 1 review covers the exact plan digest being approved. The approval action carries its
   check-in view pins (``view_pins``), whose canonical digest is the action digest; their ``plan_sha256``
   names the plan. For every CHECK-IN 1 seat the plan names (the controller's default seats otherwise), the
   latest controller credit of that seat's review of this plan (``step-credit`` of step ``plan_review``) is
   credited and its verdict is ``accept`` (approve, not ``revise``). It was credited from an observed blind
   seat session: the independence decision, taken again now from the controller store alone, credits the
   same observed fresh reviewer session, and the packet that session reviewed is the authenticated RAVEL
   projection of a blind card (profile ``blind`` or ``spec-denied``, or a card that requires blindness).
2. Every decide or effectful step of class R2 or R3 in that plan has a credited RDJ case. The controller
   dispatches an RDJ case as a seat: a governed review, by a card of the RDJ family, of the step's exact
   spec digest (``parameters.judgment.spec_sha256``, else the step's canonical digest). The case counts only
   when the latest controller credit of such a review is credited, approves, and came from an observed
   blind seat session (the same test as the CHECK-IN 1 review). Role names resolve to card ids through
   the role registry's one name-to-card mapping; a review of the spec by any other role does not count.

``evaluate`` returns every missing item (each one is a refusal) and, when nothing is missing, the evidence
that discharged the requirement: which review credits, sessions and projections, and which RDJ cases. The
ledger records that evidence with the decision.

The seat test is ``seat_review``; review points use it for every seat of a controller run (``controller_plan``
names the plan the seats must have reviewed), with the projection profile its card declares in place of a blind
one: a review point's voting seat may be a card that sees the full result.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

MECHANISM = 'rdj_approval.mapping'
BLIND_PROFILES = ('blind', 'spec-denied')
CONSEQUENTIAL = ('R2', 'R3')
FIX = ('Credit the CHECK-IN 1 review of this exact plan, and the RDJ case seat (an RDJ-family review of the exact '
       'spec) of every R2/R3 decide or effectful step, each from an observed blind seat session with an approving '
       'verdict.')
_SHA = re.compile(r'[0-9a-f]{64}')


def applies(rundir) -> bool:
    """Whether ``rundir`` is a run the controller owns; an ownership question that cannot be answered applies."""
    try:
        from ravel.controller.store import controller_owned
    except ModuleNotFoundError as exc:
        return exc.name not in ('ravel.controller', 'ravel.controller.store')
    try:
        return controller_owned(Path(rundir)) is not None
    except Exception:
        return True


def _canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def approved_plan(action) -> str:
    """The plan digest the approval action binds; ``ValueError`` when the action binds none."""
    pins = action.get('view_pins') if type(action) is dict else None
    if type(pins) is not dict or any(type(k) is not str or type(v) is not str for k, v in pins.items()):
        raise ValueError('the approval action carries no check-in view pins')
    if _canonical(pins) != action.get('digest'):
        raise ValueError("the approval action's view pins are not the pins its digest commits to")
    plan = pins.get('plan_sha256')
    if type(plan) is not str or not _SHA.fullmatch(plan):
        raise ValueError('the approval view pins no plan digest')
    return plan


def _plan(store, plan_sha):
    from ravel.controller.routes import plan_sha256
    for row in reversed(store.scan('plan')):
        record = row.get('record') or {}
        if record.get('plan_sha256') != plan_sha or not record.get('blob'):
            continue
        plan = json.loads(store.get_blob(record['blob']))
        if type(plan) is dict and plan.get('sha256') == plan_sha and plan_sha256(plan) == plan_sha:
            return plan
    return None


def _seats(plan):
    from ravel.controller.graph import CI1_SEATS
    named = next((c.get('seats') for c in plan.get('checkins') or () if type(c) is dict and c.get('id') == 'checkin1'
                  and c.get('seats')), None)
    return list(named or CI1_SEATS)


def _blind(manifest, role):
    """Whether the authenticated projection a review read is a blind projection of its role's card."""
    from . import broker, role_registry
    if manifest.get('profile') in BLIND_PROFILES:
        return True
    card = role_registry.load(role)
    return broker.digest(card) == manifest.get('card_sha256') and (card.get('requires') or {}).get('blind') is True


def _declared(manifest, role):
    """Whether the authenticated projection a review read is the profile its role's current card declares."""
    from . import broker, role_registry
    card = role_registry.load(role)
    return broker.digest(card) == manifest.get('card_sha256') and manifest.get('profile') == card['sees']['profile']


def _observed(store, credit, role, *, blind=True):
    """``(evidence, None)`` when the credited review came from an observed seat session, else ``(None, reason)``.

    The session read the authenticated RAVEL projection of its card: a blind one (``blind``), or the profile the card
    itself declares."""
    from . import review_dispatch, review_independence, role_registry
    own = credit['own']
    query = deepcopy(own.get('query') or {})
    stored = own.get('decision') or {}
    decided = review_independence.decide(deepcopy(query))
    if decided.get('independent') is not True:
        return None, 'the independence decision taken now does not credit it (' + str(decided.get('advisory')) + ')'
    if decided.get('evidence_boundary') != review_independence.CONTROLLER_STORE:
        return None, 'its evidence does not lie in the controller store'
    context = decided.get('context_id')
    if context != stored.get('context_id'):
        return None, 'the credited session differs from the session credited at review time'
    sessions = [r for r in _records(store, review_dispatch.SESSION_KIND) if r.get('session_id') == context
                and role_registry.same_card(r.get('role'), role) and r.get('role_kind') == 'reviewer']
    if len(sessions) != 1 or sessions[0].get('fresh') is not True \
            or sessions[0].get('transport_kind') in review_dispatch.SEATLESS_TRANSPORTS:
        return None, 'no single observed fresh reviewer session of this seat'
    outputs = [r for r in _records(store, review_dispatch.REVIEW_KIND) if r.get('binding') == query]
    if len(outputs) != 1:
        return None, 'no single observed review output bound to this review'
    packet = outputs[0].get('packet') or {}
    manifest = review_dispatch.observed_projection(query)
    if (manifest is None or review_dispatch.builder(manifest) != review_dispatch.PROJECTION
            or packet.get('builder') != review_dispatch.PROJECTION or packet.get('projection_verified') is not True
            or manifest.get('sha256') != packet.get('sha256') or not role_registry.same_card(manifest.get('role'), role)):
        return None, 'the packet it reviewed is not an authenticated RAVEL projection for this seat'
    if blind and not _blind(manifest, role):
        return None, f"its projection profile {manifest.get('profile')!r} is not blind"
    if not blind and not _declared(manifest, role):
        return None, f"its projection profile {manifest.get('profile')!r} is not the one its card declares"
    return {'role': role, 'credit': credit['_record_id'], 'session': context, 'session_record': sessions[0]['_record_id'],
            'review_output': outputs[0]['_record_id'], 'projection_sha256': manifest['sha256'],
            'profile': manifest['profile'], 'verdict': own.get('verdict')}, None


def _records(store, kind):
    from ravel.controller.step.services import records
    return records(store, kind)


def _reviews(store, plan, plan_sha):
    """``(evidence rows, missing items)`` of the CHECK-IN 1 review of ``plan``."""
    from ravel.controller.graph import REVIEW_SEATS
    found, missing = [], []
    for role in _seats(plan):
        evidence, reason = seat_review(store, REVIEW_SEATS['plan'][0], role, plan_sha, label='CHECK-IN 1 review')
        (missing.append(reason) if reason is not None else found.append(evidence))
    return found, missing


def seat_review(store, step_id, role, plan_sha, *, label, blind=True):
    """``(evidence, None)`` for the review of ``plan_sha`` by ``role`` at the controller's seat step ``step_id``, else
    ``(None, reason)``. The latest such controller credit counts: credited (the credit, its own decision and the
    independence decision), approving, and from an observed seat session that read its card's authenticated
    projection (a blind one when ``blind``). Role names resolve through the role registry's one mapping."""
    from . import role_registry
    credits = [r for r in _records(store, 'step-credit') if r.get('step_id') == step_id and type(r.get('own')) is dict
               and role_registry.same_card((r['own'].get('query') or {}).get('role'), role)]
    covering = [r for r in credits if (r['own'].get('query') or {}).get('subject_sha256') == plan_sha]
    short = plan_sha[:12]
    if not covering:
        others = sorted({str((r['own'].get('query') or {}).get('subject_sha256'))[:12] for r in credits})
        return None, (f"the {label} by {role} covers plan {', '.join(others)}, not the approved plan {short}"
                      if others else f'no {label} by {role} of plan {short}')
    credit = covering[-1]
    own = credit['own']
    if not (credit.get('credited') is True and own.get('credited') is True
            and (own.get('decision') or {}).get('independent') is True):
        return None, f"the {label} by {role} of plan {short} is uncredited ({(own.get('decision') or {}).get('advisory')})"
    if own.get('verdict') != 'accept':
        return None, f"the {label} by {role} of plan {short} has verdict {own.get('verdict')!r}, not approve"
    evidence, reason = _observed(store, credit, role, blind=blind)
    if reason is not None:
        return None, (f"the {label} by {role} of plan {short} was not credited from an observed "
                      f"{'blind ' if blind else ''}seat session: {reason}")
    return evidence, None


def controller_plan(rundir):
    """``(store, plan)`` of a controller run: its current plan, the latest one the controller installed (a ``plan``
    record with a revision number; a planning seat's candidate has none), verified against its digest. Raises when
    there is none: a controller run decides and delivers what its installed plan binds."""
    from ravel.controller.store import RunStore, controller_owned
    store = RunStore(controller_owned(Path(rundir)))
    installed = [r['record'] for r in store.scan('plan') if type((r.get('record') or {}).get('revision')) is int]
    if not installed or type(installed[-1].get('plan_sha256')) is not str:
        raise ValueError('the controller store binds no installed plan')
    plan = _plan(store, installed[-1]['plan_sha256'])
    if plan is None:
        raise ValueError(f"plan {installed[-1]['plan_sha256'][:12]} does not verify against its stored bytes")
    return store, plan


def _class(step):
    value = step.get('consequence_class')
    return None if value is None else value if value in ('R0', 'R1', 'R2', 'R3') else 'R3'


def subject(step) -> str:
    """The exact spec digest an RDJ case on ``step`` decides."""
    from ravel.controller.step.services import digest
    spec = ((step.get('parameters') or {}).get('judgment') or {}).get('spec_sha256')
    return spec if type(spec) is str and _SHA.fullmatch(spec) else digest(step)


def _rdj_card(role):
    """Whether ``role`` resolves, through the one name-to-card mapping, to a card of the RDJ family."""
    from . import role_registry
    found = role_registry.card_id(role)
    return found is not None and role_registry.load(found).get('family') == 'rdj'


def _case(store, digest):
    """``(evidence, None)`` for the credited RDJ case on ``digest``, else ``(None, reason)``: the latest
    controller credit of an RDJ-family review of that exact digest, credited from an observed blind seat
    session with an approving verdict."""
    credits = [r for r in _records(store, 'step-credit') if type(r.get('own')) is dict
               and (r['own'].get('query') or {}).get('subject_sha256') == digest]
    if not credits:
        return None, 'no RDJ case decided it'
    cases = [r for r in credits if _rdj_card((r['own'].get('query') or {}).get('role'))]
    if not cases:
        roles = sorted({str((r['own'].get('query') or {}).get('role')) for r in credits})
        return None, f"its spec was reviewed only by {', '.join(roles)}, not by an RDJ role"
    credit = cases[-1]
    own = credit['own']
    if not (credit.get('credited') is True and own.get('credited') is True
            and (own.get('decision') or {}).get('independent') is True):
        return None, f"its RDJ case is uncredited ({(own.get('decision') or {}).get('advisory')})"
    if own.get('verdict') != 'accept':
        return None, f"its RDJ case has verdict {own.get('verdict')!r}, not approve"
    evidence, reason = _observed(store, credit, own['query']['role'])
    if reason is not None:
        return None, f'its RDJ case was not credited from an observed blind seat session: {reason}'
    return {**evidence, 'step_id': credit.get('step_id')}, None


def case(store, digest):
    """The credited RDJ case on ``digest`` as the mapping credits it: ``(evidence, None)`` or ``(None, reason)``."""
    return _case(store, digest)


def _cases(store, plan):
    """``(evidence rows, missing items)`` of the RDJ cases the plan's R2/R3 decide and effectful steps need."""
    from ravel.controller.judgment.planning import EFFECTFUL
    found, missing = [], []
    for step in plan.get('steps') or ():
        cls = _class(step)
        if step.get('kind') not in EFFECTFUL + ('decide',) or cls not in CONSEQUENTIAL:
            continue
        digest = subject(step)
        evidence, reason = _case(store, digest)
        if reason is not None:
            missing.append(f"step {step.get('id')} (class {cls}) has no credited RDJ case on its spec {digest[:12]}: "
                           f'{reason}')
            continue
        found.append({'step': step.get('id'), 'class': cls, 'subject_sha256': digest, **evidence})
    return found, missing


def evaluate(rundir, action):
    """``(missing items, evidence)`` of a controller run's plan approval; evidence is None while anything is
    missing. Read only."""
    rundir = Path(rundir)
    try:
        plan_sha = approved_plan(action)
    except ValueError as exc:
        return [str(exc)], None
    try:
        from ravel.controller.store import RunStore, controller_owned
        store = RunStore(controller_owned(rundir))
        plan = _plan(store, plan_sha)
    except Exception as exc:  # an unreadable controller store never yields a pass
        return [f'the controller store is unreadable: {type(exc).__name__}: {exc}'[:300]], None
    if plan is None:
        return [f'plan {plan_sha[:12]} is not in the run store'], None
    try:
        reviews, missing = _reviews(store, plan, plan_sha)
        cases, more = _cases(store, plan)
    except (OSError, ValueError, KeyError, TypeError) as exc:  # unreadable evidence never yields a pass
        return [f'the review evidence is unreadable: {type(exc).__name__}: {exc}'[:300]], None
    missing += more
    if missing:
        return missing, None
    return [], {'schema_version': 1, 'mechanism': MECHANISM, 'plan_sha256': plan_sha,
                'action_digest': action.get('digest'), 'reviews': reviews, 'rdj_cases': cases}
