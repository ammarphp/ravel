"""Declared transformations and comparison metrics against reference series."""
import json
import math

import numpy as np
import pytest

from ravel.plotting import reference_metrics as rm


BASIS = {'kind': 'published_precision', 'source': 'Uncertainty quoted in the published table'}


def series(values, edges=None, **kw):
    edges = edges if edges is not None else list(range(len(values) + 1))
    return rm.binned(edges, values, **kw)


# ----------------------------------------------------------------- transformations
def test_fraction_density_round_trip_is_identity():
    s = series([0.2, 0.3, 0.5], edges=[0, 1, 3, 4], errors=[0.02, 0.03, 0.05], quantity='fraction', unit='1')
    d, rec = rm.transform(s, [{'op': 'fraction_to_density'}])
    assert d['quantity'] == 'density'
    assert np.allclose(d['values'], [0.2, 0.15, 0.5]) and np.allclose(d['errors'], [0.02, 0.015, 0.05])
    back, _ = rm.transform(d, [{'op': 'density_to_fraction'}])
    assert np.allclose(back['values'], s['values']) and np.allclose(back['errors'], s['errors'])
    assert back['quantity'] == 'fraction' and rec[0]['op'] == 'fraction_to_density'


def test_density_conversion_refuses_wrong_quantity():
    with pytest.raises(ValueError, match='fraction'):
        rm.transform(series([1, 2], quantity='density'), [{'op': 'fraction_to_density'}])


def test_exact_edge_rebinning_sums_counts_and_propagates_covariance():
    cov = [[1.0, 0.5, 0, 0], [0.5, 1.0, 0, 0], [0, 0, 4.0, 0], [0, 0, 0, 9.0]]
    s = series([1, 2, 3, 4], edges=[0, 1, 2, 3, 4], covariance=cov, quantity='count', unit='events')
    r, rec = rm.transform(s, [{'op': 'rebin', 'edges': [0, 2, 4]}])
    assert r['edges'] == [0.0, 2.0, 4.0] and np.allclose(r['values'], [3, 7])
    assert np.allclose(r['covariance'], [[3.0, 0.0], [0.0, 13.0]])
    assert rec[0]['mapping'] == [[0, 1], [2, 3]]
    with pytest.raises(ValueError, match='edge'):
        rm.transform(s, [{'op': 'rebin', 'edges': [0, 1.5, 4]}])


def test_density_rebinning_is_width_weighted():
    s = series([1.0, 3.0], edges=[0, 1, 3], quantity='density', unit='pb/GeV')
    r, _ = rm.transform(s, [{'op': 'rebin', 'edges': [0, 3]}])
    assert np.allclose(r['values'], [(1 * 1 + 3 * 2) / 3])


def test_declared_rebinning_matrix_is_applied_as_given():
    s = series([2.0, 4.0, 6.0], quantity='count', unit='events', errors=[1, 1, 1])
    r, rec = rm.transform(s, [{'op': 'rebin_matrix', 'edges': [0, 1.5, 3],
                               'matrix': [[1, 0.5, 0], [0, 0.5, 1]], 'reason': 'declared split of the middle bin'}])
    assert np.allclose(r['values'], [4.0, 8.0])
    assert np.allclose(r['covariance'], [[1.25, 0.25], [0.25, 1.25]])


def test_unit_conversion_of_values_and_axis():
    s = series([1.0, 2.0], edges=[0, 500, 1000], quantity='density', unit='pb/GeV', errors=[0.1, 0.2])
    r, _ = rm.transform(s, [{'op': 'unit', 'to': 'fb/TeV'}, {'op': 'unit', 'axis': 'x', 'from': 'GeV', 'to': 'TeV'}])
    assert r['unit'] == 'fb/TeV' and np.allclose(r['values'], [1e6, 2e6]) and np.allclose(r['errors'], [1e5, 2e5])
    assert np.allclose(r['edges'], [0, 0.5, 1.0])
    with pytest.raises(ValueError, match='unit'):
        rm.transform(s, [{'op': 'unit', 'to': 'GeV'}])


