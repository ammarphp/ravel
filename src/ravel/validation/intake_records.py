"""Schemas for the request reading, the request plan and delegated adapter defaults.

These are the end-state record shapes of the intake architecture (reading §2.5.1, plan
§2.5.2). Stage 1 pins them beside a schema-v1 task contract; Stage 2 makes them
authoritative without rewriting them. Every schema uses only the keywords that
``validate_task_contract._schema_errors`` evaluates.

The checks here are structural plus the relations this module can verify on its own:
prompt hashes and exact prompt spans. The reader's componently and conservation rules and
the plan check belong to their own modules.

Stdlib only, so hooks and the contract validator can import it before a scientific
environment exists.
"""
import hashlib
import json

from ravel.validation.validate_task_contract import (
    TASK_MODES, _TEXT, _array, _enum, _object, _schema_errors)

SCHEMA_VERSION = 1
READING_KIND = "request-reading"
ADDITIONS_KIND = "request-reading-additions"
PLAN_KIND = "request-plan"

# --------------------------------------------------------------------------- #
#  closed vocabularies (architecture §2.4)
#
#  This module is the one statement of the reading and plan vocabularies and schemas.
#  The reader (ravel.workflow.request_reading), the plan draft and plan check
#  (ravel.workflow.request_plan, ravel.validation.validate_request_plan), the contract
#  pins and the test battery import them from here; none keeps a copy.
# --------------------------------------------------------------------------- #

ARTIFACT_KINDS = ("model", "parameter_point", "event_sample", "selection", "binned_values", "cutflow",
                  "table", "scalar", "expression", "statistical_model", "inference", "figure", "document")
# A family intermediate keeps its own name under a namespace and matches only by exact name.
NAMESPACED_KIND = r"^[a-z][a-z0-9_-]*:[a-z0-9_-]+(?:/[a-z0-9_-]+)*$"
EFFECTS = ("generates_events", "simulates_detector", "executes_native", "varies_parameters",
           "acquires_published", "patches_published_model", "reads_restricted_inputs",
           "runs_authored_code", "writes_external")
NODE_KINDS = ("operation", "authored", "input", "envelope")
IMPLEMENTATIONS = ("science-mode", "scoped-adapter", "lifecycle-stage", "command",
                   "authored-analysis", "routine-build", "model-authoring", "formula", "converter",
                   "source-development", "requester-input", "owner-action", "research-coordinator")
AUTHORED_IMPLEMENTATIONS = ("authored-analysis", "routine-build", "model-authoring", "formula", "converter",
                            "source-development")
CLAIM_KINDS = ("exclusion", "estimate", "significance", "prediction", "agreement", "calculation",
               "finding", "method_performance", "document")
LEVELS = ("observed", "expected", "not_applicable")
BASES = ("generated_prediction", "simulated_acceptance", "published_statistical_model",
         "reimplemented_statistical_model", "constructed_statistical_model", "published_results",
         "supplied_inputs", "observed_data", "analytic", "numerical_solver", "trained_model",
         "authored_code", "unclassified")
# The boundary classes are the only states that stop work. `control_bypass_request` is one
# sentence asking to skip approval or review, self-approve, unblind, use a forbidden source
# or fabricate values: that sentence is refused and the rest of the request proceeds.
BOUNDARY_CLASSES = ("inaccessible_input", "unsupportable_claim", "contradiction", "control_bypass_request",
                    "no_scientific_object", "ungrounded_identifier")
WHOLE_REQUEST_BOUNDARIES = ("no_scientific_object", "ungrounded_identifier")
FIELD_AUTHORITY = ("user_quoted", "supplied", "source_document", "upstream", "adapter_default",
                   "agent_inference", "review_change")
FACT_AUTHORITY = ("user_quoted", "supplied", "source_document", "inferred", "resolved")
CONSTRAINT_TYPES = ("requested_stage", "negated_stage", "requested_tool", "tool_allowlist",
                    "prescribed_statistic", "source_restriction", "blinding", "template", "keep_fixed",
                    "budget", "delegation", "identity_context")
DISMISSALS = ("not_a_physics_value", "context_only", "negated", "quoted_not_requested", "duplicate",
              "superseded_by_answer")
