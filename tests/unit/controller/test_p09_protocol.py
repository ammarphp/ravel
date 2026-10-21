"""The analysis route adapter through the controller's sequence, with its ledger records (inert C1).

The controller graph calls the adapter at fixed points: ``parameters`` at compile, ``step`` when a
step's outcome is joined, ``bind`` after the prepare phase, ``checkin`` at each authority point,
``gate`` at each gate node, ``admit`` before a dispatch and ``ending`` before a qualified ending.
These tests drive that sequence for a fictional two-point scan with scripted (inert) step outputs and
an in-memory ledger that applies the ledger's evidence rules, so every P09 row the run instantiates
is accounted for: the positive branch ends with every row satisfied, and each negative branch
leaves the row it violates (or the hole it keeps) explicit.
"""
from __future__ import annotations

import sys
import types

import pytest

from ravel.controller.routes import analysis
from statistics_records import with_statistics  # noqa: E402
from p09_support import (Store, adopt, adopt_prepare, compile_plan, context, contract, grant, reading,
                              record_outcome)
from p09_support import route_analysis as evidence_route

R_ROWS = {"A06", "C03", "C14", "E04", "E05", "C10", "E14"}
L_ROWS = {"C28", "C30"}
LIMITS = {"schema_version": 1, "quantity": "signal_strength",
          "observed": {"value": 0.8, "status": "resolved", "bracket": [0.5, 1.0]},
          "expected": [{"value": v, "status": "resolved", "bracket": [v / 2, v * 2]} for v in (0.5, 0.7, 0.9, 1.2, 1.6)],
          "origin": "fixture", "notes": []}


class Ledger:
    """The ledger's record rules for the P09 rows of one plan (status changes, credit, reason, label)."""

    def __init__(self):
        self.rows = {}

    def materialise(self, plan):
        def add(row, node, **scope):
            key = row + "@run" + "".join(f"/{k}={v}" for k, v in sorted(scope.items()))
            self.rows[key] = {"id": row, "node": node, "scope": scope, "status": "pending", "evidence": None}
        for row, node in (("R07", "route.analysis"), ("C26", "route.analysis"), ("E04", "route.analysis.inputs"),
                          ("E05", "route.analysis.inputs"), ("A06", "authority.ci1"), ("C03", "authority.ci1"),
                          ("C04", "authority.ci1"), ("C14", "authority.ci1"), ("C36", "authority.ci3")):
            add(row, node)
        for step in plan["steps"]:
            for workflow in analysis.workflow_steps(step):  # one STEP row per delivered step document
                add(f"STEP-{workflow}", f"route.analysis.step[{workflow}]", step=step["id"])
            if "docs/workflow/steps/04-analyze.md" in step["instruction_sources"]:
                add("E14", "step.validate", step=step["id"], seat="producer")
            if step.get("waypoint"):
                add("C10", "route.analysis.waypoint", step=step["id"])
            for point in step.get("points") or ():
                for row in ("P04", "E24"):
                    add(row, "route.analysis.scan", step=step["id"], point=point)
                for row in ("E21", "E22", "E23", "G12", "SW33"):
                    add(row, "route.analysis.scan", step=step["id"])
            if step["kind"] == "compare":
                for row in ("C28", "C29", "C30"):
                    add(row, "step.compare", step=step["id"])

    def pending(self, store, *, node=None, step=None, point=None, **_):
        return [k for k, r in self.rows.items() if r["status"] == "pending"
                and node in (r["node"], r["node"].split("[", 1)[0])
                and (step is None or r["scope"].get("step") == step)
                and (point is None or r["scope"].get("point") == point)]

    def record_many(self, store, changes):
        for key, status, evidence in changes:
            row = self.rows[key]
            assert row["status"] == "pending" or (row["status"] == "satisfied" and status == "violated"), key
            if status == "satisfied" and row["id"] in R_ROWS:
                assert evidence.get("credit"), f"{key}: a review-gated row needs a credit"
            if status == "violated":
                assert evidence.get("reason"), f"{key}: a violation needs a reason"
                if row["id"] in L_ROWS:
                    assert evidence.get("label"), f"{key}: a labelled row needs its label"
            row.update(status=status, evidence=evidence)

    @staticmethod
    def population_equality(expected, actual):
        remaining = list(actual)
        holes = []
        for item in expected:
            if item in remaining:
                remaining.remove(item)
            else:
                holes.append(item)
        return holes

    def statuses(self, *ids):
        return {k: r["status"] for k, r in self.rows.items() if not ids or r["id"] in ids}


@pytest.fixture
def ledger(monkeypatch):
    found = Ledger()
    module = types.ModuleType("ravel.controller.ledger")
    for name in ("pending", "record_many", "population_equality"):
        setattr(module, name, getattr(found, name))
    monkeypatch.setitem(sys.modules, "ravel.controller.ledger", module)
    return found


