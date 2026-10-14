"""Complete signed source-deck extraction controls; no native/SDK/model calls."""
import copy
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pytest
from ravel.physics import sfitter_scan_extraction as e
from ravel.workflow import sfitter_workflow as w, agent_graph as g, science
from ravel.workflow.agent_host import AgentHost
from test_sfitter_adapter import workflow_fixture,save,pin,BASIS


def fixture(tmp,*,quadratic=True,components=False,differential=False):
    base=tmp/'inputs';base.mkdir()
    wf,docs,c=workflow_fixture(base)
    target=wf['target'];target['eft'].update(quadratic=quadratic,mixed_pairs=[[BASIS[0],BASIS[1]]] if quadratic else [])
    ob=target['observables'][0];ob.update(bins=['left','right'],normalization='normalized',representation='differential' if differential else 'integrated')
    obs=docs['extraction']['payload']['rows'][0]
    obs.update(bin_widths=[2.,3.],Meas={'data':[1.,2.],'modifiers':[{'name':'pois','type':'pois','data':[0.,0.]},{'name':'stat','type':'stat','data':[1.,1.]}]},Bkg={'data':[0.,0.],'modifiers':[]})
    docs['sm_template']['payload']['rows'][0]['data']=[10.,20.]
    for phase in ('extraction','sm_template'):
        docs[phase]['target_sha256']=g.digest(target);wf['handoffs'][phase]=save(base/(phase+'.json'),docs[phase])
    wp=save(base/'workflow.json',wf);terms=['SM',*w._terms(target)]
    coef=np.asarray([[10.,20.],*[[(-1)**i*(i+1)*.25,(i+1)*-.125] for i in range(22)],
        *([[.5+i*.01,.1+i*.02] for i in range(22)]+[[-.7,.4]] if quadratic else [])])
    coords=[['0']*22]
    for i in range(22):
        for value in (['-1','1'] if quadratic else ['1']):
            row=['0']*22;row[i]=value;coords.append(row)
    if quadratic:
        row=['0']*22;row[0]='2';row[1]='-3';coords.append(row)
    coords += [['0']*22,['.5']+['-.75']+['0']*20]
    points=[]
    # Explicit artificial returned-rate source; not a native fixture.
    source=base/'synthetic-return.txt';source.write_text('Artificial signed binned rate and covariance population; no generator/scientific execution.')
    source_pin=pin(source)
    for i,coordinate in enumerate(coords):
        role='sm_reference' if i==len(coords)-2 else 'held_out' if i==len(coords)-1 else 'training'
        component='sm' if all(v=='0' for v in coordinate) else 'total'
        if components and i==1:component='linear'
        row={'id':'p'+str(i),'component':component,'role':role,'values':dict(zip(BASIS,coordinate)),
             'rates':[],'normalization':{'scale':[2.,2.],'denominator':[5.,5.],
              'divide_by_bin_width':differential,'description':'Supplied toy generator normalization, division by widths only for declared differential bins'},
             'weight_population':[{'id':'absolute','events':10,'positive':7,'negative':2,'zero':1,'sumw':'5','sumw2':'11'}],
             'selected_weight':'absolute','sources':[source_pin],
             'independence':{'declared':role!='training','basis':'Toy premise; not authenticated by this fixture'}}
        D,_=e._design(wf,[row],[[float(x) for x in coordinate]])
        normalized=(D@coef)[0]
        row['rates']=(normalized/.4*(np.array([2.,3.]) if differential else 1.)).tolist()
        points.append(row)
    bins=[{'observable_id':ob['ID'],'bin_id':ident,'unit':ob['unit'],'representation':ob['representation'],'bin_width':width} for ident,width in zip(ob['bins'],obs['bin_widths'])]
    n=len(points)*2
    # Shared signed common mode plus independent diagonal noise: full nontrivial cross covariance.
    common=np.array([(-1.)**i*.03 for i in range(n)])
    C=np.outer(common,common)+np.eye(n)*.01
    rates={'schema_version':1,'kind':'supplied_observed_scan_rates','target_sha256':g.digest(target),'eft':target['eft'],
      'process':target['process'],'perturbative_order':target['perturbative_order'],'bins':bins,'points':points,
      'joint_covariance':{'coordinates':[{'point_id':p['id'],'observable_id':ob['ID'],'bin_id':b['bin_id'],'quantity':'rate'} for p in points for b in bins],
                          'matrix':C.tolist(),'provenance':'Explicit toy shared sample joint covariance, not sumw2 independence'},
      'normalization_uncertainty':'conditional_fixed_denominators','sampling':{'law':'supplied_joint_covariance','description':'Synthetic joint sampling declaration','source_relationships':'all point/bin cross terms supplied'},'sources':[source_pin]}
    definition={'schema_version':1,'target_sha256':g.digest(target),'points':[
        {**{k:p[k] for k in ('id','component','role','values','selected_weight')},'weight_ids':[x['id'] for x in p['weight_population']]} for p in points],'sources':[source_pin]}
    dp=save(base/'scan-definition.json',definition);rp=save(base/'rates.json',rates)
    request={'schema_version':1,'id':'signed_scan','workflow':wp,'rates':rp,'scan_definition':dp,'coupling_sanity_evidence':source_pin,
      'criteria':{'rcond':1e-12,'max_condition':1e6,'max_residual':[1e-10]*2,'max_sm_difference':[1e-10]*2,'max_baseline_difference':[1e-10]*2}}
    return base,request,save(base/'request.json',request),wf,docs,c,rates,coef,C


