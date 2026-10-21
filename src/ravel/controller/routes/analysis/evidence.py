"""Step adapters of the analysis route: what each step must leave behind before the plan moves on.

Each adapter checks the adopted outputs of one completed step (``parameters.adapter``) and returns
typed refusals; an empty list means the step's evidence holds. The checks reuse the lifecycle
validators that already define these artifacts (``validate_run_state``, ``trap_sweep``,
``validate_checkin``, the scan orchestrator) on the bytes the governed step adopted, verified by
their custody digests. A worker's own claim that it did a step is never evidence.

Adapters (step document in brackets):

- ``environment`` [01]: the tools every planned operation needs, each with an observed status;
- ``inputs.census`` [02, P6]: the resource census ladder, every rung with a status, an error rung
  never read as absence;
- ``inputs.route`` [02, E04]: the routine, model, final state, energy, detector and statistic, with
  every mismatch to the request stated as a bounded approximation, and the fidelity pin (C26);
- ``inputs.traps`` [02, P3]: twelve trap verdicts, every hit flagged or escalated;
- ``inputs.figures`` [02, P1, E05]: declared figure targets with published axis scales and the
  early-verification waypoint (or the withheld-reference waypoints);
- ``inputs.cost`` [02]: a cost record for the plan's highest rung and population;
- ``exclude`` [07] and ``scan.point`` also owe the statistics record and the uncertainty statement of the
  limit (``statistics.errors``: recomputed, a held outcome refused, every qualification labelled);
- ``recast`` [03, 04, E14, C26], ``visualize`` and ``waypoint`` [05, C10], ``compare`` [P2, P5;
  C28-C30], ``acquire`` [06], ``exclude`` [07], ``scan.point`` and ``scan.assemble`` [08],
  ``verify.mechanical``, ``verify.adversary`` [09, P8] and ``synthesize`` [results deck, C36].
"""
from __future__ import annotations

from . import common, fidelity, scan, statistics
from .common import error, placeholder

TRAPS = tuple(f"T{i}" for i in range(1, 13))
RUNG_ORDER = ("none", "dry", "smoke", "pilot", "full", "scan")
CENSUS_STATUSES = ("OK", "ABSENT", "EMPTY", "ERROR", "SKIPPED", "NOT_RUN", "PARTIAL")


def _outputs(step):
    return [o["path"] for o in step.get("outputs") or () if o.get("required", True)]


def _read(context, step, outcome, path, row=None):
    document, pin, problem = common.read_output(context, step["id"], path, outcome=outcome)
    if problem:
        return None, None, [error("evidence_missing", problem, row=row, step=step["id"])]
    return document, pin, []


def _first_json(context, step, outcome, row=None):
    """The step's first required JSON output (its primary evidence record)."""
    paths = [p for p in _outputs(step) if p.endswith(".json")]
    if not paths:
        return None, None, [error("evidence_undeclared", f"step {step['id']} declares no JSON evidence output",
                                  row=row, step=step["id"])]
    return _read(context, step, outcome, paths[0], row=row)


def _plan_operations(plan):
    return sorted({s.get("operation") for s in (plan or {}).get("steps") or () if s.get("operation")})


def max_rung(plan) -> str:
    rungs = [s.get("rung") for s in (plan or {}).get("steps") or () if s.get("rung") in RUNG_ORDER]
    return max(rungs, key=RUNG_ORDER.index) if rungs else "none"


# ---- 01 environment ---------------------------------------------------------------------------

def environment(step, outcome, context):
    doc, _, errors = _first_json(context, step, outcome, row="STEP-01-environment")
    if errors:
        return errors
    tools = doc.get("tools") if isinstance(doc, dict) else None
    if not isinstance(tools, list) or not tools:
        return [error("environment_tools_missing", "the environment record lists no tools with an observed status",
                      row="STEP-01-environment", step=step["id"])]
    out = []
    for row in tools:
        if not isinstance(row, dict) or placeholder(row.get("name")) or row.get("status") not in (
                "available", "missing", "unknown"):
            out.append(error("environment_tool_invalid", "every tool row names the tool and an observed status "
                             "(available, missing or unknown)", row="STEP-01-environment", step=step["id"]))
            break
    covered = {str(op) for op in doc.get("operations") or () if isinstance(op, str)}
    missing_ops = [op for op in _plan_operations(context.get("plan")) if op not in covered]
    if missing_ops:
        out.append(error("environment_operations_uncovered", "the environment record does not account for planned "
                         "operations: " + ", ".join(missing_ops), row="STEP-01-environment", step=step["id"]))
    absent = [r.get("name") for r in tools if isinstance(r, dict) and r.get("status") == "missing"
              and r.get("required", True)]
    if absent:
        out.append(error("environment_tool_absent", "required tools are missing on this host: " + ", ".join(
            map(str, absent)), row="STEP-01-environment", step=step["id"],
            fix="install or provision the tools, or plan an admitted alternative before CHECK-IN 1"))
    return out


