"""Expressions, efficiency maps and event readers of the columnar engine."""
import gzip
import json
import math

import awkward as ak
import numpy as np
import pytest
import uproot
import uproot.writing.identify as ident

from ravel.physics.columnar import efficiency, expressions, formats


# ---------------------------------------------------------------- expressions
def test_expression_arithmetic_comparisons_and_names():
    e = expressions.compile_expression('met > 100 and abs(eta) < 2.5 or not (n == 0)', allowed={'met', 'eta', 'n'})
    assert e.names == {'met', 'eta', 'n'}
    out = e.evaluate({'met': np.array([150.0, 50.0, 50.0]), 'eta': np.array([1.0, 1.0, 3.0]), 'n': np.array([0, 0, 2])})
    assert out.tolist() == [True, False, True]
    chained = expressions.compile_expression('80 < mll < 100', allowed={'mll'})
    assert chained.evaluate({'mll': np.array([79.0, 91.0, 100.0])}).tolist() == [False, True, False]
    arithmetic = expressions.compile_expression('max(a, b) / sqrt(c) + 2 ** 2', allowed={'a', 'b', 'c'})
    assert arithmetic.evaluate({'a': np.array([1.0]), 'b': np.array([3.0]), 'c': np.array([9.0])})[0] == pytest.approx(5.0)


@pytest.mark.parametrize('text', ['__import__("os")', 'a.b', 'a[0]', 'lambda x: x', 'open("f")', '[a]', 'a if b else c',
                                  'x', '"text" == a', 'a; b'])
def test_expression_refuses_anything_outside_the_grammar(text):
    with pytest.raises(ValueError):
        expressions.compile_expression(text, allowed={'a', 'b', 'c'})


def test_cut_with_undefined_input_fails_even_under_negation():
    cut = expressions.compile_expression('not (x > 1)', allowed={'x'})
    out = cut.evaluate_cut({'x': np.array([0.0, np.nan, 2.0])})
    assert out.tolist() == [True, False, False]
    numeric = expressions.compile_expression('x + 1', allowed={'x'})
    with pytest.raises(ValueError, match='true/false'):
        numeric.evaluate_cut({'x': np.array([1.0])})


def test_expression_on_jagged_object_fields():
    sel = expressions.compile_expression('pt > 20 and abs(eta) < 2.4', allowed={'pt', 'eta'})
    pt = ak.Array([[30.0, 10.0], [], [25.0]])
    eta = ak.Array([[0.5, 0.1], [], [2.6]])
    assert sel.evaluate_cut({'pt': pt, 'eta': eta}).tolist() == [[True, False], [], [False]]


# ---------------------------------------------------------------- efficiency maps
def _label_th2(path, xlabels, ylabels, values):
    nx, ny = len(xlabels), len(ylabels)
    data = np.zeros((nx + 2, ny + 2)); data[1:-1, 1:-1] = values

    def axis(name, labels):
        return ident.to_TAxis(name, '', len(labels), 0.0, float(len(labels)),
                              fLabels=ident.to_THashList([ident.to_TObjString(x) for x in labels]))
    h = ident.to_TH2x('eff', 'eff', data.T.ravel(), 1.0, 1.0, 1.0, 0, 0, 0, 0, 0, np.zeros((nx + 2) * (ny + 2)),
                      axis('xaxis', xlabels), axis('yaxis', ylabels))
    with uproot.recreate(path) as f:
        f['eff'] = h


