"""A scan carries each point's statistics record and uncertainty statement from harvest to the assembly.

The harvest recomputes every point's record: one that does not recompute, or a held outcome, makes
the point invalid (an explicit hole), and a result pack's summary is re-derived from the exclusion
record it is bound to. The assembly lists each qualification label with the points it applies to.
Synthetic records only.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from statistics_records import inert_statistics, inert_uncertainty
from test_limit_transport import exclusion, point_dir

from ravel.limits import attach_limits, bind_source
from ravel.physics.inference import situations
from ravel.workflow import scan_orchestrator as scan


def _qualified():
    facts = situations.make_facts(deliverables=["exclusion"], model_origin="counting", bins=[
        {"channel": "SR", "bin": 0, "observed": 2., "background": 1.5, "background_uncertainty": .5}])
    availability = {"toy-cls": {"available": False, "reason": "budget: fits limit"}}
    evidence = {"limits": {"observed": "resolved", "median": "resolved"},
                "budget_refusals": [{"method": "toy-cls", "status": "not_run", "reason": "budget"}]}
    return situations.record(facts, evidence, availability=availability,
                             decision=situations.decide(situations.assess(facts, availability=availability)))


def _held():
    facts = situations.make_facts(deliverables=["exclusion"], model_origin="constructed",
                                  bins=[{"channel": "SR", "bin": 0, "observed": 100., "background": 100.}])
    return situations.record(facts, {"limits": {"observed": "resolved", "median": "resolved"}})


def test_a_point_without_records_harvests_as_before(tmp_path):
    harvested = scan.harvest_point(point_dir(tmp_path, exclusion()))
    assert "statistics" not in harvested and "uncertainty" not in harvested


def test_the_harvest_carries_the_recomputed_record_and_statement(tmp_path):
    block, statement = _qualified(), inert_uncertainty(document=exclusion())
    harvested = scan.harvest_point(point_dir(tmp_path, {**exclusion(), "statistics": block, "uncertainty": statement}))
    assert harvested["statistics"] == block and harvested["uncertainty"] == statement


@pytest.mark.parametrize("make,match", [
    (_held, "held"),
    (lambda: {**_qualified(), "validity": inert_statistics()["validity"]}, "does not recompute"),
])
def test_a_held_or_inconsistent_point_is_never_harvested(tmp_path, make, match):
    mp = point_dir(tmp_path, {**exclusion(), "statistics": make(), "uncertainty": inert_uncertainty(document=exclusion())})
    with pytest.raises(ValueError, match=match):
        scan.harvest_point(mp)
    assert scan.point_status(mp) == ("failed", None)


def test_a_result_pack_summary_is_rederived_from_its_bound_exclusion(tmp_path):
    block = _qualified()
    original = attach_limits({**exclusion(), "statistics": block, "uncertainty": inert_uncertainty(document=exclusion())})
    mp = point_dir(tmp_path, original)
    summary = {"outcome": "qualified", "labels": situations.labels(block), "catalogue_sha256": block["catalogue_sha256"]}
    result = {**deepcopy(original), "statistics": summary}
    bind_source(result, tmp_path, "output/exclusion.json")
    (tmp_path / "result.json").write_text(json.dumps(result))
    harvested = scan.harvest_point(mp)
    assert harvested["source"] == "result.json" and harvested["statistics"] == block
    result["statistics"] = {**summary, "outcome": "valid", "labels": []}
    (tmp_path / "result.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="summary differs"):
        scan.harvest_point(mp)


def test_the_assembly_lists_each_qualification_with_its_points(tmp_path, monkeypatch):
    points = []
    for tag, block in (("p1", _qualified()), ("p2", inert_statistics())):
        folder = tmp_path / tag
        folder.mkdir()
        points.append({**point_dir(folder, {**exclusion(), "statistics": block, "uncertainty": inert_uncertainty(document=exclusion())}),
                       "tag": tag})
    manifest = {"name": "synthetic", "points": points, "n_points": 2}
    monkeypatch.setattr(scan, "load_manifest", lambda _: (str(tmp_path), manifest))
    path = tmp_path / "scan.json"
    scan.cmd_assemble(SimpleNamespace(scandir=str(tmp_path), out=str(path), nlo_renorm=None))
    document = json.loads(path.read_text())
    assert [row["statistics"]["validity"]["outcome"] for row in document["points"]] == ["qualified", "valid"]
    assert all(row["uncertainty"] == inert_uncertainty(document=exclusion()) for row in document["points"])
    assert document["limitations"] == [{"key": "statistics-qualified", "note": label, "points": ["p1"]}
                                       for label in situations.labels(_qualified())]


@pytest.mark.parametrize("key,value", [
    ("observed", .9), ("expected_median", 9.),
    ("observed_status", "above_scan"), ("expected_median_status", "above_scan"),
])
def test_harvest_refuses_uncertainty_values_or_statuses_from_another_limit(tmp_path, key, value):
    document = exclusion()
    document.update(statistics=inert_statistics(), uncertainty=inert_uncertainty(document=document))
    document["uncertainty"]["values"][key] = value
    mp = point_dir(tmp_path, document)
    with pytest.raises(ValueError, match="uncertainty"):
        scan.harvest_point(mp)
    assert scan.point_status(mp) == ("failed", None)


def test_harvest_refuses_a_delivered_region_missing_from_statistics_facts(tmp_path):
    document = exclusion()
    document.update(statistics=inert_statistics(), uncertainty=inert_uncertainty(document=document),
                    per_sr={"SR": {"n": 100.}, "unassessed": {"n": 10.}})
    mp = point_dir(tmp_path, document)
    with pytest.raises(ValueError, match="unassessed"):
        scan.harvest_point(mp)
    assert scan.point_status(mp) == ("failed", None)
