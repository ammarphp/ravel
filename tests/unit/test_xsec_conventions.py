"""Supplied production conventions never select an installed study denominator."""
from pathlib import Path
import pytest
from ravel.physics import cross_sections as xs, nlo_xsec
from ravel.workflow import scan_orchestrator


def test_local_calculation_denominators_are_not_product_defaults():
    root = Path(xs.__file__).parents[1] / 'data' / 'cross_sections'
    assert not list(root.glob('*_lo_cteq6l1.json'))
    with pytest.raises(ValueError) as error:
        nlo_xsec.load_lo_ref('ANA-0001')
    assert getattr(error.value, 'reason_code', None) == 'missing_cross_section_input'


def test_legacy_process_lookup_requires_a_supplied_convention():
    assert not hasattr(nlo_xsec, 'FILES')
    with pytest.raises(ValueError) as error:
        nlo_xsec.slepton_k(123)
    assert getattr(error.value, 'reason_code', None) == 'missing_cross_section_input'


def test_rebase_requires_a_supplied_transformation_before_io(tmp_path):
    from types import SimpleNamespace
    with pytest.raises(ValueError) as error:
        scan_orchestrator.cmd_rebase(SimpleNamespace(scandir=str(tmp_path), process='ANA-0002',
                                                     scan=None, out=None))
    assert getattr(error.value, 'reason_code', None) == 'missing_production_transformation'

import copy
import hashlib
import json


def table(tmp_path, name, data, *, basis='state-A', count=1, parameters=('mass',), order='LO',
          interpolation='exact'):
    path = tmp_path / (name + '.json')
    path.write_text(json.dumps({'data': data}))
    return {'schema_version': 1, 'basis': basis, 'sqrt_s_GeV': 12000,
            'masses': {}, 'state_count': count, 'charge': None,
            'convention': {'order': order, 'pdf': 'fictional-pdf', 'scale': 'declared mass'},
            'table': {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'parameters': list(parameters), 'interpolation': interpolation,
                      'provenance': {'kind': 'supplied-calculation', 'reference': 'fictional source',
                                     'justification': 'Synthetic input for algebra controls.'}}}


def request(source, **parameters):
    result = copy.deepcopy(source)
    result['masses'] = parameters
    return result


def test_selected_table_bytes_and_interpolation_are_required(tmp_path):
    source = table(tmp_path, 'rates', {'100': {'xsec_pb': 4}, '200': {'xsec_pb': 1}})
    assert xs.lookup(request(source, mass=100))['sigma_pb'] == 4
    with pytest.raises(ValueError, match='exact'):
        xs.lookup(request(source, mass=150))
    missing = request(source, mass=100)
    del missing['table']['interpolation']
    with pytest.raises(ValueError) as error:
        xs.lookup(missing)
    assert error.value.reason_code == 'missing_cross_section_input'
    Path(source['table']['path']).write_text('{"data": {}}')
    with pytest.raises(ValueError, match='sha256'):
        xs.lookup(request(source, mass=100))


def test_ratio_interpolation_is_selected_and_never_extrapolates(tmp_path):
    numerator = table(tmp_path, 'num', {'100': {'xsec_pb': 6}, '200': {'xsec_pb': 2}},
                      order='NLO', interpolation='loglog')
    denominator = table(tmp_path, 'den', {'100': {'xsec_pb': 4}, '150': {'xsec_pb': 2},
                                         '200': {'xsec_pb': 1}}, interpolation='loglog')
    contract = {'numerator': request(numerator, mass=150), 'denominator': request(denominator, mass=150),
                'interpolation': 'ratio-linear', 'justification': 'Interpolate a supplied smooth ratio.'}
    result = nlo_xsec.correction(contract)
    assert result['k_factor'] == pytest.approx(1.75)
    assert result['numerator']['sigma_pb'] == pytest.approx(3.5)
    changed = copy.deepcopy(contract)
    changed['denominator']['state_count'] = 2
    with pytest.raises(ValueError, match='like-for-like'):
        nlo_xsec.correction(changed)
    changed = copy.deepcopy(contract)
    for key in ('numerator', 'denominator'):
        changed[key]['masses']['mass'] = 50
    with pytest.raises(ValueError, match='extrapolation'):
        nlo_xsec.correction(changed)


def batch(tmp_path, identity, axes, coordinates, datasets, fmt):
    # Different named dimensions and populations use the same table loader.
    def nested(points):
        data = {}
        for position, values in enumerate(points):
            current = data
            for value in values[:-1]:
                current = current.setdefault(str(value), {})
            current[str(values[-1])] = {'xsec_pb': position + 1}
        return data
    source = table(tmp_path, identity, nested(coordinates), parameters=axes)
    return {'schema_version': 1, 'kind': 'cross-section-batch', 'study_id': identity,
            'datasets': datasets, 'output_format': fmt,
            'points': [{'tag': str(i), 'request': request(source, **dict(zip(axes, values)))}
                       for i, values in enumerate(coordinates)]}


