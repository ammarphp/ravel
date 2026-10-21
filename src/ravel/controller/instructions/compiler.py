"""Compile instruction-bearing files into instruction units, the text every worker packet carries.

A unit is one heading, paragraph, list item, table row, quote, comment or code block of a
heading-delimited Markdown section, one entry of a JSON source, or one field entry of an
effective role card. Its id is ``<path>#<heading-slug>/<n>`` (``n`` counts the units of
the section from the heading, unit 0; JSON entries use the entry key). Its digest is the
SHA-256 of its normalised text: NFC, LF line ends, trailing blanks and blank edge lines
removed. Its kind is ``duty`` or ``context``; any duty signal, or a doubt, makes it a duty.

The compiler reads only the source tree it is given and the effective role registry. The
inventory, the canonical-to-mirror relations and the delivering nodes are package data
(``data/instructions/sources.json``); a discovered instruction file that is neither canonical
nor a mirror of a catalogued canonical source is an error, so no instruction escapes the
catalogue. Units compile from canonical sources only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unicodedata

NORMALISATION = 'nfc-lf-rstrip-v1'
CARD_PATH = '.ravel/roles/ravel-{role}.json'
CARD_LISTS = ('protocol', 'must_check', 'escalation', 'operations', 'reviewed_by')
CARD_DUTIES = {'purpose', 'protocol', 'must_check', 'escalation', 'knowledge', 'output', 'stop', 'sees'}
MAX_SOURCE_BYTES = 1 << 20
PROSE = ('paragraph', 'item', 'row', 'quote', 'block')  # forms a census line citation makes a duty
_CARD_FIELDS = ('escalation', 'family', 'id', 'independence', 'kind', 'knowledge', 'model', 'must_check', 'operations',
                'output', 'ownership', 'protocol', 'purpose', 'requires', 'reviewed_by', 'schema_version', 'sees',
                'stop', 'tools', 'version')
_ROLE_ROW = re.compile(r'ROLE-(.+?)-(' + '|'.join(sorted(_CARD_FIELDS, key=len, reverse=True)) + r')(?:-(\d+))?')

_FENCE = re.compile(r'^( {0,3})(`{3,}|~{3,})')
_HEADING = re.compile(r'^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$')
_RULE = re.compile(r'^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$')
_ITEM = re.compile(r'^(\s*)(?:[-*+]|\d{1,9}[.)])(?:[ \t]+|$)')
_TABLE_RULE = re.compile(r'^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$')



def normalise(text: str) -> str:
    text = unicodedata.normalize('NFC', text).replace('\r\n', '\n').replace('\r', '\n')
    return '\n'.join(line.rstrip() for line in text.split('\n')).strip('\n')


def digest_text(text: str) -> str:
    return hashlib.sha256(normalise(text).encode('utf-8')).hexdigest()


def digest_value(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def slug(title: str) -> str:
    """The handbook-section slug rule: lower case, every other character run becomes one hyphen."""
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')


def is_duty(text: str, *, procedural: bool = False) -> bool:
    """Unreviewed text is a duty. Only reviewed_context data can opt a unit out.

    Wording, block form and card-field names cannot prove the absence of a duty.
    procedural remains accepted for callers of the original compiler API.
    """
    return True



# ------------------------------------------------------------------------------- Markdown and text

def _blocks(lines, start=0):
    """Yield (form, first, last, level) for the blocks of Markdown ``lines`` (0-based, inclusive)."""
    i, n = start, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = _FENCE.match(line)
        if fence:
            chars, j = fence.group(2), i + 1
            while j < n:
                close = _FENCE.match(lines[j])
                if close and close.group(2)[0] == chars[0] and len(close.group(2)) >= len(chars) \
                        and not lines[j][close.end():].strip():
                    break
                j += 1
            yield 'code', i, min(j, n - 1), 0
            i = j + 1
            continue
        heading = _HEADING.match(line)
        if heading and (heading.group(2) or '').strip():
            yield 'heading', i, i, len(heading.group(1))
            i += 1
            continue
        if _RULE.match(line):
            yield 'rule', i, i, 0
            i += 1
            continue
        if line.lstrip().startswith('<!--'):
            j = i
            while j < n and '-->' not in lines[j]:
                j += 1
            yield 'comment', i, min(j, n - 1), 0
            i = j + 1
            continue
        if line.lstrip().startswith('|'):
            j = i
            while j + 1 < n and lines[j + 1].lstrip().startswith('|'):
                j += 1
            k = i
            if j > i and _TABLE_RULE.match(lines[i + 1]):
                yield 'table-head', i, i + 1, 0
                k = i + 2
            for row in range(k, j + 1):
                yield 'row', row, row, 0
            i = j + 1
            continue
        if line.lstrip().startswith('>'):
            j = i
            while j + 1 < n and lines[j + 1].lstrip().startswith('>'):
                j += 1
            yield 'quote', i, j, 0
            i = j + 1
            continue
        form = 'item' if _ITEM.match(line) else 'paragraph'
        j = i
        while j + 1 < n:
            nxt = lines[j + 1]
            if (not nxt.strip() or _FENCE.match(nxt) or _ITEM.match(nxt) or _RULE.match(nxt)
                    or (_HEADING.match(nxt) and (_HEADING.match(nxt).group(2) or '').strip())
                    or nxt.lstrip().startswith(('|', '>', '<!--'))):
                break
            j += 1
        yield form, i, j, 0
        i = j + 1


def _frontmatter_end(lines):
    if lines and lines[0].strip() == '---':
        for j in range(1, len(lines)):
            if lines[j].strip() in ('---', '...'):
                return j
    return None


def compile_markdown(path: str, text: str, *, checklist: bool = False) -> list[dict]:
    """Units of one Markdown file, in document order."""
    lines = normalise(text).split('\n')
    units, used = [], {}
    section, count = '', 0

    def add(form, first, last, kind, **extra):
        nonlocal count
        body = '\n'.join(lines[first:last + 1])
        units.append({'id': f'{path}#{section}/{count}', 'source': path, 'section': section, 'n': count,
                      'form': form, 'kind': kind, 'lines': [first + 1, last + 1], 'text': normalise(body), **extra})
        count += 1

    end = _frontmatter_end(lines)
    start = 0
    if end is not None:
        add('frontmatter', 0, end, 'duty')
        start = end + 1
    for form, first, last, depth in _blocks(lines, start):
        if form == 'rule':
            continue
        if form == 'heading':
            title = _HEADING.match(lines[first]).group(2).strip()
            base = slug(title) or 'section'
            used[base] = used.get(base, -1) + 1
            section = base if used[base] == 0 else f'{base}-{used[base]}'
            count = 0
            add('heading', first, last, 'duty', level=depth)
            continue
        body = '\n'.join(lines[first:last + 1])
        kind = 'duty'
        add(form, first, last, kind)
    return units


def compile_text(path: str, text: str) -> list[dict]:
    """Units of a plain-text or configuration file: blank-line separated blocks under one section."""
    lines = normalise(text).split('\n')
    units, i, n = [], 0, len(lines)
    while i < n:
        if not lines[i].strip():
            i += 1
            continue
        j = i
        while j + 1 < n and lines[j + 1].strip():
            j += 1
        body = normalise('\n'.join(lines[i:j + 1]))
        units.append({'id': f'{path}#/{len(units)}', 'source': path, 'section': '', 'n': len(units),
                      'form': 'block', 'kind': 'duty' if is_duty(body) else 'context',
                      'lines': [i + 1, j + 1], 'text': body})
        i = j + 1
    return units


# ------------------------------------------------------------------------------- JSON sources

def _key_lines(text):
    """{(key,): line, (key, child): line} for top-level keys and their keys or array elements."""
    found, stack, line, expect, i, n = {}, [], 1, False, 0, len(text)

    def element():
        stack[-1][1] += 1
        if len(stack) <= 2:
            found.setdefault(tuple(entry[1] for entry in stack), line)

    while i < n:
        c = text[i]
        if c == '\n':
            line += 1
        elif c == '"':
            j = i + 1
            while text[j] != '"':
                j += 2 if text[j] == '\\' else 1
            k = j + 1
            while k < n and text[k] in ' \t\r\n':
                k += 1
            if stack and stack[-1][0] == '{' and k < n and text[k] == ':':
                stack[-1][1] = json.loads(text[i:j + 1])
                if len(stack) <= 2:
                    found.setdefault(tuple(entry[1] for entry in stack), line)
            elif stack and stack[-1][0] == '[' and expect:
                element()
            expect = False
            i = j + 1
            continue
        elif c in '{[':
            if stack and stack[-1][0] == '[' and expect:
                element()
            stack.append([c, -1 if c == '[' else None])
            expect = c == '['
        elif c in '}]':
            stack.pop()
            expect = False
        elif c == ',':
            expect = bool(stack) and stack[-1][0] == '['
        elif not c.isspace() and c != ':' and stack and stack[-1][0] == '[' and expect:
            element()
            expect = False
        i += 1
    return found


def _render(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _string_values(value):
    """Prose of a JSON value for classification: its strings and its keys read as words."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield str(key).replace('_', ' ')
            yield from _string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _string_values(child)


