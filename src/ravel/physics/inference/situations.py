"""Statistics situations: what reveals a statistics problem, how RAVEL treats it, and when it is valid.

This catalogue is data defined in code. Each situation has

- a detector over a typed facts record (``statistics-facts``) that says what in the inputs
  reveals the situation and returns that evidence;
- methods ordered from cheapest to most expensive, each naming the installed packages and the
  RAVEL entry points (Python callables, commands, science modes) that provide it;
- coded validity checks, staged ``facts`` (decidable from the inputs before anything runs) or
  ``result`` (decidable from the computed result's evidence), each with what a failure means:
  ``escalate`` to the method's stronger successor, ``qualify`` the result with a stated label, or
  ``hold`` it;
- the qualified fallback used when the appropriate method is unavailable.

A method may also state when it applies (``applies``, recomputed from the facts): one that does not
apply to the facts, such as a toy calculator that samples and refits a HistFactory model for a
simplified likelihood, is passed over with that reason, never chosen and never escalated to.

The engine is cost-aware and never neuters a capability. ``assess`` selects, for every detected
situation, the cheapest available method whose facts-stage checks pass; a method whose checks
already fail on the inputs is passed over with its reason, so an asymptotic calculation is the
default exactly when its validity conditions hold and toys or a fuller treatment are chosen
automatically when they do not. ``decide`` records that default or a seat's justified choice.
``verify`` evaluates every check the chosen methods owe from the result evidence and returns
``valid``, ``qualified`` (with labels) or ``held``. ``audit`` recomputes all three from the facts
and evidence a record carries, so a record's own verdicts are never trusted.

``export()`` is the catalogue as JSON for deciding seats (``data/inference/statistics_situations.json``
is its generated copy; ``python -m ravel.physics.inference.situations catalogue --check`` keeps it
current). Every provider it names is checked to resolve to installed code.

The thresholds are recorded with each check. They are conventions with stated reasons, not
calibrations: a result that passes them is not thereby certified.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import math
import sys
from typing import Callable

SCHEMA_VERSION = 1
FACTS_KIND = "statistics-facts"
ASSESSMENT_KIND = "statistics-assessment"
DECISION_KIND = "statistics-decision"
VALIDITY_KIND = "statistics-validity"
CATALOGUE_KIND = "statistics-situation-catalogue"
BLOCK_KIND = "statistics-record"

COSTS = ("cheap", "moderate", "expensive")
STAGES = ("facts", "result")
ON_FAIL = ("escalate", "qualify", "hold")
OUTCOMES = ("valid", "qualified", "held")
DELIVERABLES = ("exclusion", "discovery", "estimation", "derived-quantity", "efficiency")
MODEL_ORIGINS = ("published", "simplified", "constructed", "counting", "supplied")
CORRELATIONS = ("correlated", "per-region", "per-sample", "per-sample-and-region", "declared", "independent",
                "unknown")
CHOICE_ORIGINS = ("default", "seat", "escalation", "fallback")

# Recorded conventions (each check states its own threshold in the export).
SMALL_COUNT = 5.0                 # asymptotic qtilde formulae need roughly >= 5 expected and observed counts per bin
MC_RELATIVE_UNCERTAINTY = 0.1     # an MC prediction whose relative statistical uncertainty exceeds 10% is limited
MC_MIN_EFFECTIVE_ENTRIES = 10.0   # fewer than 10 effective entries make the MC moment itself unreliable
NORMAL_APPROXIMATION_COUNT = 5.0  # n*eps and n*(1-eps) >= 5 for the normal binomial approximation
LINEARITY_TOLERANCE = 0.1         # linear and sampled standard deviations agree within 10%
TOY_RELATIVE_PRECISION = 0.2      # toy crossing interval half-width within 20% of the limit
PULL_LIMIT = 3.0                  # a fitted nuisance pulled beyond 3 sigma signals tension
INJECTION_TOLERANCE = 0.1         # an Asimov fit recovers the injected strength within 0.1 of its uncertainty
PARABOLIC_TOLERANCE = 0.1         # quadratic and profile half-widths agree within 10%
VR_RESIDUAL_LIMIT = 2.0           # validation-region residuals within 2 standard deviations
MC_SAMPLE_PRECISION = 0.02        # sampled standard deviation known to 2%
REFERENCE_CLOSURE_TOLERANCE = 0.2  # a model built here reproduces a benchmark's published limit within 20%


class StatisticsRecordError(ValueError):
    """A statistics record (facts, decision or evidence) cannot be admitted; ``errors`` lists every problem."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("statistics record refused: " + "; ".join(self.errors))


# --------------------------------------------------------------------------- catalogue types

@dataclass(frozen=True)
class Provider:
    """Installed code that implements a method. ``entrypoints`` are ``module:callable`` names."""
    packages: tuple = ()
    entrypoints: tuple = ()
    commands: tuple = ()
    modes: tuple = ()

    def as_dict(self):
        return {"packages": list(self.packages), "entrypoints": list(self.entrypoints),
                "commands": list(self.commands), "modes": list(self.modes)}


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    stage: str
    evaluate: Callable
    on_fail: str
    threshold: object
    reason: str
    qualification: str

    def as_dict(self):
        return {"id": self.id, "title": self.title, "stage": self.stage, "on_fail": self.on_fail,
                "threshold": self.threshold, "reason": self.reason, "qualification": self.qualification}


@dataclass(frozen=True)
class Method:
    id: str
    title: str
    cost: str
    provider: Provider
    checks: tuple
    escalation: str | None = None
    applies: Callable | None = None
    note: str = ""

    def as_dict(self):
        return {"id": self.id, "title": self.title, "cost": self.cost, "provider": self.provider.as_dict(),
                "checks": list(self.checks), "escalation": self.escalation, "note": self.note,
                "applies": " ".join((self.applies.__doc__ or "").split()) if self.applies else None}


@dataclass(frozen=True)
class Situation:
    id: str
    title: str
    revealed_by: str
    detect: Callable
    methods: tuple
    fallback: dict
    references: tuple = ()
    facts: tuple = ()

    def as_dict(self):
        return {"id": self.id, "title": self.title, "revealed_by": self.revealed_by, "facts": list(self.facts),
                "methods": list(self.methods), "fallback": dict(self.fallback),
                "references": list(self.references)}


# --------------------------------------------------------------------------- small helpers

def _finite(value):
    return type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value)


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _result(status, detail, **extra):
    return {"status": status, "detail": detail, **extra}


def _missing(what):
    return _result("missing", f"the evidence holds no {what}")


def _bins(facts):
    return [b for b in facts.get("bins") or () if isinstance(b, dict)]


def _small_count_bins(facts):
    rows = []
    for row in _bins(facts):
        n, b = row.get("observed"), row.get("background")
        small = [k for k, v in (("observed", n), ("background", b)) if _finite(v) and v < SMALL_COUNT]
        if small:
            rows.append({"channel": row.get("channel"), "bin": row.get("bin"), "observed": n, "background": b,
                         "below": small})
    return rows


def _mc_flags(facts):
    rows = []
    for row in _bins(facts):
        mc = row.get("mc")
        if not isinstance(mc, dict):
            continue
        w, w2 = mc.get("sumw"), mc.get("sumw2")
        if not (_finite(w) and _finite(w2)):
            continue
        reasons = []
        if w <= 0:
            if w2 > 0 or w < 0:
                reasons.append("nonpositive-yield")
        else:
            if math.sqrt(max(w2, 0.0)) / w > MC_RELATIVE_UNCERTAINTY:
                reasons.append("relative-mc-uncertainty")
            if w2 > 0 and w * w / w2 < MC_MIN_EFFECTIVE_ENTRIES:
                reasons.append("effective-entries")
        if reasons:
            rows.append({"channel": row.get("channel"), "bin": row.get("bin"), "sumw": w, "sumw2": w2,
                         "flags": reasons})
    return rows


def _shared_parameters(combination):
    seen, shared = {}, {}
    for item in (combination or {}).get("inputs") or ():
        for name, kind in sorted(((item or {}).get("parameters") or {}).items()):
            if name in seen:
                shared.setdefault(name, {seen[name][0]: seen[name][1]})[item.get("id")] = kind
            else:
                seen[name] = (item.get("id"), kind)
    return shared


def _asymmetric(inputs):
    out = []
    for row in inputs or ():
        up, down = row.get("error_up"), row.get("error_down")
        if _finite(up) and _finite(down) and not math.isclose(up, down, rel_tol=1e-9, abs_tol=1e-300):
            out.append(row.get("name"))
    return out


# --------------------------------------------------------------------------- detectors

def _detect_derived(facts):
    quantities = [q for q in facts.get("derived") or () if isinstance(q, dict)]
    if not quantities:
        return None
    return {"quantities": [q.get("name") for q in quantities],
            "asymmetric_inputs": {q.get("name"): _asymmetric(q.get("inputs")) for q in quantities
                                  if _asymmetric(q.get("inputs"))},
            "unknown_correlation": [q.get("name") for q in quantities if q.get("correlation") == "unknown"],
            "nonlinear_declared": [q.get("name") for q in quantities if q.get("linear") is False]}


def _detect_systematics(facts):
    sources = [s for s in facts.get("systematics") or () if isinstance(s, dict)]
    if not sources:
        return None
    return {"sources": [s.get("name") for s in sources],
            "unknown_correlation": [s.get("name") for s in sources if s.get("correlation") in (None, "unknown")],
            "regions": sorted({r for s in sources for r in s.get("regions") or ()})}


def _small_counts_for(facts, deliverable):
    if deliverable not in set(facts.get("deliverables") or ()):
        return None
    rows = _small_count_bins(facts)
    if not rows:
        return None
    return {"bins": rows, "threshold": SMALL_COUNT}


def _detect_low_counts(facts):
    # The methods calibrate CLs; a small-count interval is a parameter-estimation check.
    return _small_counts_for(facts, "exclusion")


def _detect_low_count_significance(facts):
    return _small_counts_for(facts, "discovery")


def _detect_combination(facts):
    combination = facts.get("combination")
    inputs = (combination or {}).get("inputs") or []
    if len(inputs) < 2:
        return None
    independence = (combination or {}).get("independence")
    return {"inputs": [i.get("id") for i in inputs], "shared_parameters": _shared_parameters(combination),
            "independence": independence if isinstance(independence, str) and independence.strip() else None}


def _detect_likelihood(facts):
    tiers = facts.get("likelihood")
    if not isinstance(tiers, dict):
        return None
    if not set(facts.get("deliverables") or ()) & {"exclusion", "estimation", "discovery"}:
        return None
    return {"available": {k: tiers.get(k) for k in ("full", "covariance", "yields", "systematics_registry")},
            "appropriateness": tiers.get("appropriateness"), "covariance_source": tiers.get("covariance_source"),
            "mutually_exclusive_regions": tiers.get("mutually_exclusive_regions")}


def _detect_mc(facts):
    rows = _mc_flags(facts)
    without = [{"channel": b.get("channel"), "bin": b.get("bin")} for b in _bins(facts)
               if b.get("mc") == "absent"]
    if not rows and not without:
        return None
    return {"flagged": rows, "without_moments": without,
            "thresholds": {"max_relative_uncertainty": MC_RELATIVE_UNCERTAINTY,
                           "min_effective_entries": MC_MIN_EFFECTIVE_ENTRIES},
            "treatment": facts.get("mc_statistics")}


def _detect_lee(facts):
    scan = facts.get("scan")
    if "discovery" not in set(facts.get("deliverables") or ()) or not isinstance(scan, dict):
        return None
    hypotheses = scan.get("hypotheses")
    if not isinstance(hypotheses, int) or hypotheses < 2:
        return None
    return {"hypotheses": hypotheses, "claim": scan.get("claim")}


def _detect_validation(facts):
    origin = facts.get("model_origin")
    reasons = []
    if origin in ("constructed", "supplied"):
        reasons.append(f"the statistical model is {origin} here, not the analysis's own validated likelihood")
    if "estimation" in set(facts.get("deliverables") or ()):
        reasons.append("a parameter is estimated from the model")
    if not reasons:
        return None
    return {"model_origin": origin, "reasons": reasons}


