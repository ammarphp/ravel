"""Private account snapshots and measured-workload model recommendations.

Account windows describe operator-supplied capacity, not dispatch authority. Prior
provider counters describe measured past work; their envelope is a future scenario.
Every proposed allocation passes the existing effective-card capability checks.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
import math
from pathlib import Path

from ravel.workflow import model_catalogue as mc, transport_registry as tr

MAX_INPUT_BYTES = 1 << 20
PLANS = ('included', 'metered', 'local')
UNITS = ('tokens', 'requests', 'usd')


def _read(path):
    """Bound the read and report field errors without echoing private input values."""
    with Path(path).expanduser().open('rb') as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('model usage input exceeds the bounded read')
    try:
        return json.loads(raw)
    except (UnicodeError, ValueError):
        raise ValueError('model usage input requires valid JSON') from None


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('model usage timestamps require an explicit timezone') from None


def validate_context(document):
    keys = {'schema_version', 'kind', 'observed_utc', 'valid_until_utc', 'expected_run_seconds', 'accounts'}
    if (type(document) is not dict or set(document) != keys or type(document['schema_version']) is not int
            or document['schema_version'] != 1 or document['kind'] != 'model-usage-context'):
        raise ValueError('model usage context requires the closed version-1 snapshot fields')
    _time(document['observed_utc'])
    _time(document['valid_until_utc'])
    seconds = document['expected_run_seconds']
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('model usage expected_run_seconds must be finite and positive')
    if type(document['accounts']) is not list or len(document['accounts']) > 64:
        raise ValueError('model usage accounts must be a bounded list')
    seen = set()
    for row in document['accounts']:
        if type(row) is not dict or set(row) != {'transports', 'plan', 'windows'} or row['plan'] not in PLANS:
            raise ValueError('model usage account requires transports, plan and windows')
        transports = row['transports']
        if (type(transports) is not list or not transports or len(transports) > 64
                or any(type(t) is not str or not tr.IDENT.fullmatch(t) for t in transports)
                or len(set(transports)) != len(transports) or seen.intersection(transports)):
            raise ValueError('each model usage transport belongs to exactly one account')
        seen.update(transports)
        if type(row['windows']) is not list or len(row['windows']) > 16:
            raise ValueError('model usage windows must be a bounded list')
        for window in row['windows']:
            if (type(window) is not dict or set(window) != {'unit', 'remaining', 'resets_utc'}
                    or window['unit'] not in UNITS):
                raise ValueError('model usage window requires unit, remaining and resets_utc')
            value = window['remaining']
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0
                                      or (window['unit'] != 'usd' and type(value) is not int)):
                raise ValueError('model usage remaining must be a finite nonnegative amount in its unit')
            if window['resets_utc'] is not None:
                _time(window['resets_utc'])
    return document


def load_context(path):
    return validate_context(_read(path))


def load_prior(path):
    """Read an exported controller model-cost record, retaining its measurement status."""
    document = _read(path)
    if type(document) is not dict or document.get('kind') != 'model-cost' or document.get('schema_version') != 1:
        raise ValueError('prior usage requires an exported version-1 model-cost record')
    return document


def load_run(run_id):
    """Use the controller's reconciled provider counters from an existing run store."""
    from ravel.controller import model_cost
    from ravel.controller.diagnostics.cli import open_store
    store = open_store(run_id)
    try:
        with store.snapshot():
            return model_cost.summary(store)
    finally:
        store.close()


def _demand(records):
    """Use the largest measured per-tier demand; incomplete histories stay unknown."""
    if not records:
        return None, ['measured_prior_usage_missing']
    result = {tier: {key: 0 for key in (*mc._USAGE_KEYS, 'requests')} for tier in tr.TIERS}
    for record in records:
        if (type(record) is not dict or record.get('kind') != 'model-cost' or record.get('schema_version') != 1
                or record.get('status') != 'measured' or record.get('counter_status') != 'reported'
                or record.get('problems') != [] or type(record.get('by_tier')) is not dict
                or set(record['by_tier']) - set(tr.TIERS)):
            return None, ['prior_usage_unreconciled']
        if not record['by_tier']:
            return None, ['prior_usage_empty']
        for tier, row in record['by_tier'].items():
            if type(row) is not dict or type(row.get('tokens')) is not dict:
                return None, ['prior_usage_incomplete']
            values = {**{key: row['tokens'].get(key) for key in mc._USAGE_KEYS}, 'requests': row.get('requests')}
            if any(type(value) is not int or value < 0 for value in values.values()):
                return None, ['prior_usage_incomplete']
            for key, value in values.items():
                result[tier][key] = max(result[tier][key], value)
    return result, []


def _options(preferences, alternatives, documents):
    indexed = {d['id']: d for d in documents}
    result = {tier: [] for tier in tr.TIERS}
    for preference in (preferences, *alternatives):
        for tier in tr.TIERS:
            for transport in preferences['transport_preference']:
                model = preference['tier_models'][tier].get(transport)
                document = indexed.get(transport)
                option = (transport, model)
                if (document is not None and model and option not in result[tier]
                        and not tr.catalogue_requirement_problem(model, tier, None)
                        and not tr.model_problem(document, model, preferences.get('model_families'))):
                    result[tier].append(option)
    return result


