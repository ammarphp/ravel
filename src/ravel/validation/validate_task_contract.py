#!/usr/bin/env python3
"""Validate a task_contract.json against the binding schema (docs/reference/scope.md).

The task contract is the machine artifact that classifies a physicist request BEFORE any
compute: route_prompt.py writes it, this validator gates it, CHECK-IN 1 presents it. A
contract that fails validation must not proceed to generation (charter section 4.4).

Stdlib-only on purpose: any session (any conda env, or none) can run it.

Usage:
  validate_task_contract.py <contract.json>     # exit 0 = valid, exit 1 + itemized errors
  validate_task_contract.py --legacy <contract.json> # archive audit only, warns on waiver
  validate_task_contract.py --schema            # print the schema (JSON)
  validate_task_contract.py --selftest          # validate embedded good/bad examples
"""
# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"

import json
import math
import re
import sys
import warnings

TASK_MODES = (
    "survey", "reproduce", "reinterpret", "projection", "scan",
    "summary_plot", "anomaly_search", "no_routine", "unsupported",
)
DETECTOR_MODES = (
    "particle-level", "rivet-smearing", "simpleanalysis-delphes-native", "container",
    "effmap-folded",  # published per-object efficiency maps folded over truth objects (D2)
    # Delphes fast-sim driving a CUSTOM selection with no certified routine (Option-C detector
    # variant; CR-134, adjudication §II.4 item 6): labeled proxy, never an exclusion of record
    # until per-SR acc*eff certification vs published anchors closes
    "delphes-custom-uncertified",
    "TBD-judgment",   # a weak model may leave the choice to the physicist/CHECK-IN 1
)
STAT_MODES = (  # canonical source: result_pack.py STAT_MODES + the routing placeholder
    "published-likelihood", "simplified-likelihood", "best-sr-counting", "combined-counting",
    "stability-only", "shape-fit", "blocked-shape-fit", "sensitivity-expected-only", "none-survey",
    "TBD-judgment",
)
COMPUTE_PLANS = ("none", "dry", "smoke", "full", "scan")

# Version-1 compatibility is deliberately explicit. Historical contracts omit targets,
# and compact cost estimates omit disk/events/backend metadata. The SVJ trial also has
# TWO named walltime scenarios instead of walltime_h. These existing representations
# remain supported and checked, without filling in absent physics or budget numbers.
# Missing/unknown versions, unknown keys, arbitrary JSON extensions, and malformed
# historical fields are never grandfathered. Full provenance/approval is a lifecycle
# obligation; passing this structural gate does not establish physics validity.
COMPATIBILITY_POLICY = (
    "Version-1 compatibility: targets and pre-full/scan cost estimates remain optional. "
    "A supplied cost estimate requires mode and a walltime interval; full/scan also "
    "require points. Explicit --legacy / validate(..., legacy=True) archive auditing may "
    "waive only absent points when a nonblank note and disk_gb_peak exist; it warns and "
    "does not infer a count. Live workflow/approval callers use strict default validation. "
    "Historical compact estimates need not include disk/events/backend. "
    "The documented SVJ format may instead supply BOTH walltime_h_naive and "
    "walltime_h_with_lhe_reuse with lhe_reuse_note; both ranges are validated. "
    "Historical annotations are explicitly typed properties, not an open extension bag. "
    "No missing/unknown schema version is accepted and no input is coerced or filled in."
)


def _object(properties, required=(), additional=False):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": additional}


def _array(items):
    return {"type": "array", "items": items}


def _enum(values):
    return {"type": "string", "enum": list(values)}


_TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
_TEXTS = _array(_TEXT)
_NONNEG = {"type": "number", "minimum": 0}
_POSITIVE = {"type": "number", "exclusiveMinimum": 0}
_COUNT = {"type": "integer", "minimum": 1}
_INTERVAL = {"type": "array", "items": _NONNEG, "minItems": 2, "maxItems": 2,
             "$comment": "Additionally validate lower <= upper in validate()."}
