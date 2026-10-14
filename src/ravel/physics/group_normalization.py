"""Source-bound N/W transform of complete independent event groups.

No native runner, experimental covariance, inference or acquisition admission is
provided. Counter weights are joined once per event, never once per histogram
fill. Normalized covariance is a first-order Poissonized group covariance, not
native YODA marginal-error propagation or fixed-N sample covariance.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path


class GroupNormalizationError(ValueError):
    pass


def _require(ok, message):
    if not ok:
        raise GroupNormalizationError(message)


def _keys(value, required, optional=()):
    _require(isinstance(value, dict) and set(required) <= set(value) <= set(required) | set(optional),
             'missing or unknown object keys')


def _number(value):
    _require(type(value) in (int, float), 'finite numeric value required')
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise GroupNormalizationError('finite numeric value required') from exc
    _require(math.isfinite(value), 'finite numeric value required')
    return value


def _text(value):
    _require(isinstance(value, str) and bool(value.strip()), 'nonempty identity required')
    return value


def _decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(GroupNormalizationError('nonfinite JSON')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GroupNormalizationError('strict UTF-8 JSON required') from exc


def _sources(pins, base_dir):
    _require(isinstance(pins, list) and 1 <= len(pins) <= 64, 'bounded source pins required')
    sources = {}
    paths = set()
    for pin in pins:
        _keys(pin, ('id', 'path', 'sha256', 'size'))
        ident = _text(pin['id'])
        _require(ident not in sources, 'duplicate source identity')
        path = Path(_text(pin['path']))
        if not path.is_absolute():
            path = Path(base_dir) / path
        _require(not path.is_symlink() and path.is_file(), 'regular nonsymlink source required')
        path = path.resolve()
        _require(path not in paths, 'duplicate resolved source path')
        paths.add(path)
        _require(type(pin['size']) is int and 0 <= pin['size'] <= 32_000_000, 'bounded source size required')
        _require(path.stat().st_size == pin['size'], 'source size differs')
        raw = path.read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == pin['sha256'], 'source hash differs')
        sources[ident] = raw
    return sources


def _definition(value, sources):
    _keys(value, ('source', 'first_line', 'last_line', 'text'))
    _require(value['source'] in sources, 'unbound normalization source')
    start, end = value['first_line'], value['last_line']
    _require(type(start) is int and type(end) is int and 1 <= start <= end, 'source line interval required')
    try:
        lines = sources[value['source']].decode('utf-8').splitlines()
    except UnicodeError as exc:
        raise GroupNormalizationError('source definition requires UTF-8 text') from exc
    _require(end <= len(lines) and '\n'.join(lines[start-1:end]) == value['text'], 'source definition excerpt differs')


def _gram(rows):
    """Each row is a coordinate's group contributions, in complete group order."""
    result = [[0.] * len(rows) for _ in rows]
    for i, left in enumerate(rows):
        for j in range(i, len(rows)):
            value = math.fsum(a*b for a, b in zip(left, rows[j]))
            _require(math.isfinite(value), 'group covariance overflows')
            result[i][j] = result[j][i] = value
    return result


def _up(value):
    _require(math.isfinite(value) and value >= 0, 'arithmetic enclosure overflows')
    return math.nextafter(value, math.inf)


def _positive_sum(terms):
    total = 0.
    for term in terms:
        total = _up(total + term)
    return total


def _product_bound(product):
    # Bound relative to the computed binary64 product, including subnormals.
    return _up(_up((2.**-53)/(1.-2.**-53) * abs(product)) + math.ulp(0.))


def _dot(terms):
    products = [a*b for a, b in terms if a != 0 and b != 0]
    if not products:
        return 0., 0.
    _require(all(math.isfinite(p) for p in products), 'linearized group product overflows')
    value = math.fsum(products)
    _require(math.isfinite(value), 'linearized group sum overflows')
    # Python documents a possible least-significant-bit double rounding in fsum.
    error = _positive_sum([*(_product_bound(p) for p in products),
                           _up(4*math.ulp(value)), 4*math.ulp(0.)])
    return value, error


