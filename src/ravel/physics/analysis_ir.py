"""Closed reconstructed-event analysis programs and complete decision witnesses.

This extends the fixed native-selection vocabulary with compositional collection,
pairing and scalar expressions. It does not translate arbitrary C++, calibrate
objects, or certify an experimental analysis. The independent bundle checker
lives in validation.analysis_witness and does not import this module.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import sys
from pathlib import Path

from . import sa_native_core as core


ENERGY, ANGLE, ONE = (Fraction(1), Fraction(0)), (Fraction(0), Fraction(1)), (Fraction(0), Fraction(0))
UNITS = {'1': (ONE, 1.), 'GeV': (ENERGY, 1.), 'MeV': (ENERGY, .001),
         'TeV': (ENERGY, 1000.), 'rad': (ANGLE, 1.), 'sqrt(GeV)': ((Fraction(1, 2), Fraction(0)), 1.)}
OPS = {'lt': lambda a, b: a < b, 'le': lambda a, b: a <= b,
       'gt': lambda a, b: a > b, 'ge': lambda a, b: a >= b,
       'eq': lambda a, b: a == b, 'ne': lambda a, b: a != b}
DEFAULT_LIMITS = {'max_events': 10000, 'max_objects_per_event': 256, 'max_pairs_per_event': 8192}
MAX_MOMENT_COORDINATES, MAX_WEIGHT_STREAMS, MAX_MOMENT_WORK = 256, 16, 25_000_000


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError('unknown or missing fields: expected ' + ', '.join(required))


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite nonboolean number required')
    return float(value)


def _name(value):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError('nonempty trimmed name required')
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _type(shape, dimension=ONE, kind=None):
    return (shape, dimension, kind)


def _flags(node, kind, contract):
    flags = node.get('flags', {'all': [], 'none': []})
    _keys(flags, ('all', 'none'))
    if kind not in contract['flags']:
        if flags != {'all': [], 'none': []}:
            raise ValueError('ID predicates require a homogeneous declared collection')
        return 0, 0
    for names in flags.values():
        if not isinstance(names, list) or len(set(names)) != len(names) or any(n not in contract['flags'][kind] for n in names):
            raise ValueError('undeclared or duplicate working-point flag')
    if set(flags['all']) & set(flags['none']):
        raise ValueError('working point cannot be required and excluded')
    return tuple(sum(contract['flags'][kind][n] for n in flags[key]) for key in ('all', 'none'))


def compile_program(program, object_contract):
    """Validate a bounded topological expression program and infer every node type."""
    from .reconstructed_events import object_contract as check_contract
    contract = check_contract(deepcopy(object_contract))
    _keys(program, ('schema_version', 'name', 'nodes', 'regions'), ('limits',))
    if type(program['schema_version']) is not int or program['schema_version'] != 1:
        raise ValueError('unsupported analysis program schema')
    _name(program['name'])
    limits = deepcopy(program.get('limits', DEFAULT_LIMITS))
    _keys(limits, tuple(DEFAULT_LIMITS))
    for key, value in limits.items():
        if type(value) is not int or not 1 <= value <= {'max_events': 100000, 'max_objects_per_event': 1024, 'max_pairs_per_event': 65536}[key]:
            raise ValueError('unsupported declared resource bound: ' + key)
    nodes = program['nodes']
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 256:
        raise ValueError('one to 256 program nodes required')
    types, lowered = {}, []
    for original in nodes:
        if not isinstance(original, dict):
            raise ValueError('node must be an object')
        node = deepcopy(original)
        nid, op = _name(node.get('id')), node.get('op')
        if nid in types:
            raise ValueError('duplicate node: ' + nid)
        if op == 'input':
            _keys(node, ('id', 'op', 'collection'))
            if node['collection'] not in ('electron', 'muon', 'jet'):
                raise ValueError('unsupported input collection')
            typ = _type('collection', kind=node['collection'])
        elif op == 'met':
            _keys(node, ('id', 'op'))
            typ = _type('object', kind='met')
        elif op == 'const':
            _keys(node, ('id', 'op', 'value', 'unit'))
            _number(node['value'])
            if node['unit'] not in UNITS:
                raise ValueError('unsupported literal unit')
            typ = _type('scalar', UNITS[node['unit']][0])
        else:
            args = node.get('args')
            if not isinstance(args, list) or any(not isinstance(a, str) or a not in types for a in args):
                raise ValueError('arguments must reference previous nodes; cycles and forward references are forbidden')
            ts = [types[a] for a in args]
            def shapes(expected):
                if len(ts) != len(expected) or any(t[0] not in choices for t, choices in zip(ts, expected)):
                    raise ValueError('wrong argument types for ' + str(op))
            if op == 'filter':
                _keys(node, ('id', 'op', 'args'), ('flags',))
                shapes(({'collection'}, {'scalar'}, {'scalar'}))
                if ts[1][1] != ENERGY or ts[2][1] != ONE:
                    raise ValueError('filter needs energy pT and dimensionless eta')
                _flags(node, ts[0][2], contract)
                typ = ts[0]
            elif op in ('overlap', 'overlap_vr'):
                _keys(node, ('id', 'op', 'args'), ('flags', 'pt_from') if op == 'overlap_vr' else ('flags',))
                shapes(({'collection'}, {'collection'}, {'scalar'}) if op == 'overlap' else
                       ({'collection'}, {'collection'}, {'scalar'}, {'scalar'}, {'scalar'}))
                if ts[2][1] != ONE or (op == 'overlap_vr' and (ts[3][1] != ONE or ts[4][1] != ENERGY)):
                    raise ValueError('overlap radii are dimensionless; variable-radius scale is energy')
                if op == 'overlap_vr' and node.get('pt_from', 'candidate') not in ('candidate', 'other'):
                    raise ValueError('invalid variable-radius pT source')
                _flags(node, ts[0][2], contract)
                typ = ts[0]
            elif op == 'concat':
                _keys(node, ('id', 'op', 'args'))
                if not ts or any(t[0] != 'collection' for t in ts):
                    raise ValueError('concat needs collections')
                kinds = {t[2] for t in ts}
                kind = next(iter(kinds)) if len(kinds) == 1 else ('lepton' if kinds <= {'electron', 'muon', 'lepton'} else 'particle')
                typ = _type('collection', kind=kind)
            elif op in ('sort', 'take', 'leading', 'count', 'sum_pt', 'aplanarity', 'ossf_pairs'):
                _keys(node, ('id', 'op', 'args'), ('count',) if op == 'take' else ('index',) if op == 'leading' else ())
                shapes(({'collection'},))
                if op in ('take', 'leading') and (type(node.get('count' if op == 'take' else 'index')) is not int or node.get('count' if op == 'take' else 'index') < 0):
                    raise ValueError('exact nonnegative count/index required')
                if op == 'ossf_pairs' and ts[0][2] not in ('electron', 'muon', 'lepton'):
                    raise ValueError('OSSF pairing requires leptons')
                typ = ts[0] if op in ('sort', 'take') else _type('object', kind=ts[0][2]) if op == 'leading' else _type('pairs') if op == 'ossf_pairs' else _type('scalar', ENERGY if op == 'sum_pt' else ONE)
            elif op == 'field':
                _keys(node, ('id', 'op', 'args', 'field'))
                shapes(({'object'},))
                if node['field'] not in ('pt', 'eta', 'phi', 'mass', 'charge'):
                    raise ValueError('unsupported object field')
                typ = _type('scalar', ENERGY if node['field'] in ('pt', 'mass') else ANGLE if node['field'] == 'phi' else ONE)
            elif op in ('mass', 'mt', 'mt_massless', 'delta_phi', 'min_dphi'):
                _keys(node, ('id', 'op', 'args'))
                shapes(({'object'}, {'collection'} if op == 'min_dphi' else {'object'}))
                if op in ('mt', 'mt_massless') and ts[1][2] != 'met':
                    raise ValueError('transverse mass requires a MET second argument')
                typ = _type('scalar', ANGLE if op in ('delta_phi', 'min_dphi') else ENERGY)
            elif op == 'best_pair':
                _keys(node, ('id', 'op', 'args'))
                shapes(({'pairs'}, {'scalar'}))
                if ts[1][1] != ENERGY:
                    raise ValueError('pair target mass must have energy units')
                typ = _type('pair')
            elif op == 'pair_mass':
                _keys(node, ('id', 'op', 'args'))
                shapes(({'pair'},))
                typ = _type('scalar', ENERGY)
            elif op in ('add', 'sub', 'mul', 'div', 'min', 'max'):
                _keys(node, ('id', 'op', 'args'))
                shapes(({'scalar'}, {'scalar'}))
                if op in ('add', 'sub', 'min', 'max') and ts[0][1] != ts[1][1]:
                    raise ValueError('incompatible dimensions for ' + op)
                dim = tuple(a+b if op == 'mul' else a-b for a, b in zip(ts[0][1], ts[1][1])) if op in ('mul', 'div') else ts[0][1]
                typ = _type('scalar', dim)
            elif op in ('sqrt', 'abs'):
                _keys(node, ('id', 'op', 'args'))
                shapes(({'scalar'},))
                typ = _type('scalar', tuple(d/2 for d in ts[0][1]) if op == 'sqrt' else ts[0][1])
            elif op == 'compare':
                _keys(node, ('id', 'op', 'args', 'comparison'))
                shapes(({'scalar'}, {'scalar'}))
                if ts[0][1] != ts[1][1] or node['comparison'] not in OPS:
                    raise ValueError('comparison requires matching dimensions and a supported comparator')
                typ = _type('predicate')
            elif op in ('and', 'or', 'not'):
                _keys(node, ('id', 'op', 'args'))
                if (len(ts) != 1 if op == 'not' else len(ts) < 2) or any(t[0] != 'predicate' for t in ts):
                    raise ValueError('boolean operations require predicate arguments')
                typ = _type('predicate')
            elif op == 'defined':
                _keys(node, ('id', 'op', 'args'))
                if len(ts) != 1:
                    raise ValueError('defined requires one argument')
                typ = _type('predicate')
            elif op == 'choose':
                _keys(node, ('id', 'op', 'args'))
                if len(ts) != 3 or ts[0][0] != 'predicate' or ts[1] != ts[2]:
                    raise ValueError('choose needs a predicate and two identically typed alternatives')
                typ = ts[1]
            else:
                raise ValueError('unsupported analysis operation: ' + str(op))
        types[nid] = typ
        lowered.append({**node, 'type': {'shape': typ[0], 'dimension': [str(x) for x in typ[1]], 'kind': typ[2]}})
    regions = program['regions']
    if not isinstance(regions, list) or not 1 <= len(regions) <= 128:
        raise ValueError('one to 128 named regions required')
    seen = set()
    for region in regions:
        _keys(region, ('name', 'cuts'))
        name = _name(region['name'])
        if name in seen or not isinstance(region['cuts'], list) or not region['cuts'] or len(set(region['cuts'])) != len(region['cuts']):
            raise ValueError('duplicate region or empty/duplicate cuts')
        if any(c not in types or types[c][0] != 'predicate' for c in region['cuts']):
            raise ValueError('region cuts must name predicate nodes')
        seen.add(name)
    # Dense covariance includes every cut prefix, all regions and denominator.
    # Bound declared worst-case independent groups before kernels or allocation.
    dimension = len(regions) + sum(len(r['cuts']) for r in regions) + 1
    streams = len(contract['weight_names'])
    if (dimension > MAX_MOMENT_COORDINATES or streams > MAX_WEIGHT_STREAMS
            or limits['max_events'] * dimension * dimension * streams > MAX_MOMENT_WORK):
        raise ValueError('moment resource bound exceeded: at most 256 coordinates, 16 weight streams and 25000000 declared group-cell products')
    return {'schema_version': 1, 'program_sha256': _digest(program), 'contract_sha256': _digest(contract),
            'name': program['name'], 'nodes': lowered, 'regions': deepcopy(regions), 'limits': limits,
            'semantics': {'overlap': 'ordered eta-phi deltaR, strict radius, candidate ID guard',
                          'sort': 'descending pT, stable original object ID for equal pT',
                          'undefined': 'null propagates; only true accepts; false dominates AND, true dominates OR',
                          'pair_choice': 'closest invariant mass, ordered stable object IDs for ties'}}


def _rounded(numerator, bits):
    """The binary64 value nearest to ``numerator / 2**bits`` (integer true division rounds correctly)."""
    return numerator / (1 << bits)


def _series(x, kind):
    """Correctly rounded sin, cos or sinh of a binary64 argument, from integer arithmetic alone.

    The host mathematical library is not correctly rounded for these functions and differs
    between platforms in the last bit, which cancellation in an invariant mass magnifies. The
    Taylor series is summed in fixed point with enough bits that the truncation error is far
    below one part in 2**100 of the result, and the working precision is doubled should the
    result ever lie that close to a rounding boundary. The value is therefore the same on
    every platform.
    """
    if x == 0 or abs(x) < 2.0**-27:
        # Below this the series differs from x (or from one) by less than a quarter of a unit in the last place.
        return 1.0 if kind == 'cos' else x
    if x < 0:
        # Every term is kept nonnegative, so each truncated quotient reaches zero; cos is even, the others odd.
        return _series(-x, kind) if kind == 'cos' else -_series(-x, kind)
    bits = 192 + 3*int(x)
    numerator, denominator = x.as_integer_ratio()
    while True:
        scaled = numerator*(1 << bits)//denominator            # exact: the denominator divides 2**bits here
        square = scaled*scaled >> bits
        term = (1 << bits) if kind == 'cos' else scaled
        total, index = term, 0 if kind == 'cos' else 1
        while term:
            index += 2
            term = (term*square >> bits)//(index*(index-1))
            total += term if kind == 'sinh' or index % 4 in (0, 1) else -term
        guard = (abs(total) >> 100)+1
        low, high = _rounded(total-guard, bits), _rounded(total+guard, bits)
        if low == high:
            return low
        bits *= 2


def _four_vector(pt, eta, phi, mass):
    """Components and energy in the declared binary64 order, identical on every platform."""
    px, py, pz = pt*_series(phi, 'cos'), pt*_series(phi, 'sin'), pt*_series(eta, 'sinh')
    return px, py, pz, math.sqrt(px*px+py*py+pz*pz+mass*mass)


def _object(pt, eta, phi, mass, charge, idbits, typ):
    """The kernel's object with the four-vector of the declared arithmetic."""
    obj = core.Obj(pt, eta, phi, mass, charge, idbits, typ)
    obj.px, obj.py, obj.pz, obj.E = _four_vector(obj.pt, obj.eta, obj.phi, obj.m)
    return obj


