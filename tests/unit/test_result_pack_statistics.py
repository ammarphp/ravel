"""The legacy result pack carries the limit's uncertainty statement and recomputes its statistics record.

A held or non-recomputing record refuses the pack; a qualified one packs with each label as a keyed
``statistics-qualified`` limitation; an exclusion record written before these records existed packs as
before. Synthetic records only.
"""
from copy import deepcopy
import json

import pytest

from statistics_records import inert_uncertainty
from test_host_governance import _packable

from ravel.physics.inference import situations


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    for key in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "RAVEL_SESSION_ID", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(key, raising=False)


def _run(tmp_path, *, high_counts=False, **blocks):
    rd = tmp_path / "run"
    rd.mkdir()
    _packable(rd)
    path = rd / "outputs/pyhf_exclusion/exclusion.json"
    document = {**json.loads(path.read_text()), **blocks}
    if high_counts:
        region = {"name": "SR1", "n": 100., "b": 100., "db": .5, "s": 1.}
        (rd / "outputs/sr_yields.json").write_text(json.dumps([region]))
        document["per_sr"] = {"SR1": {k: v for k, v in region.items() if k != "name"}}
    if "statistics" in blocks and "uncertainty" not in blocks:
        document["uncertainty"] = inert_uncertainty(document=document)
    path.write_text(json.dumps(document))
    return rd


def _pack(rd):
    from ravel.workflow import result_pack
    argv = ["--rundir", str(rd), "--stat-mode", "best-sr-counting", "--detector-mode", "particle-level",
            "--normalization-ledger", "outputs/normalization-ledger.json"]
    assert result_pack.main(argv) == 0
    return json.loads((rd / "result.json").read_text())


def _refused(rd, match):
    from ravel.workflow import result_pack
    argv = ["--rundir", str(rd), "--stat-mode", "best-sr-counting", "--detector-mode", "particle-level",
            "--normalization-ledger", "outputs/normalization-ledger.json"]
    with pytest.raises(result_pack.PackError, match=match):
        result_pack.main(argv)
    assert not (rd / "result.json").exists()


def _small_count(*, refused=True, observed=3.0):
    """The packed region's own counts with a toy budget refusal: a qualified record."""
    facts = situations.make_facts(deliverables=["exclusion"], model_origin="counting", bins=[
        {"channel": "SR1", "bin": 0, "observed": observed, "background": 2.5, "background_uncertainty": .5}])
    availability = {"toy-cls": {"available": False, "reason": "budget: fits limit"}} if refused else None
    evidence = {"limits": {"observed": "resolved", "median": "resolved"}}
    if refused:
        evidence["budget_refusals"] = [{"method": "toy-cls", "status": "not_run", "reason": "budget"}]
    return situations.record(facts, evidence, availability=availability,
                             decision=situations.decide(situations.assess(facts, availability=availability)))


def test_a_record_written_before_statistics_records_packs_as_before(tmp_path, isolated):
    result = _pack(_run(tmp_path))
    assert "statistics" not in result and "uncertainty" not in result
    assert not any(row.get("key") == "statistics-qualified" for row in result["limitations"])


def test_a_valid_record_and_its_statement_travel_with_the_headline(tmp_path, isolated):
    facts = situations.make_facts(deliverables=["exclusion"], bins=[
        {"channel": "SR1", "bin": 0, "observed": 100., "background": 100., "background_uncertainty": .5}])
    block = situations.record(facts, {})
    rd = _run(tmp_path, statistics=block, high_counts=True)
    statement = json.loads((rd / "outputs/pyhf_exclusion/exclusion.json").read_text())["uncertainty"]
    result = _pack(rd)
    assert result["uncertainty"] == statement
    assert result["uncertainty"]["not_included"]
    assert result["statistics"]["outcome"] == "valid" and result["statistics"]["labels"] == []
    assert result["statistics"]["catalogue_sha256"] == situations.catalogue_sha256()
    assert not any(row.get("key") == "statistics-qualified" for row in result["limitations"])


def test_a_qualified_record_packs_with_every_label_as_a_limitation(tmp_path, isolated):
    block = _small_count()
    assert block["validity"]["outcome"] == "qualified"
    result = _pack(_run(tmp_path, statistics=block))
    assert result["statistics"]["outcome"] == "qualified"
    assert result["statistics"]["choices"] == [{"situation": "low-counts", "method": "asymptotic-cls",
                                                "origin": "fallback"}]
    rows = [row["note"] for row in result["limitations"] if row.get("key") == "statistics-qualified"]
    assert rows == situations.labels(block) and rows


def test_a_held_record_refuses_the_pack(tmp_path, isolated):
    # Assess the packed region so the held outcome is the isolated refusal.
    facts = situations.make_facts(deliverables=["exclusion"], model_origin="constructed",
                                  bins=[{"channel": "SR1", "bin": 0, "observed": 3., "background": 2.5,
                                         "background_uncertainty": .5}])
    block = situations.record(facts, {"limits": {"observed": "resolved", "median": "resolved"}})
    assert block["validity"]["outcome"] == "held"
    _refused(_run(tmp_path, statistics=block), "held")


@pytest.mark.parametrize("tamper,match", [
    (lambda b: b["validity"].update(outcome="valid", qualifications=[]), "does not recompute"),
    (lambda b: b["evidence"].pop("budget_refusals"), "no budget refusal"),
    (lambda b: b["facts"]["bins"][0].update(observed=30.0), "assessment does not follow"),
])
def test_a_record_that_does_not_recompute_refuses_the_pack(tmp_path, isolated, tamper, match):
    block = deepcopy(_small_count())
    tamper(block)
    _refused(_run(tmp_path, statistics=block), match)


def test_an_empty_description_is_not_an_assessment(tmp_path, isolated):
    block = situations.record(situations.make_facts(deliverables=["exclusion"]), {})
    assert situations.audit(block) == []
    _refused(_run(tmp_path, statistics=block), "no main-bin counts")


def test_facts_must_assess_the_packed_region_counts(tmp_path, isolated):
    block = _small_count(observed=4.0)  # the packed region SR1 has n = 3
    _refused(_run(tmp_path, statistics=block), "region SR1")


def test_an_invalid_uncertainty_statement_refuses_the_pack(tmp_path, isolated):
    rd = _run(tmp_path, statistics=_small_count())
    path = rd / "outputs/pyhf_exclusion/exclusion.json"
    document = json.loads(path.read_text())
    assert situations.result_document_errors(document["statistics"], document) == []
    statement = document["uncertainty"]
    statement["components"] = [c for c in statement["components"] if c["kind"] != "method"]
    path.write_text(json.dumps(document))
    _refused(rd, "uncertainty statement")
