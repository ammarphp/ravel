"""One effective typed card per role; deterministic host guidance, never authority.

Card authors can replace an explicit registry default at its reserved override
path. There is no filename-based discovery or second competing role identity.
The broker enforces tool scope; a generated profile is guidance, not a sandbox.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from ravel.paths import package_data_path, repository_root

SURFACES = ('claude', 'codex', 'gemini', 'antigravity', 'opencode', 'governed-node')
PROFILE_DIRS = {'claude': '.claude/agents', 'codex': '.codex/agents',
                'gemini': '.gemini/agents', 'antigravity': '.antigravity/agents',
                'opencode': '.opencode/agents', 'governed-node': '.ravel/roles'}
PANEL = ('physics-critic', 'skeptical-verifier', 'physics-decider', 'physics-improver')


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def registry_document(*, roles_root=None):
    root = Path(roles_root) if roles_root is not None else package_data_path('roles')
    path = root / 'registry.json'
    if not path.is_file() and roles_root is not None:
        path = package_data_path('roles', 'registry.json')
    from .role_registration import apply
    from .higgs_registration import compose
    # Explicit role fragments first, then the source-owned scalar role fragments; both are append-only.
    return compose(apply(path.parent, json.loads(path.read_text())), path)


def _identity(role_id, document):
    role_id = document['aliases'].get(role_id, role_id)
    if role_id not in document['roles']:
        raise ValueError('unregistered role: ' + str(role_id))
    return role_id


def load(role_id: str, *, document=None, roles_root=None) -> dict:
    document = registry_document(roles_root=roles_root) if document is None else document
    identity = _identity(role_id, document)
    row = document['roles'][identity]
    root = Path(roles_root) if roles_root is not None else package_data_path('roles')
    override = row.get('override')
    if override:
        relative = Path(override)
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix() != f'cards/{identity}.json':
            raise ValueError('invalid card override path: ' + identity)
        path = root / relative
        if not path.is_file() and roles_root is not None and not (root / 'registry.json').is_file():
            path = package_data_path('roles') / relative  # the same fallback as registry_document
        if path.is_symlink():
            raise ValueError('regular card override required: ' + identity)
        card = json.loads(path.read_text()) if path.is_file() else row['card']
    else:
        card = row['card']
    if card.get('id') != identity:
        raise ValueError('card identity differs from registry: ' + identity)
    return deepcopy(card)


def all_cards(*, document=None, roles_root=None) -> list[dict]:
    document = registry_document(roles_root=roles_root) if document is None else document
    return [load(identity, document=document, roles_root=roles_root) for identity in sorted(document['roles'])]


def card_sha256(role_id: str, *, document=None, roles_root=None) -> str:
    return _digest(load(role_id, document=document, roles_root=roles_root))


def self_checks(role_id, *, document=None, roles_root=None):
    """A producer must check the union of its reviewing cards' obligations."""
    card = load(role_id, document=document, roles_root=roles_root)
    identities = {identity for reviewer in card['reviewed_by']
                  for identity in load(reviewer, document=document, roles_root=roles_root)['must_check']}
    return resolve_self_checks(identities)


def resolve_self_checks(identities):
    """Trap knowledge references require the declared full trap-sweep validator."""
    from .run_validator_checks import TRAP_CHECK
    checks = set()
    for identity in identities:
        if identity.startswith('trap:'):
            if not re.fullmatch(r'trap:T(?:[1-9]|1[0-2])', identity):
                raise ValueError('unknown trap self-check reference')
            checks.add(TRAP_CHECK)
        else:
            checks.add(identity)
    return sorted(checks)


def registry_sha256(*, document=None, roles_root=None):
    document = registry_document(roles_root=roles_root) if document is None else document
    return _digest({'registry': document, 'effective_cards': all_cards(document=document, roles_root=roles_root)})


def request_digest(request, *, document=None, roles_root=None):
    """Worker consumers include this commitment in their immutable request."""
    return _digest({'request': request, 'card_sha256': card_sha256(request['role'], document=document, roles_root=roles_root),
                    'registry_sha256': registry_sha256(document=document, roles_root=roles_root)})


def resolve_names(names, *, document=None):
    document = registry_document() if document is None else document
    return {name: _identity(name, document) for name in names}


def request_requires(role_id):
    return {'tools': load(role_id)['requires']['tools']}


