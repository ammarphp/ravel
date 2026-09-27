"""Independent counting oracle: definitions, metamorphic checks and pyhf/kernel agreement.

Every fixture here is a SYNTHETIC development input (software tests, not physics results
or agent outcomes). Agreement tests skip when pyhf 0.7.6 or the ravel kernel is unavailable.
"""
import ast
import contextlib
import copy
import io
import json
import math
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

# Synthetic fixtures (n_obs, background, background_uncertainty, poi_cap): the family's distinct
# prior/current workspaces plus four extra cases (the public 2jl counts, a low-count excess, a
# loosely constrained background, and a large excess over a tiny, loosely constrained
# background whose conditional mu = 0 fit, and so the Asimov data, sit at the shapesys upper
# bound gamma = 10).
FIXTURES = {
    "synthetic-family-prior": (42, 38.0, 5.0, 256.0),
    "synthetic-family-V1-current": (42, 44.0, 5.0, 256.0),
    "synthetic-public-2jl": (263, 283.0, 24.0, 256.0),
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
