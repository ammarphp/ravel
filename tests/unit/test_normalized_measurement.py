"""Nonlinear mixtures, source-preserving contrasts and independent held-out math."""
from copy import deepcopy
import json
import math

import pytest

np = pytest.importorskip('numpy')
pytest.importorskip('scipy')

from ravel.physics.normalized_measurement import diagnose, inputs, mixture, prepare, run, validate


def document():
    ids = ['a', 'b', 'c']
    def vector(values, unit):
        return {'bin_ids': ids[:], 'values': values, 'unit': unit}
    return {'schema_version': 1, 'analysis_id': 'synthetic-nonlinear-contrast-control',
            'quantity': {'axes': [{'name': 'rapidity', 'unit': '1'}],
                         'bins': [{'id': 'a', 'low': [0.], 'high': [1.]},
                                  {'id': 'b', 'low': [1.], 'high': [3.]},
                                  {'id': 'c', 'low': [3.], 'high': [4.]}],
                         'representation': 'differential', 'normalization': 'normalized', 'unit': '1'},
            'data': vector([10/28, 5/28, 8/28], '1'),
            'sm_absolute': vector([2., 3., 4.], 'fb'), 'bsm_absolute': vector([4., 1., 2.], 'fb'),
            'experimental_covariance': {'bin_ids': ids[:], 'unit': '(1)^2',
                'matrix': [[.01, .003, .001], [.003, .02, .002], [.001, .002, .015]]},
            'contrast_policy': {'kind': 'unit_area_orthogonal_contrasts',
                                'theory_policy': 'fixed_central_without_uncertainty'},
            'sources': {'measurement': 'synthetic held-out control', 'covariance': 'declared synthetic full-rank matrix',
                        'sm': 'synthetic positive differential prediction', 'bsm': 'distinct synthetic positive prediction',
                        'approximation': 'Gaussian measured contrasts with fixed central predictions, no physics certification'}}


def task(**updates):
    result = {'schema_version': 1, 'input': 'input.json', 'signal_strength': 1., 'signal_strength_max': 20.}
    result.update(updates)
    return result


def test_nonlinear_mixture_keeps_denominator_and_fixed_model_degrees_of_freedom():
    result = diagnose(document(), task())
    assert result['prediction']['values'] == pytest.approx([.3, .2, .3])
    assert result['prediction']['sm_integral'] == 12
    assert result['prediction']['bsm_integral'] == 8
    assert result['prediction']['bsm_shape_fraction'] == pytest.approx(.4)
    assert result['prediction']['total_integral_before_normalization'] == 20
    assert result['goodness_of_fit']['tested_model']['degrees_of_freedom'] == 2
    # Independent full-rank Gaussian contrast calculation with T=[[1,0,-1],
    # [0,1,-2]], T*C*T^T=[[.023,.029],[.029,.072]].
    r1 = (10/28-.3)-(8/28-.3)
    r2 = (5/28-.2)-2*(8/28-.3)
    expected = (.072*r1*r1-2*.029*r1*r2+.023*r2*r2)/(.023*.072-.029*.029)
    assert result['goodness_of_fit']['tested_model']['chi2'] == pytest.approx(expected)
    assert result['basis_invariance']['alternate_chi2'] == pytest.approx(expected)
    assert result['input_covariance'] == document()['experimental_covariance']['matrix']
    assert result['discarded_normalization']['supplied_area_variance'] == pytest.approx(.127)
    assert result['inference'] is None and result['physics_validated'] is False


@pytest.mark.parametrize('mu', [0., .125, .75, 2., 7.5, 20.])
def test_heldout_strengths_agree_with_direct_absolute_mixture(mu):
    model = prepare(document())
    actual, fraction, total = mixture(model, mu)
    expected = [(s+mu*b)/(12+mu*8) for s, b in zip([2., 3., 4.], [4., 1., 2.])]
    assert actual == pytest.approx(expected)
    assert np.array([1, 2, 1]) @ actual == pytest.approx(1)
    assert fraction == pytest.approx(mu*8/(12+mu*8))
    assert total == pytest.approx(12+mu*8)


def test_fit_is_exact_fraction_fit_and_does_not_assign_boundary_chi_square_pvalue():
    result = diagnose(document(), task())
    fit = result['fit']
    assert fit['shape_fraction'] == pytest.approx(4/7)
    assert fit['signal_strength'] == pytest.approx(2.)
    assert fit['chi2'] == pytest.approx(0., abs=1e-24)
    assert fit['at_boundary'] is False
    assert fit['interior_residual_degrees_of_freedom'] == 1
    assert fit['p_value'] is None
    at_cap = diagnose(document(), task(signal_strength=.5, signal_strength_max=1.))['fit']
    assert at_cap['at_boundary'] is True and at_cap['signal_strength'] == pytest.approx(1.)
    assert at_cap['p_value'] is None
    value = document()
    model = prepare(value)
    # A held-out Gaussian datum favors a negative fraction, outside the
    # positive mixture. The fit is bounded at zero without changing the data.
    value['data']['values'] = (model['shape_sm']-.2*model['shape_direction']).tolist()
    at_zero = diagnose(value, task())['fit']
    assert at_zero['unconstrained_shape_fraction'] == pytest.approx(-.2)
    assert at_zero['shape_fraction'] == at_zero['signal_strength'] == 0
    assert at_zero['at_boundary'] is True and at_zero['p_value'] is None


