"""Synthetic irregular contours, toy discovery, comparability and delivered figures."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial import Delaunay
from scipy.stats import norm

from ravel.physics.inference import contours, figures, search, search_statistics, systematics
from test_search_abcd_region import synthetic_search


XY = [(0., 0.), (2., 0.), (0., 2.), (1., 1.), (0.4, 0.6)]


def test_linear_field_contour_is_analytic_and_inside_hull():
    values = [x + 2*y for x, y in XY]
    lines, tri = contours.irregular_lines(XY, values, 1.5)
    assert lines and len(tri['simplices']) >= 3 and tri['extrapolation'] is False
    hull = Delaunay(XY)
    for line in lines:
        assert line[:, 0] + 2*line[:, 1] == pytest.approx([1.5]*len(line), abs=1e-12)
        assert np.all(hull.find_simplex(line, tol=1e-10) >= 0)


@pytest.mark.parametrize('xy', [XY[:2], [(0, 0), (1, 1), (2, 2)], [*XY, XY[0]]])
def test_degenerate_or_duplicate_irregular_grid_refused(xy):
    with pytest.raises(ValueError, match='non-collinear|duplicate'):
        contours.irregular_lines(xy, list(range(len(xy))), 0.5)


def test_declared_difference_coordinates_preserve_original_axes():
    body = {'contours': {'x': 'x', 'y': 'y', 'levels': {'expected_cls_at_nominal': 0.2},
                        'interpolation': {'method': 'delaunay-linear', 'coordinates':
                                          ['x', {'terms': {'x': 1, 'y': -1}, 'offset': 0}]}}}
    points = [{'id': str(i), 'coordinates': {'x': x, 'y': y}, 'cls_at_nominal': {'expected': [0, 0, (x+2*y)/10]}}
              for i, (x, y) in enumerate(XY)]
    result = search_statistics._contours(body, points)[0]
    assert result['status'] == 'interpolated' and result['quantity'] == 'contour'
    assert result['triangulation']['point_ids'] == [str(i) for i in range(5)]
    for line in result['series']:
        for p in line['records']:
            assert p['x'] + 2*p['y'] == pytest.approx(2., abs=1e-10)


def write_document(tmp_path, doc=None):
    document = {'schema_version': 1, 'kind': 'search-statistics', 'statistic': {'origin': 'default'},
                **(doc or synthetic_search())}
    path = tmp_path / 'search.json'
    path.write_text(json.dumps(document))
    return {'input': str(path)}


def test_table_survives_noncollinear_refusal_and_computes_required_quantities(tmp_path):
    doc = synthetic_search()
    doc['signal_points'] = doc['signal_points'][:2]
    doc['computations']['cls_at_nominal'] = False
    result = search_statistics.run(write_document(tmp_path, doc), tmp_path, tmp_path / 'out')
    assert result['points'] == 'points.json'
    table = json.loads((tmp_path / 'out/points.json').read_text())
    assert len(table['points']) == 2 and table['inputs'][0]['sha256']
    assert table['points'][0]['expected_cls_at_nominal'] is not None
    doc = json.loads((tmp_path / 'out/inference.json').read_text())
    assert any(r.get('status') == 'not_interpolable' for r in doc['results'])


def test_reference_pin_table_summary_and_significance_map(tmp_path):
    doc = synthetic_search()
    reference = {'schema_version': 1, 'kind': 'plot-coordinate-series',
                 'axes': {'x': {'name': 'x'}, 'y': {'name': 'y'}},
                 'series': contours.series([np.array([[0., 1.5], [1.5, 0.]])],
                                           identifier='reference', label='Supplied reference contour')}
    path = tmp_path / 'reference.json'
    path.write_text(json.dumps(reference))
    doc['reference_contour'] = {'path': 'reference.json', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    task = write_document(tmp_path, doc)
    result = search_statistics.run(task, tmp_path, tmp_path / 'out')
    assert 'simulated pseudo-data' in result['data_statement']
    table = json.loads((tmp_path / 'out/points.json').read_text())
    assert len(table['points']) == 5 and len(table['inputs']) == 2
    assert all(p['expected_cls_at_nominal'] is not None and p['observed_on_pseudo_data_cls_at_nominal'] is not None
               and p['asimov_discovery_significance'] is not None and p['signal_yields'] for p in table['points'])
    inference = json.loads((tmp_path / 'out/inference.json').read_text())
    contour = next(r for r in inference['results'] if r['quantity'] == 'contour')
    assert contour['status'] == 'interpolated' and contour['series']
    assert contour['reference_contour']['source_pin']['sha256'] == doc['reference_contour']['sha256']
    rendered = figures.render(tmp_path / 'out')
    stems = {r['stem'] for r in rendered['figures']}
    assert {'contour-1', 'search-background-summary', 'search-significance-map'} <= stems
    assert (tmp_path / 'out/search-background-summary.png').stat().st_size > 1000
    doc['reference_contour']['sha256'] = '0'*64
    with pytest.raises(ValueError, match='pin mismatch'):
        search_statistics.load(write_document(tmp_path, doc), tmp_path)


def fixed_background_document():
    doc = synthetic_search()
    doc.update(regions=[{'name': 'target', 'role': 'SR', 'observed': None}],
               backgrounds=[{'name': 'background', 'normfactor': None, 'yields': {'target': {'values': [1000.]}}}],
               signal_points=[{'id': 'p', 'coordinates': {}, 'yields': {'target': {'values': [45.]}}}],
               contours=None, asimov_source='nominal', toys={'count': 1000, 'seed': 19})
    doc['computations']['background_only_fit'] = False
    doc['computations']['cls_at_nominal'] = False
    return doc


def test_toy_discovery_agrees_with_asimov_and_preserves_random_state():
    state = np.random.get_state()
    result = search.run(fixed_background_document())['points'][0]['discovery']
    toy = result['toys']['expected']
    current = np.random.get_state()
    assert state[0] == current[0] and np.array_equal(state[1], current[1]) and state[2:] == current[2:]
    assert toy['count'] == 1000 and toy['seed'] == 19
    assert abs(toy['p_value'] - norm.sf(result['expected_significance'])) < 3 * toy['p_value_mc_uncertainty']
    assert toy['significance_interval'][0] - .15 <= result['expected_significance'] <= toy['significance_interval'][1] + .15
    assert search.run(fixed_background_document())['points'][0]['discovery']['toys'] == result['toys']


@pytest.mark.parametrize('toy_request', [{'count': 10001, 'seed': 1}, {'count': 1000, 'seed': 1, 'required_significance': 5},
                                     {'count': 10, 'seed': 1, 'required_significance': 3}, {'count': True, 'seed': 1}])
def test_discovery_toy_budget_refusal(toy_request):
    with pytest.raises(ValueError, match='cap|more toys'):
        search.toy_options(toy_request)


@pytest.mark.parametrize('field', ['process', 'campaign'])
def test_generator_sample_mismatch_is_refused(field):
    source = {'name': 'variation', 'kind': 'histosys', 'construction': 'one-sided', 'alternative_kind': 'generator',
              'alternative': {'target': [11.]}, 'applies_to': {'samples': ['background'], 'regions': ['target']},
              'correlation': 'correlated', 'origin': 'requester-assumption', 'statement': 'Synthetic generator variation',
              'sample_metadata': {'nominal': {'process': 'process_a', 'campaign': 'campaign_a'},
                                  'alternative': {'process': 'process_a', 'campaign': 'campaign_a'}}}
    registry = {'schema_version': 1, 'sources': [source], 'absent': []}
    assert systematics.Registry(registry).summary()['sources'][0]['comparability'] == 'verified-declarations'
    source['sample_metadata']['alternative'][field] = 'different'
    with pytest.raises(ValueError, match=field + ' mismatch'):
        systematics.Registry(registry)
    del source['sample_metadata']
    with pytest.raises(ValueError, match='sample_metadata'):
        systematics.Registry(registry)


def test_zero_toy_tail_is_unresolved_with_nonzero_uncertainty():
    doc = fixed_background_document()
    doc['signal_points'][0]['yields']['target']['values'] = [400.]
    doc['toys']['count'] = 25
    toy = search.run(doc)['points'][0]['discovery']['toys']['expected']
    assert toy['tail_count'] == 0 and toy['status'] == 'tail_unresolved'
    assert toy['significance'] is None and toy['significance_interval'][1] is None
    assert toy['p_value_mc_uncertainty'] > 0


def test_toys_fluctuate_auxiliaries_and_refit(monkeypatch):
    doc = fixed_background_document()
    doc['backgrounds'][0]['yields']['target']['sumw2'] = [2500.]
    doc['signal_points'][0]['yields']['target']['sumw2'] = [0.]
    doc['mc_statistics'] = 'shapesys'
    doc['toys']['count'] = 30
    pyhf, _ = search._pyhf()
    original = pyhf.infer.test_statistics.q0
    datasets = []
    def capture(mu, data, *args):
        datasets.append(np.asarray(data).copy())
        return original(mu, data, *args)
    monkeypatch.setattr(pyhf.infer.test_statistics, 'q0', capture)
    result = search.run(doc)
    assert result['points'][0]['discovery']['toys']['expected']['count'] == 30
    assert len(datasets) == 31  # Asimov plus every refitted toy
    assert all(len(d) == 2 for d in datasets)
    assert np.std([d[1] for d in datasets[1:]]) > 0


def test_rectangular_contour_remains_supported():
    points = [{'id': str(i), 'coordinates': {'x': x, 'y': y},
               'cls_at_nominal': {'expected': [0, 0, (x+y)/10]}}
              for i, (x, y) in enumerate([(0., 0.), (2., 0.), (0., 2.), (2., 2.)])]
    result = search_statistics._contours({'contours': {'x': 'x', 'y': 'y',
                                         'levels': {'expected_cls_at_nominal': .1}}}, points)[0]
    assert result['quantity'] == 'contour' and result['series']
    assert 'triangulation' not in result


def test_worked_example_cli_check_and_adapter(tmp_path, capsys):
    import shutil
    from ravel import cli
    root = Path(__file__).resolve().parents[2] / 'docs/reference/search-statistics-example'
    local = tmp_path / 'example'
    shutil.copytree(root, local)
    assert cli.main(['inference', 'check', '--mode', 'search-statistics', '--input', str(local / 'search.json')]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert len(checked['inputs']) == 3
    result = search_statistics.run({'input': str(local / 'search.json')}, local, tmp_path / 'out')
    assert result['status'] == 'passed' and 'simulated pseudo-data' in result['data_statement']
    assert figures.render(tmp_path / 'out')['status'] == 'passed'


def test_worked_example_cli_lifecycle(tmp_path):
    """Requires the normal socket-backed test-domain harness; run on reviewer host."""
    import shutil
    from ravel import cli
    root = Path(__file__).resolve().parents[2] / 'docs/reference/search-statistics-example'
    local = tmp_path / 'example'
    shutil.copytree(root, local)
    spec, rd = tmp_path / 'spec.json', tmp_path / 'study'
    assert cli.main(['inference', 'spec', '--mode', 'search-statistics', '--input', str(local / 'search.json'),
                     '--policy', str(local / 'policy.json'), '--source', 'Invented supplied yields',
                     '--assumption', 'Synthetic pseudo-data only', '--max-seconds', '180',
                     '--approval-mode', 'scripted_yes', '--out', str(spec)]) == 0
    assert cli.main(['plan', '--rundir', str(rd), '--spec', str(spec)]) == 0
    shutil.copyfile(local / 'method.json', rd / 'inputs/method-decision.json')
    assert cli.main(['method-decision', '--rundir', str(rd)]) == 0
    assert cli.main(['approve', '--rundir', str(rd), '--scripted',
                     '--quote', 'Authorize this synthetic supplied-yield test only']) == 0
    assert cli.main(['run', '--rundir', str(rd)]) == 0
    delivered = sorted((rd / 'outputs').glob('attempt-*'))[-1]
    table = json.loads((delivered / 'points.json').read_text())
    assert len(table['points']) == 5 and 'simulated pseudo-data' in table['statement']
    rendered = json.loads((delivered / 'figures.json').read_text())
    assert {'contour-1', 'search-background-summary', 'search-significance-map'} <= {r['stem'] for r in rendered['figures']}


def test_observed_on_pseudo_data_uses_declared_injections():
    doc = fixed_background_document()
    del doc['toys']
    doc['computations']['cls_at_nominal'] = True
    nominal = search.run(doc)['points'][0]['cls_at_nominal']
    doc['data']['injections'] = {'background': 1.2}
    injected = search.run(doc)['points'][0]['cls_at_nominal']
    assert nominal['observed'] is None and injected['observed'] is None
    assert injected['observed_on_pseudo_data'] > nominal['observed_on_pseudo_data']
    assert injected['expected'] == pytest.approx(nominal['expected'])