class Run:
    """A scripted controller run of the analysis scan route (two approved points)."""

    def __init__(self, tmp_path, ledger, *, read=None):
        self.tmp, self.store = tmp_path, Store()
        self.read, self.con = read or reading(scan=True, values=(100, 200)), contract("scan")
        self.plan = compile_plan("analysis.scan", self.read, self.con)
        self.states, self.reviews, self.ledger = {}, {}, ledger
        ledger.materialise(self.plan)

    @property
    def ctx(self):
        return context(self.store, self.tmp, self.plan, self.read, self.con, self.states, self.reviews)

    def step(self, step_id):
        return next(s for s in self.plan["steps"] if s["id"] == step_id)

    def finish(self, step_id, outputs, status="completed", review=None, reason=None):
        step = self.step(step_id)
        assert analysis.admit(step, self.ctx) == [] or status != "completed"
        for path, document in outputs.items():
            adopt(self.store, self.tmp, step_id, path, document)
        found = record_outcome(self.store, step, status, review=review or {}, reason=reason)
        problems = analysis.step(step, found, self.ctx)
        self.states[step_id] = {"status": status if not problems else "failed", "attempts": 1,
                                "receipts": found["receipts"], "reason": reason}
        return problems

    def prepare(self):
        self.states.update(adopt_prepare(self.store, self.tmp, self.plan, cost_mode="scan"))
        for step in self.plan["steps"]:
            if (step.get("parameters") or {}).get("phase") == "prepare":
                assert analysis.step(step, {"status": "completed", "receipts": [f"receipt-{step['id']}"]},
                                     self.ctx) == []
        bound = analysis.bind(self.plan, self.ctx)
        if bound is not None:
            self.plan = bound
        self.reviews = {"checkin1": {"plan-critic": {"credited": True, "verdict": "accept",
                                                     "receipts": ["receipt-plan-critic"]}}}

    def approve(self):
        view = analysis.checkin("approve_plan", self.ctx)
        assert view["errors"] == [], view["errors"]
        assert analysis.gate("checkin1->execute", self.ctx) == []
        grant(self.store, "approve_plan", plan=self.plan)

    def smoke(self):
        assert self.finish("recast.smoke", {"outputs/smoke/recast.json": {
            "samples": ["smoke"], "events": 1000, "lhe_check": {"status": "PASS"},
            "qualification": {"routine": "FICTIONAL_ROUTINE_1", "status": "qualified"},
            "detector_mode": "simpleanalysis-delphes-native"}},
            review={"credited": True, "verdict": "accept", "seats": ["object-selection-mapper"]}) == []
        assert self.finish("visualize.waypoint", {"outputs/waypoint.json": {
            "summary": "The smoke cutflow agrees with the published rows.", "element": "first three cutflow rows",
            "expectation": "within ten percent", "evidence": "agree within six percent"}},
            review={"credited": True, "verdict": "accept", "seats": ["figure-critic"]}) == []
        view = analysis.checkin("go", self.ctx)
        assert view["errors"] == [], view["errors"]
        assert analysis.gate("checkin2->execute[visualize.waypoint]", self.ctx) == []
        grant(self.store, "go", decision="go", plan=self.plan)
        assert self.finish("acquire.data", {"outputs/hepdata/hepdata_manifest.json": {"tables": ["t1"]}}) == []

    def points(self, failed=()):
        rows = []
        for point in self.plan["parameters"]["grid"]["points"]:
            step_id = f"scan.point.{point['id']}"
            if point["id"] in failed:
                self.finish(step_id, {}, status="failed", reason="native stage exited 1")
                rows.append({"tag": point["id"], "parameters": point["parameters"], "status": "failed"})
                continue
            assert self.finish(step_id, {"outputs/point_result.json": with_statistics({
                "tag": point["id"], "parameters": point["parameters"], "statistic": "CLs", "limits": LIMITS,
                "detector_mode": "simpleanalysis-delphes-native"})}) == []
            rows.append({"tag": point["id"], "parameters": point["parameters"], "status": "completed"})
        return rows

    def assemble(self, rows, **overrides):
        done = [r for r in rows if r["status"] == "completed"]
        document = {"n_planned": len(self.plan["parameters"]["grid"]["points"]), "n_done": len(done),
                    "n_missing": len(rows) - len(done), "missing_tags": [r["tag"] for r in rows if r not in done],
                    "points": [{"tag": r["tag"], "statistic": "CLs"} for r in done], "point_population": rows,
                    "statistic": "CLs", "limits": LIMITS, "detector_mode": "simpleanalysis-delphes-native"}
        document.update(overrides)
        return self.finish("scan.assemble", {"outputs/scan.json": document})

    def deliver(self):
        assert self.finish("visualize.final", {"outputs/figures.json": {"figures": [{"id": "f1", "lint": "PASS"}]}}) == []
        assert self.finish("compare.reference", {"outputs/comparison.json": {
            "comparator": {"source": "published table 3"}, "lattice": "the published grid", "tolerance": 0.2,
            "basis_manifests": [{"quantity": "limit", "basis": "per-point", "unit": "fb"}] * 2, "attributions": []}}) == []
        assert self.finish("verify.mechanical", {"outputs/tier_a.json": {
            "verdict": "PASS", "numbers": [{"value": 0.8, "artifact": "scan.assemble:outputs/scan.json"}]}}) == []
        assert self.finish("verify.adversary", {"outputs/tier_b.json": {"attacks": [
            {"kind": k, "attack": f"{k} attack", "tested_by": "recomputed from accepted artifacts"}
            for k in ("basis", "acceptance", "statistics")]}}) == []
        assert self.finish("synthesize", {"outputs/results.json": {
            "headline": "No widget mass in the approved grid is excluded at 95% CLs.",
            "numbers": [{"value": 0.8, "artifact": "scan.assemble:outputs/scan.json"}], "recipe_ledger": None}}) == []
        view = analysis.checkin("final", self.ctx)
        assert view["errors"] == [], view["errors"]
        return analysis.gate("checkin3->deliver", self.ctx)


