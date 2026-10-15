"""Pure checks of supplied measurement bundles and prescription records.

Each named function accepts two JSON objects or local JSON paths and returns
located error strings; an empty list means only that this supplied contract
passes. No native program, optimizer, acquisition or acceptance is invoked.
``run(check_id, bundle, record)`` produces the existing check-result envelope.
The registration fragments specify the broker and knowledge integration seam.

Bundle fields: bins, values, frame, normalization, covariance, uncertainties,
theory_covariance, source_version and datasets. Record sections are named after
their physical quantities: inverse, prediction, alphas, scale, nonperturbative,
unfolding, tune, pdf, ew, parameters, combination, validity and amplitudes.
All scientific populations, thresholds, definitions and source identifiers are
supplied. Arithmetic comparisons use floating-point roundoff tolerances only,
relative to the compared quantities and therefore independent of their unit.
Closure, stress and coverage criteria must be supplied prospectively; checking
them here neither authenticates their provenance nor certifies applicability.
"""
from __future__ import annotations

from copy import deepcopy
from functools import wraps
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np

from ravel.paths import package_data_path

CHECKS = (
    'sm.frame_declared', 'sm.covariance_assembled', 'sm.normalized_rule',
    'sm.theory_cov_included', 'sm.prediction_convention', 'sm.alphas_consistent',
    'sm.prescription_declared', 'sm.np_once', 'sm.unfolding_closure',
    'sm.unfolding_coverage', 'sm.regularization_declared', 'sm.tune_heldout',
    'sm.pdf_not_circular', 'sm.tolerance_declared', 'sm.ew_scheme',
    'sm.parametrization_range', 'sm.measurement_overlap', 'sm.validity_range',
    'sm.reference_version', 'sm.pdf_error_type', 'sm.ew_combination',
    'sm.amplitude_complete',
)
MAX_BYTES = 2 * 1024 * 1024
MAX_BINS = 256


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    _require(isinstance(value, str) and bool(value.strip()), 'nonempty declaration required')
    return value


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value), 'finite numeric value required')
    return value


def _labels(value, *, allow_empty=False):
    _require(isinstance(value, list) and (allow_empty or bool(value)) and len(value) <= 4096,
             'bounded identity list required')
    _require(all(isinstance(v, str) and bool(v.strip()) for v in value), 'identity strings required')
    _require(len(set(value)) == len(value), 'duplicate identities')
    return set(value)


def _json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            _require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = item
        return result

    def constant(_):
        raise ValueError('nonfinite JSON')

    if isinstance(value, (str, Path)):
        path = Path(value)
        _require(not any(p.is_symlink() for p in (path, *path.parents)), 'regular JSON path required')
        _require(path.is_file() and path.stat().st_size <= MAX_BYTES, 'bounded JSON file required')
        with path.open('rb') as source:
            raw = source.read(MAX_BYTES + 1)
        _require(len(raw) <= MAX_BYTES, 'JSON exceeds byte bound')
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    _require(isinstance(value, dict), 'JSON object required')
    # Also reject nonfinite values in caller-supplied objects, including unused fields.
    raw = json.dumps(value, allow_nan=False)
    _require(len(raw.encode()) <= MAX_BYTES, 'record exceeds byte bound')
    return value


def _check(function):
    @wraps(function)
    def checked(bundle, record):
        try:
            function(_json(bundle), _json(record))
        except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError,
                RecursionError, np.linalg.LinAlgError) as exc:
            return [function.__name__ + ': ' + str(exc)]
        return []
    return checked


def _array(value, *, ndim=1):
    _require(isinstance(value, list) and bool(value), 'nonempty numeric array required')
    flat = [v for row in value for v in row] if ndim == 2 else value
    _require(bool(flat) and all(type(v) in (int, float) for v in flat), 'numeric array entries required')
    array = np.asarray(value, dtype=float)
    _require(array.ndim == ndim and np.isfinite(array).all(), 'finite array of declared dimension required')
    _require(array.size <= MAX_BINS * MAX_BINS, 'array exceeds size bound')
    return array


