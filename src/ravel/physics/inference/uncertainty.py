"""Uncertainty statements: every reported number with its uncertainty, its components and what it omits.

An ``uncertainty-statement`` accompanies each reported quantity:

- ``quantity`` and ``values``: what is reported;
- ``components``: each with ``kind`` (``statistical``, ``systematic`` or ``method``), ``status``
  (``evaluated`` or ``not-evaluated`` with its reason), what it means and its size (an interval,
  a standard deviation, a band, a relative impact or a ratio);
- ``included``: the uncertainty sources the reported value already folds in;
- ``not_included``: the sources it does not include, each with its reason.

The builders read RAVEL's records: exclusion results (``for_limits``), profile intervals
(``for_intervals``), propagated quantities (``for_propagation``) and efficiencies
(``for_efficiency``). For a limit, the statistical component is the expected band (the spread of
the limit under background-only fluctuations) and the systematic component is the measured
impact of the constrained nuisance parameters on the expected median (``stat_only_expected``: the
same model with every constrained parameter fixed at its nominal value). Method components are the
numerical root precision, the toy Monte Carlo interval, the asymptotic-versus-toy ratio, the
builder representation difference, the correlation bracket and the closure against published
benchmark limits, when those apply.

``statement_errors`` validates a statement and ``document_errors`` checks that a result document
states an uncertainty for every quantity it reports. A statement says what is known; it never
fills in an absent component.
"""
from __future__ import annotations

from copy import deepcopy
import math

SCHEMA_VERSION = 1
KIND = "uncertainty-statement"
COMPONENT_KINDS = ("statistical", "systematic", "method")
STATUSES = ("evaluated", "not-evaluated")
BREAKDOWN_PARAMETER_LIMIT = 60


def _finite(value):
    return type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value)


def component(name, kind, *, status="evaluated", meaning, reason=None, **size):
    if kind not in COMPONENT_KINDS:
        raise ValueError(f"component kind must be one of {COMPONENT_KINDS}")
    if status not in STATUSES:
        raise ValueError(f"component status must be one of {STATUSES}")
    if status == "not-evaluated" and not (isinstance(reason, str) and reason.strip()):
        raise ValueError(f"component {name}: a component that is not evaluated needs its reason")
    row = {"name": name, "kind": kind, "status": status, "meaning": meaning, **deepcopy(size)}
    if reason:
        row["reason"] = reason
    return row


def statement(quantity, values, components, included, not_included, *, notes=()) -> dict:
    document = {"schema_version": SCHEMA_VERSION, "kind": KIND, "quantity": quantity, "values": deepcopy(values),
                "components": list(components), "included": list(included),
                "not_included": [dict(row) for row in not_included], "notes": list(notes)}
    errors = statement_errors(document)
    if errors:
        raise ValueError("invalid uncertainty statement: " + "; ".join(errors))
    return document


def statement_errors(document) -> list[str]:
    if not isinstance(document, dict) or document.get("kind") != KIND or document.get("schema_version") != SCHEMA_VERSION:
        return [f"an uncertainty statement must be kind {KIND!r} schema_version {SCHEMA_VERSION}"]
    errors = []
    if not (isinstance(document.get("quantity"), str) and document["quantity"].strip()):
        errors.append("the statement names no quantity")
    if not isinstance(document.get("values"), dict) or not document["values"]:
        errors.append("the statement reports no values")
    components = document.get("components")
    if not isinstance(components, list) or not components:
        errors.append("the statement has no components")
    else:
        kinds = set()
        for row in components:
            if not (isinstance(row, dict) and row.get("kind") in COMPONENT_KINDS and row.get("status") in STATUSES
                    and isinstance(row.get("name"), str) and isinstance(row.get("meaning"), str)):
                errors.append("every component needs a name, a kind, a status and its meaning")
                continue
            if row["status"] == "not-evaluated" and not (isinstance(row.get("reason"), str) and row["reason"].strip()):
                errors.append(f"component {row['name']} is not evaluated and gives no reason")
            kinds.add(row["kind"])
        missing = [k for k in COMPONENT_KINDS if k not in kinds]
        if missing:
            errors.append("the statement says nothing about its " + ", ".join(missing) + " component(s)")
    if not isinstance(document.get("included"), list):
        errors.append("the statement lists no included sources")
    not_included = document.get("not_included")
    if not isinstance(not_included, list) or not all(
            isinstance(r, dict) and isinstance(r.get("component"), str) and isinstance(r.get("reason"), str)
            for r in not_included):
        errors.append("not_included lists each omitted component with its reason")
    return errors


