"""Recorded CLs calculator selection and bounded finite-toy crossings."""
from copy import deepcopy
import math

import numpy as np

from ravel.limits import attach_limits, read_limits


SMALL_COUNT = 5.0
PILOT_TOYS = 10


class ToyBudgetExceeded(RuntimeError):
    """The complete proposed toy grid exceeds the declared fit or wall-time budget."""

    def __init__(self, estimated_fits, max_fits, *, estimated_seconds=None, max_seconds=None, bound="fits",
                 pilot=None):
        self.estimated_fits = estimated_fits
        self.max_fits = max_fits
        self.estimated_seconds = estimated_seconds
        self.max_seconds = max_seconds
        self.bound = bound
        self.pilot = pilot
        if bound == "seconds":
            message = (f"toy grid needs about {estimated_seconds:.0f} s for {estimated_fits} toy experiments at the "
                       f"cost measured by a {pilot['toys']}-toy pilot; wall-time budget is {max_seconds} s")
        else:
            message = f"toy grid needs {estimated_fits} estimated fits; budget is {max_fits}"
        super().__init__(message)


def calculator_policy(model, data, *, requested="auto") -> dict:
    """Inspect only main bins at the nominal background-only parameters."""
    if requested not in ("auto", "asymptotic", "toybased"):
        raise ValueError("CLs calculator must be auto, asymptotic or toybased")
    pars = list(model.config.suggested_init())
    if model.config.poi_index is None:
        raise ValueError("CLs calculator policy needs a parameter of interest")
    pars[model.config.poi_index] = 0.0
    background = np.asarray(model.expected_actualdata(pars), dtype=float)
    observed = np.asarray(data, dtype=float)
    if (observed.ndim != 1 or len(observed) < model.config.nmaindata
            or not np.all(np.isfinite(observed[:model.config.nmaindata]))
            or np.any(observed[:model.config.nmaindata] < 0)
            or not np.all(np.isfinite(background)) or np.any(background < 0)):
        raise ValueError("calculator policy needs finite nonnegative main-bin counts")
    triggers, offset = [], 0
    for channel in model.config.channels:
        for index in range(model.config.channel_nbins[channel]):
            n, b = float(observed[offset]), float(background[offset])
            if n < SMALL_COUNT or b < SMALL_COUNT:
                triggers.append({"channel": channel, "bin": index, "n": n, "b": b})
            offset += 1
    applied = ("toybased" if triggers else "asymptotic") if requested == "auto" else requested
    reason = (f"small-count regime: {len(triggers)} main bin(s) below {SMALL_COUNT} expected or observed counts"
              if triggers else f"all main bins at or above {SMALL_COUNT} expected and observed counts")
    return {"requested": requested, "applied": applied, "small_count_threshold": SMALL_COUNT,
            "triggers": triggers, "reason": reason if requested == "auto" else "requested"}


def _validate_options(ntoys, seed, max_fits, max_seconds=None):
    if type(ntoys) is not int or not 50 <= ntoys <= 100000:
        raise ValueError("CLs toy count must be an integer in [50, 100000]")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("CLs toy seed must be an integer in [0, 2^32)")
    if max_fits is not None and (type(max_fits) is not int or max_fits < 0):
        raise ValueError("CLs toy max_fits must be a nonnegative integer or None")
    if max_seconds is not None and (type(max_seconds) not in (int, float) or not math.isfinite(max_seconds)
                                    or max_seconds < 0):
        raise ValueError("CLs toy max_seconds must be a finite nonnegative number or None")


def _grid(asymptotic, grid_factors):
    factors = list(grid_factors)
    if not factors or any(type(f) not in (int, float) or not math.isfinite(f) or f <= 0 for f in factors):
        raise ValueError("toy grid factors must be finite positive numbers")
    roots = []
    for value, status in ((asymptotic["obs_limit"], asymptotic["limit_status"]["observed"]),
                          (asymptotic["exp_limits"][2], asymptotic["limit_status"]["expected"][2])):
        if status == "resolved":
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("resolved asymptotic reference roots must be finite and positive")
            roots.append(value)
    if not roots:
        raise ValueError("toy grid requires at least one resolved observed or median asymptotic root")
    grid = []
    for value in sorted(root * factor for root in roots for factor in factors):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("toy grid mu must be finite and positive")
        if not grid or not math.isclose(value, grid[-1], rel_tol=1e-9, abs_tol=0):
            grid.append(float(value))
    return grid