@dataclass(frozen=True)
class Particle:
    uid: str
    kind: str
    obj: core.Obj


def _read_event(event, contract, limits):
    _keys(event, ('event_id', 'group_id', 'weights', 'objects', 'met'))
    eid, gid = _name(event['event_id']), _name(event['group_id'])
    if set(event['weights']) != set(contract['weight_names']):
        raise ValueError('missing or extra event weights')
    for value in event['weights'].values():
        _number(value)
    _keys(event['objects'], ('electron', 'muon', 'jet'))
    collections, lineage = {}, {}
    count = 0
    for typ, kind in enumerate(('electron', 'muon', 'jet')):
        rows = event['objects'][kind]
        if not isinstance(rows, list):
            raise ValueError('object collections must be arrays')
        count += len(rows)
        collections[kind] = []
        for i, row in enumerate(rows):
            _keys(row, ('pt', 'eta', 'phi', 'mass', 'charge', 'idbits'))
            vals = {k: _number(row[k]) for k in ('pt', 'eta', 'phi', 'mass')}
            if vals['pt'] < 0 or vals['mass'] < 0 or abs(vals['eta']) > 20 or abs(vals['phi']) > math.pi:
                raise ValueError('object outside supported numerical domain')
            if type(row['charge']) is not int or row['charge'] not in (-1, 0, 1):
                raise ValueError('unsupported object charge')
            mask = sum(contract['flags'][kind].values())
            if type(row['idbits']) is not int or row['idbits'] < 0 or row['idbits'] & ~mask:
                raise ValueError('object carries undeclared ID flags')
            uid = _digest([eid, kind, i])
            particle = Particle(uid, kind, _object(vals['pt'], vals['eta'], vals['phi'], vals['mass'], row['charge'], row['idbits'], typ))
            collections[kind].append(particle)
            lineage[uid] = {'event_id': eid, 'collection': kind, 'index': i}
    if count > limits['max_objects_per_event']:
        raise ValueError('object bound exceeded; truncation is forbidden')
    _keys(event['met'], ('pt', 'phi'))
    pt, phi = _number(event['met']['pt']), _number(event['met']['phi'])
    if pt < 0 or abs(phi) > math.pi:
        raise ValueError('MET outside supported numerical domain')
    uid = _digest([eid, 'met'])
    met = Particle(uid, 'met', _object(pt, 0, phi, 0, 0, 0, 6))
    lineage[uid] = {'event_id': eid, 'collection': 'met', 'index': 0}
    return collections, met, lineage


