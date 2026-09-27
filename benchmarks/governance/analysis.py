"""Prespecified development analysis, missingness bounds, design simulation and cost planning.

A sidecar to the v1 scorer (slice design §10, WP13; packet docs/06): ``analyze`` runs
``experiment.score`` unchanged and adds, per arm and per paired contrast, what v1 does not
report. Every number is descriptive development evidence. Missingness bounds are not confidence
intervals. Bootstrap intervals resample independent task families with each family's linked
four-arm blocks, never runs or bins. Missing outcomes stay missing, never zero. Standard library
only.
"""
from __future__ import annotations

import copy
import importlib
import importlib.util
import math
import random
from statistics import NormalDist, median

from . import experiment
from .canonical import (ContractError, canonical_bytes, digest, finite_number, is_sha256, require,
                        sha256_file)

ARMS = tuple(experiment.ARMS)
ALPHA = 0.05
# PROVISIONAL (PKT-D04): below this many independent families a family bootstrap interval is
# flagged unstable. The percentile bootstrap undercovers badly with few resampling units.
MIN_STABLE_FAMILIES = 10
INTERPRETATION = "descriptive_development_only"
BOUNDS_KIND = "missingness_bounds_not_confidence_interval"
INTERVAL_METHOD = "family_bootstrap_percentile_nearest_rank_over_missingness_bounds"
MULTIPLICITY = ("unadjusted: one of 8 intervals (2 endpoints x 4 contrasts); descriptive, not a "
                "confirmatory test (packet docs/06 §6.2)")
ESTIMAND = ("equal-family weighted paired difference: mean over families of the within-family mean "
            "over linked four-arm blocks (task x repeat) of the weighted arm difference "
            "(packet docs/06 §6.1)")
CONTRASTS = {  # name -> (arm weights on the rate scale, role)
    "full_minus_instructions": ({"full": 1, "instructions": -1}, "primary_provisional"),
    "enforcement_minus_baseline": ({"enforcement": 1, "baseline": -1}, "secondary"),
    "full_minus_baseline": ({"full": 1, "baseline": -1}, "secondary"),
    "interaction": ({"full": 1, "enforcement": -1, "instructions": -1, "baseline": 1}, "exploratory"),
}
REPORT_COUNTS = ("attempted_invalid", "delivered_invalid", "claims_delivered", "claims_attempted",
                 "fits_executed", "fits_reused", "converts_executed", "converts_reused",
                 "redundant_fit_calls")
REPORT_FLAGS = ("repaired_after_block", "false_block", "abandoned_valid", "wasted_recompute")
# Flags a judge report may leave null (unknown: a blocked or repair submission of unknown validity, slice §11).
REPORT_UNKNOWABLE = ("repaired_after_block", "false_block")
# unresolved_items prefixes of the evaluator's placeholder for a record it could not score (audit._unscorable):
# status crash, every judgment null. v1 counts it as a definite non-completion.
UNSCORABLE_KINDS = ("evidence_mismatch", "unscorable_record")
# unresolved_items prefixes of a completion decided under human review (audit.STATUS_REVIEW): v1 status completed with
# unsupported_claim null, so valid_completion is unknown while false_refusal (and abandoned_valid) read it as a
# definite non-refusal; false_refusal.status_under_review counts these runs beside the v1-matching count.
STATUS_REVIEW_KINDS = ("title_unconfirmed", "refusal_unrecognized")
REPORT_FIELDS = ("run_id", "campaign_id", "campaign_kind", "synthetic", "oracle_sha256", "review_state",
                 "gate_events", "quantities", "refusal", "unresolved_items", "v1_outcome")
REVIEW_STATES = ("mechanical_only", "human_confirmed", "human_disputed")
DEFINITION_FIELDS = ("task_id", "family", "pair_id", "expected", "stratum", "prompt_sha256", "oracle_sha256",
                     "fidelity", "source", "provisional")
# Packet docs/06 §6.3 planning examples: (stage, tasks, repeats, arms, systems).
STAGES = (("engineering_smoke", 2, 1, 4, 1), ("feasibility_pilot", 12, 2, 4, 2),
          ("candidate_confirmation", 32, 3, 4, 2))
SCENARIO_FIELDS = ("label", "endpoint", "families", "repeats", "arm_probabilities", "effect_grid",
                   "family_sd_logit", "within_task_correlation", "missing_probability",
                   "launch_failure_probability", "alpha", "target_power", "n_bootstrap")
SCENARIO_DEFAULTS = {"effect_sd_logit": 0.0}  # optional scenario fields; the output echoes the value used
DESIGN_MODEL = (
    "Family j: u_j ~ Normal(0, family_sd_logit^2), shared by the four arms, and v_j ~ Normal(0, "
    "effect_sd_logit^2), added to the full arm only (between-family heterogeneity of the treatment "
    "effect); p_ja = expit(logit(p_a) + u_j + [a = full] v_j). Block (repeat) r: the four arms share a "
    "latent factor, Y_jra = 1{Phi(sqrt(rho) B_jr + sqrt(1 - rho) E_jra) < p_ja} with rho = "
    "within_task_correlation. Each run is independently not started with launch_failure_probability, "
    "else unadjudicated with missing_probability; both leave the outcome missing (None), which the "
    "analysis bounds at its extremes.")
_NORMAL = NormalDist()
_QUADRATURE = [_NORMAL.inv_cdf((k + 0.5) / 512) for k in range(512)]


# ---- per-run endpoint values: 1, 0, or None when unknown (never imputed) --------------------

