"""Materialize source-bound role knowledge; selection grants no execution authority.

``materialize(card, node_facts, binding)`` consumes the effective role card.
The binding names a workspace and optionally frozen atlas/premise/binding paths,
source_root and withheld_ids. Only atlas metadata, premise rows and authenticated
handbook sections enter the workspace. Lessons and producer headlines are never
sources for this cold bundle. Consumers commit bundle_sha256 to their request and
call validate_cited_ids before accepting a final record.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

from ravel.paths import package_data_path, repository_root
from .knowledge import load_atlas, _node
from .knowledge_atlas import encode, digest
from .role_registry import encode as encode_card

MAX_SOURCE_BYTES = 2 * 1024 * 1024
SELECTORS = {'handbooks_for_node', 'checks_judging_node', 'premises_firing', 'conventions:node_tags'}


def _json(path):
    raw = Path(path).read_bytes()
    if len(raw) > 32 * MAX_SOURCE_BYTES:
        raise ValueError('knowledge store exceeds bounded read')
    return json.loads(raw)


def _effective_knowledge(card, order):
    knowledge = deepcopy(card['knowledge'])
    extra = order.get('knowledge', {})
    if not isinstance(extra, dict):
        raise ValueError('work-order knowledge block must be an object')
    for field in ('must_read', 'derive', 'forbidden'):
        own, requested = knowledge.get(field, []), extra.get(field, [])
        if (not isinstance(own, list) or not isinstance(requested, list) or
                any(not isinstance(v, str) for v in own + requested)):
            raise ValueError('knowledge ' + field + ' must be an ID/selector list')
        knowledge[field] = list(dict.fromkeys(own + requested))
    return knowledge


def _stores(binding):
    atlas = load_atlas(binding.get('atlas_path'))
    rows = atlas['entries']
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate atlas ID')
    premise_path = binding.get('premises_path', package_data_path('knowledge', 'premises.json'))
    premise_pin = next((p for p in atlas.get('generator', {}).get('sources', [])
                        if p['path'] == 'src/ravel/data/knowledge/premises.json'), None)
    if premise_pin and digest(Path(premise_path).read_bytes()) != premise_pin['sha256']:
        raise ValueError('premise source changed')
    premises = _json(premise_path)
    bindings = _json(binding.get('role_bindings_path', package_data_path('knowledge', 'role_bindings.json')))
    if premises.get('kind') != 'physics-premises' or premises.get('schema_version') != 1:
        raise ValueError('physics-premises/v1 required')
    if bindings.get('schema_version') != 1 or not isinstance(bindings.get('roles'), dict):
        raise ValueError('role knowledge bindings/v1 required')
    return atlas, {r['id']: r for r in rows}, premises, bindings


def _handbook(row, binding):
    relative = Path(row['source']['path'])
    if (relative.is_absolute() or '..' in relative.parts or
            relative.parts[:5] != ('src', 'ravel', 'data', 'skills', 'tools') or relative.name != 'SKILL.md'):
        raise ValueError('handbook must come from critical-path tool handbooks')
    root = binding.get('source_root') or repository_root()
    path = Path(root).resolve() / relative if root is not None else package_data_path(*relative.parts[3:])
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('regular handbook source required')
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('handbook source exceeds bounded read')
    raw = path.read_bytes()
    if digest(raw) != row['source']['sha256']:
        raise ValueError('handbook source changed: ' + row['id'])
    return raw.decode('utf-8')


def _sections(text):
    """Top-level handbook sections, including nested headings and fenced code."""
    if text.startswith('---\n'):
        parts = text.split('\n---', 1)
        if len(parts) != 2:
            raise ValueError('unterminated handbook frontmatter')
        text = parts[1].lstrip('\r\n')
    lines = text.splitlines(keepends=True)
    headings, fence = [], None
    for index, line in enumerate(lines):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker:
            chars = marker[1]
            if fence is None:
                fence = chars
            elif chars[0] == fence[0] and len(chars) >= len(fence) and not line[marker.end():].strip():
                fence = None
            continue
        if fence is None and (heading := re.match(r'^## ([^\n]+)', line)):
            title = heading[1].strip().rstrip('#').strip()
            slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
            if not slug or any(h[1] == slug for h in headings):
                raise ValueError('unique handbook section headings required')
            headings.append((index, slug, title))
    result = {}
    for n, (start, slug, title) in enumerate(headings):
        end = headings[n + 1][0] if n + 1 < len(headings) else len(lines)
        result[slug] = {'title': title, 'text': ''.join(lines[start:end]).rstrip() + '\n'}
    return result


def serve_section(handbook_id, section, binding=None):
    """Return exactly one requested ## section and its nested content."""
    binding = binding or {}
    if handbook_id in binding.get('withheld_ids', []):
        raise ValueError('withheld handbook ID: ' + handbook_id)
    rows = {r['id']: r for r in load_atlas(binding.get('atlas_path'))['entries']}
    if handbook_id not in rows:
        raise ValueError('unknown atlas ID: ' + str(handbook_id))
    if rows[handbook_id]['kind'] != 'hb' or '#' in handbook_id:
        raise ValueError('whole handbook ID required')
    sections = _sections(_handbook(rows[handbook_id], binding))
    section = section.removeprefix('#') if isinstance(section, str) else section
    if section not in sections:
        raise ValueError('unknown handbook section: ' + str(section))
    return sections[section]['text']


