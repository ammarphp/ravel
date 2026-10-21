"""Typed check-ins rendered by the controller from run state (``checkin.v1``).

A check-in is a machine artifact before it is a message. The controller renders it from a view
of run state: the current pins (plan, reading, contract, waypoint evidence, prior authority),
the route's sections, every numbered flag, open question and ambiguity, the plan's steps,
deliverables and boundaries, and the response channel. Validation re-renders the artifact from
the current state view, so a check-in that drops a flag, hides a question, removes the
alteration channel, reorders a section, leaves a required section empty or a placeholder, or
carries stale pins is refused before assent is solicited. The text shown at the terminal is a deterministic rendering of the artifact.
"""
from __future__ import annotations

from copy import deepcopy
import re

from . import common

SCHEMA = 'checkin.v1'
# The universal sections, in order, for each kind; a route template adds its own sections
# (CONTROLLER-SPEC 5.2 ``checkins``), which must appear in the declared order before ``respond``.
REQUIRED = {
    'approve_plan': ('preamble', 'plan', 'flags', 'respond'),
    'go': ('preamble', 'waypoint', 'flags', 'respond'),
    'deviation': ('preamble', 'change', 'respond'),
    'final': ('preamble', 'results', 'flags', 'respond'),
    'escalation': ('preamble', 'question', 'options', 'respond'),
    'r3_action': ('preamble', 'action', 'options', 'respond'),
    'steering': ('preamble', 'policy', 'respond'),
}
TITLES = {'approve_plan': 'CHECK-IN 1: plan', 'go': 'CHECK-IN 2: early verification',
          'deviation': 'DEVIATION CHECK-IN', 'final': 'FINAL CHECK-IN: results',
          'escalation': 'ESCALATION: a question for you', 'r3_action': 'DECISION NEEDED (R3)',
          'steering': 'STEERING POLICY'}
ITEM_KINDS = ('steps', 'deliverables', 'boundaries', 'ambiguities', 'questions', 'assumptions')
GENERATED = ('plan', 'flags', 'options', 'respond')
# A line holding only a placeholder (or no word at all) is no content.
PLACEHOLDER = re.compile(r'\W*(?:tbd|tba|todo|fixme|xxx|placeholder|to be (?:determined|decided|added|written))?\W*',
                         re.I)


def _hollow(section):
    """Whether a supplied section has no lines or only placeholder lines."""
    return all(PLACEHOLDER.fullmatch(line) for line in section['lines'])


def _strings(rows, label):
    if type(rows) is not list or any(type(r) is not str or not r.strip() for r in rows):
        raise ValueError(f'check-in {label} must be a list of nonempty strings')
    return list(rows)


def _item_text(item):
    return item if type(item) is str else common.canonical(item)


