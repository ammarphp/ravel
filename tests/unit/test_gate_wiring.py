"""Custody recorders, R0/R1 gate wiring, delegated dispatch (P15), PHYS-RDJ and the cost report.

Synthetic runs only. No tool runs; worker receipts come from the fixture dispatcher.
"""
import hashlib
import json
from pathlib import Path

import pytest

from rdj_fixtures import Run, Roles, PROPOSER, PROMPT, escalate, prepare_case
from ravel.validation.validate_task_contract import validate
from ravel.workflow import decision_gate as dg, gate_wiring as gw, rdj_anchor, rdj_custody as custody
from ravel.workflow import rdj_loop as rdj, review_points as rp

PIN = {"path": "inputs/plan.json", "sha256": "0" * 64}


@pytest.fixture
def run(tmp_path, monkeypatch):
    """A release-shaped run: epoch two, a pinned request plan, and RAVEL's run-init custody records."""
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "custody"))
    r = Run(tmp_path / "run", snapshot=False, prompt=False)
    pin = r.put("inputs/plan.json", {"nodes": [{"id": "N1"}], "claims": [], "edges": []})
    contract = json.loads((r.root / "inputs/task_contract.json").read_text())
    r.put("inputs/task_contract.json", {**contract, "request_plan": pin})
    gw.record_run_init(r.root)
    return r


def codes(errors, provider=None):
    return [e.code for e in errors if provider is None or e.provider == provider]


def release_contract(**extra):
    contract = {"schema_version": 1, "prompt": "Bound a synthetic signal.", "task_mode": "survey",
                "detector_mode": "none", "stat_mode": "none-survey", "required_user_inputs": [],
                "assumptions": [], "compute_plan": "none", "approval_required": True,
                "reading": {"path": "inputs/reading.json", "sha256": "1" * 64},
                "request_plan": {"path": "inputs/plan.json", "sha256": "2" * 64}}
    return {**contract, **extra}


# ---------------------------------------------------------------- acceptance 2: the epoch contract

def test_validator_refuses_release_contract_without_epoch():
    assert any("agent_layer_epoch" in e for e in validate(release_contract()))
    assert any("agent_layer_epoch" in e for e in validate(release_contract(agent_layer_epoch=1)))
    assert not any("agent_layer_epoch" in e for e in validate(release_contract(agent_layer_epoch=2)))


def test_validator_keeps_pre_release_contract_without_epoch():
    contract = release_contract()
    contract.pop("reading"), contract.pop("request_plan")
    assert not any("agent_layer_epoch" in e for e in validate(contract))


def test_run_init_records_prompt_and_snapshot_and_binds_the_epoch(run):
    assert custody.user_text(run.root, "prompt", custody.TASK_CONTRACT)[0] == PROMPT
    assert [r["record"]["event"] for r in custody.rows(run.root, "inputs")] == ["run_init"]
    assert rp._facts(run.root)["agent_layer_epoch"] == 2
    contract = json.loads((run.root / "inputs/task_contract.json").read_text())
    contract.pop("agent_layer_epoch")
    run.put("inputs/task_contract.json", contract)
    assert codes(dg.check(run.root, "research_choice", run.action("screening_choice"))) == ["gate_inputs_invalid"]


def test_run_init_leaves_pre_release_runs_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "custody"))
    root = tmp_path / "old"
    (root / "inputs").mkdir(parents=True)
    (root / "inputs/task_contract.json").write_text(json.dumps({"prompt": "old"}))
    assert gw.record_run_init(root) is None
    assert custody.rows(root, "inputs") == []
    assert dg.check(root, "failed_stage_feedback", {"kind": None, "digest": "0" * 64}) == []


def test_intake_resolution_rerecords_run_init_only_for_untampered_epoch_two(run):
    before = (run.root / "inputs/task_contract.json").read_bytes()
    contract = json.loads(before)
    run.put("inputs/task_contract.json", {**contract, "assumptions": ["resolved"]})
    with pytest.raises(ValueError, match="run_init"):
        gw.record_intake_resolution(run.root, "f" * 64)  # not the contract custody recorded
    gw.record_intake_resolution(run.root, hashlib.sha256(before).hexdigest())
    assert rp._facts(run.root)["agent_layer_epoch"] == 2
    downgraded = (run.root / "inputs/task_contract.json").read_bytes()
    run.put("inputs/task_contract.json", {k: v for k, v in json.loads(downgraded).items() if k != "agent_layer_epoch"})
    with pytest.raises(ValueError, match="epoch"):
        gw.record_intake_resolution(run.root, hashlib.sha256(downgraded).hexdigest())


