"""Correlation sensitivity carries the finite evaluated domain into delivery."""
import math
from copy import deepcopy

import pytest

from ravel.physics.inference import constructed, situations, uncertainty
from test_statistics_models import run_exclusion, source_registry


def test_interior_covariance_can_give_a_weaker_limit_than_both_endpoints():
    # For signal (1, 2), V=((a,c),(c,a)), information=(5a-4c)/(a*a-c*c).
    # The Gaussian expected limit is proportional to 1/sqrt(information).
    a = 100.
    width = lambda c: math.sqrt((a * a - c * c) / (5 * a - 4 * c))
    assert width(a / 2) > max(width(0.), width(.999 * a))


def test_real_endpoint_fit_carries_its_domain_and_qualification(tmp_path, monkeypatch):
    document = run_exclusion(tmp_path, monkeypatch, "constructed",
        srs=[dict(name="left", n=100, b=100, db=10, s=10),
             dict(name="right", n=100, b=100, db=10, s=20)],
        registry=source_registry("unknown"))
    bracket = document["correlation_bracket"]
    assert bracket["domain"] == {
        "kind": "finite-assignments", "coverage": "endpoint-sensitivity",
        "assignments": ["correlated", "per-region"], "sources": ["normalization"],
        "continuous_envelope": False}
    assert document["statistics"]["validity"]["outcome"] == "qualified"
    labels = situations.labels(document["statistics"])
    assert any("endpoint sensitivity" in text and "continuous" in text for text in labels)
    assert all("conservative" not in text for text in labels)
    assert "conservative" not in situations.CHECKS["bracket-envelope"].title
    component = next(c for c in document["uncertainty"]["components"] if c["name"] == "correlation-bracket")
    assert component["domain"] == bracket["domain"]
    assert "endpoint" in document["model_scope"]["correlations"]
    assert uncertainty.document_errors(document) == []


def test_unknown_bracket_rule_is_refused():
    check = situations._c_bracket_envelope({}, {"correlation_bracket": {
        "variants": {"one": 1., "two": 2.}, "reported": 1., "rule": "anything"}})
    assert check["status"] == "fail"


@pytest.mark.parametrize("mutation", ["source", "assignment", "root", "selection", "rule", "domain"])
def test_endpoint_qualification_requires_its_complete_evaluated_domain(tmp_path, monkeypatch, mutation):
    document = run_exclusion(tmp_path, monkeypatch, "constructed",
        srs=[dict(name="left", n=100, b=100, db=10, s=10),
             dict(name="right", n=100, b=100, db=10, s=20)],
        registry=source_registry("unknown"))
    record = document["statistics"]
    evidence = deepcopy(record["evidence"])
    bracket = evidence["correlation_bracket"]
    if mutation == "source":
        bracket["sources"] = bracket["domain"]["sources"] = ["another"]
    elif mutation == "assignment":
        key = next(iter(bracket["variants"]))
        bracket["variants"]["unrelated"] = bracket["variants"].pop(key)
    elif mutation == "root":
        key = next(iter(bracket["expected_median_status"]))
        bracket["expected_median_status"][key] = "above_scan"
    elif mutation == "selection":
        bracket["reported_assignment"] = {"normalization": "unknown"}
    elif mutation == "rule":
        bracket["rule"] = "min"
        bracket["reported"] = min(bracket["variants"].values())
    else:
        bracket["domain"]["continuous_envelope"] = True
    validity = situations.verify(record["facts"], record["decision"], evidence)
    assert validity["outcome"] == "held", (mutation, validity)
