"""Digitisation of synthetic vector-PDF and raster figures with known curves."""
import json
from pathlib import Path

import numpy as np
import pytest

matplotlib = pytest.importorskip('matplotlib')
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

from ravel.plotting import digitize  # noqa: E402

RED, BLUE, YELLOW, GREEN = '#d55e00', '#0072b2', '#f0e442', '#009e73'


@pytest.fixture(autouse=True)
def _default_matplotlib_style():
    """Synthetic published figures use plain matplotlib text, whatever style an earlier test applied."""
    with plt.style.context('default'):
        yield


def _linear_figure(path):
    matplotlib.rcParams['pdf.fonttype'] = 42
    fig, ax = plt.subplots(figsize=(5, 4))
    x = np.linspace(0, 10, 41)
    ax.fill_between(x, 0.5 * x + 1, 0.5 * x + 3, color=YELLOW, label='Expected band')
    ax.plot(x, 2 * x + 1, color=RED, lw=2, label='Observed limit')
    xm = np.array([1.0, 3.0, 5.0, 7.0, 9.0])
    ax.errorbar(xm, 0.3 * xm ** 2, yerr=1.0, fmt='o', color=BLUE, label='Measured points')
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 30)
    ax.set_xlabel('Mass [GeV]')
    ax.legend(loc='upper left')
    fig.savefig(path)
    plt.close(fig)


def _log_figure(path, fmt='pdf', dpi=100):
    matplotlib.rcParams['pdf.fonttype'] = 42
    fig, ax = plt.subplots(figsize=(5, 4))
    x = np.linspace(100, 1000, 60)
    ax.plot(x, 1e4 * np.exp(-x / 150), color=GREEN, lw=2, label='Cross section')
    ax.set_yscale('log')
    ax.set_xlim(100, 1000)
    ax.set_ylim(1e-1, 1e4)
    ax.set_xlabel('Mass [GeV]')
    ax.legend(loc='upper right')
    fig.savefig(path, format=fmt, dpi=dpi)
    plt.close(fig)
    return fig, ax


def _write_spec(tmp_path, spec, name='spec.json'):
    path = tmp_path / name
    path.write_text(json.dumps(spec))
    return path


def _series(doc, name):
    return next(s for s in doc['series'] if s['name'] == name)


def _points(series):
    xs = np.concatenate([np.array(seg['x']) for seg in series['segments']])
    ys = np.concatenate([np.array(seg['y']) for seg in series['segments']])
    return xs, ys


def test_vector_linear_curve_recovered_from_tick_labels(tmp_path):
    _linear_figure(tmp_path / 'fig.pdf')
    spec = {'schema_version': 1, 'source': {'path': 'fig.pdf', 'page': 1},
            'axes': {'x': {'scale': 'linear', 'label': 'Mass', 'unit': 'GeV',
                           'calibration': {'method': 'tick_labels'}},
                     'y': {'scale': 'linear', 'label': 'Limit', 'unit': 'pb',
                           'calibration': {'method': 'tick_labels'}}},
            'series': [{'name': 'observed', 'label': 'Observed limit', 'kind': 'line',
                        'select': {'color': RED}}]}
    doc = digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out')
    xs, ys = _points(_series(doc, 'observed'))
    assert len(xs) >= 20
    assert np.max(np.abs(ys - (2 * xs + 1))) < 0.05          # 0.2% of the axis span
    assert xs.min() < 0.1 and xs.max() > 9.9
    cal = doc['axes']['x']['calibration']
    assert cal['method'] == 'tick_labels' and len(cal['anchors']) >= 4
    assert cal['max_abs_residual'] < 0.02
    out = tmp_path / 'out'
    saved = json.loads((out / 'digitized.json').read_text())
    assert saved['source']['sha256'] == digitize.sha256_file(tmp_path / 'fig.pdf')
    assert saved['source']['page'] == 1 and saved['source']['format'] == 'vector-pdf'
    assert (out / 'review.png').stat().st_size > 1000
    assert saved['review_overlay']['path'] == 'review.png'


def test_vector_selection_by_legend_label_excludes_the_legend_handle(tmp_path):
    _linear_figure(tmp_path / 'fig.pdf')
    spec = {'schema_version': 1, 'source': {'path': 'fig.pdf'},
            'axes': {'x': {'calibration': {'method': 'tick_labels'}, 'label': 'Mass', 'unit': 'GeV'},
                     'y': {'calibration': {'method': 'tick_labels'}, 'label': 'Limit', 'unit': 'pb'}},
            'series': [{'name': 'observed', 'label': 'Observed limit', 'select': {'legend': 'Observed limit'}}]}
    doc = digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out')
    series = _series(doc, 'observed')
    assert series['kind'] == 'line'
    assert series['style']['color'] == RED
    xs, ys = _points(series)
    assert np.max(np.abs(ys - (2 * xs + 1))) < 0.05


