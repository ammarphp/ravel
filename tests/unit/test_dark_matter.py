"""Fictional supplied models and inert driver transports; no native physics runs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest


def request():
    return {'schema_version': 1, 'study_id': 'ANA-0001',
            'model': {'id': 'fictional-scalar', 'format': 'calchep', 'candidate': '~a',
                      'particles': [{'name': '~a', 'mass_gev': 80., 'odd': True}],
                      'coannihilation_partners': [], 'delta_m_fraction': .15,
                      'coupling_conventions': 'Supplied fictional coefficient convention'},
            'parameters': {'mass': 80., 'coupling': .23},
            'calculation': {'freeze_out': 'supplied thermal prescription',
                            'today_velocity_c': .001, 'today_rate_definition': 'supplied velocity average',
                            'channel_fraction_cutoff': .01},
            'astrophysics': {'local_density_gev_cm3': .31,
                             'velocity_distribution': {'family': 'fictional-law', 'scale_km_s': 221.},
                             'density_fraction': 1.},
            'report': {'filename': 'selected.json', 'format': 'json'}}


def raw_result():
    return {'schema_version': 1, 'status': 'ok', 'candidate': '~a', 'mass_gev': 80.,
            'omega_h2': .17, 'xf': 22., 'channel_fraction_remainder': 0.,
            'channels': [{'fraction': .7, 'incoming': ['~a', '~a'], 'outgoing': ['b', 'bbar']},
                         {'fraction': .3, 'incoming': ['~a', '~a'], 'outgoing': ['v', 'v']}],
            'sigma_si_p_cm2': 2e-44, 'sigma_si_n_cm2': 3e-44,
            'sigma_sd_p_cm2': 4e-44, 'sigma_sd_n_cm2': 5e-44,
            'sigma_v_today_cm3_s': 6e-26}


def reference(value=2., *, quantity='coupling', units='1', conditions=None):
    quote = f'{quantity} = {value}'
    extracted = 'Table A\n' + quote
    return {'id': 'qual:fictional-tool:' + quantity, 'tool': 'fictional-tool', 'quantity': quantity,
            'source': {'arxiv': None, 'doi': None, 'hepdata': None,
                       'url': 'https://example.invalid/fictional-source', 'licence': 'synthetic'},
            'locator': 'Table A', 'value': value,
            'uncertainty': {'minus': None, 'plus': None, 'definition': 'synthetic central value'},
            'units': units, 'conditions': conditions or {'mass_gev': 80.},
            'extraction_method': 'table', 'extracted_by': 'synthetic fixture', 'status': 'filled',
            'evidence': {'text_sha256': hashlib.sha256(extracted.encode()).hexdigest(),
                         'quote': quote, 'value_literal': str(value)}}, extracted


def test_missing_close_coannihilation_partner_refused():
    from ravel.physics import dark_matter as dm
    doc = request()
    doc['model']['coannihilation_partners'] = [{'name': '~b', 'mass_gev': 84.}]
    with pytest.raises(dm.DarkMatterInputError, match='~b.*0.15'):
        dm.validate_request(doc)


@pytest.mark.parametrize('field', ['local_density_gev_cm3', 'velocity_distribution', 'density_fraction'])
def test_direct_detection_convention_mismatch_names_both(field):
    from ravel.physics import dark_matter as dm
    doc = request()
    limit_halo = deepcopy(doc['astrophysics'])
    limit_halo[field] = {'family': 'different-law', 'scale_km_s': 231.} if field == 'velocity_distribution' else .6
    row, text = reference(4e-44, quantity='sigma-si-p', units='cm^2',
                          conditions={'mass_gev': 80., 'astrophysics': limit_halo,
                                      'interaction': 'si', 'nucleon': 'p'})
    with pytest.raises(dm.DarkMatterInputError) as exc:
        dm.compare_direct_detection(dm.parse_driver_output(json.dumps(raw_result()), doc), row, text=text)
    assert 'computed' in str(exc.value) and 'limit' in str(exc.value)
    assert repr(doc['astrophysics'][field]) in str(exc.value)
    assert repr(limit_halo[field]) in str(exc.value)


@pytest.mark.parametrize('mutation', ['missing', 'nonfinite', 'negative', 'duplicate', 'bad-status', 'channels', 'candidate'])
def test_malformed_driver_output_refused(mutation):
    from ravel.physics import dark_matter as dm
    row = raw_result()
    if mutation == 'missing': del row['xf']
    elif mutation == 'nonfinite': row['omega_h2'] = float('nan')
    elif mutation == 'negative': row['sigma_si_p_cm2'] = -1.
    elif mutation == 'bad-status': row['status'] = 'failed'
    elif mutation == 'channels': row['channels'][0]['fraction'] = 1.5
    elif mutation == 'candidate': row['candidate'] = '~different'
    raw = json.dumps(row)
    if mutation == 'duplicate': raw = raw[:-1] + ',"omega_h2":0.5}'
    with pytest.raises(ValueError): dm.parse_driver_output(raw, request())


def test_planted_wrong_reference_row_fails():
    from ravel.physics import dark_matter as dm
    row, text = reference()
    with pytest.raises(dm.DarkMatterInputError, match='tolerance'):
        dm.compare_reference(3., row, units='1', conditions={'mass_gev': 80.},
                             relative_tolerance=.1, text=text)


def test_reference_condition_mismatch_refused():
    from ravel.physics import dark_matter as dm
    row, text = reference()
    with pytest.raises(dm.DarkMatterInputError, match='conditions'):
        dm.compare_reference(2., row, units='1', conditions={'mass_gev': 81.},
                             relative_tolerance=.1, text=text)


def test_model_source_mutation_refused(tmp_path):
    from ravel.physics import dark_matter as dm
    path = tmp_path / 'particles.mdl'; path.write_text('fictional model')
    pin = {'path': str(path), 'size': path.stat().st_size,
           'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    path.write_text('changed model')
    with pytest.raises(ValueError, match='pin'):
        dm.model_sources({'particles.mdl': pin}, tmp_path)


def test_unapproved_run_refuses_before_native_or_output(tmp_path, monkeypatch):
    from ravel.physics import dark_matter as dm
    from ravel.physics import reinterpret_db
    monkeypatch.setattr(reinterpret_db, 'execute_native', lambda *a, **k: pytest.fail('native launch'))
    with pytest.raises(ValueError, match='approved'):
        dm.run({'config': {}}, tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_program_table_dependency_has_no_study_branch():
    from ravel.physics import parameter_space_sampling_core as core
    fragment = json.loads((Path(__file__).parents[2] / 'src/ravel/data/tools/registration/dark-matter-observables.programmes.json').read_text())
    assert fragment['programme_rows']['micromegas']['parser'] == 'ravel.physics.dark_matter.parse_driver_output'
    assert fragment['programme_rows']['micromegas']['following_programmes'] == ['phasetracer']
    if not hasattr(core, 'PROGRAMME_TABLE'):
        pytest.xfail('awaits scan-contract programme table')
    assert core.PROGRAMME_TABLE['micromegas'] == fragment['programme_rows']['micromegas']


def pin_file(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def write_pin(path, value):
    path.write_text(json.dumps(value))
    return pin_file(path)


def test_source_decision_cannot_authenticate_another_tree(tmp_path):
    from ravel.physics import dark_matter as dm
    source = tmp_path / 'source'; source.mkdir()
    unrelated = tmp_path / 'other'; unrelated.mkdir()
    licence = unrelated / 'LICENSE'; licence.write_text('fictional licence')
    decision = tmp_path / 'decision.json'
    write_pin(decision, {'tool': 'micromegas', 'version': 'fictional-version',
                         'files': {'LICENSE': pin_file(licence)}, 'licence': 'LICENSE',
                         'licence_sha256': pin_file(licence)['sha256'], 'redistribute': False})
    with pytest.raises(dm.DarkMatterInputError, match='source root'):
        dm.build_preflight(source, decision)


def test_driver_cannot_claim_different_rate_prescription():
    from ravel.physics import dark_matter as dm
    doc = request()
    doc['calculation'].pop('today_rate_definition', None)
    with pytest.raises(ValueError, match='calculation'):
        dm.validate_request(doc)


def test_delivery_scope_cannot_grant_physics_acceptance():
    from ravel.physics import dark_matter as dm
    with pytest.raises(ValueError, match='delivery'):
        dm.validate_scope({'schema_version': 2, 'max_attempts': 1,
                           'review_policy': {'policy': {'max_redos': 0, 'claim_scopes': {
                               dm.SCOPE: {'actions': ['accept']}}}}})


def execution_fixture(tmp_path, monkeypatch):
    from ravel.physics import dark_matter as dm
    from ravel.workflow import science
    rd = tmp_path / 'run'; (rd / 'inputs').mkdir(parents=True)
    (rd / 'inputs/science-plan.json').write_text('{}')
    model = tmp_path / 'particles.mdl'; model.write_text('fictional supplied model')
    binding = tmp_path / 'binding.c'; binding.write_text('/* fictional uncompiled binding */')
    binary = tmp_path / 'main'; binary.write_text('# inert binary, never executed\n'); binary.chmod(0o755)
    doc = request()
    tool = tmp_path / 'tool'; tool.mkdir()
    licence = tool / 'LICENSE'; licence.write_text('fictional external-program licence')
    decision = {'tool': 'micromegas', 'version': 'fictional-version',
                'files': {'LICENSE': pin_file(licence)}, 'licence': 'LICENSE',
                'licence_sha256': pin_file(licence)['sha256'], 'redistribute': False}
    conf = {'schema_version': 1, 'request': write_pin(tmp_path / 'request.json', doc),
            'tool': {'root': str(tool), 'decision': write_pin(tmp_path / 'decision.json', decision)},
            'model_files': {'particles.mdl': pin_file(model)},
            'binding_sources': {'binding.c': pin_file(binding)}, 'binary': pin_file(binary),
            'resources': {'max_seconds': 12, 'max_ram_mib': 512, 'max_output_bytes': 100000},
            'limits': []}
    task = {'config': write_pin(tmp_path / 'config.json', conf)}
    spec = {'schema_version': 2, 'mode': dm.MODE, 'task': task, 'max_attempts': 1,
            'review_policy': {'policy': {'max_redos': 0, 'claim_scopes': {
                dm.SCOPE: {'actions': ['delivery']}}}}}
    seen = []
    monkeypatch.setattr(science, 'verify_worker', lambda run: seen.append(run) or {
        'output_directory': 'outputs', 'max_seconds': 12})
    monkeypatch.setattr(science, 'execution_spec', lambda run: spec)
    return task, doc, conf, rd / 'outputs' / dm.MODE, seen


def test_fake_driver_transport_into_operation_result(tmp_path, monkeypatch):
    from ravel.physics import dark_matter as dm, reinterpret_db
    task, doc, conf, output, seen = execution_fixture(tmp_path, monkeypatch)
    calls = []
    def fake(command, native, resources):
        calls.append(command)
        assert json.loads(Path(command[1]).read_text()) == doc
        assert resources == conf['resources']
        Path(command[2]).write_text(json.dumps(raw_result()))
        return {'returncode': 0, 'command': command, 'wall_seconds': .001}
    monkeypatch.setattr(reinterpret_db, 'execute_native', fake)
    result = dm.run(task, tmp_path, output)
    assert len(seen) == len(calls) == 1
    assert result['observables']['omega_h2'] == .17
    assert result['observables']['xf'] == 22.
    assert result['observables']['sigma_sd_n_cm2'] == 5e-44
    assert result['observables']['sigma_v_today_cm3_s'] == 6e-26
    assert result['astrophysics'] == doc['astrophysics']
    assert result['model']['coupling_conventions'] == doc['model']['coupling_conventions']
    assert json.loads((output / doc['report']['filename']).read_text()) == result
    assert result['physics_validated'] is False and result['execution_authorized'] is False
    assert dm.context(task, tmp_path)['execution_authorized'] is False
    assert dm.execution_seconds(task, tmp_path) == 12


def test_fake_driver_nonzero_preserves_failed_native_output(tmp_path, monkeypatch):
    from ravel.physics import dark_matter as dm, reinterpret_db
    task, doc, _, output, _ = execution_fixture(tmp_path, monkeypatch)
    def fake(command, native, resources):
        (native / 'native-stderr.log').write_text('fictional numerical failure')
        Path(command[2]).write_text('partial output')
        return {'returncode': 2}
    monkeypatch.setattr(reinterpret_db, 'execute_native', fake)
    with pytest.raises(ValueError, match='driver failed'): dm.run(task, tmp_path, output)
    assert (output / 'native/driver.json').read_text() == 'partial output'
    assert not (output / doc['report']['filename']).exists()


def test_executor_refusal_is_reported_as_driver_failure(tmp_path, monkeypatch):
    """The native executor raises on a nonzero exit or a resource violation."""
    from ravel.physics import dark_matter as dm, reinterpret_db
    task, doc, _, output, _ = execution_fixture(tmp_path, monkeypatch)
    def fake(command, native, resources):
        Path(command[2]).write_text('partial output')
        raise ValueError('native execution exceeded time ceiling')
    monkeypatch.setattr(reinterpret_db, 'execute_native', fake)
    with pytest.raises(dm.DarkMatterInputError, match='driver failed.*time ceiling'):
        dm.run(task, tmp_path, output)
    assert (output / 'native/driver.json').read_text() == 'partial output'
    assert not (output / doc['report']['filename']).exists()


def test_returned_driver_mutation_is_refused(tmp_path, monkeypatch):
    from ravel.physics import dark_matter as dm, reinterpret_db
    task, _, _, output, _ = execution_fixture(tmp_path, monkeypatch)
    def fake(command, native, resources):
        Path(command[2]).write_text(json.dumps(raw_result()))
        return {'returncode': 0}
    monkeypatch.setattr(reinterpret_db, 'execute_native', fake)
    original = dm.publish
    def mutate(*args):
        result = original(*args)
        (output / 'native/driver.json').write_text('{}')
        return result
    monkeypatch.setattr(dm, 'publish', mutate)
    with pytest.raises(ValueError, match='pin'): dm.run(task, tmp_path, output)


@pytest.mark.parametrize('identity,parameters,filename,format_', [
    ('ANA-0001', {'x': .4}, 'alpha.json', 'json'),
    ('ANA-0002', {'y': -.2, 'z': 2.}, 'beta.json', 'json-compact')])
def test_supplied_identity_parameters_and_output_are_preserved(identity, parameters, filename, format_):
    from ravel.physics import dark_matter as dm
    doc = request(); doc.update(study_id=identity, parameters=parameters)
    doc['report'] = {'filename': filename, 'format': format_}
    result = dm.parse_driver_output(json.dumps(raw_result()), doc)
    assert result['study_id'] == identity and result['parameters'] == parameters


def test_distant_missing_partner_does_not_trigger_close_threshold():
    from ravel.physics import dark_matter as dm
    doc = request()
    doc['model']['coannihilation_partners'] = [{'name': '~b', 'mass_gev': 120.}]
    assert dm.validate_request(doc) == doc


def test_matching_limit_and_reference_pass():
    from ravel.physics import dark_matter as dm
    doc = request(); result = dm.parse_driver_output(json.dumps(raw_result()), doc)
    row, text = reference(4e-44, quantity='sigma-si-p', units='cm^2', conditions={
        'mass_gev': 80., 'astrophysics': doc['astrophysics'], 'interaction': 'si', 'nucleon': 'p'})
    comparison = dm.compare_direct_detection(result, row, text=text)
    assert comparison['ratio'] == .5 and comparison['above_limit'] is False
    row, text = reference()
    assert dm.compare_reference(2.1, row, units='1', conditions={'mass_gev': 80.},
                                relative_tolerance=.1, text=text)['status'] == 'passed'


@pytest.mark.parametrize('intervals,identity', [(2, 'ANA-0001'), (4, 'ANA-0002')])
def test_supplied_chained_grid_validates_without_fixed_population(tmp_path, monkeypatch, intervals, identity):
    from ravel.physics import parameter_space_sampling_core as core
    from test_parameter_space_sampling import fixture
    _, doc, ini = fixture(tmp_path, monkeypatch, method='GRID')
    doc['study_id'] = identity
    raw = ini.read_text().replace('x, flat, 0, 1, 1', f'x, flat, 0, 1, {intervals}')
    raw = raw.replace('Program name: synthetic', 'Program name: micromegas')
    raw += '\n[program2]\nProgram name: phasetracer\nExecute command: ./inert-phase\nCommand path: tools/\nInput file: 1, tools/out.txt\nInput variable: f, 1, Position, 1, 1\nOutput file: 1, tools/phase.txt\nOutput variable: transition, 1, Position, 1, 1\n'
    doc['programmes'].append({'section': 'program2', 'inputs': ['tools/out.txt'],
                             'outputs': ['tools/phase.txt'], 'intermediates': [],
                             'mutable_paths': [], 'units': {'transition': 'GeV'}, 'status': 'native'})
    assert core.config(doc) == doc
    result = core.ini(raw.encode(), doc)
    assert result['grid_population'] == (intervals + 1) * 2
    assert list(k for k in result['projection'] if k.startswith('program')) == ['program1', 'program2']


@pytest.mark.parametrize('format_', ['calchep', 'ufo'])
def test_source_package_staged_without_model_import(tmp_path, monkeypatch, format_):
    from ravel.physics import dark_matter as dm
    from collections import namedtuple
    import shutil
    Usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: Usage(100 * 1024**3, 0, 100 * 1024**3))
    makefile = tmp_path / 'Makefile'; makefile.write_text('main:\n\t@false # never executed\n')
    source = tmp_path / ('model.mdl' if format_ == 'calchep' else 'particles.py')
    source.write_text('raise RuntimeError("must never import UFO")')
    binding = tmp_path / 'binding.c'; binding.write_text('/* inert source */')
    package = {'model': 'fictional-model', 'files': {'Makefile': pin_file(makefile), source.name: pin_file(source)},
               'binding_files': {'binding.c': pin_file(binding)}}
    target = dm.prepare_model(package, tmp_path, tmp_path / 'data')
    assert target == tmp_path / 'data/fictional-model'
    assert (target / source.name).read_bytes() == source.read_bytes()
    assert 'ravel_dm_evaluate' in (target / 'main.c').read_text()
    assert (target / 'driver.h').exists()
    with pytest.raises(ValueError, match='fresh'): dm.prepare_model(package, tmp_path, tmp_path / 'data')


def test_science_dispatch_registration_dependency():
    from ravel.physics import dark_matter as dm
    from ravel.workflow import science
    if dm.MODE not in science.MODES:
        pytest.xfail('awaits registry integration')
    assert science.adapter({'mode': dm.MODE}) is dm


def test_native_budget_refused_before_driver(tmp_path, monkeypatch):
    from ravel.physics import dark_matter as dm, reinterpret_db
    task, _, config, output, _ = execution_fixture(tmp_path, monkeypatch)
    config['resources']['max_seconds'] = 13
    task['config'] = write_pin(tmp_path / 'config.json', config)
    monkeypatch.setattr(reinterpret_db, 'execute_native', lambda *a, **k: pytest.fail('driver launch'))
    with pytest.raises(ValueError, match='budget'): dm.run(task, tmp_path, output)
    assert not output.exists()


def test_native_output_population_ceiling_refused(tmp_path, monkeypatch):
    from ravel.physics import dark_matter as dm, reinterpret_db
    task, _, config, output, _ = execution_fixture(tmp_path, monkeypatch)
    def fake(command, native, resources):
        Path(command[2]).write_text(json.dumps(raw_result()))
        (native / 'unexpected.log').write_bytes(b'x' * (resources['max_output_bytes'] + 1))
        return {'returncode': 0}
    monkeypatch.setattr(reinterpret_db, 'execute_native', fake)
    with pytest.raises(ValueError, match='output.*ceiling'): dm.run(task, tmp_path, output)


def test_future_driver_symlink_refused(tmp_path, monkeypatch):
    from ravel.physics import dark_matter as dm, reinterpret_db
    task, _, _, output, _ = execution_fixture(tmp_path, monkeypatch)
    outside = tmp_path / 'outside.json'; outside.write_text(json.dumps(raw_result()))
    def fake(command, native, resources):
        Path(command[2]).symlink_to(outside)
        return {'returncode': 0}
    monkeypatch.setattr(reinterpret_db, 'execute_native', fake)
    with pytest.raises(ValueError): dm.run(task, tmp_path, output)


def test_execution_requires_tool_source_decision(tmp_path, monkeypatch):
    from ravel.physics import dark_matter as dm
    task, _, config, _, _ = execution_fixture(tmp_path, monkeypatch)
    config.pop('tool', None)
    task['config'] = write_pin(tmp_path / 'config.json', config)
    with pytest.raises(ValueError, match='execution config'):
        dm.inputs(task, tmp_path)


@pytest.mark.parametrize('x11', [True, False])
def test_build_recipe_uses_fake_tools_and_requires_x11(tmp_path, x11):
    import os
    import subprocess
    source = tmp_path / 'tool'; (source / 'sources').mkdir(parents=True)
    (source / 'CalcHEP_src/bin').mkdir(parents=True)
    envdir = tmp_path / 'env'; (envdir / 'conda-meta').mkdir(parents=True)
    (envdir / 'bin').mkdir()
    if x11:
        (envdir / 'include/X11').mkdir(parents=True)
        (envdir / 'include/X11/Xlib.h').write_text('fictional header')
    fake_python = tmp_path / 'fake-python'
    fake_python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_CALLS"\n')
    fake_python.chmod(0o755)
    fake_make = envdir / 'bin/make'
    fake_make.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_CALLS"\n'
                         ': > "$FAKE_SOURCE/sources/micromegas.a"\n'
                         'printf "#!/bin/sh\\nexit 0\\n" > "$FAKE_SOURCE/CalcHEP_src/bin/s_calchep"\n'
                         'chmod +x "$FAKE_SOURCE/CalcHEP_src/bin/s_calchep"\n')
    fake_make.chmod(0o755)
    calls = tmp_path / 'calls'
    recipe = Path(__file__).parents[2] / 'native/setup/recipes/build-micromegas.sh'
    argv = ['/bin/bash', str(recipe), '--src', str(source), '--env', str(envdir),
            '--decision', str(tmp_path / 'decision.json')]
    environment = dict(os.environ, FAKE_CALLS=str(calls), FAKE_SOURCE=str(source))
    process = subprocess.run(argv, capture_output=True, text=True, timeout=10, env=environment)
    if x11:
        assert process.returncode != 0 and 'source decision record missing' in process.stderr
        assert not calls.exists()
        (tmp_path / 'decision.json').write_text('{}')
        process = subprocess.run(argv, capture_output=True, text=True, timeout=10, env=environment)
        assert process.returncode == 0, process.stderr
        assert '-C ' + str(source) in calls.read_text()
    else:
        assert process.returncode != 0 and 'X11 headers required' in process.stderr
        assert not calls.exists()
    # The recipe builds restricted code, so it takes no interpreter: the preflight is its own installer step.
    calls.unlink(missing_ok=True)
    handed = subprocess.run([*argv, '--python', str(fake_python)], capture_output=True, text=True, timeout=10,
                            env=environment)
    assert handed.returncode != 0 and 'unknown argument --python' in handed.stderr
    assert not calls.exists()


@pytest.mark.parametrize('held', [True, False])
def test_new_group_identity_expectation_preserves_profile_and_disk(tmp_path, held):
    from group_fragment_fixture import extend_group_expectation
    main = {'group_order': ['fictional-base'], 'groups': [],
            'default': {'groups': ['fictional-base'], 'disk_gb': 1.},
            'profiles': {'site': {'groups': ['fictional-base'], 'disk_gb': 1.}},
            'unreleased': {'groups': [], 'operations': []}}
    wrapper = {'group': {'id': 'fictional-child', 'depends_on': ['fictional-base'], 'size_gb': .25}}
    if held:
        wrapper['unreleased'] = {'groups': [{'id': 'fictional-child', 'check': 'fictional-ready', 'reason': 'fictional hold'}], 'operations': []}
    directory = tmp_path / 'native/setup/groups'; directory.mkdir(parents=True)
    (directory / 'fictional-child.json').write_text(json.dumps(wrapper))
    expected = extend_group_expectation(main, tmp_path)
    assert expected['group_order'] == ['fictional-base', 'fictional-child']
    assert expected['profiles'] == main['profiles']
    assert expected['default']['disk_gb'] == (1. if held else 1.25)
    assert ('fictional-child' in expected['default']['groups']) is not held
    assert main['group_order'] == ['fictional-base']


def test_reference_boundary_is_inclusive():
    from ravel.physics import dark_matter as dm
    row, text = reference()
    assert dm.compare_reference(2.2, row, units='1', conditions={'mass_gev': 80.},
                                relative_tolerance=.1, text=text)['status'] == 'passed'


