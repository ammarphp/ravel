"""Synthetic search evidence, uncertainty and retained-output validity regression."""
from copy import deepcopy
import json

import pytest

from method_decision_fixture import admit_method
from test_inference_modes import save, spec_for
from ravel.physics.inference import search, search_statistics, situations, uncertainty
from ravel.validation import regression_triggers as rt
from ravel.workflow import science


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



def counting(s=5.0, b=20.0, sumw2=0.0):
    return {'regions': [{'name': 'SR', 'role': 'SR', 'observed': None}],
            'backgrounds': [{'name': 'bkg', 'normfactor': None,
                             'yields': {'SR': {'values': [b], 'sumw2': [sumw2]}}}],
            'signal_points': [{'id': 'p', 'coordinates': {'m': 1.0},
                               'yields': {'SR': {'values': [s], 'sumw2': [0.0]}}}],
            'mc_statistics': 'none', 'systematics': None,
            'data': {'mode': 'mc-pseudo-data', 'injections': {}},
            'computations': {'discovery': True, 'cls_at_nominal': False,
                             'cls_limits': True, 'background_only_fit': False},
            'asimov_source': 'nominal', 'cls_level': 0.05,
            'mc_adequacy': {'max_relative_uncertainty': 0.3, 'min_effective_entries': 10},
            'contours': None}


def document(tmp_path, body, statistic=None):
    return save(tmp_path / 'search.json', {
        'schema_version': 1, 'kind': 'search-statistics',
        'statistic': statistic or {'origin': 'default'}, **body})


def choice(block, situation):
    return next(row for row in block['decision']['choices'] if row['situation'] == situation)


def check(block, identifier):
    return next(row for row in block['validity']['checks'] if row['check'] == identifier)


def diagnostic(block, hypothesis='p'):
    return {'quantity': 'statistics', 'role': 'diagnostic', 'hypothesis': hypothesis,
            'record': block, 'outcome': block['validity']['outcome'],
            'labels': situations.labels(block)}


def inference(*rows):
    return {'schema_version': 1, 'kind': 'inference', 'results': list(rows)}


def validity_checks(doc):
    return [row for row in rt.evaluate(doc) if row['trigger'] == 'statistics-validity']


@pytest.fixture(scope='module')
def control_result():
    body = control_fixture()
    body['systematics'] = {'schema_version': 1, 'sources': [
        {'name': 'lumi', 'kind': 'normsys', 'relative': 0.02,
         'applies_to': {'samples': ['top', 'wjets'], 'regions': 'all'},
         'correlation': 'correlated', 'origin': 'cited', 'citation': 'synthetic control'}],
        'absent': [{'component': 'signal uncertainties', 'reason': 'synthetic control omits these'}]}
    return search.run(body)


def test_control_records_executed_injections_mc_moments_and_uncertainty(control_result):
    point = control_result['points'][0]
    block = point['statistics']
    assert situations.audit(block) == []
    assert block['validity']['outcome'] == 'valid'
    assert choice(block, 'model-validation')['method'] == 'signal-injection'
    assert check(block, 'signal-injection')['status'] == 'pass'
    strengths = [row['injected'] for row in block['evidence']['injection']]
    assert strengths == pytest.approx(sorted({1.0, point['cls_limits']['expected']['values'][2]}))
    sr = sorted((row for row in block['facts']['bins'] if row['channel'] == 'SR'), key=lambda row: row['bin'])
    assert [row['mc']['sumw'] for row in sr] == pytest.approx([16.0, 6.0])
    assert [row['mc']['sumw2'] for row in sr] == pytest.approx([1.8, 0.8])
    source, = block['facts']['systematics']
    assert source['name'] == 'lumi' and source['correlation'] == 'correlated'
    assert set(source['regions']) == {'SR', 'CRtop', 'CRw', 'VR'}
    assert {row['role'] for row in block['facts']['bins']} == {'SR', 'CR', 'VR'}
    assert 'lumi' in block['evidence']['pulls']
    assert point['cls_limits']['observed'] is None
    assert block['evidence']['limits']['observed'] == 'missing'
    statement = point['cls_limits']['uncertainty']
    assert uncertainty.statement_errors(statement) == []
    assert statement['values']['observed'] is None
    impact = next(row for row in statement['components'] if row['name'] == 'systematic-impact')
    assert impact['status'] == 'evaluated' and impact['fixed_parameters']
    assert any('MC statistical uncertainty' in row for row in statement['included'])
    assert {'component': 'signal uncertainties', 'reason': 'synthetic control omits these'} in statement['not_included']


