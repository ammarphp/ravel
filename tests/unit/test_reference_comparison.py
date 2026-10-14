"""Focused software controls. Render callbacks are inert unless marked render.

These fixtures do not establish scientific equivalence or real publication QA.
"""
import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from ravel.plotting import display_labels as labels
from ravel.plotting import reference_comparison as comparison
from ravel.plotting import figure_target


def _basis():
    return {'quantity': 'cross-section limit', 'model': 'declared software model',
            'production': 'declared channel', 'width': 'declared width',
            'branching_fraction': 'declared branching fraction', 'energy': '13 TeV',
            'normalization': 'pb', 'interference': 'declared absent',
            'response': 'declared source response'}


def _coordinates():
    return {'schema_version': 1, 'kind': 'plot-coordinate-series', 'basis': _basis(),
            'axes': {'x': {'quantity': 'mass', 'name': 'm_ll', 'unit': 'GeV', 'scale': 'linear'},
                     'y': {'quantity': 'cross_section', 'name': 'sigma', 'unit': 'pb', 'scale': 'log'}},
            'series': [{'id': 'observed_curve', 'label': 'Observed limit', 'geometry': 'polyline',
                        'records': [{'id': 'point-1', 'x': 250., 'y': .5, 'status': 'delivered'},
                                    {'id': 'point-2', 'x': 300., 'y': None, 'status': 'unknown', 'reason': 'not available'},
                                    {'id': 'point-3', 'x': 275., 'y': .4, 'status': 'delivered'}]}]}


def _pin(path, value):
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    return comparison.file_pin(path)


def _request(tmp_path, kind='numerical'):
    target = {'figure_id': 'Figure 3', 'paper': {'arxiv': 'software-fixture', 'inspire': None, 'code': None},
              'generated_counterpart': {'path': str(tmp_path / 'generated.png')},
              'axes': {'x':'linear','y':'log','source':'read-from-published'}}
    counterpart = _pin(tmp_path / 'generated.png', b'Inert generated figure; not a real render')
    source = _pin(tmp_path / 'basis.txt', b'Explicit software applicability fixture only')
    request = {'schema_version': 1, 'kind': kind,
               'target': {'figure_id': target['figure_id'], 'paper': target['paper']},
               'counterpart': counterpart,
               'applicability': {'state': 'comparable', 'reason': 'matching synthetic declared basis', 'sources': [source]},
               'agent': _pin(tmp_path / 'agent.json', _coordinates()),
               'reference': _pin(tmp_path / 'official.json', _coordinates())}
    return target, request


def _inert_render(agent, reference, directory, image=None, calibration=None, source_note=None):
    (directory / 'overlay.png').write_bytes(b'Inert PNG artifact for source/API control')
    (directory / 'overlay.pdf').write_bytes(b'Inert PDF artifact for source/API control')


@pytest.mark.parametrize('identifier,expected', [
    ('m_ll', r'$m_{\ell\ell}$'), ('p_T', r'$p_{\mathrm{T}}$'),
    ('unknown_bin_17', 'unknown bin 17'), ('signal + background', 'signal + background')])
def test_display_spelling_preserves_scientific_notation(identifier, expected):
    assert labels.display_label(identifier) == expected
    assert labels.label_errors(expected) == []


def test_units_operators_and_explicit_labels_are_preserved():
    assert labels.axis_label({'name': 'p_T', 'unit': 'GeV/c^2'}) == r'$p_{\mathrm{T}}$ [$GeV/c^2$]'
    assert labels.display_label('opaque_id', 'Tested signal') == 'Tested signal'
    with pytest.raises(ValueError):
        labels.display_label('opaque_id', 'raw_internal_id')
    assert labels.display_label('m(#tilde{chi}_{1}^{0})') == r'$m(\tilde{chi}_{1}^{0})$'


def test_whole_population_unknown_and_polyline_order_are_not_rewritten():
    doc = _coordinates(); before = copy.deepcopy(doc)
    assert comparison._coordinates(doc) == before
    assert [r['x'] for r in doc['series'][0]['records']] == [250., 300., 275.]
    assert doc['series'][0]['records'][1]['y'] is None


@pytest.mark.parametrize('field', ['energy', 'width', 'branching_fraction', 'normalization', 'production', 'interference'])
def test_heterogeneous_physics_basis_cannot_be_overlaid(field):
    agent = _coordinates(); reference = copy.deepcopy(agent)
    reference['basis'][field] = 'different declared value'
    with pytest.raises(ValueError, match='basis'):
        comparison._comparable(agent, reference)