def compile_json(path: str, text: str, *, split_over: int = 400) -> list[dict]:
    """One unit per top-level entry; a large object or array entry splits into one unit per child.

    An object child is keyed by its own key, or by its ``id`` when the child is an identified
    record in an array (handbooks, premises); an array child without an id by its index."""
    document = json.loads(text)
    lines = _key_lines(text)
    total = text.count('\n') + 1
    entries = document.items() if isinstance(document, dict) else [('items', document)]
    units = []

    def add(section, n, value, first):
        rendered = _render(value)
        prose = ' '.join(_string_values(value))
        units.append({'id': f'{path}#{section}/{n}', 'source': path, 'section': section, 'n': n, 'form': 'entry',
                      'kind': 'duty' if is_duty(prose) else 'context',
                      'lines': [first, first + rendered.count('\n')] if first else None, 'text': normalise(rendered)})

    for key, value in entries:
        section = slug(str(key)) or 'entry'
        first = lines.get((key,))
        big = isinstance(value, (dict, list)) and len(value) > 1 and len(_render(value)) > split_over
        if not big:
            add(section, 0, {key: value}, first)
            continue
        children = value.items() if isinstance(value, dict) else enumerate(value)
        for child_key, child in children:
            if isinstance(value, list) and isinstance(child, dict) and isinstance(child.get('id'), str):
                name = slug(child['id']) or str(child_key)
            else:
                name = slug(str(child_key)) if isinstance(value, dict) else str(child_key)
            add(section, name, {child_key: child} if isinstance(value, dict) else child,
                lines.get((key, child_key)))
    for unit, nxt in zip(units, units[1:] + [None]):
        if unit['lines'] and nxt and nxt['lines'] and nxt['lines'][0] > unit['lines'][0]:
            unit['lines'][1] = max(unit['lines'][0], nxt['lines'][0] - 1)
        elif unit['lines'] and nxt is None:
            unit['lines'][1] = max(unit['lines'][0], total - 1)
    return units


