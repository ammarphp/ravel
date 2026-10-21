"""Frame and plan checks, classification and the controller plan (JR02, JR03, JR04, R10, ROUTE-unsupported)."""
from copy import deepcopy
import hashlib
import json

import pytest

from ravel.controller.judgment import planning, recovery
from test_p08_fakes import digest, frame, p7, plan, reading, step

SHA = hashlib.sha256(b"a fictional request").hexdigest()
OPERATIONS = {"literal-calculation"}


def check(plan_doc, frame_doc, **kw):
    kw.setdefault("operations", OPERATIONS)
    kw.setdefault("routes", set())
    return planning.check_plan(plan_doc, frame_doc, **kw)


# ---- the frame (JR02, R10) -----------------------------------------------------------------------

def test_JR02_frame_without_a_reading_deliverable_is_refused():
    doc = frame(SHA)
    assert planning.check_frame(doc, reading(), SHA) == []
    problems = planning.check_frame(doc, reading(deliverables=("D1", "D2")), SHA)
    assert any("D2 is missing from the frame" in p for p in problems)


@pytest.mark.parametrize("mutate, expected", [
    (lambda f: f.pop("objective"), "objective"),
    (lambda f: f.update(deliverables=[]), "entries"),
    (lambda f: f["deliverables"][0].pop("acceptance"), "acceptance"),
    (lambda f: f.update(assumptions=[{**f["assumptions"][0], "number": 2}]), "numbered"),
    (lambda f: f.update(request_sha256="0" * 64), "pinned request"),
    (lambda f: f["deliverables"].append({**f["deliverables"][0], "id": "D1b"}), "more than once"),
    (lambda f: f["deliverables"].append({**f["deliverables"][0], "id": "X", "reading_ref": None}), "scope change"),
])
def test_JR02_frame_states_objective_deliverables_criteria_and_numbered_assumptions(mutate, expected):
    doc = frame(SHA)
    mutate(doc)
    assert any(expected in p for p in planning.check_frame(doc, reading(), SHA))


def test_JR02_scope_addition_is_declared_and_classified_R3():
    doc = frame(SHA)
    doc["deliverables"].append({**doc["deliverables"][0], "id": "X", "reading_ref": None,
                                "scope_change": {"kind": "added", "reason": "a companion table helps review"}})
    assert planning.check_frame(doc, reading(), SHA) == []
    calls = planning.classify_steps(plan(doc, [step("compute")], deliverables=[
        {"id": "D1", "status": "planned", "outputs": [{"step": "compute", "path": "outputs/compute.json"}]},
        {"id": "X", "status": "held", "outputs": [], "held_reason": "awaits authority"}]), doc)
    assert calls["frame:X"]["class"] == "R3"


def test_R10_reading_boundaries_constraints_and_critical_ambiguities_are_kept():
    boundaries = [{"id": "RB1", "class": "inaccessible_input"}]
    constraints = [{"id": "C1", "type": "prescribed_statistic", "value": {"statistic": "expected sensitivity"}}]
    ambiguities = [{"id": "A1", "critical": True, "status": "open"}]
    read = reading(boundaries=boundaries, constraints=constraints, ambiguities=ambiguities)
    doc = frame(SHA)
    problems = planning.check_frame(doc, read, SHA)
    assert any("boundary RB1" in p for p in problems)
    assert any("constraint C1" in p for p in problems)
    assert any("ambiguity A1" in p for p in problems)
    kept = frame(SHA, boundaries=[{"id": "B1", "statement": "a private input", "holds": ["D1"],
                                   "would_make_possible": "the owner supplies it", "reading_ref": "RB1"}],
                 constraints=[{"kind": "statistic", "statement": "the requested statistic", "reading_ref": "C1",
                               "value": "expected sensitivity"}],
                 unknowns=[{"id": "U1", "question": "Which threshold range?", "physics_critical": True,
                            "reading_ref": "A1"}])
    assert planning.check_frame(kept, read, SHA) == []
    changed = deepcopy(kept)
    changed["constraints"][0]["value"] = "a different statistic"
    assert any("verbatim" in p for p in planning.check_frame(changed, read, SHA))


# ---- the plan (JR03, JR04, ROUTE-unsupported, R10) --------------------------------------------------

def test_JR03_a_typed_dag_with_outputs_and_mapped_deliverables_is_admitted():
    doc = frame(SHA)
    assert check(plan(doc, [step("prepare"), step("compute", depends_on=["prepare"])]), doc) == []


