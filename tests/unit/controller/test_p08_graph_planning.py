"""``judgment.plan`` as the controller graph's planning subgraph (JR01-JR04, JR06, JR07, R10, A05).

The graph is invoked the way ``controller.run`` invokes it: a child invocation with the view
``{request, plan, context}`` whose ``results["plan"]`` is a controller ``plan.v1``.
"""
from pathlib import Path
import re

import pytest

from ravel.controller.judgment import control, recovery
from test_p08_fakes import (contract, invoke, judged, plan, reading, step,  # noqa: F401  (judged is a fixture)
                            Fixture, judgment_graph, passing_decision_gate)

JUDGMENT = Path(__file__).resolve().parents[3] / "src/ravel/controller/judgment"


def framed(fx, **kw):
    doc = fx.frame_doc(**kw)
    fx.steps.documents["judgment-frame-*"] = lambda s, c, x: {"outputs/question-frame.json": doc}
    return doc


def planned(fx, plan_doc, prefix="judgment-decompose-*"):
    fx.steps.documents[prefix] = lambda s, c, x: {"outputs/judgment-plan.json": plan_doc}


def test_JR01_unrecognised_request_reaches_frame_and_is_never_refused(judged):
    doc = framed(judged)
    planned(judged, plan(doc, [step("compute")]))
    result = invoke(judged, judged.view())
    first = judged.steps.calls[0]["step"]
    assert first["id"] == "judgment-frame-1" and first["kind"] == "author" and first["role"] == "coordinator"
    assert result["outcome"] == "ok" and result["results"]["plan"]["route"]["id"] == "judgment"
    assert [e["event"] for e in judged.events()][:2] == ["started", "frame"]
    assert judged.ledger.statuses("JR01") == {"JR01@run-judgment-fixture": "satisfied"}
    assert not any("refus" in str(t) for t in control.TERMINALS)


def test_R10_held_request_plans_recovery_and_keeps_its_scope_held(tmp_path, monkeypatch):
    fx = Fixture(tmp_path, reading_doc=reading(boundaries=[{"id": "RB1", "class": "no_scientific_object"}]),
                 contract_doc=contract(mode="unsupported"))
    boundary = {"id": "B1", "statement": "the request names no scientific object", "holds": ["D1"],
                "would_make_possible": "name the quantity to estimate", "reading_ref": "RB1"}
    with judgment_graph(), passing_decision_gate(monkeypatch), fx.installed():
        doc = framed(fx, boundaries=[boundary])
        planned(fx, recovery.seed_plan(doc))
        result = invoke(fx, fx.view())
    returned = result["results"]["plan"]
    assert result["outcome"] == "ok"
    assert [(d["id"], d["status"]) for d in returned["deliverables"]] == [("D1", "open")]
    assert returned["open_obligations"][0]["id"] == "D1"
    assert [s["kind"] for s in returned["steps"]] == ["ask", "synthesize"]
    assert fx.ledger.statuses("R10") == {"R10@run-judgment-fixture": "satisfied"}


def test_ROUTE_unsupported_frame_that_drops_the_held_boundary_is_refused(tmp_path, monkeypatch):
    fx = Fixture(tmp_path, reading_doc=reading(boundaries=[{"id": "RB1", "class": "inaccessible_input"}]))
    with judgment_graph(), passing_decision_gate(monkeypatch), fx.installed():
        framed(fx)
        result = invoke(fx, fx.view())
    assert result["outcome"] == "held" and "frame rounds exhausted" in result["status"]["reason"]
    assert [e["status"] for e in fx.events("frame")] == ["refused", "refused"]
    assert all(any("boundary RB1" in p for p in e["problems"]) for e in fx.events("frame"))


def test_JR02_frame_without_a_reading_deliverable_is_refused_and_bounded(judged):
    framed(judged, deliverables=[])
    result = invoke(judged, judged.view())
    assert result["outcome"] == "held" and result["status"]["reason"].startswith("judgment_planning_held")
    assert len(judged.events("frame")) == 2 and judged.events("plan") == []
    assert "satisfied" not in judged.ledger.statuses("JR02").values()


def test_JR02_frame_review_revises_within_two_rounds_then_carries_findings(judged):
    framed(judged)
    judged.steps.reviews["judgment-frame-review-*"] = {"credited": True, "verdict": "revise"}
    planned(judged, plan(judged.frame_doc(), [step("compute")]))
    result = invoke(judged, judged.view())
    assert result["outcome"] == "ok"
    assert [e["verdict"] for e in judged.events("frame_review")] == ["revise", "revise"]
    assert [e["round"] for e in judged.events("frame")] == [1, 2]


def test_JR02_frame_the_critic_fails_is_never_admitted_at_the_round_bound(judged):
    framed(judged)
    judged.steps.reviews["judgment-frame-review-*"] = {"credited": True, "verdict": "reject"}
    planned(judged, plan(judged.frame_doc(), [step("compute")]))
    result = invoke(judged, judged.view())
    assert result["outcome"] == "held" and "frame rounds exhausted" in result["status"]["reason"]
    assert [e["verdict"] for e in judged.events("frame_review")] == ["fail", "fail"]
    assert judged.events("plan") == []


