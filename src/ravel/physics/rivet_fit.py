"""Rivet-selected polynomial terms and joint MC covariance for measurement fits.

Only normalized RAW output supplies fitted values. The stored-point comparison
is a diagnostic; shape, exposure and covariance integrity remain requirements.
Joint matrices use integrated bins followed by two integrated flows per stream.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np

from . import amplitude_basis as ab, amplitude_polynomial as polynomial

DEFAULT_TOLERANCE = {'rtol': 1e-8, 'atol': 1e-15, 'covariance_rtol': 1e-7, 'covariance_atol': 1e-20}


def tolerance(value=None):
    value = deepcopy(DEFAULT_TOLERANCE if value is None else value)
    ab.require(type(value) is dict and set(value) == set(DEFAULT_TOLERANCE), 'Born diagnostic needs value and covariance tolerances')
    for key, number in value.items():
        ab.real(number, 'Born diagnostic ' + key)
        ab.require(number >= 0, 'Born diagnostic tolerances must be nonnegative')
    return value


def selected_prediction(doc, hypotheses, histogram, *, edges=None):
    """Validate RAW integrity and map portable term weights to stored-stream IDs.

The returned prediction has the same in-memory layout as amplitude_predictions,
but contains no values or covariances from that producer.
"""
    from . import weighted_events
    roster = polynomial.terms(doc, hypotheses)
    names = weighted_events.stream_names([h['id'] for h in hypotheses], doc['reference'])
    names += [t['weight'] for rows in roster.values() for t in rows]
    ab.require(set(histogram['streams']) == set(names), 'RAW stream roster differs')
    layout = histogram.get('joint_layout')
    ab.require(layout == {'streams': names, 'per_stream': 'bins, underflow, overflow',
                          'units': 'integrated (not divided by bin width)'}, 'RAW joint layout differs')
    actual_edges = ab.edges_from(histogram['edges'])
    ab.require(edges is None or np.array_equal(actual_edges, edges), 'RAW and measurement bin edges differ')
    nb, width = len(actual_edges) - 1, len(actual_edges) + 1
    provenance = histogram.get('provenance')
    representation = provenance.get('representation') if isinstance(provenance, dict) else None
    histogram_path = provenance.get('histogram') if isinstance(provenance, dict) else None
    spec = next((h for h in doc['rivet']['histograms'] if h['path'] == histogram_path), None)
    ab.require(provenance == {'stage': 'rivet-selected', 'showered': 'shower' in doc,
                             'histogram': histogram_path,
                             'normalization': 'RAW/attempted-draws', 'weight_unit': 'pb',
                             'unit': doc['unit'], 'representation': representation}
               and type(provenance['showered']) is bool and spec is not None
               and representation == spec['representation'], 'RAW normalization or stage provenance differs')
    blocks = histogram.get('blocks')
    ab.require(type(blocks) is list and blocks, 'RAW block exposure accounting required')
    ab.require(len({b['id'] for b in blocks}) == len(blocks), 'RAW block exposure roster differs')
    for block in blocks:
        ab.text(block['cohort'], 'RAW block cohort')
        ab.require(type(block['attempted']) is int and block['attempted'] > 0
                   and type(block['events']) is int and 0 <= block['events'] <= block['attempted'],
                   'RAW attempted-draw exposure differs')
    covariance = np.asarray(histogram['joint_covariance'], dtype=float)
    size = len(names) * width
    ab.require(covariance.shape == (size, size) and np.isfinite(covariance).all(), 'RAW joint covariance shape or finiteness differs')
    scale = max(float(np.max(np.abs(covariance))), 1e-300)
    ab.require(np.allclose(covariance, covariance.T, rtol=0, atol=1e-10 * scale), 'RAW joint covariance is not symmetric')
    ab.require(np.linalg.eigvalsh(covariance)[0] >= -1e-10 * scale, 'RAW joint covariance is not positive semidefinite')
    divide = np.diff(actual_edges) if representation == 'differential' else np.ones(nb)
    aliases = {t['weight']: t['stream'] for rows in roster.values() for t in rows}
    streams = {}
    for j, name in enumerate(names):
        stream = deepcopy(histogram['streams'][name])
        values = np.asarray([*stream['values'], stream['underflow'], stream['overflow']], dtype=float)
        ab.require(values.shape == (width,) and np.isfinite(values).all(), 'RAW values or flows differ')
        cov = covariance[j * width:j * width + nb, j * width:j * width + nb] / np.outer(divide, divide)
        supplied_cov = np.asarray(stream['mc_covariance'], dtype=float)
        ab.require(supplied_cov.shape == cov.shape and np.isfinite(supplied_cov).all()
                   and np.allclose(supplied_cov, cov, rtol=1e-8, atol=1e-12 * scale), 'RAW stream and joint covariance differ')
        uncertainty = np.sqrt(np.clip(np.diag(cov), 0, None))
        supplied_uncertainty = np.asarray(stream['uncertainty'], dtype=float)
        ab.require(supplied_uncertainty.shape == (nb,) and np.allclose(supplied_uncertainty, uncertainty,
                                                                     rtol=1e-8, atol=1e-12 * np.sqrt(scale)),
                   'RAW uncertainty and covariance differ')
        stream['kind'] = 'term' if name in aliases else 'difference' if '-minus-' in name else 'prediction'
        streams[aliases.get(name, name)] = stream
    return {'streams': streams, 'definitions': [(aliases.get(n, n), streams[aliases.get(n, n)]['kind']) for n in names],
            'joint': {'covariance': covariance}, 'divide': divide, 'edges': actual_edges,
            'census': deepcopy(blocks), 'provenance': deepcopy(provenance)}


def likelihood_input(doc, hypotheses, prediction, *, ablated=False):
    """A differential-measurement signal fragment, with stacked term covariance.