def test_an_rdj_case_is_a_governed_review_by_the_rdj_critic_card_on_the_exact_spec():
    from ravel.controller.judgment import control, steps
    subject = {"kind": "step-spec", "step": "choose", "sha256": "a" * 64, "class": "R2"}
    case = steps.rdj_step("judgment-rdj-choose-0-1", subject=subject, must_check=[], inputs=[], purpose="Review it.")
    assert case["kind"] == "review" and case["role"] == "rdj-critic" and "graph" not in case
    assert case["parameters"]["subject_sha256"] == "a" * 64 and case["obligations"] == ["JR06"]
    compiled = {"steps": [{"id": "choose", "kind": "decide", "class": "R2"}, {"id": "run", "kind": "operate", "class": "R3"},
                          {"id": "note", "kind": "decide", "class": "R1"}, {"id": "look", "kind": "review", "class": "R3"}]}
    assert [s["id"] for s in control.rdj_calls(compiled)] == ["choose", "run"]


def test_a_step_declares_its_validator_inputs_and_the_compiled_step_carries_them():
    doc = frame(SHA)
    inputs = {"check:validation.input_closure.check": {
        "fit": {"output": "outputs/compute.json"}, "reference": {"path": "inputs/reference.json", "sha256": "a" * 64}}}
    candidate = plan(doc, [step("compute", check_inputs=inputs)])
    assert check(candidate, doc) == []
    row = {**candidate["steps"][0], "class": "R0", "role": "calculation"}
    assert planning.controller_step(row, inputs={}, deliverables=["D1"])["parameters"]["check_inputs"] == inputs
    assert "check_inputs" not in planning.controller_step({**row, "check_inputs": {}}, inputs={}, deliverables=[])["parameters"]
    malformed = plan(doc, [step("compute", check_inputs={"check:validation.input_closure.check": "fit"})])
    assert check(malformed, doc)


def test_a_result_a_blind_reviewer_may_not_see_needs_its_approved_comparison():
    """A derive step's card is reviewed by a blind verifier that may not see a producer headline: when the step's result
    is one, the plan declares the comparison (output, pointer, unit and tolerance) CHECK-IN 1 approves; no default
    tolerance is assumed, so a step without one is refused, and a verification of another output is refused too."""
    doc = frame(SHA)
    headline = [{"path": "outputs/result.json", "kind": "result", "required": True}]
    declared = {"output": "outputs/result.json", "pointer": "/value", "unit": "1", "relative_tolerance": 0.05}
    bare = check(plan(doc, [step("compute", outputs=headline)]), doc)
    assert any("verified blind by skeptical-verifier" in p and "no default tolerance" in p for p in bare), bare
    assert check(plan(doc, [step("compute", outputs=headline, verification=declared)]), doc) == []
    elsewhere = plan(doc, [step("compute", outputs=headline, verification={**declared, "output": "outputs/other.json"})])
    assert any("not one of its outputs" in p for p in check(elsewhere, doc))
    assert check(plan(doc, [step("compute")]), doc) == []  # a result the blind reviewer may see needs no comparison


@pytest.mark.parametrize("mutate, expected", [
    (lambda p: p["steps"][0].update(kind="execute"), "kind"),
    (lambda p: p["steps"][0].update(outputs=[]), "entries"),
    (lambda p: p["steps"][0].update(depends_on=["ghost"]), "unknown step ghost"),
    (lambda p: p["steps"][0].update(depends_on=["compute"]), "cycle"),
    (lambda p: p["steps"][0].pop("budget_share"), "budget_share"),
    (lambda p: p["steps"][1].update(inputs=[{"artifact": "other:outputs/x.json"}]), "does not depend"),
    (lambda p: p.update(frame_sha256="0" * 64), "adopted frame"),
])
def test_JR03_step_of_unknown_kind_or_without_outputs_refuses_the_plan(mutate, expected):
    doc = frame(SHA)
    candidate = plan(doc, [step("prepare"), step("compute", depends_on=["prepare"])])
    mutate(candidate)
    assert any(expected in p for p in check(candidate, doc))


@pytest.mark.parametrize("field", ["argv", "command", "code", "script", "shell", "run"])
def test_JR04_inline_execution_fields_are_impossible(field):
    doc = frame(SHA)
    candidate = plan(doc, [step("compute")])
    candidate["steps"][0][field] = ["python", "-c", "print(1)"]
    problems = check(candidate, doc)
    assert problems and "governed step graph" in problems[0]


def test_ROUTE_unsupported_dropping_a_deliverable_leaves_it_open_and_refuses_the_plan():
    doc = frame(SHA)
    candidate = plan(doc, [step("compute")], deliverables=[])
    assert check(candidate, doc)
    doc2 = frame(SHA, deliverables=frame(SHA)["deliverables"] + [
        {"id": "D2", "reading_ref": "D2", "description": "A table.", "acceptance": "Every point listed.",
         "statistic": None, "units": None}])
    candidate = plan(doc2, [step("compute")])
    assert any("D2 is dropped" in p for p in check(candidate, doc2))


