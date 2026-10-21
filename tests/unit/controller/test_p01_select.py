"""P01 route selection: the start.md first-match table as ordered predicates over the intake records.

Each fictional request goes through the real intake (``cli._draft_route``); the fixture specs in
``fakes.route_specs`` stand for the route packages' specs, one per table row. Rows: R01 (route
before any effect; a development phrasing keeps scientific requirements), JR01 (no refusal).
"""
from __future__ import annotations

from copy import deepcopy

import pytest

import fakes
from ravel.cli import _draft_route
from importlib import import_module

from ravel.controller import routes

# ``routes.select`` is the binding function; the module of the same name is read from sys.modules.
selection = import_module("ravel.controller.routes.select")

PROMPTS = {
    "study": "Apply the selection of the fictional search to the supplied event file events.lhe and report the yields.",
    "manuscript": "Write a short internal note summarising the fictional results we already obtained.",
    "chain": "Draw the tree-level Feynman diagrams for a fictional scalar decaying to two photons.",
    "open": "Estimate the yield of a fictional widget process in a toy model and report the value with its uncertainty.",
    "research": "Investigate whether a new anomaly-detection method improves sensitivity for a fictional dark sector.",
    "analysis": "Reproduce the published exclusion contour of a fictional search for a heavy scalar decaying to two "
                "photons at 13 TeV.",
    "calculation": "Compute 2+2 and report the result.",
    "scoped": "Generate 10000 parton-level events for p p > t t~ at 13 TeV.",
    "held": "Do not do anything.",
}
# (request, supplied inputs, expected route) in the order of the start.md table.
ROWS = [
    ("study", [{"kind": "events", "path": "/fictional/events.lhe", "sha256": None}], "fixture-study"),
    ("manuscript", [], "fixture-manuscript"),
    ("chain", [], "fixture-chain"),
    ("open", [], "judgment"),
    ("research", [], "fixture-research"),
    ("analysis", [], "fixture-analysis"),
    ("calculation", [], "fixture-calculation"),
    ("scoped", [], "fixture-scoped"),
    ("held", [], "judgment"),
]


@pytest.fixture(scope="module")
def records():
    return {name: _draft_route(prompt, None, None)[:2] for name, prompt in PROMPTS.items()}


@pytest.fixture
def specs():
    with routes.registered(*fakes.route_specs(), only=True):
        yield fakes.route_specs()


@pytest.mark.parametrize("name,supplied,expected", ROWS, ids=[row[0] for row in ROWS])
def test_each_start_table_row_selects_its_route(records, specs, name, supplied, expected):
    contract, reading = records[name]
    decision = routes.select(contract, reading, supplied)
    assert decision["route"] == expected
    assert decision["evidence"][-1]["matched"] is True and decision["evidence"][-1]["route"] == expected
    assert set(decision) >= {"route", "evidence"}


def test_precedence_follows_the_table_rows_not_file_order(records):
    shuffled = list(reversed(fakes.route_specs()))
    with routes.registered(*shuffled, only=True):
        rows = [s["match"]["row"] for s in selection.ordered(routes.load_specs())]
        assert rows == sorted(rows)
        # The supplied-input row precedes the open-parent row it would otherwise fall into.
        contract, reading = records["study"]
        assert routes.select(contract, reading, [{"kind": "events"}])["route"] == "fixture-study"
        assert routes.select(contract, reading, [])["route"] == "judgment"
        # A whole-scope study cannot include new generation: the stage keeps it off the study row.
        mixed = deepcopy(reading)
        mixed["constraints"].append({"type": "requested_stage", "value": {"stage": "generation"}})
        assert routes.select(contract, mixed, [{"kind": "events"}])["route"] != "fixture-study"


def test_JR01_no_match_held_and_open_requests_go_to_judgment_and_nothing_is_refused(records):
    with routes.registered(only=True):
        for name in PROMPTS:
            contract, reading = records[name]
            decision = routes.select(contract, reading, [])
            assert decision["route"] == "judgment", name
    with routes.registered(*fakes.route_specs(), only=True):
        decision = routes.select(*records["held"], [])
        assert decision["route"] == "judgment" and decision["row"] == 9
        assert "D1" not in decision["evidence"][-1]["reason"]
        decision = routes.select(*records["open"], [])
        assert decision["route"] == "judgment" and decision["row"] == 4
        # Malformed or empty intake records still route (to judgment); there is no refusal outcome.
        assert routes.select({}, {}, [])["route"] == "judgment"
    import inspect
    source = inspect.getsource(selection)
    assert "refused" not in source.split("def select", 1)[1]


