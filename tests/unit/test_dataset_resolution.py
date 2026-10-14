"""Site dataset resolution (rucio or supplied listing) and MC normalization building."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import uproot

from ravel.physics import dataset_resolution as dr
from ravel.physics import root_stream_core as core

DID_A = 'mc20_13TeV:mc20_13TeV.410470.PhPy8EG_ttbar.deriv.DAOD_PHYSLITE.e6337_s3681_r13144_p5855'
DID_B = 'mc20_13TeV:mc20_13TeV.410470.PhPy8EG_ttbar.deriv.DAOD_PHYSLITE.e6337_s3681_r13145_p5855'
DID_DATA = 'data18_13TeV:data18_13TeV.periodAllYear.physics_Main.PhysCont.DAOD_PHYSLITE.grp18_v01_p5855'


class FakeRucio:
    def __init__(self, files, replicas):
        self.files, self.replicas, self.calls = files, replicas, []

    def list_files(self, scope, name):
        self.calls.append(('list_files', scope, name))
        return [dict(r) for r in self.files[f'{scope}:{name}']]

    def list_replicas(self, dids, schemes=None, rse_expression=None):
        self.calls.append(('list_replicas', tuple(d['name'] for d in dids), tuple(schemes or ()), rse_expression))
        out = []
        for d in dids:
            key = f"{d['scope']}:{d['name']}"
            out.append({'scope': d['scope'], 'name': d['name'], 'rses': {rse_expression: self.replicas[key]}})
        return out


def file_rows(prefix, n, scope='mc20_13TeV', events=100):
    return [{'scope': scope, 'name': f'{prefix}._{i:06d}.pool.root.1', 'guid': f'{prefix}-{i:04d}-guid'.upper(),
             'adler32': f'{i + 10:x}', 'bytes': 1000 + i, 'events': events + i} for i in range(n)]


def fake_client():
    files = {DID_A: file_rows('DAOD_A', 2), DID_B: file_rows('DAOD_B', 1), DID_DATA: file_rows('DAOD_D', 1, scope='data18_13TeV')}
    replicas = {}
    for rows in files.values():
        for r in rows:
            replicas[f"{r['scope']}:{r['name']}"] = [f"root://eos.example.ch//eos/rucio/{r['name']}"]
    return FakeRucio(files, replicas)


def declaration(tmp_path, *, dsid=410470, split=True):
    path = tmp_path / 'declaration.json'
    path.write_text(json.dumps({
        'schema_version': 1, 'rse': 'SITE_RSE', 'split_by_campaign': split,
        'campaigns': {'rules': [{'pattern': '_r13144_', 'campaign': 'mc20a'}, {'pattern': '_r13145_', 'campaign': 'mc20d'},
                                {'pattern': 'data18_13TeV', 'campaign': 'data18'}]},
        'samples': [{'id': 'ttbar', 'kind': 'background_mc', 'dsid': dsid, 'process': 'ttbar', 'tree': 'CollectionTree',
                     'dids': [DID_A, DID_B]},
                    {'id': 'data', 'kind': 'data', 'dsid': None, 'process': 'data', 'tree': 'CollectionTree',
                     'dids': [DID_DATA]}]}))
    return path


def test_resolve_with_rucio_client(tmp_path):
    client = fake_client()
    out = tmp_path / 'resolved.json'
    doc = dr.resolve(declaration(tmp_path), out, client=client)
    assert ('list_replicas', ('DAOD_A._000000.pool.root.1', 'DAOD_A._000001.pool.root.1'), ('root',), 'SITE_RSE') in client.calls
    ids = [s['id'] for s in doc['samples']]
    assert ids == ['ttbar.mc20a', 'ttbar.mc20d', 'data.data18']
    member = doc['samples'][0]['members'][0]
    assert member['uri'] == 'root://eos.example.ch//eos/rucio/DAOD_A._000000.pool.root.1'
    assert member['checksum']['algorithm'] == 'adler32' and member['checksum']['value'] == '0000000a'
    assert member['entries'] == 100 and member['size_bytes'] == 1000 and member['tree'] == 'CollectionTree'
    authority = member['checksum']['authority']
    assert Path(authority['path']).is_file() and doc['membership_authority'] == authority
    assert json.loads(out.read_text()) == doc


def test_resolve_with_supplied_listing_matches_client(tmp_path):
    client = fake_client()
    listing = tmp_path / 'listing.json'
    listing.write_text(json.dumps({'files': client.files, 'replicas': client.replicas}))
    from_listing = dr.resolve(declaration(tmp_path), tmp_path / 'a.json', listing=listing)
    from_client = dr.resolve(declaration(tmp_path), tmp_path / 'b.json', client=fake_client())
    strip = lambda d: [[{k: m[k] for k in m if k != 'checksum'} for m in s['members']] for s in d['samples']]
    assert strip(from_listing) == strip(from_client)


def test_resolve_refuses_missing_replica_and_events(tmp_path):
    client = fake_client()
    client.replicas[f"mc20_13TeV:DAOD_A._000001.pool.root.1"] = []
    with pytest.raises(ValueError, match='no root replica'):
        dr.resolve(declaration(tmp_path), tmp_path / 'r.json', client=client)
    client = fake_client()
    client.files[DID_A][0]['events'] = None
    with pytest.raises(ValueError, match='entries'):
        dr.resolve(declaration(tmp_path), tmp_path / 'r2.json', client=client)


def test_resolve_refuses_dsid_mismatch_with_dataset_name(tmp_path):
    with pytest.raises(ValueError, match='DSID'):
        dr.resolve(declaration(tmp_path, dsid=999999), tmp_path / 'r.json', client=fake_client())


def test_unsplit_sample_spanning_campaigns_is_refused(tmp_path):
    with pytest.raises(ValueError, match='campaign'):
        dr.resolve(declaration(tmp_path, split=False), tmp_path / 'r.json', client=fake_client())


def write_bookkeeper(path, dsid, sumw):
    with uproot.recreate(path) as f:
        f[f'CutBookkeeper_{dsid}_1_NOSYS'] = (np.array([10.0, sumw, sumw * 2]), np.array([0.0, 1.0, 2.0, 3.0]))


def normalization_inputs(tmp_path, resolved):
    # Local stand-ins for the member files: same members, file:// URIs.
    sums = {}
    for s in resolved['samples']:
        for i, m in enumerate(s['members']):
            local = tmp_path / 'files' / (m['id'].split(':')[1])
            local.parent.mkdir(exist_ok=True)
            if s['kind'] != 'data':
                write_bookkeeper(local, s['dsid'], 2.5 + i)
                sums.setdefault(s['id'], 0.0)
                sums[s['id']] += 2.5 + i
            m['uri'] = 'file://' + str(local)
    xsec = tmp_path / 'xsec.txt'
    xsec.write_text('dataset_number/I:physics_short/C:crossSection/D:genFiltEff/D:kFactor/D:etag/C\n'
                    '410470 PhPy8EG_ttbar 729.77 0.5438 1.1398 e6337\n'
                    '410471 PhPy8EG_other 1.0 1.0 1.0 e6337\n')
    descriptor = tmp_path / 'xsec-descriptor.json'
    descriptor.write_text(json.dumps({'columns': {'dsid': 'dataset_number', 'cross_section': 'crossSection',
                                                  'filter_efficiency': 'genFiltEff', 'k_factor': 'kFactor', 'etag': 'etag'},
                                      'cross_section_unit': 'pb'}))
    lumi = tmp_path / 'lumi.json'
    lumi.write_text(json.dumps({'unit': 'fb-1', 'campaigns': {'mc20a': 36.6, 'mc20d': 44.6, 'data18': 58.8}}))
    bookkeeper = tmp_path / 'bookkeeper.json'
    bookkeeper.write_text(json.dumps({'object': 'CutBookkeeper_{dsid}_*_NOSYS', 'kind': 'histogram', 'bin': 2}))
    return xsec, descriptor, lumi, bookkeeper, sums


def test_normalize_builds_root_stream_dataset(tmp_path):
    resolved_path = tmp_path / 'resolved.json'
    resolved = dr.resolve(declaration(tmp_path), resolved_path, client=fake_client())
    xsec, descriptor, lumi, bookkeeper, sums = normalization_inputs(tmp_path, resolved)
    resolved_path.write_text(json.dumps(resolved))
    out = tmp_path / 'dataset.json'
    dataset = dr.normalize(resolved_path, out, xsec_db=xsec, xsec_descriptor=descriptor, lumi=lumi, bookkeeper=bookkeeper)
    core.dataset(dataset)
    ttbar = next(s for s in dataset['samples'] if s['id'] == 'ttbar.mc20a')
    n = ttbar['normalization']
    assert n['sum_weights'] == pytest.approx(sums['ttbar.mc20a'])
    assert n['cross_section_pb'] == 729.77 and n['filter_efficiency'] == 0.5438 and n['k_factor'] == 1.1398
    assert n['luminosity_fb_inverse'] == 36.6
    assert next(s for s in dataset['samples'] if s['id'] == 'data.data18')['normalization'] is None
    record = json.loads(Path(n['source']['path']).read_text())
    assert record['sample_id'] == 'ttbar.mc20a' and record['sum_weights'] == n['sum_weights']
    original = json.loads(Path(n['original_population']['path']).read_text())
    assert [m['guid'] for m in original['members']] == [m['guid'] for m in ttbar['members']]
    authority = json.loads(Path(dataset['membership_authority']['path']).read_text())
    assert authority == {'schema_version': 1, 'samples': dataset['samples']}
    provenance = json.loads((tmp_path / 'dataset.provenance.json').read_text())
    assert provenance['xsec_db']['sha256'] and provenance['per_member_sum_weights']


def test_normalize_refuses_mismatched_dsid(tmp_path):
    resolved_path = tmp_path / 'resolved.json'
    resolved = dr.resolve(declaration(tmp_path), resolved_path, client=fake_client())
    xsec, descriptor, lumi, bookkeeper, _ = normalization_inputs(tmp_path, resolved)
    for s in resolved['samples']:
        for m in s['members']:
            if s['kind'] != 'data':
                write_bookkeeper(Path(m['uri'][7:]), 410471, 1.0)
    resolved_path.write_text(json.dumps(resolved))
    with pytest.raises(ValueError, match='bookkeeper'):
        dr.normalize(resolved_path, tmp_path / 'd.json', xsec_db=xsec, xsec_descriptor=descriptor, lumi=lumi, bookkeeper=bookkeeper)


def test_normalize_refuses_dsid_absent_from_xsec_db(tmp_path):
    resolved_path = tmp_path / 'resolved.json'
    resolved = dr.resolve(declaration(tmp_path), resolved_path, client=fake_client())
    xsec, descriptor, lumi, bookkeeper, _ = normalization_inputs(tmp_path, resolved)
    resolved_path.write_text(json.dumps(resolved))
    xsec.write_text('dataset_number/I:crossSection/D:genFiltEff/D:kFactor/D:etag/C\n410471 1.0 1.0 1.0 e1\n')
    with pytest.raises(ValueError, match='410470'):
        dr.normalize(resolved_path, tmp_path / 'd.json', xsec_db=xsec, xsec_descriptor=descriptor, lumi=lumi, bookkeeper=bookkeeper)


def test_normalize_requires_declared_units(tmp_path):
    resolved_path = tmp_path / 'resolved.json'
    resolved = dr.resolve(declaration(tmp_path), resolved_path, client=fake_client())
    xsec, descriptor, lumi, bookkeeper, _ = normalization_inputs(tmp_path, resolved)
    resolved_path.write_text(json.dumps(resolved))
    descriptor.write_text(json.dumps({'columns': {'dsid': 'dataset_number', 'cross_section': 'crossSection',
                                                  'filter_efficiency': 'genFiltEff', 'k_factor': 'kFactor'}}))
    with pytest.raises(ValueError, match='unit'):
        dr.normalize(resolved_path, tmp_path / 'd.json', xsec_db=xsec, xsec_descriptor=descriptor, lumi=lumi, bookkeeper=bookkeeper)


def test_supplied_sum_weights_table(tmp_path):
    resolved_path = tmp_path / 'resolved.json'
    resolved = dr.resolve(declaration(tmp_path), resolved_path, client=fake_client())
    xsec, descriptor, lumi, _, _ = normalization_inputs(tmp_path, resolved)
    resolved_path.write_text(json.dumps(resolved))
    table = tmp_path / 'sumw.json'
    rows = {m['id']: 4.0 for s in resolved['samples'] if s['kind'] != 'data' for m in s['members']}
    table.write_text(json.dumps({'kind': 'per-member-sum-weights', 'values': rows}))
    bookkeeper = tmp_path / 'bk.json'
    bookkeeper.write_text(json.dumps({'kind': 'table', 'table': str(table)}))
    dataset = dr.normalize(resolved_path, tmp_path / 'd.json', xsec_db=xsec, xsec_descriptor=descriptor, lumi=lumi, bookkeeper=bookkeeper)
    assert next(s for s in dataset['samples'] if s['id'] == 'ttbar.mc20a')['normalization']['sum_weights'] == 8.0
