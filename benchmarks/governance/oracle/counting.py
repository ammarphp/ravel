"""Independent single-bin asymptotic q-tilde CLs oracle (PROVISIONAL, unreviewed: PKT-D02).

Standard library only. It never imports pyhf, numpy, scipy or ravel, so it is independent
of the kernel it scores. It reproduces the *definitions* of pyhf 0.7.6, not its numerics.

Model (``pyhf.simplemodels.uncorrelated_background`` with signal ``[1]``, as the scoped
counting route builds it)::

    L(mu, g) = Pois(n | mu + g*b) * Pois(a | g*tau),   tau = b**2 / sigma_b**2,

with observed auxiliary count ``a = tau``, ``g`` in pyhf's shapesys bounds [1e-10, 10] and
``mu`` in [0, poi_cap]. Both Poisson terms are continuous (log-gamma normalised, as pyhf),
so non-integer Asimov counts are valid. With a unit signal, ``mu`` is in signal events.

Estimand (pyhf ``hypotest(test_stat="qtilde")``, asymptotics, ``calc_base_dist="normal"``):

- q~(mu) = 0 if mu_hat > mu, else max(0, 2*nll(mu, g_hat(mu)) - 2*nll(mu_hat, g_hat)),
  with mu_hat >= 0 (the fit is profiled at mu = 0 when the unbounded mu_hat is negative).
- Asimov data: the expectation (main and auxiliary) at mu = 0 and g = g_hat(0) fitted to
  the *observed* data (``generate_asimov_data(0.0, ...)``); q~_A is q~ on that data.
- Observed: t = sqrt(q) - sqrt(qA) if sqrt(q) <= sqrt(qA), else (q - qA) / (2 sqrt(qA));
  CLs = Phi(-(t + sqrt(qA))) / Phi(-t).
- Expected: t = k for k = +2, +1, 0, -1, -2, which give the -2, -1, 0, +1, +2 sigma limits.
- The limit is the mu where CLs = level, per curve.

Numerics: the conditional MLE g_hat(mu) is the positive root of a quadratic score equation;
the unconditional fit is closed form (the log-likelihood is jointly concave, so its stationary
point g = a/tau, mu = n - g*b is the maximum, or mu = 0 when that is negative); q~ uses a
cancellation-free form; Phi uses ``math.erfc``; each root is found by bisection to adjacent
floating-point numbers. Unresolved curves are reported as ``above_cap`` with a null value,
never as a fabricated root. Inputs whose arithmetic leaves the float range raise ContractError.

Cap-bounded models (a POI range [0, poi_cap] set by the workspace, e.g. [0, 10]): a curve is
``above_cap`` exactly when its CLs at mu = poi_cap is still above the level. Whenever a curve has
that status, all six curves are checked on the 64-point grid over (0, poi_cap]. The five expected
curves are monotone analytically: CLs_exp = Phi(-(k + sqrt(q~_A))) / Phi(-k), and q~_A increases
with mu (the log-likelihood is jointly concave and the Asimov mu_hat is 0). For them CLs(poi_cap)
> level proves there is no crossing in (0, poi_cap]. The observed curve, Phi(-sqrt(q~)) /
Phi(sqrt(q~_A) - sqrt(q~)) on its lower branch, is not monotone by construction. It is only
verified monotone on the grid, so for it CLs(poi_cap) > level supports "no crossing in
(0, poi_cap]" without proving it: a dip below the level between grid points would not be seen.
(A 400-point check of 399 random models found no rise on any observed curve; see the WP12
oracle appendix.) The only supported statements about an above_cap limit are the relations
"limit > poi_cap" (strict) and the weaker "limit >= poi_cap", in signal events; the value is
null, never the cap. ``limits`` then also returns ``cls_at_cap``, the six CLs at mu = poi_cap,
as evidence for the status. A resolved root never depends on the cap: the same definitions give
the same root for every cap above it. ``cls_at`` evaluates the six CLs at any mu in
(0, poi_cap] with exactly the definitions (and the same functions) the root solver uses.

Status vocabulary: the kernel (``ravel.physics.pyhf_exclude.compute``) reports the same unresolved
condition (CLs still above the level at the POI cap) as ``above_scan`` with the cap as a numeric
bound; see KERNEL_LIMIT_STATUS. The kernel's ``below_scan`` (CLs already below the level at the
first point of its scan, which lies at or below 1e-3 events) has no oracle status. The two floors
differ: the oracle raises ContractError only when CLs is still at or below the level after mu is
halved down to MU_FLOOR = 1e-9 events, so it would resolve a root just below the kernel's first
scan point that the kernel reports as below_scan. No unit-signal model can put a root there. For
a unit signal the negative log-likelihood rises by at most one unit per signal event, so q~ and
q~_A are at most 2 mu. At mu = 1e-3, sqrt(q~_A) <= 0.045, and every one of the six CLs exceeds
0.89 (the -2 sigma expected curve is the lowest, Phi(-2.045) / Phi(-2)). The kernel's below_scan
therefore cannot occur for the models this oracle accepts.

Convention values (WP12 design §1.4 rule 4): ``convention_limits`` evaluates the same limits under a
known legitimate alternative, the pre-fit (nominal-nuisance, g = 1) background-only Asimov data. A
family builder lists such values as ``convention_values`` (verdict unresolved), never as the oracle
value. Toy-based CLs is excluded by the pinned estimand clause (decision E-118) and is not computed.
"""
from __future__ import annotations

