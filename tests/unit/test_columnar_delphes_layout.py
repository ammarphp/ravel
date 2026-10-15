"""Split Delphes 3.5 TTree leaf layout, constructed independently with uproot.

These controls cover the descriptor's exact consumed leaves and scalar types;
uproot does not manufacture Delphes C++ class streamers or TRef object links.
An opt-in supplied detector file exercises those through the same recipe.
"""
import os

import awkward as ak
import numpy as np
import pytest
import uproot

from ravel.physics.columnar import engine, formats
from ravel.physics.columnar.recipe import compile_recipe

LEAVES = {
    'Electron': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Charge': 'i4', 'IsolationVar': 'f4'},
    'Muon': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Charge': 'i4', 'IsolationVar': 'f4'},
    'Photon': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'E': 'f4', 'IsolationVar': 'f4'},
    'Jet': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Mass': 'f4', 'BTag': 'u4', 'TauTag': 'u4', 'Charge': 'i4'},
    'EFlowTrack': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Mass': 'f4', 'Charge': 'i4', 'PID': 'i4'},
    'MissingET': {'MET': 'f4', 'Phi': 'f4'},
    'Event': {'Weight': 'f4', 'Number': 'i8'},
}


def layout_file(path, missing_met=False):
    data = {}
    for name, fields in LEAVES.items():
        if missing_met and name == 'MissingET':
            continue
        counts = [1, 0, 2, 0] if name not in ('MissingET', 'Event') else [1, 1, 1, 1]
        columns = {}
        for field, dtype in fields.items():
            values = np.ones(sum(counts), dtype=dtype)
            if field == 'PT':
                values[:] = [40, 60, 10]
            elif field in ('Eta', 'Phi', 'IsolationVar'):
                values[:] = 0
            elif field == 'MET':
                values[:] = [100, 0, 150, 0]
            elif field == 'Number':
                values[:] = np.arange(4)
            columns[field] = ak.unflatten(values, counts)
        data[name] = ak.zip(columns)
    with uproot.recreate(path) as output:
        tree = output.mktree('Delphes', {k: v.type for k, v in data.items()},
                             counter_name=lambda n: n + '_size', field_name=lambda n, f: n + '.' + f)
        tree.extend(data)
    return path


def selection():
    names = ['Electron', 'Muon', 'Photon', 'Jet', 'EFlowTrack']
    return {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'synthetic split-leaf selection',
            'weights': {'generator': 'weight', 'factors': []},
            'objects': [{'name': n.lower(), 'from': n, 'select': 'pt > 20'} for n in names]
                       + [{'name': 'tagged', 'from_object': 'jet', 'select': 'btag > 0'}],
            'observables': [{'name': 'n_' + n.lower(), 'op': 'count', 'collection': n.lower()} for n in names]
                           + [{'name': 'n_tagged', 'op': 'count', 'collection': 'tagged'},
                              {'name': 'met', 'op': 'met', 'unit': 'GeV'}],
            'regions': [{'name': 'inclusive', 'cuts': []},
                        {'name': 'tagged and recoil', 'cuts': [{'name': 'tag and recoil', 'expr': 'n_tagged > 0 and met > 50'}]}],
            'histograms': [], 'event_record': {'max_events': 100, 'observables': ['met', 'n_tagged']}}


def test_exact_split_leaf_layout_and_zero_objects(tmp_path):
    path = layout_file(tmp_path / 'detector.root')
    source = formats.load_descriptor('delphes')
    with uproot.open(path) as f:
        tree = f['Delphes']
        assert tree.classname == 'TTree'
        for collection, leaves in LEAVES.items():
            assert tree[collection + '_size'].array(library='np').dtype == np.dtype('i4')
            for leaf, dtype in leaves.items():
                assert ak.to_numpy(ak.flatten(tree[collection + '.' + leaf].array())).dtype == np.dtype(dtype)
    source.check_file(path)
    plan = compile_recipe(selection(), source, tmp_path)
    part = engine.analyse({'inputs': [{'path': str(path)}], 'chunk_size': 1}, plan)
    assert part['variations']['nominal']['cutflows']['inclusive'][-1] == [4, 4., 4.]
    assert part['variations']['nominal']['cutflows']['tagged and recoil'][-1] == [2, 2., 2.]
    assert [r['n_tagged'] for r in part['event_record']] == [1, 0, 1, 0]
    assert [r['met'] for r in part['event_record']] == [100, 0, 150, 0]
    chunks = list(source.read(path, collections=list(source.collections), event_fields=['weight', 'number'], step=10))
    view = source.view(chunks[0])
    for name in ('Electron', 'Muon', 'Photon', 'Jet', 'EFlowTrack'):
        assert ak.num(view.collections[name].pt).tolist() == [1, 0, 2, 0]
    assert view.event['number'].tolist() == [0, 1, 2, 3]
    summary = engine.finalize(part, plan, {'mode': 'none'}, out_dir=tmp_path / 'out')
    assert summary['events']['n'] == 4 and summary['physics_validated'] is False


def test_missing_missinget_is_refused_by_descriptor(tmp_path):
    path = layout_file(tmp_path / 'missing.root', missing_met=True)
    with pytest.raises(ValueError, match=r'MissingET\.MET'):
        formats.load_descriptor('delphes').check_file(path)


@pytest.mark.skipif(not os.environ.get('RAVEL_TEST_DELPHES_FILE'), reason='RAVEL_TEST_DELPHES_FILE is not set')
def test_supplied_real_detector_file_first_100_events(tmp_path):
    path = os.environ['RAVEL_TEST_DELPHES_FILE']
    source = formats.load_descriptor('delphes')
    report = source.check_file(path)
    assert report['entries'] >= 100, 'the optional control requires a 100-event slice'
    plan = compile_recipe(selection(), source, tmp_path)
    def run(chunk):
        return engine.analyse({'inputs': [{'path': path, 'file_index': 0, 'entry_start': 0, 'entry_stop': 100}],
                               'chunk_size': chunk}, plan)
    full, sliced = run(100), run(13)
    def compare(a, b):
        if isinstance(a, dict):
            assert a.keys() == b.keys()
            for key in a:
                compare(a[key], b[key])
        elif isinstance(a, list):
            assert len(a) == len(b)
            for x, y in zip(a, b):
                compare(x, y)
        else:
            assert a == pytest.approx(b)
    compare(full['variations'], sliced['variations'])
    assert full['event_record'] == sliced['event_record']
    assert full['variations']['nominal']['events']['n'] == 100
    result = engine.finalize(full, plan, {'mode': 'none'}, out_dir=tmp_path / 'out')
    assert result['events']['n'] == 100
