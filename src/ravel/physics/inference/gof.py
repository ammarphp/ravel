"""Goodness of fit with a saturated-model statistic and per-toy auxiliary refits.

The statistic is ``q = -2 ln [L(theta_hat; n, a) / L_saturated(n)]``: the main
measurements are compared with a model that reproduces them exactly, and the
constraint terms stay evaluated at the best fit. Its distribution is built from
toys generated at the best fit. Each toy draws new main counts *and* new
auxiliary measurements, and the fit is repeated on the toy, so the reference
distribution includes the auxiliary uncertainty. A goodness of fit that keeps the
auxiliary measurements fixed understates that spread; it is never reported as
the goodness of fit (``auxiliary`` records which one was used).

When no toys are requested, or the toy budget runs out before any toy finishes,
the asymptotic chi-square approximation with the declared degrees of freedom is
reported and labelled ``asymptotic``.
"""
from __future__ import annotations

import math
import time

import numpy as np
from scipy import special, stats

MAX_TOYS = 100000


def options(raw):
    """Validate a ``goodness_of_fit`` request: toys, seed and a wall-clock budget."""
    if raw is None:
        return {'toys': 0, 'seed': 0, 'max_seconds': None}
    if type(raw) is not dict or set(raw) - {'toys', 'seed', 'max_seconds'}:
        raise ValueError('goodness_of_fit takes toys, seed and max_seconds')
    toys = raw.get('toys', 0)
    seed = raw.get('seed', 0)
    budget = raw.get('max_seconds')
    if type(toys) is not int or not 0 <= toys <= MAX_TOYS:
        raise ValueError(f'goodness_of_fit toys must be an integer from 0 to {MAX_TOYS}')
    if type(seed) is not int or seed < 0:
        raise ValueError('goodness_of_fit seed must be a nonnegative integer')
    if budget is not None and (type(budget) not in (int, float) or not budget > 0):
        raise ValueError('goodness_of_fit max_seconds must be positive')
    return {'toys': toys, 'seed': seed, 'max_seconds': budget}


def saturated_poisson_twice_nll(n):
    """-2 ln L of Poisson counts at their own values (continuous in n)."""
    n = np.asarray(n, float)
    with np.errstate(divide='ignore', invalid='ignore'):
        log = np.where(n > 0, n * np.log(np.where(n > 0, n, 1.0)), 0.0)
    return float(-2.0 * np.sum(log - n - special.gammaln(n + 1.0)))


def evaluate(observed, *, ndf, toy=None, request=None, statistic, auxiliary='refit', data_description=None):
    """Return a ``goodness-of-fit`` result.

    ``toy(rng)`` draws one toy (main and auxiliary data at the best fit), refits it
    and returns its statistic, or None when that toy's fit fails.
    """
    if auxiliary not in ('refit', 'fixed'):
        raise ValueError('auxiliary must be refit or fixed')
    opts = options(request)
    asymptotic = {'ndf': int(ndf), 'p_value': (float(stats.chi2.sf(observed, ndf)) if ndf > 0 else None),
                  'meaning': 'chi-square approximation with the stated degrees of freedom'}
    out = {'quantity': 'goodness-of-fit', 'role': 'diagnostic', 'statistic': statistic,
           'observed': float(observed), 'auxiliary': auxiliary, 'toys_requested': opts['toys'],
           'toys_completed': 0, 'toys_failed': 0, 'seed': opts['seed'], 'budget_exhausted': False,
           'asymptotic': asymptotic, 'data': data_description}
    values = []
    if opts['toys'] and toy is not None:
        rng = np.random.default_rng(opts['seed'])
        start = time.monotonic()
        for _ in range(opts['toys']):
            if opts['max_seconds'] is not None and time.monotonic() - start > opts['max_seconds']:
                out['budget_exhausted'] = True
                break
            value = toy(rng)
            if value is None or not math.isfinite(value):
                out['toys_failed'] += 1
            else:
                values.append(float(value))
    out['toys_completed'] = len(values)
    if values:
        values = np.asarray(values)
        # Conservative toy p-value: (k + 1) / (N + 1).
        exceed = int(np.sum(values >= observed))
        out.update(method='toys', p_value=(exceed + 1) / (len(values) + 1),
                   toy_band_95=[float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))],
                   toy_median=float(np.median(values)))
    else:
        out.update(method='asymptotic', p_value=asymptotic['p_value'], toy_band_95=None,
                   asymptotic_reason=('no toys requested' if not opts['toys'] else
                                      'the toy budget ended before any toy completed'))
    out['summary'] = (f'goodness of fit ({out["method"]}{"" if out["method"] == "toys" else " fallback"}): '
                      f'{statistic} = {observed:.4g}, p = '
                      + ('n/a' if out['p_value'] is None else f'{out["p_value"]:.3g}'))
    return out


