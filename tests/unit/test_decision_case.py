"""Adaptive scientific assertions require an audited edge and external leaf."""
from copy import deepcopy
from pathlib import Path

import pytest

from ravel.workflow import decision_case as dc
from ravel.workflow.diagnostic_plan import read_json

BASE = Path(__file__).resolve().parents[2] / "tests/fixtures/physics-review"


def case():
    return read_json(BASE / "recipe-restoration-case.json")


def test_supported_adaptive_case_stops_at_external_anchor():
    result = dc.evaluate_case(case(), BASE)
    assert result["status"] == "supported"
    assert result["obligations"] == []
    assert result["logical_entailment_proven"] is False
    assert result["physics_validated"] is False
    assert len(result["nodes"]) == 2  # no arbitrary mandatory seven-hop chain


def test_author_cannot_review_own_proposition_or_supporting_edge():
    c = case(); c["nodes"][0]["author_id"] = c["nodes"][0]["review"]["reviewer_id"]
    with pytest.raises(ValueError, match="own assertion"):
        dc.validate_case(c)
    c = case(); c["edges"][0]["author_id"] = c["edges"][0]["review"]["reviewer_id"]
    with pytest.raises(ValueError, match="separate from proposition authors"):
        dc.validate_case(c)


def test_unresolved_edge_requires_specific_experiment_request():
    c = case()
    c["nodes"][0]["assertion"] = "The processed population is complete"
    c["edges"][0]["review"]["decision"] = "unresolved"
    c["edges"][0]["review"]["reason"] = "Declared source count alone does not prove complete processed exposure"
    with pytest.raises(ValueError, match="specific evidence/experiment request"):
        dc.validate_case(c)
    c["edges"][0]["request"] = {"kind": "experiment", "description": "Join all retained event IDs to the complete original source and compare counts and weights"}
    result = dc.evaluate_case(c, BASE)
    assert result["status"] == "unresolved"
    assert any(o["request"]["kind"] == "experiment" for o in result["obligations"])


def test_terminal_assertion_without_anchor_cannot_support_action():
    c = case(); c["nodes"][1]["anchors"] = []
    result = dc.evaluate_case(c, BASE)
    assert result["status"] == "unresolved"
    assert any("Terminal assertion" in o["reason"] for o in result["obligations"])


def test_bad_premise_removes_support_without_logically_refuting_parent():
    c = case(); c["nodes"][1]["review"]["decision"] = "contradicted"
    result = dc.evaluate_case(c, BASE)
    assert result["status"] == "unresolved"
    assert result["nodes"][0]["status"] == "contradicted"


def test_direct_root_review_contradiction_is_preserved():
    c = case(); c["nodes"][0]["review"]["decision"] = "contradicted"
    assert dc.evaluate_case(c, BASE)["status"] == "contradicted"


def test_anchor_pointer_value_and_type_are_checked():
    c = case(); c["nodes"][1]["anchors"][0]["value"] = 99
    result = dc.evaluate_case(c, BASE)
    assert result["anchors"][0]["status"] == "contradicted"
    assert result["status"] == "unresolved"
    c = case(); c["nodes"][1]["anchors"][0]["location"] = "/absent"
    assert dc.evaluate_case(c, BASE)["anchors"][0]["status"] == "contradicted"


def test_source_tampering_invalidates_anchor():
    c = case(); c["nodes"][1]["anchors"][0]["artifact"]["sha256"] = "0" * 64
    result = dc.evaluate_case(c, BASE)
    assert "bytes changed" in result["anchors"][0]["reason"]


@pytest.mark.parametrize("mutate,match", [
    (lambda c: c["edges"].append({**deepcopy(c["edges"][0]), "parent": "B", "child": "A"}), "cyclic"),
    (lambda c: c["budget"].update(max_depth=0), "depth budget"),
    (lambda c: c["budget"].update(max_nodes=1), "node budget"),
    (lambda c: c["nodes"].append({**deepcopy(c["nodes"][1]), "id": "orphan"}), "unreachable"),
    (lambda c: c["nodes"][1].update(material=False), "context-only"),
    (lambda c: c["edges"].append(deepcopy(c["edges"][0])), "duplicate"),
])
def test_dag_budget_and_material_support_constraints(mutate, match):
    c = case(); mutate(c)
    with pytest.raises(ValueError, match=match):
        dc.validate_case(c)


def test_material_unknown_and_unresolved_assumption_create_obligations():
    c = case()
    c["nodes"][0]["unknowns"] = [{"question": "Is the restored source the historical effective recipe?", "request": {
        "kind": "evidence", "description": "Recover and hash the original executed cards rather than current defaults"}}]
    c["nodes"][0]["assumptions"] = [{"statement": "The two streams have identical detector response", "disposition": "unresolved", "reason": "No response calibration was supplied"}]
    result = dc.evaluate_case(c, BASE)
    assert result["status"] == "unresolved"
    assert len(result["obligations"]) == 2


def test_retrospective_rs1_action_requires_specific_external_definition_evidence():
    result = dc.evaluate_case(read_json(BASE / "rs1-track-stop-case.json"), BASE)
    assert result["status"] == "unresolved"
    assert result["physics_validated"] is False
    assert all(a["status"] == "supported" for a in result["anchors"])
    assert any("primary-source" in o["request"]["description"] for o in result["obligations"])


def test_cli_never_overwrites_a_decision_record(tmp_path):
    out = tmp_path / "decision.json"
    assert dc.main(["--case", str(BASE / "recipe-restoration-case.json"), "--out", str(out)]) == 0
    before = out.read_bytes()
    with pytest.raises(SystemExit):
        dc.main(["--case", str(BASE / "recipe-restoration-case.json"), "--out", str(out)])
    assert out.read_bytes() == before


def test_recursive_audit_has_hard_resource_bounds():
    c = case(); c["budget"]["max_depth"] = 1000
    with pytest.raises(ValueError, match="finite engine limits"):
        dc.validate_case(c)


def test_shared_dag_branches_are_memoized_and_longest_depth_is_checked():
    c = case(); template = deepcopy(c["nodes"][1]); edge = deepcopy(c["edges"][0])
    c["nodes"] = [{**deepcopy(template), "id": str(i)} for i in range(50)]
    c["root"] = "0"; c["budget"] = {"max_nodes": 50, "max_depth": 49}
    c["edges"] = [{**deepcopy(edge), "parent": str(i), "child": str(j)}
                  for i in range(48) for j in (i + 1, i + 2)]
    c["edges"].append({**edge, "parent": "48", "child": "49"})
    assert dc.evaluate_case(c, BASE)["status"] == "supported"
    c["budget"]["max_depth"] = 48
    with pytest.raises(ValueError, match="depth budget"):
        dc.validate_case(c)
