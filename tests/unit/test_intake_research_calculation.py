"""Whole-goal intake and preparation; no science/model execution is needed here."""
import synthetic_identifiers as syn
import hashlib
import json
from pathlib import Path

import pytest

from ravel import cli
from ravel.validation import validate_run_state as run_validation
from ravel.validation.validate_task_contract import validate
from ravel.workflow import current_state, intake, route_prompt, task_completion


def store(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def parent(tmp_path, prompt):
    contract = route_prompt.route(prompt)
    pin = store(tmp_path / "inputs/task_contract.json", contract)
    return contract, pin


@pytest.mark.parametrize("prompt,kind", [
    ("Calculate the lifetime in mm from this supplied total width in GeV, preserving precision.", "calculation"),
    ("Compute 2 + 2 and state the dimensionless result.", "calculation"),
    ("Discover a new particle at 5 sigma, retaining null results and independent validation.", "research"),
    ("Investigate the full scalar spectrum and all 29 input points and the 37 comparison points; deliver the plots and constraints.", "research"),
    ("Run the supplied study and deliver its full simulation, selections, bins, code and report.", "research"),
    (("Implement the search analysis described in " + syn.analysis(489) + " and use it to predict the complete binned signal yield."), "research"),
    ("Develop the background estimation for the supplied collider study; preserve blinding, validation and the note.", "research"),
])
def test_intake_keeps_complete_goal_and_zero_authority(tmp_path, prompt, kind):
    contract, pin = parent(tmp_path, prompt)
    assert validate(contract) == []
    if "full simulation" in prompt:
        # ad35854: the demand for full detector simulation is held and never silently downgraded to
        # the fast response. The held contract keeps the whole request and carries no authority; the
        # same request without that demand takes the route this case names.
        assert contract["task_mode"] == "unsupported" and contract["prompt"] == prompt
        assert contract["compute_plan"] == "none" and contract["approval_required"] is True
        assert any("Full simulation of the detector" in row for row in contract["blocking"])
        assert contract["task_requirements"]["obligations"][0] == task_completion.initial_requirements(prompt)["obligations"][0]
        assert route_prompt.route(prompt.replace(" full simulation,", ""))["task_mode"] == kind
        return
    assert contract["task_mode"] == contract["intake"]["kind"] == kind
    assert contract["prompt"] == contract["intake"]["objective"] == prompt
    assert contract["intake"]["requested_outputs"] == [prompt]
    assert contract["compute_plan"] == "none" and contract["approval_required"] is True
    req = contract["task_requirements"]
    # The whole request stays first and verbatim; the census adds the reading's finer obligations.
    assert req["obligations"][0] == task_completion.initial_requirements(prompt)["obligations"][0]
    assert req["assignments"][0]["coverage"][0] == {"obligation_id": "original-request", "criteria": {"request": prompt}}
    assert [row["obligation_id"] for row in req["assignments"][0]["coverage"]] == [o["id"] for o in req["obligations"]]
    handoff = intake.execution_handoff(pin, base_dir=tmp_path)
    assert handoff["goal_binding"] == {"contract": pin, "assignment_id": "original-task"}
    projection = task_completion.binding_projection(handoff["goal_binding"], base_dir=tmp_path)
    assert projection["original_request"] == prompt
    assert projection["assignment"]["coverage"] == req["assignments"][0]["coverage"]
    assert handoff["obligations"] == req["obligations"]
    # Both original calculation prompts include obligations beyond the closed
    # literal expression grammar; they use the typed scientific child route.
    assert handoff["child_schema_version"] == 2
    if kind == "calculation":
        assert handoff["completion_api"] == "ravel.workflow.task_completion.require_final"
        assert handoff["calculation_collection_api"] is None
    assert handoff["compute_authorized"] is handoff["physics_validated"] is handoff["parent_task_accepted"] is False
    assert not (tmp_path / "inputs/checkin1_approval.json").exists()


@pytest.mark.parametrize("change", [
    lambda c: c.update(compute_plan="smoke"),
    lambda c: c.update(detector_mode="particle-level"),
    lambda c: c.update(stat_mode="sensitivity-expected-only"),
    lambda c: c.pop("task_requirements"),
])
def test_new_draft_cannot_smuggle_compute_or_metric(change):
    contract = route_prompt.route("Investigate a new search strategy and its validation.")
    change(contract)
    assert validate(contract)


def test_calculation_avoids_detector_figure_and_research_cycle(tmp_path):
    contract, pin = parent(tmp_path, "Calculate a supplied total-width lifetime in mm.")
    levels = run_validation.STAGE_MATRIX["calculation"]
    assert levels["generation"] == levels["analysis"] == levels["statistics"] == "N/A"
    assert levels["figure_contract"] == "N/A"
    handoff = intake.execution_handoff(pin, base_dir=tmp_path)
    assert handoff["planning_apis"] == ["ravel.workflow.intake_planner.prepare", "ravel.workflow.intake_planner.graph_spec", "ravel.workflow.agent_graph.execute"]
    assert handoff["completion_api"] == "ravel.workflow.task_completion.require_final"
    assert all("research_cycle" not in name for name in handoff["planning_apis"])
    store(tmp_path / "result.json", {"schema_version": 1, "value": 4, "unit": "1"})
    assert run_validation.result_pack_paths(str(tmp_path), "calculation") == {}
    assert run_validation.evaluate(str(tmp_path), contract)["verdict"] == "FAIL"
    assert not (tmp_path / "figures.json").exists()


@pytest.mark.parametrize('full_inventory', [False, True])
def test_only_explicit_checkout_state_pins_skip_in_curated_tree(tmp_path, monkeypatch, full_inventory):
    import importlib.util
    location = Path(__file__).with_name('conftest.py')
    spec = importlib.util.spec_from_file_location('selected_unit_collection_policy', location)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, '_FULL_INVENTORY', full_inventory)
    class Item:
        def __init__(self, nodeid):
            self.nodeid = nodeid; self.name = nodeid.split('::')[-1]; self.markers = []
        def add_marker(self, marker): self.markers.append(marker)
    pins = [
        'tests/unit/test_check_evidence.py::test_live_evidence_manifest_checks_clean',
    ]
    software = [
        'tests/unit/test_validate_task_contract.py::test_live_contract_loader_uses_strict_json[duplicate]',
        'tests/unit/test_approval_chain.py::test_live_guard_never_uses_the_archive_approval_concession',
        'tests/unit/test_registered_helpers.py::test_live_owned_lifecycle[normal]',
        'tests/unit/test_release_workflow_fixture_boundaries.py::test_live_logical_python_capture_and_wrong_binary_snapshot',
        'tests/unit/test_review_output_policy.py::test_live_output_mutation_refuses_review_reuse[symlink]',
        'tests/unit/test_scan_babysitter_livehung.py::test_live_points_detects_fractional_dm_short_and_full',
    ]
    items = [Item(n) for n in pins + software]
    module.pytest_collection_modifyitems(None, items)
    assert [item.nodeid for item in items if item.markers] == ([] if full_inventory else pins)
    assert all(not item.markers for item in items[len(pins):])


