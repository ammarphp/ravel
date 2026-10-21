"""Scan fan-out and population equality against the approved grid (P04, E24, G12, SW33)."""
from __future__ import annotations

from copy import deepcopy

import pytest

from ravel.controller.routes.analysis import grid, scan
from ravel.workflow import scan_orchestrator
from p09_support import Store, adopt, compile_plan, contract, reading


def _plan(values=(100, 200, 300)):
    return compile_plan("analysis.scan", reading(scan=True, values=values), contract("scan"))


def _points(plan):
    return [s for s in plan["steps"] if s["id"].startswith("scan.point.")]


def _context(store, tmp_path, plan, states):
    return {"store": store, "run_dir": str(tmp_path), "plan": plan, "state": {"steps": states}}


def _assembled(plan, statuses):
    """The assembled scan document for ``statuses`` (point id -> status), orchestrator shape."""
    rows = []
    for point in plan["parameters"]["grid"]["points"]:
        if point["id"] in statuses:
            rows.append({"tag": point["id"], "parameters": point["parameters"], "status": statuses[point["id"]]})
    completed = [r for r in rows if r["status"] == "completed"]
    return {"n_planned": len(plan["parameters"]["grid"]["points"]), "n_done": len(completed),
            "n_missing": len(plan["parameters"]["grid"]["points"]) - len(completed),
            "missing_tags": [r["tag"] for r in rows if r["status"] != "completed"],
            "points": [{"tag": r["tag"], "statistic": "CLs"} for r in completed], "point_population": rows}


# ---- the grid ------------------------------------------------------------------------------------

def test_p04_grid_is_the_cartesian_product_of_stated_axes():
    found = grid.from_reading({"facts": [
        {"id": "F1", "type": "parameter_values", "value": {"values": [1, 2], "variable": "a"}},
        {"id": "F2", "type": "parameter_range", "value": {"low": 10, "high": 30, "step": {"value": 10}, "variable": "b"}}]})
    assert found["complete"] and len(found["points"]) == 6
    assert found["points"][0]["parameters"] == {"a": 1, "b": 10}
    assert found["points"][0]["id"] == scan_orchestrator.point_tag({"a": 1, "b": 10})


def test_e24_grid_range_without_a_step_stays_open():
    found = grid.from_reading({"facts": [
        {"id": "F1", "type": "parameter_range", "value": {"text": "100 to 400", "low": 100, "high": 400}}]})
    assert not found["complete"] and not found["points"]


def test_e24_grid_above_the_ceiling_stays_open():
    axes = [{"name": f"x{i}", "values": list(range(11))} for i in range(3)]
    found = grid.grid(axes, source="test")
    assert not found["complete"] and "ceiling" in found["problems"][0]


# ---- plan membership ------------------------------------------------------------------------------

def test_g12_compiled_scan_plan_has_full_membership():
    assert scan.membership_errors(_plan()) == []


def test_sw33_point_step_dropped_from_the_plan_is_a_population_hole():
    """SW33 at plan time: an approved point without its step is refused, not silently skipped."""
    plan = _plan()
    victim = _points(plan)[1]["id"]
    plan["steps"] = [s for s in plan["steps"] if s["id"] != victim]
    errors = scan.membership_errors(plan)
    assert [e["code"] for e in errors] == ["scan_point_unplanned"] and errors[0]["row"] == "SW33"


def test_g12_unmanifested_and_duplicate_point_steps_are_refused():
    """G12: a point outside the grid or a point planned twice is refused."""
    plan = _plan()
    extra = deepcopy(_points(plan)[0])
    extra["id"] = "scan.point.extra"
    extra["parameters"]["point_id"] = "point_00000000000000000000"
    extra["parameters"]["item"] = {"id": "point_00000000000000000000", "parameters": {"m_widget": 999}}
    twice = deepcopy(_points(plan)[0])
    twice["id"] = "scan.point.twice"
    plan["steps"] += [extra, twice]
    codes = {e["code"] for e in scan.membership_errors(plan)}
    assert {"scan_point_unmanifested", "scan_point_duplicate"} <= codes


def test_g12_point_step_with_changed_coordinates_is_refused():
    plan = _plan()
    _points(plan)[0]["parameters"]["item"]["parameters"] = {"m_widget": 150}
    assert "scan_point_coordinates" in {e["code"] for e in scan.membership_errors(plan)}