def test_JR02_frame_findings_carried_past_the_bound_reach_the_returned_plan(judged):
    judged.steps.documents["judgment-frame-review-*"] = lambda s, c, x: {
        "final-record.json": {"findings": [{"text": "state the threshold range of the acceptance criterion"}]}}
    framed(judged)
    judged.steps.reviews["judgment-frame-review-*"] = {"credited": True, "verdict": "revise"}
    planned(judged, plan(judged.frame_doc(), [step("compute")]))
    result = invoke(judged, judged.view())
    assert result["outcome"] == "ok"
    carried = result["results"]["plan"]["parameters"]["judgment"]["frame_findings"]
    assert carried == [{"text": "state the threshold range of the acceptance criterion"}]


def test_JR02_uncredited_frame_review_cannot_admit_a_frame(judged):
    framed(judged)
    judged.steps.reviews["judgment-frame-review-*"] = {"credited": False, "verdict": "accept"}
    result = invoke(judged, judged.view())
    assert result["outcome"] == "held" and "could not be credited" in result["status"]["reason"]
    assert judged.events("plan") == []


def test_JR03_decomposition_outside_the_closed_vocabulary_is_refused(judged):
    doc = framed(judged)
    bad = plan(doc, [step("compute")])
    bad["steps"][0]["kind"] = "freeform"
    planned(judged, bad)
    result = invoke(judged, judged.view())
    assert result["outcome"] == "held"
    assert [e["status"] for e in judged.events("plan")] == ["refused", "refused"]
    assert "satisfied" not in judged.ledger.statuses("JR03").values()


def test_JR04_planner_that_tries_to_execute_inline_runs_nothing(judged):
    doc = framed(judged)
    bad = plan(doc, [step("compute")])
    bad["steps"][0]["argv"] = ["sh", "-c", "touch executed"]
    planned(judged, bad)
    result = invoke(judged, judged.view())
    assert result["outcome"] == "held"
    assert {c["step"]["kind"] for c in judged.steps.calls} <= {"author", "review"}
    assert not list(Path(judged.run_dir).rglob("executed"))
    assert all("governed step graph" in e["problems"][0] for e in judged.events("plan"))


def test_JR04_every_planning_step_is_bound_to_a_plan_for_the_governed_step(judged):
    doc = framed(judged)
    planned(judged, plan(doc, [step("compute")]))
    invoke(judged, judged.view())
    bound = {r["plan_sha256"] for r in judged.store.records("plan")}
    assert judged.steps.calls and all(c["context"]["plan_sha256"] in bound for c in judged.steps.calls)
    assert {r["source"] for r in judged.store.records("plan")} == {"judgment-planning"}


def test_JR04_the_judgment_package_has_no_execution_path_of_its_own():
    forbidden = re.compile(r"\bsubprocess\b|\bPopen\b|os\.system|authorized_popen|confine\.popen|agent_worker|"
                           r"execute_graph|research_cycle|cli_worker")
    for path in sorted(JUDGMENT.glob("*.py")):
        assert not forbidden.search(path.read_text()), path.name


def test_JR06_A05_planner_R1_on_an_R3_call_is_recomputed_in_the_returned_plan(judged):
    doc = framed(judged)
    call = step("pick", "decide", question="Which reading of the ambiguity?", declared_class="R1",
                action={"summary": "resolve a physics-critical ambiguity", "kind": "physics_critical_ambiguity"},
                outputs=[{"path": "outputs/judgment-record.json", "kind": "judgment-record", "required": True}])
    planned(judged, plan(doc, [call, step("compute", depends_on=["pick"])]))
    result = invoke(judged, judged.view())
    steps = {s["id"]: s for s in result["results"]["plan"]["steps"]}
    assert steps["pick"]["consequence_class"] == "R3"
    assert steps["pick"]["parameters"]["judgment"]["requirement"] == "authority"
    classified = judged.events("classified")[-1]
    assert classified["calls"]["pick"]["declared_lower"] is True
    assert any("computed class applies" in e["text"] for e in judged.events("flag"))
    assert judged.ledger.statuses("A05") == {"A05@run-judgment-fixture": "satisfied"}


def test_JR06_R2_effect_gets_its_RDJ_case_before_the_plan_returns(judged):
    doc = framed(judged)
    planned(judged, plan(doc, [step("run", "operate", operation="literal-calculation", rung="full")]))
    result = invoke(judged, judged.view())
    ids = judged.steps.ids()
    assert any(i.startswith("judgment-rdj-run-") for i in ids)
    assert result["results"]["plan"]["parameters"]["judgment"]["rdj"]["run"]
    assert result["results"]["plan"]["steps"][0]["consequence_class"] == "R2"


