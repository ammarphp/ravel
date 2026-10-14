"""Deterministic parser coverage for ordinary request shapes and target extraction.

Every prompt here is written for this file in deliberately varied wording. The
assertions check request SHAPES (single-point exclusion questions, literature
questions, fits to published measurements, prescribed statistics, staged event
generation) and generic extraction rules, never a named benchmark or task.
"""
import synthetic_identifiers as syn
import json

import pytest

from ravel.validation.validate_task_contract import validate
from ravel.workflow import intake, route_prompt as rp


def _route(prompt, interpretation=None):
    contract = rp.route(prompt, interpretation=interpretation)
    assert validate(contract) == [], validate(contract)
    return contract


# ------------------------------------------------------------- single-point exclusion questions
@pytest.mark.parametrize("prompt", [
    "Would a 1.4 TeV gluino with a 250 GeV neutralino be excluded by the ATLAS zero-lepton search?",
    ("Is the spectrum with a 620 GeV top squark and a 90 GeV LSP excluded by " + syn.analysis(490) + "?"),
    "Could my model point (a 300 GeV smuon decaying to a 260 GeV bino) be excluded by the soft dilepton analysis?",
    "Tell me whether a 2.5 TeV leptoquark decaying to b tau is ruled out by the third-generation search.",
    "Check if our benchmark is excluded by existing LHC searches for displaced vertices.",
])
def test_single_point_exclusion_question_routes_reinterpret(prompt):
    c = _route(prompt)
    assert c["task_mode"] == "reinterpret"
    assert not c["blocking"]


@pytest.mark.parametrize("prompt", [
    "Would a 1.4 TeV gluino with a 250 GeV neutralino be excluded by the ATLAS zero-lepton search?",
    "Check if our benchmark is excluded by existing LHC searches for displaced vertices.",
    ("Reproduce the cutflow of arXiv:" + syn.arxiv(545) + " for its single benchmark point."),
])
def test_single_point_request_defaults_to_one_full_point(prompt):
    c = _route(prompt)
    assert c["compute_plan"] == "full"
    assert c["cost_estimate"]["mode"] == "full" and c["cost_estimate"]["points"] == 1
    assert not any("12-point" in a for a in c["assumptions"])


@pytest.mark.parametrize("prompt", [
    ("Is a 900 GeV wino excluded anywhere in the mass plane of arXiv:" + syn.arxiv(545) + "?"),
    ("Reinterpret arXiv:" + syn.arxiv(545) + " on a grid of chargino masses with a 100 GeV LSP."),
    "Reinterpret the dijet search for Z' masses from 1 to 4 TeV.",
    ("Reinterpret arXiv:" + syn.arxiv(545) + " with a mass scan at 750, 1000, 1250 GeV"),
    ("Reproduce Figure 3 of " + syn.analysis(1) + " for a slepton-bino model."),
])
def test_plane_grid_range_requests_keep_scan(prompt):
    assert _route(prompt)["compute_plan"] == "scan"


# ------------------------------------------------------------- survey takes precedence
@pytest.mark.parametrize("prompt", [
    "Which LHC searches constrain heavy neutral leptons lighter than 10 GeV?",
    "Which ATLAS and CMS analyses constrain long-lived charginos?",
    "Which measurements constrain an invisible width of the Higgs boson?",
    "What are the strongest limits on a kinetically mixed dark photon?",
    "What are the current limits on vector-like bottom partners?",
])
def test_literature_question_routes_survey_without_compute(prompt):
    c = _route(prompt)
    assert c["task_mode"] == "survey"
    assert c["compute_plan"] == "none"


def test_bare_constrain_without_point_cue_is_not_a_generation_scan():
    c = _route("Constrain the Higgs boson self-coupling.")
    assert c["task_mode"] != "reinterpret"
    assert c["compute_plan"] not in ("scan", "full")


def test_constrain_with_model_point_cue_still_reinterprets():
    c = _route("Use the dilepton resonance search to constrain my 3 TeV Z' model.")
    assert c["task_mode"] == "reinterpret"


