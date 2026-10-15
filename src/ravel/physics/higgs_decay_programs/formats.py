"""Declarative parsers for supplied column, keyed-width and SLHA layouts.

Column positions and native keywords come from supplied source descriptions,
never guessed release-specific conventions. No upstream implementation is copied.
"""
import re

from ravel.physics.higgs_decays import _basename, _keys, _num, _pdg, _text

PLACEHOLDER = re.compile(r'\$\{([A-Za-z0-9_.-]+)\}')


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('integer ' + label + ' required')
    return value


def _channel(row, extra):
    _keys(row, ('id', 'daughters', *extra), label='layout channel')
    _text(row['id'], 'channel id')
    if type(row['daughters']) is not list or len(row['daughters']) < 2:
        raise ValueError('layout needs explicit daughter PDGs')
    for daughter in row['daughters']:
        _pdg(daughter)
    if 'quantity' in row and row['quantity'] not in ('branching_ratio', 'partial_width'):
        raise ValueError('explicit branching_ratio or partial_width column required')


def _channels(rows, extra):
    if type(rows) is not list or not rows:
        raise ValueError('nonempty explicit layout channels required')
    for row in rows:
        _channel(row, extra)
    if len({r['id'] for r in rows}) != len(rows) or len({tuple(sorted(r['daughters'])) for r in rows}) != len(rows):
        raise ValueError('distinct exclusive layout channels required')


def validate_format(contract, program, version, order):
    _keys(contract, ('schema_version', 'program', 'version', 'order', 'complete_input_schema_declared', 'card', 'layout'),
          label='program format')
    if type(contract['schema_version']) is not int or contract['schema_version'] != 1:
        raise ValueError('format schema_version 1 required')
    if contract['program'] != program or contract['version'] != version:
        raise ValueError('format program/version differs from model point')
    if contract['order'] != order:
        raise ValueError('format order differs from declared calculation order')
    if contract['complete_input_schema_declared'] is not True:
        raise ValueError('complete source-backed input schema must be declared')
    card = contract['card']
    _keys(card, ('filename', 'fields', 'template'), label='card format')
    _basename(card['filename'])
    if type(card['fields']) is not dict or not card['fields'] or type(card['template']) is not str:
        raise ValueError('explicit card fields and template required')
    for name, field in card['fields'].items():
        if type(name) is not str or not re.fullmatch('[A-Za-z0-9_.-]+', name):
            raise ValueError('ordinary flattened input name required')
        if type(field) is not dict:
            raise ValueError('field schema object required')
        if field.get('kind') == 'number':
            _keys(field, ('kind',), label='number field')
        elif field.get('kind') == 'enum':
            _keys(field, ('kind', 'tokens'), label='enum field')
            if type(field['tokens']) is not dict or not field['tokens']:
                raise ValueError('explicit enum-to-native-token map required')
            for key, token in field['tokens'].items():
                _text(key, 'enum value'); _text(token, 'native token')
                if any(c.isspace() for c in token) or '$' in token or '#' in token:
                    raise ValueError('single unambiguous native enum token required')
        else:
            raise ValueError('supported explicit number or enum input field required')
    placeholders = PLACEHOLDER.findall(card['template'])
    if set(placeholders) != set(card['fields']) or '$' in PLACEHOLDER.sub('', card['template']):
        raise ValueError('every input field must appear as a braced placeholder; no silent omission')
    layout = contract['layout']
    if type(layout) is not dict or layout.get('unit') != 'GeV':
        raise ValueError('explicit native layout width unit GeV required')
    kind = layout.get('kind')
    if kind == 'slha':
        _keys(layout, ('kind', 'unit', 'name', 'channels'), label='SLHA layout')
        _basename(layout['name']); _channels(layout['channels'], ())
        if layout['name'] == card['filename']:
            raise ValueError('native output may not overwrite its input card')
        return contract
    if kind not in ('column_tables', 'key_values'):
        raise ValueError('supported explicit output layout kind required')
    _keys(layout, ('kind', 'unit', 'files'), label='output layout')
    if type(layout['files']) is not list or not layout['files']:
        raise ValueError('nonempty output file layout required')
    names = []
    for file in layout['files']:
        if kind == 'column_tables':
            _keys(file, ('name', 'columns', 'skip_rows', 'mass_column', 'total_width_column', 'channels'),
                  label='column table layout')
            n = _integer(file['columns'], 'column count', 1)
            _integer(file['skip_rows'], 'header row count')
            columns = [_integer(file['mass_column'], 'mass column')]
            if file['total_width_column'] is not None:
                columns.append(_integer(file['total_width_column'], 'total width column'))
            _channels(file['channels'], ('column', 'quantity'))
            columns += [_integer(r['column'], 'channel column') for r in file['channels']]
            if any(c >= n for c in columns) or len(set(columns)) != len(columns):
                raise ValueError('distinct in-range mass, total and channel columns required')
        else:
            _keys(file, ('name', 'pdg', 'separator', 'mass_key', 'total_width_key', 'channels'), label='keyed layout')
            _pdg(file['pdg'])
            if file['separator'] not in ('=', ':'):
                raise ValueError('explicit keyed separator required')
            _channels(file['channels'], ('key', 'quantity'))
            keys = [file['mass_key'], file['total_width_key'], *[r['key'] for r in file['channels']]]
            for key in keys:
                _text(key, 'output key')
            if len(set(keys)) != len(keys):
                raise ValueError('distinct output keys required')
        names.append(_basename(file['name']))
    if len(set(names)) != len(names):
        raise ValueError('distinct output file names required')
    if card['filename'] in names:
        raise ValueError('native outputs may not overwrite their input card')
    return contract


