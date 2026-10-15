"""CHECK-IN 1 variants keyed by the task: each variant asks for the content that task needs."""
import json

import pytest

from ravel.validation import validate_checkin as vc


CORE = {"i": "We will compute the requested quantity from the stated inputs.",
        "iv": {"steps": ["evaluate", "cross-check"], "budget": "one bounded evaluation"},
        "v": [{"id": "F1", "assumption": "the stated convention is the intended one", "why": "the request names it"}],
        "vi": [{"mode": "answer"}, {"mode": "ask"}, {"mode": "propose"}]}

VARIANT_CONTENT = {
    "calculation": {"formula": "Gamma(X -> f fbar) = N_c g^2 m_X / (12 pi) (1 + 2 m_f^2/m_X^2) beta_f",
                    "conventions": "couplings normalised as in the supplied Lagrangian; natural units",
                    "inputs": {"m_X": "800 GeV", "g": 0.25},
                    "precision": "tree level; relative numerical error below 1e-6",
                    "check_value": "massless-fermion limit reproduces g^2 m_X / (12 pi) per colour"},
    "method_study": {"dataset": "simulated signal and background samples named in the request",
                     "splits": "train 60%, validation 20%, held-out test 20% by event number",
                     "baselines": ["cut-based selection from the reference search"],
                     "calibration": "background efficiency measured on the held-out sample"},
    "survey": {"census_table": [{"analysis": "search A", "experiment": "first", "luminosity": "139 fb^-1"},
                                {"analysis": "search B", "experiment": "second", "luminosity": "138 fb^-1"}],
               "coverage_gaps": ["no public result below the stated mass range"]},
    "manuscript": {"source_runs": [{"path": "runs/study-one", "result": "outputs/result.json"}],
                   "template": "journal two-column template supplied by the user"},
    "generate": {"recipe": "leading-order process with the supplied model, 10k events, fixed seed",
                 "observable": "normalised dilepton invariant mass, 40 bins from 0 to 2 TeV"},
    "new_search": {"blinding": "signal region data stay hidden until the background model is frozen",
                   "regions": [{"name": "SR", "definition": "two leptons, high missing momentum"},
                               {"name": "CR", "definition": "inverted missing-momentum requirement"}],
                   "validation": "background model checked in validation regions adjacent to SR"},
}


def checkin(variant, **extra):
    sections = {**CORE, **VARIANT_CONTENT[variant], **extra}
    return {"schema_version": 1, "kind": "checkin1", "variant": variant, "sections": sections}


