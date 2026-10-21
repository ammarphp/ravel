"""Parameter intervals on a pyhf model: quadratic errors, profile-likelihood intervals and their components.

``intervals(model, data, parameters, level)`` fits every free parameter (iminuit MIGRAD and HESSE),
then for each requested parameter scans the profile ``q(x) = -2 ln L(x, theta_hat(x)) + 2 ln L_max``
on a grid around the best fit and finds the crossings of the chi-square threshold of ``level``
with ``intervals.allowed_regions`` (Brent-refined, re-evaluated at the root; an edge at the scan
or physical boundary is reported as such, never as a crossing).

The statistical component is the same interval with every constrained nuisance parameter fixed at
its best-fit value (free normalisation factors stay free: they are measured by the data). The
systematic component on each side is ``sqrt(total^2 - statistical^2)``. These are the standard
decomposition conventions, stated with the result; they assume the components add in quadrature.

Each row carries the evidence the catalogue's ``parabolic-profile``, ``interval-resolved`` and
``away-from-boundary`` checks read.

Command: ``python -m ravel.physics.inference.profile --workspace W.json
[--patch P.json] [--parameter NAME ...] [--level 0.6827] [--points 31] --out estimation.json``.
The statistics catalogue audits the supplied model; a held outcome exits with code 3.
"""
from __future__ import annotations

import math

import numpy as np

from . import intervals as allowed
from .model_checks import _fit

CENTRAL = 0.682689492137


def _threshold(level):
    from scipy.stats import chi2
    if not 0 < level < 1:
        raise ValueError("the interval level must lie strictly between zero and one")
    return float(chi2.ppf(level, 1))


def _names(model):
    names = []
    for name in model.config.par_order:
        n = model.config.param_set(name).n_parameters
        names += [name] if n == 1 else [f"{name}[{i}]" for i in range(n)]
    return names


def _constrained(model):
    out = []
    for name in model.config.par_order:
        parameter = model.config.param_set(name)
        out += [bool(getattr(parameter, "constrained", False))] * parameter.n_parameters
    return out


def _scan(model, data, index, best, minimum, grid, bounds, fixed_extra, threshold):
    def q(x):
        fixed = {index: float(x), **fixed_extra}
        minuit = _fit(model, data, fixed=fixed, init=best, bounds=bounds)
        return max(float(minuit.fval) - minimum, 0.0)
    values = [q(x) for x in grid]
    domain = (bounds[index][0], bounds[index][1])
    return allowed.allowed_regions(grid, values, threshold, q, domain=domain), values


def _interval_row(region, best_value):
    """The allowed interval that contains the best fit, or None."""
    for row in region.get("intervals") or ():
        low, high = row["low"].get("value"), row["high"].get("value")
        if (low is None or low <= best_value + 1e-12) and (high is None or high >= best_value - 1e-12):
            return row
    return None


