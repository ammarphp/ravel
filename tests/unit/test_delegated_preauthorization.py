"""S1-08: plan-level pre-authorization of a delegated CHECK-IN 1 approval.

Each condition of architecture section 2.9 refuses a delegated approval and names its
row; a human approval of the same plan still succeeds. By the owner's autonomy rule, a
physics-critical adapter default is not refused when a justification anchored in the
user's text, a registered invariant or an authoritative-practice reference is recorded;
the adopted defaults are listed at CHECK-IN 3.
"""
import hashlib
import json

import pytest

from ravel.validation import intake_records, validate_checkin
from ravel.workflow import scientific_autonomy as autonomy, workflow_state

import intake_sidecar_fixtures as fx

PROMPT = "Run autonomously: " + fx.PROMPT


def _ambiguity(**over):
    row = {"id": "A1", "evidence": [fx.span(PROMPT, "13 TeV")], "issue": "which luminosity to assume",
           "readings": [{"id": "a", "value": {"lumi_fb": 139}, "authority": "agent_inference", "source": None},
                        {"id": "b", "value": {"lumi_fb": 36}, "authority": "agent_inference", "source": None}],
           "default": "a", "observable_impact": True, "reversible": True, "physics_critical": True,
           "blocks": ["N1"], "status": "open", "resolution": None}
    row.update(over)
    return row


def _user_resolution(**over):
    row = {"reading": "a", "by": "user", "evidence": fx.span(PROMPT, "published slepton search"),
           "utc": "2026-10-11T00:00:00Z"}
    row.update(over)
    return row


def _field(pointer="/task/pdf_set", value="NNPDF31_lo_as_0118", authority="adapter_default"):
    return {"pointer": pointer, "value": value, "authority": authority, "evidence": None}


def _run(tmp_path, reading_overrides=None, plan_overrides=None):
    rd = tmp_path / "run"
    contract, reading, plan = fx.pinned_run(rd, prompt=PROMPT, reading_overrides=reading_overrides,
                                            plan_overrides=plan_overrides)
    return rd, contract, reading, plan


def _justify(rd, contract, entries):
    record = {"schema_version": 1, "kind": "delegated-adapter-defaults",
              "plan_sha256": contract["request_plan"]["sha256"], "entries": entries}
    fx.write_json(rd / intake_records.DELEGATED_DEFAULTS_PATH, record)


def _entry(anchor, value="NNPDF31_lo_as_0118", **over):
    row = {"id": "J1", "node": "N1", "pointer": "/task/pdf_set", "value": value, "anchor": anchor,
           "justification": "The request names no PDF set; the adapter default is the set the published "
                            "analysis used for its signal samples.",
           "author": fx.author("host-agent")}
    row.update(over)
    return row


def _conditions(rd, contract):
    return [(r["condition"], r["row"]) for r in autonomy.plan_preauthorization(rd, contract)["refusals"]]


def test_clean_plan_has_no_refusals_and_unpinned_contract_is_untouched(tmp_path):
    rd, contract, _, _ = _run(tmp_path)
    assert _conditions(rd, contract) == []
    assert autonomy.plan_preauthorization(rd, fx.contract(PROMPT)) == {
        "applies": False, "refusals": [], "adopted_defaults": []}


