"""Object efficiencies applied to reconstructed collections before the selection."""
import json
import math

import numpy as np
import pytest

from columnar_fixtures import write_delphes
from ravel.physics.columnar import efficiency, engine, formats
from ravel.physics.columnar.recipe import compile_recipe

CARD = """
set ExecutionPath {
  PhotonEfficiency
  ElectronEfficiency
}
module Efficiency PhotonEfficiency {
  set InputArray Calorimeter/eflowPhotons
  set OutputArray photons
  # comment with a brace }
  set EfficiencyFormula {
    (pt <= 10.0) * (0.00) +
    (abs(eta) <= 2.5) * (pt > 10.0) * (0.95)
  }
}
module Efficiency ElectronEfficiency {
  set InputArray ElectronMomentumSmearing/electrons
  set EfficiencyFormula {1.0}
}
"""


def _photon(pt, eta=0.0, phi=0.0):
    return {'PT': pt, 'Eta': eta, 'Phi': phi, 'E': pt * math.cosh(eta), 'IsolationVar': 0.0}


def _electron(pt, eta=0.0, phi=0.0):
    return {'PT': pt, 'Eta': eta, 'Phi': phi, 'Charge': -1, 'IsolationVar': 0.0}


def _events(n, photons=(), electrons=()):
    return [{'Electron': [_electron(pt, phi=0.3 * k) for k, pt in enumerate(electrons)],
             'Muon': [], 'Jet': [], 'EFlowTrack': [],
             'Photon': [_photon(pt, phi=0.5 + 0.7 * k) for k, pt in enumerate(photons)],
             'MET': 50.0, 'METPhi': 0.0, 'Weight': 1.0} for _ in range(n)]


def _map(base, name='eff.json', values=(0.9, 0.5), semantics='absolute', **extra):
    (base / name).write_text(json.dumps({'axes': [{'name': 'transverse momentum', 'unit': 'GeV', 'edges': [0, 50, 1000]}],
                                         'values': list(values)}))
    return {'source': {'format': 'json-grid', 'path': name}, 'axes': [{'name': 'transverse momentum', 'unit': 'GeV'}],
            'out_of_range': 'refuse', 'citation': 'synthetic test map', 'semantics': semantics, **extra}


def _recipe(collection, source, application, region_cut, *, maps, max_objects=None, seed=None):
    step = {'name': 'identification', 'object': collection, 'map': 'id', 'coordinates': ['pt'],
            'application': application, 'card_efficiency': 'the synthetic sample was made without a detector card'}
    if max_objects is not None:
        step['max_objects'] = max_objects
    if seed is not None:
        step['seed'] = seed
    return {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'object efficiency test',
            'weights': {'generator': 'weight', 'factors': []}, 'efficiency_maps': maps,
            'objects': [{'name': collection, 'from': source, 'select': 'pt > 5'}, {'efficiency': step}],
            'observables': [{'name': 'n', 'op': 'count', 'collection': collection}],
            'regions': [{'name': 'selected', 'cuts': [{'name': 'selection', 'expr': region_cut}]}],
            'histograms': [{'name': 'multiplicity', 'region': 'selected', 'observable': 'n', 'edges': [0, 1, 2, 3],
                            'unit': '1', 'label': 'Number of objects', 'normalization': 'raw'}]}


def _run(base, events, doc, **compile_args):
    path = write_delphes(base / 'events.root', events)
    plan = compile_recipe(doc, formats.load_descriptor('delphes', base), base, **compile_args)
    partial = engine.analyse({'inputs': [{'path': str(path), 'file_index': 0}], 'chunk_size': 1000}, plan)
    return plan, partial['variations']['nominal']


def test_all_required_weight_gives_the_analytic_weight_sum(tmp_path):
    doc = _recipe('photons', 'Photon', 'all-required-weight', 'n >= 1', maps={'id': _map(tmp_path)})
    _, nominal = _run(tmp_path, _events(40, photons=[30.0]), doc)
    assert nominal['cutflows']['selected'][-1][1] == pytest.approx(40 * 0.9)


def test_a_veto_gains_acceptance_from_inefficiency_when_enumerated(tmp_path):
    doc = _recipe('electrons', 'Electron', 'enumerate', 'n == 0', maps={'id': _map(tmp_path, values=(0.7, 0.7))})
    _, nominal = _run(tmp_path, _events(25, electrons=[20.0]), doc)
    rows = nominal['cutflows']['selected']
    assert rows[0][0] == pytest.approx(25) and rows[0][1] == pytest.approx(25)
    assert rows[-1][1] == pytest.approx(25 * 0.3)
    assert rows[-1][0] == pytest.approx(25 * 0.3)  # expected raw count under enumeration
    assert nominal['events']['n'] == 25


