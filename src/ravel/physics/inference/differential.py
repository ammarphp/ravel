"""Gaussian likelihood for a measured differential spectrum with full covariance.

The prediction is the declared reference (for example a published Standard Model
baseline) plus a signed polynomial difference

    prediction(p) = reference + sum_k m_k(p) * v_k      (m_k: declared monomials)

so interference terms may be negative. The covariance is a sum of declared
components, each scaled by a law in R_i = prediction_i / reference_i:

- ``fixed``: C_ij;
- ``ratio``: R_i R_j C_ij (for example systematic components);
- ``sqrt-ratio``: sqrt(R_i R_j) C_ij (for example statistical components);

plus, when supplied, the MC covariance of the stacked term vectors propagated as
J C_MC J^T. Linear nuisances shift the prediction by nu_j times a declared
vector (relative to the reference, relative to one term, or absolute), each with
a unit Gaussian constraint; they are profiled exactly.

Objectives: ``chi2`` is r^T C^-1 r (the usual published chi-square);
``gaussian`` adds ln det C(p), the normalised Gaussian. A covariance that is not
positive definite or exceeds the declared condition ceiling makes that point
unavailable; nothing is repaired or clipped. Toys draw from the Gaussian model at
the profiled nuisances for Neyman or CLs constructions.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import optimize

LAWS = ('fixed', 'ratio', 'sqrt-ratio')
OBJECTIVES = ('chi2', 'gaussian')
MAX_BINS = 2000


def _finite(array, label):
    array = np.asarray(array, float)
    if not np.all(np.isfinite(array)):
        raise ValueError(label + ' must be finite')
    return array


class Model:
    def __init__(self, *, measured, reference, terms, components, parameters, nuisances=(),
                 mc_covariance=None, objective='chi2', max_condition=1e12):
        self.y = _finite(measured, 'measured values')
        n = len(self.y)
        if self.y.ndim != 1 or not 1 <= n <= MAX_BINS:
            raise ValueError('measured values must be a one-dimensional spectrum')
        self.reference = _finite(reference, 'reference prediction')
        if self.reference.shape != (n,):
            raise ValueError('reference prediction needs one value per measured bin')
        if objective not in OBJECTIVES:
            raise ValueError('objective must be chi2 or gaussian')
        self.objective, self.max_condition = objective, float(max_condition)
        if type(parameters) is not list or not parameters or len(set(parameters)) != len(parameters):
            raise ValueError('parameters must be a nonempty list of unique names')
        self.parameters = list(parameters)
        self.terms = []
        for k, term in enumerate(terms):
            powers = term.get('powers')
            if type(powers) is not dict or set(powers) - set(parameters) or any(
                    type(v) is not int or not 0 <= v <= 16 for v in powers.values()):
                raise ValueError(f'term {k}: powers map declared parameters to integers from 0 to 16')
            values = _finite(term['values'], f'term {k} values')
            if values.shape != (n,):
                raise ValueError(f'term {k} needs one value per measured bin')
            scale = 1.0
            if term.get('scale') is not None:
                scale = float(term['scale']['value'])
                if not math.isfinite(scale):
                    raise ValueError(f'term {k}: scale must be finite')
            self.terms.append({'powers': dict(powers), 'values': values * scale, 'kind': term.get('kind', 'other')})
        self.components = []
        for c in components:
            if c.get('law') not in LAWS:
                raise ValueError('covariance law must be fixed, ratio or sqrt-ratio')
            matrix = _finite(c['matrix'], f'covariance component {c.get("name")}')
            if matrix.shape != (n, n) or not np.allclose(matrix, matrix.T, rtol=0, atol=1e-12 * max(1, np.abs(matrix).max())):
                raise ValueError(f'covariance component {c.get("name")} must be a symmetric {n}x{n} matrix')
            self.components.append({'name': c.get('name'), 'law': c['law'], 'matrix': matrix})
        if not self.components:
            raise ValueError('at least one covariance component is required')
        if any(c['law'] != 'fixed' for c in self.components) and np.any(self.reference <= 0):
            raise ValueError('prediction-dependent covariance laws need a positive reference in every bin')
        self.mc = None
        if mc_covariance is not None:
            mc = _finite(mc_covariance, 'MC covariance')
            size = n * len(self.terms)
            if mc.shape != (size, size):
                raise ValueError('MC covariance must cover the stacked term vectors (terms x bins)')
            self.mc = mc
        self.nuisances = []
        for nu in nuisances:
            applies = nu.get('applies_to')
            if applies == 'absolute':
                shift = _finite(nu['shift'], f'nuisance {nu.get("name")} shift')
                rel = None
            else:
                rel = np.broadcast_to(_finite(nu['relative'], f'nuisance {nu.get("name")} relative size'), (n,)).copy()
                shift = None
                if applies != 'reference' and not (type(applies) is str and applies.startswith('term:')
                                                   and applies[5:].isdigit() and int(applies[5:]) < len(self.terms)):
                    raise ValueError('nuisance applies_to must be reference, term:<index> or absolute')
            self.nuisances.append({'name': nu['name'], 'applies_to': applies, 'relative': rel, 'shift': shift})
        if len({nu['name'] for nu in self.nuisances}) != len(self.nuisances):
            raise ValueError('nuisance names must be unique')

    @property
    def bins(self):
        return len(self.y)

    def _monomials(self, point):
        missing = set(self.parameters) - set(point)
        if missing:
            raise ValueError('missing parameter values: ' + ', '.join(sorted(missing)))
        out = []
        for term in self.terms:
            value = 1.0
            for p, k in term['powers'].items():
                value *= float(point[p]) ** k
            out.append(value)
        return np.array(out)

    def difference(self, point):
        m = self._monomials(point)
        return sum((mk * t['values'] for mk, t in zip(m, self.terms)), np.zeros(self.bins))

    def prediction(self, point):
        prediction = self.reference + self.difference(point)
        if not np.all(np.isfinite(prediction)):
            raise ValueError('prediction is not finite at ' + repr(point))
        return prediction

    def covariance(self, point):
        prediction = self.prediction(point)
        R = prediction / self.reference if any(c['law'] != 'fixed' for c in self.components) else None
        C = np.zeros((self.bins, self.bins))
        for c in self.components:
            if c['law'] == 'fixed':
                C = C + c['matrix']
            elif c['law'] == 'ratio':
                C = C + np.outer(R, R) * c['matrix']
            else:
                with np.errstate(invalid='ignore'):
                    C = C + np.sqrt(np.outer(R, R)) * c['matrix']
        if self.mc is not None:
            m = self._monomials(point)
            J = np.hstack([mk * np.eye(self.bins) for mk in m])
            C = C + J @ self.mc @ J.T
        return C

    def shifts(self, point):
        if not self.nuisances:
            return np.zeros((self.bins, 0))
        m = self._monomials(point)
        columns = []
        for nu in self.nuisances:
            if nu['applies_to'] == 'absolute':
                columns.append(nu['shift'])
            elif nu['applies_to'] == 'reference':
                columns.append(nu['relative'] * self.reference)
            else:
                k = int(nu['applies_to'][5:])
                columns.append(nu['relative'] * m[k] * self.terms[k]['values'])
        return np.column_stack(columns)

    def _prepare(self, point):
        """Precompute what a likelihood evaluation at this point needs, or a status."""
        prediction = self.prediction(point)
        if any(c['law'] != 'fixed' for c in self.components) and np.any(prediction / self.reference <= 0):
            return {'status': 'nonpositive_prediction_ratio'}
        C = self.covariance(point)
        if not np.all(np.isfinite(C)):
            return {'status': 'nonfinite_covariance'}
        try:
            eig = np.linalg.eigvalsh(C)
        except np.linalg.LinAlgError:
            return {'status': 'eigensystem_failed'}
        if eig[0] <= 0:
            return {'status': 'not_positive_definite', 'minimum_eigenvalue': float(eig[0])}
        condition = float(eig[-1] / eig[0])
        if condition > self.max_condition:
            return {'status': 'condition_exceeded', 'condition_number': condition}
        S = self.shifts(point)
        total = C + S @ S.T
        chol = np.linalg.cholesky(total)
        logdet = float(2 * np.sum(np.log(np.diag(np.linalg.cholesky(C))))) if self.objective == 'gaussian' else 0.0
        return {'status': 'accepted', 'prediction': prediction, 'C': C, 'S': S, 'chol': chol, 'logdet': logdet,
                'condition_number': condition}

    @staticmethod
    def _value(prep, y, aux=None):
        r = y - prep['prediction']
        if aux is not None and prep['S'].shape[1]:
            r = r - aux @ prep['S'].T if r.ndim > 1 else r - prep['S'] @ aux
        from scipy.linalg import solve_triangular
        z = solve_triangular(prep['chol'], r.T, lower=True)
        return np.sum(z * z, axis=0) + prep['logdet']

    def evaluate(self, point):
        prep = self._prepare(point)
        if prep['status'] != 'accepted':
            return {**{k: v for k, v in prep.items()}, 'twice_nll': None}
        return {'status': 'accepted', 'twice_nll': float(self._value(prep, self.y)),
                'condition_number': prep['condition_number']}

    def twice_nll(self, point):
        result = self.evaluate(point)
        return float('nan') if result['twice_nll'] is None else result['twice_nll']

    def profile_nuisances(self, point, y=None, aux=None):
        prep = self._prepare(point)
        if prep['status'] != 'accepted' or not self.nuisances:
            return {}
        y = self.y if y is None else y
        aux = np.zeros(len(self.nuisances)) if aux is None else aux
        Cinv_S = np.linalg.solve(prep['C'], prep['S'])
        A = prep['S'].T @ Cinv_S + np.eye(len(self.nuisances))
        nu = np.linalg.solve(A, Cinv_S.T @ (y - prep['prediction']) + aux)
        return {n['name']: float(v) for n, v in zip(self.nuisances, nu)}

    def scan_1d(self, parameter, grid, *, domain=(None, None), fixed=None):
        fixed = dict(fixed or {})
        grid = np.asarray(grid, float)
        if grid.ndim != 1 or len(grid) < 3 or np.any(np.diff(grid) <= 0):
            raise ValueError('scan grid must be strictly increasing with at least three points')
        lo, hi = domain
        if lo is not None and grid[0] < lo or hi is not None and grid[-1] > hi:
            raise ValueError('scan grid leaves the declared physical domain')
        rows = [self.evaluate({**fixed, parameter: float(x)}) for x in grid]
        values = np.array([np.nan if r['twice_nll'] is None else r['twice_nll'] for r in rows])
        statuses = [r['status'] for r in rows]
        finite = np.isfinite(values)
        if not finite.any():
            raise ValueError('the likelihood is unavailable at every scan point')
        k = int(np.nanargmin(values))
        best_x, best_v = float(grid[k]), float(values[k])
        f = lambda x: self.twice_nll({**fixed, parameter: float(x)})
        left, right = grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)]
        if right > left:
            r = optimize.minimize_scalar(lambda x: f(x) if math.isfinite(f(x)) else 1e300, bounds=(left, right),
                                         method='bounded', options={'xatol': 1e-10 * max(1.0, abs(best_x))})
            if math.isfinite(r.fun) and r.fun < best_v:
                best_x, best_v = float(r.x), float(r.fun)
        null = {**fixed, **{p: 0.0 for p in self.parameters if p not in fixed}}
        null_value = self.twice_nll(null)
        return {'parameter': parameter, 'grid': grid, 'twice_nll': values, 'delta': values - best_v,
                'delta_to_reference': values - null_value, 'reference_point': null,
                'reference_twice_nll': null_value, 'statuses': statuses,
                'unavailable_points': [float(x) for x, s in zip(grid, statuses) if s != 'accepted'],
                'best_fit': {parameter: best_x, 'twice_nll': best_v, 'at_scan_edge': bool(k in (0, len(grid) - 1))},
                'refine': lambda x: f(x) - best_v}

    # ------------------------------------------------------------------ toys
    def toys(self, parameter, grid, *, points, n, seed, method='neyman', null=None, fixed=None):
        """Toy p-values of the profile statistic at the requested parameter values."""
        if type(n) is not int or not 10 <= n <= 100000:
            raise ValueError('toy count must be an integer from 10 to 100000')
        if method not in ('neyman', 'cls'):
            raise ValueError('toy method must be neyman or cls')
        if method == 'cls' and null is None:
            raise ValueError('CLs toys need the background-only parameter value')
        fixed = dict(fixed or {})
        grid = np.asarray(grid, float)
        rng = np.random.default_rng(seed)
        preps = [self._prepare({**fixed, parameter: float(x)}) for x in grid]
        usable = [i for i, p in enumerate(preps) if p['status'] == 'accepted']
        if len(usable) < 3:
            raise ValueError('too few scan points with an accepted covariance for toys')
        observed = self.scan_1d(parameter, grid, fixed=fixed)
        J = len(self.nuisances)

        def statistic(prep_test, ys, auxs):
            at_test = self._value(prep_test, ys, auxs if J else None)
            best = np.min(np.vstack([self._value(preps[i], ys, auxs if J else None) for i in usable]), axis=0)
            return at_test - np.minimum(best, at_test)

        def generate(value):
            point = {**fixed, parameter: float(value)}
            prep = self._prepare(point)
            if prep['status'] != 'accepted':
                raise ValueError(f'covariance unavailable at {parameter} = {value}')
            nu = np.array(list(self.profile_nuisances(point).values())) if J else np.zeros(0)
            mean = prep['prediction'] + (prep['S'] @ nu if J else 0)
            L = np.linalg.cholesky(prep['C'])
            ys = mean + rng.normal(size=(n, self.bins)) @ L.T
            auxs = nu + rng.normal(size=(n, J)) if J else None
            return prep, ys, auxs

        rows = []
        for value in points:
            prep, ys, auxs = generate(value)
            q_obs = max(0.0, float(observed['refine'](value)))
            q_toys = statistic(prep, ys, auxs)
            p_sb = float(np.mean(q_toys >= q_obs))
            row = {'value': float(value), 'observed_statistic': q_obs, 'p_value': p_sb, 'n_toys': n,
                   'p_value_uncertainty': math.sqrt(max(p_sb * (1 - p_sb), 1.0 / n) / n)}
            if method == 'cls':
                _, yb, ab = generate(null)
                q_b = statistic(prep, yb, ab)
                p_b_complement = float(np.mean(q_b >= q_obs))
                row.update(p_background_tail=p_b_complement,
                           cls=None if p_b_complement == 0 else p_sb / p_b_complement)
            rows.append(row)
        return {'method': method, 'n_toys': n, 'seed': seed, 'points': rows,
                'statistic': 'profile likelihood ratio minimised over the scan grid',
                'grid_minimisation': 'toy best fit taken over the scan grid points'}


def admit_covariance(matrix, max_condition):
    """Strict finite symmetric SPD admission, without editing any entry."""
    matrix = np.asarray(matrix, float)
    diagnostic = {'status': 'unchecked', 'entries_repaired': False}
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or not matrix.size:
        return {**diagnostic, 'status': 'invalid_shape'}, None
    if not np.isfinite(matrix).all():
        return {**diagnostic, 'status': 'nonfinite'}, None
    if not np.array_equal(matrix, matrix.T):
        return {**diagnostic, 'status': 'asymmetric'}, None
    try:
        eigen = np.linalg.eigvalsh(matrix)
        diagnostic.update(minimum_eigenvalue=float(eigen[0]), maximum_eigenvalue=float(eigen[-1]))
        if eigen[0] <= 0:
            return {**diagnostic, 'status': 'not_positive_definite'}, None
        condition = float(eigen[-1] / eigen[0])
        diagnostic['condition_number'] = condition
        if not math.isfinite(condition) or condition > max_condition:
            return {**diagnostic, 'status': 'condition_exceeded'}, None
        chol = np.linalg.cholesky(matrix)
    except np.linalg.LinAlgError:
        return {**diagnostic, 'status': 'factorization_failed'}, None
    return {**diagnostic, 'status': 'accepted'}, chol


class CachedModel(Model):
    """Continuous amplitude response with explicitly fitted Gaussian auxiliaries.

    The nuisance-shifted prediction enters the covariance response. Thus nuisance
    fitting is numerical; the fixed-covariance analytic profile is not reused.
    Experimental SPD admission always precedes optional independent MC addition.
    """

    def __init__(self, *, response, measured, reference, components, parameters,
                 mc_policy, auxiliary=None, objective='chi2', max_condition=1e12):
        super().__init__(measured=measured, reference=reference, terms=[], components=components,
                         parameters=parameters, objective=objective, max_condition=max_condition)
        if mc_policy not in ('retained_only', 'independent_gaussian_sum'):
            raise ValueError('explicit MC policy required')
        if not math.isfinite(self.max_condition) or self.max_condition < 1:
            raise ValueError('finite condition ceiling at least one required')
        self.response, self.mc_policy = response, mc_policy
        if len(response.divide) != self.bins:
            raise ValueError('response and measurement bin populations differ')
        self.auxiliary = auxiliary
        self.aux_chol = None
        if auxiliary is not None:
            required = {'parameters', 'response', 'observed', 'offset', 'matrix', 'covariance'}
            if type(auxiliary) is not dict or set(auxiliary) != required:
                raise ValueError('complete auxiliary law required')
            names = auxiliary['parameters']
            if not names or len(set(names)) != len(names) or set(names) - set(parameters):
                raise ValueError('unique declared auxiliary parameters required')
            j = len(names)
            for key, shape in [('response', (self.bins, j)), ('observed', (j,)), ('offset', (j,)),
                               ('matrix', (j, j)), ('covariance', (j, j))]:
                if _finite(auxiliary[key], key).shape != shape:
                    raise ValueError('auxiliary ' + key + ' dimensions differ')
            diagnostic, self.aux_chol = admit_covariance(auxiliary['covariance'], self.max_condition)
            if diagnostic['status'] != 'accepted':
                raise ValueError('auxiliary covariance: ' + diagnostic['status'])
        self.component_diagnostics = []
        for component in self.components:
            matrix = component['matrix']
            if not np.array_equal(matrix, matrix.T):
                raise ValueError('cached covariance coefficients must be exactly symmetric')
            self.component_diagnostics.append({'name': component['name'], 'role': 'composite-coefficient',
                                               'minimum_eigenvalue': float(np.linalg.eigvalsh(matrix)[0]),
                                               'component_sampling_supported': False, 'entries_repaired': False})

    def difference(self, point):
        return self.response.evaluate(point)['difference']

    def evaluate(self, point):
        if set(point) != set(self.parameters) or not all(math.isfinite(float(v)) for v in point.values()):
            raise ValueError('complete finite fit state required')
        response = self.response.evaluate(point)
        prediction = self.reference + response['difference']
        auxq = auxld = 0.
        if self.auxiliary is not None:
            a = self.auxiliary
            eta = np.array([point[p] for p in a['parameters']])
            prediction += np.asarray(a['response']) @ eta
            residual = np.asarray(a['observed']) - (np.asarray(a['offset']) + np.asarray(a['matrix']) @ eta)
            z = np.linalg.solve(self.aux_chol, residual)
            auxq = float(z @ z)
            auxld = float(2*np.log(np.diag(self.aux_chol)).sum())
        evidence = {'twice_nll': None, 'prediction': prediction.tolist(), 'difference': response['difference'].tolist(),
                    'mc_covariance': response['mc_covariance'].tolist(), 'auxiliary_quadratic': auxq,
                    'auxiliary_log_determinant': auxld}
        if not np.isfinite(prediction).all():
            return {**evidence, 'status': 'nonfinite_prediction'}
        ratio = prediction / self.reference if any(c['law'] != 'fixed' for c in self.components) else np.ones(self.bins)
        if not np.isfinite(ratio).all() or np.any(ratio <= 0):
            return {**evidence, 'status': 'nonpositive_prediction_ratio'}
        experimental = np.zeros((self.bins, self.bins))
        for component in self.components:
            scale = np.ones(self.bins) if component['law'] == 'fixed' else ratio if component['law'] == 'ratio' else np.sqrt(ratio)
            experimental += np.outer(scale, scale) * component['matrix']
        exp_diagnostic, _ = admit_covariance(experimental, self.max_condition)
        evidence.update(experimental_covariance=experimental.tolist(), experimental_admission=exp_diagnostic)
        if exp_diagnostic['status'] != 'accepted':
            return {**evidence, 'status': 'experimental_' + exp_diagnostic['status']}
        mc = response['mc_covariance']
        scale = max(float(np.abs(mc).max()), 1e-300)
        if not np.isfinite(mc).all() or not np.array_equal(mc, mc.T) or np.linalg.eigvalsh(mc)[0] < -1e-12*scale:
            return {**evidence, 'status': 'invalid_mc_covariance'}
        total = experimental + (mc if self.mc_policy == 'independent_gaussian_sum' else 0.)
        score_diagnostic, chol = admit_covariance(total, self.max_condition)
        evidence.update(score_covariance=total.tolist(), score_admission=score_diagnostic)
        if score_diagnostic['status'] != 'accepted':
            return {**evidence, 'status': 'score_' + score_diagnostic['status']}
        z = np.linalg.solve(chol, prediction-self.y)
        quadratic, logdet = float(z @ z), float(2*np.log(np.diag(chol)).sum())
        # Preserve the absolute normalized Gaussian NLL, including auxiliaries.
        constant = (self.bins + (len(self.auxiliary['parameters']) if self.auxiliary else 0))*math.log(2*math.pi)
        twice = quadratic + auxq + (logdet + auxld + constant if self.objective == 'gaussian' else 0.)
        if not math.isfinite(twice):
            return {**evidence, 'status': 'nonfinite_objective'}
        return {**evidence, 'status': 'accepted', 'twice_nll': twice, 'quadratic': quadratic,
                'log_determinant': logdet, 'condition_number': score_diagnostic['condition_number']}
