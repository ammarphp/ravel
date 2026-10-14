"""Gram-matrix amplitude basis: exact post-hoc recombination and block covariance."""
import math

import numpy as np
import pytest

from ravel.physics import amplitude_basis as ab

MEMBERS = ['continuum', 'scalar_bottom', 'scalar_top', 'pseudoscalar_top']


def _random_amplitudes(rng, n, helicities=16, k=len(MEMBERS)):
    shape = (n, helicities, k)
    return rng.normal(size=shape) + 1j * rng.normal(size=shape)


def _hypotheses():
    return [
        {'id': 'continuum-only', 'constant': {'continuum': 1}, 'states': []},
        {'id': 'light', 'constant': {'continuum': 1}, 'states': [
            {'mass_gev': 125.0, 'width_gev': 0.0041, 'propagator': 'fixed-width',
             'couplings': {'scalar_bottom': 1, 'scalar_top': 1}}]},
        {'id': 'mixed', 'constant': {'continuum': 1}, 'states': [
            {'mass_gev': 125.0, 'width_gev': 0.0041, 'propagator': 'fixed-width',
             'couplings': {'scalar_bottom': 0.85, 'scalar_top': 0.85}},
            {'mass_gev': 600.0, 'width_gev': 60.0, 'propagator': 'running-width',
             'couplings': {'scalar_bottom': 0.15, 'scalar_top': [0.15, 0.02], 'pseudoscalar_top': [0.0, 0.4]}}]},
        {'id': 'pseudoscalar', 'constant': {'continuum': [1, 0]}, 'states': [
            {'mass_gev': 450.0, 'width_gev': 9.0, 'propagator': 'fixed-width',
             'couplings': {'pseudoscalar_top': 1.3}}]},
    ]


def _s(rng, n):
    return rng.uniform(70.0, 1300.0, size=n) ** 2


def test_propagator_laws():
    s = np.array([400.0 ** 2, 600.0 ** 2])
    fixed = ab.propagator(s, 600.0, 30.0, 'fixed-width')
    running = ab.propagator(s, 600.0, 30.0, 'running-width')
    assert fixed[1] == pytest.approx(1 / complex(0.0, 600.0 * 30.0))
    assert running[0] == pytest.approx(1 / complex(400.0 ** 2 - 600.0 ** 2, 400.0 ** 2 * 30.0 / 600.0))
    with pytest.raises(ValueError, match='propagator'):
        ab.propagator(s, 600.0, 30.0, 'complex-guess')
    with pytest.raises(ValueError, match='positive'):
        ab.propagator(s, 600.0, 0.0, 'fixed-width')


def test_coefficients_follow_declared_states():
    basis = ab.Basis(MEMBERS)
    rng = np.random.default_rng(1)
    s = _s(rng, 5)
    h = ab.hypothesis(_hypotheses()[2], basis)
    c = ab.coefficients(h, basis, s)
    p1 = ab.propagator(s, 125.0, 0.0041, 'fixed-width')
    p2 = ab.propagator(s, 600.0, 60.0, 'running-width')
    assert c.shape == (5, 4)
    np.testing.assert_allclose(c[:, 0], 1.0)
    np.testing.assert_allclose(c[:, 2], 0.85 * p1 + complex(0.15, 0.02) * p2)
    np.testing.assert_allclose(c[:, 3], 0.4j * p2)


@pytest.mark.parametrize('bad', [
    {'id': 'x', 'constant': {'unknown': 1}, 'states': []},
    {'id': 'x', 'constant': {'continuum': True}, 'states': []},
    {'id': 'x', 'constant': {'continuum': float('nan')}, 'states': []},
    {'id': 'x', 'constant': {}, 'states': [{'mass_gev': 100, 'width_gev': 1, 'propagator': 'fixed-width', 'couplings': {}}]},
    {'id': '', 'constant': {'continuum': 1}, 'states': []},
    {'id': 'x', 'constant': {'continuum': 1}},
])
def test_hypothesis_refusals(bad):
    with pytest.raises(ValueError):
        ab.hypothesis(bad, ab.Basis(MEMBERS))


