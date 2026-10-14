"""Table to bin-edges converter: edges only from stated contiguous intervals, never from centres."""
import json

import pytest

from ravel.physics import table_bin_edges as tb
from ravel.validation import signature_conformance as sc

SUBMISSION = {'independent_variables': [{'header': {'name': 'x_obs', 'units': 'GeV'},
                                         'values': [{'low': 0, 'high': 50}, {'low': 50, 'high': 100},
                                                    {'low': 100, 'high': 200}]}],
              'dependent_variables': [{'header': {'name': 'events'},
                                       'values': [{'value': 12, 'errors': [{'symerror': 3}]}, {'value': 7},
                                                  {'value': 2}]}]}
WEB = {'headers': [{'name': 'x_obs [GeV]'}, {'name': 'rate'}],
       'values': [{'x': [{'low': 1, 'high': 2}], 'y': [{'value': 0.5}]},
                  {'x': [{'low': 2, 'high': 4}], 'y': [{'value': 0.25}]}]}
COLUMNS = {'columns': ['x low', 'x high', 'yield', 'stat'], 'rows': [[0, 1, 4.0, 2.0], [1, 3, 9.0, 3.0]]}


def test_submission_layout_converts_to_edges_and_values():
    doc = tb.convert(SUBMISSION)
    assert doc['edges'] == [0, 50, 100, 200] and doc['values'] == [12, 7, 2]
    assert doc['x'] == 'x_obs [GeV]' and doc['errors'][0] == {'err0': [-3.0, 3.0]}
    assert len(doc['source_sha256']) == 64


def test_web_and_column_layouts_convert():
    assert tb.convert(WEB)['edges'] == [1, 2, 4]
    doc = tb.convert(COLUMNS, value_column='yield')
    assert doc['edges'] == [0, 1, 3] and doc['values'] == [4.0, 9.0] and doc['x'] == 'x'


@pytest.mark.parametrize('table,needle', [
    ({'independent_variables': [{'header': {'name': 'x'}, 'values': [{'value': 5}, {'value': 15}]}],
      'dependent_variables': [{'header': {'name': 'y'}, 'values': [{'value': 1}, {'value': 2}]}]}, 'not inferred'),
    ({'independent_variables': [{'header': {'name': 'x'}, 'values': [{'low': 0, 'high': 1}, {'low': 2, 'high': 3}]}],
      'dependent_variables': [{'header': {'name': 'y'}, 'values': [{'value': 1}, {'value': 2}]}]}, 'not inferred'),
    ({'columns': ['centre', 'yield'], 'rows': [[5, 1], [15, 2]]}, 'not inferred from centres'),
    ({'columns': ['low', 'high', 'yield'], 'rows': [[0, 1, 1], [0.5, 2, 2]]}, 'not contiguous'),
    ({'columns': ['low', 'high', 'a', 'b'], 'rows': [[0, 1, 1, 2]]}, 'name the value column'),
])
def test_tables_without_stated_contiguous_intervals_are_refused(table, needle):
    with pytest.raises(ValueError, match=needle):
        tb.convert(table)


def test_output_meets_the_converter_signature_and_the_binned_values_witness():
    doc = tb.convert(SUBMISSION)
    assert sc.witness('binned_values', doc) == []
    assert sc.output_errors('table-bin-edges', {'values': doc}) == []


def test_command_line(tmp_path, capsys):
    good, bad = tmp_path / 'good.json', tmp_path / 'bad.json'
    good.write_text(json.dumps(COLUMNS))
    bad.write_text(json.dumps({'columns': ['centre', 'y'], 'rows': [[1, 2]]}))
    assert tb.main([str(good), '--value-column', 'yield']) == 0
    assert json.loads(capsys.readouterr().out)['edges'] == [0, 1, 3]
    assert tb.main([str(bad)]) == 2
