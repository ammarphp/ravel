"""Exact selected existing fixture functions; inert approval boundary in controls only."""
import sys
from pathlib import Path
from ravel.workflow import execution,physics_review as review,waypoint_evidence as waypoint
from ravel.workflow.state_io import atomic_json

def policy():
    return {"schema_version": 1,
        "actors": {"proposer": "worker", "executor": "worker", "physics_decider": "physicist", "skeptical_verifier": "skeptic", "physics_critic": "critic"},
        "max_redos": 2, "allowed_changed_paths": ["inputs/settings.cfg"], "allowed_stages": ["detector"],
        "required_checks": [{"id": "integrity", "kind": "integrity"}, {"id": "agreement", "kind": "scientific"}],
        "claim_scopes": {"diagnostic": {"checks": ["integrity"], "actions": ["delivery"]},
            "reproduction": {"checks": ["integrity", "agreement"], "actions": ["bulk", "delivery", "reuse"]}}}

def make_attempt(root, *, value=1, extra_inputs=()):
    # A deliberately small execution receipt avoids binding concurrently edited
    # development source files; execution's package-hashing tests live elsewhere.
    inputs = ["inputs/settings.cfg", "inputs/held-fixed.txt", *extra_inputs]
    spec = {"command": [sys.executable, "-c", "pass"], "cwd": str(root.resolve()),
        "inputs": inputs, "outputs": ["outputs/produced.json"], "input_snapshot": execution.snapshot(root, inputs),
        "parents": {}, "runtime": execution.runtime_context()}
    spec["fingerprint"] = execution.digest(spec)
    record = execution.begin_attempt(root, "detector", spec, "logs/detector.log")
    atomic_json(root / "outputs/produced.json", {"value": value})
    (root / "logs/detector.log").write_text(f"generated value {value}\n")
    assert execution.finish_attempt(root, record, 0) == 0
    return record

def check_packet(root, record, *, agreement="pass", integrity="pass"):
    atomic_json(root / "inputs/comparison.json", {"status": "pass" if agreement == "pass" else "fail",
        "summary": "Declared comparison", "diagnostics": {"residual": 0 if agreement == "pass" else .2}})
    manifest = waypoint.create(root, produced="outputs/produced.json", reference="inputs/reference.json",
        comparison="inputs/comparison.json", inputs=["inputs/settings.cfg"])
    atomic_json(root / waypoint.MANIFEST, manifest)
    atomic_json(root / "inputs/checkin2.json", {"sections": {"evidence_manifest": waypoint.MANIFEST}})
    atomic_json(root / "inputs/checks.json", {"schema_version": 1, "checks": [
        {"id": cid, "status": status, "evidence": [{"path": "outputs/produced.json", "location": "$.value"}],
         "attempt_ids": [record["attempt_id"]]} for cid, status in (("integrity", integrity), ("agreement", agreement))]})

def accept(root, *, scope="reproduction", closes=()):
    """Critic, skeptic and decider accept through bound responses; declared names are advice."""
    from bound_review import bound_accept
    return bound_accept(root, scope=scope, closes=list(closes))

def finding(name="F1", paths=None):
    return {"id": name, "summary": "The setting needs the declared correction",
        "evidence": [{"path": "outputs/produced.json", "location": "$.value"}],
        "check_ids": ["agreement"], "required_paths": ["inputs/settings.cfg"] if paths is None else paths,
        "required_stages": ["detector"]}

def reject(root, name="F1", paths=None):
    """A bound critic send-back with one located finding; the cycle then awaits a decider correction."""
    from bound_review import bound_review
    return bound_review(root, role="physics_critic", verdict="send_back",
        summary="Send back for a controlled correction", findings=[finding(name, paths)])

def correct(root):
    (root / "inputs/settings.cfg").write_text("efficiency=0.85\n")
    return review.authorize_correction(root, actor_id="physicist", changed_paths=["inputs/settings.cfg"],
        stages=["detector"], recheck_checks=["agreement"])


def late_finding_context(root):
    reg, events = review._read(root)
    view = review._view(reg, events)
    cycle = view["cycle"]
    old = next(pin for pin in cycle["snapshots"] if pin["path"] == "outputs/produced.json")
    fresh = root / "inputs/late-numerical-defect.json"
    atomic_json(fresh, {"engineering_adverse_control": True, "optimizer_calls": 0, "physics_validated": False})
    context = {"schema_version": 1, "kind": "post_acceptance_scientific_finding", "run_id": reg["run_id"],
        "cycle_id": cycle["cycle_id"], "cycle_sha256": cycle["sha256"], "claim_scope": "reproduction",
        "accepted_review_sha256": [event["sha256"] for event in view["reviews"]],
        "role": "physics_critic", "actor_id": "critic", "findings": [{"id": "late-stationarity",
        "summary": "New located engineering control contests a required numerical claim",
        "check_ids": ["agreement"],
        "accepted_evidence": [{"path": old["path"], "sha256": old["sha256"], "location": "$.value"}],
        "new_evidence": [{"path": "inputs/late-numerical-defect.json", "sha256": execution.file_hash(fresh),
                          "location": "$.engineering_adverse_control"}]}]}
    target = root / "inputs/late-finding-context.json"
    atomic_json(target, context)
    return context, target

def commit_late_hold(root, context, path, **overrides):
    values = {"actor_id": "physicist", "cycle_id": context["cycle_id"], "claim_scope": context["claim_scope"],
              "summary": "Hold future use pending new scientific evidence", "finding_context": str(path),
              "finding_context_sha256": execution.file_hash(path)}
    values.update(overrides)
    return review.submit_hold(root, **values)
