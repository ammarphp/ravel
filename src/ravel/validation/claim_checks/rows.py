"""Pure claim checks of raw observations against explicitly declared scientific bounds.

These functions neither choose a physics tolerance nor execute scientific tools.
Missing observations, nonfinite numbers and boolean numeric aliases cannot pass.
"""
from __future__ import annotations

import math
import re


def number(value, *, positive=False, nonnegative=False):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, ValueError):
        valid = False
    if not valid or (positive and value <= 0) or (nonnegative and value < 0):
        raise ValueError('a finite number within the declared domain is required')
    return value


def sequence(value):
    if not isinstance(value, list) or not value:
        raise ValueError('a nonempty observation population is required')
    return value


def pin(value):
    if not isinstance(value, dict) or not isinstance(value.get('path'), str) or not value['path']:
        raise ValueError('a located evidence pin is required')
    if not isinstance(value.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', value['sha256']):
        raise ValueError('evidence pins need a sha256 digest')
    return value


def result(ok, detail, **extra):
    return {'status': 'pass' if ok else 'fail', 'detail': detail, **extra}


def generation_cut_consistency(doc):
    gen, analysis = sequence(doc['generator_cuts']), sequence(doc['analysis_cuts'])
    keys = lambda c: (c['object'], c['variable'])
    targets = {keys(c): c for c in analysis}
    if len(targets) != len(analysis) or len({keys(c) for c in gen}) != len(gen):
        raise ValueError('duplicate cut coordinates')
    failures = []
    for cut in gen:
        key = keys(cut)
        target = targets.get(key)
        if target is None or not cut.get('unit') or cut['unit'] != target.get('unit'):
            failures.append(list(key))
            continue
        if cut.get('lower') is None and cut.get('upper') is None:
            raise ValueError('effective generator cuts need a bound')
        for side in ('lower', 'upper'):
            bound = cut.get(side)
            if bound is None:
                continue
            number(bound)
            other = target.get(side)
            if other is None or (number(other) < bound if side == 'lower' else number(other) > bound):
                failures.append(list(key))
    return result(not failures, 'effective generation cuts must contain the analysis phase space', failing_cuts=failures)


def downstream_settings_after_transforms(doc):
    required, actual = doc['required_downstream'], doc['effective_downstream']
    if not isinstance(required, dict) or not required or not isinstance(actual, dict):
        raise ValueError('required and effective downstream settings are required')
    failures = []
    for key, value in required.items():
        if key not in actual:
            failures.append(key)
        elif isinstance(value, list):
            if not value or not isinstance(actual[key], list) or not all(any(type(v) is type(a) and v == a for a in actual[key]) for v in value):
                failures.append(key)
        elif type(value) is not type(actual[key]) or value != actual[key]:
            failures.append(key)
    return result(not failures, 'every transform requirement must reach the consuming settings', missing_settings=failures)


def interference_size(doc):
    powers = sequence(doc['declared_powers'])
    for power in powers:
        number(power, nonnegative=True)
    terms = sequence(doc['terms'])
    pin(doc['sigma_probe'])
    if doc['sm_amplitude_on'] is not True:
        return result(False, 'the sigma probe must include the shared SM amplitude')
    total, lower = 0., 0.
    for term in terms:
        power, value = number(term['power'], nonnegative=True), number(term['value'])
        total += value
        if power < min(powers):
            lower += abs(value)
    fraction = lower / abs(number(total, positive=True))
    bound = number(doc['max_lower_order_fraction'], nonnegative=True)
    return result(fraction <= bound, 'the fitted lower-order fraction must satisfy the declared scaling bound', lower_order_fraction=fraction)


def measurement_applicability(doc):
    shape, envelope = sequence(doc['signal_shape']), sequence(doc['validity_envelope'])
    if len(shape) != len(envelope):
        raise ValueError('measurement applicability needs the whole shape population')
    failures = []
    for i, (value, bounds) in enumerate(zip(shape, envelope)):
        if len(bounds) != 2 or number(bounds[0]) > number(bounds[1]):
            raise ValueError('validity envelopes have ordered bounds')
        if not bounds[0] <= number(value) <= bounds[1]:
            failures.append(i)
    return result(not failures, 'an unfolded measurement requires the signal shape inside its validity envelope', failing_bins=failures, checkin3_flag=bool(failures))


def agreement_correlation_range(doc):
    bounds, verdicts = doc['correlation_range'], sequence(doc['verdicts'])
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError('an unpublished correlation needs a declared range')
    lo, hi = [number(v) for v in bounds]
    if not -1 <= lo < hi <= 1:
        raise ValueError('correlation bounds must span a nonzero range within [-1,1]')
    positions = [number(v['correlation']) for v in verdicts]
    if len(positions) != len(set(positions)) or min(positions) != lo or max(positions) != hi:
        return result(False, 'report the agreement verdict over both ends of the declared correlation range')
    computed = [{'correlation': v['correlation'], 'agrees': abs(number(v['residual'])) <= number(v['tolerance'], nonnegative=True)} for v in verdicts]
    return result(all(v['agrees'] for v in computed), 'agreement is required over the declared correlation range', verdicts=computed)


def per_bin_mc_precision(doc):
    target = number(doc['relative_target'], positive=True)
    bins = sequence(doc['bins'])
    references = doc['reference_yields']
    if not isinstance(references, dict) or not references:
        raise ValueError('per-bin precision needs the complete reference population')
    if len({b['id'] for b in bins}) != len(bins) or {b['id'] for b in bins} != set(references):
        raise ValueError('per-bin MC precision must retain every reference bin exactly once')
    failures, precision = [], []
    for b in bins:
        sumw, sumw2 = number(b['sumw']), number(b['sumw2'], nonnegative=True)
        reference = number(references[b['id']], positive=True)
        relative = math.sqrt(sumw2) / reference
        # A signed-weight cancellation does not erase the measured MC variance.
        # Zero empirical variance needs a separate adequacy witness.
        ok = sumw2 > 0 and relative <= target
        if not ok:
            failures.append(b['id'])
        precision.append({'id': b['id'], 'relative_precision': relative})
    return result(not failures, 'MC uncertainty is measured against each reference-scale bin yield', failing_bins=failures, bins=precision)


def eft_validity(doc):
    cutoff, bins = number(doc['cutoff'], positive=True), sequence(doc['bins'])
    if len({b['id'] for b in bins}) != len(bins):
        raise ValueError('EFT validity needs unique bin ids')
    failures = [b['id'] for b in bins if number(b['energy_reach'], nonnegative=True) >= cutoff]
    truncation, outputs = doc.get('truncation'), doc['results']
    needed = ('linear', 'quadratic') if truncation is None else (truncation,)
    if any(key not in ('linear', 'quadratic') for key in needed):
        raise ValueError('declare linear or quadratic truncation')
    for key in needed:
        values = sequence(outputs.get(key))
        if len(values) != len(bins):
            raise ValueError('each truncation result must cover every bin')
        for v in values:
            number(v)
    return result(not failures, 'every EFT bin must lie below the cutoff; undeclared truncation requires both results', failing_bins=failures, truncations=list(needed))


def learned_selection_sculpting(doc):
    before, after = sequence(doc['before']), sequence(doc['after'])
    pin(doc['independent_sample'])
    if len(before) != len(after):
        raise ValueError('sculpting needs the same whole bin population before and after selection')
    before = [number(v, nonnegative=True) for v in before]
    after = [number(v, nonnegative=True) for v in after]
    if any(a > b for a, b in zip(after, before)):
        raise ValueError('selected counts cannot exceed preselection counts')
    a, b = number(sum(before), positive=True), number(sum(after), positive=True)
    distance = .5 * sum(abs(x / a - y / b) for x, y in zip(before, after))
    tolerance = number(doc['max_shape_distance'], nonnegative=True)
    return result(distance <= tolerance, 'learned selection sculpting is checked on an independent sample', shape_distance=distance)


def agreement_target_declared(doc):
    target = doc['target']
    if not isinstance(target, dict):
        raise ValueError('an agreement requires a target record')
    if isinstance(target.get('reference'), dict):
        # A CHECK-IN 1 agreement-target record: the provider checks it against its plan claim.
        from ravel.validation.agreement_target import validate
        errors = validate(target, doc.get('claim'), doc.get('claims', ()))
        if errors:
            return result(False, 'agreement target: ' + '; '.join(errors))
        return result(True, 'the agreement-target record validates against its plan claim')
    for key in ('reference_kind', 'quantity', 'family'):
        if not isinstance(target.get(key), str) or not target[key].strip():
            raise ValueError('agreement target needs reference kind, quantity and family')
    for p in sequence(target['pins']):
        pin(p)
    sequence(target['nodes'])
    pin(target['noise_model_reference'])
    if not isinstance(target.get('tolerance_rule'), dict) or not target['tolerance_rule']:
        raise ValueError('agreement target needs a declared tolerance rule')
    if target['reference_kind'] == 'published_reproduction':
        for p in sequence(target['recipe_pins']):
            pin(p)
    return result(True, 'reference pins, quantity, family, nodes, tolerance and noise model are declared')


def comparison_family_match(doc):
    prediction, reference = doc['prediction'], doc['reference']
    for record in (prediction, reference):
        if not all(isinstance(record.get(k), str) and record[k].strip() for k in ('family', 'quantity')):
            raise ValueError('comparison endpoints need quantity and family')
    if prediction['family'] != reference['family']:
        return result(False, 'comparison families must match')
    if prediction['quantity'] != reference['quantity']:
        conversion = doc.get('conversion')
        if not isinstance(conversion, dict):
            return result(False, 'different quantities need an explicitly bound conversion')
        pin(conversion.get('pin'))
        if conversion.get('from') != prediction['quantity'] or conversion.get('to') != reference['quantity']:
            return result(False, 'the conversion must bind these exact comparison quantities')
    return result(True, 'comparison family and quantity or declared conversion match')


def attribution_above_noise(doc):
    residual = abs(number(doc['residual']))
    sigma, minimum = number(doc['noise_sigma'], positive=True), number(doc['minimum_sigma'], positive=True)
    significance = residual / sigma
    return result(significance >= minimum, 'an attribution must exceed the declared noise threshold', residual_sigma=significance)


def signal_model_complete_before_calibration(doc):
    required, components = sequence(doc['required_components']), sequence(doc['components'])
    if len(required) != len(set(required)) or len(components) != len(set(components)):
        raise ValueError('signal-model component ids must be unique')
    completed = number(doc['completeness_sequence'], nonnegative=True)
    calibrated = number(doc['calibration_sequence'], nonnegative=True)
    missing = sorted(set(required) - set(components))
    return result(not missing and completed < calibrated, 'all signal-model components must be complete before calibration', missing_components=missing)


EVALUATORS = {name: globals()[name] for name in (
    'generation_cut_consistency', 'downstream_settings_after_transforms', 'interference_size',
    'measurement_applicability', 'agreement_correlation_range', 'per_bin_mc_precision', 'eft_validity',
    'learned_selection_sculpting', 'agreement_target_declared', 'comparison_family_match',
    'attribution_above_noise', 'signal_model_complete_before_calibration')}
