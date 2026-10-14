"""Measurement overlays: data, SM and signed-interference predictions, ratio, official figure."""
import json

import numpy as np
import pytest

pytest.importorskip('matplotlib')

from ravel.plotting import measurement_overlay as mo  # noqa: E402

EDGES = [200.0, 300.0, 400.0, 500.0, 700.0, 1000.0]
SM = [50.0, 30.0, 12.0, 5.0, 1.0]
DELTA = [2.0, -3.0, -1.5, 0.5, 0.2]          # interference: negative where destructive
BASIS = {'kind': 'published_precision', 'source': 'Uncertainty quoted in the published table'}


def _hepdata(values, low, high, stat):
    return {'independent_variables': [{'header': {'name': 'Four-lepton mass', 'units': 'GeV'},
                                       'values': [{'low': a, 'high': b} for a, b in zip(EDGES, EDGES[1:])]}],
            'dependent_variables': [{'header': {'name': 'Differential cross section', 'units': 'fb/GeV'},
                                     'values': [{'value': v, 'errors': [
                                         {'label': 'stat', 'symerror': s},
                                         {'label': 'syst', 'asymerror': {'plus': h, 'minus': -l}}]}
                                         for v, l, h, s in zip(values, low, high, stat)]}]}


def _write(tmp_path, name, value):
    (tmp_path / name).write_text(json.dumps(value))
    return name


def _spec(tmp_path, **extra):
    data = [52.0, 27.0, 10.0, 6.0, 1.3]
    _write(tmp_path, 'data.json', _hepdata(data, [3, 2, 1, 0.8, 0.3], [4, 2.5, 1.2, 1.0, 0.4], [2, 1.5, 1, 0.7, 0.3]))
    _write(tmp_path, 'sm.json', {'edges': EDGES, 'values': SM, 'errors': [1.0, 0.8, 0.4, 0.2, 0.05],
                                 'quantity': 'value', 'unit': 'fb/GeV'})
    _write(tmp_path, 'delta.json', {'edges': EDGES, 'values': DELTA, 'quantity': 'value', 'unit': 'fb/GeV'})
    spec = {'schema_version': 1, 'name': 'overlay',
            'axes': {'x': {'label': 'Four-lepton invariant mass', 'unit': 'GeV'},
                     'y': {'label': 'Differential cross section', 'unit': 'fb/GeV', 'scale': 'log'},
                     'ratio': {'label': 'Ratio to the Standard Model'}},
            'data': {'label': 'Data', 'source': {'hepdata': 'data.json', 'quantity': 'value'}},
            'predictions': [{'name': 'sm', 'label': 'Standard Model', 'source': {'path': 'sm.json'}},
                            {'name': 'heavy', 'label': 'Heavy scalar with interference',
                             'delta_from': 'sm', 'source': {'path': 'delta.json'}}],
            'ratio': {'denominator': 'sm'}}
    spec.update(extra)
    return spec


def _run(tmp_path, spec):
    path = tmp_path / 'spec.json'
    path.write_text(json.dumps(spec))
    return mo.run_spec(path, tmp_path / 'out')


def test_signed_interference_total_and_ratio_panel(tmp_path):
    receipt = _run(tmp_path, _spec(tmp_path, difference_panel=True))
    assert receipt['plot_lint'] == 'PASS'
    assert {f['path'] for f in receipt['files']} == {'overlay.pdf', 'overlay.png'}
    heavy = receipt['predictions']['heavy']
    assert heavy['values'] == pytest.approx(np.add(SM, DELTA).tolist())
    assert heavy['negative_delta_bins'] == [1, 2]
    assert receipt['ratio']['heavy'] == pytest.approx((np.add(SM, DELTA) / SM).tolist())
    assert receipt['ratio']['data'][1] == pytest.approx(27.0 / 30.0)
    assert receipt['difference']['heavy'] == pytest.approx(DELTA)
    assert min(receipt['difference']['heavy']) < 0
    assert receipt['data']['error_high'][0] == pytest.approx(np.hypot(2, 4))
    assert 'Heavy scalar with interference' in receipt['legend']
    assert all(len(p['sha256']) == 64 for p in receipt['inputs'])