def resolve_self_checks(identities):
    """The producer's self-check obligations, resolved exactly as the role registry seals them."""
    from .role_registry import resolve_self_checks as resolve
    return resolve(identities)


def _checks(card, binding):
    from .role_registry import load
    result = set()
    for role in card.get('reviewed_by', []):
        result.update(load(role, roles_root=binding.get('roles_root'))['must_check'])
    return sorted(result)


def _selected_sections(identity, sections, facts, role, bindings):
    explicit = facts.get('handbook_sections', {})
    if not isinstance(explicit, dict):
        raise ValueError('handbook_sections must be a map of IDs to section lists')
    chosen = explicit.get(identity)
    if chosen is None:
        chosen = role.get('sections', {}).get(identity)
    if chosen is None:
        operations = bindings.get('sections_by_operation', {})
        chosen = operations.get(facts.get('operation', facts.get('mode')), {}).get(identity)
    if chosen is None:
        chosen = list(sections)[:1]
    if (not isinstance(chosen, list) or not chosen or
            any(not isinstance(s, str) for s in chosen) or len(chosen) != len(set(chosen))):
        raise ValueError('nonempty unique handbook section list required: ' + identity)
    if set(chosen) - set(sections):
        raise ValueError('unknown handbook section: ' + identity)
    return chosen