def _detect_estimation(facts):
    if "estimation" not in set(facts.get("deliverables") or ()):
        return None
    estimation = facts.get("estimation") or {}
    return {"parameters": list(estimation.get("parameters") or ()), "bounds": estimation.get("bounds") or {}}


def _detect_efficiency(facts):
    rows = [e for e in facts.get("efficiencies") or () if isinstance(e, dict)]
    if not rows:
        return None
    return {"efficiencies": [e.get("name") for e in rows],
            "weighted": [e.get("name") for e in rows if e.get("weighted")],
            "negative_weights": [e.get("name") for e in rows if e.get("negative_weights")]}


# --------------------------------------------------------------------------- applicability

def _histfactory_model(facts):
    """a HistFactory (pyhf) model, which the calculator samples and refits; a simplified likelihood is not one"""
    if facts.get("model_origin") == "simplified":
        return "the calculator samples and refits a HistFactory model; a simplified likelihood is not one"
    return None


# --------------------------------------------------------------------------- checks (facts stage)

def _c_asymptotic_regime(facts, evidence):
    rows = _small_count_bins(facts)
    if rows:
        return _result("fail", f"{len(rows)} main bin(s) below {SMALL_COUNT} observed or expected counts",
                       bins=rows)
    if not _bins(facts):
        return _missing("main-bin counts")
    return _result("pass", f"every main bin has at least {SMALL_COUNT} observed and expected counts")


def _c_single_bin_known(facts, evidence):
    bins = _bins(facts)
    if len(bins) != 1:
        return _result("fail", f"the exact reference needs exactly one main bin, not {len(bins)}")
    if facts.get("systematics") or bins[0].get("background_uncertainty") not in (0, 0.0):
        return _result("fail", "the exact reference needs a known background without nuisance parameters")
    return _result("pass", "one main bin with a known background")


def _c_correlation_declared(facts, evidence):
    sources = [s for s in facts.get("systematics") or () if isinstance(s, dict)]
    unknown = [s.get("name") for s in sources if s.get("correlation") in (None, "unknown")]
    if unknown:
        return _result("fail", "no correlation model is declared for " + ", ".join(map(str, unknown)),
                       sources=unknown)
    return _result("pass", "every source declares its correlation model")


def _c_correlation_known(facts, evidence):
    unknown = [q.get("name") for q in facts.get("derived") or () if q.get("correlation") == "unknown"]
    if unknown:
        return _result("fail", "input correlations are unknown for " + ", ".join(map(str, unknown)),
                       quantities=unknown)
    return _result("pass", "input correlations are supplied or declared independent")


def _c_symmetric_errors(facts, evidence):
    asymmetric = {q.get("name"): _asymmetric(q.get("inputs")) for q in facts.get("derived") or ()
                  if _asymmetric(q.get("inputs"))}
    if asymmetric:
        return _result("fail", "asymmetric input errors: " + ", ".join(sorted(map(str, asymmetric))),
                       asymmetric=asymmetric)
    return _result("pass", "every input error is symmetric")


def _c_independence_declared(facts, evidence):
    independence = (facts.get("combination") or {}).get("independence")
    if isinstance(independence, str) and independence.strip():
        return _result("pass", "the independence or overlap of the combined event populations is stated")
    return _result("fail", "the combination states nothing about whether its event populations overlap")


def _c_no_shared_parameters(facts, evidence):
    shared = _shared_parameters(facts.get("combination"))
    if shared:
        return _result("fail", "the inputs share parameters " + ", ".join(sorted(shared)), shared=shared)
    return _result("pass", "the inputs share no parameter")


def _c_shared_consistent(facts, evidence):
    shared = _shared_parameters(facts.get("combination"))
    inconsistent = {name: kinds for name, kinds in shared.items() if len(set(map(str, kinds.values()))) > 1}
    if inconsistent:
        return _result("fail", "shared parameters with different definitions: " + ", ".join(sorted(inconsistent)),
                       inconsistent=inconsistent)
    return _result("pass", f"{len(shared)} shared parameter(s) have one definition each")


def _c_mc_modelled(facts, evidence):
    rows = _mc_flags(facts)
    treatment = (evidence or {}).get("mc_statistics", facts.get("mc_statistics"))
    if rows and treatment not in ("staterror", "shapesys"):
        return _result("fail", f"{len(rows)} MC-limited bin(s) and the model carries no MC-statistics term "
                               f"(treatment {treatment!r})", flagged=rows)
    if rows:
        return _result("pass", f"{len(rows)} MC-limited bin(s) carry the {treatment} term")
    return _result("pass", "no bin is MC-limited")


def _c_mc_moments(facts, evidence):
    without = [b for b in _bins(facts) if b.get("mc") == "absent"]
    if without:
        return _result("fail", f"{len(without)} bin(s) have no MC moments, so their MC statistical "
                               "uncertainty cannot be modelled")
    return _result("pass", "every MC-predicted bin carries sumw and sumw2")


def _c_generator_law(facts, evidence):
    if isinstance(facts.get("mc_generator_law"), str) and facts["mc_generator_law"].strip():
        return _result("pass", "the MC generator law is declared")
    return _result("fail", "the exact finite-MC likelihood needs a declared generator law")


def _c_validation_regions(facts, evidence):
    regions = sorted({b.get("channel") for b in _bins(facts) if b.get("role") == "VR"})
    if regions:
        return _result("pass", "validation regions: " + ", ".join(map(str, regions)))
    return _result("fail", "no validation region is declared")


def _c_normal_approximation(facts, evidence):
    bad = []
    for row in facts.get("efficiencies") or ():
        passed, total = row.get("passed"), row.get("total")
        if not (_finite(passed) and _finite(total) and total > 0):
            bad.append({"name": row.get("name"), "reason": "no counts"})
            continue
        eps = passed / total
        if total * eps < NORMAL_APPROXIMATION_COUNT or total * (1 - eps) < NORMAL_APPROXIMATION_COUNT:
            bad.append({"name": row.get("name"), "passed": passed, "total": total})
    if bad:
        return _result("fail", f"{len(bad)} efficiency(ies) too close to 0 or 1 for the normal approximation",
                       efficiencies=bad)
    return _result("pass", "every efficiency has n*eps and n*(1-eps) of at least 5")


def _c_unweighted(facts, evidence):
    weighted = [e.get("name") for e in facts.get("efficiencies") or () if e.get("weighted")]
    if weighted:
        return _result("fail", "weighted entries: " + ", ".join(map(str, weighted)))
    return _result("pass", "every efficiency counts unweighted entries")


def _c_nonnegative_weights(facts, evidence):
    negative = [e.get("name") for e in facts.get("efficiencies") or () if e.get("negative_weights")]
    if negative:
        return _result("fail", "negative weights in " + ", ".join(map(str, negative)))
    return _result("pass", "no negative weights")


def _c_independent_tests(facts, evidence):
    if (facts.get("scan") or {}).get("independent_tests") is True:
        return _result("pass", "the tested hypotheses are declared statistically independent")
    return _result("fail", "the scanned hypotheses are not declared independent")


def _c_local_claim(facts, evidence):
    claim = (facts.get("scan") or {}).get("claim")
    if claim == "local":
        return _result("pass", "the significance is claimed local only")
    return _result("fail", f"the claim is {claim!r}; a global claim needs a look-elsewhere correction")


def _c_one_dimensional(facts, evidence):
    dimensions = (facts.get("scan") or {}).get("dimensions")
    if dimensions == 1:
        return _result("pass", "the scan has one coordinate")
    stated = "an unstated number of" if dimensions is None else str(dimensions)
    return _result("fail", f"the scan has {stated} coordinates; upcrossings are counted along one ordered coordinate")


def _tier(facts):
    return facts.get("likelihood") if isinstance(facts.get("likelihood"), dict) else {}


def _c_published_appropriate(facts, evidence):
    tiers = _tier(facts)
    if not tiers.get("full"):
        return _result("fail", "no published likelihood is available")
    verdict = tiers.get("appropriateness")
    if verdict in ("appropriate", "appropriate-with-cautions"):
        return _result("pass", f"appropriateness verdict {verdict}")
    if verdict is None:
        return _result("fail", "the published likelihood's appropriateness is not assessed")
    return _result("fail", f"appropriateness verdict {verdict}")


def _c_covariance_sourced(facts, evidence):
    tiers = _tier(facts)
    if not tiers.get("covariance"):
        return _result("fail", "no published covariance is available")
    if not (isinstance(tiers.get("covariance_source"), str) and tiers["covariance_source"].strip()):
        return _result("fail", "the covariance has no recorded source")
    return _result("pass", "a published covariance with a recorded source")


def _c_yields_and_registry(facts, evidence):
    tiers = _tier(facts)
    if tiers.get("yields") and tiers.get("systematics_registry"):
        return _result("pass", "published yields and a declared systematics registry")
    return _result("fail", "published yields and a declared systematics registry are both needed")


def _c_yields(facts, evidence):
    if _tier(facts).get("yields"):
        return _result("pass", "published per-region yields")
    return _result("fail", "no published per-region yields")


# --------------------------------------------------------------------------- checks (result stage)

def _limit_statuses(evidence):
    limits = (evidence or {}).get("limits")
    if not isinstance(limits, dict):
        return None
    return limits


def _c_limits_resolved(facts, evidence):
    limits = _limit_statuses(evidence)
    if limits is None:
        return _missing("typed limits")
    observed, median = limits.get("observed"), limits.get("median")
    if median in (None, "missing"):
        return _result("fail", "the expected median limit is missing")
    bad = [f"{name} is {status}" for name, status in (("observed", observed), ("expected median", median))
           if status not in (None, "resolved", "missing")]
    if bad:
        return _result("fail", "unresolved limit: " + "; ".join(bad))
    return _result("pass", "the observed (when present) and expected median limits are resolved roots")


def _c_toy_precision(facts, evidence):
    toys = (evidence or {}).get("toys")
    if not isinstance(toys, dict):
        return _missing("toy calibration")
    if toys.get("status") != "run":
        return _result("fail", f"toys not run ({toys.get('reason') or toys.get('status')})", toys=toys)
    worst = None
    for name in ("observed", "median"):
        value, interval = toys.get(name), toys.get(name + "_mc_interval")
        if value is None:
            continue
        if not (_finite(value) and isinstance(interval, list) and len(interval) == 2
                and all(_finite(x) for x in interval)):
            return _result("fail", f"the {name} toy crossing has no closed MC interval")
        half = (interval[1] - interval[0]) / 2
        relative = half / value if value > 0 else math.inf
        worst = relative if worst is None else max(worst, relative)
    if worst is None:
        return _missing("toy crossings")
    if worst > TOY_RELATIVE_PRECISION:
        return _result("fail", f"toy MC interval half-width is {worst:.0%} of the limit", relative=worst)
    return _result("pass", f"toy MC interval half-width within {worst:.0%} of the limit", relative=worst)


def _reference_closure(evidence):
    found = (evidence or {}).get("reference_closure")
    return found if isinstance(found, dict) else None


def _c_reference_declared(facts, evidence):
    found = _reference_closure(evidence)
    if found is None:
        return _result("fail", "no published reference limits were supplied, and none were declared unavailable")
    if found.get("available") is False:
        reason, searched = found.get("reason"), found.get("evidence")
        if all(isinstance(v, str) and v.strip() for v in (reason, searched)):
            return _result("pass", f"no published reference limits: {reason.strip()} (searched: {searched.strip()})")
        return _result("fail", "reference limits are declared unavailable without a reason and its evidence")
    if isinstance(found.get("points"), list) and found["points"]:
        return _result("pass", f"{len(found['points'])} published reference point(s) from {found.get('source')}")
    return _result("fail", "the reference closure carries no benchmark point")


