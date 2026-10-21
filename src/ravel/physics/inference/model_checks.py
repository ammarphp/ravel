"""Model validation on a pyhf model: Asimov signal injection and the false-exclusion rate at the truth.

- ``signal_injection(model, injected)``: for each injected strength the Asimov data set at that
  strength (nuisance parameters at their nominal values) is fitted with every parameter free
  (iminuit MIGRAD, then HESSE). A well-defined model recovers the injected strength with a valid
  fit and an accurate covariance; a degenerate signal (for example one that a free background
  normalisation can absorb), a boundary that cuts the strength, or a defective parameterisation
  shows up as a bias, an invalid fit or an inaccurate covariance.
- ``exclusion_coverage(model, mu_true, ntoys, seed)``: toys drawn at the true strength; the
  fraction whose asymptotic CLs at ``mu_true`` falls below the level is the false-exclusion rate,
  reported with its Clopper-Pearson interval at 95% confidence. A 95% CLs procedure should not
  exceed 5%; CLs is conservative, so a rate well below 5% is expected.

These produce the evidence the statistics catalogue's ``signal-injection`` and
``coverage-at-truth`` checks read. They test the model as supplied; they do not test the
inputs that built it.
"""
from __future__ import annotations

import math

import numpy as np


def _fit(model, data, *, fixed=None, init=None, bounds=None):
    import iminuit
    config = model.config
    start = np.array(config.suggested_init() if init is None else init, dtype=float, copy=True)
    limits = [list(b) for b in (config.suggested_bounds() if bounds is None else bounds)]
    frozen = list(config.suggested_fixed())
    for index, value in (fixed or {}).items():
        start[index] = value
        frozen[index] = True
    data = np.asarray(data, float)

    def objective(pars):
        value = float(-2.0 * np.asarray(model.logpdf(np.asarray(pars, float), data)).ravel()[0])
        return value if math.isfinite(value) else 1e30

    minuit = iminuit.Minuit(objective, start)
    minuit.errordef = 1.0
    minuit.limits = limits
    minuit.fixed = frozen
    minuit.strategy = 1
    minuit.migrad()
    if not minuit.fmin.is_valid:
        minuit.strategy = 2
        minuit.migrad()
    minuit.hesse()
    return minuit


def _poi_bounds(model, value):
    bounds = [list(b) for b in model.config.suggested_bounds()]
    index = model.config.poi_index
    low, high = bounds[index]
    bounds[index] = [min(low, 0.0), max(high, 3.0 * abs(value) + 1.0)]
    return bounds


def _identifiable(model, pars):
    """The local main/auxiliary response must identify every free parameter.

    A numerical HESSE can report an accurate covariance for an exactly flat
    direction. Check the rank independently, including auxiliary constraints.
    Column normalization removes the arbitrary units of the parameters.
    """
    columns = []
    for index, fixed in enumerate(model.config.suggested_fixed()):
        if fixed:
            continue
        step = 1e-5 * max(1.0, abs(pars[index]))
        low, high = np.array(pars, copy=True), np.array(pars, copy=True)
        low[index] -= step
        high[index] += step
        columns.append((np.asarray(model.expected_data(high), float)
                        - np.asarray(model.expected_data(low), float)) / (2 * step))
    if not columns:
        return True
    jacobian = np.column_stack(columns)
    norms = np.linalg.norm(jacobian, axis=0)
    if not np.all(np.isfinite(jacobian)) or np.any(norms == 0):
        return False
    return np.linalg.matrix_rank(jacobian / norms) == len(columns)


def signal_injection(model, injected=(1.0,)) -> list[dict]:
    """Inject each strength on Asimov data and fit it back; one row per injected strength."""
    config = model.config
    if config.poi_index is None:
        raise ValueError("signal injection needs a model with a parameter of interest")
    rows = []
    for mu in injected:
        if type(mu) not in (int, float) or not math.isfinite(mu) or mu < 0:
            raise ValueError("injected strengths must be finite and nonnegative")
        pars = np.asarray(config.suggested_init(), float)
        pars[config.poi_index] = mu
        asimov = np.asarray(model.expected_data(pars), float)
        minuit = _fit(model, asimov, bounds=_poi_bounds(model, mu))
        index = config.poi_index
        fitted, sigma = float(minuit.values[index]), float(minuit.errors[index])
        rows.append({"injected": float(mu), "fitted": fitted, "uncertainty": sigma,
                     "valid": bool(minuit.fmin.is_valid and minuit.accurate
                                   and _identifiable(model, np.asarray(minuit.values, float))),
                     "bias_in_sigma": (fitted - mu) / sigma if sigma > 0 else None,
                     "edm": float(minuit.fmin.edm), "data": "Asimov at the injected strength, nominal nuisances"})
    return rows