def test_JR06_uncredited_RDJ_case_holds_the_planning(judged):
    doc = framed(judged)
    planned(judged, plan(doc, [step("run", "operate", operation="literal-calculation", rung="scan")]))
    judged.steps.reviews["judgment-rdj-*"] = {"credited": False, "verdict": "reject"}
    result = invoke(judged, judged.view())
    assert result["outcome"] == "held" and "RDJ case" in result["status"]["reason"]
    assert len([i for i in judged.steps.ids() if i.startswith("judgment-rdj-")]) == 2


def test_planning_is_idempotent_per_revision_and_redecomposes_on_request(judged):
    doc = framed(judged)
    planned(judged, plan(doc, [step("compute")]))
    first = invoke(judged, judged.view())["results"]["plan"]
    runs = len(judged.steps.calls)
    again = invoke(judged, judged.view())["results"]["plan"]
    assert again == first and len(judged.steps.calls) == runs
    revised = invoke(judged, judged.view(revision=1, plan=first))["results"]["plan"]
    assert "judgment-decompose-r1-1" in judged.steps.ids() and revised["revision"] == 1


def test_JR07_replan_bound_ends_the_planning_in_a_typed_hold(judged):
    judged.mode = {"mode": "autonomous", "bounds": {"replans": 1}}
    doc = framed(judged)
    planned(judged, plan(doc, [step("compute")]))
    first = invoke(judged, judged.view())["results"]["plan"]
    planned(judged, plan(doc, [step("compute"), step("check", depends_on=["compute"])]), "judgment-replan-*")
    second = invoke(judged, judged.view(purpose="replan", revision=1, plan=first, replan_requests={}))
    assert second["outcome"] == "ok"
    third = invoke(judged, judged.view(purpose="replan", revision=2, plan=second["results"]["plan"]))
    assert third["outcome"] == "held" and "replan bound" in third["status"]["reason"]


def test_JR07_replan_must_cover_a_failed_step_with_a_stage_recovery_decision(judged):
    doc = framed(judged)
    planned(judged, plan(doc, [step("generate")]))
    first = invoke(judged, judged.view())["results"]["plan"]
    planned(judged, plan(doc, [step("generate")]), "judgment-replan-*")
    result = invoke(judged, judged.view(purpose="replan", revision=1, plan=first,
                                        steps={"generate": {"status": "failed", "attempts": 1}}))
    assert result["outcome"] == "held"
    assert all(any("stage-recovery decision" in p for p in e["problems"]) for e in judged.events("plan")
               if e["source"] == "replan")


def test_scope_change_of_a_replan_is_declared_for_renewed_authority(judged):
    doc = framed(judged)
    planned(judged, plan(doc, [step("compute")]))
    first = invoke(judged, judged.view())["results"]["plan"]
    planned(judged, plan(doc, [step("compute")], deliverables=[
        {"id": "D1", "status": "held", "outputs": [], "held_reason": "an input became unavailable"}]),
        "judgment-replan-*")
    result = invoke(judged, judged.view(purpose="replan", revision=1, plan=first))
    changes = result["results"]["plan"]["parameters"]["judgment"]["scope_changes"]
    assert changes == [{"kind": "deliverable_dropped", "deliverable": "D1", "detail": "newly held"}]


def test_stop_requested_ends_the_planning_without_a_plan(judged):
    judged.authority.stop = "stop_requested"
    result = invoke(judged, judged.view())
    assert result["outcome"] == "held" and "stop" in result["status"]["reason"] and judged.steps.calls == []


PREFERENCES = {"schema_version": 1, "kind": "agent-preferences",
               "transport_preference": ["ravel-loop-local", "claude-cli-worker"]}


@pytest.mark.parametrize("preferences", [PREFERENCES, None], ids=["frozen", "absent"])
def test_every_planning_seat_carries_the_runs_frozen_agent_preferences(judged, preferences):
    # The controller passes the run's frozen agent preferences in the child context; every judgment seat's context
    # carries them unchanged, and absent preferences stay None (the governed step then holds the seat).
    doc = framed(judged)
    planned(judged, plan(doc, [step("compute")]))
    invoke(judged, judged.view(agent_preferences=preferences))
    assert judged.steps.calls
    assert all(c["context"]["agent_preferences"] == preferences for c in judged.steps.calls)


@pytest.mark.parametrize("purpose", ["plan", "replan", "route"])
def test_every_purpose_is_known_to_the_control(purpose):
    assert purpose in control.PURPOSES


def test_pass_bound_ends_the_planning_in_a_typed_hold_never_a_refusal(judged, monkeypatch):
    from ravel.controller.judgment import graph
    monkeypatch.setattr(graph, "MAX_PASSES", 2)
    framed(judged)
    result = invoke(judged, judged.view())
    assert result["outcome"] == "held" and "bound was reached" in result["status"]["reason"]
    assert judged.sink.calls == []
