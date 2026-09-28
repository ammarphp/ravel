"""Development task family ``limit_summary`` (PROVISIONAL; synthetic development only; WP12 design §2 P6).

One pair, ``hv-p1`` (exposure class ``role_label_provenance``). The deliverable: the observed and median expected
95% CLs upper limits on the number of signal events of a synthetic single-bin counting likelihood (n = 73,
b = 58.0 +- 7.0 events, unit signal, POI range [0, 256]; chosen by a scan so that no role confusion falls within
the tolerance), each with its role, and a figure caption. An earlier session left a prior fit and a summary figure
of it; the figure is made by the coordinator-only prior-recipe step ``figure`` (stages/figure.py), which takes its
legend as given, so it is fresh and can still be wrong. The twins differ only in that legend:

    valid  solid series (the observed limit) labelled "Observed", dashed (the median) "Expected (median)"
    fault  the labels swapped: the solid series carries "Expected (median)", the dashed "Observed"

Both twins are completion tasks: the prior fit is correct in both, so the reference delivers the fit's values
with their roles without computing anything (reuse plan {fit: reuse}); copying the fault twin's legend gives the
roles swapped (``swapped_roles`` -> role_error). The guard catches typed swaps (value_mismatch) but not prose
swaps (E-15); only the evaluator scores prose, which is the intended coverage beyond the guard.

Visibility (design §1.1, D-V adopted provisionally): in the valid twin the figure's labelled values are its
answers, and the fault twin shows wrong answers at the same labels (contrasting); the prior fit shows the answers
in both twins (shared evidence, E-126). Every such location is declared and both twins carry
visibility_waiver_pending. The oracle is the counting oracle; convention values are the pre-fit Asimov limits
outside the tolerance (the median moves by -5.3 %; the observed limit by -0.41 %, inside). Standard library
only; nothing here is empirical evidence.
"""
from __future__ import annotations

from pathlib import Path

from governance.canonical import require
from governance.oracle import counting
from governance.tasks import builder, registry

FAMILY = "limit_summary"
PAIR_ID = "hv-p1"
VALID, FAULT = builder.pair_task_ids("hv", PAIR_ID)
TOLERANCE = 0.005
REQUEST_PATH = Path(__file__).with_name("request.md")
COUNTS = {"n_obs": 73, "background": 58.0, "background_uncertainty": 7.0}
POI_CAP = 256.0
OBSERVED, MEDIAN = "Observed", "Expected (median)"
LEGENDS = {   # series -> (label, plotted fit field); the fault twin swaps the labels (a common plotting bug)
    "valid": [{"series": "solid", "label": OBSERVED, "field": "obs_limit_events"},
              {"series": "dashed", "label": MEDIAN, "field": "exp_limits_events[2]"}],
    "fault": [{"series": "solid", "label": MEDIAN, "field": "obs_limit_events"},
              {"series": "dashed", "label": OBSERVED, "field": "exp_limits_events[2]"}]}
LABEL_ROLES = {OBSERVED: "obs_limit_events", MEDIAN: "exp_limits_events[2]"}   # which endpoint a label names
KINDS = {"workspace.json": "workspace"}
SOURCE = {"kind": "synthetic_development", "license": "Apache-2.0", "citation": None,
          "provenance": "RAVEL synthetic development fixture (WP12 task-bank design P6); no real dataset or analysis",
          "modifications": []}
OBJECTIVE = ("Report the observed and median expected 95% CLs event-count limits of the supplied counting likelihood "
             "with their roles, and a caption for the earlier session's summary figure.")
UNITS = {"background": "events", "event_count_limits": "events", "observed_count": "events"}
LIMIT_FIELDS = ["obs_limit_events", *(f"exp_limits_events[{i}]" for i in range(5))]
ENDPOINTS = [
    {"field": "obs_limit_events", "role": "observed", "unit": "events", "relation": "eq", "metric": "relative_error",
     "tolerance": TOLERANCE, "evidence_constraint": None},
    {"field": "exp_limits_events[2]", "role": "expected", "unit": "events", "relation": "eq",
     "metric": "relative_error", "tolerance": TOLERANCE, "evidence_constraint": None}]
PAIRS = [{"id": PAIR_ID, "valid": VALID, "fault": FAULT, "exposure_class": "role_label_provenance",
          "naive": "transcribe_legend"}]
CONTRASTS = [{"id": PAIR_ID, "valid": VALID, "fault": FAULT, "exposure_class": "role_label_provenance",
              "fault_inputs": ["prior:figure"]}]
SPEC = {
    "family": FAMILY, "request": REQUEST_PATH.name, "oracle_kind": "counting",
    "approval_mode": "pre_authorized_operations",
    "input_kinds": {"workspace": registry.INPUT_KINDS["workspace"]},
    "stages": ["fit", "figure"],
    "artifact_fields": [f for f, s in registry.ARTIFACT_FIELDS.items() if s["artifact"] == "fit"],
    "prior_recipe": [{"op": "fit", "params": {}}, {"op": "figure", "params": {"legend": LEGENDS["valid"]}}],
    "pairs": PAIRS, "contrasts": CONTRASTS, "scoring_profile": FAMILY,
}