def test_R10_held_scope_is_held_or_asked_never_substituted():
    boundary = {"id": "B1", "statement": "a private input", "holds": ["D1"],
                "would_make_possible": "the owner supplies it", "reading_ref": None}
    doc = frame(SHA, boundaries=[boundary])
    substituted = plan(doc, [step("compute")])
    assert any("held scope is never substituted" in p for p in check(substituted, doc))
    held = plan(doc, [step("compute")], deliverables=[{"id": "D1", "status": "held", "outputs": [],
                                                       "held_reason": "held by B1"}])
    assert check(held, doc) == []
    asked = plan(doc, [step("ask-b1", "ask", question="Can the owner supply the input?", resolves=["B1"],
                            options=[{"id": "supply", "description": "supply it"}],
                            outputs=[{"path": "outputs/answer.json", "kind": "operator-answer", "required": True}]),
                       step("compute", depends_on=["ask-b1"])])
    assert check(asked, doc) == []
    decided = plan(doc, [step("work-around", "decide", resolves=["B1"], question="Work around it?",
                              action={"summary": "a workaround"},
                              outputs=[{"path": "outputs/judgment-record.json", "kind": "judgment-record",
                                        "required": True}]),
                         step("compute", depends_on=["work-around"])])
    assert any("held scope is never substituted" in p for p in check(decided, doc))
    assert planning.classify_steps(decided, doc)["work-around"]["class"] == "R3"


def test_R10_held_request_seed_plan_is_always_admissible():
    boundary = {"id": "B1", "statement": "no scientific object", "holds": ["D1"],
                "would_make_possible": "name the quantity", "reading_ref": None}
    unknown = {"id": "U1", "question": "Which observable?", "physics_critical": True, "reading_ref": None}
    doc = frame(SHA, boundaries=[boundary], unknowns=[unknown])
    seed = recovery.seed_plan(doc)
    assert check(seed, doc) == []
    assert all(d["status"] == "held" for d in seed["deliverables"])
    assert recovery.seed_plan(frame(SHA)) is None


def test_physics_critical_unknowns_are_resolved_by_asking_or_an_R3_decision():
    unknown = {"id": "U1", "question": "Which threshold range?", "physics_critical": True, "reading_ref": None}
    doc = frame(SHA, unknowns=[unknown])
    silent = plan(doc, [step("compute", resolves=["U1"])])
    assert any("ask or a decide" in p for p in check(silent, doc))
    decided = plan(doc, [step("pick", "decide", resolves=["U1"], question="Which range?",
                              action={"summary": "the range", "kind": "selection_choice"},
                              outputs=[{"path": "outputs/judgment-record.json", "kind": "judgment-record",
                                        "required": True}]),
                         step("compute", depends_on=["pick"])])
    assert check(decided, doc) == []
    assert planning.classify_steps(decided, doc)["pick"]["class"] == "R3"


def test_operations_routes_roles_and_protocols_are_admitted_by_code():
    doc = frame(SHA)
    unknown_op = plan(doc, [step("compute", "operate", operation="invented-operation")])
    assert any("not admitted" in p for p in check(unknown_op, doc))
    route = plan(doc, [step("covered", "route", route="study")])
    assert any("no installed route spec" in p for p in check(route, doc))
    assert check(route, doc, routes={"study"}) == []
    comparison = plan(doc, [step("compare-ref", "compare",
                                 outputs=[{"path": "outputs/c.json", "kind": "comparison", "required": True}])])
    assert any("protocols ['P2']" in p for p in check(comparison, doc))
    comparison["steps"][0]["protocols"] = ["P2"]
    assert check(comparison, doc) == []
    seat = plan(doc, [step("compute", review=["invented-role"])])
    assert any("unregistered role" in p for p in check(seat, doc, roles={"physics-critic"}))


def test_R13_operate_step_runs_under_its_registered_production_executor():
    doc = frame(SHA)
    named = plan(doc, [step("compute", "operate", operation="literal-calculation", role="analysis-author")])
    assert any("executor_role_mismatch" in p for p in check(named, doc))
    named["steps"][0]["role"] = "calculation"
    assert check(named, doc) == []
    unnamed = plan(doc, [step("compute", "operate", operation="literal-calculation")])
    assert check(unnamed, doc) == []
    compiled = planning.compile_plan(unnamed, doc, planning.classify_steps(unnamed, doc), revision=0)
    assert compiled["steps"][0]["role"] == "calculation"
    unmapped = plan(doc, [step("compute", "operate", operation="invented-operation")])
    assert any("executor_role_missing" in p for p in check(unmapped, doc, operations={"invented-operation"}))


