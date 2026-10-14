"""Binned Poisson likelihood with per-bin constrained nuisances, scans and crossings."""
import math

import numpy as np
import pytest
from scipy import optimize

from ravel.physics.inference import counting, intervals


def cowan_z(s, b, sigma):
    # Asimov discovery significance with a Poisson-constrained background uncertainty.
    term1 = (s + b) * math.log((s + b) * (b + sigma ** 2) / (b ** 2 + (s + b) * sigma ** 2))
    term2 = b ** 2 / sigma ** 2 * math.log(1 + sigma ** 2 * s / (b * (b + sigma ** 2)))
    return math.sqrt(2 * (term1 - term2))


def single(n, b, db, s, form='gaussian-linear', floor='nonnegative'):
    channel = counting.Channel('A', [n], [b], [db], form=form, floor=floor)
    return channel, counting.Likelihood([channel], counting.Signal.linear('mu', {'A': [s]}))


@pytest.mark.parametrize('n,b,db,s,mu', [(7, 5.0, 1.5, 2.0, 1.0), (0, 3.0, 1.0, 1.0, 0.5), (12, 4.0, 2.5, 3.0, 2.0),
                                          (3, 6.0, 0.4, 1.0, 0.0)])
def test_gaussian_linear_profile_matches_brute_force(n, b, db, s, mu):
    _, likelihood = single(n, b, db, s)
    def objective(bp):
        m = bp + mu * s
        return 2 * (m - n + (n * math.log(n / m) if n else 0)) + (bp - b) ** 2 / db ** 2
    brute = optimize.minimize_scalar(objective, bounds=(1e-12, b + 20 * db), method='bounded',
                                     options={'xatol': 1e-12}).fun
    assert likelihood.twice_nll({'mu': mu}) == pytest.approx(brute, rel=1e-7, abs=1e-8)


@pytest.mark.parametrize('n,b,db,s,mu', [(7, 5.0, 1.5, 2.0, 1.0), (2, 3.0, 1.0, 1.0, 0.5), (9, 4.0, 2.0, -1.0, 1.0)])
def test_poisson_gamma_profile_matches_brute_force(n, b, db, s, mu):
    _, likelihood = single(n, b, db, s, form='poisson-gamma')
    tau = (b / db) ** 2
    def objective(gamma):
        m, a = gamma * b + mu * s, gamma * tau
        if m <= 0:
            return 1e300
        return 2 * (m - n + (n * math.log(n / m) if n else 0)) + 2 * (a - tau + tau * math.log(tau / a))
    brute = optimize.minimize_scalar(objective, bounds=(1e-9, 20), method='bounded', options={'xatol': 1e-12}).fun
    assert likelihood.twice_nll({'mu': mu}) == pytest.approx(brute, rel=1e-7, abs=1e-8)


@pytest.mark.parametrize('n,b,db,s,mu', [(7, 5.0, 1.5, 2.0, 1.0), (1, 3.0, 1.0, 1.0, 0.5)])
def test_lognormal_profile_matches_brute_force(n, b, db, s, mu):
    _, likelihood = single(n, b, db, s, form='lognormal')
    a = math.log(1 + db / b)
    def objective(theta):
        m = b * math.exp(a * theta) + mu * s
        return 2 * (m - n + (n * math.log(n / m) if n else 0)) + theta ** 2
    brute = optimize.minimize_scalar(objective, bounds=(-8, 8), method='bounded', options={'xatol': 1e-10}).fun
    assert likelihood.twice_nll({'mu': mu}) == pytest.approx(brute, rel=1e-6, abs=1e-7)


@pytest.mark.parametrize('s,b,sigma', [(5.0, 10.0, 2.0), (2.0, 1.0, 0.5), (20.0, 100.0, 15.0)])
def test_asimov_discovery_significance_matches_cowan_formula(s, b, sigma):
    channel = counting.Channel('A', [s + b], [b], [sigma], form='poisson-gamma')
    likelihood = counting.Likelihood([channel], counting.Signal.linear('mu', {'A': [s]}))
    result = counting.discovery(likelihood, 'mu', null=0.0, start=1.0, bounds=(0.0, 10.0))
    assert result['significance'] == pytest.approx(cowan_z(s, b, sigma), rel=1e-6)
    # Without uncertainty: Z = sqrt(2((s+b)ln(1+s/b) - s)).
    exact = counting.Likelihood([counting.Channel('A', [s + b], [b], [0.0], form='none')],
                                counting.Signal.linear('mu', {'A': [s]}))
    z0 = counting.discovery(exact, 'mu', null=0.0, start=1.0, bounds=(0.0, 10.0))['significance']
    assert z0 == pytest.approx(math.sqrt(2 * ((s + b) * math.log(1 + s / b) - s)), rel=1e-7)


