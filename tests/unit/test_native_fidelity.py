"""Physical invariants independent of a reference implementation's output counts."""
import math

import pytest

from ravel.physics import native_sa_generic as generic
from ravel.physics import sa_native_core as core
from ravel.physics.sa_routines import ewkthreeleptonerjr2018 as erjr


def _longitudinal_boost(p, rapidity):
    """Independent rapidity form, leaving transverse components unchanged."""
    return [p[0], p[1], p[2]*math.cosh(rapidity)+p[3]*math.sinh(rapidity),
            p[3]*math.cosh(rapidity)+p[2]*math.sinh(rapidity)]


def test_hboost_massless_sum_equals_invariant_mass_in_common_rest_frame():
    # All constituents massless: sum |p*| = sum E* = invariant mass of the total.
    # This independently checks the invisible term, not just the boost formula.
    leptons = [erjr._p4(120, 1.1, .2, 0), erjr._p4(80, .7, 2.8, 0),
               erjr._p4(50, 1.4, -1.5, 0)]
    visible = [sum(p[k] for p in leptons) for k in range(4)]
    mx, my = -65., -40.
    mz = visible[2]*math.hypot(mx, my)/math.sqrt(visible[3]**2-visible[2]**2)
    total = [visible[0]+mx, visible[1]+my, visible[2]+mz,
             visible[3]+math.sqrt(mx*mx+my*my+mz*mz)]
    expected = math.sqrt(total[3]**2-sum(x*x for x in total[:3]))
    assert erjr.h_boost(leptons, mx, my) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize('rapidity', [-1.2, .8])
def test_hboost_is_invariant_under_common_longitudinal_boost(rapidity):
    leptons = [erjr._p4(120, .3, .2, .000511), erjr._p4(80, -.7, 2.8, .10566),
               erjr._p4(50, .4, -1.5, .10566)]
    moved = [_longitudinal_boost(p, rapidity) for p in leptons]
    assert erjr.h_boost(moved, -65., -40.) == pytest.approx(
        erjr.h_boost(leptons, -65., -40.), rel=1e-12)


def test_low_mass_selection_uses_paper_defined_invisible_boost():
    # Retained CR005 C1N2 (300,100) detector event 6295. The old mixed-frame
    # Hboost rejected this event; no selection threshold has been adjusted.
    arrays = {
        'el_pt': [[136.38876342773438]], 'el_eta': [[-1.24193274974823]],
        'el_phi': [[-.057600803673267365]], 'el_charge': [[-1]], 'el_id': [[0x7fffffff]],
        'mu_pt': [[154.68621826171875, 46.086639404296875]],
        'mu_eta': [[-1.5993002653121948, -1.9141796827316284]],
        'mu_phi': [[2.514890432357788, -2.787815570831299]],
        'mu_charge': [[1, -1]], 'mu_id': [[0x7fffffff, 0x7fffffff]],
        'jet_pt': [[]], 'jet_eta': [[]], 'jet_phi': [[]], 'jet_id': [[]], 'jet_m': [[]],
        'met_pt': [82.41629028320312], 'met_phi': [-1.2254962921142578],
    }
    assert erjr.select(arrays, 0) == ({'Preselection', 'SRlow'}, False, True)


def _generic_spec():
    return {'name': 'weighted-example', 'lumi_fb': 1,
            'objects': {name: {'pt': 0, 'eta': 5} for name in ['electron', 'muon', 'jet']},
            'regions': [{'name': 'SR', 'cuts': [{'var': 'MET', 'op': '>', 'val': 100}]}]}


def _met_event(pt):
    return ([], [], [], core.Obj(pt, 0, 0, 0, 0, 0, 6))


def test_generic_signal_selection_applies_eta_and_quality_mask():
    spec = _generic_spec()
    spec['signal'] = {'electron': {'pt': 20, 'eta': 1.5, 'id': core.EMediumLH}}
    electrons = [core.Obj(40, eta, phi, core.ME, -1, bits, core.ELECTRON)
                 for eta, phi, bits in [(1., 0., core.EMediumLH), (2., 1., core.EMediumLH),
                                        (.5, 2., core.ELooseLH)]]
    assert generic.select_event(spec, electrons, [], [], _met_event(200)[3])['nEl'] == 1
    with pytest.raises(ValueError, match='unsupported by the Delphes adapter'):
        generic.validate_delphes_spec(spec)
    spec['signal'] = {'jet': {'id': core.JVT50Jet}}
    with pytest.raises(ValueError, match='unsupported by the Delphes adapter'):
        generic.validate_delphes_spec(spec)


