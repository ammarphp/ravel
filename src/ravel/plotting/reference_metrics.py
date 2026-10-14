"""Quantitative comparison of a RAVEL result with a reference series.

Nothing is inferred. Every change of representation is a declared
transformation recorded in the output:

- ``fraction_to_density`` / ``density_to_fraction`` (divide or multiply by bin width),
- ``rebin`` to edges that are a subset of the current edges (counts add, densities
  are width-weighted, covariance is propagated),
- ``rebin_matrix`` with a declared linear map and reason,
- ``unit`` conversion of values or of the x axis between known units,
- ``normalize`` to unit area or to a declared total,
- ``scale`` by a declared factor with a reason,
- ``relabel`` of quantity or unit with a reason,
- ``select`` of a declared x range.

Metrics on matched bins: relative L2 ``d = ||a - b|| / ||b||``, shape L2 after
unit-area normalisation, normalisation ratio, per-bin pulls, chi2 with the supplied
covariances (agent plus reference plus digitisation), and the binned
Kolmogorov-Smirnov statistic. Curves are compared at the reference points in the
declared axis scales. Contours are compared by the symmetric Hausdorff distance
(maximum and mean) in axis fractions of the declared ranges, with logarithmic axes
measured in decades. Regions are compared by intersection over union on a grid.

A declared tolerance per metric (``pass``, ``warn`` and a ``basis``) yields
PASS / WARN / FAIL. Bins present on one side only make the comparison
INCOMPLETE. The verdict is a machine comparison, not physics review.
"""
from copy import deepcopy
import argparse
import json
import sys
from pathlib import Path
import math

import numpy as np

from .figure_io import (code_identity, finite_list, json_pointer, load_json, load_spec, pin, resolve,
                        sha256_bytes, read_bytes, write_new_json)

QUANTITIES = ('count', 'fraction', 'density', 'value')
EDGE_RTOL = 1e-9
HIGHER_IS_BETTER = {'iou', 'chi2_p_value', 'ks_p_value'}

# Multiplicative factors to a base unit, per dimension.
_UNITS = {
    'xsec': {'ab': 1e-3, 'fb': 1.0, 'pb': 1e3, 'nb': 1e6, 'ub': 1e9, 'mb': 1e12},
    'energy': {'eV': 1e-9, 'keV': 1e-6, 'MeV': 1e-3, 'GeV': 1.0, 'TeV': 1e3},
    'invlumi': {'ab^-1': 1e3, 'fb^-1': 1.0, 'pb^-1': 1e-3, 'nb^-1': 1e-6},
    'length': {'um': 1e-6, 'mm': 1e-3, 'cm': 1e-2, 'm': 1.0},
    'time': {'ps': 1e-12, 'ns': 1e-9, 's': 1.0},
}
_ALIASES = {'μb': 'ub', 'µb': 'ub', 'ab-1': 'ab^-1', 'fb-1': 'fb^-1', 'pb-1': 'pb^-1', 'nb-1': 'nb^-1',
            '1/ab': 'ab^-1', '1/fb': 'fb^-1', '1/pb': 'pb^-1', '1/nb': 'nb^-1', 'μm': 'um', 'µm': 'um'}


def _unit_factor(unit):
    """(dimension signature, factor to base) for a unit such as 'pb/GeV' or 'fb'."""
    unit = unit.strip()
    if unit in ('', '1', 'events', 'event'):
        return ((unit or '1',), 1.0)
    numerator, _, denominator = unit.partition('/')
    sig, factor = [], 1.0
    for part, sign in ((numerator, 1), (denominator, -1)):
        part = part.strip()
        if not part:
            continue
        if part == '1' and sign == 1:
            continue
        part = _ALIASES.get(part, part)
        for dim, table in _UNITS.items():
            if part in table:
                sig.append((dim, sign))
                factor *= table[part] ** sign
                break
        else:
            raise ValueError(f'unknown unit {part!r}; declare a scale with a reason instead')
    return (tuple(sorted(sig)), factor)


def unit_factor(source, target):
    s_sig, s_f = _unit_factor(source)
    t_sig, t_f = _unit_factor(target)
    if s_sig != t_sig:
        raise ValueError(f'cannot convert unit {source!r} to {target!r}: different dimensions')
    return s_f / t_f


# ===================================================================== binned series
def binned(edges, values, *, errors=None, error_low=None, error_high=None, covariance=None,
           quantity='count', unit='events', digitization_errors=None, stat_errors=None, label=None):
    edges = finite_list(edges, 'bin edges', minimum=2)
    values = finite_list(values, 'bin values')
    if len(edges) != len(values) + 1 or any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError('bin edges must increase and number one more than the values')
    if quantity not in QUANTITIES:
        raise ValueError(f'quantity must be one of {QUANTITIES}')
    if not isinstance(unit, str):
        raise ValueError('unit must be text')
    out = {'edges': edges, 'values': values, 'quantity': quantity, 'unit': unit}
    n = len(values)
    for key, value in (('errors', errors), ('error_low', error_low), ('error_high', error_high),
                       ('digitization_errors', digitization_errors), ('stat_errors', stat_errors)):
        if value is not None:
            vec = [abs(v) for v in finite_list(value, key)]
            if len(vec) != n:
                raise ValueError(f'{key} must have one entry per bin')
            out[key] = vec
    if (error_low is None) != (error_high is None):
        raise ValueError('give both error_low and error_high')
    if covariance is not None:
        cov = np.array([finite_list(row, 'covariance row') for row in covariance])
        if cov.shape != (n, n) or not np.allclose(cov, cov.T, rtol=1e-9, atol=1e-12):
            raise ValueError('covariance must be a symmetric matrix with one row per bin')
        out['covariance'] = cov.tolist()
    if label is not None:
        out['label'] = label
    return out


def _diag_cov(s):
    n = len(s['values'])
    if 'covariance' in s:
        return np.array(s['covariance'])
    if 'errors' in s:
        return np.diag(np.square(s['errors']))
    if 'error_low' in s:
        return np.diag(np.square((np.array(s['error_low']) + np.array(s['error_high'])) / 2))
    return None


def _widths(s):
    e = np.array(s['edges'])
    return np.diff(e)


def _scale_series(s, factor, *, x=False):
    s = deepcopy(s)
    if x:
        s['edges'] = [v * factor for v in s['edges']]
        return s
    s['values'] = [v * factor for v in s['values']]
    for key in ('errors', 'error_low', 'error_high', 'digitization_errors', 'stat_errors'):
        if key in s:
            s[key] = [abs(v * factor) for v in s[key]]
    if 'covariance' in s:
        s['covariance'] = (np.array(s['covariance']) * factor * factor).tolist()
    return s


def _scale_per_bin(s, factors):
    f = np.asarray(factors, float)
    s = deepcopy(s)
    s['values'] = (np.array(s['values']) * f).tolist()
    for key in ('errors', 'error_low', 'error_high', 'digitization_errors', 'stat_errors'):
        if key in s:
            s[key] = np.abs(np.array(s[key]) * f).tolist()
    if 'covariance' in s:
        s['covariance'] = (np.array(s['covariance']) * np.outer(f, f)).tolist()
    return s


