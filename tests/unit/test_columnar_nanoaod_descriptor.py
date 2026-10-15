"""Fictional flat trees, fixed-array jets and public record contracts."""
import copy
import hashlib
import json

import awkward as ak
import numpy as np
import pytest
import uproot

from ravel.physics.columnar import engine, formats
from ravel.physics.columnar.recipe import compile_recipe
from ravel.physics import root_stream_core as core, yield_hub
from root_stream_fixture import population, put


def flat_file(path):
    columns = {}
    for name in ('Electron', 'Muon', 'Photon', 'Jet', 'IsoTrack'):
        counts = [1, 0, 1]
        columns['n' + name] = np.array(counts, dtype='i4')
        for field, values in {'pt': [40., 60.], 'eta': [0., 0.], 'phi': [0., 0.],
                              'mass': [1., 2.], 'charge': [-1, 1], 'pdgId': [211, -211],
                              'pfRelIso03_all': [.1, .2], 'pfRelIso04_all': [.1, .2],
                              'btagDeepFlavB': [.7, .2]}.items():
            columns[name + '_' + field] = ak.unflatten(np.asarray(values), counts)
    columns.update(MET_pt=np.array([80., 30., 120.]), MET_phi=np.zeros(3),
                   genWeight=np.array([2., -1., 3.]), run=np.array([1, 1, 2], dtype='u4'),
                   luminosityBlock=np.array([3, 3, 4], dtype='u4'),
                   event=np.array([2**60 + 1, 2**60 + 2, 2**60 + 3], dtype='u8'))
    with uproot.recreate(path) as output:
        output.mktree('Events', {k: v.type if isinstance(v, ak.Array) else v.dtype for k, v in columns.items()})
        output['Events'].extend(columns)
    return path


def selection(collection='Jet', cut='btag > 0.5'):
    return {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'ANA-0001',
            'weights': {'generator': 'weight', 'factors': []},
            'objects': [{'name': 'objects', 'from': collection, 'select': cut}],
            'observables': [{'name': 'n', 'op': 'count', 'collection': 'objects'},
                            {'name': 'met', 'op': 'met', 'unit': 'GeV'}],
            'regions': [{'name': 'inclusive', 'cuts': []},
                        {'name': 'selected', 'cuts': [{'name': 'tag and recoil', 'expr': 'n > 0 and met > 50'}]}],
            'histograms': []}


def test_flat_tree_refuses_wrong_descriptor_and_runs_two_regions(tmp_path):
    path = flat_file(tmp_path / 'flat.root')
    with pytest.raises(ValueError, match="no tree 'Delphes'"):
        formats.load_descriptor('delphes').check_file(path)
    descriptor = formats.load_descriptor('nanoaod')
    descriptor.check_file(path)
    plan = compile_recipe(selection(), descriptor, tmp_path)
    result = engine.analyse({'inputs': [{'path': str(path), 'file_index': 0}], 'chunk_size': 2}, plan)
    flows = result['variations']['nominal']['cutflows']
    assert flows['inclusive'][-1][:3] == pytest.approx([3, 4, 14])
    assert flows['selected'][-1][:3] == pytest.approx([1, 2, 4])
    # A changed supplied working point changes selection without product edits.
    plan = compile_recipe(selection(cut='btag > 0.1'), descriptor, tmp_path)
    result = engine.analyse({'inputs': [{'path': str(path), 'file_index': 0}], 'chunk_size': 1}, plan)
    assert result['variations']['nominal']['cutflows']['selected'][-1][:3] == pytest.approx([2, 5, 13])


def test_event_identity_preserves_uint64_and_collection_counts(tmp_path):
    descriptor = formats.load_descriptor('nanoaod')
    path = flat_file(tmp_path / 'flat.root')
    chunks = list(descriptor.read(path, collections=['Electron'], event_fields=['run', 'lumi', 'number'], step=3))
    view = descriptor.view(chunks[0])
    assert view.event['number'].dtype == np.dtype('uint64')
    assert view.event['number'].tolist() == [2**60 + 1, 2**60 + 2, 2**60 + 3]
    chunks[0].arrays['nElectron'] = ak.Array([2, 0, 1])
    with pytest.raises(ValueError, match='count'):
        descriptor.view(chunks[0])


