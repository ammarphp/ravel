"""P12: the inspect, legacy, manuscript and ML route specs compile, route and stay within their contracts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ravel.controller.routes import inspect as read_only, ml

ROUTES = Path(__file__).resolve().parents[3] / "src" / "ravel" / "data" / "controller" / "routes"
OWN = ("inspect.json", "legacy.json", "manuscript.json", "ml.json")


def specs():
    found = {}
    for name in OWN:
        document = json.loads((ROUTES / name).read_text(encoding="utf-8"))
        for spec in document["specs"] if document.get("kind") == "route-spec-family" else [document]:
            found[spec["id"]] = spec
    return found


def reading(*deliverables, facts=(), constraints=()):
    rows = []
    for index, (artifact, claim) in enumerate(deliverables, 1):
        rows.append({"id": f"D{index}", "artifact": {"kind": artifact} if artifact else None, "claim_kind": claim})
    return {"facts": list(facts), "constraints": list(constraints), "deliverables": rows}


def test_P12_specs_are_present_with_their_route_ids():
    assert set(specs()) == {"inspect", "legacy", "manuscript", "ml.inference", "ml.training"}
    assert {spec["id"] for spec in specs().values() if spec.get("admits_scientific_deliverables") is False} == {
        "inspect", "legacy"}


def test_P12_read_only_specs_have_no_effect_before_compilation():
    for route in ("inspect", "legacy"):
        for step in specs()[route]["steps"]:
            full = {"inputs": [], "outputs": [], "depends_on": [], "waypoint": False, "rung": None, "budget": {},
                    **step}
            assert read_only.step_effects(full) == [], (route, step["id"])


def matched_operations(predicate):
    """The intake operations a match predicate names (``operation`` with ``eq`` or ``in``)."""
    if "field" in predicate:
        if predicate["field"] != "operation":
            return set()
        value = predicate.get("eq", predicate.get("in"))
        return set(value) if type(value) is list else {value}
    if "not" in predicate:
        return set()
    return set().union(*(matched_operations(p) for p in predicate.get("all", predicate.get("any", ()))))


@pytest.mark.parametrize("route", ["ml.inference", "ml.training"])
def test_P12_ml_specs_run_exactly_the_operation_they_match(route):
    """A request naming one governed operation is never planned with a different one."""
    spec = specs()[route]
    run = {ml.governed(step) for step in spec["steps"] if ml.governed(step) in ml.GOVERNED}
    assert matched_operations(spec["match"]["when"]) == run


def test_P12_governed_steps_name_their_executor_roles():
    executors = ml.modes.executor_table()["operations"]
    for spec in specs().values():
        for step in spec["steps"]:
            mode = ml.governed(step)
            if mode in ml.GOVERNED:
                assert step["role"] == executors[mode], step["id"]


# ---- with the controller core (P01): validation, compilation and selection ------------------

def core():
    """The controller core's compiler and selector; these tests skip only until P01 is merged."""
    from importlib import import_module
    try:  # the package exports a ``select`` function, so import the modules by name
        return (import_module("ravel.controller.routes.compiler"), import_module("ravel.controller.routes.select"))
    except ImportError as exc:
        pytest.skip(f"the controller core (P01) is not merged: {exc}")


@pytest.mark.parametrize("route", ["inspect", "legacy", "manuscript", "ml.inference", "ml.training"])
def test_P12_spec_validates(route):
    compiler, select = core()
    assert select.spec_errors(specs()[route]) == []


def test_P12_installed_specs_load_without_duplicates():
    compiler, select = core()
    ids = [spec["id"] for spec in select.load_specs()]
    assert {"inspect", "legacy", "manuscript", "ml.inference", "ml.training"} <= set(ids)
    assert len(ids) == len(set(ids))