def test_label_encoded_th2_lookup_and_policies(tmp_path):
    path = tmp_path / 'map.root'
    values = np.array([[0.9, 0.8, 0.7], [0.6, 0.5, 0.4]])
    _label_th2(path, ['(0,0.8)', '(0.8,1.4)'], ['20-35', '35-90', '90-500'], values)
    spec = {'source': {'format': 'root', 'path': 'map.root', 'object': 'eff'}, 'axis_edges': 'labels',
            'axes': [{'name': 'absolute pseudorapidity', 'unit': '1'}, {'name': 'transverse energy', 'unit': 'GeV'}],
            'out_of_range': {'transverse energy': 'clamp', 'absolute pseudorapidity': 'refuse'},
            'citation': 'synthetic test map', 'semantics': 'absolute'}
    emap = efficiency.load_map('photon-id', spec, tmp_path)
    np.testing.assert_allclose(emap.edges[0], [0.0, 0.8, 1.4])
    np.testing.assert_allclose(emap.edges[1], [20.0, 35.0, 90.0, 500.0])
    eff, counts = emap.lookup([np.array([0.1, 1.0, 0.79]), np.array([25.0, 600.0, 90.0])])
    np.testing.assert_allclose(eff, [0.9, 0.4, 0.7])
    assert counts['transverse energy']['above'] == 1 and counts['transverse energy']['clamped'] == 1
    with pytest.raises(ValueError, match='outside'):
        emap.lookup([np.array([1.5]), np.array([25.0])])
    assert emap.provenance['sha256'] and emap.provenance['object'] == 'eff'


def test_numeric_reading_of_a_labelled_map_is_refused(tmp_path):
    _label_th2(tmp_path / 'map.root', ['(0,0.8)', '(0.8,1.4)'], ['20-35', '35-90'], np.ones((2, 2)))
    spec = {'source': {'format': 'root', 'path': 'map.root', 'object': 'eff'}, 'axis_edges': 'numeric',
            'axes': [{'name': 'a', 'unit': '1'}, {'name': 'b', 'unit': 'GeV'}], 'out_of_range': 'refuse',
            'citation': 'synthetic', 'semantics': 'absolute'}
    with pytest.raises(ValueError, match='labels'):
        efficiency.load_map('m', spec, tmp_path)


def test_non_contiguous_labels_are_refused(tmp_path):
    _label_th2(tmp_path / 'map.root', ['(0,0.8)', '(1.0,1.4)'], ['20-35'], np.ones((2, 1)))
    spec = {'source': {'format': 'root', 'path': 'map.root', 'object': 'eff'}, 'axis_edges': 'labels',
            'axes': [{'name': 'a', 'unit': '1'}, {'name': 'b', 'unit': 'GeV'}], 'out_of_range': 'refuse',
            'citation': 'synthetic', 'semantics': 'absolute'}
    with pytest.raises(ValueError, match='contiguous'):
        efficiency.load_map('m', spec, tmp_path)


def test_numeric_th1_zero_policy_and_value_range(tmp_path):
    with uproot.recreate(tmp_path / 'h.root') as f:
        f['h'] = (np.array([0.5, 0.75]), np.array([10.0, 50.0, 100.0]))
    spec = {'source': {'format': 'root', 'path': 'h.root', 'object': 'h'}, 'axis_edges': 'numeric',
            'axes': [{'name': 'transverse momentum', 'unit': 'GeV'}], 'out_of_range': 'zero', 'citation': 'synthetic', 'semantics': 'absolute'}
    emap = efficiency.load_map('m', spec, tmp_path)
    eff, counts = emap.lookup([np.array([5.0, 20.0, 100.0, 70.0])])
    np.testing.assert_allclose(eff, [0.0, 0.5, 0.0, 0.75])
    assert counts['transverse momentum'] == {'below': 1, 'above': 1, 'clamped': 0, 'zeroed': 2}
    with uproot.recreate(tmp_path / 'bad.root') as f:
        f['h'] = (np.array([0.5, 75.0]), np.array([10.0, 50.0, 100.0]))
    with pytest.raises(ValueError, match='between 0 and 1'):
        efficiency.load_map('m', {**spec, 'source': {'format': 'root', 'path': 'bad.root', 'object': 'h'}}, tmp_path)