AMBIGUITY_STATUS = ("open", "resolved", "withdrawn")
RESOLVERS = ("user", "delegation", "agent")
EDGE_RESOLUTIONS = ("compatible", "convertible", "unresolved")
EDGE_ACCEPTANCE = ("accepted_review", "execution_ledger")
WAYPOINT_KINDS = ("smoke_review", "closure", "known_answer", "condition", "none")
WAYPOINT_ON_FALSE = ("stop", "skip_subgraph")
AUTHOR_ACTORS = ("deterministic-reader", "host-agent", "local-proposer", "checkin1-answer")
NODE_STATUSES = ("available", "branch", "held", "doctor-blocked")
RUNGS = ("none", "dry", "smoke", "full", "scan")
BUDGET_BASES = ("historical", "ceiling", "measured", "uncalibrated")
BUDGET_KEYS = ("wall_seconds", "native_attempts", "events", "disk_bytes", "calls", "output_tokens")
NODE_BUDGET_KEYS = ("max_seconds", "events", "disk_bytes", "native_attempts")
REVIEW_ACTIONS = ("bulk", "delivery", "reuse")
INPUT_SOURCES = ("requester", "published", "installed", "owner_action")
INPUT_STATUSES = ("supplied", "located", "awaited")
STATISTIC_SOURCES = ("prescribed", "policy_default", "declared", "not_applicable")
COMPARISON_TARGETS = ("none", "published_figure", "published_table", "published_value",
                      "published_limit_set", "supplied", "other_claim")
PLAN_STATUSES = ("draft", "proposed")
LABEL_RULES = ("D1", "D2", "D3", "D4", "D5")
SELECTION_ORIGINS = ("published", "reimplemented", "designed", "requester")
EVENT_LEVELS = ("parton", "particle", "detector", "reconstructed")
ANALYTIC_FROM = ("stated_inputs", "cited_formula", "derived")
# Facts that state a parameter range or a list of values; each is an obligation `range-<fact id>`
# that only a fanned-out node, an ambiguity row (the scan question) or a boundary can cover.
RANGE_FACTS = ("parameter_range", "parameter_values")
RANGE_PREFIX = "range-"
VOCABULARIES = {
    "artifact kinds": ARTIFACT_KINDS, "effects": EFFECTS, "node kinds": NODE_KINDS,
    "claim kinds": CLAIM_KINDS, "levels": LEVELS, "bases": BASES, "boundary classes": BOUNDARY_CLASSES,
    "field authority": FIELD_AUTHORITY, "constraint types": CONSTRAINT_TYPES, "dismissals": DISMISSALS,
    "edge resolutions": EDGE_RESOLUTIONS, "waypoint kinds": WAYPOINT_KINDS,
}

# Rule P0-S1' (architecture §4.3). It applies to a claim whose computed basis includes a published
# or reimplemented selection (simulated_acceptance with one of CERTIFICATE_ORIGINS), a published
# workspace or a reimplemented fit. Served outside route A, such a claim carries NOT_CERTIFIED.
CERTIFICATE_BASES = ("simulated_acceptance", "published_statistical_model", "reimplemented_statistical_model")
CERTIFICATE_ORIGINS = ("published", "reimplemented")
NOT_CERTIFIED = "not certified on this route"
# The anchor a physics-critical adapter default cites, as a plan field records it in `evidence`:
# a reading item id (the user's text), `invariant:<registered invariant>` or `practice:<citation>`.
# The delegated-defaults record states the same anchor as an object (ANCHOR below).
ANCHOR_REFERENCE = r"^(?:[FKWDAB][1-9][0-9]*|(?:invariant|practice):\S.*)$"


def certificate_relevant(rows):
    """True when basis rows ({element, origin?}) trigger rule P0-S1'.

    A simulated_acceptance row without a stated origin (a declared basis) is treated as
    relevant: the stricter reading wins until the plan's lineage resolves the origin.
    """
    for row in rows:
        element = row.get("element") if isinstance(row, dict) else row
        if element in ("published_statistical_model", "reimplemented_statistical_model"):
            return True
        if element == "simulated_acceptance":
            origin = row.get("origin") if isinstance(row, dict) else None
            if origin is None or origin in CERTIFICATE_ORIGINS:
                return True
    return False


# --------------------------------------------------------------------------- #
#  shared fragments
# --------------------------------------------------------------------------- #

