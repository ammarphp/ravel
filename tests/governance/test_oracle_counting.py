"""Independent counting oracle: definitions, metamorphic checks and pyhf/kernel agreement.

Every fixture here is a development input for software tests, not a physics result or an agent
outcome. All are SYNTHETIC except the 2jl counts (n = 263, b = 283 +- 24 events), which are
DERIVED FROM PUBLISHED values: ATLAS arXiv:1605.03814, SR 2jl (Table 6, as cited in
evidence/audits/2026-09-08-statistical-fidelity/README.md; record
benchmarks/scoped/atlas-2jl-counting.json), used in a single-bin gamma/Poisson approximation. No
HEPData record is used for them; the deferred human review confirms the table and whether one
should be cited. Agreement tests skip when pyhf 0.7.6 or the ravel kernel is unavailable.
"""
import ast
import contextlib
import copy
import io
import json
import math
import random
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

from governance.canonical import ContractError, canonical_bytes, sha256_bytes
from governance.oracle import counting
from governance.tasks.development.likelihood_freshness import family

ROOT = Path(__file__).resolve().parents[2]
COUNTING_SOURCE = ROOT / "benchmarks" / "governance" / "oracle" / "counting.py"

# Fixtures (n_obs, background, background_uncertainty, poi_cap): the family's distinct synthetic
# prior/current workspaces plus four extra cases: the 2jl counts derived from published values
# (see the module docstring), and three synthetic ones (a low-count excess, a loosely constrained
# background, and a large excess over a tiny, loosely constrained background whose conditional
# mu = 0 fit, and so the Asimov data, sit at the shapesys upper bound gamma = 10).
FIXTURES = {
    "synthetic-family-prior": (42, 38.0, 5.0, 256.0),
    "synthetic-family-V1-current": (42, 44.0, 5.0, 256.0),
    "derived-from-published-2jl": (263, 283.0, 24.0, 256.0),
    "synthetic-low-count": (5, 3.0, 1.0, 256.0),
    "synthetic-loose-constraint": (12, 5.0, 3.0, 256.0),
    "synthetic-gamma-at-upper-bound": (1000, 5.0, 50.0, 4096.0),
}
# Achieved worst relative agreement over all six limits of every fixture (2026-09-25, macOS
# arm64 only, pyhf 0.7.6, scipy 1.14.1, numpy 1.26.4, 64b): stock pyhf 4.2e-8, kernel 2.5e-5.
# Both bounds are regression bounds on the oracle, not the references' precision contracts.
# STOCK_PYHF_RTOL holds only with the pinned scipy_optimizer(tolerance=1e-9) below: pyhf's
# default optimizer tolerance agrees only to ~6e-5. It keeps ~24x headroom over the macOS
# result because it has not been measured on Linux. KERNEL_RTOL is the brief's 1e-3: 40x the
# achieved value and 5x below the 0.005 fidelity tolerance, so a subject who reports the
# kernel's value is scored against the oracle well inside tolerance. It is tighter than the
# kernel's full contract (root_rtol = 1e-4 plus root_cls_atol = 5e-4, up to 0.32% on S95, slice
# section 5), so a kernel change within that contract can still trip it; review such a change
# rather than widening this bound.
STOCK_PYHF_RTOL = 1e-6
KERNEL_RTOL = 1e-3


def values(result):
    return [result["obs_limit_events"], *result["exp_limits_events"]]


def cls_values(result):
    return [result["observed"], *result["expected"]]


def fixture_limits(label):
    n, b, sigma, cap = FIXTURES[label]
    return counting.limits(n, b, sigma, poi_cap=cap)


def relative(a, b):
    return abs(a - b) / abs(b)


# --------------------------------------------------------------------------- definitions

def test_family_fixtures_cover_every_family_workspace():
    seen = set()
    for variant in family.VARIANTS:
        for files in family.variant_inputs(variant).values():
            parsed = counting.parse_counting_workspace(json.loads(files["workspace.json"]))
            seen.add((parsed["n_obs"], parsed["background"], parsed["background_uncertainty"]))
    assert seen <= {fixture[:3] for fixture in FIXTURES.values()}
    assert len(seen) == 2


def test_public_2jl_reference_values():
    result = counting.limits(263, 283.0, 24.0)
    assert result["limit_status"] == {"observed": "resolved", "expected": ["resolved"] * 5}
    assert abs(result["obs_limit_events"] - 43.6513) < 5e-5
    assert abs(result["exp_limits_events"][2] - 54.8858) < 5e-5


def golden_argmax(f, lo, hi, iterations=160):
    """Test-side golden-section maximization (independent of the oracle's closed forms)."""
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iterations):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = f(d)
    return 0.5 * (a + b)


def log_likelihood(mu, g, n, a, b, tau):
    lam = mu + g * b
    return n * math.log(lam) - lam + a * math.log(g * tau) - g * tau


