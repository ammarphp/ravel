"""S1-10: a parent that owes a published-figure comparison cannot close without one.

When the obligation census (or the pinned plan's claims) holds a comparison with a
published figure, the parent closes only when an accepted figure-comparison child has
digitised that element and compared the claim's artifact with it. The shape is the
SystemA (c) chain: an analysis child, then a figure-comparison child.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from ravel.validation import validate_run_state
from ravel.workflow import route_prompt, science, task_completion as tc
from ravel.validation.validate_task_contract import validate

from test_task_completion import PROMPT, request, review_run, write

FIGURE = {"comparison": {"target": "published_figure", "locator": "Figure 3"}}
DIGITISE_AND_COMPARE = {"operations": [
    {"name": "published", "kind": "digitize", "specification": "digitise.json"},
    {"name": "agreement", "kind": "compare", "specification": "compare.json"}]}


def _parent(base, *, figure_obligation=True):
    contract = route_prompt.route(PROMPT)
    req = tc.initial_requirements(PROMPT)
    span = [{"start": 0, "end": len(PROMPT), "text": PROMPT}]
    req["obligations"].append({"id": "limits", "kind": "deliverable", "statement": "the summary limits",
                               "criteria": {"deliverable": "summary plot"}, "evidence": span})
    if figure_obligation:
        req["obligations"].append({"id": "figure", "kind": "quality",
                                   "statement": "compare the result with the published figure",
                                   "criteria": deepcopy(FIGURE), "evidence": span})
    rows = {r["id"]: {"obligation_id": r["id"], "criteria": deepcopy(r["criteria"])} for r in req["obligations"]}
    req["assignments"] = [{"id": "analysis", "purpose": "produce the limits",
                           "coverage": [rows["original-request"], rows["limits"]]}]
    if figure_obligation:
        req["assignments"].append({"id": "figure", "purpose": "digitise and compare the published figure",
                                   "coverage": [rows["figure"]]})
    contract["task_requirements"] = req
    assert validate(contract) == []
    return write(base / "parent/inputs/task_contract.json", contract)


def _child(base, contract_pin, assignment, spec, monkeypatch, *, state="satisfied"):
    rd = base / assignment
    write(rd / science.SPEC, {"goal_binding": {"contract": contract_pin, "assignment_id": assignment}, **spec})
    evidence = write(rd / "inputs/coverage.json", {"observed": f"synthetic {assignment} evidence"})
    coverage = next(a for a in tc.validate_requirements(
        __import__("json").loads(Path(contract_pin["path"]).read_text()))["assignments"] if a["id"] == assignment)
    review_run(rd, [contract_pin["path"], str(rd / science.SPEC), evidence["path"]], monkeypatch)
    return {"assignment_id": assignment, "rundir": str(rd), "claim_scope": "diagnostic",
            "coverage": [{**deepcopy(row), "state": state, "evidence": [evidence],
                          "explanation": "Synthetic contribution for the gate test."} for row in coverage["coverage"]]}


def _analysis(base, cp, monkeypatch):
    return _child(base, cp, "analysis", {"mode": "columnar-analysis"}, monkeypatch)


def test_parent_without_the_figure_comparison_child_cannot_close(tmp_path, monkeypatch):
    cp = _parent(tmp_path)
    result = tc.evaluate(request(tmp_path, cp, [_analysis(tmp_path, cp, monkeypatch)]), base_dir=tmp_path)
    assert result["unmet_obligation_ids"] == ["figure"] and not result["ready_for_parent_review"]
    assert result["published_figure_obligations"] == ["figure"]


def test_parent_with_an_accepted_figure_comparison_child_is_ready(tmp_path, monkeypatch):
    cp = _parent(tmp_path)
    figure = _child(tmp_path, cp, "figure", {"mode": "figure-comparison", "task": DIGITISE_AND_COMPARE}, monkeypatch)
    result = tc.evaluate(request(tmp_path, cp, [_analysis(tmp_path, cp, monkeypatch), figure]), base_dir=tmp_path)
    assert result["unmet_obligation_ids"] == [] and result["ready_for_parent_review"]


@pytest.mark.parametrize("spec", [
    {"mode": "columnar-analysis"},
    {"mode": "figure-comparison", "task": {"operations": [DIGITISE_AND_COMPARE["operations"][0]]}},
    {"mode": "figure-comparison", "task": {"operations": [DIGITISE_AND_COMPARE["operations"][1]]}},
])
def test_other_children_or_partial_comparisons_do_not_discharge_the_figure(tmp_path, monkeypatch, spec):
    cp = _parent(tmp_path)
    figure = _child(tmp_path, cp, "figure", spec, monkeypatch)
    result = tc.evaluate(request(tmp_path, cp, [_analysis(tmp_path, cp, monkeypatch), figure]), base_dir=tmp_path)
    assert result["unmet_obligation_ids"] == ["figure"]


def test_unaccepted_figure_comparison_child_does_not_discharge_the_figure(tmp_path, monkeypatch):
    cp = _parent(tmp_path)
    figure = _child(tmp_path, cp, "figure", {"mode": "figure-comparison", "task": DIGITISE_AND_COMPARE},
                    monkeypatch, state="partial")
    result = tc.evaluate(request(tmp_path, cp, [_analysis(tmp_path, cp, monkeypatch), figure]), base_dir=tmp_path)
    assert result["unmet_obligation_ids"] == ["figure"]


def test_final_parent_review_names_the_missing_figure_comparison(tmp_path, monkeypatch):
    cp = _parent(tmp_path)
    outcomes = [_analysis(tmp_path, cp, monkeypatch)]
    rp = request(tmp_path, cp, outcomes, parent_review={"rundir": str(tmp_path / "parent"),
                                                        "claim_scope": "original_task_completion"})
    with pytest.raises(ValueError, match="figure-comparison child"):
        tc.evaluate(rp, base_dir=tmp_path)


def test_census_without_a_figure_obligation_evaluates_as_before(tmp_path, monkeypatch):
    cp = _parent(tmp_path, figure_obligation=False)
    result = tc.evaluate(request(tmp_path, cp, [_analysis(tmp_path, cp, monkeypatch)]), base_dir=tmp_path)
    assert result["ready_for_parent_review"] and "published_figure_obligations" not in result


def test_pinned_plan_claim_against_a_published_figure_binds_its_obligations(tmp_path, monkeypatch):
    import intake_sidecar_fixtures as fx
    prompt = PROMPT
    rd = tmp_path / "parent"
    reading_pin = fx.write_json(rd / "inputs/reading.json", fx.reading(prompt, witness=[], facts=[]))
    plan = fx.plan(reading_pin, prompt, claims=[fx.claim(obligation_ids=["limits"])])
    plan_pin = fx.write_json(rd / "inputs/plan.json", plan)
    contract = route_prompt.route(PROMPT)
    req = tc.initial_requirements(PROMPT)
    span = [{"start": 0, "end": len(PROMPT), "text": PROMPT}]
    req["obligations"].append({"id": "limits", "kind": "deliverable", "statement": "the summary limits",
                               "criteria": {"deliverable": "summary plot"}, "evidence": span})
    rows = [{"obligation_id": r["id"], "criteria": deepcopy(r["criteria"])} for r in req["obligations"]]
    req["assignments"] = [{"id": "analysis", "purpose": "produce the limits", "coverage": rows}]
    contract.update(task_requirements=req, reading=reading_pin, request_plan=plan_pin)
    # A pinned reading or request plan is the release intake's contract shape; it carries epoch two.
    assert validate(contract) == ["a release-created contract (pinned reading or request_plan) requires agent_layer_epoch 2"]
    assert validate({**contract, "agent_layer_epoch": 1}) == validate(contract)
    contract["agent_layer_epoch"] = 2
    assert validate(contract) == []
    cp = write(rd / "inputs/task_contract.json", contract)
    result = tc.evaluate(request(tmp_path, cp, [_analysis(tmp_path, cp, monkeypatch)]), base_dir=tmp_path)
    assert result["published_figure_obligations"] == ["limits"]
    assert result["unmet_obligation_ids"] == ["limits"]


def test_route_a_reproduce_result_pack_evaluates_unchanged(tmp_path):
    contract = validate_run_state._base_contract(task_mode="reproduce", detector_mode="particle-level",
                                                 stat_mode="best-sr-counting")
    rd = tmp_path / "2026-10-11_reproduce"
    validate_run_state._write_json(str(rd / "inputs/task_contract.json"), contract)
    validate_run_state._write_json(str(rd / "result.json"), {"schema_version": 1})
    validate_run_state._write_json(str(rd / "figures.json"), {"schema_version": 1})
    facts = validate_run_state.discover_facts(str(rd), contract)
    status, _, checks = validate_run_state.check_result_pack(str(rd), contract, facts, "R", False)
    assert status == "PASS" and all(c["name"] != "published-figure" for c in checks)