def test_host_interpretation_handles_unfamiliar_question_without_scope_replacement(tmp_path):
    prompt = "A colleague asks: what mechanism could explain this, and how would we distinguish it?"
    interpretation = {"schema_version": 1, "prompt_sha256": intake.prompt_hash(prompt), "kind": "research",
        "objective": prompt, "requested_outputs": ["Mechanisms and executed discriminating evidence"],
        "evidence": [{"start": 0, "end": len(prompt), "text": prompt}],
        "unresolved": ["Actual dataset, statistical law and bounded experiments"]}
    contract = route_prompt.route(prompt, interpretation)
    assert validate(contract) == []
    assert contract["intake"]["source"] == "host-agent"
    assert contract["task_requirements"]["obligations"][0]["statement"] == prompt
    pin = store(tmp_path / "inputs/task_contract.json", contract)
    assert intake.execution_handoff(pin, base_dir=tmp_path)["requested_outputs"] == interpretation["requested_outputs"]


@pytest.mark.parametrize("prompt", [
    "Claim discovery of a new particle at 5 sigma.",
    "Announce a discovery from these data.",
    "Compute significance of the excess and give a 5 sigma result.",
])
def test_claim_assertion_does_not_gain_authority_from_research_words(prompt):
    contract = route_prompt.route(prompt)
    assert contract["task_mode"] == "unsupported"
    assert contract["task_requirements"]["obligations"][0]["statement"] == prompt
    assert contract["compute_plan"] == "none"


def test_research_proposal_cannot_close_original_task(tmp_path):
    contract, pin = parent(tmp_path, "Investigate an open discovery search and deliver its validated results.")
    request = {"schema_version": 1, "contract": pin, "outcomes": [], "parent_review": None, "report": None}
    request_pin = store(tmp_path / "inputs/task_completion.json", request)
    result = task_completion.evaluate(request_pin, base_dir=tmp_path)
    assert result["original_request"] == contract["prompt"]
    assert result["unmet_obligation_ids"] == ["original-request"]
    assert result["unobserved_assignment_ids"] == ["original-task"]
    assert result["ready_for_parent_review"] is result["parent_task_accepted"] is False
    with pytest.raises(ValueError, match="original parent task remains open"):
        task_completion.require_final(request_pin, base_dir=tmp_path)
    facts = {"task_contract_path": pin["path"], "result_pack_paths": {"inputs/task_completion.json": "inputs/task_completion.json"}}
    verdict, _, checks = run_validation.check_result_pack(str(tmp_path), contract, facts, "R", False)
    assert verdict == "FAIL" and "original parent task remains open" in checks[0]["msg"]


def test_research_completion_cannot_borrow_foreign_parent(tmp_path):
    contract, pin = parent(tmp_path, "Investigate the original full task.")
    _, other = parent(tmp_path / "other", "Investigate a different smaller task.")
    store(tmp_path / "inputs/task_completion.json", {"schema_version": 1, "contract": other, "outcomes": [], "parent_review": None, "report": None})
    facts = {"task_contract_path": pin["path"], "result_pack_paths": {"inputs/task_completion.json": "inputs/task_completion.json"}}
    verdict, _, checks = run_validation.check_result_pack(str(tmp_path), contract, facts, "R", False)
    assert verdict == "FAIL" and "exact original parent" in checks[0]["msg"]


