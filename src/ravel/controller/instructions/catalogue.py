"""The installed instruction catalogue and its node manifest selectors.

``build`` compiles a source tree into two read-only package data documents:
``catalogue.json`` (every unit with its exact text, digest, kind and census ids) and
``manifests.json`` (the selectors that assemble a node manifest: the common preamble,
the delivering nodes of every canonical source, role cards and their must-read
knowledge, operation signatures and their source-linked reading, judgment protocols,
check-in templates and governing skills). Every unit
belongs to at least one node; a unit no node delivers fails the build.

At run time only the installed documents are read. A project-local copy of an
instruction file, a checkout edit or an environment variable never changes what a
packet carries; the catalogue digest pins the text.

Selectors: ``<path>`` (every unit of a canonical file; a mirror path names its canonical
file), ``<path>#<slug>`` (the units of that section, its subsections excluded),
``<path>#<slug>+`` (subsections included), ``<path>#<slug>/<n>`` (one unit),
``node:<id>``, ``skill:<name>``, ``protocol:<P1..P8>``, ``checkin:<template>``,
``card:<role>``, ``operation:<id>`` and ``knowledge:<atlas id>``.
"""
from __future__ import annotations

from copy import deepcopy

import csv
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import re

from ravel.paths import package_data_path
from . import compiler

ATLAS_PATH = 'src/ravel/data/knowledge/atlas.json'
SIGNATURES_PATH = 'src/ravel/data/operation_signatures.json'
GENERATOR = 'scripts/maintenance/build_instruction_catalogue.py'
SKILLS = '.claude/skills/'


def data_path(name: str) -> Path:
    return package_data_path('instructions', name)


def _seal(document: dict) -> dict:
    body = {k: v for k, v in document.items() if k != 'sha256'}
    return {**body, 'sha256': compiler.digest_value(body)}


# ------------------------------------------------------------------------------- census citations

def citations_from(census_path: Path, coverage_path: Path, sources: dict, root: Path, *, previous=None) -> dict:
    """The census rows that cite an instruction source, pinned so a rebuild needs no outside file.

    A row citing a mirror is bound to the mirror's canonical file; decision rows are marked."""
    kinds = {}
    with open(coverage_path, newline='') as stream:
        for row in csv.DictReader(stream):
            kinds[row['row_id']] = row['source_kind']
    opener = gzip.open if str(census_path).endswith('.gz') else open
    canonical = {row['path'] for row in sources['canonical']}
    rows = []
    with opener(census_path, 'rt') as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            source = row.get('source') or ''
            target = source
            if source not in canonical and not source.startswith('.ravel/roles/'):
                rule = next((r for r in sources['mirrors'] if compiler._mirror_target(r, source)), None)
                target = compiler._mirror_target(rule, source) if rule else None
            if target is None or (target not in canonical and not target.startswith('.ravel/roles/')):
                continue
            rows.append({'id': row['id'], 'source': target, 'line': row.get('line'),
                         'source_sha256': row.get('source_sha256') if target == source else None,
                         'evidence': row.get('evidence') if target == source else None,
                         'decision': kinds.get(row['id']) == 'census-decision'})
            if target == source and 'pointer' in row and 'declared_value' in row:
                rows[-1].update(pointer=row['pointer'], declared_value=deepcopy(row['declared_value']))
    prior = {row['id']: row for row in (previous or {}).get('rows', [])}
    for row in rows:
        retained = prior.get(row['id'], {})
        if all(row.get(key) == retained.get(key) for key in (
                'id', 'source', 'line', 'source_sha256', 'evidence', 'decision')):
            for key in ('migration', 'migration_history'):
                if key in retained:
                    row[key] = deepcopy(retained[key])
    rows.sort(key=lambda r: r['id'])
    return {'schema_version': 1, 'kind': 'instruction-census-citations',
            'purpose': 'Census obligations that cite an instruction source, pinned from the census and its coverage '
                       'table so the catalogue binds each unit to the census ids it states without an outside file.',
            'census_sha256': hashlib.sha256(Path(census_path).read_bytes()).hexdigest(),
            'coverage_sha256': hashlib.sha256(Path(coverage_path).read_bytes()).hexdigest(),
            'rows': rows}