def test_c1_positive_branch_reaches_delivery_with_every_route_row_satisfied(tmp_path, ledger):
    """Inert C1: intake -> prepare -> CI1 -> smoke -> waypoint -> CI2 -> two-point scan -> CI3 -> deliver."""
    run = Run(tmp_path, ledger)
    run.prepare()
    run.approve()
    run.smoke()
    assert run.assemble(run.points()) == []
    assert run.deliver() == []
    statuses = ledger.statuses()
    open_rows = {k: v for k, v in statuses.items() if v != "satisfied"}
    assert open_rows == {}, open_rows
    assert {k.split("@")[0] for k in statuses} >= {"STEP-01-environment", "STEP-02-inputs", "STEP-03-generate",
                                                   "STEP-04-analyze", "STEP-05-visualize", "STEP-06-acquire-data",
                                                   "STEP-07-exclude", "STEP-08-scan", "STEP-09-verify", "E14"}
    assert len([k for k in statuses if k.startswith("P04@")]) == 2


def test_c1_a06_c03_refused_checkin1_holds_before_any_effect(tmp_path, ledger):
    """Negative: an incomplete CHECK-IN 1 is not presented; its rows are violated with the reason."""
    run = Run(tmp_path, ledger)
    run.states.update(adopt_prepare(run.store, tmp_path, run.plan, cost_mode="scan", empty="figure_target.json"))
    run.plan = analysis.bind(run.plan, run.ctx) or run.plan
    run.reviews = {"checkin1": {"plan-critic": {"credited": True, "verdict": "accept", "receipts": ["r"]}}}
    view = analysis.checkin("approve_plan", run.ctx)
    assert any(e["row"] == "C03" for e in view["errors"])
    assert ledger.statuses("C03") == {"C03@run": "violated"}
    assert ledger.statuses("A06", "C14") == {"A06@run": "pending", "C14@run": "pending"}
    assert analysis.admit(run.step("recast.smoke"), run.ctx)


def test_c1_a08_full_rung_before_go_is_refused(tmp_path, ledger):
    run = Run(tmp_path, ledger)
    run.prepare()
    run.approve()
    point = next(s for s in run.plan["steps"] if s["id"].startswith("scan.point."))
    errors = analysis.admit(point, run.ctx)
    assert "checkin2_go_missing" in {e["code"] for e in errors}
    assert ledger.statuses("A08") == {}  # A08 is enforced at dispatch; the refusal is the evidence


def test_c1_sw33_p04_e24_omitted_scan_point_stays_an_explicit_hole(tmp_path, ledger):
    """Negative: one point fails; the assembly cannot claim the grid and the ending keeps the hole explicit."""
    run = Run(tmp_path, ledger)
    run.prepare()
    run.approve()
    run.smoke()
    failed = run.plan["parameters"]["grid"]["points"][1]["id"]
    rows = run.points(failed=(failed,))
    claimed = [dict(r, status="completed") for r in rows]
    problems = run.assemble(claimed, n_missing=0, missing_tags=[])
    assert {"scan_point_substituted", "scan_coverage_overclaimed"} <= {e["code"] for e in problems}
    population = analysis.ending("budget exhausted", run.ctx)
    assert population["holes"] == [failed]
    holes = {k: r for k, r in ledger.rows.items() if r["id"] in ("P04", "E24") and r["scope"].get("point") == failed}
    assert holes and all(r["status"] == "violated" and "explicit hole" in r["evidence"]["reason"]
                         and "failed" in r["evidence"]["reason"] for r in holes.values())
    record = run.store.scan("analysis-scan-population")[-1]["record"]
    assert record["holes"][0]["point"] == failed and record["holes"][0]["status"] == "failed"


