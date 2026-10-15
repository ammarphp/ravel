"""Supplied Born pair-selection definitions for retained momentum caches.

This is a two-pair projection, with every acceptance/ranking/window threshold
supplied by the source descriptor. It makes no particle-level equivalence claim.
"""
from __future__ import annotations

import itertools
import math

import numpy as np

from . import amplitude_basis as ab


def validate(spec):
    fields = {'particles', 'acceptance', 'rank_pt_min', 'pairing_mass', 'primary_window',
              'secondary_min', 'secondary_max', 'same_pair_dr', 'same_species_dr',
              'different_species_dr', 'all_pair_mass_min', 'overlap_dr'}
    ab.require(type(spec) is dict and set(spec) == fields, 'complete supplied pair selection required')
    ids = spec['particles']
    ab.require(type(ids) is list and len(ids) == 4 and len(set(ids)) == 4
               and all(type(i) is int and i >= 0 for i in ids), 'four distinct particle indices required')
    acceptance = spec['acceptance']
    ab.require(type(acceptance) is dict and acceptance, 'supplied species acceptance required')
    for key, row in acceptance.items():
        ab.require(key.isdigit() and int(key) > 0 and set(row) == {'pt_min', 'abs_eta_max'}, 'species acceptance fields differ')
        for value in row.values():
            ab.require(ab.real(value) >= 0, 'nonnegative acceptance required')
    for name in ('rank_pt_min', 'primary_window'):
        ab.require(type(spec[name]) is list and len(spec[name]) == (3 if name == 'rank_pt_min' else 2), 'selection window dimensions differ')
        for value in spec[name]:
            ab.real(value)
    ab.require(spec['primary_window'][0] < spec['primary_window'][1], 'ordered primary window required')
    curve = spec['secondary_min']
    ab.require(type(curve) is dict and set(curve) == {'knots', 'values'}, 'secondary minimum needs knots and values')
    ab.edges_from(curve['knots'])
    ab.require(len(curve['values']) == len(curve['knots']), 'secondary minimum knot population differs')
    for value in curve['values']:
        ab.real(value)
    for name in fields - {'particles', 'acceptance', 'rank_pt_min', 'primary_window', 'secondary_min'}:
        ab.require(ab.real(spec[name], name) >= 0, 'nonnegative selection threshold required')
    return spec


def select(momenta, pdg, spec):
    """Boolean mask; strict pT/eta cuts and lower-inclusive mass windows."""
    validate(spec)
    p = np.asarray(momenta, float)
    ids = spec['particles']
    ab.require(p.ndim == 3 and p.shape[2] == 4 and max(ids) < p.shape[1]
               and len(pdg) == p.shape[1] and np.isfinite(p).all(), 'finite momenta and declared particle identities required')
    codes = [pdg[i] for i in ids]
    ab.require(all(str(abs(i)) in spec['acceptance'] for i in codes), 'selection lacks species acceptance')
    kept = []
    for event in p[:, ids]:
        pt = np.hypot(event[:, 0], event[:, 1])
        if np.any(pt <= 0):
            kept.append(False)
            continue
        eta, phi = np.arcsinh(event[:, 2] / pt), np.arctan2(event[:, 1], event[:, 0])
        if any(pt[i] <= spec['acceptance'][str(abs(code))]['pt_min'] or
               abs(eta[i]) >= spec['acceptance'][str(abs(code))]['abs_eta_max'] for i, code in enumerate(codes)):
            kept.append(False)
            continue

        def mass(indices):
            q = event[list(indices)].sum(axis=0)
            square = q[3] ** 2 - q[:3] @ q[:3]
            ab.require(square >= 0, 'negative supplied pair invariant')
            return math.sqrt(square)

        def dr(i, j):
            angle = abs(phi[i] - phi[j])
            return math.hypot(eta[i] - eta[j], min(angle, 2 * math.pi - angle))

        pairs = [(i, j) for i in range(4) for j in range(i) if codes[i] == -codes[j]]
        distances = [abs(mass(pair) - spec['pairing_mass']) for pair in pairs]
        ab.require(len(set(distances)) == len(distances), 'ambiguous exact pair-ranking tie')
        ranked = sorted(pairs, key=lambda pair: abs(mass(pair) - spec['pairing_mass']))
        quad = None
        for first, second in itertools.combinations(ranked, 2):
            if set(first) & set(second) or any(dr(i, j) < spec['overlap_dr'] for i in first for j in second):
                continue
            ordered = sorted((pt[i] for i in (*first, *second)), reverse=True)
            if all(v > cut for v, cut in zip(ordered, spec['rank_pt_min'])):
                quad = first, second
                break
        if quad is None:
            kept.append(False)
            continue
        first, second = quad
        curve = spec['secondary_min']
        minimum = np.interp(mass(range(4)), curve['knots'], curve['values'])
        cross = spec['same_species_dr'] if abs(codes[first[0]]) == abs(codes[second[0]]) else spec['different_species_dr']
        kept.append(bool(spec['primary_window'][0] <= mass(first) < spec['primary_window'][1]
                         and minimum <= mass(second) < spec['secondary_max']
                         and all(dr(*pair) >= spec['same_pair_dr'] for pair in quad)
                         and all(dr(i, j) >= cross for i in first for j in second)
                         and all(mass(pair) >= spec['all_pair_mass_min'] for pair in pairs)))
    return np.asarray(kept, bool)