def _linear_map(s, matrix, edges):
    m = np.array(matrix, float)
    s2 = deepcopy(s)
    s2['edges'] = list(map(float, edges))
    s2['values'] = (m @ np.array(s['values'])).tolist()
    cov = _diag_cov(s)
    for key in ('errors', 'error_low', 'error_high', 'covariance', 'stat_errors', 'digitization_errors'):
        s2.pop(key, None)
    if cov is not None:
        s2['covariance'] = (m @ cov @ m.T).tolist()
    for key in ('digitization_errors', 'stat_errors'):
        if key in s:
            s2[key] = np.sqrt(np.square(m) @ np.square(np.array(s[key]))).tolist()
    return s2


def _area(s):
    v = np.array(s['values'])
    return v * _widths(s) if s['quantity'] == 'density' else v


def transform(series, operations):
    """Apply declared operations in order; return (series, records)."""
    s = deepcopy(series)
    records = []
    for op in operations or []:
        if not isinstance(op, dict) or 'op' not in op:
            raise ValueError('each transformation needs an "op"')
        kind = op['op']
        rec = {'op': kind}
        if kind in ('fraction_to_density', 'density_to_fraction'):
            allowed = ('fraction', 'count') if kind == 'fraction_to_density' else ('density',)
            if s['quantity'] not in allowed:
                raise ValueError(f'{kind} needs a {" or ".join(allowed)} series, not {s["quantity"]}')
            w = _widths(s)
            s = _scale_per_bin(s, 1 / w if kind == 'fraction_to_density' else w)
            s['quantity'] = 'density' if kind == 'fraction_to_density' else op.get('quantity', 'fraction')
            if 'unit' in op:
                s['unit'] = op['unit']
                rec['unit'] = op['unit']
        elif kind == 'rebin':
            target = finite_list(op.get('edges'), 'rebin edges', minimum=2)
            old = s['edges']
            idx = []
            for t in target:
                hit = [i for i, e in enumerate(old) if math.isclose(e, t, rel_tol=EDGE_RTOL, abs_tol=1e-12)]
                if not hit:
                    raise ValueError(f'rebin edge {t} is not an existing bin edge; declare a rebin_matrix instead')
                idx.append(hit[0])
            if idx != sorted(idx) or len(set(idx)) != len(idx):
                raise ValueError('rebin edges must increase')
            if s['quantity'] == 'value':
                raise ValueError('a non-additive value series cannot be rebinned; relabel its quantity first')
            w = _widths(s)
            m = np.zeros((len(target) - 1, len(s['values'])))
            mapping = []
            for j, (a, b) in enumerate(zip(idx, idx[1:])):
                mapping.append(list(range(a, b)))
                for i in range(a, b):
                    m[j, i] = w[i] / (old[b] - old[a]) if s['quantity'] == 'density' else 1.0
            s = _keep_errors_form(s, _linear_map(s, m, target))
            rec.update({'edges': target, 'mapping': mapping})
        elif kind == 'rebin_matrix':
            target = finite_list(op.get('edges'), 'rebin edges', minimum=2)
            matrix = [finite_list(r, 'rebin matrix row') for r in op.get('matrix', [])]
            if len(matrix) != len(target) - 1 or any(len(r) != len(s['values']) for r in matrix):
                raise ValueError('rebin matrix must have one row per new bin and one column per old bin')
            _reason(op)
            s = _keep_errors_form(s, _linear_map(s, matrix, target), force_covariance=True)
            rec.update({'edges': target, 'matrix': matrix, 'reason': op['reason']})
        elif kind == 'unit':
            axis = op.get('axis', 'value')
            if axis == 'x':
                factor = unit_factor(op['from'], op['to'])
                s = _scale_series(s, factor, x=True)
                rec.update({'axis': 'x', 'from': op['from'], 'to': op['to'], 'factor': factor,
                            'note': 'bin edges only; convert a per-x density with its own value-unit step'})
            else:
                source = op.get('from', s['unit'])
                if source != s['unit']:
                    raise ValueError(f'unit conversion from {source!r} but the series is in {s["unit"]!r}')
                factor = unit_factor(source, op['to'])
                s = _scale_series(s, factor)
                s['unit'] = op['to']
                rec.update({'from': source, 'to': op['to'], 'factor': factor})
        elif kind == 'normalize':
            area = float(np.sum(_area(s)))
            if area == 0:
                raise ValueError('cannot normalise a series with zero area')
            if op.get('to') == 'unit_area':
                total = 1.0
            elif 'total' in op:
                total = finite_list([op['total']], 'normalisation total')[0]
            else:
                raise ValueError('normalize needs "to": "unit_area" or a declared "total"')
            factor = total / area
            s = _scale_series(s, factor)
            rec.update({'area_before': area, 'total': total, 'factor': factor,
                        'note': 'the normalisation total is treated as exact'})
        elif kind == 'scale':
            factor = finite_list([op.get('factor')], 'scale factor')[0]
            _reason(op)
            s = _scale_series(s, factor)
            rec.update({'factor': factor, 'reason': op['reason']})
        elif kind == 'relabel':
            _reason(op)
            if 'quantity' in op:
                if op['quantity'] not in QUANTITIES:
                    raise ValueError(f'quantity must be one of {QUANTITIES}')
                rec['quantity'] = [s['quantity'], op['quantity']]
                s['quantity'] = op['quantity']
            if 'unit' in op:
                rec['unit'] = [s['unit'], op['unit']]
                s['unit'] = op['unit']
            rec['reason'] = op['reason']
        elif kind == 'select':
            lo, hi = finite_list(op.get('range'), 'selected range', minimum=2)
            keep = [i for i, (a, b) in enumerate(zip(s['edges'], s['edges'][1:])) if a >= lo - 1e-12 and b <= hi + 1e-12]
            if not keep:
                raise ValueError('the selected range contains no complete bin')
            m = np.zeros((len(keep), len(s['values'])))
            for j, i in enumerate(keep):
                m[j, i] = 1.0
            s = _keep_errors_form(s, _linear_map(s, m, s['edges'][keep[0]:keep[-1] + 2]))
            rec['range'] = [lo, hi]
        else:
            raise ValueError(f'unknown transformation {kind!r}')
        records.append(rec)
    return s, records


def _keep_errors_form(old, new, force_covariance=False):
    """Prefer per-bin errors when the map keeps bins independent."""
    if 'covariance' not in new:
        return new
    cov = np.array(new['covariance'])
    if ('covariance' not in old) and not force_covariance and np.allclose(cov, np.diag(np.diag(cov))):
        new['errors'] = np.sqrt(np.diag(cov)).tolist()
        del new['covariance']
    return new


def _reason(op):
    if not isinstance(op.get('reason'), str) or not op['reason'].strip():
        raise ValueError(f'transformation {op["op"]} needs a stated reason')