def test_normalisation_to_unit_area_and_declared_total():
    counts = series([1.0, 3.0], edges=[0, 1, 3], quantity='count', unit='events', errors=[1.0, 1.0])
    u, _ = rm.transform(counts, [{'op': 'normalize', 'to': 'unit_area'}])
    assert np.isclose(sum(u['values']), 1.0) and np.allclose(u['errors'], [0.25, 0.25])
    dens = series([1.0, 3.0], edges=[0, 1, 3], quantity='density', unit='1/GeV')
    u2, _ = rm.transform(dens, [{'op': 'normalize', 'to': 'unit_area'}])
    assert np.isclose(sum(v * w for v, w in zip(u2['values'], [1, 2])), 1.0)
    t, _ = rm.transform(counts, [{'op': 'normalize', 'total': 8.0}])
    assert np.allclose(t['values'], [2.0, 6.0])


def test_scale_requires_a_reason():
    with pytest.raises(ValueError, match='reason'):
        rm.transform(series([1.0]), [{'op': 'scale', 'factor': 2.0}])
    s, rec = rm.transform(series([1.0]), [{'op': 'scale', 'factor': 2.0, 'reason': 'two lepton flavours'}])
    assert s['values'] == [2.0] and rec[0]['reason'] == 'two lepton flavours'


# ----------------------------------------------------------------- binned metrics
def test_known_offset_gives_exact_relative_l2_and_zero_shape_distance():
    ref = series([10.0, 20.0, 30.0], errors=[1.0, 2.0, 3.0], quantity='count', unit='events')
    agent = series([11.0, 22.0, 33.0], errors=[0.0, 0.0, 0.0], quantity='count', unit='events')
    out = rm.compare_binned(agent, ref)
    m = out['metrics']
    assert out['status'] == 'complete'
    assert m['relative_l2'] == pytest.approx(0.1)
    assert m['shape_l2'] == pytest.approx(0.0, abs=1e-12)
    assert m['normalization_ratio'] == pytest.approx(1.1)
    assert m['pulls'] == pytest.approx([1.0, 1.0, 1.0])
    assert m['chi2']['value'] == pytest.approx(3.0) and m['chi2']['ndf'] == 3
    assert m['ks']['statistic'] == pytest.approx(0.0, abs=1e-12)


def test_chi2_uses_supplied_covariance():
    cov = [[1.0, 0.3], [0.3, 2.0]]
    ref = series([5.0, 7.0], covariance=cov, quantity='count', unit='events')
    agent = series([6.0, 6.0], errors=[0.5, 0.5], quantity='count', unit='events')
    r = np.array([1.0, -1.0])
    total = np.array(cov) + np.diag([0.25, 0.25])
    expected = float(r @ np.linalg.solve(total, r))
    m = rm.compare_binned(agent, ref)['metrics']
    assert m['chi2']['value'] == pytest.approx(expected)
    assert m['chi2']['covariance'] == 'agent plus reference covariance'
    assert 0 < m['chi2']['p_value'] < 1


def test_ks_statistic_on_shifted_shape():
    ref = series([1.0, 1.0, 0.0, 0.0], quantity='count', unit='events')
    agent = series([0.0, 1.0, 1.0, 0.0], quantity='count', unit='events')
    m = rm.compare_binned(agent, ref)['metrics']
    assert m['ks']['statistic'] == pytest.approx(0.5)


def test_mismatched_bins_make_the_comparison_incomplete():
    ref = series([1.0, 2.0, 3.0], edges=[0, 1, 2, 3], quantity='count', unit='events')
    agent = series([1.0, 2.0], edges=[0, 1, 2], quantity='count', unit='events')
    out = rm.compare_binned(agent, ref, tolerances={'relative_l2': {'pass': 0.1, 'warn': 0.2, 'basis': BASIS},
                                                    'shape_l2': {'pass': 0.1, 'warn': 0.2, 'basis': BASIS}})
    assert out['status'] == 'incomplete'
    assert out['unmatched']['reference'] == [[2.0, 3.0]]
    assert out['verdict'] == 'INCOMPLETE'