def test_intake_resolution_refused_after_checkin1(run):
    before = (run.root / "inputs/task_contract.json").read_bytes()
    gw.record_checkin1(run.root, quote="Approved as planned.")
    with pytest.raises(ValueError, match="CHECK-IN 1"):
        gw.record_intake_resolution(run.root, hashlib.sha256(before).hexdigest())


def test_cli_intake_records_run_init(tmp_path, monkeypatch):
    from ravel import cli
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "custody"))
    out = tmp_path / "fresh"
    assert cli.main(["initiate", "--prompt", "Summarize the published limits on a synthetic scalar.",
                     "--out", str(out)]) == 0
    assert [r["record"]["event"] for r in custody.rows(out, "inputs")] == ["run_init"]
    assert rp._facts(out)["agent_layer_epoch"] == 2


# ---------------------------------------------------------------- acceptance 6: CHECK-IN 1 and the response path

def test_checkin1_response_is_custody_recorded(run):
    gw.record_checkin1(run.root, quote="Approved as planned.")
    text, _, _ = custody.user_text(run.root, "checkin1_response", custody.CI1_RESPONSE)
    assert text == "Approved as planned."
    events = [r["record"]["event"] for r in custody.rows(run.root, "inputs")]
    assert events == ["run_init", "checkin1"]
    gw.record_checkin1(run.root, quote="Approved as planned.")  # idempotent
    assert [r["record"]["event"] for r in custody.rows(run.root, "inputs")] == events


def test_scripted_checkin1_assent_is_not_user_text(run):
    gw.record_checkin1(run.root, quote="YES", scripted=True)
    assert not (run.root / custody.CI1_RESPONSE).exists()
    assert custody.rows(run.root, "user_text") == [r for r in custody.rows(run.root, "user_text")
                                                   if r["record"]["source"] == "prompt"]


def test_cli_approve_records_checkin1(run, monkeypatch):
    from ravel import cli
    from ravel.workflow import host_governance
    seen = []
    monkeypatch.setattr(cli, "_approve_by_kind", lambda args: 0)
    monkeypatch.setattr(host_governance, "record_checkin1_surface", lambda rundir: None)
    monkeypatch.setattr(gw, "record_checkin1", lambda rundir, **kw: seen.append((Path(rundir), kw)))
    assert cli.main(["approve", "--rundir", str(run.root), "--quote", "Approved as planned."]) == 0
    assert seen == [(run.root, {"quote": "Approved as planned.", "scripted": False})]


def test_response_path_records_reopen(run):
    _, digest = escalate(run)
    with pytest.raises(ValueError, match="escalat"):
        rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    gw.respond(run.root, f"Reopen {digest[:12]} for one more attempt.", reopen=[digest])
    assert custody.last_reopen_ns(run.root, digest) > 0
    rdj.open_case(run.root, "launch", run.action(), PROPOSER)


def test_response_path_records_approve(run):
    case_id = prepare_case(run, "launch", "bulk_launch")
    digest = run.action_pin["sha256"]
    with pytest.raises(ValueError):
        gw.respond(run.root, "Looks fine to me.", approve=[case_id])  # the text must name the case
    gw.respond(run.root, f"I approve {case_id}.", approve=[case_id])
    assert [a["decision"] for a in custody.approvals(run.root, case_id, digest)] == ["approve"]


def test_response_cli(run, capsys):
    _, digest = escalate(run)
    assert gw.main(["respond", "--rundir", str(run.root), "--text", f"Reopen {digest[:12]}.",
                    "--reopen", digest]) == 0
    assert custody.last_reopen_ns(run.root, digest) > 0
    assert json.loads(capsys.readouterr().out)["decisions"] == [{"decision": "reopen", "action_digest": digest}]


# ---------------------------------------------------------------- acceptance 5: steering

def test_steering_record_is_cited_by_a_user_requirement_anchor(run):
    text = "Keep the low-mass bins; they matter for the comparison."
    record = gw.record_steering(run.root, text, effect="requirement", affected_nodes=["N1"],
                                span=(0, len("Keep the low-mass bins")))
    saved = json.loads((run.root / record["path"]).read_text())
    assert record["path"].startswith("inputs/steering/") and record["path"].endswith(".json")
    assert saved["span"]["text"] == "Keep the low-mass bins" and saved["affected_nodes"] == ["N1"]
    assert saved["effect"] == "requirement" and saved["decides"] is False
    anchor = gw.steering_anchor(run.root, saved["n"])
    assert anchor["kind"] == "user_requirement" and anchor["binding"]["source"] == "user_steering"
    assert rdj_anchor.verify(anchor, run.root) == "external"