def _c_reference_closure(facts, evidence):
    found = _reference_closure(evidence)
    if found is None or found.get("available") is False or not isinstance(found.get("points"), list):
        return _result("pass", "no published reference limits to close against (reference-limits-declared states why)")
    bad, worst = [], 0.0
    for row in found["points"]:
        if not isinstance(row, dict):
            bad.append("a reference point is not a record")
            continue
        published, reproduced = row.get("published") or {}, row.get("reproduced") or {}
        for side in ("expected", "observed"):
            target = published.get(side)
            if target is None and side == "observed":
                continue
            value, status = (reproduced.get(side) or {}).get("value"), (reproduced.get(side) or {}).get("status")
            if not (_finite(target) and target > 0):
                bad.append(f"{row.get('id')}: no published {side} limit")
            elif status != "resolved" or not _finite(value):
                bad.append(f"{row.get('id')}: the reproduced {side} limit is {status or 'missing'}")
            else:
                difference = abs(value - target) / target
                worst = max(worst, difference)
                if difference > REFERENCE_CLOSURE_TOLERANCE:
                    bad.append(f"{row.get('id')}: {side} limit {value:.4g} against the published {target:.4g} "
                               f"({difference:.0%})")
    if bad:
        return _result("fail", "; ".join(bad), tolerance=REFERENCE_CLOSURE_TOLERANCE)
    return _result("pass", f"every benchmark limit within {REFERENCE_CLOSURE_TOLERANCE:.0%} (worst {worst:.1%})",
                   worst=worst)


def _c_builder_parity(facts, evidence):
    parity = (evidence or {}).get("builder_parity")
    if parity is None:
        return _missing("builder parity record")
    if parity in ("identical", "equivalent-at-one-sigma"):
        return _result("pass", f"cabinetry and the native builder agree ({parity})")
    return _result("fail", f"builder parity {parity}")


def _c_total_preserved(facts, evidence):
    residuals = (evidence or {}).get("residuals")
    if not isinstance(residuals, list):
        return _missing("published-total residuals")
    bad = [r for r in residuals if not (isinstance(r, dict) and _finite(r.get("total_uncertainty"))
                                        and _finite(r.get("declared_quadrature")) and _finite(r.get("remainder")))]
    if bad:
        return _result("fail", "a region's published total uncertainty is not decomposed")
    off = [r["region"] for r in residuals
           if not math.isclose(math.hypot(r["declared_quadrature"], r["remainder"]), r["total_uncertainty"],
                               rel_tol=1e-6, abs_tol=1e-12)]
    if off:
        return _result("fail", "declared components plus remainder do not equal the published total in "
                       + ", ".join(map(str, off)))
    return _result("pass", "declared components plus the recorded remainder reproduce every published total")


def _c_pulls(facts, evidence):
    pulls = (evidence or {}).get("pulls")
    if not isinstance(pulls, dict):
        return _missing("nuisance pulls")
    large = {k: v for k, v in pulls.items() if _finite(v) and abs(v) > PULL_LIMIT}
    if large:
        return _result("fail", "nuisance parameters pulled beyond 3 sigma: " + ", ".join(sorted(large)), pulls=large)
    return _result("pass", f"{len(pulls)} nuisance pull(s) within {PULL_LIMIT} sigma")


def _c_bracket_envelope(facts, evidence):
    bracket = (evidence or {}).get("correlation_bracket")
    if not isinstance(bracket, dict):
        return _missing("correlation bracket")
    variants = bracket.get("variants")
    reported = bracket.get("reported")
    if not (isinstance(variants, dict) and len(variants) >= 2 and all(_finite(v) for v in variants.values())):
        return _result("fail", "the correlation bracket needs at least two evaluated variants")
    rule = bracket.get("rule", "max")
    if rule not in ("max", "min"):
        return _result("fail", "the correlation bracket rule must name max or min")
    envelope = max(variants.values()) if rule == "max" else min(variants.values())
    if not (_finite(reported) and math.isclose(reported, envelope, rel_tol=1e-9, abs_tol=1e-12)):
        return _result("fail", f"the reported value {reported} is not the {rule} of the bracket {variants}")
    return _result("pass", f"the reported value is the {rule} over {len(variants)} correlation variants")


def _c_linearity(facts, evidence):
    rows = (evidence or {}).get("linearity")
    if not isinstance(rows, list) or not rows:
        return _missing("linear-versus-sampled comparison")
    bad = [r.get("name") for r in rows if not (_finite(r.get("relative_difference"))
                                               and r["relative_difference"] <= LINEARITY_TOLERANCE
                                               and _finite(r.get("mean_shift_in_sigma"))
                                               and abs(r["mean_shift_in_sigma"]) <= LINEARITY_TOLERANCE)]
    if bad:
        return _result("fail", "the linear approximation differs from sampling for " + ", ".join(map(str, bad)),
                       quantities=bad)
    return _result("pass", f"linear and sampled propagation agree within {LINEARITY_TOLERANCE:.0%}")


def _c_mc_sample_precision(facts, evidence):
    rows = (evidence or {}).get("sampling")
    if not isinstance(rows, list) or not rows:
        return _missing("sampling precision")
    bad = [r.get("name") for r in rows if not (_finite(r.get("relative_precision"))
                                               and r["relative_precision"] <= MC_SAMPLE_PRECISION)]
    if bad:
        return _result("fail", "too few samples for " + ", ".join(map(str, bad)))
    return _result("pass", f"sampled standard deviations known to {MC_SAMPLE_PRECISION:.0%}")


def _c_upcrossings(facts, evidence):
    lee = (evidence or {}).get("look_elsewhere")
    if not isinstance(lee, dict):
        return _missing("look-elsewhere evaluation")
    upcrossings, reference, observed = lee.get("upcrossings"), lee.get("reference_level"), lee.get("max_local_q0")
    if not (isinstance(upcrossings, int) and upcrossings >= 1):
        return _result("fail", "no upcrossing at the reference level; the trials factor is not estimable")
    if not (_finite(reference) and _finite(observed) and reference < observed):
        return _result("fail", "the reference level must lie below the largest local test statistic")
    return _result("pass", f"{upcrossings} upcrossing(s) at q0 = {reference:g}")


def _c_significance(facts, evidence):
    found = (evidence or {}).get("discovery")
    if not isinstance(found, dict):
        return _missing("discovery test statistic")
    values = {k: found[k] for k in ("expected_q0", "observed_q0") if found.get(k) is not None}
    if not values:
        return _missing("discovery test statistic")
    bad = sorted(k for k, v in values.items() if not _finite(v))
    if bad:
        return _result("fail", "the discovery statistic is not finite: " + ", ".join(bad))
    return _result("pass", "the discovery statistic is finite: "
                   + ", ".join(f"{k} {v:.4g}" for k, v in sorted(values.items())))


def _c_toy_tail(facts, evidence):
    toys = (evidence or {}).get("discovery_toys")
    if not isinstance(toys, dict) or not toys:
        return _missing("discovery toys")
    bad = []
    for name, row in sorted(toys.items()):
        if not isinstance(row, dict):
            bad.append(f"{name}: no toy record")
            continue
        p, error = row.get("p_value"), row.get("p_value_mc_uncertainty")
        if row.get("status") != "resolved":
            bad.append(f"{name}: no toy reaches the statistic in {row.get('count')} toys; the p-value is a bound")
        elif not (_finite(p) and _finite(error) and p > 0):
            bad.append(f"{name}: no finite p-value")
        elif error / p > TOY_RELATIVE_PRECISION:
            bad.append(f"{name}: relative Monte Carlo uncertainty {error / p:.0%}")
    if bad:
        return _result("fail", "; ".join(bad))
    return _result("pass", f"every toy p-value has a resolved tail within {TOY_RELATIVE_PRECISION:.0%}")


def _c_injection(facts, evidence):
    rows = (evidence or {}).get("injection")
    if not isinstance(rows, list) or not rows:
        return _missing("signal-injection test")
    bad = []
    for row in rows:
        mu, fitted, sigma = row.get("injected"), row.get("fitted"), row.get("uncertainty")
        if not (_finite(mu) and _finite(fitted) and _finite(sigma) and sigma > 0):
            bad.append({"injected": mu, "reason": "the fit gives no finite estimate and uncertainty"})
        elif row.get("valid") is not True:
            bad.append({"injected": mu, "reason": "the fit is invalid or its covariance is not accurate "
                                                  "(a degenerate or unidentified parameter)"})
        elif abs(fitted - mu) > INJECTION_TOLERANCE * sigma:
            bad.append({"injected": mu, "fitted": fitted, "uncertainty": sigma})
    if bad:
        return _result("fail", "injected signal not recovered", failures=bad)
    return _result("pass", f"{len(rows)} injected strength(s) recovered within {INJECTION_TOLERANCE} sigma")


def _c_vr_residuals(facts, evidence):
    residuals = (evidence or {}).get("validation_residuals")
    if not isinstance(residuals, dict) or not residuals:
        return _missing("validation-region residuals")
    bad = {k: v for k, v in residuals.items() if not (_finite(v) and abs(v) <= VR_RESIDUAL_LIMIT)}
    if bad:
        return _result("fail", "validation-region residuals beyond 2 sigma: " + ", ".join(sorted(bad)),
                       residuals=bad)
    return _result("pass", f"{len(residuals)} validation-region residual(s) within {VR_RESIDUAL_LIMIT} sigma")


def _c_coverage(facts, evidence):
    coverage = (evidence or {}).get("coverage")
    if not isinstance(coverage, dict):
        return _missing("coverage test")
    level, lower = coverage.get("level"), coverage.get("false_exclusion_lower")
    if not (_finite(level) and _finite(lower)):
        return _result("fail", "the coverage record has no level and false-exclusion bound")
    if lower > level:
        return _result("fail", f"the false-exclusion rate is above {level} at 95% confidence (lower bound {lower:.3g})")
    return _result("pass", f"false-exclusion rate consistent with at most {level} (lower bound {lower:.3g})")


def _c_parabolic(facts, evidence):
    rows = (evidence or {}).get("intervals")
    if not isinstance(rows, list) or not rows:
        return _missing("profile intervals")
    bad = []
    for row in rows:
        quadratic, low, high = row.get("quadratic_half_width"), row.get("profile_low"), row.get("profile_high")
        if not (_finite(quadratic) and _finite(low) and _finite(high)):
            bad.append(row.get("parameter"))
            continue
        if max(abs(quadratic - low), abs(quadratic - high)) > PARABOLIC_TOLERANCE * quadratic:
            bad.append(row.get("parameter"))
    if bad:
        return _result("fail", "the profile is not parabolic for " + ", ".join(map(str, bad)), parameters=bad)
    return _result("pass", "quadratic and profile half-widths agree")


def _c_interval_resolved(facts, evidence):
    rows = (evidence or {}).get("intervals")
    if not isinstance(rows, list) or not rows:
        return _missing("profile intervals")
    bad = [row.get("parameter") for row in rows if row.get("status") != "resolved"]
    if bad:
        return _result("fail", "interval edges not bracketed for " + ", ".join(map(str, bad)))
    return _result("pass", "every interval edge is a resolved crossing")


def _c_away_from_boundary(facts, evidence):
    rows = (evidence or {}).get("intervals")
    if not isinstance(rows, list) or not rows:
        return _missing("profile intervals")
    bad = [row.get("parameter") for row in rows if row.get("at_boundary")]
    if bad:
        return _result("fail", "the interval reaches a parameter boundary for " + ", ".join(map(str, bad)))
    return _result("pass", "no interval reaches a parameter boundary")


def _c_correlations_stated(facts, evidence):
    statement = (evidence or {}).get("correlations_statement")
    if isinstance(statement, str) and statement.strip():
        return _result("pass", "the counting model states its correlation assumption")
    return _result("fail", "the counting model does not state its correlation assumption")


def _c_combined(facts, evidence):
    combined = (evidence or {}).get("combined")
    if not isinstance(combined, dict):
        return _missing("combination record")
    if combined.get("inputs") and len(combined["inputs"]) >= 2 and combined.get("status") == "combined":
        return _result("pass", f"{len(combined['inputs'])} inputs combined")
    return _result("fail", "the inputs were not combined")


# --------------------------------------------------------------------------- the catalogue

def _check(id, title, stage, evaluate, on_fail, threshold, reason, qualification):
    return Check(id, title, stage, evaluate, on_fail, threshold, reason, qualification)