@pytest.mark.parametrize("label", sorted(FIXTURES))
def test_closed_form_profiles_match_numeric_maximization(label):
    n, b, sigma, cap = FIXTURES[label]
    model = counting._SingleBin(b, sigma)
    tau = b * b / (sigma * sigma)
    lo, hi = counting.GAMMA_BOUNDS
    for mu in (0.0, 0.5, 4.0, 17.0, 60.0):
        numeric = golden_argmax(lambda g: log_likelihood(mu, g, n, tau, b, tau), lo, hi)
        assert relative(model.gamma_hat(mu, n, tau), numeric) < 1e-6
    # 1-D maximization of the profile likelihood over mu in [0, poi_cap].
    def profile(mu):
        g = golden_argmax(lambda g: log_likelihood(mu, g, n, tau, b, tau), lo, hi)
        return log_likelihood(mu, g, n, tau, b, tau)
    mu_numeric = golden_argmax(profile, 0.0, cap)
    mu_hat, g_hat = model.free_fit(n, tau)
    assert mu_hat == max(n - b, 0.0)
    assert abs(mu_numeric - mu_hat) < 1e-5 * max(1.0, mu_hat)
    # The cancellation-free q~ equals the naive log-likelihood difference; the naive form
    # cancels terms of size ~n*log(n), so its own error is absolute, not relative.
    for mu in (mu_hat + 1.0, mu_hat + 10.0, mu_hat + 40.0):
        g = model.gamma_hat(mu, n, tau)
        naive = 2.0 * (log_likelihood(mu_hat, g_hat, n, tau, b, tau) - log_likelihood(mu, g, n, tau, b, tau))
        assert abs(model.qtilde(mu, n, tau, (mu_hat, g_hat)) - naive) < 1e-9 * max(1.0, naive)


def test_gamma_bounds_are_the_pyhf_shapesys_defaults():
    # pyhf 0.7.6 pyhf/modifiers/shapesys.py: "bounds": ((1e-10, 10.0),); checked against the
    # installed pyhf model in test_gamma_bounds_match_installed_pyhf.
    assert counting.GAMMA_BOUNDS == (1e-10, 10.0)


def test_gamma_upper_bound_binds_for_the_bound_fixture():
    n, b, sigma, cap = FIXTURES["synthetic-gamma-at-upper-bound"]
    model = counting._SingleBin(b, sigma)
    unclipped = (n + model.tau) / (b + model.tau)   # score root at mu = 0: g = (n + a) / (b + tau)
    assert unclipped > counting.GAMMA_BOUNDS[1]
    assert model.gamma_hat(0.0, n, model.tau) == counting.GAMMA_BOUNDS[1]
    result = counting.limits(n, b, sigma, poi_cap=cap)
    assert result["limit_status"] == {"observed": "resolved", "expected": ["resolved"] * 5}


def test_qtilde_is_zero_above_fitted_signal():
    model = counting._SingleBin(38.0, 5.0)
    fit = model.free_fit(60, model.tau)
    assert fit == (22.0, 1.0)
    assert model.qtilde(21.9, 60, model.tau, fit) == 0.0
    assert model.qtilde(22.1, 60, model.tau, fit) > 0.0


# --------------------------------------------------------------------------- metamorphic

@pytest.mark.parametrize("label", sorted(FIXTURES))
def test_expected_quantiles_strictly_ordered(label):
    result = fixture_limits(label)
    expected = result["exp_limits_events"]
    assert all(low < high for low, high in zip(expected, expected[1:]))
    assert result["limit_status"] == {"observed": "resolved", "expected": ["resolved"] * 5}


def test_observed_limit_increases_with_observed_count():
    limits = [counting.limits(n, 38.0, 5.0)["obs_limit_events"] for n in range(10, 90, 4)]
    assert all(low < high for low, high in zip(limits, limits[1:]))


def test_larger_level_gives_smaller_limits():
    strict = values(counting.limits(42, 38.0, 5.0, level=0.05))
    loose = values(counting.limits(42, 38.0, 5.0, level=0.10))
    assert all(a < b for a, b in zip(loose, strict))


def known_background_limit(n, b, index, level=0.05):
    """Test-side asymptotic q~ CLs limit for a Poisson count with exactly known b."""
    phi = statistics.NormalDist().cdf
    mu_hat = max(n - b, 0.0)

    def nll2(lam, k):
        return 2.0 * (lam - k * math.log(lam))

    def cls(mu):
        q = 0.0 if mu_hat > mu else max(0.0, nll2(mu + b, n) - nll2(mu_hat + b, n))
        qa = nll2(mu + b, b) - nll2(b, b)
        sq, sqa = math.sqrt(q), math.sqrt(qa)
        t = sq - sqa if sq <= sqa else (q - qa) / (2 * sqa)
        observed = (1 - phi(t + sqa)) / (1 - phi(t))
        expected = [(1 - phi(k + sqa)) / (1 - phi(k)) for k in (2, 1, 0, -1, -2)]
        return [observed, *expected][index] - level

    lo, hi = 1e-3, 256.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if cls(mid) > 0 else (lo, mid)
    return hi


@pytest.mark.parametrize("n,b", [(42, 38.0), (5, 3.0), (30, 45.0), (0, 3.0)])
def test_small_background_uncertainty_approaches_known_background(n, b):
    known = [known_background_limit(n, b, i) for i in range(6)]
    errors = []
    for sigma in (0.05, 0.005, 0.0005):
        errors.append(max(relative(v, k) for v, k in zip(values(counting.limits(n, b, sigma)), known)))
    # the nuisance correction vanishes as sigma_b**2: a factor 100 per decade
    assert all(90 < coarse / fine < 110 for coarse, fine in zip(errors, errors[1:]))
    assert errors[-1] < 1e-7


