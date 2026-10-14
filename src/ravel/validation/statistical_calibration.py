"""Bounded exact-law references for a known-background counting experiment.

The ordering is the observed count: CLs(mu;n) = F_(b+mu*s)(n)/F_b(n).
This is not a general profile-likelihood/qtilde calibration or an auxiliary-data
toy construction. Background and signal yields are known, bins are not weighted
observations, and no nuisance, MC or detector uncertainty is manufactured.
"Exact" refers to the Poisson law, not infinite-precision numerical evaluation.

Only the standard library is used. Finite-lattice reports retain each count,
unnormalized probability mass, truncation bounds and numerical allowance.
"""
from __future__ import annotations

import math
import sys


MAX_COUNT = 10_000
MAX_MEAN = 1_000.0
_SCOPE = "count-ordered CLs for one Poisson count with known background and signal yield"


def _finite(value, name, *, positive=False):
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number, not a boolean or string")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return number


def _count(value, name="observed_count"):
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise ValueError(f"{name} must be an integer from 0 through {MAX_COUNT}")
    return value


def _level(value):
    value = _finite(value, "level", positive=True)
    if value >= 1:
        raise ValueError("level must lie strictly between zero and one")
    return value


def _law(signal_strength, signal_yield, background_yield):
    mu = _finite(signal_strength, "signal_strength")
    signal = _finite(signal_yield, "signal_yield", positive=True)
    background = _finite(background_yield, "background_yield")
    increment = mu * signal
    if mu > 0 and increment == 0:
        raise ValueError("nonzero signal increment underflowed in the numerical domain")
    mean = background + increment
    if not math.isfinite(mean) or mean > MAX_MEAN:
        raise ValueError(f"Poisson mean exceeds the bounded numerical domain [0, {MAX_MEAN:g}]")
    return mu, signal, background, increment, mean


def _logadd(first, second):
    if first == -math.inf:
        return second
    if second == -math.inf:
        return first
    upper, lower = max(first, second), min(first, second)
    return upper + math.log1p(math.exp(lower - upper))


def _log_series(maximum, mean):
    """log(sum_(k=0)^n mean**k/k!) for every n, without CDF underflow."""
    if mean == 0:
        return [0.0] * (maximum + 1)
    log_mean = math.log(mean)
    cumulative = 0.0
    result = [cumulative]
    for count in range(1, maximum + 1):
        cumulative = _logadd(cumulative, count * log_mean - math.lgamma(count + 1))
        result.append(cumulative)
    return result


def _log_ratio(increment, signal_series, background_series):
    # Separating -increment avoids cancellation of the two -background terms.
    value = -increment + signal_series - background_series
    if not math.isfinite(value) or value > 1e-8:
        raise ArithmeticError("counting CLs failed its finite probability check")
    return min(value, 0.0)


def known_background_poisson_cls(observed_count, signal_strength, signal_yield,
                                 background_yield):
    """Return count-ordered exact-law CLs; integer observations only.

    Fractional Asimov counts are deliberately outside this reference contract.
    This function makes no claim of equivalence to a profile-likelihood ordering.
    Numerical means are bounded by MAX_MEAN and counts by MAX_COUNT.
    """
    count = _count(observed_count)
    _, _, background, increment, mean = _law(
        signal_strength, signal_yield, background_yield)
    if increment == 0:
        return 1.0
    return math.exp(_log_ratio(increment, _log_series(count, mean)[-1],
                               _log_series(count, background)[-1]))


def known_background_poisson_upper_limit(observed_count, signal_yield,
                                         background_yield, *, level=0.05,
                                         poi_cap=128.0, root_rtol=1e-10):
    """Invert the count-ordered CLs with a cap-aware, bounded endpoint.

    An above_scan value is the tested cap, not a resolved upper limit. Bisection
    uses log CLs, so small CDFs cannot disappear by dividing two underflows.
    """
    count = _count(observed_count)
    level = _level(level)
    cap = _finite(poi_cap, "poi_cap", positive=True)
    tolerance = _finite(root_rtol, "root_rtol", positive=True)
    if not 8 * sys.float_info.epsilon <= tolerance < 0.01:
        raise ValueError("root_rtol must be at least 8*machine epsilon and below 0.01")
    _, signal, background, increment, mean = _law(cap, signal_yield, background_yield)
    background_series = _log_series(count, background)[-1]
    target = math.log(level)

    def log_cls(mu):
        if mu == 0:
            return 0.0
        _, _, _, added, total = _law(mu, signal, background)
        return _log_ratio(added, _log_series(count, total)[-1], background_series)

    cap_log_cls = _log_ratio(increment, _log_series(count, mean)[-1], background_series)
    base = {"schema_version": 1, "method": "exact_count_ordered_poisson_cls",
            "scope": _SCOPE, "level": level, "observed_count": count,
            "signal_yield": signal, "background_yield": background,
            "poi_cap": cap, "cls_at_cap": math.exp(cap_log_cls),
            "physics_validated": False, "general_likelihood_coverage_validated": False}
    if cap_log_cls > target:
        return {**base, "status": "above_scan", "value": cap,
                "bracket": [cap, None], "root_cls_residual": None,
                "iterations": 0, "root_rtol": tolerance}
    if count == 0:
        root = -target / signal
        low = high = root
        iterations = 0
    else:
        low, high = 0.0, cap
        for iterations in range(1, 257):
            middle = low + (high - low) / 2
            if middle == low or middle == high:
                break
            if log_cls(middle) > target:
                low = middle
            else:
                high = middle
            if high - low <= tolerance * high:
                break
        else:
            raise ArithmeticError("Poisson upper-limit bisection exceeded its iteration bound")
        root = low + (high - low) / 2
    actual = math.exp(log_cls(root))
    if high - low > tolerance * high or abs(actual - level) > 1e-8:
        raise ArithmeticError("Poisson upper limit failed the root residual or bracket check")
    return {**base, "status": "resolved", "value": root,
            "bracket": [low, high], "cls_at_root": actual,
            "root_cls_residual": actual - level,
            "iterations": iterations, "root_rtol": tolerance}