def _view(kind, view):
    if type(view) is not dict:
        raise ValueError('a check-in renders from a run-state view object')
    allowed = {'run_id', 'pins', 'sections', 'flags', 'items', 'options', 'required_sections', 'summary'}
    extra = set(view) - allowed
    if extra:
        raise ValueError('unknown check-in view fields: ' + ', '.join(sorted(extra)))
    if type(view.get('run_id')) is not str or not view['run_id']:
        raise ValueError('a check-in view names its run')
    pins = view.get('pins', {})
    if type(pins) is not dict or not pins or any(type(k) is not str or type(v) is not str or not v
                                                 for k, v in pins.items()):
        raise ValueError('a check-in view carries the current pins (name -> digest or record id)')
    sections = view.get('sections', [])
    if type(sections) is not list:
        raise ValueError('check-in sections are a list')
    for row in sections:
        if (type(row) is not dict or set(row) != {'id', 'title', 'lines'} or type(row['id']) is not str
                or not row['id'] or type(row['title']) is not str):
            raise ValueError('a check-in section is {id, title, lines}')
        _strings(row['lines'], f'section {row["id"]} lines')
        if row['id'] in GENERATED:
            raise ValueError(f'section {row["id"]!r} is generated from run state; a view cannot supply it')
    flags = view.get('flags', [])
    if type(flags) is not list:
        raise ValueError('check-in flags are a list')
    for flag in flags:
        if (type(flag) is not dict or set(flag) != {'kind', 'text'}
                or flag['kind'] not in ('assumption', 'decision', 'question', 'ambiguity', 'risk')
                or type(flag['text']) is not str or not flag['text'].strip()):
            raise ValueError('a check-in flag is {kind, text}')
    items = view.get('items', {})
    if type(items) is not dict or not set(items) <= set(ITEM_KINDS):
        raise ValueError('check-in items are drawn from ' + ', '.join(ITEM_KINDS))
    for key, rows in items.items():
        if type(rows) is not list or any(
                not ((type(row) is str and row.strip()) or (type(row) is dict and row))
                for row in rows):
            raise ValueError(f'check-in {key} must be a list of nonempty strings or objects')
        common.canonical(rows)
    options = view.get('options', [])
    if type(options) is not list:
        raise ValueError('check-in options are a list')
    for option in options:
        if (type(option) is not dict or set(option) - {'id', 'text', 'effect', 'bounds'} or type(option.get('id')) is not str
                or type(option.get('text')) is not str or type(option.get('effect', True)) is not bool):
            raise ValueError('a check-in option is {id, text, effect, bounds?}')
    # An answer names an option by its id on one terminal line, matched without regard to case.
    ids = [option['id'].lower() for option in options]
    if (any(not re.fullmatch(r'[a-z0-9][a-z0-9_.:-]{0,63}', i) for i in ids) or len(set(ids)) != len(ids)
            or 'reject' in ids):
        raise ValueError('check-in options have distinct one-word ids other than reject')
    if type(view.get('summary', '')) is not str:
        raise ValueError('a check-in summary is text')
    required = _strings(view.get('required_sections', []), 'required_sections')
    if kind in ('escalation', 'r3_action') and not options:
        raise ValueError(f'a {kind} check-in offers its options')
    return {'run_id': view['run_id'], 'pins': dict(sorted(pins.items())), 'sections': deepcopy(sections),
            'flags': deepcopy(flags), 'items': {k: deepcopy(v) for k, v in sorted(items.items())},
            'options': deepcopy(options), 'required_sections': required, 'summary': view.get('summary', '')}


def _order(kind, required):
    universal = list(REQUIRED[kind])
    route = [s for s in required if s not in universal]
    return universal[:-1] + route + universal[-1:]


def render(kind, view):
    """The typed check-in artifact for ``kind`` rendered from ``view``."""
    kind = common.kind_of(kind)
    if kind not in REQUIRED:
        raise ValueError(f'{kind} has no typed check-in')
    v = _view(kind, view)
    supplied = {row['id']: row for row in v['sections']}
    decisions = [d for d in common.DECISIONS[kind] if d != 'default']
    generated = {
        'plan': {'id': 'plan', 'title': 'Plan',
                 'lines': [f'Step: {_item_text(s)}' for s in v['items'].get('steps', [])]
                 + [f'Deliverable: {_item_text(d)}' for d in v['items'].get('deliverables', [])]
                 + [f'Boundary: {_item_text(b)}' for b in v['items'].get('boundaries', [])]},
        'flags': {'id': 'flags', 'title': 'Numbered flags, assumptions and open questions',
                  'lines': [f'{n}. [{f["kind"]}] {f["text"]}' for n, f in enumerate(v['flags'], 1)]
                  + [f'Open question: {_item_text(q)}' for q in v['items'].get('questions', [])]
                  + [f'Ambiguity: {_item_text(a)}' for a in v['items'].get('ambiguities', [])]
                  + [f'Assumption: {_item_text(a)}' for a in v['items'].get('assumptions', [])]},
        'options': {'id': 'options', 'title': 'Options',
                    'lines': [f'{o["id"]}: {o["text"]}' + ('' if o.get('effect', True) else ' (no effect)')
                              + (' Bounds: ' + common.canonical(o['bounds']) if 'bounds' in o else '')
                              for o in v['options']]},
        'respond': {'id': 'respond', 'title': 'How to respond',
                    'lines': [f'Decisions: {", ".join(decisions)}.',
                              'Text after the decision is recorded verbatim: answer flags and questions, '
                              'state alterations or conditions. An alteration is never read as approval.']},
    }
    sections = []
    for name in _order(kind, v['required_sections']):
        if name in generated:
            section = deepcopy(generated[name])
            if name == 'plan' and (not v['items'].get('steps') or not v['items'].get('deliverables')):
                section['missing'] = True
            sections.append(section)
        elif name in supplied and not _hollow(supplied[name]):
            sections.append(deepcopy(supplied[name]))
        elif name in supplied:
            # A required section that is empty or holds only a placeholder is missing.
            sections.append({**deepcopy(supplied[name]), 'missing': True})
        else:
            sections.append({'id': name, 'title': name, 'lines': [], 'missing': True})
    order = [s['id'] for s in sections]
    sections += [deepcopy(s) for s in v['sections'] if s['id'] not in order]
    artifact = {'schema': SCHEMA, 'kind': kind, 'run_id': v['run_id'], 'title': TITLES[kind],
                'summary': v['summary'], 'pins': v['pins'], 'sections': sections,
                'flags': [{'n': n, **f} for n, f in enumerate(v['flags'], 1)], 'items': v['items'],
                'options': v['options'], 'decisions': decisions, 'alteration_channel': True,
                'required_sections': _order(kind, v['required_sections'])}
    artifact['sha256'] = common.digest({k: val for k, val in artifact.items() if k != 'sha256'})
    return artifact


