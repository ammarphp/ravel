"""Supplied full likelihood contracts, using fictional model and sample names."""
from copy import deepcopy
import importlib
import json
from pathlib import Path

import numpy as np
import pytest


def adapter():
    return importlib.import_module('ravel.physics.higgs_published_likelihood')


def registry():
    return {'schema_version': 1, 'combine_release': '9.2.1',
            'image_digest': 'sha256:' + 'a' * 64,
            'models': [{'id': 'MODEL-0001', 'module': 'synthetic.models', 'model': 'couplings',
                        'combine_release': '9.2.1', 'pois': ['k'],
                        'options': ['map=.*:k[1,0,3]', 'verbose=0']}]}


def model_declaration():
    return {'id': 'MODEL-0001', 'combine_release': '9.2.1', 'pois': ['k'],
            'options': ['map=.*:k[1,0,3]', 'verbose=0']}


def workspace():
    return {'channels': [{'name': 'C0', 'samples': [
        {'name': 'S0', 'data': [8.0], 'modifiers': [{'name': 'mu', 'type': 'normfactor', 'data': None}]},
        {'name': 'S1', 'data': [3.0], 'modifiers': [{'name': 'mu', 'type': 'normfactor', 'data': None}]},
        {'name': 'B0', 'data': [21.0], 'modifiers': []}]}],
        'observations': [{'name': 'C0', 'data': [32]}],
        'measurements': [{'name': 'M0', 'config': {'poi': 'mu', 'parameters': []}}],
        'version': '1.0.0'}


def mapping():
    return [{'channel': 'C0', 'sample': 'S0', 'production': 'P0', 'decay': 'D0'},
            {'channel': 'C0', 'sample': 'S1', 'production': 'P1', 'decay': 'D0'}]


@pytest.mark.parametrize('change', ['unknown', 'release', 'row_release', 'options', 'pois', 'module'])
def test_unadmitted_model_refused_before_native_call(change, monkeypatch, tmp_path):
    mod = adapter()
    declaration = model_declaration()
    admitted = registry()
    if change == 'unknown': declaration['id'] = 'MODEL-0002'
    elif change == 'row_release': admitted['models'][0]['combine_release'] = '0.0.1'
    elif change == 'release': declaration['combine_release'] = '0.0.1'
    elif change == 'options': declaration['options'] += ['unsafe=1']
    elif change == 'pois': declaration['pois'] = ['other']
    else: declaration['module'] = 'arbitrary.code'
    called = []
    monkeypatch.setattr('subprocess.run', lambda *a, **k: called.append(a))
    with pytest.raises(ValueError, match='admitted|release|declaration'):
        mod.combine_commands({}, {}, tmp_path, declaration, admitted=admitted)
    assert called == []


def test_shipped_admission_pins_the_toolchain_combine_image():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / 'native/setup/toolchain-manifest.json').read_text())
    group = next(g for g in manifest['groups'] if g['id'] == 'root-combine')
    digests = {step['digest'] for step in group['steps'] if step['kind'] == 'container_pull'}
    shipped = json.loads(adapter().REGISTRY.read_text())
    assert digests == {shipped['image_digest']}
    assert shipped['combine_release'] in group['title']


def test_unmapped_signal_refused():
    with pytest.raises(ValueError, match='unmapped'):
        adapter().patch_workspace(workspace(), mapping()[:1], {('P0', 'D0'): 1.0},
                                  measurement='M0', signal_modifier='mu')


@pytest.mark.parametrize('change', ['duplicate', 'background', 'unknown', 'negative', 'nonfinite', 'missing'])
def test_invalid_mapping_or_multiplier_refused(change):
    rows, factors = mapping(), {('P0', 'D0'): 1.0, ('P1', 'D0'): 1.0}
    if change == 'duplicate': rows += [deepcopy(rows[0])]
    elif change == 'background': rows[0]['sample'] = 'B0'
    elif change == 'unknown': rows[0]['sample'] = 'S9'
    elif change == 'negative': factors[('P0', 'D0')] = -1.0
    elif change == 'nonfinite': factors[('P0', 'D0')] = float('nan')
    else: del factors[('P0', 'D0')]
    with pytest.raises(ValueError):
        adapter().patch_workspace(workspace(), rows, factors, measurement='M0', signal_modifier='mu')


