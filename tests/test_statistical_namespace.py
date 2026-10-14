"""Pure namespace admission and unchanged supplied-law controls."""
import copy
import pytest
from ravel.physics import statistical_construction as c
from test_statistical_construction import fixture


def renamed_parameter(d, name):
    old=d['parameters'][0]['name'];d['parameters'][0]['name']=name
    for term in d['terms']:
        if old in term['powers']:term['powers'][name]=term['powers'].pop(old)
    return d


def bins(d, names):
    d['bins']=[{**d['bins'][0],'id':n,'observation_id':'events/'+n} for n in names]
    for t in d['terms']:
        t['coefficients']=[t['coefficients'][0]]*len(names)
        t['log_response']=[copy.deepcopy(t['log_response'][0]) for n in names]
    return d


@pytest.mark.parametrize('name',['model_s','model_b','nuisancePdf','pdf_binA','pdf_binA_bonly','POI','observables','nuisances','globalObservables','discreteParams'])
def test_parameter_generated_name_refuses_before_bundle_creation(tmp_path,name):
    d=renamed_parameter(fixture(tmp_path,True),name)
    with pytest.raises(ValueError,match='namespace collision'):c.validate(d)
    with pytest.raises(ValueError,match='namespace collision'):c.write_native_bundle(d,tmp_path/'never',runtime={},fit={},max_seconds=1)
    assert not (tmp_path/'never').exists()


@pytest.mark.parametrize('other',['A_bonly','A_proc_ravel_full','A_proc_ravel_dummy'])
def test_cross_bin_generated_names_refuse(tmp_path,other):
    d=bins(fixture(tmp_path),['A',other])
    with pytest.raises(ValueError,match='namespace collision'):c.response(d)


@pytest.mark.parametrize('aux,name',[(False,'model_s_0'),(True,'modelObs_s_0'),(True,'modelObs_s'),(False,'model_b_5')])
def test_combination_block_namespace_refuses(tmp_path,aux,name):
    d=renamed_parameter(bins(fixture(tmp_path,aux),['B'+str(i) for i in range(51)]),name)
    with pytest.raises(ValueError,match='namespace collision'):c.datacard(d)


def test_source_only_labels_and_noncolliding_suffixes_keep_semantics(tmp_path):
    d=fixture(tmp_path,True);d['model_id']='model_s';d['auxiliary']['names']=['model_s','pdf_binA']
    d=bins(d,['X_bonly','Y','Z','A'])
    out=c.validate(d)
    assert out==d and out is not d
    jet=c.mean_jet(d,c.initial_point(d))
    assert jet['means']==[30]*4
    assert 'ravel_aux_0' in c.coordinates(d)