def _crossing(grid, values, level):
    """First sign change in increasing mu; endpoints retain one-sided status."""
    for index, (mu, value) in enumerate(zip(grid, values)):
        if value == level:
            return mu, "resolved", [mu, mu]
        if index and (values[index - 1] - level) * (value - level) < 0:
            lower = grid[index - 1]
            fraction = (level - values[index - 1]) / (value - values[index - 1])
            root = math.exp(math.log(lower) + fraction * (math.log(mu) - math.log(lower)))
            return min(mu, max(lower, root)), "resolved", [lower, mu]
    if all(value > level for value in values):
        return grid[-1], "above_scan", [grid[-1], None]
    if all(value < level for value in values):
        return grid[0], "below_scan", [None, grid[0]]
    raise ValueError("toy CLs curve has no finite crossing or one-sided bound")


def _mc_error(p_sb, cl_b, ntoys):
    # pyhf returns CLb = 1 - p_b. Both empirical tails have binomial variance.
    if not (0 <= p_sb <= 1 and 0 < cl_b <= 1):
        raise ValueError("toy CLs has invalid tails or an unresolved zero background denominator")
    variance_sb = p_sb * (1 - p_sb) / ntoys
    variance_b = cl_b * (1 - cl_b) / ntoys
    return math.sqrt(variance_sb / cl_b**2 + p_sb**2 * variance_b / cl_b**4)


def _mc_interval(grid, values, errors, level, central):
    lower, lower_status, _ = _crossing(grid, [c - e for c, e in zip(values, errors)], level)
    upper, upper_status, _ = _crossing(grid, [c + e for c, e in zip(values, errors)], level)
    # A shifted crossing outside the sampled range is open, never extrapolated.
    return [None if lower_status == "below_scan" else min(lower, central),
            None if upper_status == "above_scan" else max(upper, central)]


def _toy_point(model, data, mu, ntoys):
    """Toy CLs (observed + five expected) and the tail probabilities at one tested mu."""
    import pyhf
    bounds = [list(bound) for bound in model.config.suggested_bounds()]
    bounds[model.config.poi_index] = [0.0, max(bounds[model.config.poi_index][1], 1.5 * mu, 2.0)]
    # Use the calculator underlying hypotest so expected tail probabilities
    # come from the very same ensembles, without a second toy draw/refit.
    calculator = pyhf.infer.calculators.ToyCalculator(
        data, model, par_bounds=bounds, test_stat="qtilde", ntoys=ntoys, track_progress=False)
    statistic = calculator.teststatistic(mu)
    distributions = calculator.distributions(mu)
    p_sb, cl_b, observed = calculator.pvalues(statistic, *distributions)
    exp_sb, exp_b, expected = calculator.expected_pvalues(*distributions)
    values = [float(observed), *map(float, expected)]
    if len(values) != 6 or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("toy CLs must contain six finite nonnegative values")
    return values, [p_sb, *exp_sb], [cl_b, *exp_b]


def _pilot_seed(seed):
    """A distinct, deterministic stream for the cost pilot; the main ensemble reseeds with ``seed``."""
    return (seed * 2654435761 + 1) % 2**32


