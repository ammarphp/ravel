"""Former fixed tables and helpers against the shipped descriptors and engines that replaced them.

Each control states a former constant or helper of the 2026-10-10 development line and checks
that the shipped data file or general engine carries the same content or behaviour. Routine
identities are read from the shipped data, never written here. These are equivalence checks of
transcriptions; none qualifies detector, classifier, calibration or physics accuracy.
"""
import bisect
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import pytest

from ravel.physics import compressed_validation as cv
from ravel.physics import hhh_response as hr
from ravel.physics import native_simpleanalysis
from ravel.physics import nlo_xsec
from ravel.physics import reinterpret_db
from ravel.physics import shipped_assets as sa
from ravel.physics import slepton_origin as origin
from ravel.physics import width_inputs
from ravel.physics.analysis_packages import load_routine

from analysis_package_fixtures import selected_manifest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'src' / 'ravel' / 'data'


def _json(path):
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------- native cumulant tables

OLD_SOURCE_DIGESTS = {
    'analysis': 'ab90942dc5b75b28f53d4e740473ce8c02baec351c8ccbb84947c1f9b0b052f4',
    'correlators': 'e326266236f4df5292b9de6e01d02debc78c4a484fec48384be4f49ac243f197',
    'reference': 'beec53f9b87a1d9bab82094e3db0e135b32372f436244090956222ca1fd81e5a',
    'writer': 'be593c12bb63e7078ecc9443725f97235dcf2cdc6d2854396b3c6e14600b7d1e',
    'scatter': 'bfa0b826d5b5bf30e217e0e062ce8b80a127aedc16e43fb452ee6e5d6d8f85c0',
    'point': 'a8a740cc4b916e200f77f335685ab09d4cb255c727fe819303626bd490e43279',
    'profile': 'ac6649d2a4f2440b7a558b187e129d961e60eb87202112827a9b680f657ebc35',
    'dbn': 'ec9bf3a268d625fbd8e093dabcea0da47c2c5294105d90f0b70f10ebce7d17b3',
    'storage': '1e6bc70c8bd1869488064d2d38cead6fcb6519742088fc25ca47a87c745c82fc',
    'binning': '6d0f7a62d68a1c90757117670469b841a72caa50f08ad2977be3fcd732afd959',
    'type_ids': '448e7922099a51ab492e27bea56a225f8f6409670d6d7dec4585ec51bcb30dc4',
    'correlator_projection': '45e17bec7de26f25eeda0e424bb08af1931462c565f9ec7335df33c4ae47ae62',
    'analysis_booking': '8946a4b8a9889507734f0503f80551624c582ba1151e82225a8c9577707452c1',
    'estimate_geometry': '18e742a1e86b1ae2c1095e8105697e66b7e86c8e271bcac918a3fc9641a63a4a',
    'writer_precision': '427962c546190cd4758f4afc39c3f563b33bcd7ea323e53520ca247132287aa2',
}
# The two routine-named files carry the routine id in their former names; they ship renamed.
OLD_SOURCE_FILES = {
    'analysis': '{routine}.cc', 'correlators': 'Correlators-4.1.3.hh', 'reference': '{routine}.yoda.gz',
    'writer': 'WriterYODA.cc', 'scatter': 'YODA-Scatter.h', 'point': 'YODA-Point.h', 'profile': 'YODA-Profile.h',
    'dbn': 'YODA-BinnedDbn.h', 'storage': 'YODA-BinnedStorage.h', 'binning': 'YODA-Binning.h',
    'type_ids': 'YODA-Utils-BinningUtils.h', 'correlator_projection': 'Correlators-4.1.3.cc',
    'analysis_booking': 'Rivet-Analysis-4.1.3.hh', 'estimate_geometry': 'YODA-BinnedEstimate.h',
    'writer_precision': 'YODA-Writer.h',
}
SHIPPED_NAME = {'{routine}.cc': 'routine.cc', '{routine}.yoda.gz': 'reference.yoda.gz'}
OLD_POPULATION = (
    (1, 'cnTwoInt', ('ec22',), None, '1'),
    (3, 'cnTwoInt', ('ec32',), None, '1'),
    (11, 'vnTwoDiff', ('ec22pT',), 'ec22pT', 'GeV'),
    (17, 'vnTwoDiff', ('ec22pTh',), 'ec22pTh', 'GeV'),
    (18, 'vnTwoDiff', ('ec22pTK',), 'ec22pTh', 'GeV'),
    (19, 'vnTwoDiff', ('ec22pTL',), 'ec22pTh', 'GeV'),
    (21, 'vnTwoDiff', ('ec22pTKc',), 'ec22pT', 'GeV'),
    (22, 'vnTwoDiff', ('ec22pTLc',), 'ec22pT', 'GeV'),
    (28, 'cnFourInt', ('ec22_4', 'ec24_4'), None, '1'),
    (31, 'cnSixInt', ('ec22_6', 'ec24_6', 'ec26_6'), None, '1'),
)
OLD_ECORR_TABLE = {e: t for t, _, es, _, _ in OLD_POPULATION for e in es}


