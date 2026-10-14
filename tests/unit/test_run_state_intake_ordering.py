"""Lifecycle status at intake: stage tables by task mode, CHECK-IN 1 ordering, intake flags."""
import os

import pytest

from ravel.validation import validate_run_state as vrs


def _run(tmp_path, name, contract, files=()):
    rd = tmp_path / name
    vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
    for rel, doc in files:
        if isinstance(doc, str):
            vrs._write_text(str(rd / rel), doc)
        else:
            vrs._write_json(str(rd / rel), doc)
    return str(rd)


def _levels(task_mode, contract=None):
    contract = contract or vrs._base_contract(task_mode=task_mode)
    return {stage: vrs.resolve_level(stage, task_mode, contract, {}) for stage in vrs.STAGE_ORDER}


@pytest.mark.parametrize("task_mode", ["generate", "likelihood"])
def test_scoped_modes_list_no_census_trap_or_figure_stage(task_mode):
    levels = _levels(task_mode)
    for stage in ("resource_census", "trap_sweep", "figure_contract", "basis_manifest"):
        assert levels[stage] == "N/A", stage
    assert levels["generation"] == ("R" if task_mode == "generate" else "N/A")
    assert levels["statistics"] == ("N/A" if task_mode == "generate" else "R")


@pytest.mark.parametrize("task_mode", ["survey", "summary_plot"])
def test_literature_modes_make_census_and_traps_optional(task_mode):
    levels = _levels(task_mode)
    assert levels["resource_census"] == "O"
    assert levels["trap_sweep"] == "O"
    assert levels["figure_contract"] in ("O", "N/A")
    assert levels["generation"] == "N/A"


def test_research_parent_requires_census_and_trap_sweep():
    # S1-09: open research parents receive requests the parser used to refuse; they keep
    # the published-resource census and the trap sweep (architecture section 4.3).
    levels = _levels("research")
    assert levels["resource_census"] == levels["trap_sweep"] == "R"
    assert levels["figure_contract"] == "O" and levels["generation"] == "N/A"


def _research_contract():
    from ravel.workflow.task_completion import initial_requirements
    prompt = "Study whether a light scalar coupled to muons is still allowed."
    return vrs._base_contract(task_mode="research", prompt=prompt, detector_mode="none",
                              stat_mode="TBD-judgment", task_requirements=initial_requirements(prompt))


def test_research_fixture_without_trap_sweep_or_census_fails(tmp_path):
    contract = _research_contract()
    rd = _run(tmp_path, "2026-10-11_research_bare", contract)
    result = vrs.evaluate(rd, contract, stage_limit="trap_sweep")
    status = {s["name"]: s["status"] for s in result["stages"]}
    assert status["resource_census"] == status["trap_sweep"] == "FAIL"


def test_research_fixture_with_trap_sweep_and_census_passes_those_stages(tmp_path):
    contract = _research_contract()
    rd = _run(tmp_path, "2026-10-11_research_ready", contract,
              [("inputs/resource_census.json", vrs._resource_census_doc()),
               ("inputs/trap_sweep.json", vrs._trap_sweep_doc())])
    result = vrs.evaluate(rd, contract, stage_limit="trap_sweep")
    status = {s["name"]: s["status"] for s in result["stages"]}
    assert status["resource_census"] == status["trap_sweep"] == "PASS"


def test_method_study_and_manuscript_rows_are_unchanged():
    assert [vrs.STAGE_MATRIX["method_study"][s] for s in vrs.STAGE_ORDER] == [
        "R", "N/A", "N/A", "O", "N/A", "C6", "N/A", "N/A", "N/A", "R", "R"]
    assert [vrs.STAGE_MATRIX["manuscript"][s] for s in vrs.STAGE_ORDER] == [
        "R", "N/A", "N/A", "N/A", "O", "N/A", "N/A", "N/A", "N/A", "R", "R"]


