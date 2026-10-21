"""Authority boundary of the decision-justification core: each test reproduces one way a proposer could
grant itself authority (class, approval, identity, records, provenance, anchors, graph, loop, budget,
triggers, practice, gate names, dispatch) and asserts that code refuses it."""
import json
import shutil
import sys
import time

import pytest

from ravel.workflow import decision_case as dc
from ravel.workflow import evidence_queue, rdj_anchor, rdj_custody
from ravel.workflow import rdj_loop as rdj

from inert_dispatch import inert_dispatch  # noqa: F401
from rdj_fixtures import (PROMPT, PROPOSER, assigned, TOOL, Roles, Run, add, challenge, critic, critic_once, node, reviewer,
                          said, sha, two_level_r2, verifier)


@pytest.fixture(autouse=True)
def custody(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))


def anchor_row(spec, identity="a"):
    return {"id": identity, "locator": spec.get("locator", ""), "value": spec.get("value"), "quantity": None,
            "verified": None, "kind": spec["kind"], "binding": spec["binding"]}


def context(run, **extra):
    return {"rundir": str(run.root), "input_snapshot": rdj_custody.input_snapshot(run.root), "generated": [],
            "action_pins": [], **extra}


def open_items(run, case_id):
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    return refused.value.items


def codes(items):
    return {i["code"] for i in items}


def full_r2(run, roles=None, **opts):
    roles = roles or Roles()
    case_id = two_level_r2(run, roles=roles, **opts)
    rdj.run_roles(run.root, case_id, roles)
    return case_id


# ---------------------------------------------------------------- class floor

@pytest.mark.parametrize("gate,action,expected", [
    ("delivery", {"kind": "replot_retained"}, "R3"),
    ("final_task", {"kind": "smoke_launch"}, "R3"),
    ("checkin2_accept", {"kind": "dry_run"}, "R2"),
    ("checkin2_accept", {"kind": "deliver", "rung": "smoke"}, "R2"),
    ("delivery", {"kind": "read_or_index"}, "R3"),
    ("delivery", {"kind": "tuning_change"}, "R3"),
])
def test_action_kind_or_rung_cannot_lower_the_gate_class(tmp_path, gate, action, expected):
    run = Run(tmp_path / "run")
    cls, _ = rdj.compute_class(run.root, gate, {**run.action(), **action})
    assert cls == expected


def test_lowering_happens_only_through_the_gate_policy_list(tmp_path):
    run = Run(tmp_path / "run", cost={"mode": "smoke", "points": 1, "walltime_h": [0.1, 0.2]})
    cls, factors = rdj.compute_class(run.root, "launch", run.action("smoke_launch"))
    assert cls == "R0" and factors["lowered_by"] == "smoke_launch"


# ---------------------------------------------------------------- human approval

def test_a_prompt_span_is_never_a_human_approval(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "export", run.action("export_bundle", "Export the result bundle"), PROPOSER)
    start = PROMPT.index("Set")
    with pytest.raises(ValueError, match="prompt"):
        rdj_custody.record_human_approval(run.root, case_id=case_id, source="prompt",
                                          path="inputs/task_contract.json", start=start, end=start + 3, text="Set")
    assert "human_required" in codes(open_items(run, case_id))


def test_approval_needs_user_text_recorded_after_the_commit_that_names_the_case(tmp_path):
    run = Run(tmp_path / "run")
    early = run.steering("Approved; go ahead.")
    case_id = rdj.open_case(run.root, "export", run.action("export_bundle", "Export the result bundle"), PROPOSER)
    with pytest.raises(ValueError, match="names"):
        rdj_custody.record_human_approval(run.root, case_id=case_id, source="user_steering", path=early["path"],
                                          start=0, end=8, text="Approved")
    planted = run.put("inputs/user-steering/planted.txt", f"I approve {case_id}.")
    with pytest.raises(ValueError, match="recorded"):
        rdj_custody.record_human_approval(run.root, case_id=case_id, source="user_steering", path=planted["path"],
                                          start=10, end=10 + len(case_id), text=case_id)
    # Named, correctly ordered user text alone records nothing and earns no human credit.
    with pytest.raises(ValueError, match="controller capture"):
        run.approve(case_id, confirmed=False)
    assert rdj_custody.approvals(run.root, case_id, run.case(case_id)["decision_point"]["action"]["digest"]) == []
    assert "human_required" in codes(open_items(run, case_id))
    # The operator's confirmation of exactly this case at the controller terminal (inert stand-in).
    run.approve(case_id, confirmed=True)
    assert "human_required" not in codes(open_items(run, case_id))


def test_open_case_takes_no_proposer_supplied_approval(tmp_path):
    run = Run(tmp_path / "run")
    with pytest.raises(TypeError):
        rdj.open_case(run.root, "export", run.action("export_bundle"), PROPOSER, human_approval={"source": "prompt"})


def test_irreversible_action_kind_needs_a_human_under_any_gate(tmp_path):
    run = Run(tmp_path / "run")
    cls, factors = rdj.compute_class(run.root, "launch", run.action("replace_reviewed_outputs"))
    assert cls == "R3" and factors["irreversible"]
    case_id = rdj.open_case(run.root, "launch", run.action("replace_reviewed_outputs"), PROPOSER)
    assert "human_required" in codes(open_items(run, case_id))


# ---------------------------------------------------------------- identity and attestation

def test_role_identity_comes_from_a_registered_receipt_not_the_response(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))
    with pytest.raises(ValueError, match="registered"):
        rdj.run_roles(run.root, case_id, Roles(register=False))
    assert run.case(case_id)["edges"][0]["review"] is None

    class Speaks:
        def dispatch(self, rundir, request):
            return {"output": {"reviews": []}, "session": PROPOSER}
    with pytest.raises(ValueError, match="receipt"):
        rdj.run_roles(run.root, case_id, Speaks())


def test_stub_dispatcher_is_not_part_of_the_module():
    assert not hasattr(rdj, "StubDispatcher")


