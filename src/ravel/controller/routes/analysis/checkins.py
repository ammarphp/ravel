"""Typed CHECK-INs of the analysis route, rendered from run state (A06, C03, C04, C14, C10, C36).

The authority service renders and presents a check-in (``checkin.v1``) from a view the controller
builds. This module builds the analysis route's part of that view from controller-owned evidence
only: the plan the store pins, the prepare-phase outputs the governed steps adopted (environment,
resource census, route analysis, trap sweep, figure target, waypoint, cost) and, later, the
waypoint and result artifacts. A worker never writes a check-in.

Before anything is shown, the content is checked twice:

- with the existing CHECK-IN validator (``validate_checkin``) on the equivalent section document:
  every core and variant section present with content (no placeholder), numbered flags ``F<n>``,
  the three response modes, the waypoint in (iii), and the reference-withheld rules
  (``checkin_withheld``);
- with route rules: the variant is the one the pinned request selects (C04), every result-sensitive
  assumption is a numbered flag with its reason and alternatives (C14), the cost record and the
  scan grid are present and current (A06), and for the final check-in the recipe ledger keeps every
  unknown row (C36).

``errors`` in a view hold the authority point: an incomplete check-in is never presented.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import shlex

from . import common, evidence, scan
from .common import error, placeholder

TEMPLATES = Path(__file__).resolve().parents[3] / "data" / "checkin" / "analysis.json"
RESPONSE_MODES = ["answer the numbered flags", "ask clarifying questions", "propose alterations to the plan"]
FLAG_KINDS = ("assumption", "decision", "question", "ambiguity", "risk")


@lru_cache(maxsize=1)
def _templates_text():
    return TEMPLATES.read_text(encoding="utf-8")


def templates() -> dict:
    document = json.loads(_templates_text())
    if document.get("kind") != "route-checkin-templates" or document.get("schema_version") != 1:
        raise ValueError("the analysis check-in templates are malformed")
    return document


def template(kind) -> dict:
    found = templates()["checkins"].get(kind)
    if found is None:
        raise ValueError(f"the analysis route has no {kind} check-in")
    return found


# ---- evidence ---------------------------------------------------------------------------------

def prepare_steps(plan) -> dict:
    """``adapter -> step`` for the plan's prepare-phase steps."""
    return {common.adapter_of(s): s for s in (plan or {}).get("steps") or ()
            if common.phase_of(s) == "prepare" and common.adapter_of(s)}


def collect(context) -> tuple[dict, list]:
    """``({file name: {doc, pin, step}}, problems)`` for the prepare-phase evidence CHECK-IN 1 presents."""
    plan = context.get("plan") or {}
    wanted = template("approve_plan")["evidence"]
    steps = prepare_steps(plan)
    found, problems = {}, []
    for adapter, names in wanted.items():
        step = steps.get(adapter)
        if step is None:
            problems.append(error("checkin_evidence_unplanned", f"the plan has no {adapter} step", row="A06"))
            continue
        for name in names:
            declared = next((o for o in step.get("outputs") or () if o["path"].endswith(name)), None)
            if declared is None:
                problems.append(error("checkin_evidence_undeclared", f"step {step['id']} declares no {name}",
                                      row="A06", step=step["id"]))
                continue
            doc, pin, problem = common.read_output(context, step["id"], declared["path"])
            if problem:
                if declared.get("required", True):
                    problems.append(error("checkin_evidence_missing", problem, row="A06", step=step["id"]))
                continue
            found[name] = {"doc": doc, "pin": pin, "step": step["id"]}
    return found, problems


def _doc(found, name):
    row = found.get(name)
    return row["doc"] if row and isinstance(row.get("doc"), dict) else {}


# ---- variant and flags ------------------------------------------------------------------------