# ------------------------------------------------------------------------------- knowledge (must_read)

def _atlas(root: Path, view: compiler.View) -> dict:
    path = root / ATLAS_PATH
    if not path.is_file():
        return {}
    if not view.shipped(ATLAS_PATH):
        raise ValueError('knowledge atlas is withheld from the export: ' + ATLAS_PATH)
    # The atlas is a metadata index, not delivered instruction text. Its larger
    # bounded read does not relax View's bound for any resolved source content.
    if any(p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents):
        raise ValueError('regular knowledge atlas required: ' + ATLAS_PATH)
    raw = path.read_bytes()
    if len(raw) > 4 * (1 << 20):
        raise ValueError('knowledge atlas exceeds the bounded index read: ' + ATLAS_PATH)
    entries = json.loads(raw.decode('utf-8'))['entries']
    result = {}
    for row in entries:
        if row['id'] in result:
            raise ValueError('ambiguous knowledge atlas id: ' + row['id'])
        result[row['id']] = row
    return result


def _source_records(value, identity):
    """All exact-id records, at any depth; duplicate occurrences remain ambiguous."""
    found = []
    if isinstance(value, dict):
        if value.get('id') == identity:
            found.append(value)
        for child in value.values():
            found.extend(_source_records(child, identity))
    elif isinstance(value, list):
        for child in value:
            found.extend(_source_records(child, identity))
    return found


def _knowledge_content(identity, row, view, texts, units_by_source, extra):
    """Resolve published, source-pinned content. Atlas metadata cannot stand in for it."""
    binding = row.get('source') or {}
    source = binding.get('path')
    if not isinstance(source, str) or not source or Path(source).is_absolute() or '..' in Path(source).parts:
        raise ValueError('must_read has no valid source path: ' + identity)
    if not view.shipped(source):
        raise ValueError(f'must_read source is withheld: {identity}: {source}')
    try:
        text = view.read(source)
    except (OSError, ValueError) as exc:
        raise ValueError(f'must_read source unavailable: {identity}: {source}') from exc
    if binding.get('sha256') and hashlib.sha256(text.encode('utf-8')).hexdigest() != binding['sha256']:
        raise ValueError(f'must_read source digest mismatch: {identity}: {source}')
    texts[source] = text
    if source.endswith('.json'):
        matches = _source_records(json.loads(text), identity)
        if not matches and source == SIGNATURES_PATH and identity.startswith('op:'):
            # Signature tables name complete records by operation key, while
            # standalone curation records carry an explicit id field.
            from ravel.workflow.operation_registration import read_signatures
            record = read_signatures(view.root / source, raw=text).get(identity.partition(':')[2])
            if record is not None:
                matches = [record]
        if len(matches) != 1:
            raise ValueError(f'must_read source requires one exact-id record, found {len(matches)}: {identity}: {source}')
        content = compiler.normalise(json.dumps(matches[0], indent=2, ensure_ascii=False))
        section, name, form = 'knowledge-records', compiler.slug(identity), 'entry'
    elif row.get('kind') == 'check' or identity.partition(':')[0] == 'check':
        content = compiler.normalise(text)
        section, name, form = 'knowledge-source', '0', 'source'
    else:
        if source not in units_by_source and source.endswith('.md'):
            # Operation documentation joins the same exact-source compiler as
            # canonical workflow reading. Every nested duty retains its unit.
            resolved = compiler.compile_file(source, text, 'workflow-reference')
            units_by_source[source] = resolved
            for unit in resolved:
                unit['sha256'] = compiler.digest_text(unit['text'])
                if unit['id'] in extra and extra[unit['id']] != unit:
                    raise ValueError('ambiguous operation source unit: ' + unit['id'])
                extra[unit['id']] = unit
        selectors = _knowledge_selectors(identity, {identity: row}, units_by_source)
        if selectors is None:
            raise ValueError(f'unresolved must_read source content: {identity}: {source}')
        return selectors
    if not content:
        raise ValueError('empty must_read source content: ' + identity)
    uid = f'{source}#{section}/{name}'
    unit = {'id': uid, 'source': source, 'section': section, 'n': name, 'form': form,
            'kind': 'duty', 'lines': None, 'text': content, 'sha256': compiler.digest_text(content)}
    if uid in extra and extra[uid] != unit:
        raise ValueError('ambiguous must_read unit id: ' + uid)
    extra[uid] = unit
    return [uid]