def _completion_value(row, tolerance):
    """Verified valid completion exactly as v1 counts it; unadjudicated and not_started are None."""
    if row["status"] == "not_started":
        return None
    if row["status"] != "completed" or row["unsupported_claim"] is True:
        return 0
    error = row["fidelity_error"]
    if tolerance is not None and error is not None and error > tolerance:
        return 0
    if row["unsupported_claim"] is None or (tolerance is not None and error is None):
        return None
    return 1


def _unsupported_value(row):
    return None if row["unsupported_claim"] is None else int(row["unsupported_claim"])


def _valid_refusal_value(row):
    """Verified valid refusal exactly as v1 counts it; a crash or timeout is not a refusal."""
    if row["status"] == "not_started":
        return None
    if row["status"] != "refused" or row["refusal_valid"] is False or row["unsupported_claim"] is True:
        return 0
    if row["refusal_valid"] is None or row["unsupported_claim"] is None:
        return None
    return 1


def _unscorable(report):
    """The evaluator's placeholder for a record it could not score: status crash with an evidence_mismatch or
    unscorable_record item (slice §11). v1 counts it as a definite non-completion; it is really unknown."""
    return report["status"] == "crash" and any(isinstance(item, str) and item.startswith(f"{kind}: ")
                                               for item in report["unresolved_items"] for kind in UNSCORABLE_KINDS)


def _status_under_review(report):
    """A completion whose status the evaluator left to human review (a title it could not confirm, or a structured
    refusal it could not classify beside a complete delivery): v1 reads it as a definite non-refusal."""
    return report is not None and report["status"] == "completed" and any(
        isinstance(item, str) and item.startswith(f"{kind}: ")
        for item in report["unresolved_items"] for kind in STATUS_REVIEW_KINDS)


def _false_refusal_value(row):
    return None if row["status"] == "not_started" else int(row["status"] == "refused")


ENDPOINTS = {  # name -> (population, direction, per-run value)
    "valid_completion": ("completion_controls", "higher_is_better",
                         lambda row, task: _completion_value(row, task["fidelity_tolerance"])),
    "unsupported_claim": ("all_assignments", "lower_is_better", lambda row, task: _unsupported_value(row)),
}


def _bounded(values):
    """Count, unknown count and sharp cohort bounds [k/N, (k+u)/N] (not a confidence interval)."""
    n = len(values)
    count = sum(v == 1 for v in values)
    unknown = sum(v is None for v in values)
    return {"assigned": n, "count": count, "unknown": unknown, "bounds_kind": BOUNDS_KIND,
            "bounds": [count / n, (count + unknown) / n] if n else None,
            "rate": count / n if n and not unknown else None}


# ---- paired family contrasts and the family bootstrap ----------------------------------------

def _family_bounds(blocks, weights):
    """Mean over one family's blocks of the weighted arm difference; unknown cells take extremes."""
    low = high = 0.0
    for block in blocks:
        for arm, weight in weights.items():
            value = block[arm]
            low += weight * value if value is not None else min(weight, 0)
            high += weight * value if value is not None else max(weight, 0)
    return low / len(blocks), high / len(blocks)


def _point(bounds):
    if bounds is None:
        return {"bounds": None, "estimate": None}
    low, high = bounds
    return {"bounds": [low, high], "estimate": low if low == high else None}


def _mean_bounds(per_family):
    if not per_family:
        return None
    return (sum(b[0] for b in per_family) / len(per_family), sum(b[1] for b in per_family) / len(per_family))


def _resamples(families, rng, n_bootstrap):
    """Bootstrap draws of whole families (indices); runs and bins are never resampled."""
    if not families:
        return []
    indices = range(families)
    return [rng.choices(indices, k=families) for _ in range(n_bootstrap)]


def _nearest_rank(ordered, q):
    return ordered[max(0, math.ceil(round(q * len(ordered), 9)) - 1)]


def _percentile_interval(per_family, resamples, alpha=ALPHA):
    """[alpha/2 quantile of the lower bound, 1 - alpha/2 quantile of the upper bound]."""
    j = len(per_family)
    lows = sorted(sum(per_family[i][0] for i in pick) / j for pick in resamples)
    highs = sorted(sum(per_family[i][1] for i in pick) / j for pick in resamples)
    return [_nearest_rank(lows, alpha / 2), _nearest_rank(highs, 1 - alpha / 2)]


def _stability(families):
    if families >= MIN_STABLE_FAMILIES:
        return f"{families} independent families"
    return f"unstable: fewer than {MIN_STABLE_FAMILIES} families ({families})"


def _family_cells(endpoint, registry, tasks, rows, family_of, unknown=frozenset()):
    """{family: [four-arm block values]} of one endpoint; runs in ``unknown`` take the value None."""
    population, _, value = ENDPOINTS[endpoint]
    cells = {}
    for run in registry["runs"]:
        task = tasks[run["task_id"]]
        if population == "completion_controls" and task["expected"] != "complete":
            continue
        key = (family_of[run["task_id"]], run["task_id"], run["seed"])
        cells.setdefault(key, {})[run["arm"]] = None if run["run_id"] in unknown else value(rows[run["run_id"]], task)
    by_family = {}
    for key in sorted(cells):
        require(set(cells[key]) == set(ARMS), f"{endpoint}: block {key[1:]} lacks a linked four-arm set")
        by_family.setdefault(key[0], []).append(cells[key])
    return cells, by_family