@pytest.mark.parametrize("reading_overrides, plan_overrides, expected", [
    ({"ambiguities": [_ambiguity()]}, None, ("physics_critical_ambiguity_open", "A1")),
    ({"ambiguities": [_ambiguity(status="resolved", resolution=_user_resolution(by="delegation"))]}, None,
     ("physics_critical_ambiguity_open", "A1")),
    ({"ambiguities": [_ambiguity(status="withdrawn")]}, None, ("physics_critical_ambiguity_open", "A1")),
    ({"facts": [{"id": "F1", "type": "luminosity", "value": {"fb": 139}, "evidence": [],
                 "authority": "inferred", "witness": None, "physics_critical": True}]}, None,
     ("inferred_physics_critical_fact", "F1")),
    ({"constraints": [{"id": "K1", "type": "prescribed_statistic", "value": {"text": "95% CLs"},
                       "evidence": [fx.span(PROMPT, "95% CLs")]}]}, None,
     ("statistic_differs_from_prescription", "C1")),
    (None, {"claims": [fx.claim(statistic={"source": "prescribed", "definition": "95% CLs",
                                           "evidence": [fx.span(PROMPT, "95% CLs")], "secondary": []})]},
     ("statistic_differs_from_prescription", "C1")),
    ({"boundaries": [{"id": "B1", "class": "inaccessible_input", "obligation_ids": ["original-request"],
                      "statement": "the signal workspace is private", "would_make_possible": "a public copy",
                      "evidence": [fx.span(PROMPT, "published slepton search")]}]},
     {"boundaries": ["B1"]}, ("boundary_not_user_chosen", "B1")),
    ({"boundaries": [{"id": "B1", "class": "unsupportable_claim", "obligation_ids": ["original-request"],
                      "statement": "an observed claim needs observed data", "would_make_possible": "data",
                      "evidence": [fx.span(PROMPT, "expected")]}]},
     None, ("alternative_claim_not_user_chosen", "C1")),
    (None, {"waypoints": [{"id": "WP1", "kind": "none", "after": None, "before": ["N1"],
                           "criterion": "single bounded node", "check": None, "on_false": "stop"}]},
     ("waypoint_none_delegated", "WP1")),
    (None, {"nodes": [fx.node(fields=[_field(authority="agent_inference")])]},
     ("agent_inferred_critical_field", "N1/task/pdf_set")),
    (None, {"nodes": [fx.node(fields=[_field()])]}, ("adapter_default_unjustified", "N1/task/pdf_set")),
])
def test_each_condition_refuses_and_names_its_row(tmp_path, reading_overrides, plan_overrides, expected):
    rd, contract, _, _ = _run(tmp_path, reading_overrides, plan_overrides)
    assert expected in _conditions(rd, contract)


def test_user_decided_rows_and_boundaries_do_not_refuse(tmp_path):
    decided = _ambiguity(status="resolved", resolution=_user_resolution(), blocks=["N1", "B1"])
    boundary = {"id": "B1", "class": "inaccessible_input", "obligation_ids": ["original-request"],
                "statement": "the signal workspace is private", "would_make_possible": "a public copy",
                "evidence": [fx.span(PROMPT, "published slepton search")]}
    rd, contract, _, _ = _run(tmp_path, {"ambiguities": [decided], "boundaries": [boundary]}, {"boundaries": ["B1"]})
    assert _conditions(rd, contract) == []


def test_control_bypass_request_boundary_is_policy_not_a_choice(tmp_path):
    boundary = {"id": "B1", "class": "control_bypass_request", "obligation_ids": [],
                "statement": "skip the review", "would_make_possible": "nothing; review is never waived",
                "evidence": [fx.span(PROMPT, "Run autonomously")]}
    rd, contract, _, _ = _run(tmp_path, {"boundaries": [boundary]}, {"boundaries": ["B1"]})
    assert _conditions(rd, contract) == []


@pytest.mark.parametrize("anchor", [
    {"kind": "user_span", "span": fx.span(PROMPT, "published slepton search")},
    {"kind": "registered_invariant", "invariant": "lhe-check-before-shower"},
    {"kind": "authoritative_practice", "citation": "PDF4LHC21 recommendations, J. Phys. G 49 (2022) 080501",
     "source": None},
])
def test_justified_adapter_default_is_adopted_and_listed(tmp_path, anchor):
    rd, contract, _, _ = _run(tmp_path, plan_overrides={"nodes": [fx.node(fields=[_field()])]})
    _justify(rd, contract, [_entry(anchor)])
    result = autonomy.plan_preauthorization(rd, contract)
    assert result["refusals"] == []
    assert [(r["id"], r["node"], r["pointer"]) for r in result["adopted_defaults"]] == [("J1", "N1", "/task/pdf_set")]


