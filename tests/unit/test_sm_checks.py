"""Fictional sibling records exercise arithmetic and declared measurement scope."""
from copy import deepcopy
import importlib
import json

import numpy as np
import pytest


CHECK_NAMES = (
    'frame_declared', 'covariance_assembled', 'normalized_rule', 'theory_cov_included',
    'prediction_convention', 'alphas_consistent', 'prescription_declared', 'np_once',
    'unfolding_closure', 'unfolding_coverage', 'regularization_declared', 'tune_heldout',
    'pdf_not_circular', 'tolerance_declared', 'ew_scheme', 'parametrization_range',
    'measurement_overlap', 'validity_range', 'reference_version', 'pdf_error_type',
    'ew_combination', 'amplitude_complete',
)


def packet():
    """All values and populations are fictional, supplied by the caller."""
    covariance = [[0.04, -0.04], [-0.04, 0.04]]
    bundle = {
        'id': 'ANA-0001', 'bins': ['bin-a', 'bin-b'], 'values': [0.4, 0.6],
        'frame': {'level': 'dressed', 'photon_radius': 0.12, 'prompt': 'direct',
                  'tau_feeddown': 'excluded', 'fiducial': 'selection-a'},
        'normalization': {'kind': 'normalized', 'weights': [1., 1.]},
        'covariance': covariance,
        'uncertainties': [{'errors': [0.2, 0.2], 'correlation': [[1., -1.], [-1., 1.]]}],
        'theory_covariance': [[0.01, -0.01], [-0.01, 0.01]],
        'source_version': 'revision-a', 'datasets': ['sample-a'],
    }
    record = {
        'prediction_frame': deepcopy(bundle['frame']),
        'inverse': {'method': 'pseudoinverse', 'rank': 1,
                    'matrix': np.linalg.pinv(covariance).tolist()},
        'comparison_covariance': [[0.05, -0.05], [-0.05, 0.05]],
        'theory_components': [{'id': 'scale', 'covariance': bundle['theory_covariance']}],
        'prediction': {'shape_order': 'order-a', 'rate_order': 'order-a',
                       'normalization': 'normalized', 'rate_rescaling': None},
        'alphas': {'matrix_element': 0.121, 'pdf': 0.121, 'scale': 93., 'unit': 'GeV'},
        'scale': {'prescription': 'seven-point', 'members': [[1,1], [.5,.5], [.5,1],
                  [1,.5], [1,2], [2,1], [2,2]], 'correlation': 'envelope',
                  'covariance_model': None},
        'nonperturbative': {'input_includes': False, 'applications': 1,
                           'input_values': [1., 2.], 'factors': [1.1, 0.9],
                           'output_values': [1.1, 1.8]},
        'unfolding': {
            'truth': [10., 20.], 'response': [[0.8, 0.1], [0.2, 0.9]],
            'reconstructed': [10., 20.], 'unfolded': [10., 20.],
            'closure_tolerance': 0.01,
            'stress_tests': [{'truth': [20., 10.], 'unfolded': [20., 10.]}],
            'coverage': {'truth': [10.], 'intervals': [[[9., 11.]], [[9., 11.]],
                                                     [[12., 13.]], [[9., 11.]]],
                         'minimum': 0.7, 'minimum_trials': 4},
            'regularization': {'method': 'iterations', 'strength': 3,
                               'selection_rule': 'heldout-risk', 'prior': 'prior-a',
                               'prior_variations': ['prior-b'], 'selected_before_data': True},
        },
        'tune': {'fit_observables': ['obs-a'], 'validation_observables': ['obs-b'],
                 'weights': {'obs-a': 2.}, 'heldout_residuals': [0.1], 'maximum_residual': 0.2},
        'pdf': {'fit_datasets': ['sample-b'], 'impact_datasets': ['sample-a'],
                'tolerance': {'value': 2., 'criterion': 'delta-chi2', 'source': 'supplied-rule'},
                'error_type': 'replicas', 'members': [[0.8, 1.2], [1., 1.], [1.2, 0.8]],
                'confidence_level': 68., 'target_confidence_level': 68., 'cl_factor': 1.,
                'uncertainty': [0.2, 0.2]},
        'ew': {'data_scheme': 'alpha-zero', 'prediction_scheme': 'alpha-zero',
               'data_width': 'pole', 'prediction_width': 'pole',
               'data_angle': 'effective-leptonic', 'prediction_angle': 'effective-leptonic',
               'data_top_mass': 'pole', 'prediction_top_mass': 'pole',
               'top_mass_value': 171., 'oblique': False, 'reference_point': None},
        'parameters': {'point': {'x': 2.}, 'ranges': {'x': [1., 3.]}},
        'combination': {'measurements': [
            {'id': 'channel-a', 'datasets': ['sample-a'], 'systematics': ['lumi-a']},
            {'id': 'channel-b', 'datasets': ['sample-a'], 'systematics': ['lumi-a']}],
            'overlap': [{'pair': ['channel-a', 'channel-b'], 'datasets': ['sample-a'],
                         'systematics': ['lumi-a'], 'cross_covariance': [[0.01]]}],
            'covariance': [[0.1, 0.01], [0.01, 0.1]]},
        'validity': {'coordinates': [2., 3.], 'minimum': 1., 'maximum': 4.,
                     'method': 'fixed-order', 'source': 'supplied-domain'},
        'reference_version': 'revision-a',
        'ew_combination': {'qcd': [10., 20.], 'ew_delta': [1., 2.],
                           'born': [5., 10.], 'scheme': 'additive',
                           'output': [11., 22.], 'alternative': [12., 24.],
                           'uncertainty': [1., 2.], 'real_radiation_dominated': True,
                           'photon_induced': 'included'},
        'amplitudes': {'required': ['term-a', 'term-b', 'cross-term'],
                       'included': ['term-a', 'term-b', 'cross-term'], 'omissions': []},
    }
    return bundle, record