def _operation_sources(root, view, atlas, knowledge, texts, by_source, extra):
    """Project signatures and their source-owned knowledge into executable reading."""
    if not (root / SIGNATURES_PATH).is_file() or not view.shipped(SIGNATURES_PATH):
        return {}
    from ravel.workflow.operation_registration import read_signatures
    raw = view.read(SIGNATURES_PATH)
    signatures = read_signatures(root / SIGNATURES_PATH, raw=raw)
    texts[SIGNATURES_PATH] = raw
    operations = {}

    def reading(identity, record):
        # The association is pinned to its source preimage. The existing export
        # view supplies the actual published instruction bytes, as it does for
        # canonical workflow files; both identities are checked before copying.
        source = (record.get('source') or {}).get('path')
        if (not isinstance(source, str) or Path(source).is_absolute() or '..' in Path(source).parts
                or not view.shipped(source)):
            raise ValueError('operation knowledge requires a shipped relative source: ' + identity)
        original = compiler.View(root).read(source)
        published = view.read(source)
        original_sha = hashlib.sha256(original.encode()).hexdigest()
        published_sha = hashlib.sha256(published.encode()).hexdigest()
        if record['source'].get('sha256') not in (original_sha, published_sha):
            raise ValueError('operation knowledge source digest mismatch: ' + identity)
        binding = {**record, 'source': {**record['source'], 'sha256': published_sha}}
        return _knowledge_content(identity, binding, view, texts, by_source, extra)

    for name, signature in sorted(signatures.items()):
        uid = f'{SIGNATURES_PATH}#operation-signatures/{compiler.slug(name)}'
        text = compiler.normalise(json.dumps(signature, indent=2, ensure_ascii=False))
        unit = {'id': uid, 'source': SIGNATURES_PATH, 'section': 'operation-signatures',
                'n': compiler.slug(name), 'form': 'entry', 'kind': 'duty', 'lines': None,
                'text': text, 'sha256': compiler.digest_text(text)}
        if uid in extra:
            raise ValueError('ambiguous operation signature unit: ' + name)
        extra[uid] = unit
        row = atlas.get('op:' + name, {})
        identities, declared = [], []
        if row.get('curation_source'):
            identity = 'op:' + name
            binding = {**row, 'source': row['curation_source']}
            if identity not in knowledge:
                knowledge[identity] = reading(identity, binding)
            identities.append(identity)
        for kind in ('docs', 'handbooks', 'checks'):
            for identity in row.get('links', {}).get(kind, []):
                if identity in identities:
                    continue
                target = atlas.get(identity)
                if target is None:
                    raise ValueError(f'operation {name} knowledge source missing: {identity}')
                if target.get('status') == 'declared_term':
                    # The signature carries this exact review declaration. A
                    # declaration retains its status rather than inventing code.
                    declared.append(identity)
                    continue
                if identity not in knowledge:
                    knowledge[identity] = reading(identity, target)
                identities.append(identity)
        selectors = [uid, *['knowledge:' + identity for identity in identities]]
        for reference in (signature.get('registration') or {}).get('documentation', []):
            path = reference['path'] if isinstance(reference, dict) else reference
            if path not in selectors:
                selectors.append(path)
        operations[name] = {'signature': uid, 'signature_sha256': compiler.digest_value(signature),
                            'knowledge': identities, 'declared_checks': declared,
                            'sources': selectors}
    return operations