def test_poi_cap_too_small_reports_above_cap_not_a_root():
    full = counting.limits(42, 38.0, 5.0)
    capped = counting.limits(42, 38.0, 5.0, poi_cap=10.0)
    assert capped["limit_status"] == {"observed": "above_cap",
                                      "expected": ["resolved", "above_cap", "above_cap", "above_cap", "above_cap"]}
    assert capped["obs_limit_events"] is None
    assert capped["exp_limits_events"][1:] == [None] * 4
    assert relative(capped["exp_limits_events"][0], full["exp_limits_events"][0]) < 1e-12
    tiny = counting.limits(42, 38.0, 5.0, poi_cap=5.0)
    assert values(tiny) == [None] * 6
    assert tiny["limit_status"] == {"observed": "above_cap", "expected": ["above_cap"] * 5}
    # the status is evidenced by the CLs at the cap: above the level exactly on the above_cap curves
    for result, cap in ((capped, 10.0), (tiny, 5.0)):
        at_cap = [result["cls_at_cap"]["observed"], *result["cls_at_cap"]["expected"]]
        assert at_cap == cls_values(counting.cls_at(42, 38.0, 5.0, cap, poi_cap=cap))
        statuses = [result["limit_status"]["observed"], *result["limit_status"]["expected"]]
        assert [cls > 0.05 for cls in at_cap] == [s == "above_cap" for s in statuses]
    assert full["cls_at_cap"] is None


def test_non_monotone_cls_curve_is_rejected(monkeypatch):
    real = counting._cls
    top = 2.0 * max(values(counting.limits(42, 38.0, 5.0)))   # the monotonicity grid's upper end

    def bumped(model, mu, observed, asimov):
        cls = real(model, mu, observed, asimov)
        if 0.70 * top < mu < 0.80 * top:   # synthetic bump on the observed curve, below the level
            cls[0] += 0.01
        return cls

    monkeypatch.setattr(counting, "_cls", bumped)
    with pytest.raises(ContractError, match="monotonically"):
        counting.limits(42, 38.0, 5.0)


def test_observed_curve_has_no_rise_on_a_fine_grid():
    # The expected curves are monotone analytically; the observed curve is only grid-verified by
    # limits() (module docstring). This seeded survey checks 400 points per model, from 0 to three
    # times the largest finite root, for 400 random synthetic models (one raises ContractError).
    rng = random.Random(20260926)
    checked = rising = 0
    for _ in range(400):
        b = 10 ** rng.uniform(-1, 3.5)
        sigma = b * 10 ** rng.uniform(-2, 0.3)
        n = max(0, round(b + rng.gauss(0, 1) * (b + sigma * sigma) ** 0.5 * rng.uniform(0, 3)))
        try:
            result = counting.limits(n, b, sigma, poi_cap=1e6)
        except ContractError:
            continue
        top = 3 * max(v for v in values(result) if v is not None)
        model = counting._SingleBin(b, sigma)
        observed, asimov = counting._datasets(model, float(n))
        curve = [counting._cls(model, top * i / 400, observed, asimov)[0] for i in range(1, 401)]
        checked += 1
        rising += any(later > earlier for earlier, later in zip(curve, curve[1:]))
    assert checked == 399 and rising == 0


@pytest.mark.parametrize("model", [(0, 1e-3, 1e-2), (0, 0.5, 0.05), (0, 3.0, 1.0), (5, 3.0, 1.0),
                                   (263, 283.0, 24.0), (1000, 5.0, 50.0), (10000, 1e4, 1e2)])
def test_no_crossing_below_the_kernel_first_scan_point(model):
    # q~ and q~_A are at most 2 mu for a unit signal (module docstring), so at mu = 1e-3 every CLs
    # exceeds Phi(-(2 + sqrt(2e-3))) / Phi(-2) > 0.89: the kernel's below_scan cannot occur.
    bound = 0.5 * math.erfc((2 + math.sqrt(2e-3)) / math.sqrt(2)) / (0.5 * math.erfc(2 / math.sqrt(2)))
    assert bound > 0.89
    assert min(cls_values(counting.cls_at(*model, 1e-3))) > bound


@pytest.mark.parametrize("args", [(42, 38.0, 1e-200), (42, 38.0, 1e200), (42, 1e-200, 5.0), (42, 1e200, 5.0),
                                  (42, 5e-324, 5e-324)])
def test_extreme_inputs_raise_contract_error_not_arithmetic_errors(args):
    # finite positive inputs whose tau = b**2/sigma**2 or likelihood terms leave the float range
    with pytest.raises(ContractError):
        counting.limits(*args)
    files = {"workspace.json": json.dumps(family.counting_workspace(*args)).encode()}
    with pytest.raises(ContractError):
        counting.oracle_record(files, files)


@pytest.mark.parametrize("args", [(42, 1e150, 1e-10), (42, 1e-160, 1e10)])
def test_tau_outside_the_float_range_is_named(args):
    # b**2 / sigma**2 silently becomes inf or 0.0 here (no Python arithmetic exception)
    with pytest.raises(ContractError, match="finite positive"):
        counting.limits(*args)


