"""Declared amplitude monomials and their signed quadratic weight streams.

The existing single ``coupling_scaling`` contract is retained. For several
couplings, ``coupling_polynomial`` supplies parameter descriptors and components
``{states: [indices], powers: {parameter: exponent}}``. Disjoint state groups
multiply declared amplitude monomials; constants and remaining states are fixed.
Pair products give the cross-section polynomial, without fitting its coefficients.
"""
from __future__ import annotations

from itertools import combinations_with_replacement

import numpy as np

from . import amplitude_basis as ab


def contract(doc, hypotheses):
    scaling, polynomial = doc.get('coupling_scaling'), doc.get('coupling_polynomial')
    ab.require(scaling is None or polynomial is None, 'declare one coupling polynomial contract')
    if scaling is None and polynomial is None:
        return [], []
    if scaling is not None:
        ab.require(type(scaling) is dict and set(scaling) == {'parameter', 'power', 'states', 'mc_covariance_at'},
                   'coupling_scaling needs parameter, power, states and mc_covariance_at')
        ab.text(scaling['parameter'], 'coupling parameter')
        ab.require(type(scaling['power']) is int and 1 <= scaling['power'] <= 8, 'coupling power from 1 to 8')
        ab.real(scaling['mc_covariance_at'], 'mc_covariance_at')
        parameters = [{'name': scaling['parameter'], 'unit': '', 'label': 'Coupling scale factor'}]
        components = [{'states': scaling['states'], 'powers': {scaling['parameter']: scaling['power']}}]
    else:
        ab.require(type(polynomial) is dict and set(polynomial) == {'parameters', 'components'},
                   'coupling_polynomial needs parameters and components')
        parameters, components = polynomial['parameters'], polynomial['components']
        ab.require(type(parameters) is list and parameters, 'coupling parameters required')
        for parameter in parameters:
            ab.require(type(parameter) is dict and set(parameter) == {'name', 'unit', 'label'},
                       'coupling parameters need name, unit and label')
            ab.text(parameter['name'], 'coupling parameter')
            ab.text(parameter['label'], 'coupling label')
            ab.require(type(parameter['unit']) is str, 'coupling unit must be a string')
    names = [p['name'] for p in parameters]
    ab.require(len(set(names)) == len(names), 'distinct coupling parameters required')
    ab.require(type(components) is list and components, 'amplitude components required')
    states = []
    for component in components:
        ab.require(type(component) is dict and set(component) == {'states', 'powers'},
                   'amplitude component needs states and powers')
        indices, powers = component['states'], component['powers']
        ab.require(type(indices) is list and indices and all(type(i) is int and i >= 0 for i in indices),
                   'states lists scaled state indices')
        ab.require(type(powers) is dict and powers and set(powers) <= set(names)
                   and all(type(p) is int and 1 <= p <= 8 for p in powers.values()),
                   'amplitude powers map declared parameters to integers from 1 to 8')
        states += indices
    ab.require(len(set(states)) == len(states), 'scaled state groups must be disjoint')
    ab.require(set(names) == {p for c in components for p in c['powers']}, 'every coupling parameter must be used')
    reference = next(h for h in hypotheses if h['id'] == doc['reference'])
    ab.require(not any(i < len(reference['states']) for i in states), 'the reference hypothesis cannot contain scaled states')
    for hypothesis in hypotheses:
        if hypothesis['id'] != doc['reference'] and polynomial is not None:
            ab.require(all(i < len(hypothesis['states']) for i in states), 'scaled states must exist in every tested hypothesis')
    return parameters, components


def terms(doc, hypotheses):
    """Term ordering, powers and portable event-weight names (no values)."""
    _, components = contract(doc, hypotheses)
    if not components:
        return {}
    powers = [{}, *[c['powers'] for c in components]]
    pairs = list(combinations_with_replacement(range(len(powers)), 2))
    result = {}
    for hypothesis in hypotheses:
        hid = hypothesis['id']
        if hid == doc['reference']:
            continue
        rows = []
        for k, (i, j) in enumerate(pairs):
            power = {p: powers[i].get(p, 0) + powers[j].get(p, 0) for p in set(powers[i]) | set(powers[j])}
            kind = 'other' if i == j == 0 else 'pure-signal' if i == j else 'interference'
            suffix = ('constant', 'interference', 'pure-signal')[k] if doc.get('coupling_scaling') else f'term-{k}'
            rows.append({'stream': hid + ':' + suffix, 'weight': hid + '--' + suffix,
                         'powers': power, 'kind': kind, 'pair': (i, j)})
        result[hid] = rows
    return result


def definitions(doc, basis, hypotheses):
    """(stored-stream name, portable weight name, function(Gram, s)) rows."""
    _, components = contract(doc, hypotheses)
    roster = terms(doc, hypotheses)
    if not roster:
        return []
    reference = next(h for h in hypotheses if h['id'] == doc['reference'])
    scaled = {i for c in components for i in c['states']}
    result = []
    for hypothesis in hypotheses:
        hid = hypothesis['id']
        if hid == doc['reference']:
            continue
        fixed = {**hypothesis, 'states': [s for i, s in enumerate(hypothesis['states']) if i not in scaled]}
        amplitudes = [fixed, *[{'id': hid, 'constant': {},
                              'states': [hypothesis['states'][i] for i in c['states'] if i < len(hypothesis['states'])]}
                             for c in components]]
        for term in roster[hid]:
            i, j = term['pair']

            def evaluate(gram, invariant, i=i, j=j, amplitudes=amplitudes):
                left = ab.coefficients(amplitudes[i], basis, invariant)
                if i == j:
                    value = ab.evaluate(gram, left)
                    if i == 0:
                        value = value - ab.evaluate(gram, ab.coefficients(reference, basis, invariant))
                    return value
                right = ab.coefficients(amplitudes[j], basis, invariant)
                return 2. * np.einsum('nk,nkl,nl->n', np.conj(left), gram, right).real

            result.append((term['stream'], term['weight'], evaluate))
    return result
