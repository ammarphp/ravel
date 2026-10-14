"""Spin-0 s-channel helicity amplitudes: spinor identities, analytic limits and CP properties."""
import math

import numpy as np
import pytest

from ravel.physics import amplitude_basis as ab
from ravel.physics import spin0_amplitudes as sp

from amplitude_fixtures import CONSTANTS, points as _points


def _members(*specs):
    return [{'id': f'{q}-{cp}-{d}', 'quark_mass_gev': q, 'production': cp, 'decay': d} for q, cp, d in specs]


def test_spinor_products_reproduce_invariants_and_currents():
    p = _points(1, 3)
    lam, lamt = sp.spinors(p)
    for i in range(6):
        np.testing.assert_allclose(sp.current(lam, lamt, i, i), 2 * p[:, i], atol=1e-9)
        for j in range(6):
            if i != j:
                s = 2 * sp.dot(p[:, i], p[:, j])
                np.testing.assert_allclose(sp.angle(lam, i, j) * sp.square(lamt, j, i), s, rtol=1e-9, atol=1e-6)
    lhs = sp.dot(sp.current(lam, lamt, 2, 3), sp.current(lam, lamt, 4, 5))
    np.testing.assert_allclose(lhs, 2 * sp.angle(lam, 2, 4) * sp.square(lamt, 5, 3), rtol=1e-9)


def test_form_factors_heavy_quark_limit_and_continuity():
    assert sp.form_factor(1e-7, 'even') == pytest.approx(4 / 3, rel=1e-6)
    assert sp.form_factor(1e-7, 'odd') == pytest.approx(2.0, rel=1e-6)
    below, above = sp.form_factor(1 - 1e-9, 'even'), sp.form_factor(1 + 1e-9, 'even')
    assert abs(below - above) < 1e-4
    assert sp.form_factor(4.0, 'odd').imag != 0.0
    # Light-quark limit: both form factors vanish like log^2(tau)/tau.
    assert abs(sp.form_factor(1e6, 'even')) < 1e-3 and abs(sp.form_factor(1e6, 'odd')) < 1e-3
    with pytest.raises(ValueError):
        sp.form_factor(0.5, 'mixed')


def test_production_tensors_select_equal_gluon_helicities():
    p = _points(2, 4)
    lam, lamt = sp.spinors(p)
    s = sp.dot(p[:, 0] + p[:, 1], p[:, 0] + p[:, 1])
    for h1 in '-+':
        for h2 in '-+':
            e1 = sp.polarization(lam, lamt, 0, 1, h1)
            e2 = sp.polarization(lam, lamt, 1, 0, h2)
            even, odd = sp.tensor_products(e1, p[:, 0], e2, p[:, 1])
            if h1 != h2:
                assert np.abs(even).max() < 1e-8 * s.max() and np.abs(odd).max() < 1e-8 * s.max()
            else:
                np.testing.assert_allclose(np.abs(even), np.abs(s), rtol=1e-9)
                ratio = odd / even
                np.testing.assert_allclose(np.abs(ratio), 1.0, rtol=1e-9)
                np.testing.assert_allclose(ratio.real, 0.0, atol=1e-9)
    e = {h: (sp.polarization(lam, lamt, 0, 1, h), sp.polarization(lam, lamt, 1, 0, h)) for h in '-+'}
    r_minus = sp.tensor_products(e['-'][0], p[:, 0], e['-'][1], p[:, 1])
    r_plus = sp.tensor_products(e['+'][0], p[:, 0], e['+'][1], p[:, 1])
    np.testing.assert_allclose(r_minus[1] / r_minus[0], -(r_plus[1] / r_plus[0]), rtol=1e-9)


def test_decay_g1_term_matches_spinor_closed_form():
    p = _points(3, 3)
    members = _members((173.0, 'even', 'g1'))
    a = sp.amplitudes(p, members, CONSTANTS)
    lam, lamt = sp.spinors(p)
    s = sp.dot(p[:, 0] + p[:, 1], p[:, 0] + p[:, 1])
    q1, q2 = p[:, 2] + p[:, 3], p[:, 4] + p[:, 5]
    mz, wz = CONSTANTS['z_mass_gev'], CONSTANTS['z_width_gev']
    dz = lambda q: 1 / (sp.dot(q, q) - mz ** 2 + 1j * mz * wz)
    left = CONSTANTS['lepton_z_couplings']['left']
    expected_decay = mz ** 2 * left ** 2 * dz(q1) * dz(q2) * 2 * sp.angle(lam, 2, 4) * sp.square(lamt, 5, 3)
    h = ab.HELICITY_LABELS.index(('-', '-', '-', '-'))
    loop = sp.form_factors(s, 173.0, 'even')
    e1 = sp.polarization(lam, lamt, 0, 1, '-')
    e2 = sp.polarization(lam, lamt, 1, 0, '-')
    production = sp.tensor_products(e1, p[:, 0], e2, p[:, 1])[0]
    pref = CONSTANTS['alpha_s'] / (8 * math.pi * CONSTANTS['vev_gev'] ** 2)
    np.testing.assert_allclose(a[:, h, 0], pref * production * loop * expected_decay, rtol=1e-9)