def materialize(card, node_facts, binding):
    """Write workspace/inputs/knowledge/{index.json,items/*}; return its index.

    Handbook sections and promoted lessons are procedural under the card contract;
    this cold materializer serves no lessons. Consults keep full handbooks. The
    conservative token charge is one UTF-8 byte per token; no tokenizer dependency
    or promise of a model-specific token count is introduced.
    """
    atlas, by_id, premise_doc, bindings = _stores(binding)
    knowledge = _effective_knowledge(card, node_facts)
    cap = knowledge.get('max_procedural_items', 3)
    budget = knowledge['budget_tokens']
    if type(cap) is not int or cap < 1:
        raise ValueError('max_procedural_items must be an integer >= 1')
    if type(budget) is not int or budget < 0:
        raise ValueError('budget_tokens must be a nonnegative integer')
    consult = card.get('family') == 'consult'
    cap = cap if consult else min(cap, 3)
    node_id = node_facts.get('node_id', node_facts.get('id'))
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError('nonempty node_id required')
    unknown_selectors = set(knowledge.get('derive', [])) - SELECTORS
    if unknown_selectors:
        raise ValueError('unresolved knowledge selector: ' + ', '.join(sorted(unknown_selectors)))
    role = bindings['roles'].get(card['id'], {})
    required = list(dict.fromkeys(knowledge.get('must_read', []) + role.get('must_read', [])))
    checks = _checks(card, binding)
    required_checks = set(checks) | set(card.get('must_check', []))
    selected = [(identity, 'must_read') for identity in required]
    selected += [(identity, 'derive:checks_judging_node') for identity in sorted(required_checks)]
    selected += [(identity, 'derive:role_binding') for identity in role.get('include', [])]
    node_rows, missing = _node(by_id, node_facts) if 'handbooks_for_node' in knowledge.get('derive', []) else ([], [])
    from .premises import _facts, _predicate
    operations, tags = _facts(node_facts)
    tags.update(role.get('premise_tags', []))
    premise_rows = {}
    for row in premise_doc['premises'] + premise_doc['conventions']:
        premise_rows[row['id']] = row
        selector = 'premises_firing' if row['id'].startswith('trap:') else 'conventions:node_tags'
        if selector in knowledge.get('derive', []) and _predicate(row['predicate'], operations, tags):
            selected.append((row['id'], 'derive:' + selector))
    selected += [(r['id'], 'derive:handbooks_for_node') for r, _ in node_rows
                 if r['kind'] in ('hb', 'trap', 'check') and '#' not in r['id']]
    omitted, candidates, seen = [], [], set()
    withheld = set(binding.get('withheld_ids', []))
    reviewer = (card.get('independence', {}).get('kind') in ('voting', 'specialist') or
                card.get('sees', {}).get('profile') == 'blind' or card.get('requires', {}).get('blind') is True)
    forbidden = set(knowledge.get('forbidden', []))
    if reviewer:
        forbidden.update(('lessons', 'producer_headline'))
    for identity, reason in selected:
        if identity in seen:
            continue
        seen.add(identity)
        row = by_id.get(identity)
        refused = ('withheld' if identity in withheld else
                   'forbidden' if identity.startswith(('lesson:', 'producer_headline:')) or identity in forbidden or
                   row is not None and row['kind'] in ('lesson', 'producer_headline') else
                   'unresolved' if row is None else None)
        if refused:
            if identity in required or identity in required_checks:
                raise ValueError(('unknown atlas ID: ' if refused == 'unresolved' else refused + ' required ID: ') + identity)
            omitted.append({'id': identity, 'reason': refused})
            continue
        if row['kind'] == 'hb':
            text = _handbook(row, binding)
            sections = _sections(text)
            if '#' in identity:
                fragment = identity.split('#', 1)[1]
                match = re.fullmatch(r'pitfall-([1-9][0-9]*)', fragment)
                bullets = re.findall(r'^[-*] .+(?:\n[ \t]+[^\n]+)*',
                                     sections.get('pitfalls', {}).get('text', ''), re.M)
                if not match or int(match[1]) > len(bullets):
                    raise ValueError('unknown handbook section: ' + identity)
                candidates.append((identity, 'hb', fragment, bullets[int(match[1]) - 1] + '\n', reason))
                continue
            if consult:
                candidates.append((identity, 'hb', None, text, reason))
                continue
            chosen = _selected_sections(identity, sections, node_facts, role, bindings)
            omitted.extend({'id': identity + '#' + slug, 'reason': 'procedural_cap'}
                           for slug in sections if slug not in chosen)
            candidates.extend((identity, 'hb', slug, sections[slug]['text'], reason) for slug in chosen)
        else:
            content = premise_rows.get(identity, {k: row[k] for k in
                ('id', 'kind', 'title', 'summary', 'source', 'check') if k in row})
            candidates.append((identity, row['kind'], None, encode(content).decode(), reason))
    if not consult and sum(kind == 'hb' and identity in required for identity, kind, _, _, _ in candidates) > cap:
        raise ValueError('must_read procedural items exceed cap')
    items, payloads, used, procedural = [], {}, 0, 0
    for identity, kind, section, content, reason in candidates:
        key = identity + '#' + section if section else identity
        raw = content.encode('utf-8')
        refusal = 'procedural_cap' if kind == 'hb' and not consult and procedural >= cap else \
                  'budget' if used + len(raw) > budget else None
        if refusal:
            if identity in required or identity in required_checks:
                raise ValueError('required knowledge exceeds ' + refusal + ': ' + identity)
            omitted.append({'id': identity, 'reason': refusal, **({'section': section} if section else {})})
            continue
        path = f'inputs/knowledge/items/{len(items):04d}-{digest(key.encode())[:16]}.txt'
        item = {'id': identity, 'kind': kind, 'path': path, 'sha256': digest(raw),
                'reason': reason, 'tokens': len(raw)}
        if section:
            item['section'] = section
        if kind == 'hb':
            item['source_sha256'] = by_id[identity]['source']['sha256']
            procedural += 1
        items.append(item)
        payloads[path] = raw
        used += len(raw)
    index = {'schema_version': 1, 'kind': 'knowledge-bundle', 'card_id': card['id'],
             'card_sha256': digest(encode_card(card)), 'node_id': node_id, 'items': items,
             'omitted': omitted, 'budget_tokens': budget, 'used_tokens': used,
             'token_accounting': 'utf8_bytes_upper_bound', 'max_procedural_items': cap,
             'procedural_cap_exempt': consult, 'served_ids': list(dict.fromkeys(i['id'] for i in items)),
             'self_check': resolve_self_checks(checks), 'missing': missing,
             'atlas_sha256': digest(encode(atlas)), 'premises_sha256': digest(encode(premise_doc)),
             'role_bindings_sha256': digest(encode(bindings)),
             'source_restriction_sha256': digest(encode({'withheld_ids': sorted(withheld), 'forbidden': sorted(forbidden)}))}
    index['bundle_sha256'] = digest(encode(index))
    payloads['inputs/knowledge/index.json'] = encode(index)
    workspace_path = Path(binding['workspace']).absolute()
    if workspace_path.is_symlink():
        raise ValueError('symlink in knowledge workspace')
    workspace = workspace_path.resolve()
    for relative in payloads:
        target = workspace / relative
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('symlink in knowledge workspace')
        if target.exists() and (not target.is_file() or target.read_bytes() != payloads[relative]):
            raise ValueError('existing knowledge workspace differs; use a fresh attempt')
    for relative, raw in payloads.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)
    return index