def test_P12_inspect_route_has_zero_effects():
    compiler, select = core()
    plan = compiler.compile(specs()["inspect"], reading((None, "document")), {})
    assert compiler.plan_errors(plan) == []
    assert read_only.plan_effects(plan) == [] and read_only.plan_errors(plan) == []
    assert plan["waypoints"] == [] and [s["kind"] for s in plan["steps"]] == ["synthesize"]
    assert all(row["status"] == "mapped" for row in plan["deliverables"])


def test_P12_inspect_guard_refuses_an_injected_effect():
    compiler, select = core()
    plan = compiler.compile(specs()["inspect"], reading((None, "document")), {})
    injected = dict(plan["steps"][0], id="n02", kind="operate", operation="event-production", rung="smoke",
                    budget={"events": 1000}, outputs=[{"path": "outputs/events.lhe", "kind": "event_sample",
                                                       "required": True}])
    codes = {row["code"] for row in read_only.guard(injected, plan)}
    assert {"effectful_kind", "step_operation", "effect_rung", "effect_budget", "effect_output"} <= codes
    # A later plan from another planner keeps the run read-only through the pinned route.
    judged = dict(plan, route={"id": "judgment", "version": 1, "spec_sha256": "0" * 64})
    assert read_only.guard(injected, judged) == []
    assert read_only.guard(injected, judged, route="inspect")
    assert read_only.guard(plan["steps"][0], plan) == []


def test_P12_legacy_route_compiles_read_only_and_binds_the_runs():
    compiler, select = core()
    supplied = [{"kind": "legacy-run", "path": "/runs/old", "governance": "NOT GOVERNED"}]
    plan = compiler.compile(specs()["legacy"], reading((None, "document")), {}, supplied=supplied)
    assert read_only.plan_effects(plan) == []
    assert plan["parameters"]["legacy_runs"] == supplied and plan["open_obligations"] == []
    unbound = compiler.compile(specs()["legacy"], reading((None, "document")), {})
    assert [row["id"] for row in unbound["open_obligations"]] == ["parameter:legacy_runs"]


def test_P12_read_only_routes_are_never_selected_for_science():
    compiler, select = core()
    supplied = [{"kind": "legacy-run", "path": "/runs/old"}]
    scientific = reading(("table", "exclusion"))
    chosen = select.select({}, scientific, supplied)
    assert chosen["route"] not in ("legacy", "inspect")
    rejected = [row for row in chosen["evidence"] if row["route"] == "legacy"]
    assert rejected and rejected[0]["matched"] is False
    question = select.select({}, reading((None, "document")), supplied)
    assert question["route"] == "legacy"
    governed = select.select({}, reading((None, "document")), [{"kind": "controller-run", "path": "/runs/new"}])
    assert governed["route"] == "inspect"


def test_P12_manuscript_route_compiles_with_staging_before_the_build():
    compiler, select = core()
    from ravel.controller.routes.manuscript import staged as note_staged
    plan = compiler.compile(specs()["manuscript"], reading(("document", "document")), {},
                            supplied=[{"kind": "file", "path": "/data/result.json", "sha256": "a" * 64}])
    assert compiler.plan_errors(plan) == []
    by_id = {s["id"]: s for s in plan["steps"]}
    pdf = by_id["m03-pdf"]
    assert ml.modes.ancestors(plan, "m03-pdf") == {"m01-author", "m02-sources", "m02-build"}
    assert plan["deliverables"][0]["step"] == "m03-pdf"
    approved = lambda kind, pins: {"id": "a"} if pins == {"plan_sha256": plan["sha256"]} else None  # noqa: E731
    assert ml.admit(pdf, plan=plan, authority=approved, signature_table=note_staged.signatures(),
                    executors={"operations": note_staged.executors()}) == []
    assert ml.admit(by_id["m02-build"], plan=plan, authority=approved) == []


