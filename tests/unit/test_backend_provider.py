"""Portable source controls; no upstream imports or scientific execution."""
import synthetic_identifiers as syn
import ast
import base64
import configparser
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import zlib

import pytest

from ravel.physics import backend_provider as m


def put(root, path, text):
    p = root / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); return p


@pytest.fixture
def catalogue(tmp_path):
    root = tmp_path / 'source'
    for path in m.CM_ENGINE:
        put(root, path, '# engineering fixture\n')
    put(root, 'tools/python/info.py', 'class Info:\n    @classmethod\n    def init(cls):\n        cls.analysis_groups = {"ATLAS_13TeV"}\n')
    put(root, 'data/analysis_info/ATLAS_13TeV_analyses.txt', '#disabled 8\natlas_0000_00032 2 fixture\n')
    meta = {'analysis': 'atlas_0000_00032', 'experiment': 'atlas13tev', 'ecm': '13',
            'lumi': '139', 'signal_regions': ['SR1', 'SR2'], 'expectation_known': 'y',
            'likelihoods': 'y', 'mb_signal_regions': {'pair': ['SR1', 'SR2']}}
    put(root, 'data/analysis_info/ATLAS_13TeV/atlas_0000_00032_var.j', json.dumps(meta))
    for path in ['data/analysis_info/ATLAS_13TeV/atlas_0000_00032_ref.dat',
                 'tools/analysis/src/analyses/ATLAS_13TeV/atlas_0000_00032.cc',
                 'tools/analysis/include/analyses/ATLAS_13TeV/atlas_0000_00032.h',
                 'data/cards/delphes_skimmed_ATLAS_13TeV.tcl']:
        put(root, path, 'fixture source\n')
    put(root, 'data/atlas_0000_00032/pyhf_conf.json', json.dumps({'analysis': [
        {'name': 'pair', 'bkgonly': 'background.json', 'patchset': 'patch.json'}]}))
    put(root, 'data/atlas_0000_00032/Likelihoods/background.json', '{}')
    put(root, 'data/atlas_0000_00032/Likelihoods/patch.json', '{}')
    return m.checkmate_catalog(root)


@pytest.fixture
def provider_request(tmp_path):
    events = put(tmp_path, 'supplied.hepmc', 'HepMC::Version 2.06.09\nHepMC::IO_GenEvent-START_EVENT_LISTING\n')
    return {'routine': 'checkmate:atlas_0000_00032', 'events': {'path': str(events), 'sha256': m._sha(events)},
            'format': 'hepmc2', 'max_events': 17, 'cross_section_fb': 2.5,
            'cross_section_error_fb': .125, 'random_seed': 83091, 'model': 'fullpyhf',
            'quantity': 'region_table', 'output_parent': str(tmp_path / 'native'),
            'name': 'control', 'weight_convention': 'supplied nominal signed weights; no cap', 'runtime': None}


def test_whole_active_list_and_never_served_credit(catalogue):
    assert catalogue['active_routines'] == 1
    row = m.resolve(catalogue, 'atlas_0000_00032')
    assert row['detector_card'].endswith('ATLAS_13TeV.tcl')
    assert row['signal_regions'] == ['SR1', 'SR2']
    assert catalogue['served_tasks'] is None and row['scientific_coverage'] is False


def test_prepare_materializes_actual_settings(catalogue, provider_request, tmp_path):
    result = m.prepare_checkmate(catalogue, provider_request, tmp_path / 'prepared')
    cfg = configparser.ConfigParser(); cfg.read(tmp_path / 'prepared/checkmate.ini')
    assert cfg['Parameters']['analyses'] == 'atlas_0000_00032'
    assert cfg['Parameters']['randomseed'] == '83091'
    assert cfg['Parameters']['outputexists'] == 'ask'
    assert cfg['Parameters']['no_mc_stat_err'] == 'false'
    assert cfg['Parameters']['cls'] == 'false'
    assert cfg['Parameters']['uplim'] == 'false'
    assert cfg['Parameters']['expected'] == 'false'
    assert cfg['supplied']['maxevents'] == '17'
    assert cfg['supplied']['xsect'] == '2.5*FB'
    assert result['native_command'] is None and result['blockers']
    assert result['scientific_coverage'] is False and result['executed'] is False


