"""Assemble measurement_bundle.v1 from literal tables and declared error laws.

API: assemble(document, component_map, *, routine=None, record=None) and
load_bundle(path).
The map selects one distribution/column, declares each named error's kind and
correlation, supplies record/version, observable level, normalization and a
stated total-error label. Matrix tables are consumed explicitly, never replaced
by marginal errors. Normalized tables need normalization_weights (bin widths
for densities, ones for integrated bins); no covariance projection or repair.
Components store error magnitudes: full, equicorrelation and block rules assume
one shift direction, so opposite signed shifts there need a signed matrix.

Lifecycle: validate/inputs/run consume byte-pinned JSON documents for input,
component_map and, when supplied, routine. No acquisition or native invocation.
Registration consumers must route this adapter through the existing lifecycle.
"""
from __future__ import annotations

import copy
import hashlib
import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import numpy as np

from ravel.physics import hepdata_table_map, source_tables

MAX_BINS = 256
LEVELS = {'born', 'dressed', 'bare', 'parton', 'detector'}
KINDS = {'stat', 'syst', 'lumi', 'mcstat', 'model'}
DIMENSIONLESS = ('', '1', 'dimensionless')
COMMON_SIGN = ('full', 'declared:equicorrelation', 'declared:blocks')


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f'nonfinite JSON constant: {value}')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _numeric(value):
    if isinstance(value, dict):
        result = float(source_tables.number(value))
    else:
        if isinstance(value, bool):
            raise ValueError('finite numeric scalar required')
        try:
            result = float(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError('finite numeric scalar required') from exc
    if not np.isfinite(result):
        raise ValueError('finite numeric scalar required')
    return result


def _decoded(value):
    if isinstance(value, dict):
        if set(value) == {'literal', 'decimal'}:
            return _numeric(value)
        return {k: _decoded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decoded(v) for v in value]
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'nonempty {label} required')
    return value


def _table(table):
    """Web -> submission shape, retaining the complete original error payload."""
    if 'independent_variables' in table:
        return _decoded(table)
    rows, headers = table.get('values'), table.get('headers')
    if not isinstance(rows, list) or not rows or not isinstance(headers, list):
        raise ValueError('complete supplied web table required')
    nx, ny = len(rows[0].get('x', [])), len(rows[0].get('y', []))
    if nx < 1 or ny < 1 or len(headers) != nx+ny:
        raise ValueError('complete web headers and columns required')
    if any(len(row.get('x', [])) != nx or len(row.get('y', [])) != ny for row in rows):
        raise ValueError('complete web row census required')
    def header(h):
        return h if isinstance(h, dict) else {'name': h}
    return {'name': table.get('name'), 'matrix_kind': table.get('matrix_kind'),
            'independent_variables': [{'header': header(headers[i]), 'values': [r['x'][i] for r in rows]} for i in range(nx)],
            'dependent_variables': [{'header': header(headers[nx+i]), 'values': [r['y'][i] for r in rows]} for i in range(ny)]}


def _select(document, mapping):
    identity, column = mapping['distribution'], mapping['column']
    if type(column) is not int or column < 0:
        raise ValueError('nonnegative declared column index required')
    if document.get('kind') == 'source-primary-table-basis-join':
        matches = [d for d in document['distributions'] if d['id'] == identity]
        if len(matches) != 1:
            raise ValueError('unique selected distribution required')
        d = matches[0]
        table = {'name': identity, 'independent_variables': d['axes'], 'dependent_variables': d['selected_columns']}
        matrices = copy.deepcopy(document['matrix_components'])
        return _decoded(table), d['bin_ids'], matrices, None, d.get('source')
    if document.get('kind') != 'hepdata-record' or document.get('schema_version') != 1:
        raise ValueError('literal source-tables join or supplied hepdata-record required')
    if document.get('record') != mapping['source']['hepdata'] or document.get('version') != mapping['source']['version']:
        raise ValueError('supplied record identity/version differs from component map')
    tables = document['tables']
    matches = [t for t in tables if t.get('name') == identity]
    if len(matches) != 1:
        raise ValueError('unique selected record table required')
    matrices = []
    for item in tables:
        t = _table(item)
        axes, columns = t['independent_variables'], t['dependent_variables']
        if len(axes) == 2:
            kind = item.get('matrix_kind')
            if kind is None and len(columns) == 1:
                kind = columns[0]['header'].get('name', '').lower()
            if kind not in ('covariance', 'correlation'):
                raise ValueError('explicit covariance/correlation table semantics required')
            matrices.append({'id': item['name'], 'kind': kind, 'table': t})
    table = _table(matches[0])
    count = len(table['dependent_variables'][column]['values']) if column < len(table['dependent_variables']) else 0
    return table, [f'bin{i}' for i in range(count)], matrices, document, None