def _old_path_for(routine, table, suffix=''):
    return f'/{routine}/d{table:02d}-x01-y01{suffix}'


def test_cumulant_source_tables_equal_the_shipped_pins_and_names():
    mapping = sa.cumulant_mapping()
    routine = mapping['routine']
    pins = {p['role']: p for p in mapping['sources']}
    # every former source, the binned-distribution header included, ships with its old digest
    assert set(pins) == set(OLD_SOURCE_DIGESTS) and len(pins) == 15
    for role, pin in pins.items():
        assert pin['sha256'] == OLD_SOURCE_DIGESTS[role]
        assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest() == OLD_SOURCE_DIGESTS[role]
        old = OLD_SOURCE_FILES[role]
        assert Path(pin['path']).name == SHIPPED_NAME.get(old, old)
    # the routine source and reference are the former routine-named files, byte for byte
    assert routine and pins['analysis']['path'].endswith('routine.cc')
    assert pins['reference']['path'].endswith('reference.yoda.gz')


def test_cumulant_population_and_correlator_tables_equal_the_shipped_mapping():
    from ravel.physics import native_cumulant as cumulant
    mapping = sa.cumulant_mapping()
    routine = mapping['routine']
    outputs = {o['path']: o for o in mapping['outputs']}
    assert len(outputs) == len(OLD_POPULATION)
    for table, operation, ecorrs, reference, unit in OLD_POPULATION:
        row = outputs[_old_path_for(routine, table)]
        assert row['operation'] == operation
        correlators = {x.rsplit('-', 1)[0] for x in row['operands']}
        assert correlators == set(ecorrs) | ({reference} if reference else set())
        assert all(len([x for x in row['operands'] if x.rsplit('-', 1)[0] == e]) == 9 for e in correlators)
        assert row['axes'][0]['unit'] == unit
    table_of = {p['id'].rsplit('-', 1)[0]: int(re.search(r'/d(\d+)-x01-y01$', p['reference_path'])[1])
                for p in mapping['profiles']}
    assert table_of == OLD_ECORR_TABLE
    # former cms_requests / released_sources: the requests of the shipped mapping carry the old paths
    requests = cumulant.requests_for(sa.cumulant_mapping(native_weight='w1'))
    assert sorted(r['path'] for r in requests) == sorted(
        _old_path_for(routine, t, '[w1]') for t, *_ in OLD_POPULATION)


# ---------------------------------------------------------------- native group fill sites

OLD_SITES_SHA256 = 'fc675f2f00ecc0fb40d32d8e8587601835d7c0905f4d6461b8355ec39f63b660'


def test_group_fill_sites_equal_the_former_site_table():
    """sha256 of the former SITES table (routine -> ordered fill anchors), canonical JSON."""
    routines = _json(DATA / 'analysis_assets/group-fills/descriptors.json')['routines']
    sites = {name: [s['anchor'] for s in sorted(row['sites'], key=lambda s: s['id'])]
             for name, row in routines.items()}
    assert sorted(routines) == sa.group_fill_routines()
    assert hashlib.sha256(json.dumps(sites, sort_keys=True).encode()).hexdigest() == OLD_SITES_SHA256


# ---------------------------------------------------------------- SFitter source pins

