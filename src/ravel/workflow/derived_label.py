"""The compatibility label derived from a request reading and, when present, its plan.

`derive(reading, plan)` is pure. In Stage 1 its `task_mode` selects the schema-v1
evaluator; `floor_row` is the stage row that bounds a v2 plan from below in Stage 2
(INTAKE-ARCHITECTURE sections 2.8.3 and 4.3). The first matching rule applies:

D1  a whole-request boundary, or boundaries covering every finer obligation: `unsupported`
D2  one scoped node serving every requested stage: `generate` or `likelihood`
D3  one route-A lifecycle node: its shape, as today
D4  a calculation served by goal-bound science children: `calculation`
D5  otherwise: a `research` parent (an open parent when nothing recognised the request)

The function reads boundaries, constraints, deliverables and lexical route hints. It
never reads an `identity_context` constraint or raw request text, so a benchmark,
challenge or task name cannot change the label. A route hint proposes; it never admits.
"""
from __future__ import annotations

from . import request_reading as rr

RULES = ("D1", "D2", "D3", "D4", "D5")
ROUTE_A = ("reproduce", "reinterpret", "projection", "scan", "summary_plot", "survey", "anomaly_search",
           "no_routine")
# Stages each scoped adapter serves. The scoped shower stage runs Pythia 8 only.
SCOPED_SERVES = {"generate": frozenset({"generation", "lhe-transform", "shower", "figure"}),
                 "likelihood": frozenset({"statistic", "figure"})}
UNSERVED_TOOLS = {"shower": frozenset({"Herwig", "Sherpa"})}
LIFECYCLE_IMPLEMENTATIONS = ("lifecycle-stage", "route-a")
SCOPED_IMPLEMENTATIONS = ("scoped", "scoped-adapter")
SCIENCE_IMPLEMENTATIONS = ("science-mode",)

_WHY = {
    "ungrounded_identifier": "claimed context identifier contains scientific actions, qualifiers or ambiguous content; "
                             "retain the whole request and resolve a grounded --interpretation before selecting a route",
    "no_scientific_object": "no scientific object: nothing actionable remains once negated and quoted text is "
                            "removed; restate the request positively, or resolve a grounded --interpretation",
}


def _hints(reading):
    rows = [f["value"] for f in reading["facts"] if f["type"] == "route_hint"]
    return sorted(rows, key=lambda h: (h.get("rank", 0), h.get("rule", "")))


def _hint(reading, rule):
    return next((h for h in _hints(reading) if h.get("rule") == rule), None)


def _requested_stages(reading):
    return {c["value"]["stage"] for c in reading["constraints"] if c["type"] == "requested_stage"}


def _tools(reading):
    return {c["value"]["tool"] for c in reading["constraints"] if c["type"] == "requested_tool"}


def unserved_stages(reading, mode):
    """Requested stages the scoped `mode` adapter does not serve, in canonical order."""
    served = SCOPED_SERVES.get(mode, frozenset())
    tools = _tools(reading)
    out = []
    for name, _ in rr.STAGES:
        if name not in _requested_stages(reading):
            continue
        if name not in served or tools & UNSERVED_TOOLS.get(name, frozenset()):
            out.append(name)
    return out


def _boundary_blocking(row):
    if row["class"] in _WHY:
        return _WHY[row["class"]]
    if row["class"] == "unsupportable_claim":
        return ("discovery-language: An observed discovery claim requires supporting analysis and statistical "
                "evidence. Preserve the original question and report the exact data/evidence boundary; do not "
                "replace it with exclusion. " + row["statement"] + " What would make it possible: "
                + row["would_make_possible"])
    return (f"boundary ({row['class']}): {row['statement']} What would make it possible: "
            f"{row['would_make_possible']} Preserve the original question; do not replace it with an exclusion "
            "or another quantity.")


def held_boundaries(reading, *, intent=None):
    """Boundary rows that hold the whole request (rule D1), or [] when none does."""
    host = intent is not None and intent.get("source") == "host-agent"
    rows = reading["boundaries"]
    whole = [r for r in rows if r["class"] in rr.WHOLE_REQUEST_BOUNDARIES
             and not (host and r["class"] in rr.WHOLE_REQUEST_BOUNDARIES)]
    if whole:
        return whole
    # The finer obligations: those the reading implies with spans, plus every obligation a
    # deliverable names. A boundary holds the whole request only when it covers all of them
    # (and there is at least one), or names the whole request itself.
    finer = {row["id"] for row in rr.obligation_items(reading)}
    finer |= {o for d in reading["deliverables"] for o in d["obligation_ids"] if o != rr.ORIGINAL}
    scoped = [r for r in rows if r["class"] in ("inaccessible_input", "unsupportable_claim", "contradiction")]
    if host:
        scoped = [r for r in scoped if r["class"] == "unsupportable_claim"]
    covered = {o for r in scoped for o in r["obligation_ids"]}
    if scoped and ((finer and covered >= finer) or rr.ORIGINAL in covered):
        return scoped
    return []


