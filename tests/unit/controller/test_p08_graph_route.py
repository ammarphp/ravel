"""``judgment.plan`` driving the whole judgment route (purpose ``route``; CONTROLLER-SPEC 6.2).

Scripted planner, workers and authority; the governed step, ledger, authority service and sink
are fakes with the published shapes. Covers JR04-JR09, E03, E12, GATE-failed_stage_feedback, the
budget envelope and stop.
"""
from contextlib import ExitStack
from copy import deepcopy

import pytest

from ravel.workflow import decision_gate, graph_nodes
from ravel.controller.judgment import services
from test_p08_fakes import (Fixture, contract, invoke, judgment_graph, p7, passing_decision_gate, plan, record,
                            step)

RECORD = [{"path": "outputs/judgment-record.json", "kind": "judgment-record", "required": True}]
REAL_CHECK, REAL_PROVIDERS = decision_gate.check, decision_gate.providers


def attacks(step_, context, fixture, axes=("basis", "acceptance", "statistics")):
    subject = step_["parameters"]["judgment"]["subject"]
    return {"outputs/judgment-attacks.json": {
        "schema_version": 1, "kind": "judgment-attacks",
        "subject": {"plan_sha256": subject["plan_sha256"], "draft_sha256": subject["sha256"]},
        "attacks": [{"axis": a, "attack": f"{a} attack", "test": f"{a} test", "outcome": "survives",
                     "evidence": ["a located observation"]} for a in axes]}}


def generic(step_, context, fixture):
    return {o["path"]: {"step": step_["id"], "attempt": context["attempt"]} for o in step_["outputs"]}


@pytest.fixture
def route(tmp_path, monkeypatch):
    fixture = Fixture(tmp_path, purpose="route")
    fixture.monkeypatch = monkeypatch
    with ExitStack() as stack:
        stack.enter_context(judgment_graph())
        stack.enter_context(passing_decision_gate(monkeypatch))
        stack.enter_context(fixture.installed())
        yield fixture


def script(fx, steps_, *, deliverables=None, frame_kw=None, writers=None, replans=None):
    doc = fx.frame_doc(**(frame_kw or {}))
    fx.steps.documents["judgment-frame-*"] = lambda s, c, x: {"outputs/question-frame.json": doc}
    fx.steps.documents["judgment-decompose-*"] = lambda s, c, x: {"outputs/judgment-plan.json":
                                                                plan(doc, steps_, deliverables)}
    for index, replanned in enumerate(replans or []):
        fx.steps.documents[f"judgment-replan-{index + 1}"] = (lambda value: lambda s, c, x: {
            "outputs/judgment-plan.json": value})(replanned(doc))
    fx.steps.documents["judgment-attack-*"] = attacks
    for key, writer in (writers or {}).items():
        fx.steps.documents[key] = writer
    fx.steps.documents["*"] = generic
    fx.authority.script(final="accept")
    return doc


def events(fx):
    return [e["event"] for e in fx.events()]


def ended(fx):
    rows = fx.events("bounded_end")
    return rows[-1]["reason"] if rows else None


def test_route_delivers_through_the_sole_sink_after_every_review_and_gate(route):
    choose = step("choose", "decide", outputs=RECORD, question="Which method?",
                  action={"summary": "method", "kind": "method_choice"})
    script(route, [choose, step("run", "operate", operation="literal-calculation", rung="full", depends_on=["choose"]),
                   step("report", "synthesize", depends_on=["run"])],
           writers={"choose": lambda s, c, x: {"outputs/judgment-record.json": record("choose", kind="method_choice")}})
    result = invoke(route, route.view())
    assert result["results"]["judgment"]["outcome"] == "delivered"
    assert [c[0] for c in route.sink.calls] == ["deliver"]
    order = events(route)
    assert order.index("plan_review") < order.index("checkin1") < order.index("attacks") < order.index("final_review")
    assert order.index("final_review") < order.index("checkin3") < order.index("delivered")
    ids = route.steps.ids()
    assert ids.index("judgment-rdj-run-0-1") < ids.index("run")
    assert ids.index("judgment-rdj-choose-record-1") < ids.index("run")
    assert [k for k, _ in route.authority.calls] == ["approve_plan", "final"]
    assert route.ledger.statuses("JR09") == {"JR09@run-judgment-fixture": "satisfied"}
    assert route.ledger.statuses("JR05") == {"JR05@run-judgment-fixture/step=choose": "satisfied"}


