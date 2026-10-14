"""Checks of a routine's output on a small event sample, as typed findings for its author.

The sample run is cheap feedback during construction, not a measurement: it
checks that booked outputs exist and are finite, that each per-event histogram
is filled at most once per event, that output binning equals the HEPData
record, and that each declared normalization relates the final object to its
RAW counterpart as the contract states. A normalization mismatch is classified
by its constant ratio (unit, slice width, bin width, factor two) when the ratio
matches one of those, and reported as an unclassified constant otherwise.
"""
from __future__ import annotations

import math

from . import hepdata_table_map, yoda_text

BASES = ('fiducial_N', 'in_range_N', 'xsec', 'bin_width_area_2D', 'raw')
UNITS = {'pb': 1.0, 'fb': 1e3, 'ab': 1e6, 'nb': 1e-3, 'ub': 1e-6, 'mb': 1e-9}


def validate_contract(entries):
    """Normalization contract rows: ``{object, basis, unit, slice, source}``."""
    if entries is None:
        return []
    if not isinstance(entries, list) or len(entries) > 1000:
        raise ValueError('normalization contract must be a bounded list')
    result, seen = [], set()
    for row in entries:
        if not isinstance(row, dict) or set(row) - {'object', 'basis', 'unit', 'slice', 'source'} or 'object' not in row or 'basis' not in row:
            raise ValueError('normalization rows have object, basis and optional unit, slice and source')
        if not isinstance(row['object'], str) or not row['object'].strip() or row['object'] in seen:
            raise ValueError('normalization rows name distinct output objects')
        if row['basis'] not in BASES:
            raise ValueError(f"normalization basis must be one of {BASES}")
        unit = row.get('unit')
        if unit is not None and unit not in UNITS:
            raise ValueError(f'cross-section unit must be one of {sorted(UNITS)}')
        if row['basis'] in ('xsec', 'bin_width_area_2D') and unit is None:
            raise ValueError(f"basis {row['basis']} needs its cross-section unit")
        width = None
        if row.get('slice') is not None:
            s = row['slice']
            if not isinstance(s, dict) or set(s) != {'variable', 'low', 'high'} or not all(
                    isinstance(s[k], (int, float)) and not isinstance(s[k], bool) for k in ('low', 'high')) or not s['low'] < s['high']:
                raise ValueError('a slice has variable, low and high with low < high')
            width = s['high'] - s['low']
        if row['basis'] == 'bin_width_area_2D' and width is None:
            raise ValueError('a bin_width_area_2D object declares its slice')
        seen.add(row['object'])
        result.append({'object': row['object'], 'basis': row['basis'], 'unit': unit,
                       'slice': row.get('slice'), 'source': row.get('source', 'request')})
    return result


def contract_from_spec(spec):
    """Normalization rows from typed-analysis-spec histogram items (fields keyed by name)."""
    rows = []
    for item in spec.get('items', []) if isinstance(spec, dict) else []:
        if not isinstance(item, dict) or item.get('role') != 'histogram':
            continue
        fields = item.get('fields', {})
        basis = (fields.get('normalization_basis') or {}).get('value')
        if basis is None:
            continue
        identity = (fields.get('hepdata_id') or {}).get('value') or (fields.get('output') or {}).get('value') or item.get('id')
        unit = (fields.get('cross_section_unit') or {}).get('value')
        # analysis_spec records a 2-D slice on the item; a field named slice is also read.
        slice_ = item.get('slice') if isinstance(item.get('slice'), dict) else (
            (fields.get('slice') or {}).get('value') if isinstance(fields.get('slice'), dict) and 'value' in fields.get('slice')
            else fields.get('slice'))
        rows.append({'object': identity, 'basis': basis, 'unit': unit, 'slice': slice_ if isinstance(slice_, dict) else None,
                     'source': 'analysis_spec:' + str(item.get('id'))})
    return validate_contract(rows) if rows else []


def _classify(ratio, *, slice_width=None, bin_widths=()):
    candidates = [(1e3, 'unit: the result is 1000 times the contract (pb versus fb)'),
                  (1e-3, 'unit: the result is 1/1000 of the contract (fb versus pb)'),
                  (2.0, 'factor 2: an event or object counted twice (for example both neutrino solutions)'),
                  (0.5, 'factor 1/2: half the expected normalization')]
    if slice_width:
        candidates += [(slice_width, f'slice width: the 2-D slice width {slice_width:g} was not divided out'),
                       (1 / slice_width, f'slice width: divided by the 2-D slice width {slice_width:g} twice or wrongly')]
    widths = [w for w in bin_widths if w > 0]
    if widths and max(widths) / min(widths) < 1.000001:
        w = widths[0]
        candidates += [(1 / w, f'bin width: values divided by the bin width {w:g} again'),
                       (w, f'bin width: values multiplied by the bin width {w:g}')]
    for target, label in candidates:
        if target > 0 and math.isclose(ratio, target, rel_tol=0.02):
            return label
    return 'unclassified constant'


