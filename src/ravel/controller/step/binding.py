"""Plan-bind rows: each plan step's ownership and seat derivation, checked when the plan is bound.

The rows of nodes ``step.plan_bind`` and ``step.seat_derivation`` (CF07, CF08, I05, R13, V01,
XF06 and each role's ``ownership`` and ``reviewed_by`` rows) are plan-stage rows the CHECK-IN 1
transition requires. The controller records them at the moment it binds a plan
(``record_plan_rows``); the governed step verifies them before it dispatches the step
(``unverified``) and never writes them.

Each row is recorded from the check that enforces it, run on the bound plan under the run's
pinned role registry: the role's card owns every quantity the step's outputs set; a compute step
names a registered production role; the step's review seats are derived by the controller from
the plan's review list and the card's ``reviewed_by``, each resolved, distinct and never the
producer; and the evaluated-author spawn row sets no model-family requirement. Evidence is the plan
digest, the bound contract digest, the step's digest and a ``step-plan-bind`` record of the check's
inputs and result. A row whose condition is absent (a step that names no role, a card with no
``reviewed_by``) is recorded not applicable with a typed reason; a failed check is a violation.
"""
from __future__ import annotations

from contextlib import nullcontext
from importlib.resources import files
import json

from .services import StepHold, digest, records

PLAN_BIND_NODES = ('step.plan_bind', 'step.seat_derivation')
FACT = 'step-plan-bind'
MECHANISM = 'controller.plan_bind'
COMPUTE_KINDS = ('author', 'derive', 'compare', 'review', 'synthesize', 'decide', 'acquire', 'operate')
FAMILY_LABEL = 'separate sessions; same-family candidates permitted (no cross-family requirement)'


def _base(row_id: str) -> str:
    """The row family of a role row (``ROLE-<role>-ownership`` -> ``ownership``), else the row id."""
    if not row_id.startswith('ROLE-'):
        return row_id
    for name in ('ownership', 'reviewed_by'):
        if f'-{name}' in row_id:
            return name
    return row_id


def _reviewed_by_index(row_id: str):
    tail = row_id.rsplit('-reviewed_by-', 1)
    return int(tail[1]) if len(tail) == 2 and tail[1].isdigit() else None


def _k4_families():
    """``(min_model_families, spawn_rows.json sha256)`` of the evaluated-author spawn row K4."""
    from hashlib import sha256
    raw = files('ravel').joinpath('data', 'knowledge', 'spawn_rows.json').read_bytes()
    row = next((r for r in json.loads(raw).get('rows') or () if r.get('row') == 'K4'), None)
    return (row or {}).get('min_model_families'), sha256(raw).hexdigest()


def _derivation(step, card):
    """The review seats the controller derives for ``step`` and every required role that does not resolve."""
    from ravel.workflow import role_registry
    from .graph import MAX_SEATS
    document = role_registry.registry_document()
    producer = (card or {}).get('id')
    declared = list(step.get('review') or [])
    required = declared + list((card or {}).get('reviewed_by') or [])
    seats, unresolved, collapsed = [], [], []
    for role in required:
        canonical = document['aliases'].get(role, role)
        if canonical not in document['roles']:
            unresolved.append(role)
        elif canonical == producer:
            if role in declared:
                collapsed.append(role)
        elif canonical not in seats:
            seats.append(canonical)
    repeated = sorted({r for r in declared if declared.count(r) > 1})
    return {'producer': producer, 'declared': declared, 'reviewed_by': list((card or {}).get('reviewed_by') or []),
            'seats': seats, 'unresolved': unresolved, 'collapsed': collapsed, 'repeated': repeated,
            'over_limit': len(seats) > MAX_SEATS}