def test_ask_default_option_needs_its_P7_record():
    doc = frame(SHA)
    asked = plan(doc, [step("ask-range", "ask", question="Which range?", default_option="narrow",
                            options=[{"id": "narrow", "description": "narrow"}, {"id": "wide", "description": "wide"}],
                            outputs=[{"path": "outputs/answer.json", "kind": "operator-answer", "required": True}]),
                       step("compute", depends_on=["ask-range"])])
    assert any("P7" in p for p in check(asked, doc))
    asked["steps"][0]["default"] = p7()
    assert check(asked, doc) == []


def test_C08_ask_default_that_is_physics_critical_needs_its_justification():
    doc = frame(SHA)
    unjustified = p7(physics_critical=True)
    unjustified["justification"] = None
    asked = plan(doc, [step("ask-range", "ask", question="Which range?", default_option="narrow", default=unjustified,
                            options=[{"id": "narrow", "description": "narrow"}, {"id": "wide", "description": "wide"}],
                            outputs=[{"path": "outputs/answer.json", "kind": "operator-answer", "required": True}]),
                       step("compute", depends_on=["ask-range"])])
    assert any("justification" in p for p in check(asked, doc))
    asked["steps"][0]["default"] = p7(physics_critical=True)
    assert check(asked, doc) == []


def test_failed_steps_need_a_stage_recovery_decision_before_a_retry():
    doc = frame(SHA)
    retry = plan(doc, [step("generate")])
    assert any("stage-recovery decision" in p for p in check(retry, doc, failures=("generate",)))
    recover = plan(doc, [step("recover", "decide", question="What caused the failure?", resolves=["failure:generate"],
                              triggers=["stage_recovery"], action={"summary": "recover", "kind": "stage_recovery"},
                              outputs=[{"path": "outputs/judgment-record.json", "kind": "judgment-record",
                                        "required": True}]),
                         step("generate", depends_on=["recover"])])
    assert check(recover, doc, failures=("generate",)) == []


def test_controller_plan_is_reading_keyed_with_held_scope_open():
    boundary = {"id": "B1", "statement": "a private input", "holds": ["D2"],
                "would_make_possible": "the owner supplies it", "reading_ref": None}
    doc = frame(SHA, boundaries=[boundary], deliverables=frame(SHA)["deliverables"] + [
        {"id": "T2", "reading_ref": "D2", "description": "A table.", "acceptance": "Every point listed.",
         "statistic": None, "units": None}])
    candidate = plan(doc, [step("compute")], deliverables=[
        {"id": "D1", "status": "planned", "outputs": [{"step": "compute", "path": "outputs/compute.json"}]},
        {"id": "T2", "status": "held", "outputs": [], "held_reason": "held by B1"}])
    calls = planning.classify_steps(candidate, doc)
    compiled = planning.compile_plan(candidate, doc, calls, revision=0)
    inputs = {"reading": {"artifact": "inputs/judgment/reading-x.json", "sha256": "b" * 64}}
    result = planning.controller_plan(compiled, frame=doc, reading=reading(deliverables=("D1", "D2")),
                                      run_id="run-fixture", revision=0, inputs=inputs,
                                      request={"reading_sha256": "c" * 64, "contract_sha256": "d" * 64})
    assert result["kind"] == "controller-plan" and result["route"]["id"] == "judgment"
    assert [(d["id"], d["status"]) for d in result["deliverables"]] == [("D1", "mapped"), ("D2", "open")]
    assert result["open_obligations"] == [{"id": "D2", "kind": "deliverable", "reason": "held by B1",
                                           "source": "judgment"}]
    assert result["steps"][0]["inputs"] == [inputs["reading"]] and result["steps"][0]["deliverables"] == ["D1"]
    assert result["steps"][0]["consequence_class"] == "R1"
    body = {k: v for k, v in result.items() if k != "sha256"}
    assert result["sha256"] == hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                                         ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert planning.controller_plan_problems(result) == []


def test_compiled_steps_carry_class_requirement_and_a_spec_digest():
    doc = frame(SHA)
    candidate = plan(doc, [step("compute", "operate", operation="literal-calculation", rung="full")])
    compiled = planning.compile_plan(candidate, doc, planning.classify_steps(candidate, doc), revision=0)
    row = compiled["steps"][0]
    assert row["class"] == "R2" and row["requirement"] == "rdj_review" and len(row["spec_sha256"]) == 64
    assert compiled["sha256"] == digest({k: v for k, v in compiled.items() if k != "sha256"})


def test_scope_delta_names_dropped_and_newly_held_deliverables():
    doc = frame(SHA)
    old = planning.compile_plan(plan(doc, [step("compute")]), doc, {}, revision=0)
    newly_held = plan(doc, [step("compute")], deliverables=[{"id": "D1", "status": "held", "outputs": [],
                                                              "held_reason": "an input became unavailable"}])
    assert planning.scope_delta(old, newly_held, doc) == [{"kind": "deliverable_dropped", "deliverable": "D1",
                                                           "detail": "newly held"}]