def _allocation(preferences, choices):
    return {**deepcopy(preferences), 'tier_models': {tier: {transport: model}
            for tier, (transport, model) in zip(tr.TIERS, choices)}}


def _score(choices, context, demand, now):
    """Aggregate shared accounts before checking every simultaneous reset window."""
    accounts = context['accounts']
    owners = {t: index for index, account in enumerate(accounts) for t in account['transports']}
    grouped, unknown_transports = {}, set()
    for tier, (transport, model) in zip(tr.TIERS, choices):
        if transport not in owners:
            unknown_transports.add(transport)
        owner = owners.get(transport, ('unknown', transport))
        row = grouped.setdefault(owner, {'tokens': 0, 'requests': 0, 'usd': 0.0})
        row['tokens'] += sum(demand[tier][key] for key in mc._USAGE_KEYS)
        row['requests'] += demand[tier]['requests']
        cost = mc.price(demand[tier], model)['cost_usd']
        row['usd'] = None if cost is None or row['usd'] is None else row['usd'] + cost
    unknown, pressure, marginal, checks = len(unknown_transports), 0.0, 0.0, []
    for owner, usage in grouped.items():
        if not isinstance(owner, int):
            marginal += usage['usd'] or 0
            continue
        account = accounts[owner]
        if not account['windows']:
            unknown += 1
        for window in account['windows']:
            remaining = window['remaining']
            reset = _time(window['resets_utc']) if window['resets_utc'] is not None else None
            amount = usage[window['unit']]
            known = remaining is not None and reset is not None and reset > now and amount is not None
            if not known:
                unknown += 1
                checks.append({'account': owner, 'unit': window['unit'], 'status': 'unknown'})
                continue
            if amount > remaining:
                return None
            # Pace the scenario across the remaining window. A reset grants no
            # assumed replenishment; only the recorded remaining capacity is used.
            paced = remaining * min(1.0, context['expected_run_seconds'] / (reset - now).total_seconds())
            pressure += max(0.0, amount - paced) / max(1.0, paced)
            checks.append({'account': owner, 'unit': window['unit'], 'status': 'fits_scenario',
                           'demand': amount, 'remaining': remaining, 'paced_share': paced,
                           'resets_utc': window['resets_utc']})
        if account['plan'] == 'metered':
            if usage['usd'] is None:
                unknown += 1
            else:
                marginal += usage['usd']
    return (unknown, pressure, marginal), checks


def recommend(preferences, *, documents, context=None, prior_runs=(), alternatives=(), now=None):
    """Choose a feasible capable allocation using only supplied metadata and counters."""
    from .models_setup import static_role_coverage
    now = now or datetime.now(timezone.utc)
    demand, reasons = _demand(prior_runs)
    report = {'schema_version': 1, 'kind': 'model-usage-recommendation', 'status': 'unknown',
              'basis': 'measured prior-run envelope; future workload scenario',
              'prior_run_count': len(prior_runs), 'demand': demand, 'reasons': reasons,
              'prior_usage_sha256': [hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                                     for row in prior_runs]}
    if context is None:
        report['reasons'] = [*reasons, 'account_snapshot_missing']
        return deepcopy(preferences), report
    validate_context(context)
    report['snapshot_sha256'] = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    if not (_time(context['observed_utc']) <= now < _time(context['valid_until_utc'])):
        report['reasons'] = [*reasons, 'account_snapshot_outside_validity']
        return deepcopy(preferences), report
    if demand is None or not context['accounts']:
        report['reasons'] = reasons or ['account_capacity_missing']
        return deepcopy(preferences), report
    options = _options(preferences, alternatives, documents)
    if any(not rows for rows in options.values()):
        report['reasons'] = ['tier_candidates_require_configuration']
        return deepcopy(preferences), report
    if math.prod(len(rows) for rows in options.values()) > 65536:
        raise ValueError('model usage allocation exceeds the bounded search; select preferred provider families')
    ranked = []
    for choices in product(*(options[tier] for tier in tr.TIERS)):
        score = _score(choices, context, demand, now)
        if score is not None:
            changes = sum(preferences['tier_models'][tier].get(transport) != model
                          for tier, (transport, model) in zip(tr.TIERS, choices))
            ranked.append((score[0], changes, choices, score[1]))
    # Retain funded preset models; alternatives resolve measured capacity pressure.
    # Provider mix still reflects account plans and prices within that preference.
    ranked.sort(key=lambda row: (row[0][0], row[0][1], row[1], row[0][2]))
    for score, changes, choices, checks in ranked:
        candidate = _allocation(preferences, choices)
        if static_role_coverage(candidate, documents)['uncovered']:
            continue
        report.update(status='recommended', checks=checks, reasons=[],
                      unknown_capacity_components=score[0], pacing_pressure=score[1],
                      projected_metered_usd=score[2], preset_model_changes=changes,
                      selected={tier: {'transport': transport, 'model': model}
                                for tier, (transport, model) in zip(tr.TIERS, choices)})
        return candidate, report
    raise ValueError('model usage account capacity and role requirements need a fresh snapshot '
                     'or an alternative capable provider')