def _schema_errors(value, path):
    from jsonschema import Draft202012Validator
    schema = json.loads(path.read_text())
    return [('/'.join(str(p) for p in e.absolute_path) or '$') + ': ' + e.message
            for e in Draft202012Validator(schema).iter_errors(value)]


def validate_output(identity, record):
    if not re.fullmatch(r'[a-z][a-z0-9-]*\.v[0-9]+', identity):
        return ['invalid output schema ID']
    path = package_data_path('roles', 'schema', 'outputs', identity + '.json')
    return _schema_errors(record, path) if path.is_file() else ['unresolved output schema: ' + identity]


def validate_qualification(record):
    errors = _schema_errors(record, package_data_path('roles', 'schema', 'qualification-record.json'))
    if not errors and record['status'] == 'qualified' and any(r['result'] != 'pass' for r in record['battery']):
        errors.append('qualified cell has a failing battery receipt')
    return errors


def _known_ids(root=None):
    path = (Path(root) / 'src/ravel/data/knowledge/atlas.json' if root is not None
            else package_data_path('knowledge', 'atlas.json'))
    return {r['id'] for r in json.loads(path.read_text())['entries']}


def validate_card(card, *, root=None, known_ids=None):
    errors = _schema_errors(card, package_data_path('roles', 'schema', 'card.json'))
    if errors:
        return errors
    ids = _known_ids(root) if known_ids is None else set(known_ids)
    for identity in [*card['must_check'], *card['knowledge']['must_read']]:
        if identity not in ids:
            errors.append('unresolved knowledge ID: ' + identity)
    if not package_data_path('roles', 'schema', 'outputs', card['output']['schema'] + '.json').is_file():
        errors.append('unresolved output schema: ' + card['output']['schema'])
    if not re.fullmatch(r'[a-z][a-z0-9-]*\.v[0-9]+', card['output']['schema']):
        errors.append('invalid output schema ID')
    reviewer = card['independence']['kind'] in ('voting', 'specialist')
    if reviewer:
        for key in ('lessons', 'producer_headline'):
            if key not in card['knowledge']['forbidden'] or key not in card['sees']['forbidden_inputs']:
                errors.append('reviewer must forbid ' + key)
        if any('lessons' in s for s in card['knowledge']['derive'] + card['knowledge']['must_read']):
            errors.append('reviewer cannot derive or read lessons')
    from ravel.validation.higgs_checks import card_errors
    errors += card_errors(card)
    cap = 2700 if card['family'] in ('production', 'consult', 'research', 'writing', 'upstream') else 1200
    if card['stop']['max_wall_seconds'] > cap:
        errors.append('role wall ceiling exceeds family cap')
    if card['id'] == 'literature-scout' and card['model']['tier'] != 'judgment':
        errors.append('literature-scout requires judgment tier')
    budget = card['stop'].get('evidence_budget', 0)
    if budget > 0 and (card['requires']['tools'] == 'none' or
                       card['requires']['isolation_min'] not in ('ravel-sandbox', 'os-sandbox')):
        errors.append('positive evidence budget requires a tool-capable sandbox route')
    if card['independence']['kind'] == 'voting' and budget == 0:
        if card['requires']['tools'] != 'none' or card['requires']['isolation_min'] != 'cli-policy':
            errors.append('zero-budget voting card requires tools none and cli-policy isolation')
    from ravel.validation.sm_checks import registered_review_card_errors
    errors += registered_review_card_errors(card)
    return errors


def _source_roles(root):
    """Omissions are checked against actual current producer vocabularies too."""
    found = set()
    for relative in ('agent_graph.py', 'review_context.py', 'physics_review.py', 'agentrivet_runtime.py', 'sfitter_workflow.py'):
        path = Path(root) / 'src/ravel/workflow' / relative
        if not path.is_file():
            continue
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ROLES' for t in node.targets):
                vocabulary = ast.literal_eval(node.value)
                if relative == 'sfitter_workflow.py':
                    found.update(r for roles in vocabulary.values() for r in roles)
                else:
                    found.update(vocabulary)
    path = Path(root) / 'src/ravel/data/research/protocol-default.json'
    if path.is_file():
        found.update(r for s in json.loads(path.read_text())['stages'] for r in s['roles'])
    path = Path(root) / 'src/ravel/data/operation_signatures.json'
    if path.is_file():
        found.update('consult-' + tool for operation in json.loads(path.read_text())['operations'].values()
                     for tool in operation.get('tools', []))
    found.update(('spec-author', 'card-author', 'model-author', 'statistical-model-author', 'refutation-verifier'))
    return found