# ---- 02 inputs --------------------------------------------------------------------------------

def census(step, outcome, context):
    """The resource census ladder (P6): rungs with statuses; an unreachable source is not absence."""
    path = next((p for p in _outputs(step) if p.endswith("resource_census.json")), None)
    if path is None:
        return [error("evidence_undeclared", "the census step declares no resource_census.json output",
                      row="E04", step=step["id"])]
    doc, pin, errors = _read(context, step, outcome, path, row="E04")
    if errors:
        return errors
    from ravel.validation import validate_run_state
    status, _, checks = validate_run_state.check_resource_census(
        str(context["run_dir"]), context.get("contract") or {}, {"resource_census_path": pin["path"]}, "R", False)
    out = []
    if status == "FAIL":
        out.append(error("census_invalid", "; ".join(c["msg"] for c in checks if c["level"] == "FAIL"),
                         row="E04", step=step["id"]))
    records = doc.get("records") if isinstance(doc, dict) else None
    records = list(records) if isinstance(records, list) else [doc]
    if isinstance(doc, dict) and isinstance(doc.get("records"), list) and isinstance(doc.get("rungs"), dict):
        records.append(doc)  # the census's own rungs are checked like a record's
    rows = []
    for record in records:
        rungs = (record or {}).get("rungs") if isinstance(record, dict) else None
        if isinstance(rungs, dict):
            rows.extend((name, rung) for name, rung in rungs.items())
    for name, rung in rows:
        state = rung.get("status") if isinstance(rung, dict) else None
        if not isinstance(state, str) or not state:
            out.append(error("census_rung_unstated", f"census rung {name} records no status", row="E04",
                             step=step["id"]))
        elif state.upper().startswith("ERROR") and isinstance(rung, dict) and rung.get("absent") is True:
            out.append(error("census_error_as_absence", f"census rung {name} is unreachable but recorded as absent; "
                             "an outage is not evidence of absence", row="E04", step=step["id"]))
    return out


