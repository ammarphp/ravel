"""Site dataset resolution (rucio or supplied listing) and MC normalization building."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import numpy as np
import pytest
import uproot

from ravel.physics import dataset_resolution as dr
from ravel.physics import root_stream_core as core

DID_A = 'sim_scope:sim_scope.101.process_a.deriv.NTUPLE.e100_s100_r1001_p100'
DID_B = 'sim_scope:sim_scope.101.process_a.deriv.NTUPLE.e100_s100_r1002_p100'
DID_DATA = 'observed_scope:observed_scope.recorded.NTUPLE.tag1_p100'


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


def file_rows(prefix, n, scope='sim_scope', events=100):
    return [{'scope': scope, 'name': f'{prefix}._{i:06d}.pool.root.1', 'guid': f'{prefix}-{i:04d}-guid'.upper(),
             'adler32': f'{i + 10:x}', 'bytes': 1000 + i, 'events': events + i} for i in range(n)]


def fake_client():
    files = {DID_A: file_rows('DAOD_A', 2), DID_B: file_rows('DAOD_B', 1), DID_DATA: file_rows('DAOD_D', 1, scope='observed_scope')}
    replicas = {}
    for rows in files.values():
        for r in rows:
            replicas[f"{r['scope']}:{r['name']}"] = [f"root://eos.example.ch//eos/rucio/{r['name']}"]
    return FakeRucio(files, replicas)


def declaration(tmp_path, *, dsid=101, split=True):
    path = tmp_path / 'declaration.json'
    path.write_text(json.dumps({
        'schema_version': 1, 'rse': 'SITE_RSE', 'split_by_campaign': split,
        'campaigns': {'rules': [{'pattern': '_r1001_', 'campaign': 'era_a'}, {'pattern': '_r1002_', 'campaign': 'era_b'},
                                {'pattern': 'observed_scope', 'campaign': 'observed_era'}]},
        'samples': [{'id': 'process_a', 'kind': 'background_mc', 'dsid': dsid, 'process': 'process_a', 'tree': 'Events',
                     'dids': [DID_A, DID_B]},
                    {'id': 'data', 'kind': 'data', 'dsid': None, 'process': 'data', 'tree': 'Events',
                     'dids': [DID_DATA]}]}))
    return path


def test_resolve_with_rucio_client(tmp_path):
    client = fake_client()
    out = tmp_path / 'resolved.json'
    doc = dr.resolve(declaration(tmp_path), out, client=client)
    assert ('list_replicas', ('DAOD_A._000000.pool.root.1', 'DAOD_A._000001.pool.root.1'), ('root',), 'SITE_RSE') in client.calls
    ids = [s['id'] for s in doc['samples']]
    assert ids == ['process_a.era_a', 'process_a.era_b', 'data.observed_era']
    member = doc['samples'][0]['members'][0]
    assert member['uri'] == 'root://eos.example.ch//eos/rucio/DAOD_A._000000.pool.root.1'
    assert member['checksum']['algorithm'] == 'adler32' and member['checksum']['value'] == '0000000a'
    assert member['entries'] == 100 and member['size_bytes'] == 1000 and member['tree'] == 'Events'
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
    client.replicas[f"sim_scope:DAOD_A._000001.pool.root.1"] = []
    with pytest.raises(ValueError, match='no root replica'):
        dr.resolve(declaration(tmp_path), tmp_path / 'r.json', client=client)
    client = fake_client()
    client.files[DID_A][0]['events'] = None
    with pytest.raises(ValueError, match='entries'):
        dr.resolve(declaration(tmp_path), tmp_path / 'r2.json', client=client)


def test_resolve_refuses_dsid_mismatch_with_dataset_name(tmp_path):
    with pytest.raises(ValueError, match='DSID'):
        dr.resolve(declaration(tmp_path, dsid=999), tmp_path / 'r.json', client=fake_client())


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
                    '101 process_a 2.0 0.5 1.2 e100\n'
                    '102 process_b 1.0 1.0 1.0 e100\n')
    descriptor = tmp_path / 'xsec-descriptor.json'
    descriptor.write_text(json.dumps({'columns': {'dsid': 'dataset_number', 'cross_section': 'crossSection',
                                                  'filter_efficiency': 'genFiltEff', 'k_factor': 'kFactor', 'etag': 'etag'},
                                      'cross_section_unit': 'pb'}))
    lumi = tmp_path / 'lumi.json'
    lumi.write_text(json.dumps({'unit': 'fb-1', 'campaigns': {'era_a': 10.0, 'era_b': 20.0, 'observed_era': 30.0}}))
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
    process_a = next(s for s in dataset['samples'] if s['id'] == 'process_a.era_a')
    n = process_a['normalization']
    assert n['sum_weights'] == pytest.approx(sums['process_a.era_a'])
    assert n['cross_section_pb'] == 2.0 and n['filter_efficiency'] == 0.5 and n['k_factor'] == 1.2
    assert n['luminosity_fb_inverse'] == 10.0
    assert next(s for s in dataset['samples'] if s['id'] == 'data.observed_era')['normalization'] is None
    record = json.loads(Path(n['source']['path']).read_text())
    assert record['sample_id'] == 'process_a.era_a' and record['sum_weights'] == n['sum_weights']
    original = json.loads(Path(n['original_population']['path']).read_text())
    assert [m['guid'] for m in original['members']] == [m['guid'] for m in process_a['members']]
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
                write_bookkeeper(Path(m['uri'][7:]), 102, 1.0)
    resolved_path.write_text(json.dumps(resolved))
    with pytest.raises(ValueError, match='bookkeeper'):
        dr.normalize(resolved_path, tmp_path / 'd.json', xsec_db=xsec, xsec_descriptor=descriptor, lumi=lumi, bookkeeper=bookkeeper)


def test_normalize_refuses_dsid_absent_from_xsec_db(tmp_path):
    resolved_path = tmp_path / 'resolved.json'
    resolved = dr.resolve(declaration(tmp_path), resolved_path, client=fake_client())
    xsec, descriptor, lumi, bookkeeper, _ = normalization_inputs(tmp_path, resolved)
    resolved_path.write_text(json.dumps(resolved))
    xsec.write_text('dataset_number/I:crossSection/D:genFiltEff/D:kFactor/D:etag/C\n102 1.0 1.0 1.0 e1\n')
    with pytest.raises(ValueError, match='101'):
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
    assert next(s for s in dataset['samples'] if s['id'] == 'process_a.era_a')['normalization']['sum_weights'] == 8.0


def prepared_inputs(tmp_path):
    resolved_path = tmp_path / 'resolved.json'
    resolved = dr.resolve(declaration(tmp_path), resolved_path, client=fake_client())
    xsec, descriptor, lumi, bookkeeper, _ = normalization_inputs(tmp_path, resolved)
    resolved_path.write_text(json.dumps(resolved))
    return resolved_path, resolved, dict(xsec_db=xsec, xsec_descriptor=descriptor, lumi=lumi, bookkeeper=bookkeeper)


def count_opens(monkeypatch, tmp_path):
    log = tmp_path / 'opens.txt'
    original = dr._open_uri

    def tracked(uri):
        with log.open('a') as stream:
            stream.write(uri + '\n')
        return original(uri)

    monkeypatch.setattr(dr, '_open_uri', tracked)
    return log


def test_cache_hits_then_changed_checksum_and_guid_reread_only_one_file(tmp_path, monkeypatch):
    path, resolved, inputs = prepared_inputs(tmp_path)
    log = count_opens(monkeypatch, tmp_path)
    cache = tmp_path / 'cache.json'
    dr.normalize(path, tmp_path / 'a.json', cache=cache, **inputs)
    assert len(log.read_text().splitlines()) == 3
    log.write_text('')
    dr.normalize(path, tmp_path / 'b.json', cache=cache, **inputs)
    assert log.read_text() == ''
    timing = json.loads((tmp_path / 'b.bookkeeping.json').read_text())
    assert timing['cache_hits'] == 3 and timing['files_read'] == timing['attempts'] == 0
    member = resolved['samples'][0]['members'][0]
    member['checksum']['value'] = '00000abc'
    path.write_text(json.dumps(resolved))
    dr.normalize(path, tmp_path / 'c.json', cache=cache, **inputs)
    assert log.read_text().splitlines() == [member['uri']]
    log.write_text('')
    member['guid'] = 'NEW-SYNTHETIC-GUID'
    path.write_text(json.dumps(resolved))
    dr.normalize(path, tmp_path / 'd.json', cache=cache, **inputs)
    assert log.read_text().splitlines() == [member['uri']]


def test_cache_context_changes_when_bookkeeper_changes(tmp_path, monkeypatch):
    _, resolved, _ = prepared_inputs(tmp_path)
    member, sample = resolved['samples'][0]['members'][0], resolved['samples'][0]
    log = count_opens(monkeypatch, tmp_path)
    cache = {'schema_version': 1, 'entries': {}}
    keeper = {'kind': 'histogram', 'object': 'CutBookkeeper_{dsid}_*_NOSYS', 'bin': 2}
    first = dr.member_sum_weights(member, sample, keeper, cache=cache)
    assert dr.member_sum_weights(member, sample, keeper, cache=cache) == first
    assert len(log.read_text().splitlines()) == 1
    keeper['bin'] = 1
    assert dr.member_sum_weights(member, sample, keeper, cache=cache)[0] == 10.0
    assert len(log.read_text().splitlines()) == 2


@pytest.mark.parametrize('kind', ['background_mc', 'signal_mc'])
def test_missing_campaign_without_rule_refuses_before_bookkeeping(tmp_path, monkeypatch, kind):
    path, resolved, inputs = prepared_inputs(tmp_path)
    resolved['samples'] = [s for s in resolved['samples'] if s.get('campaign') != 'era_b']
    resolved['samples'][0]['kind'] = kind
    path.write_text(json.dumps(resolved))
    monkeypatch.setattr(dr, '_open_uri', lambda uri: pytest.fail('missing campaign must refuse before opening files'))
    with pytest.raises(ValueError, match=r'process_a.*era_b'):
        dr.normalize(path, tmp_path / 'out.json', **inputs)
    assert not (tmp_path / 'out.json').exists()
    assert not (tmp_path / 'out.sources').exists()


@pytest.mark.parametrize('rule,luminosity', [('exclude', 0.0), ('available-luminosity-only', 10.0), ('scale-to-full', 30.0)])
def test_missing_campaign_policies_and_ledger(tmp_path, rule, luminosity):
    path, resolved, inputs = prepared_inputs(tmp_path)
    resolved['samples'] = [s for s in resolved['samples'] if s.get('campaign') != 'era_b']
    resolved['campaigns'].update(expected=['era_a', 'era_b'], missing_rule=rule)
    if rule == 'scale-to-full':
        resolved['campaigns']['assumption'] = 'Identical selected population per unit luminosity in the missing era.'
    path.write_text(json.dumps(resolved))
    out = tmp_path / 'dataset.json'
    dataset = dr.normalize(path, out, **inputs)
    record = json.loads((tmp_path / 'dataset.provenance.json').read_text())['missing_campaigns']['process_a.era_a']
    assert record['missing'] == ['era_b'] and record['rule'] == rule
    assert record['luminosity_used'] == luminosity and record['unit'] == 'fb-1'
    samples = [s for s in dataset['samples'] if s['kind'] != 'data']
    if rule == 'exclude':
        assert samples == []
    else:
        assert samples[0]['normalization']['luminosity_fb_inverse'] == luminosity
        if rule == 'scale-to-full':
            assert record['assumption'] == resolved['campaigns']['assumption']


def test_scale_to_full_needs_assumption(tmp_path):
    path, resolved, inputs = prepared_inputs(tmp_path)
    resolved['samples'] = [s for s in resolved['samples'] if s.get('campaign') != 'era_b']
    resolved['campaigns']['missing_rule'] = 'scale-to-full'
    path.write_text(json.dumps(resolved))
    with pytest.raises(ValueError, match='stated assumption'):
        dr.normalize(path, tmp_path / 'out.json', **inputs)


def test_all_missing_cross_sections_and_duplicate_rows_reported_together(tmp_path):
    path, resolved, inputs = prepared_inputs(tmp_path)
    resolved['samples'][1]['dsid'] = 103
    path.write_text(json.dumps(resolved))
    inputs['xsec_db'].write_text('dataset_number crossSection genFiltEff kFactor etag\n102 1 1 1 e100\n')
    with pytest.raises(ValueError) as error:
        dr.normalize(path, tmp_path / 'out.json', **inputs)
    assert '101' in str(error.value) and '103' in str(error.value)
    assert not (tmp_path / 'out.sources').exists()
    inputs['xsec_db'].write_text('dataset_number crossSection genFiltEff kFactor etag\n101 1 1 1 e100\n101 1 1 1 e100\n')
    with pytest.raises(ValueError) as error:
        dr.normalize(path, tmp_path / 'out.json', **inputs)
    assert '101 has 2' in str(error.value) and '103' in str(error.value)


def test_whitespace_xsec_header_and_descriptor_alias(tmp_path):
    path, _, inputs = prepared_inputs(tmp_path)
    inputs['xsec_db'].write_text('dataset_number crossSection genFiltEff kFactor etag\n101 2.0 0.5 1.2 e100\n')
    out = tmp_path / 'out.json'
    assert dr.main(['normalize', '--resolved', str(path), '--out', str(out), '--xsec-db', str(inputs['xsec_db']),
                    '--xsec-db-descriptor', str(inputs['xsec_descriptor']), '--lumi', str(inputs['lumi']),
                    '--bookkeeper', str(inputs['bookkeeper'])]) == 0
    assert json.loads(out.read_text())['samples'][0]['normalization']['cross_section_pb'] == 2.0


def test_bounded_reader_parallelism_and_timing(tmp_path, monkeypatch):
    _, resolved, _ = prepared_inputs(tmp_path)
    sample = resolved['samples'][0]
    log = tmp_path / 'parallel.jsonl'

    def reader(member, sample, keeper):
        with log.open('a') as stream:
            stream.write(json.dumps([time.monotonic(), 1, os.getpid()]) + '\n')
        time.sleep(0.04)
        with log.open('a') as stream:
            stream.write(json.dumps([time.monotonic(), -1, os.getpid()]) + '\n')
        return 2.0, 'synthetic'

    monkeypatch.setattr(dr, '_read_member_sum_weights', reader)
    members = [{**sample['members'][0], 'id': f'file{i}', 'guid': f'guid{i}'} for i in range(12)]
    results, timing = dr._bookkeeping([(m, sample) for m in members], {'kind': 'tree-sum'}, workers=3)
    events = sorted(json.loads(line) for line in log.read_text().splitlines())
    active, maximum = 0, 0
    for _, delta, _ in events:
        active += delta
        maximum = max(maximum, active)
    assert 1 < maximum <= 3 and active == 0
    assert len(results) == 12 and timing['files_read'] == timing['attempts'] == 12
    assert timing['workers'] == 3 and timing['complete'] and timing['failures'] == {}
    assert timing['files_per_second'] > 0


def test_timeout_writes_failure_timing_and_never_complete_dataset(tmp_path, monkeypatch):
    path, resolved, inputs = prepared_inputs(tmp_path)
    stuck = resolved['samples'][0]['members'][0]['id']

    def reader(member, sample, keeper):
        if member['id'] == stuck:
            time.sleep(10)
        return 2.0, 'synthetic'

    monkeypatch.setattr(dr, '_read_member_sum_weights', reader)
    out, cache = tmp_path / 'out.json', tmp_path / 'cache.json'
    start = time.monotonic()
    with pytest.raises(ValueError, match='incomplete'):
        dr.normalize(path, out, cache=cache, timeout=0.1, **inputs)
    assert time.monotonic() - start < 3
    assert not out.exists() and not (tmp_path / 'out.sources').exists()
    timing = json.loads((tmp_path / 'out.bookkeeping.json').read_text())
    assert timing['complete'] is False and stuck in timing['failures']
    assert timing['retries'] == 0 and timing['attempts'] == 3
    assert len(json.loads(cache.read_text())['entries']) == 2


def test_declared_retry_and_failed_entry_not_cached(tmp_path, monkeypatch):
    _, resolved, _ = prepared_inputs(tmp_path)
    sample = resolved['samples'][0]
    member = sample['members'][0]
    marker = tmp_path / 'attempt'

    def reader(member, sample, keeper):
        if not marker.exists():
            marker.write_text('failed')
            raise OSError('transient synthetic failure')
        return 3.0, 'synthetic'

    monkeypatch.setattr(dr, '_read_member_sum_weights', reader)
    cache = {'schema_version': 1, 'entries': {}}
    results, timing = dr._bookkeeping([(member, sample)], {}, cache=cache, retries=1)
    assert results[member['id']] == (3.0, 'synthetic')
    assert timing['attempts'] == 2 and timing['complete']
    assert len(cache['entries']) == 1


def test_same_campaign_shards_share_full_denominator(tmp_path):
    path, resolved, inputs = prepared_inputs(tmp_path)
    from copy import deepcopy
    first = resolved['samples'][0]
    shard = deepcopy(first)
    shard['id'] = 'another_shard'
    shard['members'] = first['members'][1:]
    first['members'] = first['members'][:1]
    resolved['samples'].append(shard)
    path.write_text(json.dumps(resolved))
    dataset = dr.normalize(path, tmp_path / 'out.json', **inputs)
    shard = next(s for s in dataset['samples'] if s['id'] == 'another_shard')
    first = dataset['samples'][0]
    assert first['normalization']['sum_weights'] == shard['normalization']['sum_weights'] == 6.0
    assert len(json.loads(Path(shard['normalization']['original_population']['path']).read_text())['members']) == 2


def test_scale_to_full_preserves_available_campaign_luminosity_ratios(tmp_path):
    path, resolved, inputs = prepared_inputs(tmp_path)
    resolved['campaigns'].update(expected=['era_a', 'era_b', 'era_c'], missing_rule='scale-to-full',
                                 assumption='Declared identical yield per unit luminosity across eras.')
    lumi = json.loads(inputs['lumi'].read_text())
    lumi['campaigns']['era_c'] = 30.0
    inputs['lumi'].write_text(json.dumps(lumi))
    path.write_text(json.dumps(resolved))
    dataset = dr.normalize(path, tmp_path / 'out.json', **inputs)
    assert [s['normalization']['luminosity_fb_inverse'] for s in dataset['samples'] if s['kind'] != 'data'] == [20.0, 40.0]
    ledger = json.loads((tmp_path / 'out.provenance.json').read_text())['missing_campaigns']
    assert all(r['luminosity_used'] == 60.0 and r['missing'] == ['era_c'] for r in ledger.values())


def test_per_sample_policy_and_cross_section_selection(tmp_path):
    path, resolved, inputs = prepared_inputs(tmp_path)
    resolved['samples'] = [s for s in resolved['samples'] if s.get('campaign') != 'era_b']
    resolved['samples'][0]['missing_campaign_rule'] = 'available-luminosity-only'
    path.write_text(json.dumps(resolved))
    inputs['xsec_db'].write_text('dataset_number crossSection genFiltEff kFactor etag\n101 2.0 0.5 1.2 first\n101 5.0 1.0 1.0 second\n')
    descriptor = json.loads(inputs['xsec_descriptor'].read_text())
    descriptor['select'] = {'etag': 'first'}
    inputs['xsec_descriptor'].write_text(json.dumps(descriptor))
    dataset = dr.normalize(path, tmp_path / 'out.json', **inputs)
    assert dataset['samples'][0]['normalization']['cross_section_pb'] == 2.0
    source = json.loads(Path(dataset['samples'][0]['normalization']['source']['path']).read_text())
    assert source['missing_campaigns']['rule'] == 'available-luminosity-only'


@pytest.mark.parametrize('setting', [{'workers': 0}, {'workers': True}, {'timeout': 0}, {'retries': -1}])
def test_bookkeeping_rejects_invalid_bounds(tmp_path, setting):
    with pytest.raises(ValueError):
        dr._bookkeeping([], {}, **setting)