def test_session_identity_and_attestation_are_read_from_the_receipt(tmp_path, inert_dispatch):
    run = Run(tmp_path / "run")
    case_id = full_r2(run)
    edge = run.case(case_id)["edges"][0]
    reviewer_ = edge["review"]["reviewer"]
    # The identity is the actor the dispatcher assigned and registered, never a name the receipt states.
    node_id = reviewer_["session_receipt"] and next(
        p.parent.parent.name for p in (run.root / "agent-work").glob("*/1/receipt.json")
        if json.loads(p.read_text())["actor_id"] == reviewer_["actor_id"])
    assert reviewer_["actor_id"] == assigned("edge-reviewer", node_id)["actor_id"]
    assert reviewer_["attestation"] == "transport_attested"
    assert reviewer_["session_receipt"].startswith("fixture-transport:")


# ---------------------------------------------------------------- independence

def test_answers_have_one_author_the_proposer(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    cid = challenge(run, case_id, "why_action", "action")
    with pytest.raises(TypeError):
        rdj.answer(run.root, case_id, [{"op": "add_child", "challenge_id": cid, "parent": "action",
                                        "node": node("A", "Ready")}], author={"actor_id": "q"})


@pytest.mark.parametrize("role", ["critic", "verifier"])
def test_critic_or_verifier_equal_to_an_edge_reviewer_is_refused(tmp_path, role):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    same = {"critic": critic(name="edge-reviewer"), "verifier": verifier(name="edge-reviewer")}[role]
    with pytest.raises(rdj.IndependenceError):
        rdj.run_roles(run.root, case_id, Roles(**{role: same}))


def test_critic_equal_to_the_proposer_is_refused(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    with pytest.raises(rdj.IndependenceError):
        rdj.run_roles(run.root, case_id, Roles(critic=critic(name="proposer")))


# ---------------------------------------------------------------- the gate trusts the case

def test_gate_reads_digest_gate_and_class_from_the_case_not_the_receipt(tmp_path):
    run = Run(tmp_path / "run", cost={"mode": "full", "points": 1, "walltime_h": [0.1, 0.2]})
    case_id = rdj.open_case(run.root, "launch", run.action("single_point_launch", "Run one point"), PROPOSER)
    add(run, case_id, "action", node("ok", "Validated", anchors=[run.stage("v", "outputs/v.json", {"ok": 1})]))
    rdj.run_roles(run.root, case_id, Roles())
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["class"] == "R1"
    bulk_pin = run.put("outputs/bulk.json", {"points": 5000})
    bulk = {"kind": "bulk_launch", "digest": bulk_pin["sha256"], "summary": "Launch 5000 points", "pins": [bulk_pin]}
    forged = {**receipt, "receipt_id": receipt["receipt_id"] + "-x", "action_digest": bulk_pin["sha256"], "class": "R3"}
    (run.root / "rdj/receipts" / (forged["receipt_id"] + ".json")).write_text(json.dumps(forged))
    assert rdj.gate_errors(run.root, "launch", bulk)
    assert rdj.gate_errors(run.root, "launch", run.action("single_point_launch")) == []


def test_receipt_absent_from_custody_does_not_open_the_gate(tmp_path, inert_dispatch):
    run = Run(tmp_path / "run")
    case_id = full_r2(run)
    receipt = rdj.authorize(run.root, case_id)
    rdj_custody_root = rdj_custody.root(run.root)
    (rdj_custody_root / "receipts.jsonl").unlink()
    assert rdj.gate_errors(run.root, "launch", run.action()) and receipt["outcome"] == "authorize"


# ---------------------------------------------------------------- journal replay

def test_an_edited_verdict_in_the_case_file_is_detected(tmp_path):
    run = Run(tmp_path / "run")
    roles = Roles(edge_reviewer=reviewer({"A->B": {"entailment": "fails", "code": "decision_does_not_follow",
                                                   "reason": "the smoke stage does not show it"}}))
    case_id = full_r2(run, roles=roles)
    path = run.root / f"rdj/cases/{case_id}.json"
    case = json.loads(path.read_text())
    for edge in case["edges"]:
        if edge["id"] == "A->B":
            edge["review"].update(entailment="holds", code="no_issue")
    path.write_text(json.dumps(case))
    with pytest.raises(rdj.CaseTampered):
        rdj.authorize(run.root, case_id)
    assert [e.code for e in rdj.gate_errors(run.root, "launch", run.action())] == ["rdj_receipt_missing"]


def test_an_edited_state_file_is_detected(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    (run.root / "outputs/plan.json").write_text(json.dumps({"points": 300}))
    with pytest.raises(rdj.CaseInvalidated):
        rdj.next_challenges(run.root, case_id)
    run.put("outputs/plan.json", {"points": 3})
    path = run.root / f"rdj/state/{case_id}.json"
    state = json.loads(path.read_text())
    state["invalidated"] = None
    path.write_text(json.dumps(state))
    with pytest.raises(rdj.CaseTampered):
        rdj.next_challenges(run.root, case_id)


def test_a_rewritten_run_journal_is_detected(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    journal = run.root / f"rdj/journal/{case_id}.jsonl"
    lines = journal.read_text().splitlines()
    first = json.loads(lines[0])
    first["record"]["data"]["class"] = "R0"
    journal.write_text("\n".join([json.dumps(first)] + lines[1:]) + "\n")
    with pytest.raises(rdj.CaseTampered):
        rdj.next_challenges(run.root, case_id)


# ---------------------------------------------------------------- input provenance

def test_input_planted_after_the_run_init_snapshot_is_generated(tmp_path):
    run = Run(tmp_path / "run")
    planted = run.put("inputs/notes/plan-notes.json", {"checked": True})  # before open_case, after run init
    rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    anchor = anchor_row({"kind": "input_artifact", "binding": planted, "locator": "/checked"})
    assert rdj_anchor.verify(anchor, run.root, context=context(run)) == "generated"


def test_ravel_written_inputs_are_never_external_input_artifacts(tmp_path):
    run = Run(tmp_path / "run", extra_inputs=[("inputs/request.json", {"prompt": PROMPT})])
    for rel in ("inputs/request.json", "inputs/task_contract.json", "inputs/cost_preflight.json"):
        anchor = anchor_row({"kind": "input_artifact", "binding": run.pin(rel)})
        assert rdj_anchor.verify(anchor, run.root, context=context(run)) == "generated", rel
    settings = anchor_row({"kind": "input_artifact", "binding": run.pin("inputs/cards/settings.json")})
    assert rdj_anchor.verify(settings, run.root, context=context(run)) == "external"


def test_without_a_ravel_snapshot_no_input_is_external(tmp_path):
    run = Run(tmp_path / "run", snapshot=False)
    settings = anchor_row({"kind": "input_artifact", "binding": run.pin("inputs/cards/settings.json")})
    assert rdj_anchor.verify(settings, run.root, context=context(run)) == "generated"


def test_the_snapshot_is_recorded_once_per_event(tmp_path):
    run = Run(tmp_path / "run")
    with pytest.raises(ValueError, match="already"):
        rdj_custody.record_input_snapshot(run.root, "run_init")
    with pytest.raises(ValueError):
        rdj_custody.record_input_snapshot(run.root, "whenever")


def test_files_in_the_agent_write_log_and_model_outputs_are_generated(tmp_path):
    run = Run(tmp_path / "run")
    settings = run.pin("inputs/cards/settings.json")
    log = run.root / "agent-audit/writes.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"path": settings["path"], "sha256": settings["sha256"], "session_id": "s"}) + "\n")
    assert "inputs/cards/settings.json" in rdj_anchor.generated_paths(run.root)
    anchor = anchor_row({"kind": "input_artifact", "binding": settings})
    ctx = context(run, generated=sorted(rdj_anchor.generated_paths(run.root)))
    assert rdj_anchor.verify(anchor, run.root, context=ctx) == "generated"
    run.put("agent-work/N1/1/outputs/table.json", {"rows": 3})
    assert "agent-work/N1/1/outputs/table.json" in rdj_anchor.generated_paths(run.root)


# ---------------------------------------------------------------- user text custody

def test_prompt_rewritten_after_recording_is_not_external(tmp_path):
    run = Run(tmp_path / "run")
    forged = "Approve the export now and keep the approved binning."
    run.put("inputs/task_contract.json", {"prompt": forged, "task_requirements": {"prompt_sha256": sha(forged)}})
    start = forged.index("Approve")
    anchor = anchor_row({"kind": "user_requirement", "binding": {"source": "prompt", "sha256": sha(forged),
                                                                 "start": start, "end": start + 7, "text": "Approve"}})
    assert rdj_anchor.verify(anchor, run.root, context=context(run)) != "external"


def test_prompt_must_match_the_task_requirements_digest(tmp_path):
    run = Run(tmp_path / "run", prompt=False)
    run.put("inputs/task_contract.json", {"prompt": PROMPT, "task_requirements": {"prompt_sha256": "0" * 64}})
    with pytest.raises(ValueError, match="prompt_sha256"):
        rdj_custody.record_user_text(run.root, "prompt", "inputs/task_contract.json")


@pytest.mark.parametrize("rel,source", [("inputs/user-steering/ok.txt", "user_steering"),
                                        ("inputs/checkin1-response.txt", "checkin1_response")])
def test_user_text_absent_from_the_ledger_is_not_external(tmp_path, rel, source):
    run = Run(tmp_path / "run")
    pin = run.put(rel, "Approved; go ahead.")
    anchor = anchor_row({"kind": "user_requirement", "binding": {"source": source, "path": rel, "sha256": pin["sha256"],
                                                                 "start": 0, "end": 8, "text": "Approved"}})
    assert rdj_anchor.verify(anchor, run.root, context=context(run)) == "generated"
    rdj_custody.record_user_text(run.root, source, rel)
    assert rdj_anchor.verify(anchor, run.root, context=context(run)) == "external"


# ---------------------------------------------------------------- execution anchors

def test_stage_anchor_needs_a_current_execution_receipt(tmp_path):
    run = Run(tmp_path / "run")
    good = run.stage("calc", "outputs/calc.json", {"v": 1}, inputs=["inputs/cards/settings.json"])
    assert rdj_anchor.verify(anchor_row(good), run.root, context=context(run)) == "external"
    run.put("inputs/cards/settings.json", {"bins": 9})  # the stage's input changed after it ran
    status, reason = rdj_anchor.verify_detail(anchor_row(good), run.root, context=context(run))
    assert status == "invalid" and "inputs changed" in reason


def test_a_hand_written_ledger_row_is_not_a_receipt(tmp_path):
    run = Run(tmp_path / "run")
    pin = run.put("outputs/forged.json", {"v": 1})
    (run.root / "execution_state.json").write_text(json.dumps({"schema_version": 1, "revision": 1, "stages": {
        "forged": {"status": "succeeded", "attempt_id": "a1", "command": TOOL,
                   "output_snapshot": {str((run.root / pin["path"]).resolve()): {"kind": "file", "files": [
                       {"name": ".", "size": 8, "sha256": pin["sha256"]}]}}}}}))
    anchor = anchor_row({"kind": "tool_output", "binding": {"receipt_id": "stage:forged:a1",
                                                            "output_path": pin["path"], "sha256": pin["sha256"]}})
    assert rdj_anchor.verify(anchor, run.root, context=context(run)) == "invalid"


@pytest.mark.parametrize("command", [
    [sys.executable, "evil/certify_acceptance.py"],
    [sys.executable, "my_script.py", "--tag", "certify_acceptance"],
    [sys.executable, "-c", "print(1)", "certify_acceptance"],
])
def test_validator_identity_is_the_resolved_module_not_an_argv_token(tmp_path, command):
    run = Run(tmp_path / "run")
    anchor = run.stage("cert", "outputs/cert.json", {"pass": True}, command, kind="measurement")
    assert rdj_anchor.verify(anchor_row(anchor), run.root, context=context(run)) == "invalid"


def test_registered_validator_with_its_digest_is_a_measurement(tmp_path):
    run = Run(tmp_path / "run")
    anchor = run.stage("cert", "outputs/cert.json", {"pass": True}, kind="measurement")
    assert rdj_anchor.verify(anchor_row(anchor), run.root, context=context(run)) == "external"
    anchor["binding"]["validator_sha256"] = "0" * 64
    assert rdj_anchor.verify(anchor_row(anchor), run.root, context=context(run)) == "invalid"


@pytest.mark.parametrize("command", [["ravel", "agent-cli", "--role", "x"], ["claude", "-p", "summarize"],
                                     ["codex", "exec", "x"], [sys.executable, "-m", "ravel.workflow.agent_worker"]])
def test_only_a_recognized_tool_producer_makes_a_tool_output(tmp_path, command):
    run = Run(tmp_path / "run")
    anchor = run.stage("summary", "outputs/summary.json", {"ok": 1}, command)
    assert rdj_anchor.verify(anchor_row(anchor), run.root, context=context(run)) == "generated"


def test_authored_script_needs_its_digest_which_reviewers_see(tmp_path):
    run = Run(tmp_path / "run")
    script = run.put("inputs/scripts/tool.py", "print('fixture, never run')\n")
    command = [sys.executable, script["path"]]
    bare = run.stage("auth", "outputs/auth.json", {"v": 2}, command, inputs=[script["path"]])
    assert rdj_anchor.verify(anchor_row(bare), run.root, context=context(run)) == "invalid"
    bound = {**bare, "binding": {**bare["binding"], "script_sha256": script["sha256"]}}
    status, _, observed = rdj_anchor.verify_full(anchor_row(bound), run.root, context=context(run))
    assert status == "external"
    assert rdj_anchor.describe({**anchor_row(bound), "verified": status}, observed)["script_sha256"] == script["sha256"]


def test_stage_whose_outputs_include_the_action_bytes_is_circular(tmp_path):
    run = Run(tmp_path / "run")
    own = run.stage("result", "outputs/plan.json", {"points": 3})
    status, reason = rdj_anchor.verify_detail(anchor_row(own), run.root,
                                              context=context(run, action_pins=[run.action_pin]))
    assert status == "invalid" and "circular" in reason


# ---------------------------------------------------------------- broker and retrieval receipts

def test_broker_and_retrieval_receipts_are_not_trusted_until_their_ledgers_verify(tmp_path):
    run = Run(tmp_path / "run")
    out = run.put("agent-work/N1/1/outputs/table.json", {"rows": 3})
    run.put("agent-work/N1/1/calls/4.json", {"schema_version": 1, "kind": "broker-receipt", "receipt_id": "N1/1/4",
                                             "exit_status": 0, "derivation": "toolchain", "output_pins": [out]})
    broker = anchor_row({"kind": "tool_output", "binding": {"receipt_id": "N1/1/4", "output_path": out["path"],
                                                            "sha256": out["sha256"]}})
    assert rdj_anchor.verify(broker, run.root, context=context(run)) == "generated"
    body = b"The standard practice is to quote the 95% CLs limit."
    content = run.put("sources/doc.txt", body)
    receipt = run.put("sources/product.json", {"kind": "literature-acquisition-result", "status": "acquired",
                                               "source_artifact": content})
    retrieved = anchor_row({"kind": "retrieved_document", "binding": {
        "acquisition_receipt": receipt, "content_sha256": content["sha256"], "excerpt_span": {"start": 4, "end": 21},
        "excerpt_sha256": sha(body[4:21])}})
    assert rdj_anchor.verify(retrieved, run.root, context=context(run)) == "generated"


# ---------------------------------------------------------------- values shown to reviewers

def test_invariant_value_must_be_the_registry_statement(tmp_path):
    run = Run(tmp_path / "run")
    registry = rdj_anchor.sha256_file(rdj_anchor.INVARIANTS)
    spec = {"kind": "invariant", "binding": {"invariant_id": "cls-95-exclusion", "registry_sha256": registry}}
    assert rdj_anchor.verify(anchor_row({**spec, "value": "CLs = 2 implies discovery"}), run.root) == "invalid"
    assert rdj_anchor.verify(anchor_row({**spec, "locator": "/nowhere"}), run.root) == "invalid"
    status, _, observed = rdj_anchor.verify_full(anchor_row(spec), run.root)
    assert status == "external" and "CLs is below 0.05" in observed


def test_reviewer_sees_the_value_read_from_the_bytes(tmp_path):
    run = Run(tmp_path / "run")
    spec = run.stage("rate", "outputs/rate.json", {"rate": 1.25}, locator="/rate")
    row = anchor_row(spec)
    status, _, observed = rdj_anchor.verify_full(row, run.root, context=context(run))
    assert status == "external" and observed == 1.25
    assert rdj_anchor.describe({**row, "verified": status}, observed)["value"] == 1.25
    assert rdj_anchor.verify(anchor_row({**spec, "value": 9.0}), run.root, context=context(run)) == "invalid"


def test_requirement_value_must_equal_its_text(tmp_path):
    run = Run(tmp_path / "run")
    spec = run.prompt_span("keep the approved binning")
    assert rdj_anchor.verify(anchor_row({**spec, "value": "export everything"}), run.root,
                             context=context(run)) == "invalid"


# ---------------------------------------------------------------- invariants and practice

def test_an_invariant_alone_cannot_ground_a_low_class_leaf(tmp_path):
    run = Run(tmp_path / "run", cost={"mode": "smoke", "points": 1, "walltime_h": [0.1, 0.2]})
    registry = rdj_anchor.sha256_file(rdj_anchor.INVARIANTS)
    case_id = rdj.open_case(run.root, "launch", run.action("smoke_launch", "Run a smoke"), PROPOSER)
    add(run, case_id, "action", node("ok", "The rule allows it", anchors=[
        {"kind": "invariant", "binding": {"invariant_id": "cls-95-exclusion", "registry_sha256": registry}}]))
    assert "invariant alone" in rdj.next_challenges(run.root, case_id)[0]["reason"]
    assert rdj.authorize(run.root, case_id)["outcome"] == "gather_evidence"
    assert rdj.gate_errors(run.root, "launch", run.action("smoke_launch"))


def test_practice_authority_is_never_read_from_the_binding(tmp_path):
    run = Run(tmp_path / "run")
    registry = rdj_anchor.sha256_file(rdj_anchor.INVARIANTS)
    not_practice = {"id": "i", "kind": "invariant", "locator": "", "value": None, "quantity": None,
                    "verified": None, "binding": {"invariant_id": "one-native-job", "registry_sha256": registry}}
    case = {"nodes": [{"id": "action", "anchors": [], "recommends_choice": False},
                      {"id": "c", "anchors": ["i"], "recommends_choice": True}],
            "edges": [{"parent": "action", "child": "c", "relation": "supports"}], "anchors": [not_practice]}
    assert rdj_anchor.exploratory_nodes(case, {"i": "external"}) == ["c"]


def test_root_choice_is_derived_from_the_action_kind_and_recorded_at_r1(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen variant B"), PROPOSER)
    assert run.case(case_id)["nodes"][0]["recommends_choice"] is True
    add(run, case_id, "action", node("P", "Variant B had the higher rate",
                                     anchors=[run.stage("m1", "outputs/m1.json", {"rate": 1.0})]))
    rdj.run_roles(run.root, case_id, Roles())
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize" and receipt["exploratory"] == ["action"]


def test_critic_can_mark_an_unmarked_choice(tmp_path):
    run = Run(tmp_path / "run")
    finding = {"id": "F1", "code": "unmarked_choice", "targets": ["B"], "materiality": "B",
               "evidence_class": "code_check", "evidence_locators": [run.check_result("probe")], "request": None}
    case_id = two_level_r2(run)
    rdj.run_roles(run.root, case_id, Roles(critic=critic([finding])))
    assert "B" in rdj.status(run.root, case_id)["exploratory"]


@pytest.mark.parametrize("code", ["unmarked_choice", "circular_justification", "irrelevant_support",
                                  "post_hoc_rationalization"])
def test_taxonomy_has_codes_for_reasoning_faults(code):
    assert code in dc.CRITIQUE_CODES


# ---------------------------------------------------------------- graph semantics

def test_rules_out_cannot_support_the_action(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    with pytest.raises(ValueError, match="rules_out"):
        add(run, case_id, "action", node("R", "Evidence against launching"), relation="rules_out")


def test_review_code_must_agree_with_its_verdict(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))
    contradicting = reviewer({"action->A": {"code": "contradiction"}})
    with pytest.raises(ValueError, match="code"):
        rdj.run_roles(run.root, case_id, Roles(edge_reviewer=contradicting))
    silent = reviewer({"action->A": {"entailment": "fails"}})
    with pytest.raises(ValueError, match="code"):
        rdj.run_roles(run.root, case_id, Roles(edge_reviewer=silent))


def test_generated_only_on_an_inner_hop_keeps_the_branch_open(tmp_path):
    run = Run(tmp_path / "run")
    roles = Roles(edge_reviewer=reviewer({"action->A": {"grounding": "generated_only", "entailment": "partial",
                                                        "code": "self_grounding"}}))
    case_id = full_r2(run, roles=roles)
    assert "branch_open" in codes(open_items(run, case_id))


def test_a_nonmaterial_claim_cannot_support_a_material_one(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    with pytest.raises(ValueError, match="material"):
        add(run, case_id, "action", node("A", "Side remark", material=False))


def test_a_material_unknown_is_queued_at_once_and_holds_the_branch(tmp_path):
    run = Run(tmp_path / "run")
    request = {"kind": "experiment", "description": "Compare variants A and B on the held-out sample"}
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen B"), PROPOSER)
    add(run, case_id, "action", node("A", "The variants differ", anchors=[run.stage("x", "outputs/x.json", {"v": 1})],
                                     unknowns=[{"question": "Do they differ on held-out data?", "request": request}]))
    assert [(i["source"], i["target"]) for i in evidence_queue.items(run.root, case_id=case_id)] == [("node_unknown", "A")]
    rdj.run_roles(run.root, case_id, Roles())
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "gather_evidence"


def test_a_free_text_assumption_on_a_material_node_blocks(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen B"), PROPOSER)
    add(run, case_id, "action", node("P", "B is better", anchors=[run.stage("m", "outputs/m.json", {"r": 1})],
                                     assumptions=["the detector response is linear"]))
    rdj.run_roles(run.root, case_id, Roles())
    assert "assumption_open" in codes(open_items(run, case_id))


def test_adding_a_premise_invalidates_every_ancestor_review(tmp_path):
    run = Run(tmp_path / "run")
    roles = Roles()
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))
    rdj.run_roles(run.root, case_id, roles)
    assert run.case(case_id)["edges"][0]["review"] is not None
    add(run, case_id, "A", node("B", "Checked", anchors=[run.stage("s", "outputs/s.json", {"ok": 1})]))
    edges = {e["id"]: e["review"] for e in run.case(case_id)["edges"]}
    assert edges["action->A"] is None


# ---------------------------------------------------------------- loop integrity

def test_a_blocking_verdict_survives_an_anchor_flip_and_a_new_reviewer(tmp_path):
    run = Run(tmp_path / "run")
    failing = reviewer({"A->B": {"entailment": "fails", "code": "decision_does_not_follow",
                                 "reason": "a completed smoke stage does not show physics correctness"}})
    case_id = two_level_r2(run)
    rdj.run_roles(run.root, case_id, Roles(edge_reviewer=failing))
    smoke = run.root / "outputs/smoke.json"
    original = smoke.read_bytes()
    smoke.write_text("{}")
    rdj.next_challenges(run.root, case_id)
    smoke.write_bytes(original)
    log = []
    roles = Roles(edge_reviewer=reviewer(log=log, name="other-reviewer"))
    rdj.run_roles(run.root, case_id, roles)
    assert not any("A->B" in batch for batch in log)
    items = open_items(run, case_id)
    assert any(i["code"] == "edge_blocked" and i["target"] == "A->B" for i in items)


def test_reviews_per_edge_are_capped(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    policy = rdj_anchor.policy()
    policy["budgets"]["max_reviews_per_edge"] = 1
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))
    rdj.run_roles(run.root, case_id, Roles())
    add(run, case_id, "A", node("B", "Checked", anchors=[run.stage("s", "outputs/s.json", {"ok": 1})]))
    rdj.run_roles(run.root, case_id, Roles())
    assert rdj.status(run.root, case_id)["phase"] == "budget_exhausted"


def test_the_verifier_cannot_resolve_a_finding_no_revision_addressed(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    policy = rdj_anchor.policy()
    policy["classes"]["R2"]["revision_rounds"] = 1
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    findings = [{"id": f"F{i}", "code": "missing_evidence", "targets": ["B"], "materiality": "A",
                 "evidence_class": "code_check", "evidence_locators": [run.check_result("probe")], "request": None} for i in (1, 2)]
    case_id = two_level_r2(run)
    roles = Roles(critic=critic_once(findings))
    rdj.run_roles(run.root, case_id, roles)
    rdj.answer(run.root, case_id, [{"op": "attach_anchor", "node_id": "B", "addresses": ["F1"],
                                    "anchor": run.stage("more", "outputs/more.json", {"events": 200})}])
    with pytest.raises(ValueError, match="revision"):
        rdj.run_roles(run.root, case_id, roles)


def test_a_b_finding_with_a_failed_repair_blocks_authorization(tmp_path):
    run = Run(tmp_path / "run")
    finding = {"id": "F1", "code": "missing_evidence", "targets": ["B"], "materiality": "B",
               "evidence_class": "code_check", "evidence_locators": [run.check_result("probe")], "request": None}
    case_id = two_level_r2(run)
    once = critic_once([finding])
    rdj.run_roles(run.root, case_id, Roles(critic=once))
    rdj.answer(run.root, case_id, [{"op": "attach_anchor", "node_id": "B", "addresses": ["F1"],
                                    "anchor": run.stage("more", "outputs/more.json", {"events": 200})}])
    rdj.run_roles(run.root, case_id, Roles(critic=once, verifier=verifier(resolved="no")))
    assert any(i["code"] == "finding_open" and i["target"] == "F1" for i in open_items(run, case_id))


def test_duplicate_review_rows_are_rejected(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))

    def twice(payload):
        row = {"edge_id": "action->A", "entailment": "fails", "relevance": "relevant", "grounding": "anchored",
               "code": "unsupported_claim", "reason": "no", "request": None}
        return said({"reviews": [row, {**row, "entailment": "holds", "code": "no_issue", "reason": "yes"}]}, "r")
    with pytest.raises(ValueError, match="duplicate"):
        rdj.run_roles(run.root, case_id, Roles(edge_reviewer=twice))


def test_duplicate_verifier_rows_are_rejected():
    reviewer_ = {"actor_id": "v", "session_receipt": "s", "attestation": "transport_attested"}
    findings = [{"id": "F1", "code": "missing_evidence", "targets": ["B"], "materiality": "C"}]
    rows = [{"finding_id": "F1", "resolved": "no", "reason": "x"}, {"finding_id": "F1", "resolved": "yes", "reason": "y"}]
    with pytest.raises(ValueError, match="duplicate"):
        dc.verification({"reviewer": reviewer_, "per_finding": rows, "outcome": "authorize"}, findings, set())


def test_a_finding_without_targets_is_rejected(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    finding = {"id": "F1", "code": "missing_evidence", "targets": [], "materiality": "A", "evidence_locators": [],
               "evidence_class": "code_check", "request": None}
    with pytest.raises(ValueError, match="target"):
        rdj.run_roles(run.root, case_id, Roles(critic=critic([finding])))


def test_the_critic_reruns_on_the_revision_and_the_verifier_sees_before_and_after(tmp_path):
    run = Run(tmp_path / "run")
    finding = {"id": "F1", "code": "missing_evidence", "targets": ["B"], "materiality": "A",
               "evidence_class": "code_check", "evidence_locators": [run.check_result("probe")], "request": None}
    seen = {}

    def critic_(payload):
        seen.setdefault("critic", []).append(payload)
        return said({"findings": [] if len(seen["critic"]) > 1 else [finding]}, "critic")

    def verifier_(payload):
        seen["verifier"] = payload
        return verifier()(payload)
    case_id = two_level_r2(run)
    rdj.run_roles(run.root, case_id, Roles(critic=critic_, verifier=verifier_))
    rdj.answer(run.root, case_id, [{"op": "revise_node", "node_id": "B", "addresses": ["F1"],
                                    "fields": {"assertion": "The smoke stage completed with 100 events"}}])
    rdj.run_roles(run.root, case_id, Roles(critic=critic_, verifier=verifier_))
    assert len(seen["critic"]) == 2 and seen["critic"][1]["diff"]
    change = seen["verifier"]["revisions"][0]["diff"][0]
    assert change["before"]["assertion"] == "The smoke stage completed with output"
    assert change["after"]["assertion"] == "The smoke stage completed with 100 events"


# ---------------------------------------------------------------- budgets

def test_rejected_calls_are_charged(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))
    for _ in range(3):
        with pytest.raises(ValueError):
            rdj.run_roles(run.root, case_id, Roles(register=False))
    assert rdj.status(run.root, case_id)["usage"]["model_calls"] == 3


def test_failing_dispatch_is_charged(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))

    class Broken:
        def dispatch(self, rundir, request):
            raise RuntimeError("transport down")
    with pytest.raises(RuntimeError):
        rdj.run_roles(run.root, case_id, Broken())
    assert rdj.status(run.root, case_id)["usage"]["model_calls"] == 1


def test_new_cases_for_one_action_are_capped(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    policy = rdj_anchor.policy()
    policy["budgets"]["max_cases_per_action"] = 2
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    with pytest.raises(ValueError, match="cases"):
        rdj.open_case(run.root, "launch", run.action(), PROPOSER)


def test_an_escalated_action_needs_a_recorded_reopen_before_a_new_case(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    policy = rdj_anchor.policy()
    policy["classes"]["R2"]["max_model_calls"] = 1
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    case_id = two_level_r2(run)
    rdj.run_roles(run.root, case_id, Roles())
    assert rdj.authorize(run.root, case_id)["outcome"] == "escalate"
    with pytest.raises(ValueError, match="escalat"):
        rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    run.steering(f"Try again on {run.action_pin['sha256'][:12]} with a smaller grid.")
    with pytest.raises(ValueError, match="escalat"):  # steering that mentions the action decides nothing
        rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    run.reopen(run.action_pin["sha256"])
    rdj.open_case(run.root, "launch", run.action(), PROPOSER)


def test_per_run_model_call_budget(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    policy = rdj_anchor.policy()
    policy["budgets"]["max_model_calls_per_run"] = 1
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    case_id = two_level_r2(run)
    rdj.run_roles(run.root, case_id, Roles())
    assert rdj.status(run.root, case_id)["phase"] == "budget_exhausted"
    assert rdj.run_status(run.root)["budget"]["max_model_calls_per_run"] == 1


# ---------------------------------------------------------------- triggers

def test_class_facts_come_from_the_cost_record(tmp_path):
    run = Run(tmp_path / "run", cost={"mode": "scan", "points": 5000, "walltime_h": [10.0, 20.0]})
    cls, factors = rdj.compute_class(run.root, "launch", run.action(), facts={"points": 1, "walltime_hours": 0})
    assert cls == "R3" and set(factors["high_consequence"]) >= {"points", "walltime"}


def test_a_missing_cost_record_raises_a_consequence_gate(tmp_path):
    run = Run(tmp_path / "run", cost=None)
    cls, factors = rdj.compute_class(run.root, "launch", run.action())
    assert cls == "R3" and factors["consequence_unknown"]


def test_a_caller_cannot_declare_its_route_catalogued(tmp_path):
    run = Run(tmp_path / "run")
    cls, factors = rdj.compute_class(run.root, "research_choice", run.action("screening_choice"),
                                     facts={"route": "unseen-method", "route_catalogued": True})
    assert cls == "R2" and factors["novelty"]


def test_root_low_confidence_deepens_every_branch(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen B"),
                            {**PROPOSER, "confidence": "low"})
    add(run, case_id, "action", node("P", "B had the higher rate", anchors=[run.stage("m", "outputs/m.json", {"r": 1})]))
    rdj.run_roles(run.root, case_id, Roles())
    reasons = {c["target"]: c["reason"] for c in rdj.next_challenges(run.root, case_id)}
    assert "depth 2" in reasons.get("P", "")


def test_a_trigger_at_r0_raises_the_case_to_r1(tmp_path):
    run = Run(tmp_path / "run", cost={"mode": "smoke", "points": 1, "walltime_h": [0.1, 0.2]})
    case_id = rdj.open_case(run.root, "launch", run.action("smoke_launch", "Run a smoke"), PROPOSER)
    one = run.stage("m1", "outputs/m1.json", {"rate": 1.0}, locator="/rate")
    two = run.stage("m2", "outputs/m2.json", {"rate": 9.0}, locator="/rate")
    add(run, case_id, "action", node("P", "The rate is known", anchors=[one, two]))
    assert run.case(case_id)["risk"]["class"] == "R1"
    assert "trigger_at_r0" in run.case(case_id)["risk"]["computed_factors"]


def test_confidence_can_only_decrease(tmp_path):
    run = Run(tmp_path / "run")
    finding = {"id": "F1", "code": "unsupported_claim", "targets": ["B"], "materiality": "A",
               "evidence_class": "code_check", "evidence_locators": [run.check_result("probe")], "request": None}
    case_id = two_level_r2(run)
    rdj.run_roles(run.root, case_id, Roles(critic=critic([finding])))
    with pytest.raises(ValueError, match="confidence"):
        rdj.answer(run.root, case_id, [{"op": "revise_node", "node_id": "B", "addresses": ["F1"],
                                        "fields": {"confidence": "high"}}])


def test_a_conflict_is_found_without_a_quantity_label(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen B"), PROPOSER)
    one = run.stage("m1", "outputs/m1.json", {"rate": 1.0}, locator="/rate")
    two = run.stage("m2", "outputs/m2.json", {"rate": 1.4}, locator="/rate")
    add(run, case_id, "action", node("P", "B is faster", anchors=[one]), node("Q", "Re-measured", anchors=[two]))
    rdj.run_roles(run.root, case_id, Roles())
    reasons = {c["target"]: c["reason"] for c in rdj.next_challenges(run.root, case_id)}
    assert all("depth 2" in reasons[t] for t in ("P", "Q"))


def test_weak_relevance_deepens_the_branch(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen B"), PROPOSER)
    add(run, case_id, "action", node("P", "B is faster", anchors=[run.stage("m", "outputs/m.json", {"r": 1})]))
    rdj.run_roles(run.root, case_id, Roles(edge_reviewer=reviewer({"action->P": {"relevance": "weak",
                                                                                 "code": "irrelevant_support"}})))
    reasons = {c["target"]: c["reason"] for c in rdj.next_challenges(run.root, case_id)}
    assert "depth 2" in reasons.get("P", "")


# ---------------------------------------------------------------- gate names and the case reader

@pytest.mark.parametrize("gate", ["bulk", "check-in-2", "made_up_gate"])
def test_gate_names_fail_closed(tmp_path, gate):
    run = Run(tmp_path / "run")
    errors = rdj.gate_errors(run.root, gate, run.action())
    assert errors and errors[0].code in ("rdj_unknown_gate", "rdj_receipt_missing")
    if gate == "made_up_gate":
        assert errors[0].code == "rdj_unknown_gate"


@pytest.mark.parametrize("alias,canonical", [("bulk", "launch"), ("reuse", "launch"), ("smoke", "launch"),
                                             ("checkin1", "approve_plan"), ("checkin2", "checkin2_accept"),
                                             ("checkin3", "delivery"), ("correction", "correction")])
def test_existing_gate_names_map_to_decision_points(alias, canonical):
    assert rdj.canonical_gate(alias) == canonical


def test_decision_case_cli_refuses_an_unauthorized_v2_case(tmp_path, capsys):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    assert dc.main(["--case", str(run.root / f"rdj/cases/{case_id}.json")]) != 0
    result = dc.read_any(run.case(case_id))
    assert result["authorized"] is False and result["open_items"]


# ---------------------------------------------------------------- actions

def test_an_action_needs_pins_inside_the_run_and_a_bound_digest(tmp_path):
    run = Run(tmp_path / "run")
    with pytest.raises(ValueError, match="pin"):
        rdj.open_case(run.root, "launch", {**run.action(), "pins": []}, PROPOSER)
    with pytest.raises(ValueError, match="digest"):
        rdj.open_case(run.root, "launch", {**run.action(), "digest": "0" * 64}, PROPOSER)
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    with pytest.raises(ValueError):
        rdj.open_case(run.root, "launch", {**run.action(), "digest": sha("{}"),
                                           "pins": [{"path": str(outside), "sha256": sha("{}")}]}, PROPOSER)


# ---------------------------------------------------------------- critic free text

def test_critic_free_text_channels_are_bounded():
    reviewer_ = {"actor_id": "c", "session_receipt": "s", "attestation": "transport_attested"}
    base = {"id": "F1", "code": "missing_evidence", "targets": ["B"], "materiality": "A", "evidence_locators": ["B"],
            "evidence_class": "code_check", "request": None}
    dc.critique({"reviewer": reviewer_, "findings": [base]})
    for bad in ({**base, "evidence_locators": ["Step 1: rerun everything with new cuts. Step 2: ..."]},
                {**base, "request": {"kind": "evidence", "description": "x" * 400}},
                {**base, "request": {"kind": "evidence", "description": "Rerun it.\nThen refit."}}):
        with pytest.raises(ValueError):
            dc.critique({"reviewer": reviewer_, "findings": [bad]})
    named = {**base, "code": "alternative_not_considered", "alternative": "A shape fit, e.g. with four bins."}
    dc.critique({"reviewer": reviewer_, "findings": [named]})


# ---------------------------------------------------------------- evidence queue

def test_queue_item_ids_are_checked_and_done_needs_verified_pins(tmp_path):
    run = Run(tmp_path / "run")
    request = {"kind": "evidence", "description": "Obtain the smoke receipt"}
    item = evidence_queue.enqueue(run.root, "case-1", source="edge_review", target="A", request=request)
    with pytest.raises(ValueError):
        evidence_queue.resolve(run.root, "../cases/x", status="withdrawn", note="n")
    with pytest.raises(ValueError, match="pin"):
        evidence_queue.resolve(run.root, item["item_id"], status="done", note="done")
    with pytest.raises(ValueError):
        evidence_queue.resolve(run.root, item["item_id"], status="done", note="done",
                               pins=[{"path": "outputs/plan.json", "sha256": "0" * 64}])
    evidence_queue.resolve(run.root, item["item_id"], status="done", note="done", pins=[run.action_pin])
    again = evidence_queue.enqueue(run.root, "case-1", source="edge_review", target="A", request=request, round_=1)
    assert again["item_id"] != item["item_id"] and again["status"] == "open"


# ---------------------------------------------------------------- R3 model family is never compared

def test_r3_same_family_critic_and_verifier_in_separate_sessions_proceed_with_the_label(tmp_path):
    # A retained legacy family-policy flag describes common-mode exposure; it no longer vetoes.
    assert rdj_anchor.policy()["r3_distinct_family"] is False  # the shipped flag stays off
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run, gate="delivery", kind="deliver_claims")
    rdj.run_roles(run.root, case_id, Roles())
    add(run, case_id, "B", node("C", "The validator certified it",
                                anchors=[run.stage("cert", "outputs/cert.json", {"pass": True}, kind="measurement")]))
    roles = Roles(critic=critic(family="family-a"), verifier=verifier(family="family-a"))
    result = rdj.run_roles(run.root, case_id, roles)
    assert result["case_id"] == case_id
    state = json.loads(rdj._state_path(run.root, case_id).read_text())
    rows = state["verifier_family_relationships"]
    assert rows and all(row["relationship"] == "same" and row["label"] == "separate session, same model family"
                        for row in rows)
    assert run.case(case_id)["verification"]["outcome"] == "authorize"


# ---------------------------------------------------------------- bounded work

def test_a_wide_dag_is_refused_quickly():
    layers, width = 40, 2
    author = {"actor_id": "p", "session_receipt": "s", "attestation": "self_attested"}
    nodes = [{"id": "action", "kind": "action", "assertion": "Act", "rationale": "r", "material": True, "round": 0,
              "author": author, "confidence": None, "anchors": [], "assumptions": [], "unknowns": [],
              "recommends_choice": False}]
    edges = []
    previous = ["action"]
    for layer in range(layers):
        current = [f"n{layer}-{i}" for i in range(width)]
        for identity in current:
            nodes.append({**nodes[0], "id": identity, "kind": "claim"})
            for parent in previous:
                edges.append({"id": f"{parent}->{identity}", "parent": parent, "child": identity, "round": 0,
                              "challenge": "why", "relation": "supports", "author": author, "review": None})
        previous = current
    case = {"schema_version": 2, "kind": dc.CASE_KIND, "case_id": "wide", "rundir": "/r",
            "decision_point": {"gate": "launch", "action_kind": "bulk_launch",
                               "action": {"summary": "Act", "digest": "a" * 64, "pins": []}},
            "risk": {"class": "R2", "computed_factors": {}, "declared_factors": {},
                     "policy": {"path": "p", "sha256": "b" * 64}},
            "proposal": {"node_id": "action", "committed_event": "c" * 64},
            "nodes": nodes, "edges": edges[:255], "anchors": [], "critique": None, "revisions": [],
            "verification": None}
    started = time.monotonic()
    with pytest.raises(ValueError, match="paths"):
        dc.validate_case_v2(case)
    assert time.monotonic() - started < 2.0


# ---------------------------------------------------------------- production dispatch

def test_rdj_roles_are_registered_agent_graph_roles():
    from ravel.workflow import agent_graph, agent_host
    assert {"rdj_edge_reviewer", "rdj_critic", "rdj_verifier"} <= agent_graph.ROLES
    assert {"rdj_critic", "rdj_verifier"} <= set(agent_host.BLIND_ROLES)


def test_blind_rdj_roles_need_a_packet(tmp_path):
    from ravel.workflow import agent_graph
    spec = {"schema_version": 1, "graph_id": "g", "budget": {"max_nodes": 1, "max_calls": 1,
            "max_output_tokens": 100, "max_wall_seconds": 60, "max_reworks": 0},
            "nodes": [{"id": "n", "kind": "model", "role": "rdj_critic", "depends_on": [], "inputs": [],
                       "packet": None, "action": "model", "parameters": {}, "max_attempts": 1}]}
    with pytest.raises(agent_graph.GraphError, match="packet"):
        agent_graph.create(tmp_path / "g", spec)


def test_cli_registers_run_roles(tmp_path, capsys):
    with pytest.raises(SystemExit):
        rdj.main(["run-roles", "--help"])
    assert "--host-config" in capsys.readouterr().out