def test_vector_markers_with_error_bars_and_band_envelope(tmp_path):
    _linear_figure(tmp_path / 'fig.pdf')
    spec = {'schema_version': 1, 'source': {'path': 'fig.pdf'},
            'axes': {'x': {'calibration': {'method': 'tick_labels'}, 'label': 'Mass', 'unit': 'GeV'},
                     'y': {'calibration': {'method': 'tick_labels'}, 'label': 'Limit', 'unit': 'pb'}},
            'series': [{'name': 'points', 'label': 'Measured points', 'kind': 'markers', 'select': {'color': BLUE}},
                       {'name': 'band', 'label': 'Expected band', 'kind': 'band', 'select': {'color': YELLOW}}]}
    doc = digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out')
    points = _series(doc, 'points')
    xs, ys = _points(points)
    assert np.allclose(xs, [1, 3, 5, 7, 9], atol=0.02)
    assert np.allclose(ys, 0.3 * xs ** 2, atol=0.05)
    seg = points['segments'][0]
    assert np.allclose(seg['y_error_low'], 1.0, atol=0.05) and np.allclose(seg['y_error_high'], 1.0, atol=0.05)
    band = _series(doc, 'band')
    lx, ly = np.array(band['lower']['x']), np.array(band['lower']['y'])
    ux, uy = np.array(band['upper']['x']), np.array(band['upper']['y'])
    assert np.max(np.abs(ly - (0.5 * lx + 1))) < 0.05
    assert np.max(np.abs(uy - (0.5 * ux + 3))) < 0.05


def test_vector_log_axis_with_mathtext_tick_labels(tmp_path):
    _log_figure(tmp_path / 'log.pdf')
    spec = {'schema_version': 1, 'source': {'path': 'log.pdf'},
            'axes': {'x': {'scale': 'linear', 'calibration': {'method': 'tick_labels'}, 'label': 'Mass', 'unit': 'GeV'},
                     'y': {'scale': 'log', 'calibration': {'method': 'tick_labels'}, 'label': 'Cross section', 'unit': 'fb'}},
            'series': [{'name': 'xsec', 'label': 'Cross section', 'select': {'color': GREEN}}]}
    doc = digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out')
    xs, ys = _points(_series(doc, 'xsec'))
    truth = 1e4 * np.exp(-xs / 150)
    keep = truth > 0.1                       # inside the visible range
    assert np.max(np.abs(ys[keep] / truth[keep] - 1)) < 0.01
    values = sorted(a['value'] for a in doc['axes']['y']['calibration']['anchors'])
    assert values[0] == pytest.approx(0.1) and values[-1] == pytest.approx(1e4)


def test_declared_tick_values_and_explicit_anchors(tmp_path):
    _linear_figure(tmp_path / 'fig.pdf')
    inventory = digitize.inventory(tmp_path / 'fig.pdf', page=1)
    ticks = inventory['tick_marks']
    assert len(ticks['x']) >= 6 and len(ticks['y']) >= 7
    spec = {'schema_version': 1, 'source': {'path': 'fig.pdf'},
            'axes': {'x': {'calibration': {'method': 'tick_values', 'values': [0, 2, 4, 6, 8, 10]}, 'label': 'Mass', 'unit': 'GeV'},
                     'y': {'calibration': {'method': 'anchors', 'anchors': [
                         {'position': ticks['y'][0], 'value': 0}, {'position': ticks['y'][-1], 'value': 30}]},
                         'label': 'Limit', 'unit': 'pb'}},
            'series': [{'name': 'observed', 'label': 'Observed limit', 'select': {'color': RED, 'tolerance': 0.05}}]}
    doc = digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out')
    xs, ys = _points(_series(doc, 'observed'))
    assert np.max(np.abs(ys - (2 * xs + 1))) < 0.05
    assert doc['axes']['x']['calibration']['method'] == 'tick_values'


def test_figure_placed_scaled_on_a_larger_page_tracks_the_transform(tmp_path):
    import pypdf
    _linear_figure(tmp_path / 'fig.pdf')
    reader = pypdf.PdfReader(str(tmp_path / 'fig.pdf'))
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page.merge_transformed_page(reader.pages[0], pypdf.Transformation().scale(0.6).translate(100, 400))
    with (tmp_path / 'paper.pdf').open('wb') as stream:
        writer.write(stream)
    spec = {'schema_version': 1, 'source': {'path': 'paper.pdf', 'page': 1},
            'axes': {'x': {'calibration': {'method': 'tick_labels'}, 'label': 'Mass', 'unit': 'GeV'},
                     'y': {'calibration': {'method': 'tick_labels'}, 'label': 'Limit', 'unit': 'pb'}},
            'series': [{'name': 'observed', 'label': 'Observed limit', 'select': {'color': RED}}]}
    doc = digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out')
    xs, ys = _points(_series(doc, 'observed'))
    assert np.max(np.abs(ys - (2 * xs + 1))) < 0.08


def _pixel_anchors(fig, ax, xs, ys, height):
    fig.canvas.draw()
    to_px = ax.transData.transform
    xa = [{'position': float(to_px((x, ys[0]))[0]), 'value': x} for x in xs]
    ya = [{'position': float(height - to_px((xs[0], y))[1]), 'value': y} for y in ys]
    return xa, ya