def test_two_lookup_contracts_change_identity_dimensions_population_and_format(tmp_path):
    contracts = [batch(tmp_path, 'ANA-0001', ('mass',), [(100,), (200,)], ['DATA-0001'], 'json'),
                 batch(tmp_path, 'ANA-0002', ('mass_u', 'mass_v'), [(80, 20), (80, 40), (160, 40)],
                       ['DATA-0002', 'DATA-0003'], 'jsonl')]
    for contract in contracts:
        path = tmp_path / (contract['study_id'] + '-request.json')
        out = tmp_path / (contract['study_id'] + '-result')
        path.write_text(json.dumps(contract))
        assert xs.main(['supplied', '--request', str(path), '--out', str(out)]) == 0
        if contract['output_format'] == 'json':
            result = json.loads(out.read_text())
            assert result['study_id'] == contract['study_id'] and result['datasets'] == contract['datasets']
            records = result['points']
        else:
            records = [json.loads(line) for line in out.read_text().splitlines()]
            assert all(r['study_id'] == contract['study_id'] and r['datasets'] == contract['datasets'] for r in records)
        assert [r['cross_section']['sigma_pb'] for r in records] == list(range(1, len(records) + 1))
        assert [r['cross_section']['masses'] for r in records] == [p['request']['masses'] for p in contract['points']]
    bad = copy.deepcopy(contracts[1])
    del bad['points'][0]['request']['table']
    with pytest.raises(ValueError) as error:
        xs.lookup(bad)
    assert error.value.reason_code == 'missing_cross_section_input'


def row(tag, sigma=10, parameters=None):
    return {**({"parameters": parameters} if parameters is not None else {}),'tag': tag, 'mu95_obs': .8, 'mu95_exp': 1.2,
            'mu95_exp_band': [.4, .7, 1.2, 2, 3], 'sigma_ref_fb': sigma,
            'limit_status': {'observed': 'resolved', 'expected': ['resolved'] * 4 + ['above_scan']},
            'limit_brackets': {'observed': [.79, .81],
                               'expected': [[.39,.41],[.69,.71],[1.19,1.21],[1.99,2.01],[3,None]]}}


def transformation(tmp_path, identity, axes, coordinates, datasets, fmt):
    contract = batch(tmp_path, identity, axes, coordinates, datasets, fmt)
    contract['kind'] = 'production-transformation'
    for p in contract['points']:
        source = p.pop('request')
        source['basis'] = 'source-total'
        p['parameters'] = source['masses']
        p['source'] = source
        target = copy.deepcopy(source)
        target['basis'] = 'target-total'
        # Select arbitrary target tables instead of implicit multiplicities.
        data = json.loads(Path(source['table']['path']).read_text())['data']
        def scale(d):
            for key,value in d.items():
                if 'xsec_pb' in value: value['xsec_pb'] *= 2
                else: scale(value)
        scale(data)
        target_source = table(tmp_path, identity+'-target', data, basis='target-total',
                              parameters=axes, order='NLO')
        p['target'] = request(target_source, **p['parameters'])
        p['components'] = [{'id': 'part-A', 'source_states': ['state-A'], 'target_states': ['state-B'],
                            'source_yield_fraction': 1, 'response_ratio': .5,
                            'justification': 'Supplied acceptance ratio from fictional source.'}]
        p['shape_justification'] = 'Assume the accepted shapes remain identical under this mapping.'
    return contract


def test_two_rebases_change_contract_population_and_format_and_refuse_missing(tmp_path):
    contracts = [transformation(tmp_path, 'ANA-0003', ('mass',), [(100,), (200,)], ['DATA-0004'], 'json'),
                 transformation(tmp_path, 'ANA-0004', ('u','v'), [(80,20),(80,40),(160,40)],
                                ['DATA-0005','DATA-0006'], 'jsonl')]
    for contract in contracts:
        rows = [row(p['tag'], (i+1)*1000, p['parameters']) for i,p in enumerate(contract['points'])]
        result = scan_orchestrator.apply_production_transformation(rows, contract, tmp_path)
        assert result['study_id'] == contract['study_id'] and result['datasets'] == contract['datasets']
        assert [r['mu95_obs'] for r in rows] == [.8] * len(rows)
        assert [r['sigma_ref_fb'] for r in rows] == [(i+1)*2000 for i in range(len(rows))]
        assert [r['production_transformation']['parameters'] for r in rows] == [p['parameters'] for p in contract['points']]
        missing = copy.deepcopy(contract)
        del missing['points'][-1]['components']
        fresh = [row(p['tag'], (i+1)*1000, p['parameters']) for i,p in enumerate(contract['points'])]
        original = copy.deepcopy(fresh)
        with pytest.raises(ValueError) as error:
            scan_orchestrator.apply_production_transformation(fresh, missing, tmp_path)
        assert error.value.reason_code == 'missing_production_transformation' and fresh == original


