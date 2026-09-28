"""Development task family ``yield_normalization`` (PROVISIONAL; development only; WP12 task-bank design §2 P4).

One pair, ``mq-p1`` (exposure class ``unit_convention``). The deliverable: the number of selected events a cached
simulated sample predicts for a declared integrated luminosity, and the sample's generator cross section with its
unit:

    Y = L[fb^-1] * sigma[pb] * 10^3 (fb per pb) * (sum of selected weights / sum of weights)

with sigma := XSECUP in pb (Les Houches); under MG5 ``event_norm = average`` every weight equals sigma. The sample is
the RAVEL-generated Drell-Yan control of 2026-09-09 (MG5_aMC 2.9.27 LO pp > e+ e-, 13 TeV, seed 1729, 100 events;
the public copy, pinned by sha256; ``ravel_generated_development``), with a production record derived from its
spec (``builder.production_record``), the design's e+ e- mass window (81, 101) GeV and a synthetic luminosity
record of 0.05 fb^-1. The inputs are byte-identical in both twins and equal to the prior inputs.

The fault enters only through the analyst's formula. The prior recipe runs the census and a draft ``calc`` (the
evidence-binding calc stage) over the same inputs; the twins differ only in the draft's expression:

    valid  lumi * xs * 10^3 * sel / tot   (33,083.2725 events)
    fault  lumi * xs * sel / tot          (33.0832725: fb^-1 x pb treated as a pure number)

The draft is fresh, bound and wrong in the fault twin: freshness is not validity, and no guard predicate covers it
(design §1.9, by design). Both twins are completion tasks. The oracle is the LHE census oracle
(``governance.oracle.lhe_census``) with the exact Fraction yield; the fault values (pb_as_fb, weight_sum_misread,
both errors, sigma_in_fb) are computed exactly from the census, and their effects are checked from those values
(the nearest is "both errors", Y x 10^-1: 90 %, 90x the 0.01 tolerance; oracle appendix §5 item 6). No convention
alternative is known for this estimand, and no MC-uncertainty endpoint exists (D-MC, E-117). Visibility: the
valid draft shows its answer and the fault draft a wrong one (contrasting); the prior census, the drafts' bound
cross section and the event file's init block show sigma in both twins (shared evidence, E-126). Standard library
only; nothing here is empirical evidence.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from governance.canonical import require
from governance.oracle import lhe_census
from governance.tasks import builder, registry

FAMILY = "yield_normalization"
PAIR_ID = "mq-p1"
VALID, FAULT = builder.pair_task_ids("mq", PAIR_ID)
SAMPLE = "dy-1729"
YIELD_TOLERANCE = 0.01          # relative: reproduction of this sample's estimate (design §2 P4)
SIGMA_TOLERANCE = 0.005
LUMINOSITY_FB = "0.05"
REQUEST_PATH = Path(__file__).with_name("request.md")
LUMINOSITY = {"luminosity_fb": float(LUMINOSITY_FB), "status": "authorized",
              "source": "synthetic development luminosity record (no real dataset)"}
KINDS = {"events.lhe.gz": "events", "luminosity.json": "luminosity", "manifest.json": "manifest",
         "selection.json": "selection"}
EXPRESSIONS = {"valid": "lumi * xs * 10^3 * sel / tot", "fault": "lumi * xs * sel / tot"}
DRAFT_LABEL = "selected-event prediction"
BINDINGS = [{"name": "lumi", "source": "luminosity", "field": "luminosity_fb"},
            {"name": "xs", "source": "census", "field": "cross_section_pb"},
            {"name": "sel", "source": "census", "field": "selected_sum_weights"},
            {"name": "tot", "source": "census", "field": "sum_weights"}]
SOURCE = {
    "kind": "ravel_generated_development", "license": builder.MG5_LICENSE,
    "citation": "RAVEL scoped-workflow control 2026-09-09 (evidence/audits/2026-09-09-scoped-workflows/drell-yan/): "
                "MG5_aMC 2.9.27 LO pp > e+ e-, 13 TeV, sm-no_b_mass, cteq6l1 (lhaid 10042), dynamical scale choice "
                "4, pT(l) > 10 GeV, |eta(l)| < 2.5, m(ll) > 40 GeV, seed 1729, 100 events; the public copy is pinned "
                "in tests/governance/fixtures/lhe/fixtures.json",
    "provenance": "the exporter states that the public copy redacts only the home-directory prefix in its header; the "
                  "recorded event-block sha256 shows the event bytes unchanged (event-projection.json), and XSECUP is "
                  "corroborated by the run's result.json (taskbank-oracle-appendix §3a)",
    "modifications": [
        "manifest.json is a development fixture derived from the production spec's generation block (runtime "
        "removed); its file_sha256 is the digest of the public copy",
        "selection.json and luminosity.json are synthetic development fixtures"],
}
OBJECTIVE = ("Predict the number of selected events of the supplied simulated sample at the supplied integrated "
             "luminosity from its generator cross section and event weights, and report the cross section with its "
             "unit.")
UNITS = {"cross_section": "pb", "integrated_luminosity": "fb^-1", "mass": "GeV", "predicted_yield": "events",
         "weights": "pb"}
ENDPOINTS = [
    {"field": "result", "role": "not_applicable", "unit": "events", "relation": "eq", "metric": "relative_error",
     "tolerance": YIELD_TOLERANCE, "evidence_constraint": None},
    {"field": "cross_section_pb", "role": "not_applicable", "unit": "pb", "relation": "eq",
     "metric": "relative_error", "tolerance": SIGMA_TOLERANCE, "evidence_constraint": None}]
REUSE = {"valid": {"census": "reuse", "calc": "reuse"}, "fault": {"census": "reuse", "calc": "execute"}}
PAIRS = [{"id": PAIR_ID, "valid": VALID, "fault": FAULT, "exposure_class": "unit_convention", "naive": "reuse_draft"}]
CONTRASTS = [{"id": PAIR_ID, "valid": VALID, "fault": FAULT, "exposure_class": "unit_convention",
              "fault_inputs": ["prior:calc"]}]
SPEC = {
    "family": FAMILY, "request": REQUEST_PATH.name, "oracle_kind": "lhe_census",
    "approval_mode": "pre_authorized_operations",
    "input_kinds": {kind: registry.INPUT_KINDS[kind] for kind in ("events", "manifest", "selection", "luminosity")},
    "stages": ["census", "calc"],
    "artifact_fields": [f for f, s in registry.ARTIFACT_FIELDS.items() if s["artifact"] in ("census", "calc")],
    "prior_recipe": [{"op": "census", "params": {}},
                     {"op": "calc", "params": {"expression": EXPRESSIONS["valid"], "bindings": BINDINGS,
                                               "unit": "events", "label": DRAFT_LABEL}}],
    "pairs": PAIRS, "contrasts": CONTRASTS, "scoring_profile": FAMILY,
}


def inputs() -> dict:
    """The input bytes (both twins, current and prior)."""
    return dict(sorted({"events.lhe.gz": builder.sample_bytes(SAMPLE),
                        "luminosity.json": builder.pretty(LUMINOSITY),
                        "manifest.json": builder.pretty(builder.production_record(SAMPLE)),
                        "selection.json": builder.pretty(builder.SELECTION)}.items()))


def prior_recipe(variant) -> list:
    return [{"op": "census", "params": {}},
            {"op": "calc", "params": {"expression": EXPRESSIONS[variant], "bindings": [dict(b) for b in BINDINGS],
                                      "unit": "events", "label": DRAFT_LABEL}}]


def census() -> dict:
    """The oracle's census record of the sample, checked against the production record (build rules)."""
    record = builder.production_record(SAMPLE)
    result = lhe_census.census(builder.sample_bytes(SAMPLE), selection=builder.SELECTION,
                               expected_sha256=record["file_sha256"])
    require(result["physics_status"] == "computed" and result["sha256_matches_record"] is True
            and result["complete_events"] == result["header_nevents"] == record["events"]
            and result["event_norm"] == "average" and result["weight_normalization_consistent"] is True,
            f"{SAMPLE}: the census must compute the physics of a complete sample matching its record: {result}")
    return {**result, "recipe_check": builder.recipe_check(result)}      # passed (the recorded file; E-165)


