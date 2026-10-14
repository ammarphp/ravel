"""Synthetic authority, scheduling and crash controls for the RDJ substrate port."""
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ravel.workflow import decision_case as dc, rdj_custody as custody, rdj_loop as rdj
from rdj_fixtures import PROPOSER, Roles, Run, add, node, reviewer, two_level_r2, verifier


def crash_process(run, case_id, body):
    script = "import os,sys\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(Path(__file__).parent)) + ")\n"
    script += "from rdj_fixtures import Roles\nfrom ravel.workflow import rdj_loop as rdj\n"
    script += "root=Path(sys.argv[1]); case_id=sys.argv[2]\n" + body
    return subprocess.run([sys.executable, "-c", script, str(run.root), case_id], check=False).returncode


def simple(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "The synthetic chain is ready"))
    return run, case_id


def test_reservation_crash_reuses_slot_and_charge(tmp_path):
    run, case_id = simple(tmp_path)
    body = """original=rdj._commit
def commit(*args, **kwargs):
    value=original(*args, **kwargs)
    if args[3]=='role_reserved': os._exit(73)
    return value
rdj._commit=commit
rdj.run_roles(root,case_id,Roles())
"""
    assert crash_process(run, case_id, body) == 73
    roles = Roles()
    rdj.run_roles(run.root, case_id, roles)
    assert len(custody.rows(run.root, "roles")) == 1
    assert rdj.status(run.root, case_id)["usage"]["model_calls"] == 1
    assert len(roles.calls) == 1
    from ravel.workflow import run_ceilings
    assert len(run_ceilings._ledger(run.root)) == 1


def test_run_roles_dispatch_is_an_agent_node(tmp_path):
    from ravel.workflow import graph_nodes
    run, case_id = simple(tmp_path)

    class Observed(Roles):
        def dispatch(self, rundir, request):
            assert graph_nodes.TRIPWIRE.get()["ravel_kind"] == "agent"
            return super().dispatch(rundir, request)

    roles = Observed()
    rdj.run_roles(run.root, case_id, roles)
    assert len(roles.calls) == 1
    assert (run.root / "framework/graphs.sqlite").is_file()


def test_unchanged_edge_binds_despite_sibling_case_change(tmp_path):
    run, case_id = simple(tmp_path)
    before = dc.merkle(run.case(case_id))["edges"]["action->A"]
    changed = []

    def respond(payload):
        if not changed:
            changed.append(True)
            add(run, case_id, "action", node("alt", "Wait", kind="alternative"), kind="why_over_alternative")
            assert dc.merkle(run.case(case_id))["edges"]["action->A"] == before
        return reviewer()(payload)

    roles = Roles(edge_reviewer=respond)
    rdj.run_roles(run.root, case_id, roles)
    _, state, _ = rdj._load(run.root, case_id)
    assert state["calls"][0]["status"] == "completed"
    assert not any(c["status"] == "stale" for c in state["calls"])


@pytest.mark.parametrize("last", ["A", "B"])
def test_parallel_batches_bind_and_join_is_sorted(tmp_path, last):
    from ravel.workflow.graphs import rdj as graph
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "One synthetic claim"), node("B", "A separate synthetic claim"))
    barrier = threading.Barrier(2)

    def respond(payload):
        barrier.wait(timeout=5)
        if payload["edges"][0]["child"]["id"] == last:
            time.sleep(0.02)
        return reviewer()(payload)

    result = graph.run(run.root, case_id, Roles(edge_reviewer=respond), edge_batch_size=1, workers=2)
    assert result["graph"]["terminal"] is None
    case, state, _ = rdj._load(run.root, case_id)
    assert all(e["review"] for e in case["edges"])
    assert [c["status"] for c in state["calls"]] == ["completed", "completed"]
    events = custody.rows(run.root, "journal-" + case_id)
    slots = [r["record"]["data"]["slot"] for r in events if r["record"]["event"] == "role_completed"]
    assert slots == sorted(slots)


@pytest.mark.parametrize("boundary", ["before_save", "after_append"])
def test_partial_reservation_save_recovers_from_custody(tmp_path, boundary):
    run, case_id = simple(tmp_path)
    if boundary == "before_save":
        body = """original=rdj._commit
def commit(*args,**kwargs):
    if args[3]=='role_reserved': os._exit(73)
    return original(*args,**kwargs)
rdj._commit=commit
rdj.run_roles(root,case_id,Roles())
"""
    else:
        body = """original=rdj.custody.append
def append(*args,**kwargs):
    row=original(*args,**kwargs)
    if args[1]=='roles': os._exit(73)
    return row
rdj.custody.append=append
rdj.run_roles(root,case_id,Roles())
"""
    assert crash_process(run, case_id, body) == 73
    roles = Roles()
    rdj.run_roles(run.root, case_id, roles)
    assert len(roles.calls) == 1
    assert len(custody.rows(run.root, "roles")) == 1
    assert rdj.status(run.root, case_id)["usage"]["model_calls"] == 1


