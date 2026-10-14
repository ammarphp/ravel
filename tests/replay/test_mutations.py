"""T4 no narrowing: every narrowing mutation of a valid reading or plan is refused.

A mutation drops a claim, stage, tool, constraint or span, changes a statistic source, collapses a
range to a point, substitutes a generator, removes a template obligation, or understates a claim.
Each must fail the reading check or the plan check. Reading mutations need
``request_reading.check``; plan mutations need ``request_plan.draft`` and the plan check.
"""
import copy

import pytest

import intake_records as ir

INTAKE = ir.Intake()
CASES = {c["id"]: c for c in ir.load_cases()}


def _records(case_id):
    prompt = CASES[case_id]["prompt"]
    INTAKE.require("reader", "planner", "plan_check")
    reading = INTAKE.read(prompt)
    plan = INTAKE.plan(reading, INTAKE.contract(prompt))
    assert INTAKE.plan_errors(reading, plan) == [], "mutations start from a valid draft"
    return prompt, reading, plan


def _drop_constraint(kind):
    def mutate(reading):
        kept = [c for c in reading["constraints"] if c["type"] != kind]
        assert len(kept) < len(reading["constraints"]), f"the reading has no {kind} constraint to drop"
        reading["constraints"] = kept
    return mutate


READING_MUTATIONS = [
    ("B22", "drop a requested tool", _drop_constraint("requested_tool")),
    ("B12", "drop the prescribed statistic", _drop_constraint("prescribed_statistic")),
    ("B14", "drop the source restriction", _drop_constraint("source_restriction")),
    ("B14", "drop the template", _drop_constraint("template")),
    ("S05", "drop blinding", _drop_constraint("blinding")),
    ("B10", "drop the requested detector stage", _drop_constraint("requested_stage")),
    ("B13", "drop the scan ambiguity", lambda r: r.update(ambiguities=[])),
    ("B13", "drop a span", lambda r: r["facts"] and r["facts"][0].update(evidence=[])),
    ("B22", "weaken a quoted fact to inferred", lambda r: r["facts"][0].update(authority="inferred")),
]


@pytest.mark.parametrize("case_id,name,mutate", READING_MUTATIONS, ids=[f"{c}-{n}" for c, n, _ in READING_MUTATIONS])
def test_reading_narrowing_is_refused(case_id, name, mutate):
    INTAKE.require("reader", "reading_check")
    prompt = CASES[case_id]["prompt"]
    reading = INTAKE.read(prompt)
    assert INTAKE.reading_errors(prompt, reading) == []
    narrowed = copy.deepcopy(reading)
    mutate(narrowed)
    assert narrowed != reading
    assert INTAKE.reading_errors(prompt, narrowed), f"{name} was accepted"


def _first_claim(plan, kinds):
    claim = next((c for c in plan["claims"] if c["kind"] in kinds), None)
    assert claim is not None, f"no {kinds} claim to mutate"
    return claim


def _collapse_range(plan):
    fanned = [n for n in plan["nodes"] if n["fan_out"]]
    if fanned:
        for node in fanned:
            node["fan_out"] = None
    else:  # the range is an open scan question; dropping it from coverage narrows the plan
        for row in plan["coverage"]:
            row["by"] = [i for i in row["by"] if not i.startswith("A")] or row["by"]
        plan["nodes"] = plan["nodes"][:1]


PLAN_MUTATIONS = [
    ("B12", "statistic source changed", lambda p: _first_claim(p, ("exclusion",))["statistic"].update(
        source="policy_default", definition="95% CLs"), {"statistic_policy_violation"}),
    ("B03", "figure comparison removed", lambda p: p.update(
        nodes=[n for n in p["nodes"] if n["operation"] != "figure-comparison"] or p["nodes"]),
     {"published_figure_unserved", "obligation_uncovered", "slot_unfilled"}),
    ("B04", "analytic label on a simulated-acceptance limit", lambda p: _first_claim(p, ("exclusion",)).update(
        basis_declared=["analytic"]), {"claim_basis_understated"}),
    ("B04", "limit declared as a prediction", lambda p: _first_claim(p, ("exclusion",)).update(kind="prediction"),
     {"claim_kind_inconsistent"}),
    ("B22", "generating node at rung none", lambda p: [n.update(rung="none") for n in p["nodes"]],
     {"rung_below_effects"}),
    ("B22", "unknown operation", lambda p: p["nodes"][0].update(operation="not-a-registered-mode"),
     {"unknown_operation"}),
    ("B21", "orphan compute", lambda p: p["nodes"].append(dict(copy.deepcopy(p["nodes"][0]), id="N99", covers=["none"],
                                                              rung="full")), {"orphan_compute"}),
    ("B19", "claim dropped", lambda p: p.update(claims=[]), {"obligation_uncovered"}),
    ("B13", "range collapsed to a point", _collapse_range, {"obligation_uncovered", "slot_unfilled"}),
    ("B14", "template obligation removed", lambda p: p.update(coverage=p["coverage"][:1]), {"obligation_uncovered"}),
]


@pytest.mark.parametrize("case_id,name,mutate,expected", PLAN_MUTATIONS,
                         ids=[f"{c}-{n}" for c, n, _, _ in PLAN_MUTATIONS])
def test_plan_narrowing_is_refused(case_id, name, mutate, expected):
    _, reading, plan = _records(case_id)
    narrowed = copy.deepcopy(plan)
    mutate(narrowed)
    assert narrowed != plan
    classes = ir.error_classes(INTAKE.plan_errors(reading, narrowed))
    assert classes, f"{name} was accepted"
    assert classes & expected, f"{name}: refused as {sorted(classes)}, expected one of {sorted(expected)}"


def test_original_request_obligation_cannot_be_dropped():
    _, reading, plan = _records("B22")
    narrowed = copy.deepcopy(plan)
    narrowed["coverage"] = [row for row in narrowed["coverage"] if row["obligation_id"] != "original-request"]
    assert narrowed != plan
    assert "obligation_uncovered" in ir.error_classes(INTAKE.plan_errors(reading, narrowed))
