"""Case registry of the non-compliance suite: every obligation row is bound to one case.

The suite proves that the controller refuses or labels each obligation's violation against an
inert adversary (a scripted worker, a hostile authored script, an operator-path negative or a
host-side fixture). Nothing here calls a model, a provider or the network.

Row population. ``tests/fixtures/enforcement/case-bindings.json`` holds one binding per row of
the controller coverage table (``scripts/maintenance/build_case_bindings.py`` writes it from that
table and from the ``@case`` declarations in the ``test_nc_*`` modules). Bespoke rows (decisions,
switches, card fields, family removals, controller duties) each name one test; structural and role
rows are parameterized cases enumerated here from the installed registry and package data, so a
new role, operation or gate without a coverage row fails ``test_nc_bindings``.

Bindings. A case declares what it runs against:

- ``INSTALLED``: guards that exist in the installed RAVEL today (inner guards, the broker and its
  toolbelt, the worker sandbox, the dispatcher). These run in every tree.
- ``CONTROLLER``: the controller interfaces (``ravel.controller``). Before the controller package
  is installed these cases end with the declared skip reason ``pending-integration:``; once it is
  installed every such case must run, and a missing interface is a failure.

A case function takes one argument, the ``nc`` fixture (``nc_env.Env``), so the mutation-adequacy
test can call it again under a disabled mechanism and require an oracle failure. A case's oracle
is written in the test (expected refusal, ledger event, receipt reason, effect count, bytes); it is
never computed by calling the mechanism under test.
"""
from __future__ import annotations

from functools import lru_cache
import importlib
import importlib.util
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'enforcement'
BINDINGS_PATH = FIXTURES / 'case-bindings.json'

INSTALLED = 'installed'
CONTROLLER = 'controller'
BINDINGS = (INSTALLED, CONTROLLER)

# Declared skip reasons. Anything else is an unexpected skip, which the strict hook in this
# directory's conftest turns into a failure.
PENDING_INTEGRATION = 'pending-integration:'
SANDBOX_BLOCKED = 'sandbox-blocked:'

ROW_ID = re.compile(r'\A[A-Z]+(?:[0-9]+|-[A-Za-z0-9_.:-]+)\Z')
BESPOKE_PREFIXES = ('R', 'I', 'A', 'T', 'V', 'P', 'B', 'D', 'L', 'G', 'C', 'E', 'EG', 'SW', 'CF', 'XF', 'JR', 'CT')
DIMENSIONS = ('ROLE', 'TOOL', 'EXEC', 'HOST', 'MODE', 'GATE', 'STEP', 'STAGE', 'CHECKIN', 'ROUTE')
# Card fields the coverage rows enumerate: scalar fields have one row, list fields one row per item,
# and every role has the two synthetic rows ``dispatch`` and ``identity``.
ROLE_SCALAR_FIELDS = ('id', 'family', 'purpose', 'model', 'independence', 'knowledge', 'output', 'ownership',
                      'requires', 'sees', 'stop', 'tools')
ROLE_LIST_FIELDS = ('protocol', 'operations', 'must_check', 'escalation', 'reviewed_by')
ROLE_SYNTHETIC_FIELDS = ('dispatch', 'identity')
ROLE_FIELDS = ROLE_SCALAR_FIELDS + ROLE_LIST_FIELDS + ROLE_SYNTHETIC_FIELDS
# The check-in kinds of the census; the installed obligation catalogue, once present, is authoritative.
CHECKIN_KINDS = ('1', '2', '3', 'deviation', 'escalation', 'final')

CASES: dict[str, 'Case'] = {}


class Case:
    """One registered case: the rows it closes, what it binds to, and its function."""

    def __init__(self, rows, func, binding, dimension=None, fields=()):
        self.rows = tuple(rows)
        self.func = func
        self.binding = binding
        self.dimension = dimension
        self.fields = tuple(fields)
        self.name = func.__name__

    def __repr__(self):
        return f'Case({self.name}, rows={self.rows}, binding={self.binding})'