def test_generic_and_container_text_preserve_signed_weighted_yields(tmp_path, monkeypatch):
    import argparse
    import csv
    import json
    spec = _generic_spec()
    events = [_met_event(200), _met_event(200), _met_event(20)]
    weights = [2., -1., 3.]
    sumw, raw, sumw2 = generic.run_events(spec, events, weights, return_sumw2=True)
    assert (raw, sumw, sumw2) == ({'SR': 2}, {'SR': 1.}, {'SR': 5.})
    totals = dict(core.summarize_weights(weights), Ngen=3, w_all=weights)
    txt = tmp_path/'weighted.txt'
    core.write_txt(txt, raw, ['SR'], totals, sumw=sumw, sumw2=sumw2)
    rows = list(csv.DictReader(txt.open()))
    assert float(rows[1]['acceptance']) == .25
    assert float(rows[1]['err']) == pytest.approx(math.sqrt(5)/4, rel=1e-6)
    with pytest.raises(ValueError, match='require per-region sumw'):
        core.write_txt(tmp_path/'wrong.txt', raw, ['SR'], totals)
    spec_path = tmp_path/'spec.json'
    spec_path.write_text(json.dumps(spec))
    monkeypatch.setattr(generic, 'read_delphes', lambda path: (events, weights))
    generic.cmd_run(argparse.Namespace(spec=spec_path, delphes='input.root', xs_pb=1.,
                                       lumi_fb=1., out=tmp_path/'yields.json'))
    region = json.loads((tmp_path/'yields.json').read_text())['regions']['SR']
    assert region == pytest.approx({'raw': 2, 'sumw': 1., 'sumw2': 5., 'acceptance': .25,
                                   'yield': 250., 'mc_stat_error': math.sqrt(5)*250})


def test_uniform_positive_weight_acceptance_is_preserved(tmp_path):
    weights = [3., 3., 3.]
    raw = {'SR': 2}
    totals = dict(core.summarize_weights(weights), Ngen=3, w_all=weights)
    implicit, explicit = tmp_path/'implicit.txt', tmp_path/'explicit.txt'
    core.write_txt(implicit, raw, ['SR'], totals)
    core.write_txt(explicit, raw, ['SR'], totals, sumw={'SR': 6.}, sumw2={'SR': 18.})
    assert implicit.read_bytes() == explicit.read_bytes()
    assert implicit.read_text().splitlines()[-1] == 'SR,2,0.666667,0.471405'


@pytest.mark.parametrize('weights', [[1., -1.], [1., math.nan], [1., math.inf], [1e308, 1e308], []])
def test_unusable_weight_normalizations_fail_explicitly(weights):
    with pytest.raises(ValueError):
        core.summarize_weights(weights)


def test_missing_or_misaligned_weights_are_never_silently_unity(monkeypatch):
    import sys
    import types
    class Tree:
        num_entries = 2
        def __contains__(self, name):
            return False
        def arrays(self, *args, **kwargs):
            return {'Event': [0, 1], 'mcWeights': [[], [2.]]}
    monkeypatch.setitem(sys.modules, 'uproot', types.SimpleNamespace(open=lambda path: {'Delphes': Tree(), 'ntuple': Tree()}))
    with pytest.raises(ValueError, match='lacks Event.Weight'):
        generic.read_delphes('dummy.root')
    with pytest.raises(ValueError, match='nominal mcWeights'):
        core.load_ntuple('dummy.root')
    with pytest.raises(ValueError, match='exactly one nominal weight'):
        generic.run_events(_generic_spec(), [_met_event(200)], [1., 2.])


def test_delphes_reader_preserves_nominal_signed_weights(monkeypatch):
    import sys
    import types
    class Branch:
        def __init__(self, values):
            self.values = values
        def array(self, **kwargs):
            return self.values
    tree = {name: Branch(values) for name, values in {
        'Event.Weight': [[2.], [-1.], [3.]],
        'MissingET.MET': [[200.], [200.], [20.]],
        'MissingET.Phi': [[0.], [0.], [0.]],
    }.items()}
    monkeypatch.setitem(sys.modules, 'uproot', types.SimpleNamespace(open=lambda path: {'Delphes': tree}))
    events, weights = generic.read_delphes('dummy.root')
    assert weights == [2., -1., 3.]
    assert generic.run_events(_generic_spec(), events, weights) == ({'SR': 1.}, {'SR': 2})


def test_counting_driver_passes_actual_weight_moments_to_writer(tmp_path, monkeypatch):
    import csv
    import types
    weights = [2., -1., 3.]
    totals = dict(core.summarize_weights(weights), Ngen=3, w_all=weights)
    monkeypatch.setattr(core, 'load_ntuple', lambda *args: ({}, [10, 11, 12], 3, totals))
    monkeypatch.setattr(core, 'write_root', lambda *args: None)
    routine = types.SimpleNamespace(NAME='Weighted', sr_order=lambda: ['SR'],
                                    select=lambda arrays, i: ({'SR'}, False, False) if i < 2 else None)
    assert core.run_counting_routine(routine, 'dummy.root', tmp_path) == {'SR': 2}
    rows = list(csv.DictReader((tmp_path/'Weighted.txt').open()))
    assert float(rows[1]['acceptance']) == .25
    assert float(rows[1]['err']) == pytest.approx(math.sqrt(5)/4, rel=1e-6)
