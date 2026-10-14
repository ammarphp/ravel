import hashlib
import json
from pathlib import Path

import pytest

from ravel.physics import model_input_study as study, model_inputs


def prepare(tmp_path, text, entries=None):
    raw = text.encode()
    source = tmp_path / "supplied.slha"
    source.write_bytes(raw)
    declaration = tmp_path / "completeness.json"
    declaration.write_text(json.dumps(model_inputs.make_manifest(raw, entries)))
    return {"slha_file": source.name, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "completeness_file": declaration.name}, source, declaration


CARD = "BLOCK MASS\n 25 125\n 1000022 20\nDECAY 25 0.004\n 1.0 2 1000022 1000022\n"


def test_unknown_completeness_is_delivered_but_never_physical_acceptance(tmp_path):
    task, source, declaration = prepare(tmp_path, CARD)
    before = source.read_bytes(), declaration.read_bytes()
    assert study.inputs(task, tmp_path) == sorted([source, declaration])
    result = study.run(task, tmp_path, tmp_path / "output")
    assert result["status"] == "passed" and result["preflight_disposition"] == "static_inventory"
    assert result["details"]["diagnostic_delivery_complete"]
    assert result["details"]["inventory"]["mass_pdgs_without_decay_record"] == [1000022]
    assert {f["id"] for f in result["details"]["findings"]} == {"channel-completeness", "missing-decay-record"}
    assert result["execution_authorized"] is result["physics_validated"] is False
    assert result["downstream_policy"]["source_findings_do_not_set_workflow_approval"]
    assert (source.read_bytes(), declaration.read_bytes()) == before


def test_conflicting_headers_are_retained_as_source_findings_not_policy(tmp_path):
    task, source, _ = prepare(tmp_path, CARD + "DECAY 25 0\nDECAY 1000022 0\nDECAY 1000022 1e-14\n")
    result = study.run(task, tmp_path, tmp_path / "output")
    assert result["status"] == "passed"  # delivered diagnosis, not accepted source
    assert result["preflight_disposition"] == "refused"
    assert result["details"]["inventory"] is None
    assert result["details"]["findings"][0]["classification"] == "source_declaration_anomaly"
    census = result["details"]["duplicate_decay_declarations"]
    assert not census["truncated"] and census["observed_header_count"] == 4
    assert [r["pdg"] for r in census["groups"]] == [25, 1000022]
    assert all(r["conflicting_supplied_widths"] for r in census["groups"])
    assert not (tmp_path / "output/model-input-inventory.json").exists()
    assert source.read_text().endswith("DECAY 1000022 1e-14\n")


def test_negative_br_is_consumer_scope_refusal_not_invalid_physics(tmp_path):
    task, _, _ = prepare(tmp_path, CARD.replace("1.0 2", "-1.0 2"))
    result = study.run(task, tmp_path, tmp_path / "output")
    assert result["preflight_disposition"] == "refused"
    finding = result["details"]["findings"][0]
    assert finding["classification"] == "unsupported_consumer_semantics"
    assert finding["physics_conclusion"] == "unresolved"
    assert result["physics_validated"] is False


def test_signed_mass_and_apparent_offshell_channel_are_preserved(tmp_path):
    # Daughter source masses exceed parent mass. No on-shell physical premise
    # was supplied, so this cannot trigger a universal threshold rejection.
    task, _, _ = prepare(tmp_path, CARD.replace("1000022 20", "1000022 -200"))
    result = study.run(task, tmp_path, tmp_path / "output")
    assert result["preflight_disposition"] == "static_inventory"
    assert any(f["id"] == "signed-mass-convention" for f in result["details"]["findings"])
    inventory = result["details"]["inventory"]
    assert inventory["masses"][1]["mass_GeV_exact"] == "-200/1"


def test_complete_declaration_is_bookkeeping_not_independent_width(tmp_path):
    entry = model_inputs.make_completeness_entry("complete", source_ref="fixture-source",
                                               evidence_text="declared complete for this fixture")
    task, _, _ = prepare(tmp_path, CARD, {"25": entry})
    result = study.run(task, tmp_path, tmp_path / "output")
    row = result["details"]["inventory"]["decays"][0]
    assert row["channel_completeness"] == "complete_br_sum_consistent"
    assert row["channels"][0]["implied_partial_width_GeV_exact"] == "1/250"
    assert result["physics_validated"] is False


