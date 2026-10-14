"""Supplied fictional scan contracts; all native dispatch is replaced by a fake."""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.physics import parameter_space_sampling_core as core, parameter_space_sampling as adapter
from test_parameter_space_sampling import fixture, pin, write


def supplied(tmp_path, monkeypatch):
    task, doc, ini = fixture(tmp_path, monkeypatch, method='GRID')
    doc.pop('original_task', None)
    doc.update(schema_version=2, study_id='ANA-0001',
               report={'format': 'json', 'path': 'selected.json', 'table': 'result/ScanResult.txt'})
    return task, doc, ini


def test_no_installed_question_population():
    assert not hasattr(core, 'POPULATION')
    assert not (core.DATA / 'original-population.json').exists()


def test_supplied_identity_is_not_an_admission_selector(tmp_path, monkeypatch):
    _, doc, _ = supplied(tmp_path, monkeypatch)
    assert core.config(doc)['study_id'] == 'ANA-0001'
    changed = deepcopy(doc)
    changed['study_id'] = 'ANA-0002'
    assert core.config(changed) == changed


def test_missing_mapping_refuses_before_external_inspection(tmp_path, monkeypatch):
    _, doc, ini = supplied(tmp_path, monkeypatch)
    ini.write_text(ini.read_text().replace('Output variable: f, 1, Position, 1, 1', 'Output variable:'))
    doc['ini'] = pin(ini)
    task = {'config': write(tmp_path / 'missing.json', doc)}
    monkeypatch.setattr(adapter, 'tree', lambda *a, **kw: pytest.fail('inspected external tree'))
    with pytest.raises(core.ScanInputError) as exc:
        adapter.inputs(task, tmp_path)
    assert exc.value.reason == 'missing_scan_input'
    assert exc.value.field == 'program1.Output variable'


def test_missing_sampler_resources_have_typed_reason(tmp_path, monkeypatch):
    _, doc, ini = supplied(tmp_path, monkeypatch)
    raw = ini.read_bytes().replace(b'Parallel threads: 1\n', b'')
    with pytest.raises(core.ScanInputError) as exc:
        core.ini(raw, doc)
    assert exc.value.reason == 'missing_scan_input'
    assert exc.value.field == 'scan.Parallel threads'


def test_legacy_identity_requires_explicit_migration(tmp_path, monkeypatch):
    _, doc, _ = fixture(tmp_path, monkeypatch)
    doc.pop('study_id', None)
    doc['original_task'] = 'ANA-0001'
    doc['schema_version'] = 1
    with pytest.raises(core.ScanInputError) as exc:
        core.config(doc)
    assert exc.value.reason == 'missing_scan_input'
    assert exc.value.field == 'study_id'