import json
import math

from governance.canonical import ContractError, finite_number, require, sha256_bytes, strict_loads

GAMMA_BOUNDS = (1e-10, 10.0)        # pyhf 0.7.6 shapesys default parameter bounds
EXPECTED_SHIFTS = (2, 1, 0, -1, -2)  # test-statistic values of the -2..+2 sigma expected curves
ROOT_RTOL = 1e-12                    # required relative bracket width of every resolved root
CLS_RESIDUAL_ATOL = 1e-9             # required |CLs(root) - level|
MU_FLOOR = 1e-9                      # lowest mu searched for a lower bracket (signal events)
SIGNIFICANT_DIGITS = 10              # oracle-record values; platform-stable digests
INPUT_KINDS = {"workspace.json": "workspace", "luminosity.json": "luminosity", "title.txt": "title"}
KERNEL_LIMIT_STATUS = {"resolved": "resolved", "above_cap": "above_scan"}  # oracle -> kernel status


def _phi(x):
    """Standard normal CDF, accurate in both tails."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _h(x):
    """x - log(1 + x) without cancellation for small |x| (x > -1)."""
    if abs(x) < 0.1:
        return sum((-x) ** k / k for k in range(2, 30))
    return x - math.log1p(x)


class _SingleBin:
    """Shapesys single-bin likelihood with unit signal; data are (main count n, auxiliary a)."""

    def __init__(self, background, background_uncertainty):
        self.b = float(background)
        self.tau = self.b ** 2 / float(background_uncertainty) ** 2  # pyhf: nom**2 / unc**2
        require(math.isfinite(self.tau) and self.tau > 0,
                "background**2 / background_uncertainty**2 must be a finite positive number")

    def gamma_hat(self, mu, n, a):
        """Conditional MLE of g at fixed mu.

        The score equation is b(b+tau) g^2 + [(b+tau) mu - (n+a) b] g - a mu = 0; with a
        positive leading and a nonpositive constant coefficient it has one nonnegative root.
        The conditional log-likelihood is concave in g, so the bounded MLE is the clipped root.
        """
        qa = self.b * (self.b + self.tau)
        qb = (self.b + self.tau) * mu - (n + a) * self.b
        qc = -a * mu
        disc = math.sqrt(qb * qb - 4.0 * qa * qc)
        g = (disc - qb) / (2.0 * qa) if qb <= 0 else (-2.0 * qc) / (qb + disc)
        return min(max(g, GAMMA_BOUNDS[0]), GAMMA_BOUNDS[1])

    def free_fit(self, n, a):
        """Unconditional MLE (mu_hat >= 0, g_hat) in closed form.

        The log-likelihood is jointly concave in (mu, g); its stationary point saturates both
        terms (g = a/tau, mu = n - g*b). If that mu is negative the concave profile is maximal
        at mu = 0. An upper POI bound is irrelevant: q~ is zero whenever mu_hat exceeds mu.
        """
        g = a / self.tau
        lo, hi = GAMMA_BOUNDS
        require(lo * (1 - 1e-12) <= g <= hi * (1 + 1e-12),
                "unconditional nuisance MLE outside the shapesys bounds")
        g = min(max(g, lo), hi)
        mu = n - g * self.b
        return (mu, g) if mu >= 0 else (0.0, self.gamma_hat(0.0, n, a))

    def qtilde(self, mu, n, a, fit):
        """q~(mu) on data (n, a) given its unconditional fit, as pyhf's qmu_tilde."""
        mu_hat, g_hat = fit
        if mu_hat > mu:
            return 0.0
        g = self.gamma_hat(mu, n, a)
        lam0, lam1 = mu_hat + g_hat * self.b, mu + g * self.b
        x, y = (lam1 - lam0) / lam0, (g - g_hat) / g_hat
        # 2*nll(mu, g) - 2*nll(mu_hat, g_hat), rearranged so no large terms cancel.
        q = 2.0 * ((lam0 - n) * x + n * _h(x) + (g_hat * self.tau - a) * y + a * _h(y))
        return max(q, 0.0)