@pytest.mark.parametrize('field', ['quantity', 'unit', 'scale'])
def test_axis_identity_units_and_scale_must_match(field):
    agent = _coordinates(); reference = copy.deepcopy(agent)
    reference['axes']['x'][field] = 'different'
    with pytest.raises(ValueError, match='axis'):
        comparison._comparable(agent, reference)


def test_log_calibration_is_affine_in_log_not_raw_coordinate():
    axis = {'scale': 'log'}
    anchors = [{'pixel': 10., 'value': 100.}, {'pixel': 210., 'value': 10000.}]
    assert comparison.pixel_coordinate(1000., axis, anchors) == pytest.approx(110.)
    assert comparison.pixel_coordinate(100., axis, anchors) == pytest.approx(10.)
    y = [{'pixel': 20., 'value': 100.}, {'pixel': 220., 'value': .01}]
    assert comparison.pixel_coordinate(1., axis, y) == pytest.approx(120.)
    with pytest.raises(ValueError):
        comparison.pixel_coordinate(0., axis, anchors)


def test_linear_calibration_and_degenerate_anchor_refusal():
    anchors = [{'pixel': 20., 'value': -5.}, {'pixel': 120., 'value': 5.}]
    assert comparison.pixel_coordinate(0., {'scale': 'linear'}, anchors) == pytest.approx(70.)
    with pytest.raises(ValueError, match='degenerate'):
        comparison.pixel_coordinate(1., {'scale': 'linear'}, [anchors[0], anchors[0]])


def test_all_unknown_is_not_a_delivered_agent_overlay():
    doc = _coordinates()
    for record in doc['series'][0]['records']:
        record.update(y=None, status='unknown', reason='missing')
    with pytest.raises(ValueError, match='no delivered'):
        comparison._coordinates(doc)


def test_source_bound_ordinary_delivery_and_gate(tmp_path, monkeypatch):
    target, request = _request(tmp_path)
    pin = _pin(tmp_path / 'request.json', request)
    monkeypatch.setattr(comparison, '_render_coordinates', _inert_render)
    target['reference_comparison'] = comparison.deliver(pin, target, tmp_path)
    assert comparison.verify_target_comparison(target) == []
    receipt = json.loads(Path(target['reference_comparison']['receipt']['path']).read_bytes())
    assert receipt['numerical_reference'] is True and receipt['visual_only'] is False
    assert receipt['numerical_fidelity'] is None and receipt['physics_validated'] is False
    assert len(receipt['population']['agent']['series'][0]['records']) == 3
    assert {Path(p['path']).suffix for p in target['reference_comparison']['overlays']} == {'.png', '.pdf'}


def test_original_input_change_before_delivery_refuses(tmp_path, monkeypatch):
    target, request = _request(tmp_path)
    def callback(*args, **kwargs):
        _inert_render(*args, **kwargs)
        Path(request['reference']['path']).write_text('{}')
    monkeypatch.setattr(comparison, '_render_coordinates', callback)
    with pytest.raises(ValueError, match='input changed'):
        comparison.deliver(_pin(tmp_path / 'request.json', request), target, tmp_path)


def test_current_output_change_does_not_rebaseline_receipt(tmp_path, monkeypatch):
    target, request = _request(tmp_path)
    monkeypatch.setattr(comparison, '_render_coordinates', _inert_render)
    target['reference_comparison'] = comparison.deliver(_pin(tmp_path / 'request.json', request), target, tmp_path)
    Path(target['reference_comparison']['overlays'][0]['path']).write_bytes(b'changed')
    assert comparison.verify_target_comparison(target)


