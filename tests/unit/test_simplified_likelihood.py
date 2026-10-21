"""Synthetic controls for supplied background covariance inference."""
from copy import deepcopy
import hashlib
import json
import math
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.optimize import minimize_scalar
from scipy.special import xlogy
from scipy.stats import norm

from ravel.limits import read_limits
from ravel.physics.inference import simplified


def single_model(n=20, s=5):
    return simplified.SimplifiedLikelihood(
        None if n is None else [n], [20], [s], ['SR'], covariance=[[4]])


def covariance_document():
    return {'schema_version': 1, 'kind': 'background-covariance',
            'regions': ['SR'], 'covariance': [[4]],
            'source': 'synthetic supplied covariance'}


def sr_inputs():
    return [{'name': 'SR', 'n': 20, 'b': 20, 'db': 2, 's': 5}]


def independent_cls(mu, n, b=20, db=2, s=5):
    # NLL(mu,t;n) = lambda - xlogy(n,lambda) + t**2/(2*db**2),
    # lambda=mu*s+b+t, t>=-b; nominal auxiliary observation is zero.
    # qtilde is one-sided about muhat=max((n-b)/s,0). Observed-mode
    # reference counts are conditional: nA=b+t_hat(0;n), with the auxiliary
    # constraint still fixed at zero. Expected-mode reference counts are b.
    # With qA=qtilde(mu;nA), sigmaA=mu/sqrt(qA), delta=sqrt(q)-sqrt(qA) for q<=qA,
    # otherwise delta=(q-qA)/(2*sqrt(qA)); CLs=sf(sqrt(qA)+delta)/sf(delta).
    # Expected shifts [2,1,0,-1,-2] give sf(sqrt(qA)+shift)/sf(shift)
    # in the recorded [-2,-1,median,+1,+2] order.
    def profile(poi, count):
        def objective(t):
            rate = poi * s + b + t
            return rate - xlogy(count, rate) + t * t / (2 * db * db)
        fit = minimize_scalar(objective, method='bounded',
                              bounds=(-b, max(100, 10 * (count + b + poi * s))),
                              options={'xatol': 1e-12})
        assert fit.success
        return fit

    def statistic(count):
        muhat = max((count - b) / s, 0)
        return 0 if muhat > mu else max(
            2 * (profile(mu, count).fun - profile(muhat, count).fun), 0)

    q = statistic(n)
    qa = statistic(b + profile(0, n).x)
    sigma_a = mu / math.sqrt(qa)
    root_a = mu / sigma_a
    delta = math.sqrt(q) - root_a if q <= qa else (q - qa) / (2 * root_a)
    observed = norm.sf(root_a + delta) / norm.sf(delta)
    root_expected = math.sqrt(statistic(b))
    expected = [norm.sf(root_expected + z) / norm.sf(z) for z in (2, 1, 0, -1, -2)]
    return observed, expected


@pytest.mark.parametrize('n', [20, 24, 16])
@pytest.mark.parametrize('mu', [0.5, 1.0, 2.0])
def test_single_bin_matches_independent_profile_oracle(n, mu):
    expected_obs, expected_band = independent_cls(mu, n)
    engine = single_model(n)
    assert engine.cls(mu, 'observed') == pytest.approx([expected_obs], abs=1e-3)
    band = engine.cls(mu, 'apriori')
    assert band == pytest.approx(expected_band, abs=1e-3)
    assert band == sorted(band)


def test_raw_confidence_complements_preserve_expected_order(monkeypatch):
    confidence = [0.99, 0.9, 0.75, 0.5, 0.1]
    calls = []

    def exclusion_confidence_level(**kwargs):
        calls.append(kwargs)
        return confidence

    monkeypatch.setattr(simplified, '_spey', lambda: SimpleNamespace(
        ExpectationType=SimpleNamespace(apriori='expected')))
    engine = single_model()
    monkeypatch.setattr(engine, 'backend', lambda: SimpleNamespace(
        exclusion_confidence_level=exclusion_confidence_level))
    assert engine.cls(1, 'apriori') == [1 - value for value in confidence]
    assert calls[0]['expected'] == 'expected'
    assert simplified.EXPECTED_ORDER == ['-2 sigma', '-1 sigma', 'median', '+1 sigma', '+2 sigma']


