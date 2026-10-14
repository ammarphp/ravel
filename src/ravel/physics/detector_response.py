"""Complete same-event response anchors and neutral LLP conditional folding.

This producer uses existing reconstructed selection and marked-MC consumers.
It supplies neither detector calibration nor an inferred sampling likelihood.
"""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import product
from pathlib import Path
import hashlib
import json
import math

MAX_BYTES = 8 * 1024**2
MAX_TOTAL = 32 * 1024**2
MAX_EVENTS = 20000
MAX_COORDINATES = 512
MAX_MOMENT_PRODUCTS = 2000000
MAX_COORDINATE_VISITS = MAX_EVENTS * MAX_COORDINATES
MAX_OUTPUT_BYTES = 256 * 1024**2


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _keys(row, keys, optional=()):
    _require(type(row) is dict and set(keys) <= row.keys() and
             set(row) <= set(keys) | set(optional), 'closed fields required: ' + ', '.join(keys))


def _number(x, label, positive=False):
    _require(type(x) in (int, float) and math.isfinite(x) and (not positive or x > 0), label + ' must be finite literal numeric' + (' and positive' if positive else ''))
    return float(x)


def _text(x):
    _require(type(x) is str and x.strip(), 'nonempty identity/source text required')
    return x


def _names(xs):
    _require(type(xs) is list and xs and all(type(x) is str and x.strip() for x in xs) and len(set(xs)) == len(xs), 'complete unique named population required')
    return [_text(x) for x in xs]