def test_method_study_intake_uses_its_own_table():
    contract = vrs._base_contract(task_mode="survey", intake={"kind": "method_study"})
    levels = _levels("survey", contract)
    for stage in ("resource_census", "trap_sweep", "figure_contract", "generation", "analysis", "statistics"):
        assert levels[stage] == "N/A", stage
    assert levels["result_pack"] == "R"


def test_manuscript_table_needs_no_census_traps_or_generation():
    levels = _levels("manuscript", {"task_mode": "manuscript"})
    for stage in ("resource_census", "trap_sweep", "generation", "statistics"):
        assert levels[stage] == "N/A", stage
    assert levels["result_pack"] == "R"


def test_reproduction_modes_keep_the_full_table():
    levels = _levels("reproduce")
    assert levels["resource_census"] == levels["trap_sweep"] == levels["figure_contract"] == "R"


def test_intake_flags_need_no_deviations_before_checkin1_approval(tmp_path):
    contract = vrs._base_contract(task_mode="survey", escalate=["survey scope: confirm the experiments"])
    rd = _run(tmp_path, "2026-10-10_fresh_intake", contract)
    facts = vrs.discover_facts(rd, contract)
    status, detail = vrs.inv_deviations_on_change(rd, contract, facts, False, False)
    assert status == "PASS", detail
    assert "CHECK-IN 1" in detail


def test_intake_flags_still_count_after_checkin1_approval(tmp_path):
    contract = vrs._base_contract(task_mode="survey", escalate=["survey scope: confirm the experiments"])
    rd = _run(tmp_path, "2026-10-10_approved", contract,
              [("inputs/checkin1_approval.json", {"schema_version": 2})])
    facts = vrs.discover_facts(rd, contract)
    status, _ = vrs.inv_deviations_on_change(rd, contract, facts, False, False)
    assert status == "FAIL"


def test_trap_hits_still_require_deviations_before_approval(tmp_path):
    contract = vrs._base_contract(task_mode="survey")
    rd = _run(tmp_path, "2026-10-10_trap", contract,
              [("inputs/trap_sweep.json", vrs._trap_sweep_doc(traps_hit=("T1",)))])
    facts = vrs.discover_facts(rd, contract)
    status, _ = vrs.inv_deviations_on_change(rd, contract, facts, False, False)
    assert status == "FAIL"


def test_next_required_orders_checkin1_approval_before_post_approval_stages(tmp_path):
    contract = vrs._base_contract(task_mode="survey", escalate=["survey scope: confirm the experiments"])
    rd = _run(tmp_path, "2026-10-10_survey_planned", contract,
              [("inputs/basis_manifest.json", vrs._basis_manifest_doc())])
    nxt = vrs.next_required(rd, contract)
    assert nxt["kind"] == "checkin"
    assert nxt["what"] == "CHECK-IN 1"
    vrs._write_json(os.path.join(rd, "inputs", "checkin1.json"), {"schema_version": 1, "kind": "checkin1"})
    nxt = vrs.next_required(rd, contract)
    assert nxt["kind"] == "checkin" and nxt["what"] == "CHECK-IN 1 approval"


def test_pre_approval_stage_blockers_come_before_the_approval(tmp_path):
    contract = vrs._base_contract(task_mode="survey")
    rd = _run(tmp_path, "2026-10-10_survey_unplanned", contract)
    nxt = vrs.next_required(rd, contract)
    assert nxt == {"kind": "artifact", "what": "basis_manifest",
                   "why": "required stage 'basis_manifest' is FAIL"}


def test_ordered_blockers_put_approval_before_result_and_verification(tmp_path):
    contract = vrs._base_contract(task_mode="survey")
    rd = _run(tmp_path, "2026-10-10_survey_order", contract,
              [("inputs/basis_manifest.json", vrs._basis_manifest_doc())])
    order = [b["what"] for b in vrs.ordered_blockers(rd, contract)]
    assert order.index("CHECK-IN 1") < order.index("result_pack") < order.index("verification")


