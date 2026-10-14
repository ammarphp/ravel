"""Spinor-helicity amplitudes for gluon-fusion spin-0 s-channel states decaying to four leptons.

The process is g(1) g(2) -> S -> Z(3,4) Z(5,6) -> l(3) lbar(4) l'(5) lbar'(6), with
all momenta outgoing (the incoming gluons carry negative energy). Each amplitude
is the *numerator* of one basis member: the S propagator is supplied later by
``amplitude_basis`` coefficients, so the members combine coherently with any
cached continuum amplitudes of the same points.

Production uses the exact one-loop quark triangle through the effective vertex

    L = alpha_s / (16 pi v) * sum_q [ kappa_q A_H(tau_q) S G G + kappa~_q A_A(tau_q) S G G~ ],
    G~^{mu nu} = 1/2 eps^{mu nu rho sigma} G_{rho sigma},  tau_q = s / (4 m_q^2),

with A_H -> 4/3 and A_A -> 2 in the heavy-quark limit. Decay uses the spin-0
ZZ vertex in the g1/g2/g4 convention of the anomalous-coupling literature

    A(S -> ZZ) = v^-1 [ g1 m_Z^2 e1.e2 + g2 f1.f2 + g4 f1.f2~ ],  f^{mu nu} = e^mu q^nu - e^nu q^mu,

where e1, e2 are the lepton currents times the declared Z couplings and Z
propagators. ``eps^{0123} = +1`` and the metric is (+,-,-,-). Momenta are
(px, py, pz, E) in GeV.

Spinors follow the light-cone decomposition along the x axis with an i for each
negative-energy momentum; <ij>[ji] = s_ij. The phase of every helicity amplitude
depends on this convention, so before CP-odd members are combined with cached
continuum amplitudes from another program, ``closure`` must reproduce that
program's own CP-even spin-0 amplitudes at the same points with one constant
factor per helicity; ``align`` then applies the factors to every member.

After the gluon-helicity sum, CP-even and CP-odd production never interfere
(the gluon pair is in (++) + (--) or (++) - (--)), so a scalar and a
pseudoscalar do not interfere with each other at all. A CP-odd decay vertex
interferes with the CP-even one point by point, but the term is CP-odd and
cancels in CP-symmetric observables such as the four-lepton mass. A continuum
has independent (++) and (--) amplitudes and interferes with both.

Every physical constant (alpha_s, v, quark and Z masses, Z width, lepton
couplings) is a required input; nothing is defaulted.
"""
from __future__ import annotations

import cmath
import math

import numpy as np

from .amplitude_basis import HELICITY_LABELS, require

PRODUCTION_CP = ('even', 'odd')
DECAY_TERMS = ('g1', 'g2', 'g4')
_SIGMA = (np.array([[0, 1], [1, 0]], dtype=complex), np.array([[0, -1j], [1j, 0]]), np.array([[1, 0], [0, -1]], dtype=complex))


# ---------------------------------------------------------------- spinors
def spinors(momenta):
    """Holomorphic and antiholomorphic spinors, each of shape (points, particles, 2)."""
    p = np.asarray(momenta, dtype=float)
    require(p.ndim == 3 and p.shape[2] == 4, 'momenta must have shape (points, particles, 4)')
    positive = p[..., 3] > 0
    bar = np.where(positive[..., None], p, -p)
    plus = bar[..., 3] + bar[..., 0]
    require(np.all(plus > 0), 'a momentum lies on the negative x light-cone; rotate the frame')
    rt = np.sqrt(plus)
    cs = bar[..., 2] - 1j * bar[..., 1]
    phase = np.where(positive, 1.0 + 0j, 1j)
    lam = phase[..., None] * np.stack([cs / rt, rt + 0j], axis=-1)
    lamt = phase[..., None] * np.stack([np.conj(cs) / rt, rt + 0j], axis=-1)
    return lam, lamt


def angle(lam, i, j):
    return lam[:, i, 0] * lam[:, j, 1] - lam[:, i, 1] * lam[:, j, 0]


def square(lamt, i, j):
    return lamt[:, i, 1] * lamt[:, j, 0] - lamt[:, i, 0] * lamt[:, j, 1]


def current(lam, lamt, i, j):
    """<i|gamma^mu|j] as (points, 4) complex vectors (px, py, pz, E); <i|gamma|i] = 2 p_i."""
    outer = lam[:, i, :, None] * lamt[:, j, None, :]
    energy = np.trace(outer, axis1=1, axis2=2)
    vector = [np.einsum('nab,ba->n', outer, s) for s in _SIGMA]
    return np.stack([-vector[2], vector[1], vector[0], energy], axis=1)


def dot(a, b):
    return a[..., 3] * b[..., 3] - a[..., 0] * b[..., 0] - a[..., 1] * b[..., 1] - a[..., 2] * b[..., 2]


def _permutations():
    import itertools
    rows = []
    for perm in itertools.permutations(range(4)):
        sign = 1
        for i in range(4):
            for j in range(i + 1, 4):
                if perm[i] > perm[j]:
                    sign = -sign
        rows.append((perm, sign))
    return tuple(rows)


