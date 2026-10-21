"""Deterministic fit and scan alarms, computed from result records.

Each alarm is a pure function of a result record. It returns check records with
``status`` ``pass``, ``warn`` or ``fail`` and ``computed: true``. The inference
engines store them in ``inference.json`` under ``computed_checks``;
``physics_review`` recomputes them from the retained outputs at acceptance, so
a reviewer or agent cannot overwrite a computed failure. A computed failure
blocks acceptance of a claim scope that requires a scientific check (limits,
measurements, reproductions). An integrity-only diagnostic scope stays
available.

Alarms (``TRIGGERS``):

- ``closure``: chi2/ndf below 0.1 warns (suspiciously good), above 3 fails; any
  closure pull above 5 fails;
- ``fit-triviality``: a chi-square exactly zero with ndf > 0, or a fit that
  returns every parameter at its input value, fails (warns for MC pseudo-data,
  where a perfect fit is expected by construction);
- ``parameter-at-bound``: parameters at or near a fit bound, including the flags
  that other RAVEL engines write (``near_lower_bound``, ``near_upper_bound``,
  ``at_boundary``), warn;
- ``nuisance-pulls``: a constrained pull above 3 warns; an RMS of pulls below
  0.7 with at least five pulls warns (a RAVEL choice: investigate overcoverage);
- ``systematic-dominance``: one source above 80% of the total systematic
  variance warns; a flat (normalisation-only) shift supplied as a shape
  variation in a multi-bin measurement warns;
- ``systematic-selfcheck``: a source with zero impact, or two sources with
  identical shift vectors, fails;
- ``reference-deviation``: a relative deviation above 0.3 from a declared
  well-measured reference fails pending investigation;
- ``goodness-of-fit``: a p-value below 0.05 (outside the 95% toy band) fails; a
  goodness of fit with fixed auxiliary measurements fails (it is refused as the
  reported goodness of fit); the asymptotic fallback is labelled;
- ``excluded-bins``: more than half of the bins excluded from a fit fails;
- ``open-at-edge``: an interval, best fit or contour that touches the hull of
  the evaluated points, or a limit censored at the scan ceiling or floor, fails
  and carries a proposed extension (level lines of declared formulas warn);
- ``validity-status``: a fit or region result without a validity status fails.
- ``statistics-validity``: audited statistics records pass, qualify with warnings,
  or fail when held or inconsistent with their facts and evidence.

Defaults may be changed only with a recorded basis (``review.thresholds``); the
record states the value, its origin and the basis used.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

TRIGGERS = ('closure', 'fit-triviality', 'parameter-at-bound', 'nuisance-pulls', 'systematic-dominance',
            'systematic-selfcheck', 'reference-deviation', 'goodness-of-fit', 'excluded-bins', 'open-at-edge',
            'validity-status', 'mc-adequacy', 'statistics-validity')
STATUSES = ('pass', 'warn', 'fail')
GENERAL = 'general fit-review default'
DEFAULTS = {
    'closure_chi2_ndf_low': (0.1, GENERAL),
    'closure_chi2_ndf_high': (3.0, GENERAL),
    'closure_pull_max': (5.0, GENERAL),
    'nuisance_pull_max': (3.0, GENERAL),
    'pull_rms_min': (0.7, 'RAVEL choice: an overcoverage investigation trigger'),
    'pull_rms_min_count': (5, 'RAVEL choice: minimum number of pulls for the RMS test'),
    'systematic_dominance_fraction': (0.8, GENERAL),
    'reference_relative_deviation': (0.3, GENERAL),
    'gof_p_value_min': (0.05, 'two-sided 95% toy band; general fit-review default'),
    'excluded_bin_fraction': (0.5, GENERAL),
    'edge_tolerance': (1e-6, 'RAVEL choice: relative distance to the hull counted as touching'),
    'edge_extension_fraction': (0.5, 'RAVEL choice: proposed extension as a fraction of the scanned span'),
}
VALID_FIT_STATUSES = ('converged', 'computed', 'resolved', 'empty', 'accepted', 'passed', 'succeeded')
FLAG_KEYS = {'near_lower_bound': ('parameter-at-bound', 'warn', 'parameter near its lower fit bound'),
             'near_upper_bound': ('parameter-at-bound', 'warn', 'parameter near its upper fit bound'),
             'at_boundary': ('parameter-at-bound', 'warn', 'fitted value at its physical boundary'),
             'at_poi_cap': ('open-at-edge', 'warn', 'observed limit equals the signal-strength scan ceiling; '
                            'quote it as a bound'),
             'median_at_cap': ('open-at-edge', 'fail', 'median expected limit equals the scan ceiling'),
             'at_mu_floor': ('open-at-edge', 'fail', 'limit at the signal-strength scan floor'),
             'band_degenerate': ('open-at-edge', 'warn', 'expected band is degenerate; quote as a bound only')}
MAX_SCANNED_FILES, MAX_SCANNED_BYTES, MAX_FLAG_BYTES = 512, 32 * 1024 ** 2, 2 * 1024 ** 2


# ----------------------------------------------------------------------------- thresholds

def thresholds(overrides=None):
    """Effective thresholds; each override needs a value and a recorded basis."""
    out = {k: {'value': v, 'origin': 'default', 'basis': basis} for k, (v, basis) in DEFAULTS.items()}
    for name, row in (overrides or {}).items():
        if name not in DEFAULTS:
            raise ValueError(f'unknown review threshold {name!r}')
        if (type(row) is not dict or set(row) != {'value', 'basis'} or type(row['value']) not in (int, float)
                or not math.isfinite(row['value']) or type(row['basis']) is not str or not row['basis'].strip()):
            raise ValueError(f'review threshold {name} needs a finite value and a recorded basis')
        out[name] = {'value': row['value'], 'origin': 'override', 'basis': row['basis']}
    return out


def validate_review(review):
    """Check an optional ``review`` block: thresholds (value + basis) and declared references."""
    if review is None:
        return {}
    if type(review) is not dict or set(review) - {'thresholds', 'references'}:
        raise ValueError('review takes thresholds and references')
    thresholds(review.get('thresholds'))
    for ref in review.get('references') or []:
        if (type(ref) is not dict or not {'label', 'path', 'value', 'source'} <= set(ref)
                or set(ref) - {'label', 'path', 'value', 'uncertainty', 'source', 'well_measured'}):
            raise ValueError('a reference needs label, path (into the record), value and source')
        if type(ref['value']) not in (int, float) or not math.isfinite(ref['value']):
            raise ValueError('a reference value must be a finite number')
        _path_tokens(ref['path'])
    return review


def _check(trigger, status, location, detail, **extra):
    if trigger not in TRIGGERS or status not in STATUSES:
        raise ValueError('unknown trigger or status')
    return {'id': f'{trigger}@{location}', 'trigger': trigger, 'status': status, 'location': location,
            'detail': detail, 'computed': True, **extra}


def _t(limits, name):
    return {'name': name, **limits[name]}


# ----------------------------------------------------------------------------- record evaluation

def evaluate(doc, *, review=None):
    """Computed checks for one ``inference.json`` record."""
    review = validate_review(review if review is not None else doc.get('review'))
    limits = thresholds(review.get('thresholds'))
    pseudo = (doc.get('diagnostics') or {}).get('data_mode') == 'mc-pseudo-data'
    checks = []
    for i, row in enumerate(doc.get('results') or []):
        where = f'results[{i}]'
        q = row.get('quantity')
        if q == 'morph-coefficients':
            checks += _chi2_rows(row, where, limits, pseudo)
        elif q == 'morph-closure':
            checks += _closure_pulls(row, where, limits)
        elif q == 'fitted-parameters':
            checks += _fitted(row, where, limits, pseudo)
        elif q == 'goodness-of-fit':
            checks += _gof(row, where, limits, pseudo)
        elif q in ('delta-nll-region', 'significance'):
            checks += _region(row, where, doc, limits)
        elif q == 'cls-limit':
            checks += _flags(row, where)
            checks += _validity(row, where)
        elif q == 'statistics':
            checks += _statistics_validity(row, where)
        elif q == 'mc-adequacy':
            for k, flag in enumerate(row.get('flags') or []):
                reasons = flag.get('flags') or [flag.get('code', 'mc_adequacy')]
                severe = flag.get('severity') == 'fail' or 'nonpositive_total_background' in reasons
                checks.append(_check('mc-adequacy', 'fail' if severe else 'warn', f'{where}.flags[{k}]',
                                     ', '.join(reasons), source=flag))
        elif q == 'contour':
            checks += _contour(row, where, doc, limits)
        elif q == 'systematics' and isinstance(row.get('selfcheck'), dict):
            checks += _systematics(row['selfcheck'], where + '.selfcheck', limits)
        if isinstance(row, dict) and 'bins_total' in row and 'bins_excluded' in row:
            checks += _excluded(row, where, limits)
    for k, ref in enumerate(review.get('references') or []):
        checks.append(_reference(doc, ref, f'review.references[{k}]', limits))
    return checks


def _statistics_validity(row, where):
    from ravel.physics.inference import situations
    block = row.get('record')
    try:
        errors = situations.audit(block)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        errors = [f'the statistics record cannot be audited: {type(exc).__name__}: {exc}']
    if errors:
        return [_check('statistics-validity', 'fail', where, '; '.join(errors[:3]), errors=errors[:3])]
    outcome, labels = block['validity']['outcome'], situations.labels(block)
    if row.get('outcome') != outcome or row.get('labels') != labels:
        return [_check('statistics-validity', 'fail', where,
                       'statistics outcome or labels disagree with the audited record')]
    status = {'held': 'fail', 'qualified': 'warn', 'valid': 'pass'}[outcome]
    return [_check('statistics-validity', status, where, '; '.join(labels) or 'every statistics validity check passed',
                   outcome=outcome, labels=labels)]


def _chi2_rows(row, where, limits, pseudo):
    ndf, chi2 = row.get('ndf') or 0, row.get('chi2')
    if not ndf or chi2 is None:
        return []
    out = []
    for b, value in enumerate(chi2):
        if value is None:
            continue
        ratio = value / ndf
        loc = f'{where}.chi2[{b}]'
        if value == 0:
            out.append(_check('fit-triviality', 'warn' if pseudo else 'fail', loc,
                              f'chi-square is exactly zero with {ndf} degrees of freedom'))
        elif ratio > limits['closure_chi2_ndf_high']['value']:
            out.append(_check('closure', 'fail', loc, f'chi2/ndf = {ratio:.3g}',
                              threshold=_t(limits, 'closure_chi2_ndf_high')))
        elif ratio < limits['closure_chi2_ndf_low']['value']:
            out.append(_check('closure', 'warn', loc, f'chi2/ndf = {ratio:.3g} is suspiciously small',
                              threshold=_t(limits, 'closure_chi2_ndf_low')))
        else:
            out.append(_check('closure', 'pass', loc, f'chi2/ndf = {ratio:.3g}'))
    return out


def _closure_pulls(row, where, limits):
    out = []
    cap = limits['closure_pull_max']['value']
    for k, c in enumerate(row.get('checks') or []):
        pulls = [p for p in (c.get('pulls') or []) if p is not None]
        worst = max((abs(p) for p in pulls), default=0.0)
        status = 'fail' if worst > cap or c.get('passed') is False else 'pass'
        out.append(_check('closure', status, f'{where}.checks[{k}]',
                          f'held-out run {c.get("id")}: largest |pull| {worst:.3g}'
                          + ('' if c.get('passed') is not False else ' (outside its declared tolerance)'),
                          threshold=_t(limits, 'closure_pull_max')))
    return out


def _fitted(row, where, limits, pseudo):
    out = _validity(row, where)
    params = row.get('parameters') or []
    moved = [p for p in params if isinstance(p.get('prefit'), dict) and p['prefit'].get('nominal') is not None]
    if moved and all(p.get('value') == p['prefit']['nominal'] for p in moved):
        out.append(_check('fit-triviality', 'warn' if pseudo else 'fail', where,
                          'every fitted parameter equals its input value; the fit did not move'))
    elif moved:
        out.append(_check('fit-triviality', 'pass', where, 'fitted parameters moved from their inputs'))
    pulls = [(p.get('name'), p['pull']) for p in params if p.get('pull') is not None]
    cap = limits['nuisance_pull_max']['value']
    big = [(n, v) for n, v in pulls if abs(v) > cap]
    if pulls:
        out.append(_check('nuisance-pulls', 'warn' if big else 'pass', where + '.parameters',
                          (f'pulls above {cap:g} sigma: ' + ', '.join(f'{n} {v:.3g}' for n, v in big)) if big
                          else f'{len(pulls)} constrained pull(s) within {cap:g} sigma',
                          threshold=_t(limits, 'nuisance_pull_max')))
    if len(pulls) >= limits['pull_rms_min_count']['value']:
        rms = math.sqrt(sum(v * v for _, v in pulls) / len(pulls))
        low = rms < limits['pull_rms_min']['value']
        out.append(_check('nuisance-pulls', 'warn' if low else 'pass', where + '.parameters.rms',
                          f'RMS of {len(pulls)} pulls = {rms:.3g}' + ('; investigate overcoverage' if low else ''),
                          threshold=_t(limits, 'pull_rms_min')))
    out += _flags(row, where)
    return out


def _gof(row, where, limits, pseudo):
    if row.get('auxiliary') == 'fixed':
        return [_check('goodness-of-fit', 'fail', where,
                       'goodness of fit with fixed auxiliary measurements is refused as the reported goodness of fit')]
    p, method = row.get('p_value'), row.get('method')
    label = 'toys' if method == 'toys' else 'asymptotic fallback'
    if p is None:
        return [_check('goodness-of-fit', 'warn', where, f'no p-value ({label})', method=method)]
    floor = limits['gof_p_value_min']['value']
    if row.get('observed') == 0 and (row.get('asymptotic') or {}).get('ndf', 0) > 0:
        return [_check('fit-triviality', 'warn' if pseudo else 'fail', where,
                       'goodness-of-fit statistic is exactly zero', method=method)]
    status = 'fail' if p < floor else 'pass'
    return [_check('goodness-of-fit', status, where, f'p = {p:.3g} ({label})', method=method,
                   threshold=_t(limits, 'gof_p_value_min'))]


def _validity(row, where):
    status = row.get('status')
    if status is None:
        return [_check('validity-status', 'fail', where, 'the fit returned without a validity status')]
    ok = status in VALID_FIT_STATUSES
    return [_check('validity-status', 'pass' if ok else 'fail', where, f'status {status}')]


def _flags(row, where):
    out = []
    def walk(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in FLAG_KEYS and item is True:
                    trigger, status, text = FLAG_KEYS[key]
                    name = value.get('name')
                    out.append(_check(trigger, status, f'{path}.{key}',
                                      text + (f' ({name})' if isinstance(name, str) else '')))
                else:
                    walk(item, f'{path}.{key}')
        elif isinstance(value, list):
            for k, item in enumerate(value):
                walk(item, f'{path}[{k}]')
    walk(row, where)
    return out


def consume_flags(doc, where='$'):
    """Alarms from the honesty and boundary flags of any RAVEL result document."""
    return _flags(doc, where)


def _axis_extension(edge, low, high, side, domain, limits):
    span = high - low
    step = limits['edge_extension_fraction']['value'] * (span if span > 0 else max(abs(edge), 1.0))
    proposed = edge + step if side == 'high' else edge - step
    if domain is not None:
        lo_d, hi_d = domain
        if side == 'low' and lo_d is not None:
            proposed = max(proposed, lo_d)
        if side == 'high' and hi_d is not None:
            proposed = min(proposed, hi_d)
    return {'side': side, 'current': edge, 'proposed': proposed}


def _domain(doc):
    grid = doc.get('grid') or {}
    d = grid.get('domain')
    return tuple(d) if isinstance(d, list) and len(d) == 2 else (None, None)


def _region(row, where, doc, limits):
    out = _validity(row, where)
    if row.get('quantity') == 'significance' and row.get('status') is None:
        out = []  # significances carry their own values; no fit status is attached
    lo_d, hi_d = _domain(doc)
    scan = row.get('scan_range')
    for k, interval in enumerate(row.get('intervals') or []):
        for side in ('low', 'high'):
            end = interval.get(side) or {}
            if end.get('status') == 'beyond_scan':
                edge = end.get('scan_edge')
                ext = _axis_extension(edge, *(scan or (edge, edge)), side, (lo_d, hi_d), limits)
                out.append(_check('open-at-edge', 'fail', f'{where}.intervals[{k}].{side}',
                                  f'the allowed region continues beyond the scanned {side} edge {edge:g}',
                                  proposed_extension={'parameter': row.get('parameter'), **ext}))
    best = row.get('best_fit')
    if isinstance(best, dict) and best.get('at_scan_edge') and 'asimov' not in str(row.get('dataset', '')).lower():
        value = best.get(row.get('parameter'))
        if scan and value is not None:
            side = 'low' if abs(value - scan[0]) <= abs(value - scan[1]) else 'high'
            edge = scan[0] if side == 'low' else scan[1]
            bound = lo_d if side == 'low' else hi_d
            if bound is not None and math.isclose(edge, bound, rel_tol=0, abs_tol=1e-12):
                out.append(_check('parameter-at-bound', 'warn', f'{where}.best_fit',
                                  f'best fit at the physical boundary {bound:g} of {row.get("parameter")}'))
            else:
                out.append(_check('open-at-edge', 'fail', f'{where}.best_fit',
                                  f'best fit at the scanned {side} edge {edge:g}',
                                  proposed_extension={'parameter': row.get('parameter'),
                                                      **_axis_extension(edge, scan[0], scan[1], side,
                                                                        (lo_d, hi_d), limits)}))
    elif isinstance(best, dict) and scan:
        out.append(_check('open-at-edge', 'pass', f'{where}.best_fit', 'best fit inside the scanned range'))
    return out


def _evaluated_points(doc, x, y):
    grid = doc.get('grid') or {}
    if grid.get('kind') == 'product':
        axes = {a['name']: a['values'] for a in grid.get('axes') or []}
        if x in axes and y in axes:
            return np.array([(a, b) for a in axes[x] for b in axes[y]], float)
    if grid.get('kind') == 'points':
        pts = [(p[x], p[y]) for p in grid.get('points') or [] if x in p and y in p]
        if pts:
            return np.array(pts, float)
    return None


def _contour(row, where, doc, limits):
    if row.get('status') == 'not_rectangular' or not row.get('series'):
        return []
    x, y = row.get('x'), row.get('y')
    points = _evaluated_points(doc, x, y)
    if points is None or len(points) < 3:
        return [_check('open-at-edge', 'warn', where, 'evaluated points unavailable; edge test not run')]
    from scipy.spatial import ConvexHull, QhullError
    low, span = points.min(axis=0), np.ptp(points, axis=0)
    if np.any(span <= 0):
        return [_check('open-at-edge', 'warn', where, 'evaluated points are collinear; edge test not run')]
    try:
        hull = ConvexHull((points - low) / span)
    except QhullError:
        return [_check('open-at-edge', 'warn', where, 'hull of the evaluated points could not be built')]
    tol = limits['edge_tolerance']['value']
    touched = {}
    for s in row['series']:
        xy = np.array([(r['x'], r['y']) for r in s.get('records') or []], float)
        if not len(xy):
            continue
        scaled = (xy - low) / span
        distance = -(scaled @ hull.equations[:, :2].T + hull.equations[:, 2])  # >= 0 inside
        for f in np.where(np.any(distance <= tol, axis=0))[0]:
            touched.setdefault(int(f), 0)
            touched[int(f)] += int(np.sum(distance[:, f] <= tol))
    if not touched:
        return [_check('open-at-edge', 'pass', where, 'contour lies inside the hull of the evaluated points')]
    proposals = []
    for f, count in sorted(touched.items()):
        normal = hull.equations[f, :2]
        proposal = {'outward_normal': {x: float(normal[0]), y: float(normal[1])}, 'touching_points': count}
        for axis, k, name in ((0, 0, x), (1, 1, y)):
            if abs(normal[k]) > 0.999:
                side = 'high' if normal[k] > 0 else 'low'
                edge = float(points[:, axis].max() if side == 'high' else points[:, axis].min())
                proposal['axis'] = name
                proposal.update(_axis_extension(edge, float(points[:, axis].min()), float(points[:, axis].max()),
                                                side, None, limits))
        if 'axis' not in proposal:
            proposal['extend_by_fraction_of_span'] = limits['edge_extension_fraction']['value']
        proposals.append(proposal)
    formula_level = 'output' in row
    return [_check('open-at-edge', 'warn' if formula_level else 'fail', where,
                   f'contour touches {len(touched)} edge(s) of the evaluated region',
                   proposed_extension=proposals)]


def _systematics(selfcheck, where, limits):
    out = []
    rows = selfcheck.get('modifiers') or []
    for k, m in enumerate(rows):
        loc = f'{where}.modifiers[{k}]'
        if m.get('zero_impact'):
            out.append(_check('systematic-selfcheck', 'fail', loc, f'{m.get("name")} has zero impact'))
        elif m.get('identical_to'):
            out.append(_check('systematic-selfcheck', 'fail', loc,
                              f'{m.get("name")} has the same shift vector as {", ".join(m["identical_to"])}'))
        else:
            out.append(_check('systematic-selfcheck', 'pass', loc, f'{m.get("name")} has a distinct nonzero impact'))
        if m.get('flat_shape_variation'):
            out.append(_check('systematic-dominance', 'warn', loc,
                              f'{m.get("name")} is a flat shift supplied as a shape variation'))
    cap = limits['systematic_dominance_fraction']['value']
    fractions = [(m.get('name'), m.get('variance_fraction')) for m in rows if m.get('variance_fraction') is not None]
    if len(fractions) >= 2:
        top = max(fractions, key=lambda r: r[1])
        out.append(_check('systematic-dominance', 'warn' if top[1] > cap else 'pass', where,
                          f'largest source {top[0]} carries {top[1]:.0%} of the systematic variance',
                          threshold=_t(limits, 'systematic_dominance_fraction')))
    return out


def _excluded(row, where, limits):
    total, excluded = row['bins_total'], row['bins_excluded']
    if not total:
        return []
    fraction = excluded / total
    cap = limits['excluded_bin_fraction']['value']
    return [_check('excluded-bins', 'fail' if fraction > cap else 'pass', where,
                   f'{excluded} of {total} bins excluded', threshold=_t(limits, 'excluded_bin_fraction'))]


def _path_tokens(path):
    if type(path) is not str or not path.strip():
        raise ValueError('a reference path is a dotted path into the record, e.g. results[2].parameter_limit.observed')
    tokens = []
    for part in path.split('.'):
        name, _, rest = part.partition('[')
        if name:
            tokens.append(name)
        while rest:
            index, _, rest = rest.partition(']')
            if not index.isdigit():
                raise ValueError('reference path indices must be integers')
            tokens.append(int(index))
            rest = rest[1:] if rest.startswith('[') else rest
    return tokens


def _lookup(doc, path):
    value = doc
    for token in _path_tokens(path):
        try:
            value = value[token]
        except (KeyError, IndexError, TypeError):
            return None
    return value


def _reference(doc, ref, where, limits):
    value = _lookup(doc, ref['path'])
    if type(value) not in (int, float) or not math.isfinite(value):
        return _check('reference-deviation', 'fail', where, f'{ref["label"]}: no numeric value at {ref["path"]}')
    if ref['value'] == 0:
        return _check('reference-deviation', 'warn', where, f'{ref["label"]}: reference is zero; no relative test')
    rel = (value - ref['value']) / abs(ref['value'])
    cap = limits['reference_relative_deviation']['value']
    well = ref.get('well_measured', True)
    status = ('fail' if well else 'warn') if abs(rel) > cap else 'pass'
    return _check('reference-deviation', status, where,
                  f'{ref["label"]}: {value:.6g} vs reference {ref["value"]:.6g} ({rel:+.1%}); source {ref["source"]}',
                  relative_deviation=rel, threshold=_t(limits, 'reference_relative_deviation'))


# ----------------------------------------------------------------------------- systematics self-check

def systematics_selfcheck(modifiers, *, shape_measurement):
    """Per-modifier self-check rows from nominal and up/down templates.

    ``modifiers``: list of ``{name, kind, nominal, up, down}`` with flat arrays
    concatenated over every sample and region the source touches. The variance
    fraction uses the symmetrised shift summed over bins.
    """
    rows, shifts = [], []
    for m in modifiers:
        nominal = np.asarray(m['nominal'], float)
        up, down = np.asarray(m['up'], float) - nominal, np.asarray(m['down'], float) - nominal
        shifts.append(np.concatenate([up, down]))
        size = 0.5 * (np.abs(up) + np.abs(down))
        row = {'name': m['name'], 'kind': m['kind'], 'zero_impact': bool(np.all(up == 0) and np.all(down == 0)),
               'impact': float(np.sum(size)), 'identical_to': []}
        if shape_measurement and m['kind'] == 'histosys' and len(nominal) > 1:
            with np.errstate(divide='ignore', invalid='ignore'):
                ratio = np.where(nominal != 0, up / nominal, np.nan)
            finite = ratio[np.isfinite(ratio)]
            row['flat_shape_variation'] = bool(len(finite) > 1 and np.allclose(finite, finite[0], rtol=1e-9, atol=0)
                                               and finite[0] != 0)
        rows.append(row)
    for i in range(len(rows)):
        for j in range(len(rows)):
            if i != j and not rows[i]['zero_impact'] and shifts[i].shape == shifts[j].shape \
                    and np.array_equal(shifts[i], shifts[j]):
                rows[i]['identical_to'].append(rows[j]['name'])
    total = sum(r['impact'] ** 2 for r in rows)
    for r in rows:
        r['variance_fraction'] = (r['impact'] ** 2 / total) if total > 0 else None
    return {'schema_version': 1, 'kind': 'systematics-selfcheck', 'shape_measurement': bool(shape_measurement),
            'modifiers': rows}


# ----------------------------------------------------------------------------- summaries and review

def summary(checks):
    counts = {s: sum(1 for c in checks if c['status'] == s) for s in STATUSES}
    return {**counts, 'failures': [c['id'] for c in checks if c['status'] == 'fail']}


def failures(checks):
    return [c for c in checks if c['status'] == 'fail']


def from_outputs(paths):
    """Recompute alarms from retained outputs (files or directories).

    ``inference.json`` records are re-evaluated from their results; other JSON
    documents up to ``MAX_FLAG_BYTES`` contribute their boundary and censoring
    flags. Returns ``(checks, scanned, skipped)``.
    """
    files = []
    for p in paths:
        p = Path(p)
        if p.is_file() and p.suffix == '.json':
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(q for q in p.rglob('*.json') if q.is_file() and not q.is_symlink()))
    checks, scanned, skipped = [], [], []
    for k, path in enumerate(files):
        size = path.stat().st_size
        record = path.name == 'inference.json'
        if k >= MAX_SCANNED_FILES or size > (MAX_SCANNED_BYTES if record else MAX_FLAG_BYTES):
            skipped.append(str(path))
            continue
        try:
            doc = json.loads(path.read_text(encoding='utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            skipped.append(str(path))
            continue
        found = evaluate(doc) if isinstance(doc, dict) and doc.get('kind') == 'inference' else consume_flags(doc)
        for c in found:
            c['source'] = str(path)
        checks.extend(found)
        scanned.append(str(path))
    return checks, scanned, skipped