def _checks(step, card, card_error, derivation):
    """``{row family: (status, reason or None)}`` for one step."""
    from . import cards
    kind = step.get('kind')
    role = step.get('role')
    result = {}
    # CF07 / ownership: the card owns every quantity the step's outputs set (inputs are judged at dispatch).
    if not role:
        result['ownership'] = ('not_applicable', 'not_applicable:step_names_no_role')
    elif card_error:
        result['ownership'] = ('violated', f'role_unresolved:{card_error}')
    else:
        errors = cards.ownership_errors(card, step)
        result['ownership'] = ('violated', 'ownership:' + errors[0]['code'] + ':' + str(errors[0].get('quantity'))) \
            if errors else ('satisfied', None)
    # R13: a compute step names a registered production role before plan approval.
    if kind not in COMPUTE_KINDS:
        result['R13'] = ('not_applicable', f'not_applicable:{kind}_step_runs_no_worker_of_its_own')
    elif not role:
        result['R13'] = ('violated', 'compute_step_names_no_role')
    elif card_error:
        result['R13'] = ('violated', f'role_unresolved:{card_error}')
    else:
        result['R13'] = ('satisfied', None)
    # I05: the producer and the derived review seats are distinct roles; a plan never makes the producer its own
    # reviewer and never repeats a seat.
    roles = ([role] if role else []) + derivation['seats']
    if derivation['collapsed'] or derivation['repeated']:
        result['I05'] = ('violated', 'roles_collapsed:' + ','.join(derivation['collapsed'] + derivation['repeated']))
    elif len(roles) < 2:
        result['I05'] = ('not_applicable', 'not_applicable:fewer_than_two_required_roles')
    else:
        result['I05'] = ('satisfied', None)
    over = ('violated', 'review_seats_exceed_limit') if derivation['over_limit'] else None
    # V01: every required review seat (plan review list and card reviewed_by) is derived by the controller.
    if not (derivation['declared'] or derivation['reviewed_by']):
        result['V01'] = ('not_applicable', 'not_applicable:no_required_review_seats')
    elif derivation['unresolved']:
        result['V01'] = ('violated', 'required_review_seat_unresolved:' + ','.join(derivation['unresolved']))
    else:
        result['V01'] = over or ('satisfied', None)
    # CF08: the card's reviewed_by triggers reviewer seats.
    if not role:
        result['CF08'] = ('not_applicable', 'not_applicable:step_names_no_role')
    elif card_error:
        result['CF08'] = ('violated', f'role_unresolved:{card_error}')
    elif not derivation['reviewed_by']:
        result['CF08'] = ('not_applicable', 'not_applicable:card_declares_no_reviewed_by')
    elif any(r in derivation['unresolved'] for r in derivation['reviewed_by']):
        result['CF08'] = ('violated', 'reviewed_by_role_unresolved')
    else:
        result['CF08'] = over or ('satisfied', None)
    return result


def _evaluate_row(row_id, checks, step, card, derivation, k4):
    family = _base(row_id)
    if family == 'XF06':
        families, sha = k4
        if families == 1:
            return 'satisfied', None, {'spawn_rows_sha256': sha, 'min_model_families': families, 'label': FAMILY_LABEL}
        return 'violated', f'k4_requires_{families}_model_families', {
            'spawn_rows_sha256': sha, 'min_model_families': families,
            'label': f'K4 requires {families} model families'}
    if family == 'reviewed_by':
        index = _reviewed_by_index(row_id)
        wanted = derivation['reviewed_by'][index] if index is not None and index < len(derivation['reviewed_by']) else None
        if wanted is None:
            return 'violated', 'reviewed_by_entry_absent', {}
        from ravel.workflow import role_registry
        canonical = role_registry.registry_document()['aliases'].get(wanted, wanted)
        if canonical in derivation['seats']:
            return ('violated', 'review_seats_exceed_limit', {}) if derivation['over_limit'] else (
                'satisfied', None, {'seat': canonical})
        return 'violated', f'reviewed_by_seat_not_derived:{wanted}', {}
    if family in ('ownership', 'CF07'):
        status, reason = checks['ownership']
        return status, reason, {}
    if family in checks:
        status, reason = checks[family]
        return status, reason, {}
    return None, None, {}  # no check here: the row stays pending and the transitions that need it hold


def record_plan_rows(store, plan, *, contract_sha256, ledger, registry_sha256=None) -> dict:
    """Bind the checked population within one verified, locked journal scope."""
    snapshot = getattr(store, 'snapshot', None)
    with snapshot() if callable(snapshot) else nullcontext():
        return _record_plan_rows(store, plan, contract_sha256=contract_sha256, ledger=ledger,
                                 registry_sha256=registry_sha256)


