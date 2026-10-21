"""R2/R3 gate wiring on delegated runs, the R3 human approval under same-user
transport, the spend_above_ceiling positive path, the review.points delegation and the
host-authored node lists.

Synthetic runs only. No tool runs; worker receipts come from the fixture dispatcher.
"""
import json
import re
import sys
from pathlib import Path

import pytest

from inert_dispatch import inert_dispatch  # noqa: F401
from rdj_fixtures import Run, prepare_case
from ravel.workflow import decision_gate as dg, gate_wiring as gw, rdj_custody as custody
from ravel.workflow import rdj_loop as rdj, run_ceilings

ROOT = Path(__file__).resolve().parents[2]
WIRING_RECORD = ROOT / "docs/reference/gate-wiring.md"


def codes(errors, provider=None):
    return [e.code for e in errors if provider is None or e.provider == provider]


def release_run(root, *, delegated):
    r = Run(root, snapshot=False, prompt=False)
    pin = r.put("inputs/plan.json", {"nodes": [{"id": "N1"}], "claims": [], "edges": []})
    contract = json.loads((r.root / "inputs/task_contract.json").read_text())
    r.put("inputs/task_contract.json", {**contract, "request_plan": pin, **({"delegated": True} if delegated else {})})
    gw.record_run_init(r.root)
    return r


@pytest.fixture
def delegated(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "custody"))
    return release_run(tmp_path / "delegated", delegated=True)


@pytest.fixture
def operator_run(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "custody"))
    return release_run(tmp_path / "operator", delegated=False)


@pytest.fixture
def lease(delegated, monkeypatch):
    from ravel.workflow import machine_lease as ml
    monkeypatch.delenv(ml.ENV, raising=False)
    held = ml.acquire("bulk", rundir=str(delegated.root), node_id="N1")
    yield held
    ml.release(held)


# ---------------------------------------------------------------- acceptance 8: the wiring record

def _record_rows():
    rows = {}
    for line in WIRING_RECORD.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\| `([a-z0-9_]+)` \| (R[0-3](?:-R[0-3])?) \| (wired|legacy) \| (.+) \|$", line)
        if match:
            rows[match.group(1)] = (match.group(2), match.group(3), match.group(4).strip())
    return rows


def test_every_gate_is_wired_or_listed_legacy_with_its_condition():
    assert set(gw.GATE_WIRING) == set(dg.GATES)
    assert set(gw.R2R3_GATES) <= set(gw.GATE_WIRING)
    rows = _record_rows()
    assert set(rows) == set(dg.GATES)
    for gate, (cls, status, reason) in gw.GATE_WIRING.items():
        assert rows[gate][:2] == (cls, status), gate
        assert reason and rows[gate][2], gate
        if status == "wired":
            assert gate in gw.WIRED_GATES


def test_record_states_same_user_transport_and_the_r3_human_requirement():
    text = WIRING_RECORD.read_text(encoding="utf-8")
    assert gw.SAME_USER_TRANSPORT and "same-user transport" in text
    assert "r3_human_approval_missing" in text


# ---------------------------------------------------------------- R2 launch (full, scan)

def test_full_launch_on_delegated_run_needs_the_r2_launch_gate(delegated, lease):
    errors = gw.launch_errors(delegated.root, "full", [sys.executable, "-c", "pass"], {"stage": "produce"})
    assert any(e.startswith("rdj:rdj_receipt_missing") for e in errors)
    assert any(e.startswith("executor:") for e in errors)  # no worker receipt or waiver for N1


def test_full_launch_action_is_r2_on_the_lease_node(delegated, lease):
    action = gw.bulk_action(delegated.root, "scan", ["x"], {"stage": "scan"})
    assert (action["kind"], action["rung"], action["node_id"], action["floor"]) == ("scan_launch", "scan", "N1", "R2")
    assert rdj.compute_class(delegated.root, "launch", action)[0] in {"R2", "R3"}


