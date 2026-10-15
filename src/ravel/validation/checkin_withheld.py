"""Conformance checks for reference-withheld planning and after-sealing comparisons."""
from __future__ import annotations

import math
from pathlib import Path

from ravel.workflow import source_policy
from ravel.workflow.restriction_guard import VALUE_CLASSES, equivalent_identities, numeric_quantities

KINDS = ('generator-closure', 'sigma-br-lumi', 'cutflow-monotone', 'mc-precision', 'invisible-census')
GALLERY_FIELDS = ('ii', 'iii', 'published_figure_gallery', 'figure_target', 'figure_targets', 'figure_id')
VALUE_FIELDS = ('published_value', 'published_comparison', 'comparison_target', 'agreement_targets')
REFERENCE_FIELDS = ('source', 'reference', 'identifiers', 'inspire', 'arxiv', 'hepdata', 'url', 'published')


def _number(value, *, positive=False):
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def _numbers(value):
    return type(value) is list and bool(value) and all(_number(v) for v in value)


def _waypoint(row):
    if type(row) is not dict or row.get('kind') not in KINDS:
        return False
    kind = row['kind']
    if kind == 'generator-closure':
        a, b, tol = (row.get(k) for k in ('generator_sigma_pb', 'table_sigma_pb', 'relative_tolerance'))
        return (_number(a) and _number(b, positive=True) and _number(tol) and
                isinstance(row.get('order_difference'), str) and bool(row['order_difference'].strip()) and
                abs(a - b) / b <= tol)
    if kind == 'sigma-br-lumi':
        a, b, c, expected = (row.get(k) for k in ('sigma_pb', 'br', 'lumi_fb', 'expected_events'))
        return (all(_number(v) for v in (a, b, c, expected)) and b <= 1 and
                math.isclose(expected, a * b * c * 1000, rel_tol=1e-9, abs_tol=1e-9))
    if kind == 'cutflow-monotone':
        counts = row.get('counts')
        return _numbers(counts) and len(counts) >= 2 and all(a >= b for a, b in zip(counts, counts[1:]))
    if kind == 'mc-precision':
        errors, target = row.get('relative_errors'), row.get('target')
        return _numbers(errors) and _number(target, positive=True) and all(v <= target for v in errors)
    a, b = row.get('detector_particles'), row.get('spectrum_particles')
    return (type(a) is list and type(b) is list and all(type(v) is int for v in a + b)
            and len(a) == len(set(a)) and len(b) == len(set(b)) and set(a) == set(b))


def _rows(contract, kinds=None):
    rows = [r for r in source_policy.canonical(contract.get('forbidden_sources', []))
            if kinds is None or r['kind'] in kinds]
    return [{**r, 'identifiers': equivalent_identities(r['identifiers'])} if 'identifiers' in r else r for r in rows]


def _target(contract, quantities):
    targets = contract.get('targets') or {}
    return {'identifiers': equivalent_identities({k: targets.get(k, []) for k in ('analysis', 'arxiv', 'inspire', 'hepdata')}),
            'classes': list(VALUE_CLASSES), 'quantities': quantities}


def _comparison_descriptors(document, quantities, base_dir=None):
    sections = document.get('sections') or {}
    candidates = [document.get('comparison_target'), sections.get('comparison_target'),
                  sections.get('figure_target'), sections.get('figure_targets'), sections.get('iii')]
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get('identifiers'), dict):
                yield {'identifiers': equivalent_identities(value['identifiers']),
                       'classes': list(VALUE_CLASSES), 'quantities': quantities}
            if isinstance(value.get('path'), str):
                path = Path(value['path'])
                aliases = []
                if not path.is_absolute() and '..' not in path.parts:
                    aliases.append(path.as_posix().removeprefix('inputs/'))
                if base_dir is not None:
                    root = Path(base_dir).resolve()
                    candidate = path if path.is_absolute() else root / path
                    for candidate in (candidate.absolute(), candidate.resolve()):
                        for base in (root / 'inputs', root):
                            if candidate.is_relative_to(base):
                                aliases.append(candidate.relative_to(base).as_posix())
                for alias in aliases:
                    if alias and alias != '.':
                        yield {**value, 'path': alias, 'classes': list(VALUE_CLASSES), 'quantities': quantities}
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)
    for candidate in candidates:
        yield from walk(candidate)


def _restricted(contract, document, base_dir=None):
    if not isinstance(contract, dict):
        return False
    rows = _rows(contract, ('blinded', 'blinded-data', 'no-value-extraction'))
    quantities = numeric_quantities(rows)
    return any(source_policy.matches(rows, source) for source in (
        _target(contract, quantities), *_comparison_descriptors(document, quantities, base_dir)))