def jet_arrays(*, include=True, trimmed=False):
    data = {'MissingET.MET': ak.Array([[0.], [0.]]), 'MissingET.Phi': ak.Array([[0.], [0.]]),
            'Event.Weight': ak.Array([[1.], [1.]])}
    if include:
        for field, values in {'PT': [300., 400.], 'Eta': [0., 0.], 'Phi': [0., 0.], 'Mass': [90., 100.]}.items():
            data['FatJet.' + field] = ak.unflatten(np.asarray(values, dtype='f4'), [1, 1])
        data['FatJet.Tau[5]'] = ak.unflatten(np.array([[.5, .2, .1, .05, .02], [.8, .4, .2, .1, .05]], dtype='f4'), [1, 1])
        # Four-vectors are stored unsplit: one record branch, with a fixed
        # array of five records for the trimmed jet and its subjets.
        vectors = [{'fP': {'fX': 30., 'fY': 0., 'fZ': 0.}, 'fE': 50.}, {'fP': {'fX': 0., 'fY': 0., 'fZ': 0.}, 'fE': 60.}]
        subjet = {'fP': {'fX': 1., 'fY': 0., 'fZ': 0.}, 'fE': 2.}
        data['FatJet.SoftDroppedJet'] = ak.unflatten(ak.Array(vectors), [1, 1])
        if trimmed:
            data['FatJet.TrimmedP4[5]'] = ak.unflatten(ak.to_regular(ak.Array([[v] + [subjet] * 4 for v in vectors]), axis=1), [1, 1])
    return data


@pytest.fixture
def jet_file(monkeypatch):
    # uproot 5.3's writer cannot round-trip a jagged fixed-array TLeaf.
    # Exercise the TBranch reader protocol with independent arrays instead;
    # real C++ streamer qualification uses a supplied file in the job record.
    from types import SimpleNamespace
    opened = uproot.open
    files = {}

    class Tree:
        num_entries = 2

        def __init__(self, data):
            self.data = data

        def values(self, recursive=True):
            def typename(name):
                if 'SoftDroppedJet' in name or 'TrimmedP4' in name:
                    return 'TLorentzVector[][5]' if '[5]' in name else 'TLorentzVector[]'
                return 'float[][5]' if '[5]' in name else 'double[]'
            return [SimpleNamespace(name=k, typename=typename(k)) for k in self.data]

        def iterate(self, *, filter_name, step_size, entry_start, entry_stop, library, report):
            for start in range(entry_start, entry_stop, step_size):
                stop = min(start + step_size, entry_stop)
                yield ak.zip({k: v[start:stop] for k, v in self.data.items() if filter_name(k)}, depth_limit=1), SimpleNamespace(tree_entry_start=start, tree_entry_stop=stop)

    class File:
        def __init__(self, data):
            self.tree = Tree(data)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __getitem__(self, name):
            if name != 'Delphes':
                raise KeyError(name)
            return self.tree

    def create(path, **options):
        path.write_bytes(b'synthetic TBranch reader protocol fixture')
        files[str(path)] = jet_arrays(**options)
        return path

    monkeypatch.setattr(uproot, 'open', lambda path: File(files[str(path)]) if str(path) in files else opened(path))
    return create


def test_missing_fatjet_is_refused_and_substructure_decoded(tmp_path, jet_file):
    descriptor = formats.load_descriptor('delphes')
    missing = jet_file(tmp_path / 'missing.root', include=False)
    with pytest.raises(ValueError, match='FatJet.*branch'):
        descriptor.check_file(missing, collections=['FatJet'], event_fields=['weight'])
    path = jet_file(tmp_path / 'jets.root')
    descriptor.check_file(path, collections=['FatJet'], event_fields=['weight'])
    chunk = next(descriptor.read(path, collections=['FatJet'], event_fields=['weight'], step=2))
    jets = descriptor.view(chunk).collections['FatJet']
    assert ak.to_list(jets.softdrop_mass) == [[40.], [60.]]
    np.testing.assert_allclose(ak.flatten(jets.tau21), [.4, .5])
    np.testing.assert_allclose(ak.flatten(jets.tau32), [.5, .5])
    assert 'trimmed_mass' not in jets.fields
    plan = compile_recipe(selection('FatJet', 'softdrop_mass > 45 and tau21 < 0.6'), descriptor, tmp_path)
    result = engine.analyse({'inputs': [{'path': str(path), 'file_index': 0}], 'chunk_size': 1}, plan)
    assert result['variations']['nominal']['cutflows']['selected'][0][:3] == pytest.approx([2, 2, 2])


