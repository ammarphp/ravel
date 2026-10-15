"""Shipped source-pinned analysis assets bind to the engines that take supplied descriptors.

Synthetic traces and native text are engineering controls: no native program runs, and no test
here establishes detector, classifier, calibration or physics accuracy. Controls that need
bytes the package does not ship (the exact upstream SFitter tree, an installed Rivet prefix)
run only when ``RAVEL_TEST_SFITTER_SOURCE`` / ``RAVEL_TEST_RIVET_PREFIX`` name them.
"""
import copy
import gzip
import hashlib
import json
import math
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from ravel.physics import classifier_inputs as ci
from ravel.physics import hhh_native_trace as nt
from ravel.physics import hhh_response as hr
from ravel.physics import native_cumulant as cumulant
from ravel.physics import native_group_fills as fills
from ravel.physics import analysis_response_features as ar
from ravel.physics import reviewed_source as records
from ravel.physics import sfitter_card_derivation as derivation
from ravel.physics import sfitter_higgs_support as support
from ravel.physics import sfitter_published_records as published
from ravel.physics import shipped_assets as sa
from ravel.physics import truth_reco_response as truth

import cumulant_fixture
import response_fixture

REPO = Path(__file__).resolve().parents[2]
SFITTER_ZIP = REPO / 'tests/fixtures/sfitteragents-6072a79e.zip'
UPSTREAM = os.environ.get('RAVEL_TEST_SFITTER_SOURCE')
RIVET_PREFIX = os.environ.get('RAVEL_TEST_RIVET_PREFIX')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- cumulant bundle

def test_cumulant_bundle_is_complete_and_every_pin_matches():
    mapping = sa.cumulant_mapping()
    assert len(mapping['outputs']) == 10 and len(mapping['profiles']) == 117
    assert mapping['routine'] and mapping['runtime_version'] == '4.1.3'
    assert {p['role'] for p in mapping['sources']} >= {'analysis', 'reference', 'writer', 'correlators'}
    assert all(sha(p['path']) == p['sha256'] for p in mapping['sources'])
    # every RAW operand is used, nine cyclic subsamples per correlator
    assert {r['id'] for r in mapping['profiles']} == {v for o in mapping['outputs'] for v in o['operands']}
    assert len({r['id'].rsplit('-', 1)[0] for r in mapping['profiles']}) == 13
    assert {o['error_policy'] for o in mapping['outputs']} == {'native_magnitudes', 'literal_zero'}


def test_cumulant_mapping_builds_the_complete_population_and_transports_synthetic_native_text(tmp_path):
    requests = cumulant.requests_for(sa.cumulant_mapping())
    assert len(requests) == 10 and len(cumulant.validate_population(requests)) == 1
    names = {p.name for p in cumulant.quantity_inputs(requests)}
    assert {'routine.cc', 'reference.yoda.gz', 'WriterYODA.cc'} <= names
    native = tmp_path / 'native.yoda'
    native.write_text(cumulant_fixture.payload(requests))
    exported = cumulant.export_family(native, requests)
    assert len(exported['observables']) == 10 and exported['transport']['kind'] == 'native-cumulant-family'


def test_cumulant_native_weight_selects_one_suffixed_stream():
    requests = cumulant.requests_for(sa.cumulant_mapping(native_weight='w1'))
    assert all(r['path'].endswith('[w1]') for r in requests)
    with pytest.raises(sa.AssetError):
        sa.cumulant_mapping(native_weight='bad weight')


def test_cumulant_changed_source_bytes_refuse(tmp_path, monkeypatch):
    bundle = tmp_path / 'native_cumulants'
    shutil.copytree(sa.CUMULANTS, bundle)
    target = bundle / 'WriterYODA.cc'
    target.write_bytes(target.read_bytes() + b'// changed\n')
    monkeypatch.setattr(sa, 'CUMULANTS', bundle)
    with pytest.raises(sa.AssetError, match='differ'):
        sa.cumulant_mapping()


# ---------------------------------------------------------------- six-b package

