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
