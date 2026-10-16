"""Synthetic original-estimator equivalence and unrelated source geometries."""
from copy import deepcopy
import hashlib
import json
import math

import numpy as np
import pytest

from ravel.physics import amplitude_basis as ab, amplitude_store as store, amplitude_response as response
from ravel.physics import amplitude_selection
from ravel.physics.inference import cached_profile, differential, differential_likelihood, documents


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def fixture(tmp_path, edges, *, retain=True):
    basis = ab.Basis(['background', 'resonance'])
    reference = {'id': 'reference', 'constant': {'background': 1.}, 'states': [
        {'mass_gev': 3., 'width_gev': .7, 'propagator': 'fixed-width', 'couplings': {'resonance': 1.}}]}
    model = deepcopy(reference)
    model['id'] = 'alternative'
    model['states'].append({'mass_gev': 7., 'width_gev': 1.3, 'propagator': 'fixed-width', 'couplings': {'resonance': 0.}})
    bindings = [
        {'path': ['states', 0, 'couplings', 'resonance'], 'offset': 1., 'coefficients': {'fraction': -1.}},
        {'path': ['states', 1, 'couplings', 'resonance'], 'offset': 0., 'coefficients': {'fraction': 1.}},
        {'path': ['states', 1, 'mass_gev'], 'offset': 0., 'coefficients': {'pole': 1.}},
        {'path': ['states', 1, 'width_gev'], 'offset': 0., 'coefficients': {'width': 1.}}]
    header = {'basis': list(basis.members), 'observables': ['invariant', 'coordinate'], 'factor_unit': 'fb',
              'proposals': {'a': 'fixed-a', 'b': 'fixed-b'}}
    exchange = np.array([True, False, True])
    if retain:
        header['pairing'] = {'exchange': exchange.tolist()}
    schedule = {'schema_version': 1, 'max_operation_seconds': 100,
                'blocks': [{'id': f'p{i}', 'cohort': 'a' if i < 3 else 'b', 'seed': i+1, 'draws': 30, 'max_seconds': 5}
                           for i in range(6)]}
    raw = []

    def produce(row, writer):
        rng = np.random.default_rng(row['seed'])
        n = len(edges)+1
        x = np.r_[edges[0]-1., (np.array(edges[:-1])+edges[1:])/2, edges[-1]+1.]
        a = rng.normal(size=(n, 2, 3, 2)) + 1j*rng.normal(size=(n, 2, 3, 2))
        a[..., 1] *= 10
        same = np.arange(n) % 3 != 0
        selected = np.arange(n) % 2 == 0
        norm, factors = rng.uniform(.3, 1., n), rng.uniform(.1, .2, n)
        invariant = np.linspace(12., 70., n)
        gram = ab.point_grams(a[:, 0], a[:, 1], identical=same, selected_direct=selected, exchange=exchange,
                             reference=ab.coefficients(reference, basis, invariant), normalization=norm)
        pairing = {'amplitudes': a, 'identical': same, 'selected_direct': selected, 'normalization': norm}
        writer.append(gram=gram, factor=factors, observables=np.column_stack([invariant, x]),
                      **({'pairing': pairing} if retain else {}))
        raw.append({'cohort': row['cohort'], 'pairing': pairing, 's': invariant, 'x': x, 'factor': factors})
        return {'attempted': 30, 'accepted': n, 'rejected': 30-n, 'failed': 0}

    store.run_schedule(tmp_path/'store', schedule, produce, header=header)
    prediction = {'schema_version': 1, 'kind': 'amplitude-predictions', 'store': 'store',
                  'hypotheses': [reference, model], 'reference': 'reference', 'reference_description': 'synthetic baseline',
                  'observable': {'name': 'coordinate', 'invariant': 'invariant', 'label': 'Coordinate', 'unit': 'GeV'},
                  'binning': {'edges': edges}, 'selection': [], 'normalization': {'unit': 'fb', 'representation': 'differential'}}
    path = tmp_path/'prediction.json'
    path.write_text(json.dumps(prediction))
    kwargs = dict(hypothesis='alternative', bindings=bindings, estimator='hypothesis-pairing', max_cache_bytes=10**7)
    return path, kwargs, raw, reference, model, basis, exchange


