"""Intent is grounded and negation aware; a draft never grants new execution rights."""
import synthetic_identifiers as syn
import copy
import json

import pytest

from ravel import cli
from ravel.workflow import intake, route_prompt
from ravel.validation.validate_task_contract import validate


@pytest.mark.parametrize('prompt', [
    ('Reinterpret ' + syn.analysis(19) + ' for a slepton model.'),
    'Reproduce an unspecified slepton search.',
    ('Reproduce ' + syn.analysis(493) + ' for sleptons.'),
    ('Compare and reproduce ' + syn.analysis(1) + ' and ' + syn.analysis(7) + '.'),
])
def test_particle_or_ambiguous_analysis_does_not_select_compressed_native_pipeline(prompt):
    result = route_prompt.route(prompt)
    assert result['detector_mode'] == 'TBD-judgment'
    assert result['stat_mode'] == 'TBD-judgment'
    assert validate(result) == []


@pytest.mark.parametrize('identity', [(syn.analysis(1)), 'ins1001', (syn.analysis(12))])
def test_identities_without_a_supplied_package_do_not_route_natively(identity):
    # Native selections arrive as supplied analysis packages; no identity is built in.
    result = route_prompt.route('Reproduce ' + identity + '.')
    assert result['detector_mode'] == 'TBD-judgment'
    assert validate(result) == []


@pytest.mark.parametrize('identity,statistic', [
    ('FictionalRoutine700', 'published-likelihood'),
])
def test_registered_native_family_uses_its_actual_statistical_scope(identity, statistic, monkeypatch):
    from ravel.physics.native_capabilities import CAPABILITIES
    monkeypatch.setitem(CAPABILITIES, 'FictionalRoutine700', {
        'analysis_ids': ('FictionalRoutine700',), 'routine': 'FictionalRoutine700',
        'models': ('fictional-model',), 'preparations': ('explicit-cards',),
        'detector': 'simpleanalysis-delphes', 'statistics': ('yields', 'mapped-likelihood'),
        'needs_restframes': False})
    result = route_prompt.route('Reproduce ' + identity + '.')
    assert result['detector_mode'] == 'simpleanalysis-delphes-native'
    assert result['stat_mode'] == statistic
    assert validate(result) == []


def test_shape_intake_preserves_native_model_and_cms_identity_choices():
    result = route_prompt.route(('Reproduce the template fit of ' + syn.analysis(28) + '.'))
    assert result['targets']['analysis'] == [(syn.analysis(28))]
    assert result['stat_mode'] == 'shape-fit'
    assert any('native runtime' in text for text in result['escalate'])
    assert all('40%' not in text for text in result['escalate'])
    assert validate(result) == []


@pytest.mark.parametrize("prompt,mode", [
    ("Survey ATLAS searches and plot published observed and expected limits.", "survey"),
    (("Reproduce the observed and expected limits for " + syn.analysis(1) + "."), "reproduce"),
    ("Fit the supplied pyhf likelihood and compute expected limits without generating events.", "likelihood"),
    ("Project expected limits to the HL-LHC at 3000 fb^-1.", "projection"),
])
def test_expected_statistic_is_not_itself_a_future_projection(prompt, mode):
    contract = route_prompt.route(prompt)
    assert contract["task_mode"] == mode
    assert contract["approval_required"] is True
    if mode in {"survey", "unsupported"}:
        assert contract["compute_plan"] == "none"


@pytest.mark.parametrize("prompt,mode", [
    (("Do not claim discovery; reproduce " + syn.analysis(1) + "."), "reproduce"),
    (("Reproduce " + syn.analysis(1) + " without a 5 sigma discovery claim."), "reproduce"),
    (("Never discover a new particle. Reproduce " + syn.analysis(1) + "."), "reproduce"),
    ("Don't scan the masses; survey ATLAS searches.", "survey"),
    (("I don't want a discovery claim, I want to reproduce " + syn.analysis(1) + "."), "reproduce"),
    (("Do not claim discovery and reproduce " + syn.analysis(1) + "."), "unsupported"),
    (("I do not want you to reproduce " + syn.analysis(1) + " and scan the masses."), "unsupported"),
    (("Neither reproduce " + syn.analysis(1) + " nor scan the masses."), "unsupported"),
    (("Do not reproduce " + syn.analysis(1) + "; scan the masses for " + syn.analysis(13) + "."), "scan"),
    (("Do not reproduce " + syn.analysis(1) + ", but scan the masses for " + syn.analysis(13) + "."), "scan"),
    (("Replicate the published analysis " + syn.analysis(1) + "."), "reproduce"),
    (("Recreate the published limits for " + syn.analysis(1) + "."), "reproduce"),
    (("Sweep the masses from 200 to 500 GeV for " + syn.analysis(1) + "."), "scan"),
    ("Compare published searches for compressed spectra.", "survey"),
    (("> Discover a new particle at 5 sigma.\nReproduce " + syn.analysis(1) + "."), "reproduce"),
    (("```Discover a new particle```\nReproduce " + syn.analysis(1) + "."), "reproduce"),
    ("Discover a new particle at 5 sigma, but do not overstate it.", "research"),
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
    lambda s: s.update(objective=("Compare " + syn.analysis(1))),
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
    prompt = "Claim discovery of a new particle at 5 sigma."
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
    contract = route_prompt.route(("Do not survey " + syn.analysis(1) + "; reproduce " + syn.analysis(13) + "."))
    assert contract["targets"]["analysis"] == [(syn.analysis(13))]


def test_host_intent_cannot_introduce_discovery_after_explicit_denial():
    prompt = "Survey collider searches. Do not claim discovery."
    semantic = interpretation(prompt)
    semantic.update(objective="Claim discovery of a new particle at 5 sigma.", requested_outputs=["Announce a discovery."])
    with pytest.raises(ValueError, match="discovery claim"):
        route_prompt.route(prompt, semantic)


@pytest.mark.parametrize('identifier', [(syn.analysis(494)), (syn.analysis(1)), 'ins1009', ('arXiv:' + syn.arxiv(11))])
def test_host_uses_same_reference_grammar_as_router(identifier):
    prompt = "Survey collider searches."
    semantic = interpretation(prompt)
    semantic['requested_outputs'] = ["Survey " + identifier]
    with pytest.raises(ValueError, match="analysis/reference"):
        route_prompt.route(prompt, semantic)
