"""HEPData table map for Rivet routine construction: identities and binning from the record.

Rivet books a histogram for HEPData table ``d``, independent variable ``x`` and
dependent variable ``y`` as ``dNN-xMM-yKK``, reading its binning from the
reference file. This module builds that map from the supplied record tables,
writes the reference ``<routine>.yoda`` from the same numbers, reads the
bookings a routine source declares and verifies them against the map.

Accepted record documents (one JSON object)::

    {"schema_version": 1, "kind": "hepdata-record", "record": "<URL or identifier or null>",
     "tables": [<table>, ...]}

Tables are in record order (table ``n`` is ``dNN``). A table uses either the
HEPData submission layout (``independent_variables``, ``dependent_variables``)
or the web table layout that ``ravel.workflow.hepdata_fetch`` retains
(``headers`` and ``values`` with ``x`` and ``y`` lists). ``load_fetch_directory``
builds the record document from a ``hepdata_fetch --tables`` output directory.
Nothing here downloads data or invents a binning: a table without numeric bin
edges is mapped with ``edges: null`` and cannot be booked by identifier.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from . import yoda_text

ID = re.compile(r'^d(\d{2,})-x(\d{2,})-y(\d{2,})$')
MAX_TABLES = 1000


def table_id(table, x, y):
    return f'd{table:02d}-x{x:02d}-y{y:02d}'


def _text(value):
    return value if isinstance(value, str) else ('' if value is None else str(value))


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _errors(errors):
    """HEPData errors -> ``{label: (down, up)}``; percentages and unusable entries are skipped."""
    result = {}
    for k, error in enumerate(errors or []):
        if not isinstance(error, dict):
            continue
        label = _text(error.get('label')) or f'err{k}'
        if 'symerror' in error:
            size = _number(error['symerror'])
            if size is not None:
                result[label] = (-abs(size), abs(size))
        elif isinstance(error.get('asymerror'), dict):
            minus, plus = _number(error['asymerror'].get('minus')), _number(error['asymerror'].get('plus'))
            if minus is not None and plus is not None:
                result[label] = (minus, plus)
    return result


def _bins(values):
    """Independent values -> list of (low, high) or None when a value has no interval."""
    bins = []
    for value in values:
        if not isinstance(value, dict):
            return None
        low, high = _number(value.get('low')), _number(value.get('high'))
        if low is None or high is None or not low < high:
            return None
        bins.append((low, high))
    return bins


def _edges(bins):
    """Contiguous increasing bins -> edges; otherwise None (gaps or overlaps cannot be booked)."""
    if not bins:
        return None
    edges = [bins[0][0]]
    for (low, high), previous in zip(bins, [None, *bins[:-1]]):
        if previous is not None and not math.isclose(low, previous[1], rel_tol=1e-9, abs_tol=1e-12):
            return None
        edges.append(high)
    return edges if all(a < b for a, b in zip(edges, edges[1:])) else None


def _submission_table(table):
    independent = table.get('independent_variables')
    dependent = table.get('dependent_variables')
    if not isinstance(independent, list) or not isinstance(dependent, list):
        raise ValueError('submission table needs independent_variables and dependent_variables lists')
    xlabels, xbins = [], []
    for variable in independent:
        header = variable.get('header', {}) if isinstance(variable, dict) else {}
        xlabels.append(_label(header))
        xbins.append(_bins(variable.get('values', [])) if isinstance(variable, dict) else None)
    deps = []
    for variable in dependent:
        if not isinstance(variable, dict):
            raise ValueError('dependent variable must be an object')
        header = variable.get('header', {})
        rows = [(_number(v.get('value')) if isinstance(v, dict) else None,
                 _errors(v.get('errors')) if isinstance(v, dict) else {}) for v in variable.get('values', [])]
        deps.append({'label': _label(header), 'qualifiers': variable.get('qualifiers', []), 'rows': rows})
    return xlabels, xbins, deps


def _web_table(table):
    headers, values = table.get('headers'), table.get('values')
    if not isinstance(headers, list) or not isinstance(values, list) or not values:
        raise ValueError('web table needs headers and nonempty values')
    n_x = len(values[0].get('x', [])) if isinstance(values[0], dict) else 0
    names = [_text(h.get('name')) if isinstance(h, dict) else _text(h) for h in headers]
    xlabels = names[:n_x]
    xbins = []
    for k in range(n_x):
        xbins.append(_bins([row.get('x', [])[k] if isinstance(row, dict) and len(row.get('x', [])) > k else None
                            for row in values]))
    n_y = len(values[0].get('y', [])) if isinstance(values[0], dict) else 0
    deps = []
    for k in range(n_y):
        rows = []
        for row in values:
            entry = row.get('y', [])[k] if isinstance(row, dict) and len(row.get('y', [])) > k else {}
            rows.append((_number(entry.get('value')), _errors(entry.get('errors'))))
        label = names[n_x + k] if len(names) > n_x + k else f'y{k + 1}'
        deps.append({'label': label, 'qualifiers': [], 'rows': rows})
    return xlabels, xbins, deps


def _label(header):
    if not isinstance(header, dict):
        return _text(header)
    name, units = _text(header.get('name')), _text(header.get('units'))
    return f'{name} [{units}]' if units else name


def build(record):
    """Record document -> table map ``{"tables": [...], "entries": {id: entry}}``."""
    if not isinstance(record, dict) or record.get('schema_version') != 1 or record.get('kind') != 'hepdata-record':
        raise ValueError('a HEPData record document has schema_version 1 and kind hepdata-record')
    tables = record.get('tables')
    if not isinstance(tables, list) or not 1 <= len(tables) <= MAX_TABLES:
        raise ValueError('the record needs a nonempty ordered tables list')
    entries = {}
    for index, table in enumerate(tables, 1):
        if not isinstance(table, dict):
            raise ValueError(f'table {index} must be an object')
        if 'independent_variables' in table:
            xlabels, xbins, deps = _submission_table(table)
        else:
            xlabels, xbins, deps = _web_table(table)
        dimension = len(xbins)
        for y, dep in enumerate(deps, 1):
            identity = table_id(index, 1, y)
            bins = xbins[0] if dimension == 1 else None
            edges = _edges(bins) if bins is not None else None
            rows = dep['rows']
            entry = {'id': identity, 'table': index, 'name': _text(table.get('name')),
                     'description': _text(table.get('description')).strip(),
                     'xlabels': xlabels, 'ylabel': dep['label'], 'qualifiers': dep['qualifiers'],
                     'dimension': dimension, 'n_points': len(rows),
                     'edges': edges if edges is not None and len(edges) == len(rows) + 1 else None,
                     'bins': ([[list(b) for b in combo] for combo in zip(*xbins)]
                              if dimension > 1 and all(b is not None for b in xbins) else None),
                     'values': [value for value, _ in rows],
                     'errors': [{k: list(v) for k, v in errs.items()} for _, errs in rows]}
            entries[identity] = entry
    return {'schema_version': 1, 'kind': 'hepdata-table-map', 'record': record.get('record'),
            'record_sha256': hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest(),
            'entries': entries}


def upstream_map(table_map):
    """The map in the Analyst's ``{id: {description, xlabels, ylabel}}`` shape, plus edges."""
    result = {}
    for identity, entry in table_map['entries'].items():
        row = {'description': entry['description'], 'xlabels': entry['xlabels'], 'ylabel': entry['ylabel']}
        if entry['edges'] is not None:
            row['bin_edges'] = entry['edges']
        row['n_bins'] = entry['n_points']
        result[identity] = row
    return result