def test_JR04_every_plan_step_runs_through_the_governed_step_bound_to_the_approved_plan(route):
    script(route, [step("prepare"), step("report", "synthesize", depends_on=["prepare"])])
    invoke(route, route.view())
    approved = [r for r in route.store.records("plan") if r["source"] == "judgment-route"]
    # One approved plan; it is pinned again after each planning phase that runs while it executes, so it stays
    # the store's latest plan and the ledger's current plan.
    assert len({r["plan_sha256"] for r in approved}) == 1
    assert route.store.records("plan")[-1]["plan_sha256"] == approved[0]["plan_sha256"]
    executed = [c for c in route.steps.calls if c["step"]["id"] in ("prepare", "report")]
    assert executed and all(c["context"]["plan_sha256"] == approved[0]["plan_sha256"] for c in executed)
    assert set(route.ledger.statuses("JR04")) == {"JR04@run-judgment-fixture/step=prepare",
                                                  "JR04@run-judgment-fixture/step=report"}


def test_JR05_decision_without_a_record_is_refused_and_its_dependents_never_run(route):
    script(route, [step("choose", "decide", outputs=RECORD, question="Which method?",
                        action={"summary": "method", "kind": "method_choice"}),
                   step("report", "synthesize", depends_on=["choose"])],
           writers={"choose": lambda s, c, x: {}})
    invoke(route, route.view())
    assert "report" not in route.steps.ids() and route.steps.ids().count("choose") == 2
    assert len(route.events("record_refused")) == 2
    assert "no branch can proceed" in ended(route)
    assert route.ledger.statuses("JR05") == {"JR05@run-judgment-fixture/step=choose": "violated"}
    assert [c[0] for c in route.sink.calls] == ["bounded_end"]


def test_E28_judgment_step_below_the_judgment_tier_is_not_credited(route):
    script(route, [step("choose", "decide", outputs=RECORD, question="Which method?",
                        action={"summary": "method", "kind": "plot_style"}),
                   step("report", "synthesize", depends_on=["choose"])],
           writers={"choose": lambda s, c, x: {"outputs/judgment-record.json": record("choose")}})
    route.steps.statuses["choose"] = lambda s, c, x: {**_completed(s, c, x, {"outputs/judgment-record.json":
                                                                           record("choose")}), "tier": "agent"}
    invoke(route, route.view())
    assert "report" not in route.steps.ids()
    assert all("judgment tier" in e["problems"][0] for e in route.events("record_refused"))
    assert route.ledger.statuses("E28") == {"E28@run-judgment-fixture/step=choose": "violated"}


def _completed(step_, context, fixture, documents):
    """A completed governed-step outcome with adopted documents (for outcome overrides)."""
    from test_p08_fakes import outcome, sha
    import json
    from pathlib import Path
    outputs = []
    for path, document in documents.items():
        raw = (json.dumps(document, sort_keys=True) + "\n").encode()
        target = Path(context["run_dir"]) / "steps" / step_["id"] / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        outputs.append({"artifact": f"{step_['id']}:{path}", "path": path, "sha256": sha(raw)})
    return outcome(step_, context["attempt"], outputs=outputs)


def test_JR06_R3_decision_waits_for_authority_before_its_dependents(route):
    script(route, [step("choose", "decide", outputs=RECORD, question="Which reading?",
                        action={"summary": "ambiguity", "kind": "physics_critical_ambiguity"}),
                   step("report", "synthesize", depends_on=["choose"])],
           writers={"choose": lambda s, c, x: {"outputs/judgment-record.json":
                                              record("choose", kind="physics_critical_ambiguity", declared="R1")}})
    route.authority.script(r3_action=("approve", "a"))
    result = invoke(route, route.view())
    assert result["results"]["judgment"]["outcome"] == "delivered"
    kinds = [k for k, _ in route.authority.calls]
    assert kinds.index("r3_action") < kinds.index("final")
    ids = route.steps.ids()
    assert ids.index("judgment-rdj-choose-record-1") < ids.index("report")
    assert route.events("record")[0]["class"] == "R3"