FAMILIES = ('res', 'nonres', 'heavyres')
FEATURES = ('mH_radius', 'mH1', 'RMS_mjj', 'RMS_DeltaRjj', 'RMS_eta', 'Skewness_DeltaAjj', 'HT_6j', 'cosTheta',
            'Aplanarity_6j', 'Sphericity_6j', 'TransverseSphericity_6j', 'Sphericity_allj', 'eta_mHHH',
            'DeltaRH1', 'DeltaRH2', 'DeltaRH3')
VETOES = ('four_jets', 'trigger', 'six_jets', 'fourth_jet', 'four_btags')


def jet(pt=100., eta=0.):
    return [float(pt + 10), float(pt), 0., 0., float(pt), float(eta), 0., 10.]


@pytest.fixture(scope='module')
def sixb():
    descriptor = sa.six_b_descriptor()
    contracts = hr.source_contracts(sa.six_b_contracts(), descriptor['trace'])
    return descriptor, contracts


def six_b_event(sixb, kind='selected', *, b=6, number=1, weight=1., score=.5, jets=None, labels=None):
    descriptor, contracts = sixb
    counts = {'four_jets': 3, 'trigger': 6, 'six_jets': 5, 'fourth_jet': 6, 'four_btags': 6, 'selected': 6}
    n = counts[kind]
    jets = [jet(100 - i * 5) for i in range(n)] if jets is None else jets
    if kind == 'fourth_jet':
        jets = [jet(40) for _ in range(n)]
    if kind == 'four_btags':
        b = 3
    if kind == 'trigger':
        b = 0
    identity = {'event_number': number, 'raw_weight_names': ['nominal'], 'raw_weights': [weight],
                'selected_weight_names': [''], 'selected_weights': [weight]}
    event = {'event_id': '0', 'group_id': '0', 'weights': {'nominal': weight}, 'native_identity': identity}
    rows = []

    def add(phase, data):
        rows.append({'event': 1, 'seq': len(rows) + 2, 'phase': phase, 'data': data})
    add('start', identity)
    add('pre_jvt', jets)
    for j in jets:
        add('jvt', {'jet': j, 'draw': .1, 'eff': .9})
    add('objects', {'jets': jets, 'muons': []})
    for i, j in enumerate(jets):
        add('tag', {'jet': j, 'draw': .1 if i < b else .99, 'eff77': .77, 'eff60': .6, 'eff70': .7})
    add('tagged_objects', {'bjets': jets[:b], 'nonbjets': jets[b:]})
    if kind != 'selected':
        add('veto', kind)
        return event, rows
    add('pairing_candidates', jets[:6])
    add('pairing', {'permutation': [0, 1, 2, 3, 4, 5], 'objective': 10.})
    features = {k: ci.cast(10 + i * .25, 'float32') for i, k in enumerate(FEATURES)}
    add('features', features)
    parity = 'odd' if number > 0 and number % 2 else 'even'
    for f in FAMILIES:
        c = contracts[f + '.' + parity]
        add('features/' + f, {x['id']: features[x['id']] for x in c['features']})
    for f in FAMILIES:
        c = contracts[f + '.' + parity]
        values = ci.prepare_features(c, {x['id']: features[x['id']] for x in c['features']})['values']
        add('input/' + f, values)
        add('output/' + f, [ci.cast(score, 'float32')])
    add('selected', {'b': min(6, b), 'triggerfrac': ci.cast((81.7 + 44.3) / 126., 'float32'),
                     'labels': labels or ['0.5', '0.5', '0.5']})
    return event, rows


def six_b_log(manifest, census, allrows):
    result = [{'seq': 1, 'event': 0, 'phase': 'header', 'data': manifest['header']}]
    for i, rows in enumerate(allrows, 1):
        for r in rows:
            result.append({**r, 'event': i, 'seq': len(result) + 1})
    sumw = math.fsum(e['weights']['nominal'] for e in census)
    result.append({'seq': len(result) + 1, 'event': len(census), 'phase': 'normalization',
                   'data': {'events': len(census), 'weight_index': 0, 'weight_name': '', 'sumW': sumw,
                            'cross_section_pb': 1., 'scale_factor': 126000 / sumw}})
    return ('unrelated native stdout\n' + '\n'.join(manifest['prefix'] + json.dumps(r) for r in result) + '\n').encode()


