"""Branch-map adapter: flat reco ntuples -> native SimpleAnalysis routine ports."""
import json
from pathlib import Path

import numpy as np
import pytest

ak = pytest.importorskip('awkward')
uproot = pytest.importorskip('uproot')

from ravel.physics import reco_ntuple_routine as rn, sa_native_core as core
from ravel.physics.analysis_packages import load_routine
from analysis_package_fixtures import selected_manifest
zl = load_routine(selected_manifest('selection-b'))

@pytest.fixture(autouse=True)
def supplied_registry(tmp_path, monkeypatch):
    from analysis_package_fixtures import qualify_fixture
    selected = qualify_fixture(tmp_path, selected_manifest('selection-b'))
    monkeypatch.setenv('RAVEL_ANALYSIS_PACKAGES', str(selected.parent))


DESCRIPTOR = {
    'schema_version': 1, 'kind': 'reco-ntuple-format', 'tree': 'analysis', 'energy_unit': 'MeV',
    'event_number': 'eventNumber', 'weights': ['mcEventWeight', 'pileupWeight'], 'sort_by_pt': True,
    'collections': {
        'electron': {'pt': 'el_pt', 'eta': 'el_eta', 'phi': 'el_phi', 'charge': 'el_charge', 'mass': None,
                     'require': ['el_select_baseline'], 'default_bits': [],
                     'id_bits': [{'flag': 'el_select_baseline', 'bits': ['ELooseLH', 'ED0Sigma5', 'EZ05mm']},
                                 {'flag': 'el_select_tight', 'bits': ['ETightLH', 'EMediumLH', 'EIsoFixedCutTight']}]},
        'muon': {'pt': 'mu_pt', 'eta': 'mu_eta', 'phi': 'mu_phi', 'charge': 'mu_charge', 'mass': None,
                 'require': [], 'default_bits': ['MuMedium', 'MuD0Sigma3', 'MuZ05mm'], 'id_bits': []},
        'jet': {'pt': 'jet_pt', 'eta': 'jet_eta', 'phi': 'jet_phi', 'charge': None, 'mass': 'jet_m',
                'require': [], 'default_bits': [], 'id_bits': [{'flag': 'jet_select_btag', 'bits': ['BTag77MV2c20']},
                                                               {'flag': 'jet_select_clean', 'bits': ['LooseBadJet']}]}},
    'met': {'px': 'met_px', 'py': 'met_py'}}


def synthetic(n=300, seed=7):
    """Random events; every third one is a hard two-jet, large missing-momentum event."""
    rng = np.random.default_rng(seed)
    rows = {k: [] for k in ('jet_pt', 'jet_eta', 'jet_phi', 'jet_m', 'jet_select_btag', 'jet_select_clean',
                            'el_pt', 'el_eta', 'el_phi', 'el_charge', 'el_select_baseline', 'el_select_tight',
                            'mu_pt', 'mu_eta', 'mu_phi', 'mu_charge')}
    met_px, met_py = [], []
    for i in range(n):
        hard = i % 3 == 0
        nj = 2 + rng.integers(0, 3) if hard else rng.integers(0, 8)
        ne = 0 if hard else rng.integers(0, 3)
        nm = 0 if hard else rng.integers(0, 2)
        met_phi = rng.uniform(-np.pi, np.pi)
        met = rng.uniform(900e3, 1400e3) if hard else abs(rng.normal(0, 600e3))
        met_px.append(met * np.cos(met_phi)); met_py.append(met * np.sin(met_phi))
        jpt = rng.uniform(300e3, 900e3, nj) if hard else rng.uniform(20e3, 1500e3, nj)
        jphi = (met_phi + np.pi + rng.uniform(-0.6, 0.6, nj)) if hard else rng.uniform(-np.pi, np.pi, nj)
        rows['jet_pt'].append(jpt); rows['jet_eta'].append(rng.uniform(-1.0, 1.0, nj) if hard else rng.uniform(-3, 3, nj))
        rows['jet_phi'].append((jphi + np.pi) % (2 * np.pi) - np.pi); rows['jet_m'].append(rng.uniform(0, 50e3, nj))
        rows['jet_select_btag'].append(rng.integers(0, 2, nj).astype(np.int8))
        rows['jet_select_clean'].append((rng.uniform(0, 1, nj) > (0.0 if hard else 0.2)).astype(np.int8))
        rows['el_pt'].append(rng.uniform(5e3, 300e3, ne)); rows['el_eta'].append(rng.uniform(-2.6, 2.6, ne))
        rows['el_phi'].append(rng.uniform(-np.pi, np.pi, ne)); rows['el_charge'].append(rng.choice([-1.0, 1.0], ne))
        rows['el_select_baseline'].append(rng.integers(0, 2, ne).astype(np.int8))
        rows['el_select_tight'].append(rng.integers(0, 2, ne).astype(np.int8))
        rows['mu_pt'].append(rng.uniform(5e3, 200e3, nm)); rows['mu_eta'].append(rng.uniform(-2.8, 2.8, nm))
        rows['mu_phi'].append(rng.uniform(-np.pi, np.pi, nm)); rows['mu_charge'].append(rng.choice([-1.0, 1.0], nm))
    flat = {k: ak.Array([list(v) for v in values]) for k, values in rows.items()}
    for key in ('jet_select_btag', 'jet_select_clean', 'el_select_baseline', 'el_select_tight'):
        flat[key] = ak.values_astype(flat[key], np.int8)
    flat.update({'met_px': np.array(met_px), 'met_py': np.array(met_py),
                 'mcEventWeight': rng.choice([1.5, -0.5, 2.0], n), 'pileupWeight': rng.uniform(0.8, 1.2, n),
                 'eventNumber': np.arange(1000, 1000 + n, dtype=np.int64)})
    return flat