CHECKS = {c.id: c for c in (
    _check("asymptotic-regime", "Counts large enough for asymptotic formulae", "facts", _c_asymptotic_regime,
           "escalate", {"min_count": SMALL_COUNT},
           "asymptotic qtilde distributions are unreliable below a few expected or observed counts",
           "small-count regime: the asymptotic CLs calibration is not verified by toys"),
    _check("asymptotic-significance-regime", "Counts large enough for an asymptotic discovery significance",
           "facts", _c_asymptotic_regime, "escalate", {"min_count": SMALL_COUNT},
           "the asymptotic half chi-square law of q0 is unreliable below a few expected or observed counts",
           "small-count regime: the asymptotic discovery significance is not verified by toys"),
    _check("asymptotic-interval-regime", "Counts large enough for asymptotic intervals", "facts",
           _c_asymptotic_regime, "qualify", {"min_count": SMALL_COUNT},
           "the coverage of a likelihood-ratio interval rests on its asymptotic chi-square law, which needs a few "
           "expected and observed counts per bin",
           "small or unstated counts: the asymptotic interval coverage is not verified by toys"),
    _check("significance-evaluated", "The discovery statistic is evaluated", "result", _c_significance, "hold",
           None, "a discovery significance needs its finite test statistic",
           "the discovery test statistic is not finite"),
    _check("toy-tail-resolved", "Toy discovery p-values are resolved and precise", "result", _c_toy_tail,
           "qualify", {"max_relative_uncertainty": TOY_RELATIVE_PRECISION},
           "a toy p-value carries the Monte Carlo uncertainty of the finite ensemble, and an empty tail is a bound",
           "toy discovery p-value with an unresolved tail or a large Monte Carlo uncertainty"),
    _check("single-bin-known-background", "One bin with a known background", "facts", _c_single_bin_known,
           "escalate", None, "the exact count-ordered CLs reference has no nuisance parameter",
           "the exact reference does not apply to this model"),
    _check("limits-resolved", "Limits are resolved roots", "result", _c_limits_resolved, "qualify", None,
           "a scan endpoint is a bound, not a limit",
           "the limit is a scan bound, not a resolved root"),
    _check("toy-mc-precision", "Toy calibration is precise enough", "result", _c_toy_precision, "qualify",
           {"max_relative_half_width": TOY_RELATIVE_PRECISION},
           "a toy crossing carries Monte Carlo uncertainty from the finite ensemble",
           "toy-calibrated limit with a large Monte Carlo uncertainty"),
    _check("correlation-declared", "Every systematic source declares its correlation", "facts",
           _c_correlation_declared, "escalate", None,
           "treating unknown correlations as known can understate or overstate the uncertainty",
           "correlations of some systematic sources are unknown; they are treated as stated"),
    _check("pulls-within-limit", "Nuisance pulls are moderate", "result", _c_pulls, "qualify",
           {"max_abs_pull": PULL_LIMIT}, "a large pull indicates tension between the data and the model",
           "a nuisance parameter is pulled beyond 3 sigma"),
    _check("reference-limits-declared", "Published reference limits are supplied or declared absent", "result",
           _c_reference_declared, "qualify", None,
           "a model built here stands in for the analysis's likelihood only as far as it reproduces the analysis's "
           "published limits",
           "closure against the published limits is not evaluated"),
    _check("reference-limit-closure", "The model reproduces the published limits", "result", _c_reference_closure,
           "hold", {"max_relative_difference": REFERENCE_CLOSURE_TOLERANCE},
           "a model that misses a benchmark's published limit by more than the tolerance does not stand in for the "
           "analysis's likelihood",
           "the model does not reproduce the published limits within the closure tolerance"),
    _check("builder-parity", "Constructed model agrees between builders", "result", _c_builder_parity, "hold", None,
           "two independent builders of one declared model must agree",
           "the constructed model differs between builders"),
    _check("published-total-preserved", "Published total uncertainties are preserved", "result",
           _c_total_preserved, "hold", None,
           "a constructed model must reproduce the published total background uncertainty per region",
           "the constructed model does not reproduce the published uncertainties"),
    _check("bracket-envelope", "The declared envelope over evaluated correlation variants is reported", "result",
           _c_bracket_envelope, "hold", None,
           "the stated correlation assignments are evaluated and their declared extremum is reported",
           "the correlation bracket is incomplete"),
    _check("correlation-known", "Input correlations are known", "facts", _c_correlation_known, "escalate", None,
           "propagation through correlated inputs needs their correlation",
           "input correlations are unknown; the conservative envelope over the stated range is reported"),
    _check("symmetric-errors", "Input errors are symmetric", "facts", _c_symmetric_errors, "escalate", None,
           "linear propagation of a covariance assumes symmetric Gaussian errors",
           "asymmetric input errors were symmetrised"),
    _check("linearity", "Linear propagation agrees with sampling", "result", _c_linearity, "escalate",
           {"tolerance": LINEARITY_TOLERANCE},
           "a non-linear function of uncertain inputs is not described by its first derivatives",
           "non-linear propagation was approximated linearly"),
    _check("mc-sample-precision", "Enough samples for the propagated spread", "result", _c_mc_sample_precision,
           "qualify", {"max_relative_precision": MC_SAMPLE_PRECISION},
           "a sampled standard deviation has its own sampling uncertainty",
           "the sampled spread carries a non-negligible sampling uncertainty"),
    _check("independence-declared", "Event-population independence is stated", "facts", _c_independence_declared,
           "hold", None, "a product of likelihoods double counts overlapping events",
           "the independence of the combined event populations is not stated"),
    _check("no-shared-parameters", "Inputs share no parameter", "facts", _c_no_shared_parameters, "escalate", None,
           "an uncorrelated combination drops the correlation of shared systematics",
           "shared systematic parameters were treated as uncorrelated"),
    _check("shared-parameter-consistency", "Shared parameters have one definition", "facts", _c_shared_consistent,
           "hold", None, "a shared name with different constraints is not one parameter",
           "inputs disagree on the definition of a shared parameter"),
    _check("inputs-combined", "The inputs were combined", "result", _c_combined, "qualify", None,
           "a combination result must name the inputs it combined", "the inputs were not combined"),
    _check("published-appropriate", "The published likelihood is appropriate", "facts", _c_published_appropriate,
           "escalate", None, "an inappropriate or unassessed likelihood describes another measurement",
           "the published likelihood was not used"),
    _check("covariance-sourced", "A sourced published covariance", "facts", _c_covariance_sourced, "escalate", None,
           "a simplified likelihood needs the published covariance and its source",
           "no sourced published covariance"),
    _check("yields-and-registry", "Yields with a declared systematics breakdown", "facts", _c_yields_and_registry,
           "escalate", None, "a constructed model needs per-region yields and every systematic component",
           "no systematics breakdown to construct a model"),
    _check("yields-available", "Published per-region yields", "facts", _c_yields, "hold", None,
           "a counting model needs the published yields", "no published yields"),
    _check("correlations-stated", "The counting model states its correlation assumption", "result",
           _c_correlations_stated, "qualify", None,
           "a counting model without published correlations must say what it assumes",
           "background correlations between regions not published; constraints assumed independent"),
    _check("mc-moments-available", "MC moments are available", "facts", _c_mc_moments, "qualify", None,
           "the MC statistical uncertainty is computed from sumw and sumw2",
           "MC statistical uncertainty not modelled: the MC moments are absent"),
    _check("mc-statistics-modelled", "MC-limited bins carry an MC-statistics term", "result", _c_mc_modelled,
           "qualify", {"max_relative_uncertainty": MC_RELATIVE_UNCERTAINTY,
                       "min_effective_entries": MC_MIN_EFFECTIVE_ENTRIES},
           "a limited MC prediction treated as exact understates the uncertainty",
           "MC statistical uncertainty of limited bins is not modelled"),
    _check("generator-law-declared", "A declared MC generator law", "facts", _c_generator_law, "escalate", None,
           "an exact finite-MC likelihood is conditional on the declared generator law",
           "no generator law is declared for the exact finite-MC likelihood"),
    _check("validation-regions-present", "Validation regions exist", "facts", _c_validation_regions, "escalate",
           None, "closure is tested in regions the background fit did not use", "no validation region to test closure"),
    _check("independent-tests-declared", "Scanned tests declared independent", "facts", _c_independent_tests,
           "escalate", None, "a Sidak correction assumes independent tests",
           "the trials correction assumes independent tests"),
    _check("one-dimensional-scan", "The scan has one coordinate", "facts", _c_one_dimensional, "escalate", None,
           "the upcrossing estimate counts crossings along one ordered scan coordinate",
           "the upcrossing trials factor applies to a one-dimensional scan only"),
    _check("local-claim", "The significance is claimed local", "facts", _c_local_claim, "escalate", None,
           "a local significance over many tested hypotheses overstates the global evidence",
           "local significance; the global significance over the scanned hypotheses is not evaluated"),
    _check("upcrossings-observed", "Upcrossings support the trials factor", "result", _c_upcrossings, "qualify",
           None, "the upcrossing estimate extrapolates from upcrossings at a low reference level",
           "the trials factor rests on too few upcrossings"),
    _check("signal-injection", "Injected signal is recovered", "result", _c_injection, "hold",
           {"tolerance_in_sigma": INJECTION_TOLERANCE},
           "an Asimov fit must recover the strength it was built with; a failure reveals degeneracy, a bound "
           "or a defective parameterisation", "the model does not recover an injected signal"),
    _check("validation-closure", "Validation regions close", "result", _c_vr_residuals, "qualify",
           {"max_abs_residual": VR_RESIDUAL_LIMIT},
           "the background model is tested in regions it was not fitted to",
           "the background model does not close in a validation region"),
    _check("coverage-at-truth", "False-exclusion rate at the truth", "result", _c_coverage, "qualify",
           {"confidence": 0.95}, "a 95% CLs limit must not exclude the true strength more than 5% of the time",
           "the limit over-excludes the true signal strength"),
    _check("parabolic-profile", "The profile is parabolic", "result", _c_parabolic, "escalate",
           {"tolerance": PARABOLIC_TOLERANCE},
           "a quadratic error is the profile interval only for a parabolic likelihood",
           "the interval is the quadratic approximation of a non-parabolic profile"),
    _check("interval-resolved", "Interval edges are resolved", "result", _c_interval_resolved, "qualify", None,
           "an interval edge at the scan edge is a bound", "an interval edge is a scan bound"),
    _check("away-from-boundary", "The interval stays away from boundaries", "result", _c_away_from_boundary,
           "qualify", None, "Wilks' theorem fails at a physical boundary of the parameter",
           "the interval reaches a physical boundary; its coverage is not verified"),
    _check("normal-approximation", "Normal approximation of a binomial", "facts", _c_normal_approximation,
           "escalate", {"min_count": NORMAL_APPROXIMATION_COUNT},
           "the normal binomial interval under-covers near 0 and 1",
           "normal-approximation efficiency interval near 0 or 1"),
    _check("unweighted-counts", "Unweighted entries", "facts", _c_unweighted, "escalate", None,
           "exact binomial intervals assume unweighted counts", "weighted entries treated as counts"),
    _check("nonnegative-weights", "No negative weights", "facts", _c_nonnegative_weights, "qualify", None,
           "negative weights break the binomial picture of an efficiency",
           "negative event weights: the efficiency uncertainty is an approximation"),
)}


def _p(*, packages=(), entrypoints=(), commands=(), modes=()):
    return Provider(tuple(packages), tuple(entrypoints), tuple(commands), tuple(modes))


EXCLUDE_COMMANDS = ("pyhf_exclude likelihood", "pyhf_exclude counting", "pyhf_exclude constructed")