def test_at_least_one_of_two_candidates(tmp_path):
    doc = _recipe('photons', 'Photon', 'enumerate', 'n >= 1', maps={'id': _map(tmp_path)})
    _, nominal = _run(tmp_path, _events(10, photons=[80.0, 30.0]), doc)
    assert nominal['cutflows']['selected'][-1][1] == pytest.approx(10 * (1 - 0.1 * 0.5))
    hist = nominal['histograms']['multiplicity']
    np.testing.assert_allclose(hist['sumw'], [0.0, 10 * (0.9 * 0.5 + 0.1 * 0.5), 10 * 0.45])


def test_bernoulli_selection_agrees_with_enumeration(tmp_path):
    maps = {'id': _map(tmp_path)}
    events = _events(3000, photons=[80.0, 30.0])
    _, exact = _run(tmp_path, events, _recipe('photons', 'Photon', 'enumerate', 'n == 1', maps=maps))
    (tmp_path / 'events.root').unlink()
    _, sampled = _run(tmp_path, events, _recipe('photons', 'Photon', 'select', 'n == 1', maps=maps, seed=11))
    p = exact['cutflows']['selected'][-1][1] / 3000
    assert p == pytest.approx(0.9 * 0.5 + 0.1 * 0.5)
    observed = sampled['cutflows']['selected'][-1][1] / 3000
    assert abs(observed - p) < 4 * math.sqrt(p * (1 - p) / 3000)


def test_enumeration_cap_is_enforced(tmp_path):
    doc = _recipe('photons', 'Photon', 'enumerate', 'n >= 1', maps={'id': _map(tmp_path)}, max_objects=1)
    with pytest.raises(ValueError, match='max_objects'):
        _run(tmp_path, _events(3, photons=[80.0, 30.0]), doc)
    with pytest.raises(ValueError, match='max_objects'):
        compile_recipe(_recipe('photons', 'Photon', 'enumerate', 'n >= 1', maps={'id': _map(tmp_path)}, max_objects=40),
                       formats.load_descriptor('delphes', tmp_path), tmp_path)


def test_plain_weight_application_is_refused(tmp_path):
    doc = _recipe('photons', 'Photon', 'weight', 'n >= 1', maps={'id': _map(tmp_path)})
    with pytest.raises(ValueError, match='all-required-weight'):
        compile_recipe(doc, formats.load_descriptor('delphes', tmp_path), tmp_path)


def test_card_guard_refuses_double_application_and_allows_conditional_stacking(tmp_path):
    (tmp_path / 'card.tcl').write_text(CARD)
    descriptor = formats.load_descriptor('delphes', tmp_path)
    absolute = _recipe('photons', 'Photon', 'enumerate', 'n >= 1', maps={'id': _map(tmp_path, card_modules=['PhotonEfficiency'])})
    with pytest.raises(ValueError, match='PhotonEfficiency'):
        compile_recipe(absolute, descriptor, tmp_path, detector_card=tmp_path / 'card.tcl')
    conditional = _recipe('photons', 'Photon', 'enumerate', 'n >= 1',
                          maps={'id': _map(tmp_path, semantics='conditional_on_reco', card_modules=['PhotonEfficiency'])})
    plan = compile_recipe(conditional, descriptor, tmp_path, detector_card=tmp_path / 'card.tcl')
    report = plan.card_report
    assert report['card']['sha256'] and report['maps']['id']['modules']['PhotonEfficiency']['trivial'] is False
    assert report['maps']['id']['decision'] == 'stacks on the card efficiency'
    # A trivial (unit) card efficiency does not double count.
    trivial = _recipe('electrons', 'Electron', 'enumerate', 'n >= 1', maps={'id': _map(tmp_path, card_modules=['ElectronEfficiency'])})
    assert compile_recipe(trivial, descriptor, tmp_path, detector_card=tmp_path / 'card.tcl').card_report['maps']['id']['decision'] == 'no double counting'
    # A conditional map needs the reconstruction efficiency it is conditional on.
    missing = _recipe('photons', 'Photon', 'enumerate', 'n >= 1',
                      maps={'id': _map(tmp_path, semantics='conditional_on_reco', card_modules=['MuonEfficiency'])})
    with pytest.raises(ValueError, match='MuonEfficiency'):
        compile_recipe(missing, descriptor, tmp_path, detector_card=tmp_path / 'card.tcl')


