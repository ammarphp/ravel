"""Fixed-route final seats follow the shared typed review policy."""
from copy import deepcopy

import pytest

import fakes
from ravel.controller.routes import compiler
from ravel.workflow import request_plan, review_points


TRIAD = ["physics-critic", "skeptical-verifier", "physics-decider"]
# A generated-prediction claim also derives the conditional absolute-prediction staffing: spawn row K5
# (two re-derivers beside the RP5 normalization auditor) and K6 (the comparative reviewer).
PREDICTION_STAFFING = ["re-deriver", "comparative-reviewer"]


def _spec(seats=None):
    checkins = [{"id": "checkin1", "sections": ["plan"], "seats": ["plan-critic"]}]
    if seats is not None:
        checkins.append({"id": "checkin3", "sections": ["results"], "seats": seats})
    return fakes._spec("fixture-seats", 6, {"field": "task_mode", "eq": "calculate"},
                       [fakes.make_step("s1", outputs=["outputs/result.json"])], [], checkins=checkins)


def _request(prediction):
    return {"nodes": [], "inputs": [], "edges": [], "claims": [{
        "id": "C1", "kind": "prediction" if prediction else "calculation",
        "basis_declared": ["generated_prediction"] if prediction else [],
        "deliverable": {"artifact": "table"}}]}


def _compile(monkeypatch, *, prediction=True, contract=None, seats=None, spec=None):
    source = _request(prediction)
    monkeypatch.setattr(request_plan, "draft", lambda reading, contract: deepcopy(source))
    return compiler.compile(spec or _spec(seats), {}, {"agent_layer_epoch": 2} if contract is None else contract)


def _seats(plan):
    return next(c["seats"] for c in plan["checkins"] if c["id"] == "checkin3")


def test_prediction_adds_normalization_seat_and_default_final_triad(monkeypatch):
    plan = _compile(monkeypatch)
    assert _seats(plan) == TRIAD + ["normalization-auditor", *PREDICTION_STAFFING, "assumption-auditor"]
    assert next(c for c in plan["checkins"] if c["id"] == "checkin3")["seat_counts"] == {"re-deriver": 2}
    assert compiler.plan_errors(plan, _spec()) == []


def test_nonprediction_does_not_invent_normalization_seat(monkeypatch):
    plan = _compile(monkeypatch, prediction=False)
    assert _seats(plan) == TRIAD + ["assumption-auditor"]


@pytest.mark.parametrize("contract", [None, {}, {"agent_layer_epoch": 1}])
def test_legacy_contract_does_not_invent_review_obligations(monkeypatch, contract):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy compilation must not derive epoch-two policy")
    monkeypatch.setattr(request_plan, "draft", forbidden)
    spec = _spec()
    plan = compiler.compile(spec, {}, contract)
    assert plan["checkins"] == spec["checkins"]


def test_declared_alias_seats_and_sections_preserved_without_duplicate_roles(monkeypatch):
    seats = ["physics-reviewer", "normalization-auditor", "skeptical-verifier"]
    spec = _spec(seats)
    original = deepcopy(spec)
    plan = _compile(monkeypatch, spec=spec)
    assert _seats(plan) == seats + ["physics-decider", *PREDICTION_STAFFING, "assumption-auditor"]
    assert plan["checkins"][-1]["sections"] == ["results"]
    assert spec == original
    assert compiler.conformance_errors(plan, spec) == []


def test_seats_are_in_plan_digest_and_policy_derivation_is_used(monkeypatch):
    positive = _compile(monkeypatch)
    negative = _compile(monkeypatch, prediction=False)
    assert positive["sha256"] != negative["sha256"]
    assert positive["sha256"] == compiler.plan_sha256(positive)
    positive["checkins"][-1]["seats"].remove("normalization-auditor")
    assert positive["sha256"] != compiler.plan_sha256(positive)


def test_only_blocking_final_controller_compatible_policy_points_add_seats(monkeypatch):
    points = [
        {"id": "RP10:fixture-figure", "blocking": True, "mode": "specialist", "gate": "delivery", "row": 10,
         "roles": [{"role": "figure-critic", "count": 1}, {"role": "figure-critic", "count": 1}]},
        {"id": "RP10:fixture-trap", "blocking": False, "mode": "specialist", "gate": "delivery", "row": 10,
         "roles": [{"role": "trap-auditor", "count": 1}]},
        {"id": "RP6:fixture-producer", "blocking": True, "mode": "producer", "gate": "delivery", "row": 6,
         "roles": [{"role": "analysis-author", "count": 1}]},
        {"id": "RP1:fixture-plan", "blocking": True, "mode": "voting", "gate": "approve_plan", "row": 1,
         "roles": [{"role": "plan-critic", "count": 1}]},
    ]
    seen = []
    def derive(facts):
        seen.append(facts)
        return deepcopy(points)
    monkeypatch.setattr(review_points, "derive", derive)
    plan = _compile(monkeypatch, contract={"agent_layer_epoch": 2, "delegated": True})
    # The core points are replaced; the conditional spawn-row staffing (K5, K6, K8) is derived separately. With no
    # core RP5 point, K5's own normalization auditor is the one that adds that seat.
    assert _seats(plan) == TRIAD + ["figure-critic", "re-deriver", "normalization-auditor", "comparative-reviewer",
                                    "assumption-auditor"]
    assert seen[0]["plan"] == _request(True)
    assert seen[0]["contract"] == {"agent_layer_epoch": 2, "delegated": True}
    assert seen[0]["delegated"] is True
