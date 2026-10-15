"""Read inference task documents and the files they reference.

A task is ``{"input": "<document>.json"}``. The document may reference other
files by relative path (to the document's directory):

- a vector: a literal list, or ``{"path": ..., "format": "binned-values"}`` (the
  ``values`` of a RAVEL binned_values result, with ``sumw2`` when present), or
  ``{"path": ..., "format": "hepdata", "column": <index or header>}``;
- a matrix: a literal nested list, or ``{"path": ..., "format": "hepdata"}`` for a
  two-axis HEPData covariance or correlation table (``"kind": "correlation"``
  with ``"errors"`` converts it), or ``{"path": ..., "format": "json"}``;
- a coupling morph: ``{"path": ...}`` to a ``coupling-morph`` document.

Every file is read once, must be a regular file without symlinks, and is pinned
by sha256 in the inference record.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

MAX_FILE = 64 * 1024 * 1024


class Context:
    def __init__(self, document_path, base):
        path = Path(document_path)
        path = path if path.is_absolute() else Path(base) / path
        self.root = path.parent
        self.pins, self._cache = {}, {}
        self.document_path = self._regular(path)
        self.document = self.json(self.document_path)

    @staticmethod
    def _regular(path):
        path = Path(path).absolute()
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError(f'input must be a regular file without symlinks: {path}')
        return path

    def path(self, relative):
        if type(relative) is not str or not relative.strip():
            raise ValueError('referenced path must be nonblank text')
        candidate = Path(relative)
        return self._regular(candidate if candidate.is_absolute() else self.root / candidate)

    def raw(self, path):
        path = self._regular(path)
        key = str(path)
        if key not in self._cache:
            raw = path.read_bytes()
            if len(raw) > MAX_FILE:
                raise ValueError(f'{path} exceeds the input size limit')
            self._cache[key] = raw
            self.pins[key] = hashlib.sha256(raw).hexdigest()
        return self._cache[key]

    def json(self, path):
        return strict_json(self.raw(path), str(path))

    def inputs(self):
        return [{'path': p, 'sha256': h} for p, h in sorted(self.pins.items())]

    # ------------------------------------------------------------------ references
    def vector(self, value, label, *, with_sumw2=False):
        if type(value) is list:
            out = np.array([_number(v, label) for v in value])
            return (out, None) if with_sumw2 else out
        if type(value) is not dict or 'path' not in value:
            raise ValueError(label + ' must be a list or a file reference')
        fmt = value.get('format')
        path = self.path(value['path'])
        if fmt == 'binned-values':
            doc = self.json(path)
            if doc.get('kind') != 'binned_values':
                raise ValueError(f'{path} is not a binned_values result')
            bins = doc.get('bins')
            if type(bins) is not list or not bins:
                raise ValueError(f'{path} has no bins')
            values = np.array([_number(b.get('value'), label) for b in bins])
            sumw2 = None
            if all('sumw2' in b for b in bins):
                sumw2 = np.array([_number(b['sumw2'], label + ' sumw2') for b in bins])
            elif all('uncertainty' in b for b in bins):
                sumw2 = np.array([_number(b['uncertainty'], label + ' uncertainty') ** 2 for b in bins])
            return (values, sumw2) if with_sumw2 else values
        if fmt == 'hepdata':
            values = hepdata_column(self._table(path), value.get('column', 0))
            return (values, None) if with_sumw2 else values
        if fmt == 'json':
            doc = self.json(path)
            key = value.get('key')
            data = doc if key is None else doc[key]
            out = np.array([_number(v, label) for v in data])
            return (out, None) if with_sumw2 else out
        raise ValueError(label + ' file format must be binned-values, hepdata or json')

    def matrix(self, value, label):
        if type(value) is list:
            out = np.array([[_number(v, label) for v in row] for row in value])
        elif type(value) is dict and 'path' in value:
            path = self.path(value['path'])
            if value.get('format') == 'hepdata':
                out = hepdata_matrix(self._table(path), value.get('column', 0), bin_edges=value.get('bin_edges'))
            elif value.get('format') == 'json':
                doc = self.json(path)
                data = doc if value.get('key') is None else doc[value['key']]
                out = np.array([[_number(v, label) for v in row] for row in data])
            else:
                raise ValueError(label + ' file format must be hepdata or json')
            if value.get('kind') == 'correlation':
                errors = self.vector(value.get('errors'), label + ' errors')
                if errors.shape != (out.shape[0],):
                    raise ValueError(label + ' errors must match the correlation matrix')
                out = out * np.outer(errors, errors)
            elif value.get('kind', 'covariance') != 'covariance':
                raise ValueError(label + ' kind must be covariance or correlation')
        else:
            raise ValueError(label + ' must be a nested list or a file reference')
        if out.ndim != 2 or out.shape[0] != out.shape[1]:
            raise ValueError(label + ' must be square')
        return out

    def morph(self, value):
        from .morphing import Morph
        if type(value) is not dict or set(value) != {'path'}:
            raise ValueError('a morph reference is {"path": ...}')
        return Morph.from_document(self.json(self.path(value['path'])), require_usable=True)

    def _table(self, path):
        raw = self.raw(path)
        if path.suffix.lower() in ('.yaml', '.yml'):
            import yaml
            docs = [d for d in yaml.safe_load_all(raw.decode('utf-8')) if isinstance(d, dict)]
            tables = [d for d in docs if 'dependent_variables' in d]
            if len(tables) != 1:
                raise ValueError(f'{path} must hold exactly one HEPData table')
            return tables[0]
        return strict_json(raw, str(path))


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' must hold finite numbers')
    return float(value)


def strict_json(raw, label):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(f'{label} repeats key {k!r}')
            out[k] = v
        return out

    def reject(name):
        raise ValueError(f'{label} contains nonfinite {name}')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject)


def _dependent(table, column):
    deps = table.get('dependent_variables')
    if type(deps) is not list or not deps:
        raise ValueError('HEPData table has no dependent variables')
    if type(column) is int:
        if not 0 <= column < len(deps):
            raise ValueError('HEPData column index is outside the table')
        return deps[column]
    matches = [d for d in deps if (d.get('header') or {}).get('name') == column]
    if len(matches) != 1:
        raise ValueError(f'HEPData column {column!r} must match exactly one dependent header')
    return matches[0]


def hepdata_column(table, column=0):
    values = _dependent(table, column).get('values')
    if type(values) is not list or not values:
        raise ValueError('HEPData column has no values')
    return np.array([_number(v.get('value'), 'HEPData value') for v in values])


def hepdata_matrix(table, column=0, *, bin_edges=None):
    """A covariance-style table with two independent variables (bin i, bin j)."""
    ivs = table.get('independent_variables')
    if type(ivs) is not list or len(ivs) != 2:
        raise ValueError('a HEPData matrix table needs two independent variables')
    def key(entry):
        if 'value' in entry:
            return ('value', entry['value'])
        return ('range', entry.get('low'), entry.get('high'))
    rows = [key(v) for v in ivs[0]['values']]
    cols = [key(v) for v in ivs[1]['values']]
    labels = list(dict.fromkeys(rows))
    if bin_edges is not None:
        from ..amplitude_basis import edges_from
        edges = edges_from(bin_edges)
        labels = [('range', float(a), float(b)) for a, b in zip(edges[:-1], edges[1:])]
        if set(rows) != set(labels) or set(cols) != set(labels):
            raise ValueError('HEPData matrix intervals differ from the supplied measurement binning')
    if list(dict.fromkeys(cols)) != labels and set(cols) != set(labels):
        raise ValueError('HEPData matrix axes must list the same bins')
    index = {k: i for i, k in enumerate(labels)}
    values = hepdata_column(table, column)
    n = len(labels)
    if len(values) != n * n or len(rows) != n * n or len(cols) != n * n:
        raise ValueError('HEPData matrix table must list every (i, j) entry exactly once')
    out = np.full((n, n), np.nan)
    for r, c, v in zip(rows, cols, values):
        if not np.isnan(out[index[r], index[c]]):
            raise ValueError('HEPData matrix repeats an entry')
        out[index[r], index[c]] = v
    if not np.isfinite(out).all():
        raise ValueError('HEPData matrix has missing or nonfinite entries')
    return out


def task_document(task):
    if type(task) is not dict or set(task) != {'input'} or type(task['input']) is not str or not task['input'].strip():
        raise ValueError('inference tasks are {"input": "<document>.json"}')
    return task['input']