def test_full_signed_quadratic_mixed_design_and_exact_covariance_map(tmp_path):
    base,r,_,wf,docs,c,rates,coef,C=fixture(tmp_path)
    report=e.extract(r,base)
    assert report['status']=='passed' and report['handoff_eligible']
    assert report['design']['rank']==46 and report['term_order']==['SM',*w._terms(wf['target'])]
    np.testing.assert_allclose(report['coefficients'],coef,rtol=1e-12,atol=1e-12)
    assert report['coefficients'][-1][0]<0 # cross coefficient once, no extra factor2
    A=np.asarray(report['linear_extraction_map']);n=len(rates['points']);T=np.zeros((46*2,n*2))
    T[:,:A.shape[1]*2]=np.kron(A,np.eye(2))
    expected=T@(.16*C)@T.T
    np.testing.assert_allclose(report['coefficient_covariance'],expected,atol=1e-14)
    D=np.asarray(report['design']['matrix']);R=np.kron(D,np.eye(2))@T-np.eye(n*2)
    np.testing.assert_allclose(report['residual_covariance'],R@(.16*C)@R.T,atol=1e-14)
    assert len(report['residuals'])==n and not report['native_fit_completed']
    assert report['raw_point_population']==rates['points']
    E=T.copy();E[:2]=0.;ER=np.kron(D,np.eye(2))@E-np.eye(n*2)
    np.testing.assert_allclose(report['emitted_coefficient_covariance'],E@(.16*C)@E.T,atol=1e-14)
    np.testing.assert_allclose(report['emitted_residual_covariance'],ER@(.16*C)@ER.T,atol=1e-14)
    assert len(report['emitted_residuals'])==n and all(row['passed'] for row in report['emitted_residuals'])


def test_actual_emitted_template_polynomial_must_pass_unchanged_all_point_bands(tmp_path):
    base,r,rp,wf,docs,c,rates,coef,C=fixture(tmp_path)
    docs['sm_template']['payload']['rows'][0]['data']=[9.,20.]
    wf['handoffs']['sm_template']=save(base/'sm_template.json',docs['sm_template'])
    r['workflow']=save(base/'workflow.json',wf)
    r['criteria']['max_sm_difference']=[2.,2.];r['criteria']['max_baseline_difference']=[2.,2.]
    rp=save(base/'request.json',r)
    result=e.extract(r,base)
    assert all(row['passed'] for row in result['residuals']) and all(row['passed'] for row in result['baseline_checks'])
    assert result['status']=='failed' and not result['handoff_eligible']
    np.testing.assert_allclose(result['emitted_residuals'][0]['residual'],[-1.,0.],atol=1e-12)
    assert result['emitted_coefficients'][0]==[9.,20.]
    E=np.asarray(result['emitted_linear_response_map']);ER=np.asarray(result['emitted_residual_map'])
    Cn=np.asarray(result['normalized_joint_covariance'])
    assert np.all(E[:2]==0.)
    np.testing.assert_allclose(result['emitted_coefficient_covariance'],E@Cn@E.T,atol=1e-14)
    np.testing.assert_allclose(result['emitted_residual_covariance'],ER@Cn@ER.T,atol=1e-14)
    receipt=e.materialize(rp,base,tmp_path/'failed-delivery')
    assert receipt['parameterization'] is None and receipt['workflow'] is None
    assert {p.name for p in (tmp_path/'failed-delivery').iterdir()}=={'scan-extraction.json','extraction-receipt.json'}


