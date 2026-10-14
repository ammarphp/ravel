from pathlib import Path
from decimal import Decimal as D,localcontext
import importlib.util,math
import pytest
import expected_only_analytic as o

def test_gaussian_quantile_and_all_five_nonlinear_crossings():
    rows=o.known_background()['rows']
    assert len(rows)==5
    assert abs(D(rows[2]['q_threshold'])-D('3.841458820694125958'))<D('1e-18')
    assert all(abs(D(x['residual']))<D('1e-100') for x in rows)
    assert sorted(D(x['limit']) for x in rows)==[D(x['limit']) for x in rows]
    # Independent binary64 libm normal CDF, not a second call to the oracle.
    for row in rows:
        p=float(row['quantile']);z=float(o.normal_quantile(str(1-.05*p)))
        assert abs(.5*(1+math.erf(z/math.sqrt(2)))-(1-.05*p))<5e-16

def test_no_integer_rounding_and_pure_conditional_MLE():
    a=o.conditional_anchor()
    with localcontext() as c:
        c.prec=110
        assert abs(D(a['beta'])-D(80)/D(81))<D('1e-108')
        assert [D(x) for x in a['counts']]==[D(20),D(40)]
        assert abs(D(a['score_at_mle']))<D('1e-105')
    assert o.poisson_q('1','20.25','3.5')!=o.poisson_q('1','20','3.5')
    assert o.poisson_q('1','20.25','3.5')>0

@pytest.mark.parametrize('args',[('-1','20','2'),('1','0','2'),('1','20','0')])
def test_invalid_source_law(args):
    with pytest.raises(ValueError):o.poisson_q(*args)