def validate(artifact, view):
    """Errors that keep ``artifact`` from being presented for assent (empty when valid)."""
    try:
        kind = common.kind_of(artifact.get('kind') if isinstance(artifact, dict) else None)
        expected = render(kind, view)
    except (ValueError, TypeError, AttributeError) as exc:
        return [f'check-in cannot be rendered from run state: {exc}']
    errors = []
    if artifact.get('schema') != SCHEMA:
        errors.append(f'check-in schema must be {SCHEMA}')
    if artifact.get('run_id') != expected['run_id']:
        errors.append('check-in names a different run')
    for name, value in expected['pins'].items():
        if (artifact.get('pins') or {}).get(name) != value:
            errors.append(f'check-in pin {name} differs from current run state')
    missing = [s['id'] for s in expected['sections'] if s.get('missing')]
    if missing:
        errors.append('check-in lacks required sections: ' + ', '.join(missing))
    shown = [s.get('id') for s in artifact.get('sections') or [] if isinstance(s, dict)]
    if shown[:len(expected['required_sections'])] != expected['required_sections']:
        errors.append('check-in sections are missing or out of order: expected ' + ', '.join(expected['required_sections']))
    shown_flags = [(f.get('kind'), f.get('text')) for f in artifact.get('flags') or [] if isinstance(f, dict)]
    for flag in expected['flags']:
        if (flag['kind'], flag['text']) not in shown_flags:
            errors.append(f'check-in hides flag {flag["n"]}: {flag["text"][:80]}')
    for key, rows in expected['items'].items():
        try:
            present = {common.canonical(row) for row in (artifact.get('items') or {}).get(key, [])}
        except (TypeError, ValueError):
            present = set()
        for row in rows:
            if common.canonical(row) not in present:
                errors.append(f'check-in omits {key[:-1] if key.endswith("s") else key}: {_item_text(row)[:80]}')
    if artifact.get('alteration_channel') is not True or set(artifact.get('decisions') or []) != set(expected['decisions']):
        errors.append('check-in removes the response or alteration channel')
    if not errors:
        try:
            actual = common.digest({k: v for k, v in artifact.items() if k != 'sha256'})
        except (TypeError, ValueError):
            actual = None
        if actual != expected['sha256'] or artifact.get('sha256') != actual:
            errors.append('check-in differs from the rendering of current run state (tampered or stale copy)')
    return errors


def text(artifact):
    """The deterministic terminal rendering of a validated artifact."""
    lines = [f'==== {artifact["title"]} (run {artifact["run_id"]}) ====']
    if artifact.get('summary'):
        lines.append(artifact['summary'])
    for section in artifact['sections']:
        lines.append('')
        lines.append(f'-- {section["title"]} --')
        lines.extend(section['lines'] or ['(none)'])
    lines.append('')
    lines.append('Pins: ' + ', '.join(f'{k}={v[:12]}' for k, v in artifact['pins'].items()))
    return '\n'.join(lines) + '\n'
