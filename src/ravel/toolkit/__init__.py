"""Small, tested functions for authored analysis code.

An authored analysis step (``ravel authored-analysis``) imports these instead of
re-deriving them. They are thin facades over the columnar engine's tested code:

- four-vectors and kinematics: ``p4``, ``invariant_mass``, ``delta_phi``, ``delta_r``,
  ``transverse_mass``, ``neutrino_pz``, ``aplanarity``, ``mt2``, ``mt2w``, ``modified_topness``;
- selection: ``overlap_mask`` (objects farther than a cone from every object of another
  collection) and ``leading`` (the n highest-pT objects);
- normalisation: ``event_scale`` (cross section x luminosity / sum of weights, with the
  sources of each input);
- expected significance: ``asimov_significance`` for a counting experiment, with an
  optional absolute background uncertainty.

The lint of an authored step flags code that defines a function with one of these names.
"""
import math

import awkward as ak
import numpy as np

from ravel.physics.columnar.kinematics import aplanarity, delta_phi, delta_r, neutrino_pz, p4
from ravel.physics.columnar.kinematics import mt as transverse_mass
from ravel.physics.columnar.mt2 import modified_topness, mt2, mt2w

FUNCTIONS = ('p4', 'invariant_mass', 'delta_phi', 'delta_r', 'transverse_mass', 'neutrino_pz', 'aplanarity',
             'mt2', 'mt2w', 'modified_topness', 'overlap_mask', 'leading', 'event_scale', 'asimov_significance')


def invariant_mass(pt, eta, phi, mass):
    """Invariant mass of all objects of each event (jagged Awkward or 1-D NumPy per event)."""
    px, py, pz, e = p4(pt, eta, phi, mass)
    if isinstance(pt, ak.Array) and pt.ndim > 1:
        px, py, pz, e = (ak.to_numpy(ak.sum(c, axis=1)) for c in (px, py, pz, e))
    m2 = e * e - px * px - py * py - pz * pz
    return np.sqrt(np.maximum(m2, 0.0))


def overlap_mask(eta, phi, other_eta, other_phi, cone):
    """True for each object with no object of the other collection within delta R < cone."""
    pairs = ak.cartesian({'a': ak.zip({'eta': eta, 'phi': phi}), 'b': ak.zip({'eta': other_eta, 'phi': other_phi})},
                         axis=1, nested=True)
    close = delta_r(pairs.a.eta, pairs.a.phi, pairs.b.eta, pairs.b.phi) < cone
    return ~ak.any(close, axis=2)


def leading(objects, n, *, key='pt'):
    """The n objects with the largest `key` in each event, in decreasing order."""
    order = ak.argsort(objects[key], axis=1, ascending=False, stable=True)
    return objects[order][:, :n]


def event_scale(*, cross_section_pb, cross_section_source, luminosity_ifb, luminosity_source, sum_of_weights):
    """Per-unit-weight scale to expected events, with the sources of each input."""
    for value, label in ((cross_section_pb, 'cross_section_pb'), (luminosity_ifb, 'luminosity_ifb'),
                         (sum_of_weights, 'sum_of_weights')):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{label} must be a positive finite number')
    for text, label in ((cross_section_source, 'cross_section_source'), (luminosity_source, 'luminosity_source')):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f'{label} must name where the value comes from')
    return {'scale': cross_section_pb * 1000.0 * luminosity_ifb / sum_of_weights,
            'cross_section_pb': cross_section_pb, 'cross_section_source': cross_section_source,
            'luminosity_ifb': luminosity_ifb, 'luminosity_source': luminosity_source,
            'sum_of_weights': sum_of_weights}


def asimov_significance(s, b, sigma_b=0.0):
    """Median discovery significance of a counting experiment (Cowan, Cranmer, Gross, Vitells).

    ``sigma_b`` is the absolute uncertainty of the background expectation.
    """
    if not (s >= 0 and b > 0 and sigma_b >= 0) or not all(math.isfinite(x) for x in (s, b, sigma_b)):
        raise ValueError('need s >= 0, b > 0 and sigma_b >= 0')
    if sigma_b == 0:
        return math.sqrt(max(2.0 * ((s + b) * math.log1p(s / b) - s), 0.0))
    v = sigma_b * sigma_b
    term1 = (s + b) * math.log((s + b) * (b + v) / (b * b + (s + b) * v))
    term2 = b * b / v * math.log1p(v * s / (b * (b + v)))
    return math.sqrt(max(2.0 * (term1 - term2), 0.0))
