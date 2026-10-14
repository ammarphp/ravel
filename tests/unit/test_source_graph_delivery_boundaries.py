"""Retained-raw delivery and point-vs-integration powers; explicit inert fixtures."""
import copy,pytest
from ravel.physics import native_statistical_construction as g
from test_source_graph_coverage import recipe,generated

@pytest.mark.parametrize('mutation',['missing','different','bool','extra','absent'])
def test_success_raw_native_mean_census_is_literal_and_complete(tmp_path,monkeypatch,mutation):
 _,r,out,*_=generated(tmp_path,monkeypatch)
 if mutation=='missing':out['native_mean_returns'].pop('A')
 elif mutation=='different':out['native_mean_returns']['A']+=1
 elif mutation=='bool':out['native_mean_returns']['A']=True;out['generated_counts']['A']=1.0;out['dataset_counts']['A']=1.0
 elif mutation=='extra':out['native_mean_returns']['invented']=1.0
 else:out.pop('native_mean_returns')
 with pytest.raises(ValueError,match='literal native'):g.validate_expected_delivery(out,r)

@pytest.mark.parametrize('name',['massObs','angleObs'])
def test_integration_powers_stay_inside_original_native_integrand(tmp_path,monkeypatch,name):
 d=recipe(tmp_path,monkeypatch);d['cells'][0]['components'][0]['powers'][name]=1
 with pytest.raises(ValueError,match='coordinate powers'):g.validate_document(d)

def test_additional_bound_point_coordinates_and_signed_generating_point_remain_admitted(tmp_path,monkeypatch):
 d=recipe(tmp_path,monkeypatch);cell=d['cells'][0];cell['components'][0]['powers']['slope']=1;cell['expected_data']['point']['slope']='1/2';cell['expected_data']['point']['c']='-1'
 assert g.validate_document(d)==d
 r=g.response(d,'cell0');assert set(cell['components'][0]['powers'])<=set(r['coordinates'])


def test_full_signed_nonzero_generation_preserves_every_point_and_raw_count(tmp_path,monkeypatch):
 from ravel.physics import regional_expected as e
 from test_source_graph_coverage import fake_graph
 d=recipe(tmp_path,monkeypatch);d['cells'][0]['expected_data']['point'].update(c='-1',slope='1/2')
 r=g.response(d,'cell0');root,w,mc,data,means,_=fake_graph(tmp_path,r)
 out=e.prepare_source_graph(root,w,mc,data,object(),r,tmp_path/'signed.json')
 assert out['generating_state']['c']['value']==-1. and out['generating_state']['slope']['value']==.5
 assert out['native_mean_returns']==out['generated_counts']==out['dataset_counts']==means
 assert set(out['generating_state'])==set(r['coordinates']) and g.validate_expected_delivery(out,r)['counts']==means