def consume(sixb, events):
    descriptor, contracts = sixb
    census = [e for e, _ in events]
    for i, e in enumerate(census):
        e['event_id'] = str(i)
        e['group_id'] = str(i // 2)
    raw = six_b_log(descriptor['trace'], census, [r for _, r in events])
    return hr.consume(raw, census, contracts, descriptor['trace'])


def test_six_b_package_pins_and_source_edit_ledger_are_exact():
    descriptor = sa.six_b_descriptor()
    source = (sa.SIXB / 'source/routine.cc').read_bytes()
    assert hashlib.sha256(source).hexdigest() == descriptor['instrumentation']['source_sha256']
    generated, edits = nt.instrument(source, descriptor['instrumentation'])
    assert len(edits) == len(descriptor['instrumentation']['edits']) and generated != source
    contracts = sa.six_b_contracts()
    assert set(contracts) == {f + '.' + p for f in FAMILIES for p in ('even', 'odd')}
    for key, row in descriptor['models'].items():
        model = Path(contracts[row['contract']]['model']['path'])
        assert model.is_file() and sha(model) == contracts[row['contract']]['model']['sha256']
        assert row['filename'] == descriptor['routine'] + '-' + key + '.onnx'
    # per-family feature records carry exactly the ten inputs each source model names
    for f in FAMILIES:
        assert 'features/' + f in [p['phase'] for p in descriptor['trace']['event_paths'][1]['phases']]
    with pytest.raises(nt.ResponseInputError):
        nt.instrument(source + b'\n', descriptor['instrumentation'])


def test_six_b_prepare_source_through_the_ordinary_adapter(tmp_path):
    task = sa.six_b_prepare_input(tmp_path / 'input')
    result = ar.run(task, tmp_path, tmp_path / 'prepared')
    assert result['status'] == 'passed'
    assert result['original_routine'] == sa.six_b_descriptor()['routine']
    assert result['routine'] == sa.six_b_descriptor()['instrumented_routine']
    with pytest.raises(sa.AssetError):
        sa.six_b_prepare_input(tmp_path / 'input')


def test_six_b_full_population_native_semantics(sixb):
    events = []
    for i, kind in enumerate((*VETOES, 'selected', 'selected', 'selected')):
        events.append(six_b_event(sixb, kind, b=4 + (i - 5) % 3, number=0 if i == 5 else -3 if i == 6 else i + 1,
                                  weight=-.25 if i == 6 else 1.))
    result = consume(sixb, events)
    assert result['events'] == 8
    assert [x['disposition'] for x in result['event_details']] == ['vetoed'] * 5 + ['selected'] * 3
    dests = result['destinations']
    for x, reason in zip(result['event_details'][:5], VETOES):
        marks = x['allocation']
        assert sum(marks) == 1 and marks[dests.index('rejected/' + reason)] == 1
    # parity follows C++ remainder semantics: zero and negative numbers use the even models
    assert [[c['model'] for c in x['feature_checks']][:1] for x in result['event_details'][5:]] == [['res.even']] * 3
    assert all(len(x['feature_checks']) == 3 for x in result['event_details'][5:])
    assert result['event_details'][5]['allocation'][dests.index('res/4b/0.5')] == 1.0
    assert result['event_details'][6]['allocation'][dests.index('nonres/5b/0.5')] == 1.0
    assert result['physics_validated'] is False


def test_six_b_odd_event_number_selects_the_odd_models(sixb):
    result = consume(sixb, [six_b_event(sixb, 'selected', b=4, number=7)])
    assert [c['model'] for c in result['event_details'][0]['feature_checks']] == ['res.odd', 'nonres.odd', 'heavyres.odd']


def test_six_b_event_with_no_preselected_jet_is_a_complete_veto(sixb):
    event = six_b_event(sixb, 'four_jets', jets=[])
    result = consume(sixb, [event])
    assert result['event_details'][0]['disposition'] == 'vetoed'
    assert result['event_details'][0]['allocation'][result['destinations'].index('rejected/four_jets')] == 1


@pytest.mark.parametrize('change', ['wrong_reason', 'wrong_label', 'wrong_triggerfrac', 'wrong_bcount', 'wrong_draw',
                                    'foreign_jet', 'pair_permutation', 'feature_float64', 'missing_record', 'extra_feature'])
def test_six_b_adverse_traces_refuse(sixb, change):
    kind = 'six_jets' if change == 'wrong_reason' else 'selected'
    event, rows = six_b_event(sixb, kind)
    rows = copy.deepcopy(rows)
    pick = lambda phase: next(r for r in rows if r['phase'] == phase)  # noqa: E731
    if change == 'wrong_reason':
        pick('veto')['data'] = 'trigger'
    elif change == 'wrong_label':
        pick('selected')['data']['labels'][0] = '0.7'
    elif change == 'wrong_triggerfrac':
        pick('selected')['data']['triggerfrac'] = .5
    elif change == 'wrong_bcount':
        pick('selected')['data']['b'] = 5
    elif change == 'wrong_draw':
        pick('jvt')['data']['draw'] = 1.
    elif change == 'foreign_jet':
        pick('tag')['data']['jet'] = jet(7.)
    elif change == 'pair_permutation':
        pick('pairing')['data']['permutation'] = [0, 0, 2, 3, 4, 5]
    elif change == 'feature_float64':
        pick('features')['data']['mH1'] = 10.1
    elif change == 'missing_record':
        rows.remove(pick('pairing'))
    elif change == 'extra_feature':
        pick('features/res')['data']['extra'] = 1.
    with pytest.raises((ValueError, KeyError, IndexError)):
        consume(sixb, [(event, rows)])


# ---------------------------------------------------------------- native fill schemas

def _block(path, edges):
    return f'BEGIN YODA_ESTIMATE1D_V3 {path}\nEdges(A1): {json.dumps(edges)}\n---\nEND YODA_ESTIMATE1D_V3\n\n'


@pytest.fixture()
def fabricated_prefix(tmp_path, monkeypatch):
    """Fabricated routine sources and reference files under a fake prefix, with a descriptor copy pinning them."""
    descriptors = json.loads((sa.ASSETS / 'group-fills/descriptors.json').read_bytes())
    prefix = tmp_path / 'prefix'
    (prefix / 'share/Rivet').mkdir(parents=True)
    (prefix / 'include/Rivet/Math').mkdir(parents=True)
    units = prefix / 'include/Rivet/Math/Units.hh'
    units.write_text('constexpr double gigaelectronvolt = 1.;\nconstexpr double GeV = gigaelectronvolt;\n')
    descriptors['units_header']['accepted_sha256'] = [sha(units)]
    for routine, row in descriptors['routines'].items():
        source = prefix / row['source']
        source.write_text('// fabricated source\n' + '\n'.join(site['anchor'] for site in row['sites']) + '\n')
        row['source_sha256'] = sha(source)
        references = {}
        for out in row['outputs']:
            for mode in (row['modes'] or {None: {}}):
                alias = row['alias'].format(routine=routine, mode=mode)
                args = {'alias': alias, 'routine': routine, **(row['modes'].get(mode, {}) if mode else {})}
                references[out['reference'].format(**args)] = [0., 1., 2.]
        reference = prefix / row['reference']
        reference.write_bytes(gzip.compress(''.join(_block('/REF' + name, edges) for name, edges in references.items()).encode()))
        row['reference_sha256'] = sha(reference)
    assets = tmp_path / 'assets'
    (assets / 'group-fills').mkdir(parents=True)
    (assets / 'group-fills/descriptors.json').write_text(json.dumps(descriptors))
    for item in descriptors['naming_sources']:
        target = assets / item['package_path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(sa.ASSETS / item['package_path'], target)
    monkeypatch.setattr(sa, 'ASSETS', assets)
    return prefix


def schema_contract(contract):
    return {**contract, 'schema_version': 2, 'group_rule': 'independent_single_subevent', 'native_weight_cap': 0}


def _cases():
    """(routine, mode, expected native-object count for two weight streams) for every shipped routine."""
    descriptors = json.loads((sa.ASSETS / 'group-fills/descriptors.json').read_bytes())['routines']
    cases = []
    for routine, row in sorted(descriptors.items()):
        for mode in (row['modes'] or {None: {}}):
            outputs = len(row['outputs'])
            per_weight = 2 * outputs + 1 + (8 if row['modes'] and row['modes'][mode].get('ancillary') else 0)
            cases.append((routine, mode, 1 + 2 * per_weight))
    return cases


def test_every_shipped_routine_and_mode_is_covered():
    assert sorted({r for r, _, _ in _cases()}) == sa.group_fill_routines() and len(_cases()) == 4
    assert sorted(c for _, _, c in _cases()) == [11, 19, 35, 51]


@pytest.mark.parametrize('routine,mode,count', _cases())
def test_group_fill_contracts_are_valid_fill_schemas(fabricated_prefix, routine, mode, count):
    contract = sa.group_fill_contract(routine, rivet_prefix=fabricated_prefix, mode=mode, weight_suffixes=('', '[up]'))
    schema = fills.fill_schema(schema_contract(contract))
    assert len(schema['native_object_paths']) == count
    assert all(o['edges'] == [0., 1., 2.] and o['unit'] == '1' for o in schema['outputs'])
    assert contract['original_source_sha256'] == schema['source']['sha256']
    assert bool(schema['sources']) == (mode is not None)
    assert [s['id'] for s in schema['sites']] == sorted(s['id'] for s in schema['sites'])
    assert {o['site'] for o in schema['outputs']} == {s['id'] for s in schema['sites']}


def test_group_fill_refuses_modes_and_changed_bytes(fabricated_prefix):
    moded = next(r for r, m, _ in _cases() if m is not None)
    plain = next(r for r, m, _ in _cases() if m is None)
    with pytest.raises(sa.AssetError, match='mode'):
        sa.group_fill_contract(moded, rivet_prefix=fabricated_prefix)
    with pytest.raises(sa.AssetError, match='missing|no shipped'):
        sa.group_fill_contract('NOT_A_ROUTINE', rivet_prefix=fabricated_prefix)
    row = json.loads((sa.ASSETS / 'group-fills/descriptors.json').read_bytes())['routines'][plain]
    source = fabricated_prefix / row['source']
    source.write_text(source.read_text() + '// changed\n')
    with pytest.raises(sa.AssetError, match='differ'):
        sa.group_fill_contract(plain, rivet_prefix=fabricated_prefix)


@pytest.mark.skipif(not RIVET_PREFIX, reason='RAVEL_TEST_RIVET_PREFIX names no installed Rivet 4.1.4 prefix')
@pytest.mark.parametrize('routine,mode', [(r, m) for r, m, _ in _cases()])
def test_group_fill_contracts_bind_to_the_released_routines(routine, mode):
    contract = sa.group_fill_contract(routine, rivet_prefix=RIVET_PREFIX, mode=mode)
    fills.fill_schema(schema_contract(contract))


# ---------------------------------------------------------------- response contract and cutflow

def test_response_contract_matches_the_direct_lepton_semantics():
    shipped, reference = sa.response_contract(), response_fixture.contract()
    different = {k for k in shipped if shipped[k] != reference[k]}
    assert different == {'study_id', 'parameter_grid', 'datasets', 'origin_labels'}
    assert shipped['origin_labels'] == {'direct': 'direct_slepton', 'descendant': 'other_slepton_descendant',
                                        'other': 'other_origin'}
    assert sa.response_contract(four_state=False)['topology'] == []
    truth.response_contract(sa.response_contract(study={'study_id': 's', 'parameter_grid': [], 'datasets': ['d'],
                                                         'output': {'stem': 'x', 'formats': ['json']}}))


def test_response_contract_classifies_a_direct_pair():
    def particle(pid, uid, mother=-1, status=1):
        return dict(pid=pid, uid=uid, m1=mother, m2=-1, status=status, pt=6., eta=.2, phi=.1, energy=6.)
    particles = [particle(1000011, 900, status=22), particle(-1000011, 200, status=22), particle(11, 37, 0),
                 particle(-11, 89, 1), particle(1000022, 56, 0), particle(1000022, 99, 1)]
    event = dict(source_entry=0, event_number=41, weight=1., particles=particles,
                 reco=[dict(index=0, flavour='electron', ref=37, pt=7., eta=.3, phi=.1)])
    row = truth.analyze_event(event, contract=sa.response_contract())
    assert [p['particle_uid'] for p in row['direct_particles']] == [37, 89]
    assert row['topology_violations'] == []


def test_cutflow_definition_binds_the_producer_bytes(tmp_path):
    from ravel.physics import compressed_validation as cv
    producer = tmp_path / 'selection.py'
    producer.write_text('# fictional selected predicate producer\n')
    pin = sa.cutflow_definition(producer, tmp_path / 'definition')
    definition = cv.bind(pin)
    value = definition.value
    assert definition.sources[value['selection_source']] == producer.read_bytes()
    assert set(value['flows']) == {'high', 'low'} and value['references'] == []
    assert all(r.startswith('SR_S_') for m in value['membership'] for r in m['regions'])
    assert set(value['unavailable']) <= set(value['predicates'])
    event = definition.new_event(1, 1.0)
    assert set(event['predicates']) == set(value['predicates'])
    with pytest.raises(sa.AssetError):
        sa.cutflow_definition(producer, tmp_path / 'definition')


# ---------------------------------------------------------------- published SFitter records

def _zip_root(tmp_path):
    root = tmp_path / 'source'
    with zipfile.ZipFile(SFITTER_ZIP) as archive:
        archive.extractall(root)
    return root


def _localized_records(tmp_path, root, monkeypatch):
    """Copy the shipped records with each source pin rebound to the archive's bytes.

    The release archive in the test fixtures is a generalized copy: two source files differ
    from the pinned upstream bytes. The control exercises the record machinery on it; the
    exact-byte pins are exercised against the upstream tree when ``RAVEL_TEST_SFITTER_SOURCE``
    names it."""
    shipped = tmp_path / 'records'
    shutil.copytree(published.DIRECTORY, shipped)
    for registry in shipped.glob('*.defect-registry.json'):
        value = json.loads(registry.read_text())
        for pin in value['sources'].values():
            target = root / pin['path']
            if target.is_file():
                pin['sha256'] = sha(target)
        registry.write_text(json.dumps(value))
    for manifest in shipped.glob('*.repair-manifest.json'):
        value = json.loads(manifest.read_text())
        for pin in value['sources'].values():
            target = root / pin['path']
            if target.is_file():
                pin['sha256'] = sha(target)
        value['defect_registry']['sha256'] = sha(shipped / value['defect_registry']['path'])
        manifest.write_text(json.dumps(value))
    monkeypatch.setattr(published, 'DIRECTORY', shipped)
    return shipped


def test_published_records_name_the_three_released_cards():
    cards = published.cards()
    assert set(cards) == {'Top_Full.json', 'Higgs_Full.json', 'Higgs_Full_with_CtG.json'}
    index = json.loads((published.DIRECTORY / 'index.json').read_text())
    assert index['source_commit'] == '6072a79e0f132d61a927f11ed482a401b34f6e3f'
    upstream = json.loads((REPO / 'src/ravel/data/sfitter/upstream-source.json').read_text())['files']
    for name, pin in cards.items():
        assert upstream[pin['path']] == pin['sha256']
    for path in published.DIRECTORY.glob('*.json'):
        if path.name == 'index.json':
            continue
        value = json.loads(path.read_text())
        assert value['review']['evidence'][0]['sha256'] == sha(published.DIRECTORY / 'review-note.md')
        assert 'physicist review' in value['review']['reviewer']
        for pin in value['sources'].values():
            if pin['path'] in upstream:
                assert upstream[pin['path']] == pin['sha256']


def test_published_records_refuse_card_bytes_that_differ(tmp_path):
    root = _zip_root(tmp_path)
    with pytest.raises(records.SourceRecordError) as caught:
        published.bind(root, 'Higgs_Full.json', tmp_path / 'bound')
    assert caught.value.reason == 'source_scope_mismatch'
    with pytest.raises(records.SourceRecordError) as caught:
        published.bind(root, 'NotACard.json', tmp_path / 'bound2')
    assert caught.value.reason == 'missing_repair_manifest'


def test_top_card_derivation_from_shipped_records(tmp_path, monkeypatch):
    root = _zip_root(tmp_path)
    _localized_records(tmp_path, root, monkeypatch)
    original = json.loads((root / 'sfitter/data/Top_Full.json').read_bytes())
    card, proof = published.derive(root, 'Top_Full.json', tmp_path / 'bound')
    assert len(card['observations']) == 52 and proof['original_bins'] == proof['derived_bins'] == 110
    assert sum(len(p['modifiers']) for p in original['predictions']) - sum(len(p['modifiers']) for p in card['predictions']) == 2
    # the earlier-card measurement replaces the mispaired row, and the dropped-D token is restored
    assert card['observations'][1]['Meas']['data'] != original['observations'][1]['Meas']['data']
    assert [m['name'] for m in card['predictions'][3]['modifiers']].count('D6qq18xD6qt8') == 1
    for row in (13, 27):
        names = [m['name'] for m in card['predictions'][row]['modifiers']]
        assert names.count('D6qt1xD6qt1') == 1
        winner = next(m for m in card['predictions'][row]['modifiers'] if m['name'] == 'D6qt1xD6qt1')
        assert winner['data'] == [0.]
    assert card['observations'][15]['Meas']['modifiers'][7] == original['observations'][15]['Meas']['modifiers'][7]
    # lineage keeps every original row and the retained unused nuisance is a reviewed placement
    assert [r['original_indices'] for r in proof['rows']] == [[i] for i in range(52)]
    assert proof['physics_validated'] is False and proof['scientific_card_review'] == 'required_separately'
    index = json.loads((published.DIRECTORY / 'index.json').read_text())['cards']['Top_Full.json']
    assert support.fingerprint(original) == index['original_fingerprint']
    assert support.fingerprint(card) == index['derived_fingerprint']
    bound = published.bind(root, 'Top_Full.json', tmp_path / 'bound-again')
    reviewed = support.inspect(root, card, bound['defect_registry'])
    placements = reviewed['scientific_input_support']['nuisance_placements']
    assert len(placements) == 1 and placements[0]['native_disposition'] == 'retained_unused'
    kinds = {a['kind'] for a in reviewed['native_law_assumptions']}
    assert kinds == {'unresolved_released_top_coefficient_intent', 'unresolved_released_top_uncertainty_placement_intent'}


@pytest.mark.skipif(not UPSTREAM, reason='RAVEL_TEST_SFITTER_SOURCE names no exact upstream tree')
def test_exact_upstream_bytes_derive_top_and_hold_both_higgs_cards(tmp_path):
    root = Path(UPSTREAM)
    card, proof = published.derive(root, 'Top_Full.json', tmp_path / 'top')
    assert proof['original_bins'] == 110 and len(card['observations']) == 52
    for name in ('Higgs_Full.json', 'Higgs_Full_with_CtG.json'):
        with pytest.raises(support.HiggsInputSupportError) as caught:
            published.derive(root, name, tmp_path / name)
        holds = caught.value.support['scientific_input_holds']
        assert [h['id'] for h in holds] == ['SFITTER-HIGGS5019-RESPONSE']
        assert caught.value.support['scientific_input_support']['input_disposition'] == 'held_source_defect'
        assert set(caught.value.support['scientific_input_support']['native_production_scaling']) >= {'weights'}


@pytest.mark.skipif(not UPSTREAM, reason='RAVEL_TEST_SFITTER_SOURCE names no exact upstream tree')
def test_exact_upstream_coalescence_applies_only_with_a_supplied_resolution(tmp_path, monkeypatch):
    """The 1801 coalescence is real source repair; the hold stays until evidence resolves it."""
    root = Path(UPSTREAM)
    name = 'Higgs_Full.json'
    bound = published.bind(root, name, tmp_path / 'bound')
    registry_path = Path(bound['defect_registry']['path'])
    registry = json.loads(registry_path.read_text())
    original = json.loads((root / 'sfitter/data' / name).read_bytes())
    registry['resolutions'] = [{'defect_id': 'SFITTER-HIGGS5019-RESPONSE',
                                'input_fingerprint': support.fingerprint(original), 'evidence': ['card'],
                                'disposition': 'resolved'}]
    registry_path.write_text(json.dumps(registry))
    manifest_path = Path(bound['repair_manifest']['path'])
    manifest = json.loads(manifest_path.read_text())
    manifest['defect_registry'] = {'path': str(registry_path), 'sha256': sha(registry_path)}
    # Test-only mechanics: a real resolution needs authenticated response evidence. This
    # fictional name replacement stands in for it so the shipped coalescence executes.
    row = original['predictions'][197]
    manifest['transforms'].insert(0, {'operation': 'replace', 'path': '/predictions/197/name',
                                      'expected': row['name'], 'value': original['observations'][197]['name']})
    manifest_path.write_text(json.dumps(manifest))
    pin = {'path': str(manifest_path), 'sha256': sha(manifest_path)}
    card, proof = derivation.derive(root, 'sfitter/data/' + name, pin)
    assert len(card['observations']) == len(original['observations']) - 1
    assert proof['rows'][0]['original_indices'] == [0, 276]


# ---------------------------------------------------------------- coalescence of numerically identical rows

@pytest.mark.parametrize('spelling,coalesces', [(1, True), (2., False)])
def test_coalescence_joins_numeric_spellings_of_one_record_only(tmp_path, spelling, coalesces):
    """Rows that differ only in the literal spelling of a number (1 and 1.0) are one record."""
    from source_record_fixtures import defect_registry, reviewed, write
    card = {'observations': [{'ID': 'r0', 'name': 'n0', 'Meas': {'data': [1.]}},
                             {'ID': 'r1', 'name': 'n1', 'Meas': {'data': [2.]}},
                             {'ID': 'r0', 'name': 'n0', 'Meas': {'data': [spelling]}}],
            'predictions': [{'ID': 'r0', 'name': 'n0', 'data': [1.], 'modifiers': []},
                            {'ID': 'r1', 'name': 'n1', 'data': [2.], 'modifiers': []},
                            {'ID': 'r0', 'name': 'n0', 'data': [1], 'modifiers': []}]}
    path = tmp_path / 'card.json'
    pin = write(path, card)
    registry = defect_registry(tmp_path, card)
    context = {'identity': 'ANA-0001', 'card_output': 'derived.json', 'output_format': 'json'}
    manifest = reviewed(tmp_path, 'repair-manifest', {'card': pin}, context=context, card_source='card',
                        defect_registry=registry, identity_template='{identity}__row{row}',
                        transforms=[{'operation': 'coalesce', 'path': '/observations', 'keep': 0, 'remove': 2}])
    manifest_pin = write(tmp_path / 'repairs.json', manifest)
    if coalesces:
        derived, proof = derivation.derive(tmp_path, path.name, manifest_pin)
        assert len(derived['observations']) == 2 and proof['rows'][0]['original_indices'] == [0, 2]
    else:
        with pytest.raises(records.SourceRecordError):
            derivation.derive(tmp_path, path.name, manifest_pin)
