"""Runtime recovery on the real controller composition: inert runs whose step cannot complete.

Each case is one bounded inert autonomous run on the wave-A gate's harness (imported from ``test_composition_wave_a``
and ``test_composition_autonomy``, never copied). The inert worker is the wave-A script with a planner variant: the
first plan's derivation reads a fictional run input; when the controller asks for a recovery plan, the planner reads
the recovery request (the failed step, its typed reason, the run's staged inputs) and proposes its alternatives with
their evidence: another source among the staged inputs when one exists, otherwise none, or a descope when the case
asks for it. No model runs and no alternative is hard-wired in the controller.

1. A required input is missing and a supplied alternative source exists: the run recovers through a deviation the
   operator's configured machine authority approves, and the delivery is accepted.
2. No alternative exists: the rest of the run completes and the qualified ending names the gap and the alternatives
   tried.
3. A provider refusal of a step is not routed to recovery: it stays a hold.
4. The recovery budget is spent: the qualified ending names it.
5. A descope (a recovery outside the operator's bounds) waits for a human, notified once with the run name and a
   state code only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

from ravel.controller.ledger import state as ledger_state
import test_composition_autonomy as autonomy
import test_composition_wave_a as wave_a

PRIMARY = "inputs/fictional-primary.json"
RELEASE = "inputs/fictional-release.json"
DATA = {"schema_version": 1, "kind": "fictional-data", "value": 1.0, "uncertainty": 0.1}


def _classification():
    from ravel.workflow import provider_policy, transport_registry
    transport = transport_registry.load(wave_a.TRANSPORT)
    return {"level": "public", "allowed_providers": [
        {"transport_id": wave_a.TRANSPORT, "account_class": provider_policy.account_class(transport)}]}


PLANNER = r'''
SCENARIO = json.loads(__SCENARIO__)
_FIRST_PLAN = plan
_FIRST_CONTENT = content
CROSS = "cross-check-"

def content(path, step, docs, consumed):
    # The cross-check step's outputs are the derivation's own documents under prefixed names.
    return _FIRST_CONTENT(path.replace("outputs/" + CROSS, "outputs/"), step, docs, consumed)

def _recovery(value):
    """The controller's recovery request anywhere in the planner's inputs (a dict naming the failed step)."""
    if isinstance(value, dict):
        if "failed_step" in value and "run_inputs" in value:
            return value
        value = list(value.values())
    if isinstance(value, list):
        for child in value:
            found = _recovery(child)
            if found is not None:
                return found
    return None

def plan(docs, step):
    doc = _FIRST_PLAN(docs, step)
    derive = next(s for s in doc["steps"] if s["id"] == "derive-value")
    if SCENARIO.get("primary"):
        derive["inputs"] = list(derive["inputs"]) + [{"artifact": SCENARIO["primary"]}]
    if SCENARIO.get("cross_check"):
        # An independent part of the analysis: the same governed derivation under its own outputs.
        other = json.loads(json.dumps(_FIRST_PLAN(docs, step)["steps"][-1]))
        other.update(id="cross-check", purpose="Derive a fictional cross-check.", budget_share={"fraction": 0.2})
        text = json.dumps(other).replace('"outputs/', '"outputs/' + CROSS)
        doc["steps"].append(json.loads(text))
    recovery = _recovery(docs)
    if recovery is None:
        contexts = [d for d in docs if isinstance(d, dict) and d.get("schema") == "judgment-plan.v1"]
        if any("failures" in d for d in contexts):  # say what a planner without a recovery request was given
            doc["rationale"] = " || ".join(",".join(sorted(d)) + " request=" + json.dumps(d.get("request"))[:300]
                                           for d in contexts)[:1500]
        return doc
    staged = {r.get("artifact") for r in recovery.get("run_inputs") or () if isinstance(r, dict)}
    rows = []
    for artifact in SCENARIO.get("alternatives") or ():
        found = artifact in staged
        rows.append({"id": "source-" + re.sub(r"[^a-z0-9-]", "-", artifact.lower())[:40], "kind": "source",
                     "description": "Read the same quantity from " + artifact + ".",
                     "evidence": [artifact + (" is a staged run input" if found else " is not among the staged inputs")],
                     "bound": None, "rejection": None if found else "the source is not available to the run"})
    rows.append({"id": "method-other", "kind": "method", "description": "Derive the quantity by another method.",
                 "evidence": ["the run declares no other method that yields the quantity"], "bound": None,
                 "rejection": "no admitted operation yields the quantity without the missing input"})
    if SCENARIO.get("descope"):
        rows.append({"id": "descope", "kind": "descope", "description": "Hold the deliverable with its reason.",
                     "evidence": ["the missing input is the only source of the quantity"], "bound": None,
                     "rejection": None})
    usable = [r for r in rows if r["rejection"] is None]
    chosen = usable[-1]["id"] if SCENARIO.get("descope") else (usable[0]["id"] if usable else None)
    for r in rows:
        if r["id"] != chosen and r["rejection"] is None:
            r["rejection"] = "another alternative was chosen"
    doc["recovery"] = {"failed_step": recovery["failed_step"], "chosen": chosen, "alternatives": rows,
                       "rationale": "Chosen from the staged inputs and the admitted operations of the run."}
    picked = next((r for r in rows if r["id"] == chosen), None)
    if picked is None:
        return doc
    if picked["kind"] == "descope":
        doc["steps"] = [s for s in doc["steps"] if s["id"] != "derive-value"]
        for row in doc["deliverables"]:
            row.update(status="held", outputs=[], held_reason="the required input is missing and no source recovers it")
        return doc
    artifact = picked["description"][len("Read the same quantity from "):-1]
    derive["id"] = "derive-value-recovered"
    derive["inputs"] = [r for r in derive["inputs"] if r.get("artifact") != SCENARIO.get("primary")] + [
        {"artifact": artifact}]
    for row in doc["deliverables"]:
        for target in row.get("outputs") or ():
            if target.get("step") == "derive-value":
                target["step"] = derive["id"]
    return doc
'''


def _worker(**scenario):
    """The wave-A inert worker with the recovery planner above (inserted before its entry point)."""
    marker = '\nif __name__ == "__main__":'
    assert wave_a.WORKER.count(marker) == 1
    planner = PLANNER.replace("__SCENARIO__", repr(json.dumps(scenario)))
    return wave_a.WORKER.replace(marker, "\n" + planner + marker)


def _recovery(store):
    return wave_a._records(store, "recovery")


def _diagnostic(store):
    """The recovery records and the judgment route's plan records (source and recovery block), for a failure."""
    plans = [{"source": r.get("source"), "recovery": (r.get("plan") or {}).get("recovery"),
              "rationale": (r.get("plan") or {}).get("rationale")}
             for r in wave_a._records(store, "judgment-plan")]
    return json.dumps({"recovery": _recovery(store), "plans": plans}, default=str)[:6000]