# ===================================================================== binned metrics
def _match_bins(a, b):
    ea = list(zip(a['edges'], a['edges'][1:]))
    eb = list(zip(b['edges'], b['edges'][1:]))
    pairs, used = [], set()
    for i, (lo, hi) in enumerate(ea):
        for j, (rlo, rhi) in enumerate(eb):
            if j in used:
                continue
            if (math.isclose(lo, rlo, rel_tol=EDGE_RTOL, abs_tol=1e-12)
                    and math.isclose(hi, rhi, rel_tol=EDGE_RTOL, abs_tol=1e-12)):
                pairs.append((i, j))
                used.add(j)
                break
    ia = {i for i, _ in pairs}
    return pairs, [list(ea[i]) for i in range(len(ea)) if i not in ia], \
        [list(eb[j]) for j in range(len(eb)) if j not in used]


def _side_errors(s, idx, toward_above):
    if 'error_low' in s:
        lo, hi = np.array(s['error_low'])[idx], np.array(s['error_high'])[idx]
        return np.where(toward_above, hi, lo)
    if 'errors' in s:
        return np.array(s['errors'])[idx]
    if 'covariance' in s:
        return np.sqrt(np.diag(np.array(s['covariance'])))[idx]
    return np.zeros(len(idx))


def _check_bin_alignment(only_a, only_b):
    """Bins on one side only make a comparison incomplete; partially overlapping bins are refused."""
    for lo, hi in only_a:
        for rlo, rhi in only_b:
            if min(hi, rhi) - max(lo, rlo) > 1e-12 * max(1.0, abs(hi), abs(rhi)):
                raise ValueError(f'bin [{lo}, {hi}] overlaps reference bin [{rlo}, {rhi}] without matching edges; '
                                 'declare a rebin or rebin_matrix transformation')


def _systematics_covariance(agent, reference, ia, ib, systematics):
    """Covariance from declared systematics: relative per-bin sizes, fully correlated or uncorrelated."""
    n = len(ia)
    total = np.zeros((n, n))
    records = []
    for syst in systematics or []:
        if not isinstance(syst, dict) or not isinstance(syst.get('label'), str) or not syst['label'].strip():
            raise ValueError('each systematic needs a label')
        side = syst.get('applies_to')
        if side not in ('agent', 'reference'):
            raise ValueError('a systematic applies_to agent or reference')
        values = np.array((agent if side == 'agent' else reference)['values'])[ia if side == 'agent' else ib]
        rel = syst.get('relative')
        rel = np.full(n, finite_list([rel], 'relative systematic')[0]) if not isinstance(rel, list) \
            else np.array(finite_list(rel, 'relative systematic', minimum=n))[:n]
        size = np.abs(rel * values)
        correlation = syst.get('correlation', 'full')
        if correlation == 'full':
            total += np.outer(size, size)
        elif correlation == 'none':
            total += np.diag(size ** 2)
        else:
            raise ValueError('systematic correlation must be full or none')
        records.append({'label': syst['label'], 'applies_to': side, 'correlation': correlation,
                        'relative': rel.tolist()})
    return total, records


def _poisson_deviance(observed, predicted, reference_counts, reference_transformed):
    if reference_counts is None:
        return {'value': None, 'reason': 'the reference was not declared as raw observed counts'}
    if reference_counts != 'raw_observed':
        raise ValueError('reference_counts must be raw_observed when declared')
    if reference_transformed:
        raise ValueError('Poisson deviance needs the untransformed raw observed counts; weighted or rescaled '
                         'counts are refused')
    if np.any(observed < 0) or np.any(np.abs(observed - np.round(observed)) > 1e-9):
        raise ValueError('Poisson deviance needs raw integer observed counts; weighted counts are refused')
    if np.any(predicted < 0) or np.any((predicted == 0) & (observed > 0)):
        return {'value': None, 'reason': 'a prediction is zero or negative where counts were observed'}
    with np.errstate(divide='ignore', invalid='ignore'):
        term = np.where(observed > 0, observed * np.log(np.where(observed > 0, observed, 1) /
                                                       np.where(predicted > 0, predicted, 1)), 0.0)
    value = float(2 * np.sum(predicted - observed + term))
    return {'value': value, 'ndf': len(observed), 'basis': 'raw integer observed counts'}


def _gaussian_chi2(residual, covariance):
    from ravel.workflow.quantitative_predictive_checks import gaussian_distance
    result = gaussian_distance(residual, covariance, {'equilibrated_condition_max': 1e12}, np)
    if result.get('status') != 'evaluated':
        return None, result.get('status', 'not evaluated').replace('_', ' ')
    return result['value'], None


def _diagnosis(metrics):
    """Advisory 'compatible with' hint; it never triggers a correction."""
    note = 'Advisory only: the hint never triggers a correction or a change of inputs.'
    chi2 = metrics.get('chi2') or {}
    raw, shape, dnorm = metrics.get('relative_l2_raw'), metrics.get('relative_l2_shape'), metrics.get('delta_norm')
    if raw is not None and raw < 1e-12:
        hint, why = 'agreement', 'the series are identical on matched bins'
    elif chi2.get('p_value') is not None and chi2['p_value'] >= 0.05:
        hint, why = 'statistics', f'chi2 p-value {chi2["p_value"]:.3g} with the supplied uncertainties'
    elif dnorm is not None and shape is not None and abs(dnorm) > 0 and shape <= 0.25 * abs(dnorm):
        hint, why = 'normalization', f'shape distance {shape:.3g} is small next to the normalisation offset {dnorm:+.3g}'
    elif shape is not None and shape > 0:
        hint, why = 'selection or detector', f'the unit-area shapes differ (shape distance {shape:.3g})'
    else:
        hint, why = 'undetermined', 'the available metrics do not separate normalisation from shape'
    return {'compatible_with': hint, 'evidence': why, 'note': note}