def test_JR06_declined_R3_decision_holds_its_branch(route):
    script(route, [step("choose", "decide", outputs=RECORD, question="Which reading?",
                        action={"summary": "ambiguity", "kind": "physics_critical_ambiguity"}),
                   step("report", "synthesize", depends_on=["choose"])],
           writers={"choose": lambda s, c, x: {"outputs/judgment-record.json":
                                              record("choose", kind="physics_critical_ambiguity")}})
    route.authority.script(r3_action="reject")
    invoke(route, route.view())
    assert "report" not in route.steps.ids() and "no branch can proceed" in ended(route)


def ask_step(default=None):
    row = step("ask-range", "ask", question="Which threshold range?",
               options=[{"id": "narrow", "description": "the narrow range"},
                        {"id": "wide", "description": "the wide range"}],
               outputs=[{"path": "outputs/answer.json", "kind": "operator-answer", "required": True}])
    if default is not None:
        row.update(default=p7(), default_option=default)
    return row


def two_branches(route, ask):
    script(route, [ask, step("use-answer", depends_on=["ask-range"]), step("other"),
                   step("report", "synthesize", depends_on=["use-answer", "other"])])


def test_JR08_unanswered_ask_in_unattended_mode_takes_the_recorded_default_and_others_continue(route):
    route.authority.wait_bound = 600
    route.authority.script(escalation="pending")
    two_branches(route, ask_step(default="narrow"))
    result = invoke(route, route.view())
    assert result["results"]["judgment"]["outcome"] == "delivered"
    answers = route.events("authority")
    assert answers[0]["state"] == "pending" and answers[-1]["state"] == "defaulted"
    assert answers[-1]["answer"] == "narrow"
    ids = route.steps.ids()
    pending_at = [i for i, e in enumerate(route.events()) if e["event"] == "authority" and e["state"] == "pending"][0]
    other_at = [i for i, e in enumerate(route.events()) if e["event"] == "step" and e["step"] == "other"][0]
    assert pending_at < other_at and ids.index("other") < ids.index("use-answer")
    assert route.clock["now"] >= 1000.0 + 600
    assert route.ledger.statuses("JR08") == {"JR08@run-judgment-fixture": "satisfied"}


def test_JR08_unanswered_ask_without_a_default_holds_only_its_branch(route):
    route.authority.wait_bound = 600
    route.authority.script(escalation="pending")
    two_branches(route, ask_step())
    invoke(route, route.view())
    assert route.events("authority")[-1]["state"] == "held"
    assert "other" in route.steps.ids() and "use-answer" not in route.steps.ids()
    assert "no branch can proceed" in ended(route)
    assert [c[0] for c in route.sink.calls] == ["bounded_end"]


def r3_effect(route):
    script(route, [step("open-region", "operate", operation="literal-calculation",
                        action={"summary": "open the fictional signal region", "kind": "unblinding"}),
                   step("report", "synthesize", depends_on=["open-region"])])


def test_JR08_R3_effect_whose_conservative_default_declines_never_runs(route):
    route.authority.wait_bound = 600
    route.authority.script(r3_action="pending")
    r3_effect(route)
    invoke(route, route.view())
    answers = [e for e in route.events("authority") if e["step"] == "open-region"]
    assert answers[-1]["state"] == "defaulted" and answers[-1]["answer"] == "decline"
    assert "open-region" not in route.steps.ids() and "report" not in route.steps.ids()
    assert "no branch can proceed" in ended(route) and [c[0] for c in route.sink.calls] == ["bounded_end"]


