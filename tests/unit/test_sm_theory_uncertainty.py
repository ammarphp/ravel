"""Synthetic member arithmetic and inert external-library boundary controls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def api():
    from ravel.physics.sm import theory_uncertainty
    return theory_uncertainty


def bundle():
    return {
        'schema_version': 1, 'kind': 'prediction-bundle',
        'program': {'name': 'synthetic-program', 'version': '1', 'receipt': 'supplied.json'},
        'order': {'qcd': 'NLO', 'ew': 'LO', 'resummation': 'none', 'matching': 'none'},
        'inputs': {'pdf': {'set': 'SYNTHETIC_SET', 'lhaid': 0, 'error_type': 'replicas'},
                   'alpha_s_mz': .118, 'ew_scheme': 'Gmu', 'masses': {},
                   'scales': {'muR': 'supplied', 'muF': 'supplied'}},
        'binning': [{'lo': 0, 'hi': 1}, {'lo': 1, 'hi': 3}], 'level': 'parton',
        'normalization': 'absolute', 'central': [10, 20], 'members': [], 'prescriptions': {},
    }


def scale_bundle():
    b = bundle()
    # Opposite pairs carry the outliers, independently of member ordering.
    for i, (r, f, v) in enumerate([
        (.5, .5, [8, 18]), (.5, 1, [9, 17]), (.5, 2, [-40, 90]),
        (1, .5, [11, 22]), (1, 1, [10, 20]), (1, 2, [12, 21]),
        (2, .5, [80, -30]), (2, 1, [13, 24]), (2, 2, [11, 23]),
    ]):
        b['members'].append({'class': 'scale', 'id': str(i), 'mu_r': r, 'mu_f': f, 'values': v})
    b['prescriptions']['scale'] = '7pt-envelope'
    return b


def pdf_bundle(kind, values):
    b = bundle()
    text = f'ErrorType: {kind}\nNumMembers: {len(values)}\nErrorConfLevel: 90\nAlphaS_MZ: 0.118\n'
    b['inputs']['pdf'].update(error_type=kind, info=api().read_pdf_info(text))
    b['members'] = [{'class': 'pdf', 'id': str(i), 'pdf_member': i, 'values': row}
                    for i, row in enumerate(values)]
    b['prescriptions']['pdf'] = {'method': 'lhapdf-error-type', 'error_type': kind,
                                  'confidence_level_percent': 68.268949}
    return b


def test_replica_info_refuses_hessian_formula_first():
    b = pdf_bundle('replicas', [[10, 20], [9, 18], [11, 22]])
    b['prescriptions']['pdf']['error_type'] = 'hessian'
    with pytest.raises(ValueError, match='ErrorType'):
        api().pdf_worker_request(b)


def test_missing_scale_corner_refuses_incomplete_envelope():
    b = scale_bundle(); b['members'].pop()
    with pytest.raises(ValueError, match='scale population'):
        api().band(b)


def test_missing_correlation_model_refuses():
    with pytest.raises(ValueError, match='correlation'):
        api().theory_covariance(scale_bundle(), {})


def test_different_order_normalization_requires_declaration():
    b = bundle(); b['normalization_order'] = 'NNLO'
    with pytest.raises(ValueError, match='normalization declaration'):
        api().band(b)


def test_np_double_application_refuses():
    b = bundle(); b['np_already_applied'] = True
    b['members'] = [{'class': 'np', 'id': 'a', 'quantity': 'ratio', 'values': [1.1, .9]}]
    b['prescriptions']['np'] = 'ratio-envelope'
    with pytest.raises(ValueError, match='already applied'):
        api().band(b)


def test_ew_multiplicative_requires_additive_comparison():
    b = bundle(); b['prescriptions']['ew'] = 'multiplicative'
    b['members'] = [{'class': 'ew', 'id': 'a', 'role': 'multiplicative', 'values': [11, 22]}]
    with pytest.raises(ValueError, match='additive comparison'):
        api().band(b)


def test_stale_worker_output_refuses():
    b = pdf_bundle('replicas', [[10, 20], [9, 18], [11, 22]])
    with pytest.raises(ValueError, match='worker request'):
        api().band(b, pdf_result={'request_sha256': '0' * 64})


def test_unknown_generator_stream_is_retained_and_incomplete():
    b = bundle()
    out = api().from_member_table(b, 'mg5-lo', [
        {'id': 'mystery', 'values': [7, 8]},
        {'id': 'MUR0.5_MUF1', 'values': [9, 19]},
    ])
    assert out['unclassified'] == ['mystery'] and out['complete'] is False
    assert out['members'][0]['class'] == 'unclassified'
    assert out['members'][0]['values'] == [7, 8]


def test_scale_seven_point_excludes_opposites_and_equals_hand_envelope():
    b = scale_bundle()
    result = api().band(b)
    assert result['minus'] == [2, 3] and result['plus'] == [3, 4]
    assert result['by_class']['scale']['selected_member_ids'] == ['0', '1', '3', '4', '5', '7', '8']
    b['prescriptions']['scale'] = '9pt-envelope'
    assert api().band(b)['minus'] == [50, 50]
    assert api().band(b)['plus'] == [70, 70]
    b['prescriptions']['scale'] = 'independent-muR-muF'
    assert api().band(b)['minus'] == pytest.approx([1, 3])
    assert api().band(b)['plus'] == pytest.approx([np.sqrt(13), np.sqrt(20)])


def test_alpha_s_mismatch_is_named_and_incomplete():
    b = bundle(); b['inputs']['pdf']['alpha_s_mz'] = .120
    out = api().assemble(b, correlation_model={})
    assert out['checks']['check:sm.alphas_consistent']['status'] == 'failed'
    assert out['complete'] is False


def test_fully_correlated_rank_one_and_uncorrelated_diagonal():
    b = scale_bundle()
    full = api().theory_covariance(b, {'scale': 'fully-correlated'})
    assert np.linalg.matrix_rank(full['by_class']['scale']) == 1
    assert full['correlation_model'] == {'scale': 'fully-correlated'}
    diagonal = api().theory_covariance(b, {'scale': 'uncorrelated'})
    assert diagonal['by_class']['scale'] == [[9, 0], [0, 16]]


def test_ew_difference_equals_absolute_mult_minus_add():
    b = bundle(); b['prescriptions']['ew'] = 'difference-as-uncertainty'
    b['members'] = [
        {'class': 'ew', 'id': 'mult', 'role': 'multiplicative', 'values': [12, 18]},
        {'class': 'ew', 'id': 'add', 'role': 'additive', 'values': [11, 21]},
    ]
    result = api().band(b)
    assert result['minus'] == [1, 3] and result['plus'] == [1, 3]


@pytest.mark.parametrize('kind,values,error', [
    ('hessian', [[10, 20], [12, 24], [8, 16]], [2, 4]),
    ('symmhessian', [[10, 20], [12, 24], [11, 22]], [np.sqrt(5), np.sqrt(20)]),
    ('replicas', [[10, 20], [9, 18], [10, 20], [11, 22]], [1, 2]),
])
def test_fake_lhapdf_band_parity(kind, values, error):
    b = pdf_bundle(kind, values); request = api().pdf_worker_request(b)
    from ravel.physics.sm import lhapdf_worker
    calls = []
    class FakeSet:
        errorType = kind
        size = len(values)
        errorConfLevel = 90
        def uncertainty(self, vals, cl):
            calls.append((vals, cl))
            i = len(calls) - 1
            return SimpleNamespace(central=values[0][i], errminus=float(error[i]), errplus=float(error[i]), errsymm=float(error[i]), scale=1)
    fake = SimpleNamespace(getPDFSet=lambda name: FakeSet(), version=lambda: 'synthetic')
    result = lhapdf_worker.evaluate(request, fake)
    out = api().band(b, pdf_result=result)
    assert out['minus'] == pytest.approx(error, abs=1e-9)
    assert out['plus'] == pytest.approx(error, abs=1e-9)
    assert [call[1] for call in calls] == [68.268949] * 2
    assert result['info_sha256'] == b['inputs']['pdf']['info']['sha256']


def test_mixed_scale_pdf_header_is_unclassified():
    b = bundle(); b['inputs']['pdf']['lhaid'] = 123
    headers = [{'id': '5', 'attributes': {'id': '5', 'MUR': '2', 'MUF': '1', 'PDF': '124'},
                'description': 'synthetic mixed variation', 'canonical_header_xml': '<weight/>'}]
    out = api().from_member_table(b, 'mg5-lo', [{'id': '5', 'values': [12, 25]}], headers=headers)
    assert out['unclassified'] == ['5']


def test_fractional_pdf_identifier_refuses():
    with pytest.raises(ValueError, match='integer'):
        api().classify_weight('PDF_MEMBER1.5', 'mg5-lo', header={
            'id': 'PDF_MEMBER1.5', 'attributes': {'id': 'PDF_MEMBER1.5', 'PDF': '1.5'}})


def test_invalid_supplied_covariance_refuses():
    b = bundle(); b['theory_covariance'] = {'by_class': {}, 'total': [[1]],
        'correlation_model': {}, 'symmetrization': 'max', 'class_correlation': 'independent',
        'law': 'declared-second-moment-proxy'}
    with pytest.raises(ValueError, match='covariance'):
        api().validate_bundle(b)


def test_negative_np_ratios_refuse():
    b = bundle(); b['np_already_applied'] = False
    b['prescriptions']['np'] = 'ratio-envelope'
    b['members'] = [{'class': 'np', 'id': 'np-a', 'quantity': 'ratio', 'values': [-1, 1]}]
    with pytest.raises(ValueError, match='positive NP ratios'):
        api().band(b)


def test_worker_must_reject_changed_error_type():
    b = pdf_bundle('replicas', [[10, 20], [9, 18], [11, 22]])
    from ravel.physics.sm import lhapdf_worker
    fake = SimpleNamespace(getPDFSet=lambda _: SimpleNamespace(errorType='hessian', size=3))
    with pytest.raises(ValueError, match='ErrorType'):
        lhapdf_worker.evaluate(api().pdf_worker_request(b), fake)


@pytest.mark.parametrize('model', [
    {'kind': 'matrix', 'values': [[1, 2], [2, 1]]},
    {'kind': 'matrix', 'values': [[1, .2], [.1, 1]]},
    {'kind': 'matrix', 'values': [[1]]},
])
def test_nonphysical_correlation_matrix_refuses(model):
    with pytest.raises(ValueError, match='correlation matrix'):
        api().theory_covariance(scale_bundle(), {'scale': model})


def test_yoda_selected_nominal_all_streams_and_density():
    from ravel.physics import yoda_text
    b = bundle()
    def hist(path, vals):
        return f'BEGIN YODA_HISTO1D_V3 {path}\nType: Histo1D\n---\nEdges(A1): [0, 1, 3]\n0 0 0\n{vals[0]} 1 1\n{vals[1]} 1 1\n0 0 0\nEND YODA_HISTO1D_V3\n'
    text = hist('/ANA-0001/h', [10, 40]) + hist('/ANA-0001/h[MUR0.5_MUF1]', [9, 36]) + hist('/ANA-0001/h[alien]', [7, 30])
    out = api().from_yoda(b, text, observable_path='/ANA-0001/h', generator='mg5-lo',
                          nominal_weight='selected', quantity='density', factor=2)
    assert out['central'] == [20, 40] and len(out['members']) == 2
    assert out['members'][0]['values'] == [18, 36]
    assert out['unclassified'] == ['alien'] and out['source']['common_factor'] == 2
    assert set(yoda_text.parse(text)) == {'/ANA-0001/h', '/ANA-0001/h[MUR0.5_MUF1]', '/ANA-0001/h[alien]'}


@pytest.mark.parametrize('generator,name,kind', [
    ('mg5-lo', 'MUR0.5_MUF1_DYN_SCALE-1', 'scale'),
    ('mg5-nlo', 'muR=2 muF=1', 'scale'),
    ('sherpa3', 'MUR2_MUF0.5', 'scale'),
    ('herwig7', 'MuR1_MuF2', 'scale'),
    ('powheg', 'renscfact=2 facscfact=1', 'scale'),
    ('pythia8-shower', 'isr:muRfac=2.0', 'shower'),
])
def test_named_generator_map_grammars(generator, name, kind):
    assert api().classify_weight(name, generator)['class'] == kind


def test_alpha_s_delta_and_np_ratio_prescriptions():
    b = bundle()
    b['members'] = [
        {'class': 'alphas', 'id': 'low', 'alpha_s_mz': .117, 'pdf_alpha_s_mz': .117, 'values': [9, 18]},
        {'class': 'alphas', 'id': 'high', 'alpha_s_mz': .119, 'pdf_alpha_s_mz': .119, 'values': [11, 22]},
    ]
    b['prescriptions']['alphas'] = {'method': 'plus-minus-delta', 'delta': .001}
    assert api().band(b)['plus'] == [1, 2]
    b['members'] = [{'class': 'np', 'id': 'low', 'quantity': 'ratio', 'values': [.9, 1.1]},
                    {'class': 'np', 'id': 'high', 'quantity': 'ratio', 'values': [1.2, .8]}]
    b['prescriptions'] = {'np': 'ratio-envelope'}; b['np_already_applied'] = False
    assert api().band(b)['minus'] == pytest.approx([1, 4])
    assert api().band(b)['plus'] == pytest.approx([2, 2])


def test_adapter_supplied_output_and_no_launch(tmp_path):
    b = scale_bundle(); b['inputs']['pdf']['alpha_s_mz'] = .118
    source = tmp_path / 'input.json'
    source.write_text(json.dumps({'bundle': b, 'correlation_model': {'scale': 'uncorrelated'}}))
    task = {'input': source.name, 'output': {'filename': 'caller-name.json', 'format': 'json-compact'}}
    api().validate(task)
    assert api().inputs(task, tmp_path) == [source]
    result = api().run(task, tmp_path, tmp_path)
    assert result['status'] == 'passed' and result['physics_validated'] is False
    delivered = json.loads((tmp_path / 'caller-name.json').read_text())
    assert delivered['complete'] and delivered['theory_covariance']['correlation_model'] == {'scale': 'uncorrelated'}


def test_unknown_header_attribute_cannot_disappear():
    with pytest.raises(ValueError, match='header contract'):
        api().classify_weight('a', 'mg5-lo', header={
            'id': 'a', 'attributes': {'id': 'a', 'MUR': '1', 'MUF': '2', 'secret_axis': '7'}})


def test_yoda_metadata_must_cover_every_named_pdf_member():
    b = pdf_bundle('replicas', [[10, 20], [9, 18], [11, 22]])
    b['members'] = []
    text = ''
    from ravel.physics import yoda_text
    for path, values in [('/ANA-0002/h', [10, 20]), ('/ANA-0002/h[PDF_MEMBER1]', [9, 18]), ('/ANA-0002/h[PDF_MEMBER2]', [11, 22])]:
        text += yoda_text.write_estimate1d(path, [0, 1, 3], [(v, {}) for v in values])
    out = api().from_yoda(b, text, observable_path='/ANA-0002/h', generator='mg5-lo',
                          nominal_weight='nominal', quantity='estimate', nominal_pdf_member=0)
    assert api().pdf_worker_request(out)['member_values'] == [[10, 20], [9, 18], [11, 22]]


def test_adapter_accepts_supplied_member_table(tmp_path):
    b = scale_bundle()
    streams = [{'id': f'MUR{m["mu_r"]}_MUF{m["mu_f"]}', 'values': m['values']} for m in b.pop('members')]
    b['members'] = []; b['inputs']['pdf']['alpha_s_mz'] = .118
    source = tmp_path / 'table.json'
    source.write_text(json.dumps({'bundle': b, 'correlation_model': {'scale': 'fully-correlated'},
                                 'member_table': {'generator': 'mg5-lo', 'streams': streams}}))
    task = {'input': source.name, 'output': {'filename': 'table-output.json', 'format': 'json'}}
    out = api().run(task, tmp_path, tmp_path)
    assert out['status'] == 'passed'


def test_adapter_pins_and_reads_supplied_yoda(tmp_path):
    from ravel.physics import yoda_text
    b = scale_bundle(); b['inputs']['pdf']['alpha_s_mz'] = .118
    text = yoda_text.write_estimate1d('/ANA-0003/h', [0, 1, 3], [(v, {}) for v in b['central']])
    for m in b['members']:
        text += yoda_text.write_estimate1d(f'/ANA-0003/h[MUR{m["mu_r"]}_MUF{m["mu_f"]}]', [0, 1, 3], [(v, {}) for v in m['values']])
    b['members'] = []
    yoda = tmp_path / 'member.yoda'; yoda.write_text(text)
    source = tmp_path / 'yoda-input.json'
    source.write_text(json.dumps({'bundle': b, 'correlation_model': {'scale': 'uncorrelated'},
        'yoda': {'input': {'path': yoda.name, 'sha256': hashlib.sha256(yoda.read_bytes()).hexdigest()},
                 'observable_path': '/ANA-0003/h', 'generator': 'mg5-lo', 'nominal_weight': 'selected', 'quantity': 'estimate'}}))
    task = {'input': source.name, 'output': {'filename': 'yoda-output.json', 'format': 'json'}}
    assert api().inputs(task, tmp_path) == [source, yoda]
    assert api().run(task, tmp_path, tmp_path)['status'] == 'passed'
    yoda.write_text(text + '# changed bytes\n')
    with pytest.raises(ValueError, match='source pin differs'):
        api().inputs(task, tmp_path)


def test_worker_installed_info_bytes_and_confidence_rescale(tmp_path):
    b = pdf_bundle('hessian', [[10, 20], [12, 24], [8, 16]])
    request = api().pdf_worker_request(b)
    from ravel.physics.sm import lhapdf_worker
    directory = tmp_path / 'SYNTHETIC_SET'; directory.mkdir()
    info = directory / 'SYNTHETIC_SET.info'; info.write_text(request['info']['text'])
    fake = SimpleNamespace(paths=lambda: [str(tmp_path)])
    assert lhapdf_worker.verify_installed_info(request, fake) == info
    info.write_text(info.read_text().replace('hessian', 'replicas'))
    with pytest.raises(ValueError, match='differs'):
        lhapdf_worker.verify_installed_info(request, fake)


def test_composite_pdf_requires_declared_components_and_no_double_count():
    b = pdf_bundle('symmhessian+as', [[10, 20], [12, 24], [11, 22], [9, 19], [11, 21]])
    with pytest.raises(ValueError, match='composite components'):
        api().pdf_worker_request(b)
    b['prescriptions']['pdf']['components'] = ['pdf', 'alphas']
    request = api().pdf_worker_request(b)
    assert request['info']['error_type'] == 'symmhessian+as'
    b['members'] += [
        {'class': 'alphas', 'id': 'low', 'alpha_s_mz': .117, 'pdf_alpha_s_mz': .117, 'values': [9, 18]},
        {'class': 'alphas', 'id': 'high', 'alpha_s_mz': .119, 'pdf_alpha_s_mz': .119, 'values': [11, 22]},
    ]
    b['prescriptions']['alphas'] = 'pdf-set-members'
    with pytest.raises(ValueError, match='double counting'):
        api().pdf_worker_request(b)


def test_pdf_info_coupling_cannot_be_masked_by_descriptor():
    b = bundle()
    b['inputs']['pdf']['info'] = api().read_pdf_info('ErrorType: replicas\nNumMembers: 3\nAlphaS_MZ: 0.120\n')
    b['inputs']['pdf']['alpha_s_mz'] = .118
    out = api().assemble(b, correlation_model={})
    assert out['checks']['check:sm.alphas_consistent']['status'] == 'failed'
    assert out['checks']['check:sm.alphas_consistent']['pdf_alpha_s_mz'] == .120
    assert out['complete'] is False


def test_malformed_supplied_structures_refuse_as_value_errors():
    b = bundle()
    b['band'] = {'minus': [0, 0], 'plus': [0, 0], 'by_class': {'scale': {}},
                 'combination': 'independent-classes-quadrature', 'unclassified': []}
    with pytest.raises(ValueError, match='prediction bundle'):
        api().validate_bundle(b)
    with pytest.raises(ValueError, match='prediction bundle'):
        api().from_member_table({}, 'mg5-lo', [])


@pytest.mark.parametrize('row', [{}, 5, {'central': 10, 'minus': 1, 'plus': 1}])
def test_malformed_worker_bins_refuse(row):
    values = [[10, 20], [9, 18], [11, 22]]
    b = pdf_bundle('replicas', values)
    from ravel.physics.sm import lhapdf_worker
    class FakeSet:
        errorType = 'replicas'
        size = len(values)
        errorConfLevel = 90
        def uncertainty(self, vals, cl):
            return SimpleNamespace(central=vals[0], errminus=1.0, errplus=1.0, errsymm=1.0, scale=1)
    fake = SimpleNamespace(getPDFSet=lambda name: FakeSet(), version=lambda: 'synthetic')
    result = lhapdf_worker.evaluate(api().pdf_worker_request(b), fake)
    assert api().band(b, pdf_result=result)['plus'] == [1, 1]
    result['bins'][0] = row
    with pytest.raises(ValueError, match='PDF worker bins'):
        api().band(b, pdf_result=result)