def _bytes(d):
    return (json.dumps(d, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _load(raw):
    def pairs(xs):
        d = {}
        for k, v in xs:
            _require(k not in d, 'duplicate JSON key: ' + k); d[k] = v
        return d
    def invalid(x):
        raise ValueError('nonfinite JSON literal: ' + x)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _regular(name, base):
    p = Path(name); p = p if p.is_absolute() else Path(base) / p
    _require(not any(q.is_symlink() for q in (p, *p.parents)) and p.is_file(), 'regular response input without symlink ancestors required: ' + str(p))
    return p.resolve()


def _read(p):
    with p.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    _require(len(raw) <= MAX_BYTES, 'response scientific input exceeds 8 MiB')
    return raw


def _pin(pin, base, captured):
    _keys(pin, ('id', 'path', 'sha256', 'reference'))
    for key in ('id', 'path', 'reference'): _text(pin[key])
    _require(type(pin['sha256']) is str and len(pin['sha256']) == 64 and all(x in '0123456789abcdef' for x in pin['sha256']), 'literal SHA256 required')
    p = _regular(pin['path'], base); raw = _read(p)
    _require(hashlib.sha256(raw).hexdigest() == pin['sha256'], 'response input differs from declared source pin: ' + str(p))
    _require(p not in captured or captured[p] == raw, 'conflicting source identity')
    captured[p] = raw
    _require(sum(map(len, captured.values())) <= MAX_TOTAL, 'response inputs exceed 32 MiB aggregate')
    return p, raw


def _unchanged(captured):
    for p, raw in captured.items():
        _require(_read(_regular(p, '.')) == raw, 'scientific response input changed: ' + str(p))


def validate(task):
    _keys(task, ('request_file',)); _text(task['request_file'])


def _request(task, base):
    validate(task); p = _regular(task['request_file'], base); raw = _read(p)
    captured = {p: raw}; d = _load(raw)
    _require(type(d) is dict, 'response request must be a JSON object')
    common = ('schema_version', 'operation', 'axes', 'reference_point', 'weight_name', 'normalization', 'source_pins', 'anchors')
    if d.get('operation') == 'fixed_event_migrations':
        _keys(d, common + ('object_contract', 'selection'), ('category_support', 'numerical_projection'))
    elif d.get('operation') == 'neutral_llp_joint_response':
        _keys(d, common + ('events', 'geometry', 'joint_response', 'decay_assumption'), ('category_support', 'numerical_projection', 'joint_calibration'))
    else:
        raise ValueError('choose fixed_event_migrations or neutral_llp_joint_response')
    _require(type(d['schema_version']) is int and d['schema_version'] == 1, 'response request schema1 required')
    _text(d['weight_name'])
    n = d['normalization']; _keys(n, ('scale', 'denominator', 'fixed_denominator', 'meaning'))
    _number(n['scale'], 'normalization scale', True); _text(n['meaning'])
    _require(n['denominator'] in ('sum_original_weights', 'fixed'), 'explicit denominator convention required')
    _require(n['fixed_denominator'] is None if n['denominator'] == 'sum_original_weights' else type(n['fixed_denominator']) in (int, float) and _number(n['fixed_denominator'], 'fixed denominator', True), 'fixed denominator must be supplied only for fixed normalization')
    axes = d['axes']; _require(type(axes) is list and 1 <= len(axes) <= 4, 'one to four complete response axes')
    for a in axes:
        _keys(a, ('name', 'knots')); _text(a['name'])
        _require(type(a['knots']) is list and 2 <= len(a['knots']) <= 5, 'two to five knots per axis')
        for x in a['knots']: _number(x, 'anchor knot')
        _require(all(x < y for x, y in zip(a['knots'], a['knots'][1:])), 'ordered distinct knots required')
    names = _names([a['name'] for a in axes]); _keys(d['reference_point'], names)
    expected = list(product(*(a['knots'] for a in axes)))
    _require(len(expected) <= 16, 'bounded16 complete joint anchors')
    for a in axes: _require(d['reference_point'][a['name']] in a['knots'], 'reference point must be a retained anchor')
    _require(type(d['anchors']) is list and len(d['anchors']) == len(expected), 'complete Cartesian anchor population required')
    points = []
    for a in d['anchors']:
        _keys(a, ('point', 'events') if d['operation'] == 'fixed_event_migrations' else ('point', 'ctau_mm'))
        _require(type(a['point']) is list and len(a['point']) == len(axes), 'ordered anchor coordinate required')
        for x in a['point']: _number(x, 'anchor point')
        points.append(tuple(a['point']))
        if 'ctau_mm' in a: _number(a['ctau_mm'], 'proper mean decay length mm', True)
    _require(len(set(points)) == len(expected) and set(points) == set(expected), 'duplicate/missing joint anchor; no inferred interactions')
    _require(type(d['source_pins']) is list, 'source pins must be an explicit list')
    pins = list(d['source_pins']); _require(pins, 'physical source and normalization evidence pins required')
    if d['operation'] == 'fixed_event_migrations': pins += [d['object_contract'], d['selection']] + [a['events'] for a in d['anchors']]
    else:
        pins += [d['events'], d['joint_response']]
        _require(d['decay_assumption'] == 'independent_exponential_proper_decays_conditional_on_supplied_truth', 'explicit conditional independent decay law required')
        _geometry(d['geometry'])
    if 'joint_calibration' in d:
        cal = d['joint_calibration']; _keys(cal, ('table', 'evidence', 'population'))
        _require(cal['population'] in ('mc', 'data'), 'explicit absolute joint calibration population required')
        pins += [cal['table'], cal['evidence']]
    if 'category_support' in d: pins.append(d['category_support'])
    if 'numerical_projection' in d:
        _keys(d['numerical_projection'], ('deck', 'component_map'))
        pins.append(d['numerical_projection']['deck'])
    _require(len(pins) <= 32 and len({x['id'] for x in pins}) == len(pins), 'bounded distinct source pin IDs')
    loaded = {}
    for pin in pins:
        path, content = _pin(pin, p.parent, captured); loaded[pin['id']] = (path, content)
    if d['operation'] == 'fixed_event_migrations':
        contract = _load(loaded[d['object_contract']['id']][1])
        from ravel.physics.reconstructed_events import object_contract, selection_spec
        object_contract(contract); selection_spec(_load(loaded[d['selection']['id']][1]), contract)
        _require(d['weight_name'] in contract['weight_names'], 'requested weight absent from object contract')
        for evidence in contract['response_evidence']:
            _require(_regular(evidence, loaded[d['object_contract']['id']][0].parent) in captured, 'object response evidence missing from full source pin closure')
    return p, d, captured, loaded


def inputs(task, base):
    return sorted(_request(task, base)[2])


def _geometry(g):
    _keys(g, ('unit', 'cells', 'outside_id', 'trajectory'))
    _require(g['unit'] == 'mm' and g['trajectory'] == 'neutral_straight_line', 'only neutral straight-line geometry with mm lengths is implemented')
    _text(g['outside_id']); cells = g['cells']
    _require(type(cells) is list and 1 <= len(cells) <= 8, 'one to eight explicit disjoint cylindrical shells')
    for c in cells:
        _keys(c, ('id', 'r_min', 'r_max', 'z_min', 'z_max'))
        _text(c['id'])
        for k in ('r_min', 'r_max', 'z_min', 'z_max'): _number(c[k], k)
        _require(0 <= c['r_min'] < c['r_max'] and c['z_min'] < c['z_max'], 'nonempty radial and longitudinal cell extents')
    _names([c['id'] for c in cells] + [g['outside_id']])
    for i, c in enumerate(cells):
        for q in cells[:i]:
            _require(not (max(c['r_min'], q['r_min']) < min(c['r_max'], q['r_max']) and max(c['z_min'], q['z_min']) < min(c['z_max'], q['z_max'])), 'overlapping decay cells cannot be treated as exclusive states')
    return g


def _inside_radius(x, y, ux, uy, radius):
    # Intervals in nonnegative lab flight distance; tangent rays have zero measure.
    a = ux*ux + uy*uy; b = x*ux + y*uy; c = x*x + y*y - radius*radius
    _require(all(math.isfinite(v) for v in (a, b, c)), 'geometry quadratic overflow; unsupported numeric domain')
    # These are the exact values of the supplied binary64 coordinates and
    # already computed direction. Subtracting rounded b*b and a*c can erase
    # a genuine intersection far from the cylinder, even with finite inputs.
    x, y, ux, uy, radius = (Fraction.from_float(float(v)) for v in (x, y, ux, uy, radius))
    a = ux*ux + uy*uy; b = x*ux + y*uy; c = x*x + y*y - radius*radius
    if a == 0:
        return [(0., math.inf)] if c < 0 else []
    disc = b*b - a*c
    if disc <= 0: return []
    # The stable quadratic formula avoids cancelling nearly equal roots.
    # 80 working digits exceed binary64 output precision; root values whose
    # positive interval cannot be represented distinctly are refused.
    with localcontext() as context:
        context.prec = 80
        decimal = lambda f: Decimal(f.numerator)/Decimal(f.denominator)
        da, db, dc = decimal(a), decimal(b), decimal(c)
        root = decimal(disc).sqrt()
        q = -root if b == 0 else -db-root if b > 0 else -db+root
        _require(q != 0, 'geometry stable root not representable; unsupported numeric domain')
        left, right = sorted((q/da, dc/q))
        if right <= 0: return []
        left = max(Decimal(0), left)
        lo, hi = float(left), float(right)
    _require(math.isfinite(lo) and math.isfinite(hi) and hi > lo,
             'geometry intersection endpoints not distinguishable in binary64; unsupported numeric domain')
    return [(lo, hi)]


def shell_intervals(particle, cell):
    """Lab-distance shell intersections for an arbitrary supplied production vertex."""
    _keys(particle, ('id', 'charge', 'mass_GeV', 'momentum_GeV', 'origin_mm'))
    _text(particle['id']); _require(type(particle['charge']) in (int, float) and particle['charge'] == 0, 'charged LLP needs a source-qualified curved/material trajectory, not straight-line fallback')
    mass = _number(particle['mass_GeV'], 'LLP mass', True)
    for key in ('momentum_GeV', 'origin_mm'):
        _require(type(particle[key]) is list and len(particle[key]) == 3, 'complete Cartesian momentum/origin coordinates')
        for x in particle[key]: _number(x, key)
    px, py, pz = particle['momentum_GeV']; x, y, z = particle['origin_mm']
    p = math.hypot(px, py, pz)
    if p == 0: return None, mass, p
    ux, uy, uz = px/p, py/p, pz/p
    radial = _inside_radius(x, y, ux, uy, cell['r_max'])
    inner = _inside_radius(x, y, ux, uy, cell['r_min']) if cell['r_min'] else []
    if uz == 0:
        zrange = (0., math.inf) if cell['z_min'] <= z < cell['z_max'] else None
    else:
        ends = sorted(((cell['z_min']-z)/uz, (cell['z_max']-z)/uz)); zrange = (max(0., ends[0]), ends[1])
    if zrange is None or zrange[1] <= zrange[0]: return [], mass, p
    answer = []
    for lo, hi in radial:
        lo, hi = max(lo, zrange[0]), min(hi, zrange[1])
        if hi <= lo: continue
        parts = [(lo, hi)]
        for a, b in inner:
            next_parts = []
            for left, right in parts:
                if b <= left or a >= right: next_parts.append((left, right))
                else:
                    if left < a: next_parts.append((left, a))
                    if b < right: next_parts.append((b, right))
            parts = next_parts
        answer += parts
    return answer, mass, p


def decay_probabilities(particle, geometry, ctau_mm):
    """Exact exponential shell probabilities; no displaced reconstruction efficiency."""
    g = _geometry(geometry); ctau = _number(ctau_mm, 'ctau_mm', True); result = {}
    for c in g['cells']:
        intervals, mass, p = shell_intervals(particle, c)
        if intervals is None:
            x, y, z = particle['origin_mm']; r = math.hypot(x, y)
            probability = float(c['r_min'] <= r < c['r_max'] and c['z_min'] <= z < c['z_max'])
        else:
            rate = mass / p / ctau
            _number(rate, 'representable proper decay rate', True)
            probability = math.fsum(math.exp(-lo*rate)*(-math.expm1(-(hi-lo)*rate)) for lo, hi in intervals)
        _require(math.isfinite(probability) and 0 <= probability <= 1, 'nonphysical shell probability; no clipping')
        result[c['id']] = probability
    outside = 1 - math.fsum(result.values())
    _require(0 <= outside <= 1, 'nonphysical complete decay population; no renormalization')
    result[g['outside_id']] = outside
    return result


def _stage(raw, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream: stream.write(raw)
    return target


def write_complete_json(document, target):
    """Stream the complete result, bounded per file; retain partial on refusal.

    Compact JSON changes formatting, not the complete scientific population.
    No full serialized duplicate is allocated before enforcing the byte cap.
    """
    target = Path(target)
    _require(not any(p.is_symlink() for p in (target, *target.parents)),
             'result path without symlink ancestors required')
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False)
    with target.open('xb') as stream:
        for piece in encoder.iterencode(document):
            raw = piece.encode('utf-8'); size += len(raw)
            _require(size + 1 <= MAX_OUTPUT_BYTES, 'complete response result exceeds 256 MiB per file; no partial result acceptance')
            stream.write(raw)
        stream.write(b'\n')
    return size + 1


def _fixed(d, loaded, out):
    from ravel.physics.reconstructed_events import run as select
    contract_raw = loaded[d['object_contract']['id']][1]
    # Kernel consumes byte-identical authenticated copies. Its response-evidence
    # labels stay original; the full original evidence closure is independently pinned.
    contract = _stage(contract_raw, out/'selection-inputs/object-contract.json')
    selection = _stage(loaded[d['selection']['id']][1], out/'selection-inputs/selection.json')
    all_rows = []; results = []
    for i, anchor in enumerate(d['anchors']):
        path = _stage(loaded[anchor['events']['id']][1], out/f'selection-inputs/events-{i}.json')
        target = out/f'selections/anchor-{i}'
        event_count = len(_load(loaded[anchor['events']['id']][1]))
        region_count = len(_load(loaded[d['selection']['id']][1])['regions'])+1
        _require(1 <= event_count <= MAX_EVENTS and event_count*len(d['anchors'])*region_count <= MAX_COORDINATE_VISITS, 'bounded complete reconstructed response coordinate census')
        result = select({'events': str(path), 'object_contract': str(contract), 'selection': str(selection)}, '.', target,
                        defer_covariance_to_response=True)
        traces = _load((target/'decisions.json').read_bytes()); events = _load(path.read_bytes())
        _require(len(traces) == len(events) <= MAX_EVENTS, 'complete bounded reconstructed event census')
        regions = result['region_names']
        _require(all(r['event_id'] == e['event_id'] and r['group_id'] == e['group_id'] and r['weights'] == e['weights'] for r, e in zip(traces, events)), 'consumed kernel trace differs from authenticated event identities/weights')
        rows = [{'event_id': r['event_id'], 'group_id': r['group_id'], 'weights': r['weights'],
                 'allocation': [float(k in r['regions']) for k in regions] + [float(not r['regions'])]} for r in traces]
        all_rows.append(rows); results.append(result)
        _require(path.read_bytes() == loaded[anchor['events']['id']][1] and contract.read_bytes() == contract_raw and selection.read_bytes() == loaded[d['selection']['id']][1], 'authenticated kernel scientific copies changed')
    return regions + ['__rejected__'], all_rows, {'selection_results': results, 'response_model': 'supplied reconstructed anchors; preserved native-SA primitive selection', 'overlapping_regions_retained': True}


def _llp(d, loaded, out):
    data = _load(loaded[d['events']['id']][1]); table = _load(loaded[d['joint_response']['id']][1])
    _keys(data, ('schema_version', 'momentum_unit', 'position_unit', 'weight_names', 'events'))
    _require(type(data['schema_version']) is int and data['schema_version'] == 1 and data['momentum_unit'] == 'GeV' and data['position_unit'] == 'mm', 'truth LLP coordinates require schema1 GeV/mm')
    calibration = None; calibration_copies = []
    if 'joint_calibration' in d:
        from ravel.physics.source_calibration.provider import ArtifactPin, JointCategoricalResponse
        cal = d['joint_calibration']; copies = {}
        for key in ('table', 'evidence'):
            raw = loaded[cal[key]['id']][1]; path = _stage(raw, out/('calibration-inputs/'+key+'.json'))
            copies[key] = ArtifactPin(str(path), hashlib.sha256(raw).hexdigest()); calibration_copies.append((path, raw))
        calibration = JointCategoricalResponse.load(copies['table'], evidence=copies['evidence'])
    weights = _names(data['weight_names']); _require(d['weight_name'] in weights, 'requested original weight not supplied')
    _keys(table, ('schema_version', 'scope', 'conditioning', 'destination_ids', 'anchors', 'source'))
    _require(type(table['schema_version']) is int and table['schema_version'] == 1 and table['scope'] == 'joint_event_conditional_probabilities', 'per-object/vertex efficiency is not joint event acceptance')
    _text(table['conditioning']); _text(table['source']); dests = _names(table['destination_ids'])
    _require('__rejected__' in dests and len(dests) <= 32, 'complete response destinations including rejected events')
    _require(type(table['anchors']) is list and len(table['anchors']) == len(d['anchors']), 'every requested response anchor required')
    tables = {}
    cell_ids = [c['id'] for c in d['geometry']['cells']] + [d['geometry']['outside_id']]
    for a in table['anchors']:
        _keys(a, ('point', 'contexts')); point = tuple(a['point'])
        _require(point not in tables and point in {tuple(x['point']) for x in d['anchors']}, 'unknown/duplicate table anchor')
        contexts = {}
        _require(type(a['contexts']) is list and a['contexts'], 'explicit complete response conditioning cells required')
        for c in a['contexts']:
            _keys(c, ('id', 'llp_count', 'llp_ids', 'states')); _text(c['id'])
            count = c['llp_count']; _require(type(count) is int and 0 <= count <= 4, 'bounded0..4 explicit LLP multiplicity')
            _require(type(c['llp_ids']) is list and len(c['llp_ids']) == count and len(set(c['llp_ids'])) == count and all(type(x) is str and x for x in c['llp_ids']), 'ordered distinct source LLP role IDs required')
            states = list(product(cell_ids, repeat=count)); _require(len(states) <= 4096 and len(c['states']) == len(states), 'complete bounded joint decay-state response table required')
            mapping = {}
            for row in c['states']:
                _keys(row, ('cells', 'calibration_context') if calibration is not None else ('cells', 'allocation')); key = tuple(row['cells'])
                _require(key in states and key not in mapping, 'unknown/duplicate joint decay state')
                if calibration is None:
                    v = row['allocation']
                else:
                    probabilities = calibration.absolute_probabilities(row['calibration_context'], population=d['joint_calibration']['population'])
                    _require(set(probabilities) == set(dests), 'calibrated joint outcome population must equal every destination, including rejected')
                    v = [probabilities[name] for name in dests]
                _require(type(v) is list and len(v) == len(dests), 'complete response destination allocation')
                _require(all(0 <= _number(x, 'joint response probability') <= 1 for x in v) and abs(math.fsum(v)-1) <= 1e-12, 'complete joint response probabilities, no missing/outside zero assumption')
                mapping[key] = v
            _require(c['id'] not in contexts, 'duplicate response conditioning context')
            contexts[c['id']] = (c['llp_ids'], mapping)
        tables[point] = contexts
    events = data['events']; _require(type(events) is list and 1 <= len(events) <= MAX_EVENTS, 'bounded complete truth event census')
    _require(len(events)*len(d['anchors'])*len(dests) <= MAX_COORDINATE_VISITS, 'bounded complete LLP response coordinate census')
    max_states = max(len(mapping) for contexts in tables.values() for roles, mapping in contexts.values())
    _require(len(events)*len(d['anchors'])*len(dests)*max_states <= 2000000, 'joint LLP state fold work exceeds two million products')
    all_rows = []; flight = []
    for anchor in d['anchors']:
        rows = []; contexts = tables[tuple(anchor['point'])]; used = set()
        for e in events:
            _keys(e, ('event_id', 'group_id', 'weights', 'context_id', 'llps'))
            _text(e['event_id']); _text(e['group_id']); _keys(e['weights'], weights)
            for w in e['weights'].values(): _number(w, 'original event weight')
            _require(e['context_id'] in contexts, 'uncovered event context; no extrapolation')
            role_ids, mapping = contexts[e['context_id']]; count = len(role_ids); used.add(e['context_id'])
            _require(type(e['llps']) is list and len(e['llps']) == count and [p['id'] for p in e['llps']] == role_ids, 'full ordered distinct LLP source population differs from response context')
            probabilities = [decay_probabilities(p, d['geometry'], anchor['ctau_mm']) for p in e['llps']]
            contributions = [[] for _ in dests]
            for cells, allocation in mapping.items():
                factor = math.prod(probabilities[i][k] for i, k in enumerate(cells))
                for i, v in enumerate(allocation): contributions[i].append(factor*v)
            values = [math.fsum(xs) for xs in contributions]
            _require(abs(math.fsum(values)-1) <= 1e-12 and all(0 <= v <= 1 for v in values), 'complete folded event probabilities; no renormalization')
            rows.append({'event_id': e['event_id'], 'group_id': e['group_id'], 'weights': e['weights'], 'allocation': values})
            flight.append({'point': anchor['point'], 'event_id': e['event_id'], 'LLP_role_ids': role_ids, 'LLP_cell_probabilities': probabilities, 'conditional_event_response': values})
        _require(used == set(contexts), 'response context census includes unused/unknown conditioning cells')
        all_rows.append(rows)
    for path, raw in calibration_copies: _require(path.read_bytes() == raw, 'authenticated joint calibration copy changed')
    return dests, all_rows, {'absolute_joint_calibration_population': d.get('joint_calibration', {}).get('population'), 'calibration_certified': False, 'flight_and_response': flight, 'response_model': table['scope'], 'conditioning': table['conditioning'], 'decay_assumption': d['decay_assumption'], 'stochastic_detector_sampling': False}


def summarize(d, destinations, all_rows):
    """Complete Gram via exact-zero support, followed by normalization projection.

    Event products and grouped sums retain the original binary64/fsum law.
    Raw Gram output also retains float product/fsum rounding. Covariance uses
    exact rational contraction of those rounded group marks/factors/ratios;
    it is rounded once per output entry, not bitwise legacy residual arithmetic.
    """
    _require(all_rows and len(all_rows) == len(d['anchors']), 'complete response anchor census')
    first = all_rows[0]
    _require(1 <= len(first) <= MAX_EVENTS, 'bounded20000 nonempty full event population')
    k = len(all_rows)*len(destinations)
    _require(0 < k <= MAX_COORDINATES and len(first)*k <= MAX_COORDINATE_VISITS,
             'bounded complete response coordinate census')
    census = [(r['event_id'], r['group_id'], r['weights']) for r in first]
    _require(len({r[0] for r in census}) == len(census), 'duplicate event identity')
    weights = _names(list(first[0]['weights']))
    _require(d['weight_name'] in weights, 'requested original weight absent')
    q = k*len(weights)
    _require(q <= MAX_COORDINATES, 'bounded512 complete weight/anchor/region coordinates')
    # Authenticate all explicit zero entries and every anchor/group/weight
    # identity before any support-dependent arithmetic or work admission.
    for rows in all_rows:
        _require([(r['event_id'], r['group_id'], r['weights']) for r in rows] == census,
                 'same ordered full event/group/weight census required at every anchor')
        for r in rows:
            _require(set(r['weights']) == set(weights) and len(r['allocation']) == len(destinations),
                     'complete weight/destination census')
            for x in r['weights'].values(): _number(x, 'original weight')
            for x in r['allocation']: _number(x, 'response mark')
    group_ids = list(dict.fromkeys(r['group_id'] for r in first))
    basis = [{'point': a['point'], 'destination': b} for a in d['anchors'] for b in destinations]
    n = d['normalization']; summaries = {}; group_marks = {}; joint_basis = []
    raw_vectors = {g: {} for g in group_ids}; factors = []; ratios = []
    products = {'event_mark': 0, 'normalized_mean': 0, 'raw_float_Gram': 0, 'raw_exact_Gram': 0,
                'normalization_projection': 0}
    def charge(kind, count=1):
        _require(sum(products.values()) + count <= MAX_MOMENT_PRODUCTS,
                 'complete joint moment work exceeds two million actual products; retain all coordinates/groups')
        products[kind] += count
    for wi, w in enumerate(weights):
        # No empty per-cell term lists: cancellation is resolved at GROUP level.
        # Skipped entries are explicit exact zeros, never absent observations.
        terms = {g: {} for g in group_ids}
        for i, event in enumerate(first):
            t = terms[event['group_id']]; weight = event['weights'][w]
            if weight != 0:
                t.setdefault(k, []).append(weight)
                for a, rows in enumerate(all_rows):
                    for b, value in enumerate(rows[i]['allocation']):
                        if value != 0:
                            charge('event_mark')
                            v = weight*value; _number(v, 'finite event response product')
                            if v != 0: t.setdefault(a*len(destinations)+b, []).append(v)
        vectors = {}
        for g, entries in terms.items():
            v = [0.]*(k+1)
            for i, xs in entries.items():
                v[i] = math.fsum(xs); _number(v[i], 'finite grouped response mark')
                if v[i] != 0:
                    index = wi*k+i if i < k else q+wi
                    raw_vectors[g][index] = v[i]
            vectors[g] = v
        sumw = math.fsum(v[-1] for v in vectors.values())
        denominator = sumw if n['denominator'] == 'sum_original_weights' else n['fixed_denominator']
        _number(denominator, 'positive original normalization denominator', True)
        numerators = [math.fsum(v[i] for v in vectors.values()) for i in range(k)]
        for value in numerators: _number(value, 'finite complete response numerator')
        factor = n['scale']/denominator
        _number(factor, 'representable positive normalization factor', True)
        charge('normalized_mean', k)
        values = [factor*x for x in numerators]
        for value in values: _number(value, 'finite normalized response value')
        factors += [Fraction(factor)]*k
        ratios += [Fraction(numerators[i]/denominator) if n['denominator'] == 'sum_original_weights'
                   else Fraction(0) for i in range(k)]
        summaries[w] = {'sum_original_weights': sumw, 'denominator': denominator,
                        'numerators': numerators, 'normalized_values': values}
        group_marks[w] = vectors
        joint_basis += [{'weight': w, **coordinate} for coordinate in basis]
    # Count BEFORE multiplying. Every raw support includes all weights and
    # their denominators, so cross-weight/anchor/cancellation terms survive.
    pairs = sum(len(v)*(len(v)+1)//2 for v in raw_vectors.values())
    charge('raw_float_Gram', pairs); charge('raw_exact_Gram', pairs)
    rounded_terms = {}; exact_gram = {}
    for vector in raw_vectors.values():
        support = sorted(vector.items())
        for a, (i, x) in enumerate(support):
            fx = Fraction(x)
            for j, y in support[a:]:
                key = (i, j); value = x*y
                _number(value, 'finite raw group Gram product')
                rounded_terms.setdefault(key, []).append(value)
                exact_gram[key] = exact_gram.get(key, Fraction(0)) + fx*Fraction(y)
    rounded_gram = {key: math.fsum(values) for key, values in rounded_terms.items()}
    for value in rounded_gram.values(): _number(value, 'finite raw group Gram sum')
    del rounded_terms
    def entry(gram, i, j): return gram.get((min(i,j), max(i,j)), 0)
    covariance = [[0.]*q for _ in range(q)]
    for i in range(q):
        di = q+i//k
        for j in range(i, q):
            dj = q+j//k; value = entry(exact_gram,i,j)
            if ratios[j] and entry(exact_gram,i,dj):
                charge('normalization_projection'); value -= ratios[j]*entry(exact_gram,i,dj)
            if ratios[i] and entry(exact_gram,di,j):
                charge('normalization_projection'); value -= ratios[i]*entry(exact_gram,di,j)
            if ratios[i] and ratios[j] and entry(exact_gram,di,dj):
                charge('normalization_projection',2)
                value += ratios[i]*ratios[j]*entry(exact_gram,di,dj)
            if value:
                charge('normalization_projection',2)
                value = float(factors[i]*factors[j]*value)
                _number(value, 'representable normalized joint covariance')
            else: value = 0.
            covariance[i][j] = covariance[j][i] = value
    for wi,w in enumerate(weights):
        indices = list(range(wi*k,(wi+1)*k)) + [q+wi]
        summaries[w]['full_numerator_denominator_Gram'] = [
            [entry(rounded_gram,i,j) for j in indices] for i in indices]
        summaries[w]['conditional_group_covariance'] = [row[wi*k:(wi+1)*k]
            for row in covariance[wi*k:(wi+1)*k]]
        summaries[w]['moment_scope'] = ('conditional_independent_group_Poisson_Gram_fixed_denominator'
            if n['denominator'] == 'fixed' else 'first_order_shared_denominator_group_Poisson_delta_Gram')
    reference = next(i for i, a in enumerate(d['anchors']) if a['point'] == [d['reference_point'][x['name']] for x in d['axes']])
    migrations = []
    for a, rows in enumerate(all_rows):
        records = []
        for i, row in enumerate(rows):
            records.append({'event_id': row['event_id'], 'group_id': row['group_id'], 'original_weights': row['weights'],
                            'from_allocation': all_rows[reference][i]['allocation'], 'to_allocation': row['allocation']})
        deterministic = all(x in (0., 1.) for r in records for key in ('from_allocation', 'to_allocation') for x in r[key])
        transition_terms = {}
        if deterministic:
            for r in records:
                key = (tuple(i for i, x in enumerate(r['from_allocation']) if x), tuple(i for i, x in enumerate(r['to_allocation']) if x))
                group = transition_terms.setdefault(key, {'events': 0, 'weights': {w: [] for w in weights}}); group['events'] += 1
                for w in weights: group['weights'][w].append(r['original_weights'][w])
        transitions = [{'from_destinations': [destinations[i] for i in key[0]], 'to_destinations': [destinations[i] for i in key[1]], 'events': group['events'],
                        'sum_original_weights': {w: math.fsum(xs) for w, xs in group['weights'].items()}} for key, group in transition_terms.items()] if deterministic else None
        migrations.append({'point': d['anchors'][a]['point'], 'records': records, 'deterministic_joint_signature_transitions': transitions, 'scope': 'same-event allocation pair; fractional response has no inferred stochastic joint transition'})
    _require(all(math.isfinite(x) for s in summaries.values() for x in s['normalized_values']),
             'derived response overflow')
    return {'basis': basis, 'destination_ids': destinations, 'events': len(first), 'group_ids': group_ids,
            'anchor_records': all_rows, 'weights': summaries, 'migration_witnesses': migrations,
            'group_marks': group_marks, 'joint_weight_anchor_basis': joint_basis,
            'joint_weight_anchor_covariance': covariance,
            'moment_work': {'products': products, 'total_products': sum(products.values()),
                'limit_products': MAX_MOMENT_PRODUCTS, 'full_event_coordinate_visits': len(first)*k,
                'limit_coordinate_visits': MAX_COORDINATE_VISITS,
                'full_weight_event_coordinate_visits': len(first)*q,
                'dense_group_mark_slots': len(group_ids)*(q+len(weights)),
                'raw_joint_dimensions_including_weight_denominators': q+len(weights),
                'nonzero_group_support_entries': sum(map(len,raw_vectors.values())),
                'dense_legacy_group_product_estimate': len(group_ids)*(q+1)**2,
                'zero_policy': 'skip only validated exact zero contributions and exact post-group cancellations; emit all coordinates/groups',
                'work_scope': 'actual scalar event/mean/Gram/contraction multiplications; census reads, additions, divisions, rational internal integer operations and serialization are bounded separately, not counted as scalar products',
                'arithmetic': 'binary64 event products and math.fsum group/Gram sums retained; exact Fraction covariance contraction of rounded group marks/factors/ratios, rounded once per output entry'},
            'likelihood_inferred': False, 'physics_validated': False, 'sampling_law_established': False}


def _handoff(d, bundle, raw, out):
    """Construct existing marked/MC artifacts only for declared complete IID support."""
    from ravel.physics import marked_response as mr, marked_response_provider as mp, mc_auxiliary as mc
    support = _load(raw)
    _keys(support, ('schema_version', 'sampling_law', 'support_complete', 'independence', 'source', 'calibration', 'categories', 'fitted_destinations'))
    _require(type(support['schema_version']) is int and support['schema_version'] == 1 and support['sampling_law'] == 'iid_fixed_mark_categories' and support['support_complete'] is True and support['independence'] == 'iid_groups_within_one_fixed_N_stream', 'complete source-declared IID support, not observed-only clustering, required')
    _text(support['source']); _text(support['calibration']); cats = support['categories']
    _require(type(cats) is list and 2 <= len(cats) <= 64, 'two to64 complete categories including unobserved support')
    groups = bundle['group_marks'][d['weight_name']]; ids = []; observed = []; cw = []; dm = []; initial = []; alloc = []
    for c in cats:
        _keys(c, ('id', 'group_ids', 'weight', 'denominator_mark', 'initial', 'allocation_at_anchors'))
        ids.append(_text(c['id'])); _require(type(c['group_ids']) is list and len(set(c['group_ids'])) == len(c['group_ids']), 'complete ordered observed group IDs')
        _number(c['weight'], 'fixed category weight'); _number(c['denominator_mark'], 'fixed category denominator mark')
        denominator = c['weight'] if d['normalization']['denominator'] == 'sum_original_weights' else 1.
        _require(c['denominator_mark'] == denominator,
                 'every support category denominator mark must obey the declared normalization law, including unobserved support')
        _require(0 < _number(c['initial'], 'latent initial') < 1, 'source-supplied positive category simplex required')
        rows = c['allocation_at_anchors']; _require(type(rows) is list and len(rows) == len(d['anchors']), 'full joint category anchor signature, including unobserved groups')
        for row in rows:
            _require(type(row) is list and len(row) == len(bundle['destination_ids']) and all(0 <= _number(v, 'category allocation') <= 1 for v in row) and abs(math.fsum(row)-1) <= 1e-12, 'exclusive complete response allocation; overlapping bins need their separate joint likelihood')
        expected = [c['weight']*x for row in rows for x in row]
        for g in c['group_ids']:
            _require(g in groups, 'support cites unknown observed group')
            _require(groups[g][:-1] == expected, 'observed full joint-anchor marks differ from declared fixed category')
            den = groups[g][-1] if d['normalization']['denominator'] == 'sum_original_weights' else 1.
            _require(den == c['denominator_mark'], 'source denominator group mark differs')
        observed += c['group_ids']; cw.append(c['weight']); dm.append(c['denominator_mark']); initial.append(c['initial']); alloc.append(rows)
    _names(ids); _require(len(set(observed)) == len(observed) and set(observed) == set(bundle['group_ids']), 'every original generator group exactly once, including rejected/zero/signed')
    _require(abs(math.fsum(initial)-1) <= 1e-12, 'no renormalization of source category simplex')
    fitted = _names(support['fitted_destinations']); total = len(groups)
    n = d['normalization']; scale = n['scale'] if n['denominator'] == 'sum_original_weights' else n['scale']*total/n['fixed_denominator']
    law = mr.prepare({'schema_version': 1, 'category_ids': ids, 'destination_ids': bundle['destination_ids'], 'fitted_destinations': fitted,
          'axes': d['axes'], 'reference_point': d['reference_point'], 'category_weights': cw, 'denominator_marks': dm, 'scale': scale, 'total_groups': total,
          'anchors': [{'point': a['point'], 'allocation': [rows[i] for rows in alloc]} for i, a in enumerate(d['anchors'])],
          'provenance': {'category_partition': support['source'], 'joint_anchor_identity': 'complete source-declared category signatures checked against every observed generator group',
                         'interpolation': 'new_piecewise_multilinear_fixed_mark_law', 'calibration': support['calibration']}})
    _stage(raw, out/'category-support.json'); _stage(_bytes(law), out/'marked-response.json')
    records = mp.category_mark_records(law); signatures = {r['id']: hashlib.sha256(mp._bytes(r)).hexdigest() for r in records}
    joint = {'schema_version': 1, 'sampling_unit': 'same_complete_IID_generator_groups_at_all_anchors', 'category_marks': records,
             'groups': [{'id': g, 'class_id': c['id'], 'category_mark_sha256': signatures[c['id']]} for c in cats for g in c['group_ids']]}
    reference = next(i for i, a in enumerate(d['anchors']) if a['point'] == [d['reference_point'][x['name']] for x in d['axes']])
    bin_indices = [bundle['destination_ids'].index(x) for x in fitted]
    classes = [{'id': c['id'], 'contribution': [c['weight']*alloc[k][reference][i] for i in bin_indices], 'denominator_mark': dm[k],
                'exposure': None, 'observed': len(c['group_ids']), 'observed_group_ids': c['group_ids'], 'initial': initial[k], 'source': 'support'} for k, c in enumerate(cats)]
    bins = [{'id': x, 'role': 'signal', 'source': 'support'} for x in fitted]
    ledger = {'schema_version': 1, 'sampling_law': 'iid_fixed_mark_categories', 'support_complete': True,
              'classes': [{k: c[k] for k in ('id', 'contribution', 'denominator_mark', 'exposure')} for c in classes],
              'groups': [{'id': g, 'class_id': c['id'], 'contribution': c['contribution'], 'denominator_mark': c['denominator_mark']} for c in classes for g in c['observed_group_ids']],
              'normalization': {'total_groups': total, 'kappa': scale, 'normalization_meaning': n['meaning']}, 'bins': [{'id': x, 'role': 'signal'} for x in fitted]}
    ledger_raw = _bytes(ledger); _stage(ledger_raw, out/'mc-ledger.json')
    sources = [{'id': 'support', 'path': 'category-support.json', 'sha256': hashlib.sha256(raw).hexdigest(), 'reference': support['source']},
               {'id': 'ledger', 'path': 'mc-ledger.json', 'sha256': hashlib.sha256(ledger_raw).hexdigest(), 'reference': 'complete constructed group ledger'},
               {'id': 'request', 'path': 'source-request.json', 'sha256': hashlib.sha256((out/'source-request.json').read_bytes()).hexdigest(), 'reference': 'explicit original normalization and source pins'}]
    model = mc.prepare({'schema_version': 2, 'model_id': 'constructed-complete-response-MC', 'sources': sources, 'bins': bins,
                'mc_design': {'kind': 'fixed_n_categories', 'sampling_law': 'iid_fixed_mark_categories', 'fixed_marks': True, 'support_complete': True,
                   'ledger_source': 'ledger', 'independence': 'iid_groups_within_one_fixed_N_stream', 'total_groups': total, 'kappa': scale, 'normalization_source': 'request', 'normalization_meaning': n['meaning']},
                'classes': classes, 'assumptions': ['Complete IID fixed-mark support is explicitly source-declared, not inferred from observed groups.', 'Calibration and generator independence remain separate scientific obligations.']})
    mc._ledger(model, ledger); mp.verify_group_marks(law, model, joint)
    _stage(_bytes(model), out/'mc-model.json'); _stage(_bytes(joint), out/'joint-mark-ledger.json')
    try: mp.smooth_mark_law(law); smooth = True
    except ValueError: smooth = False
    return {'marked_response': 'marked-response.json', 'MC_auxiliary': 'mc-model.json', 'joint_mark_ledger': 'joint-mark-ledger.json',
            'existing_provider_smoothness_compatible': smooth, 'source_domain_and_auxiliary_binding_required': True,
            'scientific_sampling_and_calibration_qualified': False, 'likelihood_created': False}


def _numerical_values(d, bundle, raw, out):
    """Expose exact binary64 outputs to the existing independent-reference checker.

    Radius zero describes the exact stored binary64 value, NOT an error bound
    on the underlying physical or mathematical quantity. Comparison bands and
    independently produced references belong to the separately pinned deck.
    """
    deck = _load(raw)
    _keys(deck, ('schema_version', 'kind', 'context', 'axes', 'components', 'training_points', 'heldout_points'))
    _require(type(deck['schema_version']) is int and deck['schema_version'] == 1 and deck['kind'] == 'numerical-reference-deck', 'existing numerical-reference deck schema1 required')
    _keys(deck['context'], ('quantity', 'model', 'process', 'normalization', 'domain', 'basis'))
    for x in deck['context'].values(): _text(x)
    _require(deck['context']['normalization'] == d['normalization']['meaning'], 'numerical comparison normalization meaning differs')
    _require([a['id'] for a in deck['axes']] == [a['name'] for a in d['axes']], 'complete ordered physical axis identity required')
    for a in deck['axes']:
        _keys(a, ('id', 'unit')); _text(a['unit'])
    mapping = d['numerical_projection']['component_map']
    names = _names([c['id'] for c in deck['components']]); _keys(mapping, names)
    _require(len(names) <= 32 and len(set(mapping.values())) == len(names) and set(mapping.values()) == set(bundle['destination_ids']), 'complete injective destination/component exposure required')
    components = []
    for c in deck['components']:
        _keys(c, ('id', 'unit', 'convention', 'atol', 'rtol')); _text(c['unit'])
        _require(c['convention'] == 'exact_binary64_value_not_a_certified_error_enclosure', 'numeric output convention must disclose binary64 and uncertified enclosure')
        components.append({k: c[k] for k in ('id', 'unit', 'convention')})
    from fractions import Fraction
    points = deck['training_points'] + deck['heldout_points']
    _require(type(deck['heldout_points']) is list and deck['heldout_points'] and len(points) == len(d['anchors']), 'complete independently declared training/held-out point census')
    indices = {tuple(Fraction(str(x)) for x in a['point']): i for i, a in enumerate(d['anchors'])}
    seen = set(); rows = []; ids = []
    for point in points:
        _keys(point, ('id', 'coordinates')); ids.append(_text(point['id']))
        coordinate = tuple(Fraction(x) for x in point['coordinates'])
        _require(coordinate in indices and coordinate not in seen, 'point IDs cannot substitute different or duplicate physical coordinates')
        seen.add(coordinate); anchor = indices[coordinate]
        values = {}
        for name, destination in mapping.items():
            i = bundle['destination_ids'].index(destination)
            value = bundle['weights'][d['weight_name']]['normalized_values'][anchor*len(bundle['destination_ids'])+i]
            numerator, denominator = value.as_integer_ratio()
            values[name] = {'mid': str(numerator)+'/'+str(denominator), 'radius': '0'}
        rows.append({'id': point['id'], 'coordinates': point['coordinates'], 'values': values})
    _names(ids)
    candidate = {'schema_version': 1, 'kind': 'numerical-point-values', 'context': deck['context'], 'axes': deck['axes'], 'components': components, 'rows': rows}
    target = _stage(_bytes(candidate), out/'numerical-point-values.json')
    return {'format': 'point-values/v1', 'candidate': str(target), 'deck_source_sha256': hashlib.sha256(raw).hexdigest(),
            'all_destination_components_exposed': True, 'independent_reference_required': True, 'physical_calibration_validated': False,
            'scope': 'existing numerical-reference-check input; exact binary64 result representation with no certified arithmetic enclosure'}


def run(task, base, out):
    p, d, captured, loaded = _request(task, base)
    output = Path(out)
    _require(not output.exists() and not any(q.is_symlink() for q in (output, *output.parents)), 'fresh response output directory without symlinks required')
    _require(not any(output.resolve() == q or output.resolve() in q.parents for q in captured), 'response output cannot contain original scientific inputs')
    output.mkdir(parents=True)
    _stage(captured[p], output/'source-request.json')
    if d['operation'] == 'fixed_event_migrations': destinations, rows, details = _fixed(d, loaded, output)
    else: destinations, rows, details = _llp(d, loaded, output)
    bundle = summarize(d, destinations, rows); details.update(bundle)
    if 'numerical_projection' in d:
        details['numerical_reference_handoff'] = _numerical_values(d, bundle, loaded[d['numerical_projection']['deck']['id']][1], output)
    if 'category_support' in d:
        details['existing_marked_MC_handoff'] = _handoff(d, bundle, loaded[d['category_support']['id']][1], output)
    _unchanged(captured)
    details['source_input_pins'] = [{'path': str(q), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for q, raw in sorted(captured.items())]
    details['checks_passed'] = True
    write_complete_json(details, output/'complete-response.json')
    return details, ['Response values are supplied or folded under an explicitly declared conditional law; physical calibration and runtime producer consumption are not established.',
                    'Complete shared-group Gram/delta moments are conditional engineering quantities, not an inferred independent Poisson, Gaussian or MC auxiliary law.',
                    'Fractional anchor allocation pairs do not identify stochastic cross-anchor detector transitions. No detector randomness is invented.',
                    'Interpolation is a new supplied piecewise-multilinear marked law only when complete IID support is explicitly supplied. No native calibration, published likelihood or fit is replaced.']
