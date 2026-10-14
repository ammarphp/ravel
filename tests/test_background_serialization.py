"""Pure saved-return representation controls; no native execution."""
from copy import deepcopy
import json
import pytest
from ravel.physics import background_discrete_profile as d
from test_background_construction import prepare, result, no_native


def returned(tmp_path):
    spec,fit,_=prepare(tmp_path)
    values=[{'id':'constant','result':result(fit)}, {'id':'linear','result':result(fit)}]
    return spec,fit,values


def test_saved_native_return_round_trip(tmp_path):
    spec,fit,values=returned(tmp_path)
    expected=d.envelope(spec,values,fit)
    saved=json.loads(json.dumps(values,allow_nan=False))
    assert saved != values  # Native grid witness integer keys become JSON strings.
    assert d.envelope(spec,saved,fit)==expected


@pytest.mark.parametrize('kind',['rational_sum','raw_value','witness','mixed_key'])
def test_saved_return_tamper_refuses(tmp_path,kind):
    spec,fit,values=returned(tmp_path)
    saved=json.loads(json.dumps(values,allow_nan=False))
    inference=saved[0]['result']['inference']
    if kind=='rational_sum': inference['absolute_nll_rows'][0]['returned_sum_rational']='999'
    elif kind=='raw_value': inference['rows'][0]['nll0']+=1
    elif kind=='witness': inference['grid_coverage']['witnesses']['0']=999
    else: inference['grid_coverage']['witnesses'][0]=inference['grid_coverage']['witnesses']['0']
    with pytest.raises(ValueError,match='raw rows and checked inference'):
        d.envelope(spec,saved,fit)
