#!/usr/bin/env python3
"""Build the non-compliance case bindings: one binding per obligation row of the coverage table.

    python3 scripts/maintenance/build_case_bindings.py --coverage <coverage.csv>   # rebuild the row table
    python3 scripts/maintenance/build_case_bindings.py                            # refresh statuses only
    python3 scripts/maintenance/build_case_bindings.py --check                    # exit 1 when stale

Inputs. The coverage table (``coverage.csv`` of the controller specification; every obligation
row with its ledger class, mechanisms, class, discharging node, building package, case binding and
canary). Without ``--coverage`` the rows embedded in the current bindings file are reused. The
installed obligation catalogue (``src/ravel/data/obligations/catalogue.json``) is required; its id
set must equal the coverage id set, else the build fails. ``--refresh-census INPUT --census-out
OUTPUT`` appends missing installed ROLE/TOOL/EXEC/HOST declarations. Existing records remain
unchanged unless ``--census-migrations PATH`` explicitly authorizes a stale EXEC-to-HOST migration.

Cases. The ``@case(...)`` and ``@dimension_case(...)`` declarations of
``tests/unit/enforcement/test_nc_*.py`` are read by parsing, never by importing: a bespoke row is
``implemented`` when one declaration lists it, and a parameterized row when a declaration covers
its dimension (and, for role rows, its card field). Every other row stays ``pending`` with its
planned case text, so the file reports exactly which cases exist.

Output: ``tests/fixtures/enforcement/case-bindings.json`` (bespoke rows in full; parameterized rows
grouped by dimension, field, node pattern, mechanisms, class and builder). Standard library only.
"""
from __future__ import annotations

import argparse
import ast
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'tests' / 'fixtures' / 'enforcement' / 'case-bindings.json'
CASE_DIR = ROOT / 'tests' / 'unit' / 'enforcement'
CATALOGUE = ROOT / 'src' / 'ravel' / 'data' / 'obligations' / 'catalogue.json'
SCHEMA_VERSION = 1
BESPOKE_KINDS = ('census-decision', 'xreview-switch', 'spec-obligation', 'unread-card-field',
                 'cross-family-removal')
PARAMETERIZED_KINDS = ('census-role-field', 'census-structural')
DIMENSIONS = ('ROLE', 'TOOL', 'EXEC', 'HOST', 'MODE', 'GATE', 'STEP', 'STAGE', 'CHECKIN', 'ROUTE')
BINDINGS = {'INSTALLED': 'installed', 'CONTROLLER': 'controller'}
ROLE_FIELDS = ('id', 'family', 'purpose', 'model', 'independence', 'knowledge', 'output', 'ownership',
               'requires', 'sees', 'stop', 'tools', 'protocol', 'operations', 'must_check', 'escalation',
               'reviewed_by', 'dispatch', 'identity')
ROLE_LIST_FIELDS = ('protocol', 'operations', 'must_check', 'escalation', 'reviewed_by')


class BuildError(Exception):
    pass


def _split(value):
    return [item for item in str(value or '').split() if item]


def _role_parts(row_id):
    """``(role, field)`` of a role row id, read from its end: ``ROLE-<role>-<field>[-<n>]``."""
    for field in sorted(ROLE_FIELDS, key=len, reverse=True):
        suffix = r'-\d+' if field in ROLE_LIST_FIELDS else ''
        match = re.fullmatch(r'ROLE-(.+)-' + re.escape(field) + suffix, row_id)
        if match:
            return match.group(1), field
    raise BuildError(f'{row_id}: unknown card field')


def _template(text, key, placeholder):
    return re.sub(r'(?<![A-Za-z0-9_-])' + re.escape(key) + r'(?![A-Za-z0-9_])', placeholder, text)


