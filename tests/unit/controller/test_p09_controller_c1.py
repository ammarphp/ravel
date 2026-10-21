"""Inert C1 through the real ``controller.run`` graph: the analysis scan route from intake to the sink.

The controller core (P01) runs its own graph: route selection over the installed route specs,
compilation with this route's adapter, the prepare phase, binding, plan review, CHECK-IN 1, the
smoke rung, the waypoint and CHECK-IN 2, the scan points, the final review, CHECK-IN 3 and the
sink. Workers are inert: the stand-in step graph adopts scripted outputs with their custody
records, so the route adapter checks real bytes. Services are the interface fakes (machine authority,
a ledger that passes, a sink that records). Nothing calls a model, a provider or the network.

This file needs the controller core and its interface fakes; without them (a package worktree that
predates the core) it is skipped at collection.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("ravel.controller.graph")
fakes = pytest.importorskip("fakes")

from ravel.controller import graph, routes  # noqa: E402
from ravel.controller.routes.analysis import scan  # noqa: E402
from p09_support import adopt, contract, evidence_set, reading  # noqa: E402
from statistics_records import with_statistics  # noqa: E402

LIMITS = {"schema_version": 1, "quantity": "signal_strength",
          "observed": {"value": 0.8, "status": "resolved", "bracket": [0.5, 1.0]},
          "expected": [{"value": v, "status": "resolved", "bracket": [v / 2, v * 2]} for v in (0.5, 0.7, 0.9, 1.2, 1.6)],
          "origin": "fixture", "notes": []}
REQUEST = b"Scan the fictional widget mass over the stated grid and report 95% CLs exclusion limits with a figure."
HOLLOW = set()  # step ids whose scripted evidence is emptied (negative branches)


def _records(store, kind):
    return [entry["record"] for entry in store.scan(kind)]


class CompleteFixtureSink(fakes.FakeSink):
    """An inspectable inert receipt retaining the base sink's architecture verdict."""

    def deliver(self, store, plan):
        receipt = super().deliver(store, plan)
        state = fakes.final_state(store)
        receipt.update({
            "host": {"run_id": store.run_id, "fixture": "in-process controller stand-ins"},
            "work": {"plan_sha256": plan["sha256"], "waves": _records(store, "wave-result")},
            "costs": {"budget": state.get("budget") or {}, "custody": [r for r in _records(store, "custody")
                      if r.get("step_id") == "inputs.cost"]},
            "ledger": {"transitions": _records(store, "transition"), "gates": _records(store, "gate")},
            "authority": _records(store, "authority"),
            "instructions": {"sources": sorted({source for step in plan["steps"]
                                                 for source in step["instruction_sources"]}),
                             "reviews": _records(store, "review")},
            "confinement": {"fixture": "inert step graph", "custody": _records(store, "custody")},
            "population": scan.population(plan, {"state": state}),
        })
        # Preserve the original receipt and append the supplemented fixture.
        receipt["id"] = store.append("receipt", {k: v for k, v in receipt.items() if k != "id"})
        return receipt


def _outputs(step, plan_parameters):
    """The inert worker's outputs for ``step`` (the evidence each analysis adapter checks)."""
    prepare = evidence_set()
    if step["id"] in HOLLOW:
        return {path: {} for path in prepare.get(step["id"], {})}
    if step["id"] in prepare:
        rows = dict(prepare[step["id"]])
        if step["id"] == "inputs.cost":
            grid = (plan_parameters or {}).get("grid") or {}
            rows["outputs/cost_preflight.json"] = dict(rows["outputs/cost_preflight.json"], mode="scan",
                                                       points=len(grid.get("points") or ()))
        return rows
    mode = "simpleanalysis-delphes-native"
    if step["id"] == "recast.smoke":
        return {"outputs/smoke/recast.json": {"samples": ["smoke"], "events": 1000, "lhe_check": {"status": "PASS"},
                                              "qualification": {"routine": "FICTIONAL_ROUTINE_1", "status": "qualified"},
                                              "detector_mode": mode}}
    if step["id"] == "visualize.waypoint":
        return {"outputs/waypoint.json": {"summary": "The smoke cutflow agrees.", "element": "first three cutflow rows",
                                           "expectation": "within ten percent", "evidence": "within six percent"}}
    if step["id"] == "acquire.data":
        return {"outputs/hepdata/hepdata_manifest.json": {"tables": ["t1"]}}
    if step["id"].startswith("scan.point."):
        item = step["parameters"]["item"]
        return {"outputs/point_result.json": with_statistics({"tag": item["id"], "parameters": item["parameters"],
                                                              "statistic": "CLs", "limits": LIMITS,
                                                              "detector_mode": mode})}
    if step["id"] == "scan.assemble":
        rows = [{"tag": p["id"], "parameters": p["parameters"], "status": "completed"}
                for p in plan_parameters["grid"]["points"]]
        return {"outputs/scan.json": {"n_planned": len(rows), "n_done": len(rows), "n_missing": 0, "missing_tags": [],
                                      "points": [{"tag": r["tag"], "statistic": "CLs"} for r in rows],
                                      "point_population": rows, "statistic": "CLs", "limits": LIMITS,
                                      "detector_mode": mode}}
    if step["id"] == "visualize.final":
        return {"outputs/figures.json": {"figures": [{"id": "f1", "lint": "PASS"}]}}
    if step["id"] == "compare.reference":
        return {"outputs/comparison.json": {"comparator": {"source": "published table"}, "lattice": "grid",
                                            "tolerance": 0.2, "attributions": [],
                                            "basis_manifests": [{"quantity": "q", "basis": "b", "unit": "u"}] * 2}}
    if step["id"] == "verify.mechanical":
        return {"outputs/tier_a.json": {"verdict": "PASS", "numbers": [{"value": 0.8, "artifact": "scan.assemble:outputs/scan.json"}]}}
    if step["id"] == "verify.adversary":
        return {"outputs/tier_b.json": {"attacks": [{"kind": k, "attack": k, "tested_by": "recomputed"}
                                                    for k in ("basis", "acceptance", "statistics")]}}
    if step["id"] == "synthesize":
        return {"outputs/results.json": {"headline": "No grid point is excluded at 95% CLs.",
                                         "numbers": [{"value": 0.8, "artifact": "scan.assemble:outputs/scan.json"}]}}
    return {}


