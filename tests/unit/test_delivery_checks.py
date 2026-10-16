"""Synthetic delivery controls: no native tools, network or generated physics."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_normalization_ledger import ledger, exact_yields


def put(root, name, doc):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def test_delivery_recomputes_planted_yield_fault_and_writes_receipt(tmp_path):
    from ravel.validation.delivery_checks import check_delivery
    doc = ledger(delivered={'SR': [v * 1000 for v in exact_yields(ledger())['SR']]})
    pack = {'deliverables': [{'path': 'yield.json', 'absolute_yield': True,
                             'normalization_ledger': put(tmp_path, 'ledger.json', doc)}]}
    findings = check_delivery(tmp_path, pack)
    row = next(r for r in findings if r['check'] == 'normalization_ledger')
    assert row['status'] == 'fail' and row['severity'] == 'A'
    assert 'unit_swap' in row['detail']
    assert row['receipt']['sha256'] == hashlib.sha256((tmp_path / row['receipt']['path']).read_bytes()).hexdigest()
    assert json.loads((tmp_path / 'outputs/delivery-checks.json').read_text())['check_results'] == findings


def test_absolute_yield_without_ledger_is_missing_input(tmp_path):
    from ravel.validation.delivery_checks import check_delivery
    rows = check_delivery(tmp_path, {'deliverables': [{'path': 'yield.json', 'absolute_yield': True}]})
    assert any(r['status'] == 'missing_input' and r['check'] == 'normalization_ledger' for r in rows)


def test_delivery_does_not_trust_a_changed_ledger_pin(tmp_path):
    from ravel.validation.delivery_checks import check_delivery
    pin = put(tmp_path, 'ledger.json', ledger(delivered=exact_yields(ledger())))
    (tmp_path / pin['path']).write_text('{}')
    rows = check_delivery(tmp_path, {'deliverables': [{'path': 'yield.json', 'absolute_yield': True,
                                                     'normalization_ledger': pin}]})
    assert any(r['status'] == 'fail' for r in rows)


def test_every_delivery_invokes_declared_figure_comparison(tmp_path, monkeypatch):
    from ravel.validation.delivery_checks import check_delivery
    from ravel.physics import figure_comparison
    calls = []
    def compare(task, base, output):
        calls.append((task, base, output))
        return {'verdicts': {'synthetic': 'FAIL'}}
    monkeypatch.setattr(figure_comparison, 'run', compare)
    spec = put(tmp_path, 'compare.json', {'schema_version': 1})
    pack = {'deliverables': [{'path': 'curve.json', 'figure_comparison': spec}]}
    rows = check_delivery(tmp_path, pack)
    assert len(calls) == 1
    assert any(r['check'] == 'figure_comparison' and r['status'] == 'fail' for r in rows)


def test_delivery_rejects_missing_selected_region():
    from ravel.physics import normalization_ledger as nl
    assert not nl.check(ledger(), delivered={})['passed']


def test_parity_rows_localize_br_omission_and_pass_control():
    from ravel.validation.normalization_ledger import parity_rows
    doc = ledger()
    clean = parity_rows(doc, delivered=exact_yields(doc))
    assert all(r['status'] == 'pass' for r in clean)
    bad = parity_rows(doc, delivered={'SR': [v / .25 for v in exact_yields(doc)['SR']]})
    assert any(r['status'] == 'fail' and 'br_omitted' in r['causes'] for r in bad)


def moments(n=3, sumw=2., sumw2=6.):
    return {'count': n, 'sumw': sumw, 'sumw2': sumw2, 'positive': 2, 'negative': 1, 'zero': 0}


def test_event_accounting_flags_drop_despite_same_signed_sum():
    from ravel.validation.event_accounting import check
    a = moments()
    b = moments(n=2, sumw=2., sumw2=4.)
    b.update(positive=2, negative=0)
    report = check({'schema_version': 1, 'input': a, 'output': b, 'transformation': {'kind': 'identity'}})
    assert not report['passed']
    assert {'count', 'sumw2', 'negative'} <= {r['field'] for r in report['rows'] if r['status'] == 'fail'}


def test_event_accounting_declared_selection_and_negative_rescaling():
    from ravel.validation.event_accounting import check
    source = moments(n=4, sumw=4., sumw2=10.)
    source['positive'] = 3
    rejected = moments(n=1, sumw=2., sumw2=4.)
    rejected.update(positive=1, negative=0)
    output = moments(sumw=-4., sumw2=24.)
    output.update(positive=1, negative=2)
    report = check({'schema_version': 1, 'input': source, 'output': output,
                    'transformation': {'kind': 'selection-and-scale', 'weight_scale': -2., 'rejected': rejected}})
    assert report['passed']


def test_event_accounting_refuses_undeclared_transform():
    from ravel.validation.event_accounting import check
    with pytest.raises(ValueError):
        check({'schema_version': 1, 'input': moments(), 'output': moments(), 'transformation': {'kind': 'guess'}})


def test_pyhf_computed_cap_alarm_on_mocked_result(monkeypatch):
    from ravel.physics import pyhf_exclude as p
    raw = {'obs_limit': 8., 'exp_limits': [1., 2., 3., 4., 8.],
           'limit_status': {'observed': 'above_scan', 'expected': ['resolved'] * 4 + ['above_scan']},
           'at_poi_cap': True, 'median_at_cap': True, 'band_degenerate': False}
    monkeypatch.setattr(p, '_compute', lambda *a, **kw: copy.deepcopy(raw))
    result = p.compute(None, None)
    assert any(r['status'] == 'fail' and r['computed'] for r in result['computed_checks'])


def test_search_mc_adequacy_alarm_is_computed():
    from ravel.validation.regression_triggers import evaluate
    rows = evaluate({'results': [{'quantity': 'mc-adequacy', 'flags': [{'code': 'synthetic-low-effective-count',
                          'severity': 'fail', 'region': 'SR', 'detail': 'signed cancellation'}]}]})
    assert rows and rows[0]['status'] == 'fail' and rows[0]['computed']


def test_counting_calibration_retains_exact_reference_and_coverage():
    from ravel.validation.delivery_checks import counting_calibration
    report = counting_calibration({'n': 0, 'b': 0., 'db': 0., 's': 2.}, signal_strength=1.)
    assert report['reference']['value'] == pytest.approx(-__import__('math').log(.05) / 2)
    assert report['coverage']['status'] == 'resolved'
    assert report['coverage']['general_likelihood_coverage_validated'] is False


def test_uncertain_background_cannot_get_known_background_calibration():
    from ravel.validation.delivery_checks import counting_calibration
    report = counting_calibration({'n': 1, 'b': 1., 'db': .2, 's': 2.})
    assert report['status'] == 'not_applicable' and report['coverage']['status'] == 'not_evaluated'


def test_science_lhe_gate_refuses_malformed_before_shower(tmp_path, monkeypatch):
    from ravel.physics import event_production as ep
    import production_fixtures as pf
    task = pf.production_task(tmp_path)
    lhe = tmp_path / 'events.lhe'
    lhe.write_text(lhe.read_text().replace('</LesHouchesEvents>', ''))
    monkeypatch.setattr(ep, '_run_jobs', lambda *a: pytest.fail('shower reached'))
    with pytest.raises(ValueError, match='lhe_check'):
        ep.run(task, tmp_path, tmp_path / 'out')


def test_integrated_shower_guard_runs_before_original_method(tmp_path):
    from ravel.validation.lhe_check import guard_shower
    lhe = tmp_path / 'Events/ravel/unweighted_events.lhe'
    lhe.parent.mkdir(parents=True)
    lhe.write_text('<LesHouchesEvents></LesHouchesEvents>')
    reached = []
    original = lambda self, line: reached.append(line)
    guarded = guard_shower(original, process=tmp_path, run_name='ravel', output=tmp_path / 'check.json')
    with pytest.raises(ValueError, match='lhe_check'):
        guarded(SimpleNamespace(me_dir=str(tmp_path)), 'ravel')
    assert reached == []


def test_shared_binned_schema_can_reach_templates_and_refuse_normalized_merge():
    from ravel.physics.binned_values import build
    from ravel.workflow.result_templates import Result
    from ravel.workflow.partitioned_execution import merge_documents
    doc = build(axes=[{'name': 'x', 'unit': '1'}], bins=[{'low': [0], 'high': [1], 'value': 2., 'sumw2': 4.}],
                unit='events', normalization={'kind': 'absolute', 'scale': 2.}, provenance={'source': 'synthetic'})
    assert Result(json.dumps(doc)).values == [2.]
    with pytest.raises(ValueError, match='normaliz'):
        merge_documents('binned_values', [doc, doc])


def test_partition_dispatch_accepts_columnar_partial():
    from ravel.workflow.partitioned_execution import MERGE_KINDS
    assert 'columnar-partial' in MERGE_KINDS


def test_cross_section_result_pin_refuses_changed_bytes(tmp_path):
    from ravel.physics.columnar.engine import _declared_cross_section
    pin = put(tmp_path, 'cross-section.json', {'kind': 'cross-section', 'schema_version': 1})
    (tmp_path / pin['path']).write_text('{}')
    with pytest.raises(ValueError, match='pin|digest|sha256'):
        _declared_cross_section({'cross_section_result': pin}, tmp_path)


def test_dataset_member_drop_is_refused(tmp_path):
    from ravel.physics.yield_hub import load_dataset
    import root_stream_fixture as rf
    ds, *_ = rf.population(tmp_path)
    ds['samples'] = ds['samples'][:2]
    # The complete authority still includes data; caller cannot trim membership.
    pin = put(tmp_path, 'trimmed.json', ds)
    with pytest.raises(ValueError, match='membership'):
        load_dataset(pin, tmp_path)


def test_root_stream_binned_projection_preserves_off_diagonal_covariance(tmp_path):
    from ravel.physics.binned_values import from_quantity
    from ravel.workflow.result_templates import Result
    import root_stream_fixture as rf
    ds, analysis, config, *_ = rf.population(tmp_path)
    doc = rf.accumulate(ds, analysis, config['limits'], 2)
    quantity = doc['samples'][0]['quantities']['regions']
    quantity['contract']['normalization']['scale'] = 1.
    binned = from_quantity(quantity, 'nominal')
    result = Result(json.dumps(binned))
    assert result.values == quantity['values']['nominal']
    assert result.covariance == [r[:3] for r in quantity['covariance'][:3]]
    assert result.flow['separable'] is False
    from ravel.workflow.partitioned_execution import merge_documents
    with pytest.raises(ValueError, match='normaliz'):
        merge_documents('binned_values', [binned, binned])


def test_reco_writer_keeps_region_edges_and_weight_moments(tmp_path):
    from ravel.physics.yield_hub import write_regions
    pin = write_regions(tmp_path / 'regions.json', ['R0', 'R1'], {'R0': -2., 'R1': 3.}, {'R0': 4., 'R1': 5.},
                        provenance={'source': 'synthetic'})
    doc = json.loads((tmp_path / 'regions.json').read_text())
    assert doc['quantity'] == {'weight_convention': 'signed'}
    assert doc['normalization']['kind'] == 'unnormalized'
    assert [b['value'] for b in doc['bins']] == [-2., 3.]
    assert doc['sumw2'] == [4., 5.]
    assert pin['sha256'] == hashlib.sha256((tmp_path / 'regions.json').read_bytes()).hexdigest()


def test_columnar_event_drop_fails_before_finalization(tmp_path):
    from columnar_fixtures import RECIPE, random_events, write_delphes
    from test_columnar_engine import plan_for, whole
    from ravel.physics.columnar import engine
    path = write_delphes(tmp_path / 'events.root', random_events(8, seed=19))
    plan = plan_for(RECIPE, tmp_path)
    partial = whole(path, plan)
    partial['variations']['nominal']['events']['n'] -= 1
    with pytest.raises(ValueError, match='event_accounting'):
        engine.finalize(partial, plan, {'mode': 'none'}, out_dir=tmp_path / 'out')


def test_real_fidelity_comparator_passes_clean_and_fails_fault(tmp_path):
    from ravel.validation.delivery_checks import check_delivery
    put(tmp_path, 'reference.json', {'edges': [0, 1, 2], 'values': [2., 4.], 'errors': [.1, .1], 'quantity': 'value', 'unit': 'events'})
    for index, factor in enumerate((1., 10.)):
        put(tmp_path, 'prediction.json', {'edges': [0, 1, 2], 'values': [2.*factor, 4.*factor], 'errors': [.1, .1], 'quantity': 'value', 'unit': 'events'})
        basis = {'kind': 'published_precision', 'source': 'synthetic tolerance control'}
        put(tmp_path, 'comparison.json', {'schema_version': 1, 'kind': 'binned', 'agent': {'path': 'prediction.json'},
            'reference': {'path': 'reference.json'}, 'tolerances': {'delta_norm': {'pass': .01, 'warn': .02, 'basis': basis}}})
        task = put(tmp_path, 'comparison-task.json', {'operations': [{'name': 'parity', 'kind': 'compare', 'specification': 'comparison.json'}]})
        rows = check_delivery(tmp_path, {'deliverables': [{'path': 'prediction.json', 'figure_comparison': task}]})
        assert next(r for r in rows if r['check'] == 'figure_comparison')['status'] == ('pass' if index == 0 else 'fail')


def test_source_bound_integrated_guard_preserves_clean_original_call(tmp_path):
    from ravel.validation import science_shower_guard, lhe_check
    import production_fixtures as pf
    path = tmp_path / 'Events/ravel/unweighted_events.lhe'
    path.parent.mkdir(parents=True)
    pf.write_lhe(path, n=2)
    called = []
    class Native:
        def do_pythia8(self, line):
            called.append(line)
            return 19
    c = {'api': {'method': 'do_pythia8'}, 'process': str(tmp_path), 'output': str(tmp_path/'check.json'), 'parameter_card': None}
    science_shower_guard.install(Native, c, lhe_check)
    instance = Native(); instance.me_dir = str(tmp_path)
    assert instance.do_pythia8('ravel') == 19 and called == ['ravel']
    path.write_text(path.read_text().replace('</LesHouchesEvents>', ''))
    with pytest.raises(ValueError, match='lhe_check'):
        instance.do_pythia8('ravel')
    assert called == ['ravel']


def test_pinned_cross_section_delivery_recomputes_columnar_yields(tmp_path):
    from columnar_fixtures import RECIPE, random_events, write_delphes
    from test_columnar_engine import plan_for, whole
    from ravel.physics.columnar import engine
    path = write_delphes(tmp_path / 'events.root', random_events(12, seed=7))
    plan = plan_for(RECIPE, tmp_path)
    pin = put(tmp_path, 'cross-section.json', {'schema_version': 1, 'kind': 'cross-section', 'status': 'passed',
        'cross_section': {'sigma_pb': .5, 'basis': 'synthetic production', 'convention': {'order': 'LO', 'pdf': 'synthetic PDF', 'scale': 'synthetic scale'},
                          'source': {'kind': 'synthetic source'}}})
    result = engine.finalize(whole(path, plan), plan, {'mode': 'cross-section', 'cross_section_pb': {'cross_section_result': pin},
        'cross_section_source': 'pinned synthetic calculation', 'luminosity_ifb': 1., 'luminosity_source': 'synthetic luminosity',
        'sum_of_weights': 'all-input-events'}, out_dir=tmp_path/'out', base=tmp_path)
    findings = result['check_results']
    assert next(r for r in findings if r['check'] == 'normalization_ledger')['status'] == 'pass'
    assert result['normalization']['cross_section_from']['convention']['order'] == 'LO'


def test_mocked_remote_dataset_uses_original_per_sample_denominators(tmp_path, monkeypatch):
    from columnar_fixtures import RECIPE, random_events, write_delphes
    from ravel.physics import columnar_analysis
    import root_stream_fixture as rf
    import uproot
    ds, *_ = rf.population(tmp_path)
    ds['samples'] = ds['samples'][:2]
    remote_files = {}
    for index, sample in enumerate(ds['samples']):
        member = sample['members'][0]
        real = write_delphes(tmp_path / f'sample-{index}.root', random_events(member['entries'], seed=10+index))
        uri = f'root://synthetic.invalid//sample-{index}.root'
        member.update(uri=uri, tree='Delphes', size_bytes=real.stat().st_size)
        member['checksum'].update(value=hashlib.sha256(real.read_bytes()).hexdigest())
        remote_files[uri] = real
    ds['membership_authority'] = rf.put(tmp_path, 'new-members.json', {'schema_version': 1, 'samples': ds['samples']})
    pin = rf.put(tmp_path, 'mc-dataset.json', ds)
    put(tmp_path, 'recipe.json', RECIPE)
    original = uproot.open
    monkeypatch.setattr(uproot, 'open', lambda path, *a, **kw: original(remote_files.get(str(path), path), *a, **kw))
    task = {'recipe': 'recipe.json', 'format': 'delphes', 'inputs': {'dataset': pin}, 'normalization': {'mode': 'dataset'}}
    result = columnar_analysis.run(task, tmp_path, tmp_path / 'out')
    assert [s['normalization']['sum_of_weights'] for s in result['samples']] == [10., 4.]
    assert [s['normalization']['scale'] for s in result['samples']] == [200., 250.]
    assert all(r['path'].startswith('root://') for s in result['samples'] for r in s['normalization']['coverage'])


@pytest.mark.parametrize('route', ['scoped', 'weighted', 'retained'])
def test_additional_science_shower_routes_reject_malformed_before_dispatch(tmp_path, monkeypatch, route):
    from types import SimpleNamespace
    import sys
    def dispatch(*args, **kwargs):
        pytest.fail('native dispatch reached before lhe_check')
    if route == 'scoped':
        from ravel.physics import scoped_shower
        path = tmp_path / 'bad.lhe'; path.write_text('<LesHouchesEvents><event>broken</event>')
        monkeypatch.setattr(scoped_shower, 'subprocess', SimpleNamespace(run=dispatch, STDOUT=-2))
        with pytest.raises(ValueError, match='lhe_check'):
            scoped_shower.run_shower(path, {'engine': 'pythia8', 'python': sys.executable,
                'seed': 19, 'settings': []}, [], tmp_path / 'out')
    elif route == 'weighted':
        from ravel.physics import weighted_events, backend_driver
        path = tmp_path / 'bad.lhe'; path.write_text('<LesHouchesEvents><event>broken</event>')
        monkeypatch.setattr(weighted_events, '_spec', lambda *a, **k: {})
        monkeypatch.setattr(backend_driver, 'drive', dispatch)
        with pytest.raises(ValueError, match='lhe_check'):
            weighted_events.rivet_rows({'doc': {'format': 'lhe', 'rivet': {},
                'shower': {'program': 'inert', 'settings': []}}},
                [{'path': path, 'block': 'control', 'pass': 0, 'events': 1}], tmp_path / 'out')
    else:
        from ravel.physics import retained_shower, native_event_io
        import test_retained_shower as fixture
        task, doc = fixture.fixture(tmp_path)
        path = tmp_path / 'input.lhe'; path.write_text('<LesHouchesEvents><event>broken</event>')
        source = next(r for r in doc['sources'] if r['id'] == 'lhe')
        source.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size)
        contract = tmp_path / 'contract.json'; fixture.write_json(contract, doc)
        task['contract_sha256'] = hashlib.sha256(contract.read_bytes()).hexdigest()
        for key in doc['environment']:
            monkeypatch.setenv(key, doc['environment'][key])
        monkeypatch.setattr(native_event_io, 'shower_original', dispatch)
        with pytest.raises(ValueError, match='lhe_check'):
            retained_shower.run(task, tmp_path, tmp_path / 'out')


@pytest.mark.parametrize('order', ['LO', 'NLO'])
def test_standalone_science_guard_loads_pinned_helper_without_ravel_install(tmp_path, monkeypatch, order):
    import sys
    monkeypatch.setattr(sys, 'argv', list(sys.argv))
    monkeypatch.setattr(sys, 'path', list(sys.path))
    from ravel.validation import science_shower_guard, lhe_check
    module, owner, method = ('madgraph.interface.madevent_interface', 'MadEventCmd', 'do_pythia8') if order == 'LO' else (
        'madgraph.interface.amcatnlo_run_interface', 'aMCatNLOCmd', 'do_shower')
    source = tmp_path / (module.replace('.', '/') + '.py')
    source.parent.mkdir(parents=True)
    source.write_text(f'class {owner}:\n    def {method}(self, line):\n        return line\n')
    namespace = {}; exec(compile(source.read_bytes(), str(source), 'exec'), namespace)
    original_import = science_shower_guard.importlib.import_module
    monkeypatch.setattr(science_shower_guard.importlib, 'import_module',
        lambda name, *a, **kw: SimpleNamespace(**namespace) if name == module else original_import(name, *a, **kw))
    driver = tmp_path / 'inert-driver.py'; driver.write_text('pass\n')
    helper = Path(lhe_check.__file__)
    pin = put(tmp_path, 'request.json', {'madgraph': str(tmp_path), 'order': order,
        'api': science_shower_guard.source_contract(tmp_path, order), 'process': str(tmp_path),
        'parameter_card': None, 'output': str(tmp_path / 'check.json'),
        'helper': {'path': str(helper), 'sha256': hashlib.sha256(helper.read_bytes()).hexdigest()}})
    science_shower_guard.main([str(tmp_path / pin['path']), pin['sha256'], str(driver), 'inert'])


def test_delivery_does_not_trust_caller_supplied_coverage_claim(tmp_path):
    from ravel.validation.delivery_checks import check_delivery
    pack = {'coverage': {'status': 'validated', 'general_likelihood_coverage_validated': True}}
    check_delivery(tmp_path, pack)
    assert pack['coverage']['status'] == 'not_evaluated'
    assert pack['coverage']['general_likelihood_coverage_validated'] is False


@pytest.mark.parametrize('fault', ['init_nan', 'event_scale_nan', 'compact_weight_nan'])
def test_science_lhe_gate_refuses_nonfinite_header_or_compact_weight(tmp_path, fault):
    import production_fixtures as pf
    from ravel.validation.lhe_check import check_science
    path = pf.write_lhe(tmp_path / 'events.lhe', n=1)
    text = path.read_text()
    if fault == 'init_nan':
        text = text.replace('6.500000e+03', 'NaN', 1)
    elif fault == 'event_scale_nan':
        lines = text.splitlines(); index = lines.index('<event>') + 1
        row = lines[index].split(); row[3] = 'NaN'; lines[index] = ' '.join(row)
        text = '\n'.join(lines) + '\n'
    else:
        text = text.replace('</event>', '<weights>NaN</weights>\n</event>')
    path.write_text(text)
    with pytest.raises(ValueError, match='lhe_check'):
        check_science(path, output=tmp_path / 'check.json')
    assert json.loads((tmp_path / 'check.json').read_text())['verdict'] == 'FAIL'


def test_columnar_subset_keeps_full_original_denominator_moments(tmp_path, monkeypatch):
    from ravel.physics import yield_hub
    original = ledger(); seen = []
    monkeypatch.setattr(yield_hub, 'delivery_checks', lambda output, **kw: seen.append(kw['ledger']) or [])
    normalization = {'mode': 'cross-section', 'cross_section_from': {'normalization_ledger': {'ledger': original}},
        'sum_of_weights': original['generated']['sumw'], 'luminosity_ifb': 1., 'luminosity_source': 'synthetic'}
    merged = {'variations': {'nominal': {'events': {'n': 2, 'sum_generator': 2., 'sum_generator2': 2.}}}}
    regions = [{'name': 'control', 'cuts': [{'sumw': 1., 'sumw2': 1., 'yield': 3.}]}]
    yield_hub.columnar_delivery_checks(tmp_path, {}, normalization, merged, regions, tmp_path)
    assert seen[0]['generated'] == original['generated']


def _resonance_lhe(path, mass, status, header=''):
    path.write_text('<LesHouchesEvents version="3.0">\n<header>\n' + header + '</header>\n<init>\n'
                    '2212 2212 6.5e3 6.5e3 0 0 0 0 3 1\n1.0 0.1 1.0 1\n</init>\n<event>\n'
                    '4 1 1.0 91.0 0.0078 0.118\n'
                    '2 -1 0 0 501 0 0 0 100 100 0 0 9\n'
                    '-1 -1 0 0 0 501 0 0 -100 100 0 0 9\n'
                    f'24 {status} 1 2 0 0 0 0 0 200 {mass} 0 9\n'
                    '-11 1 3 3 0 0 0 0 0 100 0 0 9\n</event>\n</LesHouchesEvents>\n')
    return path


def test_science_lhe_intermediate_resonance_uses_breit_wigner_cutoff(tmp_path):
    from ravel.validation.lhe_check import check_science
    card = tmp_path / 'card.dat'
    card.write_text('BLOCK MASS\n 24 80.0\nDECAY 24 2.0\n')
    # 14 GeV off shell is outside 3*Gamma but inside the generator's 15*Gamma window.
    record = check_science(_resonance_lhe(tmp_path / 'tail.lhe', 94.0, 2), param_card=card)
    assert record['verdict'] == 'PASS'
    with pytest.raises(ValueError, match='mass differs'):
        check_science(_resonance_lhe(tmp_path / 'far.lhe', 140.0, 2), param_card=card)
    # A declared narrower window is honoured, and on-shell external states stay tight.
    with pytest.raises(ValueError, match='mass differs'):
        check_science(_resonance_lhe(tmp_path / 'declared.lhe', 94.0, 2, header='5.0 = bwcutoff\n'), param_card=card)
    with pytest.raises(ValueError, match='mass differs'):
        check_science(_resonance_lhe(tmp_path / 'external.lhe', 94.0, 1), param_card=card)


def test_parity_factor_rows_report_no_cause_when_within_tolerance():
    from ravel.validation.normalization_ledger import parity_rows
    from ravel.physics import normalization_ledger as nl
    doc = ledger()
    factors = nl.check(doc)['factors']
    observed = {k: v * (1 + 1e-15) if v else v for k, v in factors.items()}
    rows = [r for r in parity_rows(doc, delivered=exact_yields(doc), applied_factors=observed) if r['stage'] != 'delivered_yield']
    assert rows and all(r['status'] == 'pass' and r['causes'] == [] for r in rows)