@pytest.mark.parametrize("mutation", ["subset", "changed-contract"])
def test_handoff_refuses_changed_parent_or_incomplete_assignment(tmp_path, mutation):
    contract, pin = parent(tmp_path, "Investigate the full background, signal and validation task.")
    if mutation == "subset":
        contract["task_requirements"]["assignments"][0]["coverage"][0]["criteria"] = {"request": "proposal only"}
        pin = store(Path(pin["path"]), contract)
    else:
        Path(pin["path"]).write_bytes(Path(pin["path"]).read_bytes() + b" ")
    with pytest.raises(ValueError):
        intake.execution_handoff(pin, base_dir=tmp_path)


def test_handoff_result_is_detached_from_caller_pin(tmp_path):
    _, pin = parent(tmp_path, "Investigate the full question and its experiments.")
    handoff = intake.execution_handoff(pin, base_dir=tmp_path)
    handoff["parent_contract"]["sha256"] = "0" * 64
    assert handoff["goal_binding"]["contract"] == pin
    again = intake.execution_handoff(pin, base_dir=tmp_path)
    assert again["parent_contract"] == pin


@pytest.mark.parametrize("prompt", ["Compute 2+2 with dimensionless units.", "Investigate a new collider search and retain its full results."])
def test_public_initiate_and_status_prepare_exact_handoff_without_execution(tmp_path, monkeypatch, prompt):
    monkeypatch.setattr(cli.subprocess, "call", lambda *a, **k: pytest.fail("intake launched compute"))
    root = tmp_path / "parent"
    assert cli.main(["initiate", "--prompt", prompt, "--out", str(root)]) == 0
    handoff = json.loads((root / "inputs/intake_handoff.json").read_text())
    packet = current_state.build_packet(root)
    assert packet["parent_task"]["original_request"] == prompt
    assert packet["intake_handoff"] == handoff
    assert not (root / "inputs/checkin1_approval.json").exists()
    assert not (root / "inputs/science-plan.json").exists()
    assert not (root / "execution_state.json").exists()


@pytest.mark.parametrize("leaf", ["task_contract.json", "intake_handoff.json"])
def test_public_initiate_refuses_late_generated_commitment_mutation(tmp_path, monkeypatch, leaf):
    original = current_state.write_packet
    def late_mutation(root):
        packet = original(root)
        path = Path(root) / "inputs" / leaf
        path.write_bytes(path.read_bytes() + b" ")
        return packet
    monkeypatch.setattr(current_state, "write_packet", late_mutation)
    root = tmp_path / "retained-partial"
    assert cli.main(["initiate", "--prompt", "Investigate a full analysis question.", "--out", str(root)]) == 2
    assert (root / "request.txt").read_text() == "Investigate a full analysis question."
    assert (root / "inputs" / leaf).is_file()
    assert not (root / "inputs/checkin1_approval.json").exists()


def test_status_checks_state_after_handoff_derivation(tmp_path, monkeypatch):
    root = tmp_path / "parent"
    assert cli.main(["initiate", "--prompt", "Investigate the full question.", "--out", str(root)]) == 0
    original = intake.execution_handoff
    def late_state(pin, *, base_dir):
        result = original(pin, base_dir=base_dir)
        path = Path(base_dir) / "run_state.json"
        path.write_bytes(path.read_bytes() + b" ")
        return result
    monkeypatch.setattr(intake, "execution_handoff", late_state)
    with pytest.raises(ValueError, match="run inputs changed"):
        current_state.build_packet(root)


def test_public_initiate_rejects_generated_handoff_changed_before_first_read(tmp_path, monkeypatch):
    original = Path.write_bytes
    def changed(path, raw):
        result = original(path, raw)
        if path.name == "intake_handoff.json":
            value = json.loads(raw)
            value["compute_authorized"] = True
            original(path, json.dumps(value).encode())
        return result
    monkeypatch.setattr(Path, "write_bytes", changed)
    root = tmp_path / "retained-partial"
    assert cli.main(["initiate", "--prompt", "Investigate the full task.", "--out", str(root)]) == 2
    assert json.loads((root / "inputs/intake_handoff.json").read_text())["compute_authorized"] is True
    assert not (root / "inputs/checkin1_approval.json").exists()


@pytest.mark.parametrize("prompt,mode", [
    (("Reproduce " + syn.analysis(1) + " with all original analysis stages."), "reproduce"),
    ("Scan the complete slepton mass grid and deliver the exclusion contour.", "scan"),
    ("Fit the supplied pyhf likelihood and compute expected limits without generating events.", "likelihood"),
    ("Generate parton-level events only for the supplied process.", "generate"),
])
def test_new_intents_do_not_narrow_existing_analysis_requests(prompt, mode):
    contract = route_prompt.route(prompt)
    assert contract["task_mode"] == mode
    assert contract["task_requirements"]["obligations"][0]["statement"] == prompt
    assert validate(contract) == []