def test_small_count_auto_calculator_records_the_actual_toy_evidence():
    body = counting(s=2.0, b=3.0)
    body.update(cls_calculator='auto', cls_toys={'count': 100, 'seed': 1})
    point = search.run(body)['points'][0]
    block = point['statistics']
    assert situations.audit(block) == []
    assert choice(block, 'low-counts')['method'] == 'toy-cls'
    assert point['cls_limits']['calculator']['applied'] == 'toybased'
    assert block['evidence']['toys']['status'] == 'run'
    assert block['evidence']['toys']['median'] == point['cls_limits']['expected']['values'][2]
    assert check(block, 'toy-mc-precision')['status'] in ('pass', 'fail')
    assert check(block, 'limits-resolved')['status'] in ('pass', 'fail')
    assert block['validity'] == situations.verify(block['facts'], block['decision'], block['evidence'])
    assert block['validity']['outcome'] in ('valid', 'qualified')


def situations_of(block):
    return {row['situation'] for row in block['assessment']['situations']}


def test_small_count_discovery_escalates_to_declared_toys_or_qualifies():
    body = counting(s=2.0, b=3.0)
    body['computations']['cls_limits'] = False
    without = search.run(body)['points'][0]['statistics']
    assert situations.audit(without) == []
    assert 'low-count-significance' in situations_of(without) and 'low-counts' not in situations_of(without)
    refused = next(row for row in situations.assess(without['facts'], availability={
        'toy-significance': {'available': False, 'reason': 'budget: the document declares no discovery toys'}})[
        'situations'] if row['situation'] == 'low-count-significance')
    assert refused['default'] is None
    assert choice(without, 'low-count-significance')['origin'] == 'fallback'
    assert without['evidence']['budget_refusals'] == [
        {'method': 'toy-significance', 'status': 'not_run', 'reason': 'budget', 'bound': 'undeclared'}]
    assert check(without, 'significance-evaluated')['status'] == 'pass'
    assert situations.situation('low-count-significance').fallback['qualification'] in situations.labels(without)
    assert without['validity']['outcome'] == 'qualified'

    body['toys'] = {'count': 400, 'seed': 3}
    point = search.run(body)['points'][0]
    block = point['statistics']
    assert situations.audit(block) == []
    selected = choice(block, 'low-count-significance')
    assert selected['method'] == 'toy-significance' and selected['origin'] == 'escalation'
    assert 'budget_refusals' not in block['evidence']
    assert block['evidence']['discovery_toys'] == point['discovery']['toys']
    tail = check(block, 'toy-tail-resolved')
    assert tail['status'] in ('pass', 'fail')
    assert block['validity']['outcome'] == ('valid' if tail['status'] == 'pass' else 'qualified')


def test_undeclared_cls_toys_qualify_a_small_count_limit():
    block = search.run(counting(s=2.0, b=3.0))['points'][0]['statistics']
    assert situations.audit(block) == []
    toys = next(row for s in block['assessment']['situations'] if s['situation'] == 'low-counts'
                for row in s['methods'] if row['method'] == 'toy-cls')
    assert toys['available'] is False and toys['unavailable_reason'].startswith('budget')
    assert choice(block, 'low-counts')['origin'] == 'fallback'
    assert situations.CHECKS['asymptotic-regime'].qualification in situations.labels(block)
    assert block['validity']['outcome'] == 'qualified'
    body = counting(s=2.0, b=3.0)
    body['cls_calculator'] = 'asymptotic'
    stated = search.run(body)['points'][0]['statistics']
    assert choice(stated, 'low-counts')['seat'] is True
    assert stated['validity']['outcome'] == 'qualified' and situations.audit(stated) == []


def test_validation_region_failure_qualifies_without_refitting_control_regions(tmp_path):
    body = control_fixture(injections={'bkg': 10.0})
    body['backgrounds'].append({'name': 'bkg', 'normfactor': None,
                                'yields': {'VR': {'values': [100.0], 'sumw2': [1.0]}}})
    body['statistics_choices'] = {'model-validation': {
        'method': 'validation-region-closure', 'justification': 'synthetic held-out closure control'}}
    source = document(tmp_path, body)
    search_statistics.run({'input': str(source)}, tmp_path, tmp_path / 'out')
    result = json.loads((tmp_path / 'out/inference.json').read_text())
    fit = next(row for row in result['results'] if row['quantity'] == 'fitted-parameters')
    assert set(fit['fit_channels']) == {'CRtop', 'CRw'}
    values = {row['name']: row['value'] for row in fit['parameters']}
    assert values['mu_top'] == pytest.approx(1.0, abs=1e-3)
    assert values['mu_w'] == pytest.approx(1.0, abs=1e-3)
    row = next(row for row in result['results'] if row['quantity'] == 'statistics')
    block = row['record']
    assert situations.audit(block) == []
    assert check(block, 'validation-closure')['status'] == 'fail'
    assert block['validity']['outcome'] == 'qualified'
    assert [row['status'] for row in validity_checks(inference(diagnostic(block)))] == ['warn']
    assert [row['status'] for row in validity_checks(result)] == ['warn']
    assert all(result['limitations'].count(label) == 1 for label in situations.labels(block))
    limits = next(row for row in result['results'] if row['quantity'] == 'cls-limit')
    assert uncertainty.statement_errors(limits['uncertainty']) == []


