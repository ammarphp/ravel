"""Generic parameter-plane figures: contours, bands, shading, references, panels."""
import json

import numpy as np
import pytest

pytest.importorskip('matplotlib')
pytest.importorskip('contourpy')

from ravel.plotting import parameter_plane as pp  # noqa: E402

AXES = {'x': {'label': 'Mediator mass', 'unit': 'GeV', 'scale': 'linear', 'range': [100, 1000]},
        'y': {'label': 'Coupling to quarks', 'unit': '', 'scale': 'log', 'range': [0.01, 1.0]}}


def _grid():
    x = np.linspace(100, 1000, 31)
    y = np.logspace(-2, 0, 41)
    X, Y = np.meshgrid(x, y)
    # Signal-strength limit: equals one on y = 0.1 * x / 500, excluded (below one) above the line.
    observed = (0.1 * X / 500 / Y) ** 2
    return x, y, observed


def _panel(scale=1.0):
    x, y, observed = _grid()
    return {'grid': {'x': x.tolist(), 'y': y.tolist(), 'level': 1.0, 'excluded': 'below',
                     'observed': (observed * scale).tolist(),
                     'expected': (observed * 1.2 * scale).tolist(),
                     'expected_1sigma': {'low': (observed * 0.9).tolist(), 'high': (observed * 1.6).tolist()},
                     'expected_2sigma': {'low': (observed * 0.7).tolist(), 'high': (observed * 2.2).tolist()}}}


def _write(tmp_path, spec, name='plane.json'):
    path = tmp_path / name
    path.write_text(json.dumps(spec))
    return path


def test_grid_contour_follows_the_analytic_level_line_on_a_log_axis():
    x, y, observed = _grid()
    segments = pp.grid_contours(x, y, observed, 1.0, 'linear', 'log')
    xs = np.concatenate([s['x'] for s in segments])
    ys = np.concatenate([s['y'] for s in segments])
    assert len(xs) > 10
    assert np.max(np.abs(np.log10(ys / (0.1 * xs / 500)))) < 0.01


def test_single_panel_with_bands_shading_and_reference_passes_lint(tmp_path):
    digitized = {'kind': 'digitized-series', 'axes': {'y': {'unit': ''}},
                 'series': [{'name': 'published', 'kind': 'line',
                             'segments': [{'x': [100, 1000], 'y': [0.025, 0.25],
                                           'x_uncertainty': [1, 1], 'y_uncertainty': [0.001, 0.01]}]}]}
    (tmp_path / 'digitized.json').write_text(json.dumps(digitized))
    panel = _panel()
    panel['references'] = [{'label': 'Published observed limit (digitised)',
                            'source': {'digitized': 'digitized.json', 'series': 'published'}}]
    panel['points'] = [{'x': 400, 'y': 0.3, 'label': 'Benchmark point'}]
    spec = {'schema_version': 1, 'axes': AXES, 'panels': [panel],
            'annotation': ['Reinterpretation at 13 TeV']}
    receipt = pp.run_spec(_write(tmp_path, spec), tmp_path / 'out')
    out = tmp_path / 'out'
    assert receipt['plot_lint'] == 'PASS'
    assert {f['path'] for f in receipt['files']} == {'plane.pdf', 'plane.png'}
    assert (out / 'plane.png').stat().st_size > 5000 and (out / 'plane.json').is_file()
    contour = receipt['panels'][0]['contours']['observed']['segments']
    xs = np.concatenate([s['x'] for s in contour])
    ys = np.concatenate([s['y'] for s in contour])
    assert np.max(np.abs(np.log10(ys / (0.1 * xs / 500)))) < 0.01
    frac = receipt['panels'][0]['excluded_fraction']
    assert 0.2 < frac < 0.9
    legend = receipt['panels'][0]['legend']
    assert 'Published observed limit (digitised)' in legend and 'Expected ±1σ' in legend
    assert receipt['inputs'] and all(len(p['sha256']) == 64 for p in receipt['inputs'])