# ------------------------------------------------------------- fits to published measurements
@pytest.mark.parametrize("prompt", [
    "Fit the Wilson coefficients C_phiq3 and C_ll using published electroweak precision measurements and their correlations.",
    "Use unfolded top-pair differential cross-section measurements to constrain two SMEFT operators.",
    "Bound the Higgs coupling modifiers kappa_V and kappa_F with the 13 TeV signal-strength measurements, including the covariance.",
])
def test_measurement_fit_routes_to_the_measurement_fit_operation_without_generation(prompt):
    c = _route(prompt)
    assert c["task_mode"] == "calculation" and c["intake"]["operation"] == "measurement_fit"
    assert c["compute_plan"] == "none"
    assert c["targets"]["masses_gev"] == []
    assert any("measurement" in e.lower() for e in c["escalate"] + c["required_user_inputs"])


# ------------------------------------------------------------- target extraction
@pytest.mark.parametrize("prompt,masses", [
    ("Reinterpret the search at 13 TeV for a 1.5 TeV W' boson.", [1500.0]),
    ("Survey 13.6 TeV searches for a 700 GeV scalar.", [700.0]),
    ("Reinterpret a 2 TeV Z' with 139 fb^-1 and 13 TeV data.", [2000.0]),
    ("Calculate the rate for a 4 TeV Z' with Gamma = 120 GeV.", [4000.0]),
    ("Calculate the rate for a 4 TeV Z' with a total width of 120 GeV.", [4000.0]),
    ("Compute the total width of a 2.5 TeV W' with coupling 0.3.", [2500.0]),
    ("Calculate the rate for a 4 TeV Z' with a 120 GeV width.", [4000.0]),
    ("Compute the cross-section for an ALP with f_a = 1 TeV and a 400 GeV mass.", [400.0]),
    ("Survey sleptons with mass splittings below 20 GeV.", []),
    ("Survey searches for higgsinos with Δm = 5 GeV and masses near 150 GeV.", [150.0]),
    ("Summarize limits on a Z' with m(Z') less than 500 GeV.", []),
    ("Reinterpret the monojet search for a 50 GeV mediator with jet pT > 250 GeV.", [50.0]),
    ("Calculate the decay rate of a scalar with m_a = 2 MeV.", [0.002]),
    ("Calculate the lifetime of a 750 MeV ALP.", [0.75]),
])
def test_mass_extraction_rejects_energies_widths_and_bounds(prompt, masses):
    assert _route(prompt)["targets"]["masses_gev"] == pytest.approx(masses)


def test_collision_energy_is_recorded_separately():
    c = _route("Reinterpret the search at 13 TeV for a 1.5 TeV W' boson.")
    assert c["targets"]["sqrt_s_gev"] == 13000.0


def test_luminosity_list_does_not_become_masses():
    c = _route("Reinterpret a 2 TeV Z' with 139 fb^-1 and 13 TeV data.")
    assert c["targets"]["lumi_fb"] == 139.0
    assert 1000.0 not in c["targets"]["masses_gev"]


@pytest.mark.parametrize("prompt,model", [
    ("Reinterpret the dilepton search for a 3 TeV Z' boson.", "Z'"),
    ("Reinterpret the lepton plus MET search for a 5 TeV W′.", "W′"),
])
def test_model_hint_keeps_the_prime(prompt, model):
    c = _route(prompt)
    assert c["targets"]["model"] == model
    assert model in c["targets"]["models"]


def test_bare_letter_is_not_a_model():
    c = _route("Evaluate Z = 2(sqrt(S+B) - sqrt(B)) for S = 10 and B = 40.")
    assert c["targets"]["model"] is None


def test_all_vocabulary_models_are_collected():
    c = _route("Summarize limits on a new spin-0 state, for example a radion or a heavy Higgs, "
               "decaying to top pairs.")
    assert {"radion", "heavy Higgs"} <= {m for m in c["targets"]["models"]}


def test_vocabulary_is_a_generic_data_file():
    vocab = rp.bsm_vocabulary()
    assert len(vocab) >= 40
    assert all(isinstance(term, str) and term.strip() for term in vocab)


@pytest.mark.parametrize("prompt,routine,inspire", [
    ("Run SYN_9040_I1228 over my HepMC sample.", "SYN_9040_I1228", "ins1228"),
    ("Apply the routine SYN_9421_I1440 to the supplied events.", "SYN_9421_I1440", "ins1440"),
])
def test_rivet_routine_identifier_is_an_input(prompt, routine, inspire):
    c = _route(prompt)
    assert routine in c["targets"]["analysis"]
    assert inspire in c["targets"]["inspire"]


@pytest.mark.parametrize("prompt,record", [
    ("Compare my histogram with HEPData record 2015.", "2015"),
    ("Take the covariance from https://www.hepdata.net/record/2007 and survey the limits.", "2007"),
])
def test_hepdata_record_identifier_is_an_input(prompt, record):
    assert record in _route(prompt)["targets"]["hepdata"]