@pytest.mark.parametrize('label,model,engine', [
    ('y', 'simple', 'multibin_limit.calc_point'),
    ('y', 'full', 'spey_wrapper.calc_point'),
    ('y', 'fullpyhf', 'multibin_limit_full.calc_point'),
    ('cov', 'simple', 'spey_wrapper.calc_cov'),
    ('cov', 'full', 'spey_wrapper.calc_cov'),
    ('cov', 'fullpyhf', 'spey_wrapper.calc_cov'),
    ('hs3', 'full', 'hs3_wrapper.calc_workspace'),
])
def test_released_distinct_statistical_branches(catalogue, label, model, engine):
    row = deepcopy(catalogue['entries'][0]); row['likelihood_label'] = label
    assert m.statistical_route(row, model, 'multibin_limits')['engine'] == engine


def test_hs3_real_limits_do_not_promote_placeholder_cls(catalogue):
    row = deepcopy(catalogue['entries'][0]); row['likelihood_label'] = 'hs3'
    with pytest.raises(ValueError, match='placeholder'):
        m.statistical_route(row, 'full', 'multibin_cls')
    with pytest.raises(ValueError, match='overrides'):
        m.statistical_route(row, 'simple', 'multibin_limits')


@pytest.mark.parametrize('model,label', [('fullpyhf', 'n'), ('full', '!n'), ('full', None)])
def test_unsupported_full_branch_refuses_instead_of_default(catalogue, model, label):
    row = deepcopy(catalogue['entries'][0]); row['likelihood_label'] = label
    with pytest.raises(ValueError, match='no supported'):
        m.statistical_route(row, model, 'multibin_cls')


@pytest.mark.parametrize('fmt', ['lhe', 'hepmc3', 'delphes-root', 'stdhep'])
def test_unimplemented_event_routes_need_exact_contract(catalogue, provider_request, tmp_path, fmt):
    provider_request['format'] = fmt
    with pytest.raises(ValueError, match='separate contracts'):
        m.prepare_checkmate(catalogue, provider_request, tmp_path / 'prepared')


@pytest.mark.parametrize('field,value', [('max_events', True), ('max_events', 0), ('random_seed', 0),
                                        ('cross_section_fb', float('nan')), ('cross_section_error_fb', -1)])
def test_bad_controls_fail_before_materializing(catalogue, provider_request, tmp_path, field, value):
    provider_request[field] = value
    with pytest.raises(ValueError): m.prepare_checkmate(catalogue, provider_request, tmp_path / 'prepared')
    assert not (tmp_path / 'prepared').exists()


def test_altered_event_bytes_refuse(catalogue, provider_request, tmp_path):
    Path(provider_request['events']['path']).write_text('altered')
    with pytest.raises(ValueError, match='changed'): m.prepare_checkmate(catalogue, provider_request, tmp_path / 'prepared')


def test_hepmc3_mislabeled_as_hepmc2_refuses(catalogue, provider_request, tmp_path):
    p = Path(provider_request['events']['path']); p.write_text('HepMC::Version 3.02.05\n')
    provider_request['events']['sha256'] = m._sha(p)
    with pytest.raises(ValueError, match='framing'): m.prepare_checkmate(catalogue, provider_request, tmp_path / 'prepared')


def test_valid_framing_with_unrecognized_file_extension_refuses(catalogue, provider_request, tmp_path):
    source = Path(provider_request['events']['path'])
    renamed = source.with_suffix('.hepmc2'); source.rename(renamed)
    provider_request['events']['path'] = str(renamed)
    with pytest.raises(ValueError, match='requires .hepmc'):
        m.prepare_checkmate(catalogue, provider_request, tmp_path / 'prepared')


def test_detector_card_drift_refuses(catalogue, provider_request, tmp_path):
    p = Path(catalogue['root']) / catalogue['entries'][0]['detector_card']; p.write_text('altered')
    with pytest.raises(ValueError, match='changed'): m.prepare_checkmate(catalogue, provider_request, tmp_path / 'prepared')


def test_missing_likelihood_asset_is_blocker(catalogue, provider_request, tmp_path):
    provider_request['quantity'] = 'multibin_limits'
    (Path(catalogue['root']) / 'data/atlas_0000_00032/Likelihoods/background.json').unlink()
    result = m.prepare_checkmate(catalogue, provider_request, tmp_path / 'prepared')
    assert any('Missing/LFS' in b for b in result['blockers'])