@pytest.fixture(scope='module')
def diagonal_controls():
    diagonal = simplified.SimplifiedLikelihood([20, 15], [20, 15], [5, 4],
        ['SR0', 'SR1'], covariance=[[4, 0], [0, 9]])
    independent = simplified.combine([
        simplified.SimplifiedLikelihood([20], [20], [5], ['SR0'], covariance=[[4]]),
        simplified.SimplifiedLikelihood([15], [15], [4], ['SR1'], covariance=[[9]])])
    return diagonal, independent


def test_independent_combination_matches_diagonal_covariance(diagonal_controls):
    diagonal, independent = diagonal_controls
    for expectation in ('observed', 'apriori'):
        assert independent.cls(1, expectation) == pytest.approx(diagonal.cls(1, expectation), abs=1e-6)
    left, right = independent.limits(), diagonal.limits()
    assert left['obs_limit'] == pytest.approx(right['obs_limit'], abs=1e-6)
    assert left['exp_limits'] == pytest.approx(right['exp_limits'], abs=1e-6)
    assert all(c.status == 'resolved' for c in [read_limits(left).observed, *read_limits(left).expected])


def test_positive_covariance_changes_resolved_limit(diagonal_controls):
    diagonal, _ = diagonal_controls
    correlated = simplified.SimplifiedLikelihood([20, 15], [20, 15], [5, 4],
        ['SR0', 'SR1'], covariance=[[4, 2], [2, 9]])
    result = correlated.limits()
    assert np.isfinite([result['obs_limit'], *result['exp_limits']]).all()
    assert read_limits(result).observed.status == 'resolved'
    assert abs(result['obs_limit'] - diagonal.limits()['obs_limit']) > 1e-4


@pytest.mark.parametrize('kwargs,match', [
    ({'covariance': [[0]]}, 'positive definite'),
    ({'correlation': [[0.5]], 'errors': [2]}, 'unit diagonal'),
    ({'covariance': [[4]], 'third_moments': [0, 0]}, 'same length'),
])
def test_invalid_model_inputs_are_refused(kwargs, match):
    with pytest.raises(ValueError, match=match):
        simplified.SimplifiedLikelihood([20], [20], [5], ['SR'], **kwargs)


@pytest.mark.parametrize('change,match', [
    ({'regions': ['other']}, 'region set'),
    ({'source': ''}, 'source'),
    ({'blocks': [['SR'], ['SR']]}, 'partition'),
    ({'blocks': [[]]}, 'unique nonblank'),
    ({'blocks': ['SR']}, 'unique nonblank'),
])
def test_invalid_covariance_documents_are_refused(change, match):
    document = covariance_document()
    document.update(change)
    with pytest.raises(ValueError, match=match):
        simplified.from_document(document, sr_inputs())


def test_covariance_document_requires_source_key():
    document = covariance_document()
    del document['source']
    with pytest.raises(ValueError, match='source'):
        simplified.from_document(document, sr_inputs())


def test_document_correlation_uses_yield_errors_in_document_order():
    rows = [dict(sr_inputs()[0], name='SR0', db=2),
            dict(sr_inputs()[0], name='SR1', db=3)]
    document = {'schema_version': 1, 'kind': 'background-covariance',
                'regions': ['SR1', 'SR0'], 'correlation': [[1, 0.5], [0.5, 1]],
                'source': 'synthetic supplied correlation'}
    engine = simplified.from_document(document, rows)
    np.testing.assert_array_equal(engine.covariance, [[9, 3], [3, 4]])


def test_document_combines_declared_independent_blocks():
    document = covariance_document()
    document.update(regions=['SR0', 'SR1'], covariance=[[4, 0], [0, 9]], blocks=[['SR1'], ['SR0']])
    rows = [dict(sr_inputs()[0], name='SR0'), dict(sr_inputs()[0], name='SR1', b=15, n=15, db=3, s=4)]
    combined = simplified.from_document(document, rows)
    assert isinstance(combined.backend(), simplified._spey().UnCorrStatisticsCombiner)
    direct = simplified.SimplifiedLikelihood([20, 15], [20, 15], [5, 4],
                                             ['SR0', 'SR1'], covariance=[[4, 0], [0, 9]])
    assert combined.cls(1, 'apriori') == pytest.approx(direct.cls(1, 'apriori'), abs=1e-6)


