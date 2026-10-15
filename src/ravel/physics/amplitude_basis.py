"""Exact post-hoc reweighting of weighted points through a Gram-matrix amplitude basis.

When the amplitude of every hypothesis is linear in a finite set of basis members,

    A_h(theta, x) = sum_k c_k(theta, s) a_{h,k}(x),

with coefficients c_k that depend only on couplings and on propagators of the
partonic invariant s, the squared amplitude summed over helicities is a Hermitian
quadratic form

    |A(theta)|^2 = c(theta, s)^dagger G(x) c(theta, s),
    G_kl(x) = sum_h w_h(x) conj(a_{h,k}(x)) a_{h,l}(x).

Storing G (K*K reals per point) instead of the helicity amplitudes allows any
coupling, mass, width and propagator choice to be evaluated afterwards, exactly, at
the same points. The integration weight of the point multiplies the result.

For final states with identical particles the two pairings are integrated with a
multichannel partition. The partition here is built from a fixed reference
amplitude, so it does not depend on the hypothesis and the weight stays quadratic.
It is still a partition of unity, so the estimator remains unbiased.

Hypothesis documents::

    {"id": "H600",
     "constant": {"<member>": 1 | [re, im]},
     "states": [{"mass_gev": 600, "width_gev": 30, "propagator": "fixed-width",
                 "couplings": {"<member>": 1 | [re, im]}}]}

c_k = constant_k + sum over states of coupling_k * P(s), with
P = 1/(s - M^2 + i M Gamma) for ``fixed-width`` and
P = 1/(s - M^2 + i s Gamma/M) for ``running-width``.
"""
from __future__ import annotations

import itertools
import math

import numpy as np

SCHEMA_VERSION = 1
PROPAGATORS = ('fixed-width', 'running-width')
# Helicity order of four-label processes: (h1, h2, h34, h56), each '-' then '+'.
HELICITY_LABELS = tuple(itertools.product('-+', repeat=4))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def real(value, label='value'):
    require(type(value) in (int, float), f'{label} must be a number, not {type(value).__name__}')
    value = float(value)
    require(math.isfinite(value), f'{label} must be finite')
    return value


def complex_value(value, label='value'):
    if type(value) is list:
        require(len(value) == 2, f'{label} must be a number or a [real, imaginary] pair')
        return complex(real(value[0], label), real(value[1], label))
    return complex(real(value, label), 0.0)


def text(value, label):
    require(isinstance(value, str) and value.strip() and '\n' not in value, f'{label} must be one line of text')
    return value


class Basis:
    """Ordered amplitude basis members."""

    def __init__(self, members):
        require(isinstance(members, (list, tuple)) and members, 'basis needs at least one member')
        names = [text(m, 'basis member') for m in members]
        require(len(set(names)) == len(names), 'basis members must be unique')
        self.members = tuple(names)
        self.index = {m: i for i, m in enumerate(names)}

    def __len__(self):
        return len(self.members)

    def __eq__(self, other):
        return isinstance(other, Basis) and other.members == self.members

    @classmethod
    def from_document(cls, doc):
        if isinstance(doc, (list, tuple)):
            return cls(list(doc))
        require(type(doc) is dict and type(doc.get('members')) is list, 'basis document needs members')
        return cls([m['id'] if type(m) is dict else m for m in doc['members']])


def propagator(s, mass, width, law):
    require(law in PROPAGATORS, f'propagator law must be one of {PROPAGATORS}')
    mass, width = real(mass, 'mass'), real(width, 'width')
    require(mass > 0 and width > 0, 'propagator mass and width must be positive')
    s = np.asarray(s, dtype=float)
    if law == 'fixed-width':
        return 1.0 / (s - mass ** 2 + 1j * mass * width)
    return 1.0 / (s - mass ** 2 + 1j * s * width / mass)


def hypothesis(doc, basis):
    require(type(doc) is dict and set(doc) == {'id', 'constant', 'states'},
            'hypothesis needs exactly id, constant and states')
    text(doc['id'], 'hypothesis id')
    require(type(doc['constant']) is dict and type(doc['states']) is list, 'constant is an object and states a list')
    for member, value in doc['constant'].items():
        require(member in basis.index, f'hypothesis {doc["id"]}: unknown basis member {member!r}')
        complex_value(value, f'hypothesis {doc["id"]} constant {member}')
    for state in doc['states']:
        require(type(state) is dict and set(state) == {'mass_gev', 'width_gev', 'propagator', 'couplings'},
                'state needs exactly mass_gev, width_gev, propagator and couplings')
        propagator(np.zeros(1), state['mass_gev'], state['width_gev'], state['propagator'])
        require(type(state['couplings']) is dict and state['couplings'], 'state needs at least one coupling')
        for member, value in state['couplings'].items():
            require(member in basis.index, f'hypothesis {doc["id"]}: unknown basis member {member!r}')
            complex_value(value, f'hypothesis {doc["id"]} coupling {member}')
    require(doc['constant'] or doc['states'], f'hypothesis {doc["id"]} has no amplitude')
    return doc


