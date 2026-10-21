"""Finite-toy CLs controls on synthetic counting likelihoods."""
from copy import deepcopy
import json
import math
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from ravel.limits import attach_limits, read_limits
from ravel.physics import pyhf_exclude as exclude
from ravel.physics.inference import search, toy_cls


@pytest.fixture
def robust_backend():
    """Use the profile optimizer and restore the caller's backend state."""
    previous = exclude.pyhf.get_backend()
    previous_escalated = exclude.robust_optimizer.escalated
    try:
        exclude.robust_optimizer.escalated = False
        exclude.pyhf.set_backend('numpy', exclude.robust_optimizer(maxiter=200000))
        yield
    finally:
        exclude.pyhf.set_backend(*previous)
        exclude.robust_optimizer.escalated = previous_escalated


def counting(n=3, b=2, db=.6, s=3):
    return exclude.model_from_counting(dict(name='SR', n=n, b=b, db=db, s=s))


def reference():
    result = {'obs_limit': 2.0, 'exp_limits': [1.0, 1.5, 2.0, 2.5, 3.0],
              'scan_mu': [.1, 1.0, 2.0, 3.0, 4.0],
              'scan_cls_obs': [.9, .2, .05, .02, .01],
              'scan_cls_exp': [[.9] * 5, [.2] * 5, [.05] * 5, [.02] * 5, [.01] * 5],
              'limit_status': {'observed': 'resolved', 'expected': ['resolved'] * 5},
              'limit_brackets': {'observed': [1.0, 3.0],
                                 'expected': [[.5, 1.5], [1.0, 2.0], [1.5, 2.5],
                                              [2.0, 3.0], [2.5, 3.5]]},
              'at_poi_cap': False, 'median_at_cap': False, 'at_mu_floor': False,
              'band_degenerate': False}
    attach_limits(result)
    return result


def assert_rng_equal(a, b):
    assert a[0] == b[0]
    np.testing.assert_array_equal(a[1], b[1])
    assert a[2:] == b[2:]


def assert_interval(value, interval):
    assert len(interval) == 2
    lo, hi = interval
    assert lo is None or math.isfinite(lo) and lo <= value
    assert hi is None or math.isfinite(hi) and value <= hi


def assert_toy_result(result, ntoys):
    xs = result['scan_mu']
    assert xs == sorted(set(xs)) and len(xs) >= 2
    assert result['n_fits'] == len(xs) * ntoys * 2
    assert len(result['scan_cls_obs']) == len(xs)
    assert np.shape(result['scan_cls_exp']) == (len(xs), 5)
    uncertainty = result['cls_mc_uncertainty']
    assert np.shape(uncertainty['observed']) == (len(xs),)
    assert np.shape(uncertainty['expected']) == (len(xs), 5)
    for values in (uncertainty['observed'], uncertainty['expected']):
        assert np.all(np.isfinite(values)) and np.all(np.asarray(values) >= 0)
    limits = read_limits(result)
    intervals = result['limit_mc_interval']
    for curve, interval in zip((limits.observed, *limits.expected),
                               (intervals['observed'], *intervals['expected'])):
        assert curve.status in {'resolved', 'above_scan', 'below_scan'}
        assert_interval(curve.value, interval)
        assert curve.bracket is not None
        assert_interval(curve.value, curve.bracket)


@pytest.mark.parametrize('n,b,applied', [(2, 1, 'toybased'), (50, 40, 'asymptotic')])
def test_auto_policy_uses_main_bin_counts(n, b, applied):
    model, data = counting(n=n, b=b, db=.6)
    policy = toy_cls.calculator_policy(model, data, requested='auto')
    assert policy['requested'] == 'auto' and policy['applied'] == applied
    assert policy['small_count_threshold'] == 5.0
    if applied == 'toybased':
        assert policy['triggers']
        trigger = policy['triggers'][0]
        assert trigger['channel'] == 'singlechannel' and trigger['bin'] == 0
        assert trigger['n'] == n and trigger['b'] == pytest.approx(b)
    else:
        assert policy['triggers'] == []