def _knowledge_selectors(identity, atlas, units_by_source):
    """Selectors that deliver the content of one must-read knowledge id, or None."""
    row = atlas.get(identity)
    if row is None:
        return None
    source = row.get('source', {}).get('path')
    units = units_by_source.get(source)
    if not units:
        return None
    kind, _, name = identity.partition(':')
    if kind == 'proto':
        prefix = compiler.slug(name) + '-'
        hits = [u['section'] for u in units if u['form'] == 'heading' and u['section'].startswith(prefix)]
        return [f'{source}#{hits[0]}'] if len(hits) == 1 else None
    if kind == 'trap':
        hits = [u['id'] for u in units if u['form'] == 'row' and re.match(r'\|\s*' + re.escape(name) + r'\s*\|', u['text'])]
        return hits if len(hits) == 1 else None
    if kind in ('hb', 'checklist', 'skill', 'doc', 'rule'):
        return [source]
    return None


# ------------------------------------------------------------------------------- build

def export_view(root: Path, *, transforms: dict | None = None, publish=None) -> compiler.View:
    """What the export publishes from ``root``: its selection, read with the declared public edits.

    A tree with a distribution registry publishes its export selection. A source checkout's build
    passes the export's declared edits (``transforms``) and their applier (``publish``), so each
    file reads as published; a public tree already holds the published text. A tree without a
    registry (a test fixture) publishes every file as it is. A source checkout and the public tree
    it exports therefore compile the same catalogue, and no withheld text enters it."""
    root = Path(root).resolve()
    from ravel import evidence_layout
    try:
        registry = evidence_layout.load_registry(root)
    except FileNotFoundError:
        return compiler.View(root, transforms=transforms, publish=publish)
    shipped = {source for source, _ in evidence_layout.selected_files(root, registry=registry)}
    return compiler.View(root, shipped=shipped, transforms=transforms, publish=publish)


