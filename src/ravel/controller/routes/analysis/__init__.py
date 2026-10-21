"""The analysis-family route adapter (P09): reproduce, reinterpret and scan on the controller.

The routes are data (``src/ravel/data/controller/routes/analysis.json``, ``route-spec.v1``): a
prepare phase (01 environment; 02 resource sweep, route analysis, trap sweep, figure target and
cost) that runs before CHECK-IN 1 and supplies its evidence, a smoke rung that ends at the
early-verification waypoint and CHECK-IN 2, the full rung or one governed step per approved scan
point, data acquisition, statistics, figures, the reference comparison, the verification panel
and the results deck. The controller graph runs every step through ``controller.step``; this
module is what only the analysis route knows. The controller calls it at fixed points
(``context`` = ``{"store", "run_dir", "plan", "state", "reading", "contract", "supplied"}``):

- ``parameters(spec, reading, contract, supplied)`` at compile: the computed parameters the route
  needs (the scan grid and its points, the requested fidelity, the published record to fetch);
- ``bind(plan, context)`` after the prepare phase: the plan with the route analysis's decisions
  bound into its execution steps (revision + 1), or None when nothing changes;
- ``admit(step, context)`` before a dispatch: refusals of generation before the 02 evidence and
  CHECK-IN 1 (R07) and of a full or scan rung before the CHECK-IN 2 GO (A08);
- ``checkin(kind, context)`` at an authority point: the route sections, flags, items, pins and
  bounds of the typed check-in, and the errors that keep it from being shown;
- ``gate(transition, context)`` at a gate node: the route's refusals for the transition;
- ``step(step, outcome, context)`` when a step's outcome is joined: its evidence refusals;
- ``ending(reason, context)`` before a qualified ending: every approved scan point that did not
  complete is recorded as an explicit hole with its status and reason.

Each call records the P09 obligations it discharges in the run's ledger, with evidence.
"""
from __future__ import annotations

from copy import deepcopy
import inspect
import re

from . import checkins, common, discharge, evidence, execution, fidelity, grid, guard, scan, statistics

ROUTES = ("analysis", "analysis.scan")
# The ROUTE rows' discharging nodes of the task modes these routes serve (coverage.csv ROUTE-*).
ROUTE_NODES = ("route.reproduce", "route.reinterpret", "route.scan")
FAMILY = "analysis"
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
UNDECIDED = ("TBD-judgment",)

__all__ = ["ROUTES", "admit", "bind", "checkin", "ending", "final_attempt", "gate", "parameters", "step",
           "unbound_errors", "materialize_launch"]


def _owns(plan) -> bool:
    return ((plan or {}).get("route") or {}).get("id") in ROUTES


def _scan_spec(spec) -> bool:
    return any(isinstance(s, dict) and s.get("foreach") == "grid_points" for s in (spec or {}).get("steps") or ())


def _identifier(reading, scheme):
    found = [((f.get("value") or {}).get("id")) for f in (reading or {}).get("facts") or ()
             if isinstance(f, dict) and f.get("type") == "identifier" and (f.get("value") or {}).get("scheme") == scheme]
    found = [x for x in dict.fromkeys(found) if isinstance(x, str)]
    return found[0] if len(found) == 1 else None


def _decided(route_analysis) -> dict:
    """The execution values a route analysis decided (only stated, decided values)."""
    doc = route_analysis if isinstance(route_analysis, dict) else {}
    values = {}
    routine = doc.get("routine")
    if isinstance(routine, dict):
        routine = routine.get("id")
    if isinstance(routine, str) and routine.strip():
        values["routine"] = routine.strip()
    for key in ("detector_mode", "stat_mode"):
        if isinstance(doc.get(key), str) and doc[key] not in UNDECIDED:
            values[key] = doc[key]
    record = doc.get("hepdata_record")
    if isinstance(record, (str, int)) and str(record).strip():
        values["hepdata_record"] = str(record).strip()
    return values