def route_analysis(step, outcome, context):
    """The resolved routine, model and statistics match the request or state a bounded approximation (E04)."""
    doc, _, errors = _first_json(context, step, outcome, row="E04")
    if errors:
        return errors
    if not isinstance(doc, dict):
        return [error("route_analysis_invalid", "the route analysis is not an object", row="E04", step=step["id"])]
    out = []
    route_fields = ("routine", "model", "final_state", "energy", "detector_mode", "stat_mode")
    for key in route_fields:
        if placeholder(doc.get(key)):
            out.append(error("route_analysis_incomplete", f"the route analysis leaves {key} unstated", row="E04",
                             step=step["id"]))
    from ravel.validation.validate_task_contract import DETECTOR_MODES, STAT_MODES
    if doc.get("detector_mode") not in DETECTOR_MODES:
        out.append(error("route_analysis_detector", f"detector_mode {doc.get('detector_mode')!r} is not a contract "
                         "detector mode", row="E04", step=step["id"]))
    if doc.get("stat_mode") not in STAT_MODES:
        out.append(error("route_analysis_statistic", f"stat_mode {doc.get('stat_mode')!r} is not a contract "
                         "statistics mode", row="E04", step=step["id"]))
    for key in ("detector_mode", "stat_mode"):
        if doc.get(key) == "TBD-judgment" and not any(key in str(e) for e in doc.get("escalate") or ()):
            out.append(error("route_analysis_undecided", f"{key} is left to judgment without an escalation naming it",
                             row="E04", step=step["id"]))
    out += request_match_errors(doc, context)
    mismatches = doc.get("mismatches") or []
    approximation_rows = doc.get("approximations") or []
    approximations = {a.get("id") for a in approximation_rows if isinstance(a, dict)
                      and isinstance(a.get("id"), str) and not placeholder(a["id"])
                      and not placeholder(a.get("bound")) and not placeholder(a.get("reason"))}
    for row in mismatches if isinstance(mismatches, list) else []:
        if not isinstance(row, dict) or row.get("approximation") not in approximations:
            out.append(error("route_analysis_unbounded_mismatch", "a mismatch between the requested analysis and the "
                             "selected routine, final state, energy or model basis is not bound to a stated "
                             "approximation", row="E04", step=step["id"]))
    for row in doc.get("approximations") or ():
        if not isinstance(row, dict) or placeholder(row.get("bound")) or placeholder(row.get("reason")):
            out.append(error("route_analysis_approximation_unbounded", "every approximation states its reason and "
                             "its bound", row="E04", step=step["id"]))
    # Compare the admitted structured reading, independently of producer-declared mismatches.
    # The exact span authenticates the constraint; no natural-language extraction happens here.
    from ravel.validation.intake_records import span_errors
    for constraint in (context.get("reading") or {}).get("constraints") or ():
        if not isinstance(constraint, dict) or constraint.get("type") != "keep_fixed":
            continue
        value = constraint.get("value") or {}
        if not isinstance(value, dict):
            continue
        fields = [key for key in route_fields if key in value]
        if not fields:
            continue
        prompt = (context.get("contract") or {}).get("prompt")
        if not isinstance(prompt, str) or not constraint.get("evidence") or span_errors(constraint, prompt, "keep_fixed"):
            out.append(error("route_analysis_constraint_unbound", "a structured keep_fixed constraint has no exact "
                             "request span", row="E04", step=step["id"]))
            continue
        for key in fields:
            if not placeholder(value[key]) and value[key] == doc.get(key):
                continue
            covered = any(isinstance(m, dict) and isinstance(constraint.get("id"), str)
                          and m.get("constraint") == constraint["id"] and m.get("field") == key
                          and m.get("requested") == value[key] and m.get("selected") == doc.get(key)
                          and m.get("approximation") in approximations
                          for m in mismatches if isinstance(mismatches, list))
            if not covered:
                out.append(error("route_analysis_constraint_mismatch", f"the selected {key} conflicts with "
                                 f"keep_fixed constraint {constraint.get('id')!r} without a bounded approximation "
                                 "covering that constraint, field and pair of values", row="E04", step=step["id"]))
    out += fidelity.result_errors(context.get("reading"), context.get("contract"),
                                  {"route analysis": doc.get("detector_mode")})
    return out


def traps(step, outcome, context):
    """The physics trap sweep (P3): twelve verdicts; every hit carries a flag number or an escalation."""
    path = next((p for p in _outputs(step) if p.endswith("trap_sweep.json")), None)
    if path is None:
        return [error("evidence_undeclared", "the trap step declares no trap_sweep.json output", row="E04",
                      step=step["id"])]
    doc, pin, errors = _read(context, step, outcome, path, row="E04")
    if errors:
        return errors
    from ravel.workflow import trap_sweep
    report = trap_sweep.validate(context["run_dir"], relative=pin["path"])
    if report["status"] != "PASS":
        return [error("trap_sweep_invalid", "; ".join(c["msg"] for c in report["checks"] if c["level"] == "FAIL")
                      or "the trap sweep does not pass", row="E04", step=step["id"])]
    return []


def withheld(context) -> bool:
    """True when the pinned contract restricts the comparison reference (the reference-withheld variant).

    A restriction census that cannot be read counts as restricting: published material is never shown
    on a guess (the check-in reports the invalid census separately).
    """
    from ravel.validation import checkin_withheld
    contract = context.get("contract")
    if not isinstance(contract, dict):
        return False
    try:
        return bool(checkin_withheld._restricted(contract, {}, None))
    except (ValueError, TypeError, KeyError):
        return True


