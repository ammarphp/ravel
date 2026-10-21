"""Reasoned assumptions on the real controller composition: a question no plan default answers, in inert runs.

Each case is one bounded inert run on the wave-A gate's harness (imported from ``test_composition_wave_a`` and
``test_composition_autonomy``, never copied). The inert planner adds an ``ask`` step whose question (which fictional
reading the request means) has no plan-declared default; the derivation depends on it. When the controller asks
for a reasoned assumption, the planner reads the request it was given (the question, its options, whether the
controller computed it physics-critical) and returns its proposal: the option the run's evidence supports, every
alternative with its evidence and reasons, and, for a physics-critical ambiguity, a sibling branch that derives the
result under the main alternative. No model runs and no answer is hard-wired in the controller.

(a) Autonomous mode with the operator's ``assumption`` delegation, an unanticipated non-critical question: the
    governed judgment step proposes, the operator's configured machine authority takes the assumption once nobody
    answered within the wait bound (machine label, never human), the delivery is accepted and lists it.
(b) A physics-critical ambiguity: the result is conditional on the assumption, the alternative branch runs as an
    approved deviation, and the delivery reports both with conditional and alternative labels.
(c) Without the delegation (outside the operator's configured authority): nothing is assumed; the question waits for
    a human, notified once with the run name and a state code.
(d) Interactive mode (physicist in the loop) is unchanged: the question waits for the physicist and no assumption is
    proposed.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re

from ravel.controller import entry, testing
from ravel.controller.ledger import state as ledger_state
import test_composition_autonomy as autonomy
import test_composition_wave_a as wave_a

CHECKINS = ",".join(list(wave_a.MACHINE_CHECKINS) + ["assumption"])

PLANNER = r'''
SCENARIO = json.loads(__SCENARIO__)
_FIRST_PLAN = plan
_FIRST_CONTENT = content
ALT = "alt-"

def content(path, step, docs, consumed):
    # The alternative branch's outputs are the derivation's own documents under prefixed names.
    return _FIRST_CONTENT(path.replace("outputs/" + ALT, "outputs/"), step, docs, consumed)

ASK = {"id": "choose-reading", "kind": "ask", "purpose": "Ask which fictional reading of the request applies.",
       "question": "Which fictional reading of the toy quantity does the request mean?",
       "options": [{"id": "reading-a", "description": "the first fictional reading"},
                   {"id": "reading-b", "description": "the second fictional reading"}],
       "inputs": [{"artifact": "reading"}],
       "outputs": [{"path": "outputs/answer.json", "kind": "operator-answer", "required": True}],
       "depends_on": [], "budget_share": {"fraction": 0.05}, "protocols": [], "review": [], "obligations": []}

def _assumption(value):
    """The controller's assumption request anywhere in the planner's inputs."""
    if isinstance(value, dict):
        if "question_step" in value and "options" in value and "physics_critical" in value:
            return value
        value = list(value.values())
    if isinstance(value, list):
        for child in value:
            found = _assumption(child)
            if found is not None:
                return found
    return None

def plan(docs, step):
    doc = _FIRST_PLAN(docs, step)
    derive = next(s for s in doc["steps"] if s["id"] == "derive-value")
    derive["depends_on"] = list(derive["depends_on"]) + ["choose-reading"]
    doc["steps"].insert(0, json.loads(json.dumps(ASK)))
    request = _assumption(docs)
    if request is None:
        return doc
    critical = bool(SCENARIO.get("critical"))
    doc["assumption"] = {
        "question_step": request["question_step"], "chosen": "reading-a", "physics_critical": critical,
        "alternative_branch": "reading-b" if critical else None,
        "rationale": "Chosen from the run's own evidence.",
        "alternatives": [
            {"option": "reading-a", "evidence": ["the reading names the first fictional quantity"],
             "reasons": "the request and its reading name the first fictional reading", "rejection": None},
            {"option": "reading-b", "evidence": ["no run input names the second fictional reading"],
             "reasons": "a possible reading that no evidence supports",
             "rejection": "nothing in the request or the run's inputs supports it"}]}
    if critical:
        # The main alternative interpretation as a sibling branch: the same derivation under its own outputs.
        other = json.loads(json.dumps(derive).replace('"outputs/', '"outputs/' + ALT))
        other.update(id="derive-value-alt", purpose="Derive the fictional quantity under the second reading.",
                     budget_share={"fraction": 0.2})
        doc["steps"].append(other)  # reported beside the deliverable (one output each), never a new deliverable
    return doc
'''


def _worker(**scenario):
    """The wave-A inert worker with the planner above (inserted before its entry point)."""
    marker = '\nif __name__ == "__main__":'
    assert wave_a.WORKER.count(marker) == 1
    return wave_a.WORKER.replace(marker, "\n" + PLANNER.replace("__SCENARIO__", repr(json.dumps(scenario))) + marker)


def _assumptions(store):
    return wave_a._records(store, "assumption")


def _diagnostic(store):
    plans = [{"source": r.get("source"), "assumption": (r.get("plan") or {}).get("assumption")}
             for r in wave_a._records(store, "judgment-plan")]
    escalations = [{k: r.get(k) for k in ("kind", "decision", "option", "label", "evidence")}
                   for r in wave_a._records(store, "authority") if r.get("kind") == "escalation"]
    return json.dumps({"assumption": _assumptions(store), "plans": plans, "escalations": escalations},
                      default=str)[:8000]


def _outcomes(store):
    return {r["step_id"]: r["status"] for r in wave_a._records(store, "step-outcome") if not r.get("seat")}


def _audited_statements(store):
    """The statements of the delivery assumption subject the K8 auditor reviewed."""
    texts = []
    for path in sorted(Path(store.run_dir, "inputs").glob("delivery-assumptions-*.json")):
        texts += [a["statement"] for a in json.loads(path.read_text())["assumptions"]]
    return texts


def test_a_non_critical_question_is_answered_by_a_reasoned_machine_assumption_and_accepted(tmp_path, monkeypatch):
    root, store = autonomy._environment(tmp_path, monkeypatch, "--machine-checkins", CHECKINS,
                                        "--r3-delegation", "final_task", "--wait-bound", "0", worker=_worker())
    try:
        observation, err = autonomy._drive(store)
        rows = _assumptions(store)
        phases = [(r["phase"], r["step"]) for r in rows]
        assert ("proposed", "choose-reading") in phases and ("taken", "choose-reading") in phases, \
            (phases, _diagnostic(store), wave_a._where(store))
        [proposed] = [r for r in rows if r["phase"] == "proposed"]
        assert proposed["option"] == "reading-a" and proposed["conditional"] is False
        assert {a["option"] for a in proposed["alternatives"]} == {"reading-a", "reading-b"}
        assert all(a["rejection"] for a in proposed["alternatives"] if a["option"] != "reading-a")
        [record] = [r for r in wave_a._records(store, "authority") if r["kind"] == "escalation"]
        assert record["decision"] == "default" and record["option"] == "reading-a", record
        assert record["label"] == "operator_configured_machine" and record["human_identity_authenticated"] is False
        assert record["evidence"]["machine_assumption"]["option"] == "reading-a"
        assert {r["label"] for r in wave_a._records(store, "authority")} == {"operator_configured_machine"}
        assert _outcomes(store).get("derive-value") == "completed", (_outcomes(store), wave_a._where(store))
        # The delivery's assumption list carries the machine assumption, and the K8 auditor reviewed it.
        assert any(s.startswith("MACHINE ASSUMPTION") for s in _audited_statements(store)), _audited_statements(store)
        from ravel.workflow import spawn_rows
        [audit] = [r for r in spawn_rows.report(store.run_dir) if r["row"] == "K8"]
        assert audit["pending"] is False, audit
        from ravel.controller import sink
        receipt = sink.receipt(store)
        assert "CONDITIONAL RESULT" not in (receipt.get("labels") or [])
        assert receipt.get("accepted") is True, json.dumps({"unmet": wave_a._unmet(store, "deliver[accepted]"),
                                                            "labels": receipt.get("labels")}, default=str)
    finally:
        ledger_state.forget(store)


def test_a_physics_critical_ambiguity_is_conditional_and_its_alternative_runs_beside_it(tmp_path, monkeypatch):
    root, store = autonomy._environment(tmp_path, monkeypatch, "--machine-checkins", CHECKINS,
                                        "--r3-delegation", "final_task", "--wait-bound", "0",
                                        worker=_worker(critical=True))
    try:
        autonomy._drive(store)
        rows = _assumptions(store)
        [proposed] = [r for r in rows if r["phase"] == "proposed"]
        assert proposed["conditional"] is True and proposed["assumptions"][0]["statement"].startswith(
            "CONDITIONAL RESULT"), _diagnostic(store)
        branch = [r for r in rows if r["phase"] in ("alternative", "alternative_skipped")]
        assert branch and branch[-1]["phase"] == "alternative", _diagnostic(store)
        assert branch[-1]["added_steps"] == ["derive-value-alt"] and branch[-1]["budget_rule"]
        deviations = [r for r in wave_a._records(store, "authority") if r["kind"] == "deviation"]
        assert deviations and deviations[-1]["label"] == "operator_configured_machine", wave_a._where(store)
        [record] = [r for r in wave_a._records(store, "authority") if r["kind"] == "escalation"]
        assert record["evidence"]["machine_assumption"]["conditional"] is True
        outcomes = _outcomes(store)
        assert outcomes.get("derive-value") == "completed" and outcomes.get("derive-value-alt") == "completed", \
            (outcomes, wave_a._where(store))
        statements = _audited_statements(store)
        assert any(s.startswith("CONDITIONAL RESULT") for s in statements), statements
        assert any(s.startswith("ALTERNATIVE BRANCH") for s in statements), statements
        from ravel.controller import sink
        receipt = sink.receipt(store)
        labels = receipt.get("labels") or []
        assert "CONDITIONAL RESULT" in labels and "ALTERNATIVE INTERPRETATION" in labels, labels
        details = [d for d in receipt.get("label_details") or () if d.get("label") == "ALTERNATIVE INTERPRETATION"]
        assert any(str(d.get("artifact") or "").startswith("derive-value-alt:") for d in details), details
        conditional = [d for d in receipt.get("label_details") or () if d.get("label") == "CONDITIONAL RESULT"]
        assert any(str(d.get("artifact") or "").startswith("derive-value:") for d in conditional), conditional
        wave_a._assert_honest_receipt(store)
    finally:
        ledger_state.forget(store)


def test_without_the_delegation_the_question_waits_for_a_human_notified_once(tmp_path, monkeypatch):
    command, log = autonomy._notifier(Path(os.path.realpath(tmp_path)))
    root, store = autonomy._environment(tmp_path, monkeypatch, "--notify-command", command, "--wait-bound", "0",
                                        worker=_worker())
    try:
        autonomy._drive(store)
        assert [r for r in _assumptions(store) if r["phase"] == "proposed"] == [], _diagnostic(store)
        requests = [r for r in wave_a._records(store, "authority-request") if r["kind"] == "escalation"]
        assert requests and requests[0]["subject"].get("machine_assumption") is None, requests
        assert [r for r in wave_a._records(store, "authority") if r["kind"] == "escalation"] == []
        lines = log.read_text().splitlines() if log.exists() else []
        assert [line for line in lines if line.endswith("WAITING_FOR_HUMAN escalation")] == \
            [f"{store.run_id} | WAITING_FOR_HUMAN escalation"], lines
        assert all(len(line.split(" | ")) == 2 for line in lines), lines
        assert _outcomes(store).get("derive-value") is None, _outcomes(store)
        endings = wave_a._records(store, "qualified-ending")
        assert endings, wave_a._where(store)
    finally:
        ledger_state.forget(store)


def test_interactive_mode_is_unchanged_the_question_waits_for_the_physicist(tmp_path, monkeypatch):
    root, store = autonomy._environment(tmp_path, monkeypatch, "--mode", "physicist-in-the-loop",
                                        "--machine-checkins", CHECKINS, "--wait-bound", "3600", worker=_worker())
    try:
        with testing.seams(False, controller=True):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                observation = entry.drive(store, unattended=False, sleep=lambda seconds: None, poll_seconds=0)
            for _ in range(6):
                pending = entry._pending(observation)
                assert pending, wave_a._pending_diagnostic(store, observation, err.getvalue())
                kind = pending[0]["payload"]["authority_kind"]
                if kind == "escalation":
                    break
                request_id = pending[0]["payload"]["pending"]["request"]
                code = re.findall(r"--code (\S+)", err.getvalue())[-1]
                decision = {"approve_plan": "approve", "go": "go", "deviation": "approve"}[kind]
                status, output = wave_a._operator("answer", "--run", store.run_id, "--request", request_id,
                                                  "--code", code, "--decision", decision)
                assert status == 0, output
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    observation = entry.drive(store, unattended=False, resume=True, sleep=lambda seconds: None,
                                              poll_seconds=0)
        [pending] = entry._pending(observation)
        assert pending["payload"]["authority_kind"] == "escalation", observation
        assert _assumptions(store) == [], _diagnostic(store)
        [request] = [r for r in wave_a._records(store, "authority-request") if r["kind"] == "escalation"]
        assert request["subject"].get("machine_assumption") is None and request["subject"].get(
            "conservative_default") is None, request["subject"]
        assert [r for r in wave_a._records(store, "authority") if r["kind"] == "escalation"] == []
    finally:
        ledger_state.forget(store)
