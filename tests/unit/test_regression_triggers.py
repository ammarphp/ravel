"""Computed fit and scan alarms: one test per trigger, each with a clean twin."""
import copy

import numpy as np
import pytest

from ravel.validation import regression_triggers as rt


def record(*results, grid=None, diagnostics=None, review=None):
    doc = {'schema_version': 1, 'kind': 'inference', 'mode': 'test', 'status': 'passed',
           'results': list(results), 'grid': grid, 'diagnostics': diagnostics or {}}
    if review is not None:
        doc['review'] = review
    return doc


def statuses(doc, trigger):
    return [c['status'] for c in rt.evaluate(doc) if c['trigger'] == trigger]


def morph(chi2, ndf=3):
    return {'quantity': 'morph-coefficients', 'role': 'primary', 'ndf': ndf, 'chi2': chi2}


def test_closure_chi2_ndf_bounds():
    assert statuses(record(morph([3.0])), 'closure') == ['pass']
    assert statuses(record(morph([12.0])), 'closure') == ['fail']
    assert statuses(record(morph([0.1])), 'closure') == ['warn']


def test_closure_pull_above_five_fails():
    ok = {'quantity': 'morph-closure', 'role': 'primary', 'checks': [{'id': 'h', 'pulls': [0.5], 'passed': True}]}
    bad = copy.deepcopy(ok); bad['checks'][0]['pulls'] = [5.5]
    assert statuses(record(ok), 'closure') == ['pass']
    assert statuses(record(bad), 'closure') == ['fail']


def fitted(values, *, pulls=None, status='converged'):
    params = []
    for k, v in enumerate(values):
        row = {'name': f'p{k}', 'value': v, 'prefit': {'constrained': pulls is not None, 'nominal': 1.0, 'width': 1.0}}
        if pulls is not None:
            row['pull'] = pulls[k]
        params.append(row)
    out = {'quantity': 'fitted-parameters', 'role': 'diagnostic', 'parameters': params}
    if status is not None:
        out['status'] = status
    return out


def test_fit_triviality_zero_chi2_and_unmoved_fit():
    assert statuses(record(morph([0.0])), 'fit-triviality') == ['fail']
    assert statuses(record(fitted([1.0, 1.0])), 'fit-triviality') == ['fail']
    assert statuses(record(fitted([1.1, 0.9])), 'fit-triviality') == ['pass']
    # Expected by construction for MC pseudo-data: recorded as a warning.
    assert statuses(record(fitted([1.0, 1.0]), diagnostics={'data_mode': 'mc-pseudo-data'}), 'fit-triviality') == ['warn']


def test_parameter_at_bound_consumes_engine_flags():
    flagged = {'quantity': 'cls-limit', 'role': 'primary', 'status': 'computed',
               'fit': {'parameters': [{'name': 'alpha', 'near_lower_bound': True, 'near_upper_bound': False}]}}
    clean = copy.deepcopy(flagged); clean['fit']['parameters'][0]['near_lower_bound'] = False
    assert statuses(record(flagged), 'parameter-at-bound') == ['warn']
    assert statuses(record(clean), 'parameter-at-bound') == []
    assert [c['status'] for c in rt.consume_flags({'at_boundary': True}) if c['trigger'] == 'parameter-at-bound'] == ['warn']


def test_nuisance_pull_size_and_rms():
    assert statuses(record(fitted([1.2, 0.8], pulls=[0.5, 3.5])), 'nuisance-pulls') == ['warn']
    assert statuses(record(fitted([1.2, 0.8], pulls=[0.5, -1.0])), 'nuisance-pulls') == ['pass']
    small = [0.1, -0.2, 0.1, 0.05, -0.1]
    assert statuses(record(fitted([1.1] * 5, pulls=small)), 'nuisance-pulls') == ['pass', 'warn']
    normal = [1.0, -0.8, 0.9, -1.1, 0.7]
    assert statuses(record(fitted([1.1] * 5, pulls=normal)), 'nuisance-pulls') == ['pass', 'pass']


def selfcheck(modifiers, shape=True):
    return {'quantity': 'systematics', 'role': 'diagnostic',
            'selfcheck': rt.systematics_selfcheck(modifiers, shape_measurement=shape)}


NOMINAL = [10.0, 20.0, 30.0]


def test_zero_impact_and_identical_systematics_fail():
    good = [{'name': 'a', 'kind': 'histosys', 'nominal': NOMINAL, 'up': [11, 21, 33], 'down': [9, 19, 27]},
            {'name': 'b', 'kind': 'normsys', 'nominal': NOMINAL, 'up': [10.5, 21, 31.5], 'down': [9.5, 19, 28.5]}]
    assert statuses(record(selfcheck(good)), 'systematic-selfcheck') == ['pass', 'pass']
    noop = good + [{'name': 'c', 'kind': 'histosys', 'nominal': NOMINAL, 'up': NOMINAL, 'down': NOMINAL}]
    assert statuses(record(selfcheck(noop)), 'systematic-selfcheck') == ['pass', 'pass', 'fail']
    twin = good + [{**good[0], 'name': 'a-copy'}]
    assert statuses(record(selfcheck(twin)), 'systematic-selfcheck') == ['fail', 'pass', 'fail']