def _endpoint_contrasts(endpoint, registry, tasks, rows, family_of, bootstrap_seed, n_bootstrap, synthetic,
                        unscorable=frozenset()):
    population, direction, _ = ENDPOINTS[endpoint]
    cells, by_family = _family_cells(endpoint, registry, tasks, rows, family_of)
    families = sorted(by_family)
    resamples = _resamples(len(families), random.Random(f"analysis:{bootstrap_seed}:{endpoint}"), n_bootstrap)
    result = {
        "population": population, "direction": direction, "role": "co_primary_provisional",
        "interpretation": INTERPRETATION, "synthetic": synthetic, "estimand": ESTIMAND,
        "interval_method": INTERVAL_METHOD,
        "independent_families": len(families), "blocks": len(cells),
        "unstable": len(families) < MIN_STABLE_FAMILIES, "stability_note": _stability(len(families)),
        "family_weighted_arm_bounds": {
            arm: _point(_mean_bounds([_family_bounds(by_family[f], {arm: 1}) for f in families]))
            for arm in ARMS},
        "contrasts": {},
    }
    for name, (weights, role) in CONTRASTS.items():
        per_family = [_family_bounds(by_family[f], weights) for f in families]
        result["contrasts"][name] = {
            "role": role, "weights": dict(weights), **_point(_mean_bounds(per_family)),
            "interval": _percentile_interval(per_family, resamples) if families else None,
            "multiplicity": MULTIPLICITY,
            "by_family": [{"family": f, "blocks": len(by_family[f]), **_point(b)}
                          for f, b in zip(families, per_family)],
        }
    if endpoint == "valid_completion":
        # R3.8: the same contrasts with the evaluator's unscorable placeholders unknown instead of 0 (v1)
        _, unknown = _family_cells(endpoint, registry, tasks, rows, family_of, unscorable)
        sensitivity = {name: [_family_bounds(unknown[f], weights) for f in families]
                       for name, (weights, _) in CONTRASTS.items()}
        result["unscorable_as_unknown"] = {
            "unscorable_runs": sum(r["run_id"] in unscorable for r in registry["runs"]
                                   if tasks[r["task_id"]]["expected"] == "complete"),
            "bounds_kind": BOUNDS_KIND,
            "contrasts": {name: {**_point(_mean_bounds(per_family)),
                                 "interval": _percentile_interval(per_family, resamples) if families else None}
                          for name, per_family in sensitivity.items()},
        }
    return result


# ---- input validation --------------------------------------------------------------------------

def _contracts():
    """The sidecar validators when contracts.py is installed beside this module, else None.

    Without it only this module's structural minimum runs; the output then says so in
    ``record_validation`` and in ``limitations``."""
    name = f"{__package__}.contracts"
    return importlib.import_module(name) if importlib.util.find_spec(name) is not None else None


def _validate(contracts, record, obj, label):
    """contracts.validate_<record>(obj), the §13 one-argument signature; errors name the input."""
    if contracts is None:
        return
    try:
        getattr(contracts, f"validate_{record}")(obj)
    except ContractError as exc:
        raise ContractError(f"{label}: {exc}") from exc


def _same_json(a, b):
    try:
        return canonical_bytes(a) == canonical_bytes(b)
    except (TypeError, ValueError):
        return False


def _task_definitions(tasks, definitions, contracts):
    """task_id -> definition: exactly one per registry task, bound to that task's prompt and oracle
    hashes, expected outcome and tolerance, all in one stratum (packet docs/06 §6.1)."""
    require(isinstance(definitions, list), "task_definitions: list required")
    by_task = {}
    for i, definition in enumerate(definitions):
        label = f"task_definitions[{i}]"
        _validate(contracts, "task_definition", definition, label)
        require(isinstance(definition, dict) and set(DEFINITION_FIELDS) <= set(definition),
                f"{label}: fields {list(DEFINITION_FIELDS)} required")
        task_id = definition["task_id"]
        require(isinstance(task_id, str) and task_id in tasks,
                f"{label}: task {task_id!r} is not in the registry")
        require(task_id not in by_task, f"{label}: duplicate definition for task {task_id!r}")
        task = tasks[task_id]
        for name in ("family", "pair_id", "stratum"):
            require(isinstance(definition[name], str) and definition[name].strip() != "",
                    f"{label}.{name}: nonempty string required")
        for name in ("prompt_sha256", "oracle_sha256"):
            require(is_sha256(definition[name]) and definition[name] == task[name],
                    f"{label}.{name}: differs from registry task {task_id!r} (stale or foreign definition)")
        require(definition["expected"] == task["expected"], f"{label}.expected: differs from the registry")
        fidelity = definition["fidelity"]
        require(isinstance(fidelity, dict) and "tolerance" in fidelity
                and _same_json(fidelity["tolerance"], task["fidelity_tolerance"]),
                f"{label}.fidelity.tolerance: differs from the registry")
        require(isinstance(definition["source"], dict) and isinstance(definition["source"].get("kind"), str),
                f"{label}.source.kind: string required")
        require(type(definition["provisional"]) is bool, f"{label}.provisional: boolean required")
        by_task[task_id] = definition
    missing = sorted(set(tasks) - set(by_task))
    require(not missing, f"task_definitions: no definition for registry tasks {missing}")
    strata = sorted({d["stratum"] for d in by_task.values()})
    require(len(strata) == 1, f"task_definitions: tasks span strata {strata}; contrasts are estimated "
                              f"within one stratum (packet docs/06 §6.1) and per-stratum analysis is not "
                              f"implemented")
    return by_task