@pytest.mark.parametrize("boundary", ["receipt", "downstream", "effect_outcome"])
def test_receipted_crash_reconciles_without_second_dispatch(tmp_path, boundary):
    from ravel.workflow.graphs import rdj as graph
    from ravel.workflow import run_ceilings
    run, case_id = simple(tmp_path)
    if boundary == "receipt":
        body = """class Completed(Roles):
    def dispatch(self,rundir,request):
        super().dispatch(rundir,request)
        os._exit(75)
rdj.run_roles(root,case_id,Completed())
"""
    elif boundary == "downstream":
        body = """from ravel.workflow.graphs import rdj as graph
original=graph._role_downstream
def downstream(*args,**kwargs):
    original(*args,**kwargs)
    os._exit(75)
graph._role_downstream=downstream
rdj.run_roles(root,case_id,Roles())
"""
    else:
        body = """from ravel.workflow import effect_ledger
original=effect_ledger._write_outcome
def outcome(root,record):
    original(root,record)
    if record['kind']=='model' and record['status']=='completed': os._exit(75)
effect_ledger._write_outcome=outcome
rdj.run_roles(root,case_id,Roles())
"""
    assert crash_process(run, case_id, body) == 75
    roles = Roles()
    result = graph.run(run.root, case_id, roles, authorize=True)
    assert roles.calls == []
    assert result["graph"]["instance"]["mode"] == "roles"
    assert len(custody.rows(run.root, "roles")) == 1
    assert len(run_ceilings._ledger(run.root)) == 1
    case, state, _ = rdj._load(run.root, case_id)
    assert case["edges"][0]["review"] is not None
    assert state["calls"][0]["status"] == "completed"


def test_changed_reviewed_edge_is_stale(tmp_path):
    from ravel.workflow.graphs import rdj as graph
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)

    def respond(payload):
        (run.root / "outputs/smoke.json").write_text('{"events": 101}')
        return reviewer()(payload)

    graph.run(run.root, case_id, Roles(edge_reviewer=respond), max_steps=1)
    _, state, _ = rdj._load(run.root, case_id)
    assert state["calls"][-1]["status"] == "stale"


@pytest.mark.parametrize("role,steps", [("critic", 1), ("verifier", 2)])
def test_whole_case_judges_keep_whole_case_staleness(tmp_path, role, steps):
    from ravel.workflow.graphs import rdj as graph
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    graph.run(run.root, case_id, Roles(), max_steps=steps)
    roles = Roles()
    original = roles.responders[role]

    def respond(payload):
        with rdj._lock(run.root, case_id):
            case, state, _ = rdj._load(run.root, case_id)
            case["edges"][0]["review"]["reason"] = "A changed synthetic review explanation"
            rdj._commit(run.root, case, state, "synthetic_review_changed")
        return original(payload)

    roles.responders[role] = respond
    graph.run(run.root, case_id, roles, max_steps=1)
    _, state, _ = rdj._load(run.root, case_id)
    assert state["calls"][-1]["role"] == role
    assert state["calls"][-1]["status"] == "stale"


def test_graph_cannot_authorize_a_failed_edge(tmp_path, monkeypatch):
    from ravel.workflow.graphs import rdj as graph
    from ravel.workflow import rdj_anchor
    policy = rdj_anchor.policy()
    policy["classes"]["R2"]["revision_rounds"] = 0
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    roles = Roles(edge_reviewer=reviewer({"A->B": {"entailment": "fails", "code": "decision_does_not_follow",
                                                  "reason": "The synthetic edge fails"}}),
                  verifier=verifier("authorize"))
    with pytest.raises(rdj.OpenItems) as refusal:
        graph.run(run.root, case_id, roles, authorize=True)
    assert any(row["code"] == "edge_blocked" for row in refusal.value.items)
    assert custody.rows(run.root, "receipts") == []


def test_full_run_pauses_for_digest_bound_proposer_answers(tmp_path):
    from ravel.workflow.graphs import rdj as graph
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    result = graph.run(run.root, case_id, Roles(), authorize=True, interactive=True)
    request = result["graph"]["interrupts"][0]["payload"]
    assert request["kind"] == "proposer_answers"
    assert request["payload"]["case_sha256"] == dc.jdigest(run.case(case_id))
    assert request["approval_from_resume"] is False


