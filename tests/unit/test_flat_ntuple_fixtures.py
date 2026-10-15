"""The synthetic flat-ntuple kit: shapes, determinism, descriptor limits and the replica catalogue."""
import json
import re
import zlib
from pathlib import Path

import awkward as ak
import numpy as np
import pytest
import uproot
from flat_ntuple_fixtures import (BOOKKEEPING_BIN, DEFAULT_DATASET_NUMBER, DEFAULT_SUFFIX, CollectionSpec,
                                  fake_replica_catalogue, write_flat_ntuple)

from ravel.physics.columnar.formats import Descriptor

HERE = Path(__file__).parent


def _read(path, tree='flat_tree'):
    with uproot.open(path) as f:
        t = f[tree]
        return {k: t[k].array(library='ak') for k in t.keys()}, {k: t[k].typename for k in t.keys()}, f.keys()


def _descriptor(fields, tree='flat_tree'):
    return {'schema_version': 1, 'kind': 'columnar-format', 'name': 'synthetic', 'source': 'test', 'format': 'root',
            'tree': tree, 'collections': {'obj': {'fields': fields}}}


# ---------------------------------------------------------------- 1. descriptor limitation (HB-04 flips it)
def test_energy_only_collection_is_refused_without_a_mass_field(tmp_path):
    rec = write_flat_ntuple(tmp_path / 'a.root', events=4, seed=1)
    energy_only = {'pt': {'branch': 'el_pt' + DEFAULT_SUFFIX, 'scale': 0.001}, 'eta': 'el_eta', 'phi': 'el_phi',
                   'e': {'branch': 'el_e' + DEFAULT_SUFFIX, 'scale': 0.001}}
    with pytest.raises(ValueError, match='must declare.*mass'):
        Descriptor(_descriptor(energy_only))
    # the same file read through a mass-only collection is accepted: the limitation is the descriptor's
    mass_only = {'pt': {'branch': 'mu_pt' + DEFAULT_SUFFIX, 'scale': 0.001}, 'eta': 'mu_eta', 'phi': 'mu_phi',
                 'mass': {'branch': 'mu_m' + DEFAULT_SUFFIX, 'scale': 0.001}}
    report = Descriptor(_descriptor(mass_only)).check_file(rec['path'])
    assert report['entries'] == 4 and 'mu_m' + DEFAULT_SUFFIX in report['branches']