def build(root: Path, *, sources: dict | None = None, citations: dict | None = None, cards: list[dict] | None = None,
          drift: list | None = None, withheld: list | None = None, view: compiler.View | None = None):
    """(catalogue, manifests) documents for the tree at ``root``, compiled from its published text
    (``view``; by default ``export_view(root)`` without public edits, which is the published text of
    a public tree; a source checkout's build passes the export's edits). Mirrors that currently
    differ from their canonical source are appended to ``drift``, and instruction files the export
    withholds to ``withheld``, when those lists are given."""
    root = Path(root).resolve()
    sources = sources if sources is not None else compiler.load_sources(root / 'src/ravel/data/instructions/sources.json')
    if cards is None:
        from ravel.workflow import role_registry
        cards = role_registry.all_cards(roles_root=root / 'src/ravel/data/roles')
    if citations is None:
        path = root / 'src/ravel/data/instructions/citations.json'
        citations = json.loads(path.read_text()) if path.is_file() else {'rows': []}
    view = view if view is not None else export_view(root)
    compiled = compiler.build(root, sources, cards=cards, view=view)
    units, texts = compiled.pop('units'), compiled.pop('texts')
    for name, target in (('drift', drift), ('withheld', withheld)):
        found = compiled.pop(name)
        if target is not None:
            target.extend(found)
    by_source = {}
    for unit in units:
        by_source.setdefault(unit['source'], []).append(unit)
    atlas = _atlas(root, view)
    # Exported text may differ from the atlas's original source. A reviewed, exact
    # old-to-published digest migration is required; never ignore the source pin.
    for migration in sources.get('knowledge_source_migrations', []):
        if not migration.get('reviewed_by') or not migration.get('reason'):
            raise ValueError('unreviewed knowledge source migration')
        source = migration.get('path')
        if hashlib.sha256(view.read(source).encode()).hexdigest() != migration.get('published_sha256'):
            raise ValueError('stale knowledge source migration: ' + str(source))
        matches = [r for r in atlas.values() if r.get('source', {}).get('path') == source]
        if not matches or any(r['source'].get('sha256') != migration.get('source_sha256') for r in matches):
            raise ValueError('knowledge source migration does not match the atlas: ' + str(source))
        for row in matches:
            row['source'] = {**row['source'], 'sha256': migration['published_sha256']}
    knowledge, extra = {}, {}
    for card in cards:
        for identity in card['knowledge']['must_read']:
            if identity in knowledge:
                continue
            if identity not in atlas:
                raise ValueError(f'must_read id {identity} of role {card["id"]} is not in the knowledge atlas')
            selectors = _knowledge_content(identity, atlas[identity], view, texts, by_source, extra)
            knowledge[identity] = selectors
    operations = _operation_sources(root, view, atlas, knowledge, texts, by_source, extra)
    existing_ids = {unit['id'] for unit in units}
    if existing_ids & extra.keys():
        raise ValueError('duplicate must_read unit ids: ' + ', '.join(sorted(existing_ids & extra.keys())))
    units.extend(extra[k] for k in sorted(extra))
    compiler.attach_census(units, citations.get('rows', []), texts)
    # Supplemental record/source units retain the actual source path and file digest.
    # Recount existing files too: a nested record may supplement an already compiled file.
    files = {row['path']: row for row in compiled['files']}
    for unit in extra.values():
        source = unit['source']
        files.setdefault(source, {'path': source, 'kind': 'knowledge-source',
                                  'sha256': hashlib.sha256(texts[source].encode('utf-8')).hexdigest()})
    for source, row in files.items():
        row['units'] = sum(unit['source'] == source for unit in units)
    compiled['files'] = [files[source] for source in sorted(files)]
    from ravel.workflow import role_registry
    catalogue = _seal({
        'schema_version': 1, 'kind': 'instruction-catalogue', 'generator': GENERATOR,
        'normalisation': compiler.NORMALISATION,
        'registry_sha256': role_registry.registry_sha256(roles_root=root / 'src/ravel/data/roles'),
        'citations_sha256': compiler.digest_value(citations.get('rows', [])),
        'knowledge_source_migrations': sources.get('knowledge_source_migrations', []),
        'files': compiled['files'], 'mirrors': compiled['mirrors'],
        'units': [_stored(u) for u in units]})
    nodes = {}
    for row in sources['canonical']:
        for node in row['nodes']:
            nodes.setdefault(node, []).append(row['path'])
    skills = {}
    for row in sources['canonical']:
        if row['path'].startswith(SKILLS):
            skills.setdefault(row['path'][len(SKILLS):].split('/')[0], []).append(row['path'])
    manifests = _seal({
        'schema_version': 1, 'kind': 'instruction-manifests', 'generator': GENERATOR,
        'catalogue_sha256': catalogue['sha256'],
        'preamble': sources['preamble'], 'protocols': sources['protocols'], 'step_kinds': sources['step_kinds'],
        'checkins': sources['checkins'], 'governing_skills': sources['governing_skills'],
        'nodes': {k: sorted(v) for k, v in sorted(nodes.items())},
        'skills': {k: sorted(v) for k, v in sorted(skills.items())},
        'roles': {card['id']: {'card': compiler.CARD_PATH.format(role=card['id']),
                               'must_read': {i: knowledge[i] for i in card['knowledge']['must_read']}}
                  for card in sorted(cards, key=lambda c: c['id'])},
        'knowledge': knowledge, 'operations': operations,
        'packet': sources.get('packet', {})})
    problems = coverage_problems(Catalogue(catalogue, manifests))
    if problems:
        raise ValueError('instruction manifest errors:\n' + '\n'.join(problems))
    return catalogue, manifests


def _stored(unit):
    stored = {'id': unit['id'], 'kind': unit['kind'], 'form': unit['form'], 'sha256': unit['sha256'],
              'lines': unit['lines'], 'text': unit['text'].split('\n')}
    for key in ('level', 'field', 'census', 'review_required', 'context_review'):
        if unit.get(key) not in (None, False, []):
            stored[key] = unit[key]
    return stored