def findings(objects, routine, *, table_map=None, contract=(), booked=(), tolerance=0.02):
    """Typed findings for a sample YODA ``objects`` dict from ``yoda_text.parse``."""
    out = []

    def add(check, severity, obj, message):
        out.append({'check': check, 'severity': severity, 'object': obj, 'message': message})

    count = objects.get('/RAW/_EVTCOUNT')
    xsec = objects.get('/RAW/_XSEC')
    events = count['rows'][0][-1] if count and count['rows'] else None
    sum_w = count['rows'][0][0] if count and count['rows'] else None
    sigma = xsec['rows'][0][0] if xsec and xsec['rows'] else None
    if events is None:
        add('event_count', 'warning', '/RAW/_EVTCOUNT', 'no event counter in the output; event-level checks are skipped')
    prefix = f'/{routine}/'
    expected = {row['id'] for row in booked if row.get('kind') == 'hepdata'} | {row['object'] for row in contract}
    names = {path[len(prefix):] for path in objects if path.startswith(prefix)}
    raw_names = {path[len('/RAW' + prefix):] for path in objects if path.startswith('/RAW' + prefix)}
    for name in sorted(expected - names - raw_names):
        add('output_missing', 'error', prefix + name, f'{prefix}{name} is booked or declared but absent from the output')
    for name in sorted(names | raw_names):
        final, raw = objects.get(prefix + name), objects.get('/RAW' + prefix + name)
        decoded = [o for o in (final, raw) if o is not None and o.get('edges') is not None]
        if not decoded:
            continue
        if final is not None and final.get('edges') is not None and not yoda_text.finite(final):
            add('non_finite', 'error', prefix + name, f'{prefix}{name} has NaN or infinite bin values')
        if raw is not None and raw.get('edges') is not None:
            entries = yoda_text.entries(raw)
            if entries == 0:
                add('empty', 'warning', prefix + name, f'{prefix}{name} has no entries after {events:g} events'
                    if events else f'{prefix}{name} has no entries')
            elif events and entries is not None and entries > events * (1 + 1e-9):
                add('multiple_fills_per_event', 'warning', prefix + name,
                    f'{prefix}{name} has {entries:g} fills for {events:g} events; a per-event observable must be filled '
                    'once per event (check double filling), unless it is defined per object')
    out += hepdata_table_map.verify_output_binning(table_map, objects, routine)
    for row in contract:
        name = row['object']
        final, raw = objects.get(prefix + name), objects.get('/RAW' + prefix + name)
        if final is None or raw is None or final.get('edges') is None or raw.get('edges') is None:
            continue
        raw_area = yoda_text.area(raw)
        if raw_area == 0:
            add('normalization_unchecked', 'info', prefix + name, f'{prefix}{name}: no RAW entries, normalization not checked')
            continue
        final_area = yoda_text.area(final)
        scale = final_area / raw_area
        width = (row['slice']['high'] - row['slice']['low']) if row.get('slice') else None
        if row['basis'] == 'raw':
            expected_scale = 1.0
        elif row['basis'] == 'in_range_N':
            expected_scale = 1.0 / raw_area
        elif row['basis'] == 'fiducial_N':
            total = sum((r[0] or 0.0) for r in raw['rows'])
            expected_scale = 1.0 / total if total else None
        else:
            if sigma is None or not sum_w:
                add('normalization_unchecked', 'info', prefix + name,
                    f'{prefix}{name}: the output has no cross section or event weight sum; the {row["basis"]} contract is not checked')
                continue
            expected_scale = sigma * UNITS[row['unit']] / sum_w / (width if row['basis'] == 'bin_width_area_2D' else 1.0)
        if not expected_scale:
            continue
        ratio = scale / expected_scale
        if abs(ratio - 1) <= tolerance:
            add('normalization', 'pass', prefix + name, f"{prefix}{name} matches the {row['basis']} contract")
            continue
        label = _classify(ratio, slice_width=width, bin_widths=yoda_text.widths(final))
        add('normalization', 'error', prefix + name,
            f"{prefix}{name}: final/RAW area ratio is {ratio:.6g} times the {row['basis']} contract"
            f"{' in ' + row['unit'] if row['unit'] else ''} ({label})")
    return out
