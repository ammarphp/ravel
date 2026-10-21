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


def card_ids(*, document=None, roles_root=None) -> dict:
    """The one mapping from role names to card ids, generated from the registry's card ids.

    Every registered card answers to its id and to the id's underscore spelling (the form agent-role names
    take, for example ``rdj_critic``). Nothing else is listed and no name is written by hand; spellings of
    two cards that collide refuse the whole mapping.
    """
    document = registry_document(roles_root=roles_root) if document is None else document
    found = {}
    for identity in sorted(document['roles']):
        for name in dict.fromkeys((identity, identity.replace('-', '_'))):
            if found.setdefault(name, identity) != identity:
                raise ValueError(f'role name {name!r} would name two cards: {found[name]} and {identity}')
    return found


def card_id(name, *, document=None, roles_root=None):
    """The card id ``name`` resolves to through ``card_ids``, or None."""
    return card_ids(document=document, roles_root=roles_root).get(name) if isinstance(name, str) else None


def same_card(first, second, *, document=None, roles_root=None) -> bool:
    """Whether two role names name the same card through ``card_ids``. A name the mapping does not list
    matches only itself, and a value that is not a nonempty name matches nothing. Two spellings of one card
    differ only in '-' against '_', so the mapping is read only for such a pair."""
    if any(not isinstance(name, str) or not name for name in (first, second)):
        return False
    if first == second or first.replace('_', '-') != second.replace('_', '-'):
        return first == second
    ids = card_ids(document=document, roles_root=roles_root)
    return ids.get(first, first) == ids.get(second, second)


def _operation_signatures(roles_root, *, supplied_document):
    # Explicit documents without a data root are isolated fixtures. Selected roots
    # likewise never borrow operation ownership from the installed package.
    if roles_root is None and supplied_document:
        return {}
    root = Path(roles_root) if roles_root is not None else package_data_path('roles')
    path = root.parent / 'operation_signatures.json'
    from .operation_registration import read_signatures
    return read_signatures(path)


def load(role_id: str, *, document=None, roles_root=None, _signatures=None) -> dict:
    supplied_document = document is not None
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
    from .operation_registration import card_operations
    signatures = (_operation_signatures(roles_root, supplied_document=supplied_document)
                  if _signatures is None else _signatures)
    return card_operations(card, signatures)


def all_cards(*, document=None, roles_root=None) -> list[dict]:
    supplied_document = document is not None
    if document is None and roles_root is None:
        roles_root = package_data_path('roles')
    document = registry_document(roles_root=roles_root) if document is None else document
    signatures = _operation_signatures(roles_root, supplied_document=supplied_document)
    return [load(identity, document=document, roles_root=roles_root, _signatures=signatures)
            for identity in sorted(document['roles'])]


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
    if document is None and roles_root is None:
        roles_root = package_data_path('roles')
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
    if not path.is_file():
        return ['unresolved output schema: ' + identity]
    errors = _schema_errors(record, path)
    if not errors and record.get('kind') == 'findings' and record.get('schema_version') == 2:
        from . import finding_routing
        try:
            for item in record['items']:
                finding_routing.validate(item)
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def validate_qualification(record):
    errors = _schema_errors(record, package_data_path('roles', 'schema', 'qualification-record.json'))
    if not errors and record['status'] == 'qualified' and any(r['result'] != 'pass' for r in record['battery']):
        errors.append('qualified cell has a failing battery receipt')
    return errors


def _known_ids(root=None):
    path = (Path(root) / 'src/ravel/data/knowledge/atlas.json' if root is not None
            else package_data_path('knowledge', 'atlas.json'))
    return {r['id'] for r in json.loads(path.read_text())['entries']}


def validate_card(card, *, root=None, known_ids=None, quantity_kinds=None):
    errors = _schema_errors(card, package_data_path('roles', 'schema', 'card.json'))
    if errors:
        return errors
    errors += ownership_card_errors(card, registry_document()['quantity_kinds'] if quantity_kinds is None else quantity_kinds)
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


def ownership_card_errors(card, kinds):
    """Quantity authority is distinct from an artifact's serialization kind."""
    contract = card.get('ownership', {})
    if (type(contract) is not dict or set(contract) != {'owns', 'judges', 'inputs'}
            or any(type(v) is not list or any(type(k) is not str for k in v)
                   or len(v) != len(set(v)) for v in contract.values())):
        return ['closed ownership contract required']
    errors = ['unknown quantity kind: ' + k for values in contract.values() for k in values if k not in kinds]
    if contract['owns'] and (card.get('independence', {}).get('kind') != 'producer'
                             or card['family'] in ('specialist-review', 'governance', 'consult')):
        errors.append('only a producer can own a quantity; reviewers may judge')
    if card.get('independence', {}).get('kind') == 'producer' and not contract['owns']:
        errors.append('producer must declare its owned quantity kinds')
    if set(contract['owns']) & set(contract['judges']):
        errors.append('a role cannot judge its own quantity')
    return errors