def compare_binned(agent, reference, tolerances=None, *, reference_counts=None, systematics=None,
                   reference_transformed=False):
    """Physics-fidelity comparison of two binned series on exactly matched bins."""
    if agent['quantity'] != reference['quantity'] or agent['unit'] != reference['unit']:
        raise ValueError(f'quantity/unit differ: agent {agent["quantity"]} in {agent["unit"]!r}, reference '
                         f'{reference["quantity"]} in {reference["unit"]!r}; declare the transformation')
    pairs, only_a, only_b = _match_bins(agent, reference)
    _check_bin_alignment(only_a, only_b)
    if not pairs:
        raise ValueError('no bins match between the agent and reference series')
    ia = [i for i, _ in pairs]
    ib = [j for _, j in pairs]
    a, b = np.array(agent['values'])[ia], np.array(reference['values'])[ib]
    k = len(pairs)
    metrics = {'bins': k, 'n_bins': k, 'n_filled': int(np.sum(b != 0))}
    norm_b = float(np.linalg.norm(b))
    metrics['relative_l2'] = float(np.linalg.norm(a - b) / norm_b) if norm_b else None
    metrics['relative_l2_raw'] = metrics['relative_l2']
    ca = _area(agent)[ia]
    cb = _area(reference)[ib]
    sa, sb = float(np.sum(ca)), float(np.sum(cb))
    metrics['normalization_ratio'] = sa / sb if sb else None
    metrics['delta_norm'] = sa / sb - 1 if sb else None
    metrics['normalization_deviation'] = abs(sa / sb - 1) if sb else None
    shape_reason = 'single_bin' if k < 2 else ('zero_total' if not sa or not sb else None)
    if shape_reason is None:
        na, nb = ca / sa, cb / sb
        metrics['shape_l2'] = float(np.linalg.norm(na - nb) / np.linalg.norm(nb))
        dev = np.abs(na - nb)
        metrics['d_bar'] = float(0.5 * np.sum(dev))
        metrics['d_max'] = float(np.max(dev))
        metrics['concentration_bound'] = 2.0 / k
        if metrics['d_bar'] > 0:
            metrics['concentration'] = metrics['d_max'] / metrics['d_bar']
        else:
            metrics['concentration'], metrics['concentration_reason'] = None, 'd_bar_zero'
    else:
        metrics.update({'shape_l2': None, 'shape_reason': shape_reason, 'd_bar': None, 'd_max': None,
                        'concentration': None, 'concentration_reason': shape_reason})
    metrics['relative_l2_shape'] = metrics['shape_l2']
    with np.errstate(divide='ignore', invalid='ignore'):
        metrics['ratio'] = [float(x) if math.isfinite(x) else None for x in a / b]
    above = a > b
    ea = _side_errors(agent, ia, ~above)
    eb = _side_errors(reference, ib, above)
    edig = np.array(reference.get('digitization_errors', [0.0] * len(reference['values'])))[ib]
    sigma = np.sqrt(ea ** 2 + eb ** 2 + edig ** 2)
    if np.all(sigma > 0):
        pulls = (a - b) / sigma
        metrics['pulls'] = [float(p) for p in pulls]
        metrics['max_abs_pull'] = float(np.max(np.abs(pulls)))
        metrics['mean_pull'] = float(np.mean(pulls))
    else:
        metrics['pulls'] = None
        metrics['max_abs_pull'] = None
    cov_a, cov_b = _diag_cov(agent), _diag_cov(reference)
    correlated = any(c is not None and not np.allclose(c, np.diag(np.diag(c)))
                     for c in (cov_a, cov_b))
    metrics['pull_basis'] = ('correlated covariance supplied; chi2 uses the full covariance' if correlated
                             else 'uncorrelated assumption')
    cov_s, syst_records = _systematics_covariance(agent, reference, ia, ib, systematics)
    if cov_a is not None or cov_b is not None or np.any(edig > 0) or syst_records:
        total = np.zeros((k, k))
        parts = []
        if cov_a is not None:
            total += cov_a[np.ix_(ia, ia)]
            parts.append('agent')
        if cov_b is not None:
            total += cov_b[np.ix_(ib, ib)]
            parts.append('reference')
        if np.any(edig > 0):
            total += np.diag(edig ** 2)
            parts.append('digitisation')
        if syst_records:
            total += cov_s
            parts.append('declared systematics')
        value, reason = _gaussian_chi2(a - b, total)
        if value is None:
            metrics['chi2'] = {'value': None, 'reason': f'the combined covariance is {reason}'}
        else:
            from scipy.stats import chi2 as chi2_dist
            metrics['chi2'] = {'value': value, 'ndf': k, 'per_ndf': value / k,
                               'p_value': float(chi2_dist.sf(value, k)),
                               'covariance': ' plus '.join(parts) + ' covariance'}
            metrics['chi2_per_ndf'] = value / k
            metrics['chi2_p_value'] = metrics['chi2']['p_value']
    else:
        metrics['chi2'] = {'value': None, 'reason': 'no uncertainties were supplied'}
    metrics['goodness_of_fit'] = {
        'chi2': metrics['chi2'].get('value'), 'systematics': syst_records,
        **({} if syst_records else {'reason': 'no systematic uncertainties were declared; the chi2 uses the '
                                              'supplied statistical and covariance terms only'})}
    metrics['poisson_deviance'] = _poisson_deviance(b, a, reference_counts, reference_transformed)
    if np.all(ca >= 0) and np.all(cb >= 0) and sa > 0 and sb > 0:
        da = np.cumsum(ca) / sa
        db = np.cumsum(cb) / sb
        stat = float(np.max(np.abs(da - db)))
        metrics['ks'] = {'statistic': stat, 'note': 'binned statistic on matched bins'}
        metrics['ks_statistic'] = stat
    else:
        metrics['ks'] = {'statistic': None, 'reason': 'needs non-negative contents'}
    status = 'complete' if not only_a and not only_b else 'incomplete'
    out = {'comparison': 'binned', 'status': status, 'metrics': metrics,
           'matched_bins': [[agent['edges'][i], agent['edges'][i + 1]] for i in ia],
           'unmatched': {'agent': only_a, 'reference': only_b},
           'quantity': agent['quantity'], 'unit': agent['unit'],
           'diagnosis_hint': _diagnosis(metrics)}
    return _verdicts(out, tolerances)


def compare_scalar(prediction, reference, tolerances=None):
    """Pull, relative deviation and resolving power of one predicted number against a reference."""
    p, r = (finite_list([d.get('value')], f'{w} value')[0] for d, w in ((prediction, 'prediction'), (reference, 'reference')))
    sp = abs(finite_list([prediction.get('uncertainty', 0.0)], 'prediction uncertainty')[0])
    sr = abs(finite_list([reference.get('uncertainty', 0.0)], 'reference uncertainty')[0])
    total = math.hypot(sp, sr)
    out = {'comparison': 'scalar', 'status': 'complete',
           'metrics': {'difference': p - r,
                       'relative_deviation': (p - r) / abs(r) if r else None,
                       'pull': (p - r) / total if total else None,
                       'resolving_power': sp / sr if sr else None}}
    out['metrics']['abs_pull'] = abs(out['metrics']['pull']) if out['metrics']['pull'] is not None else None
    out.update({k: out['metrics'][k] for k in ('pull', 'resolving_power', 'relative_deviation')})
    out['note'] = 'resolving power is the prediction uncertainty over the reference uncertainty'
    return _verdicts(out, tolerances)


def _interp_curve(curve, xs, fx, fy, log_y):
    cx, cy = np.array(curve['x'], float), np.array(curve['y'], float)
    order = np.argsort(cx)
    tx, ty = fx(cx[order]), fy(cy[order])
    t = fx(xs)
    inside = (t >= tx.min()) & (t <= tx.max())
    v = np.interp(t, tx, ty)
    return (np.power(10.0, v) if log_y else v), inside


