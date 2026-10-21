"""The 1.1.0 analysis entries keep working on legacy runs and refuse controller-owned runs (NOT GOVERNED)."""
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from ravel.workflow import resource_census, scan_babysitter, scan_orchestrator, trap_sweep
from ravel.workflow.graphs import lifecycle, production
from p09_support import trap_sweep_record


@pytest.fixture
def owned(monkeypatch, tmp_path):
    """A fake command policy that owns ``tmp_path/owned`` and exposes only the binding ``check`` interface."""
    root = (tmp_path / "owned").resolve()
    root.mkdir()
    calls = []

    def check(argv):
        calls.append(list(argv))
        for value in argv[1:]:
            path = Path(str(value)).resolve() if "/" in str(value) else None
            if path is not None and (path == root or root in path.parents):
                return f"`ravel {argv[0]}` is refused for the controller-owned run fixture-run ({value}) [SW13]"
        return None

    policy = types.ModuleType("ravel.controller.command_policy")
    policy.check = check
    controller = importlib.import_module("ravel.controller")
    monkeypatch.setitem(sys.modules, "ravel.controller.command_policy", policy)
    monkeypatch.setattr(controller, "command_policy", policy, raising=False)
    return root, calls


def test_lifecycle_refuses_a_controller_owned_run(owned):
    root, calls = owned
    with pytest.raises(PermissionError, match="controller-owned"):
        lifecycle.run(root)
    with pytest.raises(PermissionError, match="controller-owned"):
        lifecycle.respond(root, decision="approve")
    assert calls[0][:2] == ["lifecycle", "run"] and calls[1][:2] == ["lifecycle", "respond"]


def test_lifecycle_cli_reports_the_refusal(owned, capsys):
    root, _ = owned
    assert lifecycle.main(["--rundir", str(root)]) == 2
    assert "controller-owned" in capsys.readouterr().err


def test_lifecycle_passes_the_policy_for_a_legacy_run(owned, tmp_path):
    """A legacy run is not refused by the policy (it continues into the 1.1.0 lifecycle)."""
    _, calls = owned
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    lifecycle.refuse_controller_owned(legacy, "run")
    assert calls == [["lifecycle", "run", "--rundir", str(legacy.resolve())]]


def test_lifecycle_results_carry_the_not_governed_label():
    assert lifecycle.NOT_GOVERNED == "NOT GOVERNED"
    source = Path(lifecycle.__file__).read_text()
    assert "'governance': NOT_GOVERNED" in source


def test_production_entry_refuses_a_controller_owned_run(owned):
    root, calls = owned
    with pytest.raises(PermissionError, match="controller-owned"):
        production.run(root, "node-1")
    assert calls == [["production", "run", "--rundir", str(root)]]


def test_production_passes_the_policy_for_a_legacy_run(owned, tmp_path, monkeypatch):
    from ravel.workflow import graph_substrate

    _, calls = owned
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    invoked = []
    result = object()

    def run(*args, **kwargs):
        invoked.append((args, kwargs))
        return result

    monkeypatch.setattr(graph_substrate, "run", run)
    assert production.run(legacy, "node-1") is result
    assert calls == [["production", "run", "--rundir", str(legacy.resolve())]]
    assert invoked[0][0] == (legacy, production.GRAPH_ID, {"node_id": "node-1", "attempt": 1})
    assert invoked[0][1]["input"] == {"node": {"node_id": "node-1", "attempt": 1}}


def test_production_never_lets_a_host_waiver_fill_a_controller_owned_seat(monkeypatch, tmp_path):
    monkeypatch.setattr(production, "_controller_owned", lambda root: "fixture-run")
    monkeypatch.setattr(production.executor, "load_order",
                        lambda root, node: {"node_id": node, "role": "generator", "rung": "full",
                                            "order_sha256": "0" * 64, "executor": "host"})
    state = {"meta": {"scope_root": str(tmp_path), "instance": {"node_id": "node-1", "attempt": 1}},
             "node": {"node_id": "node-1", "attempt": 1}}
    with pytest.raises(Exception) as caught:
        production._order(state, {})
    assert "production_host_refused" in str(caught.value) or "host waiver" in str(caught.value)


def test_scan_orchestrator_refuses_a_controller_owned_scan(owned, monkeypatch):
    root, _ = owned
    monkeypatch.setattr(sys, "argv", ["scan_orchestrator", "launch", str(root), "--go"])
    with pytest.raises(SystemExit) as caught:
        scan_orchestrator.main()
    assert "controller-owned" in str(caught.value)