def write_flat(path, flat):
    with uproot.recreate(path) as f:
        f['analysis'] = flat


def bits(names):
    value = 0
    for name in names:
        value |= getattr(core, name)
    return value


def write_reference(path, flat):
    """The same events written directly in the routine's own input layout (GeV, sorted)."""
    el_keep = flat['el_select_baseline'] != 0
    el_bits = (ak.where(flat['el_select_baseline'] != 0, bits(['ELooseLH', 'ED0Sigma5', 'EZ05mm']), 0)
               | ak.where(flat['el_select_tight'] != 0, bits(['ETightLH', 'EMediumLH', 'EIsoFixedCutTight']), 0))
    def sort(fields, keep=None):
        if keep is not None:
            fields = {k: v[keep] for k, v in fields.items()}
        order = ak.argsort(fields['pt'], ascending=False, stable=True)
        return {k: v[order] for k, v in fields.items()}
    el = sort({'pt': flat['el_pt'] / 1e3, 'eta': flat['el_eta'], 'phi': flat['el_phi'], 'charge': flat['el_charge'],
               'id': ak.values_astype(el_bits, np.int64)}, el_keep)
    mu = sort({'pt': flat['mu_pt'] / 1e3, 'eta': flat['mu_eta'], 'phi': flat['mu_phi'], 'charge': flat['mu_charge'],
               'id': ak.values_astype(ak.zeros_like(flat['mu_pt']), np.int64) + bits(['MuMedium', 'MuD0Sigma3', 'MuZ05mm'])})
    jet = sort({'pt': flat['jet_pt'] / 1e3, 'eta': flat['jet_eta'], 'phi': flat['jet_phi'], 'm': flat['jet_m'] / 1e3,
                'id': ak.values_astype(ak.where(flat['jet_select_btag'] != 0, bits(['BTag77MV2c20']), 0)
                                       | ak.where(flat['jet_select_clean'] != 0, bits(['LooseBadJet']), 0), np.int64)})
    w = flat['mcEventWeight'] * flat['pileupWeight']
    tree = {'Event': flat['eventNumber'], 'met_pt': np.hypot(flat['met_px'], flat['met_py']) / 1e3,
            'met_phi': np.arctan2(flat['met_py'], flat['met_px']), 'mcWeights': ak.unflatten(w, np.ones(len(w), dtype=np.int64))}
    for prefix, fields in (('el', el), ('mu', mu), ('jet', jet)):
        for key, values in fields.items():
            tree[f'{prefix}_{key}'] = values
    with uproot.recreate(path) as f:
        f['ntuple'] = tree


@pytest.fixture
def ntuple(tmp_path):
    flat = synthetic()
    write_flat(tmp_path / 'flat.root', flat)
    (tmp_path / 'format.json').write_text(json.dumps(DESCRIPTOR))
    return tmp_path, flat


def task(**changes):
    value = {'descriptor': 'format.json', 'ntuples': ['flat.root'], 'routine': zl.NAME, 'max_events': None}
    value.update(changes)
    return value