def render(document: dict) -> str:
    """Deterministic text: one unit per line, so a change reads as a one-line diff."""
    head = {k: v for k, v in document.items() if k not in ('units', 'sha256')}
    lines = ['{']
    for key, value in head.items():
        lines.append(f'{json.dumps(key)}: {json.dumps(value, ensure_ascii=False, sort_keys=True)},')
    if 'units' in document:
        lines.append('"units": [')
        rows = [json.dumps(u, ensure_ascii=False, sort_keys=True) for u in document['units']]
        lines.extend(row + (',' if i < len(rows) - 1 else '') for i, row in enumerate(rows))
        lines.append('],')
    lines.append(f'"sha256": {json.dumps(document["sha256"])}')
    lines.append('}')
    return '\n'.join(lines) + '\n'


# ------------------------------------------------------------------------------- the loaded catalogue

class Catalogue:
    """One loaded catalogue and its manifests, with selector resolution."""

    def __init__(self, catalogue: dict, manifests: dict):
        self.document, self.manifests = catalogue, manifests
        self.sha256 = catalogue['sha256']
        self.units, self.order, self.by_source = {}, {}, {}
        for index, stored in enumerate(catalogue['units']):
            if stored['kind'] == 'context':
                review = stored.get('context_review')
                if not isinstance(review, dict) or any(review.get(k) != stored.get(k)
                                                      for k in ('id', 'sha256', 'kind')) \
                        or compiler.digest_text('\n'.join(stored['text'])) != stored['sha256'] \
                        or not all(isinstance(review.get(k), str) and review[k].strip()
                                   for k in ('reviewed_by', 'reason')):
                    raise ValueError('context unit lacks a current reviewed classification: ' + stored['id'])
            path, _, rest = stored['id'].partition('#')
            section, _, n = rest.rpartition('/')
            unit = {**stored, 'text': '\n'.join(stored['text']), 'source': path, 'section': section, 'n': n}
            self.units[unit['id']] = unit
            self.order[unit['id']] = index
            self.by_source.setdefault(path, []).append(unit)
        self.mirrors = {row['path']: row['canonical'] for row in catalogue['mirrors']
                        if row['relation'] == 'identical'}

    def canonical(self, path: str) -> str:
        return self.mirrors.get(path, path)

    def section(self, path: str, name: str, *, nested: bool) -> list[str]:
        units = self.by_source.get(self.canonical(path), [])
        start = next((i for i, u in enumerate(units) if u['form'] == 'heading' and u['section'] == name), None)
        if start is None:
            raise KeyError(f'no section {name} in {path}')
        level, result = units[start]['level'], [units[start]['id']]
        for unit in units[start + 1:]:
            if unit['form'] == 'heading' and (unit['level'] <= level or not nested):
                break
            result.append(unit['id'])
        return result

    def resolve(self, selector: str) -> list[str]:
        """Unit ids, in catalogue order, for one selector; an unknown selector raises KeyError."""
        kind, _, value = selector.partition(':')
        if kind == 'checkin':
            value = {'checkin1': 'CI1', 'checkin2': 'CI2', 'checkin3': 'CI3',
                     'approve_plan': 'CI1', 'go': 'CI2', 'final': 'CI3'}.get(value, value)
        man = self.manifests
        if kind == 'node' and value in man['nodes']:
            return self.resolve_all(man['nodes'][value])
        if kind == 'skill' and value in man['skills']:
            return self.resolve_all(man['skills'][value])
        if kind == 'protocol' and value in man['protocols']:
            return self.resolve_all(man['protocols']['common'] + man['protocols'][value])
        if kind == 'checkin' and value in man['checkins']:
            return self.resolve_all(man['checkins'].get('common', []) + man['checkins'][value])
        if kind == 'card' and value in man['roles']:
            return [u['id'] for u in self.by_source.get(man['roles'][value]['card'], [])]
        if kind == 'operation' and value in man.get('operations', {}):
            return self.resolve_all(man['operations'][value]['sources'])
        if kind == 'knowledge':
            if value in man.get('knowledge', {}):
                return self.resolve_all(man['knowledge'][value])
            for row in man['roles'].values():
                if value in row['must_read']:
                    return self.resolve_all(row['must_read'][value])
        if kind in ('node', 'skill', 'protocol', 'checkin', 'card', 'knowledge', 'operation'):
            raise KeyError('unknown instruction selector: ' + selector)
        if selector in self.units:
            return [selector]
        path, _, name = selector.partition('#')
        if not name:
            units = self.by_source.get(self.canonical(path))
            if not units:
                raise KeyError('uncatalogued instruction source: ' + path)
            return [u['id'] for u in units]
        nested = name.endswith('+')
        return self.section(path, name.rstrip('+'), nested=nested)

    def resolve_all(self, selectors) -> list[str]:
        seen, result = set(), []
        for selector in selectors:
            for uid in self.resolve(selector):
                if uid not in seen:
                    seen.add(uid)
                    result.append(uid)
        return result


