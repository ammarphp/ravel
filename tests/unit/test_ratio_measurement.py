"""Full ratio domains, joint uncertainty and independent Gaussian controls."""
import json
from copy import deepcopy
import pytest
np=pytest.importorskip('numpy')
pytest.importorskip('scipy')
from ravel.physics import ratio_measurement as ratio

def document():
 ids=['a','b']
 def comp(v):return {'bin_ids':ids[:],'values':v,'units':['fb/GeV','fb/rad']}
 return {'schema_version':1,'analysis_id':'synthetic-joint-ratio-control','basis':[{'id':'a','observable':'ptmiss','axis':{'name':'ptmiss','unit':'GeV'},'low':[200.],'high':[250.]},{'id':'b','observable':'dphi','axis':{'name':'dphi','unit':'rad'},'low':[0.],'high':[.5]}], 'data':{'bin_ids':ids[:],'values':[4.,2.],'unit':'1'},'experimental_covariance':{'bin_ids':ids[:],'matrix':[[.25,.1],[.1,1.]],'unit':'(1)^2'},'prediction':{'kind':'numerator_denominator','sm_numerator':comp([6.,3.]),'sm_denominator':comp([2.,1.]),'bsm_numerator':comp([2.,1.]),'bsm_denominator':comp([1.,2.]),'coefficient_convention':'positive_additive','signal_strength_domain':[0.,2.],'baseline_convention':'literal_num_den','published_sm_ratio':{'bin_ids':ids[:],'values':[3.01,2.99],'unit':'1'}}, 'applicability':{'scope':'conditional_fixed_prediction_diagnostic','prompt_lepton_met_control_contamination':'unresolved synthetic control','dilepton_efficiency_assumption':'requires source/model review','theory_covariance':'not supplied'},'sources':{'measurement':'synthetic','covariance':'supplied full cross-observable matrix','prediction':'synthetic complete numerator and denominator','approximation':'fixed Gaussian only'}}
def task(mu=1):return {'schema_version':1,'input':'input.json','signal_strength':mu}
def joint(d,matrix):
 ids=d['data']['bin_ids'];units=d['prediction']['sm_numerator']['units']
 d['prediction']['joint_component_covariance']={'coordinate_ids':[g+'/'+i for g in ['sm_numerator','sm_denominator','bsm_numerator','bsm_denominator'] for i in ids],'coordinate_units':units*4,'matrix':np.asarray(matrix).tolist(),'source':'explicit full synthetic joint covariance','method':'first_order_delta_method','experimental_independence':'declared_independent'}

def test_two_sided_ratio_fixed_dof_and_cross_distribution_covariance():
 d=document();r=ratio.diagnose(d,task());want=[8/3,4/3]
 assert r['prediction']['values']==pytest.approx(want)
 assert r['normalization']=='absolute_ratio_not_unit_area'
 residual=[4-want[0],2-want[1]];det=.25-.1**2
 direct=(residual[0]**2-2*.1*residual[0]*residual[1]+.25*residual[1]**2)/det
 assert r['goodness_of_fit']['chi2']==pytest.approx(direct)
 assert r['goodness_of_fit']['degrees_of_freedom']==2 and r['fit'] is None and r['inference'] is None and r['physics_validated'] is False
 assert r['input_experimental_covariance']==d['experimental_covariance']['matrix']
 assert r['prediction']['baseline']['published_expected_ratio']==[3.01,2.99]
 assert r['prediction']['baseline']['literal_num_den_ratio']==[3.,3.]
 assert r['prediction']['baseline']['published_rounding_residual']==pytest.approx([-.01,.01])


def test_signed_convention_preserves_negative_contributions_without_clipping():
 d=document();p=d['prediction'];p['coefficient_convention']='signed_interference';p['signal_strength_domain']=[-1,2]
 p['bsm_numerator']['values']=[-1.,.2];p['bsm_denominator']['values']=[-.25,.1]
 r=ratio.diagnose(d,task(2));assert r['prediction']['values']==pytest.approx([4/1.5,3.4/1.2])
 assert r['prediction']['source_contract']['bsm_numerator']['values']==[-1,.2]
 assert len(r['prediction']['domain_endpoint_audit'])==2


def test_heldout_large_common_scale_retains_ratio_and_denominator_derivatives():
 d=document();ordinary=ratio.prepare(d,task());factor=1e200
 for name in ['sm_numerator','sm_denominator','bsm_numerator','bsm_denominator']:
  d['prediction'][name]['values']=[v*factor for v in d['prediction'][name]['values']]
 huge=ratio.prepare(d,task())
 assert huge['prediction']==pytest.approx(ordinary['prediction'])
 assert huge['jacobian']*factor==pytest.approx(ordinary['jacobian'])


