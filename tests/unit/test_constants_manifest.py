"""Pinned PDG subset and the uncited-constant check."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ravel.validation import constants_manifest as cm

REFERENCE = Path(cm.REFERENCE)


def test_subset_is_pinned_with_edition_and_checksum():
    source = cm.load_source()
    assert source["edition"] == "2026" and source["license"] == "CC BY 4.0"
    assert source["subset_sha256"] == hashlib.sha256((REFERENCE / "pdg-subset.json").read_bytes()).hexdigest()
    assert len(source["origin"]["wheel_sha256"]) == 64 and len(source["origin"]["database_sha256"]) == 64
    subset = cm.load_subset()
    assert subset["edition"] == "2026" and len(subset["quantities"]) == 17
    z = subset["quantities"]["z_boson.mass"]
    assert z["pdgid"] == "S044M" and z["unit"] == "GeV" and z["edition"] == "2026"


def test_a_changed_subset_is_refused(tmp_path, monkeypatch):
    for name in ("pdg-subset.json", "SOURCE.json"):
        (tmp_path / name).write_bytes((REFERENCE / name).read_bytes())
    (tmp_path / "pdg-subset.json").write_text(
        (tmp_path / "pdg-subset.json").read_text().replace('"edition": "2026"', '"edition": "2025"', 1))
    monkeypatch.setattr(cm, "REFERENCE", tmp_path)
    with pytest.raises(cm.ConstantsError, match="checksum"):
        cm.load_subset()


def test_uncited_physics_critical_numbers_are_named_by_field_path():
    document = {"particles": [{"name": "a", "mass": 1.0, "mass_source": "doi:10.0/x"},
                              {"name": "b", "mass": 2.0, "width": 0.1, "source": "supplied card"},
                              {"name": "c", "mass": 3.0}],
                "analysis": {"luminosity_fb": 139.0, "cross_section": {"value": 1.0, "k_factor": 1.2, "citation": ""}}}
    found = {f["field_path"] for f in cm.check_document(document)}
    assert found == {"particles[2].mass", "analysis.luminosity_fb", "analysis.cross_section.k_factor"}


def test_booleans_and_non_critical_keys_are_not_flagged():
    assert cm.check_document({"mass_known": True, "count": 3, "label": "mass", "seed": 7}) == []


def test_pdg_cited_numbers_are_compared_with_the_subset():
    z = cm.load_subset()["quantities"]["z_boson.mass"]
    good = {"mass": z["value"] * 1000, "unit": "MeV", "pdg_ref": "S044M"}
    bad = {"mass": 91.5, "unit": "GeV", "pdg_ref": "S044M"}
    assert cm.check_document({"z": good}, pdg=True) == []
    [finding] = cm.check_document({"z": bad}, pdg=True)
    assert finding["field_path"] == "z.mass" and finding["kind"] == "pdg-mismatch" and "S044M" in finding["reason"]


def test_command_line_reports_and_exits_nonzero(tmp_path, capsys):
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"mass": 5.0}))
    assert cm.main([str(doc)]) == 1
    assert "mass" in capsys.readouterr().out
    assert cm.main(["--verify-subset"]) == 0
