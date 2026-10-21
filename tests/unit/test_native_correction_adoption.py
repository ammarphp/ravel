"""Real native custody transitions with tiny substitute workers, no physics tools.

The native card/manifest preparation, approvals, review journal, supervisor and
receipt validation are real. Substitute workers create explicitly synthetic
artifacts for every native descendant; no simulated event or fit is claimed.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

import pytest

from ravel.physics import native_pipeline as pipeline, native_effective_config as effective
from ravel.workflow import execution, physics_review as review, stage_supervisor, waypoint_evidence
from ravel.workflow.state_io import atomic_json, read_json
from bound_review import bound_review
from test_native_dispatch import configuration, approve_fixture
from test_physics_review import policy
from method_decision_fixture import admit_method


def _tiny_plan(root, config, worker):
    plan = pipeline.build_execution_plan(root, config)
    plan["required_tools"] = []; plan["required_backend_files"] = []
    for item in plan["stages"]:
        if item["stage"] not in ("prepare", "native_report"):
            item["command"] = [sys.executable, str(worker), item["stage"], json.dumps(item["outputs"])]
            # A plan built after approval already lists the approved worker among its inputs.
            item["inputs"] = list(dict.fromkeys([*item["inputs"], str(worker)]))
    plan["sources"].append(effective.fingerprint(worker))
    plan["plan_sha256"] = pipeline.plan_hash(plan)
    return plan


def _packet(root, plan, *, passed):
    produced = "output/native_execution_result.json"
    atomic_json(root/"inputs/reference.json", {"synthetic": True})
    atomic_json(root/"inputs/comparison.json", {"status": "pass" if passed else "fail",
        "summary": "Synthetic custody control only", "diagnostics": {"synthetic": True}})
    atomic_json(root/waypoint_evidence.MANIFEST, waypoint_evidence.create(root, produced=produced,
        reference="inputs/reference.json", comparison="inputs/comparison.json", inputs=[effective.MANIFEST]))
    atomic_json(root/"inputs/checkin2.json", {"sections": {"evidence_manifest": waypoint_evidence.MANIFEST}})
    records = execution.load_execution(root)["stages"]
    ids = [records[item["stage"]]["attempt_id"] for item in plan["stages"]]
    atomic_json(root/"inputs/review-checks.json", {"schema_version": 1, "checks": [
        {"id": cid, "status": "pass" if cid == "integrity" or passed else "fail", "attempt_ids": ids,
         "evidence": [{"path": produced, "location": "$.physics_certified"}]} for cid in ("integrity", "agreement")]})
    return records


def _supervisor(stage, *args, **kwargs):
    # Adoption validates the approval and review in its own process; allow for a loaded host.
    return stage_supervisor.supervise(stage, *args, **kwargs, kill_secs=60, poll=.01, grace=.2)


def _reapprove(root):
    """The operator's amendment re-approval of CHECK-IN 1, scripted like the first approval."""
    from ravel.workflow import workflow_state
    assert workflow_state.cmd_approve(argparse.Namespace(rundir=str(root), plan="smoke", scripted=True,
        quote="Amend CHECK-IN 1 for the reviewed shower correction")) == 0
    return read_json(root/"inputs/checkin1_approval.json")


def _admit(root, settings, stages, specs):
    return review.authorize_correction(root, actor_id="physicist", changed_paths=settings,
        stages=stages, recheck_checks=["agreement"], stage_specs=specs)