def test_migration_identity_preserves_limits_and_explicit_dropped_component(tmp_path):
    contract = transformation(tmp_path, 'ANA-0005', ('mass',), [(100,)], ['DATA-0007'], 'json')
    p = contract['points'][0]
    # Synthetic algebra for a tagged sample rebased to a different inclusive model.
    p['source']['state_count'] = 3
    p['target']['state_count'] = 2
    p['components'] = [
        {'id':'included', 'source_states':['a','b'], 'target_states':['d','e'],
         'source_yield_fraction':1, 'response_ratio':1/1.7, 'justification':'Supplied tagging acceptance.'},
        {'id':'omitted', 'source_states':['c'], 'target_states':[], 'source_yield_fraction':0,
         'response_ratio':0, 'justification':'Declared zero accepted contribution, verified externally.'}]
    rows = [row('0', 1000, {'mass':100})]
    old = copy.deepcopy(rows[0])
    from ravel.limits import read_limits
    scan_orchestrator.apply_production_transformation(rows, contract, tmp_path)
    factor = 1.7 / 2  # previous algebra, with every input synthetic and explicitly supplied
    assert rows[0]['mu95_obs'] == pytest.approx(old['mu95_obs'] * factor, rel=1e-14)
    assert rows[0]['mu95_exp_band'] == pytest.approx([v*factor for v in old['mu95_exp_band']])
    assert rows[0]['sigma_ref_fb'] == 2000
    assert read_limits(rows[0]).expected[-1].status == 'above_scan'
    assert rows[0]['limit_brackets']['expected'][-1] == [3*factor, None]
    assert rows[0]['production_transformation']['components'] == p['components']
    saved = copy.deepcopy(rows)
    with pytest.raises(ValueError, match='already'):
        scan_orchestrator.apply_production_transformation(rows, contract, tmp_path)
    assert rows == saved


def test_two_renormalizations_preserve_sigma_limits_and_require_correction(tmp_path, monkeypatch):
    cases = [('ANA-0006', ('mass',), [(100,), (200,)], ['DATA-0008'], 'json'),
             ('ANA-0007', ('u','v'), [(80,20),(80,40),(160,40)], ['DATA-0009','DATA-0010'], 'jsonl')]
    monkeypatch.setattr(scan_orchestrator, 'point_kfactor', lambda p: p['flat'])
    for case in cases:
        contract = transformation(tmp_path,*case)
        contract['kind'] = 'cross-section-renormalization'
        manifest = {'points':[]}
        rows = []
        for i,p in enumerate(contract['points']):
            flat = 1.1 + i*.03  # independent source factors, without a uniformity default
            denominator = p.pop('source')
            numerator = p.pop('target')
            numerator['basis'] = denominator['basis']
            p['correction'] = {'numerator':numerator,'denominator':denominator,
                               'interpolation':'ratio-of-lookups','justification':'Supplied normalization ratio.'}
            p['replaced_kfactor'] = flat
            p['application_justification'] = 'Apply this same-state correction to the supplied sample.'
            manifest['points'].append({'tag':p['tag'],'flat':flat})
            rows.append(row(p['tag'],(i+1)*1000*flat,p['parameters']))
        original = copy.deepcopy(rows)
        result = scan_orchestrator.apply_nlo_renorm(rows,contract,manifest)
        assert result['study_id'] == contract['study_id'] and result['datasets'] == contract['datasets']
        for before,after,p in zip(original,rows,contract['points']):
            factor = p['replaced_kfactor']/2
            assert after['mu95_obs'] == pytest.approx(before['mu95_obs']*factor, rel=1e-14)
            assert after['sigma_ref_fb']*after['mu95_obs'] == pytest.approx(before['sigma_ref_fb']*before['mu95_obs'], rel=1e-14)
            assert after['normalization_change']['correction']['k_factor'] == 2
        bad = copy.deepcopy(contract)
        del bad['points'][-1]['correction']
        fresh = copy.deepcopy(original)
        with pytest.raises(ValueError) as error:
            scan_orchestrator.apply_nlo_renorm(fresh,bad,manifest)
        assert error.value.reason_code == 'missing_cross_section_input' and fresh == original