def test_extreme_input_grid_never_escapes_contract_error():
    grid = [5e-324, 1e-300, 1e-150, 1e-10, 1.0, 42.0, 1e150, 1e300, 1.7e308]
    outcomes = set()
    for n in (0.0, 42.0, 1e300):
        for b in grid:
            for sigma in grid:
                try:
                    result = counting.limits(n, b, sigma)
                    outcomes.add(result["limit_status"]["observed"])
                except ContractError:
                    outcomes.add("ContractError")
    assert outcomes <= {"resolved", "above_cap", "ContractError"}


def test_luminosity_that_overflows_sigma_vis_is_rejected():
    files = family.variant_inputs("V2")["current"]
    tiny = {**files, "luminosity.json": json.dumps({**family.CERTIFIED, "luminosity_fb": 5e-324}).encode()}
    with pytest.raises(ContractError, match="overflows"):
        counting.oracle_record(tiny, files)


def test_limits_reject_invalid_arguments():
    for args, kwargs in [((-1, 38.0, 5.0), {}), ((42, 0.0, 5.0), {}), ((42, 38.0, 0.0), {}),
                         ((True, 38.0, 5.0), {}), ((42, float("nan"), 5.0), {}),
                         ((42, 38.0, 5.0), {"level": 1.0}), ((42, 38.0, 5.0), {"poi_cap": 0.0})]:
        with pytest.raises(ContractError):
            counting.limits(*args, **kwargs)


# --------------------------------------------------------------------------- cap-bounded models, cls_at
#
# WP12 task-bank models (revised design 2026-09-26, section 2 P3 and P6). The 2jl counts
# (n = 263, b = 283 +- 24 events) are transcribed from ATLAS arXiv:1605.03814, SR 2jl, and used
# in a derived single-bin gamma/Poisson approximation (derived_from_published); the POI range
# [0, 10] is a synthetic perturbation. The hv model (n = 73, b = 58.0 +- 7.0) is synthetic.
# Every expected number below was recomputed on 2026-09-26 (CPython 3.12.13, macOS arm64): the
# design values agree with the oracle to the half-unit of their last printed digit, and the
# CLs values with the test-side numeric-profile reference below.

PUBLIC_2JL = (263, 283.0, 24.0)
SYNTHETIC_HV = (73, 58.0, 7.0)
DESIGN_2JL_CLS_AT_10 = [0.60590601, 0.41145174, 0.55681585, 0.72556045, 0.88170610, 0.97254797]
DESIGN_HV_LIMITS = [34.01420, 11.58529, 15.60338, 21.78224, 30.59717, 41.57884]
# The numeric reference locates g_hat and mu_hat by golden section (argmax precision ~1e-8),
# which moves the Asimov data slightly; measured worst difference 7.5e-9, bound 5e-8.
NUMERIC_CLS_ATOL = 5e-8


def close_to_printed(value, printed, places):
    return abs(value - printed) <= 0.5 * 10.0 ** -places + 1e-12


def numeric_cls(n, b, sigma, mu, cap=256.0):
    """Test-side CLs at mu from golden-section profiles (independent of the closed forms)."""
    tau = b * b / (sigma * sigma)
    lo, hi = counting.GAMMA_BOUNDS

    def conditional(m, count, aux):
        g = golden_argmax(lambda g: log_likelihood(m, g, count, aux, b, tau), lo, hi)
        return log_likelihood(m, g, count, aux, b, tau)

    def qtilde(count, aux):
        mu_hat = golden_argmax(lambda m: conditional(m, count, aux), 0.0, cap)
        if mu_hat > mu:
            return 0.0
        return max(0.0, 2.0 * (conditional(mu_hat, count, aux) - conditional(mu, count, aux)))

    g0 = golden_argmax(lambda g: log_likelihood(0.0, g, n, tau, b, tau), lo, hi)
    q, qa = qtilde(n, tau), qtilde(g0 * b, g0 * tau)
    phi = statistics.NormalDist().cdf
    sq, sqa = math.sqrt(q), math.sqrt(qa)
    t = sq - sqa if sq <= sqa else (q - qa) / (2 * sqa)
    return [(1 - phi(t + sqa)) / (1 - phi(t))] + [(1 - phi(k + sqa)) / (1 - phi(k)) for k in (2, 1, 0, -1, -2)]


def test_public_2jl_at_cap_10_is_above_cap_on_every_curve():
    result = counting.limits(*PUBLIC_2JL, poi_cap=10.0)
    assert result["limit_status"] == {"observed": "above_cap", "expected": ["above_cap"] * 5}
    assert values(result) == [None] * 6
    at_cap = cls_values(result["cls_at_cap"])
    assert all(close_to_printed(v, d, 8) for v, d in zip(at_cap, DESIGN_2JL_CLS_AT_10)), at_cap
    assert all(cls > 0.05 for cls in at_cap)          # no crossing inside [0, 10]: S95 > 10 events
    # the uncapped limits all lie above the cap, as the status states
    assert all(v > 10.0 for v in values(counting.limits(*PUBLIC_2JL)))


