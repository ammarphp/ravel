"""Synthetic controls for signature-backed chain discovery and compatibility."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ravel.workflow import operation_definitions as definitions


def test_chain_uses_existing_signatures_and_executors():
    rows = definitions.definitions()
    assert set(rows) == {'model-events', 'columnar-analysis', 'signal-template'}
    from ravel.workflow.science import MODES, adapter
    assert [MODES.index(mode) for mode in ('model-events', 'signal-template', 'columnar-analysis')] == [22, 34, 94]
    for mode, row in rows.items():
        assert MODES.count(mode) == 1
        assert adapter({'mode': mode, 'task': {}}).__name__ == row['signature']['implementation']['module']
        assert row['executor_role']


def test_contract_positions_restore_order_and_unpositioned_append():
    row = deepcopy(definitions.definitions()['columnar-analysis']['signature'])
    rows = {}
    for name, position in [('synthetic-first', 1), ('synthetic-second', 3), ('synthetic-new', None)]:
        item = deepcopy(row)
        item['implementation'].update(mode=name)
        item['implementation'].pop('dispatch_before', None)
        if position is None:
            item['implementation'].pop('dispatch_position', None)
        else:
            item['implementation']['dispatch_position'] = position
        rows[name] = item
    roles = dict.fromkeys(rows, 'analysis-author')
    assert definitions.populate_modes(('base-first', 'base-second', 'base-third'), rows, roles) == (
        'base-first', 'synthetic-first', 'base-second', 'synthetic-second', 'base-third', 'synthetic-new')
    rows['synthetic-first']['implementation']['dispatch_before'] = 'base-second'
    assert definitions.populate_modes(('base-second', 'base-third'), rows, roles)[:2] == (
        'synthetic-first', 'base-second')


def test_source_catalogue_preserves_current_dispatch_discovery():
    from ravel.workflow.capability_routing import catalogue
    from ravel.workflow.science import MODES
    catalog = catalogue()
    assert [row['mode'] for row in catalog['operations']] == list(MODES)
    assert all(row['status'] == 'source_present_not_admitted' for row in catalog['operations'])


def test_standalone_source_loader_preserves_chain_discovery():
    import importlib.util
    from ravel.workflow import capability_routing
    from ravel.workflow.science import MODES
    spec = importlib.util.spec_from_file_location('synthetic_standalone_catalogue', capability_routing.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert [row['mode'] for row in module.catalogue()['operations']] == list(MODES)


def test_new_contract_dispatches_without_central_registration(monkeypatch):
    from ravel.validation import validate_request_plan as rp
    from ravel.workflow import production_executor
    registry = deepcopy(rp.signatures())
    row = deepcopy(registry['columnar-analysis'])
    row['implementation'].update(mode='synthetic-operation', module='synthetic.adapter',
                                 presentation='present')
    row['implementation'].pop('dispatch_position', None)
    row['implementation'].pop('dispatch_before', None)
    registry['synthetic-operation'] = row
    executors = deepcopy(production_executor.executors())
    executors['operations']['synthetic-operation'] = 'analysis-author'
    monkeypatch.setattr(rp, 'signatures', lambda: registry)
    monkeypatch.setattr(production_executor, 'executors', lambda: executors)
    sentinel = object()
    module = SimpleNamespace(present=lambda result: (result, 'synthetic delivery'))
    original_import = definitions.importlib.import_module
    monkeypatch.setattr(definitions.importlib, 'import_module',
                        lambda name: module if name == 'synthetic.adapter' else original_import(name))
    assert definitions.definitions()['synthetic-operation']['signature'] is row
    assert definitions.adapter_for('synthetic-operation') is module
    assert definitions.presentation_for('synthetic-operation', sentinel) == (sentinel, 'synthetic delivery')
    module.present = None
    with pytest.raises(ValueError, match='presentation hook is not callable'):
        definitions.presentation_for('synthetic-operation', sentinel)
    from ravel.workflow.science import adapter
    assert adapter({'mode': 'synthetic-operation', 'task': {}}) is module
    # A fresh module load discovers the additional operation for CLI validation too.
    import importlib
    from ravel.workflow import science
    try:
        importlib.reload(science)
        assert 'synthetic-operation' in science.MODES
    finally:
        monkeypatch.undo()
        importlib.reload(science)


def test_missing_executor_is_refused():
    row = next(iter(definitions.definitions().values()))['signature']
    name = row['implementation']['mode']
    with pytest.raises(ValueError, match='executor role'):
        definitions.definitions({name: row}, {})


def test_partial_signature_table_retains_only_bound_legacy_dispatch():
    roles = dict.fromkeys(definitions.LEGACY_BINDINGS, 'analysis-author')
    rows = definitions.definitions({'synthetic-annotation': {'summary': 'Supplied annotation'}}, roles)
    assert set(rows) == set(definitions.LEGACY_BINDINGS)
    for name, row in rows.items():
        assert row['signature'] is None
        assert row['implementation'] == definitions.LEGACY_BINDINGS[name]
        assert not set(row['implementation']) & {'consumes', 'produces', 'basis', 'effects'}
    assert definitions.definitions({}, {'synthetic-operation': 'analysis-author'}) == {}
    assert definitions.definitions({}, roles, compatibility={}) == {}


@pytest.mark.parametrize('fault', ['kind', 'module', 'executor', 'group'])
def test_invalid_explicit_chain_declaration_never_uses_legacy_fallback(fault):
    row = deepcopy(definitions.definitions()['columnar-analysis']['signature'])
    roles = {'columnar-analysis': 'analysis-author'}
    if fault == 'kind':
        row['implementation']['kind'] = 'command'
    elif fault == 'module':
        row['implementation']['module'] = ''
    elif fault == 'executor':
        roles = {}
    else:
        row['implementation']['dispatch_group'] = 'synthetic-invalid'
    with pytest.raises(ValueError):
        definitions.definitions({'columnar-analysis': row}, roles)


def test_compatibility_and_default_presentation_remain():
    from ravel.workflow.science import adapter
    from ravel.physics.science_worker import diagnostic_presentation
    assert adapter({'mode': 'quantities', 'task': {}}).__name__ == 'ravel.physics.quantities'
    assert diagnostic_presentation('columnar-analysis', {}) == ({}, '')
    assert diagnostic_presentation('signal-template', {}) == ({}, '')


def test_generated_event_presentation_preserves_refusal():
    from ravel.physics.science_worker import diagnostic_presentation
    result = {'status_scope': 'source_bound_generated_event_delivery',
              'physics_validated': False, 'generated_events': 7}
    fields, summary = diagnostic_presentation('model-events', result)
    assert fields == {'status_scope': result['status_scope'], 'generated_events': 7}
    assert summary.startswith('Complete source-bound generated-event and signed multiweight delivery.')
    for bad in ({**result, 'physics_validated': True}, {**result, 'status_scope': 'synthetic'},
                {k: v for k, v in result.items() if k != 'physics_validated'}):
        with pytest.raises(ValueError, match='physics certification'):
            diagnostic_presentation('model-events', bad)


@pytest.mark.parametrize('implementation', [None, [], 'synthetic'])
def test_malformed_implementation_is_refused(implementation):
    with pytest.raises(ValueError, match='implementation must be an object'):
        definitions.definitions({'synthetic-operation': {'implementation': implementation}}, {}, compatibility={})


@pytest.mark.parametrize('module', ['/outside/synthetic_adapter', ['synthetic.adapter'], 7])
def test_unregistered_explicit_chain_requires_module_name(module):
    row = {'implementation': {'kind': 'science-mode', 'mode': 'synthetic-operation',
                             'dispatch_group': definitions.GROUP, 'module': module}}
    with pytest.raises(ValueError, match='dotted Python module name') as caught:
        definitions.definitions({'synthetic-operation': row},
                                {'synthetic-operation': 'synthetic-role'}, compatibility={})
    assert caught.value.field == 'operations.synthetic-operation.implementation.module'
    assert caught.value.expected == 'dotted Python module name'
    assert caught.value.observed and caught.value.repair


@pytest.mark.parametrize('position', [[], {}, True, -1, 1.5])
def test_unregistered_explicit_chain_refuses_malformed_position(position):
    row = {'implementation': {'kind': 'science-mode', 'mode': 'synthetic-operation',
                             'dispatch_group': definitions.GROUP, 'module': 'synthetic.adapter',
                             'dispatch_position': position}}
    with pytest.raises(ValueError, match='nonnegative integer') as caught:
        definitions.definitions({'synthetic-operation': row},
                                {'synthetic-operation': 'synthetic-role'}, compatibility={})
    assert caught.value.field == 'operations.synthetic-operation.implementation.dispatch_position'
    assert caught.value.expected == 'nonnegative integer'
    assert caught.value.observed and caught.value.repair


@pytest.mark.parametrize('position', [[], {}])
def test_compatibility_position_refuses_before_identity_comparison(position):
    with pytest.raises(ValueError, match='nonnegative integers'):
        definitions.populate_modes((), {}, {'synthetic-operation': 'synthetic-role'},
                                   compatibility={'synthetic-operation': {
                                       'module': 'synthetic.adapter', 'dispatch_position': position}})
