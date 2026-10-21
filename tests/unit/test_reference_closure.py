"""Closure of constructed and simplified likelihoods against published limits, where they are available.

On the constructed and simplified rungs of the statistical-mode ladder, each published benchmark is
recomputed through the same model. Closure within the tolerance is valid; a miss holds the result;
no reference, and no declared absence with its reason and evidence, qualifies it. Synthetic
benchmarks only: their "published" limits are this model's own limits, or deliberate distortions
of them.
"""
from copy import deepcopy
import json
import sys

import numpy as np
import pytest

from ravel.physics import pyhf_exclude as exclude
from ravel.physics.inference import closure, constructed, situations
from ravel.workflow import stat_mode_decision as smd

SRS = [{"name": "left", "n": 100, "b": 100, "db": 10, "s": 20}, {"name": "right", "n": 80, "b": 80, "db": 8, "s": 10}]
REGISTRY = {"schema_version": 1, "absent": [], "sources": [
    {"name": "normalization", "kind": "normsys", "relative": .1,
     "applies_to": {"samples": ["background"], "regions": "all"}, "correlation": "correlated",
     "origin": "requester-assumption", "statement": "synthetic normalization uncertainty"}]}
COVARIANCE = {"schema_version": 1, "kind": "background-covariance", "regions": ["left", "right"],
              "covariance": [[100., 20.], [20., 64.]], "source": "synthetic covariance declaration"}
ABSENT = {"schema_version": 1, "kind": "reference-limits", "available": False,
          "reason": "synthetic: the fixture publishes no benchmark limits", "evidence": "synthetic fixture"}


@pytest.fixture(autouse=True)
def numerical_state():
    previous = exclude.pyhf.get_backend()
    state = np.random.get_state()
    try:
        yield
    finally:
        exclude.pyhf.set_backend(*previous)
        np.random.set_state(state)


def _decision(*, covariance):
    evidence = {"published_likelihood": {"available": False, "path": None, "appropriateness": None},
                "covariance": {"available": covariance, "path": "inputs/covariance.json" if covariance else None,
                               "source": COVARIANCE["source"] if covariance else None},
                "systematics_registry": {"available": not covariance,
                                         "path": None if covariance else "inputs/systematics.json"},
                "yields": {"available": True, "path": "outputs/sr_yields.json"}, "mutually_exclusive_regions": True}
    return smd.decide(evidence)


def _write(path, value):
    path.write_text(json.dumps(value))
    return str(path)