@pytest.fixture
def controller(tmp_path, monkeypatch):
    fakes.isolate(tmp_path, monkeypatch)
    # The controller's intake pins its own inputs contract at agent-layer epoch two (both intake paths); without it
    # the directory is an epoch-one layout and the run holds before any step (SW26).
    read, con = reading(scan=True, values=(100, 200)), contract("scan", agent_layer_epoch=2)
    con["prompt"] = REQUEST.decode()

    def intake(run_dir, prompt, output_workspace=None):  # the writer's own signature (no declared outputs here)
        inputs = run_dir / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        (inputs / "reading.json").write_text(json.dumps(read))
        (inputs / "task_contract.json").write_text(json.dumps(con))
        return {"contract": con, "reading": read, "contract_bytes": (inputs / "task_contract.json").read_bytes(),
                "reading_bytes": (inputs / "reading.json").read_bytes(), "label": None, "contract_errors": [],
                "plan_error": None, "intake_error": None, "layout": "minimal"}
    monkeypatch.setattr(graph, "_write_run_intake", intake)
    original = fakes.step_run

    def step_run(store, step, context):
        if context.get("run_dir"):  # review seats of the controller get no scripted outputs (none are listed)
            rows = [r["record"] for r in store.scan("plan") if r["record"].get("plan_sha256") == context.get("plan_sha256")]
            plan = json.loads(store.get_blob(rows[-1]["blob"]).decode()) if rows else {}
            for path, document in _outputs(step, plan.get("parameters") or {}).items():
                adopt(store, context["run_dir"], step["id"], path, document)
        return original(store, step, context)
    monkeypatch.setattr(fakes, "step_run", step_run)
    fakes.no_checkpoint_seat(monkeypatch)  # the stand-ins' passing gates take no CHECK-IN 2 RDJ credit
    with fakes.stand_in_graphs():
        yield tmp_path