_NULL = {"type": "null"}
_SHA = {"type": "string", "pattern": r"^[0-9a-f]{64}$"}
_OBJ = {"type": "object"}
_TEXTS = _array(_TEXT)
_NONNEG = {"type": "number", "minimum": 0}
_OPT_TEXT = {"anyOf": [_NULL, _TEXT]}
_OPT_NONNEG = {"anyOf": [_NULL, _NONNEG]}
_BOOL = {"type": "boolean"}


def _bounded(items, low=0, high=None):
    schema = {"type": "array", "items": items, "minItems": low}
    if high is not None:
        schema["maxItems"] = high
    return schema


def _id(prefix):
    return {"type": "string", "pattern": rf"^{prefix}[1-9][0-9]*$"}


def _closed(properties):
    """An object whose every listed key is required and nothing else is allowed."""
    return _object(properties, tuple(properties))


# SPAN text is the exact request bytes, so it is any non-empty string (a span may be blank-led).
SPAN = _closed({"start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1},
                "text": {"type": "string", "minLength": 1}})
# PIN paths are run-relative: no leading slash and no parent segment.
PIN = _closed({"path": {"type": "string", "minLength": 1, "pattern": r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))\S.*$"},
               "sha256": _SHA})
_OPT_PIN = {"anyOf": [_NULL, PIN]}
AUTHOR = _closed({"actor": _enum(AUTHOR_ACTORS), "host": _OPT_TEXT, "model": _OPT_TEXT,
                  "invocation_id": _OPT_TEXT, "fresh_context": {"anyOf": [_NULL, _BOOL]},
                  "record": _OPT_PIN})
ARTIFACT_KIND = {"anyOf": [_enum(ARTIFACT_KINDS), {"type": "string", "pattern": NAMESPACED_KIND}]}
_ARTIFACT = _closed({"kind": _enum(ARTIFACT_KINDS), "require": _OBJ})

# --------------------------------------------------------------------------- #
#  reading (§2.5.1)
# --------------------------------------------------------------------------- #

FACT = _closed({"id": _id("F"), "type": _TEXT, "value": _OBJ, "evidence": _bounded(SPAN, 0, 16),
                "authority": _enum(FACT_AUTHORITY), "witness": _OPT_TEXT, "physics_critical": _BOOL})
CONSTRAINT = _closed({"id": _id("K"), "type": _enum(CONSTRAINT_TYPES), "value": _OBJ,
                      "evidence": _bounded(SPAN, 1, 16)})
DELIVERABLE = _closed({"id": _id("D"), "obligation_ids": _TEXTS, "artifact": _ARTIFACT,
                       "claim_kind": {"anyOf": [_NULL, _enum(CLAIM_KINDS)]}})
READING_ROW = _closed({"id": _TEXT, "value": _OBJ, "authority": _enum(FIELD_AUTHORITY), "source": _OPT_PIN})
AMBIGUITY = _closed({
    "id": _id("A"), "evidence": _bounded(SPAN, 0, 16), "issue": _TEXT,
    "readings": _bounded(READING_ROW, 2, 16),
    "default": _OPT_TEXT, "observable_impact": _BOOL, "reversible": _BOOL,
    "physics_critical": _BOOL, "blocks": _TEXTS, "status": _enum(AMBIGUITY_STATUS),
    "resolution": {"anyOf": [_NULL, _closed({"reading": _TEXT, "by": _enum(RESOLVERS),
                                             "evidence": {"anyOf": [SPAN, PIN]}, "utc": _TEXT})]},
})
BOUNDARY = _closed({"id": _id("B"), "class": _enum(BOUNDARY_CLASSES), "obligation_ids": _TEXTS,
                    "statement": _TEXT, "would_make_possible": _TEXT,
                    "evidence": _bounded({"anyOf": [SPAN, PIN]}, 1, 16)})
