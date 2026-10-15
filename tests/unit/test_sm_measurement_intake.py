"""Synthetic covariance assembly, literal errors and supplied record controls."""
import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest


def api():
    from ravel.physics.sm import measurement_intake
    return measurement_intake


def example():
    values = [10., 20., 30.]
    errors = {'stat': [1., 2., 3.], 'shape': [2., 1., 2.],
              'scale': [1., 2., 1.], 'local': [.5, .5, .5], 'lumi': [.2, .4, .6]}
    rows = []
    for i, value in enumerate(values):
        total = math.sqrt(sum(v[i] ** 2 for v in errors.values()))
        rows.append({'value': value, 'errors': [
            {'label': k, 'symerror': ('2%' if k == 'lumi' else v[i])}
            for k, v in errors.items()] + [{'label': 'total', 'symerror': total}]})
    table = {'name': 'Table A', 'independent_variables': [
        {'header': {'name': 'x'}, 'values': [{'low': i, 'high': i+1} for i in range(3)]}],
        'dependent_variables': [{'header': {'name': 'value', 'units': 'fb'}, 'values': rows}]}
    record = {'schema_version': 1, 'kind': 'hepdata-record', 'record': 'ANA-0001', 'version': 2, 'tables': [table]}
    mapping = {'source': {'hepdata': 'ANA-0001', 'version': 2, 'tables': ['Table A'],
                           'doi': 'synthetic', 'sha256': {'record': 'a'*64}},
               'distribution': 'Table A', 'column': 0,
               'observable': {'name': 'x', 'unit': 'fb', 'level': 'dressed'},
               'normalization': 'absolute', 'fiducial': {'text': 'Supplied synthetic interval'},
               'total_error_label': 'total',
               'components': [{'name': k, 'kind': 'lumi' if k == 'lumi' else ('stat' if k == 'stat' else 'syst'),
                               'error_label': k, 'correlation': 'diagonal' if k in ('stat', 'local') else 'full'}
                              for k in errors]}
    return record, mapping


def matrix(record, values, kind='correlation', name='Table B', unit=''):
    n = len(values)
    record['tables'].append({'name': name, 'matrix_kind': kind,
        'independent_variables': [
            {'header': {'name': 'row'}, 'values': [{'value': str(i)} for i in range(n) for j in range(n)]},
            {'header': {'name': 'column'}, 'values': [{'value': str(j)} for i in range(n) for j in range(n)]}],
        'dependent_variables': [{'header': {'name': kind, 'units': unit},
                                'values': [{'value': v} for row in values for v in row]}]})


def test_ignored_correlation_table_refused_first():
    record, mapping = example()
    matrix(record, np.eye(3).tolist())
    with pytest.raises(ValueError, match='TS3.*ignored'):
        api().assemble(record, mapping)


def test_asymmetric_rule_required():
    record, mapping = example()
    record['tables'][0]['dependent_variables'][0]['values'][0]['errors'][0] = {
        'label': 'stat', 'asymerror': {'minus': -1, 'plus': 3}}
    with pytest.raises(ValueError, match='symmetrization'):
        api().assemble(record, mapping)


@pytest.mark.parametrize('fault', ['domain', 'nonpsd', 'asymmetric', 'diagonal', 'unit', 'cell'])
def test_matrix_failures_name_bins(fault):
    record, mapping = example()
    correlation = np.eye(3).tolist()
    correlation[0][1] = correlation[1][0] = 1.2 if fault == 'domain' else .9
    if fault == 'nonpsd':
        correlation[0][2] = correlation[2][0] = .9
        correlation[1][2] = correlation[2][1] = -.9
    if fault == 'asymmetric': correlation[1][0] = .2
    if fault == 'diagonal': correlation[0][0] = .5
    matrix(record, correlation, unit='fb' if fault == 'unit' else '')
    if fault == 'cell': record['tables'][1]['dependent_variables'][0]['values'].pop()
    mapping['components'][1]['correlation'] = 'matrix:Table B'
    mapping['components'][1]['matrix_labels'] = ['0', '1', '2']
    with pytest.raises(ValueError, match='bin|unit|cell'):
        api().assemble(record, mapping)


def routine():
    return {'id': 'RoutineA', 'version': '1', 'options': {}, 'record': 'ANA-0001',
            'record_version': 2, 'ref_yoda_sha256': 'b'*64,
            'source_text': 'void init() { book(_h, 1, 1, 1); }',
            'histogram_edges': {'d01-x01-y01': [0., 1., 2., 3.]}}


