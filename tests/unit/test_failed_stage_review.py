"""Failed-stage admission guards with ordinary engineering receipts; no fits/models."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from ravel.workflow import execution, failed_stage_review as failed, physics_review, review_context, agent_graph, launch_authorization
from ravel.workflow.state_io import atomic_json


def pin(path):
    return {"path": str(path), "sha256": execution.file_hash(path)}


@pytest.fixture
def case(tmp_path):
    root = tmp_path / "run"
    (root / "inputs").mkdir(parents=True)
    (root / "outputs").mkdir()
    source = root / "inputs/source.py"
    source.write_text("# harmless fixture, never executed\nvalue = 1\n")
    policy = {"schema_version": 1,
        "actors": {"proposer": "worker", "executor": "worker", "physics_critic": "critic",
                   "skeptical_verifier": "skeptic", "physics_decider": "decider"},
        "allowed_changed_paths": [], "allowed_stages": ["science"], "max_redos": 0,
        "required_checks": [{"id": "custody", "kind": "integrity"}],
        "claim_scopes": {"diagnostic": {"checks": ["custody"], "actions": ["delivery", "reuse"]}}}
    atomic_json(root / physics_review.POLICY, policy)
    inputs = ["inputs/source.py", physics_review.POLICY]
    spec = {"command": [sys.executable, "inputs/source.py"], "cwd": str(root), "inputs": inputs,
            "outputs": ["outputs"], "parents": {},
            "input_snapshot": execution.snapshot(root, inputs), "runtime": execution.runtime_context()}
    spec["fingerprint"] = execution.digest(spec)
    record = execution.begin_attempt(root, "science", spec, "logs/worker.log")
    atomic_json(root / "outputs/result.json", {"status": "unresolved", "physics_validated": False,
        "fatal": None, "custody_refusal": None, "returned": 4, "machine_passed": 3})
    atomic_json(root / "outputs/raw.json", {"score": 0.004, "failure": "bounded line search"})
    (root / "logs/worker.log").write_text("engineering fixture retained failure\n")
    assert execution.finish_attempt(root, record, 2, "exit-2") == 2
    request = {"schema_version": 1, "stage_receipt": pin(root / record["attempt_record"]),
        "failure_kind": "scientific_unresolved", "result": pin(root / "outputs/result.json"),
        "evidence": [{**pin(root / "outputs/result.json"), "location": "$.returned"},
                     {**pin(root / "outputs/raw.json"), "location": "$.failure"}],
        "required_returned_outputs": ["outputs/result.json", "outputs/raw.json"]}
    return root, record, request


def test_actual_failed_outcome_and_history_retained(case):
    root, record, request = case
    before = {str(p): execution.file_hash(p) for p in root.rglob("*") if p.is_file()}
    doc = failed.intake(request, base_dir=root)
    assert doc["stage_status"] == "failed" and doc["exit_code"] == 2
    assert doc["result_status"] == "unresolved" and doc["prior_reviews_carried"] == []
    assert not any(doc[key] for key in ("execution_authorized", "scientific_acceptance",
        "delivery_authorized", "reuse_authorized", "correction_authorized", "automatic_redo"))
    assert {str(p): execution.file_hash(p) for p in root.rglob("*") if p.is_file()} == before
    assert failed.verify(doc, base_dir=root) == doc
    assert "receipt_sha256" not in record and not (root / physics_review.REGISTRATION).exists()
    with pytest.raises(ValueError, match="successful"):
        physics_review._receipt(root, record["attempt_record"])


@pytest.mark.parametrize("kind", ["missing", "empty"])
def test_missing_returned_evidence_is_infrastructure_not_science(case, kind):
    root, _, request = case
    path = root / "outputs/raw.json"
    if kind == "missing":
        path.unlink()
    else:
        path.write_text("")
    request["evidence"] = request["evidence"][:1]
    with pytest.raises(ValueError, match="infrastructure failure"):
        failed.intake(request, base_dir=root)
    request["failure_kind"] = "infrastructure_failure"
    doc = failed.intake(request, base_dir=root)
    assert doc["failure_kind"] == "infrastructure_failure"
    assert doc["returned_output_obligations"][1]["status"] == kind
    assert not doc["scientific_acceptance"]


def test_infrastructure_can_retain_malformed_raw_output_without_scientific_admission(case):
    root, _, request = case
    (root / "outputs/raw.json").write_text('{"truncated":')
    request["evidence"][1] = {**pin(root / "outputs/raw.json"), "location": "whole malformed raw witness"}
    with pytest.raises(ValueError, match="malformed required numerical output"):
        failed.intake(request, base_dir=root)
    request["failure_kind"] = "infrastructure_failure"
    doc = failed.intake(request, base_dir=root)
    assert any(row["sha256"] == request["evidence"][1]["sha256"]
               for row in failed._files(doc["returned_outputs"]))
    assert doc["scientific_acceptance"] is False


@pytest.mark.parametrize("mutation", ["status", "validated", "fatal"])
def test_false_success_or_infrastructure_failure_cannot_be_unresolved_science(case, mutation):
    root, _, request = case
    path = root / "outputs/result.json"
    value = json.loads(path.read_text())
    if mutation == "status": value["status"] = "passed"
    if mutation == "validated": value["physics_validated"] = True
    if mutation == "fatal": value["fatal"] = "missing native dependency"
    atomic_json(path, value)
    request["result"] = pin(path)
    request["evidence"][0] = {**pin(path), "location": "$.returned"}
    with pytest.raises(ValueError):
        failed.intake(request, base_dir=root)


def test_successful_negative_hypothesis_is_not_a_failed_execution(case):
    root, record, request = case
    request["failure_kind"] = "negative_hypothesis"
    with pytest.raises(ValueError, match="ordinary review"):
        failed.intake(request, base_dir=root)
    request["failure_kind"] = "scientific_unresolved"
    record["status"] = "succeeded"; record["exit_code"] = 0
    atomic_json(root / record["attempt_record"], record)
    request["stage_receipt"] = pin(root / record["attempt_record"])
    with pytest.raises(ValueError, match="FAILED"):
        failed.intake(request, base_dir=root)


@pytest.mark.parametrize("kind", ["source", "output", "receipt", "ledger", "new_member"])
def test_stale_premise_cannot_seed_revision(case, kind):
    root, record, request = case
    doc = failed.intake(request, base_dir=root)
    if kind == "source": (root / "inputs/source.py").write_text("changed source\n")
    if kind == "output": (root / "outputs/raw.json").write_text('{"different":true}\n')
    if kind == "receipt": (root / record["attempt_record"]).write_text("{}\n")
    if kind == "ledger":
        p = root / execution.STATE_NAME; value = json.loads(p.read_text()); value["changed"] = True; atomic_json(p, value)
    if kind == "new_member": atomic_json(root / "outputs/unexpected.json", {"unexpected": True})
    with pytest.raises(ValueError): failed.verify(doc, base_dir=root)


def test_ending_mutation_refuses_before_return(case, monkeypatch):
    root, _, request = case
    old = failed._observe
    def mutate(*args):
        value = old(*args)
        (root / "outputs/raw.json").write_text('{"changed":true}\n')
        return value
    monkeypatch.setattr(failed, "_observe", mutate)
    with pytest.raises(ValueError, match="final census"):
        failed.intake(request, base_dir=root)


def test_role_packet_uses_existing_reader_and_projects_producer_status(case, tmp_path):
    root, _, request = case
    doc = failed.intake(request, base_dir=root)
    critic = failed.create_context(doc, "critic", tmp_path / "critic", base_dir=root)
    verifier = failed.create_context(doc, "verifier", tmp_path / "verifier", base_dir=root)
    assert critic["sha256"] != verifier["sha256"] and critic["allowed_claim_scopes"] == {}
    raw = review_context.read_artifact(tmp_path / "critic", "premise", expected_manifest_sha256=critic["sha256"])
    assert json.loads(raw) == doc
    result = json.loads(review_context.read_artifact(tmp_path / "critic", "e0000",
        expected_manifest_sha256=critic["sha256"]))
    assert "status" not in result and result["machine_passed"] == 3
    with pytest.raises(ValueError, match="immutable failed run"):
        failed.create_context(doc, "critic", root / "intrusion", base_dir=root)
    with pytest.raises(FileExistsError):
        failed.create_context(doc, "critic", tmp_path / "critic", base_dir=root)


def test_dependencies_include_actual_source_and_all_returned_files(case):
    root, record, request = case
    paths = {row["path"] for row in failed.inputs(request, base_dir=root)}
    assert {str(root / name) for name in ["inputs/source.py", physics_review.POLICY,
        "outputs/raw.json", "outputs/result.json", execution.STATE_NAME, record["attempt_record"]]} <= paths


def test_real_incomplete_graph_is_not_genuine_diagnostic_feedback(case, tmp_path):
    root, _, request = case
    doc = failed.intake(request, base_dir=root)
    packet = failed.create_context(doc, "critic", tmp_path / "critic", base_dir=root)
    graph_root = tmp_path / "graph"
    spec = {"schema_version": 1, "graph_id": "failure", "budget": {"max_nodes": 1,
        "max_calls": 0, "max_output_tokens": 0, "max_wall_seconds": 10, "max_reworks": 0},
        "nodes": [{"id": "critic", "kind": "model", "role": "critic", "depends_on": [],
            "inputs": [], "packet": {"path": str(tmp_path / "critic"), "manifest_sha256": packet["sha256"]},
            "action": "model", "parameters": {}, "max_attempts": 1}]}
    agent_graph.create(graph_root, spec)
    binding = {"graph_root": str(graph_root), "node_id": "critic",
               "context_manifest_sha256": packet["sha256"], "actor_id": "critic"}
    with pytest.raises(ValueError, match="not complete"):
        failed.graph_feedback(doc, binding, binding, base_dir=root, allow_control=True)


def test_declared_actor_forgery_refused_without_model_calls(case):
    root, _, request = case
    doc = failed.intake(request, base_dir=root)
    binding = {"graph_root": "/never-accessed", "node_id": "critic",
               "context_manifest_sha256": "0" * 64, "actor_id": "worker"}
    with pytest.raises(ValueError, match="actor differs"):
        failed.graph_feedback(doc, binding, binding, base_dir=root, allow_control=True)


def synthetic_retained_launch(root, record):
    """Explicitly fabricated ENGINEERING fixture, never a real launch witness."""
    metadata = {"schema_version": 1, "kind": "solver", "generated_events": 0,
                "solver_evaluations": 10, "max_seconds": 1}
    record["operation_resources"] = metadata
    committed = {k: record[k] for k in ("command", "cwd", "inputs", "outputs",
        "input_snapshot", "parents", "runtime", "operation_resources")}
    record["fingerprint"] = execution.digest(committed)
    auth = launch_authorization._append(root, {"event": "authorized", "command": record["command"],
        "context": {"stage": "science"}, "authorization": {"stage_binding": {**committed, "fingerprint": record["fingerprint"]}}})
    launched = launch_authorization._append(root, {"event": "launched", "pid": 123456789,
        "authorization_sequence": auth["sequence"], "authorization_sha256": auth["sha256"]})
    record["child_pid"] = launched["pid"]
    record["authorization_receipt"] = {"sequence": launched["sequence"], "sha256": launched["sha256"]}
    execution._update(root, "science", record)


@pytest.mark.parametrize("mutation", ["remove_metadata", "change_metadata", "add_metadata", "fingerprint"])
def test_self_rehashed_record_cannot_replace_retained_launch_metadata(case, mutation):
    root, record, request = case
    synthetic_retained_launch(root, record)
    request["stage_receipt"] = pin(root / record["attempt_record"])
    doc = failed.intake(request, base_dir=root)
    assert doc["recorded_stage_metadata"]["operation_resources"]["solver_evaluations"] == 10
    if mutation == "remove_metadata": record.pop("operation_resources")
    if mutation == "change_metadata": record["operation_resources"]["solver_evaluations"] = 11
    if mutation == "add_metadata": record["helper_declaration"] = {"not": "an admitted helper"}
    committed = {k: record[k] for k in ("command", "cwd", "inputs", "outputs", "input_snapshot", "parents", "runtime")}
    committed.update({k: record[k] for k in ("output_policy", "helper_declaration", "operation_resources") if k in record})
    record["fingerprint"] = "0" * 64 if mutation == "fingerprint" else execution.digest(committed)
    execution._update(root, "science", record)
    request["stage_receipt"] = pin(root / record["attempt_record"])
    with pytest.raises(ValueError): failed.intake(request, base_dir=root)


def test_ledger_only_control_never_becomes_genuine_scientific_feedback(case):
    root, _, request = case
    doc = failed.intake(request, base_dir=root)
    binding = {"graph_root": "/never-accessed", "node_id": "critic",
               "context_manifest_sha256": "0" * 64, "actor_id": "critic"}
    with pytest.raises(ValueError, match="retained actual launch"):
        failed.graph_feedback(doc, binding, binding, base_dir=root)


def test_graph_feedback_control_retains_both_actual_role_outputs_without_votes(case, tmp_path, monkeypatch):
    root, _, request = case
    doc = failed.intake(request, base_dir=root)
    bindings = []
    nodes = []
    for role, actor in (("critic", "critic"), ("verifier", "skeptic")):
        packet = failed.create_context(doc, role, tmp_path / role, base_dir=root)
        bindings.append({"graph_root": str(tmp_path), "node_id": role,
                         "context_manifest_sha256": packet["sha256"], "actor_id": actor})
        nodes.append({"id": role, "packet": {"path": str(tmp_path / role)}})
    # Model transport is intentionally STUBBED at its separately tested boundary.
    # The control label must survive, and these are never live scientific reviews.
    def receipt(root, node_id, **kwargs):
        binding = next(b for b in bindings if b["node_id"] == node_id)
        return {"role": node_id, "request_id": node_id, "context_manifest_sha256": binding["context_manifest_sha256"],
            "execution_observation": "control_only", "context_transport_separated": True,
            "public_value": {"hypothesis": "line search explanation", "observed_status": "unresolved"},
            "execution_authorized": False, "physics_validated": False}
    monkeypatch.setattr(agent_graph, "model_receipt", receipt)
    monkeypatch.setattr(agent_graph, "_load", lambda root: ({"nodes": nodes}, {}))
    feedback = failed.graph_feedback(doc, *bindings, base_dir=root, allow_control=True)
    assert feedback["control_only"] and len(feedback["reviews"]) == 2
    assert feedback["stage_status"] == "failed" and not feedback["scientific_acceptance"]
    assert not feedback["execution_authorized"] and not feedback["automatic_redo"]
    assert feedback["prior_reviews_carried"] == []
    assert feedback["next_action"] == "new_prospective_experiment_design"


def historical_fixture(case, tmp_path):
    root, record, request = case
    synthetic_retained_launch(root, record)
    request["stage_receipt"] = pin(root / record["attempt_record"])
    doc = failed.intake(request, base_dir=root)
    subject = {k: doc["evidence"][0][k] for k in ("path", "sha256")}
    bindings = []
    for role, actor in (("critic", "critic"), ("verifier", "skeptic")):
        report = tmp_path / (role + '-historical.json')
        atomic_json(report, {"actor_id": actor, "parent_evidence": subject,
            "status": "a supplied favorable judgment is never an acceptance vote"})
        bindings.append({"actor_id": actor, "report": pin(report), "actor_pointer": "/actor_id",
                         "subject": subject, "subject_pointer": "/parent_evidence"})
    index = tmp_path / 'historical-index.json'
    atomic_json(index, {"pins": [subject, *[b["report"] for b in bindings]]})
    return root, doc, pin(index), bindings


def test_attributed_historical_reports_do_not_fabricate_graph_transport(case, tmp_path):
    root, doc, index, bindings = historical_fixture(case, tmp_path)
    feedback = failed.historical_feedback(doc, index, *bindings, base_dir=root)
    assert feedback["feedback_source"] == "retained_attributed_reports"
    assert not feedback["fresh_role_transport_observed"] and feedback["new_model_calls"] == 0
    assert all(r["graph_model_receipt"] is None and not r["fresh_context_observed"] for r in feedback["reviews"])
    assert not feedback["scientific_acceptance"] and feedback["prior_reviews_carried"] == []
    assert failed.verify_feedback(doc, feedback, base_dir=root) == feedback


@pytest.mark.parametrize("mutation", ["actor", "subject", "index", "report_bytes"])
def test_historical_role_subject_and_index_grafts_refused(case, tmp_path, mutation):
    root, doc, index, bindings = historical_fixture(case, tmp_path)
    if mutation == "actor": bindings[0]["actor_id"] = "worker"
    if mutation == "subject": bindings[0]["subject_pointer"] = "/status"
    if mutation == "index":
        atomic_json(Path(index["path"]), {"pins": [bindings[0]["subject"], bindings[0]["report"]]})
        index = pin(Path(index["path"]))
    if mutation == "report_bytes": Path(bindings[0]["report"]["path"]).write_text('{}')
    with pytest.raises(ValueError): failed.historical_feedback(doc, index, *bindings, base_dir=root)


def test_prospective_source_intervention_binds_actual_failed_premise_without_authority(case, tmp_path):
    root, doc, index, bindings = historical_fixture(case, tmp_path)
    feedback = failed.historical_feedback(doc, index, *bindings, base_dir=root)
    proposal = tmp_path / 'prospective.json'
    candidate = tmp_path / 'candidate.py'
    atomic_json(proposal, {"intervention": "single revised direction", "scientific_calls": 0})
    candidate.write_text('# future source only, not executed\n')
    result = failed.bind_successor(doc, feedback, pin(proposal), [pin(candidate)], base_dir=root)
    assert result["parent_failure_sha256"] == doc["sha256"] and result["parent_stage_status"] == "failed"
    assert result["diagnostic_feedback_sha256"] == feedback["sha256"] and result["parent_result"] == doc["result"]
    assert result["new_scientific_plan_required"] and result["new_execution_approval_required"]
    assert not result["fresh_role_transport_observed"] and not result["execution_authorized"]
    assert not result["scientific_acceptance"] and result["prior_reviews_carried"] == []
    candidate_pin = pin(candidate); candidate.write_text('# candidate source drift\n')
    with pytest.raises(ValueError): failed.bind_successor(doc, feedback, pin(proposal), [candidate_pin], base_dir=root)


def test_historical_feedback_stale_report_and_resealed_authority_forgery_refused(case, tmp_path):
    root, doc, index, bindings = historical_fixture(case, tmp_path)
    feedback = failed.historical_feedback(doc, index, *bindings, base_dir=root)
    forged = deepcopy(feedback); forged["scientific_acceptance"] = True
    forged["sha256"] = execution.digest({k: v for k, v in forged.items() if k != 'sha256'})
    with pytest.raises(ValueError): failed.verify_feedback(doc, forged, base_dir=root)
    Path(bindings[1]["report"]["path"]).write_text('{}')
    with pytest.raises(ValueError): failed.verify_feedback(doc, feedback, base_dir=root)
