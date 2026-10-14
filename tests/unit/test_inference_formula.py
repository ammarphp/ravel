"""Declared-formula evaluator: restricted syntax, ordered definitions, grids and units."""
import math

import numpy as np
import pytest

from ravel.physics.inference import formula


def test_arithmetic_functions_and_constants_are_vectorised():
    program = formula.Program({
        'constants': [{'name': 'v', 'value': 246.0, 'unit': 'GeV', 'origin': 'requester-assumption',
                       'statement': 'take v = 246 GeV'}],
        'definitions': [{'name': 'ratio', 'expression': 'M / v', 'unit': ''}],
        'outputs': [{'name': 'band', 'expression': 'ratio * sqrt(2 * eps)', 'unit': '',
                     'label': 'Coupling band'}],
    }, parameters=[{'name': 'M', 'unit': 'GeV'}, {'name': 'eps', 'unit': ''}])
    values = program.evaluate({'M': np.array([100.0, 246.0]), 'eps': np.array([0.5, 2.0])})
    assert np.allclose(values['band'], [100 / 246.0, 2.0])
    assert program.units['band'] == '' and program.units['ratio'] == ''
    assert program.requester_assumptions() == [{'name': 'v', 'value': 246.0, 'unit': 'GeV',
                                                'statement': 'take v = 246 GeV'}]


def test_piecewise_comparisons_and_threshold_factor():
    program = formula.Program({
        'constants': [],
        'definitions': [{'name': 'beta2', 'expression': '1 - 4 * m**2 / M**2', 'unit': ''}],
        'outputs': [{'name': 'phase', 'expression': 'sqrt(beta2) * beta2 if M > 2 * m else 0', 'unit': '',
                     'label': 'Threshold factor'}],
    }, parameters=[{'name': 'M', 'unit': 'GeV'}, {'name': 'm', 'unit': 'GeV'}])
    values = program.evaluate({'M': np.array([10.0, 1.0]), 'm': np.array([1.0, 1.0])})
    beta2 = 1 - 4 / 100
    assert values['phase'][0] == pytest.approx(beta2 ** 1.5)
    assert values['phase'][1] == 0


def test_synthetic_vector_width_matches_hand_calculation():
    # Gamma(V -> f fbar) = Nc M (gV^2 + gA^2) / (12 pi) for massless fermions.
    program = formula.Program({
        'constants': [{'name': 'Nc', 'value': 3, 'unit': '', 'origin': 'cited', 'citation': 'colour factor'}],
        'definitions': [],
        'outputs': [{'name': 'width', 'expression': 'Nc * M * (gV**2 + gA**2) / (12 * pi)', 'unit': 'GeV',
                     'label': 'Partial width'}],
    }, parameters=[{'name': 'M', 'unit': 'GeV'}, {'name': 'gV', 'unit': ''}, {'name': 'gA', 'unit': ''}])
    values = program.evaluate({'M': np.array(1000.0), 'gV': np.array(0.1), 'gA': np.array(0.2)})
    assert float(values['width']) == pytest.approx(3 * 1000 * 0.05 / (12 * math.pi))
    assert program.units['width'] == 'GeV'


@pytest.mark.parametrize('expression', [
    '__import__("os")', 'M.__class__', '[M for M in range(3)]', 'lambda: 1', 'open("x")',
    'M[0]', 'eval("1")', '"text"', 'M if M else (yield)', 'f(M)', 'sqrt(M, M)', 'sqrt(x=M)',
    '(M := 2)', '{1: 2}',
])
def test_disallowed_syntax_is_refused(expression):
    with pytest.raises(ValueError):
        formula.Program({'constants': [], 'definitions': [],
                         'outputs': [{'name': 'y', 'expression': expression, 'unit': '', 'label': 'Y'}]},
                        parameters=[{'name': 'M', 'unit': ''}])


def test_names_must_be_declared_and_ordered():
    with pytest.raises(ValueError, match='undeclared'):
        formula.Program({'constants': [], 'definitions': [{'name': 'a', 'expression': 'b + 1', 'unit': ''},
                                                          {'name': 'b', 'expression': 'M', 'unit': ''}],
                         'outputs': [{'name': 'y', 'expression': 'a', 'unit': '', 'label': 'Y'}]},
                        parameters=[{'name': 'M', 'unit': ''}])
    with pytest.raises(ValueError, match='redefin'):
        formula.Program({'constants': [], 'definitions': [{'name': 'sqrt', 'expression': 'M', 'unit': ''}],
                         'outputs': [{'name': 'y', 'expression': 'M', 'unit': '', 'label': 'Y'}]},
                        parameters=[{'name': 'M', 'unit': ''}])


def test_constant_provenance_is_required():
    with pytest.raises(ValueError, match='citation'):
        formula.Program({'constants': [{'name': 'k', 'value': 1.3, 'unit': '', 'origin': 'cited'}],
                         'definitions': [], 'outputs': [{'name': 'y', 'expression': 'k', 'unit': '', 'label': 'Y'}]},
                        parameters=[])
    with pytest.raises(ValueError, match='statement'):
        formula.Program({'constants': [{'name': 'k', 'value': 1.3, 'unit': '', 'origin': 'requester-assumption'}],
                         'definitions': [], 'outputs': [{'name': 'y', 'expression': 'k', 'unit': '', 'label': 'Y'}]},
                        parameters=[])


def test_nonfinite_points_are_reported_not_clipped():
    program = formula.Program({'constants': [], 'definitions': [],
                               'outputs': [{'name': 'y', 'expression': 'log(M)', 'unit': '', 'label': 'Y'}]},
                              parameters=[{'name': 'M', 'unit': ''}])
    values = program.evaluate({'M': np.array([1.0, -1.0, 0.0])})
    assert values['y'][0] == 0 and not np.isfinite(values['y'][1]) and not np.isfinite(values['y'][2])
    assert formula.nonfinite_points(values['y']) == [1, 2]


def test_grid_construction_product_log_and_explicit_points():
    grid = formula.grid({'axes': [{'name': 'a', 'unit': '', 'values': [1, 2]},
                                  {'name': 'b', 'unit': 'GeV', 'min': 1, 'max': 100, 'points': 3, 'spacing': 'log'}]})
    assert grid.shape == (2, 3)
    assert np.allclose(grid.columns['b'][0], [1, 10, 100])
    assert np.allclose(grid.columns['a'][:, 0], [1, 2])
    points = formula.grid({'points': [{'a': 1, 'b': 3}, {'a': 2, 'b': 4}],
                           'parameters': [{'name': 'a', 'unit': ''}, {'name': 'b', 'unit': ''}]})
    assert points.shape == (2,) and np.allclose(points.columns['b'], [3, 4])
    with pytest.raises(ValueError):
        formula.grid({'axes': [{'name': 'a', 'unit': '', 'min': 0, 'max': 1, 'points': 2, 'spacing': 'log'}]})
    with pytest.raises(ValueError):
        formula.grid({'axes': [{'name': 'a', 'unit': '', 'min': 0, 'max': 1, 'points': 10 ** 7}]})