def figures(step, outcome, context):
    """Figure targets (P1, E05) from the allowed reference with published axis scales, and the waypoint.

    The step writes ``figure_target.json`` (the figure contract) and ``waypoint.json`` (the proposed
    early-verification waypoint, or, when the reference is withheld, ``withheld_waypoints`` that need
    no published material).
    """
    from ravel.validation import checkin_withheld
    out = []
    restricted = withheld(context)
    path = next((p for p in _outputs(step) if p.endswith("figure_target.json")), None)
    targets = []
    if path is None and not restricted:
        return [error("evidence_undeclared", "the figure step declares no figure_target.json output", row="E05",
                      step=step["id"])]
    if path is not None:
        doc, _, errors = _read(context, step, outcome, path, row="E05")
        if errors:
            return errors
        targets = doc.get("targets") if isinstance(doc, dict) else None
        if restricted and targets:
            out.append(error("figure_target_withheld", "the comparison reference is withheld; a published figure "
                             "target cannot be declared", row="C10", step=step["id"]))
        elif not restricted and not targets:
            return [error("figure_targets_missing", "no figure target is declared", row="E05", step=step["id"])]
    for target in targets or ():
        name = target.get("figure_id") or target.get("role") or "target"
        axes = target.get("axes") if isinstance(target.get("axes"), dict) else {}
        if axes.get("x") not in ("linear", "log") or axes.get("y") not in ("linear", "log"):
            out.append(error("figure_axes_unrecorded", f"{name}: the published axis scales are not recorded",
                             row="E05", step=step["id"]))
        if placeholder(target.get("source")):
            out.append(error("figure_source_missing", f"{name}: the target names no source evidence", row="E05",
                             step=step["id"]))
    requested = [d for d in (context.get("reading") or {}).get("deliverables") or ()
                 if isinstance(d, dict) and (d.get("artifact") or {}).get("kind") == "figure"]
    if requested and targets and len(targets) < len(requested):
        out.append(error("figure_panels_dropped", f"{len(requested)} figure deliverable(s) requested, "
                         f"{len(targets)} target(s) declared", row="E05", step=step["id"]))
    proposal = next((p for p in _outputs(step) if p.endswith("waypoint.json")), None)
    if proposal is None:
        return out + [error("waypoint_missing", "the figure step declares no waypoint.json output", row="E05",
                            step=step["id"])]
    doc, _, errors = _read(context, step, outcome, proposal, row="E05")
    if errors:
        return out + errors
    doc = doc if isinstance(doc, dict) else {}
    if restricted:
        rows = doc.get("withheld_waypoints")
        if not isinstance(rows, list) or not rows or not all(checkin_withheld._waypoint(r) for r in rows):
            out.append(error("withheld_waypoints_invalid", "a reference-withheld plan needs checkable waypoints of "
                             "the declared kinds", row="C10", step=step["id"]))
        fields = sorted(set(checkin_withheld._published_fields(doc)))
        if fields:
            out.append(error("waypoint_withheld_reference", "the waypoint carries published material: "
                             + ", ".join(fields), row="C10", step=step["id"]))
    elif any(placeholder(doc.get(k)) for k in ("element", "expectation", "why_cheap")):
        out.append(error("waypoint_incomplete", "the early-verification waypoint states no element, expectation or "
                         "reason it is cheap", row="E05", step=step["id"]))
    return out


def cost(step, outcome, context):
    """A cost record for the plan's highest rung and its population; unknown stays unknown."""
    doc, _, errors = _first_json(context, step, outcome, row="A06")
    if errors:
        return errors
    if not isinstance(doc, dict):
        return [error("cost_invalid", "the cost record is not an object", row="A06", step=step["id"])]
    out = []
    plan = context.get("plan")
    wanted = max_rung(plan)
    if wanted == "pilot":
        wanted = "smoke"
    if doc.get("mode") != wanted:
        out.append(error("cost_rung_mismatch", f"the cost record is for {doc.get('mode')}; the plan reaches {wanted}",
                         row="A06", step=step["id"]))
    grid = scan.approved_grid(plan)
    if wanted == "scan" and grid and doc.get("points") != len(grid.get("points") or ()):
        out.append(error("cost_population_mismatch", f"the cost record covers {doc.get('points')} point(s); the "
                         f"grid has {len(grid.get('points') or ())}", row="A06", step=step["id"]))
    if placeholder(doc.get("status")) or placeholder(doc.get("basis")):
        out.append(error("cost_basis_missing", "the cost record states no calibration status or basis", row="A06",
                         step=step["id"]))
    return out


# ---- 03-07 ------------------------------------------------------------------------------------

def recast(step, outcome, context):
    """Generation through the preserved routine (03, 04): a produced sample, a passing pre-shower check,
    a bound current routine qualification (E14) and the planned detector fidelity (C26)."""
    doc, _, errors = _first_json(context, step, outcome, row="STEP-03-generate")
    if errors:
        return errors
    if not isinstance(doc, dict):
        return [error("generation_record_invalid", "the recast record is not an object", row="STEP-03-generate",
                      step=step["id"])]
    out = []
    if placeholder(doc.get("events")) and placeholder(doc.get("samples")):
        out.append(error("generation_record_empty", "the recast record names no produced sample",
                         row="STEP-03-generate", step=step["id"]))
    check = doc.get("lhe_check")
    if isinstance(check, dict) and check.get("status") not in (None, "PASS"):
        out.append(error("generation_lhe_check", f"the pre-shower check is {check.get('status')}",
                         row="STEP-03-generate", step=step["id"]))
    report = doc.get("qualification")
    if not isinstance(report, dict) or placeholder(report.get("status")) or placeholder(report.get("routine")):
        out.append(error("qualification_unbound", "the recast binds no current routine qualification report; an "
                         "installed routine is not qualified by its presence", row="E14", step=step["id"]))
    elif report.get("status") not in ("qualified", "qualified-with-limits"):
        out.append(error("qualification_failed", f"the routine qualification is {report.get('status')}", row="E14",
                         step=step["id"]))
    out += fidelity.result_errors(context.get("reading"), context.get("contract"),
                                  {f"{step['id']} recast": doc.get("detector_mode")})
    return out