def test_normalization_mismatch_is_retained_and_contrasts_ignore_only_declared_direction():
    original = document()
    shifted = deepcopy(original)
    shifted['data']['values'] = [v+delta for v, delta in zip(original['data']['values'], [.001, .002, .001])]
    before, after = diagnose(original, task()), diagnose(shifted, task())
    assert after['input_data'] == shifted['data']['values']
    assert after['input_covariance'] == original['experimental_covariance']['matrix']
    assert after['discarded_normalization']['data_unit_area_residual'] == pytest.approx(.006)
    assert after['goodness_of_fit']['tested_model']['chi2'] == pytest.approx(before['goodness_of_fit']['tested_model']['chi2'])
    assert after['fit']['signal_strength'] == pytest.approx(before['fit']['signal_strength'])


def test_prediction_units_reordering_and_alternate_basis_do_not_change_diagnosis():
    original = document()
    changed = deepcopy(original)
    order = [2, 0, 1]
    for key in ('data', 'sm_absolute', 'bsm_absolute'):
        changed[key]['bin_ids'] = [original[key]['bin_ids'][i] for i in order]
        changed[key]['values'] = [original[key]['values'][i] for i in order]
    changed['experimental_covariance']['bin_ids'] = [original['data']['bin_ids'][i] for i in order]
    matrix = np.array(original['experimental_covariance']['matrix'])
    changed['experimental_covariance']['matrix'] = matrix[np.ix_(order, order)].tolist()
    for key in ('sm_absolute', 'bsm_absolute'):
        changed[key]['values'] = [v*1000 for v in changed[key]['values']]
        changed[key]['unit'] = 'ab'
    result, other = diagnose(original, task()), diagnose(changed, task())
    assert other['prediction']['values'] == pytest.approx(result['prediction']['values'])
    assert other['goodness_of_fit']['tested_model'] == pytest.approx(result['goodness_of_fit']['tested_model'])
    assert other['fit']['signal_strength'] == pytest.approx(result['fit']['signal_strength'])


def test_zero_or_proportional_bsm_has_no_invented_shape_sensitivity():
    value = document()
    value['bsm_absolute']['values'] = [0., 0., 0.]
    result = diagnose(value, task())
    assert result['prediction']['bsm_shape_fraction'] == 0
    assert result['fit'] is None
    value['bsm_absolute']['values'] = [4., 6., 8.]
    result = diagnose(value, task())
    assert result['fit'] is None
    assert result['goodness_of_fit']['sm'] == result['goodness_of_fit']['tested_model']


@pytest.mark.parametrize('mutate,match', [
    (lambda d: d['bsm_absolute']['values'].__setitem__(0, -.01), 'signed/interference'),
    (lambda d: d['sm_absolute'].update(values=[0., 0., 0.]), 'positive SM integral'),
    (lambda d: d['experimental_covariance']['matrix'][0].__setitem__(1, .003000000000001), 'exactly symmetric'),
    (lambda d: d['experimental_covariance'].update(matrix=[[0., 0., 0.]]*3), 'singular or ill-conditioned'),
    (lambda d: d['contrast_policy'].update(theory_policy='invented_diagonal_theory'), 'explicit unit-area'),
    (lambda d: d['quantity'].update(unit='fb'), 'unit differs'),
    (lambda d: d['sources'].update(sm=''), 'sm source'),
])
def test_refusals_keep_scientific_boundaries(mutate, match):
    value = document()
    mutate(value)
    with pytest.raises(ValueError, match=match):
        diagnose(value, task())


@pytest.mark.parametrize('updates', [{'signal_strength': -1.}, {'signal_strength_max': 0.},
                                    {'signal_strength': 21.}, {'signal_strength': math.inf}])
def test_strength_domain_is_explicit_and_never_clipped(updates):
    with pytest.raises(ValueError):
        validate(task(**updates))


def test_real_output_binds_complete_input_and_refuses_overwrite(tmp_path):
    path = tmp_path/'input.json'
    path.write_text(json.dumps(document()))
    result = run(task(), tmp_path, tmp_path/'output')
    assert len(result['input']['sha256']) == 64
    assert json.loads((tmp_path/'output/normalized-contrast.json').read_text()) == result
    with pytest.raises(FileExistsError):
        run(task(), tmp_path, tmp_path/'output')


def test_source_grounding_is_bound_and_byte_drift_refuses_before_execution(tmp_path):
    import hashlib

    source = tmp_path/'published-table.yaml'
    source.write_text('exact published source bytes\n')
    value = document()
    value['grounding'] = [{'path': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]
    path = tmp_path/'input.json'
    path.write_text(json.dumps(value))
    assert inputs(task(), tmp_path) == [path.resolve(), source.resolve()]
    source.write_text('changed source bytes\n')
    with pytest.raises(ValueError, match='grounding bytes differ'):
        inputs(task(), tmp_path)