def test_non_positive_total_on_a_log_axis_is_refused(tmp_path):
    spec = _spec(tmp_path)
    _write(tmp_path, 'delta.json', {'edges': EDGES, 'values': [-60.0, 0, 0, 0, 0], 'quantity': 'value',
                                    'unit': 'fb/GeV'})
    with pytest.raises(ValueError, match='logarithmic'):
        _run(tmp_path, spec)


def test_official_overlay_and_side_by_side(tmp_path):
    digitized = {'kind': 'digitized-series', 'axes': {'y': {'unit': 'fb/GeV'}},
                 'series': [{'name': 'published-sm', 'kind': 'line',
                             'segments': [{'x': [250, 350, 450, 600, 850], 'y': [49, 31, 12.5, 5.2, 1.1],
                                           'y_uncertainty': [0.5, 0.3, 0.1, 0.05, 0.01]}]}]}
    _write(tmp_path, 'digitized.json', digitized)
    spec = _spec(tmp_path, official={'label': 'Published Standard Model prediction (digitised)',
                                     'source': {'digitized': 'digitized.json', 'series': 'published-sm'}},
                 side_by_side=True)
    receipt = _run(tmp_path, spec)
    paths = {f['path'] for f in receipt['files']}
    assert paths == {'overlay.pdf', 'overlay.png', 'overlay-side-by-side.pdf', 'overlay-side-by-side.png'}
    assert receipt['official']['label'] in receipt['legend']
    assert receipt['side_by_side']['panels'] == ['Published figure', 'This result']
    assert (tmp_path / 'out' / 'overlay-side-by-side.png').stat().st_size > 5000


def test_comparison_object_is_computed_and_summarised(tmp_path):
    spec = _spec(tmp_path, comparison={'agent': 'heavy', 'reference': 'data',
                                       'tolerances': {'shape_l2': {'pass': 0.2, 'warn': 0.4, 'basis': BASIS},
                                                      'chi2_per_ndf': {'pass': 2.0, 'warn': 4.0, 'basis': BASIS}}})
    receipt = _run(tmp_path, spec)
    comparison = receipt['comparison']
    assert comparison['kind'] == 'reference-comparison' and comparison['verdict'] in ('PASS', 'WARN', 'FAIL')
    assert comparison['metrics']['n_bins'] == 5
    assert comparison['summary'][0].startswith('Machine comparison')


def test_saved_comparison_object_is_consumed(tmp_path):
    from ravel.plotting import reference_metrics as rm
    sm = rm.binned(EDGES, SM, quantity='value', unit='fb/GeV')
    ref = rm.binned(EDGES, [52.0, 27.0, 10.0, 6.0, 1.3], errors=[3, 2, 1, 1, 0.3], quantity='value', unit='fb/GeV')
    saved = rm.compare_binned(sm, ref, {'shape_l2': {'pass': 0.2, 'warn': 0.4, 'basis': BASIS}})
    saved.update({'kind': 'reference-comparison', 'summary': rm.summary_lines(saved)})
    _write(tmp_path, 'comparison.json', saved)
    receipt = _run(tmp_path, _spec(tmp_path, comparison={'path': 'comparison.json'}))
    assert receipt['comparison']['verdict'] == saved['verdict']
    assert any(p['path'].endswith('comparison.json') for p in receipt['inputs'])


def test_mismatched_bins_are_refused(tmp_path):
    spec = _spec(tmp_path)
    _write(tmp_path, 'sm.json', {'edges': [200, 300, 400, 500, 750, 1000], 'values': SM, 'quantity': 'value',
                                 'unit': 'fb/GeV'})
    with pytest.raises(ValueError, match='rebin'):
        _run(tmp_path, spec)


@pytest.mark.parametrize('where,value', [('x', 'm_4l'), ('legend', 'Muon.PT'), ('legend', 'sm_total')])
def test_machine_identifiers_are_refused(tmp_path, where, value):
    spec = _spec(tmp_path)
    if where == 'x':
        spec['axes']['x']['label'] = value
    else:
        spec['predictions'][0]['label'] = value
    with pytest.raises(ValueError, match='natural-language'):
        _run(tmp_path, spec)
