"""Per-attempt structural usage floors and separately labelled cost projections."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from importlib.resources import files
import math

from .records import CHECK, DECISION, ESCALATION, EngagementRefused, append, current_tier, data, digest, latest, rows

METRICS = ('sessions', 'calls', 'input_tokens', 'output_tokens', 'cost_usd')
COMPLETED = ('completed', 'succeeded', 'ok')
# Reserve 25% above the high projection (which already includes calibrated retries).
# Intake precedes the fact-based tier decision, so an unspecified tier reserves full.
DEFAULT_MARGIN = .25


def installed_projection():
    """Read a content-pinned projection; changed inputs require regeneration, never a cheaper tier."""
    try:
        return _installed_projection()
    except EngagementRefused:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise EngagementRefused('engagement projection unavailable: ' + str(exc)) from exc


def _installed_projection():
    installed = data('envelopes.json')
    if installed.get('status') != 'ready' or not installed.get('routes'):
        raise EngagementRefused('engagement projection unavailable; rebuild or request budget authority')
    if installed.get('sha256') != digest({k: v for k, v in installed.items() if k != 'sha256'}):
        raise EngagementRefused('engagement projection digest mismatch')
    if installed.get('calibration_sha256') != digest(data('calibration.json')):
        raise EngagementRefused('engagement calibration stale; rebuild before deriving budgets')
    policy = data('policy.json')
    if (policy.get('sha256') != digest({k: v for k, v in policy.items() if k != 'sha256'})
            or installed.get('policy_sha256') != policy.get('sha256')):
        raise EngagementRefused('engagement policy stale; rebuild before deriving budgets')
    root = files('ravel')
    pins = installed.get('source_pins', {})
    required = {'instructions/catalogue.json', 'instructions/manifests.json', 'routes', 'capabilities'}
    if not required <= pins.keys():
        raise EngagementRefused('engagement source inventory unavailable')
    for name, expected in pins.items():
        if name in ('builder', 'routes', 'capabilities'):
            continue  # Maintenance scripts need not be installed in a wheel.
        if ('..' in name.split('/') or not name.startswith(
                ('instructions/', 'roles/', 'methods/', 'code/instructions/', 'code/engagement/'))):
            raise EngagementRefused('engagement source inventory invalid')
        path = root.joinpath('controller', name[5:]) if name.startswith('code/') else root.joinpath('data', name)
        if sha256(path.read_bytes()).hexdigest() != expected:
            raise EngagementRefused('engagement source stale: ' + name)
    capability_pins = pins['capabilities']
    capability_required = {'workflow/capability_catalogue.py', 'data/knowledge/atlas.json',
                           'data/operation_signatures.json', 'data/backends/census.json'}
    if not isinstance(capability_pins, dict) or not capability_required <= capability_pins.keys():
        raise EngagementRefused('engagement capability inventory unavailable')
    for name, expected in capability_pins.items():
        if ('..' in name.split('/') or name.startswith('/') or '\\' in name
                or not name.startswith(('workflow/', 'physics/', 'data/', 'controller/', 'plotting/', 'validation/', 'setup/'))
                and name not in ('cli.py', 'analysis_catalog.py')):
            raise EngagementRefused('engagement capability inventory invalid')
        if sha256(root.joinpath(name).read_bytes()).hexdigest() != expected:
            raise EngagementRefused('engagement capability source stale: ' + name)
    routes = root.joinpath('data/controller/routes')
    actual = {p.name: sha256(p.read_bytes()).hexdigest() for p in routes.iterdir() if p.name.endswith('.json')}
    if actual != pins.get('routes'):
        raise EngagementRefused('engagement route inventory stale; rebuild before deriving budgets')
    return installed


def defaults(route, tier='full'):
    """Ceil the selected route/tier high bound plus 25%, including declared reservations.

    Before routing, use the dimension-wise maximum of the installed routes at full.
    Unknown named routes and stale inputs refuse; operator ceilings are applied by intake.
    A route descriptor may carry the already selected tier; otherwise full is conservative.
    """
    from .records import TIERS
    if isinstance(route, dict):
        tier = route.get('tier', tier)
        route = route.get('id')
    if tier not in TIERS:
        raise EngagementRefused('unknown engagement budget tier')
    installed = installed_projection()
    names = [route] if route is not None else list(installed['routes'])
    amounts = {'children': 0, 'model_calls': 0, 'tokens': 0}
    for name in names:
        entry = installed['routes'].get(name, {}).get(tier)
        if not entry or entry.get('status') != 'ready':
            raise EngagementRefused('engagement route projection unavailable: ' + str(name))
        high = entry.get('high', {})
        if not all(number(high.get(k)) for k in METRICS):
            raise EngagementRefused('engagement high projection invalid')
        values = {'children': high['sessions'], 'model_calls': high['calls'],
                  'tokens': high['input_tokens'] + high['output_tokens']}
        for key, value in entry.get('reservations', {}).items():
            if key not in values or not number(value):
                raise EngagementRefused('engagement reservation projection invalid')
            values[key] = max(values[key], value)
        for key, value in values.items():
            amounts[key] = max(amounts[key], math.ceil(value * (1 + DEFAULT_MARGIN)))
    return amounts


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def identity(row):
    return (row.get('node_id') or row.get('step_id'), row.get('seat'), row.get('attempt'))


def measured(usage):
    if not isinstance(usage, dict) or usage.get('reported') is not True:
        return None
    calls, output = usage.get('turns'), usage.get('output_tokens')
    if type(calls) is not int or calls < 0 or type(output) is not int or output < 0:
        return None
    raw = usage.get('raw')
    if isinstance(raw, dict):
        parts = [raw.get(k) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')]
        if not all(type(v) is int and v >= 0 for v in parts):
            return None
        total = sum(parts)
        # The step graph's total input already includes cache; never add the raw split to it again.
        if usage.get('input_tokens') != total:
            return None
    else:
        total = usage.get('input_tokens')
    if type(total) is not int or total < 0:
        return None
    return {'calls': calls, 'input_tokens': total, 'output_tokens': output,
            'cost_usd': usage.get('cost_usd') if number(usage.get('cost_usd')) else None}


def evaluate(dispatches, observations, deliveries, *, expected=None, broker=None, stage='deliver', thresholds=None):
    if stage not in ('wave', 'deliver'):
        raise EngagementRefused('envelope stage must be wave or deliver')
    thresholds = thresholds or data('policy.json')['thresholds']
    failures, unknown, session_rows, released = [], [], [], []
    floors = {key: {'status': 'ok', 'failures': []} for key in ('H1', 'H2', 'H3', 'H4', 'H5')}
    def fail(floor, seat, reason, *, missing=False, holds=True):
        row = {'floor': floor, 'seat': seat, 'reason': reason, 'holds': holds}
        floors[floor]['failures'].append(row)
        floors[floor]['status'] = 'unknown' if missing and floors[floor]['status'] == 'ok' else 'below_floor'
        (unknown if missing else failures).append(row)
    keys = set()
    seen_sessions = set()
    for dispatched in dispatches:
        key = identity(dispatched)
        seat = f"{key[0]}:{key[1]}:{key[2]}"
        if key in keys:
            fail('H1', seat, 'duplicate dispatch identity')
            continue
        keys.add(key)
        found = [o for o in observations if identity(o) == key]
        if not found:
            fail('H1', seat, 'missing session observation')
            continue
        if len(found) != 1:
            fail('H1', seat, 'multiple observations for one attempt')
            continue
        observation = found[0]
        # Gaps on a completed attempt hold the next wave. An attempt that did not complete is still
        # accounted and blocks acceptance, but its own failure path handles the step; it holds nothing.
        settled = observation.get('status') in COMPLETED or observation.get('final_record_returned') is True
        usage = measured(observation.get('usage'))
        if observation.get('status') == 'refused' and (observation.get('usage') or {}).get('reported') is not True:
            released.append(seat)  # refused before its session existed: no session, nothing consumed
            continue
        session = observation.get('session_id')
        if session and session in seen_sessions:
            fail('H1', seat, 'reused session identity')
            continue
        if not session:
            fail('H1', seat, 'missing session identity', missing=not settled, holds=settled)
            continue
        seen_sessions.add(session)
        if usage is None:
            fail('H1', seat, 'transport usage unreported or invalid', missing=True, holds=settled)
            continue
        row = {**usage, 'seat': seat, 'session_id': session, 'sessions': 1}
        if usage['cost_usd'] is None:
            unknown.append({'floor': 'usage', 'seat': seat, 'reason': 'cost unreported', 'holds': False})
        packet_rows = [d for d in deliveries if identity(d) == key and d.get('session', session) == session]
        packet_tokens = dispatched.get('packet_tokens')
        packet_sha = dispatched.get('packet_sha256')
        if len(packet_rows) != 1 or not packet_sha or packet_rows[0].get('packet_sha256') != packet_sha:
            fail('H2', seat, 'missing or inconsistent instruction delivery', missing=True, holds=settled)
        else:
            delivered_tokens = packet_rows[0].get('packet_tokens')
            if not number(packet_tokens):
                packet_tokens = delivered_tokens
            if not number(packet_tokens) or packet_tokens <= 0 or (delivered_tokens is not None and delivered_tokens != packet_tokens):
                fail('H2', seat, 'packet size unreported or inconsistent', missing=True, holds=settled)
            elif usage['input_tokens'] < thresholds['packet_fraction'] * packet_tokens:
                fail('H2', seat, 'input below packet floor', holds=settled)
        producer = dispatched.get('purpose', 'producer' if dispatched.get('seat') in (None, 'producer') else 'review') == 'producer'
        minimum = 2 if producer and settled else 1
        if usage['calls'] < minimum:
            fail('H3', seat, f'fewer than {minimum} model calls', holds=settled)
        session_rows.append(row)
    for observation in observations:
        if identity(observation) not in keys:
            fail('H1', str(identity(observation)), 'observation has no dispatch')
    totals = {m: sum(r[m] for r in session_rows if r[m] is not None) for m in METRICS}
    if any(r['cost_usd'] is None for r in session_rows):
        totals['cost_usd'] = None
    if len(session_rows) >= 4 and totals['calls']:
        for row in session_rows:
            if row['calls'] / totals['calls'] > thresholds['max_call_share']:
                fail('H4', row['seat'], 'session exceeds call concentration floor')
    reconciliation = {'available': broker is not None}
    if broker is not None:
        requests = broker.get('requests')
        # Retry allowance is transport evidence, never a broker/caller allowance.
        retries = sum(o.get('transport_retries', 0) for o in observations
                      if type(o.get('transport_retries', 0)) is int and o.get('transport_retries', 0) >= 0)
        reconciliation.update(requests=requests, controller_calls=totals['calls'], transport_retries=retries)
        if type(requests) is not int or requests < 0:
            fail('H5', 'broker', 'broker request count invalid', missing=True)
        elif requests != totals['calls'] + retries:
            fail('H5', 'broker', 'broker requests differ from attributed calls and transport retries')
        if 'tokens' in broker:
            reconciliation['tokens'] = broker['tokens']
            tokens = totals['input_tokens'] + totals['output_tokens']
            if not number(broker['tokens']):
                fail('H5', 'broker', 'broker token count invalid', missing=True)
            elif abs(broker['tokens'] - tokens) > thresholds['broker_token_tolerance'] * max(tokens, 1):
                fail('H5', 'broker', 'broker tokens differ from attributed tokens')
    flags = []
    # Full-run expected lows do not apply to an unfinished wave.
    if expected and expected.get('status') == 'ready':
        if stage == 'deliver':
            for metric in ('calls', 'input_tokens'):
                if totals[metric] < thresholds['far_below'] * expected['low'][metric]:
                    flags.append({'status': 'far_below', 'metric': metric})
            if len(session_rows) < expected['floor']['sessions']:
                fail('H1', 'run', 'fewer observed sessions than required seat floor')
        for metric in METRICS:
            if totals[metric] is not None and totals[metric] > thresholds['above_ceiling'] * expected['high'][metric]:
                flags.append({'status': 'above_ceiling', 'metric': metric})
    else:
        unknown.append({'floor': 'projection', 'seat': 'run', 'reason': 'envelope unavailable', 'holds': False})
    if not dispatches and (not expected or expected.get('floor', {}).get('sessions', 1) > 0):
        fail('H1', 'run', 'dispatch census empty')
    status = ('below_floor' if failures else 'unknown' if unknown else
              'above_ceiling' if any(f['status'] == 'above_ceiling' for f in flags) else
              'far_below' if flags else 'ok')
    labels = []
    if failures:
        labels.append('ENGAGEMENT BELOW FLOOR')
    if unknown:
        labels.append('USAGE UNKNOWN')
    if any(f['status'] == 'above_ceiling' for f in flags):
        labels.append('ENGAGEMENT ABOVE CEILING')
    if any(f['status'] == 'far_below' for f in flags):
        labels.append('ENGAGEMENT FAR BELOW EXPECTED')
    # Missing session evidence holds like a breach; an unavailable projection or price is statistical:
    # it is labelled and blocks acceptance, but never holds a wave.
    return {'stage': stage, 'status': status, 'observed': totals, 'expected': deepcopy(expected),
            'floors': floors, 'failures': failures, 'unknown': unknown, 'flags': flags,
            'broker': reconciliation, 'sessions': session_rows, 'released': released, 'labels': labels,
            'hold': any(row['holds'] for row in failures + unknown), 'accepted_allowed': not (failures or unknown),
            'notify': bool(flags or failures or unknown)}


JUDGMENT_ROUTE = 'judgment'
# The check-ins whose effect-authorizing answer approves a scientific plan (and binds its envelope).
APPROVING = ('approve_plan', 'deviation')


def envelope_binding(decision):
    """The digest an approval of ``decision`` binds for a plan-built envelope (a judgment plan), or None.

    Installed route projections are content-pinned in the package; a plan's own projection
    (``builder.plan_projection``) is pinned only by the authority that approved the plan it projects."""
    envelopes = (decision or {}).get('envelopes') or {}
    if not envelopes or any(e.get('source') != 'plan' for e in envelopes.values()):
        return None
    return digest({'scientific_plan_sha256': decision['scientific_plan_sha256'], 'envelopes': envelopes})


def approved_binding(store, decision, binding):
    """Whether an effect-authorizing plan approval of the decision's plan binds ``binding`` in its subject."""
    for row in rows(store, 'authority'):
        pins = (row.get('subject') or {}).get('pins') or {}
        if (row.get('kind') in APPROVING and row.get('authorizes_effects') is True
                and pins.get('plan_sha256') == decision.get('scientific_plan_sha256')
                and pins.get('engagement_envelope_sha256') == binding):
            return True
    return False