def variant(context) -> tuple[str | None, list]:
    """The CHECK-IN 1 variant the pinned request selects, and refusals when it cannot be selected (C04)."""
    from ravel.validation import validate_checkin
    from ravel.workflow import source_policy
    contract = context.get("contract") or {}
    try:
        source_policy.canonical(contract.get("forbidden_sources", []))
    except (ValueError, TypeError) as exc:
        return None, [error("source_restrictions_invalid", f"the pinned source restriction census is invalid: {exc}",
                            row="C04", fix="correct the request's source restrictions before CHECK-IN 1")]
    allowed = validate_checkin.checkin_variant(contract)["allowed"] or ()
    chosen = "reference_withheld" if evidence.withheld(context) else "reproduction"
    if allowed and chosen not in allowed:
        return None, [error("checkin_variant_unfit", f"the request selects {chosen}, which task_mode "
                            f"{contract.get('task_mode')} does not admit ({', '.join(allowed)})", row="C04",
                            fix="route the request through the judgment graph or revise it")]
    return chosen, []


def _flag_text(statement, reason=None, alternatives=None):
    text = str(statement).strip()
    if reason:
        text += f" Why: {str(reason).strip()}"
    if alternatives:
        text += " Alternatives: " + "; ".join(str(a).strip() for a in alternatives if str(a).strip())
    return text


def flags(found, context) -> tuple[list, list]:
    """Numbered flags F1..Fn from the evidence and the pinned reading, and refusals (C14, P3)."""
    rows, errors = [], []
    route = _doc(found, "route_analysis.json")
    for item in route.get("assumptions") or ():
        if not isinstance(item, dict):
            continue
        sensitive = item.get("result_sensitive", True)
        statement, reason, alternatives = item.get("statement"), item.get("reason"), item.get("alternatives")
        if sensitive and (placeholder(statement) or placeholder(reason) or not alternatives
                          or placeholder(alternatives)):
            errors.append(error("flag_incomplete", f"result-sensitive assumption {item.get('id') or statement!r} "
                                "needs its statement, reason and alternatives as a numbered flag", row="C14"))
            continue
        rows.append({"kind": "assumption", "source": "route_analysis", "id": item.get("id"),
                     "text": _flag_text(statement, reason, alternatives), "result_sensitive": bool(sensitive)})
    for item in route.get("decisions") or ():
        if isinstance(item, dict) and not placeholder(item.get("statement")):
            rows.append({"kind": "decision", "source": "route_analysis", "id": item.get("id"),
                         "text": _flag_text(item["statement"], item.get("reason"), item.get("alternatives"))})
    sweep = _doc(found, "trap_sweep.json")
    escalated = {e.get("id") for e in sweep.get("escalations") or () if isinstance(e, dict)}
    for hit in sweep.get("traps_hit") or ():
        if not isinstance(hit, dict):
            continue
        if hit.get("flag_number") is None and hit.get("id") not in escalated:
            errors.append(error("trap_hit_unflagged", f"trap {hit.get('id')} was hit without a flag or an escalation",
                                row="C14"))
            continue
        rows.append({"kind": "risk", "source": "trap_sweep", "id": hit.get("id"),
                     "text": _flag_text(f"Trap {hit.get('id')} applies: {hit.get('consequence')}",
                                        hit.get("evidence"))})
    reading = context.get("reading") or {}
    for item in reading.get("ambiguities") or ():
        if isinstance(item, dict) and item.get("status", "open") == "open":
            readings = [o.get("id") if not isinstance(o.get("value"), dict) else
                        f"{o.get('id')} ({o['value'].get('source') or o['value']})"
                        for o in item.get("readings") or () if isinstance(o, dict)]
            issue = item.get("issue") or item.get("statement") or item.get("text")
            rows.append({"kind": "ambiguity", "source": "reading", "id": item.get("id"),
                         "text": _flag_text(f"{item.get('id')}: {issue}", None, readings or None)})
    if route.get("detector_mode") == "delphes-custom-uncertified":
        rows.append({"kind": "risk", "source": "route_analysis", "id": "uncertified-detector",
                     "text": "The detector response is an uncertified fast-simulation proxy with a custom selection: "
                             "results are labelled uncertified and are no exclusion of record."})
    for number, row in enumerate(rows, 1):
        row["n"] = number
    return rows, errors


# ---- CHECK-IN 1 -------------------------------------------------------------------------------