def _output_path(value):
    """A run-relative file under outputs/ is produced by this run, not published."""
    if type(value) is not str:
        return False
    path = Path(value)
    return not path.is_absolute() and '..' not in path.parts and path.parts[:1] == ('outputs',) and len(path.parts) > 1


def _external(value):
    """True when content names a source other than this run's own outputs."""
    if isinstance(value, dict):
        if any(value.get(k) not in (None, False, '', [], {}) for k in REFERENCE_FIELDS):
            return True
        if 'path' in value and not _output_path(value['path']):
            return True
        return any(_external(child) for child in value.values())
    if isinstance(value, list):
        return any(_external(child) for child in value)
    return False


def _external_gallery(value):
    entries = value if isinstance(value, list) else [value]
    return any(not _output_path(entry) if not isinstance(entry, dict) else _external(entry) or 'path' not in entry
               for entry in entries)


def _published_fields(value, allowed=()):
    """Fields carrying published reference material; `allowed` names the permitted kinds."""
    if isinstance(value, dict):
        for key, child in value.items():
            kind = ('gallery' if key in GALLERY_FIELDS or (key == 'gallery' and _external_gallery(child)) else
                    'value' if key in VALUE_FIELDS or (key == 'comparison' and _external(child)) else None)
            if kind and kind not in allowed and child not in (None, [], {}):
                yield key
            yield from _published_fields(child, allowed)
    elif isinstance(value, list):
        for child in value:
            yield from _published_fields(child, allowed)


def _source_errors(row, contract):
    """A waypoint's external input must be declared and independent of the withheld reference."""
    source = row.get('source')
    if row.get('kind') != 'generator-closure' and 'source' not in row:
        return False
    if type(source) is not dict:
        return True
    path, identifiers = source.get('path'), source.get('identifiers')
    if path is None and identifiers is None:
        return True
    descriptor = {'classes': list(VALUE_CLASSES)}
    if identifiers is not None:
        if type(identifiers) is not dict or not any(identifiers.values()):
            return True
        descriptor['identifiers'] = equivalent_identities(identifiers)
    if path is not None:
        parts = Path(path).parts if type(path) is str else ()
        if not parts or Path(path).is_absolute() or '..' in parts:
            return True
        descriptor['path'] = Path(path).as_posix().removeprefix('inputs/')
    if not isinstance(contract, dict):
        return False
    rows = _rows(contract)
    descriptor['quantities'] = numeric_quantities(rows)
    target = _target(contract, descriptor['quantities'])['identifiers']
    if any(set(values) & set(target.get(key, [])) for key, values in descriptor.get('identifiers', {}).items()):
        return True
    return bool(source_policy.matches(rows, descriptor))


def checkin_errors(document, contract, variant, *, base_dir=None):
    """One validator seam; unrestricted reproduction keeps its existing checks."""
    errors = []
    try:
        if variant == 'reproduction' and _restricted(contract, document, base_dir):
            errors.append('CHECK-IN 1 comparison target is restricted: use reference_withheld instead of reproduction')
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(f'CHECK-IN 1 reference_withheld source restriction invalid: {exc}')
    if variant != 'reference_withheld':
        return errors
    sections = document.get('sections') or {}
    waypoints = sections.get('withheld_waypoints')
    if type(waypoints) is not list or not waypoints:
        errors.append('reference_withheld requires a non-empty withheld_waypoints list')
    else:
        for index, row in enumerate(waypoints):
            if not _waypoint(row):
                errors.append(f'reference_withheld waypoint {index + 1} must be checkable ({", ".join(KINDS)})')
            elif _source_errors(row, contract):
                errors.append(f'reference_withheld waypoint {index + 1} needs a declared source independent of the '
                              'withheld reference and its restrictions')
    material = {k: v for k, v in document.items() if k != 'post_sealing_comparison'}
    fields = sorted(set(_published_fields(material)) |
                    set(_published_fields(document.get('post_sealing_comparison'), allowed=('value',))))
    if fields:
        errors.append('reference_withheld refuses published gallery, figure target or value comparison: ' + ', '.join(fields))
    if 'post_sealing_comparison' in document:
        comparison = document['post_sealing_comparison']
        if (type(comparison) is not dict or comparison.get('result_sealed_first') is not True or
                comparison.get('phase') != 'after-delivery' or comparison.get('label') != 'after-sealing'):
            errors.append('reference_withheld comparison requires result_sealed_first=true, phase=after-delivery and label=after-sealing')
    return errors