OLD_CARD_SOURCES = {
    'Top_Full.json': '472449dcee7e1aaedfa3daeb7fb0431c6b5eabf39d4121c391b145c9b0fb0cd8',
    'Higgs_Full.json': '8ae0a8bad6d38e570efe158b3a10717bce514909a2dd57d3e96dfd5229f756d0',
    'Higgs_Full_with_CtG.json': '60d0fbd5ca396512d7921737e63254c21e6084b53ee5599c4d9d4f4cf28980b8',
    'TopLikelihood_22WC.json': 'e36925b18cadbdeea7292df18331565fafd8482f8ff1888da731ceb0c6bee688',
}
OLD_TOP_EVALUATOR_SOURCES = {
    'sfitter/sfitter/likelihood/datacard.py': 'a713917945b980afd4759ef7d637d7c9aa891e28cec6fdc7612e52d36544d6fa',
    'sfitter/sfitter/likelihood/predictions.py': '5f5b332a7595d4fda86ab09a4c379a2e3aba3c93d07e4ca71ce0696aba5bde23',
    'sfitter/sfitter/likelihood/full_likelihood.py': 'c4f34730c45ee03de503b0dd1d343717ce1343500c59ecdd05ae56cbdfc62d65',
}
OLD_HIGGS_SOURCES = {
    'sfitter/sfitter/likelihood/predictions.py': '5f5b332a7595d4fda86ab09a4c379a2e3aba3c93d07e4ca71ce0696aba5bde23',
    'sfitter/sfitter/likelihood/full_likelihood.py': 'c4f34730c45ee03de503b0dd1d343717ce1343500c59ecdd05ae56cbdfc62d65',
    'sfitter/sfitter/likelihood/datacard.py': 'a713917945b980afd4759ef7d637d7c9aa891e28cec6fdc7612e52d36544d6fa',
    'sfitter/sfitter/likelihood/sm.py': 'd6c0d8899c1101ce662374633ea852ba5f94aef4529a0111599e35f7744a20fa',
}


def _pins(value):
    """Every {path, sha256} pair anywhere in a record."""
    if isinstance(value, dict):
        if isinstance(value.get('sha256'), str) and isinstance(value.get('path'), str):
            yield value['path'], value['sha256']
        for item in value.values():
            yield from _pins(item)
    elif isinstance(value, list):
        for item in value:
            yield from _pins(item)


def _digests(value):
    return set(re.findall(r'[0-9a-f]{64}', json.dumps(value)))


def test_sfitter_source_tables_are_carried_by_the_published_records():
    from ravel.physics import sfitter_published_records as published
    records = DATA / 'sfitter/published-records'
    upstream = _json(DATA / 'sfitter/upstream-source.json')
    assert set(OLD_CARD_SOURCES.values()) <= _digests(upstream)
    index = _json(records / 'index.json')
    for card in ('Top_Full.json', 'Higgs_Full.json', 'Higgs_Full_with_CtG.json'):
        assert OLD_CARD_SOURCES[card] in _digests(index)
    assert {name: pin['sha256'] for name, pin in published.cards().items()} == {
        name: OLD_CARD_SOURCES[name] for name in ('Top_Full.json', 'Higgs_Full.json', 'Higgs_Full_with_CtG.json')}
    top = _digests(_json(records / 'top-full.defect-registry.json'))
    assert set(OLD_TOP_EVALUATOR_SOURCES.values()) <= top
    for name in ('higgs-full', 'higgs-full-with-ctg'):
        assert set(OLD_HIGGS_SOURCES.values()) <= _digests(_json(records / f'{name}.defect-registry.json'))
    # the two-coupling Top likelihood source digest is pinned by the Top repair manifest
    assert OLD_CARD_SOURCES['TopLikelihood_22WC.json'] in _digests(_json(records / 'top-full.repair-manifest.json'))


# ---------------------------------------------------------------- compressed cutflow constants

OLD_PREFIX = ('bad_jet_veto', 'baseline_lepton', 'signal_jet')
OLD_COMMON = ('two_signal_leptons', 'jpsi_veto', 'min_jet_met_dphi', 'leading_jet_met_dphi',
              'mll_window', 'lepton_separation', 'leading_lepton_pt', 'jet_count',
              'leading_jet_pt', 'b_veto', 'mtautau_veto', 'same_flavour', 'opposite_charge', 'met_preselection')