def read_coverage(path):
    path = Path(path)
    data = path.read_bytes()
    rows = []
    with path.open(newline='') as handle:
        for raw in csv.DictReader(handle):
            kind = raw['source_kind']
            row = {'id': raw['row_id'], 'source_kind': kind, 'ledger_class': raw['ledger_class'],
                   'class': raw['class_1_3_0'], 'mechanisms': _split(raw['mechanisms']), 'node': raw['graph_node'],
                   'builder': raw['package'], 'canary': _split(raw['canary']), 'spec': raw['test_idea']}
            if kind not in BESPOKE_KINDS + PARAMETERIZED_KINDS:
                raise BuildError(f'{row["id"]}: unknown source kind {kind!r}')
            rows.append(row)
    ids = [row['id'] for row in rows]
    if len(set(ids)) != len(ids):
        raise BuildError('coverage table repeats a row id')
    return {'sha256': hashlib.sha256(data).hexdigest(), 'rows': rows}


def _embedded_rows(document):
    """The coverage rows a previous build embedded (statuses dropped; parameterized specs stay templated)."""
    keep = ('id', 'source_kind', 'ledger_class', 'class', 'mechanisms', 'node', 'builder', 'canary', 'spec')
    rows = [{k: row[k] for k in keep} for row in document['bespoke']]
    groups = document['groups']
    for row_id, gid in document['parameterized'].items():
        group = groups[gid]
        key = _role_parts(row_id)[0] if group['dimension'] == 'ROLE' else row_id.split('-', 1)[1]
        rows.append({'id': row_id, 'source_kind': group['source_kind'], 'ledger_class': group['ledger_class'],
                     'class': group['class'], 'mechanisms': list(group['mechanisms']),
                     'node': group['node'].replace('[*]', f'[{key}]'), 'builder': group['builder'],
                     'canary': list(group['canary']), 'spec': group['spec'], 'templated': True})
    return {'sha256': document['coverage']['sha256'], 'rows': rows}


def _constant_strings(nodes):
    values = []
    for node in nodes:
        if isinstance(node, ast.Constant) and type(node.value) is str:
            values.append(node.value)
        else:
            raise BuildError(f'case declaration argument at line {node.lineno} is not a string literal')
    return values


def _binding(call):
    for keyword in call.keywords:
        if keyword.arg != 'binding':
            continue
        value = keyword.value
        name = value.attr if isinstance(value, ast.Attribute) else value.id if isinstance(value, ast.Name) else None
        if name in BINDINGS:
            return BINDINGS[name]
        if isinstance(value, ast.Constant) and value.value in BINDINGS.values():
            return value.value
        raise BuildError(f'binding at line {call.lineno} is not INSTALLED or CONTROLLER')
    return 'installed'


def _decorator_name(node):
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None


def scan_cases(case_dir=CASE_DIR, root=ROOT):
    """Bespoke row -> case, and (dimension, field) -> cases, from the case modules' declarations."""
    bespoke, parameterized = {}, {}
    for path in sorted(Path(case_dir).glob('test_nc_*.py')):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                name = _decorator_name(decorator)
                test = f'{relative}::{node.name}'
                if name not in ('case', 'dimension_case'):
                    continue
                if isinstance(node, ast.AsyncFunctionDef) or not node.name.startswith('test_'):
                    raise BuildError(f'{test}: case declarations require a synchronous test function')
                keywords = [keyword.arg for keyword in decorator.keywords]
                if any(key != 'binding' for key in keywords) or len(keywords) != len(set(keywords)):
                    raise BuildError(f'{test}: case declaration has unknown or duplicate keywords')
                if not decorator.args:
                    raise BuildError(f'{test}: empty {name} declaration')
                if name == 'case':
                    rows = _constant_strings(decorator.args)
                    for row in rows:
                        if row in bespoke:
                            raise BuildError(f'row {row} is closed twice: {bespoke[row]["test"]} and {test}')
                        bespoke[row] = {'test': test, 'binding': _binding(decorator)}
                elif name == 'dimension_case':
                    values = _constant_strings(decorator.args)
                    dimension, fields = values[0], values[1:] or [None]
                    if dimension not in DIMENSIONS:
                        raise BuildError(f'{test}: unknown dimension {dimension!r}')
                    if dimension == 'ROLE' and any(field not in ROLE_FIELDS for field in fields):
                        raise BuildError(f'{test}: role cases require known card fields')
                    if dimension != 'ROLE' and fields != [None]:
                        raise BuildError(f'{test}: only ROLE cases name card fields')
                    for field in fields:
                        key = (dimension, field)
                        if key in parameterized:
                            raise BuildError(f'{test}: dimension {dimension}:{field} is declared twice')
                        parameterized[key] = [{'test': test, 'binding': _binding(decorator)}]
    return bespoke, parameterized


