"""Inference science modes: registration, input inventory, delivered records and figures."""
import json
import math

import numpy as np
import pytest

from ravel.physics.inference import MODES, record
from ravel.workflow import science


def save(path, value):
    path.write_text(json.dumps(value))
    return path


def policy():
    return {'schema_version': 1, 'policy': {
        'schema_version': 1, 'actors': {'proposer': 'p', 'executor': 'e', 'physics_critic': 'c',
                                        'skeptical_verifier': 'v', 'physics_decider': 'd'},
        'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
        'required_checks': [{'id': 'integrity', 'kind': 'integrity'}, {'id': 'statistic', 'kind': 'scientific'}],
        'claim_scopes': {'inference_delivery': {'checks': ['integrity', 'statistic'], 'actions': ['delivery', 'reuse']}}},
        'correction_contract': {'task_fields': [], 'input_slots': []}}


def spec_for(mode, document):
    return {'schema_version': 2, 'mode': mode, 'source': 'Synthetic control values; no physics source',
            'assumptions': ['All numbers are synthetic test values'], 'max_seconds': 60, 'max_attempts': 1,
            'approval_mode': 'scripted_yes', 'task': {'input': str(document)}, 'review_policy': policy()}


def formula_doc(tmp_path):
    return save(tmp_path / 'formula.json', {
        'schema_version': 1, 'kind': 'formula-grid',
        'grid': {'axes': [{'name': 'g1', 'unit': '', 'label': 'Coupling g1', 'min': 0.0, 'max': 1.0, 'points': 21},
                          {'name': 'g2', 'unit': '', 'label': 'Coupling g2', 'min': 0.0, 'max': 1.0, 'points': 21}]},
        'program': {'constants': [{'name': 'B', 'value': 100.0, 'unit': 'events', 'origin': 'requester-assumption',
                                   'statement': 'background of 100 events'}],
                    'definitions': [{'name': 'S', 'expression': '400 * (g1**2 + g2**2)', 'unit': 'events'}],
                    'outputs': [{'name': 'Sig', 'expression': '2 * (sqrt(S + B) - sqrt(B))', 'unit': '',
                                 'label': 'Significance'}]},
        'contours': [{'output': 'Sig', 'levels': [2.0], 'x': 'g1', 'y': 'g2'}]})


def test_modes_are_registered_and_require_version_two(tmp_path):
    for mode in MODES:
        assert mode in science.MODES
        spec = spec_for(mode, tmp_path / 'x.json')
        assert science.adapter(spec).__name__ == 'ravel.physics.inference.' + mode.replace('-', '_')
        assert science._new_capability(spec)


def test_capability_catalogue_resolves_the_modes():
    from ravel.workflow import capability_routing
    rows = {r['mode']: r for r in capability_routing.catalogue()['operations']}
    for mode in MODES:
        assert rows[mode]['status'] == 'source_present_not_admitted'
        assert set(rows[mode]['entrypoints']) == {'validate', 'inputs', 'run'}


def test_formula_grid_validates_inventories_and_runs(tmp_path):
    doc = formula_doc(tmp_path)
    spec = spec_for('formula-grid', doc)
    science.validate(spec)
    assert science.task_inputs(spec, tmp_path) == [doc.resolve()]
    out = tmp_path / 'out'
    result = science.adapter(spec).run(spec['task'], tmp_path, out)
    assert result['status'] == 'passed' and result['physics_validated'] is False
    inference = json.loads((out / 'inference.json').read_text())
    record.validate(inference)
    contour = next(r for r in inference['results'] if r['quantity'] == 'contour')
    # Sig = 2 => sqrt(S + 100) = 11 => S = 21: a circle of radius sqrt(21/400) in (g1, g2).
    radius = math.sqrt(21 / 400)
    points = [(p['x'], p['y']) for p in contour['series'][0]['records']]
    assert all(abs(math.hypot(x, y) - radius) < 0.01 for x, y in points)
    assert inference['requester_assumptions'][0]['statement'] == 'background of 100 events'


def test_prescribed_closed_form_is_primary_and_verbatim(tmp_path):
    base = json.loads(formula_doc(tmp_path).read_text())
    doc = save(tmp_path / 'closed.json', {
        'schema_version': 1, 'kind': 'prescribed-statistic',
        'statistic': {'kind': 'closed-form', 'verbatim': 'Sig = 2(sqrt(S+B) - sqrt(B)) = 2 contour'},
        'grid': base['grid'], 'program': base['program'], 'statistic_output': 'Sig', 'threshold': 2.0,
        'region': 'at-or-above'})
    spec = spec_for('prescribed-statistic', doc)
    science.validate(spec)
    result = science.adapter(spec).run(spec['task'], tmp_path, tmp_path / 'out')
    inference = json.loads((tmp_path / 'out/inference.json').read_text())
    assert inference['statistic']['origin'] == 'prescribed'
    assert inference['statistic']['verbatim'] == 'Sig = 2(sqrt(S+B) - sqrt(B)) = 2 contour'
    assert result['primary_results'] and result['status'] == 'passed'