def _matrix(item, ids, unit):
    n = len(ids)
    if 'literal_matrix' in item:
        basis = item['bin_ids']
        if len(set(basis)) != len(basis) or not set(ids) <= set(basis):
            raise ValueError(f'matrix bin basis mismatch: {ids}')
        order = [basis.index(i) for i in ids]
        original = np.array([[_numeric(v) for v in row] for row in item['literal_matrix']])
        if original.shape != (len(basis), len(basis)):
            raise ValueError(f'matrix cell census mismatch: bins {ids}')
        result = original[np.ix_(order, order)]
        matrix_unit = item['header'].get('units', '')
    else:
        table = item['table']
        axes, columns = table['independent_variables'], table['dependent_variables']
        if len(columns) != 1 or any(len(a['values']) != n*n for a in axes) or len(columns[0]['values']) != n*n:
            raise ValueError(f'matrix cell census mismatch: bins {ids}')
        labels = []
        for axis in axes:
            seq = [v.get('value') for v in axis['values']]
            if any(v is None or isinstance(v, (dict, list, bool)) for v in seq):
                raise ValueError(f'matrix coordinate bins required: {ids}')
            labels.append(list(dict.fromkeys(str(v) for v in seq)))
        if set(labels[0]) != set(labels[1]) or len(labels[0]) != n:
            raise ValueError(f'explicit matrix coordinate order differs: bins {ids}')
        # A caller must declare the label -> bin link, not assume table row order.
        declared = item.get('matrix_labels')
        if declared is None or len(declared) != n or len(set(declared)) != n or set(declared) != set(labels[0]):
            raise ValueError(f'declared matrix labels in bin order required: bins {ids}')
        lookup = {v: i for i, v in enumerate(declared)}
        result = np.empty((n, n)); seen = set()
        for a, b, cell in zip(axes[0]['values'], axes[1]['values'], columns[0]['values']):
            ij = lookup[str(a['value'])], lookup[str(b['value'])]
            if ij in seen or set(cell) != {'value'}:
                raise ValueError(f'duplicate or malformed matrix cell: bins {ids}')
            seen.add(ij); result[ij] = _numeric(cell['value'])
        matrix_unit = columns[0]['header'].get('units', '')
    if item['kind'] == 'correlation':
        if matrix_unit in ('%', 'percent'):
            result = result/100
        elif matrix_unit not in DIMENSIONLESS:
            raise ValueError(f'correlation unit mismatch: bins {ids}')
        invalid = np.argwhere(np.abs(result) > 1)
        if len(invalid):
            i, j = invalid[0]
            raise ValueError(f'correlation outside [-1,1]: bins {ids[i]}, {ids[j]}')
        if not np.array_equal(np.diag(result), np.ones(n)):
            raise ValueError(f'correlation diagonal must equal one: bins {ids}')
    elif matrix_unit not in (DIMENSIONLESS if unit in DIMENSIONLESS else (f'({unit})^2', f'{unit}^2')):
        raise ValueError(f'covariance squared unit mismatch: bins {ids}')
    return _checked_matrix(result, ids, item['id'])


def _checked_matrix(value, ids, label):
    matrix = np.asarray(value, dtype=float)
    if matrix.shape != (len(ids), len(ids)) or not np.isfinite(matrix).all():
        raise ValueError(f'{label} finite square matrix required: bins {ids}')
    if not np.array_equal(matrix, matrix.T):
        indices = np.argwhere(matrix != matrix.T)[0]
        raise ValueError(f'{label} asymmetric: bins {ids[indices[0]]}, {ids[indices[1]]}')
    scale = max(float(np.max(np.abs(matrix))), 1e-300)
    eigen, vectors = np.linalg.eigh(matrix)
    if eigen[0] < -1e-12*scale:
        offending = [ids[i] for i in np.flatnonzero(np.abs(vectors[:, 0]) > 1e-8)]
        raise ValueError(f'{label} non-PSD: offending bins {offending}')
    return matrix