def test_duplicate_map_last_value_and_original_objection_retained(catalogue, provider_request, tmp_path):
    put(Path(catalogue['root']), 'data/atlas_0000_00032/pyhf_conf.json',
        '{"analysis":[{"name":"pair","SR_dict":{"channel":"SR1","channel":"SR2"}}]}')
    fresh = m.checkmate_catalog(catalogue['root'])
    dup = fresh['entries'][0]['duplicate_statistical_mapping_keys'][0]
    assert dup == {'key': 'channel', 'previous': 'SR1', 'effective': 'SR2'}
    provider_request['quantity'] = 'multibin_limits'
    with pytest.raises(ValueError, match='duplicate keys'):
        m.prepare_checkmate(fresh, provider_request, tmp_path / 'prepared')
    assert not (tmp_path / 'prepared').exists()


def test_no_output_overwrite(catalogue, provider_request, tmp_path):
    (Path(provider_request['output_parent']) / provider_request['name']).mkdir(parents=True)
    with pytest.raises(ValueError, match='already exists'): m.prepare_checkmate(catalogue, provider_request, tmp_path / 'prepared')


def test_space_unsafe_upstream_path_refused(catalogue, provider_request, tmp_path):
    provider_request['output_parent'] = str(tmp_path / 'unsafe path')
    with pytest.raises(ValueError, match='spaces'): m.prepare_checkmate(catalogue, provider_request, tmp_path / 'prepared')


def table(tmp_path, rows):
    return put(tmp_path, 'total_results.txt', ' '.join(m.COLUMNS) + '\n' + '\n'.join(rows) + '\n')


def test_complete_native_table_preserves_sign_and_distinguishes_r(catalogue, tmp_path):
    p = table(tmp_path, ['atlas_0000_00032 SR2 1 2 .2 0 .3 5 6 -.1 -.2',
                         'atlas_0000_00032 SR1 3 4 .4 -2 .5 7 8 -.3 -.4'])
    result = m.import_region_table(p, catalogue['entries'][0])
    assert result['rows'][1]['s'] == -2
    assert result['rows'][1]['robscons'] == -.3
    assert result['cls'] is None and result['covariance'] is None


@pytest.mark.parametrize('rows', [
    ['atlas_0000_00032 SR1 1 2 .2 3 .3 5 6 .1 .2'],
    ['wrong SR1 1 2 .2 3 .3 5 6 .1 .2'],
    ['atlas_0000_00032 SR1 1 2 .2 3 .3 5 6 .1 .2'] * 2,
    ['atlas_0000_00032 SR1 1 2 .2 nan .3 5 6 .1 .2'],
])
def test_bad_table_census_refuses(catalogue, tmp_path, rows):
    with pytest.raises(ValueError): m.import_region_table(table(tmp_path, rows), catalogue['entries'][0])


def test_pad_url_population_not_acquired_code(tmp_path):
    for stem in ('pad', 'padforma5tune', 'padforsfs'):
        row = {'name': 'same_analysis', 'description': 'fixture', 'padversion': 'v1.1',
               'ma5version': 'v1.9.60', 'gcc': '98', 'url': {'cpp': 'https://example/source'}}
        data = base64.b64encode(zlib.compress(json.dumps([row]).encode())).decode()
        put(tmp_path, f'src/pad_configuration/meta/{stem}_data.jz', '# Ma5 - PAD metadata created on fixture\n' + data)
    result = m.pad_catalog(tmp_path)
    assert result['catalogue_rows'] == 3 and result['unique_names'] == 1
    assert result['served_tasks'] is None
    with pytest.raises(ValueError, match='ambiguous'): m.resolve(result, 'same_analysis')
    assert m.resolve(result, 'madanalysis5:pad:same_analysis')['runtime_route'] == 'v1.2'


def test_paper_identity_is_not_selection_or_coverage_equivalence(catalogue):
    ravel = {'entries': [{'id': 'rivet:fixture', 'publication_urls': [('https://arxiv.org/abs/' + syn.arxiv(32))]},
                         {'id': 'simpleanalysis:another', 'metadata': {'References': [('arXiv: ' + syn.arxiv(32))]}}]}
    joined = m.paper_join(ravel, catalogue)
    assert joined['shared_paper_count'] == 1
    assert len(joined['shared_papers'][('arxiv:' + syn.arxiv(32))]) == 3
    assert joined['served_tasks'] is None and joined['scientific_equivalence'] is False