def validate_cited_ids(record, bundle, *, atlas_path=None):
    """Refuse invented or unserved knowledge_used IDs in the final record."""
    if digest(encode({k: v for k, v in bundle.items() if k != 'bundle_sha256'})) != bundle.get('bundle_sha256'):
        raise ValueError('knowledge bundle digest differs')
    cited = record.get('knowledge_used')
    if not isinstance(cited, list) or any(not isinstance(i, str) for i in cited):
        raise ValueError('knowledge_used must be an ID list')
    atlas = load_atlas(atlas_path)
    if digest(encode(atlas)) != bundle['atlas_sha256']:
        raise ValueError('citation atlas differs from materialized atlas')
    known = {r['id'] for r in atlas['entries']}
    if set(cited) - known:
        raise ValueError('unknown atlas ID: ' + ', '.join(sorted(set(cited) - known)))
    served = {r['id'] for r in bundle['items']}
    if set(cited) - served:
        raise ValueError('unserved knowledge ID: ' + ', '.join(sorted(set(cited) - served)))
    return list(dict.fromkeys(cited))


def bind_work_order(order, card, binding):
    """Work-order and toolbelt seam: preserve the order and attach its materialized index."""
    from .work_order_fidelity import digest as order_digest
    result = deepcopy(order)
    index = materialize(card, order, binding)
    result['knowledge'] = _effective_knowledge(card, order)
    result.update(knowledge_bundle=index, knowledge_omitted=deepcopy(index['omitted']),
                  handbooks=list(dict.fromkeys(i['id'] for i in index['items'] if i['kind'] == 'hb')),
                  traps=[i for i in index['served_ids'] if i.startswith('trap:')], self_check=index['self_check'])
    result['order_sha256'] = order_digest(result)
    return result


def omission_census(work_orders):
    """Every withheld item, including unselected sections, grouped by work order."""
    return [{'node_id': order['node_id'],
             **({'order_sha256': order['order_sha256']} if 'order_sha256' in order else {}), **deepcopy(row)}
            for order in work_orders for row in order['knowledge_bundle']['omitted']]


def agentrivet_brief(card, briefs, stage, last_draft=None, *, role_bindings_path=None):
    """Preserve the four original Briefs projections, including live observations.

    These are supplied construction inputs, separate from the cold knowledge
    bundle. This adapter neither executes a worker nor replaces the upstream
    runtime. The dispatcher supplies the existing Briefs instance.
    """
    document = _json(role_bindings_path or package_data_path('knowledge', 'role_bindings.json'))
    row = document['roles'].get(card['id'], {})
    if 'brief_role' not in row:
        raise ValueError('no construction brief binding for role')
    from .agentrivet_brief import PARTS
    if list(PARTS[row['brief_role']]) != row['brief_parts']:
        raise ValueError('construction brief binding drift')
    return briefs(row['brief_role'], stage, last_draft)