def test_isolated_components_keep_zero_sm_design_response_in_emitted_diagnostics(tmp_path):
    base,r,*_=fixture(tmp_path,components=True)
    result=e.extract(r,base);assert result['status']=='passed'
    for fitted,emitted in zip(result['residuals'],result['emitted_residuals']):
        if fitted['component'] in ('linear','quadratic'):
            np.testing.assert_allclose(fitted['residual'],emitted['residual'],atol=1e-14)


def test_signed_component_decomposition_and_differential_normalization(tmp_path):
    base,r,*rest=fixture(tmp_path,components=True,differential=True)
    report=e.extract(r,base);assert report['status']=='passed'
    np.testing.assert_allclose(report['coefficients'],rest[-2],atol=1e-12)
    assert report['raw_point_population'][1]['component']=='linear'


def test_source_defined_complete_population_survives_all_way_to_native_card_assembly(tmp_path):
    base,r,rp,wf,docs,c,rates,coef,_=fixture(tmp_path)
    receipt=e.materialize(rp,base,tmp_path/'extracted')
    returned=json.loads(Path(receipt['workflow']['path']).read_bytes())
    docs['conventions']['target_sha256']=g.digest(wf['target'])
    sem=json.loads(Path(c['semantic_manifest']['path']).read_bytes());sem['observables']=wf['target']['observables']
    sem['eft'].update(quadratic=True,mixed_pairs=wf['target']['eft']['mixed_pairs'])
    docs['conventions']['payload']['semantic_manifest']=save(Path(c['semantic_manifest']['path']),sem)
    # Source-bound convention draft continues through the same existing assembler.
    returned['handoffs']['conventions']=save(base/'conventions.json',docs['conventions'])
    assembly=w.materialize_datacard(returned,base,tmp_path/'assembled',run_name='signed_control')
    card=json.loads(Path(assembly['native_input']['datacard']['path']).read_bytes())
    assert len(card['predictions'][0]['modifiers'])==45
    np.testing.assert_allclose(card['predictions'][0]['modifiers'][-1]['data'],coef[-1],atol=1e-12)
    assert card['predictions'][0]['data']==[10.,20.] and card['observations'][0]['bin_widths']==[2.,3.]
    assert not assembly['execution_authorized']


@pytest.mark.parametrize('kind',['drop_point','drop_weight','order','scale','component','missing_axis','covariance_order','asymmetric','negative_cov','unknown_sampling','wrong_units','zero_denominator'])
def test_complete_source_and_covariance_adversaries(tmp_path,kind):
    base,r,rp,wf,docs,c,rates,coef,C=fixture(tmp_path)
    if kind=='drop_point':rates['points'].pop()
    elif kind=='drop_weight':rates['points'][0]['weight_population']=[]
    elif kind=='order':rates['perturbative_order']='invented NNLO'
    elif kind=='scale':rates['eft']=copy.deepcopy(rates['eft']);rates['eft']['target_scale_gev']=2000.
    elif kind=='component':rates['points'][1]['component']='quadratic'
    elif kind=='missing_axis':rates['points'][1]['values'].pop(BASIS[-1])
    elif kind=='covariance_order':rates['joint_covariance']['coordinates'].reverse()
    elif kind=='asymmetric':rates['joint_covariance']['matrix'][0][1]+=.1
    elif kind=='negative_cov':rates['joint_covariance']['matrix'][0][0]=-1.
    elif kind=='unknown_sampling':rates['sampling']['law']='inferred_independent_sumw2'
    elif kind=='wrong_units':rates['bins'][0]['unit']='fb'
    else:rates['points'][0]['normalization']['denominator'][0]=0.
    r['rates']=save(base/'rates.json',rates)
    with pytest.raises(ValueError):e.extract(r,base)


