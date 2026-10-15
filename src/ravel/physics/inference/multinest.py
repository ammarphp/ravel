"""Isolated interface to the external MultiNest Python worker.

The host process validates and records the request, hands it to a supplied
runner for the declared environment interpreter, and reads the JSON result.  It
never imports the GPL Python binding and owns no launch path: the runner is the
admitted, resource-bounded native execution supplied by the caller.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import sys

REQUIRED_SETTINGS = ('n_live', 'sampling_efficiency', 'evidence_tolerance',
                     'constant_efficiency_mode', 'seed')
_EVIDENCE = re.compile(
    r'^\s*(?:nested sampling )?global log-evidence\s*:\s*'
    r'(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*'
    r'\+/-\s*(?P<error>(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*$', re.I)


def configuration(settings):
    """Validate and make the complete external sampler configuration explicit."""
    if type(settings) is not dict:
        raise ValueError('sampler settings must be an object')
    missing = [name for name in REQUIRED_SETTINGS if name not in settings]
    if missing:
        raise ValueError('unrecorded sampler setting: ' + ', '.join(missing))
    if set(settings) != set(REQUIRED_SETTINGS):
        raise ValueError('unknown sampler settings: ' + ', '.join(sorted(set(settings) - set(REQUIRED_SETTINGS))))
    n_live = settings['n_live']
    efficiency = settings['sampling_efficiency']
    tolerance = settings['evidence_tolerance']
    seed = settings['seed']
    if type(n_live) is not int or n_live < 1:
        raise ValueError('n_live must be a positive integer')
    if type(efficiency) not in (int, float) or not math.isfinite(efficiency) or not 0 < efficiency <= 1:
        raise ValueError('sampling_efficiency must be finite in (0, 1]')
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError('evidence_tolerance must be finite and positive')
    if type(settings['constant_efficiency_mode']) is not bool:
        raise ValueError('constant_efficiency_mode must be boolean')
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    return {
        'n_live_points': n_live,
        'sampling_efficiency': float(efficiency),
        'evidence_tolerance': float(tolerance),
        'const_efficiency_mode': settings['constant_efficiency_mode'],
        'seed': seed,
        'recorded_settings': {name: settings[name] for name in REQUIRED_SETTINGS},
    }


def parse_stats(path):
    """Read the final global log evidence from a complete worker ``stats.dat``."""
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except OSError as exc:
        raise ValueError('stats.dat is unavailable') from exc
    matches = [match for line in lines if (match := _EVIDENCE.match(line))]
    if not matches:
        if any('log-evidence' in line.lower() for line in lines):
            raise ValueError('truncated stats.dat evidence row')
        raise ValueError('stats.dat global evidence row missing')
    if len(matches) != 1:
        raise ValueError('stats.dat has ambiguous global evidence rows')
    value, error = (float(matches[0].group(name)) for name in ('value', 'error'))
    if not math.isfinite(value) or not math.isfinite(error) or error < 0:
        raise ValueError('stats.dat evidence values must be finite with nonnegative error')
    return {'evidence_logz': value, 'evidence_logz_error': error}


def run_worker(settings, *, interpreter, runner):
    """Invoke the isolated environment worker through ``runner`` and validate its reply.

    ``runner(argv, input=..., text=True, capture_output=True, check=False)`` must
    return an object with ``returncode``, ``stdout`` and ``stderr``.
    """
    config = configuration(settings)
    worker = Path(__file__).with_name('multinest_worker.py')
    request = {'schema_version': 1, 'settings': config['recorded_settings']}
    completed = runner([str(interpreter), str(worker)], input=json.dumps(request), text=True,
                       capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError('isolated sampler worker failed: ' + completed.stderr.strip())
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError('isolated sampler worker did not return JSON') from exc
    if type(result) is not dict or set(result) != {'evidence_logz', 'evidence_logz_error', 'settings'}:
        raise ValueError('isolated sampler worker returned an invalid result')
    if result['settings'] != config['recorded_settings']:
        raise ValueError('isolated sampler worker settings differ from request')
    if not all(type(result[name]) in (int, float) and math.isfinite(result[name])
               for name in ('evidence_logz', 'evidence_logz_error')) or result['evidence_logz_error'] < 0:
        raise ValueError('isolated sampler worker returned invalid evidence')
    if 'pymultinest' in sys.modules:
        raise RuntimeError('GPL sampler module was imported into the RAVEL host')
    return result


def compare_reference_rows(rows):
    """General three-sigma comparison for supplied reference-evidence rows."""
    if type(rows) is not list or not rows:
        raise ValueError('nonempty reference rows required')
    checks = []
    for row in rows:
        if type(row) is not dict or set(row) != {'reference_logz', 'reference_error', 'observed_logz', 'observed_error'}:
            raise ValueError('reference row fields required')
        values = [row[name] for name in ('reference_logz', 'reference_error', 'observed_logz', 'observed_error')]
        if not all(type(value) in (int, float) and math.isfinite(value) for value in values) or row['reference_error'] < 0 or row['observed_error'] < 0:
            raise ValueError('reference values must be finite with nonnegative errors')
        sigma = math.hypot(row['reference_error'], row['observed_error'])
        checks.append({'difference': row['observed_logz'] - row['reference_logz'],
                       'combined_error': sigma, 'passed': abs(row['observed_logz'] - row['reference_logz']) <= 3 * sigma})
    return {'status': 'passed' if all(row['passed'] for row in checks) else 'failed', 'rows': checks}