def _catalogue_ids(path):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BuildError(f'obligation catalogue repeats key {key!r}')
            result[key] = value
        return result

    try:
        document = json.loads(Path(path).read_text(), object_pairs_hook=unique_object)
    except json.JSONDecodeError as exc:
        raise BuildError(f'malformed obligation catalogue: {exc}') from exc
    if type(document) is dict and (document.get('kind') == 'test-peer-catalogue'
                                  or document.get('evidence_scope') == 'peer-fake'):
        raise BuildError('a test-peer catalogue cannot establish production coverage')
    mapped = False
    if type(document) is dict:
        if 'rows' in document:
            rows = document['rows']
        elif 'obligations' in document:
            rows = document['obligations']
            mapped = type(rows) is dict
        else:
            raise BuildError('obligation catalogue requires rows or obligations')
    else:
        rows = document
    if not mapped and type(rows) is not list:
        raise BuildError('obligation catalogue rows must be a list')
    ids = set()
    entries = rows.items() if mapped else ((None, row) for row in rows)
    for key, row in entries:
        if type(row) is not dict:
            raise BuildError('obligation catalogue row must be a mapping')
        row_id = key if mapped else row.get('id')
        if type(row_id) is not str or not row_id.strip():
            raise BuildError('obligation catalogue row requires a nonempty string id')
        if mapped and 'id' in row and row['id'] != row_id:
            raise BuildError(f'obligation catalogue id differs from key {row_id!r}')
        if row_id in ids:
            raise BuildError(f'obligation catalogue repeats id {row_id!r}')
        ids.add(row_id)
    return ids


