"""Request/harness source restrictions and declared, reviewed output census.

Rows match input-root globs, source identity or class, and scoped quantities.
This module matches supplied policy; it never manufactures a restriction from a
source identity. No source patterns are embedded here. Paths are relative to a run input root;
callers must pass root-relative paths (including resolved aliases) before reading.
The broker consumes read_receipt; this module never opens candidate source bytes.
"""
from copy import deepcopy
from fnmatch import fnmatchcase
from functools import lru_cache
import hashlib
import json
from pathlib import Path

KINDS = ('forbidden-source', 'no-value-extraction', 'blinded', 'blinded-data')


def _relative(value):
    if (type(value) is not str or not value or '\\' in value or value.startswith('/')
            or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('source policy requires a portable input-root-relative path')
    return value


def _rows(rows):
    if type(rows) is not list or len(rows) > 256:
        raise ValueError('finite source restriction census required')
    result = deepcopy(rows)
    for row in result:
        if (type(row) is not dict or row.get('kind') not in KINDS
                or type(row.get('statement')) is not str or not row['statement'].strip()
                or type(row.get('evidence')) is not list):
            raise ValueError('named source restriction with evidence required')
        if set(row) - {'id', 'kind', 'classes', 'identifiers', 'paths', 'scope', 'origin', 'statement', 'evidence'}:
            raise ValueError('unknown source restriction field')
        for key in ('classes', 'paths'):
            if type(row.get(key, [])) is not list or any(type(v) is not str or not v for v in row.get(key, [])):
                raise ValueError('source restriction requires string lists')
        identifiers = row.get('identifiers', {})
        if (type(identifiers) is not dict or set(identifiers) - {'inspire', 'arxiv', 'hepdata', 'analysis'}
                or any(type(v) is not list or any(type(s) is not str or not s for s in v)
                       for v in identifiers.values())):
            raise ValueError('source restriction identifier lists required')
        origin = row.get('origin', 'request')
        if row.get('paths') and 'origin' not in row:
            raise ValueError('path restriction requires an explicit origin')
        if origin not in ('request', 'harness'):
            raise ValueError('source restriction origin must be request or harness')
        if row.get('paths') and origin == 'request' and not row['evidence']:
            raise ValueError('request path restriction requires evidence spans')
        for span in row['evidence']:
            if (type(span) is not dict or type(span.get('start')) is not int or type(span.get('end')) is not int
                    or not 0 <= span['start'] < span['end'] or type(span.get('text')) is not str or not span['text']):
                raise ValueError('source restriction requires located evidence spans')
        for pattern in row.get('paths', []):
            _relative(pattern)
        if 'scope' in row:
            scope = row['scope']
            if (row['kind'] != 'no-value-extraction' or type(scope) is not dict or set(scope) != {'quantities'}
                    or type(scope['quantities']) is not list or not scope['quantities']
                    or any(type(v) is not str or not v for v in scope['quantities'])):
                raise ValueError('quantity scope belongs to no-value-extraction rows')
    return result


def canonical(rows):
    """Validate and copy rows in the interface's (kind, statement) order."""
    return sorted(_rows(rows), key=lambda r: (r['kind'], r['statement'],
                  json.dumps(r, sort_keys=True, allow_nan=False)))


def from_reading(reading):
    """Return the reading's restriction rows in canonical (kind, statement) order.

    A reading may carry explicit ``source_restrictions`` rows; otherwise its
    source-restriction and blinding constraints supply them.
    """
    if type(reading) is not dict or type(reading.get('constraints', [])) is not list:
        raise ValueError('source restrictions require a reading with a constraint census')
    if 'source_restrictions' in reading:
        return canonical(reading['source_restrictions'])
    rows = []
    for constraint in reading.get('constraints', []):
        if type(constraint) is not dict:
            raise ValueError('reading constraint must be an object')
        if constraint.get('type') not in ('source_restriction', 'blinding'):
            continue
        row = deepcopy(constraint['value'])
        if type(row) is not dict:
            raise ValueError('reading source restriction must be an object')
        if row.get('kind') not in KINDS:
            continue
        row['evidence'] = deepcopy(constraint.get('evidence', []))
        rows.append(row)
    return canonical(rows)


def digest(rows):
    """Hash every policy key, including v2 paths, quantities and provenance."""
    return hashlib.sha256(json.dumps(_rows(rows), sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _glob(pattern, path):
    """Segment glob: * cannot cross /; ** can consume zero or more segments."""
    parts, names = pattern.split('/'), path.split('/')
    @lru_cache(None)
    def match(i, j):
        if i == len(parts): return j == len(names)
        if parts[i] == '**': return match(i + 1, j) or (j < len(names) and match(i, j + 1))
        return j < len(names) and fnmatchcase(names[j], parts[i]) and match(i + 1, j + 1)
    return match(0, 0)


def _values(value):
    if value is None: return set()
    return {value} if isinstance(value, str) else set(value)


def matches(rows, source):
    """Return every row violated by path OR source identity/class and quantity.

    Paths are independent selectors. Identifiers (top level or under
    ``identifiers``) locate a row; a located row restricts that source, not every
    source of the same class. Scoped extraction bans also require the named
    quantity, permitting definitions from that source. A row without identifiers
    or classes fails closed: a selector-free row restricts the whole source, a
    blinding row restricts every source, and a blinded-data row restricts every
    source not declared free of observed data.
    """
    if type(source) is not dict: raise ValueError('source descriptor required')
    path = source.get('path')
    if path is not None: path = _relative(path)
    source_ids = source.get('identifiers', {})
    if type(source_ids) is not dict: raise ValueError('source identifiers must be an object')
    found = []
    for row in _rows(rows):
        path_hit = path is not None and any(_glob(p, path) for p in row.get('paths', []))
        identities = row.get('identifiers', {})
        identity_hit = any(set(v) & (_values(source.get(k)) | _values(source_ids.get(k)))
                           for k, v in identities.items())
        classes = source.get('classes', [])
        if type(classes) is not list: raise ValueError('source classes must be a list')
        if source.get('class') is not None: classes = [*classes, source['class']]
        class_hit = bool(set(row.get('classes', [])) & set(classes))
        located = any(identities.values())
        if located: source_hit = identity_hit
        elif row.get('classes'): source_hit = class_hit
        elif row['kind'] == 'blinded-data': source_hit = source.get('contains_observed_data') is not False
        elif row['kind'] == 'blinded': source_hit = True
        else: source_hit = not row.get('paths')
        if row.get('scope'):
            quantities = source.get('quantities', [])
            if type(quantities) is not list: raise ValueError('source quantities must be a list')
            source_hit = source_hit and bool(set(row['scope']['quantities']) & set(quantities))
        if path_hit or source_hit: found.append(row)
    return found


def read_receipt(rows, source):
    """Broker admission receipt; caller reads only after allowed is true."""
    violated = matches(rows, source)
    return {'schema_version': 1, 'allowed': not violated,
            'refusal_code': 'forbidden_source' if violated else None,
            'source': deepcopy(source), 'rules': violated,
            'source_restriction_sha256': digest(rows)}


def require_read(rows, source):
    receipt = read_receipt(rows, source)
    if not receipt['allowed']:
        raise ValueError('forbidden_source: ' + json.dumps(receipt, sort_keys=True))
    return receipt


def inventory(rows, sources):
    """Filter supplied inputs/bundle descriptors, retaining every refusal receipt."""
    if type(sources) is not list: raise ValueError('source inventory must be a list')
    receipts = [read_receipt(rows, source) for source in sources]
    return {'sources': [r['source'] for r in receipts if r['allowed']],
            'refused': [r for r in receipts if not r['allowed']]}


def accepted(rundir, *, declared_outputs, claim_scope, base_dir=None):
    """Return declared output pins from a current accepted review, list extras.

    Declarations are exact run-relative files, never wildcards. Missing declarations
    fail; reviewed extras remain visible but acquire no delivery authority here.
    This consumes source custody without changing its completion decision.
    """
    from . import task_completion as tc
    root = Path(rundir).absolute()
    if (type(declared_outputs) is not list or any(type(p) is not str for p in declared_outputs)
            or len(declared_outputs) != len(set(declared_outputs))):
        raise ValueError('distinct declared outputs required')
    declared = {str(root / _relative(p)) for p in declared_outputs}
    if any(not Path(p).is_relative_to(root / 'outputs') for p in declared):
        raise ValueError('declared outputs must be under the run outputs directory')
    observed = tc._Inputs(Path(base_dir or root).absolute())
    try:
        rd, cycle = tc._accepted_review(str(root), claim_scope, observed)
        outputs, extras = [], []
        folder = rd / 'outputs'
        population = tuple(sorted(folder.rglob('*')))
        observed.populations[(str(folder), '*')] = population
        reviewed = set()
        for snapshot in cycle['snapshots']:
            path = Path(snapshot['path'])
            if not path.is_absolute(): path = rd / path
            if not path.is_relative_to(rd / 'outputs'): continue
            reviewed.add(str(path))
            pin = observed.capture(path)
            if not tc._in_cycle(pin, rd, cycle): raise ValueError('reviewed output changed')
            (outputs if str(path) in declared else extras).append(
                pin if str(path) in declared else {**pin, 'reviewed': True})
        extras.extend({'path': str(path), 'reviewed': False} for path in population
                      if (path.is_file() or path.is_symlink()) and str(path) not in reviewed)
        if declared != {p['path'] for p in outputs}:
            raise ValueError('declared output missing from current accepted review')
        observed.finish()
        return {'outputs': sorted(outputs, key=lambda p: p['path']),
                'undeclared_outputs': sorted(extras, key=lambda p: p['path']), 'claim_scope': claim_scope}
    finally:
        observed.close()
