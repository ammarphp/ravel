"""Read-only model attribution and catalogue pricing of the latest provider census.

Only provider-counter sessions supply requests and the four disjoint token counts.
Dispatches and observations supply identities, never replacement usage or prices.
"""
from __future__ import annotations

from copy import deepcopy
import json

from ravel.workflow import role_registry

try:
    from ravel.workflow import model_catalogue
except ImportError:
    model_catalogue = None

TOKEN_KEYS = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')


def _counter(store):
    latest = store.latest('provider-counter')
    if latest is None:
        return {'status': 'unknown', 'sessions': [], 'problems': [{'reason': 'provider_counter_missing'}]}
    return latest['record']


def _identity(row):
    return row.get('node_id'), row.get('attempt')


def _index(store, kind):
    return {_identity(entry['record']): entry['record'] for entry in store.scan(kind)}


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _price(usage, model):
    if model_catalogue is None:
        return {'status': 'catalogue_unavailable', 'cost_usd': None, 'model': model,
                'prices_per_million': None, 'price_basis': 'catalogue unavailable'}
    return model_catalogue.price(usage, model)


def _sessions(store, counter):
    dispatches = _index(store, 'step-dispatch')
    observations = _index(store, 'step-observation')
    rows = []
    for session in counter.get('sessions', []):
        key = _identity(session)
        dispatch = dispatches.get(key)
        observation = observations.get(key, {})
        selection = (dispatch or {}).get('selection') or {}
        seat = (dispatch or {}).get('seat')
        purpose = (dispatch or {}).get('purpose')
        parts = seat.split(':') if isinstance(seat, str) else []
        role = (parts[1] if len(parts) == 3 and parts[0] == 'seat' and parts[1] else purpose) if dispatch else None
        problems = deepcopy(counter.get('problems', [])) if counter.get('status') != 'reported' else []
        card = {}
        if role:
            try:
                card = role_registry.load(role)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                problems.append({'reason': 'role_card_unavailable', 'role': role, 'error': type(exc).__name__})
        card_tier = (card.get('model') or {}).get('tier')
        usage = {k: _count((session.get('usage') or {}).get(k)) for k in TOKEN_KEYS}
        requests = _count(session.get('requests'))
        if requests is None or any(v is None for v in usage.values()):
            problems.append({'reason': 'provider_usage_incomplete', 'node_id': key[0], 'attempt': key[1]})
        observed = (observation.get('model') or {}).get('observed')
        requested = selection.get('model')
        provider_models = session.get('models') or []
        pricing_model = observed
        if provider_models and (len(provider_models) != 1 or provider_models[0] != observed):
            pricing_model = None
            problems.append({'reason': 'provider_model_attribution_incomplete', 'models': provider_models})
        row = {'node_id': key[0], 'attempt': key[1], 'session_id': session.get('session_id'),
               'seat': seat, 'role': role, 'role_family': card.get('family'), 'card_tier': card_tier,
               'selected_tier': selection.get('tier') or card_tier, 'purpose': purpose,
               'step_id': (dispatch or {}).get('step_id'), 'transport': selection.get('transport_id'),
               'model_requested': requested, 'model_observed': observed,
               'family': selection.get('family'), 'effort': selection.get('effort'),
               'requests': requests, 'usage': usage, 'price': _price(usage, pricing_model),
               'counter_status': counter.get('status', 'unknown'), 'problems': problems}
        if dispatch is None:
            row['reason'] = 'dispatch_missing'
            problems.append({'reason': 'dispatch_missing', 'node_id': key[0], 'attempt': key[1]})
        rows.append(row)
    return rows


def sessions(store):
    """Join the latest census by attempt; incomplete-census rows retain its problems.

    Missing dispatches remain unattributed. An empty or missing census supplies no
    rows; ``summary`` retains its status and problems even in that case.
    """
    return _sessions(store, _counter(store))


def _group(rows, *, complete=True):
    unpriced = sum(row['price'].get('status') != 'priced' or row['price'].get('cost_usd') is None for row in rows)
    priced = sum(row['price']['cost_usd'] for row in rows
                 if row['price'].get('status') == 'priced' and row['price'].get('cost_usd') is not None)
    requests = None if any(row['requests'] is None for row in rows) else sum(row['requests'] for row in rows)
    tokens = {k: None if any(row['usage'][k] is None for row in rows)
              else sum(row['usage'][k] for row in rows) for k in TOKEN_KEYS}
    result = {'sessions': len(rows), 'requests': requests if complete else None,
            'tokens': tokens if complete else {k: None for k in TOKEN_KEYS},
            'cost_usd': priced if not unpriced and complete else None,
            'cost_usd_priced_part': priced, 'unpriced': unpriced}
    if not complete:
        result.update(requests_reported_part=requests, tokens_reported_part=tokens)
    return result


def summary(store):
    """Fully priced/reconciled is measured; available subsets are partial; absent evidence is unknown.

    Counts describe the available rows. An incomplete census cannot supply a full
    cost total, even if every available row has a price.
    """
    counter = _counter(store)
    rows = _sessions(store, counter)
    problems = deepcopy(counter.get('problems', []))
    for row in rows:
        problems.extend(row['problems'])
        if row['price'].get('status') != 'priced':
            problems.append({'reason': 'session_unpriced', 'node_id': row['node_id'], 'attempt': row['attempt'],
                             'status': row['price'].get('status')})
    unique = {json.dumps(p, sort_keys=True): p for p in problems}
    problems = list(unique.values())
    complete = counter.get('status') == 'reported' and not counter.get('problems')
    result = {'kind': 'model-cost', 'schema_version': 1,
              'status': 'measured' if complete and not problems else 'partial' if rows else 'unknown',
              'counter_status': counter.get('status', 'unknown'),
              'price_basis': '; '.join(sorted({row['price']['price_basis'] for row in rows})) or 'unavailable',
              'total': _group(rows, complete=complete), 'problems': problems,
              'unpriced_models': sorted({row['model_observed'] or row['model_requested'] or 'unknown'
                                        for row in rows if row['price'].get('status') != 'priced'})}
    for name, field in (('by_role', 'role'), ('by_tier', 'selected_tier'), ('by_model', None)):
        groups = {}
        for row in rows:
            key = row['model_observed'] if field is None else row[field]
            groups.setdefault(key or 'unknown', []).append(row)
        result[name] = {key: _group(group, complete=complete) for key, group in sorted(groups.items())}
    return result


def record(store):
    """Explicitly persist a changed measurement; readers never call this operation."""
    result = summary(store)
    previous = store.latest('model-cost')
    if previous is None or previous['record'] != result:
        store.append('model-cost', result)
    return result