def test_mapped_ntuple_reproduces_native_path_on_reference_layout(ntuple, tmp_path):
    root, flat = ntuple
    write_reference(tmp_path / 'reference.root', flat)
    expected = core.run_counting_routine(zl, str(tmp_path / 'reference.root'), str(tmp_path / 'ref-out'))
    result = rn.run(task(), root, tmp_path / 'out')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    assert {r['id']: r['raw'] for r in result['regions']} == expected
    assert sum(expected.values()) > 0  # the fixture actually populates regions
    assert (tmp_path / 'out' / (zl.NAME + '.txt')).read_text() == (tmp_path / 'ref-out' / (zl.NAME + '.txt')).read_text()


def test_weights_are_products_of_named_branches_and_signed(ntuple):
    root, flat = ntuple
    result = rn.run(task(), root, None)
    w = np.asarray(flat['mcEventWeight']) * np.asarray(flat['pileupWeight'])
    assert result['sum_weights_read'] == pytest.approx(float(w.sum()))
    assert result['events_read'] == 300


def test_max_events_and_multiple_files(ntuple, tmp_path):
    root, flat = ntuple
    write_flat(root / 'flat2.root', synthetic(n=50, seed=9))
    assert rn.run(task(ntuples=['flat.root', 'flat2.root']), root, None)['events_read'] == 350
    assert rn.run(task(ntuples=['flat.root', 'flat2.root'], max_events=320), root, None)['events_read'] == 320


def test_conversion_sorts_scales_and_maps_bits(ntuple):
    root, flat = ntuple
    table = rn.read(DESCRIPTOR, [root / 'flat.root'])
    arrays, weight, events = rn.convert(DESCRIPTOR, table)
    for i in range(20):
        pts = arrays['jet_pt'][i]
        assert list(pts) == sorted(pts, reverse=True)
        assert all(p < 2000 for p in pts)  # GeV
        for b in arrays['jet_id'][i]:
            assert b & ~(core.BTag77MV2c20 | core.LooseBadJet) == 0
    assert all(len(arrays['el_pt'][i]) == int(np.sum(np.asarray(flat['el_select_baseline'][i]) != 0)) for i in range(50))


@pytest.mark.parametrize('change', ['unknown-bit', 'no-weights', 'no-jet-mass', 'bad-unit', 'bad-met'])
def test_descriptor_refusals(change):
    d = json.loads(json.dumps(DESCRIPTOR))
    if change == 'unknown-bit':
        d['collections']['jet']['id_bits'][0]['bits'] = ['NotARealBit']
    if change == 'no-weights':
        d['weights'] = []
    if change == 'no-jet-mass':
        d['collections']['jet']['mass'] = None
    if change == 'bad-unit':
        d['energy_unit'] = 'TeV'
    if change == 'bad-met':
        d['met'] = {'pt': 'met'}
    with pytest.raises(ValueError):
        rn.validate_descriptor(d)


def test_missing_branch_is_named(ntuple):
    root, _ = ntuple
    d = json.loads(json.dumps(DESCRIPTOR))
    d['collections']['muon']['pt'] = 'muon_pt_typo'
    (root / 'format.json').write_text(json.dumps(d))
    with pytest.raises(ValueError, match='muon_pt_typo'):
        rn.run(task(), root, None)


def test_registered_science_mode_and_inputs(ntuple):
    from ravel.workflow import science
    root, _ = ntuple
    assert 'reco-ntuple-routine' in science.MODES
    module = science.adapter({'mode': 'reco-ntuple-routine', 'task': task()})
    assert module is rn
    paths = rn.inputs(task(), root)
    assert paths[0] == root / 'format.json' and paths[1] == root / 'flat.root'
    with pytest.raises(ValueError):
        rn._routine('NoSuchRoutine')


def test_check_command_reports_missing_branches(ntuple, capsys):
    root, _ = ntuple
    assert rn.main(['check', '--descriptor', str(root / 'format.json'), '--ntuple', str(root / 'flat.root')]) == 0
    assert json.loads(capsys.readouterr().out)['ntuples'][0]['entries'] == 300


def test_lifecycle_input_inventory_and_review_policy(ntuple):
    from ravel.workflow import science
    root, _ = ntuple
    spec = {'mode': 'reco-ntuple-routine', 'task': task()}
    files = science.task_inputs(spec, root)
    assert (root / 'format.json').resolve() in files and (root / 'flat.root').resolve() in files
    assert science._new_capability(spec)  # needs a prospective version-2 review policy
