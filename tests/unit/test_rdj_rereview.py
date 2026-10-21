"""Second pass over the decision-justification core.

Each test is named after the finding it closes: S1-S20 from the merged re-review of the first fix pass,
C1-C12 from the second-family conformance review of the same pass, the evidence-class rule and P17 (evidence-classed criticism
and the critic basis), P04 (support closure and common-mode anchors) and P01 (``board_head`` as an input
artifact). Each was written before its fix and failed on the base.
"""
import json
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from ravel.workflow import decision_case as dc
from ravel.workflow import evidence_queue, rdj_anchor, rdj_custody
from ravel.workflow import rdj_loop as rdj

from inert_dispatch import inert_dispatch  # noqa: F401
from rdj_fixtures import (PROPOSER, PROMPT, Roles, Run, add, challenge, critic, critic_once, node, reviewer, said,
                          two_level_r2, verifier)

ACTOR = {"actor_id": "c", "session_receipt": "s", "attestation": "transport_attested"}
HIGH = {"mode": "scan", "points": 5000, "walltime_h": [60.0, 60.0]}
SMALL = {"mode": "smoke", "points": 1, "walltime_h": [0.1, 0.1]}


@pytest.fixture(autouse=True)
def custody(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("RAVEL_NATIVE_BIN", raising=False)


def row(spec, identity="a"):
    return {"id": identity, "locator": spec.get("locator", ""), "value": spec.get("value"),
            "quantity": spec.get("quantity"), "verified": None, "kind": spec["kind"], "binding": spec["binding"]}


def ctx(run, **extra):
    return {"rundir": str(run.root), "input_snapshot": rdj_custody.input_snapshot(run.root), "generated": [],
            "action_pins": [], **extra}


def refused(run, case_id):
    with pytest.raises(rdj.OpenItems) as exc:
        rdj.authorize(run.root, case_id)
    return {i["code"] for i in exc.value.items}


def finding(fid="F1", code="missing_evidence", targets=("B",), materiality="A", evidence_class="code_check",
            locators=("B",), request=None, **extra):
    return {"id": fid, "code": code, "targets": list(targets), "materiality": materiality,
            "evidence_class": evidence_class, "evidence_locators": list(locators), "request": request, **extra}


def full_r2(run, roles=None, **opts):
    roles = roles or Roles()
    case_id = two_level_r2(run, roles=roles, **opts)
    rdj.run_roles(run.root, case_id, roles)
    return case_id


def graph_host():
    pytest.importorskip("langgraph")
    from test_rdj_loop import GraphHost
    return GraphHost({"edge_reviewer": reviewer(), "critic": critic(), "verifier": verifier()})


# ---------------------------------------------------------------- S1 graph-host attestation

def test_s1_unregistered_graph_host_is_not_transport_attested(tmp_path):
    run = Run(tmp_path / "run")
    dispatcher = rdj.AgentHostDispatcher(graph_host(), model="m")
    case_id = two_level_r2(run, roles=dispatcher)
    rdj.run_roles(run.root, case_id, dispatcher)
    case = run.case(case_id)
    assert case["critique"]["reviewer"]["attestation"] == "self_attested"
    assert {e["review"]["reviewer"]["attestation"] for e in case["edges"]} == {"self_attested"}
    assert "attestation_insufficient" in refused(run, case_id)


def test_s1_graph_receipt_the_dispatcher_did_not_register_is_rejected(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    host = graph_host()
    rdj_custody.register_host(run.root, host.identity)
    monkeypatch.setattr(rdj_custody, "register_graph_receipt", lambda *a, **k: None, raising=False)
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))
    with pytest.raises(ValueError, match="not registered"):
        rdj.run_roles(run.root, case_id, rdj.AgentHostDispatcher(host, model="m"))


# ---------------------------------------------------------------- S2 and S6 execution receipts

def test_s2_minted_stage_receipt_is_generated(tmp_path):
    run = Run(tmp_path / "run")
    for kind in ("tool_output", "measurement"):
        minted = run.stage(f"m-{kind}", f"outputs/{kind}.json", {"v": 1}, kind=kind, register=False)
        assert rdj_anchor.verify(row(minted), run.root, context=ctx(run)) == "generated", kind
    registered = run.stage("ok", "outputs/ok.json", {"v": 1})
    assert rdj_anchor.verify(row(registered), run.root, context=ctx(run)) == "external"