_TRAP_ID = {"type": "string", "pattern": r"^T[1-9][0-9]*$"}
_TRAP_HIT = {"anyOf": [
    _TRAP_ID,
    _object({"id": _TRAP_ID, "evidence": _TEXT, "consequence": _TEXT,
             "flag_number": {"anyOf": [_COUNT, {"type": "string", "pattern": r"^F[1-9][0-9]*$"}]}},
            ("id", "evidence", "consequence", "flag_number")),
]}
_TARGETS = _object({
    "model": {"anyOf": [_TEXT, {"type": "null"}]},
    "process": {"anyOf": [_TEXT, {"type": "null"}]},
    **{key: _TEXTS for key in ("analysis", "arxiv", "inspire", "figures")},
    "masses_gev": _array(_NONNEG),  # zero is physical; no invented mass/model upper bound
    "lumi_fb": {"anyOf": [_POSITIVE, {"type": "null"}]},
    "mass_floor_note": _TEXT,
})
_COST = _object({
    "mode": _enum(COMPUTE_PLANS),
    **{key: _COUNT for key in ("points", "events_per_point", "parallel")},
    "backend": _enum(("native", "container")),
    **{key: _INTERVAL for key in ("walltime_h", "per_point_min", "walltime_h_naive",
                                  "walltime_h_with_lhe_reuse")},
    "disk_gb_peak": _NONNEG,
    **{key: _TEXT for key in ("note", "disk_note", "warning", "cpu_note", "ladder",
                              "lhe_reuse_note", "proposed_primary_grid")},
    "waypoint_smoke": _object({"walltime_h": _INTERVAL, "disk_gb": _NONNEG},
                               ("walltime_h", "disk_gb")),
    "schema_version": {"type": "integer", "const": 1},
    "generated_by": {"type": "string", "const": "cost_preflight.py"},
    "generated_utc": {"type": "string"},  # emitter allows an empty deterministic timestamp
}, ("mode",))
_COST["anyOf"] = [
    {"required": ["walltime_h"]},
    {"required": ["walltime_h_naive", "walltime_h_with_lhe_reuse", "lhe_reuse_note"]},
]

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Ravel task contract, version 1",
    "$comment": COMPATIBILITY_POLICY + " The stdlib validator additionally rejects "
                "non-finite Python floats, requires exact integer types (1.0 is rejected), "
                "checks interval ordering and cross-field compute consistency. The JSON "
                "reader rejects duplicate keys and non-standard numeric literals.",
    **_object({
        "schema_version": {"type": "integer", "const": 1},
        "prompt": _TEXT,
        "task_mode": _enum(TASK_MODES),
        "detector_mode": _enum(DETECTOR_MODES),
        "stat_mode": _enum(STAT_MODES),
        "required_user_inputs": _TEXTS,
        "assumptions": _TEXTS,
        "compute_plan": _enum(COMPUTE_PLANS),
        "approval_required": {"type": "boolean", "const": True},
        "targets": _TARGETS,
        "cost_estimate": _COST,
        "blocking": _TEXTS,
        "escalate": _TEXTS,
        **{key: _TEXT for key in ("notes", "validation_oracle", "deliverable", "stat_mode_note")},
        "traps_checked": _array(_TRAP_ID),
        "traps_hit": _array(_TRAP_HIT),
        "traps_noted_generation_side": _TEXTS,
        "traps_procedural": _array(_object({"id": _TRAP_ID, "note": _TEXT}, ("id", "note"))),
        "option_c_caps": _TEXTS,
        "channels_under_consideration": _object({}, additional=_TEXT),
        "published_dark_sector_fixed": _object({
            **{key: _NONNEG for key in ("m_qdark_gev", "m_pid_diagonal_gev",
                "m_pid_offdiagonal_gev", "m_rhod_diagonal_gev", "m_rhod_offdiagonal_gev")},
            "Lambda_d_gev": _POSITIVE, "nFlav_HV": _COUNT,
            **{key: _TEXT for key in ("Lambda_d_note", "alpha_dark", "correction_note")},
        }),
    }, ("schema_version", "prompt", "task_mode", "detector_mode", "stat_mode",
        "required_user_inputs", "assumptions", "compute_plan", "approval_required")),
}


