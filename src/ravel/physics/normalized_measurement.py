"""Explicit Gaussian contrasts of nonlinear normalized SM+BSM mixtures.

This operation preserves a supplied covariance, including an inconsistent
normalization direction, and evaluates only declared unit-area contrasts. It
does not repair that covariance or certify the source as an exact normalized
measurement likelihood. Predictions are (SM + mu*BSM)/(S + mu*B), not an
additive normalized signal. Positive component densities are required; signed
interference, prediction uncertainties and CLs need distinct contracts.
"""
from __future__ import annotations

import math
import hashlib
import re
from pathlib import Path

from ravel.physics.measurement import _load, _matrix, _vector
from ravel.physics.quantities import _keys, _number, _text, validate_binning
from ravel.workflow.state_io import atomic_json


def validate(spec):
    _keys(spec, ('schema_version', 'input', 'signal_strength', 'signal_strength_max'), label='normalized contrast task')
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('unsupported normalized contrast task schema')
    _text(spec['input'], 'normalized contrast input')
    mu, cap = (_number(spec[k], k) for k in ('signal_strength', 'signal_strength_max'))
    if not 0 <= mu <= cap or cap <= 0:
        raise ValueError('signal strength must lie in its declared finite nonnegative domain')
    return dict(spec)


def inputs(spec, base):
    from ravel.workflow.science import regular
    path = regular(validate(spec)['input'], base)
    document, _ = _load(path)
    files = [path]
    for pin in _grounding(document):
        source = regular(pin['path'], path.parent)
        if hashlib.sha256(source.read_bytes()).hexdigest() != pin['sha256']:
            raise ValueError('normalized contrast grounding bytes differ from their declared identity')
        files.append(source)
    if len(set(files)) != len(files):
        raise ValueError('normalized contrast grounding repeats an input path')
    return files