# --------------------------------------------------------------------------- limits

def model_sources(model) -> dict:
    """Constrained parameters of a pyhf model grouped by what they describe."""
    groups = {"systematic": [], "mc_statistics": [], "free": []}
    types = {}
    for channel in model.spec.get("channels", []):
        for sample in channel.get("samples", []):
            for modifier in sample.get("modifiers", []):
                types.setdefault(modifier["name"], set()).add(modifier["type"])
    poi = model.config.poi_name
    for name in model.config.par_order:
        if name == poi:
            continue
        kinds = types.get(name, set())
        parameter = model.config.param_set(name)
        if kinds & {"staterror", "shapesys"}:
            groups["mc_statistics"].append(name)
        elif getattr(parameter, "constrained", False):
            groups["systematic"].append(name)
        else:
            groups["free"].append(name)
    return groups


def signal_modifiers(model) -> list[str]:
    """Modifier types carried by samples that contain the parameter of interest."""
    poi = model.config.poi_name
    found = set()
    for channel in model.spec.get("channels", []):
        for sample in channel.get("samples", []):
            names = {m["name"] for m in sample.get("modifiers", [])}
            if poi in names:
                found |= {m["type"] for m in sample.get("modifiers", []) if m["name"] != poi}
    return sorted(found)


def stat_only_model(model):
    """The same model with every constrained parameter fixed at its nominal value."""
    import pyhf
    from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS
    config = model.config
    init = list(config.suggested_init())
    overrides = {}
    for name in config.par_order:
        parameter = config.param_set(name)
        if name == config.poi_name or not getattr(parameter, "constrained", False):
            continue
        piece = init[config.par_slice(name)]
        overrides[name] = {"name": name, "fixed": True, "inits": [float(x) for x in piece]}
    spec = deepcopy(model.spec)
    merged = {row["name"]: dict(row) for row in spec.get("parameters", []) if isinstance(row, dict)}
    for name, row in overrides.items():
        merged[name] = {**merged.get(name, {}), **row}
    spec["parameters"] = list(merged.values())
    return pyhf.Model(spec, poi_name=config.poi_name, modifier_settings=MODIFIER_SETTINGS, validate=True), \
        sorted(overrides)


def stat_only_expected(model, data, compute) -> dict:
    """Expected limits with every constrained parameter fixed: the statistical-only reference."""
    fixed_model, fixed = stat_only_model(model)
    if not fixed:
        return {"status": "not-evaluated", "reason": "the model has no constrained nuisance parameter"}
    result = compute(fixed_model, data)
    return {"status": "evaluated", "fixed_parameters": fixed, "expected": [float(x) for x in result["exp_limits"]],
            "expected_status": list(result["limit_status"]["expected"]),
            "observed": float(result["obs_limit"]), "observed_status": result["limit_status"]["observed"]}


def _limit_values(res):
    from ravel.limits import read_limits
    limits = read_limits(res)
    values = {"observed": limits.observed.value, "observed_status": limits.observed.status}
    for label, curve in zip(("-2sigma", "-1sigma", "median", "+1sigma", "+2sigma"), limits.expected):
        values[f"expected_{label}"] = curve.value
        values[f"expected_{label}_status"] = curve.status
    return values


