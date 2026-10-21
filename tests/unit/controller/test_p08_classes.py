"""Consequence classes from code tables (A05, JR06): unknown is R3; a declared class only raises."""
import json
from importlib.resources import files

import pytest

from ravel.controller.judgment import classes, planning
from ravel.workflow import decision_gate


def test_JR06_class_decides_the_requirement_before_the_effect():
    assert [classes.requirement(c) for c in classes.CLASSES] == ["record", "report_at_next_checkin", "rdj_review",
                                                                 "authority"]
    with pytest.raises(ValueError):
        classes.requirement("R4")


def test_JR06_planner_R1_on_an_R3_action_is_recomputed_by_code():
    found = classes.explain({"summary": "adopt a default the request leaves to the physicist",
                             "kind": "adopt_default_left_to_physicist", "declared_class": "R1"})
    assert found["class"] == "R3" and found["computed"] == "R3" and found["declared_lower"] is True


def test_A05_physics_critical_ambiguities_and_unapproved_defaults_cannot_be_lowered():
    from ravel.workflow.scientific_autonomy import PREAUTHORIZATION_CONDITIONS
    for kind in PREAUTHORIZATION_CONDITIONS:
        assert classes.classify({"summary": kind, "kind": kind, "declared_class": "R0"}) == "R3", kind
    for kind in ("physics_critical_ambiguity", "prescription_change", "boundary_change", "deliverable_dropped",
                 "unblinding", "spend_above_ceiling"):
        assert classes.classify({"summary": kind, "kind": kind, "declared_class": "R1"}) == "R3", kind


def test_A05_unclassified_actions_default_to_R3():
    assert classes.classify({"summary": "something new"}) == "R3"
    assert classes.classify({"summary": "x", "kind": "invented_kind"}) == "R3"
    assert classes.classify({"summary": "x", "kind": "plot_style", "effects": ["invented_effect"]}) == "R3"
    assert classes.classify({"summary": "x", "kind": "plot_style", "declared_class": "R9"}) == "R3"
    assert classes.classify("not an action") == "R3"


def test_declared_class_raises_but_never_lowers():
    assert classes.classify({"summary": "x", "kind": "plot_style"}) == "R1"
    assert classes.classify({"summary": "x", "kind": "plot_style", "declared_class": "R2"}) == "R2"
    assert classes.classify({"summary": "x", "kind": "method_choice", "declared_class": "R0"}) == "R2"


def test_every_decision_gate_has_a_class_and_two_are_always_R3():
    table = classes.tables()["gate"]
    assert set(table) == set(decision_gate.GATES)
    assert table["unblind"] == "R3" and table["spend_above_ceiling"] == "R3"
    for gate in decision_gate.GATES:
        assert classes.classify({"summary": gate, "gate": gate}) == table[gate]


def test_research_choices_follow_the_research_protocol_table():
    protocol = json.loads(files("ravel").joinpath("data/research/protocol-default.json").read_text())
    for choice, cls in protocol["rdj_classes"].items():
        assert classes.classify({"summary": choice, "research_choice": choice}) == cls


def test_rdj_action_kinds_are_never_weakened_by_the_judgment_table():
    policy = json.loads(files("ravel").joinpath("data/rdj/policy.json").read_text())
    for kind, cls in policy["action_kinds"].items():
        assert classes.RANK[classes.classify({"summary": kind, "kind": kind})] >= classes.RANK[cls], kind


def test_effects_and_rungs_raise_the_class():
    assert classes.classify({"summary": "x", "step_kind": "operate", "rung": "smoke"}) == "R1"
    assert classes.classify({"summary": "x", "step_kind": "operate", "rung": "scan"}) == "R2"
    assert classes.classify({"summary": "x", "step_kind": "derive", "effects": ["irreversible"]}) == "R3"
    assert classes.classify({"summary": "x", "step_kind": "derive", "effects": ["scope_change"]}) == "R3"


def test_step_kind_table_is_the_closed_vocabulary():
    kinds = tuple(classes.tables()["step_kind"])
    assert set(kinds) == set(planning.policy()["step_kinds"])
    assert set(planning.policy()["step_kinds"]) == {"acquire", "operate", "author", "derive", "compare", "review",
                                                    "synthesize", "ask", "decide", "subgraph", "route"}