def test_raster_receipt_never_claims_numerical_reference(tmp_path, monkeypatch):
    target, request = _request(tmp_path, 'raster')
    request['reference'] = {'axes': _coordinates()['axes'], 'basis': _basis(),
                            'image': _pin(tmp_path / 'official.png', b'Inert image fixture'),
                            'calibration': {'format': 'png', 'source_note': 'Explicit fixture anchors',
                                            'image_size':[100,100], 'crop':[10,10,90,90],
                                            'x':[{'pixel':10,'value':250},{'pixel':90,'value':350}],
                                            'y':[{'pixel':10,'value':1},{'pixel':90,'value':.1}]}}
    target['extracted_image']={'path':request['reference']['image']['path']}
    request['numerical_reference_availability']={'state':'unavailable','reason':'No numerical fixture supplied',
                                                'sources':request['applicability']['sources']}
    monkeypatch.setattr(comparison, '_render_coordinates', _inert_render)
    target['reference_comparison'] = comparison.deliver(_pin(tmp_path / 'request.json', request), target, tmp_path)
    receipt = json.loads(Path(target['reference_comparison']['receipt']['path']).read_bytes())
    assert receipt['visual_only'] is True and receipt['numerical_reference'] is False
    assert comparison.verify_target_comparison(target) == []


def _declare_args(tmp_path, **updates):
    values = dict(rundir=str(tmp_path), figure_id='Figure 3', caption='Software comparison fixture',
                  role='overlay', primary=True, source='user-prompt', arxiv='software-fixture',
                  inspire=None, code=None, hepdata_table=None, axes_x='linear', axes_y='log',
                  axes_source='read-from-published', style_json=None, no_checkin=False)
    values.update(updates)
    return SimpleNamespace(**values)


def test_new_referenced_declaration_defaults_to_required_overlay(tmp_path):
    figure_target.cmd_declare(_declare_args(tmp_path))
    target = figure_target.load_contract(tmp_path)['targets'][0]
    assert target['reference_comparison']['deliverable'] == 'reference-comparison'
    assert comparison.verify_target_comparison(target)


def test_historical_target_is_not_migrated_on_merge(tmp_path):
    figure_target.cmd_declare(_declare_args(tmp_path))
    doc = figure_target.load_contract(tmp_path)
    del doc['targets'][0]['reference_comparison']
    figure_target.save_contract(tmp_path, doc)
    figure_target.cmd_declare(_declare_args(tmp_path))
    assert 'reference_comparison' not in figure_target.load_contract(tmp_path)['targets'][0]


def test_description_synthesis_is_explicit_noncomparison(tmp_path):
    figure_target.cmd_declare(_declare_args(tmp_path, figure_id=None, source='description-only'))
    target = figure_target.load_contract(tmp_path)['targets'][0]
    assert target['reference_comparison']['state'] == 'no-reference'
    assert comparison.verify_target_comparison(target) == []
    assert not target['reference_comparison'].get('overlays')


def test_existing_scan_driver_uses_all_pinned_inputs_and_original_argv(tmp_path, monkeypatch):
    from ravel.plotting import scan_contour, mplhep_style
    from test_declarative_scan_plots import contract
    target, request = _request(tmp_path, 'existing-numerical')
    request.pop('agent'); request.pop('reference')
    data, spec = contract(tmp_path)
    spec['presentation'] = {'experiment': 'CMS', 'com': 7., 'lumi': 2.}
    spec['axes']['y']['scale'] = 'log'
    for point in data['points']:
        point['beta'] += 1
    request['basis'] = _basis(); data['model_basis'] = request['basis']
    request['axes'] = {key: {'quantity': row['quantity'], 'name': row['label'],
                            'unit': row['unit'], 'scale': row['scale']}
                       for key, row in spec['axes'].items()}
    spec['layers'] = [{'kind': 'reference-contour', 'label': 'Supplied reference', 'quantity': 'observed',
        'reference': {'quantity': 'observed', 'basis': request['basis'],
                      'axes': {key: {f: row[f] for f in ('quantity', 'unit')} for key, row in spec['axes'].items()},
                      'records': [{'x': 0, 'y': 1}, {'x': 1, 'y': 2}]}}]
    request['renderer'] = {'renderer': 'scan_contour', **spec['presentation'],
                           'scan': _pin(tmp_path / 'scan.json', data),
                           'plot_spec': _pin(tmp_path / 'plot.json', spec)}
    captured = []
    def original_route(argv):
        captured.extend(argv)
        selected = json.loads(Path(argv[argv.index('--plot-spec')+1]).read_text())
        assert selected['axes'] == spec['axes']
        assert selected['layers'] == spec['layers']
        for output in selected['outputs']:
            Path(output['path']).write_bytes(b'Inert selected plot for source/API control')
    monkeypatch.setattr(mplhep_style, 'apply_style', lambda *a, **k: None)
    monkeypatch.setattr(scan_contour, 'main', original_route)
    target['reference_comparison'] = comparison.deliver(_pin(tmp_path / 'request.json', request), target, tmp_path)
    assert '--no-lint' not in captured
    assert '--plot-spec' in captured
    assert '--layout' not in captured
    assert comparison.verify_target_comparison(target) == []