def test_json_grid_and_hepdata_tables(tmp_path):
    grid = {'axes': [{'name': 'pt', 'unit': 'GeV', 'edges': [0, 10, 20]}], 'values': [0.2, 0.4]}
    (tmp_path / 'g.json').write_text(json.dumps(grid))
    spec = {'source': {'format': 'json-grid', 'path': 'g.json'}, 'axes': [{'name': 'pt', 'unit': 'GeV'}],
            'out_of_range': 'refuse', 'citation': 'synthetic', 'semantics': 'absolute'}
    assert efficiency.load_map('g', spec, tmp_path).lookup([np.array([15.0])])[0][0] == pytest.approx(0.4)
    table = {'independent_variables': [
        {'header': {'name': 'pt', 'units': 'GeV'}, 'values': [{'low': 0, 'high': 10}, {'low': 0, 'high': 10}, {'low': 10, 'high': 20}, {'low': 10, 'high': 20}]},
        {'header': {'name': 'eta'}, 'values': [{'low': 0, 'high': 1}, {'low': 1, 'high': 2}, {'low': 0, 'high': 1}, {'low': 1, 'high': 2}]}],
        'dependent_variables': [{'header': {'name': 'eff'}, 'values': [{'value': 0.1}, {'value': 0.2}, {'value': 0.3}, {'value': 0.4}]}]}
    (tmp_path / 't.yaml').write_text(json.dumps(table))
    spec = {'source': {'format': 'hepdata', 'path': 't.yaml', 'dependent_variable': 0},
            'axes': [{'name': 'pt', 'unit': 'GeV'}, {'name': 'eta', 'unit': '1'}], 'out_of_range': 'refuse',
            'citation': 'synthetic', 'semantics': 'absolute'}
    emap = efficiency.load_map('t', spec, tmp_path)
    np.testing.assert_allclose(emap.lookup([np.array([15.0, 5.0]), np.array([1.5, 0.5])])[0], [0.4, 0.1])


def test_counter_based_uniforms_are_reproducible_and_partition_free():
    a = efficiency.uniforms(7, np.array([0, 0, 1]), np.array([5, 6, 5]), np.array([0, 0, 0]))
    b = efficiency.uniforms(7, np.array([0]), np.array([6]), np.array([0]))
    assert a[1] == b[0] and len(set(a.tolist())) == 3 and np.all((a >= 0) & (a < 1))
    many = efficiency.uniforms(1, np.zeros(20000, int), np.arange(20000), np.zeros(20000, int))
    assert abs(many.mean() - 0.5) < 0.01


# ---------------------------------------------------------------- readers
DELPHES_FIELDS = {
    'Electron': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Charge': 'i4', 'IsolationVar': 'f4'},
    'Muon': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Charge': 'i4', 'IsolationVar': 'f4'},
    'Photon': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'E': 'f4', 'IsolationVar': 'f4'},
    'Jet': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Mass': 'f4', 'BTag': 'i4', 'TauTag': 'i4', 'Charge': 'i4'},
    'EFlowTrack': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Mass': 'f4', 'Charge': 'i4', 'PID': 'i4'},
}


def write_delphes(path, events):
    """Write a small Delphes-shaped tree (Branch.Field names, Branch_size counters)."""
    data = {}
    for name, fields in DELPHES_FIELDS.items():
        rows = [ev.get(name, []) for ev in events]
        counts = [len(r) for r in rows]
        data[name] = ak.zip({f: ak.unflatten(np.array([o.get(f, 0) for r in rows for o in r], dtype=dt), counts)
                             for f, dt in fields.items()})
    ones = [1] * len(events)
    data['MissingET'] = ak.zip({'MET': ak.unflatten(np.array([ev['MET'] for ev in events], 'f4'), ones),
                                'Phi': ak.unflatten(np.array([ev['METPhi'] for ev in events], 'f4'), ones)})
    data['Event'] = ak.zip({'Weight': ak.unflatten(np.array([ev.get('Weight', 1.0) for ev in events], 'f4'), ones),
                            'Number': ak.unflatten(np.arange(len(events), dtype='i8'), ones)})
    with uproot.recreate(path) as f:
        f.mktree('Delphes', {k: v.type for k, v in data.items()},
                 counter_name=lambda c: c + '_size', field_name=lambda o, i: o + '.' + i)
        f['Delphes'].extend(data)


def simple_events():
    return [
        {'Electron': [{'PT': 40.0, 'Eta': 0.5, 'Phi': 0.1, 'Charge': -1, 'IsolationVar': 0.01}],
         'Muon': [{'PT': 30.0, 'Eta': -1.0, 'Phi': 2.0, 'Charge': 1, 'IsolationVar': 0.02}],
         'Jet': [{'PT': 80.0, 'Eta': 1.0, 'Phi': -2.0, 'Mass': 10.0, 'BTag': 1, 'TauTag': 0, 'Charge': 0}],
         'EFlowTrack': [{'PT': 12.0, 'Eta': 0.2, 'Phi': 1.0, 'Charge': 1, 'PID': 211}],
         'MET': 120.0, 'METPhi': 3.0, 'Weight': 2.0},
        {'MET': 10.0, 'METPhi': 0.0, 'Weight': 0.5},
    ]


