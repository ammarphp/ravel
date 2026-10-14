"""Typed analysis specification: every field with its value, source span and status.

When an analysis has no public routine, its selection is written from the paper. This
document records what the paper says, item by item, before any code is written::

    {"schema_version": 1, "kind": "typed-analysis-spec", "analysis": "short name",
     "sources": [{"id": "paper", "path": "paper.txt"}],
     "items": [
       {"id": "electrons", "role": "object", "family": "electron",
        "fields": {"pt_min": {"value": 10, "unit": "GeV", "status": "explicit",
                              "span": {"source": "paper", "line_start": 120, "line_end": 121,
                                       "excerpt_sha256": "..."}},
                   "isolation": {"value": null, "status": "not_specified"}}},
       {"id": "sr-met", "role": "cut", "region": "signal region", "order": 3,
        "collection": {"value": "jets", "status": "explicit", "span": {...}},
        "fields": {"threshold": {...}}},
       {"id": "met-hist", "role": "histogram", "region": "signal region",
        "fields": {"normalization_basis": {"value": "xsec", "status": "inferred", "note": "..."},
                   "edges": {"value": [200, 300, 500], "status": "explicit", "span": {...}}}}]}

Roles: ``object``, ``overlap``, ``cut``, ``observable``, ``histogram``, ``trigger``,
``efficiency`` and ``normalization``. A field's status is ``explicit`` (stated in the
source: a span is required), ``inferred`` (derived by the analyst: a note is required, a
span is optional), ``ambiguous`` (the source admits several readings: list them in
``readings``) or ``not_specified``. A span names lines of a declared source file and the
SHA-256 of their exact bytes, so a quotation cannot drift from the source.

``normalization_basis`` of a histogram is ``fiducial_N``, ``in_range_N``, ``xsec`` or
``bin_width_area_2D``; a one-dimensional slice of a two-dimensional distribution
declares its ``slice`` (``{"variable", "low", "high"}``) so the slice width enters the
normalisation.

``admission_definitions`` turns the items into the ``definitions`` list of an
``analysis_specification`` (``analysis_admission``), so admission consumes this
document rather than a second schema.
"""
import hashlib
import json
from pathlib import Path

ROLES = ('object', 'overlap', 'cut', 'observable', 'histogram', 'trigger', 'efficiency', 'normalization')
STATUSES = ('explicit', 'inferred', 'ambiguous', 'not_specified')
BASES = ('fiducial_N', 'in_range_N', 'xsec', 'bin_width_area_2D')
MAX_ITEMS = 2000


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')
    return value


def check_span(raw, span, label):
    """Byte-exact check of a line span against its excerpt hash."""
    if not isinstance(span, dict) or set(span) != {'source', 'line_start', 'line_end', 'excerpt_sha256'}:
        raise ValueError(f'{label}: a span has source, line_start, line_end and excerpt_sha256')
    start, end = span['line_start'], span['line_end']
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= start + 199:
        raise ValueError(f'{label}: a span needs an exact line range of at most 200 lines')
    lines = raw.splitlines(keepends=True)
    if end > len(lines):
        raise ValueError(f'{label}: the span runs past the end of source {span["source"]!r}')
    excerpt = b''.join(lines[start - 1:end])
    if hashlib.sha256(excerpt).hexdigest() != span['excerpt_sha256']:
        raise ValueError(f'{label}: the quoted lines of source {span["source"]!r} differ from the span hash')
    return excerpt.decode('utf8', errors='replace')


def span_for(raw, source, line_start, line_end):
    """A span for lines of a source (a helper for writing a specification)."""
    excerpt = b''.join(raw.splitlines(keepends=True)[line_start - 1:line_end])
    return {'source': source, 'line_start': line_start, 'line_end': line_end,
            'excerpt_sha256': hashlib.sha256(excerpt).hexdigest()}