def test_e24_open_grid_is_refused_before_checkin1():
    plan = compile_plan("analysis.scan", {"facts": [{"id": "F1", "type": "parameter_range",
                                                     "value": {"low": 1, "high": 4}}], "deliverables": []},
                        contract("scan"))
    assert [e["code"] for e in scan.membership_errors(plan)] == ["scan_grid_open"]


# ---- run population and the assembled scan ----------------------------------------------------------

def test_p04_e24_failed_point_stays_an_explicit_hole(tmp_path):
    plan = _plan()
    points = _points(plan)
    states = {points[0]["id"]: {"status": "completed"}, points[1]["id"]: {"status": "failed", "reason": "native crash"},
              points[2]["id"]: {"status": "completed"}}
    found = scan.population(plan, _context(Store(), tmp_path, plan, states))
    hole = points[1]["parameters"]["point_id"]
    assert found["holes"] == [hole] and found["failed"] == [hole]
    row = next(r for r in found["rows"] if r["point"] == hole)
    assert row["status"] == "failed" and row["reason"] == "native crash"


def test_sw33_complete_assembly_passes(tmp_path):
    plan = _plan()
    states = {s["id"]: {"status": "completed"} for s in _points(plan)}
    document = _assembled(plan, {p["id"]: "completed" for p in plan["parameters"]["grid"]["points"]})
    assert scan.assembled_errors(document, plan, _context(Store(), tmp_path, plan, states)) == []


def test_sw33_p04_e24_omitted_point_in_the_assembly_is_refused(tmp_path):
    """P04, E24, SW33: an assembly that omits a manifest point cannot claim the grid; the hole is named."""
    plan = _plan()
    states = {s["id"]: {"status": "completed"} for s in _points(plan)}
    ids = [p["id"] for p in plan["parameters"]["grid"]["points"]]
    document = _assembled(plan, {ids[0]: "completed", ids[2]: "completed"})
    document["n_missing"] = 0
    errors = scan.assembled_errors(document, plan, _context(Store(), tmp_path, plan, states))
    assert {"scan_point_omitted", "scan_missing_tags"} <= {e["code"] for e in errors}
    omitted = next(e for e in errors if e["code"] == "scan_point_omitted")
    assert omitted["row"] == "SW33" and ids[1] in omitted["pins"]


def test_g12_assembly_claiming_an_unobserved_point_is_refused(tmp_path):
    """G12: a substituted launch history (a point claimed completed that the controller never saw complete)."""
    plan = _plan()
    points = _points(plan)
    states = {points[0]["id"]: {"status": "completed"}, points[1]["id"]: {"status": "failed"},
              points[2]["id"]: {"status": "completed"}}
    document = _assembled(plan, {p["id"]: "completed" for p in plan["parameters"]["grid"]["points"]})
    codes = {e["code"] for e in scan.assembled_errors(document, plan, _context(Store(), tmp_path, plan, states))}
    assert {"scan_point_substituted", "scan_result_unobserved", "scan_coverage_overclaimed"} <= codes


def test_e24_assembly_with_an_explicit_hole_is_honest(tmp_path):
    """A hole listed with its status is not an error of the assembly (the delivery is qualified elsewhere)."""
    plan = _plan()
    points = _points(plan)
    ids = [p["id"] for p in plan["parameters"]["grid"]["points"]]
    states = {points[0]["id"]: {"status": "completed"}, points[1]["id"]: {"status": "failed"},
              points[2]["id"]: {"status": "completed"}}
    document = _assembled(plan, {ids[0]: "completed", ids[1]: "failed", ids[2]: "completed"})
    assert scan.assembled_errors(document, plan, _context(Store(), tmp_path, plan, states)) == []


def test_g12_assembly_listing_an_unmanifested_or_duplicate_point_is_refused(tmp_path):
    plan = _plan()
    states = {s["id"]: {"status": "completed"} for s in _points(plan)}
    document = _assembled(plan, {p["id"]: "completed" for p in plan["parameters"]["grid"]["points"]})
    document["point_population"].append(dict(document["point_population"][0]))
    document["point_population"].append({"tag": "point_ffffffffffffffffffff", "status": "completed"})
    codes = {e["code"] for e in scan.assembled_errors(document, plan, _context(Store(), tmp_path, plan, states))}
    assert {"scan_point_duplicate", "scan_point_unmanifested"} <= codes