def _plan_lines(plan):
    lines = []
    for step in (plan or {}).get("steps") or ():
        parts = [step["id"], step["kind"]]
        if step.get("operation"):
            parts.append(step["operation"])
        if step.get("rung"):
            parts.append(f"rung {step['rung']}")
        argv = ((step.get("parameters") or {}).get("launch") or {}).get("argv")
        if isinstance(argv, list) and argv:
            parts.append("command: " + shlex.join(str(word) for word in argv))
        lines.append(" · ".join(parts))
    return lines


def _census_lines(doc):
    lines = []
    records = list(doc["records"]) if isinstance(doc.get("records"), list) else [doc]
    if isinstance(doc.get("records"), list) and isinstance(doc.get("rungs"), dict):
        records.append(doc)  # the census's own rungs (a reading that names no analysis is one)
    for record in records:
        if not isinstance(record, dict):
            continue
        name = record.get("analysis_id") or record.get("query") or record.get("id") or "census"
        rungs = record.get("rungs") if isinstance(record.get("rungs"), dict) else {}
        summary = ", ".join(f"{k}: {(v or {}).get('status')}" for k, v in sorted(rungs.items()) if isinstance(v, dict))
        if summary:
            lines.append(f"{name}: {summary}")
    return lines


def _method_lines(route, cost, plan):
    lines = []
    for key, label in (("routine", "Routine"), ("model", "Model"), ("final_state", "Final state"),
                       ("energy", "Collision energy"), ("detector_mode", "Detector response"),
                       ("stat_mode", "Statistic")):
        value = route.get(key)
        if not placeholder(value):
            lines.append(f"{label}: {value if isinstance(value, str) else json.dumps(value, sort_keys=True)}")
    if not placeholder(route.get("method")):
        lines.append(f"Cheapest sufficient method: {route['method']}")
    lines.append(f"Highest compute rung: {evidence.max_rung(plan)}")
    if cost:
        wall = cost.get("walltime_h")
        lines.append(f"Cost record: {cost.get('mode')} rung, calibration {cost.get('status')}, wall time "
                     f"{'unknown' if wall is None else wall} h; basis: {cost.get('basis')}")
    return lines


def legacy_document(found, context, chosen, numbered) -> dict:
    """The section document the existing CHECK-IN validator checks (keys i, i-b, ii, iii, iv, v, vi)."""
    plan = context.get("plan") or {}
    route = _doc(found, "route_analysis.json")
    sections = {
        "i": route.get("summary"),
        "i-b": _census_lines(_doc(found, "resource_census.json")) or None,
        "iv": {"steps": _plan_lines(plan), "method": _method_lines(route, _doc(found, "cost_preflight.json"), plan)},
        "v": [{"id": f"F{row['n']}", "kind": row["kind"], "text": row["text"]} for row in numbered],
        "vi": list(RESPONSE_MODES),
    }
    if chosen == "reproduction":
        gallery = _doc(found, "gallery.json").get("figures")
        targets = _doc(found, "figure_target.json").get("targets")
        proposal = _doc(found, "waypoint.json")
        sections["ii"] = gallery if gallery else None
        sections["iii"] = {"targets": targets, "waypoint": proposal or None} if targets else None
    else:
        sections["withheld_waypoints"] = _doc(found, "waypoint.json").get("withheld_waypoints")
    return {"schema_version": 1, "kind": "checkin1", "variant": chosen, "sections": sections}


def _waypoint_lines(proposal):
    """The proposed waypoint as a line, or none when the proposal states no element or expectation."""
    if placeholder(proposal.get("element")) or placeholder(proposal.get("expectation")):
        return []
    return [f"Waypoint: {proposal['element']}; expected {proposal['expectation']}"]


def _lines(value):
    if placeholder(value):
        return []
    if isinstance(value, str):
        return [value.strip()]
    if isinstance(value, list):
        return [v if isinstance(v, str) else json.dumps(v, sort_keys=True, ensure_ascii=False)
                for v in value if not placeholder(v)]
    if isinstance(value, dict):
        return [f"{k}: {v if isinstance(v, str) else json.dumps(v, sort_keys=True, ensure_ascii=False)}"
                for k, v in value.items() if not placeholder(v)]
    return [str(value)]