def test_pack_gate_enforces_pending_prospective_contract(tmp_path):
    from ravel.validation import verify_pack
    class Reporter:
        def __init__(self): self.failures = []
        def fail(self, name, message): self.failures.append(message)
        def ok(self, *args): pass
        def warn(self, *args): pass
    target, _ = _request(tmp_path)
    target['reference_comparison'] = {'schema_version': 1, 'deliverable': 'reference-comparison', 'state': 'pending'}
    reporter = Reporter()
    verify_pack.check_figure_target(reporter, str(tmp_path), [], 'fixture', {'targets': [target]})
    assert any('overlay remains undelivered' in message for message in reporter.failures)


def test_run_state_gate_uses_same_prospective_obligation(tmp_path, monkeypatch):
    from ravel.validation import validate_run_state
    target, _ = _request(tmp_path)
    target['reference_comparison'] = {'schema_version': 1, 'deliverable': 'reference-comparison', 'state': 'pending'}
    path = tmp_path / 'inputs' / 'figure_target.json'; path.parent.mkdir()
    path.write_text(json.dumps({'schema_version': 1, 'targets': [target]}))
    # Level O is an explicit scan-policy software fixture, not a review approval.
    monkeypatch.setattr(validate_run_state, 'resolve_level', lambda *args: 'O')
    status, message = validate_run_state.inv_figure_contract_fulfilled(
        str(tmp_path), {'task_mode': 'scan'},
        {'figure_target_path': str(path), 'generation_hits': ['synthetic-generation']}, False, True)
    assert status == 'FAIL' and 'overlay remains undelivered' in message


def test_declared_scale_change_invalidates_delivered_comparison(tmp_path, monkeypatch):
    target, request = _request(tmp_path)
    monkeypatch.setattr(comparison, '_render_coordinates', _inert_render)
    target['reference_comparison'] = comparison.deliver(_pin(tmp_path / 'request.json', request), target, tmp_path)
    target['axes']['x'] = 'log'
    assert any('scales differ' in value for value in comparison.verify_target_comparison(target))


def test_calibration_requires_actual_crop_corner_anchors():
    reference = {'axes': _coordinates()['axes'], 'calibration': {
        'format': 'png', 'image_size': [100,100], 'source_note': 'inspected software corners',
        'crop':[10,10,90,90], 'x':[{'pixel':10,'value':200},{'pixel':90,'value':500}],
        'y':[{'pixel':10,'value':1},{'pixel':90,'value':.1}]}}
    assert comparison._calibration(reference)['crop'] == [10,10,90,90]
    reference['calibration']['x'][0]['pixel'] = 11
    with pytest.raises(ValueError, match='crop corners'):
        comparison._calibration(reference)


def test_existing_distribution_rejects_gap_without_changing_values():
    from ravel.plotting import overlay_on_data
    class Bin:
        def __init__(self, low, high, value): self.low,self.high,self.value = low,high,value
        def xMin(self): return self.low
        def xMax(self): return self.high
        def val(self): return self.value
        def errAvg(self): return .1
    class Object:
        def __init__(self, bins): self._bins = bins
        def bins(self): return self._bins
    good = Object([Bin(0,1,2), Bin(1,3,5)])
    edges, values, errors = overlay_on_data.series(good)
    assert list(edges) == [0,1,3] and list(values) == [2,5] and list(errors) == [.1,.1]
    with pytest.raises(ValueError, match='contiguous'):
        overlay_on_data.series(Object([Bin(0,1,2), Bin(2,3,5)]))


_PEER = Path(__file__).parent / 'fixtures' / 'reference-comparison-peer-v1'


def _peer(name):
    return json.loads((_PEER / name).read_bytes())


def _supplied_uncertainty(doc):
    doc = copy.deepcopy(doc)
    for row in doc['series']:
        row['uncertainty'] = {'convention': 'absolute-y-offsets',
                              'meaning': 'Supplied software-fixture asymmetric errors; no inferred confidence law'}
        for record in row['records']:
            if record['status'] == 'delivered':
                record.update(error_low=.05, error_high=.1)
    return doc