def _close(first, second, message, *, scale=None):
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    _require(first.shape == second.shape, message)
    if scale is None:
        scale = max(np.abs(first).max(initial=0.), np.abs(second).max(initial=0.))
    # The roundoff floor follows the compared quantities, so a supplied unit cannot hide a fault.
    _require(np.allclose(first, second, rtol=1e-8, atol=1e-12 * float(scale)), message)


def _covariance(value, n=None):
    matrix = _array(value, ndim=2)
    _require(matrix.shape[0] == matrix.shape[1] and matrix.shape[0] <= MAX_BINS,
             'bounded square covariance required')
    if n is not None:
        _require(matrix.shape == (n, n), 'covariance bin population differs')
    _close(matrix, matrix.T, 'covariance is asymmetric')
    spectrum = np.linalg.eigvalsh(matrix)
    _require(spectrum.min() >= -1e-10 * max(float(np.max(np.abs(spectrum))), 1e-20),
             'covariance is not positive semidefinite')
    return matrix


def _values(bundle):
    values = _array(bundle['values'])
    _require(len(values) <= MAX_BINS and len(_labels(bundle['bins'])) == len(values),
             'values and unique bin labels differ')
    return values


def _frame(frame):
    _require(frame['level'] in {'born', 'bare', 'dressed', 'parton', 'particle', 'reconstructed'},
             'unknown particle level')
    for key in ('prompt', 'tau_feeddown', 'fiducial'):
        _text(frame[key])
    if frame['level'] == 'dressed':
        _require(_number(frame['photon_radius']) > 0, 'positive supplied dressing radius required')
    return frame


@_check
def frame_declared(bundle, record):
    """Reject missing or mismatched particle level and fiducial definitions."""
    first, second = _frame(bundle['frame']), _frame(record['prediction_frame'])
    for key in ('level', 'prompt', 'tau_feeddown', 'fiducial'):
        _require(first[key] == second[key], 'frame mismatch: ' + key)
    if first['level'] == 'dressed':
        _close(first['photon_radius'], second['photon_radius'], 'dressing radius mismatch')


@_check
def covariance_assembled(bundle, record):
    """Reassemble every supplied marginal-error and correlation contribution."""
    n = len(_values(bundle))
    assembled = np.zeros((n, n))
    components = bundle['uncertainties']
    _require(isinstance(components, list) and bool(components), 'uncertainty components required')
    for component in components:
        if 'errors' in component:
            errors = _array(component['errors'])
        else:
            down, up = _array(component['down']), _array(component['up'])
            _require(down.shape == up.shape and (down >= 0).all() and (up >= 0).all(),
                     'nonnegative asymmetric error siblings required')
            rule = component['symmetrization']
            _require(rule in {'average', 'max', 'shift'}, 'asymmetric error rule required')
            errors = (down + up) / 2 if rule != 'max' else np.maximum(down, up)
            if rule == 'shift':
                _close(component['central_shift'], (up - down) / 2, 'central shift not retained')
        _require(errors.shape == (n,) and (errors >= 0).all(), 'error vector differs from bins')
        correlation = _covariance(component['correlation'], n)
        _close(np.diag(correlation), np.ones(n), 'correlation diagonal must be one')
        _require((np.abs(correlation) <= 1 + 1e-10).all(), 'correlation outside unit range')
        assembled += errors[:, None] * correlation * errors[None, :]
    _close(_covariance(bundle['covariance'], n), assembled, 'correlation contributions were lost')


@_check
def normalized_rule(bundle, record):
    """Check normalization, its covariance null direction, rank and chosen inverse."""
    values = _values(bundle)
    definition = bundle['normalization']
    _require(definition['kind'] in {'absolute', 'normalized', 'ratio'}, 'normalization kind required')
    if definition['kind'] != 'normalized':
        return
    weights = _array(definition['weights'])
    _require(weights.shape == values.shape and (weights > 0).all(), 'positive bin weights required')
    _close(weights @ values, 1., 'distribution is not normalized with supplied bin weights')
    covariance = _covariance(bundle['covariance'], len(values))
    _close(covariance @ weights, np.zeros(len(values)), 'normalized covariance lacks its null direction',
           scale=len(values) * np.abs(covariance).max() * weights.max())
    rank = int(np.linalg.matrix_rank(covariance, hermitian=True))
    _require(rank == len(values) - 1, 'normalized covariance has additional missing directions')
    inverse = record['inverse']
    _require(type(inverse['rank']) is int and inverse['rank'] == rank, 'declared covariance rank differs')
    if inverse['method'] == 'pseudoinverse':
        expected = np.linalg.pinv(covariance, hermitian=True)
    elif inverse['method'] == 'drop-bin':
        _require(inverse['dropped_bin'] in bundle['bins'], 'dropped bin is absent')
        index = bundle['bins'].index(inverse['dropped_bin'])
        reduced = np.delete(np.delete(covariance, index, 0), index, 1)
        expected = np.linalg.inv(reduced)
    else:
        raise ValueError('normalized covariance needs pseudoinverse or declared drop-bin')
    _close(_array(inverse['matrix'], ndim=2), expected, 'reported inverse is not the chosen covariance inverse')


