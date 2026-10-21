"""Typed absence evidence at delivery, from a complete controller journal.

Composition registers the existing journal producers before intake. This module
reads their records; it never infers recorder coverage from a missing event.
A missing/late/changed registration, incomplete journal or one matching occurrence
leaves the row pending. Executed mechanisms keep their ordinary recorders.
"""
from __future__ import annotations

from copy import deepcopy
import json

from . import common

COMPOSITION = 'authority-composition'
COMPOSITION_SCHEMA = 'authority-composition.v1'
DECISION = 'delivery-decision'
DECISION_SCHEMA = 'delivery-decision.v1'

# Each event kind is a projection of producers that already append to RunStore.
# Host configuration changes have no whole-run recorder here: no registration is
# invented for them. Conserved deliverables likewise cannot be closed by absence.
ROW_EVENTS = {
    **dict.fromkeys(('A09', 'C20', 'C21', 'C31', 'C32'), 'deviation'),
    **dict.fromkeys(('A10', 'B05', 'C40', 'G06', 'SW05'), 'control'),
    **dict.fromkeys(('A11', 'G11'), 'restricted_r3'),
    **dict.fromkeys(('C37', 'C38', 'C39', 'SW03'), 'steering'),
    'CT07': 'terminal', 'SW04': 'operator_answer',
    'C23': 'checkin', 'G02': 'gate', 'C25': 'run_binding',
    'C26': 'analysis_route', 'C34': 'research_route', 'ROUTE-research': 'research_route',
    'C36': 'final_checkin', 'JR04': 'governed_step', 'JR05': 'judgment',
    'JR07': 'replan', 'JR08': 'ask',
}

# Registration pins the actual producers and the projection definition. A new
# process with different event semantics must not reuse an earlier registration.
PRODUCERS = {
    **dict.fromkeys(('deviation', 'restricted_r3', 'steering', 'checkin', 'final_checkin'),
                    ('authority-context', 'authority-request', 'authority', 'judgment-event')),
    'control': ('authority', 'stop-observation'),
    'terminal': ('authority',), 'operator_answer': ('authority',),
    'gate': ('gate',), 'run_binding': ('run',),
    'analysis_route': ('route', 'intake'), 'research_route': ('route', 'intake'),
    'governed_step': ('step-outcome', 'step-dispatch'),
    'judgment': ('judgment',), 'replan': ('judgment-event', 'plan'),
    'ask': ('authority-context', 'authority-request', 'authority', 'judgment-event'),
}