def _field(value, label, sources):
    if not isinstance(value, dict) or 'status' not in value or value['status'] not in STATUSES:
        raise ValueError(f'{label}: a field has value and status (one of {STATUSES})')
    if set(value) - {'value', 'unit', 'status', 'span', 'note', 'readings'}:
        raise ValueError(f'{label}: unexpected keys {sorted(set(value) - {"value", "unit", "status", "span", "note", "readings"})}')
    status = value['status']
    if status == 'explicit' and 'span' not in value:
        raise ValueError(f'{label}: an explicit field needs a span in its source')
    if status == 'inferred':
        _text(value.get('note'), f'{label} note (how it was inferred)')
    if status == 'ambiguous' and (not isinstance(value.get('readings'), list) or len(value['readings']) < 2):
        raise ValueError(f'{label}: an ambiguous field lists two or more readings')
    if status == 'not_specified' and value.get('value') is not None:
        raise ValueError(f'{label}: a field that is not specified has no value')
    if 'span' in value:
        if value['span'].get('source') not in sources:
            raise ValueError(f'{label}: span source {value["span"].get("source")!r} is not declared')
        value['excerpt'] = check_span(sources[value['span']['source']], value['span'], label)


def load(document, base):
    """Validate a typed specification and every span against its source bytes."""
    if isinstance(document, (str, Path)):
        path = Path(base) / document if not Path(document).is_absolute() else Path(document)
        raw = path.read_bytes()
        doc = json.loads(raw)
        pin = {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}
    else:
        doc, pin = json.loads(json.dumps(document)), None
    if not isinstance(doc, dict) or doc.get('schema_version') != 1 or doc.get('kind') != 'typed-analysis-spec':
        raise ValueError('a typed analysis specification has schema_version 1 and kind typed-analysis-spec')
    if set(doc) - {'schema_version', 'kind', 'analysis', 'sources', 'items', 'description'}:
        raise ValueError('unexpected keys in the typed analysis specification')
    _text(doc.get('analysis'), 'analysis')
    sources, source_pins = {}, []
    for s in doc.get('sources', []):
        if not isinstance(s, dict) or set(s) != {'id', 'path'} or s['id'] in sources:
            raise ValueError('each source has a distinct id and a path')
        p = Path(base) / s['path'] if not Path(s['path']).is_absolute() else Path(s['path'])
        if p.is_symlink() or not p.is_file():
            raise ValueError(f'source {s["id"]!r} must be a regular file')
        sources[s['id']] = p.read_bytes()
        source_pins.append({'id': s['id'], 'path': str(p.resolve()), 'sha256': hashlib.sha256(sources[s['id']]).hexdigest()})
    items = doc.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise ValueError(f'items is a list of 1 to {MAX_ITEMS} entries')
    ids = set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {'id', 'role', 'family', 'region', 'order', 'collection', 'fields',
                                                      'slice', 'implementation', 'impact_estimate', 'description'}:
            raise ValueError(f'item {item.get("id") if isinstance(item, dict) else item!r}: unexpected keys')
        label = f'item {item.get("id")!r}'
        _text(item.get('id'), 'item id')
        if item['id'] in ids:
            raise ValueError(f'{label} is defined twice')
        ids.add(item['id'])
        if item.get('role') not in ROLES:
            raise ValueError(f'{label}: role must be one of {ROLES}')
        if item['role'] == 'object':
            _text(item.get('family'), f'{label} family')
        if item['role'] in ('cut', 'histogram'):
            _text(item.get('region'), f'{label} region')
        if 'order' in item and (type(item['order']) is not int or item['order'] < 1):
            raise ValueError(f'{label}: order is a positive integer')
        if 'collection' in item:
            _field(item['collection'], f'{label} collection', sources)
        if 'impact_estimate' in item and (type(item['impact_estimate']) not in (int, float) or not 0 <= item['impact_estimate'] <= 10):
            raise ValueError(f'{label}: impact_estimate is the relative change in yield or shape (0 to 10)')
        if 'implementation' in item and (not isinstance(item['implementation'], dict)
                                         or item['implementation'].get('status') != 'not_applicable'
                                         or not str(item['implementation'].get('reason', '')).strip()):
            raise ValueError(f'{label}: implementation is {{"status": "not_applicable", "reason": ...}}')
        fields = item.get('fields', {})
        if not isinstance(fields, dict):
            raise ValueError(f'{label}: fields is an object')
        for key, value in fields.items():
            _field(value, f'{label} field {key!r}', sources)
        if item['role'] == 'histogram':
            basis = fields.get('normalization_basis', {})
            if basis.get('value') is not None and basis['value'] not in BASES:
                raise ValueError(f'{label}: normalization_basis must be one of {BASES}')
            if 'slice' in item:
                s = item['slice']
                if not isinstance(s, dict) or set(s) != {'variable', 'low', 'high'} \
                        or not all(type(s[k]) in (int, float) for k in ('low', 'high')) or not s['low'] < s['high']:
                    raise ValueError(f'{label}: slice has variable, low and high (low < high)')
    return {'doc': doc, 'pin': pin, 'sources': source_pins, 'items': {i['id']: i for i in doc['items']}}