OLD_MT2 = tuple(f'mt2_lt_{x}' for x in (140, 130, 120, 110, 105, 102, 101, '100p5'))
OLD_UNAVAILABLE = {'generator_filter': 'No matching ATLAS generator-filter event population',
                   'trigger': 'No measured trigger decision or efficiency in Delphes2SA',
                   'author16_veto': 'ATLAS lepton author unavailable in Delphes2SA',
                   'truth_matching': 'Delphes2SA mother pointers do not retain truth matches'}
OLD_PREDICATES = tuple(dict.fromkeys((*OLD_PREFIX, *OLD_COMMON, 'mt2_gt_100', *OLD_MT2,
    *(f'{quantity}_{band}' for band in ('high', 'low') for quantity in ('met', 'risr', 'subleading_pt')),
    *OLD_UNAVAILABLE)))


def test_compressed_cutflow_constants_equal_the_shipped_definition(tmp_path):
    definition = _json(DATA / 'analysis_assets/cutflow/compressed-slepton.cutflow.json')
    assert tuple(definition['object_preconditions']) == OLD_PREFIX
    assert tuple(definition['predicates']) == OLD_PREDICATES
    assert definition['unavailable'] == OLD_UNAVAILABLE
    for flow in definition['flows'].values():
        assert tuple(p for p in flow if p in OLD_COMMON) == OLD_COMMON
        assert tuple(p for p in flow if p in OLD_MT2) == OLD_MT2
    # the shipped definition binds to a producer and starts an event with the full predicate population
    producer = tmp_path / 'selection.py'
    producer.write_text('# synthetic producer bytes\n')
    pin = sa.cutflow_definition(producer, tmp_path / 'definition')
    bound = cv.bind(pin)
    assert tuple(bound.value['predicates']) == OLD_PREDICATES


# ---------------------------------------------------------------- six-b trace and response tables

OLD_FEATURES = ('mH_radius', 'mH1', 'RMS_mjj', 'RMS_DeltaRjj', 'RMS_eta', 'Skewness_DeltaAjj', 'HT_6j', 'cosTheta',
                'Aplanarity_6j', 'Sphericity_6j', 'TransverseSphericity_6j', 'Sphericity_allj', 'eta_mHHH',
                'DeltaRH1', 'DeltaRH2', 'DeltaRH3')
OLD_FAMILIES = ('res', 'nonres', 'heavyres')
OLD_EDGES = {
    'res': ('0.05', '0.1', '0.15', '0.2', '0.25', '0.3', '0.35', '0.4', '0.45', '0.5', '0.55', '0.6', '0.65', '0.7',
            '0.75', '0.8', '0.85', '0.9', '0.95'),
    'nonres': ('0.1', '0.15', '0.2', '0.25', '0.3', '0.35', '0.4', '0.45', '0.5', '0.55', '0.6', '0.65', '0.7', '0.75',
               '0.8', '0.85', '0.9', '0.95', '0.975'),
    'heavyres': ('0.1', '0.15', '0.2', '0.25', '0.3', '0.35', '0.4', '0.45', '0.5', '0.55', '0.6', '0.65', '0.7',
                 '0.75', '0.8', '0.85', '0.9', '0.95'),
}
OLD_VETOES = ('four_jets', 'trigger', 'six_jets', 'fourth_jet', 'four_btags')
OLD_LIMITATIONS = [
    'Released Rivet approximate response; no ATLAS endorsement or detector calibration qualification.',
    'Source uses approximate JVT, extrapolated b-tag efficiencies and omits trigger correction factors; muon smearing remains despite unused selected muons.',
    'Source cosTheta and boosted event-shape conventions are preserved. Pairing/feature/inference native accuracy and observer noninterference remain unqualified.',
    'All three network families overlap on the same events; these channel marks are not independent Poisson observations or an inferred auxiliary sampling law.',
    'Every original event and weight remains. Signed weights are not clipped; complete recorded per-weight native normalization is retained; conditional Gram propagation is not native final-YODA error equivalence.',
]


def _old_label(family, score):
    edges = OLD_EDGES[family]
    return 'overflow' if score < float(edges[0]) or score > 1 else edges[bisect.bisect_right(tuple(map(float, edges)), score) - 1]