def test_policy_maps_main_bins_and_ignores_auxiliary_counts():
    config = SimpleNamespace(suggested_init=lambda: [1.0], poi_index=0,
                             nmaindata=3, channels=['A', 'B'], channel_nbins={'A': 2, 'B': 1})
    model = SimpleNamespace(config=config, expected_actualdata=lambda pars: [40.0, 2.0, 40.0])
    policy = toy_cls.calculator_policy(model, [50.0, 8.0, 50.0, 0.0], requested='auto')
    assert policy['triggers'] == [{'channel': 'A', 'bin': 1, 'n': 8.0, 'b': 2.0}]
    model.expected_actualdata = lambda pars: [40.0, 40.0, 40.0]
    policy = toy_cls.calculator_policy(model, [50.0, 50.0, 50.0, 0.0], requested='auto')
    assert policy['applied'] == 'asymptotic' and policy['triggers'] == []


def test_explicit_asymptotic_preserves_small_count_reason():
    model, data = counting(n=2, b=1)
    policy = toy_cls.calculator_policy(model, data, requested='asymptotic')
    assert policy['applied'] == 'asymptotic' and policy['requested'] == 'asymptotic'
    assert policy['triggers'] and policy['reason'] == 'requested'


def test_real_toys_are_seeded_json_safe_and_restore_rng(robust_backend):
    model, data = counting()
    asymptotic = exclude.compute(model, data, n_curve=5)
    # Keep all six crossing/RNG checks at 400 toys on the endpoint grid;
    # the complete default grid is checked separately and exercised by the CLI.
    options = dict(ntoys=400, seed=7, asymptotic=asymptotic, grid_factors=(.5, 2.0))
    state = np.random.get_state()
    first = toy_cls.toy_limits(model, data, **options)
    assert_rng_equal(state, np.random.get_state())
    second = toy_cls.toy_limits(model, data, **options)
    assert_rng_equal(state, np.random.get_state())
    # wall_seconds is a measurement of this run, not part of the statistical result
    assert first.pop('wall_seconds') > 0 and second.pop('wall_seconds') > 0
    assert json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(second, sort_keys=True, allow_nan=False)
    assert_toy_result(first, 400)
    assert first['limit_status'] == {'observed': 'resolved', 'expected': ['resolved'] * 5}
    assert any(v > 0 for v in first['cls_mc_uncertainty']['observed'])


def test_budget_refuses_before_any_toy_calculation(monkeypatch):
    model, data = counting()
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('budget refusal must precede calculator construction')
    monkeypatch.setattr(exclude.pyhf.infer, 'hypotest', forbidden)
    monkeypatch.setattr(exclude.pyhf.infer.calculators, 'ToyCalculator', forbidden)
    with pytest.raises(toy_cls.ToyBudgetExceeded):
        toy_cls.toy_limits(model, data, ntoys=100, seed=3, asymptotic=reference(), max_fits=10)
    assert not calls


def test_budget_apply_keeps_asymptotic_headline_and_recommends_toys(monkeypatch):
    model, data = counting()
    before = reference()
    original = deepcopy(before)
    def forbidden(*args, **kwargs):
        raise AssertionError('no toy calculator fits are admitted')
    monkeypatch.setattr(exclude.pyhf.infer.calculators, 'ToyCalculator', forbidden)
    result = toy_cls.apply(model, data, before, requested='auto', ntoys=100, seed=3, max_fits=10)
    for key in ('obs_limit', 'exp_limits', 'limits', 'limit_status', 'limit_brackets', 'scan_mu'):
        assert result[key] == original[key]
    policy = result['calculator']
    assert policy['applied'] == 'asymptotic' and policy['recommended'] == 'toybased'
    assert policy['triggers'] and policy['toys']['status'] == 'not_run'
    assert policy['toys']['reason'] == 'budget' and policy['toys']['bound'] == 'fits'
    assert policy['toys']['estimated_fits'] > policy['toys']['max_fits'] == 10