def validate_registry(document=None, *, root=None, roles_root=None):
    try:
        document = registry_document(roles_root=roles_root) if document is None else document
        errors = []
        if set(document) != {'schema_version', 'kind', 'required_roles', 'aliases', 'roles'} or document['schema_version'] != 1 or document['kind'] != 'role-registry':
            return ['closed role-registry envelope required']
        if len(document['required_roles']) != len(set(document['required_roles'])):
            errors.append('duplicate required role')
        required = set(document['required_roles'])
        # The packaged source contract remains the minimum when validating a candidate.
        required.update(registry_document()['required_roles'])
        for identity in sorted(required - set(document['roles'])):
            errors.append('omitted role: ' + identity)
        for alias, identity in document['aliases'].items():
            if identity not in document['roles']:
                errors.append('unresolved role alias: ' + alias)
            if alias in document['roles'] and alias != identity:
                errors.append('alias shadows a registered role: ' + alias)
        source = Path(root) if root is not None else repository_root()
        from ravel.setup import manifest as mf
        release = mf.load(source)[0] if source is not None and mf.manifest_path(source).is_file() else {}
        for identity in _source_roles(source) if source is not None else ():
            if mf.release_mentions(release, identity):
                continue
            if document['aliases'].get(identity, identity) not in document['roles']:
                errors.append('unregistered source role: ' + identity)
        ids = _known_ids(root)
        for card in all_cards(document=document, roles_root=roles_root):
            errors += [card['id'] + ': ' + e for e in validate_card(card, known_ids=ids)]
            for identity in card['reviewed_by'] + [c['role'] for c in card['knowledge']['consult'] if c['role'] != 'by_failure_class']:
                if document['aliases'].get(identity, identity) not in document['roles']:
                    errors.append(card['id'] + ': unresolved role reference: ' + identity)
        cards_root = Path(roles_root) if roles_root is not None else package_data_path('roles')
        declared = {r['override'] for r in document['roles'].values() if r.get('override')}
        errors += ['unlisted card override: ' + p.relative_to(cards_root).as_posix()
                   for p in (cards_root / 'cards').glob('*.json') if p.relative_to(cards_root).as_posix() not in declared]
        return sorted(set(errors))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return ['cannot validate role registry: ' + str(exc)]


def finding_effect(item, *, resolve=None):
    """Only a resolver's evidence IDs confer a blocking evidence class.

    A pending request holds the finding while its test is unresolved. A reviewer's
    declared class or declared failed test grants no evidence authority.
    """
    checked = {**item, 'evidence_class': 'opinion'}
    errors = validate_output('findings.v1', {'schema_version': 1, 'kind': 'findings', 'items': [checked], 'handoff': None})
    if errors:
        raise ValueError('; '.join(errors))
    if item['severity'] != 'A':
        return 'advisory'
    request = item.get('request')
    if request:
        if request['result'] in ('pending', 'unresolved'):
            return 'wait_for_test'
    classes = [resolve(identity) if resolve is not None else 'opinion' for identity in item['evidence']]
    return 'blocking' if any(c in ('new_receipt', 'code_check') for c in classes) else 'advisory'


def qualification_labels(assignments, *, delegated=False, records=()):
    """CHECK-IN 1 projection: label the exact role/model/transport/effort cell.

    Transport-level qualification alone does not qualify a role battery. Labels
    preserve blocking/voting mode; a family-comparison advisory is a different
    evaluation policy, not a production-review demotion.
    """
    checked = []
    for record in records:
        errors = validate_qualification(record)
        if errors:
            raise ValueError('; '.join(errors))
        checked.append(record)
    result = []
    for assignment in assignments:
        row = deepcopy(assignment)
        card = load(row['role'])
        cell = (card['id'], row['model_id'], row['transport'], row['effort'])
        matching = [r for r in checked if (r['role'], r['model_id'], r['transport'], r['effort']) == cell
                    and r['role_family'] == card['family']]
        qualified = len(matching) == 1 and matching[0]['status'] == 'qualified'
        row['qualification'] = {'status': 'qualified' if qualified else 'unqualified',
                                'cell': dict(zip(('role', 'model_id', 'transport', 'effort'), cell))}
        row['label'] = ('CHECK-IN 1: configurable, unqualified ' + row['mode'] + ' role cell'
                        if delegated and row['mode'] in ('blocking', 'voting') and not qualified
                        else 'qualified role cell' if qualified else 'configurable, unqualified role cell')
        result.append(row)
    return result