def binned_doc(tmp_path, **extra):
    save(tmp_path / 'cms.json', {'n': [7.0], 'b': [6.0], 'db': [2.0]})
    doc = {'schema_version': 1, 'kind': 'prescribed-statistic',
           'statistic': {'kind': 'binned-profile',
                         'verbatim': 'Delta(-2 ln L) = 4 with per-bin Gaussian nuisances, both experiments combined'},
           'parameter': {'name': 'g', 'unit': '', 'label': 'Coupling g'},
           'domain': [0.0, None], 'scan': {'min': 0.0, 'max': 4.0, 'points': 401},
           'test_statistic': 'two-sided', 'threshold': 4.0, 'nuisance_form': 'gaussian-linear',
           'background_floor': 'nonnegative',
           'channels': [{'name': 'first', 'observed': [5, 3], 'background': [4.0, 2.0], 'background_uncertainty': [1.0, 0.5]},
                        {'name': 'second', 'observed': {'path': 'cms.json', 'format': 'json', 'key': 'n'},
                         'background': {'path': 'cms.json', 'format': 'json', 'key': 'b'},
                         'background_uncertainty': {'path': 'cms.json', 'format': 'json', 'key': 'db'}}],
           'signal': {'kind': 'power', 'reference': 1.0, 'power': 4,
                      'templates': {'first': [1.0, 0.5], 'second': [0.8]}},
           'companion': {'cls': True, 'level': 0.05}}
    doc.update(extra)
    return save(tmp_path / 'binned.json', doc)


def test_prescribed_binned_profile_with_cls_alongside(tmp_path):
    doc = binned_doc(tmp_path)
    spec = spec_for('prescribed-statistic', doc)
    science.validate(spec)
    assert set(map(str, science.task_inputs(spec, tmp_path))) == {str(doc.resolve()), str((tmp_path / 'cms.json').resolve())}
    result = science.adapter(spec).run(spec['task'], tmp_path, tmp_path / 'out')
    inference = json.loads((tmp_path / 'out/inference.json').read_text())
    primary = [r for r in inference['results'] if r['role'] == 'primary']
    assert [r['quantity'] for r in primary] == ['delta-nll-region']
    high = primary[0]['intervals'][0]['high']
    assert high['status'] == 'resolved' and high['statistic_at_value'] == pytest.approx(4.0, abs=1e-6)
    cls = next(r for r in inference['results'] if r['quantity'] == 'cls-limit')
    assert cls['role'] == 'companion' and cls['status'] == 'computed' and cls['parameter_limit']['observed'] > 0
    assert any(line.startswith('Primary:') for line in result['summary'])


def test_morphing_mode_feeds_a_polynomial_signal(tmp_path):
    morph_doc = save(tmp_path / 'morph-input.json', {
        'schema_version': 1, 'kind': 'coupling-morphing',
        'parameters': [{'name': 'g', 'unit': '', 'label': 'Coupling g'}],
        'quantity': {'name': 'yield', 'unit': 'events', 'label': 'Signal yield'},
        'basis': [{'g': 2}, {'g': 4}], 'method': 'exact', 'max_condition': 1e6,
        'runs': [{'id': 'a', 'point': {'g': 1.0}, 'values': [0.5, -0.2], 'uncertainties': [0.01, 0.01]},
                 {'id': 'b', 'point': {'g': 2.0}, 'values': [4.0, 0.8], 'uncertainties': [0.02, 0.02]}],
        'holdout': [{'id': 'h', 'point': {'g': 1.5}, 'values': [1.59375, -0.075],
                     'uncertainties': [0.02, 0.02]}],
        'closure_tolerance_sigma': 3,
        'width': {'treatment': 'not-applicable', 'reason': 'synthetic yields without a resonance'},
        'evaluate': {'axes': [{'name': 'g', 'unit': '', 'min': 0.0, 'max': 2.0, 'points': 5}]}})
    spec = spec_for('coupling-morphing', morph_doc)
    science.validate(spec)
    out = tmp_path / 'morph-out'
    assert science.adapter(spec).run(spec['task'], tmp_path, out)['status'] == 'passed'
    morph = json.loads((out / 'coupling-morph.json').read_text())
    assert morph['kind'] == 'coupling-morph' and len(morph['coefficients']) == 2
    doc = binned_doc(tmp_path, signal={'kind': 'polynomial', 'morphs': {
        'first': {'path': 'morph-out/coupling-morph.json'}, 'second': {'path': 'second-morph.json'}}},
        companion={})
    save(tmp_path / 'second-morph.json', {**morph, 'coefficients': [[0.3], [0.1]], 'covariance': None})
    spec = spec_for('prescribed-statistic', doc)
    science.validate(spec)
    result = science.adapter(spec).run(spec['task'], tmp_path, tmp_path / 'poly-out')
    assert result['status'] in ('passed', 'failed')
    inference = json.loads((tmp_path / 'poly-out/inference.json').read_text())
    assert inference['statistic']['definition']['signal'] == ['declared coupling polynomial per bin']