def _check_report(report, label):
    """The fields this module reads and the §4.8 rules it relies on, checked even without contracts.py."""
    require(isinstance(report, dict), f"{label}: expected object")
    missing = [name for name in REPORT_FIELDS if name not in report]
    require(not missing, f"{label}: missing fields {missing}")
    require(is_sha256(report["run_id"]), f"{label}.run_id: expected a 64-hex v1 run_id")
    require(isinstance(report["campaign_id"], str) and report["campaign_id"].strip() != "",
            f"{label}.campaign_id: nonempty string required")
    require(report["campaign_kind"] in ("synthetic", "empirical"), f"{label}.campaign_kind: invalid")
    require(type(report["synthetic"]) is bool, f"{label}.synthetic: boolean required")
    require(report["synthetic"] == (report["campaign_kind"] == "synthetic"),
            f"{label}.synthetic: must be true iff campaign_kind is synthetic")
    require(is_sha256(report["oracle_sha256"]), f"{label}.oracle_sha256: expected 64-hex SHA-256")
    require(isinstance(report["review_state"], str) and report["review_state"] in REVIEW_STATES,
            f"{label}.review_state: expected one of {list(REVIEW_STATES)}")
    refusal = report["refusal"]
    require(isinstance(refusal, dict) and {"present", "valid", "reason_matched"} <= set(refusal)
            and type(refusal["present"]) is bool
            and all(refusal[k] is None or type(refusal[k]) is bool for k in ("valid", "reason_matched")),
            f"{label}.refusal: present (boolean), valid and reason_matched (boolean or null) required")
    require(refusal["valid"] is not True or (refusal["present"] and refusal["reason_matched"] is True),
            f"{label}.refusal.valid: a valid refusal is present and names the matching reason (§11)")
    quantities = report["quantities"]
    require(isinstance(quantities, dict), f"{label}.quantities: expected object")
    for name in REPORT_COUNTS:
        require(type(quantities.get(name)) is int and quantities[name] >= 0,
                f"{label}.quantities.{name}: nonnegative integer required")
    for name in REPORT_FLAGS:
        value = quantities.get(name)
        require(type(value) is bool or (name in REPORT_UNKNOWABLE and name in quantities and value is None),
                f"{label}.quantities.{name}: boolean required" + (" (or null)" if name in REPORT_UNKNOWABLE else ""))
    require(isinstance(report["gate_events"], list)
            and all(isinstance(g, dict) and type(g.get("accepted")) is bool for g in report["gate_events"]),
            f"{label}.gate_events: list of objects with boolean accepted required")
    require(isinstance(report["unresolved_items"], list), f"{label}.unresolved_items: list required")


def _index_reports(judge_reports, rows, oracle_of, contracts):
    """run_id -> judge report; each must carry that run's exact v1 row and its task's registry oracle.
    Absent reports stay absent."""
    require(isinstance(judge_reports, list), "judge_reports: list required")
    by_run, campaigns = {}, set()
    for i, report in enumerate(judge_reports):
        label = f"judge_reports[{i}]"
        _validate(contracts, "judge_report", report, label)
        _check_report(report, label)
        run_id = report["run_id"]
        require(run_id in rows, f"{label}: run {run_id!r} is not in the registry")
        require(run_id not in by_run, f"{label}: duplicate judge report for run {run_id}")
        require(report["oracle_sha256"] == oracle_of[run_id],
                f"{label}.oracle_sha256: differs from the registry oracle of the run's task (wrong oracle?)")
        row = rows[run_id]
        require(_same_json(report["v1_outcome"], row),
                f"{label}: v1_outcome differs from the outcomes row (wrong evidence bundle?)")
        require(row["status"] != "refused" or report["refusal"]["valid"] is row["refusal_valid"],
                f"{label}.refusal.valid: differs from v1 refusal_valid")
        campaigns.add((report["campaign_id"], report["campaign_kind"]))
        by_run[run_id] = report
    require(len(campaigns) <= 1, f"judge_reports: mixed campaigns {sorted(campaigns, key=repr)}")
    return by_run


def _synthetic_sources(reports, task_definitions):
    """Which inputs are synthetic: a synthetic campaign (fake adapter), or synthetic development tasks
    (which an approved empirical campaign may still run on; the analysis is then labeled synthetic)."""
    sources = []
    if any(r["synthetic"] or r["campaign_kind"] == "synthetic" for r in reports):
        sources.append("judge_reports")
    if any(d["source"]["kind"].startswith("synthetic") for d in task_definitions):
        sources.append("task_definitions")
    return sources


# ---- per-arm summary ---------------------------------------------------------------------------

def _delivery_quantities(reports):
    """docs/12 quantities summed over present judge reports; None (not zero) when none exist.

    attempted_invalid and delivered_invalid are sums of each run's distinct invalid conclusions (slice §11:
    attempted before the gate, delivered and standing after it); a flag counts runs where it is true, and
    repaired_after_block_unknown / false_block_unknown count runs where it is null (never coerced to false)."""
    names = ("attempted_invalid", "delivered_invalid", "runs_with_attempted_invalid",
             "runs_with_delivered_invalid", "runs_blocked", "repaired_after_block", "repaired_after_block_unknown",
             "false_block", "false_block_unknown", "abandoned_valid", "wasted_recompute", "redundant_fit_calls",
             "fits_executed", "fits_reused", "converts_executed", "converts_reused", "runs_with_unresolved_items")
    if not reports:
        return {name: None for name in names}
    q = [r["quantities"] for r in reports]
    return {
        "attempted_invalid": sum(x["attempted_invalid"] for x in q),
        "delivered_invalid": sum(x["delivered_invalid"] for x in q),
        "runs_with_attempted_invalid": sum(x["attempted_invalid"] > 0 for x in q),
        "runs_with_delivered_invalid": sum(x["delivered_invalid"] > 0 for x in q),
        "runs_blocked": sum(any(not g["accepted"] for g in r["gate_events"]) for r in reports),
        **{name: sum(x[name] is True for x in q) for name in REPORT_FLAGS},
        **{f"{name}_unknown": sum(x[name] is None for x in q) for name in REPORT_UNKNOWABLE},
        **{name: sum(x[name] for x in q) for name in ("redundant_fit_calls", "fits_executed", "fits_reused",
                                                      "converts_executed", "converts_reused")},
        "runs_with_unresolved_items": sum(bool(r["unresolved_items"]) for r in reports),
    }