def test_two_sided_interval_without_nuisances_is_analytic():
    n, b, s0 = 9.0, 4.0, 2.0
    likelihood = counting.Likelihood([counting.Channel('A', [n], [b], [0.0], form='none')],
                                     counting.Signal.linear('mu', {'A': [s0]}))
    scan = counting.scan_1d(likelihood, 'mu', np.linspace(-1.5, 12, 271), domain=(None, None))
    assert scan['best_fit']['mu'] == pytest.approx((n - b) / s0, abs=1e-6)
    region = intervals.allowed_regions(scan['grid'], scan['delta'], 1.0, scan['refine'], domain=(None, None))
    assert region['status'] == 'resolved' and len(region['intervals']) == 1
    lo, hi = region['intervals'][0]['low']['value'], region['intervals'][0]['high']['value']
    f = lambda mu: 2 * ((mu * s0 + b) - n - n * math.log((mu * s0 + b) / n)) - 1.0
    assert f(lo) == pytest.approx(0, abs=1e-7) and f(hi) == pytest.approx(0, abs=1e-7)
    assert lo < (n - b) / s0 < hi


def test_combination_sums_log_likelihoods_across_experiments():
    a = counting.Channel('atlas', [5, 3], [4.0, 2.0], [1.0, 0.5])
    c = counting.Channel('cms', [7], [6.0], [2.0])
    templates = {'atlas': [1.0, 0.5], 'cms': [0.8]}
    signal = counting.Signal.power('g', reference=1.0, power=4, templates=templates)
    both = counting.Likelihood([a, c], signal)
    only_a = counting.Likelihood([a], counting.Signal.power('g', reference=1.0, power=4, templates={'atlas': templates['atlas']}))
    only_c = counting.Likelihood([c], counting.Signal.power('g', reference=1.0, power=4, templates={'cms': templates['cms']}))
    for g in (0.0, 0.7, 1.3):
        assert both.twice_nll({'g': g}) == pytest.approx(only_a.twice_nll({'g': g}) + only_c.twice_nll({'g': g}))
    assert both.per_channel({'g': 1.1}).keys() == {'atlas', 'cms'}


def test_power_scaling_crossing_is_bracketed_and_verified():
    channel = counting.Channel('A', [3, 2, 1], [3.5, 2.0, 1.2], [0.7, 0.4, 0.3])
    signal = counting.Signal.power('g', reference=1.0, power=4, templates={'A': [2.0, 1.0, 0.5]})
    likelihood = counting.Likelihood([channel], signal)
    scan = counting.scan_1d(likelihood, 'g', np.linspace(0, 3, 301), domain=(0.0, None))
    region = intervals.allowed_regions(scan['grid'], scan['delta'], 4.0, scan['refine'], domain=(0.0, None))
    interval = region['intervals'][0]
    assert interval['low']['status'] == 'domain_boundary' and interval['low']['value'] == 0.0
    high = interval['high']
    assert high['status'] == 'resolved' and high['bracket'][0] < high['value'] < high['bracket'][1]
    assert scan['refine'](high['value']) == pytest.approx(4.0, abs=1e-6)


def test_unbracketed_crossing_is_refused():
    channel = counting.Channel('A', [3], [3.5], [0.7])
    likelihood = counting.Likelihood([channel], counting.Signal.power('g', reference=1.0, power=4, templates={'A': [2.0]}))
    scan = counting.scan_1d(likelihood, 'g', np.linspace(0, 0.3, 31), domain=(0.0, None))
    region = intervals.allowed_regions(scan['grid'], scan['delta'], 4.0, scan['refine'], domain=(0.0, None))
    edge = region['intervals'][0]['high']
    assert edge['status'] == 'beyond_scan' and edge['value'] is None and edge['scan_edge'] == pytest.approx(0.3)
    assert region['status'] == 'unresolved'


def test_disjoint_regions_and_one_sided_statistic():
    grid = np.linspace(-3, 3, 601)
    f = lambda x: (x * x - 1.0) ** 2 * 4.0  # minima at -1 and +1, Delta(0) = 4
    region = intervals.allowed_regions(grid, f(grid), 1.0, f, domain=(None, None))
    assert len(region['intervals']) == 2 and region['status'] == 'resolved'
    one = intervals.one_sided(grid, (grid - 0.5) ** 2, best=0.5)
    assert np.all(one[grid < 0.5] == 0) and one[-1] == pytest.approx(6.25)


def test_inputs_are_checked():
    with pytest.raises(ValueError):
        counting.Channel('A', [1, 2], [1.0], [0.1])
    with pytest.raises(ValueError):
        counting.Channel('A', [-1], [1.0], [0.1])
    with pytest.raises(ValueError):
        counting.Channel('A', [1], [1.0], [0.1], form='made-up')
    with pytest.raises(ValueError):
        counting.Likelihood([counting.Channel('A', [1], [1.0], [0.1])], counting.Signal.linear('mu', {'B': [1.0]}))
