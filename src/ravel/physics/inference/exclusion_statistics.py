"""The statistics record and the uncertainty statement of an exclusion result.

``attach`` is called by ``pyhf_exclude`` (every mode) once the limit is computed. It

1. reads the facts of the model the limit was computed on (main-bin counts, the background-only
   expectation, the modifiers and their correlation, the model's origin, and, when the run supplied
   its statistical-mode decision, the likelihood tiers the analysis published);
2. assesses them with the statistics catalogue and records the decision that matches what the
   engine ran: the cost-aware default, the calculator's escalation to toys, a budget refusal (then
   the toy method is unavailable at this budget and the fallback qualifies the result), the
   correlation bracket, or a seat's justified choice (``choices``);
3. computes the evidence the chosen methods' checks owe when the engine can: a background-only
   fit for the nuisance pulls and an Asimov signal injection for a constructed or supplied model;
4. verifies every owed check and attaches ``statistics`` (facts, assessment, decision, evidence,
   validity) and ``uncertainty`` (the statement of the reported limits) to the result.

An owed check whose evidence the engine could not produce is reported as not run, which holds the
result: nothing is assumed to pass.
"""
from __future__ import annotations

from copy import deepcopy
import math

import numpy as np

from . import situations, uncertainty

ORIGINS = {"likelihood": "published", "counting": "counting", "counting-combined": "counting",
           "constructed": "constructed", "simplified": "simplified"}
CALCULATOR_JUSTIFICATION = "the asymptotic calculator was requested explicitly (--cls-calculator asymptotic)"


def tier_facts(decision_record) -> dict:
    """The ``likelihood`` facts of a statistical-mode decision record (``stat_mode_decision``)."""
    evidence = (decision_record or {}).get("evidence") or {}
    published = evidence.get("published_likelihood") or {}
    review = published.get("appropriateness") or {}
    covariance = evidence.get("covariance") or {}
    return {"full": bool(published.get("available")), "appropriateness": review.get("verdict"),
            "covariance": bool(covariance.get("available")), "covariance_source": covariance.get("source"),
            "yields": bool((evidence.get("yields") or {}).get("available")),
            "systematics_registry": bool((evidence.get("systematics_registry") or {}).get("available")),
            "mutually_exclusive_regions": evidence.get("mutually_exclusive_regions")}


def method_of_mode(mode) -> str:
    return {"likelihood": "published-likelihood", "simplified": "simplified-likelihood",
            "constructed": "constructed-likelihood", "counting": "counting",
            "counting-combined": "counting"}[mode]


def tier_errors(mode, tiers, choices) -> list[str]:
    """Refuse a run below the strongest available tier unless a seat justified that choice."""
    facts = situations.make_facts(deliverables=["exclusion"], likelihood=tiers)
    row = next((s for s in situations.assess(facts)["situations"] if s["situation"] == "likelihood-availability"),
               None)
    if row is None:
        return []
    wanted, ran = row["default"], method_of_mode(mode)
    choice = (choices or {}).get("likelihood-availability")
    if wanted == ran:
        return []
    if isinstance(choice, dict) and choice.get("method") == ran and str(choice.get("justification") or "").strip():
        return []
    return [f"the run computes {ran} but the strongest available tier is {wanted}; record that choice and its "
            "justification as likelihood-availability in --statistics-choices"]


def _systematics_from_registry(registry, regions):
    rows = []
    for source in registry.sources:
        rows.append({"name": source["name"], "regions": regions if source["regions"] == "all" else source["regions"],
                     "correlation": source["correlation"]})
    return rows


def _bins_from_srs(srs):
    return [{"channel": row["name"], "bin": 0, "observed": float(row["n"]) if row.get("n") is not None else None,
             "background": float(row["b"]), "signal": float(row["s"]), "background_uncertainty": float(row["db"])}
            for row in srs]


def _staterror_moments(facts, model):
    """Equivalent bin moments encoded by the supplied absolute staterror templates.

    HistFactory adds these sample variances in quadrature within each bin.
    Only samples carrying the modifier contribute; absent moments stay absent.
    """
    bins = {(row["channel"], row["bin"]): row for row in facts.get("bins", [])}
    for channel in model.spec.get("channels", []):
        for sample in channel.get("samples", []):
            errors = [m["data"] for m in sample.get("modifiers", []) if m["type"] == "staterror"]
            if not errors:
                continue
            for index, value in enumerate(sample["data"]):
                row = bins[(channel["name"], index)]
                moments = row.setdefault("mc", {"sumw": 0.0, "sumw2": 0.0})
                moments["sumw"] += float(value)
                moments["sumw2"] += sum(float(error[index]) ** 2 for error in errors)