def _grounding(document):
    pins = document.get('grounding', [])
    if not isinstance(pins, list):
        raise ValueError('normalized contrast grounding must be an explicit list')
    for pin in pins:
        _keys(pin, ('path', 'sha256'), label='normalized contrast grounding identity')
        _text(pin['path'], 'grounding path')
        if not isinstance(pin['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', pin['sha256']):
            raise ValueError('normalized contrast grounding requires a SHA256 identity')
    return pins


def prepare(document):
    import numpy as np

    _keys(document, ('schema_version', 'analysis_id', 'quantity', 'data', 'sm_absolute',
                     'bsm_absolute', 'experimental_covariance', 'contrast_policy', 'sources'), ('grounding',),
          label='normalized contrast input')
    _grounding(document)
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise ValueError('unsupported normalized contrast input schema')
    _text(document['analysis_id'], 'analysis_id')
    quantity = document['quantity']
    _keys(quantity, ('axes', 'bins', 'representation', 'normalization', 'unit'), label='normalized contrast quantity')
    volumes = validate_binning(quantity['axes'], quantity['bins'])
    if quantity['normalization'] != 'normalized' or quantity['representation'] not in ('integrated', 'differential'):
        raise ValueError('normalized contrasts require explicit normalized bin representation')
    dimensions = [a['unit'] for a in quantity['axes'] if a['unit'] != '1']
    unit = '1/(' + '*'.join(dimensions) + ')' if dimensions and quantity['representation'] == 'differential' else '1'
    if quantity['unit'] != unit:
        raise ValueError('normalized contrast unit differs from its geometry')
    ids = [b['id'] for b in quantity['bins']]
    if len(ids) < 2:
        raise ValueError('normalized contrast requires at least two bins')
    if document['contrast_policy'] != {'kind': 'unit_area_orthogonal_contrasts',
                                       'theory_policy': 'fixed_central_without_uncertainty'}:
        raise ValueError('explicit unit-area contrast and fixed-central-theory approximation required')
    sources = document['sources']
    _keys(sources, ('measurement', 'covariance', 'sm', 'bsm', 'approximation'), label='normalized contrast sources')
    for k, value in sources.items():
        _text(value, k + ' source')
    data = _vector(document['data'], ids, unit, 'data', np)
    absolute_unit = _text(document['sm_absolute']['unit'], 'absolute prediction unit')
    sm = _vector(document['sm_absolute'], ids, absolute_unit, 'sm_absolute', np)
    bsm = _vector(document['bsm_absolute'], ids, absolute_unit, 'bsm_absolute', np)
    if np.any(sm < 0) or np.any(bsm < 0):
        raise ValueError('negative component predictions require a signed/interference contract; no clipping is permitted')
    covariance = _matrix(document['experimental_covariance'], ids, unit, 'experimental_covariance', np)
    # _matrix validates units, labels and PSD. Preserve exact input values:
    # even a tolerated asymmetry is not silently symmetrized on this route.
    record = document['experimental_covariance']
    order = [record['bin_ids'].index(i) for i in ids]
    covariance = np.array(record['matrix'], dtype=float)[np.ix_(order, order)]
    if not np.array_equal(covariance, covariance.T):
        raise ValueError('contrast covariance must be exactly symmetric; no source matrix repair')
    area = np.array(volumes if quantity['representation'] == 'differential' else [1.]*len(ids))
    s, b = float(area @ sm), float(area @ bsm)
    if not math.isfinite(s) or not math.isfinite(b) or s <= 0:
        raise ValueError('finite positive SM integral and finite BSM integral required')
    normal = area / np.linalg.norm(area)
    projection = np.linalg.svd(normal.reshape(1, -1), full_matrices=True)[2][1:]
    reduced = projection @ covariance @ projection.T
    eigen = np.linalg.eigvalsh(reduced)
    if eigen.min() <= max(eigen.max()*1e-12, 0):
        raise ValueError('contrast covariance is singular or ill-conditioned; no regularization')
    shape_sm, shape_bsm = sm/s, (bsm/b if b > 0 else sm/s)
    direction = shape_bsm - shape_sm
    return {'bin_ids': ids, 'area': area, 'data': data, 'sm_absolute': sm, 'bsm_absolute': bsm,
            'sm_integral': s, 'bsm_integral': b, 'shape_sm': shape_sm, 'shape_bsm': shape_bsm,
            'shape_direction': direction, 'covariance': covariance, 'projection': projection,
            'normal': normal, 'projected_covariance': reduced,
            'projected_residual': projection @ (data-shape_sm), 'projected_direction': projection @ direction,
            'covariance_condition_number': float(eigen.max()/eigen.min()), 'degrees_of_freedom': len(ids)-1}


def mixture(model, mu):
    """Evaluate the contracted nonlinear mixture and its exact fraction map."""
    mu = _number(mu, 'signal strength')
    if mu < 0:
        raise ValueError('negative signal strength is outside the positive-mixture contract')
    s, b = model['sm_integral'], model['bsm_integral']
    scaled_bsm = mu*b
    total = s + scaled_bsm
    if not math.isfinite(total) or total <= 0:
        raise ValueError('mixture normalization overflows or is nonpositive')
    fraction = scaled_bsm/total
    values = model['shape_sm'] + fraction*model['shape_direction']
    if not all(math.isfinite(float(x)) for x in values):
        raise ValueError('normalized mixture prediction is nonfinite')
    return values, fraction, total


def diagnose(document, spec):
    """Analytic bounded shape-fraction fit; fixed-model chi-square only."""
    import numpy as np
    from scipy.stats import chi2

    spec = validate(spec)
    model = prepare(document)
    prediction, fraction, total = mixture(model, spec['signal_strength'])
    _, cap_fraction, _ = mixture(model, spec['signal_strength_max'])
    if cap_fraction == 1:
        raise ValueError('declared signal-strength cap loses fraction-map precision')
    p, c = model['projection'], model['projected_covariance']
    cholesky = np.linalg.cholesky(c)
    residual = np.linalg.solve(cholesky, model['projected_residual'])
    direction = np.linalg.solve(cholesky, model['projected_direction'])
    info = float(direction @ direction)
    dof = model['degrees_of_freedom']
    sm_chi2 = float(residual @ residual)
    tested_residual = residual-fraction*direction
    tested_chi2 = float(tested_residual @ tested_residual)
    fit = None
    if info > 0 and model['bsm_integral'] > 0:
        unconstrained = float(direction @ residual/info)
        fitted = min(max(unconstrained, 0.), cap_fraction)
        muhat = model['sm_integral']/model['bsm_integral'] * fitted/(1-fitted)
        at_boundary = fitted == 0 or fitted == cap_fraction
        fitted_residual = residual-fitted*direction
        fit = {'shape_fraction': fitted, 'unconstrained_shape_fraction': unconstrained,
               'unconstrained_fraction_standard_error': 1/math.sqrt(info), 'signal_strength': muhat,
               'chi2': float(fitted_residual @ fitted_residual), 'at_boundary': at_boundary,
               'free_parameters': 1, 'interior_residual_degrees_of_freedom': dof-1,
               'p_value': None,
               'distribution_scope': 'The fitted statistic has boundary-dependent distributions; no fitted chi-square p-value is assigned.'}
    # A nonorthogonal contrast basis spans the same area-null subspace and
    # checks basis invariance without changing or conditioning the source C.
    alternate = np.column_stack((np.eye(len(model['bin_ids'])-1), -model['area'][:-1]/model['area'][-1]))
    alternate_covariance = alternate @ model['covariance'] @ alternate.T
    alternate_residual = alternate @ (model['data']-prediction)
    z = np.linalg.solve(np.linalg.cholesky(alternate_covariance), alternate_residual)
    alternate_chi2 = float(z @ z)
    difference = abs(alternate_chi2-tested_chi2)
    basis_passed = difference <= 1e-9*max(tested_chi2, alternate_chi2, 1.)
    if not basis_passed:
        raise ValueError('declared contrast diagnosis is not numerically basis invariant')
    area, covariance, normal = model['area'], model['covariance'], model['normal']
    return {'schema_version': 1, 'kind': 'nonlinear_normalized_gaussian_contrast',
            'analysis_id': document['analysis_id'], 'quantity': document['quantity'],
            'bin_ids': model['bin_ids'], 'sources': document['sources'], 'task': spec,
            'grounding': _grounding(document),
            'input_data': model['data'].tolist(), 'input_covariance': covariance.tolist(),
            'contrast_projection': p.tolist(), 'contrast_covariance': c.tolist(),
            'contrast_degrees_of_freedom': dof, 'covariance_condition_number': model['covariance_condition_number'],
            'discarded_normalization': {'area_coefficients': area.tolist(),
                'data_integral': float(area @ model['data']), 'data_unit_area_residual': float(area @ model['data']-1),
                'supplied_area_variance': float(area @ covariance @ area),
                'supplied_normal_direction_variance': float(normal @ covariance @ normal),
                'supplied_contrast_normal_cross_covariance': (p @ covariance @ normal).tolist(),
                'scope': 'A declared measured-contrast likelihood discards this direction; no claim that the original covariance has a deterministic normalization null space.'},
            'prediction': {'values': prediction.tolist(), 'unit': document['quantity']['unit'],
                'sm_integral': model['sm_integral'], 'bsm_integral': model['bsm_integral'],
                'total_integral_before_normalization': total, 'bsm_shape_fraction': fraction,
                'formula': '(SM + mu*BSM)/(integral(SM) + mu*integral(BSM))',
                'absolute_unit': document['sm_absolute']['unit']},
            'goodness_of_fit': {'sm': {'chi2': sm_chi2, 'degrees_of_freedom': dof, 'p_value': float(chi2.sf(sm_chi2, dof))},
                'tested_model': {'chi2': tested_chi2, 'degrees_of_freedom': dof, 'p_value': float(chi2.sf(tested_chi2, dof))}},
            'fit': fit, 'basis_invariance': {'passed': basis_passed, 'alternate_chi2': alternate_chi2,
                                            'absolute_difference': difference, 'relative_tolerance': 1e-9},
            'inference': None, 'status': 'passed', 'physics_validated': False,
            'status_scope': 'Numerical Gaussian diagnosis of explicitly declared measured contrasts only',
            'limitations': ['The supplied full covariance is preserved; its normalization inconsistency is reported, not repaired.',
                'Fixed-hypothesis p-values are conditional on the supplied Gaussian contrast approximation, not an experimental-likelihood reconstruction.',
                'The nonlinear positive-mixture prediction retains the denominator at every signal strength; signed interference is outside this contract.',
                'SM and BSM predictions are fixed central values with no MC or theory uncertainty inferred.',
                'No CLs exclusion, fitted boundary p-value, generator validation or paper closure is established.']}


def run(spec, base, out):
    path = inputs(spec, base)[0]
    document, digest = _load(path)
    result = diagnose(document, spec)
    result['input'] = {'path': str(path), 'sha256': digest}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    atomic_json(out/'normalized-contrast.json', result)
    return result