def test_independent_partition_refuses_nonzero_cross_covariance():
    document = covariance_document()
    document.update(regions=['SR0', 'SR1'], covariance=[[4, 2], [2, 9]], blocks=[['SR0'], ['SR1']])
    rows = [dict(sr_inputs()[0], name='SR0'), dict(sr_inputs()[0], name='SR1')]
    with pytest.raises(ValueError, match='zero covariance between blocks'):
        simplified.from_document(document, rows)


def test_combination_refuses_overlapping_labels():
    with pytest.raises(ValueError, match='disjoint block labels'):
        simplified.combine([single_model(), single_model()])


def test_dependency_version_is_pinned(monkeypatch):
    import spey

    monkeypatch.setattr(spey, 'version', lambda: '0.0.0')
    with pytest.raises(RuntimeError, match='requires spey==0.2.6'):
        simplified._spey()


def test_indefinite_covariance_is_refused():
    with pytest.raises(ValueError, match='positive definite'):
        simplified.SimplifiedLikelihood([20, 15], [20, 15], [5, 4],
                                       ['SR0', 'SR1'], covariance=[[1, 2], [2, 1]])


def test_covariance_source_cannot_be_omitted():
    document = covariance_document()
    del document['source']
    with pytest.raises(ValueError, match='source'):
        simplified.from_document(document, sr_inputs())


def test_correlation_and_errors_convert_to_covariance():
    engine = simplified.SimplifiedLikelihood([20, 15], [20, 15], [5, 4],
        ['SR0', 'SR1'], correlation=[[1, 1 / 3], [1 / 3, 1]], errors=[2, 3])
    np.testing.assert_allclose(engine.covariance, [[4, 2], [2, 9]], rtol=0, atol=1e-12)


def test_zero_signal_reports_bounds_instead_of_resolved_limits():
    engine = single_model(s=0)
    assert engine.cls(2, 'observed') == [1.0]
    result = read_limits(engine.limits(poi_cap=2))
    for curve in [result.observed, *result.expected]:
        assert curve.status == 'above_scan'
        assert curve.value == 2


def test_expected_only_has_missing_observed_limit():
    engine = single_model(n=None)
    with pytest.raises(ValueError, match='requires observed data'):
        engine.cls(1, 'observed')
    result = read_limits(engine.limits())
    assert result.observed.status == 'missing'
    assert result.observed.value is None
    assert all(c.status == 'resolved' for c in result.expected)


def test_root_exactly_at_cap_is_above_scan(monkeypatch):
    engine = single_model()
    monkeypatch.setattr(engine, 'cls', lambda mu, expected:
                        [0.05 if mu == 1 else max(0.0, 1 - 0.95 * mu)]
                        * (1 if expected == 'observed' else 5))
    result = read_limits(engine.limits(poi_cap=1))
    assert all(c.status == 'above_scan' and c.value == 1
               for c in [result.observed, *result.expected])


def test_zero_third_moments_backend_is_finite():
    engine = simplified.SimplifiedLikelihood([20], [20], [5], ['SR'],
                                             covariance=[[4]], third_moments=[0])
    assert engine.backend_name == 'default.third_moment_expansion'
    assert np.isfinite(engine.cls(1, 'observed')).all()
    assert np.isfinite(engine.cls(1, 'apriori')).all()