def with_contract(tmp_path, task_mode, **extra):
    (tmp_path / "inputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "inputs" / "task_contract.json").write_text(json.dumps({"task_mode": task_mode, **extra}))
    return str(tmp_path)


@pytest.mark.parametrize("variant", sorted(VARIANT_CONTENT))
def test_each_variant_validates_without_reproduction_sections(variant):
    assert vc.validate(checkin(variant)) == []


@pytest.mark.parametrize("variant", sorted(VARIANT_CONTENT))
def test_each_variant_requires_its_own_sections(variant):
    for key in VARIANT_CONTENT[variant]:
        document = checkin(variant)
        del document["sections"][key]
        errors = vc.validate(document)
        assert any(f"({key})" in e for e in errors), (key, errors)


@pytest.mark.parametrize("variant,key", [("calculation", "precision"), ("method_study", "splits"),
                                         ("generate", "observable"), ("new_search", "blinding"),
                                         ("manuscript", "template")])
@pytest.mark.parametrize("placeholder", ["N/A", "not applicable", "", "TBD", {"note": "n/a"}, []])
def test_placeholder_content_is_not_a_section(variant, key, placeholder):
    errors = vc.validate(checkin(variant, **{key: placeholder}))
    assert any(f"({key})" in e for e in errors), errors


def test_survey_census_table_needs_identified_rows():
    errors = vc.validate(checkin("survey", census_table=[{"luminosity": "139 fb^-1"}]))
    assert any("census_table" in e for e in errors), errors
    errors = vc.validate(checkin("survey", census_table="see attached"))
    assert any("census_table" in e for e in errors), errors


def test_survey_with_no_coverage_gaps_states_an_empty_list():
    assert vc.validate(checkin("survey", coverage_gaps=[])) == []


def test_manuscript_lists_each_source_run_by_path():
    errors = vc.validate(checkin("manuscript", source_runs=[{"note": "the earlier run"}]))
    assert any("source_runs" in e for e in errors), errors


def test_unknown_variant_is_rejected():
    document = checkin("calculation")
    document["variant"] = "anything-goes"
    assert any("variant" in e for e in vc.validate(document))


@pytest.mark.parametrize("task_mode,variant", [("calculation", "calculation"), ("likelihood", "calculation"),
                                               ("generate", "generate"), ("survey", "survey"),
                                               ("summary_plot", "survey"), ("anomaly_search", "new_search")])
def test_task_mode_selects_the_variant_when_none_is_declared(tmp_path, task_mode, variant):
    base = with_contract(tmp_path, task_mode)
    document = checkin(variant)
    del document["variant"]
    assert vc.validate(document, base_dir=base) == []
    assert vc.checkin1_variant(document, vc._sibling_contract(base)) == variant


def test_method_study_intake_selects_the_method_variant(tmp_path):
    base = with_contract(tmp_path, "survey", intake={"kind": "method_study"})
    document = checkin("method_study")
    del document["variant"]
    assert vc.validate(document, base_dir=base) == []


def test_declared_variant_must_fit_the_task(tmp_path):
    base = with_contract(tmp_path, "calculation")
    errors = vc.validate(checkin("survey"), base_dir=base)
    assert any("does not fit task_mode calculation" in e for e in errors), errors


def test_research_task_declares_its_variant(tmp_path):
    base = with_contract(tmp_path, "research")
    assert vc.validate(checkin("new_search"), base_dir=base) == []
    assert vc.validate(checkin("method_study"), base_dir=base) == []
    document = checkin("new_search")
    del document["variant"]
    errors = vc.validate(document, base_dir=base)
    assert any("declare" in e and "variant" in e for e in errors), errors


def reproduction(**sections):
    base = {**CORE, "i-b": {"hepdata": "record with observed limits", "likelihood": "full likelihood released"},
            "ii": [{"figure_id": "Figure 7", "caption": "observed and expected exclusion contour"}],
            "iii": {"figure_id": "Figure 7", "waypoint": "background-only spectrum at low statistics"}}
    base.update(sections)
    return {"schema_version": 1, "kind": "checkin1", "sections": base}


@pytest.mark.parametrize("task_mode", ["reproduce", "reinterpret", "projection"])
def test_reproduction_keeps_gallery_and_waypoint(tmp_path, task_mode):
    base = with_contract(tmp_path, task_mode)
    assert vc.validate(reproduction(), base_dir=base) == []
    errors = vc.validate(reproduction(ii="not applicable"), base_dir=base)
    assert any("(ii)" in e for e in errors), errors


def test_reproduction_variant_needs_a_waypoint():
    document = reproduction(iii={"figure_id": "Figure 7"})
    assert any("waypoint" in e for e in vc.validate(document))


def test_seven_section_form_without_contract_keeps_working():
    assert vc.validate(reproduction()) == []


def test_seven_section_form_with_stand_ins_points_a_calculation_to_its_variant(tmp_path):
    base = with_contract(tmp_path, "calculation")
    document = reproduction(ii="not applicable")
    errors = vc.validate(document, base_dir=base)
    assert any("(ii)" in e for e in errors)
    assert any("calculation variant" in e for e in errors), errors


def test_checkin_variant_is_the_single_contract_reader():
    shape = vc.checkin_variant({"task_mode": "calculation"})
    assert shape["core"] == vc.CHECKIN1_CORE
    assert shape["allowed"] == ("calculation",)
    assert shape["sections"]["calculation"] == vc.CHECKIN1_VARIANTS["calculation"]
    assert vc.checkin_variant({"task_mode": "reinterpret"})["allowed"] == ("reproduction", "reference_withheld")
    assert vc.checkin_variant({"task_mode": "research", "intake": {"kind": "manuscript"}})["allowed"] == ("manuscript",)
    assert vc.checkin_variant(None)["allowed"] is None


def test_validation_follows_checkin_variant(monkeypatch):
    def derived(contract):
        return {"core": vc.CHECKIN1_CORE, "allowed": ("generate",),
                "sections": {"generate": ("recipe",)}}

    monkeypatch.setattr(vc, "checkin_variant", derived)
    document = checkin("generate")
    del document["sections"]["observable"]
    assert vc.validate(document) == []