def _guard(particle, node, contract):
    required, excluded = _flags(node, particle.kind, contract)
    bits = particle.obj.idbits
    return bits & required == required and bits & excluded == 0


def _evaluate(node, values, collections, met, contract, limits):
    op = node['op']
    if op == 'input': return collections[node['collection']]
    if op == 'met': return met
    if op == 'const': return float(node['value']) * UNITS[node['unit']][1]
    a = [values[k] for k in node['args']]
    if op == 'defined': return a[0] is not None
    if op == 'and': return False if False in a else None if None in a else True
    if op == 'or': return True if True in a else None if None in a else False
    if op == 'not': return None if a[0] is None else not a[0]
    if op == 'choose': return None if a[0] is None else a[1] if a[0] else a[2]
    if any(x is None for x in a): return None
    if op == 'filter':
        if a[1] < 0 or a[2] <= 0: raise ValueError('invalid filter threshold')
        kept = core.filterObjects([p.obj for p in a[0]], a[1], a[2])
        survivors = {id(p) for p in kept}
        return [p for p in a[0] if id(p.obj) in survivors and _guard(p, node, contract)]
    if op in ('overlap', 'overlap_vr'):
        if a[2] <= 0 or (op == 'overlap_vr' and (a[3] <= 0 or a[4] < 0)):
            raise ValueError('invalid overlap radius')
        output = []
        for candidate in a[0]:
            removed = False
            for other in a[1]:
                if candidate.uid == other.uid or not _guard(candidate, node, contract): continue
                radius = a[2]
                if op == 'overlap_vr':
                    pt = candidate.obj.pt if node.get('pt_from', 'candidate') == 'candidate' else other.obj.pt
                    if pt == 0: return None
                    radius = min(a[3], a[2] + a[4] / pt)
                if candidate.obj.deltaR(other.obj) < radius:
                    removed = True
                    break
            if not removed: output.append(candidate)
        return output
    if op == 'concat':
        out = [p for coll in a for p in coll]
        if len({p.uid for p in out}) != len(out): raise ValueError('concat would duplicate an object')
        return out
    if op == 'sort': return sorted(a[0], key=lambda p: (-p.obj.pt, p.uid))
    if op == 'take': return a[0][:node['count']]
    if op == 'leading': return a[0][node['index']] if len(a[0]) > node['index'] else None
    if op == 'count': return len(a[0])
    if op == 'sum_pt': return math.fsum(p.obj.pt for p in a[0])
    if op == 'aplanarity': return core.aplanarity([p.obj for p in a[0]])
    if op == 'field': return getattr(a[0].obj, 'm' if node['field'] == 'mass' else node['field'])
    if op == 'mass': return core.invmass(a[0].obj, a[1].obj)
    if op == 'mt_massless': return core.calcMT(a[0].obj, a[1].obj)
    if op == 'mt':
        visible, met = a[0].obj, a[1].obj
        square = visible.m*visible.m + 2*(math.hypot(visible.pt, visible.m)*met.pt-visible.pt*met.pt*math.cos(visible.phi-met.phi))
        return math.sqrt(max(0., square))
    if op == 'delta_phi': return abs(a[0].obj.deltaPhi(a[1].obj))
    if op == 'min_dphi': return core.minDphi(a[0].obj, [p.obj for p in a[1]]) if a[1] else None
    if op == 'ossf_pairs':
        if len(a[0]) * (len(a[0]) - 1) // 2 > limits['max_pairs_per_event']:
            raise ValueError('pair bound exceeded; truncation is forbidden')
        ordered = sorted(a[0], key=lambda p: p.uid)
        return [(left, right) for i, left in enumerate(ordered) for right in ordered[i+1:]
                if left.kind == right.kind and left.obj.charge * right.obj.charge < 0]
    if op == 'best_pair': return min(a[0], key=lambda pair: (abs(core.invmass(pair[0].obj, pair[1].obj) - a[1]), pair[0].uid, pair[1].uid)) if a[0] else None
    if op == 'pair_mass': return core.invmass(a[0][0].obj, a[0][1].obj)
    if op == 'add': return a[0] + a[1]
    if op == 'sub': return a[0] - a[1]
    if op == 'mul': return a[0] * a[1]
    if op == 'div': return a[0] / a[1] if a[1] != 0 else None
    if op == 'sqrt': return math.sqrt(a[0]) if a[0] >= 0 else None
    if op == 'abs': return abs(a[0])
    if op == 'min': return min(a)
    if op == 'max': return max(a)
    if op == 'compare': return OPS[node['comparison']](a[0], a[1])
    raise ValueError('unreachable unsupported operation')


