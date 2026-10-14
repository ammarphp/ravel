"""The IR's four-vector arithmetic is the same on every platform.

The producer and the standard-library witness each compute correctly rounded sin, cos and
sinh by their own exact arithmetic; the host mathematical library takes no part.
"""
import math
import random

import pytest

from ravel.physics import analysis_ir as ir
from ravel.validation import analysis_witness as witness

# Values rounded to nearest from 500-bit references, computed once outside this repository.
NEAREST = [
    ('sinh', 0.23883743584156036, 0.24111460107816196),
    ('sinh', 0.2389359325170517, 0.24121592159182356),
    ('cos', 0.1437736451625824, 0.9896823607364003),
    ('sin', 0.1437736451625824, 0.1432788360059702),
    ('sin', 3.141592653589793, 1.2246467991473532e-16),
    ('cos', 1.5707963267948966, 6.123233995736766e-17),
    ('cos', 3.141592653589793, -1.0),
    ('sinh', 20.0, 242582597.70489514),
    ('sinh', -20.0, -242582597.70489514),
    ('sin', 1.0, 0.8414709848078965),
    ('cos', 1.0, 0.5403023058681398),
    ('sinh', 1.0, 1.1752011936438014),
    ('sin', 7.450580596923828e-09, 7.450580596923828e-09),
    ('sinh', 7.450580596923828e-09, 7.450580596923828e-09),
    ('cos', 7.450580596923828e-09, 1.0),
    ('sin', -3.0, -0.1411200080598672),
    ('cos', -3.0, -0.9899924966004454),
    ('sinh', 5.0, 74.20321057778875),
    ('sin', 0.5, 0.479425538604203),
    ('sinh', 1e-05, 1.0000000000166668e-05),
    ('cos', 1e-05, 0.99999999995),
]


@pytest.mark.parametrize('kind,x,expected', NEAREST)
def test_producer_and_witness_return_the_nearest_value(kind, x, expected):
    assert ir._series(x, kind) == expected
    assert witness._nearest(kind, x) == expected


def same(a, b):
    return a == b and math.copysign(1., a) == math.copysign(1., b)


def test_two_independent_implementations_agree_bit_for_bit_over_the_supported_domain():
    generator = random.Random(20261013)
    angles = [generator.uniform(-math.pi, math.pi) for _ in range(400)]
    small = [generator.uniform(-1., 1.)*10.**generator.uniform(-14., 0.) for _ in range(300)]
    edges = [math.pi, -math.pi, 2.**-27, math.nextafter(2.**-27, 0.), math.nextafter(2.**-27, 1.), 1e-300, 5e-324]
    for x in angles+small+edges:
        for kind in ('sin', 'cos', 'sinh'):
            assert same(ir._series(x, kind), witness._nearest(kind, x)), (kind, x)
    for x in [generator.uniform(-20., 20.) for _ in range(200)]+[20., -20.]:
        assert same(ir._series(x, 'sinh'), witness._nearest('sinh', x)), x


@pytest.mark.parametrize('implementation', [lambda kind, x: ir._series(x, kind), witness._nearest])
def test_symmetry_and_signed_zero_follow_the_functions(implementation):
    for x in (0.3, 2.9, 1e-12, 17.5):
        assert implementation('sin', -x) == -implementation('sin', x)
        assert implementation('sinh', -x) == -implementation('sinh', x)
        assert implementation('cos', -x) == implementation('cos', x)
    assert same(implementation('sin', -0.), -0.) and same(implementation('sinh', -0.), -0.)
    assert same(implementation('sin', 0.), 0.) and implementation('cos', 0.) == implementation('cos', -0.) == 1.


def test_the_host_library_takes_no_part(monkeypatch):
    def unavailable(*args):
        raise AssertionError('the host mathematical library was called')
    expected = ir._four_vector(248.7813720703125, 0.23883743584156036, 0.1437736451625824, 0.00051099891)
    for module in (ir.math, witness.math):
        for name in ('sin', 'cos', 'sinh', 'cosh', 'exp', 'pow'):
            monkeypatch.setattr(module, name, unavailable)
    particle = {'pt': 248.7813720703125, 'eta': 0.23883743584156036, 'phi': 0.1437736451625824, 'mass': 0.00051099891}
    assert ir._four_vector(particle['pt'], particle['eta'], particle['phi'], particle['mass']) == expected
    energy, px, py, pz = witness._four(particle)
    assert (px, py, pz, energy) == expected


def test_components_and_energy_follow_the_declared_order_with_plain_products():
    pt, eta, phi, mass = 5.308045387268066, 0.2389359325170517, 0.14374381303787231, 0.00051099891
    px, py, pz, energy = ir._four_vector(pt, eta, phi, mass)
    assert px == pt*0.989686634608117 and py == pt*0.1432493116146098 and pz == pt*0.24121592159182356
    assert energy == math.sqrt(px*px+py*py+pz*pz+mass*mass)
    obj = ir._object(pt, eta, phi, mass, -1, 1, 0)
    assert (obj.px, obj.py, obj.pz, obj.E) == (px, py, pz, energy)
    assert (obj.pt, obj.eta, obj.phi, obj.m, obj.charge, obj.idbits) == (pt, eta, phi, mass, -1, 1)


def test_missing_momentum_uses_the_same_arithmetic():
    met = ir._object(41.5, 0, -2.5, 0, 0, 0, 6)
    assert (met.px, met.py, met.pz) == (41.5*ir._series(-2.5, 'cos'), 41.5*ir._series(-2.5, 'sin'), 0.)
    assert met.E == math.sqrt(met.px*met.px+met.py*met.py)


def test_a_result_beyond_binary64_is_an_error_not_a_wrong_value():
    assert ir._series(700., 'sinh') == witness._nearest('sinh', 700.) == 5.0711602736750225e+303
    with pytest.raises(OverflowError):
        ir._series(800., 'sinh')
    with pytest.raises(OverflowError):
        witness._nearest('sinh', 800.)
