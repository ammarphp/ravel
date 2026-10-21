"""Capability recovery and open or mixed parents as judgment plans.

A held (``unsupported``) request, an open parent or a mixed request is never refused:
the judgment planner receives the capability-recovery reading of the current source
(``capability_routing.plan``), turned into step suggestions in the closed vocabulary,
and the parts an installed route spec covers become ``route`` steps that conserve the
parent's obligations. For a frame with boundaries ``seed_plan`` gives a plan that is
always admissible: ask for what would make each held part possible, keep its scope held,
and report. It is a starting point the planner may extend; it substitutes nothing.
"""
from __future__ import annotations

from .records import digest

# Recovery stages of capability_routing.plan and the step kind that carries each.
STAGE_KINDS = {"prepare-parent": "route", "discover": "acquire", "retrieve": "acquire", "resolve": "decide",
               "reuse-or-adapt": "author", "qualify": "operate", "place-execution": "operate", "input-held": "ask",
               "adapt": "author", "deliver-partial": "synthesize", "claim-held": "ask", "design": "decide"}


def hints(prompt: str, contract: dict, reading: dict) -> dict:
    """Recovery hints for the planner from the current capability catalogue; never an admission."""
    from ravel.workflow import capability_routing
    try:
        found = capability_routing.plan(prompt, contract=contract, reading=reading)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {"status": "unavailable", "reason": str(exc)[:500], "candidates": [], "suggested_steps": []}
    candidates = [{"mode": c["mode"], "scope": c.get("scope"), "selection": c.get("selection"),
                   "chain": c.get("chain")} for c in found["candidates"]]
    suggested = []
    for action in found["next_actions"]:
        kind = STAGE_KINDS.get(action["stage"])
        if kind is not None:
            suggested.append({"kind": kind, "stage": action["stage"], "purpose": action["purpose"]})
    return {"status": found["classification_status"], "candidates": candidates,
            "withheld": [w["mode"] for w in found["withheld_candidates"]], "suggested_steps": suggested,
            "compute_authorized": False, "parent_goal_replaced": False}


def seed_plan(frame: dict) -> dict | None:
    """An always-admissible recovery plan for a frame with boundaries, or None without any."""
    if not frame.get("boundaries"):
        return None
    steps, held = [], {}
    for boundary in frame["boundaries"]:
        name = "ask-" + boundary["id"].lower()
        steps.append({"id": name, "kind": "ask", "purpose": f"Ask for what would make the held scope possible: "
                                                           f"{boundary['would_make_possible']}",
                      "question": f"{boundary['statement']} What would make it possible: "
                                  f"{boundary['would_make_possible']}. Supply it, or keep the scope held?",
                      "options": [{"id": "supply", "description": "Supply what would make it possible."},
                                  {"id": "keep_held", "description": "Keep this scope held in the delivery."}],
                      "inputs": [{"artifact": "reading"}], "outputs": [{"path": "outputs/answer.json",
                                                                         "kind": "operator-answer", "required": True}],
                      "depends_on": [], "budget_share": {"fraction": 0.0}, "protocols": [], "review": [],
                      "obligations": ["R10"] + list(boundary["holds"]), "resolves": [boundary["id"]]})
        for deliverable in boundary["holds"]:
            held.setdefault(deliverable, []).append(boundary["id"])
    for unknown in frame.get("unknowns") or []:
        steps.append({"id": "ask-" + unknown["id"].lower(), "kind": "ask", "purpose": "Resolve an unknown of the frame.",
                      "question": unknown["question"],
                      "options": [{"id": "answer", "description": "Answer the question."},
                                  {"id": "keep_open", "description": "Leave it open; dependent scope stays held."}],
                      "inputs": [{"artifact": "reading"}], "outputs": [{"path": "outputs/answer.json",
                                                                         "kind": "operator-answer", "required": True}],
                      "depends_on": [], "budget_share": {"fraction": 0.0}, "protocols": [], "review": [],
                      "obligations": ["JR02"], "resolves": [unknown["id"]]})
    steps.append({"id": "report", "kind": "synthesize", "purpose": "Report the held scope, the questions asked and "
                                                                  "what would make each part possible.",
                  "inputs": [{"artifact": "reading"}], "outputs": [{"path": "outputs/held-scope.json",
                                                                     "kind": "report", "required": True}],
                  "depends_on": [s["id"] for s in steps], "budget_share": {"fraction": 0.05}, "protocols": [],
                  "review": [], "obligations": ["R10", "ROUTE-unsupported"]})
    deliverables = []
    for row in frame["deliverables"]:
        if row["id"] in held:
            deliverables.append({"id": row["id"], "status": "held", "outputs": [],
                                 "held_reason": "held by " + ", ".join(held[row["id"]]) + " until answered"})
        else:
            deliverables.append({"id": row["id"], "status": "held", "outputs": [],
                                 "held_reason": "awaiting the answers to the recovery questions"})
    return {"schema_version": 1, "kind": "judgment-plan", "frame_sha256": digest(frame),
            "rationale": "Recovery seed: ask for what would make each held part possible and keep it held.",
            "steps": steps, "deliverables": deliverables}