WITNESS = _closed({"id": _id("W"), "type": _TEXT, "value": _OBJ, "span": SPAN})
DISMISSED = _closed({"witness": _TEXT, "reason": _enum(DISMISSALS), "note": _TEXT})
READING_SCHEMA = _closed({
    "schema_version": {"type": "integer", "const": 1},
    "kind": {"type": "string", "const": "request-reading"},
    "prompt_sha256": _SHA,
    "reader": _closed({"module": _TEXT, "source_sha256": _SHA}),
    "authors": _bounded(AUTHOR, 1, 8),
    "witness": _bounded(WITNESS, 0, 512),
    "facts": _bounded(FACT, 0, 256),
    "constraints": _bounded(CONSTRAINT, 0, 64),
    "deliverables": _bounded(DELIVERABLE, 0, 64),
    "ambiguities": _bounded(AMBIGUITY, 0, 64),
    "boundaries": _bounded(BOUNDARY, 0, 16),
    "dismissed": _array(DISMISSED),
})
# Host additions to a reading floor: new facts, constraints, deliverables and ambiguity rows
# under one author envelope (the programly merge of §2.5.1).
ADDITIONS_SCHEMA = _closed({
    "schema_version": {"type": "integer", "const": 1},
    "kind": {"type": "string", "const": "request-reading-additions"},
    "prompt_sha256": _SHA, "author": AUTHOR,
    "facts": _bounded(FACT, 0, 256), "constraints": _bounded(CONSTRAINT, 0, 64),
    "deliverables": _bounded(DELIVERABLE, 0, 64), "ambiguities": _bounded(AMBIGUITY, 0, 64)})

# --------------------------------------------------------------------------- #
#  plan and claims (§2.5.2)
# --------------------------------------------------------------------------- #

INPUT = _closed({"id": _id("I"), "provides": _closed({"kind": ARTIFACT_KIND, "require": _OBJ}),
                 "source": _enum(INPUT_SOURCES), "locator": _TEXT,
                 "evidence": _array(SPAN), "pin": _OPT_PIN, "status": _enum(INPUT_STATUSES)})
NODE_BUDGET = _closed({"basis": _enum(BUDGET_BASES), **{key: _OPT_NONNEG for key in NODE_BUDGET_KEYS}})
NODE = _closed({
    "id": _id("N"), "kind": _enum(NODE_KINDS), "operation": _OPT_TEXT,
    "implementation": _enum(IMPLEMENTATIONS),
    "status": _enum(NODE_STATUSES), "held_by": _OPT_TEXT,
    "covers": _bounded(_TEXT, 1, 64),
    "fields": _array(_closed({"pointer": {"type": "string", "pattern": "^/"}, "value": {},
                              "authority": _enum(FIELD_AUTHORITY), "evidence": _OPT_TEXT})),
    "rung": _enum(RUNGS),
    "budget": NODE_BUDGET,
    "placement": _closed({"backend_plan": _OPT_PIN}),
    "fan_out": {"anyOf": [_NULL, _closed({
        "axes": _bounded(_closed({"name": _TEXT, "unit": {"anyOf": [_NULL, {"type": "string"}]},
                                  "values": {"type": "array"}, "fact": _OPT_TEXT}), 1),
        "subgraph": _bounded(_TEXT, 1), "aggregate": _TEXT})]},
    "spec_template": _OPT_PIN,
    "review": _closed({"claim_scope": _TEXT, "actions": _array(_enum(REVIEW_ACTIONS))}),
    "authored": {"anyOf": [_NULL, _closed({"purpose": _TEXT, "signature": _OBJ, "specification": _OPT_PIN,
                                           "known_answer_tests": _bounded(_TEXT, 1, 16),
                                           "attempt_budget": {"type": "integer", "minimum": 0}})]},
    "request": _OPT_TEXT,
})
_END = _closed({"ref": _TEXT, "slot": _TEXT})
EDGE = _closed({"id": _id("E"), "from": _END, "to": _END, "kind": ARTIFACT_KIND, "require": _OBJ,
                "resolution": _enum(EDGE_RESOLUTIONS), "converter": _OPT_TEXT,
                "acceptance": _enum(EDGE_ACCEPTANCE)})
CLAIM = _closed({
    "id": _id("C"), "kind": _enum(CLAIM_KINDS), "statement": _TEXT,
    "obligation_ids": _bounded(_TEXT, 1, 32),
    "deliverable": _closed({"artifact": _enum(ARTIFACT_KINDS), "template": _OPT_PIN}),
    "level": _enum(LEVELS),
    "statistic": _closed({"source": _enum(STATISTIC_SOURCES),
                          "definition": _OPT_TEXT, "evidence": _array(SPAN),
                          "secondary": _array(_closed({"definition": _TEXT,
                                                       "label": {"type": "string", "const": "alongside"}}))}),
    "comparison": _closed({"target": _enum(COMPARISON_TARGETS), "locator": _OPT_TEXT, "metric": _OPT_TEXT,
                           "tolerance": {"anyOf": [_NULL, _OBJ]}}),
    "conventions": _closed({"basis_conversion": _BOOL}),
    "basis_declared": _array(_enum(BASES)),
    "inherits": _TEXTS,
})
WAYPOINT = _closed({"id": _id("WP"), "kind": _enum(WAYPOINT_KINDS), "after": _OPT_TEXT, "before": _TEXTS,
                    "criterion": _TEXT, "check": _OPT_TEXT, "on_false": _enum(WAYPOINT_ON_FALSE)})