def intervals(model, data, *, parameters=None, level=CENTRAL, points=31, span=4.0, stat_only=True) -> list[dict]:
    config = model.config
    names = _names(model)
    threshold = _threshold(level)
    data = np.asarray(data, float)
    best_fit = _fit(model, data)
    if not best_fit.fmin.is_valid:
        raise ValueError("the best fit is not valid; no interval is defined")
    best = np.asarray(best_fit.values, float)
    errors = np.asarray(best_fit.errors, float)
    minimum = float(best_fit.fval)
    bounds = [list(b) for b in config.suggested_bounds()]
    wanted = parameters if parameters is not None else [config.poi_name]
    constrained = _constrained(model)
    out = []
    for name in wanted:
        if name not in names:
            raise ValueError(f"{name!r} is not a parameter of the model")
        index = names.index(name)
        if config.suggested_fixed()[index]:
            raise ValueError(f"{name!r} is fixed in the model")
        sigma = errors[index] if math.isfinite(errors[index]) and errors[index] > 0 else 1.0
        low = max(bounds[index][0], best[index] - span * sigma * math.sqrt(threshold))
        high = min(bounds[index][1], best[index] + span * sigma * math.sqrt(threshold))
        grid = np.linspace(low, high, points)
        region, values = _scan(model, data, index, best, minimum, grid, bounds, {}, threshold)
        row = {"parameter": name, "level": level, "threshold": threshold, "best_fit": float(best[index]),
               "quadratic_half_width": float(errors[index] * math.sqrt(threshold)),
               "best_fit_valid": bool(best_fit.fmin.is_valid and best_fit.accurate),
               "scan": {"grid": [float(x) for x in grid], "q": [float(v) for v in values]},
               "region": region}
        chosen = _interval_row(region, best[index])
        if chosen is None or region["status"] == "empty":
            row.update(status="unresolved", profile_low=None, profile_high=None, at_boundary=False)
        else:
            lo_edge, hi_edge = chosen["low"], chosen["high"]
            resolved = {lo_edge["status"], hi_edge["status"]} <= {"resolved", "domain_boundary"}
            at_boundary = "domain_boundary" in (lo_edge["status"], hi_edge["status"])
            row.update(status="resolved" if resolved and not at_boundary else
                       ("boundary" if at_boundary else "unresolved"),
                       interval=[lo_edge.get("value"), hi_edge.get("value")], at_boundary=at_boundary,
                       profile_low=None if lo_edge.get("value") is None else float(best[index] - lo_edge["value"]),
                       profile_high=None if hi_edge.get("value") is None else float(hi_edge["value"] - best[index]))
        if stat_only:
            fixed = {i: float(best[i]) for i, c in enumerate(constrained) if c and i != index}
            stat_region, _ = _scan(model, data, index, best, minimum, grid, bounds, fixed, threshold)
            stat_row = _interval_row(stat_region, best[index])
            if stat_row is not None and {stat_row["low"]["status"], stat_row["high"]["status"]} <= {"resolved"}:
                stat_low = float(best[index] - stat_row["low"]["value"])
                stat_high = float(stat_row["high"]["value"] - best[index])
                row.update(stat_low=stat_low, stat_high=stat_high, fixed_for_statistical=sorted(
                    names[i] for i in fixed))
                if row.get("profile_low") is not None and row.get("profile_high") is not None:
                    row.update(syst_low=math.sqrt(max(row["profile_low"] ** 2 - stat_low ** 2, 0.0)),
                               syst_high=math.sqrt(max(row["profile_high"] ** 2 - stat_high ** 2, 0.0)))
            else:
                row.update(stat_low=None, stat_high=None,
                           statistical_status="the statistical-only scan did not give a resolved interval")
        out.append(row)
    return out


def evidence(rows) -> dict:
    """Validity-check evidence for interval rows."""
    return {"intervals": [{"parameter": r["parameter"], "status": r["status"], "at_boundary": r.get("at_boundary"),
                           "quadratic_half_width": r["quadratic_half_width"], "profile_low": r.get("profile_low"),
                           "profile_high": r.get("profile_high")} for r in rows]}


def main(argv=None):
    """Fit a supplied workspace and write intervals with their audited statistics evidence."""
    import argparse
    import json
    from pathlib import Path

    import pyhf

    from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS, model_from_likelihood
    from . import model_checks, situations, uncertainty

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--patch")
    parser.add_argument("--parameter", nargs="+", action="extend", dest="parameters")
    parser.add_argument("--level", type=float, default=CENTRAL)
    parser.add_argument("--points", type=int, default=31)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if not math.isfinite(args.level) or not 0 < args.level < 1:
        parser.error("--level must lie strictly between zero and one")
    if args.points < 3:
        parser.error("--points must be at least three")
    if args.patch:
        model, data = model_from_likelihood(args.workspace, args.patch)
    else:
        workspace = pyhf.Workspace(json.loads(Path(args.workspace).read_text()))
        model = workspace.model(modifier_settings=MODIFIER_SETTINGS)
        data = workspace.data(model)
    rows = intervals(model, data, parameters=args.parameters, level=args.level, points=args.points)
    facts = situations.facts_from_model(model, data, origin="supplied", deliverables=["estimation"])
    facts["estimation"] = {"parameters": [r["parameter"] for r in rows],
                           "bounds": dict(zip(_names(model), model.config.suggested_bounds()))}

    def run(situation_id, method_id, previous):
        if method_id in ("quadratic-errors", "profile-likelihood"):
            return evidence(rows)
        if method_id == "signal-injection":
            return {"injection": model_checks.signal_injection(model)}
        if method_id == "profiled-nuisances":
            from .exclusion_statistics import pulls
            found = pulls(model, data)
            return {"pulls": found["pulls"], "pull_fit_valid": found["fit_valid"]}
        # Exclusion toys and validation-region closure cannot validate an interval here.
        return {}

    record = situations.drive(facts, run)
    result = {"schema_version": 1, "kind": "estimation", "parameters": rows,
              "statistics": record, "uncertainty": uncertainty.for_intervals(rows)}
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return 3 if record["validity"]["outcome"] == "held" else 0


if __name__ == "__main__":
    raise SystemExit(main())
