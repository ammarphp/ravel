"""Obligation ledger of controller runs.

The catalogue (installed package data) lists every obligation with its mechanisms, class, discharging node,
applicability and waivability. ``materialise`` instantiates the rows that apply to a run at intake, plan, each seat
attempt, each review seat and delivery; ``record`` tracks each instance as pending, satisfied, violated, waived or
not applicable with evidence; ``gate`` lists what a graph transition still lacks; ``summary`` gives the receipt its
counts and head digest. Every change is an append-only, hash-chained event in the run store, stamped by the
controller's clock. The ledger never reads the run directory; ``decide`` hands it to the decision gate.

Binding interface (PACKAGES.md 0.2)::

    materialise(store, stage, context) -> list[str]      # stage: intake|plan|dispatch|review|deliver (and event)
    record(store, entry_id, status, evidence) -> None    # pending|satisfied|violated|waived|not_applicable
    gate(store, transition) -> list[dict]                # unmet rows; empty means the edge may be taken
    population_equality(expected, actual) -> list[str]   # holes
    summary(store) -> dict

Additions: ``record_many`` (one event for several changes), ``pending`` (what a node still has to discharge),
``current`` (the current instances of a node or step with their status and evidence, read only),
``parent_join`` (the conservation join of node ``ledger.parent_join``), ``decide`` (a decision through the decision
gate that discharges its GATE row with the evidence its providers name), ``verify`` and ``TRANSITIONS``.
Composition explicitly installs gate callbacks with ``register_gate_hook(provider_id, fn)`` and authenticated
waiver reads with ``register_authority_reader(fn)``; neither peer is imported by the ledger. Missing required
composition refuses the operation.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import chain, gates as _gates, materialise as _materialise, record as _record, state as _state
from .catalogue import Catalogue, CatalogueError, load as load_catalogue
from .chain import LedgerError
from .gates import TRANSITIONS
from .state import STATUSES, instance_key

__all__ = ['materialise', 'record', 'record_many', 'gate', 'population_equality', 'summary', 'pending', 'current',
           'parent_join', 'decide', 'verify', 'load_catalogue', 'instance_key', 'Catalogue', 'CatalogueError',
           'LedgerError', 'STATUSES', 'TRANSITIONS', 'MATERIALISE_STAGES', 'SUMMARY_SCHEMA',
           'register_gate_hook', 'register_authority_reader']

MATERIALISE_STAGES = ('intake', 'plan', 'dispatch', 'review', 'deliver', 'event')
SUMMARY_SCHEMA = 'ledger-summary.v1'


def register_gate_hook(provider_id: str, fn) -> None:
    """Install ``fn(store, canonical_transition, *, plan) -> list[dict]`` at composition.

    Callbacks add unmet rows to both transition and decision gates, including bounded endings. The transition is
    the name returned by ``parse`` (without a step qualifier); the plan is resolved from the controller store when
    available, otherwise the ledger's current projection, or None before plan materialisation. Providers return
    ordinary unmet rows or ``{row, reason}`` records. A failed or malformed callback always refuses the gate.
    """
    _gates.register_gate_hook(provider_id, fn)


def register_authority_reader(fn) -> None:
    """Install ``fn(store, record_id) -> dict`` for waivers, authenticating the cited record before returning it.

    The authority provider must check issuer custody and current authorization, resolving its accepted identifiers
    to a record body. Raise KeyError for an absent record; other failures refuse as ``authority_unverified``.
    Registration is explicit and idempotent; a different reader cannot silently replace an installed reader.
    """
    _record.register_authority_reader(fn)


def _live_registry_sha256() -> str:
    from ravel.workflow import decision_gate
    return decision_gate.registry_sha256()


def _require_pinned(cat: Catalogue, state) -> None:
    _state.require_run(state)
    if state.pins.get('catalogue_sha256') != cat.sha256:
        raise LedgerError('catalogue_changed', 'the installed obligation catalogue differs from the one this run '
                          'pinned at intake')


def materialise(store, stage: str, context: dict) -> list[str]:
    """Instantiate the obligations that apply at ``stage``; returns the instance keys (entry ids) it selected.

    Repeating a materialisation with the same context appends nothing and returns the same keys.
    """
    if stage not in MATERIALISE_STAGES:
        raise LedgerError('stage_unknown', f'unknown materialisation stage {stage!r}')
    cat = load_catalogue()
    with chain.locked(store):
        state = _state.load(store)
        if state.error:
            raise LedgerError('chain_broken', f'the ledger of this run cannot be trusted: {state.error}')
        pins = None
        if stage == 'intake':
            context = _materialise.normalise(stage, context, state)
            if state.run_id is not None:
                if chain.digest(context) == chain.digest(state.intake):
                    return list(state.intake_keys)
                raise LedgerError('intake_repeated', 'this run was materialised at intake with another context; '
                                  'the obligation denominator is pinned at intake')
            live = _live_registry_sha256()
            if live != cat.gate_registry['sha256']:
                raise LedgerError('provider_registry_unpinned', 'the installed decision-gate provider registry '
                                  'differs from the one the obligation catalogue pins')
            pins = {'catalogue_sha256': cat.sha256, 'gate_registry_sha256': live}
            run_id = context['run_id']
        else:
            _require_pinned(cat, state)
            context = _materialise.normalise(stage, context, state)
            run_id = state.run_id
            repeated = _repeated(state, stage, context)
            if repeated is not None:
                return repeated
        pairs = _materialise.select(cat, stage, context, state)
        items = _materialise.instances(cat, run_id, pairs)
        body = {'event': 'materialise', 'stage': stage, 'run_id': run_id, 'time_ns': chain.clock(),
                'catalogue_sha256': cat.sha256, 'context': context, 'context_sha256': chain.digest(context),
                'instances': items}
        if pins is not None:
            body['pins'] = pins
        chain.append(store, chain.seal(state.events, state.head, body))
        return [item['key'] for item in items]


def _repeated(state, stage: str, context: dict):
    """The keys of an identical earlier materialisation, None for a new one; a conflicting repeat is refused."""
    digest = chain.digest(context)
    if stage == 'plan':
        if state.plan is not None and chain.digest(state.plan) == digest:
            return list(state.plan_keys)
        return None
    if stage in ('dispatch', 'review'):
        unit = (context['step'], context['point'] or '', context['seat'])
        attempts = state.seats.get(unit) or {}
        if context['attempt'] in attempts:
            if chain.digest(state.seat_context[unit + (context['attempt'],)]) == digest:
                return list(attempts[context['attempt']])
            raise LedgerError('attempt_reused', f'attempt {context["attempt"]} of seat {context["seat"]} at step '
                              f'{context["step"]} was materialised with another context; a retry is a new attempt')
        if attempts and context['attempt'] < max(attempts):
            raise LedgerError('attempt_stale', f'seat {context["seat"]} at step {context["step"]} is already at '
                              f'attempt {max(attempts)}')
        return None
    if stage == 'deliver':
        if state.deliver is not None and chain.digest(state.deliver) == digest:
            return list(state.deliver_keys)
        return None
    if stage == 'event':
        occurrence = state.occurrences.get(context['id'])
        if occurrence is None:
            return None
        if occurrence['kind'] == context['kind'] and occurrence.get('step') == context['step']:
            return list(occurrence['keys'])
        raise LedgerError('event_reused', f'occurrence {context["id"]} was materialised as another event')
    return None


def record(store, entry_id: str, status: str, evidence: dict) -> None:
    """Record one status change of a materialised instance; refused changes raise LedgerError."""
    record_many(store, [(entry_id, status, evidence)])


def record_many(store, changes) -> None:
    """Record several status changes as one event: all are checked first, and none is written if one is refused."""
    changes = list(changes)
    if not changes:
        return
    cat = load_catalogue()
    with chain.locked(store):
        state = _state.load(store)
        _require_pinned(cat, state)
        seen, out = set(), []
        for change in changes:
            try:
                key, status, evidence = change
            except (TypeError, ValueError):
                raise LedgerError('change_invalid', 'a change is (entry id, status, evidence)') from None
            if key in seen:
                raise LedgerError('change_invalid', f'{key} is changed twice in one event')
            seen.add(key)
            evidence = _record.check(cat, state, store, key, status, evidence)
            out.append({'key': key, 'from': state.instances[key].status, 'to': status, 'evidence': evidence})
        body = {'event': 'status', 'run_id': state.run_id, 'time_ns': chain.clock(), 'changes': out}
        chain.append(store, chain.seal(state.events, state.head, body))


def gate(store, transition: str) -> list[dict]:
    """Unmet requirements of ``transition`` (see ``TRANSITIONS``); empty means the edge may be taken."""
    return _gates.unmet(store, transition)


def population_equality(expected: list[str], actual: list[str]) -> list[str]:
    """The holes: members of ``expected`` that ``actual`` lacks, counted with multiplicity, in expected order.

    Extras in ``actual`` are not holes; swap the arguments to list them.
    """
    return _gates.population_equality(expected, actual)


def summary(store) -> dict:
    """Counts by status, class and ledger class, refusals, waivers, violations and the head digest, for the receipt."""
    cat = load_catalogue()
    state = _state.load(store, full=True)
    current = set(state.current_keys())
    by_status = Counter()
    by_class = {c: Counter() for c in ('E', 'L', 'R', 'I')}
    by_ledger = {}
    current_status = Counter()
    waivers, violations, inapplicable = [], [], []
    for key, instance in state.instances.items():
        row = cat.rows.get(instance.id)
        by_status[instance.status] += 1
        if row is not None:
            by_class[row['class']][instance.status] += 1
            by_ledger.setdefault(row['ledger_class'], Counter())[instance.status] += 1
        if key in current:
            current_status[instance.status] += 1
        if instance.status == 'waived':
            waivers.append({'entry': key, 'id': instance.id, 'authority': (instance.evidence or {}).get('authority'),
                            'waiver': row.get('waiver') if row else None})
        if instance.status == 'not_applicable' and row is not None and row['waivability'] != 'authority':
            inapplicable.append({'entry': key, 'id': instance.id, 'waivability': row['waivability'],
                                 'reason': (instance.evidence or {}).get('reason')})
        if instance.status == 'violated':
            violations.append({'entry': key, 'id': instance.id, 'class': row['class'] if row else None,
                               'superseded': key not in current,
                               'label': (instance.evidence or {}).get('label'),
                               'reason': (instance.evidence or {}).get('reason')})
    holes = []
    present = {i.scope.get('deliverable') for i in state.instances.values() if 'deliverable' in i.scope}
    for deliverable in state.deliverables:
        instance_open = [i for i in state.instances.values()
                         if i.scope.get('deliverable') == deliverable and i.status not in ('satisfied', 'waived')]
        if deliverable not in present or instance_open:
            holes.append(deliverable)
    return {
        'schema': SUMMARY_SCHEMA,
        'run_id': state.run_id,
        'catalogue_sha256': state.pins.get('catalogue_sha256'),
        'catalogue_current': state.pins.get('catalogue_sha256') == cat.sha256,
        'gate_registry_sha256': state.pins.get('gate_registry_sha256'),
        'head': state.head,
        'events': state.events,
        'chain': {'verified': state.error is None, 'error': state.error, 'events': state.events},
        'instances': len(state.instances),
        'by_status': {s: by_status.get(s, 0) for s in STATUSES},
        'by_class': {c: {s: n.get(s, 0) for s in STATUSES} for c, n in by_class.items()},
        'by_ledger_class': {c: {s: n.get(s, 0) for s in STATUSES} for c, n in sorted(by_ledger.items())},
        'current': {'instances': len(current), 'by_status': {s: current_status.get(s, 0) for s in STATUSES}},
        'superseded': len(state.instances) - len(current & set(state.instances)),
        'refusals': len(state.refusals),
        'refusal_events': [dict(r) for r in state.refusals],
        'waivers': waivers,
        'violations': violations,
        'not_applicable': inapplicable,  # rows nobody may waive, closed as not applicable, with their reasons
        'deliverables': {'expected': list(state.deliverables), 'open': holes},
        'plan_revision': state.plan_revision,
    }


def pending(store, *, node: str | None = None, stage: str | None = None, step: str | None = None,
            seat: str | None = None, attempt: int | None = None, point: str | None = None) -> list[str]:
    """Current pending entry ids, filtered by discharging node (base or full), stage and scope."""
    cat = load_catalogue()
    state = _state.load(store, full=True)
    _require_pinned(cat, state)
    result = []
    for key in state.current_keys():
        instance = state.instances[key]
        if instance.status != 'pending':
            continue
        row_node = cat.rows[instance.id]['node']
        if node is not None and node not in (row_node, row_node.split('[', 1)[0]):
            continue
        if stage is not None and instance.stage != stage:
            continue
        scope = instance.scope
        if any(value is not None and scope.get(name) != value
               for name, value in (('step', step), ('seat', seat), ('attempt', attempt), ('point', point))):
            continue
        result.append(key)
    return result


def current(store, *, node: str | None = None, stage: str | None = None, step: str | None = None) -> list[dict]:
    """Current instances, any status, filtered by discharging node (base or full), stage and step; read only.

    Each row is ``{'entry', 'id', 'status', 'evidence'}``. A caller that verifies an earlier discharge
    reads it here; nothing is recorded.
    """
    from copy import deepcopy
    cat = load_catalogue()
    state = _state.load(store, full=True)
    _require_pinned(cat, state)
    result = []
    for key in state.current_keys():
        instance = state.instances[key]
        row_node = cat.rows[instance.id]['node']
        if node is not None and node not in (row_node, row_node.split('[', 1)[0]):
            continue
        if stage is not None and instance.stage != stage:
            continue
        if step is not None and instance.scope.get('step') != step:
            continue
        result.append({'entry': key, 'id': instance.id, 'status': instance.status,
                       'evidence': deepcopy(instance.evidence)})
    return result


def parent_join(store) -> list[str]:
    """Satisfy each pending conserved obligation whose mapped plan steps are all closed; returns those entries.

    An obligation the plan keeps open, or maps to a step that is not closed, stays pending (CONTROLLER-SPEC R05).
    """
    cat = load_catalogue()
    with chain.locked(store):
        state = _state.load(store)
        _require_pinned(cat, state)
        mapping = {d['id']: d['steps'] for d in (state.plan or {}).get('deliverables') or []}
        changes = []
        for key in state.current_keys():
            instance = state.instances[key]
            deliverable = instance.scope.get('deliverable')
            if deliverable is None or instance.status != 'pending':
                continue
            steps = mapping.get(deliverable) or []
            if steps and not any(_gates.step_unmet(cat, state, s) for s in steps):
                changes.append((key, 'satisfied', {'covered_by': steps, 'mechanism': 'ledger.parent_join'}))
        record_many(store, changes)
        return [key for key, _, _ in changes]


def _gate_entry(store, state, gate_name: str, action: dict):
    rid = f'GATE-{gate_name}'
    event = action.get('event') if isinstance(action.get('event'), str) else None
    # A step-qualified decision discharges the row of the step its transition checked, whatever other fields say.
    qualifier = _gates.parse(_gates.transition_for(store, gate_name, action)[0])[1]
    step = qualifier if qualifier is not None and event is None else next(
        (action.get(f) for f in ('step', 'waypoint', 'node_id') if isinstance(action.get(f), str)), None)
    candidates = [state.instances[k] for k in state.current_keys() if state.instances[k].id == rid]
    for instance in candidates:
        scope = instance.scope
        if event is not None and scope.get('event') == event:
            return instance.key
        if event is None and step is not None and scope.get('step') == step:
            return instance.key
    run_level = [i for i in candidates if not i.scope]
    if event is None and len(run_level) == 1:
        return run_level[0].key
    return None


def decide(store, rundir, gate_name: str, action: dict) -> list:
    """Take a decision through the decision gate and, when it passes, discharge the decision's GATE row with the
    evidence its providers name (``gate_evidence``; for a controller run's plan approval, the review and RDJ cases
    that justified it).

    Returns the decision gate's errors (empty on a pass); nothing is recorded as satisfied on a refusal. An event
    decision (deviation, correction, research choice, unblinding, spending above a ceiling, ...) names its occurrence
    in ``action['event']``; the occurrence and its obligations are materialised before the gate is asked, because the
    transition the decision leads to requires them. ``rundir`` must be the directory the controller binds to this
    ledger's run; any other directory is refused (``ledger_run_mismatch``) before anything is recorded.
    """
    from ravel.workflow import decision_gate
    if not isinstance(action, dict):
        raise ValueError('gate action must be an object')
    cat = load_catalogue()
    row = f'GATE-{gate_name}'
    with chain.locked(store):
        state = _state.load(store)
        _require_pinned(cat, state)
        owner = decision_gate._controller_owner(Path(rundir), gate_name)
        if isinstance(owner, list):
            return owner
        if owner != state.run_id:
            # A directory of another run, or one the controller does not own, is decided by other evidence (or by
            # the legacy gate); its pass never discharges this run's row.
            return [decision_gate.GateError(
                'ledger_run_mismatch', gate_name, 'ledger',
                f'{rundir} is not the run directory of controller run {state.run_id} (owner {owner!r})',
                'Take the decision on the run directory the controller bound to this run.', ('ledger:run',))]
        if _gate_entry(store, state, gate_name, action) is None and isinstance(action.get('event'), str) and \
                row in cat.rows and cat.rows[row]['applicability']['stage'] == 'event':
            materialise(store, 'event', {'kind': gate_name, 'id': action['event'], 'step': action.get('step')})
    transition, _ = _gates.transition_for(store, gate_name, action)
    with _gates.hook_scope():
        errors = list(decision_gate.check(Path(rundir), gate_name, action))
        # A decision provider may refuse before decision_gate reaches the ledger. Always consult the hooks;
        # nested transition checks share their results for this decision, so a callback is not invoked twice.
        for unmet in _gates.registered_unmet(store, transition):
            code, pin = 'ledger_' + unmet['reason'], f'ledger:{unmet["entry"]}'
            if not any(error.code == code and pin in error.pins for error in errors):
                errors.append(decision_gate.GateError(
                    code, gate_name, 'ledger', unmet['message'],
                    f'Discharge {unmet["id"] or unmet["entry"]} before {transition}.', (pin,)))
    if errors:
        return errors
    try:
        providers = _provider_evidence(rundir, gate_name, action)
    except Exception as exc:  # a passed decision whose providers cannot name their evidence is not recorded
        return [decision_gate.GateError('provider_evidence_invalid', gate_name, 'ledger', f'{type(exc).__name__}: {exc}',
                                        'Repair the named provider evidence before deciding.', ('ledger:providers',))]
    with chain.locked(store):
        state = _state.load(store)
        key = _gate_entry(store, state, gate_name, action)
        if key is None:
            raise LedgerError('entry_unknown', f'no current {row} entry matches this decision')
        from . import recorders
        proof = recorders.decision(store, gate_name, action, providers, state.pins.get('gate_registry_sha256'))
        record(store, key, 'satisfied', {'gate': gate_name, 'action_sha256': chain.digest(action),
                                         'registry_sha256': state.pins.get('gate_registry_sha256'),
                                         'record': proof,
                                         'mechanism': 'decision_gate.check',
                                         **({'providers': providers} if providers else {})})
    return []


def _provider_evidence(rundir, gate_name: str, action: dict) -> dict:
    """``{provider id: evidence}`` that the passed decision's active providers name through their optional
    ``gate_evidence`` (for example the review evidence that discharged a controller run's plan approval)."""
    from copy import deepcopy
    from importlib import import_module
    from ravel.workflow import decision_gate
    found = {}
    for row in decision_gate.providers(gate_name):
        if not row['active']:
            continue
        reader = getattr(import_module(row['module']), 'gate_evidence', None)
        if callable(reader):
            value = reader(Path(rundir), gate_name, deepcopy(action))
            if value is not None:
                found[row['id']] = value
    return found


def verify(store) -> dict:
    """The ledger chain's verification result."""
    state = _state.load(store, full=True)
    return {'verified': state.error is None, 'error': state.error, 'events': state.events, 'head': state.head}