@pytest.mark.parametrize('kind',['rank','condition','heldout','baseline','intercept'])
def test_scientific_failures_preserved_without_parameterization_or_workflow(tmp_path,kind):
    base,r,rp,wf,docs,c,rates,coef,C=fixture(tmp_path)
    if kind=='rank':
        definition=json.loads(Path(r['scan_definition']['path']).read_bytes())
        rates['points'][1]['values']=dict(rates['points'][2]['values']);definition['points'][1]['values']=dict(rates['points'][2]['values'])
        r['scan_definition']=save(base/'scan-definition.json',definition)
    elif kind=='condition':r['criteria']['max_condition']=1.01
    elif kind=='heldout':rates['points'][-1]['rates'][0]+=10.
    elif kind=='baseline':rates['points'][-2]['rates'][0]+=10.
    else:r['criteria']['max_baseline_difference']=[0.,0.]
    r['rates']=save(base/'rates.json',rates);rp=save(base/'request.json',r)
    result=e.extract(r,base);assert result['status'] in ('failed','unresolved') and not result['handoff_eligible']
    receipt=e.materialize(rp,base,tmp_path/'failed')
    assert receipt['parameterization'] is None and receipt['workflow'] is None
    assert set(p.name for p in (tmp_path/'failed').iterdir())=={'scan-extraction.json','extraction-receipt.json'}
    if kind in ('heldout','baseline'):assert len(result['residuals'])==len(rates['points'])


def test_legitimate_singular_covariance_does_not_imply_design_rank_loss(tmp_path):
    base,r,_,wf,docs,c,rates,coef,C=fixture(tmp_path)
    rates['joint_covariance']['matrix']=np.ones_like(C).tolist();r['rates']=save(base/'rates.json',rates)
    result=e.extract(r,base)
    assert result['status']=='passed' and result['input_covariance_diagnostics']['matrix_repaired'] is False


@pytest.mark.parametrize('kind',['normalization','polynomial','covariance','residual'])
def test_nonfinite_computed_arithmetic_never_passes(tmp_path,kind):
    base,r,_,wf,docs,c,rates,coef,C=fixture(tmp_path)
    if kind=='normalization':rates['points'][0]['normalization']['scale'][0]=1e308;rates['points'][0]['normalization']['denominator'][0]=1e-308
    elif kind=='polynomial':
        definition=json.loads(Path(r['scan_definition']['path']).read_bytes())
        for p in rates['points']:p['values'][BASIS[0]]='1e100'
        for p in definition['points']:p['values'][BASIS[0]]='1e100'
        # SM fails the source guard before numerical overflow; also exercise direct design below.
        r['scan_definition']=save(base/'scan-definition.json',definition)
    elif kind=='covariance':
        for p in rates['points']:p['normalization']['scale']=[1e150,1e150]
        rates['joint_covariance']['matrix']=(np.eye(len(C))*1e150).tolist()
    else:
        rates['points'][1]['rates']=[-1e308,1e308];rates['points'][2]['rates']=[1e308,-1e308]
        rates['points'][-1]['values'][BASIS[0]]='1e100'
        definition=json.loads(Path(r['scan_definition']['path']).read_bytes())
        definition['points'][-1]['values']=copy.deepcopy(rates['points'][-1]['values'])
        r['scan_definition']=save(base/'scan-definition.json',definition)
    r['rates']=save(base/'rates.json',rates)
    with pytest.raises(ValueError):e.extract(r,base)


def test_actual_graph_host_uses_complete_bound_sources_without_provider(tmp_path):
    base,r,rp,*_=fixture(tmp_path,quadratic=False)
    spec=e.graph(r,base,rp);root=tmp_path/'graph';g.create(root,spec)
    assert g.execute(root,AgentHost(api_key='not-used'),workers=1)['complete']
    _,state=g._load(root);result=g._result(root,state['nodes']['extract']['result'])
    assert result['result']['value']['status']=='passed' and g.status(root)['usage']['calls']==1
    bad=copy.deepcopy(spec);bad['graph_id']='missing';bad['nodes'][0]['inputs'].pop()
    rd=tmp_path/'missing';g.create(rd,bad)
    assert not g.execute(rd,AgentHost(api_key='not-used'),workers=1)['complete']


