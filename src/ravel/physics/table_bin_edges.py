"""Converter from a table to binned values with bin edges (WALKTHROUGH Δ-Wa4, SG-26).

A supplied or published table becomes a ``binned_values`` artifact only when the table
itself states contiguous intervals for its independent variable. Accepted layouts:

- the HEPData submission or web table layouts (read by ``hepdata_table_map``);
- a column table ``{"columns": [...], "rows": [[...], ...]}`` with columns named ``low``
  and ``high`` (or ``<axis> low`` and ``<axis> high``) and the value column chosen by name.

A table of bin centres, or of intervals with gaps or overlaps, has no edges here: the
converter refuses it rather than inventing bin boundaries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from ravel.physics import hepdata_table_map as hepdata

SCHEMA_VERSION = 1
KIND = 'binned_values'


def _sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _number(value):
    return hepdata._number(value)


def _hepdata(table, y):
    record = {'schema_version': 1, 'kind': 'hepdata-record', 'record': None, 'tables': [table]}
    entries = hepdata.build(record)['entries']
    identity = hepdata.table_id(1, 1, y)
    if identity not in entries:
        raise ValueError(f'the table has no dependent variable {y}')
    entry = entries[identity]
    if entry['dimension'] != 1:
        raise ValueError('only a table with one independent variable converts to one-dimensional edges')
    if entry['edges'] is None:
        raise ValueError('the table states no contiguous low/high intervals; bin edges are not inferred from '
                         'centres, gaps or overlaps')
    return {'x': entry['xlabels'][0], 'y': entry['ylabel'], 'edges': entry['edges'], 'values': entry['values'],
            'errors': entry['errors']}


def _column(columns, *names):
    lowered = [str(c).strip().lower() for c in columns]
    for name in names:
        if name in lowered:
            return lowered.index(name)
    for i, column in enumerate(lowered):
        if any(re.fullmatch(rf'.+[\s_]{re.escape(name)}', column) for name in names):
            return i
    return None


def _columns(table, value_column):
    columns, rows = table.get('columns'), table.get('rows')
    if not isinstance(columns, list) or not isinstance(rows, list) or not rows:
        raise ValueError('a column table has a columns list and nonempty rows')
    low, high = _column(columns, 'low', 'lo', 'xlow'), _column(columns, 'high', 'hi', 'xhigh')
    if low is None or high is None:
        raise ValueError('the table names no low and high columns; bin edges are not inferred from centres')
    if value_column is None:
        rest = [i for i in range(len(columns)) if i not in (low, high)]
        if len(rest) != 1:
            raise ValueError('name the value column: the table has more than one non-edge column')
        value = rest[0]
    elif value_column in columns:
        value = columns.index(value_column)
    else:
        raise ValueError(f'the table has no column {value_column!r}')
    bins, values = [], []
    for k, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError(f'row {k + 1} does not match the columns')
        a, b = _number(row[low]), _number(row[high])
        if a is None or b is None or not a < b:
            raise ValueError(f'row {k + 1} has no finite low < high interval')
        bins.append((a, b))
        values.append(_number(row[value]))
    edges = hepdata._edges(bins)
    if edges is None:
        raise ValueError('the intervals are not contiguous and increasing; gaps or overlaps have no single edge list')
    label = str(columns[low]).strip()
    axis = re.sub(r'[\s_]*(low|lo|xlow)$', '', label, flags=re.I) or None
    return {'x': axis, 'y': str(columns[value]), 'edges': edges, 'values': values, 'errors': None}


def convert(table, *, y=1, value_column=None):
    """A table -> ``binned_values`` ``{edges, values, errors, x, y, source_sha256}``; ValueError without edges."""
    if not isinstance(table, dict):
        raise ValueError('a table is a JSON object')
    if 'independent_variables' in table or 'headers' in table:
        result = _hepdata(table, y)
    else:
        result = _columns(table, value_column)
    if any(v is not None and not math.isfinite(v) for v in result['values']):
        raise ValueError('table values must be finite')
    return {'schema_version': SCHEMA_VERSION, 'kind': KIND, 'content': 'edges', 'x': result['x'], 'y': result['y'],
            'edges': result['edges'], 'values': result['values'], 'errors': result['errors'],
            'source_sha256': _sha256(table)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='table_bin_edges', description='Convert a table with stated intervals to bin edges.')
    ap.add_argument('table', type=Path)
    ap.add_argument('--y', type=int, default=1, help='dependent variable (HEPData layouts), 1-based')
    ap.add_argument('--value-column', help='value column name (column tables)')
    args = ap.parse_args(argv)
    try:
        print(json.dumps(convert(json.loads(args.table.read_text()), y=args.y, value_column=args.value_column),
                         indent=1))
    except ValueError as exc:
        print(f'table_bin_edges: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
