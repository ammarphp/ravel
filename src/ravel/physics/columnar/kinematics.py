"""Vectorised four-vector arithmetic for reconstructed and parton-level objects.

All functions accept NumPy arrays (one value per event or per object) and, where they
use only universal functions, Awkward arrays. Energies and momenta are in GeV; angles
are in radians. A four-vector array has shape ``(n, 4)`` ordered ``(px, py, pz, E)``.
"""
import numpy as np


def p4(pt, eta, phi, mass):
    """Cartesian components from (pT, eta, phi, m)."""
    px = pt * np.cos(phi)
    py = pt * np.sin(phi)
    pz = pt * np.sinh(eta)
    e = np.sqrt(px * px + py * py + pz * pz + mass * mass)
    return px, py, pz, e


def from_cartesian(px, py, pz, e):
    """(pT, eta, phi, m) from Cartesian components; eta is +-inf along the beam."""
    pt = np.hypot(px, py)
    p = np.sqrt(pt * pt + pz * pz)
    with np.errstate(divide='ignore', invalid='ignore'):
        eta = np.arcsinh(np.where(pt > 0, pz / np.where(pt > 0, pt, 1.0), np.sign(pz) * np.inf))
    phi = np.arctan2(py, px)
    return pt, eta, phi, mass(px, py, pz, e)


def minkowski(v):
    """Squared invariant mass of ``(n, 4)`` vectors (may be slightly negative from rounding)."""
    return v[..., 3] ** 2 - v[..., 0] ** 2 - v[..., 1] ** 2 - v[..., 2] ** 2


def mass(px, py, pz, e):
    """Invariant mass; a negative squared mass from rounding is reported as zero."""
    m2 = e * e - px * px - py * py - pz * pz
    return np.sqrt(np.maximum(m2, 0.0))


def delta_phi(phi1, phi2):
    """Absolute azimuthal separation in [0, pi]."""
    d = np.mod(phi1 - phi2 + np.pi, 2 * np.pi) - np.pi
    return np.abs(d)


def delta_r(eta1, phi1, eta2, phi2):
    return np.sqrt((eta1 - eta2) ** 2 + delta_phi(phi1, phi2) ** 2)


def mt(pt, phi, mass_, met, met_phi, *, massless=True):
    """Transverse mass of one visible system with the missing transverse momentum.

    ``massless=True`` uses sqrt(2 pT MET (1 - cos dphi)); otherwise the visible mass
    enters through its transverse energy and the invisible system is massless.
    """
    cos = np.cos(phi - met_phi)
    if massless:
        return np.sqrt(np.maximum(2.0 * pt * met * (1.0 - cos), 0.0))
    et = np.sqrt(mass_ * mass_ + pt * pt)
    return np.sqrt(np.maximum(mass_ * mass_ + 2.0 * (et * met - pt * met * cos), 0.0))


def neutrino_pz(lepton, met, *, w_mass):
    """Longitudinal neutrino momentum from the on-shell W constraint.

    Returns ``(pz, real)``. When two real solutions exist the smaller |pz| is chosen; when
    none exists the real part of the complex pair is returned and ``real`` is False.
    """
    lepton = np.asarray(lepton, float)
    met = np.asarray(met, float)
    ml2 = np.maximum(minkowski(lepton), 0.0)
    el, plz = lepton[:, 3], lepton[:, 2]
    mu = (w_mass ** 2 - ml2) / 2.0 + lepton[:, 0] * met[:, 0] + lepton[:, 1] * met[:, 1]
    a = el * el - plz * plz
    ptnu2 = met[:, 0] ** 2 + met[:, 1] ** 2
    disc = mu * mu - a * ptnu2
    real = disc >= 0
    root = el * np.sqrt(np.where(real, disc, 0.0))
    base = mu * plz
    first, second = (base + root) / a, (base - root) / a
    pz = np.where(np.abs(first) <= np.abs(second), first, second)
    return np.where(real, pz, base / a), real


def aplanarity(px, py, pz):
    """3/2 times the smallest eigenvalue of the normalised momentum tensor.

    Arrays have shape (events, objects); padding entries must be zero.
    """
    px, py, pz = (np.asarray(x, float) for x in (px, py, pz))
    comps = np.stack([px, py, pz], axis=-1)
    norm = (comps ** 2).sum(axis=(-1, -2))
    tensor = np.einsum('eoa,eob->eab', comps, comps)
    with np.errstate(invalid='ignore', divide='ignore'):
        tensor = tensor / norm[:, None, None]
    out = np.full(len(px), np.nan)
    good = norm > 0
    if good.any():
        eig = np.linalg.eigvalsh(tensor[good])
        out[good] = 1.5 * np.maximum(eig[:, 0], 0.0)
    return out
