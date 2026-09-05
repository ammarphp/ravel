"""Intent is grounded and negation aware; a draft never grants new execution rights."""
import copy
import json

import pytest

from ravel import cli
from ravel.workflow import intake, route_prompt
from ravel.validation.validate_task_contract import validate


@pytest.mark.parametrize("prompt,mode", [
    ("Do not claim discovery; reproduce ATLAS SUSY-2018-16.", "reproduce"),
    ("Reproduce ATLAS SUSY-2018-16 without a 5 sigma discovery claim.", "reproduce"),
    ("Never discover a new particle. Reproduce ATLAS SUSY-2018-16.", "reproduce"),
    ("Don't scan the masses; survey ATLAS searches.", "survey"),
    ("I don't want a discovery claim, I want to reproduce ATLAS SUSY-2018-16.", "reproduce"),
    ("Do not claim discovery and reproduce ATLAS SUSY-2018-16.", "unsupported"),
    ("I do not want you to reproduce ATLAS SUSY-2018-16 and scan the masses.", "unsupported"),
    ("Neither reproduce ATLAS SUSY-2018-16 nor scan the masses.", "unsupported"),
    ("Do not reproduce ATLAS SUSY-2018-16; scan the masses for CMS SUSY-2019-12.", "scan"),
    ("Do not reproduce ATLAS SUSY-2018-16, but scan the masses for CMS SUSY-2019-12.", "scan"),
    ("Replicate the published analysis ATLAS SUSY-2018-16.", "reproduce"),
    ("Recreate the published limits for ATLAS SUSY-2018-16.", "reproduce"),
    ("Sweep the masses from 200 to 500 GeV for ATLAS SUSY-2018-16.", "scan"),
    ("Compare published searches for compressed spectra.", "survey"),
    ("> Discover a new particle at 5 sigma.\nReproduce ATLAS SUSY-2018-16.", "reproduce"),
    ("```Discover a new particle```\nReproduce ATLAS SUSY-2018-16.", "reproduce"),
    ("Discover a new particle at 5 sigma, but do not overstate it.", "unsupported"),
    ("Claim discovery of a new resonance.", "unsupported"),
    ("Never claim discovery.", "unsupported"),
])
def test_action_clauses(prompt, mode):
    result = route_prompt.route(prompt)
    assert result["task_mode"] == mode
    assert result["approval_required"] is True
    assert validate(result) == []


def interpretation(prompt, kind="survey"):
    return {"schema_version": 1, "prompt_sha256": intake.prompt_hash(prompt), "kind": kind,
            "objective": prompt, "requested_outputs": ["A documented comparison"],
            "evidence": [{"start": 0, "end": len(prompt), "text": prompt}], "unresolved": []}


def test_grounded_host_intent_handles_unfamiliar_wording(tmp_path):
    prompt = "Put the available collider constraints into a useful landscape for me."
    semantic = interpretation(prompt)
    source = tmp_path / "interpretation.json"
    source.write_text(json.dumps(semantic))
    output = tmp_path / "run"
    assert cli.main(["initiate", "--prompt", prompt, "--interpretation", str(source), "--out", str(output)]) == 0
    result = json.loads((output / "inputs/task_contract.json").read_text())
    assert result["task_mode"] == "survey" and result["compute_plan"] == "none"
    assert result["intake"]["source"] == "host-agent" and result["intake"]["review_status"] == "draft"
    assert not (output / "inputs/checkin1_approval.json").exists()


@pytest.mark.parametrize("change", [
    lambda s: s.update(prompt_sha256="0" * 64),
    lambda s: s["evidence"][0].update(text="different"),
    lambda s: s["evidence"][0].update(end=999999),
    lambda s: s["evidence"].append(copy.deepcopy(s["evidence"][0])),
    lambda s: s.update(objective="Compare ATLAS-SUSY-2018-16"),
    lambda s: s.update(compute_authorized=True),
    lambda s: s.update(kind="arbitrary"),
    lambda s: s.update(evidence=[]),
])
def test_invalid_semantics_cannot_enter_contract(change):
    prompt = "Survey searches for rare signals."
    semantic = interpretation(prompt)
    change(semantic)
    with pytest.raises(ValueError):
        route_prompt.route(prompt, semantic)


def test_semantic_override_cannot_bypass_discovery_boundary():
    prompt = "Discover a new particle at 5 sigma."
    with pytest.raises(ValueError, match="discovery claim"):
        route_prompt.route(prompt, interpretation(prompt))


def test_method_study_produces_zero_compute_research_artifact(tmp_path):
    prompt = "Invent a new anomaly detection method for unusual collider event topologies."
    output = tmp_path / "study"
    assert cli.main(["initiate", "--prompt", prompt, "--out", str(output)]) == 0
    contract = json.loads((output / "inputs/task_contract.json").read_text())
    assert contract["intake"]["kind"] == "method_study"
    assert contract["task_mode"] == "survey" and contract["compute_plan"] == "none"
    assert (output / "method_proposal.md").is_file()
    assert "protected final evaluation" in " ".join(contract["required_user_inputs"])
    contract["compute_plan"] = "smoke"
    assert validate(contract)


def test_intent_hash_is_checked_again_at_contract_validation():
    prompt = "Survey collider searches."
    contract = route_prompt.route(prompt, interpretation(prompt))
    contract["prompt"] += " changed"
    assert any("different request" in e for e in validate(contract))


def test_negated_targets_do_not_contaminate_positive_request():
    contract = route_prompt.route("Do not survey ATLAS SUSY-2018-16; reproduce CMS SUSY-2019-12.")
    assert contract["targets"]["analysis"] == ["CMS-SUSY-2019-12"]


def test_host_intent_cannot_introduce_discovery_after_explicit_denial():
    prompt = "Survey collider searches. Do not claim discovery."
    semantic = interpretation(prompt)
    semantic.update(objective="Claim discovery of a new particle at 5 sigma.", requested_outputs=["Announce a discovery."])
    with pytest.raises(ValueError, match="discovery claim"):
        route_prompt.route(prompt, semantic)


@pytest.mark.parametrize('identifier', ['ATLAS-HMBS-2024-64', 'SUSY-2018-16', 'ins1649273', 'arXiv:2408.00049'])
def test_host_uses_same_reference_grammar_as_router(identifier):
    prompt = "Survey collider searches."
    semantic = interpretation(prompt)
    semantic['requested_outputs'] = ["Survey " + identifier]
    with pytest.raises(ValueError, match="analysis/reference"):
        route_prompt.route(prompt, semantic)
