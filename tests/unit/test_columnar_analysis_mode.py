"""Science mode columnar-analysis: admission, worker delivery, figures and command line."""
import json

import pytest

from columnar_fixtures import RECIPE, random_events, recipe, write_delphes
from ravel.physics import columnar_analysis as mode


@pytest.fixture
def study(tmp_path):
    write_delphes(tmp_path / 'a.root', random_events(150, seed=4))
    write_delphes(tmp_path / 'b.root', random_events(120, seed=5))
    (tmp_path / 'recipe.json').write_text(json.dumps(RECIPE))
    task = {'recipe': 'recipe.json', 'format': 'delphes', 'inputs': ['a.root', 'b.root'], 'chunk_size': 64,
            'normalization': {'mode': 'cross-section', 'cross_section_pb': 0.2, 'cross_section_source': 'synthetic value',
                              'luminosity_ifb': 139.0, 'luminosity_source': 'synthetic value',
                              'sum_of_weights': 'all-input-events'}}
    return tmp_path, task


@pytest.mark.parametrize('change, message', [
    ({'inputs': []}, 'inputs'), ({'inputs': ['a.root', 'a.root']}, 'twice'), ({'chunk_size': 0}, 'chunk_size'),
    ({'unexpected': 1}, 'task needs'), ({'normalization': 3}, 'normalization')])
def test_task_structure_is_checked(study, change, message):
    _, task = study
    with pytest.raises(ValueError, match=message):
        mode.validate({**task, **change})


def test_registration_and_planning_inputs(study):
    from ravel.workflow import science
    from test_science_capability_integration import specification
    base, task = study
    spec = specification('columnar-analysis', task)
    assert 'columnar-analysis' in science.MODES
    assert science.adapter(spec) is mode and science._new_capability(spec)
    science.validate(spec)
    files = science.task_inputs(spec, base)
    assert {p.name for p in files} == {'recipe.json', 'a.root', 'b.root'}


def test_planning_refuses_a_file_without_the_declared_branches(study):
    import uproot
    base, task = study
    with uproot.recreate(base / 'other.root') as f:
        f['Delphes'] = {'x': [1.0, 2.0]}
    with pytest.raises(ValueError, match='Electron.PT'):
        mode.inputs({**task, 'inputs': ['other.root']}, base)


def test_worker_delivery_figures_and_checkin(study, monkeypatch):
    from ravel.physics import science_worker
    from ravel.workflow import science
    from ravel.workflow.state_io import atomic_json, read_json
    from test_science_capability_integration import specification
    base, task = study
    spec = specification('columnar-analysis', task)
    rd = base / 'worker'; (rd / 'inputs').mkdir(parents=True)
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
    assert result['region_yields']['three leptons on Z']['raw'] >= 0
    summary = read_json(out / 'columnar-analysis/analysis-result.json')
    assert [i['file_index'] for i in summary['provenance']['inputs']] == [0, 1]
    assert all(i['complete'] for i in summary['provenance']['inputs'])
    figures = read_json(out / 'figures.json')
    assert figures['status'] == 'passed' and len(figures['figures']) == 2
    for figure in figures['figures']:
        for name in figure['files']:
            assert (out / name).stat().st_size > 0
    assert figures['figures'][0]['display_labels']['x'] == 'Missing transverse momentum [GeV]'
    assert read_json(out / 'checkin2.json')['sections']['waypoint']['status'] == 'passed'