def _section(kind, name, value):
    titles = template(kind)["titles"]
    return {"id": name, "title": titles.get(name, name), "lines": [l for l in _lines(value) if l.strip()]}


def _items(plan, reading):
    reading = reading or {}
    items = {"steps": _plan_lines(plan),
             "deliverables": [f"{d['id']}: {d['status']}" + (f" ({d['step']}:{d['output']})" if d.get("step") else "")
                              for d in (plan or {}).get("deliverables") or ()],
             "boundaries": [str(b.get("statement")) for b in reading.get("boundaries") or ()
                            if isinstance(b, dict) and b.get("statement")],
             "questions": [str(q.get("text") or q.get("statement")) for q in reading.get("open_questions") or ()
                           if isinstance(q, dict) and (q.get("text") or q.get("statement"))]}
    return {k: v for k, v in items.items() if v}


def approve_plan(context) -> dict:
    """The CHECK-IN 1 view of an analysis plan, with the refusals that keep it from being shown."""
    from ravel.validation import validate_checkin
    plan = context.get("plan") or {}
    found, errors = collect(context)
    chosen, problems = variant(context)
    errors += problems
    numbered, problems = flags(found, context)
    errors += problems
    document = legacy_document(found, context, chosen or "reproduction", numbered)
    for message in validate_checkin.validate(document, base_dir=None):
        errors.append(error("checkin_content", message, row="C03"))
    from ravel.validation import checkin_withheld
    for message in checkin_withheld.checkin_errors(document, context.get("contract"), chosen):
        errors.append(error("checkin_withheld", message, row="C10"))
    grid = scan.approved_grid(plan)
    if scan.point_steps(plan) or grid is not None:
        errors += scan.membership_errors(plan)
    tpl = template("approve_plan")
    sections_ids = list(tpl["variants"].get(chosen or "reproduction") or [])
    if grid is not None:
        sections_ids += tpl["scan"]
    route = _doc(found, "route_analysis.json")
    values = {
        "preamble": route.get("summary"),
        "resource_census": document["sections"].get("i-b"),
        "gallery": [f"{g.get('figure_id') or g.get('id')}: {g.get('caption')}" for g in
                    (_doc(found, "gallery.json").get("figures") or ()) if isinstance(g, dict)],
        "figure_target": ([f"{t.get('figure_id') or t.get('role')}: {t.get('caption_snippet') or t.get('caption')} "
                           f"(axes x={((t.get('axes') or {}).get('x'))}, y={((t.get('axes') or {}).get('y'))})"
                           for t in _doc(found, "figure_target.json").get("targets") or () if isinstance(t, dict)]
                          + _waypoint_lines(_doc(found, "waypoint.json"))),
        "withheld_waypoints": _doc(found, "waypoint.json").get("withheld_waypoints"),
        "method": document["sections"]["iv"]["method"],
        "scan_grid": ([f"{a['name']}: {len(a['values'])} value(s) {a['values'][:8]}" + (f" [{a['unit']}]"
                       if a.get("unit") else "") for a in (grid or {}).get("axes") or ()]
                      + [f"{len((grid or {}).get('points') or ())} point(s); grid digest {(grid or {}).get('sha256')}"]),
    }
    sections = [_section("approve_plan", "preamble", values["preamble"])]
    sections += [_section("approve_plan", name, values.get(name)) for name in sections_ids]
    for row in sections:
        if not row["lines"]:
            errors.append(error("checkin_section_empty", f"CHECK-IN 1 section {row['id']} has no content", row="C03"))
    pins = {"plan_sha256": plan.get("sha256") or ""}
    for name, row in sorted(found.items()):
        pins[f"evidence:{row['step']}:{name}"] = row["pin"]["sha256"]
    if grid is not None:
        pins["scan_grid_sha256"] = grid.get("sha256") or ""
    return {"kind": "approve_plan", "variant": chosen, "sections": sections,
            "required_sections": ["preamble", *sections_ids],
            "flags": [{"kind": r["kind"] if r["kind"] in FLAG_KINDS else "assumption", "text": f"F{r['n']}: {r['text']}"}
                      for r in numbered],
            "items": _items(plan, context.get("reading")), "pins": {k: v for k, v in pins.items() if v},
            "summary": route.get("summary") if isinstance(route.get("summary"), str) else "",
            "bounds": {"rung": evidence.max_rung(plan), "stages": sorted({s.get("operation") for s in plan.get("steps")
                                                                         or () if s.get("operation")})},
            "review_items": deepcopy(tpl["review_items"]), "legacy": document, "errors": errors}