def for_limits(res, *, sources=None, signal_types=None, stat_only=None, not_included=(), quantity=None) -> dict:
    """The uncertainty statement of an exclusion result (``pyhf_exclude`` or the simplified engine)."""
    values = _limit_values(res)
    components = [component(
        "expected-band", "statistical", meaning="spread of the expected limit under background-only fluctuations "
                                                 "(the -2..+2 sigma expected limits)",
        band=[values[f"expected_{k}"] for k in ("-2sigma", "-1sigma", "median", "+1sigma", "+2sigma")])]
    if values["observed"] is not None and values["expected_median"]:
        components.append(component(
            "observed-versus-expected", "statistical", meaning="the observed limit relative to the expected median; "
                                                                "a ratio away from one reflects the observed counts",
            ratio=values["observed"] / values["expected_median"]))
    if stat_only and stat_only.get("status") == "evaluated":
        median, fixed_median = values["expected_median"], stat_only["expected"][2]
        components.append(component(
            "systematic-impact", "systematic",
            meaning="impact of the constrained nuisance parameters on the expected median: the same model with "
                    "them fixed at nominal gives the statistical-only expected median",
            stat_only_expected_median=fixed_median,
            relative_impact=(median - fixed_median) / median if median else None,
            fixed_parameters=stat_only["fixed_parameters"]))
    else:
        reason = (stat_only or {}).get("reason") or "the statistical-only reference was not computed"
        components.append(component("systematic-impact", "systematic", status="not-evaluated",
                                    meaning="impact of the constrained nuisance parameters on the expected median",
                                    reason=reason))
    inference = res.get("inference") or {}
    components.append(component("root-precision", "method", meaning="relative tolerance of the CLs root finding",
                                relative_tolerance=inference.get("root_rtol", inference.get("root_atol"))))
    calculator = res.get("calculator") or {}
    toys = calculator.get("toys")
    if isinstance(toys, dict) and toys.get("status") == "run":
        components.append(component("toy-monte-carlo", "method",
                                    meaning="Monte Carlo interval of the toy CLs crossings (finite ensemble)",
                                    interval=deepcopy(res.get("limit_mc_interval")), toys=toys.get("ntoys")))
        reference = res.get("asymptotic_reference") or {}
        if _finite(reference.get("obs_limit")) and _finite(res.get("obs_limit")) and reference["obs_limit"] > 0:
            components.append(component("asymptotic-versus-toys", "method",
                                        meaning="toy-calibrated over asymptotic observed limit",
                                        ratio=res["obs_limit"] / reference["obs_limit"]))
    elif calculator.get("triggers"):
        components.append(component("toy-monte-carlo", "method", status="not-evaluated",
                                    meaning="toy calibration of the CLs crossings in a small-count regime",
                                    reason=(toys or {}).get("reason") or calculator.get("reason") or "toys not run"))
    construction = res.get("construction") or {}
    parity = (construction.get("parity") or {})
    if parity.get("cls_at_unit_signal_on_background_asimov"):
        components.append(component("builder-representation", "method",
                                    meaning="CLs at unit signal from the two builders' shape representations",
                                    relative_difference=parity["cls_at_unit_signal_on_background_asimov"].get(
                                        "relative_difference")))
    closure = res.get("reference_closure")
    if isinstance(closure, dict) and closure.get("available") is False:
        components.append(component("reference-closure", "method", status="not-evaluated",
                                    meaning="agreement of this model with the analysis's published limits at "
                                            "benchmark points",
                                    reason=closure.get("reason") or "no published reference limits"))
    elif isinstance(closure, dict) and closure.get("points"):
        differences = [abs(value) for row in closure["points"] if isinstance(row, dict)
                       for value in (row.get("relative_difference") or {}).values() if _finite(value)]
        components.append(component("reference-closure", "method",
                                    meaning="largest relative difference between the published benchmark limits "
                                            "and this model's limits for the same yields",
                                    worst_relative_difference=max(differences) if differences else None,
                                    benchmarks=len(closure["points"]), source=closure.get("source")))
    bracket = res.get("correlation_bracket")
    if isinstance(bracket, dict):
        components.append(component("correlation-bracket", "method",
                                    meaning="expected median over fully correlated and independent per-region "
                                            "assignments; endpoint sensitivity with the weakest evaluated variant",
                                    domain=deepcopy(bracket.get("domain")),
                                    variants=deepcopy(bracket.get("variants")), reported=bracket.get("reported_variant")))
    included = ["Poisson fluctuations of the observed counts"]
    sources = sources or {}
    if sources.get("systematic"):
        included.append(f"{len(sources['systematic'])} constrained systematic parameter(s): "
                        + ", ".join(sources["systematic"][:20]) + (" ..." if len(sources["systematic"]) > 20 else ""))
    if sources.get("mc_statistics"):
        included.append("MC statistical uncertainty of the predictions (" + ", ".join(sources["mc_statistics"][:10])
                        + ")")
    if sources.get("free"):
        included.append("free normalisation parameters measured by the data: " + ", ".join(sources["free"][:20]))
    omitted = [dict(row) for row in not_included]
    if signal_types is not None and not set(signal_types) & {"normsys", "histosys", "lumi", "staterror", "shapesys"}:
        omitted.append({"component": "signal uncertainties",
                        "reason": "the signal enters with its strength only: no theory, detector or MC-statistical "
                                  "nuisance parameter acts on it"})
    if signal_types is not None and not set(signal_types) & {"staterror", "shapesys"} and \
            not any(r["component"] == "signal uncertainties" for r in omitted):
        omitted.append({"component": "signal MC statistical uncertainty",
                        "reason": "no MC-statistics term acts on the signal"})
    omitted.append({"component": "reference cross-section uncertainty",
                    "reason": "a signal-strength limit is quoted relative to the nominal signal; the reference "
                              "cross-section's own uncertainty is not part of it"})
    return statement(quantity or "95% CLs upper limit on the signal strength", values, components, included, omitted)