def test_command_line_partitions_merge_finalize_and_plot(study, capsys):
    from ravel import cli
    base, task = study
    recipe_path = str(base / 'recipe.json')
    assert cli.main(['columnar-analysis', 'inspect', '--format', 'delphes', '--input', str(base / 'a.root')]) == 0
    assert json.loads(capsys.readouterr().out)['entries'] == 150
    assert cli.main(['columnar-analysis', 'validate', '--recipe', recipe_path, '--format', 'delphes',
                     '--input', str(base / 'a.root')]) == 0
    assert 'three leptons on Z' in json.loads(capsys.readouterr().out)['regions']
    for name, spec in (('p1', 'a.root@0:0-70'), ('p2', 'a.root@0:70-150'), ('p3', 'b.root@1')):
        assert cli.main(['columnar-analysis', 'analyse', '--recipe', recipe_path, '--format', 'delphes',
                         '--input', str(base / spec), '--chunk-size', '50', '--out', str(base / f'{name}.json')]) == 0
    assert cli.main(['columnar-analysis', 'merge', str(base / 'p1.json'), str(base / 'p2.json'), str(base / 'p3.json'),
                     '--out', str(base / 'merged.json')]) == 0
    (base / 'norm.json').write_text(json.dumps(task['normalization']))
    capsys.readouterr()
    for out, scale_name in (('signal', 'signal'), ('background', 'background')):
        assert cli.main(['columnar-analysis', 'finalize', '--recipe', recipe_path, '--format', 'delphes',
                         '--partial', str(base / 'merged.json'), '--normalization', str(base / 'norm.json'),
                         '--out', str(base / out)]) == 0
    capsys.readouterr()
    assert cli.main(['columnar-analysis', 'plot', '--histogram', 'met in three-lepton region',
                     '--entry', f'{base / "background"}::Diboson simulation::background',
                     '--entry', f'{base / "signal"}::Benchmark signal::signal',
                     '--out', str(base / 'control')]) == 0
    assert (base / 'control.pdf').stat().st_size > 0 and (base / 'control.png').stat().st_size > 0
    with pytest.raises(SystemExit) as refused:
        cli.main(['columnar-analysis', 'plot', '--histogram', 'met in three-lepton region',
                  '--entry', f'{base / "background"}::bkg_raw::background', '--out', str(base / 'bad')])
    assert refused.value.code == 1 and 'not natural language' in capsys.readouterr().err


def test_merged_partitions_equal_the_study_result(study, tmp_path):
    from ravel.physics.columnar import engine
    base, task = study
    plan, normalization, _, events = mode.compile_task(task, base)
    direct = mode.run(task, base, tmp_path / 'direct')
    parts = [engine.analyse({'inputs': [{'path': str(events[0]), 'file_index': 0, 'entry_start': 0, 'entry_stop': 75}],
                             'chunk_size': 30}, plan),
             engine.analyse({'inputs': [{'path': str(events[0]), 'file_index': 0, 'entry_start': 75, 'entry_stop': 150},
                                        {'path': str(events[1]), 'file_index': 1}], 'chunk_size': 30}, plan)]
    split = engine.finalize(engine.merge(parts), plan, normalization, out_dir=tmp_path / 'split')
    for region, value in direct['region_yields'].items():
        last = [r for r in split['cutflows']['nominal'] if r['name'] == region][0]['cuts'][-1]
        assert last['raw'] == value['raw'] and last['yield'] == pytest.approx(value['yield'])


@pytest.mark.parametrize('prompt', [
    'Apply my object selection to the Delphes ROOT output and report signal region yields with a cutflow.',
    'Compute MT2 and missing transverse momentum histograms from the PHYSLITE ntuple.'])
def test_capability_routing_suggests_the_mode(prompt):
    from ravel.workflow import capability_routing as cr
    rows = {c['mode'] for c in cr.plan(prompt)['candidates']}
    assert 'columnar-analysis' in rows


def test_reference_worked_recipe_compiles_and_runs(tmp_path):
    import re
    from pathlib import Path
    from ravel.physics.columnar import engine, formats
    from ravel.physics.columnar.recipe import compile_recipe
    doc = Path(__file__).resolve().parents[2] / 'docs/reference/columnar-analysis.md'
    text = doc.read_text().split('## Worked recipe', 1)[1]
    worked = json.loads(re.search(r'```json\n(.*?)\n```', text, re.S).group(1))
    plan = compile_recipe(worked, formats.load_descriptor('delphes', tmp_path), tmp_path)
    path = write_delphes(tmp_path / 'e.root', random_events(200, seed=9))
    partial = engine.analyse({'inputs': [{'path': str(path), 'file_index': 0}], 'chunk_size': 64}, plan)
    rows = partial['variations']['nominal']['cutflows']['three leptons and no isolated track']
    assert rows[0][0] == 200 and rows[-1][0] <= rows[-2][0]