def test_six_b_trace_tables_equal_the_shipped_descriptor():
    descriptor = sa.six_b_descriptor()
    text = '\n'.join(edit['new'] for edit in descriptor['instrumentation']['edits'])
    features = re.search(r'_trace\(\\?"features\\?",(.*?)\);', text)
    assert features, 'the trace emits the full feature record'
    assert tuple(re.findall(r'_tj\(\\?"(\w+)\\?"\)', features[1])) == OLD_FEATURES
    vetoes = list(dict.fromkeys(re.findall(r'_veto_trace\(\\?"(\w+)\\?"\)', text)))
    assert tuple(vetoes) == OLD_VETOES
    classifiers = descriptor['trace']['classifiers']
    assert tuple(dict.fromkeys(c['id'].split('.')[0] for c in classifiers)) == OLD_FAMILIES
    labels = {tuple(m) for m in re.findall(r'"bin_label", "args": \[[^\]]*?\]\}, \{"literal": (\[[^\]]*\])\}, \{"literal": (\[[^\]]*\])\}',
                                         json.dumps(descriptor)) for m in [json.loads(m[1])]}
    assert labels == set(OLD_EDGES.values())
    assert descriptor['limitations'][:5] == OLD_LIMITATIONS


@pytest.mark.parametrize('family', OLD_FAMILIES)
def test_six_b_score_label_matches_the_former_label_function(family):
    edges = OLD_EDGES[family]
    scores = [-0.1, 0.0, float(edges[0]), 0.07, 0.1, 0.33, 0.5, 0.95, 0.96, 0.975, 0.99, 1.0, 1.0000001, 2.0]
    for score in scores:
        expression = {'op': 'bin_label', 'args': [{'literal': score}, {'literal': [float(e) for e in edges]},
                                                  {'literal': list(edges)}, {'literal': 1}, {'literal': 'overflow'}]}
        assert hr.evaluate(expression, {}) == _old_label(family, score)


# ---------------------------------------------------------------- response contract and origin

def test_slepton_response_tables_equal_the_shipped_contract():
    contract = sa.response_contract()
    assert tuple(contract['pt_edges']) == (0, 2, 3, 4, 5, 7, 10, 15, 20, 30, 50, 100, None)
    assert tuple(contract['abs_eta_edges']) == (0, .8, 1.37, 1.52, 2., 2.47, 2.5, None)
    roots = next(rule['value'] for rule in contract['topology'] if rule['kind'] == 'allowed_roots')
    assert frozenset(roots) == frozenset((1000011, 2000011, 1000013, 2000013))
    labels = contract['origin_labels']
    assert (labels['direct'], contract['ancestor_categories'][0]['id'], labels['descendant'], labels['other']) == (
        'direct_slepton', 'tau_ancestor', 'other_slepton_descendant', 'other_origin')


def _old_charged_slepton_code(pid):
    return abs(pid) >= 1000000 and abs(pid) % 1000000 in (11, 13, 15)


def test_charged_slepton_root_predicate_is_a_supplied_selector():
    contract = {'root_selector': {'minimum_abs_pid': 1000000, 'modulus': 1000000, 'remainders': [11, 13, 15]}}
    pids = [11, 13, 15, 22, 1000011, -1000011, 2000013, -2000015, 1000012, 1000022, 1000024, 3000015, 999999]
    for pid in pids:
        assert origin.selected_root(pid, contract) == _old_charged_slepton_code(pid)


# ---------------------------------------------------------------- columnar descriptors

def test_ntuple_prefix_and_period_tables_equal_the_packaged_descriptor():
    descriptor = _json(DATA / 'columnar/branch_roles/atlas-cp-nominal-ntuple.json')
    assert tuple(c['prefix'] for c in descriptor['containers']) == ('el', 'mu', 'ph', 'tau', 'jet', 'largeRjet')
    assert tuple(int(p) for p in descriptor['periods']) == (2015, 2016, 2017, 2018, 2022, 2023, 2024, 2025)


def test_tree_array_scalar_and_family_tables_equal_the_packaged_layout():
    text = json.dumps(_json(DATA / 'columnar/array_layouts/atlas-opendata-13tev-diphoton-raw46.json'))
    for scalar in ('met_et', 'met_phi', 'mcWeight', 'SumWeights', 'XSection', 'scaleFactor_PILEUP',
                   'scaleFactor_PHOTON', 'scaleFactor_PhotonTRIGGER', 'scaleFactor_ELE', 'scaleFactor_MUON',
                   'scaleFactor_LepTRIGGER', 'scaleFactor_BTAG'):
        assert f'"{scalar}"' in text
    for family in ('photon', 'lep', 'jet'):
        assert family in text