def _definition(event_kind):
    # Module bytes bind the selectors below as well as this source-kind census.
    import hashlib
    from pathlib import Path
    return {'event_kind': event_kind, 'journal_kinds': list(PRODUCERS[event_kind]),
            'recorder': 'ravel.controller.authority.standing',
            'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def register_recorders(store):
    """Composition hook, called before intake; never backdate or renew coverage.

    Re-entry returns the original registration unchanged. Calling this late can
    record what is installed now, but cannot prove coverage from intake.
    """
    prior = common.scan(store, COMPOSITION, COMPOSITION_SCHEMA)
    if prior:
        return prior[0]
    return common.append(store, COMPOSITION, {
        'schema': COMPOSITION_SCHEMA, 'schema_version': 1, 'uid': common.uid(),
        'run_id': common.run_id(store), 'time_ns': common.now_ns(),
        'journal_head': store.head(),
        'recorders': {kind: _definition(kind) for kind in PRODUCERS}})


def delivery_decision(store, action):
    """The sink's decision boundary, appended immediately before its delivery gates.

    It is an invocation record, never an accepted outcome or permission to deliver.
    """
    if type(action) is not dict or not action:
        raise ValueError('the delivery decision binds its action')
    return common.append(store, DECISION, {
        'schema': DECISION_SCHEMA, 'schema_version': 1, 'uid': common.uid(),
        'run_id': common.run_id(store), 'time_ns': common.now_ns(),
        'journal_head': store.head(),
        'action_digest': common.digest(action)})


def _snapshot(store):
    """Fresh full-chain read using the controller reader, never its incremental cache.

    Use a separate reader so same-length edits before a cached offset are checked.
    A partial append or a head not exactly matching the snapshot is not complete.
    Only reader methods/private read state are used; no journal writer or repair.
    """
    from ravel.controller.store import RunStore, GENESIS, HEAD, JOURNAL
    fresh = RunStore.__new__(RunStore)
    fresh.run_id, fresh.store_root, fresh.root = store.run_id, store.store_root, store.root
    fresh._lock, fresh._entries, fresh._by_id = store._lock, [], {}
    fresh._offset, fresh._head, fresh._connections = 0, GENESIS, []
    with store._lock:
        fresh._refresh()
        fresh._check_head()
        if (store.root / JOURNAL).stat().st_size != fresh._offset:
            raise ValueError('the journal has an incomplete append')
        expected = {'seq': len(fresh._entries), 'digest': fresh._head}
        if json.loads((store.root / HEAD).read_bytes()) != expected:
            raise ValueError('the verified journal does not reach its authenticated head')
        entries = deepcopy(fresh._entries)
    return fresh, entries, expected


def _matches(event_kind, entry):
    kind, body = entry['kind'], entry['record']
    if kind not in PRODUCERS[event_kind]:
        return False
    if event_kind == 'control':
        return kind == 'stop-observation' or body.get('kind') in common.CONTROLS
    if event_kind == 'terminal':
        return body.get('label') in (common.LEGACY_TERMINAL, common.TERMINAL) or body.get('source') == 'controller_terminal'
    if event_kind == 'operator_answer':
        return body.get('source') == 'operator_cli' and body.get('request') is not None
    if event_kind in ('deviation', 'steering', 'ask', 'restricted_r3', 'checkin', 'final_checkin'):
        if kind == 'judgment-event':
            names = {'deviation': ('deviation',), 'ask': ('authority',)}.get(event_kind, ())
            return body.get('event') in names
        named = body.get('kind')
        if event_kind == 'restricted_r3':
            # These rows guard unblinding/spend-above-ceiling, not every R3 review.
            subject = body.get('subject') or {}
            view = body.get('view') or {}
            return named == 'r3_action' and (subject.get('gate') in ('unblind', 'spend_above_ceiling')
                                           or kind == 'authority-context' or view.get('gate') is not None)
        if event_kind == 'checkin':
            return named in common.CHECKINS
        return named == {'ask': 'escalation', 'final_checkin': 'final'}.get(event_kind, event_kind)
    if event_kind in ('analysis_route', 'research_route'):
        route = 'analysis' if event_kind == 'analysis_route' else 'research'
        named = body.get('route')
        return named == route or (type(named) is dict and named.get('id') == route) or body.get('task_mode') == route
    if event_kind == 'replan':
        return (body.get('event') in ('replan', 'replan_requested') if kind == 'judgment-event'
                else type(body.get('revision')) is int and body['revision'] > 0)
    return True


def absence_evidence(store, decision):
    """Read-only row -> typed status/evidence; any failed precondition yields no row.

    Verify from genesis, including intake through this decision. The evidence pins
    the exact head/range and event kind; a controller-issued composition record
    must precede intake and retain precisely this recorder definition.
    """
    try:
        reader, entries, head = _snapshot(store)
        if reader.check_binding():
            return {}
        compositions = common.scan(reader, COMPOSITION, COMPOSITION_SCHEMA)
        decisions = common.scan(reader, DECISION, DECISION_SCHEMA)
        if not compositions or not decisions or decisions[-1]['id'] != decision:
            return {}
        by_id = {entry['id']: entry for entry in entries}
        intake = next(entry for entry in entries if entry['kind'] == 'intake')
        composition = compositions[0]
        registration = by_id[composition['id']]
        boundary = by_id[decision]
        if (registration['seq'] >= intake['seq'] or boundary['seq'] <= intake['seq']
                or composition['run_id'] != store.run_id or decisions[-1]['run_id'] != store.run_id):
            return {}
        for entry, issued in ((registration, composition), (boundary, decisions[-1])):
            if issued.get('journal_head') != {'seq': entry['seq'] - 1, 'digest': entry['prev']}:
                return {}  # an attacker cannot re-chain the history to a different authenticated boundary
        # No input filter is allowed to hide occurrences before the delivery boundary.
        history = entries
        evidence = {}
        for row, event_kind in ROW_EVENTS.items():
            if any(c['recorders'].get(event_kind) != _definition(event_kind) for c in compositions):
                continue
            if any(_matches(event_kind, entry) for entry in history):
                continue
            evidence[row] = {'status': 'not_applicable', 'evidence': {
                'reason': f'not_applicable:authenticated_journal_has_zero_{event_kind}_events',
                'mechanism': 'controller.complete_event_journal', 'record': decision,
                'composition': composition['id'], 'event_kind': event_kind, 'event_count': 0,
                'journal_head_digest': head['digest'], 'verified_range': {
                    'from_seq': 1, 'through_seq': head['seq'], 'intake': intake['id'],
                    'delivery_decision': decision, 'decision_seq': boundary['seq']}}}
        return evidence
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration):
        return {}