def test_multi_panel_layout_and_colour_map(tmp_path):
    p1, p2 = _panel(), _panel(scale=0.5)
    p1['title'] = 'Width equal to 1 percent of the mass'
    p2['title'] = 'Width equal to 10 percent of the mass'
    p2['colour_map'] = {'surface': 'observed', 'label': 'Signal strength limit', 'scale': 'log'}
    spec = {'schema_version': 1, 'axes': AXES, 'layout': {'columns': 2}, 'panels': [p1, p2]}
    receipt = pp.run_spec(_write(tmp_path, spec), tmp_path / 'out')
    assert len(receipt['panels']) == 2 and receipt['layout'] == {'columns': 2, 'rows': 1}
    assert receipt['panels'][1]['excluded_fraction'] > receipt['panels'][0]['excluded_fraction']


def test_one_dimensional_limit_with_bands_and_theory(tmp_path):
    mass = np.linspace(200, 2000, 10)
    expected = 10 * np.exp(-mass / 600)
    spec = {'schema_version': 1,
            'axes': {'x': {'label': 'Resonance mass', 'unit': 'GeV'},
                     'y': {'label': 'Cross section times branching fraction', 'unit': 'fb', 'scale': 'log'}},
            'panels': [{'limit_curves': {'x': mass.tolist(), 'expected': expected.tolist(),
                                         'observed': (expected * 1.1).tolist(),
                                         'expected_1sigma': {'low': (expected * 0.7).tolist(), 'high': (expected * 1.4).tolist()},
                                         'expected_2sigma': {'low': (expected * 0.5).tolist(), 'high': (expected * 2.0).tolist()}},
                        'theory': [{'label': 'Benchmark model prediction', 'x': mass.tolist(),
                                    'y': (20 * np.exp(-mass / 400)).tolist()}]}]}
    receipt = pp.run_spec(_write(tmp_path, spec), tmp_path / 'out')
    assert receipt['plot_lint'] == 'PASS'
    assert 'Benchmark model prediction' in receipt['panels'][0]['legend']


def test_disjoint_excluded_intervals_are_drawn(tmp_path):
    spec = {'schema_version': 1,
            'axes': {'x': {'label': 'Resonance mass', 'unit': 'GeV', 'range': [400, 1600]},
                     'y': {'label': 'Width over mass', 'unit': '', 'range': [0, 0.3]}},
            'panels': [{'intervals': {'x': [500, 1000, 1500],
                                      'excluded': [[[0.0, 0.05], [0.15, 0.25]], [[0.02, 0.1]], []],
                                      'label': 'Excluded at 95% confidence'}}]}
    receipt = pp.run_spec(_write(tmp_path, spec), tmp_path / 'out')
    drawn = receipt['panels'][0]['intervals']
    assert [len(c['excluded']) for c in drawn] == [2, 1, 0]


@pytest.mark.parametrize('field,value', [('axis', 'm_med'), ('reference', 'obs_limit'), ('branch', 'Jet.PT')])
def test_machine_identifiers_are_refused_as_labels(tmp_path, field, value):
    axes = json.loads(json.dumps(AXES))
    panel = _panel()
    if field == 'axis':
        axes['x']['label'] = value
    elif field == 'reference':
        panel['references'] = [{'label': value, 'source': {'x': [100, 1000], 'y': [0.02, 0.2]}}]
    else:
        axes['y']['label'] = value
    spec = {'schema_version': 1, 'axes': axes, 'panels': [panel]}
    with pytest.raises(ValueError, match='natural-language'):
        pp.run_spec(_write(tmp_path, spec), tmp_path / 'out')


def test_grid_shape_mismatch_is_refused(tmp_path):
    panel = _panel()
    panel['grid']['observed'] = panel['grid']['observed'][:-1]
    spec = {'schema_version': 1, 'axes': AXES, 'panels': [panel]}
    with pytest.raises(ValueError, match='shape'):
        pp.run_spec(_write(tmp_path, spec), tmp_path / 'out')


def test_reference_comparison_object_is_computed_and_shown(tmp_path):
    x = np.linspace(100, 1000, 20)
    panel = _panel()
    basis = {'kind': 'published_precision', 'source': 'Published contour line width'}
    panel['references'] = [{'label': 'Published observed limit',
                            'source': {'x': x.tolist(), 'y': (0.1 * x / 500 * 1.05).tolist()},
                            'compare': {'with': 'observed', 'kind': 'contour', 'tip': 'max_x',
                                        'tolerances': {'hausdorff_max': {'pass': 0.02, 'warn': 0.05,
                                                                         'basis': basis}}}}]
    spec = {'schema_version': 1, 'axes': AXES, 'panels': [panel]}
    receipt = pp.run_spec(_write(tmp_path, spec), tmp_path / 'out')
    comparison = receipt['panels'][0]['references'][0]['comparison']
    assert comparison['kind'] == 'reference-comparison' and comparison['verdict'] == 'PASS'
    assert comparison['hausdorff_max'] < 0.02 and comparison['tip']['direction'] == 'max_x'
    assert comparison['summary'] and receipt['plot_lint'] == 'PASS'


