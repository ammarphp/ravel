"""Native geometry and precision controls against supplied synthetic references."""
import pytest
from ravel.physics import native_cumulant as n
from cumulant_fixture import mapping,payload

@pytest.mark.parametrize('precision',[None,'.6e','.17e'])
@pytest.mark.parametrize('edges',[[0,1,3],[.3,1.7,9.1],[0,1e-8,3e-8]])
def test_native_writer_geometry_precision_and_complete_inventory(tmp_path,precision,edges):
    req=n.requests_for(mapping(tmp_path/'inputs',edges=edges));p=tmp_path/'native.yoda';p.write_text(payload(req,precision));out=n.export_family(p,req)
    assert all(len(v['bins'])==len(edges)-1 for v in out['observables'].values())
    assert all(not v['native_finalized']['bin_width_transform_applied'] for v in out['observables'].values())

@pytest.mark.parametrize('token',['1.0000001','0.9999999','1.01','0.99'])
def test_no_arbitrary_near_match_or_precision_tolerance(token):
    assert not n._geometry_matches(token,1.)

def test_exact_asymmetric_midpoint_errors_are_retained():
    lo,hi=.3,1.7;x,a,b=n.booked_geometry([lo,hi])[0]
    assert (x,a,b)==((lo+hi)/2,abs((lo+hi)/2-lo),abs((lo+hi)/2-hi))