def test_search_statistics_mode_with_file_yields(tmp_path):
    save(tmp_path / 'bkg-sr.json', {'schema_version': 1, 'kind': 'binned_values', 'axes': [{'name': 'x', 'unit': 'GeV'}],
                                    'unit': 'events', 'representation': 'integrated',
                                    'bins': [{'low': [0], 'high': [1], 'value': 10.0, 'sumw2': 4.0}]})
    doc = save(tmp_path / 'search.json', {
        'schema_version': 1, 'kind': 'search-statistics',
        'statistic': {'origin': 'prescribed', 'verbatim': 'expected discovery significance', 'primary': 'discovery'},
        'regions': [{'name': 'SR', 'role': 'SR', 'observed': None}],
        'backgrounds': [{'name': 'bkg', 'normfactor': None, 'yields': {'SR': {'path': 'bkg-sr.json', 'format': 'binned-values'}}}],
        'signal_points': [{'id': 'p', 'coordinates': {'m': 1.0}, 'yields': {'SR': {'values': [5.0], 'sumw2': [0.0]}}}],
        'mc_statistics': 'shapesys', 'systematics': None, 'data': {'mode': 'mc-pseudo-data', 'injections': {}},
        'computations': {'discovery': True, 'cls_at_nominal': True, 'cls_limits': False, 'background_only_fit': False},
        'asimov_source': 'nominal', 'cls_level': 0.05,
        'mc_adequacy': {'max_relative_uncertainty': 0.5, 'min_effective_entries': 1}, 'contours': None})
    spec = spec_for('search-statistics', doc)
    science.validate(spec)
    assert len(science.task_inputs(spec, tmp_path)) == 2
    science.adapter(spec).run(spec['task'], tmp_path, tmp_path / 'out')
    inference = json.loads((tmp_path / 'out/inference.json').read_text())
    sig = next(r for r in inference['results'] if r['quantity'] == 'significance')
    s, b, sigma = 5.0, 10.0, 2.0
    term1 = (s + b) * math.log((s + b) * (b + sigma ** 2) / (b ** 2 + (s + b) * sigma ** 2))
    term2 = b ** 2 / sigma ** 2 * math.log(1 + sigma ** 2 * s / (b * (b + sigma ** 2)))
    assert sig['role'] == 'primary' and sig['expected_significance'] == pytest.approx(math.sqrt(2 * (term1 - term2)), rel=2e-4)
    assert next(r for r in inference['results'] if r['quantity'] == 'cls-values')['role'] == 'companion'


def differential_doc(tmp_path, **extra):
    ref = [10.0, 6.0, 3.0]
    doc = {'schema_version': 1, 'kind': 'differential-likelihood',
           'statistic': {'verbatim': '95% CL interval from Delta chi2 = 3.84', 'test_statistic': 'two-sided',
                         'threshold': 3.84, 'objective': 'chi2'},
           'observable': {'name': 'mass', 'unit': 'GeV', 'label': 'Invariant mass'},
           'measurement': {'values': [10.2, 5.9, 3.1], 'unit': 'fb/GeV', 'bin_edges': [100, 200, 300, 400]},
           'reference': {'values': ref, 'description': 'synthetic reference prediction'},
           'signal': {'convention': 'difference-to-reference', 'difference_reference': 'synthetic reference',
                      'parameters': [{'name': 'kappa', 'unit': '', 'label': 'Coupling modifier'}],
                      'terms': [{'powers': {'kappa': 2}, 'values': [-1.0, -0.4, -0.1], 'kind': 'interference'},
                                {'powers': {'kappa': 4}, 'values': [0.5, 0.2, 0.05], 'kind': 'pure-signal'}]},
           'covariance': [{'name': 'systematic', 'law': 'ratio', 'matrix': [[1, 0.2, 0], [0.2, 0.5, 0.1], [0, 0.1, 0.3]]},
                          {'name': 'statistical', 'law': 'sqrt-ratio', 'matrix': [[0.5, 0, 0], [0, 0.4, 0], [0, 0, 0.3]]}],
           'scan': {'parameter': 'kappa', 'min': 0.0, 'max': 3.0, 'points': 151}, 'domain': [0.0, None],
           'applicability': {'unfolding': {'max_relative_deviation': 0.5, 'citation': 'synthetic stress test'}}}
    doc.update(extra)
    return save(tmp_path / 'differential.json', doc)


