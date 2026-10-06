"""Numerical meaning must survive actual engine/pack/scan/plot boundaries."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.limits import (LimitCurve, attach_limits, read_limits, point_value,
                         claim_errors, prose_errors, rescale_artifact, bind_source, source_errors)
from ravel.workflow import scan_orchestrator as scan
from ravel.workflow.result_pack import build_result
from ravel.plotting.scan_contour import comparison_data, load_scan, _plot_value


def exclusion():
    return {
        'obs_limit': .8, 'exp_limits': [.4, .7, 1.2, 2., 2.],
        'at_mu_floor': False, 'at_poi_cap': False, 'median_at_cap': False,
        'limit_status': {'observed': 'resolved', 'expected':
                         ['resolved', 'resolved', 'resolved', 'above_scan', 'above_scan']},
        'limit_brackets': {'observed': [.79, .81], 'expected':
                           [[.39, .41], [.69, .71], [1.19, 1.21], [2., None], [2., None]]},
        'fit_diagnostics': {'available': True, 'covariance': None},
        'inference': {'coverage_validated': False},
        'numerical_evidence': {'coverage_validated': False, 'observed': {'status': 'resolved'}},
    }


def packed(excl):
    args = SimpleNamespace(routine=None, analysis_id=None, model=None, driving_sr=None,
                           sigma_lo_pb=1., m_parent=150., m_lsp=140., lumi_fb=139.,
                           stat_mode='published-likelihood', detector_mode='simpleanalysis-delphes',
                           limitations='')
    return build_result(args, '/run', {}, excl, None, None, [], {})


def point_dir(tmp_path, doc):
    (tmp_path / 'output').mkdir(exist_ok=True)
    (tmp_path / 'output/exclusion.json').write_text(json.dumps(doc))
    return {'run_dir': str(tmp_path), 'tag': 'p1', 'm_parent': 150., 'm_lsp': 140.}


def test_retained_probe_expected_bounds_survive_harvest(tmp_path):
    original = exclusion()
    mp = point_dir(tmp_path, original)
    result = scan.harvest_point(mp)
    assert result['limit_status'] == original['limit_status']
    assert result['limit_brackets'] == original['limit_brackets']
    assert result['fit_diagnostics'] == original['fit_diagnostics']
    assert result['numerical_evidence'] == original['numerical_evidence']
    assert point_value(result) == .8
    assert point_value(result, 3) is None
    assert scan.point_status(mp) == ('done', .8)  # completion is distinct from eligibility


def test_preferred_headline_cannot_erase_explicit_bound(tmp_path):
    mp = point_dir(tmp_path, exclusion())
    d = {'mu95_obs': .2, 'mu95_exp': .4, 'mu95_exp_band': [.1, .2, .4, .6, .8],
         'quality': 'floored', 'limit_status': {'observed': 'below_scan', 'expected': ['below_scan'] * 5}}
    (tmp_path / 'output/exclusion.json').write_text(json.dumps(d))
    bind_source(d, tmp_path, 'output/exclusion.json')
    (tmp_path / 'result.json').write_text(json.dumps(d))
    h = scan.harvest_point(mp)
    assert h['source'] == 'result.json'
    assert h['quality'] == 'floored'
    assert read_limits(h).observed.status == 'below_scan'
    assert point_value(h, allow_legacy=True) is None


@pytest.mark.parametrize('bad', [True, -1., float('nan'), float('inf'), '1.0'])
def test_nonphysical_scalar_cannot_enter_a_typed_result(bad):
    d = exclusion(); d['obs_limit'] = bad
    with pytest.raises(ValueError):
        read_limits(d)


@pytest.mark.parametrize('change', ['scalar', 'status', 'bracket', 'eligibility', 'cap'])
def test_conflicting_aliases_and_forged_eligibility_rejected(change):
    d = attach_limits(exclusion())
    if change == 'scalar': d['obs_limit'] = .3
    if change == 'status': d['limit_status']['observed'] = 'above_scan'
    if change == 'bracket': d['limit_brackets']['observed'] = [.1, .2]
    if change == 'eligibility': d['limit_eligibility']['expected_roots'] = [True] * 5
    if change == 'cap': d['at_poi_cap'] = True
    assert claim_errors(d)


@pytest.mark.parametrize('status,value,want', [
    ('below_scan', .5, True), ('below_scan', 2., None),
    ('above_scan', 2., False), ('above_scan', .5, None),
    ('missing', None, None), ('unverified', .5, None),
    ('legacy_reported', .5, None), ('resolved', .5, True), ('resolved', 2., False),
])
def test_directional_exclusion_is_not_scalar_thresholding(status, value, want):
    assert LimitCurve(value, status).exclusion() is want


def test_legacy_policy_does_not_promote_unflagged_archives():
    doc = {'mu95_obs': .5, 'mu95_exp': 1.2}
    d = attach_limits(doc)
    assert read_limits(d).observed.status == 'legacy_reported'
    assert point_value(d) is None
    assert point_value(d, allow_legacy=True) == .5
    assert d['limit_eligibility']['historical_only']
    fresh = attach_limits({'mu95_obs': .5}, source='shape-fit-unverified')
    assert read_limits(fresh).observed.status == 'unverified'


def test_missing_expected_slots_survive_and_are_not_fabricated():
    d = attach_limits({'obs_limit': .8, 'exp_limits': [None, None, 1.2, None, None],
                       'limit_status': {'observed': 'resolved', 'expected': ['missing', 'missing', 'resolved', 'missing', 'missing']}})
    assert read_limits(d).expected[0].to_dict() == dict(value=None, status='missing', bracket=None)
    assert point_value(d, 'expected') == 1.2
    assert point_value(d, 0) is None
    assert packed(d)['mu95_exp_band'] == [None, None, 1.2, None, None]


def test_positive_rescaling_preserves_bound_type_and_brackets():
    d = attach_limits(exclusion())
    rescale_artifact(d, 2.)
    assert d['obs_limit'] == 1.6
    assert d['limit_brackets']['observed'] == [1.58, 1.62]
    assert d['limit_brackets']['expected'][4] == [4., None]
    assert read_limits(d).expected[4].status == 'above_scan'
    with pytest.raises(ValueError): rescale_artifact(d, -1)


def test_malformed_preferred_result_does_not_fall_back_to_old_output(tmp_path):
    mp = point_dir(tmp_path, exclusion())
    (tmp_path / 'result.json').write_text('{')
    with pytest.raises(ValueError, match='result.json'):
        scan.harvest_point(mp)
    assert scan.point_status(mp) == ('failed', None)


def test_end_to_end_pack_assemble_plot_comparison_and_claim(tmp_path, monkeypatch):
    original = attach_limits(exclusion())
    result = packed(original)
    assert result['limits'] == original['limits']
    mp = point_dir(tmp_path, original)
    bind_source(result, tmp_path, 'output/exclusion.json')
    (tmp_path / 'result.json').write_text(json.dumps(result))
    manifest = {'name': 'test', 'points': [mp], 'n_points': 1}
    monkeypatch.setattr(scan, 'load_manifest', lambda _: (str(tmp_path), manifest))
    path = tmp_path / 'scan.json'
    scan.cmd_assemble(SimpleNamespace(scandir=str(tmp_path), out=str(path), nlo_renorm=None))
    loaded = load_scan(path)
    p = loaded['points'][0]
    assert p['limits'] == original['limits']
    assert p['numerical_evidence'] == original['numerical_evidence']
    assert p['excluded_obs'] is True
    assert loaded['n_observed_roots'] == 1
    assert _plot_value(p, 'expected') == 1.2
    assert _plot_value(p, 4) != _plot_value(p, 4)  # NaN gap; never a filled band endpoint
    p['sigma_ref_fb'] = 5.
    report = comparison_data(loaded, ([150.], [10.], [4.]))
    assert report['counts']['matched'] == 1
    assert report['records'][0]['limit_status'] == 'resolved'
    bad = copy.deepcopy(p)
    bad['limits']['observed'] = dict(value=.8, status='above_scan', bracket=[.8, None])
    bad['limit_status']['observed'] = 'above_scan'
    bad['limit_brackets']['observed'] = [.8, None]
    bad['at_poi_cap'] = True
    attach_limits(bad)
    assert claim_errors(bad)  # excluded=True is unsupported when root might be either side of 1
    assert prose_errors('mu95_obs = 0.8', bad)
    assert not prose_errors('mu95_obs > 0.8 (scan bound)', bad)
    assert comparison_data({'points': [bad]}, ([150.], [10.], [4.]))['counts']['quality_flag'] == 1


def test_legacy_converter_normalization_is_not_corrected_twice(tmp_path):
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'logs/analysis.log').write_text('Using cross section 2.4\n')
    (tmp_path / 'config.toml').write_text('[analysis]\nkfactor = 1.2\n')
    p = {'run_dir': str(tmp_path), 'config': 'config.toml'}
    assert scan.sigma_ref_fb(p) == 2400.
    (tmp_path / 'logs/madgraph.log').write_text('Cross-section : 2.0\n')
    assert scan.sigma_ref_fb(p) == 2400.
    (tmp_path / 'config.toml').write_text('[analysis]\n')
    assert scan.point_kfactor(p) is None
    assert scan.sigma_ref_fb(p) is None


def test_bound_quantiles_cannot_contradict_known_roots():
    d = exclusion()
    d['exp_limits'][0] = 2.
    d['limit_status']['expected'][0] = 'above_scan'
    d['limit_brackets']['expected'][0] = [2., None]
    with pytest.raises(ValueError, match='ordering'):
        read_limits(d)


def test_pack_and_live_invariant_reject_laundered_bound(tmp_path):
    from ravel.validation.verify_pack import Report, check_result
    from ravel.validation.validate_run_state import inv_limit_transport
    d = packed(exclusion())
    d['mu95_obs'] = .1  # unchanged canonical result contradicts scalar
    report = Report()
    check_result(report, str(tmp_path), {}, 'result.json', d, None)
    assert any(level == 'FAIL' for level, _, _ in report.lines)
    (tmp_path / 'result.json').write_text(json.dumps(d))
    verdict, reason = inv_limit_transport(str(tmp_path), {},
        {'result_pack_paths': {'result.json': 'result.json'}}, False, True)
    assert verdict == 'FAIL'
    assert 'conflicts' in reason


@pytest.mark.parametrize('status', ['above_scan', 'below_scan', 'legacy_reported', 'unverified'])
def test_unqualified_prose_cannot_turn_nonroot_into_root(status):
    d = {'mu95_obs': .5, 'limit_status': {'observed': status, 'expected': ['missing'] * 5}}
    assert prose_errors('mu95_obs = 0.5', d)
    assert prose_errors('µ95_obs = 0.5', d)
    assert not prose_errors(f'mu95_obs = 0.5 (unverified bound; {status})', d)


@pytest.mark.parametrize('quality,status', [('capped', 'below_scan'), ('floored', 'above_scan')])
def test_directionally_contradictory_quality_is_not_accepted(quality, status):
    d = {'mu95_obs': .5, 'quality': quality,
         'limit_status': {'observed': status, 'expected': ['missing'] * 5}}
    assert claim_errors(d)


def test_actual_plot_does_not_fill_censored_expected_band(tmp_path, monkeypatch):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from ravel.plotting import scan_contour as renderer
    saved = []
    monkeypatch.setattr(renderer, 'setup', lambda args: (plt, None))
    monkeypatch.setattr(renderer, 'save', lambda fig, stem: saved.append(fig))
    monkeypatch.setattr(renderer.house, 'smart_annotate', lambda *args, **kwargs: None)
    monkeypatch.setattr(renderer.house, 'smart_legend', lambda *args, **kwargs: None)
    args = SimpleNamespace(out=str(tmp_path/'figure'), logx=None, logy=None,
                           contract_axes=None, experiment='ATLAS', lumi=139, com=13)
    points = []
    for dm in (10., 20., 30.):
        p = packed(exclusion()); p.update(dm=dm, m_lsp=150.-dm, tag=str(dm))
        points.append(p)
    renderer.render_line({'points': points, 'n_done': 3, 'n_planned': 3}, [], args)
    # Both filled bands include a censored upper endpoint at every x: no polygon.
    assert all(not collection.get_paths() for collection in saved[-1].axes[0].collections)
    for p in points:
        p['limit_status']['expected'][-2:] = ['resolved', 'resolved']
        p['limit_brackets']['expected'][-2:] = [[1.9, 2.1], [1.9, 2.1]]
        del p['limits']
        attach_limits(p)
    renderer.render_line({'points': points, 'n_done': 3, 'n_planned': 3}, [], args)
    assert any(collection.get_paths() for collection in saved[-1].axes[0].collections)
    plt.close('all')


def test_real_execution_receipt_staleness_blocks_harvest(tmp_path):
    from ravel.workflow.stage_supervisor import supervise
    source = tmp_path/'input.json'; source.write_text(json.dumps(exclusion()))
    (tmp_path/'output').mkdir()
    code = "import shutil; shutil.copyfile('input.json','output/exclusion.json')"
    assert supervise('fit', tmp_path, 1, 'logs/fit.log', [sys.executable, '-c', code],
        inputs=['input.json'], outputs=['output/exclusion.json'], depends_on=[],
        cwd=str(tmp_path), resume=True, poll=.02, grace=.1, kill_secs=4) == 0
    mp = {'run_dir': str(tmp_path), 'm_parent': 150., 'm_lsp': 140.}
    assert scan.harvest_point(mp)['mu95_obs'] == .8
    assert scan.point_status(mp)[0] == 'pending'  # no final native_report receipt yet
    source.write_text(json.dumps({**exclusion(), 'obs_limit': .9}))
    with pytest.raises(ValueError, match='stale/invalid execution'):
        scan.harvest_point(mp)
    assert scan.point_status(mp)[0] == 'failed'


def test_prior_attempts_and_state_views_are_not_scientific_artifacts(tmp_path):
    from ravel.validation.verify_pack import file_index, find_artifact_jsons, resolve_ref
    old = tmp_path/'logs/execution/fit/old/prior_outputs/0/result.json'
    old.parent.mkdir(parents=True); old.write_text('{')
    (tmp_path/'current_state.json').write_text('{')
    (tmp_path/'execution_state.json').write_text('{')
    (tmp_path/'output').mkdir(); (tmp_path/'output/exclusion.json').write_text('{}')
    assert find_artifact_jsons(tmp_path) == ['output/exclusion.json']
    assert not any('prior_outputs' in name for name in file_index(tmp_path))
    assert resolve_ref(str(tmp_path), file_index(tmp_path), str(old.relative_to(tmp_path))) is None


def test_projection_transport_retains_censoring_and_numerical_evidence(tmp_path, monkeypatch):
    from ravel.physics import project_limits as projection
    original = attach_limits(exclusion())
    source = tmp_path/'srs.json'; source.write_text('[]')
    monkeypatch.setattr(projection, 'project_srs', lambda *args: [])
    monkeypatch.setattr(projection, 'run_engine', lambda *args, **kwargs: original)
    args = SimpleNamespace(srs=str(source), out=str(tmp_path/'projection'),
        bkg_scaling='syst', lumi_factor=2., sigma_scale=1., combined=False)
    projection.cmd_counting(args)
    output = json.loads((tmp_path/'projection/projection.json').read_text())['scenarios']['syst']
    assert output['limits']['expected'] == original['limits']['expected']
    assert point_value(output, 'observed') is None
    assert read_limits(output).observed.status == 'missing'
    assert read_limits(output).observed.exclusion() is None
    assert output['diagnostic_observed']['value'] == .8
    assert output['numerical_evidence'] == original['numerical_evidence']
    assert 'not an observed projection' in output['observed_semantics']
    bound = copy.deepcopy(original)
    bound['limit_status']['expected'][2] = 'above_scan'
    bound['limit_brackets']['expected'][2] = [1.2, None]
    bound['median_at_cap'] = True
    del bound['limits']
    with pytest.raises(ValueError, match='expected median'):
        projection._limits(bound)  # never substitute its usable observed value


def test_likelihood_projection_proxy_cannot_become_observed_limit(tmp_path, monkeypatch):
    from ravel.physics import project_limits as projection
    original = attach_limits(exclusion())
    def extract(bkg, patches, directory, names):
        Path(directory).mkdir(); (Path(directory)/'patched_test.json').write_text('{}')
        return ['test']
    monkeypatch.setattr(projection, 'extract_patched', extract)
    monkeypatch.setattr(projection, 'project_workspace', lambda *args: {})
    monkeypatch.setattr(projection, 'run_engine_likelihood', lambda *args: original)
    args = SimpleNamespace(out=str(tmp_path/'projection'), all_patches=True,
        bkg='fixture', patchset='fixture', bkg_scaling='syst', lumi_factor=2., workers=1)
    projection.cmd_likelihood(args)
    row = json.loads((tmp_path/'projection/projection.json').read_text())['points'][0]
    assert row['diagnostic_observed']['role'] == 'scaled-data proxy; not observed data'
    assert row['diagnostic_observed']['value'] == .8
    assert point_value(row) is None and not row['limit_eligibility']['observed_root']
    assert point_value(row, 'expected') == 1.2


def test_coherent_pack_edit_cannot_borrow_source_acceptance_certificate(tmp_path):
    import runpy
    from ravel.validation import certificates, validate_run_state as vrs
    fixture = runpy.run_path(str(Path(__file__).with_name('test_certificates.py')))
    contract, _, subject = fixture['fixture'](tmp_path, kind='acceptance', mode='none')
    source = attach_limits(exclusion())
    fixture['write'](tmp_path, subject, source)
    certificates.create_certificate(tmp_path, 'inputs/acceptance-plan.json', 'outputs/acceptance-certificate.json')
    pack = packed(source)
    pack['pointers']['exclusion'] = subject
    bind_source(pack, tmp_path, subject)
    fixture['write'](tmp_path, 'result.json', pack)
    facts = vrs.discover_facts(str(tmp_path), contract)
    assert vrs.inv_certify_before_limit(str(tmp_path), contract, facts, False, True)[0] == 'PASS'
    assert vrs.inv_limit_transport(str(tmp_path), contract, facts, False, True)[0] == 'PASS'
    rescale_artifact(pack, .01)
    pack['mu95_baseline'] = pack['mu95_obs']
    fixture['write'](tmp_path, 'result.json', pack)
    assert not claim_errors(pack)  # paired internally consistent adversary
    assert source_errors(pack, tmp_path)
    assert vrs.inv_certify_before_limit(str(tmp_path), contract, facts, False, True)[0] == 'FAIL'
    assert vrs.inv_limit_transport(str(tmp_path), contract, facts, False, True)[0] == 'FAIL'
    mp = {'run_dir': str(tmp_path), 'm_parent': 150., 'm_lsp': 140.}
    with pytest.raises(ValueError, match='bound primary inference'):
        scan.harvest_point(mp)


def test_source_binding_rejects_stale_identity_and_different_certified_subject(tmp_path):
    source = attach_limits({**exclusion(), 'm_parent': 150., 'model': 'slepton-bino'})
    path = tmp_path/'exclusion.json'; path.write_text(json.dumps(source))
    pack = packed(source); pack['model'] = 'slepton-bino'
    bind_source(pack, tmp_path, 'exclusion.json')
    assert not source_errors(pack, tmp_path)
    pack['m_parent'] = 151.
    assert source_errors(pack, tmp_path)
    pack['m_parent'] = 150.
    assert source_errors(pack, tmp_path, expected_path='other/exclusion.json')
    path.write_text(json.dumps({**source, 'new_diagnostic': 1}))
    assert 'bytes changed' in source_errors(pack, tmp_path)[0]


@pytest.mark.parametrize('field', ['sigma_ref_fb', 'sigma_ul_ours_fb', 'sigma_scale_k',
    'sigma_lo_pb', 's95_obs', 's95_exp', 'driving_sr_s', 'mu95_baseline', 'n_srs'])
def test_each_derived_headline_is_checked_against_primary_operands(tmp_path, field):
    source = attach_limits({**exclusion(), 'sigma_scale_k': 1., 'sigma_lo_pb': 1., 'best_sr': 'A'})
    source['per_sr'] = {'A': attach_limits({**exclusion(), 's': 10.})}
    path = tmp_path/'exclusion.json'; path.write_text(json.dumps(source))
    pack = packed(source); bind_source(pack, tmp_path, 'exclusion.json')
    assert pack['sigma_ref_fb'] == 1000. and pack['sigma_ul_ours_fb'] == 800.
    assert pack['s95_obs'] == 8. and pack['s95_exp'] == 12.
    assert not source_errors(pack, tmp_path)
    pack[field] = .001
    assert source_errors(pack, tmp_path)


def test_coherent_sigma_and_yield_summary_edits_cannot_override_primary_files(tmp_path):
    source = attach_limits({**exclusion(), 'sigma_scale_k': 1.})
    (tmp_path/'exclusion.json').write_text(json.dumps(source))
    provenance = {'sigma_pb': 1., 'lumi_fb': 139., 'sigma_source': 'declared fixture'}
    yields = [{'name': 'A', 'n': 2, 'b': 1., 'db': .1, 's': 3.}]
    (tmp_path/'provenance.json').write_text(json.dumps(provenance))
    (tmp_path/'yields.json').write_text(json.dumps(yields))
    pack = packed(source)
    pack['pointers'].update(provenance='provenance.json', sr_yields='yields.json')
    pack.update(sigma_source='declared fixture', n_srs=1, sr_yields_summary=yields)
    bind_source(pack, tmp_path, 'exclusion.json')
    altered = copy.deepcopy(pack)
    altered.update(sigma_lo_pb=.01, sigma_ref_fb=10., sigma_ul_ours_fb=8.)
    assert source_errors(altered, tmp_path)
    altered = copy.deepcopy(pack); altered['sr_yields_summary'][0]['n'] = 99
    assert source_errors(altered, tmp_path)
    altered = copy.deepcopy(pack); altered['sr_yields_summary'][0]['b'] = True
    assert source_errors(altered, tmp_path)  # bool is not an observed numeric quantity