# ---- CHECK-IN 2 -------------------------------------------------------------------------------

def _waypoint_steps(plan):
    return [s for s in (plan or {}).get("steps") or () if s.get("waypoint")]


def go(context) -> dict:
    """The CHECK-IN 2 view: the executed waypoint evidence the GO binds."""
    from ravel.validation import validate_checkin
    plan = context.get("plan") or {}
    errors, pins, rows = [], {}, []
    for step in _waypoint_steps(plan):
        declared = next((o["path"] for o in step.get("outputs") or () if o["path"].endswith(".json")), None)
        if declared is None:
            errors.append(error("waypoint_evidence_undeclared", f"waypoint {step['id']} declares no JSON evidence",
                                row="C10", step=step["id"]))
            continue
        doc, pin, problem = common.read_output(context, step["id"], declared)
        if problem:
            errors.append(error("waypoint_evidence_missing", problem, row="C10", step=step["id"]))
            continue
        pins[f"waypoint_document:{step['id']}"] = pin["sha256"]
        rows.append((step, doc if isinstance(doc, dict) else {}, pin))
    if not rows and not errors:
        errors.append(error("waypoint_missing", "the plan reaches CHECK-IN 2 without an executed waypoint", row="C10"))
    approval = latest_authority(context.get("store"), "approve_plan", plan=plan, held=held_authority(context))
    if approval:
        pins["approve_plan"] = approval
    else:
        errors.append(error("checkin1_record_missing", "CHECK-IN 2 binds the current CHECK-IN 1 authority record",
                            row="C10"))
    document = {"schema_version": 1, "kind": "checkin2", "sections": {
        "waypoint": [doc.get("element") or step["id"] for step, doc, _ in rows] or None,
        "expectation": [doc.get("expectation") for _, doc, _ in rows if doc.get("expectation")] or None,
        "ask": {"options": [{"name": "GO"}, {"name": "ADJUST"}]}}}
    for message in validate_checkin.validate(document, base_dir=None):
        errors.append(error("checkin_content", message, row="C10"))
    if evidence.withheld(context):
        from ravel.validation import checkin_withheld
        for step, doc, _ in rows:
            fields = sorted(set(checkin_withheld._published_fields(doc)))
            if fields:
                errors.append(error("waypoint_withheld_reference", f"waypoint {step['id']} carries published "
                                    "material: " + ", ".join(fields), row="C10", step=step["id"]))
    sections = [
        _section("go", "preamble", [doc.get("summary") for _, doc, _ in rows if doc.get("summary")]),
        _section("go", "waypoint", [f"{step['id']}: {doc.get('element')}" for step, doc, _ in rows]),
        _section("go", "expectation", [f"{step['id']}: expected {doc.get('expectation')}; found "
                                       f"{doc.get('evidence')}" for step, doc, _ in rows]),
        _section("go", "evidence_manifest", [f"{pin['artifact']} sha256 {pin['sha256']}" for _, _, pin in rows]),
    ]
    for row in sections:
        if not row["lines"]:
            errors.append(error("checkin_section_empty", f"CHECK-IN 2 section {row['id']} has no content", row="C10"))
    return {"kind": "go", "sections": sections, "required_sections": ["preamble", "waypoint", "expectation",
                                                                      "evidence_manifest"],
            "flags": [], "items": _items(plan, context.get("reading")), "pins": pins,
            "summary": "", "review_items": deepcopy(template("go")["review_items"]), "legacy": document,
            "errors": errors}


