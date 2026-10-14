"""Supplied input refusals and fictional numerical controls; no native tools."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.physics import native_sa_generic as generic, sa2json_native as converter
from ravel.plotting import summary_overlay


def test_implicit_channel_names_are_refused():
    with pytest.raises(converter.MissingChannelMap, match='channel map'):
        converter.JSONtoSA('fictional_region', 'fictional_workspace')
    with pytest.raises(converter.MissingChannelMap, match='channel map'):
        converter.compressed_channel_map({'channels': []})


@pytest.mark.parametrize('region,branch', [('fictional_amber', 'selected_a'), ('fictional_violet', 'selected_b')])
def test_supplied_mapping_ignores_names(region, branch):
    workspace = {'channels': [{'name': region, 'samples': [{'data': [1]}]}]}
    mapping = {region: {'region': branch}}
    assert converter.validate_channel_map(mapping, workspace) == mapping


def test_converter_requires_map_before_io(capsys):
    with pytest.raises(SystemExit) as error:
        converter.main(['-i', 'fictional.root', '-b', 'fictional.json', '-o', 'fictional-output.json',
                        '-n', 'signal', '-l', '2', '--mc-stat', 'none'])
    assert error.value.code == 2
    assert '--channel-map' in capsys.readouterr().err


def test_missing_luminosity_is_typed_before_native_read(tmp_path, monkeypatch):
    path = tmp_path / 'fictional.json'
    path.write_text(json.dumps({'name': 'fictional', 'objects': {}, 'regions': []}))
    monkeypatch.setattr(generic, 'read_delphes', lambda *a: pytest.fail('native read'))
    with pytest.raises(generic.MissingAnalysisInput, match='luminosity'):
        generic.cmd_run(SimpleNamespace(spec=path, lumi_fb=None, delphes='fictional.root'))


def test_btag_requires_acceptance():
    spec = {'objects': {name: {'pt': 0, 'eta': 4} for name in ('electron', 'muon', 'jet')},
            'regions': [], 'btag': {'idbit': 16}}
    with pytest.raises(generic.MissingAnalysisInput, match='btag'):
        generic.select_event(spec, [], [], [], generic.Obj(1, 0, 0, 0, 0, 0, 2))


def test_angular_observable_uses_full_supplied_jet_population():
    jets = [generic.Obj(10-i, 0, 1 if i < 4 else .01, 0, 0, 0, 2) for i in range(5)]
    met = generic.Obj(1, 0, 0, 0, 0, 0, 2)
    assert generic.compute_vars([], [], jets, [], met)['dphiMin'] == pytest.approx(.01)


def test_angular_observable_accepts_a_declared_leading_jet_count():
    jets = [generic.Obj(10-i, 0, 1 if i < 4 else .01, 0, 0, 0, 2) for i in range(5)]
    met = generic.Obj(1, 0, 0, 0, 0, 0, 2)
    assert generic.compute_vars([], [], jets, [], met, dphi_min_jets=4)['dphiMin'] == pytest.approx(1)
    spec = {'objects': {name: {'pt': 0, 'eta': 4} for name in ('electron', 'muon', 'jet')},
            'regions': [], 'dphi_min_jets': 4}
    assert generic.select_event(spec, [], [], jets, met)['dphiMin'] == pytest.approx(1)
    for bad in (0, -1, 2.5, True, '4'):
        with pytest.raises(ValueError, match='dphi_min_jets'):
            generic.select_event({**spec, 'dphi_min_jets': bad}, [], [], jets, met)


def test_summary_requires_presentation_metadata():
    with pytest.raises(ValueError, match='experiment'):
        summary_overlay.render_manifest({}, 'fictional-output', experiment=None, com=None, lumi=None)


@pytest.mark.parametrize('module', ['mass_plane_overlay', 'overlay_on_data', 'summary_overlay', 'scan_contour', 'root_figures'])
def test_cli_declares_experiment_and_energy_inputs(module):
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / f'src/ravel/plotting/{module}.py').read_text())
    for flag in ('--experiment', '--com', '--lumi'):
        sites = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'add_argument'
                 and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == flag]
        assert sites
        assert all(any(k.arg == 'required' and isinstance(k.value, ast.Constant) and k.value.value is True
                       for k in call.keywords) for call in sites)


def test_numeric_selftest_has_no_installed_source_dependency(monkeypatch):
    from ravel.physics import pyhf_exclude as engine
    monkeypatch.setattr(engine, 'package_data_path', lambda *a: pytest.fail('installed source access'))
    # Exercise orchestration with disclosed numerical fakes; numerical accuracy
    # belongs to the engine's separate analytic controls.
    monkeypatch.setattr(engine, 'compute', lambda model, data, **kw: {
        'obs_limit': .001 if data == 'small' else 2.4359,
        'exp_limits': [1, 2, 3, 4, 5], 'at_mu_floor': False,
        'at_poi_cap': data == 'ceiling', 'median_at_cap': data == 'ceiling',
        'band_degenerate': data == 'ceiling', 'optimizer': {'n_fallback': 1, 'escalated': True}})
    monkeypatch.setattr(engine, 'model_from_counting', lambda row: (None, 'small' if row['s'] > 100 else 'ceiling' if row['s'] < .01 else 'normal'))
    monkeypatch.setattr(engine, '_nanpocket_model', lambda: (None, 'pocket'))
    engine.selftest()


def test_figure_hints_are_supplied_and_summary_is_opt_in():
    from ravel.plotting import figure_manifest as manifest
    assert manifest.KNOWN_ANALYSES == manifest.FIGURE_HINTS == manifest.ANALYSIS_ALIASES == {}
    assert 'summary_recipe' not in manifest.recipe_for('A', analysis='fictional-amber')
    assert manifest.recipe_for('B', analysis='fictional-violet', figure_hint={'summary':'supplied-panel'})['figure_target']['hint'] == {'summary':'supplied-panel'}


def test_figure_hint_cli_consumes_supplied_metadata(tmp_path, monkeypatch, capsys):
    import sys
    from ravel.plotting import figure_manifest as manifest
    path = tmp_path / 'fictional-hint.json'
    path.write_text(json.dumps({'overlay': 'fictional-panel'}))
    monkeypatch.setattr(sys, 'argv', ['figure_manifest', '--archetype', 'A', '--analysis',
                                    'fictional-amber', '--figure-hint', str(path), '--json'])
    manifest.main()
    assert json.loads(capsys.readouterr().out)['figure_target']['hint'] == {'overlay': 'fictional-panel'}


def test_installation_manifest_does_not_grant_broad_qualification():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / 'native/setup/toolchain-manifest.json').read_text())
    for row in manifest['groups']:
        qualification = row.get('qualification')
        if qualification and qualification['status'] == 'qualified':
            record = qualification.get('record') or {}
            scoped = (record.get('tool') == row['id'] and record.get('platform') and record.get('date')
                      and record.get('doctor_result') == 'ready'
                      and len(str(record.get('evidence_sha256', ''))) == 64)
            assert qualification.get('receipts') or scoped, row['id']


def test_control_manifest_is_supplied(tmp_path):
    import importlib.util
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('fictional_controls', root / 'scripts/validation/run_rivet_controls.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, energy in [('fictional-amber', 71), ('fictional-violet', 83)]:
        path = tmp_path / (name + '.json')
        row = {'name': name, 'energy': energy, 'kind': 'dy', 'observable': 'fictional-observable',
               'unit': 'pb/GeV', 'normalized': False, 'grouped': False, 'expected': 'passed'}
        path.write_text(json.dumps({'schema_version': 1, 'cases': [row]}))
        assert module.load_cases(path) == [row]
    with pytest.raises(module.MissingControlInput):
        module.load_cases(None)
