"""Real ROOT transport controls; these do not pretend to execute upstream SA."""
import csv
from pathlib import Path
import pytest
from ravel.physics.simpleanalysis_adapter import read_input, parse_outputs


def fixture(tmp_path):
    uproot=pytest.importorskip('uproot'); np=pytest.importorskip('numpy'); ak=pytest.importorskip('awkward')
    with uproot.recreate(tmp_path/'input.root') as f:
        tree=f.mktree('ntuple',{'EventNumber':'int32','mcWeights':'var * float32'})
        tree.extend({'EventNumber':np.array([10,20,30],dtype='int32'),'mcWeights':ak.Array([[2.],[-1.],[1.]])})
    with uproot.recreate(tmp_path/'selection.root') as f:
        t=f.mktree('A__ntuple',{'Event':'int32','eventWeight':'float32','SR':'float32','CR':'float32'})
        t.extend({'Event':np.array([10,20,30],dtype='int32'),'eventWeight':np.array([2.,-1.,1.],dtype='float32'),
                  'SR':np.array([2.,-1.,0.],dtype='float32'),'CR':np.array([0.,-1.,1.],dtype='float32')})
    with (tmp_path/'selection.txt').open('w') as f:
        w=csv.writer(f,lineterminator='\n'); w.writerow(['SR','events','acceptance','err'])
        w.writerows([['A_All',3,2,6],['A_SR',2,.5,5**.5/2],['A_CR',2,0,2**.5/2],['A_Empty',0,0,0]])
    contract={'schema_version':1,'level':'reconstructed','energy_unit':'GeV','source':'analytic ROOT transport fixture',
        'object_definitions':'objects.json','response_evidence':[],'weight_names':['nominal'],'independent_events':True}
    return contract


def test_real_root_weight_census_and_overlapping_region_transport(tmp_path):
    c=fixture(tmp_path)
    expected=read_input(tmp_path/'input.root',c)
    assert expected=={10:2.,20:-1.,30:1.}
    r=parse_outputs(tmp_path,'A',expected,['SR','CR','Empty'])
    assert r['yields']['nominal']==[1,0,0]
    assert r['covariance']['nominal']==[[5,1,0],[1,2,0],[0,0,0]]
    assert r['region_overlap_counts']['SR']['CR']==1
    assert len(r['decisions'])==3


@pytest.mark.parametrize('defect',['census','regions','summary','weight'])
def test_slim_transport_missing_or_wrong_evidence_fails(tmp_path,defect):
    c=fixture(tmp_path); expected=read_input(tmp_path/'input.root',c)
    regions=['SR','CR']
    if defect=='census': expected.pop(30)
    if defect=='regions': regions=['Absent']
    if defect=='weight': expected[10]=20
    if defect=='summary':
        text=(tmp_path/'selection.txt').read_text().replace('A_SR,2,0.5','A_SR,2,0.9')
        (tmp_path/'selection.txt').write_text(text)
    with pytest.raises(ValueError): parse_outputs(tmp_path,'A',expected,regions)


@pytest.mark.parametrize('value',[10.5,float('nan'),float('inf'),True])
def test_lossy_event_identifiers_rejected(value):
    from ravel.physics.simpleanalysis_adapter import exact_event_id
    with pytest.raises(ValueError,match='exact finite integer'): exact_event_id(value)
