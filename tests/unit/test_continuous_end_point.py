"""A solver end point within rounding of a bound is moved onto it before stationarity is judged.

Supplied objectives and a real boundary fit whose second solver family is given the residue
another numerical library leaves; no density beyond the retained synthetic model.
"""
import json
import math
from types import SimpleNamespace

import pytest

from ravel.physics import continuous_fit as cf
import test_continuous_fit as fixture

np = pytest.importorskip('numpy')
RESIDUES = (7.124655208381615e-18, 1.059799691512968e-16, math.nextafter(0., 1.), 1e-12)


def quadratic(curvature=1., slope=.4):
    """f(x) = slope*x + curvature*x^2/2 in the first coordinate: it descends toward x=0."""
    def objective(x):
        return slope*x[0]+.5*curvature*x[0]*x[0], np.array([slope+curvature*x[0]]+[0.]*(len(x)-1))
    return objective


def move(x, objective, bounds=((0., 1.),), names=('mu',)):
    return cf._end_point_on_bounds(np.array(x), objective, bounds, names)


@pytest.mark.parametrize('residue', RESIDUES)
def test_a_residue_above_a_lower_bound_the_objective_descends_to_is_removed(residue):
    point, moves = move([residue], quadratic())
    assert point[0] == 0. and len(moves) == 1
    assert moves[0]['parameter'] == 'mu' and moves[0]['side'] == 'lower' and moves[0]['slack'] == residue
    assert moves[0]['nll_after'] <= moves[0]['nll_before']
    stationarity = cf._box_stationarity(point, quadratic()(point)[1], ((0., 1.),), ('mu',))
    assert stationarity['projected_gradient_max'] == 0.
    assert stationarity['active_bounds'] == [{'parameter': 'mu', 'side': 'lower', 'physical': True}]


@pytest.mark.parametrize('slack', [1.0000001e-12, 5e-8, 1e-3])
def test_a_slack_beyond_rounding_is_never_moved(slack):
    point, moves = move([slack], quadratic(curvature=1e16, slope=0.))
    assert point[0] == slack and moves == []
    # The exact-activity rule still sees the interior point and its full gradient.
    stationarity = cf._box_stationarity(point, quadratic(1e16, 0.)(point)[1], ((0., 1.),), ('mu',))
    assert stationarity['active_bounds'] == [] and stationarity['projected_gradient_max'] == 1e16*slack


def test_a_gradient_pointing_into_the_box_keeps_the_point():
    point, moves = move([1e-17], quadratic(slope=-.4))
    assert point[0] == 1e-17 and moves == []
    point, moves = move([1e-17], quadratic(slope=0., curvature=0.))
    assert point[0] == 1e-17 and moves == []


def test_an_objective_that_rises_at_the_bound_keeps_the_point():
    def cliff(x):                                   # a gradient that points out, a value that disagrees
        return (1. if x[0] == 0. else 0.), np.array([.4])
    point, moves = move([1e-17], cliff)
    assert point[0] == 1e-17 and moves == []

    def unusable(x):
        return (math.inf if x[0] == 0. else 0.), np.array([.4])
    assert move([1e-17], unusable)[1] == []


def test_the_upper_bound_and_a_scaled_bound_are_treated_alike():
    def toward_upper(x):
        return -.4*x[0], np.array([-.4])
    point, moves = move([math.nextafter(1., 0.)], toward_upper)
    assert point[0] == 1. and moves[0]['side'] == 'upper'
    # The rounding allowance scales with the bound: 1e-12*(1+|bound|).
    assert move([1e6-5e-7], toward_upper, bounds=((0., 1e6),))[0][0] == 1e6
    assert move([1e6-5e-6], toward_upper, bounds=((0., 1e6),))[1] == []


def test_each_coordinate_is_judged_on_its_own():
    def objective(x):
        return .4*x[0]-.3*x[1], np.array([.4, -.3, 0.])
    point, moves = cf._end_point_on_bounds(np.array([1e-17, math.nextafter(2., 0.), .5]), objective,
                                           ((0., 1.), (-2., 2.), (0., 1.)), ('mu', 'slope', 'transfer_theta'))
    assert list(point) == [0., 2., .5]
    assert [(row['parameter'], row['side']) for row in moves] == [('mu', 'lower'), ('slope', 'upper')]


