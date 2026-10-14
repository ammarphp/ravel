"""Full ROOT serialization controls, not native or detector validation."""
from pathlib import Path

import pytest

np = pytest.importorskip('numpy')
uproot = pytest.importorskip('uproot')
pytest.importorskip('awkward')

from uproot.writing.identify import to_TAxis, to_TH1x, to_TH2x, to_TObjString, to_THashList

from ravel.physics.simpleanalysis_outputs import read_outputs


def fixture(tmp_path, *, defect=None):
    path=tmp_path/'selection.root'
    edges=np.array([0.,1.,3.],dtype=np.float64)
    axis=to_TAxis('xaxis','native X',2,0.,3.,fXbins=edges)
    weights=np.array([2.,-.5,0.,1.25],dtype=np.float64)
    squared=np.array([4.,.25,0.,1.5625],dtype=np.float64)
    if defect=='nonfinite':weights[2]=np.nan
    if defect=='negative_squared':squared[1]=-.25
    hist=to_TH1x(None,'signed spectrum',weights,3.,.75,1.8125,0.,0.,
                 None if defect=='missing_squared' else squared,axis)
    two_values=np.arange(16,dtype=np.float64).reshape((4,4))-8
    two_squared=np.arange(16,dtype=np.float64).reshape((4,4))+.5
    hist2=to_TH2x(None,'all 2D flow corners',two_values.flatten(order='F'),16.,0.,120.,0.,0.,0.,0.,0.,
                  two_squared.flatten(order='F'),axis,axis)
    with uproot.recreate(path) as root:
        root['RealRoutine__h']=hist
        root['RealRoutine__h2']=hist2
        tree=root.mktree('RealRoutine__ntuple',{'Event':'int32','eventWeight':'float32','BookedZero':'float32','Observable':'float32'})
        tree.extend({'Event':np.array([10,11],dtype=np.int32),'eventWeight':np.array([2.,-.5],dtype=np.float32),
                     'BookedZero':np.zeros(2,dtype=np.float32),'Observable':np.array([3.,4.],dtype=np.float32)})
        if defect=='unknown_object':root['RealRoutine__unknown']='not an OutputHandler object'
        if defect=='extra_cycle':root['RealRoutine__h']=hist
        if defect=='other_routine':root['OtherRoutine__h']=hist
        if defect=='routine_prefix_collision':root['RealRoutineOther__h']=hist
    return path,two_values,two_squared


def test_complete_signed_flows_native_squared_weights_and_all_ntuple_branches(tmp_path):
    path,two_values,two_squared=fixture(tmp_path)
    observed=read_outputs(path,'RealRoutine',expected_events=2)
    assert observed['physics_validated'] is False
    assert observed['object_census']==['RealRoutine__h','RealRoutine__h2','RealRoutine__ntuple']
    hist=observed['objects']['RealRoutine__h']
    assert hist['sumw_with_flows']==[2.,-.5,0.,1.25]
    assert hist['sumw2_with_flows']==[4.,.25,0.,1.5625]
    assert hist['axes'][0]['edges']==[0.,1.,3.] and hist['axes'][0]['title']=='native X'
    assert hist['bin_covariance'] is None
    two=observed['objects']['RealRoutine__h2']
    assert two['sumw_with_flows']==two_values.tolist()
    assert two['sumw2_with_flows']==two_squared.tolist()
    tree=observed['objects']['RealRoutine__ntuple']
    assert tree['branches']['Observable']['values']==[3.,4.]
    assert tree['branches']['BookedZero']['values']==[0.,0.]
    assert tree['branches']['Event']['typename']=='int32_t'


@pytest.mark.parametrize('defect',['nonfinite','negative_squared','missing_squared','unknown_object','extra_cycle','other_routine','routine_prefix_collision'])
def test_no_dropped_unknown_objects_or_invented_native_moments(tmp_path,defect):
    path,_,_=fixture(tmp_path,defect=defect)
    with pytest.raises(ValueError):read_outputs(path,'RealRoutine',expected_events=2)


def test_full_rejected_event_denominator_is_required(tmp_path):
    path,_,_=fixture(tmp_path)
    with pytest.raises(ValueError,match='census'):read_outputs(path,'RealRoutine',expected_events=1)


def test_unsupported_branch_and_missing_ntuple_are_refused(tmp_path):
    path=tmp_path/'unsupported.root'
    with uproot.recreate(path) as root:
        tree=root.mktree('RealRoutine__ntuple',{'Event':'int32','Text':'string'})
        tree.extend({'Event':np.array([10],dtype=np.int32),'Text':['unsupported']})
    with pytest.raises(ValueError,match='branch type'):read_outputs(path,'RealRoutine',expected_events=1)
    empty=tmp_path/'empty.root'
    with uproot.recreate(empty):pass
    with pytest.raises(ValueError,match='one complete'):read_outputs(empty,'RealRoutine',expected_events=1)


def test_native_file_must_be_ordinary_and_stable(tmp_path,monkeypatch):
    path,_,_=fixture(tmp_path)
    alias=tmp_path/'alias.root';alias.symlink_to(path)
    with pytest.raises(ValueError,match='ordinary'):read_outputs(alias,'RealRoutine',expected_events=2)
    from ravel.physics import simpleanalysis_outputs as outputs
    original=outputs.sources.digest;calls=[]
    def changed(p):
        calls.append(p)
        return original(p) if len(calls)==1 else 'f'*64
    monkeypatch.setattr(outputs.sources,'digest',changed)
    with pytest.raises(ValueError,match='changed'):read_outputs(path,'RealRoutine',expected_events=2)


@pytest.mark.parametrize('partial',[False,True])
def test_native_bin_ids_preserve_partial_or_out_of_order_categorical_labels(tmp_path,partial):
    path,_,_=fixture(tmp_path)
    second=to_TObjString('second');second._bases[0]._members['@fUniqueID']=2
    first=to_TObjString('first');first._bases[0]._members['@fUniqueID']=1
    axis=to_TAxis('xaxis','categorical',2,0.,2.,fLabels=to_THashList([second] if partial else [second,first]))
    hist=to_TH1x(None,'native labels',np.zeros(4),0.,0.,0.,0.,0.,np.zeros(4),axis)
    with uproot.update(path) as root:root['RealRoutine__categorical']=hist
    result=read_outputs(path,'RealRoutine',expected_events=2)
    observed=result['objects']['RealRoutine__categorical']['axes'][0]
    assert observed['labels']==(['','second'] if partial else ['first','second'])
    assert observed['native_label_slots'][0]=={'bin':2,'label':'second'}