def _cls(model, mu, observed, asimov):
    """[CLs_obs, CLs_exp(-2 sigma) ... CLs_exp(+2 sigma)] at signal strength mu > 0."""
    q = model.qtilde(mu, *observed)
    qa = model.qtilde(mu, *asimov)
    require(math.isfinite(q) and math.isfinite(qa), f"nonfinite test statistic at mu={mu!r}")
    sqa, sq = math.sqrt(qa), math.sqrt(q)
    if sqa == 0.0:
        require(q == 0.0, f"Asimov test statistic vanished at mu={mu!r}; CLs undefined")
        return [1.0] * 6
    t = sq - sqa if sq <= sqa else (q - qa) / (2.0 * sqa)
    cl_b = _phi(-t)
    require(cl_b > 0.0, f"CL_b underflows at mu={mu!r}; CLs undefined")
    return [_phi(-(t + sqa)) / cl_b] + [_phi(-(k + sqa)) / _phi(-k) for k in EXPECTED_SHIFTS]


def _solve(f, poi_cap):
    """Root of a decreasing f with f(0+) > 0 on (0, poi_cap]: (value or None, status)."""
    lo, hi = None, min(1.0, poi_cap)
    while f(hi) > 0:
        if hi >= poi_cap:
            return None, "above_cap"
        lo, hi = hi, min(2.0 * hi, poi_cap)
    if lo is None:
        lo = hi / 2.0
        while f(lo) <= 0:
            require(lo > MU_FLOOR, "no lower CLs bracket above the mu floor; limit not resolved")
            hi, lo = lo, lo / 2.0
    for _ in range(2000):
        mid = 0.5 * (lo + hi)
        if not lo < mid < hi:
            break
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    require((hi - lo) <= ROOT_RTOL * hi, "bisection did not reach the root tolerance")
    return hi, "resolved"


ASIMOV = {"conditional": "background-only (mu = 0) at the conditional mu = 0 fit to observed data",
          "prefit": "background-only (mu = 0) at the nominal nuisance g = 1 (pre-fit; a convention alternative, "
                    "never the oracle value)"}


