"""Number tracing for delivered documents (D01, E20).

Reference values are the numbers of the accepted machine artifacts (JSON, CSV, TSV, YAML) the
delivery and its custody ancestors hold, plus the pinned request, reading, contract and plan
parameters. A number displayed in a table of a delivered document (Markdown or LaTeX) must equal
a reference value within its displayed rounding (half a unit of its last digit, or a relative
tolerance the plan declares in ``parameters.rounding.relative``); otherwise the document is
refused for an accepted delivery; a numeric cell may carry a bound or approximation sign. A number
in prose, or in a table cell that also holds words, is matched the same way; an unmatched one is
labelled unverified with its location. Identifiers, dates, versions, digests, paths, list and
section numbering are not numbers of the result. Percent signs compare both the value and its
fraction. Unit conversions are not inferred: a converted value does not trace.
"""
from __future__ import annotations

from bisect import bisect_left
import csv
import io
import json
import math
from pathlib import Path
import re

DOCUMENTS = ('.md', '.markdown', '.txt', '.rst', '.tex', '.html', '.htm')
MACHINE = ('.json', '.csv', '.tsv', '.yaml', '.yml')
FIGURES = ('.png', '.pdf', '.svg', '.jpg', '.jpeg', '.eps', '.gif')

_NUM = r'[-+\u2212]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?'
NUMBER = re.compile(r'(?<![A-Za-z0-9_.\u2212-])(' + _NUM + r')(%?)(?![A-Za-z_0-9])')
CELL = re.compile(r'^\s*(?:[<>\u2264\u2265\u2248~]=?\s*)?[(\[]?\s*' + _NUM
                  + r'\s*%?\s*(?:(?:\u00b1|\+/-|\+-|,|;|\u2013|-|to|/)\s*' + _NUM
                  + r'\s*%?\s*)*[)\]]?\s*(?:[A-Za-z\u00b5\u03bc/^\-0-9.]{1,12})?\s*$')
STRIP = [re.compile(p) for p in (
    r'https?://\S+', r'\S*[\\/]\S*',  # links and paths
    r'\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?)?\b', r'\b\d{1,2}:\d{2}(?::\d{2})?\b',
    r'\b\d+\.\d+\.\d+(?:\.\d+)*\b', r'\b[0-9a-f]{12,}\b', r'(?m)^\s*(?:[-*+]\s+)?\d+[.)]\s',
    r'(?m)^\s*#+\s*[\d.]+\s', r'(?i)\b(?:figure|fig\.|table|tab\.|section|sec\.|eq\.|equation|step|row|item|'
    r'stage|chapter|page|line|column|wave|attempt|check-in|checkin|appendix|note|footnote|panel|version|v)\s*\d+[a-z]?\b',
    r'\b(?:1[89]|20)\d{2}\b', r'\$\$.*?\$\$', r'`[^`]*`', r'\[\d+(?:\s*[,\u2013-]\s*\d+)*\]')]
MARKUP = re.compile(r'[*_`$\\]|\\(?:mathrm|text|textrm|pm)\b')
TABLE_RULE = re.compile(r'^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$')
DISCOVERY = re.compile(r'(?i)\b(discover(?:y|ed|s|ing)?|evidence\s+for\s+(?:a\s+|the\s+)?(?:new\s+)?'
                       r'(?:signal|particle|physics|resonance)|observ(?:ed|ation\s+of)\s+(?:a\s+|an\s+)?(?:new\s+)?'
                       r'(?:signal|particle|resonance|excess)|5\s*(?:\u03c3|sigma)\s+(?:signal|excess|evidence)|'
                       r'significant\s+(?:signal|excess))\b')
NEGATION = re.compile(r'(?i)\b(no|not|without|absence\s+of|nor|neither|cannot|never)\b[^.;]*$')
MAX_REFERENCES = 2_000_000
MAX_LISTED = 200


def parse(text):
    """``(value, decimals, exponent, percent)`` of a displayed number."""
    raw, percent = text
    raw = raw.replace('\u2212', '-').replace(',', '')
    mantissa, _, exponent = raw.lower().partition('e')
    decimals = len(mantissa.split('.', 1)[1]) if '.' in mantissa else 0
    return float(raw), decimals, int(exponent) if exponent else 0, percent == '%'


def tolerance(value, decimals, exponent, relative):
    return max(0.5 * 10.0 ** (exponent - decimals), abs(value) * (relative or 0.0), abs(value) * 1e-12)


class References:
    """A sorted set of reference values with bounded lookups."""

    def __init__(self):
        self.values = []
        self.sources = 0
        self.truncated = False

    def add(self, value):
        if type(value) in (int, float) and type(value) is not bool and math.isfinite(value):
            if len(self.values) < MAX_REFERENCES:
                self.values.append(float(value))
            else:
                self.truncated = True

    def freeze(self):
        self.values = sorted(set(self.values))
        return self

    def near(self, value, tol):
        i = bisect_left(self.values, value - tol)
        return i < len(self.values) and self.values[i] <= value + tol

    def match(self, displayed, relative=None):
        value, decimals, exponent, percent = parse(displayed)
        tol = tolerance(value, decimals, exponent, relative)
        if self.near(value, tol):
            return True
        return percent and self.near(value / 100.0, tol / 100.0)