def test_s6_module_shadowed_by_stage_cwd_is_not_the_tool(tmp_path):
    run = Run(tmp_path / "run")
    shadow = tmp_path / "shadow"
    for rel in ("ravel/__init__.py", "ravel/physics/__init__.py", "ravel/physics/pyhf_exclude.py"):
        (shadow / rel).parent.mkdir(parents=True, exist_ok=True)
        (shadow / rel).write_text("")
    anchor = run.stage("fit", "outputs/fit.json", {"mu": 1}, cwd=shadow)
    assert rdj_anchor.verify(row(anchor), run.root, context=ctx(run)) == "generated"


# ---------------------------------------------------------------- S3 the CHECK-IN 1 snapshot

def _commit_ns(run, case_id):
    return rdj_custody.rows(run.root, "journal-" + case_id)[0]["ns"]


def test_s3_file_first_seen_at_checkin1_is_generated_without_write_log(tmp_path):
    run = Run(tmp_path / "run")
    planted = run.put("inputs/notes/derived.json", {"checked": True})
    rdj_custody.record_input_snapshot(run.root, "checkin1")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    snapshot = rdj_custody.input_snapshot(run.root, before_ns=_commit_ns(run, case_id))
    assert planted["path"] not in snapshot
    assert snapshot["inputs/cards/settings.json"] == run.pin("inputs/cards/settings.json")["sha256"]
    anchor = row({"kind": "input_artifact", "binding": planted, "locator": "/checked"})
    assert rdj_anchor.verify(anchor, run.root, context={**ctx(run), "input_snapshot": snapshot}) == "generated"


def test_s3_a_write_log_that_does_not_list_the_file_does_not_vouch_for_it(tmp_path):
    """Inverted: the write log is proposer-writable, so its silence vouches for nothing. A user
    upload is external only through a registered acquisition (test_rdj_decision_control)."""
    run = Run(tmp_path / "run")
    added = run.put("inputs/notes/user-upload.json", {"bins": 4})
    run.put("agent-audit/writes.jsonl", json.dumps({"path": "outputs/x.json", "sha256": "0" * 64,
                                                    "session_id": "s"}) + "\n")
    rdj_custody.record_input_snapshot(run.root, "checkin1")
    assert added["path"] not in rdj_custody.input_snapshot(run.root)


# ---------------------------------------------------------------- S4, C1, S5, C12 the class

@pytest.mark.parametrize("action", [{"kind": "smoke_launch"}, {"kind": "dry_run"},
                                    {"kind": "bulk_launch", "rung": "smoke"}, {"kind": "single_point_launch"}])
def test_s4_lowering_void_when_consequence_fires(tmp_path, action):
    run = Run(tmp_path / "run", cost=HIGH)
    cls, factors = rdj.compute_class(run.root, "launch", action)
    assert cls == "R3" and "lowered_by" not in factors and factors["high_consequence"]


def test_c1_bulk_and_scan_keep_their_floor_under_a_smoke_rung(tmp_path):
    run = Run(tmp_path / "run", cost=SMALL)
    for gate in ("bulk", "launch", "scan"):
        assert rdj.compute_class(run.root, gate, {"kind": "bulk_launch", "rung": "smoke"})[0] == "R2", gate
    assert rdj.compute_class(run.root, "bulk", {"kind": "smoke_launch"})[0] == "R2"
    assert rdj.compute_class(run.root, "launch", {"kind": "smoke_launch"})[0] == "R0"


def test_s5_cost_record_rewritten_before_checkin1_keeps_consequence(tmp_path):
    run = Run(tmp_path / "run", cost=HIGH)
    run.put("inputs/cost_preflight.json", {"schema_version": 2, "generated_by": "cost_preflight.py", **SMALL})
    rdj_custody.record_input_snapshot(run.root, "checkin1")
    cls, factors = rdj.compute_class(run.root, "launch", run.action())
    assert cls == "R3" and "lowered_by" not in factors
    command = [sys.executable, "-m", "ravel.workflow.cost_preflight"]
    run.stage("cost", "inputs/cost_preflight.json", {"schema_version": 2, "generated_by": "cost_preflight.py",
                                                     "mode": "scan", "points": 3, "walltime_h": [0.1, 0.2]},
              command=command)
    assert rdj.compute_class(run.root, "launch", run.action())[0] == "R2"


def test_c12_an_incomplete_cost_record_is_an_unknown_consequence(tmp_path):
    run = Run(tmp_path / "run", cost={"mode": "scan", "points": 3, "walltime_h": None})
    cls, factors = rdj.compute_class(run.root, "launch", run.action())
    assert cls == "R3" and factors.get("consequence_unknown")


def test_c12_a_prompt_without_its_digest_binding_is_refused(tmp_path):
    run = Run(tmp_path / "run", prompt=False)
    run.put("inputs/task_contract.json", {"prompt": PROMPT})
    with pytest.raises(ValueError, match="prompt_sha256"):
        rdj_custody.record_user_text(run.root, "prompt", "inputs/task_contract.json")