def test_cls_at_workspace_reads_the_cap_and_matches_cls_at():
    workspace = family.counting_workspace(*PUBLIC_2JL, poi_cap=10.0)
    assert workspace["measurements"][0]["config"]["parameters"][0]["inits"] == [1]   # min(1, cap/2)
    result = counting.cls_at_workspace(workspace, 10.0)
    assert result == counting.cls_at(*PUBLIC_2JL, 10.0, poi_cap=10.0)
    assert result["poi_bounds"] == [0.0, 10.0] and result["mu"] == 10.0
    assert all(close_to_printed(v, d, 8) for v, d in zip(cls_values(result), DESIGN_2JL_CLS_AT_10))
    with pytest.raises(ContractError, match="POI range"):
        counting.cls_at_workspace(workspace, 10.5)


@pytest.mark.parametrize("model, mu, cap", [(PUBLIC_2JL, 10.0, 10.0), (PUBLIC_2JL, 43.0, 256.0),
                                            (SYNTHETIC_HV, 20.0, 256.0), (SYNTHETIC_HV, 34.0, 256.0),
                                            ((42, 38.0, 5.0), 5.0, 256.0)])
def test_cls_at_matches_numeric_profile_reference(model, mu, cap):
    ours = cls_values(counting.cls_at(*model, mu, poi_cap=cap))
    reference = numeric_cls(*model, mu, cap)
    assert max(abs(a - b) for a, b in zip(ours, reference)) <= NUMERIC_CLS_ATOL


def test_synthetic_hv_reference_values():
    result = counting.limits(*SYNTHETIC_HV)
    assert result["limit_status"] == {"observed": "resolved", "expected": ["resolved"] * 5}
    assert all(close_to_printed(v, d, 5) for v, d in zip(values(result), DESIGN_HV_LIMITS)), values(result)
    obs, median, plus1 = result["obs_limit_events"], result["exp_limits_events"][2], result["exp_limits_events"][3]
    # design margins: the swap moves the observed value by 36.0 % and the median by 56.2 %; the
    # nearest role confusion (observed vs +1 sigma) is 10.0 %
    assert round(relative(median, obs), 3) == 0.360 and round(relative(obs, median), 3) == 0.562
    assert round(relative(plus1, obs), 3) == 0.100


@pytest.mark.parametrize("model", [PUBLIC_2JL, SYNTHETIC_HV, (42, 38.0, 5.0)])
def test_cls_at_resolved_roots_equals_the_level(model):
    result = counting.limits(*model)
    for index, root in enumerate(values(result)):
        assert abs(cls_values(counting.cls_at(*model, root))[index] - 0.05) <= counting.CLS_RESIDUAL_ATOL


@pytest.mark.parametrize("model, cap", [(PUBLIC_2JL, 10.0), (PUBLIC_2JL, 256.0), (SYNTHETIC_HV, 256.0)])
def test_cls_at_is_monotone_and_ordered(model, cap):
    top = min(cap, 128.0)   # beyond ~2x the largest limit the tails approach float underflow
    grid = [counting.cls_at(*model, top * i / 100, poi_cap=cap) for i in range(1, 101)]
    curves = [cls_values(point) for point in grid]
    for index in range(6):
        assert all(later[index] < earlier[index] for earlier, later in zip(curves, curves[1:]))
    for point in curves:
        assert 0.0 < point[0] <= 1.0
        assert all(low < high for low, high in zip(point[1:], point[2:]))   # -2 sigma band lowest


def test_above_cap_status_flips_exactly_at_the_uncapped_root():
    uncapped = values(counting.limits(*PUBLIC_2JL))
    for cap in (10.0, 30.0, 40.0, 43.6, 43.7, 55.0, 80.0, 100.9, 101.0):
        result = counting.limits(*PUBLIC_2JL, poi_cap=cap)
        statuses = [result["limit_status"]["observed"], *result["limit_status"]["expected"]]
        assert statuses == ["resolved" if root <= cap else "above_cap" for root in uncapped]
        for value, root in zip(values(result), uncapped):
            assert value is None if root > cap else relative(value, root) < 1e-12   # cap-independent roots
        assert (result["cls_at_cap"] is None) == all(root <= cap for root in uncapped)


def test_above_cap_monotonicity_grid_spans_the_whole_poi_range(monkeypatch):
    # Synthetic CLs curves: curve 0 crosses the level at mu = 2; curves 1-5 stay above it on
    # (0, 100] but rise again on (60, 70). Only a grid reaching the cap sees that rise, which
    # would make "no crossing in (0, poi_cap]" unverified.
    def synthetic(model, mu, observed, asimov):
        bump = 0.05 if 60.0 < mu < 70.0 else 0.0
        return [0.1 / mu] + [0.9 - 0.001 * mu + bump] * 5

    monkeypatch.setattr(counting, "_cls", synthetic)
    with pytest.raises(ContractError, match="monotonically"):
        counting.limits(42, 38.0, 5.0, poi_cap=100.0)


@pytest.mark.parametrize("mu, kwargs", [(0.0, {}), (-1.0, {}), (257.0, {}), (10.5, {"poi_cap": 10.0}),
                                        (float("nan"), {}), (float("inf"), {}), (True, {}), ("10", {})])
def test_cls_at_rejects_mu_outside_the_poi_range(mu, kwargs):
    with pytest.raises(ContractError):
        counting.cls_at(*PUBLIC_2JL, mu, **kwargs)


def test_cls_at_extreme_inputs_raise_contract_error():
    for args in [(42, 38.0, 1e-200), (42, 1e200, 5.0), (42, 5e-324, 5e-324)]:
        with pytest.raises(ContractError):
            counting.cls_at(*args, 1.0)


