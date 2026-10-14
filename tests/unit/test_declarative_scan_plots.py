"""Fictional contracts exercise plotting without native or network work."""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pytest

from ravel.plotting import scan_contour as plotting


def contract(tmp_path, identity='ANA-0001', columns=('alpha', 'beta'), size=2, fmt='png'):
    x, y = columns
    axes = {key: {'column': col, 'quantity': col, 'unit': 'unitless',
                  'label': col.replace('_', ' ').title(), 'scale': 'linear'}
            for key, col in zip(('x', 'y'), columns)}
    data = {'analysis_id': identity, 'n_planned': size * size + 1,
            'data_schema': {'columns': {col: {'quantity': col, 'unit': 'unitless'} for col in columns}},
            'points': [{x: i, y: j, 'mu95_obs': .5 if i == 0 else 2,
                        'tag': f'{i}-{j}'} for i in range(size) for j in range(size)]}
    spec = {'schema_version': 1, 'axes': axes,
            'presentation': {'experiment': 'Fictional', 'com': 7, 'lumi': 2},
            'layers': [{'kind': 'points', 'label': identity, 'quantity': 'observed'},
                       {'kind': 'contour', 'label': 'Supplied limit boundary', 'quantity': 'observed', 'level': 1}],
            'outputs': [{'path': str(tmp_path / (identity + '.' + fmt)), 'format': fmt}]}
    return data, spec


def test_scan_cli_requires_supplied_plot_spec(tmp_path):
    data, _ = contract(tmp_path)
    path = tmp_path / 'scan.json'; path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='missing_plot_input'):
        plotting.main(['--scan', str(path), '--experiment', 'CMS', '--com', '7', '--lumi', '2', '--out', str(tmp_path/'out')])
    assert not list(tmp_path.glob('out*'))


def test_arbitrary_axes_and_requested_outputs_use_same_renderer(tmp_path):
    reports = []
    for identity, columns, size, fmt in [('ANA-0001', ('alpha', 'beta'), 2, 'png'),
                                        ('ANA-0002', ('gamma', 'delta'), 3, 'pdf')]:
        data, spec = contract(tmp_path, identity, columns, size, fmt)
        spec['presentation'].update(com=5 + size, lumi=size)
        data['model_basis'] = {'production': 'supplied fictional basis'}
        reference = {'quantity': 'observed', 'basis': data['model_basis'],
                     'axes': {key: {f: axis[f] for f in ('quantity', 'unit')} for key, axis in spec['axes'].items()},
                     'records': [{'x': i, 'y': .5 + i / 2} for i in range(size)]}
        spec['layers'].append({'kind': 'reference-contour', 'label': 'Supplied reference dataset',
                               'quantity': 'observed', 'reference': reference})
        report = plotting.render_spec(data, spec)
        assert report['layers'][-1]['records'] == reference['records']
        assert report['axes'] == spec['axes']
        assert report['recorded'] == size * size
        assert report['planned'] == size * size + 1
        assert report['outputs'] == spec['outputs']
        assert Path(spec['outputs'][0]['path']).stat().st_size > 100
        assert report['analysis_id'] == identity
        reports.append(report)
    assert len(list(tmp_path.iterdir())) == 2
    assert reports[0]['population'] != reports[1]['population']


@pytest.mark.parametrize('field', ['axes', 'layers', 'outputs', 'presentation'])
def test_missing_plot_inputs_are_typed_before_drawing(tmp_path, field, monkeypatch):
    data, spec = contract(tmp_path); del spec[field]
    monkeypatch.setattr(plt, 'subplots', lambda *a, **k: pytest.fail('draw before validation'))
    with pytest.raises(ValueError, match='missing_plot_input') as error:
        plotting.render_spec(data, spec)
    assert error.value.code == 'missing_plot_input'
    assert not list(tmp_path.iterdir())


def test_schema_axis_mismatch_retains_protective_gate(tmp_path):
    data, spec = contract(tmp_path)
    spec['axes']['x']['quantity'] = 'other'
    with pytest.raises(ValueError, match='axis_schema_mismatch'):
        plotting.render_spec(data, spec)


