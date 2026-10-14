"""Portable synthetic whole-event normalization controls.

Every source/contract/trace/RAW input is fabricated in tmp_path. No ignored
scientific corpus, private acquisition module, native tool or model is required.
"""
import copy
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from ravel.physics import group_normalization as g



def pin(path, ident):
    raw = path.read_bytes()
    return {'id': ident, 'path': str(path), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def definition(path, start, end):
    return {'source': 'routine', 'first_line': start, 'last_line': end,
            'text': '\n'.join(path.read_text().splitlines()[start-1:end])}


def save_acquired(contract, acquired, directory):
    path = directory/'acquired.json'
    path.write_text(json.dumps(acquired, allow_nan=False))
    contract['sources'] = [p for p in contract['sources'] if p['id'] != 'acquired'] + [pin(path, 'acquired')]


def save_original(contract, acquired, directory, original=None):
    weights = [r['id'] for r in contract['weights']]
    if original is None:
        original = {'schema_version': 2, 'native_analysis_alias': acquired['native_analysis_alias'],
                    'routine': acquired['logical_source_routine'], 'original_source_sha256': acquired['uninstrumented_source_sha256'],
                    'group_rule': acquired['group_rule'], 'same_process_pid': acquired['same_process_pid'], 'native_weight_cap': 0,
                    'weight_mapping': [{'id': w, 'native': '' if w == 'nominal' else w, 'raw_suffix': '' if w == 'nominal' else '['+w+']'} for w in weights],
                    'outputs': [{'id': c['output'], 'path': next(b['native_path'] for b in acquired['basis'] if b['output'] == c['output']),
                                 'edges': [b['low'] for b in c['quantity']['bins']]+[c['quantity']['bins'][-1]['high']],
                                 'axis_unit': c['quantity']['axis']['unit'], 'unit': '1'} for c in contract['components']],
                    'events': [{'input_sha256': row['id'].split(':')[0], 'encounter_ordinal': int(row['id'].split(':')[1]),
                                'event_number': i, 'selected_weights': [row['weights'][w] for w in weights]}
                               for i, row in enumerate(acquired['normalization_event_weights'])]}
    path = directory/'original-acquisition-contract.json'; path.write_text(json.dumps(original))
    contract['sources'] = [p for p in contract['sources'] if p['id'] != 'original-contract']+[pin(path, 'original-contract')]


def fixture(directory):
    source = directory/'normalization-definition.txt'
    source.write_text('Synthetic fixed coefficient times histogram sum divided by once-per-event sumW.\n')
    weights = ['nominal', 'closure-up']; outputs = ['numerator', 'denominator']
    bins = [{'id': '0', 'low': 0., 'high': 1.}, {'id': '1', 'low': 1., 'high': 3.}]
    cells = [('underflow', None, 0.), ('0', 0., 1.), ('1', 1., 3.), ('overflow', 3., None)]
    basis = [{'weight': w, 'output': o, 'native_path': '/structural/'+o, 'bin': b,
              'unit': '1', 'axis_unit': 'GeV', 'low': lo, 'high': hi}
             for w in weights for o in outputs for b, lo, hi in cells]
    # Same event can fill a histogram twice. Rejected and zero-weight events
    # remain in the full counter population. Variations need not be multiples.
    event_weights = [[2., 3.], [-.5, -.4], [0., 0.], [1.5, 1.], [1., 2.]]
    counts = [[1, 2, 0, 0, 0, 1, 1, 0], [0, 0, 1, 0, 0, 0, 1, 0],
              [0, 1, 0, 1, 0, 1, 0, 0], [0]*8, [0, 0, 1, 1, 0, 1, 0, 0]]
    groups = [{'id': 'a'*64+':'+str(i), 'values': [v*c for v in ws for c in row]}
              for i, (ws, row) in enumerate(zip(event_weights, counts))]
    counters = {w: {'sumw': math.fsum(v[k] for v in event_weights),
                    'sumw2': math.fsum(v[k]*v[k] for v in event_weights), 'entries': len(groups),
                    'raw_tokens': [format(math.fsum(v[k] for v in event_weights), '.17e'),
                                   format(math.fsum(v[k]*v[k] for v in event_weights), '.17e'), '5.00000000000000000e+00']}
                for k, w in enumerate(weights)}
    acquired = {'schema_version': 2, 'native_analysis_alias': 'structural-only',
                'logical_source_routine': 'synthetic-group-normalization', 'uninstrumented_source_sha256': pin(source, 'routine')['sha256'],
                'model_candidate': False, 'model_native_semantics_qualified': None, 'basis': basis,
                'values': [math.fsum(row['values'][i] for row in groups) for i in range(len(basis))],
                'uncertainty': {'kind': 'independent_groups', 'semantics': 'uncentered_poissonized_second_moment', 'groups': groups},
                'normalization_counter_by_weight': counters,
                'normalization_event_weights': [{'id': row['id'], 'weights': dict(zip(weights, ws))} for row, ws in zip(groups, event_weights)],
                'normalization_scope': 'Synthetic source-formula arithmetic fixture; no native trace',
                'raw_primitive_cells_checked': 86, 'source_file_encounter_groups': len(groups),
                'native_trace_sha256': 'b'*64, 'raw_yoda_sha256': 'c'*64, 'native_weight_cap': 0, 'same_process_pid': 42,
                'group_rule': 'independent_single_subevent', 'native_marginal_covariance_inferred': False,
                'experimental_independence': None, 'physics_validated': False, 'requires_separate_execution_custody_review': True}
    contract = {'schema_version': 1, 'kind': 'group-normalization-contract', 'analysis_id': acquired['logical_source_routine'],
                'sources': [pin(source, 'routine')], 'acquisition_source': 'acquired',
                'acquisition_contract_source': 'original-contract', 'native_trace_source': 'trace', 'raw_yoda_source': 'RAW',
                'weights': [{'id': w, 'counter_id': 'event-sumw/'+w, 'weight_policy': 'signed'} for w in weights],
                'components': [{'id': o, 'output': o,
                                'quantity': {'axis': {'name': 'structural-x', 'unit': 'GeV'}, 'bins': bins, 'unit': 'fb', 'representation': 'integrated'},
                                'fixed_coefficients': {w: {'value': 3., 'unit': 'fb', 'source': 'routine',
                                                            'semantics': 'fixed_cross_section_times_source_factor'} for w in weights},
                                'denominator_policy': 'positive', 'definition': definition(source, 1, 1)} for o in outputs],
                'group_rule': 'independent_single_subevent', 'flow_policy': 'scale_integrated_flows', 'coefficient_uncertainty': 'fixed_conditional'}
    for origin, key, name in [('native_trace_sha256', 'trace', 'synthetic-trace.json'), ('raw_yoda_sha256', 'RAW', 'synthetic-RAW.json')]:
        path = directory/name; path.write_text(json.dumps({'kind': 'synthetic-only-not-native', 'origin': name, 'counts': counts, 'weights': event_weights}))
        acquired[origin] = pin(path, key)['sha256']; contract['sources'].append(pin(path, key))
    save_original(contract, acquired, directory); save_acquired(contract, acquired, directory)
    return contract, acquired


@pytest.fixture
def records(tmp_path):
    return fixture(tmp_path)


def test_counter_once_per_group_full_population_and_native_separation(records):
    c, a = records; r = g.normalize(c, a)
    assert len(r['input_basis']) == len(a['basis'])+2
    assert len(r['input_groups']) == 5
    assert sum(row['kind'] == 'normalization_counter' for row in r['input_basis']) == 2
    assert r['counter_diagnostics']['nominal'] == {'sumw': 4., 'sumw2': 7.5, 'entries': 5, 'scalar_coordinate': 16,
                                                 'native_raw_tokens_separate': a['normalization_counter_by_weight']['nominal']['raw_tokens']}
    assert r['input_groups'][0]['vector'][1] == 4. and r['input_groups'][0]['vector'][16] == 2.
    assert r['input_covariance'][1][1] == 16.  # repeated-fill group square
    assert r['input_covariance'][1][16] == 8.  # two fills, one event counter
    assert r['input_covariance'][16][16] == 7.5  # rejected event still contributes
    assert r['native_marginals_separate']['raw_yoda_sha256'] == a['raw_yoda_sha256']
    assert 'no native histogram errors' in r['native_marginals_separate']['histogram_error_transport']
    assert r['experimental_independence'] is None and not r['native_acquisition_qualified'] and not r['physics_validated']


def test_exact_joint_cross_weight_and_cross_output_covariance(records):
    r = g.normalize(*records); V = np.asarray([v['vector'] for v in r['input_groups']]); J = np.asarray(r['jacobian'])
    assert np.array_equal(np.asarray(r['input_covariance']), V.T@V)
    C = np.asarray(r['output_covariance'])
    assert np.array_equal(C, C.T)
    assert C[1, 5] != 0 and C[1, 9] != 0  # across outputs and named weights
    # Direct whole matrix contraction is a separate numerical check, not a
    # source covariance reconstruction from native marginal Q.
    assert np.max(np.abs(C-(J@V.T)@(V@J.T))) < 2e-14
    assert np.linalg.eigvalsh(C).min() > -2e-14


def test_exact_fraction_emitted_j_group_gram_enclosed(records):
    r = g.normalize(*records); F = Fraction.from_float
    vectors = [row['vector'] for row in r['input_groups']]
    phi = [[sum((F(j)*F(v) for j, v in zip(row, group)), Fraction()) for group in vectors] for row in r['jacobian']]
    bound = F(r['covariance_maximum_entry_forward_error_bound'])
    for i, row in enumerate(r['output_covariance']):
        for j, value in enumerate(row):
            exact = sum((a*b for a, b in zip(phi[i], phi[j])), Fraction())
            assert abs(F(value)-exact) <= bound
    assert not r['linearized_groups_are_central_contributions']
    joint = g.derived_joint(r)
    assert joint['uncertainty']['kind'] == 'supplied_covariance'
    assert 'groups' not in joint['uncertainty']


def test_finite_difference_all_counter_histogram_coordinates(records):
    r = g.normalize(*records); x = np.asarray(r['input_values']); J = np.asarray(r['jacobian'])
    def transform(z):
        return np.asarray([f['fixed_coefficient']*z[i]/z[f['counter_coordinate']] for i, f in enumerate(r['normalization_factors'])])
    for i in range(len(x)):
        h = 2.**-15*max(1., abs(x[i])); plus = x.copy(); minus = x.copy(); plus[i] += h; minus[i] -= h
        coarse = (transform(plus)-transform(minus))/(2*h)
        plus[i] = x[i]+h/2; minus[i] = x[i]-h/2
        fine = (transform(plus)-transform(minus))/h
        # Source count: coordinate perturbation, k*N, divide, subtraction,
        # difference division and emitted-J rounding. Sixteen eps covers this
        # fixed operation population; it is not fitted to observed residuals.
        guard = 16*np.finfo(float).eps*max(1., np.max(np.abs(transform(plus))), np.max(np.abs(transform(minus))))/h
        truncation = np.zeros(len(J))
        if i >= len(r['values']):
            for k, factor in enumerate(r['normalization_factors']):
                if factor['counter_coordinate'] == i:
                    W = x[i]; delta = h/2
                    truncation[k] = abs(J[k, i])*delta*delta/(W*W-delta*delta)
        assert np.max(np.abs(fine-J[:, i])-truncation) <= guard
        if i >= len(r['values']):
            assert np.max(np.abs(fine-J[:, i])) <= np.max(np.abs(coarse-J[:, i]))/3.9+guard


def test_signed_zero_rejected_events_and_common_weight_scale_invariance(records, tmp_path):
    c, a = records; before = g.normalize(c, a); scaled = copy.deepcopy(a)
    for row in scaled['uncertainty']['groups']: row['values'] = [2*v for v in row['values']]
    for row in scaled['normalization_event_weights']: row['weights'] = {k: 2*v for k, v in row['weights'].items()}
    scaled['values'] = [2*v for v in scaled['values']]
    for counter in scaled['normalization_counter_by_weight'].values(): counter['sumw'] *= 2; counter['sumw2'] *= 4
    save_original(c, scaled, tmp_path); save_acquired(c, scaled, tmp_path); after = g.normalize(c, scaled)
    assert before['values'] == after['values'] and before['output_covariance'] == after['output_covariance']
    assert all(v == 0 for v in before['input_groups'][2]['vector'])
    assert any(v < 0 for v in before['input_groups'][1]['vector'])
    assert all(v == 0 for v in before['input_groups'][3]['vector'][:16])
    assert before['input_groups'][3]['vector'][16] > 0


def test_counter_correlation_changes_uncertainty_vs_fixed_exposure(records):
    r = g.normalize(*records); i = 1; alpha = r['jacobian'][i][i]
    incorrect = alpha*alpha*r['input_covariance'][i][i]
    assert r['output_covariance'][i][i] != incorrect
    # Perfectly inclusive one-bin observable N=W has zero first-order
    # normalization uncertainty, not a fitted uncertainty from marginal bars.
    W = 4.; ws = [2., -.5, 0., 1.5, 1.]
    assert math.fsum((3./W*w-3./W*w)**2 for w in ws) == 0


def test_full_event_population_not_selected_population(records, tmp_path):
    c, a = records; original = g.normalize(c, a)
    # Removing rejected event still closes histogram centrals; only full-event
    # exposure/counter custody makes that illicit thinning visible.
    changed = copy.deepcopy(a); changed['uncertainty']['groups'].pop(3); changed['normalization_event_weights'].pop(3)
    save_acquired(c, changed, tmp_path)
    with pytest.raises(g.GroupNormalizationError, match='population'): g.normalize(c, changed)
    assert original['counter_diagnostics']['nominal']['entries'] == 5


def test_exact_finite_slice_order_units_width_and_cross_correlations(records):
    r = g.normalize(*records)
    selected = [{'weight': 'nominal', 'component': c, 'bin': b} for c, b in [('denominator', '1'), ('numerator', '0'), ('numerator', '1')]]
    s = g.finite_slice(r, selected, representation='differential')
    assert s['projection_indices'] == [6, 1, 2] and s['coordinate_scales'] == [.5, 1., .5]
    assert s['units'] == ['fb/GeV']*3
    assert s['values'] == [r['values'][6]/2, r['values'][1], r['values'][2]/2]
    assert s['covariance'][0][1] == r['output_covariance'][6][1]/2
    assert np.array_equal(s['covariance'], np.asarray(s['covariance']).T)
    assert s['experimental_independence'] is None
    F = Fraction.from_float; bound = F(s['covariance_maximum_entry_forward_error_bound'])
    for a, i in enumerate(s['projection_indices']):
        for b, j in enumerate(s['projection_indices']):
            # This checks the retained normalized covariance part of the
            # enclosure; the full original-group enclosure is separate above.
            exact = F(r['output_covariance'][i][j])*F(s['coordinate_scales'][a])*F(s['coordinate_scales'][b])
            assert abs(F(s['covariance'][a][b])-exact) <= bound


def test_finite_slice_central_overflow_even_zero_covariance_refuses(records):
    r = g.normalize(*records)
    # Held-out accessor counterexample: the source result would need separate
    # pinning/admission; this pure synthetic mutation isolates the numeric guard.
    r['components'][0]['quantity']['bins'][0]['high'] = 1e-250
    r['values'][1] = 1e100
    for row in r['output_covariance']: row[1] = 0.
    r['output_covariance'][1] = [0.]*len(r['values'])
    with pytest.raises(g.GroupNormalizationError, match='finite numeric'):
        g.finite_slice(r, [{'weight': 'nominal', 'component': 'numerator', 'bin': '0'}], representation='differential')


@pytest.mark.parametrize('selection', [[], [{'weight': 'nominal', 'component': 'numerator', 'bin': 'underflow'}],
    [{'weight': 'nominal', 'component': 'numerator', 'bin': '0'}]*2,
    [{'weight': 'nominal', 'component': 'numerator', 'bin': '0'}, {'weight': 'closure-up', 'component': 'numerator', 'bin': '0'}],
    [{'weight': 'nominal', 'component': 'missing', 'bin': '0'}]])
def test_slice_population_refusals(records, selection):
    with pytest.raises(g.GroupNormalizationError): g.finite_slice(g.normalize(*records), selection)


@pytest.mark.parametrize('fault', ['counter_missing', 'group_missing', 'duplicate_group', 'group_order', 'truncated_hist',
    'weight_missing', 'extra_weight', 'counter_W', 'counter_Q', 'counter_entries', 'central', 'missing_flow', 'edges', 'axis',
    'inferred_marginal', 'cap', 'group_rule', 'nonfinite', 'unbound_source'])
def test_resealed_adverse_acquisition_population_and_moments(records, tmp_path, fault):
    c, a = records
    if fault == 'counter_missing': a['normalization_event_weights'].pop()
    elif fault == 'group_missing': a['uncertainty']['groups'].pop()
    elif fault == 'duplicate_group': a['uncertainty']['groups'][1]['id'] = a['uncertainty']['groups'][0]['id']
    elif fault == 'group_order': a['normalization_event_weights'].reverse()
    elif fault == 'truncated_hist': a['uncertainty']['groups'][0]['values'].pop()
    elif fault == 'weight_missing': a['normalization_event_weights'][0]['weights'].pop('closure-up')
    elif fault == 'extra_weight': a['normalization_event_weights'][0]['weights']['extra'] = 1
    elif fault == 'counter_W': a['normalization_counter_by_weight']['nominal']['sumw'] += 1
    elif fault == 'counter_Q': a['normalization_counter_by_weight']['nominal']['sumw2'] += 1
    elif fault == 'counter_entries': a['normalization_counter_by_weight']['nominal']['entries'] -= 1
    elif fault == 'central': a['values'][0] += 1
    elif fault == 'missing_flow': a['basis'].pop()
    elif fault == 'edges': a['basis'][1]['high'] = .9
    elif fault == 'axis': a['basis'][0]['axis_unit'] = 'TeV'
    elif fault == 'inferred_marginal': a['native_marginal_covariance_inferred'] = True
    elif fault == 'cap': a['native_weight_cap'] = 5
    elif fault == 'group_rule': a['group_rule'] = 'collapse_by_event_number'
    elif fault == 'nonfinite': a['uncertainty']['groups'][0]['values'][0] = 'NaN'
    elif fault == 'unbound_source': c['components'][0]['definition']['text'] += '\nchanged'
    save_acquired(c, a, tmp_path)  # hashes repaired; inspect semantic consistency
    with pytest.raises(g.GroupNormalizationError): g.normalize(c, a)


def test_nonnegative_policy_refuses_signed_groups(records):
    c, a = records; c['weights'][0]['weight_policy'] = 'nonnegative'
    with pytest.raises(g.GroupNormalizationError, match='signed'): g.normalize(c, a)


def test_zero_and_negative_total_denominator_no_clipping(records, tmp_path):
    c, a = records
    for desired, admitted in [(0., False), (-1., False)]:
        changed = copy.deepcopy(a)
        last = changed['normalization_event_weights'][-1]['weights']['nominal']
        changed['normalization_event_weights'][-1]['weights']['nominal'] = last+desired-4.
        ws = [e['weights']['nominal'] for e in changed['normalization_event_weights']]
        changed['normalization_counter_by_weight']['nominal'].update(sumw=math.fsum(ws), sumw2=math.fsum(w*w for w in ws))
        save_original(c, changed, tmp_path); save_acquired(c, changed, tmp_path)
        with pytest.raises(g.GroupNormalizationError, match='denominator'): g.normalize(c, changed)
    for component in c['components']: component['denominator_policy'] = 'nonzero_signed'
    r = g.normalize(c, changed)
    assert r['counter_diagnostics']['nominal']['sumw'] == -1. and any(v < 0 for v in r['values'])
    assert not r['physics_validated']


def test_source_and_contract_hash_no_overwrite(records, tmp_path):
    c, a = records; p = tmp_path/'contract.json'; p.write_text(json.dumps(c)); expected = pin(p, 'contract')['sha256']
    assert g.derive_from_file(p, expected_sha256=expected)['values'] == g.normalize(c, a)['values']
    with pytest.raises(g.GroupNormalizationError): g.derive_from_file(p, expected_sha256='0'*64)
    (tmp_path/'acquired.json').write_text(json.dumps(a)+' ')
    with pytest.raises(g.GroupNormalizationError, match='size'): g.normalize(c, a)


def test_counter_too_small_for_finite_transform_refuses(records, tmp_path):
    c, a = records
    for e in a['normalization_event_weights']: e['weights']['nominal'] = 1e-320
    for row in a['uncertainty']['groups']:
        row['values'][:8] = [1e-320 if v else 0. for v in row['values'][:8]]
    a['values'] = [math.fsum(row['values'][i] for row in a['uncertainty']['groups']) for i in range(16)]
    a['normalization_counter_by_weight']['nominal'].update(sumw=5e-320, sumw2=0.)
    save_original(c, a, tmp_path); save_acquired(c, a, tmp_path)
    with pytest.raises(g.GroupNormalizationError, match='overflows'): g.normalize(c, a)


@pytest.mark.parametrize('sign', [1., -1.])
def test_unrepresentable_factor_refuses_even_representable_final_central(records, tmp_path, sign):
    c, a = records
    minimum = math.ulp(0.)
    for component in c['components']:
        component['fixed_coefficients']['nominal']['value'] = minimum
        if sign < 0: component['denominator_policy'] = 'nonzero_signed'
    if sign < 0:
        for event in a['normalization_event_weights']: event['weights']['nominal'] *= -1.
        for group in a['uncertainty']['groups']:
            group['values'][:8] = [-v for v in group['values'][:8]]
        a['normalization_counter_by_weight']['nominal']['sumw'] *= -1.
        a['values'] = [math.fsum(row['values'][i] for row in a['uncertainty']['groups']) for i in range(16)]
        save_original(c, a, tmp_path); save_acquired(c, a, tmp_path)
    N, W = a['values'][1], a['normalization_counter_by_weight']['nominal']['sumw']
    assert float(Fraction(minimum)*Fraction(N)/Fraction(W)) == minimum
    assert minimum/W == 0.  # the required nonzero derivative was lost
    with pytest.raises(g.GroupNormalizationError, match='factor/derivative underflows'):
        g.normalize(c, a)


@pytest.mark.parametrize('case', ['central', 'counter_derivative'])
def test_nonzero_central_and_counter_derivative_underflow_refuse(records, tmp_path, case):
    c, a = records; minimum = math.ulp(0.)
    for component in c['components']: component['fixed_coefficients']['nominal']['value'] = 4*minimum
    for group in a['uncertainty']['groups']: group['values'][:8] = [0.]*8
    N = .25 if case == 'central' else 1.
    a['uncertainty']['groups'][0]['values'][0] = N
    a['values'] = [math.fsum(row['values'][i] for row in a['uncertainty']['groups']) for i in range(16)]
    save_acquired(c, a, tmp_path)
    assert (4*minimum)/4 == minimum  # the factor is representable
    if case == 'central':
        assert Fraction(4*minimum)*Fraction(N)/4 != 0 and minimum*N == 0.
        message = 'normalized central underflows'
    else:
        assert minimum*N == minimum and -minimum/4 == 0.
        message = 'counter derivative underflows'
    with pytest.raises(g.GroupNormalizationError, match=message): g.normalize(c, a)


@pytest.mark.parametrize('sign', [1., -1.])
def test_representable_subnormal_values_derivatives_and_exact_group_cancellation(records, tmp_path, sign):
    c, a = records; minimum = math.ulp(0.)
    for component in c['components']:
        component['fixed_coefficients']['nominal']['value'] = minimum
        if sign < 0: component['denominator_policy'] = 'nonzero_signed'
    for index, event in enumerate(a['normalization_event_weights']):
        event['weights']['nominal'] = sign if index == 0 else 0.
    for index, group in enumerate(a['uncertainty']['groups']):
        group['values'][:8] = [0.]*8
        if index == 0: group['values'][0] = group['values'][4] = sign
    a['normalization_counter_by_weight']['nominal'].update(sumw=sign, sumw2=1.)
    a['values'] = [math.fsum(row['values'][i] for row in a['uncertainty']['groups']) for i in range(16)]
    save_original(c, a, tmp_path); save_acquired(c, a, tmp_path)
    r = g.normalize(c, a); counter = r['counter_diagnostics']['nominal']['scalar_coordinate']
    for index in (0, 4):
        assert r['values'][index] == minimum
        assert r['jacobian'][index][index] == sign*minimum
        assert r['jacobian'][index][counter] == -sign*minimum
        assert all(row['vector'][index] == 0. for row in r['linearized_group_vectors'])
        assert all(v == 0. for v in r['output_covariance'][index])
    assert not r['native_acquisition_qualified'] and not r['physics_validated']


def test_exact_zero_central_and_covariance_product_underflow_keep_distinct_policies(records, tmp_path):
    c, a = records; minimum = math.ulp(0.)
    for component in c['components']: component['fixed_coefficients']['nominal']['value'] = 4*minimum
    for group in a['uncertainty']['groups']: group['values'][:8] = [0.]*8
    a['uncertainty']['groups'][0]['values'][0] = 1.
    a['uncertainty']['groups'][1]['values'][0] = -1.
    a['values'] = [math.fsum(row['values'][i] for row in a['uncertainty']['groups']) for i in range(16)]
    save_acquired(c, a, tmp_path); r = g.normalize(c, a)
    assert r['values'][0] == 0. and r['jacobian'][0][0] == minimum
    assert r['jacobian'][0][r['counter_diagnostics']['nominal']['scalar_coordinate']] == 0.
    assert r['output_covariance'][0][0] == 0.  # two nonzero phi squares underflow
    assert Fraction(2)*Fraction(minimum)**2 <= Fraction(r['covariance_maximum_entry_forward_error_bound'])


def test_finite_slice_nonzero_central_underflow_refuses_even_zero_covariance(records):
    r = g.normalize(*records)
    # Held-out accessor witness, with a finite width and zero supplied C.
    r['components'][0]['quantity']['bins'][0]['high'] = 1e308
    r['values'][1] = 1e-100
    r['output_covariance'][1][1] = 0.
    r['covariance_maximum_entry_forward_error_bound'] = 0.
    basis = [r['output_basis'][1]]
    with pytest.raises(g.GroupNormalizationError, match='finite-slice central underflows'):
        g.finite_slice(r, basis, representation='differential')
    r['values'][1] = 0.
    assert g.finite_slice(r, basis, representation='differential')['values'] == [0.]


def test_boolean_schema_and_weight_cap_not_numeric_admission(records, tmp_path):
    c, a = records; a['native_weight_cap'] = False
    save_acquired(c, a, tmp_path)
    with pytest.raises(g.GroupNormalizationError, match='weight cap'): g.normalize(c, a)


def test_original_population_refuses_resealed_thinned_acquired_record(records, tmp_path):
    c, a = records
    a['uncertainty']['groups'].pop(3); a['normalization_event_weights'].pop(3); a['source_file_encounter_groups'] = 4
    for w, counter in a['normalization_counter_by_weight'].items():
        ws = [e['weights'][w] for e in a['normalization_event_weights']]
        counter.update(sumw=math.fsum(ws), sumw2=math.fsum(v*v for v in ws), entries=4)
    save_acquired(c, a, tmp_path)  # internal sums/census resealed; original is intact
    with pytest.raises(g.GroupNormalizationError, match='original full event population'): g.normalize(c, a)


def test_joint_normalization_to_existing_derived_ratio_chain(records, tmp_path):
    from ravel.physics import derived_quantities as d
    c, a = records; r = g.normalize(c, a); j = g.derived_joint(r)
    jp = tmp_path/'normalized-joint.json'; jp.write_text(json.dumps(j)); sources = c['sources']+[pin(jp, 'joint')]
    dc = {'schema_version': 1, 'kind': 'derived-quantity-contract', 'analysis_id': c['analysis_id'],
          'sources': sources, 'joint_source': 'joint',
          'weights': [{'id': w['id'], 'nuisance': None if w['id'] == 'nominal' else 'closure',
                       'direction': 'nominal' if w['id'] == 'nominal' else 'up', 'source': 'acquired'} for w in c['weights']],
          'components': [{'id': x['id'], 'path': '/normalized/'+x['id'], 'quantity': x['quantity'],
                          'scale': {w['id']: 1. for w in c['weights']}, 'definition': x['definition']} for x in c['components']],
          'outputs': [{'id': 'ratio', 'path': '/ratio',
                       'quantity': {**c['components'][0]['quantity'], 'unit': '1'}, 'operation': 'ratio',
                       'left': {'terms': [{'component': 'numerator', 'coefficient': 1.}], 'offset': [0., 0.]},
                       'right': {'terms': [{'component': 'denominator', 'coefficient': 1.}], 'offset': [0., 0.]},
                       'denominator_policy': 'positive', 'definition': c['components'][0]['definition'], 'subset_evidence': None}],
          'output_census': [{'path': '/normalized/'+x, 'kind': 'component', 'visibility': 'internal'} for x in ['numerator', 'denominator']]+[
              {'path': '/ratio', 'kind': 'derived', 'visibility': 'public'}],
          'flow_policy': 'retain_inputs_not_derived',
          'exposure': {w: {'groups': 5, 'sumw': a['normalization_counter_by_weight'][w]['sumw'],
                           'sumw2': a['normalization_counter_by_weight'][w]['sumw2'],
                           'normalization': 'already propagated N/W; component scales are identity', 'source': 'acquired', 'weight_policy': 'signed'}
                       for w in ['nominal', 'closure-up']}, 'unsupported_transforms': []}
    out = d.derive(dc, j)
    # Independently differentiate raw N/D; normalization counter must cancel.
    raw = np.asarray(r['input_values']); V = np.asarray([v['vector'] for v in r['input_groups']]); rows = []
    for w in [0, 8]:
        for b in [1, 2]:
            row = np.zeros(len(raw)); row[w+b] = 1/raw[w+b+4]; row[w+b+4] = -(raw[w+b]/raw[w+b+4])/raw[w+b+4]; rows.append(row)
    oracle = np.asarray(rows); expected = (oracle@V.T)@(V@oracle.T)
    assert np.max(np.abs(np.asarray(out['output_covariance'])-expected)) < 2e-14
    chain = np.asarray(out['jacobian'])@np.asarray(r['jacobian'])
    assert np.max(np.abs(chain[:, -2:])) < 2e-15
    assert np.max(np.abs(chain-oracle)) < 2e-15
    assert out['native_finalized_separate'] is None and out['inference'] is None


