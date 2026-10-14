"""S1-07: CHECK-IN 1 shows the pinned plan, and every uncertified claim says why.

With a pinned request plan, CHECK-IN 1 must carry plan, claims, coverage and ambiguities
sections that equal the plan and the reading. A claim served by children with a
certificate-relevant basis shows "not certified on this route" with a plain-language
explanation for the reviewer and a proposed route that could certify it.
"""
from copy import deepcopy

import pytest

from ravel.validation import validate_checkin

import intake_sidecar_fixtures as fx


def _ambiguity(prompt=fx.PROMPT, status="open"):
    return {"id": "A1", "evidence": [fx.span(prompt, "13 TeV")], "issue": "which luminosity to assume",
            "readings": [{"id": "a", "value": {"lumi_fb": 139}, "authority": "agent_inference", "source": None},
                         {"id": "b", "value": {"lumi_fb": 36}, "authority": "agent_inference", "source": None}],
            "default": "a", "observable_impact": True, "reversible": True, "physics_critical": True,
            "blocks": ["N1"], "status": status, "resolution": None}


def _run(tmp_path, **kw):
    rd = tmp_path / "run"
    contract, reading, plan = fx.pinned_run(rd, **kw)
    return rd, reading, plan


def _errors(rd, checkin):
    return validate_checkin.validate(checkin, base_dir=str(rd))


def test_matching_plan_sections_validate(tmp_path):
    rd, reading, plan = _run(tmp_path, reading_overrides={"ambiguities": [_ambiguity()]})
    assert _errors(rd, fx.checkin1(plan, reading)) == []


@pytest.mark.parametrize("section", ["plan", "claims", "coverage", "ambiguities"])
def test_missing_plan_section_fails(tmp_path, section):
    rd, reading, plan = _run(tmp_path)
    checkin = fx.checkin1(plan, reading)
    del checkin["sections"][section]
    assert any(f"({section})" in e for e in _errors(rd, checkin))


@pytest.mark.parametrize("mutate, needle", [
    (lambda s: s["plan"].append({"id": "N9"}), "plan"),
    (lambda s: s["claims"][0].__setitem__("statement", "the model is excluded"), "claims"),
    (lambda s: s["claims"][0].__setitem__("kind", "agreement"), "claims"),
    (lambda s: s["claims"].clear(), "claims"),
    (lambda s: s["coverage"][0].__setitem__("by", ["N1"]), "coverage"),
    (lambda s: s["ambiguities"][0].__setitem__("status", "resolved"), "ambiguities"),
    (lambda s: s["ambiguities"].clear(), "ambiguities"),
])
def test_mismatched_plan_section_fails(tmp_path, mutate, needle):
    rd, reading, plan = _run(tmp_path, reading_overrides={"ambiguities": [_ambiguity()]})
    checkin = fx.checkin1(plan, reading)
    mutate(checkin["sections"])
    errors = _errors(rd, checkin)
    assert any(f"({needle})" in e for e in errors), errors


def test_open_ambiguity_must_be_a_numbered_flag(tmp_path):
    rd, reading, plan = _run(tmp_path, reading_overrides={"ambiguities": [_ambiguity()]})
    checkin = fx.checkin1(plan, reading)
    checkin["sections"]["v"] = [f for f in checkin["sections"]["v"] if "A1" not in f["text"]]
    assert any("A1" in e and "flag" in e for e in _errors(rd, checkin))


def test_children_served_certificate_claim_must_show_not_certified(tmp_path):
    rd, reading, plan = _run(tmp_path)
    checkin = fx.checkin1(plan, reading)
    row = checkin["sections"]["claims"][0]
    assert row["fidelity"] == "not certified on this route"
    row["fidelity"] = "of record"
    assert any("not certified on this route" in e for e in _errors(rd, checkin))


