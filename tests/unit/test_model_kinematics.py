import hashlib
import json
from fractions import Fraction

import pytest

from ravel.physics import model_inputs, model_kinematics as kin, model_input_study as study


def context(raw, semantics="on_shell_final_states", convention="nonnegative_only", *, line=6, daughters=None):
    evidence = "Declared on-shell final states for a bounded necessary-condition test."
    return {"schema_version": 1, "source_sha256": hashlib.sha256(raw).hexdigest(),
        "mass_convention": convention, "sources": {}, "supplemental_masses": [],
        "channel_semantics": [{"source_line": line, "parent_pdg": 25,
            "daughter_pdgs": daughters or [1000022, -1000022], "interpretation": semantics,
            "source_ref": "test physical premise", "evidence_text": evidence,
            "evidence_sha256": hashlib.sha256(evidence.encode()).hexdigest()}]}


def prepare(tmp_path, mass="20", *, br="1", width=".004", semantics="on_shell_final_states", convention="nonnegative_only"):
    raw = f"BLOCK MASS\n 25 125\n 1000022 {mass}\nDECAY 1000022 0\nDECAY 25 {width}\n {br} 2 1000022 -1000022\n".encode()
    source = tmp_path / "card.slha"
    source.write_bytes(raw)
    complete = tmp_path / "complete.json"
    complete.write_text(json.dumps(model_inputs.make_manifest(raw)))
    file = tmp_path / "kinematics.json"
    file.write_text(json.dumps(context(raw, semantics, convention)))
    task = {"slha_file": str(source), "source_sha256": hashlib.sha256(raw).hexdigest(),
            "completeness_file": str(complete), "kinematics_file": str(file)}
    return task, file, source


@pytest.mark.parametrize("mass,status,slack", [("20", "on_shell_necessary_condition_met", "85/1"),
    ("62.5", "exact_threshold_boundary", "0/1"), ("80", "on_shell_necessary_condition_violated", "-35/1")])
def test_necessary_condition_separates_open_boundary_and_deficit(tmp_path, mass, status, slack):
    task, file, source = prepare(tmp_path, mass)
    before = source.read_bytes()
    result = study.run(task, tmp_path, tmp_path / "out")
    channel = result["details"]["conditional_kinematics"]["channels"][0]
    assert channel["status"] == status and channel["mass_slack_GeV_exact"] == slack
    assert result["preflight_disposition"] == "static_inventory"
    assert result["status"] == "passed" and result["physics_validated"] is result["execution_authorized"] is False
    assert source.read_bytes() == before
    assert any(f["classification"] == "source_conditional_kinematic_anomaly" for f in result["details"]["findings"]) == (status.endswith("violated"))


@pytest.mark.parametrize("semantics,status", [("unknown", "unresolved_channel_semantics"),
    ("off_shell_inclusive", "not_applicable_off_shell_inclusive")])
def test_below_nominal_resonance_threshold_does_not_reject_inclusive_channel(tmp_path, semantics, status):
    task, _, _ = prepare(tmp_path, "80", semantics=semantics)
    result = study.run(task, tmp_path, tmp_path / "out")
    channel = result["details"]["conditional_kinematics"]["channels"][0]
    assert channel["status"] == status and channel["mass_slack_GeV_exact"] == "-35/1"
    assert not any(f["classification"] == "source_conditional_kinematic_anomaly" for f in result["details"]["findings"])


@pytest.mark.parametrize("convention,status", [("nonnegative_only", "unresolved_missing_or_signed_mass"),
    ("slha1_signed_neutralino", "on_shell_necessary_condition_met")])
def test_signed_neutralino_needs_explicit_SLHA_convention(tmp_path, convention, status):
    task, _, _ = prepare(tmp_path, "-20", convention=convention)
    result = study.run(task, tmp_path, tmp_path / "out")
    channel = result["details"]["conditional_kinematics"]["channels"][0]
    assert channel["status"] == status
    if convention == "slha1_signed_neutralino":
        assert channel["daughter_mass_sum_GeV_exact"] == "40/1"
        assert channel["mass_origins"][1]["interpretation"].startswith("magnitude_of_declared_SLHA1")
    assert result["details"]["inventory"]["masses"][1]["mass_GeV_exact"] == "-20/1"