@lru_cache(maxsize=1)
def bindings() -> dict:
    return json.loads(BINDINGS_PATH.read_text())


# The dimensions whose rows name an operation, the only rows a release can withhold.
OPERATION_DIMENSIONS = ('TOOL', 'EXEC', 'HOST', 'MODE')


@lru_cache(maxsize=1)
def withheld_rows() -> frozenset:
    """Rows the bindings carry for operations the release withholds.

    The bindings are written from the source population. A distributed tree offers the operations
    of the groups it ships, so a row of an operation dimension that its installed registries no
    longer hold is bound to an operation the release withholds; such rows have no case to run.
    Every other dimension, and every source checkout, has none."""
    from ravel import evidence_layout
    if not evidence_layout.is_public_tree(ROOT):
        return frozenset()
    stale = set(bindings()['parameterized']) - installed_population()
    return frozenset(row for row in stale if row.split('-', 1)[0] in OPERATION_DIMENSIONS)


def collection_bindings() -> dict:
    """The bindings the collected cases are checked against: those of the installed population."""
    document = bindings()
    held = withheld_rows()
    if not held:
        return document
    return dict(document, parameterized={row: group for row, group in document['parameterized'].items()
                                         if row not in held})


@lru_cache(maxsize=1)
def binding_rows() -> dict:
    """Row id -> binding entry (groups expanded)."""
    document = bindings()
    groups = document['groups']
    rows = {}
    for row in document['bespoke']:
        rows[row['id']] = row
    for row_id, group in document['parameterized'].items():
        rows[row_id] = dict(groups[group], id=row_id, group=group)
    return rows


def controller_installed() -> bool:
    """True once the controller package is importable from the installed RAVEL."""
    return importlib.util.find_spec('ravel.controller') is not None


def catalogue_path():
    from ravel.paths import package_data_path
    return package_data_path('obligations', 'catalogue.json')


def case(*rows, binding=INSTALLED):
    """Register a bespoke case closing ``rows``; the test function's name carries the first row id."""
    if binding not in BINDINGS:
        raise ValueError(f'unknown binding {binding!r}')
    if not rows:
        raise ValueError('a case closes at least one row')

    def register(func):
        known = binding_rows()
        for row in rows:
            if not ROW_ID.match(row):
                raise ValueError(f'malformed row id {row!r}')
            if row not in known:
                raise ValueError(f'{func.__name__}: row {row} has no binding in {BINDINGS_PATH.name}')
            if row in CASES:
                raise ValueError(f'row {row} is closed twice: {CASES[row].name} and {func.__name__}')
        if f'_{rows[0]}_' not in f'_{func.__name__.removeprefix("test_")}_':
            raise ValueError(f'{func.__name__} must be named after its row id {rows[0]}')
        entry = Case(rows, func, binding)
        for row in rows:
            CASES[row] = entry
        marked = pytest.mark.nc_case(rows=rows, binding=binding)(func)
        return marked
    return register


def dimension_case(dimension, *fields, binding=INSTALLED):
    """Register a parameterized case over ``dimension`` (and, for roles, the named card fields).

    The decorated test must be parametrized with ``row`` over ``dimension_rows(dimension, fields)``.
    """
    if dimension not in DIMENSIONS:
        raise ValueError(f'unknown dimension {dimension!r}')
    if dimension == 'ROLE' and (not fields or set(fields) - set(ROLE_FIELDS)):
        raise ValueError(f'role cases name card fields from {ROLE_FIELDS}')

    def register(func):
        entry = Case((), func, binding, dimension=dimension, fields=fields)
        CASES[f'{dimension}:{",".join(fields) or "*"}:{func.__name__}'] = entry
        return pytest.mark.nc_case(dimension=dimension, fields=fields, binding=binding)(func)
    return register