@pytest.mark.parametrize("field, value", [
    ("explanation", None), ("explanation", "TBD"), ("explanation", "not certified on this route"),
    ("explanation", "no certificate"), ("certifiable_route", None), ("certifiable_route", "n/a"),
])
def test_uncertified_claim_needs_a_plain_explanation_and_a_proposed_route(tmp_path, field, value):
    rd, reading, plan = _run(tmp_path)
    checkin = fx.checkin1(plan, reading)
    row = checkin["sections"]["claims"][0]
    if value is None:
        row.pop(field)
    else:
        row[field] = value
    assert any(field in e for e in _errors(rd, checkin))


def test_uncertified_claim_needs_a_fidelity_flag(tmp_path):
    rd, reading, plan = _run(tmp_path)
    checkin = fx.checkin1(plan, reading)
    checkin["sections"]["v"] = [checkin["sections"]["v"][0]]
    assert any("C1" in e and "flag" in e for e in _errors(rd, checkin))


def test_any_uncertified_fidelity_label_needs_an_explanation(tmp_path):
    rd, reading, plan = _run(tmp_path, plan_overrides={
        "label": {"task_mode": "reproduce", "rule": "D3", "floor_row": "reproduce"}})
    checkin = fx.checkin1(plan, reading)
    row = checkin["sections"]["claims"][0]
    assert row["fidelity"] == "of record"
    assert _errors(rd, checkin) == []
    row["fidelity"] = "uncertified-proxy"
    errors = _errors(rd, checkin)
    assert any("explanation" in e for e in errors) and any("certifiable_route" in e for e in errors)


def test_route_a_claim_in_place_does_not_need_the_children_label(tmp_path):
    rd, reading, plan = _run(tmp_path, plan_overrides={
        "label": {"task_mode": "reproduce", "rule": "D3", "floor_row": "reproduce"}})
    assert _errors(rd, fx.checkin1(plan, reading)) == []


def test_boundaries_and_authored_sections_follow_the_plan(tmp_path):
    authored = fx.node("N2", kind="authored", operation=None, implementation="authored-analysis",
                       authored={"purpose": "selection code", "signature": {}, "specification": None,
                                 "known_answer_tests": ["empty input gives zero"], "attempt_budget": 2})
    rd, reading, plan = _run(tmp_path, plan_overrides={"nodes": [fx.node(), authored], "boundaries": ["B1"]})
    checkin = fx.checkin1(plan, reading)
    assert _errors(rd, checkin) == []
    for section in ("boundaries", "authored"):
        broken = deepcopy(checkin)
        del broken["sections"][section]
        assert any(f"({section})" in e for e in _errors(rd, broken))


def test_unreadable_pinned_plan_fails_closed(tmp_path):
    rd, reading, plan = _run(tmp_path)
    (rd / "inputs/plan.json").write_text("{}")
    assert any("pinned" in e for e in _errors(rd, fx.checkin1(plan, reading)))


def test_contract_without_pins_validates_exactly_as_before(tmp_path):
    rd = tmp_path / "run"
    fx.write_json(rd / "inputs/task_contract.json", fx.contract())
    checkin = {"schema_version": 1, "kind": "checkin1", "variant": "survey", "sections": {
        "i": "request", "iv": "plan", "v": [{"id": "F1", "text": "x"}], "vi": ["answer", "ask", "propose"],
        "census_table": [{"source": "published search"}], "coverage_gaps": []}}
    assert _errors(rd, checkin) == []
    assert validate_checkin.validate(checkin) == []


def test_route_label_rule_is_the_plan_checks_rule():
    """CHECK-IN 1 and the plan's flags decide P0-S1' with one function."""
    from ravel.validation import validate_request_plan as rp
    reading = fx.reading()
    for basis, label, expected in ((["generated_prediction", "simulated_acceptance"], "D5", True),
                                   (["generated_prediction", "simulated_acceptance"], "D3", False),
                                   (["published_results"], "D5", False),
                                   (["published_statistical_model"], "D5", True)):
        plan = fx.plan({"path": "inputs/reading.json", "sha256": "0" * 64},
                       claims=[fx.claim(basis_declared=basis)],
                       label={"task_mode": "research", "rule": label, "floor_row": "research"})
        assert validate_checkin.needs_route_label(plan["claims"][0], plan) is expected
        assert rp.served_off_route_a(plan, "C1") is expected
    assert reading["facts"]