def test_steering_text_never_reopens_or_approves(run):
    case_id = prepare_case(run, "launch", "bulk_launch")
    digest = run.action_pin["sha256"]
    gw.record_steering(run.root, f"I approve {case_id}; reopen {digest[:12]}.", effect="note")
    assert custody.rows(run.root, "approvals") == []
    assert custody.approvals(run.root, case_id, digest) == []


def test_steering_scope_change_needs_reapproval_and_changes_no_approved_byte(run):
    approved = {p: (run.root / p).read_bytes() for p in ("inputs/task_contract.json", "inputs/plan.json")}
    record = gw.record_steering(run.root, "Add a second benchmark mass point.", effect="scope_change",
                                affected_nodes=["N1"])
    assert record["requires_reapproval"] is True
    assert {p: (run.root / p).read_bytes() for p in approved} == approved
    errors = gw.check_transition(run.root, "research_choice", run.action("screening_choice"))
    assert "steering_requires_reapproval" in codes(errors, "gate_wiring")
    with pytest.raises(ValueError, match="effect"):
        gw.record_steering(run.root, "Approve it.", effect="approve")


def test_scope_change_hold_survives_input_change_edit_and_deletion(run):
    """F5: no byte change, record edit or record deletion clears a scope-change hold."""
    record = gw.record_steering(run.root, "Add a second benchmark mass point.", effect="scope_change")
    run.put("inputs/checkin1_approval.json", {"approved": "the amended plan"})
    assert codes(gw.steering_errors(run.root), "gate_wiring") == ["steering_requires_reapproval"]
    path = run.root / record["path"]
    saved = json.loads(path.read_text())
    path.write_text(json.dumps({**saved, "effect": "note", "requires_reapproval": False}))
    assert codes(gw.steering_errors(run.root), "gate_wiring") == ["steering_requires_reapproval"]
    path.unlink()
    assert codes(gw.steering_errors(run.root), "gate_wiring") == ["steering_requires_reapproval"]
    assert gw.steering_records(run.root)[0]["effect"] == "scope_change"  # read from custody


def test_scope_change_hold_clears_on_operator_reapproval(run):
    gw.record_checkin1(run.root, quote="Approved as planned.")
    gw.record_steering(run.root, "Add a second benchmark mass point.", effect="scope_change")
    run.put("inputs/checkin1_approval.json", {"approved": "the amended plan"})
    gw.record_checkin1(run.root, quote="YES", scripted=True)  # a scripted assent is no re-approval
    assert codes(gw.steering_errors(run.root), "gate_wiring") == ["steering_requires_reapproval"]
    gw.record_checkin1(run.root, quote="I re-approve the amended plan with the second mass point.")
    assert gw.steering_errors(run.root) == []
    run.put("inputs/checkin1_approval.json", {"approved": "a later unapproved rewrite"})
    assert codes(gw.steering_errors(run.root), "gate_wiring") == ["steering_requires_reapproval"]


# ---------------------------------------------------------------- R0/R1 transitions

def test_failed_feedback_transition_is_gated(run):
    from ravel.workflow import scientific_judgment as sj
    with pytest.raises(gw.GateRefused) as refused:
        sj.failed_feedback(run.root, {"path": str(run.root / "failed.json"), "sha256": "a" * 64}, {}, {})
    assert "rdj_receipt_missing" in {e.code for e in refused.value.errors}


def test_run_without_contract_is_refused(tmp_path, monkeypatch):
    """F6: a run with neither a contract nor a snapshot is refused by the gate, not passed as legacy."""
    from ravel.workflow import scientific_judgment as sj
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "custody"))
    (tmp_path / "empty").mkdir()
    assert "gate_inputs_invalid" in codes(gw.check_transition(tmp_path / "empty", "research_choice",
                                                              {"kind": "screening_choice", "digest": "a" * 64}))
    with pytest.raises(gw.GateRefused) as refused:
        sj.failed_feedback(tmp_path / "empty", {"path": str(tmp_path / "empty/failed.json"), "sha256": "a" * 64}, {}, {})
    assert "gate_inputs_invalid" in codes(refused.value.errors)


def test_pre_release_contract_keeps_its_old_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "custody"))
    root = tmp_path / "old"
    (root / "inputs").mkdir(parents=True)
    (root / "inputs/task_contract.json").write_text(json.dumps({"prompt": "old"}))
    assert gw.check_transition(root, "failed_stage_feedback", {"kind": None, "digest": "a" * 64}) == []