def test_typed_synthetic_two_region_spec_refuses_open_ambiguity_then_runs(tmp_path):
    from ravel.workflow.analysis_spec import span_for
    from test_columnar_inputs import write_delphes
    source = b'Jets have transverse momentum above 20 GeV.\nLow region: at least one jet and recoil above 30 GeV.\nHigh region: at least one jet; recoil threshold is 100 or 150 GeV.\n'
    (tmp_path / 'paper.txt').write_bytes(source)
    def field(value, line):
        return {'value': value, 'status': 'explicit', 'span': span_for(source, 'paper', line, line)}
    doc = {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'synthetic two region selection',
           'weights': {'generator': 'weight', 'factors': []},
           'objects': [{'name': 'jets', 'from': 'Jet', 'select': 'pt > 20', 'spec_item': 'jets'}],
           'observables': [{'name': 'n', 'op': 'count', 'collection': 'jets', 'spec_item': 'count'},
                           {'name': 'recoil', 'op': 'met', 'spec_item': 'recoil'}],
           'regions': [{'name': name, 'cuts': [{'name': 'selection', 'expr': f'n >= 1 and recoil > {cut}',
                                              'spec_item': name}]} for name, cut in [('low', 30), ('high', 100)]],
           'histograms': []}
    items = [{'id': 'jets', 'role': 'object', 'family': 'jet', 'fields': {'pt_min': field(20, 1)}},
             {'id': 'count', 'role': 'observable', 'collection': field('jets', 1), 'fields': {'definition': field('count jets', 1)}},
             {'id': 'recoil', 'role': 'observable', 'fields': {'definition': field('missing transverse momentum', 2)}}]
    for name, value, line in [('low', 30, 2), ('high', 100, 3)]:
        items.append({'id': name, 'role': 'cut', 'region': name, 'order': 1, 'impact_estimate': .4,
                      'collection': field('jets', line), 'fields': {'threshold': field(value, line)}})
    spec = {'schema_version': 1, 'kind': 'typed-analysis-spec', 'analysis': 'synthetic two-region selection',
            'sources': [{'id': 'paper', 'path': 'paper.txt'}], 'items': items}
    spec['items'][-1]['fields']['threshold'] = {'value': None, 'status': 'ambiguous', 'readings': [100, 150],
                                               'span': span_for(source, 'paper', 3, 3)}
    (tmp_path / 'recipe.json').write_text(json.dumps(doc))
    spec_path = tmp_path / 'spec.json'
    spec_path.write_text(json.dumps(spec))
    write_delphes(tmp_path / 'sample.root', [{'MET': met, 'METPhi': 0, 'Weight': 1,
                                             'Jet': [{'PT': 40, 'Eta': 0, 'Phi': 0, 'Mass': 5}]}
                                            for met in [20, 50, 120, 170]])
    task = {'recipe': 'recipe.json', 'format': 'delphes', 'inputs': ['sample.root'],
            'normalization': {'mode': 'none'}, 'analysis_spec': 'spec.json'}
    with pytest.raises(ValueError, match='open ambiguities.*high variable_consistency'):
        mode.inputs(task, tmp_path)
    source = source.replace(b'recoil threshold is 100 or 150 GeV', b'recoil above 100 GeV')
    (tmp_path / 'paper.txt').write_bytes(source)
    spec['items'][-1]['collection'] = field('jets', 3)
    spec['items'][-1]['fields']['threshold'] = field(100, 3)
    spec_path.write_text(json.dumps(spec))
    files = mode.inputs(task, tmp_path)
    assert {p.name for p in files} == {'recipe.json', 'spec.json', 'paper.txt', 'sample.root'}
    plan, _, _, _ = mode.compile_task(task, tmp_path)
    assert plan.spec_report['coverage']['passed'] and plan.spec_report['ambiguities']['blocking'] == []
    result = mode.run(task, tmp_path, tmp_path / 'output')
    assert result['region_yields']['low']['yield'] == 3
    assert result['region_yields']['high']['yield'] == 2
    assert result['physics_validated'] is False