def test_quantity_or_unit_mismatch_is_refused_until_declared():
    ref = series([1.0, 2.0], quantity='density', unit='pb/GeV')
    agent = series([1.0, 2.0], quantity='fraction', unit='1')
    with pytest.raises(ValueError, match='quantity'):
        rm.compare_binned(agent, ref)


@pytest.mark.parametrize('value,verdict', [(0.05, 'PASS'), (0.1, 'PASS'), (0.15, 'WARN'), (0.25, 'FAIL')])
def test_tolerance_verdict_boundaries(value, verdict):
    ref = series([10.0, 10.0], quantity='count', unit='events')
    agent = series([10.0 * (1 + value), 10.0 * (1 + value)], quantity='count', unit='events')
    out = rm.compare_binned(agent, ref, tolerances={'relative_l2': {'pass': 0.1, 'warn': 0.2, 'basis': BASIS},
                                                    'shape_l2': {'pass': 0.1, 'warn': 0.2, 'basis': BASIS}})
    assert out['verdicts']['relative_l2']['verdict'] == verdict
    assert out['verdict'] == verdict


def test_tolerance_needs_a_basis():
    ref = series([10.0], quantity='count', unit='events')
    with pytest.raises(ValueError, match='basis'):
        rm.compare_binned(ref, ref, tolerances={'shape_l2': {'pass': 0.1, 'warn': 0.2}})


# ----------------------------------------------------------------- curves, contours, regions
def _circle(r, n=400):
    t = np.linspace(0, 2 * np.pi, n)
    return {'x': list(r * np.cos(t)), 'y': list(r * np.sin(t))}


def test_contour_hausdorff_in_axis_fractions_on_linear_axes():
    axes = {'x': {'scale': 'linear', 'range': [-2, 2]}, 'y': {'scale': 'linear', 'range': [-2, 2]}}
    out = rm.compare_contours([_circle(1.1)], [_circle(1.0)], axes)
    assert out['hausdorff_max'] == pytest.approx(0.025, abs=5e-4)
    assert out['hausdorff_mean'] == pytest.approx(0.025, abs=5e-4)
    assert out['space'].startswith('axis fraction')


def test_contour_distance_on_log_axis_uses_decades():
    axes = {'x': {'scale': 'linear', 'range': [0, 10]}, 'y': {'scale': 'log', 'range': [1, 1e4]}}
    agent = [{'x': [0, 10], 'y': [20, 20]}]
    ref = [{'x': [0, 10], 'y': [10, 10]}]
    out = rm.compare_contours(agent, ref, axes)
    assert out['hausdorff_max'] == pytest.approx(math.log10(2) / 4, rel=1e-3)


def test_region_iou_of_offset_squares_and_curve_closure():
    axes = {'x': {'scale': 'linear', 'range': [0, 2]}, 'y': {'scale': 'linear', 'range': [0, 1]}}
    a = {'polygons': [{'x': [0, 1, 1, 0], 'y': [0, 0, 1, 1]}]}
    b = {'polygons': [{'x': [0.5, 1.5, 1.5, 0.5], 'y': [0, 0, 1, 1]}]}
    out = rm.region_iou(a, b, axes, grid=400)
    assert out['iou'] == pytest.approx(1 / 3, abs=0.01)
    curve = {'curve': {'x': [0, 1, 2], 'y': [0.5, 0.5, 0.5]}, 'close': 'below'}
    half = {'polygons': [{'x': [0, 2, 2, 0], 'y': [0, 0, 0.5, 0.5]}]}
    assert rm.region_iou(curve, half, axes, grid=200)['iou'] == pytest.approx(1.0, abs=0.01)


def test_curve_relative_deviation_at_reference_points():
    axes = {'x': {'scale': 'linear'}, 'y': {'scale': 'log'}}
    ref = {'x': [1, 2, 3, 4], 'y': [10, 100, 1000, 10000]}
    agent = {'x': [1, 2, 3, 4], 'y': [11, 110, 1100, 11000]}
    out = rm.compare_curves(agent, ref, axes)
    assert out['max_relative_deviation'] == pytest.approx(0.1, rel=1e-6)
    assert out['mean_relative_deviation'] == pytest.approx(0.1, rel=1e-6)
    assert out['points'] == 4


