import copy
import hashlib
import json
import math
from pathlib import Path
import pytest

from ravel.physics import detector_response as dr, domain_adapters as da, marked_response as mr, marked_response_provider as mp, mc_auxiliary as mc
from ravel.workflow import science


def write(base, name, doc):
    path = base/name; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, allow_nan=False))
    return {'id': name.replace('/','-'), 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'reference': 'Explicit constructed engineering fixture, not detector calibration'}


def refresh(pin, doc):
    p=Path(pin['path']);p.write_text(json.dumps(doc,allow_nan=False));pin['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()


def request(base, doc):
    p=write(base,'request.json',doc)
    return {'request_file':p['path']}


def empty_event(eid='e1', gid='g1', weight=1., met=10):
    return {'event_id':eid,'group_id':gid,'weights':{'nominal':weight,'twice':weight*2},'objects':{'electron':[],'muon':[],'jet':[]},'met':{'pt':met,'phi':0.}}


def fixed(base, exclusive=True):
    c={'schema_version':1,'level':'reconstructed','source':'pure selection control','energy_unit':'GeV','flags':{'electron':{},'muon':{},'jet':{}},'response_evidence':[],'weight_names':['nominal','twice']}
    cuts={x:{'pt':0.,'eta':5.,'id':0} for x in ('electron','muon','jet')}
    s={'name':'fixed','objects':cuts,'signal':copy.deepcopy(cuts),'overlap_removal':[],'regions':[{'name':'SR','cuts':[{'var':'MET','op':'>=','val':5}]}]}
    if not exclusive:s['regions'].append({'name':'overlap','cuts':[{'var':'MET','op':'>','val':8}]})
    e0=[empty_event(),empty_event('e2','g2',1,0),empty_event('e3','g3',0,0)]
    e1=copy.deepcopy(e0);e1[0]['met']['pt']=0;e1[1]['met']['pt']=10
    d={'schema_version':1,'operation':'fixed_event_migrations','axes':[{'name':'shift','knots':[0,1]}],'reference_point':{'shift':0},'weight_name':'nominal',
       'normalization':{'scale':2.,'denominator':'fixed','fixed_denominator':2.,'meaning':'explicit constant control scale, not cross section'},
       'source_pins':[write(base,'origin.txt',{'scope':'source identity only'})],
       'object_contract':write(base,'objects.json',c),'selection':write(base,'selection.json',s),
       'anchors':[{'point':[0],'events':write(base,'events0.json',e0)},{'point':[1],'events':write(base,'events1.json',e1)}]}
    return d


def support(d):
    return {'schema_version':1,'sampling_law':'iid_fixed_mark_categories','support_complete':True,'independence':'iid_groups_within_one_fixed_N_stream',
      'source':'Complete synthetic support declaration; includes never-observed positive category','calibration':'No physical calibration, engineering only',
      'fitted_destinations':['SR'],'categories':[
      {'id':'a','group_ids':['g1'],'weight':1.,'denominator_mark':1.,'initial':.3,'allocation_at_anchors':[[1.,0.],[0.,1.]]},
      {'id':'b','group_ids':['g2'],'weight':1.,'denominator_mark':1.,'initial':.3,'allocation_at_anchors':[[0.,1.],[1.,0.]]},
      {'id':'zero','group_ids':['g3'],'weight':0.,'denominator_mark':1.,'initial':.2,'allocation_at_anchors':[[0.,1.],[0.,1.]]},
      {'id':'unobserved','group_ids':[],'weight':1.,'denominator_mark':1.,'initial':.2,'allocation_at_anchors':[[1.,0.],[1.,0.]]}]}


def execute(base,d):
    task=request(base,d);spec={'domain':'detector-response','config':task}
    assert science.adapter({'mode':'domain','task':spec}) is da
    da.validate(spec)
    pins=da.inputs(spec,base)
    result=da.run(spec,base,base/'out')
    assert not result['physics_validated'] and result['status']=='passed'
    assert set(Path(x['path']) for x in result['inputs'])==set(pins)
    assert json.loads((base/'out/domain-result.json').read_text())==result
    return result['details'],base/'out/response-construction'


def test_actual_selection_complete_census_migration_and_all_weight_cross_covariance(tmp_path):
    d=fixed(tmp_path,exclusive=False);details,out=execute(tmp_path,d)
    assert details['events']==3 and details['group_ids']==['g1','g2','g3']
    assert details['anchor_records'][0][0]['allocation']==[1.,1.,0.]
    assert details['anchor_records'][0][2]['allocation']==[0.,0.,1.]
    assert len(details['migration_witnesses'])==2
    assert details['migration_witnesses'][1]['records'][0]['from_allocation']==[1,1,0]
    assert details['migration_witnesses'][1]['records'][0]['to_allocation']==[0,0,1]
    # Different anchors share groups. Same group migrates SR→reject, hence
    # cross-anchor SR0/reject1 moment equals 1, not independent templates.
    assert details['weights']['nominal']['full_numerator_denominator_Gram'][0][5]==1
    assert details['joint_weight_anchor_covariance'][0][6]==2
    assert details['joint_weight_anchor_covariance'][0][0]==1
    assert not details['likelihood_inferred']
    assert json.loads((out/'selections/anchor-0/decisions.json').read_text())[2]['weights']['nominal']==0


def test_signed_correlated_subevents_use_group_vector_before_gram(tmp_path):
    d=fixed(tmp_path)
    for a in d['anchors']:
        events=json.loads(Path(a['events']['path']).read_text());events[1]['group_id']='g1';events[1]['weights']={'nominal':-1.,'twice':-2.};events[1]['met']['pt']=10
        refresh(a['events'],events)
    details,_=execute(tmp_path,d)
    assert details['group_marks']['nominal']['g1']==[0.,0.,-1.,1.,0.]
    assert details['weights']['nominal']['full_numerator_denominator_Gram'][2][2]==1
    assert details['weights']['nominal']['numerators'][2]==-1
    assert details['weights']['nominal']['conditional_group_covariance'][2][3]==-1


def test_existing_marked_mc_consumers_accept_constructed_complete_support(tmp_path):
    d=fixed(tmp_path);d['category_support']=write(tmp_path,'support.json',support(d));details,out=execute(tmp_path,d)
    model=mc.MCAuxiliaryBlock({'input':str(out/'mc-model.json')})
    doc=model.document();law=mr.prepare(json.loads((out/'marked-response.json').read_text()))
    joint=json.loads((out/'joint-mark-ledger.json').read_text())
    assert mp.verify_group_marks(law,doc,joint)['observed_group_count']==3
    assert doc['classes'][-1]['observed']==0 and doc['classes'][-1]['initial']>0
    assert details['existing_marked_MC_handoff']['existing_provider_smoothness_compatible']
    latent={c['id']:c['initial'] for c in doc['classes']}
    assert mr.evaluate(law,latent,{'shift':.5})['values'][0]==pytest.approx(1.5)
    assert model.nominal(latent)['signal_expectation']==pytest.approx([1.5])
    assert math.isfinite(model.auxiliary_logpdf(latent))
    # Actual provider binding, not a parallel likelihood or source domain rewrite.
    src={'active_parameter_names':['response_shift'],'active_parameter_domains':{'response_shift':{'initial':0.,'fixed':False,'bounds':[0.,1.]}},'retained_auxiliaries':[]}
    binding=mp.bind_mark_law(law,{'axis_to_source':{'shift':'response_shift'},'source_data_id':'law','group_ledger_source_id':'ledger','sampling_independence':'supplied_source_and_new_MC_auxiliaries_independent'},src,doc,['response_shift'],['SR'])
    assert binding['added_auxiliary_factors']==0
    jet=mp.mark_jet(law,{'response_shift':.5},latent,['response_shift'],{'shift':'response_shift'},['SR'])
    assert jet['signal']==pytest.approx([1.5])


@pytest.mark.parametrize('bad',['drop-event','reorder','group','weight','weight-name','duplicate','source-hash','axis','extra-joint-anchor','reference','symlink','response-evidence','idbits','nonfinite-json','normalization','fractional-source','source-closure'])
def test_fixed_adverse_controls(tmp_path,bad):
    d=fixed(tmp_path);a=d['anchors'][1];events=json.loads(Path(a['events']['path']).read_text())
    if bad=='drop-event':events.pop()
    elif bad=='reorder':events.reverse()
    elif bad=='group':events[0]['group_id']='wrong'
    elif bad=='weight':events[0]['weights']['nominal']=3
    elif bad=='weight-name':events[0]['weights']['extra']=1
    elif bad=='duplicate':events[1]['event_id']=events[0]['event_id']
    elif bad=='source-hash':a['events']['sha256']='0'*64
    elif bad=='axis':d['axes'][0]['knots']=[1,0]
    elif bad=='extra-joint-anchor':d['anchors'].append(copy.deepcopy(a))
    elif bad=='reference':d['reference_point']={'shift':.5}
    elif bad=='symlink':
        p=Path(a['events']['path']);link=tmp_path/'linked.json';link.symlink_to(p);a['events']['path']=str(link)
    elif bad=='response-evidence':
        c=json.loads(Path(d['object_contract']['path']).read_text());c['response_evidence']=['unavailable'];refresh(d['object_contract'],c)
    elif bad=='idbits':events[0]['objects']['electron']=[{'pt':10.,'eta':0.,'phi':0.,'mass':0.,'charge':-1,'idbits':1}]
    elif bad=='nonfinite-json':Path(a['events']['path']).write_text('[NaN]');a['events']['sha256']=hashlib.sha256(Path(a['events']['path']).read_bytes()).hexdigest()
    elif bad=='normalization':d['normalization']['fixed_denominator']=0
    elif bad=='fractional-source':d['normalization']['scale']=True
    elif bad=='source-closure':d['source_pins']=[]
    if bad in {'drop-event','reorder','group','weight','weight-name','duplicate','idbits'}:refresh(a['events'],events)
    with pytest.raises((ValueError,KeyError)):execute(tmp_path,d)


@pytest.mark.parametrize('bad',['observed-only','wrong-category-marks','missing-zero','unknown-group','missing-group','duplicate-group','wrong-denominator','simplex','overlap'])
def test_complete_support_cannot_be_inferred_or_mismatched(tmp_path,bad):
    d=fixed(tmp_path,exclusive=bad!='overlap');s=support(d)
    if bad=='observed-only':s['support_complete']=False
    elif bad=='wrong-category-marks':s['categories'][0]['allocation_at_anchors'][1]=[1,0]
    elif bad=='missing-zero':s['categories'].pop(2)
    elif bad=='unknown-group':s['categories'][0]['group_ids']=['unknown']
    elif bad=='missing-group':s['categories'][0]['group_ids']=[]
    elif bad=='duplicate-group':s['categories'][1]['group_ids']=['g1']
    elif bad=='wrong-denominator':s['categories'][0]['denominator_mark']=2
    elif bad=='simplex':s['categories'][0]['initial']=.9
    d['category_support']=write(tmp_path,'support.json',s)
    with pytest.raises(ValueError):execute(tmp_path,d)


def particle(momentum=(100.,0.,0.),origin=(0.,0.,0.),mass=100.,charge=0):
    return {'id':'X','charge':charge,'mass_GeV':mass,'momentum_GeV':list(momentum),'origin_mm':list(origin)}


def geometry():
    return {'unit':'mm','trajectory':'neutral_straight_line','outside_id':'outside','cells':[{'id':'inner','r_min':10.,'r_max':20.,'z_min':-30.,'z_max':30.}]}


@pytest.mark.parametrize('case,expected',[('radial',math.exp(-1)-math.exp(-2)),('axis',0.),('rest-outside',0.),('rest-inside',1.),('displaced-in',1-math.exp(-.5)),('displaced-through',math.exp(-1)-math.exp(-2)+math.exp(-4)-math.exp(-5))])
def test_geometry_arbitrary_origin_and_proper_lab_conversion(case,expected):
    p=particle()
    if case=='axis':p['momentum_GeV']=[0,0,100]
    elif case=='rest-outside':p['momentum_GeV']=[0,0,0]
    elif case=='rest-inside':p['momentum_GeV']=[0,0,0];p['origin_mm']=[15,0,0]
    elif case=='displaced-in':p['origin_mm']=[15,0,0]
    elif case=='displaced-through':p['origin_mm']=[30,0,0];p['momentum_GeV']=[-100,0,0]
    probabilities=dr.decay_probabilities(p,geometry(),10.)
    assert probabilities['inner']==pytest.approx(expected,abs=1e-14)
    assert sum(probabilities.values())==pytest.approx(1,abs=1e-14)


def llp(base, pair=True):
    data={'schema_version':1,'momentum_unit':'GeV','position_unit':'mm','weight_names':['nominal'],'events':[{'event_id':'e','group_id':'g','weights':{'nominal':2.},'context_id':'joint','llps':[particle(),{**particle(),'id':'Y'}] if pair else [particle()]}]}
    count=2 if pair else 1;states=list(__import__('itertools').product(['inner','outside'],repeat=count))
    table={'schema_version':1,'scope':'joint_event_conditional_probabilities','conditioning':'explicit synthetic joint event efficiency; not a product of vertex efficiencies','destination_ids':['SR','__rejected__'],'source':'Source-declared constructed control',
      'anchors':[{'point':[v],'contexts':[{'id':'joint','llp_count':count,'llp_ids':['X','Y'] if pair else ['X'],'states':[{'cells':list(k),'allocation':[.6,.4] if all(x=='inner' for x in k) else [0.,1.]} for k in states]}]} for v in [10.,20.]]}
    d={'schema_version':1,'operation':'neutral_llp_joint_response','axes':[{'name':'ctau_mm','knots':[10.,20.]}],'reference_point':{'ctau_mm':10.},'weight_name':'nominal',
       'normalization':{'scale':1.,'denominator':'fixed','fixed_denominator':1.,'meaning':'supplied engineering weighted event normalization'},'source_pins':[write(base,'source.json',{'basis':'conditional truth production and joint calibration source'})],
       'events':write(base,'truth.json',data),'geometry':geometry(),'joint_response':write(base,'joint.json',table),
       'decay_assumption':'independent_exponential_proper_decays_conditional_on_supplied_truth','anchors':[{'point':[v],'ctau_mm':v} for v in [10.,20.]]}
    return d


def test_joint_llp_conditional_response_and_full_shared_anchor_covariance(tmp_path):
    d=llp(tmp_path);details,_=execute(tmp_path,d)
    p0=math.exp(-1)-math.exp(-2);p1=math.exp(-.5)-math.exp(-1)
    v0=2*.6*p0*p0;v1=2*.6*p1*p1
    assert details['weights']['nominal']['normalized_values'][0]==pytest.approx(v0)
    assert details['weights']['nominal']['normalized_values'][2]==pytest.approx(v1)
    assert details['weights']['nominal']['conditional_group_covariance'][0][2]==pytest.approx(v0*v1)
    assert details['flight_and_response'][0]['conditional_event_response'][0]==pytest.approx(.6*p0*p0)
    assert not details['stochastic_detector_sampling'] and not details['likelihood_inferred']


@pytest.mark.parametrize('bad',['vertex-marginal','missing-outside','missing-joint-state','nonexhaustive','duplicate-state','unknown-context','extra-context','charged','negative-mass','wrong-units','missing-origin','trajectory','overlap-cells','wrong-weight','wrong-dependence','bool-lifetime','role-order'])
def test_llp_legitimate_response_and_physics_boundaries(tmp_path,bad):
    d=llp(tmp_path);data=json.loads(Path(d['events']['path']).read_text());table=json.loads(Path(d['joint_response']['path']).read_text())
    if bad=='vertex-marginal':table['scope']='single_vertex_efficiency'
    elif bad=='missing-outside':table['destination_ids']=['SR','unobserved']
    elif bad=='missing-joint-state':table['anchors'][0]['contexts'][0]['states'].pop()
    elif bad=='nonexhaustive':table['anchors'][0]['contexts'][0]['states'][0]['allocation']=[.2,.2]
    elif bad=='duplicate-state':table['anchors'][0]['contexts'][0]['states'][1]['cells']=['inner','inner']
    elif bad=='unknown-context':data['events'][0]['context_id']='unknown'
    elif bad=='extra-context':table['anchors'][0]['contexts'].append({**copy.deepcopy(table['anchors'][0]['contexts'][0]),'id':'unused'})
    elif bad=='charged':data['events'][0]['llps'][0]['charge']=1
    elif bad=='negative-mass':data['events'][0]['llps'][0]['mass_GeV']=-1
    elif bad=='wrong-units':data['position_unit']='cm'
    elif bad=='missing-origin':data['events'][0]['llps'][0].pop('origin_mm')
    elif bad=='trajectory':d['geometry']['trajectory']='magnetic_helix'
    elif bad=='overlap-cells':d['geometry']['cells'].append({**d['geometry']['cells'][0],'id':'overlap'})
    elif bad=='wrong-weight':data['events'][0]['weights']['nominal']=True
    elif bad=='wrong-dependence':d['decay_assumption']='unknown_correlated_decays'
    elif bad=='bool-lifetime':d['anchors'][0]['ctau_mm']=True
    elif bad=='role-order':data['events'][0]['llps'].reverse()
    refresh(d['events'],data);refresh(d['joint_response'],table)
    with pytest.raises((ValueError,KeyError)):execute(tmp_path,d)


def test_source_and_authenticated_copy_mutation_are_refused(tmp_path,monkeypatch):
    from ravel.physics import reconstructed_events as re
    d=fixed(tmp_path);original=re.run
    def changed(task,base,out,**kwargs):
        result=original(task,base,out,**kwargs);Path(task['events']).write_text('[]');return result
    monkeypatch.setattr(re,'run',changed)
    with pytest.raises(ValueError):execute(tmp_path,d)


def test_ending_original_source_mutation_cannot_be_hidden_by_staging(tmp_path,monkeypatch):
    from ravel.physics import reconstructed_events as re
    d=fixed(tmp_path);original=re.run
    def changed(task,base,out,**kwargs):
        result=original(task,base,out,**kwargs);Path(d['selection']['path']).write_text('{}');return result
    monkeypatch.setattr(re,'run',changed)
    with pytest.raises(ValueError,match='changed'):execute(tmp_path,d)


def test_input_hash_revalidation_and_no_overwrite(tmp_path):
    d=fixed(tmp_path);t=request(tmp_path,d)
    dr.inputs(t,tmp_path);Path(d['anchors'][1]['events']['path']).write_text('[]')
    with pytest.raises(ValueError,match='pin'):dr.run(t,tmp_path,tmp_path/'new')
    d=fixed(tmp_path);t=request(tmp_path,d);(tmp_path/'existing').mkdir()
    with pytest.raises(ValueError,match='fresh'):dr.run(t,tmp_path,tmp_path/'existing')


def test_normalized_shared_denominator_includes_rejected_events(tmp_path):
    d=fixed(tmp_path);d['normalization']={'scale':10.,'denominator':'sum_original_weights','fixed_denominator':None,'meaning':'ratio of complete input weighted sums'}
    details,_=execute(tmp_path,d)
    assert details['weights']['nominal']['normalized_values']==[5.,5.,5.,5.]
    c=details['weights']['nominal']['conditional_group_covariance']
    assert c[0][0]==pytest.approx(12.5)
    assert c[0][1]==pytest.approx(-12.5)
    assert c[0][2]==pytest.approx(-12.5)
    assert 'delta' in details['weights']['nominal']['moment_scope']


def test_full_cartesian_interactions_not_one_axis_at_a_time(tmp_path):
    d=fixed(tmp_path);d['axes'].append({'name':'second','knots':[0,1]});d['reference_point']['second']=0
    old=copy.deepcopy(d['anchors']);d['anchors']=[{**copy.deepcopy(a),'point':[a['point'][0],v]} for a in old for v in [0,1]]
    for i,a in enumerate(d['anchors']):
        a['events']=write(tmp_path,f'joint-{i}.json',json.loads(Path(a['events']['path']).read_text()))
    details,_=execute(tmp_path,d)
    assert len(details['anchor_records'])==4
    # A missing corner is not inferred from one-dimensional anchors.
    d['anchors'].pop()
    with pytest.raises(ValueError,match='Cartesian'):dr.inputs(request(tmp_path,d),tmp_path)


def test_schema_no_hidden_default_or_covariance_to_law(tmp_path):
    d=fixed(tmp_path);d['infer_sampling_law']=True
    with pytest.raises(ValueError):dr.inputs(request(tmp_path,d),tmp_path)


def test_work_bound_applies_before_quadratic_moments(tmp_path):
    d=fixed(tmp_path)
    rows=[[{'event_id':str(i),'group_id':str(i),'weights':{'nominal':1},'allocation':[1,0]} for i in range(2000)] for a in d['anchors']]
    # Add many named weights without silently dropping their joint covariance.
    for anchor in rows:
        for r in anchor:r['weights']={str(i):1. for i in range(20)}
    d['weight_name']='0'
    with pytest.raises(ValueError,match='two million'):dr.summarize(d,['SR','reject'],rows)


def numerical_deck(d):
    return {'schema_version':1,'kind':'numerical-reference-deck',
      'context':{'quantity':'conditional selected weighted event marks','model':'synthetic control','process':'no physical process simulated','normalization':d['normalization']['meaning'],'domain':'supplied two-anchor engineering control','basis':'complete selected/rejected destinations'},
      'axes':[{'id':'shift','unit':'declared nuisance coordinate'}],
      'components':[{'id':'selected','unit':'weighted event','convention':'exact_binary64_value_not_a_certified_error_enclosure','atol':'0','rtol':'0'},
                    {'id':'rejected','unit':'weighted event','convention':'exact_binary64_value_not_a_certified_error_enclosure','atol':'0','rtol':'0'}],
      'training_points':[{'id':'nominal','coordinates':['0']}], 'heldout_points':[{'id':'variation','coordinates':['1']}]}




@pytest.mark.parametrize('bad',['renamed-physical-point','partial-component','normalization','alias-component','wrong-convention','missing-heldout'])
def test_calibration_comparison_projection_preserves_scope_and_complete_exposure(tmp_path,bad):
    d=fixed(tmp_path);deck=numerical_deck(d);mapping={'selected':'SR','rejected':'__rejected__'}
    if bad=='renamed-physical-point':deck['heldout_points'][0]['coordinates']=['2']
    elif bad=='partial-component':deck['components'].pop();mapping.pop('rejected')
    elif bad=='normalization':deck['context']['normalization']='other scale'
    elif bad=='alias-component':mapping['rejected']='SR'
    elif bad=='wrong-convention':deck['components'][0]['convention']='exact physical calibration'
    elif bad=='missing-heldout':deck['heldout_points']=[]
    d['numerical_projection']={'deck':write(tmp_path,'deck.json',deck),'component_map':mapping}
    with pytest.raises(ValueError):execute(tmp_path,d)


def test_zero_llp_complete_rejected_event_and_signed_census(tmp_path):
    d=llp(tmp_path,False);data=json.loads(Path(d['events']['path']).read_text());table=json.loads(Path(d['joint_response']['path']).read_text())
    data['events'].append({'event_id':'empty','group_id':'g2','weights':{'nominal':-1.},'context_id':'empty','llps':[]})
    for anchor in table['anchors']:anchor['contexts'].append({'id':'empty','llp_count':0,'llp_ids':[],'states':[{'cells':[],'allocation':[0.,1.]}]})
    refresh(d['events'],data);refresh(d['joint_response'],table);details,_=execute(tmp_path,d)
    assert details['events']==2 and details['anchor_records'][0][1]['allocation']==[0.,1.]
    assert details['group_marks']['nominal']['g2']==[0.,-1.,0.,-1.,-1.]


def test_longitudinal_exit_limits_true_geometric_shell():
    p=particle(momentum=(100.,0.,100.));g=geometry();g['cells'][0]['z_max']=15.
    # x=z lab trajectory: shell intersects x=10 through15 only; proper
    # distance = x*m/px. This is not an eta-only efficiency shortcut.
    assert dr.decay_probabilities(p,g,10)['inner']==pytest.approx(math.exp(-1)-math.exp(-1.5))


def test_disjoint_shell_complete_partition_and_support_boundary():
    g=geometry();g['cells'].append({'id':'outer','r_min':20.,'r_max':30.,'z_min':-30.,'z_max':30.})
    v=dr.decay_probabilities(particle(),g,10.)
    assert v['inner']==pytest.approx(math.exp(-1)-math.exp(-2))
    assert v['outer']==pytest.approx(math.exp(-2)-math.exp(-3))
    assert v['outside']==pytest.approx(1-math.exp(-1)+math.exp(-3))


def test_non_smooth_category_law_is_retained_without_fake_profiler_compatibility(tmp_path):
    d=fixed(tmp_path);d['axes'][0]['knots']=[0,1,2];last=copy.deepcopy(d['anchors'][1]);last['point']=[2]
    last['events']=write(tmp_path,'events2.json',json.loads(Path(last['events']['path']).read_text()));d['anchors'].append(last)
    s=support(d)
    for c in s['categories']:c['allocation_at_anchors'].append(copy.deepcopy(c['allocation_at_anchors'][-1]))
    d['category_support']=write(tmp_path,'support.json',s);details,out=execute(tmp_path,d)
    assert not details['existing_marked_MC_handoff']['existing_provider_smoothness_compatible']
    law=json.loads((out/'marked-response.json').read_text())
    assert mr.evaluate(law,{'a':.4,'b':.2,'zero':.2,'unobserved':.2},{'shift':1})['nondifferentiable_axes']==['shift']
    with pytest.raises(ValueError,match='nonsmooth'):mp.smooth_mark_law(law)


def test_true_ordinary_plan_retains_complete_input_closure_no_approval_or_execution(tmp_path):
    d=fixed(tmp_path);t=request(tmp_path,d)
    actors={k:'PENDING-'+k for k in ('proposer','executor','physics_critic','skeptical_verifier','physics_decider')}
    policy={'schema_version':1,'actors':actors,'max_redos':0,'allowed_changed_paths':[], 'allowed_stages':['science'],
      'required_checks':[{'id':'complete_source','kind':'integrity'}], 'claim_scopes':{'response_construction':{'checks':['complete_source'],'actions':['delivery']}}}
    spec={'schema_version':2,'mode':'domain','source':'explicit synthetic fixed-event response control','assumptions':['Engineering construction only, no scientific calibration or likelihood inferred.'],
      'max_seconds':30,'approval_mode':'scripted_yes','max_attempts':1,'task':{'domain':'detector-response','config':t},
      'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    pin=write(tmp_path,'ordinary.json',spec);root=tmp_path/'ordinary-study';plan=science.plan(root,pin['path'])
    assert plan['schema_version']==2 and not (root/'inputs/science-approval.json').exists() and not (root/'outputs').exists()
    assert set(science.task_inputs(spec,tmp_path))==set(dr.inputs(t,tmp_path))
    science.verify_plan(root,approved=False)
    Path(d['anchors'][0]['events']['path']).write_text('[]')
    with pytest.raises(ValueError):science.verify_plan(root,approved=False)


def calibrated_llp(base):
    d=llp(base);table=json.loads(Path(d['joint_response']['path']).read_text())
    evidence=write(base,'calibration-evidence.json',{'kind':'synthetic conditional event calibration control','no_physical_calibration':True})
    cells=[]
    for anchor in table['anchors']:
        for row in anchor['contexts'][0]['states']:
            role=dict(zip(['cell_X','cell_Y'],row['cells']))
            row.pop('allocation');row['calibration_context']=role
            if anchor['point']==[10.]:
                p=.3 if all(x=='inner' for x in row['cells']) else 0.
                cells.append({'context':role,'mc':{'SR':p,'__rejected__':1-p},'data':{'SR':2*p,'__rejected__':1-2*p}})
    calibration={'quantity':'absolute_joint_data_and_mc_probabilities','calibration_evidence_sha256':evidence['sha256'],'exhaustive_mutually_exclusive':True,'conditioning_fields':['cell_X','cell_Y'],'cells':cells}
    refresh(d['joint_response'],table)
    d['joint_calibration']={'table':write(base,'joint-calibration.json',calibration),'evidence':evidence,'population':'data'}
    return d


def test_existing_absolute_joint_calibration_is_consumed_not_scale_factor(tmp_path):
    d=calibrated_llp(tmp_path);details,out=execute(tmp_path,d)
    p=math.exp(-1)-math.exp(-2)
    assert details['weights']['nominal']['normalized_values'][0]==pytest.approx(2*.6*p*p)
    assert details['absolute_joint_calibration_population']=='data' and not details['calibration_certified']
    assert (out/'calibration-inputs/table.json').read_bytes()==Path(d['joint_calibration']['table']['path']).read_bytes()
    # The accepted selection SF would equal2, which is NOT a probability.
    from ravel.physics.source_calibration.provider import ArtifactPin,JointCategoricalResponse
    c=d['joint_calibration'];api=JointCategoricalResponse.load(ArtifactPin(c['table']['path'],c['table']['sha256']),evidence=ArtifactPin(c['evidence']['path'],c['evidence']['sha256']))
    context={'cell_X':'inner','cell_Y':'inner'}
    assert api.selection_sf(context,['SR'])==2.
    value=api.absolute_probabilities(context,population='data');assert value['SR']==.6
    value['SR']=99;assert api.absolute_probabilities(context,population='data')['SR']==.6
    assert api.absolute_probabilities(context,population='mc')['SR']==.3
    with pytest.raises(ValueError):api.absolute_probabilities(context,population='unknown')
    Path(c['evidence']['path']).write_text('{}')
    with pytest.raises(ValueError):api.absolute_probabilities(context,population='data')


@pytest.mark.parametrize('bad',['marginal-sf','positive-data-zero-mc','missing-reject','missing-context','wrong-evidence','not-exclusive','wrong-population','extra-allocation','changed-conditioning'])
def test_calibration_reference_contract_is_not_invented_or_factorized(tmp_path,bad):
    d=calibrated_llp(tmp_path);c=d['joint_calibration'];table=json.loads(Path(c['table']['path']).read_text())
    if bad=='marginal-sf':table['quantity']='marginal_scale_factor'
    elif bad=='positive-data-zero-mc':table['cells'][0]['mc']={'SR':0.,'__rejected__':1.}
    elif bad=='missing-reject':
        for cell in table['cells']:cell['mc'].pop('__rejected__');cell['data'].pop('__rejected__')
    elif bad=='missing-context':table['cells'].pop()
    elif bad=='wrong-evidence':table['calibration_evidence_sha256']='0'*64
    elif bad=='not-exclusive':table['exhaustive_mutually_exclusive']=False
    elif bad=='wrong-population':c['population']='sf'
    elif bad=='extra-allocation':
        t=json.loads(Path(d['joint_response']['path']).read_text());t['anchors'][0]['contexts'][0]['states'][0]['allocation']=[.3,.7];refresh(d['joint_response'],t)
    elif bad=='changed-conditioning':table['conditioning_fields']=['other-role']
    refresh(c['table'],table)
    with pytest.raises(ValueError):execute(tmp_path,d)


def test_overlap_signature_migrations_aggregate_without_independent_region_assumption(tmp_path):
    d=fixed(tmp_path,False);details,_=execute(tmp_path,d)
    rows=details['migration_witnesses'][1]['deterministic_joint_signature_transitions']
    assert len(rows)==3 and sum(r['events'] for r in rows)==3
    assert rows[0]=={'from_destinations':['SR','overlap'],'to_destinations':['__rejected__'],'events':1,'sum_original_weights':{'nominal':1.,'twice':2.}}


def test_fractional_response_does_not_invent_stochastic_transition_table(tmp_path):
    details,_=execute(tmp_path,llp(tmp_path))
    assert all(r['deterministic_joint_signature_transitions'] is None for r in details['migration_witnesses'])


@pytest.mark.parametrize('kind',['quadratic-overflow','proper-rate-overflow','proper-rate-underflow'])
def test_unrepresentable_geometry_refuses_instead_of_false_zero(kind):
    p=particle();tau=10.
    if kind=='quadratic-overflow':p['origin_mm']=[1e200,0,0]
    elif kind=='proper-rate-overflow':tau=1e-320
    elif kind=='proper-rate-underflow':p['momentum_GeV']=[1e308,0,0];tau=1e308
    with pytest.raises(ValueError):dr.decay_probabilities(p,geometry(),tau)


def test_binary64_comparison_export_exposes_all_destinations_without_error_certificate(tmp_path):
    from fractions import Fraction
    d=fixed(tmp_path);d['normalization']['scale']=.1;d['normalization']['fixed_denominator']=3.
    deck=numerical_deck(d)
    d['numerical_projection']={'deck':write(tmp_path,'deck.json',deck),'component_map':{'selected':'SR','rejected':'__rejected__'}}
    details,out=execute(tmp_path,d);candidate=json.loads((out/'numerical-point-values.json').read_text())
    assert len(candidate['rows'])==2 and len(candidate['components'])==2
    for row in candidate['rows']:
        assert set(row['values'])=={'selected','rejected'}
        assert Fraction(row['values']['selected']['mid'])==Fraction.from_float(.1/3.)
        assert row['values']['selected']['radius']=='0'
    assert not details['numerical_reference_handoff']['physical_calibration_validated']
    assert 'no certified' in details['numerical_reference_handoff']['scope']


def test_new_response_capability_cannot_create_a_legacy_unreviewed_plan(tmp_path):
    d=fixed(tmp_path);t=request(tmp_path,d)
    spec={'schema_version':1,'mode':'domain','source':'synthetic','assumptions':['no physical claim'],'max_seconds':30,'approval_mode':'scripted_yes',
          'task':{'domain':'detector-response','config':t}}
    p=write(tmp_path,'legacy-source.json',spec)
    with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'legacy-plan',p['path'])
    assert not (tmp_path/'legacy-plan').exists()