def compare_curves(agent, reference, axes, at=None):
    """Relative deviation of the agent curve at the reference x points, or at declared x values."""
    fx = _scaler(axes.get('x', {}))
    fy = _scaler(axes.get('y', {}))
    if at is not None:
        xs = np.array(finite_list(at, 'declared comparison points'))
        log_y = axes.get('y', {}).get('scale') == 'log'
        va, ina = _interp_curve(agent, xs, fx, fy, log_y)
        vr, inr = _interp_curve(reference, xs, fx, fy, log_y)
        inside = ina & inr
        if not np.any(inside):
            raise ValueError('no declared point lies on both curves')
        with np.errstate(divide='ignore', invalid='ignore'):
            dev = np.abs(va[inside] - vr[inside]) / np.abs(vr[inside])
        dev = dev[np.isfinite(dev)]
        return {'comparison': 'curve', 'points': int(np.sum(inside)), 'outside_overlap': int(np.sum(~inside)),
                'at': xs[inside].tolist(), 'max_relative_deviation': float(np.max(dev)),
                'mean_relative_deviation': float(np.mean(dev)), 'deviations': [float(d) for d in dev]}
    ax_, ay = np.array(agent['x'], float), np.array(agent['y'], float)
    rx, ry = np.array(reference['x'], float), np.array(reference['y'], float)
    order = np.argsort(ax_)
    tx, ty = fx(ax_[order]), fy(ay[order])
    trx = fx(rx)
    inside = (trx >= tx.min()) & (trx <= tx.max())
    if not np.any(inside):
        raise ValueError('the curves share no x range')
    interp = np.interp(trx[inside], tx, ty)
    back = np.power(10.0, interp) if axes.get('y', {}).get('scale') == 'log' else interp
    with np.errstate(divide='ignore', invalid='ignore'):
        dev = np.abs(back - ry[inside]) / np.abs(ry[inside])
    dev = dev[np.isfinite(dev)]
    return {'comparison': 'curve', 'points': int(np.sum(inside)),
            'outside_overlap': int(np.sum(~inside)),
            'max_relative_deviation': float(np.max(dev)), 'mean_relative_deviation': float(np.mean(dev)),
            'deviations': [float(d) for d in dev]}


def _scaler(axis):
    scale = axis.get('scale', 'linear')
    if scale == 'log':
        def f(v):
            v = np.asarray(v, float)
            if np.any(v <= 0):
                raise ValueError('a logarithmic axis needs positive coordinates')
            return np.log10(v)
        return f
    if scale != 'linear':
        raise ValueError('axis scale must be linear or log')
    return lambda v: np.asarray(v, float)


def _normaliser(axes, *point_sets):
    """Map data coordinates to [0, 1] axis fractions over the declared (or joint) range."""
    fx, fy = _scaler(axes.get('x', {})), _scaler(axes.get('y', {}))
    ranges = []
    for key, f in (('x', fx), ('y', fy)):
        rng = axes.get(key, {}).get('range')
        if rng is not None:
            lo, hi = f(finite_list(rng, f'{key} range', minimum=2))
        else:
            vals = np.concatenate([f(np.asarray(p[key], float)) for p in point_sets])
            lo, hi = float(vals.min()), float(vals.max())
        if hi <= lo:
            raise ValueError(f'{key} axis range must be positive')
        ranges.append((lo, hi))

    def apply(xs, ys):
        return np.column_stack([(fx(xs) - ranges[0][0]) / (ranges[0][1] - ranges[0][0]),
                                (fy(ys) - ranges[1][0]) / (ranges[1][1] - ranges[1][0])])
    return apply, ranges


def _resample(points, spacing):
    out = [points[:1]]
    for p, q in zip(points[:-1], points[1:]):
        n = max(1, int(math.ceil(np.linalg.norm(q - p) / spacing)))
        t = np.linspace(0, 1, n + 1)[1:, None]
        out.append(p + t * (q - p))
    return np.vstack(out)


_TIPS = {'max_x': (0, 1), 'min_x': (0, -1), 'max_y': (1, 1), 'min_y': (1, -1)}


def _tip(segments, direction):
    axis, sign = _TIPS[direction]
    best = None
    for seg in segments:
        pts = np.column_stack([np.asarray(seg['x'], float), np.asarray(seg['y'], float)])
        i = int(np.argmax(sign * pts[:, axis]))
        if best is None or sign * pts[i, axis] > sign * best[axis]:
            best = pts[i]
    return [float(best[0]), float(best[1])]


def compare_contours(agent_segments, reference_segments, axes, spacing=1e-3, tip=None):
    from scipy.spatial import cKDTree
    if not agent_segments or not reference_segments:
        raise ValueError('both contours need at least one segment')
    apply, ranges = _normaliser(axes, *agent_segments, *reference_segments)

    def cloud(segments):
        parts = []
        for seg in segments:
            pts = apply(np.asarray(seg['x'], float), np.asarray(seg['y'], float))
            parts.append(_resample(pts, spacing) if len(pts) > 1 else pts)
        return np.vstack(parts)
    a, b = cloud(agent_segments), cloud(reference_segments)
    dab, _ = cKDTree(b).query(a)
    dba, _ = cKDTree(a).query(b)
    out = {'comparison': 'contour', 'hausdorff_max': float(max(dab.max(), dba.max())),
           'hausdorff_mean': float((dab.mean() + dba.mean()) / 2),
           'directed_max': {'agent_to_reference': float(dab.max()), 'reference_to_agent': float(dba.max())},
           'space': 'axis fraction of the declared ranges (log axes in decades)',
           'ranges': [list(r) for r in ranges], 'sampling': spacing}
    if tip is not None:
        if tip not in _TIPS:
            raise ValueError(f'contour tip direction must be one of {sorted(_TIPS)}')
        ta, tr = _tip(agent_segments, tip), _tip(reference_segments, tip)
        out['tip'] = {'direction': tip, 'agent': ta, 'reference': tr,
                      'difference': [ta[0] - tr[0], ta[1] - tr[1]]}
    return out


def _region_polygons(region, ranges, apply):
    polys = []
    if 'polygons' in region:
        for p in region['polygons']:
            polys.append(apply(np.asarray(p['x'], float), np.asarray(p['y'], float)))
    elif 'curve' in region:
        c = region['curve']
        pts = apply(np.asarray(c['x'], float), np.asarray(c['y'], float))
        close = region.get('close')
        if close == 'below':
            extra = [(pts[-1, 0], 0.0), (pts[0, 0], 0.0)]
        elif close == 'above':
            extra = [(pts[-1, 0], 1.0), (pts[0, 0], 1.0)]
        elif close == 'left':
            extra = [(0.0, pts[-1, 1]), (0.0, pts[0, 1])]
        elif close == 'right':
            extra = [(1.0, pts[-1, 1]), (1.0, pts[0, 1])]
        elif close == 'self':
            extra = []
        else:
            raise ValueError('an open curve region needs "close": below, above, left, right or self')
        polys.append(np.vstack([pts, np.array(extra).reshape(-1, 2)]))
    else:
        raise ValueError('a region needs polygons or a curve with a declared closure')
    return polys


