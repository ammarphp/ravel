"""Correlated differential-measurement likelihood: covariance laws, signed polynomial signals, toys."""
import numpy as np
import pytest

from ravel.physics.inference import applicability, differential, intervals

REF = np.array([10.0, 6.0, 3.0])
SYS = np.array([[1.0, 0.3, 0.1], [0.3, 0.8, 0.2], [0.1, 0.2, 0.5]])
STAT = np.diag([0.6, 0.4, 0.3])
BKG = np.diag([0.05, 0.05, 0.05])


def components():
    return [{'name': 'systematic', 'matrix': SYS, 'law': 'ratio'},
            {'name': 'statistical', 'matrix': STAT, 'law': 'sqrt-ratio'},
            {'name': 'background', 'matrix': BKG, 'law': 'fixed'}]


def model(measured, terms, **extra):
    return differential.Model(measured=np.asarray(measured, float), reference=REF, terms=terms,
                              components=components(), parameters=['kappa'], **extra)


def test_reference_chi2_reproduces_the_published_formula():
    y = np.array([10.5, 5.6, 3.4])
    m = model(y, [{'powers': {'kappa': 2}, 'values': np.array([1.0, 0.5, 0.2])}], objective='chi2')
    C = SYS + STAT + BKG
    r = y - REF
    assert m.twice_nll({'kappa': 0.0}) == pytest.approx(float(r @ np.linalg.solve(C, r)))


def test_prediction_dependent_covariance_matches_hand_computation():
    term = np.array([2.0, -1.0, 0.6])
    m = model(REF, [{'powers': {'kappa': 2}, 'values': term}])
    kappa = 0.7
    R = (REF + kappa ** 2 * term) / REF
    expected = np.outer(R, R) * SYS + np.sqrt(np.outer(R, R)) * STAT + BKG
    assert np.allclose(m.covariance({'kappa': kappa}), expected)
    gaussian = model(REF, [{'powers': {'kappa': 2}, 'values': term}], objective='gaussian')
    pred = REF + kappa ** 2 * term
    r = REF - pred
    value = r @ np.linalg.solve(expected, r) + np.linalg.slogdet(expected)[1]
    assert gaussian.twice_nll({'kappa': kappa}) == pytest.approx(value)


def test_linear_nuisances_are_profiled_exactly():
    y = np.array([11.0, 6.5, 2.7])
    terms = [{'powers': {'kappa': 2}, 'values': np.array([1.0, 0.5, 0.2])}]
    nuisances = [{'name': 'theory', 'applies_to': 'reference', 'relative': np.array([0.05, 0.05, 0.05])},
                 {'name': 'k_interference', 'applies_to': 'term:0', 'relative': np.array([0.2, 0.2, 0.2])}]
    m = model(y, terms, nuisances=nuisances, objective='chi2')
    from scipy import optimize
    kappa = 0.8
    def full(nu):
        pred = REF + kappa ** 2 * terms[0]['values'] + nu[0] * 0.05 * REF + nu[1] * 0.2 * kappa ** 2 * terms[0]['values']
        C = m.covariance({'kappa': kappa})
        r = y - pred
        return r @ np.linalg.solve(C, r) + nu @ nu
    brute = optimize.minimize(full, np.zeros(2), method='BFGS', options={'gtol': 1e-10}).fun
    assert m.twice_nll({'kappa': kappa}) == pytest.approx(brute, rel=1e-8)
    fitted = m.profile_nuisances({'kappa': kappa})
    assert set(fitted) == {'theory', 'k_interference'}


def test_non_spd_and_nonfinite_inputs_are_refused():
    bad = [{'name': 'systematic', 'matrix': -SYS, 'law': 'fixed'}]
    m = differential.Model(measured=REF, reference=REF, terms=[{'powers': {'kappa': 2}, 'values': np.ones(3)}],
                           components=bad, parameters=['kappa'])
    point = m.evaluate({'kappa': 0.0})
    assert point['status'] == 'not_positive_definite' and point['twice_nll'] is None
    with pytest.raises(ValueError, match='finite'):
        model(REF, [{'powers': {'kappa': 2}, 'values': np.array([1.0, np.nan, 0.0])}])
    with pytest.raises(ValueError):
        differential.Model(measured=REF, reference=REF, terms=[], components=[
            {'name': 'x', 'matrix': SYS[:2, :2], 'law': 'fixed'}], parameters=['kappa'])