def parameters(spec, reading, contract, supplied=(), *, route_analysis=None) -> dict:
    """Computed compile-time parameters; values the request does not fix are left out, never guessed."""
    out = {"fidelity": fidelity.requested(reading, contract)["level"]}
    record = _identifier(reading, "inspire")
    if record:
        out["hepdata_record"] = record
    out.update(_decided(route_analysis))
    if _scan_spec(spec):
        document = (route_analysis or {}).get("scan_grid") if isinstance(route_analysis, dict) else None
        found = grid.resolve(reading, document)
        out["grid"] = found
        out["grid_points"] = deepcopy(found["points"]) if found["complete"] else []
        out["grid_sha256"] = found["sha256"]
    return out


def _route_analysis(context):
    plan = context.get("plan") or {}
    step = checkins.prepare_steps(plan).get("inputs.route")
    if step is None:
        return None
    declared = next((o["path"] for o in step.get("outputs") or () if o["path"].endswith(".json")), None)
    doc, _, problem = common.read_output(context, step["id"], declared) if declared else (None, None, "none")
    return None if problem else doc


def _substitute(value, values):
    if isinstance(value, str):
        if value in UNDECIDED:
            return value
        return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), value)
    if isinstance(value, list):
        return [_substitute(v, values) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, values) for k, v in value.items()}
    return deepcopy(value)


def _decide_task(task, values):
    task = dict(task or {})
    for key in ("detector_mode", "stat_mode"):
        if task.get(key) in UNDECIDED and key in values:
            task[key] = values[key]
    return task


def _recompile(plan, context, computed):
    """The plan recompiled from its route spec with ``computed`` parameters, when the compiler supports it."""
    routes = common.optional_module("ravel.controller.routes")
    if routes is None or not hasattr(routes, "compile") or \
            "parameters" not in inspect.signature(routes.compile).parameters:
        return None
    spec = routes.find(plan["route"]["id"])
    return routes.compile(spec, context.get("reading") or {}, context.get("contract") or {},
                          supplied=context.get("supplied") or (), revision=int(plan.get("revision", 0)) + 1,
                          run_id=plan.get("run_id"), parameters=computed)


def _staged_supplied(context) -> list:
    """The supplied input files intake staged as ``inputs/<name>`` with their digests (its own record)."""
    store, pins = context.get("store"), ((context.get("state") or {}).get("request") or {})
    if store is None or not pins.get("intake_record_id"):
        return []
    record = store.read("intake", pins["intake_record_id"])["record"]
    return [deepcopy(row) for row in record.get("supplied") or () if isinstance(row, dict)]


def bind(plan, context) -> dict | None:
    """The plan with the route analysis's decisions bound into its execution steps, or None.

    Prepare-phase steps already ran: their bytes never change. A recompiled plan whose prepare steps
    differ is not returned.
    """
    if not _owns(plan):
        return None
    analysis = _route_analysis({**context, "plan": plan})
    if analysis is None:
        return None
    values = _decided(analysis)
    bound = None
    routes = common.optional_module("ravel.controller.routes")
    if routes is not None and hasattr(routes, "find") and hasattr(routes, "compile"):
        try:
            spec = routes.find(plan["route"]["id"])
            computed = parameters(spec, context.get("reading"), context.get("contract"),
                                  context.get("supplied") or (), route_analysis=analysis)
            bound = _recompile(plan, context, computed)
        except (ValueError, KeyError, TypeError):
            bound = None
    if bound is not None:
        bound = statistics.bind(execution.bind_launches(bound, analysis, _staged_supplied(context)), context)
        bound["sha256"] = common.digest({k: v for k, v in bound.items() if k != "sha256"})
        old = {s["id"]: s for s in plan.get("steps") or () if common.phase_of(s) == "prepare"}
        for step in bound['steps']:
            if step['id'] in old:
                # The compiler's static ceilings were already narrowed before
                # preparation. Preserve the exact reservation that actually ran.
                step['budget'] = deepcopy(old[step['id']].get('budget', {}))
        new = {s["id"]: s for s in bound.get("steps") or () if common.phase_of(s) == "prepare"}
        if common.digest(old) != common.digest(new):
            return None
        bound['sha256'] = common.digest({k: v for k, v in bound.items() if k != 'sha256'})
        return bound if bound.get("sha256") != plan.get("sha256") else None
    changed = deepcopy(plan)
    for row in changed.get("steps") or ():
        if common.phase_of(row) == "prepare":
            continue
        params = _substitute(row.get("parameters") or {}, values)
        if isinstance(params.get("task"), dict):
            params["task"] = _decide_task(params["task"], values)
        row["parameters"] = params
    changed["parameters"] = {**(changed.get("parameters") or {}), **values}
    changed = statistics.bind(execution.bind_launches(changed, analysis, _staged_supplied(context)), context)
    if common.digest(changed["steps"]) == common.digest(plan.get("steps")):
        return None
    changed["revision"] = int(plan.get("revision", 0)) + 1
    changed["sha256"] = common.digest({k: v for k, v in changed.items() if k != "sha256"})
    return changed


