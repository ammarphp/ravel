"""Synthetic streaming skim, custody and throughput controls."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil

import awkward as ak
import numpy as np
import pytest
import uproot

from ravel.physics.columnar import engine, formats, skim
from ravel.physics.columnar.recipe import compile_recipe
from ravel.workflow import partitioned_execution as pe


def descriptor():
    return formats.load_descriptor({'schema_version': 1, 'kind': 'columnar-format', 'name': 'synthetic events',
                                    'source': 'synthetic fixture', 'format': 'root', 'tree': 'Events',
                                    'collections': {}, 'met': {'magnitude': 'magnitude', 'phi': 'angle'},
                                    'event': {'generator': 'generator', 'factor': 'factor', 'identifier': 'identifier'}})


def recipe(output=True, format='root', branches='all-declared'):
    doc = {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'synthetic threshold selection',
           'weights': {'generator': 'generator', 'factors': ['factor']}, 'objects': [],
           'observables': [{'name': 'magnitude', 'op': 'met'}],
           'regions': [{'name': 'passing', 'cuts': [{'name': 'threshold', 'expr': 'magnitude >= 20'}]}],
           'histograms': [{'name': 'selected magnitude', 'region': 'passing', 'observable': 'magnitude',
                           'edges': [0, 20, 40, 80], 'unit': 'GeV', 'label': 'Missing momentum', 'normalization': 'raw'}]}
    if output:
        doc['skim'] = {'region': 'passing', 'branches': branches, 'format': format}
    return doc


def population(tmp_path):
    path = tmp_path / 'events.root'
    arrays = {'magnitude': np.array([10., 20., 30., 40., 50., 60.]), 'angle': np.zeros(6),
              'generator': np.array([1., -2., 0., 3., 4., -1.]), 'factor': np.array([2., 3., 1., 0.5, 2., 1.]),
              'identifier': np.array([101, 102, 103, 104, 105, 106], dtype=np.int64), 'undeclared': np.ones(6)}
    with uproot.recreate(path) as f:
        f.mktree('Events', {k: v.dtype for k, v in arrays.items()})
        f['Events'].extend(arrays)
    return path, arrays


def analyse(path, doc, tmp_path, *, output='out', start=0, stop=None, index=0, chunk=2):
    plan = compile_recipe(doc, descriptor(), tmp_path)
    partition = {'inputs': [{'path': str(path), 'file_index': index}], 'chunk_size': chunk}
    if path.suffix != '.json':
        partition['inputs'][0].update(entry_start=start, entry_stop=stop)
    partial = engine.analyse(partition, plan, skim_dir=tmp_path / output)
    return partial, plan


@pytest.mark.parametrize('format', ['root', 'parquet'])
def test_skim_keeps_exact_passing_events_and_replays_same_recipe(tmp_path, format):
    if format == 'parquet':
        pytest.importorskip('pyarrow')
    path, arrays = population(tmp_path)
    doc = recipe(format=format)
    part, plan = analyse(path, doc, tmp_path)
    pin = part['skims'][0]
    custody = skim.validate_partition(pin)
    assert custody['entries_in'] == 6 and custody['entries_out'] == 5
    assert custody['sum_weights_in'] == 4.5 and custody['sum_weights_out'] == 2.5
    kept = ak.concatenate([ak.Array(c) for c in skim._data_chunks(custody, custody['branches'] + list(skim.RESERVED), 2)])
    assert kept.identifier.tolist() == arrays['identifier'][1:].tolist()
    assert kept.ravel_event_number.tolist() == [1, 2, 3, 4, 5]
    assert kept.ravel_weight.tolist() == [-6., 0., 1.5, 8., -1.]
    assert 'undeclared' not in kept.fields
    replay, _ = analyse(Path(pin['path']), doc, tmp_path, output='replay', chunk=3)
    a = part['variations']['nominal']['histograms']
    b = replay['variations']['nominal']['histograms']
    assert a == b
    assert skim.validate_partition(replay['skims'][0])['sum_weights_out'] == 2.5
    assert part['throughput']['entries'] == 6
    assert part['throughput']['bytes_read'] == 6 * 5 * 8
    assert part['throughput']['columns_read'] == sorted(custody['branches'])
    merged = engine.merge([part])
    final = engine.finalize(merged, plan, {'mode': 'none'}, out_dir=tmp_path / 'final')
    manifest = tmp_path / 'final/skim-manifest.json'
    assert any(f['path'] == 'skim-manifest.json' for f in final['files'])
    replay2, _ = analyse(manifest, recipe(output=False), tmp_path)
    assert replay2['variations']['nominal']['histograms'] == a
    assert not (tmp_path / 'final/events.root').exists()


def test_partition_merge_pins_totals_and_refuses_tampering(tmp_path):
    path, _ = population(tmp_path)
    p1, _ = analyse(path, recipe(), tmp_path, output='one', stop=3)
    p2, _ = analyse(path, recipe(), tmp_path, output='two', start=3)
    pins = [p1['skims'][0], p2['skims'][0]]
    manifest = pe.merge_documents('skim', pins)
    assert manifest['entries_in'] == 6 and manifest['entries_out'] == 5
    assert manifest['sum_weights_in'] == 4.5 and manifest['sum_weights_out'] == 2.5
    assert engine.merge([p1, p2])['skim_manifest'] == manifest
    with pytest.raises(ValueError, match='duplicate'):
        pe.merge_documents('skim', [pins[0], pins[0]])
    data = Path(manifest['partitions'][0]['data']['path'])
    with data.open('ab') as f:
        f.write(b'tampered')
    with pytest.raises(ValueError, match='checksum'):
        pe.merge_documents('skim', pins)


@pytest.mark.parametrize('change', ['sum_weights_out', 'entries_out', 'inputs', 'recipe_sha256'])
def test_custody_semantics_refuse_even_when_custody_hash_is_updated(tmp_path, change):
    path, _ = population(tmp_path)
    part, _ = analyse(path, recipe(), tmp_path)
    pin = part['skims'][0]
    file = Path(pin['path'])
    doc = json.loads(file.read_bytes())
    if change == 'inputs':
        doc['inputs'][0]['entry_stop'] += 1
    elif change == 'recipe_sha256':
        doc[change] = 'invalid'
    else:
        doc[change] += 1
    file.write_text(json.dumps(doc))
    pin['sha256'] = skim.digest(file)
    with pytest.raises(ValueError):
        pe.merge_documents('skim', [pin])


def test_explicit_branch_subset_and_missing_replay_columns(tmp_path):
    path, _ = population(tmp_path)
    part, _ = analyse(path, recipe(branches=['identifier']), tmp_path)
    custody = skim.validate_partition(part['skims'][0])
    assert custody['branches'] == ['identifier']
    with pytest.raises(ValueError, match='missing branches'):
        analyse(Path(part['skims'][0]['path']), recipe(output=False), tmp_path)


def test_relocated_custody_and_data_remain_readable(tmp_path):
    path, _ = population(tmp_path)
    part, _ = analyse(path, recipe(), tmp_path)
    shutil.copytree(tmp_path / 'out/skim', tmp_path / 'moved')
    moved = tmp_path / 'moved/custody.json'
    pin = {**part['skims'][0], 'path': str(moved)}
    assert skim.validate_partition(pin)['entries_out'] == 5


def test_no_passing_events_still_writes_typed_empty_skim(tmp_path):
    path, _ = population(tmp_path)
    doc = recipe()
    doc['regions'][0]['cuts'][0]['expr'] = 'magnitude > 1000'
    part, _ = analyse(path, doc, tmp_path)
    assert skim.validate_partition(part['skims'][0])['entries_out'] == 0
    replay, _ = analyse(Path(part['skims'][0]['path']), recipe(output=False), tmp_path)
    assert replay['variations']['nominal']['events']['n'] == 0


@pytest.mark.parametrize('spec', [None, {}, {'region': 'missing', 'branches': 'all-declared', 'format': 'root'},
                                  {'region': 'passing', 'branches': ['undeclared'], 'format': 'root'},
                                  {'region': 'passing', 'branches': [], 'format': 'root'},
                                  {'region': 'passing', 'branches': 'all-declared', 'format': 'pickle'}])
def test_invalid_skim_outputs_fail_at_compile(tmp_path, spec):
    doc = recipe()
    doc['skim'] = spec
    with pytest.raises(ValueError, match='skim'):
        compile_recipe(doc, descriptor(), tmp_path)


def pilot_ledger(tmp_path, measurements=True, native=False):
    spec = {'schema_version': 1, 'name': 'synthetic-pass',
            'population': {'members': [{'uri': 'root://storage.invalid/a', 'entries': 100, 'size_bytes': 1000},
                                       {'uri': 'root://storage.invalid/b', 'entries': 200, 'size_bytes': 2000},
                                       {'uri': 'root://storage.invalid/c', 'entries': 700, 'size_bytes': 7000}]},
            'partitioning': {'members_per_partition': 1},
            'stage': {'backend': 'native' if native else 'site', 'argv': ['worker', '{partition_inputs}'],
                      'resources': {'cpus': 4, 'memory_mib': 128, 'wall_seconds': 3600}},
            'outputs': [{'name': 'partial.json', 'merge': 'columnar-partial'}], 'max_concurrent': 2}
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = {}
    for i, (events, duration) in enumerate([(100, 10), (200, 40), (700, None)]):
        attempts = []
        if duration:
            partial = tmp_path / f'partial-{i}.json'
            partial.write_text(json.dumps({'kind': 'columnar-partial', 'throughput': {
                'entries': events, 'bytes_read': events * 24, 'wall_seconds': duration,
                'columns_read': ['x', 'weight'], 'byte_basis': 'decoded-column-bytes'}}))
            receipt = tmp_path / f'receipt-{i}.json'
            receipt.write_text(json.dumps({'outputs': [{'destination': str(partial), 'sha256': skim.digest(partial)}]}))
            attempts = [{'state': 'succeeded', 'started_utc': start.isoformat(),
                         'finished_utc': (start + timedelta(seconds=duration)).isoformat(),
                         'receipt': str(receipt), 'receipt_sha256': skim.digest(receipt)}]
        rows[f'p{i:05d}'] = {'entries': events, 'size_bytes': events * 10,
                              'status': 'succeeded' if duration else 'pending', 'attempts': attempts}
    if not measurements:
        for row in rows.values():
            row.update(status='pending', attempts=[])
    ledger = {'schema_version': 1, 'name': spec['name'], 'specification': spec, 'partitions': rows,
              'specification_sha256': pe.specification_digest(spec)}
    (tmp_path / pe.LEDGER).write_text(json.dumps(ledger))
    return ledger


def test_forecast_two_pilots_projects_whole_dataset_and_spread(tmp_path):
    pilot_ledger(tmp_path)
    f = pe.forecast(tmp_path)
    assert f['seconds_per_event'] == pytest.approx(50 / 300)
    assert f['bytes_read_per_event'] == 24
    assert f['seconds_per_byte'] == pytest.approx(50 / 7200)
    assert f['projected_core_hours'] == pytest.approx(1000 * (50 / 300) * 4 / 3600)
    assert f['projected_wall_hours'] == pytest.approx(1000 * (50 / 300) / 2 / 3600)
    assert f['estimated_core_hours'] == pytest.approx(700 * (50 / 300) * 4 / 3600)
    assert f['pilot_spread']['minimum_seconds_per_unit'] == 0.1
    assert f['pilot_spread']['maximum_seconds_per_unit'] == 0.2
    assert f['cost_record']['resource_vector']['cpu_hours'] == f['projected_core_hours']
    assert f['cost_approval_seam']['supported'] is False


def test_native_forecast_obeys_single_machine_lease(tmp_path):
    pilot_ledger(tmp_path, native=True)
    f = pe.forecast(tmp_path)
    assert f['max_concurrent'] == 1
    assert f['projected_wall_hours'] == pytest.approx(1000 * (50 / 300) / 3600)


def test_forecast_without_pilot_is_uncalibrated(tmp_path):
    pilot_ledger(tmp_path, measurements=False)
    f = pe.forecast(tmp_path)
    assert f['calibration'] == 'uncalibrated' and f['projected_core_hours'] is None
    assert f['seconds_per_event'] is None and f['pilot_spread'] is None


def test_forecast_refuses_tampered_pilot_output(tmp_path):
    pilot_ledger(tmp_path)
    (tmp_path / 'partial-0.json').write_text('{}')
    with pytest.raises(ValueError, match='checksum'):
        pe.forecast(tmp_path)


def test_empty_input_range_and_empty_reexport_keep_schema(tmp_path):
    path, _ = population(tmp_path)
    part, _ = analyse(path, recipe(), tmp_path, start=2, stop=2)
    assert skim.validate_partition(part['skims'][0])['entries_in'] == 0
    replay, _ = analyse(Path(part['skims'][0]['path']), recipe(), tmp_path, output='reexport')
    assert skim.validate_partition(replay['skims'][0])['entries_out'] == 0


def test_jagged_branches_and_original_random_selection_replay(tmp_path):
    from columnar_fixtures import recipe as object_recipe, random_events, write_delphes
    events = random_events(40, seed=7)
    path = write_delphes(tmp_path / 'jagged.root', events)
    d = object_recipe()
    (tmp_path / 'efficiency.json').write_text(json.dumps({
        'axes': [{'name': 'Transverse momentum', 'unit': 'GeV', 'edges': [0, 10000]}], 'values': [0.5]}))
    d['efficiency_maps'] = {'selection': {
        'source': {'format': 'json-grid', 'path': 'efficiency.json'},
        'axes': [{'name': 'Transverse momentum', 'unit': 'GeV'}], 'out_of_range': 'zero',
        'citation': 'synthetic map', 'semantics': 'absolute'}}
    d['objects'].insert(2, {'efficiency': {'name': 'random selection', 'object': 'muons', 'map': 'selection',
                                         'coordinates': ['pt'], 'application': 'select', 'seed': 31,
                                         'card_efficiency': 'synthetic input without detector efficiencies'}})
    d['skim'] = {'region': 'two leptons', 'branches': 'all-declared', 'format': 'root'}
    plan = compile_recipe(d, formats.load_descriptor('delphes'), tmp_path)
    part = engine.analyse({'inputs': [{'path': str(path), 'file_index': 5}], 'chunk_size': 13},
                          plan, skim_dir=tmp_path / 'jagged-output')
    replay = engine.analyse({'inputs': [{'path': part['skims'][0]['path']}], 'chunk_size': 7},
                            plan, skim_dir=tmp_path / 'jagged-replay')
    for name, h in part['variations']['nominal']['histograms'].items():
        other = replay['variations']['nominal']['histograms'][name]
        assert h['entries'] == other['entries']
        assert h['sumw'] == pytest.approx(other['sumw'], abs=1e-12)
        assert h['sumw2'] == pytest.approx(other['sumw2'], abs=1e-12)
    assert skim.validate_partition(part['skims'][0])['entries_out'] > 0


def completed_skims(tmp_path):
    path, _ = population(tmp_path)
    other = tmp_path / 'other.root'
    shutil.copyfile(path, other)
    members = []
    rows = {}
    outputs = [{'name': 'skim/custody.json', 'merge': 'skim'}, {'name': 'skim/events.root', 'merge': 'none'}]
    for n, source in enumerate([path, other]):
        part, _ = analyse(source, recipe(), tmp_path, output=f'partition-{n}', index=n)
        pid = f'p{n:05d}'
        member = {'path': str(source), 'checksum': 'sha256:' + skim.digest(source), 'entries': 6,
                  'size_bytes': source.stat().st_size}
        members.append(member)
        directory = tmp_path / f'partition-{n}'
        receipt_path = directory / 'receipt.json'
        receipt_path.write_text(json.dumps({'outputs': [
            {'name': o['name'], 'destination': str(directory / o['name']), 'sha256': skim.digest(directory / o['name'])}
            for o in outputs]}))
        rows[pid] = {'members_sha256': pe.eb.digest([member]), 'entries': 6, 'size_bytes': member['size_bytes'],
                     'status': 'succeeded', 'attempts': [{'state': 'succeeded', 'receipt': str(receipt_path),
                                                         'receipt_sha256': skim.digest(receipt_path)}]}
    work = tmp_path / 'work'
    work.mkdir()
    spec = {'schema_version': 1, 'name': 'synthetic-partitions', 'population': {'members': members},
            'partitioning': {'members_per_partition': 1}, 'outputs': outputs,
            'stage': {'backend': 'native', 'argv': ['worker', '{partition_inputs}'],
                      'resources': {'cpus': 1, 'memory_mib': 128, 'wall_seconds': 60}}}
    ledger = {'schema_version': 1, 'name': spec['name'], 'specification': spec, 'partitions': rows,
              'specification_sha256': pe.specification_digest(spec)}
    (work / pe.LEDGER).write_text(json.dumps(ledger))
    return work, ledger


def test_partition_receipt_merge_references_checked_skims(tmp_path):
    work, _ = completed_skims(tmp_path)
    receipt = pe.merge(work)
    result = json.loads((work / 'merged/skim/custody.json').read_bytes())
    assert result['kind'] == 'columnar-skim-manifest' and result['entries_out'] == 10
    assert result['sum_weights_out'] == 5.0
    assert receipt['merged'][0]['merge'] == 'skim'
    assert not (work / 'merged/skim/events.root').exists()
    replay, _ = analyse(work / 'merged/skim/custody.json', recipe(output=False), tmp_path)
    assert replay['variations']['nominal']['events']['n'] == 10


def test_partition_merge_refuses_custody_for_a_different_input(tmp_path):
    work, ledger = completed_skims(tmp_path)
    # Keep the custody internally valid, but attach it to a different population member.
    ledger['specification']['population']['members'][0]['checksum'] = 'sha256:' + '0' * 64
    ledger['specification_sha256'] = pe.specification_digest(ledger['specification'])
    ledger['partitions']['p00000']['members_sha256'] = pe.eb.digest(ledger['specification']['population']['members'][:1])
    (work / pe.LEDGER).write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match='checksum differs from declared partition'):
        pe.merge(work)


def test_frontend_descriptor_validation_admits_pinned_skim_inputs(tmp_path):
    path, _ = population(tmp_path)
    part, _ = analyse(path, recipe(), tmp_path)
    later = compile_recipe(recipe(output=False), descriptor(), tmp_path)
    report = later.descriptor.check_file(part['skims'][0]['path'], collections=[],
                                         event_fields=['generator', 'factor'])
    assert report['entries'] == 5 and report['input_kind'] == 'columnar-skim'


def test_skim_refuses_enumerated_replica_populations():
    from types import SimpleNamespace
    step = SimpleNamespace(kind='efficiency', spec={'application': 'enumerate'})
    with pytest.raises(ValueError, match='enumerated'):
        skim.compile_skim(recipe()['skim'], descriptor(), {'passing': []}, [step])


def test_partial_merge_retains_skim_custody_through_aggregate_merges(tmp_path):
    path, _ = population(tmp_path)
    one, _ = analyse(path, recipe(), tmp_path, output='one', stop=3)
    two, _ = analyse(path, recipe(), tmp_path, output='two', start=3)
    merged = engine.merge([one, two])
    assert engine.merge([merged])['skim_manifest'] == merged['skim_manifest']


def test_forecast_refuses_tampered_pilot_receipt(tmp_path):
    pilot_ledger(tmp_path)
    (tmp_path / 'receipt-0.json').write_text('{}')
    with pytest.raises(ValueError, match='receipt changed'):
        pe.forecast(tmp_path)


def test_event_number_is_preserved_separately_from_source_entry(tmp_path):
    path, _ = population(tmp_path)
    descriptor_doc = descriptor().doc
    descriptor_doc['event']['number'] = descriptor_doc['event'].pop('identifier')
    d = formats.load_descriptor(descriptor_doc)
    doc = recipe(branches=['magnitude', 'angle', 'generator', 'factor'])
    plan = compile_recipe(doc, d, tmp_path)
    part = engine.analyse({'inputs': [{'path': str(path)}], 'chunk_size': 2}, plan, skim_dir=tmp_path / 'output')
    custody = skim.validate_partition(part['skims'][0])
    data = ak.concatenate([ak.Array(c) for c in skim._data_chunks(custody, list(skim.RESERVED), 2)])
    assert data.ravel_event_number.tolist() == [102, 103, 104, 105, 106]
    assert data.ravel_source_entry.tolist() == [1, 2, 3, 4, 5]
    assert 'identifier' not in custody['branches']
    replay = engine.analyse({'inputs': [{'path': part['skims'][0]['path']}], 'chunk_size': 2}, plan,
                            skim_dir=tmp_path / 'replay')
    record = skim.validate_partition(replay['skims'][0])
    data = ak.concatenate([ak.Array(c) for c in skim._data_chunks(record, list(skim.RESERVED), 2)])
    assert data.ravel_event_number.tolist() == [102, 103, 104, 105, 106]


def test_skim_normalization_requires_original_population_denominator(tmp_path):
    path, _ = population(tmp_path)
    part, _ = analyse(path, recipe(), tmp_path)
    replay, plan = analyse(Path(part['skims'][0]['path']), recipe(output=False), tmp_path)
    norm = {'mode': 'cross-section', 'cross_section_pb': 1.0, 'cross_section_source': 'synthetic input',
            'luminosity_ifb': 1.0, 'luminosity_source': 'synthetic input', 'sum_of_weights': 'all-input-events'}
    with pytest.raises(ValueError, match='original-population denominator'):
        engine.resolve_normalization(norm, replay, plan)
    norm.update(sum_of_weights=5.0, sum_of_weights_source='synthetic full original generator sum')
    assert engine.resolve_normalization(norm, replay, plan)['scale'] == 200.0
