import pytest
from ravel.workflow import sfitter_review_protocol as p

@pytest.mark.parametrize('actual,expected,absolute,relative',[
    ([1e308],[-1e308],1.,0.),
    ([1.],[1e308],1e308,2.),
    ([float('inf')],[1.],1.,0.),
])
def test_derived_nonfinite_is_refused(actual,expected,absolute,relative):
    with pytest.raises(ValueError):p._agreement(actual,expected,{'absolute':absolute,'relative':relative})

def test_exact_finite_comparison_criteria_remain_unchanged():
    assert p._agreement([1.25],[1.],{'absolute':.25,'relative':0.})==([.25],True)
    assert p._agreement([1.2500001],[1.],{'absolute':.25,'relative':0.})[1] is False
