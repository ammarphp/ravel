"""Portable fabricated-source controls; no real P1 delivery/approval inferred."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.physics import published_summary as operation


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path.write_text(json.dumps(value, allow_nan=False))
    return pin(path)


def fixture(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('FABRICATED source. No measured limit or experimental acceptance.')
    survey = {'schema_version': 1, 'survey_target': 'fabricated', 'candidates': [
        {'id': 'A', 'experiment': 'ATLAS', 'final_state': 'l-nu-qq',
         'mass_range_gev': [250, 1000], 'provenance': 'digitized',
         'disposition': {'state': 'plotted', 'reason': 'fabricated in-window', 'reviewer': 'synthetic'}},
        {'id': 'B', 'experiment': 'CMS', 'final_state': 'l-nu-qq',
         'mass_range_gev': [600, 1000], 'provenance': 'digitized',
         'disposition': {'state': 'excluded', 'reason_class': 'out-of-range',
                         'reason': 'above window', 'reviewer': 'synthetic'}}]}
    manifest = {'schema_version': 1, 'window_gev': [150, 500],
        'target_basis': {'quantity': '95% CL UL [pb]', 'model': 'Synthetic hypothesis', 'sqrt_s': '13 TeV'},
        'curves': [{'survey_id': 'A', 'source': 'A l-nu-qq', 'draw': 'primary', 'provenance': 'digitized',
                    'lumi_fb': 1, 'native_basis': 'digitized fabricated pb', 'transformation': 'IDENTITY',
                    'identity_check': 'NONE', 'resolved': {'mass_gev': [250, 300, 450, 500, 1000],
                        'obs': [8, 4, 1, .8, .1], 'exp': [None, 3, None, .7, .2],
                        'theory': [None, None, None, None, .15], 'theory_label': 'out-of-window'}}],
        'coverage_gaps': [{'lo_gev': 150, 'hi_gev': 250, 'note': 'No retained curve in supplied census'}]}
    contract = {'schema_version': 1, 'kind': 'published-limit-summary/v1',
        'survey': write(tmp_path / 'survey.json', survey),
        'manifest': write(tmp_path / 'manifest.json', manifest),
        'source_assets': {'source': pin(source)}, 'candidate_sources': [
            {'survey_id': c['id'], 'mass_range_gev': list(c['mass_range_gev']), 'source_ids': ['source'], 'energy_tev':13}
            for c in survey['candidates']],
        'resolved_series_sha256': {'A': operation.digest(manifest['curves'][0]['resolved'])},
        'window': {'lo_gev': 150, 'hi_gev': 500, 'upper_inclusive': False},
        'energy_tev':13,
        'census_scope': 'Fabricated bounded census; current completeness unknown.',
        'precision_scope': 'Fabricated source-only controls, no physics.'}
    return survey, manifest, contract


def task(tmp_path, contract):
    p = write(tmp_path / 'contract.json', contract)
    return {'schema_version': 1, 'input': p['path'], 'input_sha256': p['sha256']}


def test_full_values_retained_half_open_view_and_nulls(tmp_path):
    survey, manifest, contract = fixture(tmp_path)
    r = operation.inspect(survey, manifest, contract)
    assert r['audit']['verdict'] == 'PASS'
    shown = r['render_manifest']['curves'][0]['resolved']
    assert shown['mass_gev'] == [250, 300, 450, 500]
    assert shown['exp'] == [None, 3, None, .7] and shown['theory'] == [None] * 4
    assert r['render_manifest']['excluded_boundary_anchors'] == [{'survey_id':'A',
        'source_index':3,'mass_gev':500,'in_requested_window':False,
        'purpose':'literal sample for display clipping only'}]
    assert all(not row['in_requested_window'] for row in r['complete_series_rows'] if row['mass_gev']==500)
    assert len(r['complete_series_rows']) == 15
    assert manifest['curves'][0]['resolved']['mass_gev'][-1] == 1000


@pytest.mark.parametrize('fault', ['stale_range', 'stale_gap', 'out_of_range', 'duplicate_id',
    'duplicate_curve', 'source_missing', 'source_id', 'series_hash', 'negative', 'infinite',
    'duplicate_mass', 'short_series', 'wrong_transform', 'provenance', 'mislabel', 'window', 'unknown_series',
    'unavailable_endpoint', 'energy_label', 'mixed_energy'])
def test_source_meaning_and_numerical_census_refuses(tmp_path, fault):
    survey, manifest, contract = fixture(tmp_path)
    c = manifest['curves'][0]
    if fault == 'stale_range': survey['candidates'][0]['mass_range_gev'][0] = 200
    if fault == 'stale_gap': manifest['coverage_gaps'][0]['hi_gev'] = 200
    if fault == 'out_of_range': survey['candidates'][1]['mass_range_gev'][0] = contract['candidate_sources'][1]['mass_range_gev'][0] = 450
    if fault == 'duplicate_id': survey['candidates'][1]['id'] = 'A'
    if fault == 'duplicate_curve': manifest['curves'].append(deepcopy(c))
    if fault == 'source_missing': contract['candidate_sources'].pop()
    if fault == 'source_id': contract['candidate_sources'][0]['source_ids'] = ['absent']
    if fault == 'series_hash': contract['resolved_series_sha256']['A'] = '0' * 64
    if fault == 'negative': c['resolved']['obs'][0] = -1
    if fault == 'infinite': c['resolved']['obs'][0] = float('inf')
    if fault == 'duplicate_mass': c['resolved']['mass_gev'][1] = 250
    if fault == 'short_series': c['resolved']['obs'].pop()
    if fault == 'wrong_transform': c['transformation'] = ''
    if fault == 'provenance': c['provenance'] = 'hepdata-machine'
    if fault == 'mislabel': c['source'] = 'A fully-leptonic'
    if fault == 'window': manifest['window_gev'] = [150, 1000]
    if fault == 'unknown_series': c['resolved']['variance'] = [1] * 5
    if fault == 'unavailable_endpoint': c['resolved']['obs'][0] = None
    if fault == 'energy_label': manifest['target_basis']['sqrt_s'] = '8 TeV'
    if fault == 'mixed_energy': contract['candidate_sources'][1]['energy_tev'] = 8
    if fault not in ('series_hash', 'infinite'): contract['resolved_series_sha256']['A'] = operation.digest(c['resolved'])
    with pytest.raises(ValueError): operation.inspect(survey, manifest, contract)


def test_coverage_only_view_and_closed_upper_endpoint(tmp_path):
    survey, manifest, contract = fixture(tmp_path)
    contract['window'] = {'lo_gev': 100, 'hi_gev': 200, 'upper_inclusive': True}
    manifest['window_gev'] = [100, 200]
    manifest['coverage_gaps'] = [{'lo_gev': 100, 'hi_gev': 200, 'note':'No retained curve'}]
    r = operation.inspect(survey, manifest, contract)
    assert r['render_manifest']['curves'][0]['resolved']['mass_gev'] == []
    contract['window'] = {'lo_gev':150,'hi_gev':500,'upper_inclusive':True}
    manifest['window_gev']=[150,500]
    manifest['coverage_gaps']=[{'lo_gev':150,'hi_gev':250,'note':'No retained curve'}]
    assert operation.inspect(survey,manifest,contract)['render_manifest']['curves'][0]['resolved']['mass_gev'][-1] == 500


def test_plotted_disposition_cannot_be_hidden(tmp_path):
    survey, manifest, contract = fixture(tmp_path)
    manifest['curves'][0]['draw'] = 'none'
    with pytest.raises(ValueError,match='disposition'): operation.inspect(survey,manifest,contract)


def test_finite_json_exponent_and_nesting_guard():
    with pytest.raises(ValueError,match='finite'): operation._json(b'{"hidden":1e400}')
    with pytest.raises(ValueError,match='bounded'): operation._json(('['*26+'0'+']'*26).encode())


def test_new_mode_refuses_legacy_authority_before_consuming_run(tmp_path):
    from ravel.workflow import science
    _, _, contract = fixture(tmp_path)
    spec = {'schema_version':1,'mode':'published-summary','source':'Synthetic source controls',
            'assumptions':['No actual science authority'],'approval_mode':'scripted_yes',
            'max_seconds':60,'task':task(tmp_path,contract)}
    p=tmp_path/'legacy-spec.json';p.write_text(json.dumps(spec))
    with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'run',p)
    assert not (tmp_path/'run').exists()


def test_full_graph_and_real_synthetic_renderer(tmp_path):
    _, _, contract = fixture(tmp_path)
    t = task(tmp_path, contract)
    assert {p.name for p in operation.inputs(t, tmp_path)} == {'contract.json', 'source.txt', 'manifest.json', 'survey.json'}
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    result = operation.run(t, tmp_path, tmp_path / 'published-summary')
    assert result == json.loads((tmp_path / 'published-summary/published-summary.json').read_text())
    assert [s['kind'] for s in result['plotted']['series']] == ['obs', 'exp']
    assert not result['new_limits_derived'] and not result['model_exclusion_inferred']
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert (tmp_path / 'published-summary/summary.png').read_bytes().startswith(b'\x89PNG')
    assert (tmp_path / 'published-summary/summary.pdf').read_bytes().startswith(b'%PDF')
    with pytest.raises(ValueError, match='fresh'): operation.run(t, tmp_path, tmp_path / 'published-summary')


def test_changed_source_after_render_refuses_without_result(tmp_path, monkeypatch):
    from ravel.plotting import summary_overlay
    _, _, contract = fixture(tmp_path)
    t = task(tmp_path, contract)
    def render(manifest, out, **kwargs):
        Path(out + '.png').write_bytes(b'synthetic')
        Path(out + '.pdf').write_bytes(b'synthetic')
        (tmp_path / 'source.txt').write_text('changed')
        return {}
    monkeypatch.setattr(summary_overlay, 'render_manifest', render)
    with pytest.raises(ValueError, match='changed'): operation.run(t, tmp_path, tmp_path / 'delivery')
    assert not (tmp_path / 'delivery/published-summary.json').exists()
    assert (tmp_path / 'delivery/survey.json').exists()  # failed partials retained


@pytest.mark.parametrize('fault', ['duplicate_json', 'bad_pin', 'linked_source', 'task_extra', 'oversize'])
def test_resource_admission_controls(tmp_path, fault):
    _, _, contract = fixture(tmp_path)
    if fault == 'bad_pin': contract['source_assets']['source']['sha256'] = '0' * 64
    if fault == 'linked_source':
        link = tmp_path / 'link'; link.symlink_to(tmp_path / 'source.txt')
        contract['source_assets']['source']['path'] = str(link)
    if fault == 'oversize':
        p = tmp_path / 'source.txt'
        with p.open('wb') as stream: stream.truncate(operation.MAX_SOURCE + 1)
        contract['source_assets']['source'] = pin(p)
    t = task(tmp_path, contract)
    if fault == 'task_extra': t['infer_exclusion'] = True
    if fault == 'duplicate_json':
        p = Path(t['input']); p.write_text('{"schema_version":1,"schema_version":1}')
        t['input_sha256'] = pin(p)['sha256']
    with pytest.raises(ValueError): operation.inputs(t, tmp_path)


def test_actual_public_dispatch_worker_fresh_subdir_without_authority_claim(tmp_path, monkeypatch):
    from ravel.workflow import science
    from ravel.physics import science_worker
    from ravel.plotting.science_figures import render
    _, _, contract = fixture(tmp_path)
    t = task(tmp_path, contract)
    spec = {'mode': 'published-summary', 'task': t, 'schema_version': 2,
            'assumptions': ['Synthetic source control, mocked authorization only.']}
    assert science.adapter(spec) is operation and science._new_capability(spec)
    monkeypatch.setattr(science_worker, 'verify_worker', lambda rd: {
        'attempt': 1, 'output_directory': 'outputs/attempt-1', 'base_dir': str(tmp_path),
        'stage_binding': {'input_snapshot': []}})
    monkeypatch.setattr(science_worker, 'execution_spec', lambda rd: spec)
    assert science_worker.main([str(tmp_path)]) == 0
    out = tmp_path / 'outputs/attempt-1'
    assert json.loads((out / 'checkin2.json').read_text())['sections']['waypoint']['status'] == 'passed'
    figures = json.loads((out / 'figures.json').read_text())
    assert figures['figures'][0]['stem'] == 'published-summary/summary'
    assert 'published-summary/summary.pdf' in figures['figures'][0]['files']
    (out / 'published-summary/summary.pdf').unlink()
    with pytest.raises(ValueError, match='required'): render(spec, json.loads((out / 'result.json').read_text()), tmp_path, out)


def test_legacy_renderer_cli_delegates_without_changing_options(tmp_path, monkeypatch):
    from ravel.plotting import summary_overlay
    _, manifest, _ = fixture(tmp_path)
    path = tmp_path / 'legacy-manifest.json'
    path.write_text(json.dumps(manifest))
    seen = {}
    def render(actual, out, **kwargs):
        seen.update(manifest=actual, out=out, options=kwargs)
        return {'legacy_call': True}
    monkeypatch.setattr(summary_overlay, 'render_manifest', render)
    required = ['--manifest', str(path), '--out', str(tmp_path / 'overlay'),
                '--experiment', 'CMS', '--com', '8']
    # The header luminosity is a required declaration; the command line has no default for it.
    with pytest.raises(SystemExit) as refused: summary_overlay.main(required + ['--no-lint'])
    assert refused.value.code == 2 and not seen
    assert summary_overlay.main(required + ['--lumi', '7', '--no-lint']) == {'legacy_call': True}
    assert seen['manifest'] == manifest
    assert seen['options'] == {'experiment': 'CMS', 'com': 8., 'lumi': 7., 'logy': True, 'allow_lint': True}
    assert type(seen['options']['lumi']) is float


def second_drawn_curve(tmp_path, *, experiment, lumi_fb):
    survey, manifest, contract = fixture(tmp_path)
    survey['candidates'].append({'id': 'C', 'experiment': experiment, 'final_state': 'l-nu-qq',
        'mass_range_gev': [250, 1000], 'provenance': 'digitized',
        'disposition': {'state': 'plotted', 'reason': 'fabricated in-window', 'reviewer': 'synthetic'}})
    curve = deepcopy(manifest['curves'][0])
    curve.update(survey_id='C', source='C l-nu-qq', lumi_fb=lumi_fb)
    manifest['curves'].append(curve)
    contract['survey'] = write(tmp_path / 'survey.json', survey)
    contract['manifest'] = write(tmp_path / 'manifest.json', manifest)
    contract['candidate_sources'].append({'survey_id': 'C', 'mass_range_gev': [250, 1000],
                                          'source_ids': ['source'], 'energy_tev': 13})
    contract['resolved_series_sha256']['C'] = operation.digest(curve['resolved'])
    return survey, manifest, contract


def test_renderer_receives_the_declared_header_luminosity_and_experiment(tmp_path, monkeypatch):
    from ravel.plotting import summary_overlay
    seen = []
    def render(view, out, **kwargs):
        seen.append(kwargs)
        Path(out + '.png').write_bytes(b'synthetic')
        Path(out + '.pdf').write_bytes(b'synthetic')
        return {}
    monkeypatch.setattr(summary_overlay, 'render_manifest', render)
    _, manifest, contract = second_drawn_curve(tmp_path, experiment='ATLAS', lumi_fb=1)
    manifest['curves'][0]['lumi_fb'] = manifest['curves'][1]['lumi_fb'] = 3.5
    contract['manifest'] = write(tmp_path / 'manifest.json', manifest)
    operation.run(task(tmp_path, contract), tmp_path, tmp_path / 'delivery')
    assert seen == [{'experiment': 'ATLAS', 'com': 13, 'lumi': 3.5}]


@pytest.mark.parametrize('experiment,lumi_fb,reason', [
    ('ATLAS', 2, 'one declared luminosity'), ('CMS', 1, 'one declared experiment'),
    (None, 1, 'one declared experiment'), ('', 1, 'one declared experiment')])
def test_ambiguous_header_declaration_is_refused_before_delivery(tmp_path, monkeypatch, experiment, lumi_fb, reason):
    from ravel.plotting import summary_overlay
    monkeypatch.setattr(summary_overlay, 'render_manifest',
                        lambda *a, **k: pytest.fail('renderer reached without one declared header'))
    _, _, contract = second_drawn_curve(tmp_path, experiment=experiment, lumi_fb=lumi_fb)
    with pytest.raises(ValueError, match=reason): operation.run(task(tmp_path, contract), tmp_path, tmp_path / 'delivery')
    assert not (tmp_path / 'delivery').exists()


def test_real_synthetic_coverage_only_renderer_retains_scope(tmp_path):
    survey, manifest, contract = fixture(tmp_path)
    contract['window'] = {'lo_gev': 100, 'hi_gev': 200, 'upper_inclusive': False}
    manifest['window_gev'] = [100, 200]
    manifest['coverage_gaps'] = [{'lo_gev':100, 'hi_gev':200, 'note':'No retained curve in supplied census'}]
    contract['manifest'] = write(tmp_path/'manifest.json', manifest)
    result = operation.run(task(tmp_path, contract), tmp_path, tmp_path/'coverage-only')
    assert result['plotted']['drawn_curves'] == 0 and result['plotted']['series'] == []
    assert result['plotted']['plot_lint'] == 'passed'
    assert result['complete_series_rows'] and result['model_exclusion_inferred'] is False
    assert (tmp_path/'coverage-only/summary.png').stat().st_size > 0
    assert (tmp_path/'coverage-only/summary.pdf').stat().st_size > 0


def test_no_interpolated_boundary_or_beyond_window_anchor(tmp_path):
    survey, manifest, contract = fixture(tmp_path)
    manifest['curves'][0]['resolved']['mass_gev'][3] = 550
    contract['resolved_series_sha256']['A'] = operation.digest(manifest['curves'][0]['resolved'])
    r = operation.inspect(survey,manifest,contract)
    assert r['render_manifest']['curves'][0]['resolved']['mass_gev'] == [250,300,450]
    assert r['render_manifest']['excluded_boundary_anchors'] == []
    assert all(row['mass_gev'] != 500 for row in r['complete_series_rows'])
    assert 'not search-reach' in r['render_manifest']['annotations'][2]


def test_closed_upper_bound_is_selected_without_excluded_anchor(tmp_path):
    survey, manifest, contract = fixture(tmp_path)
    contract['window']['upper_inclusive'] = True
    r = operation.inspect(survey,manifest,contract)
    assert r['render_manifest']['excluded_boundary_anchors'] == []
    assert all(row['in_requested_window'] for row in r['complete_series_rows'] if row['mass_gev']==500)


def test_boundary_only_value_does_not_create_a_coverage_curve(tmp_path):
    survey, manifest, contract = fixture(tmp_path)
    contract['window'] = {'lo_gev':150,'hi_gev':250,'upper_inclusive':False}
    manifest['window_gev'] = [150,250]
    manifest['coverage_gaps'] = [{'lo_gev':150,'hi_gev':250,'note':'No retained curve'}]
    r = operation.inspect(survey,manifest,contract)
    assert r['render_manifest']['excluded_boundary_anchors'] == []
    assert r['render_manifest']['curves'][0]['resolved']['mass_gev'] == []