def validate_ownership(assignments, handoffs=(), *, required_kinds=(), document=None, roles_root=None):
    """Return final owners for a closed assembly, refusing parallel production.

    Assignment keys are workflow node IDs, values are registered role IDs. A
    handoff names a kind, from and to: the predecessor's owned output becomes
    the successor's declared input. Repeated ownership must form one chain.
    Scheduling and artifact custody remain the caller's responsibility.
    """
    document = registry_document(roles_root=roles_root) if document is None else document
    kinds = document['quantity_kinds']
    if type(assignments) is not dict or type(handoffs) not in (list, tuple):
        raise ValueError('ownership assignments and finite handoffs required')
    cards, owners = {}, {}
    for node, identity in assignments.items():
        card = load(identity, document=document, roles_root=roles_root)
        errors = ownership_card_errors(card, kinds)
        if errors:
            raise ValueError(identity + ': ' + '; '.join(errors))
        cards[node] = card
        for kind in card['ownership']['owns']:
            owners.setdefault(kind, set()).add(node)
    edges = {}
    for row in handoffs:
        if type(row) is not dict or set(row) != {'kind', 'from', 'to'}:
            raise ValueError('closed quantity handoff required')
        kind, source, target = row['kind'], row['from'], row['to']
        if any(type(v) is not str for v in (kind, source, target)):
            raise ValueError('quantity handoff identities must be text')
        if source == target or source not in cards or target not in cards or kind not in kinds:
            raise ValueError('unresolved quantity handoff')
        if (kind not in cards[source]['ownership']['owns']
                or kind not in cards[target]['ownership']['inputs']):
            raise ValueError('handoff requires owned output and declared consumer input')
        edge = (source, target)
        if edge in edges.setdefault(kind, []):
            raise ValueError('duplicate quantity handoff')
        edges[kind].append(edge)
    final = {}
    for kind in set(owners) | set(required_kinds):
        if kind not in kinds:
            raise ValueError('unknown required quantity kind: ' + str(kind))
        producers = owners.get(kind, set())
        if not producers:
            raise ValueError('missing owner for quantity: ' + kind)
        chain = [(a, b) for a, b in edges.get(kind, []) if b in producers]
        incoming = {b for a, b in chain}
        roots = producers - incoming
        if len(roots) != 1 or len(chain) != len(producers) - 1:
            raise ValueError('duplicate ownership requires an explicit handoff chain: ' + kind)
        current = next(iter(roots)); seen = set()
        while current not in seen:
            seen.add(current)
            following = [b for a, b in chain if a == current]
            if len(following) > 1:
                raise ValueError('branching quantity ownership: ' + kind)
            if not following:
                break
            current = following[0]
        if seen != producers or any(a == current for a, b in chain):
            raise ValueError('cyclic or disconnected quantity ownership: ' + kind)
        final[kind] = current
    return dict(sorted(final.items()))


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
        if document is None and roles_root is None:
            roles_root = package_data_path('roles')
        document = registry_document(roles_root=roles_root) if document is None else document
        errors = []
        if set(document) != {'schema_version', 'kind', 'required_roles', 'aliases', 'roles', 'quantity_kinds'} or document['schema_version'] != 1 or document['kind'] != 'role-registry':
            return ['closed role-registry envelope required']
        if len(document['required_roles']) != len(set(document['required_roles'])):
            errors.append('duplicate required role')
        vocabulary = document['quantity_kinds']
        if (type(vocabulary) is not dict or not vocabulary
                or any(not re.fullmatch(r'[a-z][a-z0-9-]*', kind)
                       or type(row) is not dict or set(row) != {'source_roles'}
                       or type(row['source_roles']) is not list or not row['source_roles']
                       or any(role not in document['roles'] for role in row['source_roles'])
                       for kind, row in vocabulary.items())):
            return ['controlled quantity vocabulary with source roles required']
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
            errors += [card['id'] + ': ' + e for e in validate_card(card, known_ids=ids, quantity_kinds=vocabulary)]
            for identity in card['reviewed_by'] + [c['role'] for c in card['knowledge']['consult'] if c['role'] != 'by_failure_class']:
                if document['aliases'].get(identity, identity) not in document['roles']:
                    errors.append(card['id'] + ': unresolved role reference: ' + identity)
        cards_root = Path(roles_root) if roles_root is not None else package_data_path('roles')
        declared = {r['override'] for r in document['roles'].values() if r.get('override')}
        errors += ['unlisted card override: ' + p.relative_to(cards_root).as_posix()
                   for p in (cards_root / 'cards').glob('*.json') if p.relative_to(cards_root).as_posix() not in declared]
        from .sfitter_workflow import validate_phase_ownership
        validate_phase_ownership(document=document, roles_root=roles_root)
        if {'higgs-coupling-analyst', 'higgs-combination-reviewer', 'higgs-theory-uncertainty-auditor'} <= set(document['roles']):
            validate_phase_ownership(higgs=True, document=document, roles_root=roles_root)
        return sorted(set(errors))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return ['cannot validate role registry: ' + str(exc)]


