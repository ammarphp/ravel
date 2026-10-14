"""The request-reading and request-plan records, as the replay, population and neutrality suites see them.

This module binds the suites to the two records that join the intake streams:

- ``READING_SCHEMA``: the request reading (``inputs/reading.json``);
- ``PLAN_SCHEMA``: the request plan with its claims (``inputs/plan.json``).

Both schemas are imported from ``ravel.validation.intake_records``, the one statement of the
vocabularies and schemas, and use only the keywords that ``validate_task_contract._schema_errors``
evaluates. The rules that
a schema cannot state (spans equal the prompt bytes, every witness item is used or dismissed,
references resolve, the graph is acyclic, delegation grants no authority) are checked by
``reading_rule_errors`` and ``plan_rule_errors``, independently of the modules under test.

``Intake`` binds the production modules when they exist and skips otherwise, so the suites
activate as soon as the reader, the planner, the plan check and the derived label land.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import re
from pathlib import Path

import pytest

import synthetic_identifiers as syn

REPO = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------------------------
# Closed vocabularies and schemas: the production statement, imported (one source of truth).
# The suites below check the reader, planner and label against these; the rules a schema
# cannot state are re-derived independently in reading_rule_errors and plan_rule_errors.
# --------------------------------------------------------------------------------------------
from ravel.validation.intake_records import (  # noqa: E402,F401
    ARTIFACT_KIND, ARTIFACT_KINDS, AUTHOR, AUTHOR_ACTORS, BASES, BOUNDARY_CLASSES, BUDGET_BASES, CLAIM, CLAIM_KINDS,
    COMPARISON_TARGETS, CONSTRAINT_TYPES, DISMISSALS, EDGE, EDGE_RESOLUTIONS, EFFECTS, FACT, FACT_AUTHORITY,
    FIELD_AUTHORITY, INPUT, INPUT_SOURCES, INPUT_STATUSES, LABEL_RULES, LEVELS, NODE, NODE_KINDS, NODE_STATUSES,
    PIN, PLAN_SCHEMA, READING_SCHEMA, REVIEW_ACTIONS, RUNGS, SPAN, STATISTIC_SOURCES, VOCABULARIES, WAYPOINT,
    WAYPOINT_KINDS, WHOLE_REQUEST_BOUNDARIES, AMBIGUITY)
from ravel.validation.validate_task_contract import TASK_MODES  # noqa: E402,F401

EVALUATED_KEYWORDS = {"type", "properties", "required", "additionalProperties", "enum", "const", "pattern",
                      "items", "minItems", "maxItems", "anyOf", "minLength", "minimum", "maximum",
                      "exclusiveMinimum", "exclusiveMaximum"}


def schema_keywords(schema, found=None):
    """Every keyword used anywhere in a schema."""
    found = set() if found is None else found
    if isinstance(schema, dict):
        for key, value in schema.items():
            found.add(key)
            if key == "properties":
                for sub in value.values():
                    schema_keywords(sub, found)
            elif key in ("items", "additionalProperties") and isinstance(value, dict):
                schema_keywords(value, found)
            elif key == "anyOf":
                for sub in value:
                    schema_keywords(sub, found)
    return found


def schema_errors(value, schema, path):
    from ravel.validation.validate_task_contract import _schema_errors
    return _schema_errors(value, schema, path)


# --------------------------------------------------------------------------------------------
# Rules a schema cannot state
# --------------------------------------------------------------------------------------------


def prompt_sha256(prompt):
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def spans_in(value):
    """Every SPAN-shaped object nested in a record."""
    if isinstance(value, dict):
        if set(value) == {"start", "end", "text"}:
            yield value
        else:
            for item in value.values():
                yield from spans_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from spans_in(item)


def _duplicates(ids):
    seen, dup = set(), set()
    for i in ids:
        (dup if i in seen else seen).add(i)
    return sorted(dup)


def reading_rule_errors(prompt, reading):
    errors = [f"schema: {e}" for e in schema_errors(reading, READING_SCHEMA, "reading")]
    if errors:
        return errors
    if reading["prompt_sha256"] != prompt_sha256(prompt):
        errors.append("prompt_sha256 is not the hash of the request bytes")
    for span in spans_in(reading):
        if not (0 <= span["start"] < span["end"] <= len(prompt)) or prompt[span["start"]:span["end"]] != span["text"]:
            errors.append(f"span {span} does not equal the request bytes")
    for field in ("witness", "facts", "constraints", "deliverables", "ambiguities", "boundaries"):
        dup = _duplicates(item["id"] for item in reading[field])
        if dup:
            errors.append(f"duplicate {field} ids {dup}")
    witness = {w["id"] for w in reading["witness"]}
    used = {f["witness"] for f in reading["facts"] if f["witness"]}
    dismissed = {d["witness"] for d in reading["dismissed"]}
    if used - witness or dismissed - witness:
        errors.append(f"facts or dismissals name unknown witness items {sorted((used | dismissed) - witness)}")
    if witness - used - dismissed:
        errors.append(f"witness items neither used nor dismissed {sorted(witness - used - dismissed)}")
    for fact in reading["facts"]:
        if fact["authority"] == "user_quoted" and not fact["evidence"]:
            errors.append(f"{fact['id']} is user_quoted without a span")
    for constraint in reading["constraints"]:
        if constraint["type"] == "delegation" and constraint["value"].get("authority_granted") is not False:
            errors.append(f"{constraint['id']}: a delegation phrase must record authority_granted false")
    if reading["authors"][0]["actor"] != "deterministic-reader":
        errors.append("the deterministic reader must be the first author")
    for ambiguity in reading["ambiguities"]:
        ids = [r["id"] for r in ambiguity["readings"]]
        if _duplicates(ids):
            errors.append(f"{ambiguity['id']} repeats a reading id")
        if ambiguity["default"] is not None and ambiguity["default"] not in ids:
            errors.append(f"{ambiguity['id']} default names no reading")
    return errors


def plan_ids(plan):
    return {item["id"] for field in ("nodes", "inputs", "claims", "waypoints") for item in plan[field]}


def plan_rule_errors(reading, plan, obligation_ids=None):
    errors = [f"schema: {e}" for e in schema_errors(plan, PLAN_SCHEMA, "plan")]
    if errors:
        return errors
    if plan["prompt_sha256"] != reading["prompt_sha256"]:
        errors.append("plan and reading hash different requests")
    for field in ("nodes", "inputs", "edges", "claims", "waypoints"):
        dup = _duplicates(item["id"] for item in plan[field])
        if dup:
            errors.append(f"duplicate {field} ids {dup}")
    refs = {n["id"] for n in plan["nodes"]} | {i["id"] for i in plan["inputs"]}
    claims = {c["id"] for c in plan["claims"]}
    for edge in plan["edges"]:
        # A claim is a sink: an edge may deliver an artifact to it (its lineage), never start at it.
        if edge["from"]["ref"] not in refs:
            errors.append(f"{edge['id']} from names unknown {edge['from']['ref']}"
                          + (" (a claim is never a source)" if edge["from"]["ref"] in claims else ""))
        if edge["to"]["ref"] not in refs | claims:
            errors.append(f"{edge['id']} to names unknown {edge['to']['ref']}")
    reading_boundaries = {b["id"] for b in reading["boundaries"]}
    if set(plan["boundaries"]) - reading_boundaries:
        errors.append(f"plan boundaries absent from the reading {sorted(set(plan['boundaries']) - reading_boundaries)}")
    known = plan_ids(plan) | {a["id"] for a in reading["ambiguities"]} | reading_boundaries
    covered = {}
    for row in plan["coverage"]:
        missing = set(row["by"]) - known
        if missing:
            errors.append(f"coverage of {row['obligation_id']} names unknown {sorted(missing)}")
        covered.setdefault(row["obligation_id"], set()).update(row["by"])
    for obligation in obligation_ids or ():
        if not covered.get(obligation):
            errors.append(f"obligation {obligation} is covered by nothing")
    for claim in plan["claims"]:
        if claim["inherits"] and claim["kind"] != "document":
            errors.append(f"{claim['id']} inherits claims but is not a document claim")
    # acyclic over node and input references
    graph = {}
    for edge in plan["edges"]:
        graph.setdefault(edge["from"]["ref"], set()).add(edge["to"]["ref"])
    state = {}

    def cyclic(node):
        state[node] = 1
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1 or (state.get(nxt) is None and cyclic(nxt)):
                return True
        state[node] = 2
        return False

    if any(state.get(n) is None and cyclic(n) for n in list(graph)):
        errors.append("the plan graph has a cycle")
    return errors


# --------------------------------------------------------------------------------------------
# Binding to the production modules
# --------------------------------------------------------------------------------------------


def _module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name and name.startswith(exc.name):
            return None
        raise


def _first(module, names):
    for name in names:
        fn = getattr(module, name, None) if module else None
        if callable(fn):
            return fn
    return None


def _call(fn, *args, **optional):
    params = inspect.signature(fn).parameters
    kwargs = {k: v for k, v in optional.items() if k in params}
    return fn(*args, **kwargs)


class Intake:
    """The reader, planner, plan check and derived label, bound when their modules exist."""

    def __init__(self):
        self.reading_module = _module("ravel.workflow.request_reading")
        self.plan_module = _module("ravel.workflow.request_plan")
        self.check_module = _module("ravel.validation.validate_request_plan")
        self.label_module = _module("ravel.workflow.derived_label")
        self._document = _first(self.reading_module, ("document",))
        self._reading_check = _first(self.reading_module, ("check",))
        self._draft = _first(self.plan_module, ("draft",))
        self._plan_check = _first(self.check_module, ("check", "validate", "validate_request_plan"))
        self._derive = _first(self.label_module, ("derive",))

    def require(self, *parts):
        names = {"reader": ("ravel.workflow.request_reading.document", self._document),
                 "reading_check": ("ravel.workflow.request_reading.check", self._reading_check),
                 "planner": ("ravel.workflow.request_plan.draft", self._draft),
                 "plan_check": ("ravel.validation.validate_request_plan.check", self._plan_check),
                 "label": ("ravel.workflow.derived_label.derive", self._derive)}
        for part in parts:
            name, fn = names[part]
            if fn is None:
                pytest.skip(f"{name} has not landed")

    def read(self, prompt, interpretation=None):
        self.require("reader")
        if interpretation is None:
            return self._document(prompt)
        return _call(self._document, prompt, interpretation=interpretation)

    def reading_errors(self, prompt, reading):
        self.require("reading_check")
        return list(_call(self._reading_check, reading, prompt) or [])

    def contract(self, prompt):
        from ravel.workflow import route_prompt
        return route_prompt.route(prompt)

    def plan(self, reading, contract):
        self.require("planner")
        return self._draft(reading, contract)

    def plan_errors(self, reading, plan, delegation=None):
        self.require("plan_check")
        result = _call(self._plan_check, reading, plan, registry=None, delegation=delegation)
        if isinstance(result, dict):
            result = result.get("errors", [])
        return list(result or [])

    def label(self, reading, plan):
        self.require("label")
        return self._derive(reading, plan)

    def obligation_ids(self, contract):
        requirements = contract.get("task_requirements") if isinstance(contract, dict) else None
        if not isinstance(requirements, dict):
            return None
        return [o["id"] for o in requirements.get("obligations", []) if isinstance(o, dict) and "id" in o]


def error_classes(errors):
    return {e.get("error_class") if isinstance(e, dict) else str(e) for e in errors}


def signatures():
    """{operation: signature} from the operation signature registry, or None before it lands."""
    path = REPO / "src" / "ravel" / "data" / "operation_signatures.json"
    if not path.is_file():
        return None
    document = json.loads(path.read_text())
    # The registry file wraps its entries: {schema_version, kind, scope, operations: {name: entry}}.
    return document.get("operations", document) if isinstance(document, dict) else None


def node_effects(plan, registry):
    """Effects per node: the registry's, plus varies_parameters for a node that fans out over a grid
    and runs_authored_code for an authored node (architecture §2.4, operation effects)."""
    effects = {}
    for node in plan["nodes"]:
        entry = registry.get(node["operation"]) if node["operation"] else None
        found = set(entry.get("effects", [])) if isinstance(entry, dict) else set()
        if node.get("fan_out"):
            found.add("varies_parameters")
        if node["kind"] == "authored":
            found.add("runs_authored_code")
        effects[node["id"]] = found
    return effects


# --------------------------------------------------------------------------------------------
# Projections used by expectations and by the label-neutrality hashes
# --------------------------------------------------------------------------------------------


def locate(prompt, needle):
    """The [start, end) of the first occurrence of ``needle``; raises if the case is malformed."""
    start = prompt.find(needle)
    if start < 0:
        raise AssertionError(f"case text {needle!r} does not occur in its prompt")
    return start, start + len(needle)


def overlaps(span, window):
    return span["start"] < window[1] and window[0] < span["end"]


def evidence_overlapping(items, window, key="evidence"):
    return [item for item in items if any(overlaps(s, window) for s in item.get(key) or [] if "start" in s)]


def is_held(reading, label=None):
    """Whether the outcome holds the whole request (derived rule D1 or a whole-request boundary)."""
    if label is not None and label.get("rule") == "D1":
        return True
    # Rule D1 read off the reading alone: a whole-request class, or a boundary that names the whole request.
    return any(b["class"] in WHOLE_REQUEST_BOUNDARIES or "original-request" in b["obligation_ids"]
               for b in reading["boundaries"] if b["class"] != "control_bypass_request")


def bare_refusal(reading, plan, label=None):
    """Reasons the outcome is a refusal that names no boundary class, evidence or way forward."""
    reasons = []
    for boundary in reading["boundaries"]:
        if boundary["class"] not in BOUNDARY_CLASSES:
            reasons.append(f"{boundary['id']} has no boundary class")
        if not boundary["evidence"]:
            reasons.append(f"{boundary['id']} has no evidence")
        if not boundary["would_make_possible"].strip() or not boundary["statement"].strip():
            reasons.append(f"{boundary['id']} does not say what would make the request possible")
    held = is_held(reading, label)
    if held and not reading["boundaries"]:
        reasons.append("the request is held with no boundary row")
    if label is not None and label.get("task_mode") == "unsupported" and not reading["boundaries"]:
        reasons.append("the derived label is unsupported with no boundary row")
    if not held and plan is not None:
        working = [n for n in plan["nodes"] if n["status"] != "held" or n["held_by"]]
        if not working and not plan["inputs"] and not plan["claims"]:
            reasons.append("the plan neither works on, asks for, nor claims anything")
    return reasons


def _span_texts(item, key="evidence"):
    return sorted(s["text"] for s in item.get(key) or [] if isinstance(s, dict) and "text" in s)


def _inside(item, windows, key="evidence"):
    spans = [s for s in item.get(key) or [] if isinstance(s, dict) and "start" in s]
    return bool(spans) and all(any(w[0] <= s["start"] and s["end"] <= w[1] for w in windows) for s in spans)


def neutral_projection(reading, plan=None, label=None, *, ignore_constraints=("identity_context",)):
    """Everything a decision may depend on, without offsets, ids, locators or identity context."""
    windows = [(s["start"], s["end"]) for c in reading["constraints"] if c["type"] == "identity_context"
               for s in c["evidence"]]
    dump = lambda value: json.dumps(value, sort_keys=True)  # noqa: E731
    facts = sorted(dump([f["type"], f["value"], f["authority"], f["physics_critical"], _span_texts(f)])
                   for f in reading["facts"] if not _inside(f, windows))
    constraints = sorted(dump([c["type"], c["value"], _span_texts(c)]) for c in reading["constraints"]
                         if c["type"] not in ignore_constraints and not _inside(c, windows))
    deliverables = sorted(dump([d["artifact"], d["claim_kind"]]) for d in reading["deliverables"])
    ambiguities = sorted(dump([a["issue"], a["physics_critical"], a["observable_impact"], _span_texts(a),
                               sorted(r["id"] for r in a["readings"])]) for a in reading["ambiguities"])
    boundaries = sorted(dump([b["class"], sorted(s.get("text", "") for s in b["evidence"])])
                        for b in reading["boundaries"])
    projection = {"facts": facts, "constraints": constraints, "deliverables": deliverables,
                  "ambiguities": ambiguities, "boundaries": boundaries}
    if plan is not None:
        operations = {n["id"]: n["operation"] or n["kind"] for n in plan["nodes"]}
        operations.update({i["id"]: f"input:{i['provides']['kind']}" for i in plan["inputs"]})
        projection["plan"] = {
            "nodes": sorted(dump([n["kind"], n["operation"], n["implementation"], n["status"], n["held_by"],
                                  n["rung"]]) for n in plan["nodes"]),
            "inputs": sorted(dump([i["provides"], i["source"], i["status"]]) for i in plan["inputs"]),
            "edges": sorted(dump([operations.get(e["from"]["ref"]), e["from"]["slot"], operations.get(e["to"]["ref"]),
                                  e["to"]["slot"], e["kind"], e["resolution"]]) for e in plan["edges"]),
            "claims": sorted(dump([c["kind"], c["level"], c["statistic"]["source"], c["statistic"]["definition"],
                                   c["comparison"]["target"], sorted(c["basis_declared"])]) for c in plan["claims"]),
            "waypoints": sorted(w["kind"] for w in plan["waypoints"]),
        }
    if label is not None:
        projection["label"] = {k: label.get(k) for k in ("task_mode", "rule", "floor_row")}
    return projection


def projection_hash(projection):
    return hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()


# --------------------------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------------------------
CASES_DIR = Path(__file__).resolve().parent / "cases"
CASE_FILES = ("ported.json", "generic.json", "coverage.json", "probes.json", "adversarial.json")
EXPECT_KEYS = {"spans", "constraints", "constraints_absent", "not_mass", "boundaries", "held", "claims",
               "claim_kinds_absent", "effects_required", "effects_forbidden", "ambiguity", "scan_range",
               "statement_excludes", "delegation", "prescribed_statistic", "fact_types_absent", "boundaries_any"}


def load_cases(*names):
    cases = []
    for name in names or CASE_FILES:
        doc = syn.load_json(CASES_DIR / name)
        for case in doc["cases"]:
            cases.append(dict(case, file=name))
    return cases


def case_params(*names):
    return [pytest.param(case, id=case["id"]) for case in load_cases(*names)]


def shape_errors(case):
    """Structural errors in a case: unknown keys, vocabulary or text absent from the prompt."""
    errors = []
    prompt, expect = case["prompt"], case.get("expect", {})
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        errors.append(f"unknown expectation keys {sorted(unknown)}")
    texts = list(expect.get("spans", [])) + list(expect.get("not_mass", [])) + list(expect.get("ambiguity", []))
    texts += [c["span"] for c in expect.get("constraints", []) if "span" in c]
    texts += [expect["scan_range"]] if "scan_range" in expect else []
    texts += [expect["prescribed_statistic"]] if "prescribed_statistic" in expect else []
    for text in texts:
        if text not in prompt:
            errors.append(f"{text!r} is not in the prompt")
    for c in expect.get("constraints", []):
        if c.get("type") not in CONSTRAINT_TYPES:
            errors.append(f"unknown constraint type {c.get('type')!r}")
    for t in expect.get("constraints_absent", []):
        if t not in CONSTRAINT_TYPES:
            errors.append(f"unknown constraint type {t!r}")
    for cls in expect.get("boundaries", []) + expect.get("boundaries_any", []):
        if cls not in BOUNDARY_CLASSES:
            errors.append(f"unknown boundary class {cls!r}")
    for claim in expect.get("claims", []):
        for key, vocab in (("kind", CLAIM_KINDS), ("level", LEVELS), ("comparison", COMPARISON_TARGETS),
                           ("statistic_source", STATISTIC_SOURCES)):
            for value in claim.get(key, []):
                if value not in vocab:
                    errors.append(f"claim {key} {value!r} is not in its vocabulary")
    for kind in expect.get("claim_kinds_absent", []):
        if kind not in CLAIM_KINDS:
            errors.append(f"unknown claim kind {kind!r}")
    for effect in expect.get("effects_required", []) + expect.get("effects_forbidden", []):
        if effect not in EFFECTS:
            errors.append(f"unknown effect {effect!r}")
    return errors


def expectation_failures(case, reading, plan=None, label=None, registry=None):
    """Every expectation of a case that the reading, plan and label do not meet."""
    prompt, expect, failures = case["prompt"], case.get("expect", {}), []
    statements = reading["facts"] + reading["constraints"]
    for text in expect.get("spans", []):
        if not evidence_overlapping(statements, locate(prompt, text)):
            failures.append(f"{text!r} is not read as a fact or constraint")
    for wanted in expect.get("constraints", []):
        rows = [c for c in reading["constraints"] if c["type"] == wanted["type"]]
        if "span" in wanted:
            rows = evidence_overlapping(rows, locate(prompt, wanted["span"]))
        if not rows:
            failures.append(f"no {wanted['type']} constraint" + (f" on {wanted['span']!r}" if "span" in wanted else ""))
    for kind in expect.get("constraints_absent", []):
        if any(c["type"] == kind for c in reading["constraints"]):
            failures.append(f"unexpected {kind} constraint")
    for text in expect.get("not_mass", []):
        masses = [f for f in reading["facts"] if "mass" in f["type"].lower()]
        if evidence_overlapping(masses, locate(prompt, text)):
            failures.append(f"{text!r} is read as a mass")
    for text in expect.get("ambiguity", []):
        if not evidence_overlapping(reading["ambiguities"], locate(prompt, text)):
            failures.append(f"no ambiguity row on {text!r}")
    if "prescribed_statistic" in expect:
        window = locate(prompt, expect["prescribed_statistic"])
        rows = evidence_overlapping([c for c in reading["constraints"] if c["type"] == "prescribed_statistic"], window)
        if not rows:
            failures.append(f"the prescribed statistic {expect['prescribed_statistic']!r} is not recorded")
    if "delegation" in expect:
        has = any(c["type"] == "delegation" for c in reading["constraints"])
        if has != expect["delegation"]:
            failures.append("delegation " + ("missing" if expect["delegation"] else "recorded without a phrase"))
    classes = sorted({b["class"] for b in reading["boundaries"]})
    if "boundaries" in expect and classes != sorted(set(expect["boundaries"])):
        failures.append(f"boundary classes {classes}, expected {sorted(set(expect['boundaries']))}")
    if expect.get("boundaries_any") and not set(classes) & set(expect["boundaries_any"]):
        failures.append(f"boundary classes {classes}, expected one of {expect['boundaries_any']}")
    for word in expect.get("fact_types_absent", []):
        if any(word.lower() in f["type"].lower() for f in reading["facts"]):
            failures.append(f"a fact of type {word!r} was read from request text")
    if "held" in expect and is_held(reading, label) != expect["held"]:
        failures.append("the request is " + ("not held" if expect["held"] else "held"))
    if plan is None:
        return failures
    for wanted in expect.get("claims", []):
        matches = [c for c in plan["claims"]
                   if (not wanted.get("kind") or c["kind"] in wanted["kind"])
                   and (not wanted.get("level") or c["level"] in wanted["level"])
                   and (not wanted.get("comparison") or c["comparison"]["target"] in wanted["comparison"])
                   and (not wanted.get("statistic_source") or c["statistic"]["source"] in wanted["statistic_source"])
                   and (not wanted.get("statistic_text")
                        or wanted["statistic_text"] in (c["statistic"]["definition"] or ""))]
        if not matches:
            failures.append(f"no claim matching {wanted}")
    for kind in expect.get("claim_kinds_absent", []):
        if any(c["kind"] == kind for c in plan["claims"]):
            failures.append(f"unexpected {kind} claim")
    for word in expect.get("statement_excludes", []):
        for claim in plan["claims"]:
            if word.lower() in claim["statement"].lower():
                failures.append(f"{claim['id']} statement presupposes the outcome ({word!r})")
    if "scan_range" in expect:
        window = locate(prompt, expect["scan_range"])
        fanned = any(n["fan_out"] for n in plan["nodes"])
        asked = evidence_overlapping(reading["ambiguities"], window)
        if not (fanned or asked):
            failures.append(f"the range {expect['scan_range']!r} became a one-point plan")
    if registry is not None:
        effects = set().union(*node_effects(plan, registry).values()) if plan["nodes"] else set()
        for effect in expect.get("effects_required", []):
            if effect not in effects:
                failures.append(f"no node {effect}")
        for effect in expect.get("effects_forbidden", []):
            if effect in effects:
                failures.append(f"a node {effect}, which the request does not ask for")
    return failures


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


VOCABULARY_DENYLIST = re.compile(
    r"atlas|cms|lhcb|alice|belle|cdf|d0|lep|planck|arxiv|hepdata|inspire|bench|challenge|workflow|recast"
    r"|reproduce|reinterpret|survey|summary_plot|projection|anomaly|olympics|paper", re.I)
