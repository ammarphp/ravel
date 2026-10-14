"""Optional grounded advice and real fresh-process arithmetic through the host."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.validation import numerical_witness
from ravel.physics import model_inputs
from ravel.workflow import agent_graph, agent_host, execution
from ravel.workflow.state_io import atomic_json, read_json
from test_agent_host import Control, pin, request, tool
from test_numerical_witness import fixture, raw
from test_research_transfer import setup


def grounded_inputs(tmp_path):
    case, affordances = setup(tmp_path)
    case_path, aff_path = tmp_path / "case.json", tmp_path / "affordances.json"
    atomic_json(case_path, case); atomic_json(aff_path, affordances)
    return tool("grounded-allocator", {"case_input": "case", "affordances_input": "affordances"},
                [pin(case_path, "case"), pin(aff_path, "affordances"), pin(tmp_path / "input.txt", "source")])


def witness_inputs(tmp_path, *, corrupted=False):
    data, census = fixture()
    claim = numerical_witness.derive(raw(data))
    if corrupted: claim["covariance"]["difference"][0][0] = "1/2"
    paths = [tmp_path / "witness.json", tmp_path / "claim.json", tmp_path / "census.json"]
    paths[0].write_bytes(raw(data)); paths[1].write_bytes(raw(claim)); paths[2].write_bytes(census)
    pins = [pin(path, key) for path, key in zip(paths, ["input", "claim", "census"])]
    pins.append(pin(Path(numerical_witness.__file__).resolve(), "checker"))
    return tool("numerical-witness", {"input_input": "input", "claim_input": "claim", "census_input": "census",
                                      "checker_input": "checker", "atol": "0", "rtol": "0"}, pins)


def test_grounded_advice_uses_all_pinned_dependencies_and_remains_optional(tmp_path):
    node = grounded_inputs(tmp_path); control = Control()
    result = agent_host.AgentHost().execute(node, request(node), control)
    assert result["value"]["policy"]["first_action"] == "witness"
    assert result["value"]["unique_class_count"] == 4
    assert result["execution_authorized"] is result["physics_validated"] is False
    assert len(control.calls) == 1


def test_grounded_unlisted_embedded_dependency_refuses_before_dispatch(tmp_path):
    node = grounded_inputs(tmp_path); node["inputs"].pop(); control = Control()
    with pytest.raises(agent_host.HostFailure, match="explicitly hash-bound"):
        agent_host.AgentHost().execute(node, request(node), control)
    assert control.calls == []


@pytest.mark.parametrize("action", ["grounded-allocator", "numerical-witness"])
@pytest.mark.parametrize("role", ["critic", "verifier"])
def test_new_raw_tools_cannot_bypass_blind_role_packet_boundary(action, role, tmp_path):
    node = grounded_inputs(tmp_path) if action == "grounded-allocator" else witness_inputs(tmp_path)
    node["role"] = role; control = Control()
    with pytest.raises(agent_host.HostFailure, match="blinded review role"):
        agent_host.AgentHost().execute(node, request(node), control)
    assert control.calls == []


@pytest.mark.parametrize("corrupted,status", [(False, "verified"), (True, "mismatch")])
def test_actual_fresh_checker_records_valid_and_adverse_witnesses(corrupted, status, tmp_path):
    node = witness_inputs(tmp_path, corrupted=corrupted); control = Control()
    result = agent_host.AgentHost().execute(node, request(node), control)["value"]
    assert result["receipt"]["status"] == status
    assert result["fresh_process"] is True
    assert result["receipt"]["runtime"]["python"]
    assert result["execution_authorized"] is result["physics_validated"] is False
    assert len(control.calls) == 1


def test_malformed_census_is_retained_refusal_and_not_arithmetic_acceptance(tmp_path):
    node = witness_inputs(tmp_path)
    census = tmp_path / "census.json"; value = read_json(census); value["records"].pop(); atomic_json(census, value)
    node["inputs"][2] = pin(census, "census")
    result = agent_host.AgentHost().execute(node, request(node), Control())["value"]
    assert result["receipt"]["status"] == "refused"
    assert result["receipt"]["arithmetic_verified"] is False


def test_unlisted_checker_or_unbounded_tolerance_refuses_before_dispatch(tmp_path):
    node = witness_inputs(tmp_path); control = Control()
    node["parameters"]["rtol"] = "2"
    with pytest.raises(agent_host.HostFailure, match="arithmetic tolerance"):
        agent_host.AgentHost().execute(node, request(node), control)
    assert not control.calls
    node["parameters"]["rtol"] = "0"; node["inputs"].pop()
    with pytest.raises(agent_host.HostFailure, match="explicitly hash-bound"):
        agent_host.AgentHost().execute(node, request(node), control)


def test_graph_reuses_completed_effect_and_bounded_repair_produces_fresh_receipt(tmp_path, monkeypatch):
    node = witness_inputs(tmp_path, corrupted=True)
    spec = {"schema_version": 1, "graph_id": "arithmetic-repair",
            "budget": {"max_nodes": 2, "max_calls": 3, "max_output_tokens": 0,
                       "max_wall_seconds": 30, "max_reworks": 1}, "nodes": [node]}
    root = tmp_path / "graph"; agent_graph.create(root, spec)
    adapter = agent_host.AgentHost(); count = []
    original = adapter._witness_process
    def counted(*args): count.append(True); return original(*args)
    monkeypatch.setattr(adapter, "_witness_process", counted)
    first = agent_graph.execute(root, adapter)
    assert first["complete"] and first["usage"]["calls"] == len(count) == 1
    assert agent_graph.execute(root, adapter)["usage"]["calls"] == len(count) == 1
    retained = read_json(root / first["nodes"][node["id"]]["result"]["path"])
    assert retained["result"]["value"]["receipt"]["status"] == "mismatch"
    repaired = deepcopy(spec)
    data, _ = fixture(); (tmp_path / "claim-repaired.json").write_bytes(raw(numerical_witness.derive(raw(data))))
    repaired["nodes"][0]["inputs"][1] = pin(tmp_path / "claim-repaired.json", "claim")
    agent_graph.revise(root, repaired, reason="explicit corrected arithmetic claim, same supplied population")
    second = agent_graph.execute(root, adapter)
    assert second["complete"] and second["usage"]["calls"] == len(count) == 2
    successor = read_json(root / second["nodes"][node["id"]]["result"]["path"])
    assert successor["result"]["value"]["receipt"]["status"] == "verified"
    assert agent_graph.execute(root, adapter)["usage"]["calls"] == len(count) == 2
    assert len(list((root / "calls").glob("*.json"))) == 2


def test_graph_resume_catches_embedded_prerequisite_drift(tmp_path):
    node = grounded_inputs(tmp_path)
    spec = {"schema_version": 1, "graph_id": "grounded-source",
            "budget": {"max_nodes": 1, "max_calls": 2, "max_output_tokens": 0,
                       "max_wall_seconds": 30, "max_reworks": 0}, "nodes": [node]}
    root = tmp_path / "graph"; agent_graph.create(root, spec)
    adapter = agent_host.AgentHost(); assert agent_graph.execute(root, adapter)["complete"]
    (tmp_path / "input.txt").write_text("changed after completed advice")
    with pytest.raises(agent_graph.GraphError, match="artifact changed"):
        agent_graph.execute(root, adapter)
    assert agent_graph.status(root)["usage"]["calls"] == 1


def test_source_pinned_model_inventory_is_an_actual_allowlisted_host_operation(tmp_path):
    from test_model_inputs import card
    raw = card(); source = tmp_path / "model.slha"; source.write_bytes(raw)
    manifest = tmp_path / "complete.json"; atomic_json(manifest, model_inputs.make_manifest(raw))
    node = tool("model-inputs", {"slha_input": "slha", "completeness_input": "completeness"},
                [pin(source, "slha"), pin(manifest, "completeness")])
    result = agent_host.AgentHost().execute(node, request(node), Control())
    assert result["value"]["kind"] == "model_input_preflight"
    assert result["value"]["decays"][0]["channel_completeness"] == "unresolved_completeness_unknown"
    assert result["execution_authorized"] is result["physics_validated"] is False
    node["inputs"].pop(); control = Control()
    with pytest.raises(agent_host.HostFailure, match="explicitly hash-bound"):
        agent_host.AgentHost().execute(node, request(node), control)
    assert control.calls == []


def test_tool_output_bound_and_model_blind_role_boundary_are_enforced(tmp_path):
    from test_model_inputs import card
    raw = card(); source = tmp_path / "model.slha"; source.write_bytes(raw)
    manifest = tmp_path / "complete.json"; atomic_json(manifest, model_inputs.make_manifest(raw))
    node = tool("model-inputs", {"slha_input": "slha", "completeness_input": "completeness"},
                [pin(source, "slha"), pin(manifest, "completeness")])
    with pytest.raises(agent_host.HostFailure, match="response exceeds"):
        agent_host.AgentHost(max_response_bytes=128).execute(node, request(node), Control())
    node["role"] = "critic"; control = Control()
    with pytest.raises(agent_host.HostFailure, match="blinded review role"):
        agent_host.AgentHost().execute(node, request(node), control)
    assert not control.calls