def test_P12_manuscript_route_selected_for_manuscript_requests(monkeypatch):
    compiler, select = core()
    from ravel.workflow import intake
    monkeypatch.setattr(intake, "operation_kind", lambda text: "manuscript")
    chosen = select.select({"prompt": "a request", "task_mode": "research"}, reading(("document", "document")), [])
    assert chosen["route"] == "manuscript"


def test_P12_ml_inference_plan_never_contains_training():
    compiler, select = core()
    plan = compiler.compile(specs()["ml.inference"], reading(("table", "estimate"), (None, "finding")), {})
    assert compiler.plan_errors(plan) == []
    assert not any(ml.governed(step) == ml.TRAINING for step in plan["steps"])
    approved = lambda kind, pins: {"id": "a"} if pins == {"plan_sha256": plan["sha256"]} else None  # noqa: E731
    apply = next(s for s in plan["steps"] if s["id"] == "i03-apply")
    assert ml.admit(apply, plan=plan, authority=approved) == []


def test_P12_ml_training_plan_holds_with_the_prerequisite_reason():
    """The staged training plan (P17): admitted with its contracts; held with the typed reason without the executor."""
    compiler, select = core()
    from ravel.controller.routes.ml import staged, training
    supplied = [{"kind": "file", "path": "/data/fixture/table.npz", "sha256": "f" * 64, "size": 1}]
    plan = compiler.compile(specs()["ml.training"], reading(("table", "method_performance")), {}, supplied=supplied)
    assert compiler.plan_errors(plan) == []
    train = next(s for s in plan["steps"] if s["id"] == "t05-train")
    approved = lambda kind, pins: {"id": kind} if kind == "approve_plan" and pins == {"plan_sha256": plan["sha256"]} \
        else None  # noqa: E731
    contracts = dict(signature_table=staged.signatures(), executors={"operations": staged.executors()})
    assert ml.admit(train, plan=plan, authority=approved, **contracts) == []
    errors = ml.admit(train, plan=plan, authority=approved, prerequisites=training.prerequisites(object()), **contracts)
    assert [e["code"] for e in errors] == ["ml_training_prerequisites_unmet"]
    assert errors[0]["hold"] == ml.PREREQUISITE_HOLD


def test_P12_manuscript_pdf_launch_names_an_absent_engine_with_a_nonempty_token(tmp_path, monkeypatch):
    """Without a qualified TeX engine the PDF stage runs to its source-only ending; its approved argv stays a
    list of nonempty tokens, as the operation commitment at CHECK-IN 1 requires."""
    compiler, select = core()
    from ravel.controller.routes.manuscript import staged
    monkeypatch.setattr(staged, "qualified_engine", lambda environ=None: None)
    plan = compiler.compile(specs()["manuscript"], reading(("document", "document")), {},
                            supplied=[{"kind": "file", "path": "/data/result.json", "sha256": "a" * 64}])
    pdf = {s["id"]: s for s in plan["steps"]}["m03-pdf"]
    argv = pdf["parameters"]["launch"]["argv"]
    assert all(type(token) is str and token for token in argv), argv
    assert "--tex=" in argv and "--tex" not in argv
    assert staged.pdf_admission(pdf, tmp_path) == ("source-only", [])
    engine = tmp_path / "bin" / "pdflatex"
    two_tokens = {**pdf, "parameters": {"launch": {"argv": [*argv[:argv.index("--tex=")], "--tex", str(engine)]}}}
    one_token = {**pdf, "parameters": {"launch": {"argv": [*argv[:argv.index("--tex=")], f"--tex={engine}"]}}}
    assert staged.pdf_admission(one_token, tmp_path) == staged.pdf_admission(two_tokens, tmp_path)
    assert staged.pdf_admission(one_token, tmp_path)[0] is None
    both = {**pdf, "parameters": {"launch": {"argv": [*argv, "--tex", str(engine)]}}}
    assert staged.pdf_admission(both, tmp_path)[1][0]["code"] == "manuscript_pdf_engine_ambiguous"
