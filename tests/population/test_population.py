"""T2 coverage over a fixed-seed population: zero bare refusals.

CI draws 2,000 requests with the fixed seed; ``RAVEL_POPULATION_SIZE`` raises it (20,000 nightly).
Gated: no bare refusal, holds only in the six boundary classes with evidence, every witness item
used or dismissed, and every obligation covered. Reported, not gated: recall of the constraint
each request's wording should yield, the share with only registered nodes, and the share needing
authored or held nodes.
"""
import collections
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "replay"))

import intake_records as ir  # noqa: E402
import request_population as rp  # noqa: E402

# Re-pinned after 4127a9a replaced the example record identifiers in the "identifiers" input
# phrase (HEPData record and arXiv identifier); no axis value, seed or draw order changed.
POPULATION_SHA256 = "991967ee93c3d8c0d90f332826a9a9f8476fa49ff039fc04e7c0c0477fdb6bae"


def test_population_is_fixed_and_spans_every_axis():
    population = rp.generate()
    assert len(population) == rp.CI_SIZE
    assert rp.digest(population) == rp.digest(rp.generate()), "the population is not reproducible"
    assert rp.digest(population) == POPULATION_SHA256, "the CI population changed; re-pin deliberately"
    for axis, values in (("field", rp.FIELDS), ("deliverable", rp.DELIVERABLES), ("inputs", rp.INPUTS),
                         ("beams", rp.BEAMS), ("level", rp.LEVELS), ("constraint", rp.CONSTRAINTS),
                         ("phrasing", rp.PHRASINGS)):
        assert {p["axes"][axis] for p in population} == set(values), axis
    assert set(rp.DELIVERABLES) == set(ir.CLAIM_KINDS)
    assert len({p["prompt"] for p in population}) > 0.9 * len(population)
    assert all(len(p["prompt"].encode()) < 32 * 1024 for p in population)


def test_population_names_no_benchmark_or_task_identity():
    for request in rp.generate():
        assert not re.search(r"bench|challenge|task label|olympics", request["prompt"], re.I), request["id"]


def test_population_has_zero_bare_refusals():
    intake = ir.Intake()
    intake.require("reader")
    planning = intake._draft is not None
    size = int(os.environ.get("RAVEL_POPULATION_SIZE", rp.CI_SIZE))
    population = rp.generate(size)
    failures, recall, shares = [], collections.Counter(), collections.Counter()
    for request in population:
        prompt = request["prompt"]
        try:
            reading = intake.read(prompt)
            contract = intake.contract(prompt) if planning else None
            plan = intake.plan(reading, contract) if planning else None
            label = intake.label(reading, plan) if planning and intake._derive is not None else None
        except Exception as exc:  # a crash is a refusal with no boundary
            failures.append(f"{request['id']}: {type(exc).__name__}: {exc}")
            continue
        problems = ir.reading_rule_errors(prompt, reading)
        if plan is not None:
            problems += ir.plan_rule_errors(reading, plan, intake.obligation_ids(contract))
        problems += ir.bare_refusal(reading, plan, label)
        if problems:
            failures.append(f"{request['id']}: {problems[:3]}")
        expected = request["expected_constraint"]
        if expected:
            recall[(expected, "asked")] += 1
            recall[(expected, "read")] += any(c["type"] == expected for c in reading["constraints"])
        if plan is None:
            continue
        kinds = {n["kind"] for n in plan["nodes"]}
        shares["registered only" if kinds <= {"operation", "input"} and
               all(n["status"] != "held" for n in plan["nodes"]) else "authored or held"] += 1
    report = {kind: f"{recall[(kind, 'read')]}/{recall[(kind, 'asked')]}"
              for kind in sorted({k for k, _ in recall})}
    print(f"population {size}: recall {report}; plans {dict(shares)}")
    assert not failures, f"{len(failures)} bare refusals or invalid records:\n  " + "\n  ".join(failures[:25])