def test_c1_p04_e24_point_never_dispatched_is_an_explicit_hole(tmp_path, ledger):
    """A budget that ends the run before a point runs still leaves that point named, with its status."""
    run = Run(tmp_path, ledger)
    run.prepare()
    run.approve()
    run.smoke()
    population = analysis.ending("the wall-time budget is exhausted", run.ctx)
    assert sorted(population["holes"]) == sorted(p["id"] for p in run.plan["parameters"]["grid"]["points"])
    assert {r["status"] for r in ledger.rows.values() if r["id"] == "P04"} == {"violated"}


def test_c26_full_simulation_request_is_refused_before_any_effect(tmp_path, ledger):
    """C26 through the protocol: a full detector simulation was requested and the route analysis chose a
    fast response; the route-analysis step is refused, CHECK-IN 1 cannot pass and C26 records the refusal."""
    run = Run(tmp_path, ledger, read=reading(scan=True, values=(100, 200), full_simulation=True))
    run.states.update(adopt_prepare(run.store, tmp_path, run.plan, cost_mode="scan"))
    refused = analysis.step(run.step("inputs.route"), {"status": "completed", "receipts": ["r"]}, run.ctx)
    assert "fidelity_delivered_below_request" in {e["code"] for e in refused}
    run.plan = analysis.bind(run.plan, run.ctx) or run.plan
    errors = analysis.gate("checkin1->execute", run.ctx)
    assert any(e["row"] == "C26" for e in errors)
    assert ledger.statuses("C26") == {"C26@run": "violated"}
    assert analysis.admit(run.step("recast.smoke"), run.ctx)


def test_g12_refused_attempt_that_will_be_retried_records_nothing(tmp_path, ledger):
    """A step's rows have one instance and a violation is final: only the last attempt records one."""
    run = Run(tmp_path, ledger)
    run.prepare()
    run.approve()
    step = run.step("recast.smoke")
    adopt(run.store, tmp_path, step["id"], "outputs/smoke/recast.json", {"samples": ["smoke"], "events": 10})
    def mine():
        return {r["status"] for r in ledger.rows.values()
                if r["id"] in ("STEP-03-generate", "E14") and r["scope"].get("step") == step["id"]}
    first = record_outcome(run.store, step, "completed", attempt=1)
    assert analysis.step(step, first, run.ctx)  # refused: no qualification
    assert mine() == {"pending"}
    last = record_outcome(run.store, step, "completed", attempt=step["attempt_limit"])
    assert analysis.step(step, last, run.ctx)
    assert mine() == {"violated"}


def test_sw33_is_recorded_at_assembly_not_at_each_point(tmp_path, ledger):
    run = Run(tmp_path, ledger)
    run.prepare()
    run.approve()
    run.smoke()
    rows = run.points()
    assert set(ledger.statuses("SW33").values()) == {"pending"}
    assert set(ledger.statuses("G12").values()) == {"satisfied"}
    assert run.assemble(rows) == []
    assert set(ledger.statuses("SW33").values()) == {"satisfied"}


def test_sw33_is_recorded_at_a_bounded_ending_with_explicit_holes(tmp_path, ledger):
    run = Run(tmp_path, ledger)
    run.prepare()
    run.approve()
    run.smoke()
    analysis.ending("the deadline margin is reached", run.ctx)
    assert set(ledger.statuses("SW33").values()) == {"satisfied"}
    assert set(ledger.statuses("P04").values()) == {"violated"}


def test_bind_keeps_the_request_grid_and_prepare_steps(tmp_path, ledger):
    run = Run(tmp_path, ledger)
    before = {s["id"]: s for s in run.plan["steps"] if s["parameters"].get("phase") == "prepare"}
    grid_before = run.plan["parameters"]["grid"]["sha256"]
    run.states.update(adopt_prepare(run.store, tmp_path, run.plan, cost_mode="scan"))
    adopt(run.store, tmp_path, "inputs.route", "outputs/route_analysis.json",
          dict(evidence_route(), scan_grid={"axes": [{"name": "m_widget", "values": [100, 200, 300, 400]}]}))
    bound = analysis.bind(run.plan, run.ctx)
    assert bound is not None and bound["revision"] == run.plan["revision"] + 1
    assert bound["parameters"]["grid"]["sha256"] == grid_before  # the request fixed the grid
    assert {s["id"]: s for s in bound["steps"] if s["parameters"].get("phase") == "prepare"} == before
    assert len([s for s in bound["steps"] if s["id"].startswith("scan.point.")]) == 2
