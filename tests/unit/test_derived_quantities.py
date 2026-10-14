"""Independent numerical, source-formula, basis and adverse admission tests."""
import copy, gzip, hashlib, json, math, re
from fractions import Fraction
from decimal import Decimal, localcontext
from pathlib import Path
import pytest
np = pytest.importorskip("numpy")
from ravel.physics.derived_quantities import derive, derive_from_file, prediction_slice, DerivedQuantityError

def bind(contract,joint,path):
    path.write_text(json.dumps(joint,allow_nan=False))
    pin={'id':'joint','path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
    contract['sources']=[p for p in contract['sources'] if p['id']!='joint']+[pin]

@pytest.fixture
def sample(tmp_path):
    source=tmp_path/'definition.txt';source.write_text('Explicit structural ratio, subset efficiency and asymmetry.\n')
    pin={'id':'formula','path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'size':source.stat().st_size}
    definition={'source':'formula','first_line':1,'last_line':1,'text':source.read_text().strip()}
    quantity={'axis':{'name':'x','unit':'GeV'},'bins':[{'id':'b1','low':0,'high':1},{'id':'b2','low':1,'high':3}],'unit':'pb','representation':'integrated'}
    components=[{'id':c,'path':'/'+c,'quantity':copy.deepcopy(quantity),'scale':{'nominal':1,'scale-up':2},'definition':definition} for c in ['A','B']]
    outputs=[]
    for operation in ['ratio','efficiency','asymmetry']:
        q=copy.deepcopy(quantity);q['unit']='1'
        outputs.append({'id':operation,'path':'/'+operation,'quantity':q,'operation':operation,'left':{'terms':[{'component':'A','coefficient':1}],'offset':[0,0]},'right':{'terms':[{'component':'B','coefficient':1}],'offset':[0,0]},'denominator_policy':'positive','definition':definition,'subset_evidence':'formula' if operation=='efficiency' else None})
    basis=[{'weight':w,'component':c,'bin':b} for w in ['nominal','scale-up'] for c in ['A','B'] for b in ['underflow','b1','b2','overflow']]
    groups=[]
    for g in range(4):
        vector=[]
        for r in basis:
            val=0 if r['bin'] in ['underflow','overflow'] else (int(g<2) if r['component']=='A' else 1)
            if r['bin']=='b2':val*=g+1
            if r['weight']=='scale-up':val*=.8 if r['component']=='A' else 1.2
            vector.append(val)
        groups.append({'id':str(g),'vector':vector})
    joint={'schema_version':1,'basis':basis,'values':[math.fsum(g['vector'][i] for g in groups) for i in range(len(basis))],'uncertainty':{'kind':'independent_group_moments','semantics':'poissonized_independent_groups_uncentred_second_moment','groups':groups}}
    contract={'schema_version':1,'kind':'derived-quantity-contract','analysis_id':'structural-control','sources':[pin],'joint_source':'joint','weights':[{'id':'nominal','nuisance':None,'direction':'nominal','source':'formula'},{'id':'scale-up','nuisance':'scale','direction':'up','source':'formula'}],'components':components,'outputs':outputs,'output_census':[{'path':c['path'],'kind':'component','visibility':'internal'} for c in components]+[{'path':o['path'],'kind':'derived','visibility':'public'} for o in outputs],'flow_policy':'retain_inputs_not_derived','exposure':{w:{'groups':4,'sumw':4,'sumw2':4,'normalization':'Explicit structural identity scale','source':'formula','weight_policy':'nonnegative'} for w in ['nominal','scale-up']},'unsupported_transforms':[]}
    path=tmp_path/'joint.json';bind(contract,joint,path)
    return contract,joint,path

def test_subset_joint_variance_and_flow_retention(sample):
    c,j,_=sample;r=derive(c,j)
    assert r['values'][0]==.5
    assert r['output_covariance'][0][0]==pytest.approx(float(Fraction(1,16)))
    # Assuming independent numerator and denominator gives 3/16, not 1/16.
    assert r['output_covariance'][0][0]!=pytest.approx(float(Fraction(3,16)))
    assert len(r['input_basis'])==16 and len(r['output_basis'])==12
    assert {b['bin'] for b in r['output_basis']}=={'b1','b2'}
    assert r['input_basis']==j['basis'] and r['input_uncertainty']==j['uncertainty']
    assert r['inference'] is None and not r['physics_validated']

def test_independent_full_jacobian_and_cross_variation_covariance(sample):
    c,j,_=sample;r=derive(c,j); x=j['values']; keys=[tuple(b[k] for k in ('weight','component','bin')) for b in j['basis']]
    G=np.array([g['vector'] for g in j['uncertainty']['groups']]); expected=[]
    for b in r['output_basis']:
        ia=keys.index((b['weight'],'A',b['bin']));ib=keys.index((b['weight'],'B',b['bin']));scale=c['components'][0]['scale'][b['weight']]
        a=x[ia]*scale;d=x[ib]*scale; row=[0.]*len(x)
        if b['output']=='asymmetry':da=2*d/(a+d)**2;db=-2*a/(a+d)**2
        else:da=1/d;db=-a/d**2
        row[ia]=da*scale;row[ib]=db*scale;expected.append(row)
    assert np.allclose(r['jacobian'],expected,rtol=1e-14,atol=1e-16)
    covariance=[[math.fsum(math.fsum(a*v for a,v in zip(row,g))*math.fsum(a*v for a,v in zip(other,g)) for g in G) for other in expected] for row in expected]
    assert np.allclose(r['output_covariance'],covariance,rtol=1e-13,atol=1e-16)
    assert covariance[0][2]!=0 # Cross-weight correlations survive.

def test_basis_permutation_invariance(sample):
    c,j,path=sample;before=derive(c,j);order=list(reversed(range(len(j['basis']))))
    j['basis']=[j['basis'][i] for i in order];j['values']=[j['values'][i] for i in order]
    for g in j['uncertainty']['groups']:g['vector']=[g['vector'][i] for i in order]
    bind(c,j,path);after=derive(c,j)
    assert before['values']==after['values'];assert np.allclose(before['output_covariance'],after['output_covariance'])
    assert np.allclose(np.array(before['jacobian'])[:,order],after['jacobian'])

def test_supplied_full_covariance_and_fixed_offsets(sample):
    c,j,path=sample;groups=np.array([g['vector'] for g in j['uncertainty']['groups']]);C=groups.T@groups
    j['uncertainty']={'kind':'supplied_covariance','matrix':C.tolist(),'semantics':'Explicit conditional full covariance'}
    c['outputs'][0]['left']['offset']=[3,3];c['outputs'][0]['right']['offset']=[2,2]
    bind(c,j,path);r=derive(c,j);assert r['values'][0]==5/6
    assert r['input_covariance']==C.tolist() and r['covariance_diagnostics']['matrix_repaired'] is False

def test_native_errors_retained_separately(sample):
    c,j,path=sample;r=derive(c,j)
    j['native_finalized']={'semantics':'Supplied native marginal controls, not delta-covariance','basis':r['output_basis'],'values':r['values'],'errors_low':[-.9]*12,'errors_high':[1.1]*12}
    bind(c,j,path);r=derive(c,j)
    assert r['native_finalized_separate']==j['native_finalized'] and r['output_covariance'][0][0]==pytest.approx(1/16)

@pytest.mark.parametrize('mutation,match',[
    ('no_flow','basis'),('duplicate_basis','basis'),('wrong_geometry','join'),('wrong_unit','units'),('marginal_only','joint covariance'),('missing_cross_covariance','complete'),('indefinite','semidefinite'),('asymmetric','asymmetric'),('bad_exposure','exposure'),('signed_efficiency','efficiency'),('subset','subset'),('negative_weight','weight policy'),('zero_denominator','denominator'),('unknown_transform','transform'),('unknown_key','keys'),('census_missing','census'),('bad_excerpt','excerpt'),('bad_pin','digest'),('bad_weight','identity'),('missing_scale','scales'),('efficiency_offset','offsets'),('unbound_subset','subset'),('flow_derive','flow policy'),('moment_sum','sums'),('native_missing','native'),('nonfinite','finite')])
def test_adverse_admission(sample,mutation,match):
    c,j,path=sample
    if mutation=='no_flow':j['basis'].pop();j['values'].pop()
    elif mutation=='duplicate_basis':j['basis'][-1]=j['basis'][0]
    elif mutation=='wrong_geometry':c['outputs'][0]['quantity']['bins'][-1]['high']=4
    elif mutation=='wrong_unit':c['components'][0]['quantity']['unit']='fb'
    elif mutation=='marginal_only':j['uncertainty']={'kind':'marginal_errors','errors':[1]*16}
    elif mutation in ['missing_cross_covariance','indefinite','asymmetric']:
        C=np.eye(16);j['uncertainty']={'kind':'supplied_covariance','matrix':C.tolist(),'semantics':'declared'}
        if mutation=='missing_cross_covariance':j['uncertainty']['matrix'][0].pop()
        elif mutation=='indefinite':j['uncertainty']['matrix'][0][0]=-1
        else:j['uncertainty']['matrix'][0][1]=1
    elif mutation=='bad_exposure':c['exposure']['nominal']['groups']=3
    elif mutation=='signed_efficiency':c['exposure']['nominal']['weight_policy']='signed'
    elif mutation=='subset':
        for g in j['uncertainty']['groups']:g['vector'][1]=2
        j['values'][1]=8
    elif mutation=='negative_weight':j['values'][1]=-2; j['uncertainty']['groups'][0]['vector'][1]=-3
    elif mutation=='zero_denominator':
        for g in j['uncertainty']['groups']:g['vector'][5]=0
        j['values'][5]=0
    elif mutation=='unknown_transform':c['outputs'][0]['operation']='custom_ast'
    elif mutation=='unknown_key':c['magic_covariance']=True
    elif mutation=='census_missing':c['output_census'].pop()
    elif mutation=='bad_excerpt':c['outputs'][0]['definition']['text']='changed'
    elif mutation=='bad_pin':c['sources'][0]['sha256']='0'*64
    elif mutation=='bad_weight':c['weights'][1]['nuisance']=None
    elif mutation=='missing_scale':c['components'][0]['scale'].pop('scale-up')
    elif mutation=='efficiency_offset':c['outputs'][1]['left']['offset'][0]=1
    elif mutation=='unbound_subset':c['outputs'][1]['subset_evidence']='absent'
    elif mutation=='flow_derive':c['flow_policy']='guess_zero_flow'
    elif mutation=='moment_sum':j['values'][1]=3
    elif mutation=='native_missing':j['native_finalized']={'semantics':'unknown','basis':[],'values':[],'errors_low':[],'errors_high':[]}
    elif mutation=='nonfinite':c['components'][0]['scale']['nominal']=float('nan')
    bind(c,j,path)
    with pytest.raises(DerivedQuantityError,match=match):derive(c,j)

def test_unbound_joint_document_refused(sample):
    c,j,_=sample;j['values'][1]+=1
    with pytest.raises(DerivedQuantityError,match='source-bound'):derive(c,j)

def test_signed_ratio_requires_explicit_policy(sample):
    c,j,path=sample
    c['outputs']=c['outputs'][:1]; c['output_census']=[r for r in c['output_census'] if r['kind']=='component' or r['path']=='/ratio']
    for e in c['exposure'].values():e['weight_policy']='signed'
    for i,r in enumerate(j['basis']):
        if r['component']=='B':
            j['values'][i]*=-1
            for g in j['uncertainty']['groups']:g['vector'][i]*=-1
    bind(c,j,path)
    with pytest.raises(DerivedQuantityError,match='denominator'):derive(c,j)
    c['outputs'][0]['denominator_policy']='nonzero_signed';assert derive(c,j)['values'][0]==-.5

def test_file_contract_binding_and_exact_prediction_slice(sample):
    c,j,path=sample;contract_path=path.parent/'contract.json';contract_path.write_text(json.dumps(c))
    digest=hashlib.sha256(contract_path.read_bytes()).hexdigest()
    r=derive_from_file(contract_path,expected_sha256=digest)
    basis=[r['output_basis'][1],r['output_basis'][0]];p=prediction_slice(r,basis)
    assert p['values']==[r['values'][1],r['values'][0]]
    assert p['covariance']==[[r['output_covariance'][i][k] for k in [1,0]] for i in [1,0]]
    assert p['experimental_independence'] is None and p['statistical_inference'] is None
    with pytest.raises(DerivedQuantityError,match='digest'):derive_from_file(contract_path,expected_sha256='0'*64)
    with pytest.raises(DerivedQuantityError,match='single-weight'):prediction_slice(r,[r['output_basis'][0],r['output_basis'][2]])
    with pytest.raises(DerivedQuantityError,match='unique'):prediction_slice(r,[r['output_basis'][0],r['output_basis'][0]])
    with pytest.raises(DerivedQuantityError,match='unknown'):prediction_slice(r,[{'weight':'nominal','output':'ratio','bin':'b99'}])

def test_group_subset_violation_despite_valid_central_efficiency(sample):
    c,j,path=sample
    # Two accepted-group contributions [1.5,.5] still sum to 2 of total 4,
    # but the first group violates a claimed numerator subset of its total 1.
    j['uncertainty']['groups'][0]['vector'][1]=1.5;j['uncertainty']['groups'][1]['vector'][1]=.5
    bind(c,j,path)
    with pytest.raises(DerivedQuantityError,match='groups violate'):derive(c,j)

def test_jacobian_finite_difference_of_mixture_offsets(sample):
    c,j,path=sample;c['outputs']=c['outputs'][:1];c['output_census']=[r for r in c['output_census'] if r['kind']=='component' or r['path']=='/ratio']
    c['outputs'][0]['left']['offset']=[5,6];c['outputs'][0]['right']['offset']=[7,8]
    G=np.array([g['vector'] for g in j['uncertainty']['groups']]);j['uncertainty']={'kind':'supplied_covariance','matrix':(G.T@G).tolist(),'semantics':'full supplied structural covariance'}
    bind(c,j,path);r=derive(c,j);step=1e-5;direction=np.arange(16)/100
    plus=copy.deepcopy(j);minus=copy.deepcopy(j)
    plus['values']=(np.array(j['values'])+step*direction).tolist();minus['values']=(np.array(j['values'])-step*direction).tolist()
    # Keep the zero flow states nonnegative while perturbing finite bins.
    direction[[0,3,4,7,8,11,12,15]]=0
    plus['values']=(np.array(j['values'])+step*direction).tolist();minus['values']=(np.array(j['values'])-step*direction).tolist()
    bind(c,plus,path);a=np.array(derive(c,plus)['values']);bind(c,minus,path);b=np.array(derive(c,minus)['values'])
    assert np.allclose((a-b)/(2*step),np.array(r['jacobian'])@direction,rtol=3e-7,atol=1e-10)

def test_supplied_positive_definite_factor_forward_error_enclosure(sample):
    c,j,path=sample
    rng=np.random.default_rng(928);factor=rng.normal(size=(16,16));C=factor@factor.T+np.eye(16)*.3
    j['uncertainty']={'kind':'supplied_covariance','matrix':C.tolist(),'semantics':'positive-definite full structural covariance'}
    bind(c,j,path);r=derive(c,j)
    assert 'Cholesky' in r['derived_covariance_arithmetic']
    assert r['input_covariance']==C.tolist() and r['source_factor_residual_max_abs']>=0
    bound=Decimal.from_float(r['factor_covariance_forward_error_bound'])
    with localcontext() as ctx:
        ctx.prec=100
        for i,row in enumerate(r['jacobian']):
            for k,other in enumerate(r['jacobian']):
                exact=sum((Decimal.from_float(a)*Decimal.from_float(float(C[x,y]))*Decimal.from_float(b) for x,a in enumerate(row) if a for y,b in enumerate(other) if b),Decimal(0))
                assert abs(Decimal.from_float(r['output_covariance'][i][k])-exact)<=bound

def test_common_large_exposure_scale_cancels_without_denominator_square(sample):
    c,j,_=sample;before=derive(c,j)
    for component in c['components']:
        for weight in component['scale']:component['scale'][weight]*=1e200
    after=derive(c,j)
    assert np.allclose(before['values'],after['values'],rtol=1e-14)
    assert np.allclose(before['jacobian'],after['jacobian'],rtol=1e-14,atol=1e-16)
    assert np.allclose(before['output_covariance'],after['output_covariance'],rtol=1e-13,atol=1e-16)
    assert after['denominators'][0]['input_variance'] is None
    assert math.isfinite(after['denominators'][0]['relative_input_variance'])

def test_normal_operation_complete_inputs_fresh_output_and_source_digest(sample):
    from ravel.physics.derived_quantities import validate,inputs,run
    c,j,path=sample;contract=path.parent/'contract.json';contract.write_text(json.dumps(c))
    spec={'schema_version':1,'input':str(contract),'contract_sha256':hashlib.sha256(contract.read_bytes()).hexdigest()}
    assert validate(spec)==spec and len(inputs(spec,path.parent))==3
    out=path.parent/'operation-output';r=run(spec,path.parent,out)
    assert r==json.loads((out/'derived-quantities.json').read_text())
    assert r['status']=='passed' and not r['physics_validated'] and r['inference'] is None
    with pytest.raises(DerivedQuantityError,match='fresh'):run(spec,path.parent,out)
    spec['contract_sha256']='0'*64
    with pytest.raises(DerivedQuantityError,match='digest'):inputs(spec,path.parent)
    with pytest.raises(DerivedQuantityError,match='keys'):validate({**spec,'guess_covariance':True})

def test_actual_worker_filesystem_lifecycle_with_real_derived_adapter(sample,monkeypatch):
    from ravel.physics import science_worker
    from ravel.plotting import science_figures
    from ravel.workflow.state_io import atomic_json,read_json
    from test_science_capability_integration import specification
    c,j,path=sample;contract=path.parent/'contract.json';contract.write_text(json.dumps(c))
    task={'schema_version':1,'input':str(contract),'contract_sha256':hashlib.sha256(contract.read_bytes()).hexdigest()}
    spec=specification('derived-quantities',task)
    rd=path.parent/'worker-run';(rd/'inputs').mkdir(parents=True)
    atomic_json(rd/'inputs/science.json',spec)
    atomic_json(rd/'inputs/science-plan.json',{'schema_version':2,'execution_task':task,'mutable_inputs':[]})
    atomic_json(rd/'inputs/science-execution-task.json',{'schema_version':1,'task':task})
    proposal={'base_dir':str(path.parent),'attempt':1,'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}}
    # Only approval verification and rendering are mocked. Dispatch, actual
    # execution-spec admission, source guards, adapter and filesystem are real.
    monkeypatch.setattr(science_worker,'verify_worker',lambda _:proposal)
    monkeypatch.setattr(science_figures,'render',lambda *_:{'figures':[],'tables':[]})
    assert science_worker.main([str(rd),'--attempt','1'])==0
    out=rd/'outputs/attempt-1';result=read_json(out/'result.json')
    assert result==read_json(out/'derived-quantities/derived-quantities.json')
    assert result['status']=='passed' and not result['physics_validated'] and result['inference'] is None
    assert read_json(out/'verification.json')['passed'] is True
    assert read_json(out/'checkin2.json')['sections']['waypoint']['status']=='passed'
    snapshot={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])
    assert snapshot=={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