def test_dominant_source_and_flat_shape_shift_warn():
    balanced = [{'name': 'a', 'kind': 'histosys', 'nominal': NOMINAL, 'up': [11, 21, 33], 'down': [9, 19, 27]},
                {'name': 'b', 'kind': 'histosys', 'nominal': NOMINAL, 'up': [11.5, 20, 32], 'down': [8.5, 20, 28]}]
    assert statuses(record(selfcheck(balanced)), 'systematic-dominance') == ['pass']
    dominant = [balanced[0], {**balanced[1], 'up': [10.01, 20, 30.01], 'down': [9.99, 20, 29.99]}]
    assert statuses(record(selfcheck(dominant)), 'systematic-dominance') == ['warn']
    flat = [balanced[0], {'name': 'f', 'kind': 'histosys', 'nominal': NOMINAL, 'up': [11, 22, 33], 'down': [9, 18, 27]}]
    assert 'warn' in statuses(record(selfcheck(flat)), 'systematic-dominance')
    assert statuses(record(selfcheck(flat, shape=False)), 'systematic-dominance') == ['pass']


def test_reference_deviation_needs_a_declared_reference():
    limit = {'quantity': 'cls-limit', 'role': 'primary', 'status': 'computed', 'parameter_limit': {'observed': 1.0}}
    ref = {'label': 'published limit', 'path': 'results[0].parameter_limit.observed', 'value': 1.2, 'source': 'HEPData table 3'}
    assert statuses(record(limit, review={'references': [ref]}), 'reference-deviation') == ['pass']
    far = {**ref, 'value': 2.0}
    assert statuses(record(limit, review={'references': [far]}), 'reference-deviation') == ['fail']


def gof(p, auxiliary='refit', method='toys', observed=5.0):
    return {'quantity': 'goodness-of-fit', 'role': 'diagnostic', 'p_value': p, 'auxiliary': auxiliary,
            'method': method, 'observed': observed, 'asymptotic': {'ndf': 4}}


def test_goodness_of_fit_band_fixed_auxiliary_and_asymptotic_label():
    assert statuses(record(gof(0.4)), 'goodness-of-fit') == ['pass']
    assert statuses(record(gof(0.01)), 'goodness-of-fit') == ['fail']
    assert statuses(record(gof(0.4, auxiliary='fixed')), 'goodness-of-fit') == ['fail']
    fallback = [c for c in rt.evaluate(record(gof(0.4, method='asymptotic'))) if c['trigger'] == 'goodness-of-fit']
    assert fallback[0]['status'] == 'pass' and 'asymptotic' in fallback[0]['detail']


def test_excluded_bins():
    assert statuses(record({'quantity': 'post-fit-predictions', 'role': 'diagnostic', 'bins_total': 10,
                            'bins_excluded': 6}), 'excluded-bins') == ['fail']
    assert statuses(record({'quantity': 'post-fit-predictions', 'role': 'diagnostic', 'bins_total': 10,
                            'bins_excluded': 5}), 'excluded-bins') == ['pass']


def region(high, best=0.5, at_edge=False, status='resolved'):
    return {'quantity': 'delta-nll-region', 'role': 'primary', 'parameter': 'g', 'status': status,
            'scan_range': [0.0, 2.0], 'intervals': [{'low': {'status': 'domain_boundary', 'value': 0.0}, 'high': high}],
            'best_fit': {'g': best, 'twice_nll': 0.0, 'at_scan_edge': at_edge}}


SCAN = {'kind': 'scan', 'values': [0.0, 1.0, 2.0], 'domain': [0.0, None]}


def test_interval_and_best_fit_open_at_edge_with_proposed_extension():
    clean = record(region({'status': 'resolved', 'value': 1.2}), grid=SCAN)
    assert statuses(clean, 'open-at-edge') == ['pass']
    open_high = record(region({'status': 'beyond_scan', 'value': None, 'scan_edge': 2.0}), grid=SCAN)
    alarm = [c for c in rt.evaluate(open_high) if c['trigger'] == 'open-at-edge' and c['status'] == 'fail']
    assert alarm and alarm[0]['proposed_extension'] == {'parameter': 'g', 'side': 'high', 'current': 2.0, 'proposed': 3.0}
    at_high_edge = record(region({'status': 'resolved', 'value': 1.2}, best=2.0, at_edge=True), grid=SCAN)
    assert 'fail' in statuses(at_high_edge, 'open-at-edge')
    # A best fit at the physical boundary g = 0 is a parameter at its bound, not an open scan.
    at_zero = record(region({'status': 'resolved', 'value': 1.2}, best=0.0, at_edge=True), grid=SCAN)
    assert statuses(at_zero, 'open-at-edge') == [] and statuses(at_zero, 'parameter-at-bound') == ['warn']


