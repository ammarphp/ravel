"""Collection controls: deleting, duplicating or misbinding a case cannot preserve coverage."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from nc_audit import collection_errors, expected_pairs, pending_rows

FILE = 'tests/unit/enforcement/test_nc_toy.py'


def _document():
    return {'bespoke': [{'id': 'Q01', 'test': f'{FILE}::test_Q01', 'status': 'implemented', 'binding': 'installed'},
                         {'id': 'Q02', 'test': None, 'status': 'pending', 'binding': None}],
            'groups': {'g001': {'status': 'implemented', 'dimension': 'TOOL', 'field': None,
                               'bindings': ['controller'], 'tests': [f'{FILE}::test_tool']}},
            'parameterized': {'TOOL-toy-one': 'g001', 'TOOL-toy-two': 'g001'}}


def _item(test, *, rows=(), row=None, dimension=None, fields=(), binding='installed'):
    marker = SimpleNamespace(kwargs={'rows': rows, 'dimension': dimension, 'fields': fields, 'binding': binding})
    node = f'{FILE}::{test}' + (f'[{row}]' if row else '')
    return SimpleNamespace(nodeid=node, get_closest_marker=lambda _: marker,
                           callspec=SimpleNamespace(params={'row': row} if row else {}))


def _items():
    return [_item('test_Q01', rows=('Q01',)),
            _item('test_tool', dimension='TOOL', row='TOOL-toy-one', binding='controller'),
            _item('test_tool', dimension='TOOL', row='TOOL-toy-two', binding='controller')]


def test_compliant_population_and_pending_rows_are_distinct():
    document = _document()
    assert collection_errors(_items(), document, installed_rows=set(document['parameterized'])) == []
    assert len(expected_pairs(document)) == 3
    assert pending_rows(document) == ['Q02']
    document['groups']['g001']['status'] = 'pending'
    assert pending_rows(document) == ['Q02', 'TOOL-toy-one', 'TOOL-toy-two']


def test_removed_parameter_is_a_missing_collected_case():
    errors = collection_errors(_items()[:-1], _document())
    assert any('declared cases missing' in error and 'TOOL-toy-two' in error for error in errors)


def test_repeated_case_is_not_an_extra_completed_obligation():
    items = _items()
    errors = collection_errors(items + [items[0]], _document())
    assert any('collected more than once' in error and 'Q01' in error for error in errors)


@pytest.mark.parametrize('change,reason', [
    ({'row': 'TOOL-toy-unknown'}, 'unknown or absent'),
    ({'row': None}, 'unknown or absent'),
    ({'dimension': 'EXEC'}, 'dimension or card field'),
    ({'binding': 'installed'}, 'runtime binding differs'),
])
def test_mutated_dimension_case_is_refused(change, reason):
    values = {'dimension': 'TOOL', 'row': 'TOOL-toy-one', 'binding': 'controller'}
    values.update(change)
    items = [_items()[0], _item('test_tool', **values), _items()[2]]
    assert any(reason in error for error in collection_errors(items, _document()))


def test_case_cannot_claim_another_tests_row_or_an_empty_declaration():
    items = [_item('test_other', rows=('Q01',)), *_items()[1:]]
    assert any('no declaration binds' in error for error in collection_errors(items, _document()))
    items[0] = _item('test_Q01')
    assert any('declares no rows' in error for error in collection_errors(items, _document()))


def test_case_cannot_claim_a_pending_row_or_another_binding():
    for changes in ({'rows': ('Q02',)}, {'rows': ('Q01',), 'binding': 'controller'}):
        items = [_item('test_Q01', **changes), *_items()[1:]]
        assert any('unknown row or runtime binding differs' in error or 'no declaration binds' in error
                   for error in collection_errors(items, _document()))


def test_role_field_must_match_its_declared_projection():
    document = _document()
    document['groups']['g001'].update(dimension='ROLE', field='purpose')
    document['parameterized'] = {'ROLE-toy-purpose': 'g001'}
    item = _item('test_tool', dimension='ROLE', fields=('identity',), row='ROLE-toy-purpose', binding='controller')
    assert any('card field' in error for error in collection_errors([_items()[0], item], document))
    item.get_closest_marker('nc_case').kwargs['fields'] = ('purpose',)
    assert collection_errors([_items()[0], item], document) == []


def test_registry_addition_and_removal_refuse_collection():
    population = set(_document()['parameterized'])
    for changed in (population | {'TOOL-toy-new'}, population - {'TOOL-toy-two'}):
        errors = collection_errors(_items(), _document(), installed_rows=changed)
        assert any('installed population differs' in error for error in errors)


def test_explicit_subset_does_not_claim_the_missing_cases():
    document = _document()
    original = deepcopy(document)
    assert collection_errors(_items()[:1], document, complete_files=False) == []
    assert collection_errors([_item('test_Q01', rows=('Q99',))], document, complete_files=False)
    assert collection_errors(_items()[:1], document, installed_rows={'TOOL-new'}, complete_files=False)
    assert document == original


def test_unmarked_function_cannot_replace_a_deleted_case():
    item = SimpleNamespace(nodeid=f'{FILE}::test_Q01', get_closest_marker=lambda _: None)
    assert any('declared cases missing' in error for error in collection_errors([item], _document()))