def test_approved_run_reports_the_next_stage_not_the_approval(tmp_path, monkeypatch):
    from ravel.workflow import workflow_state
    contract = vrs._base_contract(task_mode="survey")
    rd = _run(tmp_path, "2026-10-10_survey_approved", contract,
              [("inputs/basis_manifest.json", vrs._basis_manifest_doc()),
               ("inputs/checkin1.json", {"schema_version": 1, "kind": "checkin1"}),
               ("inputs/checkin1_approval.json", {"schema_version": 2})])
    monkeypatch.setattr(workflow_state, "verify_approval", lambda rundir, **_: [])
    assert vrs.next_required(rd, contract)["what"] == "result_pack"


def test_workflow_state_next_required_uses_the_same_order(tmp_path):
    from ravel.workflow import workflow_state
    contract = vrs._base_contract(task_mode="survey")
    rd = _run(tmp_path, "2026-10-10_survey_ws", contract,
              [("inputs/basis_manifest.json", vrs._basis_manifest_doc())])
    assert workflow_state.compute_next_required(rd, contract)["what"] == "CHECK-IN 1"


def test_survey_result_without_trap_sweep_is_not_an_invariant_failure(tmp_path):
    contract = vrs._base_contract(task_mode="survey")
    rd = _run(tmp_path, "2026-10-10_survey_done", contract,
              [("inputs/basis_manifest.json", vrs._basis_manifest_doc()),
               ("outputs/survey.json", {"schema_version": 1, "candidates": []})])
    facts = vrs.discover_facts(rd, contract)
    status, _ = vrs.inv_trap_sweep_recorded(rd, contract, facts, False, False)
    assert status != "FAIL"


def test_status_packet_points_at_checkin1_before_post_approval_work(tmp_path):
    from ravel.workflow import current_state, workflow_state
    contract = vrs._base_contract(task_mode="survey", escalate=["survey scope: confirm the experiments"])
    rd = _run(tmp_path, "2026-10-10_survey_packet", contract,
              [("inputs/basis_manifest.json", vrs._basis_manifest_doc())])
    assert workflow_state.main(["init", "--rundir", rd]) == 0
    packet = current_state.build_packet(rd)
    assert packet["next_required"]["kind"] == "checkin"
    assert packet["next_required"]["what"] == "CHECK-IN 1"
    assert "check-ins.md" in str(packet["next_instruction"])
    assert all(b["what"] != "DEVIATIONS-on-change" for b in packet["blockers"])


def test_required_stages_is_the_single_contract_reader():
    plan = vrs.required_stages({"task_mode": "reproduce"})
    assert set(plan["levels"]) == set(vrs.STAGE_ORDER)
    assert plan["checkin1"] == {"required": True, "before": "generation"}
    scoped = vrs.required_stages({"task_mode": "likelihood"})
    assert scoped["checkin1"] == {"required": True, "before": "route"}
    assert vrs.required_stages({"task_mode": "calculation"})["checkin1"]["required"] is False
    study = vrs.required_stages({"task_mode": "research", "intake": {"kind": "method_study"}})
    assert study["levels"]["basis_manifest"] == "C6"
    assert study["levels"]["generation"] == "N/A"


def test_resolve_level_and_blockers_follow_required_stages(monkeypatch, tmp_path):
    original = vrs.required_stages

    def derived(contract, task_mode=None):
        plan = original(contract, task_mode)
        return {**plan, "levels": {**plan["levels"], "trap_sweep": "N/A"},
                "checkin1": {"required": False, "before": None}}

    monkeypatch.setattr(vrs, "required_stages", derived)
    contract = vrs._base_contract(task_mode="reproduce")
    assert vrs.resolve_level("trap_sweep", "reproduce", contract, {}) == "N/A"
    rd = _run(tmp_path, "derived", contract)
    assert all(b["kind"] != "checkin" for b in vrs.ordered_blockers(rd, contract))