def test_map_semantics_and_percent_units(tmp_path):
    spec = _map(tmp_path, values=(90.0, 50.0))
    with pytest.raises(ValueError, match='percent'):
        efficiency.load_map('id', spec, tmp_path)
    with pytest.raises(ValueError, match='scale_factor'):
        efficiency.load_map('id', {**spec, 'allow_above_one': True}, tmp_path)
    scale = efficiency.load_map('id', {**_map(tmp_path, values=(1.02, 0.97)), 'semantics': 'scale_factor', 'allow_above_one': True}, tmp_path)
    assert scale.semantics == 'scale_factor'
    with pytest.raises(ValueError, match='semantics'):
        efficiency.load_map('id', {k: v for k, v in _map(tmp_path).items() if k != 'semantics'}, tmp_path)


def test_out_of_range_objects_are_counted(tmp_path):
    doc = _recipe('photons', 'Photon', 'enumerate', 'n >= 1', maps={'id': {**_map(tmp_path), 'out_of_range': 'zero'}})
    _, nominal = _run(tmp_path, _events(4, photons=[2000.0, 30.0]), doc)
    counts = nominal['efficiency']['identification']
    assert counts['objects'] == 8 and counts['axes']['transverse momentum']['zeroed'] == 4
    assert nominal['cutflows']['selected'][-1][1] == pytest.approx(4 * 0.9)


def test_yoda_scatter_maps(tmp_path):
    (tmp_path / 'eff.yoda').write_text("""
BEGIN YODA_SCATTER2D_V2 /REF/eff
Path: /REF/eff
Type: Scatter2D
---
# xval   xerr-   xerr+   yval   yerr-   yerr+
1.500000e+01 5.000000e+00 5.000000e+00 6.000000e-01 1.0e-02 1.0e-02
3.500000e+01 1.500000e+01 1.500000e+01 8.000000e-01 1.0e-02 1.0e-02
END YODA_SCATTER2D_V2

BEGIN YODA_SCATTER3D_V2 /REF/eff2d
Type: Scatter3D
---
0.5 0.5 0.5 15 5 5 0.1 0 0
1.5 0.5 0.5 15 5 5 0.2 0 0
0.5 0.5 0.5 35 15 15 0.3 0 0
1.5 0.5 0.5 35 15 15 0.4 0 0
END YODA_SCATTER3D_V2
""")
    spec = {'source': {'format': 'yoda', 'path': 'eff.yoda', 'object': '/REF/eff'}, 'semantics': 'absolute',
            'axes': [{'name': 'transverse momentum', 'unit': 'GeV'}], 'out_of_range': 'refuse', 'citation': 'synthetic'}
    emap = efficiency.load_map('y', spec, tmp_path)
    np.testing.assert_allclose(emap.edges[0], [10, 20, 50])
    np.testing.assert_allclose(emap.lookup([np.array([12.0, 49.0])])[0], [0.6, 0.8])
    spec2 = {**spec, 'source': {'format': 'yoda', 'path': 'eff.yoda', 'object': '/REF/eff2d'},
             'axes': [{'name': 'pseudorapidity', 'unit': '1'}, {'name': 'transverse momentum', 'unit': 'GeV'}]}
    emap2 = efficiency.load_map('y2', spec2, tmp_path)
    np.testing.assert_allclose(emap2.lookup([np.array([1.2, 0.2]), np.array([40.0, 11.0])])[0], [0.4, 0.1])
    with pytest.raises(ValueError, match='not in'):
        efficiency.load_map('y3', {**spec, 'source': {'format': 'yoda', 'path': 'eff.yoda', 'object': '/REF/none'}}, tmp_path)


def test_enumerated_results_finalize_with_expected_counts_and_card_check(tmp_path):
    (tmp_path / 'card.tcl').write_text(CARD)
    doc = _recipe('photons', 'Photon', 'enumerate', 'n >= 1',
                  maps={'id': _map(tmp_path, semantics='conditional_on_reco', card_modules=['PhotonEfficiency'])})
    doc['event_record'] = {'max_events': 3, 'observables': ['n']}
    plan, _ = _run(tmp_path, _events(6, photons=[80.0, 30.0]), doc, detector_card=tmp_path / 'card.tcl')
    partial = engine.analyse({'inputs': [{'path': str(tmp_path / 'events.root'), 'file_index': 0}], 'chunk_size': 4}, plan)
    result = engine.finalize(partial, plan, {'mode': 'none'}, out_dir=tmp_path / 'out')
    provenance = result['provenance'] if 'provenance' in result else json.loads((tmp_path / 'out/analysis-result.json').read_text())['provenance']
    assert provenance['expected_counts'] is True
    assert provenance['detector_card_check']['maps']['id']['decision'] == 'stacks on the card efficiency'
    cutflow = json.loads((tmp_path / 'out/cutflow.json').read_text())
    assert 'selected' in json.dumps(cutflow)
    rows = [json.loads(line) for line in (tmp_path / 'out/event-record.jsonl').read_text().splitlines()]
    assert len(rows) == 3 and all('subset_probability' in r for r in rows)