def checkin_fields(stage, *, delegated=False):
    """The decision gate writes role_assignments on a stage; retain the CI1 labels verbatim.

    An absent field preserves the legacy CHECK-IN 1 byte identity.
    """
    if 'role_assignments' not in stage:
        return {}
    return {'role_qualifications': qualification_labels(stage['role_assignments'], delegated=delegated,
                                                       records=stage.get('role_qualification_records', []))}


def profile_paths(surface, *, document=None):
    surface = 'governed-node' if surface == 'hookless' else surface
    if surface not in SURFACES:
        raise ValueError('unknown host surface: ' + surface)
    extension = 'toml' if surface == 'codex' else 'json' if surface == 'governed-node' else 'md'
    return {c['id']: f'{PROFILE_DIRS[surface]}/ravel-{c["id"]}.{extension}' for c in all_cards(document=document)}


def gate_shim(surface, *, document=None, roles_root=None):
    table = json.loads(package_data_path('agent_surface', 'hooks.json').read_text())
    if surface not in table['shim_paths']:
        raise ValueError('no gate shim for surface: ' + surface)
    digest = registry_sha256(document=document, roles_root=roles_root)
    return table['shim_paths'][surface], f'#!/bin/sh\n# Generated role registry {digest}; manual adapter, explicit run/action required.\nexec ravel gate "$@"\n'


def host_capabilities():
    return json.loads(package_data_path('agent_surface', 'host_capabilities.json').read_text())


def native_binding(card, surface, *, capabilities=None):
    """Return verified, exact native fields or None: never infer an authority map."""
    if card['requires']['attestation_min'] != 'self':
        return None  # Native host subagents never provide transport attestation.
    caps = (capabilities or host_capabilities())['surfaces'].get(surface)
    if caps is None:
        return None
    values = {f'requires.{key}': value for key, value in card['requires'].items()}
    values.update({f'model.{key}': value for key, value in card['model'].items()})
    fields = {}
    for key, value in values.items():
        mapping = caps['mappings'].get(key)
        if not mapping or mapping['status'] != 'confirmed' or not mapping.get('source'):
            return None
        entry = mapping.get('values', {}).get(json.dumps(value, sort_keys=True))
        if entry is None:
            return None
        for native, bound in entry.items():
            if native in fields and fields[native] != bound:
                return None
            fields[native] = bound
    if surface == 'claude' and 'tools' not in fields:
        return None
    return fields