def test_requested_missing_grooming_field_refused_and_present_array_read(tmp_path, jet_file):
    descriptor = formats.load_descriptor('delphes')
    doc = selection('FatJet', 'trimmed_mass > 20')
    plan = compile_recipe(doc, descriptor, tmp_path)
    with pytest.raises(ValueError, match='trimmed_mass.*branch'):
        plan.descriptor.check_file(jet_file(tmp_path / 'missing.root'), collections=['FatJet'], event_fields=['weight'])
    path = jet_file(tmp_path / 'present.root', trimmed=True)
    plan.descriptor.check_file(path, collections=['FatJet'], event_fields=['weight'])
    chunk = next(plan.descriptor.read(path, collections=['FatJet'], event_fields=['weight'], step=2))
    assert ak.to_list(plan.descriptor.view(chunk).collections['FatJet'].trimmed_mass) == [[40.], [60.]]


def test_record_member_needs_a_record_branch_and_a_present_member(tmp_path, jet_file):
    def descriptor(field):
        return formats.load_descriptor({
            'schema_version': 1, 'kind': 'columnar-format', 'name': 'members', 'format': 'root', 'source': 'synthetic',
            'tree': 'Delphes', 'collections': {'FatJet': {'fields': {
                'pt': 'FatJet.PT', 'eta': 'FatJet.Eta', 'phi': 'FatJet.Phi', 'mass': 'FatJet.Mass', 'energy': field}}},
            'event': {'weight': {'branch': 'Event.Weight', 'reduce': 'first'}}})
    path = jet_file(tmp_path / 'jets.root')
    good = descriptor({'branch': 'FatJet.SoftDroppedJet', 'member': ['fE']})
    good.check_file(path, collections=['FatJet'], event_fields=['weight'])
    chunk = next(good.read(path, collections=['FatJet'], event_fields=['weight'], step=2))
    assert ak.to_list(good.view(chunk).collections['FatJet'].energy) == [[50.], [60.]]
    # A whole record is not a numeric field, and a number has no members.
    with pytest.raises(ValueError, match='non-numeric'):
        descriptor('FatJet.SoftDroppedJet').check_file(path, collections=['FatJet'], event_fields=['weight'])
    with pytest.raises(ValueError, match='member'):
        descriptor({'branch': 'FatJet.PT', 'member': ['fE']}).check_file(path, collections=['FatJet'], event_fields=['weight'])
    absent = descriptor({'branch': 'FatJet.SoftDroppedJet', 'member': ['fT']})
    absent.check_file(path, collections=['FatJet'], event_fields=['weight'])
    chunk = next(absent.read(path, collections=['FatJet'], event_fields=['weight'], step=2))
    with pytest.raises(ValueError, match="member 'fT'"):
        absent.view(chunk)
    for bad in ([], 'fE', ['fE', 3], ['not valid']):
        with pytest.raises(ValueError, match='member'):
            descriptor({'branch': 'FatJet.SoftDroppedJet', 'member': bad})


def record_dataset(tmp_path):
    ds, analysis, cfg, _, _ = population(tmp_path)
    ds['samples'] = ds['samples'][:1]
    sample = ds['samples'][0]
    sample.pop('dsid')
    sample.update(id_scheme='record', record_id='REC-0001', authority='https://example.invalid/records/REC-0001')
    member = sample['members'][0]
    member.pop('did')
    member['guid'] = member['checksum']['algorithm'] + ':' + member['checksum']['value']
    original = {'schema_version': 1, 'sample_id': sample['id'], **{k: sample[k] for k in ('id_scheme', 'record_id', 'authority')},
                'members': [{k: member[k] for k in ('guid', 'entries')}]}
    sample['normalization']['original_population'] = put(tmp_path, 'original-record.json', original)
    source = {'schema_version': 1, 'sample_id': sample['id'], **{k: sample[k] for k in ('id_scheme', 'record_id', 'authority')},
              'original_population_sha256': sample['normalization']['original_population']['sha256'],
              **{k: v for k, v in sample['normalization'].items() if k not in ('source', 'original_population')}}
    sample['normalization']['source'] = put(tmp_path, 'record-normalization.json', source)
    ds['membership_authority'] = put(tmp_path, 'record-membership.json', {'schema_version': 1, 'samples': ds['samples']})
    analysis['blinding'] = None
    cfg['bundle']['blind_entry'] = None
    return ds, analysis, cfg