def _errors(rows, label, central, header, rule):
    if rule not in ('none', 'average', 'max'):
        raise ValueError('declared symmetrization rule must be none, average or max')
    pairs, magnitudes, directions = [], [], []
    def shift(raw, value, error):
        percent = isinstance(raw, str) and raw.strip().endswith('%')
        unit = error.get('units', header.get('error_units'))
        if unit not in (None, '%', 'percent', 'absolute', header.get('units')) or (percent and unit not in (None, '%', 'percent')):
            raise ValueError('error units conflict with table header')
        number = _numeric(raw.strip()[:-1] if percent else raw)
        return number * (value/100 if percent or unit in ('%', 'percent') else 1)
    for row, value in zip(rows, central):
        matches = [e for e in row.get('errors', []) if e.get('label') == label]
        if len(matches) != 1:
            raise ValueError(f'unique named error {label} required in each bin')
        error = matches[0]
        if ('symerror' in error) == ('asymerror' in error):
            raise ValueError('exactly one symmetric/asymmetric error payload required')
        if 'asymerror' in error:
            if rule == 'none':
                raise ValueError(f'asymmetric error {label} requires declared symmetrization')
            asym = error['asymerror']
            if set(asym) != {'minus', 'plus'}:
                raise ValueError('complete asymmetric errors required')
            down, up = (shift(asym[k], value, error) for k in ('minus', 'plus'))
            # Only an unambiguous pair orients the shift; a one-sided pair claims no direction.
            direction = 1 if down <= 0 <= up and down != up else -1 if up <= 0 <= down and down != up else 0
        else:
            down = up = shift(error['symerror'], value, error)
            direction = int(np.sign(up))
        minus, plus = abs(down), abs(up)
        pairs.append([minus, plus]); directions.append(direction)
        magnitudes.append((minus+plus)/2 if rule == 'average' else max(minus, plus))
    return pairs, np.array(magnitudes), directions


def _common_sign(directions, groups, ids, name):
    """Magnitudes with a positive declared correlation cannot represent opposite shifts."""
    for group in dict.fromkeys(groups):
        chosen = [i for i, g in enumerate(groups) if g == group]
        if {directions[i] for i in chosen} >= {-1, 1}:
            offending = [ids[i] for i in chosen if directions[i] == -1]
            raise ValueError(f'opposite signed shifts in {name} need a signed correlation matrix: bins {offending}')


def _normalization(values, bins, covariance, normalization, weights):
    ids = [str(i) for i in range(len(values))]
    rank = int(np.linalg.matrix_rank(covariance, tol=max(np.max(np.abs(covariance)), 1e-300)*1e-12))
    if normalization != 'normalized':
        return rank, 'absolute-covariance' if normalization == 'absolute' else 'ratio-covariance'
    if not isinstance(weights, list) or len(weights) != len(values):
        raise ValueError('normalized tables require explicit bin integration weights')
    w = np.array([_numeric(v) for v in weights])
    if np.any(w <= 0) or abs(float(w @ values)-1) > 1e-12:
        raise ValueError('normalized central bin-sum constraint failed')
    if rank != len(values)-1:
        raise ValueError(f'normalized rank must equal n-1: bins {ids}')
    scale = max(float(np.max(np.abs(covariance))), 1e-300)
    if np.max(np.abs(covariance @ w)) > 1e-12*scale*max(float(np.max(w)), 1):
        raise ValueError(f'normalized covariance bin-sum constraint failed: bins {ids}')
    return rank, 'normalized-rank-n-minus-one'