def _limits_evidence(res):
    from ravel.limits import read_limits
    limits = read_limits(res)
    return {"observed": limits.observed.status, "median": limits.expected[2].status}


def _toys_evidence(res):
    calculator = res.get("calculator") or {}
    toys = calculator.get("toys")
    if not isinstance(toys, dict):
        return None
    if toys.get("status") != "run":
        return {"status": toys.get("status"), "reason": toys.get("reason")}
    intervals = res.get("limit_mc_interval") or {}
    return {"status": "run", "observed": res.get("obs_limit"), "median": (res.get("exp_limits") or [None] * 5)[2],
            "observed_mc_interval": intervals.get("observed"),
            "median_mc_interval": (intervals.get("expected") or [None] * 5)[2]}


def pulls(model, data) -> dict:
    """Pulls of the scalar Gaussian-constrained parameters in a background-only fit to the data."""
    from .model_checks import _fit
    config = model.config
    fixed = {} if config.poi_index is None else {config.poi_index: 0.0}
    minuit = _fit(model, np.asarray(data, float), fixed=fixed)
    out = {}
    init = config.suggested_init()
    for name in config.par_order:
        parameter = config.param_set(name)
        if name == config.poi_name or parameter.n_parameters != 1 or not getattr(parameter, "constrained", False):
            continue
        if getattr(parameter, "pdf_type", "normal") != "normal":
            continue
        index = config.par_slice(name).start
        width = parameter.width()[0] if hasattr(parameter, "width") else 1.0
        if width and width > 0:
            out[name] = float((minuit.values[index] - init[index]) / width)
    return {"pulls": out, "fit_valid": bool(minuit.fmin.is_valid), "fit": "background-only, all nuisances free"}


def _choices(res, assessment, choices):
    seat = deepcopy(choices or {})
    detected = {row["situation"] for row in assessment["situations"]}
    calculator = res.get("calculator") or {}
    if "low-counts" in detected and calculator.get("requested") == "asymptotic" and "low-counts" not in seat:
        seat["low-counts"] = {"method": "asymptotic-cls", "justification": CALCULATOR_JUSTIFICATION}
    return {k: v for k, v in seat.items() if k in detected}


def _availability(res):
    toys = (res.get("calculator") or {}).get("toys")
    if isinstance(toys, dict) and toys.get("status") == "not_run" and toys.get("reason") == "budget":
        return {"toy-cls": {"available": False,
                            "reason": f"budget: {toys.get('bound', 'fits')} limit (estimated "
                                      f"{toys.get('estimated_seconds') or toys.get('estimated_fits')})"}}
    return {}


