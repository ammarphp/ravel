"""Requested published-summary contract on declared models, processes and experiments.

Fabricated sources and series only. Each configuration differs in model, process,
spin, unit, experiment set and mass window from every other one.
"""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.physics import published_summary as op
from ravel.plotting import figure_target as ft, summary_overlay as overlay, science_figures
from test_published_summary import write, pin


CONFIGS = {
    'dark-photon': {
        'prompt': "Make a summary plot of the published CMS and LHCb limits on a dark photon A' -> mu mu "
                  "between 10 and 80 GeV.",
        'parent_model': None, 'parent_masses': [10.0, 80.0],
        'request': {'model': 'dark photon', 'resonance': "A'", 'decay': 'mumu', 'spin': 1,
                    'experiments': ['CMS', 'LHCb'], 'window': {'lo_gev': 10, 'hi_gev': 80, 'upper_inclusive': True}},
        'unit': 'fb', 'masses': [5, 20, 50, 80, 120],
        'panels': [('prompt', 'CMS', 'dark photon', 'Drell-Yan-like', 'P1'),
                   ('displaced', 'LHCb', 'dark photon', 'meson decays', 'P2')],
    },
    'heavy-scalar': {
        'prompt': 'Summarise published ATLAS limits on a heavy scalar S->ZZ in the xSM for masses '
                  'from 200 GeV up to 1000 GeV.',
        'parent_model': 'xSM', 'parent_masses': [200.0, 1000.0],
        'request': {'model': 'xSM', 'resonance': 'S', 'decay': 'ZZ', 'spin': 0,
                    'experiments': ['ATLAS'], 'window': {'lo_gev': 200, 'hi_gev': 1000, 'upper_inclusive': False}},
        'unit': 'pb', 'masses': [150, 400, 700, 1000, 2000],
        'panels': [('ggf', 'ATLAS', 'xSM', 'gluon fusion', 'G1')],
    },
}


def panel_basis(cfg, model, production):
    r = cfg['request']
    return {'model': model, 'resonance': r['resonance'], 'spin': r['spin'], 'decay': r['decay'],
            'production': production, 'width': 'Synthetic narrow width', 'quantity': f"95% CL UL [{cfg['unit']}]",
            'unit': cfg['unit'], 'energy_tev': 13, 'branching_convention': 'Synthetic sigma times BR'}


def schema1_panel(folder, cfg, experiment, model, cid):
    window = cfg['request']['window']
    masses = cfg['masses']
    source = folder / 'source.txt'
    source.write_text('FABRICATED source. No measured limit.')
    survey = {'schema_version': 1, 'survey_target': 'fabricated', 'candidates': [
        {'id': cid, 'experiment': experiment, 'final_state': cfg['request']['decay'],
         'mass_range_gev': [masses[0], masses[-1]], 'provenance': 'digitized',
         'disposition': {'state': 'plotted', 'reason': 'fabricated in-window', 'reviewer': 'synthetic'}}]}
    resolved = {'mass_gev': list(masses), 'obs': [5, 3, 2, 1, .5], 'exp': [4, None, 2, .9, .4]}
    manifest = {'schema_version': 1, 'window_gev': [window['lo_gev'], window['hi_gev']],
        'target_basis': {'quantity': f"95% CL UL [{cfg['unit']}]", 'model': model, 'sqrt_s': '13 TeV'},
        'curves': [{'survey_id': cid, 'source': cid + ' synthetic', 'draw': 'primary', 'provenance': 'digitized',
                    'lumi_fb': 10, 'native_basis': 'digitized fabricated', 'transformation': 'IDENTITY',
                    'identity_check': 'NONE', 'resolved': resolved}],
        'coverage_gaps': []}
    contract = {'schema_version': 1, 'kind': 'published-limit-summary/v1',
        'survey': write(folder / 'survey.json', survey), 'manifest': write(folder / 'manifest.json', manifest),
        'source_assets': {'source': pin(source)},
        'candidate_sources': [{'survey_id': cid, 'mass_range_gev': [masses[0], masses[-1]],
                               'source_ids': ['source'], 'energy_tev': 13}],
        'resolved_series_sha256': {cid: op.digest(resolved)}, 'window': dict(window), 'energy_tev': 13,
        'census_scope': 'Fabricated bounded census.', 'precision_scope': 'Fabricated controls, no physics.'}
    return write(folder / 'contract.json', contract)