@_check
def theory_cov_included(bundle, record):
    """Verify the supplied theory components and experimental-plus-theory sum."""
    n = len(_values(bundle))
    components = record['theory_components']
    _require(isinstance(components, list) and bool(components), 'theory component census required')
    _labels([c['id'] for c in components])
    total = sum((_covariance(c['covariance'], n) for c in components), np.zeros((n, n)))
    _close(_covariance(bundle['theory_covariance'], n), total, 'theory component total differs')
    _close(_covariance(record['comparison_covariance'], n), _covariance(bundle['covariance'], n) + total,
           'comparison omits or double counts theory covariance')


@_check
def prediction_convention(bundle, record):
    """Require explicit shape/rate orders and any different-order rescaling."""
    prediction = record['prediction']
    _text(prediction['shape_order']); _text(prediction['rate_order'])
    _require(prediction['normalization'] == bundle['normalization']['kind'], 'prediction normalization differs')
    if prediction['shape_order'] != prediction['rate_order']:
        rescaling = prediction['rate_rescaling']
        _text(rescaling['source']); _text(rescaling['uncertainty_prescription'])
        source, target = _number(rescaling['source_rate']), _number(rescaling['target_rate'])
        _require(source > 0 and target > 0, 'positive rescaling rates required')
        _close(_number(rescaling['factor']), target / source, 'rate rescaling factor differs')


@_check
def alphas_consistent(bundle, record):
    """Check the matrix-element and PDF coupling at the declared common scale."""
    alpha = record['alphas']
    _require(alpha['unit'] == 'GeV' and _number(alpha['scale']) > 0, 'common coupling scale required')
    first, second = _number(alpha['matrix_element']), _number(alpha['pdf'])
    _require(first > 0 and second > 0, 'positive strong couplings required')
    _close(first, second, 'matrix-element and PDF alpha_s differ')


@_check
def prescription_declared(bundle, record):
    """Check scale-member census and declared envelope/covariance correlation."""
    scale = record['scale']
    members = _array(scale['members'], ndim=2)
    _require(members.shape[1] == 2 and (members > 0).all(), 'positive scale pairs required')
    observed = {tuple(row) for row in members}
    _require(len(observed) == len(members) and (1., 1.) in observed, 'unique members including nominal required')
    prescription = scale['prescription']
    if prescription in {'seven-point', 'nine-point'}:
        expected = {(r, f) for r in (.5, 1., 2.) for f in (.5, 1., 2.)}
        if prescription == 'seven-point': expected -= {(.5, 2.), (2., .5)}
        _require(observed == expected, 'scale member population differs from prescription')
    elif prescription == 'independent':
        declared = {tuple(row) for row in _array(scale['declared_members'], ndim=2)}
        _require(observed == declared, 'independent scale members differ from declaration')
    else:
        raise ValueError('scale prescription required')
    _require(scale['correlation'] in {'envelope', 'fully-correlated', 'uncorrelated', 'nuisance'},
             'scale correlation model undeclared')
    if scale['correlation'] != 'envelope':
        model = scale['covariance_model']
        _text(model['source']); _text(model['distribution'])
        _covariance(model['matrix'], len(_values(bundle)))


