"""Goodness of fit, systematics self-check and computed checks carried by inference.json."""
import copy
import json

import numpy as np
import pytest

from ravel.physics.inference import counting, gof, prescribed_statistic, record, search_statistics
from ravel.physics.inference.cli import example
from test_inference_modes import binned_doc, formula_doc, save


def test_without_toys_the_asymptotic_fallback_is_labelled():
    result = gof.evaluate(3.0, ndf=3, statistic='q', request=None)
    assert result['method'] == 'asymptotic' and result['asymptotic_reason'] == 'no toys requested'
    assert result['p_value'] == pytest.approx(0.3916, abs=1e-3)
    assert result['auxiliary'] == 'refit' and 'fallback' in result['summary']


def test_toy_budget_and_conservative_p_value():
    draws = iter([1.0, 2.0, 3.0, 4.0])
    result = gof.evaluate(2.5, ndf=1, statistic='q', request={'toys': 4, 'seed': 1},
                          toy=lambda rng: next(draws))
    assert result['method'] == 'toys' and result['toys_completed'] == 4
    assert result['p_value'] == pytest.approx((2 + 1) / (4 + 1))
    assert result['toy_band_95'][0] <= result['toy_median'] <= result['toy_band_95'][1]
    with pytest.raises(ValueError, match='toys'):
        gof.options({'toys': -1})


def channels(observed):
    return [counting.Channel('c', observed, [20.0, 30.0, 25.0, 15.0], [2.0, 3.0, 2.5, 1.5])]


def likelihood(observed):
    signal = counting.Signal.linear('mu', {'c': [2.0, 3.0, 2.0, 1.0]})
    return counting.Likelihood(channels(observed), signal)


def toy_gof(observed, toys=200):
    grid = np.linspace(0.0, 10.0, 101)
    model = likelihood(observed)
    scan = counting.scan_1d(model, 'mu', grid, domain=(0.0, None))
    best = {'mu': scan['best_fit']['mu']}
    return gof.evaluate(scan['best_fit']['twice_nll'], ndf=3, statistic='q', request={'toys': toys, 'seed': 7},
                        toy=gof.counting_toy(model, 'mu', grid, (0.0, None), best))


def test_saturated_toy_goodness_of_fit_separates_good_and_bad_models():
    good = toy_gof([22.0, 33.0, 26.0, 16.0])
    assert good['method'] == 'toys' and good['toys_completed'] >= 190 and good['p_value'] > 0.2
    bad = toy_gof([60.0, 5.0, 70.0, 2.0])
    assert bad['p_value'] < 0.05
    # The toys refit the auxiliary measurement too: the toy median is near ndf (3), not near zero.
    assert 1.0 < good['toy_median'] < 6.0


def test_binned_prescribed_statistic_reports_goodness_of_fit_with_toys(tmp_path):
    doc = binned_doc(tmp_path, goodness_of_fit={'toys': 30, 'seed': 3})
    prescribed_statistic.run({'input': str(doc)}, tmp_path, tmp_path / 'out')
    inference = json.loads((tmp_path / 'out/inference.json').read_text())
    rows = [r for r in inference['results'] if r['quantity'] == 'goodness-of-fit']
    assert rows and rows[0]['method'] == 'toys' and rows[0]['toys_completed'] + rows[0]['toys_failed'] == 30
    assert any(c['trigger'] == 'goodness-of-fit' for c in inference['computed_checks'])


def test_closed_form_statistic_refuses_a_goodness_of_fit_request(tmp_path):
    base = json.loads(formula_doc(tmp_path).read_text())
    path = save(tmp_path / 'closed.json', {
        'schema_version': 1, 'kind': 'prescribed-statistic',
        'statistic': {'kind': 'closed-form', 'verbatim': 'Sig = 2 contour'},
        'grid': base['grid'], 'program': base['program'], 'statistic_output': 'Sig', 'threshold': 2.0,
        'region': 'at-or-above', 'goodness_of_fit': {'toys': 10}})
    with pytest.raises(ValueError, match='goodness_of_fit'):
        prescribed_statistic.load({'input': str(path)}, tmp_path)


