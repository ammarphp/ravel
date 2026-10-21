"""Typed step specifications (controller ``step.v1``) for the judgment route's own workers.

The planner, its critic, the RDJ seats, the kill-the-result worker and the final review
triad are ordinary typed steps: none of them executes anything itself, and every one runs
through ``step.run``, the entry of the governed step graph that fixed routes use (JR04). The
planner writes one document (``author``); a reviewer returns findings (``review``); an RDJ
case is a review by the RDJ critic card on one exact subject digest, credited only from its
observed seat session. Judgment-specific fields travel under ``parameters.judgment``.

The governed step runs only steps bound to a plan record in the run store. Planning steps
precede any approved plan, so the controller binds them to a planning plan it writes itself
(``planning_plan``): a ``controller-plan`` whose steps are exactly the planning steps of one
phase, with every reading deliverable open. It authorizes no effect beyond writing the
declared documents into the run.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json

from .planning import ROUTE_ROWS, plan_sha256, policy

PROTOCOLS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]


@lru_cache(maxsize=1)
def final_review_roles() -> tuple[str, ...]:
    """The CHECK-IN 3 triad from the installed review points (the parent-delivery row)."""
    document = json.loads(files("ravel").joinpath("data", "review_points.json").read_text(encoding="utf-8"))
    trigger = policy()["roles"]["final_review_trigger"]
    for row in document["rows"]:
        if trigger in row["trigger"].split("|") and row["roles"]:
            return tuple(row["roles"])
    raise ValueError(f"no review point row names the final review trigger {trigger!r}")


def _output(name):
    row = policy()["outputs"][name]
    return {"path": row["path"], "kind": row["kind"], "required": True}


def _step(step_id, kind, *, role, description, inputs, outputs, obligations, protocols=(), review=(), sources=(),
          parameters=None, graph=None):
    step = {"id": step_id, "kind": kind, "description": description, "role": role, "inputs": deepcopy(inputs),
            "outputs": deepcopy(outputs), "depends_on": [], "waypoint": False, "rung": None, "budget": {},
            "protocols": list(protocols), "review": list(review), "instruction_sources": list(sources),
            "obligations": list(obligations), "consequence_class": "R0", "attempt_limit": 1,
            "parameters": {"judgment": deepcopy(parameters or {})}}
    if graph is not None:
        step["graph"] = {"id": graph}
    return step


def planner_step(phase: str, number: int, *, inputs: list, purpose: str, output: str, obligations: list) -> dict:
    """The planner (coordinator card, judgment tier, fresh session) writes one document."""
    return _step(f"judgment-{phase}-{number}", "author", role=policy()["roles"]["planner"], description=purpose,
                 inputs=inputs, outputs=[_output(output)], obligations=obligations, protocols=PROTOCOLS,
                 sources=policy()["instruction_sources"]["frame" if phase == "frame" else "decompose"],
                 parameters={"phase": phase, "output_schema": policy()["outputs"][output]["kind"] + ".v1"})


def review_step(step_id: str, *, seats: list, subject: dict, must_check: list, inputs: list, purpose: str,
                obligations: list, sources="review") -> dict:
    """An independent review (fresh session, distinct actor, RAVEL-built packet) of one exact subject."""
    return _step(step_id, "review", role=seats[0], description=purpose, inputs=inputs, outputs=[_output("review")],
                 obligations=obligations, review=seats[1:], sources=policy()["instruction_sources"][sources],
                 parameters={"subject": deepcopy(subject), "must_check": deepcopy(must_check)})


def rdj_role() -> str:
    """The card id of the RDJ critic, resolved through the role registry's one name-to-card mapping."""
    from ravel.workflow import role_registry
    from ravel.workflow.rdj_loop import AGENT_ROLES
    found = role_registry.card_id(AGENT_ROLES["critic"])
    if found is None:
        raise ValueError(f"the RDJ critic role {AGENT_ROLES['critic']!r} names no registered card")
    return found


# The method ladder an RDJ case checks a decision against (the cheapest sufficient method, CHECK-IN 1).
METHOD_LADDER = "docs/workflow/checklists/check-ins.md#cheapest-sufficient-method"


def rdj_step(step_id: str, *, subject: dict, must_check: list, inputs: list, purpose: str, protocols=()) -> dict:
    """An RDJ case on one exact subject digest: a governed review by the RDJ critic card.

    The controller dispatches it as it dispatches a blind review seat (the role's projection, an observed
    seat session, its receipt and transcript) and credits it only from that observed session;
    ``parameters.subject_sha256`` binds the credit to the subject's exact digest. Its packet carries the
    method ladder and the operating protocols (the judgment protocols, and ``protocols``: those the decided
    step's triggers require) as duties it acknowledges.
    """
    # JR06 is the obligation an RDJ case discharges (M21 is a mechanism id, never a declared obligation).
    step = review_step(step_id, seats=[rdj_role()], subject=subject, must_check=must_check, inputs=inputs,
                       purpose=purpose, obligations=["JR06"])
    step["parameters"]["subject_sha256"] = subject["sha256"]
    step["instruction_sources"] = list(dict.fromkeys([*step["instruction_sources"], METHOD_LADDER]))
    step["protocols"] = list(dict.fromkeys([*step["protocols"], *protocols]))
    return step


def attack_step(number: int, *, inputs: list, subject: dict, exclude_roles: list) -> dict:
    """Kill-the-result (P8): a fresh worker, never the planner or a producer, writes three attacks."""
    step = review_step(f"judgment-attack-{number}", seats=[policy()["roles"]["attacker"]], subject=subject,
                       must_check=[{"id": "JR09:attacks", "row": "JR09",
                                    "text": "Write three attacks on the drafted result (basis, acceptance, statistics) "
                                            "and how each was tested, as judgment-attacks.v1."}],
                       inputs=inputs, purpose="Argue the drafted result is wrong three specific ways before the "
                                              "final review sees it.",
                       obligations=["JR09"], sources="attack")
    step["outputs"] = [_output("attacks")]
    step["protocols"] = ["P8"]
    step["parameters"]["judgment"]["distinct_actor_from"] = sorted(set(exclude_roles))
    return step


def planning_plan(steps: list, *, run_id: str, reading: dict, request: dict, phase: str) -> dict:
    """The controller plan that binds one phase's planning steps for the governed step graph.

    It declares the route's own rows (``ROUTE_ROWS``), the rows the judgment graph discharges while it
    plans, so each is in the ledger's current population when its node records it; their run-scoped
    instances carry over unchanged into the plan the route returns, which declares the same rows.
    """
    deliverables = [{"id": d["id"], "status": "open", "step": None, "output": None,
                     "reason": "the judgment route is still planning", "claim_kind": d.get("claim_kind"),
                     "artifact_kind": (d.get("artifact") or {}).get("kind") if type(d.get("artifact")) is dict else None}
                    for d in reading.get("deliverables") or [] if type(d) is dict and type(d.get("id")) is str]
    plan = {"schema_version": 1, "kind": "controller-plan", "run_id": run_id,
            "route": {"id": "judgment", "version": 1, "spec_sha256": None},
            "parameters": {"judgment": {"planning_phase": phase}}, "steps": deepcopy(steps),
            "deliverables": deliverables, "waypoints": [], "obligations": list(ROUTE_ROWS), "open_obligations": [],
            "instruction_sources": list(policy()["instruction_sources"]["decompose"]),
            "reading_sha256": request.get("reading_sha256"), "contract_sha256": request.get("contract_sha256")}
    plan["sha256"] = plan_sha256(plan)
    return plan