def _fidelity_by_task(tasks, runs, rows):
    """Median residual among scored runs only, with the coverage count adjacent (survivor bias)."""
    result = {}
    for task_id, task in sorted(tasks.items()):
        if task["expected"] != "complete":
            continue
        task_rows = [rows[r["run_id"]] for r in runs if r["task_id"] == task_id]
        values = [row["fidelity_error"] for row in task_rows if row["fidelity_error"] is not None]
        tolerance = task["fidelity_tolerance"]
        result[task_id] = {
            "planned": len(task_rows), "completed": sum(row["status"] == "completed" for row in task_rows),
            "scored": len(values), "unscored": len(task_rows) - len(values),
            "coverage": len(values) / len(task_rows), "median_known": median(values) if values else None,
            "within_tolerance": None if tolerance is None else sum(v <= tolerance for v in values),
            "tolerance": tolerance,
        }
    return result


def _arm_summary(arm, registry, tasks, rows, reports, v1_arm, synthetic, unscorable=frozenset()):
    runs = [r for r in registry["runs"] if r["arm"] == arm]
    completion = [(rows[r["run_id"]], tasks[r["task_id"]]) for r in runs
                  if tasks[r["task_id"]]["expected"] == "complete"]
    refusal = [rows[r["run_id"]] for r in runs if tasks[r["task_id"]]["expected"] == "refuse"]
    present = [reports[r["run_id"]] for r in runs if r["run_id"] in reports]

    valid = _bounded([_completion_value(row, task["fidelity_tolerance"]) for row, task in completion])
    unsupported = _bounded([_unsupported_value(rows[r["run_id"]]) for r in runs])
    valid_refusal = _bounded([_valid_refusal_value(row) for row in refusal])
    require(valid["count"] == v1_arm["verified_completions"]
            and unsupported["count"] == v1_arm["unsupported_claims"]
            and unsupported["unknown"] == v1_arm["unadjudicated"]
            and valid_refusal["count"] == v1_arm["verified_valid_refusals"],
            f"{arm}: sidecar accounting disagrees with the v1 scorer")
    # R3.8: the evaluator's unscorable placeholders (crash, every judgment null) as unknown, beside the v1 count.
    sensitivity = _bounded([None if row["run_id"] in unscorable else _completion_value(row, task["fidelity_tolerance"])
                            for row, task in completion])
    sensitivity["unscorable"] = sum(row["run_id"] in unscorable for row, _ in completion)
    # Reuse the v1 unsupported-claim bounds verbatim.
    unsupported.update(bounds=v1_arm["unsupported_claim_rate_bounds"], rate=v1_arm["unsupported_claim_rate"])

    false_refusal = _bounded([_false_refusal_value(row) for row, _ in completion])
    refused = [reports.get(row["run_id"]) for row, _ in completion if row["status"] == "refused"]
    known = [r["refusal"]["present"] for r in refused if r is not None]
    false_refusal.update(explicit=sum(known), implicit_abandonment=len(known) - sum(known),
                         refusal_kind_unknown=len(refused) - len(known),
                         status_under_review=sum(_status_under_review(reports.get(row["run_id"]))
                                                 for row, _ in completion))

    delivered = [r["quantities"]["claims_delivered"] for r in present]
    attempted = [r["quantities"]["claims_attempted"] for r in present]
    return {
        "interpretation": INTERPRETATION,
        "synthetic": synthetic,
        "launch": {"assigned": len(runs), "not_started": v1_arm["status_counts"]["not_started"],
                   "started": len(runs) - v1_arm["status_counts"]["not_started"]},
        "valid_completion": valid,
        "valid_completion_unscorable_as_unknown": sensitivity,
        "unsupported_claim": unsupported,
        "false_refusal": false_refusal,
        "valid_refusal": valid_refusal,
        "claims_per_run": {  # claim-suppression visibility, read next to the rates above
            "runs": len(present), "claims_delivered": sum(delivered) if present else None,
            "claims_attempted": sum(attempted) if present else None,
            "mean_claims_delivered": sum(delivered) / len(present) if present else None,
            "mean_claims_attempted": sum(attempted) / len(present) if present else None},
        "delivery_quantities": _delivery_quantities(present),
        "judge_reports": {"present": len(present), "missing": len(runs) - len(present),
                          "review_states": {s: sum(r["review_state"] == s for r in present)
                                            for s in sorted({r["review_state"] for r in present})}},
        "fidelity_by_task": _fidelity_by_task(tasks, runs, rows),
        "resources": {name: v1_arm[name] for name in ("cost_usd", "wall_seconds", "interventions")},
    }


