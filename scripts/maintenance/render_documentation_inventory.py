#!/usr/bin/env python3
"""Render and check the source-derived documentation inventory and CLI reference.

No command handler, adapter, model client, native tool or doctor probe is run.
The capability join reads registration metadata; parser declarations are read as
Python syntax. Snapshots carry original source pins, never hashes of generated
knowledge/documents, so refreshing the atlas cannot create a self-hash cycle.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import posixpath
from urllib.parse import unquote, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = 'docs/reference/documentation-inventory.json'
MARKDOWN = 'docs/reference/documentation-inventory.md'
COMMANDS = 'docs/cli/commands.md'
# The knowledge atlas registers a marked index as a document and never links it by mention.
GENERATED_INDEX_MARKER = '<!-- ravel:generated-index -->'
COMMAND_JSON = 'docs/reference/documentation-command-inventory.json'
CONFIG_JSON = 'docs/reference/documentation-configuration-inventory.json'
SOURCE_SCOPE = ('src/ravel', 'scripts', 'native')

# Narrative homes explain the lifecycle around a source declaration. Exact item
# anchors live in the generated reference, rather than demanding repeated lists
# in prose. These are domains, never capability/command membership allowlists.
HOMES = {
    'capability': 'docs/reference/scope.md',
    'science-mode': 'docs/guides/study-types.md',
    'descriptor': 'docs/guides/study-types.md',
    'config-key': 'docs/reference/configuration.md',
    'config-keyset': 'docs/reference/configuration.md',
    'route': 'docs/architecture/controller.md',
    'graph': 'docs/architecture/controller.md',
    'graph-node': 'docs/architecture/controller.md',
    'role': 'docs/reference/roles.md',
    'seat': 'docs/reference/engagement.md',
    'transport': 'docs/architecture/providers.md',
    'provider': 'docs/architecture/providers.md',
    'installer-component': 'docs/installation.md',
    'doctor-check': 'docs/installation.md',
    'manifest': 'docs/architecture/execution.md',
    'build-tool': 'docs/build-and-release.md',
    'module': 'docs/architecture/execution.md',
}


def encode(value):
    if not isinstance(value, dict):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n'
    lines = ['{']
    keys = sorted(value)
    for index, key in enumerate(keys):
        encoded_key = json.dumps(key)
        child = value[key]
        suffix = ',' if index < len(keys) - 1 else ''
        if isinstance(child, list) and child:
            lines.append('  ' + encoded_key + ': [')
            for item_index, item in enumerate(child):
                lines.append('    ' + json.dumps(item, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')) +
                             (',' if item_index < len(child) - 1 else ''))
            lines.append('  ]' + suffix)
        else:
            lines.append('  ' + encoded_key + ': ' + json.dumps(child, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + suffix)
    return '\n'.join([*lines, '}']) + '\n'


def slug(value):
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def anchor(identity):
    return slug(identity.split(':', 1)[0]) + '-' + hashlib.sha256(identity.encode()).hexdigest()[:16]


def cell(value):
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return value.replace('&', '&amp;').replace('|', '&#124;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', ' ').replace('`', '&#96;')


def first_line(value):
    return next((line.strip() for line in str(value or '').splitlines() if line.strip()), '')


def json_source(root, relative):
    return json.loads((root / relative).read_text(encoding='utf-8'))


def held_names(root, toolchain):
    """Names of the census-bound groups this tree withholds from a release.

    A source tree lists them as unreleased; a released tree carries no such list and declares only
    the groups it ships, so a group the census binds but the manifest does not declare is held there as
    well (``held_groups``). A source checkout and its release therefore name the same set, and a document rendered from either
    omits the same declarations."""
    census = json_source(root, 'src/ravel/data/backends/census.json')
    bound = set()
    for tool in census['tools']:
        bound |= set(tool.get('installer_groups', []))
        bound |= {check['group'] for check in tool.get('doctor_checks', []) if check.get('kind') == 'manifest'}
    return sorted(bound & toolchain.held_groups(toolchain.view(root), bound))


def names_any(held, value):
    """Does ``value`` name one of the held groups as a word of its own?"""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return any(re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', text) for name in held)


def module_description(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    functions = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith('_') for node in tree.body)
    classes = sum(isinstance(node, ast.ClassDef) and not node.name.startswith('_') for node in tree.body)
    return f'Python source declaring {functions} public functions and {classes} public classes; behavior follows its source contracts.'


def parser_source_paths(root):
    """Discover parsers across the complete product and repository script trees."""
    return sorted({path for relative in SOURCE_SCOPE for path in (Path(root) / relative).rglob('*.py')
                   if '__pycache__' not in path.parts and 'ArgumentParser' in path.read_text(encoding='utf-8')})


def schema_fields(schema, prefix='', gaps=None, *, source='<schema>', documents=None, references=None, boundaries=None):
    """Named use-site properties with confined, source-declared reference resolution.

    No URL is fetched. Controller name refs and judgment property fragments follow
    their owning source loaders; other documents use JSON pointers, IDs and anchors.
    A recursive edge points to its already expanded use site instead of inventing
    infinitely many configuration paths.
    """
    found = {}
    gaps = gaps if gaps is not None else []
    references = references if references is not None else []
    boundaries = boundaries if boundaries is not None else []
    documents = {**(documents or {}), source: schema}
    identifiers = {}
    anchors = {}

    def index(node, document, pointer='', base=''):
        if isinstance(node, dict):
            identifier = node.get('$id')
            if isinstance(identifier, str):
                base = urljoin(base, identifier) if base else identifier
                for spelling in {identifier, base}:
                    identifiers.setdefault(spelling, []).append((document, pointer, node))
            if isinstance(node.get('$anchor'), str):
                anchors.setdefault((document, node['$anchor']), []).append((pointer, node))
            for name, child in node.items():
                index(child, document, pointer + '/' + name.replace('~', '~0').replace('/', '~1'), base)
        elif isinstance(node, list):
            for position, child in enumerate(node):
                index(child, document, pointer + '/' + str(position), base)

    for document, value in documents.items():
        index(value, document)

    def failure(path, reference, reason, document):
        gap = {'path': path, 'reference': reference, 'reason': reason, 'source': document}
        if gap not in gaps:
            gaps.append(gap)

    def target_for(reference, document, path):
        if not isinstance(reference, str):
            failure(path, reference, 'reference is not a string', document)
            return None
        base, _, fragment = reference.partition('#')
        target_source, pointer, target = document, '', documents[document]
        if base:
            matches = identifiers.get(base, [])
            declared_base = documents[document].get('$id', '')
            if not matches and declared_base:
                matches = identifiers.get(urljoin(declared_base, base), [])
            # Identifiers can be declared under more than one spelling, but the
            # same declaration does not become ambiguous through that alias.
            unique = {(item[0], item[1]): item for item in matches}
            if len(unique) > 1:
                failure(path, reference, 'ambiguous declared schema identifier', document)
                return None
            if unique:
                target_source, pointer, target = next(iter(unique.values()))
            else:
                if urlsplit(base).scheme or base.startswith('/'):
                    failure(path, reference, 'unresolved schema identifier; no remote fetching', document)
                    return None
                if document.startswith('src/ravel/data/judgment/schemas/'):
                    candidate = posixpath.join('src/ravel/data/judgment/schemas', base)
                else:
                    candidate = posixpath.join(posixpath.dirname(document), base)
                    if document.startswith('src/ravel/data/controller/schemas/') and '/' not in base and not base.endswith('.json'):
                        candidate += '.json'
                candidate = posixpath.normpath(candidate)
                if candidate.startswith('../') or candidate not in documents:
                    failure(path, reference, 'missing confined schema document', document)
                    return None
                target_source, target = candidate, documents[candidate]
        fragment = unquote(fragment)
        if fragment:
            try:
                if fragment.startswith('/'):
                    for part in fragment[1:].split('/'):
                        decoded = part.replace('~1', '/').replace('~0', '~')
                        target = target[int(decoded)] if isinstance(target, list) else target[decoded]
                    pointer += fragment
                elif document.startswith('src/ravel/data/judgment/schemas/'):
                    # Judgment's loader explicitly defines #name as a property,
                    # rather than a standard JSON Schema anchor.
                    target = target['properties'][fragment]
                    pointer += '/properties/' + fragment.replace('~', '~0').replace('/', '~1')
                else:
                    matches = anchors.get((target_source, fragment), [])
                    if len(matches) != 1:
                        failure(path, reference, 'ambiguous schema anchor' if matches else 'missing schema anchor', document)
                        return None
                    pointer, target = matches[0]
            except (KeyError, TypeError, ValueError, IndexError):
                failure(path, reference, 'missing local reference', document)
                return None
        if not isinstance(target, dict):
            failure(path, reference, 'schema reference target is not an object', document)
            return None
        return target_source, pointer, target

    def resolve(node, path, chain, document):
        if not isinstance(node, dict):
            return node, chain, document, False
        reference = node.get('$ref')
        if not reference:
            return node, chain, document, False
        result = target_for(reference, document, path)
        if result is None:
            return node, chain, document, True
        target_source, pointer, target = result
        identity = (target_source, pointer)
        previous = next((use for target_id, use in chain if target_id == identity), None)
        edge = {'source': document, 'path': path, 'reference': reference,
                'target_source': target_source, 'target_pointer': pointer,
                'recursive': previous is not None}
        if previous is not None:
            edge['target_use_site'] = previous
        if edge not in references:
            references.append(edge)
        if previous is not None:
            return {'$ref': reference, **({'type': target['type']} if 'type' in target else {}),
                    'documentation_reference': edge}, chain, target_source, True
        if len(chain) >= 64:
            failure(path, reference, 'schema reference expansion exceeds bound', document)
            return node, chain, document, True
        merged = {**target, **{key: child for key, child in node.items() if key != '$ref'}}
        return resolve(merged, path, (*chain, (identity, path)), target_source)

    def visit(node, path, chain, document, resolved=False, predicates=()):
        if not isinstance(node, dict):
            return
        if not resolved:
            node, chain, document, terminal = resolve(node, path, chain, document)
            if terminal:
                return
        required = node.get('required', [])
        required = required if isinstance(required, list) else []
        properties = {name: {} for name in required if isinstance(name, str)}
        properties.update(node.get('properties', {}))
        for name, raw in properties.items():
            key = path + '.' + name if path else name
            value, child_chain, child_document, terminal = resolve(raw, key, chain, document)
            if not isinstance(value, dict):
                continue
            facts = {k: v for k, v in value.items() if k in
                     ('type', 'enum', 'const', 'default', 'minimum', 'maximum', 'pattern', 'minItems', 'maxItems', 'additionalProperties', 'allOf', 'anyOf', 'oneOf', '$ref', 'documentation_reference')}
            row = {'key': key, 'required': name in required,
                   'summary': value.get('description', value.get('title', 'Schema property: ' + key)),
                   'constraints': facts, 'source': child_document}
            if predicates:
                row['predicates'] = list(predicates)
            found.setdefault(key, []).append(row)
            if not terminal:
                visit(value, key, child_chain, child_document, resolved=True, predicates=predicates)
        if isinstance(node.get('items'), dict):
            visit(node['items'], path + '[]', chain, document, predicates=predicates)
        for keyword in ('prefixItems', 'items'):
            if isinstance(node.get(keyword), list):
                for position, child in enumerate(node[keyword]):
                    visit(child, path + '[]', chain, document,
                          predicates=(*predicates, {'array_position': position, 'keyword': keyword}))
        if isinstance(node.get('contains'), dict):
            visit(node['contains'], path + '[]', chain, document,
                  predicates=(*predicates, {'array_member_constraint': 'contains'}))
        for variant in ('oneOf', 'anyOf', 'allOf'):
            for position, child in enumerate(node.get(variant, [])):
                visit(child, path, chain, document,
                      predicates=(*predicates, {'composition': variant, 'branch': position}))
        if isinstance(node.get('if'), dict):
            visit(node['if'], path, chain, document,
                  predicates=(*predicates, {'conditional': 'if', 'predicate_only': True}))
            for keyword in ('then', 'else'):
                if isinstance(node.get(keyword), dict):
                    visit(node[keyword], path, chain, document,
                          predicates=(*predicates, {'conditional': keyword, 'if': node['if']}))
        for keyword in ('dependentSchemas', 'dependencies', 'dependentRequired'):
            for dependency, child in node.get(keyword, {}).items():
                condition = (*predicates, {'dependency_present': dependency, 'keyword': keyword})
                if dependency not in properties:
                    visit({'properties': {dependency: {}}}, path, chain, document,
                          predicates=(*predicates, {'dependency_trigger': keyword}))
                if isinstance(child, dict):
                    visit(child, path, chain, document, predicates=condition)
                elif isinstance(child, list):
                    visit({'required': child}, path, chain, document, predicates=condition)
        dynamic_path = path + '.{key}' if path else '{key}'
        for pattern, child in node.get('patternProperties', {}).items():
            boundary = {'source': document, 'path': path, 'kind': 'patternProperties', 'pattern': pattern,
                        'scope': 'Pattern-selected map keys use the typed {key} position.'}
            if boundary not in boundaries:
                boundaries.append(boundary)
            visit(child, dynamic_path, chain, document, predicates=(*predicates, {'dynamic_key_pattern': pattern}))
        for keyword in ('additionalProperties', 'unevaluatedProperties'):
            child = node.get(keyword)
            if child is True or isinstance(child, dict):
                boundary = {'source': document, 'path': path, 'kind': keyword,
                            'scope': 'Open map keys use the typed {key} position for named value fields.'}
                if boundary not in boundaries:
                    boundaries.append(boundary)
                if isinstance(child, dict):
                    visit(child, dynamic_path, chain, document,
                          predicates=(*predicates, {'dynamic_key_values': keyword}))
        if isinstance(node.get('propertyNames'), dict):
            boundary = {'source': document, 'path': path, 'kind': 'propertyNames',
                        'constraints': node['propertyNames'], 'scope': 'Declared constraints on map key names.'}
            if boundary not in boundaries:
                boundaries.append(boundary)
            names = node['propertyNames'].get('enum', [])
            if isinstance(names, list) and all(isinstance(name, str) for name in names):
                visit({'properties': {name: node.get('additionalProperties', {}) if isinstance(node.get('additionalProperties'), dict) else {}
                                      for name in names}}, path, chain, document,
                      predicates=(*predicates, {'key_name_constraint': 'propertyNames.enum'}))
        # Definitions are templates, not root properties. They are visited only
        # through a declared use site's local reference.

    visit(schema, prefix, (((source, ''), prefix),), source)
    return [{'key': key, 'variants': values} for key, values in sorted(found.items())]


def data_fields(value, prefix=''):
    """Named editable record keys; array members share one [] field vocabulary."""
    rows = {}
    if isinstance(value, dict):
        for name, child in value.items():
            key = prefix + '.' + name if prefix else name
            rows[key] = {'key': key, 'value_type': type(child).__name__}
            rows.update({row['key']: row for row in data_fields(child, key)})
    elif isinstance(value, list):
        for child in value:
            rows.update({row['key']: row for row in data_fields(child, prefix + '[]')})
    return list(rows.values())


def command_registrations(root):
    """Actual dispatch roots, including required lifecycle adapter words."""
    from ravel.workflow.knowledge_atlas import literal
    cli = Path(root) / 'src/ravel/cli.py'
    rows = []
    for registry in ('FOCUSED_COMMANDS', 'LIFECYCLE_COMMANDS', 'CONTROLLER_COMMANDS'):
        for name, record in literal(cli, registry).items():
            command_name = name + (' ' + record[1] if registry == 'LIFECYCLE_COMMANDS' and record[1] else '')
            rows.append({'name': name, 'command': 'ravel ' + command_name, 'registry': registry,
                         'module': 'ravel.' + record[0] if not record[0].startswith('ravel.') else record[0],
                         'summary': record[-1]})
    # Early dispatch prefixes (for example an audit subcommand) are code-owned
    # aliases as well. Resolve their imported main without invoking it.
    from documentation_parsers import Declarations, Imported
    reader = Declarations(Path(root), cli)
    for branch in ast.walk(reader.tree):
        if not isinstance(branch, ast.If) or not isinstance(branch.test, ast.Compare):
            continue
        comparison = branch.test
        left = comparison.left
        if not isinstance(left, ast.Subscript) or not isinstance(left.value, ast.Name) or left.value.id != 'arguments':
            continue
        if not isinstance(left.slice, ast.Slice) or left.slice.lower is not None:
            continue
        for compared in comparison.comparators:
            if not isinstance(compared, (ast.List, ast.Tuple)) or not compared.elts or not all(
                    isinstance(child, ast.Constant) and isinstance(child.value, str) for child in compared.elts):
                continue
            prefix = 'ravel ' + ' '.join(child.value for child in compared.elts)
            for call in ast.walk(ast.Module(body=branch.body, type_ignores=[])):
                if not isinstance(call, ast.Call):
                    continue
                imported = reader.value(call.func, reader.globals)
                if isinstance(imported, Imported) and imported.name == 'main' and imported.module.startswith('ravel.'):
                    rows.append({'name': prefix.removeprefix('ravel '), 'command': prefix, 'registry': 'prefix-dispatch',
                                 'module': imported.module, 'summary': 'Source-declared early dispatch prefix'})
    for declaration, prefix, module in (
            ('LITERATURE_SERVING_COMMANDS', 'literature', 'ravel.workflow.literature_cli'),
            ('REPLAY_OPERATIONS', 'replay', 'ravel.workflow.replay')):
        try:
            values = literal(cli, declaration)
        except ValueError:
            continue  # Small synthetic source fixtures can omit unrelated dispatches.
        for word in values:
            rows.append({'name': prefix + ' ' + word, 'command': 'ravel ' + prefix + ' ' + word,
                         'registry': declaration, 'module': module,
                         'summary': 'Source-declared special dispatch command'})
    unique = {(row['registry'], row['name'], row['module']): row for row in rows}
    return list(unique.values())


def effective_roles(root):
    """Effective cards and their actual base, fragment or override declaration."""
    from ravel.workflow.role_registry import registry_document, all_cards
    root = Path(root)
    role_source = 'src/ravel/data/roles/registry.json'
    document = registry_document(roles_root=root / 'src/ravel/data/roles')
    sources = {name: role_source for name in json_source(root, role_source)['roles']}
    for fragment in sorted((root / 'src/ravel/data/roles/registration').glob('*.json')):
        sources.update({name: fragment.relative_to(root).as_posix() for name in json.loads(fragment.read_text()).get('roles', {})})
    scalar = root / 'src/ravel/data/higgs/registration/roles.json'
    if scalar.is_file():
        sources.update({name: scalar.relative_to(root).as_posix() for name in json.loads(scalar.read_text()).get('append', {}).get('roles', {})})
    rows = []
    for card in all_cards(document=document, roles_root=root / 'src/ravel/data/roles'):
        name = card['id']
        override = document['roles'][name].get('override')
        source = ('src/ravel/data/roles/' + override if override and (root / 'src/ravel/data/roles' / override).is_file() else sources[name])
        rows.append({'card': card, 'source': source})
    return rows


def declaration_description(kind, identity, source, details=None, summary=''):
    """Describe structural facts without copying free-form source display prose."""
    facts = details or {}
    if kind in ('module', 'build-tool'):
        return summary
    if kind == 'capability':
        products = facts.get('produces')
        output_scope = (str(len(products)) + ' declared output slots' if isinstance(products, list) else
                        'output contract follows the source record' if not products or products.get('status') == 'not_declared' else
                        'output contract retained in the source record')
        return 'Catalogue ' + facts['catalogue_kind'] + ' declaration; ' + output_scope + '; cost class ' + facts['cost_class'] + '.'
    if kind == 'option':
        named = any(name.startswith('-') for name in facts['names'])
        required = facts.get('constraints', {}).get('required') in (True, 'True')
        return ('Required ' if required else 'Declared ') + ('option' if named else 'positional argument') + '; source help at ' + source + ':' + str(facts['line']) + '.'
    if kind in ('parser', 'command'):
        return kind.title() + ' declaration in ' + facts.get('scope', facts.get('registry', 'source')) + '; admission follows its handler.'
    if kind == 'config-key':
        if facts.get('namespace') == 'environment':
            return 'Named process-environment input read via ' + facts['access'] + '.'
        variants = facts.get('variants', [])
        if variants:
            types = sorted({str(row['constraints']['type']) for row in variants if 'type' in row['constraints']})
            return ('Schema property; ' + ('required' if any(row['required'] for row in variants) else 'optional') +
                    ('; declared type ' + ', '.join(types) if types else '') + '.')
        return 'Declared configuration field in ' + facts.get('namespace', 'source record') + '.'
    if kind == 'config-keyset':
        return 'Source field vocabulary ' + facts['declaration'] + '; ' + str(len(facts['named_keys'])) + ' named keys.'
    if kind == 'descriptor':
        return 'Discovery descriptor; ' + str(len(facts.get('operations', []))) + ' operation selectors and ' + str(len(facts.get('tools', []))) + ' tool selectors.'
    if kind == 'science-mode':
        return 'Registered science mode' + (' with a provider binding.' if facts.get('provider') else '; admission follows the operation contract.')
    if kind == 'graph':
        return 'Graph builder ' + facts['module'] + ':' + facts['builder'] + '; scope ' + facts['scope'] + '.'
    if kind == 'graph-node':
        return ('Registered builder node in ' + facts['graph'] if 'graph' in facts else 'Graph framework vocabulary ' + facts['category']) + '.'
    if kind == 'route':
        return 'Installed route predicate; ' + str(len(facts.get('steps', []))) + ' declared plan steps.'
    if kind == 'transport':
        return 'Transport declaration with executor kind ' + facts['transport_kind'] + '.'
    if kind == 'role':
        return 'Effective role card in family ' + facts.get('family', 'source-declared') + '; model and independence constraints remain explicit.'
    if kind == 'installer-component':
        return 'Installer component with ' + str(facts['check_count']) + ' declared readiness checks.'
    if kind == 'doctor-check':
        return 'Readiness probe declaration; check kind ' + str(facts.get('kind', 'source-defined')) + '.'
    if kind == 'provider':
        return 'Provider family vocabulary.' if 'family' in facts else 'Model preference preset; exact declaration retained.'
    if kind == 'seat':
        return 'Registered engagement seat-plan or dynamic role binding.'
    if kind == 'manifest':
        return 'Installed manifest with ' + str(len(facts['top_level_keys'])) + ' declared top-level keys.'
    return kind.title() + ' source declaration.'


def structural_details(value, source, *, parser=False):
    """Retain machine fields; replace copied display prose with its source pointer."""
    def parser_constraint(child):
        try:
            literal = ast.literal_eval(child) if isinstance(child, str) else child
        except (ValueError, SyntaxError, TypeError):
            return 'source declaration at ' + source

        def numeric(item):
            return item is None or isinstance(item, (int, float, bool)) or (
                isinstance(item, (tuple, list)) and all(numeric(member) for member in item))
        return literal if numeric(literal) else 'source declaration at ' + source

    prose_scopes = {
        'Events not yet processed by Rivet: use analyze.': 'Use analyze for events before Rivet processing.',
        'One withheld test evaluation of a classifier comparison is wanted.': 'One sealed confirmation evaluation of a classifier comparison is requested.',
        'The prescribed quantity is the primary result and CLs may accompany it.': 'The prescribed quantity is the primary result; CLs is an optional companion.',
        'The newer Pythia-free recipe, its checkmate-abi check and its cleanup are held under strict xfails of the source tests until an admitted native build qualifies them. Runtime ABI closure may not be claimed before that qualification.': 'The recipe declares native ABI and cleanup qualification checks.',
        'Testers qualify this group on their own Linux analysis facility with the recorded procedure. No such run is recorded here and none is claimed; the group does not run on the reference Mac.': 'Linux facility qualification follows the recorded procedure.',
        'Installer declaration; installation not inspected': 'Installer declaration and its doctor checks.',
        'No exact installer binding declared for this vocabulary term': 'Tool vocabulary declaration; consult its source record.',
        'No execution evidence inferred.': 'Source declaration and its evidence contract.',
        'Reference registration only; no native or scientific qualification inferred.': 'Registered source reference and its qualification contract.',
        'Reference registration only; no physics qualification inferred.': 'Registered source reference and its qualification contract.',
        'Registered from a source-owned registration fragment; installation and qualification are pending until a receipt exists.': 'Registered source fragment; installation and qualification use recorded receipts.',
        'Registration only; no readiness inferred.': 'Source registration; readiness uses the declared doctor checks.',
        'Reported historical census status; no current installation or physics certification inferred.': 'Historical tool census; current readiness uses doctor.',
        'Shipped source reader/construction only; no external engine readiness inferred.': 'Source reader/construction declaration.',
    }
    if isinstance(value, str) and value in prose_scopes:
        return prose_scopes[value]
    if isinstance(value, dict):
        return {key: ('source declaration at ' + source if key in ('summary', 'description', 'title', 'notes', 'reason', 'rationale', 'help', 'purpose', 'applicability', 'instruction', 'limitations') else
                      parser_constraint(child) if parser and key in ('choices', 'default') else structural_details(child, source, parser=parser))
                for key, child in value.items()}
    if isinstance(value, list):
        return [structural_details(child, source, parser=parser) for child in value]
    return value


def selected_inventory(root):
    """Dispatch the source-view hook only when source distribution data exists.

    A published checkout reads itself and needs no source-maintenance tooling.
    """
    root = Path(root)
    sys.path.insert(0, str(root / 'src'))
    from ravel import evidence_layout
    if not (root / evidence_layout.REGISTRY).is_file():
        return None
    registry = evidence_layout.load_registry(root)
    if not evidence_layout.source_fields(registry['distribution']):
        return None
    sys.path.insert(0, str(root / 'scripts/release'))
    from documentation_projection import selected_inventory as source_view
    return source_view(root)


def inventory(root=ROOT, *, source_tree=False):
    root = Path(root).resolve()
    if not source_tree:
        selected = selected_inventory(root)
        if selected is not None:
            return selected
    sys.path.insert(0, str(root / 'src'))
    from documentation_parsers import Declarations, extract, expand_dynamic_programs
    from ravel.workflow.capability_catalogue import catalogue
    from ravel.workflow.knowledge_atlas import literal
    from ravel.validation.validate_task_contract import SCHEMA
    from ravel.workflow.operation_definitions import populate_modes
    from ravel.setup import manifest as toolchain

    # A release documents only what it ships; the source audit (source_tree) keeps every declaration.
    held = [] if source_tree else held_names(root, toolchain)
    entries, pins = {}, {}

    def pin(relative):
        path = root / relative
        if path.is_file():
            # Generated atlas/instruction output can include documentation hashes.
            # Pin their original declarations instead of producing a hash cycle.
            if relative in ('src/ravel/data/knowledge/atlas.json', 'src/ravel/data/agents/call_sites.json',
                            'src/ravel/data/agents/affordances.json', 'src/ravel/data/instructions/catalogue.json'):
                return
            if relative.startswith('docs/') or relative.startswith('src/ravel/data/workflow/'):
                return
            pins[relative] = {'path': relative, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def add(identity, kind, summary, source, *, details=None, home=None, scope=None):
        if identity in entries:
            raise ValueError('duplicate documentation inventory id: ' + identity)
        pin(source)
        target = COMMANDS if kind in ('parser', 'command', 'option') else MARKDOWN
        refs = [target + '#' + anchor(identity)]
        if home or kind in HOMES:
            refs.append(home or HOMES[kind])
        entries[identity] = {'id': identity, 'kind': kind,
                             'summary': declaration_description(kind, identity, source, details, summary),
                             'source': source, 'docs': refs,
                             'scope': scope or 'registration'}
        if details is not None:
            location = source + (':' + str(details['line']) if 'line' in details else '')
            entries[identity]['details'] = structural_details(details, location, parser=kind == 'option')

    # The complete deciding catalogue is generated from the actual source join.
    # All ids survive, including declarations with unavailable execution paths.
    capabilities = catalogue(source_root=root)
    for row in capabilities['entries']:
        add('capability:' + row['id'], 'capability', row['summary'], row['source']['path'],
            details={'capability_id': row['id'], 'catalogue_kind': row['kind'],
                     'applicability': row['applicability'],
                     'prerequisites_ref': row['prerequisites']['ref'],
                     'produces': row['produces'], 'cost_class': row['cost_class']})
    for source in capabilities['sources']:
        pin(source['path'])
    # Composed role/consult/graph declarations consume these finite data
    # registries even when a newly added fragment only changes a join or alias.
    # Generated atlas/document hashes remain excluded by pin().
    for path in sorted((root / 'src/ravel/data').rglob('*.json')):
        if 'registration' in path.parts or path.parent.name in ('knowledge', 'roles'):
            pin(path.relative_to(root).as_posix())

    command_modules = []
    for record in command_registrations(root):
        command_modules.append((record['command'].removeprefix('ravel '), record['module']))
        add('command-registry:' + record['registry'] + ':' + record['name'] + ':' + record['module'], 'command', record['summary'],
            'src/ravel/cli.py', details={'command': record['command'], 'scope': record['registry'], 'line': 1,
                                       'registry': record['registry'], 'module': record['module']}, scope='dispatch-registration')
    for relative in SOURCE_SCOPE:
        for path in sorted((root / relative).rglob('*.py')):
            if '__pycache__' in path.parts:
                continue
            pin(path.relative_to(root).as_posix())
    parser_paths = parser_source_paths(root)
    parser_rows, parser_gaps = extract(root, parser_paths, command_modules)
    parser_rows, parser_context_gaps = expand_dynamic_programs(root, parser_rows)
    # A declaration whose runtime predicate names a withheld group is not offered by the release.
    parser_rows = [row for row in parser_rows if not names_any(held, row.get('availability', ''))]
    for row in parser_rows:
        add(row['id'], row['kind'], row['summary'], row['source'], details={key: value for key, value in row.items() if key not in ('id', 'kind', 'summary', 'source')},
            scope='conditional-source-declaration' if 'availability' in row else 'parser-declaration')
    catalogue_gaps = []
    for capability in capabilities['entries']:
        if capability['kind'] != 'command' or not capability['id'].startswith('cmd:'):
            continue
        command = 'ravel ' + capability['id'].removeprefix('cmd:')
        declarations = [row for row in parser_rows if row['kind'] in ('parser', 'command') and row['command'] == command]
        if declarations and all(row.get('availability', {}).get('kind') == 'conditional-source-declaration' for row in declarations):
            catalogue_gaps.append({'capability_id': capability['id'], 'source': capability['source']['path'],
                                   'command': command, 'availability': [row['availability'] for row in declarations],
                                   'scope': 'Conditional parser declaration; its runtime source predicate governs dispatch.'})

    science_path = root / 'src/ravel/workflow/science.py'
    science_tree = ast.parse(science_path.read_text(encoding='utf-8'))
    declared_modes = next(ast.literal_eval(node.value) for node in science_tree.body
                          if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'MODES'
                          for target in node.targets))
    modes = populate_modes(declared_modes)
    providers = literal(science_path, 'PROVIDER_MODES')
    descriptors = json_source(root, 'src/ravel/data/mode_descriptors.json')['modes']
    for name in sorted(set(modes) | set(providers)):
        add('science-mode:' + name, 'science-mode', descriptors.get(name, {}).get('summary', name),
            'src/ravel/workflow/science.py', details={'mode': name, 'provider': providers.get(name),
                'applicability': descriptors.get(name, {}).get('applicability', {})})
    for name, descriptor in sorted(descriptors.items()):
        add('descriptor:' + name, 'descriptor', descriptor['summary'], 'src/ravel/data/mode_descriptors.json',
            details=descriptor, scope='discovery-only')

    # Schema-derived task/operator keys include nested and conditional properties.
    schemas = {'task': ('src/ravel/validation/validate_task_contract.py', SCHEMA)}
    for relative in ('src/ravel/data/controller/schemas/operator-config.v1.json',
                     'src/ravel/data/site_tools/policy.schema.json', 'src/ravel/data/site_tools/scope.schema.json'):
        schemas[Path(relative).stem] = (relative, json_source(root, relative))
    schema_sources = {source for source, _ in schemas.values()}
    for base in ('src/ravel/data', 'native/setup'):
        for path in sorted((root / base).rglob('*.json')):
            if 'schema' not in path.name.lower() and not any(part in ('schema', 'schemas') for part in path.parts):
                continue
            source = path.relative_to(root).as_posix()
            if source not in schema_sources:
                document = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(document, dict):
                    schemas[source] = (source, document)
    schema_reference_gaps, schema_references, configuration_dynamic_boundaries = [], [], []
    schema_documents = {source: schema for source, schema in schemas.values()}
    for name, (source, schema) in sorted(schemas.items()):
        unresolved_refs = []
        fields = schema_fields(schema, gaps=unresolved_refs, source=source, documents=schema_documents,
                               references=schema_references, boundaries=configuration_dynamic_boundaries)
        schema_reference_gaps.extend(unresolved_refs)
        for field in fields:
            add('config:' + name + ':' + field['key'], 'config-key', field['variants'][0]['summary'], source,
                details={'namespace': name, **field}, scope='configuration-contract')
    # The model record format and site options are editable data contracts rather
    # than one JSON schema. Read original defaults, not a machine-local overlay.
    source = 'src/ravel/workflow/site_profiles/options.py'
    reader = Declarations(root, root / source)
    defaults = reader.globals['DEFAULTS']
    profile_keys = {node.args[0].value for node in ast.walk(reader.tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and
                    isinstance(node.func.value, ast.Name) and node.func.value.id == 'profile' and
                    node.func.attr == 'get' and node.args and isinstance(node.args[0], ast.Constant) and
                    isinstance(node.args[0].value, str)}
    for key in sorted(set(defaults) | set(reader.globals['OPTIONAL']) | profile_keys):
        add('config:site-profile:' + key, 'config-key', 'Site executor option: ' + key, source,
            details={'namespace': 'site-profile', 'key': key,
                     'default': str(defaults[key]) if key in defaults else 'not declared'}, home='docs/reference/configuration.md')
    model_source = 'src/ravel/data/models/catalogue.json'
    models = json_source(root, model_source)
    # Models and presets share one record vocabulary; individual model records
    # remain visible in the provider table without repeating each config field.
    for section, value in (('model-catalogue', {**{key: value for key, value in models.items() if key not in ('models', 'presets')}, 'models': [], 'presets': {}}),
                           ('model-record', models['models']), ('model-preset', list(models['presets'].values()))):
        for field in data_fields(value):
            add('config:' + section + ':' + field['key'], 'config-key', 'Editable ' + section + ' field: ' + field['key'],
                model_source, details={'namespace': section, **field})
    # Named source keysets/default dictionaries are a separate typed census.
    # They can describe record fields as well as operator-facing settings; the
    # source namespace and declaration kind stay explicit. Arbitrary computed
    # dictionaries and unnamed local validator shapes are outside this census.
    configuration_gaps = []
    non_vocabulary_declarations = []
    for path in sorted((root / 'src/ravel').rglob('*.py')):
        text = path.read_text(encoding='utf-8')
        if not re.search(r'\b[A-Z_]*(?:KEYS|FIELDS|DEFAULTS|SETTINGS|OPTIONS)\b', text):
            continue
        tree = ast.parse(text)
        declarations = [(target.id, node.value) for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                        if isinstance(target, ast.Name) and re.fullmatch(r'[A-Z_]*(?:KEYS|FIELDS|DEFAULTS|SETTINGS|OPTIONS)', target.id)]
        if not declarations:
            continue
        source = path.relative_to(root).as_posix()
        reader = Declarations(root, path)
        for consumed in reader.data_sources:
            pin(consumed)
        for name, expression in declarations:
            declared = reader.globals.get(name)
            if isinstance(declared, (int, float, bool, type(None))) or (isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute) and expression.func.attr == 'compile' and isinstance(expression.func.value, ast.Name) and expression.func.value.id == 're'):
                non_vocabulary_declarations.append({'source': source, 'declaration': name, 'scope': 'Numeric/scalar constant or regular expression.'})
                continue
            if isinstance(declared, dict):
                keys = [key for key in declared if isinstance(key, str)]
            elif isinstance(declared, (tuple, list, set)):
                keys = [key for key in declared if isinstance(key, str)]
            else:
                keys = []
            add('config-keyset:' + source + ':' + name, 'config-keyset', 'Named source field vocabulary: ' + name,
                source, details={'declaration': name, 'named_keys': sorted(set(keys)),
                                 'expression': ast.unparse(expression), 'scope': 'Named field declaration; acceptance follows its owning validator.'})
            if not keys and not isinstance(declared, (dict, tuple, list, set)):
                configuration_gaps.append({'source': source, 'declaration': name, 'expression': ast.unparse(expression),
                                           'scope': 'No finite string key vocabulary resolved statically; no exhaustive configuration claim.'})
            for key in sorted(set(keys)):
                add('config:named:' + source + ':' + name + ':' + key, 'config-key', name + ' field: ' + key,
                    source, details={'namespace': source + ':' + name, 'key': key}, scope='named-field-vocabulary')
    for name, preset in sorted(models['presets'].items()):
        add('provider:preset:' + name, 'provider', preset.get('summary', name), model_source, details=preset)
    for family in sorted({model['family'] for model in models['models']}):
        rows = [model for model in models['models'] if model['family'] == family]
        add('provider:family:' + family, 'provider', 'Declared provider family and model record vocabulary', model_source,
            details={'family': family, 'classes': sorted({model['class'] for model in rows}),
                     'tiers': sorted({tier for model in rows for tier in model['tiers']})})

    for relative in sorted((root / 'src/ravel/data/transports').glob('*.json')):
        source = relative.relative_to(root).as_posix()
        document = json_source(root, source)
        add('transport:' + document['id'], 'transport', first_line(document.get('notes')) or document['transport_kind'], source,
            details={'transport_kind': document['transport_kind'], 'launcher': document.get('launcher'),
                     'capabilities': document.get('capabilities'), 'qualification': document.get('qualification'),
                     'auth_environment_names': document.get('auth', {}).get('env_names', [])})
        # Record named transport settings once per declared field vocabulary.
    transport_keys = {}
    for relative in sorted((root / 'src/ravel/data/transports').glob('*.json')):
        for field in data_fields(json.loads(relative.read_text())):
            transport_keys.setdefault(field['key'], (field, relative.relative_to(root).as_posix()))
    for key, (field, source) in sorted(transport_keys.items()):
        add('config:transport:' + key, 'config-key', 'Transport declaration setting: ' + key, source,
            details={'namespace': 'transport', **field})

    from documentation_environment import collect_environment_reads
    environment_paths = sorted({path for base in SOURCE_SCOPE
                                for path in (root / base).rglob('*.py')})
    environment_rows, environment_dynamic_reads, environment_gaps = collect_environment_reads(root, environment_paths)
    for declaration in environment_rows:
        add('config:environment:' + declaration['source'] + ':' + str(declaration['line']) + ':' +
            declaration['access'] + ':' + declaration['name'], 'config-key',
            'Named process-environment input: ' + declaration['name'], declaration['source'],
            details={'namespace': 'environment', 'key': declaration['name'], **declaration}, scope='environment-read')

    from importlib import import_module
    selector = import_module('ravel.controller.routes.select')
    for path in sorted((root / 'src/ravel/data/controller/routes').glob('*.json')):
        source = path.relative_to(root).as_posix()
        for route in selector._read_specs(path):
            add('route:' + route['id'], 'route', route.get('description', route.get('reason', route['id'])),
                source, details=route, scope='route-predicate')
    selector_source = 'src/ravel/controller/routes/select.py'
    selector_reader = Declarations(root, root / selector_source)
    for route in selector_reader.globals['BUILTIN']:
        add('route:' + route['id'], 'route', route.get('description', route.get('reason', route['id'])),
            selector_source, details=route, scope='route-predicate')

    graph_sources = [root / 'src/ravel/data/graphs/registry.json', *sorted((root / 'src/ravel/data/graphs/registration').glob('*.json'))]
    graphs = {}
    for path in graph_sources:
        pin(path.relative_to(root).as_posix())
        for graph in json.loads(path.read_text())['graphs']:
            graphs[graph['id']] = (graph, path.relative_to(root).as_posix())
    for name, (graph, source) in sorted(graphs.items()):
        add('graph:' + name, 'graph', graph['module'] + ':' + graph['builder'] + ' (' + graph['scope'] + ')', source,
            details=graph)
    from documentation_graphs import collect_graph_nodes
    node_rows, graph_gaps = collect_graph_nodes(root, [registration for registration, _ in graphs.values()])
    for node in node_rows:
        add('graph-node:' + node['graph'] + ':' + node['name'] + ':' + node['source'] + ':' + str(node['line']),
            'graph-node', 'Registered builder node: ' + node['name'], node['source'], details=node)
    node_source = 'src/ravel/workflow/graph_nodes.py'
    for category in ('KINDS', 'REQUIRED_NODES'):
        for name in literal(root / node_source, category):
            add('graph-node:' + category.lower() + ':' + name, 'graph-node', category.lower() + ': ' + name,
                node_source, details={'category': category, 'name': name})
    for path in sorted((root / 'src/ravel').rglob('*.py')):
        source = path.relative_to(root).as_posix()
        add('module:' + source, 'module', module_description(path), source,
            home='docs/architecture/controller.md' if '/controller/' in source else None)

    for registration in effective_roles(root):
        role = registration['card']
        name = role['id']
        add('role:' + name, 'role', role.get('purpose', role.get('description', role.get('title', name))), registration['source'],
            details={key: value for key, value in role.items() if key in ('family', 'model', 'risk', 'independence', 'output', 'stop')})
    seat_source = 'src/ravel/data/controller/engagement/policy.json'
    seats = json_source(root, seat_source)
    for name, declaration in sorted(seats['seat_plans'].items()):
        add('seat:' + name, 'seat', 'Engagement seat plan: ' + name, seat_source, details=declaration)
    for name, declaration in sorted(seats['dynamic_seat_roles'].items()):
        add('seat:dynamic:' + name, 'seat', 'Dynamic engagement role binding: ' + name, seat_source, details=declaration)

    manifest = toolchain.view(root)
    for group in sorted(manifest['groups'], key=lambda row: row['id']):
        source = 'native/setup/groups/' + group['id'] + '.json'
        if not (root / source).is_file():
            source = 'native/setup/toolchain-manifest.json'
        add('installer:' + group['id'], 'installer-component', group['title'], source,
            details={'platforms': group.get('platforms'), 'depends_on': group.get('depends_on', []),
                     'qualification': group.get('qualification'), 'check_count': len(group.get('checks', []))})
        for index, check in enumerate(group.get('checks', [])):
            add('doctor:' + group['id'] + ':' + str(index), 'doctor-check', check.get('description', check.get('kind', 'Toolchain check')),
                source, details=check, scope='probe-declaration')
    for base in ('scripts', 'native'):
        for path in sorted((root / base).rglob('*')):
            if path.suffix in ('.py', '.sh') and path.is_file() and '__pycache__' not in path.parts:
                source = path.relative_to(root).as_posix()
                if names_any(held, source):
                    continue
                add('build-tool:' + source, 'build-tool', module_description(path) if path.suffix == '.py' else
                    'Installation or maintenance shell entry point: ' + path.name, source)
    for relative in ('native/setup/toolchain-manifest.json', 'environment/site-profiles.json',
                     'environment/python/installation.json', 'src/ravel/data/instructions/manifests.json',
                     'src/ravel/data/site_tools/policy.json', 'src/ravel/data/agents/sanctioned.json'):
        document = json_source(root, relative)
        add('manifest:' + relative, 'manifest', document.get('description', document.get('kind', Path(relative).name)),
            relative, details={'top_level_keys': sorted(document)})
    schema_gaps = []
    operator_source = 'src/ravel/controller/authority/operator.py'
    validator_checkins = literal(root / operator_source, 'MACHINE_CHECKINS')
    operator_schema = json_source(root, 'src/ravel/data/controller/schemas/operator-config.v1.json')
    schema_checkins = operator_schema['properties']['machine_checkins']['items']['enum']
    if set(validator_checkins) != set(schema_checkins):
        schema_gaps.append({'field': 'operator.machine_checkins', 'schema_source': 'src/ravel/data/controller/schemas/operator-config.v1.json',
                            'validator_source': operator_source, 'schema_values': sorted(schema_checkins),
                            'validator_values': sorted(validator_checkins),
                            'scope': 'Declared schema and validator vocabularies, each linked to its source.'})
    # Pin the generator and extractor as source inputs, excluding their outputs.
    pin('scripts/maintenance/documentation_parsers.py')
    return {'schema_version': 1, 'kind': 'documentation-inventory',
            'scope': 'Enumerated source declarations with documentation and source identities.',
            'counts': dict(sorted(Counter(row['kind'] for row in entries.values()).items())),
            'entries': sorted(entries.values(), key=lambda row: row['id']),
            'source_pins': sorted(pins.values(), key=lambda row: row['path']),
            'capability_prerequisites': structural_details(capabilities['prerequisite_sets'], 'src/ravel/data/backends/census.json'),
            'configuration_census': 'Named JSON-schema properties and required/dependency names, including conditional branches, confined cross-file references and named fields below typed dynamic map positions; model/transport record vocabularies; site defaults; module-level uppercase *KEYS/*FIELDS/*DEFAULTS/*SETTINGS/*OPTIONS declarations; and named process-environment reads in Python sources. Literal/constant names, finite source loops, environment parameter defaults and constructor environment aliases are enumerated. Runtime-selected environment names and open map positions are explicit typed boundaries. Dynamic map positions and runtime-selected names retain their source expressions.',
            'configuration_gaps': configuration_gaps, 'non_vocabulary_declarations': non_vocabulary_declarations,
            'schema_reference_gaps': schema_reference_gaps, 'schema_references': schema_references,
            'configuration_dynamic_boundaries': configuration_dynamic_boundaries,
            'environment_dynamic_reads': environment_dynamic_reads, 'environment_gaps': environment_gaps,
            'scope_definitions': {'registration': 'Source registration and its governing contract.',
                                  'parser-declaration': 'Parser declaration; command handling and operation admission remain separate.',
                                  'conditional-source-declaration': 'Parser declaration under its runtime source predicate.',
                                  'configuration-contract': 'Declared configuration schema; values must satisfy current validators.',
                                  'discovery-only': 'Discovery vocabulary and applicability predicate; execution requires operation admission.',
                                  'probe-declaration': 'Declared readiness check; run doctor for probe results.',
                                  'environment-read': 'Named process-environment input read, with runtime-selected names reported separately.',
                                  'named-field-vocabulary': 'Named source field vocabulary for records and operator settings; its owning validator governs acceptance.'},
            'parser_gaps': parser_gaps, 'parser_context_gaps': parser_context_gaps, 'graph_gaps': graph_gaps,
            'schema_gaps': schema_gaps, 'catalogue_gaps': catalogue_gaps,
            'compute_authorized': False, 'physics_validated': False}


def render_markdown(value):
    lines = ['# Documentation inventory', '', GENERATED_INDEX_MARKER, '',
             'This reference maps source declarations to documentation entries and narrative guides.',
             'Descriptions identify source declarations. Readiness checks and scientific results carry their own evidence.',
             'Source hashes and declarations are in [the JSON index](documentation-inventory.json),',
             '[command records](documentation-command-inventory.json) and [configuration records](documentation-configuration-inventory.json).',
             'Refresh all three snapshots with `python scripts/maintenance/render_documentation_inventory.py --write`;',
             '`--check` reports source, membership, content or documentation drift.', '',
             'The [parser reference](../cli/commands.md) records parser hierarchies, entry points,',
             'positional arguments, options and typed source constraints. Fixed numeric and boolean',
             'defaults remain exact; textual help/default/choice metadata points to its source declaration.',
             'Expressions marked `source:` remain expressions;',
             'the inventory reads their declared source syntax.', '',
             '| Declaration kind | Count |', '|---|---:|']
    for kind, count in value['counts'].items():
        lines.append('| ' + kind + ' | ' + str(count) + ' |')
    lines.extend(['', '## Coverage method', '',
        'The catalogue join is enumerated independently of these checked snapshots. Source parsers are',
        'walked as syntax, including finite loops, aliases and parser helpers. Task and operator schema',
        'properties include nested and conditional keys. Site defaults, model and transport record',
        'vocabularies, graph registrations/nodes, roles, seat plans, installation checks, manifests,',
        'maintenance tools and the complete Python module roster are retained. Builder-node declarations',
        'are counted as source declarations; computed runtime node expansions remain explicit graph gaps.',
        value.get('configuration_census', ''),
        'Unresolved named field declarations are recorded as configuration gaps in the JSON index.',
        'A new, removed or changed source entry changes the expected snapshot; a missing document or',
        'anchor also fails the gate. Original source pins exclude generated atlas/document hashes',
        'to keep source pins stable across regeneration. The gate checks documentation completeness.', '',
        '## Parser census', ''])
    if value['parser_gaps']:
        for gap in value['parser_gaps']:
            lines.append('- ' + cell(gap))
    else:
        lines.append('Every parser declaration in the source census has a documentation entry.')
    if value.get('schema_gaps'):
        lines.extend(['', '## Schema and validator vocabularies', ''])
        for gap in value['schema_gaps']:
            lines.append('- `' + gap['field'] + '`: schema values ' + cell(gap['schema_values']) +
                         '; validator values ' + cell(gap['validator_values']) + '. ' + gap['scope'])
    if value.get('catalogue_gaps'):
        lines.extend(['', '## Conditional catalogue declarations', '',
                      'These catalogue items have only conditional source parser declarations.',
                      'Their runtime predicates govern dispatch.', ''])
        for gap in value['catalogue_gaps']:
            lines.append('- `' + cell(gap['capability_id']) + '`: ' + cell(gap['availability']) + ' [Source](../../' + gap['source'] + ').')
    for kind in value['counts']:
        if kind in ('parser', 'command', 'option'):
            continue
        lines.extend(['', '## ' + kind.replace('-', ' ').title(), '', '| Entry | Description | Source | Guide |', '|---|---|---|---|'])
        for row in value['entries']:
            if row['kind'] != kind:
                continue
            home = row['docs'][1] if len(row['docs']) > 1 else row['docs'][0]
            lines.append('| <a id="' + anchor(row['id']) + '"></a>`' + cell(row['id']) + '` | ' + cell(row['summary']) +
                         ' | [' + cell(row['source']) + '](../../' + row['source'] + ') | [Guide](../../' + home + ') |')
    return '\n'.join(lines) + '\n'


def snapshot_outputs(value):
    command_rows = [row for row in value['entries'] if row['kind'] in ('parser', 'command', 'option')]
    config_rows = [row for row in value['entries'] if row['kind'] in ('config-key', 'config-keyset')]
    main = {key: child for key, child in value.items() if key != 'entries'}
    main['entries'] = [row for row in value['entries'] if row['kind'] not in ('parser', 'command', 'option', 'config-key', 'config-keyset')]
    main['parts'] = [{'path': path, 'entries': len(rows)} for path, rows in ((COMMAND_JSON, command_rows), (CONFIG_JSON, config_rows))]
    return {OUTPUT: encode(main), COMMAND_JSON: encode({'schema_version': 1, 'kind': 'documentation-command-inventory', 'entries': command_rows}),
            CONFIG_JSON: encode({'schema_version': 1, 'kind': 'documentation-configuration-inventory', 'entries': config_rows}),
            MARKDOWN: render_markdown(value), COMMANDS: render_commands(value)}


def render_commands(value):
    lines = ['# Parser command reference', '', GENERATED_INDEX_MARKER, '',
             'These entries describe the actual parser declarations in the source tree, including module',
             'entry points and installation/maintenance commands. Use [the CLI guide](../cli.md) for the',
             'ordinary workflow and [the inventory](../reference/documentation-inventory.md) for scope.',
             'Execution requires the handler operation contract and approval.',
             'Descriptions state typed declaration facts. Numeric/boolean/null defaults and numeric choices',
             'remain exact; textual help/default/choice values link to their source declaration.',
             '`source:` marks an unevaluated expression; runtime defaults and conditional dispatch follow',
             'the named source. Standard argparse',
             '`-h`/`--help` is implicit unless the parser disables help. Positional arguments appear without `--`.',
             'Refresh with `python scripts/maintenance/render_documentation_inventory.py --write`.', '']
    rows = [row for row in value['entries'] if row['kind'] in ('parser', 'command', 'option')]
    for source in sorted({row['source'] for row in rows}):
        lines.extend(['', '## ' + source, '', '| Command or argument | Description | Constraints | Source |', '|---|---|---|---|'])
        for row in sorted((row for row in rows if row['source'] == source), key=lambda row: (
                row['details']['command'], row['kind'] == 'option', row['id'])):
            details = row['details']
            label = details['command']
            if row['kind'] == 'option':
                label += ' ' + ', '.join(details['names'])
            constraints = details.get('constraints', {})
            constraints_text = '; '.join(key + '=' + str(value)
                                for key, value in constraints.items()) or row['kind']
            if 'availability' in details:
                constraints_text += '; availability=' + json.dumps(details['availability'], sort_keys=True)
            if details.get('dispatch_choices'):
                constraints_text += '; dispatch choices=' + ', '.join(details['dispatch_choices'])
            lines.append('| <a id="' + anchor(row['id']) + '"></a>`' + cell(label) + '` | ' + cell(row['summary']) +
                         ' | ' + cell(constraints_text) + ' | [' + str(details['line']) + '](../../' + source + '#L' + str(details['line']) + ') |')
    return '\n'.join(lines) + '\n'


def documentation_errors(root, value, rendered=None):
    """Validate item-level entries and their narrative document targets."""
    root = Path(root)
    rendered = rendered or {}
    errors = []
    pages = {}
    ids = [row['id'] for row in value['entries']]
    if len(ids) != len(set(ids)):
        errors.append('duplicate documentation ids')
    for row in value['entries']:
        if not row.get('docs'):
            errors.append('undocumented item: ' + row['id'])
        for reference in row.get('docs', []):
            page, _, fragment = reference.partition('#')
            if page not in pages:
                text = rendered.get(page)
                if text is None:
                    path = root / page
                    text = path.read_text(encoding='utf-8') if path.is_file() else None
                pages[page] = (None if text is None else
                               set(re.findall(r'id="([^"]+)"', text)) |
                               {slug(match.group(1)) for match in re.finditer(r'^#{1,6}\s+(.+)$', text, re.M)})
            anchors = pages[page]
            if anchors is None:
                errors.append('missing documentation page: ' + page)
            elif fragment and fragment not in anchors:
                errors.append('missing documentation entry: ' + reference)
    for category, label in (
            ('parser_gaps', 'parser declarations'), ('parser_context_gaps', 'parser contexts'),
            ('graph_gaps', 'graph declarations'), ('configuration_gaps', 'configuration declarations'),
            ('schema_reference_gaps', 'schema references'), ('environment_gaps', 'environment reads')):
        if value.get(category):
            errors.append('unresolved ' + label + ': ' + str(len(value[category])))
    return sorted(set(errors))


def snapshot_errors(root=ROOT, expected=None):
    root = Path(root)
    value = expected if expected is not None else inventory(root)
    outputs = snapshot_outputs(value)
    errors = documentation_errors(root, value)
    from documentation_references import errors as authored_errors
    errors.extend('stale authored ' + row['kind'] + ' reference: ' + row['source'] + ':' + str(row['line']) + ' ' + row['reference']
                  for row in authored_errors(root, value))
    for path, text in outputs.items():
        actual = root / path
        if not actual.is_file() or actual.read_text(encoding='utf-8') != text:
            errors.append('stale documentation snapshot: ' + path)
    return sorted(set(errors))


def source_audit_documentation(source_value, projection, public_value=None):
    """Join a full audit to actual source-only or released documentation anchors."""
    value = deepcopy(source_value)
    released = public_value['entries'] if public_value is not None else projection['public_entries']
    docs = {row['id']: row['docs'] for row in [*released, *projection['entries']]}
    for row in value['entries']:
        row['docs'] = docs[row['id']]
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='refuse stale or missing documentation snapshots')
    action.add_argument('--write', action='store_true', help='refresh source-derived reference snapshots')
    parser.add_argument('--root', type=Path, default=ROOT, help='selected source checkout')
    parser.add_argument('--source-tree', action='store_true', help='include undistributed declarations; requires --json-output')
    parser.add_argument('--json-output', type=Path, help='write only an audit inventory JSON at this explicit destination')
    parser.add_argument('--documentation-json', type=Path, help='join a full source audit to this checked source-projection documentation')
    args = parser.parse_args(argv)
    if args.source_tree and not args.json_output:
        parser.error('--source-tree requires --json-output to preserve public snapshots')
    value = inventory(args.root, source_tree=args.source_tree)
    if args.json_output:
        if not args.write:
            parser.error('--json-output requires --write')
        if args.documentation_json:
            value = source_audit_documentation(value, json.loads(args.documentation_json.read_text(encoding='utf-8')))
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(encode(value), encoding='utf-8')
        print(encode({'counts': value['counts'], 'entries': len(value['entries']), 'parser_gaps': value['parser_gaps']}).strip())
        return 0
    outputs = snapshot_outputs(value)
    if args.write:
        for relative, text in outputs.items():
            target = args.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        errors = snapshot_errors(args.root, value)
    else:
        errors = snapshot_errors(args.root, value)
    print(encode({'counts': value['counts'], 'entries': len(value['entries']),
                  'parser_gaps': len(value['parser_gaps']), 'errors': errors}).strip())
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