def _datasets(model, n, asimov="conditional"):
    """Observed data and the background-only Asimov data, each with its unconditional fit. The Asimov nuisance is
    the conditional background-only fit to data (the estimand) or, for the pre-fit convention, nominal (g = 1)."""
    a = model.tau
    observed = (n, a, model.free_fit(n, a))
    g0 = model.gamma_hat(0.0, n, a) if asimov == "conditional" else 1.0
    n_asimov, a_asimov = g0 * model.b, g0 * model.tau
    return observed, (n_asimov, a_asimov, model.free_fit(n_asimov, a_asimov))


def limits(n_obs, background, background_uncertainty, *, level=0.05, poi_cap=256.0) -> dict:
    """95% (level=0.05) asymptotic q~ CLs upper limits on signal events, observed and expected.

    Returns ``obs_limit_events``, ``exp_limits_events`` (-2..+2 sigma), ``limit_status``
    ({"observed": s, "expected": [s]*5}, s in resolved/above_cap; unresolved values are null),
    ``cls_at_cap`` (the six CLs at mu = poi_cap when any curve is above_cap, else null),
    ``method`` and ``root_precision``. ``above_cap`` means CLs(poi_cap) > level on a curve
    verified monotone over (0, poi_cap]: the limit exceeds poi_cap (strictly) and has no value
    inside the POI range. Full precision; ``oracle_record`` rounds. Every failure, including
    float overflow or underflow on extreme inputs, raises ContractError.
    """
    return _checked_limits(n_obs, background, background_uncertainty, level, poi_cap, "conditional")


def convention_limits(n_obs, background, background_uncertainty, *, convention="prefit_asimov", level=0.05,
                      poi_cap=256.0) -> dict:
    """``limits`` under a known legitimate convention alternative (only ``prefit_asimov``: the background-only
    Asimov data at the nominal nuisance, g = 1). Same record shape; ``method.estimand`` names the convention.
    A convention value is never the oracle value (design §1.4 rule 4)."""
    require(convention == "prefit_asimov", f"convention: only prefit_asimov is defined, not {convention!r}")
    result = _checked_limits(n_obs, background, background_uncertainty, level, poi_cap, "prefit")
    result["method"]["estimand"] = "convention_value_prefit_asimov"
    return result


def _checked_limits(n_obs, background, background_uncertainty, level, poi_cap, asimov):
    require(finite_number(n_obs) and n_obs >= 0, "n_obs: finite nonnegative number required")
    require(finite_number(background) and background > 0, "background: finite positive number required")
    require(finite_number(background_uncertainty) and background_uncertainty > 0,
            "background_uncertainty: finite positive number required")
    require(finite_number(level) and 0 < level < 1, "level: must lie strictly between 0 and 1")
    require(finite_number(poi_cap) and poi_cap > 0, "poi_cap: finite positive number required")
    try:
        return _limits(n_obs, background, background_uncertainty, level, float(poi_cap), asimov)
    except ContractError:
        raise
    except (ArithmeticError, ValueError) as exc:   # float overflow, underflow to zero, math domain
        raise ContractError(f"counting oracle arithmetic failed for these inputs: {exc!r}") from exc