def reference_yoda(table_map, routine):
    """Reference YODA text with every one-dimensional table that has contiguous edges."""
    if not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,127}', routine or ''):
        raise ValueError('routine identifier required')
    parts = []
    for identity, entry in sorted(table_map['entries'].items()):
        if entry['edges'] is None:
            continue
        labels = []
        for errs in entry['errors']:
            for label in errs:
                if label not in labels:
                    labels.append(label)
        rows = [(value, {k: tuple(v) for k, v in errs.items()}) for value, errs in zip(entry['values'], entry['errors'])]
        parts.append(yoda_text.write_estimate1d(f'/REF/{routine}/{identity}', entry['edges'], rows,
                                                title=entry['ylabel'], error_labels=labels))
    if not parts:
        raise ValueError('no one-dimensional table with contiguous numeric edges to write')
    return ''.join(parts)


def load_fetch_directory(path):
    """Record document from a ``hepdata_fetch --tables`` directory (record-data JSON route)."""
    root = Path(path)
    manifest = json.loads((root / 'manifest.json').read_text())
    rows = manifest.get('table_files')
    if not isinstance(rows, list) or not rows:
        raise ValueError('fetch manifest lists no retained tables')
    tables = []
    for row in rows:
        if not str(row.get('file', '')).endswith('.json'):
            raise ValueError('only the JSON table route is read here; convert submission YAML first')
        tables.append(json.loads((root / row['file']).read_text()))
    return {'schema_version': 1, 'kind': 'hepdata-record', 'record': manifest.get('record_url') or manifest.get('inspire'),
            'tables': tables}


