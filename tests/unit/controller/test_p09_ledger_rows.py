"""The P09 rows in the real obligation ledger: instantiated by the analysis plans, discharged by the adapter.

The ledger (P02) materialises the installed catalogue's rows from a compiled analysis plan; the route
adapter records them with the evidence the catalogue's class requires (a credit for review-gated rows,
a reason for violations). This file needs the ledger and the controller's run store; a worktree
without them skips it at collection.
"""
from __future__ import annotations

import pytest

ledger = pytest.importorskip("ravel.controller.ledger")
store_module = pytest.importorskip("ravel.controller.store")

from ravel.controller.ledger import state as state_module  # noqa: E402
from ravel.controller.routes import analysis  # noqa: E402
from p09_support import (adopt_prepare, compile_plan, context, contract, grant, reading,  # noqa: E402
                              record_outcome)

RUN = "run-p09-ledger"


@pytest.fixture
def store(tmp_path):
    found = store_module.RunStore(RUN, root=tmp_path / "store")
    try:
        yield found
    finally:
        state_module.forget(found)


def _materialise(store, spec_id, task_mode):
    read = reading(scan=spec_id == "analysis.scan")
    con = contract(task_mode)
    plan = compile_plan(spec_id, read, con)
    ledger.materialise(store, "intake", {"run_id": store.run_id, "task_mode": task_mode, "route": spec_id,
                                         "deliverables": [d["id"] for d in read["deliverables"]]})
    ledger.materialise(store, "plan", {"plan": plan})
    return plan, read, con


def _rows(store, node, **scope):
    return sorted(k.split("@", 1)[0] for k in ledger.pending(store, node=node, **scope))


def test_scan_plan_instantiates_every_point_and_scan_row(store):
    plan, _, _ = _materialise(store, "analysis.scan", "scan")
    points = [s for s in plan["steps"] if s["id"].startswith("scan.point.")]
    for step in points:
        point = step["points"][0]
        assert _rows(store, "route.analysis.scan", step=step["id"], point=point) == ["E24", "P04"]
        assert set(_rows(store, "route.analysis.scan", step=step["id"])) >= {"E21", "E22", "E23", "G12", "SW33"}
    assert _rows(store, "route.analysis") == ["C26", "R07"]
    assert _rows(store, "route.analysis.inputs") == ["E04", "E05"]
    assert _rows(store, "route.analysis.waypoint", step="visualize.waypoint") == ["C10"]
    assert set(_rows(store, "authority.ci1")) >= {"A06", "C03", "C04", "C14"}
    assert "ROUTE-scan" in _rows(store, "route.scan")


def test_every_workflow_step_document_instantiates_its_step_row(store):
    plan, _, _ = _materialise(store, "analysis", "reproduce")
    for step in plan["steps"]:
        for workflow_step in analysis.workflow_steps(step):
            assert _rows(store, f"route.analysis.step[{workflow_step}]", step=step["id"]) == [f"STEP-{workflow_step}"]


def test_adapter_discharges_checkin1_rows_with_the_ledger_rules(store, tmp_path):
    plan, read, con = _materialise(store, "analysis", "reproduce")
    states = adopt_prepare(store, tmp_path, plan)
    reviews = {"checkin1": {"plan-critic": {"credited": True, "verdict": "accept", "receipts": ["r1"]}}}
    ctx = context(store, tmp_path, plan, read, con, states, reviews)
    for step in plan["steps"]:
        if step["parameters"].get("phase") == "prepare":
            assert analysis.step(step, {"status": "completed", "attempt": 1, "receipts": ["r"]}, ctx) == []
    plan = analysis.bind(plan, ctx) or plan
    view = analysis.checkin("approve_plan", context(store, tmp_path, plan, read, con, states, reviews))
    assert view["errors"] == []
    assert analysis.gate("checkin1->execute", context(store, tmp_path, plan, read, con, states, reviews)) == []
    assert not set(_rows(store, "authority.ci1")) & {"A06", "C03", "C04", "C14"}
    assert _rows(store, "route.analysis") == []
    assert _rows(store, "route.analysis.inputs") == []
    assert not [r for r in store.scan("route-ledger-refusal")]


def test_ending_keeps_unfinished_points_as_explicit_violations(store, tmp_path):
    plan, read, con = _materialise(store, "analysis.scan", "scan")
    states = adopt_prepare(store, tmp_path, plan, cost_mode="scan")
    grant(store, "approve_plan", plan=plan)
    population = analysis.ending("the wall-time budget is exhausted", context(store, tmp_path, plan, read, con, states))
    assert len(population["holes"]) == len(plan["parameters"]["grid"]["points"])
    summary = ledger.summary(store)
    violated = {v["id"] for v in summary["violations"]}
    assert {"P04", "E24"} <= violated
    assert all("explicit hole" in v["reason"] for v in summary["violations"] if v["id"] in ("P04", "E24"))
    assert not [r for r in store.scan("route-ledger-refusal")]


def test_refused_point_on_its_last_attempt_violates_its_rows_with_the_reason(store, tmp_path):
    plan, read, con = _materialise(store, "analysis.scan", "scan")
    states = adopt_prepare(store, tmp_path, plan, cost_mode="scan")
    point = next(s for s in plan["steps"] if s["id"].startswith("scan.point."))
    failed = record_outcome(store, point, "failed", attempt=point["attempt_limit"], reason="native stage exited 1")
    analysis.step(point, failed, context(store, tmp_path, plan, read, con, states))
    summary = ledger.summary(store)
    reasons = [v["reason"] for v in summary["violations"] if v["id"] == "P04"]
    assert reasons and "native stage exited 1" in reasons[0]