# ---------------------------------------------------------------- 2. every item reads back
def test_every_shape_item_is_present_with_the_declared_dtypes(tmp_path):
    rec = write_flat_ntuple(tmp_path / 'a.root', events=30, seed=7, tree='synth_tree', extra_weights=('alpha',),
                            met_form='both', met_terms=('termx', 'termy'))
    data, types, keys = _read(rec['path'], 'synth_tree')
    sfx = DEFAULT_SUFFIX
    # 1 tree name and 2 index-aligned prefix vectors, energy-only and mass-only side by side
    assert rec['tree'] == 'synth_tree' and len(data['el_pt' + sfx]) == 30
    for prefix, kind in (('el', 'e'), ('jet', 'e'), ('mu', 'm')):
        other = 'm' if kind == 'e' else 'e'
        assert f'{prefix}_{kind}{sfx}' in data and f'{prefix}_{other}{sfx}' not in data
        counts = ak.num(data[f'{prefix}_pt{sfx}'])
        for name in ('eta', 'phi'):
            assert ak.all(ak.num(data[f'{prefix}_{name}']) == counts)
        assert ak.all(ak.num(data[f'{prefix}_{kind}{sfx}']) == counts)
    # momenta in MeV: a 5 GeV floor is 5000 in the file
    assert float(ak.min(data['el_pt' + sfx])) >= 5000.0
    # unsorted pT in at least one event
    pt = data['el_pt' + sfx]
    assert any(len(ev) >= 2 and any(a < b for a, b in zip(ev[:-1], ev[1:])) for ev in ak.to_list(pt))
    # 3 multi-part per-object fields and their dtypes
    assert ak.all(ak.num(data['el_select_wpa']) == ak.num(pt))
    assert 'int8' in types['el_select_wpa'] or 'char' in types['el_select_wpa'].lower()
    assert types['el_trigmatch_alpha'] == types['el_select_wpa']
    assert 'el_effsf_reco' + sfx in data and 'mu_effsf_reco' + sfx in data
    assert types['jet_tagbin'].startswith('int32')
    assert ak.all(ak.num(data['jet_tagbin']) == ak.num(data['jet_pt' + sfx]))
    # 4 suffix on some branches only
    assert rec['suffixed_branches']
    assert not any(k.endswith(sfx) for k in ('el_eta', 'el_phi', 'mu_eta', 'mu_phi', 'jet_eta', 'jet_phi'))
    assert 'el_eta' in data and 'el_phi' in data
    assert not any(k + sfx in data for k in ('el_eta', 'el_phi'))
    assert 'el_select_wpa' in data and 'el_select_wpa' + sfx not in data
    # 5 scalar event branches
    assert types['event_number'].startswith('uint64') and types['data_period'].startswith('int32')
    assert types['pass_trig_alpha'].startswith('bool') and types['pass_trig_beta'].startswith('bool')
    for name in ('weight_mc', 'weight_pileup', 'weight_extra_alpha'):
        assert len(data[name]) == 30
    # 6 missing momentum, both forms plus per-term recoil
    assert {'met_met', 'met_phi', 'met_px', 'met_py', 'met_term_termx_px', 'met_term_termy_py'} <= set(data)
    assert np.allclose(np.hypot(ak.to_numpy(data['met_px']), ak.to_numpy(data['met_py'])),
                       ak.to_numpy(data['met_met']), rtol=1e-4)
    # 7 bookkeeping histogram with the dsid in its name, sum of weights in the declared bin
    name = f'Bookkeeper_{DEFAULT_DATASET_NUMBER}_1_nomx'
    assert name + ';1' in keys and str(DEFAULT_DATASET_NUMBER) in name
    with uproot.open(rec['path']) as f:
        values = f[name].values()
    assert np.isclose(values[BOOKKEEPING_BIN - 1], float(ak.sum(data['weight_mc'])), rtol=1e-6)
    assert rec['bookkeeping']['bin'] == BOOKKEEPING_BIN
    # 8 truth label per object and a truth-particle collection with mass branches
    assert ak.all(ak.num(data['el_truth_label']) == ak.num(pt))
    assert {'truth_pt', 'truth_eta', 'truth_phi', 'truth_m', 'truth_pdgid'} <= set(data)
    assert ak.all(ak.num(data['truth_m']) == ak.num(data['truth_pt']))


def test_optional_branches_are_optional(tmp_path):
    rec = write_flat_ntuple(tmp_path / 'a.root', events=5, seed=1, nominal_suffix='_VARQ', met_form='cartesian',
                            bookkeeping=False, truth_particles=False,
                            collections={'ph': CollectionSpec(mass='m', mean=1.0, flags=(), truth_label=False)})
    data, _, keys = _read(rec['path'])
    assert 'weight_extra_alpha' not in data and 'met_met' not in data and {'met_px', 'met_py'} <= set(data)
    assert {'ph_pt_VARQ', 'ph_m_VARQ', 'ph_eta', 'ph_phi'} <= set(data) and 'ph_e_VARQ' not in data
    assert not any(k.startswith('truth_') for k in data) and not any(k.startswith('Bookkeeper') for k in keys)
    assert rec['bookkeeping'] is None and rec['nominal_suffix'] == '_VARQ'


def test_bad_arguments_are_refused(tmp_path):
    with pytest.raises(ValueError, match='events'):
        write_flat_ntuple(tmp_path / 'a.root', events=0, seed=1)
    with pytest.raises(ValueError, match='met_form'):
        write_flat_ntuple(tmp_path / 'a.root', events=2, seed=1, met_form='mixed')
    with pytest.raises(ValueError, match='mass'):
        write_flat_ntuple(tmp_path / 'a.root', events=2, seed=1, collections={'x': CollectionSpec(mass='q')})