def test_exact_peer_internal_labels_require_semantic_names():
    for case in _peer('opaque-label-inputs.json')['cases']:
        with pytest.raises(ValueError, match='semantic display label'):
            labels.display_label(case['identifier'], case['explicit'])
    assert labels.display_label('sr_3_obs_0', 'Missing transverse momentum selection') == \
        'Missing transverse momentum selection'
    assert labels.label_errors('sr 3 obs 0')


def test_exact_peer_unequal_integrated_bin_domains_refuse():
    agent = comparison._coordinates(_peer('bin-domain-agent.json'))
    reference = comparison._coordinates(_peer('bin-domain-reference.json'))
    with pytest.raises(ValueError, match='bin support'):
        comparison._comparable(agent, reference)


def test_unknown_bin_population_and_all_series_support_are_complete():
    doc = _coordinates()
    doc['series'][0]['geometry'] = 'bins'
    for i, record in enumerate(doc['series'][0]['records']):
        record.update(x=i+.5, low=i, high=i+1)
    original = comparison._coordinates(copy.deepcopy(doc))
    comparison._comparable(original, comparison._coordinates(copy.deepcopy(doc)))
    missing = copy.deepcopy(doc); missing['series'][0]['records'].pop(1)
    with pytest.raises(ValueError, match='bin support'):
        comparison._comparable(original, comparison._coordinates(missing))
    mismatch = copy.deepcopy(doc)
    extra = copy.deepcopy(mismatch['series'][0]); extra['id'] = 'other'; extra['label'] = 'Other prediction'
    extra['records'].pop(1); mismatch['series'].append(extra)
    with pytest.raises(ValueError, match='interval support'):
        comparison._comparable(original, comparison._coordinates(mismatch))
    mixed = copy.deepcopy(doc); mixed['series'][0]['geometry'] = 'markers'
    for record in mixed['series'][0]['records']:
        del record['low']; del record['high']
    with pytest.raises(ValueError, match='bin support'):
        comparison._comparable(original, comparison._coordinates(mixed))


def test_independent_curve_grids_remain_literal_and_comparable():
    agent = _coordinates(); reference = copy.deepcopy(agent)
    reference['series'][0]['records'][0]['x'] = 255.
    reference['series'][0]['records'][2]['x'] = 270.
    comparison._comparable(comparison._coordinates(agent), comparison._coordinates(reference))
    assert [r['x'] for r in reference['series'][0]['records']] == [255., 300., 270.]


def test_exact_peer_errors_need_an_explicit_convention():
    for name in ('supplied-errors-agent.json', 'supplied-errors-reference.json'):
        with pytest.raises(ValueError, match='unsupported fields'):
            comparison._coordinates(_peer(name))
        doc = _peer(name)
        for row in doc['series']:
            meaning = row.pop('uncertainty_scope')
            row['uncertainty'] = {'convention': 'absolute-y-offsets',
                                  'meaning': meaning}
        assert comparison._coordinates(doc) == doc


@pytest.mark.parametrize('field', ['covariance', 'error_low', 'error_high', 'efficiency'])
def test_unsupported_scientific_record_content_is_not_discarded(field):
    doc = _coordinates(); doc['series'][0]['records'][0][field] = .1
    with pytest.raises(ValueError, match='unsupported fields'):
        comparison._coordinates(doc)


def test_declared_uncertainty_complete_alignment_and_log_support():
    doc = _supplied_uncertainty(_coordinates())
    assert comparison._coordinates(copy.deepcopy(doc)) == doc
    absent = copy.deepcopy(doc); del absent['series'][0]['records'][2]['error_high']
    with pytest.raises(ValueError):
        comparison._coordinates(absent)
    unknown = copy.deepcopy(doc); unknown['series'][0]['records'][1]['error_low'] = .1
    with pytest.raises(ValueError, match='unknown records'):
        comparison._coordinates(unknown)
    crossing = copy.deepcopy(doc); crossing['series'][0]['records'][0]['error_low'] = .5
    with pytest.raises(ValueError, match='no clipping'):
        comparison._coordinates(crossing)
    unavailable = _coordinates()
    unavailable['series'][0]['uncertainty'] = {'convention': 'unavailable', 'meaning': 'Source has no errors'}
    assert comparison._coordinates(unavailable) == unavailable