OLD_RELEASE = {
    'submission.yaml': 'ce5eb11cae0dd50c3e4c96c7954d853ff7a5bf03f5b7af02bb58578ac9883c8f',
    'SR.yaml': 'a4d1619aaedbc149bf47add20dc74a20e3795da3155ee9c6c6f861d4e8bc9bff',
    'forward_CR.yaml': '0b607b4c1dd7627dd59f6b82574afce32d2bdc75bbe9247cc71b5f0c640d5276',
    'central_inverted_CR.yaml': 'ba4a3604e94a42d4ddf105a05fa668d84a296524f08aa2a4b441aa7acc5cf4b5',
    'forward_inverted_CR.yaml': 'c4056329948ecfaa087fbe06c68f202e9950d467e3a2ae31fa7aa7e1889be01b',
    'coupling.yaml': '147dcdc61717d4206d92a0bb51ac4220384224a6330363daf7ac2dacac130e4e',
    'xsec.yaml': '6f19335935aa8846bd6275b8a59f9026630d1d6539c470d472baa02c61310872',
}
OLD_REGIONS = ('central_tagged', 'forward_tagged', 'central_antitagged', 'forward_antitagged')
OLD_REGION_FILES = dict(zip(OLD_REGIONS, ('SR.yaml', 'forward_CR.yaml', 'central_inverted_CR.yaml',
                                          'forward_inverted_CR.yaml')))
OLD_SERIES = ['Data', 'Non-resonant background', '$\\gamma+W$', '$\\gamma+Z$', '$t\\bar{t}$',
              "$\\gamma + Z' (m_{Z'} = 20) GeV$", "$\\gamma + Z' (m_{Z'} = 40) GeV$",
              "$\\gamma + Z' (m_{Z'} = 125) GeV \\times 5$", 'Background estimate uncertainty']


def test_width_release_tables_equal_the_packaged_source_descriptor():
    names = width_inputs.descriptor_names()
    assert len(names) >= 1
    descriptor = _json(width_inputs.LIBRARY / f'{names[0]}.json')
    assert descriptor['files'] == OLD_RELEASE
    regions = [t for t in descriptor['tables'] if t['role'] == 'region']
    assert tuple(t['id'] for t in regions) == OLD_REGIONS
    assert {t['id']: t['file'] for t in regions} == OLD_REGION_FILES
    for table in regions:
        assert [c['header']['name'] for c in table['columns']] == OLD_SERIES


# ---------------------------------------------------------------- shipped selection packages

def test_selected_two_pass_package_serves_the_former_region_orders(monkeypatch):
    manifest = selected_manifest('selection-a')
    monkeypatch.setenv('RAVEL_ANALYSIS_PACKAGE', str(manifest))
    routine = load_routine(manifest)
    assert native_simpleanalysis.sr_order() == routine.sr_order() and len(routine.sr_order()) == 141
    assert native_simpleanalysis.cr_order() == [f'CR_S_{p}_{m}' for p in ('VV', 'tau', 'top') for m in ('high', 'low')]
    for name in ('select_objects', 'select_regions', 'select_slepton_controls'):
        assert callable(getattr(native_simpleanalysis, name))


def test_counting_packages_serve_the_former_routine_module_functions(tmp_path, monkeypatch):
    for label in ('selection-b', 'selection-c'):
        manifest = selected_manifest(label)
        routine = load_routine(manifest)
        assert routine.sr_order() == _json(manifest)['routine']['regions']
        assert callable(routine.select)
    erjr = load_routine(selected_manifest('selection-c'))
    assert callable(erjr.h_boost) and callable(erjr.audit_reconstruction)
    existing = tmp_path / 'audit.json'
    existing.write_text('{}')
    monkeypatch.setattr(sys, 'argv', ['audit', '--input', str(tmp_path / 'events.root'), '--out', str(existing)])
    with pytest.raises(SystemExit) as stopped:
        erjr.main()
    assert stopped.value.code == 2 and existing.read_text() == '{}'


