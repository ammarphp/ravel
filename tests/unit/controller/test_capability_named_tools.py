"""Named-tool recall from inert synthetic catalogue declarations."""
import pytest

from ravel.controller import capabilities


@pytest.fixture
def catalogue(monkeypatch):
    monkeypatch.setattr(capabilities, '_projection', lambda: {})
    atlas = {
        'entries': [{
            'id': 'tool:descriptor/CopperLoom',
            'kind': 'tool',
            'title': 'CopperLoom',
            'summary': 'A fictional declared tool for metadata recall.',
            'links': {'operations': ['op:weave']},
        }],
    }
    signatures = {
        name: {'summary': name, 'tools': tools, 'consumes': [], 'produces': []}
        for name, tools in (
            ('weave', ['CopperLoom']),
            ('polish', ['CopperLoom']),
            ('paint', ['Pigment']),
        )
    }
    return capabilities.catalogue(atlas=atlas, specs=[], signatures=signatures)


@pytest.mark.parametrize('name', (
    'CopperLoom',
    'copperloom',
    'tool:descriptor/CopperLoom',
    'descriptor/CopperLoom',
))
def test_named_tool_offers_declared_tool_and_associated_operations(catalogue, name):
    selected = capabilities.applicable(catalogue, {'requested_tools': [name]})

    assert {row['id'] for row in selected['tools']} == {'tool:descriptor/CopperLoom'}
    assert {row['id'] for row in selected['operations']} == {'weave', 'polish'}


@pytest.mark.parametrize('name', (
    'Copper',
    'Loom',
    'CopperLoomExtra',
    'ExtraCopperLoom',
    'unrelated',
))
def test_tool_recall_requires_an_exact_declared_identity(catalogue, name):
    selected = capabilities.applicable(catalogue, {'requested_tools': [name]})

    assert selected['tools'] == []
    assert selected['operations'] == []


def test_absent_tool_name_does_not_select_operations(catalogue):
    selected = capabilities.applicable(catalogue, {})

    assert selected['tools'] == []
    assert selected['operations'] == []


@pytest.mark.parametrize('name', ('weave', 'polish', 'paint'))
def test_direct_operation_recall_is_preserved(catalogue, name):
    selected = capabilities.applicable(catalogue, {'operation': name})

    assert {row['id'] for row in selected['operations']} == {name}
    assert selected['tools'] == []