def test_sw33_assembly_without_a_population_is_refused(tmp_path):
    plan = _plan()
    errors = scan.assembled_errors({"points": []}, plan, _context(Store(), tmp_path, plan, {}))
    assert [e["code"] for e in errors] == ["scan_population_missing"]


def test_g12_point_step_must_run_its_own_approved_point():
    plan = _plan()
    step = deepcopy(_points(plan)[0])
    assert scan.point_errors(step, {}, plan) == []
    step["parameters"]["point_id"] = "point_ffffffffffffffffffff"
    assert [e["code"] for e in scan.point_errors(step, {}, plan)] == ["scan_point_unmanifested"]


def test_p04_point_evidence_retains_membership_authority_and_receipts(tmp_path):
    store = Store()
    plan = _plan()
    from p09_support import grant
    approval = grant(store, "approve_plan", plan=plan, uid="auth-1")
    go = grant(store, "go", decision="go", plan=plan, uid="auth-2")
    step = _points(plan)[0]
    found = scan.point_evidence(store, plan, step, {"status": "completed", "receipts": ["r1"]})
    assert found["grid_sha256"] == plan["parameters"]["grid"]["sha256"]
    # Authority is named by its store id, the identity the authority service authenticates; never by a uid.
    assert found["authority"] == [approval, go] and found["receipts"] == ["r1"]
    assert "auth-1" not in found["authority"] and "auth-2" not in found["authority"]


def test_sw33_completed_result_rows_cannot_be_omitted_or_duplicated(tmp_path):
    plan = _plan()
    states = {s["id"]: {"status": "completed"} for s in _points(plan)}
    document = _assembled(plan, {p["id"]: "completed" for p in plan["parameters"]["grid"]["points"]})
    document["points"] = document["points"][:1] * 2
    errors = scan.assembled_errors(document, plan, _context(Store(), tmp_path, plan, states))
    assert "scan_results_population" in {e["code"] for e in errors}


def test_e24_assembly_counts_cannot_contradict_controller_population(tmp_path):
    plan = _plan()
    states = {s["id"]: {"status": "completed"} for s in _points(plan)}
    document = _assembled(plan, {p["id"]: "completed" for p in plan["parameters"]["grid"]["points"]})
    document["n_done"] = 0
    errors = scan.assembled_errors(document, plan, _context(Store(), tmp_path, plan, states))
    assert "scan_population_count" in {e["code"] for e in errors}


def test_e24_partial_grid_resolution_keeps_every_requested_axis():
    read = {"facts": [
        {"id": "F1", "type": "parameter_values", "value": {"variable": "a", "values": [1, 2]}},
        {"id": "F2", "type": "parameter_range", "value": {"variable": "b", "low": 10, "high": 20}}]}
    dropped = grid.resolve(read, {"axes": [{"name": "b", "values": [10, 20]}]})
    assert not dropped["complete"] and any("omits" in p for p in dropped["problems"])
    changed = grid.resolve(read, {"axes": [{"name": "a", "values": [1]}, {"name": "b", "values": [10, 20]}]})
    assert not changed["complete"] and any("fixed values" in p for p in changed["problems"])
    correct = grid.resolve(read, {"axes": [{"name": "a", "values": [1, 2]}, {"name": "b", "values": [10, 20]}]})
    assert correct["complete"] and len(correct["points"]) == 4
    read["facts"][1]["value"]["unit"] = "unit-a"
    changed_unit = grid.resolve(read, {"axes": [{"name": "a", "values": [1, 2]},
                                               {"name": "b", "values": [10, 20], "unit": "unit-b"}]})
    assert not changed_unit["complete"] and any("requested unit" in p for p in changed_unit["problems"])


def test_p04_explicit_coordinates_keep_their_requested_precision():
    values = [1.00000000000001, 1.00000000000002]
    found = grid.from_reading({"facts": [{"id": "F1", "type": "parameter_values",
                                       "value": {"variable": "a", "values": values}}]})
    assert found["complete"] and found["axes"][0]["values"] == values
    assert len({p["id"] for p in found["points"]}) == 2