def visualize(step, outcome, context):
    doc, _, errors = _first_json(context, step, outcome, row="STEP-05-visualize")
    if errors:
        return errors
    figures = (doc or {}).get("figures") if isinstance(doc, dict) else None
    if not isinstance(figures, list) or not figures:
        return [error("figures_missing", "the figure index lists no figure", row="STEP-05-visualize",
                      step=step["id"])]
    lint = [f.get("id") or f.get("path") for f in figures if isinstance(f, dict) and f.get("lint") not in (None, "PASS")]
    if lint:
        return [error("figures_lint", "figures fail the plot lint: " + ", ".join(map(str, lint)),
                      row="STEP-05-visualize", step=step["id"])]
    return []


def waypoint(step, outcome, context):
    """CHECK-IN 2 evidence (C10): a bound evidence manifest; withheld runs carry no published reference."""
    doc, _, errors = _first_json(context, step, outcome, row="C10")
    if errors:
        return errors
    out = []
    if not isinstance(doc, dict) or placeholder(doc.get("expectation")) or placeholder(doc.get("evidence")):
        out.append(error("waypoint_evidence_incomplete", "the waypoint record states no expectation or evidence",
                         row="C10", step=step["id"]))
    from ravel.validation import checkin_withheld
    if withheld(context):
        fields = sorted(set(checkin_withheld._published_fields(doc or {})))
        if fields:
            out.append(error("waypoint_withheld_reference", "a reference-withheld waypoint carries published "
                             "material: " + ", ".join(fields), row="C10", step=step["id"]))
    return out


def acquire(step, outcome, context):
    doc, _, errors = _first_json(context, step, outcome, row="STEP-06-acquire-data")
    if errors:
        return errors
    if isinstance(doc, dict) and doc.get("status") == "not_applicable":
        return _acquisition_not_applicable(step, doc, context)
    if not isinstance(doc, dict) or placeholder(doc.get("tables")) and placeholder(doc.get("likelihood")):
        return [error("acquisition_empty", "the acquisition record names no table or likelihood",
                      row="STEP-06-acquire-data", step=step["id"])]
    return []


def _acquisition_not_applicable(step, doc, context):
    """A typed not-applicable acquisition holds only with its evidence: the run's census found no analysis to
    sweep and the route analysis names no published record."""
    census_path = next((r["artifact"].split(":", 1)[1] for r in step.get("inputs") or ()
                        if str(r.get("artifact", "")).endswith(":outputs/inputs/resource_census.json")), None)
    census, pin, problem = common.read_output(context, "inputs.census", census_path) if census_path else (
        None, None, "the acquisition declares no census input")
    rung = ((census or {}).get("rungs") or {}).get("reading/targets") or {} if isinstance(census, dict) else {}
    route = None
    route_step = next((r["artifact"] for r in step.get("inputs") or ()
                       if str(r.get("artifact", "")).endswith(":outputs/route_analysis.json")), None)
    if route_step:
        route, _, _ = common.read_output(context, route_step.split(":", 1)[0], route_step.split(":", 1)[1])
    evidence_ = doc.get("evidence") if isinstance(doc.get("evidence"), dict) else {}
    if (problem or not isinstance(census, dict) or census.get("records") != [] or rung.get("status") != "ABSENT"
            or not isinstance(route, dict) or "hepdata_record" not in route or route["hepdata_record"] is not None
            or evidence_.get("census_sha256") != (pin or {}).get("sha256") or placeholder(doc.get("reason"))):
        return [error("acquisition_not_applicable_unsupported", "a not-applicable acquisition needs the run's census "
                      "to have found no analysis and the route analysis to name no published record",
                      row="STEP-06-acquire-data", step=step["id"])]
    return []