def plant(name, bundle, record):
    if name == 'frame_declared': record['prediction_frame']['level'] = 'born'
    elif name == 'covariance_assembled': bundle['covariance'][0][1] = 0.
    elif name == 'normalized_rule': record['inverse'] = {'method': 'full-inverse', 'rank': 2}
    elif name == 'theory_cov_included': record['comparison_covariance'] = bundle['covariance']
    elif name == 'prediction_convention': record['prediction']['rate_order'] = 'order-b'
    elif name == 'alphas_consistent': record['alphas']['matrix_element'] = 0.13
    elif name == 'prescription_declared': record['scale']['correlation'] = None
    elif name == 'np_once': record['nonperturbative']['input_includes'] = True
    elif name == 'unfolding_closure': record['unfolding']['stress_tests'][0]['unfolded'] = [10., 20.]
    elif name == 'unfolding_coverage': record['unfolding']['coverage']['intervals'] *= 0
    elif name == 'regularization_declared': record['unfolding']['regularization']['prior_variations'] = []
    elif name == 'tune_heldout': record['tune']['validation_observables'] = ['obs-a']
    elif name == 'pdf_not_circular': record['pdf']['fit_datasets'] = ['sample-a']
    elif name == 'tolerance_declared': record['pdf']['tolerance']['criterion'] = ''
    elif name == 'ew_scheme': record['ew']['prediction_width'] = 'running'
    elif name == 'parametrization_range': record['parameters']['point']['x'] = 4.
    elif name == 'measurement_overlap': record['combination']['overlap'] = []
    elif name == 'validity_range': record['validity']['coordinates'] = [0.2]
    elif name == 'reference_version': record['reference_version'] = 'revision-b'
    elif name == 'pdf_error_type': record['pdf']['error_type'] = 'hessian'
    elif name == 'ew_combination': record['ew_combination']['alternative'] = []
    elif name == 'amplitude_complete': record['amplitudes']['included'].remove('cross-term')
    else: raise AssertionError(name)