MAX_NODES = 128
PLAN_SCHEMA = _closed({
    "schema_version": {"type": "integer", "const": 1},
    "kind": {"type": "string", "const": "request-plan"},
    "prompt_sha256": _SHA,
    "reading": PIN,
    "signatures": _closed({"path": _TEXT, "entries": {"type": "object", "additionalProperties": _SHA}}),
    "status": _enum(PLAN_STATUSES),
    "authors": _bounded(AUTHOR, 1, 8),
    "inputs": _bounded(INPUT, 0, 64),
    "nodes": _bounded(NODE, 1, MAX_NODES),
    "edges": _bounded(EDGE, 0, 512),
    "claims": _bounded(CLAIM, 0, 64),
    "waypoints": _bounded(WAYPOINT, 0, 64),
    "boundaries": _TEXTS,
    "coverage": _array(_closed({"obligation_id": _TEXT, "by": _bounded(_TEXT, 1, 32)})),
    "aggregate_budget": _closed({key: _OPT_NONNEG for key in BUDGET_KEYS}),
    "label": _closed({"task_mode": _enum(TASK_MODES), "rule": _enum(LABEL_RULES), "floor_row": _TEXT}),
})

# --------------------------------------------------------------------------- #
#  delegated adapter defaults (an owner rule; seam for the adapter decision record)
# --------------------------------------------------------------------------- #

DELEGATED_DEFAULTS_PATH = "inputs/delegated_defaults.json"
ANCHOR_KINDS = ("user_span", "registered_invariant", "authoritative_practice")
ANCHOR = {"anyOf": [
    _closed({"kind": {"type": "string", "const": "user_span"}, "span": SPAN}),
    _closed({"kind": {"type": "string", "const": "registered_invariant"}, "invariant": _TEXT}),
    _closed({"kind": {"type": "string", "const": "authoritative_practice"}, "citation": _TEXT,
             "source": _OPT_PIN}),
]}
DELEGATED_DEFAULTS_SCHEMA = _closed({
    "schema_version": {"type": "integer", "const": 1},
    "kind": {"type": "string", "const": "delegated-adapter-defaults"},
    "plan_sha256": _SHA,
    "entries": _bounded(_closed({"id": _id("J"), "node": _id("N"), "pointer": _TEXT, "value": {},
                                 "anchor": ANCHOR, "justification": _TEXT, "author": AUTHOR}), 0, 256),
})

SCHEMAS = {"request-reading": READING_SCHEMA, "request-reading-additions": ADDITIONS_SCHEMA,
           "request-plan": PLAN_SCHEMA, "delegated-adapter-defaults": DELEGATED_DEFAULTS_SCHEMA}


# --------------------------------------------------------------------------- #
#  checks
# --------------------------------------------------------------------------- #

def prompt_sha256(prompt):
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def spans(value):
    """Every SPAN-shaped object inside a record, in document order."""
    if isinstance(value, dict):
        if set(value) == {"start", "end", "text"}:
            yield value
            return
        for item in value.values():
            yield from spans(item)
    elif isinstance(value, list):
        for item in value:
            yield from spans(item)


def span_errors(record, prompt, label):
    errors = []
    for span in spans(record):
        start, end = span.get("start"), span.get("end")
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(prompt)
                or prompt[start:end] != span.get("text")):
            errors.append(f"{label}: span {json.dumps(span)[:120]} is not the exact request text")
    return errors


def _unique_ids(rows, label):
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    duplicates = sorted({i for i in ids if ids.count(i) > 1 and isinstance(i, str)})
    return [f"{label} ids are not distinct: {', '.join(duplicates)}"] if duplicates else []