@_check
def np_once(bundle, record):
    """Require exactly one total nonperturbative correction and recompute output."""
    correction = record['nonperturbative']
    _require(type(correction['input_includes']) is bool, 'input correction status required')
    count = correction['applications']
    _require(type(count) is int and count >= 0 and count + int(correction['input_includes']) == 1,
             'nonperturbative correction missing or applied twice')
    inputs, factors = _array(correction['input_values']), _array(correction['factors'])
    _require(inputs.shape == factors.shape and (factors > 0).all(), 'correction factors differ from bins')
    _close(_array(correction['output_values']), inputs * factors ** count, 'correction output differs')


@_check
def unfolding_closure(bundle, record):
    """Compute response forward closure and independent stress residuals."""
    unfolding = record['unfolding']
    truth = _array(unfolding['truth']); response = _array(unfolding['response'], ndim=2)
    _require(response.shape[1] == len(truth) and (response >= 0).all(), 'response dimensions or probabilities invalid')
    _require((response.sum(axis=0) <= 1 + 1e-10).all(), 'response efficiency exceeds one')
    _close(_array(unfolding['reconstructed']), response @ truth, 'response fails forward closure')
    tolerance = _number(unfolding['closure_tolerance'])
    _require(tolerance >= 0, 'nonnegative supplied closure tolerance required')
    trials = [{'truth': truth.tolist(), 'unfolded': unfolding['unfolded']}, *unfolding['stress_tests']]
    _require(len(trials) > 1, 'stress tests are required in addition to closure')
    stressed = False
    for trial in trials:
        expected, unfolded = _array(trial['truth']), _array(trial['unfolded'])
        _require(expected.shape == truth.shape == unfolded.shape, 'closure bin dimensions differ')
        stressed |= not np.array_equal(expected, truth)
        _require((np.abs(unfolded - expected) <= tolerance).all(), 'closure or stress residual exceeds criterion')
    _require(stressed, 'stress population repeats the closure truth')


@_check
def unfolding_coverage(bundle, record):
    """Recompute interval coverage per truth coordinate from supplied trials."""
    coverage = record['unfolding']['coverage']
    truth = _array(coverage['truth']); trials = coverage['intervals']
    floor, minimum = _number(coverage['minimum']), coverage['minimum_trials']
    _require(0 < floor <= 1 and type(minimum) is int and minimum > 0, 'coverage criteria required')
    _require(isinstance(trials, list) and minimum <= len(trials) <= 4096, 'coverage trials missing or insufficient')
    contained = np.zeros(len(truth))
    for trial in trials:
        intervals = _array(trial, ndim=2)
        _require(intervals.shape == (len(truth), 2) and (intervals[:, 0] <= intervals[:, 1]).all(),
                 'ordered coverage intervals required')
        contained += (intervals[:, 0] <= truth) & (truth <= intervals[:, 1])
    _require((contained / len(trials) >= floor).all(), 'computed coverage below supplied criterion')


@_check
def regularization_declared(bundle, record):
    """Require regularization selection, prior variation and prospective choice."""
    regularization = record['unfolding']['regularization']
    for key in ('method', 'selection_rule', 'prior'): _text(regularization[key])
    _require(_number(regularization['strength']) >= 0, 'regularization strength required')
    variations = _labels(regularization['prior_variations'])
    _require(regularization['prior'] not in variations, 'prior variations must differ from nominal')
    _require(regularization['selected_before_data'] is True, 'regularization was not prospectively selected')


@_check
def tune_heldout(bundle, record):
    """Require disjoint validation observables, fit weights and held-out residuals."""
    tune = record['tune']
    fit, validation = _labels(tune['fit_observables']), _labels(tune['validation_observables'])
    _require(not fit & validation, 'validation observable was used in tuning')
    weights = tune['weights']
    _require(isinstance(weights, dict) and set(weights) == fit and
             all(_number(v) > 0 for v in weights.values()), 'declared positive weights for each fit observable required')
    residuals = _array(tune['heldout_residuals'])
    maximum = _number(tune['maximum_residual'])
    _require(len(residuals) == len(validation) and maximum >= 0 and
             (np.abs(residuals) <= maximum).all(), 'held-out residual criterion fails')


@_check
def pdf_not_circular(bundle, record):
    """Refuse PDF impact data present in the fitted-set data population."""
    pdf = record['pdf']
    fit, impact = _labels(pdf['fit_datasets']), _labels(pdf['impact_datasets'])
    _require(impact == _labels(bundle['datasets']), 'impact population differs from measurement data')
    _require(not fit & impact, 'PDF impact data were used in the PDF fit')


