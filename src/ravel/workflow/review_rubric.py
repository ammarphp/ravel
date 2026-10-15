"""Review rubrics as data: what a review panel checks, and a pinned overlay that tightens it.

A rubric (``data/review/<name>.json``, kind ``review-rubric``) lists items. Each item states
the evidence that satisfies it and what counts as a blocking finding. An item with a
``rule`` is computed over the review packet the analysis declares; an item whose rule is
null is a judgment item the reviewer answers with located evidence.

Rules are data, so an overlay can add a computed item without a code change. A rule is an
object with exactly one of these forms (paths are dotted keys into the packet, or into
the row inside ``each``):

- ``{"present": [path, ...]}``: every path holds a value (false and 0 are values; null,
  an empty string, list or object are not);
- ``{"equals": {"path": p, "value": v}}``;
- ``{"at_most": {"path": p, "limit": number}}`` or ``{"at_most": {"path": p, "limit_path": q}}``;
- ``{"each": {"path": list, "where": {path: value}, "nonempty": bool, "require": rule}}``:
  the list is declared and every row matching ``where`` satisfies ``require``;
  ``nonempty`` also requires at least one matching row;
- ``{"all": [rule, ...]}`` and ``{"any": [rule, ...]}``;
- ``{"when": rule, "then": rule}``: ``then`` is required only when ``when`` holds.

``evaluate`` returns a ``ravel-check-result``. A blocking item that fails is an ``A``
finding naming the item; an advisory item that fails is a ``C`` finding. A packet that
lacks a whole section the rubric reads is ``inconclusive``, never a pass.

An overlay (kind ``review-rubric-overlay``) lives outside the repository and is named by
a pin ``{"path", "sha256"}``. It may ``add`` items and ``tighten`` existing ones: raise an
advisory item to blocking, and add a rule that must hold together with the item's own
rule. It cannot remove an item, replace a rule or lower a severity. A run selects its
rubric in ``inputs/review_rubric.json``; ``review_projection.build`` then places the
merged rubric in every reviewer packet of that run.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .state_io import atomic_json, read_json

SCHEMA_VERSION = 1
KIND = 'review-rubric'
OVERLAY_KIND = 'review-rubric-overlay'
SELECTION_KIND = 'review-rubric-selection'
SELECTION = 'inputs/review_rubric.json'
CHECK_ID = 'review.rubric'
SEVERITIES = ('advisory', 'blocking')
MATERIALITY = {'blocking': 'A', 'advisory': 'C'}
RUBRICS = {'search-analysis-review': 'review/search_analysis_rubric.json'}
FORMS = ('present', 'equals', 'at_most', 'each', 'all', 'any', 'when')
ITEM_KEYS = {'id', 'section', 'topic', 'severity', 'question', 'evidence', 'blocking', 'rule'}
TIGHTEN_KEYS = {'id', 'severity', 'rule', 'evidence', 'blocking'}
MAX_ITEMS = 400
MAX_OVERLAY_BYTES = 1_000_000
MAX_DEPTH = 8
_ID = re.compile(r'[A-Za-z][A-Za-z0-9._-]{0,63}')
_PATH = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*')
_SHA = re.compile(r'[0-9a-f]{64}')
_MISSING = object()


# ---- rules --------------------------------------------------------------------------------

def _is_path(value):
    return type(value) is str and _PATH.fullmatch(value) is not None


def _number(value):
    return type(value) in (int, float) and value == value and abs(value) != float('inf')


def rule_errors(rule, where='rule', depth=0):
    """Errors of one rule against the rule forms above; empty when it is well formed."""
    if depth > MAX_DEPTH:
        return [f'{where}: nested deeper than {MAX_DEPTH}']
    if type(rule) is not dict:
        return [f'{where}: a rule is an object']
    keys = set(rule)
    form = next((f for f in FORMS if f in keys), None)
    if form is None or keys != ({'when', 'then'} if form == 'when' else {form}):
        return [f'{where}: a rule has exactly one form of ' + ', '.join(FORMS)]
    body = rule[form]
    if form == 'present':
        ok = type(body) is list and body and all(_is_path(p) for p in body)
        return [] if ok else [f'{where}.present: a non-empty list of paths']
    if form == 'equals':
        ok = (type(body) is dict and set(body) == {'path', 'value'} and _is_path(body['path'])
              and type(body['value']) in (bool, int, float, str))
        return [] if ok else [f'{where}.equals: {{path, value}} with a scalar value']
    if form == 'at_most':
        ok = (type(body) is dict and _is_path(body.get('path'))
              and (set(body) == {'path', 'limit'} and _number(body['limit'])
                   or set(body) == {'path', 'limit_path'} and _is_path(body['limit_path'])))
        return [] if ok else [f'{where}.at_most: {{path, limit}} or {{path, limit_path}}']
    if form == 'each':
        if type(body) is not dict or not {'path', 'require'} <= set(body) <= {'path', 'where', 'nonempty', 'require'}:
            return [f'{where}.each: {{path, require}} with optional where and nonempty']
        errors = [] if _is_path(body['path']) else [f'{where}.each.path: a path']
        selector = body.get('where', {})
        if type(selector) is not dict or not all(_is_path(k) and type(v) in (bool, int, float, str)
                                                 for k, v in selector.items()):
            errors.append(f'{where}.each.where: paths mapped to scalar values')
        if type(body.get('nonempty', False)) is not bool:
            errors.append(f'{where}.each.nonempty: true or false')
        return errors + rule_errors(body['require'], where + '.each.require', depth + 1)
    if form in ('all', 'any'):
        if type(body) is not list or not body:
            return [f'{where}.{form}: a non-empty list of rules']
        return [e for i, r in enumerate(body) for e in rule_errors(r, f'{where}.{form}[{i}]', depth + 1)]
    return rule_errors(body, where + '.when', depth + 1) + rule_errors(rule['then'], where + '.then', depth + 1)


def _get(node, path):
    for part in path.split('.'):
        if type(node) is not dict or part not in node:
            return _MISSING
        node = node[part]
    return node


def _filled(value):
    if value is _MISSING or value is None:
        return False
    if type(value) is str:
        return bool(value.strip())
    return value not in ([], {})


def _same(value, expected):
    # true is not 1: a declared boolean is compared as a boolean.
    return type(value) is type(expected) and value == expected or (
        _number(value) and _number(expected) and type(value) is not bool and type(expected) is not bool
        and value == expected)


def _misses(rule, node, at):
    """What ``node`` lacks to satisfy ``rule``: a list of statements, empty when it holds."""
    form = next(f for f in FORMS if f in rule)
    body = rule[form]
    if form == 'present':
        return [f'{at}{path} is not stated' for path in body if not _filled(_get(node, path))]
    if form == 'equals':
        value = _get(node, body['path'])
        if value is _MISSING:
            return [f"{at}{body['path']} is not stated"]
        return [] if _same(value, body['value']) else [
            f"{at}{body['path']} is {json.dumps(value)}, not {json.dumps(body['value'])}"]
    if form == 'at_most':
        value = _get(node, body['path'])
        limit = body['limit'] if 'limit' in body else _get(node, body['limit_path'])
        if not _number(value) or type(value) is bool:
            return [f"{at}{body['path']} is not a stated number"]
        if not _number(limit) or type(limit) is bool:
            return [f"{at}{body['limit_path']} is not a stated number"]
        return [] if value <= limit else [f"{at}{body['path']} is {value:g}, above the limit {limit:g}"]
    if form == 'each':
        rows = _get(node, body['path'])
        if type(rows) is not list:
            return [f"{at}{body['path']} is not declared as a list"]
        selector = body.get('where', {})
        found, matched = [], 0
        for index, row in enumerate(rows):
            if not all(_same(_get(row, key), expected) for key, expected in selector.items()):
                continue
            matched += 1
            name = row.get('name') if type(row) is dict and type(row.get('name')) is str else str(index)
            found.extend(_misses(body['require'], row, f"{at}{body['path']}[{name}]."))
        if body.get('nonempty') and not matched:
            chosen = ' with ' + ', '.join(f'{k} {json.dumps(v)}' for k, v in selector.items()) if selector else ''
            found.append(f"{at}{body['path']} declares no row{chosen}")
        return found
    if form == 'all':
        return [m for r in body for m in _misses(r, node, at)]
    if form == 'any':
        branches = [_misses(r, node, at) for r in body]
        if any(not b for b in branches):
            return []
        return ['none of the accepted alternatives holds: ' + ' | '.join('; '.join(b) for b in branches)]
    return _misses(rule['then'], node, at) if not _misses(body, node, at) else []


def _roots(rule):
    """Top-level packet keys a rule reads (rows inside ``each`` are relative to their list)."""
    form = next(f for f in FORMS if f in rule)
    body = rule[form]
    if form == 'present':
        return {p.split('.')[0] for p in body}
    if form == 'equals':
        return {body['path'].split('.')[0]}
    if form == 'at_most':
        return {body['path'].split('.')[0]} | ({body['limit_path'].split('.')[0]} if 'limit_path' in body else set())
    if form == 'each':
        return {body['path'].split('.')[0]}
    if form in ('all', 'any'):
        return set().union(*(_roots(r) for r in body))
    return _roots(body) | _roots(rule['then'])


# ---- rubric documents ---------------------------------------------------------------------

def item_errors(item, where='item'):
    if type(item) is not dict or set(item) != ITEM_KEYS:
        return [f'{where}: an item has exactly the keys ' + ', '.join(sorted(ITEM_KEYS))]
    errors = []
    if type(item['id']) is not str or not _ID.fullmatch(item['id']):
        errors.append(f'{where}.id: a short identifier')
    for key in ('section', 'topic', 'question', 'evidence', 'blocking'):
        if type(item[key]) is not str or not item[key].strip():
            errors.append(f'{where}.{key}: a non-empty text')
    if not _is_path(item['section']) or '.' in item['section']:
        errors.append(f'{where}.section: one packet key')
    if item['severity'] not in SEVERITIES:
        errors.append(f'{where}.severity: ' + ' or '.join(SEVERITIES))
    if item['rule'] is not None:
        errors.extend(rule_errors(item['rule'], where + '.rule'))
    return errors


def rubric_errors(rubric):
    """Schema errors of a rubric document; empty when it is valid."""
    if type(rubric) is not dict:
        return ['a rubric is an object']
    errors = []
    allowed = {'schema_version', 'kind', 'id', 'purpose', 'packet', 'items', 'overlay'}
    if not {'schema_version', 'kind', 'id', 'purpose', 'packet', 'items'} <= set(rubric) <= allowed:
        errors.append('a rubric has schema_version, kind, id, purpose, packet and items')
        return errors
    if rubric['schema_version'] != SCHEMA_VERSION or rubric['kind'] != KIND:
        errors.append(f'schema_version {SCHEMA_VERSION} and kind {KIND} are required')
    if type(rubric['id']) is not str or not _ID.fullmatch(rubric['id']):
        errors.append('id: a short identifier')
    if type(rubric['purpose']) is not str or not rubric['purpose'].strip():
        errors.append('purpose: a non-empty text')
    packet = rubric['packet']
    sections = packet.get('sections') if type(packet) is dict else None
    if (type(packet) is not dict or set(packet) != {'kind', 'sections'} or type(packet['kind']) is not str
            or type(sections) is not list or not sections
            or not all(_is_path(s) and '.' not in s for s in sections) or len(set(sections)) != len(sections)):
        return errors + ['packet: {kind, sections} with distinct section keys']
    items = rubric['items']
    if type(items) is not list or not items or len(items) > MAX_ITEMS:
        return errors + [f'items: between 1 and {MAX_ITEMS} items']
    seen = set()
    for index, item in enumerate(items):
        found = item_errors(item, f'items[{index}]')
        errors.extend(found)
        if found:
            continue
        if item['id'] in seen:
            errors.append(f"items[{index}].id: {item['id']} is repeated")
        seen.add(item['id'])
        if item['section'] not in sections:
            errors.append(f"items[{index}].section: {item['section']} is not a packet section")
    overlay = rubric.get('overlay')
    if overlay is not None and not (type(overlay) is dict and set(overlay) == {'id', 'sha256'}
                                    and type(overlay['id']) is str and type(overlay['sha256']) is str
                                    and _SHA.fullmatch(overlay['sha256'])):
        errors.append('overlay: null or {id, sha256}')
    return errors


def load(rubric_id):
    """The shipped rubric with this id."""
    from ravel.paths import package_data_path
    if rubric_id not in RUBRICS:
        raise ValueError(f'unknown review rubric {rubric_id!r}; shipped rubrics: ' + ', '.join(sorted(RUBRICS)))
    rubric = read_json(Path(package_data_path(RUBRICS[rubric_id])))
    errors = rubric_errors(rubric)
    if errors or rubric['id'] != rubric_id:
        raise ValueError('shipped review rubric is invalid: ' + '; '.join(errors[:5] or ['id differs']))
    return rubric


def digest(document):
    return hashlib.sha256(document_bytes(document)).hexdigest()


def document_bytes(document):
    return (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


# ---- overlay ------------------------------------------------------------------------------

def overlay_errors(overlay, rubric):
    """Errors of an overlay against the rubric it tightens; empty when it may be applied."""
    if type(overlay) is not dict:
        return ['an overlay is an object']
    allowed = {'schema_version', 'kind', 'id', 'rubric', 'add', 'tighten'}
    if not {'schema_version', 'kind', 'id', 'rubric'} <= set(overlay) <= allowed:
        return ['an overlay has schema_version, kind, id and rubric, with add and tighten; '
                'it has no way to remove or replace an item']
    errors = []
    if overlay['schema_version'] != SCHEMA_VERSION or overlay['kind'] != OVERLAY_KIND:
        errors.append(f'schema_version {SCHEMA_VERSION} and kind {OVERLAY_KIND} are required')
    if type(overlay['id']) is not str or not _ID.fullmatch(overlay['id']):
        errors.append('id: a short identifier')
    if overlay['rubric'] != rubric['id']:
        errors.append(f"the overlay is for rubric {overlay['rubric']!r}, not {rubric['id']!r}")
    added, tightened = overlay.get('add', []), overlay.get('tighten', [])
    if type(added) is not list or type(tightened) is not list or not (added or tightened):
        return errors + ['add and tighten are lists, and at least one row is given']
    base = {item['id']: item for item in rubric['items']}
    new = set()
    for index, item in enumerate(added):
        found = item_errors(item, f'add[{index}]')
        errors.extend(found)
        if found:
            continue
        if item['id'] in base or item['id'] in new:
            errors.append(f"add[{index}].id: {item['id']} already exists; use tighten")
        new.add(item['id'])
    seen = set()
    for index, row in enumerate(tightened):
        where = f'tighten[{index}]'
        if type(row) is not dict or 'id' not in row or not set(row) <= TIGHTEN_KEYS or len(row) < 2:
            errors.append(f'{where}: id with any of severity, rule, evidence and blocking')
            continue
        if row['id'] not in base:
            errors.append(f"{where}.id: {row['id']!r} is not an item of the rubric")
            continue
        if row['id'] in seen:
            errors.append(f"{where}.id: {row['id']} is tightened twice")
        seen.add(row['id'])
        if 'severity' in row and row['severity'] != 'blocking':
            errors.append(f'{where}.severity: an overlay can only raise an item to blocking')
        if 'rule' in row:
            errors.extend(rule_errors(row['rule'], where + '.rule'))
        for key in ('evidence', 'blocking'):
            if key in row and (type(row[key]) is not str or not row[key].strip()):
                errors.append(f'{where}.{key}: a non-empty text')
    if len(rubric['items']) + len(added) > MAX_ITEMS:
        errors.append(f'the merged rubric exceeds {MAX_ITEMS} items')
    return errors


def read_overlay(pin):
    """The overlay document and its sha256 for ``{"path", "sha256"}``; the bytes must match the pin."""
    if (type(pin) is not dict or set(pin) != {'path', 'sha256'} or type(pin['path']) is not str or not pin['path']
            or type(pin['sha256']) is not str or not _SHA.fullmatch(pin['sha256'])):
        raise ValueError('a rubric overlay is named by a pin {path, sha256}')
    path = Path(pin['path']).expanduser()
    if not path.is_file():
        raise ValueError('the pinned rubric overlay is not a readable file')
    if path.stat().st_size > MAX_OVERLAY_BYTES:
        raise ValueError('the rubric overlay exceeds its size bound')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('the rubric overlay bytes differ from the pinned sha256')
    try:
        return json.loads(raw.decode('utf-8')), pin['sha256']
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError('the rubric overlay is not a JSON document') from exc


def apply_overlay(rubric, overlay, sha256):
    """The rubric tightened by ``overlay``; the input rubric is unchanged."""
    if rubric.get('overlay') is not None:
        raise ValueError('the rubric already carries an overlay')
    errors = overlay_errors(overlay, rubric)
    if errors:
        raise ValueError('the rubric overlay is refused: ' + '; '.join(errors[:5]))
    merged = deepcopy(rubric)
    by_id = {item['id']: item for item in merged['items']}
    for row in overlay.get('tighten', []):
        item = by_id[row['id']]
        if 'severity' in row:
            item['severity'] = 'blocking'
        if 'rule' in row:
            item['rule'] = deepcopy(row['rule']) if item['rule'] is None else {'all': [item['rule'], deepcopy(row['rule'])]}
        for key in ('evidence', 'blocking'):
            if key in row:
                item[key] = item[key].rstrip() + ' ' + row[key].strip()
    for item in overlay.get('add', []):
        merged['items'].append(deepcopy(item))
        if item['section'] not in merged['packet']['sections']:
            merged['packet']['sections'].append(item['section'])
    merged['overlay'] = {'id': overlay['id'], 'sha256': sha256}
    return merged


def merged(rubric_id, overlay_pin=None):
    """The shipped rubric, tightened by the pinned overlay when one is given."""
    rubric = load(rubric_id)
    if overlay_pin is None:
        return rubric
    overlay, sha256 = read_overlay(overlay_pin)
    return apply_overlay(rubric, overlay, sha256)


def extension_errors(rubric):
    """Errors unless ``rubric`` is the shipped rubric of its id or a tightening of it."""
    errors = rubric_errors(rubric)
    if errors:
        return errors
    if rubric['id'] not in RUBRICS:
        return [f"unknown review rubric {rubric['id']!r}"]
    base = load(rubric['id'])
    got = {item['id']: item for item in rubric['items']}
    if not set(base['packet']['sections']) <= set(rubric['packet']['sections']):
        errors.append('a section of the shipped rubric is missing')
    for item in base['items']:
        mine = got.get(item['id'])
        if mine is None:
            errors.append(f"{item['id']}: an item of the shipped rubric is missing")
            continue
        if SEVERITIES.index(mine['severity']) < SEVERITIES.index(item['severity']):
            errors.append(f"{item['id']}: the severity is lowered")
        kept = (mine['rule'] == item['rule'] or item['rule'] is None
                or type(mine['rule']) is dict and set(mine['rule']) == {'all'} and mine['rule']['all'][:1] == [item['rule']])
        if not kept or mine['section'] != item['section']:
            errors.append(f"{item['id']}: the shipped rule is not retained")
    if len(got) > len(base['items']) and rubric.get('overlay') is None:
        errors.append('added items name no overlay')
    return errors


# ---- evaluation ---------------------------------------------------------------------------

def evaluate(packet, rubric=None, *, check_id=CHECK_ID):
    """Apply ``rubric`` (default: the shipped search-analysis rubric) to a review packet."""
    from .review_projection_checks import _finding, result
    rubric = load('search-analysis-review') if rubric is None else rubric
    errors = rubric_errors(rubric)
    if errors:
        raise ValueError('invalid review rubric: ' + '; '.join(errors[:5]))
    diagnostics = {'rubric': rubric['id'], 'rubric_sha256': digest(rubric), 'overlay': deepcopy(rubric.get('overlay')),
                   'items': len(rubric['items'])}
    if type(packet) is not dict or packet.get('kind') != rubric['packet']['kind']:
        return result(check_id, [], status='inconclusive', outcome='inputs_missing',
                      diagnostics={**diagnostics, 'missing': ['packet of kind ' + rubric['packet']['kind']]})
    absent = [s for s in rubric['packet']['sections'] if type(packet.get(s)) is not dict]
    findings, satisfied, judgment, unread = [], [], [], []
    for item in rubric['items']:
        if item['rule'] is None:
            judgment.append(item['id'])
            continue
        if {item['section'], *_roots(item['rule'])} & set(absent):
            unread.append(item['id'])
            continue
        misses = _misses(item['rule'], packet, '')
        if not misses:
            satisfied.append(item['id'])
            continue
        blocking = item['severity'] == 'blocking'
        summary = (f"{item['id']} ({item['topic']}): " + (item['blocking'] if blocking else item['question'])
                   + ' Missing: ' + '; '.join(misses[:8]) + ('' if len(misses) <= 8 else f'; and {len(misses) - 8} more'))
        findings.append(_finding(check_id, item['id'], summary, materiality=MATERIALITY[item['severity']],
                                 location=item['section'], item=item['id'], topic=item['topic'],
                                 required_evidence=item['evidence'], misses=misses))
    diagnostics.update(satisfied=satisfied, judgment_items=judgment, unread_items=unread, sections_missing=absent)
    if any(f['materiality'] == 'A' for f in findings):
        return result(check_id, findings, diagnostics=diagnostics)
    if absent:
        return result(check_id, findings, status='inconclusive', outcome='inputs_missing',
                      diagnostics={**diagnostics, 'missing': absent})
    return result(check_id, findings, diagnostics=diagnostics)


def check(doc, *, check_id=CHECK_ID):
    """The broker document check. ``doc``: ``{'packet': {...}, 'rubric': id or rubric document}``.

    A rubric document is the one a reviewer received in its packet. It is accepted only as the
    shipped rubric of its id or a tightening of it, so a weakened copy cannot pass a packet.
    """
    from .review_projection_checks import result
    if type(doc) is not dict or 'packet' not in doc:
        return result(check_id, [], status='inconclusive', outcome='inputs_missing', diagnostics={'missing': ['packet']})
    chosen = doc.get('rubric', 'search-analysis-review')
    try:
        if type(chosen) is str:
            rubric = load(chosen)
        else:
            errors = extension_errors(chosen)
            if errors:
                raise ValueError('; '.join(errors[:5]))
            rubric = chosen
    except ValueError as exc:
        return result(check_id, [], status='inconclusive', outcome='rubric_refused', diagnostics={'refusal': str(exc)})
    return evaluate(doc['packet'], rubric, check_id=check_id)


# ---- run selection ------------------------------------------------------------------------

def selection_errors(value):
    if type(value) is not dict or set(value) != {'schema_version', 'kind', 'rubric', 'overlay'}:
        return ['a selection has schema_version, kind, rubric and overlay']
    errors = []
    if value['schema_version'] != SCHEMA_VERSION or value['kind'] != SELECTION_KIND:
        errors.append(f'schema_version {SCHEMA_VERSION} and kind {SELECTION_KIND} are required')
    if value['rubric'] not in RUBRICS:
        errors.append('rubric: a shipped rubric id')
    pin = value['overlay']
    if pin is not None and not (type(pin) is dict and set(pin) == {'path', 'sha256'} and type(pin['path']) is str
                                and pin['path'] and type(pin['sha256']) is str and _SHA.fullmatch(pin['sha256'])):
        errors.append('overlay: null or a pin {path, sha256}')
    return errors


def select(rundir, rubric_id, overlay_path=None):
    """Record the rubric of a run; the overlay is pinned by the sha256 of its current bytes."""
    pin = None
    if overlay_path is not None:
        path = Path(overlay_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError('the rubric overlay is not a readable file')
        pin = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    merged(rubric_id, pin)  # refuse an unknown rubric or an invalid overlay before recording
    value = {'schema_version': SCHEMA_VERSION, 'kind': SELECTION_KIND, 'rubric': rubric_id, 'overlay': pin}
    atomic_json(Path(rundir) / SELECTION, value)
    return value


def selected(rundir):
    """The merged rubric a run selected, or None when it selected none."""
    path = Path(rundir) / SELECTION
    if not path.is_file():
        return None
    value = read_json(path)
    errors = selection_errors(value)
    if errors:
        raise ValueError(f'{SELECTION} is invalid: ' + '; '.join(errors))
    return merged(value['rubric'], value['overlay'])


# ---- command line -------------------------------------------------------------------------

def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(prog='ravel review-rubric', description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)

    def source(p):
        p.add_argument('--rubric', default='search-analysis-review', choices=sorted(RUBRICS))
        p.add_argument('--overlay', help='overlay file that tightens the rubric')
        p.add_argument('--overlay-sha256', help='expected sha256 of the overlay (default: its current bytes)')
    show = sub.add_parser('show', help='print the rubric, merged with an overlay when one is given')
    source(show)
    chosen = sub.add_parser('select', help='record the rubric of a run in ' + SELECTION)
    chosen.add_argument('--rundir', required=True, type=Path)
    chosen.add_argument('--rubric', default='search-analysis-review', choices=sorted(RUBRICS))
    chosen.add_argument('--overlay', help='overlay file that tightens the rubric')
    run = sub.add_parser('check', help='apply the rubric to a review packet; exit 1 on a blocking finding')
    run.add_argument('--packet', required=True, type=Path)
    run.add_argument('--rundir', type=Path, help='use the rubric this run selected')
    source(run)
    args = parser.parse_args(argv)
    try:
        if args.command == 'select':
            value = select(args.rundir, args.rubric, args.overlay)
            print(json.dumps(value, indent=2, sort_keys=True))
            return 0
        if args.command == 'check' and args.rundir is not None:
            rubric = selected(args.rundir)
            if rubric is None:
                raise ValueError(f'{args.rundir} selected no rubric; run `ravel review-rubric select` first')
        else:
            pin = None
            if args.overlay:
                path = Path(args.overlay).expanduser().resolve()
                if not path.is_file():
                    raise ValueError('the rubric overlay is not a readable file')
                pin = {'path': str(path),
                       'sha256': args.overlay_sha256 or hashlib.sha256(path.read_bytes()).hexdigest()}
            rubric = merged(args.rubric, pin)
        if args.command == 'show':
            sys.stdout.write(document_bytes(rubric).decode())
            return 0
        value = evaluate(read_json(args.packet), rubric)
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
        return {'passed': 0, 'failed': 1}.get(value['status'], 3)
    except (OSError, ValueError) as exc:
        print(f'ravel review-rubric: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