def test_adapter_records_one_global_scan_decision(tmp_path):
    body = counting()
    body['computations']['cls_limits'] = False
    body['signal_points'] = [
        {'id': str(i), 'coordinates': {'m': float(i)},
         'yields': {'SR': {'values': [s], 'sumw2': [0.0]}}}
        for i, s in enumerate((0.5, 5.0, 8.0))]
    source = document(tmp_path, body, {'origin': 'prescribed', 'primary': 'discovery',
                                     'verbatim': 'expected discovery significance', 'claim': 'global'})
    search_statistics.run({'input': str(source)}, tmp_path, tmp_path / 'out')
    doc = json.loads((tmp_path / 'out/inference.json').read_text())
    rows = [row for row in doc['results'] if row['quantity'] == 'statistics']
    assert len(rows) == 4
    scan, = [row for row in rows if row['hypothesis'] is None]
    block = scan['record']
    assert situations.audit(block) == []
    assert choice(block, 'look-elsewhere')['method'] == 'trials-factor'
    assert check(block, 'upcrossings-observed')['status'] == 'pass'
    assert block['evidence']['look_elsewhere']['reference_level'] == 0.5
    assert block['evidence']['look_elsewhere']['upcrossings'] == 1
    assert all(row['role'] == 'diagnostic' for row in rows)


def test_missing_mc_treatment_qualifies_the_limit():
    point = search.run(counting(sumw2=36.0))['points'][0]
    block = point['statistics']
    assert situations.audit(block) == []
    assert choice(block, 'limited-mc-statistics')['method'] == 'mc-staterror'
    assert check(block, 'mc-statistics-modelled')['status'] == 'fail'
    assert block['validity']['outcome'] == 'qualified'


@pytest.mark.parametrize('method', ['fallback', 'signal-injection'])
def test_load_admits_justified_seat_choices(tmp_path, method):
    body = counting()
    body['statistics_choices'] = {'model-validation': {
        'method': method, 'justification': 'synthetic choice exercises admission'}}
    source = document(tmp_path, body)
    _, _, loaded = search_statistics.load({'input': str(source)}, tmp_path)
    assert loaded['statistics_choices'] == body['statistics_choices']
    block = search.run(loaded)['points'][0]['statistics']
    assert situations.audit(block) == []
    selected = choice(block, 'model-validation')
    assert selected['seat'] is True
    assert selected['origin'] == ('fallback' if method == 'fallback' else 'seat')
    assert block['validity']['outcome'] == ('qualified' if method == 'fallback' else 'valid')


@pytest.mark.parametrize('choices,match', [
    ({'combination': {'method': 'fallback', 'justification': 'synthetic control'}}, 'not detected'),
    ({'model-validation': {'method': 'signal-injection', 'justification': ''}}, 'justification'),
    ({'model-validation': None}, 'justification'),
    ({'model-validation': {'method': 'trials-factor', 'justification': 'synthetic control'}}, 'not a method'),
    ([], 'must be an object')])
def test_load_refuses_undetected_and_malformed_choices(tmp_path, choices, match):
    body = counting()
    body['statistics_choices'] = choices
    source = document(tmp_path, body)
    with pytest.raises(ValueError, match=match):
        search_statistics.load({'input': str(source)}, tmp_path)


@pytest.mark.parametrize('statistic,match', [
    ({'origin': 'default', 'claim': 'unknown'}, 'claim'),
    ({'origin': 'default', 'independent_tests': 1}, 'boolean')])
def test_load_refuses_bad_scan_claims(tmp_path, statistic, match):
    source = document(tmp_path, counting(), statistic)
    with pytest.raises(ValueError, match=match):
        search_statistics.load({'input': str(source)}, tmp_path)