def test_JR06_declined_R3_effect_holds_its_branch_without_asking_again(route):
    route.authority.script(r3_action="reject")
    r3_effect(route)
    invoke(route, route.view())
    assert [k for k, _ in route.authority.calls].count("r3_action") == 1
    assert "open-region" not in route.steps.ids() and "no branch can proceed" in ended(route)


def test_JR06_granted_R3_effect_runs_after_its_authority(route):
    route.authority.script(r3_action=("approve", "authorize"))
    r3_effect(route)
    result = invoke(route, route.view())
    assert result["results"]["judgment"]["outcome"] == "delivered"
    kinds = [k for k, _ in route.authority.calls]
    assert kinds.index("r3_action") < kinds.index("final") and "open-region" in route.steps.ids()


def r3_decision_with_default(route, default_option):
    route.authority.wait_bound = 600
    route.authority.script(r3_action="pending")
    script(route, [step("choose", "decide", outputs=RECORD, question="Which reading?",
                        action={"summary": "ambiguity", "kind": "physics_critical_ambiguity"}),
                   step("report", "synthesize", depends_on=["choose"])],
           writers={"choose": lambda s, c, x: {"outputs/judgment-record.json": record(
               "choose", kind="physics_critical_ambiguity", default=p7(), default_option=default_option)}})
    return invoke(route, route.view())


def test_JR08_default_that_overturns_the_recorded_choice_holds_the_branch(route):
    r3_decision_with_default(route, "b")
    assert route.events("authority")[-1]["state"] == "defaulted" and route.events("authority")[-1]["answer"] == "b"
    assert "report" not in route.steps.ids() and "no branch can proceed" in ended(route)
    from ravel.controller.judgment import records
    assert list(records.outcomes(route.store).values()) == ["overturned"]


def test_JR08_default_that_is_the_recorded_choice_closes_the_decision(route):
    result = r3_decision_with_default(route, "a")
    assert result["results"]["judgment"]["outcome"] == "delivered" and "report" in route.steps.ids()
    from ravel.controller.judgment import records
    assert list(records.outcomes(route.store).values()) == ["confirmed"]


def test_stop_reaches_a_run_that_waits_for_an_answer(route):
    route.authority.wait_bound = 3600
    route.authority.script(escalation="pending")
    two_branches(route, ask_step())

    def sleep_then_stop(seconds):
        route.clock["now"] += seconds
        route.authority.stop = "stop_requested"
    with services.overridden(sleep=sleep_then_stop):
        invoke(route, route.view())
    assert ended(route) == "stop: stop_requested" and route.clock["now"] < 1000.0 + 3600
    assert "use-answer" not in route.steps.ids()


def test_JR07_scope_changing_replan_needs_renewed_authority(route):
    held = lambda doc: plan(doc, [step("other"), step("report", "synthesize", depends_on=["other"])],  # noqa: E731
                            deliverables=[{"id": "D1", "status": "held", "outputs": [],
                                           "held_reason": "the generator failed; the deliverable is held"}])
    script(route, [step("generate"), step("report", "synthesize", depends_on=["generate"])], replans=[held])
    route.steps.statuses["generate"] = "failed"
    invoke(route, route.view())
    kinds = [k for k, _ in route.authority.calls]
    assert "deviation" in kinds and kinds.index("deviation") < kinds.index("final")
    deviation = [s for k, s in route.authority.calls if k == "deviation"][0]
    assert deviation["change"]["direction"] == "scope" and deviation["change"]["touches"] == ["D1"]
    assert any(e["gate"] == "deviation" and e["passed"] for e in route.events("gate"))


def test_JR07_declined_scope_change_is_not_adopted(route):
    held = lambda doc: plan(doc, [step("other")], deliverables=[  # noqa: E731
        {"id": "D1", "status": "held", "outputs": [], "held_reason": "held"}])
    script(route, [step("generate"), step("report", "synthesize", depends_on=["generate"])], replans=[held, held])
    route.steps.statuses["generate"] = "failed"
    route.authority.script(deviation="reject")
    invoke(route, route.view())
    assert not any(e["gate"] == "deviation" for e in route.events("gate"))
    assert "replan" in ended(route) and [c[0] for c in route.sink.calls] == ["bounded_end"]


