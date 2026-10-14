"""Analytic checks for the columnar kinematic library and the MT2 family."""
import math

import numpy as np
import pytest

from ravel.physics.columnar import kinematics as k
from ravel.physics.columnar import mt2 as m


def four(pt, eta, phi, mass):
    px, py, pz, e = k.p4(np.asarray(pt, float), np.asarray(eta, float), np.asarray(phi, float), np.asarray(mass, float))
    return np.stack([px, py, pz, e], axis=-1)


def test_p4_mass_and_angles():
    v = four([50.0], [0.7], [1.1], [10.0])
    assert k.mass(*v.T)[0] == pytest.approx(10.0, rel=1e-12)
    back = four([40.0, 40.0], [0.0, 0.0], [0.0, math.pi], [0.0, 0.0])
    total = back.sum(axis=0)
    assert k.mass(*total) == pytest.approx(80.0)
    assert k.delta_phi(np.array([3.0]), np.array([-3.0]))[0] == pytest.approx(2 * math.pi - 6.0)
    assert k.delta_r(np.array([0.0]), np.array([0.0]), np.array([0.3]), np.array([0.4]))[0] == pytest.approx(0.5)


def test_transverse_mass_massless_and_massive():
    assert k.mt(np.array([50.0]), np.array([0.0]), np.array([0.0]), np.array([50.0]), np.array([math.pi]))[0] == pytest.approx(100.0)
    assert k.mt(np.array([50.0]), np.array([0.0]), np.array([0.0]), np.array([50.0]), np.array([0.0]))[0] == pytest.approx(0.0, abs=1e-9)
    massive = k.mt(np.array([30.0]), np.array([0.0]), np.array([1.777]), np.array([40.0]), np.array([2.0]), massless=False)[0]
    et = math.hypot(30.0, 1.777)
    expected = math.sqrt(1.777 ** 2 + 2 * (et * 40.0 - 30.0 * 40.0 * math.cos(2.0)))
    assert massive == pytest.approx(expected)


def test_neutrino_pz_reconstructs_w_mass():
    lep = four([35.0], [0.4], [0.3], [0.0])
    met = np.array([[30.0 * math.cos(2.0), 30.0 * math.sin(2.0)]])
    pz, real = k.neutrino_pz(lep, met, w_mass=80.0)
    nu = np.array([met[0, 0], met[0, 1], pz[0], math.sqrt(met[0, 0] ** 2 + met[0, 1] ** 2 + pz[0] ** 2)])
    assert real[0]
    assert k.mass(*(lep[0] + nu)) == pytest.approx(80.0, rel=1e-9)


def test_aplanarity_of_planar_event_is_zero():
    vectors = four([30.0, 40.0, 50.0], [0.0, 0.0, 0.0], [0.0, 2.0, 4.0], [0.0, 0.0, 0.0])
    assert k.aplanarity(vectors[None, :, 0], vectors[None, :, 1], vectors[None, :, 2])[0] == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------- MT2
def test_mt2_without_missing_momentum_is_largest_visible_mass():
    value = m.mt2(np.array([5.0]), np.array([10.0]), np.array([3.0]), np.array([7.0]), np.array([-4.0]), np.array([9.0]),
                  np.array([0.0]), np.array([0.0]), np.array([0.0]), np.array([0.0]))
    assert value[0] == pytest.approx(7.0, rel=1e-7)


def test_mt2_massless_without_upstream_momentum_closed_form():
    rng = np.random.default_rng(3)
    n = 50
    p1 = rng.normal(0, 60, size=(n, 2))
    p2 = rng.normal(0, 60, size=(n, 2))
    miss = -(p1 + p2)
    z = np.zeros(n)
    value = m.mt2(z, p1[:, 0], p1[:, 1], z, p2[:, 0], p2[:, 1], miss[:, 0], miss[:, 1], z, z)
    expected = np.sqrt(2 * (np.hypot(*p1.T) * np.hypot(*p2.T) + (p1 * p2).sum(axis=1)))
    np.testing.assert_allclose(value, expected, rtol=1e-6, atol=1e-6)


def _pair_decays(rng, n, parent, visible, invisible):
    """Two parents of mass `parent` at rest in the transverse plane, each to visible + invisible."""
    p_star = math.sqrt((parent ** 2 - (visible + invisible) ** 2) * (parent ** 2 - (visible - invisible) ** 2)) / (2 * parent)
    out = []
    for _ in range(2):
        cos_t = rng.uniform(-1, 1, n); phi = rng.uniform(0, 2 * math.pi, n)
        sin_t = np.sqrt(1 - cos_t ** 2)
        direction = np.stack([sin_t * np.cos(phi), sin_t * np.sin(phi), cos_t], axis=1)
        # a random boost along z keeps the transverse kinematics of a parent at transverse rest
        out.append(p_star * direction)
    return out