# ---------------------------------------------------------------- 3. determinism
def _arrays(path):
    data, _, _ = _read(path)
    return {k: ak.to_list(v) for k, v in data.items()}


def test_same_seed_same_arrays_and_different_seed_differs(tmp_path):
    a = write_flat_ntuple(tmp_path / 'a.root', events=25, seed=3)
    b = write_flat_ntuple(tmp_path / 'b.root', events=25, seed=3)
    c = write_flat_ntuple(tmp_path / 'c.root', events=25, seed=4)
    assert _arrays(a['path']) == _arrays(b['path'])
    assert _arrays(a['path']) != _arrays(c['path'])
    assert a['sum_weights'] == b['sum_weights']


# ---------------------------------------------------------------- 9 replica catalogue
def test_replica_catalogue_points_at_the_fixture_files(tmp_path):
    ds_a = [write_flat_ntuple(tmp_path / f'a{i}.root', events=6 + i, seed=i) for i in range(2)]
    ds_b = [write_flat_ntuple(tmp_path / 'b0.root', events=4, seed=9, bookkeeping={'dataset_number': 987655})]
    path = fake_replica_catalogue(tmp_path / 'cat', 'synth.container.v1', {'synth.ds.a': ds_a, 'synth.ds.b': ds_b})
    doc = json.loads(path.read_text())
    assert doc['container']['did'] == 'synth_scope:synth.container.v1'
    datasets = {d['did']: d for d in doc['container']['datasets']}
    assert sorted(datasets) == ['synth_scope:synth.ds.a', 'synth_scope:synth.ds.b']
    for rec, row in zip(ds_a, datasets['synth_scope:synth.ds.a']['files']):
        raw = Path(rec['path']).read_bytes()
        assert row['bytes'] == len(raw) == rec['size'] and row['events'] == rec['entries']
        assert row['adler32'] == f'{zlib.adler32(raw):08x}'
        assert row['uri'].startswith('root://') and row['uri'].endswith(rec['path'])
        assert doc['replicas'][f"synth_scope:{row['name']}"] == [row['uri']]
    assert [r['events'] for r in doc['files']['synth_scope:synth.ds.a']] == [6, 7]


# ---------------------------------------------------------------- 4. generality scan
# Real names are written split so this file does not itself contain them.
_BANNED = [r'NO' + r'SYS', r'\bti' + r'ght\b', r'\blo' + r'ose\b', r'\bme' + r'dium\b', r'HL' + r'T_', r'mc' + r'(16|20|23)',
           r'DA' + r'OD', r'PHYS' + r'LITE', r'Cut' + r'Bookkeeper', r'\b4104' + r'\d\d\b', r'tt' + r'bar',
           r'AT' + r'LAS', r'\bC' + r'MS\b', r'ANA' + r'-\d', r'EXOT' + r'-\d', r'SUSY' + r'-\d', r'DL' + r'1', r'iv' + r'ar[a-z]+',
           r'JET' + r'_', r'\bFixed' + r'Cut']


@pytest.mark.parametrize('source', ['flat_ntuple_fixtures.py', 'test_flat_ntuple_fixtures.py'])
def test_new_files_name_no_real_identity(source):
    text = (HERE / source).read_text()
    hits = [p for p in _BANNED if re.search(p, text)]
    assert hits == []


def test_written_file_names_no_real_identity(tmp_path):
    rec = write_flat_ntuple(tmp_path / 'a.root', events=5, seed=1, extra_weights=('alpha',), met_terms=('termx',))
    data, _, keys = _read(rec['path'])
    blob = ' '.join(list(data) + list(keys) + [rec['tree']])
    assert [p for p in _BANNED if re.search(p, blob)] == []
