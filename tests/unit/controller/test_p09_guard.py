"""Route refusals at dispatch and at controller transitions (R07, A08, E21, C26)."""
from __future__ import annotations

from copy import deepcopy

import pytest

from ravel.controller.routes import analysis
from ravel.controller.routes.analysis import fidelity, guard
from p09_support import (Store, adopt, adopt_prepare, compile_plan, context, contract, grant, reading,
                              route_analysis)


def _setup(tmp_path, *, task_mode="reproduce", read=None, con=None, prepare=True, **adopt_options):
    store = Store()
    read = read or reading(scan=task_mode == "scan")
    con = con or contract(task_mode)
    plan = compile_plan("analysis.scan" if task_mode == "scan" else "analysis", read, con)
    states = adopt_prepare(store, tmp_path, plan, **adopt_options) if prepare else {}
    plan = analysis.bind(plan, context(store, tmp_path, plan, read, con, states)) or plan
    return store, plan, read, con, states


def _step(plan, step_id):
    return next(s for s in plan["steps"] if s["id"] == step_id)


def _codes(errors):
    return {e["code"] for e in errors}


# ---- R07: generation never precedes the 02-inputs evidence and CHECK-IN 1 -------------------------

def test_r07_generation_refused_without_inputs_evidence_and_checkin1(tmp_path):
    """R07: a reproduction plan's smoke generation cannot be dispatched before 02-inputs evidence and CI1."""
    store, plan, read, con, _ = _setup(tmp_path, prepare=False)
    errors = guard.admit(_step(plan, "recast.smoke"), context(store, tmp_path, plan, read, con, {}))
    assert {"prepare_step_open", "checkin1_missing"} <= _codes(errors)
    assert {e["row"] for e in errors} == {"R07"}


def test_r07_generation_refused_after_inputs_but_before_checkin1(tmp_path):
    store, plan, read, con, states = _setup(tmp_path)
    errors = guard.admit(_step(plan, "recast.smoke"), context(store, tmp_path, plan, read, con, states))
    assert _codes(errors) == {"checkin1_missing"}


def test_r07_generation_admitted_after_inputs_evidence_and_checkin1(tmp_path):
    store, plan, read, con, states = _setup(tmp_path)
    grant(store, "approve_plan", plan=plan)
    assert guard.admit(_step(plan, "recast.smoke"), context(store, tmp_path, plan, read, con, states)) == []


@pytest.mark.parametrize("mutation", ["stale", "declined", "no_effect", "other_run"])
def test_r07_historical_or_non_authorizing_checkin1_does_not_admit_generation(tmp_path, mutation):
    store, plan, read, con, states = _setup(tmp_path)
    grant(store, "approve_plan", plan=plan)
    extra = {}
    if mutation == "stale":
        extra["subject"] = {"pins": {"plan_sha256": "0" * 64}}
    elif mutation == "declined":
        extra["decision"] = "reject"
    elif mutation == "no_effect":
        extra["authorizes_effects"] = False
    else:
        extra["run_id"] = "other-run"
    grant(store, "approve_plan", plan=plan, **extra)
    assert "checkin1_missing" in _codes(guard.admit(_step(plan, "recast.smoke"),
                                                  context(store, tmp_path, plan, read, con, states)))


def test_r07_approved_deviation_chain_renews_plan_authority(tmp_path):
    store, plan, read, con, states = _setup(tmp_path)
    approval = grant(store, "approve_plan", plan=plan)
    changed = deepcopy(plan)
    changed["sha256"] = "1" * 64
    grant(store, "deviation", plan=changed, subject={"pins": {
        "plan_sha256": changed["sha256"], "previous_plan_sha256": plan["sha256"], "approve_plan": approval}})
    assert guard.admit(_step(changed, "recast.smoke"), context(store, tmp_path, changed, read, con, states)) == []


def test_r07_generation_refused_when_inputs_evidence_does_not_hold(tmp_path):
    """The 02-inputs evidence is checked, not just its presence: a trap hit without a flag holds generation."""
    store, plan, read, con, states = _setup(tmp_path)
    grant(store, "approve_plan", plan=plan)
    from p09_support import trap_sweep_record
    sweep = trap_sweep_record()
    sweep["traps_hit"][0]["flag_number"] = None
    next(v for v in sweep["verdicts"] if v["id"] == "T8")["flag_number"] = None
    adopt(store, tmp_path, "inputs.traps", "outputs/trap_sweep.json", sweep)
    errors = guard.admit(_step(plan, "recast.smoke"), context(store, tmp_path, plan, read, con, states))
    assert "trap_sweep_invalid" in _codes(errors)