def test_admitted_uncertainties_are_drawn_and_log_raster_endpoints_are_exact():
    class Axis:
        def __init__(self): self.lines, self.errors = [], []
        def plot(self, *args, **kwargs):
            self.lines.append((args, kwargs))
            return [SimpleNamespace(get_color=lambda: 'fixture-blue')]
        def errorbar(self, *args, **kwargs): self.errors.append((args, kwargs))
    doc = comparison._coordinates(_supplied_uncertainty(_coordinates()))
    ax = Axis(); comparison._draw_series(ax, doc, 'Agent')
    assert len(ax.errors) == 2
    assert ax.errors[0][1]['yerr'][0][0] == pytest.approx(.05)
    assert ax.errors[0][1]['yerr'][1][0] == pytest.approx(.1)
    assert math.isnan(ax.lines[0][0][1][1])
    anchors = [{'pixel': 40., 'value': 1.}, {'pixel': 240., 'value': .1}]
    def mapping(key, value):
        return value if key == 'x' else comparison.pixel_coordinate(value, {'scale': 'log'}, anchors)
    raster = Axis(); comparison._draw_series(raster, doc, 'Agent', mapping)
    record = doc['series'][0]['records'][0]
    center = mapping('y', record['y'])
    endpoints = [mapping('y', record['y']-record['error_low']),
                 mapping('y', record['y']+record['error_high'])]
    assert raster.errors[0][1]['yerr'][0][0] == pytest.approx(center-min(endpoints))
    assert raster.errors[0][1]['yerr'][1][0] == pytest.approx(max(endpoints)-center)


@pytest.mark.parametrize('geometry', ['bins', 'markers'])
def test_multiple_series_keep_actual_artist_error_and_legend_colors(geometry):
    class Axis:
        def __init__(self):
            self.lines, self.errors = [], []
            self.colors = iter(['fixture-teal', 'fixture-coral'])
        def plot(self, *args, **kwargs):
            color = kwargs.get('color')
            if color is None:
                color = next(self.colors)
            self.lines.append((args, kwargs, color))
            return [SimpleNamespace(get_color=lambda: color)]
        def errorbar(self, *args, **kwargs):
            self.errors.append((args, kwargs))
    doc = _supplied_uncertainty(_coordinates())
    row = doc['series'][0]; row['geometry'] = geometry
    if geometry == 'bins':
        for index, record in enumerate(row['records']):
            record.update(x=index+.5, low=index, high=index+1)
    other = copy.deepcopy(row)
    other.update(id='alternative_prediction', label='Alternative prediction')
    doc['series'].append(other)
    original = copy.deepcopy(doc)
    ax = Axis(); comparison._draw_series(ax, comparison._coordinates(doc), 'Agent')
    assert doc == original
    comparison._comparable(doc, copy.deepcopy(doc))
    assert len(ax.errors) == 4
    assert ax.lines[0][1]['label'] == 'Agent: Observed limit'
    assert [error[1]['color'] for error in ax.errors] == ['fixture-teal']*2 + ['fixture-coral']*2
    assert all(error[1]['ecolor'] == error[1]['color'] for error in ax.errors)
    if geometry == 'bins':
        assert len(ax.lines) == 4
        assert [line[2] for line in ax.lines] == ['fixture-teal']*2 + ['fixture-coral']*2
        assert ax.lines[1][1]['color'] == 'fixture-teal' and ax.lines[1][1]['label'] is None
        assert ax.lines[2][1]['label'] == 'Agent: Alternative prediction'
        assert ax.lines[3][1]['color'] == 'fixture-coral' and ax.lines[3][1]['label'] is None
        assert ax.lines[0][0] == ([0, 1], [.5, .5])
        assert ax.lines[1][0] == ([2, 3], [.4, .4])
    else:
        assert len(ax.lines) == 2
        assert [line[2] for line in ax.lines] == ['fixture-teal', 'fixture-coral']
        assert ax.lines[1][1]['label'] == 'Agent: Alternative prediction'
        assert math.isnan(ax.lines[0][0][1][1])