def test_gram_recombination_equals_direct_square_distinct_particles():
    rng = np.random.default_rng(7)
    basis = ab.Basis(MEMBERS)
    n = 40
    direct = _random_amplitudes(rng, n)
    norm = rng.uniform(0.5, 2.0, size=n)
    s = _s(rng, n)
    G = ab.point_grams(direct, normalization=norm)
    for doc in _hypotheses():
        c = ab.coefficients(ab.hypothesis(doc, basis), basis, s)
        expected = np.array([norm[i] * sum(abs(np.dot(direct[i, h], c[i])) ** 2 for h in range(16)) for i in range(n)])
        np.testing.assert_allclose(ab.evaluate(G, c), expected, rtol=1e-12, atol=0)


@pytest.mark.parametrize('selected_direct', [True, False])
def test_gram_recombination_equals_direct_square_identical_particles(selected_direct):
    rng = np.random.default_rng(11)
    basis = ab.Basis(MEMBERS)
    n = 30
    direct, swap = _random_amplitudes(rng, n), _random_amplitudes(rng, n)
    exchange = np.array([h34 == h56 for (_, _, h34, h56) in ab.HELICITY_LABELS])
    norm = rng.uniform(0.5, 2.0, size=n)
    s = _s(rng, n)
    selected = np.full(n, selected_direct)
    reference = ab.coefficients(ab.hypothesis(_hypotheses()[1], basis), basis, s)
    G = ab.point_grams(direct, swap=swap, identical=np.ones(n, bool), selected_direct=selected,
                       exchange=exchange, reference=reference, normalization=norm)
    for doc in _hypotheses():
        c = ab.coefficients(ab.hypothesis(doc, basis), basis, s)
        expected = []
        for i in range(n):
            total = 0.0
            for h in range(16):
                m, w = np.dot(direct[i, h], c[i]), np.dot(swap[i, h], c[i])
                mr, wr = np.dot(direct[i, h], reference[i]), np.dot(swap[i, h], reference[i])
                chosen, chosen_ref = (m, mr) if selected_direct else (w, wr)
                if exchange[h]:
                    total += 2 * abs(chosen_ref) ** 2 / (abs(mr) ** 2 + abs(wr) ** 2) * abs(m - w) ** 2
                else:
                    total += 2 * abs(chosen) ** 2
            expected.append(norm[i] * total)
        np.testing.assert_allclose(ab.evaluate(G, c), expected, rtol=1e-12, atol=0)


def test_reference_partition_equals_hypothesis_partition_when_they_coincide():
    rng = np.random.default_rng(3)
    basis = ab.Basis(MEMBERS)
    n = 10
    direct, swap = _random_amplitudes(rng, n), _random_amplitudes(rng, n)
    exchange = np.ones(16, bool)
    s = _s(rng, n)
    c = ab.coefficients(ab.hypothesis(_hypotheses()[3], basis), basis, s)
    G = ab.point_grams(direct, swap=swap, identical=np.ones(n, bool), selected_direct=np.ones(n, bool),
                       exchange=exchange, reference=c, normalization=np.ones(n))
    m = np.einsum('nhk,nk->nh', direct, c)
    w = np.einsum('nhk,nk->nh', swap, c)
    per_hypothesis = (2 * abs(m) ** 2 * abs(m - w) ** 2 / (abs(m) ** 2 + abs(w) ** 2)).sum(axis=1)
    np.testing.assert_allclose(ab.evaluate(G, c), per_hypothesis, rtol=1e-12)


