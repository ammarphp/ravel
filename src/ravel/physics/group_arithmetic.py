"""Bounded full-group contractions with vectorized binary64 multiplication.

No BLAS reduction, sample compression, centering or covariance repair. Products
are computed by separate NumPy multiply ufuncs; math.fsum retains group order.
The outward bound covers emitted binary64 operands, not missing physics inputs.
"""
from __future__ import annotations

import math
import numpy as np

U = 2. ** -53
TINY = math.ulp(0.)


def require(value, message):
    if not value:
        raise ValueError(message)


def up(value):
    require(math.isfinite(value) and value >= 0., 'finite outward bound required')
    answer = math.nextafter(value, math.inf)
    require(math.isfinite(answer), 'outward bound overflows')
    return answer


def add_up(*values):
    total = 0.
    for value in values:
        require(math.isfinite(value) and value >= 0., 'finite positive bound term required')
        total = up(total + value)
    return total


def rows(value, label):
    out = np.asarray(value, dtype=np.float64)
    require(out.ndim == 2 and 1 <= out.shape[0] <= 768 and
            1 <= out.shape[1] <= 20000 and bool(np.isfinite(out).all()),
            label + ' requires a bounded finite coordinate-by-group matrix')
    return out


def product_sum(left, right):
    """Enclose sum of exact products of the supplied binary64 operands.

    Separate ufunc multiplication has no reduction/reassociation or fused add.
    For each finite product p, |exact(a*b)-p| <= u/(1-u)*|p|+eta.
    eta is conservatively one minimum subnormal. Python fsum's documented
    occasional double rounding is covered by four output ulps, including zero.
    """
    require(left.shape == right.shape and left.ndim == 1 and
            bool(np.isfinite(left).all()) and bool(np.isfinite(right).all()),
            'same finite one-dimensional operands required')
    active = (left != 0.) & (right != 0.)
    count = int(np.count_nonzero(active))
    if count == 0:
        return 0., 0.
    with np.errstate(over='ignore', under='ignore', invalid='ignore'):
        products = np.multiply(left[active], right[active])
    require(bool(np.isfinite(products).all()), 'group product overflows')
    vals = products.tolist()
    try:
        value = math.fsum(vals)
        absolute = math.fsum(abs(p) for p in vals)
    except OverflowError as exc:
        raise ValueError('group sum overflows') from exc
    require(math.isfinite(value) and math.isfinite(absolute), 'group sum overflows')
    absolute_upper = add_up(absolute, up(4*math.ulp(absolute)), 4*TINY)
    rate_upper = up(U / (1.-U))
    error = add_up(up(rate_upper*absolute_upper), up(count*TINY),
                   up(4*math.ulp(value)), 4*TINY)
    return value, error


def positive_product_upper(left, right):
    require(bool((left >= 0.).all()) and bool((right >= 0.).all()),
            'nonnegative propagation operands required')
    value, error = product_sum(left, right)
    if error == 0.:
        return value
    return add_up(value, error)


def gram(value, *, error=None, maximum_pair_products=100_000_000):
    """Full symmetric Gram and emitted-operand forward-error enclosure.

    error[i,g] bounds the previously computed group-gradient error. No error
    vectors are inferred. The bound adds |phi_i| e_j + |phi_j| e_i + e_i e_j.
    Every original group remains represented, including zero/no-fill groups.
    """
    require(type(maximum_pair_products) is int and
            1 <= maximum_pair_products <= 100_000_000,
            'explicit bounded product budget required')
    a = rows(value, 'groups')
    n, m = a.shape
    require(n*n*m <= maximum_pair_products, 'full covariance product budget exceeded')
    e = np.zeros_like(a) if error is None else rows(error, 'gradient bounds')
    require(e.shape == a.shape and bool((e >= 0.).all()),
            'complete nonnegative group-gradient error matrix required')
    covariance = [[0.]*n for _ in range(n)]
    enclosure = [[0.]*n for _ in range(n)]
    absolute = np.abs(a)
    active = [i for i in range(n) if bool((a[i] != 0.).any()) or bool((e[i] != 0.).any())]
    maximum = 0.
    for position, i in enumerate(active):
        for j in active[position:]:
            value, arithmetic = product_sum(a[i], a[j])
            terms = (positive_product_upper(absolute[i], e[j]),
                     positive_product_upper(absolute[j], e[i]),
                     positive_product_upper(e[i], e[j]))
            bound = arithmetic if all(t == 0. for t in terms) else add_up(arithmetic, *terms)
            covariance[i][j] = covariance[j][i] = value
            enclosure[i][j] = enclosure[j][i] = bound
            maximum = max(maximum, bound)
    return {'matrix': covariance, 'entry_forward_error_bounds': enclosure,
            'maximum_entry_forward_error_bound': maximum,
            'groups': m, 'coordinates': n,
            'algorithm': 'separate_binary64_numpy_products_ordered_math_fsum',
            'scope': 'Exact emitted binary64 operand Gram plus supplied absolute group-gradient bounds; source groups are neither centered nor reduced, no physics or covariance repair'}