def test_no_prescribed_figure_layout_or_number_in_product():
    source = Path(plotting.__file__).read_text()
    assert 'render_fig3' not in source
    assert '__fig3' not in source
    assert 'm_slepton' not in source


def test_migration_preserves_bounds_and_lattice_holes(tmp_path):
    data, spec = contract(tmp_path, size=3)
    data['points'][4]['quality'] = 'capped'
    data['points'][4]['mu95_obs'] = 2
    report = plotting.render_spec(data, spec)
    assert report['population'][4]['limits'] == plotting.read_limits(data['points'][4]).to_dict()
    assert report['layers'][0]['eligible'] == 8
    assert report['layers'][1]['masked_triangles'] > 0
    assert report['missing_scan_points'] == 1


def test_comparison_missing_plot_spec_is_typed(tmp_path):
    from ravel.plotting import reference_comparison as comparison
    config = {'renderer': 'scan_contour', 'experiment': 'CMS', 'com': 7, 'lumi': 2,
              'layout': 'grid', 'limit_kind': 'observed', 'scan': {}, 'contours': []}
    request = {'renderer': config, 'axes': {
        key: {'quantity': col, 'name': col, 'unit': 'unitless', 'scale': 'linear'}
        for key, col in zip(('x', 'y'), ('alpha', 'beta'))},
        'basis': {'normalization': 'mu', 'state_content': 'supplied', 'prediction_level': 'supplied', 'assumptions': []}}
    with pytest.raises(ValueError, match='missing_plot_input'):
        comparison._existing_sources(request, None)


def test_exact_residual_identity_and_full_population(tmp_path):
    data, spec = contract(tmp_path, columns=('m_parent', 'dm'))
    basis = {'normalization': 'fictional supplied production basis'}
    data['model_basis'] = basis
    for point in data['points']:
        point['sigma_ref_fb'] = 4
    reference = {'quantity': 'observed', 'basis': basis, 'unit': 'fb',
                 'axes': {k: {f: spec['axes'][k][f] for f in ('quantity', 'unit')} for k in ('x', 'y')},
                 'records': [{'x': 0, 'y': 0, 'value': 2}, {'x': 1, 'y': 0, 'value': 4}]}
    spec['layers'] = [{'kind': 'residual', 'label': 'Supplied exact comparison', 'quantity': 'observed',
                       'reference': reference, 'match_tolerance': 0,
                       'normalization': {'field': 'sigma_ref_fb', 'basis': basis, 'unit': 'fb'}}]
    report = plotting.render_spec(data, spec)
    result = report['layers'][0]
    assert result['counts'] == {'matched': 2, 'unmatched_reference': 2, 'quality_flag': 0, 'invalid_input': 0}
    assert [r['residual'] for r in result['records'] if r['status'] == 'matched'] == [0, 1]
    assert result['matched_fraction_of_plan'] == 2/5


def test_comparison_axes_without_reference_are_refused(tmp_path):
    data, spec = contract(tmp_path)
    axes = {k: {f: spec['axes'][k][f] for f in ('quantity', 'unit', 'scale')} for k in ('x', 'y')}
    with pytest.raises(ValueError, match='missing_plot_input'):
        plotting.validate_spec(data, spec, axes)


def test_log_line_rejects_nonpositive_plotted_values(tmp_path):
    data, spec = contract(tmp_path, columns=('alpha', 'mu95_obs'))
    spec['axes']['y']['scale'] = 'log'
    data['points'] = [{'alpha': 0, 'mu95_obs': .5}, {'alpha': 1, 'mu95_obs': 2}]
    spec['layers'] = [{'kind': 'line', 'label': 'Supplied expected line', 'quantity': 'expected'}]
    for p in data['points']:
        p['mu95_exp'] = 0
    with pytest.raises(ValueError):
        plotting.render_spec(data, spec)


