"""The analysis route specs as data: structure, admission and compilation (R07, ROUTE-*, STEP-01..09, E21)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from p09_support import compile_plan, contract, reading, specs

ROOT = Path(__file__).resolve().parents[3]
PREPARE = ("env", "inputs.census", "inputs.route", "inputs.traps", "inputs.figures", "inputs.cost")
WORKFLOW_STEPS = ("01-environment", "02-inputs", "03-generate", "04-analyze", "05-visualize", "06-acquire-data",
                  "07-exclude", "09-verify")


def _signatures():
    return json.loads((ROOT / "src/ravel/data/operation_signatures.json").read_text())["operations"]


def _executors():
    return json.loads((ROOT / "src/ravel/data/roles/executors.json").read_text())["operations"]


def _ancestors(steps, step_id):
    by_id = {s["id"]: s for s in steps}
    seen, stack = set(), list(by_id[step_id]["depends_on"])
    while stack:
        current = stack.pop()
        if current in seen or current not in by_id:
            continue
        seen.add(current)
        stack.extend(by_id[current]["depends_on"])
    return seen


@pytest.mark.parametrize("spec_id", ["analysis", "analysis.scan"])
def test_route_reproduce_reinterpret_scan_specs_match_row_six(spec_id):
    spec = specs()[spec_id]
    assert spec["match"]["row"] == 6
    assert spec["admits_scientific_deliverables"] is True
    modes = spec["match"]["when"].get("in") or [spec["match"]["when"].get("eq")]
    assert set(modes) <= {"reproduce", "reinterpret", "scan"}


def test_scan_spec_is_tried_before_the_single_point_spec():
    assert specs()["analysis.scan"]["match"]["order"] < specs()["analysis"]["match"]["order"]


@pytest.mark.parametrize("spec_id", ["analysis", "analysis.scan"])
def test_installed_census_budget_explicitly_requests_zero_events(spec_id):
    from ravel.controller import routes

    census = next(step for step in routes.find(spec_id)["steps"] if step["id"] == "inputs.census")
    assert census["budget"]["events"] == 0


@pytest.mark.parametrize("spec_id", ["analysis", "analysis.scan"])
def test_r07_prepare_phase_runs_at_no_rung_and_feeds_every_production_step(spec_id):
    """R07 by structure: no generation step can be ready before every 02-inputs step completed."""
    spec = specs()[spec_id]
    steps = {s["id"]: s for s in spec["steps"]}
    for step_id in PREPARE:
        assert steps[step_id]["parameters"]["phase"] == "prepare"
        assert steps[step_id]["rung"] == "none"
        assert all(steps[d]["parameters"].get("phase") == "prepare" for d in steps[step_id]["depends_on"])
    for step in spec["steps"]:
        if step.get("rung") in ("smoke", "pilot", "full", "scan"):
            assert set(PREPARE) <= _ancestors(spec["steps"], step["id"]) | set(step["depends_on"]), step["id"]
            assert step["parameters"].get("phase") != "prepare"


@pytest.mark.parametrize("spec_id", ["analysis", "analysis.scan"])
def test_e21_bulk_rungs_sit_behind_the_waypoint(spec_id):
    """A08 and E21 by structure: the full and scan rungs depend on the smoke waypoint."""
    spec = specs()[spec_id]
    waypoints = [s["id"] for s in spec["steps"] if s.get("waypoint")]
    assert waypoints == ["visualize.waypoint"]
    for step in spec["steps"]:
        if step.get("rung") in ("full", "scan"):
            assert "visualize.waypoint" in _ancestors(spec["steps"], step["id"]) | set(step["depends_on"]), step["id"]


@pytest.mark.parametrize("spec_id", ["analysis", "analysis.scan"])
def test_step_01_09_every_workflow_step_document_is_delivered(spec_id):
    """STEP-01..09: each step document is an instruction source of a plan step, so its rows materialise."""
    spec = specs()[spec_id]
    sources = {src for s in spec["steps"] for src in s["instruction_sources"]}
    wanted = list(WORKFLOW_STEPS) + (["08-scan"] if spec_id == "analysis.scan" else [])
    for name in wanted:
        assert f"docs/workflow/steps/{name}.md" in sources, name
    for path in sources | set(spec.get("instruction_sources") or ()):
        assert (ROOT / path).is_file(), path


@pytest.mark.parametrize("spec_id", ["analysis", "analysis.scan"])
def test_operations_are_admissible_by_signature_and_executor(spec_id):
    """Every operation step names a registered operation, its executor role and produced artifact kinds."""
    signatures, executors = _signatures(), _executors()
    for step in specs()[spec_id]["steps"]:
        if step["kind"] not in ("operate", "acquire"):
            continue
        signature = signatures[step["operation"]]
        produced = {slot["kind"] for slot in signature["produces"]}
        assert {o["kind"] for o in step["outputs"]} <= produced, step["id"]
        required = executors.get(step["operation"])
        # A declared host operation (the trusted acquisition) runs under the registry's host actor.
        from ravel.controller.step.operations import executors as executor_table
        table = executor_table()
        host = table["coordinator"]["role"] if step["operation"] in table.get("host_operations", {}) else None
        expected = required if required is not None else host
        assert expected is not None, step["id"]
        assert step.get("role") == expected, step["id"]
        ceiling = signature["cost"].get("ceiling_pointer")
        if ceiling == "/max_seconds":
            assert step["parameters"]["task"]["max_seconds"] <= step["budget"]["wall_seconds"]
        if ceiling == "/max_bytes":
            assert step["parameters"]["task"]["max_bytes"] > 0


@pytest.mark.parametrize("spec_id", ["analysis", "analysis.scan"])
def test_worker_roles_exist_in_the_registry(spec_id):
    registry = json.loads((ROOT / "src/ravel/data/roles/registry.json").read_text())["roles"]
    spec = specs()[spec_id]
    roles = {s["role"] for s in spec["steps"] if s.get("role")}
    roles |= {r for s in spec["steps"] for r in s["review"]}
    roles |= {r for c in spec["checkins"] for r in c.get("seats") or ()}
    assert roles <= set(registry), roles - set(registry)


@pytest.mark.parametrize("spec_id", ["analysis", "analysis.scan"])
def test_checkins_and_route_obligations_are_declared(spec_id):
    spec = specs()[spec_id]
    assert [c["id"] for c in spec["checkins"]] == ["checkin1", "checkin2", "checkin3"]
    assert spec["checkins"][0]["seats"] == ["plan-critic"]
    assert set(spec["obligations"]) >= {"R07", "C26", "E04", "E05", "C10"}


def test_single_point_plan_maps_every_deliverable():
    plan = compile_plan("analysis", reading(), contract("reproduce"))
    rows = {d["id"]: d for d in plan["deliverables"]}
    assert rows["D1"]["status"] == "mapped" and rows["D1"]["step"] == "run.full"
    assert rows["D2"]["status"] == "mapped" and rows["D2"]["step"] == "visualize.final"
    assert plan["waypoints"] == ["visualize.waypoint"]


def test_route_unmapped_deliverable_stays_an_open_obligation():
    """A deliverable the route cannot produce is never dropped (R02, R05): it stays open."""
    found = reading()
    found["deliverables"].append({"id": "D9", "artifact": {"kind": "model", "require": {}}, "claim_kind": "finding"})
    plan = compile_plan("analysis", found, contract("reproduce"))
    rows = {d["id"]: d for d in plan["deliverables"]}
    assert rows["D9"]["status"] == "open"


def test_scan_plan_has_one_governed_step_per_approved_point():
    plan = compile_plan("analysis.scan", reading(scan=True, values=(100, 200, 300)), contract("scan"))
    points = [s for s in plan["steps"] if s["id"].startswith("scan.point.")]
    grid = plan["parameters"]["grid"]
    assert grid["complete"] and len(grid["points"]) == 3 == len(points)
    assert {s["parameters"]["point_id"] for s in points} == {p["id"] for p in grid["points"]}
    assert all(s["rung"] == "scan" for s in points)
    assemble = next(s for s in plan["steps"] if s["id"] == "scan.assemble")
    assert sorted(assemble["depends_on"]) == sorted(s["id"] for s in points)
    rows = {d["id"]: d for d in plan["deliverables"]}
    assert rows["D1"]["step"] == "scan.assemble"


def test_scan_grid_left_open_by_the_request_compiles_no_points():
    """A range without a step is not completed by guesswork: the grid stays open (no point step)."""
    found = reading(scan=False)
    found["facts"].append({"id": "F9", "type": "parameter_range",
                           "value": {"text": "between 100 and 400 GeV", "low": 100, "high": 400, "unit": "GeV",
                                     "step": None, "variable": "m_widget"}})
    plan = compile_plan("analysis.scan", found, contract("scan"))
    assert not [s for s in plan["steps"] if s["id"].startswith("scan.point.")]
    assert plan["parameters"]["grid"]["complete"] is False
    assert "states no step" in plan["parameters"]["grid"]["problems"][0]


@pytest.mark.parametrize('spec_id', ['analysis', 'analysis.scan'])
def test_plotting_steps_bind_the_required_reviewers_figure_contract(spec_id):
    spec = specs()[spec_id]
    for step in spec['steps']:
        if step['id'] not in ('visualize.waypoint', 'visualize.final'):
            continue
        fields = step['parameters']['check_inputs']['check:validation.validate_run_state.check_figure_contract']
        assert fields['target'] == {'source': 'output', 'step': 'inputs.figures',
                                    'path': 'outputs/figure_target.json', 'type': 'path'}
        assert 'inputs.figures' in step['depends_on']
        assert any(row['artifact'] == 'inputs.figures:outputs/figure_target.json'
                   and row.get('required') is True for row in step['inputs'])


@pytest.mark.parametrize('identifier', ['recast.smoke', 'visualize.waypoint', 'visualize.final'])
def test_acceptance_review_has_a_declared_typed_subject(identifier):
    route = specs()['analysis']
    step = next(row for row in route['steps'] if row['id'] == identifier)
    check = 'check:validation.certify_acceptance'
    document = step['parameters']['check_inputs'][check]['document']
    primary = next(row['path'] for row in step['outputs'] if row['path'].endswith('.json'))
    assert document == {'source': 'output', 'step': identifier, 'path': primary,
                        'field': '/validator_inputs/' + check + '/document', 'type': 'path'}
    assert step['parameters']['validator_exports'][primary][document['field']] == 'path'
