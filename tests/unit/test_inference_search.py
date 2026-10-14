"""pyhf search statistics: SR/CR/VR model building, Z0, CLs, background-only fits, MC adequacy."""
import math

import numpy as np
import pytest

from ravel.physics.inference import search


def cowan_z(s, b, sigma):
    term1 = (s + b) * math.log((s + b) * (b + sigma ** 2) / (b ** 2 + (s + b) * sigma ** 2))
    term2 = b ** 2 / sigma ** 2 * math.log(1 + sigma ** 2 * s / (b * (b + sigma ** 2)))
    return math.sqrt(2 * (term1 - term2))


def single_bin(s, b, sigma, **extra):
    doc = {'regions': [{'name': 'SR', 'role': 'SR', 'observed': None}],
           'backgrounds': [{'name': 'bkg', 'normfactor': None, 'yields': {'SR': {'values': [b], 'sumw2': [sigma ** 2]}}}],
           'signal_points': [{'id': 'p', 'coordinates': {}, 'yields': {'SR': {'values': [s], 'sumw2': [0.0]}}}],
           'mc_statistics': 'shapesys', 'systematics': None,
           'data': {'mode': 'mc-pseudo-data', 'injections': {}},
           'computations': {'discovery': True, 'cls_at_nominal': False, 'cls_limits': False,
                            'background_only_fit': False},
           'asimov_source': 'nominal', 'cls_level': 0.05,
           'mc_adequacy': {'max_relative_uncertainty': 0.5, 'min_effective_entries': 1}, 'contours': None}
    doc.update(extra)
    return doc


@pytest.mark.parametrize('s,b,sigma', [(5.0, 10.0, 2.0), (3.0, 4.0, 1.0)])
def test_single_bin_expected_discovery_matches_cowan(s, b, sigma):
    result = search.run(single_bin(s, b, sigma))
    z = result['points'][0]['discovery']['expected_significance']
    assert z == pytest.approx(cowan_z(s, b, sigma), rel=2e-4)


def control_fixture(mode='mc-pseudo-data', injections=None):
    return {'regions': [{'name': 'SR', 'role': 'SR', 'observed': None},
                        {'name': 'CRtop', 'role': 'CR', 'observed': None},
                        {'name': 'CRw', 'role': 'CR', 'observed': None},
                        {'name': 'VR', 'role': 'VR', 'observed': None}],
            'backgrounds': [
                {'name': 'top', 'normfactor': 'mu_top', 'yields': {
                    'SR': {'values': [10.0, 4.0], 'sumw2': [1.0, 0.5]}, 'CRtop': {'values': [200.0], 'sumw2': [20.0]},
                    'CRw': {'values': [15.0], 'sumw2': [2.0]}, 'VR': {'values': [40.0], 'sumw2': [4.0]}}},
                {'name': 'wjets', 'normfactor': 'mu_w', 'yields': {
                    'SR': {'values': [6.0, 2.0], 'sumw2': [0.8, 0.3]}, 'CRtop': {'values': [20.0], 'sumw2': [3.0]},
                    'CRw': {'values': [150.0], 'sumw2': [15.0]}, 'VR': {'values': [30.0], 'sumw2': [3.0]}}}],
            'signal_points': [{'id': 'a', 'coordinates': {'m': 1.0}, 'yields': {
                'SR': {'values': [6.0, 5.0], 'sumw2': [0.2, 0.2]}, 'CRtop': {'values': [0.5], 'sumw2': [0.01]},
                'CRw': {'values': [0.2], 'sumw2': [0.01]}, 'VR': {'values': [1.0], 'sumw2': [0.05]}}}],
            'mc_statistics': 'staterror', 'systematics': None,
            'data': {'mode': mode, 'injections': injections or {}},
            'computations': {'discovery': True, 'cls_at_nominal': True, 'cls_limits': True, 'background_only_fit': True},
            'asimov_source': 'background-only-fit', 'cls_level': 0.05,
            'mc_adequacy': {'max_relative_uncertainty': 0.3, 'min_effective_entries': 10}, 'contours': None}


