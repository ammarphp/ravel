"""Applicability checks for reinterpreting measurements, and interpretation traps.

- ``unfolding_guard``: an unfolded measurement is validated for deviations from
  the unfolding model up to some size (the paper's stress tests). Given a cited
  maximum relative deviation, flag every scanned parameter value whose
  prediction differs from the reference by more than that in any bin.
- ``k_factor_policy``: a K-factor applied to an interference term needs a cited
  or requester-stated value and a declared nuisance on that term.
- ``interpretation_traps``: short, checkable physics notes shown to the agent
  with every measurement reinterpretation.
"""
from __future__ import annotations

import json

import numpy as np

from ravel.paths import package_data_path

TRAPS_FILE = package_data_path('inference', 'interpretation_traps.json')


def _cited(declaration, label):
    if type(declaration) is not dict:
        raise ValueError(label + ' must be an object')
    origin = declaration.get('origin', 'cited')
    if origin == 'cited':
        if type(declaration.get('citation')) is not str or not declaration['citation'].strip():
            raise ValueError(label + ' needs a citation')
    elif origin == 'requester-assumption':
        if type(declaration.get('statement')) is not str or not declaration['statement'].strip():
            raise ValueError(label + ' needs the requester statement')
    else:
        raise ValueError(label + ' origin must be cited or requester-assumption')


def unfolding_guard(model, parameter, grid, declaration, fixed=None):
    _cited(declaration, 'the unfolding validity range')
    limit = declaration.get('max_relative_deviation')
    if type(limit) not in (int, float) or not limit > 0:
        raise ValueError('max_relative_deviation must be a positive number')
    fixed = dict(fixed or {})
    deviations = []
    for x in np.asarray(grid, float):
        delta = model.difference({**fixed, parameter: float(x)})
        deviations.append(float(np.max(np.abs(delta) / np.abs(model.reference))))
    flagged = [float(x) for x, d in zip(grid, deviations) if d > limit]
    return {'max_relative_deviation': float(limit),
            'provenance': declaration.get('citation') or declaration.get('statement'),
            'fires': bool(flagged), 'first_flagged_value': flagged[0] if flagged else None,
            'flagged_values': flagged, 'largest_deviation_on_scan': max(deviations),
            'meaning': 'parameter values whose predicted spectrum differs from the reference by more than the '
                       'validated deviation in at least one bin; results there rely on unfolding outside its tested range'}


def mark_edges(region, guard, parameter):
    """Annotate interval edges that lie where the unfolding guard fires."""
    if not guard or not guard['fires']:
        return region
    flagged = set(guard['flagged_values'])
    first = guard['first_flagged_value']
    for row in region.get('intervals', []):
        for edge in (row['low'], row['high']):
            if edge.get('value') is not None and edge['value'] >= first:
                edge['outside_unfolding_validity'] = True
    region['unfolding_guard_parameter'] = parameter
    region['unfolding_guard_flagged_points'] = len(flagged)
    return region


def k_factor_policy(terms, nuisances):
    findings = []
    for k, term in enumerate(terms):
        scale = term.get('scale')
        if scale is None:
            continue
        _cited(scale, f'term {k} scale factor')
        if term.get('kind') == 'interference':
            covered = any(nu.get('applies_to') == f'term:{k}' for nu in nuisances)
            if not covered:
                findings.append({'term': k, 'finding': 'unconstrained_interference_k_factor',
                                 'detail': 'a scale factor on an interference term has no declared uncertainty '
                                           'nuisance on that term; no universal K-factor applies to interference'})
    return findings


def interpretation_traps():
    doc = json.loads(TRAPS_FILE.read_text())
    traps = doc['traps']
    for trap in traps:
        if set(trap) != {'id', 'statement', 'check'}:
            raise ValueError('interpretation traps need id, statement and check')
    return traps