def unbound_errors(plan, *, gate=None) -> list:
    """Execution steps that still carry an unbound placeholder or an undecided mode."""
    errors = []
    for row in (plan or {}).get("steps") or ():
        if common.phase_of(row) == "prepare":
            continue
        params = row.get("parameters") or {}
        text = repr({k: params.get(k) for k in ("task", "launch", "point_id", "grid_sha256")})
        names = sorted(set(PLACEHOLDER.findall(text)))
        undecided = [k for k in ("detector_mode", "stat_mode") if (params.get("task") or {}).get(k) in UNDECIDED]
        if names or undecided:
            errors.append(common.error("plan_unbound", f"step {row['id']} is not bound: "
                                       + ", ".join([f"{{{n}}}" for n in names] + [f"{k} undecided" for k in undecided]),
                                       gate=gate, row="R07", step=row["id"],
                                       fix="complete the route analysis so its decisions bind the plan before CHECK-IN 1"))
    return errors


def admit(step, context) -> list:
    if not _owns(context.get("plan")):
        return []
    errors = guard.admit(step, context)
    if errors:
        discharge.refusals(context.get("store"), common.NODES["route"], errors)
    return errors


# ---- check-ins ---------------------------------------------------------------------------------

def checkin(kind, context) -> dict:
    """The route part of a typed check-in view; ``errors`` hold the authority point."""
    if not _owns(context.get("plan")):
        return {"kind": kind, "errors": [], "sections": [], "required_sections": []}
    view = checkins.view(kind, context)
    store = context.get("store")
    if kind in ("approve_plan", "checkin1"):
        view["errors"] = view["errors"] + unbound_errors(context.get("plan"))
        if view["errors"]:
            discharge.refusals(store, common.NODES["ci1"], view["errors"])
        else:
            credit = discharge.credit(context, "checkin1")
            evidence_ = {"validator": "validate_checkin+route.analysis.checkins",
                         "sha256": common.digest(view.get("legacy")), "mechanism": common.PROVIDER}
            discharge.record(store, common.NODES["ci1"], "satisfied", evidence_, rows={"C04"})
            if credit:
                discharge.record(store, common.NODES["ci1"], "satisfied", {**evidence_, "credit": credit},
                                 rows={"A06", "C03", "C14"})
                discharge.record(store, common.NODES["inputs"], "satisfied", {**evidence_, "credit": credit},
                                 rows={"E04", "E05"})
    elif kind in ("go", "checkin2"):
        if view["errors"]:
            discharge.refusals(store, common.NODES["waypoint"], view["errors"])
        else:
            for row in (context.get("plan") or {}).get("steps") or ():
                if not row.get("waypoint"):
                    continue
                review = ((common.outcomes(store).get(row["id"]) or {}).get("outcome") or {}).get("review") or {}
                if review.get("credited"):
                    discharge.record(store, common.NODES["waypoint"], "satisfied",
                                     {"credit": "review:" + common.digest(review), "mechanism": common.PROVIDER,
                                      "sha256": view["pins"].get(f"waypoint:{row['id']}")}, step=row["id"])
    elif kind in ("final", "checkin3"):
        if view["errors"]:
            discharge.refusals(store, common.NODES["ci3"], view["errors"])
        else:
            discharge.record(store, common.NODES["ci3"], "satisfied",
                             {"validator": "route.analysis.checkins.final", "mechanism": common.PROVIDER,
                              "sha256": common.digest(view.get("recipe_ledger"))}, rows={"C36"})
    return view


# ---- transitions -------------------------------------------------------------------------------

