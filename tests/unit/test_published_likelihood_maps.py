"""Shipped published workspaces and the explicit channel maps that join native yields to them."""
import copy
import gzip
import hashlib
import json
import sys
from types import SimpleNamespace

import jsonpatch
import numpy as np
import pyhf
import pytest

from ravel.paths import package_data_path
from ravel.physics import pyhf_exclude
from ravel.physics import sa2json_native as converter

IDS = ['susy-2018-06-three-lepton', 'susy-2018-16-compressed-full',
       'susy-2018-16-compressed-sr-only-diagnostic']
UNCOMPRESSED_2018_16 = 'f609ddbe3a6f43f01f3ec2725c8244009a750fba349f3698e292a1deaa73b282'


def registry():
    return converter.published_likelihoods()


def likelihood(identity):
    return next(row for row in registry()['likelihoods'] if row['id'] == identity)


def load_workspace(row):
    raw = package_data_path(*row['workspace']['file'].split('/')).read_bytes()
    if row['workspace']['compression'] == 'gzip':
        raw = gzip.decompress(raw)
    return raw, json.loads(raw)


@pytest.fixture(scope='module')
def spec6():
    return load_workspace(likelihood('susy-2018-06-three-lepton'))[1]


@pytest.fixture(scope='module')
def spec16():
    return load_workspace(likelihood('susy-2018-16-compressed'))[1]


def synthetic_yields(mapping, weight=1e-3):
    """One event per mapped channel: every selected event lies in exactly one model channel."""
    names = [name for name, entry in mapping.items() if entry is not None]
    n = len(names)
    branches = {'isee': np.zeros(n), 'ismm': np.zeros(n)}
    for i, name in enumerate(names):
        entry = mapping[name]
        branches.setdefault(entry['region'], np.zeros(n))[i] = weight*(i + 1)
        if entry.get('flavour'):
            branches[entry['flavour']][i] = 1.0
    return branches


def test_registry_pins_every_file_and_channel_set():
    document = registry()
    assert document['kind'] == 'published-likelihood-registry' and document['schema_version'] == 1
    seen = []
    for row in document['likelihoods']:
        raw, spec = load_workspace(row)
        assert hashlib.sha256(raw).hexdigest() == row['workspace']['sha256']
        assert len(raw) == row['workspace']['bytes']
        assert [c['name'] for c in spec['channels']] == row['workspace']['channels']
        assert converter.signal_poi(spec) == row['workspace']['poi'] == 'mu_SIG'
        if row['workspace']['compression'] == 'gzip':
            stored = package_data_path(*row['workspace']['file'].split('/')).read_bytes()
            assert hashlib.sha256(stored).hexdigest() == row['workspace']['compressed_sha256']
        for patch in row['signal_patches']:
            body = package_data_path(*('fixtures/' + patch['file'].removeprefix('fixtures/')).split('/')).read_bytes()
            assert hashlib.sha256(body).hexdigest() == patch['sha256']
        for entry in row['channel_maps']:
            mapping, record = converter.shipped_channel_map(entry['id'])
            assert record['sha256'] == entry['sha256'] and record['published_likelihood'] == row['id']
            assert converter.validate_channel_map(mapping, spec) == mapping
            seen.append(entry['id'])
    assert seen == IDS
    assert likelihood('susy-2018-16-compressed')['workspace']['sha256'] == UNCOMPRESSED_2018_16


def test_each_publication_names_its_source():
    for row in registry()['likelihoods']:
        publication = row['publication']
        assert publication['analysis_id'].startswith('ATLAS-SUSY-')
        assert publication['hepdata_url'].startswith('https://www.hepdata.net/record/ins')
        assert row['workspace']['license'] == 'CC BY 4.0' and row['workspace']['acquisition']
        for entry in row['channel_maps']:
            assert entry['region_source'] and entry['acceptance_validated'] is False


def test_the_two_signal_models_differ_only_in_the_control_regions(spec16):
    full, _ = converter.shipped_channel_map('susy-2018-16-compressed-full')
    diagnostic, record = converter.shipped_channel_map('susy-2018-16-compressed-sr-only-diagnostic')
    assert list(full) == [c['name'] for c in spec16['channels']] == list(diagnostic)
    controls = [name for name in full if name.startswith('CR')]
    assert len(controls) == 6 and len(full) == 38
    assert all(diagnostic[name] is None for name in controls)
    assert {k: v for k, v in full.items() if k not in controls} == {k: v for k, v in diagnostic.items() if k not in controls}
    assert all(full[name] == {'region': f"CR_S_{name[2:name.index('_')]}_{'high' if 'hghmet' in name else 'low'}"}
               for name in controls)
    signal = full['SRmm_eMT2c_lowmet_V2_cuts']
    assert signal == {'region': 'SR_S_low_eMT2c', 'flavour': 'ismm'}
    assert record['omissions'] == ['signal contamination of the six control regions']