def values(point):
    answer = {'ew_scheme': point['ew_scheme']}
    answer.update({'physics_inputs.' + k: v for k, v in point['physics_inputs'].items()})
    answer.update({'parameters.' + k: v for k, v in point['parameters'].items()})
    answer.update({f"scalars.{s['pdg']}.mass_GeV": s['mass_GeV'] for s in point['scalars']})
    return answer


def render(point, contract):
    validate_format(contract, point['program'], point['version'], point['order'])
    supplied = values(point)
    fields = contract['card']['fields']
    if set(supplied) != set(fields):
        raise ValueError('input schema must cover exactly every supplied physics, model, scheme and mass input')
    tokens = {}
    for name, value in supplied.items():
        schema = fields[name]
        if schema['kind'] == 'number':
            tokens[name] = format(_num(value, name), '.17g')
        else:
            if type(value) is not str or value not in schema['tokens']:
                raise ValueError('input ' + name + ' has no declared native encoding')
            tokens[name] = schema['tokens'][value]
    # string.Template does not support dotted names. Only the explicit braced
    # grammar above is replaced; supplied values cannot inject lines or code.
    return PLACEHOLDER.sub(lambda match: tokens[match.group(1)], contract['card']['template'])


def output_names(contract):
    layout = contract['layout']
    return [layout['name']] if layout['kind'] == 'slha' else [f['name'] for f in layout['files']]


def _float(token):
    try:
        value = float(token.replace('D', 'E').replace('d', 'e'))
    except (ValueError, AttributeError) as exc:
        raise ValueError('finite native numeric token required') from exc
    _num(value, 'native output value')
    if value == 0:
        from decimal import Decimal, InvalidOperation
        try:
            if Decimal(token.replace('D', 'E').replace('d', 'e')) != 0:
                raise ValueError('native numeric token underflows transport precision')
        except InvalidOperation as exc:
            raise ValueError('decimal native token required') from exc
    return value


def _column_rows(text, file, mass):
    rows = []
    for line in text.splitlines()[file['skip_rows']:]:
        content = line.split('#', 1)[0].strip()
        if not content:
            continue
        tokens = content.split()
        if len(tokens) != file['columns']:
            raise ValueError('native column count differs from supplied layout')
        numbers = [_float(x) for x in tokens]
        if numbers[file['mass_column']] == mass:
            rows.append(numbers)
    if len(rows) != 1:
        raise ValueError('exactly one native output row at requested mass required')
    return rows[0]


def _column_scalar(layout, outputs, scalar):
    totals, channels = [], []
    for file in layout['files']:
        row = _column_rows(outputs[file['name']], file, scalar['mass_GeV'])
        if file['total_width_column'] is not None:
            totals.append(row[file['total_width_column']])
        channels += [(c, row[c['column']], c['quantity']) for c in file['channels']]
    if not totals or any(t != totals[0] for t in totals):
        raise ValueError('explicit consistent native total width required')
    return totals[0], channels


