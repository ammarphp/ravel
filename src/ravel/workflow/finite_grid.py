"""Finite supplied grids and literal card edits with no physical defaults."""
from copy import deepcopy
from fractions import Fraction
from itertools import product
import math
import re


class SpecificationError(ValueError):
    def __init__(self, reason, field):
        self.reason, self.field = reason, field
        super().__init__(f'{reason}: {field}')


def required(document, fields):
    if type(document) is not dict:
        raise SpecificationError('invalid_input', 'document')
    for field in fields:
        if field not in document or document[field] is None:
            raise SpecificationError('missing_input', field)


def identifier(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,80}', value):
        raise SpecificationError('invalid_input', 'safe identifier')
    return value


def literal(value):
    if type(value) not in (str, int, float) or isinstance(value, bool):
        raise SpecificationError('invalid_input', 'finite numeric literal')
    try:
        token = str(value)
        if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?', token):
            raise ValueError()
        number = Fraction(token.replace('D', 'E').replace('d', 'e'))
        if not math.isfinite(float(number)):
            raise ValueError()
    except (ValueError, OverflowError):
        raise SpecificationError('invalid_input', 'finite numeric literal') from None
    return token, number


def coordinates(axes, *, maximum=4096):
    if type(axes) is not list or not 1 <= len(axes) <= 8:
        raise SpecificationError('missing_input' if not axes else 'invalid_input', 'axes')
    names, vectors, count = [], [], 1
    for axis in axes:
        required(axis, ('name', 'values'))
        name = identifier(axis['name'])
        if name in names or type(axis['values']) is not list or not axis['values']:
            raise SpecificationError('invalid_input', 'unique nonempty axes')
        numbers = [literal(v)[1] for v in axis['values']]
        if len(set(numbers)) != len(numbers):
            raise SpecificationError('invalid_input', 'duplicate axis coordinate')
        names.append(name); vectors.append(axis['values']); count *= len(numbers)
        if count > maximum:
            raise SpecificationError('resource_bound', 'grid point count')
    return [dict(zip(names, values)) for values in product(*vectors)]


def delivery(document):
    required(document, ('format', 'filename'))
    if set(document) != {'format', 'filename'} or document['format'] not in ('json', 'tsv'):
        raise SpecificationError('invalid_input', 'delivery format')
    identifier(document['filename'])
    return deepcopy(document)


def parameter_grid(document):
    required(document, ('schema_version', 'study_id', 'axes', 'bindings', 'relations', 'source_evidence', 'dataset_population', 'delivery'))
    if document['schema_version'] != 1 or type(document['schema_version']) is not int:
        raise SpecificationError('invalid_input', 'grid schema version')
    identifier(document['study_id']); delivery(document['delivery'])
    datasets = document['dataset_population']
    if type(datasets) is not list or not datasets:
        raise SpecificationError('missing_input', 'dataset_population')
    ids = []
    for dataset in datasets:
        required(dataset, ('id', 'source'))
        ids.append(identifier(dataset['id']))
    if len(set(ids)) != len(ids):
        raise SpecificationError('invalid_input', 'duplicate dataset identity')
    points = coordinates(document['axes'])
    if type(document['bindings']) is not list or not document['bindings']:
        raise SpecificationError('missing_input', 'bindings')
    if type(document['relations']) is not list:
        raise SpecificationError('invalid_input', 'relations')
    available = set(points[0]); addresses = set(); bound = set()
    for relation in document['relations']:
        required(relation, ('parameter', 'operation'))
        name = identifier(relation['parameter'])
        if name in available:
            raise SpecificationError('invalid_input', 'duplicate relation parameter')
        op = relation['operation']
        fields = {'parameter', 'operation', 'value'} if op == 'constant' else {'parameter', 'operation', 'source', 'scale', 'offset'}
        required(relation, fields)
        if set(relation) != fields or op not in ('constant', 'affine'):
            raise SpecificationError('invalid_input', 'parameter relation')
        if op == 'constant':
            value = literal(relation['value'])[0]
            for point in points: point[name] = value
        else:
            if relation['source'] not in available:
                raise SpecificationError('invalid_input', 'relation source or cycle')
            scale, offset = literal(relation['scale'])[1], literal(relation['offset'])[1]
            for point in points:
                value = literal(point[relation['source']])[1]*scale+offset
                # Exact finite decimal representation; recurring rationals are refused.
                from decimal import Decimal, localcontext
                with localcontext() as context:
                    context.prec = 80
                    token = str(Decimal(value.numerator)/Decimal(value.denominator))
                if literal(token)[1] != value:
                    raise SpecificationError('invalid_input', 'nonterminating relation result')
                point[name] = token
        available.add(name)
    for binding in document['bindings']:
        required(binding, ('parameter', 'block', 'codes'))
        if set(binding) != {'parameter', 'block', 'codes'} or binding['parameter'] not in available:
            raise SpecificationError('invalid_input', 'card binding')
        block = identifier(binding['block']).upper(); codes = binding['codes']
        if type(codes) is not list or not codes or any(type(c) is not int for c in codes):
            raise SpecificationError('invalid_input', 'card address')
        address = (block, tuple(codes))
        if address in addresses:
            raise SpecificationError('invalid_input', 'duplicate card address')
        addresses.add(address); bound.add(binding['parameter'])
    if available != bound:
        raise SpecificationError('missing_input', 'binding for every parameter')
    if type(document['source_evidence']) is not list or not document['source_evidence']:
        raise SpecificationError('missing_input', 'source_evidence')
    return points


def edit_card(raw, bindings, point):
    """Replace only named scalar tokens, refusing ambiguous scaled occurrences."""
    replacements = {(b['block'].upper(), tuple(b['codes'])): literal(point[b['parameter']])[0] for b in bindings}
    if len(replacements) != len(bindings):
        raise SpecificationError('invalid_input', 'duplicate card address')
    block, seen, lines, changes = None, set(), [], []
    for index, line in enumerate(raw.decode('utf-8').splitlines(keepends=True), 1):
        tokens = list(re.finditer(r'\S+', line.split('#', 1)[0]))
        if tokens and tokens[0].group().upper() == 'BLOCK':
            block = tokens[1].group().upper()
        elif tokens and tokens[0].group().upper() == 'DECAY':
            block = None
        elif tokens and block:
            try: codes = tuple(int(t.group()) for t in tokens[:-1])
            except ValueError: codes = ()
            key = (block, codes)
            if key in replacements:
                if key in seen:
                    raise SpecificationError('invalid_input', 'ambiguous card address')
                seen.add(key); token = tokens[-1]; value = replacements[key]
                changes.append({'block': block, 'codes': list(codes), 'line': index, 'before': token.group(), 'after': value})
                line = line[:token.start()]+value+line[token.end():]
        lines.append(line)
    if seen != set(replacements):
        raise SpecificationError('missing_input', 'card address')
    return ''.join(lines).encode('utf-8'), changes


def write_delivery(path, spec, document, rows):
    from .state_io import atomic_json
    if (path/spec['filename']).exists() or (path/spec['filename']).is_symlink():
        raise SpecificationError('invalid_input', 'delivery collides with an existing output')
    if spec['format'] == 'json':
        atomic_json(path/spec['filename'], document)
    else:
        import csv
        import json
        with (path/spec['filename']).open('x', newline='') as stream:
            writer = csv.writer(stream, delimiter='\t')
            writer.writerow(('study_id', 'record'))
            writer.writerows((document['study_id'], json.dumps(row, sort_keys=True, separators=(',', ':'))) for row in rows)
