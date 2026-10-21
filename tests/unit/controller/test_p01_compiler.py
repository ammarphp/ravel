"""P01 route-spec compiler: fixture specs compile to valid plans; nothing a reading asks for is dropped.

Population equality (R02, R04, R09 with the route packages): every reading deliverable is mapped to
a declared step output or kept as an explicit open obligation; unbound required parameters too.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

import fakes
from ravel.cli import _draft_route
from ravel.controller import routes, schema_errors
from ravel.controller.routes import compiler
from ravel.controller.routes.select import installed_specs

ANALYSIS = ("Reproduce the published exclusion contour of a fictional search for a heavy scalar decaying to two "
            "photons at 13 TeV.")


@pytest.fixture(scope="module")
def analysis():
    contract, reading, _ = _draft_route(ANALYSIS, None, None)
    return contract, reading


def _spec(steps, deliverables, **extra):
    spec = fakes._spec("fixture-compile", 6, {"field": "task_mode", "eq": "reproduce"}, steps, deliverables)
    spec.update(extra)
    return spec


@pytest.mark.parametrize("spec", fakes.route_specs(), ids=[s["id"] for s in fakes.route_specs()])
def test_each_fixture_spec_compiles_to_a_valid_plan(analysis, spec):
    contract, reading = analysis
    plan = routes.compile(spec, reading, contract)
    assert schema_errors(plan, "plan.v1") == []
    assert routes.plan_errors(plan) == []
    assert plan["route"] == {"id": spec["id"], "version": 1, "spec_sha256": plan["route"]["spec_sha256"]}
    assert plan["sha256"] == routes.plan_sha256(plan)
    # The catch-all mapping covers every reading deliverable: none is open.
    assert [d["status"] for d in plan["deliverables"]] == ["mapped"] * len(reading["deliverables"])
    assert plan["open_obligations"] == []
    assert plan == routes.compile(spec, reading, contract)  # deterministic


def test_a_dropped_deliverable_stays_an_open_obligation(analysis):
    contract, reading = analysis
    kinds = {d["id"]: d["artifact"]["kind"] for d in reading["deliverables"]}
    assert set(kinds.values()) == {"figure", "inference"}
    steps = [fakes.make_step("figure", outputs=["outputs/figure.json"])]
    plan = routes.compile(_spec(steps, [{"match": {"artifact": ["figure"]}, "step": "figure",
                                         "output": "outputs/figure.json"}]), reading, contract)
    mapped = {d["id"]: d["status"] for d in plan["deliverables"]}
    assert sorted(mapped.values()) == ["mapped", "open"]
    open_ids = [d["id"] for d in plan["deliverables"] if d["status"] == "open"]
    assert [o["id"] for o in plan["open_obligations"]] == open_ids
    assert plan["steps"][0]["deliverables"] == [d for d in mapped if mapped[d] == "mapped"]


def test_unbound_required_parameters_are_open_obligations_and_bound_ones_fill_placeholders(analysis):
    contract, reading = analysis
    steps = [fakes.make_step("s1", outputs=["outputs/{statistic}.json"], title="statistic {statistic}")]
    spec = _spec(steps, [{"match": {"any": True}, "step": "s1", "output": "outputs/CLs.json"}],
                 parameters=[{"name": "statistic", "from": "constraint:prescribed_statistic", "default": "CLs"},
                             {"name": "grid", "from": "fact:fictional_grid", "required": True}])
    plan = routes.compile(spec, reading, contract)
    assert plan["steps"][0]["outputs"][0]["path"] == "outputs/CLs.json"
    assert plan["steps"][0]["title"] == "statistic CLs"
    assert [o["id"] for o in plan["open_obligations"]] == ["parameter:grid"]
    assert plan["parameters"]["grid"] is None


def test_foreach_expands_points_and_rewires_dependencies_and_inputs(analysis):
    contract, reading = analysis
    steps = [fakes.make_step("point", outputs=["outputs/point-{item}.json"], foreach="points"),
             fakes.make_step("assemble", depends_on=["point"], outputs=["outputs/assembled.json"],
                             inputs=[{"artifact": "point:outputs/point-{item}.json", "sha256": None}])]
    spec = _spec(steps, [{"match": {"any": True}, "step": "assemble", "output": "outputs/assembled.json"}],
                 parameters=[{"name": "points", "from": "contract:fictional_points",
                              "default": [{"id": "a"}, {"id": "b"}]}])
    # A foreach step's own placeholders resolve per item; the assembling step's input is per point.
    steps[1]["inputs"] = [{"artifact": "point:outputs/point-a.json", "sha256": None}]
    with pytest.raises(routes.CompileError):
        routes.compile(spec, reading, contract)  # the input names one output of a two-point expansion
    steps[1]["inputs"] = []
    plan = routes.compile(spec, reading, contract)
    ids = [s["id"] for s in plan["steps"]]
    assert ids == ["point.a", "point.b", "assemble"]
    assert plan["steps"][2]["depends_on"] == ["point.a", "point.b"]
    assert [s["parameters"]["item"] for s in plan["steps"][:2]] == [{"id": "a"}, {"id": "b"}]
    assert [s["outputs"][0]["path"] for s in plan["steps"][:2]] == ["outputs/point-a.json", "outputs/point-b.json"]


@pytest.mark.parametrize("mutate,fragment", [
    (lambda s: s["steps"].append(deepcopy(s["steps"][0])), "not unique"),
    (lambda s: s["steps"][0].update(depends_on=["ghost"]), "unknown step"),
    (lambda s: s["steps"][0].update(kind="teleport"), "not a valid step.v1"),
    (lambda s: s["steps"][0].update(operation="op-{unbound}"), "unresolved placeholders"),
    (lambda s: s["steps"].append(fakes.make_step("s2", depends_on=["s3"])) or
     s["steps"].append(fakes.make_step("s3", depends_on=["s2"])), "cycle"),
    (lambda s: s["steps"].append(fakes.make_step("s2", depends_on=["s1"], inputs=[
        {"artifact": "s1:outputs/undeclared.json", "sha256": None}])), "does not declare"),
    (lambda s: s["deliverables"][0].update(output="outputs/other.json"), "does not declare"),
    (lambda s: s["deliverables"][0].update(step="ghost"), "unknown step"),
    (lambda s: s["steps"][0]["outputs"][0].update(path="../escape.json"), "not a valid step.v1"),
])
def test_malformed_specs_and_dags_do_not_compile(analysis, mutate, fragment):
    contract, reading = analysis
    spec = _spec([fakes.make_step("s1", outputs=["outputs/result.json"])],
                 [{"match": {"any": True}, "step": "s1", "output": "outputs/result.json"}])
    mutate(spec)
    with pytest.raises(routes.CompileError, match=fragment):
        routes.compile(spec, reading, contract)


def test_plan_errors_detect_a_tampered_or_inconsistent_plan(analysis):
    contract, reading = analysis
    plan = routes.compile(fakes.route_specs()[5], reading, contract)
    assert routes.plan_errors(plan) == []
    tampered = deepcopy(plan)
    tampered["steps"][0]["rung"] = "full"
    assert any("sha256" in p for p in routes.plan_errors(tampered))
    dangling = deepcopy(plan)
    dangling["waypoints"] = ["ghost"]
    dangling["sha256"] = routes.plan_sha256(dangling)
    assert any("waypoint" in p for p in routes.plan_errors(dangling))
    assert routes.plan_errors({"kind": "controller-plan"})


def test_population_equality_uses_the_ledger_when_installed(monkeypatch):
    import sys
    import types
    calls = []
    ledger = types.ModuleType("ravel.controller.ledger")

    def population_equality(expected, actual):
        calls.append((list(expected), list(actual)))
        return [e for e in expected if e not in set(actual)]
    ledger.population_equality = population_equality
    monkeypatch.setitem(sys.modules, "ravel.controller.ledger", ledger)
    assert compiler.population_holes(["D1", "D2"], ["D2"]) == ["D1"]
    assert calls == [(["D1", "D2"], ["D2"])]


def test_a_route_adapter_computes_parameters_before_expansion(analysis, monkeypatch):
    import sys
    import types
    contract, reading = analysis
    module = types.ModuleType("ravel.controller.routes.fixture_params")
    module.parameters = lambda spec, reading, contract, supplied: {"points": [{"id": "x1"}, {"id": "x2"}]}
    monkeypatch.setitem(sys.modules, "ravel.controller.routes.fixture_params", module)
    spec = _spec([fakes.make_step("point", outputs=["outputs/point-{item}.json"], points=["{item}"], foreach="points"),
                  fakes.make_step("assemble", depends_on=["point"], outputs=["outputs/assembled.json"])],
                 [{"match": {"any": True}, "step": "assemble", "output": "outputs/assembled.json"}],
                 adapter="fixture_params",
                 parameters=[{"name": "points", "from": "fact:fictional_points", "required": True}])
    plan = routes.compile(spec, reading, contract)
    assert [s["id"] for s in plan["steps"]] == ["point.x1", "point.x2", "assemble"]
    assert [s["points"] for s in plan["steps"][:2]] == [["x1"], ["x2"]]
    assert plan["open_obligations"] == []
    module.parameters = lambda *args: ["not", "an", "object"]
    with pytest.raises(routes.CompileError, match="must return an object"):
        routes.compile(spec, reading, contract)
    assert routes.adapter_module({"id": "x"}) is None
    assert any("adapter" in e for e in compiler.selection.spec_errors({**spec, "adapter": "../escape"}))


def test_prepare_steps_run_at_rung_none_or_dry_and_depend_only_on_prepare_steps(analysis):
    contract, reading = analysis
    prepare = {"phase": "prepare"}
    good = _spec([fakes.make_step("census", kind="acquire", rung="none", outputs=["outputs/census.json"],
                                  parameters=prepare),
                  fakes.make_step("s1", depends_on=["census"], rung="smoke", outputs=["outputs/result.json"])],
                 [{"match": {"any": True}, "step": "s1", "output": "outputs/result.json"}])
    assert routes.compile(good, reading, contract)["steps"][0]["parameters"]["phase"] == "prepare"
    late = deepcopy(good)
    late["steps"][0]["rung"] = "smoke"
    with pytest.raises(routes.CompileError, match="only rungs none and dry"):
        routes.compile(late, reading, contract)
    after = deepcopy(good)
    after["steps"] = [fakes.make_step("s0", rung="dry", outputs=["outputs/s0.json"]),
                      fakes.make_step("census", kind="acquire", rung="none", depends_on=["s0"],
                                      outputs=["outputs/census.json"], parameters=prepare),
                      fakes.make_step("s1", depends_on=["census"], outputs=["outputs/result.json"])]
    with pytest.raises(routes.CompileError, match="runs after CHECK-IN 1"):
        routes.compile(after, reading, contract)


def test_explicit_parameters_are_merged_after_the_adapters(analysis, monkeypatch):
    import sys
    import types
    contract, reading = analysis
    module = types.ModuleType("ravel.controller.routes.fixture_params")
    module.parameters = lambda spec, reading, contract, supplied: {"points": [{"id": "x1"}]}
    monkeypatch.setitem(sys.modules, "ravel.controller.routes.fixture_params", module)
    spec = _spec([fakes.make_step("point", outputs=["outputs/point-{item}.json"], points=["{item}"], foreach="points"),
                  fakes.make_step("assemble", depends_on=["point"], outputs=["outputs/assembled.json"])],
                 [{"match": {"any": True}, "step": "assemble", "output": "outputs/assembled.json"}],
                 adapter="fixture_params")
    plan = routes.compile(spec, reading, contract, parameters={"points": [{"id": "y1"}, {"id": "y2"}]})
    assert [s["id"] for s in plan["steps"]] == ["point.y1", "point.y2", "assemble"]
    with pytest.raises(routes.CompileError, match="must be an object"):
        routes.compile(spec, reading, contract, parameters=["y1"])


@pytest.mark.parametrize("mutate,fragment", [
    (lambda plan: plan.update(checkins=[]), "check-in checkin1 is missing"),
    (lambda plan: plan["checkins"][0].update(seats=[]), "lost its seats"),
    (lambda plan: plan["checkins"][0].update(sections=[]), "lost its sections"),
    (lambda plan: plan.update(steps=[], deliverables=[]), "route stage s1 is missing"),
    (lambda plan: plan.update(obligations=[]), "route obligations"),
    (lambda plan: plan["route"].update(spec_sha256="0" * 64), "another version"),
])
def test_a_resealed_plan_that_drops_its_routes_checkins_stages_or_obligations_is_refused(analysis, mutate, fragment):
    contract, reading = analysis
    spec = next(s for s in fakes.route_specs() if s["id"] == "fixture-analysis")
    plan = routes.compile(spec, reading, contract)
    assert routes.plan_errors(plan, spec) == [] and routes.conformance_errors(plan, spec) == []
    edited = deepcopy(plan)
    mutate(edited)
    edited["sha256"] = routes.plan_sha256(edited)
    assert routes.plan_errors(edited) == [] or fragment == "route stage s1 is missing"
    assert any(fragment in problem for problem in routes.plan_errors(edited, spec))


_INSTALLED = installed_specs()


@pytest.mark.parametrize("spec", _INSTALLED, ids=[s["id"] for s in _INSTALLED])
def test_every_installed_spec_compiles(analysis, spec):
    contract, reading = analysis
    assert schema_errors(spec, "route-spec.v1") == []
    plan = routes.compile(spec, reading, contract)
    assert schema_errors(plan, "plan.v1") == []
    assert routes.plan_errors(plan) == []
    assert all(schema_errors(step, "step.v1") == [] for step in plan["steps"])


_TYPED = {"stage": "plan", "skills": ["fixture-skill"], "checkin": "checkin1", "template_id": "tpl",
          "seats": [{"seat": "s", "role": "plan-critic", "kind": "review"}],
          "engagement": {"tier": "lean"}, "engagement_folded_into": "producer:s1:author", "correction_rounds": 2}


def test_typed_optional_step_fields_validate_in_specs_steps_and_plans(analysis):
    contract, reading = analysis
    step = fakes.make_step("s1", outputs=["outputs/result.json"], **_TYPED)
    assert schema_errors(step, "step.v1") == []
    spec = _spec([deepcopy(step)], [{"match": {"any": True}, "step": "s1", "output": "outputs/result.json"}])
    assert schema_errors(spec, "route-spec.v1") == []
    plan = routes.compile(spec, reading, contract)
    assert plan["steps"][0]["checkin"] == "checkin1" and plan["steps"][0]["template_id"] == "tpl"
    plan["engagement"] = {"tier": "lean"}
    plan["checkins"] = [{"id": "checkin1", "seats": ["plan-critic"],
                         "engagement_seats": [{"seat": "s", "role": "plan-critic", "kind": "review"}]}]
    assert schema_errors(plan, "plan.v1") == []
    assert schema_errors({"engagement": {"tier": "lean"}}, "run-state.v1") == []


@pytest.mark.parametrize("field,value", [("checkin", "checkin9"), ("correction_rounds", -1), ("stage", ""),
                                        ("skills", "one"), ("seats", [{"seat": "s"}]), ("engagement", "lean"),
                                        ("undeclared_field", 1)])
def test_the_new_step_fields_stay_typed_and_the_schema_stays_closed(field, value):
    step = fakes.make_step("s1", **{field: value})
    assert schema_errors(step, "step.v1") != []
    spec = _spec([step], [{"match": {"any": True}, "step": "s1", "output": "outputs/result.json"}])
    if field != "undeclared_field":  # route-spec steps stay open to extras, typed on the declared fields
        assert schema_errors(spec, "route-spec.v1") != []


# ---- one budget vocabulary: a step's budget in the authority's dimensions -----------------------------------

def test_step_budget_dimensions_map_to_the_authority_budget_through_one_explicit_table():
    from ravel.controller import schema
    from ravel.controller.authority.operator import BUDGET_KEYS
    assert set(compiler.AUTHORITY_BUDGET.values()) <= set(BUDGET_KEYS)
    # One name per resource: broker calls are the authority's model calls; P06 keeps no second name for them.
    assert compiler.AUTHORITY_BUDGET["broker_calls"] == "model_calls" and "broker_calls" not in BUDGET_KEYS
    budget = {"broker_calls": 40, "attempts": 3, "wall_seconds": 60, "review_rounds": 2, "children": 1, "tokens": 9,
              "events": 5, "cost_usd": 1.5, "core_hours": 0.5}
    assert compiler.authority_budget(budget) == {"model_calls": 40, "wall_seconds": 60, "review_rounds": 2,
                                                 "children": 1, "tokens": 9, "events": 5, "cost_usd": 1.5,
                                                 "core_hours": 0.5}  # attempts is the step's retry limit
    # Every dimension a step may declare is in the table or is the step's own retry limit.
    declared = set(schema("step.v1")["properties"]["budget"]["properties"])
    assert declared == set(compiler.AUTHORITY_BUDGET) | set(compiler.STEP_LIMITS)


@pytest.mark.parametrize("dimension", ["gpu_hours", "model_calls", "concurrency"])
def test_a_step_budget_dimension_outside_the_table_fails_compile(analysis, dimension):
    contract, reading = analysis
    step = fakes.make_step("s1", outputs=["outputs/result.json"], budget={"wall_seconds": 10, dimension: 1})
    spec = _spec([step], [{"match": {"any": True}, "step": "s1", "output": "outputs/result.json"}])
    with pytest.raises(compiler.CompileError, match=f"budget dimension {dimension!r}"):
        routes.compile(spec, reading, contract)
    with pytest.raises(compiler.CompileError, match=f"budget dimension {dimension!r}"):
        compiler.authority_budget({dimension: 1})