# ---------------------------------------------------------------- S7, C11 sticky escalation

def test_s7_abandoned_case_with_open_finding_escalates_the_action(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    rdj.run_roles(run.root, case_id, Roles(critic=critic([finding(locators=(run.check_result("probe"),))])))
    with pytest.raises(ValueError, match="escalat"):
        rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    outcomes = [r["record"]["outcome"] for r in rdj_custody.rows(run.root, "receipts")
                if r["record"]["case_id"] == case_id]
    assert outcomes == ["escalate"]
    assert rdj.gate_errors(run.root, "launch", run.action())
    run.reopen(run.action_pin["sha256"])
    rdj.open_case(run.root, "launch", run.action(), PROPOSER)


def test_c11_escalation_stops_an_already_open_sibling_case(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    first = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    second = full_r2(run)
    policy = rdj_anchor.policy()
    policy["classes"]["R2"]["max_model_calls"] = 0
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    add(run, first, "action", node("A", "Ready"))
    rdj.run_roles(run.root, first, Roles())
    assert rdj.authorize(run.root, first)["outcome"] == "escalate"
    assert "action_escalated" in refused(run, second)


def test_c11_the_review_cap_admits_every_class_depth():
    pol = rdj_anchor.policy()
    for cls, rules in pol["classes"].items():
        assert pol["budgets"]["max_reviews_per_edge"] >= rules["max_depth"] + rules["revision_rounds"], cls


# ---------------------------------------------------------------- S8 interim proposer identity

def test_s8_a_proposer_without_a_session_is_refused_and_recorded_in_custody(tmp_path):
    run = Run(tmp_path / "run")
    with pytest.raises(ValueError, match="session"):
        rdj.open_case(run.root, "launch", run.action(), {**PROPOSER, "session_receipt": None})
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    rows = [r["record"] for r in rdj_custody.rows(run.root, "cases") if r["record"]["case_id"] == case_id]
    assert rows[0]["proposer"] == PROPOSER


# ---------------------------------------------------------------- S10, C3 queue completion

UNKNOWN = {"question": "Is the grid converged?", "request": {"kind": "experiment",
                                                              "description": "Run the convergence check"}}


def test_s10_done_with_planted_pin_does_not_clear_unknown(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "The grid is adequate", unknowns=[UNKNOWN]))
    item = evidence_queue.items(run.root, case_id=case_id)[0]
    planted = run.put("outputs/converged.json", {"converged": True})
    evidence_queue.resolve(run.root, item["item_id"], status="done", note="checked", pins=[planted])
    assert rdj._open_unknowns(run.root, run.case(case_id)) == ["A"]


def test_c3_a_hand_written_done_record_does_not_clear_unknown(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "The grid is adequate", unknowns=[UNKNOWN]))
    item = evidence_queue.items(run.root, case_id=case_id)[0]
    path = run.root / f"rdj/queue/{item['item_id']}.json"
    path.write_text(json.dumps({**item, "status": "done"}))
    assert rdj._open_unknowns(run.root, run.case(case_id)) == ["A"]
    answer = run.stage("converge", "outputs/converge.json", {"converged": True})
    path.write_text(json.dumps(item))
    evidence_queue.resolve(run.root, item["item_id"], status="done", note="the convergence stage ran",
                           pins=[run.pin(answer["binding"]["output_path"])])
    assert rdj._open_unknowns(run.root, run.case(case_id)) == []


# ---------------------------------------------------------------- S11, C10 run identity

def test_s11_moved_run_keeps_custody_and_recreated_run_starts_clean(tmp_path):
    run = Run(tmp_path / "run", run_id="run-0001")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    moved = tmp_path / "moved"
    shutil.move(str(run.root), str(moved))
    with pytest.raises(rdj_custody.CustodyError, match="relocated"):
        rdj_custody.root(moved)
    rdj_custody.relocate(moved, "run-0001")
    assert rdj.status(moved, case_id)["phase"] not in ("tampered", "unreadable")
    fresh = Run(tmp_path / "run", run_id="run-0002")
    assert rdj_custody.rows(fresh.root, "cases") == []
    contract = json.loads((fresh.root / "inputs/task_contract.json").read_text())
    (fresh.root / "inputs/task_contract.json").write_text(json.dumps({**contract, "run_id": "run-9999"}))
    with pytest.raises(rdj_custody.CustodyError):
        rdj_custody.root(fresh.root)