def test_finite_ratio_with_unrepresentable_jacobian_refuses():
 d=document()
 for name in ['sm_numerator','sm_denominator','bsm_numerator','bsm_denominator']:
  d['prediction'][name]['values']=[v*1e-310 for v in d['prediction'][name]['values']]
 with np.errstate(over='ignore'):
  with pytest.raises(ValueError,match='Jacobian overflows'):ratio.prepare(d,task())


@pytest.mark.parametrize('mutate,message',[(lambda d:d['prediction']['bsm_numerator'].update(values=[-1,1]),'positive-additive'),(lambda d:d['prediction']['bsm_denominator'].update(values=[-1,2]),'positive-additive'),(lambda d:d['prediction'].update(coefficient_convention='unspecified'),'convention'),(lambda d:d['prediction']['sm_denominator'].update(values=[0,1]),'SM numerator'),(lambda d:d['prediction']['bsm_numerator'].update(units=['fb','fb/rad']),'units differ')])
def test_model_domain_and_units_refuse(mutate,message):
 d=document();mutate(d)
 with pytest.raises(ValueError,match=message):ratio.prepare(d,task())


def test_invalid_denominator_at_domain_endpoint_refuses_even_if_tested_point_is_valid():
 d=document();d['prediction']['coefficient_convention']='signed_interference';d['prediction']['bsm_denominator']['values']=[-1,0]
 with pytest.raises(ValueError,match='over declared domain'):ratio.prepare(d,task(.1))


def test_invalid_numerator_at_domain_endpoint_refuses():
 d=document();d['prediction']['coefficient_convention']='signed_interference';d['prediction']['bsm_numerator']['values']=[-4,0]
 with pytest.raises(ValueError,match='over declared domain'):ratio.prepare(d,task(.1))


def test_supplied_joint_covariance_preserves_all_correlations_and_delta_method():
 d=document();v=np.array([.2,.4,.1,-.1,.3,-.2,.1,.2]);V=np.outer(v,v);joint(d,V)
 r=ratio.diagnose(d,task());J=np.asarray(r['delta_method_jacobian'])
 derivative=J@v;expected=np.outer(derivative,derivative)
 assert np.asarray(r['prediction_covariance'])==pytest.approx(expected)
 assert np.asarray(r['combined_covariance'])==pytest.approx(np.asarray(d['experimental_covariance']['matrix'])+expected)
 assert r['prediction']['source_contract']['joint_component_covariance']['matrix']==V.tolist()
 assert r['joint_covariance_audit']['matrix_modified'] is False
 # Held-out source derivatives through actual ratio evaluation, no helper reuse.
 eps=1e-5
 plus=deepcopy(d);minus=deepcopy(d)
 for g,name in enumerate(['sm_numerator','sm_denominator','bsm_numerator','bsm_denominator']):
  a=np.asarray(d['prediction'][name]['values']);plus['prediction'][name]['values']=(a+eps*v[g*2:g*2+2]).tolist();minus['prediction'][name]['values']=(a-eps*v[g*2:g*2+2]).tolist()
 finite=(ratio.prepare(plus,task())['prediction']-ratio.prepare(minus,task())['prediction'])/(2*eps)
 assert finite==pytest.approx(derivative,rel=1e-8,abs=1e-10)


def test_correlated_common_scaling_cancels_in_ratio_uncertainty():
 d=document();p=d['prediction'];v=np.array(p['sm_numerator']['values']+p['sm_denominator']['values']+p['bsm_numerator']['values']+p['bsm_denominator']['values'])
 joint(d,np.outer(v,v));r=ratio.diagnose(d,task())
 assert np.max(np.abs(r['prediction_covariance']))<1e-13
 assert r['input_experimental_covariance']==d['experimental_covariance']['matrix']


@pytest.mark.parametrize('defect',['missing-coordinate','wrong-unit','asymmetric','indefinite','boolean','independence','method'])
def test_joint_uncertainty_contract_refuses_adverse_inputs(defect):
 d=document();joint(d,np.eye(8));q=d['prediction']['joint_component_covariance']
 if defect=='missing-coordinate':q['coordinate_ids'].pop()
 elif defect=='wrong-unit':q['coordinate_units'][0]='fb'
 elif defect=='asymmetric':q['matrix'][0][1]=.1
 elif defect=='indefinite':q['matrix'][0][0]=-1
 elif defect=='boolean':q['matrix'][0][0]=True
 elif defect=='independence':q['experimental_independence']='unknown'
 else:q['method']='unknown'
 with pytest.raises(ValueError):ratio.prepare(d,task())


def test_no_prediction_covariance_created_from_absent_marginal_errors():
 r=ratio.diagnose(document(),task());assert r['prediction_covariance']==[[0.,0.],[0.,0.]]
 assert 'no covariance inferred' in r['prediction']['scope']