@pytest.mark.parametrize('fault', ['fractions','state_population','justification','source_sigma','energy','shape'])
def test_rebase_invalid_component_inputs_refuse_atomically(tmp_path,fault):
    contract = transformation(tmp_path,'ANA-0008',('mass',),[(100,),(200,)],['DATA-0011'],'json')
    p = contract['points'][-1]
    if fault == 'fractions': p['components'][0]['source_yield_fraction'] = .7
    if fault == 'state_population': p['components'][0]['source_states'] = ['a','b']
    if fault == 'justification': p['components'][0]['justification'] = ' '
    if fault == 'source_sigma': p['source']['masses']['mass'] = 100
    if fault == 'energy': p['target']['sqrt_s_GeV'] = 9000
    if fault == 'shape': del p['shape_justification']
    rows = [row('0',1000,{'mass':100}),row('1',2000,{'mass':200})]
    original = copy.deepcopy(rows)
    with pytest.raises(ValueError):
        scan_orchestrator.apply_production_transformation(rows,contract,tmp_path)
    assert rows == original


def test_rebase_cli_honors_selected_serialization_and_preserves_provenance(tmp_path):
    from types import SimpleNamespace
    for identity,fmt in [('ANA-0009','json'),('ANA-0010','jsonl')]:
        contract = transformation(tmp_path,identity,('mass',),[(100,)],['DATA-0012'],fmt)
        path = tmp_path/(identity+'-contract.json')
        path.write_text(json.dumps(contract))
        scan_path = tmp_path/(identity+'-scan.json')
        scan_path.write_text(json.dumps({'points':[row('0',1000,{'mass':100})],'n_planned':1,'n_done':1}))
        out = tmp_path/(identity+'-result')
        scan_orchestrator.cmd_rebase(SimpleNamespace(scandir=str(tmp_path),scan=str(scan_path),out=str(out),
                                                     transformation=str(path)))
        result = json.loads(out.read_text())
        assert result['n_planned'] == 1 and result['study_id'] == identity
        assert result['model_basis']['contract']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
        if fmt == 'jsonl': assert result['tag'] == '0'
        else: assert result['points'][0]['tag'] == '0'


def test_selected_science_inputs_bind_relative_table_and_requested_serialization(tmp_path):
    contract = batch(tmp_path,'ANA-0011',('mass',),[(100,),(200,)],['DATA-0013'],'jsonl')
    table_path = Path(contract['points'][0]['request']['table']['path'])
    for p in contract['points']:
        p['request']['table']['path'] = table_path.name
    path = tmp_path/'request.json'
    path.write_text(json.dumps(contract))
    inputs = xs.inputs({'request':str(path)},tmp_path)
    assert path.resolve() in inputs and table_path.resolve() in inputs
    result = xs.run({'request':str(path)},tmp_path,tmp_path/'out')
    assert result['status'] == 'passed'
    output = tmp_path/'out'/'cross-section.jsonl'
    assert output.exists()
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 2 and [r['cross_section']['sigma_pb'] for r in records] == [1,2]
    assert all(r['physics_validated'] is False for r in records)


def test_transformation_coordinate_must_match_source_row(tmp_path):
    contract = transformation(tmp_path,'ANA-0012',('mass',),[(100,)],['DATA-0014'],'json')
    rows = [row('0',1000)]
    rows[0]['parameters'] = {'mass':200}
    original = copy.deepcopy(rows)
    with pytest.raises(ValueError,match='coordinate'):
        scan_orchestrator.apply_production_transformation(rows,contract,tmp_path)
    assert rows == original


def test_missing_source_coordinate_cannot_be_guessed(tmp_path):
    contract = transformation(tmp_path,'ANA-0013',('mass',),[(100,)],['DATA-0015'],'json')
    rows = [row('0',1000)]
    original = copy.deepcopy(rows)
    with pytest.raises(ValueError) as error:
        scan_orchestrator.apply_production_transformation(rows,contract,tmp_path)
    assert error.value.reason_code == 'missing_production_transformation' and rows == original


def test_supplied_table_requires_actual_pdf_and_scale_conventions(tmp_path):
    source = table(tmp_path,'convention',{'100':{'xsec_pb':1}})
    for key in ('pdf','scale'):
        missing = request(source,mass=100)
        missing['convention'][key] = 'as-published'
        with pytest.raises(ValueError) as error:
            xs.lookup(missing)
        assert error.value.reason_code == 'missing_cross_section_input'


def test_contour_annotation_reads_supplied_normalization_records():
    from ravel.plotting import scan_contour
    assert scan_contour._normalization_note({'normalization': {'study_id': 'ANA-0014'}}) == \
        r'signal $\sigma$: supplied correction contract'
    rebased = scan_contour._normalization_note({'model_basis': {'study_id': 'ANA-0014'},
                                                'normalization': {'study_id': 'ANA-0014'}})
    assert rebased == r'$\mu$ on the supplied target $\sigma$ basis'
    assert scan_contour._normalization_note({}) is None