def prefit_asimov_limits(n, b, sigma, level=0.05, cap=256.0):
    """Test-side limits under the pre-fit (nominal-nuisance, g = 1) Asimov convention.

    A known legitimate alternative to the oracle's conditional mu = 0 Asimov data: the design
    lists its values as convention_values (verdict unresolved), never as the oracle value.
    """
    model = counting._SingleBin(b, sigma)
    observed = (float(n), model.tau, model.free_fit(float(n), model.tau))
    asimov = (model.b, model.tau, model.free_fit(model.b, model.tau))
    roots = []
    for index in range(6):
        lo, hi = 1e-6, cap
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if counting._cls(model, mid, observed, asimov)[index] > level else (lo, mid)
        roots.append(hi)
    return roots


def test_prefit_asimov_convention_values():
    # design section 2 P3/P6 and 7.1: (model, observed, median) under the pre-fit convention
    shifts = {}
    for label, model in {"2jl": PUBLIC_2JL, "hv": SYNTHETIC_HV, "lf-prior": (42, 38.0, 5.0),
                         "lf-v1": (42, 44.0, 5.0)}.items():
        pre, post = prefit_asimov_limits(*model), values(counting.limits(*model))
        shifts[label] = (round(100 * (pre[0] / post[0] - 1), 2), round(100 * (pre[3] / post[3] - 1), 1))
        if label == "2jl":
            assert close_to_printed(pre[0], 43.93693, 5) and close_to_printed(pre[3], 56.25982, 5)
        if label == "hv":
            assert close_to_printed(pre[3], 20.62317, 5)
    assert shifts == {"2jl": (0.65, 2.5), "hv": (-0.41, -5.3), "lf-prior": (-0.44, -1.9), "lf-v1": (0.25, 0.8)}
    # lf-c collision: the pre-fit median at the current 117.6 fb^-1 lies 0.066 % from the stale
    # median at 120.0 fb^-1 (a fault value and a convention value within tolerance of each other)
    prefit_current = prefit_asimov_limits(42, 38.0, 5.0)[3] / 117.6
    stale = counting.limits(42, 38.0, 5.0)["exp_limits_events"][2] / 120.0
    assert close_to_printed(prefit_current, 0.1372986, 7) and close_to_printed(stale, 0.1372085, 7)
    assert round(100 * relative(prefit_current, stale), 3) == 0.066


def test_convention_limits_match_the_test_side_prefit_helper():
    """The oracle's convention helper (WP12 plan step 7: the family builders list convention_values) agrees with
    the independent test-side bisection above, and its record names the convention."""
    for model in (PUBLIC_2JL, SYNTHETIC_HV, (42, 38.0, 5.0), (42, 44.0, 5.0)):
        expected = prefit_asimov_limits(*model)
        result = counting.convention_limits(*model)
        assert all(relative(a, b) < 1e-9 for a, b in zip([result["obs_limit_events"], *result["exp_limits_events"]],
                                                          expected))
        assert result["method"]["estimand"] == "convention_value_prefit_asimov"
        assert "nominal nuisance" in result["method"]["asimov"]
    capped = counting.convention_limits(*PUBLIC_2JL, poi_cap=10.0)
    assert capped["limit_status"]["observed"] == "above_cap" and capped["obs_limit_events"] is None
    assert counting.limits(*PUBLIC_2JL)["method"]["asimov"] == (
        "background-only (mu = 0) at the conditional mu = 0 fit to observed data")
    with pytest.raises(ContractError, match="only prefit_asimov"):
        counting.convention_limits(*PUBLIC_2JL, convention="toy_cls")


def test_oracle_record_carries_cls_at_cap_and_an_optional_prior():
    files = {"workspace.json": json.dumps(family.counting_workspace(263, 283, 24, poi_cap=10.0)).encode()}
    record = counting.oracle_record(files)
    assert record["prior"] is None
    at_cap, direct = record["current"]["cls_at_cap"], counting.cls_at(263, 283, 24, 10.0, poi_cap=10.0)
    assert at_cap["observed"] == float(f"{direct['observed']:.9e}") == 0.60590601
    assert at_cap["expected"] == [float(f"{v:.9e}") for v in direct["expected"]]
    inputs = family.variant_inputs("V0")
    lf = counting.oracle_record(inputs["current"], inputs["prior"])
    assert lf["current"]["cls_at_cap"] is None and lf["prior"]["cls_at_cap"] is None


# --------------------------------------------------------------------------- workspace parsing

def scoped_workspace():
    return family.counting_workspace(42, 38.0, 5.0)


def test_parse_counting_workspace_round_trip():
    assert counting.parse_counting_workspace(scoped_workspace()) == {
        "n_obs": 42, "background": 38.0, "background_uncertainty": 5.0, "poi_cap": 256.0}