def toy_limits(model, data, *, level=0.05, ntoys, seed, asymptotic,
               grid_factors=(0.5, 0.7, 0.85, 1.0, 1.2, 1.5, 2.0), max_fits=None,
               max_seconds=None) -> dict:
    """Sample both hypotheses once per grid point and invert all six CLs curves.

    Two budgets are checked before the main ensemble: the toy-experiment count
    (deterministic) and, when ``max_seconds`` is given, the wall time projected from
    a measured pilot of PILOT_TOYS toys at the central grid point. The pilot draws
    from its own seeded stream, so the main results do not depend on whether it ran.
    A refusal is typed (ToyBudgetExceeded) so the caller records it.
    """
    import time
    import pyhf

    _validate_options(ntoys, seed, max_fits, max_seconds)
    if type(level) not in (int, float) or not math.isfinite(level) or not 0 < level < 1:
        raise ValueError("CLs level must be finite and strictly between zero and one")
    grid_factors = tuple(grid_factors)
    grid = _grid(asymptotic, grid_factors)
    estimated_fits = len(grid) * ntoys * 2
    if max_fits is not None and estimated_fits > max_fits:
        raise ToyBudgetExceeded(estimated_fits, max_fits, max_seconds=max_seconds, bound="fits")

    cls, uncertainty, pilot, estimated_seconds = [], [], None, None
    state = np.random.get_state()
    _, optimizer = pyhf.get_backend()
    guard = type(optimizer)
    escalation = getattr(guard, "escalated", None)
    try:
        if max_seconds is not None:
            toys = min(PILOT_TOYS, ntoys)
            np.random.seed(_pilot_seed(seed))
            started = time.perf_counter()
            _toy_point(model, data, grid[len(grid) // 2], toys)
            elapsed = time.perf_counter() - started
            per_experiment = elapsed / (2 * toys)
            estimated_seconds = per_experiment * estimated_fits
            pilot = {"toys": toys, "mu": grid[len(grid) // 2], "seed": _pilot_seed(seed),
                     "wall_seconds": elapsed, "seconds_per_toy_experiment": per_experiment}
            if estimated_seconds > max_seconds:
                raise ToyBudgetExceeded(estimated_fits, max_fits, estimated_seconds=estimated_seconds,
                                        max_seconds=max_seconds, bound="seconds", pilot=pilot)
        started = time.perf_counter()
        np.random.seed(seed)
        for mu in grid:
            values, sb, b = _toy_point(model, data, mu, ntoys)
            cls.append(values)
            uncertainty.append([_mc_error(float(x), float(y), ntoys) for x, y in zip(sb, b)])
        wall = time.perf_counter() - started
    finally:
        np.random.set_state(state)
        if escalation is not None:
            guard.escalated = escalation

    values, statuses, brackets, intervals = [], [], [], []
    for curve, errors in zip(np.asarray(cls).T, np.asarray(uncertainty).T):
        value, status, bracket = _crossing(grid, curve, level)
        values.append(value)
        statuses.append(status)
        brackets.append(bracket)
        intervals.append(_mc_interval(grid, curve, errors, level, value))
    ratios = {}
    for name, value, reference, status in (
            ("observed", values[0], asymptotic["obs_limit"], asymptotic["limit_status"]["observed"]),
            ("median", values[3], asymptotic["exp_limits"][2], asymptotic["limit_status"]["expected"][2])):
        index = 0 if name == "observed" else 3
        ratios[name] = value / reference if status == statuses[index] == "resolved" else None
    result = {
        "obs_limit": values[0], "exp_limits": values[1:],
        "limit_status": {"observed": statuses[0], "expected": statuses[1:]},
        "limit_brackets": {"observed": brackets[0], "expected": brackets[1:]},
        "limit_mc_interval": {"observed": intervals[0], "expected": intervals[1:]},
        "scan_mu": grid, "scan_cls_obs": [row[0] for row in cls],
        "scan_cls_exp": [row[1:] for row in cls],
        "cls_mc_uncertainty": {"observed": [row[0] for row in uncertainty],
                               "expected": [row[1:] for row in uncertainty]},
        "ntoys": ntoys, "seed": seed, "n_fits": estimated_fits,
        "wall_seconds": wall, "estimated_seconds": estimated_seconds, "pilot": pilot,
        "at_poi_cap": statuses[0] == "above_scan", "median_at_cap": statuses[3] == "above_scan",
        "at_mu_floor": "below_scan" in statuses,
        "band_degenerate": bool(values[5] / max(values[1], 1e-12) < 1.5),
        "agreement_with_asymptotic": ratios,
        "inference": {"method": "toy-based CLs", "test_stat": "qtilde", "level": level,
                      "ntoys": ntoys, "seed": seed,
                      "grid_rule": {"roots": "resolved asymptotic observed and expected median",
                                    "factors": list(grid_factors), "dedup_relative_tolerance": 1e-9},
                      "root_rule": "log-linear interpolation between bracketing toy points",
                      "mc_uncertainty": "first-order independent-binomial tail errors; zero empirical tails have zero binomial error; expected-quantile uncertainty not included",
                      "coverage_validated": False,
                      "scope": "finite-toy calibration of the CLs crossing on the supplied model; MC uncertainty recorded; no acceptance certification"},
    }
    return attach_limits(result, source="pyhf-toys")


def apply(model, data, asymptotic_result, *, requested, ntoys, seed, max_fits, max_seconds=None) -> dict:
    """Update the headline in place, retaining its asymptotic reference and curve.

    A budget refusal (fit count, or wall time projected from the measured pilot)
    keeps the asymptotic headline and records the toy recommendation, never silently.
    """
    policy = calculator_policy(model, data, requested=requested)
    if policy["applied"] == "asymptotic":
        asymptotic_result["calculator"] = {**policy, "toys": None}
        return asymptotic_result
    try:
        toy = toy_limits(model, data, level=asymptotic_result.get("inference", {}).get("level", 0.05),
                         ntoys=ntoys, seed=seed, asymptotic=asymptotic_result, max_fits=max_fits,
                         max_seconds=max_seconds)
    except ToyBudgetExceeded as exc:
        asymptotic_result["calculator"] = {
            **policy, "applied": "asymptotic", "recommended": "toybased",
            "toys": {"status": "not_run", "reason": "budget", "bound": exc.bound,
                     "estimated_fits": exc.estimated_fits, "max_fits": exc.max_fits,
                     "estimated_seconds": exc.estimated_seconds, "max_seconds": exc.max_seconds,
                     "pilot": exc.pilot}}
        return asymptotic_result
    asymptotic_result["asymptotic_reference"] = deepcopy({key: asymptotic_result[key] for key in (
        "obs_limit", "exp_limits", "limit_status", "limit_brackets", "limits",
        "scan_mu", "scan_cls_obs", "scan_cls_exp")})
    for key in ("obs_limit", "exp_limits", "limit_status", "limit_brackets", "limit_mc_interval",
                "at_poi_cap", "median_at_cap", "at_mu_floor", "band_degenerate", "agreement_with_asymptotic"):
        asymptotic_result[key] = toy[key]
    attach_limits(asymptotic_result, result=read_limits(toy))
    asymptotic_result["toy_scan"] = {key: toy[key] for key in (
        "scan_mu", "scan_cls_obs", "scan_cls_exp", "cls_mc_uncertainty")}
    asymptotic_result["calculator"] = {**policy, "toys": {
        "status": "run", "ntoys": ntoys, "seed": seed, "n_fits": toy["n_fits"],
        "wall_seconds": toy["wall_seconds"], "estimated_seconds": toy["estimated_seconds"],
        "pilot": toy["pilot"], "max_fits": max_fits, "max_seconds": max_seconds}}
    asymptotic_result.setdefault("inference", {}).update(
        method="toy-based CLs (asymptotic bracket reference retained)", toys=toy["inference"])
    if "coverage" in asymptotic_result:
        asymptotic_result["coverage"]["scope"] = "finite-toy CLs crossing on supplied likelihood; coverage not validated"
    from ravel.validation import regression_triggers
    asymptotic_result['computed_checks'] = regression_triggers.consume_flags(asymptotic_result)
    asymptotic_result['computed_check_summary'] = regression_triggers.summary(asymptotic_result['computed_checks'])
    return asymptotic_result