@_check
def tolerance_declared(bundle, record):
    """Require a supplied PDF tolerance definition and effective replica accounting."""
    tolerance = record['pdf']['tolerance']
    _require(_number(tolerance['value']) > 0, 'positive tolerance required')
    _text(tolerance['criterion']); _text(tolerance['source'])
    if 'replica_weights' in record['pdf']:
        weights = _array(record['pdf']['replica_weights'])
        _require((weights >= 0).all() and weights.sum() > 0, 'nonnegative nonzero replica weights required')
        normalized = weights / weights.sum()
        positive = normalized[normalized > 0]
        effective = math.exp(float(-(positive * np.log(positive)).sum()))
        _close(_number(record['pdf']['effective_replicas']), effective, 'effective replica count differs')


@_check
def ew_scheme(bundle, record):
    """Match input, width, mixing-angle and mass schemes; locate oblique origin."""
    ew = record['ew']
    choices = {'scheme': {'g-mu', 'alpha-zero', 'alpha-z'}, 'width': {'pole', 'fixed', 'running'},
               'angle': {'effective-leptonic', 'msbar', 'on-shell'}, 'top_mass': {'pole', 'msbar'}}
    for key, allowed in choices.items():
        data, prediction = ew['data_' + key], ew['prediction_' + key]
        _require(data in allowed and prediction in allowed, 'undeclared EW convention: ' + key)
        if data != prediction:
            conversion = ew['conversions'][key]
            _text(conversion['source']); _text(conversion['equation'])
            _require(conversion['from'] == prediction and conversion['to'] == data,
                     'EW conversion direction differs')
    _require(_number(ew['top_mass_value']) > 0, 'prediction top mass required')
    _require(type(ew['oblique']) is bool, 'oblique scope required')
    if ew['oblique']:
        point = ew['reference_point']
        _require(_number(point['scalar_mass']) > 0 and _number(point['top_mass']) > 0,
                 'positive oblique reference masses required')
        _text(point['scheme'])


@_check
def parametrization_range(bundle, record):
    """Check every supplied parameter against its declared validity interval."""
    parameters = record['parameters']; point, ranges = parameters['point'], parameters['ranges']
    _require(isinstance(point, dict) and bool(point) and set(point) == set(ranges),
             'point and validity parameter populations differ')
    for name, value in point.items():
        bounds = _array(ranges[name])
        _require(len(bounds) == 2 and bounds[0] <= bounds[1], 'ordered parameter range required')
        _require(bounds[0] <= _number(value) <= bounds[1], 'parameter outside validity range: ' + name)


@_check
def measurement_overlap(bundle, record):
    """Require cross-covariance for every shared dataset or systematic source."""
    combination = record['combination']; measurements = combination['measurements']
    _require(isinstance(measurements, list) and len(measurements) >= 2, 'measurement combination population required')
    ids = _labels([m['id'] for m in measurements])
    sizes = [len(_labels(m['bins'])) if 'bins' in m else 1 for m in measurements]
    boundaries = np.cumsum([0, *sizes])
    covariance = _covariance(combination['covariance'], sum(sizes))
    overlaps = {}
    for row in combination['overlap']:
        pair = frozenset(_labels(row['pair']))
        _require(len(pair) == 2 and pair <= ids and pair not in overlaps, 'unique known measurement pair required')
        overlaps[pair] = row
    for i, first in enumerate(measurements):
        datasets = _labels(first['datasets'])
        systematics = _labels(first['systematics'], allow_empty=True)
        for j in range(i + 1, len(measurements)):
            second = measurements[j]
            shared_data = datasets & _labels(second['datasets'])
            shared_systematics = systematics & _labels(second['systematics'], allow_empty=True)
            luminosity = set()
            for measurement in (first, second):
                if 'luminosity_source' in measurement:
                    _text(measurement['luminosity_source'])
            if first.get('luminosity_source') is not None and first.get('luminosity_source') == second.get('luminosity_source'):
                luminosity.add(first['luminosity_source'])
            pair = frozenset((first['id'], second['id']))
            if shared_data or shared_systematics or luminosity:
                _require(pair in overlaps, 'shared measurement inputs treated as independent')
            if pair in overlaps:
                row = overlaps[pair]
                _require(_labels(row['datasets'], allow_empty=True) == shared_data and
                         _labels(row['systematics'], allow_empty=True) == shared_systematics and
                         _labels(row.get('luminosity_sources', []), allow_empty=True) == luminosity,
                         'overlap source census differs')
                cross = _array(row['cross_covariance'], ndim=2)
                block = covariance[boundaries[i]:boundaries[i + 1], boundaries[j]:boundaries[j + 1]]
                if row['pair'] != [first['id'], second['id']]:
                    # Supplied cross blocks are oriented in the declared pair order.
                    cross = cross.T
                _require(cross.shape == (sizes[i], sizes[j]), 'measurement block cross-covariance required')
                _close(block, cross, 'combination discarded cross-covariance')
                if not np.any(cross) and (shared_data or shared_systematics or luminosity):
                    _text(row['zero_justification'])


