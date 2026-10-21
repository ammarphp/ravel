"""Step 07 on the analysis route: the statistics record and the uncertainty statement are enforced.

The adapter recomputes the limit-setting engine's statistics record (``situations.audit``), refuses a
held outcome, requires every qualification label in the result's limitations, and requires a valid
uncertainty statement. The statistics seats receive the catalogue as a pinned run input. Synthetic
records only.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from statistics_records import inert_statistics, inert_uncertainty, with_statistics

from ravel.controller.routes import analysis
from ravel.controller.routes.analysis import evidence, statistics
from ravel.physics.inference import situations
from p09_support import (Store, adopt, adopt_prepare, compile_plan, context, contract, outcome, reading)

LIMITS = {"schema_version": 1, "quantity": "signal_strength",
          "observed": {"value": 0.8, "status": "resolved", "bracket": [0.5, 1.0]},
          "expected": [{"value": v, "status": "resolved", "bracket": [v / 2, v * 2]} for v in (0.5, 0.7, 0.9, 1.2, 1.6)],
          "origin": "fixture", "notes": []}
BASE = {"statistic": "CLs", "confidence_level": 0.95, "limits": LIMITS, "detector_mode": "simpleanalysis-delphes-native"}


@pytest.fixture
def run(tmp_path):
    store = Store()
    read, con = reading(), contract("reproduce")
    plan = compile_plan("analysis", read, con)
    states = adopt_prepare(store, tmp_path, plan)
    return store, plan, context(store, tmp_path, plan, read, con, states), tmp_path


def _codes(errors):
    return {e["code"] for e in errors}


def _check(run, document):
    store, plan, ctx, tmp_path = run
    step = next(s for s in plan["steps"] if s["id"] == "run.full")
    adopt(store, tmp_path, step["id"], "outputs/limits.json", document)
    return evidence.check(step, outcome(step), ctx)


def _low_count_record(*, budget_refused):
    """A record whose small-count region forced toys that a budget refused: qualified."""
    facts = situations.make_facts(deliverables=["exclusion"], model_origin="counting",
                                  bins=[{"channel": "SR", "bin": 0, "observed": 2.0, "background": 1.5,
                                         "background_uncertainty": 0.5}])
    availability = {"toy-cls": {"available": False, "reason": "budget: fits limit"}} if budget_refused else None
    evidence_doc = {"limits": {"observed": "resolved", "median": "resolved"}}
    if budget_refused:
        evidence_doc["budget_refusals"] = [{"method": "toy-cls", "status": "not_run", "reason": "budget"}]
    assessment = situations.assess(facts, availability=availability)
    return situations.record(facts, evidence_doc, availability=availability,
                             decision=situations.decide(assessment))


def test_a_valid_record_and_statement_pass(run):
    assert _check(run, with_statistics(BASE)) == []


def test_a_limit_without_records_is_refused(run):
    codes = _codes(_check(run, dict(BASE)))
    assert {"statistics_record_missing", "uncertainty_unstated"} <= codes
    assert all(e["row"] == "STEP-07-exclude" for e in _check(run, dict(BASE)) if e["code"].startswith(("statistics", "uncertainty")))


def test_a_record_that_does_not_recompute_is_refused(run):
    block = inert_statistics()
    block["validity"]["outcome"] = "qualified"
    codes = _codes(_check(run, {**BASE, "statistics": block, "uncertainty": inert_uncertainty()}))
    assert "statistics_record_invalid" in codes


def test_an_empty_description_is_not_an_assessment(run):
    facts = situations.make_facts(deliverables=["exclusion"])
    block = situations.record(facts, {})
    errors = _check(run, {**BASE, "statistics": block, "uncertainty": inert_uncertainty()})
    found = [e for e in errors if e["code"] == "statistics_record_invalid"]
    assert found and "no main-bin counts" in found[0]["message"]


def test_facts_must_agree_with_the_result_counts(run):
    document = with_statistics({**BASE, "per_sr": {"SR": {"n": 7, "b": 100.0}}})
    found = [e for e in _check(run, document) if e["code"] == "statistics_record_invalid"]
    assert found and "region SR" in found[0]["message"]


def test_a_held_outcome_is_refused_with_its_labels(run):
    facts = situations.make_facts(deliverables=["exclusion"], model_origin="constructed",
                                  bins=[{"channel": "SR", "bin": 0, "observed": 100.0, "background": 100.0}])
    block = situations.record(facts, {"limits": {"observed": "resolved", "median": "resolved"}})
    assert block["validity"]["outcome"] == "held"  # signal injection owed and not run
    errors = _check(run, {**BASE, "statistics": block, "uncertainty": inert_uncertainty()})
    held = [e for e in errors if e["code"] == "statistics_held"]
    assert held and "signal-injection did not run" in held[0]["message"]


def test_a_qualified_outcome_must_carry_its_labels(run):
    block = _low_count_record(budget_refused=True)
    assert block["validity"]["outcome"] == "qualified" and situations.audit(block) == []
    labels = situations.labels(block)
    unlabelled = _check(run, {**BASE, "statistics": block, "uncertainty": inert_uncertainty()})
    assert "statistics_qualification_unlabelled" in _codes(unlabelled)
    labelled = {**BASE, "statistics": block, "uncertainty": inert_uncertainty(),
                "limitations": [{"key": "statistics", "note": label} for label in labels]}
    assert _check(run, labelled) == []
    as_text = {**BASE, "statistics": block, "uncertainty": inert_uncertainty(), "limitations": list(labels)}
    assert _check(run, as_text) == []


def test_a_budget_claim_without_its_refusal_does_not_recompute(run):
    block = _low_count_record(budget_refused=True)
    block["evidence"].pop("budget_refusals")
    errors = _check(run, {**BASE, "statistics": block, "uncertainty": inert_uncertainty(),
                          "limitations": situations.labels(block)})
    found = [e for e in errors if e["code"] == "statistics_record_invalid"]
    assert found and "no budget refusal" in found[0]["message"]


def test_an_invalid_uncertainty_statement_is_refused(run):
    statement = inert_uncertainty()
    statement["components"] = [c for c in statement["components"] if c["kind"] != "systematic"]
    errors = _check(run, {**BASE, "statistics": inert_statistics(), "uncertainty": statement})
    found = [e for e in errors if e["code"] == "uncertainty_unstated"]
    assert found and "systematic" in found[0]["message"]


def test_scan_points_owe_the_same_records(tmp_path):
    store = Store()
    read, con = reading(scan=True), contract("scan")
    plan = compile_plan("analysis.scan", read, con)
    states = adopt_prepare(store, tmp_path, plan)
    ctx = context(store, tmp_path, plan, read, con, states)
    step = next(s for s in plan["steps"] if s["id"].startswith("scan.point."))
    item = step["parameters"]["item"]
    document = {"tag": item["id"], "parameters": item["parameters"], **BASE}
    adopt(store, tmp_path, step["id"], "outputs/point_result.json", document)
    errors = evidence.check(step, outcome(step), ctx)
    assert {"statistics_record_missing", "uncertainty_unstated"} <= _codes(errors)
    assert all(e["row"] == "P04" for e in errors if e["code"].startswith(("statistics", "uncertainty")))
    adopt(store, tmp_path, step["id"], "outputs/point_result.json", with_statistics(document))
    assert evidence.check(step, outcome(step), ctx) == []


def test_the_statistics_seats_receive_the_catalogue_as_a_pinned_input(run):
    store, plan, ctx, tmp_path = run
    bound = statistics.bind(plan, ctx)
    rows = {s["id"]: [r for r in s["inputs"] if statistics.is_catalogue_input(r)] for s in bound["steps"]}
    assert [len(rows[s["id"]]) for s in bound["steps"] if s["id"] == "run.full"] == [1]
    assert all(not v for k, v in rows.items() if k != "run.full")
    row = rows["run.full"][0]
    assert row["kind"] == statistics.INPUT_KIND == "document"  # the operation's declared context-document slot
    raw = (tmp_path / row["artifact"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    assert json.loads(raw) == situations.export()
    assert statistics.bind(bound, ctx) == bound  # idempotent
    assert statistics.bind(plan, {**ctx, "run_dir": None}) == plan


def test_route_binding_pins_the_catalogue_in_the_bound_plan(run):
    store, plan, ctx, tmp_path = run
    bound = analysis.bind(plan, ctx)
    assert bound is not None
    step = next(s for s in bound["steps"] if s["id"] == "run.full")
    assert any(statistics.is_catalogue_input(r) for r in step["inputs"])