def test_wall_time_budget_refuses_from_a_measured_pilot(monkeypatch):
    model, data = counting()
    clock = {'now': 0.0}
    monkeypatch.setattr('time.perf_counter', lambda: clock['now'])
    pilots = []

    def slow_point(model_, data_, mu, ntoys):
        pilots.append((mu, ntoys))
        clock['now'] += 2.0 * ntoys  # one second per toy experiment, two hypotheses per toy
        return [.5] * 6, [.4] * 6, [.8] * 6

    monkeypatch.setattr(toy_cls, '_toy_point', slow_point)
    result = toy_cls.apply(model, data, reference(), requested='auto', ntoys=100, seed=3, max_fits=None,
                           max_seconds=60.0)
    toys = result['calculator']['toys']
    assert pilots == [(pilots[0][0], toy_cls.PILOT_TOYS)]  # only the pilot ran
    assert result['calculator']['applied'] == 'asymptotic' and result['calculator']['recommended'] == 'toybased'
    assert toys['status'] == 'not_run' and toys['reason'] == 'budget' and toys['bound'] == 'seconds'
    assert toys['pilot']['seconds_per_toy_experiment'] == pytest.approx(1.0)
    assert toys['estimated_seconds'] == pytest.approx(toys['estimated_fits'] * 1.0) and toys['max_seconds'] == 60.0
    with pytest.raises(ValueError, match='max_seconds'):
        toy_cls.toy_limits(model, data, ntoys=100, seed=3, asymptotic=reference(), max_seconds=-1.0)
    # the deterministic fit-count budget refuses before any pilot runs
    pilots.clear()
    with pytest.raises(toy_cls.ToyBudgetExceeded) as refused:
        toy_cls.toy_limits(model, data, ntoys=100, seed=3, asymptotic=reference(), max_fits=10, max_seconds=60.0)
    assert refused.value.bound == 'fits' and refused.value.estimated_seconds is None and pilots == []


def test_pilot_does_not_change_the_seeded_ensemble(robust_backend):
    model, data = counting()
    asymptotic = exclude.compute(model, data, n_curve=5)
    options = dict(ntoys=60, seed=11, asymptotic=asymptotic, grid_factors=(.5, 2.0))
    plain = toy_cls.toy_limits(model, data, **options)
    piloted = toy_cls.toy_limits(model, data, max_seconds=1e6, **options)
    assert piloted['pilot']['toys'] == toy_cls.PILOT_TOYS and plain['pilot'] is None
    for key in ('obs_limit', 'exp_limits', 'scan_cls_obs', 'scan_cls_exp', 'cls_mc_uncertainty'):
        assert piloted[key] == plain[key]


def stub_calculator(monkeypatch, function):
    visits = []
    class Calculator:
        def __init__(self, *args, **kwargs):
            self.ntoys = kwargs['ntoys']
        def distributions(self, mu, *args, **kwargs):
            self.mu = float(mu)
            visits.append(self.mu)
            dist = SimpleNamespace(samples=np.arange(self.ntoys, dtype=float))
            return dist, dist
        def teststatistic(self, mu):
            self.mu = float(mu)
            return 0.0
        def pvalues(self, *args):
            cls = function(self.mu)
            clb = 1.0 if cls == 1.0 else .8
            return np.asarray(cls * clb), np.asarray(clb), np.asarray(cls)
        def expected_pvalues(self, *args):
            cls = function(self.mu)
            clb = 1.0 if cls == 1.0 else .8
            return [np.full(5, cls * clb), np.full(5, clb), np.full(5, cls)]
    monkeypatch.setattr(exclude.pyhf.infer.calculators, 'ToyCalculator', Calculator)
    return visits


def test_synthetic_grid_is_deduplicated_and_interpolates_root(monkeypatch):
    model, data = counting()
    visits = stub_calculator(monkeypatch, lambda mu: min(.95, .1 / mu))
    result = toy_cls.toy_limits(model, data, ntoys=100, seed=3, asymptotic=reference(),
                                grid_factors=(.5, 1, 1 + 1e-11, 1, 2, .5))
    assert visits == sorted(set(visits))
    assert result['scan_mu'] == visits
    assert result['obs_limit'] == pytest.approx(2)
    assert result['exp_limits'] == pytest.approx([2] * 5)
    assert result['limit_status']['observed'] == 'resolved'
    assert_toy_result(result, 100)
    assert all(v > 0 for v in result['cls_mc_uncertainty']['observed'])


def test_default_grid_uses_all_seven_factors_for_both_roots(monkeypatch):
    model, data = counting()
    visits = stub_calculator(monkeypatch, lambda mu: min(.95, .1 / mu))
    asymptotic = {'obs_limit': 3, 'exp_limits': [1, 1.5, 2, 2.5, 3],
                  'limit_status': {'observed': 'resolved', 'expected': ['resolved'] * 5}}
    result = toy_cls.toy_limits(model, data, ntoys=50, seed=7, asymptotic=asymptotic)
    factors = (.5, .7, .85, 1, 1.2, 1.5, 2)
    expected = sorted({root * factor for root in (2, 3) for factor in factors})
    assert result['scan_mu'] == visits == expected
    assert result['n_fits'] == len(expected) * 50 * 2