@_check
def validity_range(bundle, record):
    """Refuse a prediction outside the supplied observable validity domain."""
    validity = record['validity']; coordinates = _array(validity['coordinates'])
    lower, upper = _number(validity['minimum']), _number(validity['maximum'])
    _text(validity['method']); _text(validity['source'])
    _require(lower <= upper and ((coordinates >= lower) & (coordinates <= upper)).all(),
             'prediction outside declared validity range')


@_check
def reference_version(bundle, record):
    """Require identical supplied measurement and routine-reference revisions."""
    _require(_text(bundle['source_version']) == _text(record['reference_version']),
             'routine reference and measurement source revisions differ')


@_check
def pdf_error_type(bundle, record):
    """Recompute supplied replica or Hessian errors with explicit CL rescaling."""
    pdf = record['pdf']; members = _array(pdf['members'], ndim=2)
    error_type = pdf['error_type']
    if error_type == 'replicas':
        includes_nominal = pdf.get('nominal_member_included', False)
        _require(type(includes_nominal) is bool, 'replica nominal-member layout must be boolean')
        if includes_nominal:
            members = members[1:]
        _require(len(members) >= 2, 'multiple replica members required')
        error = members.std(axis=0, ddof=1)
    elif error_type == 'symmhessian':
        _require(len(members) >= 2, 'nominal and symmetric eigenvectors required')
        error = np.sqrt(((members[1:] - members[0]) ** 2).sum(axis=0))
    elif error_type == 'hessian':
        _require(len(members) >= 3 and len(members) % 2 == 1, 'nominal and paired eigenvectors required')
        error = .5 * np.sqrt(((members[1::2] - members[2::2]) ** 2).sum(axis=0))
    else:
        raise ValueError('unknown PDF ErrorType')
    confidence, target = _number(pdf['confidence_level']), _number(pdf['target_confidence_level'])
    _require(0 < confidence < 100 and 0 < target < 100, 'confidence levels must be percentages')
    factor = NormalDist().inv_cdf(.5 + target / 200) / NormalDist().inv_cdf(.5 + confidence / 200)
    if confidence != target:
        _require(pdf['confidence_rescaling'] == 'gaussian', 'CL conversion distribution must be declared')
    _close(_number(pdf['cl_factor']), factor, 'PDF confidence rescaling differs')
    _close(_array(pdf['uncertainty']), error * factor, 'uncertainty uses wrong member formula')


@_check
def ew_combination(bundle, record):
    """Compare additive and multiplicative predictions and retain their difference."""
    ew = record['ew_combination']
    qcd, delta, born = _array(ew['qcd']), _array(ew['ew_delta']), _array(ew['born'])
    _require(qcd.shape == delta.shape == born.shape and (born != 0).all(), 'consistent nonzero Born reference required')
    additive, multiplicative = qcd + delta, qcd * (1 + delta / born)
    _require(ew['scheme'] in {'additive', 'multiplicative'}, 'QCD/EW combination scheme required')
    expected, alternative = (additive, multiplicative) if ew['scheme'] == 'additive' else (multiplicative, additive)
    _close(_array(ew['output']), expected, 'chosen QCD/EW output differs')
    _close(_array(ew['alternative']), alternative, 'alternative QCD/EW comparison missing or differs')
    _close(_array(ew['uncertainty']), np.abs(additive - multiplicative), 'combination difference uncertainty omitted')
    _require(type(ew['real_radiation_dominated']) is bool, 'radiation regime must be declared')
    _require(ew['photon_induced'] in {'included', 'excluded-with-source'}, 'photon-induced contribution scope required')
    if ew['photon_induced'] == 'excluded-with-source': _text(ew['photon_source'])