def _rel():
    return {"metric": "relative_error", "value": TOLERANCE}


def inputs() -> dict:
    """The input bytes (both twins, current and prior): the counting workspace."""
    return {"workspace.json": builder.pretty(builder.counting_workspace(*COUNTS.values(), POI_CAP))}


def prior_recipe(variant) -> list:
    return [{"op": "fit", "params": {}}, {"op": "figure", "params": {"legend": [dict(e) for e in LEGENDS[variant]]}}]


def _field(side, field):
    key, _, rest = field.partition("[")
    return side[key][int(rest[:-1])] if rest else side[key]


def _task(variant, side):
    task_id = VALID if variant == "valid" else FAULT
    status = side["limit_status"]
    require(status["observed"] == "resolved" and all(s == "resolved" for s in status["expected"]),
            f"{task_id}: every limit must resolve within [0, {POI_CAP:g}]")
    scored = {f: _field(side, f) for f in LIMIT_FIELDS}
    tolerances = {f: _rel() for f in LIMIT_FIELDS}
    builder.check_role_separation(task_id, scored, tolerances, LIMIT_FIELDS)
    obs, median = scored["obs_limit_events"], scored["exp_limits_events[2]"]
    faults = [builder.fault_value("swapped_roles", "role_error", "obs_limit_events", median, _rel(),
                                  note="the observed and median expected limits delivered with their roles swapped "
                                       "(the fault twin's legend, copied)"),
              builder.fault_value("swapped_roles", "role_error", "exp_limits_events[2]", obs, _rel(),
                                  note="the observed and median expected limits delivered with their roles swapped")]
    convention = counting.convention_limits(*COUNTS.values(), poi_cap=POI_CAP)
    conventions = [builder.convention_value("prefit_asimov", f, float(f"{_field(convention, f):.9e}"))
                   for f in LIMIT_FIELDS
                   if abs(_field(convention, f) - scored[f]) > TOLERANCE * abs(scored[f])]
    collisions = builder.check_values(task_id, scored, tolerances, faults, conventions)
    legend = [{"series": e["series"], "label": e["label"], "limit_events": f"{_field(side, e['field']):.4g}"}
              for e in LEGENDS[variant]]
    shown = {f"the prior figure's legend value labelled {label}": {
                 "provenance": "prior_artifact",
                 "values": {LABEL_ROLES[label]: float(next(e["limit_events"] for e in legend if e["label"] == label))}}
             for label in (OBSERVED, MEDIAN)}
    shown["the prior fit"] = {"provenance": "prior_artifact",
                              "values": {e["field"]: scored[e["field"]] for e in ENDPOINTS}}
    oracle = {**counting.oracle_record(inputs(), inputs()), "family": FAMILY, "task_id": task_id,
              "bank_version": registry.BANK_VERSION,
              "endpoint_values": {e["field"]: scored[e["field"]] for e in ENDPOINTS}, "scored_values": scored,
              "fault_values": faults, "convention_values": conventions, "collisions": collisions,
              "excluded_conventions": [{"convention": "toy_cls", "reason": "excluded by the pinned estimand clause "
                                        "'asymptotic q-tilde, computed with the task tool' (E-118)"}],
              "prior_figure": {"legend": legend, "labels_match_series": variant == "valid"}}
    return {
        "task_id": task_id, "variant": variant, "pair_id": PAIR_ID, "twin": FAULT if variant == "valid" else VALID,
        "expected": "complete", "exposure_class": "role_label_provenance",
        "label": "legend correct" if variant == "valid" else "legend swapped", "objective": OBJECTIVE,
        "inputs": inputs(), "kinds": dict(KINDS), "prior_inputs": inputs(), "prior_kinds": dict(KINDS),
        "prior_recipe": prior_recipe(variant), "units": dict(UNITS), "oracle_kind": "counting",
        "approval_mode": "pre_authorized_operations", "endpoints": [dict(e) for e in ENDPOINTS],
        "fidelity": {"metric": "relative_error", "quantity": "obs_limit_events", "tolerance": TOLERANCE},
        "diagnostic_tolerance": None, "required_title": None, "reuse_plan": {"fit": "reuse"},
        "refusal_conditions": [], "source": SOURCE, "oracle": oracle,
        "answers": {e["field"]: scored[e["field"]] for e in ENDPOINTS},
        "tolerances": {e["field"]: _rel() for e in ENDPOINTS}, "shown": shown,
        "canary_values": list(scored.values()) + [c["value"] for c in conventions]}


def build_family(out_dir, *, canary=None, budget=None) -> dict:
    """Write the family's evaluator tree into a new or empty ``out_dir`` (tasks.builder.build); return its index."""
    side = counting.oracle_record(inputs())["current"]
    tasks = sorted((_task(variant, side) for variant in ("valid", "fault")), key=lambda task: task["task_id"])
    return builder.build(out_dir, spec=SPEC, request_path=REQUEST_PATH, tasks=tasks, canary=canary, budget=budget,
                         index_extra={"source": SOURCE, "tolerance": TOLERANCE,
                                      "effect_metric": "fault values against the oracle values "
                                                       "(builder.check_values); role separation of the six limits"})
