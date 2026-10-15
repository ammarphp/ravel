"""Supplied selection discovery, binding and missing-input boundaries."""
import json
from pathlib import Path

import pytest

from ravel.physics import native_capabilities as capabilities
from ravel.physics import native_pipeline, native_simpleanalysis, stau_adapter


def test_native_admission_has_no_installed_analysis_population(monkeypatch):
    monkeypatch.delenv('RAVEL_ANALYSIS_PACKAGES', raising=False)
    monkeypatch.delenv('RAVEL_ANALYSIS_PACKAGE', raising=False)
    assert not capabilities.CAPABILITIES


def test_missing_native_adapter_binding_is_typed(tmp_path):
    config = tmp_path / 'config.toml'
    config.write_text('[simpleanalysis]\nname = "ANA-0001"\n')
    with pytest.raises(ValueError) as caught:
        native_pipeline.build_execution_plan(tmp_path, config)
    assert getattr(caught.value, 'reason', None) == 'missing_native_binding'


def test_selection_is_never_implicitly_installed(monkeypatch):
    monkeypatch.delenv('RAVEL_ANALYSIS_PACKAGE', raising=False)
    with pytest.raises(ValueError) as caught:
        native_simpleanalysis.sr_order()
    assert getattr(caught.value, 'reason', None) == 'missing_analysis_package'


def test_calibrated_projection_requires_selected_package():
    with pytest.raises(ValueError) as caught:
        stau_adapter.validate_document({})
    assert getattr(caught.value, 'reason', None) == 'missing_analysis_package'


def test_channel_mapping_already_requires_complete_supplied_input():
    from ravel.physics.sa2json_native import compressed_channel_map, MissingChannelMap
    with pytest.raises(MissingChannelMap):
        compressed_channel_map({'channels': []})


def test_generic_normalization_already_has_no_luminosity_default(tmp_path):
    import argparse
    import json
    from ravel.physics.native_sa_generic import cmd_run, MissingAnalysisInput
    spec = tmp_path / 'selection.json'
    spec.write_text(json.dumps({'name': 'ANA-0001'}))
    with pytest.raises(MissingAnalysisInput):
        cmd_run(argparse.Namespace(spec=spec, lumi_fb=None))