@_check
def amplitude_complete(bundle, record):
    """Compare required contributions with included terms and justified omissions."""
    amplitudes = record['amplitudes']
    required, included = _labels(amplitudes['required']), _labels(amplitudes['included'])
    omissions = amplitudes['omissions']; omitted = set()
    for omission in omissions:
        identity = _text(omission['id']); _text(omission['source']); _text(omission['scope'])
        _require(identity in required and identity not in included | omitted, 'invalid amplitude omission')
        bound, threshold = _number(omission['bound']), _number(omission['maximum'])
        _require(0 <= bound <= threshold, 'omitted amplitude bound exceeds criterion')
        omitted.add(identity)
    _require(required <= included | omitted, 'required amplitude or interference term is missing')


def run(check_id, bundle, record):
    """Execute a registered pure check over supplied records, preserving failures."""
    identity = check_id.removeprefix('check:')
    _require(identity in CHECKS, 'unknown SM check: ' + check_id)
    errors = globals()[identity.removeprefix('sm.')](bundle, record)
    # Use the existing result schema; this helper creates no receipt or gate authority.
    from ravel.workflow.review_projection_checks import result
    return result(check_id, [], status='failed' if errors else 'passed', diagnostics={'errors': errors})


def review_card_errors(card):
    """Specialist cards require blindness, a fresh session and a distinct producer."""
    if card.get('family') != 'specialist-review':
        return []
    errors = []
    independence = card.get('independence', {})
    if independence.get('fresh_session') is not True:
        errors.append('specialist review requires a fresh session')
    if 'producer' not in independence.get('distinct_actor_from', []):
        errors.append('specialist review requires a distinct producer actor')
    for field in (card.get('knowledge', {}).get('forbidden', []),
                  card.get('sees', {}).get('forbidden_inputs', [])):
        if not {'producer_headline', 'lessons'} <= set(field):
            errors.append('specialist review must forbid producer_headline and lessons')
    return errors


def registered_review_card_errors(card):
    """Apply this fragment's specialist contract without changing legacy cards."""
    if card['id'] not in _registration('roles')['roles']:
        return []
    return review_card_errors(card)


def _registration(name):
    return json.loads(package_data_path('sm', 'registration', name + '.json').read_text())


def derive_review_points(plan):
    """Derive SM staffing rows without launching work; compose at the spawn seam."""
    if plan.get('agent_layer_epoch') != 2:
        return []
    from ravel.workflow.spawn_rows import review_metadata
    nodes = plan.get('plan', plan).get('nodes', [])
    _labels([node['id'] for node in nodes]) if nodes else None
    rows = _registration('spawn-rows')['rows']
    points = []
    for node in nodes:
        stage = review_metadata(node).get('stage', node.get('stage'))
        for row in rows:
            if stage not in row['stages'] and node.get('operation') not in row['operations']:
                continue
            scope = node['id']
            points.append({'id': row['row'] + ':' + scope, 'row': row['row'], 'node_id': scope,
                           'when': {'trigger': row['trigger'], 'at': 'node:' + scope},
                           'roles': deepcopy(row['roles']), 'mode': row['mode'], 'blocking': True,
                           'gate': row['gate'], 'parallel_group': 'spawn:' + scope, 'depends_on': [],
                           'attestation_min': 'transport'})
    return sorted(points, key=lambda point: (point['row'], point['id']))


def staffing_errors(plan, points):
    """Reject omitted per-node specialists in a proposed review-point derivation."""
    errors = []
    for required in derive_review_points(plan):
        matching = [p for p in points if p.get('id') == required['id'] and
                    p.get('node_id') == required['node_id'] and p.get('gate') == required['gate'] and
                    p.get('blocking') is True and p.get('mode') == required['mode']]
        if len(matching) != 1 or matching[0].get('roles') != required['roles']:
            errors.append('missing or altered specialist review: ' + required['id'])
    return errors