def test_record_missing_authority_refused(tmp_path):
    ds, _, _ = record_dataset(tmp_path)
    ds['samples'][0].pop('authority')
    with pytest.raises(ValueError, match='authority'):
        core.dataset(ds)


def test_record_local_dataset_explicit_normalization(tmp_path):
    ds, _, _ = record_dataset(tmp_path)
    path = flat_file(tmp_path / 'flat.root')
    sample = ds['samples'][0]; member = sample['members'][0]
    raw = path.read_bytes()
    member.update(uri=path.as_uri(), tree='Events', entries=3, size_bytes=len(raw))
    member['checksum']['value'] = hashlib.sha256(raw).hexdigest()
    member['guid'] = 'sha256:' + member['checksum']['value']
    original = {'schema_version': 1, 'sample_id': sample['id'], **{k: sample[k] for k in ('id_scheme', 'record_id', 'authority')},
                'members': [{k: member[k] for k in ('guid', 'entries')}]}
    n = sample['normalization']
    n['original_population'] = put(tmp_path, 'original-flat.json', original)
    source = json.loads(open(n['source']['path']).read())
    source['original_population_sha256'] = n['original_population']['sha256']
    n['source'] = put(tmp_path, 'flat-normalization.json', source)
    ds['membership_authority'] = put(tmp_path, 'flat-membership.json', {'schema_version': 1, 'samples': ds['samples']})
    ds_pin = put(tmp_path, 'flat-dataset.json', ds)
    loaded, _ = yield_hub.load_dataset(ds_pin, tmp_path)
    assert loaded == ds
    plan = compile_recipe(selection(), formats.load_descriptor('nanoaod'), tmp_path)
    partial = engine.analyse({'inputs': [{'path': str(path), 'file_index': 0}], 'chunk_size': 2}, plan)
    result = engine.finalize(partial, plan, yield_hub.dataset_normalization(sample), out_dir=tmp_path / 'out')
    assert result['cutflows']['nominal'][1]['cuts'][-1]['yield'] == pytest.approx(400.)


def test_dsid_receipt_bytes_unchanged(tmp_path):
    from root_stream_fixture import accumulate
    ds, analysis, cfg, _, _ = population(tmp_path)
    assert core.dataset(ds) == ds
    receipt = accumulate(ds, analysis, cfg['limits'], 2)
    # Pin paths are supplied by the fixture; compare portable normalization values.
    for sample in receipt['samples']:
        for name in ('source', 'original_population'):
            if sample['normalization'] is not None:
                sample['normalization'][name].update(path=name + '.json', sha256='0' * 64, size=0)
    assert hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == '56da0826074f8504c02ccb855a0036926962901b48f929c76219177fe5987952'


def test_record_adapter_context_worker_receipt_and_identity_refusal(tmp_path):
    from ravel.physics import root_stream as adapter, root_stream_worker as worker
    ds, analysis, cfg = record_dataset(tmp_path)
    sample = ds['samples'][0]; member = sample['members'][0]
    data = {name: np.asarray(values, dtype='f8') for name, values in
            {'w': [2., -1., 3.], 'sf': [.5, 2., 1.], 'variation': [1., 1., 1.], 'x': [.5, 2.5, .5]}.items()}
    path = tmp_path / 'local.root'
    with uproot.recreate(path) as output:
        output.mktree('mini', {k: v.dtype for k, v in data.items()})
        output['mini'].extend(data)
    raw = path.read_bytes()
    member.update(uri=path.as_uri(), entries=3, size_bytes=len(raw))
    member['checksum']['value'] = hashlib.sha256(raw).hexdigest()
    member['guid'] = 'sha256:' + member['checksum']['value']
    identity = core.sample_identity(sample)
    n = sample['normalization']
    n['original_population'] = put(tmp_path, 'stream-population.json',
        {'schema_version': 1, 'sample_id': sample['id'], **identity, 'members': [core.member_exposure(member)]})
    source = {'schema_version': 1, 'sample_id': sample['id'], **identity,
              'original_population_sha256': n['original_population']['sha256'],
              **{k: v for k, v in n.items() if k not in ('source', 'original_population')}}
    n['source'] = put(tmp_path, 'stream-normalization.json', source)
    ds['membership_authority'] = put(tmp_path, 'stream-members.json', {'schema_version': 1, 'samples': ds['samples']})
    cfg['dataset'] = put(tmp_path, 'stream-dataset.json', ds)
    cfg['analysis'] = put(tmp_path, 'stream-analysis.json', analysis)
    task = {'config': put(tmp_path, 'stream-config.json', cfg)}
    context = adapter.context(task, tmp_path)
    assert context['sample_ids'] == [{'id': sample['id'], 'kind': sample['kind'], **identity}]
    result = worker.stream(core.dataset(ds), core.analysis(analysis, ds), cfg, tmp_path)
    adapter.validate_delivery(result, ds, analysis, cfg['limits'])
    receipt = result['delivery']['samples'][0]
    assert {k: receipt[k] for k in identity} == identity
    assert receipt['quantities']['regions']['values']['nominal'] == pytest.approx([800., 0., -400.])
    altered = copy.deepcopy(result)
    altered['delivery']['samples'][0]['authority'] = 'https://example.invalid/other'
    with pytest.raises(ValueError, match='sample normalization/weight law differs'):
        adapter.validate_delivery(altered, ds, analysis, cfg['limits'])
    source['authority'] = 'https://example.invalid/other'
    with pytest.raises(ValueError, match='identity/authority differs'):
        core.normalization_records(sample, json.loads(open(n['original_population']['path']).read()), source)