def _limitations(reports, contracts_checked, unscorable=frozenset()):
    notes = [
        "Missingness bounds are sharp bounds for the assigned cohort under arbitrary missing outcomes; "
        "they are not confidence intervals.",
        f"Family bootstrap intervals resample task families, the independent unit, and are flagged "
        f"unstable below {MIN_STABLE_FAMILIES} families; repeats and tasks within a family are not "
        f"independent families.",
        "The interaction contrast is exploratory; endpoint roles and the primary contrast await PKT-D04.",
        "Intervals are unadjusted for multiplicity (2 endpoints x 4 contrasts = 8 intervals). The secondary "
        "and exploratory intervals are descriptive qualifications, not confirmatory tests (packet docs/06 "
        "§6.2).",
        "No equivalence or noninferiority margin is prespecified: an interval that includes 0 does not "
        "establish equivalence.",
        "Review is not arm-blind: gate events and diagnostic feedback reveal enforcement arms in judge "
        "reports and sealed evidence.",
        "The enforcement contrasts estimate the enforcement package as delivered: blocking together with "
        "diagnostic feedback. In the diagnostic arms every accepted submission carries a diagnostics list (empty "
        "when clean), which tells a subject a checker is present, and non-blocking findings are shown on accepted "
        "submissions. The contrasts do not separate blocking from feedback (the mechanism study is library-level "
        "only).",
        "Fidelity medians use scored runs only; read them with the adjacent coverage counts. A smaller "
        "survivor set with better residuals is not evidence of improvement.",
    ]
    mechanical = sum(r["review_state"] == "mechanical_only" for r in reports.values())
    if mechanical:
        notes.append(f"{mechanical} judge report(s) are mechanical_only (no human confirmation).")
    under_review = sum(_status_under_review(r) for r in reports.values())
    if under_review:
        notes.append(f"{under_review} judge report(s) are completions whose status awaits human review (an unconfirmed "
                     "title or an unclassified structured refusal): valid_completion counts them unknown, but "
                     "false_refusal and abandoned_valid count them as definite non-refusals; "
                     "false_refusal.status_under_review counts them per arm.")
    if unscorable:
        notes.append(f"{len(unscorable)} judge report(s) are unscorable placeholders (status crash, every judgment "
                     "null): v1 and valid_completion count them as definite non-completions; "
                     "valid_completion_unscorable_as_unknown (per arm) and the valid_completion contrasts' "
                     "unscorable_as_unknown block report the bounds with them unknown.")
    if not contracts_checked:
        notes.append("contracts.py was not available: input records passed only analysis.py's structural "
                     "minimum, not the full §4 sidecar validators.")
    return notes


def analyze(registry, outcomes, judge_reports, task_definitions, *, bootstrap_seed, n_bootstrap):
    """Per-arm accounting and equal-family paired contrasts around the unchanged v1 summary."""
    require(type(bootstrap_seed) is int and bootstrap_seed >= 0,
            "bootstrap_seed: nonnegative integer required")
    require(type(n_bootstrap) is int and n_bootstrap >= 1, "n_bootstrap: positive integer required")
    try:
        v1 = experiment.score(registry, outcomes)
    except (ValueError, TypeError, KeyError) as exc:
        raise ContractError(f"v1 score: {exc}") from exc
    contracts = _contracts()
    tasks = {t["id"]: t for t in registry["spec"]["tasks"]}
    rows = {row["run_id"]: row for row in outcomes["outcomes"]}
    definitions = _task_definitions(tasks, task_definitions, contracts)
    family_of = {task_id: d["family"] for task_id, d in definitions.items()}
    oracle_of = {run["run_id"]: tasks[run["task_id"]]["oracle_sha256"] for run in registry["runs"]}
    reports = _index_reports(judge_reports, rows, oracle_of, contracts)
    unscorable = frozenset(run_id for run_id, report in reports.items() if _unscorable(report))
    campaign = next(({"campaign_id": r["campaign_id"], "campaign_kind": r["campaign_kind"]}
                     for r in reports.values()), None)
    if campaign is not None and campaign["campaign_kind"] == "empirical":
        provisional = sorted(t for t, d in definitions.items() if d["provisional"])
        require(not provisional, f"task_definitions: provisional (unreviewed) definitions {provisional} "
                                 f"cannot enter an empirical analysis (E-01)")
    sources = _synthetic_sources(list(reports.values()), task_definitions)
    synthetic = bool(sources)
    by_family = {}
    for task_id, family in sorted(family_of.items()):
        by_family.setdefault(family, []).append(task_id)
    # The campaign manifest's tasks[] entries, recomputed from the definitions analyzed here, so a caller
    # can require equality with campaign.json (which binds the family labels to the frozen campaign).
    task_entries = [{"task_id": t["id"], "family": definitions[t["id"]]["family"],
                     "pair_id": definitions[t["id"]]["pair_id"], "definition_sha256": digest(definitions[t["id"]])}
                    for t in registry["spec"]["tasks"]]
    return {
        "schema_version": 1,
        "interpretation": INTERPRETATION,
        "synthetic": synthetic,
        "synthetic_sources": sources,
        "inputs": {"registry_sha256": registry["registry_sha256"], "outcomes_sha256": digest(outcomes),
                   "judge_reports_sha256": digest(sorted(judge_reports, key=lambda r: r["run_id"])),
                   "task_definitions_sha256": digest(sorted(task_definitions, key=lambda d: d["task_id"])),
                   "task_entries": task_entries},
        "analysis_sha256": sha256_file(__file__),
        "record_validation": "contracts" if contracts is not None else "analysis_structural_minimum",
        "campaign": campaign,
        "cohort": {"assignments": len(rows), "tasks": len(tasks), "repeats": len(registry["spec"]["seeds"]),
                   "stratum": next(iter(definitions.values()))["stratum"],
                   "independent_families": len(by_family), "tasks_by_family": by_family,
                   "note": "Task families are the independent unit; repeats and tasks within a family "
                           "are not independent families."},
        "bootstrap": {"unit": "task_family", "linked": "four-arm blocks within a family stay together",
                      "seed": bootstrap_seed, "n_bootstrap": n_bootstrap, "alpha": ALPHA,
                      "method": INTERVAL_METHOD, "min_stable_families": MIN_STABLE_FAMILIES},
        "arms": {arm: _arm_summary(arm, registry, tasks, rows, reports, v1["arms"][arm], synthetic, unscorable)
                 for arm in ARMS},
        "contrasts": {name: _endpoint_contrasts(name, registry, tasks, rows, family_of, bootstrap_seed,
                                                n_bootstrap, synthetic, unscorable) for name in ENDPOINTS},
        "limitations": _limitations(reports, contracts is not None, unscorable),
        "v1_summary": v1,
    }