@pytest.mark.parametrize('fault', ['version', 'identity', 'bins', 'unknown', 'missing', 'dynamic'])
def test_routine_mismatch_ts6(fault):
    record, mapping = example()
    supplied = routine()
    if fault == 'version': supplied['record_version'] = 1
    if fault == 'identity': supplied['record'] = 'ANA-0002'
    if fault == 'bins': supplied['histogram_edges']['d01-x01-y01'][-1] = 4
    if fault == 'unknown': supplied['source_text'] = 'book(_h, 8, 1, 1);'
    if fault == 'missing': supplied['histogram_edges'] = {}
    if fault == 'dynamic': supplied['source_text'] = 'book(_h, index, 1, 1);'
    with pytest.raises(ValueError, match='TS6'):
        api().assemble(record, mapping, routine=supplied)


def normalized():
    record, mapping = example()
    column = record['tables'][0]['dependent_variables'][0]
    covariance = (np.eye(3) - np.ones((3, 3))/3) * .01
    for i, row in enumerate(column['values']):
        row['value'] = [0.2, 0.3, 0.5][i]
        row['errors'] = [{'label': 'total', 'symerror': math.sqrt(covariance[i, i])}]
    matrix(record, covariance.tolist(), kind='covariance', unit='(fb)^2')
    mapping.update(normalization='normalized', normalization_weights=[1, 1, 1],
                   components=[{'name': 'experimental', 'kind': 'syst', 'correlation': 'matrix:Table B', 'matrix_labels': ['0', '1', '2']}])
    return record, mapping


@pytest.mark.parametrize('fault', ['rank', 'constraint', 'central'])
def test_normalized_invalid_law_refused(fault):
    record, mapping = normalized()
    cells = record['tables'][1]['dependent_variables'][0]['values']
    if fault in ('rank', 'constraint'):
        for i, cell in enumerate(cells): cell['value'] = (.01 if i in (0, 4, 8) else 0) if fault == 'rank' else 0
    else: record['tables'][0]['dependent_variables'][0]['values'][0]['value'] = .4
    with pytest.raises(ValueError, match='normalized|total'):
        api().assemble(record, mapping)


def test_unmapped_named_error_refused():
    record, mapping = example()
    mapping['components'].pop()
    with pytest.raises(ValueError, match='unmapped'):
        api().assemble(record, mapping)


def test_stated_total_disagreement_refused():
    record, mapping = example()
    record['tables'][0]['dependent_variables'][0]['values'][0]['errors'][-1]['symerror'] *= 2
    with pytest.raises(ValueError, match='total.*bin'):
        api().assemble(record, mapping)


def test_luminosity_must_be_fully_correlated():
    record, mapping = example()
    mapping['components'][-1]['correlation'] = 'diagonal'
    with pytest.raises(ValueError, match='luminosity'):
        api().assemble(record, mapping)


def test_missing_level_refused():
    record, mapping = example()
    del mapping['observable']['level']
    with pytest.raises(ValueError, match='level'):
        api().assemble(record, mapping)


def test_total_symmetric_psd_and_marginals():
    record, mapping = example()
    bundle = api().assemble(record, mapping)
    expected = np.diag(np.array([1, 2, 3])**2 + .25)
    for vector in ([2, 1, 2], [1, 2, 1], [.2, .4, .6]): expected += np.outer(vector, vector)
    np.testing.assert_allclose(bundle['covariance']['total'], expected, rtol=1e-14)
    assert bundle['covariance']['psd'] and bundle['assembly_checks']['total_reproduced_max_rel_dev'] < .001
    assert bundle['components'][-1]['values'] == [[.2, .2], [.4, .4], [.6, .6]]


@pytest.mark.parametrize('rule,expected', [('average', 2), ('max', 3)])
def test_asymmetric_hand_computation(rule, expected):
    record, mapping = example()
    rows = record['tables'][0]['dependent_variables'][0]['values']
    rows[0]['errors'][0] = {'label': 'stat', 'asymerror': {'minus': '-10%', 'plus': '30%'}}
    rows[0]['errors'][-1]['symerror'] = math.sqrt(expected**2 + 4 + 1 + .25 + .04)
    mapping['components'][0]['symmetrization'] = rule
    bundle = api().assemble(record, mapping)
    assert bundle['covariance']['by_component']['stat'][0][0] == expected**2
    assert bundle['components'][0]['symmetrized'] == rule


def test_normalized_rank_and_constraint():
    record, mapping = normalized()
    bundle = api().assemble(record, mapping)
    assert bundle['covariance']['rank'] == 2
    assert bundle['covariance']['law'] == 'normalized-rank-n-minus-one'
    np.testing.assert_allclose(np.array(bundle['covariance']['total']) @ np.ones(3), 0, atol=1e-12)
    assert abs(sum(bundle['values'])-1) < 1e-12


