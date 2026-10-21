"""The sink recomputes a delivered result's statistics record: held withholds, qualified qualifies and labels."""
from __future__ import annotations

from statistics_records import inert_statistics

from ravel.controller.sink import checks
from ravel.physics.inference import situations


def _record(outcome):
    if outcome == "valid":
        return inert_statistics()
    bins = [{"channel": "SR", "bin": 0, "observed": 2.0, "background": 1.5, "background_uncertainty": 0.5}]
    if outcome == "qualified":
        facts = situations.make_facts(deliverables=["exclusion"], model_origin="counting", bins=bins)
        availability = {"toy-cls": {"available": False, "reason": "budget: fits limit"}}
        evidence = {"limits": {"observed": "resolved", "median": "resolved"},
                    "budget_refusals": [{"method": "toy-cls", "status": "not_run", "reason": "budget"}]}
        return situations.record(facts, evidence, availability=availability,
                                 decision=situations.decide(situations.assess(facts, availability=availability)))
    facts = situations.make_facts(deliverables=["exclusion"], model_origin="constructed",
                                  bins=[{"channel": "SR", "bin": 0, "observed": 100.0, "background": 100.0}])
    return situations.record(facts, {"limits": {"observed": "resolved", "median": "resolved"}})


def _run(document):
    findings = checks.Findings()
    checks._statistics_validity(findings, "run.full:outputs/limits.json", document)
    return findings


def test_a_valid_record_neither_refuses_nor_labels():
    findings = _run({"statistics": _record("valid")})
    assert findings.refusals == [] and findings.labels == []


def test_a_document_without_a_record_is_left_to_its_route():
    for document in ({"limits": {}}, {"points": 3}, {"points": {"p1": {}}}, {"points": [1, {"tag": "p1"}]}):
        findings = _run(document)
        assert findings.refusals == [] and findings.labels == []


def test_a_qualified_outcome_qualifies_the_delivery_and_labels_the_artifact():
    block = _record("qualified")
    assert block["validity"]["outcome"] == "qualified"
    findings = _run({"statistics": block})
    assert [r["consequence"] for r in findings.refusals] == ["qualified"]
    assert findings.refusals[0]["code"] == "statistics_qualified"
    texts = [entry["text"] for entry in findings.labels if entry["label"] == checks.STATISTICS_QUALIFIED]
    assert texts and set(texts) == set(situations.labels(block))
    assert all(entry["artifact"] == "run.full:outputs/limits.json" for entry in findings.labels)


def test_a_held_outcome_withholds_the_delivery():
    block = _record("held")
    assert block["validity"]["outcome"] == "held"
    findings = _run({"statistics": block})
    assert [(r["code"], r["consequence"]) for r in findings.refusals] == [("statistics_held", "diagnostic")]


def test_a_record_that_does_not_recompute_withholds_the_delivery():
    block = _record("qualified")
    block["validity"]["outcome"] = "valid"
    block["validity"]["qualifications"] = []
    findings = _run({"statistics": block})
    assert [(r["code"], r["consequence"]) for r in findings.refusals] == [("statistics_record_invalid", "diagnostic")]


def test_a_scan_document_is_checked_point_by_point():
    qualified, held = _record("qualified"), _record("held")
    tampered = _record("qualified")
    tampered["validity"]["outcome"] = "valid"
    scan = {"points": [{"tag": "p1", "statistics": qualified}, {"tag": "p2", "statistics": _record("valid")},
                       {"tag": "p3"}]}
    findings = _run(scan)
    assert [(r["code"], r["consequence"]) for r in findings.refusals] == [("statistics_qualified", "qualified")]
    texts = [entry["text"] for entry in findings.labels if entry["label"] == checks.STATISTICS_QUALIFIED]
    assert texts == ["p1: " + label for label in situations.labels(qualified)]
    findings = _run({"points": [{"tag": "p1", "statistics": qualified}, {"tag": "p2", "statistics": held},
                                {"tag": "p3", "statistics": tampered}]})
    codes = [(r["code"], r["consequence"]) for r in findings.refusals]
    assert ("statistics_held", "diagnostic") in codes and ("statistics_record_invalid", "diagnostic") in codes
    assert any(r["message"].startswith("p2: ") for r in findings.refusals if r["code"] == "statistics_held")
    assert any(r["message"].startswith("p3: ") for r in findings.refusals if r["code"] == "statistics_record_invalid")