def test_mt2_endpoint_is_parent_mass():
    rng = np.random.default_rng(11)
    n, parent, vis, inv = 3000, 300.0, 0.0, 100.0
    d1, d2 = _pair_decays(rng, n, parent, vis, inv)
    miss = -(d1[:, :2] + d2[:, :2])
    z = np.zeros(n)
    value = m.mt2(z + vis, d1[:, 0], d1[:, 1], z + vis, d2[:, 0], d2[:, 1], miss[:, 0], miss[:, 1], z + inv, z + inv)
    assert np.all(value <= parent * (1 + 1e-7))
    assert value.max() > 0.97 * parent
    assert np.all(value >= vis + inv - 1e-9)


def test_mt2_matches_reference_bisection():
    from ravel.physics.sa_native_core import get_mT2
    rng = np.random.default_rng(5)
    n = 200
    a = rng.normal(0, 80, size=(n, 2)); b = rng.normal(0, 80, size=(n, 2)); miss = rng.normal(0, 90, size=(n, 2))
    ma = rng.uniform(0, 30, n); mb = rng.uniform(0, 30, n); chi = rng.choice([0.0, 50.0], n)
    value = m.mt2(ma, a[:, 0], a[:, 1], mb, b[:, 0], b[:, 1], miss[:, 0], miss[:, 1], chi, chi)
    reference = np.array([get_mT2(ma[i], a[i, 0], a[i, 1], mb[i], b[i, 0], b[i, 1], miss[i, 0], miss[i, 1], chi[i], chi[i])
                          for i in range(n)])
    np.testing.assert_allclose(value, reference, rtol=1e-6, atol=1e-6)


# ---------------------------------------------------------------- MT2W
def _semileptonic_top_pair(rng, n, m_top, m_w, m_b):
    """Exact on-shell t -> b W(l nu) and t -> b W(lost) configurations with transverse recoil."""
    def two_body(parent_mass, a, b, count):
        p = math.sqrt((parent_mass ** 2 - (a + b) ** 2) * (parent_mass ** 2 - (a - b) ** 2)) / (2 * parent_mass)
        c = rng.uniform(-1, 1, count); f = rng.uniform(0, 2 * math.pi, count); s = np.sqrt(1 - c ** 2)
        d = np.stack([s * np.cos(f), s * np.sin(f), c], axis=1) * p
        return (np.column_stack([d, np.sqrt(a ** 2 + p ** 2) * np.ones(count)]),
                np.column_stack([-d, np.sqrt(b ** 2 + p ** 2) * np.ones(count)]))

    def boost(v, beta):
        b2 = (beta ** 2).sum(axis=1); g = 1 / np.sqrt(1 - b2)
        bp = (beta * v[:, :3]).sum(axis=1)
        g2 = np.where(b2 > 0, (g - 1) / np.where(b2 > 0, b2, 1), 0)
        space = v[:, :3] + (g2 * bp)[:, None] * beta + (g * v[:, 3])[:, None] * beta
        return np.column_stack([space, g * (v[:, 3] + bp)])

    def top(beta):
        b, w = two_body(m_top, m_b, m_w, n)
        return boost(b, beta), boost(w, beta)

    beta1 = rng.uniform(-0.5, 0.5, (n, 3)); beta2 = rng.uniform(-0.5, 0.5, (n, 3))
    b1, w1 = top(beta1); b2, w2 = top(beta2)
    lep, nu = two_body(m_w, 0.0, 0.0, n)
    lep = boost(lep, w1[:, :3] / w1[:, 3:4]); nu = boost(nu, w1[:, :3] / w1[:, 3:4])
    met = nu[:, :2] + w2[:, :2]
    return lep, b1, b2, met


def test_mt2w_true_configuration_is_bounded_by_the_top_mass():
    rng = np.random.default_rng(21)
    lep, b1, b2, met = _semileptonic_top_pair(rng, 300, 173.0, 80.4, 4.7)
    value = m.mt2w(lep, b1, b2, met, w_mass=80.4)
    assert np.all(np.isfinite(value))
    assert np.all(value <= 173.0 * (1 + 2e-4))
    assert np.all(value >= 80.4 + 4.7 - 1e-6)
    assert np.median(value) > 100.0