@pytest.mark.parametrize('bad_prediction',[None,[],False])
def test_prediction_requires_an_explicit_object(bad_prediction):
 d=document();d['prediction']=bad_prediction
 with pytest.raises(ValueError,match='object'):ratio.prepare(d,task())


def test_fixed_published_ratio_baseline_keeps_literal_values_and_all_dof():
 d=document();d['prediction']={'kind':'fixed_ratio','ratio':{'bin_ids':['a','b'],'values':[3.01,2.99],'unit':'1'},'baseline_convention':'literal_published_ratio'}
 r=ratio.diagnose(d,task(0));assert r['prediction']['values']==[3.01,2.99];assert r['goodness_of_fit']['degrees_of_freedom']==2
 with pytest.raises(ValueError,match='mu0'):ratio.prepare(d,task(1))


def fixed_prediction(d,matrix=None):
 d['prediction']={'kind':'fixed_ratio','ratio':{'bin_ids':['a','b'],'values':[8/3,4/3],'unit':'1'},'baseline_convention':'supplied_derived_ratio'}
 if matrix is not None:
  d['prediction']['prediction_covariance']={'bin_ids':['b','a'],'matrix':np.asarray(matrix)[np.ix_([1,0],[1,0])].tolist(),'unit':'(1)^2','source':'Explicit nominal subset of complete derived output covariance','method':'first_order_delta_method','experimental_independence':'declared_independent'}


def test_fixed_output_covariance_seam_keeps_exact_cross_bin_matrix_and_basis():
 d=document();V=np.array([[.16,-.08],[-.08,.04]])
 fixed_prediction(d,V);r=ratio.diagnose(d,task(0))
 assert r['prediction_covariance']==V.tolist()
 assert r['prediction']['source_contract']['prediction_covariance']['bin_ids']==['b','a']
 total=np.array([[.41,.02],[.02,1.04]]);residual=np.array([4-8/3,2-4/3])
 direct=(total[1,1]*residual[0]**2-2*total[0,1]*residual[0]*residual[1]+total[0,0]*residual[1]**2)/(total[0,0]*total[1,1]-total[0,1]**2)
 assert r['goodness_of_fit']['chi2']==pytest.approx(direct)
 assert r['fixed_prediction_covariance_audit']['matrix_modified'] is False
 assert r['delta_method_jacobian'] is None  # Producer's derivation stays source-bound, not fabricated here.


@pytest.mark.parametrize('defect',['missing-bin','duplicate-bin','short-row','asymmetric','indefinite','boolean','unit','independence','method','empty-source'])
def test_fixed_output_covariance_adverse_contracts_refuse(defect):
 d=document();fixed_prediction(d,np.eye(2));q=d['prediction']['prediction_covariance']
 if defect=='missing-bin':q['bin_ids'].pop()
 elif defect=='duplicate-bin':q['bin_ids']=['a','a']
 elif defect=='short-row':q['matrix'][0].pop()
 elif defect=='asymmetric':q['matrix'][0][1]=1e-14
 elif defect=='indefinite':q['matrix'][0][0]=-1
 elif defect=='boolean':q['matrix'][0][0]=True
 elif defect=='unit':q['unit']='fb^2'
 elif defect=='independence':q['experimental_independence']='unknown'
 elif defect=='method':q['method']='marginal_error_heuristic'
 else:q['source']=''
 with pytest.raises(ValueError):ratio.prepare(d,task(0))


def test_experimental_asymmetry_singularity_and_basis_population_refuse():
 d=document();d['experimental_covariance']['matrix'][0][1]+=.0000000000001
 with pytest.raises(ValueError,match='exactly symmetric'):ratio.prepare(d,task())
 d=document();d['experimental_covariance']['matrix']=[[1,1],[1,1]]
 with pytest.raises(ValueError,match='singular'):ratio.prepare(d,task())
 d=document();d['basis'][1]['id']='a'
 with pytest.raises(ValueError,match='repeats'):ratio.prepare(d,task())


def test_input_source_pins_and_no_overwrite(tmp_path):
 d=document();source=tmp_path/'source.yaml';source.write_text('preserved source bytes\n')
 import hashlib
 d['grounding']=[{'path':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]
 inp=tmp_path/'input.json';inp.write_text(json.dumps(d));t=task();t['input']=inp.name
 assert ratio.inputs(t,tmp_path)==[inp,source]
 out=tmp_path/'out';ratio.run(t,tmp_path,out)
 with pytest.raises(FileExistsError):ratio.run(t,tmp_path,out)
 source.write_text('changed source')
 with pytest.raises(ValueError,match='grounding bytes differ'):ratio.inputs(t,tmp_path)
