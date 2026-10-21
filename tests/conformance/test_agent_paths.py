"""G8 conformance: the agent call-site census.

1. completeness, 2. no new bypass, 3. detector recall by mutation, 4. graph introspection,
5. runtime boundary tripwire, 6. host surfaces. Fixtures under ``fixtures/`` are parsed,
never imported; each names the module it is planted in on its first line, so a fixture
can sit inside a sanctioned module at an unsanctioned qualname.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ravel.validation import check_agent_paths as cap

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def census():
    return cap.census()


def _scan(name):
    path = FIXTURES / name
    text = path.read_text()
    module = text.splitlines()[0].split("census-module:", 1)[1].strip()
    return cap.classify(cap.scan_source(text, module=module, path=f"fixtures/{name}"), cap.load_sanctioned())


def _found(rows, disposition="bypass"):
    return {(r["qualname"].split(":", 1)[1], r["sink"]) for r in rows if r["disposition"] == disposition}


# ---- 1. completeness -----------------------------------------------------------------

def test_census_regenerates_byte_identically(census):
    assert cap.render(census) == cap.CALL_SITES.read_bytes(), (
        "call_sites.json is stale: python -m ravel.validation.check_agent_paths census --write")


def test_every_file_on_disk_is_scanned(census):
    on_disk = sorted(p.relative_to(cap.SRC.parent).as_posix() for p in cap.SRC.rglob("*.py")
                     if "__pycache__" not in p.parts)
    assert census["files_scanned"] == len(on_disk)
    assert census["files_sha256"] == cap.digest(on_disk)


def test_every_row_has_the_declared_fields(census):
    for row in census["rows"]:
        assert set(row) == set(cap.ROW_FIELDS)
        assert row["sink"] in cap.SINKS and row["disposition"] in cap.DISPOSITIONS


# ---- 2. no new bypass ----------------------------------------------------------------

def test_every_bypass_is_in_the_baseline(census):
    report = cap.compare(census, cap.load_baseline())
    assert report["new_bypasses"] == [], json.dumps(report["new_bypasses"], indent=1)


def test_baseline_only_shrinks(census):
    baseline = cap.load_baseline()
    report = cap.compare(census, baseline)
    assert report["stale_entries"] == [], (
        "these bypasses are gone; delete them from bypass_baseline.json: "
        + json.dumps(report["stale_entries"], indent=1))
    assert len(baseline["entries"]) <= baseline["ceiling"]
    for entry in baseline["entries"]:
        assert entry["fix_package"] and entry["reason"]


def test_a_planted_bypass_is_a_new_row_and_fails_the_comparison(census):
    rows = _scan("bypass_agent_graph.py")
    report = cap.compare({**census, "rows": census["rows"] + rows}, cap.load_baseline())
    assert {(e["qualname"], e["sink"]) for e in report["new_bypasses"]} == {
        ("ravel.workflow.synthetic_caller:run_directly", "S3")}


# ---- 3. detector recall by mutation ---------------------------------------------------

MUTATIONS = {
    "bypass_agent_host_inside.py": {("rogue_direct", "S1"), ("rogue_alias", "S1")},
    "bypass_agent_host_alias.py": {("through_alias", "S1"), ("through_module_alias", "S1"),
                                   ("through_helper", "S1"), ("through_annotation", "S1"),
                                   ("through_getattr", "S1")},
    "bypass_sdk.py": {("direct_import", "S4"), ("dynamic_import", "S4"), ("from_import", "S4"),
                      ("upstream_loop", "S5"), ("upstream_package", "S5")},
    "bypass_stategraph.py": {("rogue_graph", "S2")},
    "bypass_launcher.py": {("rogue_literal", "S1"), ("rogue_assembled", "S1"), ("rogue_template", "S1")},
    "bypass_instructions.py": {("literal_dict", "S6"), ("literal_subscript", "S6"), ("bound_then_used", "S6"),
                               ("from_prompt_file", "S6")},
    "bypass_agent_graph.py": {("run_directly", "S3")},
    "bypass_control_flow.py": {("rogue_body", "S2"), ("rogue_router", "S2")},
    "bypass_ungated_effect.py": {("_ungated_launch", "S7")},
    "bypass_clean.py": set(),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_planted_fixture_is_detected_exactly(name):
    assert _found(_scan(name)) == MUTATIONS[name]


def test_every_fixture_file_has_an_expectation():
    assert sorted(p.name for p in FIXTURES.glob("bypass_*.py")) == sorted(MUTATIONS)


def test_gated_effect_is_substrate_and_ungated_effect_is_a_bypass():
    rows = _scan("bypass_ungated_effect.py")
    assert _found(rows, "substrate") == {("_gated_launch", "S7")}
    ungated = [r for r in rows if r["qualname"].endswith(":_ungated_launch")]
    assert ungated and all(r["gate"] is None for r in ungated)


def test_sanctions_name_qualnames_not_modules():
    for row in cap.load_sanctioned()["sanctioned"]:
        module, qualname = row["qualname"].split(":", 1)
        assert module.startswith("ravel.") and qualname and qualname != "<module>"


@pytest.mark.parametrize("graph_id", [
    "literature.scout", "literature.source", "manuscript.build", "manuscript.section",
    "research.loop", "research.stage",
])
def test_shared_builders_have_exact_registered_graph_sanctions(graph_id):
    from ravel.workflow import graph_registry
    registered = graph_registry.get(graph_id)
    qualname = registered["module"] + ":" + registered["builder"]
    matches = [row for row in cap.load_sanctioned()["sanctioned"] if row["qualname"] == qualname]
    assert len(matches) == 1
    assert matches[0]["disposition"] == "registered_graph"
    assert matches[0]["sinks"] == ["S2"] and matches[0]["graph_id"] == graph_id


def test_research_dispatch_and_legacy_pause_use_shared_substrate_calls(census):
    migrated = {
        "ravel.workflow.graphs.stage:_dispatch.run",
        "ravel.workflow.research_orchestrator:_open_plan.idea_call",
        "ravel.workflow.research_orchestrator:_legacy_pause",
    }
    assert not [row for row in census["rows"] if row["qualname"] in migrated]
    shared = [row for row in census["rows"] if row["qualname"] in {
        "ravel.workflow.graph_substrate:execute_role_graph",
        "ravel.workflow.graph_substrate:legacy_pause",
    }]
    assert {row["sink"] for row in shared} == {"S2", "S3"}
    assert all(row["disposition"] == "substrate" for row in shared)


def test_sanctioned_qualnames_still_exist(census):
    seen = {(r["qualname"], r["sink"]) for r in census["rows"]}
    missing = [row["qualname"] for row in cap.load_sanctioned()["sanctioned"]
               if not any((row["qualname"], sink) in seen for sink in row["sinks"])]
    assert missing == [], "remove sanctions that no longer match a call site: " + ", ".join(missing)


# ---- 4. graph introspection -----------------------------------------------------------

def _registered():
    from ravel.workflow import graph_registry
    return json.loads(graph_registry.REGISTRY.read_text())["graphs"]  # committed rows, not test registrations


@pytest.mark.parametrize("row", _registered(), ids=lambda r: r["id"])
def test_registered_graph_walk(row, tmp_path):
    findings = cap.introspect_graph(row, scope_root=tmp_path)
    assert findings["problems"] == [], findings


def test_a_graph_that_reads_a_retained_root_is_walked_over_a_root_made_inside_the_scope(tmp_path):
    row = next(r for r in _registered() if r["id"] == "intake.plan")
    declared = cap.load_sanctioned()["introspection_roots"]["intake.plan"]
    assert declared["instance_key"] in row["instance_keys"]
    instance = cap._materialized("intake.plan", {declared["instance_key"]: "unused"}, tmp_path)
    root = instance[declared["instance_key"]]
    assert root.is_relative_to(tmp_path) and (root / "graph_spec.json").is_file()
    assert cap.introspect_graph(row, scope_root=tmp_path / "walk")["problems"] == []


def test_introspection_reports_dominance_without_treating_it_as_authority(tmp_path):
    row = _registered()[0]
    findings = cap.introspect_graph(row, scope_root=tmp_path)
    assert set(findings["gate_dominance"]) == set(findings["consequential_effects"])


@pytest.mark.xfail(reason="awaits the ravel_loop per-use builder and the research-board item subgraphs", strict=True)
def test_per_use_builders_are_walked(tmp_path):
    assert cap.per_use_builders(), "no per-use builder (agent, ravel_loop, item subgraph) is registered yet"


# ---- 5. runtime boundary assertions ---------------------------------------------------

def test_tripwire_is_silent_when_off(monkeypatch):
    from ravel.workflow import agent_tripwire
    monkeypatch.delenv(agent_tripwire.ENV, raising=False)
    assert agent_tripwire.check("provider_transport.request") is None


def test_tripwire_refuses_a_call_without_substrate_context(monkeypatch):
    from ravel.workflow import agent_tripwire
    monkeypatch.setenv(agent_tripwire.ENV, "1")
    with pytest.raises(agent_tripwire.TripwireViolation, match="provider_transport.request"):
        agent_tripwire.check("provider_transport.request")


def test_tripwire_report_mode_records_without_raising(monkeypatch, tmp_path):
    from ravel.workflow import agent_tripwire
    record = tmp_path / "tripwire.jsonl"
    monkeypatch.setenv(agent_tripwire.ENV, "report")
    monkeypatch.setenv(agent_tripwire.RECORD_ENV, str(record))
    result = agent_tripwire.check("authorized_popen")
    assert result["ok"] is False and result["reason"] == "no_substrate_context"
    line = json.loads(record.read_text().splitlines()[0])
    assert line["layer"] == "authorized_popen" and line["ok"] is False


def test_tripwire_accepts_an_acting_node_and_refuses_a_non_acting_one(monkeypatch):
    from ravel.workflow import agent_tripwire, graph_nodes
    monkeypatch.setenv(agent_tripwire.ENV, "1")
    seen = {}

    def body(state):
        seen["result"] = agent_tripwire.check("authorized_popen")
        return {}
    graph_nodes._instrumented("effect", "synthetic.graph", None, body)({})
    assert seen["result"]["ok"] is True and seen["result"]["context"]["graph_id"] == "synthetic.graph"

    def gate_body(state):
        agent_tripwire.check("authorized_popen")
        return {}
    with pytest.raises(agent_tripwire.TripwireViolation, match="kind gate may not reach authorized_popen"):
        graph_nodes._instrumented("gate", "synthetic.graph", None, gate_body)({})


def test_every_tripwire_layer_names_a_real_callable():
    from importlib import import_module
    for layer in cap.load_sanctioned()["tripwire_layers"]:
        module, qualname = layer["callable"].split(":")
        target = import_module(module)
        for part in qualname.split("."):
            target = getattr(target, part)
        assert callable(target) and layer["acting_kinds"]


def test_lowest_layers_assert_substrate_context(census, tmp_path, monkeypatch):
    import runpy
    assert cap.tripwire_coverage(census)["missing"] == []
    controls = runpy.run_path(str(Path(__file__).parents[1] / "unit" / "test_agent_tripwire.py"))
    for index, layer in enumerate(controls["LAYERS"]):
        root = tmp_path / str(index)
        root.mkdir()
        controls["test_lowest_layers_assert_substrate_context"](root, monkeypatch, layer)


@pytest.mark.xfail(reason="awaits workload chains and their fixtures", strict=True)
def test_fixture_chains_run_clean_under_the_tripwire():
    assert cap.tripwire_chains(), "no workload chain is registered"


# ---- 6. host surfaces -----------------------------------------------------------------

def test_transport_attested_roles_redirect_on_every_host_surface():
    problems = cap.host_surface_problems()
    assert problems == [], "\n".join(problems)


def test_host_surface_check_catches_a_local_profile(monkeypatch):
    from ravel.workflow import role_registry
    real = role_registry.render

    def leaky(surface, **kwargs):
        files = real(surface, **kwargs)
        return {path: content.replace("Do not perform this role here.", "Perform this role.")
                for path, content in files.items()}
    monkeypatch.setattr(role_registry, "render", leaky)
    assert cap.host_surface_problems()


# ---- gate record ----------------------------------------------------------------------

def test_release_check_g8_reports_in_report_mode(capsys):
    from ravel import cli
    assert cli.main(["release", "check", "--gate", "G8"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["gate"] == "G8" and record["mode"] == "report"
    assert record["passed"] is (record["baseline_entries"] == 0 and not record["blocking_reasons"])
    assert record["new_bypasses"] == 0 and record["stale_entries"] == 0


def test_release_check_blocks_in_empty_mode_while_the_baseline_has_rows(capsys):
    record = cap.gate_record(mode="empty")
    assert record["passed"] is False and any("baseline" in r for r in record["blocking_reasons"])
    assert cap.main(["check", "--gate", "G8", "--mode", "empty"]) == 1


def test_release_check_refuses_other_gates(capsys):
    assert cap.main(["check", "--gate", "G1"]) == 2
    assert "gate G1: this command records G8 only" in capsys.readouterr().err


def test_report_mode_is_the_committed_enforcement():
    assert cap.load_baseline()["enforcement"] == "report"


def test_upstream_framework_modules_are_matched_by_digest(monkeypatch):
    """Retired upstream frameworks are named only by digest; a digest match is an S5 import."""
    import hashlib
    name = "example_retired_framework"
    assert not cap._is_s5_module(name + ".core")
    monkeypatch.setattr(cap, "S5_MODULE_DIGESTS", cap.S5_MODULE_DIGESTS | {hashlib.sha256(name.encode()).hexdigest()})
    assert cap._is_s5_module(name) and cap._is_s5_module(name + ".core")
    assert cap._is_s5_module("autogen.agentchat")