def test_builtin_delphes_descriptor_reads_a_delphes_tree(tmp_path):
    path = tmp_path / 'delphes.root'
    write_delphes(path, simple_events())
    source = formats.load_descriptor('delphes')
    report = source.check_file(path)
    assert report['tree'] == 'Delphes' and report['entries'] == 2
    assert report['branches']['Jet.TauTag'].startswith('int')
    chunks = list(source.read(path, collections=['Electron', 'Jet', 'EFlowTrack'], event_fields=['weight'], step=10))
    assert len(chunks) == 1
    view = source.view(chunks[0])
    assert view.entries.tolist() == [0, 1]
    assert view.event['weight'].tolist() == [2.0, 0.5]
    assert view.met_magnitude.tolist() == [120.0, 10.0]
    ele = view.collections['Electron']
    assert ak.to_list(ele.pt) == [[40.0], []] and ak.to_list(ele.flavour) == [[11], []]
    assert ak.to_list(ele.mass)[0][0] == pytest.approx(0.000510998950)
    assert ak.to_list(view.collections['Jet'].btag) == [[1], []]


def test_descriptor_refuses_missing_or_misshapen_branches(tmp_path):
    path = tmp_path / 'delphes.root'
    write_delphes(path, simple_events())
    doc = json.loads(json.dumps(formats.builtin('delphes')))
    doc['collections']['Jet']['fields']['btag'] = 'Jet.NoSuchBranch'
    with pytest.raises(ValueError, match='Jet.NoSuchBranch'):
        formats.Descriptor(doc).check_file(path)
    doc = json.loads(json.dumps(formats.builtin('delphes')))
    doc['collections']['Jet']['fields']['pt'] = 'Jet_size'
    with pytest.raises(ValueError, match='jagged'):
        formats.Descriptor(doc).check_file(path)


def test_flat_ntuple_descriptor_scales_units_and_substitutes_variations(tmp_path):
    path = tmp_path / 'flat.root'
    with uproot.recreate(path) as f:
        f['nominal'] = {'el_pt_NOSYS': ak.Array([[50000.0, 20000.0], []]), 'el_eta': ak.Array([[0.1, 0.2], []]),
                        'el_phi': ak.Array([[0.0, 1.0], []]), 'el_pt_EG_SCALE__1up': ak.Array([[51000.0, 20400.0], []]),
                        'met_met_NOSYS': np.array([30000.0, 1000.0]), 'met_phi_NOSYS': np.array([0.0, 1.0]),
                        'met_met_EG_SCALE__1up': np.array([31000.0, 1000.0]), 'met_phi_EG_SCALE__1up': np.array([0.0, 1.0]),
                        'weight_mc': np.array([1.5, -0.5]), 'weight_pileup_NOSYS': np.array([1.0, 2.0])}
    doc = {'schema_version': 1, 'kind': 'columnar-format', 'name': 'synthetic flat ntuple', 'format': 'root',
           'tree': 'nominal', 'source': 'synthetic test',
           'collections': {'el': {'fields': {'pt': {'branch': 'el_pt_NOSYS', 'scale': 0.001}, 'eta': 'el_eta', 'phi': 'el_phi',
                                             'mass': {'fixed': 0.0, 'source': 'massless approximation for the test'},
                                             'pdg_id': {'fixed': 11, 'source': 'electron'}}}},
           'met': {'magnitude': {'branch': 'met_met_NOSYS', 'scale': 0.001}, 'phi': 'met_phi_NOSYS'},
           'event': {'mc': 'weight_mc', 'pileup': 'weight_pileup_NOSYS'},
           'variations': {'energy scale up': {'replace': ['_NOSYS', '_EG_SCALE__1up']}}}
    source = formats.Descriptor(doc)
    source.check_file(path, variations=['energy scale up'])
    chunk = next(iter(source.read(path, collections=['el'], event_fields=['mc', 'pileup'], step=100,
                                  variations=['energy scale up'])))
    nominal, varied = source.view(chunk), source.view(chunk, variation='energy scale up')
    assert ak.to_list(nominal.collections['el'].pt) == [[50.0, 20.0], []]
    assert ak.flatten(varied.collections['el'].pt).tolist() == pytest.approx([51.0, 20.4])
    assert varied.met_magnitude.tolist() == [31.0, 1.0]
    assert varied.event['pileup'].tolist() == [1.0, 2.0]          # no variation branch: nominal kept