def _interpretation(prompt, kind, **extra):
    return {"schema_version": 1, "prompt_sha256": intake.prompt_hash(prompt), "kind": kind,
            "objective": prompt, "requested_outputs": [prompt],
            "evidence": [{"start": 0, "end": len(prompt), "text": prompt}], "unresolved": [], **extra}


def test_host_interpretation_overrides_extracted_targets():
    prompt = "Reinterpret the beam-dump search for an ALP with mass one twentieth of an MeV at 13 TeV."
    interp = _interpretation(prompt, "reinterpret",
                             targets={"masses_gev": [0.00005], "model": "ALP", "sqrt_s_gev": 13000.0})
    c = _route(prompt, interp)
    assert c["targets"]["masses_gev"] == [0.00005]
    assert c["targets"]["model"] == "ALP"


def test_host_interpretation_cannot_add_unstated_identifier():
    prompt = "Reinterpret the beam-dump search for a light ALP."
    interp = _interpretation(prompt, "reinterpret", targets={"arxiv": [(syn.arxiv(545))]})
    with pytest.raises(ValueError):
        rp.route(prompt, interpretation=interp)


# ------------------------------------------------------------- prescribed statistics
@pytest.mark.parametrize("prompt,span", [
    ("Determine the 2-sigma excluded region for a leptophobic W' in the coupling-mass plane.",
     "2-sigma excluded region"),
    ("Scan the Z' mass from 1 to 3 TeV and draw the 3σ exclusion contour.", "3σ exclusion contour"),
    ("Reinterpret the tau search for a 1 TeV Z' using Δχ² = 4 as the exclusion criterion.", "Δχ²"),
    ("Reinterpret the tau search for a 1 TeV Z' using delta chi2 < 4.", "delta chi2"),
    ("Is a 400 GeV stop excluded at 90% CL by the one-lepton search?", "90% CL"),
])
def test_prescribed_statistic_is_the_requested_quantity(prompt, span):
    c = _route(prompt)
    assert c["stat_mode"] == "prescribed-statistic"
    assert span in c["stat_mode_note"]
    assert any(span in e for e in c["escalate"])


def test_prescribed_formula_is_recorded_for_a_calculation():
    prompt = "Evaluate Z = 2(sqrt(S+B) - sqrt(B)) for S = 10 and B = 40 at 139 fb^-1."
    c = _route(prompt)
    assert c["task_mode"] == "calculation"
    assert "2(sqrt(S+B) - sqrt(B))" in c["stat_mode_note"]


def test_default_cls_request_is_not_prescribed():
    c = _route("Is a 1 TeV gluino excluded at 95% CLs by the multijet search?")
    assert c["stat_mode"] != "prescribed-statistic"
    assert "stat_mode_note" not in c


# ------------------------------------------------------------- generation with later stages
def test_generate_request_with_shower_records_blocking_stage():
    # The scoped shower stage runs Pythia 8; a Herwig shower keeps the request whole as a research
    # parent with the shower stage and the Herwig tool as obligations (rule D5).
    c = _route("Generate 20k Drell-Yan events with MadGraph, shower them with Herwig and "
               "histogram the dilepton mass.")
    assert c["task_mode"] == "research" and c["compute_plan"] == "none"
    criteria = [o["criteria"] for o in c["task_requirements"]["obligations"]]
    assert any(x.get("stage") == "shower" for x in criteria) and any(x.get("tool") == "Herwig" for x in criteria)


def test_generate_interpretation_with_detector_stage_records_blocking():
    prompt = "Produce events for my model, pass them through Delphes, and plot the leading-jet pT."
    interp = _interpretation(prompt, "generate")
    c = _route(prompt, interp)
    assert c["task_mode"] == "generate"
    assert any("detector" in b for b in c["blocking"])


def test_parton_level_generation_has_no_blocking():
    c = _route("Generate 5000 parton-level events of p p > t t~ with MadGraph.")
    assert c["task_mode"] == "generate"
    assert c["blocking"] == []


# ------------------------------------------------------------- selftest
def test_reference_prompts_are_generic_and_selftest_passes(capsys):
    rp.selftest()
    text = json.dumps(rp.REFERENCE_PROMPTS).lower()
    for word in ("toponium", "hvt", "svj", "semi-visible", "dark pion", (syn.arxiv(11))):
        assert word not in text