def test_simplified_cli_writes_readable_limits_and_scaled_result(tmp_path, monkeypatch):
    from matplotlib.image import imread
    from ravel.physics import pyhf_exclude

    covariance = tmp_path / 'covariance.json'
    yields = tmp_path / 'yields.json'
    covariance.write_text(json.dumps(covariance_document()))
    yields.write_text(json.dumps(sr_inputs()))
    results = []
    for scale in (1, 2):
        output = tmp_path / f'output-{scale}'
        monkeypatch.setattr(sys, 'argv', ['pyhf_exclude', 'simplified', '--srs', str(yields),
            '--covariance', str(covariance), '--out', str(output), '--sigma-scale', str(scale)])
        pyhf_exclude.main()
        result = json.loads((output / 'exclusion.json').read_text())
        assert imread(output / 'exclusion.png').size > 0
        typed = read_limits(result)
        assert typed.observed.status == 'resolved'
        assert all(c.status == 'resolved' for c in typed.expected)
        for flag in ('at_mu_floor', 'at_poi_cap', 'median_at_cap', 'band_degenerate'):
            assert type(result[flag]) is bool
        for key in ('exp_limits', 'scan_mu', 'scan_cls_obs', 'scan_cls_exp'):
            assert np.isfinite(result[key]).all()
        assert len(result['scan_mu']) >= 11 and result['scan_mu'][0] == 0
        for values in np.asarray([result['scan_cls_obs'], *np.asarray(result['scan_cls_exp']).T]):
            assert np.all(np.diff(values) <= 1e-6)
        for evidence in [result['numerical_evidence']['observed'], *result['numerical_evidence']['expected']]:
            assert abs(evidence['residual']) < 5e-6
            assert evidence['cls_at_root'] == pytest.approx(0.05, abs=5e-6)
        provenance = result['execution_provenance']
        assert provenance['dependencies']['spey'] == '0.2.6'
        hashes = {entry['path']: entry['sha256'] for entry in provenance['inputs']}
        for path in (covariance, yields):
            assert hashes[str(path)] == hashlib.sha256(path.read_bytes()).hexdigest()
        results.append(result)
    assert results[1]['sigma_scale_k'] == 2
    assert results[1]['obs_limit'] == pytest.approx(results[0]['obs_limit'] / 2, rel=1e-9)
    assert results[1]['exp_limits'] == pytest.approx(np.array(results[0]['exp_limits']) / 2, rel=1e-9)
    for original, scaled in zip(results[0]['numerical_evidence']['expected'], results[1]['numerical_evidence']['expected']):
        assert scaled['bracket'] == pytest.approx(np.array(original['bracket']) / 2)


def search_document():
    return {'regions': [{'name': 'SR', 'role': 'SR', 'observed': [20]}],
        'backgrounds': [{'name': 'bkg', 'normfactor': None,
                         'yields': {'SR': {'values': [20], 'sumw2': [4]}}}],
        'signal_points': [{'id': 'p', 'coordinates': {},
                           'yields': {'SR': {'values': [5], 'sumw2': [0]}}}],
        'mc_statistics': 'none', 'systematics': None,
        'data': {'mode': 'observed', 'injections': {}},
        'computations': {'discovery': False, 'cls_at_nominal': True,
                         'cls_limits': True, 'background_only_fit': False},
        'asimov_source': 'nominal', 'cls_level': 0.05,
        'mc_adequacy': {'max_relative_uncertainty': 0.5, 'min_effective_entries': 1},
        'contours': None, 'background_covariance': {
            'regions': ['SR'], 'covariance': [[4]], 'source': 'synthetic supplied covariance'}}


def test_search_uses_supplied_covariance_engine():
    from ravel.physics.inference import search

    point = search.run(search_document())['points'][0]
    engine = single_model()
    nominal, limits = point['cls_at_nominal'], point['cls_limits']
    assert nominal['engine'] == limits['engine'] == 'spey-simplified-likelihood'
    assert nominal['observed'] == pytest.approx(engine.cls(1, 'observed')[0], abs=1e-6)
    assert nominal['expected'] == pytest.approx(engine.cls(1, 'apriori'), abs=1e-6)
    direct = engine.limits()
    assert limits['observed']['value'] == pytest.approx(direct['obs_limit'], abs=1e-6)
    assert limits['expected']['values'] == pytest.approx(direct['exp_limits'], abs=1e-6)


@pytest.mark.parametrize('role', ['CR', 'VR'])
def test_search_refuses_other_region_roles(role):
    from ravel.physics.inference import search

    document = search_document()
    document['regions'].append({'name': 'other', 'role': role, 'observed': [20]})
    for sample in document['backgrounds'] + document['signal_points']:
        sample['yields']['other'] = deepcopy(sample['yields']['SR'])
    with pytest.raises(ValueError, match='SR|control|validation'):
        search.run(document)