def test_entry_ranges_and_chunking(tmp_path):
    path = tmp_path / 'delphes.root'
    write_delphes(path, simple_events() * 5)
    source = formats.load_descriptor('delphes')
    chunks = list(source.read(path, collections=['Jet'], event_fields=[], step=3, entry_start=2, entry_stop=9))
    assert [c.entry_start for c in chunks] == [2, 5, 8]
    assert sum(c.length for c in chunks) == 7


LHE = """<LesHouchesEvents version="3.0">
<header>
<initrwgt><weightgroup name="scale"><weight id="muR2">muR=2</weight></weightgroup></initrwgt>
</header>
<init>
2212 2212 6500.0 6500.0 0 0 0 0 3 1
0.25 0.001 1.0 1
</init>
<event>
4 1 +2.0e-01 9.1e+01 7.5e-03 1.2e-01
21 -1 0 0 501 502 0.0 0.0 100.0 100.0 0.0 0. 9.
21 -1 0 0 502 501 0.0 0.0 -100.0 100.0 0.0 0. 9.
22 1 1 2 0 0 30.0 0.0 10.0 31.6227766 0.0 0. 9.
12 1 1 2 0 0 -30.0 0.0 -10.0 31.6227766 0.0 0. 9.
<rwgt>
<wgt id="muR2">0.18</wgt>
</rwgt>
</event>
<event>
4 1 +2.0e-01 9.1e+01 7.5e-03 1.2e-01
21 -1 0 0 501 502 0.0 0.0 50.0 50.0 0.0 0. 9.
21 -1 0 0 502 501 0.0 0.0 -50.0 50.0 0.0 0. 9.
-11 1 1 2 0 0 0.0 25.0 0.0 25.0 0.0 0. 9.
11 1 1 2 0 0 0.0 -25.0 0.0 25.0 0.0 0. 9.
<rwgt>
<wgt id="muR2">0.21</wgt>
</rwgt>
</event>
</LesHouchesEvents>
"""


def test_lhe_reader_with_named_weights_and_invisible_set(tmp_path):
    path = tmp_path / 'events.lhe.gz'
    with gzip.open(path, 'wt') as stream:
        stream.write(LHE)
    doc = {'schema_version': 1, 'kind': 'columnar-format', 'name': 'parton level', 'format': 'lhe',
           'source': 'synthetic',
           'collections': {'photons': {'pdg': [22], 'status': [1]},
                           'leptons': {'pdg': [11, -11, 13, -13], 'status': [1], 'charge_from_pdg_sign': -1}},
           'invisible': {'pdg': [12, -12, 14, -14, 16, -16], 'source': 'neutrinos'},
           'event': {'weight': 'nominal', 'scale up': {'lhe_weight_id': 'muR2'}}}
    source = formats.Descriptor(doc)
    report = source.check_file(path)
    assert report['entries'] == 2 and report['cross_section_pb'] == pytest.approx(0.25)
    chunk = next(iter(source.read(path, collections=['photons', 'leptons'], event_fields=['weight', 'scale up'], step=10)))
    view = source.view(chunk)
    assert view.event['weight'].tolist() == [0.2, 0.2]
    assert view.event['scale up'].tolist() == [0.18, 0.21]
    assert ak.to_list(view.collections['photons'].pt) == [[30.0], []]
    assert ak.to_list(view.collections['leptons'].charge) == [[], [1, -1]]
    assert view.met_magnitude.tolist() == pytest.approx([30.0, 0.0])
    assert view.met_phi[0] == pytest.approx(math.pi)