@pytest.mark.parametrize('cls,status', [(0.0, 'below_scan'), (1.0, 'above_scan')])
def test_zero_or_unit_empirical_tails_have_zero_binomial_error(monkeypatch, cls, status):
    model, data = counting()
    stub_calculator(monkeypatch, lambda mu: cls)
    result = toy_cls.toy_limits(model, data, ntoys=100, seed=3, asymptotic=reference())
    assert result['limit_status']['observed'] == status
    assert result['limit_status']['expected'] == [status] * 5
    np.testing.assert_array_equal(result['cls_mc_uncertainty']['observed'], 0)
    np.testing.assert_array_equal(result['cls_mc_uncertainty']['expected'], 0)
    assert_toy_result(result, 100)


@pytest.mark.parametrize('field,value', [('ntoys', 0), ('ntoys', -1), ('ntoys', True),
                                        ('ntoys', 1.5), ('ntoys', 49), ('seed', -1), ('seed', True),
                                        ('seed', 1.5), ('seed', 2 ** 32)])
def test_invalid_toy_options_refuse_before_fitting(monkeypatch, field, value):
    model, data = counting()
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid options must refuse before fitting')
    monkeypatch.setattr(exclude.pyhf.infer.calculators, 'ToyCalculator', forbidden)
    options = dict(ntoys=100, seed=3)
    options[field] = value
    with pytest.raises(ValueError):
        toy_cls.toy_limits(model, data, asymptotic=reference(), **options)



@pytest.mark.parametrize('p_sb,cl_b', [(0.0, .8), (1.0, 1.0), (.04, .8)])
def test_ratio_mc_error_matches_binomial_propagation(p_sb, cl_b):
    expected = math.sqrt(p_sb * (1 - p_sb) / 100 / cl_b ** 2
                         + p_sb ** 2 * cl_b * (1 - cl_b) / 100 / cl_b ** 4)
    assert toy_cls._mc_error(p_sb, cl_b, 100) == pytest.approx(expected)


def test_zero_background_tail_is_unresolved():
    with pytest.raises(ValueError, match='denominator'):
        toy_cls._mc_error(.1, 0, 100)


def test_root_uses_log_mu_interpolation():
    value, status, bracket = toy_cls._crossing([1.0, 4.0], [.1, .025], .05)
    assert value == pytest.approx(4 ** (2 / 3))
    assert status == 'resolved' and bracket == [1.0, 4.0]


def test_unknown_calculator_is_rejected():
    model, data = counting()
    with pytest.raises(ValueError, match='calculator'):
        toy_cls.calculator_policy(model, data, requested='unknown')


def test_grid_uses_only_resolved_reference_roots(monkeypatch):
    model, data = counting()
    visits = stub_calculator(monkeypatch, lambda mu: min(.95, .1 / mu))
    asymptotic = reference()
    asymptotic['obs_limit'] = 100
    asymptotic['limit_status']['observed'] = 'above_scan'
    result = toy_cls.toy_limits(model, data, ntoys=50, seed=0, asymptotic=asymptotic,
                                grid_factors=(.5, 1, 2))
    assert result['scan_mu'] == visits == [1, 2, 4]
    assert result['agreement_with_asymptotic']['observed'] is None
    asymptotic['limit_status']['expected'][2] = 'above_scan'
    with pytest.raises(ValueError, match='resolved'):
        toy_cls.toy_limits(model, data, ntoys=50, seed=0, asymptotic=asymptotic)
    assert visits == [1, 2, 4]


def test_rng_and_optimizer_escalation_restore_after_failed_toy(monkeypatch, robust_backend):
    model, data = counting()
    state = np.random.get_state()
    escalation = exclude.robust_optimizer.escalated
    class FailedCalculator:
        def __init__(self, *args, **kwargs):
            np.random.random()
            exclude.robust_optimizer.escalated = not escalation
            raise RuntimeError('synthetic failed fit')
    monkeypatch.setattr(exclude.pyhf.infer.calculators, 'ToyCalculator', FailedCalculator)
    with pytest.raises(RuntimeError, match='synthetic failed fit'):
        toy_cls.toy_limits(model, data, ntoys=50, seed=7, asymptotic=reference())
    assert_rng_equal(state, np.random.get_state())
    assert exclude.robust_optimizer.escalated == escalation


def test_explicit_asymptotic_apply_changes_only_calculator():
    model, data = counting()
    original = reference()
    result = deepcopy(original)
    assert toy_cls.apply(model, data, result, requested='asymptotic', ntoys=100,
                          seed=1, max_fits=10) is result
    policy = result.pop('calculator')
    assert result == original
    assert policy['applied'] == 'asymptotic' and policy['toys'] is None