def selected_spec(data, path, mode='grid', quantity='observed'):
    """Explicit synthetic migration input for existing numerical controls."""
    columns = ('dm', 'mu95_obs') if mode == 'line' else ('m_parent', 'dm')
    data['data_schema'] = {'columns': {col: {'quantity': col, 'unit': 'unitless'} for col in columns}}
    spec = {'schema_version': 1,
            'axes': {k: {'column': col, 'quantity': col, 'unit': 'unitless', 'label': col.replace('_', ' '), 'scale': 'linear'}
                     for k, col in zip(('x', 'y'), columns)},
            'presentation': {'experiment': 'CMS', 'com': 7, 'lumi': 2},
            'outputs': [{'path': str(path) + '.png', 'format': 'png'}],
            'layers': [{'kind': 'line' if mode == 'line' else 'points', 'label': 'Supplied values', 'quantity': quantity}]}
    if mode == 'line':
        spec['layers'] += [{'kind': 'band', 'label': 'Supplied expected band', 'quantity': 'expected', 'indices': [0, 4]}]
    else:
        spec['layers'] += [{'kind': 'contour', 'label': 'Supplied boundary', 'quantity': quantity, 'level': 1}]
    return spec


def render_selected_line(renderer, data, args):
    args.plot_spec = selected_spec(data, args.out, 'line')
    return renderer.render_line(data, [], args)


@pytest.mark.parametrize('identity,columns,size,fmt', [('ANA-0003', ('alpha', 'beta'), 2, 'png'),
                                                       ('ANA-0004', ('gamma', 'delta'), 3, 'pdf')])
def test_comparison_admits_supplied_axes_population_and_format(tmp_path, monkeypatch, identity, columns, size, fmt):
    from test_reference_comparison import _request, _basis, _pin
    from ravel.plotting import reference_comparison as comparison
    target, request = _request(tmp_path, 'existing-numerical')
    request.pop('agent'); request.pop('reference')
    data, spec = contract(tmp_path, identity, columns, size, fmt)
    spec['presentation'] = {'experiment': 'CMS', 'com': 5 + size, 'lumi': size}
    basis = {**_basis(), 'energy': f"{spec['presentation']['com']} TeV"}
    data['model_basis'] = basis; request['basis'] = basis
    target['axes']['y'] = 'linear'
    target['paper']['code'] = identity
    request['target']['paper'] = target['paper']
    request['axes'] = {key: {'quantity': axis['quantity'], 'name': axis['label'],
                            'unit': axis['unit'], 'scale': axis['scale']} for key, axis in spec['axes'].items()}
    reference = {'quantity': 'observed', 'basis': basis,
        'axes': {key: {f: row[f] for f in ('quantity', 'unit')} for key, row in spec['axes'].items()},
        'records': [{'x': i, 'y': .5 + i / 2} for i in range(size)]}
    spec['layers'].append({'kind': 'reference-contour', 'label': 'Supplied reference',
                           'quantity': 'observed', 'reference': reference})
    request['renderer'] = {'renderer': 'scan_contour', **spec['presentation'],
                           'scan': _pin(tmp_path/'scan.json', data), 'plot_spec': _pin(tmp_path/'plot.json', spec)}
    delivered = comparison.deliver(_pin(tmp_path/'request.json', request), target, tmp_path)
    target['reference_comparison'] = delivered
    assert comparison.verify_target_comparison(target) == []
    assert len(delivered['overlays']) == 1
    assert Path(delivered['overlays'][0]['path']).name == identity + '.' + fmt
    receipt = json.loads(Path(delivered['receipt']['path']).read_text())
    assert receipt['population']['scan']['points'] == data['points']
    assert receipt['population']['plot_spec'] == spec
    assert len(receipt['population']['plot_spec']['layers'][-1]['reference']['records']) == size
    assert receipt['physics_validated'] is False