def scope_omissions(model_scope) -> list[dict]:
    """``not_included`` rows from an exclusion result's ``model_scope`` statements."""
    out = []
    for key, text in sorted((model_scope or {}).items()):
        if not isinstance(text, str):
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in ("not included", "not represented", "assumed", "unavailable",
                                                "not published", "absent")):
            out.append({"component": key.replace("_", " "), "reason": text})
    return out


# --------------------------------------------------------------------------- intervals, propagation, efficiency

def for_intervals(rows) -> list[dict]:
    out = []
    for row in rows:
        values = {"best_fit": row["best_fit"], "interval": row.get("interval"), "level": row["level"],
                  "total_half_widths": [row.get("profile_low"), row.get("profile_high")]}
        components = []
        if row.get("stat_low") is not None:
            components.append(component("statistical", "statistical",
                                        meaning="half-widths with every constrained nuisance parameter fixed at its "
                                                "best-fit value", low=row["stat_low"], high=row["stat_high"]))
        else:
            components.append(component("statistical", "statistical", status="not-evaluated",
                                        meaning="half-widths with constrained nuisance parameters fixed",
                                        reason=row.get("statistical_status") or "the statistical-only scan was not run"))
        if row.get("syst_low") is not None:
            components.append(component("systematic", "systematic",
                                        meaning="quadrature difference of the total and statistical half-widths",
                                        low=row["syst_low"], high=row["syst_high"]))
        else:
            components.append(component("systematic", "systematic", status="not-evaluated",
                                        meaning="quadrature difference of the total and statistical half-widths",
                                        reason="the total or the statistical interval is not resolved"))
        components.append(component("quadratic-versus-profile", "method",
                                    meaning="quadratic (HESSE) half-width against the profile half-widths",
                                    quadratic_half_width=row["quadratic_half_width"],
                                    profile=[row.get("profile_low"), row.get("profile_high")]))
        out.append(statement(f"{row['parameter']} at {row['level']:.3g} confidence", values, components,
                             ["Poisson fluctuations of the observed counts",
                              "every free and constrained parameter profiled"],
                             [{"component": "coverage", "reason": "the chi-square threshold of the profile is "
                                                                  "assumed; coverage is not evaluated by toys"}]))
    return out


