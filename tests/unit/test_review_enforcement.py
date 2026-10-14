"""Real tiny-process controls across review, supervisor, launch audit and delivery gates.

These use actual CHECK-IN 1 approval verification and actual execution receipts.
No physics generator, detector simulator, fit or external service is invoked.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

from ravel.workflow import execution, physics_review as review, review_enforcement, stage_supervisor, waypoint_evidence
from ravel.workflow import launch_authorization, workflow_state
from ravel.workflow.state_io import atomic_json, read_json
from test_checkin2_gate import CHECKIN2, _run, _ws
from test_physics_review import policy


@pytest.fixture
def control(tmp_path):
    root = _run(tmp_path, checkin2=False)
    p = policy()
    p.update(allowed_changed_paths=["inputs/control-settings.json"], allowed_stages=["control"])
    atomic_json(root / review.POLICY, p)
    approval = _ws("approve", "--rundir", root, "--quote", "Approve the exact synthetic two-redo test envelope", "--plan", "full")
    assert approval.returncode == 0, approval.stderr
    settings = root / "inputs/control-settings.json"
    output = root / "outputs/control-result.json"
    script = root / "inputs/control-worker.py"
    script.write_text("import json, pathlib, sys\n"
        "settings = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        "if settings['fail']: raise SystemExit(7)\n"
        "path = pathlib.Path(sys.argv[2]); path.parent.mkdir(parents=True, exist_ok=True)\n"
        "path.write_text(json.dumps({'value': settings['value']}) + '\\n')\n")
    atomic_json(settings, {"value": 1, "fail": False})
    command = [sys.executable, str(script), str(settings), str(output)]
    inputs, outputs = [str(settings), str(script)], [str(output)]
    data = {"root": root, "settings": settings, "output": output, "command": command, "inputs": inputs, "outputs": outputs}
    assert _supervise(data) == 0
    _packet(data, "fail")
    receipt = execution.load_execution(root)["stages"]["control"]
    review.open_cycle(root, effective_settings=["inputs/control-settings.json"],
        stage_receipts=[receipt["attempt_record"]], check_results="inputs/review-checks.json")
    return data


def _supervise(data, *, command=None, resume=False):
    return stage_supervisor.supervise("control", str(data["root"]), 1, "logs/control.log",
        data["command"] if command is None else command, kill_secs=10, poll=.01, grace=.2,
        inputs=data["inputs"], outputs=data["outputs"], depends_on=[], resume=resume, cwd=str(data["root"]),
        required_plan="smoke" if not review.active(data["root"]) else "full")


def _packet(data, agreement):
    root = data["root"]
    atomic_json(root / "inputs/control-reference.json", {"value": 2})
    atomic_json(root / "inputs/control-comparison.json", {"status": agreement,
        "summary": "The declared synthetic measurement", "diagnostics": {"value": read_json(data["output"])["value"]}})
    manifest = waypoint_evidence.create(root, produced="outputs/control-result.json", reference="inputs/control-reference.json",
        comparison="inputs/control-comparison.json", inputs=["inputs/control-settings.json"])
    atomic_json(root / waypoint_evidence.MANIFEST, manifest)
    checkin = copy.deepcopy(CHECKIN2)
    checkin["sections"]["evidence_manifest"] = waypoint_evidence.MANIFEST
    atomic_json(root / "inputs/checkin2.json", checkin)
    receipt = execution.load_execution(root)["stages"]["control"]
    atomic_json(root / "inputs/review-checks.json", {"schema_version": 1, "checks": [
        {"id": name, "status": status, "attempt_ids": [receipt["attempt_id"]],
         "evidence": [{"path": "outputs/control-result.json", "location": "$.value"}]}
        for name, status in (("integrity", "pass"), ("agreement", agreement))]})


def _reject(data):
    return review.submit_review(data["root"], role="physics_critic", actor_id="critic", verdict="send_back",
        summary="The declared value is wrong; perform the bounded correction", findings=[{
            "id": "F-value", "summary": "Recompute after fixing the declared setting",
            "evidence": [{"path": "outputs/control-result.json", "location": "$.value"}],
            "check_ids": ["agreement"], "required_paths": ["inputs/control-settings.json"], "required_stages": ["control"]}])


def _admit(data, *, fail=False):
    atomic_json(data["settings"], {"value": 2, "fail": fail})
    return review.authorize_correction(data["root"], actor_id="physicist",
        changed_paths=["inputs/control-settings.json"], stages=["control"], recheck_checks=["agreement"])


def _accept(data, *, closes=(), scope="reproduction"):
    for role, actor in (("physics_critic", "critic"), ("skeptical_verifier", "skeptic"), ("physics_decider", "physicist")):
        review.submit_review(data["root"], role=role, actor_id=actor, verdict="accept", summary="Checked the actual control output",
            closes=list(closes), claim_scope=scope)


def test_real_sendback_redo_successor_go_and_launch_audit(control):
    data, root = control, control["root"]
    first_attempt = execution.load_execution(root)["stages"]["control"]["attempt_id"]
    _reject(data)
    assert review_enforcement.delivery_errors(root)
    amendment = _admit(data)
    assert _supervise(data, resume=True) == 0  # admitted correction forces a fresh attempt
    receipt = execution.load_execution(root)["stages"]["control"]
    assert receipt["attempt_id"] != first_attempt
    assert receipt["authorization_receipt"]
    assert read_json(data["output"])["value"] == 2
    assert review_enforcement.delivery_errors(root), "execution success does not self-certify the science"
    _packet(data, "pass")
    review.open_cycle(root, effective_settings=["inputs/control-settings.json"],
        stage_receipts=[receipt["attempt_record"]], check_results="inputs/review-checks.json",
        correction_id=amendment["correction_id"])
    _accept(data, closes=["F-value"])
    assert review_enforcement.delivery_errors(root) == []
    go = _ws("go", "--rundir", root, "--quote", "GO after the three recorded reviews")
    assert go.returncode == 0, go.stderr
    assert workflow_state.verify_checkin2_go(str(root)) == []
    assert launch_authorization.audit_launches(root) == []
    # Existing valid products are reusable after the completed review; no second process.
    before = len(launch_authorization._events(root))
    assert _supervise(data, resume=True) == 0
    assert len(launch_authorization._events(root)) == before


def test_rejected_valid_receipt_cannot_escape_through_resume(control):
    _reject(control)
    original = execution.load_execution(control["root"])["stages"]["control"]["attempt_id"]
    with pytest.raises(ValueError, match="scientific review blocks"):
        _supervise(control, resume=True)
    assert execution.load_execution(control["root"])["stages"]["control"]["attempt_id"] == original
    assert review_enforcement.delivery_errors(control["root"])


def test_changed_correction_command_is_refused_before_process_or_attempt(control):
    _reject(control)
    _admit(control)
    before = execution.load_execution(control["root"])["stages"]["control"]["attempt_id"]
    with pytest.raises(ValueError, match="differ from admission"):
        _supervise(control, command=[sys.executable, "-c", "raise SystemExit(0)"])
    assert execution.load_execution(control["root"])["stages"]["control"]["attempt_id"] == before
    assert [e["authorization"]["required_plan"] for e in launch_authorization._events(control["root"])
            if e["event"] == "authorized"] == ["smoke"]


def test_failed_real_correction_consumes_budget_and_cannot_resume_or_reset(control):
    _reject(control)
    _admit(control, fail=True)
    assert _supervise(control, resume=True) == 7
    status = review.status(control["root"])
    assert status["state"] == "correction_failed" and status["redos_used"] == 1
    failed_attempt = execution.load_execution(control["root"])["stages"]["control"]["attempt_id"]
    assert launch_authorization.audit_launches(control["root"]) == []
    with pytest.raises(ValueError, match="scientific review blocks"):
        _supervise(control, resume=True)
    _admit(control, fail=True)
    assert _supervise(control) == 7
    assert execution.load_execution(control["root"])["stages"]["control"]["attempt_id"] != failed_attempt
    assert review.status(control["root"])["redos_remaining"] == 0
    with pytest.raises(ValueError, match="budget exhausted"):
        _admit(control, fail=False)
    assert review_enforcement.delivery_errors(control["root"])


def test_reviewed_diagnostic_rejection_can_be_delivered_but_cannot_launch_bulk(control):
    _accept(control, scope="diagnostic")
    assert review_enforcement.delivery_errors(control["root"]) == []
    go = _ws("go", "--rundir", control["root"], "--quote", "Try to turn diagnosis into production")
    assert go.returncode != 0 and "does not authorize bulk" in go.stderr
    with pytest.raises(ValueError, match="does not authorize bulk"):
        _supervise(control)


def test_same_path_bulk_overwrite_refuses_and_retains_previous_evidence(control):
    data, root = control, control["root"]
    _reject(data)
    amendment = _admit(data)
    assert _supervise(data) == 0
    receipt = execution.load_execution(root)["stages"]["control"]
    _packet(data, "pass")
    review.open_cycle(root, effective_settings=["inputs/control-settings.json"],
        stage_receipts=[receipt["attempt_record"]], check_results="inputs/review-checks.json",
        correction_id=amendment["correction_id"])
    _accept(data, closes=["F-value"])
    go = _ws("go", "--rundir", root, "--quote", "GO for declared production")
    assert go.returncode == 0, go.stderr
    previous = data["output"].read_bytes()
    launches = len(launch_authorization._events(root))
    # Current supported boundary: reviewed outputs must be preserved separately
    # from new production outputs. The attempted overwrite must launch no process.
    try:
        result = _supervise(data)
    except ValueError:
        result = 2
    assert result != 0
    assert len(launch_authorization._events(root)) == launches
    assert data["output"].read_bytes() == previous
    assert execution.load_execution(root)["stages"]["control"]["attempt_id"] == receipt["attempt_id"]


@pytest.mark.parametrize("events", [1, 1000, 1001])
def test_initial_declared_smoke_has_retained_full_envelope_authorization(tmp_path, events):
    root = _run(tmp_path, checkin2=False)
    assert not review.active(root)
    assert not (root / "inputs/checkin2_go.json").exists()
    script = root / "inputs/smoke-control.py"
    script.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('measured\\n')\n")
    output = root / "smoke-control.txt"
    args = ("smoke-control", str(root), events, "logs/smoke-control.log", [sys.executable, str(script), str(output)])
    kwargs = dict(kill_secs=10, poll=.01, grace=.2, inputs=[str(script)], outputs=[str(output)],
                  depends_on=[], cwd=str(root), required_plan="smoke")
    if events > 1000:
        with pytest.raises(ValueError, match="event count exceeds"):
            stage_supervisor.supervise(*args, **kwargs)
        assert not output.exists()
        assert not launch_authorization._events(root)
        assert "smoke-control" not in execution.load_execution(root)["stages"]
    else:
        assert stage_supervisor.supervise(*args, **kwargs) == 0
        receipt = execution.load_execution(root)["stages"]["smoke-control"]
        assert receipt["authorization_receipt"]
        launches = launch_authorization._events(root)
        launched = next(e for e in launches if e["event"] == "authorized")
        assert launched["authorization"]["required_plan"] == "smoke"
        assert json.loads(launched["authorization"]["approval"]["text"])["approved_plan"] == "full"
        launch_authorization._historical_errors(launched)
        assert "recorded bulk compute" in launch_authorization.audit_launches(root)[0]
        assert not review.active(root)


@pytest.mark.parametrize("rung", [None, "smoke"])
def test_generic_cli_cannot_launch_contracted_work_without_approval(tmp_path, rung):
    import subprocess
    root = _run(tmp_path, checkin2=False, approve=False)
    output = root / "unauthorized.txt"
    command = [sys.executable, "-m", "ravel.workflow.stage_supervisor", "--stage", "control",
               "--rundir", str(root), "--events", "1", "--log", "logs/control.log"]
    if rung:
        command.extend(["--required-plan", rung])
    command.extend(["--", sys.executable, "-c", "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('bad')", str(output)])
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists() and not launch_authorization._events(root)
