"""Independent, standard-library-only replay of closed analysis witness bundles.

This file can be copied out of RAVEL and run directly. It imports no producer,
native kernel, ROOT library, or numerical package. Its scalar four-vector and
symmetric-eigenvalue formulas form a separate numerical implementation. Bundle
self-consistency does not authenticate its scientific source; callers may bind
the manifest to an externally retained digest.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys


def _pairs(items):
    output = {}
    for key, value in items:
        if key in output: raise ValueError('duplicate JSON key')
        output[key] = value
    return output


def _read(path):
    return json.loads(path.read_text(), object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON: ' + value)))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError('unknown or missing witness fields')


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value): raise ValueError('nonfinite or nonnumeric witness value')
    return float(value)


def _name(value):
    if not isinstance(value, str) or not value or value != value.strip(): raise ValueError('invalid witness name')
    return value


_E, _A, _D = (Fraction(1), Fraction(0)), (Fraction(0), Fraction(1)), (Fraction(0), Fraction(0))
_UNITS = {'1': (_D, 1.), 'GeV': (_E, 1.), 'MeV': (_E, .001), 'TeV': (_E, 1000.),
          'rad': (_A, 1.), 'sqrt(GeV)': ((Fraction(1, 2), Fraction(0)), 1.)}
_EXTRA = {'input': ('collection',), 'const': ('value', 'unit'), 'field': ('args', 'field'),
          'compare': ('args', 'comparison'), 'take': ('args', 'count'), 'leading': ('args', 'index')}
_UNARY = {'sort', 'take', 'leading', 'count', 'sum_pt', 'aplanarity', 'ossf_pairs', 'field',
          'pair_mass', 'sqrt', 'abs', 'not', 'defined'}
_BINARY = {'concat', 'mass', 'mt', 'mt_massless', 'delta_phi', 'min_dphi', 'best_pair', 'add', 'sub', 'mul', 'div',
           'min', 'max', 'compare', 'and', 'or'}


def _check_contract(c):
    _keys(c, ('schema_version', 'level', 'source', 'energy_unit', 'flags', 'response_evidence', 'weight_names'))
    if type(c['schema_version']) is not int or c['schema_version'] != 1 or c['level'] != 'reconstructed' or c['energy_unit'] != 'GeV':
        raise ValueError('unsupported object contract')
    _name(c['source'])
    _keys(c['flags'], ('electron', 'muon', 'jet'))
    for flags in c['flags'].values():
        if not isinstance(flags, dict): raise ValueError('invalid flags')
        bits = []
        for name, value in flags.items():
            _name(name)
            if type(value) is not int or not 0 < value < 2**30 or value & (value - 1): raise ValueError('invalid flag bit')
            bits.append(value)
        if len(set(bits)) != len(bits): raise ValueError('aliased working-point flags')
    if not isinstance(c['weight_names'], list) or not c['weight_names'] or len(set(c['weight_names'])) != len(c['weight_names']):
        raise ValueError('invalid weight names')
    if len(c['weight_names']) > 16: raise ValueError('moment resource bound: too many weight streams')
    for value in c['weight_names']: _name(value)
    if not isinstance(c['response_evidence'], list): raise ValueError('invalid response evidence')
    for value in c['response_evidence']: _name(value)


def _flag_masks(node, kind, contract):
    flags = node.get('flags', {'all': [], 'none': []})
    _keys(flags, ('all', 'none'))
    if kind not in contract['flags']:
        if flags != {'all': [], 'none': []}: raise ValueError('mixed collection cannot carry ID predicates')
        return 0, 0
    for names in flags.values():
        if not isinstance(names, list) or len(set(names)) != len(names) or any(n not in contract['flags'][kind] for n in names):
            raise ValueError('unknown or repeated ID flag')
    if set(flags['all']) & set(flags['none']): raise ValueError('contradictory flag request')
    return [sum(contract['flags'][kind][n] for n in flags[k]) for k in ('all', 'none')]


def _check_program(program, contract):
    _keys(program, ('schema_version', 'name', 'nodes', 'regions'), ('limits',))
    if type(program['schema_version']) is not int or program['schema_version'] != 1: raise ValueError('unsupported program')
    _name(program['name'])
    limits = program.get('limits', {'max_events': 10000, 'max_objects_per_event': 256, 'max_pairs_per_event': 8192})
    _keys(limits, ('max_events', 'max_objects_per_event', 'max_pairs_per_event'))
    for key, high in [('max_events', 100000), ('max_objects_per_event', 1024), ('max_pairs_per_event', 65536)]:
        if type(limits[key]) is not int or not 1 <= limits[key] <= high: raise ValueError('unsupported resource limit')
    if not isinstance(program['nodes'], list) or not 1 <= len(program['nodes']) <= 256: raise ValueError('invalid node count')
    types = {}
    for node in program['nodes']:
        if not isinstance(node, dict): raise ValueError('invalid node')
        op, nid = node.get('op'), _name(node.get('id'))
        if nid in types: raise ValueError('duplicate node')
        if op not in _UNARY | _BINARY | {'input', 'const', 'met', 'filter', 'overlap', 'overlap_vr', 'choose'}:
            raise ValueError('unsupported witness operation')
        required = ('id', 'op') + _EXTRA.get(op, () if op == 'met' else ('args',))
        optional = ('flags', 'pt_from') if op == 'overlap_vr' else ('flags',) if op in ('filter', 'overlap') else ()
        _keys(node, required, optional)
        args = node.get('args', [])
        if not isinstance(args, list) or any(not isinstance(k, str) or k not in types for k in args): raise ValueError('bad expression dependency')
        ts = [types[k] for k in args]
        if op in _UNARY and len(args) != 1: raise ValueError('unary arity')
        if op in _BINARY - {'concat', 'and', 'or'} and len(args) != 2: raise ValueError('binary arity')
        if op in ('and', 'or') and len(args) < 2: raise ValueError('logical arity')
        if op == 'input':
            if node['collection'] not in contract['flags']: raise ValueError('unknown collection')
            typ = ('collection', _D, node['collection'])
        elif op == 'met': typ = ('object', _D, 'met')
        elif op == 'const':
            _number(node['value'])
            if node['unit'] not in _UNITS: raise ValueError('unsupported unit')
            typ = ('scalar', _UNITS[node['unit']][0], None)
        elif op in ('filter', 'overlap', 'overlap_vr'):
            expected = 3 if op != 'overlap_vr' else 5
            if len(ts) != expected or ts[0][0] != 'collection': raise ValueError('bad collection operation')
            if op == 'filter':
                if ts[1][:2] != ('scalar', _E) or ts[2][:2] != ('scalar', _D): raise ValueError('filter dimension mismatch')
            elif ts[1][0] != 'collection' or ts[2][:2] != ('scalar', _D): raise ValueError('overlap dimension mismatch')
            if op == 'overlap_vr' and (ts[3][:2] != ('scalar', _D) or ts[4][:2] != ('scalar', _E) or node.get('pt_from', 'candidate') not in ('candidate', 'other')):
                raise ValueError('variable-radius dimension mismatch')
            _flag_masks(node, ts[0][2], contract)
            typ = ts[0]
        elif op == 'concat':
            if not ts or any(t[0] != 'collection' for t in ts): raise ValueError('concat type mismatch')
            kinds = {t[2] for t in ts}
            kind = next(iter(kinds)) if len(kinds) == 1 else 'lepton' if kinds <= {'electron', 'muon', 'lepton'} else 'particle'
            typ = ('collection', _D, kind)
        elif op in ('sort', 'take', 'leading', 'count', 'sum_pt', 'aplanarity', 'ossf_pairs'):
            if ts[0][0] != 'collection': raise ValueError('collection required')
            if op in ('take', 'leading'):
                value = node['count' if op == 'take' else 'index']
                if type(value) is not int or value < 0: raise ValueError('invalid exact index')
            if op == 'ossf_pairs' and ts[0][2] not in ('electron', 'muon', 'lepton'): raise ValueError('nonleptonic OSSF pair')
            typ = ts[0] if op in ('sort', 'take') else ('object', _D, ts[0][2]) if op == 'leading' else ('pairs', _D, None) if op == 'ossf_pairs' else ('scalar', _E if op == 'sum_pt' else _D, None)
        elif op == 'field':
            if ts[0][0] != 'object' or node['field'] not in ('pt', 'mass', 'eta', 'phi', 'charge'): raise ValueError('bad field')
            typ = ('scalar', _E if node['field'] in ('pt', 'mass') else _A if node['field'] == 'phi' else _D, None)
        elif op in ('mass', 'mt', 'mt_massless', 'delta_phi', 'min_dphi'):
            if ts[0][0] != 'object' or ts[1][0] != ('collection' if op == 'min_dphi' else 'object'): raise ValueError('bad kinematic types')
            if op in ('mt', 'mt_massless') and ts[1][2] != 'met': raise ValueError('transverse mass requires MET')
            typ = ('scalar', _A if op in ('delta_phi', 'min_dphi') else _E, None)
        elif op == 'best_pair':
            if ts[0][0] != 'pairs' or ts[1][:2] != ('scalar', _E): raise ValueError('bad pair choice')
            typ = ('pair', _D, None)
        elif op == 'pair_mass':
            if ts[0][0] != 'pair': raise ValueError('pair required')
            typ = ('scalar', _E, None)
        elif op in ('add', 'sub', 'mul', 'div', 'min', 'max', 'compare'):
            if any(t[0] != 'scalar' for t in ts): raise ValueError('scalar required')
            if op not in ('mul', 'div') and ts[0][1] != ts[1][1]: raise ValueError('incompatible expression dimensions')
            if op == 'compare':
                if node['comparison'] not in ('lt', 'le', 'gt', 'ge', 'eq', 'ne'): raise ValueError('unknown comparison')
                typ = ('predicate', _D, None)
            else:
                dimension = tuple(a+b if op == 'mul' else a-b for a,b in zip(ts[0][1], ts[1][1])) if op in ('mul', 'div') else ts[0][1]
                typ = ('scalar', dimension, None)
        elif op in ('sqrt', 'abs'):
            if ts[0][0] != 'scalar': raise ValueError('scalar required')
            typ = ('scalar', tuple(v/2 for v in ts[0][1]) if op == 'sqrt' else ts[0][1], None)
        elif op in ('and', 'or', 'not'):
            if any(t[0] != 'predicate' for t in ts): raise ValueError('predicate required')
            typ = ('predicate', _D, None)
        elif op == 'defined': typ = ('predicate', _D, None)
        else:
            if len(ts) != 3 or ts[0][0] != 'predicate' or ts[1] != ts[2]: raise ValueError('invalid conditional types')
            typ = ts[1]
        types[nid] = typ
    if not isinstance(program['regions'], list) or not 1 <= len(program['regions']) <= 128: raise ValueError('invalid regions')
    names = set()
    for region in program['regions']:
        _keys(region, ('name', 'cuts'))
        name = _name(region['name'])
        if name in names or not isinstance(region['cuts'], list) or not region['cuts'] or len(set(region['cuts'])) != len(region['cuts']): raise ValueError('invalid region cuts')
        if any(k not in types or types[k][0] != 'predicate' for k in region['cuts']): raise ValueError('unknown cut predicate')
        names.add(name)
    dimension = len(program['regions']) + sum(len(r['cuts']) for r in program['regions']) + 1
    if (dimension > 256 or len(contract['weight_names']) > 16
            or limits['max_events'] * dimension * dimension * len(contract['weight_names']) > 25_000_000):
        raise ValueError('moment resource bound exceeded')
    return limits, types


def _particles(event, contract, limits):
    _keys(event, ('event_id', 'group_id', 'weights', 'objects', 'met'))
    eid = _name(event['event_id'])
    _name(event['group_id'])
    if not isinstance(event['weights'], dict) or set(event['weights']) != set(contract['weight_names']): raise ValueError('weight population mismatch')
    for value in event['weights'].values(): _number(value)
    _keys(event['objects'], ('electron', 'muon', 'jet'))
    objects, lineage = {}, {}
    count = 0
    for kind, rows in event['objects'].items():
        if not isinstance(rows, list): raise ValueError('invalid object list')
        count += len(rows)
        objects[kind] = []
        for index, row in enumerate(rows):
            _keys(row, ('pt', 'eta', 'phi', 'mass', 'charge', 'idbits'))
            for key in ('pt', 'eta', 'phi', 'mass'): _number(row[key])
            if row['pt'] < 0 or row['mass'] < 0 or abs(row['eta']) > 20 or abs(row['phi']) > math.pi: raise ValueError('unsupported object domain')
            if type(row['charge']) is not int or row['charge'] not in (-1,0,1): raise ValueError('invalid charge')
            if type(row['idbits']) is not int or row['idbits'] < 0 or row['idbits'] & ~sum(contract['flags'][kind].values()): raise ValueError('invalid object ID bits')
            uid = _digest([eid, kind, index])
            objects[kind].append({**row, 'uid': uid, 'kind': kind})
            lineage[uid] = {'event_id': eid, 'collection': kind, 'index': index}
    if count > limits['max_objects_per_event']: raise ValueError('object bound exceeded')
    _keys(event['met'], ('pt', 'phi'))
    pt, phi = _number(event['met']['pt']), _number(event['met']['phi'])
    if pt < 0 or abs(phi) > math.pi: raise ValueError('invalid MET')
    uid = _digest([eid, 'met'])
    met = {'pt': pt, 'phi': phi, 'eta': 0., 'mass': 0., 'charge': 0, 'idbits': 0, 'uid': uid, 'kind': 'met'}
    lineage[uid] = {'event_id': eid, 'collection': 'met', 'index': 0}
    return objects, met, lineage


def _nearest(kind, x):
    """sin, cos or sinh of a binary64 argument, rounded to the nearest binary64 value.

    The IR declares these three functions correctly rounded, because the host library is
    not and its last bit differs between platforms. This replay sums the exact rational
    Taylor series: every partial sum is a fraction, the remainder is bounded by twice the
    next term once the terms shrink by half, and the sum is accepted when both ends of
    that bound convert to the same binary64 value.
    """
    if x == 0:
        return 1.0 if kind == 'cos' else x
    if x < 0:
        return _nearest(kind, -x) if kind == 'cos' else -_nearest(kind, -x)
    numerator, denominator = x.as_integer_ratio()
    square_n, square_d = numerator*numerator, denominator*denominator
    index = 0 if kind == 'cos' else 1
    # The partial sum and its last term share one denominator, so both stay exact integers over it.
    term, common = (1, 1) if kind == 'cos' else (numerator, denominator)
    total, sign = term, 1
    while True:
        index += 2
        scale = square_d*index*(index-1)
        term, total, common = term*square_n, total*scale, common*scale
        sign = sign if kind == 'sinh' else -sign
        total += sign*term
        # Wait until the terms shrink by half and the last one is far below the sum's last bit.
        if 2*square_n > square_d*(index+1)*(index+2) or term.bit_length()+110 > abs(total).bit_length():
            continue
        # |remainder| <= 2*|next term| <= 2*|this term|: both ends of that bound must agree.
        low, high = Fraction(total-2*term, common), Fraction(total+2*term, common)
        if float(low) == float(high):
            return float(low)


def _four(p):
    transverse = p['pt']
    px, py, pz = transverse * _nearest('cos', p['phi']), transverse * _nearest('sin', p['phi']), transverse * _nearest('sinh', p['eta'])
    # The IR specifies binary64 native four-vector order, including cancellation
    # in invariant mass. Independently reconstruct the vector in that order.
    momentum_squared = px*px + py*py + pz*pz
    return math.sqrt(momentum_squared + p['mass']*p['mass']), px, py, pz


def _mass(left, right):
    vector = [a+b for a,b in zip(_four(left), _four(right))]
    mass_squared = vector[0]*vector[0] - vector[1]*vector[1] - vector[2]*vector[2] - vector[3]*vector[3]
    # Legacy native semantics: a nonpositive computed mass square maps to zero.
    # Supplied particles have nonnegative rest masses; this is not a general
    # interpretation of physically spacelike vectors or a precision guarantee.
    return math.sqrt(mass_squared) if mass_squared > 0 else 0.


def _phi(a, b):
    return abs((a['phi'] - b['phi'] + math.pi) % (2*math.pi) - math.pi)


def _aplanarity(particles):
    if len(particles) < 2: return 0.
    vectors = [_four(p)[1:] for p in particles]
    denominator = sum(sum(x*x for x in p) for p in vectors)
    if denominator == 0: return 0.
    matrix = [[sum(p[i]*p[j] for p in vectors)/denominator for j in range(3)] for i in range(3)]
    # Jacobi rotations avoid acos endpoint sensitivity for nearly planar events.
    # This is independent of the producer's numpy.linalg.eigvalsh implementation.
    for _ in range(32):
        i,j = max(((0,1),(0,2),(1,2)), key=lambda pair:abs(matrix[pair[0]][pair[1]]))
        off = matrix[i][j]
        if abs(off) < 1e-15: break
        angle = .5*math.atan2(2*off,matrix[j][j]-matrix[i][i])
        cosine,sine = math.cos(angle),math.sin(angle)
        left,right = matrix[i][i],matrix[j][j]
        matrix[i][i] = cosine*cosine*left - 2*sine*cosine*off + sine*sine*right
        matrix[j][j] = sine*sine*left + 2*sine*cosine*off + cosine*cosine*right
        matrix[i][j] = matrix[j][i] = 0.
        for k in set(range(3))-{i,j}:
            a,b = matrix[k][i],matrix[k][j]
            matrix[k][i] = matrix[i][k] = cosine*a-sine*b
            matrix[k][j] = matrix[j][k] = sine*a+cosine*b
    return 1.5*min(matrix[i][i] for i in range(3))


def _node(node, values, objects, met, contract, limits):
    op = node['op']
    if op == 'input': return objects[node['collection']]
    if op == 'met': return met
    if op == 'const': return node['value'] * _UNITS[node['unit']][1]
    args = [values[k] for k in node['args']]
    if op == 'defined': return args[0] is not None
    if op == 'and': return False if False in args else None if None in args else True
    if op == 'or': return True if True in args else None if None in args else False
    if op == 'not': return None if args[0] is None else not args[0]
    if op == 'choose': return None if args[0] is None else args[1] if args[0] else args[2]
    if any(a is None for a in args): return None
    def guard(obj):
        required, excluded = _flag_masks(node, obj['kind'], contract)
        return obj['idbits'] & required == required and obj['idbits'] & excluded == 0
    if op == 'filter':
        if args[1] < 0 or args[2] <= 0: raise ValueError('invalid filter threshold')
        return [o for o in args[0] if o['pt'] >= args[1] and abs(o['eta']) < args[2] and guard(o)]
    if op in ('overlap', 'overlap_vr'):
        if args[2] <= 0 or (op == 'overlap_vr' and (args[3] <= 0 or args[4] < 0)): raise ValueError('invalid overlap radius')
        output = []
        for candidate in args[0]:
            drop = False
            for other in args[1]:
                if candidate['uid'] == other['uid'] or not guard(candidate): continue
                radius = args[2]
                if op == 'overlap_vr':
                    pt = (candidate if node.get('pt_from', 'candidate') == 'candidate' else other)['pt']
                    if pt == 0: return None
                    radius = min(args[3], args[2] + args[4]/pt)
                if math.hypot(candidate['eta']-other['eta'], _phi(candidate, other)) < radius:
                    drop = True
                    break
            if not drop: output.append(candidate)
        return output
    if op == 'concat':
        output = [o for coll in args for o in coll]
        if len({o['uid'] for o in output}) != len(output): raise ValueError('duplicate concat object')
        return output
    if op == 'sort': return sorted(args[0], key=lambda o: (-o['pt'], o['uid']))
    if op == 'take': return args[0][:node['count']]
    if op == 'leading': return args[0][node['index']] if len(args[0]) > node['index'] else None
    if op == 'count': return len(args[0])
    if op == 'sum_pt': return math.fsum(o['pt'] for o in args[0])
    if op == 'aplanarity': return _aplanarity(args[0])
    if op == 'field': return args[0][node['field']]
    if op == 'mass': return _mass(*args)
    if op == 'mt_massless': return math.sqrt(max(0., 2*args[0]['pt']*args[1]['pt']*(1-math.cos(args[0]['phi']-args[1]['phi']))))
    if op == 'mt':
        visible, missing = args
        transverse_energy = math.hypot(visible['pt'], visible['mass'])
        square = visible['mass']**2 + 2*(transverse_energy*missing['pt']-visible['pt']*missing['pt']*math.cos(visible['phi']-missing['phi']))
        return math.sqrt(max(0., square))
    if op == 'delta_phi': return _phi(*args)
    if op == 'min_dphi': return min(_phi(args[0], o) for o in args[1]) if args[1] else None
    if op == 'ossf_pairs':
        if len(args[0])*(len(args[0])-1)//2 > limits['max_pairs_per_event']: raise ValueError('pair bound exceeded')
        ordered = sorted(args[0], key=lambda o:o['uid'])
        return [(a,b) for i,a in enumerate(ordered) for b in ordered[i+1:] if a['kind'] == b['kind'] and a['charge']*b['charge'] < 0]
    if op == 'best_pair': return min(args[0], key=lambda pair: (abs(_mass(*pair)-args[1]), pair[0]['uid'], pair[1]['uid'])) if args[0] else None
    if op == 'pair_mass': return _mass(*args[0])
    if op == 'add': return args[0] + args[1]
    if op == 'sub': return args[0] - args[1]
    if op == 'mul': return args[0] * args[1]
    if op == 'div': return args[0] / args[1] if args[1] != 0 else None
    if op == 'sqrt': return math.sqrt(args[0]) if args[0] >= 0 else None
    if op == 'abs': return abs(args[0])
    if op == 'min': return min(args)
    if op == 'max': return max(args)
    if op == 'compare':
        left, right = args
        return {'lt': left < right, 'le': left <= right, 'gt': left > right, 'ge': left >= right, 'eq': left == right, 'ne': left != right}[node['comparison']]
    raise ValueError('unsupported operation')


def _serial(value):
    if isinstance(value, dict): return {'object_id': value['uid']}
    if isinstance(value, tuple): return {'pair': [_serial(v) for v in value]}
    if isinstance(value, list): return [_serial(v) for v in value]
    if value is not None and type(value) is not bool: _number(value)
    return value


def _equal(left, right):
    if type(left) is bool or type(right) is bool or left is None or right is None: return left is right
    if type(left) in (float, int) and type(right) in (float, int):
        return math.isclose(_number(left), _number(right), rel_tol=1e-10, abs_tol=1e-10)
    if isinstance(left, dict) and isinstance(right, dict): return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list): return len(left) == len(right) and all(_equal(a,b) for a,b in zip(left,right))
    return type(left) is type(right) and left == right


def _and(left, right):
    return False if left is False or right is False else None if left is None or right is None else True


def _verify(directory, expected_manifest_sha256):
    directory = Path(directory).absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)): raise ValueError('bundle may not traverse symlinks')
    manifest_path = directory/'manifest.json'
    if not manifest_path.is_file() or manifest_path.is_symlink(): raise ValueError('missing regular manifest')
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if expected_manifest_sha256 is not None and digest != expected_manifest_sha256: raise ValueError('externally bound manifest digest differs')
    manifest = _read(manifest_path)
    _keys(manifest, ('schema_version','files'))
    expected = {'program.json','contract.json','events.json','trace.json','result.json'}
    if type(manifest['schema_version']) is not int or manifest['schema_version'] != 1 or not isinstance(manifest['files'],dict) or set(manifest['files']) not in (expected, expected | {'verify.py'}):
        raise ValueError('bundle inventory differs')
    inventory = {p.name for p in directory.iterdir()}
    if inventory - set(manifest['files']) - {'manifest.json', 'verification.json'}: raise ValueError('unmanifested bundle entry')
    for name, checksum in manifest['files'].items():
        path = directory/name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum: raise ValueError('bundle byte custody differs: ' + name)
    program, contract, events, trace, result = [_read(directory/name) for name in ('program.json','contract.json','events.json','trace.json','result.json')]
    _check_contract(contract)
    limits, types = _check_program(program, contract)
    if not isinstance(events,list) or not events or len(events) > limits['max_events'] or not isinstance(trace,list): raise ValueError('invalid full population')
    plan = result.get('compiled_plan', {})
    if plan.get('program_sha256') != _digest(program) or plan.get('contract_sha256') != _digest(contract) or plan.get('limits') != limits or plan.get('regions') != program['regions']:
        raise ValueError('compiled plan binding differs')
    expected_nodes = [{**node,'type':{'shape': types[node['id']][0], 'dimension':[str(v) for v in types[node['id']][1]], 'kind':types[node['id']][2]}} for node in program['nodes']]
    if plan.get('nodes') != expected_nodes: raise ValueError('compiled expression/type differs')
    actual = {}
    for row in trace:
        _keys(row, ('event_id','group_id','weights','object_lineage','nodes','cutflow','regions'))
        eid = _name(row['event_id'])
        if eid in actual: raise ValueError('duplicate witness event')
        actual[eid] = row
    if len(actual) != len(events): raise ValueError('witness denominator differs')
    seen, groups = set(), {}
    regions = [r['name'] for r in program['regions']]
    weights = contract['weight_names']
    cells = [(r['name'], cut) for r in program['regions'] for cut in r['cuts']]
    raw = dict.fromkeys(regions,0)
    overlap = {r:dict.fromkeys(regions,0) for r in regions}
    cut_counts = {cell:dict.fromkeys(('passed','failed','undefined','not_reached'),0) for cell in cells}
    dimension = len(regions)+len(cells)+1
    for event in events:
        objects, met, lineage = _particles(event,contract,limits)
        eid = event['event_id']
        if eid in seen or eid not in actual: raise ValueError('missing or duplicate original event')
        seen.add(eid)
        row, values = actual[eid], {}
        if row['weights'] != event['weights'] or row['group_id'] != event['group_id'] or row['object_lineage'] != lineage: raise ValueError('event identity/weight/object lineage differs: ' + eid)
        if set(row['nodes']) != set(types): raise ValueError('incomplete node population')
        for node in program['nodes']:
            value = _node(node, values, objects, met, contract, limits)
            values[node['id']] = value
            expected_value = {'status': 'undefined' if value is None else 'defined','value':_serial(value)}
            if not _equal(row['nodes'][node['id']], expected_value): raise ValueError('first divergent node: ' + eid + '/' + node['id'])
        selected, cuts, masks = [], {}, {}
        for region in program['regions']:
            prefix, reached, rows = True, True, []
            for cut in region['cuts']:
                value = values[cut]
                status = 'not_reached' if not reached else 'undefined' if value is None else 'passed' if value else 'failed'
                prefix = _and(prefix,value)
                cut_counts[(region['name'],cut)][status] += 1
                rows.append({'predicate':cut,'value':value,'status':status,'cumulative':prefix})
                masks[(region['name'],cut)] = prefix
                reached = reached and value is True
            cuts[region['name']] = rows
            if prefix is True: selected.append(region['name'])
        if row['cutflow'] != cuts or row['regions'] != selected: raise ValueError('predicate cascade or membership differs: ' + eid)
        terms = groups.setdefault(event['group_id'], {w:[] for w in weights})
        for region in selected:
            raw[region] += 1
            for other in selected: overlap[region][other] += 1
        membership = [r in selected for r in regions] + [masks[c] is True for c in cells] + [True]
        for w in weights:
            terms[w].append(tuple(event['weights'][w]*mask for mask in membership))
    groups = {name:{w:[math.fsum(row[i] for row in terms[w]) for i in range(dimension)] for w in weights}
              for name, terms in groups.items()}
    sums = {w:[math.fsum(g[w][i] for g in groups.values()) for i in range(dimension)] for w in weights}
    moments = {w:[[math.fsum(g[w][i]*g[w][j] for g in groups.values()) for j in range(dimension)] for i in range(dimension)] for w in weights}
    cutflow = {}
    for region in program['regions']:
        rows = []
        for cut in region['cuts']:
            index = len(regions)+cells.index((region['name'],cut))
            rows.append({'predicate':cut,**cut_counts[(region['name'],cut)],
                         'cumulative_sumw':{w:sums[w][index] for w in weights},
                         'cumulative_group_second_moment':{w:moments[w][index][index] for w in weights}})
        cutflow[region['name']] = rows
    expected_result = {'schema_version':1,'status':'passed','physics_validated':False,'events':len(events),'independent_groups':len(groups),
                       'region_names':regions,'weight_names':weights,'sumw_all_events':[sums[w][-1] for w in weights],
                       'raw_selected':raw,'region_overlap_counts':overlap,'cutflow':cutflow,
                       'precision_status':{r:'zero_selected_precision_unresolved' if raw[r]==0 else 'conditional_group_moments_only' for r in regions},
                       'yields':{w:sums[w][:len(regions)] for w in weights},
                       'covariance':{w:[r[:len(regions)] for r in moments[w][:len(regions)]] for w in weights},
                       'cutflow_covariance_order':[list(c) for c in cells],
                       'cutflow_covariance':{w:[r[len(regions):-1] for r in moments[w][len(regions):-1]] for w in weights}}
    for key, value in expected_result.items():
        if key not in result or not _equal(result[key],value): raise ValueError('independently accumulated result differs: ' + key)
    return {'status':'passed','passed':True,'physics_validated':False,'events':len(events),
            'checked_nodes':len(events)*len(types),'manifest_sha256':digest,
            'source_custody':'external_manifest_digest_matched' if expected_manifest_sha256 is not None else 'bundle_self_consistency_only',
            'scope':'Independent closed-program same-event numerical/decision replay and group moments',
            'limitations':['No detector calibration, experimental cutflow or arbitrary-program equivalence is established.',
                           'Scalar node comparison tolerance is 1e-10 absolute/relative; predicate decisions are exact.',
                           'Invariant mass replays ordered native binary64 arithmetic, including zero for nonpositive computed mass square; it is not an exact continuum or cancellation-error certificate.',
                           'An unanchored self-consistent bundle does not authenticate its scientific inputs.']}


def verify_bundle(directory, expected_manifest_sha256=None):
    """Return an explicit failure and first divergence instead of trusting a producer report."""
    try:
        return _verify(directory, expected_manifest_sha256)
    except (ValueError, OSError, KeyError, TypeError, OverflowError, ZeroDivisionError, RecursionError) as exc:
        return {'status':'failed','passed':False,'physics_validated':False,'error':str(exc),
                'scope':'Independent closed-program witness verification'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--manifest-sha256')
    args = parser.parse_args(argv)
    result = verify_bundle(args.bundle,args.manifest_sha256)
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0 if result['passed'] else 3


if __name__ == '__main__':
    sys.exit(main())