def requested_statistic(reading) -> str | None:
    for row in (reading or {}).get("constraints") or ():
        if isinstance(row, dict) and row.get("type") == "prescribed_statistic":
            return (row.get("value") or {}).get("statistic")
    return None


def exclusion_requested(reading) -> bool:
    return any(isinstance(d, dict) and d.get("claim_kind") == "exclusion" for d in (reading or {}).get("deliverables") or ())


def exclude(step, outcome, context):
    """The requested quantity is the primary result: a prescribed statistic as written, else 95% CLs for an
    exclusion; limits carry their typed numerical status."""
    doc, _, errors = _first_json(context, step, outcome, row="STEP-07-exclude")
    if errors:
        return errors
    if not isinstance(doc, dict):
        return [error("statistics_invalid", "the statistics record is not an object", row="STEP-07-exclude",
                      step=step["id"])]
    out = []
    reading = context.get("reading")
    prescribed = requested_statistic(reading)
    primary = doc.get("statistic")
    if prescribed is not None and primary != prescribed:
        out.append(error("statistic_substituted", f"the request prescribes {prescribed}; the primary result is "
                         f"{primary}", row="STEP-07-exclude", step=step["id"]))
    if prescribed is None and exclusion_requested(reading):
        level = doc.get("confidence_level", 0.95)
        if not isinstance(primary, str) or primary.lower() != "cls" or level != 0.95:
            out.append(error("statistic_default", "an exclusion request without a prescribed statistic delivers "
                             f"95% CLs; the primary result is {primary} at {level}", row="STEP-07-exclude",
                             step=step["id"]))
    if "limits" in doc or exclusion_requested(reading):
        try:
            from ravel.limits import read_limits
            read_limits(doc)
        except (ValueError, TypeError, KeyError) as exc:
            out.append(error("limits_unreadable", f"the limits carry no typed numerical status: {exc}"[:500],
                             row="STEP-07-exclude", step=step["id"]))
    out += fidelity.result_errors(reading, context.get("contract"), {f"{step['id']} result": doc.get("detector_mode")})
    out += statistics.errors(doc, step)
    return out


# ---- 08 scan ----------------------------------------------------------------------------------

def scan_point(step, outcome, context):
    """One approved point: membership in the grid, its own result for its own tag, the requested statistic."""
    errors = scan.point_errors(step, outcome, context.get("plan"))
    if errors:
        return errors
    doc, _, problems = _first_json(context, step, outcome, row="P04")
    if problems:
        return problems
    doc = doc if isinstance(doc, dict) else {}
    point_id, coordinates = scan.point_of(step)
    out = []
    if doc.get("tag") != point_id:
        out.append(error("scan_point_result_foreign", f"the result of {step['id']} names point {doc.get('tag')!r}, "
                         f"not {point_id}", row="G12", step=step["id"]))
    if isinstance(doc.get("parameters"), dict) and doc["parameters"] != coordinates:
        out.append(error("scan_point_coordinates", f"the result of {step['id']} carries other coordinates",
                         row="G12", step=step["id"]))
    out += [{**e, "row": e.get("row") if e.get("row") != "STEP-07-exclude" else "P04"}
            for e in exclude(step, outcome, context)]
    return out


def scan_assemble(step, outcome, context):
    doc, _, errors = _first_json(context, step, outcome, row="SW33")
    if errors:
        return errors
    return scan.assembled_errors(doc, context.get("plan"), context, step_id=step["id"])


# ---- 09 verify --------------------------------------------------------------------------------

def verify_mechanical(step, outcome, context):
    """Tier A: every number traced; a failing trace is a finding, never silently fixed."""
    doc, _, errors = _first_json(context, step, outcome, row="STEP-09-verify")
    if errors:
        return errors
    if not isinstance(doc, dict) or doc.get("verdict") not in ("PASS", "FAIL"):
        return [error("tier_a_unrecorded", "the mechanical verification records no PASS or FAIL verdict",
                      row="STEP-09-verify", step=step["id"])]
    if doc["verdict"] == "FAIL":
        return [error("tier_a_failed", "mechanical verification failed; retain its findings and repair or qualify "
                      "the result before delivery", row="STEP-09-verify", step=step["id"])]
    untraced = [n for n in doc.get("numbers") or () if not isinstance(n, dict)
                or common.trace_problem(context, n.get("artifact"))]
    if untraced:
        return [error("tier_a_untraced", f"{len(untraced)} reported number(s) trace to no accepted artifact",
                      row="STEP-09-verify", step=step["id"])]
    return []


