"""Atomic budget reservations in the run store (mechanism M17).

Every effect is reserved before it starts, on every dimension of the run's budget envelope (the
operator's frozen envelope narrowed by approved steering, read from the authority service):
wall seconds, model calls, tokens, cost where the transport measures it, core-hours, generated
events and children (one per worker or launch attempt). The check and the append happen under
one lock in the store, so two reservations racing for the last unit cannot both pass.
Reservations are never refunded by a worker's word: a settled attempt is charged its measured
use where the controller observed it and its full reservation where it did not; an attempt
that started without a receipted outcome stays charged in full until it is reconciled; retries
and review seats are new reservations. A hold before anything started releases its own
reservation. Unknown amounts stay unknown: an unknown request never passes a finite ceiling,
and a dimension without a configured ceiling is reported as unbounded, never as zero.
"""
from __future__ import annotations

from copy import deepcopy
import math
import platform
import sys

from ravel.workflow.state_io import file_lock

from .services import StepHold, digest, lock_path, module, records

# Supplied data read (bytes, files) and batch CPU-hours are reserved and charged like every other resource;
# an attempt that names none of them reserves zero (earlier records without them are read as zero).
OPTIONAL_DIMENSIONS = ('input_bytes', 'input_files', 'batch_cpu_hours')
DIMENSIONS = ('wall_seconds', 'model_calls', 'tokens', 'cost_usd', 'core_hours', 'events', 'children',
              *OPTIONAL_DIMENSIONS)
# The operator must bound these for any effect to start; the others may be unconfigured.
FINITE = ('wall_seconds', 'model_calls', 'children')
# Measured after the effect: no transport states them in advance. An unknown request passes only
# while the charged total is below the ceiling; a known request is checked like any other.
MEASURED_AFTER = ('tokens', 'cost_usd')
TOP_RUNGS = ('full', 'scan')
# These registered units describe work bounded by a local deadline, rather than event throughput.
# Unknown units never inherit this classification.
NON_EVENT_UNITS = ('task', 'seconds', 'wall_seconds', 'bytes', 'blocks')
RESERVATION = 'budget-reservation'
SETTLEMENT = 'budget-settlement'
CALIBRATION = 'pilot-calibration'
PILOT_LAUNCH = 'pilot-launch'
PILOT_RUNG = 'pilot'
# An approved launch argv word the controller replaces with the acting rung's own event budget.
EVENTS_TOKEN = '@events'
# A derived pilot generates this fraction of the top rung's declared events (at least one), unless the
# approved step declares its own smaller pilot (``parameters.pilot.events``).
PILOT_FRACTION = 0.01
SETTLED = ('settled', 'released', 'reconciled')


def _number(value):
    return value is None or (type(value) in (int, float) and value >= 0)


def envelope(store, context=None):
    """The run's budget envelope, one ceiling (or None) per dimension, from the authority service."""
    authority = module('authority')
    bounds = getattr(authority, 'effective_bounds', None)
    if bounds is not None:
        try:
            found = bounds(store)
        except Exception as exc:
            # No frozen operating mode (or more than one): the run has no envelope, a hold, never a failed step.
            if 'AuthorityRefused' not in {cls.__name__ for cls in type(exc).__mro__}:
                raise
            raise StepHold('operating_mode_unavailable', str(exc)[:500]) from None
        value = found.get('budgets') if type(found) is dict else None
    else:
        value = ((context or {}).get('mode') or {}).get('budgets')
    if type(value) is not dict or not all(_number(value.get(d)) for d in DIMENSIONS):
        raise StepHold('budget_envelope_missing', 'the run carries the operator\'s frozen budget envelope')
    ceilings = {dimension: value.get(dimension) for dimension in DIMENSIONS}
    missing = [d for d in FINITE if ceilings[d] is None]
    if missing:
        raise StepHold('budget_ceiling_missing', 'the operator bounds ' + ', '.join(missing) + ' before any effect')
    return ceilings


