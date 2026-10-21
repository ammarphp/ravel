"""Error propagation through a derived quantity: linear, sampled, and over unknown correlations.

A derived quantity is a declared expression (the safe formula language of ``formula``) of inputs
that each carry a central value and an error, symmetric or asymmetric (``error_up``,
``error_down``, both positive). Their correlation is a supplied matrix, declared independent, or
unknown for named pairs.

- ``linear``: the first-order variance ``J C J^T`` with a central-difference Jacobian at the central
  values. Asymmetric errors are symmetrised (their mean) and that is recorded.
- ``sampled``: inputs drawn through a Gaussian copula with the declared correlation; an
  asymmetric input is the split normal ``x = value + error_up * z`` for ``z > 0`` and
  ``value + error_down * z`` otherwise. The central 68.3% interval of the sampled quantity and its
  median are reported, with the sampling precision of the spread.
- ``bracket``: each pair with an unknown correlation is evaluated at the ends of its stated range
  and at zero (every corner, at most 64 variants); the widest interval is reported and the
  variants are kept.

Every result carries the evidence the statistics catalogue's checks read: the linear-versus-
sampled comparison, the sampling precision and the correlation bracket. Nothing here invents a
correlation: an unknown one is bracketed, never set to zero silently.
"""
from __future__ import annotations

from copy import deepcopy
import itertools
import math

import numpy as np

from .formula import Expression

CENTRAL = 0.682689492137
MAX_VARIANTS = 64
METHODS = ("linear", "sampled", "bracket")


def _inputs(inputs):
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("a derived quantity needs a nonempty list of inputs")
    names, rows = [], []
    for row in inputs:
        if not isinstance(row, dict) or not {"name", "value"} <= set(row):
            raise ValueError("every input needs a name and a value")
        name = row["name"]
        if not isinstance(name, str) or name in names:
            raise ValueError("input names must be distinct strings")
        up = row.get("error_up", row.get("error"))
        down = row.get("error_down", row.get("error"))
        for label, value in (("value", row["value"]), ("error_up", up), ("error_down", down)):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"input {name}: {label} must be a finite number")
        if up < 0 or down < 0:
            raise ValueError(f"input {name}: errors are positive magnitudes")
        kind = row.get("kind", "total")
        if kind not in ("statistical", "systematic", "total"):
            raise ValueError(f"input {name}: kind must be statistical, systematic or total")
        names.append(name)
        rows.append({"name": name, "value": float(row["value"]), "error_up": float(up), "error_down": float(down),
                     "kind": kind})
    return names, rows


def _correlation(matrix, n, unknown, names):
    if matrix is None:
        corr = np.eye(n)
    else:
        corr = np.asarray(matrix, float)
        if corr.shape != (n, n) or not np.all(np.isfinite(corr)):
            raise ValueError(f"the correlation must be a finite {n} by {n} matrix")
        if not np.allclose(corr, corr.T, rtol=0, atol=1e-12) or not np.allclose(np.diag(corr), 1, atol=1e-12) \
                or np.any(np.abs(corr) > 1 + 1e-12):
            raise ValueError("the correlation must be symmetric with unit diagonal and entries in [-1, 1]")
    pairs = []
    for pair in unknown or ():
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2 and all(p in names for p in pair)
                and pair[0] != pair[1]):
            raise ValueError("an unknown correlation names two distinct inputs")
        pairs.append((names.index(pair[0]), names.index(pair[1])))
    return corr, pairs


def _positive_definite(corr):
    try:
        np.linalg.cholesky(corr)
        return True
    except np.linalg.LinAlgError:
        # Perfect (anti)correlation is a valid, singular Gaussian at a bracket endpoint.
        return bool(np.linalg.eigvalsh(corr).min() >= -1e-12)


def _jacobian(expression, names, values):
    grad = []
    for i, name in enumerate(names):
        step = 1e-6 * max(1.0, abs(values[i]))
        up, down = list(values), list(values)
        up[i] += step
        down[i] -= step
        f_up = float(expression.evaluate(dict(zip(names, up))))
        f_down = float(expression.evaluate(dict(zip(names, down))))
        grad.append((f_up - f_down) / (2 * step))
    return np.asarray(grad)


def _linear(expression, names, rows, corr):
    values = [r["value"] for r in rows]
    sigma = np.asarray([(r["error_up"] + r["error_down"]) / 2 for r in rows])
    jac = _jacobian(expression, names, values)
    cov = corr * np.outer(sigma, sigma)
    variance = float(jac @ cov @ jac)
    central = float(expression.evaluate(dict(zip(names, values))))
    contributions = {name: float((jac[i] * sigma[i]) ** 2) for i, name in enumerate(names)}
    cross = variance - sum(contributions.values())
    return {"value": central, "sigma": math.sqrt(max(variance, 0.0)), "jacobian": dict(zip(names, map(float, jac))),
            "variance_contributions": contributions, "correlation_contribution": float(cross),
            "symmetrised": [r["name"] for r in rows
                            if not math.isclose(r["error_up"], r["error_down"], rel_tol=1e-9, abs_tol=1e-300)]}