# ------------------------------------------------------------------------------- effective cards

_OUTPUT_FILE = re.compile(r'`[^`\n]*(?:/|\.(?:json|jsonl|md|yaml|yml|toml|csv|tsv|txt|pdf|png|svg|root|yoda|lhe|hepmc|'
                          r'tex|py|cc|dat|slha|onnx)\b)[^`\n]*`')
_OUTPUT_VERB = re.compile(r'\s*(?:Return|Write|Emit|Produce|Record|Report|Deliver|Attach|Output)\b')


def names_output(text: str, card: dict) -> bool:
    """A protocol sentence that names an output: a declared output path, kind or schema, a file-like
    token, an output schema id, or an opening verb that produces something."""
    declared = card.get('output', {})
    names = {row[key] for row in declared.get('declared_outputs', []) for key in ('path', 'kind')}
    names.add(declared.get('schema'))
    return bool(any(name and name in text for name in names) or _OUTPUT_FILE.search(text)
                or re.search(r'\b(?:findings|producer)\.v\d\b', text) or _OUTPUT_VERB.match(text))


def card_units(card: dict) -> list[dict]:
    """Units of one effective card: list fields element by element (an empty list as one ``none``
    unit), every other field whole.

    The canonical path is the governed-node rendering of the effective card, the file the census
    cites; host profiles are mirrors of it. A protocol sentence that names an output is
    review-required: the reviewer checks it against that output."""
    path = CARD_PATH.format(role=card['id'])
    units = []
    for field in sorted(card):
        value = card[field]
        entries = (list(enumerate(value)) or [('none', [])]) if field in CARD_LISTS else [(0, value)]
        for n, entry in entries:
            text = entry if isinstance(entry, str) else json.dumps(entry, sort_keys=True, ensure_ascii=False)
            unit = {'id': f'{path}#{field}/{n}', 'source': path, 'section': field, 'n': n,
                    'form': 'field', 'kind': 'duty',
                    'lines': None, 'text': normalise(text), 'role': card['id'], 'field': field}
            if field == 'protocol' and names_output(text, card):
                unit['review_required'] = True
            units.append(unit)
    return units