def test_production_registry_refuses_without_module_source_evidence(tmp_path):
    with pytest.raises(ValueError, match='admitted'):
        adapter().combine_commands({}, {}, tmp_path, model_declaration())


def test_native_dispatch_refuses_missing_owner_seam_without_launch(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr('subprocess.run', lambda *a, **k: called.append(a))
    with pytest.raises(adapter().InterfaceUnavailable, match='physics.model'):
        adapter().run_combine({}, tmp_path, tmp_path / 'out', model_declaration(), admitted=registry())
    assert not called


def parameterization():
    return {'framework': 'kappa',
            'parameters': [{'name': 'k', 'bounds': [0.4, 1.8], 'initial': 1.0, 'unit': '', 'label': 'Coupling'}],
            'program': {'constants': [], 'definitions': [], 'outputs': [
                {'name': 'r0', 'expression': 'k**2', 'unit': '', 'label': 'First rate'},
                {'name': 'r1', 'expression': 'k**4', 'unit': '', 'label': 'Second rate'}]},
            'rates': [{'production': 'P0', 'decay': 'D0', 'output': 'r0'},
                      {'production': 'P1', 'decay': 'D0', 'output': 'r1'}]}


def gaussian_constrained_workspace():
    ws, rows, rates = workspace(), [], []
    ws['channels'], ws['observations'] = [], []
    declaration = parameterization()
    declaration['rates'] = []
    constants = []
    for p in range(2):
        for d in range(2):
            i = 2 * p + d
            channel, sample = f'C{i}', f'S{i}'
            b, s, sigma = 40.0 + 5 * i, 8.0 + 2 * i, 3.0 + i
            constants.append((b, s, sigma))
            ws['channels'].append({'name': channel, 'samples': [
                {'name': sample, 'data': [s], 'modifiers': [{'name': 'mu', 'type': 'normfactor', 'data': None}]},
                {'name': 'B0', 'data': [b], 'modifiers': [{'name': f'err{i}', 'type': 'staterror', 'data': [sigma]}]}]})
            ws['observations'].append({'name': channel, 'data': [b + s]})
            rows.append({'channel': channel, 'sample': sample, 'production': f'P{p}', 'decay': f'D{d}'})
            declaration['rates'].append({'production': f'P{p}', 'decay': f'D{d}', 'output': f'r{p}'})
    return ws, rows, declaration, constants


def analytic_profile(k, constants):
    # Main Poisson observations and independent Gaussian background constraints.
    # Solve the profiled mean's quadratic; constants cancel in delta(-2 ln L).
    result = 0.0
    for i, (b, nominal, sigma) in enumerate(constants):
        s = nominal * k ** (2 if i < 2 else 4)
        n = b + nominal
        a = b + s - sigma**2
        mean = (a + np.sqrt(a*a + 4*n*sigma**2)) / 2
        gamma = (mean - s) / b
        assert 1e-10 < gamma < 10
        result += 2 * (mean - n*np.log(mean)) + ((gamma - 1)*b/sigma)**2
    return result


def test_two_production_two_decay_profile_matches_analytic_gaussian_constraints():
    ws, rows, declaration, constants = gaussian_constrained_workspace()
    source = deepcopy(ws)
    points = [{'k': k} for k in [0.7, 0.9, 1.0, 1.15, 1.3]]
    result = adapter().scan_pyhf(ws, rows, declaration, points, measurement='M0', signal_modifier='mu')
    for row, point in zip(result['scan'], points):
        expected = analytic_profile(point['k'], constants) - analytic_profile(1, constants)
        assert row['delta_twice_nll'] == pytest.approx(expected, abs=1e-4)
    assert result['best_fit']['coordinates']['k'] == pytest.approx(1.0, abs=1e-4)
    assert ws == source
    assert result['physics_validated'] is False


def test_point_patch_keeps_source_data_auxiliary_constraints_and_zero_rates():
    import pyhf
    from jsonpatch import JsonPatch
    ws = workspace()
    ws['channels'][0]['samples'][0]['modifiers'].append(
        {'name': 'shape', 'type': 'histosys', 'data': {'hi_data': [10.0], 'lo_data': [6.0]}})
    source = deepcopy(ws)
    patched, patches = adapter().patch_workspace(ws, mapping(), {('P0', 'D0'): 0.0, ('P1', 'D0'): 2.0},
                                                measurement='M0', signal_modifier='mu')
    assert JsonPatch(patches).apply(ws) == patched
    assert patched['observations'] == ws['observations']
    assert patched['channels'][0]['samples'][2] == ws['channels'][0]['samples'][2]
    assert patched['channels'][0]['samples'][0]['modifiers'][1] == ws['channels'][0]['samples'][0]['modifiers'][1]
    model = pyhf.Workspace(patched).model()
    pars = model.config.suggested_init()
    pars[model.config.par_map['shape']['slice'].start] = 1.0
    assert np.asarray(model.expected_actualdata(pars)).tolist() == pytest.approx([27.0])
    assert ws == source


def test_supplied_stxs_population_and_renamed_samples_need_no_product_edit():
    ws, rows = workspace(), mapping()
    ws['channels'][0]['name'] = 'CATEGORY-0003'
    ws['observations'][0]['name'] = 'CATEGORY-0003'
    for row in rows: row['channel'] = 'CATEGORY-0003'
    declaration = parameterization()
    declaration['framework'] = 'stxs'
    declaration['parameters'][0]['name'] = 'rate'
    for output in declaration['program']['outputs']: output['expression'] = 'rate'
    result = adapter().scan_pyhf(ws, rows, declaration, [{'rate': 0.8}, {'rate': 1.2}],
                                 measurement='M0', signal_modifier='mu')
    assert [r['coordinates'] for r in result['scan']] == [{'rate': 0.8}, {'rate': 1.2}]
    assert result['best_fit']['coordinates']['rate'] == pytest.approx(1, abs=1e-5)


def native_configuration():
    return {'schema_version': 1, 'model': {'card': 'input.dat'},
            'runtime': {'expected': {'combine_version': '9.2.1'},
                        'transport': {'kind': 'podman', 'manifest_digest': 'sha256:' + 'a' * 64}},
            'fit': {'mass': 125, 'method': 'MultiDimFit', 'seed': 7, 'poi': 'k',
                    'domain': ['0', '2'], 'points': 2, 'minimizer': None, 'data': 'observed'}}


def test_fake_native_binaries_receive_exact_admitted_recipe_and_parse_fixture(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    mod = adapter()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    fixture = {'rows': [{'k': 1.0, 'deltaNLL': 0.0, 'quantileExpected': -1.0},
                        {'k': 0.5, 'deltaNLL': 0.125, 'quantileExpected': 0.5},
                        {'k': 1.5, 'deltaNLL': 0.125, 'quantileExpected': 0.5}], 'fit_results': []}
    builder = bin_dir / 'text2workspace.py'
    builder.write_text(f'#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n'
                       'Path("build-argv.json").write_text(json.dumps(sys.argv[1:]))\n'
                       'Path(sys.argv[sys.argv.index("-o")+1]).write_text("synthetic workspace")\n')
    combine = bin_dir / 'combine'
    combine.write_text(f'#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n'
                       'Path("fit-argv.json").write_text(json.dumps(sys.argv[1:]))\n'
                       f'print("RAVEL_NATIVE_RESULT=" + {json.dumps(json.dumps(fixture))})\n')
    builder.chmod(0o755); combine.chmod(0o755)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    config = native_configuration()
    build, fit = mod.combine_commands(config, {'text2workspace': 'text2workspace.py', 'combine': 'combine'},
                                     tmp_path, model_declaration(), admitted=registry())
    subprocess.run(build, cwd=tmp_path, check=True, capture_output=True, text=True)
    completed = subprocess.run(fit, cwd=tmp_path, check=True, capture_output=True, text=True)
    args = json.loads((tmp_path / 'build-argv.json').read_text())
    assert args == [str(tmp_path / 'input.dat'), '-o', str(tmp_path / 'ravel_workspace.root'), '-m', '125',
                    '-P', 'synthetic.models:couplings', '--PO', 'map=.*:k[1,0,3]', '--PO', 'verbose=0']
    assert json.loads((tmp_path / 'fit-argv.json').read_text()) == fit[1:]
    parsed = mod.parse_combine_scan(completed.stdout, config['fit'])
    assert parsed['rows'] == fixture['rows']
    assert parsed['passed']
    assert len(parsed['grid_coverage']['witnesses']) == 2


def test_pyhf_backend_restored_after_profile():
    import pyhf
    previous = pyhf.get_backend()
    adapter().scan_pyhf(workspace(), mapping(), parameterization(), [{'k': 0.8}],
                        measurement='M0', signal_modifier='mu')
    actual = pyhf.get_backend()
    assert all(a is b for a, b in zip(actual, previous))


def test_hs3_formula_request_is_declarative_and_preserves_supplied_model():
    model = {'metadata': {'hs3_version': '0.2'}, 'functions': [{'name': 'f0', 'type': 'formula', 'expression': 'mu'}]}
    source = deepcopy(model)
    request = adapter().hs3_formula_request(model, parameterization(),
        [{'function': 'f0', 'production': 'P0', 'decay': 'D0'}], [{'k': 0.9}])
    assert request['formula_functions'] == [{'name': 'f0', 'output': 'r0'}]
    assert request['model'] == source == model
    assert request['physics_validated'] is False


@pytest.mark.xfail(reason='awaits HS3 repair', strict=True, raises=RuntimeError)
def test_hs3_reparameterized_formula_profile_equals_pyhf(tmp_path):
    ws, rows, declaration, _ = gaussian_constrained_workspace()
    points = [{'k': 0.7}, {'k': 1.0}, {'k': 1.3}]
    expected = adapter().scan_pyhf(ws, rows, declaration, points, measurement='M0', signal_modifier='mu')
    # Repaired seam consumes this generic supplied conversion contract. Its owner
    # constructs the RooFit graph without importing native code in this process.
    request = adapter().hs3_formula_request(synthetic_hs3(ws), declaration,
        [{'function': 'f' + str(i), 'production': r['production'], 'decay': r['decay']} for i, r in enumerate(rows)], points)
    actual = adapter().run_hs3({'input': 'synthetic.json'}, tmp_path, tmp_path / 'out', request)
    assert [r['delta_twice_nll'] for r in actual['scan']] == pytest.approx(
        [r['delta_twice_nll'] for r in expected['scan']], abs=1e-4)


@pytest.mark.parametrize('change', ['release', 'digest', 'source_model'])
def test_native_runtime_or_source_model_mismatch_refused(change, tmp_path):
    config = native_configuration()
    if change == 'release': config['runtime']['expected']['combine_version'] = '0.0.1'
    elif change == 'digest': config['runtime']['transport']['manifest_digest'] = 'sha256:' + 'b' * 64
    else: config['model']['physics_model'] = {'path': 'another.py'}
    with pytest.raises(ValueError):
        adapter().combine_commands(config, {}, tmp_path, model_declaration(), admitted=registry())


@pytest.mark.parametrize('engine', ['combine', 'hs3'])
def test_native_owner_seam_without_supervised_authority_refused(engine, tmp_path, monkeypatch):
    mod = adapter()
    target = importlib.import_module('ravel.physics.native_likelihood' if engine == 'combine' else 'ravel.physics.hs3_likelihood')
    called = []
    name = 'run_with_physics_model' if engine == 'combine' else 'run_with_formula_functions'
    monkeypatch.setattr(target, name, lambda *a, **k: called.append(a), raising=False)
    shipped = tmp_path / 'models.json'
    shipped.write_text(json.dumps(registry()))
    monkeypatch.setattr(mod, 'REGISTRY', shipped)
    with pytest.raises(ValueError, match='approved supervised stage'):
        if engine == 'combine':
            mod.run_combine({}, tmp_path, tmp_path / 'out', model_declaration())
        else:
            mod.run_hs3({}, tmp_path, tmp_path / 'out', {})
    assert not called


@pytest.mark.parametrize('change', ['nonfinite', 'extra', 'missing', 'outside'])
def test_invalid_parameter_scan_refused_before_optimizer(change, monkeypatch):
    from scipy import optimize
    called = []
    monkeypatch.setattr(optimize, 'minimize', lambda *a, **k: called.append(a))
    point = {'k': 0.9}
    if change == 'nonfinite': point['k'] = float('nan')
    elif change == 'extra': point['q'] = 1.0
    elif change == 'missing': point = {}
    else: point['k'] = 10
    with pytest.raises(ValueError):
        adapter().scan_pyhf(workspace(), mapping(), parameterization(), [point], measurement='M0', signal_modifier='mu')
    assert not called


def write_configuration(tmp_path):
    import hashlib
    ws_path = tmp_path / 'workspace.json'
    ws_path.write_text(json.dumps(workspace()))
    config = {'schema_version': 1, 'kind': 'higgs-published-likelihood', 'engine': 'pyhf',
              'likelihood': {'path': ws_path.name, 'sha256': hashlib.sha256(ws_path.read_bytes()).hexdigest()},
              'measurement': 'M0', 'signal_modifier': 'mu', 'sample_map': mapping(),
              'parameterization': parameterization(), 'points': [{'k': 0.9}, {'k': 1.1}], 'fit_tolerance': 1e-9,
              'max_seconds': 120,
              'output': {'filename': 'result.json', 'format': 'json'}}
    path = tmp_path / 'configuration.json'
    path.write_text(json.dumps(config))
    return path, ws_path


def test_changed_workspace_bytes_refused_at_intake(tmp_path):
    config, ws_path = write_configuration(tmp_path)
    ws_path.write_text(ws_path.read_text() + '\n')
    with pytest.raises(ValueError, match='changed likelihood'):
        adapter().inputs({'input': config.name}, tmp_path)


def test_duplicate_configuration_json_refused(tmp_path):
    config, _ = write_configuration(tmp_path)
    config.write_text(config.read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
    with pytest.raises(ValueError, match='duplicate JSON'):
        adapter().inputs({'input': config.name}, tmp_path)


@pytest.mark.parametrize('record_ids', [[], [''], ['REC-0001', 'REC-0001']])
def test_invalid_acquisition_population_refused(record_ids):
    with pytest.raises(ValueError):
        adapter().acquisition_configuration(record_ids, fetch_requested=True)


def test_supplied_record_acquisition_is_configuration_only(monkeypatch):
    called = []
    monkeypatch.setattr('subprocess.run', lambda *a, **k: called.append(a))
    config = adapter().acquisition_configuration(['REC-0001', 'REC-0003'], fetch_requested=True)
    assert config['record_identifiers'] == ['REC-0001', 'REC-0003']
    assert config['operation'] == 'acquire-published'
    assert config['fetch_requested'] is True
    assert config['resource_detection']['formats'] == ['combine', 'pyhf', 'hs3']
    assert not called


@pytest.mark.parametrize('output_format', ['json', 'json-compact'])
def test_task_intake_and_supplied_output_format(tmp_path, output_format):
    path, ws_path = write_configuration(tmp_path)
    doc = json.loads(path.read_text())
    doc['output'] = {'filename': 'supplied-result.dat', 'format': output_format}
    path.write_text(json.dumps(doc))
    paths = adapter().inputs({'input': path.name}, tmp_path)
    assert path in paths and ws_path in paths
    out = tmp_path / 'out'
    result = adapter().run({'input': path.name}, tmp_path, out)
    published = out / 'supplied-result.dat'
    assert json.loads(published.read_text()) == result
    assert (len(published.read_text().splitlines()) == 1) == (output_format == 'json-compact')
    assert len(list(out.iterdir())) == 1


def test_unsafe_requested_output_refused_during_intake(tmp_path):
    path, _ = write_configuration(tmp_path)
    doc = json.loads(path.read_text())
    doc['output'] = {'filename': '../result.json', 'format': 'json'}
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='output basename'):
        adapter().inputs({'input': path.name}, tmp_path)


def synthetic_hs3(ws):
    """HS3 sibling with the same supplied main data and Gaussian constraints."""
    distributions, datasets, functions, constraints = [], [], [], []
    axes, values, labels = [{'name': 'mu', 'min': 0, 'max': 10}], [{'name': 'mu', 'value': 1}], []
    for i, channel in enumerate(ws['channels']):
        label = channel['name']
        labels.append(label)
        axis = [{'name': 'x' + str(i), 'edges': [0, 1]}]
        samples = []
        for sample in channel['samples']:
            modifiers = []
            for modifier in sample['modifiers']:
                if modifier['name'] == 'mu':
                    functions.append({'name': 'f' + str(i), 'type': 'generic_function', 'expression': 'mu', 'arguments': ['mu']})
                    modifiers.append({'name': 'signal' + str(i), 'type': 'normfactor', 'parameter': 'f' + str(i)})
                elif modifier['type'] == 'staterror':
                    name = 'gamma' + str(i)
                    constraint = 'constraint' + str(i)
                    width = modifier['data'][0] / sample['data'][0]
                    distributions.append({'name': constraint, 'type': 'gaussian_dist', 'x': name, 'mean': 1.0, 'sigma': width})
                    constraints.append(constraint)
                    axes.append({'name': name, 'min': 0, 'max': 10}); values.append({'name': name, 'value': 1})
                    modifiers.append({'name': name, 'type': 'normfactor', 'parameter': name})
            samples.append({'name': sample['name'], 'data': {'contents': sample['data']}, 'modifiers': modifiers})
        distributions.append({'name': 'model_' + label, 'type': 'histfactory_dist', 'axes': axis, 'samples': samples})
        observed = next(o for o in ws['observations'] if o['name'] == label)
        datasets.append({'name': 'obs_' + label, 'type': 'binned', 'axes': axis, 'contents': observed['data']})
    category = {'index_cat': 'category', 'labels': labels, 'indices': list(range(len(labels)))}
    return {'metadata': {'hs3_version': '0.2', 'packages': [{'name': 'ROOT', 'version': '6.35.01'}]},
            'functions': functions, 'distributions': distributions, 'data': datasets,
            'domains': [{'name': 'default_domain', 'type': 'product_domain', 'axes': axes}],
            'parameter_points': [{'name': 'default_values', 'parameters': values}],
            'likelihoods': [{'name': 'likelihood', 'distributions': ['model_' + label for label in labels],
                             'data': ['obs_' + label for label in labels], 'aux_distributions': constraints}],
            'analyses': [{'name': 'analysis', 'likelihood': 'likelihood', 'domains': ['default_domain'], 'parameters_of_interest': ['mu']}],
            'misc': {'ROOT_internal': {'ModelConfigs': {'analysis': {'mcName': 'ModelConfig', 'pdfName': 'model'}},
                     'combined_distributions': {'model': {**category, 'distributions': ['model_' + label for label in labels]}},
                     'combined_datasets': {'obs': category}}}}


def test_synthetic_hs3_sibling_passes_existing_structural_inspector():
    from ravel.physics.hs3_likelihood import inspect_graph
    ws, _, _, _ = gaussian_constrained_workspace()
    model = synthetic_hs3(ws)
    inspected = inspect_graph(json.dumps(model).encode(), ['histfactory_dist', 'gaussian_dist', 'generic_function'])
    assert inspected['bindings']['analysis']['dataset'] == 'obs'
    assert inspected['inventory']['counts']['functions'] == 4
    assert inspected['inventory']['counts']['data'] == 4


def test_parameterization_converter_seam_consumed_at_intake(tmp_path, monkeypatch):
    import sys
    from types import ModuleType
    owner = ModuleType('ravel.physics.higgs_parameterization')
    seen = []
    def convert(bundle):
        seen.append(bundle)
        return parameterization()
    owner.published_likelihood_program = convert
    monkeypatch.setitem(sys.modules, owner.__name__, owner)
    path, _ = write_configuration(tmp_path)
    doc = json.loads(path.read_text())
    doc['parameterization'] = {'bundle': {'id': 'MODEL-0001'}}
    path.write_text(json.dumps(doc))
    adapter().inputs({'input': path.name}, tmp_path)
    assert seen == [{'id': 'MODEL-0001'}]


def test_combine_input_owner_seam_consumes_pinned_model(tmp_path, monkeypatch):
    import hashlib
    from ravel.physics import native_likelihood
    mod = adapter()
    registry_path = tmp_path / 'models.json'
    registry_path.write_text(json.dumps(registry()))
    monkeypatch.setattr(mod, 'REGISTRY', registry_path)
    native_path = tmp_path / 'native.json'
    native_path.write_text(json.dumps(native_configuration()))
    config = {'schema_version': 1, 'kind': mod.MODE, 'engine': 'combine',
              'native_configuration': {'path': native_path.name, 'sha256': hashlib.sha256(native_path.read_bytes()).hexdigest()},
              'physics_model': model_declaration(), 'output': {'filename': 'fit.dat', 'format': 'json'}}
    path = tmp_path / 'configuration.json'; path.write_text(json.dumps(config))
    seen = []
    def observe(task, base, *, physics_model):
        seen.append((task, base, physics_model))
        return [native_path]
    monkeypatch.setattr(native_likelihood, 'inputs_with_physics_model', observe, raising=False)
    pins = mod.inputs({'input': path.name}, tmp_path)
    assert seen[0][0] == {'input': str(native_path)}
    assert seen[0][2]['module'] == 'synthetic.models'
    assert seen[0][2]['image_digest'] == registry()['image_digest']
    assert pins.count(native_path) == 1


def test_two_parameter_profile_retains_supplied_point_order():
    ws, rows, declaration, constants = gaussian_constrained_workspace()
    declaration['parameters'] = [
        {'name': name, 'bounds': [0.4, 1.8], 'initial': 1.0, 'unit': '', 'label': name}
        for name in ('a', 'b')]
    declaration['program']['outputs'][0]['expression'] = 'a**2'
    declaration['program']['outputs'][1]['expression'] = 'b**4'
    points = [{'a': 0.8, 'b': 1.2}, {'a': 1.0, 'b': 1.0}]
    result = adapter().scan_pyhf(ws, rows, declaration, points, measurement='M0', signal_modifier='mu')
    expected = analytic_profile(0.8, constants[:2]) - analytic_profile(1, constants[:2])
    # Reuse the analytic law after moving the second production to the first
    # positions and squaring its coupling to reproduce the declared fourth power.
    expected += analytic_profile(1.2**2, constants[2:]) - analytic_profile(1, constants[2:])
    assert result['scan'][0]['delta_twice_nll'] == pytest.approx(expected, abs=1e-4)
    assert [row['coordinates'] for row in result['scan']] == points
    assert result['fit_diagnostics']['globality_qualified'] is False


def test_failed_continuous_fit_is_retained_in_requested_output(tmp_path, monkeypatch):
    from scipy import optimize
    from types import SimpleNamespace
    def fail_after_evaluation(fun, initial, **kwargs):
        fun(initial)
        return SimpleNamespace(success=False, fun=0.0, message='synthetic optimizer failure', nfev=1)
    monkeypatch.setattr(optimize, 'minimize', fail_after_evaluation)
    path, _ = write_configuration(tmp_path)
    out = tmp_path / 'out'
    result = adapter().run({'input': path.name}, tmp_path, out)
    assert result['status'] == 'failed'
    assert result['physics_validated'] is False
    assert 'synthetic optimizer failure' in result['error']['message']
    assert result['diagnostics']['profile_attempts']
    assert result['diagnostics']['parameter_optimizer']['success'] is False
    assert json.loads((out / 'result.json').read_text()) == result


def test_pyhf_time_ceiling_is_the_declared_integer(tmp_path):
    path, _ = write_configuration(tmp_path)
    seconds = adapter().execution_seconds({'input': path.name}, tmp_path)
    assert type(seconds) is int and seconds == 120


@pytest.mark.parametrize('value', [None, 0, True, 1.5, '60', 86401])
def test_invalid_pyhf_time_ceiling_refused_at_intake(value, tmp_path):
    path, _ = write_configuration(tmp_path)
    doc = json.loads(path.read_text())
    if value is None: del doc['max_seconds']
    else: doc['max_seconds'] = value
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='time ceiling|requires exactly'):
        adapter().inputs({'input': path.name}, tmp_path)


def test_elapsed_time_ceiling_stops_the_scan_and_is_retained(tmp_path, monkeypatch):
    import time
    with pytest.raises(RuntimeError, match='time ceiling'):
        adapter().scan_pyhf(workspace(), mapping(), parameterization(), [{'k': 0.8}], measurement='M0',
                            signal_modifier='mu', deadline=time.monotonic() - 1)
    path, _ = write_configuration(tmp_path)
    ticks = iter([0.0])
    monkeypatch.setattr(adapter().time, 'monotonic', lambda: next(ticks, 1e9))
    result = adapter().run({'input': path.name}, tmp_path, tmp_path / 'out')
    assert result['status'] == 'failed'
    assert 'time ceiling' in result['error']['message']
    assert 'scan' not in result


def test_best_fit_record_is_not_a_scan_row(monkeypatch):
    from scipy import optimize
    from types import SimpleNamespace
    def stop_at_start(fun, initial, **kwargs):
        return SimpleNamespace(success=True, fun=fun(initial), x=list(initial), message='synthetic stop', nfev=1)
    monkeypatch.setattr(optimize, 'minimize', stop_at_start)
    result = adapter().scan_pyhf(workspace(), mapping(), parameterization(), [{'k': 1.0}, {'k': 1.0}],
                                 measurement='M0', signal_modifier='mu')
    assert 'delta_twice_nll' not in result['best_fit']
    assert [row['delta_twice_nll'] for row in result['scan']] == [0.0, 0.0]
    assert result['scan'][0] is not result['scan'][1]


def test_profile_reports_guarded_optimizer_counts():
    result = adapter().scan_pyhf(*gaussian_constrained_workspace()[:3], [{'k': 0.9}],
                                 measurement='M0', signal_modifier='mu')
    guard = result['fit_diagnostics']['optimizer_guard']
    assert set(guard) == {'n_minimizations', 'n_fallback', 'n_nan_flagged', 'n_escalated', 'escalated'}
    assert guard['n_minimizations'] >= result['fit_diagnostics']['evaluations'] > 0
    assert all(type(guard[key]) is int and guard[key] >= 0 for key in guard if key != 'escalated')
    assert type(guard['escalated']) is bool


def fragment():
    return json.loads(adapter().ACQUISITION.read_text())


def test_registration_signature_conforms_to_the_shared_schema():
    from ravel.validation import signature_conformance as conformance, validate_request_plan as plan
    mod = adapter()
    entry = fragment()['operation_signatures'][mod.MODE]
    assert conformance._schema_errors(entry, plan.SIGNATURE_SCHEMA, 'signature') == []
    assert entry['implementation'] == {'kind': 'science-mode', 'mode': mod.MODE, 'module': mod.__name__}
    slots = entry['consumes'] + entry['produces']
    assert all(conformance.known_kind(slot['kind']) for slot in slots)
    assert set(entry['basis']['passes']) <= {slot['slot'] for slot in entry['consumes']}
    assert all(tool == tool.strip() and not tool.startswith('re:') for tool in entry['tools'])
    result = mod.scan_pyhf(workspace(), mapping(), parameterization(), [{'k': 0.9}],
                           measurement='M0', signal_modifier='mu')
    assert [conformance.witness(slot['kind'], result) for slot in entry['produces']] == [[]]


def test_registration_descriptor_and_toolchain_rows_use_shared_shapes():
    from ravel.workflow import capability_routing
    mod = adapter()
    document = fragment()
    assert set(document['mode_descriptors']) == set(document['operation_signatures']) == {mod.MODE}
    row = document['mode_descriptors'][mod.MODE]
    assert set(row) == {*capability_routing.DESCRIPTOR_FIELDS, 'applicability'}
    assert type(row['summary']) is str and row['applicability'] == {'scope': 'general'}
    for key in capability_routing.DESCRIPTOR_FIELDS[1:]:
        assert type(row[key]) is list and all(type(term) is str and term.strip() for term in row[key])
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / 'native/setup/toolchain-manifest.json').read_text())
    groups = {group['id'] for group in manifest['groups']}
    assert [set(r) for r in document['manifest_operations']] == [{'mode', 'groups'}]
    assert document['manifest_operations'][0]['mode'] == mod.MODE
    assert set(document['manifest_operations'][0]['groups']) <= groups