def admission_definitions(spec, artifact):
    """Rows for ``analysis_specification.definitions`` (one per item)."""
    rows = []
    for item in spec['doc']['items']:
        spans = [f['span'] for f in item.get('fields', {}).values() if 'span' in f]
        locator = ('; '.join(f'{s["source"]} lines {s["line_start"]}-{s["line_end"]}' for s in spans)
                   or 'no source span (inferred or not specified)')
        statuses = sorted({f['status'] for f in item.get('fields', {}).values()})
        rows.append({'id': item['id'], 'role': item['role'], 'artifact': artifact, 'locator': locator,
                     'definition': json.dumps({k: v.get('value') for k, v in item.get('fields', {}).items()},
                                              sort_keys=True) + f' [{", ".join(statuses) or "no fields"}]'})
    return rows


def histogram_basis_errors(item, histogram):
    """Problems with how a recipe histogram realises a specified normalisation basis."""
    basis = item.get('fields', {}).get('normalization_basis', {}).get('value')
    if basis is None:
        return []
    errors = []
    norm, ndim = histogram.normalization, len(histogram.observables)
    if basis in ('fiducial_N', 'in_range_N'):
        want = 'all' if basis == 'fiducial_N' else 'in-range'
        if norm not in ('fraction', 'density') or histogram.fraction_denominator != want:
            errors.append(f'{basis} needs fraction or density normalisation with fraction_denominator {want}')
    elif basis == 'xsec':
        if norm not in ('yield', 'yield-per-width'):
            errors.append('xsec needs yield or yield-per-width normalisation')
    elif basis == 'bin_width_area_2D':
        if norm not in ('density', 'yield-per-width'):
            errors.append('bin_width_area_2D needs a per-width normalisation')
        if ndim == 1:
            s = item.get('slice')
            width = getattr(histogram, 'slice_width', None)
            if s is None:
                errors.append('a one-dimensional histogram with bin_width_area_2D needs the slice it is cut from')
            elif width is None or abs(width - (s['high'] - s['low'])) > 1e-9 * max(1.0, abs(s['high'] - s['low'])):
                errors.append(f'slice-area normalisation: the histogram must divide by the slice width '
                              f'{s["high"] - s["low"]:g} of {s["variable"]}')
        elif ndim != 2:
            errors.append('bin_width_area_2D applies to two axes or a slice of two')
    return errors


IMPLEMENTED_ROLES = ('object', 'overlap', 'cut', 'observable', 'histogram')


def coverage(spec, plan):
    """Check the specification-to-recipe mapping in both directions.

    Every recipe node must name the specification items it implements; every object,
    overlap, cut, observable and histogram item must be implemented by a node or declare
    ``implementation: not_applicable`` with a reason; histogram nodes must realise their
    item's normalisation basis.
    """
    items = spec['items']
    unlabelled = [label for label, ids in plan.spec_nodes.items() if not ids]
    unknown = sorted({i for ids in plan.spec_nodes.values() for i in ids if i not in items})
    implemented = {i for ids in plan.spec_nodes.values() for i in ids}
    unimplemented = [i for i, item in items.items() if item['role'] in IMPLEMENTED_ROLES and i not in implemented
                     and 'implementation' not in item]
    basis = []
    histograms = {h.name: h for h in plan.histograms}
    for label, ids in plan.spec_nodes.items():
        if not label.startswith('histogram '):
            continue
        h = histograms.get(label.removeprefix('histogram '))
        for i in ids:
            if h is not None and i in items and items[i]['role'] == 'histogram':
                basis += [f'{label}: {e}' for e in histogram_basis_errors(items[i], h)]
    return {'nodes': plan.spec_nodes, 'nodes_without_spec_item': unlabelled, 'unknown_spec_items': unknown,
            'unimplemented_spec_items': unimplemented, 'normalization_basis_errors': basis,
            'not_applicable': {i: item['implementation']['reason'] for i, item in items.items() if 'implementation' in item},
            'passed': not (unlabelled or unknown or unimplemented or basis)}
