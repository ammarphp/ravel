"""Root-only proposed genuine ordinary lifecycle control; unexecuted by author.

Two tiny synthetic quantity records use the existing supervised Python worker.
No ROOT reader, remote site, Snakemake process, simulation or physics claim.
"""

from method_decision_fixture import admit_method
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from ravel.workflow import science, site_workflow
from ravel.workflow.state_io import atomic_json, read_json
from ravel.physics import root_stream
from site_ordinary_fixture import contract, event, policy
from root_stream_fixture import population


def pin(path):
    path = Path(path).absolute()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def test_genuine_schema2_supervised_ordinary_delivery_and_wms_reuse(tmp_path):
    atomic_json(tmp_path / "contract.json", contract())
    (tmp_path / "records.jsonl").write_text("\n".join(json.dumps(row) for row in
        [event("a", [[.5]], 2), event("b", [[2]], -1)]) + "\n")
    review = policy()
    review.update(max_redos=0, allowed_stages=["science"], allowed_changed_paths=[])
    spec = {"schema_version": 2, "mode": "quantities", "source": "Root-admitted synthetic software lifecycle control",
        "assumptions": ["Two synthetic records establish software custody, not physics"],
        "max_seconds": 20, "max_attempts": 1, "approval_mode": "scripted_yes",
        "task": {"contract": "contract.json", "records": "records.jsonl"},
        "review_policy": {"schema_version": 1, "policy": review,
            "correction_contract": {"task_fields": [], "input_slots": []}}}
    atomic_json(tmp_path / "spec.json", spec)
    rd = tmp_path / "study"
    science.plan(rd, tmp_path / "spec.json"); admit_method(rd)
    prepared = science.verify_plan(rd, approved=False)
    assert prepared["schema_version"] == 2 and "output_directory" not in prepared
    assert len(prepared["stages"]) == 1 and len(prepared["stages"][0]["outputs"]) == 1
    folder = rd / prepared["stages"][0]["outputs"][0]

    atomic_json(tmp_path / "audit.json", {"synthetic_software_control": True})
    proof = pin(tmp_path / "audit.json")
    atomic_json(tmp_path / "blind-policy.json", {"schema_version": 1,
        "policy": "exclude_signal_region_data_from_model_and_analysis", "review_source": proof,
        "original_domain": None})
    request = {"schema_version": 1, "site_id": "root-software-only", "python": pin(sys.executable),
        "tasks": [{"id": "analyze", "rundir": str(rd), "plan": pin(rd / science.PLAN),
            "owner": {"kind": "ordinary"}, "depends_on": []}],
        "audit": {"prompts": [proof], "model_build": "none-synthetic-software-control",
            "timestamps": ["2026-10-09T00:00:00Z"], "token_accounting": proof,
            "environment": proof, "tracked_skill_sources": [proof],
            "blinding_policy": pin(tmp_path / "blind-policy.json")},
        "wms": {"engine": "snakemake", "version": "9.27.0", "cores": 1, "retries": 0}}
    exported = site_workflow.export(request, tmp_path, tmp_path / "export")
    path, sha = exported["manifest"]["path"], exported["manifest"]["sha256"]
    assert exported["execution_authorized"] is False
    assert site_workflow.verify(path, sha)["tasks"][0]["output_directory"] == str(folder.relative_to(rd))
    assert not (rd / "execution_attempt.json").exists()
    science.approve(rd, "Root-admitted synthetic software control only", scripted=True)
    marker = site_workflow.run_step(path, "analyze", sha)
    assert marker["status"] == "delivered" and marker["scientific_acceptance_inferred"] is False
    receipt = root_stream.ordinary_delivery(rd, expected_output=folder)
    assert receipt["outputs"] == marker["outputs"] and receipt["scientific_acceptance_inferred"] is False
    assert receipt["result"]["quantities"]["values"]["nominal"] == [2, -1]
    assert science.execution.load_execution(rd)["stages"]["science"]["status"] == "succeeded"
    original_attempt = read_json(rd / "execution_attempt.json")
    assert site_workflow.verify(path, sha)["tasks"][0]["id"] == "analyze"

    with pytest.raises(ValueError, match="spent WMS step"):
        site_workflow.run_step(path, "analyze", sha)
    assert read_json(rd / "execution_attempt.json") == original_attempt

    # Original result remains intact, but a missing or stale actual attempt
    # cannot be replaced by the otherwise valid completion marker.
    token = rd / "logs/science-attempts/00000001.json"
    old = token.read_bytes()
    token.unlink()
    with pytest.raises((OSError, ValueError, KeyError)):
        site_workflow.verify(path, sha)
    token.write_bytes(old)
    assert site_workflow.verify(path, sha)["tasks"][0]["id"] == "analyze"
    changed = deepcopy(original_attempt)
    changed["budget_seconds"] = 21
    atomic_json(token, changed)
    with pytest.raises((OSError, ValueError, KeyError)):
        site_workflow.verify(path, sha)
    token.write_bytes(old)
    assert site_workflow.verify(path, sha)["tasks"][0]["id"] == "analyze"

    original_result = (folder / "result.json").read_bytes()
    (folder / "result.json").write_bytes(b"{}\n")
    with pytest.raises((OSError, ValueError, KeyError)):
        site_workflow.verify(path, sha)
    (folder / "result.json").write_bytes(original_result)
    assert site_workflow.verify(path, sha)["tasks"][0]["id"] == "analyze"



