"""Repaired behavior for retained e904 findings; synthetic controls only."""
import copy
import json
import math
from pathlib import Path
import pytest
from ravel.physics import detector_response as dr,marked_response as mr
from test_detector_response import particle,geometry,write,execute,llp,fixed,support,refresh

@pytest.mark.parametrize('coordinate',[1e6,1e8,1e12])
def test_far_inward_unit_cylinder_preserves_positive_intersection_and_probability(coordinate):
 p=particle(momentum=(-1.,0.,0.),origin=(coordinate,0.,0.),mass=1.)
 c={'id':'unit','r_min':0.,'r_max':1.,'z_min':-1.,'z_max':1.};g={**geometry(),'cells':[c]}
 assert dr.shell_intervals(p,c)[0]==[(coordinate-1.,coordinate+1.)]
 got=dr.decay_probabilities(p,g,coordinate)
 expected=math.exp(-(coordinate-1.)/coordinate)*(-math.expm1(-2./coordinate))
 assert got['unit']>0. and got['unit']==pytest.approx(expected,rel=2e-15,abs=0.)
 assert got['outside']==1.-got['unit']

@pytest.mark.parametrize('coordinate',[1e8,1e12])
def test_far_shell_retains_both_pieces_and_complete_longitudinal_clipping(coordinate):
 p=particle(momentum=(-1.,0.,0.),origin=(coordinate,0.,0.),mass=1.)
 c={'id':'shell','r_min':1.,'r_max':2.,'z_min':-1.,'z_max':1.}
 assert dr.shell_intervals(p,c)[0]==[(coordinate-2.,coordinate-1.),(coordinate+1.,coordinate+2.)]

@pytest.mark.parametrize('y,intersects',[(0.,True),(.5,True),(1.,False),(math.nextafter(1.,0.),True),(math.nextafter(1.,2.),False)])
def test_exact_supplied_line_tangent_sign_is_not_guessed_by_rounded_discriminant(y,intersects):
 # Modest origin keeps tiny near-tangent positive chord endpoints resolvable.
 answer=dr._inside_radius(2.,y,-1.,0.,1.)
 assert bool(answer)==intersects
 if intersects:assert answer[0][0]<answer[0][1]

@pytest.mark.parametrize('coordinate',[1e17,1e100])
def test_unresolvable_positive_intersection_refuses_without_fabricated_zero(coordinate):
 with pytest.raises(ValueError,match='not distinguishable'):
  dr._inside_radius(coordinate,0.,-1.,0.,1.)

@pytest.mark.parametrize('origin,direction,expected',[(0.,1.,[(0.,1.)]),(1.,-1.,[(0.,2.)]),(1.,1.,[]),(-1.,1.,[(0.,2.)])])
def test_zero_b_and_zero_c_stable_root_branches(origin,direction,expected):
 assert dr._inside_radius(origin,0.,direction,0.,1.)==expected


@pytest.mark.parametrize('x,y,ux,uy',[(0.,1e8,0.,-1.),(-1e8,0.,1.,0.),(0.,-1e8,0.,1.)])
def test_far_intersection_survives_exact_quarter_turns(x,y,ux,uy):
 assert dr._inside_radius(x,y,ux,uy,1.)==[(99999999.,100000001.)]


def test_radial_interval_is_still_intersected_with_longitudinal_window():
 p=particle(momentum=(-1.,0.,1.),origin=(3.,0.,-3.),mass=1.)
 cell={'id':'unit','r_min':0.,'r_max':1.,'z_min':-.5,'z_max':.5}
 got=dr.shell_intervals(p,cell)[0]
 assert len(got)==1 and got[0]==pytest.approx((2.5*math.sqrt(2.),3.5*math.sqrt(2.)))


def normalization_fixture():
 d={'axes':[{'name':'a','knots':[0,1]}],'reference_point':{'a':0},'anchors':[{'point':[0]},{'point':[1]}],
    'weight_name':'nominal','normalization':{'scale':1.,'denominator':'fixed','fixed_denominator':2.,'meaning':'synthetic explicit normalization'}}
 rows=[[{'event_id':'selected','group_id':'g1','weights':{'nominal':1.},'allocation':[1.,0.]},
        {'event_id':'rejected','group_id':'g2','weights':{'nominal':1.},'allocation':[0.,1.]}] for _ in range(2)]
 support={'schema_version':1,'sampling_law':'iid_fixed_mark_categories','support_complete':True,'independence':'iid_groups_within_one_fixed_N_stream',
  'source':'synthetic complete source-declared support','calibration':'no physical calibration','fitted_destinations':['S'],'categories':[
  {'id':'selected','group_ids':['g1'],'weight':1.,'denominator_mark':1.,'initial':.25,'allocation_at_anchors':[[1.,0.],[1.,0.]]},
  {'id':'rejected','group_ids':['g2'],'weight':1.,'denominator_mark':1.,'initial':.25,'allocation_at_anchors':[[0.,1.],[0.,1.]]},
  {'id':'unseen','group_ids':[],'weight':1.,'denominator_mark':1.,'initial':.5,'allocation_at_anchors':[[1.,0.],[1.,0.]]}]}
 return d,rows,support

@pytest.mark.parametrize('mode',['fixed','sum_original_weights'])
def test_retained_unseen_wrong_denominator_refuses_before_emitting_likelihood_artifacts(tmp_path,mode):
 d,rows,s=normalization_fixture();d['normalization'].update(denominator=mode,fixed_denominator=2. if mode=='fixed' else None)
 s['categories'][-1]['denominator_mark']=2.
 b=dr.summarize(d,['S','__rejected__'],rows);out=tmp_path/'out';out.mkdir();(out/'source-request.json').write_bytes(dr._bytes(d))
 with pytest.raises(ValueError,match='every support category denominator mark'):
  dr._handoff(d,b,dr._bytes(s),out)
 assert not (out/'marked-response.json').exists() and not (out/'mc-model.json').exists()

