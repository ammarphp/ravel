"""Look-elsewhere corrections for a significance reported over scanned hypotheses.

- ``global_significance(q0, reference_level)``: the upcrossing estimate of the global p-value for a
  one-sided discovery statistic with one degree of freedom:
  ``p_global ~ p_local(u) + N(c0) exp(-(u - c0) / 2)``, where ``u`` is the largest local ``q0`` on
  the scan, ``c0`` a low reference level and ``N(c0)`` the number of upcrossings of ``c0`` along the
  scan. The scan is the ordered sequence of tested hypotheses; its spacing must resolve the
  structure of ``q0``. The estimate is an upper bound that is tight at large ``u``.
- ``sidak(p_local, n)``: ``1 - (1 - p)^n`` for ``n`` declared independent tests.

Both return the local and global p-values and significances. They do not establish that the
scan is fine enough or that ``q0`` is chi-square distributed; the catalogue records those
premises with the result.
"""
from __future__ import annotations

import math


def _scan(values):
    if not isinstance(values, (list, tuple)) or len(values) < 2:
        raise ValueError("a look-elsewhere correction needs the local q0 at two or more scanned hypotheses")
    out = []
    for value in values:
        if type(value) not in (int, float) or not math.isfinite(value) or value < -1e-9:
            raise ValueError("local q0 values must be finite and nonnegative")
        out.append(max(float(value), 0.0))
    return out


def upcrossings(values, level) -> int:
    """Number of upward crossings of ``level`` along the scan (a start above the level is not one)."""
    values = _scan(values)
    return sum(1 for a, b in zip(values, values[1:]) if a <= level < b)


def _local(q0):
    from scipy.stats import norm
    z = math.sqrt(max(q0, 0.0))
    return float(norm.sf(z)), z


def global_significance(values, *, reference_level=0.5) -> dict:
    from scipy.stats import norm
    values = _scan(values)
    if type(reference_level) not in (int, float) or not math.isfinite(reference_level) or reference_level < 0:
        raise ValueError("the reference level must be a finite nonnegative q0")
    u = max(values)
    p_local, z_local = _local(u)
    n = upcrossings(values, reference_level)
    expected = n * math.exp(-(u - reference_level) / 2) if u > reference_level else None
    p_global = None if expected is None else min(1.0, p_local + expected)
    return {"method": "upcrossings", "hypotheses": len(values), "max_local_q0": u,
            "local_p_value": p_local, "local_significance": z_local,
            "reference_level": float(reference_level), "upcrossings": n,
            "expected_upcrossings_at_max": expected, "global_p_value": p_global,
            "global_significance": None if p_global is None else max(0.0, float(norm.isf(p_global))),
            "trials_factor": None if p_global is None or p_local <= 0 else p_global / p_local,
            "premises": ["q0 is asymptotically half chi-square with one degree of freedom at each hypothesis",
                         "the scan spacing resolves the structure of q0"]}


def sidak(p_local, n) -> dict:
    from scipy.stats import norm
    if type(p_local) not in (int, float) or not 0 <= p_local <= 1:
        raise ValueError("p_local must lie in [0, 1]")
    if type(n) is not int or n < 1:
        raise ValueError("the number of independent tests must be a positive integer")
    p_global = -math.expm1(n * math.log1p(-p_local)) if p_local < 1 else 1.0
    return {"method": "sidak", "independent_tests": n, "local_p_value": float(p_local),
            "local_significance": float(norm.isf(p_local)) if 0 < p_local < 1 else None,
            "global_p_value": float(p_global),
            "global_significance": float(norm.isf(p_global)) if 0 < p_global < 1 else None,
            "premises": ["the tested hypotheses are statistically independent"]}