def test_JR07_replan_past_its_bound_ends_in_a_qualified_delivery(route):
    route.mode = {"mode": "autonomous", "bounds": {"replans": 2}}
    again = lambda doc: plan(doc, [step("generate-again"),  # noqa: E731
                                   step("report", "synthesize", depends_on=["generate-again"])])
    script(route, [step("generate"), step("report", "synthesize", depends_on=["generate"])],
           replans=[again, again, again])
    route.steps.statuses["generate"] = "failed"
    route.steps.statuses["generate-again"] = "failed"
    invoke(route, route.view())
    assert len(route.events("replan")) == 2 and "replan bound" in ended(route)
    assert route.sink.calls[-1][0] == "bounded_end"
    assert route.ledger.statuses("JR07")["JR07@run-judgment-fixture"] == "satisfied"


def test_JR09_delivery_without_the_three_attacks_is_refused(route):
    script(route, [step("report", "synthesize")],
           writers={"judgment-attack-*": lambda s, c, x: attacks(s, c, x, axes=("basis", "statistics", "basis"))})
    invoke(route, route.view())
    assert route.events("attacks")[0]["status"] == "invalid"
    assert route.events("final_review") == [] and route.events("checkin3") == []
    assert "attacks are missing or incomplete" in ended(route)
    assert [c[0] for c in route.sink.calls] == ["bounded_end"]
    assert route.ledger.statuses("JR09") == {"JR09@run-judgment-fixture": "violated"}


def test_JR09_attacks_precede_the_fresh_triad_and_become_its_must_check_items(route):
    script(route, [step("report", "synthesize")])
    invoke(route, route.view())
    finals = [c["step"] for c in route.steps.calls if c["step"]["id"].startswith("judgment-final-")]
    assert sorted(s["role"] for s in finals) == ["physics-critic", "physics-decider", "skeptical-verifier"]
    for seat in finals:
        axes = [m["id"] for m in seat["parameters"]["judgment"]["must_check"]]
        assert axes == ["JR09:basis", "JR09:acceptance", "JR09:statistics"]
    attack = [c["step"] for c in route.steps.calls if c["step"]["id"].startswith("judgment-attack-")][0]
    assert "coordinator" in attack["parameters"]["judgment"]["distinct_actor_from"]


def recovery_evidence():
    return {"failure": {"step": "generate", "summary": "the fictional generator wrote no events"},
            "local_diagnosis": {"summary": "an undecayed state empties the selection", "evidence": ["log excerpt"]},
            "recipe_search": {"path": "inputs/recipe_search.json", "sha256": "a" * 64, "hits": 2},
            "diagnosis_class": "generator_model"}


def recovery_plan(doc):
    recover = step("recover", "decide", outputs=RECORD, question="Why did the generator fail?",
                   resolves=["failure:generate"], triggers=["stage_recovery"],
                   action={"summary": "stage recovery", "kind": "stage_recovery"})
    return plan(doc, [recover, step("generate", depends_on=["recover"]),
                      step("report", "synthesize", depends_on=["generate"])])


def failing_then_recovering(route, *, epoch=2):
    route.contract = contract(epoch=epoch)
    import json
    route.pins["contract_sha256"] = route.store.put_blob(json.dumps(route.contract).encode())
    script(route, [step("generate"), step("report", "synthesize", depends_on=["generate"])],
           replans=[recovery_plan],
           writers={"recover": lambda s, c, x: {"outputs/judgment-record.json": record(
               "recover", kind="stage_recovery", evidence={"recovery": recovery_evidence()})}})
    attempts = {"n": 0}

    def generate(step_, context, fixture):
        attempts["n"] += 1
        return "failed" if attempts["n"] == 1 else None
    route.steps.statuses["generate"] = generate


