"""Recalibrate engagement projections from reconciled per-session provider usage."""
from __future__ import annotations

import argparse
from copy import deepcopy
import difflib
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

from ravel.controller import model_cost
from ravel.controller.store import RunStore, StoreError, store_root
from ravel.paths import package_data_path

LEVELS = {'low': .2, 'central': .5, 'high': .8}
# First matching category wins. Role-card family is distinct from model family.
# Check-in seats precede review purpose; consult precedes judgment-tier production.
CATEGORY_RULES = {
    'checkin': {'families': ('rdj', 'checkin', 'check-in'), 'role_prefixes': ('rdj',),
                'seat_prefixes': ('checkin', 'check-in'), 'step_prefixes': ('checkin', 'check-in')},
    'review': {'purpose': 'review'},
    'consult': {'family': 'consult'},
    'judgment': {'card_tier': 'judgment', 'purpose': 'producer'},
    'producer': {},
}
PRICE_TOKENS = {'uncached': ('input_tokens', 'input'), 'write': ('cache_creation_input_tokens', 'cache_write'),
                'read': ('cache_read_input_tokens', 'cache_read'), 'output': ('output_tokens', 'output')}


def calibration_path():
    return package_data_path('controller', 'engagement', 'calibration.json')


def installed_calibration():
    return json.loads(calibration_path().read_text(encoding='utf-8'))


def category(row):
    """Classify joined dispatch/card metadata using the ordered rules above."""
    for name, rule in CATEGORY_RULES.items():
        if name == 'checkin':
            if (row.get('role_family') in rule['families']
                    or (row.get('role') or '').startswith(rule['role_prefixes'])
                    or (row.get('seat') or '').startswith(rule['seat_prefixes'])
                    or (row.get('step_id') or '').startswith(rule['step_prefixes'])):
                return name
        elif all(row.get('role_family' if key == 'family' else key) == value for key, value in rule.items()):
            return name
    return 'producer'


def _percentiles(values):
    """Linear interpolation at (N - 1) * p, rounded upward after interpolation."""
    values = sorted(values)
    result = {}
    for level, fraction in LEVELS.items():
        position = (len(values) - 1) * fraction
        index = math.floor(position)
        upper = min(index + 1, len(values) - 1)
        result[level] = math.ceil(values[index] + (position - index) * (values[upper] - values[index]))
    return result


def _output_reference(calibration, name):
    return {level: value[name] if isinstance(value, dict) else value
            for level in LEVELS for value in [calibration['parameters'][level]['output_per_call']]}


def measure(stores):
    """Use available valid sessions; preserve undersampled categories and unpriced rates.

    Zero-call sessions have no defined output per call and cannot calibrate a
    category. Missing dispatch/card metadata cannot establish its category.
    Diagnostics retain those rows in the digest and session/run census.
    """
    installed = installed_calibration()
    rows, problems, seen = [], [], set()
    for store in stores:
        identity = str(store.root.resolve())
        if identity in seen:
            continue
        seen.add(identity)
        counter = store.latest('provider-counter')
        if counter is None:
            problems.append({'run_id': store.run_id, 'reason': 'provider_counter_missing'})
        else:
            problems.extend({'run_id': store.run_id, **p} for p in counter['record'].get('problems', []))
        rows.extend({'run_id': store.run_id, **row} for row in model_cost.sessions(store))
    rows.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(',', ':')))
    raw = json.dumps(rows, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    calls, output, insufficient = deepcopy(installed['calls']), {}, []
    for name in CATEGORY_RULES:
        selected = [row for row in rows if row['role'] is not None and row['card_tier'] is not None
                    and row['requests'] is not None and row['requests'] > 0
                    and all(value is not None for value in row['usage'].values()) and category(row) == name]
        if len(selected) < 5:
            insufficient.append(name)
            output[name] = _output_reference(installed, name)
        else:
            calls[name] = _percentiles([row['requests'] for row in selected])
            output[name] = _percentiles([row['usage']['output_tokens'] / row['requests'] for row in selected])
    prices = deepcopy(installed['prices_per_million'])
    priced = bool(rows) and all(row['price'].get('status') == 'priced' for row in rows)
    if priced:
        for name, (token, price_key) in PRICE_TOKENS.items():
            denominator = sum(row['usage'][token] for row in rows)
            if denominator:
                prices[name] = sum(row['usage'][token] * row['price']['prices_per_million'][price_key]
                                   for row in rows) / denominator
    basis = f'measured from {len(rows)} sessions of {len(seen)} runs; digest {sha256(raw).hexdigest()}'
    return {'sessions': len(rows), 'runs': len(seen), 'calls': calls, 'output_per_call': output,
            'prices_per_million': prices, 'basis': basis,
            'price_basis': 'measured token-weighted catalogue prices' if priced else
                           'measured usage; installed price reference retained because pricing is incomplete',
            'insufficient': insufficient, 'problems': problems}


def apply(calibration, measurement):
    """Replace measured dimensions on a copy, preserving all other projection parameters."""
    result = deepcopy(calibration)
    result['calls'] = deepcopy(measurement['calls'])
    for level in LEVELS:
        result['parameters'][level]['output_per_call'] = {
            name: values[level] for name, values in measurement['output_per_call'].items()}
    for key in ('prices_per_million', 'basis'):
        result[key] = deepcopy(measurement[key])
    result['price_basis'] = measurement.get('price_basis', 'measured token-weighted catalogue prices')
    return result


def _encode(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n'


def _source_checkout(path):
    if 'site-packages' in path.resolve().parts or 'dist-packages' in path.resolve().parts:
        return False
    return any((parent / 'pyproject.toml').is_file()
               and path.resolve() == parent / 'src/ravel/data/controller/engagement/calibration.json'
               and (parent / 'scripts/maintenance/build_engagement_envelopes.py').is_file()
               for parent in path.resolve().parents)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', nargs='+', required=True, metavar='RUN_ID')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    try:
        path = Path(calibration_path())
        if args.write and not _source_checkout(path):
            print('recalibration writes require a source checkout; installed package data is read-only', file=sys.stderr)
            return 2
        root = store_root()
        stores = []
        for run_id in dict.fromkeys(args.runs):
            if not (root / run_id / 'run.json').is_file():
                raise StoreError(f'no controller run {run_id} in the operator store')
            stores.append(RunStore(run_id, root=root))
        calibration = installed_calibration()
        measurement = measure(stores)
        updated = apply(calibration, measurement)
        diff = ''.join(difflib.unified_diff(_encode(calibration).splitlines(keepends=True),
                                           _encode(updated).splitlines(keepends=True),
                                           fromfile='installed', tofile='measured'))
        print(_encode({'measurement': measurement, 'diff': diff}), end='')
        if args.write:
            path.write_text(_encode(updated), encoding='utf-8')
            print('Run scripts/maintenance/build_engagement_envelopes.py, then '
                  'scripts/maintenance/build_engagement_envelopes.py --check.')
        return 1 if args.check and updated != calibration else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('recalibration refused: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