def build(tmp_path, name):
    cfg = deepcopy(CONFIGS[name])
    tmp_path = tmp_path.resolve()
    request = cfg['request']
    panels, summaries, definitions, candidates = {}, [], [], []
    for index, (pid, experiment, model, production, cid) in enumerate(cfg['panels']):
        folder = tmp_path / pid
        folder.mkdir()
        cp = schema1_panel(folder, cfg, experiment, model, cid)
        summaries.append({'id': pid, 'summary': cp})
        panels[pid] = op._load({'schema_version': 1, 'input': cp['path'], 'input_sha256': cp['sha256']}, tmp_path)
        role = 'requested_model' if index == 0 else 'alternative_model'
        definitions.append({'id': pid, 'role': role, 'model_basis': panel_basis(cfg, model, production),
            'axes': {'x': 'linear', 'y': 'log', 'x_label': 'm [GeV]', 'y_label': f"95% CL UL [{cfg['unit']}]"},
            'caption': f'{model} {production} synthetic basis', 'relation_to_request': 'Separate production panel.'})
        candidates.append({'id': cid, 'experiment': experiment, 'reference_ids': [pid + '-ref'],
            'mass_range_gev': [cfg['masses'][0], cfg['masses'][-1]], 'model_basis': panel_basis(cfg, model, production),
            'disposition': 'plotted' if role == 'requested_model' else 'alternative_panel',
            'reason': 'Fabricated in-window source quantity.', 'panel_id': pid, 'curve_id': cid})
    targets = {'masses_gev': cfg['parent_masses']}
    if cfg['parent_model'] is not None:
        targets['model'] = cfg['parent_model']
    parent = {'schema_version': 1, 'prompt': cfg['prompt'], 'task_mode': 'summary_plot', 'targets': targets}
    pp = write(tmp_path / 'parent.json', parent)
    sources = {}
    for identity in ['paper', 'catalog', 'review', 'mplhep', 'font']:
        p = tmp_path / (identity + '.txt')
        p.write_text('FABRICATED ' + identity + '\n')
        sources[identity] = pin(p)
    target = {'schema_version': 2, 'figure_class': 'published-search-summary', 'parent_task_sha256': pp['sha256'],
        'request': deepcopy(request), 'panels': definitions, 'candidates': candidates, 'census_as_of': '2026-10-09',
        'references': [{'id': d['id'] + '-ref', 'source_id': 'paper', 'paper': 'fabricated source', 'version': 'v1',
                        'figure_or_table': 'Table 1', 'caption': 'Synthetic limits.'} for d in definitions]}
    by_experiment = {}
    for row in candidates:
        by_experiment.setdefault(row['experiment'], []).append(row['id'])
    census = {'schema_version': 1, 'kind': 'official-search-census', 'as_of': '2026-10-09',
        'experiments': request['experiments'], 'candidate_ids': [c['id'] for c in candidates],
        'searches': [{'experiment': e, 'source_id': 'catalog', 'locator': 'Synthetic catalogue',
                      'query': 'All searches for the declared process.', 'candidate_ids': ids}
                     for e, ids in by_experiment.items()],
        'source_review_ids': ['review']}
    contract = {'schema_version': 2, 'kind': 'requested-published-summary/v2', 'parent_task': pp,
        'figure_target': write(tmp_path / 'target.json', target), 'search_census': write(tmp_path / 'census.json', census),
        'panels': summaries, 'source_assets': sources,
        'runtime_resources': {'mplhep_source_id': 'mplhep', 'font_source_ids': ['font']}}
    return parent, target, census, panels, contract


def check(parent, target, census, panels, contract):
    return op.validate_requested_summary(target, parent, census, panels, set(contract['source_assets']),
                                         contract['parent_task']['sha256'])


@pytest.mark.parametrize('name', sorted(CONFIGS))
def test_declared_model_process_and_experiments_validate(tmp_path, name):
    parent, target, census, panels, contract = build(tmp_path, name)
    result = check(parent, target, census, panels, contract)
    assert result['task_contract_complete'] and result['scientific_task_accepted'] is False
    assert result['request'] == target['request']
    assert result['panel_ids'] == [p[0] for p in CONFIGS[name]['panels']]


@pytest.mark.parametrize('name', sorted(CONFIGS))
def test_figure_target_entry_point_uses_the_same_contract(tmp_path, name):
    parent, target, census, panels, contract = build(tmp_path, name)
    assert ft.validate_search_summary(target, parent, census, panels, set(contract['source_assets']),
                                      contract['parent_task']['sha256'])['request'] == target['request']


@pytest.mark.parametrize('name,fault', [(n, f) for n in sorted(CONFIGS) for f in (
    'drop-experiment', 'other-process', 'other-decay', 'spin', 'unit-label', 'model', 'window-bound',
    'missing-search', 'ungrounded-experiment')])
