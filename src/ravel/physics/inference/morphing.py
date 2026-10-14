"""Coupling-polynomial morphing from a declared monomial basis.

A quantity (a cross section, or each bin of a template) that is a polynomial in
couplings is written as ``y(p) = sum_k c_k m_k(p)`` with declared monomials
``m_k`` (for example g1^2, g1*g2, g2^2, or g^4). From N runs at known points:

- ``exact``: N equals the number of monomials; solve ``A c = y``;
- ``weighted-least-squares``: N at least the number of monomials, every run has
  an uncertainty; minimise the weighted squared residuals.

The condition number of the column-equilibrated design matrix is checked against
a declared ceiling (the raw value is also reported). Coefficient covariance is
propagated from the run uncertainties. Held-out runs give a closure pull per
bin against a declared tolerance in standard deviations. Evaluation on a grid
returns the prediction and, when available, its propagated variance.
"""
from __future__ import annotations

import math

import numpy as np

from ravel.physics import coupling_polynomial as cp

from .formula import NAME

MAX_MONOMIALS, MAX_RUNS, MAX_BINS = 64, 4096, 4096
RCOND = 1e-15
METHODS = ('exact', 'weighted-least-squares')


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite number')
    return float(value)


def _basis(basis, parameters):
    if type(basis) is not list or not 1 <= len(basis) <= MAX_MONOMIALS:
        raise ValueError('basis must be a nonempty list of monomials')
    out = [cp._powers(monomial, parameters, 'each monomial') for monomial in basis]
    if len(set(out)) != len(out):
        raise ValueError('basis repeats a monomial')
    return out


monomial_label = cp.monomial_label


def _rows(rows, parameters, label):
    if type(rows) is not list:
        raise ValueError(label + ' must be a list')
    points, values, sigmas, ids = [], [], [], []
    width = None
    for row in rows:
        if type(row) is not dict or 'point' not in row or 'id' not in row:
            raise ValueError(label + ' need id, point and value(s)')
        allowed = {'id', 'point', 'value', 'uncertainty', 'values', 'uncertainties', 'source'}
        if set(row) - allowed or ('value' in row) == ('values' in row):
            raise ValueError(label + ': give either value/uncertainty or values/uncertainties')
        if type(row['point']) is not dict or set(row['point']) != set(parameters):
            raise ValueError(label + ' points must give exactly the declared parameters')
        points.append([_number(row['point'][p], 'point coordinate') for p in parameters])
        if 'value' in row:
            if 'uncertainties' in row:
                raise ValueError('scalar runs use uncertainty, not uncertainties')
            value = [_number(row['value'], 'run value')]
            sigma = None if 'uncertainty' not in row else [_number(row['uncertainty'], 'run uncertainty')]
        else:
            if 'uncertainty' in row or type(row['values']) is not list or not 1 <= len(row['values']) <= MAX_BINS:
                raise ValueError('vector runs need a values list and optional uncertainties list')
            value = [_number(v, 'run value') for v in row['values']]
            sigma = None
            if 'uncertainties' in row:
                if type(row['uncertainties']) is not list or len(row['uncertainties']) != len(value):
                    raise ValueError('uncertainties must match values')
                sigma = [_number(v, 'run uncertainty') for v in row['uncertainties']]
        if sigma is not None and any(s <= 0 for s in sigma):
            raise ValueError('run uncertainties must be positive')
        if width is None:
            width = len(value)
        elif len(value) != width:
            raise ValueError('all runs must have the same number of bins')
        ids.append(str(row['id'])); values.append(value); sigmas.append(sigma)
    if len(set(ids)) != len(ids):
        raise ValueError(label + ' ids must be unique')
    return ids, np.array(points, float).reshape(len(rows), len(parameters)), values, sigmas, width