@pytest.fixture
def corrected_native(tmp_path, monkeypatch):
    """A send-back, the corrected source card and the prepared derivative, before any amendment."""
    root = tmp_path.resolve()
    (root/"inputs").mkdir()
    monkeypatch.setenv("RAVEL_NATIVE_BUILD", str(root/"native-build"))
    converter = root/"native-build/tools/miniforge3/envs/pipeline/share/mapyde/scripts/Delphes2SA.py"
    converter.parent.mkdir(parents=True); converter.write_text("# synthetic unused backend input\n")
    config = configuration(root)
    worker = root/"inputs/tiny-native-worker.py"
    worker.write_text("import json,pathlib,sys\n"
        "for name in json.loads(sys.argv[2]):\n"
        " p=pathlib.Path(name); p.parent.mkdir(parents=True,exist_ok=True)\n"
        " p.write_text(json.dumps({'synthetic_stage':sys.argv[1],'physics_certified':False})+'\\n')\n"
        "print('synthetic worker '+sys.argv[1],flush=True)\n")
    original = _tiny_plan(root, config, worker)
    derivative_path = root/"inputs/native_derivative.json"
    settings = [derivative_path.relative_to(root).as_posix(), effective.MANIFEST,
                "cards/shower.cfg", "output/shower.cfg"]
    p = policy(); p.update(allowed_changed_paths=settings,
                          allowed_stages=[item["stage"] for item in original["stages"]])
    atomic_json(root/review.POLICY, p)
    # The method decision precedes approval; record it before the plan, as approve_fixture does.
    admit_method(root, "new_events")
    # Rebuild now that the prospective policy and decision are stage/approval inputs.
    original = _tiny_plan(root, config, worker)
    approve_fixture(original)
    first_approval = execution.file_hash(root/"inputs/checkin1_approval.json")
    derivative_path.write_bytes(Path(original["plan_path"]).read_bytes())
    assert pipeline.execute_plan(original, supervisor=_supervisor, resume=False) == 0
    before = _packet(root, original, passed=False)
    review.open_cycle(root, effective_settings=settings,
        stage_receipts=[before[item["stage"]]["attempt_record"] for item in original["stages"]],
        check_results="inputs/review-checks.json")
    # The send-back is the bound response of a dispatched critic; declared names are advice.
    bound_review(root, role="physics_critic", verdict="send_back",
        summary="Exercise explicit shower setting correction", findings=[{
            "id": "F-shower", "summary": "Rerun the controlled native chain after the shower correction",
            "evidence": [{"path": "output/shower.cfg", "location": "PartonLevel:MPI"}],
            "check_ids": ["agreement"], "required_paths": settings,
            "required_stages": [item["stage"] for item in original["stages"]]}])
    shower_source = root/"cards/shower.cfg"
    shower_source.write_text(shower_source.read_text()+"PartonLevel:MPI = off\n")
    derivative = pipeline.correction_derivative(_tiny_plan(root, config, worker), plan_path=derivative_path)
    pipeline.write_plan(derivative); pipeline.prepare(derivative)
    specs = []
    for item in derivative["stages"]:
        old_inputs = [str(derivative_path) if value == original["plan_path"] else value
                      for value in before[item["stage"]]["inputs"]]
        specs.append({**item, "inputs": list(dict.fromkeys([*old_inputs, *item["inputs"]])),
                      "cwd": str(root), "log": str(root/"logs"/(item["stage"]+".log"))})
    return root, original, derivative, before, settings, specs, first_approval


@pytest.fixture
def admitted_native(corrected_native):
    root, original, derivative, before, settings, specs, first_approval = corrected_native
    amended = _reapprove(root)
    amendment = _admit(root, settings, [item["stage"] for item in derivative["stages"]], specs)
    return root, original, derivative, amendment, before, settings, first_approval, amended