def coefficients(doc, basis, s):
    """Coefficient matrix c[n, k] of one hypothesis at partonic invariants s[n]."""
    s = np.asarray(s, dtype=float)
    c = np.zeros((s.size, len(basis)), dtype=complex)
    for member, value in doc['constant'].items():
        c[:, basis.index[member]] += complex_value(value)
    for state in doc['states']:
        p = propagator(s, state['mass_gev'], state['width_gev'], state['propagator'])
        for member, value in state['couplings'].items():
            c[:, basis.index[member]] += complex_value(value) * p
    return c


def _outer(vectors, weights):
    """sum_h w[n,h] conj(a[n,h,k]) a[n,h,l]."""
    return np.einsum('nh,nhk,nhl->nkl', weights, np.conj(vectors), vectors)


def point_grams(direct, swap=None, *, identical=None, selected_direct=None, exchange=None, reference=None,
                normalization=None):
    """Per-point Gram matrices G[n, k, l] from basis helicity amplitudes a[n, h, k].

    Distinct particles: G = sum_h conj(a_h) a_h^T.
    Identical particles (``identical[n]``), integrated with the pairing mapping chosen
    by ``selected_direct[n]``: for helicities with ``exchange[h]`` both pairings
    interfere, |m - w|^2, weighted by 2 P_ref; otherwise the mapped pairing alone,
    weighted by 2. P_ref = |ref_selected|^2 / (|ref_m|^2 + |ref_w|^2) uses the
    fixed reference coefficients ``reference[n, k]`` (equal split if both vanish).
    """
    direct = np.asarray(direct, dtype=complex)
    require(direct.ndim == 3, 'amplitudes must have shape (points, helicities, members)')
    n, h, k = direct.shape
    norm = np.ones(n) if normalization is None else np.asarray(normalization, dtype=float)
    require(norm.shape == (n,) and np.isfinite(norm).all(), 'normalization must be finite, one per point')
    require(np.isfinite(direct).all(), 'amplitudes must be finite')
    if swap is None:
        require(identical is None or not np.any(identical), 'identical particles need the swapped pairing')
        return _outer(direct, np.broadcast_to(norm[:, None], (n, h)))
    swap = np.asarray(swap, dtype=complex)
    require(swap.shape == direct.shape and np.isfinite(swap).all(), 'swapped amplitudes must match the direct shape')
    identical = np.asarray(identical, dtype=bool)
    selected = np.asarray(selected_direct, dtype=bool)
    exchange = np.asarray(exchange, dtype=bool)
    reference = np.asarray(reference, dtype=complex)
    require(identical.shape == (n,) and selected.shape == (n,), 'identical and selected_direct flags, one per point')
    require(exchange.shape == (h,), 'exchange flag, one per helicity')
    require(reference.shape == (n, k), 'reference coefficients, one row per point')
    chosen = np.where(selected[:, None, None], direct, swap)
    ref_m = np.einsum('nhk,nk->nh', direct, reference)
    ref_w = np.einsum('nhk,nk->nh', swap, reference)
    denominator = np.abs(ref_m) ** 2 + np.abs(ref_w) ** 2
    ref_chosen = np.where(selected[:, None], np.abs(ref_m) ** 2, np.abs(ref_w) ** 2)
    with np.errstate(invalid='ignore', divide='ignore'):
        partition = np.where(denominator > 0, ref_chosen / np.where(denominator > 0, denominator, 1.0), 0.5)
    # Distinct-particle points use the direct pairing only.
    G = np.where(identical[:, None, None], 0.0, 1.0) * _outer(direct, np.broadcast_to(norm[:, None], (n, h)))
    mixed = np.where(exchange[None, :], 2.0 * partition, 0.0) * norm[:, None]
    single = np.where(exchange[None, :], 0.0, 2.0) * norm[:, None]
    same = _outer(direct - swap, mixed) + _outer(chosen, np.broadcast_to(single, (n, h)))
    return G + np.where(identical[:, None, None], 1.0, 0.0) * same


def evaluate(G, c):
    """Weights Re(c^dagger G c) for every point."""
    return np.einsum('nk,nkl,nl->n', np.conj(c), G, c).real