def verify_adversary(step, outcome, context):
    """Tier B and P8: three written attacks (basis, acceptance, statistics), each with how it was tested."""
    doc, _, errors = _first_json(context, step, outcome, row="STEP-09-verify")
    if errors:
        return errors
    attacks = (doc or {}).get("attacks") if isinstance(doc, dict) else None
    kinds = {a.get("kind") for a in attacks or () if isinstance(a, dict)
             and not placeholder(a.get("attack")) and not placeholder(a.get("tested_by"))}
    missing = [k for k in ("basis", "acceptance", "statistics") if k not in kinds]
    if missing:
        return [error("attacks_missing", "the adversary record lacks tested attacks on: " + ", ".join(missing),
                      row="STEP-09-verify", step=step["id"])]
    return []


# ---- comparison and the results deck ------------------------------------------------------------

def compare(step, outcome, context):
    """One pinned comparator with matching quantity, basis and unit (C28); residual diagnosis from registered
    output and distinct replicas (C29); attribution only above an approved noise model (C30). A withheld
    reference defers the comparison until the result is sealed."""
    doc, _, errors = _first_json(context, step, outcome, row="C28")
    if errors:
        return errors
    doc = doc if isinstance(doc, dict) else {}
    from ravel.validation import checkin_withheld
    if withheld(context):
        fields = sorted(set(checkin_withheld._published_fields(doc)))
        if doc.get("deferred_until_sealed") is not True or fields:
            return [error("comparison_before_sealing", "the reference is withheld: the comparison is deferred until "
                          "the result is sealed and carries no published material" + (f" ({', '.join(fields)})"
                                                                                    if fields else ""),
                          row="C28", step=step["id"])]
        return []
    out = []
    comparator = doc.get("comparator")
    if not isinstance(comparator, dict) or placeholder(comparator.get("source")) or isinstance(
            doc.get("comparators"), list) and len(doc["comparators"]) > 1:
        out.append(error("comparator_unpinned", "an agreement claim names exactly one pinned comparator", row="C28",
                         step=step["id"]))
    manifests = doc.get("basis_manifests")
    if not isinstance(manifests, list) or len(manifests) != 2 or not all(isinstance(m, dict) for m in manifests):
        out.append(error("basis_manifest_missing", "the comparison carries the two basis manifests (P2)", row="C28",
                         step=step["id"]))
    else:
        for key in ("quantity", "basis", "unit"):
            if any(placeholder(m.get(key)) for m in manifests) or manifests[0].get(key) != manifests[1].get(key):
                out.append(error("basis_mismatch", f"the compared quantities differ in {key}: "
                                 f"{manifests[0].get(key)!r} against {manifests[1].get(key)!r}", row="C28",
                                 step=step["id"]))
    if placeholder(doc.get("tolerance")) or placeholder(doc.get("lattice")):
        out.append(error("tolerance_unapproved", "the comparison states no approved lattice and tolerance",
                         row="C28", step=step["id"]))
    for item in doc.get("attributions") or ():
        if not isinstance(item, dict):
            continue
        replicas = item.get("replicas") or []
        if item.get("model_output") is not None and not str(item.get("model_output")).startswith("artifact:"):
            out.append(error("residual_model_unregistered", "a residual diagnosis uses model output that is not a "
                             "registered artifact", row="C29", step=step["id"]))
        elif common.trace_problem(context, item.get("model_output")):
            out.append(error("residual_model_unregistered", "the residual model output has no current accepted "
                             "custody bytes", row="C29", step=step["id"]))
        replica_ids = [str(r).removeprefix("artifact:") for r in replicas]
        if replicas and len(set(replica_ids)) != len(replicas):
            out.append(error("replicas_not_distinct", "residual replicas repeat", row="C29", step=step["id"]))
        if not replicas or any(common.trace_problem(context, r) for r in replicas):
            out.append(error("replicas_unregistered", "residual replicas must name distinct producer-adopted "
                             "artifacts; seed labels alone carry no custody", row="C29", step=step["id"]))
        if placeholder(item.get("noise_model")) or item.get("above_noise") is not True:
            out.append(error("attribution_below_noise", f"cause {item.get('cause')!r} is attributed without an "
                             "approved noise model and above-noise evidence", row="C30", step=step["id"]))
    return out