def gate(transition, context) -> list:
    """The route's refusals for one transition; on a pass the route rows it discharges are recorded."""
    plan = context.get("plan")
    if not _owns(plan):
        return []
    errors = guard.gate(transition, context)
    name = str(transition).replace("→", "->").split("[", 1)[0]
    if name in ("plan_review->checkin1", "checkin1->execute", "deviation->execute"):
        errors += unbound_errors(plan, gate=name)
    store = context.get("store")
    if errors:
        discharge.refusals(store, common.NODES["route"], errors)
        missing = [e for e in errors if e["code"] == "route_stage_missing"]
        for node in ROUTE_NODES if missing else ():
            discharge.record(store, node, "violated", {"reason": "; ".join(e["message"] for e in missing)[:1500],
                                                       "mechanism": common.PROVIDER},
                             rows={f"ROUTE-{node.split('.', 1)[1]}"})
        return errors
    if name == "checkin3->deliver":
        for node in ROUTE_NODES:  # the ROUTE row of the request's task mode (instantiated at intake)
            discharge.record(store, node, "satisfied",
                             {"mechanism": "every route stage, check-in and review completed before delivery",
                              "sha256": plan.get("sha256")}, rows={f"ROUTE-{node.split('.', 1)[1]}"})
    if name == "checkin1->execute":
        found, _ = checkins.collect(context)
        discharge.record(store, common.NODES["route"], "satisfied",
                         {"mechanism": "prepare-phase evidence and CHECK-IN 1 before any production step",
                          "artifact": sorted(r["pin"]["artifact"] for r in found.values())}, rows={"R07"})
        discharge.record(store, common.NODES["route"], "satisfied",
                         {"mechanism": "fidelity pinned at intake equals the planned detector fidelity",
                          "validator": "route.analysis.fidelity", "sha256": plan.get("sha256")}, rows={"C26"})
    return errors


# ---- step outcomes -----------------------------------------------------------------------------

WORKFLOW_DOCUMENT = re.compile(r"^docs/workflow/steps/(0[1-9]-[a-z-]+)\.md$")
ANALYZE_DOCUMENT = "docs/workflow/steps/04-analyze.md"


def workflow_steps(step) -> list:
    """The workflow-step documents a plan step delivers (each instantiates its STEP row in the ledger)."""
    found = [m.group(1) for m in (WORKFLOW_DOCUMENT.match(str(s).split("#", 1)[0])
                                   for s in step.get("instruction_sources") or ()) if m]
    named = common.workflow_step_of(step)
    return list(dict.fromkeys(([named] if named else []) + found))


def _step_rows(store, step, outcome, errors):
    """STEP rows of every workflow document the step delivers; E14 where the analyze document is delivered."""
    for workflow_step in workflow_steps(step):
        node = f"{common.NODES['route']}.step[{workflow_step}]"
        rows = {f"STEP-{workflow_step}"}
        if errors:
            discharge.record(store, node, "violated", {"reason": "; ".join(e["message"] for e in errors)[:1500]},
                             rows=rows, step=step["id"])
        else:
            discharge.record(store, node, "satisfied",
                             {"receipt": list(outcome.get("receipts") or []),
                              "validator": f"route.analysis.{common.adapter_of(step)}", "mechanism": common.PROVIDER},
                             rows=rows, step=step["id"])
    if ANALYZE_DOCUMENT not in {str(s).split("#", 1)[0] for s in step.get("instruction_sources") or ()}:
        return
    qualification = [e for e in errors if e.get("row") == "E14"]
    review = outcome.get("review") or {}
    if qualification:
        discharge.record(store, common.NODES["validate"], "violated",
                         {"reason": "; ".join(e["message"] for e in qualification)[:1500]}, rows={"E14"}, step=step["id"])
    elif review.get("credited"):
        discharge.record(store, common.NODES["validate"], "satisfied",
                         {"credit": "review:" + common.digest(review), "validator": "route.analysis.recast",
                          "mechanism": common.PROVIDER}, rows={"E14"}, step=step["id"])