def test_trigger_audits_valid_held_qualified_and_absent_records(tmp_path):
    # Only cheap inference runs: the toy ensemble is confined to the small-count test.
    original = search.run(counting())['points'][0]['statistics']
    assert original['validity']['outcome'] == 'valid'
    assert [row['status'] for row in validity_checks(inference(diagnostic(original)))] == ['pass']
    evidence = deepcopy(original['evidence'])
    evidence.pop('injection')
    held = situations.record(original['facts'], evidence, decision=original['decision'])
    assert held['validity']['outcome'] == 'held' and situations.audit(held) == []
    assert [row['status'] for row in validity_checks(inference(diagnostic(held)))] == ['fail']
    qualified = situations.record(original['facts'], original['evidence'], choices={'model-validation': {
        'method': 'fallback', 'justification': 'synthetic control omits validation'}})
    assert qualified['validity']['outcome'] == 'qualified' and situations.audit(qualified) == []
    assert [row['status'] for row in validity_checks(inference(diagnostic(qualified)))] == ['warn']
    assert validity_checks(inference()) == []
    path = save(tmp_path / 'inference.json', inference(diagnostic(original)))
    checks, scanned, skipped = rt.from_outputs([path])
    assert [row['status'] for row in checks if row['trigger'] == 'statistics-validity'] == ['pass']
    assert scanned == [str(path)] and skipped == []
    tampered = json.loads(path.read_text())
    tampered['results'][0]['record']['validity']['outcome'] = 'held'
    save(path, tampered)
    checks, _, _ = rt.from_outputs([path])
    assert [row['status'] for row in checks if row['trigger'] == 'statistics-validity'] == ['fail']


@pytest.mark.parametrize('independent,outcome', [(True, 'valid'), (False, 'qualified')])
def test_scan_seat_choice_checks_independence(independent, outcome):
    points = [{'discovery': {'expected_q0': q}} for q in (0.1, 1.0, 4.0)]
    block = search_statistics._scan_statistics(
        {'claim': 'global', 'independent_tests': independent}, points,
        {'look-elsewhere': {'method': 'sidak-correction', 'justification': 'synthetic independence control'}})
    assert situations.audit(block) == []
    assert choice(block, 'look-elsewhere')['method'] == 'sidak-correction'
    assert choice(block, 'look-elsewhere')['seat'] is True
    assert check(block, 'independent-tests-declared')['status'] == ('pass' if independent else 'fail')
    assert block['validity']['outcome'] == outcome


def test_blinded_uncertainty_does_not_inherit_an_observed_only_cap():
    from ravel.limits import LimitCurve, LimitResult, attach_limits
    original = attach_limits(
        {'obs_limit': 10.0, 'exp_limits': [1., 2., 3., 4., 5.], 'quality': 'capped',
         'at_poi_cap': True, 'median_at_cap': False, 'at_mu_floor': False},
        result=LimitResult(LimitCurve(10.0, 'above_scan', (10.0, None)),
                           tuple(LimitCurve(v, 'resolved') for v in (1., 2., 3., 4., 5.))))
    statement = uncertainty.for_limits(search._reported_limits(original, False))
    assert search._limit_status(original, True) == 'unresolved'
    assert search._limit_status(original, False) == 'resolved'
    assert uncertainty.statement_errors(statement) == []
    assert statement['values']['observed'] is None
    assert statement['values']['expected_median'] == 3.0
    assert not any(row['name'] == 'observed-versus-expected' for row in statement['components'])
    assert original['at_poi_cap'] is True and original['obs_limit'] == 10.0


def test_real_science_lifecycle_retains_recomputable_statistics(tmp_path):
    body = counting()
    save(tmp_path / 'bkg-sr.json', {
        'schema_version': 1, 'kind': 'binned_values', 'axes': [{'name': 'x', 'unit': 'GeV'}],
        'unit': 'events', 'representation': 'integrated',
        'bins': [{'low': [0], 'high': [1], 'value': 20.0, 'sumw2': 0.0}]})
    body['backgrounds'][0]['yields']['SR'] = {'path': 'bkg-sr.json', 'format': 'binned-values'}
    source = document(tmp_path, body)
    spec = save(tmp_path / 'spec.json', spec_for('search-statistics', source))
    rundir = tmp_path / 'run'
    science.plan(rundir, spec)
    admit_method(rundir)
    science.approve(rundir, 'Actual authorization for this bounded synthetic worker control', scripted=True)
    code = science.run(rundir)
    assert code == 0, {'packet': science.packet(rundir),
                       'logs': {str(p.relative_to(rundir)): p.read_text(errors='replace')[-8000:]
                                for p in (rundir / 'logs').glob('*.log')}}
    path = rundir / 'outputs/attempt-1/inference.json'
    doc = json.loads(path.read_text())
    saved = [row for row in doc['computed_checks'] if row['trigger'] == 'statistics-validity']
    assert saved and all(row['computed'] is True and row['status'] == 'pass' for row in saved)
    assert saved == validity_checks(doc)
    checks, scanned, skipped = rt.from_outputs([path])
    recomputed = [{key: value for key, value in row.items() if key != 'source'}
                  for row in checks if row['trigger'] == 'statistics-validity']
    assert recomputed == saved
    assert scanned == [str(path)] and skipped == []