def test_record_columnar_mode_runs_local_member_and_preserves_identity(tmp_path):
    # Reuse the normalized local fixture, then exercise the public mode seam.
    test_record_local_dataset_explicit_normalization(tmp_path)
    from ravel.physics import columnar_analysis
    recipe = tmp_path / 'recipe.json'
    recipe.write_text(json.dumps(selection()))
    dataset_pin = json.loads((tmp_path / 'flat-dataset.json').read_text())
    task = {'recipe': str(recipe), 'format': 'nanoaod',
            'inputs': {'dataset': put(tmp_path, 'mode-dataset.json', dataset_pin)}, 'normalization': {'mode': 'dataset'}}
    result = columnar_analysis.run(task, tmp_path, tmp_path / 'mode-output')
    assert result['samples'][0]['record_id'] == 'REC-0001'
    assert result['samples'][0]['authority'] == 'https://example.invalid/records/REC-0001'
    assert 'dsid' not in result['samples'][0]


@pytest.mark.parametrize('authority', ['', 'relative/page', 'file:///local', 'https://user:pass@example.invalid/page', 'https://example.invalid/page?token=x'])
def test_record_invalid_authority_refused(tmp_path, authority):
    ds, _, _ = record_dataset(tmp_path)
    ds['samples'][0]['authority'] = authority
    with pytest.raises(ValueError, match='authority'):
        core.dataset(ds)


@pytest.mark.parametrize('authority', ['doi:10.0000/REC-0001', '10.0000/REC-0001', 'https://doi.org/10.0000/REC-0001'])
def test_record_doi_authority_is_retained(tmp_path, authority):
    ds, _, _ = record_dataset(tmp_path)
    ds['samples'][0]['authority'] = authority
    assert core.dataset(ds)['samples'][0]['authority'] == authority


def test_record_does_not_inherit_normalization_or_aliased_checksum(tmp_path):
    ds, _, _ = record_dataset(tmp_path)
    altered = copy.deepcopy(ds)
    altered['samples'][0]['normalization'].pop('cross_section_pb')
    with pytest.raises(ValueError, match='normalization'):
        core.dataset(altered)
    ds['samples'][0]['members'][0]['guid'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError, match='checksum identity'):
        core.dataset(ds)


def test_subjettiness_zero_denominator_and_missing_fixed_slot_refused(jet_file, tmp_path):
    descriptor = formats.load_descriptor('delphes')
    path = jet_file(tmp_path / 'jets.root')
    chunk = next(descriptor.read(path, collections=['FatJet'], event_fields=['weight'], step=2))
    chunk.arrays['FatJet.Tau[5]'] = ak.unflatten(np.array([[0., .2, .1, .05, .02], [.8, .4, .2, .1, .05]]), [1, 1])
    jets = descriptor.view(chunk).collections['FatJet']
    assert np.isnan(ak.to_list(jets.tau21)[0][0])
    chunk.arrays['FatJet.Tau[5]'] = ak.unflatten(np.ones((2, 2)), [1, 1])
    with pytest.raises(ValueError, match='fixed array index'):
        descriptor.view(chunk)


def test_public_member_source_guid_does_not_need_rucio_did(tmp_path):
    ds, _, _ = record_dataset(tmp_path)
    ds['samples'][0]['members'][0]['guid'] = 'guid-FILE-0001'
    assert core.dataset(ds) == ds