def check_envelope(store, stage, broker=None):
    decision = latest(store, DECISION)
    tier = current_tier(store)
    expected = (decision or {}).get('envelopes', {}).get(tier)
    binding = envelope_binding(decision)
    if binding is not None and not approved_binding(store, decision, binding):
        expected = None  # a plan's own projection that no approval bound is no envelope
    dispatches, observations = rows(store, 'step-dispatch'), rows(store, 'step-observation')
    deliveries = [r for r in rows(store, 'instruction-delivery') if r.get('kind') == 'instruction-delivery-session']
    # Settlements are corroboration, never replacements for a missing session observation.
    settlements = rows(store, 'budget-settlement')
    result = evaluate(dispatches, observations, deliveries, expected=expected, broker=broker, stage=stage)
    result.update(tier=tier, decision_id=(decision or {}).get('record_id'),
                  escalation_sha256=digest(rows(store, ESCALATION)),
                  usage_sha256=digest({'dispatches': dispatches, 'observations': observations,
                                       'deliveries': deliveries, 'settlements': settlements}),
                  evidence_sha256=digest({'dispatches': dispatches, 'observations': observations,
                                          'deliveries': deliveries, 'settlements': settlements, 'broker': broker}))
    result['settlement_ids'] = [r['record_id'] for r in settlements]
    return append(store, CHECK, result)