@pytest.mark.parametrize('name', CHECK_NAMES)
def test_planted_fault_is_rejected_and_clean_sibling_accepted(name, tmp_path):
    # Import inside each test so the base records every missing capability separately.
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    paths = [tmp_path / 'bundle.json', tmp_path / 'record.json']
    for path, value in zip(paths, (bundle, record)): path.write_text(json.dumps(value))
    assert getattr(sm, name)(*paths) == []
    plant(name, bundle, record)
    for path, value in zip(paths, (bundle, record)): path.write_text(json.dumps(value))
    assert getattr(sm, name)(*paths), name


@pytest.mark.parametrize('name', CHECK_NAMES)
def test_missing_inputs_never_pass(name):
    sm = importlib.import_module('ravel.validation.sm_checks')
    assert getattr(sm, name)({}, {})


@pytest.mark.parametrize('name', CHECK_NAMES)
def test_registered_check_result_reports_fault(name):
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    assert sm.run('check:sm.' + name, bundle, record)['status'] == 'passed'
    plant(name, bundle, record)
    result = sm.run('check:sm.' + name, bundle, record)
    assert result['status'] == 'failed' and result['diagnostics']['errors']


@pytest.mark.parametrize('name', CHECK_NAMES)
def test_corrupt_record_file_is_rejected(name, tmp_path):
    sm = importlib.import_module('ravel.validation.sm_checks')
    path = tmp_path / 'record.json'
    path.write_text('{"value": NaN}')
    assert getattr(sm, name)({}, path)


@pytest.mark.parametrize('fault', ['rank', 'matrix', 'normalization', 'null-direction'])
def test_normalized_check_recomputes_null_direction_rank_and_inverse(fault):
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    if fault == 'rank': record['inverse']['rank'] = 2
    elif fault == 'matrix': record['inverse']['matrix'] = np.eye(2).tolist()
    elif fault == 'normalization': bundle['values'] = [0.4, 0.4]
    else: bundle['covariance'] = np.eye(2).tolist()
    assert sm.normalized_rule(bundle, record)


def test_drop_bin_uses_the_declared_bin_and_reduced_covariance():
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    record['inverse'] = {'method': 'drop-bin', 'dropped_bin': 'bin-a', 'rank': 1, 'matrix': [[25.]]}
    assert sm.normalized_rule(bundle, record) == []
    record['inverse']['dropped_bin'] = 'unknown-bin'
    assert sm.normalized_rule(bundle, record)


def test_coverage_is_computed_from_intervals_not_a_declared_fraction():
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    coverage = record['unfolding']['coverage']
    coverage['intervals'] = [[[12., 13.]]] * 4
    coverage['claimed_fraction'] = 1.
    assert sm.unfolding_coverage(bundle, record)


def test_uncertainty_formula_and_confidence_rescaling_are_recomputed():
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    pdf = record['pdf']
    pdf.update(error_type='symmhessian', members=[[1., 1.], [1.2, 0.8]],
               uncertainty=[0.2, 0.2])
    assert sm.pdf_error_type(bundle, record) == []
    pdf.update(confidence_level=90., target_confidence_level=68., cl_factor=1.)
    assert sm.pdf_error_type(bundle, record)


def test_unrecognized_check_is_refused():
    sm = importlib.import_module('ravel.validation.sm_checks')
    with pytest.raises(ValueError, match='unknown'):
        sm.run('check:sm.unknown', {}, {})


def test_combination_accepts_supplied_vector_populations_and_block_overlap():
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    combination = record['combination']
    combination['measurements'][0]['bins'] = ['first', 'second']
    combination['measurements'][1]['bins'] = ['third']
    combination['overlap'][0]['cross_covariance'] = [[0.01], [0.02]]
    combination['covariance'] = [[0.1, 0., 0.01], [0., 0.1, 0.02], [0.01, 0.02, 0.1]]
    assert sm.measurement_overlap(bundle, record) == []
    combination['covariance'][1][2] = combination['covariance'][2][1] = 0.
    assert sm.measurement_overlap(bundle, record)


def test_cross_covariance_orientation_follows_supplied_pair_order():
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    combination = record['combination']
    combination['measurements'][0]['bins'] = ['first', 'second']
    combination['measurements'][1]['bins'] = ['third']
    combination['overlap'][0]['pair'].reverse()
    combination['overlap'][0]['cross_covariance'] = [[0.01, 0.02]]
    combination['covariance'] = [[0.1, 0., 0.01], [0., 0.1, 0.02], [0.01, 0.02, 0.1]]
    assert sm.measurement_overlap(bundle, record) == []