def _schema_errors(value, schema, path):
    """Evaluate ONLY the JSON Schema keywords used above, with exact Python types.

    This is not a general-purpose JSON Schema library. Keeping the small structural
    gate stdlib-only lets hooks validate intake before a scientific env is installed.
    """
    errs = []
    typ = schema.get("type")
    expected = {"object": (dict,), "array": (list,), "string": (str,),
                "integer": (int,), "number": (int, float), "boolean": (bool,),
                "null": (type(None),)}
    if typ is not None and type(value) not in expected[typ]:
        return [f"{path} must be {typ}, got {type(value).__name__}"]
    if type(value) is float and not math.isfinite(value):
        return [f"{path} must be finite, got {value!r}"]
    if "anyOf" in schema:
        choices = [_schema_errors(value, option, path) for option in schema["anyOf"]]
        if all(choices):
            errs.append(f"{path} does not match an allowed format: " +
                        " OR ".join("; ".join(option) for option in choices))
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        errs.append(f"{path} must be literally {json.dumps(schema['const'])}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path} {value!r} not in {tuple(schema['enum'])}")
    if type(value) is dict:
        for key in schema.get("required", ()):
            if key not in value:
                errs.append(f"{path} missing required field '{key}'")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if type(key) is not str or not key.strip():
                errs.append(f"{path} object keys must be nonblank strings")
            elif key in properties:
                errs.extend(_schema_errors(item, properties[key], f"{path}.{key}"))
            elif additional is False:
                errs.append(f"{path}.{key} is an unknown field")
            elif type(additional) is dict:
                errs.extend(_schema_errors(item, additional, f"{path}.{key}"))
    if type(value) is list:
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            errs.append(f"{path} must have {schema.get('minItems', 0)} to "
                        f"{schema.get('maxItems', 'unbounded')} entries")
        if "items" in schema:
            for i, item in enumerate(value):
                errs.extend(_schema_errors(item, schema["items"], f"{path}[{i}]"))
    if type(value) is str:
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{path} must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path} does not match {schema['pattern']!r}")
    if type(value) in (int, float):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path} must be >= {schema['minimum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errs.append(f"{path} must be > {schema['exclusiveMinimum']}")
    return errs


def validate(c, *, legacy=False):
    """Return errors without changing inputs; legacy=True is an explicit archive audit.

    A legacy waiver emits a UserWarning and applies only to missing point-count metadata
    in an otherwise typed cost estimate with disk and explanatory note. It never waives
    versions, malformed fields, non-finite values, compute consistency, or approval.
    """
    if type(legacy) is not bool:
        return ["legacy must be a boolean archive-audit option"]
    errs = _schema_errors(c, SCHEMA, "contract")
    if errs:
        return errs  # malformed structures must never reach type-assuming cross-field logic
    tm, sm, cp = c["task_mode"], c["stat_mode"], c["compute_plan"]
    if tm == "unsupported":
        if not c.get("blocking"):
            errs.append("task_mode=unsupported requires 'blocking' to NAME the refusal line "
                        "(PRODUCT-CONTRACT section 6)")
        if cp in ("smoke", "full", "scan"):
            errs.append("task_mode=unsupported cannot request generation (compute_plan=smoke|full|scan)")
    if sm == "blocked-shape-fit" and cp in ("full", "scan"):
        errs.append("stat_mode=blocked-shape-fit cannot carry compute_plan=full|scan — the "
                    "statistical paradigm is refused; offer the sensitivity-expected-only path")
    if tm in ("survey", "summary_plot") and cp in ("full", "scan"):
        errs.append(f"task_mode={tm} is a no-generation mode; compute_plan must be none|dry|smoke")
    cost = c.get("cost_estimate")
    if cp in ("full", "scan") and cost is None:
        errs.append(f"compute_plan={cp} requires a cost_estimate (run cost_preflight.py)")
    if cost is not None:
        if cost["mode"] != cp:
            errs.append(f"cost_estimate.mode={cost['mode']} does not match compute_plan={cp}")
        if cp in ("full", "scan") and "points" not in cost:
            if legacy and "note" in cost and "disk_gb_peak" in cost:
                warnings.warn("ARCHIVE ONLY: cost_estimate.points is absent; explicit legacy "
                              "audit accepts the historical budget note without inferring "
                              "a count. This is not a valid live-compute contract.",
                              UserWarning, stacklevel=2)
            else:
                errs.append(f"cost_estimate.points is required for compute_plan={cp}")
        intervals = {f"cost_estimate.{key}": cost[key] for key in
                     ("walltime_h", "per_point_min", "walltime_h_naive", "walltime_h_with_lhe_reuse")
                     if key in cost}
        if "waypoint_smoke" in cost:
            intervals["cost_estimate.waypoint_smoke.walltime_h"] = cost["waypoint_smoke"]["walltime_h"]
        for path, (lo, hi) in intervals.items():
            if lo > hi:
                errs.append(f"{path} must be ordered [lower, upper]")
            if cp in ("full", "scan") and ".walltime_h" in path and hi == 0:
                errs.append(f"{path} must have a positive upper estimate for compute_plan={cp}")
    return errs


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON object key {key!r}")
        obj[key] = value
    return obj


def _reject_constant(value):
    raise ValueError(f"non-finite JSON numeric literal {value}")


def load_contract(path):
    """Read unambiguous standards-compliant JSON; validate() still checks its schema."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def selftest():
    good = {
        "schema_version": 1,
        "prompt": "Initiate: reproduce Figure 3 of the slepton search vs the slepton-bino model",
        "task_mode": "reproduce", "detector_mode": "simpleanalysis-delphes-native",
        "stat_mode": "published-likelihood",
        "required_user_inputs": [], "assumptions": ["F1: NLO+NLL k-factors from the WG grid"],
        "compute_plan": "scan", "approval_required": True,
        "cost_estimate": {"mode": "scan", "points": 52, "walltime_h": [6.5, 10.8]},
    }
    bads = [
        ({**good, "approval_required": False}, "approval_required"),
        ({**good, "schema_version": True}, "schema_version"),
        ({**good, "schema_version": 2}, "schema_version"),
        ({k: v for k, v in good.items() if k != "schema_version"}, "schema_version"),
        ({**good, "task_mode": "discovery"}, "task_mode"),
        ({**good, "task_mode": "unsupported"}, "blocking"),
        ({**good, "stat_mode": "blocked-shape-fit"}, "blocked-shape-fit"),
        ({**good, "compute_plan": "scan", "cost_estimate": None}, "cost_estimate"),
        ({k: v for k, v in good.items() if k != "assumptions"}, "assumptions"),
        ({**good, "targets": {"masses_gev": [True]}}, "masses_gev"),
        ({**good, "targets": {"lumi_fb": -139}}, "lumi_fb"),
        ({**good, "cost_estimate": "approved"}, "cost_estimate"),
        ({**good, "cost_estimate": {"mode": "scan", "points": False,
                                   "walltime_h": [1, 2]}}, "points"),
        ({**good, "cost_estimate": {"mode": "scan", "points": 52,
                                   "walltime_h": [float("nan"), 2]}}, "walltime_h"),
        ({**good, "cost_estimate": {"mode": "scan", "points": 52,
                                   "walltime_h": [2, 1]}}, "walltime_h"),
        ({**good, "cost_estimate": {"mode": "none", "points": 52,
                                   "walltime_h": [1, 2]}}, "cost_estimate.mode"),
        ({**good, "approval_require": False}, "approval_require"),
    ]
    # CR-134: the custom-uncertified-Delphes route is a first-class contract value
    good_custom = {**good, "detector_mode": "delphes-custom-uncertified",
                   "stat_mode": "sensitivity-expected-only", "compute_plan": "smoke",
                   "cost_estimate": {"mode": "smoke", "walltime_h": [0.1, 0.35]}}
    for g in (good, good_custom):
        errs = validate(g)
        if errs:
            sys.exit(f"selftest FAILED: a good contract did not validate: {errs}")
    for bad, needle in bads:
        errs = validate(bad)
        if not errs or not any(needle in e for e in errs):
            sys.exit(f"selftest FAILED: expected an error mentioning {needle!r}, got {errs}")
    print(f"validate_task_contract selftest: 2 good + {len(bads)} bad contracts judged correctly.")


def main():
    args = sys.argv[1:]
    legacy = len(args) == 2 and args[0] == "--legacy"
    if legacy:
        args = args[1:]
    if len(args) != 1:
        sys.exit(__doc__)
    if args[0] == "--schema" and not legacy:
        print(json.dumps(SCHEMA, indent=2))
        return
    if args[0] == "--selftest" and not legacy:
        selftest()
        return
    try:
        contract = load_contract(args[0])
    except (OSError, ValueError, UnicodeError, RecursionError) as e:
        sys.exit(f"validate_task_contract: cannot read {args[0]}: {e}")
    errs = validate(contract, legacy=legacy)
    if errs:
        print(f"INVALID task contract ({args[0]}):")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    label = "archive-compatible task contract (NOT live-compute validation)" if legacy else "valid task contract"
    print(f"{label}: task_mode={contract['task_mode']} "
          f"detector_mode={contract['detector_mode']} stat_mode={contract['stat_mode']} "
          f"compute_plan={contract['compute_plan']} (approval required)")


if __name__ == "__main__":
    main()
