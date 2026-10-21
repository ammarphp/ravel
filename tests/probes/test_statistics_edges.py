"""Bounded, offline statistical probes with fictional inputs only.

These exercise combinations at numerical transport, assessment and delivery
boundaries. Recorded evidence in the lightweight cases is explicitly synthetic;
it is not a claim that a likelihood fit or a toy ensemble was executed.
"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from statistics_records import inert_statistics, inert_uncertainty
from unit.test_limit_transport import exclusion, packed, point_dir
from unit.test_likelihood_appropriateness import add, workspace

from ravel.limits import attach_limits, bind_source, read_limits, source_errors
from ravel.physics import normalization_ledger as normalization
from ravel.physics.inference import search_statistics, situations, systematics, uncertainty
from ravel.plotting.scan_contour import comparison_data
from ravel.validation import likelihood_appropriateness, regression_triggers
from ravel.validation.verify_pack import Report, check_result
from ravel.workflow import scan_orchestrator as scan


def _write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, allow_nan=False))
    return path


def _qualified_counts():
    facts = situations.make_facts(
        deliverables=["exclusion"], model_origin="counting",
        bins=[{"channel": "SR", "bin": 0, "observed": 0.0,
               "background": 2.5, "background_uncertainty": 0.5}])
    availability = {"toy-cls": {"available": False, "reason": "budget: no toy fits admitted"}}
    evidence = {"limits": {"observed": "resolved", "median": "resolved"},
                "budget_refusals": [{"method": "toy-cls", "status": "not_run", "reason": "budget"}]}
    decision = situations.decide(situations.assess(facts, availability=availability))
    return situations.record(facts, evidence, availability=availability, decision=decision)


def _held_counts():
    facts = situations.make_facts(
        deliverables=["exclusion"], model_origin="constructed",
        bins=[{"channel": "SR", "bin": 0, "observed": 40.0, "background": 40.0}])
    return situations.record(facts, {"limits": {"observed": "resolved", "median": "resolved"}})


def _validity_rows(block):
    document = {"schema_version": 1, "kind": "inference", "results": [
        {"quantity": "statistics", "role": "diagnostic", "hypothesis": "p",
         "record": block, "outcome": block["validity"]["outcome"],
         "labels": situations.labels(block)}]}
    return [row for row in regression_triggers.evaluate(document)
            if row["trigger"] == "statistics-validity"]


def test_zero_observations_keep_both_toy_qualifications_in_adapter_output(tmp_path):
    """A resolved numerical limit at n=0 cannot imply calibrated CLs or discovery."""
    source = _write(tmp_path / "search.json", {
        "schema_version": 1, "kind": "search-statistics", "statistic": {"origin": "default"},
        "regions": [{"name": "SR", "role": "SR", "observed": [0.0]}],
        "backgrounds": [{"name": "background", "normfactor": None,
                         "yields": {"SR": {"values": [2.5], "sumw2": [0.0]}}}],
        "signal_points": [{"id": "p", "coordinates": {"mass": 1.0},
                           "yields": {"SR": {"values": [2.0], "sumw2": [0.0]}}}],
        "mc_statistics": "none", "systematics": None,
        "data": {"mode": "observed", "injections": {}},
        "computations": {"discovery": True, "cls_at_nominal": True,
                         "cls_limits": True, "background_only_fit": False},
        "asimov_source": "nominal", "cls_level": 0.05,
        "mc_adequacy": {"max_relative_uncertainty": 0.3, "min_effective_entries": 10},
        "contours": None})
    search_statistics.run({"input": str(source)}, tmp_path, tmp_path / "output")
    result = json.loads((tmp_path / "output/inference.json").read_text())
    block, = [row["record"] for row in result["results"] if row["quantity"] == "statistics"]
    assert situations.audit(block) == []
    assert block["facts"]["bins"][0]["observed"] == 0.0
    assert block["validity"]["outcome"] == "qualified"
    refused = {row["method"] for row in block["evidence"]["budget_refusals"]}
    assert {"toy-cls", "toy-significance"} <= refused
    expected_labels = {situations.situation(name).fallback["qualification"]
                       for name in ("low-counts", "low-count-significance")}
    assert expected_labels <= set(situations.labels(block))
    assert expected_labels <= set(result["limitations"])
    limit, = [row for row in result["results"] if row["quantity"] == "cls-limit"]
    assert limit["level"] == 0.05
    assert limit["observed"]["value"] > 0
    assert uncertainty.statement_errors(limit["uncertainty"]) == []
    assert [row["status"] for row in _validity_rows(block)] == ["warn"]


def test_unknown_shared_correlations_require_build_refusal_and_qualified_fallback():
    """Two region-dependent sources remain unknown even with finite recorded roots."""
    registry = systematics.Registry({"schema_version": 1, "absent": [], "sources": [
        {"name": name, "kind": "normsys", "relative_by_region": {"A": 0.1, "B": 0.2},
         "applies_to": {"samples": ["background"], "regions": ["A", "B"]},
         "correlation": "unknown", "origin": "cited", "citation": "fictional input table"}
        for name in ("scale", "shape")]})
    for region in ("A", "B"):
        with pytest.raises(ValueError, match="correlation.*unknown"):
            registry.modifiers("background", region, np.asarray([20.0]))
    facts = situations.make_facts(
        deliverables=["exclusion"], model_origin="counting",
        bins=[{"channel": region, "bin": 0, "observed": 20.0, "background": 20.0}
              for region in ("A", "B")], systematics=registry.sources,
        likelihood={"yields": True, "full": False, "covariance": False,
                    "systematics_registry": True, "mutually_exclusive_regions": True})
    block = situations.record(facts, {
        "limits": {"observed": "resolved", "median": "resolved"},
        "correlations_statement": "Only one region is used; cross-region correlation is unknown."},
        choices={
            "systematic-nuisances": {
                "method": "fallback", "justification": "No correlation variants admitted in this fictional record."},
            "likelihood-availability": {
                "method": "counting", "justification": "Use only one region with the recorded counting roots."}})
    assert situations.audit(block) == []
    assessment = next(row for row in block["assessment"]["situations"]
                      if row["situation"] == "systematic-nuisances")
    assert set(assessment["evidence"]["unknown_correlation"]) == {"scale", "shape"}
    assert block["validity"]["outcome"] == "qualified"
    assert situations.situation("systematic-nuisances").fallback["qualification"] in situations.labels(block)
    assert [row["status"] for row in _validity_rows(block)] == ["warn"]


def test_reused_likelihood_reports_changed_signal_selection_and_control_contamination():
    """Structural patch success cannot hide three independent applicability failures."""
    declared = {"signal_model": {"process": "a > x x", "final_state": "two visible objects",
                                  "parameters": ["mass"]}, "selection_identity": "selection-v1"}
    selection = {"signal_model": {"process": "a > y y", "final_state": "two visible objects",
                                   "parameters": ["mass"]}, "identity": "selection-v2"}
    verdict = likelihood_appropriateness.assess(
        workspace(), [add(0), add(1)],
        channel_map={"SR_a": {"region": "A"}, "SR_b": {"region": "B"}, "CR_x": None},
        declared=declared, selection=selection, signal_yields={"CR_x": {"s": 30.0, "b": 200.0}})
    assert verdict["verdict"] == "inappropriate"
    blocking = {row["code"]: row for row in verdict["findings"] if row["severity"] == "blocking"}
    assert {"signal-model-differs", "selection-changed", "control-regions-without-signal"} <= blocking.keys()
    assert blocking["control-regions-without-signal"]["evidence"]["channels"] == ["CR_x"]
    assert likelihood_appropriateness.validate_record(verdict) == []


def test_partial_scan_preserves_failed_and_missing_population_with_point_qualifications(tmp_path, monkeypatch):
    points = []
    for tag, block in (("qualified", _qualified_counts()), ("held", _held_counts()),
                       ("resolved", inert_statistics())):
        folder = tmp_path / tag
        folder.mkdir()
        points.append({**point_dir(folder, {**exclusion(), "statistics": block,
                                           "uncertainty": inert_uncertainty(document=exclusion())}), "tag": tag})
    missing = tmp_path / "missing"
    missing.mkdir()
    points.append({"tag": "missing", "run_dir": str(missing), "m_parent": 180.0, "dm": 10.0})
    manifest = {"name": "fictional scan", "points": points, "n_points": 4}
    monkeypatch.setattr(scan, "load_manifest", lambda _: (str(tmp_path), manifest))
    output = tmp_path / "scan.json"
    scan.cmd_assemble(SimpleNamespace(scandir=str(tmp_path), out=str(output), nlo_renorm=None))
    assembled = json.loads(output.read_text())
    assert (assembled["n_planned"], assembled["n_done"], assembled["n_missing"]) == (4, 2, 2)
    assert set(assembled["missing_tags"]) == {"held", "missing"}
    assert set(assembled["invalid_points"]) == {"held"}
    assert "held" in assembled["invalid_points"]["held"]
    assert {row["tag"]: row["status"] for row in assembled["point_population"]} == {
        "qualified": "completed", "held": "failed", "resolved": "completed", "missing": "missing"}
    assert {row["tag"] for row in assembled["points"]} == {"qualified", "resolved"}
    assert assembled["n_observed_roots"] == 2
    assert assembled["limitations"]
    assert all(row["points"] == ["qualified"] for row in assembled["limitations"])


def test_off_grid_and_capped_limits_cannot_acquire_reference_precision():
    points = []
    for tag, mass, status in (("exact", 100.0, "resolved"), ("off-grid", 125.0, "resolved"),
                              ("outside", 175.0, "resolved"), ("capped", 150.0, "above_scan")):
        point = attach_limits({"mu95_obs": 2.0, "mu95_exp": 2.0,
            "limit_status": {"observed": status,
                             "expected": ["missing", "missing", "resolved", "missing", "missing"]}})
        point.update(tag=tag, m_parent=mass, dm=10.0, sigma_ref_fb=5.0)
        points.append(point)
    report = comparison_data({"points": points, "n_planned": 5},
                             ([100.0, 150.0], [10.0, 10.0], [8.0, 12.0]))
    assert {row["tag"]: row["status"] for row in report["records"]} == {
        "exact": "matched", "off-grid": "unmatched_reference", "outside": "unmatched_reference",
        "capped": "quality_flag"}
    assert report["matched_fraction_of_plan"] == 0.2
    assert report["missing_scan_points"] == 1
    assert report["median_absolute_residual"] == pytest.approx(0.25)
    assert all("residual" not in row for row in report["records"] if row["tag"] != "exact")
    assert read_limits(points[-1]).observed.exclusion() is False


def test_signed_moments_and_equivalent_pb_fb_ledgers_preserve_yields_and_variance():
    """Cancellation changes the denominator; unit conversion happens once, variance twice."""
    ledger = {"schema_version": 1, "sample": "fictional signed sample",
        "luminosity": {"value": 2.0, "unit": "fb^-1", "source": "fictional exposure"},
        "sigma": {"value": 0.5, "unit": "pb", "order": "LO", "tool": "fictional calculator",
                  "pdf": "fictional density", "scales": "fixed", "process_basis": "a > x x",
                  "source": "fictional rate table"},
        "generated": {"requested_N": 10, "n_events": 10, "sumw": 6.0, "sumw2": 10.0,
                      "negative_fraction": 0.2},
        "selected": {"SR": {"sumw": [2.0, -1.0], "sumw2": [4.0, 1.0]}},
        "bin_convention": "per-bin", "observable_normalized": False}
    equivalent = deepcopy(ledger)
    equivalent["sigma"].update(value=500.0, unit="fb")
    equivalent["luminosity"].update(value=2000.0, unit="pb^-1")
    oracle_scale = 1000.0 / 6.0
    oracle = [2.0 * oracle_scale, -oracle_scale]
    for document in (ledger, equivalent):
        report = normalization.check(document, delivered={"SR": oracle})
        assert report["passed"], report["failures"]
        assert report["scale"] == pytest.approx(oracle_scale)
        assert {row["code"] for row in report["warnings"]} >= {"negative_weights"}
        projected = normalization.expected_yields(document)["SR"]
        assert projected["values"] == pytest.approx(oracle)
        assert [error ** 2 for error in projected["errors"]] == pytest.approx(
            [4.0 * oracle_scale ** 2, oracle_scale ** 2])
        wrong = normalization.check(document, delivered={"SR": [value * 1000.0 for value in oracle]})
        assert not wrong["passed"]
        assert "unit_swap" in {row["code"] for row in wrong["failures"]}


def test_source_bound_resolved_limit_qualifies_wrong_prose_in_delivered_markdown(tmp_path, monkeypatch, record_property):
    """The controller labels an unmatched prose value, beyond the scoped pack utility."""
    from ravel.controller import sink
    from unit.controller.p07_support import READING, Run, statuses

    primary = attach_limits(exclusion())
    point_dir(tmp_path, primary)
    result = packed(primary)
    bind_source(result, tmp_path, "output/exclusion.json")
    assert source_errors(result, tmp_path, required=True) == []
    _write(tmp_path / "result.json", result)
    for name, quoted, clean in (("clean", "0.8", True), ("wrong", "0.2", False)):
        prose = f"# Result\n\nThe observed limit is mu95_obs = {quoted}.\n"
        (tmp_path / "RESULT.md").write_text(prose)
        mechanical = Report()
        check_result(mechanical, str(tmp_path), {}, "result.json", result, None)
        mechanical_failures = [message for level, _, message in mechanical.lines if level == "FAIL"]
        record_property(f"mechanical_{name}_findings", json.dumps(mechanical_failures))
        if clean:
            assert mechanical_failures == []

        # Each sibling uses the unchanged P07 harness with its own ledger/store.
        with monkeypatch.context() as scoped:
            reading = deepcopy(READING)
            reading["deliverables"][0]["claim_kind"] = "exclusion"
            run = Run(tmp_path / name, scoped, reading=reading)
            # Adopt scientific output, with its full inert evidence. The legacy
            # pack's architecture wrapper is a sink-owned receipt and cannot be
            # adopted as worker evidence (the unchanged D06 guard refuses it).
            adopted = {**deepcopy(primary), "statistic": "95% CLs",
                       "statistics": inert_statistics(), "uncertainty": inert_uncertainty(document=primary)}
            _write(run.dir / "output/exclusion.json", adopted)
            bind_source(adopted, run.dir, "output/exclusion.json")
            assert source_errors(adopted, run.dir, required=True) == []
            run.complete(value=adopted, report=prose)
            receipt = run.deliver()
            status, evidence = statuses(run, "D01")["s2:outputs/report.md"]
            assert receipt["label"] == "accepted", receipt
            delivered = run.delivered("artifacts/s2/outputs/report.md").read_text()
            header = delivered.split("<!-- END RAVEL SINK NOTICE -->")[0]
            adopted_report = run.dir / "steps/s2/outputs/report.md"
            adopted_digest = hashlib.sha256(adopted_report.read_bytes()).hexdigest()
            assert "Source: steps/s2/outputs/report.md" in header
            assert adopted_digest in header
            assert "Receipt: delivery/RECEIPT.json" in header
            assert delivered.endswith(prose)
            if clean:
                assert status == "satisfied"
                assert sink.UNVERIFIED not in receipt["labels"]
                assert sink.UNVERIFIED not in header
            else:
                assert status == "violated"
                assert evidence["label"] == sink.UNVERIFIED
                assert "0.2" in evidence["reason"]
                assert sink.UNVERIFIED in receipt["labels"]
                assert sink.UNVERIFIED in header


def test_delivery_rechecks_changed_evidence_even_after_primary_source_is_rebound(tmp_path):
    block = _qualified_counts()
    primary = attach_limits({**exclusion(), "statistics": block, "uncertainty": inert_uncertainty(document=exclusion())})
    point = point_dir(tmp_path, primary)
    result = deepcopy(primary)
    result["statistics"] = {"outcome": "qualified", "labels": situations.labels(block),
                            "catalogue_sha256": block["catalogue_sha256"]}
    bind_source(result, tmp_path, "output/exclusion.json")
    _write(tmp_path / "result.json", result)
    assert scan.harvest_point(point)["statistics"] == block
    changed = deepcopy(primary)
    changed["statistics"]["evidence"].pop("budget_refusals")
    source = _write(tmp_path / "output/exclusion.json", changed)
    assert any("bytes changed" in error for error in source_errors(result, tmp_path, required=True))
    # Refreshing file custody alone cannot discharge the changed statistical evidence.
    result["limit_source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    _write(tmp_path / "result.json", result)
    with pytest.raises(ValueError, match="does not recompute|no budget refusal"):
        scan.harvest_point(point)
    assert scan.point_status(point) == ("failed", None)
    # A newly recomputed hold also cannot be promoted by an old headline summary.
    changed["statistics"] = _held_counts()
    source = _write(source, changed)
    result["limit_source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    result["statistics"].update(outcome="valid", labels=[])
    _write(tmp_path / "result.json", result)
    with pytest.raises(ValueError, match="held|summary differs"):
        scan.harvest_point(point)
    assert scan.point_status(point) == ("failed", None)