def _limits(n_obs, background, background_uncertainty, level, poi_cap, convention="conditional"):
    model = _SingleBin(background, background_uncertainty)
    observed, asimov = _datasets(model, float(n_obs), convention)

    def curve(index):
        return lambda mu: _cls(model, mu, observed, asimov)[index] - level

    solved = [_solve(curve(i), poi_cap) for i in range(6)]
    values = [value for value, _ in solved]
    resolved = [v for v in values if v is not None]
    for i, value in enumerate(values):
        if value is not None:
            require(abs(curve(i)(value)) <= CLS_RESIDUAL_ATOL, "CLs residual at root exceeds tolerance")
    # Each root is unique only if its curve is monotone; check all six on a fixed grid. An
    # above_cap status means "no crossing in (0, poi_cap]", so the grid then spans the full range.
    above_cap = any(status == "above_cap" for _, status in solved)
    top = poi_cap if above_cap or not resolved else min(poi_cap, 2.0 * max(resolved))
    grid = [_cls(model, top * i / 64, observed, asimov) for i in range(1, 65)]
    for i in range(6):
        require(all(later[i] <= earlier[i] + 1e-12 for earlier, later in zip(grid, grid[1:])),
                "CLs curve is not monotonically decreasing; root would not be unique")
    return {
        "obs_limit_events": values[0],
        "exp_limits_events": values[1:],
        "limit_status": {"observed": solved[0][1], "expected": [s for _, s in solved[1:]]},
        "cls_at_cap": _cls_record(_cls(model, poi_cap, observed, asimov)) if above_cap else None,
        "method": {
            "estimand": "asymptotic_qtilde_cls_upper_limit", "level": level,
            "definition": "pyhf 0.7.6 hypotest(test_stat='qtilde', calctype='asymptotics', "
                          "calc_base_dist='normal')",
            "model": "single-bin uncorrelated_background: unit normfactor signal mu, shapesys "
                     "Poisson-constrained background, tau = b**2/sigma_b**2",
            "asimov": ASIMOV[convention],
            "expected_order": ["-2", "-1", "0", "+1", "+2"],
            "poi_bounds": [0.0, poi_cap], "gamma_bounds": list(GAMMA_BOUNDS),
            "implementation": "closed-form profiles; standard library only; no pyhf or ravel",
        },
        "root_precision": {"solver": "bracketed bisection to adjacent floats", "rtol": ROOT_RTOL,
                           "cls_residual_atol": CLS_RESIDUAL_ATOL, "monotonicity_grid_points": 64},
    }


def _cls_record(values):
    return {"observed": values[0], "expected": values[1:]}


def cls_at(n_obs, background, background_uncertainty, mu, *, poi_cap=256.0) -> dict:
    """Observed and expected (-2..+2 sigma) asymptotic q~ CLs at one signal strength mu.

    Same model, estimand and Asimov data as ``limits``, evaluated by the very function its root
    solver brackets, at full double precision (no root, so no solver tolerance applies). mu is
    in signal events and must lie in the model's POI range (0, poi_cap]; mu = 0 is excluded
    because CLs is not defined there. Returns ``mu``, ``observed``, ``expected`` (-2..+2 sigma
    order, as ``exp_limits_events``) and ``poi_bounds``. Every failure raises ContractError.
    """
    require(finite_number(n_obs) and n_obs >= 0, "n_obs: finite nonnegative number required")
    require(finite_number(background) and background > 0, "background: finite positive number required")
    require(finite_number(background_uncertainty) and background_uncertainty > 0,
            "background_uncertainty: finite positive number required")
    require(finite_number(poi_cap) and poi_cap > 0, "poi_cap: finite positive number required")
    require(finite_number(mu) and 0 < mu <= poi_cap, "mu: must lie in the POI range (0, poi_cap]")
    try:
        model = _SingleBin(background, background_uncertainty)
        observed, asimov = _datasets(model, float(n_obs))
        values = _cls(model, float(mu), observed, asimov)
    except ContractError:
        raise
    except (ArithmeticError, ValueError) as exc:
        raise ContractError(f"counting oracle arithmetic failed for these inputs: {exc!r}") from exc
    return {"mu": float(mu), **_cls_record(values), "poi_bounds": [0.0, float(poi_cap)]}


def cls_at_workspace(workspace: dict, mu) -> dict:
    """``cls_at`` for exactly the scoped counting workspace (POI range read from the workspace)."""
    counting = parse_counting_workspace(workspace)
    return cls_at(counting["n_obs"], counting["background"], counting["background_uncertainty"], mu,
                  poi_cap=counting["poi_cap"])


def _one_number(value, label):
    require(isinstance(value, list) and len(value) == 1 and finite_number(value[0]),
            f"{label}: expected a one-element list holding a finite number")
    return value[0]