def _routine_check(routine, record, source, selected, column, bins):
    if record is None:
        raise ValueError('TS6: routine verification needs complete supplied record tables')
    if record.get('record') != source['hepdata'] or record.get('version') != source['version']:
        raise ValueError('TS6: supplied REF record identity/version mismatch')
    if routine.get('record') != source['hepdata'] or routine.get('record_version') != source['version']:
        raise ValueError('TS6: routine REF record identity/version mismatch')
    mapping = hepdata_table_map.build(_decoded(record))
    booked = hepdata_table_map.bookings(routine.get('source_text', ''))
    findings = hepdata_table_map.verify_bookings(mapping, booked)
    if not booked or any(b['kind'] != 'hepdata' for b in booked) or findings:
        raise ValueError(f'TS6: routine bookings mismatch or unverifiable: {findings}')
    edges = routine.get('histogram_edges', {})
    booked_ids = [b['id'] for b in booked]
    if set(edges) != set(booked_ids):
        raise ValueError('TS6: complete booked histogram bin edges required')
    for identity in booked_ids:
        expected = mapping['entries'][identity]['edges']
        if expected is None or list(map(_numeric, edges[identity])) != expected:
            raise ValueError(f'TS6: routine bins mismatch for {identity}')
    objects = {f"/{routine['id']}/{k}": {'edges': v} for k, v in edges.items()}
    if hepdata_table_map.verify_output_binning(mapping, objects, routine['id']):
        raise ValueError('TS6: output binning mismatch')
    selected_indices = [i for i, t in enumerate(record['tables'], 1) if t.get('name') == selected]
    if len(selected_indices) != 1:
        raise ValueError('TS6: selected REF table identity missing or repeated')
    selected_index = selected_indices[0]
    identity = hepdata_table_map.table_id(selected_index, 1, column+1)
    if identity not in booked_ids or mapping['entries'][identity]['edges'] != [bins[0]['lo'], *[b['hi'] for b in bins]]:
        raise ValueError('TS6: selected intake bins/column not booked from matching record')
    result = {k: copy.deepcopy(routine[k]) for k in ('id', 'version', 'options', 'record_version', 'ref_yoda_sha256')}
    result['source_sha256'] = hashlib.sha256(routine['source_text'].encode()).hexdigest()
    result['table_map_sha256'] = mapping['record_sha256']
    return result, {k: mapping['entries'][k]['name'] for k in booked_ids}