def supplied_fit(monkeypatch, mu, gradient):
    opt = pytest.importorskip('scipy.optimize')
    document = {'full_range': [0., 5.], 'parameters': {
        'mu': {'bounds': [0., 1.], 'initial': .3}, 'background_yield': {'bounds': [1., 10.], 'initial': 2.},
        'slope': {'bounds': [-1., 1.], 'initial': 0.}, 'transfer_theta': {'bounds': [-8., 8.], 'initial': 0.}}}
    monkeypatch.setattr(cf, 'prepare', lambda d: d)
    monkeypatch.setattr(opt, 'minimize', lambda *a, **kw: SimpleNamespace(
        x=np.array([mu, math.log(2.), 0., 0.]), success=True, message='Supplied synthetic endpoint; no optimizer', nit=0))
    monkeypatch.setattr(cf, 'evaluate', lambda *a: {'nll': 0., 'gradient': [gradient, 0., 0., 0.]})
    monkeypatch.setattr(cf, 'independent_quadrature', lambda *a: {'nll': 0.})
    monkeypatch.setattr(cf, 'identifiability', lambda *a: {'identified': True})
    return cf.fit(document)


@pytest.mark.parametrize('residue', RESIDUES)
def test_fit_verifies_a_supplied_end_point_within_rounding_of_the_physical_bound(monkeypatch, residue):
    result = supplied_fit(monkeypatch, residue, 5e8)
    assert result['verified'] is True and result['parameters']['mu'] == 0.
    for row in result['attempts']:
        assert row['verified'] and row['stationarity']['coordinates'][0] == 0.
        assert row['active_bounds'] == [{'parameter': 'mu', 'side': 'lower', 'physical': True}]
        assert row['projected_gradient_max'] == 0.
        assert row['end_point_moves'] == [{'parameter': 'mu', 'side': 'lower', 'slack': residue,
                                           'nll_before': 0., 'nll_after': 0.}]
    json.dumps(result, allow_nan=False)


def test_fit_records_no_move_for_an_exact_or_a_distant_end_point(monkeypatch):
    for mu, verified in ((0., True), (5e-8, False)):
        result = supplied_fit(monkeypatch, mu, 5e8)
        assert result['verified'] is verified
        assert all('end_point_moves' not in row and row['stationarity']['coordinates'][0] == mu
                   for row in result['attempts'])


def test_boundary_fit_passes_when_one_solver_family_leaves_a_residue(tmp_path, monkeypatch):
    opt = pytest.importorskip('scipy.optimize')
    model = fixture.document()
    model['regions'][1]['observed'] = [20]          # the signal region lies below the continuum: mu = 0
    fixture.bind(tmp_path, model)
    actual, left = opt.minimize, []

    def with_residue(*args, **kwargs):
        result = actual(*args, **kwargs)
        # The first free coordinate is mu when it is fitted; a conditional fit has no mu coordinate.
        # Whatever this host's library left there (exactly zero, or its own residue) is replaced.
        if kwargs['method'] == 'SLSQP' and len(result.x) == 4 and 0. <= result.x[0] <= 1e-12:
            result.x[0] = RESIDUES[len(left) % 2]
            left.append(result.x[0])
        return result
    monkeypatch.setattr(opt, 'minimize', with_residue)
    result = cf.run({'input': 'model.json'}, tmp_path, tmp_path/'outputs')
    assert left, 'the control needs a solver end point on the physical bound'
    assert result['status'] == 'passed', result['profile']['global_fit'].get('failure')
    fitted = result['profile']['global_fit']
    assert fitted['parameters']['mu'] == 0. and fitted['cross_solver_nll_difference'] <= 1e-5
    moved = [row for row in fitted['attempts'] if row['method'] == 'SLSQP']
    assert moved and all(row['verified'] and row['end_point_moves'][0]['slack'] in RESIDUES for row in moved)
    assert all('end_point_moves' not in row for row in fitted['attempts'] if row['method'] == 'L-BFGS-B')
