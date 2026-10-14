"""Supplied export contracts with fictional inputs and inert tree readers."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from ravel.physics import tree_array_export as exporter
from test_tree_array_export import FakeAk, pin
from shipped_catalogue import shipped_operations


def request(tmp_path, *, variant=0):
    tmp_path.mkdir(parents=True, exist_ok=True)
    authority = tmp_path / 'authority.txt'
    authority.write_text('Synthetic units, ordering and raw weight premises')
    inputs = []
    for index in range(variant + 1):
        source = tmp_path / ('member-' + str(index) + '.bin')
        source.write_bytes(b'INERT TREE INPUT')
        fmt = 'npy' if variant == 0 else 'npz'
        inputs.append({'id': 'member-' + str(index), 'pin': pin(source), 'tree': 'events-' + str(variant),
                       'destination': 'supplied/' + str(index) + '.' + fmt, 'format': fmt,
                       'consumer': 'downstream/' + str(index)})
    columns = [{'name': 'signed-weight', 'kind': 'scalar', 'branch': 'weight', 'unit': '1'}]
    columns += [{'name': 'coordinate-' + str(i), 'kind': 'jagged', 'branch': 'coordinate', 'index': i, 'unit': 'GeV'}
                for i in range(variant + 1)]
    columns += [{'name': 'reserved', 'kind': 'constant', 'value': None, 'unit': '1'}]
    contract = {'schema_version': 2, 'study_id': 'ANA-000' + str(variant + 1),
                'parameter_grid': {'axes': [{'name': 'scale', 'unit': '1'}],
                                   'points': [{'scale': i + 1} for i in range(variant + 1)]},
                'sources': [pin(authority)], 'datasets': inputs,
                'layout': {'dtype': 'float64', 'columns': columns, 'jagged_groups': [['coordinate']],
                           'padding': None, 'overflow': 'truncate'},
                'source_premises': {'units': 'supplied per column', 'ordering': 'source positional order',
                                    'weight_semantics': 'signed raw values, no rescale'},
                'max_seconds': 20, 'max_ram_mib': 128}
    if variant:
        contract['parameter_grid'] = {'axes': [{'name': 'offset', 'unit': 'GeV'}, {'name': 'power', 'unit': '1'}],
                                      'points': [{'offset': -3, 'power': 2}, {'offset': 7, 'power': 4}]}
    path = tmp_path / 'request.json'
    path.write_bytes(exporter.encode(contract))
    return {'input': str(path), 'input_sha256': pin(path)['sha256']}, contract


class Reader:
    def __init__(self, tree):
        self.tree = tree
        self.calls = []

    def open(self, stream):
        assert stream.read() == b'INERT TREE INPUT'
        stream.seek(0)
        owner = self
        class Root:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __getitem__(self, tree):
                assert tree == owner.tree
                def arrays(names, library):
                    owner.calls.append((tree, names, library))
                    return {'weight': np.array([-2., 0., 3.]), 'coordinate': [[5, 1], [], [8]]}
                return SimpleNamespace(num_entries=3, arrays=arrays)
        return Root()


def test_two_supplied_contracts_change_population_grid_layout_and_format(tmp_path, monkeypatch):
    outputs = []
    for variant in (0, 1):
        task, contract = request(tmp_path / str(variant), variant=variant)
        reader = Reader('events-' + str(variant))
        monkeypatch.setattr(exporter, '_runtime', lambda: (np, FakeAk, reader))
        result = exporter.run(task, tmp_path, tmp_path / ('out-' + str(variant)))
        exporter.finalize(result, tmp_path / ('out-' + str(variant)))
        assert result['export_contract'] == contract
        assert result['study_id'] == contract['study_id']
        assert result['parameter_grid'] == contract['parameter_grid']
        assert len(result['arrays']) == variant + 1
        assert len(reader.calls) == variant + 1
        for row, source in zip(result['arrays'], contract['datasets']):
            assert row['file_id'] == source['id'] and row['format'] == source['format']
            assert row['artifact']['path'].endswith(source['destination'])
            assert row['shape'] == [3, variant + 3]
            loaded = np.load(row['artifact']['path'], allow_pickle=False)
            array = loaded if source['format'] == 'npy' else loaded['array']
            np.testing.assert_array_equal(array[:, 0], [-2, 0, 3])
            assert array[0, 1] == 5 and np.isnan(array[1, 1])
            if variant: assert array[0, 2] == 1 and np.isnan(array[2, 2])
            assert np.isnan(array[:, -1]).all()
            if source['format'] == 'npz': loaded.close()
        outputs.append(result)
    assert outputs[0]['columns'] != outputs[1]['columns']


@pytest.mark.parametrize('field', ['datasets', 'layout', 'sources', 'parameter_grid'])
def test_missing_array_input_is_typed(tmp_path, field):
    task, contract = request(tmp_path)
    del contract[field]
    Path(task['input']).write_bytes(exporter.encode(contract))
    task['input_sha256'] = pin(Path(task['input']))['sha256']
    with pytest.raises(exporter.MissingArrayInput, match=field): exporter.context(task, tmp_path)


def test_no_installed_source_filename_or_column_population():
    for symbol in ('ORIGINAL_SHA', 'FILE_LIST_SHA', 'IDS', 'OUTPUTS', 'HANDOFF', 'SCALARS', 'FAMILIES', 'BRANCHES', 'COLUMNS'):
        assert not hasattr(exporter, symbol)


@pytest.mark.parametrize('damage', ['census', 'premise'])
def test_recommitted_receipt_cannot_change_supplied_census_or_premises(tmp_path, monkeypatch, damage):
    task, contract = request(tmp_path)
    monkeypatch.setattr(exporter, '_runtime', lambda: (np, FakeAk, Reader('events-0')))
    out = tmp_path / 'out'
    result = exporter.run(task, tmp_path, out)
    if damage == 'census': result['file_census'].clear()
    else: result['weight_semantics'] = 'unsupported replacement'
    stripped = {k: v for k, v in result.items() if k != 'commitment'}
    (out / 'delivery.json').write_bytes(exporter.encode(stripped))
    commitment = exporter._json((out / 'completion.json').read_bytes())
    commitment['result_sha256'] = exporter.hashlib.sha256(exporter.encode(stripped)).hexdigest()
    commitment['artifacts'][-1] = exporter._pin(out / 'delivery.json')
    (out / 'completion.json').write_bytes(exporter.encode(commitment))
    result['commitment'] = exporter._pin(out / 'completion.json')
    with pytest.raises(ValueError, match='census|premises'): exporter.finalize(result, out)


def test_numeric_padding_preserves_source_nan_and_explicit_constants():
    contract = {'dtype': 'float64', 'padding': -7, 'overflow': 'truncate', 'jagged_groups': [['coordinate']],
                'columns': [{'name': 'first', 'kind': 'jagged', 'branch': 'coordinate', 'index': 0, 'unit': '1'},
                            {'name': 'second', 'kind': 'jagged', 'branch': 'coordinate', 'index': 1, 'unit': '1'},
                            {'name': 'constant', 'kind': 'constant', 'value': 9, 'unit': '1'}]}
    class PaddingReader(FakeAk):
        @staticmethod
        def pad_none(values, slots, axis, clip):
            return [list(row[:slots]) + [None] * max(0, slots - len(row)) for row in values]
        @staticmethod
        def fill_none(values, replacement):
            return [[replacement if v is None else v for v in row] for row in values]
    array, info = exporter.convert({'coordinate': [[np.nan], [2, 3, 4], []]}, 3, np=np, ak=PaddingReader,
                                   max_ram_mib=1, layout=contract)
    np.testing.assert_array_equal(array, [[np.nan, -7, 9], [2, 3, 9], [-7, -7, 9]])
    assert info['source_nan_counts'] == [1, 0, 0]
    assert info['padding_counts'] == [1, 2, 0]
    assert info['padding_nan_counts'] == [0, 0, 0]
    # A supplied truncate policy is never silent: dropped objects are counted.
    assert info['truncated_objects'] == {'coordinate': 1}


def test_registration_fragment_declares_supplied_applicability():
    root = Path(__file__).parents[2]
    fragment = exporter._json((root / 'src/ravel/data/generality/registration/columnar-array-contracts.json').read_bytes())
    for mode in ('dataset-query-quantities', 'tree-array-export'):
        assert fragment['mode_descriptors'][mode]['applicability'] == {'scope': 'general'}


def test_registration_signatures_conform_to_the_shared_schema():
    from ravel.validation.signature_conformance import entry_errors
    root = Path(__file__).parents[2]
    fragment = exporter._json((root / 'src/ravel/data/generality/registration/columnar-array-contracts.json').read_bytes())
    signatures = fragment['operation_signatures']
    # The fragment keeps the signature of an operation a release withholds; this tree checks the ones it ships.
    for mode in shipped_operations(signatures):
        assert entry_errors(mode, signatures[mode]) == []