def _keyed_scalar(layout, outputs, scalar):
    files = [f for f in layout['files'] if f['pdg'] == scalar['pdg']]
    if not files:
        raise ValueError('keyed layout lacks requested scalar')
    totals, channels = [], []
    for file in files:
        records = {}
        for line in outputs[file['name']].splitlines():
            content = line.split('#', 1)[0].strip()
            if not content:
                continue
            parts = content.split(file['separator'])
            if len(parts) != 2 or not parts[0].strip() or parts[0].strip() in records:
                raise ValueError('distinct unambiguous keyed native values required')
            records[parts[0].strip()] = _float(parts[1].strip())
        try:
            if records[file['mass_key']] != scalar['mass_GeV']:
                raise ValueError('exact native mass required')
            totals.append(records[file['total_width_key']])
            channels += [(c, records[c['key']], c['quantity']) for c in file['channels']]
        except KeyError as exc:
            raise ValueError('missing required keyed native value') from exc
    if any(t != totals[0] for t in totals):
        raise ValueError('consistent keyed native total width required')
    return totals[0], channels


def _slha_scalars(text, channels):
    result = {}; masses = {}; current = None; block = None
    mapping = {tuple(sorted(r['daughters'])): r for r in channels}
    for line in text.splitlines():
        tokens = line.split('#', 1)[0].split()
        if not tokens:
            continue
        if tokens[0].upper() == 'BLOCK':
            if len(tokens) < 2:
                raise ValueError('named SLHA BLOCK required')
            block = tokens[1].upper(); current = None
            continue
        if tokens[0].upper() == 'DECAY':
            if len(tokens) != 3:
                raise ValueError('SLHA DECAY header requires PDG and total width')
            try:
                pdg = _pdg(int(tokens[1]))
            except ValueError as exc:
                raise ValueError('SLHA integer parent PDG required') from exc
            if pdg in result:
                raise ValueError('duplicate SLHA DECAY block')
            current = result[pdg] = (_float(tokens[2]), [])
            block = None
            continue
        if block:
            if block == 'MASS':
                if len(tokens) != 2:
                    raise ValueError('SLHA MASS row requires PDG and mass')
                try:
                    pdg = _pdg(int(tokens[0]))
                except ValueError as exc:
                    raise ValueError('SLHA MASS integer PDG required') from exc
                if pdg in masses:
                    raise ValueError('duplicate SLHA mass identity')
                masses[pdg] = _float(tokens[1])
            continue
        if current is None or len(tokens) < 4:
            raise ValueError('native row outside a SLHA DECAY block')
        try:
            n = int(tokens[1]); daughters = [_pdg(int(x)) for x in tokens[2:]]
        except ValueError as exc:
            raise ValueError('SLHA integer daughter PDGs and multiplicity required') from exc
        if n != len(daughters) or n < 2:
            raise ValueError('SLHA daughter multiplicity differs from row')
        key = tuple(sorted(daughters))
        # Unselected scalar channels are retained as raw identities, then filtered.
        channel = mapping.get(key, {'id': None, 'daughters': daughters})
        current[1].append((channel, _float(tokens[0]), 'branching_ratio'))
    return result, masses


def parse(point, contract, outputs):
    from ravel.physics.higgs_decays import validate_table
    validate_format(contract, point['program'], point['version'], point['order'])
    if type(outputs) is not dict or set(outputs) != set(output_names(contract)) or any(type(v) is not str for v in outputs.values()):
        raise ValueError('exact supplied output file population required')
    layout = contract['layout']; scalars = []
    slha, masses = (_slha_scalars(outputs[layout['name']], layout['channels'])
                    if layout['kind'] == 'slha' else (None, {}))
    for scalar in point['scalars']:
        if layout['kind'] == 'column_tables':
            total, rows = _column_scalar(layout, outputs, scalar)
        elif layout['kind'] == 'key_values':
            total, rows = _keyed_scalar(layout, outputs, scalar)
        else:
            if scalar['pdg'] not in slha:
                raise ValueError('missing requested SLHA scalar')
            if scalar['pdg'] in masses and masses[scalar['pdg']] != scalar['mass_GeV']:
                raise ValueError('reported SLHA mass differs from requested scalar mass')
            total, rows = slha[scalar['pdg']]
        _num(total, 'native total width', positive=True)
        channels = []
        for c, value, quantity in rows:
            if c['id'] is None:
                raise ValueError('selected scalar channel has no supplied physical channel mapping')
            # The native quantity is transported unchanged; only the other is derived.
            width, ratio = (value * total, value) if quantity == 'branching_ratio' else (value, value / total)
            channels.append({'id': c['id'], 'daughters': list(c['daughters']),
                             'partial_width_GeV': width, 'branching_ratio': ratio,
                             'program': point['program']})
        scalars.append({**scalar, 'total_width_GeV': total, 'channels': channels})
    table = {'schema_version': 1, **{k: point[k] for k in ('program', 'version', 'order', 'ew_scheme')},
             'units': 'GeV', 'scalars': scalars, 'layout_qualified': False}
    return validate_table(table)
