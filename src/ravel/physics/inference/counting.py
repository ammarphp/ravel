"""Binned Poisson likelihood with independent per-bin background nuisances.

For bin i of a channel: observed n_i, background b_i with absolute uncertainty
d_i, and signal s_i(parameters). The declared nuisance form fixes the per-bin
term that is profiled independently:

- ``gaussian-linear``: mean b_i(1 + theta_i) + s_i, theta_i ~ Normal(0, d_i/b_i);
  the same law as a pyhf ``staterror`` modifier on one background sample;
- ``poisson-gamma``: mean gamma_i b_i + s_i with an auxiliary Poisson count
  tau_i = (b_i/d_i)^2 (pyhf ``shapesys``);
- ``lognormal``: mean b_i (1 + d_i/b_i)^theta_i + s_i, theta_i ~ Normal(0, 1);
- ``none``: mean b_i + s_i.

``floor: nonnegative`` keeps the fitted background at or above zero for the
gaussian-linear form. The profile is exact (closed form) for the first two forms
and a bounded one-dimensional search for the lognormal form.

-2 ln L uses the saturated Poisson form 2(m - n + n ln(n/m)), so values are
comparable across points. Channels (for example experiments) are independent:
the combined statistic is the sum of channel terms.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import optimize

FORMS = ('gaussian-linear', 'poisson-gamma', 'lognormal', 'none')
FLOORS = ('nonnegative', 'unbounded')
MAX_BINS = 10000
LOGNORMAL_RANGE = 10.0


def _vector(values, label, *, nonnegative=True):
    if type(values) is not list or not 1 <= len(values) <= MAX_BINS:
        raise ValueError(label + ' must be a nonempty list')
    out = []
    for v in values:
        if type(v) not in (int, float) or not math.isfinite(v) or (nonnegative and v < 0):
            raise ValueError(label + ' must hold finite' + (' nonnegative' if nonnegative else '') + ' numbers')
        out.append(float(v))
    return np.array(out)


def poisson_term(n, m):
    """2 (m - n + n ln(n/m)); infinite where m <= 0 < n or m < 0."""
    n = np.asarray(n, float); m = np.asarray(m, float)
    with np.errstate(divide='ignore', invalid='ignore'):
        log_part = np.where(n > 0, n * np.log(np.where(n > 0, n, 1.0) / m), 0.0)
        value = 2.0 * (m - n + log_part)
    bad = (m < 0) | ((m <= 0) & (n > 0)) | ~np.isfinite(value)
    return np.where(bad, np.inf, value)


class Channel:
    def __init__(self, name, observed, background, uncertainty, *, form='gaussian-linear', floor='nonnegative'):
        if type(name) is not str or not name.strip():
            raise ValueError('channel name required')
        self.name = name
        self.n = _vector(list(observed), 'observed counts')
        self.b = _vector(list(background), 'background')
        self.d = _vector(list(uncertainty), 'background uncertainty')
        if not len(self.n) == len(self.b) == len(self.d):
            raise ValueError(f'channel {name}: observed, background and uncertainty need the same bins')
        if form not in FORMS:
            raise ValueError('nuisance form must be one of ' + ', '.join(FORMS))
        if floor not in FLOORS:
            raise ValueError('floor must be nonnegative or unbounded')
        if form != 'none' and np.any(self.d <= 0):
            raise ValueError(f'channel {name}: the {form} form needs positive uncertainties (use form none for fixed backgrounds)')
        if form in ('poisson-gamma', 'lognormal') and np.any(self.b <= 0):
            raise ValueError(f'channel {name}: the {form} form needs positive backgrounds')
        self.form, self.floor = form, floor

    @property
    def bins(self):
        return len(self.n)

    def profile(self, s):
        """Profiled per-bin -2 ln L and fitted background means; s has shape (bins, points)."""
        n, b, d = self.n[:, None], self.b[:, None], self.d[:, None]
        s = np.asarray(s, float)
        if self.form == 'none':
            m = b + s
            return poisson_term(n, m), np.broadcast_to(b, s.shape).copy()
        if self.form == 'gaussian-linear':
            d2 = d * d
            B = d2 - s - b
            disc = np.sqrt(B * B + 4 * n * d2)
            with np.errstate(divide='ignore', invalid='ignore'):
                mu = np.where(B <= 0, (-B + disc) / 2, np.where(B + disc > 0, 2 * n * d2 / (B + disc), 0.0))
            lower = np.maximum(s, 0.0) if self.floor == 'nonnegative' else np.zeros_like(s)
            mu = np.maximum(mu, lower)
            bkg = mu - s
            return poisson_term(n, mu) + (bkg - b) ** 2 / d2, bkg
        if self.form == 'poisson-gamma':
            tau = (b / d) ** 2
            A = b * b + tau * b
            Bq = b * s - n * b + tau * s - tau * b
            C = -tau * s
            disc = Bq * Bq - 4 * A * C
            root = np.sqrt(np.where(disc >= 0, disc, np.nan))
            with np.errstate(invalid='ignore', divide='ignore'):
                r1 = (-Bq + root) / (2 * A)
                r2 = (-Bq - root) / (2 * A)
            g_low = np.maximum(0.0, -s / b)
            best_value = np.full(s.shape, np.inf)
            best_gamma = np.full(s.shape, np.nan)
            for gamma in (r1, r2, g_low):
                gamma = np.where(np.isfinite(gamma) & (gamma >= g_low), gamma, np.nan)
                value = poisson_term(n, gamma * b + s) + poisson_term(tau, gamma * tau)
                value = np.where(np.isfinite(gamma), value, np.inf)
                take = value < best_value
                best_value = np.where(take, value, best_value)
                best_gamma = np.where(take, gamma, best_gamma)
            return best_value, best_gamma * b
        # lognormal: golden-section search on theta in [-R, R]; unimodal for this convex-in-mean term.
        a = np.log1p(d / b)
        f = lambda t: poisson_term(n, b * np.exp(a * t) + s) + t * t
        lo = np.full(s.shape, -LOGNORMAL_RANGE); hi = np.full(s.shape, LOGNORMAL_RANGE)
        ratio = (math.sqrt(5) - 1) / 2
        c = hi - ratio * (hi - lo); e = lo + ratio * (hi - lo)
        fc, fe = f(c), f(e)
        for _ in range(120):
            left = fc <= fe
            hi = np.where(left, e, hi); lo = np.where(left, lo, c)
            new_c = hi - ratio * (hi - lo); new_e = lo + ratio * (hi - lo)
            c, e = np.where(left, new_c, e), np.where(left, c, new_e)
            fc, fe = np.where(left, f(c), fe), np.where(left, fc, f(e))
        theta = (lo + hi) / 2
        return f(theta), b * np.exp(a * theta)


class Signal:
    """Signal per channel as a function of named parameters."""

    def __init__(self, parameters, evaluate, channels, kind, description, *, reference=1.0, power=1):
        self.parameters, self._evaluate, self.channels = list(parameters), evaluate, channels
        self.kind, self.description = kind, description
        self.reference, self.power = reference, power

    def __call__(self, point):
        return self._evaluate(point)

    @classmethod
    def linear(cls, parameter, templates):
        t = {k: _vector(list(v), 'signal template', nonnegative=False) for k, v in templates.items()}
        return cls([parameter], lambda p: {k: np.multiply.outer(v, np.atleast_1d(np.asarray(p[parameter], float)))
                                           for k, v in t.items()},
                   {k: len(v) for k, v in t.items()}, 'linear', f's = {parameter} * template')

    @classmethod
    def power(cls, parameter, *, reference, power, templates):
        if type(power) is not int or not 1 <= power <= 16:
            raise ValueError('signal power must be an integer from 1 to 16')
        if type(reference) not in (int, float) or not math.isfinite(reference) or reference == 0:
            raise ValueError('signal reference value must be finite and nonzero')
        t = {k: _vector(list(v), 'signal template', nonnegative=False) for k, v in templates.items()}
        def evaluate(p):
            x = np.atleast_1d(np.asarray(p[parameter], float))
            return {k: np.multiply.outer(v, (x / reference) ** power) for k, v in t.items()}
        return cls([parameter], evaluate, {k: len(v) for k, v in t.items()}, 'power',
                   f's = ({parameter}/{reference:g})^{power} * template at {parameter} = {reference:g}',
                   reference=float(reference), power=power)

    @classmethod
    def polynomial(cls, morphs, *, fixed=None):
        """Per-channel coupling morphs (``morphing.Morph``); ``fixed`` pins extra parameters."""
        fixed = dict(fixed or {})
        names = None
        for morph in morphs.values():
            free = [p for p in morph.parameters if p not in fixed]
            if names is None:
                names = free
            elif free != names:
                raise ValueError('all channel morphs must share the same free parameters')
        def evaluate(p):
            columns = {**{k: np.asarray(v, float) for k, v in fixed.items()},
                       **{k: np.atleast_1d(np.asarray(p[k], float)) for k in names}}
            shape = np.broadcast_shapes(*[np.shape(columns[k]) for k in names])
            columns = {k: np.broadcast_to(v, shape) for k, v in columns.items()}
            return {k: m.predict(columns) for k, m in morphs.items()}
        return cls(names, evaluate, {k: m.bins for k, m in morphs.items()}, 'polynomial',
                   'declared coupling polynomial per bin')


class Likelihood:
    def __init__(self, channels, signal):
        names = [c.name for c in channels]
        if not channels or len(set(names)) != len(names):
            raise ValueError('channels need unique names')
        if set(signal.channels) != set(names):
            raise ValueError('signal templates must cover exactly the declared channels')
        for c in channels:
            if signal.channels[c.name] != c.bins:
                raise ValueError(f'signal template for {c.name} has the wrong number of bins')
        self.channels, self.signal = channels, signal

    def per_channel(self, point, *, with_backgrounds=False):
        s = self.signal(point)
        out, fitted = {}, {}
        for c in self.channels:
            values, bkg = c.profile(s[c.name])
            out[c.name] = values.sum(axis=0)
            fitted[c.name] = bkg
        squeeze = lambda v: float(v[0]) if np.size(v) == 1 else v
        result = {k: squeeze(v) for k, v in out.items()}
        return (result, fitted) if with_backgrounds else result

    def twice_nll(self, point):
        total = sum(np.asarray(v, float) for v in self.per_channel(point).values())
        return float(total) if np.ndim(total) == 0 else total


def scan_1d(likelihood, parameter, grid, *, domain=(None, None), fixed=None):
    grid = np.asarray(grid, float)
    if grid.ndim != 1 or len(grid) < 3 or np.any(np.diff(grid) <= 0):
        raise ValueError('scan grid must be strictly increasing with at least three points')
    lo, hi = domain
    if lo is not None and grid[0] < lo or hi is not None and grid[-1] > hi:
        raise ValueError('scan grid leaves the declared physical domain')
    fixed = dict(fixed or {})
    nll = lambda x: likelihood.twice_nll({**fixed, parameter: x})
    values = np.atleast_1d(nll(grid))
    if not np.all(np.isfinite(values)):
        raise ValueError('the likelihood is not finite at some scan points')
    k = int(np.argmin(values))
    left, right = grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)]
    best_x, best_v = float(grid[k]), float(values[k])
    if right > left:
        r = optimize.minimize_scalar(lambda x: float(nll(x)), bounds=(left, right), method='bounded',
                                     options={'xatol': 1e-10 * max(1.0, abs(best_x))})
        if r.fun < best_v:
            best_x, best_v = float(r.x), float(r.fun)
    delta = values - best_v
    local_minima = [float(grid[i]) for i in range(1, len(grid) - 1)
                    if values[i] < values[i - 1] and values[i] < values[i + 1] and i != k]
    return {'parameter': parameter, 'grid': grid, 'twice_nll': values, 'delta': delta,
            'best_fit': {parameter: best_x, 'twice_nll': best_v,
                         'at_scan_edge': bool(k in (0, len(grid) - 1))},
            'other_local_minima': local_minima,
            'refine': lambda x: float(nll(x)) - best_v}


def scan_grid(likelihood, columns, fixed=None):
    """-2 ln L on an arbitrary parameter grid (columns broadcast to one shape)."""
    fixed = dict(fixed or {})
    shape = np.broadcast_shapes(*[np.shape(v) for v in columns.values()])
    flat = {k: np.broadcast_to(np.asarray(v, float), shape).ravel() for k, v in columns.items()}
    values = np.asarray(likelihood.twice_nll({**fixed, **flat}), float).reshape(shape)
    return values


def discovery(likelihood, parameter, *, null, start, bounds, points=201):
    """q0 = -2 ln lambda(null) for best fit above the null; Z = sqrt(q0)."""
    lo, hi = bounds
    grid = np.linspace(lo, hi, points)
    scan = scan_1d(likelihood, parameter, grid, domain=bounds)
    best = scan['best_fit'][parameter]
    q0 = max(0.0, likelihood.twice_nll({parameter: null}) - scan['best_fit']['twice_nll']) if best > null else 0.0
    return {'q0': q0, 'significance': math.sqrt(q0), 'best_fit': best, 'null': null,
            'best_fit_at_scan_edge': scan['best_fit']['at_scan_edge']}


def channel_from_spec(spec, *, form, floor):
    fields = {'name', 'observed', 'background', 'background_uncertainty'}
    if type(spec) is not dict or not fields <= set(spec) or set(spec) - fields - {'source', 'bin_labels'}:
        raise ValueError('channels need name, observed, background and background_uncertainty (plus optional source)')
    return Channel(spec['name'], spec['observed'], spec['background'], spec['background_uncertainty'],
                   form=form, floor=floor)