def test_scan_orchestrator_plan_refuses_a_run_root_inside_a_controller_owned_run(owned, monkeypatch, tmp_path):
    """``plan`` writes under the spec's run_root: a spec kept outside an owned run cannot plan points into it."""
    root, _ = owned
    template = tmp_path / "supplied.toml"
    template.write_text("[parameters]\nvalue = 0\n")
    spec = {"schema_version": 2, "name": "SCAN-A", "template_toml": str(template),
            "subst": {"parameters.value": "value"}, "run_prefix": "SCAN-A", "run_root": str(root / "runs"),
            "axes": [{"name": "value", "values": [2, 4]}], "max_points": 10,
            "datasets": [{"id": "DATA-A", "path": "supplied-events"}],
            "quantities": [{"name": "response", "source": "output/response.json", "field": "value"}],
            "output": {"format": "json", "path": "requested.json"}}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    monkeypatch.setattr(sys, "argv", ["scan_orchestrator", "plan", str(path)])
    with pytest.raises(SystemExit) as caught:
        scan_orchestrator.main()
    assert "controller-owned" in str(caught.value)
    assert not (root / "runs").exists()
    # positive control: the same spec planning outside the owned run writes its manifest
    spec["run_root"] = str(tmp_path / "legacy-runs")
    path.write_text(json.dumps(spec))
    scan_orchestrator.main()
    assert (tmp_path / "legacy-runs" / "SCAN-A_SCAN" / "scan_manifest.json").is_file()


def test_e22_e23_scan_babysitter_refuses_a_controller_owned_scan(owned, monkeypatch, capsys):
    root, _ = owned
    monkeypatch.setattr(sys, "argv", ["scan_babysitter", str(root), "--once"])
    assert scan_babysitter.main() == 2
    assert "controller-owned" in capsys.readouterr().err


def test_trap_sweep_validates_a_record_where_the_governed_step_adopted_it(tmp_path):
    target = tmp_path / "steps" / "inputs.traps" / "outputs" / "trap_sweep.json"
    target.parent.mkdir(parents=True)
    import json
    target.write_text(json.dumps(trap_sweep_record()))
    report = trap_sweep.validate(tmp_path, relative="steps/inputs.traps/outputs/trap_sweep.json")
    assert report["status"] == "PASS" and report["traps_hit"] == ["T8"]
    with pytest.raises(ValueError):
        trap_sweep.validate(tmp_path, relative="../outside.json")
    assert trap_sweep.validate(tmp_path)["status"] == "FAIL"  # the legacy location is unchanged


def test_census_targets_come_from_the_pinned_reading():
    reading = {"facts": [{"type": "identifier", "value": {"scheme": "inspire", "id": "4242"}},
                         {"type": "identifier", "value": {"scheme": "arxiv", "id": "fictional-preprint-7"}}]}
    analyses, keywords = resource_census.reading_targets(reading)
    assert analyses == [{"inspire": "4242", "arxiv": "fictional-preprint-7", "id": None}] and keywords == []
    analyses, keywords = resource_census.reading_targets(
        {"facts": [{"type": "model_term", "value": {"text": "widget pair"}},
                   {"type": "experiment", "value": {"text": "fictional detector"}}]})
    assert analyses == [] and keywords == ["widget pair fictional detector"]
    assert resource_census.reading_targets({"facts": []}) == ([], [])
    with pytest.raises(ValueError):
        resource_census.reading_targets([])


def test_census_cli_refuses_a_reading_that_names_nothing(tmp_path, capsys):
    path = tmp_path / "reading.json"
    path.write_text('{"facts": []}')
    with pytest.raises(SystemExit):
        resource_census.main(["--reading", str(path)])
    assert "names an analysis or topic" in capsys.readouterr().err


def test_e04_controller_census_embeds_every_source_record(tmp_path, monkeypatch):
    from ravel.workflow import resource_census
    reading = tmp_path / 'reading.json'
    reading.write_text('{"facts":[{"type":"identifier","value":{"scheme":"inspire","id":"4242"}}]}')
    member = {'id': 'fictional-source', 'rungs_ok': 1, 'rungs': {'metadata': {'status': 'OK', 'detail': [1, 2]}}}
    monkeypatch.setattr(resource_census, 'census_one', lambda *args: member)
    target = tmp_path / 'outputs/census.json'
    assert resource_census.main(['--reading', str(reading), '--controller-output', str(target)]) == 0
    import json
    doc = json.loads(target.read_text())
    assert doc['records'] == [member] and doc['rungs']['0/metadata']['detail'] == [1, 2]


def test_step_06_data_acquisition_keeps_registered_module_and_reader_guards(monkeypatch):
    from ravel.workflow import hepdata_fetch
    calls = []
    monkeypatch.setattr(hepdata_fetch, 'main', lambda args: calls.append(args) or 4)
    assert resource_census.main(['--fetch-published-data', '--inspire', '4242', '--tables']) == 4
    assert calls == [['--inspire', '4242', '--tables']]