def finding_effect(item, *, resolve=None):
    """Only a resolver's evidence IDs confer a blocking evidence class.

    A pending request holds the finding while its test is unresolved. A reviewer's
    declared class or declared failed test grants no evidence authority.
    """
    checked = {**item, 'evidence_class': 'opinion'}
    from . import finding_routing
    version = 2 if 'classification' in item else 1
    errors = validate_output('findings.v2', {'schema_version': version, 'kind': 'findings', 'items': [checked], 'handoff': None})
    if errors:
        raise ValueError('; '.join(errors))
    if finding_routing.kind(item) == 'limitation':
        return 'claim_disposition'
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
        redirect = (
            'Do not perform this role here. Never perform it in the parent conversation. Resolve RUN, NODE, SPEC.json and '
            'SUBJECT.json from the active work request; never guess a missing binding. '
            'SUBJECT.json must contain the exact subject scope and sha256 pinned by SPEC.json. '
            f'Run `python -m ravel.workflow.transports.host_subagent dispatch --rundir RUN '
            f'--node NODE --role {card["id"]} --spec SPEC.json --subject SUBJECT.json`. '
            'This is the common role dispatcher, including host adapters. If dispatch is refused, '
            'report the missing requirements and hold the role. An explicitly advisory result '
            'does not satisfy the required role; never substitute a parent persona.'
        )
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
    if surface != 'governed-node':
        rel, content = gate_shim(surface, document=document, roles_root=roles_root)
        files[rel] = content
    from .host_hooks import render as render_hooks
    files.update(render_hooks(surface))
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
    removed = {'.claude/settings.ravel-gates.json', '.ravel/gate-surface.json'}
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
    files['src/ravel/data/operation_signatures.json'] = roles.parent / 'operation_signatures.json'
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
    for name in ('role_registry.py', 'operation_registration.py', 'work_order_fidelity.py', 'work_dispatch.py', 'host_guards.py', 'host_hooks.py', 'native_shims.py'):
        files['src/ravel/workflow/' + name] = (project / 'src/ravel/workflow' / name
                                              if project is not None else Path(__file__).parent / name)
    files['src/ravel/data/agent_surface/host_capabilities.json'] = (project / 'src/ravel/data/agent_surface/host_capabilities.json'
                                                               if project is not None else package_data_path('agent_surface', 'host_capabilities.json'))
    files['src/ravel/data/agent_surface/hooks.json'] = (project / 'src/ravel/data/agent_surface/hooks.json'
        if project is not None else package_data_path('agent_surface', 'hooks.json'))
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


# Instruction documents a render writes at a project's root. A project's own text (anything without
# RAVEL's generated mark in its first lines) is kept unless the caller asks to replace it.
INSTRUCTION_DOCUMENTS = ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md')
GENERATED_MARK = re.compile(r'^<!-- Generated from the RAVEL role registry [0-9a-f]{64}\. Do not hand edit\. -->$')


def project_instructions(path):
    """Whether ``path`` holds a project-authored instruction document (a link counts as one)."""
    path = Path(path)
    if path.is_symlink():
        return True
    if not path.is_file():
        return False
    lines = path.read_bytes().decode('utf-8', errors='replace').splitlines()[:3]
    return not any(GENERATED_MARK.match(line) for line in lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--project', type=Path)
    ap.add_argument('--replace-instructions', action='store_true',
                    help="also replace a project's own AGENTS.md, CLAUDE.md or GEMINI.md")
    args = ap.parse_args(argv)
    errors = validate_registry()
    if errors:
        print('\n'.join(errors))
        return 1
    if args.write:
        root = args.project or repository_root()
        if root is None:
            ap.error('--project is required outside a checkout')
        retired = ['.claude/settings.ravel-gates.json', '.ravel/gate-surface.json']
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
        preserved = []
        for surface in SURFACES:
            for relative, text in render(surface).items():
                path = root / relative
                if path.is_file() and not path.is_symlink() and path.read_bytes() == text.encode():
                    continue
                if relative in INSTRUCTION_DOCUMENTS and not args.replace_instructions and project_instructions(path):
                    preserved.append(relative)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        print('Rendered role surfaces; protected .claude/hooks and active settings were not changed.')
        if preserved:
            print("Kept the project's own " + ', '.join(sorted(set(preserved)))
                  + ' (pass --replace-instructions to replace them).')
    else:
        print(json.dumps([{'id': c['id'], 'card_sha256': card_sha256(c['id'])} for c in all_cards()], indent=2))
    return 0


register_surface_extension()


if __name__ == '__main__':
    raise SystemExit(main())