def direct(raw, reference, model, basis, exchange, edges):
    """Scalar original amplitude partition and block formula, independent of helpers."""
    cohorts = {}
    for block in raw:
        histograms = []
        for h in (reference, model):
            bins = [0.] * (len(edges)+1)
            for i, invariant in enumerate(block['s']):
                coefficients = [complex(h['constant'].get(name, 0.)) for name in basis.members]
                for state in h['states']:
                    prop = 1/complex(invariant-state['mass_gev']**2, state['mass_gev']*state['width_gev'])
                    for k, member in enumerate(basis.members):
                        coefficients[k] += prop*state['couplings'].get(member, 0.)
                payload = block['pairing']
                square = 0.
                for hel in range(len(exchange)):
                    m, s = [sum(payload['amplitudes'][i, pairing, hel, k]*c for k, c in enumerate(coefficients))
                            for pairing in (0, 1)]
                    if not payload['identical'][i]:
                        square += abs(m)**2
                    else:
                        ratio = 1.-2.*(m.conjugate()*s).real/(abs(m)**2+abs(s)**2) if exchange[hel] else 1.
                        square += 2.*abs(m if payload['selected_direct'][i] else s)**2*ratio
                value = square*payload['normalization'][i]*block['factor'][i]
                x = block['x'][i]
                index = len(edges)-1 if x < edges[0] else len(edges)
                for k, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
                    if lo <= x < hi:
                        index = k
                        break
                bins[index] += value
            histograms.append(np.array(bins))
        cohorts.setdefault(block['cohort'], []).append(np.r_[*histograms, histograms[1]-histograms[0]])
    mean = np.zeros(3*(len(edges)+1))
    covariance = np.zeros((len(mean), len(mean)))
    for rows in cohorts.values():
        r = len(rows)
        average = sum(rows)/r
        mean += average
        covariance += sum(np.outer(v-average, v-average) for v in rows)/(r*(r-1))
    return mean, covariance, cohorts


@pytest.mark.parametrize('edges', [list(np.linspace(1., 16., 16)), [-4., 2., 5., 19.]])
def test_original_estimator_mean_covariance_cross_state_and_profile(tmp_path, edges):
    path, kwargs, raw, ref, model, basis, exchange = fixture(tmp_path, edges)
    cached = response.CachedResponse({'input': str(path)}, tmp_path, **kwargs)
    states = [{'fraction': u, 'pole': 7., 'width': 1.3} for u in (0., .27, .68)]
    states.append({'fraction': .4, 'pole': 6.5, 'width': .9})
    outputs = []
    for state in states:
        bound = deepcopy(model)
        bound['states'][0]['couplings']['resonance'] = 1-state['fraction']
        bound['states'][1]['couplings']['resonance'] = state['fraction']
        bound['states'][1]['mass_gev'] = state['pole']
        bound['states'][1]['width_gev'] = state['width']
        mean, covariance, _ = direct(raw, ref, bound, basis, exchange, edges)
        result = cached.evaluate(state)
        np.testing.assert_allclose(result['joint']['mean'], mean, rtol=2e-12, atol=1e-12)
        np.testing.assert_allclose(result['joint']['covariance'], covariance, rtol=2e-11, atol=1e-11)
        outputs.append(result)
    np.testing.assert_allclose(outputs[0]['difference'], 0., atol=8*np.finfo(float).eps)
    cross = response.cross_covariance(outputs[1], outputs[2])
    expected = sum((np.array(outputs[1]['blocks'][c])-np.mean(outputs[1]['blocks'][c], axis=0)).T @
                   (np.array(outputs[2]['blocks'][c])-np.mean(outputs[2]['blocks'][c], axis=0))/6 for c in ('a', 'b'))
    np.testing.assert_allclose(cross, expected)
    np.testing.assert_allclose(cross, response.cross_covariance(outputs[2], outputs[1]).T)
    # Finite-cache equality requires the declared partition; Gram is not a surrogate.
    gram = response.CachedResponse({'input': str(path)}, tmp_path, **{**kwargs, 'estimator': 'reference-gram'})
    assert not np.allclose(gram.evaluate(states[2])['difference'], outputs[2]['difference'])
    n = len(edges)-1
    baseline = np.full(n, 100.)
    fit_model = differential.CachedModel(response=cached, measured=baseline+outputs[1]['difference'], reference=baseline,
             components=[{'name': 'noise', 'law': 'fixed', 'matrix': np.eye(n)}], parameters=list(states[0]), mc_policy='retained_only')
    params = parameters()
    result = cached_profile.profile(fit_model, params, [states[0], states[2]], [{'id': 'fixed', 'fixed': {'fraction': .27}}],
                                    max_evaluations=2000, max_seconds=30, tolerance=1e-4)
    assert result['status'] == 'passed'
    assert result['best_known_global']['point']['fraction'] == pytest.approx(.27, abs=1e-5)
    assert len(result['fits']) == 4 and result['threshold'] is None
    cached.finish()


