"""Set equalities of the non-compliance suite: catalogue = coverage = bindings; installed = parameterized.

The bindings file is derived (``scripts/maintenance/build_case_bindings.py``); these tests keep it
current and complete. A new role, operation, executor, mode, gate, step, stage, check-in kind or
route without a coverage row fails here, and so does a declared case that does not exist.
"""
from __future__ import annotations

import collections
import importlib.util
import json
from pathlib import Path

import pytest

import nc_cases
from nc_audit import pending_rows

BUILDER = nc_cases.ROOT / 'scripts' / 'maintenance' / 'build_case_bindings.py'


def _builder():
    spec = importlib.util.spec_from_file_location('nc_build_case_bindings', BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bindings_file_is_current_with_the_declared_cases():
    builder = _builder()
    document = nc_cases.bindings()
    rebuilt = builder.build(builder._embedded_rows(document), builder.scan_cases())
    assert builder.render(rebuilt) == nc_cases.BINDINGS_PATH.read_text(), (
        'case-bindings.json is stale: run python3 scripts/maintenance/build_case_bindings.py')


def test_every_coverage_row_has_exactly_one_binding():
    document = nc_cases.bindings()
    bespoke = [row['id'] for row in document['bespoke']]
    parameterized = list(document['parameterized'])
    assert len(set(bespoke)) == len(bespoke)
    assert not set(bespoke) & set(parameterized)
    assert len(bespoke) + len(parameterized) == document['coverage']['rows']
    assert set(document['parameterized'].values()) == set(document['groups'])
    for row in document['bespoke']:
        assert nc_cases.ROW_ID.match(row['id']), row['id']
        assert row['mechanisms'] and row['class'] in 'ELRI' and row['node'] and row['builder'], row['id']
        assert row['spec'], row['id']
    for gid, group in document['groups'].items():
        assert group['dimension'] in nc_cases.DIMENSIONS, gid
        assert group['mechanisms'] and group['class'] in 'ELRI' and group['spec'], gid


def test_bespoke_population_is_the_specified_one():
    kinds = collections.Counter(row['source_kind'] for row in nc_cases.bindings()['bespoke'])
    assert kinds == {'census-decision': 160, 'xreview-switch': 41, 'unread-card-field': 14,
                     'cross-family-removal': 8, 'spec-obligation': 33}


def test_every_coverage_row_has_an_implemented_case():
    pending = pending_rows(nc_cases.bindings())
    assert not pending, f'coverage rows without an implemented case ({len(pending)}): {pending}'


def test_catalogue_equals_coverage_equals_bindings():
    """The catalogue and the bindings name the same rows and were built from the same coverage table.

    The coverage table itself is not shipped; both documents record its digest and row count.
    ``build_case_bindings.py --check --coverage <coverage.csv>`` verifies the bindings against it.
    """
    rows = set(nc_cases.binding_rows())
    path = nc_cases.catalogue_path()
    assert path.is_file(), f'obligation catalogue is missing; catalogue equality cannot be established: {path}'
    assert set(_builder()._catalogue_ids(path)) == rows
    catalogue = json.loads(path.read_text())
    if path.name == 'obligation-catalogue.peer.json':
        assert not nc_cases.controller_installed()
        assert catalogue['kind'] == 'test-peer-catalogue' and catalogue['evidence_scope'] == 'peer-fake'
        recorded = {'sha256': catalogue['coverage_sha256'], 'rows': len(catalogue['rows'])}
    else:
        recorded = catalogue['inputs']['coverage']
    coverage = nc_cases.bindings()['coverage']
    assert recorded['sha256'] == coverage['sha256'], 'catalogue and bindings come from different coverage tables'
    assert recorded['rows'] == coverage['rows'] == len(rows)


def test_catalogue_preserves_each_ledger_class_and_mechanism_population():
    document = json.loads(nc_cases.catalogue_path().read_text())
    rows = document['rows']
    by_id = {row['id']: row for row in rows}
    assert len(rows) == len(by_id)
    for identifier, binding in nc_cases.binding_rows().items():
        row = by_id[identifier]
        assert row['class'] == binding['class'], identifier
        assert row['ledger_class'] == binding['ledger_class'], identifier
        assert set(row['mechanisms']) == set(binding['mechanisms']), identifier


@pytest.mark.parametrize('dimension', nc_cases.DIMENSIONS)
def test_installed_population_equals_the_parameterized_bindings(dimension):
    bound = {row for row, gid in nc_cases.bindings()['parameterized'].items()
             if nc_cases.bindings()['groups'][gid]['dimension'] == dimension}
    installed = set(nc_cases.dimension_rows(dimension))
    assert installed - bound == set(), f'{dimension} rows without a coverage row: {sorted(installed - bound)[:20]}'
    stale = bound - installed - nc_cases.withheld_rows()  # a release's withheld operations have no installed row
    assert stale == set(), f'{dimension} coverage rows absent from the installed data: {sorted(stale)[:20]}'


def test_every_role_row_resolves_to_its_effective_card():
    rows = [row for row in nc_cases.bindings()['parameterized'] if row.startswith('ROLE-')]
    for row in rows:
        card, field, index = nc_cases.role_row(row)
        if field in nc_cases.ROLE_LIST_FIELDS:
            assert 0 <= index < len(card[field]), row
        elif field in nc_cases.ROLE_SCALAR_FIELDS:
            assert field in card, row


def _declared():
    """(bespoke row -> test, (dimension, field) -> tests) from the declarations, by parsing."""
    return _builder().scan_cases()


def test_declared_cases_are_the_registered_cases():
    bespoke, parameterized = _declared()
    document = nc_cases.bindings()
    implemented = {row['id']: row['test'] for row in document['bespoke'] if row['status'] == 'implemented'}
    assert {row: bound['test'] for row, bound in bespoke.items()} == implemented
    groups = {(g['dimension'], g['field']) for g in document['groups'].values() if g['status'] == 'implemented'}
    assert set(parameterized) == groups


def test_case_modules_import_and_register_exactly_their_declarations():
    bespoke, parameterized = _declared()
    for path in sorted(Path(nc_cases.ROOT / 'tests' / 'unit' / 'enforcement').glob('test_nc_*.py')):
        name = path.stem
        if name in ('test_nc_bindings', 'test_nc_mutation_adequacy'):
            continue
        importlib.import_module(name)
    registered = {row: f'tests/unit/enforcement/{case.func.__module__}.py::{case.name}'
                  for row, case in nc_cases.CASES.items() if not case.dimension}
    assert registered == {row: bound['test'] for row, bound in bespoke.items()}
    dims = {(case.dimension, field) for case in nc_cases.CASES.values() if case.dimension
            for field in (case.fields or (None,))}
    assert dims == set(parameterized)