def test_E12_GATE_failed_stage_feedback_recovery_passes_its_gate_and_the_retry_runs(route):
    failing_then_recovering(route)
    result = invoke(route, route.view())
    assert result["results"]["judgment"]["outcome"] == "delivered"
    gate = [e for e in route.events("gate") if e["gate"] == "failed_stage_feedback"]
    assert gate and gate[0]["passed"] and gate[0]["transition"] == "checkin1→execute"
    assert route.steps.ids().count("generate") == 2
    assert route.ledger.statuses("GATE-failed_stage_feedback") == {
        "GATE-failed_stage_feedback@run-judgment-fixture": "satisfied"}


def test_GATE_failed_stage_feedback_refuses_an_epoch_one_layout(route):
    failing_then_recovering(route, epoch=1)
    invoke(route, route.view())
    gate = [e for e in route.events("gate") if e["gate"] == "failed_stage_feedback"][0]
    assert not gate["passed"] and "epoch_one_layout_refused" in [e["code"] for e in gate["errors"]]
    assert route.steps.ids().count("generate") == 1
    assert "satisfied" not in route.ledger.statuses("GATE-failed_stage_feedback").values()


def recovery_gate(route):
    """The recovery gate node over the recorded stage-recovery decision of a completed run."""
    from ravel.controller.judgment import graph, records
    from test_p08_fakes import RUN_ID
    failing_then_recovering(route)
    invoke(route, route.view())
    subject = records.for_step(route.store, "recover")[-1]["record_sha256"]
    state = {"meta": {"graph_id": "judgment.plan", "version": 1, "instance": {"run_id": RUN_ID},
                      "scope_root": str(route.tmp / "scope"), "path": None},
             "request": dict(route.pins), "context": route.view()["context"],
             "decision": {"phase": "gate", "reason": "fixture", "detail": {
                 "gate": "failed_stage_feedback", "subject_sha256": subject, "transition": "checkin1→execute"}}}
    node = graph._gate_node("failed_stage_feedback")
    return lambda: node.function(state)["gates"]["failed_stage_feedback"]["errors"]


def test_GATE_failed_stage_feedback_refuses_a_context_variable_gate_override(route):
    decide = recovery_gate(route)
    assert decide() == []
    route.monkeypatch.setattr(services, "seams_enabled", lambda: False)
    token = graph_nodes.GATE_CHECK.set(lambda rundir, gate, action: [])
    try:
        errors = decide()
    finally:
        graph_nodes.GATE_CHECK.reset(token)
    assert "gate_seam_refused" in [e["code"] for e in errors]


def test_GATE_failed_stage_feedback_refuses_when_a_required_provider_is_removed(route):
    decide = recovery_gate(route)
    assert decide() == []
    registry = decision_gate._registry()
    registry["providers"] = [p for p in registry["providers"] if p["id"] not in ("review_points", "rdj")]
    route.monkeypatch.setattr(decision_gate, "_registry", lambda: deepcopy(registry))
    route.monkeypatch.setattr(decision_gate, "_facts", lambda rundir: {"agent_layer_epoch": 2})
    route.monkeypatch.setattr(decision_gate, "check", REAL_CHECK)
    route.monkeypatch.setattr(decision_gate, "providers", REAL_PROVIDERS)
    inactive = {e["provider"] for e in decide() if e["code"] == "provider_inactive"}
    assert {"review_points", "rdj"} <= inactive


def test_GATE_failed_stage_feedback_refuses_feedback_without_a_recorded_decision(route):
    from ravel.controller.judgment import graph
    recovery_gate(route)
    errors = graph.recovery_errors(route.store, contract(), "f" * 64)
    assert [e["code"] for e in errors] == ["recovery_record_missing"]


def test_E12_recovery_without_the_recipe_search_is_refused_and_the_failure_stays_open(route):
    failing_then_recovering(route)
    evidence = recovery_evidence()
    evidence.pop("recipe_search")
    route.steps.documents["recover"] = lambda s, c, x: {"outputs/judgment-record.json": record(
        "recover", kind="stage_recovery", evidence={"recovery": evidence})}
    invoke(route, route.view())
    assert route.events("gate") and not any(e["gate"] == "failed_stage_feedback" for e in route.events("gate"))
    assert all("recipe_search" in " ".join(e["problems"]) for e in route.events("record_refused"))
    assert route.steps.ids().count("generate") == 1