def package(tmp_path, *, name='ANA-0001', qualified=True):
    import hashlib
    import json
    root = tmp_path / name
    root.mkdir()
    source = root / 'selection.py'
    source.write_text('''NAME = "supplied"
FLAVOUR_FLAGS = ("first", "second")
def sr_order(): return ["selected"]
def select(arrays, i, *, parameters):
    return ({"selected"} if arrays["value"][i] > parameters["threshold"] else set(), True, False)
''')
    pin = {'path': 'selection.py', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    compatibility = {'models': ['c1n2-wz'], 'preparations': ['explicit-cards'],
                     'detectors': ['simpleanalysis-delphes'], 'statistics': ['yields', 'mapped-likelihood']}
    evidence = root / 'qualification.json'
    evidence.write_text(json.dumps({'schema_version': 1, 'kind': 'routine-qualification',
        'status': 'passed', 'interface_version': 1, 'selection_sha256': pin['sha256'],
        'compatibility': compatibility, 'checks': [{'name': 'synthetic-interface', 'passed': True, 'reference': 1., 'computed': 1., 'rtol': 0., 'atol': 0.}]}))
    manifest = {'schema_version': 1, 'kind': 'analysis-package', 'package_id': name, 'package_version': '1.0',
        'analysis_ids': [name], 'compatibility': compatibility,
        'routine': {**pin, 'kind': 'counting', 'regions': ['selected'], 'flavour_flags': ['first', 'second'],
                    'accepts_parameters': True, 'helper_outputs': [], 'arguments': []},
        'qualification': {'status': 'qualified' if qualified else 'pending', 'evidence':
            [{'path': 'qualification.json', 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}] if qualified else []}}
    path = root / 'manifest.json'
    path.write_text(json.dumps(manifest))
    return path


def test_discovery_reads_metadata_without_importing_selection(tmp_path, monkeypatch):
    from ravel.physics.analysis_packages import discover
    path = package(tmp_path)
    import hashlib, json
    source = path.parent / 'selection.py'
    source.write_text('raise AssertionError("metadata discovery executed supplied source")\n')
    document = json.loads(path.read_text())
    document['routine']['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    document['qualification'] = {'status': 'pending', 'evidence': []}
    path.write_text(json.dumps(document))
    monkeypatch.setenv('RAVEL_ANALYSIS_PACKAGES', str(tmp_path))
    rows = discover()
    from ravel.physics.analysis_packages import SHIPPED_ROOT
    shipped = {json.loads(p.read_text())['package_id'] for p in SHIPPED_ROOT.glob('*/manifest.json')}
    assert shipped and shipped < set(rows)
    assert [name for name in rows if name not in shipped] == ['ANA-0001']
    assert rows['ANA-0001']['physics_certified'] is False


def test_supplied_package_admission_and_mutation_are_fail_closed(tmp_path):
    from ravel.physics.analysis_packages import load_package, PackageInputError
    path = package(tmp_path)
    assert load_package(path, require_qualification=True)['package_id'] == 'ANA-0001'
    (path.parent / 'selection.py').write_text('raise RuntimeError("must not import")')
    with pytest.raises(PackageInputError) as caught:
        load_package(path, require_qualification=True)
    assert caught.value.reason == 'package_source_changed'


def test_pending_package_cannot_admit_native_execution(tmp_path):
    from ravel.physics.analysis_packages import load_package, PackageInputError
    path = package(tmp_path, qualified=False)
    with pytest.raises(PackageInputError) as caught:
        load_package(path, require_qualification=True)
    assert caught.value.reason == 'missing_package_qualification'


def test_two_contracts_change_identity_grid_population_and_format(tmp_path):
    import json
    from ravel.physics.analysis_packages import evaluate_contract, PackageInputError
    path = package(tmp_path)
    first = {'study_id': 'ANA-0001', 'analysis_package': str(path),
             'parameter_points': [{'threshold': 2}], 'dataset': {'arrays': {'value': [1, 3]}, 'weights': [1., 2.]},
             'output': {'format': 'json', 'path': str(tmp_path / 'first.json')}}
    second = {'study_id': 'ANA-0002', 'analysis_package': str(path),
              'parameter_points': [{'threshold': 0}, {'threshold': 4}],
              'dataset': {'arrays': {'value': [1, 3, 5]}, 'weights': [1., 2., -1.]},
              'output': {'format': 'jsonl', 'path': str(tmp_path / 'second.jsonl')}}
    a, b = evaluate_contract(first), evaluate_contract(second)
    assert a['study_id'] == first['study_id'] and a['points'][0]['sumw'] == {'selected': 2.}
    assert [point['parameters'] for point in b['points']] == second['parameter_points']
    assert [point['sumw'] for point in b['points']] == [{'selected': 2.}, {'selected': -1.}]
    assert a['events'] == 2 and b['events'] == 3
    assert json.loads(Path(first['output']['path']).read_text()) == a
    assert len(Path(second['output']['path']).read_text().splitlines()) == 2
    del first['dataset']
    with pytest.raises(PackageInputError) as caught:
        evaluate_contract(first)
    assert caught.value.reason == 'missing_dataset'


def test_generic_qualification_compares_supplied_values_and_binds_source(tmp_path):
    import json
    from ravel.physics.analysis_packages import qualify_package, PackageInputError
    path = package(tmp_path, qualified=False)
    output = tmp_path / 'comparison.json'
    report = qualify_package(path, reference={'count': 3., 'weight': 1.5},
                             computed={'count': 3., 'weight': 1.5001},
                             tolerances={'count': {'rtol': 0., 'atol': 0.},
                                         'weight': {'rtol': 0., 'atol': .001}}, output=output)
    assert report['status'] == 'passed' and json.loads(output.read_text()) == report
    assert report['selection_sha256'] == json.loads(path.read_text())['routine']['sha256']
    with pytest.raises(PackageInputError) as caught:
        qualify_package(path, reference={'count': 3.}, computed={}, tolerances={}, output=tmp_path / 'bad.json')
    assert caught.value.reason == 'missing_qualification_values'


def test_native_bindings_cannot_fall_through_to_another_adapter(tmp_path):
    import json
    from test_native_dispatch import configuration
    from ravel.physics.analysis_packages import PackageInputError
    config = configuration(tmp_path)
    manifest = tmp_path / 'packages' / 'fictional' / 'manifest.json'
    document = json.loads(manifest.read_text())
    document['compatibility']['preparations'] = ['unimplemented-adapter']
    # Admission must reject an unimplemented binding before reading qualification or cards.
    config.write_text(config.read_text().replace('preparation = "explicit-cards"', 'preparation = "unimplemented-adapter"'))
    with pytest.raises(PackageInputError) as caught:
        native_pipeline.build_execution_plan(tmp_path, config)
    assert caught.value.reason == 'unsupported_native_binding'


def test_two_native_contracts_bind_distinct_populations_and_outputs(tmp_path):
    import json
    from test_native_dispatch import configuration, workspace
    from analysis_package_fixtures import native_package
    from ravel.physics.analysis_packages import PackageInputError
    plans = []
    for index, (identity, population, grid, statistics) in enumerate([
        ('ANA-0001', 2, [{'parent': 300, 'child': 100}], 'yields'),
        ('ANA-0002', 3, [{'parent': 300, 'child': 100}, {'parent': 400, 'child': 80}], 'mapped-likelihood')]):
        root = tmp_path / str(index)
        root.mkdir()
        path = configuration(root, statistics)
        native_package(root / 'packages' / 'selected', identity, ['selected'], models=['c1n2-wz'])
        text = path.read_text().replace('FictionalRoutine700', identity).replace('packages/fictional/manifest.json', 'packages/selected/manifest.json')
        text = text.replace('nevents = 2', 'nevents = ' + str(population))
        (root / 'cards/run.dat').write_text((root / 'cards/run.dat').read_text().replace('2 = nevents', str(population) + ' = nevents'))
        if statistics == 'mapped-likelihood':
            (root / 'workspace.json').write_text(json.dumps(workspace()))
            (root / 'channels.json').write_text(json.dumps({'A': {'region': 'selected'}}))
            text += 'likelihood = "workspace.json"\nchannel_map = "channels.json"\n'
        path.write_text(text)
        plans.append(native_pipeline.build_execution_plan(root, path, analysis_id=identity, campaign_points=len(grid)))
    first, second = plans
    assert [p['capability']['routine'] for p in plans] == ['ANA-0001', 'ANA-0002']
    assert [p['nevents'] for p in plans] == [2, 3]
    assert [p['campaign_points'] for p in plans] == [1, 2]
    assert 'sa2json' not in [s['stage'] for s in first['stages']]
    assert 'sa2json' in [s['stage'] for s in second['stages']]
    assert all(p['compute_authorized'] is False for p in plans)
    config = Path(second['config'])
    config.write_text(config.read_text().replace('detector = "simpleanalysis-delphes"\n', ''))
    with pytest.raises(PackageInputError) as caught:
        native_pipeline.build_execution_plan(second['rundir'], config)
    assert caught.value.reason == 'missing_native_binding'


def test_trace_selection_source_comes_from_its_supplied_package(tmp_path):
    import hashlib
    from ravel.physics.analysis_packages import selection_source_from_metadata, PackageInputError
    path = package(tmp_path, qualified=False)
    source, pins = selection_source_from_metadata({'analysis_package': {
        'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}})
    assert source['path'] == str(path.parent / 'selection.py') and len(pins) == 2
    with pytest.raises(PackageInputError) as caught:
        selection_source_from_metadata({})
    assert caught.value.reason == 'missing_analysis_package'


def test_launch_cannot_use_a_plan_without_its_package_binding(tmp_path):
    from test_native_dispatch import configuration
    from ravel.physics.analysis_packages import PackageInputError
    plan = native_pipeline.build_execution_plan(tmp_path, configuration(tmp_path))
    del plan['capability']['analysis_package']
    plan['plan_sha256'] = native_pipeline.plan_hash(plan)
    with pytest.raises(PackageInputError) as caught:
        native_pipeline.verify_execution_approval(plan)
    assert caught.value.reason == 'missing_analysis_package'


def test_launch_requires_all_selected_package_sources_in_plan(tmp_path):
    from test_native_dispatch import configuration
    from ravel.physics.analysis_packages import PackageInputError
    plan = native_pipeline.build_execution_plan(tmp_path, configuration(tmp_path))
    manifest = plan['capability']['analysis_package']
    plan['sources'] = [pin for pin in plan['sources'] if pin['path'] != manifest]
    plan['plan_sha256'] = native_pipeline.plan_hash(plan)
    with pytest.raises(PackageInputError) as caught:
        native_pipeline.verify_execution_approval(plan)
    assert caught.value.reason == 'missing_package_source_binding'


def test_launch_rechecks_package_compatibility(tmp_path):
    from test_native_dispatch import configuration
    from ravel.physics.analysis_packages import PackageInputError
    plan = native_pipeline.build_execution_plan(tmp_path, configuration(tmp_path))
    plan['capability']['model'] = 'unsupported-model'
    plan['plan_sha256'] = native_pipeline.plan_hash(plan)
    with pytest.raises(PackageInputError) as caught:
        native_pipeline.verify_execution_approval(plan)
    assert caught.value.reason == 'unsupported_package_binding'


@pytest.mark.parametrize('module', ['ravel.physics.stau_adapter', 'ravel.physics.native_simpleanalysis',
                                    'ravel.physics.sa_routines.routine002'])
def test_optional_attribute_probes_do_not_require_an_ambient_selection(module, monkeypatch):
    import importlib
    monkeypatch.delenv('RAVEL_ANALYSIS_PACKAGE', raising=False)
    selected = importlib.import_module(module)
    # Workflow adapters probe optional hooks with getattr(..., None); a probe is not a selection request.
    assert getattr(selected, 'helper_declaration', None) is None
    assert not hasattr(selected, 'owner_limits')
    with pytest.raises(ValueError) as caught:
        selected.sr_order
    assert caught.value.reason == 'missing_analysis_package'