METHODS = {m.id: m for m in (
    # low counts
    Method("asymptotic-cls", "Asymptotic CLs (qtilde) with the Asimov expected band", "cheap",
           _p(packages=("pyhf",), entrypoints=("ravel.physics.pyhf_exclude:compute",),
              commands=EXCLUDE_COMMANDS, modes=("search-statistics",)),
           ("asymptotic-regime", "limits-resolved"), escalation="toy-cls"),
    Method("toy-cls", "Toy-based CLs calibrated around the asymptotic roots", "expensive",
           _p(packages=("pyhf",), entrypoints=("ravel.physics.inference.toy_cls:apply",),
              commands=tuple(c + " --cls-calculator toybased" for c in EXCLUDE_COMMANDS), modes=("search-statistics",)),
           ("toy-mc-precision", "limits-resolved"), applies=_histfactory_model),
    Method("exact-count-calibration", "Exact count-ordered CLs for one bin with a known background", "cheap",
           _p(entrypoints=("ravel.validation.statistical_calibration:known_background_poisson_upper_limit",)),
           ("single-bin-known-background", "limits-resolved"), note="a reference for one bin without nuisance parameters"),
    # low counts in a discovery significance
    Method("asymptotic-significance", "Asymptotic discovery significance from the profile-likelihood q0", "cheap",
           _p(packages=("pyhf",), modes=("search-statistics",)),
           ("asymptotic-significance-regime", "significance-evaluated"), escalation="toy-significance"),
    Method("toy-significance", "Discovery p-value from background-only toys with q0 refitted on each", "expensive",
           _p(packages=("pyhf", "scipy"), entrypoints=("ravel.physics.inference.search:toy_discovery",),
              modes=("search-statistics",)),
           ("significance-evaluated", "toy-tail-resolved"), applies=_histfactory_model),
    # systematics and nuisance parameters
    Method("profiled-nuisances", "Constrained nuisance parameters profiled in a HistFactory model", "moderate",
           _p(packages=("pyhf", "cabinetry"),
              entrypoints=("ravel.physics.inference.constructed:build",
                           "ravel.physics.inference.model_construction:construct"),
              commands=("pyhf_exclude constructed", "pyhf_exclude likelihood"), modes=("search-statistics",)),
           ("correlation-declared", "pulls-within-limit"), escalation="correlation-bracketing"),
    Method("correlation-bracketing", "Evaluate fully correlated and independent assignments as endpoint sensitivity",
           "moderate", _p(packages=("pyhf", "cabinetry"),
                          entrypoints=("ravel.physics.inference.constructed:bracket_correlations",),
                          commands=("pyhf_exclude constructed",)),
           ("bracket-envelope",)),
    # error propagation
    Method("linear-propagation", "First-order propagation of the input covariance", "cheap",
           _p(packages=("numpy",), entrypoints=("ravel.physics.inference.propagation:propagate",),
              modes=("derived-quantities",)),
           ("correlation-known", "symmetric-errors", "linearity"), escalation="sampled-propagation"),
    Method("sampled-propagation", "Monte Carlo propagation with split-normal inputs for asymmetric errors",
           "moderate", _p(packages=("numpy",), entrypoints=("ravel.physics.inference.propagation:propagate",)),
           ("correlation-known", "mc-sample-precision"), escalation="propagation-correlation-bracketing"),
    Method("propagation-correlation-bracketing", "Propagation over the stated range of each unknown correlation, "
           "reporting the widest interval", "moderate",
           _p(packages=("numpy",), entrypoints=("ravel.physics.inference.propagation:propagate",)),
           ("bracket-envelope", "mc-sample-precision")),
    # combination
    Method("independent-combination", "Product of independent likelihoods", "cheap",
           _p(packages=("spey",), entrypoints=("ravel.physics.inference.simplified:combine",),
              commands=("pyhf_exclude simplified",)),
           ("independence-declared", "no-shared-parameters", "inputs-combined"), escalation="joint-likelihood"),
    Method("joint-likelihood", "One likelihood with shared parameters correlated by name", "moderate",
           _p(packages=("pyhf",), entrypoints=("ravel.physics.workspace_combination:combine",),
              modes=("workspace-combination-study",)),
           ("independence-declared", "shared-parameter-consistency", "inputs-combined")),
    # likelihood availability tiers
    Method("published-likelihood", "The analysis's published likelihood with the run's signal", "moderate",
           _p(packages=("pyhf", "jsonpatch"), entrypoints=("ravel.physics.pyhf_exclude:model_from_likelihood",
                                                           "ravel.validation.likelihood_appropriateness:assess"),
              commands=("pyhf_exclude likelihood",), modes=("published-model",)),
           ("published-appropriate", "limits-resolved"), escalation="simplified-likelihood"),
    Method("simplified-likelihood", "Simplified likelihood from the published background covariance", "cheap",
           _p(packages=("spey",), entrypoints=("ravel.physics.inference.simplified:from_document",),
              commands=("pyhf_exclude simplified",), modes=("search-statistics",)),
           ("covariance-sourced", "limits-resolved", "reference-limits-declared", "reference-limit-closure"),
           escalation="constructed-likelihood"),
    Method("constructed-likelihood", "HistFactory model constructed from published yields and their systematics",
           "moderate", _p(packages=("pyhf", "cabinetry"), entrypoints=("ravel.physics.inference.constructed:build",),
                          commands=("pyhf_exclude constructed",)),
           ("yields-and-registry", "builder-parity", "published-total-preserved", "limits-resolved",
            "reference-limits-declared", "reference-limit-closure"),
           escalation="counting"),
    Method("counting", "Single-bin counting per region (the most sensitive region, or exclusive regions combined)",
           "cheap", _p(packages=("pyhf",), entrypoints=("ravel.physics.pyhf_exclude:model_from_counting",),
                       commands=("pyhf_exclude counting", "pyhf_exclude counting --combined")),
           ("yields-available", "correlations-stated", "limits-resolved")),
    # limited MC statistics
    Method("mc-staterror", "Per-bin Gaussian MC-statistics term (Barlow-Beeston lite)", "cheap",
           _p(packages=("pyhf",), commands=("sa2json_native --mc-stat staterror",), modes=("search-statistics",)),
           ("mc-moments-available", "mc-statistics-modelled")),
    Method("mc-shapesys", "Per-sample Poisson-gamma MC-statistics term", "cheap",
           _p(packages=("pyhf",), commands=("sa2json_native --mc-stat shapesys",), modes=("search-statistics",)),
           ("mc-moments-available", "mc-statistics-modelled")),
    Method("finite-mc-model", "Exact finite-MC likelihood under a declared generator law", "expensive",
           _p(entrypoints=("ravel.physics.finite_mc_model:validate",), modes=("finite-mc",)),
           ("generator-law-declared", "mc-moments-available")),
    # look-elsewhere
    Method("local-significance", "Local significance at each tested hypothesis", "cheap",
           _p(packages=("pyhf",), modes=("search-statistics",)), ("local-claim",), escalation="trials-factor"),
    Method("trials-factor", "Global significance from upcrossings of the local test statistic along the scan",
           "cheap", _p(packages=("scipy",), entrypoints=("ravel.physics.inference.lee:global_significance",)),
           ("one-dimensional-scan", "upcrossings-observed")),
    Method("sidak-correction", "Sidak correction for independent tests", "cheap",
           _p(packages=("scipy",), entrypoints=("ravel.physics.inference.lee:sidak",)),
           ("independent-tests-declared",)),
    # closure, injection, coverage
    Method("signal-injection", "Asimov signal-injection and recovery", "cheap",
           _p(packages=("pyhf", "iminuit"), entrypoints=("ravel.physics.inference.model_checks:signal_injection",)),
           ("signal-injection",)),
    Method("validation-region-closure", "Background-only fit closure in validation regions", "cheap",
           _p(packages=("pyhf", "iminuit"), modes=("search-statistics",)),
           ("validation-regions-present", "validation-closure")),
    Method("coverage-toys", "False-exclusion rate of the limit at the true strength from toys", "expensive",
           _p(packages=("pyhf",), entrypoints=("ravel.physics.inference.model_checks:exclusion_coverage",
                                               "ravel.validation.statistical_calibration:known_background_poisson_coverage")),
           ("coverage-at-truth",)),
    # parameter estimation
    Method("quadratic-errors", "Quadratic (HESSE) errors at the best fit", "cheap",
           _p(packages=("pyhf", "iminuit"), entrypoints=("ravel.physics.inference.profile:intervals",)),
           ("asymptotic-interval-regime", "parabolic-profile"), escalation="profile-likelihood"),
    Method("profile-likelihood", "Profile-likelihood interval with verified crossings", "moderate",
           _p(packages=("pyhf", "scipy"), entrypoints=("ravel.physics.inference.profile:intervals",
                                                       "ravel.physics.inference.intervals:allowed_regions"),
              modes=("prescribed-statistic",)),
           ("asymptotic-interval-regime", "interval-resolved", "away-from-boundary")),
    Method("toy-neyman", "Toy Neyman construction for intervals near a boundary", "expensive",
           _p(packages=("iminuit",), modes=("differential-likelihood",)), ("interval-resolved",)),
    # efficiency and acceptance
    Method("normal-binomial", "Normal approximation of the binomial efficiency error", "cheap",
           _p(packages=("scipy",), entrypoints=("ravel.physics.inference.efficiency:interval",)),
           ("unweighted-counts", "normal-approximation"), escalation="wilson-binomial"),
    Method("wilson-binomial", "Wilson score interval", "cheap",
           _p(packages=("scipy",), entrypoints=("ravel.physics.inference.efficiency:interval",)),
           ("unweighted-counts",), escalation="clopper-pearson"),
    Method("clopper-pearson", "Exact Clopper-Pearson interval", "cheap",
           _p(packages=("scipy",), entrypoints=("ravel.physics.inference.efficiency:interval",)),
           ("unweighted-counts",), escalation="weighted-efficiency"),
    Method("weighted-efficiency", "Weighted efficiency with effective entries from sumw2", "cheap",
           _p(packages=("numpy",), entrypoints=("ravel.physics.inference.efficiency:weighted",)),
           ("nonnegative-weights",)),
)}