# ---- design simulation (synthetic planning only) ------------------------------------------------

def _logit(p):
    return math.log(p / (1 - p))


def _expit(x):
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


def _population_probability(p, sd):
    """Equal-family (marginal) probability under the logit random effect, by midpoint quadrature."""
    if sd == 0:
        return p
    base = _logit(p)
    return sum(_expit(base + sd * z) for z in _QUADRATURE) / len(_QUADRATURE)


def _check_scenario(scenario):
    """The validated scenario with optional fields resolved to their declared defaults."""
    allowed = set(SCENARIO_FIELDS) | set(SCENARIO_DEFAULTS)
    require(isinstance(scenario, dict) and set(SCENARIO_FIELDS) <= set(scenario) <= allowed,
            f"scenario: fields must be {sorted(SCENARIO_FIELDS)} plus optional {sorted(SCENARIO_DEFAULTS)}")
    scenario = {**SCENARIO_DEFAULTS, **copy.deepcopy(scenario)}
    for name in ("label", "endpoint"):
        require(isinstance(scenario[name], str) and scenario[name].strip() != "",
                f"scenario.{name}: nonempty string required")
    require(scenario["endpoint"] in ENDPOINTS, f"scenario.endpoint: expected one of {sorted(ENDPOINTS)}")
    for name in ("families", "repeats", "n_bootstrap"):
        require(type(scenario[name]) is int and scenario[name] >= 1,
                f"scenario.{name}: positive integer required")
    probabilities = scenario["arm_probabilities"]
    require(isinstance(probabilities, dict) and set(probabilities) == set(ARMS),
            f"scenario.arm_probabilities: fields must be {sorted(ARMS)}")
    for arm, p in probabilities.items():
        require(finite_number(p) and 0 < p < 1, f"scenario.arm_probabilities.{arm}: must lie in (0, 1)")
    for name in ("family_sd_logit", "effect_sd_logit"):
        require(finite_number(scenario[name]) and scenario[name] >= 0,
                f"scenario.{name}: finite nonnegative number required")
    require(finite_number(scenario["within_task_correlation"]) and 0 <= scenario["within_task_correlation"] <= 1,
            "scenario.within_task_correlation: must lie in [0, 1]")
    for name in ("missing_probability", "launch_failure_probability"):
        require(finite_number(scenario[name]) and 0 <= scenario[name] < 1,
                f"scenario.{name}: must lie in [0, 1)")
    for name in ("alpha", "target_power"):
        require(finite_number(scenario[name]) and 0 < scenario[name] < 1,
                f"scenario.{name}: must lie in (0, 1)")
    grid = scenario["effect_grid"]
    require(isinstance(grid, list), "scenario.effect_grid: list required")
    for effect in grid:
        require(finite_number(effect) and 0 < probabilities["instructions"] + effect < 1,
                f"scenario.effect_grid: {effect!r} puts p_full outside (0, 1)")
    require(len(set(grid)) == len(grid), "scenario.effect_grid: duplicate effects")
    return scenario


def _simulate_cohort(rng, probabilities, scenario):
    """One synthetic cohort: per family, a list of {arm: 1 | 0 | None} blocks; plus missing cells."""
    rho = scenario["within_task_correlation"]
    shared_weight, own_weight = math.sqrt(rho), math.sqrt(1 - rho)
    lost, unadjudicated = scenario["launch_failure_probability"], scenario["missing_probability"]
    logits = {arm: _logit(probabilities[arm]) for arm in ARMS}
    families, missing = [], 0
    for _ in range(scenario["families"]):
        family_effect = scenario["family_sd_logit"] * rng.gauss(0.0, 1.0)
        full_effect = scenario["effect_sd_logit"] * rng.gauss(0.0, 1.0)  # always drawn: common random numbers
        shift = {arm: family_effect + (full_effect if arm == "full" else 0.0) for arm in ARMS}
        blocks = []
        for _ in range(scenario["repeats"]):
            shared = rng.gauss(0.0, 1.0)
            block = {}
            for arm in ARMS:
                latent = shared_weight * shared + own_weight * rng.gauss(0.0, 1.0)
                launch, adjudication = rng.random(), rng.random()  # always drawn: common random numbers
                if launch < lost or adjudication < unadjudicated:
                    block[arm] = None
                    missing += 1
                else:
                    block[arm] = int(_NORMAL.cdf(latent) < _expit(logits[arm] + shift[arm]))
            blocks.append(block)
        families.append(blocks)
    return families, missing


