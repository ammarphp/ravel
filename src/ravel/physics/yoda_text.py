"""Read and write the plain-text YODA objects a routine check needs.

Reads one-dimensional histograms (``Histo1D``), estimates (``Estimate1D``),
counters and zero-dimensional estimates from YODA 2 text files, as Rivet 4
writes them. Writes reference ``Estimate1D`` objects from numeric tables. Other
object types are listed with their type and path but not decoded.
"""
from __future__ import annotations

import math
import re

_BEGIN = re.compile(r'^BEGIN YODA_(\S+) (\S+)\s*$')
_NUMBER = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[-+]?(?:nan|inf)'


def _float(token):
    if token == '---':
        return None
    value = float(token)
    return value


def _edges(line):
    body = line.split(':', 1)[1].strip()
    if not (body.startswith('[') and body.endswith(']')):
        raise ValueError('YODA edges need a bracketed list')
    inner = body[1:-1].strip()
    if not inner:
        return []
    if '"' in inner:
        return [part.strip().strip('"') for part in inner.split(',')]
    return [float(part) for part in inner.split(',')]


def parse(text):
    """Return ``{path: object}`` for every YODA object in the text.

    Each object has ``type``, ``path`` and ``annotations``; decoded types add
    ``edges`` and ``rows`` (one row per bin including underflow and overflow).
    """
    if not isinstance(text, str):
        raise ValueError('YODA text required')
    objects = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = _BEGIN.match(lines[i])
        if not match:
            i += 1
            continue
        kind, path = match.group(1), match.group(2)
        end = 'END YODA_' + kind
        body = []
        i += 1
        while i < len(lines) and lines[i].strip() != end:
            body.append(lines[i])
            i += 1
        if i >= len(lines):
            raise ValueError(f'unterminated YODA object {path}')
        i += 1
        if path in objects:
            raise ValueError(f'duplicate YODA object {path}')
        objects[path] = _object(kind, path, body)
    return objects


def _object(kind, path, body):
    annotations, data = {}, []
    in_data = False
    for line in body:
        if not in_data:
            if line.strip() == '---':
                in_data = True
                continue
            if ':' in line:
                key, value = line.split(':', 1)
                annotations[key.strip()] = value.strip()
            continue
        data.append(line)
    base = kind.split('_V')[0]
    result = {'kind': kind, 'type': annotations.get('Type', base), 'path': path, 'annotations': annotations}
    edges, rows = None, []
    for line in data:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('Edges(A1)'):
            edges = _edges(stripped)
            continue
        if stripped.startswith('#') or ':' in stripped.split()[0]:
            continue
        tokens = stripped.split()
        if not all(t == '---' or re.fullmatch(_NUMBER, t, re.I) for t in tokens):
            continue
        rows.append([_float(t) for t in tokens])
    if base in ('HISTO1D', 'ESTIMATE1D'):
        if edges is None or any(type(e) is not float for e in edges) or len(edges) < 2:
            raise ValueError(f'numeric edges required for {path}')
        if len(rows) != len(edges) + 1:
            raise ValueError(f'{path}: {len(rows)} rows for {len(edges) - 1} bins plus two flow bins')
    result['edges'] = edges
    result['rows'] = rows
    return result


def _in_range(obj):
    return obj['rows'][1:-1]


def widths(obj):
    edges = obj['edges']
    return [edges[k + 1] - edges[k] for k in range(len(edges) - 1)]


def values(obj):
    """In-range bin values: sumW for a Histo1D, value for an Estimate1D."""
    return [row[0] for row in _in_range(obj)]


def entries(obj):
    """Fill count of a Histo1D over all bins including flows, or None."""
    if not obj['kind'].startswith('HISTO1D'):
        return None
    return sum((row[-1] or 0.0) for row in obj['rows'])


def area(obj):
    """In-range integral: sumW for a Histo1D, value times width for an Estimate1D."""
    vals = values(obj)
    if obj['kind'].startswith('HISTO1D'):
        return sum(v or 0.0 for v in vals)
    return sum((v or 0.0) * w for v, w in zip(vals, widths(obj)))


def scalar(obj):
    """Value of a counter (sumW) or zero-dimensional estimate."""
    if not obj['rows']:
        raise ValueError(f'no value in {obj["path"]}')
    return obj['rows'][0][0]


def finite(obj):
    return all(v is not None and math.isfinite(v) for v in values(obj))


def _fmt(value):
    return f'{value:.6e}'


def write_estimate1d(path, edges, rows, *, title='', error_labels=()):
    """One reference ``Estimate1D``: ``rows`` are ``(value, {label: (down, up)})`` per bin."""
    if len(edges) < 2 or any(not math.isfinite(e) for e in edges) or list(edges) != sorted(edges) or len(set(edges)) != len(edges):
        raise ValueError(f'{path}: increasing finite edges required')
    if len(rows) != len(edges) - 1:
        raise ValueError(f'{path}: one value per bin required')
    labels = list(error_labels)
    lines = [f'BEGIN YODA_ESTIMATE1D_V3 {path}', f'Path: {path}', f'Title: {title}', 'Type: Estimate1D', '---',
             'Edges(A1): [' + ', '.join(_fmt(e) for e in edges) + ']']
    if labels:
        lines.append('ErrorLabels: [' + ', '.join('"' + l + '"' for l in labels) + ']')
    header = '# value      \t' + ''.join(f'errDn({k + 1})     \terrUp({k + 1})     \t' for k in range(len(labels)))
    lines.append(header)
    empty = 'nan          \t' + '---          \t---          \t' * len(labels)
    lines.append(empty)
    for value, errors in rows:
        cells = [_fmt(value) if value is not None and math.isfinite(value) else 'nan']
        for label in labels:
            pair = errors.get(label)
            cells += ['---', '---'] if pair is None else [_fmt(pair[0]), _fmt(pair[1])]
        lines.append(' \t'.join(cells) + ' \t')
    lines.append(empty)
    lines.append('END YODA_ESTIMATE1D_V3')
    return '\n'.join(lines) + '\n\n'