def test_matching_routine_records_map():
    record, mapping = example()
    bundle = api().assemble(record, mapping, routine=routine())
    assert bundle['fiducial']['routine_bookings'] == {'d01-x01-y01': 'Table A'}
    assert bundle['routine']['record_version'] == 2


def test_declared_rule_correlation():
    record, mapping = example()
    mapping['components'][1]['correlation'] = 'declared:equicorrelation'
    mapping['components'][1]['rule'] = {'rho': .25}
    bundle = api().assemble(record, mapping)
    assert bundle['covariance']['by_component']['shape'][0][1] == .5


def test_web_table_layout_preserves_percent_header():
    record, mapping = example()
    table = record['tables'][0]
    column = table['dependent_variables'][0]
    for row in column['values']:
        for error in row['errors']:
            if error['label'] == 'lumi': error['symerror'] = 2
            else: error['symerror'] = 100 * error['symerror'] / row['value']
    column['header']['error_units'] = '%'
    record['tables'][0] = {'name': 'Table A', 'headers': [table['independent_variables'][0]['header'], column['header']],
        'values': [{'x': [axis], 'y': [row]} for axis, row in zip(table['independent_variables'][0]['values'], column['values'])]}
    bundle = api().assemble(record, mapping)
    assert bundle['components'][-1]['values'][2] == [.6, .6]
    assert bundle['assembly_checks']['total_reproduced_max_rel_dev'] < 1e-12


def test_literal_source_tables_join_and_matrix(tmp_path):
    from ravel.physics import source_tables
    import hashlib
    import yaml
    record, mapping = example()
    table = record['tables'][0]
    path = tmp_path/'table.yaml'
    path.write_text(yaml.safe_dump({k: table[k] for k in ('independent_variables', 'dependent_variables')}))
    pin = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    literal = source_tables.read_table(pin)
    joined = {'kind': 'source-primary-table-basis-join', 'distributions': [
        {'id': 'Table A', 'source': pin, 'axes': literal['payload']['independent_variables'],
         'bin_ids': ['b0', 'b1', 'b2'], 'selected_columns': literal['payload']['dependent_variables']}],
        'matrix_components': [], 'contract_sha256': 'c'*64}
    bundle = api().assemble(joined, mapping)
    assert bundle['bin_ids'] == ['b0', 'b1', 'b2']
    assert bundle['values'] == [10, 20, 30]
    assert bundle['source']['sha256']['Table A'] == pin['sha256']


def test_bundle_round_trip_and_tamper(tmp_path):
    record, mapping = example()
    bundle = api().assemble(record, mapping)
    path = tmp_path/'bundle.json'
    path.write_text(json.dumps(bundle))
    assert api().load_bundle(path) == bundle
    bundle['covariance']['total'][0][0] += 1
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match='component'):
        api().load_bundle(path)


def test_loader_duplicate_and_nonfinite_refused(tmp_path):
    path = tmp_path/'bundle.json'
    for raw in ('{"kind": 1, "kind": 2}', '{"value": NaN}'):
        path.write_text(raw)
        with pytest.raises(ValueError): api().load_bundle(path)


def test_lifecycle_contract_pins_all_inputs(tmp_path):
    import hashlib
    record, mapping = example()
    paths = []
    for name, doc in [('tables.json', record), ('map.json', mapping)]:
        path = tmp_path/name
        path.write_text(json.dumps(doc))
        paths.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    spec = {'schema_version': 1, 'input': paths[0], 'component_map': paths[1]}
    assert api().inputs(spec, tmp_path) == [tmp_path/'tables.json', tmp_path/'map.json']
    result = api().run(spec, tmp_path, tmp_path/'out')
    assert api().load_bundle(tmp_path/'out'/'measurement-bundle.json') == result
    (tmp_path/'map.json').write_text('{}')
    with pytest.raises(ValueError, match='digest'): api().inputs(spec, tmp_path)


@pytest.mark.parametrize('fault', ['version', 'identity'])
def test_separate_record_version_and_identity_refused(fault):
    record, mapping = example()
    other = copy.deepcopy(record)
    other['version' if fault == 'version' else 'record'] = 3 if fault == 'version' else 'ANA-0002'
    with pytest.raises(ValueError, match='TS6'):
        api().assemble(record, mapping, routine=routine(), record=other)