def test_full_launch_on_undelegated_or_pre_release_run_keeps_its_authorization(operator_run, tmp_path):
    assert gw.launch_errors(operator_run.root, "full", ["x"], {}) == []
    old = tmp_path / "old"
    (old / "inputs").mkdir(parents=True)
    (old / "inputs/task_contract.json").write_text(json.dumps({"prompt": "old"}))
    assert gw.launch_errors(old, "scan", ["x"], {}) == []


def test_contract_changed_after_run_init_is_refused_not_undelegated(delegated):
    contract = json.loads((delegated.root / "inputs/task_contract.json").read_text())
    contract.pop("delegated")
    delegated.put("inputs/task_contract.json", contract)
    assert "gate_inputs_invalid" in codes(gw.delegated_errors(delegated.root, "delivery", gw.delivery_action(delegated.root)))


# ---------------------------------------------------------------- R2 delegated CHECK-IN 1 and CHECK-IN 2

def test_delegated_approval_needs_the_approve_plan_gate(delegated, monkeypatch):
    from ravel.workflow import scientific_autonomy, workflow_state as ws
    monkeypatch.setattr(scientific_autonomy, "plan_authority", lambda rd, required_plan: {"value": {}})
    with pytest.raises(gw.GateRefused) as refused:
        ws.record_delegated_approval(str(delegated.root), "smoke")
    assert refused.value.gate == "approve_plan"
    assert "rdj_receipt_missing" in codes(refused.value.errors, "rdj")
    assert not (delegated.root / "inputs/checkin1_approval.json").exists()


def test_delegated_go_needs_the_checkin2_accept_gate(delegated, monkeypatch):
    from ravel.workflow import scientific_autonomy, workflow_state as ws
    monkeypatch.setattr(scientific_autonomy, "authorize", lambda rd, gate: {"value": {}})
    with pytest.raises(gw.GateRefused) as refused:
        ws.record_delegated_go(str(delegated.root))
    assert refused.value.gate == "checkin2_accept"
    assert "rdj_receipt_missing" in codes(refused.value.errors, "rdj")
    assert not (delegated.root / "inputs/checkin2_go.json").exists()


def test_approve_plan_passes_for_a_delegated_fixture_plan(delegated, monkeypatch, inert_dispatch):
    """With the real role cards and a synthetic host whose transport selection
    succeeds, an authorized R2 case for the plan clears the approve_plan gate."""
    from ravel.workflow import transport_registry
    monkeypatch.setattr(transport_registry, "select", lambda card, *a, **k: {"role": card["id"], "transport": "synthetic"})
    action = gw.plan_action(delegated.root, "smoke", write=True)
    case_id = prepare_case(delegated, "approve_plan", "plan_approval", "R2", action=action)
    assert rdj.authorize(delegated.root, case_id)["outcome"] == "authorize"
    assert gw.delegated_errors(delegated.root, "approve_plan", gw.plan_action(delegated.root, "smoke")) == []


# ---------------------------------------------------------------- R3 delivery and export

def test_result_pack_refuses_a_delegated_run_without_the_delivery_gate(delegated):
    from ravel.workflow import result_pack
    with pytest.raises(result_pack.PackError, match="decision gate refuses delivery: rdj:rdj_receipt_missing"):
        result_pack.main(["--rundir", str(delegated.root), "--stat-mode", result_pack.STAT_MODES[0],
                          "--detector-mode", result_pack.DETECTOR_MODES[0]])


def test_submission_export_refuses_a_delegated_run_without_the_export_gate(delegated, tmp_path, monkeypatch):
    from ravel.workflow import submission_export as se
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"rundir": str(delegated.root)}))
    monkeypatch.setattr(se, "validate_request", lambda value: value)
    monkeypatch.setattr(se, "_results", lambda *a: pytest.fail("exported without the export gate"))
    with pytest.raises(gw.GateRefused) as refused:
        se.export(request, tmp_path / "repo")
    assert refused.value.gate == "export" and "rdj_receipt_missing" in codes(refused.value.errors, "rdj")