def region_iou(agent_region, reference_region, axes, grid=400):
    from matplotlib.path import Path as MplPath
    point_sets = []
    for region in (agent_region, reference_region):
        if 'polygons' in region:
            point_sets.extend(region['polygons'])
        elif 'curve' in region:
            point_sets.append(region['curve'])
    apply, ranges = _normaliser(axes, *point_sets)
    centres = (np.arange(grid) + 0.5) / grid
    gx, gy = np.meshgrid(centres, centres)
    flat = np.column_stack([gx.ravel(), gy.ravel()])

    def mask(region):
        m = np.zeros(len(flat), bool)
        for poly in _region_polygons(region, ranges, apply):
            m ^= MplPath(poly).contains_points(flat)
        return m
    ma, mb = mask(agent_region), mask(reference_region)
    union = int(np.sum(ma | mb))
    if union == 0:
        raise ValueError('both regions are empty inside the declared ranges')
    return {'comparison': 'region', 'iou': float(np.sum(ma & mb) / union),
            'agent_fraction': float(ma.mean()), 'reference_fraction': float(mb.mean()),
            'area_ratio': float(ma.mean() / mb.mean()) if mb.any() else None,
            'grid': grid, 'space': 'axis fraction of the declared ranges (log axes in decades)',
            'resolution': 1.0 / grid}


RAW_L2 = {'relative_l2', 'relative_l2_raw'}
SIGNED = {'delta_norm', 'mean_pull', 'pull', 'difference', 'relative_deviation'}


def check_basis(name, basis):
    """A tolerance basis is supervised spread of independent reference reruns, published precision,
    or a cited community convention."""
    if not isinstance(basis, dict) or basis.get('kind') not in ('supervised_spread', 'published_precision',
                                                                 'community'):
        raise ValueError(f'tolerance for {name} needs a basis of kind supervised_spread, published_precision '
                         'or community')
    kind = basis['kind']
    if kind == 'supervised_spread':
        n = basis.get('n')
        sha = basis.get('evidence_sha256')
        if type(n) is not int or n < 2 or not isinstance(sha, str) or len(sha) != 64 \
                or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError(f'tolerance basis for {name}: supervised_spread needs n >= 2 and evidence_sha256')
        if basis.get('evidence') != 'independent reference reruns':
            raise ValueError(f'tolerance basis for {name}: the spread must come from independent reference reruns, '
                             'not from the candidate runs')
    else:
        field = 'source' if kind == 'published_precision' else 'citation'
        if not isinstance(basis.get(field), str) or not basis[field].strip():
            raise ValueError(f'tolerance basis for {name}: {kind} needs a {field}')
    return dict(basis)


def _verdicts(out, tolerances):
    verdicts = {}
    metrics = out.get('metrics', out)
    if tolerances and set(tolerances) <= RAW_L2:
        raise ValueError('raw relative L2 never decides a verdict alone; add a shape, normalisation, chi2 or '
                         'pull tolerance')
    for name, rule in (tolerances or {}).items():
        if not isinstance(rule, dict):
            raise ValueError(f'tolerance for {name} needs pass, warn and a basis')
        basis = check_basis(name, rule.get('basis'))
        p, w = finite_list([rule.get('pass'), rule.get('warn')], f'{name} tolerance', minimum=2)
        higher = rule.get('direction', 'higher' if name in HIGHER_IS_BETTER else 'lower') == 'higher'
        value = metrics.get(name)
        if isinstance(value, dict):
            value = value.get('value', value.get('statistic'))
        if value is not None and name in SIGNED:
            value = abs(value)
        if value is None:
            verdict = 'NOT_AVAILABLE'
        elif higher:
            verdict = 'PASS' if value >= p * (1 - 1e-9) else ('WARN' if value >= w * (1 - 1e-9) else 'FAIL')
        else:
            verdict = 'PASS' if value <= p * (1 + 1e-9) else ('WARN' if value <= w * (1 + 1e-9) else 'FAIL')
        verdicts[name] = {'value': value, 'pass': p, 'warn': w, 'direction': 'higher' if higher else 'lower',
                          'basis': basis, 'verdict': verdict}
    out['verdicts'] = verdicts
    if out.get('status') == 'incomplete' or any(v['verdict'] == 'NOT_AVAILABLE' for v in verdicts.values()):
        out['verdict'] = 'INCOMPLETE'
    elif not verdicts:
        out['verdict'] = 'NOT_ASSESSED'
    else:
        order = {'PASS': 0, 'WARN': 1, 'FAIL': 2}
        out['verdict'] = max((v['verdict'] for v in verdicts.values()), key=order.get)
    return out


# ===================================================================== sources
class _Recorder:
    def __init__(self):
        self.pins = {}

    def read(self, path):
        path = Path(path).absolute()
        if str(path) not in self.pins:
            self.pins[str(path)] = pin(path)
        return load_json(path)


def _from_hepdata(table, column, quantity, unit=None):
    indep = table.get('independent_variables') or []
    deps = table.get('dependent_variables') or []
    if len(indep) != 1:
        raise ValueError('a one-dimensional HEPData table is required')
    if isinstance(column, int):
        dep = deps[column]
    else:
        matches = [d for d in deps if d.get('header', {}).get('name') == column]
        if len(matches) != 1:
            raise ValueError(f'HEPData column {column!r} not found exactly once')
        dep = matches[0]
    edges = []
    for i, v in enumerate(indep[0]['values']):
        if 'low' not in v or 'high' not in v:
            raise ValueError('HEPData independent values need low and high bin edges')
        if edges and not math.isclose(edges[-1], float(v['low']), rel_tol=EDGE_RTOL, abs_tol=1e-12):
            raise ValueError('HEPData bins must be contiguous; select a contiguous range')
        if not edges:
            edges.append(float(v['low']))
        edges.append(float(v['high']))
    values, lows, highs, stats = [], [], [], []
    for row in dep['values']:
        value = float(row['value'])
        lo2 = hi2 = 0.0
        stat = None
        for err in row.get('errors', []):
            if 'symerror' in err:
                e = _err_value(err['symerror'], value)
                minus, plus = e, e
            elif 'asymerror' in err:
                plus = _err_value(err['asymerror']['plus'], value)
                minus = _err_value(err['asymerror']['minus'], value)
            else:
                continue
            if plus >= 0 >= minus:
                up, down = plus, -minus
            elif minus >= 0 >= plus:
                up, down = minus, -plus
            else:                                  # both written as magnitudes
                up, down = abs(plus), abs(minus)
            hi2 += up ** 2
            lo2 += down ** 2
            if 'stat' in str(err.get('label', '')).lower():
                stat = math.sqrt(((up + down) / 2) ** 2 + (stat or 0.0) ** 2)
        values.append(value)
        lows.append(math.sqrt(lo2))
        highs.append(math.sqrt(hi2))
        stats.append(stat)
    out = binned(edges, values, error_low=lows, error_high=highs, quantity=quantity,
                 unit=unit if unit is not None else dep.get('header', {}).get('units', ''))
    if all(s is not None for s in stats):
        out['stat_errors'] = stats
    return out