def test_no_narrowing_or_substitution(tmp_path, name, fault):
    p, t, c, l, k = build(tmp_path, name)
    request = t['request']
    if fault == 'drop-experiment':
        request['experiments'] = request['experiments'][:-1] or ['CMS']
    elif fault == 'other-process':
        request['resonance'] = 'W'
    elif fault == 'other-decay':
        request['decay'] = 'tautau'
    elif fault == 'spin':
        for row in t['candidates']:
            row['model_basis']['spin'] = 2
        for row in t['panels']:
            row['model_basis']['spin'] = 2
    elif fault == 'unit-label':
        t['panels'][0]['axes']['y_label'] = '95% CL UL [nb]'
    elif fault == 'model':
        request['model'] = 'unrelated model'
    elif fault == 'window-bound':
        p['targets']['masses_gev'] = [p['targets']['masses_gev'][-1] * 2]
    elif fault == 'missing-search':
        c['searches'].pop()
    elif fault == 'ungrounded-experiment':
        request['experiments'] = sorted(request['experiments'] + ['ALICE'])
    with pytest.raises(ValueError):
        check(p, t, c, l, k)


def test_eligible_candidate_follows_requested_process(tmp_path):
    p, t, c, l, k = build(tmp_path, 'heavy-scalar')
    hidden = deepcopy(t['candidates'][0])
    hidden.update(id='hidden', disposition='incompatible', panel_id=None, curve_id=None)
    t['candidates'].append(hidden)
    c['candidate_ids'].append('hidden')
    c['searches'][0]['candidate_ids'].append('hidden')
    with pytest.raises(ValueError, match='compatible panel'):
        check(p, t, c, l, k)
    hidden['model_basis'].update(spin=1, resonance="Z'", decay='WW')
    assert check(p, t, c, l, k)['candidate_ids'] == ['G1', 'hidden']


def test_delivery_labels_follow_declared_experiments(tmp_path, monkeypatch):
    p, t, c, l, k = build(tmp_path, 'dark-photon')
    request = write(tmp_path / 'request.json', k)
    task = {'schema_version': 2, 'input': request['path'], 'input_sha256': request['sha256']}
    runtime = {key: dict(k['source_assets'][key]) for key in ['mplhep', 'font']}
    def renderer(panels, target, stem):
        from PIL import Image
        Image.new('RGB', (150, 100), 'white').save(stem + '.png')
        Path(stem + '.pdf').write_bytes(b'synthetic pdf')
        evidence = {'status': 'passed', 'mplhep_loaded': True, 'geometric_lint': 'passed', 'panel_count': 2,
            'experiments': ['CMS', 'LHCb'], 'figure_class': 'published-search-summary',
            'mplhep_module': {**runtime['mplhep'], 'size': Path(runtime['mplhep']['path']).stat().st_size},
            'fonts': [{**runtime['font'], 'size': Path(runtime['font']['path']).stat().st_size, 'family': 'mock'}]}
        return {'panels': [{'id': x} for x in panels], 'publication_evidence': evidence,
                'output_pins': [{**pin(Path(stem + ext)), 'size': Path(stem + ext).stat().st_size} for ext in ['.png', '.pdf']]}
    monkeypatch.setattr(overlay, 'render_summary_panels', renderer)
    worker = tmp_path.resolve() / 'worker'
    worker.mkdir()
    result = op.run(task, tmp_path, worker / 'published-summary')
    gallery = (worker / 'published-summary' / 'SOURCE-GALLERY.md').read_text()
    assert 'CMS and LHCb' in gallery and 'ATLAS' not in gallery
    lifecycle = result['figure_target_lifecycle']['targets'][0]
    assert lifecycle['paper']['code'] == 'Published CMS and LHCb search synthesis'
    assert science_figures.render({'mode': 'published-summary', 'task': task}, result, tmp_path, worker)['status'] == 'passed'


def test_style_evidence_accepts_declared_experiment_set(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from types import SimpleNamespace
    from ravel.plotting import mplhep_style as house
    with plt.rc_context({'pdf.fonttype': 42, 'ps.fonttype': 42}):
        fig, ax = plt.subplots(figsize=(4, 3))
        ax.plot([20, 50], [1, .5], label='Synthetic LHCb obs.')
        ax.set_xlabel('m [GeV]')
        ax.set_ylabel('95% CL UL [fb]')
        ax.legend()
        house.tick_hygiene(ax)
        house.publication_axes(ax)
        headers = [fig.text(.1, .98, 'CMS and LHCb published results', weight='bold', style='italic'),
                   fig.text(.1, .90, 'sqrt(s) = 13 TeV')]
        module = tmp_path / 'synthetic-mplhep.py'
        module.write_text('# fabricated\n')
        monkeypatch.setattr(font_manager.FontProperties, 'get_name', lambda self: 'Helvetica')
        report = house.publication_evidence(fig, [ax], headers, hep=SimpleNamespace(__file__=str(module)),
                                            experiments=['CMS', 'LHCb'], energies=[13])
        assert report['experiments'] == ['CMS', 'LHCb']
        plt.close(fig)


def test_house_style_follows_declared_experiments():
    from ravel.plotting import mplhep_style as house
    assert house.house_style_for(['CMS', 'LHCb']) == 'CMS'
    assert house.house_style_for(['BaBar', 'LHCb']) == 'LHCb'
    assert house.house_style_for(['Belle II']) == 'ROOT'
