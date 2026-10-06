"""Scientific diagnostic edge cases: no division by zero or invented bands."""
import json
import pytest
from ravel.plotting.science_figures import render

@pytest.mark.parametrize('zero_sm',[False,True])
def test_measurement_ratio_with_supplied_covariance(tmp_path,zero_sm):
    pytest.importorskip('matplotlib');pytest.importorskip('mplhep')
    from test_measurement import document
    model=document()
    if zero_sm:model['sm']['values'][0]=0
    model['theory_covariance']={'bin_ids':['a','b'],'matrix':[[1,0],[0,4]],'unit':'(pb)^2'}
    model['covariance_policy']='independent_theory_sum'
    (tmp_path/'input.json').write_text(json.dumps(model))
    result=render({'mode':'measurement','task':{'input':'input.json','signal_strength':1}},
                  {'bin_ids':['a','b'],'unit':'pb'},tmp_path,tmp_path)
    assert result['status']=='passed'
    assert result['figures'][0]['plot_lint']=='PASS'
    assert (tmp_path/'measurement.pdf').stat().st_size>0