def _err_value(raw, value):
    if isinstance(raw, str):
        text = raw.strip()
        if text.endswith('%'):
            return float(text[:-1]) / 100.0 * abs(value)
        return float(text)
    return float(raw)


def _from_binned_values(doc):
    if len(doc.get('axes', [])) != 1:
        raise ValueError('a one-dimensional binned_values result is required')
    edges = []
    for b in doc['bins']:
        lo, hi = float(b['low'][0]), float(b['high'][0])
        if edges and not math.isclose(edges[-1], lo, rel_tol=EDGE_RTOL, abs_tol=1e-12):
            raise ValueError('binned_values bins must be contiguous')
        if not edges:
            edges.append(lo)
        edges.append(hi)
    quantity = 'density' if doc.get('representation') == 'differential' else 'count'
    return binned(edges, [b['value'] for b in doc['bins']], errors=[b.get('uncertainty', 0.0) for b in doc['bins']],
                  quantity=quantity, unit=doc['unit'])


def _digitized_series(doc, name):
    from .digitize import load_series
    return load_series(doc, name)


def load_source(source, base, context=None, recorder=None):
    """Resolve a declared source into a binned series, a curve, contour segments or a region."""
    recorder = recorder or _Recorder()
    if not isinstance(source, dict):
        raise ValueError('a source must be an object')
    if 'operation' in source:
        if not context or source['operation'] not in context:
            raise ValueError(f'unknown operation {source["operation"]!r}')
        doc = context[source['operation']]
        return _from_digitized(doc, source)
    if 'digitized' in source:
        doc = recorder.read(resolve(base, source['digitized']))
        return _from_digitized(doc, source)
    if 'hepdata' in source:
        doc = recorder.read(resolve(base, source['hepdata']))
        doc = json_pointer(doc, source.get('pointer'))
        return _from_hepdata(doc, source.get('column', 0), source.get('quantity', 'value'), source.get('unit'))
    if 'inference' in source:
        return _from_inference(recorder.read(resolve(base, source['inference'])), source)
    if 'path' in source:
        doc = json_pointer(recorder.read(resolve(base, source['path'])), source.get('pointer'))
    else:
        doc = {k: v for k, v in source.items() if k not in ('label',)}
    if isinstance(doc, dict) and doc.get('kind') == 'digitized-series':
        return _from_digitized(doc, source)
    if isinstance(doc, dict) and doc.get('kind') == 'plot-coordinate-series':
        return {'segments': _series_segments(doc.get('series') or [], source.get('series'))}
    if isinstance(doc, dict) and doc.get('kind') == 'binned_values':
        return _from_binned_values(doc)
    if isinstance(doc, dict) and 'independent_variables' in doc:
        return _from_hepdata(doc, source.get('column', 0), source.get('quantity', 'value'), source.get('unit'))
    if isinstance(doc, dict) and 'edges' in doc:
        keys = ('errors', 'error_low', 'error_high', 'covariance', 'digitization_errors', 'stat_errors', 'label')
        return binned(doc['edges'], doc['values'], quantity=doc.get('quantity', source.get('quantity', 'count')),
                      unit=doc.get('unit', source.get('unit', 'events')), **{k: doc[k] for k in keys if k in doc})
    if isinstance(doc, dict) and 'value' in doc and not ({'edges', 'x', 'y'} & set(doc)):
        out = {'value': finite_list([doc['value']], 'scalar value')[0]}
        if 'uncertainty' in doc:
            out['uncertainty'] = abs(finite_list([doc['uncertainty']], 'scalar uncertainty')[0])
        return out
    if isinstance(doc, dict) and ('x' in doc and 'y' in doc):
        return {'x': finite_list(doc['x'], 'x'), 'y': finite_list(doc['y'], 'y')}
    if isinstance(doc, dict) and ('polygons' in doc or 'curve' in doc or 'segments' in doc):
        return doc
    raise ValueError('source is not a binned series, curve, contour, region, HEPData table or digitized series')


def _series_segments(rows, wanted=None):
    """Polylines from plot-coordinate-series rows; records without coordinates are skipped."""
    segments = []
    for row in rows:
        if wanted is not None and row.get('id') != wanted and row.get('label') != wanted:
            continue
        pts = [(r.get('x'), r.get('y')) for r in row.get('records', [])]
        pts = [(float(x), float(y)) for x, y in pts if isinstance(x, (int, float)) and isinstance(y, (int, float))]
        if len(pts) >= 2:
            segments.append({'x': [p[0] for p in pts], 'y': [p[1] for p in pts]})
    if not segments:
        raise ValueError('the coordinate series holds no polyline with two or more points')
    return segments


def inference_result(doc, wanted, quantity=None):
    """One result row of a statistics inference record, by name or index."""
    if not isinstance(doc, dict) or doc.get('kind') != 'inference':
        raise ValueError('an inference record is required')
    rows = doc.get('results') or []
    if isinstance(wanted, int) and not isinstance(wanted, bool):
        candidates = [r for r in rows if quantity is None or r.get('quantity') == quantity]
        if not 0 <= wanted < len(candidates):
            raise ValueError(f'inference result index {wanted} is out of range')
        return candidates[wanted]
    matches = [r for r in rows if r.get('name') == wanted and (quantity is None or r.get('quantity') == quantity)]
    if len(matches) != 1:
        raise ValueError(f'inference result {wanted!r} not found exactly once')
    return matches[0]


def _from_inference(doc, source):
    row = inference_result(doc, source.get('result', 0))
    if row.get('quantity') == 'contour':
        return {'segments': _series_segments(row.get('series') or [], source.get('series'))}
    raise ValueError(f'inference result {row.get("name")!r} is {row.get("quantity")}; draw grid values through '
                     'a parameter-plane grid')


def _from_digitized(doc, source):
    series = _digitized_series(doc, source.get('series'))
    shape = source.get('as', 'curve')
    if shape == 'contour':
        return {'segments': [{'x': s['x'], 'y': s['y']} for s in series['segments']]}
    if shape == 'region':
        if 'polygon' in series:
            return {'polygons': [{'x': series['polygon']['x'], 'y': series['polygon']['y']}]}
        xs, ys = _joined(series)
        return {'curve': {'x': xs, 'y': ys}, 'close': source.get('close')}
    xs, ys, us = _joined(series, with_uncertainty=True)
    if shape == 'curve':
        return {'x': xs, 'y': ys, 'y_uncertainty': us}
    if shape == 'bins':
        edges = finite_list(source.get('edges'), 'bin edges for the digitized series', minimum=2)
        order = np.argsort(xs)
        x, y, u = np.array(xs)[order], np.array(ys)[order], np.array(us)[order]
        centres = (np.array(edges[:-1]) + np.array(edges[1:])) / 2
        if centres.min() < x.min() or centres.max() > x.max():
            raise ValueError('declared bin centres lie outside the digitized curve')
        values = np.interp(centres, x, y)
        dig = np.interp(centres, x, u)
        return binned(edges, values.tolist(), digitization_errors=dig.tolist(),
                      quantity=source.get('quantity', 'value'),
                      unit=source.get('unit', doc.get('axes', {}).get('y', {}).get('unit', '')))
    raise ValueError('a digitized source is used "as" curve, bins, contour or region')