MUTATIONS = {
    "extra top-level key": lambda w: w.update(extra=1),
    "missing measurements": lambda w: w.pop("measurements"),
    "version": lambda w: w.update(version="1.0.1"),
    "second channel": lambda w: w["channels"].append(copy.deepcopy(w["channels"][0])),
    "extra sample": lambda w: w["channels"][0]["samples"].append(copy.deepcopy(w["channels"][0]["samples"][1])),
    "signal not unit": lambda w: w["channels"][0]["samples"][0].update(data=[2.0]),
    "signal modifier type": lambda w: w["channels"][0]["samples"][0]["modifiers"][0].update(type="shapefactor"),
    "background modifier type": lambda w: w["channels"][0]["samples"][1]["modifiers"][0].update(type="staterror"),
    "extra background modifier": lambda w: w["channels"][0]["samples"][1]["modifiers"].append(
        {"name": "norm", "type": "normsys", "data": {"hi": 1.1, "lo": 0.9}}),
    "zero uncertainty": lambda w: w["channels"][0]["samples"][1]["modifiers"][0].update(data=[0.0]),
    "two observed bins": lambda w: w["observations"][0].update(data=[42, 1]),
    "boolean count": lambda w: w["observations"][0].update(data=[True]),
    "negative count": lambda w: w["observations"][0].update(data=[-1]),
    "measurement name": lambda w: w["measurements"][0].update(name="other"),
    "poi name": lambda w: w["measurements"][0]["config"].update(poi="sigma"),
    "nonzero lower bound": lambda w: w["measurements"][0]["config"]["parameters"][0].update(bounds=[[1, 256.0]]),
    "inits": lambda w: w["measurements"][0]["config"]["parameters"][0].update(inits=[0.5]),
    "extra parameter field": lambda w: w["measurements"][0]["config"]["parameters"][0].update(fixed=False),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_parse_counting_workspace_rejects_other_structures(name):
    workspace = scoped_workspace()
    MUTATIONS[name](workspace)
    with pytest.raises(ContractError):
        counting.parse_counting_workspace(workspace)


# --------------------------------------------------------------------------- oracle record

def test_oracle_record_sides_and_conversion():
    inputs = family.variant_inputs("V2")
    record = counting.oracle_record(inputs["current"], inputs["prior"])
    assert record["schema_version"] == 1 and record["provisional"] is True
    current, prior = record["current"], record["prior"]
    assert current["inputs"] == {name: sha256_bytes(data) for name, data in inputs["current"].items()}
    assert current["luminosity_fb"] == 117.6 and prior["luminosity_fb"] == 120.0
    raw = counting.limits(42, 38.0, 5.0)
    assert current["obs_limit_events"] == prior["obs_limit_events"]
    assert relative(current["obs_limit_events"], raw["obs_limit_events"]) < 1e-9
    assert relative(current["sigma_vis_obs_fb"], raw["obs_limit_events"] / 117.6) < 1e-9
    assert relative(prior["sigma_vis_exp_fb"][2], raw["exp_limits_events"][2] / 120.0) < 1e-9
    assert canonical_bytes(record) == canonical_bytes(counting.oracle_record(inputs["current"], inputs["prior"]))


def test_oracle_record_without_luminosity_has_null_cross_sections():
    inputs = family.variant_inputs("V3")
    current = counting.oracle_record(inputs["current"], inputs["prior"])["current"]
    assert current["luminosity_fb"] is None
    assert current["sigma_vis_obs_fb"] is None and current["sigma_vis_exp_fb"] == [None] * 5
    assert current["limit_status"]["observed"] == "resolved" and current["obs_limit_events"] > 0


def test_oracle_record_unresolved_limit_is_null():
    files = {"workspace.json": json.dumps(family.counting_workspace(42, 38.0, 5.0, poi_cap=10.0)).encode(),
             "luminosity.json": json.dumps(family.PRELIMINARY).encode()}
    side = counting.oracle_record(files, files)["current"]
    assert side["obs_limit_events"] is None and side["sigma_vis_obs_fb"] is None
    assert side["sigma_vis_exp_fb"][0] is not None and side["sigma_vis_exp_fb"][1:] == [None] * 4


def test_oracle_record_rejects_malformed_inputs():
    good = family.variant_inputs("V2")["current"]
    lumi = json.loads(good["luminosity.json"])
    bad_cases = [
        {**good, "notes.txt": b"x"},
        {name: data for name, data in good.items() if name != "workspace.json"},
        {**good, "title.txt": "text not bytes"},
        {**good, "workspace.json": b'{"version": "1.0.0", "version": "1.0.0"}'},
        {**good, "workspace.json": b"\xff\xfe"},
        {**good, "luminosity.json": json.dumps({**lumi, "extra": 1}).encode()},
        {**good, "luminosity.json": json.dumps({**lumi, "luminosity_fb": 0}).encode()},
        {**good, "luminosity.json": b'{"luminosity_fb": NaN, "status": "x", "source": "y"}'},
    ]
    for files in bad_cases:
        with pytest.raises(ContractError):
            counting.oracle_record(files, good)


# --------------------------------------------------------------------------- independence

def test_counting_module_imports_only_stdlib_and_canonical():
    tree = ast.parse(COUNTING_SOURCE.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert modules <= {"__future__", "json", "math", "governance"}
    script = ("import sys; sys.path[:0] = [sys.argv[1]]; import governance.oracle.counting as c; "
              "c.limits(42, 38.0, 5.0); print(sorted(m for m in ('pyhf', 'numpy', 'scipy', 'ravel') "
              "if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", script, str(ROOT / "benchmarks")],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


# --------------------------------------------------------------------------- agreement

@pytest.fixture(scope="module")
def pyhf_module():
    pyhf = pytest.importorskip("pyhf", reason="pyhf is not installed; agreement cannot be tested")
    pytest.importorskip("scipy", reason="scipy is not installed; stock pyhf roots need brentq")
    if pyhf.__version__ != "0.7.6":
        pytest.skip(f"oracle definitions are pinned to pyhf 0.7.6, found {pyhf.__version__}")
    saved = pyhf.get_backend()
    yield pyhf
    pyhf.set_backend(*saved)


def pyhf_model(pyhf, n, b, sigma, cap=256.0):
    workspace = pyhf.Workspace(family.counting_workspace(n, b, sigma, poi_cap=cap))
    model = workspace.model()
    return model, workspace.data(model)


def test_gamma_bounds_match_installed_pyhf(pyhf_module):
    model, _ = pyhf_model(pyhf_module, 42, 38.0, 5.0)
    bounds = model.config.suggested_bounds()[model.config.par_slice("uncorr_bkguncrt")]
    assert [tuple(map(float, pair)) for pair in bounds] == [counting.GAMMA_BOUNDS]


@pytest.fixture(scope="module")
def stock_pyhf_limits(pyhf_module):
    """Roots of stock pyhf 0.7.6 hypotest CLs curves (scipy optimizer, tolerance 1e-9)."""
    from scipy.optimize import brentq
    pyhf = pyhf_module
    pyhf.set_backend("numpy", pyhf.optimize.scipy_optimizer(tolerance=1e-9), precision="64b")
    results = {}
    for label, (n, b, sigma, cap) in FIXTURES.items():
        model, data = pyhf_model(pyhf, n, b, sigma, cap)
        cache = {}

        def cls(mu):
            if mu not in cache:
                observed, expected = pyhf.infer.hypotest(mu, data, model, test_stat="qtilde",
                                                         return_expected_set=True)
                cache[mu] = [float(observed), *map(float, expected)]
            return cache[mu]

        roots = []
        for column in range(6):
            f = lambda mu: cls(mu)[column] - 0.05
            hi = 1.0
            while f(hi) > 0:
                hi *= 2.0
            roots.append(brentq(f, hi / 2.0 if hi > 1.0 else 1e-2, hi, xtol=1e-12, rtol=1e-12, maxiter=200))
        results[label] = roots
    return results


@pytest.fixture(scope="module")
def kernel_limits(pyhf_module):
    """ravel.physics.pyhf_exclude.compute with the scoped worker's exact backend settings."""
    pyhf = pyhf_module
    try:
        from ravel.physics.pyhf_exclude import compute, robust_optimizer
    except ImportError as exc:
        pytest.skip(f"ravel kernel unavailable: {exc}")
    results = {}
    for label, (n, b, sigma, cap) in FIXTURES.items():
        model, data = pyhf_model(pyhf, n, b, sigma, cap)
        pyhf.set_backend("numpy", robust_optimizer(tolerance=1e-9), precision="64b")
        with contextlib.redirect_stderr(io.StringIO()):
            results[label] = compute(model, data, poi_cap=cap, diagnostic_record={})
    # the prior with a cap below most limits: the kernel's status vocabulary for "above the cap"
    model, data = pyhf_model(pyhf, 42, 38.0, 5.0, 10.0)
    pyhf.set_backend("numpy", robust_optimizer(tolerance=1e-9), precision="64b")
    with contextlib.redirect_stderr(io.StringIO()):
        results["synthetic-family-prior-capped-10"] = compute(model, data, poi_cap=10.0, diagnostic_record={})
    return results


def test_agreement_with_stock_pyhf(stock_pyhf_limits):
    worst = {}
    for label, stock in stock_pyhf_limits.items():
        ours = values(fixture_limits(label))
        worst[label] = max(relative(a, b) for a, b in zip(ours, stock))
    print("stock pyhf worst relative difference per fixture:", json.dumps(worst))
    assert max(worst.values()) <= STOCK_PYHF_RTOL, worst


def test_agreement_with_ravel_kernel(kernel_limits):
    worst = {}
    for label in FIXTURES:
        result = kernel_limits[label]
        assert result["limit_status"] == {"observed": "resolved", "expected": ["resolved"] * 5}
        ours = values(fixture_limits(label))
        kernel = [result["obs_limit"], *result["exp_limits"]]
        worst[label] = max(relative(a, b) for a, b in zip(ours, kernel))
    print("kernel worst relative difference per fixture:", json.dumps(worst))
    assert max(worst.values()) <= KERNEL_RTOL, worst


def test_kernel_status_vocabulary_maps_to_the_oracle(kernel_limits):
    kernel = kernel_limits["synthetic-family-prior-capped-10"]
    ours = counting.limits(42, 38.0, 5.0, poi_cap=10.0)
    mapped = {"observed": counting.KERNEL_LIMIT_STATUS[ours["limit_status"]["observed"]],
              "expected": [counting.KERNEL_LIMIT_STATUS[s] for s in ours["limit_status"]["expected"]]}
    assert kernel["limit_status"] == mapped
    assert mapped["expected"] == ["resolved"] + ["above_scan"] * 4
    # the kernel reports the cap as a bound where the oracle reports null
    assert kernel["obs_limit"] == 10.0 and ours["obs_limit_events"] is None
    assert relative(ours["exp_limits_events"][0], kernel["exp_limits"][0]) <= KERNEL_RTOL
