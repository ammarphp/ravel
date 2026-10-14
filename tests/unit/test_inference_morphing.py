"""Coupling-polynomial morphing: exact solve, weighted fit, conditioning, closure, propagation."""
import numpy as np
import pytest

from ravel.physics.inference import morphing

BASIS = [{'a': 2}, {'a': 1, 'b': 1}, {'b': 2}]


def quadratic(a, b, coefficients=(2.0, -0.5, 0.25)):
    return coefficients[0] * a * a + coefficients[1] * a * b + coefficients[2] * b * b


def runs(points, sigma=0.0):
    return [{'id': f'r{i}', 'point': {'a': a, 'b': b}, 'value': quadratic(a, b),
             **({'uncertainty': sigma} if sigma else {})} for i, (a, b) in enumerate(points)]


def test_exact_recovery_of_a_synthetic_quadratic():
    fit = morphing.fit({'parameters': ['a', 'b'], 'basis': BASIS, 'method': 'exact', 'max_condition': 1e6,
                        'runs': runs([(1, 0), (0, 1), (1, 1)])})
    assert np.allclose(fit.coefficients[:, 0], [2.0, -0.5, 0.25])
    assert fit.condition_number < 10
    assert fit.predict({'a': np.array([0.3]), 'b': np.array([-2.0])})[0][0] == pytest.approx(quadratic(0.3, -2.0))


def test_weighted_fit_reports_covariance_and_chi2():
    rng = np.random.default_rng(3)
    points = [(1, 0), (0, 1), (1, 1), (2, 1), (1, 2), (0.5, 1.5)]
    data = runs(points, sigma=0.01)
    for row in data:
        row['value'] += rng.normal(0, 0.01)
    fit = morphing.fit({'parameters': ['a', 'b'], 'basis': BASIS, 'method': 'weighted-least-squares',
                        'max_condition': 1e6, 'runs': data})
    assert np.allclose(fit.coefficients[:, 0], [2.0, -0.5, 0.25], atol=0.05)
    assert fit.covariance.shape == (1, 3, 3) and np.all(np.diag(fit.covariance[0]) > 0)
    assert fit.ndf == 3 and fit.chi2[0] >= 0
    # Exact solve with uncertainties propagates A^-1 diag(sigma^2) A^-T.
    exact = morphing.fit({'parameters': ['a', 'b'], 'basis': BASIS, 'method': 'exact', 'max_condition': 1e6,
                          'runs': runs([(1, 0), (0, 1), (1, 1)], sigma=0.1)})
    A = np.array([[1, 0, 0], [0, 0, 1], [1, 1, 1]], float)
    inv = np.linalg.inv(A)
    assert np.allclose(exact.covariance[0], inv @ np.diag([0.01] * 3) @ inv.T)


def test_ill_conditioned_or_rank_deficient_sets_are_refused():
    with pytest.raises(ValueError, match='condition'):
        morphing.fit({'parameters': ['a', 'b'], 'basis': BASIS, 'method': 'exact', 'max_condition': 1e3,
                      'runs': runs([(1, 1), (1, 1.0001), (1, 0.9999)])})
    with pytest.raises(ValueError, match='at least'):
        morphing.fit({'parameters': ['a', 'b'], 'basis': BASIS, 'method': 'exact', 'max_condition': 1e6,
                      'runs': runs([(1, 0), (0, 1)])})
    with pytest.raises(ValueError, match='exactly'):
        morphing.fit({'parameters': ['a', 'b'], 'basis': BASIS, 'method': 'exact', 'max_condition': 1e6,
                      'runs': runs([(1, 0), (0, 1), (1, 1), (2, 1)])})


def test_closure_flags_a_held_out_point():
    spec = {'parameters': ['a', 'b'], 'basis': BASIS, 'method': 'exact', 'max_condition': 1e6,
            'runs': runs([(1, 0), (0, 1), (1, 1)], sigma=0.01),
            'holdout': [{'id': 'h', 'point': {'a': 2, 'b': -1}, 'value': quadratic(2, -1), 'uncertainty': 0.01}],
            'closure_tolerance_sigma': 3}
    good = morphing.fit(spec)
    assert good.closure[0]['passed'] is True and abs(good.closure[0]['pulls'][0]) < 1e-6
    spec['holdout'][0]['value'] += 1.0
    bad = morphing.fit(spec)
    assert bad.closure[0]['passed'] is False
    with pytest.raises(ValueError, match='tolerance'):
        morphing.fit({**spec, 'closure_tolerance_sigma': None})


def test_per_bin_templates_and_g_power_scaling():
    # One template at g0, basis {g^4}: s(g) = s0 * (g/g0)^4 in every bin.
    template = [4.0, 2.0, 0.5]
    fit = morphing.fit({'parameters': ['g'], 'basis': [{'g': 4}], 'method': 'exact', 'max_condition': 10,
                        'runs': [{'id': 't', 'point': {'g': 0.5}, 'values': template,
                                  'uncertainties': [0.4, 0.2, 0.05]}]})
    predicted, variance = fit.predict({'g': np.array([1.0, 0.25])}, with_variance=True)
    assert np.allclose(predicted[:, 0], np.array(template) * 16)
    assert np.allclose(predicted[:, 1], np.array(template) / 16)
    assert np.allclose(np.sqrt(variance[:, 0]), np.array([0.4, 0.2, 0.05]) * 16)


def test_document_round_trip_preserves_coefficients():
    fit = morphing.fit({'parameters': ['a', 'b'], 'basis': BASIS, 'method': 'exact', 'max_condition': 1e6,
                        'runs': runs([(1, 0), (0, 1), (1, 1)])})
    doc = fit.document()
    again = morphing.Morph.from_document(doc)
    assert np.allclose(again.coefficients, fit.coefficients)
    assert again.monomials(dict(a=np.array(2.0), b=np.array(3.0))).tolist() == [4.0, 6.0, 9.0]