def _walk_json(value, refs, depth=0):
    if depth > 128:
        return
    if type(value) in (int, float) and type(value) is not bool:
        refs.add(value)
    elif type(value) is str:
        text = value.strip()
        if text and len(text) < 64:
            try:
                refs.add(float(text.replace(',', '')))
            except ValueError:
                pass
    elif type(value) is dict:
        for item in value.values():
            _walk_json(item, refs, depth + 1)
    elif type(value) is list:
        for item in value:
            _walk_json(item, refs, depth + 1)


def add_text_numbers(text, refs):
    for match in NUMBER.finditer(text or ''):
        try:
            refs.add(parse(match.groups())[0])
        except ValueError:
            pass


def add_machine(path, refs, limit):
    """Numbers of one machine artifact; returns False when its format is not read."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if path.stat().st_size > limit:
            return False
        raw = path.read_bytes()
        if suffix == '.json':
            _walk_json(json.loads(raw), refs)
        elif suffix in ('.csv', '.tsv'):
            dialect = 'excel-tab' if suffix == '.tsv' else 'excel'
            for row in csv.reader(io.StringIO(raw.decode('utf-8')), dialect=dialect):
                for cell in row:
                    _walk_json(cell, refs)
        elif suffix in ('.yaml', '.yml'):
            import yaml
            for document in yaml.safe_load_all(raw.decode('utf-8')):
                _walk_json(document, refs)
        else:
            return False
    except Exception:  # an unreadable or malformed machine artifact contributes no reference values
        return False
    return True


def clean(text):
    for pattern in STRIP:
        text = pattern.sub(' ', text)
    return text


def _cells_markdown(line):
    inner = line.strip()
    if inner.startswith('|'):
        inner = inner[1:]
    if inner.endswith('|'):
        inner = inner[:-1]
    return [c.strip() for c in inner.split('|')]


def segments(text, suffix):
    """``[(kind, line number, text)]`` with kind ``table`` (a numeric cell) or ``prose``."""
    out = []
    lines = text.splitlines()
    in_tabular = False
    header_pending = False
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if suffix == '.tex':
            if '\\begin{tabular' in stripped:
                in_tabular, header_pending = True, True
                continue
            if '\\end{tabular' in stripped:
                in_tabular = False
                continue
            if in_tabular:
                body = re.sub(r'\\(?:hline|toprule|midrule|bottomrule)', '', stripped).rstrip('\\').strip()
                if not body:
                    continue
                cells = [c.strip() for c in body.split('&')]
                if header_pending:
                    header_pending = False
                    continue
                out.extend(('table', number, c) for c in cells)
                continue
            if stripped.startswith('%'):
                continue
        elif stripped.startswith('|') and stripped.count('|') >= 2:
            following = lines[number] if number < len(lines) else ''
            if TABLE_RULE.match(stripped):
                continue
            if TABLE_RULE.match(following.strip()):
                continue  # the header row names columns
            out.extend(('table', number, c) for c in _cells_markdown(stripped))
            continue
        if suffix in ('.html', '.htm'):
            stripped = re.sub(r'<[^>]+>', ' ', stripped)
        out.append(('prose', number, stripped))
    return out


def trace(text, suffix, refs, relative=None):
    """Table and prose numbers of a document: ``{tables, prose, untraced_table, unmatched_prose}``."""
    result = {'table_numbers': 0, 'prose_numbers': 0, 'untraced_table': [], 'unmatched_prose': [],
              'discovery_language': []}
    for kind, line, chunk in segments(text, suffix):
        if kind == 'table':
            cell = MARKUP.sub(' ', chunk)
            if CELL.match(cell):
                for match in NUMBER.finditer(cell):
                    result['table_numbers'] += 1
                    if not refs.match(match.groups(), relative):
                        result['untraced_table'].append({'line': line, 'text': ''.join(match.groups()),
                                                         'cell': chunk[:120]})
                continue
            # A cell with words is checked like prose: a number in it that matches nothing is labelled.
        for found in DISCOVERY.finditer(chunk):
            if not NEGATION.search(chunk[max(0, found.start() - 60):found.start()]):
                result['discovery_language'].append({'line': line, 'text': found.group(0)})
        for match in NUMBER.finditer(clean(MARKUP.sub(' ', chunk))):
            result['prose_numbers'] += 1
            if not refs.match(match.groups(), relative):
                result['unmatched_prose'].append({'line': line, 'text': ''.join(match.groups())})
    for key in ('untraced_table', 'unmatched_prose', 'discovery_language'):
        result[key + '_count'] = len(result[key])
        result[key] = result[key][:MAX_LISTED]
    return result
