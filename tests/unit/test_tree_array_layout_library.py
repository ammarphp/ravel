"""Packaged array layout templates drive the same exporter as a supplied layout.

Original use: the former fixed 46-column raw-array producer. ``ORIGINAL_COLUMNS`` and the index map
are that producer's column population and positions (production run of 974985d), and the arrays
below are compared with them value by value, NaN pattern included. Second use: a different
population (leptons, jets and a large-R jet with energies) through the same ``convert`` and
``run``, with an npz destination.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from ravel.physics import tree_array_export as a
import test_tree_array_export as base

DIPHOTON = 'atlas-opendata-13tev-diphoton-raw46'
LEPJET = 'atlas-opendata-13tev-lepton-jet-large-r-raw'

ORIGINAL_COLUMNS = (
    *(f'{f}_{c}[{i}]' for f, n, _ in base.FAMILIES for i in range(n) for c in ('pt', 'eta', 'phi')),
    'met_et', 'met_phi', 'mcWeight', 'SumWeights', 'XSection', 'photon_isTightID[0]', 'photon_isTightID[1]',
    'scaleFactor_PILEUP', 'scaleFactor_PHOTON', 'scaleFactor_PhotonTRIGGER', 'scaleFactor_ELE',
    'scaleFactor_MUON', 'scaleFactor_LepTRIGGER', 'scaleFactor_BTAG',
    'diphoton_mass_placeholder', 'diphoton_pt_placeholder')
ORIGINAL_SCALAR_POSITIONS = (30, 31, 32, 33, 34, 37, 38, 39, 40, 41, 42, 43)


def test_library_lists_templates_and_rejects_unknown_or_hostile_identifiers():
    assert {DIPHOTON, LEPJET} <= set(a.layout_names())
    for name in a.layout_names():
        layout = a.library_layout(name)
        assert layout == a.validate_layout(name) and layout['dtype'] == 'float64'
    for bad in ('nope', '../tree-array-layout', 'A', ''):
        with pytest.raises(ValueError):
            a.library_layout(bad)


def test_original_46_column_population_order_and_groups():
    layout = a.library_layout(DIPHOTON)
    assert [c['name'] for c in layout['columns']] == list(ORIGINAL_COLUMNS) and len(ORIGINAL_COLUMNS) == 46
    assert a._branches(layout) and set(a._branches(layout)) == set(base.BRANCHES)
    assert layout['padding'] is None and layout['overflow'] == 'truncate'
    constants = [c for c in layout['columns'] if c['kind'] == 'constant']
    assert [c['name'] for c in constants] == list(ORIGINAL_COLUMNS[-2:]) and all(c['value'] is None for c in constants)


@pytest.mark.parametrize('count', [0, 1, 3])
def test_original_array_values_padding_and_counts(count):
    b = base.branches(count)
    arr, meta = a.convert(deepcopy(b), count, np=np, ak=base.FakeAk, max_ram_mib=1, layout=DIPHOTON)
    assert arr.shape == (count, 46) and arr.dtype == np.float64
    expected = np.full((count, 46), np.nan)
    for family, slots, offset in base.FAMILIES:
        for entry in range(count):
            for slot in range(slots):
                for axis, coordinate in enumerate(('pt', 'eta', 'phi')):
                    row = b[family + '_' + coordinate][entry]
                    if slot < len(row): expected[entry, offset + 3 * slot + axis] = row[slot]
    for name, position in zip(base.SCALARS, ORIGINAL_SCALAR_POSITIONS):
        expected[:, position] = b[name]
    for entry in range(count):
        for slot in (0, 1):
            row = b['photon_isTightID'][entry]
            if slot < len(row): expected[entry, 35 + slot] = row[slot]
    np.testing.assert_array_equal(arr, expected)
    assert meta['shape'] == [count, 46] and meta['constant_nan_counts'][-2:] == [count, count]
    assert meta['nan_counts'] == np.isnan(expected).sum(axis=0).tolist()
    # source NaN (none here) stays distinct from padding: every NaN in columns 0-43 is padding
    assert meta['source_nan_counts'] == [0] * 46
    assert meta['padding_nan_counts'] == meta['padding_counts']


def test_original_end_to_end_run_by_template_name_matches_inline_layout(tmp_path, monkeypatch):
    task, d, roots = base.fixture(tmp_path)
    base.mock_runtime(monkeypatch)
    inline = a.run(task, tmp_path, tmp_path / 'out-inline')
    named = deepcopy(d); named['layout'] = DIPHOTON
    path = tmp_path / 'producer-named.json'; path.write_bytes(a.encode(named))
    task2 = {'input': str(path), 'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    result = a.run(task2, tmp_path, tmp_path / 'out-named')
    assert result['columns'] == list(ORIGINAL_COLUMNS) and result['columns'][:44] == inline['columns'][:44]
    for left, right in zip(inline['arrays'], result['arrays']):
        np.testing.assert_array_equal(np.load(left['artifact']['path']), np.load(right['artifact']['path']))
        assert left['nan_counts'] == right['nan_counts'] and left['padding_counts'] == right['padding_counts']
    a.finalize(result, tmp_path / 'out-named')
    context = a.context(task2, tmp_path)
    assert context['export_contract']['layout'] == a.library_layout(DIPHOTON)
    assert len(context['columns']) == 46


# ---- second, unrelated use ----------------------------------------------------------------------

LJ_FAMILIES = (('lep', 2, 0, ('pt', 'eta', 'phi', 'E')), ('jet', 4, 8, ('pt', 'eta', 'phi', 'E')),
               ('largeRjet', 1, 24, ('pt', 'eta', 'phi', 'E')))
LJ_SCALARS = ('met_et', 'met_phi', 'mcWeight', 'SumWeights', 'XSection', 'scaleFactor_PILEUP', 'scaleFactor_ELE',
              'scaleFactor_MUON', 'scaleFactor_BTAG', 'scaleFactor_LepTRIGGER')


def lj_branches(count):
    sizes = {'lep': [2, 0, 5], 'jet': [6, 1, 0], 'largeRjet': [1, 0, 2]}
    out = {}
    for family, _, _, coords in LJ_FAMILIES:
        for coordinate in coords:
            out[f'{family}_{coordinate}'] = [[1000. * (ord(coordinate[0]) % 7) + 10 * e + i for i in range(sizes[family][e])]
                                             for e in range(count)]
    out['largeRjet_m'] = [[80. + e + i for i in range(sizes['largeRjet'][e])] for e in range(count)]
    for k, name in enumerate(LJ_SCALARS): out[name] = np.array([k + e / 10 for e in range(count)])
    return out


def test_second_use_lepton_jet_largeR_layout_through_the_same_engine():
    layout = a.library_layout(LEPJET)
    assert len(layout['columns']) == 39 and layout['jagged_groups'][2][-1] == 'largeRjet_m'
    b = lj_branches(3)
    arr, meta = a.convert(deepcopy(b), 3, np=np, ak=base.FakeAk, max_ram_mib=1, layout=LEPJET)
    assert arr.shape == (3, 39)
    names = [c['name'] for c in layout['columns']]
    column = {n: i for i, n in enumerate(names)}
    assert arr[0, column['lep_pt[1]']] == b['lep_pt'][0][1] and np.isnan(arr[1, column['lep_pt[0]']])
    # five leptons in entry 2: only two positions are exported and three objects are counted as truncated
    assert arr[2, column['lep_E[1]']] == b['lep_E'][2][1] and meta['truncated_objects']['lep_pt'] == 3
    assert meta['truncated_objects']['jet_pt'] == 2 and meta['truncated_objects']['largeRjet_pt'] == 1
    assert arr[0, column['largeRjet_m[0]']] == b['largeRjet_m'][0][0]
    for name in LJ_SCALARS: np.testing.assert_array_equal(arr[:, column[name]], b[name])
    assert meta['padding_counts'][column['lep_pt[0]']] == 1 and meta['source_nan_counts'] == [0] * 39


def test_second_use_runs_end_to_end_to_npz_without_the_original_producer_mocks(tmp_path, monkeypatch):
    layout = a.library_layout(LEPJET)
    wanted = a._branches(layout)

    class Root:
        def __init__(self, count): self.count = count
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __getitem__(self, key):
            assert key == 'mini'
            def arrays(names, **kwargs):
                assert set(names) == set(wanted) and kwargs == {'library': 'ak'}
                return lj_branches(self.count)
            return SimpleNamespace(num_entries=self.count, arrays=arrays)

    reader = SimpleNamespace(open=lambda stream: Root(3))
    monkeypatch.setattr(a, '_runtime', lambda: (np, base.FakeAk, reader))
    source = tmp_path / 'sample.bin'; source.write_bytes(b'INERT')
    authority = tmp_path / 'authority.txt'; authority.write_text('synthetic premises')
    request = {'schema_version': 2, 'study_id': 'second-use',
               'parameter_grid': {'axes': [{'name': 'index', 'unit': '1'}], 'points': [{'index': 0}, {'index': 1}]},
               'sources': [base.pin(authority)], 'layout': LEPJET,
               'datasets': [{'id': 'sample', 'pin': base.pin(source), 'tree': 'mini', 'destination': 'out/sample.npz',
                             'format': 'npz', 'consumer': None}],
               'source_premises': {'units': 'source units unchanged', 'ordering': 'stored order unchanged',
                                   'weight_semantics': 'raw weight and separate normalization branches'},
               'max_seconds': 20, 'max_ram_mib': 64}
    path = tmp_path / 'request.json'; path.write_bytes(a.encode(request))
    task = {'input': str(path), 'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    result = a.run(task, tmp_path, tmp_path / 'delivery')
    with np.load(result['arrays'][0]['artifact']['path']) as archive:
        assert archive['array'].shape == (3, 39)
    assert result['columns'] == [c['name'] for c in layout['columns']]
    a.finalize(result, tmp_path / 'delivery')


def test_packaged_layouts_cite_a_public_url_and_carry_no_hash():
    import re
    for name in a.layout_names():
        text = (a.LIBRARY / (name + '.json')).read_text()
        assert 'https://' in text and not re.search(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])', text)