def test_limit_censored_at_the_scan_ceiling_is_open_at_edge():
    capped = {'quantity': 'cls-limit', 'role': 'primary', 'status': 'computed',
              'flags': {'median_at_cap': True, 'at_mu_floor': False, 'band_degenerate': False}}
    assert statuses(record(capped), 'open-at-edge') == ['fail']
    capped['flags']['median_at_cap'] = False
    assert statuses(record(capped), 'open-at-edge') == []


def contour(points, **extra):
    return {'quantity': 'contour', 'role': 'primary', 'x': 'm', 'y': 'g', **extra,
            'series': [{'id': 's', 'records': [{'x': x, 'y': y} for x, y in points]}]}


GRID2 = {'kind': 'product', 'axes': [{'name': 'm', 'values': [100.0, 200.0, 300.0]},
                                     {'name': 'g', 'values': [0.1, 0.5, 1.0]}]}


def test_contour_touching_the_evaluated_hull_is_open_at_edge():
    inside = record(contour([(150.0, 0.3), (250.0, 0.7)]), grid=GRID2)
    assert statuses(inside, 'open-at-edge') == ['pass']
    touching = record(contour([(150.0, 0.3), (300.0, 0.7)]), grid=GRID2)
    alarm = [c for c in rt.evaluate(touching) if c['trigger'] == 'open-at-edge'][0]
    assert alarm['status'] == 'fail'
    proposal = alarm['proposed_extension'][0]
    assert proposal['axis'] == 'm' and proposal['side'] == 'high' and proposal['proposed'] == pytest.approx(400.0)
    # A level line of a declared formula is geometry, not a statistical claim.
    formula_line = record(contour([(150.0, 0.3), (300.0, 0.7)], output='width', level=10.0), grid=GRID2)
    assert statuses(formula_line, 'open-at-edge') == ['warn']


def test_fit_without_a_validity_status_fails():
    assert 'fail' in statuses(record(fitted([1.1], status=None)), 'validity-status')
    assert statuses(record(fitted([1.1])), 'validity-status') == ['pass']
    assert statuses(record(fitted([1.1], status='not_converged')), 'validity-status') == ['fail']


def test_threshold_overrides_need_a_recorded_basis():
    with pytest.raises(ValueError, match='basis'):
        rt.thresholds({'closure_chi2_ndf_high': {'value': 5.0}})
    doc = record(morph([18.0]), review={'thresholds': {'closure_chi2_ndf_high': {'value': 5.0, 'basis': 'paper uses 5'}}})
    alarm = [c for c in rt.evaluate(doc) if c['trigger'] == 'closure'][0]
    assert alarm['status'] == 'fail' and alarm['threshold']['origin'] == 'override'
    doc['review']['thresholds']['closure_chi2_ndf_high']['value'] = 10.0
    assert statuses(doc, 'closure') == ['pass']


def test_removing_any_trigger_condition_is_detected():
    # Every trigger fires on at least one fixture above; this guards the catalogue itself.
    fired = set()
    fixtures = [record({'quantity': 'mc-adequacy', 'flags': [{'flags': ['nonpositive_total_background']}]}),
                record(morph([12.0])), record(morph([0.0])), record(fitted([1.2], pulls=[4.0])),
                record(gof(0.01)), record(region({'status': 'beyond_scan', 'value': None, 'scan_edge': 2.0}), grid=SCAN),
                record(fitted([1.1], status=None)),
                record({'quantity': 'post-fit-predictions', 'role': 'diagnostic', 'bins_total': 4, 'bins_excluded': 3}),
                record(selfcheck([{'name': 'c', 'kind': 'histosys', 'nominal': NOMINAL, 'up': NOMINAL, 'down': NOMINAL},
                                  {'name': 'f', 'kind': 'histosys', 'nominal': NOMINAL, 'up': [11, 22, 33], 'down': [9, 18, 27]}])),
                record({'quantity': 'cls-limit', 'role': 'primary', 'status': 'computed', 'flags': {'near_lower_bound': True},
                        'parameter_limit': {'observed': 1.0}},
                       review={'references': [{'label': 'x', 'path': 'results[0].parameter_limit.observed',
                                               'value': 3.0, 'source': 's'}]})]
    for doc in fixtures:
        fired |= {c['trigger'] for c in rt.evaluate(doc) if c['status'] != 'pass'}
    assert fired == set(rt.TRIGGERS)