def test_R01_a_development_phrasing_never_drops_scientific_deliverables():
    contract, reading, _ = _draft_route("Refactor the scan code and also produce a 95% CLs exclusion limit plot "
                                        "for a fictional model.", None, None)
    inspect_spec = fakes._spec("fixture-inspect", 1, {"field": "deliverable_count", "in": list(range(0, 50))},
                               fakes._one_step(kind="derive"), [], admits=False)
    with routes.registered(inspect_spec, *fakes.route_specs(), only=True):
        decision = routes.select(contract, reading, [])
        assert decision["route"] == "fixture-analysis"
        skipped = [e for e in decision["evidence"] if e["route"] == "fixture-inspect"]
        assert skipped and skipped[0]["matched"] is False and "scientific" in skipped[0]["reason"]
        no_science = {"task_mode": "research"}
        assert routes.select(no_science, {"deliverables": []}, [])["route"] == "fixture-inspect"


def test_spec_and_predicate_validation():
    good = fakes.route_specs()[0]
    assert selection.spec_errors(good) == []
    for broken, fragment in (
            ({**good, "match": {"row": 1, "when": {"field": "nope", "eq": "x"}}}, "not a view field"),
            ({**good, "match": {"row": 1, "when": {"field": "task_mode", "contains_any": ["x"]}}}, "list field"),
            ({**good, "match": {"row": 1, "when": {"all": []}}}, "non-empty list"),
            ({**good, "match": {"row": 1, "when": {"field": "held", "is": "yes"}}}, "true or false"),
            ({**good, "id": "judgment"}, "controller's own"),
            ({**good, "kind": "other"}, "literally")):
        errors = selection.spec_errors(broken)
        assert errors and any(fragment in e for e in errors), (fragment, errors)
    with pytest.raises(routes.RouteSpecError):
        with routes.registered({**good, "match": {"row": 1, "when": {}}}):
            pass
    with pytest.raises(routes.RouteSpecError, match="duplicate"):
        with routes.registered(good, good, only=True):
            pass


def test_evaluate_operators():
    facts = {"task_mode": "scan", "requested_stages": ["figure", "statistic"], "held": False, "supplied_kinds": []}
    holds = selection.evaluate
    assert holds({"field": "task_mode", "eq": "scan"}, facts)
    assert holds({"field": "task_mode", "in": ["scan", "reproduce"]}, facts)
    assert holds({"field": "requested_stages", "contains_any": ["figure"]}, facts)
    assert holds({"field": "requested_stages", "contains_all": ["figure", "statistic"]}, facts)
    assert holds({"field": "requested_stages", "disjoint": ["generation"]}, facts)
    assert holds({"field": "supplied_kinds", "empty": True}, facts)
    assert holds({"field": "held", "is": False}, facts)
    assert holds({"not": {"field": "task_mode", "eq": "reproduce"}}, facts)
    assert holds({"any": [{"field": "task_mode", "eq": "x"}, {"field": "held", "is": False}]}, facts)
    assert not holds({"all": [{"field": "task_mode", "eq": "scan"}, {"field": "held", "is": True}]}, facts)


def test_installed_specs_are_validated_and_route_registration_is_a_test_seam(tmp_path, monkeypatch):
    from ravel.controller import testing
    with testing.seams(False):
        with pytest.raises(testing.SeamRefused):
            with routes.registered(*fakes.route_specs()):
                pass
    monkeypatch.setattr(selection, "ROUTES", tmp_path)
    (tmp_path / "bad.json").write_text('{"schema_version": 1, "kind": "route-spec", "id": "x"}')
    with pytest.raises(routes.RouteSpecError, match="invalid"):
        selection.installed_specs()
    (tmp_path / "bad.json").unlink()
    import json
    family = {"schema_version": 1, "kind": "route-spec-family", "specs": fakes.route_specs()[:2]}
    (tmp_path / "family.json").write_text(json.dumps(family))
    assert [s["id"] for s in selection.installed_specs()] == ["fixture-study", "fixture-manuscript"]


def test_a_missing_adapter_is_typed_and_an_installed_adapters_own_import_error_propagates(tmp_path, monkeypatch):
    spec = {**fakes.route_specs()[0], "adapter": "fixture_absent_adapter"}
    with pytest.raises(selection.RouteAdapterMissing) as missing:
        routes.adapter_module(spec)
    assert missing.value.reason == "route_adapter_missing" and missing.value.route == spec["id"]
    assert not isinstance(missing.value, routes.RouteSpecError)  # a caller never goes on without the route's hooks
    # The package that would hold the adapter is absent: the adapter is not installed either.
    with pytest.raises(selection.RouteAdapterMissing):
        routes.adapter_module({**spec, "adapter": "fixture_absent_package.adapter"})
    # An installed adapter that fails its own import raises that error, unchanged.
    package = import_module("ravel.controller.routes")
    (tmp_path / "fixture_broken_adapter.py").write_text("import fictional_missing_dependency  # noqa: F401\n")
    monkeypatch.setattr(package, "__path__", [*package.__path__, str(tmp_path)])
    with pytest.raises(ModuleNotFoundError) as broken:
        routes.adapter_module({**spec, "adapter": "fixture_broken_adapter"})
    assert broken.value.name == "fictional_missing_dependency"
    assert not isinstance(broken.value, selection.RouteAdapterMissing)
    # ``routes.select`` stays the binding selection function (the module is read from sys.modules).
    assert routes.select is selection.select and callable(routes.select)
