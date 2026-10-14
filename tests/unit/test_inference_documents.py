"""Inference document references: HEPData tables, binned_values results, correlation matrices."""
import json

import numpy as np
import pytest
import yaml

from ravel.physics.inference import documents


def hepdata_vector_table():
    return {'independent_variables': [{'header': {'name': 'mass', 'units': 'GeV'},
                                       'values': [{'low': 0, 'high': 1}, {'low': 1, 'high': 2}]}],
            'dependent_variables': [{'header': {'name': 'cross section'}, 'values': [{'value': 1.5}, {'value': 0.5}]},
                                    {'header': {'name': 'prediction'}, 'values': [{'value': 1.4}, {'value': 0.6}]}]}


def hepdata_matrix_table(entries):
    bins = [{'low': 0, 'high': 1}, {'low': 1, 'high': 2}]
    rows, cols, values = [], [], []
    for i in range(2):
        for j in range(2):
            rows.append(bins[i]); cols.append(bins[j]); values.append({'value': entries[i][j]})
    return {'independent_variables': [{'header': {'name': 'bin i'}, 'values': rows},
                                      {'header': {'name': 'bin j'}, 'values': cols}],
            'dependent_variables': [{'header': {'name': 'correlation'}, 'values': values}]}


def context(tmp_path, document):
    (tmp_path / 'doc.json').write_text(json.dumps(document))
    return documents.Context('doc.json', tmp_path)


def test_hepdata_columns_by_index_and_header(tmp_path):
    (tmp_path / 'table.yaml').write_text(yaml.safe_dump(hepdata_vector_table()))
    ctx = context(tmp_path, {})
    assert np.allclose(ctx.vector({'path': 'table.yaml', 'format': 'hepdata', 'column': 0}, 'x'), [1.5, 0.5])
    assert np.allclose(ctx.vector({'path': 'table.yaml', 'format': 'hepdata', 'column': 'prediction'}, 'x'), [1.4, 0.6])
    with pytest.raises(ValueError):
        ctx.vector({'path': 'table.yaml', 'format': 'hepdata', 'column': 'missing'}, 'x')
    assert {p['path'] for p in ctx.inputs()} == {str((tmp_path / 'doc.json').absolute()), str((tmp_path / 'table.yaml').absolute())}


def test_hepdata_correlation_matrix_becomes_covariance(tmp_path):
    (tmp_path / 'corr.yaml').write_text(yaml.safe_dump(hepdata_matrix_table([[1.0, 0.25], [0.25, 1.0]])))
    ctx = context(tmp_path, {})
    cov = ctx.matrix({'path': 'corr.yaml', 'format': 'hepdata', 'kind': 'correlation', 'errors': [2.0, 3.0]}, 'C')
    assert np.allclose(cov, [[4.0, 1.5], [1.5, 9.0]])


def test_incomplete_hepdata_matrix_is_refused(tmp_path):
    table = hepdata_matrix_table([[1.0, 0.25], [0.25, 1.0]])
    for var in table['independent_variables']:
        var['values'] = var['values'][:3]
    table['dependent_variables'][0]['values'] = table['dependent_variables'][0]['values'][:3]
    (tmp_path / 'bad.yaml').write_text(yaml.safe_dump(table))
    with pytest.raises(ValueError):
        context(tmp_path, {}).matrix({'path': 'bad.yaml', 'format': 'hepdata'}, 'C')


def test_binned_values_supply_values_and_sumw2(tmp_path):
    (tmp_path / 'h.json').write_text(json.dumps({
        'schema_version': 1, 'kind': 'binned_values', 'axes': [{'name': 'x', 'unit': 'GeV'}], 'unit': 'events',
        'representation': 'integrated',
        'bins': [{'low': [0], 'high': [1], 'value': 3.0, 'sumw2': 0.5}, {'low': [1], 'high': [2], 'value': 1.0, 'sumw2': 0.2}]}))
    values, sumw2 = context(tmp_path, {}).vector({'path': 'h.json', 'format': 'binned-values'}, 'h', with_sumw2=True)
    assert values.tolist() == [3.0, 1.0] and sumw2.tolist() == [0.5, 0.2]


def test_strict_json_and_regular_files(tmp_path):
    (tmp_path / 'doc.json').write_text('{"a": 1, "a": 2}')
    with pytest.raises(ValueError, match='repeats'):
        documents.Context('doc.json', tmp_path)
    (tmp_path / 'nan.json').write_text('{"a": NaN}')
    with pytest.raises(ValueError, match='nonfinite'):
        documents.Context('nan.json', tmp_path)
    (tmp_path / 'real.json').write_text('{}')
    (tmp_path / 'link.json').symlink_to(tmp_path / 'real.json')
    with pytest.raises(ValueError, match='symlink'):
        documents.Context('link.json', tmp_path)
