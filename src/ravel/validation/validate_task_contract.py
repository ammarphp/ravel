#!/usr/bin/env python3
"""Validate a task_contract.json against the binding schema (docs/reference/scope.md).

The task contract is the machine artifact that classifies a physicist request BEFORE any
compute: route_prompt.py writes it, this validator gates it, CHECK-IN 1 presents it. A
contract that fails validation must not proceed to generation.

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
    "summary_plot", "anomaly_search", "no_routine", "generate", "likelihood",
    "calculation", "research", "unsupported",
)
DETECTOR_MODES = (
    "particle-level", "rivet-smearing", "simpleanalysis-delphes-native", "container",
    "effmap-folded",  # published per-object efficiency maps folded over truth objects (D2)
    # Delphes fast-sim driving a CUSTOM selection with no certified routine (Option-C detector
    # variant): labeled proxy, never an exclusion of record
    # until per-SR acc*eff certification vs published anchors closes
    "delphes-custom-uncertified",
    "TBD-judgment",   # a weak model may leave the choice to the physicist/CHECK-IN 1
    "parton-level", "none",
)
STAT_MODES = (  # canonical source: result_pack.py STAT_MODES + the routing placeholder
    "published-likelihood", "simplified-likelihood", "constructed-likelihood", "best-sr-counting", "combined-counting",
    "stability-only", "shape-fit", "blocked-shape-fit", "sensitivity-expected-only", "none-survey",
    "prescribed-statistic",
    "TBD-judgment", "none-generation", "provided-likelihood",
)
COMPUTE_PLANS = ("none", "dry", "smoke", "full", "scan")

# Version-1 compatibility is deliberately explicit. Historical contracts omit targets,
# and compact cost estimates omit disk/events/backend metadata. One recorded run also has
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
    "models": _TEXTS,
    "process": {"anyOf": [_TEXT, {"type": "null"}]},
    **{key: _TEXTS for key in ("analysis", "arxiv", "inspire", "hepdata", "figures")},
    "masses_gev": _array(_NONNEG),  # zero is physical; no invented mass/model upper bound
    "sqrt_s_gev": {"anyOf": [_POSITIVE, {"type": "null"}]},
    "lumi_fb": {"anyOf": [_POSITIVE, {"type": "null"}]},
    "mass_floor_note": _TEXT,
})
_COST = _object({
    "mode": _enum(COMPUTE_PLANS),
    **{key: _COUNT for key in ("points", "events_per_point", "parallel", "solver_evaluations")},
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

# Historical numeric records remain byte-meaning compatible. Fresh unknown
# generation cost is explicit and cannot be confused with a zero estimate.
_LEGACY_COST = _COST
_COST = {'oneOf': [_LEGACY_COST, _object({
    'schema_version': {'type': 'integer', 'const': 2},
    'mode': _enum(('smoke','full','scan')),
    'points': _COUNT, 'events_per_point': {'anyOf': [_COUNT, {'type': 'null'}]},
    'backend': _enum(('native','container')), 'parallel': _COUNT,
    'calibration_status': {'const': 'uncalibrated'},
    'walltime_h': {'type': 'null'}, 'disk_gb_peak': {'type': 'null'},
    'next_api': {'const': 'ravel.workflow.generation_efficiency.prepare_pilot'},
    'production_feasibility_established': {'const': False}, 'note': _TEXT,
    'generated_by': {'const': 'cost_preflight.py'}, 'generated_utc': {'type': 'string'},
}, ('schema_version','mode','points','events_per_point','backend','parallel',
    'calibration_status','walltime_h','disk_gb_peak','next_api',
    'production_feasibility_established','note')),
    # Measured cost: wall time scaled from completed pilots on this machine, with
    # the forecast file pinned by hash (workflow/pilot_cost.py).
    _object({
    'schema_version': {'type': 'integer', 'const': 3},
    'mode': _enum(('smoke','full','scan')),
    'points': _COUNT, 'events_per_point': {'anyOf': [_COUNT, {'type': 'null'}]},
    'backend': {'const': 'native'}, 'parallel': {'const': 1},
    'calibration_status': {'const': 'measured'},
    'walltime_h': _INTERVAL, 'disk_gb_peak': {'anyOf': [_NONNEG, {'type': 'null'}]},
    'basis': _object({
        'kind': _enum(('supervised_pilot_forecast', 'generation_empirical_forecast')),
        'forecast': _object({'path': _TEXT, 'sha256': {'type': 'string', 'pattern': r'^[0-9a-f]{64}$'},
                             'size': {'type': 'integer', 'minimum': 1}}, ('path', 'sha256', 'size')),
        'unit': _TEXT, 'pilots': _COUNT, 'machine': {'type': 'object'},
        'margin': {'type': 'number', 'minimum': 1, 'maximum': 100}},
        ('kind', 'forecast', 'unit', 'pilots', 'machine', 'margin')),
    'production_feasibility_established': {'const': False}, 'note': _TEXT,
    'generated_by': {'const': 'cost_preflight.py'}, 'generated_utc': {'type': 'string'},
}, ('schema_version','mode','points','events_per_point','backend','parallel','calibration_status',
    'walltime_h','disk_gb_peak','basis','production_feasibility_established','note','generated_by'))]}

# Resource fields extend each cost shape without changing historical approval
# representations. Missing observations are null, never an inferred zero.
from ravel.workflow.cost_records import DIMENSIONS, CONTRACT_DIMENSIONS, STATUSES
_NULL_NUMBER = {'anyOf': [_NONNEG, {'type': 'null'}]}
_COST_RESOURCE_FIELDS = {
    'cost_class': _TEXT, 'status': _enum(STATUSES),
    'resource_vector': _object({key: _NULL_NUMBER for key in DIMENSIONS}, DIMENSIONS),
    'profile': _object({key: {'anyOf': [_TEXT, {'type': 'object'}, {'type': 'null'}]}
                        for key in ('process', 'configuration', 'machine')}, ('process', 'configuration', 'machine')),
    'uncertainty': {'anyOf': [_object({key: _INTERVAL for key in DIMENSIONS}), {'type': 'null'}]},
    **{key: _NULL_NUMBER for key in CONTRACT_DIMENSIONS},
    'forecast_basis': _TEXT,
}
for _cost_shape in _COST['oneOf']:
    _cost_shape['properties'].update(_COST_RESOURCE_FIELDS)
# Unknown non-generation usage does not acquire the old zero-wall/disk anchor.
_LEGACY_COST['properties'].update({
    'walltime_h': {'anyOf': [_INTERVAL, {'type': 'null'}]},
    'disk_gb_peak': _NULL_NUMBER,
    'basis': _TEXT,
})
_COST['oneOf'][1]['properties']['basis'] = _TEXT

# Optional producer provenance is orthogonal to the calibrated-cost schema.
for _cost_shape in _COST['oneOf']:
    _cost_shape['properties'].update({key: {'type': 'string', 'pattern': r'^[0-9a-f]{64}$'}
                                     for key in ('input_fingerprint', 'payload_sha256')})

# JSON-schema callers receive the same closed shape as the machine validator.
# Exact prompt spans, IDs/assignment references and the mandatory literal whole
# request are relational invariants additionally checked by validate_requirements.
_TASK_PIN = _object({"path": _TEXT, "sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
                     "size": {"type": "integer", "minimum": 1, "maximum": 64_000_000}},
                    ("path", "sha256", "size"))
_TASK_ID = {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$"}
_TASK_CRITERIA = {"type": "object", "minProperties": 1,
                  "$comment": "Caller-declared interpretation; finite JSON and bounded size additionally checked."}
_TASK_SPAN = _object({"start": {"type": "integer", "minimum": 0},
                      "end": {"type": "integer", "minimum": 1}, "text": _TEXT}, ("start", "end", "text"))
_TASK_OBLIGATION = _object({"id": _TASK_ID, "kind": _enum(("experiment", "model", "domain", "quantity",
    "deliverable", "quality", "coverage", "method", "whole_request")), "statement": _TEXT,
    "criteria": _TASK_CRITERIA, "evidence": {"type": "array", "items": _TASK_SPAN, "minItems": 1, "maxItems": 16}},
    ("id", "kind", "statement", "criteria", "evidence"))
_TASK_COVERAGE = _object({"obligation_id": _TASK_ID, "criteria": _TASK_CRITERIA}, ("obligation_id", "criteria"))
_TASK_ASSIGNMENT = _object({"id": _TASK_ID, "purpose": _TEXT,
    "coverage": {"type": "array", "items": _TASK_COVERAGE, "minItems": 1, "maxItems": 64}}, ("id", "purpose", "coverage"))
_TASK_REQUIREMENTS = _object({"schema_version": {"type": "integer", "const": 1},
    "completion_epoch": {"type": "integer", "const": 1},
    "prompt_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
    "obligations": {"type": "array", "items": _TASK_OBLIGATION, "minItems": 1, "maxItems": 64},
    "assignments": {"type": "array", "items": _TASK_ASSIGNMENT, "maxItems": 128},
    "amendments": {"type": "array", "items": _TASK_PIN, "maxItems": 16},
    "parent_acceptance_scope": {"type": "string", "const": "original_task_completion"}},
    ("schema_version", "prompt_sha256", "obligations", "assignments", "amendments", "parent_acceptance_scope"))

# Concrete operations a host may name directly as the interpretation kind. The
# stored intake keeps the planning parent kind and records the operation.
OPERATION_KINDS = ("manuscript", "diagram", "measurement_fit", "supplied_events",
                   "published-classifier", "ml-training")
INTERPRETATION_SCHEMA = _object({
    "schema_version": {"type": "integer", "const": 1},
    "prompt_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "kind": _enum((*TASK_MODES[:-1], "method_study", *OPERATION_KINDS)),
    "operation": _enum(OPERATION_KINDS),
    "objective": _TEXT,
    "requested_outputs": {"type": "array", "items": _TEXT, "minItems": 1},
    "evidence": {"type": "array", "minItems": 1, "items": _object({
        "start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1},
        "text": _TEXT}, ("start", "end", "text"))},
    "unresolved": _TEXTS,
    # Optional host corrections of the lexical targets; identifiers must appear in the request.
    "targets": _TARGETS,
}, ("schema_version", "prompt_sha256", "kind", "objective", "requested_outputs", "evidence", "unresolved"))
INTAKE_SCHEMA = {**INTERPRETATION_SCHEMA, "properties": {
    **INTERPRETATION_SCHEMA["properties"], "kind": _enum((*TASK_MODES[:-1], "method_study")),
    "source": _enum(("host-agent", "local-parser")),
    "review_status": {"type": "string", "const": "draft"}},
    "required": [*INTERPRETATION_SCHEMA["required"], "source", "review_status"]}

from ravel.workflow.point_overrides import DECLARATION_SCHEMAS

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Ravel task contract, version 1",
    "$comment": COMPATIBILITY_POLICY + " The stdlib validator additionally rejects "
                "non-finite Python floats, requires exact integer types (1.0 is rejected), "
                "checks interval ordering and cross-field compute consistency. The JSON "
                "reader rejects duplicate keys and non-standard numeric literals.",
    **_object({
        "schema_version": {"type": "integer", "const": 1},
        "agent_layer_epoch": {"type": "integer", "enum": [1, 2]},
        "prompt": _TEXT,
        "task_mode": _enum(TASK_MODES),
        "detector_mode": _enum(DETECTOR_MODES),
        "stat_mode": _enum(STAT_MODES),
        "required_user_inputs": _TEXTS,
        "assumptions": _TEXTS,
        "compute_plan": _enum(COMPUTE_PLANS),
        "approval_required": {"type": "boolean", "const": True},
        "autonomy": _object({"path": _TEXT, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}, ("path", "sha256")),
        # Optional run-relative pins of the request reading and the request plan (intake
        # architecture §2.5.5). They only add approval inputs; validate_pins reads them.
        **{key: _object({"path": _TEXT, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
                        ("path", "sha256")) for key in ("reading", "request_plan")},
        "targets": _TARGETS,
        "forbidden_sources": _array(_object({}, additional=True)),
        "intake": INTAKE_SCHEMA,
        "task_requirements": _TASK_REQUIREMENTS,
        **DECLARATION_SCHEMAS,
        "execution_plan": _object({"path": _TEXT,
            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}, ("path", "sha256")),
        "certification_plans": _object({kind: _object({
            "path": _TEXT,
            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        }, ("path", "sha256")) for kind in ("r5", "acceptance")}),
        "operation_resources": _object({"schema_version": {"type": "integer", "const": 1},
            "kind": {"type": "string", "const": "solver"},
            "generated_events": {"type": "integer", "const": 0},
            "solver_evaluations": _COUNT, "max_seconds": _POSITIVE},
            ("schema_version", "kind", "generated_events", "solver_evaluations", "max_seconds")),
        "cost_estimate": _COST,
        # Optional delivery deadline; study_deadline checks the cross-field rules.
        "deadline": _object({"utc": _TEXT, "budget_s": _POSITIVE, "start_utc": _TEXT, "margin_s": _NONNEG},
                            ("margin_s",)),
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
    if "oneOf" in schema:
        choices = [_schema_errors(value, option, path) for option in schema["oneOf"]]
        matches = sum(not option for option in choices)
        if matches == 0:
            errs.append(f"{path} does not match an allowed format: " +
                        " OR ".join("; ".join(option) for option in choices))
        elif matches > 1:
            errs.append(f"{path} matches more than one exclusive format")
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
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path} must be <= {schema['maximum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errs.append(f"{path} must be < {schema['exclusiveMaximum']}")
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
    if "task_requirements" in c:
        from ravel.workflow.task_completion import validate_requirements
        try: validate_requirements(c)
        except (ValueError, TypeError, KeyError): errs.append("invalid original task obligations/assignment mapping")
    tm, sm, cp = c["task_mode"], c["stat_mode"], c["compute_plan"]
    if 'forbidden_sources' in c:
        from ravel.workflow.source_policy import digest
        try:
            digest(c['forbidden_sources'])
        except (ValueError, TypeError) as exc:
            errs.append(f'forbidden_sources: {exc}')
    from ravel.workflow import request_reading, intake
    # An archive audit judges the contract by the rules it was written under.
    for boundary in ([] if legacy else request_reading.boundaries(c['prompt'], intake.actionable_text(c['prompt']))):
        if boundary['kind'] == 'full-simulation' and cp != 'none':
            errs.append(boundary['statement'])
    if "deadline" in c:
        from ravel.workflow.study_deadline import contract_errors
        errs.extend(contract_errors(c["deadline"]))
    if "operation_resources" in c:
        resources = c["operation_resources"]
        if cp != "full" or "execution_plan" not in c:
            errs.append("solver resources require a full task-bound execution plan")
        cost = c.get("cost_estimate", {})
        if "events_per_point" in cost or cost.get("solver_evaluations") != resources["solver_evaluations"]:
            errs.append("solver cost must declare matching evaluations and omit generated-event bookkeeping")
        if "walltime_h" not in cost or cost["walltime_h"][1]*3600 > resources["max_seconds"] + 1e-9:
            errs.append("solver cost walltime exceeds its declared maximum")
    elif "solver_evaluations" in c.get("cost_estimate", {}):
        errs.append("solver cost requires an explicit solver operation resource contract")
    if tm in ("calculation", "research"):
        if cp != "none" or c["detector_mode"] != "none" or sm != "TBD-judgment":
            errs.append(f"{tm} is a zero-compute parent intake; prepare explicit ordinary child specifications")
        if "task_requirements" not in c:
            errs.append(f"{tm} requires the complete original task obligation census")
    if tm in ("generate", "likelihood"):
        detectors, statistic = ((("parton-level", "particle-level"), "none-generation") if tm == "generate"
                                else (("none",), "provided-likelihood"))
        if c["detector_mode"] not in detectors or sm != statistic:
            errs.append(f"{tm} requires detector_mode in {detectors} and stat_mode={statistic}")
        if cp not in ("none", "full"):
            errs.append(f"{tm} uses none for intake or full for its bounded scoped plan")
        if cp == "full" and "execution_plan" not in c:
            errs.append(f"{tm} compute requires a bound execution_plan")
    if "execution_plan" in c:
        path = c["execution_plan"]["path"]
        if path.startswith("/") or "\\" in path or any(p in ("", ".", "..") for p in path.split("/")):
            errs.append("execution_plan.path must be a portable run-relative path")
    if "intake" in c:
        from ravel.workflow.intake import validate_interpretation
        intent = c["intake"]
        errs.extend(validate_interpretation({k: v for k, v in intent.items()
                                             if k not in ("source", "review_status")}, c["prompt"]))
        expected = "survey" if intent["kind"] == "method_study" else intent["kind"]
        if expected != tm:
            errs.append("intake kind disagrees with task_mode")
        if intent["kind"] == "method_study" and (cp != "none" or sm != "none-survey"):
            errs.append("method study intake is a zero-compute proposal")
    for key in PIN_KEYS:
        if key in c and not _portable(c[key]["path"]):
            errs.append(f"{key}.path must be a portable run-relative path")
    if ("reading" in c or "request_plan" in c) and c.get("agent_layer_epoch") != 2:
        # Only the release intake pins a reading or request plan; it stamps epoch two.
        errs.append("a release-created contract (pinned reading or request_plan) requires agent_layer_epoch 2")
    if "request_plan" in c:
        if "reading" not in c:
            errs.append("request_plan requires a pinned reading")
        elif c["reading"]["path"] == c["request_plan"]["path"]:
            errs.append("reading and request_plan must pin distinct files")
    if c.get("certification_plans"):
        if not (c.get("targets") or {}).get("analysis"):
            errs.append("certification_plans require targets.analysis identities")
        for kind, pin in c["certification_plans"].items():
            path = pin["path"]
            if path.startswith("/") or "\\" in path or any(p in ("", ".", "..") for p in path.split("/")):
                errs.append(f"certification_plans.{kind}.path must be a portable run-relative path")
    if tm == "unsupported":
        if not c.get("blocking"):
            errs.append("task_mode=unsupported requires 'blocking' to NAME the refusal line "
                        "(docs/reference/scope.md section 6)")
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
        if set(cost) & (set(_COST_RESOURCE_FIELDS) - {'forecast_basis'}):
            from ravel.workflow.cost_records import make_record
            required = {'cost_class', 'status', 'profile', 'uncertainty', 'resource_vector', *CONTRACT_DIMENSIONS}
            if not required <= set(cost):
                errs.append('cost_estimate resource record is incomplete')
            else:
                try:
                    checked = make_record(cost['cost_class'], cost['status'], cost['profile'],
                        cost.get('forecast_basis', cost.get('basis', 'Cost record.')),
                        uncertainty=cost['uncertainty'], **cost['resource_vector'])
                    if any(cost[k] != checked[k] for k in CONTRACT_DIMENSIONS):
                        errs.append('cost_estimate scalar projections differ from resource vector')
                except ValueError as exc:
                    errs.append('cost_estimate: ' + str(exc))
            # Version 1 holds historical references and unknown usage; neither is a calibration.
            expected = {1: ('historical', 'unknown'), 2: ('uncalibrated',), 3: ('calibrated',)}[
                cost.get('schema_version', 1)] if cost.get('schema_version', 1) in (1, 2, 3) else None
            if expected is not None and cost.get('status') not in expected:
                errs.append('cost_estimate status conflicts with legacy calibration status')
        if cost.get('schema_version', 1) == 1 and cost.get('walltime_h', []) is None and (
                cost.get('status') != 'unknown' or cost['mode'] not in ('none', 'dry')):
            errs.append('cost_estimate null walltime requires explicitly unknown non-generation usage')
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
                     if key in cost and cost[key] is not None}
        if "waypoint_smoke" in cost:
            intervals["cost_estimate.waypoint_smoke.walltime_h"] = cost["waypoint_smoke"]["walltime_h"]
        for path, (lo, hi) in intervals.items():
            if lo > hi:
                errs.append(f"{path} must be ordered [lower, upper]")
            if cp in ("full", "scan") and ".walltime_h" in path and hi == 0:
                errs.append(f"{path} must have a positive upper estimate for compute_plan={cp}")
    return errs


PIN_KEYS = ("reading", "request_plan")
_PIN_MAX_BYTES = 4_000_000


def _portable(path):
    return not (path.startswith("/") or "\\" in path or any(p in ("", ".", "..") for p in path.split("/")))


def pinned_paths(rundir, contract):
    """Absolute paths of the records a contract pins, in PIN_KEYS order (empty without pins)."""
    if not isinstance(contract, dict):
        return []
    import os
    return [os.path.join(rundir, contract[key]["path"]) for key in PIN_KEYS
            if isinstance(contract.get(key), dict) and isinstance(contract[key].get("path"), str)]


def read_pinned(rundir, pin, label):
    """Bytes of one pinned record, read once and checked against its pin. Raises ValueError."""
    import hashlib
    import os
    path = pin.get("path") if isinstance(pin, dict) else None
    if not isinstance(path, str) or not _portable(path):
        raise ValueError(f"{label} pin must name a portable run-relative path")
    full = os.path.join(rundir, path)
    parts = path.split("/")
    for depth in range(1, len(parts) + 1):
        if os.path.islink(os.path.join(rundir, *parts[:depth])):
            raise ValueError(f"{label} {path} is not a regular file inside the run (symlink)")
    if not os.path.isfile(full):
        raise ValueError(f"{label} {path} is not a regular file inside the run")
    size = os.path.getsize(full)
    if not 0 < size <= _PIN_MAX_BYTES:
        raise ValueError(f"{label} {path} must be nonempty and at most {_PIN_MAX_BYTES} bytes")
    with open(full, "rb") as fh:
        raw = fh.read(_PIN_MAX_BYTES + 1)
    if hashlib.sha256(raw).hexdigest() != pin.get("sha256"):
        raise ValueError(f"{label} {path} sha256 differs from its contract pin")
    return raw


def load_pinned(rundir, contract, key):
    """The parsed record a contract pins under key (None when unpinned). Raises ValueError."""
    if not isinstance(contract, dict) or key not in contract:
        return None
    raw = read_pinned(rundir, contract[key], key)
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError(f"{key} {contract[key]['path']} is not strict JSON: {exc}") from None


def validate_pins(rundir, contract):
    """Errors for the records a contract pins: presence, hash, schema and request binding.

    validate() stays pure; this reads the run directory. A contract without pins
    returns no errors and reads nothing.
    """
    if not isinstance(contract, dict) or not any(key in contract for key in PIN_KEYS):
        return []
    from ravel.validation import intake_records
    prompt = contract.get("prompt") if isinstance(contract.get("prompt"), str) else ""
    errors, records = [], {}
    for key in PIN_KEYS:
        try:
            records[key] = load_pinned(rundir, contract, key)
        except ValueError as exc:
            errors.append(str(exc))
    if records.get("reading") is not None:
        errors += intake_records.reading_errors(records["reading"], prompt)
        from ravel.workflow import source_policy
        try:
            rows = source_policy.from_reading(records['reading'])
            if (rows or 'forbidden_sources' in contract) and contract.get('forbidden_sources') != rows:
                errors.append('forbidden_sources must equal source_policy.from_reading of the pinned reading')
        except (ValueError, TypeError, KeyError) as exc:
            errors.append(f'forbidden_sources: {exc}')
    if records.get("request_plan") is not None:
        errors += intake_records.plan_errors(records["request_plan"], prompt, contract.get("reading"))
    return errors


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
    # the custom-uncertified-Delphes route is a first-class contract value
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
