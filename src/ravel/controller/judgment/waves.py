"""The wave review: code first, over the outcomes of the last wave.

For every step the last wave ran it records what the controller observed: a decide
step's record is validated, classified and stored, or refused (JR05, E28); a compare
step needs its P2 basis manifests and a comparison within tolerance, else a P5
decomposition is opened by replanning; a step whose triggers name protocols needs that
evidence (P1, P3-P6); a resource is declared unavailable only with the source ladder
(E03); a failed stage asks for a recovery plan with diagnosis and recipe search (E12);
worker escalations are acted on. The planner proposes nothing here: only code decides.
"""
from __future__ import annotations

from . import protocols, records
from .planning import policy
from .services import read_output

EVIDENCE_KIND = "protocol-evidence"
COMPARISON_KIND = "comparison"


def declared_path(step, kind):
    """The declared output path of ``kind`` in a step (the step outcome names paths, not kinds)."""
    found = [o["path"] for o in step.get("outputs") or [] if o.get("kind") == kind]
    return found[0] if found else None


def _evidence(run, step, outcome, kind):
    path = declared_path(step, kind)
    if path is None:
        return None, [f"step {step['id']} declares no {kind} output"]
    doc, where = read_output(run, outcome, path=path, step_id=step["id"])
    if doc is None:
        return None, [f"step {step['id']} wrote no {kind} output: {where}"]
    if type(doc) is not dict or type(doc.get("protocol_evidence")) is not dict:
        return None, [f"step {step['id']} {kind} output carries no protocol_evidence object"]
    return doc, []


def review(store, run: dict, view: dict, plan: dict, bound: dict, number: int, wave: dict) -> list[dict]:
    """Events for the wave numbered ``number`` (judgment records are stored as they are accepted)."""
    by_id = {s["id"]: s for s in plan["steps"]}
    events, replan, end, flags = [], None, None, []
    for name in wave.get("steps") or []:
        step = by_id.get(name)
        state = view["steps"].get(name) or {}
        outcome = state.get("outcome")
        if step is None or outcome is None:
            continue
        status = outcome["status"]
        escalation = outcome.get("escalation")
        if escalation == "stop":
            end = end or f"the worker of step {name} escalated stop"
        elif escalation == "checkin_flag":
            flags.append({"event": "flag", "step": name, "text": outcome.get("reason") or "worker check-in flag"})
        elif escalation in ("decision_block", "new_experiment_required"):
            replan = replan or {"reason": escalation, "step": name}
        if status == "exhausted":
            end = end or f"the budget was exhausted in step {name}"
            continue
        if status == "stopped":
            end = end or f"step {name} stopped: {outcome.get('reason') or 'stop requested'}"
            continue
        if status == "held":
            events.append({"event": "step_state", "step": name, "status": "held",
                           "reason": outcome.get("reason") or "the governed step held"})
            continue
        if status == "failed":
            events.append({"event": "step_state", "step": name, "status": "failed",
                           "reason": outcome.get("reason") or "the governed step failed"})
            replan = replan or {"reason": "stage_failure", "step": name}
            continue
        problems, close, extra = _adopted(store, run, step, state, outcome)
        events.extend(extra)
        if problems:
            retry = state.get("attempts", 0) < bound["step_attempts"]
            if step["kind"] == "decide":
                events.append({"event": "record_refused", "step": name, "problems": problems})
            events.append({"event": "step_state", "step": name, "status": "retry" if retry else "violated",
                           "reason": "; ".join(problems)[:2000]})
            continue
        if close is not None:
            events.append(close)
        for item in extra:
            if item.get("replan_request"):
                replan = replan or item["replan_request"]
    decision = "end" if end else "replan" if replan else "continue"
    summary = {"event": "wave_review", "number": number, "decision": decision}
    if replan:
        summary["replan_request"] = replan
    if end:
        summary["end"] = end
    return events + flags + [summary]


def _adopted(store, run, step, state, outcome):
    """(problems, closing event or None, extra events) for an adopted step."""
    name = step["id"]
    triggers = sorted(set(step.get("triggers") or []) | set(protocols.implied_triggers(step["kind"],
                                                                                      step.get("action"))))
    if step["kind"] == "decide":
        tier = outcome.get("tier")
        if tier is not None and tier != "judgment":
            return [f"decide step {name} ran at the {tier} tier; a judgment call needs the judgment tier"], None, []
        path = declared_path(step, policy()["outputs"]["record"]["kind"]) or policy()["outputs"]["record"]["path"]
        doc, where = read_output(run, outcome, path=path, step_id=name)
        if doc is None:
            return [f"decide step {name} took a judgment without a record: {where}"], None, []
        try:
            judgment_id = records.record_judgment(store, doc, step=step, plan_class=step["class"])
        except records.JudgmentRecordError as exc:
            return exc.errors, None, []
        stored = records.for_step(store, name)[-1]
        return [], None, [{"event": "record", "step": name, "judgment_id": judgment_id,
                           "record_sha256": stored["record_sha256"], "class": stored["class"],
                           "requirement": stored["reviewer_requirement"], "triggers": stored["triggers"],
                           "default": stored.get("default"), "default_option": stored.get("default_option"),
                           "options": [o["id"] for o in stored["options"]], "chosen": stored["chosen"]}]
    extra = []
    if step["kind"] == "compare":
        doc, problems = _evidence(run, step, outcome, COMPARISON_KIND)
        if problems:
            return problems, None, []
        problems = protocols.check_required(triggers, doc["protocol_evidence"])
        if problems:
            return problems, None, []
        if type(doc.get("within_tolerance")) is not bool:
            return [f"compare step {name} states no within_tolerance verdict"], None, []
        if not doc["within_tolerance"]:
            extra.append({"event": "flag", "step": name, "text": "comparison outside tolerance; P5 decomposition opened",
                          "replan_request": {"reason": "discrepancy", "step": name}})
    elif triggers:
        doc, problems = _evidence(run, step, outcome, EVIDENCE_KIND)
        if problems:
            return problems, None, []
        problems = protocols.check_required(triggers, doc["protocol_evidence"])
        if problems:
            return problems, None, []
        p4 = doc["protocol_evidence"].get("P4")
        if p4 and any(row["action"] == "open_p5" for row in p4["rows"]):
            extra.append({"event": "flag", "step": name, "text": "an anchor ratio outside its regime opened P5",
                          "replan_request": {"reason": "discrepancy", "step": name}})
        p6 = doc["protocol_evidence"].get("P6")
        if p6 and p6["claim"] == "unavailable":
            return [], {"event": "step_state", "step": name, "status": "held",
                        "reason": "required resource unavailable after source-ladder rungs 1-5; ask the physicist "
                                  "with the ladder's evidence"}, extra + [
                {"event": "flag", "step": name, "text": "resource unavailable after the source ladder",
                 "replan_request": {"reason": "resource_unavailable", "step": name}}]
    return [], {"event": "step_state", "step": name, "status": "closed", "reason": None}, extra
