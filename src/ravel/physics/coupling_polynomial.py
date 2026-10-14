"""Polynomial dependence on couplings: bases, design matrices, SVD solve, covariance, held-out checks.

A rate, or each bin of a template, that depends polynomially on couplings is
``y(p) = sum_k c_k m_k(p)`` with monomials ``m_k``. This module is the shared core
for every client that extracts the coefficients from runs at known points:

- ``basis_of_degree`` and ``basis_from_amplitudes`` build the monomial basis from a
  declared total degree or from the coupling orders of the amplitude terms
  (``|sum_a A_a|^2`` gives every product ``A_a A_b``, including mixed-degree
  interference with a coupling-independent amplitude); ``check_basis`` refuses a
  declared basis that differs from the one those orders imply;
- ``design`` evaluates the monomials at run points;
- ``svd_extraction`` returns the rank, singular values, condition number and the
  linear extraction map of a design matrix;
- ``solve`` fits per-bin coefficients, unweighted or weighted by run
  uncertainties, with coefficient covariance and chi-square;
- ``propagate_covariance`` carries a full covariance through a linear map;
- ``held_out`` compares a prediction with a run that was not used in the fit,
  using the combined uncertainty of the run and of the prediction.

Clients: ``ravel.physics.inference.morphing`` (the ``coupling-morphing`` science
mode) and ``ravel.physics.sfitter_scan_extraction``.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
from itertools import combinations_with_replacement, product
import math

import numpy as np

from ravel.physics import derived_quantities as dq

MAX_POWER = 16
MAX_MONOMIALS = 256


def _powers(term, parameters, label):
    if type(term) is not dict or set(term) - set(parameters):
        raise ValueError(label + ' maps declared parameters to integer powers')
    if any(type(v) is not int or not 0 <= v <= MAX_POWER for v in term.values()):
        raise ValueError(label + f' powers must be integers from 0 to {MAX_POWER}')
    return tuple(term.get(p, 0) for p in parameters)


def basis_of_degree(parameters, degree, *, homogeneous):
    """Every monomial of total degree ``degree`` (or up to it when not homogeneous)."""
    if type(degree) is not int or not 0 <= degree <= MAX_POWER:
        raise ValueError(f'degree must be an integer from 0 to {MAX_POWER}')
    out = [t for t in product(range(degree + 1), repeat=len(parameters))
           if (sum(t) == degree if homogeneous else sum(t) <= degree)]
    if len(out) > MAX_MONOMIALS:
        raise ValueError('the declared degree gives too many monomials')
    return sorted(out)


def basis_from_amplitudes(parameters, amplitudes):
    """Monomials of ``|sum_a A_a|^2`` for amplitude terms with declared coupling orders.

    Each amplitude term maps parameters to their power in that term; ``{}`` is a
    term that does not depend on the parameters (for example a Standard Model
    amplitude). The basis holds every pairwise product, so interference terms of
    mixed degree are included.
    """
    if type(amplitudes) is not list or not amplitudes:
        raise ValueError('amplitudes must be a nonempty list of coupling-order maps')
    terms = [_powers(a, parameters, 'each amplitude term') for a in amplitudes]
    if len(set(terms)) != len(terms):
        raise ValueError('amplitude terms repeat a coupling order')
    out = sorted({tuple(x + y for x, y in zip(a, b)) for a, b in combinations_with_replacement(terms, 2)})
    if len(out) > MAX_MONOMIALS:
        raise ValueError('the declared amplitudes give too many monomials')
    return out


def check_basis(parameters, basis, *, amplitudes=None, degree=None):
    """Refuse a declared basis whose monomials differ from the declared coupling orders."""
    implied = []
    if amplitudes is not None:
        implied.append(('the amplitude coupling orders', basis_from_amplitudes(parameters, amplitudes)))
    if degree is not None:
        if type(degree) is not dict or set(degree) != {'total', 'homogeneous'} or type(degree['homogeneous']) is not bool:
            raise ValueError('degree is {"total": n, "homogeneous": true|false}')
        implied.append(('the declared total degree',
                        basis_of_degree(parameters, degree['total'], homogeneous=degree['homogeneous'])))
    declared = set(map(tuple, basis))
    for source, expected in implied:
        missing, extra = sorted(set(expected) - declared), sorted(declared - set(expected))
        if missing or extra:
            label = lambda ts: ', '.join(monomial_label(t, parameters) for t in ts) or 'none'
            raise ValueError(f'the declared basis does not match the degree implied by {source}: '
                             f'missing {label(missing)}; not implied {label(extra)}')
    return sorted(declared)


def monomial_label(powers, parameters):
    parts = [p if n == 1 else f'{p}^{n}' for p, n in zip(parameters, powers) if n]
    return '*'.join(parts) or '1'


def monomials(columns, parameters, basis):
    """Monomial values, shape (len(basis),) + broadcast shape of the coordinates."""
    arrays = [np.asarray(columns[p], float) for p in parameters]
    shape = np.broadcast_shapes(*[a.shape for a in arrays]) if arrays else ()
    out = np.empty((len(basis),) + shape)
    for k, powers in enumerate(basis):
        term = np.ones(shape)
        for a, n in zip(arrays, powers):
            if n:
                term = term * np.power(a, n)
        out[k] = term
    return out


def design(points, basis):
    """Design matrix (runs x monomials) for run coordinates ``points`` (runs x parameters)."""
    points = np.asarray(points, float)
    if points.ndim != 2:
        raise ValueError('points must be a runs x parameters array')
    columns = {i: points[:, i] for i in range(points.shape[1])}
    return monomials(columns, list(range(points.shape[1])), basis).T


def svd_extraction(X, rcond, *, max_condition=None):
    """Rank, singular values, condition number and (when identified) the extraction map.

    The map ``M`` (monomials x runs) satisfies ``c = M y`` for the least-squares
    solution. It is returned only for full column rank and, when ``max_condition``
    is given, a condition number within it.
    """
    u, s, vh = np.linalg.svd(np.asarray(X, float), full_matrices=False)
    if not bool(np.all(np.isfinite(s))):
        raise ValueError('nonfinite computed singular values')
    rank = int(np.count_nonzero(s > rcond * s[0])) if len(s) else 0
    condition = float(s[0] / s[-1]) if len(s) and s[-1] > 0 else None
    if condition is not None and not math.isfinite(condition):
        condition = None
    mapping = None
    if (rank == np.shape(X)[1] and condition is not None
            and (max_condition is None or condition <= max_condition)):
        mapping = (vh.T / s) @ u.T
    return {'singular_values': s, 'rank': rank, 'condition': condition, 'map': mapping}


def equilibrated_condition(A):
    scale = np.linalg.norm(A, axis=0)
    if np.any(scale == 0):
        raise ValueError('a monomial vanishes at every run point; the basis is not determined')
    return float(np.linalg.cond(A / scale))


def solve(A, Y, *, rcond, sigma=None, max_condition=None):
    """Per-bin coefficients from runs ``Y`` (runs x bins).

    Without ``sigma`` the fit is unweighted and no covariance is returned. With
    ``sigma`` (runs x bins, positive) each bin is weighted by ``1/sigma^2``; the
    coefficient covariance is ``(A^T W A)^-1`` and the chi-square is reported.
    ``coefficients`` is None when the design is rank deficient or exceeds
    ``max_condition``.
    """
    A = np.asarray(A, float); Y = np.asarray(Y, float)
    n, k = A.shape
    if Y.ndim != 2 or Y.shape[0] != n:
        raise ValueError('values must be a runs x bins array')
    base = svd_extraction(A, rcond, max_condition=max_condition)
    out = {'rank': base['rank'], 'singular_values': base['singular_values'].tolist(),
           'condition': base['condition'], 'equilibrated_condition': equilibrated_condition(A),
           'ndf': n - k, 'coefficients': None, 'covariance': None, 'chi2': None, 'map': None}
    if base['map'] is None:
        return out
    bins = Y.shape[1]
    if sigma is None:
        coefficients = base['map'] @ Y
        out.update(coefficients=coefficients, map=base['map'],
                   chi2=None if n == k else np.zeros(bins))
        return out
    S = np.asarray(sigma, float)
    if S.shape != Y.shape or not bool(np.all(S > 0)):
        raise ValueError('uncertainties must be positive and match the values')
    coefficients = np.empty((k, bins)); covariance = np.empty((bins, k, k)); chi2 = np.empty(bins)
    for b in range(bins):
        w = 1.0 / S[:, b]
        weighted = svd_extraction(A * w[:, None], rcond)
        if weighted['map'] is None:
            return out
        M = weighted['map'] * w[None, :]
        coefficients[:, b] = M @ Y[:, b]
        covariance[b] = weighted['map'] @ weighted['map'].T
        residual = (Y[:, b] - A @ coefficients[:, b]) * w
        chi2[b] = float(residual @ residual)
    out.update(coefficients=coefficients, covariance=covariance, chi2=chi2)
    return out


def propagate_covariance(A, C, label):
    """Full covariance ``A C A^T`` of a linear map; returns (matrix, diagnostics).

    Each upper output entry is emitted once, then mirrored; the supplied ``C`` is
    never averaged, regularized or eigenvalue-clipped. Near a null residual
    direction, two ordinary matrix products can lose the positive-semidefinite
    sign; the same fixed linear map is then recomputed with bounded 100-digit
    dot products of the exact binary64 inputs.
    """
    raw = _finite((A @ C) @ A.T, label)
    asymmetry = dq._number(float(np.max(np.abs(raw - raw.T))))
    upper = np.triu(raw); matrix = upper + np.triu(raw, 1).T
    arithmetic = 'upper BLAS output product entries mirrored; source covariance unchanged'
    try:
        _, diagnostic = dq._matrix(matrix.tolist(), len(matrix))
    except dq.DerivedQuantityError as exc:
        if str(exc) != 'non-positive-semidefinite covariance':
            raise
        m, n = A.shape
        if m * n * n + m * m * n > 5_000_000:
            raise ValueError('cancellation-sensitive covariance exceeds compensated arithmetic budget') from exc
        with localcontext() as ctx:
            ctx.prec = 100
            aa = [[Decimal.from_float(float(v)) for v in row] for row in A]
            cc = [[Decimal.from_float(float(v)) for v in row] for row in C]
            middle = [[sum((cc[i][j] * aa[k][j] for j in range(n)), Decimal(0))
                       for k in range(m)] for i in range(n)]
            matrix = np.zeros((m, m))
            for i in range(m):
                for k in range(i, m):
                    value = sum((aa[i][j] * middle[j][k] for j in range(n)), Decimal(0))
                    matrix[i, k] = matrix[k, i] = float(value)
        _finite(matrix, 'extended-precision covariance')
        _, diagnostic = dq._matrix(matrix.tolist(), len(matrix))
        arithmetic = ('bounded 100-digit dot products of exact input binary64 values; upper entries mirrored; '
                      'source covariance unchanged')
    return matrix, {**diagnostic, 'raw_product_max_asymmetry': asymmetry, 'arithmetic': arithmetic}


def held_out(*, predicted, prediction_variance, observed, uncertainty, tolerance_sigma):
    """Pull ``(predicted - observed) / sqrt(var_prediction + uncertainty^2)`` per bin."""
    predicted = np.atleast_1d(np.asarray(predicted, float))
    observed = np.atleast_1d(np.asarray(observed, float))
    sigma = np.atleast_1d(np.asarray(uncertainty, float))
    variance = (np.zeros_like(predicted) if prediction_variance is None
                else np.atleast_1d(np.asarray(prediction_variance, float)))
    if not (predicted.shape == observed.shape == sigma.shape == variance.shape):
        raise ValueError('held-out values, uncertainties and predictions must have the same bins')
    if not bool(np.all(sigma > 0)):
        raise ValueError('held-out runs need positive uncertainties')
    if type(tolerance_sigma) not in (int, float) or not tolerance_sigma > 0:
        raise ValueError('a held-out comparison needs a positive tolerance in standard deviations')
    pulls = (predicted - observed) / np.sqrt(variance + sigma ** 2)
    return {'predicted': predicted.tolist(), 'observed': observed.tolist(), 'pulls': pulls.tolist(),
            'combined_uncertainty': np.sqrt(variance + sigma ** 2).tolist(),
            'tolerance_sigma': float(tolerance_sigma), 'passed': bool(np.all(np.abs(pulls) <= tolerance_sigma))}


def _finite(value, label):
    result = np.asarray(value, dtype=float)
    if not bool(np.all(np.isfinite(result))):
        raise ValueError('nonfinite computed ' + label)
    return result