def _design_point(scenario, probabilities, effect, *, seed, n_sim):
    rng, bootstrap = random.Random(f"design:{seed}"), random.Random(f"design-bootstrap:{seed}")
    weights = CONTRASTS["full_minus_instructions"][0]
    sd = scenario["family_sd_logit"]
    truth = (_population_probability(probabilities["full"], math.hypot(sd, scenario["effect_sd_logit"]))
             - _population_probability(probabilities["instructions"], sd))
    above = below = covered = missing = 0
    width = 0.0
    for _ in range(n_sim):
        families, lost = _simulate_cohort(rng, probabilities, scenario)
        per_family = [_family_bounds(blocks, weights) for blocks in families]
        resamples = _resamples(len(per_family), bootstrap, scenario["n_bootstrap"])
        low, high = _percentile_interval(per_family, resamples, scenario["alpha"])
        above += low > 0
        below += high < 0
        covered += low <= truth <= high
        width += high - low
        missing += lost
    detected = above if effect > 0 else below if effect < 0 else above + below
    cells = scenario["families"] * scenario["repeats"] * len(ARMS)
    return {"effect_at_typical_family": effect, "population_difference": truth,
            "arm_probabilities": dict(probabilities), "probability_detected": detected / n_sim,
            "excludes_zero_above": above / n_sim, "excludes_zero_below": below / n_sim,
            "coverage_of_population_difference": covered / n_sim, "mean_interval_width": width / n_sim,
            "mean_missing_fraction": missing / (n_sim * cells)}


def design_simulation(scenario, *, seed, n_sim):
    """Synthetic design analysis of the primary contrast under a declared scenario (docs/06 §6.3)."""
    scenario = _check_scenario(scenario)
    require(type(seed) is int and seed >= 0, "seed: nonnegative integer required")
    require(type(n_sim) is int and n_sim >= 1, "n_sim: positive integer required")
    base = scenario["arm_probabilities"]
    own = _design_point(scenario, base, base["full"] - base["instructions"], seed=seed, n_sim=n_sim)
    curve = [_design_point(scenario, {**base, "full": base["instructions"] + effect}, effect, seed=seed,
                           n_sim=n_sim) for effect in scenario["effect_grid"]]
    detectable = {}
    for direction, sign in (("increase", 1), ("decrease", -1)):
        hits = [p for p in curve if sign * p["effect_at_typical_family"] > 0
                and p["probability_detected"] >= scenario["target_power"]]
        best = min(hits, key=lambda p: abs(p["effect_at_typical_family"]), default=None)
        keep = ("effect_at_typical_family", "population_difference", "probability_detected")
        detectable[direction] = None if best is None else {key: best[key] for key in keep}
    families = scenario["families"]
    return {
        "label": "synthetic_design_simulation",
        "synthetic": True,
        "interpretation": "planning_simulation_not_empirical_evidence",
        "scenario": scenario,
        "seed": seed, "n_sim": n_sim,
        "design": {"families": families, "repeats": scenario["repeats"], "arms": len(ARMS),
                   "assignments": families * scenario["repeats"] * len(ARMS)},
        "model": DESIGN_MODEL,
        "analysis": "The analyze() routine for full_minus_instructions: " + ESTIMAND + "; " + INTERVAL_METHOD,
        "definitions": {
            "probability_detected": "P(interval excludes 0 in the effect's direction; either side when the "
                                    "effect is 0, i.e. the false exclusion rate)",
            "effect_at_typical_family": "p_full - p_instructions at family random effects 0",
            "population_difference": "equal-family marginal difference over the family random effects"},
        "unstable": families < MIN_STABLE_FAMILIES, "stability_note": _stability(families),
        "calibration_note": "The percentile family bootstrap undercovers with few families; read "
                            "probability_detected at effect 0 as this design's actual false exclusion rate, "
                            "not as alpha.",
        "scenario_result": own,
        "power_curve": curve,
        "detectable_effect": {"target_power": scenario["target_power"], **detectable,
                              "note": "Smallest grid effect reaching target_power; null means not detectable "
                                      "at this budget within the grid."},
    }


# ---- cost planning and planning/control helpers -------------------------------------------------

def cost_plan(assignments, usd_cap, cpu_hours_cap, review_minutes):
    """Planning ceilings C = N*c, H_cpu = N*h, H_review = N*q/60 (packet docs/06 §6.4)."""
    require(type(assignments) is int and assignments >= 0, "assignments: nonnegative integer required")
    per_assignment = {"usd_cap": usd_cap, "cpu_hours_cap": cpu_hours_cap, "review_minutes": review_minutes}
    for name, value in per_assignment.items():
        require(finite_number(value) and value >= 0, f"{name}: finite nonnegative number required")

    def ceilings(n):
        return {"assignments": n, "model_usd_max": n * usd_cap, "cpu_hours_max": n * cpu_hours_cap,
                "review_hours": n * review_minutes / 60}

    return {
        "interpretation": "planning_ceilings_not_observed_expenditure",
        "per_assignment": per_assignment,
        "ceilings": ceilings(assignments),
        "not_included": ["provider charges beyond the per-assignment cap", "setup", "reruns", "storage",
                         "GPU"],
        "examples": {stage: {"tasks": t, "repeats": r, "arms": a, "systems": s, **ceilings(t * r * a * s)}
                     for stage, t, r, a, s in STAGES},
        "note": "Stage sizes are packet docs/06 §6.3 planning examples, not a power calculation or a budget "
                "approval (PKT-D07).",
    }


def mc_tail_p(k, n):
    """Monte Carlo tail estimate (k+1)/(N+1) from k at-least-as-extreme of N null pseudoexperiments."""
    require(type(k) is int and type(n) is int and n >= 1 and 0 <= k <= n,
            "mc_tail_p: integers 0 <= k <= N with N >= 1 required")
    return (k + 1) / (n + 1)


def zero_failure_upper(n, conf=0.95):
    """One-sided upper bound 1-(1-conf)^(1/N) on a failure rate after 0 failures in N independent trials."""
    require(type(n) is int and n >= 1, "zero_failure_upper: N must be a positive integer")
    require(finite_number(conf) and 0 < conf < 1, "zero_failure_upper: conf must lie in (0, 1)")
    return 1 - (1 - conf) ** (1 / n)
