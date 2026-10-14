"""Publicly portable controls; synthetic values are not native measurements."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from ravel.workflow import agent_graph
from ravel.workflow.execution import digest

HERE = Path(__file__).resolve().parent

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

if (HERE / "scientific_context.py").exists():
    sc = _load("ravel.workflow.scientific_context", HERE / "scientific_context.py")
    host = _load("ravel.workflow._portable_context_host", HERE / "agent_host.py")
else:
    from ravel.workflow import scientific_context as sc, agent_host as host

def pin(path):
    return {"path": str(path.absolute()), "sha256": sc.analysis_sources.digest(path)}

def write(path, value):
    path.write_text(json.dumps(value, allow_nan=False) + "\n")
    return pin(path)

def request(base):
    source = base / "api.py"
    source.write_text("def requested_api(data):\n    owners = [data]\n    return owners\n")
    return {"schema_version": 1, "task_id": "synthetic-api-control", "task": "Read the requested API and deliver both independent fixed-point records.",
        "source_capsules": [], "api_documents": [{"id": "api", "pin": pin(source), "language": "python", "role": "api", "version": "Own synthetic API fixture; not native", "dependencies": []}],
        "queries": [{"id": "api-definition", "symbol": "requested_api", "mode": "definition", "documents": ["api"], "required": True}],
        "requested_quantities": [{"id": "two-records", "artifact": "records", "pointer": "/rows", "check": {"kind": "record-census", "id_field": "point", "expected_ids": ["0", "1"], "finite_fields": ["value"]}, "meaning": "Complete distinct supplied fixed-point census; no actual execution claim"}],
        "compatibility_groups": [{"id": "current", "artifacts": ["records"], "carryover": False, "basis": "Current attempt must deliver its own synthetic records."}],
        "max_source_bytes": 128000, "max_context_bytes": 16000, "max_steps": 3}

def attempt(outputs=None, identity="a1", **overrides):
    return {"id": identity, "outputs": outputs or {}, "code_status": "success", "actor_complete": True,
        "question": "Which source component prevents delivery of the second requested quantity?",
        "next_experiment": {"hypothesis": "The API call construction omitted the requested record.", "change": "Repair only that construction.", "measurement": "Check the complete two-record census.", "if_supported": "Prepare a separately admitted run.", "if_not_supported": "Use the observed mismatch to revise the API hypothesis."}, **overrides}

def result(base, name="result.json"):
    return write(base / name, {"rows": [{"point": "0", "value": 1.25}, {"point": "1", "value": 2.5}]})

def independent(base):
    r = request(base)
    r["requested_quantities"] = [{"id": key, "artifact": key, "pointer": "/value", "check": {"kind": "finite"}, "meaning": "Independent synthetic quantity"} for key in ("A", "B")]
    r["compatibility_groups"] = [{"id": key, "artifacts": [key], "carryover": True, "basis": "Explicitly declared independent quantities with unchanged source/input basis; no inferred physics composition."} for key in ("A", "B")]
    return r

def test_named_definition_and_owners_are_preserved(tmp_path):
    c = sc.compile_context(request(tmp_path), tmp_path)
    assert c["context_complete"] and "owners = [data]" in c["context_entries"][0]["text"]
    assert not c["quantity_completion"] and not c["execution_authorized"]

def test_python_call_retains_enclosing_execution_block(tmp_path):
    r = request(tmp_path); p = tmp_path / "call.py"
    p.write_text("def run():\n    owners = ['Constrain', 'GlobalObservables']\n    cmdlist = list(owners)\n    return requested_api(cmdlist)\n")
    r["api_documents"][0].update(pin=pin(p), role="example")
    r["queries"][0]["mode"] = "occurrence"
    c = sc.compile_context(r, tmp_path)
    assert "owners =" in c["context_entries"][0]["text"] and "cmdlist =" in c["context_entries"][0]["text"]
    assert c["context_entries"][0]["extraction"] == "python-enclosing-execution-block"

def test_successful_code_does_not_complete_absent_outputs(tmp_path):
    c = sc.apply_step(sc.compile_context(request(tmp_path), tmp_path), attempt(), tmp_path)
    assert not c["quantity_completion"] and c["steps"][0]["actor_complete_reported"]
    assert c["steps"][0]["status"] == "revise" and c["next_experiment"]["measurement"]

@pytest.mark.parametrize("fault", ["missing", "duplicate", "foreign", "bool", "empty"])
def test_complete_record_denominator_not_exit_status_controls_completion(tmp_path, fault):
    c = sc.compile_context(request(tmp_path), tmp_path)
    rows = [{"point": "0", "value": 1.25}, {"point": "1", "value": 2.5}]
    if fault == "missing": rows.pop()
    elif fault == "duplicate": rows[1] = deepcopy(rows[0])
    elif fault == "foreign": rows[1]["point"] = "2"
    elif fault == "bool": rows[1]["value"] = True
    else: rows = []
    p = write(tmp_path / "bad.json", {"rows": rows})
    assert not sc.apply_step(c, attempt({"records": p}), tmp_path)["quantity_completion"]

def test_nonfinite_supplied_output_refuses_without_completion(tmp_path):
    c = sc.compile_context(request(tmp_path), tmp_path); p = tmp_path / "bad.json"
    p.write_text('{"rows":[{"point":"0","value":NaN}]}')
    with pytest.raises(ValueError, match="non-finite"):
        sc.apply_step(c, attempt({"records": pin(p)}), tmp_path)

def test_last_bounded_attempt_can_succeed_and_restart_keeps_failed_question(tmp_path):
    r = request(tmp_path); r["max_steps"] = 2
    c = sc.compile_context(r, tmp_path); p = tmp_path / "state.json"; sc.persist_context(p, c)
    first = sc.apply_step(c, attempt(), tmp_path)
    sc.persist_context(p, first, expected_parent_sha256=c["context_sha256"])
    final = sc.apply_step(sc.read_json(p), attempt({"records": result(tmp_path)}, identity="a2"), tmp_path)
    sc.persist_context(p, final, expected_parent_sha256=first["context_sha256"])
    assert final["quantity_completion"] and final["steps"][0]["question"]
    with pytest.raises(ValueError, match="attempt limit"):
        sc.apply_step(final, attempt(identity="a3"), tmp_path)
    with pytest.raises(ValueError, match="unchanged parent"):
        sc.persist_context(p, final, expected_parent_sha256=c["context_sha256"])

def test_independent_carryover_and_invalid_new_output_replacement(tmp_path):
    c = sc.compile_context(independent(tmp_path), tmp_path)
    a = write(tmp_path / "a.json", {"value": 3}); b = write(tmp_path / "b.json", {"value": 7})
    first = sc.apply_step(c, attempt({"A": a}), tmp_path)
    second = sc.apply_step(first, attempt({"B": b}, identity="a2"), tmp_path)
    assert second["quantity_completion"] and second["effective_outputs"][0]["source_step"] == "a1"
    bad = write(tmp_path / "bad-a.json", {"value": True})
    third = sc.apply_step(second, attempt({"A": bad}, identity="a3"), tmp_path)
    assert not third["quantity_completion"] and third["steps"][:2] == second["steps"]

def test_no_carry_group_requires_current_outputs(tmp_path):
    r = independent(tmp_path); r["compatibility_groups"][0]["carryover"] = False
    c = sc.compile_context(r, tmp_path)
    first = sc.apply_step(c, attempt({"A": write(tmp_path / "a.json", {"value": 3})}), tmp_path)
    second = sc.apply_step(first, attempt({"B": write(tmp_path / "b.json", {"value": 7})}, identity="a2"), tmp_path)
    assert not second["quantity_completion"]

def test_coupled_group_requires_all_members_in_one_update(tmp_path):
    r = independent(tmp_path); r["compatibility_groups"] = [{"id": "paired", "artifacts": ["A", "B"], "carryover": True, "basis": "Explicit matched-pair update; no old/new arms."}]
    c = sc.compile_context(r, tmp_path)
    a = write(tmp_path / "a.json", {"value": 3}); b = write(tmp_path / "b.json", {"value": 7})
    with pytest.raises(ValueError, match="all artifacts together"):
        sc.apply_step(c, attempt({"A": a}), tmp_path)
    first = sc.apply_step(c, attempt({"A": a, "B": b}), tmp_path)
    with pytest.raises(ValueError, match="all artifacts together"):
        sc.apply_step(first, attempt({"B": b}, identity="a2"), tmp_path)

def test_changed_retained_output_refuses_carryover(tmp_path):
    c = sc.compile_context(independent(tmp_path), tmp_path)
    a = write(tmp_path / "a.json", {"value": 3})
    first = sc.apply_step(c, attempt({"A": a}), tmp_path)
    (tmp_path / "a.json").write_text('{}')
    with pytest.raises(ValueError, match="input bytes changed"):
        sc.apply_step(first, attempt(identity="a2"), tmp_path)

def test_late_file_lookup_and_whole_span_budget_omission(tmp_path):
    r = request(tmp_path); docs = []
    for i in range(60):
        p = tmp_path / (str(i) + ".py"); p.write_text(f"def target{i}():\n    return {i}\n")
        docs.append({"id": str(i), "pin": pin(p), "language": "python", "role": "api", "version": "Synthetic", "dependencies": []})
    r["api_documents"] = docs; r["queries"] = [{"id": "late", "symbol": "target59", "mode": "definition", "documents": [], "required": True}]
    c = sc.compile_context(r, tmp_path)
    assert c["context_complete"] and "target59" in c["context_entries"][0]["text"]
    r["queries"][0]["symbol"] = "absent"
    assert not sc.compile_context(r, tmp_path)["context_complete"]
    r["queries"][0]["symbol"] = "target59"; (tmp_path / "59.py").write_text("def target59():\n" + "    # retained context\n" * 100 + "    return 59\n")
    r["api_documents"][-1]["pin"] = pin(tmp_path / "59.py"); r["max_context_bytes"] = 1024
    limited = sc.compile_context(r, tmp_path)
    assert limited["omissions"] and not limited["context_complete"] and limited["context_bytes"] <= 1024

class Control:
    def __init__(self): self.calls = []
    def cancelled(self): return False
    def check_cancelled(self): pass
    def call(self, label, kind, request, function, output_tokens=0): self.calls.append(label); return function()

def host_request(paths, role="proposer"):
    inputs = [{"id": identity, **pin(path)} for identity, path in paths.items()]
    node = {"id": "ctx", "kind": "tool", "role": role, "depends_on": [], "inputs": inputs, "packet": None,
        "action": "scientific-context", "parameters": {"request_input": "request"}, "max_attempts": 1}
    req = {"schema_version": 1, "graph_id": "portable-context", "graph_revision": "a" * 64, "node_id": "ctx", "generation": 1,
        "node_sha256": digest(node), "request_id": "b" * 64, "input_artifacts": deepcopy(inputs), "packet": None, "dependencies": []}
    return node, req

def test_host_exposes_context_only_after_all_actual_source_inputs(tmp_path):
    r = request(tmp_path); p = tmp_path / "request.json"; write(p, r)
    n, req = host_request({"request": p}); ctl = Control()
    with pytest.raises(host.HostFailure, match="unbound source"):
        host.AgentHost().execute(n, req, ctl)
    assert not ctl.calls
    n, req = host_request({"request": p, "source": tmp_path / "api.py"}); ctl = Control()
    assert host.AgentHost().execute(n, req, ctl)["value"] == sc.compile_context(r, tmp_path)
    assert ctl.calls == ["scientific-context"]

@pytest.mark.parametrize("role", ["critic", "verifier"])
def test_blind_roles_do_not_get_constructor_context(tmp_path, role):
    p = tmp_path / "request.json"; write(p, request(tmp_path))
    n, req = host_request({"request": p, "source": tmp_path / "api.py"}, role)
    with pytest.raises(host.HostFailure): host.AgentHost().execute(n, req, Control())

@pytest.mark.parametrize("dependency", ["analysis_sources", "state_io"])
def test_actual_graph_charges_once_reuses_and_checks_real_dependencies(tmp_path, monkeypatch, dependency):
    p = tmp_path / "request.json"; write(p, request(tmp_path)); n, _ = host_request({"request": p, "source": tmp_path / "api.py"})
    specification = {"schema_version": 1, "graph_id": "portable-context", "budget": {"max_nodes": 1, "max_calls": 1,
        "max_output_tokens": 0, "max_wall_seconds": 30, "max_reworks": 0}, "nodes": [n]}
    root = tmp_path / "graph"; agent_graph.create(root, specification); adapter = host.AgentHost()
    first = agent_graph.execute(root, adapter, workers=1)
    assert first["complete"] and first["usage"]["calls"] == 1
    assert agent_graph.execute(root, adapter, workers=1)["usage"]["calls"] == 1
    module = getattr(sc, dependency); path = tmp_path / "different.py"; path.write_bytes(Path(module.__file__).read_bytes() + b"\n# source-identity adverse control\n")
    monkeypatch.setattr(module, "__file__", str(path))
    retained = agent_graph.status(root)
    with pytest.raises(agent_graph.GraphError, match="^completed generation source/request/host differs; explicit rework required$"): agent_graph.execute(root, adapter, workers=1)
    # The refusal precedes any reservation: no call is charged and the completed generation is untouched.
    assert agent_graph.status(root) == retained and retained["usage"]["calls"] == 1