# ------------------------------------------------------------------------------- the inventory

def load_sources(path: Path) -> dict:
    document = json.loads(Path(path).read_text())
    if document.get('kind') != 'instruction-sources' or document.get('schema_version') != 1:
        raise ValueError('instruction-sources/v1 required')
    return document


def _files(root: Path, patterns):
    found = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and not path.is_symlink() and path.name != '.DS_Store' \
                    and '__pycache__' not in path.parts:
                found.add(path.relative_to(root).as_posix())
    return found


def _read(root: Path, relative: str) -> str:
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents) \
            or not path.is_file():
        raise ValueError('regular instruction source required: ' + relative)
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError('instruction source exceeds the bounded read: ' + relative)
    return raw.decode('utf-8')


class View:
    """The files a tree publishes and the text it publishes for each.

    The default view ships every file as it is. ``catalogue.export_view`` narrows it to the export
    selection and applies the declared public edits, so a source checkout and the public tree it
    exports compile the same units."""

    def __init__(self, root: Path, *, shipped: set[str] | None = None, transforms: dict | None = None,
                 publish=None):
        self.root, self._shipped, self._transforms, self._publish = Path(root), shipped, transforms or {}, publish

    def shipped(self, relative: str) -> bool:
        return self._shipped is None or relative in self._shipped

    def read(self, relative: str) -> str:
        text = _read(self.root, relative)
        if self._publish is not None and relative in self._transforms:
            return self._publish(self.root, relative, relative, self._transforms).decode('utf-8')
        return text


def compile_file(relative: str, text: str, kind: str) -> list[dict]:
    if relative.endswith('.json'):
        return compile_json(relative, text)
    if relative.endswith('.md'):
        return compile_markdown(relative, text, checklist=kind == 'workflow-checklist')
    return compile_text(relative, text)


def _mirror_target(rule, relative):
    """The canonical path a mirror rule names for ``relative`` (``{name}`` binds one segment, ``{rest}`` any)."""
    pattern = re.escape(rule['mirror']).replace(r'\{rest\}', '(?P<rest>.+)').replace(r'\{name\}', '(?P<name>[^/]+)')
    found = re.fullmatch(pattern, relative)
    if not found:
        return None
    return rule['canonical'].format(**found.groupdict())


def _strip_generated_mark(text):
    first, _, rest = text.partition('\n')
    return rest if first.startswith('<!-- Generated from the RAVEL role registry') else text


