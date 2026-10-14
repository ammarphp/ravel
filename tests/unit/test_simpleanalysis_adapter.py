"""Real ROOT transport controls; these do not pretend to execute upstream SA."""
import csv
from pathlib import Path
import pytest
from ravel.physics.simpleanalysis_adapter import read_input, parse_outputs


def fixture(tmp_path):
    uproot=pytest.importorskip('uproot'); np=pytest.importorskip('numpy'); ak=pytest.importorskip('awkward')
    with uproot.recreate(tmp_path/'input.root') as f:
        tree=f.mktree('ntuple',{'Event':'int32','mcWeights':'var * float32'})
        tree.extend({'Event':np.array([10,20,30],dtype='int32'),'mcWeights':ak.Array([[2.],[-1.],[1.]])})
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


@pytest.mark.parametrize('branch,kind', [('EventNumber','int32'), ('Event','int64'), ('Event','float64')])
def test_input_identity_matches_native_slimreader_branch_and_integer_type(tmp_path,branch,kind):
    c=fixture(tmp_path)
    import uproot, numpy as np, awkward as ak
    with uproot.recreate(tmp_path/'input.root') as f:
        tree=f.mktree('ntuple',{branch:kind,'mcWeights':'var * float32'})
        tree.extend({branch:np.array([10,20,30],dtype=kind),'mcWeights':ak.Array([[2.],[-1.],[1.]])})
    with pytest.raises(ValueError,match='identity|Int_t'):
        read_input(tmp_path/'input.root',c)


def test_eventnumber_alias_cannot_replace_native_event_census(tmp_path):
    c=fixture(tmp_path)
    import uproot, numpy as np, awkward as ak
    with uproot.recreate(tmp_path/'input.root') as f:
        tree=f.mktree('ntuple',{'Event':'int32','EventNumber':'int32','mcWeights':'var * float32'})
        tree.extend({'Event':np.array([10,20,30],dtype='int32'),
            'EventNumber':np.array([90,91,92],dtype='int32'),'mcWeights':ak.Array([[2.],[-1.],[1.]])})
    assert read_input(tmp_path/'input.root',c)=={10:2.,20:-1.,30:1.}


def test_structural_scope_is_explicit_and_requires_full_native_root_abi(tmp_path):
    c=fixture(tmp_path)
    c.update(schema_version=2,level='synthetic_structural')
    with pytest.raises(ValueError,match='upstream branch obligations'):
        read_input(tmp_path/'input.root',c)
    c['response_evidence']=['invented-detector-response.json']
    with pytest.raises(ValueError,match='cannot assert detector'):
        read_input(tmp_path/'input.root',c)


def test_source_built_reconstructed_inputs_also_require_complete_native_slimreader_abi(tmp_path):
    c=fixture(tmp_path)
    assert read_input(tmp_path/'input.root',c)=={10:2.,20:-1.,30:1.}
    with pytest.raises(ValueError,match='upstream branch obligations'):
        read_input(tmp_path/'input.root',c,require_native_abi=True)


def test_native_schema_retains_full_source_object_denominator_and_vector_abi():
    from ravel.physics.simpleanalysis_adapter import native_slim_schema
    schema=native_slim_schema()
    assert len(schema)==82 and schema['Event']=='int32_t' and schema['mcWeights']=='std::vector<float>'
    assert schema['HSTruth_decayVz']=='std::vector<float>' and schema['el_id']=='std::vector<int>'


def test_all_branch_names_do_not_admit_jagged_leaflists_as_native_std_vectors(tmp_path):
    c=fixture(tmp_path);c.update(schema_version=2,level='synthetic_structural')
    import uproot, numpy as np, awkward as ak
    from ravel.physics.simpleanalysis_adapter import native_slim_schema
    schema=native_slim_schema();branches={};data={}
    for name,kind in schema.items():
        if 'vector' in kind:
            branches[name]='var * '+('float32' if 'float' in kind else 'int32')
            data[name]=ak.Array([[1.]]) if name=='mcWeights' else ak.Array([[]])
        else:
            branches[name]='int32' if kind=='int32_t' else 'float32'
            data[name]=np.array([1 if name=='Event' else 0],dtype=branches[name])
    with uproot.recreate(tmp_path/'input.root') as f:
        tree=f.mktree('ntuple',branches);tree.extend(data)
    with pytest.raises(ValueError,match='ABI differs.*mcWeights'):
        read_input(tmp_path/'input.root',c)


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


def test_explicit_named_selection_joins_exact_vector_index_and_keeps_legacy_refusal(tmp_path):
    c=fixture(tmp_path);c['weight_names']=['nominal','muR=0.5 muF=1.0']
    import uproot,numpy as np,awkward as ak
    with uproot.recreate(tmp_path/'input.root') as root:
        tree=root.mktree('ntuple',{'Event':'int32','mcWeights':'var * float32'})
        tree.extend({'Event':np.array([10,20,30],dtype='int32'),'mcWeights':ak.Array([[2.,3.],[-1.,-.5],[1.,2.]])})
    with pytest.raises(ValueError,match='single nominal'):read_input(tmp_path/'input.root',c)
    assert read_input(tmp_path/'input.root',c,weight_name='muR=0.5 muF=1.0')=={10:3.,20:-.5,30:2.}
    assert read_input(tmp_path/'input.root',c,weight_name='nominal')=={10:2.,20:-1.,30:1.}
    with pytest.raises(ValueError,match='absent'):read_input(tmp_path/'input.root',c,weight_name='guessed')


@pytest.mark.parametrize('weights',[[[2.,3.],[-1.],[1.,2.]],[[2.,3.],[-1.,0.],[1.,2.]],[[2.,3.],[-1.,-.5],[1.,float('nan')]]])
def test_wrong_or_skipped_named_weight_census_is_refused(tmp_path,weights):
    c=fixture(tmp_path);c['weight_names']=['nominal','variation']
    import uproot,numpy as np,awkward as ak
    with uproot.recreate(tmp_path/'input.root') as root:
        tree=root.mktree('ntuple',{'Event':'int32','mcWeights':'var * float32'})
        tree.extend({'Event':np.array([10,20,30],dtype='int32'),'mcWeights':ak.Array(weights)})
    with pytest.raises(ValueError,match='complete finite'):read_input(tmp_path/'input.root',c,weight_name='variation')
