"""Deterministic independent known-background Poisson references only."""
import ast
import math
from pathlib import Path

import pytest

from ravel.validation import statistical_calibration as calibration


def direct_cdf(count, mean):
    # Independent finite sum for the small, hand-frozen cases in this board.
    return math.exp(-mean) * math.fsum(mean ** k / math.factorial(k)
                                     for k in range(count + 1))


@pytest.mark.parametrize("count,mu,signal,background", [
    (0, 3.0, 1.0, 0.0), (0, 3.0, 1.0, 20.0),
    (2, 1.5, 2.0, 0.2), (7, 0.5, 3.0, 2.0), (3, 0.0, 1.0, 2.0)])
def test_count_ordered_cls_matches_independent_finite_sum(count, mu, signal, background):
    actual = calibration.known_background_poisson_cls(count, mu, signal, background)
    expected = direct_cdf(count, background + mu * signal) / direct_cdf(count, background)
    assert actual == pytest.approx(expected, rel=1e-12, abs=1e-15)


def test_zero_count_formula_and_signal_unit_rescaling():
    for background in (0.0, 0.2, 2.0, 20.0):
        result = calibration.known_background_poisson_upper_limit(0, 1.0, background)
        assert result["status"] == "resolved"
        assert result["value"] == pytest.approx(-math.log(0.05), abs=1e-12)
        assert result["root_cls_residual"] == pytest.approx(0.0, abs=1e-14)
    scaled = calibration.known_background_poisson_upper_limit(0, 2.0, 0.0)
    assert scaled["value"] == pytest.approx(-math.log(0.05) / 2, abs=1e-12)


def test_nonzero_count_root_checked_without_producer_backend():
    result = calibration.known_background_poisson_upper_limit(2, 1.0, 0.2)
    root = result["value"]
    assert result["status"] == "resolved"
    assert direct_cdf(2, 0.2 + root) / direct_cdf(2, 0.2) == pytest.approx(0.05, abs=1e-10)
    assert result["bracket"][0] <= root <= result["bracket"][1]
    assert result["iterations"] <= 256


def test_insufficient_cap_is_a_bound_and_exact_cap_is_a_root():
    bounded = calibration.known_background_poisson_upper_limit(0, 1.0, 0.0, poi_cap=1.0)
    assert bounded["status"] == "above_scan"
    assert bounded["value"] == 1.0
    assert bounded["bracket"] == [1.0, None]
    assert bounded["root_cls_residual"] is None
    exact_cap = calibration.known_background_poisson_upper_limit(
        0, 1.0, 0.0, poi_cap=-math.log(0.05))
    assert exact_cap["status"] == "resolved"


def test_log_cdf_ratio_does_not_divide_two_underflowed_cdfs():
    assert calibration.known_background_poisson_cls(0, 3.0, 1.0, 997.0) == pytest.approx(
        math.exp(-3), rel=1e-12)


def test_exact_finite_lattice_retains_all_mass_and_zero_count_rejection():
    result = calibration.known_background_poisson_coverage(3.0, 1.0, 0.0, max_count=100)
    assert result["status"] == "resolved"
    assert [r["observed_count"] for r in result["lattice"] if r["excluded"]] == [0]
    assert result["retained_rejected_probability"] == pytest.approx(math.exp(-3), abs=1e-14)
    expected = 1 - math.exp(-3)
    assert result["coverage_lower_bound"] <= expected <= result["coverage_upper_bound"]
    assert result["omitted_probability_upper_bound"] < 1e-100
    assert result["retained_probability"] == pytest.approx(
        result["retained_covered_probability"] + result["retained_rejected_probability"], abs=1e-14)
    assert result["lattice_size"] == 101
    assert result["random_draws"] == 0
    assert result["general_likelihood_coverage_validated"] is False


