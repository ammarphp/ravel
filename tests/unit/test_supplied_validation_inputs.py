"""Supplied validation inputs never inherit an installed study or qualification."""
import importlib.util
import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def controls():
    spec = importlib.util.spec_from_file_location(
        'fictional_supplied_controls', ROOT / 'scripts/validation/run_rivet_controls.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selftest_never_dispatches_to_installed_retained_input(monkeypatch):
    from ravel.physics import pyhf_exclude as exclude
    monkeypatch.setattr(exclude, 'compute', lambda model, data, **kw: {
        'obs_limit': .001 if data == 'small' else 2.4359,
        'exp_limits': [1, 2, 3, 4, 5], 'at_mu_floor': False,
        'at_poi_cap': data == 'ceiling', 'median_at_cap': data == 'ceiling',
        'band_degenerate': data == 'ceiling',
        'optimizer': {'n_fallback': 1, 'escalated': True}})
    monkeypatch.setattr(exclude, 'model_from_counting', lambda row: (
        None, 'small' if row['s'] > 100 else 'ceiling' if row['s'] < .01 else 'normal'))
    monkeypatch.setattr(exclude, '_nanpocket_model', lambda: (None, 'pocket'))
    monkeypatch.setattr(exclude, '_retained_freefit_selftest',
                        lambda *a: pytest.fail('installed retained fixture dispatched'))
    exclude.selftest()


def test_fit_reference_requires_selected_input():
    from ravel.physics import pyhf_exclude as exclude
    with pytest.raises(exclude.MissingReferenceInput) as error:
        exclude._retained_freefit_selftest()
    assert error.value.reason == 'missing_reference_input'


def test_control_suite_requires_selected_specs():
    module = controls()
    with pytest.raises(module.MissingControlInput) as error:
        module.load_suite(None)
    assert error.value.reason == 'missing_control_input'


def test_installation_record_does_not_qualify_an_operation():
    from ravel.setup import doctor
    group = {'id': 'fictional-engine', 'qualification': {
        'status': 'qualified', 'basis': 'Synthetic installation only',
        'record': {'doctor_result': 'ready'}}}
    label = doctor.group_label(group, 'ready', [{'status': 'ready'}])
    assert label['label'] == 'ready'
    assert label['qualification'] == 'built-unqualified'
    assert label['installation']['status'] == 'ready'


def test_qualification_requires_selected_receipt_and_scope():
    from ravel.setup import qualification
    with pytest.raises(qualification.MissingQualificationInput) as error:
        qualification.compare_receipt(None, None)
    assert error.value.reason == 'missing_qualification_input'


@pytest.mark.parametrize('row,paths', [
    (53, ('src/ravel/resources.py', 'src/ravel/data/replay')),
    (55, ('src/ravel/validation/benchmark.py',)),
    (56, ('scripts/build_evidence.py', 'scripts/gen_validation_pages.py',
          'scripts/validation_summary.py',
          'scripts/check_fidelity_audits.py')),
])
def test_removed_sites_stay_removed(row, paths):
    assert all(not (ROOT / p).exists() for p in paths), row
    if row == 56:
        assert not list((ROOT / 'scripts').glob('check_*_audits.py'))


def context(identity, grid, datasets):
    return {'study_id': identity, 'parameter_grid': grid, 'datasets': datasets}


def test_two_selected_fit_contracts_preserve_analytic_values_and_formats(tmp_path):
    """The supplied comparison preserves the former fit quantities without its source."""
    from ravel.physics import pyhf_exclude as exclude
    observed = []
    for identity, counts, background, signal, grid, datasets, fmt in (
            ('ANA-0001', [7], [5], [2], {'x': [1, 2]}, ['sample-a'], 'json'),
            ('ANA-0002', [10, 6], [4, 3], [6, 3], {'y': [3, 5, 8]}, ['sample-b', 'sample-c'], 'jsonl')):
        # At mu=1 each Poisson rate equals the supplied observation: analytic MLE.
        model = {'channels': [{'name': 'fictional-channel', 'samples': [
            {'name': 'background', 'data': background, 'modifiers': []}]}],
            'observations': [{'name': 'fictional-channel', 'data': counts}],
            'measurements': [{'name': 'fictional-measurement', 'config': {'poi': 'mu', 'parameters': []}}],
            'version': '1.0.0'}
        patch = [{'op': 'add', 'path': '/channels/0/samples/-', 'value': {
            'name': 'signal', 'data': signal, 'modifiers': [{'name': 'mu', 'type': 'normfactor', 'data': None}]}}]
        bkg = tmp_path / (identity + '-background.json'); bkg.write_text(json.dumps(model))
        sig = tmp_path / (identity + '-signal.json'); sig.write_text(json.dumps(patch))
        analytic = 2 * sum(n - n * math.log(n) + math.lgamma(n + 1) for n in counts)
        contract = {'background': str(bkg), 'patch': str(sig),
                    'expected': {key: {'value': value, 'atol': 1e-6, 'rtol': 1e-6}
                                 for key, value in [('mu_hat', 1.), ('twice_nll', analytic)]},
                    'context': context(identity, grid, datasets), 'output_format': fmt}
        result = exclude._retained_freefit_selftest(contract)
        assert result['status'] == 'passed' and all(result['checks'].values())
        assert result['actual'] == pytest.approx({'mu_hat': 1., 'twice_nll': analytic}, abs=1e-6)
        rendered = json.loads(result['rendered'])
        assert rendered['context'] == contract['context'] and rendered['output_format'] == fmt
        assert (len(result['rendered'].splitlines()) == 1) == (fmt == 'jsonl')
        observed.append(result)
    assert observed[0]['context'] != observed[1]['context']
    broken = copy.deepcopy(contract); del broken['expected']
    with pytest.raises(exclude.MissingReferenceInput) as error:
        exclude.check_fit_reference(broken)
    assert error.value.reason == 'missing_reference_input'


def test_fit_reference_allows_signed_finite_likelihood_values(tmp_path, monkeypatch):
    from ravel.physics import pyhf_exclude as exclude
    from types import SimpleNamespace
    source = tmp_path / 'fictional-model.json'; source.write_text('{}')
    model = SimpleNamespace(config=SimpleNamespace(poi_index=0))
    monkeypatch.setattr(exclude, 'model_from_likelihood', lambda *a: (model, []))
    monkeypatch.setattr(exclude.pyhf.infer.mle, 'fit', lambda *a, **k: ([-1.], -2.))
    contract = {'background': str(source), 'patch': str(source), 'output_format': 'json',
                'expected': {key: {'value': value, 'atol': 0., 'rtol': 0.}
                             for key, value in [('mu_hat', -1.), ('twice_nll', -2.)]}}
    assert exclude.check_fit_reference(contract)['status'] == 'passed'


def test_two_control_contracts_select_grids_populations_and_report_formats(tmp_path, monkeypatch):
    module = controls()
    plans, calls = {}, []
    def plan(rd, spec):
        plans[str(rd)] = json.loads(Path(spec).read_text())
        calls.append(('plan', str(rd)))
    def approve(rd, assent, scripted):
        assert assent == 'Synthetic assent' and scripted is True
        assert calls[-1] == ('method', str(rd))  # the bounded method decision precedes approval
        calls.append(('approve', str(rd)))
    def record_decision(rd, **kwargs):
        assert calls[-1] == ('plan', str(rd)) and kwargs['authority'] == 'scripted_experiment'
        calls.append(('method', str(rd)))
    def run(rd):
        assert calls[-1] == ('approve', str(rd))
        calls.append(('run', str(rd)))
        return 0
    monkeypatch.setattr(module.science, 'plan', plan)
    monkeypatch.setattr(module.science, 'approve', approve)
    monkeypatch.setattr(module.science, 'run', run)
    monkeypatch.setattr(module.science, 'packet', lambda rd: {
        'lifecycle_verdict': 'PASS', 'supplied': plans[str(rd)]})
    from ravel.workflow import method_selection
    monkeypatch.setattr(method_selection, 'record_validation_decision', record_decision)
    monkeypatch.setattr(module, 'read_json', lambda path: {'source': 'Synthetic', 'max_seconds': 1, 'mode': 'analyze'})
    outputs = []
    for identity, grid, datasets, fmt in (
            ('ANA-0001', {'x': [1, 2]}, ['sample-a'], 'json'),
            ('ANA-0002', {'y': [3, 5, 8]}, ['sample-b', 'sample-c'], 'jsonl')):
        cases = []
        supplied = context(identity, grid, datasets)
        for i, dataset in enumerate(datasets):
            spec = tmp_path / f'{identity}-{i}.json'
            spec.write_text(json.dumps({**supplied, 'selected_dataset': dataset}))
            cases.append({'name': f'fictional-control-{i}', 'spec': spec.name, 'expected': 'passed'})
        manifest = {'schema_version': 2, 'cases': cases,
                    'report': {'path': f'outputs/report.{fmt}', 'format': fmt}}
        path = tmp_path / f'{identity}-controls.json'; path.write_text(json.dumps(manifest))
        suite = module.load_suite(path)
        root = tmp_path / identity; root.mkdir()
        assert module.execute_cases(root, suite['cases'], 'Synthetic assent', suite['report']) == 0
        text = (root / suite['report']['path']).read_text()
        rows = json.loads(text)['results'] if fmt == 'json' else [json.loads(line) for line in text.splitlines()]
        assert len(rows) == len(datasets)
        assert [r['packet']['supplied']['selected_dataset'] for r in rows] == datasets
        assert all(r['packet']['supplied']['parameter_grid'] == grid for r in rows)
        assert all(r['packet']['supplied']['study_id'] == identity for r in rows)
        outputs.append(rows)
    assert len(outputs[0]) != len(outputs[1])
    del manifest['report']; path.write_text(json.dumps(manifest))
    with pytest.raises(module.MissingControlInput) as error:
        module.load_suite(path)
    assert error.value.reason == 'missing_control_input'


def test_selected_synthetic_control_preserves_grouped_weights_and_normalization(tmp_path, monkeypatch):
    module = controls()
    row = {'name': 'fictional-control', 'energy': 700, 'kind': 'dy', 'observable': 'fictional-bin',
           'unit': '1/GeV', 'normalized': True, 'grouped': True, 'expected': 'normalization_failure'}
    path = tmp_path / 'controls.json'; path.write_text(json.dumps({'schema_version': 1, 'cases': [row]}))
    runtime = tmp_path / 'runtime.json'; runtime.write_text('{}')
    out = tmp_path / 'prepared'
    monkeypatch.setattr(module.sys, 'argv', ['controls', '--cases', str(path), '--runtime', str(runtime),
                                           '--source', str(tmp_path), '--out', str(out)])
    monkeypatch.setattr(module.science, 'run', lambda *a: pytest.fail('preparation launched compute'))
    assert module.main() == 0
    data = out / 'inputs'
    # Migration identity: identical event bytes under the explicitly selected convention.
    expected = module.events(700, 'dy').replace('W nominal', 'W nominal\\|scale').replace('E 1 ', 'E 0 ')
    expected = expected.replace('W 1', 'W 2 4', 1).replace('W 1', 'W -1 -2', 1)
    assert (data / 'fictional-control.hepmc').read_text() == expected
    metadata = json.loads((data / 'fictional-control-metadata.json').read_text())
    assert metadata['groups'] == 'correlated_event_number' and metadata['weight_names'] == ['nominal', 'scale']
    spec = json.loads((data / 'fictional-control-spec.json').read_text())
    assert spec['task']['observables'][0]['normalization'] == 'normalized'
    assert spec['task']['observables'][0]['unit'] == '1/GeV'
    assert json.loads((out / 'cases.json').read_text())['cases'][0]['expected'] == 'normalization_failure'


def test_two_receipt_contracts_match_only_exact_scope_and_formats(tmp_path):
    from ravel.setup import qualification
    evidence = tmp_path / 'synthetic-evidence.json'; evidence.write_text('{"passed":true}')
    check = {'name': 'fictional-invariant', 'status': 'passed', 'evidence': {
        'path': str(evidence), 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}}
    for identity, grid, datasets, fmt in (
            ('ANA-0001', {'x': [1, 2]}, ['sample-a'], 'json'),
            ('ANA-0002', {'y': [3, 5, 8]}, ['sample-b', 'sample-c'], 'jsonl')):
        scope = {'tool': 'fictional-engine', 'versions': {'engine': '1.2.3'},
                 'platform': 'fictional-platform', 'operation': 'fictional-fit',
                 'conditions': context(identity, grid, datasets)}
        receipt = {'schema_version': 1, 'scope': scope, 'checks': [check]}
        request = {'scope': scope, 'output_format': fmt}
        result = qualification.compare_receipt(receipt, request)
        assert result['status'] == 'matched' and result['scope'] == scope
        assert result['scientific_acceptance'] is False
        assert json.loads(result['rendered'])['scope'] == scope
        assert (len(result['rendered'].splitlines()) == 1) == (fmt == 'jsonl')
        for key, value in [('versions', {'engine': '9.9.9'}), ('platform', 'other-platform'),
                           ('operation', 'other-fit'), ('conditions', context('ANA-0003', {}, []))]:
            changed = copy.deepcopy(request); changed['scope'][key] = value
            with pytest.raises(ValueError, match='scope differs'):
                qualification.compare_receipt(receipt, changed)
    missing = copy.deepcopy(request); del missing['scope']['conditions']
    with pytest.raises(qualification.MissingQualificationInput) as error:
        qualification.compare_receipt(receipt, missing)
    assert error.value.reason == 'missing_qualification_input'
    for status in ('failed', 'not_run'):
        altered = copy.deepcopy(receipt); altered['checks'][0]['status'] = status
        assert qualification.compare_receipt(altered, request)['status'] == status
    evidence.write_text('{"passed":false}')
    with pytest.raises(ValueError, match='digest differs'):
        qualification.compare_receipt(receipt, request)


def test_census_never_promotes_installation_to_numerical_qualification():
    from ravel.setup.qualification import census_status
    assert census_status('ready') == 'built_but_unqualified'
    assert census_status('missing') == 'not_installed'