SITUATIONS = (
    Situation("derived-quantity-propagation", "Error propagation through derived quantities",
              "derived quantities computed from inputs that carry uncertainties", _detect_derived,
              ("linear-propagation", "sampled-propagation", "propagation-correlation-bracketing"),
              {"method": "propagation-correlation-bracketing", "outcome": "qualified",
               "qualification": "input correlations unknown; the widest interval over the stated correlation "
                                "range is reported"},
              references=("conv:published-information",), facts=("derived",)),
    Situation("systematic-nuisances", "Systematic uncertainties as nuisance parameters",
              "a systematics breakdown or background uncertainties that enter the statistical model",
              _detect_systematics, ("profiled-nuisances", "correlation-bracketing"),
              {"method": "counting", "outcome": "qualified",
               "qualification": "the correlation of systematic sources across regions is unknown and not bracketed; "
                                "the most sensitive single region is used"},
              references=("conv:published-information", "conv:asimov-profile"), facts=("systematics",)),
    Situation("low-counts", "Low counts and asymptotic breakdown in an exclusion",
              "an exclusion from main bins with fewer than five observed or expected counts", _detect_low_counts,
              ("asymptotic-cls", "toy-cls", "exact-count-calibration"),
              {"method": "asymptotic-cls", "outcome": "qualified",
               "qualification": "small-count regime: the asymptotic CLs calibration is not verified by toys"},
              references=("conv:asimov-profile",), facts=("deliverables", "bins")),
    Situation("low-count-significance", "Low counts in a discovery significance",
              "a discovery significance from main bins with fewer than five observed or expected counts",
              _detect_low_count_significance, ("asymptotic-significance", "toy-significance"),
              {"method": "asymptotic-significance", "outcome": "qualified",
               "qualification": "small-count regime: the asymptotic discovery significance is not verified by toys"},
              references=("conv:discovery",), facts=("deliverables", "bins")),
    Situation("combination", "Combination of channels or analyses",
              "two or more inputs to combine, possibly sharing systematic parameters", _detect_combination,
              ("independent-combination", "joint-likelihood"),
              {"method": None, "outcome": "qualified",
               "qualification": "the inputs are not combined; the most sensitive single input is quoted"},
              references=("conv:published-information",), facts=("combination",)),
    Situation("likelihood-availability", "Likelihood availability tier",
              "what the analysis published: full likelihood, background covariance, or per-region yields",
              _detect_likelihood,
              ("published-likelihood", "simplified-likelihood", "constructed-likelihood", "counting"),
              {"method": None, "outcome": "held",
               "qualification": "no statistical model is available; no limit is delivered"},
              references=("conv:published-information", "conv:statistic-policy"), facts=("likelihood",)),
    Situation("limited-mc-statistics", "Limited Monte Carlo statistics",
              "MC-predicted bins with a large relative statistical uncertainty or few effective entries",
              _detect_mc, ("mc-staterror", "mc-shapesys", "finite-mc-model"),
              {"method": None, "outcome": "qualified",
               "qualification": "MC statistical uncertainty not modelled in the flagged bins"},
              facts=("bins", "mc_statistics")),
    Situation("look-elsewhere", "Look-elsewhere effect in scans",
              "a significance reported over two or more tested hypotheses", _detect_lee,
              ("local-significance", "trials-factor", "sidak-correction"),
              {"method": "local-significance", "outcome": "qualified",
               "qualification": "local significance; the global significance over the scanned hypotheses is not "
                                "evaluated"},
              references=("conv:discovery",), facts=("deliverables", "scan")),
    Situation("model-validation", "Closure, signal injection and coverage",
              "a statistical model constructed or supplied here rather than published, or a fitted parameter",
              _detect_validation, ("signal-injection", "validation-region-closure", "coverage-toys"),
              {"method": None, "outcome": "qualified",
               "qualification": "closure, signal injection and coverage are not evaluated"},
              references=("conv:asimov-profile",), facts=("model_origin", "deliverables")),
    Situation("parameter-estimation", "Parameter estimation with profile intervals",
              "a request to estimate (fit, measure) a parameter", _detect_estimation,
              ("quadratic-errors", "profile-likelihood", "toy-neyman"),
              {"method": "profile-likelihood", "outcome": "qualified",
               "qualification": "profile-likelihood interval near a boundary; its coverage is not verified"},
              references=("conv:asimov-profile",), facts=("deliverables", "estimation")),
    Situation("efficiency-acceptance", "Efficiency and acceptance uncertainties",
              "efficiencies or acceptances computed from selected and generated entries", _detect_efficiency,
              ("normal-binomial", "wilson-binomial", "clopper-pearson", "weighted-efficiency"),
              {"method": "clopper-pearson", "outcome": "qualified", "qualification": "conservative exact interval"},
              facts=("efficiencies",)),
)
SITUATION_IDS = tuple(s.id for s in SITUATIONS)
# The likelihood-availability methods are the statistical-mode ladder (stat_mode_decision.LADDER).
STAT_MODE_OF_METHOD = {"published-likelihood": "published-likelihood", "simplified-likelihood": "simplified-likelihood",
                       "constructed-likelihood": "constructed-likelihood", "counting": "best-sr-counting"}
_BY_ID = {s.id: s for s in SITUATIONS}


def situation(identifier) -> Situation:
    try:
        return _BY_ID[identifier]
    except KeyError:
        raise KeyError(f"unknown statistics situation {identifier!r}") from None


# --------------------------------------------------------------------------- provider resolution

def _installed_version(package):
    from importlib import metadata
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _pinned():
    """Pinned versions of the host packages, from the installed distribution's own metadata."""
    from importlib import metadata
    pins = {}
    try:
        requirements = metadata.requires("ravel-hep") or []
    except metadata.PackageNotFoundError:
        requirements = []
    for row in requirements:
        if ";" in row:
            continue
        name, sep, version = row.partition("==")
        if sep:
            pins[name.split("[")[0].strip().lower()] = version.strip()
    return pins


def provider_status(method_id, *, resolve_entrypoints=False) -> dict:
    """Whether a method's packages are installed (at their pin when one is declared)."""
    method = METHODS[method_id]
    pins = _pinned()
    packages = {}
    available = True
    for package in method.provider.packages:
        version = _installed_version(package)
        wanted = pins.get(package.lower())
        ok = version is not None and (wanted is None or version == wanted)
        packages[package] = {"installed": version, "pinned": wanted, "ok": ok}
        available &= ok
    status = {"available": bool(available), "packages": packages}
    if resolve_entrypoints:
        status["entrypoints"] = {e: _resolve(e) for e in method.provider.entrypoints}
        status["available"] = status["available"] and all(status["entrypoints"].values())
    return status


def _resolve(entrypoint) -> bool:
    import importlib
    module, _, name = entrypoint.partition(":")
    try:
        return callable(getattr(importlib.import_module(module), name))
    except (ImportError, AttributeError):
        return False


# --------------------------------------------------------------------------- facts

FACT_KEYS = ("deliverables", "likelihood", "bins", "mc_statistics", "mc_generator_law", "systematics",
             "combination", "scan", "derived", "efficiencies", "estimation", "model_origin", "sources")


def facts_errors(facts) -> list[str]:
    if not isinstance(facts, dict):
        return ["facts must be an object"]
    errors = []
    if facts.get("schema_version") != SCHEMA_VERSION or facts.get("kind") != FACTS_KIND:
        errors.append(f"facts must be kind {FACTS_KIND!r} schema_version {SCHEMA_VERSION}")
    unknown = set(facts) - set(FACT_KEYS) - {"schema_version", "kind"}
    if unknown:
        errors.append(f"facts carry unknown keys {sorted(unknown)}")
    deliverables = facts.get("deliverables", [])
    if not isinstance(deliverables, list) or set(deliverables) - set(DELIVERABLES):
        errors.append(f"deliverables must be a list drawn from {DELIVERABLES}")
    if facts.get("model_origin") not in (None, *MODEL_ORIGINS):
        errors.append(f"model_origin must be one of {MODEL_ORIGINS}")
    if facts.get("mc_statistics") not in (None, "staterror", "shapesys", "none"):
        errors.append("mc_statistics must be staterror, shapesys or none")
    for name in ("bins", "systematics", "derived", "efficiencies"):
        if name in facts and not (isinstance(facts[name], list) and all(isinstance(r, dict) for r in facts[name])):
            errors.append(f"{name} must be a list of objects")
    for row in facts.get("systematics") or ():
        if isinstance(row, dict) and row.get("correlation") not in (None, *CORRELATIONS):
            errors.append(f"systematic {row.get('name')!r} has correlation {row.get('correlation')!r}")
    for row in facts.get("bins") or ():
        if isinstance(row, dict):
            for key in ("observed", "background", "signal", "background_uncertainty"):
                if row.get(key) is not None and not (_finite(row[key]) and row[key] >= 0):
                    errors.append(f"bin {row.get('channel')}[{row.get('bin')}] {key} must be finite and nonnegative")
            mc = row.get("mc")
            if mc not in (None, "absent") and not (isinstance(mc, dict) and _finite(mc.get("sumw"))
                                                   and _finite(mc.get("sumw2")) and mc["sumw2"] >= 0):
                errors.append(f"bin {row.get('channel')}[{row.get('bin')}] mc must be absent or sumw and sumw2")
    scan = facts.get("scan")
    if scan is not None and not (isinstance(scan, dict) and isinstance(scan.get("hypotheses"), int)
                                 and scan["hypotheses"] >= 1):
        errors.append("scan must state its number of tested hypotheses")
    elif isinstance(scan, dict) and scan.get("dimensions") is not None and not (
            type(scan["dimensions"]) is int and scan["dimensions"] >= 1):
        errors.append("scan dimensions must be a positive integer when stated")
    return errors


def make_facts(**values) -> dict:
    facts = {"schema_version": SCHEMA_VERSION, "kind": FACTS_KIND,
             **{k: deepcopy(v) for k, v in values.items() if v is not None}}
    errors = facts_errors(facts)
    if errors:
        raise StatisticsRecordError(errors)
    return facts


def facts_from_model(model, data, *, origin, deliverables=("exclusion",), systematics_correlation="declared",
                     likelihood=None, mc_statistics=None):
    """Facts read from a pyhf model and its data: main-bin counts, background-only expectation, modifiers.

    In a HistFactory model a modifier name is one parameter in every bin it appears in, so the
    correlation of every source is declared by construction (``systematics_correlation``).
    """
    import numpy as np
    config = model.config
    pars = np.asarray(config.suggested_init(), float)
    if config.poi_index is not None:
        pars[config.poi_index] = 0.0
    background = np.asarray(model.expected_actualdata(pars), float)
    observed = np.asarray(data, float)[:config.nmaindata]
    signal = None
    if config.poi_index is not None:
        unit = np.asarray(config.suggested_init(), float)
        unit[config.poi_index] = 1.0
        signal = np.asarray(model.expected_actualdata(unit), float) - background
    bins, offset = [], 0
    for channel in config.channels:
        for index in range(config.channel_nbins[channel]):
            row = {"channel": channel, "bin": index, "observed": float(observed[offset]),
                   "background": float(max(background[offset], 0.0))}
            if signal is not None:
                row["signal"] = float(max(signal[offset], 0.0))
            bins.append(row)
            offset += 1
    types = {}
    for channel in model.spec.get("channels", []):
        for sample in channel.get("samples", []):
            for modifier in sample.get("modifiers", []):
                types.setdefault(modifier["name"], set()).add(modifier["type"])
    if mc_statistics is None:
        kinds = {t for v in types.values() for t in v}
        mc_statistics = "staterror" if "staterror" in kinds else "shapesys" if "shapesys" in kinds else "none"
    poi = config.poi_name
    sources = [{"name": name, "types": sorted(kinds), "correlation": systematics_correlation}
               for name, kinds in sorted(types.items())
               if name != poi and kinds & {"normsys", "histosys", "lumi"}]
    return make_facts(deliverables=list(deliverables), model_origin=origin, bins=bins, mc_statistics=mc_statistics,
                      systematics=sources or None, likelihood=likelihood)


# --------------------------------------------------------------------------- assess / decide / verify

def _evaluate(check_id, facts, evidence):
    check = CHECKS[check_id]
    try:
        outcome = check.evaluate(facts, evidence or {})
    except (TypeError, ValueError, KeyError, AttributeError, ZeroDivisionError) as exc:
        outcome = _result("missing", f"the check could not read its inputs: {type(exc).__name__}: {exc}")
    return {"check": check_id, "stage": check.stage, "on_fail": check.on_fail, **outcome}


def assess(facts, *, availability=None) -> dict:
    """Detected situations, each method's facts-stage checks and availability, and the cost-aware default."""
    errors = facts_errors(facts)
    if errors:
        raise StatisticsRecordError(errors)
    availability = availability or {}
    situations = []
    for item in SITUATIONS:
        evidence = item.detect(facts)
        if evidence is None:
            continue
        methods, default = [], None
        for method_id in item.methods:
            method = METHODS[method_id]
            status = availability.get(method_id)
            if status is None:
                status = provider_status(method_id)
            prechecks = [_evaluate(c, facts, {}) for c in method.checks if CHECKS[c].stage == "facts"]
            # A qualification is retained by verify, not used to force an inapplicable fallback.
            blocking = [p for p in prechecks if p["status"] != "pass" and p["on_fail"] != "qualify"]
            inapplicable = method.applies(facts) if method.applies else None
            row = {"method": method_id, "cost": method.cost, "available": bool(status["available"]),
                   **({"unavailable_reason": status["reason"]} if not status["available"] and status.get("reason")
                      else {}),
                   **({"inapplicable": inapplicable} if inapplicable else {}),
                   "provider": method.provider.as_dict(), "prechecks": prechecks,
                   "result_checks": [c for c in method.checks if CHECKS[c].stage == "result"],
                   "eligible": bool(status["available"]) and not blocking and not inapplicable}
            if not row["available"]:
                row["passed_over"] = status.get("reason") or "provider not installed at its pinned version"
            elif inapplicable:
                row["passed_over"] = inapplicable
            elif blocking:
                row["passed_over"] = "; ".join(f"{p['check']}: {p['detail']}" for p in blocking)
            methods.append(row)
            if default is None and row["eligible"]:
                default = method_id
        situations.append({"situation": item.id, "title": item.title, "evidence": evidence, "methods": methods,
                           "default": default, "fallback": dict(item.fallback)})
    body = {"schema_version": SCHEMA_VERSION, "kind": ASSESSMENT_KIND, "catalogue_sha256": catalogue_sha256(),
            "facts_sha256": digest(facts), "situations": situations}
    return body