def test_c1_scan_route_runs_from_intake_to_the_sink(controller):
    with fakes.installed(sink=CompleteFixtureSink()) as services:
        store, observation = fakes.drive_request(controller, REQUEST)
    values = fakes.final_state(store)
    assert values["route"]["id"] == "analysis.scan"
    dispatched = [step for step, _ in fakes.DISPATCHED]
    prepare = ["env", "inputs.census", "inputs.route", "inputs.traps", "inputs.figures", "inputs.cost"]
    first_review = dispatched.index(next(s for s in dispatched if s.startswith("review.") or s == "plan_review"))
    assert set(prepare) <= set(dispatched[:first_review])
    assert dispatched.index("recast.smoke") > first_review
    points = [s for s in dispatched if s.startswith("scan.point.")]
    assert len(points) == 2 and dispatched.index("visualize.waypoint") < min(dispatched.index(p) for p in points)
    assert values["plan"]["source"] == "bind"
    plan = graph.current_plan(values, store)
    grid = plan["parameters"]["grid"]
    critics = [step for step, _ in fakes.PACKETS if step.get("role") == "plan-critic"]
    assert len(critics) == 1
    assert {item["id"] for item in critics[0]["parameters"]["review_items"]} == {
        "ci1.census", "ci1.route", "ci1.figures", "ci1.cost", "ci1.flags", "ci1.substance"}
    packets = [(step, ctx) for step, ctx in fakes.PACKETS if step["id"].startswith("scan.point.")]
    assert len(packets) == len(grid["points"])
    by_point = {step["parameters"]["item"]["id"]: (step, ctx) for step, ctx in packets}
    assert set(by_point) == {point["id"] for point in grid["points"]}
    receipts = []
    for point in grid["points"]:
        step, ctx = by_point[point["id"]]
        assert step["points"] == [point["id"]] and ctx["point"] == point["id"]
        assert step["parameters"]["item"]["parameters"] == point["parameters"]
        assert step["parameters"]["grid_sha256"] == grid["sha256"]
        assert ctx["plan_sha256"] == plan["sha256"]
        outcome = values["steps"][step["id"]]
        assert outcome["status"] == "completed" and outcome["attempts"] == 1
        assert outcome["receipts"]
        receipts.extend(outcome["receipts"])
    assert len(receipts) == len(set(receipts)) == len(grid["points"])
    for record in _records(store, "authority"):
        if record.get("kind") in ("approve_plan", "go"):
            assert record["subject"]["pins"]["plan_sha256"] == plan["sha256"]
    requests = [c for c in services["authority"].calls if c[0] == "request"]
    ci1 = next(c[2]["view"] for c in requests if c[1] == "approve_plan")
    assert {"preamble", "resource_census", "gallery", "figure_target", "method", "scan_grid"} <= set(ci1["required_sections"])
    go = next(c[2]["view"] for c in requests if c[1] == "go")
    assert any(k.startswith("waypoint:") for k in go["pins"])
    assert observation["terminal"] is None, observation
    assert services["sink"].calls[-1][0] == "deliver"
    receipt = _records(store, "receipt")[-1]
    assert {"host", "work", "costs", "ledger", "authority", "instructions", "confinement", "population"} <= receipt.keys()
    assert all(receipt[key] for key in ("host", "work", "costs", "ledger", "authority", "instructions", "confinement"))
    assert receipt["host"]["run_id"] == store.run_id
    assert receipt["work"]["waves"] and receipt["costs"]["custody"]
    assert receipt["ledger"]["transitions"] and receipt["ledger"]["gates"]
    assert receipt["instructions"]["sources"] and receipt["instructions"]["reviews"]
    assert receipt["confinement"]["custody"]
    assert receipt["plan_sha256"] == receipt["work"]["plan_sha256"] == plan["sha256"]
    assert receipt["population"]["grid_sha256"] == grid["sha256"]
    assert set(receipt["population"]["completed"]) == set(by_point)
    assert receipt["population"]["holes"] == []
    assert receipt["qualified"] is False and receipt["architecture_complete"] is False
    assert not receipt.get("accepted")


def test_c1_incomplete_checkin1_ends_qualified_before_any_production_step(controller):
    """Negative: an empty figure target leaves CHECK-IN 1 incomplete; the run ends qualified, nothing produced."""
    HOLLOW.add("inputs.figures")
    try:
        with fakes.installed() as services:
            store, observation = fakes.drive_request(controller, REQUEST)
    finally:
        HOLLOW.clear()
    dispatched = [step for step, _ in fakes.DISPATCHED]
    assert not [s for s in dispatched if s in ("recast.smoke", "run.full") or s.startswith("scan.point.")]
    assert observation["terminal"]["status"] == "qualified"
    assert services["sink"].calls[-1][0] == "bounded_end"
    assert not [call for call in services["authority"].calls if call[:2] == ("request", "approve_plan")]


@pytest.mark.parametrize("decision", ["adjust", "stop"])
def test_c1_no_scan_dispatch_without_checkin2_go(controller, decision):
    authority = fakes.FakeAuthority(answers={"go": decision})
    with fakes.installed(authority=authority) as services:
        store, observation = fakes.drive_request(controller, REQUEST)
    assert any(call[:2] == ("request", "go") for call in authority.calls)
    assert not [step for step, _ in fakes.DISPATCHED if step.startswith("scan.point.") or step == "run.full"]
    assert not [r for r in _records(store, "authority") if r.get("kind") == "go" and r.get("decision") == "go"]
    assert observation["terminal"]["status"] == "qualified"
    assert services["sink"].calls[-1][0] == "bounded_end"


@pytest.mark.parametrize("failure", ["failed", "budget_exhausted"])
def test_c1_point_failure_keeps_holes_in_qualified_ending(controller, failure):
    # A failed point exhausts its retries; an exhausted dependency leaves all points unrun.
    from p09_support import compile_plan
    plan = compile_plan("analysis.scan", reading(scan=True, values=(100, 200)), contract("scan"))
    step_id = ("acquire.data" if failure == "budget_exhausted" else
               next(step["id"] for step in plan["steps"] if step["id"].startswith("scan.point.")))
    fakes.SCRIPT[step_id] = [{"status": failure, "reason": "scripted bounded C1 failure"}] * 2
    with fakes.installed() as services:
        store, observation = fakes.drive_request(controller, REQUEST)
    assert observation["terminal"]["status"] == "qualified"
    assert services["sink"].calls[-1][0] == "bounded_end"
    population = _records(store, "analysis-scan-population")[-1]
    assert population["holes"]
    assert {row["point"] for row in population["holes"]} == set(population["expected"]) - set(population["completed"])
    if failure == "failed":
        assert any(row["step"] == step_id and row["status"] == "failed" for row in population["holes"])
    else:
        assert len(population["holes"]) == len(population["expected"])
        assert not [step for step, _ in fakes.DISPATCHED if step.startswith("scan.point.")]
    receipt = _records(store, "receipt")[-1]
    assert receipt["qualified"] is True and receipt["architecture_complete"] is False
