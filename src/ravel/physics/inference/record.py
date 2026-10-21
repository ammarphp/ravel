"""The ``inference.json`` record shared by every inference engine.

Fields:

- ``engine``: the mode and engine variant that produced the record;
- ``statistic``: ``origin`` is ``prescribed`` (the requester's statistic, recorded
  verbatim in ``verbatim`` and as a machine ``definition``), ``default`` (RAVEL's
  95% CLs for an exclusion request without a prescribed statistic) or
  ``not-applicable`` (formulas, morphing);
- ``parameters``: names, units and natural-language labels;
- ``results``: a list of quantities, each with ``quantity`` (one of QUANTITIES),
  ``role`` (``primary``, ``companion`` or ``diagnostic``) and its values;
- ``grid``: the evaluated grid or points;
- ``diagnostics``: numerical evidence (fit status, condition numbers, brackets);
- ``inputs``: path and sha256 of every input file;
- ``requester_assumptions``: values supplied by the requester, as stated;
- ``limitations``: what the record does not establish;
- ``review``: threshold overrides (each with a recorded basis) and declared
  references, when supplied;
- ``computed_checks``: deterministic fit and scan alarms
  (``ravel.validation.regression_triggers``), each ``pass``, ``warn`` or ``fail``;
  ``computed_check_summary`` counts them. Scientific review recomputes them from
  the retained record and refuses a scientific claim while one fails.

Nonfinite numbers are written as null with their positions listed by the engine.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1
QUANTITIES = ('grid-values', 'contour', 'morph-coefficients', 'morph-closure', 'delta-nll-region',
              'delta-nll-scan', 'best-fit', 'significance', 'cls-limit', 'cls-values', 'fitted-parameters',
              'post-fit-predictions', 'toy-p-values', 'applicability', 'mc-adequacy', 'systematics',
              'goodness-of-fit', 'model-construction', 'statistics')
ROLES = ('primary', 'companion', 'diagnostic')
ORIGINS = ('prescribed', 'default', 'not-applicable')


def clean(value):
    """JSON-safe copy: numpy to Python, nonfinite floats to None."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (int, str)):
        return value
    raise TypeError(f'value of type {type(value).__name__} is not JSON-serialisable')


def result(quantity, role, **values):
    if quantity not in QUANTITIES:
        raise ValueError('unknown quantity ' + quantity)
    if role not in ROLES:
        raise ValueError('result role must be primary, companion or diagnostic')
    return {'quantity': quantity, 'role': role, **values}


def statistic(origin, *, verbatim=None, definition=None):
    if origin not in ORIGINS:
        raise ValueError('statistic origin must be prescribed, default or not-applicable')
    if origin == 'prescribed' and (type(verbatim) is not str or not verbatim.strip()):
        raise ValueError('a prescribed statistic must be recorded verbatim')
    return {'origin': origin, 'verbatim': verbatim, 'definition': definition or {}}


def build(*, mode, engine, statistic, parameters, results, inputs, grid=None, diagnostics=None,
          requester_assumptions=(), limitations=(), status='passed'):
    doc = {'schema_version': SCHEMA_VERSION, 'kind': 'inference', 'mode': mode, 'engine': engine,
           'status': status, 'statistic': statistic, 'parameters': list(parameters), 'results': list(results),
           'grid': grid, 'diagnostics': diagnostics or {}, 'inputs': list(inputs),
           'requester_assumptions': list(requester_assumptions), 'limitations': list(limitations),
           'physics_validated': False}
    validate(doc)
    return clean(doc)


def validate(doc):
    if type(doc) is not dict or doc.get('kind') != 'inference' or doc.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('inference record schema 1 required')
    if doc.get('status') not in ('passed', 'failed'):
        raise ValueError('inference record status must be passed or failed')
    st = doc.get('statistic')
    if type(st) is not dict or st.get('origin') not in ORIGINS:
        raise ValueError('inference record needs a statistic origin')
    if st['origin'] == 'prescribed' and not st.get('verbatim'):
        raise ValueError('a prescribed statistic must be recorded verbatim')
    results = doc.get('results')
    if type(results) is not list:
        raise ValueError('inference results must be a list')
    for row in results:
        if row.get('quantity') not in QUANTITIES or row.get('role') not in ROLES:
            raise ValueError('every result needs a known quantity and role')
    if st['origin'] == 'prescribed' and doc['status'] == 'passed' and not any(r['role'] == 'primary' for r in results):
        raise ValueError('a prescribed statistic must be delivered as a primary result')
    for pin in doc.get('inputs', []):
        if type(pin) is not dict or set(pin) != {'path', 'sha256'}:
            raise ValueError('inputs are path and sha256 pins')
    if doc.get('physics_validated') is not False:
        raise ValueError('an inference record never claims physics validation')
    for check in doc.get('computed_checks', []):
        if (type(check) is not dict or check.get('computed') is not True
                or check.get('status') not in ('pass', 'warn', 'fail') or not check.get('trigger')):
            raise ValueError('computed checks are machine records with trigger, status pass/warn/fail and computed')
    return doc


def write(path, doc):
    path = Path(path)
    data = json.dumps(clean(doc), indent=2, allow_nan=False) + '\n'
    path.write_text(data)
    return {'path': str(path), 'sha256': hashlib.sha256(data.encode()).hexdigest()}


def summary_lines(doc):
    """Short plain-text lines describing the primary and companion results."""
    lines = []
    for row in doc['results']:
        if row['role'] == 'diagnostic':
            continue
        text = row.get('summary')
        if text:
            lines.append(('Primary: ' if row['role'] == 'primary' else 'Alongside: ') + text)
    return lines