def machine_pin():
    """The controller host's identity for pilot calibration (platform, architecture, node)."""
    return digest({'platform': sys.platform, 'machine': platform.machine(), 'node': platform.node()})


def key(step_id, attempt, seat=None):
    return f'{step_id}/{attempt}/{seat or "producer"}'


def _state(store):
    """``{key: {reservation, settlement}}`` from the store's append-only rows."""
    found = {}
    for row in records(store, RESERVATION):
        found.setdefault(row['key'], {})['reservation'] = row
    for row in records(store, SETTLEMENT):
        if row['key'] in found:
            found[row['key']]['settlement'] = row
    return found


def _charged(entry):
    reservation, settlement = entry['reservation'], entry.get('settlement')
    if settlement is None or settlement['status'] not in SETTLED:
        found = dict(reservation['amounts'])
    else:
        found = dict(settlement['charged'])
    return {**{d: 0 for d in OPTIONAL_DIMENSIONS}, **found}


def totals(store, ceilings=None):
    """Per dimension: the ceiling, the reserved and charged sums, and what is unknown."""
    state = _state(store)
    result = {}
    for dimension in DIMENSIONS:
        charged = [_charged(e).get(dimension) for e in state.values()]
        open_rows = [e['reservation']['amounts'].get(dimension, 0 if dimension in OPTIONAL_DIMENSIONS else None)
                     for e in state.values()
                     if (e.get('settlement') or {}).get('status') not in SETTLED]
        measured = [((e.get('settlement') or {}).get('measured') or {}).get(dimension) for e in state.values()
                    if e.get('settlement')]
        result[dimension] = {
            'ceiling': None if ceilings is None else ceilings.get(dimension),
            'charged': sum(v for v in charged if v is not None),
            'reserved_open': sum(v for v in open_rows if v is not None),
            'measured': sum(v for v in measured if v is not None),
            'unknown': sum(1 for v in charged if v is None) + sum(1 for v in measured if v is None)}
    return result


def reserve(store, *, step_id, attempt, amounts, ceilings, seat=None, parent=None, basis=None):
    """Reserve ``amounts`` for one attempt under the store lock; the same key returns its reservation.

    A refusal names each dimension that would pass its ceiling, or that is unknown against a finite one
    (a measured-after dimension admits an unknown request only while its charged total is below the ceiling).
    """
    if type(amounts) is dict:
        amounts = {**{d: 0 for d in OPTIONAL_DIMENSIONS}, **amounts}
    if type(amounts) is not dict or set(amounts) != set(DIMENSIONS) or not all(_number(v) for v in amounts.values()):
        raise StepHold('reservation_invalid', 'a reservation names every dimension')
    name = key(step_id, attempt, seat)
    with file_lock(lock_path(store, 'budget')):
        state = _state(store)
        if name in state:
            existing = state[name]['reservation']
            if existing['amounts'] != amounts:
                raise StepHold('reservation_changed', f'attempt {name} is already reserved with other amounts')
            existing.setdefault('record_id', existing.get('_record_id'))
            return existing
        charged = {d: 0 for d in DIMENSIONS}
        for entry in state.values():
            for dimension, value in _charged(entry).items():
                if value is not None:
                    charged[dimension] += value
        refused = []
        for dimension in DIMENSIONS:
            ceiling, wanted = ceilings.get(dimension), amounts[dimension]
            if ceiling is None:
                continue
            if wanted is None:
                if dimension not in MEASURED_AFTER or charged[dimension] >= ceiling:
                    refused.append({'dimension': dimension, 'reason': 'unknown_request', 'ceiling': ceiling,
                                    'charged': charged[dimension]})
            elif charged[dimension] + wanted > ceiling:
                refused.append({'dimension': dimension, 'reason': 'ceiling', 'ceiling': ceiling,
                                'charged': charged[dimension], 'requested': wanted})
        if refused:
            reason = 'budget_unknown_request' if all(r['reason'] == 'unknown_request' for r in refused) else \
                'budget_exhausted'
            raise StepHold(reason, 'the reservation passes no ceiling: ' + ', '.join(r['dimension'] for r in refused)
                           + '; the operator may raise the envelope, or the run ends qualified',
                           evidence={'refused': refused, 'key': name})
        record = {'schema_version': 1, 'kind': RESERVATION, 'key': name, 'step_id': step_id, 'attempt': attempt,
                  'seat': seat, 'parent': parent, 'amounts': deepcopy(amounts),
                  'ceilings_sha256': digest(ceilings), 'charged_before': charged, 'basis': deepcopy(basis)}
        record['record_id'] = store.append(RESERVATION, record)
        return record