# ---------------------------------------------------------------- bookings

_BOOK = re.compile(r'\bbook\s*\(')


def _split_args(text):
    depth, current, args = 0, '', []
    for char in text:
        if char in '([{':
            depth += 1
        elif char in ')]}':
            if depth == 0:
                args.append(current.strip())
                return args
            depth -= 1
        if char == ',' and depth == 0:
            args.append(current.strip())
            current = ''
        else:
            current += char
    return None


def _strip_comments(source):
    source = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), source, flags=re.S)
    return re.sub(r'//[^\n]*', '', source)


def bookings(source):
    """Static ``book(...)`` calls of a routine: HEPData identifiers or explicit binnings."""
    text = _strip_comments(source)
    result = []
    for match in _BOOK.finditer(text):
        args = _split_args(text[match.end():])
        if not args:
            continue
        line = text.count('\n', 0, match.start()) + 1
        row = {'line': line, 'target': args[0], 'id': None, 'kind': 'unknown', 'name': None}
        rest = args[1:]
        ints = [re.fullmatch(r'\d+', a) for a in rest]
        if len(rest) == 3 and all(ints):
            row.update(kind='hepdata', id=table_id(*(int(a) for a in rest)))
        elif rest and re.fullmatch(r'"[^"]*"', rest[0]):
            name = rest[0][1:-1]
            row['name'] = name
            if ID.match(name) and len(rest) == 1:
                d, x, y = (int(g) for g in ID.match(name).groups())
                row.update(kind='hepdata', id=table_id(d, x, y))
            elif len(rest) == 1:
                row['kind'] = 'reference_name'
            elif len(rest) >= 2:
                row['kind'] = 'explicit'
                if len(rest) == 4 and all(re.fullmatch(r'[-+0-9.eE]+', a) for a in rest[1:]):
                    row['uniform'] = {'n': rest[1], 'low': rest[2], 'high': rest[3]}
        result.append(row)
    return result