def _ending(store):
    endings = wave_a._records(store, "qualified-ending")
    assert endings, wave_a._where(store)
    return endings[-1]


def test_a_missing_input_with_a_supplied_alternative_recovers_and_is_accepted(tmp_path, monkeypatch):
    worker = _worker(primary=PRIMARY, alternatives=[RELEASE])
    root, store = autonomy._environment(tmp_path, monkeypatch, "--r3-delegation", "final_task", "--wait-bound", "0",
                                        worker=worker, supplied={"fictional-release.json": DATA},
                                        supplied_classification=_classification())
    try:
        observation, err = autonomy._drive(store)
        phases = [(r["phase"], r["step"]) for r in _recovery(store)]
        assert ("requested", "derive-value") in phases and ("adopted", "derive-value") in phases, \
            (phases, _diagnostic(store), wave_a._where(store))
        [proposed] = [r for r in _recovery(store) if r["phase"] == "proposed"]
        assert proposed["chosen"].startswith("source-") and {a["kind"] for a in proposed["alternatives"]} >= \
            {"source", "method"}
        assert all(a["rejection"] for a in proposed["alternatives"] if a["id"] != proposed["chosen"])
        deviations = [r for r in wave_a._records(store, "authority") if r["kind"] == "deviation"]
        assert deviations and deviations[-1]["label"] == "operator_configured_machine", deviations
        assert deviations[-1]["decision"] == "approve"
        outcomes = {r["step_id"]: r["status"] for r in wave_a._records(store, "step-outcome") if not r.get("seat")}
        assert outcomes.get("derive-value") == "held" and outcomes.get("derive-value-recovered") == "completed", \
            (outcomes, wave_a._where(store), [r.get("reason") for r in wave_a._records(store, "wave")])
        from ravel.controller import sink
        receipt = sink.receipt(store)
        assert receipt.get("accepted") is True, json.dumps({"unmet": wave_a._unmet(store, "deliver[accepted]"),
                                                            "labels": receipt.get("labels")}, default=str)
    finally:
        ledger_state.forget(store)