# ----------------------------------------------------------------- sources and the specification
def test_hepdata_table_source_with_asymmetric_and_percent_errors(tmp_path):
    table = {'independent_variables': [{'header': {'name': 'Mass', 'units': 'GeV'},
                                         'values': [{'low': 100, 'high': 200}, {'low': 200, 'high': 300}]}],
             'dependent_variables': [{'header': {'name': 'Cross section', 'units': 'fb/GeV'},
                                      'values': [{'value': 10.0, 'errors': [{'label': 'stat', 'symerror': 1.0},
                                                                            {'label': 'sys', 'asymerror': {'plus': 2.0, 'minus': -1.0}}]},
                                                 {'value': 5.0, 'errors': [{'label': 'stat', 'symerror': '10%'}]}]}]}
    (tmp_path / 'table.json').write_text(json.dumps(table))
    s = rm.load_source({'hepdata': 'table.json', 'column': 'Cross section', 'quantity': 'density'}, tmp_path)
    assert s['edges'] == [100.0, 200.0, 300.0] and s['values'] == [10.0, 5.0] and s['unit'] == 'fb/GeV'
    assert s['error_high'][0] == pytest.approx(math.sqrt(1 + 4)) and s['error_low'][0] == pytest.approx(math.sqrt(2))
    assert s['error_high'][1] == pytest.approx(0.5)
    assert s['stat_errors'] == pytest.approx([1.0, 0.5])


def test_binned_values_result_and_digitized_series_sources(tmp_path):
    result = {'schema_version': 1, 'kind': 'binned_values', 'axes': [{'name': 'MET', 'unit': 'GeV'}],
              'unit': 'events', 'representation': 'integrated',
              'bins': [{'low': [0], 'high': [10], 'value': 4.0, 'uncertainty': 2.0},
                       {'low': [10], 'high': [20], 'value': 9.0}]}
    (tmp_path / 'result.json').write_text(json.dumps(result))
    s = rm.load_source({'path': 'result.json'}, tmp_path)
    assert s['edges'] == [0.0, 10.0, 20.0] and s['quantity'] == 'count' and s['errors'] == [2.0, 0.0]
    digitized = {'kind': 'digitized-series', 'axes': {'y': {'unit': 'pb'}},
                 'series': [{'name': 'step', 'kind': 'line',
                             'segments': [{'x': [0, 9.99, 10.01, 20], 'y': [3, 3, 8, 8],
                                           'x_uncertainty': [0.01] * 4, 'y_uncertainty': [0.1] * 4}]}]}
    (tmp_path / 'dig.json').write_text(json.dumps(digitized))
    d = rm.load_source({'digitized': 'dig.json', 'series': 'step', 'as': 'bins', 'edges': [0, 10, 20],
                        'quantity': 'count', 'unit': 'events'}, tmp_path)
    assert np.allclose(d['values'], [3, 8]) and np.allclose(d['digitization_errors'], [0.1, 0.1])


def test_specification_writes_comparison_with_provenance(tmp_path):
    ref = {'edges': [0, 1, 2], 'values': [0.4, 0.6], 'errors': [0.04, 0.06], 'quantity': 'fraction', 'unit': '1'}
    agent = {'edges': [0, 1, 2], 'values': [40.0, 62.0], 'errors': [2.0, 2.0], 'quantity': 'count', 'unit': 'events'}
    (tmp_path / 'ref.json').write_text(json.dumps(ref))
    (tmp_path / 'agent.json').write_text(json.dumps({'result': agent}))
    spec = {'schema_version': 1, 'kind': 'binned',
            'agent': {'path': 'agent.json', 'pointer': '/result'}, 'reference': {'path': 'ref.json'},
            'transformations': {'agent': [{'op': 'normalize', 'to': 'unit_area'},
                                          {'op': 'relabel', 'quantity': 'fraction', 'unit': '1',
                                           'reason': 'unit-area counts are fractions'}]},
            'tolerances': {'shape_l2': {'pass': 0.05, 'warn': 0.1, 'basis': BASIS}}}
    (tmp_path / 'spec.json').write_text(json.dumps(spec))
    out = rm.run_spec(tmp_path / 'spec.json', tmp_path / 'comparison.json')
    saved = json.loads((tmp_path / 'comparison.json').read_text())
    assert saved == out
    assert saved['kind'] == 'reference-comparison' and saved['verdict'] == 'PASS'
    assert {p['sha256'] for p in saved['inputs']} and len(saved['inputs']) == 3
    assert [t['op'] for t in saved['transformations']['agent']] == ['normalize', 'relabel']
    assert saved['machine_review_only'] is True
    with pytest.raises(FileExistsError):
        rm.run_spec(tmp_path / 'spec.json', tmp_path / 'comparison.json')