def test_destructive_interference_gives_disjoint_allowed_regions():
    # Delta = kappa^2 I + kappa^4 S with I = -2 S: the prediction returns to the reference at kappa^2 = 2.
    S = np.array([3.0, 1.8, 0.9])
    terms = [{'powers': {'kappa': 2}, 'values': -2 * S}, {'powers': {'kappa': 4}, 'values': S}]
    m = model(REF, terms, objective='chi2')
    scan = m.scan_1d('kappa', np.linspace(0, 2.0, 401), domain=(0.0, None))
    region = intervals.allowed_regions(scan['grid'], scan['delta'], 1.0, scan['refine'], domain=(0.0, None))
    assert len(region['intervals']) == 2 and region['status'] == 'resolved'
    second = region['intervals'][1]
    assert second['low']['value'] < np.sqrt(2) < second['high']['value']
    assert np.all(scan['delta'] >= -1e-12)
    assert scan['delta_to_reference'][0] == pytest.approx(0.0)


def test_gaussian_toy_coverage_on_a_three_bin_model():
    rng = np.random.default_rng(11)
    C = SYS + STAT + BKG
    signal = np.array([1.0, 0.6, 0.3])
    truth = 1.0
    covered, trials = 0, 300
    L = np.linalg.cholesky(C)
    grid = np.linspace(-3, 5, 161)
    for _ in range(trials):
        y = REF + truth * signal + L @ rng.normal(size=3)
        m = differential.Model(measured=y, reference=REF, terms=[{'powers': {'mu': 1}, 'values': signal}],
                               components=[{'name': 'total', 'matrix': C, 'law': 'fixed'}], parameters=['mu'],
                               objective='chi2')
        scan = m.scan_1d('mu', grid, domain=(None, None))
        if scan['refine'](truth) <= 1.0:
            covered += 1
    assert abs(covered / trials - 0.6827) < 0.08


def test_neyman_toys_match_asymptotics_for_a_linear_gaussian_model():
    C = SYS + STAT + BKG
    signal = np.array([1.0, 0.6, 0.3])
    m = differential.Model(measured=REF + 0.5 * signal, reference=REF, terms=[{'powers': {'mu': 1}, 'values': signal}],
                           components=[{'name': 'total', 'matrix': C, 'law': 'fixed'}], parameters=['mu'],
                           objective='chi2')
    grid = np.linspace(-6, 7, 131)
    toys = m.toys('mu', grid, points=[0.5, 3.0], n=400, seed=5, method='neyman')
    by_point = {round(row['value'], 6): row for row in toys['points']}
    assert by_point[0.5]['p_value'] > 0.9
    # Delta at mu=3 is asymptotically chi2(1); toy p-value agrees within statistics.
    from scipy import stats
    delta = m.scan_1d('mu', grid)['refine'](3.0)
    assert abs(by_point[3.0]['p_value'] - stats.chi2.sf(delta, 1)) < 0.05
    assert toys['n_toys'] == 400 and toys['seed'] == 5


def test_unfolding_guard_flags_large_relative_deviations():
    S = np.array([5.0, 0.6, 0.3])
    m = model(REF, [{'powers': {'kappa': 2}, 'values': S}])
    guard = applicability.unfolding_guard(m, 'kappa', np.linspace(0, 2, 21),
                                          {'max_relative_deviation': 0.5, 'citation': 'stress test table'})
    assert guard['fires'] and guard['first_flagged_value'] == pytest.approx(1.1)
    with pytest.raises(ValueError, match='citation'):
        applicability.unfolding_guard(m, 'kappa', np.linspace(0, 2, 21), {'max_relative_deviation': 0.5})


def test_interference_k_factor_needs_a_declared_uncertainty():
    terms = [{'powers': {'kappa': 2}, 'values': np.ones(3), 'kind': 'interference',
              'scale': {'value': 1.5, 'origin': 'cited', 'citation': 'higher-order calculation'}}]
    findings = applicability.k_factor_policy(terms, nuisances=[])
    assert findings and findings[0]['finding'] == 'unconstrained_interference_k_factor'
    covered = applicability.k_factor_policy(terms, nuisances=[{'name': 'k', 'applies_to': 'term:0', 'relative': 0.3}])
    assert covered == []
    with pytest.raises(ValueError, match='citation'):
        applicability.k_factor_policy([{**terms[0], 'scale': {'value': 1.5, 'origin': 'cited'}}], nuisances=[])


def test_interpretation_traps_load():
    traps = applicability.interpretation_traps()
    ids = {t['id'] for t in traps}
    assert {'landau-yang', 'cp-odd-continuum-interference', 'cp-even-cp-odd-interference-in-even-observables',
            'signed-weight-normalisation', 'interference-k-factor', 'unfolding-validity'} <= ids
    assert all(t['statement'] and t['check'] for t in traps)