def test_apply_retains_reference_and_regenerates_typed_toy_headline(monkeypatch):
    model, data = counting()
    stub_calculator(monkeypatch, lambda mu: min(.95, .1 / mu))
    original = reference()
    result = toy_cls.apply(model, data, deepcopy(original), requested='auto', ntoys=50,
                           seed=1, max_fits=10000)
    assert result['calculator']['applied'] == 'toybased'
    assert result['calculator']['toys']['status'] == 'run'
    for key, value in result['asymptotic_reference'].items():
        assert value == original[key]
    assert read_limits(result).observed.value == result['obs_limit']
    assert result['inference']['method'].startswith('toy-based CLs')
    assert result['scan_mu'] == original['scan_mu']
    from ravel.validation import regression_triggers
    assert result['computed_checks'] == regression_triggers.consume_flags(result)


def search_document():
    return {'regions': [{'name': 'SR', 'role': 'SR', 'observed': [2]}],
            'backgrounds': [{'name': 'bkg', 'normfactor': None,
                             'yields': {'SR': {'values': [2], 'sumw2': [.36]}}}],
            'signal_points': [{'id': 'p', 'coordinates': {},
                               'yields': {'SR': {'values': [3], 'sumw2': [0]}}}],
            'mc_statistics': 'shapesys', 'systematics': None,
            'data': {'mode': 'observed', 'injections': {}},
            'computations': {'discovery': False, 'cls_at_nominal': False, 'cls_limits': True,
                             'background_only_fit': False},
            'asimov_source': 'nominal', 'cls_level': .05,
            'mc_adequacy': {'max_relative_uncertainty': .5, 'min_effective_entries': 1},
            'contours': None, 'cls_calculator': 'auto', 'cls_toys': {'count': 100, 'seed': 1}}


def test_search_auto_applies_declared_small_count_toys(robust_backend):
    point = search.run(search_document())['points'][0]
    result = point['cls_limits']
    assert result['calculator']['applied'] == 'toybased'
    assert result['calculator']['toys']['ntoys'] == 100
    assert result['calculator']['toys']['seed'] == 1
    assert result['calculator']['toys']['status'] == 'run'
    assert_interval(result['observed']['value'], result['mc_interval']['observed'])
    for value, interval in zip(result['expected']['values'], result['mc_interval']['expected']):
        assert_interval(value, interval)


@pytest.mark.parametrize('applied', ['asymptotic', 'toybased'])
def test_search_summary_names_the_applied_calculator(tmp_path, monkeypatch, applied):
    from ravel.physics.inference import search_statistics
    document = search_document()
    document.update(schema_version=1, kind='search-statistics', statistic={'origin': 'default'})
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(document))
    calculator = {'applied': applied, 'toys': {'status': 'run', 'ntoys': 100, 'seed': 1}
                  if applied == 'toybased' else None}
    raw = {'mc_adequacy_flags': [], 'data_mode': 'observed', 'injections': {},
           'blinded_signal_regions': [], 'regions': document['regions'],
           'systematics': None, 'abcd': [], 'points': [{
               'id': 'p', 'coordinates': {}, 'signal_yields': {'SR': [3]},
               'cls_limits': {'level': .05, 'observed': {'value': 2, 'status': 'resolved'},
                              'expected': {'values': [1, 1.5, 2, 2.5, 3], 'status': ['resolved'] * 5},
                              'flags': {}, 'calculator': calculator}}]}
    monkeypatch.setattr(search, 'run', lambda *args, **kwargs: raw)
    output = tmp_path / 'out'
    search_statistics.run({'input': str(path)}, tmp_path, output)
    result = json.loads((output / 'inference.json').read_text())
    summary = next(row['summary'] for row in result['results'] if row['quantity'] == 'cls-limit')
    expected = 'toy-based CLs' if applied == 'toybased' else 'asymptotic CLs'
    assert expected in summary
    if applied == 'toybased':
        assert 'toy-based calibration (100 toys, seed 1)' in result['limitations'][0]
    else:
        assert result['limitations'][0].startswith('CLs and Asimov significances use asymptotic formulae')