# ----------------------------------------------------------------- physics-fidelity comparison object
def test_perfect_match_gives_zero_distances_and_a_null_concentration():
    ref = series([5.0, 10.0, 5.0], quantity='count', unit='events')
    m = rm.compare_binned(ref, ref)['metrics']
    assert m['relative_l2_raw'] == 0 and m['relative_l2_shape'] == 0 and m['delta_norm'] == 0
    assert m['d_bar'] == 0 and m['d_max'] == 0
    assert m['concentration'] is None and m['concentration_reason'] == 'd_bar_zero'
    assert m['n_bins'] == 3 and m['n_filled'] == 3


def test_all_zero_prediction_gives_raw_one_and_a_null_shape():
    ref = series([5.0, 10.0, 5.0], quantity='count', unit='events')
    agent = series([0.0, 0.0, 0.0], quantity='count', unit='events')
    m = rm.compare_binned(agent, ref)['metrics']
    assert m['relative_l2_raw'] == pytest.approx(1.0)
    assert m['relative_l2_shape'] is None and m['shape_reason'] == 'zero_total'


def test_single_bin_has_no_shape():
    ref = series([5.0], quantity='count', unit='events')
    m = rm.compare_binned(series([6.0], quantity='count', unit='events'), ref)['metrics']
    assert m['relative_l2_shape'] is None and m['shape_reason'] == 'single_bin'


def test_uniform_factor_two_is_a_normalisation_difference():
    ref = series([5.0, 10.0, 5.0], errors=[0.5, 0.5, 0.5], quantity='count', unit='events')
    agent = series([10.0, 20.0, 10.0], quantity='count', unit='events')
    out = rm.compare_binned(agent, ref)
    m = out['metrics']
    assert m['relative_l2_raw'] == pytest.approx(1.0) and m['relative_l2_shape'] == pytest.approx(0.0, abs=1e-12)
    assert m['delta_norm'] == pytest.approx(1.0)
    assert out['diagnosis_hint']['compatible_with'] == 'normalization'
    assert 'never' in out['diagnosis_hint']['note']


def test_shape_difference_points_to_selection_or_detector_and_small_noise_to_statistics():
    ref = series([10.0, 10.0, 10.0, 10.0], errors=[0.1] * 4, quantity='count', unit='events')
    agent = series([16.0, 12.0, 8.0, 4.0], quantity='count', unit='events')
    assert rm.compare_binned(agent, ref)['diagnosis_hint']['compatible_with'] == 'selection or detector'
    noisy = series([10.0, 10.0, 10.0, 10.0], errors=[3.0] * 4, quantity='count', unit='events')
    agent = series([11.0, 9.5, 10.5, 9.0], quantity='count', unit='events')
    assert rm.compare_binned(agent, noisy)['diagnosis_hint']['compatible_with'] == 'statistics'


def test_concentration_is_bounded_below_by_two_over_k():
    rng = np.random.default_rng(3)
    for k in (2, 5, 9):
        for _ in range(20):
            ref = series(rng.uniform(1, 5, k).tolist(), quantity='count', unit='events')
            agent = series(rng.uniform(1, 5, k).tolist(), quantity='count', unit='events')
            m = rm.compare_binned(agent, ref)['metrics']
            assert m['concentration'] >= 2 / k - 1e-12
            assert m['concentration_bound'] == pytest.approx(2 / k)
    # The bound is attained by equal-magnitude alternating deviations.
    ref = series([1.0, 1.0, 1.0, 1.0], quantity='count', unit='events')
    agent = series([1.5, 0.5, 1.5, 0.5], quantity='count', unit='events')
    assert rm.compare_binned(agent, ref)['metrics']['concentration'] == pytest.approx(0.5)


