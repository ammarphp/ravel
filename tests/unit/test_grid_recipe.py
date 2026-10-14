"""Declared-axes grid recipe: axes are data, the vocabulary is family-neutral, two unrelated families."""
import json
from pathlib import Path

import pytest

from ravel.validation.intake_records import NODE
from ravel.validation.validate_task_contract import _schema_errors
from ravel.workflow import grid_recipe as gr

# Two unrelated synthetic parameter families: a mediator mass against a coupling, and an
# effective-operator scale against a dimensionless coefficient with a paired-list grid.
FAMILY_A = {'schema_version': 1, 'kind': 'grid-recipe', 'axes': [
    {'name': 'm_med', 'unit': 'GeV', 'values': [500, 1000, 1500]},
    {'name': 'g_q', 'unit': None, 'range': {'min': 0.01, 'max': 1.0, 'steps': 3, 'spacing': 'log'}}]}
FAMILY_B = {'schema_version': 1, 'kind': 'grid-recipe', 'combine': 'zip', 'axes': [
    {'name': 'Lambda', 'unit': 'TeV', 'range': {'min': 1, 'max': 4, 'steps': 4}},
    {'name': 'c_6', 'unit': None, 'values': [-1.0, -0.5, 0.5, 1.0]}]}


def test_two_unrelated_families_expand_from_declared_axes_alone():
    a = gr.points(FAMILY_A)
    assert len(a) == 9
    assert a[0] == {'m_med': 500, 'g_q': 0.01} and a[-1] == {'m_med': 1500, 'g_q': 1.0}
    assert a[1]['g_q'] == pytest.approx(0.1)
    b = gr.points(FAMILY_B)
    assert b == [{'Lambda': 1, 'c_6': -1.0}, {'Lambda': 2.0, 'c_6': -0.5}, {'Lambda': 3.0, 'c_6': 0.5},
                 {'Lambda': 4, 'c_6': 1.0}]


def test_axis_names_and_units_are_data_not_vocabulary():
    renamed = json.loads(json.dumps(FAMILY_A).replace('m_med', 'axis_one').replace('g_q', 'axis_two'))
    values = lambda r: [list(p.values()) for p in gr.points(r)]
    assert values(renamed) == values(FAMILY_A)
    source = Path(gr.__file__).read_text().lower()
    for family_word in ('mass', 'lifetime', 'coupling', 'mediator', 'gluino', 'squark', 'dark', 'neutralino'):
        assert family_word not in source, family_word


def test_fan_out_axes_fit_the_plan_node_schema():
    fan_out = {'axes': gr.fan_out_axes(FAMILY_A, {'m_med': 'F1'}), 'subgraph': ['N2'], 'aggregate': 'N3'}
    assert _schema_errors(fan_out, NODE['properties']['fan_out'], 'fan_out') == []
    assert fan_out['axes'][0] == {'name': 'm_med', 'unit': 'GeV', 'values': [500, 1000, 1500], 'fact': 'F1'}


def test_document_pins_the_recipe():
    doc = gr.document(FAMILY_B)
    assert doc['kind'] == 'parameter-grid' and doc['recipe_sha256'] == gr.recipe_sha256(FAMILY_B)
    assert [a['name'] for a in doc['axes']] == ['Lambda', 'c_6'] and len(doc['points']) == 4


@pytest.mark.parametrize('change,needle', [
    ({'axes': []}, '1 to 8 axes'),
    ({'axes': [{'name': 'x', 'values': [1, 2]}]}, 'states its unit'),
    ({'axes': [{'name': 'x', 'unit': 'GeV'}]}, 'either values or a range'),
    ({'axes': [{'name': 'x', 'unit': 'GeV', 'values': [1, 1]}]}, 'distinct'),
    ({'axes': [{'name': 'x', 'unit': None, 'range': {'min': 0, 'max': 1, 'steps': 3, 'spacing': 'log'}}]}, 'min > 0'),
    ({'axes': [{'name': 'x', 'unit': None, 'range': {'min': 2, 'max': 1, 'steps': 3}}]}, 'min < max'),
    ({'axes': [{'name': 'x', 'unit': None, 'values': [1]}, {'name': 'x', 'unit': None, 'values': [2]}]}, 'names are distinct'),
    ({'combine': 'zip', 'axes': [{'name': 'x', 'unit': None, 'values': [1]}, {'name': 'y', 'unit': None, 'values': [1, 2]}]},
     'equal length'),
    ({'axes': [{'name': 'x', 'unit': None, 'range': {'min': 1, 'max': 2, 'steps': 1000}},
               {'name': 'y', 'unit': None, 'range': {'min': 1, 'max': 2, 'steps': 1000}}]}, 'at most 10000'),
    ({'kind': 'other'}, 'kind grid-recipe'),
])
def test_incomplete_recipes_are_refused(change, needle):
    recipe = dict(FAMILY_A, **change)
    errors = gr.errors(recipe)
    assert any(needle in e for e in errors), errors
    with pytest.raises(ValueError):
        gr.points(recipe)


def test_command_line_expands_and_checks(tmp_path, capsys):
    path = tmp_path / 'recipe.json'
    path.write_text(json.dumps(FAMILY_A))
    assert gr.main([str(path)]) == 0
    assert len(json.loads(capsys.readouterr().out)['points']) == 9
    path.write_text(json.dumps(dict(FAMILY_A, axes=[])))
    assert gr.main([str(path), '--check']) == 1