def test_reference_partition_integrates_like_the_per_hypothesis_partition():
    """Any partition of unity gives an unbiased two-channel estimator of the same integral."""
    rng = np.random.default_rng(2024)
    n = 400_000

    def amps(x):
        m = np.exp(-((x - 0.3) / 0.05) ** 2) + 0.2j
        w = 0.7 * np.exp(-((x - 0.7) / 0.05) ** 2) - 0.1
        return m, w

    def density(x, centre):
        # Normalized mixture on [0, 1]: half flat, half truncated Gaussian peak.
        from math import erf, sqrt
        sigma = 0.07
        norm = 0.5 * (erf((1 - centre) / (sqrt(2) * sigma)) - erf((0 - centre) / (sqrt(2) * sigma)))
        return 0.5 + 0.5 * np.exp(-0.5 * ((x - centre) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi) * norm)

    def sample(centre, size):
        flat = rng.uniform(size=size)
        peak = rng.normal(centre, 0.07, size=size * 2)
        peak = peak[(peak >= 0) & (peak <= 1)][:size]
        choose = rng.uniform(size=size) < 0.5
        return np.where(choose, flat, peak)

    channel = rng.uniform(size=n) < 0.5
    x = np.where(channel, sample(0.3, n), sample(0.7, n))
    p = np.where(channel, density(x, 0.3), density(x, 0.7))
    m, w = amps(x)
    integrand = abs(m - w) ** 2
    ref_m, ref_w = 1.0 + 0.0 * x, 0.5 + 0.3 * x  # a fixed reference amplitude pair
    own = np.where(channel, abs(m) ** 2, abs(w) ** 2) / (abs(m) ** 2 + abs(w) ** 2)
    ref = np.where(channel, abs(ref_m) ** 2, abs(ref_w) ** 2) / (abs(ref_m) ** 2 + abs(ref_w) ** 2)
    est_own = 2 * own * integrand / p
    est_ref = 2 * ref * integrand / p
    grid = np.linspace(0, 1, 2_000_001)
    m_g, w_g = amps(grid)
    exact = np.trapz(abs(m_g - w_g) ** 2, grid)
    for est in (est_own, est_ref):
        error = est.std() / math.sqrt(n)
        assert abs(est.mean() - exact) < 4 * error


def test_zero_reference_partition_falls_back_to_equal_split():
    basis = ab.Basis(['a'])
    direct = np.ones((1, 1, 1), complex)
    swap = np.zeros((1, 1, 1), complex)
    G = ab.point_grams(direct, swap=swap, identical=np.ones(1, bool), selected_direct=np.ones(1, bool),
                       exchange=np.ones(1, bool), reference=np.zeros((1, 1), complex), normalization=np.ones(1))
    assert ab.evaluate(G, np.ones((1, 1), complex))[0] == pytest.approx(1.0)


def test_gram_is_hermitian_and_weights_real():
    rng = np.random.default_rng(5)
    G = ab.point_grams(_random_amplitudes(rng, 6), normalization=np.ones(6))
    np.testing.assert_allclose(G, np.conj(np.swapaxes(G, 1, 2)), atol=1e-12)
    eigen = np.linalg.eigvalsh(G)
    assert (eigen > -1e-9).all()


def test_pack_unpack_round_trip():
    rng = np.random.default_rng(9)
    G = ab.point_grams(_random_amplitudes(rng, 7), normalization=np.ones(7))
    packed = ab.pack(G)
    assert packed.shape == (7, 16)
    np.testing.assert_array_equal(ab.unpack(packed, 4), G)


def test_histogram_keeps_flows_separately():
    edges = [10.0, 20.0, 40.0]
    values = np.array([5.0, 10.0, 19.999, 20.0, 39.0, 40.0, 100.0])
    weights = np.arange(1.0, 8.0)
    hist = ab.histogram(values, weights, edges)
    # bins, then underflow, then overflow
    assert hist.tolist() == [2.0 + 3.0, 4.0 + 5.0, 1.0, 6.0 + 7.0]


def test_streams_include_signed_differences_to_reference():
    names = ab.stream_names(['SM', 'H1', 'H2'], reference='SM')
    assert names == ['SM', 'H1', 'H2', 'delta:H1', 'delta:H2']
    with pytest.raises(ValueError):
        ab.stream_names(['H1'], reference='SM')


def test_centered_block_covariance_matches_numpy():
    rng = np.random.default_rng(13)
    cohort_a = [rng.normal(size=5) for _ in range(6)]
    cohort_b = [rng.normal(size=5) for _ in range(4)]
    joint = ab.centered_blocks({'a': cohort_a, 'b': cohort_b})
    expected_mean = np.mean(cohort_a, axis=0) + np.mean(cohort_b, axis=0)
    expected_cov = np.cov(np.array(cohort_a).T) / 6 + np.cov(np.array(cohort_b).T) / 4
    np.testing.assert_allclose(joint['mean'], expected_mean, rtol=1e-12)
    np.testing.assert_allclose(joint['covariance'], expected_cov, rtol=1e-12, atol=1e-15)
    assert [c['blocks'] for c in joint['cohorts']] == [6, 4]


def test_centered_blocks_require_two_blocks_per_cohort():
    with pytest.raises(ValueError, match='two'):
        ab.centered_blocks({'a': [np.ones(3)]})
    with pytest.raises(ValueError, match='length'):
        ab.centered_blocks({'a': [np.ones(3), np.ones(2)]})
