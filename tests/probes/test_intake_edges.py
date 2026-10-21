"""Physicist requests with mixed conventions and incomplete instructions.

These exercise the deterministic reading, proposed plan and check-in surface;
model-driven clarification is reserved for the live follow-up protocol.
"""
import pytest

from ravel.workflow import request_reading as reading, request_plan as planning


def proposed(prompt):
    record = reading.document(prompt)
    assert reading.check(record, prompt) == []
    plan = planning.draft(record, {"prompt": prompt}, catalogue=lambda _: False)
    sections, flags = planning.checkin_sections(record, plan)
    return record, plan, sections, flags


@pytest.mark.parametrize("energy", [27, 100], ids=["27-tev", "100-tev"])
def test_unusual_collision_energy_with_mixed_mass_units(energy):
    prompt = (f"Set limits on a scalar with mass 1.4 TeV decaying to a particle with mass 250 GeV "
              f"at a {energy} TeV collider, using 12 fb^-1 of collision data.")
    record, plan, sections, flags = proposed(prompt)
    facts = record["facts"]
    assert [f["value"]["gev"] for f in facts if f["type"] == "mass"] == [1400., 250.], record
    assert [f["value"]["gev"] for f in facts if f["type"] == "collision_energy"] == [energy * 1000.], record
    assert len([f for f in facts if f["type"] == "luminosity"]) == 1
    claims = [c for c in plan["claims"] if c["kind"] == "exclusion"]
    assert claims and all(c["statistic"]["definition"] == "95% CLs" for c in claims), plan
    assert all(s["fidelity"] for s in sections["claims"])


def test_vague_model_question_keeps_missing_masses_unassigned():
    record, plan, sections, flags = proposed(
        "Is my scalar model excluded? The model package is supplied at ./inputs/model.zip.")
    assert not any(f["type"] in ("mass", "parameter_range", "parameter_values") for f in record["facts"])
    # The model package can supply parameters when inspected. A draft may choose
    # an operation or research envelope; neither supplies a missing mass itself.
    assert plan["claims"] and sections["plan"]
    assert all(value is None for value in plan["aggregate_budget"].values())
    assert any(c["obligation_id"] == "original-request" and c["by"] for c in sections["coverage"])
    assert plan["status"] == "draft"
    assert all(s["fidelity"] for s in sections["claims"])


def test_unresolved_paper_title_preserves_statistic_outside_title():
    prompt = ('Use the paper titled "Scalar limits at 81 TeV with 5 sigma evidence"; '
              'report the 3-sigma excluded region for the supplied model.')
    record, plan, sections, flags = proposed(prompt)
    titles = [f for f in record["facts"] if f["type"] == "publication_title"]
    assert len(titles) == 1 and titles[0]["value"]["resolution_required"]
    assert not any(f["type"] in ("identifier", "mass", "collision_energy") for f in record["facts"])
    prescriptions = [c for c in plan["claims"] if c["kind"] == "exclusion"]
    assert prescriptions and all(c["statistic"]["source"] == "prescribed" and
                                "3-sigma" in c["statistic"]["definition"] for c in prescriptions), plan
    assert any(a["physics_critical"] and a["status"] == "open" and
               a["issue"].startswith("construction of the prescribed statistic") for a in sections["ambiguities"])


def test_changed_approval_wording_preserves_new_statistic_and_open_construction():
    record, plan, sections, flags = proposed(
        "Go ahead but use the 3-sigma excluded region for the scalar model. Run autonomously.")
    claims = [c for c in plan["claims"] if c["kind"] == "exclusion"]
    assert claims and all(c["statistic"]["source"] == "prescribed" and
                         "3-sigma" in c["statistic"]["definition"] for c in claims), plan
    assert any(a["physics_critical"] and a["status"] == "open" and
               "construction" in a["issue"] for a in sections["ambiguities"])
    delegation = [c for c in record["constraints"] if c["type"] == "delegation"]
    assert delegation and all(c["value"]["authority_granted"] is False for c in delegation)


def test_conflicting_same_sample_energies_reach_checkin_with_remedy():
    record, plan, sections, flags = proposed(
        "Set limits using the same sample at a 27 TeV collider and at a 100 TeV collider, with 12 fb^-1.")
    conflicts = [b for b in record["boundaries"] if b["class"] == "contradiction"]
    assert conflicts and all(b["would_make_possible"] and len(b["evidence"]) >= 2 for b in conflicts), record
    assert {b["id"] for b in conflicts} <= {b["id"] for b in sections["boundaries"]}
    assert any("different values of collision energy" in flag["text"] for flag in flags), flags
