"""Source-bound model bookkeeping, with physical scope explicitly unresolved."""
from copy import deepcopy
from fractions import Fraction
import hashlib

import pytest

from ravel.physics import model_inputs as models


def card(width="1D-14", branching="1.0", *, daughters="1000022 1 -1"):
    return ("BLOCK MASS\n 1000021 1200\n 1000022 -100\n"
            f"DECAY 1000021 {width}\n {branching} 3 {daughters}\n"
            "XSECTION 13000 2212 2212 2 1000021 1000021\n 0 0 0 0 0 0 1.2E-3 test\n").encode()


def audit(raw, *, entries=None):
    return models.audit_slha_bytes(raw, source_name="source.slha", expected_sha256=hashlib.sha256(raw).hexdigest(),
                                  completeness_manifest=models.make_manifest(raw, entries))


def test_exact_source_units_lifetime_and_unresolved_channel_completeness():
    raw = card(); result = audit(raw)
    decay = result["decays"][0]
    assert result["source"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["units"] == {"mass": "GeV", "total_width": "GeV", "branching_fraction": "dimensionless"}
    assert Fraction(decay["total_width_GeV_exact"]) == Fraction(1, 10**14)
    assert Fraction(decay["lifetime"]["proper_ctau_mm_exact"]) == Fraction("19.73269804")
    assert decay["channel_completeness"] == "unresolved_completeness_unknown"
    assert {row["pdg"]: row for row in result["masses"]}[1000022]["sign_interpretation"] == "preserved_uninterpreted"
    assert result["mass_pdgs_without_decay_record"] == [1000022]
    assert "xsection" in result["opaque_blocks"]
    assert result["execution_authorized"] is result["physics_validated"] is False


def test_zero_width_is_stable_by_card_without_imputing_missing_decays():
    raw = b"BLOCK MASS\n 1000022 100\n 1000021 900\nDECAY 1000022 0\n"
    result = audit(raw)
    assert result["decays"][0]["lifetime"]["status"] == "stable_by_card"
    assert result["decays"][0]["lifetime"]["proper_ctau_mm"] is None
    assert result["mass_pdgs_without_decay_record"] == [1000021]


def test_complete_declaration_preserves_evidence_but_does_not_certify_model():
    raw = card()
    entry = models.make_completeness_entry("complete", source_ref="explicit supplied-channel scope",
                                           evidence_text="This fixture declares its one listed channel complete.")
    result = audit(raw, entries={"1000021": entry})
    assert result["decays"][0]["channel_completeness"] == "complete_br_sum_consistent"
    assert result["decays"][0]["completeness_declaration"] == entry
    assert result["physics_validated"] is False


def test_incomplete_partial_list_stays_unresolved_and_complete_partial_list_refuses():
    raw = card(branching="0.8")
    entry = models.make_completeness_entry("incomplete", source_ref="declared partial scope", evidence_text="Partial list.")
    assert audit(raw, entries={"1000021": entry})["decays"][0]["channel_completeness"] == "unresolved_explicitly_incomplete"
    entry = models.make_completeness_entry("complete", source_ref="declared complete scope", evidence_text="Complete list.")
    with pytest.raises(ValueError, match="BR sum"):
        audit(raw, entries={"1000021": entry})


@pytest.mark.parametrize("source", [card(width="-1"), card(branching="-0.2"), card(branching="1.1"),
                                   card().replace(b"1.0 3", b"1.0 2"),
                                   card() + b"DECAY 1000021 0\n",
                                   card().replace(b"XSECTION", b" 1.0 3 -1 1 1000022\nXSECTION"),
                                   card(width="NaN"), card(width="1e999"),
                                   b"BLOCK MASS\n0 1\n"])
def test_malformed_or_ambiguous_card_is_refused_without_overwriting(source):
    original = bytes(source)
    with pytest.raises(ValueError): audit(source)
    assert source == original


def test_source_hash_manifest_hash_and_declaration_integrity_are_external_obligations():
    raw = card(); manifest = models.make_manifest(raw)
    with pytest.raises(ValueError, match="SHA256"):
        models.audit_slha_bytes(raw, source_name="source.slha", expected_sha256="a" * 64, completeness_manifest=manifest)
    bad = deepcopy(manifest); bad["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="different SLHA"):
        models.audit_slha_bytes(raw, source_name="source.slha", expected_sha256=hashlib.sha256(raw).hexdigest(), completeness_manifest=bad)
    bad = models.make_manifest(raw, {"1000021": models.make_completeness_entry("complete", source_ref="source", evidence_text="complete")})
    bad["channel_completeness"]["1000021"]["evidence_text"] = "different"
    with pytest.raises(ValueError, match="evidence hash"):
        models.audit_slha_bytes(raw, source_name="source.slha", expected_sha256=hashlib.sha256(raw).hexdigest(), completeness_manifest=bad)


def test_no_generic_threshold_or_missing_daughter_mass_rule_is_invented():
    raw = card(daughters="1000022 9999998 9999999")
    assert audit(raw)["checks_passed"] is True
    assert audit(raw)["physics_validated"] is False


def test_file_reader_is_bounded_and_preserves_original(tmp_path):
    source = tmp_path / "card.slha"; raw = card(); source.write_bytes(raw)
    result = models.audit_slha_file(source, expected_sha256=hashlib.sha256(raw).hexdigest(), completeness_manifest=models.make_manifest(raw))
    assert result["source"]["bytes_read_only"] and source.read_bytes() == raw
    link = tmp_path / "link.slha"; link.symlink_to(source)
    with pytest.raises(ValueError, match="symlink"):
        models.audit_slha_file(link, expected_sha256=hashlib.sha256(raw).hexdigest(), completeness_manifest=models.make_manifest(raw))