@pytest.mark.parametrize("stale", [False, True])
def test_proposer_resume_checks_digest_and_only_applies_content(tmp_path, stale):
    from ravel.workflow.graphs import rdj as graph
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    result = graph.run(run.root, case_id, Roles(), authorize=True, interactive=True)
    pause = result["graph"]["interrupts"][0]
    payload = pause["payload"]["payload"]
    question = next(q for q in payload["challenges"] if q["kind"] == "why_action")
    response = {"case_sha256": "0" * 64 if stale else payload["case_sha256"], "answers": [
        {"op": "add_child", "challenge_id": question["id"], "parent": "action", "node": node("A", "Ready")}]}
    result = graph.run(run.root, case_id, Roles(), authorize=True, interactive=True,
                       respond={pause["id"]: response})
    if stale:
        assert result["graph"]["terminal"]["status"] == "decision_required"
        assert len(run.case(case_id)["nodes"]) == 1
    else:
        assert {n["id"] for n in run.case(case_id)["nodes"]} == {"action", "A"}
        assert result["graph"]["interrupts"][0]["kind"] == "proposer_answers"
    assert custody.rows(run.root, "receipts") == []


def test_answer_checks_expected_digest_inside_its_own_lock(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    question = next(q for q in rdj.next_challenges(run.root, case_id) if q["kind"] == "why_action")
    before = dc.jdigest(run.case(case_id))
    with pytest.raises(ValueError, match="stale"):
        rdj.answer(run.root, case_id, [{"op": "add_child", "challenge_id": question["id"],
                   "parent": "action", "node": node("A", "Ready")}], expected_case_sha256="0" * 64)
    assert dc.jdigest(run.case(case_id)) == before


def test_campaign_charge_uses_original_reservation_seam(tmp_path, monkeypatch):
    from ravel.workflow.graphs import rdj as graph
    from ravel.workflow import effect_ledger, research_cycle
    run, case_id = simple(tmp_path)
    recorded = []
    monkeypatch.setattr(research_cycle, "_load", lambda root: ({}, {"resource_ledger": recorded}))

    def reserve(root, identity, amount, evidence):
        assert root == (tmp_path / "campaign").resolve()
        assert identity.startswith("operation:rdj:")
        recorded.append({"id": identity, "ceiling": amount, "basis": evidence})

    monkeypatch.setattr(research_cycle, "reserve_operation", reserve)
    amount = {"calls": 1, "output_tokens": 20, "wall_seconds": 3, "native_attempts": 0}
    graph.run(run.root, case_id, Roles(), campaign=tmp_path / "campaign", campaign_charge=amount)
    model = next(r for r in effect_ledger.receipts(run.root) if r["kind"] == "model")
    assert [c["ledger"] for c in model["charges"]] == ["run_ceilings", "campaign"]
    assert all(c["applied"] for c in model["charges"])
    assert recorded[0]["ceiling"] == amount
    assert graph._present_campaign(run.root, model["call_id"]) is True
    assert model["identity"]["card"]["id"] == "rdj-edge-reviewer"
    assert len(model["identity"]["instruction_sha256"]) == 64
    assert model["framework_step"]["thread_id"]


def test_full_tool_reviewers_pending_lg2():
    pytest.xfail("awaits full-tool reviewer toolbelt integration; single-call seam is tested")


def test_registered_subgraph_seam_uses_domain_defaults(tmp_path):
    from ravel.workflow.graphs import rdj as graph
    from ravel.workflow import graph_substrate
    run, case_id = simple(tmp_path)
    roles = Roles()
    instance = {"case_id": case_id, "cycle": "0" * 64, "mode": "full"}
    with graph.dispatch_context(roles) as context:
        result = graph_substrate.run(run.root.resolve(), graph.CASE, instance)
    assert context["errors"] == []
    assert len(roles.calls) == 1
    assert result["interrupts"][0]["kind"] == "proposer_answers"


def test_started_dispatch_without_receipt_never_dispatches_twice(tmp_path):
    from ravel.workflow.graphs import rdj as graph
    run, case_id = simple(tmp_path)
    body = """class Lost(Roles):
    def dispatch(self,rundir,request):
        (rundir/'dispatch-count').write_text('1')
        os._exit(74)
rdj.run_roles(root,case_id,Lost())
"""
    assert crash_process(run, case_id, body) == 74
    roles = Roles()
    result = graph.run(run.root, case_id, roles)
    assert (run.root / "dispatch-count").read_text() == "1"
    assert roles.calls == []
    assert len(custody.rows(run.root, "roles")) == 1
    assert result["graph"]["interrupts"][0]["kind"] == "reconcile_evidence"


def test_cli_registers_run(capsys):
    with pytest.raises(SystemExit) as result:
        rdj.main(["run", "--help"])
    assert result.value.code == 0
    assert "--case-id" in capsys.readouterr().out