def _joined(series, with_uncertainty=False):
    xs, ys, us = [], [], []
    for seg in series['segments']:
        xs.extend(seg['x'])
        ys.extend(seg['y'])
        us.extend(seg.get('y_uncertainty', [0.0] * len(seg['x'])))
    return (xs, ys, us) if with_uncertainty else (xs, ys)


# ===================================================================== specification
def compare(spec, base, context=None, recorder=None):
    """Evaluate one comparison specification (already loaded); return the comparison object.

    The same object feeds reports, check-ins and figure overlays (see ``summary_lines``).
    """
    recorder = recorder or _Recorder()
    allowed = {'schema_version', 'kind', 'agent', 'reference', 'transformations', 'tolerances', 'axes', 'grid',
               'description', 'label', 'reference_counts', 'systematics', 'at', 'tip'}
    if set(spec) - allowed:
        raise ValueError(f'unknown comparison fields: {sorted(set(spec) - allowed)}')
    kind = spec.get('kind', 'binned')
    agent = load_source(spec.get('agent'), base, context, recorder)
    reference = load_source(spec.get('reference'), base, context, recorder)
    tolerances = spec.get('tolerances')
    applied = {'agent': [], 'reference': []}
    if kind == 'binned':
        ops = spec.get('transformations') or {}
        agent, applied['agent'] = transform(agent, ops.get('agent'))
        reference, applied['reference'] = transform(reference, ops.get('reference'))
        result = compare_binned(agent, reference, tolerances, reference_counts=spec.get('reference_counts'),
                                systematics=spec.get('systematics'),
                                reference_transformed=bool(applied['reference']))
        result['agent_series'], result['reference_series'] = agent, reference
    else:
        if spec.get('transformations'):
            raise ValueError('transformations apply to binned comparisons; convert curve units before digitising')
        axes = spec.get('axes') or {}
        if kind in ('curve', 'contour', 'region'):
            for key in ('x', 'y'):
                if 'scale' not in axes.get(key, {}):
                    raise ValueError(f'a {kind} comparison needs a declared metric space: the {key} axis scale')
        if kind == 'curve':
            result = _verdicts(compare_curves(agent, reference, axes, at=spec.get('at')), tolerances)
        elif kind == 'contour':
            result = _verdicts(compare_contours(_segments(agent), _segments(reference), axes, tip=spec.get('tip')),
                               tolerances)
        elif kind == 'region':
            result = _verdicts(region_iou(agent, reference, axes, int(spec.get('grid', 400))), tolerances)
        elif kind == 'scalar':
            result = compare_scalar(agent, reference, tolerances)
        else:
            raise ValueError('comparison kind must be binned, curve, contour, region or scalar')
    result.update({'schema_version': 1, 'kind': 'reference-comparison', 'comparison_kind': kind,
                   'transformations': applied, 'machine_review_only': True,
                   'limitations': ['A machine comparison under declared transformations; it is not physics review.',
                                   'Digitised references are approximate; their uncertainty is included only where '
                                   'the source carries it.']})
    if spec.get('label'):
        result['label'] = spec['label']
    result['summary'] = summary_lines(result)
    return result


_METRIC_WORDS = {
    'relative_l2_raw': 'Relative difference (L2)', 'relative_l2_shape': 'Shape difference (L2, unit area)',
    'delta_norm': 'Normalisation offset', 'd_bar': 'Total variation distance', 'max_abs_pull': 'Largest pull',
    'chi2_per_ndf': 'Chi-square per bin', 'hausdorff_max': 'Largest contour distance (axis fraction)',
    'hausdorff_mean': 'Mean contour distance (axis fraction)', 'iou': 'Region overlap (intersection over union)',
    'max_relative_deviation': 'Largest relative deviation', 'pull': 'Pull', 'resolving_power': 'Resolving power',
}
_HINT_WORDS = {'normalization': 'a normalisation difference', 'selection or detector':
               'a selection or detector-response difference', 'statistics': 'statistical fluctuation',
               'agreement': 'agreement', 'undetermined': 'no single cause'}


def summary_lines(comparison):
    """Short natural-language lines describing a comparison object, for figure annotations and reports."""
    metrics = comparison.get('metrics', comparison)
    lines = []
    verdict = comparison.get('verdict')
    if verdict and verdict != 'NOT_ASSESSED':
        lines.append(f'Machine comparison: {verdict.lower().replace("_", " ")}')
    for key in ('relative_l2_raw', 'relative_l2_shape', 'delta_norm', 'chi2_per_ndf', 'max_abs_pull',
                'hausdorff_max', 'hausdorff_mean', 'iou', 'max_relative_deviation', 'pull', 'resolving_power'):
        value = metrics.get(key, comparison.get(key))
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            text = f'{value:+.3g}' if key in ('delta_norm', 'pull') else f'{value:.3g}'
            lines.append(f'{_METRIC_WORDS[key]}: {text}')
        if len(lines) >= 5:
            break
    hint = comparison.get('diagnosis_hint')
    if hint:
        lines.append('Compatible with ' + _HINT_WORDS.get(hint['compatible_with'], 'no single cause'))
    if comparison.get('status') == 'incomplete':
        lines.append('Incomplete: some bins exist on one side only')
    return lines


def _segments(source):
    if 'segments' in source:
        return source['segments']
    if 'x' in source and 'y' in source:
        return [{'x': source['x'], 'y': source['y']}]
    raise ValueError('a contour source needs segments or x/y points')


def run_spec(spec_path, out_path, context=None):
    spec, base = load_spec(spec_path)
    recorder = _Recorder()
    recorder.pins[str(Path(spec_path).absolute())] = pin(spec_path)
    result = compare(spec, base, context, recorder)
    result['inputs'] = list(recorder.pins.values())
    result['provenance'] = {'tool': 'ravel.plotting.reference_metrics', 'code': code_identity(__file__)}
    write_new_json(out_path, result)
    return result


def main(argv=None):
    """``ravel compare --spec S --out comparison.json``."""
    parser = argparse.ArgumentParser(prog='ravel compare', description='Compare a result with a reference series '
                                     'under declared transformations and tolerances.')
    parser.add_argument('--spec', required=True, type=Path, help='comparison specification JSON')
    parser.add_argument('--out', required=True, type=Path, help='new comparison.json path')
    args = parser.parse_args(argv)
    try:
        doc = run_spec(args.spec, args.out)
    except (ValueError, OSError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'verdict': doc.get('verdict'), 'summary': doc.get('summary', [])}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