def test_native_adoption_repairs_actual_preparation_dependency_and_full_chain(admitted_native):
    root, original, derivative, amendment, before, settings, first_approval, amended = admitted_native
    # The amendment re-approval names exactly the changed approved inputs against the first approval.
    assert {row["path"] for row in amended["input_changes"]} == {"cards/shower.cfg", "output/shower.cfg"}
    assert {row["prior_approval_sha256"] for row in amended["input_changes"]} == {first_approval}
    assert "stage prepare outputs changed" in execution.stage_errors(root, "prepare")
    original_approval = (root/"inputs/checkin1_approval.json").read_bytes()
    cards_before = {name: (root/"output"/name).read_bytes() for name in effective.expected_cards(derivative)}
    assert pipeline.execute_plan(derivative, supervisor=_supervisor) == 0
    assert (root/"inputs/checkin1_approval.json").read_bytes() == original_approval
    assert cards_before == {name: (root/"output"/name).read_bytes() for name in cards_before}
    assert read_json(root/"output/native_preparation_adoption.json")["mode"] == "adopt_frozen_prepared_cards"
    after = execution.load_execution(root)["stages"]
    assert all(after[name]["attempt_id"] != before[name]["attempt_id"] for name in before)
    assert execution.validate_completed_execution(root, derivative["stages"]) == []
    _packet(root, derivative, passed=True)
    review.open_cycle(root, effective_settings=settings, correction_id=amendment["correction_id"],
        stage_receipts=[after[item["stage"]]["attempt_record"] for item in derivative["stages"]],
        check_results="inputs/review-checks.json")
    for role in ("physics_critic", "skeptical_verifier", "physics_decider"):
        bound_review(root, role=role, verdict="accept", summary="Synthetic custody checks passed",
                     closes=["F-shower"], claim_scope="reproduction")
    assert review.gate_errors(root, "delivery") == []
    assert pipeline.execute_plan(derivative, supervisor=_supervisor, resume=True) == 0
    assert execution.load_execution(root)["stages"] == after


@pytest.mark.parametrize("mutation,reason", [
    ("card", "approved input changed: output/shower.cfg"),
    ("ordinary_prepare", "native correction requires isolated adoption of its frozen prepared cards"),
    ("missing_descendant", "native correction must preserve the complete approved stage graph")])
def test_native_adoption_refuses_changed_bytes_or_scope_before_launch(admitted_native, mutation, reason):
    root, _, derivative, amendment, before, *_ = admitted_native
    if mutation == "card":
        (root/"output/shower.cfg").write_text("Beams:frameType = 5\n")
    elif mutation == "ordinary_prepare":
        derivative = copy.deepcopy(derivative)
        derivative["stages"][0]["command"] = pipeline.module_command("ravel.physics.native_pipeline", "prepare", "--plan", derivative["plan_path"])
        derivative["plan_sha256"] = pipeline.plan_hash(derivative)
    else:
        derivative = copy.deepcopy(derivative)
        derivative["stages"] = derivative["stages"][:-1]
        derivative["plan_sha256"] = pipeline.plan_hash(derivative)
    with pytest.raises(ValueError, match=reason):
        pipeline.execute_plan(derivative, supervisor=_supervisor)
    assert execution.load_execution(root)["stages"] == before
    assert not (root/"output/native_preparation_adoption.json").exists()


@pytest.mark.parametrize("amendment", ["none", "unlisted_input"])
def test_native_adoption_without_matching_amendment_reapproval_is_refused(corrected_native, amendment):
    """Changed card bytes are never admitted under the unchanged first approval, nor beyond the review policy."""
    root, _, derivative, before, settings, specs, first_approval = corrected_native
    reason = "re-approve CHECK-IN 1"
    if amendment == "unlisted_input":
        detector = root/"cards/detector.tcl"
        detector.write_text(detector.read_text()+"# unreviewed detector revision\n")
        _reapprove(root)
        reason = "outside the review policy's allowed changed paths: cards/detector.tcl"
    else:
        assert execution.file_hash(root/"inputs/checkin1_approval.json") == first_approval
    events = sorted(p.name for p in (root/review.DIRECTORY/"events").iterdir())
    with pytest.raises(ValueError, match=reason):
        _admit(root, settings, [item["stage"] for item in derivative["stages"]], specs)
    with pytest.raises(ValueError, match=reason):
        pipeline.execute_plan(derivative, supervisor=_supervisor)
    assert sorted(p.name for p in (root/review.DIRECTORY/"events").iterdir()) == events
    assert execution.load_execution(root)["stages"] == before
    assert not (root/"output/native_preparation_adoption.json").exists()
