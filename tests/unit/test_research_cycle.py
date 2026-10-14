"""Real-entry engineering controls; supplied math is not scientific efficacy.

The connected case calls actual Host/Graph/context and ordinary v2 plan/approve/
supervisor/worker/review APIs. Reviewers are explicit synthetic test actors, not
independent models or physicists. No generator, native library or model runs.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from ravel.workflow import agent_host, agent_graph, physics_review, review_context, science
from ravel.workflow import research_cycle as cycle, scientific_context as sc
from ravel.workflow.state_io import atomic_json, read_json


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if type(value) is str: path.write_text(value)
    else: atomic_json(path, value)
    return cycle._pin(path)


def quantities_contract():
    return {"schema_version": 1, "axes": [{"name": "x", "unit": "1"}],
        "bins": [{"id": "one", "low": [0.0], "high": [1.0]}], "weight_names": ["nominal"],
        "input_weight_unit": "1", "representation": "integrated", "normalization": {"kind": "absolute", "scale": 1.0, "unit": "1"}}


def source_context(base):
    source = write(base / "math.py", "def group_variance(weights):\n    return sum(weights)**2\n")
    return {"schema_version": 1, "task_id": "signed-group-question", "task": "Deliver the paired two-record conditional variance and preserve all negative results.",
        "source_capsules": [], "api_documents": [{"id": "math", "pin": {k: source[k] for k in ("path", "sha256")},
            "language": "python", "role": "api", "version": "Explicit own synthetic math control, not native", "dependencies": []}],
        "queries": [{"id": "group-math", "symbol": "group_variance", "mode": "definition", "documents": ["math"], "required": True}],
        "requested_quantities": [{"id": "conditional-variance", "artifact": "measurement", "pointer": "/quantities/covariance",
            "check": {"kind": "exact", "value": [[1.0]]}, "meaning": "Two supplied signed contributions 2 and -1 in one explicit group; no physical uncertainty qualification."}],
        "compatibility_groups": [{"id": "current-candidate", "artifacts": ["measurement"], "carryover": False,
            "basis": "Every new candidate must supply its own complete two-record result."}],
        "max_source_bytes": 128000, "max_context_bytes": 16000, "max_steps": 6}


def contract(base):
    return {"schema_version": 1, "id": "supplied-group-investigation", "question": "Can pairing signed supplied subevents change conditional variance while retaining the sum?",
        "scope": "Synthetic engineering loop; neither independent model reasoning nor physics efficacy.",
        "context_request": write(base / "context-request.json", source_context(base)),
        "premises": [{"id": "pairing", "statement": "The actual initial record population has separate groups.", "basis": []}],
        "budget": {"calls": 20, "output_tokens": 0, "wall_seconds": 600, "native_attempts": 6},
        "max_experiments": 6, "exploration_every": 2, "required_experiments": ["paired"]}


def hypotheses():
    return [{"id": "independent", "statement": "The separate-group result can persist for the paired design.", "stream": "citation_led",
             "premise_ids": [], "source_basis": [], "parents": []},
            {"id": "grouped", "statement": "Explicit pairing changes the square from 2²+(-1)² to (2-1)².", "stream": "speculative",
             "premise_ids": [], "source_basis": [], "parents": []},
            {"id": "unknown", "statement": "Another supplied-record semantic may alter the result; propose a discriminating check.", "stream": "speculative",
             "premise_ids": [], "source_basis": [], "parents": []}]


def propose(base, root):
    rows = hypotheses()
    return cycle.propose(root, rows, origin={"kind": "supplied_source", "pin": write(base / "hypotheses.json", rows),
        "description": "Own engineering source proposals, not actual model-generated hypotheses."})


def specification(base, identity, grouped, malformed=False):
    b = base / identity; b.mkdir()
    write(b / "contract.json", quantities_contract())
    records = [{"event_id": "a", "group_id": "shared" if grouped else "a", "shard_id": "toy", "weights": {"nominal": 2}, "fills": [[.5]]},
               {"event_id": "b", "group_id": "shared" if grouped else "b", "shard_id": "toy", "weights": {"nominal": -1}, "fills": [[.5]]}]
    write(b / "records.jsonl", "{\"event_id\":\"bad\"}\n" if malformed else "\n".join(json.dumps(x) for x in records) + "\n")
    policy = {"schema_version": 1, "actors": {"proposer": "fixture-worker", "executor": "fixture-worker",
        "physics_critic": "fixture-critic", "skeptical_verifier": "fixture-skeptic", "physics_decider": "fixture-decider"},
        "max_redos": 0, "allowed_changed_paths": [], "allowed_stages": ["science"],
        "required_checks": [{"id": "integrity", "kind": "integrity"}, {"id": "math", "kind": "scientific"}],
        "claim_scopes": {"supplied_math_diagnostic": {"checks": ["integrity", "math"], "actions": ["delivery", "reuse"]}}}
    return write(b / "study.json", {"schema_version": 2, "mode": "quantities", "source": "Explicit synthetic signed-group arithmetic control.",
        "assumptions": ["The two record weights/fills/group identities are supplied; this is not native acquisition or physics validation."],
        "max_seconds": 30, "max_attempts": 1, "approval_mode": "scripted_yes", "task": {"contract": "contract.json", "records": "records.jsonl"},
        "review_policy": {"schema_version": 1, "policy": policy, "correction_contract": {"task_fields": [], "input_slots": []}}})


def experiment(base, identity, *, grouped, parent=None, premise_ids=None, malformed=False):
    return {"id": identity, "question": "Measure the complete two-record supplied conditional variance.",
        "premise_ids": [] if premise_ids is None else premise_ids, "parent": parent,
        "change": "Use the explicitly paired population." if grouped else "First measure the retained separate-group population.",
        "study": specification(base, identity, grouped, malformed), "cost": {"calls": 0, "output_tokens": 0, "wall_seconds": 30, "native_attempts": 1},
        "predictions": {"independent": "independent", "grouped": "shared" if grouped else "independent", "unknown": None},
        "observable": {"pointer": "/quantities/covariance/0/0", "outcomes": {"independent": 5.0, "shared": 1.0}},
        "context_outputs": {"measurement": "outputs/attempt-1/result.json"},
        "acceptance_scope": "supplied_math_diagnostic", "exploratory": grouped}


def actual_context_graph(root, base):
    request = read_json(base / "context-request.json")
    inputs = [{"id": "request", **{k: cycle._pin(base / "context-request.json")[k] for k in ("path", "sha256")}},
              {"id": "api", **{k: cycle._pin(base / "math.py")[k] for k in ("path", "sha256")}}]
    node = {"id": "context", "kind": "tool", "role": "proposer", "depends_on": [], "inputs": inputs,
        "packet": None, "action": "scientific-context", "parameters": {"request_input": "request"}, "max_attempts": 1}
    spec = {"schema_version": 1, "graph_id": "actual-context", "budget": {"max_nodes": 1, "max_calls": 1,
        "max_output_tokens": 0, "max_wall_seconds": 30, "max_reworks": 0}, "nodes": [node]}
    path = base / "context-graph"
    state = cycle.execute_graph(root, path, spec, agent_host.AgentHost())
    assert state["complete"] and state["usage"]["calls"] == 1
    assert cycle._graph_result(path, "context")["value"]["value"] == sc.compile_context(request, base)
    again = cycle.execute_graph(root, path, spec, agent_host.AgentHost())
    assert again["usage"] == state["usage"]


def review_math(rd, root, identity):
    record = science.execution.load_execution(rd)["stages"]["science"]
    values = read_json(rd / "outputs/attempt-1/result.json")["quantities"]
    expected = 1.0 if identity == "paired" else 5.0
    assert values["values"]["nominal"] == [1.0] and values["covariance"] == [[expected]]
    write(rd / "inputs/cycle-checks.json", {"schema_version": 1, "checks": [
        {"id": key, "status": "pass", "evidence": [{"path": "outputs/attempt-1/result.json", "location": "$.quantities"}],
         "attempt_ids": [record["attempt_id"]]} for key in ("integrity", "math")]})
    physics_review.open_cycle(rd, effective_settings=science.review_effective_settings(rd),
        stage_receipts=[record["attempt_record"]], check_results="inputs/cycle-checks.json")
    for role, actor, packet_role in (("physics_critic", "fixture-critic", "critic"),
                                   ("skeptical_verifier", "fixture-skeptic", "verifier"),
                                   ("physics_decider", "fixture-decider", "synthesizer")):
        packet = root / (identity + "-" + packet_role)
        manifest = review_context.create(rd, packet_role, packet)
        for artifact in manifest["artifacts"]:
            review_context.read_artifact(packet, artifact["id"], expected_manifest_sha256=manifest["sha256"])
        physics_review.submit_review(rd, role=role, actor_id=actor, verdict="accept", claim_scope="supplied_math_diagnostic",
            summary="Synthetic separate test actor checks the complete arithmetic population; no scientific expert or independent model claim.")
    return cycle.adjudicate(root, identity)


def run_one(base, root, e, *, designed=False):
    if not designed: cycle.design(root, e)
    rd = base / (e["id"] + "-run")
    cycle.prepare_experiment(root, e["id"], rd)
    from method_decision_fixture import admit_method
    admit_method(rd)
    with pytest.raises((ValueError, OSError)): cycle.run_experiment(root, e["id"])
    assert not (rd / "execution_attempt.json").exists()
    science.approve(rd, "User-authorized pure engineering control only, not model/native/physics approval.", scripted=True)
    assert cycle.run_experiment(root, e["id"]) == 0
    cycle.observe(root, e["id"])
    return rd


def actual_revision_graph(base, root, parent, challenger, *, wrong_feedback=False):
    feedback = cycle.feedback_packet(root, parent)
    proposal = {"kind": "research_revision", "parent_experiment": parent, "feedback_sha256": "0" * 64 if wrong_feedback else feedback["sha256"],
        "reason": "Retain the nondiscriminating first outcome and construct the paired population to distinguish the rival predictions.",
        "hypotheses": [], "experiment": challenger}
    path = base / (challenger["id"] + "-proposal.json")
    source = write(path, proposal)
    spec_path = Path(challenger["study"]["path"])
    dependencies = science.task_inputs(read_json(spec_path), spec_path.parent)
    pins = [source, feedback, challenger["study"], *[cycle._pin(p) for p in dependencies]]
    unique = {p["path"]: p for p in pins}
    inputs = [{"id": "pin-" + str(i), **{k: p[k] for k in ("path", "sha256")}} for i, p in enumerate(unique.values())]
    indices = {p["path"]: p["id"] for p in inputs}
    node = {"id": "improve", "kind": "tool", "role": "improver", "depends_on": [], "inputs": inputs,
        "packet": None, "action": "research-revision", "parameters": {"proposal_input": indices[source["path"]],
            "feedback_input": indices[feedback["path"]]}, "max_attempts": 1}
    specification = {"schema_version": 1, "graph_id": "actual-constructive-revision",
        "budget": {"max_nodes": 1, "max_calls": 1, "max_output_tokens": 0, "max_wall_seconds": 30, "max_reworks": 0}, "nodes": [node]}
    graph = base / (challenger["id"] + "-graph")
    result = cycle.execute_graph(root, graph, specification, agent_host.AgentHost())
    return graph, result


def report_request(base, root, rd):
    _, state = cycle._load(root)
    context_path = root / "synthesis-context" / (state["context"]["context_sha256"] + ".json")
    write(context_path, state["context"])
    result = cycle._pin(rd / "outputs/attempt-1/result.json")
    fields = [{"field": "variance", "type": "number", "source": {"kind": "direct", "tool_id": "study", "pointer": "/quantities/covariance/0/0"}}]
    context_pin = cycle._pin(context_path)
    context_pin["path"] = str(context_path.relative_to(base))
    return {"schema_version": 1, "title": "Synthetic supplied-group investigation",
        "artifact_request": {"schema_version": 1, "contract": {"source_scope": "Conditional supplied arithmetic only.", "tool_fields": fields,
            "interpretation_fields": [], "unresolved_semantics": [], "max_artifact_bytes": 2048},
            "basis": [cycle._pin(base / "context-request.json")], "tools": {"study": result}, "interpretation": {}},
        "context": context_pin, "facts": [{"id": "conditional", "selector": {"kind": "direct", "pointer": "/variance"},
            "quantity_id": "conditional-variance", "context_selector": {"kind": "direct", "pointer": "/0/0"},
            "label": "Conditional group variance", "unit": "1", "scope": "synthetic_given_groups", "population": "Both supplied signed records",
            "limitations": ["No native event acquisition, model benefit or physics qualification."]}],
        "sections": [{"id": "complete", "kind": "table", "caption": "Complete supplied conditional quantity.", "columns": ["Variance"],
            "rows": [{"id": "paired", "facts": ["conditional"]}]}], "interpretation": ["The initial separate-group control did not discriminate the rival hypotheses; the paired follow-up did, conditional on supplied group semantics."]}


def test_connected_two_iteration_real_host_studies_roles_and_synthesis(tmp_path):
    root = tmp_path / "cycle"
    cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    actual_context_graph(root, tmp_path)
    propose(tmp_path, root)
    first = run_one(tmp_path, root, experiment(tmp_path, "separate", grouped=False))
    before = cycle._load(root)[1]
    assert not before["context"]["quantity_completion"]
    assert before["experiments"][0]["observation"]["prediction_comparison"] == {"independent": "matches", "grouped": "matches", "unknown": "unknown"}
    review_math(first, root, "separate")
    challenger = experiment(tmp_path, "paired", grouped=True, parent="separate")
    graph, graph_result = actual_revision_graph(tmp_path, root, "separate", challenger)
    assert graph_result["complete"] and graph_result["usage"]["calls"] == 1
    amended = cycle.adopt_revision(root, graph_root=graph, node_id="improve")
    assert amended["revisions"][-1]["old_votes_carried"] == []
    assert amended["experiments"][-1]["adjudication"] is None
    second = run_one(tmp_path, root, challenger, designed=True)
    with pytest.raises(ValueError): cycle.synthesize(root, report_request(tmp_path, root, second), base_dir=tmp_path)
    after = review_math(second, root, "paired")
    assert after["experiments"][1]["observation"]["prediction_comparison"] == {"independent": "differs", "grouped": "matches", "unknown": "unknown"}
    assert cycle.status(root)["connected_task_complete"]
    request = report_request(tmp_path, root, second)
    request["artifact_request"]["basis"][0]["path"] = "context-request.json"
    request["artifact_request"]["tools"]["study"]["path"] = str(second.relative_to(tmp_path) / "outputs/attempt-1/result.json")
    synthesis = cycle.synthesize(root, request, base_dir=tmp_path)
    assert len(synthesis["all_evidence_including_negative_and_reopened"]) == 2
    assert "| 1.0 |" in synthesis["report"]["report_text"]
    assert synthesis["actual_graph_usage"][0]["usage"]["calls"] == 1
    assert not synthesis["benefit_measured"] and not synthesis["physics_validated"]
    science.run(second, resume=True)
    assert len(list((second / "logs/science-attempts").glob("*.json"))) == 1


def test_speculation_needs_no_source_consensus_and_resources_never_reset(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    assert sum(x["stream"] == "speculative" and not x["source_basis"] for x in cycle._load(root)[1]["hypotheses"]) == 2
    first = experiment(tmp_path, "separate", grouped=False); cycle.design(root, first)
    second = experiment(tmp_path, "paired", grouped=True); cycle.design(root, second)
    assert cycle.select(root)["selected"] == "paired"
    cycle.prepare_experiment(root, "paired", tmp_path / "run")
    assert cycle.select(root)["selected"] == "separate"
    with pytest.raises(ValueError): cycle.prepare_experiment(root, "paired", tmp_path / "rerun")
    assert len(cycle._load(root)[1]["resource_ledger"]) == 1


def test_changed_premise_reopens_descendants_without_deleting_measurements(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    e = experiment(tmp_path, "separate", grouped=False, premise_ids=["pairing"]); cycle.design(root, e)
    child = experiment(tmp_path, "paired", grouped=True, parent="separate"); cycle.design(root, child)
    state = cycle.revise_premise(root, "pairing", "Use an explicitly paired source population.", basis=[], reason="A constructive follow-up changes the grouping premise.")
    assert {x["id"] for x in state["experiments"] if "applicability_reopened" in x} == {"separate", "paired"}
    assert cycle.select(root)["selected"] is None
    assert len(list((root / "history").glob("*.json"))) == state["revision"] + 1


def test_source_change_refuses_current_context_and_immutable_history_tamper(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    (tmp_path / "math.py").write_text("def different():\n    pass\n")
    with pytest.raises(ValueError): cycle.status(root)


def test_end_to_end_coordination_deadline_retained_before_any_new_graph(tmp_path, monkeypatch):
    root = tmp_path / "cycle"; c = contract(tmp_path); c["budget"]["wall_seconds"] = 60
    cycle.create(root, c, base_dir=tmp_path, evaluation_harness=True)
    monkeypatch.setattr(cycle.time, "time", lambda: 1000.0)
    actual_context_graph(root, tmp_path)
    monkeypatch.setattr(cycle.time, "time", lambda: 1040.0)
    _, state = cycle._load(root)
    spec = read_json(tmp_path / "context-graph" / agent_graph.SPEC)
    with pytest.raises(cycle.OperationalBoundaryError): cycle.execute_graph(root, tmp_path / "new-graph", spec, agent_host.AgentHost())
    final = cycle._load(root)[1]
    assert final["timing"]["started_epoch"] == 1000.0 and final["timing"]["deadline_epoch"] == 1060.0
    assert final["operational_boundaries"][-1]["new_attempts"] == 0
    assert final["operational_boundaries"][-1]["scientific_result"] is None
    assert not (tmp_path / "new-graph").exists()


def phase_request(root):
    state = cycle._load(root)[1]
    return {"schema_version": 1, "budget": state["contract"]["budget"], "usage": cycle._usage(state),
        "checks": [{"id": "lifecycle", "cost": {"calls": 1, "output_tokens": 0, "wall_seconds": 10, "native_attempts": 0}}],
        "designs": [{"id": e["id"], "construction_cost": e["cost"], "check_ids": ["lifecycle"],
            "polish_cost": {"calls": 0, "output_tokens": 0, "wall_seconds": 0, "native_attempts": 0}} for e in state["experiments"]],
        "completed_check_ids": [], "retained_design_ids": [], "mandatory_check_ids": ["lifecycle"]}


def test_real_phase_reservation_cannot_be_bypassed_at_preparation(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    first = experiment(tmp_path, "separate", grouped=False)
    second = experiment(tmp_path, "paired", grouped=True, parent="separate")
    cycle.design(root, first); cycle.design(root, second)
    policy = phase_request(root)
    cycle.configure_phases(root, write(tmp_path / "phase.json", policy),
        check_contracts={"lifecycle": {"experiment_id": "separate", "required_check_ids": ["integrity", "math"], "purpose": "adapter_lifecycle"}},
        preconstruction_checks={"separate": [], "paired": ["lifecycle"]})
    assert cycle.select(root)["phase_allocation"]["check_reservation"]["calls"] == 1
    with pytest.raises(ValueError): cycle.prepare_experiment(root, "paired", tmp_path / "premature")
    assert not (tmp_path / "premature").exists()
    rd = run_one(tmp_path, root, first, designed=True)
    with pytest.raises(ValueError): cycle.record_check(root, "lifecycle")
    review_math(rd, root, "separate")
    cycle.record_check(root, "lifecycle")
    selected = cycle.select(root)
    assert selected["selected"] == "paired" and selected["phase_allocation"]["check_reservation"]["calls"] == 0
    assert selected["usage_ceiling"]["calls"] == 1
    cycle.prepare_experiment(root, "paired", tmp_path / "proper")
    with pytest.raises(ValueError): cycle.record_check(root, "lifecycle")
    # Optional source policy cannot override the persisted actual-check obligations.
    with pytest.raises(ValueError): cycle.select(root, allocation=policy)


def test_successful_unclassified_outcome_is_not_automatic_hypothesis_support(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    e = experiment(tmp_path, "separate", grouped=False)
    e["observable"]["outcomes"] = {"independent": 50.0, "shared": 10.0}
    rd = run_one(tmp_path, root, e)
    observation = cycle._load(root)[1]["experiments"][0]["observation"]
    assert observation["execution_status"] == "succeeded" and observation["measured"] == 5.0
    assert observation["result_category"] == "unresolved_measurement"
    assert set(observation["prediction_comparison"].values()) == {"unknown"}
    review_math(rd, root, "separate")
    assert not cycle.status(root)["connected_task_complete"]


def test_expired_campaign_continuation_debits_original_calls_and_preserves_deadline(tmp_path, monkeypatch):
    root = tmp_path / "cycle"; c = contract(tmp_path); c["budget"]["wall_seconds"] = 60
    cycle.create(root, c, base_dir=tmp_path, evaluation_harness=True)
    monkeypatch.setattr(cycle.time, "time", lambda: 1000.0)
    actual_context_graph(root, tmp_path)
    monkeypatch.setattr(cycle.time, "time", lambda: 1100.0)
    next_contract = deepcopy(c); next_contract["id"] = "explicit-follow-up"; next_contract["budget"]["wall_seconds"] = 120
    new = cycle.continue_campaign(root, tmp_path / "continuation", next_contract, reason="A separate prospective phase retains original operational incompletion.")
    assert new["timing"]["started_epoch"] is None
    assert cycle._usage(new)["calls"] == 1 and cycle._usage(new)["wall_seconds"] == 0
    assert new["resource_ledger"][0]["basis"]["original_elapsed_seconds"] == 100.0
    assert cycle._load(root)[1]["timing"]["deadline_epoch"] == 1060.0
    changed = deepcopy(next_contract); changed["budget"]["calls"] += 1
    with pytest.raises(ValueError): cycle.continue_campaign(root, tmp_path / "reset", changed, reason="Forbidden silent reset.")


def test_phase_policy_reserves_checks_after_actual_graph_tool_overhead(tmp_path):
    root = tmp_path / "cycle"; c = contract(tmp_path); c["budget"]["calls"] = 1
    cycle.create(root, c, base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    e = experiment(tmp_path, "separate", grouped=False); cycle.design(root, e)
    policy = phase_request(root)
    cycle.configure_phases(root, write(tmp_path / "phase.json", policy),
        check_contracts={"lifecycle": {"experiment_id": "separate", "required_check_ids": ["integrity", "math"], "purpose": "adapter_lifecycle"}},
        preconstruction_checks={"separate": []})
    assert cycle.select(root)["selected"] == "separate"
    actual_context_graph(root, tmp_path)
    selected = cycle.select(root)
    assert selected["usage_ceiling"]["calls"] == 1
    assert selected["phase_allocation"]["check_reservation_deficits"]["calls"] == 1
    assert selected["selected"] is None
    with pytest.raises(ValueError): cycle.prepare_experiment(root, "separate", tmp_path / "unaffordable")
    assert not (tmp_path / "unaffordable").exists()


def test_phase_policy_cannot_drop_original_check_or_edit_obligation(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    cycle.design(root, experiment(tmp_path, "separate", grouped=False))
    request = phase_request(root)
    check_contract = {"lifecycle": {"experiment_id": "separate", "required_check_ids": ["integrity", "math"], "purpose": "adapter_lifecycle"}}
    cycle.configure_phases(root, write(tmp_path / "phase.json", request), check_contracts=check_contract,
        preconstruction_checks={"separate": []})
    changed = deepcopy(request); changed["mandatory_check_ids"] = []
    with pytest.raises(ValueError): cycle.configure_phases(root, write(tmp_path / "relaxed.json", changed),
        check_contracts=check_contract, preconstruction_checks={"separate": []})
    changed = deepcopy(request); changed["checks"][0]["cost"]["calls"] = 0
    with pytest.raises(ValueError): cycle.configure_phases(root, write(tmp_path / "reduced.json", changed),
        check_contracts=check_contract, preconstruction_checks={"separate": []})


def test_actual_failed_worker_retains_unknown_predictions_and_no_scientific_support(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    e = experiment(tmp_path, "malformed", grouped=False, malformed=True)
    cycle.design(root, e); rd = tmp_path / "failed-run"
    cycle.prepare_experiment(root, e["id"], rd)
    from method_decision_fixture import admit_method
    admit_method(rd)
    science.approve(rd, "Pure malformed-input engineering control; no native/model scientific execution.", scripted=True)
    assert cycle.run_experiment(root, e["id"]) != 0
    state = cycle.observe(root, e["id"])
    observed = state["experiments"][0]["observation"]
    assert observed["execution_status"] == "failed" and observed["result"] is None
    assert observed["result_category"] == "execution_or_adapter_failure_unresolved"
    assert set(observed["prediction_comparison"].values()) == {"unknown"}
    assert not state["context"]["quantity_completion"] and not cycle.status(root)["connected_task_complete"]
    with pytest.raises(ValueError): cycle.feedback_packet(root, e["id"])
    assert len(list((rd / "logs/science-attempts").glob("*.json"))) == 1


def test_hypothesis_descendants_keep_changed_premise_dependency(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    rows = hypotheses(); rows[0]["premise_ids"] = ["pairing"]
    rows[1]["parents"] = ["independent"]
    cycle.propose(root, rows, origin={"kind": "supplied_source", "pin": write(tmp_path / "ideas.json", rows),
        "description": "Own conditional hypothesis lineage control."})
    before = cycle._load(root)[1]
    inherited = next(h for h in before["hypotheses"] if h["id"] == "grouped")
    assert inherited["premise_bindings"] == before["hypotheses"][0]["premise_bindings"]
    after = cycle.revise_premise(root, "pairing", "A changed source population is now requested.", basis=[], reason="Explicit premise change.")
    assert not cycle._fresh(after, inherited["premise_bindings"])


def test_scoped_executable_adaptation_is_a_new_proposal_not_carried_acceptance(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    source = write(tmp_path / "adapter.py", "def OLD(weights):\n    return sum(weights)**2\n")
    observation = write(tmp_path / "old-observation.json", {"scope": "Own supplied grouped arithmetic", "success": True})
    observation["path"] = "old-observation.json"
    catalog = {"schema_version": 1, "entries": [{"id": "paired", "summary": "Group signed contributions before conditional variance.",
        "domain": "supplied_arithmetic", "scope": "Two scalar signed weights only", "facets": {"grouping": "explicit", "population": "two"},
        "source": {k: source[k] for k in ("path", "sha256")}, "fragment": {"first_line": 1, "last_line": 2, "text": (tmp_path / "adapter.py").read_text()},
        "parameters": [{"id": "function", "token": "OLD", "kind": "identifier", "expected_occurrences": 1}],
        "observations": [{"id": "own", "status": "reported_success", "scope": "Source-author supplied control only", "artifact": observation}],
        "reopen_when": ["Population, group definition, dimensions or scientific uncertainty law changes"]}]}
    catalog_pin = write(tmp_path / "catalog.json", catalog)
    catalog_pin["path"] = "catalog.json"
    request = {"schema_version": 1, "catalog": catalog_pin, "top_k": 1, "max_context_bytes": 16000,
        "task": {"id": "new-population", "question": "Reuse group arithmetic in a larger supplied population.", "domain": "supplied_arithmetic",
            "scope": "Complete new population, not just constructor fragment", "facets": {"grouping": "explicit", "population": "three"},
            "source_obligations": [{"id": "population", "description": "Supply and check every new signed record."}]}}
    state = cycle.reuse_adaptation(root, write(tmp_path / "retrieve.json", request), entry_id="paired", bindings={"function": "NEW"})
    record = cycle._read(state["adaptations"][0], tmp_path)
    proposal = record["proposal"]
    assert "def NEW" in proposal["controlled_source"]
    assert proposal["scope_differences"] == [{"facet": "population", "origin": "two", "target": "three"}]
    assert proposal["old_votes_carried"] == [] and proposal["fresh_execution_and_full_scope_review_required"]
    assert not cycle.status(root)["connected_task_complete"]


def test_complete_worker_custody_without_model_heldout_answer_exposure(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    e = experiment(tmp_path, "separate", grouped=False)
    deps = [cycle._pin(p) for p in science.task_inputs(read_json(e["study"]["path"]), Path(e["study"]["path"]).parent)]
    hidden = next(p for p in deps if Path(p["path"]).name == "records.jsonl")
    classifications = {p["path"]: "withheld_evaluation" if p == hidden else "model_context" for p in deps}
    scoped = cycle.bind_input_exposure(e, classifications, tmp_path / "exposure", base_dir=tmp_path,
        reason="Own engineered heldout-content admission control, not actual OS blinding.")
    cycle.design(root, scoped)
    current = cycle._load(root)[1]["experiments"][0]
    assert current["input_pins"] == deps
    presented = [p for p in deps if p != hidden] + [scoped["input_exposure"]]
    cycle._model_input_admission(scoped, deps, presented, tmp_path)
    with pytest.raises(ValueError): cycle._model_input_admission(scoped, deps, deps + [scoped["input_exposure"]], tmp_path)
    clone = write(tmp_path / "hidden-clone.jsonl", Path(hidden["path"]).read_text())
    with pytest.raises(ValueError): cycle._model_input_admission(scoped, deps, presented + [clone], tmp_path)
    with pytest.raises(ValueError): cycle._model_input_admission(scoped, deps, presented[:-1], tmp_path)
    broken = deepcopy(classifications); broken.pop(hidden["path"])
    with pytest.raises(ValueError): cycle.bind_input_exposure(e, broken, tmp_path / "missing", base_dir=tmp_path, reason="Incomplete custody must refuse.")