def parameters():
    return [{'name': name, 'unit': '', 'label': name, 'value': value, 'min': low, 'max': high, 'constant': fixed}
            for name, value, low, high, fixed in [('fraction', .1, 0., 1., False), ('pole', 7., 5., 9., True),
                                                ('width', 1.3, .5, 2., True)]]


def test_zero_limit_and_binding_poles():
    zeros = np.zeros((1, 2, 2, 1), complex)
    assert ab.pairing_square(zeros, [[1.]], identical=np.array([True]), selected_direct=np.array([False]),
                             exchange=np.array([True, False]), normalization=[1.])[0] == 0.
    with pytest.raises(ValueError, match='literal'):
        ab.pairing_square(zeros, [[1.]], identical=[1], selected_direct=[0], exchange=[True, False], normalization=[1.])


def test_cache_missing_pairings_mutation_and_budget(tmp_path):
    path, kwargs, *_ = fixture(tmp_path, [1., 2., 4.], retain=False)
    with pytest.raises(ValueError, match='retained pairings'):
        response.CachedResponse({'input': str(path)}, tmp_path, **kwargs)
    kwargs['estimator'] = 'reference-gram'
    with pytest.raises(ValueError, match='byte budget'):
        response.CachedResponse({'input': str(path)}, tmp_path, **{**kwargs, 'max_cache_bytes': 1})
    cached = response.CachedResponse({'input': str(path)}, tmp_path, **kwargs)
    path.write_text(path.read_text()+'\n')
    with pytest.raises(ValueError, match='ending identity'):
        cached.finish()


def test_dynamic_auxiliary_normalized_score_and_pre_mc_admission(tmp_path):
    path, kwargs, *_ = fixture(tmp_path, [1., 3., 8.])
    cached = response.CachedResponse({'input': str(path)}, tmp_path, **kwargs)
    point = {'fraction': .3, 'pole': 7., 'width': 1.3, 'shift': .2}
    aux = {'parameters': ['shift'], 'response': [[1.], [2.]], 'observed': [.4], 'offset': [.1],
           'matrix': [[2.]], 'covariance': [[.3]]}
    baseline = np.array([30., 40.])
    components = [{'name': 'systematic', 'law': 'ratio', 'matrix': np.diag([1., 2.])},
                  {'name': 'statistical', 'law': 'sqrt-ratio', 'matrix': np.diag([3., 4.])},
                  {'name': 'fixed', 'law': 'fixed', 'matrix': np.diag([.2, .4])}]
    model = differential.CachedModel(response=cached, measured=baseline, reference=baseline, components=components,
             parameters=list(point), mc_policy='independent_gaussian_sum', auxiliary=aux, objective='gaussian')
    result = model.evaluate(point)
    p = baseline+cached.evaluate(point)['difference']+np.array([.2, .4])
    ratio = p/baseline
    C = np.outer(ratio, ratio)*components[0]['matrix']+np.sqrt(np.outer(ratio, ratio))*components[1]['matrix']+components[2]['matrix']
    C += cached.evaluate(point)['mc_covariance']
    expected = (p-baseline)@np.linalg.solve(C, p-baseline)+np.linalg.slogdet(C)[1]
    expected += (.4-(.1+2*.2))**2/.3 + math.log(.3)+3*math.log(2*math.pi)
    assert result['twice_nll'] == pytest.approx(expected)
    bad = differential.CachedModel(response=cached, measured=baseline, reference=baseline, parameters=list(point),
           components=[{'name': 'coefficient', 'law': 'fixed', 'matrix': -np.eye(2)}], mc_policy='independent_gaussian_sum')
    assert bad.evaluate(point)['status'] == 'experimental_not_positive_definite'
    assert bad.component_diagnostics[0]['component_sampling_supported'] is False