def render(surface, *, document=None, roles_root=None) -> dict[str, str]:
    surface = 'governed-node' if surface == 'hookless' else surface
    if surface not in SURFACES:
        raise ValueError('unknown host surface: ' + surface)
    cards = all_cards(document=document, roles_root=roles_root)
    digest = registry_sha256(document=document, roles_root=roles_root)
    mark = f'Generated from the RAVEL role registry {digest}. Do not hand edit.'
    paths = profile_paths(surface, document=document)
    files = {}
    for card in cards:
        binding = native_binding(card, surface)
        redirect = f"Do not perform this role here. Run `ravel work dispatch --role {card['id']}`."
        body = (mark + '\n\n' + card['purpose'] + '\n\nContract:\n' + json.dumps(card, indent=2, sort_keys=True) + '\n'
                if binding is not None else redirect + '\n')
        fields = binding if binding is not None else host_capabilities()['surfaces'].get(surface, {}).get('redirect_fields', {})
        description = card['purpose'] if binding is not None else 'Dispatch redirect for ' + card['id'] + '.'
        if surface == 'codex':
            content = '# ' + mark + '\n' + 'name = ' + json.dumps('ravel-' + card['id']) + '\n'
            content += 'description = ' + json.dumps(description) + '\n'
            content += ''.join(key + ' = ' + json.dumps(value) + '\n' for key, value in fields.items())
            content += 'developer_instructions = ' + json.dumps(body) + '\n'
        elif surface == 'governed-node':
            content = json.dumps({'registry_sha256': digest, 'card': card}, indent=2, sort_keys=True) + '\n'
        else:
            content = '---\n# ' + mark + '\nname: ravel-' + card['id'] + '\ndescription: ' + json.dumps(description) + '\n'
            content += ''.join(key + ': ' + json.dumps(value) + '\n' for key, value in fields.items())
            content += '---\n\n' + body
        files[paths[card['id']]] = content
    if surface == 'claude':
        instructions = package_data_path('agent_surface', 'instructions.md').read_text()
        files['AGENTS.md'] = '<!-- ' + mark + ' -->\n' + instructions
        files['CLAUDE.md'] = '@AGENTS.md\n\n<!-- ' + mark + ' -->\nUse the registered ravel-* profiles; resolve the Tier B panel through `ravel agent-surface profiles --host claude --project .`.\n'
    elif surface in ('gemini', 'antigravity'):
        name = 'GEMINI.md' if surface == 'gemini' else '.antigravity/RAVEL.md'
        files[name] = '@AGENTS.md\n\n<!-- ' + mark + ' -->\nResolve registered role profiles before dispatch. Profiles declare policy; the broker and `ravel gate` enforce it.\n'
    elif surface == 'opencode':
        files['.opencode/RAVEL.md'] = '<!-- ' + mark + ' -->\nRead AGENTS.md and the mirrored workflow skills in .claude/skills and .agents/skills.\n'
    if surface in ('claude', 'codex', 'gemini'):
        rel, content = gate_shim(surface, document=document, roles_root=roles_root)
        files[rel] = content
    from .site_tools import declaration
    files['.ravel/site-tools/' + surface + '.json'] = json.dumps(declaration(surface), indent=2, sort_keys=True) + '\n'
    if surface == 'codex':
        config = '# ' + mark + '\n'
        for card in cards:
            config += '\n[agents.ravel-' + card['id'] + ']\n'
            config += 'description = ' + json.dumps('Dispatch redirect for ' + card['id'] + '.' if native_binding(card, surface) is None else card['purpose']) + '\n'
            config += 'config_file = ' + json.dumps('agents/ravel-' + card['id'] + '.toml') + '\n'
        files['.codex/config.toml'] = config
    return files


def check_rendered(project, *, surfaces=SURFACES, document=None, roles_root=None, exclude=()):
    project = Path(project)
    errors = []
    for surface in surfaces:
        expected = render(surface, document=document, roles_root=roles_root)
        for relative, text in expected.items():
            if relative in exclude:
                continue  # Installed project instructions retain their own merged prose.
            path = Path(project) / relative
            if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file():
                errors.append('generated surface missing or nonregular: ' + relative)
            elif path.read_bytes() != text.encode():
                errors.append('generated surface drift: ' + relative)
        directory = Path(project) / PROFILE_DIRS[surface]
        for path in sorted(directory.rglob('*')):
            if path.is_file() or path.is_symlink():
                relative = path.relative_to(project).as_posix()
                if relative not in expected:
                    errors.append('generated surface orphan: ' + relative)
        table = json.loads(package_data_path('agent_surface', 'hooks.json').read_text())
        shim = table['shim_paths'].get(surface)
        if shim:
            shim_dir = project / Path(shim).parent
            for path in sorted(shim_dir.glob('ravel-gate*')):
                relative = path.relative_to(project).as_posix()
                if relative not in expected:
                    errors.append('generated surface orphan: ' + relative)
    removed = {'.codex/hooks.json', '.gemini/settings.json', '.claude/settings.ravel-gates.json', '.ravel/gate-surface.json'}
    selected_roots = {PROFILE_DIRS[surface].split('/')[0] for surface in surfaces}
    errors.extend('generated surface orphan: ' + rel for rel in sorted(removed)
                  if rel.split('/')[0] in selected_roots and ((project / rel).exists() or (project / rel).is_symlink()))
    return errors


