"""One source-derived capability view for every deciding seat.

Only metadata is read. Registration, historical qualification, current readiness
and execution authority are distinct. Cost never removes a relevant capability.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

POLICY = {
    'selection': 'Match the whole request against applicability before considering cost.',
    'cost': 'Cost changes placement, staging or approval; never silently omit a required capability.',
    'availability': 'Unknown installation, license or qualification is not availability. Retain the obligation '
                    'and acquire, qualify or propose an explicitly qualified fallback.',
    'authority': 'Catalogue presence and recall suggestions authorize no execution and certify no physics.',
}


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def _locations(source_root):
    package = Path(__file__).resolve().parents[1]
    if source_root is not None:
        root = Path(source_root).absolute()
        return root, root / 'src/ravel'
    return (package.parent.parent if package.parent.name == 'src' else package.parent), package


def _prerequisites(*, groups=(), licenses=(), qualification=None, inputs=()):
    return {'installed': 'not_observed', 'licensed': 'not_observed' if licenses else 'no_requirement_declared',
            'qualified': 'not_observed', 'groups': sorted(set(groups)), 'licenses': list(licenses),
            'qualification': qualification or {'status': 'registered', 'scope': 'No execution evidence inferred.'},
            'inputs': list(inputs)}


def _cost(signature):
    effects = set(signature.get('effects', []))
    if 'generates_events' in effects:
        return 'generation'
    cost = signature.get('cost_class')
    if isinstance(cost, str) and cost:
        return cost
    unit = signature.get('cost', {}).get('unit')
    # Keep the actual declared resource class instead of inventing a numerical forecast.
    return 'declared:' + unit if unit else 'unknown'


def catalogue(*, source_root=None):
    """Join existing inventories, retaining every declaration and its source scope.

    The generated atlas supplies knowledge links and curation; dispatcher,
    signatures, route specs and installer/census rows close its inventory gaps.
    No allowlist, rank limit, cost filter or native readiness probe is used.
    """
    from ravel.workflow import capability_routing as routing
    from ravel.workflow.operation_registration import read_signatures
    from ravel.workflow.knowledge import load_atlas
    from ravel.setup import manifest as mf
    from importlib import import_module
    select = import_module("ravel.controller.routes.select")

    root, package = _locations(source_root)
    pins = {}

    def pin(path):
        path = Path(path)
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError('capability source must be a regular file without symlinks: ' + str(path))
        relative = path.relative_to(root).as_posix()
        value = {'path': relative, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        pins[relative] = value
        return value

    pin(package / 'workflow/capability_catalogue.py')
    atlas_path = package / 'data/knowledge/atlas.json'
    atlas = load_atlas(atlas_path)
    pin(atlas_path)
    atlas_rows = {row['id']: row for row in atlas['entries']}
    signature_path = package / 'data/operation_signatures.json'
    signatures = read_signatures(signature_path)
    pin(signature_path)
    routed = routing.catalogue(source_root)
    for value in routed['source_pins']:
        pin(value['path'])
    manifest_path = root / 'native/setup/toolchain-manifest.json'
    manifest = mf.view(root) if manifest_path.is_file() else {'groups': [], 'operations': []}
    # Wheels retain atlas tool declarations, without a native/setup tree.
    if manifest_path.is_file():
        pin(manifest_path)
        for path in sorted((root / 'native/setup/groups').glob('*.json')):
            pin(path)
    groups = {g['id']: g for g in manifest.get('groups', [])}
    bindings = manifest.get('operations', [])
    if isinstance(bindings, list):
        bindings = {row['mode']: row.get('groups', []) for row in bindings}
    bindings = {mode: value.get('groups', []) if isinstance(value, dict) else value
                for mode, value in bindings.items()}
    rows = {}

    def add(identity, kind, summary, source, *, applicability=None, prerequisites=None,
            produces=None, cost_class='unknown', links=None, **extra):
        if identity in rows:
            raise ValueError('duplicate capability identity: ' + identity)
        rows[identity] = {'id': identity, 'kind': kind, 'summary': summary, 'source': source,
                          'applicability': applicability or {'scope': 'declared_only'},
                          'prerequisites': prerequisites or _prerequisites(),
                          'produces': produces if produces is not None else {'status': 'not_declared'},
                          'cost_class': cost_class, 'links': links or {}, **extra}
        return rows[identity]

    dispatch = {row['mode']: row for row in routed['operations']}
    operation_names = set(signatures) | set(dispatch) | {
        key[3:] for key, value in atlas_rows.items() if value['kind'] == 'op'}
    for mode in sorted(operation_names):
        knowledge = atlas_rows.get('op:' + mode, {})
        operation = knowledge.get('op', {})
        selected = dispatch.get(mode, {})
        signature = signatures.get(mode, {})
        descriptor = selected.get('descriptor')
        required = bindings.get(mode, [])
        licenses = [license_ for group in required for license_ in groups.get(group, {}).get('licenses', [])]
        prerequisites = _prerequisites(groups=required, licenses=licenses,
            qualification={'status': operation.get('validation_tier', 'registered'),
                           'scope': 'Historical operation tier; current inputs and runtime still require qualification.'},
            inputs=signature.get('consumes', operation.get('inputs', (descriptor or {}).get('inputs', []))))
        prerequisites['implementation'] = selected.get('status', 'declared_not_inspected')
        source = (pin(selected['source']['path']) if selected.get('source') else
                  pin(signature_path) if signature else knowledge['source'])
        add('op:' + mode, 'operation', (descriptor or {}).get('summary', knowledge.get('summary', signature.get('summary', mode))),
            source, applicability={**operation.get('applicability', {'scope': 'declared_only'}),
                                    **((descriptor or {}).get('applicability', {})),
                                    'use_when': operation.get('use_when', []),
                                    'do_not_use_when': operation.get('do_not_use_when', [])},
            prerequisites=prerequisites, produces=signature.get('produces', operation.get('outputs', (descriptor or {}).get('outputs'))),
            cost_class=_cost(signature) if signature else operation.get('cost_class', 'unknown'),
            links=knowledge.get('links', {}), descriptor=descriptor, cost=signature.get('cost', {}))

    # Tool rows from the atlas include installer groups, source census and descriptor
    # vocabulary. Preserve each identity: a vocabulary term is not an installed engine.
    for identity, item in sorted(atlas_rows.items()):
        if item['kind'] not in ('tool', 'cmd'):
            continue
        kind = 'tool' if item['kind'] == 'tool' else 'command'
        group_ids = ([item['installer_group']] if item.get('installer_group') else
                     [value.removeprefix('tool:') for value in item.get('links', {}).get('installer_groups', [])])
        required_licenses = item.get('licenses', [license_ for gid in group_ids
                                                for license_ in groups.get(gid, {}).get('licenses', [])])
        add(identity, kind, item['summary'], item['source'],
            applicability={'scope': 'declared_only', 'operations': item.get('links', {}).get('operations', [])},
            prerequisites=_prerequisites(groups=group_ids, licenses=required_licenses,
                qualification={'status': item.get('qualification_status', 'registered'),
                               'scope': item.get('qualification_scope', 'Registration only; no readiness inferred.')}),
            links=item.get('links', {}))
    for gid, group in sorted(groups.items()):
        identity = 'tool:' + gid
        if identity not in rows:
            add(identity, 'tool', group['title'], pin(manifest_path),
                prerequisites=_prerequisites(groups=[gid], licenses=group.get('licenses', []),
                                             qualification=group.get('qualification')))
        rows[identity]['prerequisites']['depends_on'] = group.get('depends_on', [])
        rows[identity]['prerequisites']['platforms'] = group.get('platforms', [])
        rows[identity]['prerequisites']['platform_qualification'] = group.get('qualification', {})
    census_path = package / 'data/backends/census.json'
    from ravel.workflow.tool_census import load_census
    census = load_census(census_path, catalog=None)
    census_source = pin(census_path)
    for item in census['tools']:
        identity = 'tool:' + item['id']
        if identity not in rows:
            add(identity, 'tool', item.get('purpose', item.get('title', item['id'])), census_source,
                prerequisites=_prerequisites(qualification={'status': item['status'], 'scope': item['evidence_scope']}))
        rows[identity]['prerequisites']['doctor_checks'] = item['doctor_checks']
        rows[identity]['prerequisites']['requirement'] = item['requirement']
    for backend in census['backends']:
        tool = rows['tool:' + backend['tool_id']]
        tool['applicability'].setdefault('backends', []).append({key: backend[key] for key in
            ('id', 'signal_bases', 'families', 'assumptions', 'coverage_scope')})

    # The agent-facing affordance census is a separate registered tool population,
    # including typed workspace/retrieval tools and explicitly absent affordances.
    # Keep it alongside native engines rather than mistaking one census for both.
    from ravel.workflow import toolbelt
    affordance_path = package / 'data/agents/affordances.json'
    affordance_source = pin(affordance_path)
    pin(package / 'workflow/toolbelt.py')
    pin(package / 'workflow/role_registry.py')
    for path in sorted((package / 'data/roles').rglob('*.json')):
        pin(path)
    affordances = (toolbelt.census(atlas=atlas) if source_root is None else json.loads(affordance_path.read_bytes()))
    affordance_groups = {}
    for declaration in affordances['rows']:
        affordance_groups.setdefault(declaration['tool'], []).append(declaration)
    for name, declarations in sorted(affordance_groups.items()):
        execution_paths = sorted({row['executes_through'] for row in declarations if row['executes_through']})
        schema_sources = sorted({row['schema_source'] for row in declarations if row['schema_source']})
        add('tool:affordance/' + name, 'tool', name + ': ' + (', '.join(execution_paths) or 'declared; execution unavailable'),
            affordance_source, applicability={'scope': 'role_affordance',
                'roles': sorted({row['role'] for row in declarations}),
                'declarations': [{key: value for key, value in row.items() if key != 'test'} for row in declarations]},
            produces={'schema_sources': schema_sources, 'execution_paths': execution_paths,
                      'scope': 'Role-dependent interface; inspect its declared output schema.'},
            cost_class='metadata' if execution_paths and all(path == 'structured_output' or path == 'knowledge_find'
                or path.startswith('broker:knowledge') for path in execution_paths) else 'unknown')
    # Source-selected route families and the built-in judgment route. No route
    # adapter is imported, and extra test registrations use the same specs API.
    if source_root is None:
        specs = select.load_specs()
        builtins = select.BUILTIN
    else:
        specs = [spec for path in sorted((package / 'data/controller/routes').glob('*.json'))
                 for spec in select._read_specs(path)]
        # The built-in route uses a symbolic constant: read its selected source AST.
        import ast
        tree = ast.parse((package / 'controller/routes/select.py').read_text())
        names = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == 'JUDGMENT':
                    names['JUDGMENT'] = ast.literal_eval(node.value)
                if node.targets[0].id == 'BUILTIN':
                    class Constants(ast.NodeTransformer):
                        def visit_Name(self, value):
                            return ast.copy_location(ast.Constant(names[value.id]), value) if value.id in names else value
                    builtins = ast.literal_eval(Constants().visit(node.value))
                    break
        else:
            raise ValueError('selected route source lacks BUILTIN')
    route_source = pin(package / 'controller/routes/select.py')
    for path in sorted((package / 'data/controller/routes').glob('*.json')):
        pin(path)
    for spec in [*specs, *builtins]:
        add('route:' + spec['id'], 'route', spec.get('description', spec.get('reason', spec['id'])), route_source,
            applicability={'scope': 'route_predicate', 'match': spec['match']},
            produces=[output for step in spec.get('steps', []) for output in step.get('outputs', [])],
            prerequisites=_prerequisites(inputs=spec.get('parameters', [])), cost_class='composite',
            links={'operations': sorted({'op:' + step['operation'] for step in spec.get('steps', []) if step.get('operation')})})
    # Focused planning commands not yet in a generated atlas remain visible now.
    for item in routed['planning_tools']:
        identity = 'cmd:' + item['mode']
        if identity not in rows:
            add(identity, 'command', item['summary'], pin(item['dispatch_source']['path']))
    from ravel.workflow.knowledge_atlas import literal
    for name, (_, summary) in literal(package / 'cli.py', 'FOCUSED_COMMANDS').items():
        if 'cmd:' + name not in rows:
            add('cmd:' + name, 'command', summary, pin(package / 'cli.py'))
    for operation in list(rows.values()):
        if operation['kind'] != 'operation':
            continue
        for term in (operation.get('descriptor') or {}).get('tools', []):
            identity = 'tool:descriptor/' + term
            if identity not in rows:
                add(identity, 'tool', 'Declared descriptor tool: ' + term,
                    pin(package / 'data/mode_descriptors.json'),
                    applicability={'scope': 'declared_only', 'operations': [operation['id']]})
            operation['links'].setdefault('tools', [])
            if identity not in operation['links']['tools']:
                operation['links']['tools'].append(identity)
    # Infer only contextual operation products, never a standalone engine's
    # scientific result. Installer and descriptor bindings already declare these
    # edges; keeping the producer identity prevents an invented tool contract.
    for operation in list(rows.values()):
        if operation['kind'] != 'operation':
            continue
        tool_ids = set(operation['links'].get('tools', [])) | {
            'tool:' + gid for gid in operation['prerequisites']['groups']}
        for identity in sorted(tool_ids):
            if identity in rows:
                tool = rows[identity]
                tool['links'].setdefault('operations', [])
                if operation['id'] not in tool['links']['operations']:
                    tool['links']['operations'].append(operation['id'])
                tool['applicability']['operations'] = sorted(tool['links']['operations'])
    for row in rows.values():
        if row['kind'] not in ('tool', 'command'):
            continue
        bound = [rows[identity] for identity in row['links'].get('operations', []) if identity in rows]
        if bound:
            row['produces'] = {'operation_products': [{'operation': item['id'], 'produces': item['produces']}
                                                     for item in sorted(bound, key=lambda item: item['id'])]}
            classes = sorted({str(item['cost_class']) for item in bound})
            row['cost_class'] = classes[0] if len(classes) == 1 else 'composite'
            row['cost_classes'] = classes
    # Normalize repeated prerequisites and provenance without dropping any fact.
    # The complete data remains inline even under a lean engagement scope.
    prerequisite_sets = {}
    for row in rows.values():
        value = row['prerequisites']
        key = digest(value)[:16]
        if key in prerequisite_sets and prerequisite_sets[key] != value:
            raise ValueError('prerequisite identity collision')
        prerequisite_sets[key] = value
        row['prerequisites'] = {'ref': key}
        source = row['source']
        row['source'] = {'path': source['path']}
        source_path = root / source['path']
        pins.setdefault(source['path'], pin(source_path) if source_path.is_file() else source)
        row['links'] = {key: values for key, values in row['links'].items()
                        if key in ('tools', 'operations', 'installer_groups', 'commands')}
    return {'schema_version': 1, 'kind': 'deciding-capability-catalogue',
            'prerequisite_sets': prerequisite_sets,
            'entries': sorted(rows.values(), key=lambda row: row['id']),
            'sources': sorted(pins.values(), key=lambda value: value['path']),
            'coverage': {kind: sorted(row['id'] for row in rows.values() if row['kind'] == kind)
                         for kind in ('route', 'operation', 'tool', 'command')},
            'compute_authorized': False, 'physics_validated': False}


_CACHE = {}


def _fingerprint(root, package, value):
    # Content, not mtimes, determines cache freshness. Directory rosters detect
    # new registrations even when no previously pinned member changed.
    paths = {root / pin['path'] for pin in value['sources']}
    for relative in ('data/controller/routes',):
        paths.update((package / relative).glob('*.json'))
    paths.update((root / 'native/setup/groups').glob('*.json'))
    from importlib import import_module
    registered = import_module('ravel.controller.routes.select').load_specs()
    observed = []
    for path in sorted(paths):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError('capability source must not contain symlinks: ' + str(path))
        observed.append((str(path), hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None))
    roster = sorted(path.relative_to(package).as_posix() for path in (package / 'data').rglob('*.json'))
    return digest({'files': observed, 'routes': registered, 'data_roster': roster})


def for_seat(seat_kind: str, *, source_root=None):
    """Complete catalogue data for any seat; new kinds cannot silently miss it."""
    if type(seat_kind) is not str or not seat_kind.strip():
        raise ValueError('capability context requires a nonblank seat kind')
    root, package = _locations(source_root)
    cached = _CACHE.get(str(package))
    if cached is not None and _fingerprint(root, package, cached[1]) == cached[0]:
        value = deepcopy(cached[1])
    else:
        value = catalogue(source_root=source_root)
        _CACHE[str(package)] = (_fingerprint(root, package, value), deepcopy(value))
    return {'schema_version': 1, 'kind': 'seat-capability-context', 'seat_kind': seat_kind,
            'catalogue_sha256': digest(value), 'catalogue': value, 'policy': dict(POLICY)}


def recall(prompt: str, *, context=None, availability=None):
    """Provisional capability plan using the routing inventory's applicability matcher.

    Availability is supplied, scoped evidence (keyed by catalogue ID), not inferred
    from a historical census or missing runtime. A failed prerequisite preserves the
    required operation and yields a qualified fallback, without executing it.
    This deterministic seam permits inert recall controls; it is not model recall.
    """
    from ravel.workflow.capability_routing import suggest
    if type(prompt) is not str or not prompt.strip():
        raise ValueError('recall requires the original request')
    context = context if context is not None else for_seat('planning')
    value = context['catalogue']
    if digest(value) != context['catalogue_sha256']:
        raise ValueError('capability catalogue digest mismatch')
    operations = {row['id'][3:]: {'mode': row['id'][3:], 'descriptor': row.get('descriptor')}
                  for row in value['entries'] if row['kind'] == 'operation'}
    by_id = {row['id']: row for row in value['entries']}
    steps = []
    for candidate in suggest(prompt, operations):
        identity = 'op:' + candidate['mode']
        evidence = (availability or {}).get(identity, {})
        missing = [key for key in ('installed', 'licensed', 'qualified') if evidence.get(key) is not True]
        alternative = by_id[identity]['applicability'].get('general_operation')
        fallback = None
        if missing:
            fallback = {'kind': 'qualify-prerequisites', 'requires': missing,
                        'candidate': 'op:' + alternative if alternative else identity,
                        'qualification_required': True, 'preserves_required_capability': identity,
                        'scope': 'Confirm applicability, obtain missing inputs or runtime and qualify before execution; '
                                 'a general alternative does not inherit the requested scientific claim.'}
        steps.append({'capability': identity, 'matched': candidate['matched'], 'cost_class': by_id[identity]['cost_class'],
                      'status': 'requires_qualification' if missing else 'candidate', 'fallback': fallback})
    return {'schema_version': 1, 'kind': 'capability-recall-plan', 'original_request': prompt,
            'catalogue_sha256': context['catalogue_sha256'], 'steps': steps,
            'compute_authorized': False, 'physics_validated': False}


def shards(context, *, max_bytes=384 * 1024):
    """Lossless bounded JSON pieces of the packet data, readable by the existing broker.

    Fragment paths locate exact values in the complete context. No capability is
    ranked or truncated; even a growing prerequisite/source census can be split.
    """
    if type(max_bytes) is not int or max_bytes < 1024:
        raise ValueError('capability shard byte bound must be an integer of at least 1024')
    if digest(context['catalogue']) != context['catalogue_sha256']:
        raise ValueError('capability catalogue digest mismatch')
    fragments = []
    budget = max_bytes - 512

    def split(path, value):
        fragment = {'path': path, 'value': value}
        if len(encode(fragment)) <= budget:
            fragments.append(fragment)
        elif isinstance(value, (dict, list)):
            fragments.append({'path': path, 'value': {} if isinstance(value, dict) else []})
            children = ((key, value[key]) for key in sorted(value)) if isinstance(value, dict) else enumerate(value)
            for key, child in children:
                split([*path, key], child)
        else:
            raise ValueError('one capability fact exceeds the broker-readable shard byte bound')

    # Split large objects before packing; the path records are ordinary JSON data.
    for key in sorted(context):
        if key != 'catalogue':
            split([key], context[key])
    for key in sorted(context['catalogue']):
        split(['catalogue', key], context['catalogue'][key])
    batches, current, size = [], [], 0
    for fragment in fragments:
        amount = len(encode(fragment)) + 1
        if current and size + amount > budget:
            batches.append(current)
            current, size = [], 0
        current.append(fragment)
        size += amount
    if current:
        batches.append(current)
    result = [{'schema_version': 1, 'kind': 'capability-data-shard',
               'catalogue_sha256': context['catalogue_sha256'], 'context_sha256': digest(context),
               'part': index, 'parts': len(batches),
               'fragments': batch} for index, batch in enumerate(batches)]
    if any(len(encode(row)) > max_bytes for row in result):
        raise ValueError('capability shard exceeds its declared byte bound')
    return result


def assemble(parts):
    """Reconstruct and verify complete packet data; incomplete shards never count."""
    if not parts or sorted(row.get('part', -1) for row in parts) != list(range(len(parts))):
        raise ValueError('complete distinct capability shards required')
    identity = parts[0]['catalogue_sha256']
    context_identity = parts[0]['context_sha256']
    result, seen = {}, set()
    for part in sorted(parts, key=lambda row: row['part']):
        if (part.get('kind') != 'capability-data-shard' or part.get('schema_version') != 1
                or part.get('parts') != len(parts) or part.get('catalogue_sha256') != identity
                or part.get('context_sha256') != context_identity):
            raise ValueError('capability shards disagree')
        for fragment in part['fragments']:
            path = fragment['path']
            if not path or tuple(path) in seen:
                raise ValueError('duplicate or empty capability fragment path')
            seen.add(tuple(path))
            current = result
            for index, key in enumerate(path):
                if isinstance(current, list):
                    if type(key) is not int or key < 0:
                        raise ValueError('invalid capability fragment list index')
                    while len(current) <= key:
                        current.append(None)
                if index == len(path) - 1:
                    current[key] = deepcopy(fragment['value'])
                else:
                    next_value = [] if type(path[index + 1]) is int else {}
                    if isinstance(current, dict):
                        current = current.setdefault(key, next_value)
                    else:
                        if current[key] is None:
                            current[key] = next_value
                        current = current[key]
    if (result.get('catalogue_sha256') != identity or digest(result['catalogue']) != identity
            or digest(result) != context_identity):
        raise ValueError('reassembled capability catalogue digest mismatch')
    return result