def synthesize(step, outcome, context):
    """The results deck: numbers traced to accepted artifacts; the recipe ledger kept with every unknown row."""
    doc, _, errors = _first_json(context, step, outcome, row="STEP-09-verify")
    if errors:
        return errors
    doc = doc if isinstance(doc, dict) else {}
    out = []
    if placeholder(doc.get("headline")):
        out.append(error("results_headline_missing", "the results deck states no headline", row="STEP-09-verify",
                         step=step["id"]))
    untraced = [n for n in doc.get("numbers") or () if not isinstance(n, dict)
                or common.trace_problem(context, n.get("artifact"))]
    if untraced:
        out.append(error("results_untraced", f"{len(untraced)} number(s) in the deck trace to no accepted artifact",
                         row="STEP-09-verify", step=step["id"]))
    from . import checkins
    try:
        current = checkins.recipe_rows(context.get("run_dir"))
    except checkins.RecipeLedgerUnreadable as exc:
        return out + [error("recipe_ledger_unreadable", str(exc), row="C36", step=step["id"])]
    out += [{**e, "step": step["id"]} for e in checkins.recipe_errors(doc.get("recipe_ledger"), current)]
    return out


ADAPTERS = {
    "environment": environment,
    "inputs.census": census,
    "inputs.route": route_analysis,
    "inputs.traps": traps,
    "inputs.figures": figures,
    "inputs.cost": cost,
    "recast": recast,
    "visualize": visualize,
    "waypoint": waypoint,
    "acquire": acquire,
    "exclude": exclude,
    scan.POINT: scan_point,
    scan.ASSEMBLE: scan_assemble,
    "verify.mechanical": verify_mechanical,
    "verify.adversary": verify_adversary,
    "compare": compare,
    "synthesize": synthesize,
}


def check(step, outcome, context) -> list:
    """The named adapter's refusals for a completed step; a step without an adapter has none here."""
    name = common.adapter_of(step)
    if name is None:
        return []
    function = ADAPTERS.get(name)
    if function is None:
        return [error("adapter_unknown", f"step {step.get('id')} names unknown analysis adapter {name}",
                      step=step.get("id"))]
    try:
        return function(step, outcome, context)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return [error("adapter_failed", f"{name} could not check step {step.get('id')}: {type(exc).__name__}: {exc}",
                      step=step.get("id"))]


def request_match_errors(document, context):
    """Routine selection cannot contradict explicit retained request constraints."""
    out = []
    reading = context.get("reading") or {}
    requested_states = [(row.get("value") or {}).get("final_state")
                        for row in reading.get("constraints") or ()
                        if type(row) is dict and row.get("type") == "final_state"
                        and type(row.get("value")) is dict]
    if any(value and value != document.get("final_state") for value in requested_states):
        out.append(error("route_final_state_mismatch", "selected routine final state differs from the pinned request",
                         row="E04"))
    requested_routines = [(row.get("value") or {}).get("routine")
                          for row in reading.get("constraints") or ()
                          if type(row) is dict and row.get("type") == "routine"
                          and type(row.get("value")) is dict]
    pins = (context.get("plan") or {}).get("request_pins") or {}
    requested_routines += [pins["routine"]] if pins.get("routine") else []
    if pins.get("final_state") and pins["final_state"] != document.get("final_state"):
        out.append(error("route_final_state_mismatch", "selected final state differs from the retained request pin",
                         row="E04"))
    selected = document.get("routine")
    selected = selected.get("id") if isinstance(selected, dict) else selected
    for requested in requested_routines:
        requested = requested.get("id") if isinstance(requested, dict) else requested
        if requested and requested != selected:
            out.append(error("route_routine_mismatch", "selected routine differs from the pinned request", row="E04"))
            break
    return out


def main(argv=None):
    """Narrow file frontend for the registered scan-aggregation executor.

    P04/P05 own authority, input staging and process confinement. This command
    only adapts the verified manifest file to the existing assembly API; it does
    not launch points or grant access to any additional run directory.
    """
    import argparse
    from pathlib import Path
    from types import SimpleNamespace
    from ravel.workflow import scan_orchestrator
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    assemble = sub.add_parser("assemble")
    assemble.add_argument("--manifest", required=True, type=Path)
    assemble.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.manifest.name != "scan_manifest.json" or args.manifest.is_symlink() or not args.manifest.is_file():
        parser.error("assembly needs its verified scan_manifest.json")
    if args.out.is_absolute() or ".." in args.out.parts:
        parser.error("assembly writes a declared path inside its attempt outputs")
    result = scan_orchestrator.cmd_assemble(SimpleNamespace(scandir=str(args.manifest.resolve().parent),
                                                          out=str(args.out), normalization_contract=None))
    return 0 if result is None else result


if __name__ == "__main__":
    raise SystemExit(main())