def pairing_square(amplitudes, c, *, identical, selected_direct, exchange, normalization):
    """Replay the hypothesis-dependent partition from retained pairing amplitudes.

    Unlike a reference-partition Gram, this estimator is generally rational in
    the coefficients. It must not be exported as polynomial term weights.
    Both-zero exchange channels contribute their continuous zero limit.
    """
    a, c = np.asarray(amplitudes, complex), np.asarray(c, complex)
    require(a.ndim == 4 and a.shape[1] == 2, 'pairings need (points, 2, helicities, members)')
    n, _, h, k = a.shape
    require(c.shape == (n, k) and np.isfinite(a).all() and np.isfinite(c).all(), 'finite matching coefficients required')
    same, selected, exch = (np.asarray(v) for v in (identical, selected_direct, exchange))
    require(same.shape == selected.shape == (n,) and exch.shape == (h,)
            and all(v.dtype == bool for v in (same, selected, exch)), 'literal pairing and exchange flags required')
    norm = np.asarray(normalization, float)
    require(norm.shape == (n,) and np.isfinite(norm).all(), 'finite pairing normalization required')
    m, s = (np.einsum('nhk,nk->nh', a[:, j], c) for j in (0, 1))
    chosen = np.where(selected[:, None], m, s)
    scale = np.maximum(np.abs(m), np.abs(s))
    safe = np.where(scale > 0, scale, 1.)
    x, y = m / safe, s / safe
    denom = np.abs(x) ** 2 + np.abs(y) ** 2
    partition = np.abs(x - y) ** 2 / np.where(denom > 0, denom, 1.)
    square = np.where(same[:, None], 2 * np.abs(chosen) ** 2 * np.where(exch, partition, 1.), np.abs(m) ** 2)
    result = square.sum(axis=1) * norm
    require(np.isfinite(result).all(), 'pairing square overflow')
    return result


def pack(G):
    """K*K reals per point: diagonal, then upper-triangle real parts, then imaginary parts."""
    G = np.asarray(G)
    k = G.shape[-1]
    upper = np.triu_indices(k, 1)
    return np.concatenate([np.real(np.diagonal(G, axis1=1, axis2=2)),
                           np.real(G[:, upper[0], upper[1]]), np.imag(G[:, upper[0], upper[1]])], axis=1)


def unpack(packed, k):
    packed = np.asarray(packed, dtype=float)
    require(packed.ndim == 2 and packed.shape[1] == k * k, 'packed Gram rows need K*K values')
    n = packed.shape[0]
    upper = np.triu_indices(k, 1)
    m = len(upper[0])
    G = np.zeros((n, k, k), dtype=complex)
    G[:, np.arange(k), np.arange(k)] = packed[:, :k]
    values = packed[:, k:k + m] + 1j * packed[:, k + m:]
    G[:, upper[0], upper[1]] = values
    G[:, upper[1], upper[0]] = np.conj(values)
    return G


def edges_from(edges):
    require(isinstance(edges, (list, tuple)) and len(edges) >= 2, 'at least two bin edges required')
    values = [real(e, 'bin edge') for e in edges]
    require(all(b > a for a, b in zip(values, values[1:])), 'bin edges must increase strictly')
    return np.array(values)


def bin_index(values, edges):
    """Bin index per value: 0..B-1 for bins, B for underflow, B+1 for overflow (lower edge inclusive)."""
    edges = np.asarray(edges, dtype=float)
    b = len(edges) - 1
    values = np.asarray(values, dtype=float)
    index = np.searchsorted(edges, values, side='right') - 1
    index = np.where(values < edges[0], b, index)
    return np.where(values >= edges[-1], b + 1, index)


def histogram(values, weights, edges):
    edges = np.asarray(edges, dtype=float)
    return np.bincount(bin_index(values, edges), weights=np.asarray(weights, dtype=float), minlength=len(edges) + 1)


def stream_names(hypothesis_ids, reference):
    """Absolute predictions for every hypothesis, then signed differences to the reference."""
    require(reference in hypothesis_ids, f'reference hypothesis {reference!r} must be one of the hypotheses')
    require(len(set(hypothesis_ids)) == len(hypothesis_ids), 'hypothesis ids must be unique')
    return [*hypothesis_ids, *[f'delta:{h}' for h in hypothesis_ids if h != reference]]


def centered_blocks(cohorts):
    """Mean and covariance of the mean from independent equal-exposure blocks.

    Independent cohorts (for example lepton-flavour channels integrated separately)
    add: their means and covariances sum. Within a cohort the covariance of the mean
    is sum (v - m)(v - m)^T / (r (r - 1)) over its r blocks.
    """
    require(type(cohorts) is dict and cohorts, 'at least one cohort of blocks required')
    size = None
    mean = cov = None
    rows = []
    for name, blocks in cohorts.items():
        blocks = [np.asarray(b, dtype=float) for b in blocks]
        require(len(blocks) >= 2, f'cohort {name} needs at least two independent blocks')
        for b in blocks:
            size = b.shape if size is None else size
            require(b.shape == size and b.ndim == 1, 'every block vector must have the same length')
            require(np.isfinite(b).all(), 'block vectors must be finite')
        matrix = np.array(blocks)
        r = len(blocks)
        m = matrix.mean(axis=0)
        centered = matrix - m
        c = centered.T @ centered / (r * (r - 1))
        mean = m if mean is None else mean + m
        cov = c if cov is None else cov + c
        rows.append({'cohort': name, 'blocks': r, 'mean': m.tolist()})
    return {'mean': mean, 'covariance': cov, 'cohorts': rows,
            'semantics': 'centered covariance of the mean of independent equal-exposure blocks; cohorts add'}