def _serialize(value):
    if isinstance(value, Particle): return {'object_id': value.uid}
    if isinstance(value, tuple): return {'pair': [_serialize(v) for v in value]}
    if isinstance(value, list): return [_serialize(v) for v in value]
    if value is not None and type(value) is not bool and not math.isfinite(value):
        raise ValueError('nonfinite expression result')
    return value


def _and(left, right):
    return False if left is False or right is False else None if left is None or right is None else True


def evaluate_program(program, object_contract, events):
    """Execute a typed plan; retain every rejected/zero/signed-weight input event."""
    plan = compile_program(program, object_contract)
    contract = deepcopy(object_contract)
    if not isinstance(events, list) or not events or len(events) > plan['limits']['max_events']:
        raise ValueError('nonempty event population within declared bound required')
    seen, decisions = set(), []
    regions = [r['name'] for r in plan['regions']]
    names = contract['weight_names']
    cells = [(r['name'], p) for r in plan['regions'] for p in r['cuts']]
    group_vectors = {}
    raw = dict.fromkeys(regions, 0)
    overlap = {r: dict.fromkeys(regions, 0) for r in regions}
    cut_counts = {cell: {'passed': 0, 'failed': 0, 'undefined': 0, 'not_reached': 0} for cell in cells}
    for event in events:
        collections, met, lineage = _read_event(event, contract, plan['limits'])
        eid, gid = event['event_id'], event['group_id']
        if eid in seen: raise ValueError('duplicate event identifier')
        seen.add(eid)
        values = {}
        for node in plan['nodes']:
            value = _evaluate(node, values, collections, met, contract, plan['limits'])
            _serialize(value)
            values[node['id']] = value
        selected, cuts, mask_cells = [], {}, {}
        for region in plan['regions']:
            prefix, reached, rows = True, True, []
            for predicate in region['cuts']:
                decision = values[predicate]
                status = 'not_reached' if not reached else 'undefined' if decision is None else 'passed' if decision else 'failed'
                cut_counts[(region['name'], predicate)][status] += 1
                prefix = _and(prefix, decision)
                rows.append({'predicate': predicate, 'value': decision, 'status': status, 'cumulative': prefix})
                mask_cells[(region['name'], predicate)] = prefix
                reached = reached and decision is True
            cuts[region['name']] = rows
            if prefix is True: selected.append(region['name'])
        decisions.append({'event_id': eid, 'group_id': gid, 'weights': deepcopy(event['weights']),
                          'object_lineage': lineage,
                          'nodes': {k: {'status': 'undefined' if v is None else 'defined', 'value': _serialize(v)} for k, v in values.items()},
                          'cutflow': cuts, 'regions': selected})
        contributions = group_vectors.setdefault(gid, {w: [] for w in names})
        for r in selected:
            raw[r] += 1
            for q in selected: overlap[r][q] += 1
        masks = [r in selected for r in regions] + [mask_cells[cell] is True for cell in cells] + [True]
        for w in names:
            contributions[w].append([event['weights'][w] * mask for mask in masks])
    dimension = len(regions) + len(cells) + 1
    group_vectors = {gid: {w: [math.fsum(row[i] for row in group[w]) for i in range(dimension)] for w in names}
                     for gid, group in group_vectors.items()}
    sums = {w: [math.fsum(group[w][i] for group in group_vectors.values()) for i in range(dimension)] for w in names}
    moments = {w: [[math.fsum(group[w][i] * group[w][j] for group in group_vectors.values()) for j in range(dimension)] for i in range(dimension)] for w in names}
    cutflow = {}
    for region in plan['regions']:
        rows = []
        for predicate in region['cuts']:
            cell = (region['name'], predicate)
            i = len(regions) + cells.index(cell)
            rows.append({'predicate': predicate, **cut_counts[cell],
                         'cumulative_sumw': {w: sums[w][i] for w in names},
                         'cumulative_group_second_moment': {w: moments[w][i][i] for w in names}})
        cutflow[region['name']] = rows
    result = {'schema_version': 1, 'status': 'passed', 'physics_validated': False,
              'scope': 'Closed compositional reconstructed-object analysis with complete event decisions',
              'inputs': {'program': deepcopy(program), 'contract': contract, 'events': deepcopy(events)},
              'compiled_plan': plan, 'decisions': decisions, 'events': len(events), 'independent_groups': len(group_vectors),
              'region_names': regions, 'weight_names': names, 'sumw_all_events': [sums[w][-1] for w in names],
              'yields': {w: sums[w][:len(regions)] for w in names},
              'covariance': {w: [row[:len(regions)] for row in moments[w][:len(regions)]] for w in names},
              'raw_selected': raw, 'region_overlap_counts': overlap, 'cutflow': cutflow,
              'precision_status': {r: 'zero_selected_precision_unresolved' if raw[r] == 0 else 'conditional_group_moments_only' for r in regions},
              'cutflow_covariance_order': [list(c) for c in cells],
              'cutflow_covariance': {w: [row[len(regions):-1] for row in moments[w][len(regions):-1]] for w in names},
              'limitations': ['Supplied reconstructed objects and ID flags are not detector calibration.',
                              'Group second moments are conditional Poisson MC covariance, not experimental covariance.',
                              'Invariant mass follows binary64 native four-vector order: E squared minus px squared, then py squared, then pz squared; nonpositive computed mass square maps to zero. Four-vector components use correctly rounded sine, cosine and hyperbolic sine and plain products, so they are the same on every platform; other functions follow the host library. Cancellation limits remain.',
                              'mt includes supplied visible rest mass and assumes a massless invisible MET system; mt_massless explicitly preserves the legacy zero-visible-mass convention.',
                              'Dense moments are limited to 256 coordinates, 16 weight streams and 25000000 declared worst-case group-cell products; use independently grouped bounded shards for larger populations.',
                              'Agreement on retained events is not arbitrary-program equivalence or paper reproduction.']}
    json.dumps(result, allow_nan=False)
    return result


