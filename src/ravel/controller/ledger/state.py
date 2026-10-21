"""The ledger state: verified events folded into instances and the run's current populations.

The current population of a run is the latest intake materialisation, the latest plan revision, the latest attempt
of every seat, the latest delivery and every occurrence (deviation, escalation or event decision). Instances outside
it are superseded: a retried seat attempt, a step a replan removed. They stay in the record and in the receipt.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from urllib.parse import quote

from . import chain
from .chain import LedgerError

STATUSES = ('pending', 'satisfied', 'violated', 'waived', 'not_applicable')
# Allowed status changes (CONTROLLER-SPEC 7.3): nothing returns to pending and ``violated`` is final.
ALLOWED = {
    'pending': ('satisfied', 'violated', 'waived', 'not_applicable'),
    'satisfied': ('satisfied', 'violated'),
    'waived': ('violated',),
    'not_applicable': ('violated',),
    'violated': (),
}
STAGES = ('intake', 'plan', 'dispatch', 'review', 'deliver', 'event')
SCOPE_FIELDS = ('step', 'point', 'seat', 'attempt', 'deliverable', 'artifact', 'claim', 'event')
SAFE = '-_.~:+#'


def instance_key(row_id: str, run_id: str, scope: dict) -> str:
    """``<row>@<run>[/step=..][/point=..][/seat=..][/attempt=..][/deliverable=..][/artifact=..][/claim=..][/event=..]``."""
    parts = [f'{row_id}@{quote(run_id, safe=SAFE)}']
    for name in SCOPE_FIELDS:
        value = scope.get(name)
        if value is not None:
            parts.append(f'{name}={quote(str(value), safe=SAFE)}')
    return '/'.join(parts)


@dataclass
class Instance:
    key: str
    id: str
    stage: str
    scope: dict
    created: int
    status: str = 'pending'
    evidence: dict | None = None
    history: list = field(default_factory=list)


@dataclass
class State:
    events: int = 0
    head: str = chain.GENESIS
    error: str | None = None
    run_id: str | None = None
    pins: dict = field(default_factory=dict)
    instances: dict = field(default_factory=dict)
    intake: dict | None = None
    intake_keys: tuple = ()
    plan: dict | None = None
    plan_keys: tuple = ()
    plan_revision: int = 0
    seats: dict = field(default_factory=dict)          # (step, point, seat) -> {attempt: keys}
    seat_context: dict = field(default_factory=dict)   # (step, point, seat, attempt) -> context
    deliver: dict | None = None
    deliver_keys: tuple = ()
    occurrences: dict = field(default_factory=dict)    # occurrence id -> {kind, step, keys}
    deliverables: list = field(default_factory=list)   # the original obligations, in order of first appearance
    planned_steps: set = field(default_factory=set)     # every step id of every plan revision
    refusals: list = field(default_factory=list)

    # ---- populations ------------------------------------------------------------------------------------
    def latest_seats(self) -> dict:
        """(step, point, seat) -> (latest attempt, keys) for current steps and controller steps.

        A seat of a step that an earlier plan revision had and the current one does not is superseded.
        """
        current = {s['id'] for s in self.plan_steps()}
        return {unit: (max(attempts), attempts[max(attempts)]) for unit, attempts in self.seats.items()
                if unit[0] in current or unit[0] not in self.planned_steps}

    def current_keys(self) -> list[str]:
        """Intake, current plan, latest seat attempts, latest delivery, occurrences and every conserved obligation."""
        keys = list(self.intake_keys) + list(self.plan_keys)
        keys.extend(k for k, i in self.instances.items() if 'deliverable' in i.scope)
        for _, (_, seat_keys) in sorted(self.latest_seats().items()):
            keys.extend(seat_keys)
        keys.extend(self.deliver_keys)
        for occurrence in self.occurrences.values():
            keys.extend(occurrence['keys'])
        seen, result = set(), []
        for key in keys:
            if key not in seen:
                seen.add(key)
                result.append(key)
        return result

    def plan_steps(self) -> list[dict]:
        return list((self.plan or {}).get('steps') or [])

    def step(self, step_id: str) -> dict | None:
        for step in self.plan_steps():
            if step['id'] == step_id:
                return step
        return None


def _fail(state: State, message: str) -> State:
    state.error = state.error or message
    return state


def apply(state: State, event: dict) -> State:
    """Fold one verified event. An inconsistent event sets ``state.error``; nothing after it is trusted."""
    if state.error:
        return state
    body = event['body']
    seq = event['seq']
    kind = body.get('event')
    run_id = body.get('run_id')
    if state.run_id is not None and run_id != state.run_id:
        return _fail(state, f'ledger event {seq} belongs to run {run_id!r}, not {state.run_id!r}')
    if kind == 'materialise':
        stage = body.get('stage')
        if stage not in STAGES:
            return _fail(state, f'ledger event {seq} names an unknown stage {stage!r}')
        if state.run_id is None:
            if stage != 'intake':
                return _fail(state, f'ledger event {seq} precedes the intake materialisation')
            state.run_id = run_id
            state.pins = dict(body.get('pins') or {})
        elif stage == 'intake':
            return _fail(state, f'ledger event {seq} is a second intake materialisation')
        if body.get('catalogue_sha256') != state.pins.get('catalogue_sha256'):
            return _fail(state, f'ledger event {seq} was materialised from a different catalogue')
        keys = []
        for item in body.get('instances') or []:
            key = item.get('key')
            if not isinstance(key, str) or not isinstance(item.get('id'), str):
                return _fail(state, f'ledger event {seq} carries an invalid instance')
            existing = state.instances.get(key)
            if existing is None:
                state.instances[key] = Instance(key=key, id=item['id'], stage=stage,
                                                scope=dict(item.get('scope') or {}), created=seq)
            elif existing.id != item['id']:
                return _fail(state, f'ledger event {seq} reuses instance key {key} for another obligation')
            keys.append(key)
        context = body.get('context') or {}
        keys = tuple(keys)
        if stage == 'intake':
            state.intake, state.intake_keys = context, keys
            _extend(state.deliverables, context.get('deliverables') or [])
        elif stage == 'plan':
            state.plan, state.plan_keys = context, keys
            state.plan_revision += 1
            state.planned_steps.update(s['id'] for s in context.get('steps') or [])
            _extend(state.deliverables, [d['id'] for d in context.get('deliverables') or []])
        elif stage in ('dispatch', 'review'):
            unit = (context.get('step'), context.get('point') or '', context.get('seat'))
            attempt = context.get('attempt')
            state.seats.setdefault(unit, {})[attempt] = keys
            state.seat_context[unit + (attempt,)] = context
        elif stage == 'deliver':
            state.deliver, state.deliver_keys = context, keys
        else:
            state.occurrences[context.get('id')] = {'kind': context.get('kind'), 'step': context.get('step'),
                                                    'keys': keys}
    elif kind == 'status':
        if state.run_id is None:
            return _fail(state, f'ledger event {seq} precedes the intake materialisation')
        for change in body.get('changes') or []:
            instance = state.instances.get(change.get('key'))
            if instance is None:
                return _fail(state, f'ledger event {seq} changes an unknown instance {change.get("key")!r}')
            if change.get('from') != instance.status or change.get('to') not in ALLOWED[instance.status]:
                return _fail(state, f'ledger event {seq} records an inconsistent change of {instance.key}')
            evidence = change.get('evidence') or {}
            instance.history.append({'seq': seq, 'from': instance.status, 'to': change['to'],
                                     'evidence_sha256': chain.digest(evidence)})
            instance.status, instance.evidence = change['to'], evidence
            if evidence.get('refusal'):
                state.refusals.append({'seq': seq, 'entry': instance.key, 'id': instance.id,
                                       'status': change['to'], 'refusal': evidence['refusal']})
    else:
        return _fail(state, f'ledger event {seq} has an unknown kind {kind!r}')
    state.events = seq + 1
    state.head = event['sha256']
    return state


def _extend(population: list, items) -> None:
    for item in items:
        if item not in population:
            population.append(item)


def fold(events) -> State:
    state = State()
    for event in events:
        apply(state, event)
    return state


# ---- loading ---------------------------------------------------------------------------------------------

_CACHE: dict[str, State] = {}
_SEEN: dict[str, tuple[int, str]] = {}   # per run: the longest chain this process verified (events, head)


def _high_water(key: str, state: State) -> State:
    """Refuse a ledger shorter than, or diverging from, the chain this process already verified.

    A complete rewrite by a process that can write the store is outside the chain's reach; the receipt anchors the
    head digest for that (CONTROLLER-SPEC 2.2).
    """
    if state.error:
        return state
    seen = _SEEN.get(key)
    if seen is not None:
        events, head = seen
        if state.events < events:
            return _fail(state, f'the ledger lost events: this process verified {events}, the store now holds '
                         f'{state.events}')
        if state.events == events and state.head != head:
            return _fail(state, 'the ledger was rewritten after this process verified it')
    if seen is None or state.events >= seen[0]:
        _SEEN[key] = (state.events, state.head)
    return state


def load(store, *, full: bool = False) -> State:
    """The folded state of the run's ledger.

    The snapshot, verification, cache and high-water update share the writers' thread/process lock.
    ``full`` verifies and folds every event (gates and summaries). Otherwise a cached state
    is reused when its head event is unchanged in the store; only the newer events are verified and folded.
    Returned states remain snapshots: extending the cache never mutates a prior reader's state.
    A chain fault is returned as ``state.error``, never raised.
    """
    with chain.locked(store):
        return _load_locked(store, full=full)


def _load_locked(store, *, full: bool) -> State:
    records = chain.scan(store)
    key = chain.store_key(store)
    cached = None if full else _CACHE.get(key)
    if cached is not None and not cached.error and 0 < cached.events <= len(records):
        cached = deepcopy(cached)
        try:
            ordered = sorted(records, key=lambda r: r['seq'])
        except (KeyError, TypeError):
            ordered = None
        if ordered is not None:
            last = ordered[cached.events - 1]
            own = {k: last.get(k) for k in chain.FIELDS}
            if last.get('sha256') == cached.head and own['seq'] == cached.events - 1 and chain.digest(own) == cached.head:
                tail, error = chain.verify_tail(ordered[cached.events:], cached.events, cached.head)
                for event in tail:
                    apply(cached, event)
                if error:
                    _fail(cached, error)
                if not cached.error:
                    _CACHE[key] = cached
                return _high_water(key, cached)
    events, error = chain.verify(records)
    state = fold(events)
    if error:
        _fail(state, error)
    _high_water(key, state)
    if not full and not state.error:
        _CACHE[key] = state
    return state


def forget(store) -> None:
    """Drop this process's cached state and high-water mark of the run (a fresh process)."""
    with chain.locked(store):
        key = chain.store_key(store)
        _CACHE.pop(key, None)
        _SEEN.pop(key, None)


def require_run(state: State) -> None:
    if state.error:
        raise LedgerError('chain_broken', f'the ledger of this run cannot be trusted: {state.error}')
    if state.run_id is None:
        raise LedgerError('not_materialised', 'the run has no intake materialisation')