def test_compressed_map_is_selected_by_exact_channel_set_never_by_pattern(spec16):
    full = converter.compressed_channel_map(spec16, 'full')
    assert full == converter.shipped_channel_map('susy-2018-16-compressed-full')[0]
    diagnostic = converter.compressed_channel_map(spec16, 'sr-only-diagnostic')
    assert sum(entry is None for entry in diagnostic.values()) == 6
    with pytest.raises(converter.MissingChannelMap, match='channel map'):
        converter.compressed_channel_map(spec16)
    with pytest.raises(ValueError, match='unknown compressed'):
        converter.compressed_channel_map(spec16, 'partial')
    # A workspace with one channel renamed or removed is not the published one.
    renamed = copy.deepcopy(spec16)
    renamed['channels'][0]['name'] = 'CRVV_MT2_hghmet_cuts_renamed'
    with pytest.raises(converter.MissingChannelMap):
        converter.compressed_channel_map(renamed, 'full')
    short = copy.deepcopy(spec16)
    short['channels'].pop()
    with pytest.raises(converter.MissingChannelMap):
        converter.compressed_channel_map(short, 'full')
    with pytest.raises(converter.MissingChannelMap):
        converter.compressed_channel_map({'channels': []}, 'full')


def test_json_to_sa_resolves_only_through_a_declared_map():
    with pytest.raises(converter.MissingChannelMap, match='channel map'):
        converter.JSONtoSA('SRlow_cuts', 'any_workspace')
    assert converter.JSONtoSA('SRlow_cuts', None, channel_map='susy-2018-06-three-lepton') == 'SRlow'
    assert converter.JSONtoSA('CRVV_MT2_lowmet_cuts', None,
                              channel_map='susy-2018-16-compressed-full') == 'CR_S_VV_low'
    assert converter.JSONtoSA('CRVV_MT2_lowmet_cuts', None,
                              channel_map='susy-2018-16-compressed-sr-only-diagnostic') is None
    assert converter.JSONtoSA('x', None, channel_map={'x': {'region': 'R'}}) == 'R'
    with pytest.raises(converter.MissingChannelMap, match='absent'):
        converter.JSONtoSA('SRlow_cuts', None, channel_map='susy-2018-16-compressed-full')
    with pytest.raises(converter.MissingChannelMap, match='no shipped'):
        converter.shipped_channel_map('no-such-map')


def test_three_lepton_patch_from_a_synthetic_yield_file_validates(spec6):
    mapping, _ = converter.shipped_channel_map('susy-2018-06-three-lepton')
    branches = {'SRlow': np.array([0.002, 0.0, 0.0, 0.0]), 'SRISR': np.array([0.0, 0.003, 0.0, 0.0]),
                'CRlow': np.array([0.0, 0.0, 0.001, 0.0]), 'CRISR': np.array([0.0, 0.0, 0.0, 0.004])}
    patch, metadata = converter.build_signal_patch(spec6, [branches], name='native_signal', mapping=mapping,
                                                  lumi=139000., mc_stat='shapesys')
    patched = jsonpatch.apply_patch(spec6, patch)
    pyhf.schema.validate(patched, 'workspace.json')
    model = pyhf.Workspace(patched).model()
    assert model.config.poi_name == 'mu_SIG'
    by_channel = {r['channel']: r for r in metadata['channels']}
    assert by_channel['SRlow_cuts']['nominal_yield'] == pytest.approx(0.002*139000.)
    assert by_channel['CRISR_cuts']['nominal_yield'] == pytest.approx(0.004*139000.)
    assert all(r['status'] == 'nominal-signal' and r['mapping'] == mapping[r['channel']] for r in by_channel.values())
    for channel in patched['channels']:
        assert [s['name'] for s in channel['samples']].count('native_signal') == 1


def test_compressed_patches_validate_for_both_signal_models(spec16):
    full, _ = converter.shipped_channel_map('susy-2018-16-compressed-full')
    branches = synthetic_yields(full)
    patch, metadata = converter.build_signal_patch(spec16, [branches], name='native_signal', mapping=full,
                                                  lumi=139000., mc_stat='shapesys')
    patched = jsonpatch.apply_patch(spec16, patch)
    pyhf.schema.validate(patched, 'workspace.json')
    pyhf.Workspace(patched).model()
    assert [r['channel'] for r in metadata['channels']] == [c['name'] for c in spec16['channels']]
    assert {r['status'] for r in metadata['channels']} == {'nominal-signal'}
    # The flavour mask keeps an ee event out of the mm channel that shares its region.
    rows = {r['channel']: r for r in metadata['channels']}
    assert rows['SRee_eMT2a_hghmet_cuts']['nonzero_weights'] == 1 == rows['SRmm_eMT2a_hghmet_cuts']['nonzero_weights']

    diagnostic, _ = converter.shipped_channel_map('susy-2018-16-compressed-sr-only-diagnostic')
    patch, metadata = converter.build_signal_patch(spec16, [synthetic_yields(diagnostic)], name='native_signal',
                                                  mapping=diagnostic, lumi=139000., mc_stat='none')
    pyhf.Workspace(jsonpatch.apply_patch(spec16, patch)).model()
    omitted = [r['channel'] for r in metadata['channels'] if r['status'] == 'declared-signal-omission']
    assert len(omitted) == 6 and all(name.startswith('CR') for name in omitted)