def held_authority(context, kind="approve_plan"):
    """The authority record ids the controller holds for ``kind`` (``state.authority``), as the service reported them."""
    held = (((context or {}).get("state") or {}).get("authority") or {}).get(kind)
    return list(held) if isinstance(held, list) else None


def latest_authority(store, kind, *, plan=None, held=None) -> str | None:
    """Latest grant for this plan; a later refusal never resurrects an earlier grant.

    A changed plan can retain its original CI1 only through a chain of approved deviations
    naming both the preceding plan and the CI1 they amend. The authority service still checks
    revocation, bounds and exact effect pins immediately before launch.

    ``held`` is the controller's record of this kind's authority ids. When its latest names this same record (its
    store id, or the id or uid the authority service reported), the grant is named by that id, the one the
    controller's own check-in pins; otherwise by its store id.
    """
    rows = common.records(store, common.AUTHORITY)
    row = next((r for r in reversed(rows) if r.get("kind") == kind), None)
    if row is None or row.get("decision") not in ("approve", "go") or row.get("authorizes_effects") is not True:
        return None
    if row.get("run_id") != getattr(store, "run_id", None):
        return None
    # The authority reader authenticates canonical RunStore ids. A signed body's
    # uid identifies its issuance, not the store record that a later check-in pins.
    identifier = row.get("_record_id") or row.get("id")
    if not isinstance(identifier, str) or not identifier:
        return None
    pinned = held[-1] if held else None
    if isinstance(pinned, str) and pinned and pinned in (row.get("_record_id"), row.get("id"), row.get("uid")):
        identifier = pinned
    if plan is None:
        return identifier
    target = plan.get("sha256")
    original = ((row.get("subject") or {}).get("pins") or {}).get("plan_sha256")
    if not target or not original:
        return None
    if original == target:
        return identifier
    if kind != "approve_plan":
        return None
    seen = set()
    for _ in range(64):
        if target in seen:
            return None
        seen.add(target)
        renewal = next((r for r in reversed(rows) if r.get("kind") == "deviation"
                        and ((r.get("subject") or {}).get("pins") or {}).get("plan_sha256") == target), None)
        if renewal is None or renewal.get("decision") != "approve" or renewal.get("authorizes_effects") is not True:
            return None
        pins = ((renewal.get("subject") or {}).get("pins") or {})
        if pins.get("approve_plan") not in (identifier, row.get("_record_id")):
            return None
        target = pins.get("previous_plan_sha256")
        if target == original:
            return identifier
        if not isinstance(target, str):
            return None
    return None


# ---- FINAL CHECK-IN ---------------------------------------------------------------------------

class RecipeLedgerUnreadable(ValueError):
    """The run has recipe inputs but its ledger cannot be rebuilt (a pinned input changed or is unreadable)."""


