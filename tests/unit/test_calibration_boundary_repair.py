import json,pytest
from test_full_auxiliary_calibration import fixture,fake
from ravel.physics import regional_calibration as c,regional_expected as e,statistical_construction as r


@pytest.mark.parametrize('field,value',[('confidence_level','999999999999999999999999999999999999999/1000000000000000000000000000000000000000'),('confidence_level','1/'+str(10**400)),('numerical_margin','1/'+str(10**400))])
def test_request_binary64_endpoint_or_underflow_refuses(tmp_path,field,value):
    d,q=fixture(tmp_path);q[field]=value
    with pytest.raises(ValueError,match='representable'):c.validate(q,d)


def test_unresolved_tolerance_uses_declared_exact_fraction(tmp_path):
    d,q=fixture(tmp_path)
    q['maximum_unresolved_fraction']='999999999999999999999/1000000000000000000000'
    rows=[{'truth_id':'truth1','ordinal':i,'status':'unresolved'} for i in range(2)]
    assert not c.summarize(q,rows)['cohorts'][0]['unresolved_tolerance_met']


def test_nonfinite_failed_fit_is_structured_same_complete_native_payload(tmp_path,monkeypatch):
    d,q=fixture(tmp_path);facade,w,mc,data,calls=fake(tmp_path,d)
    original=e._profile_fit
    def invalid(*args):
        row=original(*args);row['edm']=float('nan');return row
    monkeypatch.setattr(e,'_profile_fit',invalid)
    value=c.execute(facade,w,mc,data,r.response(d),q,e,tmp_path/'journal.json',60)
    payload=json.dumps(value,allow_nan=False)
    assert json.loads(payload)==json.loads((tmp_path/'journal.json').read_bytes())
    assert value['status']=='delivered' and all(x['status']=='unresolved' for x in value['rows'])
    assert value['rows'][0]['free']['fit']['edm']=={'nonfinite_native_float':'nan'}
    assert value['summary']['cohorts'][0]['identification_interval']==[0,1]
    c.validate_delivery(value,r.response(d),q,e)


def test_failure_report_exposes_existing_full_denominator(tmp_path):
    from ravel.plotting.science_figures import render
    d,q=fixture(tmp_path);rows=[{'truth_id':'truth1','ordinal':i,'status':'unresolved'} for i in range(2)]
    summary=c.summarize(q,rows)
    render({'mode':'full-auxiliary-calibration','task':{}},{'status':'failed','calibration_failure_audit':{'summary':summary}},tmp_path,tmp_path)
    assert json.loads((tmp_path/'calibration-summary.json').read_bytes())==summary
    assert 'Native delivery failed' in (tmp_path/'calibration-report.md').read_text()


def test_nonpositive_native_generating_mean_stays_failed_full_population(tmp_path,monkeypatch):
    # Explicitly supplied bad getter, not an actual ROOT observation.
    d,q=fixture(tmp_path);facade,w,mc,data,calls=fake(tmp_path,d)
    from types import SimpleNamespace
    monkeypatch.setattr(w,'function',lambda name:SimpleNamespace(getVal=lambda:0.))
    result=c.execute(facade,w,mc,data,r.response(d),q,e,tmp_path/'zero-means.json',60)
    assert result['status']=='delivered' and result['top_level_profile_requests']==0
    assert all(row['status']=='unresolved' for row in result['rows'])
    assert result['summary']['cohorts'][0]['identification_interval']==[0,1]
    c.validate_delivery(result,r.response(d),q,e)