def _scan_rows(store, plan, step, outcome, errors):
    point_id, _ = scan.point_of(step)
    evidence_ = scan.point_evidence(store, plan, step, outcome)
    node = common.NODES["scan"]
    completed = outcome.get("status") == "completed"
    membership = [e for e in errors if e.get("row") in ("G12", "SW33")]
    if membership:
        discharge.refusals(store, node, membership, step=step["id"])
    else:
        discharge.record(store, node, "satisfied", {"mechanism": "point membership in the approved grid",
                                                    "sha256": evidence_["grid_sha256"], "record": evidence_},
                         rows={"G12"}, step=step["id"])
    if completed and not errors:
        discharge.record(store, node, "satisfied", {"record": evidence_, "receipt": evidence_["receipts"],
                                                    "mechanism": common.PROVIDER},
                         rows={"P04", "E24"}, step=step["id"], point=point_id)
        discharge.record(store, node, "satisfied", {"record": evidence_, "mechanism": "approved rung ladder and "
                                                    "per-point reservation", "receipt": evidence_["receipts"]},
                         rows={"E21", "E22", "E23"}, step=step["id"])
    elif not completed:
        reason = scan.hole_reason(point_id, outcome.get("status"), outcome.get("reason"))
        discharge.record(store, node, "violated", {"reason": reason, "record": evidence_},
                         rows={"P04", "E24"}, step=step["id"], point=point_id)


def _population_rows(store, plan, errors, *, mechanism):
    """SW33 on every point step: population equality was applied (holes explicit) or the assembly was refused."""
    refused = [e for e in errors if e.get("row") in ("SW33", "G12", "E24")]
    for step_ in (plan or {}).get("steps") or ():
        if common.adapter_of(step_) != scan.POINT:
            continue
        if refused:
            discharge.record(store, common.NODES["scan"], "violated",
                             {"reason": "; ".join(e["message"] for e in refused)[:1500], "mechanism": mechanism},
                             rows={"SW33"}, step=step_["id"])
        else:
            discharge.record(store, common.NODES["scan"], "satisfied",
                             {"mechanism": mechanism, "sha256": (scan.approved_grid(plan) or {}).get("sha256")},
                             rows={"SW33"}, step=step_["id"])


def final_attempt(step_, outcome) -> bool:
    """True when the controller will not run this step again (its attempt limit is reached)."""
    return int((outcome or {}).get("attempt") or 1) >= int((step_ or {}).get("attempt_limit") or 1)


def step(step_, outcome, context) -> list:
    """Evidence refusals for a joined step outcome.

    A refused attempt the controller will retry records nothing in the ledger (a step's rows have one
    instance, and a violation is final); the refusal is the step's failure reason. Rows are recorded
    satisfied when the evidence holds, and violated only on the step's last attempt.
    """
    plan = context.get("plan")
    if not _owns(plan):
        return []
    outcome = outcome or {}
    store = context.get("store")
    completed = outcome.get("status") == "completed"
    errors = evidence.check(step_, outcome, context) if completed else []
    if (errors or not completed) and not final_attempt(step_, outcome):
        return errors
    if outcome.get("status") == "completed" or errors:
        _step_rows(store, step_, outcome, errors)
    if common.adapter_of(step_) == scan.POINT:
        _scan_rows(store, plan, step_, outcome, errors)
    if common.adapter_of(step_) == scan.ASSEMBLE and outcome.get("status") == "completed":
        _population_rows(store, plan, errors, mechanism="the assembled population against the approved grid")
    if step_.get("kind") == "compare" and outcome.get("status") == "completed":
        rows = {e.get("row") for e in errors}
        for row in ("C28", "C29", "C30"):
            if row in rows:
                discharge.record(store, common.NODES["compare"], "violated",
                                 {"reason": "; ".join(e["message"] for e in errors if e.get("row") == row)[:1500],
                                  "label": "comparison refused"}, rows={row}, step=step_["id"])
            else:
                discharge.record(store, common.NODES["compare"], "satisfied",
                                 {"validator": "route.analysis.compare", "mechanism": common.PROVIDER},
                                 rows={row}, step=step_["id"])
    return errors


# ---- the qualified ending -----------------------------------------------------------------------