def test_physical_image_ticks_use_standard_values_and_exact_existing_mapping():
    log_axis = {'scale': 'log'}
    anchors = [{'pixel': 40., 'value': 1.}, {'pixel': 240., 'value': .1}]
    values = comparison._physical_ticks(log_axis, anchors)
    assert values == [.1, .2, .5, 1.]
    assert [comparison.pixel_coordinate(v, log_axis, anchors) for v in values] == pytest.approx(
        [240., 179.79400086720375, 100.20599913279625, 40.])
    linear = comparison._physical_ticks({'scale': 'linear'},
        [{'pixel': 60., 'value': 200.}, {'pixel': 360., 'value': 350.}])
    assert linear == [200., 250., 300., 350.]
    narrow = comparison._physical_ticks(log_axis,
        [{'pixel': 40., 'value': .99}, {'pixel': 240., 'value': 1.01}])
    assert len(narrow) >= 2 and all(.99 <= value <= 1.01 for value in narrow)


@pytest.mark.parametrize('change', ['coordinate', 'boolean-value', 'omitted-record', 'uncertainty', 'missing-source', 'kind'])
def test_saved_population_and_kind_match_original_pinned_documents(tmp_path, monkeypatch, change):
    target, request = _request(tmp_path)
    agent = _supplied_uncertainty(_coordinates())
    if change == 'boolean-value':
        agent['series'][0]['records'][0]['y'] = 1.0
    request['agent'] = _pin(tmp_path / 'agent.json', agent)
    request['reference'] = _pin(tmp_path / 'official.json', copy.deepcopy(agent))
    monkeypatch.setattr(comparison, '_render_coordinates', _inert_render)
    target['reference_comparison'] = comparison.deliver(_pin(tmp_path / 'request.json', request), target, tmp_path)
    assert comparison.verify_target_comparison(target) == []
    path = Path(target['reference_comparison']['receipt']['path'])
    receipt = json.loads(path.read_bytes())
    if change == 'coordinate':
        receipt['population']['agent']['series'][0]['records'][0]['y'] = .7
    elif change == 'boolean-value':
        receipt['population']['agent']['series'][0]['records'][0]['y'] = True
    elif change == 'omitted-record':
        receipt['population']['agent']['series'][0]['records'].pop(1)
    elif change == 'uncertainty':
        receipt['population']['agent']['series'][0]['records'][0]['error_high'] = .2
    elif change == 'missing-source':
        receipt['input_pins'].pop()
    else:
        receipt.update(comparison_kind='raster', visual_only=True, numerical_reference=False)
    target['reference_comparison']['receipt'] = _pin(path, receipt)
    assert comparison.verify_target_comparison(target)


def test_raster_cannot_be_serialized_as_numerical_delivery(tmp_path, monkeypatch):
    target, request = _request(tmp_path, 'raster')
    image = _pin(tmp_path / 'reference.png', b'Inert image source; no actual renderer')
    target['extracted_image'] = {'path': image['path'], 'route': 'software-fixture'}
    request['reference'] = {'image': image, 'axes': _coordinates()['axes'], 'basis': _basis(),
                            'calibration': {'format': 'png', 'image_size': [100,100],
                                'crop': [10,10,90,90], 'source_note': 'Literal fixture axes',
                                'x': [{'pixel':10,'value':200},{'pixel':90,'value':350}],
                                'y': [{'pixel':10,'value':1},{'pixel':90,'value':.1}]}}
    request['numerical_reference_availability'] = {'state': 'unavailable', 'reason': 'Software fixture only',
        'sources': request['applicability']['sources']}
    monkeypatch.setattr(comparison, '_render_coordinates', _inert_render)
    target['reference_comparison'] = comparison.deliver(_pin(tmp_path / 'request.json', request), target, tmp_path)
    assert comparison.verify_target_comparison(target) == []
    path = Path(target['reference_comparison']['receipt']['path']); receipt = json.loads(path.read_bytes())
    receipt.update(comparison_kind='numerical', visual_only=False, numerical_reference=True)
    target['reference_comparison']['receipt'] = _pin(path, receipt)
    assert comparison.verify_target_comparison(target)


def test_renderer_preserves_the_original_admitted_population(tmp_path, monkeypatch):
    target, request = _request(tmp_path)
    def changed_population(agent, reference, directory, **kwargs):
        _inert_render(agent, reference, directory)
        agent['series'][0]['records'][0]['y'] = .7
    monkeypatch.setattr(comparison, '_render_coordinates', changed_population)
    with pytest.raises(ValueError, match='originally admitted'):
        comparison.deliver(_pin(tmp_path/'request.json', request), target, tmp_path)
