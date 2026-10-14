"""Shared coupling-polynomial core: bases from coupling orders, SVD solve, covariance, held-out checks."""
import json

import numpy as np
import pytest

from ravel.physics import coupling_polynomial as cp
from ravel.physics.inference import coupling_morphing, morphing


def test_basis_from_amplitude_terms_includes_mixed_interference_degrees():
    # Amplitude = SM (no coupling) + g1 * g2 (one new-physics diagram).
    basis = cp.basis_from_amplitudes(['g1', 'g2'], [{}, {'g1': 1, 'g2': 1}])
    assert basis == [(0, 0), (1, 1), (2, 2)]
    # Two new-physics diagrams without SM: g1^2, g1 g2, g2^2 (all degree 2).
    assert cp.basis_from_amplitudes(['g1', 'g2'], [{'g1': 1}, {'g2': 1}]) == [(0, 2), (1, 1), (2, 0)]


def test_basis_of_total_degree():
    assert cp.basis_of_degree(['a', 'b'], 2, homogeneous=True) == [(0, 2), (1, 1), (2, 0)]
    assert len(cp.basis_of_degree(['a', 'b'], 2, homogeneous=False)) == 6


def test_declared_basis_must_match_declared_coupling_orders():
    with pytest.raises(ValueError, match='degree'):
        cp.check_basis(['g'], [(2,), (4,)], amplitudes=[{}, {'g': 1}])
    cp.check_basis(['g'], [(0,), (1,), (2,)], amplitudes=[{}, {'g': 1}])
    with pytest.raises(ValueError, match='degree'):
        cp.check_basis(['a', 'b'], [(2, 0), (1, 1), (0, 3)], degree={'total': 2, 'homogeneous': True})


def test_analytic_polynomial_is_recovered_exactly_with_condition_number():
    basis = [(2, 0), (1, 1), (0, 2)]
    points = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    truth = np.array([2.0, -0.5, 0.25])
    A = cp.design(points, basis)
    solution = cp.solve(A, (A @ truth)[:, None], rcond=1e-12)
    assert solution['rank'] == 3
    assert np.allclose(solution['coefficients'][:, 0], truth)
    assert solution['condition'] == pytest.approx(np.linalg.cond(A))
    assert solution['equilibrated_condition'] >= 1