def test_unknown_daughter_is_never_zero_filled(tmp_path):
    task, file, source = prepare(tmp_path)
    source.write_bytes(source.read_bytes().replace(b"1000022 20", b"1000035 20"))
    task["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    (tmp_path / "complete.json").write_text(json.dumps(model_inputs.make_manifest(source.read_bytes())))
    data = json.loads(file.read_text()); data["source_sha256"] = task["source_sha256"]
    file.write_text(json.dumps(data))
    result = study.run(task, tmp_path, tmp_path / "out")
    channel = result["details"]["conditional_kinematics"]["channels"][0]
    assert channel["status"] == "unresolved_missing_or_signed_mass"
    assert channel["unresolved_mass_pdgs"] == [-1000022, 1000022]
    assert "daughter_mass_sum_GeV_exact" not in channel


def test_arbitrary_negative_scalar_not_abs_coerced(tmp_path):
    task, file, source = prepare(tmp_path)
    raw = source.read_bytes().replace(b"25 125", b"25 -125")
    source.write_bytes(raw); task["source_sha256"] = hashlib.sha256(raw).hexdigest()
    (tmp_path / "complete.json").write_text(json.dumps(model_inputs.make_manifest(raw)))
    data = json.loads(file.read_text()); data["source_sha256"] = task["source_sha256"]; data["mass_convention"] = "slha1_signed_neutralino"
    file.write_text(json.dumps(data))
    result = study.run(task, tmp_path, tmp_path / "out")
    channel = result["details"]["conditional_kinematics"]["channels"][0]
    assert channel["status"] == "unresolved_missing_or_signed_mass" and channel["unresolved_mass_pdgs"] == [25]


@pytest.mark.parametrize("br,width", [("0", ".004"), ("1", "0")])
def test_inactive_source_channel_is_not_positive_BR_contradiction(tmp_path, br, width):
    task, _, _ = prepare(tmp_path, "80", br=br, width=width)
    result = study.run(task, tmp_path, tmp_path / "out")
    assert result["details"]["conditional_kinematics"]["channels"][0]["status"] == "inactive_by_supplied_width_or_BR"


def add_supplemental(tmp_path, file, *, pdg=13, token="106.", unit="MeV"):
    source = tmp_path / "model-definition.txt"
    text = f"mu = Particle(pdg={pdg}, mass=106.*MeV)"
    source.write_text(text + "\n")
    data = json.loads(file.read_text())
    data["sources"] = {"model": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}
    data["supplemental_masses"] = [{"pdg": pdg, "pdg_token": str(pdg), "mass_token": token, "unit": unit,
        "source_id": "model", "source_line": 1, "source_text": text}]
    file.write_text(json.dumps(data))
    return source


def test_external_mass_files_are_explicit_inputs_and_drift_fails_intake(tmp_path):
    task, file, _ = prepare(tmp_path)
    mass_source = add_supplemental(tmp_path, file)
    assert mass_source in study.inputs(task, tmp_path)
    mass_source.write_text("mu = Particle(pdg=13, mass=107.*MeV)\n")
    with pytest.raises(ValueError, match="evidence hash differs"):
        study.inputs(task, tmp_path)


@pytest.mark.parametrize("token,unit", [("107.", "MeV"), ("106.", "GeV")])
def test_token_and_unit_must_be_present_on_exact_pinned_line(tmp_path, token, unit):
    task, file, _ = prepare(tmp_path)
    add_supplemental(tmp_path, file, token=token, unit=unit)
    with pytest.raises(ValueError, match="token and declared unit"):
        study.inputs(task, tmp_path)


def test_external_mass_cannot_silently_override_supplied_mass(tmp_path):
    task, file, _ = prepare(tmp_path)
    add_supplemental(tmp_path, file, pdg=1000022)
    with pytest.raises(ValueError, match="cannot override"):
        study.run(task, tmp_path, tmp_path / "out")


@pytest.mark.parametrize("token", ["11", "130", "-13"])
def test_mass_source_cannot_be_relabeled_to_an_absent_particle_token(tmp_path, token):
    task, file, _ = prepare(tmp_path)
    add_supplemental(tmp_path, file)
    data = json.loads(file.read_text())
    data["supplemental_masses"][0]["pdg"] = int(token)
    data["supplemental_masses"][0]["pdg_token"] = token
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="PDG token must occur"):
        study.inputs(task, tmp_path)


def test_pdg_evidence_token_cannot_claim_another_signed_identity(tmp_path):
    task, file, _ = prepare(tmp_path)
    add_supplemental(tmp_path, file)
    data = json.loads(file.read_text()); data["supplemental_masses"][0]["pdg_token"] = "11"
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="differs from declared signed"):
        study.inputs(task, tmp_path)


def test_positive_pdg_token_cannot_match_a_negative_source_identity_substring(tmp_path):
    task, file, _ = prepare(tmp_path)
    source = add_supplemental(tmp_path, file, pdg=-13)
    data = json.loads(file.read_text()); record = data["supplemental_masses"][0]
    record.update(pdg=13, pdg_token="13")
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="PDG token must occur"):
        study.inputs(task, tmp_path)