def test_actual_root_stream_schema2_plan_export_and_missing_plan_private_context(tmp_path):
    # Actual plan/verification/export APIs, no plan or authority doubles. The
    # declared ROOT members and interpreter are inert source fixtures only;
    # nothing is approved or executed and no ROOT reader is opened.
    source = tmp_path / "source"
    source.mkdir()
    _, analysis, _, task, proof = population(source)
    review = policy()
    review.update(max_redos=0, allowed_stages=["science"], allowed_changed_paths=[],
        claim_scopes={root_stream.SCOPE: {"checks": ["integrity"], "actions": ["delivery"]}})
    spec = {"schema_version": 2, "mode": "root-stream", "source": "Synthetic source-only ROOT plan regression",
        "assumptions": ["No real ROOT reader or site runtime is used"], "max_seconds": 20,
        "max_attempts": 1, "approval_mode": "scripted_yes", "task": task,
        "review_policy": {"schema_version": 1, "policy": review,
            "correction_contract": {"task_fields": [], "input_slots": []}}}
    atomic_json(source / "spec.json", spec)
    rd = tmp_path / "study"
    science.plan(rd, source / "spec.json"); admit_method(rd)
    original = science.verify_plan(rd, approved=False)
    assert original["schema_version"] == 2 and "output_directory" not in original
    _, effective, destination = root_stream.ordinary_plan_destination(rd)
    assert effective["task"] == task and destination == original["stages"][0]["outputs"][0]
    atomic_json(source / "export-blind-policy.json", {"schema_version": 1,
        "policy": "exclude_signal_region_data_from_model_and_analysis", "review_source": proof,
        "original_domain": analysis["blinding"]["source"]})
    request = {"schema_version": 1, "site_id": "root-software-only", "python": pin(sys.executable),
        "tasks": [{"id": "analyze", "rundir": str(rd), "plan": pin(rd / science.PLAN),
            "owner": {"kind": "ordinary"}, "depends_on": []}],
        "audit": {"prompts": [proof], "model_build": "none-source-only-regression",
            "timestamps": ["2026-10-09T00:00:00Z"], "token_accounting": proof,
            "environment": proof, "tracked_skill_sources": [proof],
            "blinding_policy": pin(source / "export-blind-policy.json")},
        "wms": {"engine": "snakemake", "version": "9.27.0", "cores": 1, "retries": 0}}
    exported = site_workflow.export(request, source, tmp_path / "export")
    assert site_workflow.verify(exported["manifest"]["path"], exported["manifest"]["sha256"])["tasks"][0]["output_directory"] == destination
    assert not (rd / "execution_attempt.json").exists()
    ledger = rd / destination / "root-stream/native/completed-intervals.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(b'{"sample":"data","member":"data_file","start":0,"stop":2}\n{"sample":"data","member":"data_file","start":2,"stop":4}\n')
    from ravel.workflow.agent_host import AgentHost, HostFailure
    for missing in (False, True):
        if missing:
            (rd / science.PLAN).rename(rd / (science.PLAN + ".retained"))
        with pytest.raises(ValueError):
            root_stream.model_artifact_source(ledger, pin(ledger)["sha256"])
        with pytest.raises(HostFailure):
            AgentHost()._context({"packet": None, "role": "lead"}, {"request_id": "synthetic"},
                {"ledger": (ledger, pin(ledger)["sha256"])})