def test_edge_mismatched_bins_need_a_declared_rebin():
    ref = series([1.0, 2.0], edges=[0, 1, 2], quantity='count', unit='events')
    agent = series([1.0, 2.0], edges=[0, 1.5, 2], quantity='count', unit='events')
    with pytest.raises(ValueError, match='rebin'):
        rm.compare_binned(agent, ref)


def test_fraction_to_density_equals_manual_bin_width_division():
    s = series([0.25, 0.25, 0.5], edges=[0, 2, 3, 7], quantity='fraction', unit='1')
    d, _ = rm.transform(s, [{'op': 'fraction_to_density'}])
    assert d['values'] == pytest.approx([0.25 / 2, 0.25 / 1, 0.5 / 4])


def test_covariance_distance_matches_the_existing_gaussian_distance():
    from ravel.workflow.quantitative_predictive_checks import gaussian_distance
    cov = [[1.0, 0.4, 0.1], [0.4, 2.0, 0.3], [0.1, 0.3, 1.5]]
    ref = series([5.0, 7.0, 9.0], covariance=cov, quantity='count', unit='events')
    agent = series([6.0, 6.0, 10.0], quantity='count', unit='events')
    expected = gaussian_distance(np.array([1.0, -1.0, 1.0]), np.array(cov),
                                 {'equilibrated_condition_max': 1e12}, np)['value']
    m = rm.compare_binned(agent, ref)['metrics']
    assert m['chi2']['value'] == pytest.approx(expected)
    assert m['pull_basis'] == 'correlated covariance supplied; chi2 uses the full covariance'
    diag = rm.compare_binned(agent, series([5.0, 7.0, 9.0], errors=[1, 1, 1], quantity='count', unit='events'))
    assert diag['metrics']['pull_basis'] == 'uncorrelated assumption'


def test_poisson_deviance_on_raw_counts_and_refused_for_weighted_counts():
    ref = series([3.0, 0.0, 7.0], quantity='count', unit='events')
    agent = series([2.5, 0.4, 8.0], quantity='count', unit='events')
    m = rm.compare_binned(agent, ref, reference_counts='raw_observed')['metrics']
    n, mu = np.array([3.0, 0.0, 7.0]), np.array([2.5, 0.4, 8.0])
    term = np.where(n > 0, n * np.log(np.where(n > 0, n, 1) / mu), 0.0)
    assert m['poisson_deviance']['value'] == pytest.approx(float(2 * np.sum(mu - n + term)))
    weighted = series([3.2, 0.0, 7.0], quantity='count', unit='events')
    with pytest.raises(ValueError, match='weighted'):
        rm.compare_binned(agent, weighted, reference_counts='raw_observed')
    assert rm.compare_binned(agent, ref)['metrics']['poisson_deviance']['value'] is None


def test_declared_systematics_enter_the_goodness_of_fit():
    ref = series([10.0, 10.0], errors=[1.0, 1.0], quantity='count', unit='events')
    agent = series([11.0, 11.0], quantity='count', unit='events')
    plain = rm.compare_binned(agent, ref)['metrics']
    assert plain['goodness_of_fit']['systematics'] == []
    assert 'no systematic' in plain['goodness_of_fit']['reason']
    syst = [{'label': 'Luminosity', 'applies_to': 'agent', 'relative': 0.1, 'correlation': 'full'}]
    m = rm.compare_binned(agent, ref, systematics=syst)['metrics']
    cov = np.diag([1.0, 1.0]) + np.outer([1.1, 1.1], [1.1, 1.1])
    r = np.array([1.0, 1.0])
    assert m['chi2']['value'] == pytest.approx(float(r @ np.linalg.solve(cov, r)))
    assert m['goodness_of_fit']['systematics'][0]['label'] == 'Luminosity'


