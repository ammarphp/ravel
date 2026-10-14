"""Decision justification (RDJ) core: T1-T9 and T15 of the design, on synthetic runs and receipted roles."""
import json

import pytest

from ravel.workflow import decision_case as dc
from ravel.workflow import evidence_queue, rdj_anchor, rdj_custody
from ravel.workflow import rdj_loop as rdj

from rdj_fixtures import (PROMPT, PROPOSER, Roles, Run, add, critic, critic_once, node, reviewer, said, sha,
                          two_level_r2, verifier)

SMOKE = {"mode": "smoke", "points": 1, "walltime_h": [0.1, 0.2]}


@pytest.fixture(autouse=True)
def custody(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))


def context(run, **extra):
    return {"rundir": str(run.root), "input_snapshot": rdj_custody.input_snapshot(run.root), "generated": [],
            "action_pins": [], **extra}


# ---------------------------------------------------------------- T1 self-grounding and circularity

def test_t1_planted_self_grounding_chain_is_refused_and_named(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "The scan is ready"))
    rdj.run_roles(run.root, case_id, Roles())
    add(run, case_id, "A", node("B", "The configuration was checked"))
    rdj.run_roles(run.root, case_id, Roles())
    planted = run.put("inputs/notes/check.json", {"checked": True})  # written after the commit by the proposer
    add(run, case_id, "B", node("C", "The check file says so",
                                anchors=[{"kind": "input_artifact", "binding": planted, "locator": "/checked"}]))
    add(run, case_id, "action", node("alt", "Wait", kind="alternative"), kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, Roles())
    case = run.case(case_id)
    assert [a["verified"] for a in case["anchors"]] == ["generated"]
    assert all(e["review"]["entailment"] == "holds" for e in case["edges"])
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    grounding = [i for i in refused.value.items if i["code"] == "self_grounding"]
    assert grounding and "action -> A -> B -> C" in grounding[0]["message"]
    assert [e.code for e in rdj.gate_errors(run.root, "launch", run.action())] == ["rdj_receipt_missing"]


@pytest.mark.parametrize("binding", [
    {"source": "user_steering", "path": "inputs/request.json"},
    {"source": "prompt", "path": "inputs/request.json"},
])
def test_t1a_ravel_request_file_is_not_a_user_requirement(tmp_path, binding):
    run = Run(tmp_path / "run")
    text = "keep the approved binning"
    run.put("inputs/request.json", PROMPT)
    start = PROMPT.index(text)
    anchor = {"id": "x", "kind": "user_requirement", "locator": "", "value": None, "quantity": None, "verified": None,
              "binding": {**binding, "sha256": sha(PROMPT), "start": start, "end": start + len(text), "text": text}}
    assert rdj_anchor.verify(anchor, run.root, context=context(run)) == "invalid"


def test_t1b_anchor_that_is_the_actions_own_output_is_circular(tmp_path):
    run = Run(tmp_path / "run")
    own = run.stage("result", "outputs/plan.json", {"points": 3})  # the action pins exactly these bytes
    anchor = {"id": "x", "value": None, "quantity": None, "verified": None, **own}
    status, reason = rdj_anchor.verify_detail(anchor, run.root, context=context(run, action_pins=[run.action_pin]))
    assert status == "invalid" and "circular" in reason
    legacy = {**anchor, "kind": "external_source"}
    assert rdj_anchor.verify(legacy, run.root, context=context(run)) == "invalid"


# ---------------------------------------------------------------- T2 unsupported edge