def require_controller(*modules):
    """Import the named ``ravel.controller`` modules for a CONTROLLER case.

    Before integration (no controller package installed) the case ends with the declared skip;
    once the package is installed, a missing module is an error, never a skip.
    """
    if not controller_installed():
        pytest.skip(f'{PENDING_INTEGRATION} ravel.controller is not installed in this tree')
    loaded = []
    for name in modules:
        loaded.append(importlib.import_module(f'ravel.controller.{name}' if name else 'ravel.controller'))
    return loaded[0] if len(loaded) == 1 else tuple(loaded)


# ------------------------------------------------------------------ installed-data enumeration

@lru_cache(maxsize=1)
def _cards():
    from ravel.workflow import role_registry
    return tuple(role_registry.all_cards())


def role_rows(fields=ROLE_FIELDS):
    """Role row ids of the effective registry for ``fields``, exactly as the coverage table names them."""
    rows = []
    for card in _cards():
        role = card['id']
        for field in fields:
            if field in ROLE_SYNTHETIC_FIELDS:
                rows.append(f'ROLE-{role}-{field}')
            elif field in ROLE_SCALAR_FIELDS:
                if field in card:
                    rows.append(f'ROLE-{role}-{field}')
            elif field in ROLE_LIST_FIELDS:
                rows.extend(f'ROLE-{role}-{field}-{i}' for i, _ in enumerate(card.get(field) or ()))
            else:
                raise ValueError(f'unknown role field {field!r}')
    return rows


def role_row(row):
    """``(card, field, index)`` of a role row id; ``index`` is None for scalar and synthetic fields."""
    for card in sorted(_cards(), key=lambda c: len(c['id']), reverse=True):
        prefix = f'ROLE-{card["id"]}-'
        if not row.startswith(prefix):
            continue
        rest = row[len(prefix):]
        for field in ROLE_FIELDS:
            if rest == field:
                return card, field, None
            if rest.startswith(field + '-') and field in ROLE_LIST_FIELDS:
                return card, field, int(rest[len(field) + 1:])
    raise KeyError(row)


def _package_json(*parts):
    from ravel.paths import package_data_path
    return json.loads(package_data_path(*parts).read_text())


def dimension_keys(dimension):
    """The installed population of a structural dimension (without the ``<DIM>-`` prefix)."""
    if dimension == 'TOOL':
        return sorted(_package_json('operation_signatures.json')['operations'])
    if dimension == 'EXEC':
        return sorted(_package_json('roles', 'executors.json')['operations'])
    if dimension == 'HOST':
        return sorted(_package_json('roles', 'executors.json')['host_operations'])
    if dimension == 'MODE':
        return sorted(_package_json('mode_descriptors.json')['modes'])
    if dimension == 'GATE':
        from ravel.workflow import decision_gate
        return list(decision_gate.GATES)
    if dimension == 'STAGE':
        return [stage['id'] for stage in _package_json('research', 'protocol-default.json')['stages']]
    if dimension == 'STEP':
        return sorted(p.stem for p in (ROOT / 'docs' / 'workflow' / 'steps').glob('*.md'))
    if dimension == 'ROUTE':
        from ravel.validation.validate_task_contract import TASK_MODES
        return list(TASK_MODES)
    if dimension == 'CHECKIN':
        path = catalogue_path()
        if path.is_file():
            ids = [row['id'] for row in _catalogue_rows(path)]
            return sorted(i.split('-', 1)[1] for i in ids if i.startswith('CHECKIN-'))
        return list(CHECKIN_KINDS)
    raise ValueError(f'unknown dimension {dimension!r}')


def _catalogue_rows(path):
    document = json.loads(Path(path).read_text())
    rows = document.get('rows', document.get('obligations', document)) if type(document) is dict else document
    if type(rows) is dict:
        rows = [dict(value, id=key) for key, value in rows.items()]
    return rows


def dimension_rows(dimension, fields=()):
    if dimension == 'ROLE':
        return role_rows(fields or ROLE_FIELDS)
    return [f'{dimension}-{key}' for key in dimension_keys(dimension)]


def installed_population():
    """Every parameterized row id derivable from the installed registry and package data."""
    rows = set(role_rows())
    for dimension in DIMENSIONS[1:]:
        rows.update(dimension_rows(dimension))
    return rows
