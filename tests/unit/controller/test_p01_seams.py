"""P01 in-process seams (SW30) and the substrate's refusal of ``--clear-stop`` for controller runs (SW05).

The test harness enables the seams in this process (``tests/conftest.py``); each case turns them off
with ``testing.seams(False)`` to run as a production process would. A controller process, and any
scope a controller run owns, refuses ``gate_check``/``gate_providers``, the ``GATE_CHECK``/
``GATE_PROVIDERS`` context variables, in-process registrations and ``machine_lease._LOCATION``.
Legacy runs in an ordinary process keep their seams.
"""
from __future__ import annotations

import pytest

import fakes
from ravel.controller import graph, routes, testing
from ravel.controller.store import RunStore
from ravel.workflow import graph_nodes, graph_registry, graph_substrate as gs, machine_lease

SELFTEST = {"label": "seams", "steps": 0, "delay_ms": 0, "ask": False}


def _owned_scope(tmp_path):
    store = RunStore.create(tmp_path / "runs" / "owned", root=tmp_path / "store")
    return store, store.graph_scope()


def _gate(scope, gate_name, action):
    return []


def test_SW30_gate_seams_are_refused_for_a_controller_scope_outside_the_harness(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "legacy-state"))
    _, scope = _owned_scope(tmp_path)
    with testing.seams(False):
        for options in ({"gate_check": _gate}, {"gate_providers": lambda g: {}}):
            with pytest.raises(ValueError, match="in-process test seam"):
                gs.run(scope, "substrate.selftest", SELFTEST, **options)
        with graph_nodes.gate_checker(_gate, None, None, []):
            with pytest.raises(ValueError, match="in-process test seam"):
                gs.run(scope, "substrate.selftest", SELFTEST)
        with pytest.raises(ValueError, match="in-process test seam"):
            gs.respond(scope, "substrate.selftest", SELFTEST, {"x": {}}, gate_check=_gate)
    # The harness may use them on the same scope.
    observation = gs.run(scope, "substrate.selftest", SELFTEST, gate_check=_gate)
    assert observation["graph_id"] == "substrate.selftest"


def test_SW30_a_controller_process_refuses_every_seam_even_for_legacy_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "legacy-state"))
    legacy = tmp_path / "legacy-scope"
    with testing.seams(False, controller=True):
        with pytest.raises(ValueError, match="in-process test seam"):
            gs.run(legacy, "substrate.selftest", SELFTEST, gate_check=_gate)
        with pytest.raises(graph_registry.RegistryError, match="in-process test seam"):
            with graph_registry.registered(*fakes.graph_rows(), replace=True):
                pass
        with pytest.raises(testing.SeamRefused):
            with routes.registered(*fakes.route_specs()):
                pass
        with pytest.raises(testing.SeamRefused):
            with graph.services(ledger=fakes.FakeLedger()):
                pass
        monkeypatch.setattr(machine_lease, "_LOCATION", str(tmp_path / "elsewhere"))
        with pytest.raises(ValueError, match="machine_lease._LOCATION"):
            gs.run(legacy, "substrate.selftest", SELFTEST)
        monkeypatch.setattr(machine_lease, "_LOCATION", None)
        assert gs.run(legacy, "substrate.selftest", SELFTEST)["graph_id"] == "substrate.selftest"


def test_SW30_legacy_scopes_in_an_ordinary_process_keep_their_seams(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "legacy-state"))
    with testing.seams(False, controller=False):
        observation = gs.run(tmp_path / "legacy-scope", "substrate.selftest", SELFTEST, gate_check=_gate)
        assert observation["graph_id"] == "substrate.selftest"
        with graph_registry.registered(*fakes.graph_rows(), replace=True):
            assert graph_registry.get("controller.step")["owner"] == "controller-fakes"