@pytest.mark.parametrize('fault', ['nonfinite', 'interval', 'component', 'lumi', 'routine_version'])
def test_bundle_semantic_tampering_refused(tmp_path, fault):
    record, mapping = example()
    bundle = api().assemble(record, mapping, routine=routine())
    if fault == 'nonfinite': bundle['values'][0] = 1e309
    if fault == 'interval': bundle['bins'][0]['hi'] = -1
    if fault == 'component': bundle['components'][0]['values'][0][0] += 1
    if fault == 'lumi': bundle['components'][-1]['correlation'] = 'diagonal'
    if fault == 'routine_version': bundle['routine']['record_version'] += 1
    path = tmp_path/'bundle.json'
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError): api().load_bundle(path)


def test_matrix_label_permutation_preserves_bins():
    record, mapping = example()
    matrix(record, [[1, .2, .3], [.2, 1, .4], [.3, .4, 1]])
    mapping['components'][1].update(correlation='matrix:Table B', matrix_labels=['2', '0', '1'])
    bundle = api().assemble(record, mapping)
    assert bundle['covariance']['by_component']['shape'][0][1] == 2*1*.3


def test_normalized_density_uses_declared_widths():
    record, mapping = normalized()
    widths = np.array([1, 2, 3])
    axis = record['tables'][0]['independent_variables'][0]['values']
    for v, low, high in zip(axis, [0, 1, 3], [1, 3, 6]): v.update(low=low, high=high)
    for row, width in zip(record['tables'][0]['dependent_variables'][0]['values'], widths):
        row['value'] /= width
        row['errors'][0]['symerror'] /= width
    cells = record['tables'][1]['dependent_variables'][0]['values']
    for i, cell in enumerate(cells): cell['value'] /= widths[i//3]*widths[i%3]
    mapping['normalization_weights'] = widths.tolist()
    bundle = api().assemble(record, mapping)
    assert bundle['covariance']['rank'] == 2
    np.testing.assert_allclose(np.array(bundle['covariance']['total'])@widths, 0, atol=1e-12)


def test_literal_joined_correlation_consumed():
    record, mapping = example()
    table = record['tables'][0]
    joined = {'kind': 'source-primary-table-basis-join', 'distributions': [
        {'id': 'Table A', 'axes': table['independent_variables'], 'bin_ids': ['a', 'b', 'c'],
         'selected_columns': table['dependent_variables']}],
        'matrix_components': [{'id': 'R', 'kind': 'correlation', 'header': {'units': ''},
            'bin_ids': ['c', 'a', 'b'], 'literal_matrix': [[1, .3, .4], [.3, 1, .2], [.4, .2, 1]]}]}
    mapping['components'][1]['correlation'] = 'matrix:R'
    bundle = api().assemble(joined, mapping)
    assert bundle['covariance']['by_component']['shape'][0][1] == .4


def test_declared_block_rule():
    record, mapping = example()
    mapping['components'][1].update(correlation='declared:blocks', rule={'groups': ['a', 'a', 'b'], 'rho': .5})
    bundle = api().assemble(record, mapping)
    assert bundle['covariance']['by_component']['shape'][0][1] == 1
    assert bundle['covariance']['by_component']['shape'][0][2] == 0


def test_declared_signed_rule():
    record, mapping = example()
    mapping['components'][1].update(correlation='declared:matrix', rule={
        'bin_ids': ['bin0', 'bin1', 'bin2'], 'values': [[1, -1, 1], [-1, 1, -1], [1, -1, 1]]})
    bundle = api().assemble(record, mapping)
    assert bundle['covariance']['by_component']['shape'][0][1] == -2


def test_supplied_fixture_schema_and_registration_fragment():
    from ravel.validation import validate_request_plan as rp
    import jsonschema
    root = Path(__file__).resolve().parents[2]
    fixture = root/'tests/fixtures/sm/intake'
    bundle = api().assemble(json.loads((fixture/'record.json').read_text()),
                            json.loads((fixture/'component-map.json').read_text()))
    schema = json.loads((root/'src/ravel/data/sm/schema/measurement-bundle.schema.json').read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(bundle)
    fragment = json.loads((root/'src/ravel/data/sm/registration/measurement-intake.json').read_text())
    jsonschema.Draft202012Validator(rp.SIGNATURE_SCHEMA).validate(fragment['operation_signatures']['measurement-intake'])
    assert fragment['mode_descriptors']['measurement-intake']['applicability'] == {'scope': 'general'}
    assert fragment['operation_signatures']['measurement-intake']['effects'] == []


@pytest.mark.parametrize('count', [1, 2, 5])
def test_supplied_population_units_and_identity_vary(count):
    record, mapping = example()
    record.update(record='ANA-0002', version=7)
    table = record['tables'][0]
    table['name'] = 'Table C'
    table['independent_variables'][0]['values'] = [{'low': i*2, 'high': (i+1)*2} for i in range(count)]
    table['dependent_variables'][0].update(header={'name': 'density', 'units': 'pb'}, values=[
        {'value': i+1, 'errors': [{'label': 'stat', 'symerror': .1*(i+1)},
                                {'label': 'total', 'symerror': .1*(i+1)}]} for i in range(count)])
    mapping['source'].update(hepdata='ANA-0002', version=7, tables=['Table C'])
    mapping.update(distribution='Table C', components=[mapping['components'][0]])
    mapping['observable'].update(unit='pb', level='born')
    bundle = api().assemble(record, mapping)
    assert len(bundle['bins']) == count
    assert bundle['covariance']['rank'] == count
    np.testing.assert_allclose(np.diag(bundle['covariance']['total']), (.1*np.arange(1, count+1))**2)


@pytest.mark.parametrize('unit', [None, '', '1'])
def test_dimensionless_covariance_table_accepted(unit):
    record, mapping = normalized()
    record['tables'][0]['dependent_variables'][0]['header'] = {'name': 'value'}
    record['tables'][1]['dependent_variables'][0]['header'] = {'name': 'covariance'} if unit is None else {'name': 'covariance', 'units': unit}
    mapping['observable']['unit'] = ''
    bundle = api().assemble(record, mapping)
    assert bundle['covariance']['rank'] == 2
    record['tables'][1]['dependent_variables'][0]['header']['units'] = 'fb'
    with pytest.raises(ValueError, match='unit'):
        api().assemble(record, mapping)


def signed(fault):
    record, mapping = example()
    rows = record['tables'][0]['dependent_variables'][0]['values']
    if fault == 'symmetric': rows[1]['errors'][1]['symerror'] = -1.
    if fault == 'flipped': rows[1]['errors'][1] = {'label': 'shape', 'asymerror': {'minus': 1., 'plus': -1.}}
    if fault == 'relative':
        rows[1]['value'] = -20.
        for row in rows: row['errors'][1]['symerror'] = '10%'
        rows[0]['errors'][-1]['symerror'] = math.sqrt(1 + 1 + 1 + .25 + .04)
        rows[1]['errors'][-1]['symerror'] = math.sqrt(4 + 4 + 4 + .25 + .16)
        rows[2]['errors'][-1]['symerror'] = math.sqrt(9 + 9 + 1 + .25 + .36)
        mapping['components'][-1]['correlation'] = 'diagonal'; mapping['components'][-1]['kind'] = 'syst'
    mapping['components'][1]['symmetrization'] = 'average'
    return record, mapping


@pytest.mark.parametrize('fault', ['symmetric', 'flipped', 'relative'])
@pytest.mark.parametrize('correlation', ['full', 'declared:equicorrelation', 'declared:blocks'])
def test_opposite_signed_shifts_in_common_sign_rule_refused(fault, correlation):
    record, mapping = signed(fault)
    mapping['components'][1].update(correlation=correlation, rule={'rho': .5, 'groups': ['a', 'a', 'b']})
    with pytest.raises(ValueError, match='signed.*bin1'):
        api().assemble(record, mapping)


def test_signed_shifts_without_common_sign_rule_keep_magnitudes():
    record, mapping = signed('symmetric')
    mapping['components'][1]['correlation'] = 'diagonal'
    assert api().assemble(record, mapping)['covariance']['by_component']['shape'][1][1] == 1
    mapping['components'][1].update(correlation='declared:blocks', rule={'rho': .5, 'groups': ['a', 'b', 'a']})
    assert api().assemble(record, mapping)['covariance']['by_component']['shape'][0][2] == 2
    mapping['components'][1].update(correlation='declared:matrix', rule={
        'bin_ids': ['bin0', 'bin1', 'bin2'], 'values': [[1, -1, 1], [-1, 1, -1], [1, -1, 1]]})
    assert api().assemble(record, mapping)['covariance']['by_component']['shape'][0][1] == -2
    for row in record['tables'][0]['dependent_variables'][0]['values']: row['errors'][1]['symerror'] = -abs(row['errors'][1]['symerror'])
    mapping['components'][1]['correlation'] = 'full'; del mapping['components'][1]['rule']
    assert api().assemble(record, mapping)['covariance']['by_component']['shape'][0][1] == 2


@pytest.mark.parametrize('unit', ['absolute', 'fb'])
def test_percent_literal_with_absolute_units_refused(unit):
    record, mapping = example()
    for row in record['tables'][0]['dependent_variables'][0]['values']: row['errors'][4]['units'] = unit
    with pytest.raises(ValueError, match='units conflict'):
        api().assemble(record, mapping)