def coverage_problems(cat: Catalogue) -> list[str]:
    """Every unit in at least one node manifest; every manifest selector resolves."""
    problems, covered = [], set()
    man = cat.manifests
    groups = [('preamble', man['preamble'])]
    groups += [(f'node:{k}', [f'node:{k}']) for k in man['nodes']]
    groups += [(f'protocol:{k}', [f'protocol:{k}']) for k in man['protocols'] if k != 'common']
    groups += [(f'checkin:{k}', [f'checkin:{k}']) for k in man['checkins'] if k != 'common']
    groups += [(f'skill:{rule["skill"]}', [f'skill:{rule["skill"]}']) for rule in man['governing_skills']]
    groups += [(f'operation:{name}', [f'operation:{name}']) for name in man.get('operations', {})]
    for role, row in man['roles'].items():
        groups.append((f'card:{role}', [f'card:{role}']))
        groups += [(f'knowledge:{k}', v) for k, v in row['must_read'].items()]
    for name, selectors in groups:
        try:
            covered.update(cat.resolve_all(selectors))
        except KeyError as exc:
            problems.append(f'{name}: {exc.args[0]}')
    problems += ['unit in no node manifest: ' + uid for uid in cat.units if uid not in covered]
    return problems


@lru_cache(maxsize=4)
def _load(identity) -> Catalogue:
    catalogue = json.loads(data_path('catalogue.json').read_text())
    manifests = json.loads(data_path('manifests.json').read_text())
    for document in (catalogue, manifests):
        if _seal(document)['sha256'] != document.get('sha256'):
            raise ValueError(f'installed {document.get("kind")} fails its own digest')
    if manifests['catalogue_sha256'] != catalogue['sha256']:
        raise ValueError('installed instruction manifests name a different catalogue')
    return Catalogue(catalogue, manifests)


def installed() -> Catalogue:
    """The installed catalogue, verified against its own digests when loaded and reloaded whenever
    either file changes (device, inode, size or modification time)."""
    stats = [data_path(name).stat() for name in ('catalogue.json', 'manifests.json')]
    return _load(tuple((s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) for s in stats))

_FAMILY = re.compile(r'(?i)(?:cross[- ]family|(?:different|distinct|second|another|other)\s+(?:model\s+|provider\s+|'
                     r'transport\s+)?famil(?:y|ies)|famil(?:y|ies)\s+(?:distinct|different)\s+from)')


def family_mandates(cat: Catalogue) -> list[str]:
    """Units that require a reviewer or worker from a second model family: prose that states the
    requirement, or an effective card naming roles in ``model.distinct_family_from``. Complete
    must-read records are delivered duties and are scanned like prose. Independent review means a
    fresh session, a different actor and confined reads, never a family."""
    found = []
    for uid, unit in cat.units.items():
        if unit.get('field') == 'model':
            if json.loads(unit['text']).get('distinct_family_from'):
                found.append(uid)
        elif _FAMILY.search(unit['text']):
            found.append(uid)
    return found