def test_two_supplied_contracts_run_same_adapter(tmp_path, monkeypatch):
    import itertools
    import json
    from ravel.physics import reinterpret_db

    expected = {}
    seen = []
    monkeypatch.setattr(adapter, '_approved', lambda task, out: (tmp_path, {'max_seconds': 20}))

    def fake_execute(command, native, resources):
        request = core.strict((native / 'request.json').read_bytes())
        doc, info = request['config'], request['info']
        work = Path(request['work'])
        assert (work / 'ravel-native.ini').read_bytes() == Path(doc['ini']['path']).read_bytes()
        data = [float(v) for v in (work / 'tools/in.txt').read_text().split()]
        axes = [[p['numeric'][0] + i * (p['numeric'][1] - p['numeric'][0]) / p['numeric'][2]
                 for i in range(int(p['numeric'][2]) + 1)] for p in info['parameters']]
        points = list(itertools.product(*axes))
        header = ','.join([p['name'] for p in info['parameters']] + ['f'])
        raw = header + '\n' + ''.join(','.join(map(str, [*point, sum(point) + sum(data)])) + '\n' for point in points)
        folder = work / info['result_folder']
        (folder / 'Figures').mkdir(parents=True)
        (folder / 'ScanResult.txt').write_text(raw)
        for name in info['figures']:
            (folder / 'Figures' / name).write_bytes(b'explicit inert image')
        write(native / 'observation.json', {'status': 'completed', 'counts': {'evaluations': len(points)},
                                          'workers': [], 'samplers': {}})
        expected[doc['study_id']] = raw.encode()
        seen.append((doc['study_id'], info['grid_population'], len(data), doc['report']['format']))
        return {'returncode': 0, 'inert_transport': True}

    monkeypatch.setattr(reinterpret_db, 'execute_native', fake_execute)
    results = []
    for ordinal, axes, data, fmt, plot in [
        (1, 'x, flat, 0, 1, 1\ny, flat, 0, 1, 1', '1 2', 'json', 'Color: x, y, f, selected'),
        (2, 'alpha, flat, 2, 5, 2\nbeta, flat, 10, 14, 1\ngamma, flat, -1, 1, 3', '3 4 5 6 7', 'csv', 'Histogram: f, distribution'),
    ]:
        root = tmp_path / str(ordinal)
        root.mkdir()
        _, doc, ini = supplied(root, monkeypatch)
        doc['study_id'] = 'ANA-000' + str(ordinal)
        folder = 'result' + str(ordinal)
        names = [row.split(',')[0] for row in axes.splitlines()]
        mappings = '\n  '.join(name + ', 1, Position, 1, ' + str(i) for i, name in enumerate(names, 1))
        ini.write_text('[scan]\nResult folder name: ' + folder + '\nScan method: GRID\nInput parameters: ' +
                       axes.replace('\n', '\n  ') + '\nParallel threads: 1\n[program1]\nProgram name: fictional\n' +
                       'Execute command: ./program.sh\nCommand path: tools/\nInput file: 1, tools/in.txt\n' +
                       'Input variable: ' + mappings + '\nOutput file: 1, tools/out.txt\n' +
                       'Output variable: f, 1, Position, 1, 1\n[plot]\n' + plot + '\n')
        (root / 'workspace/tools/in.txt').write_text(data)
        from test_parameter_space_sampling import manifest
        doc['workspace']['manifest'] = write(root / 'workspace.json', manifest(root / 'workspace'))
        doc['question'] = write(root / 'question.json', {'study_id': doc['study_id'], 'population': data.split()})
        doc['ini'] = pin(ini)
        doc['report'] = {'format': fmt, 'path': 'export.' + fmt, 'table': folder + '/ScanResult.txt'}
        task = {'config': write(root / 'contract.json', doc)}
        result = adapter.run(task, root, root / 'delivery/parameter-space-sampling')
        assert result['status'] == 'passed', result['errors']
        report = adapter.write_report(result, root / 'delivery')
        output = root / 'delivery' / doc['report']['path']
        assert report['selected_table'] == {'format': fmt, 'file': doc['report']['path'], 'table': doc['report']['table']}
        assert doc['report']['path'] in report['tables'][0]['files']
        if fmt == 'csv':
            assert output.read_bytes() == expected[doc['study_id']]
        else:
            assert json.loads(output.read_bytes()) == core.table(expected[doc['study_id']])
        assert result['programme_contracts'] == doc['programmes']
        assert result['delivery']['figures'] == [folder + '/Figures/' + name for name in result['native_configuration']['figures']]
        results.append(result)
    assert seen == [('ANA-0001', 4, 2, 'json'), ('ANA-0002', 24, 5, 'csv')]
    assert results[0]['config_identity'] != results[1]['config_identity']


def test_selected_migration_preserves_transform_constraint_and_intermediate(tmp_path, monkeypatch):
    _, doc, ini = supplied(tmp_path, monkeypatch)
    raw = ini.read_bytes().replace(b'x, 1, Position, 1, 1', b'2*x, 1, Label, coupling, 2')
    doc['programmes'][0]['intermediates'] = ['tools/retained.txt']
    ini.write_bytes(raw)
    doc['ini'] = pin(ini)
    legacy = deepcopy(doc)
    legacy['schema_version'] = 1
    legacy['original_task'] = legacy.pop('study_id')
    legacy.pop('report')
    before = core.ini(raw, legacy)
    # Conversion is explicitly selected by the supplier, not a product default.
    config = deepcopy(legacy)
    config['study_id'] = config.pop('original_task')
    config['schema_version'] = 2
    config['report'] = doc['report']
    after = core.ini(raw, core.config(config))
    assert before == after
    assert '2*x, 1, Label, coupling, 2' in after['projection']['program1']['Input variable']
    assert after['projection']['constraint']['Gaussian'] == 'f, 1, 0.2'
    assert config['programmes'][0]['intermediates'] == ['tools/retained.txt']
    assert after['grid_population'] == 4
    assert after['figures'] == ['Color_x_y_f.png']
    assert core.prior_coordinate(.25, after['parameters'][0]) == .25


def test_schema_matches_supplied_contracts(tmp_path, monkeypatch):
    import json
    import jsonschema
    schema = json.loads((core.DATA / 'scan-contract.schema.json').read_bytes())
    _, doc, _ = supplied(tmp_path, monkeypatch)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(doc, schema)
    doc['runtime'] = None
    jsonschema.validate(doc, schema)


def test_registration_uses_current_applicability_interface():
    import json
    from ravel.workflow.capability_routing import _applicability
    fragment = json.loads((core.DATA.parent / 'generality/registration/supplied-scan-contract.json').read_bytes())
    predicate = fragment['mode_descriptors']['parameter-space-sampling']['applicability']
    assert _applicability(predicate, 'parameter-space-sampling', {'parameter-space-sampling'}) == {'scope': 'general'}