@pytest.mark.parametrize("background", [0.0, 0.2, 2.0, 20.0])
@pytest.mark.parametrize("mu", [0.0, 0.25, 1.0, 3.0, 8.0])
def test_twenty_fixed_truth_cells_have_conservative_count_ordered_coverage(background, mu):
    result = calibration.known_background_poisson_coverage(mu, 1.0, background, max_count=200)
    assert result["status"] == "resolved"
    assert result["coverage_lower_bound"] >= 0.95 - 1e-10


def test_small_lattice_is_incomplete_without_renormalizing_retained_mass():
    result = calibration.known_background_poisson_coverage(3.0, 1.0, 0.0, max_count=0)
    assert result["status"] == "incomplete"
    assert result["retained_probability"] == pytest.approx(math.exp(-3))
    assert result["omitted_probability_upper_bound"] == 1.0
    assert result["retained_covered_probability"] == 0.0
    assert result["coverage_lower_bound"] == 0.0
    assert result["coverage_upper_bound"] == 1.0


def test_geometric_tail_bound_covers_independently_summed_missing_probability():
    result = calibration.known_background_poisson_coverage(3.0, 1.0, 0.0, max_count=8)
    omitted = math.fsum(math.exp(-3) * 3 ** n / math.factorial(n) for n in range(9, 80))
    assert result["omitted_probability_upper_bound"] >= omitted
    assert result["status"] == "incomplete"
    assert result["retained_probability"] + omitted == pytest.approx(1, abs=1e-14)


@pytest.mark.parametrize("bad", [True, False, -1, 1.5, "1", None, math.nan, math.inf, 10_001])
def test_observations_and_lattice_cap_require_bounded_integer_counts(bad):
    with pytest.raises(ValueError):
        calibration.known_background_poisson_cls(bad, 1.0, 1.0, 0.0)
    with pytest.raises(ValueError):
        calibration.known_background_poisson_coverage(1.0, 1.0, 0.0, max_count=bad)


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("bad", [True, False, -1.0, "2", None, math.nan, math.inf, 10 ** 1000])
def test_strict_finite_law_inputs(index, bad):
    values = [1.0, 1.0, 0.0]
    values[index] = bad
    with pytest.raises(ValueError):
        calibration.known_background_poisson_cls(0, *values)
    with pytest.raises(ValueError):
        calibration.known_background_poisson_coverage(*values)


def test_zero_signal_and_out_of_domain_mean_are_refused():
    with pytest.raises(ValueError, match="signal_yield"):
        calibration.known_background_poisson_upper_limit(0, 0.0, 0.0)
    with pytest.raises(ValueError, match="numerical domain"):
        calibration.known_background_poisson_cls(0, 2.0, 1.0, 999.0)
    with pytest.raises(ValueError, match="underflowed"):
        calibration.known_background_poisson_cls(0, math.nextafter(0.0, 1.0),
                                                 math.nextafter(0.0, 1.0), 0.0)


@pytest.mark.parametrize("kwargs", [
    {"level": True}, {"level": 0.0}, {"level": 1.0}, {"level": math.nan},
    {"poi_cap": False}, {"poi_cap": 0.0}, {"poi_cap": math.inf},
    {"root_rtol": True}, {"root_rtol": 1e-20}, {"root_rtol": 0.1}])
def test_invalid_endpoint_controls(kwargs):
    with pytest.raises(ValueError):
        calibration.known_background_poisson_upper_limit(0, 1.0, 0.0, **kwargs)


@pytest.mark.parametrize("bad", [True, False, 0.0, -1.0, 1.0, math.inf, math.nan])
def test_invalid_tail_tolerance(bad):
    with pytest.raises(ValueError):
        calibration.known_background_poisson_coverage(1.0, 1.0, 0.0, tail_tolerance=bad)


def test_checker_has_no_producer_or_inference_backend_imports():
    tree = ast.parse(Path(calibration.__file__).read_text())
    names = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    names += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
              for alias in node.names]
    assert set(names) <= {"__future__", "math", "sys"}