def verify_bookings(table_map, booked, histograms=()):
    """Findings for bookings against the map and the Analyst's declared histograms."""
    entries = table_map['entries'] if table_map else {}
    findings = []
    seen = {}
    for row in booked:
        if row['kind'] == 'hepdata':
            if table_map is not None and row['id'] not in entries:
                findings.append({'check': 'booking_unknown_table', 'severity': 'error', 'object': row['id'],
                                 'message': f"line {row['line']}: book(..., {row['id']}) names no table in the HEPData record "
                                            f"(tables: {', '.join(sorted(entries)[:40]) or 'none'})"})
            elif table_map is not None and entries[row['id']]['edges'] is None:
                findings.append({'check': 'booking_without_edges', 'severity': 'error', 'object': row['id'],
                                 'message': f"line {row['line']}: {row['id']} has no contiguous one-dimensional bin edges in the record; "
                                            "book it with explicit edges taken from the record or the paper"})
            if row['id'] in seen:
                findings.append({'check': 'booking_duplicate', 'severity': 'warning', 'object': row['id'],
                                 'message': f"lines {seen[row['id']]} and {row['line']} both book {row['id']}"})
            seen.setdefault(row['id'], row['line'])
    declared = [h for h in histograms if isinstance(h, dict)]
    booked_ids = {row['id'] for row in booked if row['kind'] == 'hepdata'}
    for hist in declared:
        identity = hist.get('hepdata_id')
        if hist.get('binning_source') == 'HEPDATA' and identity:
            if table_map is not None and identity not in entries:
                findings.append({'check': 'declared_unknown_table', 'severity': 'error', 'object': identity,
                                 'message': f"histogram {hist.get('name')!r} declares HEPData table {identity}, absent from the record"})
            elif identity not in booked_ids:
                findings.append({'check': 'declared_not_booked', 'severity': 'warning', 'object': identity,
                                 'message': f"histogram {hist.get('name')!r} declares {identity} but no book() call uses it"})
    return findings


def verify_output_binning(table_map, objects, routine):
    """Findings where a produced object's edges differ from the record's edges."""
    findings = []
    if table_map is None:
        return findings
    for identity, entry in table_map['entries'].items():
        if entry['edges'] is None:
            continue
        for path in (f'/{routine}/{identity}', f'/RAW/{routine}/{identity}'):
            obj = objects.get(path)
            if obj is None or obj.get('edges') is None:
                continue
            edges = obj['edges']
            same = len(edges) == len(entry['edges']) and all(
                math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9) for a, b in zip(edges, entry['edges']))
            if not same:
                findings.append({'check': 'binning_mismatch', 'severity': 'error', 'object': path,
                                 'message': f'{path} has {len(edges) - 1} bins {edges[:6]}...; the record has '
                                            f"{len(entry['edges']) - 1} bins {entry['edges'][:6]}..."})
            break
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel rivet-hepdata-map', description=__doc__.split('\n')[0])
    subs = parser.add_subparsers(dest='action', required=True)
    b = subs.add_parser('build', help='table map from a record document or a hepdata_fetch directory')
    b.add_argument('--record', type=Path, required=True)
    b.add_argument('--out', type=Path, required=True)
    r = subs.add_parser('reference', help='write the reference YODA for a routine')
    r.add_argument('--map', type=Path, required=True)
    r.add_argument('--routine', required=True)
    r.add_argument('--out', type=Path, required=True)
    v = subs.add_parser('verify', help='check a routine source\'s bookings against the map')
    v.add_argument('--map', type=Path, required=True)
    v.add_argument('--source', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == 'build':
        record = (load_fetch_directory(args.record) if args.record.is_dir()
                  else json.loads(args.record.read_text()))
        result = build(record)
        if args.out.exists():
            raise SystemExit('refusing to overwrite ' + str(args.out))
        args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
        print(json.dumps({'map': str(args.out), 'tables': len(result['entries'])}))
    elif args.action == 'reference':
        if args.out.exists():
            raise SystemExit('refusing to overwrite ' + str(args.out))
        args.out.write_text(reference_yoda(json.loads(args.map.read_text()), args.routine))
        print(json.dumps({'reference': str(args.out)}))
    else:
        table_map = json.loads(args.map.read_text())
        found = verify_bookings(table_map, bookings(args.source.read_text()))
        print(json.dumps({'findings': found}, indent=2))
        return 1 if any(f['severity'] == 'error' for f in found) else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