def build(coverage, cases, *, catalogue=None):
    rows = coverage['rows']
    ids = [row['id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise BuildError('coverage table repeats a row id')
    if catalogue is not None:
        expected = {row['id'] for row in rows}
        actual = _catalogue_ids(catalogue)
        if actual != expected:
            missing, extra = sorted(expected - actual), sorted(actual - expected)
            raise BuildError(f'obligation catalogue differs from the coverage table: missing {missing[:10]} '
                             f'({len(missing)}), extra {extra[:10]} ({len(extra)})')
    bespoke_cases, dimension_cases = cases
    document = {'schema_version': SCHEMA_VERSION, 'kind': 'enforcement-case-bindings',
                'generator': 'scripts/maintenance/build_case_bindings.py',
                'coverage': {'sha256': coverage['sha256'], 'rows': len(rows)},
                'summary': {}, 'bespoke': [], 'groups': {}, 'parameterized': {}}
    known = set()
    group_ids = {}
    # Bespoke rows keep the table's order; parameterized rows are grouped in id order, so group ids
    # do not depend on the order of the input.
    ordered = ([row for row in rows if row['source_kind'] in BESPOKE_KINDS]
               + sorted((row for row in rows if row['source_kind'] not in BESPOKE_KINDS), key=lambda r: r['id']))
    for row in ordered:
        known.add(row['id'])
        if row['source_kind'] in BESPOKE_KINDS:
            bound = bespoke_cases.get(row['id'])
            document['bespoke'].append(dict(row, case=row['id'], status='implemented' if bound else 'pending',
                                            binding=bound['binding'] if bound else None,
                                            test=bound['test'] if bound else None))
            continue
        dimension = row['id'].split('-', 1)[0]
        if dimension not in DIMENSIONS:
            raise BuildError(f'{row["id"]}: parameterized row outside the known dimensions')
        field, node, spec = None, row['node'], row['spec']
        key = row['id'].split('-', 1)[1]
        if dimension == 'ROLE':
            key, field = _role_parts(row['id'])
        node = node.replace(f'[{key}]', '[*]')
        if not row.get('templated'):
            spec = _template(spec, key, '<role>' if dimension == 'ROLE' else '<id>')
        signature = (dimension, field, node, tuple(row['mechanisms']), row['class'], row['builder'],
                     row['ledger_class'], tuple(row['canary']), row['source_kind'])
        gid = group_ids.get(signature)
        if gid is None:
            gid = group_ids[signature] = f'g{len(group_ids) + 1:03d}'
            bound = dimension_cases.get((dimension, field), [])
            document['groups'][gid] = {
                'dimension': dimension, 'field': field, 'node': node, 'mechanisms': list(row['mechanisms']),
                'class': row['class'], 'builder': row['builder'], 'ledger_class': row['ledger_class'],
                'canary': list(row['canary']), 'source_kind': row['source_kind'],
                'case': f'{dimension}:{field}' if field else dimension, 'spec': spec, 'example': row['id'],
                'status': 'implemented' if bound else 'pending',
                'bindings': sorted({b['binding'] for b in bound}), 'tests': sorted(b['test'] for b in bound)}
        document['parameterized'][row['id']] = gid
    unknown = sorted(set(bespoke_cases) - known)
    if unknown:
        raise BuildError(f'cases close rows that are not in the coverage table: {unknown}')
    stale = sorted(f'{d}:{f}' for d, f in dimension_cases
                   if not any(g['dimension'] == d and g['field'] == f for g in document['groups'].values()))
    if stale:
        raise BuildError(f'dimension cases cover no coverage rows: {stale}')
    document['summary'] = summarise(document)
    return document


def summarise(document):
    bespoke = document['bespoke']
    groups = document['groups']
    para = document['parameterized']

    def count(items):
        return {status: sum(1 for i in items if i == status) for status in ('implemented', 'pending')}

    by_binding = {}
    for row in bespoke:
        key = row['binding'] or 'none'
        by_binding[key] = by_binding.get(key, 0) + 1
    para_status = [groups[gid]['status'] for gid in para.values()]
    para_binding = {}
    for gid in para.values():
        for binding in groups[gid]['bindings'] or ['none']:
            para_binding[binding] = para_binding.get(binding, 0) + 1
    by_kind = {}
    for row in bespoke:
        entry = by_kind.setdefault(row['source_kind'], {'implemented': 0, 'pending': 0})
        entry[row['status']] += 1
    return {'rows': len(bespoke) + len(para), 'bespoke': len(bespoke), 'parameterized': len(para),
            'bespoke_status': count([r['status'] for r in bespoke]), 'bespoke_by_kind': by_kind,
            'bespoke_by_binding': dict(sorted(by_binding.items())),
            'parameterized_status': count(para_status), 'parameterized_by_binding': dict(sorted(para_binding.items())),
            'groups': len(groups)}


def render(document):
    return json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + '\n'


def production_catalogue(path):
    """CLI builds always compare against a real catalogue, never a peer test fixture."""
    path = Path(path)
    if not path.is_file():
        raise BuildError(f'required obligation catalogue is missing: {path}')
    if 'fixtures' in path.absolute().parts or 'fixtures' in path.resolve().parts:
        raise BuildError(f'peer fixture cannot supply the production obligation catalogue: {path}')
    return path


def _pointer_part(value):
    return str(value).replace('~', '~0').replace('/', '~1')


def installed_census_rows():
    """Source-backed effective installed projection, independent of the test registry."""
    if str(ROOT / 'src') not in sys.path:
        sys.path.insert(0, str(ROOT / 'src'))
    from ravel.workflow import role_registry

    data = ROOT / 'src/ravel/data'
    signature_path = data / 'operation_signatures.json'
    signatures = json.loads(signature_path.read_bytes())['operations']
    executor_path = data / 'roles/executors.json'
    executor_table = json.loads(executor_path.read_bytes())
    executors = executor_table['operations']
    registry_path = data / 'roles/registry.json'
    registry = role_registry.registry_document(roles_root=data / 'roles')
    origins = {name: (registry_path, '/roles/' + _pointer_part(name) + '/card')
               for name in json.loads(registry_path.read_bytes())['roles']}
    for path in sorted((data / 'roles/registration').glob('*.json')):
        for name in json.loads(path.read_bytes()).get('roles', {}):
            origins[name] = (path, '/roles/' + _pointer_part(name) + '/card')
    path = data / 'higgs/registration/roles.json'
    if path.is_file():
        for name in json.loads(path.read_bytes()).get('append', {}).get('roles', {}):
            origins[name] = (path, '/append/roles/' + _pointer_part(name) + '/card')

    rows = {}

    def add(row_id, obligation, category, path, pointer, value, routes, **extra):
        raw = path.read_bytes()
        # The pointer is authoritative; line names its owning declaration in the source.
        owner = pointer.split('/')[2] if pointer.startswith(('/operations/', '/host_operations/')) else None
        line = next((i for i, text in enumerate(raw.decode().splitlines(), 1)
                     if owner is not None and json.dumps(owner) + ':' in text), 1)
        rows[row_id] = dict(id=row_id, obligation=obligation, category=category,
                            source=path.relative_to(ROOT).as_posix(), line=line,
                            source_sha256=hashlib.sha256(raw).hexdigest(), pointer=pointer,
                            declared_value=value, **{'class': 'ADVISORY'},
                            adjudication='OPEN-STRUCTURAL: current installed projection',
                            result_path=True, test_id='NC-' + row_id, routes=routes, **extra)

    categories = {'operations': 'tools', 'tools': 'tools', 'requires': 'tools',
                  'independence': 'independence', 'sees': 'independence', 'output': 'custody',
                  'must_check': 'scientific', 'escalation': 'stop', 'stop': 'budget',
                  'reviewed_by': 'review', 'dispatch': 'spawn'}
    for card in role_registry.all_cards(roles_root=data / 'roles'):
        role = card['id']
        record = registry['roles'][role]
        path, base_pointer = origins[role]
        if record.get('override') and (data / 'roles' / record['override']).is_file():
            path, base_pointer = data / 'roles' / record['override'], ''
            authored = json.loads(path.read_bytes())
        else:
            authored = record['card']
        digest = hashlib.sha256(role_registry.encode(card)).hexdigest()
        for field in ROLE_FIELDS:
            if field in ('dispatch', 'identity'):
                members = [(None, card)]
            elif field in ROLE_LIST_FIELDS:
                members = list(enumerate(card.get(field) or ()))
            elif field in card:
                members = [(None, card[field])]
            else:
                continue
            for index, value in members:
                row_id = f'ROLE-{role}-{field}' + (f'-{index}' if index is not None else '')
                source, pointer = path, base_pointer
                declared = value
                if field not in ('dispatch', 'identity'):
                    pointer += '/' + field + (f'/{index}' if index is not None else '')
                if field == 'operations' and index >= len(authored.get('operations', [])):
                    signature = signatures[value]
                    if signature.get('registration', {}).get('executor') != role:
                        raise BuildError(f'{row_id}: effective operation lacks its source executor')
                    source = signature_path
                    pointer = '/operations/' + _pointer_part(value) + '/registration/executor'
                    declared = role
                add(row_id, f'Role {role}: apply the effective {field} projection '
                    + json.dumps(value, sort_keys=True), categories.get(field, 'instructions'),
                    source, pointer, declared, 'role:' + role, effective_card_sha256=digest,
                    effective_card_field=field, effective_card_value=value)
    for operation, value in signatures.items():
        add('TOOL-' + operation, f'Operation {operation}: apply its declared signature; declaration '
            'does not establish scientific support.', 'tools', signature_path,
            '/operations/' + _pointer_part(operation), value, 'operation:' + operation)
    for operation, value in executors.items():
        add('EXEC-' + operation, f'Compute operation {operation}: dispatch through required '
            f'production role {value}.', 'spawn', executor_path,
            '/operations/' + _pointer_part(operation), value, 'operation:' + operation)
    for operation, reason in executor_table['host_operations'].items():
        host_role = executor_table['coordinator']['role']
        add('HOST-' + operation, f'Host operation {operation}: the declared host actor {host_role} '
            'must use the controller confined-launch path; refuse production, other-role or worker '
            'substitution and require an intact confined output or preparation receipt. ' + reason,
            'spawn', executor_path, '/host_operations/' + _pointer_part(operation),
            reason, 'operation:' + operation, host_role=host_role, host_role_pointer='/coordinator/role')
    return rows


_CARD_POSITION = re.compile(r'^ROLE-(?P<role>.+)-operations-(?P<index>\d+)$')


def _census_migrations(document):
    """Read the explicit, narrowly scoped retirement authorizations.

    Two forms exist, both for one operation that moved to the host: an ``EXEC-<op>`` row retires into
    its fresh ``HOST-<op>`` replacement; a card-position row ``ROLE-<role>-operations-<n>`` retires
    when the role's card no longer lists ``operation`` (named in the entry) and the installed host
    operation ``HOST-<operation>`` exists. Both name the duty, mechanism and reason reviewed.
    """
    if isinstance(document, (str, Path)):
        document = json.loads(Path(document).read_bytes())
    if (type(document) is not dict or type(document.get('schema_version')) is not int
            or document['schema_version'] != 1 or type(document.get('migrations')) is not list):
        raise BuildError('census migrations require schema_version 1 and a migrations list')
    mappings = {}
    targets = set()
    for entry in document['migrations']:
        if type(entry) is not dict or any(type(entry.get(key)) is not str or not entry[key].strip()
                                         for key in ('old', 'new', 'duty', 'mechanism', 'reason')):
            raise BuildError('each census migration requires nonempty old, new, duty, mechanism and reason')
        old, new = entry['old'], entry['new']
        position = _CARD_POSITION.fullmatch(old)
        if position is not None:
            operation = entry.get('operation')
            if type(operation) is not str or not operation.strip() or new != 'HOST-' + operation:
                raise BuildError('a card-position retirement names the operation that moved to the host '
                                 'and its HOST row')
        elif not old.startswith('EXEC-') or new != 'HOST-' + old.removeprefix('EXEC-') or old == 'EXEC-':
            raise BuildError('census migrations only allow EXEC-to-HOST mappings for the same operation')
        if old in mappings or (position is None and new in targets):
            raise BuildError('census migrations repeat an old or new id')
        mappings[old] = entry
        if position is None:
            targets.add(new)
    return mappings


def refresh_census(source, output, *, installed=None, migrations=None):
    """Append declarations; only explicit validated EXEC-to-HOST migrations may retire rows.

    Untouched JSONL lines remain byte-identical, including whitespace and line endings.
    Migration audit details are returned to the caller; no sidecar metadata is written.
    """
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise BuildError('census refresh requires a distinct output; preserve the original census')
    original = gzip.decompress(source.read_bytes())
    lines = original.splitlines(keepends=True)
    entries = [(line, json.loads(line)) for line in lines if line.strip()]
    records = [row for _, row in entries]
    ids = [row['id'] for row in records]
    if len(ids) != len(set(ids)):
        raise BuildError('census repeats a row id')
    installed = installed_census_rows() if installed is None else installed
    stale = sorted(row_id for row_id in ids if row_id.startswith(('ROLE-', 'TOOL-', 'EXEC-', 'HOST-'))
                   and row_id not in installed)
    mappings = {} if migrations is None else _census_migrations(migrations)
    if set(mappings) - set(stale):
        raise BuildError('census migration is not needed for a stale original row: '
                         + str(sorted(set(mappings) - set(stale))))
    if set(stale) - set(mappings):
        raise BuildError(f'census contains stale installed dimension IDs; refusing retirement: '
                         f'{sorted(set(stale) - set(mappings))}')
    originals = {row['id']: (line, row) for line, row in entries}
    applied = []
    source_path = 'src/ravel/data/roles/executors.json'
    for old, entry in sorted(mappings.items()):
        new = entry['new']
        line, row = originals[old]
        replacement = installed.get(new)
        position = _CARD_POSITION.fullmatch(old)
        if position is not None:
            operation, role, index = entry['operation'], position['role'], int(position['index'])
            if row.get('effective_card_field') != 'operations':
                raise BuildError(f'{old}: a card-position retirement needs an operations row')
            remaining = [r for rid, r in installed.items() if rid.startswith(f'ROLE-{role}-operations-')]
            if any(r.get('effective_card_value') == operation for r in remaining):
                raise BuildError(f'{old}: the card still lists {operation}; nothing moved to the host')
            if len(remaining) != index:
                raise BuildError(f'{old}: the card retains {len(remaining)} operations; only its last position retires')
            if (type(replacement) is not dict or replacement.get('id') != new
                    or replacement.get('source') != source_path
                    or replacement.get('pointer') != '/host_operations/' + _pointer_part(operation)):
                raise BuildError(f'{new}: the operation must be an installed host operation')
            applied.append(dict(entry, old_row_sha256=hashlib.sha256(line).hexdigest()))
            continue
        operation = old.removeprefix('EXEC-')
        if (row.get('source') != source_path
                or row.get('pointer') != '/operations/' + _pointer_part(operation)):
            raise BuildError(f'{old}: stale EXEC source is missing or invalid')
        if (new in ids or type(replacement) is not dict or replacement.get('id') != new
                or replacement.get('source') != source_path
                or replacement.get('pointer') != '/host_operations/' + _pointer_part(operation)):
            raise BuildError(f'{new}: migration target must be a fresh installed host replacement')
        applied.append(dict(entry, old_row_sha256=hashlib.sha256(line).hexdigest()))
    retained = set(ids) - set(mappings)
    added = sorted(set(installed) - retained)
    # Keep every untouched byte, including blank lines, in its original order.
    payload = b''.join(line for line in lines
                       if not line.strip() or json.loads(line)['id'] not in mappings)
    if added and payload and not payload.endswith(b'\n'):
        payload += b'\n'
    payload += b''.join((json.dumps(installed[row_id], sort_keys=True, separators=(',', ':'))
                        + '\n').encode() for row_id in added)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(gzip.compress(payload, mtime=0))
    summary = {'input_rows': len(records), 'rows': len(retained) + len(added),
               'added_count': len(added), 'added_ids': added}
    if migrations is not None:
        summary['applied_migrations'] = applied
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--coverage', type=Path, help='coverage table (coverage.csv); default: rows in the bindings')
    parser.add_argument('--catalogue', type=Path, default=CATALOGUE,
                        help='required production obligation catalogue (default: installed)')
    parser.add_argument('--refresh-census', type=Path, help='append missing installed declarations to this census')
    parser.add_argument('--census-out', type=Path, help='distinct refreshed gzip JSONL census output')
    parser.add_argument('--census-migrations', type=Path,
                        help='explicit schema-version-1 EXEC-to-HOST migration document')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--check', action='store_true', help='exit 1 when the bindings file is stale')
    args = parser.parse_args(argv)
    try:
        if (args.refresh_census is not None or args.census_out is not None
                or args.census_migrations is not None):
            if args.refresh_census is None or args.census_out is None:
                raise BuildError('--refresh-census and --census-out are required together')
            if args.coverage is not None or args.check or args.catalogue != CATALOGUE or args.out != OUT:
                raise BuildError('census refresh cannot be combined with binding build options')
            print(json.dumps(refresh_census(args.refresh_census, args.census_out,
                                            migrations=args.census_migrations), sort_keys=True))
            return 0
        catalogue = production_catalogue(args.catalogue)
        if args.coverage is not None:
            coverage = read_coverage(args.coverage)
        elif args.out.is_file():
            coverage = _embedded_rows(json.loads(args.out.read_text()))
        else:
            parser.error('--coverage is required for the first build')
        document = build(coverage, scan_cases(), catalogue=catalogue)
    except (BuildError, OSError, ValueError, KeyError, SyntaxError) as exc:
        print(f'build_case_bindings: {exc}', file=sys.stderr)
        return 1
    text = render(document)
    if args.check:
        current = args.out.read_text() if args.out.is_file() else ''
        if current != text:
            print(f'build_case_bindings: {args.out} is stale; rerun without --check', file=sys.stderr)
            return 1
        print(json.dumps(document['summary'], sort_keys=True))
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(json.dumps(document['summary'], sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