def build(root: Path, sources: dict, *, cards: list[dict], view: View | None = None) -> dict:
    """The catalogue for ``root``: units, the canonical sources and the mirror map.

    Units compile from the published text of each canonical source (``view``). The mirror map must
    be total: every discovered instruction file that the tree publishes is a canonical source, the
    governed-node rendering of an effective card, or a mirror whose canonical source is in the
    catalogue; a file the export withholds is outside the catalogue (``withheld``), and a canonical
    source must be published. Byte equality of a mirror is kept by its own generator gate (skill
    sync, instruction bundle, host-surface render); ``drift`` lists the mirrors that currently
    differ, for the build report."""
    root = Path(root)
    view = view if view is not None else View(root)
    canonical = {row['path']: row for row in sources['canonical']}
    found = _files(root, sources['discover'])
    discovered = {relative for relative in found if view.shipped(relative)}
    units, mirrors, drift, errors = [], [], [], []
    texts = {}
    for relative in sorted(canonical):
        row = canonical[relative]
        if not (root / relative).is_file():
            errors.append('canonical instruction source missing: ' + relative)
            continue
        if not view.shipped(relative):
            errors.append('canonical instruction source is withheld from the export: ' + relative)
            continue
        texts[relative] = view.read(relative)
        units.extend(compile_file(relative, texts[relative], row['kind']))
    role_paths = {CARD_PATH.format(role=card['id']): card for card in cards}
    for card in cards:
        units.extend(card_units(card))
    for relative in sorted(discovered - set(canonical)):
        if relative in role_paths:
            if json.loads(view.read(relative)).get('card') != role_paths[relative]:
                drift.append(relative)
            continue
        rule = next((r for r in sources['mirrors'] if _mirror_target(r, relative)), None)
        if rule is None:
            errors.append('instruction file without a canonical source or delivering node: ' + relative)
            continue
        target, relation = _mirror_target(rule, relative), rule['relation']
        if relation in ('identical', 'generated-from', 'host-stub'):
            if target not in texts:
                errors.append(f'mirror {relative} names an uncatalogued canonical source {target}')
            elif relation == 'identical' and view.read(relative) != texts[target]:
                drift.append(relative)
            elif relation == 'generated-from' and \
                    normalise(_strip_generated_mark(texts[target])) != normalise(view.read(relative)):
                drift.append(relative)
        elif relation == 'card-profile':
            if target not in role_paths:
                errors.append(f'profile {relative} names an unregistered role card {target}')
        elif relation != 'card-input':
            errors.append(f'unknown mirror relation {relation} for {relative}')
        mirrors.append({'path': relative, 'canonical': target, 'relation': relation})
    seen = set()
    for unit in units:
        if unit['id'] in seen:
            errors.append('duplicate instruction unit id: ' + unit['id'])
        seen.add(unit['id'])
        unit['sha256'] = digest_text(unit['text'])
    reviewed = set()
    by_id = {u['id']: u for u in units}
    for classification in sources.get('reviewed_context', []):
        uid = classification.get('id')
        unit = by_id.get(uid)
        if uid in reviewed or unit is None or classification.get('kind') != 'context' \
                or classification.get('sha256') != unit['sha256'] \
                or not all(isinstance(classification.get(k), str) and classification[k].strip()
                           for k in ('reviewed_by', 'reason')):
            errors.append('invalid or stale reviewed context classification: ' + str(uid))
            continue
        reviewed.add(uid)
        unit['kind'] = 'context'
        unit['context_review'] = dict(classification)
    if errors:
        raise ValueError('instruction catalogue errors:\n' + '\n'.join(errors))
    files = [{'path': p, 'kind': canonical[p]['kind'], 'sha256': hashlib.sha256(texts[p].encode()).hexdigest(),
              'units': sum(1 for u in units if u['source'] == p)} for p in sorted(texts)]
    files += [{'path': p, 'kind': 'role-card', 'sha256': digest_value(card),
               'units': sum(1 for u in units if u['source'] == p)} for p, card in sorted(role_paths.items())]
    return {'files': files, 'mirrors': mirrors, 'units': units, 'drift': drift, 'texts': texts,
            'withheld': sorted(found - discovered)}


# ------------------------------------------------------------------------------- census citations

def _section_ranges(units):
    """{heading id: [unit ids of the section, nested sections included]}"""
    result, open_ = {}, []
    for unit in units:
        if unit['form'] == 'heading':
            open_ = [(level, uid) for level, uid in open_ if level < unit['level']]
            open_.append((unit['level'], unit['id']))
            result[unit['id']] = []
        for _, uid in open_:
            result[uid].append(unit['id'])
    return result