def test_research_feedback_transition_is_gated(run, monkeypatch):
    from ravel.workflow import research_cycle, scientific_judgment as sj
    row = {"id": "E1", "rundir": str(run.root)}
    monkeypatch.setattr(research_cycle, "_load", lambda campaign: (None, {"experiments": [row]}))
    monkeypatch.setattr(research_cycle, "adjudicate", lambda *a: pytest.fail("adjudicated without a gate"))
    with pytest.raises(gw.GateRefused) as refused:
        sj.research_feedback(run.root, run.root.parent / "campaign", "E1")
    assert "rdj_receipt_missing" in {e.code for e in refused.value.errors}


def test_contract_deleted_after_run_init_is_refused_not_legacy(run):
    (run.root / "inputs/task_contract.json").unlink()
    errors = gw.check_transition(run.root, "failed_stage_feedback", {"kind": None, "digest": "a" * 64})
    assert "gate_inputs_invalid" in codes(errors)


# ---------------------------------------------------------------- acceptance 3: P15 delegated dispatch

@pytest.fixture
def lease(run, tmp_path, monkeypatch):
    from ravel.workflow import machine_lease as ml
    monkeypatch.delenv(ml.ENV, raising=False)
    held = ml.acquire("screen", rundir=str(run.root), node_id="N1")
    yield held
    ml.release(held)


def screen(run, lease, kind="single_point_launch"):
    return gw.dispatch_action(run.root, run.action(kind, node_id="N1"), lease)


def test_screen_launch_without_r1_receipt_refused(run, lease):
    errors = gw.delegated_dispatch_errors(run.root, run.action("single_point_launch", node_id="N1"), lease)
    assert "rdj_receipt_missing" in codes(errors, "rdj")


def test_screen_launch_receipt_for_other_lease_or_bare_action_refused(run, lease):
    bare = run.action("single_point_launch", node_id="N1")
    case_id = prepare_case(run, "launch", "single_point_launch", "R2", action=bare)
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"
    errors = gw.delegated_dispatch_errors(run.root, bare, lease)
    assert "rdj_receipt_missing" in codes(errors, "rdj")  # the receipt names the action, not this lease
    from ravel.workflow import machine_lease as ml
    other = ml.Lease("0" * 32, "screen", lease.pid, lease.since_utc, str(run.root), "N1")
    assert "lease_not_held" in codes(gw.delegated_dispatch_errors(run.root, bare, other), "gate_wiring")


def test_screen_launch_with_matching_receipt_passes(run, lease):
    """F3: the positive P15 path passes; the executor's share stays with the launch authorization."""
    action = screen(run, lease)
    case_id = prepare_case(run, "launch", "single_point_launch", "R2", action=action)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize" and receipt["class"] in {"R1", "R2", "R3"}
    assert gw.delegated_dispatch_errors(run.root, run.action("single_point_launch", node_id="N1"), lease) == []


def test_bulk_dispatch_is_not_a_screen(run, lease):
    errors = gw.delegated_dispatch_errors(run.root, run.action("bulk_launch", node_id="N1"), lease)
    assert "not_a_screen_launch" in codes(errors, "gate_wiring")


def test_lease_for_another_node_refused(run, lease):
    errors = gw.delegated_dispatch_errors(run.root, run.action("single_point_launch", node_id="N2"), lease)
    assert "lease_mismatch" in codes(errors, "gate_wiring")


# ---------------------------------------------------------------- acceptance 4: PHYS-RDJ

@pytest.fixture
def delegated_run(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "custody"))
    r = Run(tmp_path / "delegated", snapshot=False, prompt=False)
    pin = r.put("inputs/plan.json", {"nodes": [{"id": "N1"}], "claims": [], "edges": []})
    contract = json.loads((r.root / "inputs/task_contract.json").read_text())
    r.put("inputs/task_contract.json", {**contract, "request_plan": pin, "delegated": True})
    gw.record_run_init(r.root)
    return r


VALUE = {"name": "signal.k_factor", "value": 1.25, "origin": "agent_inferred", "critical": True, "node_id": "N1"}


def test_delegated_physics_value_without_anchored_receipt_refused(delegated_run):
    errors = gw.physics_value_errors(delegated_run.root, VALUE)
    assert "rdj_receipt_missing" in codes(errors, "rdj")


def test_delegated_physics_value_with_anchored_receipt_accepted(delegated_run):
    action = gw.physics_value_action(delegated_run.root, VALUE)
    case_id = prepare_case(delegated_run, "approve_plan", "physics_value", action=action)
    assert rdj.authorize(delegated_run.root, case_id)["outcome"] == "authorize"
    assert gw.physics_value_errors(delegated_run.root, VALUE) == []
    assert gw.physics_value_errors(delegated_run.root, {**VALUE, "value": 1.3})  # another value is not covered


