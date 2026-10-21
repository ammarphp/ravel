"""Exact region and headline custody at route, scan and delivery boundaries."""
from copy import deepcopy

import pytest

from statistics_records import inert_statistics
from test_p09_statistics import BASE, _check, run  # noqa: F401
from ravel.controller.routes.analysis import statistics
from ravel.controller.sink import checks
from ravel.physics.inference import situations, uncertainty


def result():
    document = deepcopy(BASE)
    document.update(statistics=inert_statistics(), per_sr={"SR": {"n": 100.0, "b": 100.0}})
    document["uncertainty"] = uncertainty.for_limits(document)
    return document


@pytest.mark.parametrize("boundary", ["route", "scan", "sink", "scan-sink"])
@pytest.mark.parametrize("mutation", ["rename", "missing", "count", "uncertainty", "expected", "status", "band-status", "omitted"])
def test_each_boundary_binds_the_complete_result(run, boundary, mutation):
    document = result()
    if mutation == "rename":
        document["per_sr"]["other"] = document["per_sr"].pop("SR")
    elif mutation == "missing":
        document["per_sr"]["other"] = {"n": 100.0, "b": 100.0}
    elif mutation == "count":
        document["per_sr"]["SR"]["n"] = None
    elif mutation == "uncertainty":
        document["uncertainty"]["values"]["observed"] = 7.0
    elif mutation == "expected":
        document["uncertainty"]["values"]["expected_+1sigma"] = 7.0
    elif mutation == "status":
        document["uncertainty"]["values"]["observed_status"] = "above_scan"
    elif mutation == "band-status":
        document["uncertainty"]["values"]["expected_+1sigma_status"] = "above_scan"
    else:
        document["uncertainty"]["values"].pop("expected_median")
    if boundary == "route":
        errors = _check(run, document)
    elif boundary == "scan":
        errors = statistics.errors(document, {"id": "scan.point.one"}, row="P04")
    else:
        findings = checks.Findings()
        checks._statistics_validity(findings, "result.json",
            {"points": [{"tag": "one", **document}]} if boundary == "scan-sink" else document)
        errors = findings.refusals
    code = "statistics_record_invalid" if mutation in {"rename", "missing", "count"} else "uncertainty_unstated"
    assert code in {error["code"] for error in errors}, errors


def test_matching_values_reach_both_boundaries(run):
    document = result()
    assert _check(run, document) == []
    findings = checks.Findings()
    checks._statistics_validity(findings, "result.json", document)
    assert findings.refusals == []
    assert uncertainty.document_errors(document) == []


def test_multibin_region_uses_every_bin_and_rejects_duplicate_identity():
    facts = situations.make_facts(deliverables=["exclusion"], bins=[
        {"channel": "shape", "bin": 0, "observed": 40., "background": 40.},
        {"channel": "shape", "bin": 1, "observed": 60., "background": 60.}])
    block = {"facts": facts}
    assert situations.result_facts_errors(block, {"shape": 100.}) == []
    assert situations.result_facts_errors(block, {"shape": 60.})
    facts["bins"][1]["bin"] = 0
    assert situations.result_facts_errors(block, {"shape": 100.})


def test_document_validator_binds_uncertainty_values():
    document = result()
    document["uncertainty"]["values"]["observed"] = 8.
    assert uncertainty.document_errors(document)
