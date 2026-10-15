"""Synthetic refusal and construction tests for Standard-Model reference inputs."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3

from jsonschema import Draft202012Validator
import pytest

from ravel import analysis_catalog
from ravel.setup import manifest as manifest
from ravel.validation import constants_manifest
from ravel.validation import sm_reference_data
from ravel.workflow import analysis_catalog_build as catalog_builder
from synthetic_catalog import RIVET, checkout

ROOT = Path(__file__).resolve().parents[2]


def _pdg_builder():
    path = ROOT / "scripts/setup/build_pdg_subset.py"
    spec = importlib.util.spec_from_file_location("build_pdg_subset", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sm_pdf_set_builder():
    path = ROOT / "scripts/setup/build_sm_pdf_sets.py"
    spec = importlib.util.spec_from_file_location("build_sm_pdf_sets", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_fake_pdg_database(path: Path, rows):
    """``rows``: (identifier, description, unit, in summary table, value, error) per database row."""
    database = sqlite3.connect(path)
    database.executescript(
        """
        create table pdginfo (name text, value text);
        create table pdgid (pdgid text, description text);
        create table pdgdata (
          pdgid text, value_type text, value real, error_positive real,
          error_negative real, unit_text text, edition text,
          confidence_level real, in_summary_table integer
        );
        """
    )
    database.executemany(
        "insert into pdginfo values (?, ?)",
        [("edition", "2026"), ("data_release_timestamp", "2099-01-01"),
         ("citation", "synthetic reference"), ("license", "CC BY 4.0"),
         ("schema_version", "1")],
    )
    for identifier, description, unit, summary, value, error in rows:
        database.execute("insert into pdgid values (?, ?)", (identifier, description))
        database.execute(
            "insert into pdgdata values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (identifier, "V", value, error, error, unit, "2026", None, int(summary)),
        )
    database.commit()
    database.close()


def _fake_pdg_rows(builder):
    """One synthetic row per declared identifier: dimensioned summary rows, dimensionless
    electroweak rows, and decoys whose descriptions read like the wanted quantities."""
    rows = [(identifier, f"synthetic {key}", "GeV", True, float(index), 0.1)
            for index, (key, identifier) in enumerate(builder.QUANTITIES, start=1)]
    rows += [(identifier, f"synthetic {key}", "", summary, 0.25 + index / 100, 0.01)
             for index, (key, identifier, summary) in enumerate(builder.EW_QUANTITIES, start=1)]
    rows += [("DECOY1", "fermion coupling", "", True, 9.0, 0.1),
             ("DECOY2", "synthetic z_pole.r_b", "", True, 9.0, 0.1)]
    return rows


def _pdf_pins():
    return {
        "schema_version": 1,
        "kind": "ravel-sm-pdf-pins",
        "sets": [{"name": name, "lhaid": 900000 + index, "size": index,
                  "sha256": f"{index:064x}", "used_for": "synthetic use"}
                 for index, name in enumerate(manifest.SM_PDF_SET_NAMES, start=1)],
    }


def _pdf_catalogue():
    return {"schema_version": 1, "kind": "ravel-lhapdf-sets", "base_url": "https://example.invalid/sets",
            "sets": [{"name": "BASEPDF", "lhaid": 800001, "size": 1, "sha256": "a" * 64,
                      "digest_status": "single-download", "used_for": "synthetic base"}]}


def test_pdg_subset_rejects_rows_without_database_identity_or_edition():
    subset = {
        "schema_version": 1,
        "kind": "ravel-pdg-subset",
        "edition": "2026",
        "quantities": {"typed.by.hand": {"value": 1.0, "unit": "unit"}},
    }
    with pytest.raises(constants_manifest.ConstantsError, match="pdgid|edition"):
        constants_manifest.validate_subset(subset)


def test_pdg_subset_keeps_the_database_unit_of_a_dimensionless_row():
    row = {"pdgid": "SYN001", "edition": "2026", "value": 0.25, "unit": ""}
    subset = {"schema_version": 1, "kind": "ravel-pdg-subset", "edition": "2026", "quantities": {"ratio": row}}
    assert constants_manifest.validate_subset(subset) is subset
    del row["unit"]
    with pytest.raises(constants_manifest.ConstantsError, match="unit"):
        constants_manifest.validate_subset(subset)


def test_pdg_builder_emits_ew_rows_and_source_checksum_from_database(tmp_path):
    builder = _pdg_builder()
    database, wheel, output = tmp_path / "pdg.sqlite", tmp_path / "pdg-2026.0-py3-none-any.whl", tmp_path / "out"
    _write_fake_pdg_database(database, _fake_pdg_rows(builder))
    wheel.write_bytes(b"synthetic wheel")

    ew_output = tmp_path / "ew-inputs.json"
    arguments = ["--sqlite", str(database), "--wheel", str(wheel), "--out", str(output), "--ew-out", str(ew_output)]
    assert builder.main(arguments) is None
    subset = json.loads((output / "pdg-subset.json").read_text())
    source = json.loads((output / "SOURCE.json").read_text())
    constants_manifest.validate_subset(subset)
    quantities = subset["quantities"]
    assert builder.EW_QUANTITIES
    for key, identifier, _ in builder.EW_QUANTITIES:
        assert quantities[key]["pdgid"] == identifier and quantities[key]["unit"] == ""
    assert all(row["edition"] == "2026" for row in quantities.values())
    assert not {"DECOY1", "DECOY2"} & {row["pdgid"] for row in quantities.values()}
    assert source["subset_sha256"] == hashlib.sha256((output / "pdg-subset.json").read_bytes()).hexdigest()

    bundle = sm_reference_data.validate_ew_inputs(json.loads(ew_output.read_text()))
    assert bundle["symmetrization"] == "max"
    traced = {row["pdgid"]: row for row in quantities.values()}
    for row in [*bundle["inputs"].values(), *bundle["m_w_variants"].values()]:
        assert row["value"] == traced[row["pdgid"]]["value"] and row["unit"] == traced[row["pdgid"]]["unit"]
    assert bundle["inputs"]["z_pole.gamma_z"]["pdgid"] == quantities["z_boson.width"]["pdgid"]

    database = sqlite3.connect(database)
    database.execute("update pdgdata set value = value + 1 where pdgid = ?", (builder.EW_QUANTITIES[-1][1],))
    database.commit()
    database.close()
    builder.main(arguments)
    assert json.loads((output / "SOURCE.json").read_text())["subset_sha256"] != source["subset_sha256"]


def test_pdg_builder_selects_rows_by_identifier_and_table_never_by_description(tmp_path):
    builder = _pdg_builder()
    listing = next(identifier for _, identifier, summary in builder.EW_QUANTITIES if not summary)
    rows = [row for row in _fake_pdg_rows(builder) if row[0] != listing]
    _write_fake_pdg_database(tmp_path / "missing.sqlite", rows)
    with pytest.raises(SystemExit, match=listing):
        builder.build(tmp_path / "missing.sqlite", None)
    # The same identifier present only as a summary-table row is not the declared listing row.
    rows.append((listing, "synthetic listing quantity", "", True, 0.5, 0.01))
    _write_fake_pdg_database(tmp_path / "wrong-table.sqlite", rows)
    with pytest.raises(SystemExit, match=listing):
        builder.build(tmp_path / "wrong-table.sqlite", None)


@pytest.mark.parametrize("value,error", [(None, 0.01), (0.5, None), (0.5, 0.0)])
def test_pdg_builder_refuses_an_ew_input_without_value_or_uncertainty(tmp_path, value, error):
    builder = _pdg_builder()
    target = builder.EW_QUANTITIES[0][1]
    rows = [(row[0], row[1], row[2], row[3], value, error) if row[0] == target else row
            for row in _fake_pdg_rows(builder)]
    _write_fake_pdg_database(tmp_path / "pdg.sqlite", rows)
    _, selected = builder.build(tmp_path / "pdg.sqlite", None)
    with pytest.raises(SystemExit, match=target):
        builder.ew_inputs(selected, "2026")


def test_pdf_set_validator_requires_complete_pin_matched_fields():
    pins = _pdf_pins()
    catalogue = _pdf_catalogue()
    catalogue["sets"] = [{"name": manifest.SM_PDF_SET_NAMES[0], "size": 12, "sha256": "1" * 64,
                          "digest_status": "single-download", "used_for": "synthetic use"}]
    with pytest.raises(manifest.ManifestError, match="LHAID|lhaid"):
        manifest.validate_pdf_sets(catalogue, sm_pins=pins)


@pytest.mark.parametrize("field,value", [
    ("sha256", "f" * 64), ("size", 999), ("lhaid", 1), ("used_for", "typed by hand"),
    ("digest_status", "verified"),
])
def test_pdf_set_row_that_differs_from_its_acquired_pin_is_refused(field, value):
    pins = _pdf_pins()
    catalogue = manifest.append_sm_pdf_sets(_pdf_catalogue(), pins)
    manifest.validate_pdf_sets(catalogue, sm_pins=pins)
    catalogue["sets"][-1][field] = value
    with pytest.raises(manifest.ManifestError, match=manifest.SM_PDF_SET_NAMES[-1]):
        manifest.validate_pdf_sets(catalogue, sm_pins=pins)


@pytest.mark.parametrize("mutate", [
    lambda pins: pins["sets"][0].pop("sha256"),
    lambda pins: pins["sets"][0].update(sha256="z" * 64),
    lambda pins: pins["sets"][0].update(size=0),
    lambda pins: pins["sets"][0].pop("lhaid"),
    lambda pins: pins["sets"].pop(),
    lambda pins: pins["sets"].append("not a row"),
])
def test_pdf_pin_schema_validator_and_builder_refuse_the_same_documents(mutate):
    schema = Draft202012Validator(json.loads((ROOT / "native/setup/sm-pins.schema.json").read_text()))
    builder = _sm_pdf_set_builder()
    pins = _pdf_pins()
    assert not list(schema.iter_errors(pins))
    assert builder.build(_pdf_catalogue(), pins) == manifest.append_sm_pdf_sets(_pdf_catalogue(), pins)
    mutate(pins)
    assert list(schema.iter_errors(pins))
    with pytest.raises(manifest.ManifestError):
        manifest.validate_sm_pdf_pins(pins)
    with pytest.raises(manifest.ManifestError):
        builder.build(_pdf_catalogue(), pins)


def test_pdf_pins_append_all_source_matched_rows_without_rewriting_existing_rows():
    pins = _pdf_pins()
    catalogue = _pdf_catalogue()
    result = manifest.append_sm_pdf_sets(catalogue, pins)
    assert catalogue == _pdf_catalogue()
    assert result["sets"][0] == catalogue["sets"][0]
    assert [row["name"] for row in result["sets"][-10:]] == list(manifest.SM_PDF_SET_NAMES)
    assert all(row["digest_status"] == "single-download" for row in result["sets"][-10:])
    with pytest.raises(manifest.ManifestError, match="already present"):
        manifest.append_sm_pdf_sets(result, pins)


LEPTON_COLLIDER_ROUTINES = {
    "analyses/pluginGEN/ANA_0001_I0001.info": (
        "Name: ANA_0001_I0001\nSummary: synthetic inclusive spectrum\n"
        "Experiment: GENERIC\nCollider: e+ e-\nStatus: VALIDATED\n"
    ),
    "analyses/pluginGEN/ANA_0001_I0001.cc": "class Synthetic {}\n",
    "analyses/pluginGEN/ANA_0002_I0002.info": (
        "Name: ANA_0002_I0002\nSummary: synthetic thrust and event shapes\n"
        "Experiment: GENERIC\nCollider: e+ e-\nStatus: VALIDATED\n"
    ),
    "analyses/pluginGEN/ANA_0002_I0002.cc": "class SyntheticShape {}\n",
}


def test_catalogue_builder_keeps_generic_non_hadron_routine(tmp_path):
    rivet = checkout(tmp_path / "rivet", LEPTON_COLLIDER_ROUTINES)
    catalogue = catalog_builder.build(rivet_root=rivet, retrieved="2099-01-01")
    families = {row["name"]: row["family"] for row in catalogue["entries"]}
    assert families == {"ANA_0001_I0001": "fiducial-measurement", "ANA_0002_I0002": "event-shape"}


def test_every_catalogue_family_has_an_adaptation_packet(tmp_path):
    assert set(analysis_catalog.FAMILY_REQUIREMENTS) == set(analysis_catalog.FAMILIES)
    rivet = checkout(tmp_path / "rivet", LEPTON_COLLIDER_ROUTINES)
    catalogue = catalog_builder.build(rivet_root=rivet, retrieved="2099-01-01")
    for row in catalogue["entries"]:
        packet = analysis_catalog.adaptation_packet(catalogue, row)
        assert packet["compute_authorized"] is False and packet["physics_validated"] is False
        assert len(packet["requirements"]) >= 7


def test_added_routines_leave_existing_catalogue_rows_unchanged(tmp_path):
    before = catalog_builder.build(rivet_root=checkout(tmp_path / "before", RIVET), retrieved="2099-01-01")
    after = catalog_builder.build(rivet_root=checkout(tmp_path / "after", {**RIVET, **LEPTON_COLLIDER_ROUTINES}),
                                  retrieved="2099-01-01")
    rows = {row["id"]: row for row in after["entries"]}
    assert all(rows[row["id"]] == row for row in before["entries"])
    assert set(rows) - {row["id"] for row in before["entries"]} == {"rivet:ANA_0001_I0001", "rivet:ANA_0002_I0002"}


def test_ew_bundle_validates_and_only_pdg_identifiers_select_mw_variants():
    bundle = {
        "schema_version": 1,
        "kind": "ravel-ew-inputs",
        "edition": "2026",
        "symmetrization": "max",
        "inputs": {"ratio": {"pdgid": "SYN001", "value": 0.1, "uncertainty": 0.01, "unit": ""}},
        "m_w_variants": {"SYN002": {"pdgid": "SYN002", "value": 80.0, "uncertainty": 0.1, "unit": "GeV"}},
    }
    sm_reference_data.validate_ew_inputs(bundle)
    assert sm_reference_data.select_mw_variant(bundle, "SYN002")["pdgid"] == "SYN002"
    with pytest.raises(KeyError, match="unknown"):
        sm_reference_data.select_mw_variant(bundle, "named-variant")
    for mutate in (lambda b: b.pop("symmetrization"),
                   lambda b: b["inputs"]["ratio"].pop("pdgid"),
                   lambda b: b["m_w_variants"].update(label=b["m_w_variants"].pop("SYN002"))):
        broken = copy.deepcopy(bundle)
        mutate(broken)
        with pytest.raises(ValueError):
            sm_reference_data.validate_ew_inputs(broken)