def _label(task_mode, rule, *, status="routed", open_parent=False, blocking=(), would=(), hint=None, note=None):
    return {"task_mode": task_mode, "rule": rule, "floor_row": task_mode, "status": status,
            "open": bool(open_parent), "blocking": list(blocking), "would_make_possible": list(would),
            "hint": hint, "note": note}


def _kind_label(kind, reading, *, source, operation=None):
    """The label a recognised request kind proposes, before the plan refines it."""
    if kind == "method_study":
        return _label("survey", "D5", hint=source, note="method-study storage: a survey intake of kind method_study")
    if kind in ("generate", "likelihood"):
        if source != "host-agent" and unserved_stages(reading, kind):
            return None
        return _label(kind, "D2", hint=source)
    if kind == "calculation":
        return _label("calculation", "D4", hint=source)
    if kind == "research":
        return _label("research", "D5", hint=source)
    if kind in ROUTE_A:
        return _label(kind, "D3", hint=source)
    return None


def _propose(reading, intent):
    held = held_boundaries(reading, intent=intent)
    if held:
        return _label("unsupported", "D1", status="held", blocking=[_boundary_blocking(r) for r in held],
                      would=[r["would_make_possible"] for r in held])
    if intent is not None and intent.get("source") == "host-agent":
        kind = intent.get("kind")
        label = _kind_label(kind, reading, source="host-agent", operation=intent.get("operation"))
        if label is not None:
            return label
    if any(f['type'] == 'question_form' for f in reading['facts']):
        return _label('research', 'D5', open_parent=True, hint='question-form',
                      note='outcome-open question retained by the research coordinator')
    semantic = _hint(reading, "semantic-kind")
    if semantic and semantic.get("mode"):
        label = _kind_label(semantic["mode"], reading, source="semantic-kind", operation=semantic.get("operation"))
        if label is not None:
            return label
        if semantic["mode"] in ("generate", "likelihood"):
            return _label("research", "D5", open_parent=True, hint="semantic-kind",
                          note="requested stages beyond the scoped adapter: "
                               + ", ".join(unserved_stages(reading, semantic["mode"])))
    inferred = _hint(reading, "inferred-kind")
    if inferred and inferred.get("mode"):
        label = _kind_label(inferred["mode"], reading, source="inferred-kind")
        if label is not None:
            return label
    for hint in _hints(reading):
        if hint.get("strength") != "strong" or hint.get("rule") in ("semantic-kind", "inferred-kind"):
            continue
        if hint.get("rule") == "measurement-fit-shape":
            continue
        label = _kind_label(hint["mode"], reading, source=hint["rule"])
        if label is not None:
            return label
    return _label("research", "D5", open_parent=True, hint=None,
                  note="no rule recognises the request as one bounded shape; an open parent composes it")


def _structural(reading, plan, catalogue=None):
    """Rules D2-D4 read off a schema-valid plan's structure (request_plan.provisional_label), or None."""
    try:
        from ravel.validation import validate_request_plan as rp
        from ravel.workflow import request_plan
    except ImportError:
        return None
    if rp.plan_schema_errors(plan):
        return None
    try:
        return request_plan.provisional_label(reading, plan, catalogue=catalogue)
    except (KeyError, TypeError, ValueError):
        return None