def check_known_request(store, *, step_id, attempt, amounts, ceilings, seat=None):
    """Refuse a known overage before asking cost authority; this never reserves or grants spend.

    Unknown costs retain their question path. The later atomic reservation checks all dimensions
    again, so concurrent requests cannot spend the same remaining resource after this read.
    """
    name = key(step_id, attempt, seat)
    with file_lock(lock_path(store, 'budget')):
        state = _state(store)
        if name in state:
            if state[name]['reservation']['amounts'] != amounts:
                raise StepHold('reservation_changed', f'attempt {name} is already reserved with other amounts')
            return  # An idempotent replay does not request another allocation.
        charged = {d: 0 for d in DIMENSIONS}
        for entry in state.values():
            for dimension, value in _charged(entry).items():
                if value is not None:
                    charged[dimension] += value
        refused = [{'dimension': d, 'reason': 'ceiling', 'ceiling': ceilings[d],
                    'charged': charged[d], 'requested': wanted}
                   for d, wanted in amounts.items() if wanted is not None and ceilings.get(d) is not None
                   and charged[d] + wanted > ceilings[d]]
        if refused:
            raise StepHold('budget_exhausted', 'the known reservation exceeds the operator envelope',
                           evidence={'refused': refused, 'key': name})


def settle(store, name, *, status, measured=None, evidence=None):
    """Close a reservation once: ``settled`` (observed), ``released`` (nothing started),
    ``ambiguous`` (started, no receipted outcome) or ``reconciled``. Idempotent per status."""
    if status not in (*SETTLED, 'ambiguous'):
        raise ValueError('unknown settlement status')
    with file_lock(lock_path(store, 'budget')):
        state = _state(store)
        if name not in state:
            return None
        current = state[name].get('settlement')
        if current is not None and (current['status'] in SETTLED or current['status'] == status):
            current.setdefault('record_id', current.get('_record_id'))
            return current
        amounts = {**{d: 0 for d in OPTIONAL_DIMENSIONS}, **state[name]['reservation']['amounts']}
        measured = {d: (measured or {}).get(d) for d in DIMENSIONS}
        if status == 'released':
            charged = {d: 0 for d in DIMENSIONS}
        elif status == 'settled':
            # Measured where observed, the whole reservation where not; children are always charged.
            charged = {d: (measured[d] if measured[d] is not None and d != 'children' else amounts[d])
                       for d in DIMENSIONS}
        else:
            charged = dict(amounts)
        record = {'schema_version': 1, 'kind': SETTLEMENT, 'key': name, 'status': status, 'measured': measured,
                  'charged': charged, 'evidence': deepcopy(evidence)}
        record['record_id'] = store.append(SETTLEMENT, record)
        return record


def unsettled_prior(store, step_id, attempt):
    """Earlier attempts of the step that started and have no settled outcome."""
    found = []
    for name, entry in _state(store).items():
        reservation = entry['reservation']
        if reservation['step_id'] != step_id or reservation['attempt'] >= attempt:
            continue
        status = (entry.get('settlement') or {}).get('status')
        if status not in SETTLED:
            found.append({'key': name, 'status': status or 'open'})
    return sorted(found, key=lambda r: r['key'])