def test_delivery_action_ignores_the_stamped_enforcement_record(delegated):
    delegated.put("outputs/claims/C1.json", {"id": "C1", "value": 1})
    before = gw.delivery_action(delegated.root)["digest"]
    delegated.put("outputs/claims/C1.json", {"id": "C1", "value": 1, "enforcement": {"host": "any"}})
    assert gw.delivery_action(delegated.root)["digest"] == before
    delegated.put("outputs/claims/C1.json", {"id": "C1", "value": 2})
    assert gw.delivery_action(delegated.root)["digest"] != before


def confirmed_respond(rundir, text, case_id):
    """The operator confirms exactly this case at the controller terminal (inert stand-in)."""
    from operator_capture import operator_at_terminal
    with pytest.MonkeyPatch.context() as patch:
        operator_at_terminal(patch)
        return gw.respond(rundir, text, approve=[case_id], confirm=True)


def _authorized_r3(run, gate, kind, action, *, approve):
    case_id = prepare_case(run, gate, kind, "R3", action=action)
    if approve:
        confirmed_respond(run.root, f"I approve {case_id} as presented.", case_id)
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"
    return case_id


def test_r3_gate_needs_a_recorded_human_approval_under_same_user_transport(delegated, inert_dispatch):
    action = gw.delivery_action(delegated.root, write=True)
    case_id = _authorized_r3(delegated, "delivery", "delivery", action, approve=False)
    assert rdj.authorizing_receipt(delegated.root, "delivery", action) is not None
    errors = gw.human_approval_errors(delegated.root, "delivery", action)
    assert codes(errors) == ["r3_human_approval_missing"] and errors[0].pins == (f"rdj/cases/{case_id}.json",)


def test_r3_human_approval_comes_from_the_trusted_response_path(delegated, inert_dispatch):
    action = gw.delivery_action(delegated.root, write=True)
    _authorized_r3(delegated, "delivery", "delivery", action, approve=True)
    assert gw.human_approval_errors(delegated.root, "delivery", action) == []


def test_steering_text_never_supplies_the_r3_human_approval(delegated, inert_dispatch):
    action = gw.delivery_action(delegated.root, write=True)
    case_id = prepare_case(delegated, "delivery", "delivery", "R3", action=action)
    gw.record_steering(delegated.root, f"Please approve {case_id} soon.", effect="note")
    assert rdj.authorize(delegated.root, case_id)["outcome"] == "authorize"
    assert codes(gw.human_approval_errors(delegated.root, "delivery", action)) == ["r3_human_approval_missing"]


def test_scope_change_steering_holds_delivery_until_reapproval(delegated):
    gw.record_steering(delegated.root, "Add a second signal region.", effect="scope_change", affected_nodes=["N1"])
    errors = gw.delegated_errors(delegated.root, "delivery", gw.delivery_action(delegated.root))
    assert "steering_requires_reapproval" in codes(errors, "gate_wiring")


# ---------------------------------------------------------------- acceptance 8: spend_above_ceiling end to end

def _spend_run(run):
    run.put(run_ceilings.RECORD, run_ceilings.default("analysis"))
    run_ceilings.charge(run.root, "worker", 72)  # the original ceiling is spent
    raised = {**run_ceilings.default("analysis"), "source": "checkin1_response", "max_invocations": 100}
    run.put(run_ceilings.RECORD, json.dumps(raised))
    return (run.root / run_ceilings.RECORD).read_text()