def arithmetic_policy(contract):
    """Prospective opt-in; legacy absent policy keeps every original limit."""
    value = contract.get('arithmetic_policy')
    if value is None:
        _require('arithmetic_policy' not in contract, 'explicit null arithmetic policy refuses')
        return {'method': 'legacy_compensated', 'maximum_groups': 4096,
                'maximum_pair_group_products': 25_000_000}
    _keys(value, ('method', 'maximum_groups', 'maximum_pair_group_products'))
    _require(value['method'] == 'vectorized_products_compensated_sum_v1' and
             type(value['maximum_groups']) is int and 1 <= value['maximum_groups'] <= 20000 and
             type(value['maximum_pair_group_products']) is int and
             1 <= value['maximum_pair_group_products'] <= 100_000_000,
             'closed bounded full-cohort arithmetic policy required')
    return dict(value)


def arithmetic_budget(contract, coordinates, groups):
    policy = arithmetic_policy(contract)
    _require(coordinates <= 768 and groups <= policy['maximum_groups'] and
             coordinates**2*groups <= policy['maximum_pair_group_products'],
             'complete declared covariance arithmetic budget exceeded')
    return policy


def normalize(contract, acquired, *, base_dir='.'):
    """Return integrated components k*N/W, full joint J/C and retained RAW origin.

    Fixed coefficients include an explicitly supplied cross section and any
    source-declared constant/group-width factor. Finite bin widths are NOT
    applied here; integrated flows are scaled by the same source coefficient.
    A later exact finite slice may divide by its explicitly declared bin width.
    """
    _keys(contract, ('schema_version', 'kind', 'analysis_id', 'sources', 'acquisition_source',
                     'acquisition_contract_source', 'native_trace_source', 'raw_yoda_source',
                     'weights', 'components', 'group_rule', 'flow_policy', 'coefficient_uncertainty'), ('arithmetic_policy',))
    _require(type(contract['schema_version']) is int and contract['schema_version'] == 1 and
             contract['kind'] == 'group-normalization-contract', 'unsupported normalization contract')
    _require(contract['group_rule'] == 'independent_single_subevent' and
             contract['flow_policy'] == 'scale_integrated_flows' and
             contract['coefficient_uncertainty'] == 'fixed_conditional', 'unsupported group/flow/coefficient policy')
    _text(contract['analysis_id'])
    sources = _sources(contract['sources'], base_dir)
    _require(contract['acquisition_source'] in sources and
             _decode(sources[contract['acquisition_source']]) == acquired, 'acquired record is not source-bound')
    _keys(acquired, ('schema_version', 'native_analysis_alias', 'logical_source_routine', 'uninstrumented_source_sha256',
                     'basis', 'values', 'uncertainty', 'normalization_counter_by_weight', 'normalization_event_weights',
                     'source_file_encounter_groups', 'native_trace_sha256', 'raw_yoda_sha256', 'native_weight_cap',
                     'same_process_pid', 'group_rule', 'native_marginal_covariance_inferred', 'physics_validated',
                     'requires_separate_execution_custody_review', 'raw_primitive_cells_checked'),
                    ('model_candidate', 'model_native_semantics_qualified', 'normalization_scope', 'experimental_independence', 'limits'))
    _require(type(acquired.get('schema_version')) is int and acquired['schema_version'] == 2 and acquired.get('group_rule') == contract['group_rule'],
             'v2 complete independent acquisition required')
    _require(acquired.get('logical_source_routine') == contract['analysis_id'], 'logical routine differs')
    _require(type(acquired.get('native_weight_cap')) in (int, float) and acquired['native_weight_cap'] == 0 and acquired.get('native_marginal_covariance_inferred') is False,
             'unsupported weight cap or inferred native covariance')
    _require(type(acquired['same_process_pid']) is int and acquired['same_process_pid'] > 0 and
             type(acquired['source_file_encounter_groups']) is int, 'exact native process/group count types required')
    _require(acquired.get('physics_validated') is False and
             acquired.get('requires_separate_execution_custody_review') is True, 'acquisition review boundary required')
    for name in ('native_trace_sha256', 'raw_yoda_sha256', 'uninstrumented_source_sha256'):
        _require(isinstance(acquired.get(name), str) and re.fullmatch('[0-9a-f]{64}', acquired[name]), 'exact acquisition origin required')
    for origin, digest in [('native_trace_source', 'native_trace_sha256'), ('raw_yoda_source', 'raw_yoda_sha256')]:
        _require(contract[origin] in sources and hashlib.sha256(sources[contract[origin]]).hexdigest() == acquired[digest],
                 'exact complete trace/RAW origin binding required')
    _require(acquired['uninstrumented_source_sha256'] in {hashlib.sha256(raw).hexdigest() for raw in sources.values()},
             'original routine source bytes must be pinned')
    _require(contract['acquisition_contract_source'] in sources, 'original acquisition contract required')
    original = _decode(sources[contract['acquisition_contract_source']])
    _require(isinstance(original, dict), 'original acquisition contract object required')
    for field, actual in [('schema_version', 2), ('native_analysis_alias', acquired['native_analysis_alias']),
                          ('routine', acquired['logical_source_routine']), ('original_source_sha256', acquired['uninstrumented_source_sha256']),
                          ('same_process_pid', acquired['same_process_pid']), ('native_weight_cap', 0),
                          ('group_rule', contract['group_rule'])]:
        _require(original.get(field) == actual, 'original acquisition contract origin differs')

    _require(isinstance(contract['weights'], list) and 1 <= len(contract['weights']) <= 16,
             'bounded named weight list required')
    weights = []
    for record in contract['weights']:
        _keys(record, ('id', 'counter_id', 'weight_policy'))
        weight = _text(record['id'])
        _require(weight not in weights and record['weight_policy'] in ('signed', 'nonnegative'), 'named weight census/policy differs')
        _text(record['counter_id']); weights.append(weight)
    _require(1 <= len(weights) <= 16 and weights[0] == 'nominal', 'bounded nominal-first named weights required')
    counter_ids = [r['counter_id'] for r in contract['weights']]
    _require(len(set(counter_ids)) == len(counter_ids), 'unique scalar counter identities required')
    _require(isinstance(acquired['normalization_counter_by_weight'], dict) and
             set(acquired['normalization_counter_by_weight']) == set(weights), 'complete selected counter weight census required')
    names = original.get('weight_mapping')
    _require(isinstance(names, list) and all(isinstance(r, dict) for r in names) and [r.get('id') for r in names] == weights and
             all(isinstance(r.get('native'), str) and isinstance(r.get('raw_suffix'), str) for r in names) and
             len({r['native'] for r in names}) == len(names) and len({r['raw_suffix'] for r in names}) == len(names),
             'exact original selected native weight label/suffix/order required')
    basis = acquired['basis']
    _require(isinstance(basis, list) and 1 <= len(basis) + len(weights) <= 768, 'bounded complete acquired basis required')
    _require(isinstance(contract['components'], list) and 1 <= len(contract['components']) <= 64, 'bounded component list required')
    components = {}; geometry = {}; output_map = {}
    for component in contract['components']:
        _keys(component, ('id', 'output', 'quantity', 'fixed_coefficients', 'denominator_policy', 'definition'))
        ident, output = _text(component['id']), _text(component['output'])
        _require(ident not in components and output not in output_map, 'duplicate source/component binding')
        _definition(component['definition'], sources)
        quantity = component['quantity']
        _keys(quantity, ('axis', 'bins', 'unit', 'representation'))
        _keys(quantity['axis'], ('name', 'unit'))
        _text(quantity['axis']['name']); _text(quantity['axis']['unit']); _text(quantity['unit'])
        _require(quantity['representation'] == 'integrated', 'normalization transforms integrated quantities only')
        bins = quantity['bins']
        _require(isinstance(bins, list) and 1 <= len(bins) <= 128, 'finite declared geometry required')
        previous = None; bin_map = {}
        for b in bins:
            _keys(b, ('id', 'low', 'high'))
            bin_id = _text(b['id']); low, high = _number(b['low']), _number(b['high'])
            _require(bin_id not in bin_map and bin_id not in ('underflow', 'overflow') and
                     low < high and (previous is None or low == previous), 'exact contiguous unique bin geometry required')
            bin_map[bin_id] = (low, high); previous = high
        geometry[ident] = {'underflow': (None, _number(bins[0]['low'])), **bin_map,
                           'overflow': (_number(bins[-1]['high']), None)}
        _require(component['denominator_policy'] in ('positive', 'nonzero_signed'), 'explicit normalization denominator policy required')
        coefficients = component['fixed_coefficients']
        _require(isinstance(coefficients, dict) and set(coefficients) == set(weights), 'complete fixed coefficient weight census required')
        for coefficient in coefficients.values():
            _keys(coefficient, ('value', 'unit', 'source', 'semantics'))
            _require(_number(coefficient['value']) > 0 and coefficient['unit'] == quantity['unit'] and
                     coefficient['source'] in sources and coefficient['semantics'] == 'fixed_cross_section_times_source_factor',
                     'positive source-bound fixed cross-section coefficient required')
        components[ident] = component; output_map[output] = ident
    _require(1 <= len(components) <= 64, 'bounded component census required')
    expected = {(w, c, b) for w in weights for c in components for b in geometry[c]}
    keys = []
    for row in basis:
        _keys(row, ('weight', 'output', 'native_path', 'bin', 'unit', 'axis_unit', 'low', 'high'))
        _text(row['native_path'])
        _require(row['output'] in output_map, 'missing or extra source output binding')
        c = output_map[row['output']]; key = (row['weight'], c, row['bin'])
        _require(key in expected and row['unit'] == '1' and row['axis_unit'] == components[c]['quantity']['axis']['unit'] and
                 (row['low'], row['high']) == geometry[c][row['bin']], 'exact acquired axis/edge/unit join required')
        keys.append(key)
    _require(len(keys) == len(set(keys)) and set(keys) == expected, 'full finite/flow/weight/component census differs')
    original_outputs = original.get('outputs')
    _require(isinstance(original_outputs, list) and all(isinstance(r, dict) for r in original_outputs) and len(original_outputs) == len(components) and
             {r.get('id') for r in original_outputs} == set(output_map), 'original complete output census differs')
    for o in original_outputs:
        c = components[output_map[o['id']]]; q = c['quantity']
        edges = [b['low'] for b in q['bins']]+[q['bins'][-1]['high']]
        native_paths = {r['native_path'] for r in basis if r['output'] == o['id']}
        _require(native_paths == {o.get('path')} and o.get('edges') == edges and o.get('axis_unit') == q['axis']['unit'] and
                 o.get('unit') == '1', 'original acquisition output geometry/unit/path differs')
    uncertainty = acquired['uncertainty']
    _keys(uncertainty, ('kind', 'semantics', 'groups'))
    _require(uncertainty['kind'] == 'independent_groups' and uncertainty['semantics'] == 'uncentered_poissonized_second_moment',
             'complete independent group moments required; no marginal conversion')
    groups = uncertainty['groups']; events = acquired['normalization_event_weights']
    _require(isinstance(groups, list) and 1 <= len(groups) <= arithmetic_policy(contract)['maximum_groups'] and isinstance(events, list) and len(events) == len(groups),
             'complete full-event group/counter census required')
    n = len(keys); m = len(groups)
    original_events = original.get('events')
    _require(isinstance(original_events, list) and len(original_events) == m and all(isinstance(e, dict) for e in original_events),
             'original full event population differs')
    arithmetic = arithmetic_policy(contract)
    if arithmetic['method'] == 'legacy_compensated':
        _require((n+len(weights))**2*m <= 25_000_000, 'finite covariance arithmetic budget exceeded')
    else:
        arithmetic_budget(contract, n+len(weights), m)
    group_ids = []; vectors = []
    for g, event, origin in zip(groups, events, original_events):
        _keys(g, ('id', 'values')); _keys(event, ('id', 'weights'))
        ident = _text(g['id'])
        _require(re.fullmatch('[0-9a-f]{64}:[0-9]+', ident) and ident not in group_ids and event['id'] == ident,
                 'unique exact source-file encounter/counter group alignment required')
        group_ids.append(ident)
        _require(isinstance(g['values'], list) and len(g['values']) == n and
                 isinstance(event['weights'], dict) and set(event['weights']) == set(weights), 'complete group coordinate/weight vector required')
        hist = [_number(v) for v in g['values']]; counter = [_number(event['weights'][w]) for w in weights]
        _require(origin.get('input_sha256', '')+':'+str(origin.get('encounter_ordinal')) == ident and
                 origin.get('selected_weights') == counter, 'original exact encounter identity/effective weights differ')
        for i, key in enumerate(keys):
            policy = contract['weights'][weights.index(key[0])]['weight_policy']
            _require(policy != 'nonnegative' or (hist[i] >= 0 and counter[weights.index(key[0])] >= 0),
                     'signed contribution violates declared nonnegative policy')
        vectors.append(hist+counter)
    _require(acquired['source_file_encounter_groups'] == m, 'acquisition group count differs')
    input_values = [math.fsum(row[i] for row in vectors) for i in range(n+len(weights))]
    _require(isinstance(acquired['values'], list) and len(acquired['values']) == n and
             [_number(v) for v in acquired['values']] == input_values[:n], 'acquired central sums differ from complete groups')
    counter_diagnostics = {}
    for k, w in enumerate(weights):
        counter = acquired['normalization_counter_by_weight'][w]
        _keys(counter, ('sumw', 'sumw2', 'entries', 'raw_tokens'))
        W = input_values[n+k]; Q = math.fsum(row[n+k]*row[n+k] for row in vectors)
        _require(type(counter['entries']) is int and counter['entries'] == m and
                 _number(counter['sumw']) == W and _number(counter['sumw2']) == Q,
                 'once-per-event counter moments/entries differ')
        _require(isinstance(counter['raw_tokens'], list) and len(counter['raw_tokens']) == 3 and
                 all(isinstance(t, str) and math.isfinite(float(t)) for t in counter['raw_tokens']), 'complete native counter literals required')
        counter_diagnostics[w] = {'sumw': W, 'sumw2': Q, 'entries': m, 'scalar_coordinate': n+k,
                                  'native_raw_tokens_separate': counter['raw_tokens']}
    input_rows = list(map(list, zip(*vectors)))
    input_arithmetic = None
    if arithmetic['method'] == 'legacy_compensated':
        input_covariance = _gram(input_rows)
    else:
        from . import group_arithmetic
        input_arithmetic = group_arithmetic.gram(input_rows, maximum_pair_products=arithmetic['maximum_pair_group_products'])
        input_covariance = input_arithmetic['matrix']
    values = []; jacobian = []; normalized_rows = []; error_rows = []; factors = []
    for i, (w, c, bin_id) in enumerate(keys):
        wi = weights.index(w); W = input_values[n+wi]; N = input_values[i]
        policy = components[c]['denominator_policy']
        _require(W > 0 if policy == 'positive' else W != 0, 'zero/inadmissible full-event normalization denominator')
        coefficient = _number(components[c]['fixed_coefficients'][w]['value'])
        alpha = coefficient/W; value = alpha*N; beta = -value/W
        _require(all(math.isfinite(v) for v in (alpha, value, beta)), 'normalization/Jacobian overflows')
        _require(alpha != 0., 'nonzero normalization factor/derivative underflows')
        _require(N == 0. or value != 0., 'nonzero normalized central underflows')
        _require(value == 0. or beta != 0., 'nonzero normalization counter derivative underflows')
        row = [0.]*(n+len(weights)); row[i] = alpha; row[n+wi] = beta
        phi = [_dot([(alpha, g[i]), (beta, g[n+wi])]) for g in vectors]
        values.append(value); jacobian.append(row)
        normalized_rows.append([p[0] for p in phi]); error_rows.append([p[1] for p in phi])
        factors.append({'weight': w, 'component': c, 'bin': bin_id, 'fixed_coefficient': coefficient,
                        'counter': W, 'counter_coordinate': n+wi, 'denominator_policy': policy})
    output_arithmetic = None
    if arithmetic['method'] != 'legacy_compensated':
        output_arithmetic = group_arithmetic.gram(normalized_rows, error=error_rows,
            maximum_pair_products=arithmetic['maximum_pair_group_products'])
        covariance = output_arithmetic['matrix']
        maximum_error = output_arithmetic['maximum_entry_forward_error_bound']
    else:
        covariance = [[0.]*n for _ in range(n)]; maximum_error = 0.
        active = [i for i in range(n) if any(normalized_rows[i]) or any(error_rows[i])]
        for position, i in enumerate(active):
            for j in active[position:]:
                value, dot_error = _dot(zip(normalized_rows[i], normalized_rows[j]))
                phi_error = _positive_sum(_positive_sum([_up(abs(a)*eb), _up(abs(b)*ea), _up(ea*eb)])
                                          for a, b, ea, eb in zip(normalized_rows[i], normalized_rows[j], error_rows[i], error_rows[j]))
                bound = _positive_sum([dot_error, phi_error])
                covariance[i][j] = covariance[j][i] = value
                maximum_error = max(maximum_error, bound)
    # Recheck every pinned origin at the end of this arithmetic operation.
    _require(_sources(contract['sources'], base_dir) == sources, 'source changed during normalization')
    result = {'schema_version': 1, 'kind': 'group-normalization-result', 'analysis_id': contract['analysis_id'],
              'sources': contract['sources'], 'acquisition_source': contract['acquisition_source'],
              'acquisition_contract_source': contract['acquisition_contract_source'],
              'contract': contract, 'components': contract['components'],
              'input_basis': [dict(row, kind='histogram') for row in basis] +
                             [{'kind': 'normalization_counter', 'weight': w, 'counter': contract['weights'][k]['counter_id'], 'unit': '1'}
                              for k, w in enumerate(weights)],
              'input_values': input_values, 'input_covariance': input_covariance,
              'input_groups': [{'id': ident, 'vector': v} for ident, v in zip(group_ids, vectors)],
              'output_basis': [{'weight': w, 'component': c, 'bin': b} for w, c, b in keys],
              'values': values, 'output_covariance': covariance, 'jacobian': jacobian,
              'linearized_group_vectors': [{'id': ident, 'vector': [r[g] for r in normalized_rows]} for g, ident in enumerate(group_ids)],
              'linearized_groups_are_central_contributions': False,
              'representability_policy': 'Nonzero k/W, nonzero (k/W)*N when N!=0, and nonzero -y/W when y!=0 must survive binary64 evaluation; otherwise refuse. Representable subnormals and exact zero central/group-gradient cancellation remain allowed. Covariance product underflow is covered only by the emitted-J forward enclosure.',
              'normalization_factors': factors, 'counter_diagnostics': counter_diagnostics,
              'covariance_maximum_entry_forward_error_bound': maximum_error,
              'forward_error_scope': 'Exact-real Gram of J_float times the supplied binary64 complete groups. Product/fsum rounding is enclosed; this does not enclose source-real Jacobian modelling or source decimal uncertainty.',
              'native_marginals_separate': {'raw_yoda_sha256': acquired['raw_yoda_sha256'],
                                           'primitive_cells_checked': acquired['raw_primitive_cells_checked'],
                                           'counter_by_weight': acquired['normalization_counter_by_weight'],
                                           'histogram_error_transport': 'Original native RAW remains pinned; no native histogram errors or sumW2 are inferred from group covariance.'},
              'uncertainty_scope': 'First-order normalized uncentered Poissonized independent-group covariance. Fixed cross-section coefficients are conditional; no fixed-N, sparse calibration, theory covariance or native marginal-error equivalence.',
              'experimental_independence': None, 'requires_separate_execution_custody_review': True,
              'native_acquisition_qualified': False, 'inference': None, 'physics_validated': False}
    if arithmetic['method'] != 'legacy_compensated':
        result['arithmetic_admission'] = {'policy': arithmetic,
            'input_entry_forward_error_bounds': input_arithmetic['entry_forward_error_bounds'],
            'output_entry_forward_error_bounds': output_arithmetic['entry_forward_error_bounds'],
            'method': output_arithmetic['algorithm'], 'scope': output_arithmetic['scope']}
    return copy.deepcopy(result)