def attach(res, *, model=None, data=None, mode, choices=None, tiers=None, registry=None, srs=None,
           stat_only=None, compute=None, breakdown="auto", scale=1.0, regions=None) -> dict:
    """Attach ``statistics`` and ``uncertainty`` to an exclusion result; returns the result.

    ``regions`` names the main bins of a counting model, whose one channel stands for one region per
    bin, so the facts carry the region names the result reports.
    """
    origin = ORIGINS[mode]
    if model is not None:
        facts = situations.facts_from_model(model, data, origin=origin, deliverables=["exclusion"], likelihood=tiers)
        _staterror_moments(facts, model)
        if regions is not None:
            if len(regions) != len(facts["bins"]):
                raise ValueError(f"{len(regions)} region names for {len(facts['bins'])} counting bins")
            for row, name in zip(facts["bins"], regions):
                row.update(channel=name, bin=0)
        if registry is not None and srs is not None:
            facts["systematics"] = _systematics_from_registry(registry, [row["name"] for row in srs]) or None
            if facts["systematics"] is None:
                facts.pop("systematics")
        if mode in ("counting", "counting-combined"):
            facts.pop("systematics", None)
            facts["mc_statistics"] = "none"
    else:
        facts = situations.make_facts(deliverables=["exclusion"], model_origin=origin, bins=_bins_from_srs(srs),
                                      likelihood=tiers)
    availability = {**{m: situations.provider_status(m) for m in situations.METHODS}, **_availability(res)}
    assessment = situations.assess(facts, availability=availability)
    decision = situations.decide(assessment, _choices(res, assessment, choices))
    chosen = {row["situation"]: row["method"] for row in decision["choices"]}
    evidence = {"limits": _limits_evidence(res), "mc_statistics": facts.get("mc_statistics")}
    toys = _toys_evidence(res)
    if toys is not None:
        evidence["toys"] = toys
    budget = _availability(res)
    if budget:
        evidence["budget_refusals"] = [{"method": "toy-cls", **deepcopy((res.get("calculator") or {}).get("toys"))}]
    construction = res.get("construction") or {}
    if construction:
        evidence["builder_parity"] = (construction.get("parity") or {}).get("status")
        evidence["residuals"] = deepcopy(construction.get("residuals"))
    if isinstance(res.get("correlation_bracket"), dict):
        evidence["correlation_bracket"] = deepcopy(res["correlation_bracket"])
    if isinstance(res.get("reference_closure"), dict):
        evidence["reference_closure"] = deepcopy(res["reference_closure"])
    scope = res.get("model_scope") or {}
    if mode in ("counting", "counting-combined"):
        evidence["correlations_statement"] = scope.get("correlations")
    if chosen.get("systematic-nuisances") == "profiled-nuisances" and model is not None:
        try:
            found = pulls(model, data)
            evidence["pulls"] = found["pulls"]
            evidence["pull_fit_valid"] = found["fit_valid"]
        except Exception as exc:  # recorded: the owed check then reports that it did not run
            evidence["pulls_error"] = f"{type(exc).__name__}: {exc}"[:500]
    if chosen.get("model-validation") == "signal-injection" and model is not None:
        from .model_checks import signal_injection
        median = (res.get("exp_limits") or [None] * 5)[2]
        strengths = sorted({1.0, *([float(median) * scale] if median and math.isfinite(median) else [])})
        try:
            evidence["injection"] = signal_injection(model, injected=strengths)
        except Exception as exc:
            evidence["injection_error"] = f"{type(exc).__name__}: {exc}"[:500]
    block = situations.record(facts, evidence, availability=availability, decision=decision)
    res["statistics"] = block
    # The labels travel with the number: a result adopted as written already states them.
    for key, entries in (("statistics-qualified", block["validity"]["qualifications"]),
                         ("statistics-held", block["validity"]["holds"])):
        for entry in entries:
            rows = res.setdefault("limitations", [])
            if not any(isinstance(row, dict) and row.get("note") == entry["label"] for row in rows):
                rows.append({"key": key, "note": entry["label"]})
    # the uncertainty statement
    sources = uncertainty.model_sources(model) if model is not None and mode not in ("counting", "counting-combined") \
        else None
    if mode in ("counting", "counting-combined"):
        sources = {"systematic": ["background uncertainty of each region (Poisson-gamma constraint)"],
                   "mc_statistics": [], "free": []}
    signal_types = uncertainty.signal_modifiers(model) if model is not None else None
    if stat_only is None and compute is not None and model is not None:
        parameters = len(model.config.par_order)
        if breakdown == "on" or (breakdown == "auto" and parameters <= uncertainty.BREAKDOWN_PARAMETER_LIMIT):
            try:
                stat_only = uncertainty.stat_only_expected(model, data, compute)
            except Exception as exc:
                stat_only = {"status": "not-evaluated", "reason": f"the statistical-only reference failed: "
                                                                  f"{type(exc).__name__}: {exc}"[:400]}
        else:
            stat_only = {"status": "not-evaluated",
                         "reason": f"the model has {parameters} parameters; the statistical-only reference runs with "
                                   "--uncertainty-breakdown on"}
    if stat_only and stat_only.get("status") == "evaluated" and scale != 1.0:
        stat_only = {**stat_only, "expected": [x / scale for x in stat_only["expected"]],
                     "observed": stat_only["observed"] / scale}
    not_included = uncertainty.scope_omissions(scope)
    res["uncertainty"] = uncertainty.for_limits(res, sources=sources, signal_types=signal_types,
                                                stat_only=stat_only, not_included=not_included)
    return res


def outcome(res) -> str:
    return ((res.get("statistics") or {}).get("validity") or {}).get("outcome", "held")
