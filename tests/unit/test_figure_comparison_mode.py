"""Science mode figure-comparison: digitise, compare and draw as one approved study."""
import json

import numpy as np
import pytest

matplotlib = pytest.importorskip('matplotlib')
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

from ravel.physics import figure_comparison as mode  # noqa: E402

RED = '#d55e00'
EDGES = [100.0, 300.0, 500.0, 700.0, 900.0]
BASIS = {'kind': 'published_precision', 'source': 'Line width of the published figure'}


@pytest.fixture(autouse=True)
def _default_matplotlib_style():
    """Synthetic published figures use plain matplotlib text, whatever style an earlier test applied."""
    with plt.style.context('default'):
        yield


def _published_figure(path):
    matplotlib.rcParams['pdf.fonttype'] = 42
    fig, ax = plt.subplots(figsize=(5, 4))
    x = np.linspace(100, 900, 41)
    ax.plot(x, 0.02 * x + 1, color=RED, lw=2, label='Published prediction')
    ax.set_xlim(100, 900)
    ax.set_ylim(0, 20)
    ax.set_xlabel('Mass [GeV]')
    ax.legend(loc='upper left')
    fig.savefig(path)
    plt.close(fig)


@pytest.fixture
def study(tmp_path):
    _published_figure(tmp_path / 'published.pdf')
    digitise = {'schema_version': 1, 'source': {'path': 'published.pdf'},
                'axes': {'x': {'label': 'Mass', 'unit': 'GeV', 'calibration': {'method': 'tick_labels'}},
                         'y': {'label': 'Events per bin', 'unit': '', 'calibration': {'method': 'tick_labels'}}},
                'series': [{'name': 'prediction', 'label': 'Published prediction', 'kind': 'line',
                            'select': {'color': RED}}]}
    centres = (np.array(EDGES[1:]) + np.array(EDGES[:-1])) / 2
    ours = {'edges': EDGES, 'values': (0.02 * centres + 1.05).tolist(), 'errors': [0.2] * 4,
            'quantity': 'value', 'unit': ''}
    data = {'edges': EDGES, 'values': (0.02 * centres + 0.9).tolist(), 'errors': [0.5] * 4,
            'quantity': 'value', 'unit': ''}
    compare = {'schema_version': 1, 'kind': 'binned', 'agent': {'path': 'ours.json'},
               'reference': {'operation': 'published', 'series': 'prediction', 'as': 'bins', 'edges': EDGES,
                             'quantity': 'value', 'unit': ''},
               'tolerances': {'shape_l2': {'pass': 0.05, 'warn': 0.1, 'basis': BASIS},
                              'delta_norm': {'pass': 0.05, 'warn': 0.1, 'basis': BASIS}}}
    overlay = {'schema_version': 1, 'name': 'overlay',
               'axes': {'x': {'label': 'Mass', 'unit': 'GeV'}, 'y': {'label': 'Events per bin', 'unit': ''},
                        'ratio': {'label': 'Ratio to data'}},
               'data': {'label': 'Data', 'source': {'path': 'data.json'}},
               'predictions': [{'name': 'ours', 'label': 'This prediction', 'source': {'path': 'ours.json'}}],
               'ratio': {'denominator': 'data'},
               'official': {'label': 'Published prediction (digitised)',
                            'source': {'operation': 'published', 'series': 'prediction'}},
               'comparison': {'operation': 'agreement'}, 'side_by_side': True}
    for name, doc in (('digitise.json', digitise), ('compare.json', compare), ('overlay.json', overlay),
                      ('ours.json', ours), ('data.json', data)):
        (tmp_path / name).write_text(json.dumps(doc))
    task = {'operations': [{'name': 'published', 'kind': 'digitize', 'specification': 'digitise.json'},
                           {'name': 'agreement', 'kind': 'compare', 'specification': 'compare.json'},
                           {'name': 'figure', 'kind': 'measurement-overlay', 'specification': 'overlay.json'}]}
    return tmp_path, task


@pytest.mark.parametrize('change, message', [
    ({'operations': []}, 'operations'),
    ({'operations': [{'name': 'a', 'kind': 'paint', 'specification': 'x.json'}]}, 'kind'),
    ({'operations': [{'name': 'a', 'kind': 'compare', 'specification': 'x.json'}] * 2}, 'unique'),
    ({'extra': 1}, 'task')])