# ---- rung and calibration (A07, C02, C13) -------------------------------------------------

def rung_errors(step):
    """The step's requested events within the rung ceiling its approved plan bytes carry."""
    ceiling = ((step.get('parameters') or {}).get('rung_ceiling') or {})
    wanted = (step.get('budget') or {}).get('events')
    limit = ceiling.get('events')
    if wanted is not None and type(limit) in (int, float) and wanted > limit:
        return [{'code': 'rung_ceiling_exceeded', 'rung': step.get('rung'), 'requested': wanted, 'approved': limit}]
    return []


def process_pin(step):
    """What a pilot must share with the production rung: the operation and its declared process identity.

    The plan names the process (``parameters.process_sha256``: model, cards and configuration, without
    the event count or rung); without one, the launch configuration digest stands for it.
    """
    parameters = step.get('parameters') or {}
    declared = parameters.get('process_sha256')
    if type(declared) is str and declared:
        return digest({'operation': step.get('operation'), 'process': declared})
    launch = parameters.get('launch') or {}
    return digest({'operation': step.get('operation'), 'config': launch.get('config_sha256')})


def calibration(store, step):
    """A succeeded pilot of the same operation, process and machine with measured observations, or None."""
    pin, machine = process_pin(step), machine_pin()
    found = None
    for row in records(store, CALIBRATION):
        measured = row.get('measured') or {}
        if (row.get('operation') == step.get('operation') and row.get('process_sha256') == pin
                and row.get('machine_sha256') == machine and row.get('status') == 'succeeded'
                and type(measured.get('events')) in (int, float) and measured['events'] > 0
                and type(measured.get('wall_seconds')) in (int, float)):
            found = row
    return found


def reservation_bound(step, amounts, ceilings, *, branch, signature):
    """A conservative local-launch upper estimate, or None when enforcement cannot establish it.

    A reservation is accounting, not a runtime limiter. Only the ordinary confined launch has
    the watchdog and CPU grant used here. Model spend, event throughput, acquisition and remote
    work need their own enforcement/calibration; a finite ledger entry alone proves none of them.
    """
    unit = ((signature or {}).get('cost') or {}).get('unit')
    launch = (step.get('parameters') or {}).get('launch')
    if (branch != 'launch' or unit not in NON_EVENT_UNITS or signature.get('effects') != []
            or type(launch) is not dict or not launch.get('argv')
            or (step.get('parameters') or {}).get('adapter') is not None
            or pilot_step(step)[0] is not None):
        return None
    # The other local backend advertises cooperative thread settings, not a hard CPU
    # ceiling. Its core-hour reservation cannot stand for an enforced upper estimate.
    if sys.platform != 'linux' or launch.get('backend') not in (None, 'auto', 'bwrap'):
        return None
    if set(amounts) != set(DIMENSIONS) or any(
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
            for value in amounts.values()):
        return None
    wall, cpus = amounts['wall_seconds'], launch.get('cpus', 1)
    if (wall <= 0 or type(cpus) is not int or cpus < 1 or amounts['children'] != 1
            or amounts['core_hours'] != wall * cpus / 3600.0):
        return None
    # No runtime meter bounds these for an arbitrary local launch. They must be absent
    # from its declared work, not merely hidden by the branch's accounting projection.
    unused = ('model_calls', 'tokens', 'cost_usd', 'events', *OPTIONAL_DIMENSIONS)
    share = step.get('budget') or {}
    if (any(amounts[d] != 0 or share.get(d, 0) != 0 for d in unused)
            or share.get('broker_calls', 0) != 0
            or set(share) - set(DIMENSIONS) - {'attempts', 'broker_calls'}):
        return None
    if any(ceiling is not None and (type(ceiling) not in (int, float)
               or not math.isfinite(ceiling) or ceiling < 0 or amounts[d] > ceiling)
           for d, ceiling in ceilings.items()):
        return None
    mechanism = {d: 'not-used-by-local-launch' for d in unused}
    mechanism.update(wall_seconds='controller-watchdog', core_hours='confined-cpu-grant-and-wall-watchdog',
                     children='one-governed-attempt')
    return {'schema_version': 1, 'kind': 'conservative-cost-bound', 'basis': 'approved-reservation',
            'cost_unit': unit, 'amounts': deepcopy(amounts), 'mechanism': mechanism}