def test_reference_contour_requires_matching_explicit_basis(tmp_path):
    data, spec = contract(tmp_path)
    data['model_basis'] = {'production': 'fictional basis A'}
    spec['layers'] = [{'kind': 'reference-contour', 'label': 'Supplied reference', 'quantity': 'observed',
        'reference': {'quantity': 'observed', 'basis': {'production': 'fictional basis B'},
                      'axes': {key: {f: row[f] for f in ('quantity', 'unit')} for key, row in spec['axes'].items()},
                      'records': [{'x': 0, 'y': 0}, {'x': 1, 'y': 1}]}}]
    with pytest.raises(ValueError, match='comparison_mismatch'):
        plotting.render_spec(data, spec)


def test_rendering_restores_callers_style(tmp_path):
    import matplotlib as mpl
    data, spec = contract(tmp_path)
    spec['presentation']['experiment'] = 'CMS'
    with mpl.rc_context({'font.family': ['monospace'], 'axes.labelsize': 9}):
        original = mpl.rcParams.copy()
        plotting.render_spec(data, spec)
        assert mpl.rcParams['font.family'] == original['font.family']
        assert mpl.rcParams['axes.labelsize'] == original['axes.labelsize']


def test_cli_never_overwrites_supplied_scan_or_spec(tmp_path):
    data, spec = contract(tmp_path)
    source = tmp_path / 'ANA-0001.png'
    source.write_text(json.dumps(data))
    path = tmp_path / 'plot.json'; path.write_text(json.dumps(spec))
    original = source.read_bytes()
    with pytest.raises(ValueError, match='input_output_collision'):
        plotting.main(['--scan', str(source), '--plot-spec', str(path),
                       '--experiment', 'Fictional', '--com', '7', '--lumi', '2'])
    assert source.read_bytes() == original


def test_old_reference_flags_cannot_select_an_implicit_layout(tmp_path):
    with pytest.raises(ValueError, match='missing_plot_input'):
        plotting.main(['--scan', str(tmp_path/'missing-scan.json'), '--experiment', 'CMS',
                       '--com', '7', '--lumi', '2', '--atlas-limit', str(tmp_path/'missing-ref.yaml'),
                       '--layout', 'grid', '--out', str(tmp_path/'out')])


def test_scan_producer_exports_supplied_columns(tmp_path, monkeypatch):
    """Consumer seam remains explicit until the general scan producer lands."""
    from types import SimpleNamespace
    from ravel.limits import attach_limits
    from ravel.workflow import scan_orchestrator as producer
    schema = {'columns': {'alpha': {'quantity': 'alpha', 'unit': 'unitless'},
                          'beta': {'quantity': 'beta', 'unit': 'unitless'}}}
    manifest = {'name': 'ANA-0005', 'analysis_id': 'ANA-0005', 'n_points': 1,
                'data_schema': schema, 'points': [{'tag': 'supplied'}]}
    row = attach_limits({'tag': 'supplied', 'm_parent': 3, 'm_lsp': 2,
                         'alpha': 4, 'beta': -2, 'mu95_obs': 2, 'mu95_exp': 3,
                         'source': 'synthetic'})
    monkeypatch.setattr(producer, 'load_manifest', lambda path: (str(tmp_path), manifest))
    monkeypatch.setattr(producer, 'harvest_point', lambda point: row)
    output = tmp_path / 'scan.json'
    producer.cmd_assemble(SimpleNamespace(scandir=str(tmp_path), out=str(output), nlo_renorm=None))
    assembled = json.loads(output.read_text())
    if 'data_schema' not in assembled:
        pytest.xfail('awaits GEN-4B')
    assert assembled['data_schema'] == schema
    assert assembled['points'][0]['alpha'] == 4
    assert assembled['points'][0]['beta'] == -2


def test_automatic_limits_keep_boundary_markers_visible(tmp_path, monkeypatch):
    data, spec = contract(tmp_path)
    captured = []
    monkeypatch.setattr(plotting, 'save', lambda fig, outputs: captured.append((fig.axes[0].get_xlim(), fig.axes[0].get_ylim())))
    plotting.render_spec(data, spec)
    for limits, key in zip(captured[0], ('x', 'y')):
        values = [p[spec['axes'][key]['column']] for p in data['points']]
        assert limits[0] < min(values)
        assert limits[1] > max(values)