def test_r07_prepare_step_is_admitted_without_checkin1_but_never_above_dry(tmp_path):
    store, plan, read, con, _ = _setup(tmp_path, prepare=False)
    ctx = context(store, tmp_path, plan, read, con, {})
    assert guard.admit(_step(plan, "inputs.census"), ctx) == []
    bad = deepcopy(_step(plan, "inputs.census"))
    bad["rung"] = "smoke"
    assert _codes(guard.admit(bad, ctx)) == {"prepare_rung"}
    # a prepare-phase label never admits generation: the operation's own effects are checked too
    generating = deepcopy(_step(plan, "inputs.census"))
    generating["operation"] = "lifecycle-routine-recast"
    assert _codes(guard.admit(generating, ctx)) == {"prepare_production"}


def test_r07_checkin1_gate_refuses_an_unbound_or_unprepared_plan(tmp_path):
    store, plan, read, con, _ = _setup(tmp_path, prepare=False)
    errors = analysis.gate("checkin1->execute", context(store, tmp_path, plan, read, con, {}))
    assert "prepare_step_open" in _codes(errors)
    assert "plan_unbound" in _codes(errors)


def test_r07_checkin1_gate_passes_a_bound_prepared_plan(tmp_path):
    store, plan, read, con, states = _setup(tmp_path)
    assert analysis.gate("checkin1->execute", context(store, tmp_path, plan, read, con, states)) == []
    run_full = _step(plan, "run.full")
    assert run_full["parameters"]["task"]["analysis"] == "FICTIONAL_ROUTINE_1"
    assert run_full["parameters"]["task"]["stat_mode"] == "best-sr-counting"
    assert plan["revision"] == 1


# ---- A08 and E21: the full and scan rungs wait for CHECK-IN 2 and keep the rung ladder ----------------

def test_a08_full_rung_refused_before_checkin2_go(tmp_path):
    """A08: the full rung is refused without the CHECK-IN 2 GO, even after CHECK-IN 1."""
    store, plan, read, con, states = _setup(tmp_path)
    grant(store, "approve_plan", plan=plan)
    ctx = context(store, tmp_path, plan, read, con, states)
    errors = guard.admit(_step(plan, "run.full"), ctx)
    assert _codes(errors) == {"checkin2_go_missing"} and errors[0]["row"] == "A08"
    grant(store, "go", decision="go", plan=plan)
    assert guard.admit(_step(plan, "run.full"), ctx) == []


def test_a08_scan_point_refused_before_checkin2_go(tmp_path):
    store, plan, read, con, states = _setup(tmp_path, task_mode="scan", cost_mode="scan")
    grant(store, "approve_plan", plan=plan)
    point = next(s for s in plan["steps"] if s["id"].startswith("scan.point."))
    assert "checkin2_go_missing" in _codes(guard.admit(point, context(store, tmp_path, plan, read, con, states)))


def test_e21_plan_without_a_waypoint_below_the_bulk_rung_is_refused(tmp_path):
    """E21: a plan that skips the smoke waypoint before the full rung is refused at CHECK-IN 1."""
    store, plan, read, con, states = _setup(tmp_path)
    plan = deepcopy(plan)
    for step in plan["steps"]:
        step["waypoint"] = False
    plan["waypoints"] = []
    errors = guard.ladder_errors(plan)
    assert _codes(errors) == {"waypoint_missing"} and errors[0]["row"] == "E21"


def test_e21_bulk_step_that_bypasses_the_waypoint_is_refused(tmp_path):
    store, plan, read, con, states = _setup(tmp_path)
    plan = deepcopy(plan)
    run_full = _step(plan, "run.full")
    run_full["depends_on"] = ["acquire.data"]
    run_full["inputs"] = [i for i in run_full["inputs"] if not i["artifact"].startswith("visualize.waypoint:")]
    assert "rung_ladder_skipped" in _codes(guard.ladder_errors(plan))


# ---- C26: the requested detector fidelity is pinned ------------------------------------------------

def test_c26_full_simulation_request_refuses_a_fast_response_plan(tmp_path):
    """C26: a full detector simulation was requested; a fast-response plan is refused at CHECK-IN 1."""
    read = reading(full_simulation=True)
    store, plan, read, con, states = _setup(tmp_path, read=read)
    errors = analysis.gate("checkin1->execute", context(store, tmp_path, plan, read, con, states))
    downgraded = [e for e in errors if e["code"] in ("fidelity_downgraded", "fidelity_delivered_below_request")]
    assert downgraded and {e["row"] for e in downgraded} == {"C26"}