def declared_operation_bound(step, amounts, ceilings, *, branch, signature, ceiling, known_launch):
    """A declared wall-cost upper estimate enforced by the ordinary launch watchdog.

    Its scope is wall cost and the confined CPU grant. Event/input allocations remain separately
    reserved; this fact grants no measured event count or forecast calibration credit.
    """
    unit = ((signature or {}).get('cost') or {}).get('unit')
    if (branch != 'launch' or step.get('kind') != 'operate' or not known_launch
            or unit not in (*NON_EVENT_UNITS, 'points', 'events') or ceiling is None
            or ceiling['dimension'] != 'wall_seconds'
            or pilot_step(step)[0] is not None or sys.platform != 'linux'):
        return None
    if set(amounts) != set(DIMENSIONS) or any(
            type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in amounts.values()):
        return None
    share = step.get('budget') or {}
    maximum = share.get('wall_seconds')
    wall = ceiling['amount']
    launch = (step.get('parameters') or {}).get('launch') or {}
    cpus = launch.get('cpus', 1)
    if (type(maximum) not in (int, float) or not math.isfinite(maximum) or not 0 < wall <= maximum
            or wall != amounts['wall_seconds'] or type(cpus) is not int or cpus < 1
            or launch.get('backend') not in (None, 'auto', 'bwrap')
            or amounts['core_hours'] != wall * cpus / 3600.0 or amounts['children'] != 1):
        return None
    unused = ('model_calls', 'tokens', 'cost_usd', 'batch_cpu_hours')
    if (any(amounts[d] != 0 or share.get(d, 0) != 0 for d in unused)
            or share.get('broker_calls', 0) != 0
            or set(share) - set(DIMENSIONS) - {'attempts', 'broker_calls'}
            or any(limit is not None and (type(limit) not in (int, float) or not math.isfinite(limit)
                       or limit < 0 or amounts[d] > limit) for d, limit in ceilings.items())):
        return None
    return {'schema_version': 1, 'kind': 'conservative-cost-bound', 'basis': 'declared-operation-ceiling',
            'cost_unit': unit, 'ceiling_pointer': ceiling['ceiling_pointer'],
            'amounts': {'wall_seconds': wall, 'core_hours': amounts['core_hours']},
            'mechanism': {'wall_seconds': 'controller-watchdog',
                          'core_hours': 'confined-cpu-grant-and-wall-watchdog'}}


def calibration_errors(store, step, *, signoff=None, upper_bound=None, amounts=None):
    """Top-rung cost needs a matched pilot, an enforced upper estimate or operator cost authority."""
    if step.get('rung') not in TOP_RUNGS or step['kind'] not in ('operate', 'acquire'):
        return []
    pilot = calibration(store, step)
    if pilot is not None:
        events = (step.get('budget') or {}).get('events')
        wall = (amounts if amounts is not None else step.get('budget') or {}).get('wall_seconds')
        rate = pilot['measured']['wall_seconds'] / pilot['measured']['events']
        if events is not None and wall is not None and rate * events > wall:
            return [{'code': 'forecast_exceeds_reservation', 'forecast_wall_seconds': rate * events,
                     'reserved_wall_seconds': wall, 'pilot': pilot.get('record_id')}]
        return []
    if signoff is not None or upper_bound is not None:
        return []
    return [{'code': 'uncalibrated_top_rung_cost', 'operation': step.get('operation'), 'rung': step.get('rung'),
             'would_make_possible': 'a succeeded pilot of the same process on this machine, a conservative '
                                    'enforced upper estimate within the operator envelope, or the operator\'s '
                                    'own cost authority for this step'}]