def test_a_yield_file_missing_a_mapped_branch_is_an_error_not_a_zero(spec16):
    full, _ = converter.shipped_channel_map('susy-2018-16-compressed-full')
    branches = synthetic_yields(full)
    del branches['CR_S_top_low']
    with pytest.raises(ValueError, match='missing or invalid SR branch: CR_S_top_low'):
        converter.build_signal_patch(spec16, [branches], name='native_signal', mapping=full,
                                     lumi=139000., mc_stat='none')


def test_cli_with_a_shipped_map_records_its_identity(tmp_path, monkeypatch, spec16):
    root = tmp_path/'input.root'
    root.write_bytes(b'fixture ROOT handled by read-only fake')
    bkg = tmp_path/'background.json'
    bkg.write_bytes(load_workspace(likelihood('susy-2018-16-compressed'))[0])
    full, _ = converter.shipped_channel_map('susy-2018-16-compressed-full')
    values = synthetic_yields(full)

    class File:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def __getitem__(self, key): return SimpleNamespace(arrays=lambda: values)
    monkeypatch.setitem(sys.modules, 'uproot', SimpleNamespace(open=lambda path: File()))
    patch, metadata = tmp_path/'patch.json', tmp_path/'signal_model.json'
    argv = ['-i', str(root), '-b', str(bkg), '-o', str(patch), '-n', 'signal', '-l', '139000',
            '--mc-stat', 'shapesys', '--signal-metadata', str(metadata)]
    converter.main(argv + ['--shipped-channel-map', 'susy-2018-16-compressed-full'])
    record = json.loads(metadata.read_text())
    assert record['published_likelihood']['id'] == 'susy-2018-16-compressed'
    assert record['published_likelihood']['workspace_bytes_match_registry'] is True
    assert record['published_likelihood']['omissions'] == []
    assert record['channel_map']['sha256'] == likelihood('susy-2018-16-compressed')['channel_maps'][0]['sha256']
    assert record['patch']['sha256'] == hashlib.sha256(patch.read_bytes()).hexdigest()
    pyhf.Workspace(jsonpatch.apply_patch(spec16, json.loads(patch.read_text()))).model()
    with pytest.raises(SystemExit):
        converter.main(argv + ['--shipped-channel-map', 'susy-2018-16-compressed-full',
                               '--channel-map', str(tmp_path/'x.json')])
    with pytest.raises(SystemExit):
        converter.main(argv + ['--shipped-channel-map', 'susy-2018-16-compressed-full',
                               '--compressed-signal-model', 'sr-only-diagnostic', '-c'])


@pytest.mark.parametrize('prior_optimizer', ['default', 'guarded'])
def test_the_shipped_three_lepton_reference_fit_matches_its_published_numbers(prior_optimizer):
    fixture = package_data_path('fixtures', 'susy-2018-06')
    reference = json.loads((fixture/'reference_fit.json').read_text())
    reference = {**reference, 'background': str(fixture/reference['background']),
                 'patch': str(fixture/reference['patch'])}
    original_backend = pyhf.get_backend()
    optimizer = (pyhf.optimize.scipy_optimizer() if prior_optimizer == 'default' else
                 pyhf_exclude.robust_optimizer(maxiter=200000))
    try:
        pyhf.set_backend('numpy', optimizer, precision='64b')
        caller_backend = pyhf.get_backend()
        result = pyhf_exclude.check_fit_reference(reference)
        assert pyhf.get_backend() == caller_backend
    finally:
        pyhf.set_backend(*original_backend)
    assert result['status'] == 'passed', result['actual']
    assert result['actual']['twice_nll'] == pytest.approx(271.786, abs=0.1)
    assert result['actual']['mu_hat'] == pytest.approx(0.2446, abs=0.02)
    assert [i['sha256'] for i in result['inputs']] == [
        likelihood('susy-2018-06-three-lepton')['workspace']['sha256'],
        likelihood('susy-2018-06-three-lepton')['signal_patches'][0]['sha256']]