def test_budget_preserves_failed_unissued_schedule(tmp_path):
    path, kwargs, *_ = fixture(tmp_path, [1., 3., 8.])
    cached = response.CachedResponse({'input': str(path)}, tmp_path, **kwargs)
    params = parameters()
    model = differential.CachedModel(response=cached, measured=[20., 20.], reference=[20., 20.],
               components=[{'name': 'noise', 'law': 'fixed', 'matrix': np.eye(2)}], parameters=[p['name'] for p in params], mc_policy='retained_only')
    result = cached_profile.profile(model, params, [{'fraction': .1, 'pole': 7., 'width': 1.3}],
              [{'id': 'edge', 'fixed': {'fraction': 1.}}], max_evaluations=1, max_seconds=30, tolerance=1e-4)
    assert [r['delivery'] for r in result['fits']] == ['failed', 'unissued']
    assert len(result['evaluations']) == 1 and result['status'] == 'failed'


def test_matrix_source_join_uses_supplied_interval_order():
    table = {'independent_variables': [{'values': [{'low': a, 'high': b} for a, b in rows]} for rows in
             [[(2, 5), (0, 2), (2, 5), (0, 2)], [(2, 5), (0, 2), (0, 2), (2, 5)]]],
             'dependent_variables': [{'values': [{'value': v} for v in [4., 2., .3, .3]]}]}
    np.testing.assert_array_equal(documents.hepdata_matrix(table, bin_edges=[0., 2., 5.]), [[2., .3], [.3, 4.]])
    with pytest.raises(ValueError, match='binning'):
        documents.hepdata_matrix(table, bin_edges=[0., 3., 5.])
    table['independent_variables'][1]['values'].pop()
    with pytest.raises(ValueError, match='every'):
        documents.hepdata_matrix(table, bin_edges=[0., 2., 5.])


def test_adapter_delivers_cached_profiles_and_complete_inputs(tmp_path, monkeypatch):
    path, kwargs, *_ = fixture(tmp_path, [1., 3., 8.])
    doc = {'schema_version': 1, 'kind': 'differential-likelihood', 'operation': 'cached-profile',
           'statistic': {'verbatim': 'Conditional objective differences only', 'objective': 'chi2'},
           'response': {'prediction': pin(path), **{k: v for k, v in kwargs.items() if k != 'max_cache_bytes'}},
           'measurement': {'values': [30., 30.], 'unit': 'fb/GeV', 'bin_edges': [1., 3., 8.]},
           'reference': {'values': [30., 30.], 'description': 'supplied synthetic baseline'},
           'covariance': [{'name': 'noise', 'law': 'fixed', 'matrix': np.eye(2).tolist()}], 'parameters': parameters(),
           'fit': {'starts': [{'fraction': .1, 'pole': 7., 'width': 1.3}],
                   'profile_cells': [{'id': 'null', 'fixed': {'fraction': 0.}}], 'tolerance': 1e-4},
           'mc_policy': 'retained_only', 'max_condition': 1e8,
           'resources': {'max_cache_bytes': 10**7, 'max_evaluations': 1000, 'max_seconds': 30, 'max_output_bytes': 10**7}}
    task_path = tmp_path/'fit.json'
    task_path.write_text(json.dumps(doc))
    task = {'input': str(task_path)}
    files = differential_likelihood.inputs(task, tmp_path)
    assert path in files and len(files) == len(set(files))
    assert len([p for p in files if p.suffix == '.ravg']) == 6
    result = differential_likelihood.run(task, tmp_path, tmp_path/'out')
    assert result['status'] == 'passed'
    emitted = json.loads((tmp_path/'out/inference.json').read_text())
    row = emitted['results'][0]
    assert row['best_known_global']['point']['fraction'] == pytest.approx(0., abs=1e-5)
    assert len(row['cross_state_covariance']['upper_triangle']) == 3
    assert len(row['responses'][0]['joint']['mean']) == 12
    assert emitted['physics_validated'] is False and row['intervals'] is None

    # A source-admitted native setup failure retains all unissued calls; no ROOT import.
    from ravel.physics.inference import cached_native
    runtime = tmp_path/'synthetic-runtime'
    runtime.write_bytes(b'inert runtime identity')
    doc['fit']['engine'] = 'roofit'
    doc['runtime'] = {'version': 'synthetic', 'files': [pin(runtime)]}
    for parameter in doc['parameters']:
        parameter['error'] = .1
    task_path.write_text(json.dumps(doc))
    monkeypatch.setattr(cached_native, 'authorized', lambda *args: None)
    def refused_runtime(*args):
        raise RuntimeError('synthetic native setup failure')
    monkeypatch.setattr(cached_native, 'load', refused_runtime)
    failed = differential_likelihood.run(task, tmp_path, tmp_path/'failed-native')
    assert failed['status'] == 'failed'
    record = json.loads((tmp_path/'failed-native/inference.json').read_text())['results'][0]
    assert record['scheduled_fit_calls'] == 2 and record['objective_evaluations'] == 0
    assert all(r['delivery'] == 'unissued' for r in record['fits'])