def test_t2_failed_edge_blocks_authorization_even_when_the_verifier_authorizes(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    policy = rdj_anchor.policy()
    policy["classes"]["R2"]["revision_rounds"] = 0
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    case_id = two_level_r2(run)
    failing = reviewer({"A->B": {"entailment": "fails", "code": "decision_does_not_follow",
                                 "reason": "a completed smoke stage does not show physics correctness"}})
    rdj.run_roles(run.root, case_id, Roles(edge_reviewer=failing, verifier=verifier("authorize")))
    assert run.case(case_id)["verification"]["outcome"] == "authorize"
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    assert any(i["code"] == "edge_blocked" and i["target"] == "A->B" for i in refused.value.items)
    assert rdj.gate_errors(run.root, "bulk", run.action())[0].code == "rdj_receipt_missing"


def test_r2_case_authorizes_and_the_gate_accepts_only_the_exact_action(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    rdj.run_roles(run.root, case_id, Roles())
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize" and receipt["class"] == "R2"
    assert receipt["attestation_summary"]["distinct_sessions"] and receipt["attestation_summary"]["distinct_actors"]
    assert set(receipt) == {"schema_version", "kind", "receipt_id", "case_sha256", "case", "action_digest", "gate",
                            "class", "outcome", "attestation_summary", "policy_sha256", "open_a_findings",
                            "unresolved_branches", "exploratory", "authorized_utc"}
    assert rdj.gate_errors(run.root, "launch", run.action()) == []
    assert rdj.gate_errors(run.root, "bulk", run.action()) == []
    other_pin = run.put("outputs/other.json", {"points": 4})
    other = {**run.action(), "digest": other_pin["sha256"], "pins": [other_pin]}
    assert rdj.gate_errors(run.root, "launch", other)[0].code == "rdj_receipt_missing"


# ---------------------------------------------------------------- T3 affected branches

def test_t3_revision_rereviews_only_affected_branch_and_anchor_change_invalidates_its_ancestors(tmp_path):
    run = Run(tmp_path / "run")
    log = []
    finding = {"id": "F1", "code": "missing_evidence", "targets": ["X2"], "materiality": "A",
               "evidence_class": "code_check", "evidence_locators": [run.check_result("probe")], "request": None}
    roles = Roles(edge_reviewer=reviewer(log=log), critic=critic_once([finding]))
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("X1", "Branch X holds"), node("Y1", "Branch Y holds"))
    rdj.run_roles(run.root, case_id, roles)
    add(run, case_id, "X1", node("X2", "X is measured", anchors=[run.stage("x", "outputs/x.json", {"v": 1})]))
    y_anchor = {"kind": "input_artifact", "binding": run.pin("inputs/cards/settings.json"), "locator": "/bins"}
    add(run, case_id, "Y1", node("Y2", "Y uses the approved binning", anchors=[y_anchor]))
    add(run, case_id, "action", node("alt", "Do nothing", kind="alternative"), kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, roles)
    before = {e["id"]: e["review"] for e in run.case(case_id)["edges"]}
    calls_before = len(log)
    rdj.answer(run.root, case_id, [{"op": "revise_node", "node_id": "X2", "addresses": ["F1"],
                                    "fields": {"anchors": [run.stage("x2", "outputs/x2.json", {"v": 2})]}}])
    rdj.run_roles(run.root, case_id, roles)
    assert log[calls_before:] == [["X1->X2", "action->X1"]]  # one batched call, affected edges only
    after = {e["id"]: e["review"] for e in run.case(case_id)["edges"]}
    for kept in ("action->Y1", "Y1->Y2", "action->alt"):
        assert after[kept] == before[kept]
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"
    # Change the bytes under Y: Y and its ancestors lose their reviews; X keeps its own.
    (run.root / "inputs/cards/settings.json").write_text(json.dumps({"bins": 5}))
    rdj.next_challenges(run.root, case_id)
    edges = {e["id"]: e["review"] for e in run.case(case_id)["edges"]}
    assert edges["Y1->Y2"] is None and edges["action->Y1"] is None
    assert edges["X1->X2"] is not None and edges["action->alt"] is not None
    assert rdj.gate_errors(run.root, "launch", run.action())  # the receipt no longer holds


# ---------------------------------------------------------------- T4 low-risk reversible action

def test_t4_smoke_launch_is_r0_one_hop_and_no_model_call(tmp_path):
    run = Run(tmp_path / "run", cost=SMOKE)
    roles = Roles()
    case_id = rdj.open_case(run.root, "launch", run.action("smoke_launch", "Run a local smoke"), PROPOSER)
    add(run, case_id, "action", node("ready", "The cards were validated",
                                     anchors=[run.stage("validate", "outputs/cards-ok.json", {"ok": True})]))
    rdj.run_roles(run.root, case_id, roles)
    receipt = rdj.authorize(run.root, case_id)
    case = run.case(case_id)
    assert receipt["class"] == "R0" and receipt["outcome"] == "authorize"
    assert len(case["edges"]) == 1 and case["critique"] is None and case["verification"] is None
    assert roles.calls == []


def test_t4_novel_route_raises_smoke_to_r1_with_a_single_model_call(tmp_path):
    run = Run(tmp_path / "run", cost=SMOKE)
    roles = Roles()
    case_id = rdj.open_case(run.root, "launch", run.action("smoke_launch", "Run a local smoke"), PROPOSER,
                            facts={"route": "new-backend"})
    add(run, case_id, "action", node("ready", "The cards were validated",
                                     anchors=[run.stage("validate", "outputs/cards-ok.json", {"ok": True})]))
    rdj.run_roles(run.root, case_id, roles)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["class"] == "R1" and [r for r, _ in roles.calls] == ["edge_reviewer"]


# ---------------------------------------------------------------- T5 triggers

def test_t5_conflicting_anchors_deepen_the_branch(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen variant B"), PROPOSER)
    one = run.stage("m1", "outputs/m1.json", {"rate": 1.0}, locator="/rate")
    two = run.stage("m2", "outputs/m2.json", {"rate": 1.4}, locator="/rate")
    add(run, case_id, "action", node("P", "Variant B has the higher rate", anchors=[{**one, "quantity": "rate"}]),
        node("Q", "The rate was re-measured", anchors=[{**two, "quantity": "rate"}]))
    rdj.run_roles(run.root, case_id, Roles())
    open_targets = {c["target"]: c["reason"] for c in rdj.next_challenges(run.root, case_id)}
    assert set(open_targets) == {"P", "Q"} and all("depth 2" in r for r in open_targets.values())


def test_t5_novelty_raises_class_and_declared_low_confidence_cannot_lower_it(tmp_path):
    run = Run(tmp_path / "run")
    base, _ = rdj.compute_class(run.root, "research_choice", run.action("screening_choice"))
    novel, factors = rdj.compute_class(run.root, "research_choice", run.action("screening_choice"),
                                       facts={"route": "unseen-method"})
    assert (base, novel) == ("R1", "R2") and factors["novelty"]
    case_id = rdj.open_case(run.root, "launch", run.action(), {**PROPOSER, "confidence": "low"},
                            declared={"class": "R0"})
    assert run.case(case_id)["risk"]["class"] == "R2"


# ---------------------------------------------------------------- T6 critic cannot regenerate

@pytest.mark.parametrize("output", [
    {"findings": [], "revised_plan": "Launch fewer points instead."},
    {"findings": [{"id": "F", "code": "rewrite_plan", "targets": ["B"], "materiality": "A", "evidence_locators": [],
                   "evidence_class": "opinion", "request": None}]},
    {"findings": [{"id": "F", "code": "unsupported_claim", "targets": ["B"], "materiality": "A",
                   "evidence_class": "opinion", "evidence_locators": [], "request": None, "plan": "Do it this way."}]},
    {"findings": [{"id": "F", "code": "alternative_not_considered", "targets": ["action"], "materiality": "B",
                   "evidence_class": "opinion", "evidence_locators": [], "request": None,
                   "alternative": "Use a smaller grid. Then rerun the fit with new cuts."}]},
])
def test_t6_critic_output_outside_the_closed_schema_is_rejected(tmp_path, output):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    roles = Roles(critic=lambda payload: said(output, "critic"))
    with pytest.raises(ValueError):
        rdj.run_roles(run.root, case_id, roles)
    assert run.case(case_id)["critique"] is None


# ---------------------------------------------------------------- T7 critic and verifier separation

def test_t7_same_session_critic_and_verifier_refused_at_r3(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run, gate="delivery", kind="deliver_claims")
    rdj.run_roles(run.root, case_id, Roles())
    add(run, case_id, "B", node("C", "The validator certified it",
                                anchors=[run.stage("cert", "outputs/cert.json", {"pass": True}, kind="measurement")]))
    roles = Roles(critic=critic(name="panel", session="shared"), verifier=verifier(name="panel-2", session="shared"))
    with pytest.raises(rdj.IndependenceError, match="R3"):
        rdj.run_roles(run.root, case_id, roles)


def test_t7_same_session_at_r2_without_a_human_is_self_attested_and_refused(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    roles = Roles(critic=critic(name="panel", session="shared"), verifier=verifier(name="other", session="shared"))
    with pytest.raises(rdj.IndependenceError, match="self_attested"):
        rdj.run_roles(run.root, case_id, roles)


def test_t7_same_session_at_r2_with_a_recorded_human_approval_is_labelled_self_attested(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    run.approve(case_id)
    roles = Roles(critic=critic(name="panel", session="shared"), verifier=verifier(name="other", session="shared"))
    rdj.run_roles(run.root, case_id, roles)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["attestation_summary"]["verifier"] == "self_attested"
    assert receipt["attestation_summary"]["human_approver"]


# ---------------------------------------------------------------- T8 proposal committed first

def test_t8_changed_action_bytes_invalidate_the_whole_case(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    journal = (run.root / f"rdj/journal/{case_id}.jsonl").read_text().splitlines()
    assert json.loads(journal[0])["record"]["event"] == "proposal_committed"
    add(run, case_id, "action", node("A", "Ready"))
    (run.root / "outputs/plan.json").write_text(json.dumps({"points": 300}))
    with pytest.raises(rdj.CaseInvalidated, match="new proposal commit"):
        rdj.next_challenges(run.root, case_id)
    with pytest.raises(rdj.CaseInvalidated):
        rdj.authorize(run.root, case_id)
    assert rdj.status(run.root, case_id)["phase"] == "invalidated"


def test_t8_revising_the_committed_action_node_invalidates(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    finding = {"id": "F1", "code": "risk_underestimated", "targets": ["action"], "materiality": "A",
               "evidence_class": "opinion", "evidence_locators": [], "request": None}
    rdj.run_roles(run.root, case_id, Roles(critic=critic([finding])))
    with pytest.raises(rdj.CaseInvalidated):
        rdj.answer(run.root, case_id, [{"op": "revise_node", "node_id": "action", "addresses": ["F1"],
                                        "fields": {"assertion": "Launch fewer points"}}])


# ---------------------------------------------------------------- T9 requirement spans and invariants

def test_t9_requirement_spans_and_invariant_ids_are_checked(tmp_path):
    run = Run(tmp_path / "run")
    good = {"id": "r", "locator": "", "value": None, "quantity": None, "verified": None,
            **run.prompt_span("keep the approved binning")}
    assert rdj_anchor.verify(good, run.root) == "external"
    shifted = json.loads(json.dumps(good)); shifted["binding"]["start"] += 1; shifted["binding"]["end"] += 1
    assert rdj_anchor.verify(shifted, run.root) == "invalid"
    registry = rdj_anchor.sha256_file(rdj_anchor.INVARIANTS)
    known = {"id": "i", "kind": "invariant", "binding": {"invariant_id": "cls-95-exclusion", "registry_sha256": registry},
             "locator": "", "value": None, "quantity": None, "verified": None}
    assert rdj_anchor.verify(known, run.root) == "external"
    unknown = json.loads(json.dumps(known)); unknown["binding"]["invariant_id"] = "made-up-rule"
    assert rdj_anchor.verify(unknown, run.root) == "invalid"


# ---------------------------------------------------------------- T15 requests become work items

def test_t15_unresolved_branch_request_becomes_a_typed_work_item(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice", "Screen variant B"), PROPOSER)
    add(run, case_id, "action", node("P", "Variant B separates the hypotheses"))
    rdj.run_roles(run.root, case_id, Roles())
    request = {"kind": "experiment", "description": "Run the discriminating comparison of variants A and B"}
    add(run, case_id, "P", node("Q", "The two variants predict different rates",
                                unknowns=[{"question": "Do they differ on the held-out sample?", "request": request}]))
    rdj.run_roles(run.root, case_id, Roles())
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "gather_evidence" and receipt["unresolved_branches"] == 1
    items = evidence_queue.items(run.root, case_id=case_id)
    assert [(i["route"], i["target"], i["request"]) for i in items] == [("research_cycle", "Q", request)]
    assert items[0]["case"]["path"] == f"rdj/cases/{case_id}.json"
    assert rdj.gate_errors(run.root, "research_choice", run.action("screening_choice"))[0].code == "rdj_not_authorized"


# ---------------------------------------------------------------- owner additions

def test_tuning_change_carries_its_class_into_deviations(tmp_path):
    run = Run(tmp_path / "run")
    tuning = {"class": "recipe_restoration", "parameter": "shower.tune", "from": "default", "to": "published-recipe",
              "reason": "The published recipe names this tune"}
    case_id = two_level_r2(run, gate="deviation", kind="tuning_change", tuning=tuning,
                           leaf_anchor=run.prompt_span("keep the approved binning"))
    rdj.run_roles(run.root, case_id, Roles())
    receipt = rdj.authorize(run.root, case_id)
    ledger = (run.root / "DEVIATIONS.md").read_text()
    assert receipt["outcome"] == "authorize"
    assert "tuning class: recipe_restoration" in ledger and "outputs/plan.json" in ledger and receipt["receipt_id"] in ledger
    with pytest.raises(ValueError, match="tuning change class"):
        rdj.open_case(run.root, "deviation", run.action("tuning_change"), PROPOSER, tuning={**tuning, "class": "guess"})
    assert len(rdj_custody.rows(run.root, "cases")) == 1  # a refused proposal is never committed


def test_analysis_choice_without_practice_anchor_stays_exploratory(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("choice", "Use four bins", recommends_choice=True))
    rdj.run_roles(run.root, case_id, Roles())
    add(run, case_id, "choice", node("why", "Four bins pass the closure test",
                                     anchors=[run.stage("closure", "outputs/closure.json", {"ok": True})]))
    add(run, case_id, "action", node("alt", "Use eight bins", kind="alternative"), kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, Roles())
    assert rdj.status(run.root, case_id)["exploratory"] == ["choice"]
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    assert [i["target"] for i in refused.value.items if i["code"] == "exploratory_choice"] == ["choice"]


def test_analysis_choice_with_a_user_requirement_is_not_exploratory(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("choice", "Keep the approved binning", recommends_choice=True))
    rdj.run_roles(run.root, case_id, Roles())
    add(run, case_id, "choice", node("asked", "The user asked for it",
                                     anchors=[run.prompt_span("keep the approved binning")]))
    add(run, case_id, "action", node("alt", "Rebin", kind="alternative"), kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, Roles())
    assert rdj.status(run.root, case_id)["exploratory"] == []
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"


def test_budget_exhaustion_yields_escalate(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    policy = rdj_anchor.policy()
    policy["classes"]["R2"]["max_model_calls"] = 2
    monkeypatch.setattr(rdj_anchor, "policy", lambda: policy)
    rdj.run_roles(run.root, case_id, Roles())
    assert rdj.status(run.root, case_id)["phase"] == "budget_exhausted"
    assert rdj.authorize(run.root, case_id)["outcome"] == "escalate"


class GraphHost:
    """A fixture agent host for agent_graph: reads the RDJ payload from the pinned input or the
    blind role packet and answers as a provider transport would."""

    identity = {"test_fixture": "rdj-graph-host"}

    def __init__(self, responders):
        self.responders = responders
        self.nodes = []

    def execute(self, item, request, control):
        from pathlib import Path
        self.nodes.append(item)
        if item["packet"] is not None:
            payload = json.loads((Path(item["packet"]["path"]) / "artifacts/rdj-payload.json").read_text())
        else:
            payload = json.loads(Path(item["inputs"][0]["path"]).read_text())
        role = {"rdj_edge_reviewer": "edge_reviewer", "rdj_critic": "critic", "rdj_verifier": "verifier"}[item["role"]]
        said_ = self.responders[role](payload)
        result = {"kind": "model_result", "value": said_["output"],
                  "transport": {"adapter": "fixture-http", "execution_mode": "provider_http",
                                "request_id": request["request_id"], "actor_id": said_["actor"],
                                "requested_model": "m", "observed_model": "m"},
                  "isolation": {"fresh_request": True, "fresh_context": True, "parent_transcript_supplied": False}}
        return control.call("fixture-http", "model", request, lambda: result, output_tokens=64)


def test_roles_dispatch_through_agent_graph_on_registered_rdj_roles(tmp_path):
    pytest.importorskip("langgraph")
    run = Run(tmp_path / "run")
    host = GraphHost({"edge_reviewer": reviewer(), "critic": critic(), "verifier": verifier()})
    rdj_custody.register_host(run.root, host.identity)  # the operator path registers its host
    case_id = two_level_r2(run, roles=rdj.AgentHostDispatcher(host, model="m"))
    rdj.run_roles(run.root, case_id, rdj.AgentHostDispatcher(host, model="m"))
    assert [n["role"] for n in host.nodes][-2:] == ["rdj_critic", "rdj_verifier"]
    blind = [n for n in host.nodes if n["role"] in ("rdj_critic", "rdj_verifier")]
    assert all(n["packet"] is not None and n["inputs"] == [] and n["action"] == "model" for n in blind)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize"
    assert receipt["attestation_summary"]["critic"] == "transport_attested"


def test_edge_reviewer_cannot_review_its_own_hop(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("A", "Ready"))
    with pytest.raises(rdj.IndependenceError):
        rdj.run_roles(run.root, case_id, Roles(edge_reviewer=reviewer(name="proposer")))


def test_v1_cases_still_read_and_unknown_versions_are_refused():
    v1 = {"schema_version": 1, "action": "Do it", "root": "r", "triggers": [{"kind": "novelty", "reason": "new"}],
          "budget": {"max_nodes": 2, "max_depth": 1},
          "nodes": [{"id": "r", "author_id": "p", "assertion": "Root", "rationale": "why", "material": True,
                     "assumptions": [], "unknowns": [], "anchors": [],
                     "review": {"reviewer_id": "q", "decision": "unresolved", "reason": "no anchor"}}],
          "edges": []}
    assert dc.read_any(v1)["kind"] == "scientific_decision_case"
    with pytest.raises(ValueError):
        dc.read_any({"schema_version": 3})


def test_cli_opens_answers_and_authorizes_through_ravel_rdj(tmp_path, capsys):
    from ravel import cli
    run = Run(tmp_path / "run", cost=SMOKE)
    files = tmp_path / "files"
    files.mkdir()
    (files / "action.json").write_text(json.dumps(run.action("smoke_launch", "Run a smoke")))
    (files / "proposer.json").write_text(json.dumps(PROPOSER))
    assert cli.main(["rdj", "case", "--rundir", str(run.root), "--open", "--gate", "smoke",
                     "--action", str(files / "action.json"), "--proposer", str(files / "proposer.json")]) == 0
    opened = json.loads(capsys.readouterr().out)
    case_id, (first,) = opened["case_id"], opened["challenges"]
    anchor = run.stage("v", "outputs/v.json", {"ok": 1})
    (files / "answers.json").write_text(json.dumps([{"op": "add_child", "challenge_id": first["id"], "parent": "action",
                                                     "node": node("ok", "Validated", anchors=[anchor])}]))
    assert cli.main(["rdj", "answer", "--rundir", str(run.root), "--case-id", case_id,
                     "--answers", str(files / "answers.json")]) == 0
    capsys.readouterr()
    assert cli.main(["rdj", "status", "--rundir", str(run.root), "--case-id", case_id]) == 0
    assert json.loads(capsys.readouterr().out)["phase"] == "ready"
    assert cli.main(["rdj", "authorize", "--rundir", str(run.root), "--case-id", case_id]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "authorize"
    assert cli.main(["rdj", "status", "--rundir", str(run.root)]) == 0
    assert json.loads(capsys.readouterr().out)["cases"][0]["case_id"] == case_id
    assert cli.main(["decision-case", "--case", str(run.root / f"rdj/cases/{case_id}.json")]) == 0