def test_actual_public_science_plan_and_approval_refusal(tmp_path):
    base,r,rp,*_=fixture(tmp_path,quadratic=False)
    from test_sfitter_adapter import specification
    spec=specification({'request':rp['path']});spec['mode']='sfitter-scan-extraction'
    spec['review_policy']['policy']['claim_scopes']={e.SCOPE:{'checks':['integrity'],'actions':['delivery']}}
    science.validate(spec)
    assert science.adapter(spec) is e and science._new_capability(spec)
    paths=science.task_inputs(spec,base);assert Path(r['rates']['path']) in paths and Path(r['scan_definition']['path']) in paths
    with pytest.raises(ValueError,match='approved'):e.run(spec['task'],base,tmp_path/'unapproved')
    # Real unapproved ordinary plan, no worker/approval/native dispatch.
    path=save(base/'specification.json',spec);rd=tmp_path/'ordinary'
    plan=science.plan(rd,path['path']);assert science.verify_plan(rd,approved=False)==plan


@pytest.mark.parametrize('target',['scan-extraction.json','parameterization.json','workflow.json','extraction-receipt.json','extra.json'])
def test_every_generated_member_rechecked_after_final_callback(tmp_path,monkeypatch,target):
    base,r,rp,*_=fixture(tmp_path,quadratic=False);original=e.atomic_json
    def mutate(path,doc):
        original(path,doc)
        if Path(path).name=='extraction-receipt.json':
            p=Path(path).parent/target;p.write_text('changed late scientific delivery')
    monkeypatch.setattr(e,'atomic_json',mutate)
    with pytest.raises(ValueError):e.materialize(rp,base,tmp_path/'ending')


def test_ending_input_drift_and_dotdot_output_alias_preserve_originals(tmp_path,monkeypatch):
    base,r,rp,*_=fixture(tmp_path,quadratic=False)
    for out in [base/'derived',tmp_path/'unused/../inputs/derived']:
        with pytest.raises(ValueError):e.materialize(rp,base,out)
    original=e._calculate
    def change(*args):
        result=original(*args);Path(r['rates']['path']).write_text('{}');return result
    monkeypatch.setattr(e,'_calculate',change)
    with pytest.raises(ValueError):e.extract(r,base)


def test_cli_emits_whole_workflow_and_no_native_autorun(tmp_path):
    base,r,rp,*_=fixture(tmp_path,quadratic=False)
    assert e.main(['--request',rp['path'],'--output',str(tmp_path/'cli')])==0
    receipt=json.loads((tmp_path/'cli/extraction-receipt.json').read_bytes())
    assert receipt['workflow'] and not receipt['execution_authorized'] and not receipt['native_fit_completed']


def test_real_common_worker_body_delivers_full_diagnosis_with_synthetic_authority_only(tmp_path,monkeypatch):
    from ravel.physics import science_worker
    from test_sfitter_adapter import specification
    base,r,rp,*_=fixture(tmp_path,quadratic=False)
    task={'request':rp['path']};spec=specification(task);spec['mode']='sfitter-scan-extraction'
    spec['review_policy']['policy']['claim_scopes']={e.SCOPE:{'checks':['integrity'],'actions':['delivery']}}
    rd=tmp_path/'worker';(rd/'inputs').mkdir(parents=True)
    plan={'schema_version':2,'base_dir':str(base),'attempt':1,'output_directory':'outputs/attempt-1',
          'max_seconds':30,'stage_binding':{'input_snapshot':{}}}
    save(rd/'inputs/science-plan.json',plan);save(rd/'inputs/science.json',spec)
    for module in (science,science_worker):
        monkeypatch.setattr(module,'verify_worker',lambda _:plan)
        monkeypatch.setattr(module,'execution_spec',lambda _:spec)
    assert science_worker.main([str(rd),'--attempt','1'])==0
    out=rd/'outputs/attempt-1';report=json.loads((out/'scan-extraction.json').read_bytes())
    assert json.loads((out/'result.json').read_bytes())==report
    assert json.loads((out/'verification.json').read_bytes())['status_scope']==e.SCOPE
    assert json.loads((out/'parameterization.json').read_bytes())['physics_validated'] is False
    assert 'MC likelihood' in (out/'RESULT.md').read_text()
    with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])