def ending(reason, context) -> dict:
    """Before a bounded ending: record every approved point that did not complete as an explicit hole.

    Returns the population record (completed points and holes with their status and reason); it never
    blocks the ending.
    """
    plan = context.get("plan")
    if not _owns(plan) or scan.approved_grid(plan) is None:
        return {}
    store = context.get("store")
    population = scan.population(plan, context)
    steps = {scan.point_of(s)[0]: s for s in (plan or {}).get("steps") or ()
             if common.adapter_of(s) == scan.POINT}
    for row in population["rows"]:
        if row["status"] == "completed" or row["point"] not in steps:
            continue
        step_ = steps[row["point"]]
        evidence_ = scan.point_evidence(store, plan, step_, {"status": row["status"], "reason": row.get("reason"),
                                                             "receipts": row.get("receipts") or []})
        discharge.record(store, common.NODES["scan"], "violated",
                         {"reason": scan.hole_reason(row["point"], row["status"], row.get("reason") or reason),
                          "record": evidence_},
                         rows={"P04", "E24"}, step=step_["id"], point=row["point"])
    _population_rows(store, plan, [], mechanism="population equality at a bounded ending, every hole explicit")
    if store is None:
        return population
    store.append("analysis-scan-population", {"reason": str(reason)[:500], "grid_sha256": population["grid_sha256"],
                                              "expected": population["expected"], "completed": population["completed"],
                                              "holes": [{k: r.get(k) for k in ("point", "step", "status", "reason")}
                                                        for r in population["rows"] if r["status"] != "completed"]})
    return population