def _method_rank(item, method_id):
    return list(item.methods).index(method_id) if method_id in item.methods else len(item.methods)


def decide(assessment, choices=None) -> dict:
    """The decision record: the cost-aware default per detected situation, or a seat's justified choice.

    ``choices`` is ``{situation: {"method": id, "justification": text}}``. A seat may choose any method
    the situation lists (a cheaper one than the default is allowed with its justification; its failed
    checks then qualify the result) or the fallback; never a method of another situation.
    """
    choices = choices or {}
    errors = []
    if not isinstance(choices, dict):
        raise StatisticsRecordError(["choices must be an object keyed by situation"])
    detected = {row["situation"]: row for row in assessment["situations"]}
    unknown = sorted(set(choices) - set(detected))
    if unknown:
        errors.append("choices name situations that were not detected: " + ", ".join(unknown))
    rows = []
    for situation_id, row in detected.items():
        item = situation(situation_id)
        choice = choices.get(situation_id)
        if choice is not None:
            if not (isinstance(choice, dict) and set(choice) <= {"method", "justification"}
                    and isinstance(choice.get("justification"), str) and choice["justification"].strip()):
                errors.append(f"{situation_id}: a seat's choice needs a method and a nonblank justification")
                continue
            method = choice.get("method")
            fallback = item.fallback.get("method")
            if method not in item.methods and method != "fallback":
                errors.append(f"{situation_id}: {method!r} is not a method of this situation")
                continue
            entry = {"situation": situation_id, "method": None if method == "fallback" else method,
                     "origin": "fallback" if method == "fallback" else "seat", "seat": True,
                     "justification": choice["justification"].strip()}
            if method == "fallback":
                entry["method"] = fallback
                entry["qualification"] = item.fallback["qualification"]
            rows.append(entry)
            continue
        if row["default"] is not None:
            origin = "default"
            first = item.methods[0]
            if row["default"] != first:
                origin = "escalation"
            entry = {"situation": situation_id, "method": row["default"], "origin": origin, "seat": False,
                     "justification": ("the cheapest available method whose input checks pass"
                                       if origin == "default" else
                                       "cheaper methods are passed over: " + "; ".join(
                                           f"{m['method']}: {m.get('passed_over')}" for m in row["methods"]
                                           if _method_rank(item, m["method"]) < _method_rank(item, row["default"])))}
        else:
            entry = {"situation": situation_id, "method": item.fallback.get("method"), "origin": "fallback",
                     "seat": False,
                     "justification": "no listed method is available with passing input checks: " + "; ".join(
                         f"{m['method']}: {m.get('passed_over')}" for m in row["methods"]),
                     "qualification": item.fallback["qualification"]}
        rows.append(entry)
    if errors:
        raise StatisticsRecordError(errors)
    return {"schema_version": SCHEMA_VERSION, "kind": DECISION_KIND, "assessment_sha256": digest(assessment),
            "choices": rows}


def apply_escalation(decision, situation_id, method_id, check_id) -> dict:
    """The decision with one situation escalated along its method's catalogue edge after a failed check.

    Only an engine-chosen method escalates (a seat's choice stands; its failed checks qualify the
    result). The step is recorded in the row's ``escalations`` chain so ``audit`` can replay it.
    """
    item = situation(situation_id)
    changed = deepcopy(decision)
    for row in changed["choices"]:
        if row["situation"] != situation_id:
            continue
        current = METHODS.get(row["method"])
        check = CHECKS.get(check_id)
        if row.get("seat"):
            raise StatisticsRecordError([f"{situation_id}: a seat's choice is not escalated"])
        if current is None or current.escalation != method_id or method_id not in item.methods:
            raise StatisticsRecordError([f"{situation_id}: {method_id!r} is not the escalation of {row['method']!r}"])
        if check is None or check_id not in current.checks or check.on_fail != "escalate":
            raise StatisticsRecordError([f"{situation_id}: {check_id!r} is not an escalating check of "
                                         f"{row['method']!r}"])
        chain = list(row.get("escalations") or ()) + [{"from": row["method"], "to": method_id, "check": check_id}]
        row.update(method=method_id, origin="escalation", escalations=chain,
                   justification=f"{check_id} failed for {chain[-1]['from']}; escalated to {method_id}")
        return changed
    raise StatisticsRecordError([f"{situation_id} is not in the decision"])


def _endpoint_domain_errors(facts, bracket):
    """The finite assignment census, resolved roots and selected endpoint match the facts."""
    import itertools
    from .constructed import BRACKET_CORRELATIONS, MAX_BRACKETED
    if not isinstance(bracket, dict):
        return ["correlation endpoint sensitivity requires an evaluated domain record"]
    sources = bracket.get("sources")
    unknown = [row.get("name") for row in facts.get("systematics") or []
               if isinstance(row, dict) and row.get("correlation") == "unknown"]
    if (not isinstance(sources, list) or not sources or len(sources) > MAX_BRACKETED
            or any(not isinstance(name, str) for name in sources)
            or any(not isinstance(name, str) for name in unknown)
            or len(set(sources)) != len(sources) or sorted(sources) != sorted(unknown)):
        return ["the endpoint source census must equal the facts' unknown correlations"]
    expected_domain = {"kind": "finite-assignments", "coverage": "endpoint-sensitivity",
                       "assignments": list(BRACKET_CORRELATIONS), "sources": sources,
                       "continuous_envelope": False}
    if bracket.get("domain") != expected_domain:
        return ["correlation endpoint sensitivity requires its evaluated domain record"]
    assignments = {','.join(f'{name}={value}' for name, value in zip(sources, corner)): dict(zip(sources, corner))
                   for corner in itertools.product(BRACKET_CORRELATIONS, repeat=len(sources))}
    variants = bracket.get("variants") or {}
    statuses = bracket.get("expected_median_status") or {}
    if (not isinstance(variants, dict) or not isinstance(statuses, dict)
            or set(variants) != set(assignments) or set(statuses) != set(assignments)):
        return ["the endpoint census requires every assignment and its numerical status"]
    if any(status != "resolved" for status in statuses.values()):
        return ["each endpoint requires a resolved expected median limit"]
    selected = bracket.get("reported_variant")
    if (bracket.get("rule") != "max" or selected not in assignments
            or bracket.get("reported_assignment") != assignments[selected]
            or bracket.get("reported") != variants[selected]):
        return ["the reported endpoint must bind its assignment and weakest-expected selection rule"]
    return []


def verify(facts, decision, evidence) -> dict:
    """Every check the chosen methods owe, evaluated on the facts and the result evidence, and the outcome."""
    rows, qualifications, holds, escalations = [], [], [], []
    for choice in decision["choices"]:
        item = situation(choice["situation"])
        method_id = choice.get("method")
        if method_id is None:
            label = choice.get("qualification") or item.fallback["qualification"]
            target = holds if item.fallback.get("outcome") == "held" else qualifications
            target.append({"situation": item.id, "label": label})
            continue
        if choice.get("qualification"):
            qualifications.append({"situation": item.id, "label": choice["qualification"]})
        if method_id == "correlation-bracketing":
            qualifications.append({"situation": item.id, "label":
                "correlation endpoint sensitivity: the weakest expected limit among fully correlated and "
                "independent per-region assignments; continuous and intermediate correlation coverage "
                "requires a separate domain assessment"})
            bracket = (evidence or {}).get("correlation_bracket") or {}
            holds.extend({"situation": item.id, "label": problem}
                         for problem in _endpoint_domain_errors(facts, bracket))
        method = METHODS[method_id]
        for check_id in method.checks:
            result = _evaluate(check_id, facts, evidence)
            result.update(situation=item.id, method=method_id)
            rows.append(result)
            if result["status"] == "pass":
                continue
            check = CHECKS[check_id]
            if result["status"] == "missing" and check.stage == "result":
                holds.append({"situation": item.id, "check": check_id,
                              "label": f"validity check {check_id} did not run: {result['detail']}"})
                continue
            if check.on_fail == "hold":
                holds.append({"situation": item.id, "check": check_id, "label": check.qualification})
            elif check.on_fail == "escalate" and method.escalation and choice["origin"] in ("default", "escalation"):
                escalations.append({"situation": item.id, "from": method_id, "to": method.escalation,
                                    "check": check_id})
                qualifications.append({"situation": item.id, "label": check.qualification})
            else:
                qualifications.append({"situation": item.id, "label": check.qualification})
    outcome = "held" if holds else "qualified" if qualifications else "valid"
    unique = []
    for row in qualifications:
        if row not in unique:
            unique.append(row)
    return {"schema_version": SCHEMA_VERSION, "kind": VALIDITY_KIND, "decision_sha256": digest(decision),
            "evidence_sha256": digest(evidence or {}), "checks": rows, "outcome": outcome,
            "qualifications": unique, "holds": holds, "escalations": escalations}


def drive(facts, run, *, choices=None, availability=None, max_rounds=4) -> dict:
    """Run the decided methods and escalate automatically while a failed check calls for it.

    ``run(situation_id, method_id, evidence)`` executes one method and returns the evidence it
    produced, merged into the record's evidence. After each round every escalation the validity
    record recommends is applied when the stronger method is available and applies, and only those
    situations run again. A seat's choice is never escalated; a method that cannot run returns no evidence and
    its owed checks then report that they did not run. Returns the statistics record.
    """
    assessment = assess(facts, availability=availability)
    decision = decide(assessment, choices)
    available = {row["method"]: row["available"] and not row.get("inapplicable")
                 for s in assessment["situations"] for row in s["methods"]}
    evidence = {}
    pending = [row for row in decision["choices"] if row["method"] is not None]
    for _ in range(max_rounds):
        for row in pending:
            produced = run(row["situation"], row["method"], deepcopy(evidence))
            if produced:
                evidence.update(deepcopy(produced))
        validity = verify(facts, decision, evidence)
        moves = [m for m in validity["escalations"] if available.get(m["to"])]
        if not moves:
            break
        pending = []
        for move in moves:
            decision = apply_escalation(decision, move["situation"], move["to"], move["check"])
            pending.append(next(r for r in decision["choices"] if r["situation"] == move["situation"]))
    return record(facts, evidence, availability=availability, decision=decision)


def record(facts, evidence, *, choices=None, availability=None, decision=None) -> dict:
    """The complete statistics record attached to a result: facts, assessment, decision, evidence, validity."""
    assessment = assess(facts, availability=availability)
    decision = decision if decision is not None else decide(assessment, choices)
    validity = verify(facts, decision, evidence)
    return {"schema_version": SCHEMA_VERSION, "kind": BLOCK_KIND, "catalogue_sha256": catalogue_sha256(),
            "facts": deepcopy(facts), "assessment": assessment, "decision": decision,
            "evidence": deepcopy(evidence or {}), "validity": validity}


def audit(block, *, availability=None) -> list[str]:
    """Recompute a statistics record from its facts and evidence; every disagreement is an error.

    The record's own assessment, decision provenance and validity are never trusted: the
    assessment and validity are recomputed, the decision must follow from the recomputed
    assessment (defaults) or be a justified seat choice the catalogue admits. A record whose
    structure cannot be read is refused with that reason, never an exception.
    """
    try:
        return _audit(block, availability=availability)
    except (TypeError, ValueError, KeyError, AttributeError, IndexError) as exc:
        return [f"the statistics record is malformed: {type(exc).__name__}: {exc}"[:500]]


