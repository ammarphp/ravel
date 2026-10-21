"""Supplied background-covariance likelihoods and audited asymptotic CLs roots.

Spey returns apriori confidence levels in descending order. Their complements
are already in pyhf order: [-2 sigma, -1 sigma, median, +1 sigma, +2 sigma].
No matrix repair, signal uncertainty or coverage certification is performed.
"""
from __future__ import annotations

from copy import deepcopy
import math
import os

import numpy as np
from scipy.optimize import brentq

from ravel.limits import LimitCurve, LimitResult, attach_limits

SPEY_VERSION = "0.2.6"
EXPECTED_ORDER = ['-2 sigma', '-1 sigma', 'median', '+1 sigma', '+2 sigma']


def _spey():
    os.environ['SPEY_CHECKUPDATE'] = 'OFF'
    try:
        import spey
    except ImportError as error:
        raise RuntimeError('simplified likelihood requires spey==0.2.6') from error
    if spey.version() != SPEY_VERSION:
        raise RuntimeError('this adapter requires spey==0.2.6; other versions require a compatibility review')
    return spey


def _vector(raw, label, *, nonnegative=True):
    try:
        values = np.asarray(raw, dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{label} must be a finite numeric vector') from error
    if (values.ndim != 1 or not values.size or not np.isfinite(values).all()
            or any(isinstance(x, (bool, str)) for x in raw)
            or (nonnegative and np.any(values < 0))):
        raise ValueError(f'{label} must be a finite' + (' nonnegative' if nonnegative else '') + ' numeric vector')
    return values.copy()


def _labels(raw, label='labels'):
    if (not isinstance(raw, (list, tuple)) or not raw
            or any(not isinstance(x, str) or not x.strip() for x in raw)
            or len(set(raw)) != len(raw)):
        raise ValueError(f'{label} must be unique nonblank names')
    return list(raw)


def _matrix(raw, n, label):
    try:
        matrix = np.asarray(raw, dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{label} must be a finite square matrix') from error
    if matrix.shape != (n, n) or not np.isfinite(matrix).all():
        raise ValueError(f'{label} must be a finite {n} by {n} matrix')
    if not np.allclose(matrix, matrix.T, rtol=1e-12, atol=0):
        raise ValueError(f'{label} must be symmetric within 1e-12 relative tolerance')
    return matrix.copy()


class _Inference:
    def _fit_bounds(self, mu):
        return [(0.0, max(256.0, 2 * mu))]

    def cls(self, mu, expected):
        if expected not in ('observed', 'apriori'):
            raise ValueError('expected must be observed or apriori')
        if expected == 'observed' and self.observed is None:
            raise ValueError('observed CLs requires observed data')
        if type(mu) not in (int, float) or not math.isfinite(mu) or mu < 0:
            raise ValueError('mu must be finite and nonnegative')
        spey = _spey()
        size = 1 if expected == 'observed' else 5
        if mu == 0 or not np.any(self.signal):
            return [1.0] * size
        confidence = self.backend().exclusion_confidence_level(
            poi_test=float(mu), expected=getattr(spey.ExpectationType, expected),
            par_bounds=self._fit_bounds(mu), verbose=False,
            tol=1e-12)
        values = [1 - float(x) for x in confidence]
        if len(values) != size or any(not math.isfinite(x) or not 0 <= x <= 1 for x in values):
            raise ValueError('spey returned invalid CLs values or an unexpected result shape')
        if expected == 'apriori' and any(a > b + 1e-10 for a, b in zip(values, values[1:])):
            raise ValueError('spey expected CLs do not follow [-2,-1,median,+1,+2] order')
        return values

    def limits(self, level=0.05, poi_cap=128.0):
        if type(level) not in (int, float) or not 0 < level < 1:
            raise ValueError('level must be between zero and one')
        if type(poi_cap) not in (int, float) or not math.isfinite(poi_cap) or poi_cap <= 0:
            raise ValueError('poi_cap must be finite and positive')
        cache = {}

        def evaluate(mu, *, fresh=False):
            if fresh or mu not in cache:
                expected = self.cls(mu, 'apriori')
                observed = self.cls(mu, 'observed')[0] if self.observed is not None else None
                cache[mu] = [observed, *expected]
            return cache[mu]

        upper = min(1.0, poi_cap)
        while True:
            values = evaluate(upper)
            if (values[0] is None or values[0] < level) and values[5] < level or upper == poi_cap:
                break
            upper = min(upper * 2, poi_cap)
        curves, evidence = [], []
        for index in range(6):
            if index == 0 and self.observed is None:
                curves.append(LimitCurve(None, 'missing'))
                evidence.append({'status': 'missing', 'bracket': None, 'cls_at_root': None, 'residual': None})
                continue
            end = evaluate(upper)[index]
            if end >= level:
                curves.append(LimitCurve(float(upper), 'above_scan', (float(upper), None)))
                evidence.append({'status': 'above_scan', 'bracket': [float(upper), None],
                                 'cls_at_cap': end, 'cls_at_root': None, 'residual': None})
                continue
            root = float(brentq(lambda mu: evaluate(mu)[index] - level, 0.0, upper,
                                xtol=1e-10, rtol=1e-10, maxiter=100))
            actual = evaluate(root, fresh=True)[index]
            if abs(actual - level) > 5e-6:
                raise ValueError('spey root failed CLs residual verification')
            if root >= poi_cap:
                curves.append(LimitCurve(float(poi_cap), 'above_scan', (float(poi_cap), None)))
                evidence.append({'status': 'above_scan', 'bracket': [float(poi_cap), None],
                                 'cls_at_cap': actual, 'cls_at_root': None, 'residual': None})
                continue
            curves.append(LimitCurve(root, 'resolved', (0.0, float(upper))))
            evidence.append({'status': 'resolved', 'bracket': [0.0, float(upper)],
                             'bracket_cls': [1.0, end], 'cls_at_root': actual, 'residual': actual - level})
        scan = np.linspace(0.0, upper, 21).tolist()
        values = [evaluate(mu) for mu in scan]
        for index in range(6):
            if index == 0 and self.observed is None:
                continue
            if any(b[index] > a[index] + 1e-6 for a, b in zip(values, values[1:])):
                raise ValueError('spey returned a nonmonotone CLs scan; no limit emitted')
        typed = LimitResult(curves[0], tuple(curves[1:]), origin='spey')
        expected = [c.value for c in curves[1:]]
        return attach_limits({
            'obs_limit': curves[0].value, 'exp_limits': expected,
            'scan_mu': scan, 'scan_cls_obs': [v[0] for v in values],
            'scan_cls_exp': [v[1:] for v in values], 'cls_monotonic': True,
            'at_poi_cap': curves[0].status == 'above_scan',
            'median_at_cap': curves[3].status == 'above_scan', 'at_mu_floor': False,
            'band_degenerate': bool(expected[4] / max(expected[0], 1e-12) < 1.5),
            'numerical_evidence': {'observed': evidence[0], 'expected': evidence[1:]},
            'inference': {'method': 'asymptotic CLs (spey)', 'test_stat': 'qtilde', 'level': level,
                          'backend': self.backend_name, 'backend_version': SPEY_VERSION,
                          'root_solver': 'scipy.brentq', 'root_atol': 1e-10, 'root_rtol': 1e-10,
                          'coverage_validated': False, 'expected_order': EXPECTED_ORDER,
                          'scope': 'Poisson counts with supplied background covariance; no signal uncertainty or control regions'}
        }, result=typed, source='spey')


class SimplifiedLikelihood(_Inference):
    def _fit_bounds(self, mu):
        # A single bound broadcasts to nuisance parameters in scipy. Only the
        # POI is nonnegative; the additive Gaussian nuisances remain unbounded.
        return super()._fit_bounds(mu) + [(None, None)] * len(self.labels)

    def __init__(self, observed, background, signal, labels, *, covariance=None,
                 correlation=None, errors=None, third_moments=None):
        self.labels = _labels(labels)
        self.background = _vector(background, 'background')
        self.signal = _vector(signal, 'signal')
        self.observed = None if observed is None else _vector(observed, 'observed')
        n = len(self.labels)
        if any(len(x) != n for x in (self.background, self.signal)
               + (() if self.observed is None else (self.observed,))):
            raise ValueError('observed, background, signal and labels must have equal lengths')
        if (covariance is None) == (correlation is None) or covariance is not None and errors is not None:
            raise ValueError('supply exactly one of covariance or correlation with errors')
        if correlation is not None:
            corr = _matrix(correlation, n, 'correlation')
            if not np.allclose(np.diag(corr), 1, rtol=1e-12, atol=0) or np.any(np.abs(corr) > 1):
                raise ValueError('correlation must have unit diagonal and |r| <= 1')
            error = _vector(errors, 'errors')
            if len(error) != n:
                raise ValueError('errors must have the same length as labels')
            covariance = error[:, None] * corr * error[None, :]
        self.covariance = _matrix(covariance, n, 'covariance')
        try:
            np.linalg.cholesky(self.covariance)
        except np.linalg.LinAlgError as error:
            raise ValueError('covariance must be positive definite; no repair or regularisation is allowed') from error
        self.third_moments = None if third_moments is None else _vector(third_moments, 'third_moments', nonnegative=False)
        if self.third_moments is not None:
            if len(self.third_moments) != n:
                raise ValueError('third_moments must have the same length as labels')
            if np.any(self.third_moments ** 2 > 8 * np.diag(self.covariance) ** 3):
                raise ValueError('third_moments exceed the supported expansion domain')
        self.backend_name = ('default.correlated_background' if self.third_moments is None
                             else 'default.third_moment_expansion')
        self._backend = None

    def backend(self):
        _spey()
        if self._backend is None:
            self._backend = self._make_backend('single-block')
        return self._backend

    def _make_backend(self, analysis):
        spey = _spey()
        kwargs = {} if self.third_moments is None else {'third_moment': self.third_moments.tolist()}
        return spey.get_backend(self.backend_name)(
            signal_yields=self.signal.tolist(), background_yields=self.background.tolist(),
            data=(self.background if self.observed is None else self.observed).tolist(),
            covariance_matrix=self.covariance.tolist(), analysis=analysis, **kwargs)


class _Combined(_Inference):
    def __init__(self, blocks):
        self.blocks = list(blocks)
        if not self.blocks or any(not isinstance(b, SimplifiedLikelihood) for b in self.blocks):
            raise ValueError('combine needs a nonempty list of SimplifiedLikelihood blocks')
        self.labels = _labels([x for b in self.blocks for x in b.labels], 'disjoint block labels')
        self.signal = np.concatenate([b.signal for b in self.blocks])
        self.observed = (None if any(b.observed is None for b in self.blocks)
                         else np.concatenate([b.observed for b in self.blocks]))
        self.backend_name = 'spey.UnCorrStatisticsCombiner'
        self._backend = None

    def backend(self):
        spey = _spey()
        if self._backend is None:
            # Distinct analysis identities are required by the independent combiner.
            models = [b._make_backend(f'block-{i}') for i, b in enumerate(self.blocks)]

            class NuisanceBoundsCombiner(spey.UnCorrStatisticsCombiner):
                # In 0.2.6 the outer one-dimensional POI bounds also propagate
                # into each nuisance fit, where scipy broadcasts them. Retain
                # them for the outer fit but use each backend's complete bounds
                # for conditional nuisance fits and null-data construction.
                def likelihood(self, *args, **kwargs):
                    kwargs.pop('par_bounds', None)
                    return super().likelihood(*args, **kwargs)

                def generate_asimov_data(self, *args, **kwargs):
                    kwargs.pop('par_bounds', None)
                    return super().generate_asimov_data(*args, **kwargs)

            self._backend = NuisanceBoundsCombiner(*models)
        return self._backend


def combine(blocks):
    """Combine explicitly independent blocks; labels cannot overlap."""
    return _Combined(blocks)


def from_document(covariance_document, yields):
    d = covariance_document
    allowed = {'schema_version', 'kind', 'regions', 'covariance', 'correlation', 'third_moments', 'blocks', 'source'}
    if (not isinstance(d, dict) or set(d) - allowed or type(d.get('schema_version')) is not int
            or d.get('schema_version') != 1 or d.get('kind') != 'background-covariance'):
        raise ValueError('background-covariance schema_version 1 document required')
    if not isinstance(d.get('source'), str) or not d['source'].strip():
        raise ValueError('background covariance requires a nonblank source citation')
    if ('covariance' in d) == ('correlation' in d):
        raise ValueError('supply exactly one of covariance or correlation')
    regions = _labels(d.get('regions'), 'regions')
    if not isinstance(yields, list) or not yields or any(not isinstance(r, dict) for r in yields):
        raise ValueError('yields must be a nonempty list of SR inputs')
    names = _labels([r.get('name') for r in yields], 'yield names')
    if set(names) != set(regions):
        raise ValueError('covariance region set must equal the yield region set')
    by_name = {r['name']: r for r in yields}
    rows = [by_name[r] for r in regions]
    _vector([r.get('db') for r in rows], 'db')
    observed = [r.get('n') for r in rows]
    if any(n is None for n in observed) and not all(n is None for n in observed):
        raise ValueError('observed counts must be supplied for every region or none')
    full = SimplifiedLikelihood(None if all(n is None for n in observed) else observed,
        [r.get('b') for r in rows], [r.get('s') for r in rows], regions,
        covariance=d.get('covariance'), correlation=d.get('correlation'),
        errors=[r.get('db') for r in rows] if 'correlation' in d else None,
        third_moments=d.get('third_moments'))
    blocks = d.get('blocks', [regions])
    if not isinstance(blocks, list) or not blocks:
        raise ValueError('blocks must partition regions into nonempty lists')
    for block in blocks:
        _labels(block, 'block regions')
    flat = [r for block in blocks for r in block]
    if len(flat) != len(set(flat)) or set(flat) != set(regions):
        raise ValueError('blocks must partition regions exactly')
    membership = {r: i for i, block in enumerate(blocks) for r in block}
    if any(full.covariance[i, j] != 0 for i, r in enumerate(regions) for j, s in enumerate(regions)
           if membership[r] != membership[s]):
        raise ValueError('independent blocks require zero covariance between blocks')
    if len(blocks) == 1:
        return full
    engines = []
    for block in blocks:
        idx = [regions.index(r) for r in block]
        engines.append(SimplifiedLikelihood(None if full.observed is None else full.observed[idx],
            full.background[idx], full.signal[idx], block, covariance=full.covariance[np.ix_(idx, idx)],
            third_moments=None if full.third_moments is None else full.third_moments[idx]))
    return combine(engines)


def run_yields(covariance_document, yields, *, level=0.05):
    from ravel.physics.pyhf_exclude import low_count_flags
    engine = from_document(covariance_document, yields)
    result = engine.limits(level=level)
    result.update(mode='simplified', stat_mode='simplified-likelihood',
        model_scope={'background_constraint': ('correlated Gaussian (published covariance)'
                     if covariance_document.get('third_moments') is None else 'third-moment expansion (published covariance and third moments)'),
                     'correlations': 'published covariance',
                     'blocks': covariance_document.get('blocks', [covariance_document['regions']]),
                     'control_regions': 'not represented in a simplified likelihood',
                     'signal_uncertainty': 'not included', 'acceptance_validated': False},
        per_sr={r['name']: {**r, 'low_count_flags': low_count_flags({**r, 'n': r['b'] if r.get('n') is None else r['n']})}
                for r in yields}, covariance_source=covariance_document['source'])
    return result


STATISTICAL_ONLY_SCALE = 1e-9


def statistical_only_document(covariance_document):
    """The same background-covariance document with the covariance reduced to a negligible diagonal.

    The simplified likelihood then keeps only the Poisson term: the statistical-only reference for
    the systematic component of an uncertainty statement. Third moments are dropped with it.
    """
    document = deepcopy(covariance_document)
    regions = document.get("regions")
    if not isinstance(regions, list) or not regions:
        raise ValueError("the covariance document names no regions")
    size = len(regions)
    if "covariance" in document:
        scale = max(abs(float(document["covariance"][i][i])) for i in range(size)) or 1.0
    else:
        scale = 1.0
    document.pop("correlation", None)
    document.pop("third_moments", None)
    document["covariance"] = [[STATISTICAL_ONLY_SCALE * scale if i == j else 0.0 for j in range(size)]
                              for i in range(size)]
    return document
