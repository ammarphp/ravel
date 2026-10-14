"""Supplied axes and recipes control preparation without installed physics choices."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.physics import prepare_native_slepton as cards
from ravel.workflow import scan_orchestrator as scan

ROOT = Path(__file__).resolve().parents[2]


def recipe(root, model='MODEL_A', process='a a > b b'):
    root.mkdir(parents=True, exist_ok=True)
    (root/'param.txt').write_text('Block MASS\n 101 {{VALUE}} # retained\nDECAY 101 0.0\n 1.0 2 11 12\n')
    (root/'run.txt').write_text('0 = nevents\n0 = iseed\n0 = ebeam1\n0 = ebeam2\n0 = ickkw\ninternal = pdlabel\n0 = lhaid\nFalse = use_syst\n0 = cut\n')
    (root/'process.txt').write_text(f'import model {model}\ngenerate {process}\n')
    (root/'launch.txt').write_text('{{PROCESS}}\noutput output/PROC_madgraph\n\nset run_mode 2\nset nb_core 4\nlaunch output/PROC_madgraph\nmadspin=OFF\nshower=OFF\nreweight=OFF\ndone\n{{PARAM_CARD}}\n{{RUN_CARD}}\nset iseed {{SEED}}\ndone\n')
    return {'schema_version': 1, 'param_template': 'param.txt', 'run_template': 'run.txt',
            'process_card': 'process.txt', 'launch_template': 'launch.txt', 'parameters': {'value': 7.5},
            'bindings': [{'parameter': 'value', 'placeholder': 'VALUE'}],
            'run_controls': {'nevents': 9, 'iseed': 3, 'ebeam1': 80, 'ebeam2': 80,
                             'pdlabel': 'internal', 'ickkw': 0, 'use_syst': False, 'cut': 2}}


def contract(root, name='ANA-0001', csv=False):
    root.mkdir(parents=True, exist_ok=True)
    template = root/'supplied.toml'
    template.write_text('[parameters]\nvalue = 0\n')
    return {'schema_version': 2, 'name': name, 'template_toml': str(template),
            'subst': {'parameters.value': 'value'}, 'run_prefix': name,
            'run_root': str(root/'runs'), 'axes': [{'name': 'value', 'values': [2, 4]}],
            'max_points': 10, 'datasets': [{'id': 'DATA-A', 'path': 'supplied-events'}],
            'quantities': [{'name': 'response', 'source': 'output/response.json', 'field': 'value'}],
            'output': {'format': 'csv' if csv else 'json', 'path': 'requested.csv' if csv else 'requested.json'}}


def test_row20_installed_template_has_no_selected_physics():
    path = ROOT/'src/ravel/data/templates/scan.schema.json'
    assert path.is_file(), 'parameter-free scan schema required'
    schema = json.loads(path.read_text())
    assert 'default' not in path.read_text()
    assert {'axes', 'quantities', 'datasets', 'output'} <= set(schema['required'])
    assert not (ROOT/'src/ravel/data/templates/slepton_scan_template.toml').exists()


def test_row21_process_requires_selected_source(tmp_path):
    assert not (ROOT/'src/ravel/data/templates/slepton_isrslep_generate.mg5').exists()
    request = recipe(tmp_path)
    del request['process_card']
    with pytest.raises(cards.MissingInputError) as caught:
        cards.render_recipe(request, base=tmp_path, rundir=tmp_path/'run')
    assert caught.value.reason == 'missing-input' and caught.value.field == 'process_card'


def test_row22_renderer_requires_parameter_bindings(tmp_path):
    request = recipe(tmp_path)
    del request['bindings']
    with pytest.raises(cards.MissingInputError) as caught:
        cards.render_recipe(request, base=tmp_path, rundir=tmp_path/'run')
    assert caught.value.field == 'bindings'


def test_row37_implicit_mass_plane_is_refused(tmp_path):
    request = contract(tmp_path)
    del request['axes']
    request['grid'] = {'m_parent': [9], 'dm': [2]}
    path = tmp_path/'contract.json'; path.write_text(json.dumps(request))
    with pytest.raises(scan.MissingInputError) as caught:
        scan.load_spec(path)
    assert caught.value.reason == 'missing-input' and caught.value.field == 'axes'


def test_two_model_process_recipes_and_output_selection(tmp_path):
    first = recipe(tmp_path/'one')
    second = recipe(tmp_path/'two', 'MODEL_B', 'x > y z')
    second['parameters'] = {'width': .25}
    second['bindings'] = [{'parameter': 'width', 'block': 'MASS', 'indices': [101]}]
    (tmp_path/'two/param.txt').write_text('Block MASS\n 101 0.0 # retained\nDECAY 101 0.0\n 1.0 2 11 12\n')
    second['run_controls']['nevents'] = 13
    a = cards.render_recipe(first, base=tmp_path/'one', rundir=tmp_path/'one/run')
    b = cards.render_recipe(second, base=tmp_path/'two', rundir=tmp_path/'two/run')
    assert '7.5 # retained' in a['param_card.dat']
    assert '0.25 # retained' in b['param_card.dat']
    assert 'MODEL_A' in a['run.mg5'] and 'MODEL_B' in b['run.mg5']
    assert '  9  = nevents' in a['run_card.dat'] and '  13  = nevents' in b['run_card.dat']
    assert 'DECAY 101 0.0\n 1.0 2 11 12\n' in a['param_card.dat']


def test_migrated_recipe_effective_card_bytes(tmp_path):
    request = recipe(tmp_path)
    out = cards.render_recipe(request, base=tmp_path, rundir=tmp_path/'run')
    expected = '\n'.join(f'  {value}  = {key}' for key, value in
        [('nevents', '9'), ('iseed', '3'), ('ebeam1', '80'), ('ebeam2', '80'),
         ('ickkw', '0'), ('pdlabel', 'internal'), ('lhaid', '0'), ('use_syst', 'False'), ('cut', '2')])+'\n'
    # Unselected lhaid stays exactly as supplied; keyed overlays retain the former byte idiom.
    expected = expected.replace('  0  = lhaid', '0 = lhaid')
    assert out['run_card.dat'] == expected
    assert out['param_card.dat'] == (tmp_path/'param.txt').read_text().replace('{{VALUE}}', '7.5')
    assert out['run.mg5'] == f'''import model MODEL_A
generate a a > b b
output output/PROC_madgraph

set run_mode 2
set nb_core 4
launch output/PROC_madgraph
madspin=OFF
shower=OFF
reweight=OFF
done
{tmp_path}/run/output/param_card.dat
{tmp_path}/run/output/run_card.dat
set iseed 3
done
'''


def test_different_studies_grids_populations_outputs_same_path(tmp_path):
    requests = [contract(tmp_path/'one'), contract(tmp_path/'two', 'ANA-0002', csv=True)]
    requests[1]['axes'] += [{'name': 'coupling', 'values': [.1, .3, .9]}]
    requests[1]['subst']['parameters.coupling'] = 'coupling'
    Path(requests[1]['template_toml']).write_text('[parameters]\nvalue = 0\ncoupling = 0\n')
    requests[1]['datasets'] = [{'id': 'DATA-B'}, {'id': 'DATA-C'}]
    for request in requests:
        path = Path(request['template_toml']).with_suffix('.json')
        path.write_text(json.dumps(request))
        scan.cmd_plan(SimpleNamespace(spec=str(path), dry_run=False))
        directory = Path(request['run_root'])/(request['run_prefix']+'_SCAN')
        manifest = json.loads((directory/'scan_manifest.json').read_text())
        assert manifest['axes'] == request['axes'] and manifest['datasets'] == request['datasets']
        assert manifest['quantities'] == request['quantities'] and manifest['output'] == request['output']
        assert manifest['n_points'] == (2 if request['name'] == 'ANA-0001' else 6)
        for point in manifest['points']:
            assert set(point['parameters']) == {row['name'] for row in request['axes']}
            import tomllib
            configured = tomllib.loads((Path(point['run_dir'])/point['config']).read_text())
            assert configured['parameters'] == point['parameters']
            source = Path(point['run_dir'])/'output/response.json'; source.parent.mkdir()
            source.write_text(json.dumps({'value': point['parameters']['value']*3}))
        scan.cmd_assemble(SimpleNamespace(scandir=str(directory), out=None, nlo_renorm=None))
        output = directory/request['output']['path']
        assert output.is_file()
        if request['output']['format'] == 'json':
            result = json.loads(output.read_text())
            assert result['datasets'] == request['datasets']
            assert [p['response'] for p in result['points']] == [6, 12]
        else:
            import csv
            rows = list(csv.DictReader(output.open()))
            assert len(rows) == 6 and rows[0]['coupling'] == '0.1'
    del requests[0]['datasets']
    path.write_text(json.dumps(requests[0]))
    with pytest.raises(scan.MissingInputError) as caught:
        scan.load_spec(path)
    assert caught.value.field == 'datasets'


@pytest.mark.parametrize('mutation', ['missing-address', 'duplicate-address', 'unresolved', 'conflict'])
def test_renderer_refuses_silent_edits(tmp_path, mutation):
    request = recipe(tmp_path)
    if mutation == 'missing-address':
        request['bindings'] = [{'parameter': 'value', 'block': 'MASS', 'indices': [999]}]
    elif mutation == 'duplicate-address':
        request['bindings'] *= 2
    elif mutation == 'unresolved':
        (tmp_path/'param.txt').write_text('Block MASS\n 101 {{VALUE}}\n 102 {{OTHER}}\n')
    else:
        request['run_controls']['unknown'] = 1
    with pytest.raises(ValueError):
        cards.render_recipe(request, base=tmp_path, rundir=tmp_path/'run')


def test_duplicate_section_key_is_not_a_scan_binding(tmp_path):
    request = contract(tmp_path)
    request['subst'] = {'value': 'value'}
    text = '[one]\nvalue = 1\n[two]\nvalue = 2\n'
    with pytest.raises(ValueError, match='exactly one'):
        scan.substitute_toml(text, request, {'value': 3})


def test_migrated_native_route_preserves_effective_card_bytes(tmp_path, monkeypatch):
    from test_native_effective_config import prepared
    from ravel.physics import native_effective_config as effective
    plan = prepared(tmp_path, monkeypatch)
    out = tmp_path/'output'
    process = Path(plan['inputs']['process_card']).read_text().rstrip()
    old_launch = (f'{process}\noutput PROC_madgraph\nlaunch PROC_madgraph\nmadspin=OFF\n'
                  f'shower=OFF\nreweight=OFF\ndone\n{out}/param_card.dat\n{out}/run_card.dat\ndone\n')
    assert (out/'run.mg5').read_text() == old_launch
    param = Path(plan['inputs']['param_template']).read_text()
    assert (out/'param_card.dat').read_text() == param.replace('{{MSLEP}}', '150').replace('{{MN1}}', '140')
    assert (out/'run_card.dat').read_text() == plan['rendered']['run_card.dat']
    assert (out/'shower.cfg').read_text() == plan['rendered']['shower.cfg']
    assert effective.validate(plan) == []


@pytest.mark.parametrize('mutation', ['output-collision', 'overlapping-directories', 'traversal', 'nonfinite'])
def test_scan_refuses_conflicting_outputs_before_writing(tmp_path, mutation):
    request = contract(tmp_path)
    if mutation == 'output-collision':
        request['output']['path'] = 'scan_manifest.json'
    elif mutation == 'traversal':
        request['quantities'][0]['source'] = '../other.json'
    elif mutation == 'nonfinite':
        request['axes'][0]['values'] = [float('nan')]
    else:
        points = scan.enumerate_points(request)
        occupied = Path(request['run_root'])/(request['run_prefix']+'_'+scan.point_tag(points[-1]))/'config/point.toml'
        occupied.parent.mkdir(parents=True)
        occupied.write_text('keep original bytes')
    path = tmp_path/'contract.json'; path.write_text(json.dumps(request))
    with pytest.raises(ValueError):
        scan.cmd_plan(SimpleNamespace(spec=str(path), dry_run=False))
    if mutation == 'overlapping-directories':
        assert occupied.read_text() == 'keep original bytes'
        assert not (Path(request['run_root'])/(request['run_prefix']+'_'+scan.point_tag(points[0]))).exists()


def test_general_quantity_cannot_claim_other_parameters(tmp_path):
    (tmp_path/'output').mkdir()
    (tmp_path/'output/response.json').write_text(json.dumps({'value': 1, 'parameters': {'value': 99}}))
    point = {'run_dir': str(tmp_path), 'parameters': {'value': 2},
             'quantities': [{'name': 'response', 'source': 'output/response.json', 'field': 'value'}]}
    with pytest.raises(ValueError, match='parameters'):
        scan.harvest_point(point)


def test_scan_cannot_drop_an_axis_from_point_inputs(tmp_path):
    request = contract(tmp_path)
    request['axes'].append({'name': 'coupling', 'values': [.1, .5]})
    path = tmp_path/'contract.json'; path.write_text(json.dumps(request))
    with pytest.raises(ValueError, match='every axis'):
        scan.load_spec(path)


def test_missing_selected_template_has_typed_reason(tmp_path):
    request = contract(tmp_path)
    request['template_toml'] = str(tmp_path/'absent.toml')
    path = tmp_path/'contract.json'; path.write_text(json.dumps(request))
    with pytest.raises(scan.MissingInputError) as caught:
        scan.cmd_plan(SimpleNamespace(spec=str(path), dry_run=True))
    assert caught.value.field == 'template_toml'


@pytest.mark.parametrize('mutation', ['parameter', 'version'])
def test_native_recipe_conflicts_are_refused_before_preparation(tmp_path, monkeypatch, mutation):
    from test_native_effective_config import slepton_configuration
    from ravel.physics import native_pipeline
    config = slepton_configuration(tmp_path, monkeypatch)
    text = config.read_text()
    if mutation == 'parameter':
        text = text.replace('MSLEP = 150', 'MSLEP = 151')
    else:
        text = text.replace('schema_version = 1', 'schema_version = 2')
    config.write_text(text)
    with pytest.raises(ValueError, match='conflict|version'):
        native_pipeline.build_execution_plan(tmp_path, config)
    assert not (tmp_path/'output').exists()


def test_named_point_liveness_reaches_existing_monitor():
    from ravel.workflow.scan_babysitter import live_points
    tag = scan.point_tag({'coupling': .25, 'width': 2.})
    command = f'python -m ravel.physics.native_pipeline run --plan /runs/ANA-0001_{tag}/inputs/native_execution_plan.json'
    assert tag in live_points(command)
    assert tag not in live_points(f'python scan_babysitter.py {command}')


@pytest.mark.parametrize('mutation', ['expected-differs', 'inverted-hierarchy'])
def test_native_rendered_masses_must_match_expected_and_hierarchy(tmp_path, monkeypatch, mutation):
    from test_native_effective_config import slepton_configuration
    from ravel.physics import native_pipeline
    config = slepton_configuration(tmp_path, monkeypatch)
    text = config.read_text()
    if mutation == 'expected-differs':
        text = text.replace('"1000022" = 140}', '"1000022" = 141}')
    else:
        text = (text.replace('MSLEP = 150', 'MSLEP = 130').replace('parent = 150', 'parent = 130')
                .replace('= 150,', '= 130,'))
    config.write_text(text)
    with pytest.raises(ValueError, match='rendered parameter card' if mutation == 'expected-differs' else 'heavier'):
        native_pipeline.build_execution_plan(tmp_path, config)
    assert not (tmp_path/'output').exists()


def test_named_scan_assembly_takes_only_a_supplied_normalization(tmp_path):
    """Named-axis assembly refuses the retired process-selected correction and applies a supplied
    normalization contract to its rows before any output is written."""
    request = contract(tmp_path/'one')
    path = Path(request['template_toml']).with_suffix('.json'); path.write_text(json.dumps(request))
    scan.cmd_plan(SimpleNamespace(spec=str(path), dry_run=False))
    directory = Path(request['run_root'])/(request['run_prefix']+'_SCAN')
    manifest = json.loads((directory/'scan_manifest.json').read_text())
    for point in manifest['points']:
        source = Path(point['run_dir'])/'output/response.json'; source.parent.mkdir()
        source.write_text(json.dumps({'value': point['parameters']['value']*3}))
    output = directory/request['output']['path']
    from ravel.physics.xsec_conventions import MissingInput
    with pytest.raises(MissingInput):
        scan.cmd_assemble(SimpleNamespace(scandir=str(directory), out=None, nlo_renorm='a-process'))
    assert not output.exists()
    unrelated = tmp_path/'normalization.json'
    unrelated.write_text(json.dumps({'kind': 'cross-section-renormalization', 'points': []}))
    with pytest.raises(ValueError):
        scan.cmd_assemble(SimpleNamespace(scandir=str(directory), out=None, nlo_renorm=None,
                                          normalization_contract=str(unrelated)))
    assert not output.exists()