def test_decimal_mass_is_not_accepted_as_particle_identity_token(tmp_path):
    task, file, _ = prepare(tmp_path)
    source = add_supplemental(tmp_path, file, pdg=11)
    text = "e = Particle(pdg=11, mass=13.*MeV)"
    source.write_text(text + "\n")
    data = json.loads(file.read_text()); record = data["supplemental_masses"][0]
    record.update(pdg=13, pdg_token="13", mass_token="13.", source_text=text)
    data["sources"]["model"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="PDG token must occur"):
        study.inputs(task, tmp_path)


def test_interpretation_is_bound_to_exact_parent_and_ordered_daughters(tmp_path):
    task, file, _ = prepare(tmp_path)
    data = json.loads(file.read_text()); data["channel_semantics"][0]["daughter_pdgs"] = [1000022, 13]
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="source parent/daughter"):
        study.run(task, tmp_path, tmp_path / "out")


def test_new_kinematic_context_never_changes_strict_duplicate_source_refusal(tmp_path):
    task, file, source = prepare(tmp_path)
    raw = source.read_bytes() + b"DECAY 25 0\n"
    source.write_bytes(raw); task["source_sha256"] = hashlib.sha256(raw).hexdigest()
    (tmp_path / "complete.json").write_text(json.dumps(model_inputs.make_manifest(raw)))
    data = json.loads(file.read_text()); data["source_sha256"] = task["source_sha256"]
    file.write_text(json.dumps(data))
    result = study.run(task, tmp_path, tmp_path / "out")
    assert result["preflight_disposition"] == "refused" and result["details"]["inventory"] is None
    assert result["details"]["conditional_kinematics"]["status"] == "not_assessed_source_refused"


@pytest.mark.parametrize("field", ["mass_convention", "interpretation", "unit"])
def test_malformed_context_enum_is_configuration_refusal(tmp_path, field):
    task, file, _ = prepare(tmp_path)
    if field == "unit":
        add_supplemental(tmp_path, file)
    data = json.loads(file.read_text())
    target = data if field == "mass_convention" else data["channel_semantics"][0] if field == "interpretation" else data["supplemental_masses"][0]
    target[field] = []
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        study.inputs(task, tmp_path)


def test_source_pinned_long_lived_mass_point_exact_deficit(tmp_path):
    # Literal mass/decay tokens from unchanged longLived.slha SHA9f704...267,
    # lines122/126/200/202. Daughter mass assertion is independently pinned.
    raw = b"BLOCK MASS\n 1000015 3.51750240E+02\n 1000022 3.51664610E+02\nDECAY 1000015 1.00000000E-19\n 0.5000000 4 1000022 13 -14 16\n"
    source = tmp_path / "source-slice.slha"; source.write_bytes(raw)
    complete = tmp_path / "complete.json"; complete.write_text(json.dumps(model_inputs.make_manifest(raw)))
    mass_source = tmp_path / "mass-definitions.txt"
    lines = ["mu = Particle(pdg=13, mass=106.*MeV)", "nu_mu = Particle(pdg=14, mass=0.*MeV)", "nu_tau = Particle(pdg=16, mass=0.*MeV)"]
    mass_source.write_text("\n".join(lines) + "\n")
    data = context(raw, line=5, daughters=[1000022, 13, -14, 16]); data["channel_semantics"][0]["parent_pdg"] = 1000015
    data["sources"] = {"native-SM-source": {"path": str(mass_source), "sha256": hashlib.sha256(mass_source.read_bytes()).hexdigest()}}
    data["supplemental_masses"] = [{"pdg": pdg, "pdg_token": str(pdg), "mass_token": token, "unit": "MeV", "source_id": "native-SM-source", "source_line": line, "source_text": lines[line-1]}
        for pdg, token, line in [(13,"106.",1),(14,"0.",2),(16,"0.",3)]]
    file = tmp_path / "kinematics.json"; file.write_text(json.dumps(data))
    task = {"slha_file": str(source), "source_sha256": data["source_sha256"], "completeness_file": str(complete), "kinematics_file": str(file)}
    row = study.run(task, tmp_path, tmp_path / "out")["details"]["conditional_kinematics"]["channels"][0]
    assert Fraction(row["daughter_mass_sum_GeV_exact"]) == Fraction("351.770610")
    assert Fraction(row["mass_slack_GeV_exact"]) == Fraction("-.020370")
    assert row["status"] == "on_shell_necessary_condition_violated"
