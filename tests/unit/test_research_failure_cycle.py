"""Canonical failure-to-successor entry controls; no fits or model calls."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

from ravel.workflow import execution, failed_stage_review as failed, physics_review
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow import research_cycle as cycle
from test_research_cycle import (write, contract, propose, experiment, run_one,
                                 review_math, actual_revision_graph, report_request)


def existing_failure(base, *, with_resource=True):
    """Explicit synthetic ledger fixture, never a native/model authority."""
    root = base / "retained-failed-run"
    (root / "inputs").mkdir(parents=True)
    (root / "outputs").mkdir()
    (root / "inputs/source.py").write_text("# own synthetic fixture; not executed\n")
    policy = {"schema_version": 1,
        "actors": {"proposer": "fixture-worker", "executor": "fixture-worker",
            "physics_critic": "fixture-critic", "skeptical_verifier": "fixture-skeptic",
            "physics_decider": "fixture-decider"}, "allowed_changed_paths": [],
        "allowed_stages": ["science"], "max_redos": 0,
        "required_checks": [{"id": "custody", "kind": "integrity"}],
        "claim_scopes": {"fixture": {"checks": ["custody"], "actions": ["delivery", "reuse"]}}}
    atomic_json(root / physics_review.POLICY, policy)
    inputs = ["inputs/source.py", physics_review.POLICY]
    spec = {"command": [sys.executable, "inputs/source.py"], "cwd": str(root),
        "inputs": inputs, "outputs": ["outputs"], "parents": {},
        "input_snapshot": execution.snapshot(root, inputs), "runtime": execution.runtime_context()}
    if with_resource: spec["operation_resources"] = {"schema_version": 1, "kind": "solver", "generated_events": 0, "solver_evaluations": 1, "max_seconds": 30}
    spec["fingerprint"] = execution.digest(spec)
    record = execution.begin_attempt(root, "science", spec, "logs/worker.log")
    result = write(root / "outputs/result.json", {"status": "unresolved", "fatal": None,
        "custody_refusal": None, "physics_validated": False, "scope": "Own unresolved engineering witness"})
    raw = write(root / "outputs/raw.json", {"failure": "Own bounded method witness", "score": .01})
    (root / "logs/worker.log").write_text("Synthetic ledger failure, no native/model process\n")
    assert execution.finish_attempt(root, record, 2, "exit-2") == 2
    request = {"schema_version": 1, "stage_receipt": {k: cycle._pin(root / record["attempt_record"])[k] for k in ("path", "sha256")},
        "failure_kind": "scientific_unresolved", "result": {k: result[k] for k in ("path", "sha256")},
        "evidence": [{**{k: result[k] for k in ("path", "sha256")}, "location": "$.status"}],
        "required_returned_outputs": ["outputs/result.json", "outputs/raw.json"]}
    document = failed.intake(request, base_dir=root)
    document_pin = write(base / "failure-intake.json", document)
    reports = []
    for actor, role in (("fixture-critic", "critic"), ("fixture-skeptic", "verifier")):
        report = write(base / (role + "-source-report.json"), {"actor": actor,
            "subject": result["sha256"], "critique": "Design a fresh discriminating study; retain the failed result."})
        reports.append({"actor_id": actor, "report": {k: report[k] for k in ("path", "sha256")},
            "actor_pointer": "/actor", "subject": {k: result[k] for k in ("path", "sha256")}, "subject_pointer": "/subject"})
    index = write(base / "diagnostic-index.json", {"pins": [r["report"] for r in reports] + [{k: result[k] for k in ("path", "sha256")} ]})
    feedback = failed.historical_feedback(document, {k: index[k] for k in ("path", "sha256")}, *reports, base_dir=root)
    feedback_pin = write(base / "historical-feedback.json", feedback)
    return root, document_pin, feedback_pin


def connect(base, root):
    prior, document, feedback = existing_failure(base)
    result = cycle.import_failed_stage(root, "failed-parent", document, premise_ids=["pairing"],
        predictions={h: None for h in ("independent", "grouped", "unknown")},
        historical_cost={"calls": 0, "output_tokens": 0, "wall_seconds": 30, "native_attempts": 1})
    assert result["experiments"][0]["observation"]["result_category"] == "scientific_unresolved"
    cycle.diagnostic_feedback(root, "failed-parent", feedback, allow_control=True)
    return prior, document, feedback


def test_canonical_failed_parent_real_host_successor_worker_roles_report(tmp_path):
    root = tmp_path / "cycle"
    cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    prior, _, _ = connect(tmp_path, root)
    before = {str(p): execution.file_hash(p) for p in prior.rglob("*") if p.is_file()}
    e = experiment(tmp_path, "paired", grouped=True, parent="failed-parent")
    graph, result = actual_revision_graph(tmp_path, root, "failed-parent", e)
    assert result["complete"] and result["usage"]["calls"] == 1
    cycle.adopt_revision(root, graph_root=graph, node_id="improve")
    successor = run_one(tmp_path, root, e, designed=True)
    review_math(successor, root, "paired")
    assert cycle.status(root)["connected_task_complete"]
    request = report_request(tmp_path, root, successor)
    request["artifact_request"]["basis"][0]["path"] = "context-request.json"
    request["artifact_request"]["tools"]["study"]["path"] = str(successor.relative_to(tmp_path) / "outputs/attempt-1/result.json")
    report = cycle.synthesize(root, request, base_dir=tmp_path)
    negative = report["all_evidence_including_negative_and_reopened"][0]
    assert negative["observation"]["execution_status"] == "failed"
    assert negative["adjudication"] is None and negative["diagnostic_feedback"] is not None
    assert report["resource_ledger"][0]["ceiling"]["native_attempts"] == 1
    assert {str(p): execution.file_hash(p) for p in prior.rglob("*") if p.is_file()} == before
    assert not report["benefit_measured"] and not report["physics_validated"]


def test_failure_diagnosis_never_satisfies_ordinary_acceptance_or_old_retry(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    connect(tmp_path, root)
    for function in (cycle.run_experiment, cycle.observe, cycle.adjudicate):
        with pytest.raises(ValueError): function(root, "failed-parent")
    with pytest.raises(ValueError): cycle.prepare_experiment(root, "failed-parent", tmp_path / "retry")
    _, state = cycle._load(root)
    with pytest.raises(ValueError, match="never grants"):
        cycle._current_evidence(state, state["experiments"][0], accepted=True)
    assert cycle.status(root)["experiments"][0]["historically_accepted"] is False


def test_historical_report_drift_refuses_new_design_selection(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    connect(tmp_path, root)
    cycle.design(root, experiment(tmp_path, "paired", grouped=True, parent="failed-parent"))
    assert cycle.select(root)["selected"] == "paired"
    (tmp_path / "critic-source-report.json").write_text('{"changed":true}\n')
    with pytest.raises(ValueError): cycle.select(root)


def test_failed_prediction_support_and_historical_resource_reset_refused(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    _, document, _ = existing_failure(tmp_path)
    for predictions, cost in [({"grouped": "supported"}, {"calls": 0, "output_tokens": 0, "wall_seconds": 30, "native_attempts": 1}),
                              ({"grouped": None}, {"calls": 0, "output_tokens": 0, "wall_seconds": 30, "native_attempts": 0})]:
        with pytest.raises(ValueError):
            cycle.import_failed_stage(root, "failed-parent", document, premise_ids=[], predictions=predictions, historical_cost=cost)
    assert cycle._load(root)[1]["resource_ledger"] == []


def test_source_supplied_successor_preserves_no_model_provenance(tmp_path):
    root = tmp_path / "cycle"; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    connect(tmp_path, root)
    feedback = cycle.feedback_packet(root, "failed-parent")
    e = experiment(tmp_path, "paired", grouped=True, parent="failed-parent")
    proposal = write(tmp_path / "reviewed-source-proposal.json", {"kind": "research_revision", "parent_experiment": "failed-parent",
        "feedback_sha256": feedback["sha256"], "reason": "Own source implementation; no model transport claimed.", "hypotheses": [], "experiment": e})
    state = cycle.adopt_source_revision(root, proposal, description="Source-only implementation review is not an observed model call.")
    assert state["graphs"] == [] and state["revisions"][-1]["old_votes_carried"] == []
    assert state["revisions"][-1]["origin"]["actual_model_calls"] == 0
    assert state["experiments"][-1]["adjudication"] is None
    assert cycle.select(root)["selected"] == "paired"
