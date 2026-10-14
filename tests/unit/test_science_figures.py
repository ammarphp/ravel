"""Scientific diagnostic edge cases: no division by zero or invented bands."""
import json
import builtins
import pytest
from ravel.plotting.science_figures import render

@pytest.mark.parametrize('zero_sm',[False,True])
def test_measurement_ratio_with_supplied_covariance(tmp_path,zero_sm):
    pytest.importorskip('matplotlib');pytest.importorskip('mplhep')
    from test_measurement import document
    model=document()
    if zero_sm:model['sm']['values'][0]=0
    model['theory_covariance']={'bin_ids':['a','b'],'matrix':[[1,0],[0,4]],'unit':'(pb)^2'}
    model['covariance_policy']='independent_theory_sum'
    (tmp_path/'input.json').write_text(json.dumps(model))
    result=render({'mode':'measurement','task':{'input':'input.json','signal_strength':1}},
                  {'bin_ids':['a','b'],'unit':'pb'},tmp_path,tmp_path)
    assert result['status']=='passed'
    assert result['figures'][0]['plot_lint']=='PASS'
    assert (tmp_path/'measurement.pdf').stat().st_size>0


def test_contrast_figure_uses_paired_covariance_without_inventing_independence(tmp_path):
    pytest.importorskip('matplotlib')
    result = {'bin_ids': ['a', 'b'], 'unit': '1',
              'quantity': {'axes': [], 'bins': []},
              'contrasts': [{'id': 'paired', 'baseline_stream': 'before::nominal',
                             'candidate_stream': 'after::nominal',
                             'baseline': [.25, .75], 'candidate': [.5, .5],
                             'difference': [.25, -.25],
                             'baseline_covariance': [[.1, -.1], [-.1, .1]],
                             'candidate_covariance': [[.1, -.1], [-.1, .1]],
                             'covariance': [[.01, -.01], [-.01, .01]]}]}
    rendered = render({'mode': 'contrast', 'task': {'input': 'unused.json'}}, result, tmp_path, tmp_path)
    assert rendered['status'] == 'passed'
    assert rendered['figures'][0]['stem'] == 'contrast-paired'
    assert (tmp_path / 'contrast-paired.pdf').stat().st_size > 0
    result['contrasts'][0]['covariance'][0][0] = -.1
    with pytest.raises(ValueError, match='declared contrast covariance'):
        render({'mode': 'contrast', 'task': {}}, result, tmp_path, tmp_path)


def scalar_counter():
    return {'contract': {'path': '/CONTROL/yield', 'quantity_kind': 'scalar_counter',
                        'axes': [], 'representation': 'integrated', 'normalization': 'absolute', 'unit': 'pb'},
            'quantity_kind': 'scalar_counter',
            'bins': [{'low': [], 'high': [], 'value': 2.5, 'error_low': .2, 'error_high': .4,
                      'variance': None, 'integrated_sumw': 2.5, 'entries': 7}],
            'storage_semantics': 'finalized scalar estimate with matching RAW Counter',
            'final_counter': None, 'raw_counter': {'sumw': 10., 'sumw2': 16., 'entries': 7.},
            'covariance_scope': 'upstream scalar marginal errors; no cross-counter covariance supplied'}


def test_built_scalar_report_preserves_final_errors_and_raw_moments_without_plot_dependency(tmp_path, monkeypatch):
    original_import = builtins.__import__
    def forbid_plot_dependency(name, *args, **kwargs):
        if name.startswith('matplotlib'):
            pytest.fail('a scalar output must not acquire a bin-index plot or plotting dependency')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', forbid_plot_dependency)
    observable = scalar_counter()
    (tmp_path / 'observables.json').write_text(json.dumps({'observables': {'/CONTROL/yield': observable}}))
    receipt = render({'mode': 'analyze', 'task': {'backend': 'rivet-built'}}, {}, tmp_path, tmp_path)
    assert receipt['status'] == 'passed' and receipt['figures'] == []
    assert receipt['tables'][0]['files'] == ['scalar-counters.json', 'scalar-counters.md']
    table = json.loads((tmp_path / 'scalar-counters.json').read_text())
    assert table['counters'] == [{'path': '/CONTROL/yield', 'observable': observable}]
    assert table['physics_validated'] is False
    assert not list(tmp_path.glob('*.png')) and not list(tmp_path.glob('*.pdf'))
    assert '2.5 | 0.2 | 0.4 | pb' in (tmp_path / 'scalar-counters.md').read_text()


@pytest.mark.parametrize('change', ['geometry', 'negative_error', 'normalized'])
def test_scalar_report_rejects_invented_geometry_or_uncertainty(tmp_path, change):
    observable = scalar_counter()
    if change == 'geometry':
        observable['bins'][0]['low'] = [0]
    elif change == 'negative_error':
        observable['bins'][0]['error_low'] = -.2
    else:
        observable['contract']['normalization'] = 'normalized'
    (tmp_path / 'observables.json').write_text(json.dumps({'observables': {'/CONTROL/yield': observable}}))
    with pytest.raises(ValueError, match='scalar_counter figure report'):
        render({'mode': 'analyze', 'task': {'backend': 'rivet-built'}}, {}, tmp_path, tmp_path)
    assert not (tmp_path / 'scalar-counters.json').exists()


def test_built_mixed_observables_keep_histogram_geometry_and_scalar_table(tmp_path):
    pytest.importorskip('matplotlib')
    histogram = {'contract': {'axes': [{'name': 'mass', 'unit': 'GeV'}], 'unit': 'pb'},
                 'bins': [{'low': [0.], 'high': [1.], 'value': .5, 'error_low': .1, 'error_high': .1},
                          {'low': [1.], 'high': [3.], 'value': .7, 'error_low': .2, 'error_high': .2}]}
    (tmp_path / 'observables.json').write_text(json.dumps({'observables': {
        '/CONTROL/yield': scalar_counter(), '/CONTROL/mass': histogram}}))
    receipt = render({'mode': 'analyze', 'task': {'backend': 'rivet-built'}}, {}, tmp_path, tmp_path)
    assert receipt['status'] == 'passed'
    assert len(receipt['figures']) == len(receipt['tables']) == 1
    assert receipt['figures'][0]['files'] == ['observable-1.pdf', 'observable-1.png']
    assert (tmp_path / 'observable-1.png').stat().st_size > 0