def test_rank_deficient_design_reports_rank_and_no_coefficients():
    A = cp.design(np.array([[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]), [(1, 0), (0, 1)])
    solution = cp.solve(A, np.ones((3, 1)), rcond=1e-10)
    assert solution['rank'] == 1 and solution['coefficients'] is None


def test_weighted_per_bin_toy_fit_has_unit_pull_width():
    rng = np.random.default_rng(11)
    basis = [(2,), (4,)]
    points = np.linspace(0.5, 2.0, 8)[:, None]
    truth = np.array([[1.0, 3.0], [0.2, -0.1]])  # monomials x bins
    A = cp.design(points, basis)
    sigma = np.full((8, 2), 0.05)
    pulls = []
    for _ in range(200):
        Y = A @ truth + rng.normal(0, 0.05, size=(8, 2))
        solution = cp.solve(A, Y, rcond=1e-12, sigma=sigma)
        cov = solution['covariance']
        pulls.append((solution['coefficients'] - truth) / np.sqrt(np.stack([np.diag(c) for c in cov], axis=1)))
    pulls = np.array(pulls)
    assert abs(pulls.mean()) < 0.1 and 0.85 < pulls.std() < 1.15


def test_held_out_comparison_uses_combined_mc_error():
    check = cp.held_out(predicted=[10.0], prediction_variance=[0.09], observed=[10.4], uncertainty=[0.4],
                        tolerance_sigma=1.0)
    assert check['pulls'][0] == pytest.approx(-0.8) and check['passed'] is True
    check = cp.held_out(predicted=[10.0], prediction_variance=[0.0], observed=[11.0], uncertainty=[0.4],
                        tolerance_sigma=1.0)
    assert check['passed'] is False


def test_covariance_propagation_is_symmetric_and_exact_for_simple_maps():
    M = np.array([[1.0, 2.0], [0.0, 1.0]])
    C = np.array([[1.0, 0.5], [0.5, 2.0]])
    matrix, diagnostics = cp.propagate_covariance(M, C, 'test covariance')
    assert np.allclose(matrix, M @ C @ M.T) and np.array_equal(matrix, matrix.T)
    assert 'arithmetic' in diagnostics


def test_sfitter_extractor_is_a_client_of_the_shared_core():
    from ravel.physics import sfitter_scan_extraction as sfitter
    assert sfitter._covariance is cp.propagate_covariance
    import inspect
    assert 'cp.svd_extraction' in inspect.getsource(sfitter._calculate)


# --------------------------------------------------------------------- mode-level requirements

def _save(path, doc):
    path.write_text(json.dumps(doc))
    return path


def _mode_doc(**changes):
    doc = {'schema_version': 1, 'kind': 'coupling-morphing',
           'parameters': [{'name': 'g', 'unit': '', 'label': 'Coupling'}],
           'quantity': {'name': 'xsec', 'unit': 'pb', 'label': 'Cross section'},
           'basis': [{'g': 2}, {'g': 4}], 'method': 'exact', 'max_condition': 1e6,
           'runs': [{'id': 'a', 'point': {'g': 1.0}, 'value': 1.2, 'uncertainty': 0.01},
                    {'id': 'b', 'point': {'g': 2.0}, 'value': 4.0 + 3.2, 'uncertainty': 0.02}],
           'holdout': [{'id': 'h', 'point': {'g': 1.5}, 'value': 2.25 + 0.2 * 5.0625, 'uncertainty': 0.02}],
           'closure_tolerance_sigma': 3,
           'width': {'treatment': 'fixed', 'value': 1.5, 'unit': 'GeV', 'source': 'requester: width held fixed'}}
    doc.update(changes)
    return {k: v for k, v in doc.items() if v is not None}


def _run(tmp_path, doc):
    path = _save(tmp_path / 'morph.json', doc)
    return coupling_morphing.run({'input': str(path)}, tmp_path, tmp_path / 'out')


def test_mode_requires_a_width_declaration(tmp_path):
    with pytest.raises(ValueError, match='width'):
        _run(tmp_path, _mode_doc(width=None))
    with pytest.raises(ValueError, match='width'):
        _run(tmp_path, _mode_doc(width={'treatment': 'fixed', 'value': 1.0}))


def test_mode_requires_a_held_out_point(tmp_path):
    with pytest.raises(ValueError, match='held-out'):
        _run(tmp_path, _mode_doc(holdout=None))


def test_passing_closure_marks_the_morph_usable(tmp_path):
    result = _run(tmp_path, _mode_doc())
    assert result['status'] == 'passed'
    morph = json.loads((tmp_path / 'out/coupling-morph.json').read_text())
    assert morph['usable'] is True and morph['width']['treatment'] == 'fixed'
    assert morphing.Morph.from_document(morph, require_usable=True).bins == 1


def test_non_polynomial_dependence_is_refused_by_the_held_out_check(tmp_path):
    # theta'-like dependence: y = g^2 / (1 + 0.5 g^2) is not in span{g^2, g^4}.
    f = lambda g: g * g / (1 + 0.5 * g * g)
    doc = _mode_doc(runs=[{'id': 'a', 'point': {'g': 1.0}, 'value': f(1.0), 'uncertainty': 1e-3},
                          {'id': 'b', 'point': {'g': 2.0}, 'value': f(2.0), 'uncertainty': 1e-3}],
                    holdout=[{'id': 'h', 'point': {'g': 1.5}, 'value': f(1.5), 'uncertainty': 1e-3}])
    result = _run(tmp_path, doc)
    assert result['status'] == 'failed'
    morph = json.loads((tmp_path / 'out/coupling-morph.json').read_text())
    assert morph['usable'] is False
    with pytest.raises(ValueError, match='held-out'):
        morphing.Morph.from_document(morph, require_usable=True)


def test_degree_mismatch_between_basis_and_coupling_orders_is_refused(tmp_path):
    with pytest.raises(ValueError, match='degree'):
        _run(tmp_path, _mode_doc(amplitudes=[{}, {'g': 1}]))


def test_basis_can_be_derived_from_amplitude_coupling_orders(tmp_path):
    doc = _mode_doc(basis=None, amplitudes=[{'g': 1}, {'g': 2}])  # |g + c g^2|^2 -> g^2, g^3, g^4
    f = lambda g: 1.0 * g ** 2 + 0.3 * g ** 3 + 0.2 * g ** 4
    doc['runs'] = [{'id': f'r{i}', 'point': {'g': g}, 'value': f(g), 'uncertainty': 0.01}
                   for i, g in enumerate((0.5, 1.0, 2.0))]
    doc['holdout'] = [{'id': 'h', 'point': {'g': 1.5}, 'value': f(1.5), 'uncertainty': 0.01}]
    assert _run(tmp_path, doc)['status'] == 'passed'
    morph = json.loads((tmp_path / 'out/coupling-morph.json').read_text())
    assert morph['monomial_labels'] == ['g^2', 'g^3', 'g^4']


def test_morphed_width_is_fitted_with_the_same_core(tmp_path):
    width = {'treatment': 'morphed', 'unit': 'GeV', 'basis': [{'g': 2}],
             'runs': [{'id': 'wa', 'point': {'g': 1.0}, 'value': 0.1, 'uncertainty': 0.001}],
             'holdout': [{'id': 'wh', 'point': {'g': 2.0}, 'value': 0.4, 'uncertainty': 0.004}]}
    assert _run(tmp_path, _mode_doc(width=width))['status'] == 'passed'
    morph = json.loads((tmp_path / 'out/coupling-morph.json').read_text())
    assert morph['width']['treatment'] == 'morphed'
    assert morph['width']['fit']['coefficients'][0][0] == pytest.approx(0.1)
    assert morph['width']['fit']['closure'][0]['passed'] is True