_PERMUTATIONS = _permutations()


def levi_civita(a, b, c, d):
    """eps_{mu nu rho sigma} a^mu b^nu c^rho d^sigma with eps^{0123} = +1 (so eps_{0123} = -1)."""
    vectors = [v[..., [3, 0, 1, 2]] for v in (a, b, c, d)]
    total = 0
    for perm, sign in _PERMUTATIONS:
        total = total + sign * vectors[0][..., perm[0]] * vectors[1][..., perm[1]] * vectors[2][..., perm[2]] * vectors[3][..., perm[3]]
    return -total


def polarization(lam, lamt, k, q, helicity):
    """Outgoing gluon polarization of particle k with reference particle q."""
    if helicity == '+':
        return current(lam, lamt, q, k) / (math.sqrt(2.0) * angle(lam, q, k))[:, None]
    return current(lam, lamt, k, q) / (math.sqrt(2.0) * square(lamt, k, q))[:, None]


def tensor_products(a1, q1, a2, q2):
    """f1.f2 and f1.f2~ for f^{mu nu} = a^mu q^nu - a^nu q^mu."""
    even = 2.0 * (dot(a1, a2) * dot(q1, q2) - dot(a1, q2) * dot(a2, q1))
    odd = 2.0 * levi_civita(a1, q1, a2, q2)
    return even, odd


# ---------------------------------------------------------------- form factors
def _f(tau):
    if tau <= 1.0:
        return complex(math.asin(math.sqrt(tau)) ** 2, 0.0)
    beta = math.sqrt(1.0 - 1.0 / tau)
    return -0.25 * (math.log((1.0 + beta) / (1.0 - beta)) - 1j * math.pi) ** 2


def form_factor(tau, cp):
    """Quark-loop form factor: A_H(tau) for cp='even', A_A(tau) for cp='odd'."""
    require(cp in PRODUCTION_CP, 'cp must be even or odd')
    tau = float(tau)
    require(math.isfinite(tau) and tau > 0, 'tau must be positive')
    f = _f(tau)
    if cp == 'even':
        return 2.0 * (tau + (tau - 1.0) * f) / tau ** 2
    return 2.0 * f / tau


def form_factors(s, mass, cp):
    return np.array([form_factor(x / (4.0 * mass ** 2), cp) for x in np.asarray(s, dtype=float)])


# ---------------------------------------------------------------- members
def _positive(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value > 0, f'{label} must be a positive number')
    return float(value)


def validate_constants(constants):
    required = {'alpha_s', 'vev_gev', 'z_mass_gev', 'z_width_gev', 'lepton_z_couplings'}
    require(type(constants) is dict and set(constants) == required,
            'constants need exactly alpha_s, vev_gev, z_mass_gev, z_width_gev and lepton_z_couplings')
    for key in ('alpha_s', 'vev_gev', 'z_mass_gev', 'z_width_gev'):
        _positive(constants[key], key)
    couplings = constants['lepton_z_couplings']
    require(type(couplings) is dict and set(couplings) == {'left', 'right'}
            and all(type(couplings[k]) in (int, float) and math.isfinite(couplings[k]) for k in couplings),
            'lepton_z_couplings needs numeric left and right couplings')
    return constants


def validate_member(member):
    require(type(member) is dict and set(member) == {'id', 'quark_mass_gev', 'production', 'decay'},
            'spin-0 member needs exactly id, quark_mass_gev, production and decay')
    require(isinstance(member['id'], str) and member['id'].strip(), 'member id must be text')
    _positive(member['quark_mass_gev'], 'quark_mass_gev')
    require(member['production'] in PRODUCTION_CP, 'production must be even or odd')
    require(member['decay'] in DECAY_TERMS, f'decay must be one of {DECAY_TERMS}')
    return member