def _inference_record(tmp_path):
    """A record in the statistics stream's inference.json form (values indexed [x][y])."""
    x, y, observed = _grid()
    from ravel.plotting.parameter_plane import grid_contours
    lines = grid_contours(x, y, observed, 1.0, 'linear', 'log')
    obs = observed.T.tolist()
    obs[0][0] = None                       # a nonfinite value is written as null
    doc = {'schema_version': 1, 'kind': 'inference', 'status': 'passed', 'physics_validated': False,
           'statistic': {'origin': 'default'},
           'parameters': [{'name': 'mass', 'unit': 'GeV', 'label': 'Mediator mass'},
                          {'name': 'coupling', 'unit': '', 'label': 'Coupling to quarks'}],
           'grid': {'kind': 'product', 'axes': [{'name': 'mass', 'unit': 'GeV', 'values': x.tolist()},
                                                {'name': 'coupling', 'unit': '', 'values': y.tolist()}]},
           'results': [{'quantity': 'grid-values', 'role': 'primary', 'name': 'mu_obs', 'label': 'Signal strength limit',
                        'unit': '', 'values': obs},
                       {'quantity': 'grid-values', 'role': 'companion', 'name': 'mu_exp', 'label': 'Expected',
                        'unit': '', 'values': (observed * 1.2).T.tolist()},
                       {'quantity': 'contour', 'role': 'primary', 'name': 'observed-contour', 'x': 'mass',
                        'y': 'coupling', 'series': [{'id': f'c-{k}', 'label': 'Observed', 'geometry': 'polyline',
                                                     'records': [{'x': a, 'y': b} for a, b in zip(s['x'], s['y'])]}
                                                    for k, s in enumerate(lines)]}],
           'inputs': []}
    (tmp_path / 'inference.json').write_text(json.dumps(doc))


def test_grid_and_contour_read_from_an_inference_record(tmp_path):
    _inference_record(tmp_path)
    basis = {'kind': 'community', 'citation': 'Same-grid self-consistency'}
    panel = {'grid': {'inference': 'inference.json', 'x': 'mass', 'y': 'coupling', 'level': 1.0, 'excluded': 'below',
                      'surfaces': {'observed': 'mu_obs', 'expected': 'mu_exp'}},
             'references': [{'label': 'Contour from the statistics record',
                             'source': {'inference': 'inference.json', 'result': 'observed-contour'},
                             'compare': {'with': 'observed', 'tolerances': {
                                 'hausdorff_max': {'pass': 0.01, 'warn': 0.02, 'basis': basis}}}}]}
    spec = {'schema_version': 1, 'axes': AXES, 'panels': [panel]}
    receipt = pp.run_spec(_write(tmp_path, spec), tmp_path / 'out')
    assert receipt['plot_lint'] == 'PASS'
    assert receipt['panels'][0]['references'][0]['comparison']['verdict'] == 'PASS'
    assert any(p['path'].endswith('inference.json') for p in receipt['inputs'])
    assert receipt['panels'][0]['grid_source']['missing_values'] == 1


def test_inference_grid_refuses_unknown_axes_or_results(tmp_path):
    _inference_record(tmp_path)
    for grid, message in (({'x': 'width', 'y': 'coupling', 'surfaces': {'observed': 'mu_obs'}}, 'width'),
                          ({'x': 'mass', 'y': 'coupling', 'surfaces': {'observed': 'missing'}}, 'missing')):
        spec = {'schema_version': 1, 'axes': AXES,
                'panels': [{'grid': {'inference': 'inference.json', **grid}}]}
        with pytest.raises(ValueError, match=message):
            pp.run_spec(_write(tmp_path, spec, f'{message}.json'), tmp_path / f'out-{message}')
