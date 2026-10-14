"""Routine lookup distinguishes an unchecked source tree from a checked one with no match."""
import json

import pytest

from ravel import analysis_catalog
from ravel.analysis_catalog import load_catalog
from ravel.workflow import routine_fetch
from synthetic_catalog import build


@pytest.fixture(autouse=True)
def local_catalogue(tmp_path_factory, monkeypatch):
    path, _ = build(tmp_path_factory.mktemp('upstream'))
    monkeypatch.setenv(analysis_catalog.CATALOG_ENV, str(path))


def _entries(framework):
    return [r for r in load_catalog()["entries"] if r["framework"] == framework]


def test_missing_source_trees_are_reported_as_not_checked(tmp_path):
    row = next(r for r in _entries("rivet") if r["inspire_id"])
    found = routine_fetch.find_routines("ins" + row["inspire_id"],
                                        rivet_share=tmp_path / "absent-rivet",
                                        sa_src=tmp_path / "absent-sa")
    assert found["rivet"]["checked"] is False and found["rivet"]["matches"] == []
    assert "absent-rivet" in found["rivet"]["reason"]
    assert found["simpleanalysis"]["checked"] is False
    ids = [m["id"] for m in found["catalog"]["matches"]]
    assert row["id"] in ids


def test_catalogue_resolves_an_experiment_prefixed_analysis_code(tmp_path):
    row = next(r for r in _entries("simpleanalysis") if r["analysis_ids"])
    query = "XYZ-" + row["analysis_ids"][0]
    found = routine_fetch.find_routines(query, rivet_share=tmp_path / "none",
                                        sa_src=tmp_path / "none")
    assert row["id"] in [m["id"] for m in found["catalog"]["matches"]]


def test_catalogue_matches_title_keywords(tmp_path):
    row = _entries("rivet")[0]
    word = max(row["title"].split(), key=len)
    found = routine_fetch.find_routines(word, rivet_share=tmp_path / "none",
                                        sa_src=tmp_path / "none")
    assert row["id"] in [m["id"] for m in found["catalog"]["matches"]]


def test_local_trees_are_scanned_when_present(tmp_path):
    share = tmp_path / "Rivet"
    share.mkdir()
    (share / "XYZ_9010_I0010.info").write_text(
        "Name: XYZ_9010_I0010\nStatus: VALIDATED\nReferences:\n- 'XYZ-FAKE-9010-02'\n")
    (share / "XYZ_9011_I10010.info").write_text("Name: XYZ_9011_I10010\nStatus: VALIDATED\n")
    src = tmp_path / "sa" / "SimpleAnalysisCodes" / "src"
    src.mkdir(parents=True)
    (src / "ANA-FAKE-9010-02.cxx").write_text("DefineAnalysis(FakeSearchC)\n")
    found = routine_fetch.find_routines("ins0010", rivet_share=share, sa_src=tmp_path / "sa")
    assert found["rivet"]["checked"] is True
    assert [h["routine"] for h in found["rivet"]["matches"]] == ["XYZ_9010_I0010"]
    assert found["rivet"]["matches"][0]["codes"] == ["XYZ-FAKE-9010-02"]
    found = routine_fetch.find_routines("XYZ-FAKE-9010-02", rivet_share=share,
                                        sa_src=tmp_path / "sa")
    assert found["simpleanalysis"]["checked"] is True
    assert found["simpleanalysis"]["matches"][0]["names"] == ["FakeSearchC"]


def test_text_report_never_claims_zero_matches_for_an_unchecked_tree(tmp_path, capsys):
    row = next(r for r in _entries("rivet") if r["inspire_id"])
    routine_fetch.main(["--query", "ins" + row["inspire_id"],
                        "--rivet-share", str(tmp_path / "x"), "--sa-src", str(tmp_path / "y")])
    out = capsys.readouterr().out
    assert "0 match" not in out
    assert "not checked" in out.lower()
    assert row["name"] in out


def test_json_report(tmp_path, capsys):
    routine_fetch.main(["--query", "zzzz-no-such-analysis", "--json",
                        "--rivet-share", str(tmp_path / "x"), "--sa-src", str(tmp_path / "y")])
    doc = json.loads(capsys.readouterr().out)
    assert doc["query"] == "zzzz-no-such-analysis"
    assert doc["catalog"]["checked"] is True and doc["catalog"]["matches"] == []
