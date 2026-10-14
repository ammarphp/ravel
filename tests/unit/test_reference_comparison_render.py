"""Two separately root-granted chart controls, never part of the pure batch.

Every source chart and coordinate is an explicit synthetic software fixture.
These exercises do not qualify an official figure, calibration or physics result.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from ravel.plotting import reference_comparison as comparison, figure_target
from test_reference_comparison import _request, _pin, _basis, _coordinates, _supplied_uncertainty


def _chart(path, doc):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FixedFormatter, NullFormatter
    # Literal 400x300 canvas and plot-area corners [60,40,360,240].
    with matplotlib.rc_context({'savefig.bbox': None, 'font.size': 8,
            'axes.labelsize': 9, 'axes.labelpad': 4,
            'xtick.labelsize': 8, 'ytick.labelsize': 8,
            'xtick.major.pad': 3, 'ytick.major.pad': 3,
            'xtick.minor.pad': 3, 'ytick.minor.pad': 3}):
        fig = plt.figure(figsize=(4,3), dpi=100)
        ax = fig.add_axes([.15,.2,.75,2/3])
        records = doc['series'][0]['records']
        artist = ax.plot([r['x'] for r in records],
                [r['y'] if r['status'] == 'delivered' else float('nan') for r in records])[0]
        for r in records:
            if r['status'] == 'delivered':
                ax.errorbar([r['x']], [r['y']], yerr=[[r['error_low']], [r['error_high']]],
                            fmt='none', color=artist.get_color(), ecolor=artist.get_color())
        ax.set(xlim=(200,350), ylim=(.1,1), yscale='log',
               xlabel=r'$m_{\ell\ell}$ [GeV]', ylabel=r'$\sigma$ [pb]')
        # Local source-fixture labels: standard physical ticks, no minor scientific labels.
        # Neither the physical limits nor the calibrated axes rectangle changes.
        ax.yaxis.set_major_locator(FixedLocator([.1, .2, .5, 1.]))
        ax.yaxis.set_major_formatter(FixedFormatter(['0.1', '0.2', '0.5', '1']))
        ax.yaxis.set_minor_formatter(NullFormatter())
        fig.canvas.draw()
        assert fig.canvas.get_width_height() == (400, 300)
        renderer = fig.canvas.get_renderer()
        assert ax.get_window_extent(renderer).bounds == pytest.approx((60, 60, 300, 200))
        texts = [ax.xaxis.label, ax.yaxis.label]
        for axis in (ax.xaxis, ax.yaxis):
            low, high = sorted(axis.get_view_interval())
            for tick in axis.get_major_ticks() + axis.get_minor_ticks():
                if low <= tick.get_loc() <= high:
                    texts.extend([tick.label1, tick.label2])
            texts.append(axis.offsetText)
        assert ax.get_yticks().tolist() == pytest.approx([.1, .2, .5, 1.])
        assert [label.get_text() for label in ax.get_yticklabels()] == ['0.1', '0.2', '0.5', '1']
        assert all(not label.get_text() for label in ax.get_yticklabels(minor=True))
        label_bounds = []
        for text in texts:
            if not text.get_visible() or not text.get_text():
                continue
            bounds = text.get_window_extent(renderer)
            assert 0 <= bounds.x0 < bounds.x1 <= 400
            assert 0 <= bounds.y0 < bounds.y1 <= 300
            label_bounds.append({'text': text.get_text(), 'bounds': list(bounds.bounds)})
        Path(str(path)+'.layout.json').write_text(json.dumps({
            'canvas': [400, 300], 'crop': [60, 40, 360, 240],
            'source_labels_within_canvas': True, 'label_bounds': label_bounds,
            'scientific_qualification': False}, indent=2))
        fig.savefig(path, dpi=100)
        plt.close(fig)


def _prepare(tmp_path, kind):
    target, request = _request(tmp_path, kind)
    doc = _supplied_uncertainty(_coordinates())
    request['agent'] = _pin(tmp_path / 'agent.json', doc)
    request['reference'] = _pin(tmp_path / 'official.json', doc)
    generated = tmp_path / 'generated.png'; _chart(generated, doc)
    request['counterpart'] = comparison.file_pin(generated)
    image = tmp_path / 'synthetic-source.png'; _chart(image, doc)
    pin = comparison.file_pin(image)
    target['extracted_image'] = {'path': pin['path'], 'route': 'synthetic software fixture'}
    target['reference_comparison'] = {'schema_version': 1, 'deliverable': 'reference-comparison', 'state': 'pending'}
    if kind == 'raster':
        request['reference'] = {'image': pin, 'axes': doc['axes'], 'basis': _basis(),
            'calibration': {'format': 'png', 'image_size': [400,300],
                'crop': [60,40,360,240],
                'x': [{'pixel':60,'value':200},{'pixel':360,'value':350}],
                'y': [{'pixel':40,'value':1},{'pixel':240,'value':.1}],
                'source_note': 'Synthetic fixed axes [.15,.2,.75,2/3]; no official data claim'}}
        request['numerical_reference_availability'] = {'state': 'unavailable',
            'reason': 'Synthetic raster-only software fixture; not an acquired reference',
            'sources': request['applicability']['sources']}
    request_path = tmp_path / 'request.json'; _pin(request_path, request)
    figure_target.save_contract(tmp_path, {'schema_version': 1, 'targets': [target]})
    return request_path


def _compose(tmp_path, request_path, monkeypatch):
    from matplotlib.axes import Axes
    errors = []
    original_errorbar = Axes.errorbar
    def observed_errorbar(self, *args, **kwargs):
        errors.append((args, kwargs, self))
        return original_errorbar(self, *args, **kwargs)
    monkeypatch.setattr(Axes, 'errorbar', observed_errorbar)
    out = tmp_path / 'plots' / 'side-by-side.png'
    figure_target.cmd_compose(SimpleNamespace(rundir=str(tmp_path), figure_id='Figure 3',
        out=str(out), comparison_request=str(request_path)))
    target = figure_target.load_contract(tmp_path)['targets'][0]
    assert Path(target['side_by_side']).is_file() and target['side_by_side'] == str(out)
    assert comparison.verify_target_comparison(target) == []
    pins = target['reference_comparison']['overlays']
    assert {Path(pin['path']).suffix for pin in pins} == {'.png', '.pdf'}
    assert all(Path(pin['path']).stat().st_size > 100 for pin in pins)
    from PIL import Image
    with Image.open(next(pin['path'] for pin in pins if pin['path'].endswith('.png'))) as image:
        assert image.width > 100 and image.height > 100
    receipt = json.loads(Path(target['reference_comparison']['receipt']['path']).read_bytes())
    # Concrete root-view paths are retained beside the actual contract, not inferred from test success.
    (tmp_path / 'ROOT-VISUAL-INSPECTION.json').write_text(json.dumps({
        'side_by_side': target['side_by_side'], 'source_image': str(tmp_path/'synthetic-source.png'),
        'generated': str(tmp_path/'generated.png'), 'receipt': target['reference_comparison']['receipt'],
        'source_layout': str(tmp_path/'synthetic-source.png.layout.json'),
        'generated_layout': str(tmp_path/'generated.png.layout.json'),
        'overlays': pins, 'scientific_qualification': False}, indent=2))
    return receipt, errors


def test_actual_numerical_plot_route(tmp_path, monkeypatch):
    request_path = _prepare(tmp_path, 'numerical')
    receipt, errors = _compose(tmp_path, request_path, monkeypatch)
    assert receipt['visual_only'] is False and receipt['numerical_reference'] is True
    assert receipt['numerical_fidelity'] is None and receipt['physics_validated'] is False
    assert len(errors) == 4  # Two delivered records in each complete agent/reference population.
    assert errors[0][1]['yerr'][0][0] == pytest.approx(.05)
    assert errors[0][1]['yerr'][1][0] == pytest.approx(.1)
    assert all(error[1]['color'] == error[1]['ecolor'] for error in errors)
    assert errors[0][1]['color'] == errors[1][1]['color']
    assert errors[2][1]['color'] == errors[3][1]['color']
    assert errors[0][1]['color'] != errors[2][1]['color']
    ax = errors[0][2]
    assert ax.get_xlim()[0] < 250 and ax.get_xlim()[1] > 275
    assert ax.get_xmargin() == pytest.approx(.06) and ax.get_ymargin() == pytest.approx(.06)
    assert receipt['population']['agent']['series'][0]['records'][1]['status'] == 'unknown'


def test_actual_calibrated_log_image_plot_route(tmp_path, monkeypatch):
    request_path = _prepare(tmp_path, 'raster')
    receipt, errors = _compose(tmp_path, request_path, monkeypatch)
    assert receipt['numerical_fidelity'] is None and receipt['visual_only'] is True
    assert receipt['numerical_reference'] is False and receipt['physics_validated'] is False
    assert len(errors) == 2
    calibration = receipt['population']['reference_image']['calibration']
    record = receipt['population']['agent']['series'][0]['records'][0]
    axis = receipt['population']['agent']['axes']['y']
    center = comparison.pixel_coordinate(record['y'], axis, calibration['y'])
    endpoints = [comparison.pixel_coordinate(record['y']-record['error_low'], axis, calibration['y']),
                 comparison.pixel_coordinate(record['y']+record['error_high'], axis, calibration['y'])]
    assert errors[0][1]['yerr'][0][0] == pytest.approx(center-min(endpoints))
    assert errors[0][1]['yerr'][1][0] == pytest.approx(max(endpoints)-center)
    ax = errors[0][2]
    assert ax.get_xlim() == pytest.approx((60, 360))
    assert ax.get_ylim() == pytest.approx((240, 40))
    assert [text.get_text() for text in ax.get_yticklabels()] == ['0.1', '0.2', '0.5', '1']
    assert ax.get_yticks().tolist() == pytest.approx([
        comparison.pixel_coordinate(value, axis, calibration['y']) for value in (.1, .2, .5, 1.)])