def test_spend_above_ceiling_positive_path_end_to_end(delegated, inert_dispatch):
    response = _spend_run(delegated)
    # 1. The operator's CHECK-IN 1 response, which raises the ceiling, is custody-recorded.
    assert gw.record_checkin1(delegated.root, quote=response)["response_recorded"]
    assert custody.user_text(delegated.root, "checkin1_response", custody.CI1_RESPONSE)[0] == response
    action = gw.spend_action(delegated.root, 1, write=True)
    assert codes(gw.delegated_errors(delegated.root, "spend_above_ceiling", action), "rdj") == ["rdj_receipt_missing"]
    # 2. An R3 RDJ receipt, which (irreversible) needs 3. the operator's recorded human approval.
    case_id = prepare_case(delegated, "spend_above_ceiling", "spend", "R3", action=action)
    with pytest.raises(rdj.OpenItems):
        rdj.authorize(delegated.root, case_id)
    confirmed_respond(delegated.root, f"I approve {case_id}: spend one more invocation.", case_id)
    receipt = rdj.authorize(delegated.root, case_id)
    assert receipt["outcome"] == "authorize" and receipt["class"] == "R3"
    assert receipt["attestation_summary"]["human_approver"]
    assert dg.check(delegated.root, "spend_above_ceiling", action) == []
    assert gw.delegated_errors(delegated.root, "spend_above_ceiling", action) == []


def test_spend_above_ceiling_without_the_recorded_response_is_refused(delegated):
    """A raised ceiling the operator never answered binds nothing: the gate refuses and no further
    invocation, not even an RDJ role call, can be charged."""
    _spend_run(delegated)
    action = gw.spend_action(delegated.root, 1, write=True)
    errors = gw.delegated_errors(delegated.root, "spend_above_ceiling", action)
    assert "ceiling_exceeded" in codes(errors, "ceilings") and "rdj_receipt_missing" in codes(errors, "rdj")
    with pytest.raises(run_ceilings.CeilingExceeded):
        run_ceilings.charge(delegated.root, "rdj", 1)


def test_spend_above_ceiling_on_an_impossible_fixture_is_a_gaming_event(delegated, inert_dispatch):
    response = _spend_run(delegated)
    gw.record_checkin1(delegated.root, quote=response)
    action = gw.spend_action(delegated.root, 1, write=True)
    case_id = prepare_case(delegated, "spend_above_ceiling", "spend", "R3", action=action)
    confirmed_respond(delegated.root, f"I approve {case_id}.", case_id)
    rdj.authorize(delegated.root, case_id)
    gw.register_impossible_fixture(delegated.root, "synthetic-spend", "no honest spend exists")
    assert codes(gw.delegated_errors(delegated.root, "spend_above_ceiling", action)) == ["impossible_fixture_pass"]
    assert gw.gaming_events(delegated.root)[-1]["gate"] == "spend_above_ceiling"


# ---------------------------------------------------------------- review-points delegation and the executor handoff

def test_advance_delegates_an_epoch_two_run_to_review_points(delegated, monkeypatch, tmp_path):
    from ravel.workflow import research_orchestrator, scientific_judgment as sj
    from ravel.workflow.graphs import review as review_graph
    seen = []
    monkeypatch.setattr(review_graph, "orchestrated", lambda root, claim_scope=None: seen.append((root, claim_scope)) or {"phase": "review_points"})
    monkeypatch.setattr(research_orchestrator, "review", lambda *a, **k: pytest.fail("advance bypassed review.points"))
    value = sj.advance(delegated.root, tmp_path / "out", host=None, model="m", reasoning_effort="low",
                       max_output_tokens=1, max_wall_seconds=1, claim_scope="C1")
    assert value == {"phase": "review_points"} and seen == [(delegated.root, "C1")]


def test_checkin_packet_lists_host_authored_nodes(delegated, monkeypatch):
    from ravel.workflow import production_executor
    from ravel.workflow.graphs import review as review_graph
    rows = [{"node_id": "N1", "executor": "host", "counts": False}]
    monkeypatch.setattr(production_executor, "host_authored_nodes", lambda root: rows)
    state = {"meta": {"graph_id": review_graph.POINTS, "scope_root": str(delegated.root), "instance": {"at": "checkin3"}}}
    assert review_graph._host_authored(state) == rows