def project_exclusive_regions(bundles, census, regions, *, manifest_sha256s):
    """Export verified B witnesses to A's one-fill categorical arm records.

    Manifest digests must be retained outside each bundle. The caller declares
    original shard identity and exclusive chosen regions; overlapping chosen
    regions are refused. A verifies contribution arithmetic, while these B
    bundle receipts establish the cut-to-bin computation on supplied objects.
    """
    from ravel.validation.analysis_witness import verify_bundle
    if (not isinstance(bundles, list) or not bundles or not isinstance(manifest_sha256s, list)
            or len(bundles) != len(manifest_sha256s)):
        raise ValueError('bundles require one external manifest digest each')
    if (not isinstance(regions, list) or not regions or len(set(regions)) != len(regions)
            or any(not isinstance(r, str) for r in regions)):
        raise ValueError('declare distinct exclusive region bins')
    _keys(census, ('schema_version', 'kind', 'records'))
    if type(census['schema_version']) is not int or census['schema_version'] != 1 or census['kind'] != 'original_event_census':
        raise ValueError('original event census required')
    if not isinstance(census['records'], list) or not census['records']:
        raise ValueError('nonempty original event census required')
    identifiers, groups = {}, {}
    for row in census['records']:
        _keys(row, ('event_id', 'group_id', 'shard_id'))
        for value in row.values(): _name(value)
        if row['event_id'] in identifiers: raise ValueError('duplicate census event')
        if groups.setdefault(row['group_id'], row['shard_id']) != row['shard_id']:
            raise ValueError('independent group crosses declared shards')
        identifiers[row['event_id']] = row
    records, receipts, programs, contracts = {}, [], set(), set()
    for path, checksum in zip(bundles, manifest_sha256s):
        if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
            raise ValueError('external manifest digest must be lowercase SHA256')
        bundle = Path(path)
        report = verify_bundle(bundle, checksum)
        if not report['passed']: raise ValueError('analysis witness verification failed: ' + report['error'])
        events = json.loads((bundle/'events.json').read_text())
        trace = json.loads((bundle/'trace.json').read_text())
        program = json.loads((bundle/'program.json').read_text())
        contract = json.loads((bundle/'contract.json').read_text())
        available = {r['name'] for r in program['regions']}
        if not set(regions) <= available: raise ValueError('projection region is absent from verified program')
        programs.add(_digest(program)); contracts.add(_digest(contract))
        originals = {e['event_id']: e for e in events}
        for decision in trace:
            eid = decision['event_id']
            if eid in records or eid not in identifiers: raise ValueError('duplicate or foreign projected event')
            original, identity = originals[eid], identifiers[eid]
            if identity['group_id'] != original['group_id']: raise ValueError('projected independent group differs')
            chosen = [r for r in regions if r in decision['regions']]
            if len(chosen) > 1: raise ValueError('chosen region bins overlap on event: ' + eid)
            records[eid] = {**identity, 'weights': deepcopy(original['weights']),
                            'fills': [[regions.index(chosen[0]) + .5]] if chosen else []}
        receipts.append({'bundle': str(bundle.resolve()), 'manifest_sha256': checksum,
                         'events_sha256': hashlib.sha256((bundle/'events.json').read_bytes()).hexdigest(),
                         'trace_sha256': hashlib.sha256((bundle/'trace.json').read_bytes()).hexdigest(),
                         'verification': report})
    if set(records) != set(identifiers): raise ValueError('projected denominator differs from original census')
    if len(programs) != 1 or len(contracts) != 1: raise ValueError('projection shards require the same program and object contract')
    return {'schema_version': 1, 'arm_records': [records[r['event_id']] for r in census['records']],
            'source_binding': {'program_sha256': next(iter(programs)), 'contract_sha256': next(iter(contracts)),
                               'census_sha256': _digest(census), 'exclusive_regions': regions,
                               'axis_edges': list(range(len(regions)+1)), 'axis_unit': '1', 'bundles': receipts},
            'physics_validated': False,
            'scope': 'Verified supplied-object cuts to exclusive one-fill contribution rows; A separately checks their covariance'}