def test_supplied_fiducial_definition_changes_acceptance_and_preserves_ranking():
    spatial = np.array([[15., 0., 3.], [-11., 0., -2.], [0., 10., 1.], [0., -9., -1.]])
    momenta = np.column_stack([spatial, np.linalg.norm(spatial, axis=1)])[None, ...]
    spec = {'particles': [0, 1, 2, 3], 'acceptance': {'1': {'pt_min': 2., 'abs_eta_max': 3.},
            '2': {'pt_min': 2., 'abs_eta_max': 3.}}, 'rank_pt_min': [12., 8., 5.], 'pairing_mass': 25.,
            'primary_window': [20., 30.], 'secondary_min': {'knots': [0., 50., 100.], 'values': [2., 4., 10.]},
            'secondary_max': 23., 'same_pair_dr': .1, 'same_species_dr': .1, 'different_species_dr': .2,
            'all_pair_mass_min': 1., 'overlap_dr': 1e-13}
    assert amplitude_selection.select(momenta, [1, -1, 2, -2], spec).tolist() == [True]
    changed = deepcopy(spec)
    changed['rank_pt_min'][0] = 16.
    assert amplitude_selection.select(momenta, [1, -1, 2, -2], changed).tolist() == [False]
    changed = deepcopy(spec)
    changed['primary_window'] = [20., 24.]
    assert amplitude_selection.select(momenta, [1, -1, 2, -2], changed).tolist() == [False]
    changed['unexpected'] = 1
    with pytest.raises(ValueError, match='complete supplied'):
        amplitude_selection.validate(changed)


def test_integrator_retains_all_pairings_with_inert_stage_seam(tmp_path, monkeypatch):
    from ravel.physics import amplitude_integration as integration, amplitude_records
    from types import SimpleNamespace
    protocol = {'members': {'amplitude': {}}, 'channels': {'1': {'pdg': [1, -1, 2, -2, 3, -3]}}, 'factor_unit': 'fb',
                'operations': {'block': 2}}
    schedule = {'schema_version': 1, 'max_operation_seconds': 10,
                'blocks': [{'id': f'b{i}', 'cohort': 'channel', 'seed': i+1, 'draws': 2, 'max_seconds': 2} for i in range(2)]}
    ctx = {'doc': {'operation': 'blocks', 'retain_pairings': True, 'schedule': schedule}, 'protocol': protocol,
           'spin0': None, 'store': tmp_path/'store', 'safety_cuts': [],
           'addon': SimpleNamespace(identity=lambda: {'id': 'synthetic-addon'}),
           'cohorts': {'channel': {'channel': 1, 'card': {'sha256': 'synthetic-card'}}}}
    # This control exercises the real writer/manifest join; it never prepares or launches a backend.
    monkeypatch.setattr(integration, 'load', lambda *args: ctx)
    monkeypatch.setattr(integration, 'warmups', lambda *args: ({'channel': b'proposal'}, [{'cohort': 'channel', 'sha256': 'proposal'}]))
    amps = np.ones((2, 2, 16, 1), complex)
    meta = np.ones((2, 9))
    parsed = {'meta': meta, 'identical': np.array([False, True]), 'selected_direct': np.array([True, False]),
              'summary': {'attempted': 2, 'accepted': 2, 'rejected': 0, 'failed': 0, 'excluded': 0}}
    census = {'attempted': 2, 'excluded': 0, 'stored': 2, 'weight_unmeasured': 0, 'by_cut': {},
              'factor_excluded': 0., 'factor_stored': 2.,
              'weight_excluded': 0., 'weight_stored': 2.}
    monkeypatch.setattr(integration, 'run_stage', lambda *args, **kw: (parsed, None, {'synthetic': True,
                                                                                     'safety': {'census': census}}))
    monkeypatch.setattr(amplitude_records, 'oracle_check', lambda *args, **kw: {'passed': True, 'max_relative_residual': {}})
    monkeypatch.setattr(amplitude_records, 'to_block', lambda *args, **kw: (
        {'gram': np.ones((2, 1, 1)), 'factor': np.ones(2), 'observables': np.ones((2, 5)),
         'momenta': np.ones((2, 6, 4)), 'amplitudes': amps}, parsed, None))
    result = integration.run({'input': 'synthetic'}, tmp_path, tmp_path/'out')
    assert result['store_status'] == 'complete'
    block = store.read_block(tmp_path/'store/b0.ravg')
    np.testing.assert_array_equal(block['pairing']['amplitudes'], amps)
    assert block['header']['pairing']['exchange'] == amplitude_records.EXCHANGE.tolist()