class Morph:
    """Fitted or loaded coefficients ``c[k, bin]`` with optional covariance ``cov[bin, k, k]``."""

    def __init__(self, parameters, basis, coefficients, covariance=None, **diagnostics):
        self.parameters, self.basis = list(parameters), [tuple(b) for b in basis]
        self.coefficients = np.asarray(coefficients, float)
        self.covariance = None if covariance is None else np.asarray(covariance, float)
        self.condition_number = diagnostics.get('condition_number')
        self.raw_condition_number = diagnostics.get('raw_condition_number')
        self.method = diagnostics.get('method')
        self.ndf = diagnostics.get('ndf', 0)
        self.chi2 = diagnostics.get('chi2')
        self.closure = diagnostics.get('closure', [])
        self.runs = diagnostics.get('runs', [])
        self.width = diagnostics.get('width')

    @property
    def usable(self):
        """True when at least one held-out run was compared and every comparison passed."""
        width_fit = self.width.get('fit') if isinstance(self.width, dict) else None
        return (bool(self.closure) and all(c.get('passed') is True for c in self.closure)
                and (width_fit is None or width_fit.get('usable') is True))

    @property
    def bins(self):
        return self.coefficients.shape[1]

    def monomials(self, columns):
        return cp.monomials(columns, self.parameters, self.basis)

    def predict(self, columns, *, with_variance=False):
        m = self.monomials(columns)
        flat = m.reshape(len(self.basis), -1)
        predicted = (self.coefficients.T @ flat).reshape((self.bins,) + m.shape[1:])
        if not with_variance:
            return predicted
        if self.covariance is None:
            return predicted, None
        variance = np.einsum('kp,bkl,lp->bp', flat, self.covariance, flat).reshape(predicted.shape)
        return predicted, variance

    def document(self):
        return {'schema_version': 1, 'kind': 'coupling-morph', 'parameters': self.parameters,
                'basis': [dict((p, n) for p, n in zip(self.parameters, b) if n) for b in self.basis],
                'monomial_labels': [monomial_label(b, self.parameters) for b in self.basis],
                'coefficients': self.coefficients.tolist(),
                'covariance': None if self.covariance is None else self.covariance.tolist(),
                'method': self.method, 'condition_number': self.condition_number,
                'raw_condition_number': self.raw_condition_number, 'ndf': self.ndf,
                'chi2': None if self.chi2 is None else [float(x) for x in self.chi2],
                'closure': self.closure, 'runs': self.runs, 'usable': self.usable,
                'width': self.width}

    @classmethod
    def from_document(cls, doc, *, require_usable=False):
        """Load a morph; ``require_usable`` refuses one without a passing held-out comparison."""
        if type(doc) is not dict or doc.get('kind') != 'coupling-morph' or doc.get('schema_version') != 1:
            raise ValueError('a coupling-morph document (schema 1) is required')
        parameters = doc['parameters']
        if type(parameters) is not list or any(type(p) is not str or not NAME.fullmatch(p) for p in parameters):
            raise ValueError('morph parameters must be identifiers')
        basis = _basis(doc['basis'], parameters)
        coefficients = np.array(doc['coefficients'], float)
        if coefficients.ndim != 2 or coefficients.shape[0] != len(basis) or not np.all(np.isfinite(coefficients)):
            raise ValueError('morph coefficients must be a finite monomials x bins array')
        covariance = doc.get('covariance')
        if covariance is not None:
            covariance = np.array(covariance, float)
            if covariance.shape != (coefficients.shape[1], len(basis), len(basis)):
                raise ValueError('morph covariance must be bins x monomials x monomials')
        closure = doc.get('closure') or []
        if require_usable and not (closure and all(c.get('passed') is True for c in closure)
                                   and doc.get('usable', True) is True):
            raise ValueError('this morph has no passing held-out comparison; refit it with at least one '
                             'held-out run that agrees within the combined uncertainty')
        return cls(parameters, basis, coefficients, covariance, method=doc.get('method'), width=doc.get('width'),
                   condition_number=doc.get('condition_number'), ndf=doc.get('ndf', 0),
                   raw_condition_number=doc.get('raw_condition_number'), closure=doc.get('closure', []))


