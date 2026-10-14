"""Portable conditional BSM covariance law; no native or optimizer calls."""
import hashlib,json,math
from copy import deepcopy
from fractions import Fraction
import pytest
np=pytest.importorskip('numpy')
pytest.importorskip('scipy')
from ravel.physics import ratio_measurement as ratio
from test_ratio_measurement import document,task


def bsm_document():
    d=document();ids=d['data']['bin_ids'];units=d['prediction']['sm_numerator']['units']
    groups=[[.3,-.2,.1,.2],[-.1,.4,.2,-.1],[.05,.1,-.15,.3]]
    c=[[math.fsum(g[i]*g[j] for g in groups) for j in range(4)] for i in range(4)]
    d['prediction']['bsm_component_covariance']={
        'coordinate_ids':[kind+'/'+i for kind in ['bsm_numerator','bsm_denominator'] for i in ids],
        'coordinate_units':units*2,'matrix':c,'source':'Full synthetic same-event numerator/denominator covariance',
        'method':'first_order_delta_method','experimental_independence':'declared_independent',
        'sm_treatment':'conditional_fixed_central_no_theory_covariance'}
    return d


def exact_emitted_j_covariance(j,c):
    # Separate oracle: dense Fraction contraction of exactly emitted binary64.
    f=Fraction.from_float
    return [[float(sum((f(a)*f(c[k][l])*f(b)
        for k,a in enumerate(ji) for l,b in enumerate(jj)),Fraction()))
        for jj in j] for ji in j]


def test_complete_bsm_crosscovariance_and_direct_gaussian_law():
    d=bsm_document();old=deepcopy(d);r=ratio.diagnose(d,task(.7));j=np.array(r['delta_method_jacobian'])[:,4:]
    expected=exact_emitted_j_covariance(j.tolist(),d['prediction']['bsm_component_covariance']['matrix'])
    assert np.array(r['prediction_covariance'])==pytest.approx(np.array(expected),rel=2e-15,abs=1e-17)
    c=np.array(r['combined_covariance']);v=np.array(d['data']['values'])-r['prediction']['values']
    want=(c[1,1]*v[0]**2-2*c[0,1]*v[0]*v[1]+c[0,0]*v[1]**2)/(c[0,0]*c[1,1]-c[0,1]**2)
    assert r['goodness_of_fit']['chi2']==pytest.approx(want,rel=2e-15)
    assert d==old
    assert r['prediction']['source_contract']['bsm_component_covariance']['matrix']==old['prediction']['bsm_component_covariance']['matrix']
    assert r['joint_covariance_audit']['matrix_modified'] is False
    assert r['joint_covariance_audit']['sm_or_theory_covariance_inferred'] is False
    assert r['joint_covariance_audit']['covariance_scope']=='supplied_BSM_numerator_denominator_only'
    assert r['goodness_of_fit']['degrees_of_freedom']==2
    assert r['fit'] is None and r['inference'] is None and r['physics_validated'] is False