class _DevianceModel:
    """The same likelihood up to a data-only constant, without large Poisson cancellations."""

    def __init__(self, model):
        self.model = model
        self.normal = []
        offset = model.config.nmaindata
        for name in model.config.auxdata_order:
            parameter = model.config.param_set(name)
            if parameter.pdf_type == "normal":
                self.normal.extend(zip(range(offset, offset + parameter.n_parameters), parameter.width()))
            elif parameter.pdf_type != "poisson":
                raise ValueError(f"unsupported auxiliary law {parameter.pdf_type!r}")
            offset += parameter.n_parameters

    def __getattr__(self, name):
        return getattr(self.model, name)

    def logpdf(self, pars, data):
        mean = np.asarray(self.model.expected_data(pars), float)
        observed = np.asarray(data, float)
        poisson = np.ones(len(observed), dtype=bool)
        total = 0.0
        for index, width in self.normal:
            poisson[index] = False
            total += ((observed[index] - mean[index]) / width) ** 2
        mean, observed = mean[poisson], observed[poisson]
        if np.any(mean < 0):
            return np.asarray([-math.inf])
        positive = observed > 0
        total += 2 * np.sum(mean[~positive])
        with np.errstate(divide="ignore", invalid="ignore"):
            rate, count = mean[positive], observed[positive]
            delta = (rate - count) / count
            terms = np.where(abs(delta) < .5, count * (delta - np.log1p(delta)),
                             rate - count + count * (np.log(count) - np.log(rate)))
            total += 2 * np.sum(terms)
        return np.asarray([-0.5 * total])


def exclusion_coverage(model, *, mu_true=1.0, ntoys=200, seed=1, level=0.05) -> dict:
    """False-exclusion rate of the asymptotic CLs test at the true strength, from seeded toys."""
    import pyhf
    from scipy.stats import beta
    config = model.config
    if config.poi_index is None:
        raise ValueError("coverage needs a model with a parameter of interest")
    if type(ntoys) is not int or not 20 <= ntoys <= 100000:
        raise ValueError("coverage toys must be an integer in [20, 100000]")
    if type(seed) is not int or not 0 <= seed < 2 ** 32:
        raise ValueError("the coverage seed must be an integer in [0, 2^32)")
    pars = np.asarray(config.suggested_init(), float)
    pars[config.poi_index] = mu_true
    state = np.random.get_state()
    try:
        np.random.seed(seed)
        toys = np.asarray(model.make_pdf(pars).sample((ntoys,)), float)
    finally:
        np.random.set_state(state)
    bounds = _poi_bounds(model, mu_true)
    bounds[config.poi_index][0] = 0.0
    widths = np.ones(config.npars)
    for name in config.par_order:
        parameter = config.param_set(name)
        if getattr(parameter, "constrained", False):
            widths[config.par_slice(name)] = parameter.width()

    class CoverageOptimizer(pyhf.optimize.minuit_optimizer):
        def _get_minimizer(self, *args, **kwargs):
            minimizer = super()._get_minimizer(*args, **kwargs)
            # A default step of order one cannot resolve a tight auxiliary constraint.
            minimizer.errors = np.where(widths > 0, widths, 1.0)
            return minimizer

        def _minimize(self, minimizer, func, x0, **kwargs):
            if all(minimizer.fixed):
                from scipy.optimize import OptimizeResult
                return OptimizeResult(x=np.asarray(x0), fun=float(func(np.asarray(x0))),
                                      success=True, nfev=1, message="every parameter is fixed")
            return super()._minimize(minimizer, func, x0, **kwargs)

    previous = pyhf.get_backend()
    excluded, failed = 0, 0
    try:
        pyhf.set_backend("numpy", CoverageOptimizer(strategy=2, tolerance=.01), precision="64b")
        stable = _DevianceModel(model)
        for toy in toys:
            try:
                cls = float(pyhf.infer.hypotest(mu_true, toy, stable, par_bounds=bounds, test_stat="qtilde"))
            except Exception:  # retain failed fits explicitly in the record
                failed += 1
                continue
            if not math.isfinite(cls):
                failed += 1
            elif cls < level:
                excluded += 1
    finally:
        pyhf.set_backend(*previous)
    n = ntoys - failed
    if n <= 0:
        raise ValueError("every coverage toy failed to fit")
    confidence = 0.95
    alpha = 1 - confidence
    lower = 0.0 if excluded == 0 else float(beta.ppf(alpha / 2, excluded, n - excluded + 1))
    upper = 1.0 if excluded == n else float(beta.ppf(1 - alpha / 2, excluded + 1, n - excluded))
    return {"method": "toy false-exclusion rate", "mu_true": float(mu_true), "level": float(level),
            "toys": ntoys, "failed_toys": failed, "seed": seed, "excluded": excluded,
            "false_exclusion_rate": excluded / n, "false_exclusion_lower": lower, "false_exclusion_upper": upper,
            "interval_confidence": confidence, "calculator": "asymptotic qtilde"}