@pytest.mark.parametrize('change,match', [
    ({'systematics': {'schema_version': 1, 'absent': [], 'sources': []}}, 'systematics'),
    ({'mc_statistics': 'shapesys'}, 'signal MC statistics'),
    ({'asimov_source': 'background-only-fit'}, 'nominal'),
])
def test_search_refuses_unsupported_covariance_options(change, match):
    from ravel.physics.inference import search

    document = search_document()
    document.update(change)
    with pytest.raises(ValueError, match=match):
        search.run(document)


def test_search_refuses_discovery_with_supplied_covariance():
    from ravel.physics.inference import search

    document = search_document()
    document['computations']['discovery'] = True
    with pytest.raises(ValueError, match='discovery'):
        search.run(document)


@pytest.mark.parametrize('option', ['normfactor', 'background_only_fit'])
def test_search_refuses_discarded_fit_inputs(option):
    from ravel.physics.inference import search

    document = search_document()
    if option == 'normfactor':
        document['backgrounds'][0]['normfactor'] = 'background_scale'
    else:
        document['computations']['background_only_fit'] = True
    with pytest.raises(ValueError, match=option):
        search.run(document)


def test_search_flattens_multibin_regions_in_declared_covariance_order():
    from ravel.physics.inference import search

    document = search_document()
    document['regions'] = [{'name': 'SR0', 'role': 'SR', 'observed': [20, 15]},
                           {'name': 'SR1', 'role': 'SR', 'observed': [10]}]
    document['backgrounds'][0]['yields'] = {
        'SR0': {'values': [20, 15], 'sumw2': [4, 9]},
        'SR1': {'values': [10], 'sumw2': [1]}}
    document['signal_points'][0]['yields'] = {
        'SR0': {'values': [5, 4], 'sumw2': [0, 0]},
        'SR1': {'values': [3], 'sumw2': [0]}}
    document['background_covariance'] = {
        'regions': ['SR1', 'SR0'], 'covariance': [[1, 0, 0], [0, 4, 0], [0, 0, 9]],
        'source': 'synthetic supplied covariance'}
    document['computations']['cls_limits'] = False
    actual = search.run(document)['points'][0]['cls_at_nominal']
    direct = simplified.SimplifiedLikelihood([10, 20, 15], [10, 20, 15], [3, 5, 4],
        ['bin0', 'bin1', 'bin2'], covariance=[[1, 0, 0], [0, 4, 0], [0, 0, 9]])
    assert actual['observed'] == pytest.approx(direct.cls(1, 'observed')[0], abs=1e-6)
    assert actual['expected'] == pytest.approx(direct.cls(1, 'apriori'), abs=1e-6)


def test_search_expected_only_retains_missing_observed():
    from ravel.physics.inference import search

    document = search_document()
    document['regions'][0]['observed'] = None
    document['computations']['allow_blinded_signal_regions'] = True
    point = search.run(document)['points'][0]
    assert point['cls_at_nominal']['observed'] is None
    assert point['cls_limits']['observed'] is None
    assert point['cls_limits']['expected']['status'] == ['resolved'] * 5
    assert np.isfinite(point['cls_limits']['expected']['values']).all()


def test_search_correlation_requires_supplied_error_scales():
    from ravel.physics.inference import search
    document = search_document()
    covariance = document['background_covariance']
    del covariance['covariance']
    covariance['correlation'] = [[1]]
    with pytest.raises(ValueError, match='explicit per-bin errors'):
        search.SearchModel(document)
    covariance['errors'] = [2]
    model = search.SearchModel(document)
    np.testing.assert_array_equal(model._simplified_engine(model.points[0]).covariance, [[4]])


def test_search_mode_record_uses_covariance_engine(tmp_path):
    from ravel.physics.inference import search_statistics
    document = {'schema_version': 1, 'kind': 'search-statistics',
                'statistic': {'origin': 'default'}, **search_document()}
    document['computations']['cls_limits'] = False
    path = tmp_path / 'search.json'
    path.write_text(json.dumps(document))
    result = search_statistics.run({'input': str(path)}, tmp_path, tmp_path / 'output')
    inference = json.loads((tmp_path / 'output' / 'inference.json').read_text())
    assert result['engine'] == inference['engine'] == 'spey-simplified-likelihood'
    assert 'Background uncertainties enter through the supplied covariance only; signal MC statistics and control regions are not represented.' in inference['limitations']
    assert all(r['quantity'] != 'significance' for r in inference['results'])