def search_document(**changes):
    doc = copy.deepcopy(example('search-statistics'))
    doc['regions'] = [{'name': 'SR', 'role': 'SR', 'observed': None},
                      {'name': 'CRtop', 'role': 'CR', 'observed': [131.0, 92.0]},
                      {'name': 'CRw', 'role': 'CR', 'observed': [166.0]},
                      {'name': 'VR', 'role': 'VR', 'observed': [72.0]}]
    for bkg, split in zip(doc['backgrounds'], ([120.0, 80.0], [12.0, 8.0])):
        bkg['yields']['CRtop'] = {'values': split, 'sumw2': [x / 10 for x in split]}
    point = doc['signal_points'][0]
    point['yields']['CRtop'] = {'values': [0.3, 0.2], 'sumw2': [0.01, 0.01]}
    doc['data'] = {'mode': 'observed', 'injections': {}}
    doc['statistic'] = {'origin': 'default'}
    doc['computations']['allow_blinded_signal_regions'] = True
    doc.update(changes)
    return doc


def test_search_background_fit_carries_toy_goodness_of_fit_and_systematics_selfcheck(tmp_path):
    doc = search_document(goodness_of_fit={'toys': 12, 'seed': 5})
    sources = doc['systematics']['sources']
    sources.append({**sources[0], 'name': 'luminosity_copy'})
    path = save(tmp_path / 'search.json', doc)
    result = search_statistics.run({'input': str(path)}, tmp_path, tmp_path / 'out')
    inference = json.loads((tmp_path / 'out/inference.json').read_text())
    fit_gof = next(r for r in inference['results'] if r['quantity'] == 'goodness-of-fit')
    assert fit_gof['method'] == 'toys' and fit_gof['auxiliary'] == 'refit' and fit_gof['asymptotic']['ndf'] == 1
    assert 0 < fit_gof['p_value'] <= 1
    selfcheck = json.loads((tmp_path / 'out/systematics_selfcheck.json').read_text())
    assert [m['identical_to'] for m in selfcheck['modifiers']] == [['luminosity_copy'], ['luminosity']]
    failures = inference['computed_check_summary']['failures']
    assert any(f.startswith('systematic-selfcheck@') for f in failures)
    assert result['computed_checks']['fail'] >= 2


def test_inference_record_refuses_a_hand_written_computed_check():
    doc = {'schema_version': 1, 'kind': 'inference', 'status': 'passed', 'physics_validated': False,
           'statistic': {'origin': 'not-applicable'}, 'results': [],
           'computed_checks': [{'trigger': 'closure', 'status': 'ok'}]}
    with pytest.raises(ValueError, match='computed checks'):
        record.validate(doc)


def test_review_thresholds_and_references_are_recorded(tmp_path):
    doc = binned_doc(tmp_path, review={
        'thresholds': {'gof_p_value_min': {'value': 0.01, 'basis': 'the requester tests at 1%'}},
        'references': [{'label': 'published best fit', 'path': 'results[2].best_fit.g', 'value': 0.5,
                        'source': 'synthetic reference'}]})
    prescribed_statistic.run({'input': str(doc)}, tmp_path, tmp_path / 'out')
    inference = json.loads((tmp_path / 'out/inference.json').read_text())
    assert inference['review']['thresholds']['gof_p_value_min']['basis'] == 'the requester tests at 1%'
    ref = next(c for c in inference['computed_checks'] if c['trigger'] == 'reference-deviation')
    assert ref['status'] in ('pass', 'fail') and 'synthetic reference' in ref['detail']
    with pytest.raises(ValueError, match='basis'):
        prescribed_statistic.load({'input': str(binned_doc(tmp_path, review={
            'thresholds': {'gof_p_value_min': {'value': 0.01}}}))}, tmp_path)


def test_differential_likelihood_reports_a_labelled_asymptotic_chi_square(tmp_path):
    from ravel.physics.inference import differential_likelihood
    path = save(tmp_path / 'diff.json', example('differential-likelihood'))
    differential_likelihood.run({'input': str(path)}, tmp_path, tmp_path / 'out')
    inference = json.loads((tmp_path / 'out/inference.json').read_text())
    row = next(r for r in inference['results'] if r['quantity'] == 'goodness-of-fit')
    bins = len(inference['diagnostics']['bin_edges']) - 1
    assert row['method'] == 'asymptotic' and row['asymptotic']['ndf'] == bins - 1
    assert 'Gaussian likelihood' in row['asymptotic']['meaning'] and row['observed'] >= 0