def amplitudes(momenta, members, constants, *, references=(1, 0)):
    """Helicity amplitudes a[n, h, k] of the declared spin-0 members (no S propagator).

    ``momenta`` has shape (points, 6, 4): gluons 1 and 2 (negative energy), then the
    lepton of the first Z, its antilepton, the lepton of the second Z and its
    antilepton. Helicity order follows ``amplitude_basis.HELICITY_LABELS``
    (gluon 1, gluon 2, first lepton line, second lepton line); for a lepton line
    '-' is the left-handed lepton current.
    """
    validate_constants(constants)
    require(type(members) is list and members, 'at least one spin-0 member required')
    for m in members:
        validate_member(m)
    require(len({m['id'] for m in members}) == len(members), 'member ids must be unique')
    p = np.asarray(momenta, dtype=float)
    require(p.ndim == 3 and p.shape[1:] == (6, 4), 'momenta must have shape (points, 6, 4)')
    require(np.all(p[:, :2, 3] < 0) and np.all(p[:, 2:, 3] > 0), 'gluons must carry negative energy and leptons positive')
    require(np.allclose(p.sum(axis=1), 0.0, atol=1e-8 * np.abs(p).max()), 'momenta must conserve four-momentum')
    lam, lamt = spinors(p)
    n = p.shape[0]
    k1, k2 = p[:, 0], p[:, 1]
    q1, q2 = p[:, 2] + p[:, 3], p[:, 4] + p[:, 5]
    s = dot(k1 + k2, k1 + k2)
    mz, wz = float(constants['z_mass_gev']), float(constants['z_width_gev'])
    dz1 = 1.0 / (dot(q1, q1) - mz ** 2 + 1j * mz * wz)
    dz2 = 1.0 / (dot(q2, q2) - mz ** 2 + 1j * mz * wz)
    zc = {'-': float(constants['lepton_z_couplings']['left']), '+': float(constants['lepton_z_couplings']['right'])}
    v = float(constants['vev_gev'])
    prefactor = float(constants['alpha_s']) / (8.0 * math.pi * v) / v
    ref1, ref2 = references
    gluon = {}
    for h1 in '-+':
        e1 = polarization(lam, lamt, 0, ref1, h1)
        for h2 in '-+':
            e2 = polarization(lam, lamt, 1, ref2, h2)
            gluon[h1, h2] = tensor_products(e1, k1, e2, k2)
    lepton = {}
    for h34 in '-+':
        j1 = (current(lam, lamt, 2, 3) if h34 == '-' else current(lam, lamt, 3, 2)) * (zc[h34] * dz1)[:, None]
        for h56 in '-+':
            j2 = (current(lam, lamt, 4, 5) if h56 == '-' else current(lam, lamt, 5, 4)) * (zc[h56] * dz2)[:, None]
            even, odd = tensor_products(j1, q1, j2, q2)
            lepton[h34, h56] = {'g1': mz ** 2 * dot(j1, j2), 'g2': even, 'g4': odd}
    loops = {}
    for m in members:
        key = (m['quark_mass_gev'], m['production'])
        if key not in loops:
            loops[key] = form_factors(s, m['quark_mass_gev'], m['production'])
    out = np.zeros((n, len(HELICITY_LABELS), len(members)), dtype=complex)
    for h, (h1, h2, h34, h56) in enumerate(HELICITY_LABELS):
        even, odd = gluon[h1, h2]
        for k, m in enumerate(members):
            production = (even if m['production'] == 'even' else odd) * loops[m['quark_mass_gev'], m['production']]
            out[:, h, k] = prefactor * production * lepton[h34, h56][m['decay']]
    return out


# ---------------------------------------------------------------- closure with cached amplitudes
def closure(mine, reference, *, rtol=1e-6, floor=1e-12):
    """Fit one constant complex factor per helicity mapping ``mine`` onto ``reference``.

    Both arrays have shape (points, helicities). Helicities where both vanish
    (relative to the largest amplitude) need no factor. The closure passes when
    every point matches within ``rtol`` of the largest reference amplitude.
    """
    mine = np.asarray(mine, dtype=complex)
    reference = np.asarray(reference, dtype=complex)
    require(mine.shape == reference.shape and mine.ndim == 2, 'closure needs two (points, helicities) arrays')
    scale_m = np.abs(mine).max(initial=0.0)
    scale_r = np.abs(reference).max(initial=0.0)
    require(scale_m > 0 and scale_r > 0, 'closure needs nonzero amplitudes')
    factors, residual = [], 0.0
    for h in range(mine.shape[1]):
        m, r = mine[:, h], reference[:, h]
        if np.abs(m).max() <= floor * scale_m and np.abs(r).max() <= floor * scale_r:
            factors.append(None)
            continue
        norm = np.vdot(m, m).real
        if norm == 0:
            factors.append(None)
            residual = math.inf
            continue
        c = np.vdot(m, r) / norm
        factors.append(c)
        residual = max(residual, float(np.abs(r - c * m).max() / scale_r))
    present = [c for c in factors if c is not None]
    spread = 0.0 if not present else max(abs(c / present[0] - 1.0) for c in present)
    return {'passed': residual <= rtol, 'max_relative_residual': residual, 'rtol': rtol,
            'factors': [None if c is None else [c.real, c.imag] for c in factors],
            'common_factor': spread <= rtol, 'factor_spread': spread}


def align(amplitudes_, result):
    """Apply closure factors (per helicity) to member amplitudes a[n, h, k]."""
    require(result.get('passed') is True, 'closure did not pass; members cannot be combined with the cached amplitudes')
    a = np.array(amplitudes_, dtype=complex)
    require(a.ndim == 3 and a.shape[1] == len(result['factors']), 'amplitudes and closure factors differ in helicities')
    for h, c in enumerate(result['factors']):
        a[:, h, :] *= 0.0 if c is None else complex(c[0], c[1])
    return a


def gauge_check(momenta, members, constants):
    """Gauge check: amplitudes do not depend on the gluon reference momenta."""
    a = amplitudes(momenta, members, constants, references=(1, 0))
    b = amplitudes(momenta, members, constants, references=(2, 4))
    scale = max(np.abs(a).max(), 1e-300)
    return float(np.abs(a - b).max() / scale)