def fit(spec):
    allowed = {'parameters', 'basis', 'method', 'max_condition', 'runs', 'holdout', 'closure_tolerance_sigma'}
    if type(spec) is not dict or not {'parameters', 'basis', 'method', 'max_condition', 'runs'} <= set(spec) or set(spec) - allowed:
        raise ValueError('morphing needs parameters, basis, method, max_condition and runs')
    parameters = spec['parameters']
    if (type(parameters) is not list or not parameters or len(set(parameters)) != len(parameters)
            or any(type(p) is not str or not NAME.fullmatch(p) for p in parameters)):
        raise ValueError('parameters must be unique identifiers')
    basis = _basis(spec['basis'], parameters)
    method = spec['method']
    if method not in METHODS:
        raise ValueError('method must be exact or weighted-least-squares')
    ceiling = _number(spec['max_condition'], 'max_condition')
    if ceiling < 1:
        raise ValueError('max_condition must be at least one')
    ids, points, values, sigmas, width = _rows(spec['runs'], parameters, 'runs')
    n, k = len(ids), len(basis)
    if n < k:
        raise ValueError(f'{k} monomials need at least {k} runs; {n} supplied')
    if method == 'exact' and n != k:
        raise ValueError('the exact method needs exactly as many runs as monomials')
    if n > MAX_RUNS:
        raise ValueError('too many runs')
    A = cp.design(points, basis)  # n x k
    Y = np.array(values, float)  # n x bins
    has_sigma = all(s is not None for s in sigmas)
    if method == 'weighted-least-squares' and not has_sigma:
        raise ValueError('weighted least squares needs an uncertainty for every run')
    S = np.array(sigmas, float) if has_sigma else None  # n x bins
    raw = float(np.linalg.cond(A))
    condition = cp.equilibrated_condition(A)
    if not math.isfinite(condition) or condition > ceiling:
        raise ValueError(f'design matrix condition number {condition:.3g} exceeds the declared ceiling {ceiling:.3g}')
    solution = cp.solve(A, Y, rcond=RCOND, sigma=S)
    if solution['coefficients'] is None:
        raise ValueError(f'the design matrix has rank {solution["rank"]} for {k} monomials')
    coefficients, covariance = solution['coefficients'], solution['covariance']
    chi2 = solution['chi2'] if method == 'weighted-least-squares' else np.zeros(width)
    result = Morph(parameters, basis, coefficients, covariance, method=method, condition_number=condition,
                   raw_condition_number=raw, ndf=n - k, chi2=chi2,
                   runs=[{'id': i, 'point': dict(zip(parameters, map(float, p)))} for i, p in zip(ids, points)])
    holdout = spec.get('holdout') or []
    if holdout:
        tolerance = spec.get('closure_tolerance_sigma')
        if type(tolerance) not in (int, float) or not tolerance > 0:
            raise ValueError('held-out runs need a positive closure_tolerance_sigma')
        hids, hpoints, hvalues, hsigmas, hwidth = _rows(holdout, parameters, 'holdout')
        if hwidth != width:
            raise ValueError('held-out runs must have the same bins as the fitted runs')
        for hid, point, value, sigma in zip(hids, hpoints, hvalues, hsigmas):
            if sigma is None:
                raise ValueError('held-out runs need uncertainties for a closure test')
            predicted, variance = result.predict({p: np.array(point[i]) for i, p in enumerate(parameters)},
                                                 with_variance=True)
            check = cp.held_out(predicted=predicted, prediction_variance=variance, observed=value,
                                uncertainty=sigma, tolerance_sigma=tolerance)
            result.closure.append({'id': hid, 'point': dict(zip(parameters, map(float, point))), **check})
    return result