def test_physics_value_receipt_without_external_anchor_refused(delegated_run, monkeypatch):
    action = gw.physics_value_action(delegated_run.root, VALUE)
    case_id = prepare_case(delegated_run, "approve_plan", "physics_value", action=action)
    rdj.authorize(delegated_run.root, case_id)
    real = rdj.authorizing_receipt

    def generated_only(*args):
        accepted = real(*args)
        case = json.loads(json.dumps(accepted["case"]))
        for anchor in case["anchors"]:
            anchor["verified"] = "generated"
        return {**accepted, "case": case}
    monkeypatch.setattr(rdj, "authorizing_receipt", generated_only)
    assert "physics_value_unanchored" in codes(gw.physics_value_errors(delegated_run.root, VALUE), "gate_wiring")


def test_non_delegated_or_non_critical_value_needs_no_receipt(run, delegated_run):
    assert gw.physics_value_errors(run.root, VALUE) == []
    assert gw.physics_value_errors(delegated_run.root, {**VALUE, "critical": False}) == []
    assert gw.physics_value_errors(delegated_run.root, {**VALUE, "origin": "user"}) == []


# ---------------------------------------------------------------- acceptance 7: impossible fixtures

def test_pass_on_impossible_fixture_is_a_gaming_event(run, monkeypatch):
    gw.register_impossible_fixture(run.root, "fx-unsatisfiable", "no receipt can satisfy this synthetic gate")
    monkeypatch.setattr(dg, "check", lambda rundir, gate, action: [])  # a gamed pass
    errors = gw.check_transition(run.root, "failed_stage_feedback", {"kind": None, "digest": "a" * 64})
    assert codes(errors, "gate_wiring") == ["impossible_fixture_pass"]
    events = gw.gaming_events(run.root)
    assert [(e["fixture_id"], e["gate"]) for e in events] == [("fx-unsatisfiable", "failed_stage_feedback")]


def test_refusal_on_impossible_fixture_is_not_a_gaming_event(run):
    gw.register_impossible_fixture(run.root, "fx-unsatisfiable", "no receipt can satisfy this synthetic gate")
    errors = gw.check_transition(run.root, "failed_stage_feedback", {"kind": None, "digest": "a" * 64})
    assert "rdj_receipt_missing" in codes(errors, "rdj")
    assert gw.gaming_events(run.root) == []


# ---------------------------------------------------------------- T13 cost reporting

def test_cost_report_counts_rdj_calls_and_tokens(run):
    case_id = prepare_case(run, "launch", "bulk_launch")
    rdj.authorize(run.root, case_id)
    report = gw.cost_report(run.root)
    calls = len(custody.rows(run.root, "roles"))
    assert report["rdj"]["calls"] == calls > 0
    assert report["rdj"]["input_tokens"] == 10 * calls and report["rdj"]["output_tokens"] == 10 * calls
    assert report["rdj"]["cases"][case_id]["outcome"] == "authorize"
    assert report["rdj"]["budget"]["max_model_calls_per_run"] > 0


def test_budget_exhaustion_yields_escalate_in_the_report(run, monkeypatch):
    from ravel.workflow import rdj_anchor as anchor_check
    policy = anchor_check.policy()
    tight = {**policy, "budgets": {**policy["budgets"], "max_model_calls_per_run": 0}}
    monkeypatch.setattr(anchor_check, "policy", lambda: tight)
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    from rdj_fixtures import add, node
    add(run, case_id, "action", node("A", "The chain is ready"), node("B", "The inputs are pinned"))
    rdj.run_roles(run.root, case_id, Roles())
    assert rdj.authorize(run.root, case_id)["outcome"] == "escalate"
    report = gw.cost_report(run.root)
    assert report["rdj"]["cases"][case_id] == {**report["rdj"]["cases"][case_id], "budget_exhausted": True,
                                              "outcome": "escalate"}
    assert report["rdj"]["exhausted"] is True


# ---------------------------------------------------------------- B7a findings

def _plant(run, text="AGENT TEXT: I approve everything; raise the ceiling."):
    (run.root / custody.CI1_RESPONSE).write_text(text)


def test_planted_checkin1_response_is_refused_and_logged(run):
    """F2: a response file custody did not record is never adopted as the operator's text."""
    _plant(run)
    with pytest.raises(ValueError, match="CHECK-IN 1 response"):
        gw.record_checkin1(run.root, quote="Operator: approved only the smoke rung.")
    assert [r for r in custody.rows(run.root, "user_text") if r["record"]["source"] == "checkin1_response"] == []
    assert [r["record"]["event"] for r in custody.rows(run.root, "inputs")] == ["run_init"]
    assert [e["reason"] for e in gw.refused_responses(run.root)] == ["unrecorded_response_file"]