def assemble(document, component_map, *, routine=None, record=None):
    """Validate supplied semantics, assemble covariance and return a schema-valid bundle."""
    m = copy.deepcopy(component_map)
    observable = m.get('observable', {})
    if observable.get('level') not in LEVELS:
        raise ValueError('declared observable level required (TS2)')
    if m.get('normalization') not in ('absolute', 'normalized', 'ratio'):
        raise ValueError('declared normalization required')
    source = m['source']
    if type(source.get('version')) is not int or source['version'] < 1:
        raise ValueError('positive record version required')
    _text(source.get('hepdata'), 'supplied record identifier')
    table, ids, matrix_items, full_record, pin = _select(document, m)
    if not 1 <= len(ids) <= MAX_BINS or len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i for i in ids):
        raise ValueError('bounded unique measurement bin identities required')
    axes, columns = table['independent_variables'], table['dependent_variables']
    if len(axes) != 1 or m['column'] >= len(columns):
        raise ValueError('one-dimensional selected column required')
    col = columns[m['column']]; rows = col['values']; unit = col['header'].get('units', '')
    if unit != observable.get('unit') or len(rows) != len(ids) or len(axes[0]['values']) != len(ids):
        raise ValueError('observable unit or complete bin census mismatch')
    bins = [{'lo': _numeric(v['low']), 'hi': _numeric(v['high'])} for v in axes[0]['values']]
    if any(b['lo'] >= b['hi'] for b in bins) or any(a['hi'] > b['lo'] for a, b in zip(bins, bins[1:])):
        raise ValueError('ordered nonoverlapping bin intervals required')
    central = np.array([_numeric(row['value']) for row in rows])
    matrices = {item['id']: item for item in matrix_items}
    if len(matrices) != len(matrix_items):
        raise ValueError('unique supplied matrix identities required')
    declarations = m.get('components', [])
    if not declarations or len(declarations) > 128 or len({c['name'] for c in declarations}) != len(declarations):
        raise ValueError('nonempty unique component map required')
    used = {c['correlation'].split(':', 1)[1] for c in declarations if c['correlation'].startswith('matrix:')}
    if set(matrices)-used:
        raise ValueError(f'TS3: supplied covariance/correlation table ignored: {sorted(set(matrices)-used)}')
    if used-set(matrices):
        raise ValueError('declared matrix table missing')
    total_label = _text(m.get('total_error_label'), 'stated total error label')
    labels = [c['error_label'] for c in declarations if 'error_label' in c]
    if len(set(labels)) != len(labels) or total_label in labels:
        raise ValueError('unique component error labels separate from total required')
    ignored = m.get('excluded_errors', {})
    if not isinstance(ignored, dict) or any(not isinstance(v, str) or not v.strip() for v in ignored.values()) or set(ignored) & set(labels+[total_label]):
        raise ValueError('excluded errors need distinct labels and declared reasons')
    for row in rows:
        row_labels = [e.get('label') for e in row.get('errors', [])]
        if len(set(row_labels)) != len(row_labels) or any(not isinstance(v, str) for v in row_labels):
            raise ValueError('unique named source errors required')
        if set(row_labels)-set(labels+[total_label])-set(ignored):
            raise ValueError('unmapped named source error')
    by_component, components = {}, []
    for c in declarations:
        _text(c['name'], 'component name')
        if c['kind'] not in KINDS:
            raise ValueError('declared component kind required')
        corr = c['correlation']; rule = c.get('symmetrization', 'none')
        if c['kind'] == 'lumi' and corr != 'full':
            raise ValueError('luminosity must be fully correlated')
        pairs = sigma = None
        if 'error_label' in c:
            pairs, sigma, directions = _errors(rows, c['error_label'], central, col['header'], rule)
        if corr.startswith('matrix:'):
            item = copy.deepcopy(matrices[corr.split(':', 1)[1]])
            if 'table' in item:
                item['matrix_labels'] = c.get('matrix_labels')
            coefficient = _matrix(item, ids, unit)
            if item['kind'] == 'covariance':
                covariance = coefficient
                if sigma is not None and not np.allclose(sigma**2, np.diag(covariance), rtol=.001, atol=0):
                    raise ValueError(f'component matrix marginal errors differ: bins {ids}')
                if pairs is None:
                    sigma = np.sqrt(np.diag(covariance)); pairs = [[float(s), float(s)] for s in sigma]
            else:
                if sigma is None:
                    raise ValueError('correlation table needs declared marginal errors')
                covariance = coefficient*np.outer(sigma, sigma)
        else:
            if sigma is None:
                raise ValueError('nonmatrix component requires named errors')
            if corr == 'diagonal': coefficient = np.eye(len(ids))
            elif corr == 'full': coefficient = np.ones((len(ids), len(ids)))
            elif corr in ('declared:equicorrelation', 'declared:blocks'):
                rho = _numeric(c.get('rule', {}).get('rho'))
                if not -1 <= rho <= 1:
                    raise ValueError(f'declared correlation outside [-1,1]: bins {ids}')
                coefficient = np.full((len(ids), len(ids)), rho); np.fill_diagonal(coefficient, 1)
                if corr == 'declared:blocks':
                    groups = c['rule'].get('groups')
                    if not isinstance(groups, list) or len(groups) != len(ids) or any(not isinstance(g, str) or not g for g in groups):
                        raise ValueError('declared groups must cover each bin')
                    coefficient *= np.equal.outer(groups, groups)
                _checked_matrix(coefficient, ids, c['name'])
            elif corr == 'declared:matrix':
                declared = c.get('rule', {})
                if declared.get('bin_ids') != ids:
                    raise ValueError(f'declared correlation bin ordering differs: bins {ids}')
                coefficient = _checked_matrix(declared.get('values'), ids, c['name'])
                if np.any(np.abs(coefficient) > 1) or not np.array_equal(np.diag(coefficient), np.ones(len(ids))):
                    raise ValueError(f'declared correlation domain/diagonal invalid: bins {ids}')
            else:
                raise ValueError('unsupported declared correlation rule')
            if corr in COMMON_SIGN:
                _common_sign(directions, c['rule']['groups'] if corr == 'declared:blocks' else [None]*len(ids), ids, c['name'])
            covariance = coefficient*np.outer(sigma, sigma)
        covariance = _checked_matrix(covariance, ids, c['name'])
        by_component[c['name']] = covariance.tolist()
        components.append({'name': c['name'], 'kind': c['kind'], 'symmetrized': rule,
                           'values': pairs, 'correlation': corr, 'declaration': c})
    total = _checked_matrix(sum(np.array(v) for v in by_component.values()), ids, 'total')
    _, stated, _ = _errors(rows, total_label, central, col['header'], m.get('total_symmetrization', 'none'))
    actual = np.sqrt(np.diag(total))
    deviations = np.divide(np.abs(actual-stated), stated, out=np.where(actual == 0, 0., np.inf), where=stated != 0)
    if np.max(deviations) > .001:
        offending = [ids[i] for i in np.flatnonzero(deviations > .001)]
        raise ValueError(f'stated total uncertainty mismatch: bins {offending}')
    rank, law = _normalization(central, bins, total, m['normalization'], m.get('normalization_weights'))
    fiducial = copy.deepcopy(m['fiducial']); fiducial['routine_bookings'] = {}
    checked_routine = None
    if routine is not None:
        supplied_record = record if record is not None else full_record
        record_column = m.get('record_column', m['column'])
        if type(record_column) is not int or record_column < 0:
            raise ValueError('TS6: nonnegative REF column index required')
        checked_routine, fiducial['routine_bookings'] = _routine_check(routine, supplied_record, source, m['distribution'], record_column, bins)
    if pin:
        source['sha256'][m['distribution']] = pin['sha256']
    source['sha256']['source_tables'] = source_tables.digest(document)
    source['sha256']['component_map'] = source_tables.digest(component_map)
    bundle = {'schema_version': 1, 'kind': 'measurement-bundle', 'source': source,
              'routine': checked_routine, 'observable': observable, 'normalization': m['normalization'],
              'normalization_weights': m.get('normalization_weights'), 'bin_ids': list(ids), 'bins': bins,
              'values': central.tolist(), 'components': components,
              'covariance': {'total': total.tolist(), 'by_component': by_component, 'rank': rank, 'psd': True, 'law': law},
              'fiducial': fiducial, 'assembly_checks': {'total_reproduced_max_rel_dev': float(np.max(deviations)),
                    'rule_for_asymmetric': {c['name']: c['symmetrized'] for c in components},
                    'stated_total': stated.tolist(), 'excluded_errors': ignored,
                    'total_symmetrization': m.get('total_symmetrization', 'none')},
              'physics_validated': False}
    return _validate_bundle(bundle)


