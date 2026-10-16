"""Shared binned yield interchange; carries moments and normalization provenance.

Independent-bin sumw2 and full covariance remain distinct. Converting a
weighted quantity retains its covariance and combined, inseparable flow.
"""
from copy import deepcopy
import math

KEYS = {'schema_version', 'kind', 'axes', 'unit', 'representation', 'bins', 'overflow', 'underflow',
        'overflow_in_last_bin', 'underflow_in_first_bin', 'description', 'sumw2', 'normalization', 'provenance', 'covariance', 'quantity'}


def number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' must be finite')
    return float(value)


def validate(doc):
    if type(doc) is not dict or set(doc) - KEYS or not {'schema_version', 'kind', 'axes', 'unit', 'representation', 'bins'} <= set(doc):
        raise ValueError('binned_values result needs axes, unit, representation and bins with only shared schema keys')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1 or doc['kind'] != 'binned_values' or doc['representation'] not in ('integrated', 'differential'):
        raise ValueError('binned_values version 1 with integrated or differential representation required')
    if 'quantity' in doc:
        from ravel.validation.semantic_composition import compare, message
        expected = {'unit': doc['unit'], 'normalization': {'per_bin_width': doc['representation'] == 'differential'}}
        ids = doc.get('provenance', {}).get('bin_ids') if isinstance(doc.get('provenance'), dict) else None
        if ids is not None:
            expected['bin_ids'] = ids
        errors = compare(doc['quantity'], expected, 'binned_values')['errors']
        if errors:
            raise ValueError('; '.join(map(message, errors)))
    axes = doc['axes']
    if type(axes) is not list or not axes or any(type(a) is not dict or set(a) != {'name', 'unit'} or
            type(a['name']) is not str or not a['name'].strip() or type(a['unit']) is not str for a in axes):
        raise ValueError('binned axes need unique names and literal units')
    if len({a['name'] for a in axes}) != len(axes) or type(doc['unit']) is not str or not doc['unit'].strip():
        raise ValueError('unique axes and a value unit required')
    if type(doc['bins']) is not list or not doc['bins']:
        raise ValueError('nonempty binned values required')
    for b in doc['bins']:
        if type(b) is not dict or not {'low', 'high', 'value'} <= set(b) <= {'low', 'high', 'value', 'uncertainty', 'sumw2'}:
            raise ValueError('result bins need low/high/value and optional uncertainty/sumw2')
        if any(type(b[k]) is not list or len(b[k]) != len(axes) for k in ('low', 'high')):
            raise ValueError('bin dimensions differ from axes')
        for low, high in zip(b['low'], b['high']):
            if number(high, 'edge') <= number(low, 'edge'):
                raise ValueError('bin edges must strictly increase')
        number(b['value'], 'value')
        for key in ('uncertainty', 'sumw2'):
            if key in b and number(b[key], key) < 0:
                raise ValueError(key + ' must be nonnegative')
        if 'uncertainty' in b and 'sumw2' in b and not math.isclose(b['uncertainty']**2, b['sumw2'], rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError('uncertainty differs from sumw2')
    if 'sumw2' in doc:
        values = doc['sumw2']
        if type(values) is not list or len(values) != len(doc['bins']):
            raise ValueError('sumw2 must have one entry per bin')
        for b, variance in zip(doc['bins'], values):
            if number(variance, 'sumw2') < 0 or ('sumw2' in b and variance != b['sumw2']):
                raise ValueError('sumw2 is negative or differs from bin moment')
    if 'normalization' in doc:
        n = doc['normalization']
        if type(n) is not dict or n.get('kind') not in ('unnormalized', 'absolute', 'normalized', 'shape'):
            raise ValueError('normalization needs an explicit kind')
        if 'scale' in n:
            number(n['scale'], 'normalization scale')
    if 'provenance' in doc and type(doc['provenance']) is not dict:
        raise ValueError('provenance must be an object')
    if 'covariance' in doc:
        matrix = doc['covariance']; n = len(doc['bins'])
        if type(matrix) is not list or len(matrix) != n or any(type(r) is not list or len(r) != n for r in matrix):
            raise ValueError('covariance dimensions differ from bins')
        for i, row in enumerate(matrix):
            for j, value in enumerate(row):
                number(value, 'covariance')
                if value != matrix[j][i] or (i == j and value < 0):
                    raise ValueError('symmetric covariance with nonnegative diagonal required')
            if 'sumw2' in doc and not math.isclose(row[i], doc['sumw2'][i], rel_tol=1e-12, abs_tol=1e-15):
                raise ValueError('covariance diagonal differs from sumw2')
    return doc


def build(*, axes, bins, unit, representation='integrated', normalization, provenance, **flows):
    doc = {'schema_version': 1, 'kind': 'binned_values', 'axes': deepcopy(axes), 'bins': deepcopy(bins),
           'unit': unit, 'representation': representation, 'normalization': deepcopy(normalization),
           'provenance': deepcopy(provenance), **flows}
    if all('sumw2' in b for b in bins):
        doc['sumw2'] = [b['sumw2'] for b in bins]
    return validate(doc)


def from_quantity(quantity, weight, *, descriptor=None):
    """Project one named stream without discarding its bin covariance or flows."""
    if quantity.get('finalization_pending') is not False:
        raise ValueError('finalized weighted quantity required')
    # Weighted moments retain the signed event stream; normalization never
    # replaces weights by their magnitudes, even when all inputs are positive.
    from ravel.validation.semantic_composition import compare, message
    supplied = deepcopy(descriptor) if descriptor is not None else {}
    errors = compare(supplied, {'weight_convention': 'signed'}, 'from_quantity')['errors']
    if errors:
        raise ValueError('; '.join(map(message, errors)))
    supplied['weight_convention'] = 'signed'
    contract = quantity['contract']; names = contract['weight_names']
    k = names.index(weight); n = len(contract['bins'])
    covariance = [r[k*n:(k+1)*n] for r in quantity['covariance'][k*n:(k+1)*n]]
    values = quantity['values'][weight]
    normalization = {**deepcopy(contract['normalization']), 'kind': 'normalized',
                     'original_kind': contract['normalization']['kind']}
    return build(axes=contract['axes'],
                 bins=[{'low': b['low'], 'high': b['high'], 'value': v, 'sumw2': covariance[i][i]}
                       for i, (b, v) in enumerate(zip(contract['bins'], values))], unit=quantity['unit'],
                 representation=contract['representation'], normalization=normalization,
                 provenance={'weight': weight, 'bin_ids': [b['id'] for b in contract['bins']],
                             'contract_sha256': quantity['contract_sha256'], 'state_sha256': quantity['state_sha256'],
                             'combined_flow': quantity['flow'][weight], 'flow_separable': False}, covariance=covariance,
                 quantity=supplied)