# ---- the legacy assembly audit (SW33 helper for launch_authorization.audit_scan_launches) ---------

@pytest.mark.parametrize("mutation,expected", [
    ("omit", "omits 1 manifest point"),
    ("extra", "unmanifested"),
    ("twice", "twice"),
])
def test_sw33_legacy_population_compares_the_whole_manifest(mutation, expected):
    manifest = {"points": [{"tag": "point_a"}, {"tag": "point_b"}, {"tag": "point_c"}]}
    rows = [{"tag": "point_a", "status": "completed"}, {"tag": "point_b", "status": "completed"},
            {"tag": "point_c", "status": "completed"}]
    if mutation == "omit":
        rows = rows[:2]
    elif mutation == "extra":
        rows.append({"tag": "point_z", "status": "completed"})
    else:
        rows.append(dict(rows[0]))
    errors = scan_orchestrator.population_errors(manifest, {"point_population": rows})
    assert any(expected in e for e in errors)


def test_sw33_legacy_population_refuses_a_full_coverage_claim_with_holes():
    manifest = {"points": [{"tag": "point_a"}, {"tag": "point_b"}]}
    scan_doc = {"n_missing": 0, "point_population": [{"tag": "point_a", "status": "completed"},
                                                      {"tag": "point_b", "status": "failed"}]}
    assert any("claims full coverage" in e for e in scan_orchestrator.population_errors(manifest, scan_doc))
    assert scan_orchestrator.population_errors(manifest, {"point_population": [
        {"tag": "point_a", "status": "completed"}, {"tag": "point_b", "status": "completed"}]}) == []


def test_sw33_legacy_population_refuses_unconfirmed_result_rows_and_never_raises():
    manifest = {"points": [{"tag": "point_a"}, {"tag": "point_b"}]}
    scan_doc = {"points": [{"tag": "point_a"}, {"tag": "point_b"}],
                "point_population": [{"tag": "point_a", "status": "completed"}, {"tag": "point_b", "status": "failed"}],
                "missing_tags": ["point_b"]}
    errors = scan_orchestrator.population_errors(manifest, scan_doc)
    assert any("does not mark completed" in e for e in errors)
    assert scan_orchestrator.population_errors(manifest, {"points": [{"tag": "point_a"}], "missing_tags": []}) == [
        "scan omits 1 manifest point(s): point_b", "scan claims full coverage with 1 point(s) not completed"]
    for malformed in (None, [], "x", {"points": "x", "point_population": 3},
                      {"points": [{"tag": {"invalid": 1}}, {"tag": []}], "point_population": [{"tag": [1]}]}):
        assert isinstance(scan_orchestrator.population_errors(malformed, malformed), list)


# ---- the approved grid: the request's own, or the route analysis's inside the request -----------------

def test_e24_route_analysis_never_replaces_a_grid_the_request_fixes():
    read = {"facts": [{"id": "F1", "type": "parameter_values",
                       "value": {"values": [100, 200], "variable": "m_widget"}}]}
    found = grid.resolve(read, {"axes": [{"name": "m_widget", "values": [100, 200, 300, 400]}]})
    assert found["source"] == "reading" and [p["parameters"]["m_widget"] for p in found["points"]] == [100, 200]


def test_e24_route_analysis_fills_an_open_grid_inside_the_requested_range():
    read = {"facts": [{"id": "F1", "type": "parameter_range",
                       "value": {"text": "100 to 400", "low": 100, "high": 400, "variable": "m_widget"}}]}
    inside = grid.resolve(read, {"axes": [{"name": "m_widget", "values": [100, 250, 400]}]})
    assert inside["complete"] and inside["source"] == "route-analysis"
    outside = grid.resolve(read, {"axes": [{"name": "m_widget", "values": [100, 500]}]})
    assert not outside["complete"] and "leaves the requested range" in outside["problems"][0]
    foreign = grid.resolve(read, {"axes": [{"name": "m_other", "values": [1, 2]}]})
    assert not foreign["complete"]
    assert any("omits the requested axis m_widget" in p for p in foreign["problems"])
    assert any("axis m_other" in p and "does not name" in p for p in foreign["problems"])