def _validate_bundle(bundle):
    try:
        json.dumps(bundle, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError('finite JSON measurement bundle required') from exc
    schema = _json(files('ravel').joinpath('data/sm/schema/measurement-bundle.schema.json').read_bytes())
    try:
        jsonschema.Draft202012Validator(schema).validate(bundle)
    except jsonschema.ValidationError as exc:
        raise ValueError(f'measurement_bundle.v1 schema: {exc.message}') from exc
    ids = bundle['bin_ids']; total = _checked_matrix(bundle['covariance']['total'], ids, 'total')
    names = [c['name'] for c in bundle['components']]
    by = bundle['covariance']['by_component']
    if len(set(ids)) != len(ids) or len(set(names)) != len(names) or set(names) != set(by):
        raise ValueError('unique matching component and bin identities required')
    if len(bundle['values']) != len(ids) or len(bundle['bins']) != len(ids):
        raise ValueError('complete bundle bin census required')
    bins = bundle['bins']
    if any(b['lo'] >= b['hi'] for b in bins) or any(a['hi'] > b['lo'] for a, b in zip(bins, bins[1:])):
        raise ValueError('ordered nonoverlapping bundle intervals required')
    if bundle['routine'] is not None and bundle['routine']['record_version'] != bundle['source']['version']:
        raise ValueError('TS6: bundle routine REF version mismatch')
    checked = [_checked_matrix(by[name], ids, name) for name in names]
    if not np.array_equal(sum(checked), total):
        raise ValueError('total covariance differs from component sum')
    for component in bundle['components']:
        if len(component['values']) != len(ids):
            raise ValueError('component bin census mismatch')
        errors = np.array(component['values'])
        sigma = errors.mean(axis=1) if component['symmetrized'] == 'average' else errors.max(axis=1)
        if component['symmetrized'] == 'none' and not np.array_equal(errors[:, 0], errors[:, 1]):
            raise ValueError('asymmetric component requires symmetrization')
        if not np.allclose(sigma**2, np.diag(by[component['name']]), rtol=.001, atol=0):
            raise ValueError('component uncertainties differ from covariance marginals')
        if component['kind'] == 'lumi' and component['correlation'] != 'full':
            raise ValueError('luminosity must be fully correlated')
        declared = component['declaration']
        if any(declared.get(k) != component[k] for k in ('name', 'kind', 'correlation')) or declared.get('symmetrization', 'none') != component['symmetrized']:
            raise ValueError('component metadata differs from declaration')
        if component['correlation'] in ('diagonal', 'full'):
            expected = np.diag(sigma**2) if component['correlation'] == 'diagonal' else np.outer(sigma, sigma)
            if not np.allclose(by[component['name']], expected, rtol=1e-12, atol=0):
                raise ValueError('component correlation differs from declared law')
    if bundle['assembly_checks']['rule_for_asymmetric'] != {c['name']: c['symmetrized'] for c in bundle['components']}:
        raise ValueError('bundle asymmetric rule ledger mismatch')
    rank, law = _normalization(np.array(bundle['values']), bundle['bins'], total, bundle['normalization'], bundle['normalization_weights'])
    if rank != bundle['covariance']['rank'] or law != bundle['covariance']['law']:
        raise ValueError('bundle covariance rank/law mismatch')
    stated = np.array(bundle['assembly_checks']['stated_total'])
    if stated.shape != (len(ids),):
        raise ValueError('stated total bin census mismatch')
    actual = np.sqrt(np.diag(total))
    dev = np.divide(np.abs(actual-stated), stated, out=np.where(actual == 0, 0., np.inf), where=stated != 0)
    if np.max(dev) > .001 or float(np.max(dev)) != bundle['assembly_checks']['total_reproduced_max_rel_dev']:
        raise ValueError('bundle stated total check mismatch')
    return bundle


def load_bundle(path):
    """Read bounded nonsymlink JSON and check schema and covariance invariants."""
    return _validate_bundle(_json(source_tables.bounded_read(Path(path))))


def validate(spec):
    required = {'schema_version', 'input', 'component_map'}
    if not isinstance(spec, dict) or not required <= set(spec) or set(spec)-required-{'routine', 'record'} or type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('closed measurement-intake task/v1 required')
    for key in set(spec)-{'schema_version'}:
        pin = spec[key]
        if not isinstance(pin, dict) or set(pin) != {'path', 'sha256'}:
            raise ValueError('each intake input needs a path and SHA256 pin')
        _text(pin['path'], 'input path')
        if not isinstance(pin['sha256'], str) or len(pin['sha256']) != 64 or any(c not in '0123456789abcdef' for c in pin['sha256']):
            raise ValueError('input SHA256 required')
    return copy.deepcopy(spec)


def _inputs(spec, base):
    from ravel.workflow.science import regular
    spec = validate(spec); paths, docs = [], {}
    for key in ('input', 'component_map', 'routine', 'record'):
        if key not in spec: continue
        path = regular(spec[key]['path'], base)
        raw = source_tables.bounded_read(path)
        if hashlib.sha256(raw).hexdigest() != spec[key]['sha256']:
            raise ValueError(f'{key} input digest mismatch')
        paths.append(path); docs[key] = _json(raw)
    return paths, docs


def inputs(spec, base):
    paths, docs = _inputs(spec, base)
    assemble(docs['input'], docs['component_map'], routine=docs.get('routine'), record=docs.get('record'))
    return paths


def run(spec, base, out):
    from ravel.workflow.state_io import atomic_json
    _, docs = _inputs(spec, base)
    bundle = assemble(docs['input'], docs['component_map'], routine=docs.get('routine'), record=docs.get('record'))
    bundle.update(status='passed', status_scope='Declared covariance assembly and supplied routine reference checks; no source applicability certification')
    _validate_bundle(bundle)
    out = Path(out)
    if out.exists() or out.is_symlink() or any(p.is_symlink() for p in out.parents):
        raise ValueError('fresh unlinked measurement output directory required')
    out.mkdir(parents=True, exist_ok=False)
    atomic_json(out/'measurement-bundle.json', bundle)
    return bundle