def test_differential_mode_reports_region_guard_and_traps(tmp_path):
    doc = differential_doc(tmp_path)
    spec = spec_for('differential-likelihood', doc)
    science.validate(spec)
    result = science.adapter(spec).run(spec['task'], tmp_path, tmp_path / 'out')
    inference = json.loads((tmp_path / 'out/inference.json').read_text())
    region = next(r for r in inference['results'] if r['quantity'] == 'delta-nll-region')
    assert region['role'] == 'primary' and region['status'] in ('resolved', 'unresolved')
    assert any(r['quantity'] == 'applicability' for r in inference['results'])
    assert {t['id'] for t in inference['diagnostics']['interpretation_traps']} >= {'landau-yang'}
    assert result['physics_validated'] is False


def test_differential_mode_refuses_reference_double_counting(tmp_path):
    raw = json.loads(differential_doc(tmp_path).read_text())
    raw['signal']['convention'] = 'absolute-prediction'
    doc = save(tmp_path / 'absolute.json', raw)
    with pytest.raises(ValueError, match='difference-to-reference'):
        science.validate(spec_for('differential-likelihood', doc)) or science.task_inputs(
            spec_for('differential-likelihood', doc), tmp_path)


def test_differential_default_statistic_requires_toy_cls(tmp_path):
    raw = json.loads(differential_doc(tmp_path).read_text())
    del raw['statistic']['verbatim']
    doc = save(tmp_path / 'default.json', raw)
    with pytest.raises(ValueError, match='CLs'):
        science.task_inputs(spec_for('differential-likelihood', doc), tmp_path)
    raw['statistic']['toys'] = {'n': 50, 'seed': 3, 'method': 'cls', 'points': [0.5, 2.5], 'confidence_level': 0.95,
                                'null': 0.0}
    doc = save(tmp_path / 'default.json', raw)
    spec = spec_for('differential-likelihood', doc)
    science.adapter(spec).run(spec['task'], tmp_path, tmp_path / 'out')
    inference = json.loads((tmp_path / 'out/inference.json').read_text())
    assert inference['statistic']['origin'] == 'default'
    assert next(r for r in inference['results'] if r['quantity'] == 'toy-p-values')['role'] == 'primary'


def test_worker_writes_common_records_and_figures(tmp_path, monkeypatch):
    from ravel.physics import science_worker as worker
    doc = binned_doc(tmp_path, companion={})
    spec = spec_for('prescribed-statistic', doc)
    rd = tmp_path / 'study'; rd.mkdir()
    monkeypatch.setattr(worker, 'verify_worker', lambda _: {'attempt': 1, 'base_dir': str(tmp_path),
                        'output_directory': 'outputs/attempt-1', 'stage_binding': {'input_snapshot': {}}})
    monkeypatch.setattr(worker, 'execution_spec', lambda _: spec)
    assert worker.main([str(rd)]) == 0
    out = rd / 'outputs/attempt-1'
    assert json.loads((out / 'inference.json').read_text())['mode'] == 'prescribed-statistic'
    figures = json.loads((out / 'figures.json').read_text())
    assert figures['status'] == 'passed' and figures['figures']
    for figure in figures['figures']:
        for name in figure['files']:
            assert (out / name).is_file()
    checkin = json.loads((out / 'checkin2.json').read_text())
    assert 'Primary:' in checkin['sections']['waypoint']['primary'][0]
    assert 'Primary:' in (out / 'RESULT.md').read_text()


def test_mode_descriptor_entries_are_complete_and_neutral():
    import re
    from ravel.paths import package_data_path
    # The inference modes are described in the central file that capability routing reads.
    central = json.loads(package_data_path('mode_descriptors.json').read_text())
    assert set(MODES) <= set(central['modes'])
    assert not package_data_path('inference', 'mode_descriptors.json').exists()
    doc = {'modes': {mode: central['modes'][mode] for mode in MODES}}
    fields = ('summary', 'operations', 'tools', 'inputs', 'observables', 'outputs', 'context')
    for row in doc['modes'].values():
        assert tuple(sorted(row)) == tuple(sorted((*fields, 'applicability'))) and row['summary'].strip()
        assert row['applicability'] == {'scope': 'general'}
        for key in fields[1:]:
            for term in row[key]:
                assert term.strip()
                if term.startswith('re:'):
                    re.compile(term[3:])
    vocabulary = json.dumps(doc).lower()
    for identity in ('mapyde', 'challenge'):
        assert identity not in vocabulary
    from ravel.validation import check_generality
    assert not check_generality.load_denylist(None, env={}).hits(vocabulary)