def test_without_an_alternative_the_rest_completes_and_the_ending_names_the_gap(tmp_path, monkeypatch):
    worker = _worker(primary=PRIMARY, alternatives=[RELEASE], cross_check=True)
    root, store = autonomy._environment(tmp_path, monkeypatch, "--wait-bound", "0", worker=worker)
    try:
        autonomy._drive(store)
        phases = [r["phase"] for r in _recovery(store)]
        assert phases[:2] == ["requested", "none"], (phases, _diagnostic(store))
        outcomes = {r["step_id"]: r["status"] for r in wave_a._records(store, "step-outcome") if not r.get("seat")}
        assert outcomes.get("cross-check") == "completed" and outcomes.get("derive-value") == "held", \
            (outcomes, wave_a._where(store))
        ending = _ending(store)
        assert "no alternative was found" in ending["reason"] and "derive-value" in ending["reason"], ending
        [gap] = ending["recovery"]
        assert gap["step"] == "derive-value" and gap["code"] == "run_input_missing"
        assert {a["id"] for a in gap["alternatives"]} >= {"method-other"}
        assert all(a["rejection"] for a in gap["alternatives"])
    finally:
        ledger_state.forget(store)


def test_a_provider_refusal_is_not_routed_to_recovery(tmp_path, monkeypatch):
    from ravel.controller.step import graph as step_graph
    from ravel.controller.step.services import StepHold
    original = step_graph._worker_preflight

    def refusing(state, *args, **kwargs):
        if state["step"]["id"] == "derive-value" and step_graph._seat(state) is None:
            raise StepHold("provider_policy_refused", "the project does not admit this worker family (fault injection)",
                           evidence={"not_dispatched": True})
        return original(state, *args, **kwargs)
    monkeypatch.setattr(step_graph, "_worker_preflight", refusing)
    root, store = autonomy._environment(tmp_path, monkeypatch, "--wait-bound", "0", worker=_worker())
    try:
        autonomy._drive(store)
        outcomes = {r["step_id"]: (r["status"], r.get("reason")) for r in wave_a._records(store, "step-outcome")
                    if not r.get("seat")}
        assert outcomes.get("derive-value") == ("held", "provider_policy_refused"), (outcomes, wave_a._where(store))
        assert _recovery(store) == []
        assert _ending(store)["recovery"] == []
    finally:
        ledger_state.forget(store)


def test_a_spent_recovery_budget_ends_qualified_naming_it(tmp_path, monkeypatch):
    worker = _worker(primary=PRIMARY, alternatives=[RELEASE])
    root, store = autonomy._environment(tmp_path, monkeypatch, "--wait-bound", "0", "--budget", "recoveries=0",
                                        worker=worker, supplied={"fictional-release.json": DATA},
                                        supplied_classification=_classification())
    try:
        autonomy._drive(store)
        assert [r["phase"] for r in _recovery(store)] == ["budget_exhausted"], wave_a._where(store)
        ending = _ending(store)
        assert "the recovery budget was exhausted" in ending["reason"], ending
        assert ending["recovery"][0]["outcome"] == "budget_exhausted"
    finally:
        ledger_state.forget(store)


def test_a_descope_waits_for_a_human_with_one_notification(tmp_path, monkeypatch):
    command, log = autonomy._notifier(Path(os.path.realpath(tmp_path)))
    worker = _worker(primary=PRIMARY, alternatives=[], cross_check=True, descope=True)
    root, store = autonomy._environment(tmp_path, monkeypatch, "--notify-command", command, "--wait-bound", "20",
                                        worker=worker)
    try:
        autonomy._drive(store, sleep=lambda seconds: time.sleep(min(seconds, 2.0)))
        proposed = [r for r in _recovery(store) if r["phase"] == "proposed"]
        assert len(proposed) == 1 and proposed[0]["chosen"] == "descope", _diagnostic(store)
        requests = [r for r in wave_a._records(store, "authority-request") if r["kind"] == "deviation"]
        assert requests and "changing scope" in requests[0]["reason"], requests
        assert not [r for r in wave_a._records(store, "authority") if r["kind"] == "deviation"
                    and r.get("label") == "operator_configured_machine"]
        lines = log.read_text().splitlines() if log.exists() else []
        assert [line for line in lines if "WAITING_FOR_HUMAN deviation" in line] == \
            [f"{store.run_id} | WAITING_FOR_HUMAN deviation"], lines
        assert all(len(line.split(" | ")) == 2 for line in lines), lines  # run name and state code only
        ending = _ending(store)
        assert "the recovery deviation was not approved" in ending["reason"], ending
    finally:
        ledger_state.forget(store)