def _keys(value, expected, label):
    require(isinstance(value, dict), f"{label}: expected object")
    require(set(value) == set(expected), f"{label}: fields must be {sorted(expected)}")


def parse_counting_workspace(workspace: dict) -> dict:
    """Extract the counting inputs from exactly the workspace the scoped route builds.

    Anything else (other samples, modifiers, channels, measurements, signal != 1, POI bounds
    or inits) raises ContractError: this oracle is valid for that one model only.
    """
    _keys(workspace, {"version", "channels", "observations", "measurements"}, "workspace")
    require(workspace["version"] == "1.0.0", "workspace version: expected 1.0.0")
    channels = workspace["channels"]
    require(isinstance(channels, list) and len(channels) == 1, "workspace: exactly one channel required")
    _keys(channels[0], {"name", "samples"}, "channel")
    require(channels[0]["name"] == "singlechannel", "channel name: expected singlechannel")
    samples = channels[0]["samples"]
    require(isinstance(samples, list) and len(samples) == 2, "channel: exactly signal and background samples")
    signal, background = samples
    _keys(signal, {"name", "data", "modifiers"}, "signal sample")
    require(signal["name"] == "signal", "first sample: expected signal")
    require(_one_number(signal["data"], "signal data") == 1, "signal: unit signal template required")
    require(signal["modifiers"] == [{"name": "mu", "type": "normfactor", "data": None}],
            "signal modifiers: exactly the normfactor mu")
    _keys(background, {"name", "data", "modifiers"}, "background sample")
    require(background["name"] == "background", "second sample: expected background")
    b = _one_number(background["data"], "background data")
    modifiers = background["modifiers"]
    require(isinstance(modifiers, list) and len(modifiers) == 1, "background: exactly one modifier")
    _keys(modifiers[0], {"name", "type", "data"}, "background modifier")
    require(modifiers[0]["name"] == "uncorr_bkguncrt" and modifiers[0]["type"] == "shapesys",
            "background modifier: expected shapesys uncorr_bkguncrt")
    sigma = _one_number(modifiers[0]["data"], "background uncertainty")
    require(b > 0 and sigma > 0, "background and its uncertainty must be positive")
    observations = workspace["observations"]
    require(isinstance(observations, list) and len(observations) == 1, "exactly one observation")
    _keys(observations[0], {"name", "data"}, "observation")
    require(observations[0]["name"] == "singlechannel", "observation name: expected singlechannel")
    n = _one_number(observations[0]["data"], "observed count")
    require(n >= 0, "observed count must be nonnegative")
    measurements = workspace["measurements"]
    require(isinstance(measurements, list) and len(measurements) == 1, "exactly one measurement")
    _keys(measurements[0], {"name", "config"}, "measurement")
    require(measurements[0]["name"] == "counting", "measurement name: expected counting")
    _keys(measurements[0]["config"], {"poi", "parameters"}, "measurement config")
    require(measurements[0]["config"]["poi"] == "mu", "measurement POI: expected mu")
    parameters = measurements[0]["config"]["parameters"]
    require(isinstance(parameters, list) and len(parameters) == 1, "exactly one parameter setting")
    _keys(parameters[0], {"name", "bounds", "inits"}, "POI parameter")
    require(parameters[0]["name"] == "mu", "parameter setting: expected mu")
    bounds = parameters[0]["bounds"]
    require(isinstance(bounds, list) and len(bounds) == 1 and isinstance(bounds[0], list)
            and len(bounds[0]) == 2 and all(finite_number(v) for v in bounds[0]),
            "POI bounds: expected [[0, poi_cap]]")
    require(bounds[0][0] == 0 and bounds[0][1] > 0, "POI bounds: expected [[0, poi_cap]] with poi_cap > 0")
    cap = bounds[0][1]
    require(_one_number(parameters[0]["inits"], "POI inits") == min(1, cap / 2),
            "POI inits: expected [min(1, poi_cap / 2)]")
    return {"n_obs": n, "background": b, "background_uncertainty": sigma, "poi_cap": cap}