def test_native_profile_seam_retains_status_and_checks_objective_scale():
    from types import SimpleNamespace
    params = [{'name': 'x', 'unit': '', 'label': 'x', 'value': .5, 'min': 0., 'max': 1., 'constant': False, 'error': .1}]
    calls = []
    def minimize(parameters, point, fixed, evaluate, index):
        calls.append((dict(point), dict(fixed)))
        final = {'x': fixed.get('x', .25)}
        twice = evaluate(final)
        return final, {'fit': {'performed': True, 'min_nll': .5*twice, 'status': 0, 'cov_qual': 3}}, True
    model = SimpleNamespace(evaluate=lambda p: {'status': 'accepted', 'twice_nll': (p['x']-.25)**2})
    result = cached_profile.profile(model, params, [{'x': .1}, {'x': .9}], [{'id': 'edge', 'fixed': {'x': 1.}}],
             max_evaluations=30, max_seconds=10, tolerance=1e-5, native_minimizer=minimize)
    assert result['status'] == 'passed' and len(calls) == 4
    assert calls[:2] == [({'x': .1}, {}), ({'x': .9}, {})]
    assert result['fits'][2]['q'] == pytest.approx(.75**2)
    assert params[0]['value'] == .5


def test_native_route_requires_ordinary_approval_without_loading_root(tmp_path):
    from ravel.physics.inference import cached_native
    with pytest.raises(ValueError, match='ordinary admitted'):
        cached_native.authorized({'input': 'synthetic.json'}, tmp_path/'result')
    assert cached_native.ASSET.is_file()


def test_profile_retains_disconnected_minima_and_invalid_states():
    from types import SimpleNamespace
    params = [{'name': 'x', 'unit': '', 'label': 'x', 'value': 0., 'min': -2., 'max': 2., 'constant': False}]
    model = SimpleNamespace(evaluate=lambda p: {'status': 'accepted', 'twice_nll': (p['x']**2-1)**2})
    result = cached_profile.profile(model, params, [{'x': -.8}, {'x': .8}], [{'id': 'middle', 'fixed': {'x': 0.}}],
                                   max_evaluations=300, max_seconds=10, tolerance=1e-4)
    assert result['status'] == 'passed'
    assert result['fits'][0]['point']['x'] == pytest.approx(-1., abs=1e-4)
    assert result['fits'][1]['point']['x'] == pytest.approx(1., abs=1e-4)
    assert result['fits'][2]['q'] == pytest.approx(1., abs=1e-8)
    bad = SimpleNamespace(evaluate=lambda p: {'status': 'experimental_not_positive_definite', 'twice_nll': None})
    failed = cached_profile.profile(bad, params, [{'x': .8}], [], max_evaluations=100, max_seconds=10, tolerance=1e-4)
    assert failed['best_known_global'] is None and failed['status'] == 'failed'
    assert failed['evaluations'][0]['score']['status'] == 'experimental_not_positive_definite'


