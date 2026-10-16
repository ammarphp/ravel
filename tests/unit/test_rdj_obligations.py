"""Fictional, receipted controls for evidence obligations and bounded review effort."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import decision_case as dc
from ravel.workflow import rdj_loop as rdj

from rdj_fixtures import PROPOSER, Roles, Run, add, node, reviewer, sha, two_level_r2


@pytest.fixture(autouse=True)
def custody(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("RAVEL_NATIVE_BIN", raising=False)


def test_baseline_untyped_review_effort(tmp_path):
    run, roles = Run(tmp_path / "run"), Roles()
    case_id = two_level_r2(run, roles=roles)
    rdj.run_roles(run.root, case_id, roles)
    rdj.authorize(run.root, case_id)
    assert [role for role, _ in roles.calls] == ["edge_reviewer", "edge_reviewer", "critic", "verifier"]
    assert len(run.case(case_id)["edges"]) == 3
    print("synthetic baseline: 4 model calls; 3 reviewed edges; 2 support steps")


def test_typed_one_hop_closes_without_depth_padding(tmp_path):
    run, roles = Run(tmp_path / "run"), Roles()
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    anchor = run.stage("witness", "outputs/witness.json", {"ready": True})
    add(run, case_id, "action", node("claim", "The retained witness supports this action", anchors=[anchor],
                                    evidence_obligations=["tool_output"]))
    add(run, case_id, "action", node("other", "Use a smaller retained task", kind="alternative"),
        kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, roles)
    assert rdj.next_challenges(run.root, case_id) == []
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"
    assert [role for role, _ in roles.calls] == ["edge_reviewer", "critic", "verifier"]
    print("synthetic typed: 3 model calls; 2 reviewed edges; 1 support step")


def test_untyped_one_hop_still_exhibits_the_depth_hold(tmp_path):
    run, roles = Run(tmp_path / "run"), Roles()
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("claim", "The witness supports the action",
                                    anchors=[run.stage("w", "outputs/w.json", {"ready": True})]))
    rdj.run_roles(run.root, case_id, roles)
    assert "needs support to depth 2 (now 1)" in reasons(run, case_id)
    assert [role for role, _ in roles.calls] == ["edge_reviewer"]


def one_hop(run, *, gate="launch", obligations=("tool_output",), anchors=None, confidence=None, proposer=None,
            roles=None, facts=None, review_scope=None):
    roles = roles or Roles()
    case_id = rdj.open_case(run.root, gate, run.action(), proposer or PROPOSER, facts=facts,
                            **({"review_scope": review_scope} if review_scope is not None else {}))
    if anchors is None:
        anchors = [run.stage("witness", "outputs/witness.json", {"ready": True})]
    add(run, case_id, "action", node("claim", "A retained witness supports the action", anchors=anchors,
                                    confidence=confidence, evidence_obligations=list(obligations)))
    add(run, case_id, "action", node("other", "Use a smaller retained task", kind="alternative"),
        kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, roles)
    return case_id, roles


def reasons(run, case_id):
    return " ".join(c["reason"] for c in rdj.next_challenges(run.root, case_id))


def attach(run, case_id, anchor):
    challenge = next(c for c in rdj.next_challenges(run.root, case_id) if c["target"] == "claim")
    rdj.answer(run.root, case_id, [{"op": "attach_anchor", "node_id": "claim",
                                  "challenge_id": challenge["id"], "anchor": anchor}])


def test_wrong_kind_does_not_discharge_even_beyond_legacy_minimum(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("parent", "The declaration needs a measurement",
                                    evidence_obligations=["measurement"]))
    rdj.run_roles(run.root, case_id, Roles())
    add(run, case_id, "parent", node("claim", "A different witness was retained",
                                    anchors=[run.stage("w", "outputs/w.json", {"ready": True})]))
    rdj.run_roles(run.root, case_id, Roles())
    assert "requires measurement" in reasons(run, case_id)
    with pytest.raises(rdj.OpenItems):
        rdj.authorize(run.root, case_id)


def test_generated_kind_is_not_external_evidence(tmp_path):
    run = Run(tmp_path / "run")
    unregistered = run.stage("w", "outputs/w.json", {"ready": True}, register=False)
    case_id, _ = one_hop(run, anchors=[unregistered])
    with pytest.raises(rdj.OpenItems):
        rdj.authorize(run.root, case_id)


def test_sibling_evidence_cannot_discharge_another_branch(tmp_path):
    run, roles = Run(tmp_path / "run"), Roles()
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action",
        node("claim", "This claim requires its own measurement", evidence_obligations=["measurement"],
             anchors=[run.stage("w", "outputs/w.json", {"ready": True})]),
        node("sibling", "A different claim has a measurement", evidence_obligations=["measurement"],
             anchors=[run.stage("m", "outputs/m.json", {"observed": True}, kind="measurement")]))
    rdj.run_roles(run.root, case_id, roles)
    assert "claim requires measurement evidence" in reasons(run, case_id)


def test_ancestor_evidence_cannot_discharge_a_child_obligation(tmp_path):
    run, roles = Run(tmp_path / "run"), Roles()
    case_id = rdj.open_case(run.root, "launch", run.action(), PROPOSER)
    add(run, case_id, "action", node("parent", "A parent measurement was retained", anchors=[
        run.stage("m", "outputs/m.json", {"observed": True}, kind="measurement")]))
    rdj.run_roles(run.root, case_id, roles)
    add(run, case_id, "parent", node("claim", "The child needs a different measurement",
                                    evidence_obligations=["measurement"],
                                    anchors=[run.stage("w", "outputs/w.json", {"ready": True})]))
    rdj.run_roles(run.root, case_id, roles)
    assert "claim requires measurement evidence" in reasons(run, case_id)


@pytest.mark.parametrize("where", ["root", "claim"])
def test_low_confidence_requires_additional_distinct_matching_evidence(tmp_path, where):
    run = Run(tmp_path / "run")
    anchor = run.stage("w", "outputs/w.json", {"first": True, "second": True}, locator="/first")
    duplicate = {**anchor, "locator": "/second"}
    case_id, roles = one_hop(run, anchors=[anchor, duplicate],
                             proposer={**PROPOSER, "confidence": "low"} if where == "root" else None,
                             confidence="low" if where == "claim" else None)
    assert "2 distinct source(s) (now 1)" in reasons(run, case_id)
    attach(run, case_id, run.stage("extra", "outputs/extra.json", {"ready": True}))
    rdj.run_roles(run.root, case_id, roles)
    assert rdj.next_challenges(run.root, case_id) == []
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"


@pytest.mark.parametrize("kind", ["tool_output", "measurement", "input_artifact"])
def test_copied_bytes_do_not_discharge_additional_evidence(tmp_path, kind):
    inputs = [("inputs/one.json", {"ready": True}), ("inputs/two.json", {"ready": True})]
    run = Run(tmp_path / "run", extra_inputs=inputs)
    if kind == "input_artifact":
        anchors = [{"kind": kind, "binding": run.pin(path)} for path, _ in inputs]
    else:
        anchors = [run.stage(name, f"outputs/{name}.json", {"ready": True}, kind=kind)
                   for name in ("one", "two")]
    case_id, roles = one_hop(run, anchors=anchors, obligations=(kind,), confidence="low")
    assert len(roles.calls) == 1, {"calls": len(roles.calls), "reviewed_edges": len(run.case(case_id)["edges"])}
    assert "2 distinct source(s) (now 1)" in reasons(run, case_id)
    with pytest.raises(rdj.OpenItems):
        rdj.authorize(run.root, case_id)
    assert [role for role, _ in roles.calls] == ["edge_reviewer"]
    assert len(run.case(case_id)["edges"]) == 2


def test_copied_bytes_remain_common_evidence_at_consequential_boundary(tmp_path):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "delivery", run.action(), PROPOSER)
    add(run, case_id, "action", *(node(name, "The retained evidence supports this claim",
            anchors=[run.stage(name, f"outputs/{name}.json", {"ready": True})],
            evidence_obligations=["tool_output"]) for name in ("one", "two")))
    assert [item["claims"] for item in rdj.common_mode_anchors(run.root, case_id)] == [["one", "two"]]


def test_additional_matching_sources_do_not_erase_conflict(tmp_path):
    run = Run(tmp_path / "run")
    anchors = [run.stage("a", "outputs/a.json", {"rate": 1}, locator="/rate"),
               run.stage("b", "outputs/b.json", {"rate": 4}, locator="/rate"),
               run.stage("c", "outputs/c.json", {"rate": 4}, locator="/rate")]
    case_id, _ = one_hop(run, anchors=anchors)
    assert "conflicting external evidence resolved" in reasons(run, case_id)
    with pytest.raises(rdj.OpenItems):
        rdj.authorize(run.root, case_id)


def test_typed_high_class_keeps_tool_and_transport_requirements(tmp_path):
    run = Run(tmp_path / "run")
    case_id, roles = one_hop(run, gate="delivery")
    assert run.case(case_id)["risk"]["class"] == "R3"
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"
    assert [role for role, _ in roles.calls] == ["edge_reviewer", "critic", "verifier"]


def test_typed_high_class_cannot_replace_tool_with_user_text(tmp_path):
    run = Run(tmp_path / "run")
    case_id, _ = one_hop(run, gate="delivery", obligations=("user_requirement",),
                         anchors=[run.prompt_span("Set a limit")])
    assert "needs a tool-output or measurement anchor" in reasons(run, case_id)
    with pytest.raises(rdj.OpenItems):
        rdj.authorize(run.root, case_id)


def test_typed_high_class_cannot_replace_transport_with_host_attestation(tmp_path):
    run = Run(tmp_path / "run")
    case_id, _ = one_hop(run, gate="delivery", roles=Roles(edge_reviewer=reviewer(attestation="host_attested")))
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    assert "attestation_insufficient" in {row["code"] for row in refused.value.items}


def test_root_obligation_is_discharged_by_supporting_evidence(tmp_path):
    run, roles = Run(tmp_path / "run"), Roles()
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice"), PROPOSER,
                            evidence_obligations=["tool_output"])
    add(run, case_id, "action", node("claim", "The witness supports the choice",
                                    anchors=[run.stage("w", "outputs/w.json", {"ready": True})]))
    rdj.run_roles(run.root, case_id, roles)
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"
    payload = roles.calls[0][1]
    assert run.case(case_id)["nodes"][0]["evidence_obligations"] == ["tool_output"]
    assert payload["edges"][0]["parent"]["evidence_obligations"] == ["tool_output"]


def test_maximum_depth_is_hard_even_for_discharged_obligations(tmp_path, monkeypatch):
    run = Run(tmp_path / "run")
    case_id, _ = one_hop(run)
    case, state, _ = rdj._load(run.root, case_id)
    policy = deepcopy(rdj.anchor_check.policy())
    policy["classes"]["R2"]["max_depth"] = 0
    monkeypatch.setattr(rdj.anchor_check, "policy", lambda: policy)
    _, unresolved, _, closed = rdj._frontier(case, state, "R2")
    assert not closed and "claim" in unresolved


@pytest.mark.parametrize("obligations", [[], ["unknown_kind"], ["tool_output", "tool_output"], "tool_output", None])
def test_typed_declaration_is_strict(tmp_path, obligations):
    run = Run(tmp_path / "run")
    case_id = rdj.open_case(run.root, "research_choice", run.action("screening_choice"), PROPOSER)
    with pytest.raises(ValueError, match="evidence obligations"):
        add(run, case_id, "action", node("claim", "A declaration", evidence_obligations=obligations))


def test_obligation_changes_invalidate_merkle_review_without_changing_legacy_shape(tmp_path):
    run = Run(tmp_path / "run")
    case_id = two_level_r2(run)
    case = run.case(case_id)
    before = dc.merkle(case)
    altered = deepcopy(case)
    altered["nodes"][1]["evidence_obligations"] = ["measurement"]
    assert before["edges"] != dc.merkle(altered)["edges"]
    altered["nodes"][1]["unexpected"] = True
    with pytest.raises(ValueError):
        dc.validate_case_v2(altered)


def test_accepted_same_gate_reuses_without_calls_and_rechecks_evidence(tmp_path):
    run = Run(tmp_path / "run")
    case_id, roles = one_hop(run)
    receipt = rdj.authorize(run.root, case_id)
    call_count = len(roles.calls)
    for _ in range(3):
        assert rdj.gate_errors(run.root, "launch", run.action()) == []
        assert rdj.authorizing_receipt(run.root, "launch", run.action())["receipt"] == receipt
    assert len(roles.calls) == call_count
    run.put("outputs/witness.json", {"ready": False})
    assert rdj.gate_errors(run.root, "launch", run.action())
    assert rdj.authorizing_receipt(run.root, "launch", run.action()) is None


def test_acceptance_does_not_cross_gate_without_equivalence_contract(tmp_path):
    run = Run(tmp_path / "run")
    case_id, _ = one_hop(run, gate="delivery")
    rdj.authorize(run.root, case_id)
    assert rdj.authorizing_receipt(run.root, "final_task", run.action()) is None


def test_unwritten_gate_action_without_receipt_preserves_missing_receipt_refusal(tmp_path):
    from ravel.workflow import gate_wiring

    run = Run(tmp_path / "run")
    action = gate_wiring.value_action(run.root, "bulk_launch", {"points": 3}, "Synthetic bounded launch")
    before = {p.relative_to(run.root): p.read_bytes() for p in run.root.rglob("*") if p.is_file()}
    assert not (run.root / action["pins"][0]["path"]).exists()
    assert [error.code for error in rdj.gate_errors(run.root, "launch", action)] == ["rdj_receipt_missing"]
    assert rdj.authorizing_receipt(run.root, "launch", action) is None
    assert before == {p.relative_to(run.root): p.read_bytes() for p in run.root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("change", ["different_bytes", "copied_subject", "missing_subject", "empty_pins"])
def test_same_gate_receipt_cannot_authorize_another_supplied_pin_subject(tmp_path, change):
    run = Run(tmp_path / "run")
    case_id, roles = one_hop(run)
    receipt = rdj.authorize(run.root, case_id)
    assert len(roles.calls) == 3 and len(run.case(case_id)["edges"]) == 2
    assert rdj.authorizing_receipt(run.root, "launch", run.action())["receipt"] == receipt
    if change == "empty_pins":
        pins = []
    else:
        body = {"points": 8} if change == "different_bytes" else {"points": 3}
        pins = [run.put("outputs/other-plan.json", body)]
        if change == "missing_subject":
            (run.root / pins[0]["path"]).unlink()
    changed = {**run.action(), "pins": pins}
    accepted = rdj.authorizing_receipt(run.root, "launch", changed)
    assert accepted is None, {"change": change, "calls": len(roles.calls),
                              "reviewed_edges": len(run.case(case_id)["edges"])}
    assert rdj.gate_errors(run.root, "launch", changed)
    assert len(roles.calls) == 3
    assert rdj.authorizing_receipt(run.root, "launch", run.action())["receipt"] == receipt


def test_same_gate_pin_normalization_preserves_current_and_legacy_reuse(tmp_path):
    run = Run(tmp_path / "run")
    case_id, roles = one_hop(run)
    receipt = rdj.authorize(run.root, case_id)
    absolute = {**run.action_pin, "path": str(run.root / run.action_pin["path"])}
    for action in (run.action(pins=[absolute]),
                   {key: value for key, value in run.action().items() if key != "pins"}):
        assert rdj.authorizing_receipt(run.root, "launch", action)["receipt"] == receipt
    assert len(roles.calls) == 3 and len(run.case(case_id)["edges"]) == 2


def test_stale_acceptance_does_not_suppress_route_novelty(tmp_path):
    run, roles = Run(tmp_path / "run"), Roles()
    action = run.action(route="fictional-route")
    case_id = rdj.open_case(run.root, "launch", action, PROPOSER)
    add(run, case_id, "action", node("claim", "A retained witness supports this route",
                                    anchors=[run.stage("w", "outputs/w.json", {"ready": True})],
                                    evidence_obligations=["tool_output"]))
    add(run, case_id, "action", node("other", "Use a smaller retained task", kind="alternative"),
        kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, roles)
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"
    assert rdj.compute_class(run.root, "launch", action)[0] == "R2"
    run.put("outputs/w.json", {"ready": False})
    assert rdj.compute_class(run.root, "launch", action)[0] == "R3"


def test_saturated_class_does_not_transfer_acceptance_to_a_changed_route(tmp_path):
    run, roles = Run(tmp_path / "run"), Roles()
    action = run.action(route="fictional-route-a")
    case_id = rdj.open_case(run.root, "delivery", action, PROPOSER)
    add(run, case_id, "action", node("claim", "A retained witness supports this route", anchors=[
        run.stage("w", "outputs/w.json", {"ready": True})], evidence_obligations=["tool_output"]))
    add(run, case_id, "action", node("other", "Use a smaller retained task", kind="alternative"),
        kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, roles)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["class"] == "R3" and len(roles.calls) == 3
    assert len(run.case(case_id)["edges"]) == 2
    for changed in (run.action(route="fictional-route-b"),
                    run.action(facts={"route": "fictional-route-b"})):
        assert rdj.compute_class(run.root, "delivery", changed)[0] == "R3"
        assert rdj.authorizing_receipt(run.root, "delivery", changed) is None, {
            "calls": len(roles.calls), "reviewed_edges": len(run.case(case_id)["edges"])}
        assert rdj.gate_errors(run.root, "delivery", changed)
    assert len(roles.calls) == 3
    assert rdj.authorizing_receipt(run.root, "delivery", action)["receipt"] == receipt
    assert rdj.authorizing_receipt(run.root, "delivery", run.action())["receipt"] == receipt


def exploration_run(tmp_path, *, changes=None, supplied=True):
    contract = {"schema_version": 1, "kind": "rdj-exploration-contract", "scope": "exploration_only",
                "gate": "research_choice", "action_kind": "screening_choice",
                "action_digest": sha(json.dumps({"points": 3})), "execution": "broker_only",
                "hypothesis": "The fictional alternate rule predicts a different ordering",
                "question": "Does a supplied witness distinguish the two fictional rules?",
                "expected_outputs": ["outputs/comparison.json"],
                "bounds": {"max_broker_calls": 2, "max_model_calls": 0},
                "stop_condition": "Stop after the bounded witness query regardless of its answer",
                **(changes or {})}
    inputs = [("inputs/exploration.json", contract)] if supplied else []
    run = Run(tmp_path / "run", extra_inputs=inputs)
    if not supplied:
        run.put("inputs/exploration.json", contract)
    action = run.action("screening_choice", "Select a bounded fictional evidence comparison",
                        route="fictional-unknown-route", authorization_scope="exploration_only")
    return run, action


def exploration_case(run, action, *, tool=True, roles=None, **kwargs):
    roles = roles or Roles()
    case_id = rdj.open_case(run.root, "research_choice", action, PROPOSER,
                            exploration_contract=run.pin("inputs/exploration.json"), **kwargs)
    anchor = run.stage("w", "outputs/w.json", {"ready": True}) if tool else run.prompt_span("Set a limit")
    add(run, case_id, "action", node("claim", "A retained witness bounds the comparison", anchors=[anchor],
                                    evidence_obligations=["tool_output" if tool else "user_requirement"]))
    add(run, case_id, "action", node("other", "Retain the current fictional rule", kind="alternative"),
        kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, roles)
    return case_id, roles


def test_supplied_bounded_exploration_selects_experiment_without_scientific_acceptance(tmp_path):
    run, action = exploration_run(tmp_path)
    case_id, roles = exploration_case(run, action)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["class"] == "R2" and receipt["outcome"] == "authorize"
    assert receipt["authorization_scope"] == "exploration_only"
    assert receipt["execution_authorized"] is False and receipt["scientific_acceptance"] is False
    assert receipt["exploratory"] == ["action"]
    assert [role for role, _ in roles.calls] == ["edge_reviewer", "critic", "verifier"]
    for _, payload in roles.calls:
        shown = payload.get("case", payload)
        assert shown["exploration_contract"]["question"].startswith("Does a supplied witness")
        assert shown["authorization_scope"] == "exploration_only"
    assert rdj.authorizing_receipt(run.root, "research_choice", action)["receipt"] == receipt
    plain = {k: v for k, v in action.items() if k != "authorization_scope"}
    assert rdj.authorizing_receipt(run.root, "research_choice", plain) is None
    for gate in ("launch", "checkin2_accept", "delivery", "final_task"):
        assert rdj.authorizing_receipt(run.root, gate, action) is None
    assert rdj.authorizing_receipt(run.root, "research_choice", {**action, "kind": "promotion"}) is None
    assert rdj.compute_class(run.root, "research_choice", action)[0] == "R2"  # Exploration never accepts the route.


def test_bounded_exploration_keeps_high_class_tool_requirement(tmp_path):
    run, action = exploration_run(tmp_path)
    case_id, _ = exploration_case(run, action, tool=False, facts={"scope_change": True})
    assert run.case(case_id)["risk"]["class"] == "R3"
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    assert "branch_open" in {row["code"] for row in refused.value.items}


def test_bounded_exploration_keeps_high_class_transport_requirement(tmp_path):
    run, action = exploration_run(tmp_path)
    case_id, _ = exploration_case(run, action, facts={"scope_change": True},
                                  roles=Roles(edge_reviewer=reviewer(attestation="host_attested")))
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    assert "attestation_insufficient" in {row["code"] for row in refused.value.items}


@pytest.mark.parametrize("changes", [
    {"schema_version": True}, {"action_digest": "0" * 64}, {"scope": "scientific_acceptance"},
    {"execution": "native"}, {"question": ""}, {"stop_condition": ""}, {"expected_outputs": []},
    {"expected_outputs": ["../outputs/answer.json"]}, {"bounds": {"max_broker_calls": 9, "max_model_calls": 0}},
    {"bounds": {"max_broker_calls": 2, "max_model_calls": 25}},
    {"bounds": {"max_broker_calls": True, "max_model_calls": 0}},
    {"bounds": {"max_broker_calls": 2}}, {"unexpected_permission": True},
])
def test_exploration_contract_is_exact_finite_and_current_policy_bounded(tmp_path, changes):
    run, action = exploration_run(tmp_path, changes=changes)
    with pytest.raises(ValueError):
        rdj.open_case(run.root, "research_choice", action, PROPOSER,
                      exploration_contract=run.pin("inputs/exploration.json"))


def test_agent_written_contract_cannot_authorize_exploration(tmp_path):
    run, action = exploration_run(tmp_path, supplied=False)
    with pytest.raises(ValueError, match="independently supplied"):
        rdj.open_case(run.root, "research_choice", action, PROPOSER,
                      exploration_contract=run.pin("inputs/exploration.json"))


def test_exploration_contract_cannot_be_attached_to_launch_or_promotion(tmp_path):
    run, action = exploration_run(tmp_path)
    for gate, kind in (("launch", "screening_choice"), ("research_choice", "promotion")):
        with pytest.raises(ValueError, match="exploration-only"):
            rdj.open_case(run.root, gate, {**action, "kind": kind}, PROPOSER,
                          exploration_contract=run.pin("inputs/exploration.json"))


def test_exploration_contract_is_rechecked_after_authorization(tmp_path):
    run, action = exploration_run(tmp_path)
    case_id, _ = exploration_case(run, action)
    rdj.authorize(run.root, case_id)
    run.put("inputs/exploration.json", {"replaced": True})
    assert rdj.authorizing_receipt(run.root, "research_choice", action) is None


def test_cost_policy_has_separate_dimensions_with_legacy_spend_floor(tmp_path):
    run = Run(tmp_path / "run")
    policy = rdj.anchor_check.policy()
    assert "spend_usd_above" not in policy["high_consequence"]
    dimensions = policy["cost_dimensions"]
    assert dimensions["absolute_cost"]["raise_above_usd"] == 0
    assert dimensions["authorized_budget_fraction"]["raise_above"] is None
    _, factors = rdj.compute_class(run.root, "launch", run.action())
    assert factors["cost_dimensions"]["authorized_budget_fraction"]["status"] == "absent"


@pytest.mark.parametrize("kind,spend,expected", [
    ("smoke_launch", 0, "R0"), ("smoke_launch", 0.01, "R3"),
    ("single_point_launch", 0, "R1"), ("single_point_launch", 0.01, "R3"),
    ("bulk_launch", 0, "R2"), ("bulk_launch", 0.01, "R3"),
])
def test_cost_dimension_default_preserves_legacy_class(tmp_path, kind, spend, expected):
    run = Run(tmp_path / "run", cost={"mode": "smoke", "points": 1, "walltime_h": [0.1, 0.2],
                                      "spend_usd": spend})
    cls, _ = rdj.compute_class(run.root, "launch", run.action(kind))
    assert cls == expected


def test_budget_declarations_never_relax_positive_spend_floor(tmp_path):
    run = Run(tmp_path / "run", cost={"mode": "smoke", "points": 1, "walltime_h": [0.1, 0.2],
                                      "spend_usd": 0.01})
    for facts in ({"authorized_budget_usd": 1e12, "authorized_budget_fraction": 0},
                  {"authorized_budget_fraction": 1e-12}, {"authorized_budget_fraction": 100}):
        cls, factors = rdj.compute_class(run.root, "launch", run.action("smoke_launch"), facts=facts)
        assert cls == "R3" and "spend" in factors["high_consequence"]
        budget = factors["cost_dimensions"]["authorized_budget_fraction"]
        assert budget["status"] == "declared_unverified" and budget["authorization_status"] == "unknown"


def test_no_fraction_threshold_is_invented_or_derived_from_budget_amount(tmp_path):
    run = Run(tmp_path / "run", cost={"mode": "smoke", "points": 1, "walltime_h": [0.1, 0.2], "spend_usd": 0})
    for facts in ({"authorized_budget_usd": 1000}, {"authorized_budget_fraction": 100}):
        cls, factors = rdj.compute_class(run.root, "launch", run.action("smoke_launch"), facts=facts)
        assert cls == "R0"
        budget = factors["cost_dimensions"]["authorized_budget_fraction"]
        assert budget["threshold_status"] == "owner_policy_required"
        assert budget["declared_fraction"] == facts.get("authorized_budget_fraction")


def test_missing_budget_and_missing_absolute_spend_remain_explicit(tmp_path):
    run = Run(tmp_path / "run")
    _, factors = rdj.compute_class(run.root, "launch", run.action())
    dimensions = factors["cost_dimensions"]
    assert dimensions["absolute_cost"]["value_usd"] is None
    assert dimensions["absolute_cost"]["status"] == "unknown"
    assert dimensions["authorized_budget_fraction"]["declared_fraction"] is None
    assert dimensions["authorized_budget_fraction"]["status"] == "absent"


def test_explicit_unknown_budget_is_distinct_from_absence_or_zero(tmp_path):
    run = Run(tmp_path / "run")
    _, unknown = rdj.compute_class(run.root, "launch", run.action(),
                                   facts={"authorized_budget_fraction": None, "authorized_budget_usd": None})
    assert unknown["cost_dimensions"]["authorized_budget_fraction"]["status"] == "unknown"
    _, zero = rdj.compute_class(run.root, "launch", run.action(), facts={"authorized_budget_fraction": 0})
    budget = zero["cost_dimensions"]["authorized_budget_fraction"]
    assert budget["declared_fraction"] == 0 and budget["status"] == "declared_unverified"
    assert budget["authorization_status"] == "unknown"


@pytest.mark.parametrize("facts,expected", [
    ({"irreversible": True}, "R3"), ({"scientific_consequence": True}, "R3"),
    ({"irreversible": False, "scientific_consequence": False}, "R0"),
])
def test_separate_declared_consequences_only_raise(tmp_path, facts, expected):
    run = Run(tmp_path / "run", cost={"mode": "smoke", "points": 1, "walltime_h": [0.1, 0.2]})
    assert rdj.compute_class(run.root, "launch", run.action("smoke_launch"), facts=facts)[0] == expected


def test_false_caller_flags_cannot_undo_recorded_or_policy_irreversibility(tmp_path):
    run = Run(tmp_path / "run", cost={"mode": "smoke", "points": 1, "walltime_h": [0.1, 0.2],
                                      "irreversible": True, "scientific_consequence": True})
    cls, factors = rdj.compute_class(run.root, "launch", run.action("smoke_launch"),
                                     facts={"irreversible": False, "scientific_consequence": False})
    assert cls == "R3" and factors["irreversible"] is True
    assert factors["cost_dimensions"]["scientific_consequence"]["declared"] is True
    assert rdj.compute_class(run.root, "export", run.action("smoke_launch"),
                             facts={"irreversible": False})[0] == "R3"


def test_explicit_facts_cannot_lower_action_embedded_flags_or_amount(tmp_path):
    run = Run(tmp_path / "run")
    action = run.action(facts={"irreversible": True, "spend_usd": 1})
    cls, factors = rdj.compute_class(run.root, "launch", action,
                                     facts={"irreversible": False, "spend_usd": 0})
    assert cls == "R3" and factors["irreversible"]
    assert factors["cost_dimensions"]["absolute_cost"]["value_usd"] == 1


@pytest.mark.parametrize("field", ["points", "walltime_hours", "spend_usd", "authorized_budget_usd",
                                    "authorized_budget_fraction"])
@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), True])
def test_nonfinite_negative_or_boolean_numeric_risk_facts_are_refused(tmp_path, field, value):
    run = Run(tmp_path / "run")
    with pytest.raises(ValueError, match="finite and nonnegative"):
        rdj.compute_class(run.root, "launch", run.action(), facts={field: value})


@pytest.mark.parametrize("field", ["irreversible", "scientific_consequence"])
@pytest.mark.parametrize("value", [0, 1, "false"])
def test_risk_flags_are_typed_booleans(tmp_path, field, value):
    run = Run(tmp_path / "run")
    with pytest.raises(ValueError, match="boolean"):
        rdj.compute_class(run.root, "launch", run.action(), facts={field: value})


@pytest.mark.parametrize("cost", [
    {"points": -1, "walltime_h": [0.1, 0.2]}, {"points": 1, "walltime_h": [-0.1, 0.2]},
    {"points": 1, "walltime_h": [0.1, 0.2], "spend_usd": -1},
    {"points": 1, "walltime_h": [0.1, 0.2], "authorized_budget_fraction": -1},
])
def test_invalid_recorded_dimensions_are_refused_without_discarding_raising_facts(tmp_path, cost):
    run = Run(tmp_path / "run", cost={"mode": "full", **cost})
    with pytest.raises(ValueError, match="finite.*nonnegative"):
        rdj.compute_class(run.root, "launch", run.action())


def test_invalid_optional_cost_cannot_hide_high_workload_under_smoke_lowering(tmp_path):
    run = Run(tmp_path / "run", cost={"mode": "smoke", "points": 5000, "walltime_h": [0.1, 0.2],
                                      "spend_usd": -1})
    with pytest.raises(ValueError, match="spend_usd"):
        rdj.compute_class(run.root, "launch", run.action("smoke_launch"))


def test_missing_cost_record_cannot_be_replaced_by_arbitrary_budget_declaration(tmp_path):
    run = Run(tmp_path / "run", cost=None)
    cls, factors = rdj.compute_class(run.root, "launch", run.action(), facts={"authorized_budget_usd": 1e12})
    assert cls == "R3" and factors["consequence_unknown"]


def test_declared_irreversibility_requires_human_approval_even_with_high_class_review(tmp_path):
    run = Run(tmp_path / "run")
    case_id, _ = one_hop(run, facts={"irreversible": True})
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, case_id)
    assert "human_required" in {row["code"] for row in refused.value.items}
    run.approve(case_id)
    assert rdj.authorize(run.root, case_id)["outcome"] == "authorize"


def test_later_irreversibility_cannot_reuse_reversible_high_class_receipt(tmp_path):
    run = Run(tmp_path / "run")
    case_id, _ = one_hop(run, gate="delivery")
    rdj.authorize(run.root, case_id)
    changed = run.action(facts={"irreversible": True})
    assert rdj.authorizing_receipt(run.root, "delivery", changed) is None
    assert "rdj_human_required" in {error.code for error in rdj.gate_errors(run.root, "delivery", changed)}


def portable_review_run(tmp_path, *, gates=("delivery", "final_task"), scope_changes=None):
    action = {"kind": "bulk_launch", "summary": "Launch the synthetic scan", "digest": sha(json.dumps({"points": 3})),
              "pins": [{"path": "outputs/plan.json", "sha256": sha(json.dumps({"points": 3}))}]}
    regime = {"mode": "fictional-rule-a"}
    pin = {"path": "inputs/regime.json", "sha256": sha(json.dumps(regime))}
    scope = {"schema_version": 1, "kind": "rdj-review-scope", "scope": "The same fictional artifact decision",
             "regime": "fictional-rule-a", "compatible_gates": list(gates),
             "action": action, "semantic_inputs": [pin], **(scope_changes or {})}
    other_regime = {"mode": "fictional-rule-b"}
    other_scope = {**scope, "regime": "fictional-rule-b", "semantic_inputs": [
        {"path": "inputs/other-regime.json", "sha256": sha(json.dumps(other_regime))}]}
    return Run(tmp_path / "run", extra_inputs=[("inputs/regime.json", regime), ("inputs/review-scope.json", scope),
                                               ("inputs/other-regime.json", other_regime),
                                               ("inputs/other-scope.json", other_scope),
                                               ("inputs/context.json", {"variant": "fictional-original"})])


def accepted_portable(run, **kwargs):
    case_id, roles = one_hop(run, gate="delivery", review_scope=run.pin("inputs/review-scope.json"), **kwargs)
    return case_id, rdj.authorize(run.root, case_id), roles


def test_supplied_identical_scope_reuses_review_into_new_gate_specific_receipt(tmp_path):
    run = portable_review_run(tmp_path)
    scope = run.pin("inputs/review-scope.json")
    source_id, source_roles = one_hop(run, gate="delivery", review_scope=scope)
    source = rdj.authorize(run.root, source_id)
    assert len(source_roles.calls) == 3
    for _, payload in source_roles.calls:
        context = payload.get("case", payload)["review_scope_context"]
        assert context["contract"]["compatible_gates"] == ["delivery", "final_task"]
        assert context["semantic_inputs"][0]["content"] == {"mode": "fictional-rule-a"}
        assert context["current_inputs"]["inputs/context.json"] == run.pin("inputs/context.json")["sha256"]
        assert set(context["implementation_sha256"]) == {"rdj_loop", "decision_case", "rdj_anchor"}
    assert rdj.authorizing_receipt(run.root, "final_task", run.action()) is None
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER,
                              review_scope=scope, reuse_from=source["receipt_id"])
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    target = rdj.authorize(run.root, target_id)
    assert roles.calls == []
    assert target["gate"] == "final_task" and source["gate"] == "delivery"
    assert target["review_reuse"]["source_receipt"]["receipt_id"] == source["receipt_id"]
    assert target["review_reuse"]["execution_authorized"] is False
    assert rdj.authorizing_receipt(run.root, "final_task", run.action())["receipt"] == target
    assert rdj.authorizing_receipt(run.root, "delivery", run.action())["receipt"] == source


@pytest.mark.parametrize("change", ["context", "regime", "declared_risk", "typed_obligation"])
def test_changed_semantics_inputs_risk_or_obligations_dispatch_current_review(tmp_path, change):
    run = portable_review_run(tmp_path)
    _, source, _ = accepted_portable(run)
    scope, options = run.pin("inputs/review-scope.json"), {}
    if change == "context":
        run.put("inputs/context.json", {"variant": "fictional-changed"})
    elif change == "regime":
        scope = run.pin("inputs/other-scope.json")
    elif change == "declared_risk":
        options["declared"] = {"class": "R3"}
    else:
        options["evidence_obligations"] = ["measurement"]
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER,
                              review_scope=scope, reuse_from=source["receipt_id"], **options)
    assert rdj.status(run.root, target_id)["review_reuse"] is None
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert roles.calls and roles.calls[0][0] == "edge_reviewer"
    if change != "typed_obligation":
        assert len(roles.calls) == 3
        assert "review_reuse" not in rdj.authorize(run.root, target_id)


def test_changed_evidence_dispatches_current_review_and_keeps_evidence_hold(tmp_path):
    run = portable_review_run(tmp_path)
    _, source, _ = accepted_portable(run)
    run.put("outputs/witness.json", {"ready": False})
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER,
                              review_scope=run.pin("inputs/review-scope.json"), reuse_from=source["receipt_id"])
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert roles.calls and rdj.status(run.root, target_id)["review_reuse"] is None
    with pytest.raises(rdj.OpenItems):
        rdj.authorize(run.root, target_id)


@pytest.mark.parametrize("gate", ["report_integrity", "checkin2_accept"])
def test_different_shipped_gate_cards_or_effective_risk_require_fresh_review(tmp_path, gate):
    run = portable_review_run(tmp_path, gates=("delivery", "final_task", gate))
    _, source, _ = accepted_portable(run)
    target_id = rdj.open_case(run.root, gate, run.action(), PROPOSER,
                              review_scope=run.pin("inputs/review-scope.json"), reuse_from=source["receipt_id"])
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert len(roles.calls) == 3 and rdj.status(run.root, target_id)["review_reuse"] is None


def test_changed_registered_card_digest_requires_fresh_review(tmp_path, monkeypatch):
    from ravel.workflow import role_registry
    run = portable_review_run(tmp_path)
    _, source, _ = accepted_portable(run)
    original = role_registry.card_sha256
    monkeypatch.setattr(role_registry, "card_sha256", lambda role: sha("changed" + original(role)))
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER,
                              review_scope=run.pin("inputs/review-scope.json"), reuse_from=source["receipt_id"])
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert len(roles.calls) == 3 and rdj.status(run.root, target_id)["review_reuse"] is None


def test_changed_policy_identity_requires_fresh_review(tmp_path, monkeypatch):
    run = portable_review_run(tmp_path)
    _, source, _ = accepted_portable(run)
    actual = rdj.anchor_check.policy_pin()
    monkeypatch.setattr(rdj.anchor_check, "policy_pin", lambda: {**actual, "sha256": sha("different-policy")})
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER,
                              review_scope=run.pin("inputs/review-scope.json"), reuse_from=source["receipt_id"])
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert len(roles.calls) == 3 and rdj.status(run.root, target_id)["review_reuse"] is None


def test_changed_original_transport_output_requires_fresh_review(tmp_path):
    run = portable_review_run(tmp_path)
    _, source, _ = accepted_portable(run)
    final = next((run.root / "agent-work").glob("*/1/final.json"))
    final.write_text("{}")
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER,
                              review_scope=run.pin("inputs/review-scope.json"), reuse_from=source["receipt_id"])
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert len(roles.calls) == 3 and rdj.status(run.root, target_id)["review_reuse"] is None


def test_legacy_cross_gate_bundle_gets_fresh_current_reviews(tmp_path):
    run = Run(tmp_path / "run")
    source_id, _ = one_hop(run, gate="delivery")
    source = rdj.authorize(run.root, source_id)
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER, reuse_from=source["receipt_id"])
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert len(roles.calls) == 3
    assert "review_reuse" not in rdj.authorize(run.root, target_id)


def test_exploration_bundle_cannot_be_reused_across_gates(tmp_path):
    run, action = exploration_run(tmp_path)
    source_id, _ = exploration_case(run, action)
    source = rdj.authorize(run.root, source_id)
    with pytest.raises(ValueError, match="exploration"):
        rdj.open_case(run.root, "final_task", run.action(), PROPOSER, reuse_from=source["receipt_id"])


def test_context_drift_after_reuse_refuses_gate_then_dispatches_fresh_review(tmp_path):
    run = portable_review_run(tmp_path)
    _, source, _ = accepted_portable(run)
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER,
                              review_scope=run.pin("inputs/review-scope.json"), reuse_from=source["receipt_id"])
    rdj.authorize(run.root, target_id)
    run.put("inputs/context.json", {"variant": "fictional-next"})
    assert rdj.authorizing_receipt(run.root, "final_task", run.action()) is None
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert len(roles.calls) == 3
    assert "review_reuse" not in rdj.authorize(run.root, target_id)


def test_source_transport_drift_after_reuse_dispatches_fresh_review(tmp_path):
    run = portable_review_run(tmp_path)
    _, source, _ = accepted_portable(run)
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER,
                              review_scope=run.pin("inputs/review-scope.json"), reuse_from=source["receipt_id"])
    rdj.authorize(run.root, target_id)
    next((run.root / "agent-work").glob("*/1/final.json")).write_text("{}")
    assert rdj.authorizing_receipt(run.root, "final_task", run.action()) is None
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert len(roles.calls) == 3
    assert "review_reuse" not in rdj.authorize(run.root, target_id)


def test_reopen_epoch_requires_fresh_review_even_when_input_bytes_are_unchanged(tmp_path):
    run = portable_review_run(tmp_path)
    digest = run.action_pin["sha256"]
    text = f"Reopen action {digest[:12]}."
    steering = run.steering(text)
    source_id, source, _ = accepted_portable(run)
    before_inputs = {path.relative_to(run.root).as_posix(): sha(path.read_bytes())
                     for path in (run.root / "inputs").rglob("*") if path.is_file()}
    source_case = (run.root / f"rdj/cases/{source_id}.json").read_bytes()
    source_receipt = (run.root / f"rdj/receipts/{source['receipt_id']}.json").read_bytes()
    start = text.index(digest[:12])
    rdj.custody.record_reopen(run.root, action_digest=digest, source="user_steering", path=steering["path"],
                              start=start, end=start + 12, text=digest[:12])
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER,
                              review_scope=run.pin("inputs/review-scope.json"), reuse_from=source["receipt_id"])
    assert before_inputs == {path.relative_to(run.root).as_posix(): sha(path.read_bytes())
                             for path in (run.root / "inputs").rglob("*") if path.is_file()}
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert len(roles.calls) == 3 and rdj.status(run.root, target_id)["review_reuse"] is None
    assert "review_reuse" not in rdj.authorize(run.root, target_id)
    assert (run.root / f"rdj/cases/{source_id}.json").read_bytes() == source_case
    assert (run.root / f"rdj/receipts/{source['receipt_id']}.json").read_bytes() == source_receipt


def test_reused_review_never_transfers_case_specific_human_approval(tmp_path):
    run = portable_review_run(tmp_path)
    scope = run.pin("inputs/review-scope.json")
    source_id, source_roles = one_hop(run, gate="delivery", review_scope=scope, facts={"irreversible": True})
    run.approve(source_id)
    rdj.run_roles(run.root, source_id, source_roles)  # The new user-input context receives current review.
    source = rdj.authorize(run.root, source_id)
    target_id = rdj.open_case(run.root, "final_task", run.action(), PROPOSER, review_scope=scope,
                              facts={"irreversible": True}, reuse_from=source["receipt_id"])
    assert rdj.status(run.root, target_id)["review_reuse"] is not None
    roles = Roles()
    rdj.run_roles(run.root, target_id, roles)
    assert roles.calls == []
    with pytest.raises(rdj.OpenItems) as refused:
        rdj.authorize(run.root, target_id)
    assert "human_required" in {item["code"] for item in refused.value.items}
    run.approve(target_id)
    rdj.run_roles(run.root, target_id, roles)
    assert len(roles.calls) == 3
    assert rdj.authorize(run.root, target_id)["outcome"] == "authorize"


@pytest.mark.parametrize("change", ["generated", "wrong_action", "wrong_gate", "extra_permission"])
def test_review_scope_is_an_exact_authoritative_input_contract(tmp_path, change):
    changes = {}
    if change == "wrong_action":
        changes["action"] = {"kind": "bulk_launch", "summary": "Launch the synthetic scan", "digest": "0" * 64,
                             "pins": [{"path": "outputs/plan.json", "sha256": sha(json.dumps({"points": 3}))}]}
    elif change == "wrong_gate":
        changes["compatible_gates"] = ["delivery"]
    elif change == "extra_permission":
        changes["execution_authorized"] = True
    run = portable_review_run(tmp_path, scope_changes=changes)
    pin = run.pin("inputs/review-scope.json")
    if change == "generated":
        body = json.loads((run.root / pin["path"]).read_text())
        pin = run.put("inputs/generated-scope.json", body)
    with pytest.raises(ValueError):
        rdj.open_case(run.root, "final_task", run.action(), PROPOSER, review_scope=pin)