def _refine(label, plan, reading, intent, catalogue=None):
    """Stage 1 rules D2-D5 against the plan's nodes, when a plan exists.

    A proposal from the reading (D2, D3 or D4) stands only when the plan has the structure its
    rule names; otherwise the request is a research parent. A request no hint recognises (D5)
    takes the rule the plan's structure satisfies: one scoped node serving every requested stage
    (D2), one route-A lifecycle node P0-S1' admits (D3), or goal-bound science calculations (D4).
    """
    nodes = plan.get("nodes") or []
    if label["rule"] == "D1" or not nodes:
        return label
    if intent is not None and intent.get("source") == "host-agent":
        return label
    implementations = [n.get("implementation") for n in nodes]
    if label["rule"] == "D2" and not (len(nodes) == 1 and implementations[0] in SCOPED_IMPLEMENTATIONS):
        return _label("research", "D5", open_parent=True, hint=label["hint"],
                      note="the plan needs more than one scoped node")
    if label["rule"] == "D3" and not (len(nodes) == 1 and implementations[0] in LIFECYCLE_IMPLEMENTATIONS):
        return _label("research", "D5", open_parent=True, hint=label["hint"],
                      note="the plan is not a single route-A lifecycle node")
    if label["rule"] == "D4" and not all(i in SCIENCE_IMPLEMENTATIONS for i in implementations):
        return _label("research", "D5", open_parent=False, hint=label["hint"],
                      note="the calculation needs nodes beyond goal-bound science children")
    if label["rule"] == "D5":
        structural = _structural(reading, plan, catalogue)
        if structural is not None and structural["rule"] in ("D2", "D3", "D4"):
            return _label(structural["task_mode"], structural["rule"], hint=label["hint"],
                          note="rule " + structural["rule"] + " read off the plan's structure")
        if structural is not None and structural["rule"] == "D1":
            return _label("unsupported", "D1", status="held", hint=label["hint"],
                          blocking=[_boundary_blocking(r) for r in reading["boundaries"]],
                          would=[r["would_make_possible"] for r in reading["boundaries"]])
    return label


def floor_row(reading, plan=None, label=None):
    """The Stage 2 floor row, from the claims when a plan has them."""
    label = label or derive(reading, plan)
    if label["rule"] == "D1":
        return "unsupported"
    claims = (plan or {}).get("claims") or []
    if not claims:
        return label["task_mode"]
    kinds = {c.get("kind") for c in claims}
    nodes = (plan or {}).get("nodes") or []
    if len(nodes) == 1 and nodes[0].get("implementation") in SCOPED_IMPLEMENTATIONS:
        return label["task_mode"] if label["task_mode"] in ("generate", "likelihood") else "generate"
    published = {"simulated_acceptance", "published_statistical_model", "reimplemented_statistical_model"}
    declared = {b for c in claims for b in c.get("basis_declared", [])}
    certifiable = bool(declared & published)
    if any(n.get("fan_out") for n in nodes) and kinds & {"exclusion", "estimate"} and certifiable:
        return "scan"
    if any((c.get("comparison") or {}).get("target") == "published_figure" for c in claims) and certifiable:
        return "reproduce"
    if "exclusion" in kinds and certifiable:
        return "reinterpret"
    if any(c.get("level") == "expected" for c in claims) and certifiable:
        return "projection"
    if "finding" in kinds and any((c.get("deliverable") or {}).get("artifact") == "figure" for c in claims):
        return "summary_plot"
    if declared and declared <= {"published_results", "analytic", "supplied_inputs"}:
        return "survey" if kinds <= {"finding", "agreement"} else "calculation"
    if "method_performance" in kinds:
        return "method_study"
    if kinds == {"document"}:
        return "manuscript"
    return "research"


def derive(reading, plan=None, *, intent=None, catalogue=None):
    """The derived label: {task_mode, rule, floor_row, status, open, blocking, would_make_possible, hint, note}.

    `intent` is the validated host interpretation recorded in the contract's intake (Stage 1's
    stand-in for a host-composed plan); a local-parser intake adds nothing beyond the reading.
    """
    label = _propose(reading, intent)
    if plan is not None:
        label = _refine(label, plan, reading, intent, catalogue)
    label["floor_row"] = _floor(reading, plan, label) if plan is not None else (
        "unsupported" if label["rule"] == "D1" else label["task_mode"])
    return label


def _floor(reading, plan, label):
    """The floor row: from the plan's computed bases when the plan is schema-valid, else declared bases."""
    if label["rule"] == "D1":
        return "unsupported"
    try:
        from ravel.validation import validate_request_plan as rp
        from ravel.workflow import request_plan
    except ImportError:
        return floor_row(reading, plan, label)
    if rp.plan_schema_errors(plan):
        return floor_row(reading, plan, label)
    return request_plan.floor_row(reading, plan)


def plan_label(reading, plan, *, catalogue=None):
    """The {task_mode, rule, floor_row} a request plan records: the derived label of its reading and plan.

    `catalogue(locator) -> bool` overrides the analysis-catalogue lookup, as in `request_plan.draft`.
    """
    label = derive(reading, plan, catalogue=catalogue)
    return {key: label[key] for key in ("task_mode", "rule", "floor_row")}