def test_SW30_a_gate_override_is_ignored_and_recorded_for_a_controller_run(tmp_path):
    store, _ = _owned_scope(tmp_path)
    action = {"kind": "x", "digest": "0" * 64, "summary": "x", "pins": []}
    with testing.seams(False), graph_nodes.gate_checker(_gate, None, lambda g: {"review_points": True}, []):
        errors = graph_nodes.check_gate(str(store.run_dir), "approve_plan", action)
    assert errors[0]["code"] == "seam_refused"
    assert any(e["code"] != "seam_refused" for e in errors)  # the installed decision gate decided
    with graph_nodes.gate_checker(_gate, None, lambda g: {}, []):
        assert all(e["code"] != "seam_refused" for e in graph_nodes.check_gate(str(store.run_dir), "approve_plan",
                                                                               action))


def test_SW30_only_a_conftest_enables_the_seams_and_no_environment_does(monkeypatch):
    with pytest.raises(testing.SeamRefused, match="conftest"):
        testing.enable_seams()
    for name in ("RAVEL_TEST_SEAMS", "RAVEL_ENABLE_SEAMS", "PYTEST_CURRENT_TEST"):
        monkeypatch.setenv(name, "1")
    with testing.seams(False):
        assert testing.seams_enabled() is False
        with pytest.raises(testing.SeamRefused):
            testing.refuse("anything")
    assert testing.seams_enabled() is True


def test_SW05_the_substrate_refuses_clear_stop_for_a_controller_run(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "legacy-state"))
    store, scope = _owned_scope(tmp_path)
    gs.stop(scope, reason="operator stop")
    for target in (scope, store.run_dir):
        with pytest.raises(ValueError, match="--clear-stop is refused"):
            gs.run(target, "substrate.selftest", SELFTEST, clear_stop=True)
        with pytest.raises(ValueError, match="--clear-stop is refused"):
            gs.respond(target, "substrate.selftest", SELFTEST, {"x": {}}, clear_stop=True)
        with pytest.raises(ValueError, match="--clear-stop is refused"):
            gs.refuse_controller_switches(target, clear_stop=True)
    assert (scope / gs.STOP).exists()
    legacy = tmp_path / "legacy-scope"
    gs.stop(legacy, reason="legacy stop")
    observation = gs.run(legacy, "substrate.selftest", SELFTEST, clear_stop=True)
    assert observation["graph_id"] == "substrate.selftest" and not (legacy / gs.STOP).exists()


def test_the_registration_loader_reads_fragments_and_refuses_duplicates(tmp_path, monkeypatch):
    import json
    row = dict(graph_registry.get("substrate.selftest"))
    rows = graph_registry.fragments()
    assert [r["id"] for r in rows if r["id"] == graph.GRAPH_ID] == [graph.GRAPH_ID]
    (tmp_path / "a.json").write_text(json.dumps({"schema_version": 1, "kind": "graph-registration",
                                                 "graphs": [{**row, "id": "fixture.fragment"}]}))
    monkeypatch.setattr(graph_registry, "REGISTRATION", tmp_path)
    assert graph_registry.get("fixture.fragment")["builder"] == "selftest"
    (tmp_path / "b.json").write_text(json.dumps({"schema_version": 1, "kind": "graph-registration",
                                                 "graphs": [{**row, "id": "fixture.fragment"}]}))
    with pytest.raises(graph_registry.RegistryError, match="duplicate"):
        graph_registry.load()
    (tmp_path / "b.json").write_text(json.dumps({"kind": "graph-registry", "graphs": []}))
    with pytest.raises(graph_registry.RegistryError, match="graph-registration"):
        graph_registry.load()
    (tmp_path / "b.json").write_text(json.dumps({"schema_version": 1, "kind": "graph-registration",
                                                 "graphs": [{**row, "id": "Bad Id"}]}))
    with pytest.raises(graph_registry.RegistryError, match="invalid"):
        graph_registry.load()


def test_seam_and_clear_stop_refusals_name_no_internal_row_label(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "legacy-state"))
    _, scope = _owned_scope(tmp_path)
    messages = []
    with testing.seams(False, controller=True):
        for call in (lambda: gs.run(scope, "substrate.selftest", SELFTEST, gate_check=_gate),
                     lambda: gs.refuse_controller_switches(scope, clear_stop=True),
                     lambda: testing.refuse("anything")):
            with pytest.raises(ValueError) as caught:
                call()
            messages.append(str(caught.value))
    assert messages and all("SW" not in m for m in messages), messages