def test_c10_a_custody_root_inside_the_run_is_refused(tmp_path, lock_domain_at):
    run = Run(tmp_path / "run")
    inside = run.root / "inputs/state"
    inside.mkdir(parents=True)
    (inside / "ravel-test-machine-domain").write_text("x")
    lock_domain_at(inside)
    with pytest.raises(rdj_custody.CustodyError, match="inside the run"):
        rdj_custody.root(run.root)


# ---------------------------------------------------------------- S12, S13 false refusals

def test_s12_a_reopen_decision_resets_the_case_budget(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    policy = rdj_anchor.policy()
    policy["budgets"]["max_cases_per_action"] = 2
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    for _ in range(2):
        rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    digest = run.action_pin["sha256"]
    run.steering(f"Do not try {digest[:12]} again.")
    with pytest.raises(ValueError, match="cases"):
        rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    run.reopen(digest)
    rdj.open_case(run.root, "launch", run.action(), PROPOSER)


def test_s13_r1_allows_one_revision_round(tmp_path):
    assert rdj_anchor.policy()["classes"]["R1"]["revision_rounds"] == 1
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen B"), PROPOSER)
    add(run, case_id, "action", node("P", "B is faster", anchors=[run.stage("m", "outputs/m.json", {"r": 1})]),
        node("Q", "B used fewer calls", anchors=[run.stage("q", "outputs/q.json", {"r": 2})]))
    failing = reviewer({"action->P": {"entailment": "fails", "code": "decision_does_not_follow",
                                      "reason": "a rate is not a speed"}})
    rdj.run_roles(run.root, case_id, Roles(edge_reviewer=failing))
    rdj.answer(run.root, case_id, [{"op": "remove_edge", "edge_id": "action->P", "addresses": ["E:action->P"]}])
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"


# ---------------------------------------------------------------- S14 to S20 robustness

def test_s14_worker_final_record_outside_its_directory_is_rejected(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))

    class Escaping(Roles):
        def dispatch(self, rundir, request):
            ref = super().dispatch(rundir, request)
            path = Path(rundir) / ref["path"]
            receipt = json.loads(path.read_text())
            (tmp_path / "outside.json").write_bytes((path.parent / "final.json").read_bytes())
            receipt["final_record"]["path"] = "../../../../outside.json"
            path.write_text(json.dumps(receipt, sort_keys=True))
            rdj_custody.register_worker_receipt(rundir, ref["path"])
            return ref
    with pytest.raises(ValueError, match="final record"):
        rdj.run_roles(run.root, case_id, Escaping())


def test_s15_a_torn_custody_line_and_a_missing_case_are_reported(tmp_path):
    run = Run(tmp_path / "run")
    torn = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    missing = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    with (rdj_custody.root(run.root) / f"journal-{torn}.jsonl").open("a") as stream:
        stream.write('{"seq": 9, "tor')
    with pytest.raises(rdj_custody.CustodyError):
        rdj_custody.rows(run.root, "journal-" + torn)
    assert rdj.status(run.root, torn)["phase"] == "tampered"
    (run.root / f"rdj/cases/{missing}.json").unlink()
    phases = {r["case_id"]: r["phase"] for r in rdj.run_status(run.root)["cases"]}
    assert phases == {torn: "tampered", missing: "tampered"}


def test_s15_an_interrupted_save_is_restored_from_custody(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))
    saved = {p: (run.root / p).read_bytes() for p in (f"rdj/cases/{case_id}.json", f"rdj/state/{case_id}.json")}
    (run.root / f"rdj/state/{case_id}.json").unlink()
    journal = run.root / f"rdj/journal/{case_id}.jsonl"
    journal.write_text("".join(journal.read_text().splitlines(True)[:-1]))
    assert rdj.status(run.root, case_id)["phase"] == "tampered"
    rdj.restore(run.root, case_id)
    assert {p: (run.root / p).read_bytes() for p in saved} == saved
    assert rdj.next_challenges(run.root, case_id)


def test_s16_identical_bytes_at_another_path_are_not_circular(tmp_path):
    run = Run(tmp_path / "run")
    copy = run.stage("copy", "outputs/copy.json", {"points": 3})  # the same bytes as the action's plan
    assert copy["binding"]["sha256"] == run.action_pin["sha256"]
    assert rdj_anchor.verify(row(copy), run.root, context=ctx(run, action_pins=[run.action_pin])) == "external"