@pytest.mark.parametrize('change', [
    {'cls_calculator': 'unknown'}, {'cls_toys': None}, {'cls_toys': {}},
    {'cls_toys': {'count': 100}}, {'cls_toys': {'count': 0, 'seed': 1}},
    {'cls_toys': {'count': 100, 'seed': True}},
    {'cls_toys': {'count': 100, 'seed': 1, 'unknown': 2}},
    {'cls_calculator': 'asymptotic'},
])
def test_search_rejects_invalid_cls_configuration(change):
    document = search_document()
    document.update(change)
    with pytest.raises(ValueError):
        search.SearchModel(document)


def assert_scaled(a, b, factor=.5):
    if isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b)
        for left, right in zip(a, b):
            assert_scaled(left, right, factor)
    elif a is None:
        assert b is None
    else:
        assert b == pytest.approx(a * factor)


def assert_scaled_result(original, scaled):
    for key in ('obs_limit', 'exp_limits', 'scan_mu', 'limit_brackets', 'limit_mc_interval'):
        if isinstance(original[key], dict):
            for kind in original[key]:
                assert_scaled(original[key][kind], scaled[key][kind])
        else:
            assert_scaled(original[key], scaled[key])
    assert original['limit_status'] == scaled['limit_status']
    for key in ('scan_cls_obs', 'scan_cls_exp'):
        np.testing.assert_array_equal(original[key], scaled[key])
    for key in ('toy_scan', 'asymptotic_reference'):
        assert_scaled(original[key]['scan_mu'], scaled[key]['scan_mu'])
        for field in ('scan_cls_obs', 'scan_cls_exp'):
            np.testing.assert_array_equal(original[key][field], scaled[key][field])
    ref_a, ref_b = original['asymptotic_reference'], scaled['asymptotic_reference']
    for field in ('obs_limit', 'exp_limits'):
        assert_scaled(ref_a[field], ref_b[field])
    for kind in ('observed', 'expected'):
        assert_scaled(ref_a['limit_brackets'][kind], ref_b['limit_brackets'][kind])
    for a, b in zip((read_limits(original).observed, *read_limits(original).expected),
                    (read_limits(scaled).observed, *read_limits(scaled).expected)):
        assert_scaled(a.value, b.value)
        assert_scaled(list(a.bracket), list(b.bracket))
        assert a.status == b.status
    for key in ('computed_checks', 'computed_check_summary'):
        assert key in original and key in scaled


def test_counting_cli_toys_selects_best_sr_and_scales_all_coordinates(tmp_path, monkeypatch, robust_backend):
    # Scaling does not need an additional floating background nuisance; the
    # real-toy and search cases above retain that nuisance at nonzero width.
    strong = dict(name='A', n=2, b=2, db=0, s=6)
    weak = dict(name='B', n=2, b=2, db=0, s=1)
    monkeypatch.setattr(exclude, 'plot', lambda *args, **kwargs: None)
    def run(rows, scale, suffix):
        path = tmp_path / f'counts-{suffix}.json'
        path.write_text(json.dumps(rows))
        out = tmp_path / suffix
        monkeypatch.setattr(sys, 'argv', ['pyhf_exclude', 'counting', '--srs', str(path),
            '--out', str(out), '--cls-calculator', 'toybased', '--toys', '100',
            '--toy-seed', '3', '--toy-max-fits', '200000', '--sigma-scale', str(scale)])
        exclude.main()
        return json.loads((out / 'exclusion.json').read_text())
    original = run([strong, weak], 1, 'unscaled')
    scaled = run([weak, strong], 2, 'scaled')
    assert original['best_sr'] == scaled['best_sr'] == 'A'
    assert original['asymptotic_reference']['obs_limit'] == original['per_sr']['A']['obs_limit']
    assert scaled['asymptotic_reference']['obs_limit'] == scaled['per_sr']['A']['obs_limit']
    assert original['per_sr']['A']['exp_median'] < original['per_sr']['B']['exp_median']
    assert original['calculator']['applied'] == scaled['calculator']['applied'] == 'toybased'
    assert_scaled_result(original, scaled)
    for name in ('A', 'B'):
        a, b = original['per_sr'][name], scaled['per_sr'][name]
        assert a['calculator_policy']['applied'] == b['calculator_policy']['applied'] == 'toybased'
        assert 'calculator' not in a and 'calculator' not in b
        for key in ('obs_limit', 'exp_limits', 'exp_median'):
            assert_scaled(a[key], b[key])
        for key in ('limit_brackets',):
            for kind in ('observed', 'expected'):
                assert_scaled(a[key][kind], b[key][kind])
        assert read_limits(a).observed.value == a['obs_limit']
        assert read_limits(b).observed.value == b['obs_limit']
        assert b['s'] == 2 * a['s']