def test_practice_source_pin_is_verified(tmp_path):
    rd, contract, _, _ = _run(tmp_path, plan_overrides={"nodes": [fx.node(fields=[_field()])]})
    source = rd / "inputs/pdf-practice.txt"
    source.write_text("PDF4LHC21 recommendation excerpt\n")
    anchor = {"kind": "authoritative_practice", "citation": "PDF4LHC21 recommendations",
              "source": {"path": "inputs/pdf-practice.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}
    _justify(rd, contract, [_entry(anchor)])
    assert _conditions(rd, contract) == []
    source.write_text("edited\n")
    assert ("adapter_default_unjustified", "N1/task/pdf_set") in _conditions(rd, contract)


@pytest.mark.parametrize("entry, condition", [
    (_entry({"kind": "registered_invariant", "invariant": "no-such-invariant"}), "adapter_default_unjustified"),
    (_entry({"kind": "registered_invariant", "invariant": "lhe-check-before-shower"}, value="CT18"),
     "adapter_default_unjustified"),
    (_entry({"kind": "registered_invariant", "invariant": "lhe-check-before-shower"}, justification="default"),
     "adapter_default_unjustified"),
    (_entry({"kind": "user_span", "span": {"start": 0, "end": 3, "text": "Xun"}}), "pinned_records_invalid"),
])
def test_bad_justification_refuses(tmp_path, entry, condition):
    rd, contract, _, _ = _run(tmp_path, plan_overrides={"nodes": [fx.node(fields=[_field()])]})
    _justify(rd, contract, [entry])
    assert condition in [c for c, _ in _conditions(rd, contract)]


def test_justification_record_binds_the_exact_plan(tmp_path):
    rd, contract, _, _ = _run(tmp_path, plan_overrides={"nodes": [fx.node(fields=[_field()])]})
    _justify(rd, contract, [_entry({"kind": "registered_invariant", "invariant": "lhe-check-before-shower"})])
    record = json.loads((rd / intake_records.DELEGATED_DEFAULTS_PATH).read_text())
    record["plan_sha256"] = "0" * 64
    fx.write_json(rd / intake_records.DELEGATED_DEFAULTS_PATH, record)
    assert ("pinned_records_invalid", intake_records.DELEGATED_DEFAULTS_PATH) in _conditions(rd, contract)


def test_signature_registry_marks_non_critical_fields(tmp_path, monkeypatch):
    registry = tmp_path / "operation_signatures.json"
    registry.write_text(json.dumps({"figure-comparison": {"critical_fields": ["/task/luminosity_fb"]}}))
    monkeypatch.setattr(autonomy, "SIGNATURES_PATH", registry)
    rd, contract, _, _ = _run(tmp_path, plan_overrides={"nodes": [fx.node(fields=[_field()])]})
    assert _conditions(rd, contract) == []
    rd2, contract2, _, _ = _run(tmp_path / "b", plan_overrides={
        "nodes": [fx.node(fields=[_field("/task/luminosity_fb", 139)])]})
    assert ("adapter_default_unjustified", "N1/task/luminosity_fb") in _conditions(rd2, contract2)


# --------------------------------------------------------------------------- #
#  delegated versus human approval of the same plan
# --------------------------------------------------------------------------- #

def _approvable(tmp_path, reading_overrides=None, plan_overrides=None):
    rd, contract, reading, plan = _run(tmp_path, reading_overrides, plan_overrides)
    user = rd / "inputs/initial-user-message.txt"
    user.write_text(PROMPT)
    declared = autonomy.prepare_declaration(
        contract, rd / "inputs/delegation.json",
        user_text={"path": str(user), "sha256": hashlib.sha256(PROMPT.encode()).hexdigest()},
        quote="Run autonomously:", origin="initial_prompt", delegate_actor="ravel-coordinator",
        actions=["approve_plan"],
        bounds={"compute_plans": ["none"], "allowed_changed_paths": [], "allowed_stages": [], "max_redos": 0},
        task_class="research_analysis", base_dir=rd)
    fx.write_json(rd / "inputs/task_contract.json", declared["document"])
    fx.write_json(rd / "inputs/checkin1.json", fx.checkin1(plan, reading))
    fx.write_json(rd / "inputs/cost_preflight.json", {"schema_version": 1, "generated_by": "cost_preflight.py",
                                                      "mode": "none", "walltime_h": [0, 0]})
    return rd


def test_delegated_approval_is_refused_and_a_human_approval_succeeds(tmp_path):
    rd = _approvable(tmp_path, {"ambiguities": [_ambiguity()]})
    with pytest.raises(ValueError, match="physics_critical_ambiguity_open A1"):
        workflow_state.record_delegated_approval(rd, "none")
    assert not (rd / "inputs/checkin1_approval.json").exists()

    class Args:
        rundir, plan, quote = str(rd), "none", "Approved as planned; A1 stays at 139 fb^-1."
    assert workflow_state.cmd_approve(Args) == 0
    assert workflow_state.verify_approval(str(rd)) == []


def test_delegated_approval_of_a_clean_plan_is_recorded_as_machine(tmp_path, monkeypatch):
    from ravel.workflow import gate_wiring
    gated = []
    # The R2 approve_plan decision has its own tests (test_gate_wiring_r2r3); this one isolates the record.
    monkeypatch.setattr(gate_wiring, "require_delegated", lambda rundir, gate, action: gated.append(gate))
    rd = _approvable(tmp_path)
    record = workflow_state.record_delegated_approval(rd, "none")
    assert record["authority"] == "delegated_machine" and gated == ["approve_plan"]
    assert workflow_state.verify_approval(str(rd)) == []


def test_cli_delegated_approve_reaches_the_plan_preauthorization(tmp_path, capsys):
    from ravel import cli
    rd = _approvable(tmp_path, plan_overrides={"nodes": [fx.node(fields=[_field()])]})
    assert cli.main(["approve", "--rundir", str(rd), "--delegated"]) == 2
    assert "adapter_default_unjustified N1/task/pdf_set" in capsys.readouterr().err


def test_cli_delegated_approve_without_a_pinned_plan_keeps_its_refusal(tmp_path, capsys):
    from ravel import cli
    rd = tmp_path / "run"
    fx.write_json(rd / "inputs/task_contract.json", fx.contract())
    assert cli.main(["approve", "--rundir", str(rd), "--delegated"]) == 2
    assert "pinned request plan" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
#  CHECK-IN 3 listing
# --------------------------------------------------------------------------- #

def _deck(**extra):
    sections = {s: "x" for s in validate_checkin.DECK_SECTIONS}
    sections.update(extra)
    return {"schema_version": 1, "kind": "deck", "sections": sections}


def test_final_deck_lists_every_adopted_default(tmp_path):
    rd, contract, _, _ = _run(tmp_path, plan_overrides={"nodes": [fx.node(fields=[_field()])]})
    entry = _entry({"kind": "registered_invariant", "invariant": "lhe-check-before-shower"})
    _justify(rd, contract, [entry])
    assert any("adopted_defaults" in e for e in validate_checkin.validate(_deck(), base_dir=str(rd)))
    listed = [{"id": "J1", "node": "N1", "pointer": "/task/pdf_set", "justification": entry["justification"]}]
    # The pinned plan gives the run recipe rows, so the deck also carries the delivery disclosure.
    from ravel.workflow import recipe_ledger
    assert validate_checkin.validate(_deck(adopted_defaults=listed), base_dir=str(rd)) == [
        "CHECK-IN 3 must list every unknown recipe ledger row and current deviation"]
    disclosed = recipe_ledger.with_checkin3_section(_deck(adopted_defaults=listed), rd)
    assert [r["field"] for r in disclosed["sections"]["recipe_ledger"]["unknown"]] == ["/task/pdf_set"]
    assert validate_checkin.validate(disclosed, base_dir=str(rd)) == []
    assert any("adopted_defaults" in e for e in validate_checkin.validate(
        recipe_ledger.with_checkin3_section(_deck(), rd), base_dir=str(rd)))
    assert [r["id"] for r in autonomy.adopted_defaults(rd)] == ["J1"]


def test_deck_without_pins_is_unchanged(tmp_path):
    rd = tmp_path / "run"
    fx.write_json(rd / "inputs/task_contract.json", fx.contract())
    assert validate_checkin.validate(_deck(), base_dir=str(rd)) == []


# --------------------------------------------------------------------------- #
#  goal-bound children are pre-authorized against the parent's pinned plan
# --------------------------------------------------------------------------- #

def _child_of(rd, tmp_path):
    raw = (rd / "inputs/task_contract.json").read_bytes()
    pin = {"path": str(rd / "inputs/task_contract.json"), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    child = tmp_path / "child"
    (child / "inputs").mkdir(parents=True)
    return child, {"schema_version": 2, "mode": "figure-comparison",
                   "goal_binding": {"contract": pin, "assignment_id": "fig3"}}


def test_child_delegation_is_checked_against_the_parent_plan(tmp_path):
    rd, _, _, _ = _run(tmp_path, {"ambiguities": [_ambiguity()]})
    child, spec = _child_of(rd, tmp_path)
    assert autonomy.preauthorization_target(child, spec)[0] == rd
    assert autonomy.preauthorization_errors(child, spec) == [
        "physics_critical_ambiguity_open A1: which luminosity to assume"]


def test_plan_authority_refuses_a_child_under_an_unresolved_parent_plan(tmp_path, monkeypatch):
    rd, _, _, _ = _run(tmp_path, {"ambiguities": [_ambiguity()]})
    child, spec = _child_of(rd, tmp_path)
    monkeypatch.setattr(autonomy, "_run_document", lambda root: (child, spec))
    monkeypatch.setattr(autonomy, "declaration", lambda document, base, **_: {
        "value": {"actions": ["approve_plan"], "bounds": {"compute_plans": ["smoke"]}}})
    with pytest.raises(ValueError, match="physics_critical_ambiguity_open A1"):
        autonomy.plan_authority(child, required_plan="smoke")


def test_child_without_a_plan_pinned_parent_is_unchanged(tmp_path):
    rd = tmp_path / "parent"
    fx.write_json(rd / "inputs/task_contract.json", fx.contract())
    child, spec = _child_of(rd, tmp_path)
    assert autonomy.preauthorization_target(child, spec) is None
    assert autonomy.preauthorization_errors(child, spec) == []


def test_version1_contract_without_a_pinned_plan_still_cannot_bind_delegation(tmp_path):
    rd = tmp_path / "run"
    contract = fx.contract(PROMPT)
    fx.write_json(rd / "inputs/task_contract.json", contract)
    user = rd / "inputs/initial-user-message.txt"
    user.write_text(PROMPT)
    with pytest.raises(ValueError, match="schema2 review"):
        autonomy.prepare_declaration(
            contract, rd / "inputs/delegation.json",
            user_text={"path": str(user), "sha256": hashlib.sha256(PROMPT.encode()).hexdigest()},
            quote="Run autonomously:", origin="initial_prompt", delegate_actor="ravel-coordinator",
            actions=["approve_plan"],
            bounds={"compute_plans": ["none"], "allowed_changed_paths": [], "allowed_stages": [], "max_redos": 0},
            task_class="research_analysis", base_dir=rd)


@pytest.mark.parametrize("reference, anchor, refused", [
    ("invariant:lhe-check-before-shower", {"kind": "registered_invariant", "invariant": "lhe-check-before-shower"}, False),
    ("invariant:lhe-check-before-shower", {"kind": "authoritative_practice", "citation": "PDF4LHC21", "source": None},
     True),
    ("practice:PDF4LHC21 recommendations", {"kind": "authoritative_practice", "citation": "PDF4LHC21 recommendations",
                                            "source": None}, False),
    ("F1", {"kind": "user_span", "span": fx.span(PROMPT, "300 GeV")}, False),
    ("F1", {"kind": "user_span", "span": fx.span(PROMPT, "published slepton search")}, True),
])
def test_recorded_anchor_must_name_the_plan_fields_anchor(tmp_path, reference, anchor, refused):
    """The plan check's anchor reference on the field and the recorded justification agree (P0-S1' seam)."""
    field = dict(_field(), evidence=reference)
    rd, contract, _, _ = _run(tmp_path, plan_overrides={"nodes": [fx.node(fields=[field])]})
    _justify(rd, contract, [_entry(anchor)])
    assert (("adapter_default_unjustified", "N1/task/pdf_set") in _conditions(rd, contract)) is refused