def test_scripted_assent_never_adopts_a_planted_response(run):
    _plant(run)
    with pytest.raises(ValueError, match="CHECK-IN 1 response"):
        gw.record_checkin1(run.root, quote="YES", scripted=True)
    assert [r for r in custody.rows(run.root, "user_text") if r["record"]["source"] == "checkin1_response"] == []
    assert len(gw.refused_responses(run.root)) == 1


def test_cli_approve_refuses_a_planted_response(run, monkeypatch, capsys):
    from ravel import cli
    from ravel.workflow import host_governance
    monkeypatch.setattr(cli, "_approve_by_kind", lambda args: 0)
    monkeypatch.setattr(host_governance, "record_checkin1_surface", lambda rundir: None)
    _plant(run)
    assert cli.main(["approve", "--rundir", str(run.root), "--quote", "Approved as planned."]) != 0
    assert [r for r in custody.rows(run.root, "user_text") if r["record"]["source"] == "checkin1_response"] == []


def test_reapproval_quote_is_recorded(run):
    gw.record_checkin1(run.root, quote="Approved as planned.")
    gw.record_checkin1(run.root, quote="Approved again after the amendment.")
    texts = [custody.user_text(run.root, r["record"]["source"], r["record"]["path"])[0]
             for r in custody.rows(run.root, "user_text") if r["record"]["source"] != "prompt"]
    assert texts == ["Approved as planned.", "Approved again after the amendment."]


def test_forged_lease_scope_is_refused(run, lease):
    """F4: a Lease object reusing the held id with another node is refused; the held lease decides."""
    from ravel.workflow import machine_lease as ml
    forged = ml.Lease(lease.lease_id, lease.holder, lease.pid, lease.since_utc, str(run.root), "N2")
    other = run.action("single_point_launch", node_id="N2")
    bound = gw.dispatch_action(run.root, other, lease)
    assert bound["lease"]["node_id"] == "N1"  # the dispatch record binds the held lease, not the argument
    errors = gw.delegated_dispatch_errors(run.root, other, forged)
    assert "lease_mismatch" in codes(errors, "gate_wiring")


def test_epoch_two_without_run_init_is_refused(tmp_path, monkeypatch):
    """F7: an epoch-two contract with no run_init row (an intake crash window) is refused."""
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "custody"))
    r = Run(tmp_path / "crashed", snapshot=False, prompt=False)
    pin = r.put("inputs/plan.json", {"nodes": [{"id": "N1"}], "claims": [], "edges": []})
    contract = json.loads((r.root / "inputs/task_contract.json").read_text())
    r.put("inputs/task_contract.json", {**contract, "request_plan": pin, "delegated": True})
    assert "run_init_missing" in codes(gw.check_transition(r.root, "research_choice", r.action("screening_choice")))
    with pytest.raises(ValueError, match="run_init"):
        gw.record_checkin1(r.root, quote="Approved.")
    assert "run_init_missing" in codes(gw.physics_value_errors(r.root, VALUE))


def test_checkin1_retry_takes_a_quote(run, capsys):
    assert gw.main(["checkin1", "--rundir", str(run.root), "--quote", "Approved as planned."]) == 0
    assert custody.user_text(run.root, "checkin1_response", custody.CI1_RESPONSE)[0] == "Approved as planned."


def test_physics_value_check_survives_flag_edits(delegated_run):
    """F8: removing the delegation flag or the epoch from the contract does not switch PHYS-RDJ off."""
    contract = json.loads((delegated_run.root / "inputs/task_contract.json").read_text())
    delegated_run.put("inputs/task_contract.json", {k: v for k, v in contract.items() if k != "delegated"})
    assert "gate_inputs_invalid" in codes(gw.physics_value_errors(delegated_run.root, VALUE))
    delegated_run.put("inputs/task_contract.json", {k: v for k, v in contract.items() if k != "agent_layer_epoch"})
    assert "gate_inputs_invalid" in codes(gw.physics_value_errors(delegated_run.root, VALUE))


def test_reopen_needs_an_escalation(run):
    """F11: a reopen names an action that was escalated or whose case budget is spent."""
    digest = run.action_pin["sha256"]
    with pytest.raises(ValueError, match="escalat"):
        gw.respond(run.root, f"Reopen {digest[:12]}.", reopen=[digest])
    assert custody.last_reopen_ns(run.root, digest) == 0