def attach_census(units, census, texts):
    """Attach census ids to the units that state them.

    A role row binds its card field entry by id. A row citing a file's first line states the whole
    file. Another source row binds the unit holding its cited line when the source still has the
    census digest, otherwise the unit holding its quoted evidence; a cited heading binds its whole
    section. A prose unit that a row cites by line or evidence states that obligation, so it is a
    duty whatever its wording. Decision rows mark their units review-required."""
    by_source, by_id = {}, {u['id']: u for u in units}
    for unit in units:
        by_source.setdefault(unit['source'], []).append(unit)
    sections = {}
    for source, rows in by_source.items():
        sections[source] = _section_ranges(rows)
    for row in census:
        bound = []
        role = _ROLE_ROW.fullmatch(row['id'])
        if role:
            uid = f'{CARD_PATH.format(role=role.group(1))}#{role.group(2)}/{role.group(3) or 0}'
            bound = [uid] if uid in by_id else []
        elif re.fullmatch(r'ROLE-.+-(?:dispatch|identity)', row['id']):
            continue  # structural rows have a separate enforcement owner, never prose bindings
        elif row.get('source') in texts and row.get('pointer') and 'declared_value' in row:
            pointer = row['pointer']
            value = json.loads(texts[row['source']])
            try:
                if not pointer.startswith('/'):
                    raise ValueError('absolute JSON pointer required')
                for token in pointer[1:].split('/'):
                    token = token.replace('~1', '/').replace('~0', '~')
                    value = value[int(token)] if isinstance(value, list) else value[token]
                uid = row['source'] + '#' + '/'.join(slug(token.replace('~1', '/').replace('~0', '~'))
                                                       for token in pointer[1:].split('/'))
                if (json.dumps(value, sort_keys=True, allow_nan=False)
                        != json.dumps(row['declared_value'], sort_keys=True, allow_nan=False) or uid not in by_id):
                    raise ValueError('source pointer value or instruction unit changed')
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError('unresolved source pointer citation: ' + row['id']) from exc
            bound = [uid]
        elif row.get('source') in by_source and row.get('line'):
            rows = by_source[row['source']]
            current = hashlib.sha256(texts[row['source']].encode()).hexdigest() if row['source'] in texts else None
            hit = None
            if current is not None and current == row.get('source_sha256'):
                if row['line'] == 1:
                    bound = [u['id'] for u in rows]
                else:
                    hit = next((u for u in rows if u['lines'] and u['lines'][0] <= row['line'] <= u['lines'][1]), None)
            evidence = ' '.join(str(row.get('evidence') or '').split())
            if not bound and hit is None and evidence:
                hits = [u for u in rows if evidence in ' '.join(u['text'].split())]
                if len(hits) == 1 and ' '.join(hits[0]['text'].split()).count(evidence) == 1:
                    hit = hits[0]
            if not bound and hit is None:
                migration = row.get('migration', {})
                pins = migration.get('units', {})
                if migration.get('source_sha256') == current and current is not None \
                        and migration.get('reviewed_by') and migration.get('reason') and pins \
                        and all(uid in by_id and by_id[uid]['source'] == row['source']
                                and digest_text(by_id[uid]['text']) == digest for uid, digest in pins.items()):
                    bound = list(pins)
                else:
                    raise ValueError('unresolved or ambiguous census citation: ' + row['id'])
            if hit is not None:
                bound = sections[row['source']].get(hit['id'], [hit['id']]) if hit['form'] == 'heading' else [hit['id']]
                if hit['form'] in PROSE:
                    hit['kind'] = 'duty'  # the census names this line as an obligation
        else:
            raise ValueError('unresolved census citation source or line: ' + row['id'])
        for uid in bound:
            unit = by_id[uid]
            unit.setdefault('census', [])
            if row['id'] not in unit['census']:
                unit['census'].append(row['id'])
            if row.get('decision'):
                unit['review_required'] = True
    for unit in units:
        if 'census' in unit:
            unit['census'].sort()
