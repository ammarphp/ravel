"""Artifact-bound comparison and serving checks; no event generation."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from ravel.validation import certificates as c
from ravel.validation import validate_run_state as vrs
from ravel.validation.validate_task_contract import validate
from ravel.physics import shape_fit as sf

REPO = Path(__file__).resolve().parents[2]


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2) + '\n')


def pin(root, path):
    return {k: v for k, v in c.binding(root, path).items() if k != 'mode'}


def approve_run(root, mode='smoke'):
    write(root, 'inputs/checkin1.json', {'schema_version': 1, 'kind': 'checkin1', 'sections': {
        'i': 'declared target', 'i-b': 'known resources', 'ii': 'figure scope',
        'iii': {'plan': 'bounded comparison', 'waypoint': 'reference comparisons'},
        'iv': 'budget', 'v': [{'id': 'F1', 'text': 'declared normalization'}],
        'vi': ['answer', 'ask', 'propose']}})
    write(root, 'inputs/cost_preflight.json', {'schema_version': 1, 'generated_by': 'cost_preflight.py',
          'mode': mode, 'walltime_h': [0, 0] if mode in ('none', 'dry') else [.5, 1]})
    result = subprocess.run([sys.executable, str(REPO / 'scripts/run.py'),
        'ravel.workflow.workflow_state', 'approve', '--rundir', str(root), '--plan', mode,
        '--quote', 'Approved the declared fixture comparison'], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def fixture(root, kind='r5', approve=True, mode='smoke'):
    context = dict(analysis_id='ATLAS-TEST', quantity='mu95_exp' if kind == 'r5' else 'acceptance',
                   units='dimensionless', basis={'process': 'test-model', 'normalization': 'selected/generated'})
    write(root, 'inputs/model.json', {'selection': 'fixed-before-comparison'})
    refs, comparisons = [], []
    for i, mass in enumerate((100, 200)):
        ctx = {**context, 'point_id': f'm{mass}', 'parameters': {'mass_gev': mass}, 'reference_id': f'published-row-{i}'}
        refs.append(c.measurement(ctx, 1.0 + i, quantity=context['quantity']))
        write(root, f'outputs/pred{i}.json', {'validation_point': c.measurement(ctx, 1.01 + i, quantity=context['quantity'])})
        comparisons.append({'point_id': ctx['point_id'], 'parameters': ctx['parameters'], 'reference_id': ctx['reference_id'],
            'prediction': {'path': f'outputs/pred{i}.json', 'record_pointer': '/validation_point'},
            'reference': {'path': 'inputs/reference.json', 'record_pointer': f'/points/{i}'}})
    write(root, 'inputs/reference.json', {'points': refs})
    for item in comparisons:
        item['reference']['sha256'] = c.digest(root / 'inputs/reference.json')
    subject = 'outputs/shape_fit.json' if kind == 'r5' else 'outputs/exclusion.json'
    write(root, subject, {'mu95_obs': 1.2, 'mu95_exp': 1.1, 'r5_status': 'held'})
    plan = {'schema_version': 1, 'kind': kind, **context, 'policy': {'claim': 'central-value', 'relative_tolerance': .15},
        'dependencies': [pin(root, 'inputs/model.json')], 'subjects': [subject], 'comparisons': comparisons}
    plan_path = f'inputs/{kind}-plan.json'
    write(root, plan_path, plan)
    contract = vrs._base_contract(task_mode='reproduce', stat_mode='shape-fit' if kind == 'r5' else 'best-sr-counting',
                                 compute_plan=mode, targets={'analysis': ['ATLAS-TEST']})
    contract['certification_plans'] = {kind: pin(root, plan_path)}
    write(root, 'inputs/task_contract.json', contract)
    if approve:
        approve_run(root, mode)
    c.create_certificate(root, plan_path, f'outputs/{kind}-certificate.json')
    return contract, plan, subject


def check(root, contract, kind='r5', subject=None, live=True):
    return c.validate_certificate(root, f'outputs/{kind}-certificate.json', kind=kind, contract=contract,
        required_subjects=[subject] if subject else (), live=live)


def test_approved_comparison_recomputed_read_only(tmp_path):
    contract, _, subject = fixture(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = check(tmp_path, contract, subject=subject)
    assert result['status'] == 'PASS', result
    assert result['evidence']['comparisons'][0]['relative_residual'] == pytest.approx(.01)
    assert 'no detector or coverage' in result['evidence']['scope']
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('changed', ['outputs/pred0.json', 'outputs/shape_fit.json', 'inputs/model.json', 'inputs/reference.json'])
def test_changed_scientific_artifact_fails(tmp_path, changed):
    contract, _, subject = fixture(tmp_path)
    obj = c.read_json(tmp_path / changed)
    obj['tampered'] = True
    write(tmp_path, changed, obj)
    result = check(tmp_path, contract, subject=subject)
    assert result['status'] == 'FAIL' and 'changed artifact' in str(result)


def test_certificate_comparison_omission_fails(tmp_path):
    contract, _, _ = fixture(tmp_path)
    cert = c.read_json(tmp_path / 'outputs/r5-certificate.json')
    cert['comparisons'] = cert['comparisons'][:1]
    cert['verdict'] = 'PASS'
    write(tmp_path, 'outputs/r5-certificate.json', cert)
    assert check(tmp_path, contract)['status'] == 'FAIL'


@pytest.mark.parametrize('change', ['mass', 'point_id', 'reference_id', 'units', 'basis', 'analysis_id'])
def test_wrong_measurement_identity_cannot_be_certified(tmp_path, change):
    _, plan, _ = fixture(tmp_path)
    path = 'outputs/pred0.json' if change != 'reference_id' else 'inputs/reference.json'
    obj = c.read_json(tmp_path / path)
    point = obj['validation_point'] if change != 'reference_id' else obj['points'][0]
    if change == 'mass':
        point['parameters']['mass_gev'] = 101
    elif change == 'basis':
        point[change]['normalization'] = 'cross-section-pb'
    else:
        point[change] = 'wrong'
    write(tmp_path, path, obj)
    if change == 'reference_id':
        for comp in plan['comparisons']:
            comp['reference']['sha256'] = c.digest(tmp_path / path)
        write(tmp_path, 'inputs/r5-plan.json', plan)
    with pytest.raises(c.CertificateError, match='mismatch'):
        c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/new-cert.json')


@pytest.mark.parametrize('change', ['duplicate_mass', 'duplicate_point', 'duplicate_reference', 'no_mass'])
def test_duplicate_or_unnamed_identity_rejected(tmp_path, change):
    _, plan, _ = fixture(tmp_path)
    a, b = plan['comparisons']
    if change == 'duplicate_mass':
        b['parameters'] = {'mass_gev': a['parameters']['mass_gev'], 'unrelated': 2}
    elif change == 'duplicate_point':
        b['point_id'] = a['point_id']
    elif change == 'duplicate_reference':
        b['reference'] = copy.deepcopy(a['reference'])
    else:
        a['parameters'] = {'arbitrary': 100}
    write(tmp_path, 'inputs/r5-plan.json', plan)
    with pytest.raises(c.CertificateError):
        c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/new-cert.json')


def test_repinning_edited_tolerance_needs_renewed_approval(tmp_path):
    contract, plan, subject = fixture(tmp_path)
    plan['policy']['relative_tolerance'] = .5
    write(tmp_path, 'inputs/r5-plan.json', plan)
    c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/r5-certificate.json')
    assert 'not pinned' in str(check(tmp_path, contract))
    contract['certification_plans']['r5'] = pin(tmp_path, 'inputs/r5-plan.json')
    write(tmp_path, 'inputs/task_contract.json', contract)
    assert 'approval binding' in str(check(tmp_path, contract))
    approve_run(tmp_path)
    assert check(tmp_path, contract, subject=subject)['status'] == 'PASS'


def test_unapproved_comparison_is_not_live_authority(tmp_path):
    contract, _, _ = fixture(tmp_path, approve=False)
    assert check(tmp_path, contract, live=False)['status'] == 'PASS'
    assert check(tmp_path, contract, live=True)['status'] == 'FAIL'


def test_precision_requires_uncertainties_and_never_claims_coverage(tmp_path):
    _, plan, _ = fixture(tmp_path)
    plan['policy'] = {'claim': 'precision', 'relative_tolerance': .15, 'max_relative_uncertainty': .05, 'sigma_factor': 1}
    write(tmp_path, 'inputs/r5-plan.json', plan)
    with pytest.raises(c.CertificateError, match='uncertainty'):
        c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/precision.json')
    refs = c.read_json(tmp_path / 'inputs/reference.json')
    for i in range(2):
        path = f'outputs/pred{i}.json'
        pred = c.read_json(tmp_path / path)
        pred['validation_point']['uncertainty'] = {'standard': .01, 'source': 'MC study', 'independence_group': 'simulation'}
        refs['points'][i]['uncertainty'] = {'standard': .01, 'source': 'reference table', 'independence_group': 'published'}
        write(tmp_path, path, pred)
    write(tmp_path, 'inputs/reference.json', refs)
    for comp in plan['comparisons']:
        comp['reference']['sha256'] = c.digest(tmp_path / 'inputs/reference.json')
    write(tmp_path, 'inputs/r5-plan.json', plan)
    result = c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/precision.json')
    assert result['verdict'] == 'PASS' and 'no coverage certification' in result['scope']
    plan['policy']['claim'] = 'calibrated'
    write(tmp_path, 'inputs/r5-plan.json', plan)
    with pytest.raises(c.CertificateError, match='coverage/calibration'):
        c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/calibrated.json')


def test_r5_live_consumer_ignores_boolean_and_markdown_claims(tmp_path):
    contract, _, subject = fixture(tmp_path)
    facts = dict(statistics_path=subject, statistics_artifact_name='shape_fit.json', fold_result_path=None,
        replane_path=None, result_pack_paths={'result.json': 'result.json'}, verification_json_path=None, ladder_path='ladder.md')
    assert vrs.inv_r5_before_limit(str(tmp_path), contract, facts, False, True)[0] == 'PASS'
    (tmp_path / 'outputs/r5-certificate.json').unlink()
    write(tmp_path, subject, {'r5_status': 'closed', 'r5_reference_points': [{'in_tolerance': True}] * 2})
    (tmp_path / 'ladder.md').write_text('| R5 | checked-pass |\n')
    assert vrs.inv_r5_before_limit(str(tmp_path), contract, facts, False, True)[0] == 'FAIL'


def test_acceptance_consumer_binds_current_statistics(tmp_path):
    contract, _, subject = fixture(tmp_path, kind='acceptance')
    facts = vrs.discover_facts(str(tmp_path), contract)
    facts['statistics_path'] = subject
    assert vrs.inv_certify_before_limit(str(tmp_path), contract, facts, False, True)[0] == 'PASS'
    write(tmp_path, subject, {'mu95_obs': .001})
    assert vrs.inv_certify_before_limit(str(tmp_path), contract, facts, False, True)[0] == 'FAIL'


@pytest.mark.parametrize('raw', ['{"value": NaN}', '{"value": 1e999}', '{"value": 1,"value": 2}'])
def test_strict_json_rejects_nonfinite_and_duplicate_keys(tmp_path, raw):
    path = tmp_path / 'bad.json'
    path.write_text(raw)
    with pytest.raises(ValueError):
        c.read_json(path)


def test_symlink_output_and_input_overwrite_refused(tmp_path):
    fixture(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + '-outside')
    outside.mkdir()
    (tmp_path / 'escape').symlink_to(outside, target_is_directory=True)
    for output in ('escape/cert.json', 'inputs/model.json', '../escape.json'):
        with pytest.raises(c.CertificateError):
            c.create_certificate(tmp_path, 'inputs/r5-plan.json', output)
    assert list(outside.iterdir()) == []


def test_contract_rejects_nonportable_plan(tmp_path):
    contract, _, _ = fixture(tmp_path)
    assert validate(contract) == []
    contract['certification_plans']['r5']['path'] = '../plan.json'
    assert any('portable' in e for e in validate(contract))


def test_acceptance_values_come_from_complete_computed_sr_population():
    ctx = dict(point_id='sr1', parameters={'mass_gev': 100}, analysis_id='A', quantity='acceptance',
               units='dimensionless', basis={'normalization': 'selected/generated'})
    rows = [{'sr': 'SR1', 'mine': .002, 'node': 'grid node (100,0)'}]
    assert c.acceptance_points(rows, {'SR1': ctx})[0]['value'] == .002
    for contexts in ({}, {'SR1': {**ctx, 'value': 999}}):
        with pytest.raises(c.CertificateError):
            c.acceptance_points(rows, contexts)


def test_shape_numerical_bracket_and_failure_controls(monkeypatch):
    import numpy as np
    monkeypatch.setattr(sf, 'fit_bkg', lambda *a: (np.array([1]), 0))
    monkeypatch.setattr(sf, 'bkg_binned', lambda *a: np.array([1]))
    monkeypatch.setattr(sf, 'cls_at_mu', lambda *a: 1 / (1 + a[-1]))
    result = sf.upper_limit(None, None, None, None, None, details=True)
    assert result['status'] == 'resolved' and result['bracket'][0] <= 19 <= result['bracket'][1]
    assert result['cls_endpoints'][0] >= .05 > result['cls_endpoints'][1]
    assert result['calibrated'] is False
    monkeypatch.setattr(sf, 'cls_at_mu', lambda *a: 1)
    result = sf.upper_limit(None, None, None, None, None, details=True)
    assert result['status'] == 'above_scan' and result['value'] == 2 ** 23
    monkeypatch.setattr(sf, 'cls_at_mu', lambda *a: float('nan'))
    with pytest.raises(RuntimeError, match='non-finite'):
        sf.upper_limit(None, None, None, None, None, details=True)


def test_approved_no_generation_comparison(tmp_path):
    contract, _, subject = fixture(tmp_path, mode='none')
    assert check(tmp_path, contract, subject=subject)['status'] == 'PASS'


def test_shape_writer_closes_only_with_approved_bound_comparisons(tmp_path):
    contract, _, subject = fixture(tmp_path, mode='none')
    kwargs = dict(spectrum_label='toy', n_bins=10, edge_lo=0, edge_hi=10, lumi_fb=1,
        bkg_form='dijet4', chi2=1, ndf=6, sig_label='reference template', sig_yield_mu1=10,
        mu95_obs=.5, mu95_exp=.6, mu95_exp_band=None, r5_points=[{'in_tolerance': True}] * 2,
        is_synthetic=False, png_path=None, pdf_path=None, timestamp='')
    unbound = sf.write_shape_fit_json(tmp_path / subject, **kwargs)
    assert unbound['r5_status'] == 'held'
    assert unbound['excluded_obs'] is None
    closed = sf.write_shape_fit_json(tmp_path / subject, **kwargs,
        certification_plan='inputs/r5-plan.json', rundir=tmp_path)
    assert closed['r5_status'] == 'closed', closed
    assert check(tmp_path, contract, subject=subject)['status'] == 'PASS'
    assert closed['limit_status']['observed'] == 'unverified'
    assert closed['excluded_obs'] is None  # Agreement cannot invent a numerically verified root.


def test_out_of_tolerance_recomputed_even_with_true_notes(tmp_path):
    contract, _, _ = fixture(tmp_path)
    obj = c.read_json(tmp_path / 'outputs/pred0.json')
    obj['validation_point']['value'] = 2
    obj['in_tolerance'] = True
    write(tmp_path, 'outputs/pred0.json', obj)
    result = c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/r5-certificate.json')
    assert result['verdict'] == 'FAIL'
    assert check(tmp_path, contract)['status'] == 'FAIL'


def test_boolean_measurement_and_unmatched_reference_fail(tmp_path):
    fixture(tmp_path)
    path = 'outputs/pred0.json'
    obj = c.read_json(tmp_path / path)
    obj['validation_point']['value'] = True
    write(tmp_path, path, obj)
    with pytest.raises(c.CertificateError, match='number'):
        c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/new-cert.json')
    obj['validation_point']['value'] = 1
    obj['validation_point']['node'] = 'nearest'
    write(tmp_path, path, obj)
    with pytest.raises(c.CertificateError, match='exact'):
        c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/new-cert.json')


def test_failed_optimizer_cannot_supply_a_finite_reported_limit(monkeypatch):
    import numpy as np
    from types import SimpleNamespace
    import scipy.optimize
    monkeypatch.setattr(scipy.optimize, 'minimize', lambda *a, **k:
        SimpleNamespace(success=False, fun=0, x=np.zeros(4)))
    with pytest.raises(RuntimeError, match='did not converge'):
        sf.fit_bkg(np.array([1.]), np.array([1., 2.]), 13000, 'dijet4')
    with pytest.raises(RuntimeError, match='did not converge'):
        sf.fit_mu_profiled(np.array([1.]), np.array([1., 2.]), 13000, 'dijet4', np.array([1.]),
                           p0=np.array([1., 1., 1., 1.]))


def test_numerical_types_do_not_alias_certificate_booleans(tmp_path):
    contract, _, _ = fixture(tmp_path)
    cert = c.read_json(tmp_path / 'outputs/r5-certificate.json')
    cert['comparisons'][0]['within_tolerance'] = 1
    write(tmp_path, 'outputs/r5-certificate.json', cert)
    assert check(tmp_path, contract)['status'] == 'FAIL'
    with pytest.raises(c.CertificateError, match='finite'):
        c.measurement(dict(point_id='x', parameters={'mass_gev': 10**500}, analysis_id='A',
            quantity='mu95_exp', units='dimensionless', basis={'normalization': 'x'}), 1, quantity='mu95_exp')


@pytest.mark.parametrize('kind', ['r5', 'acceptance'])
def test_pack_boundary_uses_same_approved_subject_bindings(tmp_path, kind):
    _, _, subject = fixture(tmp_path, kind=kind, mode='none')
    assert c.validate_pack_certificates(tmp_path, tmp_path / subject)[kind]['claim'] == 'central-value'
    write(tmp_path, subject, {'mu95_exp': .00001})
    with pytest.raises(c.CertificateError, match='changed artifact'):
        c.validate_pack_certificates(tmp_path, tmp_path / subject)


def test_acceptance_producer_normalizes_its_actual_report_values(tmp_path, monkeypatch):
    from ravel.validation import certify_acceptance as acceptance
    write(tmp_path, 'yields.json', {'SR_S_A': {'acceptance': .1, 'events': 100}})
    ctx = dict(point_id='SR_S_A-100', parameters={'mass_gev': 100}, analysis_id='A', quantity='acceptance',
               units='dimensionless', basis={'normalization': 'selected/generated'})
    write(tmp_path, 'context.json', {'SR_S_A': ctx})
    monkeypatch.setattr(acceptance, 'published_acceff', lambda *_a, **_kw: (.1, 'grid node (100,10)', False))
    monkeypatch.setattr(sys, 'argv', ['certify_acceptance', '--acceptance', str(tmp_path / 'yields.json'),
        '--tables-dir', str(tmp_path), '--grid', 'slepton', '--m-parent', '100', '--dm', '10',
        '--srs', 'SR_S_A', '--out', str(tmp_path / 'cert.md'),
        '--certification-context', str(tmp_path / 'context.json')])
    acceptance.main()
    report = c.read_json(tmp_path / 'cert.json')
    assert report['validation_points'][0]['value'] == report['rows'][0]['mine'] == .1
    assert report['validation_points'][0]['node'] == 'exact'


def test_normalized_shape_point_cannot_disagree_with_primary_value(tmp_path):
    _, _, _ = fixture(tmp_path)
    path = 'outputs/pred0.json'
    obj = c.read_json(tmp_path / path)
    obj.update(generator='shape_fit.py', mu95_exp=100,
               certification_producer={'module': 'ravel.physics.shape_fit', 'sha256': c.digest(sf.__file__)})
    write(tmp_path, path, obj)
    with pytest.raises(c.CertificateError, match='primary fitted limit'):
        c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/new.json')
    obj['mu95_exp'] = obj['validation_point']['value']
    obj['certification_producer']['sha256'] = '0' * 64
    write(tmp_path, path, obj)
    with pytest.raises(c.CertificateError, match='implementation changed'):
        c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/new.json')


def test_normalized_acceptance_point_cannot_disagree_with_primary_row(tmp_path):
    from ravel.validation import certify_acceptance as acceptance
    _, plan, _ = fixture(tmp_path, kind='acceptance')
    path = 'outputs/pred0.json'
    point = c.read_json(tmp_path / path)['validation_point']
    point['role'] = 'SR1'
    obj = {'validation_points': [point], 'rows': [{'sr': 'SR1', 'mine': 100, 'node': 'grid node (100,0)'}],
           'certification_producer': {'module': 'ravel.validation.certify_acceptance', 'sha256': c.digest(acceptance.__file__)}}
    write(tmp_path, path, obj)
    plan['comparisons'][0]['prediction']['record_pointer'] = '/validation_points/0'
    write(tmp_path, 'inputs/acceptance-plan.json', plan)
    with pytest.raises(c.CertificateError, match='computed SR row'):
        c.create_certificate(tmp_path, 'inputs/acceptance-plan.json', 'outputs/new.json')
    obj['rows'][0]['mine'] = point['value']
    write(tmp_path, path, obj)
    assert c.create_certificate(tmp_path, 'inputs/acceptance-plan.json', 'outputs/new.json')['verdict'] == 'PASS'


@pytest.mark.parametrize('scenario', ['missing-generator', 'wrong-module', 'typed-conflict'])
def test_known_shape_producer_discriminator_and_typed_value_agree(tmp_path, scenario):
    from ravel.validation import certify_acceptance as acceptance
    from ravel.limits import LimitCurve, LimitResult
    fixture(tmp_path)
    obj = c.read_json(tmp_path / 'outputs/pred0.json')
    obj.update(generator='shape_fit.py', mu95_exp=obj['validation_point']['value'],
               certification_producer={'module': 'ravel.physics.shape_fit', 'sha256': c.digest(sf.__file__)})
    if scenario == 'missing-generator':
        del obj['generator']
        obj['mu95_exp'] = 100
    elif scenario == 'wrong-module':
        obj['certification_producer'] = {'module': 'ravel.validation.certify_acceptance', 'sha256': c.digest(acceptance.__file__)}
    else:
        absent = LimitCurve(None, 'missing')
        obj['limits'] = LimitResult(absent, (absent, absent, LimitCurve(100., 'resolved', (99.,101.)), absent, absent)).to_dict()
    write(tmp_path, 'outputs/pred0.json', obj)
    with pytest.raises(c.CertificateError):
        c.create_certificate(tmp_path, 'inputs/r5-plan.json', 'outputs/new.json')


def test_known_acceptance_producer_cannot_omit_primary_rows(tmp_path):
    from ravel.validation import certify_acceptance as acceptance
    fixture(tmp_path, kind='acceptance')
    obj = c.read_json(tmp_path / 'outputs/pred0.json')
    obj['certification_producer'] = {'module': 'ravel.validation.certify_acceptance', 'sha256': c.digest(acceptance.__file__)}
    write(tmp_path, 'outputs/pred0.json', obj)
    with pytest.raises(c.CertificateError, match='rows'):
        c.create_certificate(tmp_path, 'inputs/acceptance-plan.json', 'outputs/new.json')