def record_calibration(store, step, *, status, measured):
    """A pilot-rung operation's observed cost, bound to its process and this machine."""
    return store.append(CALIBRATION, {'schema_version': 1, 'kind': CALIBRATION, 'step_id': step['id'],
                                      'operation': step.get('operation'), 'process_sha256': process_pin(step),
                                      'machine_sha256': machine_pin(), 'rung': step.get('rung'), 'status': status,
                                      'measured': deepcopy(measured)})


# ---- the derived pilot rung (the unattended cost default) ---------------------------------

def pilot_id(step_id):
    """The derived pilot's own step identity: its attempt directory and records never meet the full rung's."""
    return f'{step_id[:100]}.pilot'


def pilot_bound(step):
    """``(events, rule)`` for a derived pilot of ``step``, or ``(None, reason)``.

    The bound is the approved step's own pilot declaration (``parameters.pilot.events``, fewer events
    than the top rung), else ``ceil(PILOT_FRACTION * events)`` of the top rung's declared events (at
    least one). It sizes compute only; it is never a physics input, and nothing is derived when the
    step declares no event budget.
    """
    events = (step.get('budget') or {}).get('events')
    if type(events) is not int or events < 1:
        return None, 'top_rung_events_undeclared'
    declared = (step.get('parameters') or {}).get('pilot')
    if declared is not None:
        wanted = declared.get('events') if type(declared) is dict else None
        if type(wanted) is not int or not 1 <= wanted < events:
            return None, 'pilot_declaration_invalid'
        return wanted, 'declared'
    return min(events, max(1, math.ceil(events * PILOT_FRACTION))), 'fraction'


def pilot_step(step):
    """``(derived pilot step, None)`` of an uncalibrated top-rung operation, or ``(None, reason)``.

    The pilot is the same operation and declared process (its ``process_pin`` equals the step's) at
    rung ``pilot`` with the bounded event budget and the step's own wall budget. Its approved launch
    must pass the event count through ``EVENTS_TOKEN``, so the launched command generates the bound;
    a launch that fixes its own count, or a launch the route materialises, derives no pilot.
    """
    if step.get('rung') not in TOP_RUNGS or step.get('kind') not in ('operate', 'acquire'):
        return None, 'not_top_rung'
    events, rule = pilot_bound(step)
    if events is None:
        return None, rule
    wall = (step.get('budget') or {}).get('wall_seconds')
    if type(wall) not in (int, float) or not math.isfinite(wall) or wall <= 0:
        return None, 'pilot_wall_unbounded'
    launch = (step.get('parameters') or {}).get('launch')
    if type(launch) is not dict or type(launch.get('argv')) is not list:
        return None, 'launch_not_declared'
    if EVENTS_TOKEN not in launch['argv']:
        return None, 'launch_event_count_unbound'
    derived = deepcopy(step)
    derived['id'] = pilot_id(step['id'])
    derived['rung'] = PILOT_RUNG
    derived['budget'] = {**(step.get('budget') or {}), 'events': events}
    derived.setdefault('parameters', {})['pilot_of'] = {
        'step_sha256': digest(step), 'rung': step['rung'], 'events': step['budget']['events'], 'bound': events,
        'rule': rule}
    return derived, None


def resolve_events(argv, step):
    """The argv with ``EVENTS_TOKEN`` replaced by the acting step's declared events (unchanged without it)."""
    if EVENTS_TOKEN not in argv:
        return list(argv)
    events = (step.get('budget') or {}).get('events')
    if type(events) is not int or events < 0:
        raise StepHold('launch_event_count_missing', 'a launch that takes its event count needs the step\'s declared '
                       'event budget')
    return [str(events) if word == EVENTS_TOKEN else word for word in argv]