def test_actual_ravel_metadata_references_string_and_empty_string(catalogue):
    ravel = {'entries': [{'id': 'rivet:fixture', 'metadata': {'References': ('arXiv: ' + syn.arxiv(32))}},
                         {'id': 'simpleanalysis:unknown', 'metadata': {'References': ''}}]}
    joined = m.paper_join(ravel, catalogue)
    assert joined['shared_paper_count'] == 1
    assert joined['unresolved'] == ['simpleanalysis:unknown']


def test_native_import_header_cannot_alias_r_as_cls(catalogue, tmp_path):
    p = table(tmp_path, [])
    p.write_text(p.read_text().replace('robscons', 'cls_obs'))
    with pytest.raises(ValueError, match='header'): m.import_region_table(p, catalogue['entries'][0])


def test_sourced_alias_is_not_unknown_catalogue_credit(catalogue, tmp_path):
    source = put(tmp_path, 'alias-source.txt', 'supplied mapping assertion only')
    alias = {'paper': ('arxiv:' + syn.arxiv(32)), 'routine': 'madanalysis5:unknown',
             'source_pin': {'path': str(source), 'sha256': m._sha(source)}}
    with pytest.raises(ValueError, match='not in'): m.paper_join({'entries': []}, catalogue, [alias])
    alias['routine'] = 'checkmate:atlas_0000_00032'; source.write_text('changed')
    with pytest.raises(ValueError, match='changed'): m.paper_join({'entries': []}, catalogue, [alias])


def test_actual_command_entrypoints_discovery_prepare_complete_import(catalogue, provider_request, tmp_path):
    catalog_path = tmp_path / 'catalogue.json'
    assert m.main(['catalogue', '--backend', 'checkmate', '--source', catalogue['root'],
                   '--out', str(catalog_path)]) == 0
    request = put(tmp_path, 'request.json', json.dumps(provider_request))
    assert m.main(['prepare-checkmate', '--catalogue', str(catalog_path), '--request', str(request),
                   '--out', str(tmp_path / 'prepared')]) == 0
    p = table(tmp_path, ['atlas_0000_00032 SR1 1 2 .2 -3 .3 5 6 -.1 -.2',
                         'atlas_0000_00032 SR2 1 2 .2 0 .3 5 6 -.1 -.2'])
    out = tmp_path / 'import.json'
    assert m.main(['import-region-table', '--catalogue', str(catalog_path),
                   '--routine', provider_request['routine'], '--table', str(p), '--out', str(out)]) == 0
    result = m.read_json(out)
    assert len(result['rows']) == 2 and result['rows'][0]['s'] == -3 and result['cls'] is None
    with pytest.raises(FileExistsError):
        m.main(['catalogue', '--backend', 'checkmate', '--source', catalogue['root'], '--out', str(catalog_path)])


@pytest.mark.parametrize('quantity', ['region_table','multibin_cls','multibin_limits'])
def test_requested_and_effective_upstream_statistics_are_distinct(catalogue,provider_request,tmp_path,quantity):
    provider_request['quantity']=quantity
    value=m.prepare_checkmate(catalogue,provider_request,tmp_path/'prepared')
    expected=value['effective_statistics']
    assert value['requested_statistics']['expected_band'] is False
    assert expected['expected_band_requested_from_wrapper'] is (quantity=='multibin_limits')
    assert expected['observed_cls_requested_from_wrapper'] is (quantity!='region_table')
    assert expected['observed_upper_limit_requested_from_wrapper'] is (quantity=='multibin_limits')
    assert expected['extra_work_vs_declared_quantity'] is (quantity=='multibin_limits')
    assert expected['runtime_observed'] is False


def test_effective_hs3_detailed_does_not_claim_computed_cls(catalogue):
    row=deepcopy(catalogue['entries'][0]);row['likelihood_label']='hs3'
    route=m.statistical_route(row,'full','multibin_limits')
    effective=m.effective_statistics(route)
    assert effective['observed_cls_requested_from_wrapper'] is True
    assert effective['returned_cls_computed'] is False
    assert effective['hs3_cls_placeholders_quarantined'] is True
    assert effective['expected_band_requested_from_wrapper'] is True