# ---------------------------------------------------------------- restored helpers

def test_nlo_xsec_main_is_a_command_entry_point_with_the_same_refusal():
    assert callable(nlo_xsec.main) and nlo_xsec.main is not nlo_xsec.main_args
    with pytest.raises(SystemExit) as refused:
        nlo_xsec.main(['--process', 'gluino', '--mass', '1000'])
    assert getattr(refused.value, 'reason_code', None) == 'missing_cross_section_input'


SLHA = """BLOCK MASS
   1000011   2.000000E+02   # ~e_L
   1000022   1.500000E+02   # ~chi_10
DECAY   1000011   1.000000E+00
     1.000000E+00   2   1000022   11
DECAY   1000022   0.000000E+00
"""


def test_add_xsection_writes_a_new_slha_with_the_supplied_block(tmp_path):
    source = tmp_path / 'model.slha'
    source.write_text(SLHA)
    output = tmp_path / 'with-xsec.slha'
    pin = reinterpret_db.add_xsection(source, 0.0123, '1000011 -1000011', sqrts_gev=13000., qcd_order=1,
                                      code='supplied-table', output=output)
    assert source.read_text() == SLHA and pin['path'] == str(output.resolve())
    text = output.read_text()
    assert text.startswith(SLHA)
    header, values = text.splitlines()[-2:]
    assert header.split() == ['XSECTION', '1.300000E+04', '2212', '2212', '2', '1000011', '-1000011']
    fields = values.split()
    assert fields[:3] == ['0', '1', '0'] and float(fields[6]) == pytest.approx(0.0123) and fields[7] == 'supplied-table'
    pyslha = pytest.importorskip('pyslha')
    parsed = pyslha.readSLHAFile(str(output))
    process = next(iter(parsed.xsections.values()))
    assert sorted(process.pidsfinal) == [-1000011, 1000011]
    assert process.xsecs[0].value == pytest.approx(0.0123) and process.xsecs[0].qcd_order == 1


@pytest.mark.parametrize('change,match', [
    (dict(sigma_pb=-1.), 'sigma_pb'), (dict(sigma_pb=math.nan), 'sigma_pb'), (dict(sqrts_gev=0.), 'sqrts_gev'),
    (dict(qcd_order=-1), 'qcd_order'), (dict(code='two words'), 'code'), (dict(proc=''), 'proc'),
    (dict(proc='1000011 x'), 'proc'), (dict(initial=(2212,)), 'initial')])
def test_add_xsection_requires_every_convention_explicitly(tmp_path, change, match):
    source = tmp_path / 'model.slha'
    source.write_text(SLHA)
    arguments = dict(sigma_pb=0.01, proc='1000011 -1000011', sqrts_gev=13000., qcd_order=0, code='MG5LO',
                     output=tmp_path / 'out.slha')
    arguments.update(change)
    sigma, proc = arguments.pop('sigma_pb'), arguments.pop('proc')
    with pytest.raises(ValueError, match=match):
        reinterpret_db.add_xsection(source, sigma, proc, **arguments)
    assert not (tmp_path / 'out.slha').exists()


def test_add_xsection_preserves_the_supplied_file_and_refuses_a_duplicate_block(tmp_path):
    source = tmp_path / 'model.slha'
    source.write_text(SLHA)
    with pytest.raises(ValueError, match='new output'):
        reinterpret_db.add_xsection(source, 0.01, [1000011, -1000011], sqrts_gev=13000., qcd_order=0,
                                    code='MG5LO', output=source)
    first = tmp_path / 'first.slha'
    reinterpret_db.add_xsection(source, 0.01, [1000011, -1000011], sqrts_gev=13000., qcd_order=0,
                                code='MG5LO', output=first)
    with pytest.raises(ValueError, match='already carries'):
        reinterpret_db.add_xsection(first, 0.02, '-1000011 1000011', sqrts_gev=13000., qcd_order=1,
                                    code='NLO', output=tmp_path / 'second.slha')
    other_energy = tmp_path / 'other.slha'
    reinterpret_db.add_xsection(first, 0.02, '1000011 -1000011', sqrts_gev=13600., qcd_order=0,
                                code='MG5LO', output=other_energy)
    assert other_energy.read_text().count('XSECTION') == 2
    assert source.read_text() == SLHA