def _tail_upper_bound(maximum, mean):
    if mean == 0:
        return 0.0, "zero mean"
    if maximum + 2 <= mean:
        return 1.0, "trivial bound; geometric ratio is not below one"
    first_log_mass = -mean + (maximum + 1) * math.log(mean) - math.lgamma(maximum + 2)
    # Subsequent probabilities have ratio <= mean/(maximum+2). Preserve an
    # upper rounding margin and a nonzero bound even when exp underflows.
    log_bound = first_log_mass - math.log1p(-mean / (maximum + 2))
    bound = min(1.0, math.exp(min(log_bound, 0.0)) * (1 + 1e-10)
                + math.nextafter(0.0, 1.0))
    return bound, "geometric Poisson tail p(K+1)/(1-mean/(K+2))"


def known_background_poisson_coverage(signal_strength, signal_yield,
                                      background_yield, *, level=0.05,
                                      max_count=512, tail_tolerance=1e-10):
    """Enumerate coverage at one fixed truth without random draws or roots.

    All counts from zero through max_count are retained. Rejection uses the
    strict CLs < level convention, so the interval contains its root. No main
    or auxiliary nuisance law, plug-in ensemble, or cap-dependent interval is
    silently substituted. An inadequate lattice is reported as incomplete.
    """
    maximum = _count(max_count, "max_count")
    level = _level(level)
    tail_tolerance = _finite(tail_tolerance, "tail_tolerance", positive=True)
    if tail_tolerance >= 1:
        raise ValueError("tail_tolerance must lie strictly between zero and one")
    mu, signal, background, increment, mean = _law(
        signal_strength, signal_yield, background_yield)
    signal_series, background_series = (_log_series(maximum, value)
                                        for value in (mean, background))
    target, lattice = math.log(level), []
    log_mean = math.log(mean) if mean else None
    for count in range(maximum + 1):
        mass = (math.exp(-mean + count * log_mean - math.lgamma(count + 1))
                if mean else float(count == 0))
        log_cls = (0.0 if increment == 0 else
                   _log_ratio(increment, signal_series[count], background_series[count]))
        lattice.append({"observed_count": count, "probability": mass,
                        "cls": math.exp(log_cls), "excluded": log_cls < target})
    retained = math.fsum(row["probability"] for row in lattice)
    covered = math.fsum(row["probability"] for row in lattice if not row["excluded"])
    rejected = math.fsum(row["probability"] for row in lattice if row["excluded"])
    omitted, tail_method = _tail_upper_bound(maximum, mean)
    roundoff = 64 * sys.float_info.epsilon * (maximum + 1)
    if retained > 1 + roundoff or abs(covered + rejected - retained) > roundoff:
        raise ArithmeticError("finite Poisson lattice failed probability-mass accounting")
    # Incomplete tails can contain covered or rejected outcomes. Do not
    # renormalize retained outcomes or assign omitted mass a favourable label.
    return {"schema_version": 1, "method": "exact_count_ordered_poisson_cls_lattice",
            "scope": _SCOPE, "status": "resolved" if omitted + roundoff <= tail_tolerance
            else "incomplete", "signal_strength": mu, "signal_yield": signal,
            "background_yield": background, "poisson_mean": mean, "level": level,
            "max_count": maximum, "lattice_size": len(lattice),
            "retained_probability": retained,
            "retained_covered_probability": covered,
            "retained_rejected_probability": rejected,
            "omitted_probability_upper_bound": omitted,
            "omitted_tail_method": tail_method, "tail_tolerance": tail_tolerance,
            "numerical_roundoff_allowance": roundoff,
            "coverage_lower_bound": max(0.0, covered - roundoff),
            "coverage_upper_bound": min(1.0, covered + omitted + roundoff),
            "rejection_probability_lower_bound": max(0.0, rejected - roundoff),
            "rejection_probability_upper_bound": min(1.0, rejected + omitted + roundoff),
            "interval_endpoint_convention": "included; reject only if CLs < level",
            "failed_lattice_cells": 0, "lattice": lattice,
            "random_draws": 0, "physics_validated": False,
            "general_likelihood_coverage_validated": False}