def test_disjoint_measurements_can_have_an_empty_shared_systematic_population():
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    combination = record['combination']
    for i, measurement in enumerate(combination['measurements']):
        measurement['datasets'] = ['sample-' + str(i)]
        measurement['systematics'] = []
    combination['overlap'] = []
    combination['covariance'] = [[0.1, 0.], [0., 0.1]]
    assert sm.measurement_overlap(bundle, record) == []


def test_replica_nominal_member_is_not_treated_as_a_replica():
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    pdf = record['pdf']
    pdf['nominal_member_included'] = True
    pdf['members'] = [[1., 1.], [0.8, 1.2], [1., 1.], [1.2, 0.8]]
    assert sm.pdf_error_type(bundle, record) == []
    pdf['uncertainty'] = [0.1, 0.1]
    assert sm.pdf_error_type(bundle, record)


@pytest.mark.parametrize('fault', ['lumi', 'systematics'])
def test_overlap_source_identity_must_cover_every_shared_source(fault):
    sm = importlib.import_module('ravel.validation.sm_checks')
    bundle, record = packet()
    combination = record['combination']
    if fault == 'lumi':
        for measurement in combination['measurements']: measurement['luminosity_source'] = 'luminosity-a'
    else:
        for measurement in combination['measurements']: measurement['systematics'].append('calibration-a')
    assert sm.measurement_overlap(bundle, record)


def small_unit_packet(unit=1e-12):
    """The same fictional records expressed in a unit larger by a supplied factor."""
    bundle, record = packet()
    square = unit * unit
    scaled = lambda rows, factor: (np.asarray(rows) * factor).tolist()
    bundle['values'] = scaled(bundle['values'], unit)
    bundle['normalization']['weights'] = scaled(bundle['normalization']['weights'], 1 / unit)
    bundle['covariance'] = scaled(bundle['covariance'], square)
    bundle['uncertainties'][0]['errors'] = scaled(bundle['uncertainties'][0]['errors'], unit)
    bundle['theory_covariance'] = scaled(bundle['theory_covariance'], square)
    record['theory_components'][0]['covariance'] = bundle['theory_covariance']
    record['comparison_covariance'] = scaled(record['comparison_covariance'], square)
    record['inverse']['matrix'] = np.linalg.pinv(bundle['covariance']).tolist()
    record['combination']['covariance'] = scaled(record['combination']['covariance'], square)
    record['combination']['overlap'][0]['cross_covariance'] = scaled([[0.01]], square)
    record['pdf']['members'] = scaled(record['pdf']['members'], unit)
    record['pdf']['uncertainty'] = scaled(record['pdf']['uncertainty'], unit)
    return bundle, record


@pytest.mark.parametrize('name', ['covariance_assembled', 'normalized_rule', 'theory_cov_included',
                                  'measurement_overlap', 'pdf_error_type'])
def test_fault_detection_does_not_depend_on_the_supplied_unit(name):
    sm = importlib.import_module('ravel.validation.sm_checks')
    unit = 1e-12
    bundle, record = small_unit_packet(unit)
    assert getattr(sm, name)(bundle, record) == []
    if name == 'covariance_assembled':
        bundle['covariance'][0][1] = bundle['covariance'][1][0] = 0.
    elif name == 'normalized_rule':
        # Rank and inverse stay consistent; only the normalization direction is wrong.
        bundle['normalization']['weights'] = [1 / unit, 2 / unit]
        bundle['values'] = [0.2 * unit, 0.4 * unit]
    elif name == 'theory_cov_included':
        record['comparison_covariance'] = bundle['covariance']
    elif name == 'measurement_overlap':
        record['combination']['covariance'][0][1] = record['combination']['covariance'][1][0] = 0.
    else:
        record['pdf']['uncertainty'] = [0.1 * unit, 0.1 * unit]
    assert getattr(sm, name)(bundle, record), name
