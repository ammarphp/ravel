"""Efficiency and acceptance intervals.

- ``interval(passed, total, method)``: ``normal`` (the binomial normal approximation, valid only
  away from 0 and 1), ``wilson`` (score interval) or ``clopper-pearson`` (exact and conservative),
  at a central confidence (default 68.3%), from ``scipy.stats``;
- ``weighted(...)``: an efficiency of weighted entries, ``sum_pass w / sum_all w``, with the
  variance ``(S2_pass (1 - eps)^2 + S2_fail eps^2) / W^2`` from the sums of squared weights of
  passing and failing entries, and the effective number of entries ``W^2 / S2``. Negative weights
  are reported, not removed.

These are the providers the statistics catalogue names for the efficiency-acceptance situation;
an efficiency that enters a likelihood as a signal uncertainty does so through the systematics
registry.
"""
from __future__ import annotations

import math

CENTRAL = 0.682689492137
METHODS = ("normal", "wilson", "clopper-pearson")


def _counts(passed, total):
    for label, value in (("passed", passed), ("total", total)):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{label} must be a finite nonnegative count")
    if total <= 0 or passed > total:
        raise ValueError("an efficiency needs 0 <= passed <= total and total > 0")
    return float(passed), float(total)


def interval(passed, total, *, method="clopper-pearson", confidence=CENTRAL) -> dict:
    from scipy.stats import beta, norm
    passed, total = _counts(passed, total)
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    if not 0 < confidence < 1:
        raise ValueError("confidence must lie strictly between zero and one")
    eps = passed / total
    alpha = 1 - confidence
    z = float(norm.isf(alpha / 2))
    if method == "normal":
        sigma = math.sqrt(eps * (1 - eps) / total)
        low, high = eps - z * sigma, eps + z * sigma
    elif method == "wilson":
        denominator = 1 + z * z / total
        centre = (eps + z * z / (2 * total)) / denominator
        half = z * math.sqrt(eps * (1 - eps) / total + z * z / (4 * total * total)) / denominator
        low, high = centre - half, centre + half
    else:
        low = 0.0 if passed == 0 else float(beta.ppf(alpha / 2, passed, total - passed + 1))
        high = 1.0 if passed == total else float(beta.ppf(1 - alpha / 2, passed + 1, total - passed))
    return {"method": method, "efficiency": eps, "interval": [max(low, 0.0) if method != "normal" else low,
                                                              min(high, 1.0) if method != "normal" else high],
            "confidence": confidence, "passed": passed, "total": total,
            "outside_unit_interval": bool(low < 0 or high > 1),
            "normal_approximation_valid": bool(total * eps >= 5 and total * (1 - eps) >= 5)}


def weighted(sumw_pass, sumw2_pass, sumw_fail, sumw2_fail, *, confidence=CENTRAL) -> dict:
    from scipy.stats import norm
    for label, value in (("sumw_pass", sumw_pass), ("sumw2_pass", sumw2_pass), ("sumw_fail", sumw_fail),
                         ("sumw2_fail", sumw2_fail)):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{label} must be finite")
    if sumw2_pass < 0 or sumw2_fail < 0:
        raise ValueError("sums of squared weights are nonnegative")
    total = sumw_pass + sumw_fail
    if total <= 0:
        raise ValueError("the total weight must be positive")
    eps = sumw_pass / total
    variance = (sumw2_pass * (1 - eps) ** 2 + sumw2_fail * eps ** 2) / total ** 2
    sigma = math.sqrt(max(variance, 0.0))
    z = float(norm.isf((1 - confidence) / 2))
    s2 = sumw2_pass + sumw2_fail
    return {"method": "weighted", "efficiency": eps, "sigma": sigma, "interval": [eps - z * sigma, eps + z * sigma],
            "confidence": confidence, "effective_entries": total * total / s2 if s2 > 0 else None,
            "negative_weight_sum": bool(sumw_pass < 0 or sumw_fail < 0), "outside_unit_interval": bool(eps < 0 or eps > 1)}


def facts_entry(name, *, passed=None, total=None, weighted_sums=None, negative_weights=False) -> dict:
    """The ``efficiencies`` row of statistics facts."""
    row = {"name": name, "weighted": weighted_sums is not None, "negative_weights": bool(negative_weights)}
    if passed is not None:
        row.update(passed=passed, total=total)
    if weighted_sums is not None:
        row["sums"] = dict(weighted_sums)
    return row