# --------------------------------------------------------------------- binned Poisson channels

def counting_toy(likelihood, parameter, grid, domain, best):
    """Toy generator for ``counting.Likelihood`` at the best fit ``best`` (a parameter dict).

    Each toy draws counts from the fitted means and the auxiliary background
    measurement from its constraint at the fitted background, then refits the
    parameter on the same scan grid with every per-bin nuisance profiled.
    """
    from . import counting
    _, fitted = likelihood.per_channel(best, with_backgrounds=True)
    signal = likelihood.signal(best)

    def draw(rng):
        channels = []
        for c in likelihood.channels:
            s = np.asarray(signal[c.name], float).reshape(-1)
            bkg = np.asarray(fitted[c.name], float).reshape(-1)
            n = rng.poisson(np.clip(bkg + s, 0, None)).astype(float)
            toy = object.__new__(counting.Channel)
            toy.name, toy.form, toy.floor, toy.n, toy.d = c.name, c.form, c.floor, n, c.d.copy()
            if c.form == 'gaussian-linear':
                toy.b = rng.normal(bkg, c.d)
            elif c.form == 'poisson-gamma':
                tau = (c.b / c.d) ** 2
                m = rng.poisson(tau * bkg / c.b).astype(float)
                if np.any(m <= 0):
                    return None
                toy.b = m / tau * c.b
                toy.d = toy.b / np.sqrt(tau)
            elif c.form == 'lognormal':
                a = np.log1p(c.d / c.b)
                theta = np.log(bkg / c.b) / a
                toy.b = c.b * np.exp(a * rng.normal(theta, 1.0))
                toy.d = toy.b * c.d / c.b
            else:
                toy.b = c.b.copy()
            channels.append(toy)
        try:
            refit = counting.scan_1d(counting.Likelihood(channels, likelihood.signal), parameter, grid, domain=domain)
        except ValueError:
            return None
        return refit['best_fit']['twice_nll']
    return draw


# --------------------------------------------------------------------- pyhf models

def pyhf_statistic(model, pars, data):
    """Saturated-main statistic for a pyhf model: -2 ln L(pars) - (-2 ln L_sat(main counts))."""
    main = np.asarray(data, float)[:model.config.nmaindata]
    twice = float(-2.0 * model.logpdf(np.asarray(pars, float), np.asarray(data, float))[0])
    return twice - saturated_poisson_twice_nll(main)


def pyhf_toy(model, pars, fit):
    """Toy generator: sample main and auxiliary data at ``pars``; ``fit(data)`` returns refitted pars or None."""
    import pyhf
    pdf = model.make_pdf(pyhf.tensorlib.astensor(np.asarray(pars, float)))

    def draw(rng):
        seed = int(rng.integers(0, 2**31 - 1))
        state = np.random.get_state()
        np.random.seed(seed)  # pyhf's numpy backend samples through numpy's global generator
        try:
            data = np.asarray(pdf.sample((1,)), float)[0]
        finally:
            np.random.set_state(state)
        refit = fit(data)
        return None if refit is None else pyhf_statistic(model, refit, data)
    return draw
