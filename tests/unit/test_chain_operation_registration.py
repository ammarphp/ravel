"""Closed opt-in contracts and deterministic projections; synthetic inputs only."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.workflow import operation_definitions as definitions
from ravel.workflow import operation_registration as registration
from test_chain_discovery_projection import signature


@pytest.mark.parametrize('field', ['executor', 'descriptor', 'setup_groups', 'documentation', 'curation'])
def test_missing_registration_property_is_located(field):
    row = signature()
    del row['registration'][field]
    with pytest.raises(ValueError) as caught:
        registration.registered_rows({'synthetic-operation': row})
    text = str(caught.value)
    assert field in text
    assert all(label in text for label in ('field=', 'observed=', 'expected=', 'repair='))


@pytest.mark.parametrize('fault', ['extra', 'nonfinite', 'wrong-example', 'wrong-group',
                                  'unknown-general', 'unsafe-doc', 'blank', 'module-path',
                                  'null-implementation', 'position-bool'])
def test_invalid_registration_refuses_before_projection(fault):
    row = signature()
    value = row['registration']
    if fault == 'extra':
        value['qualification'] = 'accepted'
    elif fault == 'nonfinite':
        value['curation']['examples'][0]['spec']['task']['value'] = float('inf')
    elif fault == 'wrong-example':
        value['curation']['examples'][0]['spec']['mode'] = 'other'
    elif fault == 'wrong-group':
        row['implementation']['dispatch_group'] = 'other'
    elif fault == 'unknown-general':
        value['descriptor']['applicability'] = {'scope': 'source-bound', 'bound_to': 'synthetic source',
            'select_when': [['synthetic']], 'general_operation': 'missing'}
    elif fault == 'unsafe-doc':
        value['documentation'][0]['path'] = 'docs/../other.md'
    elif fault == 'blank':
        value['curation']['use_when'] = ['   ']
    elif fault == 'module-path':
        row['implementation']['module'] = '/outside/synthetic_adapter'
    elif fault == 'null-implementation':
        row['implementation'] = None
    else:
        row['implementation']['dispatch_position'] = True
    with pytest.raises(ValueError, match='field=.*observed=.*expected=.*repair='):
        registration.executor_document({'operations': {}}, {'synthetic-operation': row})


def test_projection_is_deterministic_and_never_changes_authority():
    rows = {'synthetic-operation': signature()}
    source = {'operations': {}, 'host_operations': {}, 'budgets': {'value': 7}}
    before = deepcopy(source)
    first = registration.executor_document(source, rows)
    assert registration.executor_document(first, rows) == first
    assert source == before and first['budgets'] == before['budgets']
    assert set(first) == set(source)
    source['host_operations']['synthetic-operation'] = 'host reason'
    with pytest.raises(ValueError, match='production-only'):
        registration.executor_document(source, rows)


@pytest.mark.parametrize('key', ['setup_groups', 'documentation'])
def test_duplicate_registration_entries_refuse_in_signature_loader(key, monkeypatch):
    from ravel.validation import validate_request_plan as plans
    row = signature()
    # Use a complete signature so this exercises the supported schema dialect
    # and the additional identity check through the ordinary cached reader.
    full = deepcopy(plans.signatures()['columnar-analysis'])
    full['implementation'] = row['implementation']
    full['registration'] = row['registration']
    full['registration'][key].append(deepcopy(full['registration'][key][0]))
    document = {'schema_version': 1, 'kind': 'operation-signatures', 'scope': 'synthetic',
                'operations': {'synthetic-operation': full}}
    monkeypatch.setattr(plans, '_signature_document', lambda: document)
    plans._checked_signatures.cache_clear()
    try:
        with pytest.raises(ValueError, match=key + '.*distinct entries'):
            plans.signatures()
    finally:
        plans._checked_signatures.cache_clear()


@pytest.mark.parametrize('anchor_only', [False, True])
def test_manifest_and_dispatch_orders_match_for_reversed_contract_order(anchor_only):
    rows = {}
    for name, position in [('synthetic-late', 2), ('synthetic-early', 0)]:
        row = signature(name=name)
        row['implementation']['dispatch_position'] = position
        rows[name] = row
    if anchor_only:
        del rows['synthetic-late']['implementation']['dispatch_position']
        rows['synthetic-late']['implementation']['dispatch_before'] = 'a'
    base = ['a', 'b', 'c']
    document = {'groups': [{'id': 'synthetic-group'}],
                'operations': [{'mode': name, 'groups': []} for name in base]}
    projected = registration.manifest_document(document, rows)
    assert [row['mode'] for row in projected['operations']] == list(
        definitions.populate_modes(base, rows, {}, compatibility={}))


@pytest.mark.parametrize('case', ['duplicate', 'nonfinite', 'dangling-link', 'ancestor-link'])
def test_source_reader_refuses_ambiguous_or_foreign_bytes(tmp_path, case):
    path = tmp_path / 'operation_signatures.json'
    if case == 'duplicate':
        path.write_text('{"operations": {}, "operations": {}}')
    elif case == 'nonfinite':
        path.write_text('{"operations": {"synthetic": {"value": NaN}}}')
    elif case == 'dangling-link':
        path.symlink_to(tmp_path / 'missing.json')
    else:
        target = tmp_path / 'target'
        target.mkdir()
        (target / path.name).write_text(json.dumps({'operations': {}}))
        link = tmp_path / 'link'
        link.symlink_to(target, target_is_directory=True)
        path = link / path.name
    with pytest.raises(ValueError, match='field=.*observed=.*expected=.*repair='):
        registration.read_signatures(path)


def test_setup_projection_keeps_the_standard_library_bootstrap(tmp_path):
    row = signature()
    source = Path(__file__).resolve().parents[2] / 'src'
    script = f'''import sys
sys.path.insert(0, {str(source)!r})
from ravel.workflow.operation_registration import manifest_document
from ravel.setup.manifest import load
document = {{'groups': [{{'id': 'synthetic-group'}}], 'operations': []}}
rows = {{'synthetic-operation': {row!r}}}
assert manifest_document(document, rows)['operations'][0]['groups'] == ['synthetic-group']
load({str(source.parent)!r})
assert 'jsonschema' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-S', '-B', '-c', script], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('key,value,location', [
    ('module', '/outside/synthetic_adapter', 'module'),
    ('dispatch_position', [], 'dispatch_position'),
    ('mode', 'synthetic-other', ''),
    ('kind', 'synthetic-kind', ''),
])
def test_declared_implementation_diagnostics_match_registration_presence(key, value, location):
    row = signature()
    row['implementation'][key] = value
    expected_field = 'operations.synthetic-operation.implementation' + ('.' + location if location else '')
    errors = []
    for registered in (True, False):
        candidate = deepcopy(row)
        if not registered:
            candidate.pop('registration')
        with pytest.raises(ValueError) as caught:
            definitions.definitions({'synthetic-operation': candidate},
                                    {'synthetic-operation': 'analysis-author'}, compatibility={})
        error = caught.value
        assert error.field == expected_field
        assert error.observed and error.expected and error.repair
        errors.append((error.field, error.observed, error.expected, error.repair))
    assert errors[0] == errors[1]