def compare_results(left, right):
    """Find the first divergent expression on the exact same event population."""
    lrows, rrows = ({r['event_id']: r for r in result['decisions']} for result in (left, right))
    if len(lrows) != len(left['decisions']) or len(rrows) != len(right['decisions']) or lrows.keys() != rrows.keys():
        raise ValueError('differential comparison requires an identical unique full event population')
    if left['region_names'] != right['region_names']:
        raise ValueError('differential region identities differ')
    original_left, original_right = ({event['event_id']: event for event in result['inputs']['events']} for result in (left,right))
    if original_left != original_right or _digest(left['inputs']['contract']) != _digest(right['inputs']['contract']):
        raise ValueError('differential input event content or object contract differs; object interventions require their own protocol')
    order = [n['id'] for n in left['compiled_plan']['nodes']]
    if set(order) != {n['id'] for n in right['compiled_plan']['nodes']}:
        raise ValueError('first divergence requires aligned node identities')
    ltypes = {n['id']:n['type'] for n in left['compiled_plan']['nodes']}
    rtypes = {n['id']:n['type'] for n in right['compiled_plan']['nodes']}
    if ltypes != rtypes: raise ValueError('aligned expressions have different types')
    predicates = [n for n in order if ltypes[n]['shape'] == 'predicate']
    witnesses = []
    counts = {'numerical_only':0,'predicate_only':0,'selection_changed':0}
    for eid in sorted(lrows):
        a, b = lrows[eid], rrows[eid]
        if a['weights'] != b['weights'] or a['group_id'] != b['group_id'] or a['object_lineage'] != b['object_lineage']:
            raise ValueError('differential input identities, groups or weights differ')
        divergent = next((n for n in order if a['nodes'][n] != b['nodes'][n]), None)
        divergent_predicate = next((n for n in predicates if a['nodes'][n] != b['nodes'][n]), None)
        divergent_cut = next(({'region':region,'predicate':p['predicate'],'left':p,'right':q}
                              for region in left['region_names'] for p,q in zip(a['cutflow'][region],b['cutflow'][region]) if p != q),None)
        selection_changed = a['regions'] != b['regions']
        if divergent is not None or a['regions'] != b['regions']:
            category = 'selection_changed' if selection_changed else 'predicate_only' if divergent_predicate is not None else 'numerical_only'
            counts[category] += 1
            witnesses.append({'event_id': eid, 'first_divergent_node': divergent,
                              'first_divergent_predicate':divergent_predicate,'first_divergent_cut':divergent_cut,
                              'selection_changed':selection_changed,'change_kind':category,
                              'left': a['nodes'].get(divergent), 'right': b['nodes'].get(divergent),
                              'left_regions': a['regions'], 'right_regions': b['regions'],
                              'input_event_sha256':_digest(original_left[eid]),
                              'object_lineage': a['object_lineage']})
    return {'status': 'failed' if witnesses else 'passed', 'events': len(lrows),
            'matched_events': len(lrows) - len(witnesses), 'change_counts':counts,'witnesses': witnesses,
            'scope': 'Observed same-event differences; not an allowed-state capacity bound', 'physics_validated': False}


