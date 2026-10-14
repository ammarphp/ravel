"""Small no-refit provenance, phase-budget and numerical guard controls."""
from copy import deepcopy
import math
from pathlib import Path

import pytest

from ravel.validation import likelihood_candidate_check as check
from ravel.validation import likelihood_parity as parity
from ravel.validation import likelihood_profile_probe as profile
from diagnostic_plan_fixture import TOLERANCES, CANDIDATE_LIMITS, CANDIDATE_PLAN


def portfolio():
    starts = [[.01 * (seed + 1)] * 6 for seed in range(3)]
    for seed in starts:
        seed[1] = seed[2] = 1.
    probe = {'bounds': [[-5., 5.]] * 6, 'fixed_coordinates': [[1, 1.], [2, 1.]],
             'ordered_starts': starts}
    compiled = {'model_compact_sha256': 'model', 'data_compact_sha256': 'data'}
    identity = {'model_sha256': 'model', 'data_sha256': 'data', **probe}
    children = {}
    for backend in ('numpy', 'jax'):
        trials = []
        for i, seed in enumerate(starts):
            row = {'seed_index': i, 'seed': seed, 'status': 'succeeded',
                   'result': {'parameters': seed, 'objective': 1. + i, 'success': True}}
            if backend == 'numpy' and i == 2:
                row.pop('result')
                row['status'] = 'interrupted'
            trials.append(row)
        children[backend] = {'backend': backend, 'compiled_identity': identity,
                             'seed_denominator': 3, 'trials': trials}
    children['jax']['best'] = children['jax']['trials'][0]['result']
    return children, probe, compiled


def test_exact_retained_completed_set_keeps_missing_scalar_start():
    children, probe, compiled = portfolio()
    rows = check.select_candidates(children, probe, compiled, CANDIDATE_PLAN)
    assert [(x['backend'], x['seed_index']) for x in rows] == [tuple(x) for x in CANDIDATE_PLAN['candidate_selectors']]
    assert len(rows) == 5
    assert children['numpy']['trials'][2]['status'] == 'interrupted'


@pytest.mark.parametrize('change', ['start', 'model', 'fixed', 'bounds', 'status', 'selected', 'nan', 'missing'])
def test_candidate_identity_and_census_refuse_semantic_drift(change):
    children, probe, compiled = deepcopy(portfolio())
    if change == 'start':
        children['numpy']['trials'][0]['seed'] = [0.] * 6
    elif change == 'model':
        children['jax']['compiled_identity'] = {**children['jax']['compiled_identity'], 'model_sha256': 'other'}
    elif change == 'fixed':
        children['numpy']['trials'][0]['result']['parameters'] = [.02] * 6
    elif change == 'bounds':
        children['numpy']['trials'][0]['result']['parameters'] = [6.] * 6
    elif change == 'status':
        children['numpy']['trials'][2]['status'] = 'succeeded'
    elif change == 'selected':
        children['jax']['best'] = children['jax']['trials'][1]['result']
    elif change == 'nan':
        children['jax']['trials'][0]['result']['objective'] = math.nan
    else:
        children['jax']['trials'].pop()
    with pytest.raises(ValueError):
        check.select_candidates(children, probe, compiled, CANDIDATE_PLAN)


def test_origin_receipt_associates_exact_path_and_hash(tmp_path):
    path = tmp_path / 'child.json'
    pin = {'path': str(path), 'sha256': 'good'}
    snapshot = {str(tmp_path): {'kind': 'directory', 'files': [{'name': 'child.json', 'sha256': 'good'}]}}
    check._snapshot_pin(snapshot, pin)
    for wrong in ({'path': str(tmp_path / 'other.json'), 'sha256': 'good'}, {'path': str(path), 'sha256': 'wrong'}):
        with pytest.raises(ValueError):
            check._snapshot_pin(snapshot, wrong)


def test_reserved_phase_and_total_call_budgets_are_independent():
    now = [0.]
    counter = check.Counter({**CANDIDATE_LIMITS, 'numerical_seconds':90,'evaluator_calls': 2}, clock=lambda: now[0])
    counter.begin('numpy', 60)
    counter.check('scalar')
    now[0] = 59.
    counter.check('scalar')
    with pytest.raises(check.CheckBudget, match='ceiling'):
        counter.check('jax')
    now[0] = 60.
    with pytest.raises(check.CheckBudget, match='phase'):
        counter.check()
    counter.begin('jax', 30)
    now[0] = 90.
    with pytest.raises(check.CheckBudget, match='phase'):
        counter.check()
    assert counter.snapshot()['calls'] == 2


def test_all_free_h_h2_census_excludes_only_original_two_fixed_coordinates():
    children, probe, compiled = portfolio()
    candidates = check.select_candidates(children, probe, compiled, CANDIDATE_PLAN)
    calls = [0]
    def scalar(point):
        calls[0] += 1
        return math.fsum(x*x for x in point)
    for candidate in candidates:
        rows = parity.finite_difference(scalar, candidate['parameters'], probe['bounds'], probe['fixed_coordinates'])
        assert [r['index'] for r in rows if r['rule'] == 'fixed'] == [1, 2]
        assert len(rows) == 6
        assert parity.compare_gradients(rows, [2*x for x in candidate['parameters']])['passed']
    assert calls[0] == 80
    assert calls[0] + 6 * 3 == 98 < CANDIDATE_LIMITS['evaluator_calls']


def row():
    return {'independent_twice_nll': 10., 'recorded_twice_nll': 10., 'numpy_twice_nll': 10.,
            'jax_twice_nll': 10., 'gradient_parity': {'passed': True},
            'step_convergence_passed': True, 'fd_projected_gradient': 1e-5,
            'analytic_projected_gradient': 1e-5}


def test_arithmetic_agreement_is_not_stationarity_or_reference_quality():
    bad = row()
    bad['fd_projected_gradient'] = .01
    check.qualify(bad, 10., TOLERANCES)
    assert bad['arithmetic_passed'] and not bad['candidate_checks_passed']
    bad = row()
    check.qualify(bad, 9., TOLERANCES)
    assert bad['arithmetic_passed'] and bad['stationary'] and not bad['reference_quality_passed']
    good = row()
    check.qualify(good, 11., TOLERANCES)
    assert good['candidate_checks_passed'] and good['best_minus_reference'] == -1.


@pytest.mark.parametrize('field', ['recorded_twice_nll', 'numpy_twice_nll', 'jax_twice_nll'])
def test_each_density_identity_is_required(field):
    bad = row()
    bad[field] += 2 * TOLERANCES['independent_density']
    check.qualify(bad, 10., TOLERANCES)
    assert not bad['arithmetic_passed']


def test_h_h2_convergence_and_analytic_agreement_are_separate_obligations():
    bad = row()
    bad['step_convergence_passed'] = False
    check.qualify(bad, 10., TOLERANCES)
    assert not bad['candidate_checks_passed']
    bad = row()
    bad['gradient_parity']['passed'] = False
    check.qualify(bad, 10., TOLERANCES)
    assert not bad['candidate_checks_passed']