def project(sessions, calibration):
    """Design model, summed over actual built packets; no fitted task constants."""
    totals = {level: {m: 0 for m in METRICS} for level in ('low', 'central', 'high')}
    floor = {'sessions': sum(not s.get('conditional') for s in sessions),
             'input_tokens': math.ceil(.8 * sum(s['packet_tokens'] for s in sessions if not s.get('conditional'))),
             'calls': sum(1 if s['category'] != 'producer' else 2 for s in sessions if not s.get('conditional')),
             'output_tokens': 0, 'cost_usd': 0}
    for level in totals:
        for session in sessions:
            if session.get('conditional') and level == 'low':
                continue
            params = calibration['parameters'][level]
            n = calibration['calls'][session['category']][level]
            packet = session['packet_tokens'] * params['tau']
            writes = params['S'] + packet + (n - 1) * params['delta']
            reads = (n - 1) * (params['S'] + packet) + params['delta'] * n * (n - 1) / 2
            per_call = params['output_per_call']
            if isinstance(per_call, dict):
                per_call = per_call[session['category']]
            output = n * per_call + params['tau_ack'] * session['duty_units'] * calibration['ack_tokens_per_unit'] + params['record_tokens']
            price = calibration['prices_per_million']
            cost = (writes * price['write'] + reads * price['read'] + output * price['output']) / 1e6
            values = {'sessions': 1, 'calls': n, 'input_tokens': writes + reads, 'output_tokens': output, 'cost_usd': cost}
            for metric in METRICS:
                totals[level][metric] += values[metric]
        if level == 'high' and sessions:
            # Two complete retries of the most expensive packet, including its output and call budget.
            maximum = max(sessions, key=lambda s: s['packet_tokens'])
            retry_cal = deepcopy(calibration)
            retry_cal['high_retries'] = 0
            if calibration['high_retries']:
                retry = project([maximum], retry_cal)['high']
                for metric in METRICS:
                    totals[level][metric] += calibration['high_retries'] * retry[metric]
        for metric in METRICS:
            totals[level][metric] = round(max(floor[metric], totals[level][metric]), 6)
    return {'status': 'ready', 'floor': floor, **totals}


def budget_projection(expected, remaining):
    if not expected or expected.get('status') != 'ready':
        return {'class': 'R3', 'action': 'spend_above_ceiling', 'reason': 'projection unknown'}
    amounts = {'children': expected['high']['sessions'], 'model_calls': expected['high']['calls'],
               'tokens': expected['high']['input_tokens'] + expected['high']['output_tokens'],
               'cost_usd': expected['high']['cost_usd']}
    exceeded = [k for k, v in amounts.items() if k in remaining
                and not (k == 'cost_usd' and remaining[k] is None)
                and (not number(remaining[k]) or v > remaining[k])]
    return {'class': 'R3', 'action': 'spend_above_ceiling', 'dimensions': exceeded} if exceeded else None