def lower_legacy_selection(selection, object_contract):
    """Lower the existing fixed-variable selection into the compositional vocabulary.

    Equal-pT ties now use stable source-object IDs. A same-event comparison must
    report any difference from an upstream implementation with unspecified ties.
    """
    from .reconstructed_events import selection_spec
    spec = selection_spec(deepcopy(selection), object_contract)
    nodes, counter = [], 0
    def add(op, args=None, **fields):
        nonlocal counter
        counter += 1
        nid = f'n{counter}'
        nodes.append({'id': nid, 'op': op, **({'args': args} if args is not None else {}), **fields})
        return nid
    def constant(value, unit='1'): return add('const', value=value, unit=unit)
    def filter_coll(source, kind, cuts):
        mask = cuts.get('id', 0)
        flags = [name for name, bit in object_contract['flags'][kind].items() if mask & bit]
        return add('filter', [source, constant(cuts['pt'], 'GeV'), constant(cuts['eta'])], flags={'all': flags, 'none': []})
    coll = {kind: filter_coll(add('input', collection=kind), kind, spec['objects'][kind]) for kind in ('electron','muon','jet')}
    met = add('met')
    for step in spec['overlap_removal']:
        coll[step['remove']] = add('overlap', [coll[step['remove']], coll[step['near']], constant(step['dR'])])
    coll = {kind: filter_coll(coll[kind], kind, spec['signal'][kind]) for kind in coll}
    leptons = add('sort', [add('concat', [coll['electron'], coll['muon']])])
    jets = add('sort', [coll['jet']])
    if 'btag' in spec:
        b = spec['btag']
        bjets = filter_coll(jets, 'jet', {'pt': b['pt'], 'eta': b['eta'], 'id': b['idbit']})
    else:
        bjets = add('take', [jets], count=0)
    variables = {'nEl':add('count',[coll['electron']]), 'nMu':add('count',[coll['muon']]),
                 'nLep':add('count',[leptons]), 'nJet':add('count',[jets]), 'nBjet':add('count',[bjets]),
                 'MET':add('field',[met],field='pt'), 'HT':add('sum_pt',[jets])}
    variables['meff'] = add('add',[variables['HT'],variables['MET']])
    lead_leptons = [add('leading',[leptons],index=i) for i in range(2)]
    lead_jets = [add('leading',[jets],index=i) for i in range(4)]
    for i, obj in enumerate(lead_leptons): variables[f'lep{i+1}pt'] = add('field',[obj],field='pt')
    for i, obj in enumerate(lead_jets): variables[f'jet{i+1}pt'] = add('field',[obj],field='pt')
    variables['mll'] = add('mass',lead_leptons)
    variables['mjj'] = add('mass',lead_jets[:2])
    variables['mTlep'] = add('mt_massless',[lead_leptons[0],met])
    variables['dphiMin'] = add('min_dphi',[met,add('take',[jets],count=4)])
    comparisons = {'<':'lt','<=':'le','>':'gt','>=':'ge','==':'eq','!=':'ne'}
    regions = []
    for region in spec['regions']:
        cuts = []
        for cut in region['cuts']:
            unit = '1' if cut['var'].startswith('n') else 'rad' if cut['var'] == 'dphiMin' else 'GeV'
            cuts.append(add('compare',[variables[cut['var']],constant(cut['val'],unit)],comparison=comparisons[cut['op']]))
        regions.append({'name':region['name'],'cuts':cuts})
    program = {'schema_version':1,'name':spec['name'],'nodes':nodes,'regions':regions}
    compile_program(program,object_contract)
    return program


def influence_closure(compiled_plan, changed_nodes):
    """Return graph descendants; this alone is not an affected-event bound."""
    node_ids = {node['id'] for node in compiled_plan['nodes']}
    affected = set(changed_nodes)
    if affected - node_ids: raise ValueError('unknown changed expression node')
    for node in compiled_plan['nodes']:
        if affected.intersection(node.get('args', [])): affected.add(node['id'])
    return {'nodes':[node['id'] for node in compiled_plan['nodes'] if node['id'] in affected],
            'regions':[region['name'] for region in compiled_plan['regions'] if affected.intersection(region['cuts'])],
            'scope':'Static expression influence only; observed first differences do not establish allowed event states'}