def _sampled(expression, names, rows, corr, samples, seed):
    if not _positive_definite(corr):
        raise ValueError("the correlation matrix is not positive semidefinite")
    rng = np.random.default_rng(seed)
    try:
        factor = np.linalg.cholesky(corr)
    except np.linalg.LinAlgError:
        eigenvalues, eigenvectors = np.linalg.eigh(corr)
        factor = eigenvectors * np.sqrt(np.clip(eigenvalues, 0.0, None))
    z = rng.standard_normal((samples, len(names))) @ factor.T
    scope = {}
    for i, row in enumerate(rows):
        zi = z[:, i]
        scope[row["name"]] = row["value"] + np.where(zi > 0, row["error_up"], row["error_down"]) * zi
    values = np.asarray(expression.evaluate(scope), float)
    finite = np.isfinite(values)
    if finite.mean() < 0.999:
        raise ValueError(f"{(~finite).sum()} of {samples} samples give a nonfinite quantity; the declared "
                         "inputs reach the expression's singularity")
    values = values[finite]
    lo, median, hi = np.quantile(values, [(1 - CENTRAL) / 2, 0.5, (1 + CENTRAL) / 2])
    std = float(np.std(values, ddof=1))
    return {"median": float(median), "interval": [float(lo), float(hi)], "mean": float(np.mean(values)),
            "std": std, "samples": int(values.size), "seed": seed,
            "relative_precision": 1 / math.sqrt(2 * (values.size - 1))}


def propagate(definition, *, method="sampled", samples=200000, seed=1) -> dict:
    """Propagate one declared quantity ``{name, expression, inputs, correlation?, unknown_correlations?,
    correlation_range?}``; returns the result with the evidence its validity checks read."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    if not isinstance(definition, dict) or not {"name", "expression", "inputs"} <= set(definition):
        raise ValueError("a derived quantity needs a name, an expression and inputs")
    names, rows = _inputs(definition["inputs"])
    expression = Expression(definition["expression"], set(names))
    corr, unknown = _correlation(definition.get("correlation"), len(names), definition.get("unknown_correlations"),
                                 names)
    if type(samples) is not int or samples < 1000:
        raise ValueError("sampled propagation needs at least 1000 samples")
    linear = _linear(expression, names, rows, corr)
    out = {"name": definition["name"], "expression": definition["expression"], "method": method,
           "inputs": deepcopy(rows), "linear": linear}
    if unknown and method != "bracket":
        raise ValueError("unknown correlations are bracketed (method bracket); they are never set silently")
    if method == "linear":
        sampled = _sampled(expression, names, rows, corr, samples, seed)
        out.update(value=linear["value"], interval=[linear["value"] - linear["sigma"], linear["value"] + linear["sigma"]],
                   sampled_reference=sampled)
    elif method == "sampled":
        sampled = _sampled(expression, names, rows, corr, samples, seed)
        out.update(value=sampled["median"], interval=sampled["interval"], sampled=sampled)
    else:
        low, high = definition.get("correlation_range", [-1.0, 1.0])
        if not (type(low) in (int, float) and type(high) in (int, float) and -1 <= low <= 0 <= high <= 1):
            raise ValueError("a correlation range must contain zero and lie within [-1, 1]")
        if 3 ** len(unknown) > MAX_VARIANTS:
            raise ValueError(f"too many unknown correlations to bracket (at most {MAX_VARIANTS} variants)")
        variants, details = {}, {}
        for corner in itertools.product((low, 0.0, high), repeat=len(unknown)):
            trial = corr.copy()
            for (i, j), rho in zip(unknown, corner):
                trial[i, j] = trial[j, i] = rho
            key = ",".join(f"{names[i]}~{names[j]}={rho:g}" for (i, j), rho in zip(unknown, corner)) or "declared"
            if not _positive_definite(trial):
                details[key] = {"status": "not-positive-definite"}
                continue
            sampled = _sampled(expression, names, rows, trial, samples, seed)
            details[key] = {"status": "evaluated", **sampled}
            variants[key] = (sampled["interval"][1] - sampled["interval"][0]) / 2
        if not variants:
            raise ValueError("no correlation variant in the stated range is positive definite")
        widest = max(variants, key=variants.get)
        chosen = details[widest]
        out.update(value=chosen["median"], interval=chosen["interval"], sampled=chosen,
                   correlation_bracket={"pairs": [[names[i], names[j]] for i, j in unknown],
                                        "range": [low, high], "variants": variants, "rule": "max",
                                        "reported": variants[widest], "reported_variant": widest,
                                        "details": details})
    sampled = out.get("sampled") or out.get("sampled_reference")
    shift = (sampled["mean"] - linear["value"]) / sampled["std"] if sampled["std"] > 0 else 0.0
    out["linearity"] = {"name": definition["name"], "linear_sigma": linear["sigma"], "sampled_std": sampled["std"],
                        "relative_difference": abs(linear["sigma"] - sampled["std"]) / sampled["std"]
                        if sampled["std"] > 0 else 0.0,
                        "mean_shift_in_sigma": float(shift)}
    out["sampling"] = {"name": definition["name"], "samples": sampled["samples"],
                       "relative_precision": sampled["relative_precision"]}
    return out


def facts_entry(definition) -> dict:
    """The ``derived`` row of statistics facts for one declared quantity."""
    names, rows = _inputs(definition["inputs"])
    correlation = "unknown" if definition.get("unknown_correlations") else \
        "supplied" if definition.get("correlation") is not None else "independent"
    return {"name": definition["name"], "inputs": rows, "correlation": correlation}


def evidence(results) -> dict:
    """Validity-check evidence for a list of propagation results."""
    out = {"linearity": [r["linearity"] for r in results], "sampling": [r["sampling"] for r in results]}
    brackets = [r["correlation_bracket"] for r in results if "correlation_bracket" in r]
    if brackets:
        # the check reads one bracket; a quantity-wise list keeps every one
        out["correlation_bracket"] = brackets[0] if len(brackets) == 1 else {
            "variants": {f"{r['name']}:{k}": v for r in results if "correlation_bracket" in r
                         for k, v in r["correlation_bracket"]["variants"].items()},
            "rule": "max", "reported": max(b["reported"] for b in brackets)}
    return out