def test_complete_joint_rate_denominator_covariance_uses_explicit_delta_map(tmp_path):
    base,r,_,wf,docs,c,rates,coef,C=fixture(tmp_path,quadratic=False)
    order=rates['joint_covariance']['coordinates'];n=len(order)
    rates['normalization_uncertainty']='joint_delta_denominators'
    rates['joint_covariance']['coordinates']=order+[{**row,'quantity':'denominator'} for row in order]
    joint=np.block([[C,np.eye(n)*.002],[np.eye(n)*.002,np.eye(n)*.04]])
    rates['joint_covariance']['matrix']=joint.tolist();r['rates']=save(base/'rates.json',rates)
    report=e.extract(r,base);assert report['status']=='passed'
    Y=np.asarray([p['rates'] for p in rates['points']]).reshape(-1)
    J=np.column_stack((np.eye(n)*.4,np.diag(-Y*.4/5)))
    np.testing.assert_allclose(report['normalization_jacobian'],J,atol=1e-15)
    np.testing.assert_allclose(report['normalized_joint_covariance'],J@joint@J.T,atol=1e-13)
    assert 'first-order delta' in report['normalization_uncertainty_scope']
    assert report['finite_mc_likelihood_transport'].startswith('unimplemented')


def test_complete_multiple_observations_keep_cross_covariance_and_native_handoff_order(tmp_path):
    base,r,rp,wf,docs,c,rates,coef,C=fixture(tmp_path,quadratic=False)
    target=wf['target'];old=copy.deepcopy(target['observables'][0]);old.update(bins=['left'],normalization='absolute')
    other=copy.deepcopy(old);other.update(ID='second',name='second_observation',bins=['right'])
    target['observables']=[old,other]
    original=docs['extraction']['payload']['rows'][0];ext=[]
    for i,ob in enumerate(target['observables']):
        row=copy.deepcopy(original);row.update(ID=ob['ID'],name=ob['name'],bin_widths=[original['bin_widths'][i]])
        for slot in ('Meas','Bkg'):
            row[slot]['data']=[original[slot]['data'][i]]
            for modifier in row[slot]['modifiers']:modifier['data']=[modifier['data'][i]]
        ext.append(row)
    docs['extraction']['payload']['rows']=ext
    sm=docs['sm_template']['payload']['rows'][0]
    docs['sm_template']['payload']['rows']=[{**copy.deepcopy(sm),'ID':ob['ID'],'name':ob['name'],'data':[10.+10*i]} for i,ob in enumerate(target['observables'])]
    for phase in ('extraction','sm_template'):
        docs[phase]['target_sha256']=g.digest(target);wf['handoffs'][phase]=save(base/(phase+'.json'),docs[phase])
    r['workflow']=save(base/'workflow.json',wf)
    rates['target_sha256']=g.digest(target)
    rates['bins']=[{'observable_id':ob['ID'],'bin_id':ob['bins'][0],'unit':ob['unit'],'representation':ob['representation'],'bin_width':2.+i} for i,ob in enumerate(target['observables'])]
    rates['joint_covariance']['coordinates']=[{'point_id':p['id'],'observable_id':b['observable_id'],'bin_id':b['bin_id'],'quantity':'rate'} for p in rates['points'] for b in rates['bins']]
    definition=json.loads(Path(r['scan_definition']['path']).read_bytes());definition['target_sha256']=g.digest(target)
    r['scan_definition']=save(base/'scan-definition.json',definition);r['rates']=save(base/'rates.json',rates);rp=save(base/'request.json',r)
    receipt=e.materialize(rp,base,tmp_path/'both')
    doc=json.loads(Path(receipt['parameterization']['path']).read_bytes())
    assert [row['ID'] for row in doc['payload']['rows']]==['control','second']
    np.testing.assert_allclose(doc['payload']['rows'][1]['modifiers'][0]['data'],coef[1,1:2],atol=1e-12)
    report=json.loads(Path(receipt['report']['path']).read_bytes())
    assert report['coefficient_covariance'][0][1]!=0