def test_c26_full_simulation_request_refuses_a_fast_response_delivery(tmp_path):
    """C26 at delivery: a fast-response result never satisfies a full-simulation request."""
    read = reading(full_simulation=True)
    errors = fidelity.result_errors(read, contract("reproduce"), {"run.full:outputs/limits.json":
                                                                  "simpleanalysis-delphes-native"})
    assert _codes(errors) == {"fidelity_delivered_below_request"}


def test_c26_requested_fidelity_label_cannot_upgrade_a_fast_detector():
    plan = {"steps": [{"id": "detector", "parameters": {"fidelity": "full-simulation",
                                                       "task": {"detector_mode": "simpleanalysis-delphes-native"}}}]}
    assert _codes(fidelity.plan_errors(reading(full_simulation=True), contract(), plan)) == {"fidelity_downgraded"}
    assert _codes(fidelity.result_errors(reading(full_simulation=True), contract(), {})) == {"fidelity_result_missing"}


def test_c26_fidelity_positive_controls():
    assert fidelity.result_errors(reading(), contract("reproduce"), {"x": "simpleanalysis-delphes-native"}) == []
    read = reading()
    read["constraints"].append({"id": "K2", "type": "requested_stage", "value": {"stage": "detector"}})
    assert fidelity.result_errors(read, contract("reproduce"), {"x": "simpleanalysis-delphes-native"}) == []
    assert fidelity.result_errors(read, contract("reproduce"), {"x": "particle-level"})


@pytest.mark.parametrize("mode", ["rivet-smearing", "effmap-folded", "simpleanalysis-delphes-native"])
def test_c26_requested_detector_stage_admits_every_detector_response(mode):
    """A requested detector stage needs some detector response: smearing and efficiency-map folding supply it
    as well as a fast simulation. Only an explicit full-simulation demand asks for more."""
    read = reading()
    read["constraints"].append({"id": "K2", "type": "requested_stage", "value": {"stage": "detector"}})
    plan = {"steps": [{"id": "detector", "parameters": {"task": {"detector_mode": mode}}}]}
    assert fidelity.plan_errors(read, contract(), plan) == []
    assert fidelity.result_errors(read, contract("reproduce"), {"x": mode}) == []


def test_c26_requested_detector_stage_still_refuses_a_plan_without_detector_response():
    read = reading()
    read["constraints"].append({"id": "K2", "type": "requested_stage", "value": {"stage": "detector"}})
    assert _codes(fidelity.plan_errors(read, contract(), {"steps": [{"id": "s", "parameters": {}}]})) == {
        "fidelity_unplanned"}
    plan = {"steps": [{"id": "s", "parameters": {"task": {"detector_mode": "particle-level"}}}]}
    assert _codes(fidelity.plan_errors(read, contract(), plan)) == {"fidelity_downgraded"}


def test_c26_route_analysis_choosing_a_lower_fidelity_than_requested_is_refused(tmp_path):
    """The route analysis cannot quietly downgrade a requested detector stage to particle level."""
    read = reading()
    read["constraints"].append({"id": "K2", "type": "requested_stage", "value": {"stage": "detector"}})
    store, plan, read, con, states = _setup(tmp_path, read=read)
    adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json", route_analysis(detector_mode="particle-level"))
    from ravel.controller.routes.analysis import evidence
    problems = evidence.route_analysis(_step(plan, "inputs.route"), None,
                                       context(store, tmp_path, plan, read, con, states))
    assert "fidelity_delivered_below_request" in _codes(problems)


# ---- ROUTE-*: the route's stages, check-ins and reviews are not optional ---------------------------

@pytest.mark.parametrize("dropped,where", [
    ("inputs.traps", "checkin1"), ("inputs.figures", "checkin1"), ("visualize.waypoint", "checkin1"),
    ("verify.adversary", "final"), ("synthesize", "final"), ("compare.reference", "final"),
])
def test_route_dropped_stage_is_refused(tmp_path, dropped, where):
    """ROUTE-reproduce, ROUTE-reinterpret, ROUTE-scan: a plan without one of its stages cannot pass the gate."""
    store, plan, read, con, states = _setup(tmp_path)
    plan = deepcopy(plan)
    plan["steps"] = [s for s in plan["steps"] if s["id"] != dropped]
    for step in plan["steps"]:
        step["depends_on"] = [d for d in step["depends_on"] if d != dropped]
    plan["waypoints"] = [w for w in plan["waypoints"] if w != dropped]
    transition = "checkin1->execute" if where == "checkin1" else "checkin3->deliver"
    grant(store, "approve_plan", plan=plan)
    errors = analysis.gate(transition, context(store, tmp_path, plan, read, con, states))
    assert errors, dropped
    if where == "final":
        assert "route_stage_missing" in _codes(errors)