def _mt2w_bruteforce(lep, b1, b2, met, w_mass):
    """Grid over the lepton-side neutrino transverse momentum, then local refinement."""
    from scipy.optimize import minimize

    def side(px, py):
        el = lep[3]; plt = lep[:2]; plz = lep[2]
        a = (w_mass ** 2 - (lep[3] ** 2 - (lep[:3] ** 2).sum())) / 2
        # p.l = a with p massless: E el - px lx - py ly - pz lz = a, E = sqrt(pt^2 + pz^2)
        pt2 = px ** 2 + py ** 2
        c = a + px * plt[0] + py * plt[1]
        # (E el)^2 = (c + pz lz)^2 -> quadratic in pz
        qa = el ** 2 - plz ** 2; qb = -2 * c * plz; qc = el ** 2 * pt2 - c ** 2
        disc = qb ** 2 - 4 * qa * qc
        roots = []
        ok = disc >= 0
        for sign in (1, -1):
            pz = np.where(ok, (-qb + sign * np.sqrt(np.where(ok, disc, 0))) / (2 * qa), np.nan)
            e = np.sqrt(pt2 + pz ** 2)
            good = ok & (np.abs(e * el - pz * plz - c) < 1e-6 * (1 + np.abs(c)))
            top = np.stack([px + lep[0] + b1[0], py + lep[1] + b1[1], pz + lep[2] + b1[2], e + lep[3] + b1[3]])
            mass2 = top[3] ** 2 - (top[:3] ** 2).sum(axis=0)
            roots.append(np.where(good, np.sqrt(np.maximum(mass2, 0)), np.inf))
        return roots

    def other(px, py):
        qx, qy = met[0] - px, met[1] - py
        etb = math.sqrt(b2[3] ** 2 - b2[2] ** 2)
        mb2 = b2[3] ** 2 - (b2[:3] ** 2).sum()
        etq = np.sqrt(w_mass ** 2 + qx ** 2 + qy ** 2)
        return np.sqrt(mb2 + w_mass ** 2 + 2 * (etb * etq - b2[0] * qx - b2[1] * qy))

    grid = np.linspace(-600, 600, 1201)
    gx, gy = np.meshgrid(grid, grid)
    m2 = other(gx, gy)
    objective = np.min([np.where(m2 <= r, r, np.inf) for r in side(gx, gy)], axis=0)
    best = np.unravel_index(np.argmin(objective), objective.shape)
    start = np.array([gx[best], gy[best]])

    def penalty(x):
        a2 = other(np.array(x[0]), np.array(x[1]))
        values = [float(r + 1e3 * max(0.0, a2 - r)) for r in side(np.array(x[0]), np.array(x[1])) if np.isfinite(r)]
        return min(values) if values else 1e9
    refined = minimize(penalty, start, method='Nelder-Mead', options={'xatol': 1e-6, 'fatol': 1e-9, 'maxiter': 4000})
    return min(float(objective[best]), refined.fun)


def test_mt2w_agrees_with_bruteforce_minimisation():
    rng = np.random.default_rng(8)
    lep, b1, b2, met = _semileptonic_top_pair(rng, 6, 173.0, 80.4, 4.7)
    met = met + rng.normal(0, 25, met.shape)          # detector-like mismeasurement
    value = m.mt2w(lep, b1, b2, met, w_mass=80.4)
    for i in range(len(value)):
        reference = _mt2w_bruteforce(lep[i], b1[i], b2[i], met[i], 80.4)
        assert value[i] == pytest.approx(reference, rel=3e-3), i


# ---------------------------------------------------------------- modified topness
def test_modified_topness_true_configuration_is_minus_infinity_or_floor():
    rng = np.random.default_rng(4)
    lep, _, b2, met = _semileptonic_top_pair(rng, 40, 173.0, 80.4, 4.7)
    value = m.modified_topness(lep, b2, met, m_w=80.4, m_top=173.0, sigma_w=5.0, sigma_top=15.0)
    assert np.all(value == -np.inf)
    floored = m.modified_topness(lep, b2, met, m_w=80.4, m_top=173.0, sigma_w=5.0, sigma_top=15.0, floor=1e-6)
    np.testing.assert_allclose(floored, math.log(1e-6))


def test_modified_topness_matches_numerical_minimum():
    from scipy.optimize import minimize
    rng = np.random.default_rng(12)
    n = 12
    lep = four(rng.uniform(150, 300, n), rng.uniform(-1, 1, n), rng.uniform(-3, 3, n), np.zeros(n))
    b = four(rng.uniform(100, 300, n), rng.uniform(-1, 1, n), rng.uniform(-3, 3, n), np.full(n, 4.7))
    met = rng.normal(0, 300, (n, 2))
    value = m.modified_topness(lep, b, met, m_w=80.4, m_top=173.0, sigma_w=5.0, sigma_top=15.0)
    for i in range(n):
        def s(x):
            nu = np.array(x); w = met[i] - nu
            etl = math.hypot(lep[i, 0], lep[i, 1]); mt2l = 2 * (etl * math.hypot(*nu) - lep[i, :2] @ nu)
            mb2 = b[i, 3] ** 2 - (b[i, :3] ** 2).sum(); etb = math.sqrt(mb2 + b[i, 0] ** 2 + b[i, 1] ** 2)
            mt2b = mb2 + 80.4 ** 2 + 2 * (etb * math.sqrt(80.4 ** 2 + w @ w) - b[i, :2] @ w)
            return max(0.0, mt2l - 80.4 ** 2) ** 2 / 5.0 ** 4 + max(0.0, mt2b - 173.0 ** 2) ** 2 / 15.0 ** 4
        best = min((minimize(s, x0, method='Nelder-Mead', options={'xatol': 1e-8, 'fatol': 1e-12, 'maxiter': 20000})
                    for x0 in (met[i] / 2, met[i], np.array([1.0, 1.0]), -met[i])), key=lambda r: r.fun)
        if best.fun <= 0:
            assert value[i] == -np.inf
        else:
            assert value[i] == pytest.approx(math.log(best.fun), abs=2e-3), i