def test_s17_an_approval_record_without_consent_is_not_an_approval(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    run.approve(case_id)
    record = rdj_custody.rows(run.root, "approvals")[0]["record"]
    assert record["decision"] == "approve"
    (rdj_custody.root(run.root) / "approvals.jsonl").unlink()
    rdj_custody.append(run.root, "approvals", {k: v for k, v in record.items() if k != "decision"})
    assert rdj_custody.approvals(run.root, case_id, run.action_pin["sha256"]) == []


def test_s18_an_unchecked_reference_record_id_is_not_shown(tmp_path):
    run = Run(tmp_path / "run")
    anchor = row({"kind": "external_fact",
                  "binding": {"record_id": "record-1/table-2", "file": run.pin("inputs/cards/settings.json")}})
    status, _, observed = rdj_anchor.verify_full(anchor, run.root, context=ctx(run))
    assert "record_id" not in rdj_anchor.describe({**anchor, "verified": status}, observed)


def test_s19_concurrent_opens_respect_the_case_budget(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    policy = rdj_anchor.policy()
    policy["budgets"]["max_cases_per_action"] = 2
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    real = rdj_custody.rows

    def slow(rundir, ledger):
        rows = real(rundir, ledger)
        if ledger == "cases":
            time.sleep(0.05)
        return rows
    monkeypatch.setattr(rdj_custody, "rows", slow)
    results = []

    def attempt():
        try:
            rdj.open_case(run.root, "launch", run.action(), PROPOSER)
            results.append("opened")
        except ValueError:
            results.append("refused")
    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("opened") == 2


def test_s20_the_snapshot_file_limit_comes_from_policy(tmp_path, monkeypatch):
    assert rdj_anchor.policy()["input_snapshot_max_files"] >= 65536
    policy = rdj_anchor.policy()
    policy["input_snapshot_max_files"] = 1
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    with pytest.raises(rdj_custody.CustodyError, match="file limit"):
        Run(tmp_path / "run")


# ---------------------------------------------------------------- C4 receipts bind the case they authorized

def test_c4_a_receipt_binds_the_case_state_it_authorized(tmp_path, inert_dispatch):
    run = Run(tmp_path / "run")
    case_id = full_r2(run)
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"
    assert rdj.gate_errors(run.root, "launch", run.action()) == []
    case, state, _ = rdj._load(run.root, case_id)
    case["risk"]["computed_factors"]["later"] = True
    rdj._commit(run.root, case, state, "later_save")
    assert "rdj_case_changed" in {e.code for e in rdj.gate_errors(run.root, "launch", run.action())}


def test_c4_exhausted_budget_and_a_non_authorize_verifier_are_open_items(tmp_path, inert_dispatch):
    run = Run(tmp_path / "run")
    case_id = full_r2(run)
    case, state, _ = rdj._load(run.root, case_id)
    assert rdj.authorization_errors(run.root, case, state) == []
    assert "budget_exhausted" in {i["code"] for i in rdj.authorization_errors(
        run.root, case, {**state, "budget_exhausted": True, "budget_reason": "spent"})}
    escalating = json.loads(json.dumps(case))
    escalating["verification"]["outcome"] = "escalate"
    assert "verifier_outcome" in {i["code"] for i in rdj.authorization_errors(run.root, escalating, state)}


# ---------------------------------------------------------------- C5 freshness

def test_c5_revising_a_parent_claim_drops_its_outgoing_reviews(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    rdj.run_roles(run.root, case_id, Roles(critic=critic_once([finding(targets=("A",), locators=(run.check_result("probe"),))])))
    rdj.answer(run.root, case_id, [{"op": "revise_node", "node_id": "A", "addresses": ["F1"],
                                    "fields": {"assertion": "The smoke receipts show every stage ran"}}])
    edges = {e["id"]: e for e in run.case(case_id)["edges"]}
    assert edges["A->B"]["review"] is None and "every stage ran" in edges["A->B"]["challenge"]


def test_c5_verification_binds_the_edge_verdicts(tmp_path):
    run = Run(tmp_path / "run")
    case_id = full_r2(run)
    case, state, _ = rdj._load(run.root, case_id)
    before = rdj._verify_digest(case, state)
    next(e for e in case["edges"] if e["review"])["review"]["reason"] = "a different public reason"
    assert rdj._verify_digest(case, state) != before


def test_c5_the_critic_reruns_after_growth_without_a_revision(tmp_path):
    run = Run(tmp_path / "run")
    calls = []

    def critic_(payload):
        calls.append(payload)
        return said({"findings": []}, "critic")
    roles = Roles(critic=critic_)
    case_id = full_r2(run, roles=roles)
    run.put("outputs/smoke.json", {"events": 1})  # B's anchor no longer verifies; B is open again
    rdj.run_roles(run.root, case_id, roles)  # the hop into B is re-reviewed; the proposer must answer B
    seen = len(calls)
    cid = challenge(run, case_id, "why_believe", "B")
    rdj.answer(run.root, case_id, [{"op": "attach_anchor", "challenge_id": cid, "node_id": "B",
                                    "anchor": run.stage("smoke2", "outputs/smoke2.json", {"events": 100})}])
    rdj.run_roles(run.root, case_id, roles)
    assert len(calls) == seen + 1


# ---------------------------------------------------------------- C6 quantity identity

def test_c6_a_quantity_label_cannot_hide_a_conflict(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen B"), PROPOSER)
    one = {**run.stage("m1", "outputs/m1.json", {"rate": 1.0}, locator="/rate"), "quantity": "rate-a"}
    two = {**run.stage("m2", "outputs/m2.json", {"rate": 9.0}, locator="/rate"), "quantity": "rate-b"}
    add(run, case_id, "action", node("P", "B is faster", anchors=[one]), node("Q", "Re-measured", anchors=[two]))
    rdj.run_roles(run.root, case_id, Roles())
    reasons = {c["target"]: c["reason"] for c in rdj.next_challenges(run.root, case_id)}
    assert all("depth 2" in reasons[t] for t in ("P", "Q"))


def test_c6_the_same_leaf_name_under_different_paths_is_not_a_conflict(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen B"), PROPOSER)
    one = run.stage("m1", "outputs/m1.json", {"signal": {"rate": 1.0}}, locator="/signal/rate")
    two = run.stage("m2", "outputs/m2.json", {"background": {"rate": 9.0}}, locator="/background/rate")
    add(run, case_id, "action", node("P", "Signal is small", anchors=[one]), node("Q", "Background is large",
                                                                                   anchors=[two]))
    rdj.run_roles(run.root, case_id, Roles())
    assert not [c for c in rdj.next_challenges(run.root, case_id) if c["target"] in ("P", "Q")]


# ---------------------------------------------------------------- C7 producer identity

def test_c7_a_native_tool_name_outside_the_native_build_is_not_a_tool(tmp_path):
    run = Run(tmp_path / "run")
    fake = run.stage("rivet", "outputs/histograms.json", {"h": 1}, command=["/untrusted/bin/rivet", "--pwd"])
    assert rdj_anchor.verify(row(fake), run.root, context=ctx(run)) == "generated"


# ---------------------------------------------------------------- minor rows of the second-family review

def test_c_edge_review_code_is_no_issue_exactly_when_the_hop_is_affirmative():
    review = {"reviewer": ACTOR, "edge_sha256": "0" * 64, "entailment": "partial", "relevance": "relevant",
              "grounding": "anchored", "code": "no_issue", "reason": "mostly", "request": None}
    with pytest.raises(ValueError, match="no_issue"):
        dc.edge_review(review)


def test_c_the_critic_must_differ_from_the_verifier(tmp_path):
    run = Run(tmp_path / "run")
    case_id = full_r2(run)
    case, state, _ = rdj._load(run.root, case_id)
    with pytest.raises(rdj.IndependenceError):
        rdj._record_critique(run.root, case, state, {"findings": []}, case["verification"]["reviewer"])


def test_c_the_verifier_sees_each_finding_whole(tmp_path):
    run = Run(tmp_path / "run")
    seen = {}

    def verifier_(payload):
        seen["findings"] = payload["findings"]
        return verifier(resolved="no")(payload)
    full_r2(run, roles=Roles(critic=critic([finding(evidence_class="opinion", locators=())]), verifier=verifier_))
    assert set(seen["findings"][0]) >= {"evidence_class", "evidence_locators", "request"}


def test_c_long_text_and_binary_inputs_verify_against_their_full_bytes(tmp_path):
    text = "x" * 5000
    run = Run(tmp_path / "run", extra_inputs=[("inputs/notes/long.txt", text), ("inputs/data/table.bin", b"\x00\xff")])
    long_ = row({"kind": "input_artifact", "binding": run.pin("inputs/notes/long.txt"), "value": text})
    assert rdj_anchor.verify(long_, run.root, context=ctx(run)) == "external"
    binary = row({"kind": "input_artifact", "binding": run.pin("inputs/data/table.bin")})
    status, _, observed = rdj_anchor.verify_full(binary, run.root, context=ctx(run))
    assert status == "external" and observed == {"bytes": 2, "sha256": run.pin("inputs/data/table.bin")["sha256"]}


# ---------------------------------------------------------------- evidence-classed criticism

def test_l04_findings_carry_an_evidence_class():
    base = finding()
    dc.critique({"reviewer": ACTOR, "findings": [base]})
    assert set(dc.EVIDENCE_CLASSES) == {"new_receipt", "code_check", "cited", "opinion"}
    for bad in ({k: v for k, v in base.items() if k != "evidence_class"}, {**base, "evidence_class": "hunch"}):
        with pytest.raises(ValueError, match="evidence class"):
            dc.critique({"reviewer": ACTOR, "findings": [bad]})


OPINION = dict(code="risk_underestimated", targets=("action",), locators=(), evidence_class="opinion")
TEST_REQUEST = {"kind": "experiment", "description": "Run a coarser grid and compare the yields",
                "max_broker_calls": 2}


def test_l04_s7_an_opinion_only_finding_against_a_correct_plan_does_not_block(tmp_path, inert_dispatch):
    run = Run(tmp_path / "run")
    case_id = full_r2(run, roles=Roles(critic=critic([finding(**OPINION)])))
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize" and receipt["open_a_findings"] == 0
    assert rdj.decision_detail(run.root, receipt["receipt_id"])["advisory_findings"] == ["F1"]


def test_l04_s7_the_same_finding_with_a_failing_requested_test_blocks(tmp_path, inert_dispatch):
    run = Run(tmp_path / "run")
    roles = Roles(critic=critic_once([finding(**OPINION, request=TEST_REQUEST)]), verifier=verifier(resolved="no"))
    case_id = full_r2(run, roles=roles)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "gather_evidence" and receipt["open_a_findings"] == 1
    item = next(i for i in evidence_queue.items(run.root, case_id=case_id) if i["source"] == "critic_finding")
    assert item["request"]["max_broker_calls"] == 2
    result = run.stage("coarse", "outputs/coarse.json", {"yield_ratio": 1.8})
    evidence_queue.resolve(run.root, item["item_id"], status="done", note="the coarse grid disagrees",
                           pins=[run.pin(result["binding"]["output_path"])], verdict="upholds")
    rdj.run_roles(run.root, case_id, roles)
    assert "finding_open" in refused(run, case_id)


def test_l04_s7_a_requested_test_that_refutes_the_finding_releases_it(tmp_path, inert_dispatch):
    run = Run(tmp_path / "run")
    roles = Roles(critic=critic_once([finding(**OPINION, request=TEST_REQUEST)]), verifier=verifier(resolved="no"))
    case_id = full_r2(run, roles=roles)
    item = next(i for i in evidence_queue.items(run.root, case_id=case_id) if i["source"] == "critic_finding")
    result = run.stage("coarse", "outputs/coarse.json", {"yield_ratio": 1.0})
    evidence_queue.resolve(run.root, item["item_id"], status="done", note="the coarse grid agrees",
                           pins=[run.pin(result["binding"]["output_path"])], verdict="refutes")
    rdj.run_roles(run.root, case_id, roles)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize" and receipt["open_a_findings"] == 0


def test_l04_request_max_broker_calls_bounds_the_critics_tests(tmp_path):
    cap = rdj_anchor.policy()["budgets"]["max_critic_broker_calls"]
    for bad in (-1, "2", True):
        with pytest.raises(ValueError, match="max_broker_calls"):
            dc.request_v2({**TEST_REQUEST, "max_broker_calls": bad})
    run = Run(tmp_path / "run")
    over = finding(**OPINION, request={**TEST_REQUEST, "max_broker_calls": cap + 1})
    case_id = two_level_r2(run)
    with pytest.raises(ValueError, match="max_broker_calls"):
        rdj.run_roles(run.root, case_id, Roles(critic=critic([over])))


@pytest.mark.parametrize("kind", ["research_meta_review", "manuscript_integrity_assessment", "integrity"])
def test_l04_a_review_or_integrity_verdict_cited_as_an_anchor_is_generated(tmp_path, kind):
    verdict = {"kind": kind, "verdict": "accept"}
    run = Run(tmp_path / "run", extra_inputs=[("inputs/reviews/verdict.json", verdict)])
    as_input = row({"kind": "input_artifact", "binding": run.pin("inputs/reviews/verdict.json"), "locator": "/verdict"})
    assert rdj_anchor.verify(as_input, run.root, context=ctx(run)) == "generated"
    as_output = run.stage("review", "outputs/verdict.json", verdict, locator="/verdict")
    assert rdj_anchor.verify(row(as_output), run.root, context=ctx(run)) == "generated"
    case_id = full_r2(run, leaf_anchor=as_output)
    assert refused(run, case_id) & {"self_grounding", "branch_open"}


# ---------------------------------------------------------------- P17 critic basis (RDJ half)

def test_p17_a_blocking_class_whose_basis_does_not_verify_is_advisory(tmp_path, inert_dispatch):
    run = Run(tmp_path / "run")
    unbacked = [finding("F1", locators=("outputs/absent.json",)),
                finding("F2", evidence_class="new_receipt", locators=("stage:ghost:1",))]
    roles = Roles(critic=critic(unbacked), verifier=verifier(resolved="no"))
    case_id = full_r2(run, roles=roles)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize"
    assert rdj.decision_detail(run.root, receipt["receipt_id"])["advisory_findings"] == ["F1", "F2"]
    assert rdj.check_critic_basis(run.root, case_id) == []


def test_p17_a_new_receipt_finding_with_a_registered_receipt_blocks(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    probe = run.stage("probe", "outputs/probe.json", {"converged": False})
    receipt_id = probe["binding"]["receipt_id"]
    rdj.run_roles(run.root, case_id, Roles(critic=critic([finding(evidence_class="new_receipt",
                                                                  locators=(receipt_id,))]),
                                           verifier=verifier(resolved="no")))
    assert "finding_open" in refused(run, case_id)
    assert rdj.check_critic_basis(run.root, case_id) == []


# ---------------------------------------------------------------- P04 support closure and common-mode anchors

def test_p04_support_closure_recomputes_byte_identically(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "The configuration is ready"))
    rdj.run_roles(run.root, case_id, Roles())
    add(run, case_id, "A", node("B", "The grid is converged", unknowns=[UNKNOWN],
                                anchors=[run.stage("s", "outputs/s.json", {"ok": 1})]))
    stored = rdj._load(run.root, case_id)[1]["support_closure"]
    recomputed = rdj.support_closure(run.root, case_id)
    assert dc.jdigest(stored) == dc.jdigest(recomputed)
    assert recomputed["unknown"] == ["A", "B", "action"] and recomputed["conflict"] == []
    assert rdj.check_support_closure(run.root, case_id) == []
    case, state, _ = rdj._load(run.root, case_id)
    state["support_closure"] = {**state["support_closure"], "unknown": []}
    rdj._commit(run.root, case, state, "planted")
    assert rdj.check_support_closure(run.root, case_id)


def test_p04_the_conflict_set_propagates_to_the_claims_it_supports(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen B"), PROPOSER)
    one = run.stage("m1", "outputs/m1.json", {"rate": 1.0}, locator="/rate")
    two = run.stage("m2", "outputs/m2.json", {"rate": 9.0}, locator="/rate")
    add(run, case_id, "action", node("P", "B is faster", anchors=[one]), node("Q", "Re-measured", anchors=[two]))
    assert rdj.support_closure(run.root, case_id)["conflict"] == ["P", "Q", "action"]


def _shared_card_case(run, gate, kind):
    card = {"kind": "input_artifact", "binding": run.pin("inputs/cards/settings.json"), "locator": "/bins"}
    case_id = rdj.open_case(run.root, gate, run.action(kind), PROPOSER)
    add(run, case_id, "action", node("P", "The binning is the approved one", anchors=[card]),
        node("Q", "The fit uses four bins", anchors=[dict(card)]))
    return case_id


def test_p04_a_planted_anchor_shared_by_two_material_claims_is_flagged_at_r3_and_delivery(tmp_path):
    run = Run(tmp_path / "run")
    case_id = _shared_card_case(run, "delivery", "deliver_result")
    flagged = rdj.common_mode_anchors(run.root, case_id)
    assert [sorted(f["claims"]) for f in flagged] == [["P", "Q"]]
    assert "common_mode_anchor" in {i["code"] for i in rdj.status(run.root, case_id)["open_items"]}


def test_p04_a_shared_anchor_below_r3_is_not_flagged(tmp_path):
    run = Run(tmp_path / "run", cost=SMALL)
    case_id = _shared_card_case(run, "research_choice", "screening_choice")
    assert rdj.common_mode_anchors(run.root, case_id) == []


# ---------------------------------------------------------------- P01 board_head as an input artifact

def test_p01_board_head_is_an_input_artifact_and_board_content_is_generated(tmp_path):
    run = Run(tmp_path / "run", extra_inputs=[("inputs/board/head.json", {"head": "0" * 64}),
                                              ("inputs/board/posts/p1.json", {"claim": "the grid is converged"})])
    head = run.pin("inputs/board/head.json")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER,
                            input_artifacts=[{"role": "board_head", **head}])
    assert run.case(case_id)["input_artifacts"] == [{"role": "board_head", **head}]
    case, state, _ = rdj._load(run.root, case_id)
    context = rdj._context(run.root, case, state)
    for rel in ("inputs/board/head.json", "inputs/board/posts/p1.json"):
        anchor = row({"kind": "input_artifact", "binding": run.pin(rel)})
        assert rdj_anchor.verify(anchor, run.root, context=context) == "generated", rel
    bad = {**run.case(case_id), "input_artifacts": [{"role": "notes", **head}]}
    with pytest.raises(ValueError, match="input artifact"):
        dc.validate_case_v2(bad)
