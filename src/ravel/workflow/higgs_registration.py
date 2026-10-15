"""Compose source-owned scalar role fragments without mutating shared registries.

Composition is inert, append-only and rejects conflicting identities. Frozen stores
compose only fragments beside their own data root, never a host-global fallback.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ravel.paths import package_data_path

FILES = {'role-registry': 'roles.json', 'consult-bindings': 'consults.json',
         'role-knowledge-bindings': 'knowledge.json', 'spawn-row-catalogue': 'spawn.json',
         'validator-allowlist': 'validators.json', 'physics-premises': 'premises.json'}


def fragment_paths(data_root=None):
    root = Path(data_root) if data_root is not None else package_data_path()
    # Operation-row fragments share this folder; only the registry fragments named in FILES compose here.
    names = set(FILES.values())
    return sorted(p for p in (root / 'higgs/registration').glob('*.json') if p.name in names)


def compose(document, path=None):
    """Append a matching fragment; conflicts require explicit integration disposition."""
    if not isinstance(document, dict) or document.get('kind') not in FILES:
        return document
    data_root = Path(path).parent.parent if path is not None else package_data_path()
    source = data_root / 'higgs/registration' / FILES[document['kind']]
    if not source.is_file():
        return document
    if source.is_symlink() or source.stat().st_size > 2_000_000:
        raise ValueError('bounded regular registration fragment required')
    fragment = json.loads(source.read_text())
    if (set(fragment) != {'schema_version', 'kind', 'target', 'append'}
            or type(fragment['schema_version']) is not int or fragment['schema_version'] != 1
            or fragment['kind'] != 'registry-registration' or fragment['target'] != document['kind']
            or type(fragment['append']) is not dict):
        raise ValueError('closed versioned registry registration required')
    result = deepcopy(document)
    for key, extra in fragment['append'].items():
        if key not in result:
            raise ValueError('registration cannot introduce envelope fields: ' + key)
        own = result[key]
        if isinstance(own, dict) and isinstance(extra, dict):
            for identity, value in extra.items():
                if identity in own:
                    raise ValueError('registration identity collision: ' + identity)
                own[identity] = deepcopy(value)
        elif isinstance(own, list) and isinstance(extra, list):
            identity_key = {'rows': 'row', 'validators': 'id', 'premises': 'id', 'conventions': 'id'}.get(key)
            identities = [r[identity_key] for r in own] if identity_key else own[:]
            for value in extra:
                identity = value[identity_key] if identity_key else value
                if identity in identities:
                    raise ValueError('registration identity collision: ' + str(identity))
                identities.append(identity)
                own.append(deepcopy(value))
        else:
            raise ValueError('registration append must match collection type')
    return result


def validate_store_fragments(atlas, *paths):
    """Bind composed cold knowledge to the atlas's exact fragment source bytes."""
    pins = {p['path']: p['sha256'] for p in atlas.get('generator', {}).get('sources', [])}
    for source in paths:
        source = Path(source)
        kinds = {'premises.json': 'physics-premises', 'role_bindings.json': 'role-knowledge-bindings'}
        kind = kinds.get(source.name)
        if kind is None:
            continue
        filename = FILES[kind]
        relative = 'src/ravel/data/higgs/registration/' + filename
        fragment = source.parent.parent / 'higgs/registration' / filename
        expected = pins.get(relative)
        if expected is None and not fragment.exists():
            continue
        if (not fragment.is_file() or fragment.is_symlink() or expected is None
                or hashlib.sha256(fragment.read_bytes()).hexdigest() != expected):
            raise ValueError('registration source changed or is unpinned: ' + filename)


def compose_stores(premises, bindings, atlas, premise_path, binding):
    """Compose cold stores through one authenticated materializer seam."""
    binding_path = binding.get('role_bindings_path', package_data_path('knowledge', 'role_bindings.json'))
    validate_store_fragments(atlas, premise_path, binding_path)
    return compose(premises, premise_path), compose(bindings, binding_path)


def derive_higgs(nodes, rows, add, review_metadata):
    """Staff declared semantic facts using the existing review-point constructor."""
    for node in sorted(nodes, key=lambda n: n['id']):
        metadata = review_metadata(node)
        tags = metadata.get('domain_tags', [])
        experiments = metadata.get('experiments', [])
        if (type(tags) is not list or any(type(t) is not str for t in tags)
                or type(experiments) is not list or any(type(e) is not str or not e for e in experiments)):
            raise ValueError('domain tags and experiments must be text lists')
        facts = set(tags)
        for row in sorted(rows.values(), key=lambda r: r['row']):
            if row.get('predicate') != 'declared-domain':
                continue
            if set(row['tags_all']) <= facts and len(set(experiments)) >= row['min_experiments']:
                add(row['row'], node['id'], node=node['id'])


def index_registration(root, add, pin):
    """Index every consumed fragment and authored convention, including byte custody."""
    data = Path(root) / 'src/ravel/data'
    for path in fragment_paths(data):
        pin(path)
        fragment = json.loads(path.read_text())
        if fragment['target'] != 'physics-premises':
            continue
        for key, kind in (('premises', 'trap'), ('conventions', 'conv')):
            for row in fragment['append'].get(key, []):
                add(kind, row['id'].split(':', 1)[1], row['title'], row['statement'], path)
    shard = data / 'knowledge/conventions/higgs.json'
    if shard.is_file():
        pin(shard)
    pin(Path(root) / 'src/ravel/workflow/higgs_registration.py')


def premise_pin(row, fallback):
    """Use the source fragment for added rows; preserve original source custody."""
    path = package_data_path('higgs/registration/premises.json')
    fragment = json.loads(path.read_text())
    ids = {r['id'] for rows in fragment['append'].values() for r in rows}
    if row['id'] not in ids:
        return fallback
    raw = path.read_bytes()
    return {'path': str(path), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