def _json_bytes(data, name):
    try:
        return strict_loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{name}: not strict UTF-8 JSON ({exc})") from exc


def _luminosity_fb(record):
    _keys(record, {"luminosity_fb", "status", "source"}, "luminosity record")
    value = record["luminosity_fb"]
    require(finite_number(value) and value > 0, "luminosity_fb: finite positive number required")
    for name in ("status", "source"):
        require(isinstance(record[name], str) and record[name].strip(), f"luminosity {name}: nonempty string")
    return value


def _rounded(value):
    return None if value is None else float(f"{value:.{SIGNIFICANT_DIGITS - 1}e}")


def _oracle_side(files, label):
    require(isinstance(files, dict), f"{label} inputs: expected {{name: bytes}}")
    require(set(files) <= set(INPUT_KINDS), f"{label} inputs: unknown names {sorted(set(files) - set(INPUT_KINDS))}")
    require("workspace.json" in files, f"{label} inputs: workspace.json required")
    require(all(type(data) is bytes for data in files.values()), f"{label} inputs: values must be bytes")
    counting = parse_counting_workspace(_json_bytes(files["workspace.json"], "workspace.json"))
    lumi = _luminosity_fb(_json_bytes(files["luminosity.json"], "luminosity.json")) \
        if "luminosity.json" in files else None
    result = limits(counting["n_obs"], counting["background"], counting["background_uncertainty"],
                    poi_cap=counting["poi_cap"])

    def sigma(value):
        if value is None or lumi is None:
            return None
        converted = value / lumi
        require(math.isfinite(converted), "sigma_vis = S95 / luminosity_fb overflows")
        return _rounded(converted)

    return {
        "inputs": {name: sha256_bytes(files[name]) for name in sorted(files)},
        "counting": counting,
        "luminosity_fb": lumi,
        "obs_limit_events": _rounded(result["obs_limit_events"]),
        "exp_limits_events": [_rounded(v) for v in result["exp_limits_events"]],
        "limit_status": result["limit_status"],
        "sigma_vis_obs_fb": sigma(result["obs_limit_events"]),
        "sigma_vis_exp_fb": [sigma(v) for v in result["exp_limits_events"]],
        "cls_at_cap": None if result["cls_at_cap"] is None else {
            "observed": _rounded(result["cls_at_cap"]["observed"]),
            "expected": [_rounded(v) for v in result["cls_at_cap"]["expected"]]},
        "method": result["method"],
        "root_precision": result["root_precision"],
    }


def oracle_record(current: dict, prior: dict | None = None) -> dict:
    """Evaluator oracle for one task variant from the exact input bytes.

    ``current`` and ``prior`` map input file names (workspace.json, optional luminosity.json,
    optional title.txt) to bytes; ``prior`` is None for a task without prior inputs (its side is
    then null). Each side carries the input digests, the counting inputs, the limits in events,
    sigma_vis = S95 / L in fb (null without a luminosity record or for an unresolved limit) and
    ``cls_at_cap``, the six CLs at mu = poi_cap when a curve is above_cap (the evidence for that
    status), else null. Field names match the claim ``artifact_field`` vocabulary. Values are
    rounded to 10 significant digits so the record digest is platform-stable. ``cls_at_cap`` joined
    each side at WP12 plan step 7, as the oracle appendix planned (§1b): the likelihood_freshness
    records gain a null field on each side, so their bytes and digests changed with it.
    """
    return {
        "schema_version": 1,
        "oracle": "governance.oracle.counting",
        "provisional": True,
        "review": "unreviewed (PKT-D02 pending)",
        "significant_digits": SIGNIFICANT_DIGITS,
        "current": _oracle_side(current, "current"),
        "prior": None if prior is None else _oracle_side(prior, "prior"),
    }