def test_amplitudes_do_not_depend_on_gluon_reference_vectors():
    p = _points(4, 5)
    members = _members((173.0, 'even', 'g1'), (173.0, 'odd', 'g4'), (4.8, 'even', 'g2'), (173.0, 'odd', 'g1'))
    assert sp.gauge_check(p, members, CONSTANTS) < 1e-9


def _cp_mirror(p):
    """CP image: parity on every momentum, leptons exchanged with their antileptons."""
    q = p.copy()
    q[..., :3] *= -1
    return q[:, [0, 1, 3, 2, 5, 4]]


def test_cp_odd_interference_vanishes_for_cp_symmetric_observables():
    p = _points(5, 8)
    # 0: even production, even decay (scalar)   1: odd production, odd decay (pseudoscalar)
    # 2: odd production, even decay             3: even production, odd decay
    members = _members((173.0, 'even', 'g1'), (173.0, 'odd', 'g4'), (173.0, 'odd', 'g1'), (173.0, 'even', 'g4'))
    a = sp.amplitudes(p, members, CONSTANTS)
    b = sp.amplitudes(_cp_mirror(p), members, CONSTANTS)
    G, Gm = ab.point_grams(a), ab.point_grams(b)
    scale = np.abs(G).max()
    # The gluon pair of a spin-0 state is in (++) + (--) for CP-even and (++) - (--)
    # for CP-odd production: after the helicity sum they never interfere, point by
    # point. In particular the pseudoscalar does not interfere with the scalar.
    for i, j in ((0, 1), (0, 2), (1, 3), (2, 3)):
        assert np.abs(G[:, i, j]).max() < 1e-12 * scale
    # A CP-odd decay vertex interferes with the CP-even one point by point, but the
    # term is CP-odd: observables symmetric under CP (the four-lepton mass, CP-even
    # angular sums) integrate a point and its CP image alike, so it cancels.
    for i, j in ((0, 3), (1, 2)):
        assert np.abs(G[:, i, j]).max() > 1e-3 * scale
        assert np.abs(G[:, i, j] + Gm[:, i, j]).max() < 1e-9 * scale
    np.testing.assert_allclose(np.diagonal(G, axis1=1, axis2=2).real, np.diagonal(Gm, axis1=1, axis2=2).real, rtol=1e-9)


def test_pseudoscalar_interferes_with_unequal_gluon_helicity_amplitudes():
    # A continuum has independent (++) and (--) amplitudes, so it overlaps with the
    # CP-odd gluon state; the overlap is what makes pseudoscalar-continuum
    # interference nonzero in the four-lepton mass.
    p = _points(6, 6)
    a = sp.amplitudes(p, _members((173.0, 'odd', 'g4'), (173.0, 'even', 'g4')), CONSTANTS)
    plus = np.array([h[0] == '+' and h[1] == '+' for h in ab.HELICITY_LABELS])
    continuum = np.where(plus[None, :], 1.0, 0.2) * a[:, :, 1]
    G = ab.point_grams(np.stack([continuum, a[:, :, 0]], axis=2))
    assert np.abs(G[:, 0, 1]).max() > 1e-3 * np.abs(G).max()


def test_closure_recovers_constant_factors_and_aligns_members():
    p = _points(7, 6)
    members = _members((173.0, 'even', 'g1'), (173.0, 'odd', 'g4'))
    a = sp.amplitudes(p, members, CONSTANTS)
    factors = np.exp(1j * np.linspace(0, 3, 16)) * 2.5
    reference = a[:, :, 0] * factors
    result = sp.closure(a[:, :, 0], reference)
    assert result['passed'] and not result['common_factor']
    aligned = sp.align(a, result)
    np.testing.assert_allclose(aligned[:, :, 0], reference, rtol=1e-9, atol=1e-12 * np.abs(reference).max())
    noisy = reference * (1 + 1e-3 * np.random.default_rng(0).normal(size=reference.shape))
    failed = sp.closure(a[:, :, 0], noisy, rtol=1e-6)
    assert not failed['passed']
    with pytest.raises(ValueError, match='closure'):
        sp.align(a, failed)


def test_inputs_are_required():
    p = _points(8, 1)
    with pytest.raises(ValueError, match='constants'):
        sp.amplitudes(p, _members((173.0, 'even', 'g1')), {**CONSTANTS, 'alpha_s': None} | {'extra': 1})
    with pytest.raises(ValueError, match='decay'):
        sp.amplitudes(p, _members((173.0, 'even', 'g3')), CONSTANTS)
    with pytest.raises(ValueError, match='conserve'):
        bad = p.copy()
        bad[:, 2, 3] += 1.0
        sp.amplitudes(bad, _members((173.0, 'even', 'g1')), CONSTANTS)
