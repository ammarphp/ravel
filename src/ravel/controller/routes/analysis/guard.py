"""Route refusals of the analysis family at controller transitions and before each dispatch.

The controller graph already orders the run (intake, plan, CHECK-IN 1, waves, CHECK-IN 2 at the
waypoint, final review, CHECK-IN 3, sink) and the authority service refuses an effect above the
approved rung. This module adds what only the analysis route knows:

- R07: nothing at or above the smoke rung, and no production operation, is dispatched before every
  prepare-phase step (01 environment, 02 inputs) has completed with its evidence holding and a
  CHECK-IN 1 authority record exists for the current plan;
- A08 and E21: a full or scan rung step needs the current CHECK-IN 2 GO, and a plan that reaches
  the full or scan rung must have a waypoint below it (the rung ladder dry, smoke, pilot, full,
  scan is never skipped);
- C26: the planned and delivered detector fidelity never falls below the pinned request;
- C03/A06/C04/C14 at CHECK-IN 1, C10 at CHECK-IN 2, C36 at the final check-in (``checkins``);
- SW33, G12, P04 and E24: the scan population equals the approved grid before final review and
  delivery (``scan``).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from . import checkins, common, evidence, fidelity, scan
from .common import error

PRODUCTION_RUNGS = ("smoke", "pilot", "full", "scan")
BULK_RUNGS = ("full", "scan")
PRODUCTION_EFFECTS = ("generates_events", "simulates_detector", "executes_native", "runs_authored_code")


def _transition(name):
    text = str(name or "").replace("→", "->").strip()
    base, _, rest = text.partition("[")
    return base.strip(), rest.rstrip("]") or None


@lru_cache(maxsize=1)
def _signatures():
    from ravel.workflow.operation_registration import read_signatures
    return read_signatures(Path(__file__).resolve().parents[3] / "data" / "operation_signatures.json")


def _signature_effects(operation):
    if not operation:
        return []
    return list((_signatures().get(operation) or {}).get("effects") or ())


def production(step) -> bool:
    """A step that generates, simulates, runs native code or sits at a production rung."""
    if step.get("rung") in PRODUCTION_RUNGS:
        return True
    return bool(set(_signature_effects(step.get("operation"))) & set(PRODUCTION_EFFECTS))


def prepare_errors(context, *, gate=None) -> list:
    """Every prepare-phase step completed and its evidence holds (the 02-inputs evidence of R07)."""
    plan = context.get("plan") or {}
    steps = [s for s in plan.get("steps") or () if common.phase_of(s) == "prepare"]
    if not steps:
        return [error("prepare_phase_missing", "the analysis plan has no prepare phase (01 environment, 02 inputs)",
                      gate=gate, row="R07")]
    errors = []
    for step in steps:
        status = common.step_status(context, step["id"])
        if status != "completed":
            errors.append(error("prepare_step_open", f"prepare step {step['id']} is {status or 'not run'}",
                                gate=gate, row="R07", step=step["id"],
                                fix="complete the 01 and 02 steps before CHECK-IN 1"))
            continue
        outcome = common.outcomes(context.get("store")).get(step["id"])
        for problem in evidence.check(step, outcome, context):
            errors.append({**problem, "gate": gate})
    return errors


def ladder_errors(plan, *, gate=None) -> list:
    """A plan that reaches the full or scan rung has a waypoint below it (A08, E21)."""
    steps = (plan or {}).get("steps") or ()
    bulk = [s for s in steps if s.get("rung") in BULK_RUNGS]
    if not bulk:
        return []
    by_id = {s["id"]: s for s in steps}
    waypoints = [s for s in steps if s.get("waypoint")]
    errors = []
    if not waypoints:
        errors.append(error("waypoint_missing", "the plan reaches the full or scan rung without an early-verification "
                            "waypoint, so no CHECK-IN 2 GO would precede bulk compute", gate=gate, row="E21"))
    for step in bulk:
        seen, stack, below = set(), list(step.get("depends_on") or ()), False
        while stack:
            current = stack.pop()
            if current in seen or current not in by_id:
                continue
            seen.add(current)
            if by_id[current].get("waypoint"):
                below = True
                break
            stack.extend(by_id[current].get("depends_on") or ())
        if waypoints and not below:
            errors.append(error("rung_ladder_skipped", f"bulk step {step['id']} does not depend on a waypoint; the "
                                "smoke rung and CHECK-IN 2 cannot be skipped", gate=gate, row="E21", step=step["id"]))
    return errors


def admit(step, context) -> list:
    """Refusals before ``step`` is dispatched (R07, A08); an empty list admits it."""
    plan = context.get("plan") or {}
    if common.phase_of(step) == "prepare":
        if step.get("rung") not in (None, "none", "dry"):
            return [error("prepare_rung", f"prepare step {step['id']} is at rung {step.get('rung')}", row="R07",
                          step=step["id"])]
        if production(step):
            return [error("prepare_production", f"prepare step {step['id']} runs {step.get('operation')}, which "
                          "generates, simulates or runs native code before CHECK-IN 1", row="R07", step=step["id"])]
        return []
    errors = []
    if production(step) or step.get("rung") in PRODUCTION_RUNGS:
        errors += prepare_errors(context)
        if checkins.latest_authority(context.get("store"), "approve_plan", plan=plan) is None:
            errors.append(error("checkin1_missing", f"{step['id']} would generate or launch before CHECK-IN 1 "
                                "authority exists for this plan", row="R07", step=step["id"]))
    if step.get("rung") in BULK_RUNGS:
        if checkins.latest_authority(context.get("store"), "go", plan=plan) is None:
            errors.append(error("checkin2_go_missing", f"{step['id']} is at the {step['rung']} rung and no CHECK-IN 2 "
                                "GO exists", row="A08", step=step["id"]))
        errors += ladder_errors(plan)
    return errors


def delivered_modes(context) -> dict:
    """``result name -> detector mode`` from the adopted statistics and scan outputs."""
    found = {}
    for step in (context.get("plan") or {}).get("steps") or ():
        if common.adapter_of(step) not in ("exclude", scan.ASSEMBLE):
            continue
        declared = next((o["path"] for o in step.get("outputs") or () if o["path"].endswith(".json")), None)
        if declared is None:
            continue
        doc, _, problem = common.read_output(context, step["id"], declared)
        if problem or not isinstance(doc, dict):
            continue
        found[f"{step['id']}:{declared}"] = doc.get("detector_mode")
    return found


def gate(transition, context) -> list:
    """Route refusals for one controller transition (P01 gate nodes and ledger transitions)."""
    name, qualifier = _transition(transition)
    plan = context.get("plan") or {}
    reading, contract = context.get("reading"), context.get("contract")
    errors = []
    if name in ("plan_review->checkin1", "checkin1->execute"):
        errors += prepare_errors(context, gate=name)
        errors += [{**e, "gate": name} for e in checkins.approve_plan(context)["errors"]]
        errors += fidelity.plan_errors(reading, contract, plan, gate=name)
        errors += ladder_errors(plan, gate=name)
        errors += scan.membership_errors(plan, gate=name)
    elif name == "deviation->execute":
        errors += fidelity.plan_errors(reading, contract, plan, gate=name)
        errors += ladder_errors(plan, gate=name)
        errors += scan.membership_errors(plan, gate=name)
    elif name == "checkin2->execute":
        errors += [{**e, "gate": name} for e in checkins.go(context)["errors"]]
    elif name == "execute->final_review":
        if scan.approved_grid(plan) is not None:
            population = scan.population(plan, context)
            if population["holes"]:
                errors.append(error("scan_holes", f"{len(population['holes'])} approved point(s) are not completed: "
                                    + ", ".join(population["holes"][:20]), gate=name, row="E24",
                                    pins=population["holes"][:50]))
    elif name in ("final_review->checkin3", "checkin3->deliver") or (name == "deliver"
                                                                     and qualifier in (None, "accepted")):
        errors += [{**e, "gate": name} for e in checkins.final(context)["errors"]]
        errors += fidelity.result_errors(reading, contract, delivered_modes(context), gate=name)
        if scan.approved_grid(plan) is not None:
            for step in scan.assembly_steps(plan):
                declared = next((o["path"] for o in step.get("outputs") or () if o["path"].endswith(".json")), None)
                doc, _, problem = common.read_output(context, step["id"], declared) if declared else (None, None, "")
                if problem or doc is None:
                    errors.append(error("scan_assembly_missing", f"{step['id']}: {problem or 'no assembled scan'}",
                                        gate=name, row="SW33", step=step["id"]))
                else:
                    errors += scan.assembled_errors(doc, plan, context, step_id=step["id"], gate=name)
    return errors