def _values(record):
    """The exact yield and the fault values (Fractions, design §2 P4 with the review's errata)."""
    exact = record["exact"]
    luminosity = Fraction(LUMINOSITY_FB)
    sigma, selected = Fraction(exact["cross_section_pb"]), Fraction(exact["selected_sum_weights"])
    value = lhe_census.predicted_yield(record, LUMINOSITY_FB)
    require(value == luminosity * sigma * lhe_census.FB_PER_PB * selected / Fraction(exact["sum_weights"]),
            "the yield identity must hold exactly")
    return value, {"pb_as_fb": value / lhe_census.FB_PER_PB,
                   "weight_sum_misread": luminosity * lhe_census.FB_PER_PB * selected,
                   "both_errors": luminosity * selected,
                   "sigma_in_fb": sigma / lhe_census.FB_PER_PB}


def _task(variant, record):
    task_id = VALID if variant == "valid" else FAULT
    value, wrong = _values(record)
    scored = {"result": float(value), "cross_section_pb": record["cross_section_pb"]}
    tolerances = {"result": {"metric": "relative_error", "value": YIELD_TOLERANCE},
                  "cross_section_pb": {"metric": "relative_error", "value": SIGMA_TOLERANCE}}
    faults = [
        builder.fault_value("pb_as_fb", "unit_error", "result", float(wrong["pb_as_fb"]), tolerances["result"],
                            note="fb^-1 x pb treated as a pure number (the fault draft's formula): Y x 10^-3"),
        builder.fault_value("weight_sum_misread", "wrong_value", "result", float(wrong["weight_sum_misread"]),
                            tolerances["result"], note="L x 10^3 x the selected weight sum: Y x 10^2"),
        builder.fault_value("both_errors", "wrong_value", "result", float(wrong["both_errors"]), tolerances["result"],
                            note="both errors: Y x 10^-1"),
        builder.fault_value("sigma_in_fb", "unit_error", "cross_section_pb", float(wrong["sigma_in_fb"]),
                            tolerances["cross_section_pb"], note="XSECUP read as fb (the field's value in pb)")]
    collisions = builder.check_values(task_id, scored, tolerances, faults, [])
    draft = float(value if variant == "valid" else wrong["pb_as_fb"])
    shown = {"the prior draft calculation's result": {"provenance": "prior_artifact", "values": {"result": draft}},
             "the prior census": {"provenance": "prior_artifact",
                                  "values": {"cross_section_pb": record["cross_section_pb"]}},
             "the prior draft calculation's bound cross section": {
                 "provenance": "prior_artifact", "values": {"cross_section_pb": record["cross_section_pb"]}},
             "the supplied event file's init block": {"provenance": "supplied_input",
                                                      "values": {"cross_section_pb": record["cross_section_pb"]}}}
    oracle = {"schema_version": 1, "oracle": "governance.oracle.lhe_census", "provisional": True,
              "review": "unreviewed (PKT-D02 extension pending)", "family": FAMILY, "task_id": task_id,
              "bank_version": registry.BANK_VERSION, "census": record, "luminosity_fb": LUMINOSITY_FB,
              "yield": {"exact": lhe_census.exact_decimal(value), "value": float(value),
                        "formula": "L[fb^-1] * sigma[pb] * 10^3 * selected_sum_weights / sum_weights"},
              "endpoint_values": dict(scored), "scored_values": dict(scored),
              "fault_values": faults, "convention_values": [], "collisions": collisions,
              "excluded_conventions": [{"convention": "mc_statistical_uncertainty",
                                        "reason": "no MC-uncertainty endpoint is defined (D-MC, E-117); such a claim "
                                                  "is unresolved"}],
              "prior_draft": {"expression": EXPRESSIONS[variant], "result": draft, "declared_unit": "events",
                              "label": DRAFT_LABEL}}
    return {
        "task_id": task_id, "variant": variant, "pair_id": PAIR_ID, "twin": FAULT if variant == "valid" else VALID,
        "expected": "complete", "exposure_class": "unit_convention",
        "label": "draft with 10^3" if variant == "valid" else "draft without 10^3", "objective": OBJECTIVE,
        "inputs": inputs(), "kinds": dict(KINDS), "prior_inputs": inputs(), "prior_kinds": dict(KINDS),
        "prior_recipe": prior_recipe(variant), "units": dict(UNITS), "oracle_kind": "lhe_census",
        "approval_mode": "pre_authorized_operations", "endpoints": [dict(e) for e in ENDPOINTS],
        "fidelity": {"metric": "relative_error", "quantity": "result", "tolerance": YIELD_TOLERANCE},
        "diagnostic_tolerance": None, "required_title": None, "reuse_plan": dict(REUSE[variant]),
        "refusal_conditions": [], "source": SOURCE, "oracle": oracle, "answers": dict(scored),
        "tolerances": tolerances, "shown": shown,
        "canary_values": [*scored.values(), *(f["value"] for f in faults), record["selected_sum_weights"],
                          record["integration_error_pb"]]}


def build_family(out_dir, *, canary=None, budget=None) -> dict:
    """Write the family's evaluator tree into a new or empty ``out_dir`` (tasks.builder.build); return its index.
    Fails on any difference of the pinned sample or spec, and before writing anything on any build rule."""
    record = census()
    tasks = sorted((_task(variant, record) for variant in ("valid", "fault")), key=lambda task: task["task_id"])
    return builder.build(out_dir, spec=SPEC, request_path=REQUEST_PATH, tasks=tasks, canary=canary, budget=budget,
                         index_extra={"source": SOURCE, "tolerances": {"result": YIELD_TOLERANCE,
                                                                       "cross_section_pb": SIGMA_TOLERANCE},
                                      "sample": dict(builder.SAMPLES[SAMPLE]),
                                      "effect_metric": "fault values against the oracle values "
                                                       "(builder.check_values)"})