def record_standing_rows(store, decision):
    """The sink's standing-row hook: pending run rows only, typed NA only.

    No satisfaction, waiver, conservation override or replacement of executed
    evidence occurs here. A ledger refusal leaves the row pending.
    """
    from ravel.controller.graph import service
    ledger = service('ledger')
    evidence = absence_evidence(store, decision)
    recorded, pending = [], []
    if not evidence:
        try:
            _snapshot(store)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return {'recorded': recorded, 'pending': pending}
    # A refused delivery may be resumed. Never keep an old absence discharge
    # after a newly observed event or a gap in recorder coverage. Ledger rows
    # cannot return to pending, so an invalidated old proof becomes a violation.
    try:
        current = getattr(ledger, 'current', lambda _: [])(store)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # A validly re-chained file can still invalidate the caller's cached
        # reader offset. It grants no absence credit and must write nothing.
        return {'recorded': recorded, 'pending': pending}
    revalidated = {}
    for instance in current:
        prior = instance.get('evidence') or {}
        row = instance['id']
        if (instance['status'] != 'not_applicable'
                or prior.get('mechanism') != 'controller.complete_event_journal'):
            continue
        if row in evidence:
            revalidated[row] = evidence[row]['evidence']
            continue
        ledger.record(store, instance['entry'], 'violated', {
            'reason': 'the current delivery journal no longer proves the earlier event absence',
            'label': 'UNVERIFIED EVENT ABSENCE', 'record': decision,
            'previous_evidence': deepcopy(prior)})
        recorded.append(instance['entry'])
    if revalidated:
        store.append('standing-row-revalidation', {'decision': decision, 'rows': revalidated})
    for key in ledger.pending(store):
        row = key.split('@', 1)[0]
        found = evidence.get(row)
        if found is None:
            continue
        # Protect scoped/conserved instances even if a catalogue later reuses an id.
        if any('/' + scope + '=' in key for scope in ('deliverable', 'step', 'seat', 'artifact', 'point', 'waypoint')):
            continue
        try:
            ledger.record(store, key, found['status'], found['evidence'])
            recorded.append(key)
        except Exception:
            pending.append(key)
    return {'recorded': recorded, 'pending': pending}


def record_delivery_rows(store, action):
    """Sink interface: unregistered runs gain no absence evidence at delivery."""
    if not common.scan(store, COMPOSITION, COMPOSITION_SCHEMA):
        return {'recorded': [], 'pending': []}
    _snapshot(store)  # fail closed before any writer can rely on an incremental cache
    from .event_rows import record_executed_rows
    executed = record_executed_rows(store)
    decision = delivery_decision(store, action)
    absent = record_standing_rows(store, decision['id'])
    return {key: executed[key] + absent[key] for key in ('recorded', 'pending')}
