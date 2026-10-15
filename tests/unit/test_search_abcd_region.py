"""Synthetic external ABCD estimate, closure and shared search-fit controls."""
from copy import deepcopy

import numpy as np
import pytest

from ravel.physics.inference import search
from ravel.physics.statistical_model import abcd_estimate


def abcd_spec(correlated=False):
    return {'background': 'alpha', 'independent': True,
            'uncertainty_treatment': 'independent-delta-lognormal',
            'controls': {k: {'yield': v, 'sumw2': v, 'observation_id': f'sideband_{k}'}
                         for k, v in zip(('B', 'C', 'D'), (200., 100., 1000.))},
            'closure': {'x_pass': [0, 0, 1, 1] * 100,
                        'y_pass': ([0, 0, 1, 1] if correlated else [0, 1, 0, 1]) * 100,
                        'max_abs_correlation': 0.1}}


def synthetic_search():
    doc = {'regions': [{'name': 'target', 'role': 'abcd', 'observed': None, 'bins': 1, 'abcd': abcd_spec()},
                       {'name': 'control_a', 'role': 'CR', 'observed': None},
                       {'name': 'control_b', 'role': 'CR', 'observed': None},
                       {'name': 'validation', 'role': 'VR', 'observed': None}],
           'backgrounds': [
               {'name': 'alpha', 'normfactor': 'scale_alpha', 'yields': {
                   'control_a': {'values': [200.]}, 'control_b': {'values': [10.]},
                   'validation': {'values': [40.]}}},
               {'name': 'beta', 'normfactor': 'scale_beta', 'yields': {
                   'target': {'values': [10.]}, 'control_a': {'values': [10.]},
                   'control_b': {'values': [150.]}, 'validation': {'values': [30.]}}}],
           'signal_points': [{'id': f'point_{i}', 'coordinates': {'x': x, 'y': y},
                              'yields': {'target': {'values': [s]}}}
                             for i, (x, y, s) in enumerate([(0., 0., 3.), (2., 0., 18.), (0., 2., 18.),
                                                          (1., 1., 25.), (0.4, 0.6, 7.)])],
           'mc_statistics': 'none', 'systematics': None, 'data': {'mode': 'mc-pseudo-data', 'injections': {}},
           'computations': {'discovery': True, 'cls_at_nominal': True, 'cls_limits': False, 'background_only_fit': True},
           'asimov_source': 'background-only-fit', 'cls_level': 0.05,
           'mc_adequacy': {'max_relative_uncertainty': 0.5, 'min_effective_entries': 1},
           'contours': {'x': 'x', 'y': 'y', 'levels': {'expected_cls_at_nominal': 0.05},
                        'interpolation': {'method': 'delaunay-linear', 'coordinates': ['x', 'y']}}}
    return doc


def test_abcd_enters_fit_and_records_closure_without_mutating_inputs():
    doc = synthetic_search()
    original = deepcopy(doc)
    result = search.run(doc)
    assert doc == original
    estimate = result['abcd'][0]
    assert estimate['prediction'] == pytest.approx(20.)
    assert estimate['sigma'] == pytest.approx(20 * np.sqrt(1/200 + 1/100 + 1/1000))
    assert estimate['closure']['status'] == 'passed'
    fit = result['background_only_fit']
    assert fit['status'] == 'converged'
    assert set(fit['fit_channels']) == {'control_a', 'control_b'}
    parameters = {p['name']: p['value'] for p in fit['parameters']}
    assert parameters['scale_alpha'] == pytest.approx(1., abs=1e-3)
    assert parameters['scale_beta'] == pytest.approx(1., abs=1e-3)
    target = next(r for r in fit['region_predictions'] if r['region'] == 'target')
    assert sum(target['prediction']) == pytest.approx(30., abs=1e-3)
    assert sum(sum(p['postfit']) for p in target['processes']) == pytest.approx(sum(target['prediction']))
    model = search.SearchModel(doc)
    spec = model.workspace(model.points[0])
    mods = [m for c in spec['channels'] if c['name'] == 'target' for s in c['samples'] for m in s['modifiers']]
    assert any(m['name'] == 'abcd_target' and m['type'] == 'normsys' for m in mods)
    assert 'validation' not in {c['name'] for c in spec['channels']}


def test_planted_abcd_correlation_is_flagged():
    estimate = abcd_estimate(abcd_spec(correlated=True))
    assert estimate['closure']['status'] == 'flagged'
    assert estimate['closure']['correlation'] == pytest.approx(1.)
    assert estimate['closure']['p_value'] < 1e-10


@pytest.mark.parametrize('mutation', ['zero_denominator', 'dependent', 'duplicate', 'constant', 'double_use'])
def test_invalid_abcd_refused(mutation):
    doc = synthetic_search()
    spec = doc['regions'][0]['abcd']
    if mutation == 'zero_denominator':
        spec['controls']['D']['yield'] = 0
    elif mutation == 'dependent':
        spec['independent'] = False
    elif mutation == 'duplicate':
        spec['controls']['C']['observation_id'] = spec['controls']['B']['observation_id']
    elif mutation == 'constant':
        spec['closure']['x_pass'] = [0] * 400
    else:
        spec['controls']['D']['observation_id'] = 'control_a'
    with pytest.raises(ValueError):
        search.SearchModel(doc)