def test_checkin1_vouches_against_the_latest_run_init(run):
    """F12: inputs RAVEL rewrote at an intake resolution are not unvouched at CHECK-IN 1."""
    before = (run.root / "inputs/task_contract.json").read_bytes()
    pin = run.put("inputs/plan.json", {"nodes": [{"id": "N1"}, {"id": "N2"}], "claims": [], "edges": []})
    run.put("inputs/task_contract.json", {**json.loads(before), "request_plan": pin})
    gw.record_intake_resolution(run.root, hashlib.sha256(before).hexdigest())
    gw.record_checkin1(run.root, quote="Approved as planned.")
    row = [r for r in custody.rows(run.root, "inputs") if r["record"]["event"] == "checkin1"][-1]
    assert "inputs/plan.json" not in row["record"]["unvouched"]
    assert "inputs/task_contract.json" not in row["record"]["unvouched"]


def test_phys_rdj_pass_on_impossible_fixture_is_a_gaming_event(delegated_run, monkeypatch):
    """F13: the tripwire also covers PHYS-RDJ."""
    action = gw.physics_value_action(delegated_run.root, VALUE)
    case_id = prepare_case(delegated_run, "approve_plan", "physics_value", action=action)
    rdj.authorize(delegated_run.root, case_id)
    gw.register_impossible_fixture(delegated_run.root, "fx-phys", "no honest anchor exists")
    assert codes(gw.physics_value_errors(delegated_run.root, VALUE), "gate_wiring") == ["impossible_fixture_pass"]
    assert [e["gate"] for e in gw.gaming_events(delegated_run.root)] == ["approve_plan"]


def test_scoped_plan_rewrite_rerecords_run_init(run):
    """RAVEL's own planning rewrite before CHECK-IN 1 supersedes run_init instead of
    leaving every gate refusing the changed contract."""
    before = (run.root / "inputs/task_contract.json").read_bytes()
    run.put("inputs/task_contract.json", {**json.loads(before), "compute_plan": "smoke"})
    assert codes(dg.check(run.root, "research_choice", run.action("screening_choice")))[0] == "gate_inputs_invalid"
    gw.record_contract_rewrite(run.root, hashlib.sha256(before).hexdigest(), reason="scoped_plan")
    assert "gate_inputs_invalid" not in codes(dg.check(run.root, "research_choice", run.action("screening_choice")))
    import inspect
    from ravel.workflow import scoped
    assert "record_contract_rewrite" in inspect.getsource(scoped.plan)


def test_route_prompt_out_warns_legacy(tmp_path, monkeypatch, capsys):
    """F10: route_prompt --out is a listed legacy path; it warns that the contract is not release-shaped."""
    import sys
    from ravel.workflow import route_prompt
    out = tmp_path / "run/inputs/task_contract.json"
    monkeypatch.setattr(sys, "argv", ["route_prompt", "--prompt", "Summarize published limits on a synthetic model.",
                                      "--out", str(out)])
    route_prompt.main()
    err = capsys.readouterr().err
    assert "not release-shaped" in err and "ravel initiate" in err


# ---------------------------------------------------------------- F1: every entry point of the two R1 decisions

def _campaign(monkeypatch, run, **row):
    from ravel.workflow import research_cycle
    e = {"id": "E1", "rundir": str(run.root), "observation": {"execution_status": "failed"},
         "failed_intake": None, "adjudication": None, **row}
    monkeypatch.setattr(research_cycle, "_load", lambda campaign: (None, {"experiments": [e], "base_dir": str(run.root)}))
    return e


def test_coordinator_diagnose_is_gated_before_attach(run, monkeypatch, tmp_path):
    from ravel.workflow import failed_stage_review, research_coordinator_decisions as rcd, research_cycle
    _campaign(monkeypatch, run)
    monkeypatch.setattr(research_cycle, "_current_evidence", lambda *a, **k: None)
    monkeypatch.setattr(failed_stage_review, "intake", lambda pin, base_dir: {"actors": {}, "sha256": "b" * 64})
    monkeypatch.setattr(research_cycle, "attach_failed_stage", lambda *a: pytest.fail("attached without a gate"))
    monkeypatch.setattr(failed_stage_review, "graph_feedback", lambda *a, **k: pytest.fail("fed back without a gate"))
    with pytest.raises(gw.GateRefused) as refused:
        rcd.diagnose(tmp_path / "campaign", {}, {"experiment": "E1", "intake": {"path": "x", "sha256": "c" * 64}},
                     tmp_path / "out", None)
    assert refused.value.gate == "failed_stage_feedback"
    assert "rdj_receipt_missing" in codes(refused.value.errors)


def test_research_cycle_cli_adjudicate_is_gated(run, monkeypatch, tmp_path, capsys):
    from ravel.workflow import research_cycle
    _campaign(monkeypatch, run)
    monkeypatch.setattr(research_cycle, "adjudicate", lambda *a: pytest.fail("adjudicated without a gate"))
    with pytest.raises(SystemExit) as exited:
        research_cycle.main(["adjudicate", "--cycle", str(tmp_path / "campaign"), "--experiment", "E1"])
    assert exited.value.code != 0
    assert "research_choice refused" in capsys.readouterr().err