This fragment also feeds differential.Model directly for several parameters.
The file-backed differential-likelihood scan adapter retains its one-parameter
scan contract; this handoff does not add a multidimensional scan algorithm.
"""
    parameters, _ = polynomial.contract(doc, hypotheses)
    roster = polynomial.terms(doc, hypotheses)
    ab.require(roster, 'Rivet fit requires declared polynomial term weights')
    names = [n for n, _ in prediction['definitions']]
    nb = len(prediction['divide'])
    rows = []
    for hypothesis in hypotheses:
        hid = hypothesis['id']
        if hid == doc['reference']:
            continue
        selected = [t for t in roster[hid] if not ablated or t['kind'] != 'interference']
        indices = [names.index(t['stream']) * (nb + 2) + i for t in selected for i in range(nb)]
        divide = np.tile(prediction['divide'], len(selected))
        covariance = prediction['joint']['covariance'][np.ix_(indices, indices)] / np.outer(divide, divide)
        coordinates = {f'state{i}_{field}': state[field] for i, state in enumerate(hypothesis['states'])
                       for field in ('mass_gev', 'width_gev')}
        rows.append({'id': hid, 'coordinates': coordinates, 'terms': [
            {'powers': t['powers'], 'kind': t['kind'], 'values': prediction['streams'][t['stream']]['values']} for t in selected],
            'mc_covariance': covariance.tolist()})
    return {'schema_version': 1, 'kind': 'differential-likelihood-input',
            'signal': {'convention': 'difference-to-reference', 'difference_reference': doc['reference_description'],
                       'parameters': parameters}, 'hypotheses': rows,
            'reference_prediction': {'values': prediction['streams'][doc['reference']]['values'],
                                     'description': doc['reference_description']},
            'provenance': deepcopy(prediction['provenance'])}


def born_diagnostic(born, selected, *, declared_tolerance=None):
    """Record residuals in values, flows and joint covariance; never reject shifts."""
    tol = tolerance(declared_tolerance)
    names = [n for n, _ in selected['definitions']]
    born_names = born['joint_layout']['streams']
    ab.require(born['edges'] == selected['edges'].tolist(), 'Born diagnostic bin edges differ')
    ab.require(set(names) == set(born_names), 'Born diagnostic stream roster differs')
    nb = len(selected['divide'])
    residuals = {}
    matched = True
    for name in names:
        expected = np.asarray([*born['streams'][name]['values'], born['streams'][name]['underflow'], born['streams'][name]['overflow']])
        actual = np.asarray([*selected['streams'][name]['values'], selected['streams'][name]['underflow'], selected['streams'][name]['overflow']])
        agrees = bool(np.allclose(actual, expected, rtol=tol['rtol'], atol=tol['atol']))
        matched &= agrees
        residuals[name] = {'within_tolerance': agrees, 'values': (actual[:nb] - expected[:nb]).tolist(),
                           'underflow': float(actual[nb] - expected[nb]), 'overflow': float(actual[nb + 1] - expected[nb + 1]),
                           'max_abs': float(np.max(np.abs(actual - expected)))}
    indices = [born_names.index(n) * (nb + 2) + i for n in names for i in range(nb + 2)]
    expected_cov = np.asarray(born['joint_covariance'])[np.ix_(indices, indices)]
    actual_cov = selected['joint']['covariance']
    cov_agrees = bool(np.allclose(actual_cov, expected_cov, rtol=tol['covariance_rtol'], atol=tol['covariance_atol']))
    return {'schema_version': 1, 'kind': 'born-rivet-diagnostic', 'gate': False,
            'status': 'within-tolerance' if matched and cov_agrees else 'outside-tolerance',
            'tolerance': tol, 'tolerance_source': 'caller' if declared_tolerance is not None else 'default',
            'compared_stages': ['Born', 'rivet-selected'], 'fitted_stage': selected['provenance']['stage'],
            'showered': selected['provenance']['showered'], 'streams': residuals,
            'covariance': {'within_tolerance': cov_agrees, 'max_abs': float(np.max(np.abs(actual_cov - expected_cov)))},
            'physics_validated': False}