def owned_paths(project):
    """SURFACE_EXTENSIONS: include absent reserved overrides and orphans."""
    project = Path(project) if project is not None else repository_root()
    roles = project / 'src/ravel/data/roles' if project is not None else package_data_path('roles')
    document = registry_document(roles_root=roles)
    files = {'src/ravel/data/roles/registry.json': roles / 'registry.json'}
    files['src/ravel/__init__.py'] = (project / 'src/ravel/__init__.py' if project is not None
                                      else Path(__file__).resolve().parents[1] / '__init__.py')
    for row in document['roles'].values():
        if row.get('override'):
            rel = 'src/ravel/data/roles/' + row['override']
            files[rel] = roles / row['override']
    if (roles / 'cards').is_dir():
        # Unlisted card files are orphans; fingerprint them so adding one changes the surface.
        for path in (roles / 'cards').rglob('*'):
            if path.is_file() or path.is_symlink():
                files['src/ravel/data/roles/' + path.relative_to(roles).as_posix()] = path
    for path in (roles / 'schema').rglob('*.json'):
        files['src/ravel/data/roles/' + path.relative_to(roles).as_posix()] = path
    for name in ('role_registry.py', 'work_order_fidelity.py', 'work_dispatch.py'):
        files['src/ravel/workflow/' + name] = (project / 'src/ravel/workflow' / name
                                              if project is not None else Path(__file__).parent / name)
    files['src/ravel/data/agent_surface/host_capabilities.json'] = (project / 'src/ravel/data/agent_surface/host_capabilities.json'
                                                               if project is not None else package_data_path('agent_surface', 'host_capabilities.json'))
    if project is not None:
        for surface in SURFACES:
            files.update({rel: project / rel for rel in render(surface, roles_root=roles)})
            for path in (project / PROFILE_DIRS[surface]).rglob('*'):
                if path.is_file() or path.is_symlink():
                    files[path.relative_to(project).as_posix()] = path
    return files


def surface_metadata(project=None):
    roles = Path(project) / 'src/ravel/data/roles' if project is not None else None
    return {'role_registry_sha256': registry_sha256(roles_root=roles)}


def register_surface_extension():
    """Register only through the public extension tuple, never wrap its code.

    The host must pass its project to this callback and include callback.metadata
    in its CHECK-IN 1 row. A zero-argument legacy invocation fails closed rather
    than fingerprinting an unrelated checkout.
    """
    import importlib
    try:
        governance = importlib.import_module('ravel.workflow.host_governance')
    except ModuleNotFoundError as exc:
        if exc.name != 'ravel.workflow.host_governance':
            raise
        return False
    if not hasattr(governance, 'SURFACE_EXTENSIONS'):
        return False
    owned_paths.metadata = surface_metadata
    if owned_paths not in governance.SURFACE_EXTENSIONS:
        governance.SURFACE_EXTENSIONS += (owned_paths,)
    return True


def resolve_panel(project, surface):
    paths = profile_paths(surface)
    result = {r: str(Path(project) / paths[r]) for r in PANEL}
    if any(not Path(p).is_file() for p in result.values()):
        raise ValueError('installed verification panel has unresolved profiles')
    expected = render(surface)
    if any(Path(result[r]).is_symlink() or Path(result[r]).read_bytes() != expected[paths[r]].encode() for r in PANEL):
        raise ValueError('installed verification panel has stale profiles')
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--project', type=Path)
    args = ap.parse_args(argv)
    errors = validate_registry()
    if errors:
        print('\n'.join(errors))
        return 1
    if args.write:
        root = args.project or repository_root()
        if root is None:
            ap.error('--project is required outside a checkout')
        retired = ['.claude/settings.ravel-gates.json', '.codex/hooks.json', '.gemini/settings.json', '.ravel/gate-surface.json']
        for relative in retired:
            path = root / relative
            if path.is_file():
                prior = json.loads(path.read_text())
                if 'registry_sha256' in prior:
                    path.unlink()  # Retire only this renderer's generated pseudo tables.
        document = registry_document()
        registered = set(document['roles']) | set(document['aliases'])
        for path in (root / PROFILE_DIRS['claude']).glob('*.md'):
            if not path.name.startswith('ravel-') and path.stem in registered:
                path.unlink()
        for surface in SURFACES:
            for relative, text in render(surface).items():
                path = root / relative
                if path.is_file() and not path.is_symlink() and path.read_bytes() == text.encode():
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        print('Rendered role surfaces; protected .claude/hooks and active settings were not changed.')
    else:
        print(json.dumps([{'id': c['id'], 'card_sha256': card_sha256(c['id'])} for c in all_cards()], indent=2))
    return 0


register_surface_extension()


if __name__ == '__main__':
    raise SystemExit(main())