def test_original_raw_returns_replay_complete_cache_and_refuse_drift(tmp_path):
    from amplitude_fixtures import DECLARED_CUTS, program_output
    from ravel.physics import amplitude_records as records
    protocol = {'format': 'RAVEL_MCFM_3', 'safety_cuts': DECLARED_CUTS, 'channels': {'1': {'pdg': [21, 21, 11, -11, 13, -13]}},
                'amplitude_channels': ['up', 'down', 'bottom', 'top', 'hbottom', 'htop'],
                'members': {'background': {'sum': {'up': 2, 'down': 2, 'bottom': 1, 'top': 1}},
                            'signal': {'sum': {'hbottom': 1, 'htop': 1}, 'per_reference_propagator': True}},
                'factor': ['grid_weight_over_n', 'phase_space', 'flux', 'pdf_product'],
                'factor_divisor': 'branching_ratio', 'factor_unit': 'fb', 'operations': {'block': 2}}
    proposal = tmp_path/'proposal.bin'
    proposal.write_bytes(b'synthetic fixed proposal')
    sources, captured = [], []
    schedule = {'schema_version': 1, 'max_operation_seconds': 30,
                'blocks': [{'id': f'b{i}', 'cohort': 'sample', 'seed': 100+i, 'draws': 3, 'max_seconds': 5} for i in range(2)]}
    def produce(row, writer):
        raw = program_output(2, 3, row['seed'], 1, reject=(2,))
        path = tmp_path/(row['id']+'.dat')
        path.write_bytes(raw)
        parsed = records.parse(raw, operation=2, draws=3, seed=row['seed'], channel=1, protocol=protocol)
        values, _, _ = records.to_block(parsed, protocol)
        amps = values.pop('amplitudes')
        writer.append(**values, pairing={'amplitudes': amps, 'identical': parsed['identical'],
                      'selected_direct': parsed['selected_direct'], 'normalization': parsed['meta'][:, 5]})
        sources.append({'id': row['id'], 'channel': 1, 'source': pin(path), 'proposal': pin(proposal)})
        captured.append(parsed)
        return {k: parsed['summary'][k] for k in ('attempted', 'accepted', 'rejected', 'failed')}
    header = {'basis': ['background', 'signal'], 'observables': list(records.OBSERVABLES), 'factor_unit': 'fb',
              'particles': {'pdg': protocol['channels']['1']['pdg'], 'status': [-1, -1, 1, 1, 1, 1]},
              'pairing': {'exchange': records.EXCHANGE.tolist()}, 'proposals': {'sample': pin(proposal)['sha256']},
              'safety_cuts': DECLARED_CUTS}
    store.run_schedule(tmp_path/'store', schedule, produce, header=header)
    mass, width = map(float, captured[0]['meta'][0, 1:3])
    ref = {'id': 'baseline', 'constant': {'background': 1.}, 'states': [
        {'mass_gev': mass, 'width_gev': width, 'propagator': 'fixed-width', 'couplings': {'signal': 1.}}]}
    alternative = deepcopy(ref)
    alternative['id'] = 'alternative'
    doc = {'schema_version': 1, 'kind': 'amplitude-predictions', 'store': 'store', 'hypotheses': [ref, alternative],
           'reference': 'baseline', 'reference_description': 'synthetic source',
           'observable': {'name': records.OBSERVABLES[1], 'invariant': records.OBSERVABLES[0], 'label': 'Coordinate', 'unit': 'GeV'},
           'selection': [], 'normalization': {'unit': 'fb', 'representation': 'integrated'}, 'binning': {'edges': [0., 1000., 5000.]}}
    path = tmp_path/'prediction.json'
    path.write_text(json.dumps(doc))
    replay = {'protocol': protocol, 'blocks': sources}
    kwargs = {'hypothesis': 'alternative', 'bindings': [], 'estimator': 'hypothesis-pairing', 'max_cache_bytes': 10**7,
              'replay': replay, 'replay_base': tmp_path}
    cached = response.CachedResponse({'input': str(path)}, tmp_path, **kwargs)
    assert cached.evaluate({})['raw_replayed'] is True
    cached.finish()
    first = tmp_path/'b0.dat'
    first.write_bytes(first.read_bytes().replace(b' META ', b' BAD ', 1))
    with pytest.raises(ValueError, match='digest'):
        response.CachedResponse({'input': str(path)}, tmp_path, **kwargs)