def reading_errors(reading, prompt):
    errors = _schema_errors(reading, READING_SCHEMA, "reading")
    if errors:
        return errors
    if reading["prompt_sha256"] != prompt_sha256(prompt):
        errors.append("reading.prompt_sha256 does not bind this request")
    for key in ("witness", "facts", "constraints", "deliverables", "ambiguities", "boundaries"):
        errors += _unique_ids(reading[key], f"reading.{key}")
    return errors + span_errors(reading, prompt, "reading")


def plan_errors(plan, prompt, reading_pin=None):
    errors = _schema_errors(plan, PLAN_SCHEMA, "request_plan")
    if errors:
        return errors
    if plan["prompt_sha256"] != prompt_sha256(prompt):
        errors.append("request_plan.prompt_sha256 does not bind this request")
    if reading_pin is not None and plan["reading"] != reading_pin:
        errors.append("request_plan.reading does not pin the contract's reading")
    for key in ("inputs", "nodes", "edges", "claims", "waypoints"):
        errors += _unique_ids(plan[key], f"request_plan.{key}")
    return errors + span_errors(plan, prompt, "request_plan")


def defaults_errors(record, prompt, plan_sha):
    errors = _schema_errors(record, DELEGATED_DEFAULTS_SCHEMA, "delegated_defaults")
    if errors:
        return errors
    if record["plan_sha256"] != plan_sha:
        errors.append("delegated_defaults.plan_sha256 does not bind the pinned request plan")
    errors += _unique_ids(record["entries"], "delegated_defaults.entries")
    return errors + span_errors(record, prompt, "delegated_defaults")


def anchor_reference_errors(anchor, reference, reading):
    """Errors when a recorded justification anchor does not state the anchor a plan field cites.

    A plan field records an adapter default's anchor as a string (ANCHOR_REFERENCE): a reading item
    id, ``invariant:<name>`` or ``practice:<citation>``. The delegated-defaults record states it as an
    object (ANCHOR). The two must name the same anchor: the reading item's evidence holds the user
    span, the invariant names agree, or the practice citations agree.
    """
    import re
    if reference is None:
        return []
    if not isinstance(reference, str) or not re.match(ANCHOR_REFERENCE, reference):
        return [f"the plan field cites {reference!r}, which is not an anchor reference"]
    kind = anchor.get("kind")
    if reference.startswith("invariant:"):
        if kind != "registered_invariant" or anchor.get("invariant") != reference[len("invariant:"):].strip():
            return [f"the justification anchor differs from the plan's {reference!r}"]
        return []
    if reference.startswith("practice:"):
        if kind != "authoritative_practice" or anchor.get("citation", "").strip() != reference[len("practice:"):].strip():
            return [f"the justification anchor differs from the plan's {reference!r}"]
        return []
    items = {row["id"]: row for key in ("facts", "constraints", "deliverables", "ambiguities", "boundaries", "witness")
             for row in (reading or {}).get(key, ())}
    item = items.get(reference)
    if item is None:
        return [f"the plan field cites {reference}, which the reading does not hold"]
    evidence = item.get("evidence") or ([item["span"]] if "span" in item else [])
    if kind != "user_span" or anchor.get("span") not in evidence:
        return [f"the justification anchor is not the user text of {reference}"]
    return []


def load_delegated_defaults(rundir, contract):
    """(record, errors) for the run's delegated adapter-default justifications.

    Only a contract that pins a request plan has this record; it is bound into the
    approval fingerprint beside the plan. An absent file is (None, []).
    """
    import os
    from ravel.validation import validate_task_contract as vtc
    if not isinstance(contract, dict) or not isinstance(contract.get("request_plan"), dict):
        return None, []
    path = os.path.join(rundir, DELEGATED_DEFAULTS_PATH)
    if not os.path.lexists(path):
        return None, []
    if os.path.islink(path) or not os.path.isfile(path):
        return None, [f"{DELEGATED_DEFAULTS_PATH} must be a regular file"]
    with open(path, "rb") as fh:
        raw = fh.read(4_000_001)
    try:
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=vtc._unique_object,
                            parse_constant=vtc._reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        return None, [f"{DELEGATED_DEFAULTS_PATH} is not strict JSON: {exc}"]
    prompt = contract.get("prompt") if isinstance(contract.get("prompt"), str) else ""
    return record, defaults_errors(record, prompt, contract["request_plan"].get("sha256"))