def _record_plan_rows(store, plan, *, contract_sha256, ledger, registry_sha256=None) -> dict:
    """Record every checked plan-bind row through the ledger's atomic batch; returns counts.

    ``ledger`` offers ``current`` and ``record`` (the obligation ledger). A row recorded for the same
    step bytes is left as recorded; a row recorded for other bytes of the same step id is recorded
    again (a later status the ledger refuses stays as it was and is listed under ``refused``).
    """
    current, record = getattr(ledger, 'current', None), getattr(ledger, 'record', None)
    if not callable(current) or not callable(record):
        return {'recorded': 0, 'skipped': 'the ledger offers no current/record interface'}
    plan_sha = plan.get('sha256')
    pin = registry_sha256
    k4 = None
    counts = {'recorded': 0, 'kept': 0, 'refused': []}
    for step in plan.get('steps') or ():
        if type(step) is not dict or type(step.get('id')) is not str:
            continue
        step_sha = digest(step)
        rows = [r for node in PLAN_BIND_NODES for r in current(store, node=node, step=step['id'])]
        due = [r for r in rows if r['status'] == 'pending' or (r.get('evidence') or {}).get('step_sha256') != step_sha]
        counts['kept'] += len(rows) - len(due)
        if not due:
            continue
        if pin is None:
            from .graph import registry_pin
            pin = registry_pin(store, {})
        card, card_sha, card_error = None, None, None
        if step.get('role'):
            from . import cards
            try:
                card, card_sha, _ = cards.resolve(step['role'], {'registry_sha256': pin})
            except StepHold as exc:
                card_error = exc.reason
        derivation = _derivation(step, card)
        checks = _checks(step, card, card_error, derivation)
        if k4 is None and any(_base(r['id']) == 'XF06' for r in due):
            k4 = _k4_families()
        fact = store.append(FACT, {'schema_version': 1, 'plan_sha256': plan_sha, 'contract_sha256': contract_sha256,
                                   'registry_sha256': pin, 'step_id': step['id'], 'step_sha256': step_sha,
                                   'role': step.get('role'), 'card_sha256': card_sha, 'card_error': card_error,
                                   'derivation': derivation,
                                   'checks': {k: {'status': s, 'reason': r} for k, (s, r) in checks.items()}})
        changes = []
        for row in due:
            status, reason, extra = _evaluate_row(row['id'], checks, step, card, derivation, k4)
            if status is None:
                counts.setdefault('unchecked', []).append(row['entry'])
                continue
            evidence = {'sha256': plan_sha, 'contract_sha256': contract_sha256, 'step_sha256': step_sha,
                        'record': fact, 'mechanism': MECHANISM, **extra}
            if reason:
                evidence['reason'] = reason
            changes.append((row['entry'], status, evidence))
        batch = getattr(ledger, 'record_many', None)
        if changes and callable(batch):
            try:
                batch(store, changes)
                counts['recorded'] += len(changes)
                continue
            except Exception:  # atomic refusal writes nothing; retain each row's existing refusal account
                pass
        for entry, status, evidence in changes:
            try:
                record(store, entry, status, evidence)
                counts['recorded'] += 1
            except Exception as exc:  # the ledger refused the change; the earlier record stays and is listed
                counts['refused'].append({'entry': entry, 'status': status,
                                          'reason': f'{type(exc).__name__}: {exc}'[:300]})
    if counts['refused']:
        store.append(FACT + '-refused', {'plan_sha256': plan_sha, 'refused': counts['refused']})
    return counts


def _reevaluated(store, step, row_id):
    """``(status, reason)`` of one plan-bind row's check on ``step``'s current bytes (read-only)."""
    from .graph import registry_pin
    card, card_error = None, None
    if step.get('role'):
        from . import cards
        try:
            card, _, _ = cards.resolve(step['role'], {'registry_sha256': registry_pin(store, {})})
        except StepHold as exc:
            card_error = exc.reason
    derivation = _derivation(step, card)
    k4 = _k4_families() if _base(row_id) == 'XF06' else None
    status, reason, _ = _evaluate_row(row_id, _checks(step, card, card_error, derivation), step, card, derivation, k4)
    return status, reason


def unverified(ledger, store, step) -> list[dict]:
    """The plan-bind rows of ``step`` that do not show a met discharge for its current bytes (empty when verified).

    The ledger keeps ``not_applicable`` final, so a row recorded not applicable for earlier bytes of the step (a
    route re-bound it) cannot be recorded again: its check is re-evaluated on the current bytes, and only the same
    not-applicable outcome, for the same reason, verifies it.
    """
    current = getattr(ledger, 'current', None)
    if not callable(current):
        return []  # an interface fake without the ledger's read access; the installed ledger always has it
    step_sha = digest(step)
    problems = []
    for node in PLAN_BIND_NODES:
        for row in current(store, node=node, step=step['id']):
            evidence = row.get('evidence') or {}
            if row['status'] == 'pending':
                problems.append({'entry': row['entry'], 'problem': 'unrecorded'})
            elif row['status'] == 'violated' and not evidence.get('label'):
                problems.append({'entry': row['entry'], 'problem': 'violated', 'reason': evidence.get('reason')})
            elif evidence.get('step_sha256') != step_sha and not (
                    row['status'] == 'not_applicable'
                    and _reevaluated(store, step, row['id']) == ('not_applicable', evidence.get('reason'))):
                problems.append({'entry': row['entry'], 'problem': 'recorded_for_other_step_bytes'})
    return problems


def fact(store, record_id):
    """The ``step-plan-bind`` record a row's evidence names (for readers and tests)."""
    for row in records(store, FACT):
        if row.get('_record_id') == record_id:
            return row
    return None