def test_threshold_basis_must_be_typed_and_raw_l2_cannot_decide_alone():
    ref = series([10.0, 10.0], quantity='count', unit='events')
    with pytest.raises(ValueError, match='basis'):
        rm.compare_binned(ref, ref, tolerances={'shape_l2': {'pass': 0.1, 'warn': 0.2, 'basis': 'my opinion'}})
    spread = {'kind': 'supervised_spread', 'n': 5, 'evidence_sha256': 'a' * 64}
    with pytest.raises(ValueError, match='independent reference reruns'):
        rm.compare_binned(ref, ref, tolerances={'shape_l2': {'pass': 0.1, 'warn': 0.2, 'basis': spread}})
    spread['evidence'] = 'independent reference reruns'
    out = rm.compare_binned(ref, ref, tolerances={'shape_l2': {'pass': 0.1, 'warn': 0.2, 'basis': spread}})
    assert out['verdict'] == 'PASS'
    community = {'kind': 'community', 'citation': 'Les Houches recommendations (2019)'}
    with pytest.raises(ValueError, match='raw'):
        rm.compare_binned(ref, ref, tolerances={'relative_l2_raw': {'pass': 0.1, 'warn': 0.2, 'basis': community}})


def test_a_perturbed_reference_flips_pass_to_fail():
    ref = series([10.0, 20.0, 30.0], errors=[1.0, 1.0, 1.0], quantity='count', unit='events')
    agent = series([10.2, 19.8, 30.1], quantity='count', unit='events')
    tol = {'shape_l2': {'pass': 0.05, 'warn': 0.1, 'basis': BASIS},
           'delta_norm': {'pass': 0.05, 'warn': 0.1, 'basis': BASIS}}
    assert rm.compare_binned(agent, ref, tolerances=tol)['verdict'] == 'PASS'
    bent = series([10.0, 20.0, 45.0], errors=[1.0, 1.0, 1.0], quantity='count', unit='events')
    assert rm.compare_binned(agent, bent, tolerances=tol)['verdict'] == 'FAIL'


def test_scalar_pull_and_resolving_power():
    out = rm.compare_scalar({'value': 1.30, 'uncertainty': 0.05}, {'value': 1.20, 'uncertainty': 0.10})
    assert out['pull'] == pytest.approx(0.1 / math.hypot(0.05, 0.10))
    assert out['resolving_power'] == pytest.approx(0.5)
    assert out['relative_deviation'] == pytest.approx(0.1 / 1.2)


def test_curve_deviation_at_declared_points_contour_tips_and_area_ratio():
    axes = {'x': {'scale': 'linear', 'range': [0, 10]}, 'y': {'scale': 'linear', 'range': [0, 10]}}
    ref = {'x': [0, 10], 'y': [1, 1]}
    agent = {'x': [0, 10], 'y': [1.1, 1.1]}
    out = rm.compare_curves(agent, ref, axes, at=[2.0, 5.0])
    assert out['points'] == 2 and out['max_relative_deviation'] == pytest.approx(0.1)
    tips = rm.compare_contours([{'x': [0, 4, 0], 'y': [0, 2, 4]}], [{'x': [0, 5, 0], 'y': [0, 2, 4]}], axes,
                               tip='max_x')['tip']
    assert tips['agent'] == [4, 2] and tips['reference'] == [5, 2] and tips['difference'] == [-1, 0]
    a = {'polygons': [{'x': [0, 4, 4, 0], 'y': [0, 0, 10, 10]}]}
    b = {'polygons': [{'x': [0, 5, 5, 0], 'y': [0, 0, 10, 10]}]}
    assert rm.region_iou(a, b, axes)['area_ratio'] == pytest.approx(0.8, abs=0.01)


def test_comparison_object_summary_is_natural_language(tmp_path):
    ref = series([5.0, 10.0, 5.0], errors=[0.5, 0.5, 0.5], quantity='count', unit='events')
    agent = series([10.0, 20.0, 10.0], quantity='count', unit='events')
    out = rm.compare_binned(agent, ref, tolerances={'shape_l2': {'pass': 0.1, 'warn': 0.2, 'basis': BASIS}})
    lines = rm.summary_lines(out)
    assert any('normalisation' in l.lower() or 'normalization' in l.lower() for l in lines)
    from ravel.plotting.figure_io import natural_label
    for line in lines:
        natural_label(line)