def materialize_launch(step, context):
    """Derive one closed executor launch from an approved operation task.

    The caller retains the approved step unchanged. P04 verifies its plan binding,
    resolves the returned input tokens through ``execution.resolve_launch``, and
    passes only that census to P05. Missing preparation is a typed hold, never an
    invitation to dispatch the operation as an agent session.
    """
    from pathlib import Path
    from ravel.controller.step import custody, operations, spec
    from ravel.controller.step.services import StepHold

    def refuse(message, reason="launch_unmaterialised"):
        raise StepHold(reason, message)

    operation = step.get("operation")
    policy = operations.ANALYSIS_LAUNCHES.get(operation)
    signature = operations.signatures().get(operation)
    if step.get("kind") != "operate" or policy is None or signature is None:
        refuse("only a registered analysis operation has a closed launch adapter")
    if signature.get("implementation") != policy["implementation"]:
        refuse("the registered implementation differs from the closed launch adapter")
    if operations.executors()["operations"].get(operation) != policy["role"] or step.get("role") != policy["role"]:
        refuse("the operation must retain its registered executor role")
    context = dict(context)
    plan = context.get("plan")
    if plan is None:
        plan = operations.current_plan(context["store"], context)
        context["plan"] = plan
    for name in ("reading", "contract"):
        if context.get(name) is None:
            try:
                import json
                context[name] = json.loads(context["store"].get_blob(plan[name + "_sha256"]).decode("utf-8"))
            except (KeyError, ValueError, OSError, AttributeError) as exc:
                refuse("the retained " + name + " is unavailable: " + str(exc), "launch_request_changed")
    wanted = context.get("plan_sha256") or plan.get("sha256")
    if (not _owns(plan) or wanted != plan.get("sha256") or
            common.digest({k: v for k, v in plan.items() if k != "sha256"}) != wanted):
        refuse("the current plan pin changed", "launch_request_changed")
    planned = [s for s in plan.get("steps", ()) if s.get("id") == step.get("id")]
    if len(planned) != 1 or common.digest(planned[0]) != common.digest(step):
        refuse("the operation differs from the retained plan step", "launch_request_changed")
    pins = {}
    for name in ("reading", "contract"):
        pin = plan.get(name + "_sha256")
        document = context.get(name)
        if not pin or not isinstance(document, dict) or common.digest(document) != pin:
            refuse("the retained " + name + " pin changed", "launch_request_changed")
        pins[name + "_sha256"] = pin
    retained = (context.get("state") or {}).get("request") or {}
    for name, pin in pins.items():
        if retained.get(name) not in (None, pin):
            refuse("the request and plan pins disagree", "launch_request_changed")
    if context.get("request_sha256") not in (None, retained.get("sha256")):
        refuse("the request identity changed", "launch_request_changed")
    task = spec.parameters(step).get("task")
    if type(task) is not dict or set(task) - set(policy["task_fields"]):
        refuse("the task is outside the closed executor signature")
    executor = task.get("executor")
    if type(executor) is not dict or set(executor) != set(policy["executor_fields"]):
        refuse("the operation needs its prepared closed executor task")
    if spec.launch(step) is not None:
        refuse("task materialization does not replace an explicit approved launch")
    problems = operations.admission_errors(step, approved=planned[0], signature=signature)
    if problems:
        refuse(str(problems))
    # All ancestors are derived from the retained DAG, never caller-supplied grants.
    by_id = {s["id"]: s for s in plan["steps"]}
    ancestors, pending = set(), list(step.get("depends_on") or ())
    while pending:
        parent = pending.pop()
        if parent in ancestors:
            continue
        ancestors.add(parent)
        pending.extend((by_id.get(parent) or {}).get("depends_on") or ())
    problems, adopted, supplied = custody.input_errors(context.get("store"), step, context["run_dir"],
                                                       ancestors=ancestors)
    if problems:
        refuse(str(problems), "launch_input_invalid")
    inputs = [{"artifact": row["artifact"], "path": row.get("destination") or row.get("path"),
               "sha256": row["sha256"]} for row in [*adopted, *supplied]]
    source = executor[policy["input"]]
    if not isinstance(source, str):
        refuse("the executor input names one declared artifact")
    source = source.removeprefix("@input:")
    if source not in {row["artifact"] for row in inputs}:
        refuse("the executor input is not in verified declared custody", "launch_input_invalid")
    problems = operations.admission_errors(step, inputs_custody=[*adopted, *supplied],
                                           approved=planned[0], signature=signature)
    if problems:
        refuse(str(problems), "launch_input_invalid")
    # Reuse the analysis boundary's component-link and byte checks, including
    # accepted predecessor destinations (not just run-input paths).
    provisional = {"argv": ["@input:" + source]}
    checked = deepcopy(step)
    checked["parameters"]["launch"] = provisional
    try:
        execution.resolve_launch(checked, context, output_root=context["run_dir"], inputs=inputs)
    except (ValueError, OSError) as exc:
        refuse(str(exc), "launch_input_invalid")
    route = _route_analysis(context)
    if route is None:
        refuse("the selected routine has no current adopted route evidence", "launch_request_changed")
    if route is not None:
        problems = evidence.request_match_errors(route, context)
        selected = _decided(route).get("routine")
        if task.get("analysis") is not None and task["analysis"] != selected:
            problems.append(common.error("route_routine_mismatch", "task differs from the selected routine"))
        if problems:
            refuse(str(problems), "launch_request_changed")
    argv = list(policy["argv"])
    if "actions" in policy:
        if executor["action"] not in policy["actions"]:
            refuse("the figure action is outside the closed signature")
        argv.append(executor["action"])
    argv.extend([policy["flag"], "@input:" + source])
    if operation == "lifecycle-scan-aggregation":
        path = next(row["path"] for row in inputs if row["artifact"] == source)
        if Path(path).name != "scan_manifest.json":
            refuse("aggregation consumes a scan_manifest.json in verified custody")
        outputs = [o["path"] for o in step["outputs"] if o.get("required", True) and o["path"].endswith(".json")]
        if len(outputs) != 1:
            refuse("aggregation declares exactly one required JSON output")
        argv.extend(["--out", outputs[0].removeprefix("outputs/")])
    elif operation == "figure-comparison":
        argv.extend(["--out", "."])
    point, coordinates = scan.point_of(step)
    try:
        execution.request(step, context)  # validates singleton point and grid context
    except ValueError as exc:
        refuse(str(exc), "launch_request_changed")
    return {"argv": argv, "env": {}, "reads": [], "stage": policy["stage"],
            "input_custody": inputs,
            "scope": {"operation": operation, "role": step["role"], "step_id": step["id"],
                      "plan_sha256": wanted, "request_sha256": retained.get("sha256"), **pins,
                      "task_sha256": common.digest(task), "rung": step.get("rung") or "none",
                      "point": point, "coordinates": coordinates,
                      "grid_sha256": spec.parameters(step).get("grid_sha256"),
                      "outputs": deepcopy(step["outputs"])}}
