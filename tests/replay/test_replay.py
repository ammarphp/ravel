"""Deterministic replay: readings, plans and claims for every named request.

Each case is read by the deterministic reader, drafted into a plan with the router's v1 contract,
checked by the plan check and labelled. The assertions are about what the records contain (facts,
constraints, obligations covered, claims, effects, holds), never about a task_mode. Parts skip until
their module lands: the reading assertions need ``request_reading.document``; the plan assertions
also need ``request_plan.draft``.
"""
import json
import subprocess
import sys

import pytest

import intake_records as ir

INTAKE = ir.Intake()
CASES = ir.case_params()


def _outcome(case):
    prompt = case["prompt"]
    reading = INTAKE.read(prompt)
    errors = ir.reading_rule_errors(prompt, reading)
    assert not errors, errors
    plan = label = contract = None
    if INTAKE._draft is not None:
        contract = INTAKE.contract(prompt)
        plan = INTAKE.plan(reading, contract)
    if INTAKE._derive is not None and plan is not None:
        label = INTAKE.label(reading, plan)
    return reading, contract, plan, label


@pytest.mark.parametrize("case", CASES)
def test_reading_is_valid_deterministic_and_meets_its_expectations(case):
    reading, _, _, _ = _outcome(case)
    assert ir.canonical(INTAKE.read(case["prompt"])) == ir.canonical(reading), "the reading is not deterministic"
    if INTAKE._reading_check is not None:
        assert INTAKE.reading_errors(case["prompt"], reading) == []
    failures = ir.expectation_failures(case, reading)
    assert not failures, failures


@pytest.mark.parametrize("case", CASES)
def test_plan_covers_every_obligation_and_meets_its_expectations(case):
    INTAKE.require("reader", "planner")
    reading, contract, plan, label = _outcome(case)
    obligations = INTAKE.obligation_ids(contract)
    errors = ir.plan_rule_errors(reading, plan, obligations)
    assert not errors, errors
    if INTAKE._plan_check is not None:
        assert INTAKE.plan_errors(reading, plan) == [], "the deterministic draft must pass its own plan check"
    assert ir.bare_refusal(reading, plan, label) == []
    if label is not None:
        assert plan["label"]["task_mode"] == label.get("task_mode")
        assert plan["label"]["rule"] == label.get("rule")
    assert ir.canonical(INTAKE.plan(reading, INTAKE.contract(case["prompt"]))) == ir.canonical(plan)
    failures = ir.expectation_failures(case, reading, plan, label, ir.signatures())
    assert not failures, failures


@pytest.mark.parametrize("case", CASES)
def test_original_request_obligation_is_first_and_verbatim(case):
    INTAKE.require("reader")
    from ravel.workflow import task_completion
    contract = INTAKE.contract(case["prompt"])
    requirements = contract.get("task_requirements")
    assert requirements, "every request carries the obligation census"
    original = task_completion.initial_requirements(case["prompt"])["obligations"][0]
    assert requirements["obligations"][0] == original


def test_reading_hash_is_the_same_in_a_fresh_process():
    INTAKE.require("reader")
    sample = [c.values[0]["prompt"] for c in CASES[::9]]
    here = [ir.canonical(INTAKE.read(p)) for p in sample]
    code = ("import json,sys; from ravel.workflow import request_reading as r; "
            "print(json.dumps([json.dumps(r.document(p), sort_keys=True, separators=(',', ':')) "
            "for p in json.loads(sys.stdin.read())]))")
    out = subprocess.run([sys.executable, "-c", code], input=json.dumps(sample), capture_output=True, text=True,
                         check=True, env={**__import__("os").environ, "PYTHONHASHSEED": "17"})
    assert json.loads(out.stdout) == here


def test_oversized_request_is_refused_with_a_typed_error_not_a_crash():
    INTAKE.require("reader")
    prompt = "Compute the Z width. " + "x" * 40000
    try:
        reading = INTAKE.read(prompt)
    except ValueError:
        return
    assert ir.reading_rule_errors(prompt, reading) == []
