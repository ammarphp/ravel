"""Quantity contracts at operation boundaries, without inferred physics inputs.

Descriptors are partial facts. Requirements turn absent facts into located
obligations; only contradictions are errors. No conversion is performed here.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations
import json

from ravel.physics.quantities import _number, _text
from ravel.validation import core

KINDS = ('cross_section', 'differential_cross_section', 'event_count', 'efficiency',
         'acceptance_efficiency', 'luminosity', 'sample_exposure', 'statistical_model', 'inference')
FIELDS = ('kind', 'unit', 'normalization', 'included_factors', 'weight_convention',
          'selection', 'model_point', 'bin_ids', 'auxiliary_information', 'exposure', 'regional_exposures',
          'scale', 'event_population', 'luminosity', 'covariance', 'applicability')
CORE = ('kind', 'unit', 'normalization', 'included_factors', 'weight_convention', 'selection', 'model_point')
NORMALIZATION = ('per_luminosity', 'per_bin_width', 'per_event')


def _finding(location, field, observed, expected):
    return {'location': location, 'field': field, 'observed': deepcopy(observed), 'expected': deepcopy(expected),
            'repair': 'repair supplied facts or supply missing evidence; do not infer physics inputs'}


def message(row):
    repair = row.get('repair', 'repair supplied facts or supply missing evidence; do not infer physics inputs')
    return f"{row['location']}: {row['field']} observed {row['observed']!r}; expected {row['expected']!r}; repair {repair}"


def _at(value, path):
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return value is not None, value


def descriptor_errors(quantity, location='quantity'):
    """Validate stated facts only; missing facts belong to the consumer contract."""
    errors = []

    def bad(field, value, expected):
        errors.append(_finding(location, field, value, expected))

    if not isinstance(quantity, dict):
        return [_finding(location, 'quantity', quantity, 'descriptor object')]
    for field in quantity.keys() - set(FIELDS):
        bad(field, quantity[field], list(FIELDS))
    for field, value in quantity.items():
        if value is None:
            continue
        if field == 'kind' and value not in KINDS:
            bad(field, value, list(KINDS))
        elif field == 'weight_convention' and value not in ('signed', 'absolute', 'unweighted'):
            bad(field, value, ['signed', 'absolute', 'unweighted'])
        elif field in ('unit', 'selection'):
            try:
                _text(value, field)
            except ValueError as exc:
                bad(field, value, str(exc))
        elif field == 'model_point':
            if not isinstance(value, dict) or not value:
                bad(field, value, 'nonempty supplied model identity and coordinates')
        elif field == 'normalization':
            if not isinstance(value, dict):
                bad(field, value, 'explicit boolean normalization properties')
            else:
                for name, flag in value.items():
                    if name not in NORMALIZATION or (flag is not None and type(flag) is not bool):
                        bad(field + '.' + name, flag, 'boolean ' + ', '.join(NORMALIZATION))
        elif field in ('bin_ids', 'auxiliary_information'):
            if not isinstance(value, list) or (field == 'bin_ids' and not value) or any(not isinstance(v, str) or not v.strip() for v in value):
                bad(field, value, 'list of literal identities')
            elif len(value) != len(set(value)):
                bad(field, value, 'each identity once')
        elif field == 'regional_exposures':
            if not isinstance(value, dict) or not value:
                bad(field, value, 'nonempty region-to-exposure mapping')
            else:
                for region, exposure in value.items():
                    if not isinstance(region, str) or not region.strip():
                        bad(field, region, 'literal region identity')
                    errors += descriptor_errors({'exposure': exposure}, location + '.' + field + '.' + region)
        elif field == 'exposure':
            if not isinstance(value, dict) or set(value) - {'id', 'revision'}:
                bad(field, value, 'sample exposure id and revision')
            else:
                for key, item in value.items():
                    if item is None:
                        continue
                    try:
                        _text(item, key)
                    except ValueError as exc:
                        bad(field + '.' + key, item, str(exc))
        elif field == 'included_factors':
            if not isinstance(value, list):
                bad(field, value, 'list of named factors with kind, value and source')
                continue
            names = set()
            for i, factor in enumerate(value):
                label = f'{field}.{i}'
                if not isinstance(factor, dict) or set(factor) - {'name', 'kind', 'value', 'source'}:
                    bad(label, factor, 'name, kind, value and source')
                    continue
                for key in ('name', 'source'):
                    if factor.get(key) is None:
                        continue
                    try:
                        _text(factor[key], key)
                    except ValueError as exc:
                        bad(label + '.' + key, factor[key], str(exc))
                name = factor.get('name')
                if isinstance(name, str):
                    if name in names:
                        bad(label + '.name', name, 'factor included exactly once')
                    names.add(name)
                if factor.get('kind') is not None and factor['kind'] not in ('branching_fraction', 'filter_efficiency', 'k_factor'):
                    bad(label + '.kind', factor['kind'], ['branching_fraction', 'filter_efficiency', 'k_factor'])
                if factor.get('value') is None:
                    continue
                try:
                    number = _number(factor['value'], 'factor')
                    if number < 0 or (factor.get('kind') in ('branching_fraction', 'filter_efficiency') and number > 1):
                        raise ValueError('factor outside physical range')
                except ValueError as exc:
                    bad(label + '.value', factor['value'], str(exc))
    kind, unit = quantity.get('kind'), quantity.get('unit')
    if kind in ('event_count', 'sample_exposure') and unit is not None and unit != 'events':
        bad('unit', unit, 'events')
    if kind in ('efficiency', 'acceptance_efficiency') and unit is not None and unit != '1':
        bad('unit', unit, '1')
    normalization = quantity.get('normalization')
    # A cross section is a rate per unit integrated luminosity; an event count is not.
    if isinstance(normalization, dict) and normalization.get('per_luminosity') is not None:
        if kind in ('cross_section', 'differential_cross_section', 'event_count'):
            expected = kind != 'event_count'
            if normalization['per_luminosity'] is not expected:
                bad('normalization.per_luminosity', normalization['per_luminosity'], expected)
    if isinstance(normalization, dict) and normalization.get('per_bin_width') is not None:
        if kind in ('cross_section', 'differential_cross_section', 'event_count'):
            expected = kind == 'differential_cross_section'
            if normalization['per_bin_width'] is not expected:
                bad('normalization.per_bin_width', normalization['per_bin_width'], expected)
    errors += extension_errors(quantity, location)
    return errors



EXTENSION_FIELDS = {
    'event_population': ('id', 'revision', 'grouping', 'events', 'sumw', 'sumw2', 'negative_events'),
    'luminosity': ('value', 'unit', 'scale'),
    'covariance': ('status', 'basis', 'matrix', 'source'),
    'applicability': ('id', 'parameters', 'assumptions'),
}


def _required_extension_path(path, paths):
    if path in paths:
        return True
    parts = path.split('.')
    return (len(parts) in (3, 4) and parts[:2] == ['applicability', 'parameters']
            and bool(parts[2].strip()) and (len(parts) == 3 or parts[3] in ('minimum', 'maximum', 'unit')))


def extension_errors(quantity, location='quantity'):
    """Check supplied extended facts, retaining absent facts as partial evidence."""
    errors = []

    def bad(field, value, expected):
        errors.append(_finding(location, field, value, expected))

    def number(field, value, *, nonnegative=False, positive=False, integer=False):
        try:
            core.finite_number(value, field=field, minimum=0 if nonnegative or positive else None)
            if positive and value <= 0:
                raise ValueError('positive value required')
            if integer and type(value) is not int:
                raise ValueError('integer required')
            return True
        except ValueError as exc:
            bad(field, value, str(exc))
            return False

    def text(field, value):
        if type(value) is not str or not value.strip():
            bad(field, value, 'nonempty literal string')

    def strings(field, value, unique=False):
        if type(value) is not list or any(type(v) is not str or not v.strip() for v in value):
            bad(field, value, 'list of nonempty literal strings')
        elif unique and len(value) != len(set(value)):
            bad(field, value, 'unique literal strings')

    if not isinstance(quantity, dict):
        return errors
    if quantity.get('scale') is not None:
        number('scale', quantity['scale'], positive=True)
    for group, keys in EXTENSION_FIELDS.items():
        value = quantity.get(group)
        if value is None:
            continue
        if type(value) is not dict:
            bad(group, value, 'partial closed object with fields ' + ', '.join(keys))
            continue
        try:
            core.closed_object(value, set(value).intersection(keys), field=group)
        except ValueError as exc:
            bad(group, value, str(exc))
            continue
        for key, item in value.items():
            field = group + '.' + key
            if item is None:
                if group == 'covariance' and key == 'matrix' and value.get('status') == 'known':
                    bad(field, item, 'finite symmetric positive semidefinite matrix')
                continue
            if key in ('id', 'revision', 'source'):
                text(field, item)
            elif group == 'event_population':
                if key == 'grouping':
                    if item != 'event':
                        bad(field, item, 'event')
                else:
                    number(field, item, nonnegative=key != 'sumw', integer=key in ('events', 'negative_events'))
            elif group == 'luminosity':
                if key == 'unit':
                    if item != 'fb^-1':
                        bad(field, item, 'fb^-1')
                else:
                    number(field, item, positive=True)
            elif group == 'covariance':
                if key == 'status' and item not in ('known', 'unknown', 'not_applicable'):
                    bad(field, item, ['known', 'unknown', 'not_applicable'])
                elif key == 'basis':
                    strings(field, item, unique=True)
                elif key == 'matrix':
                    if value.get('status') in ('unknown', 'not_applicable'):
                        bad(field, item, 'null for unknown or not_applicable covariance')
                    else:
                        _covariance_matrix_errors(item, value.get('basis'), field, bad)
            elif group == 'applicability':
                if key == 'assumptions':
                    strings(field, item)
                elif key == 'parameters':
                    if type(item) is not dict:
                        bad(field, item, 'parameter-to-bound mapping')
                        continue
                    for name, bounds in item.items():
                        label = field + '.' + str(name)
                        text(label, name)
                        if type(bounds) is not dict or set(bounds) - {'minimum', 'maximum', 'unit'}:
                            bad(label, bounds, 'partial closed minimum, maximum, unit object')
                            continue
                        valid = True
                        for bound, number_value in bounds.items():
                            if number_value is None:
                                continue
                            if bound == 'unit':
                                if type(number_value) is not str:
                                    bad(label + '.unit', number_value, 'literal unit string')
                            else:
                                valid = number(label + '.' + bound, number_value) and valid
                        if valid and bounds.get('minimum') is not None and bounds.get('maximum') is not None:
                            if bounds['minimum'] > bounds['maximum']:
                                bad(label, bounds, 'minimum <= maximum')
    return errors


def _covariance_matrix_errors(matrix, basis, field, bad):
    if type(matrix) is not list or any(type(row) is not list or len(row) != len(matrix) for row in matrix):
        bad(field, matrix, 'square numeric matrix')
        return
    if isinstance(basis, list) and len(basis) != len(matrix):
        bad(field, matrix, 'matrix dimension equal to covariance basis length')
        return
    try:
        for row in matrix:
            for value in row:
                core.finite_number(value, field=field)
    except ValueError as exc:
        bad(field, matrix, str(exc))
        return
    if not matrix:
        return
    import numpy as np
    array = np.asarray(matrix, dtype=float)
    scale = float(np.max(np.abs(array))) or 1.0
    array = array / scale
    tolerance = 1e-12
    if not np.allclose(array, array.T, rtol=0, atol=tolerance):
        bad(field, matrix, 'symmetric covariance matrix within relative scale tolerance 1e-12')
        return
    try:
        minimum = float(np.linalg.eigvalsh((array + array.T) / 2).min())
    except np.linalg.LinAlgError:
        bad(field, matrix, 'numerically resolvable positive semidefinite covariance')
        return
    if minimum < -tolerance:
        bad(field, matrix, 'positive semidefinite covariance within relative scale tolerance 1e-12')


def requirement_errors(requirement, location='require.quantity'):
    if not isinstance(requirement, dict):
        return [_finding(location, 'quantity', requirement, 'requirement object')]
    errors = descriptor_errors({k: v for k, v in requirement.items() if k != 'required'}, location)
    required = requirement.get('required', [])
    paths = set(FIELDS) | {'normalization.' + k for k in NORMALIZATION} | {'exposure.id', 'exposure.revision'}
    paths |= {group + '.' + key for group, keys in EXTENSION_FIELDS.items() for key in keys}
    if not isinstance(required, list) or any(not isinstance(p, str) or not _required_extension_path(p, paths) for p in required):
        errors.append(_finding(location, 'required', required, sorted(paths)))
    return errors


def compare(observed, expected, location):
    """Return errors and obligations, preserving field, observed and expected values."""
    errors, obligations = [], []
    if observed is not None:
        errors += descriptor_errors(observed, location)
    errors += requirement_errors(expected, location + '.requires')
    if errors:
        return {'errors': errors, 'obligations': obligations}
    observed = observed or {}
    for i, factor in enumerate(observed.get('included_factors') or []):
        for key in ('name', 'kind', 'value', 'source'):
            if factor.get(key) is None:
                obligations.append(_finding(location, f'included_factors.{i}.{key}', None, 'explicit supplied value'))
    if isinstance(observed.get('exposure'), dict):
        for key in ('id', 'revision'):
            if observed['exposure'].get(key) is None:
                obligations.append(_finding(location, 'exposure.' + key, None, 'explicit supplied value'))
    for path in expected.get('required', []):
        present, value = _at(observed, path)
        if not present:
            obligations.append(_finding(location, path, value, 'explicit supplied value'))

    def walk(actual, wanted, path=''):
        for key, target in wanted.items():
            if key == 'required' or target is None:
                continue
            name = path + key
            present, value = _at(actual, key)
            if not present:
                obligations.append(_finding(location, name, value, target))
            elif isinstance(target, dict):
                if not isinstance(value, dict):
                    errors.append(_finding(location, name, value, target))
                else:
                    walk(value, target, name + '.')
            elif type(value) is not type(target) or value != target:
                errors.append(_finding(location, name, value, target))
    walk(observed, {k: v for k, v in expected.items() if k != 'required'})
    regions = observed.get('regional_exposures') or {}
    exposure = observed.get('exposure')
    for region, regional in regions.items():
        if exposure is None:
            obligations.append(_finding(location, 'exposure', None, 'shared sample identity and revision'))
        else:
            regional_report = compare({'exposure': regional}, {'exposure': exposure,
                                      'required': ['exposure.id', 'exposure.revision']},
                                     location + '.regional_exposures.' + region)
            errors += regional_report['errors']
            obligations += regional_report['obligations']
    # A parent and an exact requirement can refer to the same missing fact.
    obligations = list({(r['location'], r['field']): r for r in obligations}.values())
    return {'errors': errors, 'obligations': obligations}


def artifact_report(artifact, expected, location):
    """Check semantic facts against existing artifact-domain validators as well."""
    report = compare(artifact.get('quantity') if isinstance(artifact, dict) else None, expected, location)
    if not isinstance(artifact, dict) or not isinstance(artifact.get('quantity'), dict):
        return report
    quantity = artifact['quantity']
    if artifact.get('kind') == 'binned_values' and 'schema_version' in artifact and 'bins' in artifact:
        from ravel.physics.binned_values import validate
        try:
            validate(artifact)
        except ValueError as exc:
            report['errors'].append(_finding(location, 'artifact', 'invalid', str(exc)))
    for field in ('unit',):
        if field in artifact and field in quantity and artifact[field] != quantity[field]:
            report['errors'].append(_finding(location, field, quantity[field], artifact[field]))
    if 'representation' in artifact and isinstance(quantity.get('normalization'), dict):
        flag = quantity['normalization'].get('per_bin_width')
        if flag is not None and flag != (artifact['representation'] == 'differential'):
            report['errors'].append(_finding(location, 'normalization.per_bin_width', flag,
                                               artifact['representation'] == 'differential'))
    ids = artifact.get('provenance', {}).get('bin_ids') if isinstance(artifact.get('provenance'), dict) else None
    if ids is not None and 'bin_ids' in quantity and ids != quantity['bin_ids']:
        report['errors'].append(_finding(location, 'bin_ids', quantity['bin_ids'], ids))
    return report


def relations(rows, rules, location):
    """Compare incoming quantities at a consumer, including repeated input slots.

    Rules explicitly name slots and fields. Equality retains array order; disjoint
    information identities forbid counting an auxiliary observation twice.
    Relations compare shared facts only. Missing facts are obligations of the
    consuming slot, never requirements inferred from a different input.
    """
    report = {'errors': [], 'obligations': []}
    expanded = []
    for rule in rules:
        selected = [r for r in rows if r['slot'] in rule['slots']]
        if not rule.get('group_by'):
            expanded.append((rule, selected))
            continue
        groups = {}
        for row in selected:
            key = []
            for field in rule['group_by']:
                present, value = _at(row.get('quantity'), field)
                if not present:
                    break
                key.append(value)
            else:
                groups.setdefault(json.dumps(key, sort_keys=True), []).append(row)
        expanded.extend((rule, group) for group in groups.values())
    for rule, selected in expanded:
        for field in rule['fields']:
            values = []
            for row in selected:
                present, value = _at(row.get('quantity'), field)
                if present:
                    values.append((row, value))
            if rule['relation'] == 'equal' and values:
                def shared(actual, expected, path, row, first):
                    if isinstance(actual, dict) and isinstance(expected, dict):
                        for key in sorted(actual.keys() & expected.keys()):
                            if actual[key] is not None and expected[key] is not None:
                                shared(actual[key], expected[key], path + '.' + key, row, first)
                    elif type(actual) is not type(expected) or actual != expected:
                        report['errors'].append(_finding(row['location'], path, actual,
                                                            {first['location']: expected}))

                # Partial dictionaries need every pair: the first may lack a
                # coordinate that two later inputs both state and disagree on.
                for (first, reference), (row, value) in combinations(values, 2):
                    shared(value, reference, field, row, first)
            elif rule['relation'] == 'disjoint':
                seen = {}
                for row, value in values:
                    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                        report['errors'].append(_finding(row['location'], field, value, 'list of information identities'))
                        continue
                    for token in value:
                        if token in seen:
                            report['errors'].append(_finding(row['location'], field, token,
                                                                'information used once; already at ' + seen[token]))
                        seen[token] = row['location']
    return report


def plan_report(plan, registry, artifacts=None):
    """Semantic part of the ordinary request-plan composition check."""
    nodes = {n['id']: n for n in plan['nodes']}
    inputs = {i['id']: i for i in plan['inputs']}
    report = {'errors': [], 'obligations': []}
    incoming = {}

    def add(result):
        for side in report:
            report[side].extend(result[side])

    for edge in plan['edges']:
        source, target = edge['from']['ref'], edge['to']['ref']
        producer = nodes.get(source, {})
        consumer = nodes.get(target, {})
        signature = registry.get(producer.get('operation')) or {}
        produced = next((s for s in signature.get('produces', []) if s['slot'] == edge['from']['slot']), {})
        provided = inputs.get(source, {}).get('provides', produced).get('require', {}).get('quantity')
        stated = edge['require'].get('quantity')
        location = f"{edge['id']} {source}.{edge['from']['slot']} -> {target}.{edge['to']['slot']}"
        # An edge annotation cannot silently relabel producer facts.
        if provided is not None and stated is not None:
            add(compare(stated, provided, location))
        quantity = provided if stated is None else stated
        if artifacts is not None and edge['id'] in artifacts:
            artifact = artifacts[edge['id']]
            actual = artifact.get('quantity') if isinstance(artifact, dict) else None
            add(artifact_report(artifact, stated or provided or {}, location))
            if provided is not None:
                add(compare(actual, provided, location + '.producer'))
            quantity = actual
        signature = registry.get(consumer.get('operation')) or {}
        wanted = next((s for s in signature.get('consumes', []) if s['slot'] == edge['to']['slot']), {})
        requirement = wanted.get('require', {}).get('quantity')
        if requirement is not None:
            add(compare(quantity, requirement, location))
        elif quantity is not None:
            report['errors'] += descriptor_errors(quantity, location)
        incoming.setdefault(target, []).append({'slot': edge['to']['slot'], 'quantity': quantity, 'location': location})
    for target, rows in incoming.items():
        signature = registry.get(nodes.get(target, {}).get('operation')) or {}
        add(relations(rows, signature.get('quantity_relations', []), target))
    return report