def derive_from_file(path, *, expected_sha256):
    path = Path(path)
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 1_000_000, 'bounded regular contract required')
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'contract hash differs')
    contract = _decode(raw); sources = _sources(contract['sources'], path.parent)
    _require(contract['acquisition_source'] in sources, 'bound acquisition source required')
    return normalize(contract, _decode(sources[contract['acquisition_source']]), base_dir=path.parent)


def derived_joint(result):
    """Supply normalized central components/full covariance to existing derive().

    The linearized group vectors do not sum to normalized centrals, so they MUST
    NOT be relabelled as the existing independent_group_moments input schema.
    The caller must pin this result and explicitly bind its normalized geometry,
    source contract, coefficients and acquisition in the next derived contract.
    """
    _require(result.get('kind') == 'group-normalization-result', 'normalization result required')
    return copy.deepcopy({'schema_version': 1, 'basis': result['output_basis'], 'values': result['values'],
                          'uncertainty': {'kind': 'supplied_covariance', 'matrix': result['output_covariance'],
                                          'semantics': result['uncertainty_scope']}})


def finite_slice(result, basis, *, representation='integrated'):
    """Select an exact explicit single-weight finite component basis and full C.

    Differential values divide by the SAME declared finite bin widths once.
    This is a coordinate/unit transform, not an experimental independence claim.
    """
    _require(result.get('kind') == 'group-normalization-result', 'normalization result required')
    _require(isinstance(basis, list) and bool(basis) and representation in ('integrated', 'differential'), 'explicit finite prediction slice required')
    available = [tuple(r[k] for k in ('weight', 'component', 'bin')) for r in result['output_basis']]
    requested = []
    for row in basis:
        _keys(row, ('weight', 'component', 'bin'))
        requested.append(tuple(_text(row[k]) for k in ('weight', 'component', 'bin')))
    _require(len(set(requested)) == len(requested) and len({r[0] for r in requested}) == 1 and
             set(requested) <= set(available) and all(r[2] not in ('underflow', 'overflow') for r in requested),
             'unique single-weight exact finite component slice required')
    components = {c['id']: c for c in result['components']}; scales = []; units = []
    for w, c, b in requested:
        q = components[c]['quantity']; cell = next(v for v in q['bins'] if v['id'] == b)
        width = _number(_number(cell['high'])-_number(cell['low']))
        _require(width > 0, 'finite positive bin width required')
        scale = _number(1. if representation == 'integrated' else 1./width)
        _require(scale > 0, 'finite positive density scale required')
        scales.append(scale)
        units.append(q['unit'] if representation == 'integrated' or q['axis']['unit'] == '1' else q['unit']+'/'+q['axis']['unit'])
    indices = [available.index(r) for r in requested]
    values = []
    for i, s in zip(indices, scales):
        source_value = _number(result['values'][i])
        value = _number(source_value*s)
        _require(source_value == 0. or value != 0., 'nonzero finite-slice central underflows')
        values.append(value)
    covariance = [[0.]*len(indices) for _ in indices]; maximum_error = 0.
    for a, i in enumerate(indices):
        for b in range(a, len(indices)):
            first = result['output_covariance'][i][indices[b]]*scales[a]
            value = first*scales[b]
            _require(math.isfinite(value), 'finite-slice covariance overflows')
            covariance[a][b] = covariance[b][a] = value
            source_error = _up(_up(result['covariance_maximum_entry_forward_error_bound']*scales[a])*scales[b])
            error = _positive_sum([source_error, _up(_product_bound(first)*scales[b]), _product_bound(value)])
            maximum_error = max(maximum_error, error)
    return copy.deepcopy({'schema_version': 1, 'kind': 'normalized-component-slice', 'basis': basis,
                          'values': values, 'units': units,
                          'covariance': covariance,
                          'covariance_maximum_entry_forward_error_bound': maximum_error,
                          'forward_error_scope': 'Original normalized Gram enclosure times the emitted binary64 finite coordinate scales, plus two-product rounding. It does not enclose exact-real source edge subtraction, reciprocal rounding, source-real Jacobian modelling or physical uncertainty.',
                          'representation': representation, 'projection_indices': indices, 'coordinate_scales': scales,
                          'sources': result['sources'], 'acquisition_source': result['acquisition_source'],
                          'method': 'first_order_delta_method', 'experimental_independence': None,
                          'inference': None, 'physics_validated': False})