def for_propagation(result) -> dict:
    """The statement of a propagated quantity; statistical and systematic shares need declared input kinds."""
    linear = result["linear"]
    kinds = {row["name"]: row.get("kind", "total") for row in result["inputs"]}
    total = sum(linear["variance_contributions"].values()) + linear["correlation_contribution"]
    shares = {name: (value / total if total > 0 else None) for name, value in linear["variance_contributions"].items()}
    values = {"value": result["value"], "interval": result["interval"], "method": result["method"],
              "first_order_variance_shares": shares,
              "correlation_variance": linear["correlation_contribution"]}
    components = []
    for kind in ("statistical", "systematic"):
        names = [n for n, k in kinds.items() if k == kind]
        if names and all(k in ("statistical", "systematic") for k in kinds.values()):
            components.append(component(kind, kind, meaning=f"first-order variance share of the {kind} inputs",
                                        inputs=names, variance_share=sum(shares[n] or 0.0 for n in names)))
        else:
            components.append(component(kind, kind, status="not-evaluated",
                                        meaning=f"{kind} share of the propagated uncertainty",
                                        reason="the inputs' errors are not all declared statistical or systematic, so "
                                               "the shares cannot be separated"))
    lin = result["linearity"]
    components.append(component("linear-versus-sampled", "method",
                                meaning="relative difference of the linear and sampled spreads",
                                relative_difference=lin["relative_difference"],
                                mean_shift_in_sigma=lin["mean_shift_in_sigma"]))
    if "correlation_bracket" in result:
        components.append(component("correlation-bracket", "method",
                                    meaning="half-widths over the stated range of each unknown correlation",
                                    variants=result["correlation_bracket"]["variants"],
                                    reported=result["correlation_bracket"]["reported_variant"]))
    omitted = []
    if linear["symmetrised"] and result["method"] == "linear":
        omitted.append({"component": "error asymmetry", "reason": "asymmetric errors were symmetrised for linear "
                                                                  "propagation: " + ", ".join(linear["symmetrised"])})
    return statement(result["name"], values, components,
                     ["the declared errors of every input", "the declared input correlations"], omitted)


def for_efficiency(result, *, name) -> dict:
    components = [component("binomial", "statistical", meaning=f"{result['method']} interval at "
                                                                f"{result['confidence']:.3g} confidence",
                            interval=result["interval"]),
                  component("systematic", "systematic", status="not-evaluated",
                            meaning="systematic uncertainty of the selection efficiency",
                            reason="an efficiency from counts carries only its statistical uncertainty; detector and "
                                   "modelling uncertainties enter separately"),
                  component("interval-construction", "method", meaning="the interval construction used",
                            construction=result["method"])]
    omitted = [{"component": "selection systematics", "reason": "not part of a counting efficiency"}]
    if result.get("negative_weight_sum"):
        omitted.append({"component": "exact binomial treatment", "reason": "negative weights"})
    return statement(name, {"efficiency": result["efficiency"], "interval": result["interval"]}, components,
                     ["binomial (or weighted) statistical fluctuations of the selected entries"], omitted)


# --------------------------------------------------------------------------- documents

def document_errors(document, *, require=("limits",)) -> list[str]:
    """A result document that reports limits (or other listed quantities) must state their uncertainty."""
    if not isinstance(document, dict):
        return ["the result document is not an object"]
    reports = any(key in document for key in require) or any(
        key in document for key in ("obs_limit", "exp_limits"))
    if not reports:
        return []
    found = document.get("uncertainty")
    if found is None:
        return ["the result reports limits but states no uncertainty (an uncertainty-statement under 'uncertainty')"]
    errors = statement_errors(found)
    if errors:
        return errors
    if any(key in document for key in ("limits", "obs_limit", "exp_limits")):
        try:
            expected = _limit_values(document)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            return [f"the reported limits are invalid: {exc}"]
        values = found["values"]
        for key, value in expected.items():
            actual = values.get(key)
            if (key not in values or actual != value
                    or (type(value) in (int, float) and not _finite(actual))):
                errors.append(f"uncertainty.values.{key} disagrees with the reported limit: {actual!r} versus {value!r}")
    return errors