def test_inconsistent_completeness_is_delivered_as_declared_source_conflict(tmp_path):
    entry = model_inputs.make_completeness_entry("complete", source_ref="fixture-source", evidence_text="complete")
    task, _, _ = prepare(tmp_path, CARD.replace("1.0 2", ".5 2"), {"25": entry})
    result = study.run(task, tmp_path, tmp_path / "output")
    assert result["status"] == "passed" and result["preflight_disposition"] == "refused"
    assert result["details"]["findings"][0]["classification"] == "completeness_declaration_inconsistent"


def test_task_hash_drift_is_hard_intake_failure(tmp_path):
    task, source, _ = prepare(tmp_path, CARD)
    source.write_text(CARD + "# drift\n")
    with pytest.raises(ValueError, match="external task source_sha256"):
        study.run(task, tmp_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("bad", ['{"schema_version":1,"schema_version":1}', '{"v":NaN}', '{}'])
def test_configuration_errors_do_not_become_source_findings(tmp_path, bad):
    task, _, declaration = prepare(tmp_path, CARD)
    declaration.write_text(bad)
    with pytest.raises(ValueError):
        study.inputs(task, tmp_path)
    assert not (tmp_path / "output").exists()


def test_absent_decay_declaration_is_configuration_failure(tmp_path):
    entry = model_inputs.make_completeness_entry("complete", source_ref="fixture", evidence_text="complete")
    task, _, _ = prepare(tmp_path, CARD, {"999": entry})
    with pytest.raises(ValueError, match="absent DECAY"):
        study.run(task, tmp_path, tmp_path / "output")


def test_manifest_enforces_utf8_instead_of_json_encoding_autodetection(tmp_path):
    task, _, declaration = prepare(tmp_path, CARD)
    declaration.write_bytes(declaration.read_text().encode("utf-16"))
    with pytest.raises(ValueError, match="strict UTF-8"):
        study.inputs(task, tmp_path)


def test_malformed_headers_are_counted_and_not_claimed_equivalent(tmp_path):
    task, _, _ = prepare(tmp_path, CARD + "DECAY 1000022\n")
    result = study.run(task, tmp_path, tmp_path / "output")
    census = result["details"]["duplicate_decay_declarations"]
    assert census["observed_header_count"] == 2
    assert census["parsed_header_count"] == census["malformed_header_count"] == 1
    assert census["declaration_equivalence_assessed"] is False


def test_repeated_mass_sections_are_contract_scope_findings(tmp_path):
    task, _, _ = prepare(tmp_path, CARD + "BLOCK MASS Q= 100\n 25 125\n")
    result = study.run(task, tmp_path, tmp_path / "output")
    assert result["preflight_disposition"] == "refused"
    assert result["details"]["findings"][0]["classification"] == "adapter_unsupported_scope"


def test_inputs_under_output_cannot_be_overwritten(tmp_path):
    task, source, declaration = prepare(tmp_path, CARD)
    before = source.read_bytes(), declaration.read_bytes()
    with pytest.raises(ValueError, match="contain or overwrite"):
        study.run(task, tmp_path, tmp_path)
    assert (source.read_bytes(), declaration.read_bytes()) == before


def test_parent_symlink_is_refused(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    task, _, _ = prepare(target, CARD)
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)
    task["slha_file"] = str(link / "supplied.slha")
    task["completeness_file"] = str(target / "completeness.json")
    with pytest.raises(ValueError, match="without symlinks"):
        study.inputs(task, tmp_path)


def test_census_bound_is_explicit_not_a_claim_of_full_inventory(tmp_path):
    lines = ["BLOCK MASS", "25 125"] + [f"DECAY 25 {i}" for i in range(study.MAX_CENSUS_HEADERS + 1)]
    task, _, _ = prepare(tmp_path, "\n".join(lines) + "\n")
    result = study.run(task, tmp_path, tmp_path / "output")
    census = result["details"]["duplicate_decay_declarations"]
    assert census["truncated"] and census["observed_header_count"] == study.MAX_CENSUS_HEADERS + 1
    assert len(census["groups"][0]["declarations"]) == study.MAX_CENSUS_HEADERS