def test_finite_difference_numerator_and_denominator_derivatives():
    d=bsm_document();model=ratio.prepare(d,task(.7));j=model['jacobian'][:,4:]
    # Perturb each actual component separately: all cross-mode coordinates matter.
    eps=1e-5
    for k in range(4):
        name=['bsm_numerator','bsm_denominator'][k//2];i=k%2
        plus,minus=deepcopy(d),deepcopy(d)
        plus['prediction'][name]['values'][i]+=eps
        minus['prediction'][name]['values'][i]-=eps
        finite=(ratio.prepare(plus,task(.7))['prediction']-ratio.prepare(minus,task(.7))['prediction'])/(2*eps)
        assert finite==pytest.approx(j[:,k],rel=1e-9,abs=1e-10)


def test_mu0_retains_literal_sm_and_source_matrix_without_padded_unknowns():
    d=bsm_document();r=ratio.diagnose(d,task(0))
    assert r['prediction']['values']==[3.,3.]
    assert r['prediction_covariance']==[[0.,0.],[0.,0.]]
    assert len(r['prediction']['source_contract']['bsm_component_covariance']['matrix'])==4
    assert 'joint_component_covariance' not in r['prediction']['source_contract']
    assert 'unknown SM/theory covariance' in r['prediction']['scope']
    assert r['applicability']['theory_covariance']=='not supplied'


def test_cross_numden_terms_cannot_be_replaced_by_independent_marginals():
    d=bsm_document();full=ratio.prepare(d,task(.7))['prediction_covariance']
    q=d['prediction']['bsm_component_covariance']
    for i in range(2):
        for j in range(2,4):q['matrix'][i][j]=q['matrix'][j][i]=0.
    dropped=ratio.prepare(d,task(.7))['prediction_covariance']
    assert np.max(np.abs(full-dropped))>1e-4
    d=bsm_document();d['prediction']['bsm_denominator']['values']=[0.,0.]
    assert np.max(np.abs(full-ratio.prepare(d,task(.7))['prediction_covariance']))>1e-4


def test_common_component_unit_scaling_preserves_ratio_and_covariance():
    d=bsm_document();ordinary=ratio.prepare(d,task(.7));scale=7.5
    for name in ['sm_numerator','sm_denominator','bsm_numerator','bsm_denominator']:
        p=d['prediction'][name];p['values']=[v*scale for v in p['values']]
        p['units']=['scaled/GeV','scaled/rad']
    q=d['prediction']['bsm_component_covariance'];q['coordinate_units']=['scaled/GeV','scaled/rad']*2
    q['matrix']=[[v*scale**2 for v in row] for row in q['matrix']]
    scaled=ratio.prepare(d,task(.7))
    assert scaled['prediction']==pytest.approx(ordinary['prediction'])
    assert scaled['prediction_covariance']==pytest.approx(ordinary['prediction_covariance'])
    assert scaled['jacobian']*scale==pytest.approx(ordinary['jacobian'])


def test_signed_interference_keeps_full_denominator_and_no_clipping():
    d=bsm_document();p=d['prediction'];p['coefficient_convention']='signed_interference'
    p['signal_strength_domain']=[-1.,2.];p['bsm_numerator']['values']=[-1.,.2];p['bsm_denominator']['values']=[-.25,.1]
    r=ratio.diagnose(d,task(2));assert r['prediction']['values']==pytest.approx([4/1.5,3.4/1.2])
    assert r['prediction']['source_contract']['bsm_denominator']['values']==[-.25,.1]
    assert r['joint_covariance_audit']['sm_treatment']=='conditional_fixed_central_no_theory_covariance'


@pytest.mark.parametrize('defect',['extra-key','missing-sm-treatment','inferred-theory','missing-coordinate','duplicate-coordinate','permuted-coordinate','wrong-unit','short-matrix','short-row','asymmetric','indefinite','boolean','nonfinite','independence','method','empty-source','both-covariances'])
def test_bsm_covariance_closed_contract_refusals(defect):
    d=bsm_document();q=d['prediction']['bsm_component_covariance']
    if defect=='extra-key':q['unknown']=1
    elif defect=='missing-sm-treatment':q.pop('sm_treatment')
    elif defect=='inferred-theory':q['sm_treatment']='unknown_theory_is_zero'
    elif defect=='missing-coordinate':q['coordinate_ids'].pop()
    elif defect=='duplicate-coordinate':q['coordinate_ids'][1]=q['coordinate_ids'][0]
    elif defect=='permuted-coordinate':q['coordinate_ids'].reverse()
    elif defect=='wrong-unit':q['coordinate_units'][2]='1'
    elif defect=='short-matrix':q['matrix'].pop()
    elif defect=='short-row':q['matrix'][0].pop()
    elif defect=='asymmetric':q['matrix'][0][1]+=1e-15
    elif defect=='indefinite':q['matrix'][0][0]=-1.
    elif defect=='boolean':q['matrix'][0][0]=True
    elif defect=='nonfinite':q['matrix'][0][0]=float('nan')
    elif defect=='independence':q['experimental_independence']='inferred_independent'
    elif defect=='method':q['method']='marginal_errors'
    elif defect=='empty-source':q['source']=''
    else:
        p=deepcopy(q);p.pop('sm_treatment');d['prediction']['joint_component_covariance']=p
    with pytest.raises(ValueError):ratio.prepare(d,task())


def test_real_file_graph_and_adapter_no_overwrite(tmp_path):
    root=tmp_path.resolve();d=bsm_document();source=root/'same-events.json';source.write_text('{"supplied_groups":true}\n')
    d['grounding']=[{'path':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]
    p=root/'input.json';p.write_text(json.dumps(d));t=task(.7)
    assert ratio.inputs(t,root)==[p,source]
    out=root/'result';r=ratio.run(t,root,out)
    written=json.loads((out/'ratio-diagnostic.json').read_text())
    assert written==r and written['joint_covariance_audit']['sm_or_theory_covariance_inferred'] is False
    before=(out/'ratio-diagnostic.json').read_bytes()
    with pytest.raises(FileExistsError):ratio.run(t,root,out)
    assert (out/'ratio-diagnostic.json').read_bytes()==before
    source.write_text('{"supplied_groups":false}\n')
    with pytest.raises(ValueError,match='grounding bytes differ'):ratio.inputs(t,root)


def test_actual_worker_route_keeps_conditional_covariance_and_checkin2(tmp_path,monkeypatch):
    from ravel.physics import science_worker
    from ravel.workflow import science
    from ravel.workflow.state_io import atomic_json,read_json
    root=tmp_path.resolve();atomic_json(root/'input.json',bsm_document());rd=root/'run';rd.mkdir()
    spec={'schema_version':2,'mode':'ratio-measurement','task':task(.7),'assumptions':['Synthetic supplied covariance, conditional fixed SM; no physical model or physics acceptance.']}
    assert science.adapter(spec) is ratio
    proposal={'base_dir':str(root),'attempt':1,'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}}
    # Only authority/spec are mocked; actual dispatcher, adapter, rendering and IO run.
    monkeypatch.setattr(science_worker,'verify_worker',lambda _:proposal)
    monkeypatch.setattr(science_worker,'execution_spec',lambda _:spec)
    assert science_worker.main([str(rd),'--attempt','1'])==0
    out=rd/'outputs/attempt-1';r=read_json(out/'result.json')
    assert r==read_json(out/'ratio-measurement/ratio-diagnostic.json')
    assert r['status']=='passed' and r['physics_validated'] is False
    assert read_json(out/'checkin2.json')['sections']['waypoint']['status']=='passed'
    assert read_json(out/'verification.json')['expert_review'] is False
    before={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])
    assert before=={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