def test_normalisation_factor_closure_on_injected_pseudo_data():
    result = search.run(control_fixture(injections={'top': 1.3, 'wjets': 0.8}))
    fit = result['background_only_fit']
    assert fit['status'] == 'converged'
    values = {p['name']: p['value'] for p in fit['parameters']}
    assert values['mu_top'] == pytest.approx(1.3, abs=1e-3) and values['mu_w'] == pytest.approx(0.8, abs=1e-3)
    vr = next(r for r in fit['region_predictions'] if r['region'] == 'VR')
    assert vr['used_in_fit'] is False and vr['residuals'][0] == pytest.approx(0.0, abs=1e-3)
    assert fit['correlation'][0][0] == pytest.approx(1.0)
    assert set(fit['fit_channels']) == {'CRtop', 'CRw'}


def test_validation_regions_never_enter_the_fit_model():
    model = search.SearchModel(control_fixture())
    spec = model.workspace(model.points[0], roles=('SR', 'CR'))
    assert {c['name'] for c in spec['channels']} == {'SR', 'CRtop', 'CRw'}
    mods = {m['name'] for c in spec['channels'] for s in c['samples'] for m in s['modifiers']}
    assert {'mu', 'mu_top', 'mu_w'} <= mods


def test_cls_limits_and_expected_bands_are_reported():
    result = search.run(control_fixture())
    point = result['points'][0]
    assert point['cls_limits']['expected']['status'][2] == 'resolved'
    assert 0 < point['cls_limits']['expected']['values'][2] < 10
    assert point['cls_limits']['observed'] is None  # signal region blinded
    band = point['cls_at_nominal']['expected']
    assert len(band) == 5 and band == sorted(band)  # pyhf order: -2 sigma (smallest CLs) first


def test_cls_limit_agrees_with_the_counting_regression_model():
    from ravel.physics import pyhf_exclude
    doc = single_bin(4.0, 6.0, 1.5, regions=[{'name': 'SR', 'role': 'SR', 'observed': [8.0]}],
                     data={'mode': 'observed', 'injections': {}},
                     computations={'discovery': False, 'cls_at_nominal': False, 'cls_limits': True,
                                   'background_only_fit': False})
    ours = search.run(doc)['points'][0]['cls_limits']
    model, data = pyhf_exclude.model_from_counting({'name': 'SR', 'n': 8, 'b': 6.0, 'db': 1.5, 's': 4.0})
    ref = pyhf_exclude.compute(model, data)
    assert ours['observed']['value'] == pytest.approx(ref['obs_limit'], rel=1e-3)


def test_mc_statistics_adequacy_flags():
    doc = control_fixture()
    doc['backgrounds'][0]['yields']['SR'] = {'values': [10.0, 4.0], 'sumw2': [1.0, 9.0]}
    flags = search.SearchModel(doc).mc_adequacy()
    hit = [f for f in flags if f['sample'] == 'top' and f['region'] == 'SR' and f['bin'] == 1]
    assert hit and {'relative_mc_uncertainty', 'effective_entries'} <= set(hit[0]['flags'])


def test_blinded_signal_region_cannot_use_observed_mode():
    doc = control_fixture(mode='observed')
    for region, counts in (('CRtop', [221.0]), ('CRw', [168.0]), ('VR', [70.0])):
        next(r for r in doc['regions'] if r['name'] == region)['observed'] = counts
    with pytest.raises(ValueError, match='blinded'):
        search.SearchModel(doc)
    doc['computations']['allow_blinded_signal_regions'] = True
    assert search.SearchModel(doc).blinded == ['SR']
    doc['regions'][1]['observed'] = None
    with pytest.raises(ValueError, match='control region'):
        search.SearchModel(doc)


def test_systematics_registry_enters_the_workspace():
    doc = control_fixture()
    doc['systematics'] = {'schema_version': 1, 'absent': [], 'sources': [
        {'name': 'lumi', 'kind': 'normsys', 'relative': 0.02, 'applies_to': {'samples': 'all', 'regions': 'all'},
         'correlation': 'correlated', 'origin': 'cited', 'citation': 'luminosity note'}]}
    model = search.SearchModel(doc)
    spec = model.workspace(model.points[0], roles=('SR', 'CR'))
    lumi = [m for c in spec['channels'] for s in c['samples'] for m in s['modifiers'] if m['name'] == 'lumi']
    assert len(lumi) == 3 * 3 and all(m['data'] == {'hi': 1.02, 'lo': 0.98} for m in lumi)