def recipe_rows(run_dir) -> dict | None:
    """The current recipe ledger's CHECK-IN 3 section (unknown and deviated rows), or None without recipe inputs.

    A run with recipe inputs whose ledger cannot be rebuilt raises ``RecipeLedgerUnreadable``: the final
    check-in reports it rather than treating the ledger as absent.
    """
    from ravel.validation.validate_checkin import _sibling_contract
    from ravel.workflow import recipe_ledger
    if run_dir is None:
        return None
    contract = _sibling_contract(run_dir)
    if not recipe_ledger._has_inputs(run_dir, contract):
        return None
    try:
        return recipe_ledger.checkin3_section(run_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RecipeLedgerUnreadable(f"the recipe ledger cannot be rebuilt: {exc}"[:500]) from exc


def recipe_errors(shown, current) -> list:
    """C36: the shown ledger keeps every current unknown and deviated row unchanged."""
    if current is None:
        return []
    errors = []
    shown = shown if isinstance(shown, dict) else {}
    for key in ("unknown", "deviated"):
        want = {json.dumps(r, sort_keys=True) for r in current.get(key) or ()}
        have = {json.dumps(r, sort_keys=True) for r in shown.get(key) or ()}
        lost = want - have
        if lost:
            errors.append(error("recipe_rows_dropped", f"the final check-in drops or alters {len(lost)} {key} recipe "
                                "ledger row(s); every unknown row is kept unchanged", row="C36"))
    return errors


# The stages every analysis plan keeps, by adapter: a plan without one cannot deliver (ROUTE-*).
ROUTE_STAGES = ("environment", "inputs.census", "inputs.route", "inputs.traps", "inputs.figures", "inputs.cost",
                "recast", "waypoint", "acquire", "visualize", "compare", "verify.mechanical", "verify.adversary",
                "synthesize")


def stage_errors(plan) -> list:
    """Route stages missing from the plan, the result stage included (a single point or an assembled scan)."""
    adapters = {common.adapter_of(s) for s in (plan or {}).get("steps") or ()}
    missing = [a for a in ROUTE_STAGES if a not in adapters]
    if not ({"exclude", scan.ASSEMBLE} & adapters):
        missing.append("exclude or scan.assemble")
    if not any(s.get("waypoint") for s in (plan or {}).get("steps") or ()):
        missing.append("the waypoint")
    return [error("route_stage_missing", f"the analysis plan lacks its {name} stage; the route's stages, "
                  "check-ins and reviews are not optional", row=None) for name in missing]


def final(context) -> dict:
    """The FINAL CHECK-IN view: results traced to accepted artifacts, verification, recipe ledger, holes."""
    plan = context.get("plan") or {}
    errors, pins = stage_errors(plan), {}
    approval = latest_authority(context.get("store"), "approve_plan", plan=plan, held=held_authority(context))
    if approval:
        pins["approve_plan"] = approval
    else:
        errors.append(error("checkin1_record_missing", "the final check-in binds the CHECK-IN 1 record", row="C36"))
    results, verification = [], []
    for step in (plan or {}).get("steps") or ():
        adapter = common.adapter_of(step)
        if adapter not in ("exclude", scan.ASSEMBLE, "verify.mechanical", "verify.adversary", "synthesize"):
            continue
        declared = next((o["path"] for o in step.get("outputs") or () if o["path"].endswith(".json")), None)
        doc, pin, problem = common.read_output(context, step["id"], declared) if declared else (None, None, "none")
        if problem:
            errors.append(error("result_evidence_missing", f"{step['id']}: {problem}", row="C36", step=step["id"]))
            continue
        pins[f"result:{step['id']}"] = pin["sha256"]
        target = verification if adapter.startswith("verify") else results
        target.append(f"{step['id']} ({pin['artifact']}, sha256 {pin['sha256'][:12]}): "
                      + (doc.get("headline") or doc.get("verdict") or doc.get("statistic") or "recorded"))
    try:
        current = recipe_rows(context.get("run_dir"))
    except RecipeLedgerUnreadable as exc:
        current = None
        errors.append(error("recipe_ledger_unreadable", str(exc), row="C36"))
    shown = None
    deck = next((s for s in plan.get("steps") or () if common.adapter_of(s) == "synthesize"), None)
    if deck is not None:
        declared = next((o["path"] for o in deck.get("outputs") or () if o["path"].endswith(".json")), None)
        doc, _, _ = common.read_output(context, deck["id"], declared) if declared else (None, None, None)
        shown = (doc or {}).get("recipe_ledger") if isinstance(doc, dict) else None
        errors += recipe_errors(shown, current)
    recipe = ([f"unknown: {r.get('id')} {r.get('layer', '')}".strip() for r in (current or {}).get("unknown") or ()]
              + [f"deviated: {r.get('id')} {r.get('layer', '')}".strip() for r in (current or {}).get("deviated") or ()]
              ) or ["No recipe ledger rows are recorded for this run."]
    tpl = template("final")
    names = list(tpl["route"]) + (tpl["scan"] if scan.approved_grid(plan) else [])
    values = {"preamble": results[:1] or None, "results": results, "verification": verification,
              "recipe_ledger": recipe, "limitations": [l for l in (context.get("labels") or [])] or
              ["Limitations are those the verification panel and the ledger record above."]}
    if scan.approved_grid(plan):
        population = scan.population(plan, context)
        values["scan_population"] = ([f"{len(population['completed'])} of {len(population['expected'])} approved "
                                      "point(s) completed"]
                                     + [f"hole {row['point']}: {row['status']}" + (f" ({row.get('reason')})"
                                                                                   if row.get("reason") else "")
                                        for row in population["rows"] if row["status"] != "completed"])
    sections = [_section("final", "preamble", values["preamble"]), _section("final", "results", values["results"])]
    sections += [_section("final", name, values.get(name)) for name in names]
    for row in sections:
        if not row["lines"]:
            errors.append(error("checkin_section_empty", f"the final check-in section {row['id']} has no content",
                                row="C36"))
    return {"kind": "final", "sections": sections, "required_sections": ["preamble", "results", *names],
            "flags": [], "items": _items(plan, context.get("reading")), "pins": pins, "summary": "",
            "review_items": deepcopy(tpl["review_items"]), "recipe_ledger": current, "errors": errors}


# ---- deviation and R3 questions ----------------------------------------------------------------

def _changed_steps(context):
    """Step ids whose bytes differ between the approved plan and the current one (from the store's plans)."""
    plan = context.get("plan") or {}
    approved = ((context.get("state") or {}).get("plan") or {}).get("approved_sha256")
    old = None
    for row in common.records(context.get("store"), "plan"):
        if row.get("plan_sha256") == approved and row.get("blob") and hasattr(context.get("store"), "get_blob"):
            try:
                old = json.loads(context["store"].get_blob(row["blob"]).decode("utf-8"))
            except (OSError, ValueError, KeyError):
                old = None
    if not isinstance(old, dict):
        return None
    before = {s["id"]: common.digest(s) for s in old.get("steps") or ()}
    after = {s["id"]: common.digest(s) for s in plan.get("steps") or ()}
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def deviation(context) -> dict:
    """The deviation check-in: what changed in the approved analysis plan, and what it touches."""
    plan = context.get("plan") or {}
    changed = _changed_steps(context)
    errors = []
    lines = [f"Plan revision {plan.get('revision', 0)} replaces the approved plan."]
    lines.append("Changed steps: " + (", ".join(changed) if changed else "not determinable from the store"))
    grid = scan.approved_grid(plan)
    if grid is not None:
        lines.append(f"Scan grid {grid.get('sha256')}: {len(grid.get('points') or ())} point(s)")
    sections = [_section_titled("preamble", "In plain language",
                                ["The analysis plan changed after its approval; this needs renewed authority."]),
                _section_titled("change", "What changed", lines)]
    return {"kind": "deviation", "sections": sections, "required_sections": ["preamble", "change"], "flags": [],
            "items": {}, "pins": {"plan_sha256": plan.get("sha256") or ""}, "errors": errors}


def r3_action(context) -> dict:
    """An escalation from an analysis step: which steps asked and why."""
    state = context.get("state") or {}
    pending = {k: v for k, v in (state.get("escalations") or {}).items() if (v or {}).get("status") == "pending"}
    lines = [f"{step}: {row.get('escalation')} — {row.get('reason') or 'no reason given'}"
             for step, row in sorted(pending.items())] or ["An analysis step asked for a decision."]
    return {"kind": "r3_action", "sections": [
        _section_titled("preamble", "In plain language", ["A step of the analysis needs your decision before it "
                                                          "continues; other branches continue meanwhile."]),
        _section_titled("action", "The decision asked for", lines)],
        "required_sections": ["preamble", "action"], "flags": [], "items": {}, "pins": {}, "errors": []}


def _section_titled(name, title, lines):
    return {"id": name, "title": title, "lines": [l for l in _lines(lines) if l.strip()]}


VIEWS = {"approve_plan": approve_plan, "checkin1": approve_plan, "go": go, "checkin2": go, "final": final,
         "checkin3": final, "deviation": deviation, "r3_action": r3_action, "escalation": r3_action}


def view(kind, context) -> dict:
    function = VIEWS.get(kind)
    if function is None:
        return {"kind": kind, "errors": [], "sections": [], "required_sections": []}
    return function(context)