@pytest.mark.parametrize('logy', [False, True])
def test_raster_curve_recovered_with_declared_pixel_calibration(tmp_path, logy):
    fig, ax = plt.subplots(figsize=(5, 4), dpi=100)
    x = np.linspace(100, 1000, 200)
    y = 1e4 * np.exp(-x / 150) if logy else 0.02 * x + 3
    ax.plot(x, y, color=GREEN, lw=1.5)
    ax.set_xlim(100, 1000)
    if logy:
        ax.set_yscale('log')
        ax.set_ylim(1e-1, 1e4)
        yticks = [1e-1, 1e4]
    else:
        ax.set_ylim(0, 25)
        yticks = [0, 25]
    fig.savefig(tmp_path / 'fig.png', dpi=100)
    width, height = fig.canvas.get_width_height()
    xa, ya = _pixel_anchors(fig, ax, [100, 1000], yticks, height)
    plt.close(fig)
    spec = {'schema_version': 1, 'source': {'path': 'fig.png'},
            'axes': {'x': {'scale': 'linear', 'label': 'Mass', 'unit': 'GeV', 'calibration': {'method': 'anchors', 'anchors': xa}},
                     'y': {'scale': 'log' if logy else 'linear', 'label': 'Cross section', 'unit': 'fb',
                           'calibration': {'method': 'anchors', 'anchors': ya}}},
            'series': [{'name': 'curve', 'label': 'Cross section', 'kind': 'line', 'select': {'color': GREEN, 'tolerance': 0.25}}]}
    doc = digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out')
    assert doc['source']['format'] == 'raster'
    xs, ys = _points(_series(doc, 'curve'))
    assert len(xs) > 100
    truth = 1e4 * np.exp(-xs / 150) if logy else 0.02 * xs + 3
    keep = (truth > 0.15) if logy else slice(None)
    if logy:
        assert np.median(np.abs(np.log10(ys[keep] / truth[keep]))) < 0.02
    else:
        assert np.median(np.abs(ys - truth)) < 0.1
    seg = _series(doc, 'curve')['segments'][0]
    assert all(u > 0 for u in seg['y_uncertainty'])
    assert (tmp_path / 'out' / 'review.png').is_file()


def test_raster_markers_found_as_connected_components(tmp_path):
    fig, ax = plt.subplots(figsize=(5, 4), dpi=100)
    xm = np.array([2.0, 4.0, 6.0, 8.0])
    ax.plot(xm, xm + 1, 's', color=BLUE, ms=6)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    fig.savefig(tmp_path / 'm.png', dpi=100)
    width, height = fig.canvas.get_width_height()
    xa, ya = _pixel_anchors(fig, ax, [0, 10], [0, 10], height)
    plt.close(fig)
    spec = {'schema_version': 1, 'source': {'path': 'm.png'},
            'axes': {'x': {'label': 'Mass', 'unit': 'GeV', 'calibration': {'method': 'anchors', 'anchors': xa}},
                     'y': {'label': 'Events', 'unit': '', 'calibration': {'method': 'anchors', 'anchors': ya}}},
            'series': [{'name': 'pts', 'label': 'Points', 'kind': 'markers', 'select': {'color': BLUE, 'tolerance': 0.2}}]}
    doc = digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out')
    xs, ys = _points(_series(doc, 'pts'))
    assert np.allclose(xs, xm, atol=0.05) and np.allclose(ys, xm + 1, atol=0.05)


def test_unmatched_selection_and_existing_output_are_refused(tmp_path):
    _linear_figure(tmp_path / 'fig.pdf')
    spec = {'schema_version': 1, 'source': {'path': 'fig.pdf'},
            'axes': {'x': {'calibration': {'method': 'tick_labels'}, 'label': 'Mass', 'unit': 'GeV'},
                     'y': {'calibration': {'method': 'tick_labels'}, 'label': 'Limit', 'unit': 'pb'}},
            'series': [{'name': 'none', 'label': 'Nothing', 'select': {'color': '#123456', 'tolerance': 0.01}}]}
    with pytest.raises(ValueError, match='no drawn'):
        digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out1')
    (tmp_path / 'out2').mkdir()
    (tmp_path / 'out2' / 'keep.txt').write_text('x')
    spec['series'][0]['select'] = {'color': RED}
    with pytest.raises(ValueError, match='new or empty'):
        digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out2')


def test_series_label_must_be_natural_language(tmp_path):
    _linear_figure(tmp_path / 'fig.pdf')
    spec = {'schema_version': 1, 'source': {'path': 'fig.pdf'},
            'axes': {'x': {'calibration': {'method': 'tick_labels'}, 'label': 'Mass', 'unit': 'GeV'},
                     'y': {'calibration': {'method': 'tick_labels'}, 'label': 'Limit', 'unit': 'pb'}},
            'series': [{'name': 'observed', 'label': 'obs_limit_xsec', 'select': {'color': RED}}]}
    with pytest.raises(ValueError, match='natural-language'):
        digitize.run_spec(_write_spec(tmp_path, spec), tmp_path / 'out')