def write_bundle(result, directory, *, _capture=None):
    """Write a detached replay bundle and invoke its independent checker."""
    from ravel.workflow.state_io import atomic_json
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payloads = {'program.json': result['inputs']['program'], 'contract.json': result['inputs']['contract'],
                'events.json': result['inputs']['events'], 'trace.json': result['decisions'],
                'result.json': {k: v for k, v in result.items() if k not in ('inputs', 'decisions')}}
    def emit(path,payload):
        if _capture is None:
            atomic_json(path,payload);return
        expected=(json.dumps(payload,indent=2,allow_nan=False)+'\n').encode()
        if len(expected)>8*1024**2:
            raise ValueError('complete emitted replay file exceeds capture ceiling')
        atomic_json(path,payload)
        _capture.read(path,path.parent,hashlib.sha256(expected).hexdigest())
    for name, payload in payloads.items():
        if (directory / name).exists(): raise ValueError('bundle destination already exists: ' + name)
        emit(directory / name, payload)
    from ravel.validation import analysis_witness
    checker = directory / 'verify.py'
    if checker.exists(): raise ValueError('bundle checker destination already exists')
    source=Path(analysis_witness.__file__)
    checker_raw=(source.read_bytes() if _capture is None else _capture.read(source,source.parent)[1])
    checker.write_bytes(checker_raw)
    if _capture is not None:_capture.read(checker,checker.parent,hashlib.sha256(checker_raw).hexdigest())
    manifest = {'schema_version': 1, 'files': {name: hashlib.sha256((directory/name).read_bytes() if _capture is None else _capture.files[(directory/name).absolute()][1]).hexdigest() for name in (*payloads, 'verify.py')}}
    if (directory/'manifest.json').exists(): raise ValueError('bundle manifest destination already exists')
    emit(directory / 'manifest.json', manifest)
    verify_bundle = analysis_witness.verify_bundle
    verification = verify_bundle(directory)
    emit(directory / 'verification.json', verification)
    return verification


def validate(task):
    _keys(task, ('backend', 'program', 'contract', 'events'), ('sfitter_observation',))
    if task['backend'] != 'analysis-ir' or any(not isinstance(task[k], str) or not task[k] for k in ('program', 'contract', 'events')):
        raise ValueError('analysis-ir requires explicit program, contract and events paths')


def inputs(task, base_dir):
    from ravel.workflow.science import regular
    from ravel.workflow.state_io import read_json
    validate(task)
    files = [regular(task[k], base_dir) for k in ('program', 'contract', 'events')]
    contract = read_json(files[1])
    compile_program(read_json(files[0]), contract)
    dependencies = files + [regular(p, base_dir) for p in contract['response_evidence']]
    if 'sfitter_observation' in task:
        from . import sfitter_observed_events as observed
        cp=regular(task['sfitter_observation'],base_dir)
        captured=observed.Capture();_,raw=captured.read(cp,base_dir)
        dependencies += [cp,*[Path(pin['path']) for pin in observed.ir_inputs(observed.decode(raw),cp.parent)]]
        captured.finish()
    return dependencies


def run(task, base_dir, outdir):
    from ravel.workflow.state_io import read_json
    files = inputs(task, base_dir)
    if 'sfitter_observation' in task:
        from . import sfitter_observed_events as observed
        cap=observed.Capture(); original_streams=observed.StreamCapture()
        cp=Path(task['sfitter_observation']);cp=cp if cp.is_absolute() else Path(base_dir).absolute()/cp
        _,raw=cap.read(cp,base_dir);configuration=observed.decode(raw)
        lhe_path=original_streams.pin(configuration['generator']['lhe'],cp.parent)
        for source in files:
            if source!=lhe_path:cap.read(source,base_dir)
        docs=[observed.decode(cap.files[Path(p)][1]) for p in files[:3]]
        result=evaluate_program(*docs)
    else:
        result = evaluate_program(read_json(files[0]), read_json(files[1]), read_json(files[2]))
    generated=observed.Capture() if 'sfitter_observation' in task else None
    output_root=Path(outdir).absolute()
    try:
        verified = write_bundle(result, output_root / 'analysis-witness',_capture=generated)
        summary = {k: v for k, v in result.items() if k not in ('inputs', 'decisions')}
        summary['witness_bundle'] = 'analysis-witness'
        summary['independent_verification'] = verified
        if verified['status'] != 'passed': summary['status'] = 'failed'
        if 'sfitter_observation' in task and summary['status']=='passed':
            program_pin={'path':str(files[0]),'sha256':hashlib.sha256(cap.files[files[0]][1]).hexdigest()}
            manifest=output_root/'analysis-witness/manifest.json'
            summary['sfitter_observation']=observed.emit_ir(result,configuration,cp.parent,output_root/'sfitter-bin-observations.jsonl',program_pin=program_pin,witness={'manifest':{'path':str(manifest),'sha256':hashlib.sha256(generated.files[manifest][1]).hexdigest()}},_generated=generated)
            observed._write(output_root/'sfitter-observation-producer.json',summary['sfitter_observation'],generated)
        return summary
    finally:
        if generated is not None:
            original_error=sys.exception();ending_errors=[]
            for capture in (cap,original_streams):
                try:capture.finish()
                except Exception as error:ending_errors.append(error)
            try:
                generated.bind_output_tree(output_root);generated.finish()
            except Exception as error:ending_errors.append(error)
            if ending_errors:
                detail='; '.join(str(error) for error in ending_errors)
                if original_error is not None:
                    raise ValueError(str(original_error)+'; ending producer custody refused: '+detail) from original_error
                raise ending_errors[0]