@pytest.mark.parametrize('mode',['fixed','sum_original_weights'])
def test_corrected_complete_support_initial_mean_matches_declared_normalization(tmp_path,mode):
 d,rows,s=normalization_fixture();d['normalization'].update(denominator=mode,fixed_denominator=2. if mode=='fixed' else None)
 b=dr.summarize(d,['S','__rejected__'],rows);out=tmp_path/'out';out.mkdir();(out/'source-request.json').write_bytes(dr._bytes(d))
 h=dr._handoff(d,b,dr._bytes(s),out);law=json.loads((out/'marked-response.json').read_bytes())
 assert mr.evaluate(law,{'selected':.25,'rejected':.25,'unseen':.5},{'a':0})['values']==[.75,.25]
 assert not h['scientific_sampling_and_calibration_qualified'] and not h['likelihood_created']
 assert law['denominator_marks']==[1.,1.,1.]

@pytest.mark.parametrize('mode,den,expected',[('fixed',1.,1.25),('sum_original_weights',2.,5./6)])
def test_unseen_distinct_weight_uses_fixed_one_or_exact_weight_law(tmp_path,mode,den,expected):
 d,rows,s=normalization_fixture();d['normalization'].update(denominator=mode,fixed_denominator=2. if mode=='fixed' else None)
 s['categories'][-1].update(weight=2.,denominator_mark=den)
 b=dr.summarize(d,['S','__rejected__'],rows);out=tmp_path/'out';out.mkdir();(out/'source-request.json').write_bytes(dr._bytes(d))
 dr._handoff(d,b,dr._bytes(s),out);law=json.loads((out/'marked-response.json').read_bytes())
 assert mr.evaluate(law,{'selected':.25,'rejected':.25,'unseen':.5},{'a':0})['values'][0]==pytest.approx(expected)


@pytest.mark.parametrize('mode,weight',[('fixed',0.),('fixed',-.25),('sum_original_weights',0.),('sum_original_weights',-.25)])
def test_complete_support_zero_and_signed_unseen_marks_obey_same_normalization(tmp_path,mode,weight):
 d,rows,s=normalization_fixture();d['normalization'].update(denominator=mode,fixed_denominator=2. if mode=='fixed' else None)
 s['categories'][-1].update(weight=weight,denominator_mark=weight if mode=='sum_original_weights' else 1.)
 b=dr.summarize(d,['S','__rejected__'],rows);out=tmp_path/'out';out.mkdir();(out/'source-request.json').write_bytes(dr._bytes(d))
 dr._handoff(d,b,dr._bytes(s),out);law=json.loads((out/'marked-response.json').read_bytes())
 numerator=.25+.5*weight
 expected=numerator/(.5+.5*weight) if mode=='sum_original_weights' else numerator
 assert mr.evaluate(law,{'selected':.25,'rejected':.25,'unseen':.5},{'a':0})['values'][0]==pytest.approx(expected)


def test_ordinary_llp_adapter_retains_far_cylinder_response_without_qualifying_calibration(tmp_path):
 d=llp(tmp_path,pair=False)
 data=json.loads(Path(d['events']['path']).read_bytes())
 data['events'][0]['llps']=[particle(momentum=(-1.,0.,0.),origin=(1e8,0.,0.),mass=1.)]
 refresh(d['events'],data)
 d['geometry']['cells']=[{'id':'unit','r_min':0.,'r_max':1.,'z_min':-1.,'z_max':1.}]
 d['axes'][0]['knots']=[1e8,2e8];d['reference_point']={'ctau_mm':1e8}
 for anchor,ctau in zip(d['anchors'],(1e8,2e8)):
  anchor.update(point=[ctau],ctau_mm=ctau)
 table=json.loads(Path(d['joint_response']['path']).read_bytes())
 for anchor,ctau in zip(table['anchors'],(1e8,2e8)):
  anchor['point']=[ctau]
  for state in anchor['contexts'][0]['states']:
   state['cells']=['unit' if name=='inner' else name for name in state['cells']]
 refresh(d['joint_response'],table)
 details,out=execute(tmp_path,d)
 for index,ctau in enumerate((1e8,2e8)):
  probability=math.exp(-(1e8-1)/ctau)*(-math.expm1(-2/ctau))
  assert details['weights']['nominal']['normalized_values'][2*index]==pytest.approx(2*.6*probability,rel=2e-15,abs=0.)
  assert details['weights']['nominal']['normalized_values'][2*index]>0.
 assert details['events']==1 and not details['likelihood_inferred']
 assert not details['stochastic_detector_sampling']
 assert json.loads((out/'complete-response.json').read_bytes())['events']==1
 assert not (out/'joint-mark-ledger.json').exists()  # no complete category sampling law supplied


@pytest.mark.parametrize('mode',['fixed','sum_original_weights'])
def test_ordinary_adapter_refuses_unseen_wrong_denominator_before_mc_delivery(tmp_path,mode):
 d=fixed(tmp_path);s=support(d)
 d['normalization'].update(denominator=mode,fixed_denominator=2. if mode=='fixed' else None)
 if mode=='sum_original_weights':
  s['categories'][2]['denominator_mark']=0.
 s['categories'][-1]['denominator_mark']=2.
 d['category_support']=write(tmp_path,'support.json',s)
 with pytest.raises(ValueError,match='every support category denominator mark'):
  execute(tmp_path,d)
 out=tmp_path/'out/response-construction'
 assert not (tmp_path/'out/domain-result.json').exists()
 assert not (out/'marked-response.json').exists() and not (out/'mc-model.json').exists()
