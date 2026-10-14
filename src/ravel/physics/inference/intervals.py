"""Allowed regions from a scanned test statistic with bracketed, verified crossings.

``allowed_regions`` returns every maximal run of scan points with
``statistic <= threshold``. Each edge is one of:

- ``resolved``: a sign change of ``statistic - threshold`` between neighbouring
  scan points, refined with Brent's method and re-evaluated at the root;
- ``domain_boundary``: the run reaches the declared physical domain edge, which
  the scan includes;
- ``beyond_scan``: the run reaches the scan edge inside the physical domain. No
  value is reported; the scan edge is recorded. The region is ``unresolved``.

Disjoint regions are kept separate. The scan spacing limits which narrow
regions can be seen; it is reported with the result.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import optimize

ROOT_XTOL = 1e-12
ROOT_RTOL = 1e-10


def _edge_value(x):
    return None if x is None or not math.isfinite(x) else float(x)


def _crossing(grid, values, i, threshold, refine):
    a, b = float(grid[i]), float(grid[i + 1])
    fa, fb = refine(a) - threshold, refine(b) - threshold
    if not (math.isfinite(fa) and math.isfinite(fb)) or fa * fb > 0:
        return {'status': 'refinement_failed', 'value': None, 'bracket': [a, b],
                'reason': 'the refined statistic does not change sign across the scan bracket'}
    if fa == 0:
        root = a
    elif fb == 0:
        root = b
    else:
        root = optimize.brentq(lambda x: refine(x) - threshold, a, b, xtol=ROOT_XTOL, rtol=ROOT_RTOL, maxiter=200)
    residual = refine(root) - threshold
    tolerance = 1e-6 * max(1.0, abs(threshold))
    status = 'resolved' if abs(residual) <= tolerance else 'refinement_failed'
    return {'status': status, 'value': float(root) if status == 'resolved' else None, 'bracket': [a, b],
            'statistic_at_value': float(refine(root)), 'residual': float(residual)}


def allowed_regions(grid, statistic, threshold, refine, *, domain=(None, None)):
    grid = np.asarray(grid, float)
    values = np.asarray(statistic, float)
    if grid.ndim != 1 or grid.shape != values.shape or len(grid) < 2 or np.any(np.diff(grid) <= 0):
        raise ValueError('a strictly increasing one-dimensional scan is required')
    if not np.all(np.isfinite(values)):
        bad = [float(x) for x in grid[~np.isfinite(values)]]
        return {'status': 'failed', 'threshold': float(threshold), 'intervals': [],
                'reason': 'the statistic is not finite at scan points', 'nonfinite_points': bad}
    lo_domain, hi_domain = domain
    inside = values <= threshold
    intervals = []
    i = 0
    n = len(grid)
    while i < n:
        if not inside[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and inside[j + 1]:
            j += 1
        if i == 0:
            if lo_domain is not None and math.isclose(grid[0], lo_domain, rel_tol=0, abs_tol=1e-12):
                low = {'status': 'domain_boundary', 'value': float(grid[0])}
            else:
                low = {'status': 'beyond_scan', 'value': None, 'scan_edge': float(grid[0])}
        else:
            low = _crossing(grid, values, i - 1, threshold, refine)
        if j == n - 1:
            if hi_domain is not None and math.isclose(grid[-1], hi_domain, rel_tol=0, abs_tol=1e-12):
                high = {'status': 'domain_boundary', 'value': float(grid[-1])}
            else:
                high = {'status': 'beyond_scan', 'value': None, 'scan_edge': float(grid[-1])}
        else:
            high = _crossing(grid, values, j, threshold, refine)
        intervals.append({'low': low, 'high': high, 'scan_points': int(j - i + 1)})
        i = j + 1
    statuses = {e['status'] for row in intervals for e in (row['low'], row['high'])}
    status = ('empty' if not intervals else 'resolved' if statuses <= {'resolved', 'domain_boundary'}
              else 'unresolved')
    spacing = float(np.max(np.diff(grid)))
    return {'status': status, 'threshold': float(threshold), 'intervals': intervals,
            'scan_range': [float(grid[0]), float(grid[-1])], 'max_scan_spacing': spacing,
            'narrow_regions': [k for k, row in enumerate(intervals) if row['scan_points'] == 1]}


def one_sided(grid, statistic, best):
    """Upper-limit statistic: zero below the best fit, unchanged above it."""
    grid = np.asarray(grid, float)
    return np.where(grid < best, 0.0, np.asarray(statistic, float))


def describe(region, parameter):
    """Plain-text summary of allowed intervals for reports."""
    if region['status'] == 'empty':
        return f'no {parameter} value satisfies the threshold on the scan'
    parts = []
    for row in region['intervals']:
        lo = row['low']; hi = row['high']
        lo_text = f'{lo["value"]:.6g}' if lo['value'] is not None else f'below {lo.get("scan_edge", "scan")} (not bracketed)'
        hi_text = f'{hi["value"]:.6g}' if hi['value'] is not None else f'above {hi.get("scan_edge", "scan")} (not bracketed)'
        parts.append(f'[{lo_text}, {hi_text}]')
    return f'{parameter} in ' + ' or '.join(parts)
