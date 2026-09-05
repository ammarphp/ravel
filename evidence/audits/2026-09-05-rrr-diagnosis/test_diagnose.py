"""Adversarial arithmetic and full retained-population controls for this audit."""
import copy
import importlib.util
import json
import math
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rrr_diagnose", HERE / "diagnose.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_coarse_exponential_bracket_is_not_an_evaluated_root():
    # Known analytic control: CLs=exp(-mu). The secant estimate is not log(20).
    x = [0., 10.]
    y = [1., math.exp(-10)]
    secant = (.05 - 1) / (math.exp(-10) - 1) * 10
    result = audit.crossing_diagnostic(x, y, secant)
    assert result["status"] == "sampled_bracket"
    assert result["reported_matches_linear"]
    assert not result["cls_evaluated_at_reported"]
    assert result["log_interpolation_mu_diagnostic_only"] == pytest.approx(math.log(20))
    assert secant > 3 * math.log(20)


@pytest.mark.parametrize("x,y,status", [
    ([0., 1.], [.01, .001], "all_below"),
    ([0., 1.], [1., .2], "all_above"),
    ([0., 1., 2., 3.], [1., .01, .2, .001], "ambiguous_samples"),
    ([0., 0., 1.], [1., .2, .01], "invalid_samples"),
    ([0., 1.], [1., float("nan")], "invalid_samples"),
    ([0., 1.], [1., -.1], "invalid_samples"),
])
def test_bad_or_censored_samples_are_not_interpolated(x, y, status):
    assert audit.crossing_diagnostic(x, y, .5)["status"] == status


def test_signed_distribution_keeps_outliers_and_distinguishes_absolute():
    result = audit.distribution([-0.5, -0.4, -0.3, 2.])
    assert result["n"] == 4
    assert result["negative"] == 3
    assert result["signed_median"] == pytest.approx(-.35)
    assert result["median_absolute"] == pytest.approx(.45)
    assert result["quantiles"]["1"] == 2


def snapshot():
    return json.loads((HERE / "retained-inputs.json").read_text())


def test_full_retained_population_and_paired_quality_denominator():
    report = audit.analyse(snapshot())
    assert len(report["points"]) == 3 * 52 * 2
    assert report["summary"]["original"]["kinds"]["observed"]["counts"]["matched"] == 50
    assert report["summary"]["fresh_cteq6l1"]["kinds"]["observed"]["counts"]["matched"] == 52
    pair = report["pairs"]["original_to_pdf_rescan"]["observed"]
    assert pair["planned_union"] == 52
    assert pair["matched"] == 48
    assert len(pair["ineligible_tags"]) == 4
    assert report["summary"]["original"]["kinds"]["observed"]["plain_linear_interpolation_matches"] == 50


def test_snapshot_cannot_silently_drop_points_or_change_residual():
    source = snapshot()
    changed = copy.deepcopy(source)
    changed["campaigns"]["original"]["comparisons"]["observed"]["records"].pop()
    with pytest.raises(ValueError, match="retain all scan points"):
        audit.analyse(changed)
    changed = copy.deepcopy(source)
    changed["campaigns"]["original"]["comparisons"]["observed"]["records"][0]["residual"] = .99
    with pytest.raises(ValueError, match="arithmetic mismatch"):
        audit.analyse(changed)


def test_retained_red_cell_and_normalization_cancellation_are_exposed():
    report = audit.analyse(snapshot())
    red = next(r for r in report["points"] if (r["campaign"], r["kind"], r["tag"]) == ("original", "observed", "m50_dm5"))
    assert red["residual"] == pytest.approx(.8784199982832863)
    assert red["numerical"]["interval_index"] == 0
    assert red["numerical"]["width_over_reported"] > 1
    assert not red["mc"]["signal_stat_nuisance_present"]
    assert abs(red["normalization"]["rounding_cancellation_fraction"]) < 4e-5


def test_partial_detector_exposure_cannot_masquerade_as_20000_events():
    report = audit.analyse(snapshot())
    rows = {r["tag"]: r for r in report["points"] if r["campaign"] == "pdf_rescan" and r["kind"] == "observed"}
    assert rows["m250_dm5"]["mc"]["n_generated"] == 20000
    assert rows["m250_dm5"]["mc"]["n_detector_events"] == 221
    assert not rows["m250_dm5"]["mc"]["detector_exposure_complete"]
    assert rows["m250_dm5"]["mc"]["sr_s_imt2h_events"] == 3
    assert sum(rows["m250_dm5"]["mc"]["channel_count_proxy_using_detector_exposure"]) == pytest.approx(3, rel=1e-5)
    assert rows["m150_dm20"]["mc"]["detector_exposure_complete"]
    pair = report["pairs"]["original_to_pdf_rescan"]["observed"]
    assert pair["matched"] == 48  # Original archive arithmetic is preserved.
    assert pair["complete_exposure_ratio_sensitivity_not_replacement"]["n"] == 46