def validate(spec):
    """Closed supplied-record task with an externally pinned outer contract."""
    _keys(spec, ('schema_version', 'input', 'contract_sha256'))
    _require(type(spec['schema_version']) is int and spec['schema_version'] == 1,
             'unsupported group normalization task schema')
    _text(spec['input'])
    _require(isinstance(spec['contract_sha256'], str) and
             re.fullmatch('[0-9a-f]{64}', spec['contract_sha256']), 'exact contract digest required')
    return copy.deepcopy(spec)


def inputs(spec, base):
    """Inventory original contract/record/source/trace/RAW pins without arithmetic.

    The retained acquisition is supplied input. Its labels and byte custody do
    not qualify a native observer, event projection, model or covariance law.
    """
    from ravel.workflow.science import regular
    spec = validate(spec)
    path = regular(spec['input'], base)
    _require(path.stat().st_size <= 1_000_000, 'bounded regular contract required')
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == spec['contract_sha256'], 'contract hash differs')
    contract = _decode(raw)
    _require(isinstance(contract, dict) and type(contract.get('schema_version')) is int and
             contract['schema_version'] == 1 and contract.get('kind') == 'group-normalization-contract',
             'unsupported normalization contract')
    arithmetic_policy(contract)
    sources = _sources(contract.get('sources'), path.parent)
    _require(all(contract.get(key) in sources for key in
                 ('acquisition_source', 'acquisition_contract_source', 'native_trace_source', 'raw_yoda_source')),
             'complete acquisition/contract/trace/RAW origin pins required')
    files = [path]
    for pin in contract['sources']:
        source = regular(pin['path'], path.parent)
        _require(source not in files, 'repeated operation input path')
        files.append(source)
    return files


def run(spec, base, out):
    """Deliver deterministic supplied-group normalization in a fresh directory."""
    from ravel.workflow.state_io import atomic_json
    path = inputs(spec, base)[0]
    result = derive_from_file(path, expected_sha256=spec['contract_sha256'])
    result['status'] = 'passed'
    result['status_scope'] = 'Supplied source-bound group normalization and conditional first-order joint covariance only'
    result['input'] = {'path': str(path), 'sha256': spec['contract_sha256']}
    out = Path(out)
    _require(not out.exists() and not out.is_symlink(), 'fresh normalization output directory required')
    out.mkdir(parents=True, exist_ok=False)
    atomic_json(out/'group-normalization.json', result)
    atomic_json(out/'normalized-joint.json', derived_joint(result))
    return result