def unavailable(statuses):
    names = {1: "publication", 2: "data_record", 3: "public_code", 4: "recast_database", 5: "citing_work"}
    return {"protocol_evidence": {"P6": {"claim": "unavailable", "census": None, "rungs": [
        {"rung": n, "name": names[n], "status": statuses.get(n, "ABSENT"), "evidence": f"rung {n}", "reason": None}
        for n in sorted(names)]}}}


def acquire_plan():
    return [step("fetch", "acquire", triggers=["resource_unavailable"], protocols=["P6"],
                 outputs=[{"path": "outputs/evidence.json", "kind": "protocol-evidence", "required": True}]),
            step("report", "synthesize", depends_on=["fetch"])]


def test_E03_resource_unavailable_after_the_ladder_holds_its_branch_and_asks_by_replanning(route):
    route.mode = {"mode": "autonomous", "bounds": {"replans": 0}}
    script(route, acquire_plan(), writers={"fetch": lambda s, c, x: {"outputs/evidence.json": unavailable({})}})
    invoke(route, route.view())
    states = route.events("step_state")
    assert states[0]["status"] == "held" and "source-ladder" in states[0]["reason"]
    assert route.events("wave_review")[0]["replan_request"]["reason"] == "resource_unavailable"
    assert "replan bound" in ended(route)


def test_E03_unavailable_claim_with_an_outage_rung_is_not_absence(route):
    script(route, acquire_plan(), writers={"fetch": lambda s, c, x: {"outputs/evidence.json": unavailable({2: "ERROR"})}})
    invoke(route, route.view())
    assert [e["status"] for e in route.events("step_state")] == ["retry", "violated"]
    assert "outage" in route.events("step_state")[0]["reason"]


def test_budget_exhausted_mid_wave_ends_in_a_qualified_delivery(route):
    script(route, [step("prepare"), step("other"), step("report", "synthesize", depends_on=["prepare", "other"])])
    route.steps.statuses["other"] = "budget_exhausted"
    invoke(route, route.view())
    assert "budget was exhausted" in ended(route) and [c[0] for c in route.sink.calls] == ["bounded_end"]


def test_stop_drains_to_a_qualified_ending_before_any_further_effect(route):
    script(route, [step("prepare")])
    route.authority.stop = "stop_requested"
    invoke(route, route.view())
    assert route.steps.calls == [] and ended(route) == "stop: stop_requested"


def test_refused_approve_plan_gate_never_reaches_execution(route):
    script(route, [step("prepare")])
    route.ledger.unmet["checkin1→execute"] = [{"id": "CHECKIN-1@run-judgment-fixture", "reason": "unmet"}]
    invoke(route, route.view())
    assert "prepare" not in route.steps.ids() and "approve_plan gate refused" in ended(route)


def test_declined_checkin1_revises_the_plan_within_its_rounds(route):
    doc = script(route, [step("prepare")])
    revised = plan(doc, [step("prepare"), step("check", depends_on=["prepare"])])
    route.steps.documents["judgment-decompose-2"] = lambda s, c, x: {"outputs/judgment-plan.json": revised}
    route.steps.documents = {"judgment-decompose-2": route.steps.documents.pop("judgment-decompose-2"),
                             **route.steps.documents}
    route.authority.script(approve_plan=["adjust", "approve"], final="accept")
    result = invoke(route, route.view())
    assert result["results"]["judgment"]["outcome"] == "delivered"
    assert [e["round"] for e in route.events("plan")] == [1, 2]


def test_a_failing_node_ends_in_a_qualified_delivery(route):
    script(route, [step("prepare"), step("report", "synthesize", depends_on=["prepare"])])

    def broken(step_, context, fixture):
        raise RuntimeError("the fictional governed step crashed")
    route.steps.statuses["prepare"] = broken
    invoke(route, route.view())
    assert "node failed" in ended(route) and [c[0] for c in route.sink.calls] == ["bounded_end"]
