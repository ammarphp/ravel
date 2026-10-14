from fractions import Fraction
import math
import numpy as np
import pytest
from ravel.physics import group_arithmetic as a


def exact_dot(x, y):
    return sum((Fraction(float(u))*Fraction(float(v)) for u,v in zip(x,y)), Fraction(0))


@pytest.mark.parametrize('vectors', [
    [[1., -1., 0., 2.], [1., 1., 0., -2.]],
    [[1., 2.**-52, -1.], [1., -2.**-52, 1.]],
    [[1.e100, -1.e100, 3.], [1.e-100, 1.e-100, 1.]],
    [[math.ulp(0.), 0., -math.ulp(0.)], [.5, 2., .5]],
])
def test_emitted_binary_gram_encloses_fraction(vectors):
    r = a.gram(vectors)
    for i,x in enumerate(vectors):
        for j,y in enumerate(vectors):
            exact = exact_dot(x,y)
            assert abs(Fraction(r['matrix'][i][j])-exact) <= Fraction(r['entry_forward_error_bounds'][i][j])
            assert r['matrix'][i][j] == r['matrix'][j][i]


def test_gradient_error_encloses_exact_perturbed_gram():
    x = [[1., -1., 0.], [2.**-40, 2., -3.]]
    e = [[2.**-30, 2.**-31, 2.**-32], [2.**-35]*3]
    r = a.gram(x, error=e)
    # Independent corner extremals, not a product-computed tolerance.
    for sign in (-1,1):
        perturbed = [[Fraction(v)+sign*Fraction(d) for v,d in zip(row,er)] for row,er in zip(x,e)]
        for i in range(2):
            for j in range(2):
                exact = sum((u*v for u,v in zip(perturbed[i],perturbed[j])), Fraction(0))
                assert abs(Fraction(r['matrix'][i][j])-exact) <= Fraction(r['entry_forward_error_bounds'][i][j])


def test_full_20000_groups_once_with_signed_zero_weights():
    # Complete event/counter vectors. Unselected/zero events are retained.
    weights = [1., -0.5, 0., 2.]*5000
    counts = [w if i%3 == 0 else 0. for i,w in enumerate(weights)]
    r = a.gram([counts, weights], maximum_pair_products=80_000)
    assert r['groups'] == 20000
    assert r['matrix'][1][1] == 26250.
    assert r['matrix'][0][1] == float(exact_dot(counts, weights))


def test_exact_zeros_do_not_acquire_roundoff_or_drop_population():
    r = a.gram([[0.]*20000, [1.]*20000])
    assert r['matrix'][0] == [0., 0.]
    assert r['entry_forward_error_bounds'][0] == [0., 0.]
    assert r['groups'] == 20000


@pytest.mark.parametrize('vectors,error', [
    ([[float('nan')]],None), ([[float('inf')]],None),
    ([[1.]], [[-1.]]), ([[1.,2.]], [[0.]]),
    ([[1.e308]],None), ([[]],None),
])
def test_invalid_or_nonrepresentable_refuses(vectors,error):
    with pytest.raises(ValueError): a.gram(vectors,error=error)


def test_budget_population_refusals():
    with pytest.raises(ValueError): a.gram([[1.]*20001])
    with pytest.raises(ValueError): a.gram([[1.]*20]*3, maximum_pair_products=179)
    with pytest.raises(ValueError): a.gram([[1.]], maximum_pair_products=True)
