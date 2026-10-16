"""Explicit contract projections for the event/inference chain.

Only authored registration fields are projected. Existing tables remain the
compatibility source for signatures without this opt-in block. No projection
grants execution, human approval, installation or scientific qualification.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

from ravel.validation.core import fail, finite_json_tree, same_json

GROUP = 'event-inference-chain'
TEXT = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
TERMS = {'type': 'array', 'items': TEXT}


def _object(properties, required=None):
    return {'type': 'object', 'properties': properties, 'additionalProperties': False,
            'required': list(properties if required is None else required)}


APPLICABILITY_SCHEMA = {'anyOf': [
    _object({'scope': {'const': 'general'}}),
    _object({'scope': {'const': 'source-bound'}, 'bound_to': TEXT,
             'select_when': {'type': 'array', 'minItems': 1,
                             'items': {**TERMS, 'minItems': 1}},
             'general_operation': {'anyOf': [TEXT, {'type': 'null'}]}}),
]}
DESCRIPTOR_SCHEMA = _object({
    'summary': TEXT, **{key: TERMS for key in ('operations', 'tools', 'inputs', 'observables', 'outputs', 'context')},
    'applicability': APPLICABILITY_SCHEMA,
})
CURATION_SCHEMA = _object({
    'use_when': {**TERMS, 'minItems': 1}, 'do_not_use_when': {**TERMS, 'minItems': 1},
    'examples': {'type': 'array', 'minItems': 1, 'items': _object({
        'phrase': TEXT, 'command': TEXT,
        'spec': {'type': 'object', 'required': ['mode', 'task'],
                 'properties': {'mode': TEXT, 'task': {'type': 'object'}}},
    }, required=('phrase', 'spec'))},
})
REGISTRATION_SCHEMA = _object({
    'executor': {'type': 'string', 'pattern': '^[a-z][a-z0-9-]*$'},
    'descriptor': DESCRIPTOR_SCHEMA,
    'setup_groups': {**TERMS, 'minItems': 1},
    'documentation': {'type': 'array', 'minItems': 1,
                      'items': _object({'path': {'type': 'string', 'pattern': r'^docs/.+\.md$'},
                                        'section': TEXT})},
    'curation': CURATION_SCHEMA,
})


def _refuse(field, observed, expected):
    fail(field, observed, expected, repair='repair the operation contract or its conflicting source declaration')


def read_signatures(path, *, raw=None):
    """Read only the selected tree, including historical optional table shapes."""
    path = Path(path)
    if any(part.is_symlink() for part in (path, *path.parents)):
        _refuse(str(path), str(path), 'operation signature path without symlinks')
    if not path.exists():
        return {}
    if not path.is_file():
        _refuse(str(path), str(path), 'regular operation signature file')

    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                _refuse(str(path) + '.' + key, key, 'unique JSON key')
            result[key] = value
        return result

    def constant(value):
        _refuse(str(path), value, 'finite JSON value')

    value = json.loads(path.read_bytes() if raw is None else raw,
                       object_pairs_hook=pairs, parse_constant=constant)
    finite_json_tree(value, field=str(path))
    if not isinstance(value, dict):
        _refuse(str(path), value, 'operation signature object')
    rows = value.get('operations', value.get('signatures', value))
    if isinstance(rows, list):
        mapped = {}
        for row in rows:
            name = row.get('operation', row.get('id')) if isinstance(row, dict) else None
            if not isinstance(name, str) or name in mapped:
                _refuse(str(path), name, 'distinct named operation signatures')
            mapped[name] = row
        rows = mapped
    if not isinstance(rows, dict) or any(not isinstance(row, dict) for row in rows.values()):
        _refuse(str(path), rows, 'operation names mapped to signature objects')
    return rows


def _implementation(name, signature, *, require_chain=False):
    """Validate shared explicit implementation structure without loading adapters."""
    field = f'operations.{name}'
    if not isinstance(signature, dict):
        _refuse(field, signature, 'operation signature object')
    implementation = signature.get('implementation', {})
    if not isinstance(implementation, dict):
        _refuse(field + '.implementation', implementation, 'operation implementation must be an object')
    if not require_chain and implementation.get('dispatch_group') != GROUP:
        return implementation
    if (implementation.get('dispatch_group') != GROUP
            or implementation.get('kind') != 'science-mode' or implementation.get('mode') != name):
        _refuse(field + '.implementation', implementation,
                'own science-mode implementation in event-inference-chain')
    module = implementation.get('module')
    if not isinstance(module, str) or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', module):
        _refuse(field + '.implementation.module', module, 'dotted Python module name')
    position = implementation.get('dispatch_position')
    if 'dispatch_position' in implementation and (type(position) is not int or position < 0):
        _refuse(field + '.implementation.dispatch_position', position, 'nonnegative integer')
    return implementation


def _declarations(signatures):
    """Identify explicit chain declarations without importing optional runtimes."""
    for name, signature in signatures.items():
        if not isinstance(signature, dict):
            _refuse(f'operations.{name}', signature, 'operation signature object')
        if 'registration' not in signature:
            continue
        field = f'operations.{name}.registration'
        _implementation(name, signature, require_chain=True)
        value = signature['registration']
        finite_json_tree(value, field=field)
        if not isinstance(value, dict):
            _refuse(field, value, 'registration object')
        yield name, value


def registered_rows(signatures):
    """Validate the closed opt-in contract before scientific interface projection."""
    rows = {}
    for name, value in _declarations(signatures):
        from jsonschema import Draft202012Validator
        field = f'operations.{name}.registration'
        issue = next(Draft202012Validator(REGISTRATION_SCHEMA).iter_errors(value), None)
        if issue is not None:
            location = '.'.join([field, *map(str, issue.absolute_path)])
            _refuse(location, issue.instance, issue.message)
        # The request-record dialect has no uniqueItems keyword. Enforce the
        # same identity constraint explicitly with the existing schema library.
        for key in ('setup_groups', 'documentation'):
            if not Draft202012Validator({'uniqueItems': True}).is_valid(value[key]):
                _refuse(field + '.' + key, value[key], 'distinct entries')
        for index, example in enumerate(value['curation']['examples']):
            if example['spec']['mode'] != name:
                _refuse(f'{field}.curation.examples.{index}.spec.mode', example['spec']['mode'], name)
        applicability = value['descriptor']['applicability']
        general = applicability.get('general_operation')
        if general is not None and (general == name or general not in signatures):
            _refuse(field + '.descriptor.applicability.general_operation', general,
                    'a distinct registered operation or null')
        for row in value['documentation']:
            path = Path(row['path'])
            if path.is_absolute() or '..' in path.parts or path.as_posix() != row['path']:
                _refuse(field + '.documentation.path', row['path'], 'normalized relative shipped Markdown path')
        rows[name] = value
    return rows


def _setup_rows(signatures):
    """Bootstrap needs only explicit dependency mappings, before schema libraries.

    Full registration and admission remain the scientific readers' responsibility;
    the installer still applies its own manifest and group validators.
    """
    rows = dict(_declarations(signatures))
    for name, row in rows.items():
        groups = row.get('setup_groups')
        if (type(groups) is not list or not groups
                or any(type(group) is not str or not group.strip() for group in groups)
                or len(groups) != len(set(groups))):
            _refuse(f'operations.{name}.registration.setup_groups', groups,
                    'nonempty distinct installer group names')
    return rows


def _merge(table, name, value, field):
    if name in table and not same_json(table[name], value):
        _refuse(field + '.' + name, table[name], f'contract declaration {value!r}')
    table[name] = deepcopy(value)


def executor_document(document, signatures):
    result = deepcopy(document)
    for name, row in registered_rows(signatures).items():
        if name in result.get('host_operations', {}):
            _refuse('executors.host_operations.' + name, result['host_operations'][name],
                    'production-only chain operation')
        _merge(result['operations'], name, row['executor'], 'executors.operations')
    return result


def descriptor_document(document, signatures):
    result = deepcopy(document)
    for name, row in registered_rows(signatures).items():
        _merge(result['modes'], name, row['descriptor'], 'descriptors.modes')
    return result


def manifest_document(document, signatures):
    result = deepcopy(document)
    rows = _setup_rows(signatures)
    if not rows:
        return result
    operations = result.get('operations')
    if not isinstance(operations, list):
        _refuse('manifest.operations', operations, 'operation list')
    names = [row.get('mode') for row in operations]
    if len(names) != len(set(names)):
        _refuse('manifest.operations', names, 'distinct operation names')
    groups = {group['id'] for group in result.get('groups', [])}
    scoped = {name for name, signature in signatures.items()
              if signature.get('implementation', {}).get('kind') == 'scoped-adapter'}
    positioned = [name for name in rows if 'dispatch_position' in signatures[name]['implementation']]
    positions = [signatures[name]['implementation']['dispatch_position'] for name in positioned]
    if len(positions) != len(set(positions)):
        _refuse('operations.implementation.dispatch_position', positions, 'distinct nonnegative positions')
    ordered = sorted(positioned, key=lambda name: signatures[name]['implementation']['dispatch_position'])
    ordered += [name for name in rows if name not in positioned]
    for name in ordered:
        row = rows[name]
        if not set(row['setup_groups']) <= groups:
            _refuse(f'operations.{name}.registration.setup_groups', row['setup_groups'],
                    'explicit existing installer groups')
        expected = {'mode': name, 'groups': row['setup_groups']}
        if name in names:
            observed = operations[names.index(name)]
            if not same_json(observed, expected):
                _refuse('manifest.operations.' + name, observed, f'contract declaration {expected!r}')
            continue
        impl = signatures[name]['implementation']
        anchor = impl.get('dispatch_before')
        if 'dispatch_position' in impl and anchor in names:
            position = names.index(anchor)
        elif 'dispatch_position' in impl:
            position = impl['dispatch_position']
            if type(position) is not int or position < 0:
                _refuse(f'operations.{name}.implementation.dispatch_position', position, 'nonnegative integer')
            position = min(position, len(names))
        else:
            position = next((i for i, op in enumerate(names) if op in scoped), len(names))
        operations.insert(position, deepcopy(expected))
        names.insert(position, name)
    return result


def card_operations(card, signatures):
    """Project only explicit assignments; card identity and all other duties stay owned."""
    result = deepcopy(card)
    for name, row in registered_rows(signatures).items():
        assigned = row['executor'] == card['id']
        operations = result.get('operations', [])
        if name in operations and not assigned:
            _refuse(f'roles.{card["id"]}.operations', operations,
                    f'{name} belongs to declared executor {row["executor"]}')
        if assigned:
            if card.get('family') != 'production':
                _refuse(f'roles.{card["id"]}.family', card.get('family'), 'production')
            if name not in operations:
                result.setdefault('operations', []).append(name)
    return result