def _audit(block, *, availability=None) -> list[str]:
    if not isinstance(block, dict) or block.get("kind") != BLOCK_KIND or block.get("schema_version") != SCHEMA_VERSION:
        return [f"the statistics record must be kind {BLOCK_KIND!r} schema_version {SCHEMA_VERSION}"]
    errors = []
    if block.get("catalogue_sha256") != catalogue_sha256():
        errors.append("the statistics record was made with another catalogue version")
    facts, evidence, decision = block.get("facts"), block.get("evidence"), block.get("decision")
    problems = facts_errors(facts)
    if problems:
        return errors + problems
    if not isinstance(evidence, dict):
        return errors + ["the statistics record carries no evidence object"]
    recorded = block.get("assessment") or {}
    if availability is None:
        # The record's availability claims are used (it may come from another host), except that a method
        # claimed unavailable while it is installed here cannot excuse passing it over.
        availability = {}
        for s in recorded.get("situations") or ():
            for row in s.get("methods") or ():
                if not (isinstance(row, dict) and row.get("method") in METHODS and "available" in row):
                    continue
                reason = row.get("unavailable_reason")
                if row["available"] is False and provider_status(row["method"])["available"]:
                    refused = [r for r in (evidence or {}).get("budget_refusals") or ()
                               if isinstance(r, dict) and r.get("method") == row["method"]] \
                        if isinstance(evidence, dict) else []
                    if not (isinstance(reason, str) and reason.startswith("budget") and refused):
                        errors.append(f"{row['method']} is recorded unavailable but is installed at its pinned "
                                      "version, and no budget refusal of it is recorded")
                availability[row["method"]] = {"available": bool(row["available"]),
                                               **({"reason": reason} if reason else {})}
    assessment = assess(facts, availability=availability)
    if recorded != assessment:
        errors.append("the recorded assessment does not follow from the recorded facts")
    if not isinstance(decision, dict) or decision.get("kind") != DECISION_KIND:
        return errors + ["the statistics record carries no decision"]
    if decision.get("assessment_sha256") != digest(assessment):
        errors.append("the decision was made on another assessment")
    detected = {row["situation"] for row in assessment["situations"]}
    chosen = [row.get("situation") for row in decision.get("choices") or ()]
    if sorted(chosen) != sorted(detected) or len(set(chosen)) != len(chosen):
        errors.append("the decision must choose exactly once for every detected situation")
    seat = {row["situation"]: {"method": "fallback" if row.get("origin") == "fallback" else row.get("method"),
                               "justification": row.get("justification")}
            for row in decision.get("choices") or () if isinstance(row, dict) and row.get("seat") is True}
    try:
        expected = decide(assessment, seat)
    except StatisticsRecordError as exc:
        return errors + exc.errors
    replayed = _replay_escalations(expected, decision)
    if replayed is None:
        errors.append("the decision is neither the default, a justified seat choice nor a recorded escalation")
    else:
        for want, have in zip(sorted(replayed["choices"], key=lambda r: r["situation"]),
                              sorted(decision.get("choices") or (), key=lambda r: r.get("situation"))):
            fields = ("situation", "method", "origin", "seat", "escalations")
            if any(want.get(k) != have.get(k) for k in fields):
                errors.append(f"{want['situation']}: recorded choice {have.get('method')!r} ({have.get('origin')}) "
                              f"does not follow from the assessment ({want.get('method')!r}, {want.get('origin')})")
    usable = {(s["situation"], m["method"]): m["available"] and not m.get("inapplicable")
              for s in assessment["situations"] for m in s["methods"]}
    for row in decision.get("choices") or ():
        for step in row.get("escalations") or ():
            if not isinstance(step, dict) or step.get("check") not in CHECKS:
                continue
            if not usable.get((row.get("situation"), step.get("to"))):
                errors.append(f"{row.get('situation')}: the escalation to {step.get('to')} names a method that is "
                              "unavailable or does not apply to these facts")
            found = _evaluate(step["check"], facts, evidence)
            if found["status"] != "fail":
                errors.append(f"{row.get('situation')}: the escalation from {step.get('from')} cites {step['check']}, "
                              f"which does not fail on the recorded evidence ({found['status']})")
    validity = verify(facts, decision, evidence)
    if block.get("validity") != validity:
        errors.append("the recorded validity does not follow from the recorded evidence")
    return errors


def result_facts_errors(block, counts=None) -> list[str]:
    """Why a record does not assess the result it is attached to (empty when it does).

    The facts must name a statistical deliverable and carry main-bin counts, so an empty description
    is not an assessment. ``counts`` maps every delivered region to its observed count;
    each count equals the sum of that region's uniquely identified main bins.
    """
    facts = (block or {}).get("facts") or {}
    problems = []
    if not set(facts.get("deliverables") or ()) & {"exclusion", "discovery", "estimation"}:
        problems.append("its facts name no statistical deliverable of this step")
    bins = [b for b in facts.get("bins") or () if isinstance(b, dict)]
    if not bins:
        problems.append("its facts carry no main-bin counts: nothing was assessed")
    observed, identities = {}, set()
    for row in bins:
        name, index = row.get("channel"), row.get("bin")
        identity = (name, index)
        if identity in identities:
            problems.append(f"its facts repeat region {name} bin {index}")
        identities.add(identity)
        observed.setdefault(name, []).append(row.get("observed"))
    for name, count in sorted((counts or {}).items()):
        if name not in observed:
            problems.append(f"its facts omit delivered region {name}")
            continue
        values = observed[name]
        if not _finite(count) or not all(_finite(value) for value in values):
            problems.append(f"region {name} requires finite observed counts in the result and its facts")
            continue
        total = math.fsum(values)
        if total != count:
            problems.append(f"its facts give region {name} {total} observed events, the result {count}")
    return problems


def result_document_errors(block, document) -> list[str]:
    """Bind a delivered region census to its recorded main-bin counts."""
    regions = document.get("per_sr")
    if regions is None:
        return result_facts_errors(block)
    if not isinstance(regions, dict) or not regions:
        return ["the delivered per_sr census requires a nonempty region mapping"]
    if any(not isinstance(name, str) or not isinstance(row, dict) for name, row in regions.items()):
        return ["each delivered region requires a name and count record"]
    return result_facts_errors(block, {name: row.get("n") for name, row in regions.items()})


def _replay_escalations(expected, decision):
    """The expected decision with every recorded escalation chain applied, when each step is admissible."""
    replayed = deepcopy(expected)
    for row in decision.get("choices") or ():
        for step in row.get("escalations") or ():
            current = next((r for r in replayed["choices"] if r["situation"] == row.get("situation")), None)
            if current is None or not isinstance(step, dict) or current["method"] != step.get("from"):
                return None
            try:
                replayed = apply_escalation(replayed, row["situation"], step.get("to"), step.get("check"))
            except StatisticsRecordError:
                return None
    return replayed


def labels(block) -> list[str]:
    """The qualification and hold labels a delivery must show for a statistics record."""
    validity = (block or {}).get("validity") or {}
    out = []
    for row in [*(validity.get("qualifications") or ()), *(validity.get("holds") or ())]:
        if isinstance(row, dict) and row.get("label") and row["label"] not in out:
            out.append(row["label"])
    return out


# --------------------------------------------------------------------------- export

def export(*, resolve=False) -> dict:
    """The catalogue as data for deciding seats (no callables)."""
    document = {
        "schema_version": SCHEMA_VERSION, "kind": CATALOGUE_KIND,
        "purpose": "Statistics situations RAVEL detects in its inputs, the installed methods that treat each, the "
                   "validity checks each method owes and the qualified fallback. The default is the cheapest "
                   "available method whose input checks pass; a seat may choose another listed method with a "
                   "justification. Passing the checks does not certify a result.",
        "outcomes": {"valid": "every owed check passed", "qualified": "the result is delivered with the listed labels",
                     "held": "the result is not delivered until the hold is resolved"},
        "situations": [s.as_dict() for s in SITUATIONS],
        "methods": {k: v.as_dict() for k, v in sorted(METHODS.items())},
        "checks": {k: v.as_dict() for k, v in sorted(CHECKS.items())},
    }
    if resolve:
        document["providers"] = {k: provider_status(k, resolve_entrypoints=True) for k in sorted(METHODS)}
    return document


_DIGEST = {}


def catalogue_sha256() -> str:
    if "value" not in _DIGEST:
        _DIGEST["value"] = digest(export())
    return _DIGEST["value"]


def summary() -> list[dict]:
    """A compact view for a seat's context: situation, what reveals it, methods with cost, checks and fallback."""
    rows = []
    for item in SITUATIONS:
        rows.append({"situation": item.id, "revealed_by": item.revealed_by,
                     "methods": [{"method": m, "cost": METHODS[m].cost,
                                  "checks": list(METHODS[m].checks),
                                  "provider": [*METHODS[m].provider.commands[:2], *METHODS[m].provider.modes[:1],
                                               *METHODS[m].provider.entrypoints[:1]]}
                                 for m in item.methods],
                     "fallback": item.fallback})
    return rows


def _consistency_errors() -> list[str]:
    """Catalogue self-consistency: every reference resolves inside the catalogue."""
    errors = []
    for item in SITUATIONS:
        for method_id in item.methods:
            if method_id not in METHODS:
                errors.append(f"{item.id}: unknown method {method_id}")
        fallback = item.fallback.get("method")
        if fallback is not None and fallback not in METHODS:
            errors.append(f"{item.id}: unknown fallback method {fallback}")
        if not item.fallback.get("qualification"):
            errors.append(f"{item.id}: the fallback needs its qualification")
        if item.fallback.get("outcome") not in ("qualified", "held"):
            errors.append(f"{item.id}: the fallback needs its outcome")
    for method in METHODS.values():
        if method.cost not in COSTS:
            errors.append(f"{method.id}: cost {method.cost}")
        for check_id in method.checks:
            if check_id not in CHECKS:
                errors.append(f"{method.id}: unknown check {check_id}")
        if method.escalation is not None and method.escalation not in METHODS:
            errors.append(f"{method.id}: unknown escalation {method.escalation}")
        if not (method.provider.packages or method.provider.entrypoints or method.provider.modes):
            errors.append(f"{method.id}: no provider")
        if method.applies is not None and not (method.applies.__doc__ or "").strip():
            errors.append(f"{method.id}: its applicability predicate states no condition")
    for check in CHECKS.values():
        if check.stage not in STAGES or check.on_fail not in ON_FAIL:
            errors.append(f"{check.id}: stage {check.stage} or on_fail {check.on_fail}")
    return errors


# --------------------------------------------------------------------------- CLI

def _export_path():
    from ravel.paths import package_data_path
    return package_data_path("inference", "statistics_situations.json")


def _export_bytes():
    return (json.dumps(export(), indent=1, sort_keys=True, allow_nan=False) + "\n").encode()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cat = sub.add_parser("catalogue", help="print, write or check the exported catalogue")
    group = cat.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    cat.add_argument("--resolve", action="store_true", help="include provider resolution (installed versions)")
    ass = sub.add_parser("assess", help="detected situations and the cost-aware default for a facts document")
    ass.add_argument("--facts", required=True)
    ass.add_argument("--choices", help="seat choices {situation: {method, justification}}")
    aud = sub.add_parser("audit", help="recompute a statistics record (a result's 'statistics' block)")
    aud.add_argument("--record", required=True)
    aud.add_argument("--field", default="statistics", help="the block's key in the record (empty: the whole file)")
    args = parser.parse_args(argv)
    if args.command == "catalogue":
        errors = _consistency_errors()
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        path = _export_path()
        if args.write:
            path.write_bytes(_export_bytes())
            print(f"wrote {path}")
            return 0
        if args.check:
            if not path.is_file() or path.read_bytes() != _export_bytes():
                print(f"{path} is stale; regenerate with: python -m ravel.physics.inference.situations catalogue "
                      "--write", file=sys.stderr)
                return 1
            print(f"{path} is current ({catalogue_sha256()})")
            return 0
        print(json.dumps(export(resolve=args.resolve), indent=1, sort_keys=True))
        return 0
    if args.command == "assess":
        facts = json.loads(open(args.facts).read())
        choices = json.loads(open(args.choices).read()) if args.choices else None
        try:
            assessment = assess(facts)
            decision = decide(assessment, choices)
        except StatisticsRecordError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"assessment": assessment, "decision": decision}, indent=1, sort_keys=True))
        return 0
    document = json.loads(open(args.record).read())
    block = document.get(args.field) if args.field else document
    errors = audit(block)
    for error in errors:
        print(f"statistics record: {error}", file=sys.stderr)
    if errors:
        return 1
    validity = block["validity"]
    print(f"statistics record consistent: outcome {validity['outcome']}"
          + (": " + "; ".join(labels(block)) if labels(block) else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