def _run(tmp_path, monkeypatch, mode, reference=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    args = ["pyhf_exclude", mode, "--srs", _write(tmp_path / "srs.json", SRS), "--out", str(tmp_path / "out"),
            "--stat-mode-decision", _write(tmp_path / "decision.json", _decision(covariance=mode == "simplified"))]
    if mode == "constructed":
        args += ["--systematics", _write(tmp_path / "sources.json", REGISTRY), "--regions-exclusive",
                 "--cls-calculator", "asymptotic"]
    else:
        args += ["--covariance", _write(tmp_path / "covariance.json", COVARIANCE)]
    if reference is not None:
        args += ["--reference-limits", _write(tmp_path / "reference.json", reference)]
    monkeypatch.setattr(sys, "argv", args)
    try:
        exclude.main()
        code = 0
    except SystemExit as exc:
        code = exc.code
    document = json.loads((tmp_path / "out" / "exclusion.json").read_text())
    assert situations.audit(document["statistics"]) == []
    return document, code


def _reference(document, factor):
    """Benchmarks at the run's own signal and at twice it, 'published' at ``factor`` times this model's limits."""
    expected, observed = document["exp_limits"][2], document["obs_limit"]
    return {"schema_version": 1, "kind": "reference-limits", "quantity": "signal_strength",
            "source": "synthetic benchmark table",
            "points": [{"id": "run-signal", "signal": {r["name"]: r["s"] for r in SRS},
                        "expected": expected * factor, "observed": observed * factor},
                       {"id": "twice", "signal": {r["name"]: 2 * r["s"] for r in SRS},
                        "expected": expected / 2 * factor, "observed": None}]}


def _check(block, name):
    return next(row for row in block["validity"]["checks"] if row["check"] == name)


@pytest.mark.parametrize("mode,method", [("constructed", "constructed-likelihood"),
                                         ("simplified", "simplified-likelihood")])
def test_closure_against_published_limits_decides_the_rung_outcome(tmp_path, monkeypatch, mode, method):
    plain, code = _run(tmp_path / "plain", monkeypatch, mode)
    block = plain["statistics"]
    selected = next(r for r in block["decision"]["choices"] if r["situation"] == "likelihood-availability")
    assert selected["method"] == method
    assert _check(block, "reference-limits-declared")["status"] == "fail"
    label = situations.CHECKS["reference-limits-declared"].qualification
    assert label in situations.labels(block) and block["validity"]["outcome"] == "qualified" and code == 0
    assert {"key": "statistics-qualified", "note": label} in plain["limitations"]

    absent, code = _run(tmp_path / "absent", monkeypatch, mode, ABSENT)
    assert _check(absent["statistics"], "reference-limits-declared")["status"] == "pass"
    assert label not in situations.labels(absent["statistics"]) and code == 0
    assert "limitations" not in absent  # nothing to state: an unqualified result keeps its shape

    closing, code = _run(tmp_path / "close", monkeypatch, mode, _reference(plain, 1.0))
    assert closing["reference_closure"]["calculator"] == "asymptotic"
    rows = closing["reference_closure"]["points"]
    assert [r["id"] for r in rows] == ["run-signal", "twice"]
    assert abs(rows[0]["relative_difference"]["expected"]) < 1e-6
    assert abs(rows[1]["relative_difference"]["expected"]) < .01  # twice the signal halves the limit
    assert _check(closing["statistics"], "reference-limit-closure")["status"] == "pass"
    stated = next(c for c in closing["uncertainty"]["components"] if c["name"] == "reference-closure")
    assert stated["kind"] == "method" and stated["benchmarks"] == 2 and stated["worst_relative_difference"] < .01
    declared = next(c for c in absent["uncertainty"]["components"] if c["name"] == "reference-closure")
    assert declared["status"] == "not-evaluated" and declared["reason"] == ABSENT["reason"]
    assert situations.CHECKS["reference-limit-closure"].qualification not in situations.labels(closing["statistics"])
    assert code == 0

    missing, code = _run(tmp_path / "far", monkeypatch, mode, _reference(plain, 1.5))
    assert _check(missing["statistics"], "reference-limit-closure")["status"] == "fail"
    assert missing["statistics"]["validity"]["outcome"] == "held" and code == 3
    assert {"key": "statistics-held", "note": situations.CHECKS["reference-limit-closure"].qualification} in \
        missing["limitations"]


def test_the_check_recomputes_differences_instead_of_reading_them():
    facts = situations.make_facts(deliverables=["exclusion"], model_origin="constructed",
                                  bins=[{"channel": "left", "bin": 0, "observed": 100., "background": 100.}])
    row = {"id": "bm", "published": {"expected": 1.0, "observed": None},
           "reproduced": {"expected": {"value": 2.0, "status": "resolved"}, "observed": None},
           "relative_difference": {"expected": 0.0, "observed": None}}
    evidence = {"reference_closure": {"available": True, "points": [row]}}
    assert situations.CHECKS["reference-limit-closure"].evaluate(facts, evidence)["status"] == "fail"
    unresolved = deepcopy(evidence)
    unresolved["reference_closure"]["points"][0]["reproduced"]["expected"] = {"value": 1.0, "status": "above_scan"}
    assert "above_scan" in situations.CHECKS["reference-limit-closure"].evaluate(facts, unresolved)["detail"]
    reasonless = {"reference_closure": {"available": False, "reason": " ", "evidence": "searched"}}
    assert situations.CHECKS["reference-limits-declared"].evaluate(facts, reasonless)["status"] == "fail"


@pytest.mark.parametrize("damage,match", [
    (lambda d: d.update(kind="limits"), "kind"),
    (lambda d: d.pop("source"), "source"),
    (lambda d: d.update(quantity="cross_section"), "quantity"),
    (lambda d: d["points"][0]["signal"].pop("right"), "exactly the regions"),
    (lambda d: d["points"][0].update(expected=0), "positive"),
    (lambda d: d["points"][0].update(signal={"left": 0, "right": 0}), "no signal"),
    (lambda d: d["points"].append(deepcopy(d["points"][0])), "listed twice"),
    (lambda d: d.update(extra=1), "carry"),
])
def test_reference_documents_are_validated(damage, match):
    document = {"schema_version": 1, "kind": "reference-limits", "quantity": "signal_strength", "source": "table",
                "points": [{"id": "bm", "signal": {"left": 1., "right": 2.}, "expected": 1., "observed": None}]}
    assert closure.load(document, ["left", "right"])["points"][0]["id"] == "bm"
    damage(document)
    with pytest.raises(ValueError, match=match):
        closure.load(document, ["left", "right"])
    with pytest.raises(ValueError, match="reason"):
        closure.load({**ABSENT, "reason": ""}, ["left", "right"])


def test_a_bracketed_result_is_closed_with_its_reported_variant():
    document = deepcopy(REGISTRY)
    document["sources"][0]["correlation"] = "unknown"
    bracket = {"sources": ["normalization"], "reported_variant": "normalization=per-region",
               "reported_assignment": {"normalization": "per-region"}}
    assert constructed.variant_registry(document, bracket)["sources"][0]["correlation"] == "per-region"
    assert constructed.variant_registry(document)["sources"][0]["correlation"] == "unknown"
    assert document["sources"][0]["correlation"] == "unknown"  # the input registry is not changed