def test_research_cycle_cli_diagnostic_feedback_is_gated(run, monkeypatch, tmp_path, capsys):
    from ravel.workflow import research_cycle
    _campaign(monkeypatch, run, failed_intake={"path": "failed.json", "sha256": "d" * 64})
    monkeypatch.setattr(research_cycle, "diagnostic_feedback", lambda *a, **k: pytest.fail("fed back without a gate"))
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"feedback_pin": {"path": "f.json", "sha256": "e" * 64}}))
    with pytest.raises(SystemExit) as exited:
        research_cycle.main(["diagnostic-feedback", "--cycle", str(tmp_path / "campaign"), "--experiment", "E1",
                             "--request", str(request)])
    assert exited.value.code != 0
    assert "failed_stage_feedback refused" in capsys.readouterr().err


def test_orchestrator_adjudicate_is_gated():
    """Every research_orchestrator call of cycle.adjudicate is preceded, in its function, by the gate."""
    import ast
    import inspect
    from ravel.workflow import research_orchestrator
    tree = ast.parse(inspect.getsource(research_orchestrator))
    ungated = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        calls = sorted((n.lineno, ast.unparse(n.func)) for n in ast.walk(fn) if isinstance(n, ast.Call))
        for line, name in calls:
            if name == "cycle.adjudicate" and not any(n == "gate_wiring.require_research_choice" and l <= line
                                                      for l, n in calls):
                ungated.append((fn.name, line))
    assert ungated == []



def test_research_engines_feed_back_failed_stages_only_through_the_gate():
    """Both research engines (the legacy orchestrator and the research.loop graph, which shares its
    node table) reach failed-stage feedback only through gated entry points: a direct feedback call
    is preceded, in its function, by require_failed_feedback, and the diagnose action delegates to
    research_coordinator_decisions.diagnose, which gates before any role runs."""
    import ast
    import inspect
    from ravel.workflow import research_coordinator_decisions, research_orchestrator
    from ravel.workflow.graphs import research_loop, stage
    feedback = {"attach_failed_stage", "diagnostic_feedback", "graph_feedback"}
    ungated = []
    for module in (research_orchestrator, research_loop, stage, research_coordinator_decisions):
        tree = ast.parse(inspect.getsource(module))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            calls = sorted((n.lineno, ast.unparse(n.func)) for n in ast.walk(fn) if isinstance(n, ast.Call))
            for line, name in calls:
                if name.rsplit(".", 1)[-1] in feedback and not any(
                        n.endswith("require_failed_feedback") and l <= line for l, n in calls):
                    ungated.append((module.__name__, fn.name, line))
    assert ungated == []
    source = inspect.getsource(research_orchestrator)
    assert "decisions.diagnose(" in source
    assert "require_failed_feedback" in inspect.getsource(research_coordinator_decisions.diagnose)

# ---------------------------------------------------------------- F3: production callers of P15 and PHYS-RDJ

def test_launch_authorization_runs_p15_on_a_delegated_screen(delegated_run, monkeypatch):
    from ravel.workflow import launch_authorization as la, physics_review, workflow_state as ws
    monkeypatch.setattr(ws, "verify_approval", lambda *a, **k: [])
    monkeypatch.setattr(physics_review, "active", lambda root: False)
    with pytest.raises(ValueError, match="rdj_receipt_missing|lease_missing"):
        la._capture(delegated_run.root, "smoke", command=["echo", "screen"], context={"kind": "scientific-stage"})


def test_plan_preauthorization_consults_phys_rdj(tmp_path, monkeypatch):
    from test_delegated_preauthorization import _conditions, _field, _run
    import intake_sidecar_fixtures as fx
    rd, contract, _, _ = _run(tmp_path, plan_overrides={"nodes": [fx.node(fields=[_field(authority="agent_inference")])]})
    seen = []

    def check(root, value, **kw):
        seen.append((value["name"], value["origin"], value["critical"], kw.get("delegated")))
        return []
    monkeypatch.setattr(gw, "physics_value_errors", check)
    monkeypatch.setattr(gw, "epoch_two", lambda root: True)  # an epoch-two run whose receipt authorizes
    assert ("agent_inferred_critical_field", "N1/task/pdf_set") not in _conditions(rd, contract)
    assert seen == [("N1/task/pdf_set", "agent_inferred", True, True)]
    monkeypatch.undo()
    # Without an anchored receipt (and here without epoch two) the refusal stands.
    assert ("agent_inferred_critical_field", "N1/task/pdf_set") in _conditions(rd, contract)