def test_task_structure_is_checked(change, message):
    with pytest.raises(ValueError, match=message):
        mode.validate({'operations': [{'name': 'a', 'kind': 'compare', 'specification': 'x.json'}], **change})


def test_registration_and_planning_inputs(study):
    from ravel.workflow import science
    from test_science_capability_integration import specification
    base, task = study
    spec = specification('figure-comparison', task)
    assert 'figure-comparison' in science.MODES
    assert science.adapter(spec) is mode and science._new_capability(spec)
    science.validate(spec)
    names = {p.name for p in science.task_inputs(spec, base)}
    assert names == {'digitise.json', 'compare.json', 'overlay.json', 'published.pdf', 'ours.json', 'data.json'}


def test_planning_refuses_a_later_reference_to_an_unknown_operation(study):
    base, task = study
    task = {'operations': task['operations'][1:]}
    with pytest.raises(ValueError, match='published'):
        mode.inputs(task, base)


def test_worker_runs_the_operations_in_order_and_publishes_figures(study, monkeypatch):
    from ravel.physics import science_worker
    from ravel.workflow import science
    from ravel.workflow.state_io import atomic_json, read_json
    from test_science_capability_integration import specification
    base, task = study
    spec = specification('figure-comparison', task)
    rd = base / 'worker'
    (rd / 'inputs').mkdir(parents=True)
    atomic_json(rd / 'inputs/science.json', spec)
    atomic_json(rd / 'inputs/science-plan.json', {'schema_version': 2, 'execution_task': task, 'mutable_inputs': []})
    atomic_json(rd / 'inputs/science-execution-task.json', {'schema_version': 1, 'task': task})
    proposal = {'base_dir': str(base), 'attempt': 1, 'output_directory': 'outputs/attempt-1',
                'stage_binding': {'input_snapshot': {}}}
    monkeypatch.setattr(science_worker, 'verify_worker', lambda _: proposal)
    assert science_worker.main([str(rd), '--attempt', '1']) == 0
    out = rd / 'outputs/attempt-1'
    result = read_json(out / 'result.json')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    ops = {o['name']: o for o in result['operations']}
    assert ops['agreement']['verdict'] == 'PASS'
    assert ops['figure']['plot_lint'] == 'PASS'
    overlay = read_json(out / 'figure-comparison/figure/overlay.json')
    assert overlay['comparison']['verdict'] == 'PASS'
    figures = read_json(out / 'figures.json')
    assert figures['status'] == 'passed'
    stems = {f['stem'] for f in figures['figures']}
    assert {'figure-comparison/figure/overlay', 'figure-comparison/figure/overlay-side-by-side',
            'figure-comparison/published/review'} <= stems
    for f in figures['figures']:
        for name in f['files']:
            assert (out / name).stat().st_size > 0
    assert read_json(out / 'checkin2.json')['sections']['waypoint']['status'] == 'passed'


@pytest.mark.parametrize('prompt', [
    'Digitise the exclusion contour from the published figure and overlay our result on the official figure.',
    'Draw the parameter plane with a side-by-side panel against the HEPData table.'])
def test_capability_routing_finds_the_mode(prompt):
    from ravel.workflow import capability_routing as cr
    rows = {c['mode']: c for c in cr.plan(prompt)['candidates']}
    assert 'figure-comparison' in rows and rows['figure-comparison']['matched']


def test_focused_commands_route_to_the_tools(tmp_path, capsys):
    from ravel import cli
    assert cli.FOCUSED_COMMANDS['figure'][0] == 'physics.figure_comparison'
    assert cli.FOCUSED_COMMANDS['compare'][0] == 'validation.fidelity'
    spec = {'schema_version': 1, 'kind': 'scalar', 'agent': {'value': 1.3, 'uncertainty': 0.05},
            'reference': {'value': 1.2, 'uncertainty': 0.1},
            'tolerances': {'abs_pull': {'pass': 2, 'warn': 3, 'basis': BASIS}}}
    (tmp_path / 'scalar.json').write_text(json.dumps(spec))
    assert cli.main(['compare', '--spec', str(tmp_path / 'scalar.json'), '--out', str(tmp_path / 'c.json')]) == 0
    assert json.loads(capsys.readouterr().out)['verdict'] == 'PASS'
    assert cli.main(['figure', 'plan', '--task', str(tmp_path / 'missing.json')]) == 2
